"""Unit tests for services/feature_lifecycle.py (phase 186 plan 09, D-30).

Feature status is data quality: computed, valid, covered. Pure derivation is tested
directly; the batch node runs against a fake asyncpg connection (no DB).
"""

from __future__ import annotations

import inspect
from datetime import UTC, datetime, timedelta

import pytest

import services.feature_lifecycle as fl
from services.feature_lifecycle import (
    Evaluation,
    LifecycleConfig,
    LifecycleGate,
    build_tf_query,
    derive_feature_transition,
    evidence_key,
    latest_per_window,
    quote_feature_column,
)

_W1 = datetime(2025, 6, 24, 5, 15, tzinfo=UTC)
_W2 = datetime(2025, 12, 24, 5, 15, tzinfo=UTC)
_W3 = datetime(2026, 6, 24, 5, 15, tzinfo=UTC)
_T0 = datetime(2026, 9, 1, tzinfo=UTC)

_GATE = LifecycleGate(demotion_min_consecutive=2, recovery_min_passes=1)


def _eval(window, passed, *, status="active", at=None) -> Evaluation:
    return Evaluation(
        window_end=window,
        evaluated_status=status,
        passed=passed,
        n_observations=1000,
        guard_status="ok",
        evaluated_at=at or _T0,
    )


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


def test_config_reads_only_the_four_feature_keys():
    seen: list[str] = []

    def fake_cfg(cfg, key, default):
        seen.append(key)
        return default

    original = fl._cfg
    fl._cfg = fake_cfg
    try:
        config = LifecycleConfig.from_apr({})
    finally:
        fl._cfg = original
    assert sorted(seen) == [
        "feature.coverage.min_symbol_fraction",
        "feature.lifecycle.demotion_min_consecutive",
        "feature.lifecycle.lookback_days",
        "feature.lifecycle.recovery_min_passes",
    ]
    assert config == LifecycleConfig(0.95, 90, 2, 1)


# ---------------------------------------------------------------------------
# Derivation
# ---------------------------------------------------------------------------


class TestDerivation:
    def test_single_failing_window_does_not_demote(self):
        assert derive_feature_transition("active", None, [_eval(_W1, False)], _GATE) is None

    def test_two_failing_windows_demote_with_data_quality_fail(self):
        t = derive_feature_transition("active", None, [_eval(_W1, False), _eval(_W2, False)], _GATE)
        assert t.to_status == "shadow_only" and t.reason == "data_quality_fail"
        assert t.n_windows == 2 and t.evidence.window_end == _W2

    def test_passing_window_restores_shadow_only(self):
        t = derive_feature_transition(
            "shadow_only", None, [_eval(_W1, True, status="shadow_only")], _GATE
        )
        assert t.to_status == "active" and t.reason == "data_quality_restored"

    def test_failing_window_does_not_restore(self):
        evals = [_eval(_W1, False, status="shadow_only")]
        assert derive_feature_transition("shadow_only", None, evals, _GATE) is None

    def test_recomputing_one_window_never_counts_as_new_evidence(self):
        evals = [_eval(_W1, False, at=_T0 + timedelta(days=d)) for d in range(5)]
        assert derive_feature_transition("active", None, evals, _GATE) is None

    def test_latest_evaluation_of_a_window_supersedes(self):
        evals = [
            _eval(_W1, False),
            _eval(_W2, False, at=_T0),
            _eval(_W2, True, at=_T0 + timedelta(days=1)),
        ]
        assert derive_feature_transition("active", None, evals, _GATE) is None

    def test_intervening_pass_resets_streak(self):
        evals = [_eval(_W1, False), _eval(_W2, True), _eval(_W3, False)]
        assert derive_feature_transition("active", None, evals, _GATE) is None

    def test_evidence_before_entering_status_is_ignored(self):
        since = _T0 + timedelta(days=10)
        evals = [_eval(_W1, False, at=_T0), _eval(_W2, False, at=since + timedelta(days=1))]
        assert derive_feature_transition("active", since, evals, _GATE) is None

    def test_evidence_under_another_status_is_ignored(self):
        evals = [_eval(_W1, False, status="shadow_only"), _eval(_W2, False)]
        assert derive_feature_transition("active", None, evals, _GATE) is None

    @pytest.mark.parametrize("status", ["candidate", "deprecated"])
    def test_ungoverned_status_never_transitions(self, status):
        evals = [_eval(_W1, False, status=status), _eval(_W2, False, status=status)]
        assert derive_feature_transition(status, None, evals, _GATE) is None


def test_latest_per_window_orders_by_window():
    latest = latest_per_window([_eval(_W3, True), _eval(_W1, True), _eval(_W2, True)])
    assert [e.window_end for e in latest] == [_W1, _W2, _W3]


# ---------------------------------------------------------------------------
# Evidence key
# ---------------------------------------------------------------------------

_RULE = LifecycleConfig(0.95, 90, 2, 1).rule_fingerprint()
_ROWS = [{"tf": "1d", "symbol_coverage": 1.0, "n_non_finite": 0}]


class TestEvidenceKey:
    def test_identical_evidence_gives_identical_key(self):
        assert evidence_key("active", _RULE, _ROWS) == evidence_key("active", _RULE, list(_ROWS))

    def test_changed_statistic_changes_key(self):
        other = [{"tf": "1d", "symbol_coverage": 0.9, "n_non_finite": 0}]
        assert evidence_key("active", _RULE, _ROWS) != evidence_key("active", _RULE, other)

    def test_changed_rule_changes_key(self):
        rule = LifecycleConfig(0.9, 90, 2, 1).rule_fingerprint()
        assert evidence_key("active", _RULE, _ROWS) != evidence_key("active", rule, _ROWS)

    def test_changed_status_changes_key(self):
        assert evidence_key("active", _RULE, _ROWS) != evidence_key("shadow_only", _RULE, _ROWS)


# ---------------------------------------------------------------------------
# Query construction
# ---------------------------------------------------------------------------

_COLS = {"momentum_z": "real", "hour_of_day": "integer", "rsi": "double precision"}


def test_quote_feature_column_rejects_unknown_name():
    assert quote_feature_column("rsi", _COLS) == '"rsi"'
    with pytest.raises(ValueError):
        quote_feature_column('rsi"; DROP TABLE x; --', _COLS)


def test_tf_query_counts_non_finite_only_on_float_columns():
    sql = build_tf_query(["momentum_z", "hour_of_day", "rsi"], _COLS)
    assert "FROM feature_vectors" in sql
    assert "'NaN'::real" in sql and "'NaN'::double precision" in sql
    assert "0::bigint AS x1" in sql
    assert "GROUP BY symbol" in sql


# ---------------------------------------------------------------------------
# Batch node against a fake connection
# ---------------------------------------------------------------------------


class _Tx:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _FakeConn:
    def __init__(self, *, concepts, columns, tfs, agg, evaluations=()):
        self.concepts = concepts
        self.columns = columns
        self.tfs = tfs
        self.agg = agg  # tf -> list of {symbol, n_rows, <col>: (populated, non_finite)}
        self.evaluations = list(evaluations)
        self.writes: list[str] = []

    def transaction(self):
        return _Tx()

    async def fetch(self, sql, *args):
        if "FROM concept_registry" in sql:
            return self.concepts
        if "information_schema.columns" in sql:
            return [{"column_name": c, "data_type": t} for c, t in self.columns.items()]
        if "SELECT DISTINCT tf" in sql:
            return [{"tf": t} for t in self.tfs]
        if "FROM concept_evaluation" in sql:
            return self.evaluations
        if "FROM feature_vectors" in sql:
            tf = args[0]
            names = [c for c in self.columns if f'"{c}"' in sql]
            # order of appearance in the query is the chunk order
            names.sort(key=lambda c: sql.index(f'"{c}"'))
            rows = []
            for sym in self.agg[tf]:
                row = {"symbol": sym["symbol"], "n_rows": sym["n_rows"]}
                for i, name in enumerate(names):
                    populated, bad = sym.get(name, (sym["n_rows"], 0))
                    row[f"c{i}"], row[f"x{i}"] = populated, bad
                rows.append(row)
            return rows
        raise AssertionError(f"unexpected fetch: {sql[:60]}")

    async def execute(self, sql, *args):
        self.writes.append(sql)
        return "UPDATE 1"

    async def executemany(self, sql, rows):
        self.writes.append(sql)

    async def fetchrow(self, sql, *args):
        self.writes.append(sql)
        return None

    async def fetchval(self, sql, *args):
        self.writes.append(sql)
        return None


def _concept(name, status, cid=None):
    return {"concept_id": cid or f"id-{name}", "name": name, "status": status, "status_since": None}


def _node(dry_run=True) -> fl.FeatureLifecycle:
    return fl.FeatureLifecycle("postgresql://unused", _W2, dry_run=dry_run)


def _symbols(n_pop, n_all, n_rows=10):
    return [
        {"symbol": f"S{i}", "n_rows": n_rows, "good": (n_rows if i < n_pop else 0, 0)}
        for i in range(n_all)
    ]


async def _plan(conn, config=None):
    return await _node()._plan(conn, config or LifecycleConfig(0.95, 90, 2, 1))


def _fake(concepts, agg, columns=None, **kw):
    columns = columns or {"good": "real"}
    return _FakeConn(concepts=concepts, columns=columns, tfs=list(agg), agg=agg, **kw)


@pytest.mark.asyncio
async def test_plan_passes_a_covered_finite_feature():
    conn = _fake([_concept("good", "active")], {"1d": _symbols(10, 10)})
    plan = await _plan(conn)
    assert [r.evaluation.passed for r in plan.rows] == [True]
    assert plan.rows[0].evaluation.guard_status == "ok"
    assert plan.transitions == []


@pytest.mark.asyncio
async def test_plan_missing_column_is_not_computed():
    conn = _fake([_concept("ghost", "active")], {"1d": _symbols(10, 10)}, columns={"good": "real"})
    plan = await _plan(conn)
    row = plan.rows[0]
    assert not row.evaluation.passed
    assert row.verdict.failures == ("not_computed",)
    assert row.evaluation.detail["column_missing"] is True


@pytest.mark.asyncio
async def test_plan_low_coverage_fails_and_demotes_after_two_windows():
    conn = _fake(
        [_concept("good", "active", "c1")],
        {"1d": _symbols(1, 10)},
        evaluations=[
            {
                "concept_id": "c1",
                "window_end": _W1,
                "evaluated_status": "active",
                "passed": False,
                "n_observations": 100,
                "guard_status": "ok",
                "evaluated_at": _T0,
                "statistic": 0.1,
                "detail": {"per_tf": []},
            }
        ],
    )
    plan = await _plan(conn)
    assert not plan.rows[0].evaluation.passed
    assert [(t.name, t.transition.reason) for t in plan.transitions] == [
        ("good", "data_quality_fail")
    ]


@pytest.mark.asyncio
async def test_plan_ignores_candidate_and_deprecated():
    conn = _fake(
        [_concept("good", "candidate"), _concept("other", "deprecated")],
        {"1d": _symbols(10, 10)},
    )
    plan = await _plan(conn)
    assert plan.rows == [] and plan.transitions == []


@pytest.mark.asyncio
async def test_plan_returns_none_without_feature_vectors_in_span():
    conn = _FakeConn(concepts=[], columns={}, tfs=[], agg={})
    assert await _plan(conn) is None


@pytest.mark.asyncio
async def test_non_finite_values_fail():
    agg = {"1d": [{"symbol": "S0", "n_rows": 10, "good": (10, 3)}]}
    plan = await _plan(_fake([_concept("good", "active")], agg))
    assert plan.rows[0].verdict.failures == ("non_finite",)


@pytest.mark.asyncio
async def test_rerun_on_identical_evidence_has_identical_evidence_key():
    make = lambda: _fake([_concept("good", "active")], {"1d": _symbols(10, 10)})  # noqa: E731
    a, b = await _plan(make()), await _plan(make())
    assert a.rows[0].evidence_key == b.rows[0].evidence_key
    changed = await _plan(_fake([_concept("good", "active")], {"1d": _symbols(9, 10)}))
    assert changed.rows[0].evidence_key != a.rows[0].evidence_key


@pytest.mark.asyncio
async def test_dry_run_writes_nothing(monkeypatch):
    conn = _fake([_concept("good", "active")], {"1d": _symbols(1, 10)})

    class _Pool:
        def acquire(self):
            outer = self

            class _Ctx:
                async def __aenter__(self_inner):
                    return conn

                async def __aexit__(self_inner, *exc):
                    return False

            del outer
            return _Ctx()

    async def fake_apr(_conn):
        return {}

    monkeypatch.setattr(fl, "load_apr_dict_async", fake_apr)
    await _node(dry_run=True).execute(_Pool())
    assert conn.writes == []


# ---------------------------------------------------------------------------
# Source contracts
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "needle", ["ensemble_weights", "feature_ic_scores", "alpha.ensemble", "alpha.decay"]
)
def test_module_reads_no_old_chain_table_or_key(needle):
    assert needle not in inspect.getsource(fl)


def test_evaluation_load_reads_only_rows_this_rule_wrote():
    assert "detail ? 'per_tf'" in fl._LOAD_EVALUATIONS_SQL


def test_ledger_upsert_refreshes_recency_on_identical_evidence():
    sql = fl._UPSERT_EVALUATION_SQL
    assert "ON CONFLICT (concept_id, window_end, evidence_key)" in sql
    assert "evaluated_at = EXCLUDED.evaluated_at" in sql


def test_transitions_carry_no_fdr_attestation():
    source = inspect.getsource(fl.FeatureLifecycle._apply)
    assert "fdr_passed=None" in source
