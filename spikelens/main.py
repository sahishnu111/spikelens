"""FastAPI app: batch analysis, uploads, streaming ingest with API keys, webhooks, /metrics."""

from __future__ import annotations

import csv
import io
import json
import logging
import os
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated
from urllib.parse import urlparse

import httpx
from fastapi import BackgroundTasks, FastAPI, File, Form, Header, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles

from . import __version__
from .db import Database
from .detectors import detect_period, precision_recall, run_detector
from .logparse import logs_to_series
from .metrics import METRICS
from .schemas import AnalyzeRequest, AnalyzeResponse, Anomaly, IngestRequest, StreamCreate
from .streaming import StreamingEWMA, StreamingRobustZ
from .synthetic import demo_log_lines, make_series

log = logging.getLogger("spikelens")
STATIC = Path(__file__).parent / "static"
MAX_UPLOAD_BYTES = int(os.environ.get("SPIKELENS_MAX_UPLOAD_MB", "10")) * 1024 * 1024
ALLOW_WEBHOOKS = os.environ.get("SPIKELENS_ALLOW_WEBHOOKS", "1") == "1"

app = FastAPI(title="SpikeLens", version=__version__,
              description="Lightweight, self-hostable anomaly detection for metrics and logs.")
db = Database()
_detectors: dict[int, StreamingRobustZ | StreamingEWMA] = {}


@app.middleware("http")
async def _metrics_mw(request: Request, call_next):  # type: ignore[no-untyped-def]
    t0 = time.perf_counter()
    response = await call_next(request)
    route = request.scope.get("route")
    path = getattr(route, "path", "unmatched")
    METRICS.observe_request(request.method, path, response.status_code, time.perf_counter() - t0)
    return response


# --------------------------------------------------------------------------- helpers
def analyze(req: AnalyzeRequest) -> AnalyzeResponse:
    res = run_detector(req.detector, req.values, sensitivity=req.sensitivity, period=req.period)
    anomalies = [
        Anomaly(index=i, timestamp=req.timestamps[i] if req.timestamps else None, value=req.values[i],
                score=round(res.scores[i], 4), reason=res.reasons.get(i, "flagged"))
        for i in res.anomaly_indices
    ]
    metrics = precision_recall(res.flags, req.labels, tolerance=2) if req.labels else None
    period = res.params.get("period")
    METRICS.inc("spikelens_points_analyzed_total", len(req.values))
    METRICS.inc("spikelens_anomalies_found_total", len(anomalies))
    return AnalyzeResponse(
        detector=res.detector, params=res.params, n_points=len(req.values), timestamps=req.timestamps,
        values=req.values, scores=[round(s, 4) for s in res.scores], anomalies=anomalies, metrics=metrics,
        detected_period=period if isinstance(period, int) else detect_period(req.values),
    )


def _float(s: str) -> float | None:
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def parse_tabular(text: str, filename: str) -> tuple[list[str] | None, list[float], list[bool] | None]:
    """CSV with a numeric value column (+ optional timestamp/label columns) or JSON."""
    if filename.endswith(".json") or text.lstrip().startswith(("[", "{")):
        data = json.loads(text)
        if isinstance(data, dict):
            vals = data.get("values")
            if vals is None:
                raise ValueError("JSON object must contain 'values'")
            return data.get("timestamps"), [float(v) for v in vals], data.get("labels")
        if data and isinstance(data[0], dict):
            vk = next((k for k in ("value", "values", "y") if k in data[0]), None)
            if vk is None:
                raise ValueError("JSON rows need a 'value' field")
            tk = next((k for k in ("timestamp", "ts", "time") if k in data[0]), None)
            lk = next((k for k in ("label", "is_anomaly", "anomaly") if k in data[0]), None)
            return ([str(r[tk]) for r in data] if tk else None, [float(r[vk]) for r in data],
                    [bool(int(r[lk])) for r in data] if lk else None)
        return None, [float(v) for v in data], None
    rows = list(csv.reader(io.StringIO(text)))
    rows = [r for r in rows if r]
    if not rows:
        raise ValueError("empty file")
    header = [h.strip().lower() for h in rows[0]]
    has_header = any(_float(h) is None for h in rows[0])
    body = rows[1:] if has_header else rows
    if has_header:
        vi = next((header.index(k) for k in ("value", "values", "y", "count") if k in header), None)
        if vi is None:  # first numeric column
            vi = next(i for i, c in enumerate(body[0]) if _float(c) is not None)
        ti = next((header.index(k) for k in ("timestamp", "ts", "time", "date") if k in header), None)
        li = next((header.index(k) for k in ("label", "is_anomaly", "anomaly") if k in header), None)
    else:
        vi = len(body[0]) - 1
        ti = 0 if len(body[0]) > 1 else None
        li = None
    vals, ts, labels = [], [], []
    for r in body:
        v = _float(r[vi]) if vi < len(r) else None
        if v is None:
            continue
        vals.append(v)
        if ti is not None:
            ts.append(r[ti])
        if li is not None:
            labels.append(r[li].strip().lower() in ("1", "true", "yes"))
    return (ts or None), vals, (labels or None)


def _check_webhook(url: str | None) -> str | None:
    if not url:
        return None
    if not ALLOW_WEBHOOKS:
        raise HTTPException(400, "webhooks are disabled on this instance")
    p = urlparse(url)
    if p.scheme not in ("http", "https") or not p.netloc:
        raise HTTPException(422, "webhook_url must be an http(s) URL")
    return url


async def _send_webhook(url: str, stream_name: str, anomalies: list[dict]) -> None:
    lines = [f"- {a['ts']}: {a['reason']}" for a in anomalies[:10]]
    payload = {"text": f":rotating_light: SpikeLens: {len(anomalies)} anomaly(ies) on `{stream_name}`\n" + "\n".join(lines),
               "stream": stream_name, "anomalies": anomalies}
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.post(url, json=payload)
        METRICS.inc("spikelens_webhooks_sent_total", 1)
        log.info("webhook %s -> %s", url, r.status_code)
    except httpx.HTTPError as e:  # never fail ingest because of an alert
        METRICS.inc("spikelens_webhook_errors_total", 1)
        log.warning("webhook failed: %s", e)


def _detector_for(row) -> StreamingRobustZ | StreamingEWMA:  # type: ignore[no-untyped-def]
    sid = int(row["id"])
    if sid not in _detectors:
        d: StreamingRobustZ | StreamingEWMA = (
            StreamingRobustZ(window=row["win"], threshold=row["threshold"]) if row["detector"] == "robust_z"
            else StreamingEWMA(threshold=row["threshold"])
        )
        for p in db.points(sid, limit=max(row["win"], 200)):  # warm state after a restart
            d.update(p["value"])
        _detectors[sid] = d
    return _detectors[sid]


# --------------------------------------------------------------------------- routes
@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "version": __version__}


@app.get("/api/detectors")
def detectors() -> dict:
    return {"detectors": [
        {"name": "auto", "desc": "ensemble; if autocorrelation finds a period, members see the deseasonalized series"},
        {"name": "ensemble", "desc": "majority vote (>=2 of 4) of the detectors below"},
        {"name": "robust_z", "desc": "rolling median/MAD robust z-score over the previous 60 points"},
        {"name": "ewma", "desc": "EWMA control chart (mean alpha=0.1, variance alpha=0.05)"},
        {"name": "seasonal", "desc": "trend + seasonal profile decomposition, robust z on the residual"},
        {"name": "iforest", "desc": "scikit-learn Isolation Forest baseline on value/diff/local-deviation"},
    ]}


@app.post("/api/analyze", response_model=AnalyzeResponse)
def analyze_route(req: AnalyzeRequest) -> AnalyzeResponse:
    try:
        return analyze(req)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e


@app.post("/api/export")
def export(req: AnalyzeRequest, format: Annotated[str, Query(pattern="^(csv|json)$")] = "csv") -> Response:
    res = analyze(req)
    rows = [a.model_dump() for a in res.anomalies]
    if format == "json":
        return Response(json.dumps(rows, indent=2), media_type="application/json",
                        headers={"Content-Disposition": "attachment; filename=anomalies.json"})
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=["index", "timestamp", "value", "score", "reason"])
    w.writeheader()
    w.writerows(rows)
    return PlainTextResponse(buf.getvalue(), media_type="text/csv",
                             headers={"Content-Disposition": "attachment; filename=anomalies.csv"})


@app.post("/api/upload", response_model=AnalyzeResponse)
async def upload(file: Annotated[UploadFile, File()],
                 kind: Annotated[str, Form(pattern="^(auto|series|logs)$")] = "auto",
                 detector: Annotated[str, Form()] = "auto",
                 sensitivity: Annotated[float, Form()] = 1.0,
                 log_metric: Annotated[str, Form(pattern="^(count|error_rate|errors)$")] = "count") -> AnalyzeResponse:
    raw = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "file too large")
    text = raw.decode("utf-8", errors="replace")
    name = (file.filename or "").lower()
    is_logs = kind == "logs" or (kind == "auto" and (name.endswith((".log", ".txt")) or "HTTP/1." in text[:2000]))
    try:
        if is_logs:
            s = logs_to_series(text.splitlines())
            if len(s.counts) < 3:
                raise ValueError(f"could not parse enough log lines (parsed {s.parsed}, skipped {s.skipped})")
            values = {"count": s.counts, "errors": s.errors, "error_rate": s.error_rate}[log_metric]
            req = AnalyzeRequest(values=[float(v) for v in values], timestamps=s.timestamps,
                                 detector=detector, sensitivity=sensitivity)  # type: ignore[arg-type]
        else:
            ts, vals, labels = parse_tabular(text, name)
            req = AnalyzeRequest(values=vals, timestamps=ts, labels=labels,
                                 detector=detector, sensitivity=sensitivity)  # type: ignore[arg-type]
        return analyze(req)
    except (ValueError, KeyError, StopIteration, json.JSONDecodeError) as e:
        raise HTTPException(422, f"could not parse file: {e}") from e


@app.get("/api/demo")
def demo(kind: Annotated[str, Query(pattern="^(mixed|spikes|level_shift|seasonal_break|logs)$")] = "mixed") -> dict:
    if kind == "logs":
        s = logs_to_series(demo_log_lines())
        return {"timestamps": s.timestamps, "values": [float(v) for v in s.counts], "labels": None,
                "error_rate": s.error_rate, "description": "nginx access log: requests per minute (error burst at 13:30, outage at 14:30)"}
    syn = make_series(n=1440, period=60, kind=kind, seed=7)
    return {"timestamps": syn.timestamps, "values": syn.values, "labels": syn.labels,
            "description": f"synthetic 1-day per-minute series, hourly seasonality, injected {kind} (labelled)"}


@app.get("/api/demo/logfile", response_class=PlainTextResponse)
def demo_logfile() -> str:
    return "\n".join(demo_log_lines()) + "\n"


@app.post("/api/streams", status_code=201)
def create_stream(body: StreamCreate) -> dict:
    url = _check_webhook(body.webhook_url)
    sid, key = db.create_stream(body.name, body.detector, body.threshold, body.window, url)
    return {"id": sid, "api_key": key, "name": body.name, "detector": body.detector,
            "note": "store the api_key now; only its SHA-256 hash is kept"}


@app.post("/api/streams/ingest")
async def ingest(body: IngestRequest, background: BackgroundTasks,
                 x_api_key: Annotated[str, Header()]) -> dict:
    row = db.stream_by_key(x_api_key)
    if row is None:
        raise HTTPException(401, "invalid API key")
    det = _detector_for(row)
    now = datetime.now(UTC).isoformat()
    out, rows, alerts = [], [], []
    for p in body.points:
        v = det.update(p.value)
        ts = p.ts or now
        rows.append((ts, p.value, round(v.score, 4), v.is_anomaly, v.reason))
        out.append({"ts": ts, "value": p.value, "score": round(v.score, 4), "is_anomaly": v.is_anomaly, "reason": v.reason})
        if v.is_anomaly:
            alerts.append({"ts": ts, "value": p.value, "reason": v.reason})
    db.add_points(int(row["id"]), rows)
    METRICS.inc("spikelens_points_ingested_total", len(rows))
    METRICS.inc("spikelens_anomalies_found_total", len(alerts))
    if alerts and row["webhook_url"]:
        background.add_task(_send_webhook, row["webhook_url"], row["name"], alerts)
    return {"stream_id": row["id"], "accepted": len(rows), "anomalies": len(alerts), "results": out}


@app.get("/api/streams/{stream_id}")
def get_stream(stream_id: int, x_api_key: Annotated[str, Header()], limit: int = Query(2000, le=20000)) -> dict:
    row = db.stream_by_key(x_api_key)
    if row is None or int(row["id"]) != stream_id:
        raise HTTPException(401, "invalid API key for this stream")
    pts = db.points(stream_id, limit)
    return {"id": stream_id, "name": row["name"], "detector": row["detector"],
            "timestamps": [p["ts"] for p in pts], "values": [p["value"] for p in pts],
            "scores": [p["score"] for p in pts],
            "anomalies": [{"ts": p["ts"], "value": p["value"], "score": p["score"], "reason": p["reason"]}
                          for p in pts if p["is_anomaly"]]}


@app.get("/metrics", response_class=PlainTextResponse)
def metrics() -> str:
    return METRICS.render()


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


app.mount("/static", StaticFiles(directory=STATIC), name="static")
