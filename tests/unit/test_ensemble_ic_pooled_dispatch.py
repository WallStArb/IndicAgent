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
from src.observability.corpus_manifest import CorpusManifest

_T1 = datetime(2026, 1, 1, tzinfo=UTC)
_T2 = datetime(2026, 1, 1, 0, 5, tzinfo=UTC)


def _row(
    symbol: str,
    bar_ts: datetime,
    regime_label: str,
    alpha_score: float,
    return_fast: float | None = 0.001,
    return_mid: float | None = 0.002,
    return_slow: float | None = 0.003,
    return_extended: float | None = 0.004,
) -> dict:
    """A raw per-(symbol, bar_ts) row as _POOLED_WORKER_FETCH_SQL actually returns it
    (todo 148): suspect returns are already NULL-masked by that query's CASE
    expression before _aggregate_pooled_series ever sees the row -- there is no
    separate return_{scale}_suspect key here, only a possibly-None value. Pass
    return_fast=None (etc.) to simulate a suspect-flagged row for that scale."""
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

    def test_null_masked_return_excluded_from_its_own_column_mean_only(self):
        """todo 148 price-sanity guard: _POOLED_WORKER_FETCH_SQL's CASE expression
        already masks a suspect-flagged return to NULL before this function sees the
        row (a corrupt IBKR print poisons a raw cross-sectional mean by an unbounded
        amount, unlike a bounded rank-IC swap). _aggregate_pooled_series's existing
        `if value is not None` skip must exclude that NULL from its column's mean --
        but the row's OTHER scales (return_mid here) and alpha_score, which weren't
        masked, must still contribute normally. A corrupt exit price for one scale
        doesn't imply the other scales (different exit bars) are corrupt too."""
        rows = [
            _row("AAA", _T1, "mid_bull", alpha_score=0.1, return_fast=None, return_mid=0.02),
            _row("BBB", _T1, "mid_bull", alpha_score=0.3, return_fast=0.03, return_mid=0.04),
        ]

        pooled = _aggregate_pooled_series(rows, tf="5m")

        assert len(pooled) == 1
        # return_fast mean is BBB-only (0.03) -- AAA's NULL is excluded, not averaged in.
        assert pooled[0]["return_fast"] == pytest.approx(0.03)
        # return_mid and alpha_score are unaffected -- both symbols' values still pool.
        assert pooled[0]["return_mid"] == pytest.approx(0.03)
        assert pooled[0]["alpha_score"] == pytest.approx(0.2)

    def test_all_scales_null_masked_drops_symbol_from_every_return_mean(self):
        """If every scale is NULL-masked for one symbol's row, that symbol contributes
        to no return column's mean but still contributes to alpha_score (alpha_score
        has no suspect flag -- it isn't return-derived, so SQL never masks it)."""
        rows = [
            _row(
                "AAA",
                _T1,
                "mid_bull",
                alpha_score=0.1,
                return_fast=None,
                return_mid=None,
                return_slow=None,
                return_extended=None,
            ),
            _row("BBB", _T1, "mid_bull", alpha_score=0.3, return_fast=0.03),
        ]

        pooled = _aggregate_pooled_series(rows, tf="5m")

        assert pooled[0]["return_fast"] == pytest.approx(0.03)
        assert pooled[0]["alpha_score"] == pytest.approx(0.2)

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
    blending their rows. Without ea.weight_version filters in both fetch SQL constants,
    a run scoped to a challenger variant would silently measure the champion's
    ensemble_alpha rows too (SQL-text inspection, no live DB required)."""

    def test_per_symbol_fetch_sql_filters_by_weight_version(self):
        assert "ea.weight_version = %s" in _WORKER_FETCH_SQL

    def test_pooled_fetch_sql_filters_by_weight_version(self):
        assert "ea.weight_version = %s" in _POOLED_WORKER_FETCH_SQL

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
    ensemble_alpha emptiness check must be scoped to the resolved weight_version. An unscoped
    count(*) would pass as long as SOME other weight_version has rows, letting a
    typo'd/stale --weight-version silently complete with zero measured rows instead of
    crashing loud -- exactly the failure class this module's docstring says it prevents."""

    @pytest.mark.asyncio
    async def test_raises_when_ensemble_alpha_empty_for_weight_version(self):
        conn = AsyncMock()
        conn.fetchval.return_value = 0

        with pytest.raises(RuntimeError, match="v1_shrunk"):
            await _assert_prerequisites(conn, "v1_shrunk", tfs=["5m"])

    @pytest.mark.asyncio
    async def test_ensemble_alpha_count_query_is_scoped_by_weight_version_param(self, tmp_path):
        conn = AsyncMock()
        conn.fetchval.return_value = 5
        manifest = CorpusManifest("ensemble_trainer", tmp_path)
        manifest.set_inputs(weight_version="v1_shrunk")
        manifest.scope_suffix = "v1_shrunk"
        manifest.mark_success()
        manifest.write()

        await _assert_prerequisites(conn, "v1_shrunk", tfs=["5m"], manifest_dir=tmp_path)

        first_call = conn.fetchval.call_args_list[0]
        query_text = first_call.args[0]
        assert "weight_version" in query_text
        assert first_call.args[1] == "v1_shrunk"


class TestAssertPrerequisitesManifestGate:
    """Regression guard (2026-07-08 altitude review): ensemble_alpha having nonzero rows
    for a weight_version is not sufficient evidence the ensemble_trainer run that wrote
    them finished -- its 'full replace' delete-then-repopulate can be interrupted mid-run
    by a crash, leaving nonzero but incomplete rows. _assert_prerequisites must also
    check ensemble_trainer's manifest for that exact weight_version before trusting the
    row counts checked above it."""

    @pytest.mark.asyncio
    async def test_raises_when_no_trainer_manifest_exists(self, tmp_path):
        conn = AsyncMock()
        conn.fetchval.return_value = 5

        with pytest.raises(RuntimeError, match="No manifest found for prerequisite step"):
            await _assert_prerequisites(conn, "v1_shrunk", tfs=["5m"], manifest_dir=tmp_path)

    @pytest.mark.asyncio
    async def test_raises_when_manifest_content_disagrees_with_its_own_scoped_file(self, tmp_path):
        """A manifest written under the v1_shrunk-scoped filename but whose recorded
        inputs.weight_version says something else (a corrupted/mislabeled file) must
        still be rejected -- the input-matching check is defense in depth on top of
        filename scoping, not a substitute for it."""
        conn = AsyncMock()
        conn.fetchval.return_value = 5
        manifest = CorpusManifest("ensemble_trainer", tmp_path)
        manifest.set_inputs(weight_version="v1")
        manifest.scope_suffix = "v1_shrunk"
        manifest.mark_success()
        manifest.write()

        with pytest.raises(RuntimeError, match="does not match this run's inputs"):
            await _assert_prerequisites(conn, "v1_shrunk", tfs=["5m"], manifest_dir=tmp_path)

    @pytest.mark.asyncio
    async def test_raises_when_manifest_status_is_not_success(self, tmp_path):
        conn = AsyncMock()
        conn.fetchval.return_value = 5
        manifest = CorpusManifest("ensemble_trainer", tmp_path)
        manifest.set_inputs(weight_version="v1_shrunk")
        manifest.scope_suffix = "v1_shrunk"
        manifest.add_error("crashed mid-run")
        manifest.write()

        with pytest.raises(RuntimeError, match="status='failed'"):
            await _assert_prerequisites(conn, "v1_shrunk", tfs=["5m"], manifest_dir=tmp_path)

    @pytest.mark.asyncio
    async def test_passes_when_manifest_matches_and_succeeded(self, tmp_path):
        conn = AsyncMock()
        conn.fetchval.return_value = 5
        manifest = CorpusManifest("ensemble_trainer", tmp_path)
        manifest.set_inputs(weight_version="v1_shrunk")
        manifest.scope_suffix = "v1_shrunk"
        manifest.mark_success()
        manifest.write()

        await _assert_prerequisites(conn, "v1_shrunk", tfs=["5m"], manifest_dir=tmp_path)

    @pytest.mark.asyncio
    async def test_does_not_confuse_two_different_weight_versions_manifests(self, tmp_path):
        """Regression guard for the exact bug this scope_suffix mechanism fixes: a
        crashed run for one weight_version must never affect a completely different,
        still-healthy weight_version's gate check -- they must live in separate
        manifest files, not overwrite the same one."""
        conn = AsyncMock()
        conn.fetchval.return_value = 5

        healthy = CorpusManifest("ensemble_trainer", tmp_path)
        healthy.set_inputs(weight_version="v1")
        healthy.scope_suffix = "v1"
        healthy.mark_success()
        healthy.write()

        crashed = CorpusManifest("ensemble_trainer", tmp_path)
        crashed.set_inputs(weight_version="v1_shrunk")
        crashed.scope_suffix = "v1_shrunk"
        crashed.add_error("simulated crash")
        crashed.write()

        # The healthy v1 run's gate must still pass, unaffected by the unrelated
        # v1_shrunk run's failure.
        await _assert_prerequisites(conn, "v1", tfs=["5m"], manifest_dir=tmp_path)

        # The crashed v1_shrunk run's gate must still correctly raise.
        with pytest.raises(RuntimeError, match="status='failed'"):
            await _assert_prerequisites(conn, "v1_shrunk", tfs=["5m"], manifest_dir=tmp_path)
