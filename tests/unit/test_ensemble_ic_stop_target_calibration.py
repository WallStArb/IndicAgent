"""Unit tests: Phase 166 D-01b/D-03.1 scalar candidate -- stop_atr_mult/target_r_multiple
calibration.

Two units under test, both in services/ensemble_ic_engine.py:

- `_select_stop_target_from_excursions` -- pure function, per-symbol selection from
  alpha_frames' uncensored MAE/MFE excursion subpopulations (Finding 1/Pitfall 1: NOT
  a copy of `_select_hold_bars_from_decay`'s decay-threshold walk).
- `EnsembleICEngine._calibrate_stop_target` -- async orchestration mirroring
  `_calibrate_hold_max_bars`' STRUCTURE (group by (symbol, tf, regime) -> per-symbol
  selection -> group by (regime, tf) -> median across qualifying symbols ->
  skip-if-empty -> `config_service.set`). DB/ConfigService interactions are faked
  (no real asyncpg connection, no real DB) -- this is still unit-level coverage, not
  an integration test.

No Kafka. `ConfigService` is patched at the module level it is imported into
(`services.ensemble_ic_engine.ConfigService`).
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import numpy as np
import pytest

_project_root = Path(__file__).parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from services.ensemble_ic_engine import (  # noqa: E402
    EnsembleICConfig,
    EnsembleICEngine,
    _select_stop_target_from_excursions,
)

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


# ---------------------------------------------------------------------------
# Task 2: EnsembleICEngine._calibrate_stop_target (async orchestration)
# ---------------------------------------------------------------------------


def _make_config(**overrides: Any) -> EnsembleICConfig:
    defaults: dict[str, Any] = dict(
        fdr_alpha=0.05,
        walk_forward_folds=3,
        sharpe_window_size=2000,
        sharpe_min_windows=30,
        subsample_min_stride=5,
        min_reliable_n=100,
        hac_max_lag=3,
        lookahead_fast=1,
        lookahead_mid=5,
        lookahead_slow=20,
        lookahead_extended=60,
        n_workers=1,
        pooled_fetch_itersize=1000,
        decay_threshold=0.05,
        min_qualifying_fraction=0.6,
        wf_stability_ratio=3.0,
        gate_lookahead="fast",
        wf_stability_metric="ic_ratio",
        min_obs_per_regime=3000,
    )
    defaults.update(overrides)
    return EnsembleICConfig(**defaults)


def _ic_row(symbol: str, tf: str, is_pooled: bool = False) -> dict[str, Any]:
    """Minimal stand-in for an alpha_ensemble_ic corpus row -- only the fields
    _calibrate_stop_target actually reads (symbol, is_pooled) are populated."""
    return {"symbol": symbol, "tf": tf, "is_pooled": is_pooled}


def _db_frame_row(
    symbol: str,
    tf: str,
    regime: str,
    status: str,
    mae: float | None = None,
    mfe: float | None = None,
    stop_atr_mult: float = 1.5,
) -> dict[str, Any]:
    """Stand-in for one alpha_frames row as returned by _STOP_TARGET_FETCH_SQL."""
    return {
        "symbol": symbol,
        "tf": tf,
        "regime": regime,
        "counterfactual_status": status,
        "stop_atr_mult": stop_atr_mult,
        "counterfactual_mae": mae,
        "counterfactual_mfe": mfe,
    }


class _FakeConn:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows
        self.fetch_calls: list[tuple[Any, ...]] = []

    async def fetch(self, query: str, *args: Any) -> list[dict[str, Any]]:
        self.fetch_calls.append((query, args))
        return self._rows


class _FakeAcquireCtx:
    def __init__(self, conn: _FakeConn) -> None:
        self._conn = conn

    async def __aenter__(self) -> _FakeConn:
        return self._conn

    async def __aexit__(self, *exc: Any) -> bool:
        return False


class _FakePool:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.conn = _FakeConn(rows)

    def acquire(self) -> _FakeAcquireCtx:
        return _FakeAcquireCtx(self.conn)


async def _run_calibrate_stop_target(
    ic_rows: list[dict[str, Any]],
    frame_rows: list[dict[str, Any]],
    config: EnsembleICConfig,
) -> tuple[int, AsyncMock]:
    """Helper: construct an EnsembleICEngine, patch ConfigService, run
    _calibrate_stop_target, return (n_written, mocked_config_service_instance)."""
    engine = EnsembleICEngine(db_dsn="postgresql://fake/db")
    pool = _FakePool(frame_rows)

    with patch("services.ensemble_ic_engine.ConfigService") as mock_cls:
        mock_instance = mock_cls.return_value
        mock_instance.initialize = AsyncMock()
        mock_instance.set = AsyncMock()
        from datetime import UTC, datetime

        n_written = await engine._calibrate_stop_target(
            pool,  # type: ignore[arg-type]
            ic_rows,
            config,
            "champion-v1",
            datetime(2026, 1, 1, tzinfo=UTC),
        )
    return n_written, mock_instance


def test_groups_by_cell_and_writes_median_across_qualifying_symbols():
    """Test 6: groups alpha_frames rows by (symbol, tf, regime) skipping is_pooled=true
    ic rows, calls the selection function per symbol, groups results by (regime, tf),
    and returns the median across qualifying symbols per cell.

    3 symbols (A, B, C) in the SAME (regime, tf) cell:
    - A: closed_target mae_atr=1.5 (x3) -> stop=1.5; closed_max_hold mfe=1.0 (x3) -> target=1.0
    - B: closed_target mae_atr=3.0 (x3) -> stop=3.0; closed_max_hold mfe=2.0 (x3) -> target=2.0
    - C: closed_target mae_atr=2.0 (x3) -> stop=2.0; closed_max_hold mfe=1.5 (x3) -> target=1.5
    Median stop = 2.0 (of [1.5, 3.0, 2.0]); median target = 1.5 (of [1.0, 2.0, 1.5]).
    """
    ic_rows = [_ic_row("A", "5m"), _ic_row("B", "5m"), _ic_row("C", "5m")]
    frame_rows = []
    for symbol, mae, stop_atr_mult, mfe in (
        ("A", -1.0, 1.5, 1.0),
        ("B", -2.0, 1.5, 2.0),
        ("C", -1.0, 2.0, 1.5),
    ):
        for _ in range(3):
            frame_rows.append(
                _db_frame_row(
                    symbol,
                    "5m",
                    "trending_up",
                    "closed_target",
                    mae=mae,
                    stop_atr_mult=stop_atr_mult,
                )
            )
            frame_rows.append(
                _db_frame_row(symbol, "5m", "trending_up", "closed_max_hold", mfe=mfe)
            )

    config = _make_config()
    import asyncio

    n_written, mock_instance = asyncio.run(_run_calibrate_stop_target(ic_rows, frame_rows, config))

    assert n_written == 2  # one stop key + one target key
    calls = {c.args[0]: c for c in mock_instance.set.await_args_list}
    assert "alpha.frame.stop_atr_mult.trending_up.5m" in calls
    assert "alpha.frame.target_r_multiple.trending_up.5m" in calls
    stop_call = calls["alpha.frame.stop_atr_mult.trending_up.5m"]
    target_call = calls["alpha.frame.target_r_multiple.trending_up.5m"]
    assert stop_call.args[1] == "2.0"
    assert target_call.args[1] == "1.5"
    # Acceptance: reason strings mention percentile, qualifying count, censoring method.
    stop_reason = stop_call.kwargs["reason"]
    assert "percentile" in stop_reason
    assert "3 qualifying" in stop_reason
    assert "closed_stop" in stop_reason  # censoring method disclosure
    target_reason = target_call.kwargs["reason"]
    assert "percentile" in target_reason
    assert "3 qualifying" in target_reason
    assert "closed_stop" in target_reason or "closed_target" in target_reason


def test_zero_qualifying_symbols_writes_nothing_for_that_cell():
    """Test 7: a (regime, tf) with zero qualifying symbols (every symbol has fewer
    than min_frames observations) writes nothing for that cell -- no config_service.set
    call, n_written=0.
    """
    ic_rows = [_ic_row("A", "5m"), _ic_row("B", "5m")]
    frame_rows = [
        # Only 2 closed_target frames each -- below default min_frames=3.
        _db_frame_row("A", "5m", "ranging", "closed_target", mae=-1.0, stop_atr_mult=1.5),
        _db_frame_row("A", "5m", "ranging", "closed_target", mae=-1.0, stop_atr_mult=1.5),
        _db_frame_row("B", "5m", "ranging", "closed_target", mae=-1.0, stop_atr_mult=1.5),
        _db_frame_row("B", "5m", "ranging", "closed_target", mae=-1.0, stop_atr_mult=1.5),
    ]
    config = _make_config()
    import asyncio

    n_written, mock_instance = asyncio.run(_run_calibrate_stop_target(ic_rows, frame_rows, config))

    assert n_written == 0
    mock_instance.set.assert_not_awaited()


def test_is_pooled_ic_rows_excluded_from_eligible_symbols():
    """POOLED is a diagnostic aggregate, not a tradable (symbol, tf, regime) cell --
    excluded from the eligible-symbols scope entirely (mirrors
    _calibrate_hold_max_bars' is_pooled exclusion).
    """
    ic_rows = [_ic_row("POOLED", "5m", is_pooled=True)]
    frame_rows: list[dict[str, Any]] = []
    config = _make_config()
    import asyncio

    n_written, mock_instance = asyncio.run(_run_calibrate_stop_target(ic_rows, frame_rows, config))

    assert n_written == 0
    mock_instance.set.assert_not_awaited()


def test_dispatch_calls_calibrate_stop_target_under_same_cr02_champion_gate():
    """Test 8 (CR-02): _calibrate_stop_target is called inside the SAME
    `if weight_version == champion_weight_version:` block as _calibrate_hold_max_bars,
    and the skip branch logs ensemble_ic.stop_target_calibration_skipped (source-level
    assertion, matching the plan's own "asserted by reading the dispatch" acceptance
    criterion).
    """
    source = Path(
        Path(__file__).parent.parent.parent / "services" / "ensemble_ic_engine.py"
    ).read_text()

    gate_idx = source.index("if weight_version == champion_weight_version:")
    else_idx = source.index("else:", gate_idx)
    gate_block = source[gate_idx:else_idx]
    assert "_calibrate_hold_max_bars" in gate_block
    assert "_calibrate_stop_target" in gate_block

    skip_block = source[else_idx : else_idx + 1200]
    assert "ensemble_ic.hold_max_bars_calibration_skipped" in skip_block
    assert "ensemble_ic.stop_target_calibration_skipped" in skip_block
    assert "scoped_weight_version_run" in skip_block
