"""Evidence record assembly (D-09, D-21): complete, JSON-clean, token-free."""

import json

import numpy as np
import pytest

from src.intelligence.research.evaluate import EvaluationResult
from src.intelligence.research.evidence import (
    SCHEMA,
    evidence_record,
    resolution_years,
    turnover_per_session,
)
from src.intelligence.research.spec import CostSpec
from src.intelligence.research.timing import TimingResult
from src.intelligence.statistics.hac import HacTestResult

KEYS = {
    "schema",
    "kind",
    "subject",
    "decision",
    "shift_null",
    "power",
    "coverage",
    "turnover_per_session",
    "cost_band",
    "resolution_years_80pct_power",
    "hashes",
    "guards",
}
TIMING = TimingResult(HacTestResult(0.001, 0.0004, 2.5, 0.006, 8, 3000), 0.9, 252)
PERIODS = (("2010-01-04", "2014-12-31"), ("2015-01-01", "2025-12-23"))


def _result():
    return EvaluationResult(
        arms=("rank_vol_neutral",),
        sharpe_obs=np.array([0.8]),
        sharpe_null=np.array([[0.1], [0.3], [-0.2]]),
        shifts=np.array([26, 52, 78]),
        adjusted_p=np.array([0.25]),
        excess=np.array([0.7]),
        sub_period_excess=np.array([[0.001, np.nan]]),
        excess_ci=np.array([[-0.1, 1.5]]),
        excess_se=np.array([0.4]),
        diagnostics={
            "rank_vol_neutral": {
                "observed": {"skew": np.float64(np.nan), "hit_rate": np.float32(0.51)}
            }
        },
    )


def _record(**kw):
    kw.setdefault("screen", None)
    return evidence_record(
        TIMING,
        _result(),
        kind="evidence",
        subject="member.intraday_periodicity.same_slot_lag1",
        n_shifts=3,
        power=None,
        coverage={"mean": 0.9},
        turnover=2.0,
        costs=CostSpec(bps_low=1.0, bps_high=5.0),
        hashes={"spec_hash": "a" * 64},
        guards={"memory_reach": 26},
        sub_periods=PERIODS,
        **kw,
    )


def _walk(x):
    if isinstance(x, dict):
        for k, v in x.items():
            yield k
            yield from _walk(v)
    elif isinstance(x, list):
        for v in x:
            yield from _walk(v)
    else:
        yield x


def test_record_is_json_clean_and_complete():
    rec = _record()
    json.dumps(rec, allow_nan=False)
    assert set(rec) == KEYS
    assert rec["schema"] == SCHEMA
    assert rec["power"] is None
    assert rec["shift_null"]["per_period"][1]["mean_session_excess"] is None
    assert rec["shift_null"]["shape"]["rank_vol_neutral"]["observed"]["skew"] is None
    for v in _walk(rec):
        assert not isinstance(v, (np.generic, np.ndarray))


def test_record_has_no_tokens():
    for v in _walk(_record()):
        if isinstance(v, str):
            assert v.lower() not in {"pass", "fail", "verdict", "passed", "failed"}


def test_record_maps_result_fields():
    rec = _record()
    assert rec["decision"]["statistic"] == "hac_timing_t"
    assert (rec["decision"]["t"], rec["decision"]["p"], rec["decision"]["lag"]) == (2.5, 0.006, 8)
    assert rec["resolution_years_80pct_power"] == pytest.approx(
        ((1.6449 + 0.8416) / 0.9) ** 2, rel=1e-3
    )
    sn = rec["shift_null"]
    assert sn["estimate"] == 0.7 and sn["bootstrap_se"] == 0.4 and sn["permutation_p"] == 0.25
    assert sn["bootstrap_ci"] == [-0.1, 1.5] and sn["null_median_sharpe"] == pytest.approx(0.1)


def test_resolution_years():
    assert resolution_years(0.5) == pytest.approx(((1.6449 + 0.8416) / 0.5) ** 2, rel=1e-3)
    for e in (0.0, -0.2, float("nan"), None):
        assert resolution_years(e) is None


def test_turnover_per_session():
    w = np.array([[0.25, -0.25], [0.5, -0.5], [0.1, -0.1], [0.0, 0.0]])
    has = np.array([True, True, True, False])
    trade = np.ones(4, dtype=bool)
    # Session 0: 2 * (0.5 + 1.0) = 3.0; session 1: 2 * 0.2 = 0.4; mean 1.7.
    assert turnover_per_session(w, has, trade, 2) == pytest.approx(1.7)


def test_cost_band_is_diagnostic():
    band = _record()["cost_band"]
    assert band["annual_drag_low"] == pytest.approx(2.0 * 1.0 * 1e-4 * 252)
    assert band["annual_drag_high"] == pytest.approx(2.0 * 5.0 * 1e-4 * 252)
    assert band["diagnostic_only"] is True


def test_screen_carried_only_when_given():
    screen = {"alpha": 0.05, "budget_m": 30, "bar": 0.05 / 30, "p": 0.001, "p_below_bar": True}
    assert _record(screen=screen)["screen"] == screen
    assert "screen" not in _record()


def test_missing_shift_null_is_recorded_as_none():
    rec = evidence_record(
        TIMING,
        None,
        kind="evidence",
        subject="s",
        n_shifts=0,
        power=None,
        coverage={},
        turnover=1.0,
        costs=CostSpec(bps_low=1.0, bps_high=5.0),
        hashes={},
        guards={},
        sub_periods=PERIODS,
    )
    assert rec["shift_null"] is None and rec["decision"]["p"] == 0.006
