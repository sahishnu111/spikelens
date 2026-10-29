"""Minimal Prometheus text-format exporter (no client library needed)."""

from __future__ import annotations

import threading
from collections import defaultdict

BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, float("inf"))


class Metrics:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.counters: dict[str, float] = defaultdict(float)
        self.requests: dict[tuple[str, str, int], int] = defaultdict(int)
        self.hist: dict[str, list[int]] = defaultdict(lambda: [0] * len(BUCKETS))
        self.hist_sum: dict[str, float] = defaultdict(float)

    def inc(self, name: str, v: float = 1) -> None:
        with self._lock:
            self.counters[name] += v

    def observe_request(self, method: str, path: str, status: int, seconds: float) -> None:
        with self._lock:
            self.requests[(method, path, status)] += 1
            h = self.hist[path]
            for i, b in enumerate(BUCKETS):
                if seconds <= b:
                    h[i] += 1
            self.hist_sum[path] += seconds

    def render(self) -> str:
        out = []
        with self._lock:
            for name in sorted(self.counters):
                out += [f"# TYPE {name} counter", f"{name} {self.counters[name]:g}"]
            out.append("# TYPE spikelens_http_requests_total counter")
            for (m, p, s), c in sorted(self.requests.items()):
                out.append(f'spikelens_http_requests_total{{method="{m}",path="{p}",status="{s}"}} {c}')
            out.append("# TYPE spikelens_http_request_duration_seconds histogram")
            for p, h in sorted(self.hist.items()):
                for b, c in zip(BUCKETS, h, strict=True):
                    le = "+Inf" if b == float("inf") else f"{b:g}"
                    out.append(f'spikelens_http_request_duration_seconds_bucket{{path="{p}",le="{le}"}} {c}')
                out.append(f'spikelens_http_request_duration_seconds_sum{{path="{p}"}} {self.hist_sum[p]:.6f}')
                out.append(f'spikelens_http_request_duration_seconds_count{{path="{p}"}} {h[-1]}')
        return "\n".join(out) + "\n"


METRICS = Metrics()
