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

_GATE = LifecycleConfig(0.95, 90, demotion_min_consecutive=2, recovery_min_passes=1)


def _eval(window, passed, *, status="active", at=None) -> Evaluation:
    return Evaluation(
        window_end=window,
        evaluated_status=status,
        passed=passed,
        n_observations=1000,
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
        "infra.feature_lifecycle.max_concurrent_tfs",
    ]
    assert config == LifecycleConfig(0.95, 90, 2, 1, max_concurrent_tfs=3)


# The fingerprint as it was built before the explicit field list (dataclasses.asdict minus the
# infra knob); evidence keys already written must not move.
_LEGACY_FINGERPRINT = {
    "coverage_floor": 0.95,
    "lookback_days": 90,
    "demotion_min_consecutive": 2,
    "recovery_min_passes": 1,
}


def test_rule_fingerprint_equals_the_pre_refactor_output():
    config = LifecycleConfig(0.95, 90, 2, 1)
    assert config.rule_fingerprint() == _LEGACY_FINGERPRINT
    import dataclasses

    legacy = dataclasses.asdict(config)
    del legacy["max_concurrent_tfs"]
    assert config.rule_fingerprint() == legacy
    assert list(config.rule_fingerprint()) == list(legacy)


def test_the_concurrency_knob_is_not_part_of_the_rule_fingerprint():
    """An infra knob cannot move a verdict; tuning it must not re-evaluate every window."""
    base = LifecycleConfig(0.95, 90, 2, 1)
    assert "max_concurrent_tfs" not in base.rule_fingerprint()
    assert evidence_key("active", base.rule_fingerprint(), _ROWS) == evidence_key(
        "active", LifecycleConfig(0.95, 90, 2, 1, max_concurrent_tfs=9).rule_fingerprint(), _ROWS
    )


def test_a_new_infra_field_does_not_change_the_fingerprint():
    import dataclasses

    @dataclasses.dataclass(frozen=True)
    class Extended(LifecycleConfig):
        new_infra_knob: int = 7

    assert Extended(0.95, 90, 2, 1).rule_fingerprint() == _LEGACY_FINGERPRINT


def test_every_config_field_is_classified_as_rule_or_infra():
    import dataclasses

    names = [f.name for f in dataclasses.fields(LifecycleConfig)]
    assert sorted(names) == sorted(fl.RULE_FIELDS + fl.INFRA_FIELDS)
    assert not set(fl.RULE_FIELDS) & set(fl.INFRA_FIELDS)


@pytest.mark.asyncio
async def test_execute_loads_the_infra_pattern_beside_the_feature_patterns(monkeypatch):
    seen = {}

    async def fake_load(conn, extra_like_patterns=None):
        seen["patterns"] = extra_like_patterns
        return {}

    class _Acquire:
        async def __aenter__(self_inner):
            return object()

        async def __aexit__(self_inner, *exc):
            return False

    class _Pool:
        def acquire(self):
            return _Acquire()

    async def no_plan(self, conn, config):
        return None

    monkeypatch.setattr(fl, "load_apr_dict_async", fake_load)
    monkeypatch.setattr(fl.FeatureLifecycle, "_plan", no_plan)
    await _node().execute(_Pool())
    assert "infra.feature_lifecycle.%" in seen["patterns"]


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

    def test_passing_window_restores_a_data_quality_demotion(self):
        t = derive_feature_transition(
            "shadow_only",
            None,
            [_eval(_W1, True, status="shadow_only")],
            _GATE,
            last_transition_reason="data_quality_fail",
        )
        assert t.to_status == "active" and t.reason == "data_quality_restored"

    @pytest.mark.parametrize(
        "last_reason", [None, "demotion_performance", "operator_override", "promotion"]
    )
    def test_shadow_only_for_another_reason_is_never_restored(self, last_reason):
        """Seeded pending validation (no log row), a performance demotion or an operator
        decision is not a data-quality verdict; perfect coverage never promotes it."""
        evals = [_eval(_W1, True, status="shadow_only"), _eval(_W2, True, status="shadow_only")]
        assert (
            derive_feature_transition(
                "shadow_only", None, evals, _GATE, last_transition_reason=last_reason
            )
            is None
        )

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

    @pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
    def test_non_finite_evidence_raises_instead_of_stringifying(self, bad):
        rows = [{"tf": "1d", "symbol_coverage": bad, "n_non_finite": 0}]
        with pytest.raises(ValueError):
            evidence_key("active", _RULE, rows)

    @pytest.mark.parametrize(
        "evidence",
        [
            {"status": "active", "rule": _RULE, "per_tf": _ROWS},
            {"status": "shadow_only", "rule": _RULE, "per_tf": []},
            {
                "status": "active",
                "rule": _RULE,
                "per_tf": [
                    {"tf": "5m", "symbol_coverage": 0.987654321, "check": None, "ok": True},
                    {"tf": "1d", "symbol_coverage": 1e-12, "n_rows": 10**12, "check": "n\u00e9"},
                ],
            },
        ],
    )
    def test_serialization_equals_the_spec_canonical_json_so_no_key_moves(self, evidence):
        """The local serializer replaced research.spec.canonical_json; keys stay identical."""
        import hashlib

        from src.intelligence.research.spec import canonical_json

        assert fl._canonical_json(evidence) == canonical_json(evidence)
        key = evidence_key(evidence["status"], evidence["rule"], evidence["per_tf"])
        assert key == hashlib.sha256(canonical_json(evidence).encode()).hexdigest()

    @pytest.mark.parametrize("bad", [float("nan"), float("inf")])
    def test_local_serializer_rejects_non_finite_and_unserializable_values(self, bad):
        with pytest.raises(ValueError):
            fl._canonical_json({"x": bad})
        with pytest.raises(TypeError):
            fl._canonical_json({"x": datetime(2026, 1, 1, tzinfo=UTC)})

    def test_module_does_not_import_research(self):
        assert "src.intelligence.research" not in inspect.getsource(fl)

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


def _concept(name, status, cid=None, last_reason=None):
    return {
        "concept_id": cid or f"id-{name}",
        "name": name,
        "status": status,
        "status_since": None,
        "last_transition_reason": last_reason,
    }


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
    assert plan.transitions == []


@pytest.mark.asyncio
async def test_plan_missing_column_is_not_computed():
    conn = _fake([_concept("ghost", "active")], {"1d": _symbols(10, 10)}, columns={"good": "real"})
    plan = await _plan(conn)
    row = plan.rows[0]
    assert not row.evaluation.passed
    assert row.verdict.failures == ("not_computed",)
    assert "column_missing" not in row.evaluation.detail
    assert row.per_tf == () and row.n_cells == 0
    assert row.evaluation.detail["per_tf"] == []


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
async def test_plan_seeded_shadow_only_feature_stays_shadow_only_at_full_coverage():
    conn = _fake([_concept("good", "shadow_only")], {"1d": _symbols(10, 10)})
    plan = await _plan(conn)
    assert plan.rows[0].evaluation.passed
    assert plan.transitions == []


@pytest.mark.asyncio
async def test_plan_restores_after_a_data_quality_demotion():
    conn = _fake(
        [_concept("good", "shadow_only", last_reason="data_quality_fail")],
        {"1d": _symbols(10, 10)},
    )
    plan = await _plan(conn)
    assert [(t.name, t.transition.reason) for t in plan.transitions] == [
        ("good", "data_quality_restored")
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


async def _emitted_facts(monkeypatch, agg, config=None):
    facts = []

    async def capture(conn, batch):
        facts.extend((f[1], f[2], f[3], f[4], f[5]) for f in batch)

    monkeypatch.setattr(fl, "emit_integrity_facts_async", capture)
    conn = _fake([_concept("good", "active")], agg)
    config = config or LifecycleConfig(0.95, 90, 2, 1)
    plan = await _plan(conn, config)
    await _node(dry_run=False)._apply(conn, plan, config)
    return [f for f in facts if f[0] is not None]


@pytest.mark.asyncio
async def test_non_finite_fact_carries_the_non_finite_count_not_a_passing_coverage(monkeypatch):
    """100% coverage with a NaN: the fact must not read coverage 1.0 against floor 0.95
    while passed is False."""
    agg = {"1d": [{"symbol": "S0", "n_rows": 10, "good": (10, 1)}]}
    facts = await _emitted_facts(monkeypatch, agg)
    assert facts == [("good|tf=1d", "n_non_finite", 1.0, 0.0, False)]


@pytest.mark.asyncio
async def test_not_computed_is_one_whole_feature_fact_without_a_sentinel_tf(monkeypatch):
    facts = []

    async def capture(conn, batch):
        facts.extend((f[1], f[2], f[3], f[4], f[5]) for f in batch)

    monkeypatch.setattr(fl, "emit_integrity_facts_async", capture)
    conn = _fake([_concept("ghost", "active")], {"1d": _symbols(10, 10)})
    config = LifecycleConfig(0.95, 90, 2, 1)
    plan = await _plan(conn, config)
    await _node(dry_run=False)._apply(conn, plan, config)
    assert [f for f in facts if f[0] is not None] == [
        ("ghost", "symbol_coverage", 0.0, 0.95, False)
    ]
    assert fl.FeatureLifecycle._failure_counts(plan) == {"not_computed": 1}


@pytest.mark.asyncio
async def test_coverage_fact_keeps_coverage_against_the_floor(monkeypatch):
    facts = await _emitted_facts(monkeypatch, {"1d": _symbols(1, 10)})
    assert facts == [("good|tf=1d", "symbol_coverage", 0.1, 0.95, False)]


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

    async def fake_apr(_conn, **_kwargs):
        return {}

    monkeypatch.setattr(fl, "load_apr_dict_async", fake_apr)
    await _node(dry_run=True).execute(_Pool())
    assert conn.writes == []


@pytest.mark.asyncio
async def test_execute_loads_the_feature_apr_keys_through_the_real_loader():
    """The loader only reads alpha.% unless told otherwise; the four feature.* keys must be
    requested, or the config silently uses its defaults."""
    apr_rows = {
        "feature.coverage.min_symbol_fraction": 0.5,
        "feature.lifecycle.lookback_days": 30,
        "feature.lifecycle.demotion_min_consecutive": 3,
        "feature.lifecycle.recovery_min_passes": 4,
        "alpha.unrelated.key": 1,
    }
    conn = _fake([_concept("good", "active")], {"1d": _symbols(6, 10)})
    plain_fetch = conn.fetch

    async def fetch(sql, *args):
        if "FROM config_state" in sql:
            patterns = [p.rstrip("%") for p in args[0]]
            return [
                {"config_key": k, "config_value": v}
                for k, v in apr_rows.items()
                if any(k.startswith(p) for p in patterns)
            ]
        return await plain_fetch(sql, *args)

    conn.fetch = fetch

    class _Pool:
        def acquire(self):
            class _Ctx:
                async def __aenter__(self_inner):
                    return conn

                async def __aexit__(self_inner, *exc):
                    return False

            return _Ctx()

    node = _node(dry_run=True)
    seen: list[LifecycleConfig] = []
    real_plan = node._plan

    async def spy(c, config):
        seen.append(config)
        return await real_plan(c, config)

    node._plan = spy
    await node.execute(_Pool())
    assert seen == [LifecycleConfig(0.5, 30, 3, 4)]


# ---------------------------------------------------------------------------
# Source contracts
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "needle", ["ensemble_weights", "feature_ic_scores", "alpha.ensemble", "alpha.decay"]
)
def test_module_reads_no_old_chain_table_or_key(needle):
    assert needle not in inspect.getsource(fl)


def test_evaluation_load_reads_only_rows_this_rule_wrote():
    for sql in (fl._LOAD_EVALUATIONS_SQL, fl._LOAD_CONCEPT_EVALUATIONS_SQL):
        assert "evidence_kind = 'data_quality'" in sql
        assert "per_tf" not in sql
    assert "evidence_kind" in fl._UPSERT_EVALUATION_SQL
    assert "guard_status" not in fl._UPSERT_EVALUATION_SQL


def test_ledger_upsert_refreshes_recency_on_identical_evidence():
    sql = fl._UPSERT_EVALUATION_SQL
    assert "ON CONFLICT (concept_id, window_end, evidence_key)" in sql
    assert "evaluated_at = EXCLUDED.evaluated_at" in sql


def test_transitions_carry_no_fdr_attestation():
    source = inspect.getsource(fl.FeatureLifecycle._apply)
    assert "fdr_passed=None" in source


# ---------------------------------------------------------------------------
# Trailing-window ledger read: transitions equal the whole-ledger derivation
# ---------------------------------------------------------------------------


def _ledger_row(concept_id, window, passed, status, at):
    return {
        "concept_id": concept_id,
        "window_end": window,
        "evaluated_status": status,
        "passed": passed,
        "n_observations": 1000,
        "evaluated_at": at,
        "statistic": 0.9,
    }


class _LedgerConn:
    """Serves the two ledger reads from an in-memory ledger, applying the documented
    semantics of _LOAD_EVALUATIONS_SQL (status and since filter, latest per window, newest
    $5 windows per concept) and returning a concept's whole history for the escalation read."""

    def __init__(self, ledger):
        self.ledger = ledger

    async def fetch(self, sql, *args):
        if sql == fl._LOAD_CONCEPT_EVALUATIONS_SQL:
            _domain, concept_id = args
            return [r for r in self.ledger if r["concept_id"] == concept_id]
        assert sql == fl._LOAD_EVALUATIONS_SQL
        _domain, ids, statuses, sinces, limit = args
        out = []
        for cid, status, since in zip(ids, statuses, sinces, strict=True):
            kept = [
                r
                for r in self.ledger
                if r["concept_id"] == cid
                and r["evaluated_status"] == status
                and (since is None or r["evaluated_at"] >= since)
            ]
            latest = {}
            for r in kept:
                if (
                    r["window_end"] not in latest
                    or r["evaluated_at"] > latest[r["window_end"]]["evaluated_at"]
                ):
                    latest[r["window_end"]] = r
            newest = sorted(latest, reverse=True)[:limit]
            out.extend(latest[w] for w in newest)
        return out


def _long_ledger():
    """Concepts with 60 weekly windows and different endings, replays, an older status and
    rows before status_since."""
    since = _T0 - timedelta(days=100)
    ledger, concepts = [], {}
    endings = {  # name -> (status, passes for the last windows, oldest to newest)
        "steady_pass": ("active", [True] * 60),
        "fail_streak_2": ("active", [True] * 58 + [False] * 2),
        "fail_streak_9": ("active", [True] * 51 + [False] * 9),
        "one_fail": ("active", [True] * 59 + [False]),
        "alternating": ("active", [i % 2 == 0 for i in range(60)]),
        "pass_streak_7": ("shadow_only", [False] * 53 + [True] * 7),
        "pass_then_fail": ("shadow_only", [True] * 59 + [False]),
    }
    for i, (name, (status, passes)) in enumerate(endings.items()):
        cid = f"id-{name}"
        concepts[name] = {
            "concept_id": cid,
            "name": name,
            "status": status,
            "status_since": since,
            "last_transition_reason": "data_quality_fail",
        }
        for w, passed in enumerate(passes):
            window = _W1 + timedelta(days=7 * w)
            at = since + timedelta(days=w + 1)
            ledger.append(_ledger_row(cid, window, passed, status, at))
            if w % 9 == 0:  # a replay of the window, later, that agrees
                ledger.append(_ledger_row(cid, window, passed, status, at + timedelta(hours=1)))
            if w % 13 == 0:  # evidence from before the concept entered the status: never counts
                ledger.append(
                    _ledger_row(cid, window, not passed, status, since - timedelta(days=1))
                )
            if w % 11 == 0:  # evidence under the other status: never counts
                other = "shadow_only" if status == "active" else "active"
                ledger.append(_ledger_row(cid, window, not passed, other, at))
    return ledger, concepts


@pytest.mark.asyncio
@pytest.mark.parametrize("demotion,recovery", [(1, 1), (2, 1), (3, 2), (5, 4), (9, 7), (12, 9)])
async def test_trailing_window_read_derives_the_whole_ledger_transitions(demotion, recovery):
    ledger, concepts = _long_ledger()
    config = LifecycleConfig(0.95, 90, demotion, recovery)
    governed = sorted(concepts)
    got = await _node()._transitions(_LedgerConn(ledger), concepts, governed, config, [])
    want = []
    for name in governed:
        c = concepts[name]
        evaluations = [
            Evaluation(
                r["window_end"],
                r["evaluated_status"],
                r["passed"],
                r["n_observations"],
                r["evaluated_at"],
                r["statistic"],
            )
            for r in ledger
            if r["concept_id"] == c["concept_id"]
        ]
        t = derive_feature_transition(
            c["status"],
            c["status_since"],
            evaluations,
            config,
            last_transition_reason=c["last_transition_reason"],
        )
        if t is not None:
            want.append(fl.PlannedTransition(name, c["status"], t))
    assert got == want
    if (demotion, recovery) == (2, 1):  # streaks longer than the loaded windows keep their length
        assert {p.name: p.transition.n_windows for p in got} == {
            "fail_streak_2": 2,
            "fail_streak_9": 9,
            "pass_streak_7": 7,
        }


def test_evaluation_load_is_restricted_to_governed_status_since_and_newest_windows():
    sql = fl._LOAD_EVALUATIONS_SQL
    assert "e.evaluated_status = g.status" in sql
    assert "e.evaluated_at >= g.status_since" in sql
    assert "DISTINCT ON (e.concept_id, e.window_end)" in sql and "recency <= $5" in sql


@pytest.mark.asyncio
async def test_tfs_are_measured_concurrently_over_a_pool_and_in_order():
    agg = {"1d": _symbols(10, 10), "1h": _symbols(10, 10), "5m": _symbols(10, 10)}
    conn = _fake([_concept("good", "active")], agg)
    peak = {"now": 0, "max": 0}

    class _Pool:
        def acquire(self):
            class _Ctx:
                async def __aenter__(self_inner):
                    peak["now"] += 1
                    peak["max"] = max(peak["max"], peak["now"])
                    return conn

                async def __aexit__(self_inner, *exc):
                    peak["now"] -= 1
                    return False

            return _Ctx()

    node = _node()
    node._pool = _Pool()
    over_pool = await node._plan(conn, LifecycleConfig(0.95, 90, 2, 1, max_concurrent_tfs=2))
    sequential = await _plan(conn)
    assert peak["max"] <= 2
    assert [q.tf for q in over_pool.rows[0].per_tf] == ["1d", "1h", "5m"]
    assert over_pool.rows[0].evidence_key == sequential.rows[0].evidence_key
