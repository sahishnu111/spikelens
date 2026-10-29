"""Batch anomaly detectors.

Every detector takes a 1-D sequence of floats and returns a DetectionResult with a
per-point score (higher = more anomalous, comparable to the threshold), a boolean
flag and a plain-English reason for each flagged point.

The statistics are implemented by hand (rolling median/MAD, EWMA, autocorrelation,
seasonal profile); scikit-learn is used only for the Isolation Forest baseline.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

import numpy as np

MAD_TO_SIGMA = 1.4826  # MAD * 1.4826 ~= std-dev for Gaussian data
STD_FLOOR = 0.5


@dataclass
class DetectionResult:
    detector: str
    scores: list[float]
    flags: list[bool]
    reasons: dict[int, str] = field(default_factory=dict)
    params: dict[str, float | int | str] = field(default_factory=dict)

    @property
    def anomaly_indices(self) -> list[int]:
        return [i for i, f in enumerate(self.flags) if f]


def robust_scale(a: np.ndarray, med: float) -> float:
    """Sigma estimate: 1.4826*MAD, falling back to 1.2533*mean-absolute-deviation when the MAD
    is 0 (sparse data such as error rates that are mostly 0; then the larger of that and the
    std-dev), and never below half the plain
    standard deviation (so rare small blips in sparse data are not all 'infinite' outliers)."""
    dev = np.abs(a - med)
    mad = float(np.median(dev)) * MAD_TO_SIGMA
    if mad <= 0:
        mad = max(float(np.mean(dev)) * 1.2533, float(np.std(a)))
    return max(mad, STD_FLOOR * float(np.std(a)), 1e-9 + 1e-6 * abs(med))


def _arr(values: Sequence[float]) -> np.ndarray:
    a = np.asarray(values, dtype=float)
    if a.ndim != 1:
        raise ValueError("expected a 1-D series")
    if np.isnan(a).any():  # forward-fill gaps, then back-fill leading NaNs
        idx = np.where(~np.isnan(a), np.arange(len(a)), 0)
        np.maximum.accumulate(idx, out=idx)
        a = a[idx]
        if np.isnan(a[0]):
            first = np.flatnonzero(~np.isnan(a))
            a[np.isnan(a)] = a[first[0]] if len(first) else 0.0
    return a


# --------------------------------------------------------------------------- #
# Rolling robust z-score (median / MAD)
# --------------------------------------------------------------------------- #
def robust_zscore(values: Sequence[float], window: int = 60, threshold: float = 4.0) -> DetectionResult:
    """Score each point against the median/MAD of the *preceding* `window` points.

    Using only past points makes the batch result identical to the streaming one and
    avoids an anomaly masking itself.
    """
    x = _arr(values)
    n = len(x)
    scores = np.zeros(n)
    reasons: dict[int, str] = {}
    min_hist = max(5, window // 4)
    for i in range(n):
        lo = max(0, i - window)
        hist = x[lo:i]
        if len(hist) < min_hist:
            continue
        med = float(np.median(hist))
        mad = robust_scale(hist, med)
        scores[i] = abs(x[i] - med) / mad
        if scores[i] > threshold:
            direction = "above" if x[i] > med else "below"
            reasons[i] = (
                f"value {x[i]:.4g} is {scores[i]:.1f} MADs {direction} the rolling median "
                f"{med:.4g} of the previous {len(hist)} points"
            )
    flags = (scores > threshold).tolist()
    return DetectionResult("robust_z", scores.tolist(), flags, reasons, {"window": window, "threshold": threshold})


# --------------------------------------------------------------------------- #
# EWMA control chart
# --------------------------------------------------------------------------- #
def ewma(values: Sequence[float], alpha: float = 0.1, threshold: float = 4.0, warmup: int = 20,
         var_alpha: float = 0.05) -> DetectionResult:
    """EWMA of mean (`alpha`) and variance (slower `var_alpha`, so the noise estimate is stable); flag points whose deviation from the running mean exceeds
    `threshold` running standard deviations. Flagged points do not update the state so a
    single spike does not inflate the variance (level shifts are adopted after warmup).
    """
    x = _arr(values)
    n = len(x)
    scores = np.zeros(n)
    reasons: dict[int, str] = {}
    if n == 0:
        return DetectionResult("ewma", [], [], {}, {"alpha": alpha, "threshold": threshold})
    w = min(warmup, n)
    mean = float(np.mean(x[:w]))
    var = float(np.var(x[:w])) + 1e-12
    consecutive = 0
    for i in range(n):
        if i < w:
            continue
        std = max(np.sqrt(var), 1e-9 + 1e-6 * abs(mean))
        dev = x[i] - mean
        z = abs(dev) / std
        if i >= w:
            scores[i] = z
        if i >= w and z > threshold:
            consecutive += 1
            reasons[i] = (
                f"value {x[i]:.4g} deviates {z:.1f} sigma from the EWMA mean {mean:.4g} "
                f"(alpha={alpha})"
            )
            if consecutive < warmup:  # hold state; adopt a persistent new level eventually
                continue
        else:
            consecutive = 0
        mean = mean + alpha * dev
        var = (1 - var_alpha) * (var + var_alpha * dev * dev)
    flags = (np.asarray(scores) > threshold).tolist()
    return DetectionResult("ewma", scores.tolist(), flags, reasons, {"alpha": alpha, "threshold": threshold})


# --------------------------------------------------------------------------- #
# Seasonality
# --------------------------------------------------------------------------- #
def autocorrelation(x: np.ndarray, max_lag: int) -> np.ndarray:
    """Sample ACF for lags 0..max_lag via FFT (O(n log n))."""
    x = x - x.mean()
    n = len(x)
    size = 1 << (2 * n - 1).bit_length()
    f = np.fft.rfft(x, size)
    acf = np.fft.irfft(f * np.conj(f), size)[: max_lag + 1]
    return acf / acf[0] if acf[0] > 0 else np.zeros(max_lag + 1)


def detect_period(values: Sequence[float], min_period: int = 4, max_period: int | None = None,
                  min_acf: float = 0.3) -> int | None:
    """Return the dominant period: the first local ACF peak above `min_acf`, or None."""
    x = _arr(values)
    n = len(x)
    if n < 3 * min_period:
        return None
    max_period = min(max_period or n // 3, n // 2)
    # remove a linear trend so a drifting series doesn't look 'periodic' at every lag
    t = np.arange(n)
    slope, intercept = np.polyfit(t, x, 1)
    acf = autocorrelation(x - (slope * t + intercept), max_period)
    best, best_val = None, min_acf
    for lag in range(min_period, max_period):
        if acf[lag] > acf[lag - 1] and acf[lag] >= acf[lag + 1] and acf[lag] > best_val:
            best, best_val = lag, acf[lag]
            break
    if best and 3 * best < max_period:  # refine using the 2nd and 3rd harmonics' peaks
        ests = [float(best)]
        for k in (2, 3):
            lo, hi = k * best - k, k * best + k + 1
            ests.append((lo + int(np.argmax(acf[lo:hi]))) / k)
        best = round(float(np.median(ests)))
    return best


def seasonal_residual(values: Sequence[float], period: int | None = None, threshold: float = 4.0,
                      trend_window: int | None = None) -> DetectionResult:
    """STL-like decomposition: robust trend (rolling median) + seasonal profile (median of
    detrended values at each phase) -> residual; flag residuals by robust z-score."""
    x = _arr(values)
    n = len(x)
    p = period or detect_period(x)
    if not p or n < 2 * p:
        res = robust_zscore(x, threshold=threshold)
        res.detector = "seasonal"
        res.params["period"] = "none (fell back to robust_z)"
        return res
    tw = trend_window or (p if p % 2 == 1 else p + 1)
    half = tw // 2
    pad = np.pad(x, half, mode="edge")
    windows = np.lib.stride_tricks.sliding_window_view(pad, tw)
    trend = np.median(windows, axis=1)[:n]
    detr = x - trend
    phase = np.arange(n) % p
    profile = np.array([np.median(detr[phase == k]) for k in range(p)])
    seasonal = profile[phase]
    resid = detr - seasonal
    med = float(np.median(resid))
    mad = robust_scale(resid, med)
    scores = np.abs(resid - med) / mad
    reasons = {}
    for i in np.flatnonzero(scores > threshold):
        expected = trend[i] + seasonal[i]
        reasons[int(i)] = (
            f"value {x[i]:.4g} vs expected {expected:.4g} (trend {trend[i]:.4g} + seasonal "
            f"{seasonal[i]:+.4g}, period {p}); seasonal residual is {scores[i]:.1f} MADs"
        )
    return DetectionResult("seasonal", scores.tolist(), (scores > threshold).tolist(), reasons,
                           {"period": p, "threshold": threshold})


# --------------------------------------------------------------------------- #
# Isolation Forest baseline (scikit-learn)
# --------------------------------------------------------------------------- #
def isolation_forest(values: Sequence[float], contamination: float = 0.01, window: int = 5,
                     seed: int = 0) -> DetectionResult:
    """Isolation Forest on [value, first difference, deviation from local mean]."""
    from sklearn.ensemble import IsolationForest

    x = _arr(values)
    n = len(x)
    if n < 10:
        return DetectionResult("iforest", [0.0] * n, [False] * n, {}, {"contamination": contamination})
    diff = np.diff(x, prepend=x[0])
    local = np.convolve(np.pad(x, window, mode="edge"), np.ones(2 * window + 1) / (2 * window + 1), "valid")
    feats = np.column_stack([x, diff, x - local])
    feats = (feats - feats.mean(0)) / (feats.std(0) + 1e-12)
    model = IsolationForest(n_estimators=100, contamination=contamination, random_state=seed)
    model.fit(feats)
    raw = -model.score_samples(feats)  # higher = more anomalous
    cut = float(-model.offset_)
    flags = (raw > cut).tolist()
    scores = (raw / cut).tolist()  # >1 means flagged
    reasons = {i: f"isolated quickly by the forest (anomaly score {raw[i]:.3f} > cutoff {cut:.3f})"
               for i, f in enumerate(flags) if f}
    return DetectionResult("iforest", scores, flags, reasons, {"contamination": contamination})


# --------------------------------------------------------------------------- #
# Ensemble
# --------------------------------------------------------------------------- #
DETECTORS = {
    "robust_z": robust_zscore,
    "ewma": ewma,
    "seasonal": seasonal_residual,
    "iforest": isolation_forest,
}


def ensemble(values: Sequence[float], min_votes: int = 2, sensitivity: float = 1.0,
             members: Sequence[str] = ("robust_z", "ewma", "seasonal", "iforest"),
             tolerance: int = 1, period: int | None = None) -> DetectionResult:
    """Majority vote: a point is anomalous if >= min_votes members flag it (or a neighbour
    within `tolerance`). `sensitivity` scales thresholds (higher = more alerts)."""
    x = _arr(values)
    results = run_members(x, members, sensitivity, period)
    n = len(x)
    votes = np.zeros(n, dtype=int)
    for r in results:
        f = np.asarray(r.flags, dtype=bool)
        if tolerance:
            g = f.copy()
            for t in range(1, tolerance + 1):
                g[t:] |= f[:-t]
                g[:-t] |= f[t:]
            f = g
        votes += f
    flags = votes >= min_votes
    # only keep the strongest point within each tolerance cluster flagged by someone
    raw_any = np.zeros(n, dtype=bool)
    for r in results:
        raw_any |= np.asarray(r.flags, dtype=bool)
    flags &= raw_any
    reasons = {}
    for i in np.flatnonzero(flags):
        who = [r.detector for r in results if r.flags[i]]
        detail = next((r.reasons[i] for r in results if i in r.reasons), "")
        reasons[int(i)] = f"{votes[i]}/{len(results)} detectors agree ({', '.join(who)}): {detail}"
    p = next((r.params.get("period") for r in results if isinstance(r.params.get("period"), int)), None)
    params: dict[str, float | int | str] = {"min_votes": min_votes, "sensitivity": sensitivity}
    if p:
        params["period"] = p
    return DetectionResult("ensemble", (votes / len(results)).tolist(), flags.tolist(), reasons, params)


def deseasonalize(x: np.ndarray, period: int) -> np.ndarray:
    """Subtract the median seasonal profile (keeps trend and level shifts visible)."""
    n = len(x)
    tw = period if period % 2 == 1 else period + 1
    pad = np.pad(x, tw // 2, mode="edge")
    trend = np.median(np.lib.stride_tricks.sliding_window_view(pad, tw), axis=1)[:n]
    phase = np.arange(n) % period
    detr = x - trend
    profile = np.array([np.median(detr[phase == k]) for k in range(period)])
    return x - profile[phase]


def run_members(x: np.ndarray, members: Sequence[str], sensitivity: float = 1.0,
                period: int | None = None) -> list[DetectionResult]:
    """Run ensemble members. If the series is seasonal, the non-seasonal members see the
    deseasonalized series so daily/hourly cycles are not mistaken for anomalies."""
    thr = 4.0 / max(sensitivity, 1e-3)
    p = period or detect_period(x)
    xd = deseasonalize(x, p) if p and len(x) >= 2 * p else x
    out = []
    for m in members:
        if m == "iforest":
            out.append(isolation_forest(xd, contamination=min(0.5, 0.01 * sensitivity)))
        elif m == "seasonal":
            out.append(seasonal_residual(x, period=p, threshold=thr))
        else:
            r = DETECTORS[m](xd, threshold=thr)
            if xd is not x:  # explain in terms of the original value
                r.reasons = {i: why + " [values here are after removing the seasonal pattern]" for i, why in r.reasons.items()}
            out.append(r)
    return out


def run_detector(name: str, values: Sequence[float], sensitivity: float = 1.0,
                 period: int | None = None) -> DetectionResult:
    """Dispatch by name. `auto` picks seasonal if a period is found, else ensemble."""
    thr = 4.0 / max(sensitivity, 1e-3)
    if name == "auto":
        r = ensemble(values, sensitivity=sensitivity, period=period)
        r.params["auto_selected"] = "ensemble (seasonal-aware)" if "period" in r.params else "ensemble"
        return r
    if name == "ensemble":
        return ensemble(values, sensitivity=sensitivity, period=period)
    if name == "seasonal":
        return seasonal_residual(values, period=period, threshold=thr)
    if name == "iforest":
        return isolation_forest(values, contamination=min(0.5, 0.01 * sensitivity))
    if name in DETECTORS:
        return DETECTORS[name](values, threshold=thr)
    raise ValueError(f"unknown detector {name!r}; choose from auto, ensemble, {', '.join(DETECTORS)}")


def precision_recall(flags: Sequence[bool], labels: Sequence[bool], tolerance: int = 0) -> dict[str, float]:
    """Point-wise precision/recall/F1. With tolerance>0 a flag within `tolerance` points of
    a true anomaly counts as a hit (and a labelled point is recalled if any flag is near)."""
    f = np.asarray(flags, dtype=bool)
    y = np.asarray(labels, dtype=bool)
    if tolerance:
        def dilate(a: np.ndarray) -> np.ndarray:
            b = a.copy()
            for t in range(1, tolerance + 1):
                b[t:] |= a[:-t]
                b[:-t] |= a[t:]
            return b
        tp_p = int((f & dilate(y)).sum())
        tp_r = int((y & dilate(f)).sum())
    else:
        tp_p = tp_r = int((f & y).sum())
    precision = tp_p / f.sum() if f.sum() else 0.0
    recall = tp_r / y.sum() if y.sum() else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {"precision": round(float(precision), 4), "recall": round(float(recall), 4),
            "f1": round(float(f1), 4), "flagged": int(f.sum()), "labelled": int(y.sum())}
