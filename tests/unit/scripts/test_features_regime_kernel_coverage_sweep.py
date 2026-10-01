"""Unit tests for the read-only regime kernel coverage sweep (186-18). No database."""

from __future__ import annotations

import numpy as np
import pytest

from scripts.infrastructure import features_regime_kernel_coverage_sweep as sweep
from src.intelligence.features.kernels._hmm import HmmConfig
from tests.unit.intelligence.regime_kernel_fixtures import (
    SMALL_HMM_APR,
    make_synthetic_regime_bars,
)

NAN = np.nan


def test_summarize_counts_segments_not_rows():
    # 3 rows of no model, then segments of 4 rows: written, degenerate, not converged, other, written
    status = np.array([0, 0, 0] + [1] * 4 + [2] * 4 + [3] * 4 + [4] * 4 + [1] * 2, dtype=float)
    out = sweep.summarize_segments(status, 4)
    assert out["status_counts"] == {"1": 2, "2": 1, "3": 1, "4": 1}
    assert out["attempted"] == 5
    assert out["skip_fraction"] == pytest.approx(3 / 5)
    assert out["labeled_rows"] == 6
    assert out["first_labeled_row"] == 3


def test_summarize_all_zero_and_all_nan_have_no_attempts():
    for status in (np.zeros(10), np.full(10, NAN)):
        out = sweep.summarize_segments(status, 5)
        assert out["attempted"] == 0
        assert out["skip_fraction"] is None
        assert out["labeled_rows"] == 0
        assert out["first_labeled_row"] is None


def test_summarize_nan_tail_after_segments_is_not_a_segment():
    status = np.array([1, 1, 1, 1, NAN, NAN, NAN, NAN], dtype=float)
    out = sweep.summarize_segments(status, 4)
    assert out["status_counts"]["1"] == 1
    assert out["attempted"] == 1
    assert out["skip_fraction"] == 0.0


def test_summarize_rejects_a_non_positive_schedule():
    with pytest.raises(ValueError):
        sweep.summarize_segments(np.ones(3), 0)


def _hmm() -> HmmConfig:
    return HmmConfig.from_values(SMALL_HMM_APR.get)


def test_overrides_replace_fields_and_unknown_fields_raise():
    assert sweep.parse_override(["hmm_refit_every_bars_1d=126"]) == {"hmm_refit_every_bars_1d": 126}
    replaced = sweep.apply_overrides(_hmm(), {"hmm_refit_every_bars_1d": 126})
    assert replaced.hmm_refit_every_bars_1d == 126
    assert replaced.hmm_n_components == _hmm().hmm_n_components
    with pytest.raises(ValueError, match="unknown HmmConfig field"):
        sweep.parse_override(["hmm_not_a_field=1"])
    with pytest.raises(ValueError, match="unknown HmmConfig field"):
        sweep.apply_overrides(_hmm(), {"hmm_not_a_field": 1})
    with pytest.raises(ValueError):
        sweep.parse_override(["no_equals_sign"])


def test_sweep_grid_combines_with_the_fixed_overrides():
    sets = sweep.override_sets({"hmm_n_iter": 10}, ["hmm_refit_every_bars_1d=126,252"])
    assert sets == [
        {"hmm_n_iter": 10, "hmm_refit_every_bars_1d": 126},
        {"hmm_n_iter": 10, "hmm_refit_every_bars_1d": 252},
    ]
    assert sweep.override_sets({}, []) == [{}]
    assert sweep.override_label({}) == "base"


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


def test_run_cell_on_synthetic_bars_matches_the_kernel_status():
    bars = make_synthetic_regime_bars(1250, 42)
    job = {
        "symbol": "SYN",
        "tf": "1d",
        "family": "trend",
        "hmm": _hmm(),
        "override_label": "base",
        **bars,
    }
    cell = sweep._run_cell(job)
    assert "error" not in cell
    assert cell["summary"]["attempted"] >= 1
    assert cell["summary"]["labeled_rows"] > 0
    assert cell["class"] == sweep.CLASS_LABELS_UNDER_KERNEL


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
