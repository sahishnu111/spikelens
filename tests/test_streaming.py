import numpy as np
import pytest

from spikelens.detectors import ewma, robust_zscore
from spikelens.streaming import RollingMedian, StreamingEWMA, StreamingRobustZ


@pytest.mark.parametrize("window", [1, 2, 7, 50])
def test_rolling_median_and_mad_match_numpy(window):
    rng = np.random.default_rng(window)
    data = rng.integers(0, 20, 400).astype(float)  # many duplicates on purpose
    rm = RollingMedian(window)
    for i, v in enumerate(data):
        rm.push(v)
        w = data[max(0, i - window + 1): i + 1]
        assert rm.median() == pytest.approx(np.median(w))
        assert rm.mad() == pytest.approx(np.median(np.abs(w - np.median(w))))


def test_streaming_robust_z_matches_batch():
    rng = np.random.default_rng(0)
    x = rng.normal(0, 1, 800)
    x[[300, 600]] += 15
    batch = robust_zscore(x, window=60)
    s = StreamingRobustZ(window=60)
    stream_flags = [s.update(v).is_anomaly for v in x]
    assert stream_flags == batch.flags
    assert [i for i, f in enumerate(stream_flags) if f] == batch.anomaly_indices


def test_streaming_ewma_matches_batch():
    rng = np.random.default_rng(1)
    x = rng.normal(5, 1, 500)
    x[250] += 20
    batch = ewma(x)
    s = StreamingEWMA()
    assert [s.update(v).is_anomaly for v in x] == batch.flags


def test_rolling_median_rejects_bad_window():
    with pytest.raises(ValueError):
        RollingMedian(0)


def test_streaming_matches_batch_on_sparse_zero_mad_data():
    rng = np.random.default_rng(5)
    x = np.where(rng.random(400) < 0.1, 0.02, 0.0)
    x[300] = 0.7
    s = StreamingRobustZ(window=60)
    assert [s.update(v).is_anomaly for v in x] == robust_zscore(x, window=60).flags
