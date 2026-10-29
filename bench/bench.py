"""Throughput + latency benchmark.

1. Streaming detectors: points/sec (pure Python, single core).
2. Batch detectors: wall time on a 10k-point series.
3. API: starts uvicorn on a temp DB, measures /api/streams/ingest latency p50/p95/p99
   for 1-point and 100-point requests, plus /api/analyze on a 1440-point series.

Usage: python bench/bench.py   -> writes bench/results.json and bench/results.md
"""

from __future__ import annotations

import json
import os
import platform
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from spikelens.detectors import run_detector  # noqa: E402
from spikelens.streaming import StreamingEWMA, StreamingRobustZ  # noqa: E402
from spikelens.synthetic import make_series  # noqa: E402


def stream_tput(make, n=200_000) -> float:
    x = np.random.default_rng(0).normal(size=n).tolist()
    d = make()
    t0 = time.perf_counter()
    for v in x:
        d.update(v)
    return n / (time.perf_counter() - t0)


def pct(a, q):
    return round(float(np.percentile(a, q)) * 1000, 2)


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def api_bench() -> dict:
    port = free_port()
    tmp = tempfile.mkdtemp()
    env = {**os.environ, "SPIKELENS_DB": f"{tmp}/bench.db"}
    proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "spikelens.main:app", "--port", str(port), "--log-level", "warning"],
                            cwd=ROOT, env=env)
    base = f"http://127.0.0.1:{port}"
    try:
        for _ in range(100):
            try:
                httpx.get(base + "/api/health", timeout=1)
                break
            except httpx.HTTPError:
                time.sleep(0.1)
        out = {}
        with httpx.Client(base_url=base, timeout=10) as c:
            key = c.post("/api/streams", json={"name": "bench"}).json()["api_key"]
            h = {"x-api-key": key}
            rng = np.random.default_rng(0)
            for batch, reps in ((1, 2000), (100, 500)):
                lat = []
                for _ in range(50):  # warm-up
                    c.post("/api/streams/ingest", json={"points": [{"value": float(v)} for v in rng.normal(size=batch)]}, headers=h)
                t_all = time.perf_counter()
                for _ in range(reps):
                    body = {"points": [{"value": float(v)} for v in rng.normal(size=batch)]}
                    t0 = time.perf_counter()
                    r = c.post("/api/streams/ingest", json=body, headers=h)
                    lat.append(time.perf_counter() - t0)
                    assert r.status_code == 200
                el = time.perf_counter() - t_all
                out[f"ingest_batch_{batch}"] = {"requests": reps, "p50_ms": pct(lat, 50), "p95_ms": pct(lat, 95),
                                                "p99_ms": pct(lat, 99), "points_per_sec": round(reps * batch / el)}
            s = make_series(kind="mixed", seed=0)
            lat = []
            for _ in range(30):
                t0 = time.perf_counter()
                c.post("/api/analyze", json={"values": s.values, "detector": "ensemble"})
                lat.append(time.perf_counter() - t0)
            out["analyze_1440_ensemble"] = {"requests": 30, "p50_ms": pct(lat, 50), "p95_ms": pct(lat, 95)}
        return out
    finally:
        proc.terminate()
        proc.wait()


def main() -> None:
    res: dict = {"machine": f"{platform.processor() or platform.machine()}, {os.cpu_count()} vCPU, Python {platform.python_version()}"}
    res["streaming_points_per_sec"] = {
        "robust_z (window=60)": round(stream_tput(lambda: StreamingRobustZ(window=60))),
        "robust_z (window=1000)": round(stream_tput(lambda: StreamingRobustZ(window=1000))),
        "ewma": round(stream_tput(StreamingEWMA)),
    }
    x = make_series(n=10_000, period=60, kind="mixed", seed=0).values
    res["batch_10k_points_seconds"] = {}
    for d in ("robust_z", "ewma", "seasonal", "iforest", "ensemble"):
        t0 = time.perf_counter()
        run_detector(d, x)
        res["batch_10k_points_seconds"][d] = round(time.perf_counter() - t0, 3)
    res["api"] = api_bench()
    out = Path(__file__).parent
    (out / "results.json").write_text(json.dumps(res, indent=2))
    md = [f"Machine: {res['machine']} (single uvicorn worker, SQLite WAL)", "", "| streaming detector | points/sec |", "|---|---|"]
    md += [f"| {k} | {v:,} |" for k, v in res["streaming_points_per_sec"].items()]
    md += ["", "| batch detector (10k points) | seconds |", "|---|---|"]
    md += [f"| {k} | {v} |" for k, v in res["batch_10k_points_seconds"].items()]
    md += ["", "| API endpoint | p50 ms | p95 ms | throughput |", "|---|---|---|---|"]
    for k, v in res["api"].items():
        md.append(f"| {k} | {v['p50_ms']} | {v['p95_ms']} | {str(v.get('points_per_sec', '-')) + ' pts/s' if 'points_per_sec' in v else '-'} |")
    (out / "results.md").write_text("\n".join(md) + "\n")
    print("\n".join(md))


if __name__ == "__main__":
    main()
