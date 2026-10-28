"""The pure pod series (plan 187-10 Task 1)."""

import hashlib

import numpy as np
import pytest

from src.intelligence.research.ledger import AttemptSeries
from src.intelligence.research.pod import pod_series, series_sha256
from src.intelligence.statistics.hac import hac_mean_test


def _series(days, values):
    return AttemptSeries(
        sessions=np.array(days, dtype="datetime64[D]"), values=np.array(values, dtype=np.float64)
    )


A = _series(["2024-01-02", "2024-01-03", "2024-01-05", "2024-01-08"], [1.0, 2.0, 3.0, 4.0])
B = _series(["2024-01-03", "2024-01-04", "2024-01-05", "2024-01-08"], [0.5, 9.0, -1.0, 0.25])
C = _series(["2024-01-02", "2024-01-03", "2024-01-08"], [10.0, 20.0, 30.0])


def test_the_sum_runs_on_the_common_sessions_only():
    pod = pod_series([A, B, C])
    assert (
        pod.series.sessions.tolist()
        == np.array(["2024-01-03", "2024-01-08"], dtype="datetime64[D]").tolist()
    )
    np.testing.assert_array_equal(pod.series.values, [2.0 + 0.5 + 20.0, 4.0 + 0.25 + 30.0])
    assert pod.dropped == (2, 2, 1)


def test_the_pod_statistic_is_the_hac_test_on_the_hand_sum():
    rng = np.random.default_rng(0)
    days = np.arange("2020-01-01", "2021-06-01", dtype="datetime64[D]")
    a = _series(days[::1], rng.normal(size=days.size))
    b = _series(days[::2], rng.normal(size=days[::2].size))
    pod = pod_series([a, b])
    hand = a.values[::2] + b.values
    np.testing.assert_array_equal(pod.series.values, hand)
    assert hac_mean_test(pod.series.values) == hac_mean_test(hand)


def test_disjoint_calendars_give_no_series():
    early = _series(["2024-01-02", "2024-01-03"], [1.0, 2.0])
    late = _series(["2024-02-01"], [1.0])
    pod = pod_series([early, late])
    assert pod.series is None and pod.dropped == (2, 1)


@pytest.mark.parametrize(
    "members",
    [
        [A],
        [A, _series(["2024-01-03", "2024-01-02"], [1.0, 2.0])],  # out of order
        [A, _series(["2024-01-03", "2024-01-04"], [1.0, np.nan])],  # a filled or untested row
    ],
)
def test_malformed_members_are_refused(members):
    with pytest.raises(ValueError):
        pod_series(members)


def test_series_sha256_is_the_documented_content_hash():
    expected = hashlib.sha256(
        A.sessions.astype("<i8").tobytes() + A.values.astype("<f8").tobytes()
    ).hexdigest()
    assert series_sha256(A) == expected
    moved = _series(A.sessions, A.values + np.array([0, 0, 0, np.spacing(4.0)]))
    assert series_sha256(moved) != expected  # one ulp moves it
