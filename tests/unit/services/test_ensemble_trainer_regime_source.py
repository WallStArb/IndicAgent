"""Unit tests: ensemble_trainer's stratum source is cross-sectional POOLED IC, never
the per-symbol feature_vectors regime column (Phase 172 Plan 07).

Purpose: 172-RESEARCH.md's inventory lists ensemble_trainer.py as a downstream
regime consumer of Phase 172's cutover. Reading the module's own query text shows
its stratum-discovery/eligibility filter is `symbol = 'POOLED' AND is_pooled = true
AND regime != '_pooled'` (CLAUDE.md Key Decisions, load-bearing) -- cross-sectional
POOLED rows written by ic_engine.py's market_regimes-stratified pass, structurally
independent of feature_vectors.regime / feature_vectors.regime_volatility (the
per-symbol HMM columns plan 172-06 repointed). This file pins that independence by
test rather than by argument: no source change was required or made in plan 172-06
or 172-07 for ensemble_trainer.py to keep working correctly under the cutover.

Two techniques, matching this codebase's own established conventions:
  - Source-inspection assertions (inspect.getsource + string checks), mirroring
    plan 172-06's test_ic_engine.py pattern and this file's own
    test_ensemble_trainer_alignment_gate.py precedent -- reads the query text from
    the module's own source rather than a re-typed copy, so a test goes red if the
    real query changes.
  - One direct behavioral test driving the real _process_stratum() end-to-end twice
    (regime='trending_up' vs regime='calm') with otherwise-identical synthetic
    inputs, proving no branch anywhere in the stratum-processing path keys off the
    regime label string itself -- pure opaque-parameter treatment, not just an
    absence-of-reference argument.
"""

from __future__ import annotations

import asyncio
import inspect
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

_project_root = Path(__file__).parent.parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

import services.ensemble_trainer as ensemble_trainer_module
from services.ensemble_trainer import EnsembleConfig, EnsembleTrainer, _eligibility_where

# ---------------------------------------------------------------------------
# Source-inspection helpers
# ---------------------------------------------------------------------------


def _strata_discovery_query_source() -> str:
    """Extract the literal SELECT DISTINCT tf, regime ... ORDER BY tf, regime block
    from services/ensemble_trainer.py's own module source -- not a re-typed copy, so
    this goes stale (and the tests using it go red) if the query text is edited."""
    module_source = inspect.getsource(ensemble_trainer_module)
    match = re.search(
        r"SELECT DISTINCT tf, regime.*?ORDER BY tf, regime",
        module_source,
        re.DOTALL,
    )
    assert match is not None, (
        "Could not locate the strata-discovery 'SELECT DISTINCT tf, regime' query "
        "in services/ensemble_trainer.py -- has it been renamed or restructured?"
    )
    return match.group(0)


def _process_stratum_source() -> str:
    """Full source of EnsembleTrainer._process_stratum, for label-string
    special-casing and regime-column-reference checks."""
    return inspect.getsource(EnsembleTrainer._process_stratum)


def _fv_join_query_source() -> str:
    """Extract the feature_vectors/market_regimes JOIN query block inside
    _process_stratum -- the query that actually fetches the feature matrix for a
    stratum's bars."""
    source = _process_stratum_source()
    match = re.search(
        r"SELECT fv\.symbol.*?ORDER BY fv\.bar_ts, fv\.symbol",
        source,
        re.DOTALL,
    )
    assert match is not None, (
        "Could not locate the fv_rows feature-matrix query in _process_stratum -- "
        "has it been renamed or restructured?"
    )
    return match.group(0)


# Both regime vocabularies -- old per-symbol trend labels (retired by plan 172-06)
# and new per-symbol volatility labels (live) -- neither should ever appear as a
# literal string comparison anywhere in _process_stratum's source. ensemble_trainer
# treats `regime` purely as an opaque GROUP BY / bound-parameter key throughout.
_TREND_VOCAB = {"trending_up", "trending_down", "ranging", "transition_up", "transition_down"}
_VOLATILITY_VOCAB = {"calm", "elevated", "turbulent"}


# ---------------------------------------------------------------------------
# 1. _eligibility_where -- the shared builder behind every consumer below
# ---------------------------------------------------------------------------


def test_eligibility_where_base_contains_required_clauses():
    """The three clauses CLAUDE.md's Key Decisions calls load-bearing must all be
    present in the real, live query text -- read from the function's own return
    value, not re-typed, so this goes red if any clause is edited or removed.
    Verified manually during authoring: commenting out the `regime != '_pooled'`
    clause in _eligibility_where and re-running this test produces a failure;
    restoring the clause restores green (see SUMMARY for the transcript)."""
    base_where, _ = _eligibility_where(sign_symmetric=False)

    assert "symbol = 'POOLED'" in base_where
    assert "is_pooled = true" in base_where
    assert "regime != '_pooled'" in base_where


def test_eligibility_where_full_adds_passes_fdr_without_dropping_base_clauses():
    """The 'full' variant (used by strata discovery) must still carry all three
    base clauses plus passes_fdr=true -- strata discovery must never train on
    cells that failed BH-FDR."""
    base_where, full_where = _eligibility_where(sign_symmetric=False)

    assert base_where in full_where
    assert "passes_fdr = true" in full_where


# ---------------------------------------------------------------------------
# 2. Strata-discovery query -- must read feature_ic_scores only
# ---------------------------------------------------------------------------


def test_strata_discovery_query_selects_distinct_tf_regime_from_feature_ic_scores():
    """The stratum-discovery SQL selects DISTINCT tf, regime from feature_ic_scores
    and is driven by the real eligibility_where value (not a hardcoded string)."""
    query = _strata_discovery_query_source()

    assert "FROM feature_ic_scores" in query
    assert "{eligibility_where}" in query, (
        "Strata query must be built from _eligibility_where()'s return value, not "
        "a re-typed literal -- confirms the SELECT-DISTINCT filter and the "
        "eligibility gate can never silently drift apart."
    )
    assert "AND regime IS NOT NULL" in query


def test_strata_discovery_query_does_not_reference_feature_vectors_or_regime_volatility():
    """The stratum-discovery SQL must not reference feature_vectors, the per-symbol
    regime_volatility column, or the symbol_hmm regime_scope -- its label source is
    exclusively the cross-sectional POOLED rows in feature_ic_scores."""
    query = _strata_discovery_query_source()

    assert "feature_vectors" not in query
    assert "regime_volatility" not in query
    assert "regime_scope" not in query
    assert "symbol_hmm" not in query


# ---------------------------------------------------------------------------
# 3. _process_stratum -- regime is an opaque bound parameter, never a literal
# ---------------------------------------------------------------------------


def test_process_stratum_never_special_cases_any_regime_label_string():
    """No branch in _process_stratum's source may compare `regime` against a
    literal label string from either vocabulary -- old trend labels (retired by
    plan 172-06) or new volatility labels (live). If this test ever needs to
    change, ensemble_trainer.py has stopped treating regime as opaque, which is
    exactly the regression this file exists to catch."""
    source = _process_stratum_source()

    for label in _TREND_VOCAB | _VOLATILITY_VOCAB:
        assert f'"{label}"' not in source, f"found literal comparison against {label!r}"
        assert f"'{label}'" not in source, f"found literal comparison against {label!r}"


def test_process_stratum_ic_rows_query_binds_regime_as_parameter():
    """_process_stratum's own feature_ic_scores fetch (ic_rows) binds tf/regime as
    parameters ($1/$2), not string-interpolated -- confirms no per-label branching
    is even structurally possible at the SQL-construction layer."""
    source = _process_stratum_source()

    assert "tf = $1 AND regime = $2" in source


def test_fv_join_query_does_not_select_or_filter_on_feature_vectors_regime_column():
    """The feature-matrix fetch joins feature_vectors to market_regimes and filters
    on mr.regime_label (the cross-sectional label) -- it must never select or
    filter on fv.regime or fv.regime_volatility (the per-symbol HMM columns)."""
    query = _fv_join_query_source()

    assert "mr.regime_label = $2" in query
    assert "fv.regime_volatility" not in query
    assert re.search(r"fv\.regime\b(?!_)", query) is None, (
        "fv_rows query must not select/filter on fv.regime -- cross-sectional "
        "stratification reads mr.regime_label only"
    )


# ---------------------------------------------------------------------------
# 4. Behavioral: a 'calm' stratum is processed identically to a cross-sectional
#    stratum -- the actual claim under test, not just an absence-of-reference.
# ---------------------------------------------------------------------------


class _FakeConn:
    """Dispatches conn.fetch() by SQL substring; records conn.executemany() calls
    for weight-row inspection. Mirrors test_ensemble_trainer_alignment_gate.py's
    _FakeConn idiom (captured_sql / canned-rows-by-call) extended with the two
    extra primitives _process_stratum needs: transaction() and executemany()."""

    def __init__(self, ic_rows: list[dict], fv_rows: list[dict]):
        self._ic_rows = ic_rows
        self._fv_rows = fv_rows
        self.executemany_calls: list[tuple[str, list[tuple]]] = []

    async def fetch(self, sql: str, *args):
        if "FROM feature_ic_scores" in sql:
            return self._ic_rows
        if "FROM feature_vectors" in sql:
            return self._fv_rows
        raise AssertionError(f"Unexpected query in test fake: {sql[:120]!r}")

    async def executemany(self, sql: str, rows):
        self.executemany_calls.append((sql, list(rows)))

    def transaction(self):
        return _NullAsyncContext()

    def weight_rows(self) -> list[tuple]:
        for sql, rows in self.executemany_calls:
            if "INSERT INTO ensemble_weights" in sql:
                return rows
        raise AssertionError("no ensemble_weights executemany call recorded")

    def alpha_rows(self) -> list[tuple]:
        for sql, rows in self.executemany_calls:
            if "INSERT INTO ensemble_alpha" in sql:
                return rows
        raise AssertionError("no ensemble_alpha executemany call recorded")


class _NullAsyncContext:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


def _synthetic_ic_rows() -> list[dict]:
    now = datetime.now(UTC)
    return [
        {
            "feature_name": "feat_a",
            "ic_sharpe_hac": 0.5,
            "ic_shrunk": 0.5,
            "shrinkage_weight": 1.0,
            "ic_ci_lower": 0.10,
            "ic_ci_upper": 0.90,
            "ic_sign": 1,
            "lookahead_bars": 5,
            "training_window_end": now,
        },
        {
            "feature_name": "feat_b",
            "ic_sharpe_hac": 0.3,
            "ic_shrunk": 0.3,
            "shrinkage_weight": 1.0,
            "ic_ci_lower": 0.05,
            "ic_ci_upper": 0.60,
            "ic_sign": 1,
            "lookahead_bars": 5,
            "training_window_end": now,
        },
    ]


def _synthetic_fv_rows() -> list[dict]:
    return [
        {"symbol": "SPY", "feat_a": 1.00, "feat_b": 2.00, "bar_ts": 1},
        {"symbol": "QQQ", "feat_a": 1.50, "feat_b": 1.80, "bar_ts": 1},
        {"symbol": "SPY", "feat_a": 1.20, "feat_b": 2.10, "bar_ts": 2},
        {"symbol": "QQQ", "feat_a": 1.60, "feat_b": 1.90, "bar_ts": 2},
        {"symbol": "SPY", "feat_a": 0.90, "feat_b": 1.95, "bar_ts": 3},
        {"symbol": "QQQ", "feat_a": 1.55, "feat_b": 1.85, "bar_ts": 3},
    ]


def _run_process_stratum(regime: str) -> tuple[EnsembleTrainer, _FakeConn]:
    trainer = EnsembleTrainer(db_dsn="postgresql://fake/fake")
    config = EnsembleConfig(
        max_feature_weight=0.90,
        effective_n_gate=1.0,
        weight_version="test",
        min_passing_features=2,
        max_cluster_corr=0.80,
        max_cluster_weight=0.90,
        meta_fdr_min_fraction=0.50,
        meta_fdr_min_cells=1,
        sharpe_floor=0.025,
        weight_half_life_days=30.0,
        weight_stale_max_days=90,
        ic_input="ic_sharpe_hac",
        weight_method="ic_proportional",
        mv_condition_max=1000.0,
        sign_symmetric=False,
    )
    conn = _FakeConn(ic_rows=_synthetic_ic_rows(), fv_rows=_synthetic_fv_rows())
    wrote = asyncio.run(
        trainer._process_stratum(
            conn=conn,
            tf="1d",
            regime=regime,
            feature_cols=["feat_a", "feat_b"],
            config=config,
            cfg={},
            meta_eligible_features={"feat_a", "feat_b"},
        )
    )
    assert wrote is True, f"_process_stratum did not write for regime={regime!r}"
    return trainer, conn


def test_calm_stratum_processed_identically_to_cross_sectional_stratum():
    """Drive the real _process_stratum() twice with byte-identical synthetic IC
    and feature data, varying only the regime label: 'trending_up' (a retired
    cross-sectional-shaped label) vs 'calm' (a volatility label). The resulting
    ensemble_weights rows must be identical except for the regime field itself --
    proving regime is consumed as an opaque GROUP BY key with zero special-casing,
    exactly as the module's own docstrings claim. This is the behavioral claim
    plan 172-06's column-name repoint in ic_engine.py could not have affected."""
    _, conn_cross_sectional = _run_process_stratum("trending_up")
    _, conn_volatility = _run_process_stratum("calm")

    # --- ensemble_weights rows: (symbol, tf, regime, weight_version, feature_name,
    # raw_weight, weight, ic_sharpe, lookahead_bars, effective_n) ---
    cs_weight_rows = conn_cross_sectional.weight_rows()
    vol_weight_rows = conn_volatility.weight_rows()
    assert len(cs_weight_rows) == len(vol_weight_rows) == 2

    # Index 2 = regime, index 10 = computed_at (a fresh datetime.now(UTC) captured
    # once per _process_stratum call -- excluded since the two invocations run at
    # microseconds-apart wall-clock times, not because it could ever legitimately
    # differ for a real reason tied to the regime label).
    WEIGHT_REGIME_IDX = 2
    WEIGHT_TS_IDX = 10
    for cs_row, vol_row in zip(cs_weight_rows, vol_weight_rows):
        assert cs_row[WEIGHT_REGIME_IDX] == "trending_up"
        assert vol_row[WEIGHT_REGIME_IDX] == "calm"

        def _strip(row: tuple) -> tuple:
            return tuple(
                v for i, v in enumerate(row) if i not in (WEIGHT_REGIME_IDX, WEIGHT_TS_IDX)
            )

        assert _strip(cs_row) == _strip(vol_row)

    # --- ensemble_alpha rows: (symbol, tf, bar_ts, weight_version, regime,
    # alpha_score, alpha_ci_lower, alpha_ci_upper, effective_n, n_features_active,
    # computed_at) -- regime at index 4 here, a DIFFERENT position than the weights
    # table, exercising a second, independent write path against the same claim. ---
    cs_alpha_rows = conn_cross_sectional.alpha_rows()
    vol_alpha_rows = conn_volatility.alpha_rows()
    assert len(cs_alpha_rows) == len(vol_alpha_rows) == len(_synthetic_fv_rows())

    ALPHA_REGIME_IDX = 4
    ALPHA_TS_IDX = 10
    for cs_row, vol_row in zip(cs_alpha_rows, vol_alpha_rows):
        assert cs_row[ALPHA_REGIME_IDX] == "trending_up"
        assert vol_row[ALPHA_REGIME_IDX] == "calm"

        def _strip(row: tuple) -> tuple:
            return tuple(v for i, v in enumerate(row) if i not in (ALPHA_REGIME_IDX, ALPHA_TS_IDX))

        assert _strip(cs_row) == _strip(vol_row)


def test_volatility_label_iterated_as_ordinary_stratum_no_exception():
    """A stub result set whose regime is a volatility label ('elevated') is
    processed without any special handling, error, or divergent code path --
    confirms plan 172-06's column-name repoint required no change here."""
    trainer, conn = _run_process_stratum("elevated")

    assert len(conn.executemany_calls) == 2
    assert all(row[2] == "elevated" for row in conn.weight_rows())
    assert all(row[4] == "elevated" for row in conn.alpha_rows())


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
