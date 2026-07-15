"""Unit tests: ConceptRegistryService (todo 058).

decide_comparison_action is the pure invariant-enforcement core: invariant 2
(re-evaluation needs new evidence: corpus-advance precondition + F3 evidence-mass
floor), invariant 7 (initial effective-N floor), F8 (baseline_metric = mean of the
consecutive winning evals, never the final one), and the deprecated-is-operator-only
rule. No DB, no Kafka. Pure Python.
"""

from __future__ import annotations

import sys
from pathlib import Path

_project_root = Path(__file__).parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

import pytest

from src.intelligence.concept_registry_service import (
    GateState,
    decide_comparison_action,
)


def _state(**overrides) -> GateState:
    base = dict(
        status="candidate",
        promotion_consecutive=0,
        promotion_eval_metrics=(),
        last_eval_corpus_build_ref=None,
        last_eval_n=None,
        min_promotion_consecutive=2,
        min_new_observations=2000.0,
        min_gate_n=1000.0,
    )
    base.update(overrides)
    return GateState(**base)


def test_deprecated_is_untouchable():
    """Automated path never acts on a deprecated concept (operator-only status)."""
    decision = decide_comparison_action(
        _state(status="deprecated"),
        won=True,
        eval_metric=0.05,
        eval_n=5000.0,
        corpus_build_ref="run_A",
    )
    assert decision.action == "noop_deprecated"


def test_same_corpus_build_is_blocked():
    """Invariant 2 precondition: never evaluate twice against the same corpus build."""
    decision = decide_comparison_action(
        _state(last_eval_corpus_build_ref="run_A", last_eval_n=3000.0),
        won=True,
        eval_metric=0.05,
        eval_n=9000.0,
        corpus_build_ref="run_A",
    )
    assert decision.action == "blocked_same_corpus"


def test_initial_effective_n_floor_blocks():
    """Invariant 7: eval_n below min_gate_n blocks regardless of the win."""
    decision = decide_comparison_action(
        _state(),
        won=True,
        eval_metric=0.05,
        eval_n=999.0,
        corpus_build_ref="run_A",
    )
    assert decision.action == "blocked_min_n"


def test_evidence_mass_floor_blocks_reeval():
    """F3: re-evaluation needs >= min_new_observations NEW independent observations
    since the last recorded eval; corpus-advance alone is insufficient."""
    decision = decide_comparison_action(
        _state(last_eval_corpus_build_ref="run_A", last_eval_n=5000.0),
        won=True,
        eval_metric=0.05,
        eval_n=6999.0,
        corpus_build_ref="run_B",
    )
    assert decision.action == "blocked_evidence_floor"


def test_first_eval_skips_evidence_mass_floor():
    """The F3 floor governs RE-evaluation. A first-ever eval (last_eval_n None) is
    governed by min_gate_n only."""
    decision = decide_comparison_action(
        _state(),
        won=True,
        eval_metric=0.05,
        eval_n=1500.0,
        corpus_build_ref="run_A",
    )
    assert decision.action == "record_win"


def test_loss_resets_consecutive_and_metrics():
    decision = decide_comparison_action(
        _state(
            promotion_consecutive=1,
            promotion_eval_metrics=(0.04,),
            last_eval_corpus_build_ref="run_A",
            last_eval_n=3000.0,
        ),
        won=False,
        eval_metric=None,
        eval_n=6000.0,
        corpus_build_ref="run_B",
    )
    assert decision.action == "record_loss"
    assert decision.new_promotion_consecutive == 0
    assert decision.new_promotion_eval_metrics == ()
    assert decision.baseline_metric is None


def test_win_below_consecutive_floor_records_but_does_not_promote():
    decision = decide_comparison_action(
        _state(),
        won=True,
        eval_metric=0.04,
        eval_n=3000.0,
        corpus_build_ref="run_A",
    )
    assert decision.action == "record_win"
    assert decision.new_promotion_consecutive == 1
    assert decision.new_promotion_eval_metrics == (0.04,)
    assert decision.baseline_metric is None


def test_promotion_baseline_is_mean_of_consecutive_evals_not_final():
    """F8 winner's-curse guard: baseline_metric = mean(promotion_eval_metrics including
    this eval), NEVER the final (selection-inflated) eval alone."""
    decision = decide_comparison_action(
        _state(
            promotion_consecutive=1,
            promotion_eval_metrics=(0.02,),
            last_eval_corpus_build_ref="run_A",
            last_eval_n=3000.0,
        ),
        won=True,
        eval_metric=0.06,
        eval_n=6000.0,
        corpus_build_ref="run_B",
    )
    assert decision.action == "promote"
    assert decision.new_promotion_consecutive == 2
    assert decision.new_promotion_eval_metrics == (0.02, 0.06)
    assert decision.baseline_metric == 0.04  # mean(0.02, 0.06), not 0.06


def test_win_on_already_active_concept_records_win_not_promote():
    """F2: a WIN for an already-active recipe updates the eval cache; it neither
    re-promotes nor displaces anything (redundancy displacement is disabled here)."""
    decision = decide_comparison_action(
        _state(
            status="active",
            promotion_consecutive=3,
            promotion_eval_metrics=(0.02, 0.03, 0.04),
            last_eval_corpus_build_ref="run_A",
            last_eval_n=3000.0,
        ),
        won=True,
        eval_metric=0.05,
        eval_n=6000.0,
        corpus_build_ref="run_B",
    )
    assert decision.action == "record_win"


def test_shadow_only_crossing_floor_is_not_promotable():
    """Phase 160 review finding 2: shadow_only can never reach 'promote' (only
    'candidate' can), so crossing the floor from shadow_only must be flagged
    distinctly rather than silently recorded as an ordinary record_win."""
    decision = decide_comparison_action(
        _state(
            status="shadow_only",
            promotion_consecutive=1,
            promotion_eval_metrics=(0.02,),
            last_eval_corpus_build_ref="run_A",
            last_eval_n=3000.0,
        ),
        won=True,
        eval_metric=0.06,
        eval_n=6000.0,
        corpus_build_ref="run_B",
    )
    assert decision.action == "record_win_not_promotable"
    assert decision.new_promotion_consecutive == 2
    assert decision.new_promotion_eval_metrics == (0.02, 0.06)


def test_won_requires_eval_metric():
    with pytest.raises(ValueError):
        decide_comparison_action(
            _state(),
            won=True,
            eval_metric=None,
            eval_n=3000.0,
            corpus_build_ref="run_A",
        )


# ---------------------------------------------------------------------------
# Transactional apply (Task 4): SQL-constant regression tests + FakeConn flows.
# The effective pytest-asyncio mode in this environment is strict despite
# pytest.ini's addopts listing --asyncio-mode=auto (matches the established
# convention in tests/unit/test_base_batch_jsonb.py), so each async test is
# explicitly marked @pytest.mark.asyncio.
# ---------------------------------------------------------------------------

from src.intelligence.concept_registry_service import (
    _CAS_PROMOTE_SQL,
    _GATE_CACHE_UPDATE_SQL,
    _GATE_PROMOTE_UPDATE_SQL,
    _LOAD_CONCEPT_SQL,
    _TRANSITION_INSERT_SQL,
    ConceptNotFoundError,
    ConceptRegistryService,
)


class _FakeTransaction:
    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        self._conn.tx_entered += 1
        return self

    async def __aexit__(self, exc_type, exc, tb):
        if exc_type is not None:
            self._conn.tx_rolled_back += 1
        return False


class _FakeConn:
    """Minimal asyncpg-shaped stub: canned fetchrow row, recorded execute calls."""

    def __init__(self, row, cas_result="UPDATE 1", gate_result="UPDATE 1"):
        self.row = row
        self.cas_result = cas_result
        self.gate_result = gate_result
        self.executed: list[tuple[str, tuple]] = []
        self.tx_entered = 0
        self.tx_rolled_back = 0

    def transaction(self):
        return _FakeTransaction(self)

    async def fetchrow(self, sql, *args):
        return self.row

    async def execute(self, sql, *args):
        self.executed.append((sql, args))
        if sql is _CAS_PROMOTE_SQL:
            return self.cas_result
        if sql is _GATE_CACHE_UPDATE_SQL or sql is _GATE_PROMOTE_UPDATE_SQL:
            return self.gate_result
        return "UPDATE 1"


def _row(**overrides):
    base = dict(
        concept_id="11111111-1111-1111-1111-111111111111",
        status="candidate",
        promotion_consecutive=1,
        promotion_eval_metrics=[0.02],
        last_eval_corpus_build_ref="run_A",
        last_eval_n=3000.0,
        min_promotion_consecutive=None,
        min_new_observations=None,
        min_gate_n=None,
    )
    base.update(overrides)
    return base


_DEFAULTS = dict(
    default_min_promotion_consecutive=2,
    default_min_new_observations=2000.0,
    default_min_gate_n=1000.0,
)


def test_cas_promote_sql_has_optimistic_lock():
    """Invariant 9: the status UPDATE must carry AND status = <from> so a racing or
    stale evaluator can never log a transition whose from_status never matched."""
    assert "AND status = " in _CAS_PROMOTE_SQL
    assert "UPDATE concept_registry" in _CAS_PROMOTE_SQL


def test_transition_insert_sql_carries_corpus_build_ref():
    """F3: every automated transition records the corpus build that produced it."""
    assert "corpus_build_ref" in _TRANSITION_INSERT_SQL
    assert "concept_transition_log" in _TRANSITION_INSERT_SQL


def test_load_sql_joins_gate():
    assert "concept_gate" in _LOAD_CONCEPT_SQL
    assert "concept_registry" in _LOAD_CONCEPT_SQL


def test_gate_update_sqls_touch_cache_columns():
    for sql in (_GATE_CACHE_UPDATE_SQL, _GATE_PROMOTE_UPDATE_SQL):
        assert "last_eval_corpus_build_ref" in sql
        assert "promotion_consecutive" in sql
    assert "baseline_metric" in _GATE_PROMOTE_UPDATE_SQL


@pytest.mark.asyncio
async def test_unknown_concept_raises():
    service = ConceptRegistryService()
    conn = _FakeConn(row=None)
    with pytest.raises(ConceptNotFoundError):
        await service.record_comparison_outcome(
            conn,
            domain="ensemble_strategy",
            name="nope",
            won=True,
            eval_metric=0.05,
            eval_n=6000.0,
            corpus_build_ref="run_B",
            **_DEFAULTS,
        )


@pytest.mark.asyncio
async def test_blocked_decision_writes_nothing():
    service = ConceptRegistryService()
    conn = _FakeConn(row=_row())
    decision = await service.record_comparison_outcome(
        conn,
        domain="ensemble_strategy",
        name="e1_shrunk_ic",
        won=True,
        eval_metric=0.05,
        eval_n=6000.0,
        corpus_build_ref="run_A",  # same corpus
        **_DEFAULTS,
    )
    assert decision.action == "blocked_same_corpus"
    assert conn.executed == []


@pytest.mark.asyncio
async def test_promotion_flow_is_cas_plus_transition_plus_gate_in_one_tx():
    service = ConceptRegistryService()
    conn = _FakeConn(row=_row())
    decision = await service.record_comparison_outcome(
        conn,
        domain="ensemble_strategy",
        name="e1_shrunk_ic",
        won=True,
        eval_metric=0.06,
        eval_n=6000.0,
        corpus_build_ref="run_B",
        **_DEFAULTS,
    )
    assert decision.action == "promote"
    assert decision.baseline_metric == pytest.approx(0.04)
    executed_sqls = [sql for sql, _ in conn.executed]
    assert executed_sqls == [_CAS_PROMOTE_SQL, _TRANSITION_INSERT_SQL, _GATE_PROMOTE_UPDATE_SQL]
    assert conn.tx_entered == 1


@pytest.mark.asyncio
async def test_promotion_cas_race_returns_blocked_status_race():
    """CAS matched zero rows (status changed under us): abort, no transition row."""
    service = ConceptRegistryService()
    conn = _FakeConn(row=_row(), cas_result="UPDATE 0")
    decision = await service.record_comparison_outcome(
        conn,
        domain="ensemble_strategy",
        name="e1_shrunk_ic",
        won=True,
        eval_metric=0.06,
        eval_n=6000.0,
        corpus_build_ref="run_B",
        **_DEFAULTS,
    )
    assert decision.action == "blocked_status_race"
    executed_sqls = [sql for sql, _ in conn.executed]
    assert _TRANSITION_INSERT_SQL not in executed_sqls


@pytest.mark.asyncio
async def test_record_loss_updates_gate_cache_only():
    service = ConceptRegistryService()
    conn = _FakeConn(row=_row())
    decision = await service.record_comparison_outcome(
        conn,
        domain="ensemble_strategy",
        name="e2_mean_variance",
        won=False,
        eval_metric=None,
        eval_n=6000.0,
        corpus_build_ref="run_B",
        **_DEFAULTS,
    )
    assert decision.action == "record_loss"
    executed_sqls = [sql for sql, _ in conn.executed]
    assert executed_sqls == [_GATE_CACHE_UPDATE_SQL]


@pytest.mark.asyncio
async def test_shadow_only_win_still_updates_gate_cache():
    """Phase 160 review finding 2: the eval cache write still happens for
    record_win_not_promotable (only the log level differs from record_win)."""
    service = ConceptRegistryService()
    conn = _FakeConn(row=_row(status="shadow_only"))
    decision = await service.record_comparison_outcome(
        conn,
        domain="ensemble_strategy",
        name="e3_shadow_candidate",
        won=True,
        eval_metric=0.06,
        eval_n=6000.0,
        corpus_build_ref="run_B",
        **_DEFAULTS,
    )
    assert decision.action == "record_win_not_promotable"
    executed_sqls = [sql for sql, _ in conn.executed]
    assert executed_sqls == [_GATE_CACHE_UPDATE_SQL]


@pytest.mark.asyncio
async def test_vanished_gate_row_raises_on_promote():
    """Phase 160 review finding 4: a zero-row gate UPDATE mid-promote must
    crash loudly, not commit a status flip with no matching gate update."""
    service = ConceptRegistryService()
    conn = _FakeConn(row=_row(), gate_result="UPDATE 0")
    with pytest.raises(RuntimeError):
        await service.record_comparison_outcome(
            conn,
            domain="ensemble_strategy",
            name="e1_shrunk_ic",
            won=True,
            eval_metric=0.06,
            eval_n=6000.0,
            corpus_build_ref="run_B",
            **_DEFAULTS,
        )


@pytest.mark.asyncio
async def test_gate_row_overrides_beat_apr_defaults():
    """A non-NULL concept_gate.min_promotion_consecutive overrides the APR default:
    with override 3, the second consecutive win records but does not promote."""
    service = ConceptRegistryService()
    conn = _FakeConn(row=_row(min_promotion_consecutive=3))
    decision = await service.record_comparison_outcome(
        conn,
        domain="ensemble_strategy",
        name="e1_shrunk_ic",
        won=True,
        eval_metric=0.06,
        eval_n=6000.0,
        corpus_build_ref="run_B",
        **_DEFAULTS,
    )
    assert decision.action == "record_win"
