"""Unit tests for the read-only regime kernel coverage sweep (186-18). No database."""

from __future__ import annotations

import dataclasses

import numpy as np
import pytest

from scripts.infrastructure import features_regime_kernel_coverage_sweep as sweep
from src.intelligence.features.kernels._hmm import (
    EVENT_CONVERGENCE,
    EVENT_SEGMENT_SKIPPED,
    FAMILY_SPECS,
    HmmConfig,
    RegimeEventRecord,
)
from src.intelligence.features.kernels.regime import compute_regime_columns
from tests.unit.intelligence.regime_kernel_fixtures import (
    SMALL_HMM_APR,
    make_collapsing_segment_bars,
    make_synthetic_regime_bars,
)


def _hmm() -> HmmConfig:
    return HmmConfig.from_values(SMALL_HMM_APR.get)


def _events(*segments):
    """(seg_start, seg_end, reason or None) to the kernel's event records."""
    out = []
    for start, end, reason in segments:
        out.append(RegimeEventRecord(EVENT_CONVERGENCE, {"seg_start": start, "seg_end": end}))
        if reason:
            out.append(
                RegimeEventRecord(
                    EVENT_SEGMENT_SKIPPED, {"seg_start": start, "seg_end": end, "reason": reason}
                )
            )
    return tuple(out)


def test_summarize_counts_segments_by_status_from_events():
    events = _events(
        (10, 14, None),
        (14, 18, "degenerate_occupation"),
        (18, 22, "not_converged"),
        (22, 26, "insufficient_obs"),
        (26, 28, None),
    )
    out = sweep.summarize_segments(events)
    assert out["status_counts"] == {"1": 2, "2": 1, "3": 1, "4": 1}
    assert out["attempted"] == 5
    assert out["skip_fraction"] == pytest.approx(3 / 5)
    assert out["labeled_rows"] == 6


def test_summarize_no_events_has_no_attempts():
    out = sweep.summarize_segments(())
    assert out["attempted"] == 0 and out["skip_fraction"] is None and out["labeled_rows"] == 0


@pytest.mark.parametrize("family", ["trend", "volatility"])
def test_event_summary_equals_the_status_array_layout(family):
    """The kernel's events and its row status array describe the same segments: counts from the
    events equal counts read off the status array at each segment start (independent check)."""
    bars = make_collapsing_segment_bars()
    hmm = _hmm()
    spec = FAMILY_SPECS[family]
    result = compute_regime_columns(bars["close"], bars["volume"], hmm, "1d", spec)
    status = result.columns[spec.status_output]
    summary = sweep.summarize_segments(result.events)
    starts = [e.fields["seg_start"] for e in result.events if e.kind == EVENT_CONVERGENCE]
    assert summary["attempted"] == len(starts) >= 1
    first_row = int(np.flatnonzero(status > 0)[0])
    for code in ("1", "2", "3", "4"):
        assert summary["status_counts"][code] == sum(
            1
            for i in range(len(starts))
            if status[first_row + i * hmm.hmm_refit_every_bars_1d] == int(code)
        )
    assert summary["labeled_rows"] == int((status == 1).sum())


def test_overrides_cast_to_the_field_type_and_unknown_fields_raise():
    assert sweep.parse_override(["hmm_refit_every_bars_1d=126"]) == {"hmm_refit_every_bars_1d": 126}
    replaced = dataclasses.replace(_hmm(), **sweep.parse_override(["hmm_refit_every_bars_1d=126"]))
    assert replaced.hmm_refit_every_bars_1d == 126
    with pytest.raises(ValueError, match="unknown HmmConfig field"):
        sweep.parse_override(["hmm_not_a_field=1"])
    with pytest.raises(ValueError):
        sweep.parse_override(["no_equals_sign"])


def test_sweep_axis_is_one_schedule_field():
    assert sweep.parse_sweep(None) is None
    assert sweep.parse_sweep("hmm_refit_every_bars_1d=126,252") == (
        "hmm_refit_every_bars_1d",
        [126, 252],
    )
    with pytest.raises(ValueError, match="schedule field"):
        sweep.parse_sweep("hmm_vol_window=10,20")
    with pytest.raises(ValueError):
        sweep.parse_sweep("hmm_refit_every_bars_1d")


def _cell(counts, n_obs=1000, boundary=600, error=None):
    cell = {
        "summary": {
            "status_counts": {"1": counts[0], "2": counts[1], "3": counts[2], "4": counts[3]},
            "attempted": sum(counts),
        },
        "n_obs": n_obs,
        "first_boundary_obs": boundary,
    }
    if error:
        cell["error"] = error
    return cell


@pytest.mark.parametrize(
    "cell,expected",
    [
        (_cell((0, 0, 0, 0), n_obs=100), sweep.CLASS_HISTORY_SHORT),
        (_cell((0, 0, 0, 0), n_obs=600), sweep.CLASS_HISTORY_SHORT),  # no row past the boundary
        (_cell((0, 0, 0, 0), n_obs=601), sweep.CLASS_DEFECT),
        (_cell((0, 3, 0, 0)), sweep.CLASS_DEGENERATE),
        (_cell((0, 0, 2, 0)), sweep.CLASS_NOT_CONVERGED),
        (_cell((1, 5, 0, 0)), sweep.CLASS_LABELS_UNDER_KERNEL),
        (_cell((0, 2, 1, 0)), sweep.CLASS_DEFECT),
        (_cell((0, 0, 0, 0), error="boom"), sweep.CLASS_DEFECT),
    ],
)
def test_classification_rule(cell, expected):
    assert sweep.classify_cell(cell) == expected


def test_run_series_loops_families_and_sweep_points_over_one_bar_set():
    bars = make_synthetic_regime_bars(1250, 42)
    hmm = _hmm()
    points = [
        ("hmm_refit_every_bars_1d=300", hmm),
        ("hmm_refit_every_bars_1d=600", dataclasses.replace(hmm, hmm_refit_every_bars_1d=600)),
    ]
    cells = sweep._run_series(
        {
            "symbol": "SYN",
            "tf": "1d",
            "families": ["trend", "volatility"],
            "points": points,
            "close": bars["close"],
            "volume": bars["volume"],
        }
    )
    assert [(c["family"], c["overrides"]) for c in cells] == [
        ("trend", "hmm_refit_every_bars_1d=300"),
        ("trend", "hmm_refit_every_bars_1d=600"),
        ("volatility", "hmm_refit_every_bars_1d=300"),
        ("volatility", "hmm_refit_every_bars_1d=600"),
    ]
    assert all("error" not in c for c in cells)
    trend300, trend600 = cells[0], cells[1]
    assert trend300["summary"]["attempted"] > trend600["summary"]["attempted"] >= 1
    assert trend300["class"] == sweep.CLASS_LABELS_UNDER_KERNEL


def test_pool_cells_sums_segments_and_the_labeled_fraction():
    def cell(symbol, counts, labeled, post):
        return {
            "symbol": symbol,
            "tf": "1d",
            "family": "trend",
            "overrides": "base",
            "class": "x",
            "summary": {
                "status_counts": {"1": counts[0], "2": counts[1], "3": counts[2], "4": counts[3]},
                "labeled_rows": labeled,
            },
            "post_boundary_rows": post,
        }

    pooled = sweep.pool_cells([cell("A", (1, 1, 0, 0), 100, 200), cell("B", (0, 2, 0, 0), 0, 200)])
    only = pooled["1d|trend|base"]
    assert only["attempted"] == 4
    assert only["skip_fraction"] == pytest.approx(3 / 4)
    assert only["dominant_skip_status"] == "2"
    assert only["labeled_fraction_after_first_boundary"] == pytest.approx(100 / 400)


# --- the todo 289 rule, in code -------------------------------------------------------------


def test_decision_reproduces_the_recorded_289_result():
    """The recorded pooled 1d skip fractions (evidence/186-18-regime-coverage.json) keep 252."""
    skips = {
        126: {"trend": 0.1506, "volatility": 0.9838},
        252: {"trend": 0.1594, "volatility": 0.9821},
        504: {"trend": 0.1799, "volatility": 0.9794},
    }
    decision = sweep.decide_refit_schedule(skips, current=252)
    assert decision["deciding_values"] == {"126": 0.9838, "252": 0.9821, "504": 0.9794}
    assert decision["smallest_deciding_value"] == 0.9794
    assert decision["keep_current"] is True and decision["chosen"] == 252
    assert "within 0.02" in decision["rule"]


def _flat(a, b, c):
    return {126: {"x": a}, 252: {"x": b}, 504: {"x": c}}


def test_decision_takes_the_smallest_when_252_is_more_than_the_tolerance_above():
    decision = sweep.decide_refit_schedule(_flat(0.30, 0.40, 0.35), current=252)
    assert decision["keep_current"] is False and decision["chosen"] == 126


def test_decision_boundary_exactly_at_the_tolerance_keeps_current():
    assert sweep.decide_refit_schedule(_flat(0.30, 0.32, 0.50), current=252)["chosen"] == 252
    assert sweep.decide_refit_schedule(_flat(0.30, 0.3201, 0.50), current=252)["chosen"] == 126


def test_decision_uses_the_larger_family_and_breaks_ties_toward_the_smaller_schedule():
    skips = {
        126: {"trend": 0.9, "volatility": 0.1},
        252: {"trend": 0.1, "volatility": 0.5},
        504: {"trend": 0.5, "volatility": 0.1},
    }
    # deciding: 126 -> 0.9, 252 -> 0.5, 504 -> 0.5; 252 is the smallest and is current
    assert sweep.decide_refit_schedule(skips, current=126)["chosen"] == 252
    tie = {126: {"x": 0.5}, 252: {"x": 0.9}, 504: {"x": 0.5}}
    assert sweep.decide_refit_schedule(tie, current=252)["chosen"] == 126


def test_refit_decision_reads_the_pooled_report_and_ignores_other_fields():
    pooled = {
        f"1d|{family}|hmm_refit_every_bars_1d={v}": {"skip_fraction": f}
        for v, trend, vol in ((126, 0.15, 0.98), (252, 0.16, 0.98), (504, 0.18, 0.97))
        for family, f in (("trend", trend), ("volatility", vol))
    }
    decision = sweep.refit_decision(
        pooled, "hmm_refit_every_bars_1d", [126, 252, 504], ["trend", "volatility"], 252
    )
    assert decision is not None and decision["chosen"] == 252
    assert (
        sweep.refit_decision(pooled, "hmm_initial_warmup_bars_1d", [126, 252], ["trend"], 252)
        is None
    )
