"""Unit tests: pooled cross-sectional aggregation grain (todo 046 / D-01, Wave 0).

_aggregate_pooled_series is a pure, importable helper in services/ensemble_ic_engine.py.
Given raw per-(symbol, bar_ts) rows fetched by _POOLED_WORKER_FETCH_SQL, it reduces them
to one row per (tf, regime, bar_ts) cell by averaging alpha_score + forward returns
across symbols -- grouping by (tf, regime, bar_ts) BEFORE averaging, never averaging
first and labeling second (RESEARCH.md Pitfall 5).

No DB, no Kafka. Pure Python -- feeds synthetic in-memory dicts, matching the
psycopg2.extras.RealDictCursor row shape produced by _POOLED_WORKER_FETCH_SQL.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

project_root = Path(__file__).parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from services.ensemble_ic_engine import (
    _ENSEMBLE_IC_INSERT_SQL,
    _POOLED_SYMBOL,
    _POOLED_WORKER_FETCH_SQL,
    _WORKER_FETCH_SQL,
    _aggregate_pooled_series,
    _assert_prerequisites,
    build_ensemble_ic_row,
)

_T1 = datetime(2026, 1, 1, tzinfo=UTC)
_T2 = datetime(2026, 1, 1, 0, 5, tzinfo=UTC)


def _row(
    symbol: str,
    bar_ts: datetime,
    regime_label: str,
    alpha_score: float,
    return_fast: float = 0.001,
    return_mid: float = 0.002,
    return_slow: float = 0.003,
    return_extended: float = 0.004,
) -> dict:
    return {
        "symbol": symbol,
        "bar_ts": bar_ts,
        "regime_label": regime_label,
        "alpha_score": alpha_score,
        "return_fast": return_fast,
        "return_mid": return_mid,
        "return_slow": return_slow,
        "return_extended": return_extended,
    }


class TestAggregatePooledSeries:
    def test_pools_alpha_score_as_mean_across_symbols_at_same_cell(self):
        """3 symbols sharing one (tf, regime, bar_ts) cell -> pooled alpha_score is
        the mean of the 3 symbols' alpha_score at that bar_ts."""
        rows = [
            _row("AAA", _T1, "mid_bull", alpha_score=0.1),
            _row("BBB", _T1, "mid_bull", alpha_score=0.2),
            _row("CCC", _T1, "mid_bull", alpha_score=0.3),
        ]

        pooled = _aggregate_pooled_series(rows, tf="5m")

        assert len(pooled) == 1
        assert pooled[0]["bar_ts"] == _T1
        assert pooled[0]["regime_label"] == "mid_bull"
        assert pooled[0]["alpha_score"] == pytest.approx(0.2)

    def test_also_pools_forward_returns_as_mean_across_symbols(self):
        """Not just alpha_score -- every _POOLED_VALUE_COLS column is averaged so the
        pooled row is a paired (alpha, return) observation, not alpha-only."""
        rows = [
            _row("AAA", _T1, "mid_bull", alpha_score=0.1, return_fast=0.01),
            _row("BBB", _T1, "mid_bull", alpha_score=0.3, return_fast=0.03),
        ]

        pooled = _aggregate_pooled_series(rows, tf="5m")

        assert len(pooled) == 1
        assert pooled[0]["alpha_score"] == pytest.approx(0.2)
        assert pooled[0]["return_fast"] == pytest.approx(0.02)

    def test_different_regime_labels_at_same_bar_ts_are_not_mixed(self):
        """Regression guard (RESEARCH.md Pitfall 5): if two rows share a bar_ts but
        carry DIFFERENT regime_label values, they must produce TWO separate pooled
        cells, not one row averaging across regimes. An average-first-label-second
        implementation would collapse this into a single row with alpha_score=0.2
        (mean of 0.1 and 0.3) -- this test fails under that implementation."""
        rows = [
            _row("AAA", _T1, "mid_bull", alpha_score=0.1),
            _row("BBB", _T1, "low_bear", alpha_score=0.3),
        ]

        pooled = _aggregate_pooled_series(rows, tf="5m")

        assert len(pooled) == 2
        by_regime = {r["regime_label"]: r for r in pooled}
        assert set(by_regime) == {"mid_bull", "low_bear"}
        # Each cell keeps its own single-symbol value -- never blended with the other
        # regime's observation.
        assert by_regime["mid_bull"]["alpha_score"] == pytest.approx(0.1)
        assert by_regime["low_bear"]["alpha_score"] == pytest.approx(0.3)

    def test_groups_by_bar_ts_separately_even_within_same_regime(self):
        """Two distinct bar_ts within the same regime must remain two distinct pooled
        cells (grain is (tf, regime, bar_ts), not (tf, regime))."""
        rows = [
            _row("AAA", _T1, "mid_bull", alpha_score=0.1),
            _row("BBB", _T1, "mid_bull", alpha_score=0.3),
            _row("AAA", _T2, "mid_bull", alpha_score=0.9),
        ]

        pooled = _aggregate_pooled_series(rows, tf="5m")

        assert len(pooled) == 2
        by_ts = {r["bar_ts"]: r for r in pooled}
        assert by_ts[_T1]["alpha_score"] == pytest.approx(0.2)
        assert by_ts[_T2]["alpha_score"] == pytest.approx(0.9)

    def test_pooled_cell_symbol_matches_pooled_sentinel_and_check_constraint(self):
        """A pooled cell built for a (tf, regime) produces a row whose symbol equals
        _POOLED_SYMBOL and satisfies (symbol='POOLED')=is_pooled (migration 195's
        alpha_ensemble_ic_pooled_symbol_consistent CHECK constraint contract)."""
        rows = [_row("AAA", _T1, "mid_bull", alpha_score=0.1)]
        pooled = _aggregate_pooled_series(rows, tf="5m")
        assert len(pooled) == 1

        built_row = build_ensemble_ic_row(
            symbol=_POOLED_SYMBOL,
            tf="5m",
            regime=pooled[0]["regime_label"],
            lookahead="fast",
            lookahead_bars=1,
            run_ts=datetime.now(UTC),
            weight_version="v1",
        )

        assert built_row["symbol"] == _POOLED_SYMBOL
        assert built_row["is_pooled"] is True
        # CHECK constraint identity: (symbol = 'POOLED') = is_pooled
        assert (built_row["symbol"] == "POOLED") == built_row["is_pooled"]
        assert built_row["weight_version"] == "v1"

    def test_empty_input_yields_no_pooled_row_and_no_divide_by_zero(self):
        """Empty input -> empty output, no ZeroDivisionError / no crash."""
        pooled = _aggregate_pooled_series([], tf="5m")
        assert pooled == []

    def test_rows_missing_regime_label_are_dropped_not_crashed(self):
        """A row with regime_label=None cannot be assigned to a stratum -- dropped,
        not included in any pooled cell, no exception."""
        rows = [
            _row("AAA", _T1, None, alpha_score=0.1),
            _row("BBB", _T1, "mid_bull", alpha_score=0.3),
        ]

        pooled = _aggregate_pooled_series(rows, tf="5m")

        assert len(pooled) == 1
        assert pooled[0]["alpha_score"] == pytest.approx(0.3)

    def test_output_sorted_by_bar_ts(self):
        rows = [
            _row("AAA", _T2, "mid_bull", alpha_score=0.9),
            _row("BBB", _T1, "mid_bull", alpha_score=0.1),
        ]

        pooled = _aggregate_pooled_series(rows, tf="5m")

        assert [r["bar_ts"] for r in pooled] == [_T1, _T2]


class TestWeightVersionScoping:
    """Regression guard for the migration-196 fix: alpha_ensemble_ic must be keyed by
    weight_version so Plan 05's A/B judge can compare two weight variants without
    blending their rows. Without ae.weight_version filters in both fetch SQL constants,
    a run scoped to a challenger variant would silently measure the champion's
    alpha_events rows too (SQL-text inspection, no live DB required)."""

    def test_per_symbol_fetch_sql_filters_by_weight_version(self):
        assert "ae.weight_version = %s" in _WORKER_FETCH_SQL

    def test_pooled_fetch_sql_filters_by_weight_version(self):
        assert "ae.weight_version = %s" in _POOLED_WORKER_FETCH_SQL

    def test_insert_sql_writes_weight_version_column(self):
        assert "weight_version" in _ENSEMBLE_IC_INSERT_SQL

    def test_build_ensemble_ic_row_requires_weight_version(self):
        row = build_ensemble_ic_row(
            symbol=_POOLED_SYMBOL,
            tf="5m",
            regime="mid_bull",
            lookahead="fast",
            lookahead_bars=1,
            run_ts=_T1,
            weight_version="v1_shrunk",
        )
        assert row["weight_version"] == "v1_shrunk"


class TestAssertPrerequisitesWeightVersionScoped:
    """Regression guard for CR-01 (code review, 142B.1-REVIEW.md): _assert_prerequisites'
    alpha_events emptiness check must be scoped to the resolved weight_version. An unscoped
    count(*) would pass as long as SOME other weight_version has rows, letting a
    typo'd/stale --weight-version silently complete with zero measured rows instead of
    crashing loud -- exactly the failure class this module's docstring says it prevents."""

    @pytest.mark.asyncio
    async def test_raises_when_alpha_events_empty_for_weight_version(self):
        conn = AsyncMock()
        conn.fetchval.return_value = 0

        with pytest.raises(RuntimeError, match="weight_version='v1_shrunk'|v1_shrunk"):
            await _assert_prerequisites(conn, "v1_shrunk", tfs=["5m"])

    @pytest.mark.asyncio
    async def test_alpha_events_count_query_is_scoped_by_weight_version_param(self):
        conn = AsyncMock()
        conn.fetchval.return_value = 5

        await _assert_prerequisites(conn, "v1_shrunk", tfs=["5m"])

        first_call = conn.fetchval.call_args_list[0]
        query_text = first_call.args[0]
        assert "weight_version" in query_text
        assert first_call.args[1] == "v1_shrunk"
