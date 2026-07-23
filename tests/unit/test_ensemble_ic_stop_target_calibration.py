"""Unit tests: Phase 166 D-01b/D-03.1 scalar candidate -- stop_atr_mult/target_r_multiple
calibration.

Task 1: `_select_stop_target_from_excursions` -- pure function, per-symbol selection
from alpha_frames' uncensored MAE/MFE excursion subpopulations (Finding 1/Pitfall 1:
NOT a copy of `_select_hold_bars_from_decay`'s decay-threshold walk). No DB, no Kafka.

Task 2 adds `EnsembleICEngine._calibrate_stop_target` coverage to this same file.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import numpy as np
import pytest

_project_root = Path(__file__).parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from services.ensemble_ic_engine import _select_stop_target_from_excursions  # noqa: E402

# ---------------------------------------------------------------------------
# Task 1: _select_stop_target_from_excursions (pure function)
# ---------------------------------------------------------------------------


def _frame(
    status: str,
    mae: float | None = None,
    mfe: float | None = None,
    stop_atr_mult: float = 1.5,
) -> dict[str, Any]:
    return {
        "counterfactual_status": status,
        "counterfactual_mae": mae,
        "counterfactual_mfe": mfe,
        "stop_atr_mult": stop_atr_mult,
    }


def test_stop_selection_uses_closed_target_percentile_of_atr_rescaled_mae():
    """Test 1: closed_target frames with known ATR-rescaled MAE values -> the
    configured percentile (default 90th) as stop_atr_mult.

    mae values [-1.0, -1.0, -1.0, -1.0, -2.0], stop_atr_mult=1.5 -> mae_atr values
    [1.5, 1.5, 1.5, 1.5, 3.0]. 90th percentile computed via numpy for exactness.
    """
    cells = [
        _frame("closed_target", mae=-1.0, stop_atr_mult=1.5),
        _frame("closed_target", mae=-1.0, stop_atr_mult=1.5),
        _frame("closed_target", mae=-1.0, stop_atr_mult=1.5),
        _frame("closed_target", mae=-1.0, stop_atr_mult=1.5),
        _frame("closed_target", mae=-2.0, stop_atr_mult=1.5),
    ]
    stop, target = _select_stop_target_from_excursions(
        cells, stop_mae_percentile=90.0, target_mfe_percentile=50.0, min_frames=3
    )
    expected = float(np.percentile([1.5, 1.5, 1.5, 1.5, 3.0], 90.0))
    assert stop == pytest.approx(expected)
    assert target is None  # no closed_max_hold frames in this cell


def test_target_selection_uses_closed_max_hold_percentile_of_r_unit_mfe():
    """Test 2: closed_max_hold frames with known R-unit MFE values -> the configured
    percentile (default 50th, median) as target_r_multiple. MFE is NOT rescaled.
    """
    cells = [
        _frame("closed_max_hold", mfe=1.0),
        _frame("closed_max_hold", mfe=2.0),
        _frame("closed_max_hold", mfe=3.0),
    ]
    stop, target = _select_stop_target_from_excursions(
        cells, stop_mae_percentile=90.0, target_mfe_percentile=50.0, min_frames=3
    )
    assert stop is None  # no closed_target frames in this cell
    assert target == pytest.approx(2.0)


def test_closed_stop_frames_excluded_from_stop_distribution_088_censoring():
    """Test 3: a cell of ONLY closed_stop frames returns None for the stop component
    -- closed_stop is right-censored at the stop distance (todo 088), never used to
    place the stop itself.
    """
    cells = [
        _frame("closed_stop", mae=-1.0, stop_atr_mult=1.5),
        _frame("closed_stop", mae=-1.2, stop_atr_mult=1.5),
        _frame("closed_stop", mae=-0.9, stop_atr_mult=1.5),
        _frame("closed_stop", mae=-1.1, stop_atr_mult=1.5),
    ]
    stop, target = _select_stop_target_from_excursions(
        cells, stop_mae_percentile=90.0, target_mfe_percentile=50.0, min_frames=3
    )
    assert stop is None
    assert target is None


def test_below_min_frames_returns_none_never_fabricated():
    """Test 4: a cell with fewer than the minimum qualifying frames returns None --
    never a fabricated value from a thin sample. min_frames=3, only 2 closed_target
    frames present.
    """
    cells = [
        _frame("closed_target", mae=-1.0, stop_atr_mult=1.5),
        _frame("closed_target", mae=-1.1, stop_atr_mult=1.5),
    ]
    stop, target = _select_stop_target_from_excursions(
        cells, stop_mae_percentile=90.0, target_mfe_percentile=50.0, min_frames=3
    )
    assert stop is None
    assert target is None


def test_nan_inf_excursion_values_filtered_before_percentile():
    """Test 5: NaN/inf excursion values are filtered out before the percentile is
    computed -- a cell with 3 finite values plus NaN/inf pollution still qualifies and
    computes from the finite subset only.
    """
    cells = [
        _frame("closed_target", mae=-1.0, stop_atr_mult=1.5),
        _frame("closed_target", mae=-1.0, stop_atr_mult=1.5),
        _frame("closed_target", mae=-1.0, stop_atr_mult=1.5),
        _frame("closed_target", mae=float("nan"), stop_atr_mult=1.5),
        _frame("closed_target", mae=float("inf"), stop_atr_mult=1.5),
    ]
    stop, target = _select_stop_target_from_excursions(
        cells, stop_mae_percentile=90.0, target_mfe_percentile=50.0, min_frames=3
    )
    # Only the 3 finite mae_atr=1.5 values remain -> percentile is exactly 1.5.
    assert stop == pytest.approx(1.5)


def test_empty_cell_list_returns_none_none():
    """No frames at all for this symbol's cell -- both components None."""
    stop, target = _select_stop_target_from_excursions(
        [], stop_mae_percentile=90.0, target_mfe_percentile=50.0, min_frames=3
    )
    assert stop is None
    assert target is None


def test_closed_ic_decay_excluded_from_both_distributions():
    """closed_ic_decay frames contribute to neither the stop nor the target
    distribution -- not part of either uncensored subpopulation.
    """
    cells = [
        _frame("closed_ic_decay", mae=-5.0, mfe=5.0, stop_atr_mult=1.5),
        _frame("closed_ic_decay", mae=-5.0, mfe=5.0, stop_atr_mult=1.5),
        _frame("closed_ic_decay", mae=-5.0, mfe=5.0, stop_atr_mult=1.5),
    ]
    stop, target = _select_stop_target_from_excursions(
        cells, stop_mae_percentile=90.0, target_mfe_percentile=50.0, min_frames=3
    )
    assert stop is None
    assert target is None


def test_no_decay_threshold_or_lookahead_reference_in_module():
    """Acceptance criterion: no reference to decay_threshold or lookahead inside the
    new selection function -- Pitfall 1 (the IC-decay-walk does not transfer to a
    distance/reward-ratio parameter). Grep the function's own source text.
    """
    import inspect

    from services.ensemble_ic_engine import _select_stop_target_from_excursions as fn

    source = inspect.getsource(fn)
    assert "decay_threshold" not in source
    assert "lookahead" not in source
