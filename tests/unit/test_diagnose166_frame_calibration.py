"""Unit tests: Phase 166 D-01a diagnosis pure functions.

_summarize_excursions / _compare_to_current are pure module-level functions in
scripts/analysis/diagnose166_frame_calibration.py -- no DB, no Kafka, synthetic rows only.

Covers:
- Test 1: per-(regime,tf) MAE/MFE percentile summary, ATR-rescaling correctness given each
  row's own snapshotted stop_atr_mult.
- Test 2: closed_stop frames are excluded from the stop-placement (MAE) distribution --
  right-censored at the stop threshold (088 alignment) -- while closed_target frames
  contribute to stop placement and closed_max_hold frames contribute to target placement.
- Test 3: _compare_to_current returns a per-cell delta against the current global scalars.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_project_root = Path(__file__).parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from scripts.analysis.diagnose166_frame_calibration import (  # noqa: E402
    _compare_to_current,
    _summarize_excursions,
)


def _row(
    regime: str,
    tf: str,
    status: str,
    stop_atr_mult: float,
    counterfactual_mae: float,
    counterfactual_mfe: float,
) -> dict:
    return {
        "regime": regime,
        "tf": tf,
        "status": status,
        "stop_atr_mult": stop_atr_mult,
        "counterfactual_mae": counterfactual_mae,
        "counterfactual_mfe": counterfactual_mfe,
    }


def test_summarize_excursions_rescales_mae_to_atr_units_from_snapshotted_stop_atr_mult():
    """Single closed_target row, stop_atr_mult=2.0, counterfactual_mae=-0.4 (R-units).
    mae_atr = abs(-0.4) * 2.0 = 0.8 -- the 90th percentile of a single-value distribution is
    that value itself."""
    rows = [_row("mid_bull", "5m", "closed_target", 2.0, -0.4, 0.0)]

    summary = _summarize_excursions(rows, stop_mae_percentile=90.0, target_mfe_percentile=50.0)

    cell = summary[("mid_bull", "5m")]
    assert cell["n_stop_qualifying"] == 1
    assert cell["stop_atr_mult_percentile"] == 0.8
    # No closed_max_hold rows in this fixture -- target side has zero qualifying frames.
    assert cell["n_target_qualifying"] == 0
    assert cell["target_r_multiple_percentile"] is None


def test_summarize_excursions_excludes_closed_stop_right_censored_mae():
    """Mixed closed_stop / closed_target / closed_max_hold frames in one cell. closed_stop's
    MAE (right-censored at the stop threshold, 088) must NOT appear in the stop-placement
    distribution -- only closed_target frames qualify for stop, only closed_max_hold frames
    qualify for target."""
    rows = [
        # closed_stop: MAE is bounded by the stop -- must be excluded from stop distribution.
        _row("high_bear", "1h", "closed_stop", 1.5, -1.0, 0.0),
        _row("high_bear", "1h", "closed_stop", 1.5, -0.98, 0.0),
        # closed_target: uncensored MAE -- these ARE the stop-placement distribution.
        _row("high_bear", "1h", "closed_target", 1.5, -0.3, 1.9),
        _row("high_bear", "1h", "closed_target", 1.5, -0.5, 2.1),
        # closed_max_hold: uncensored MFE -- these ARE the target-placement distribution.
        _row("high_bear", "1h", "closed_max_hold", 1.5, -0.2, 0.7),
        _row("high_bear", "1h", "closed_max_hold", 1.5, -0.1, 1.3),
        # closed_ic_decay: excluded from BOTH distributions (neither uncensored population).
        _row("high_bear", "1h", "closed_ic_decay", 1.5, -0.6, 0.9),
    ]

    summary = _summarize_excursions(rows, stop_mae_percentile=100.0, target_mfe_percentile=100.0)

    cell = summary[("high_bear", "1h")]
    # Only the 2 closed_target rows qualify for stop -- closed_stop's 2 rows excluded.
    assert cell["n_stop_qualifying"] == 2
    # max (100th percentile) of [abs(-0.3)*1.5, abs(-0.5)*1.5] = max(0.45, 0.75) = 0.75
    assert cell["stop_atr_mult_percentile"] == 0.75
    # Only the 2 closed_max_hold rows qualify for target -- closed_stop/closed_ic_decay excluded.
    assert cell["n_target_qualifying"] == 2
    # max (100th percentile) of [0.7, 1.3] = 1.3
    assert cell["target_r_multiple_percentile"] == 1.3


def test_compare_to_current_returns_per_cell_delta_against_global_scalars():
    """A cell whose empirical stop percentile (2.1 ATR) is wider than the current global
    1.5, and whose empirical target percentile (1.2 R) is narrower than the current global
    2.0, produces a positive stop_delta and a negative target_delta."""
    summary = {
        ("low_neutral", "15m"): {
            "n_stop_qualifying": 10,
            "n_target_qualifying": 8,
            "stop_atr_mult_percentile": 2.1,
            "target_r_multiple_percentile": 1.2,
        },
    }
    current_global = {"stop_atr_mult": 1.5, "target_r_multiple": 2.0}

    comparison = _compare_to_current(summary, current_global)

    cell = comparison[("low_neutral", "15m")]
    assert cell["current_stop_atr_mult"] == 1.5
    assert cell["empirical_stop_atr_mult"] == 2.1
    assert cell["stop_delta"] == pytest.approx(0.6)
    assert cell["current_target_r_multiple"] == 2.0
    assert cell["empirical_target_r_multiple"] == 1.2
    assert cell["target_delta"] == pytest.approx(-0.8)


def test_compare_to_current_handles_missing_percentile_as_none():
    """A cell with zero qualifying frames on one side must produce a None delta, never a
    fabricated 0.0 or a KeyError."""
    summary = {
        ("mid_neutral", "1d"): {
            "n_stop_qualifying": 0,
            "n_target_qualifying": 5,
            "stop_atr_mult_percentile": None,
            "target_r_multiple_percentile": 1.8,
        },
    }

    comparison = _compare_to_current(summary, {"stop_atr_mult": 1.5, "target_r_multiple": 2.0})

    cell = comparison[("mid_neutral", "1d")]
    assert cell["empirical_stop_atr_mult"] is None
    assert cell["stop_delta"] is None
    assert cell["target_delta"] == pytest.approx(-0.2)
