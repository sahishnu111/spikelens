Machine: x86_64, 8 vCPU, Python 3.13.5 (single uvicorn worker, SQLite WAL)

| streaming detector | points/sec |
|---|---|
| robust_z (window=60) | 223,714 |
| robust_z (window=1000) | 18,297 |
| ewma | 3,310,251 |

| batch detector (10k points) | seconds |
|---|---|
| robust_z | 0.267 |
| ewma | 0.007 |
| seasonal | 0.044 |
| iforest | 0.918 |
| ensemble | 0.452 |

| API endpoint | p50 ms | p95 ms | throughput |
|---|---|---|---|
| ingest_batch_1 | 1.42 | 2.12 | 637 pts/s |
| ingest_batch_100 | 2.82 | 3.65 | 30198 pts/s |
| analyze_1440_ensemble | 140.63 | 179.99 | - |
