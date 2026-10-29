"""Deterministic synthetic series with injected, labelled anomalies (for demo, tests, eval)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import numpy as np


@dataclass
class Synthetic:
    timestamps: list[str]
    values: list[float]
    labels: list[bool]
    kind: str


def make_series(n: int = 1440, period: int = 60, kind: str = "spikes", seed: int = 0,
                noise: float = 1.0, amplitude: float = 10.0) -> Synthetic:
    """kind in {spikes, level_shift, seasonal_break, mixed}."""
    rng = np.random.default_rng(seed)
    t = np.arange(n)
    base = 50 + amplitude * np.sin(2 * np.pi * t / period) + rng.normal(0, noise, n)
    labels = np.zeros(n, dtype=bool)
    lo = 2 * period  # leave history for warm-up
    if kind in ("spikes", "mixed"):
        idx = rng.choice(np.arange(lo, n), size=max(3, n // 200), replace=False)
        sign = rng.choice([-1, 1], size=len(idx))
        base[idx] += sign * rng.uniform(6, 10, len(idx)) * noise
        labels[idx] = True
    if kind in ("level_shift", "mixed"):
        s = int(rng.integers(lo, n - 50))
        base[s:] += 8 * noise
        labels[s : s + 3] = True  # the change point and its first few points
    if kind in ("seasonal_break", "mixed"):
        s = int(rng.integers(lo, n - period))
        # one cycle where the seasonal pattern is inverted
        seg = slice(s, s + period // 2)
        base[seg] -= 2 * amplitude * np.sin(2 * np.pi * t[seg] / period)
        resid = np.abs(2 * amplitude * np.sin(2 * np.pi * t[seg] / period))
        labels[seg] |= resid > 4 * noise
    start = datetime(2026, 1, 1, tzinfo=UTC)
    ts = [(start + timedelta(minutes=int(i))).isoformat() for i in t]
    return Synthetic(ts, [round(float(v), 4) for v in base], labels.tolist(), kind)


def demo_log_lines(minutes: int = 240, seed: int = 1) -> list[str]:
    """nginx combined lines with an error burst and a traffic drop."""
    rng = np.random.default_rng(seed)
    start = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    lines = []
    for m in range(minutes):
        rate = 40 + 15 * np.sin(2 * np.pi * m / 60)
        if 150 <= m < 156:
            rate *= 0.1  # outage
        k = int(rng.poisson(rate))
        err_p = 0.6 if 90 <= m < 94 else 0.01
        for _ in range(k):
            ts = start + timedelta(minutes=m, seconds=float(rng.uniform(0, 59.9)))
            status = 500 if rng.random() < err_p else 200
            path = rng.choice(["/", "/api/items", "/login", "/static/app.js"])
            lines.append(f'10.0.0.{rng.integers(1, 255)} - - [{ts.strftime("%d/%b/%Y:%H:%M:%S +0000")}] '
                         f'"GET {path} HTTP/1.1" {status} {rng.integers(200, 5000)} "-" "demo"')
    lines.sort(key=lambda s: s.split("[")[1][:20])
    return lines
