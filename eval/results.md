## Synthetic benchmark (mean over 10 seeds, 1440 points each, ±2-point tolerance)

| scenario | robust_z | ewma | seasonal | iforest | ensemble |
|---|---|---|---|---|---|
| spikes | P 0.00 / R 0.00 / **F1 0.00** | P 0.00 / R 0.00 / **F1 0.00** | P 0.91 / R 0.99 / **F1 0.94** | P 0.59 / R 1.00 / **F1 0.74** | P 0.80 / R 1.00 / **F1 0.88** |
| level_shift | P 0.00 / R 0.00 / **F1 0.00** | P 0.00 / R 0.00 / **F1 0.00** | P 0.20 / R 0.70 / **F1 0.31** | P 0.08 / R 1.00 / **F1 0.15** | P 0.24 / R 1.00 / **F1 0.39** |
| seasonal_break | P 0.00 / R 0.00 / **F1 0.00** | P 0.00 / R 0.00 / **F1 0.00** | P 0.48 / R 0.97 / **F1 0.64** | P 0.23 / R 0.18 / **F1 0.19** | P 0.96 / R 0.96 / **F1 0.96** |
| mixed | P 0.00 / R 0.00 / **F1 0.00** | P 0.00 / R 0.00 / **F1 0.00** | P 0.60 / R 0.93 / **F1 0.72** | P 0.91 / R 0.42 / **F1 0.57** | P 0.70 / R 0.94 / **F1 0.80** |
| spikes (no seasonality) | P 0.91 / R 1.00 / **F1 0.95** | P 0.96 / R 1.00 / **F1 0.98** | P 0.91 / R 1.00 / **F1 0.95** | P 0.53 / R 1.00 / **F1 0.69** | P 0.91 / R 1.00 / **F1 0.95** |
| level_shift (no seasonality) | P 0.30 / R 1.00 / **F1 0.46** | P 0.24 / R 1.00 / **F1 0.39** | P 0.00 / R 0.00 / **F1 0.00** | P 0.11 / R 1.00 / **F1 0.20** | P 0.23 / R 1.00 / **F1 0.38** |
| mixed (no seasonality) | P 0.48 / R 0.98 / **F1 0.65** | P 0.43 / R 0.98 / **F1 0.59** | P 0.49 / R 0.69 / **F1 0.53** | P 0.63 / R 1.00 / **F1 0.77** | P 0.42 / R 1.00 / **F1 0.60** |

## NAB subset (event-window metrics)

window_recall = fraction of labelled anomaly windows containing >=1 flag; flag_precision = fraction of flags inside a window.

| file | windows | robust_z | ewma | seasonal | iforest | ensemble |
|---|---|---|---|---|---|---|
| machine_temperature_system_failure.csv | 4 | R 1.00 / P 0.18 (877 flags) | R 1.00 / P 0.35 (211 flags) | R 1.00 / P 0.18 (877 flags) | R 1.00 / P 0.52 (227 flags) | R 1.00 / P 0.19 (900 flags) |
| nyc_taxi.csv | 5 | R 0.20 / P 0.33 (3 flags) | R 0.00 / P 0.00 (0 flags) | R 1.00 / P 0.11 (746 flags) | R 0.60 / P 0.10 (104 flags) | R 1.00 / P 0.09 (529 flags) |
| ambient_temperature_system_failure.csv | 2 | R 0.50 / P 0.07 (29 flags) | R 0.00 / P 0.00 (7 flags) | R 0.50 / P 0.16 (57 flags) | R 1.00 / P 0.34 (73 flags) | R 0.50 / P 0.20 (45 flags) |
| cpu_utilization_asg_misconfiguration.csv | 1 | R 1.00 / P 0.07 (1593 flags) | R 1.00 / P 0.04 (3499 flags) | R 1.00 / P 0.22 (1213 flags) | R 1.00 / P 0.11 (180 flags) | R 1.00 / P 0.07 (2350 flags) |
| ec2_request_latency_system_failure.csv | 3 | R 1.00 / P 0.56 (23 flags) | R 1.00 / P 0.94 (17 flags) | R 1.00 / P 0.56 (23 flags) | R 1.00 / P 0.39 (41 flags) | R 1.00 / P 0.57 (28 flags) |
| ec2_cpu_utilization_825cc2.csv | 1 | R 1.00 / P 0.42 (89 flags) | R 1.00 / P 0.47 (53 flags) | R 1.00 / P 0.42 (89 flags) | R 1.00 / P 0.66 (41 flags) | R 1.00 / P 0.43 (99 flags) |
| rds_cpu_utilization_cc0c53.csv | 2 | R 1.00 / P 0.29 (68 flags) | R 1.00 / P 0.32 (71 flags) | R 1.00 / P 0.24 (143 flags) | R 1.00 / P 0.41 (41 flags) | R 1.00 / P 0.35 (91 flags) |
| speed_7578.csv | 4 | R 1.00 / P 0.59 (46 flags) | R 1.00 / P 0.60 (47 flags) | R 1.00 / P 0.59 (46 flags) | R 1.00 / P 0.83 (12 flags) | R 1.00 / P 0.62 (53 flags) |
| **mean** | | R 0.84 / P 0.31 / F1 0.41 | R 0.75 / P 0.34 / F1 0.43 | R 0.94 / P 0.31 / F1 0.44 | R 0.95 / P 0.42 / F1 0.55 | R 0.94 / P 0.32 / F1 0.44 |
