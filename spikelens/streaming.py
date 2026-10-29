"""Streaming detectors with O(log w) per-point updates.

`RollingMedian` keeps a sorted window (bisect insort / removal), so median lookup is O(1)
and updates are O(log w) comparisons plus an O(w) memmove that is tiny in practice.
`RollingMAD` needs the median of |x - median|; we compute it with a two-pointer merge over
the sorted window in O(w) without allocation-heavy numpy calls (still exact).
"""

from __future__ import annotations

import math
from bisect import bisect_left, insort
from collections import deque
from dataclasses import dataclass

MAD_TO_SIGMA = 1.4826
STD_FLOOR = 0.5  # keep in sync with detectors.STD_FLOOR


class RollingMedian:
    def __init__(self, window: int) -> None:
        if window < 1:
            raise ValueError("window must be >= 1")
        self.window = window
        self._fifo: deque[float] = deque()
        self._sorted: list[float] = []
        self._sum = 0.0
        self._sumsq = 0.0

    def __len__(self) -> int:
        return len(self._fifo)

    def push(self, x: float) -> None:
        self._fifo.append(x)
        insort(self._sorted, x)
        self._sum += x
        self._sumsq += x * x
        if len(self._fifo) > self.window:
            old = self._fifo.popleft()
            del self._sorted[bisect_left(self._sorted, old)]
            self._sum -= old
            self._sumsq -= old * old

    def std(self) -> float:
        """Population std of the window from running sums (O(1))."""
        n = len(self._fifo)
        if n == 0:
            return math.nan
        mean = self._sum / n
        return math.sqrt(max(self._sumsq / n - mean * mean, 0.0))

    def median(self) -> float:
        s, n = self._sorted, len(self._sorted)
        if n == 0:
            return math.nan
        m = n // 2
        return s[m] if n % 2 else (s[m - 1] + s[m]) / 2

    def mean_abs_dev(self, center: float) -> float:
        return sum(abs(v - center) for v in self._sorted) / len(self._sorted) if self._sorted else math.nan

    def mad(self) -> float:
        """Exact median absolute deviation via k-th smallest over two sorted runs."""
        s, n = self._sorted, len(self._sorted)
        if n == 0:
            return math.nan
        med = self.median()
        # left run: med - s[j] for j descending from the split; right run: s[j] - med ascending
        split = bisect_left(s, med)
        i, j = split - 1, split
        k_targets = (n - 1) // 2, n // 2
        out = []
        for k in range(k_targets[1] + 1):
            a = med - s[i] if i >= 0 else math.inf
            b = s[j] - med if j < n else math.inf
            if a <= b:
                v, i = a, i - 1
            else:
                v, j = b, j + 1
            if k in k_targets:
                out.append(v)
        return sum(out) / len(out)


@dataclass
class StreamVerdict:
    value: float
    score: float
    is_anomaly: bool
    reason: str | None


class StreamingRobustZ:
    """Same semantics as detectors.robust_zscore, one point at a time."""

    def __init__(self, window: int = 60, threshold: float = 4.0) -> None:
        self.window = window
        self.threshold = threshold
        self.min_hist = max(5, window // 4)
        self._rm = RollingMedian(window)

    def update(self, x: float) -> StreamVerdict:
        score, reason = 0.0, None
        if len(self._rm) >= self.min_hist:
            med = self._rm.median()
            mad = self._rm.mad() * MAD_TO_SIGMA
            if mad <= 0:  # same fallback as detectors.robust_scale (O(w), only when MAD == 0)
                mad = max(self._rm.mean_abs_dev(med) * 1.2533, self._rm.std())
            mad = max(mad, STD_FLOOR * self._rm.std(), 1e-9 + 1e-6 * abs(med))
            score = abs(x - med) / mad
            if score > self.threshold:
                direction = "above" if x > med else "below"
                reason = (f"value {x:.4g} is {score:.1f} MADs {direction} the rolling median "
                          f"{med:.4g} of the previous {len(self._rm)} points")
        self._rm.push(x)
        return StreamVerdict(x, score, reason is not None, reason)


class StreamingEWMA:
    """O(1) EWMA control chart, same semantics as detectors.ewma."""

    def __init__(self, alpha: float = 0.1, threshold: float = 4.0, warmup: int = 20, var_alpha: float = 0.05) -> None:
        self.alpha, self.threshold, self.warmup, self.var_alpha = alpha, threshold, warmup, var_alpha
        self._buf: list[float] = []
        self.mean = 0.0
        self.var = 0.0
        self._consecutive = 0

    def update(self, x: float) -> StreamVerdict:
        if len(self._buf) < self.warmup:
            self._buf.append(x)
            if len(self._buf) == self.warmup:
                n = len(self._buf)
                self.mean = sum(self._buf) / n
                self.var = sum((v - self.mean) ** 2 for v in self._buf) / n + 1e-12
            return StreamVerdict(x, 0.0, False, None)
        std = max(math.sqrt(self.var), 1e-9 + 1e-6 * abs(self.mean))
        dev = x - self.mean
        z = abs(dev) / std
        reason = None
        if z > self.threshold:
            self._consecutive += 1
            reason = f"value {x:.4g} deviates {z:.1f} sigma from the EWMA mean {self.mean:.4g} (alpha={self.alpha})"
            if self._consecutive < self.warmup:
                return StreamVerdict(x, z, True, reason)
        else:
            self._consecutive = 0
        self.mean += self.alpha * dev
        self.var = (1 - self.var_alpha) * (self.var + self.var_alpha * dev * dev)
        return StreamVerdict(x, z, reason is not None, reason)
