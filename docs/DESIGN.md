# SpikeLens design doc

## Goal
Give a small team a one-container tool that answers "which points in this metric/log are weird, and why?"
for both uploaded files (batch) and live points (streaming), without hand-tuned thresholds.

## Non-goals
Long-term metric storage, dashboards-as-code, multi-tenant auth, tracing. Use Prometheus/Grafana/Datadog for those.

## Data flow
1. **Ingest**: `/api/upload` (CSV/JSON/log), `/api/analyze` (JSON), `/api/streams/ingest` (API key).
2. **Normalize**: logs are parsed line by line (regex for combined format, ISO-timestamp + level for generic
   lines) and bucketed to 60 s. Empty buckets are emitted as 0 so outages are visible. NaNs are forward-filled.
3. **Detect** (batch): `run_detector(name, values, sensitivity)`; `sensitivity` divides the base threshold
   of 4 robust sigmas (and scales the Isolation Forest contamination).
4. **Explain**: each detector returns `scores`, `flags`, and a `reasons` dict {index: sentence} built from the
   same statistics used to decide (median, MAD, expected value = trend + seasonal, EWMA mean/sigma).
5. **Stream**: per-stream detector object kept in memory, warmed from the last `max(window, 200)` stored points
   on first use; each ingest request is scored, written in one SQLite transaction, and anomalies trigger a
   background webhook POST (failures are counted, never fail the ingest).

## Algorithms
| detector | idea | cost |
|---|---|---|
| robust z | `|x_t - median(x_{t-w..t-1})| / (1.4826·MAD)` | batch O(n·w log w) numpy; streaming O(log w) insert + O(w) MAD |
| EWMA | `m += α(x-m)`, `v = (1-β)(v + β(x-m)^2)`, flag if `|x-m| > k·sqrt(v)`; flagged points don't update state (until a run of `warmup` flags, then the new level is adopted) | O(1) |
| period | FFT autocorrelation of the linearly-detrended series, first local max > 0.3, refined with the 2nd/3rd harmonic peaks | O(n log n) |
| seasonal residual | trend = rolling median (window ≈ period), seasonal = per-phase median of detrended values, robust z on residual | O(n·p) |
| Isolation Forest | sklearn, features `[x, Δx, x - local mean]`, contamination 1% | O(n log n) |
| ensemble | deseasonalize if a period exists, run all 4, dilate flags by ±1, flag where ≥ 2 vote | sum of members |

## Key decisions
- **Past-only windows** → batch == streaming (asserted in tests), no self-masking.
- **Scale fallbacks** for MAD = 0 (sparse series): max(1.2533·meanAD, std), floored at 0.5·std overall.
- **Sorted list vs two heaps**: exact median + MAD from one structure, no lazy deletion; O(w) memmove accepted.
- **API keys**: random 32-byte urlsafe tokens, only SHA-256 stored; keys are per stream.
- **SQLite WAL** with a process-level lock around a single connection: simplest correct option for one worker.
- **Webhook payload** is Slack-compatible (`text`) plus structured `anomalies` for other receivers;
  webhooks can be disabled for public demos (`SPIKELENS_ALLOW_WEBHOOKS=0`) to avoid the server being used to send requests to arbitrary URLs.

## Evaluation methodology
- Synthetic: `synthetic.make_series` with fixed seeds 0–9; labels are the injected points; ±2 point tolerance.
- NAB: 8 series downloaded from the public NAB GitHub repo; window-based recall/precision (not the NAB score).
- Benchmarks: `bench/bench.py` (streaming points/s on 200k points; API latency against a real uvicorn process).

## Risks / next steps
Level-shift false positives (add CUSUM change-point detection), multi-seasonality, horizontal scaling (move
streaming state to Redis or shard by stream id), auth for multi-user deployments.
