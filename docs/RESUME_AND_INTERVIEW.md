# Resume bullets and interview prep (SpikeLens)

> Every number below comes from `eval/results.md` and `bench/results.md` in this repo. Re-run the scripts
> before an interview and update the numbers if you change the code. Do not claim production use or users
> unless that becomes true (e.g. after deploying and sharing it).

## Resume (Projects section)

**SpikeLens — self-hostable anomaly detection for metrics & logs** (personal project) · Python, FastAPI, NumPy,
scikit-learn, SQLite, Docker, GitHub Actions · `github.com/sahishnu111/spikelens` · live demo: _<add after deploy>_

- Built a FastAPI + vanilla-JS web app that ingests CSV/JSON time series, raw nginx/apache logs, or streaming
  points via API keys, flags anomalies with a plain-English reason per point, and sends Slack-compatible webhook alerts.
- Implemented rolling median/MAD, EWMA control-chart and seasonal-decomposition detectors from scratch (FFT
  autocorrelation for automatic period detection) plus an Isolation Forest baseline; a seasonal-aware voting
  ensemble raised F1 from 0.00 (plain rolling z-score) to 0.80–0.96 on seeded synthetic seasonal benchmarks.
- Wrote streaming detectors (sorted-window median/MAD, O(1) EWMA) that match the batch results exactly
  (tested); measured 224K points/s single-core and 2.8 ms p50 / 3.7 ms p95 for 100-point ingest requests with SQLite.
- Evaluated honestly on 8 labelled series from the public NAB benchmark (94% of incident windows caught,
  0.32 flag precision), with 44 pytest tests, ruff, and a GitHub Actions pipeline (tests, eval, Docker build).

(Shorter variant if space is tight: keep bullets 1–3.)

## What you must be able to explain

### Statistics / algorithms
- **Median and MAD**: why robust (50% breakdown point), why `1.4826·MAD ≈ σ` for Gaussian data, what happens
  when MAD = 0 and the fallback used here (mean absolute deviation, std floor).
- **Robust z-score** vs classic z-score; why we use only *past* points (no self-masking, streaming == batch).
- **EWMA**: the recurrence, what α controls (memory ≈ 1/α points), why variance uses a slower β, why flagged
  points don't update state, how a level shift is eventually adopted.
- **Seasonality**: autocorrelation function, why the first ACF peak ≈ period, why detrend first, computing ACF
  with FFT in O(n log n) (Wiener–Khinchin), harmonic refinement; STL idea (trend + seasonal + residual).
- **Isolation Forest**: random splits isolate outliers in fewer steps; average path length → score; contamination parameter.
- **Ensembles / voting**: why agreement raises precision; the ±1 tolerance.
- **Precision / recall / F1**, tolerance windows, event-level vs point-level metrics, why NAB precision is low,
  the threshold (sensitivity) tradeoff and ROC/PR curves.

### Data structures / complexity
- Rolling median options: sort each window O(w log w); **two heaps** with lazy deletion O(log w); **sorted list
  + bisect** (used here) O(log w) search + O(w) shift; order-statistic tree / skip list O(log w).
- How MAD is computed from the sorted window with a two-pointer merge (k-th smallest of two sorted runs).
- Why window 1000 is ~12x slower than window 60 in the benchmark.

### Backend / systems
- **FastAPI / ASGI**: async vs sync endpoints (sync ones run in a threadpool), pydantic validation, dependency
  of response models, background tasks for webhooks, middleware for metrics.
- **API design**: resource naming, status codes (201, 401, 413, 422), API-key auth in a header, storing only a
  hash, idempotency/retries for ingest, batching to amortize per-request overhead (1 vs 100 points/request numbers).
- **SQLite**: WAL mode, single writer, transactions, indexes, why fine for one node and when to move to Postgres.
- **Docker**: slim base, non-root user, `$PORT`, healthcheck, layer caching (requirements before code).
- **CI**: what the GitHub Actions jobs do, matrix builds, why lint + tests + container smoke test.
- **Streaming vs batch**: state per stream, warm-up after restart, what breaks with multiple workers (sticky
  routing / external state), backpressure.
- **Prometheus** text format, counters vs histograms, why the app exposes `/metrics` itself.
- Security: upload size limits, webhook SSRF risk (why the public demo disables webhooks).

## Likely interview questions
1. Why median/MAD instead of mean/std? What is the breakdown point? What did you do when MAD was 0?
2. Walk me through detecting the period of a series. Why might ACF pick a multiple of the true period?
3. How does your streaming median work, and what is its complexity? How would you make MAD O(log w)?
4. Your NAB precision is 0.32. Why, and how would you improve it? (change-point detection for level shifts,
   alert dedup into incidents, per-series tuning, better thresholds)
5. How do you know the streaming detector is correct? (equivalence test vs batch, numpy oracle test)
6. What happens if two uvicorn workers handle the same stream?
7. How would you scale ingest to 1M points/s? (batching, partition by stream, columnar store, C++/Rust hot path)
8. How do you choose the sensitivity threshold? What does the precision/recall tradeoff look like?
9. Why FastAPI and SQLite? What would you change for a multi-tenant SaaS?
10. What did the AI agents do, and how did you verify their output? (be specific and honest)
11. Who is the customer, and why wouldn't they just use Grafana alerts? (static thresholds, seasonality, setup cost)
