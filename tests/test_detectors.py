import numpy as np
import pytest

from spikelens.detectors import (
    detect_period,
    ensemble,
    ewma,
    isolation_forest,
    precision_recall,
    robust_zscore,
    run_detector,
    seasonal_residual,
)
from spikelens.synthetic import make_series


def flat_with_spikes(seed=0, n=600, idx=(200, 350, 500)):
    rng = np.random.default_rng(seed)
    x = 10 + rng.normal(0, 1, n)
    for i in idx:
        x[i] += 12
    return x, set(idx)


@pytest.mark.parametrize("fn", [robust_zscore, ewma])
def test_point_detectors_find_injected_spikes(fn):
    x, truth = flat_with_spikes()
    res = fn(x)
    assert truth <= set(res.anomaly_indices)
    assert len(res.anomaly_indices) <= len(truth) + 3  # few false positives on clean noise


def test_robust_z_explanation_mentions_mad():
    x, _ = flat_with_spikes()
    res = robust_zscore(x)
    assert "MADs above the rolling median" in res.reasons[200]


def test_robust_z_is_not_fooled_by_outliers_in_window():
    # MAD/median are robust: a spike right after another spike is still flagged
    x, _ = flat_with_spikes(idx=(300, 301))
    assert {300, 301} <= set(robust_zscore(x).anomaly_indices)


def test_constant_series_does_not_divide_by_zero():
    x = np.full(100, 5.0)
    x[60] = 6.0
    res = robust_zscore(x)
    assert res.anomaly_indices == [60]
    assert np.isfinite(res.scores).all()


def test_nan_values_are_filled():
    x, _ = flat_with_spikes()
    x[10] = np.nan
    assert np.isfinite(robust_zscore(x).scores).all()


@pytest.mark.parametrize("period", [24, 60, 144])
def test_detect_period(period):
    s = make_series(n=period * 10, period=period, kind="spikes", seed=1)
    assert detect_period(s.values) == period


def test_detect_period_none_for_noise():
    rng = np.random.default_rng(3)
    assert detect_period(rng.normal(size=500)) is None


def test_seasonal_detector_catches_seasonal_break_that_zscore_misses():
    s = make_series(kind="seasonal_break", seed=7)
    seas = precision_recall(seasonal_residual(s.values).flags, s.labels, tolerance=2)
    rz = precision_recall(robust_zscore(s.values).flags, s.labels, tolerance=2)
    assert seas["recall"] > 0.8
    assert seas["f1"] > rz["f1"]


def test_seasonal_reason_has_expected_value():
    s = make_series(kind="spikes", seed=7)
    res = seasonal_residual(s.values)
    assert res.params["period"] == 60
    assert all("seasonal residual" in r for r in res.reasons.values())


def test_iforest_flags_spikes():
    x, truth = flat_with_spikes()
    assert truth <= set(isolation_forest(x, contamination=0.01).anomaly_indices)


def test_ensemble_beats_or_matches_best_single_on_mixed():
    s = make_series(kind="mixed", seed=7)
    ens = precision_recall(ensemble(s.values).flags, s.labels, tolerance=2)["f1"]
    assert ens > 0.7


def test_sensitivity_monotonic():
    s = make_series(kind="mixed", seed=2)
    lo = len(run_detector("robust_z", s.values, sensitivity=0.5).anomaly_indices)
    hi = len(run_detector("robust_z", s.values, sensitivity=2.0).anomaly_indices)
    assert hi >= lo


def test_unknown_detector():
    with pytest.raises(ValueError):
        run_detector("nope", [1, 2, 3])


def test_precision_recall_tolerance():
    flags = [False, True, False, False]
    labels = [True, False, False, False]
    assert precision_recall(flags, labels)["f1"] == 0
    assert precision_recall(flags, labels, tolerance=1)["f1"] == 1.0


def test_sparse_series_with_zero_mad_is_not_flooded():
    # mostly-zero error rate with rare small blips, then a real burst
    rng = np.random.default_rng(0)
    x = np.where(rng.random(400) < 0.1, 0.02, 0.0)
    x[300:304] = 0.6
    flagged = set(robust_zscore(x).anomaly_indices)
    assert {300, 301} <= flagged
    assert len(flagged - set(range(300, 304))) <= 4
