"""Unit tests: ConceptRegistryService (todo 058, 187-12).

record_transition is the one status-flip path (CAS plus log in one transaction, fail-closed
FDR, deprecated is operator-only); register_idea logs a candidate with no recipe. No DB.
"""

from __future__ import annotations

import sys
from pathlib import Path

_project_root = Path(__file__).parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

import pytest

from src.intelligence.concept_registry_service import (
    _CAS_TRANSITION_SQL,
    _LOAD_TRANSITION_TARGET_SQL,
    _REGISTER_IDEA_SQL,
    _TRANSITION_LOG_INSERT_SQL,
    TYPED_DOMAINS,
    ConceptExistsError,
    ConceptNotFoundError,
    ConceptRegistryService,
    TransitionResult,
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

    def __init__(self, row, cas_result="UPDATE 1", idea_id="33333333-3333-3333-3333-333333333333"):
        self.row = row
        self.cas_result = cas_result
        self.idea_id = idea_id
        self.executed: list[tuple[str, tuple]] = []
        self.fetchvals: list[tuple[str, tuple]] = []
        self.tx_entered = 0
        self.tx_rolled_back = 0

    def transaction(self):
        return _FakeTransaction(self)

    async def fetchrow(self, sql, *args):
        return self.row

    async def fetchval(self, sql, *args):
        self.fetchvals.append((sql, args))
        return self.idea_id

    async def execute(self, sql, *args):
        self.executed.append((sql, args))
        if sql is _CAS_TRANSITION_SQL:
            return self.cas_result
        return "UPDATE 1"


def test_transition_sql_has_optimistic_lock():
    """Same invariant as test_cas_promote_sql_has_optimistic_lock, for record_transition
    (the feature_lifecycle node and the operator override CLI)."""
    assert "AND status = " in _CAS_TRANSITION_SQL
    assert "UPDATE concept_registry" in _CAS_TRANSITION_SQL
    assert "enabled = ($1 = 'active')" in _CAS_TRANSITION_SQL


def test_transition_target_sql_holds_row_lock():
    assert "FOR UPDATE" in _LOAD_TRANSITION_TARGET_SQL
    assert "g.fdr_required" in _LOAD_TRANSITION_TARGET_SQL


# ---------------------------------------------------------------------------
# register_idea (187-12): a candidate row, no recipe
# ---------------------------------------------------------------------------


async def _register(conn, **overrides):
    kwargs = dict(
        domain="family",
        name="overnight_gap_reversal",
        description="gap reversal after earnings",
        sources=["docs/ideas/gap.md"],
        author="brandon",
    )
    kwargs.update(overrides)
    return await ConceptRegistryService().register_idea(conn, **kwargs)


def test_register_idea_sql_is_one_candidate_insert_that_never_overwrites():
    assert "INSERT INTO concept_registry" in _REGISTER_IDEA_SQL
    assert "'candidate'" in _REGISTER_IDEA_SQL
    assert "ON CONFLICT (domain, name) DO NOTHING" in _REGISTER_IDEA_SQL
    assert "concept_recipe" not in _REGISTER_IDEA_SQL


def test_typed_domains_match_the_registry_check():
    assert TYPED_DOMAINS == {
        "feature",
        "family",
        "member",
        "combiner",
        "construction_rule",
        "book",
        "method",
    }


@pytest.mark.asyncio
async def test_register_idea_returns_the_new_concept_id_with_metadata():
    conn = _FakeConn(row=None)
    concept_id = await _register(conn)
    assert concept_id == conn.idea_id
    ((sql, args),) = conn.fetchvals
    assert sql is _REGISTER_IDEA_SQL
    domain, name, description, metadata = args
    assert (domain, name, description) == (
        "family",
        "overnight_gap_reversal",
        "gap reversal after earnings",
    )
    assert metadata["sources"] == ["docs/ideas/gap.md"]
    assert metadata["author"] == "brandon"
    assert metadata["logged_at"].endswith("Z")


@pytest.mark.asyncio
async def test_register_idea_refuses_an_existing_name():
    with pytest.raises(ConceptExistsError):
        await _register(_FakeConn(row=None, idea_id=None))


@pytest.mark.asyncio
@pytest.mark.parametrize("domain", ["ensemble_strategy", "signal", ""])
async def test_register_idea_refuses_an_invalid_domain_before_any_sql(domain):
    conn = _FakeConn(row=None)
    with pytest.raises(ValueError):
        await _register(conn, domain=domain)
    assert conn.fetchvals == [] and conn.executed == []


# ---------------------------------------------------------------------------
# record_transition (todo 402): the generic lifecycle transition path
# ---------------------------------------------------------------------------

_TARGET = {"concept_id": "22222222-2222-2222-2222-222222222222", "fdr_required": True}


async def _transition(conn, **overrides):
    kwargs = dict(
        domain="feature",
        name="momentum_z_mid",
        from_status="active",
        to_status="shadow_only",
        reason="demotion_performance",
    )
    kwargs.update(overrides)
    return await ConceptRegistryService().record_transition(conn, **kwargs)


@pytest.mark.asyncio
async def test_record_transition_is_cas_then_log_in_one_tx():
    conn = _FakeConn(row=_TARGET)
    assert await _transition(conn) is TransitionResult.APPLIED
    assert [sql for sql, _ in conn.executed] == [_CAS_TRANSITION_SQL, _TRANSITION_LOG_INSERT_SQL]
    assert conn.tx_entered == 1


@pytest.mark.asyncio
async def test_record_transition_cas_miss_writes_no_log():
    conn = _FakeConn(row=_TARGET, cas_result="UPDATE 0")
    assert await _transition(conn) is TransitionResult.LOCK_MISS
    assert [sql for sql, _ in conn.executed] == [_CAS_TRANSITION_SQL]


@pytest.mark.asyncio
async def test_record_transition_promotion_fails_closed_without_fdr_attestation():
    conn = _FakeConn(row=_TARGET)
    applied = await _transition(
        conn, from_status="shadow_only", to_status="active", reason="promotion"
    )
    assert applied is TransitionResult.FDR_BLOCKED
    assert conn.executed == []


@pytest.mark.asyncio
async def test_record_transition_promotion_with_attestation_applies():
    conn = _FakeConn(row=_TARGET)
    applied = await _transition(
        conn, from_status="shadow_only", to_status="active", reason="promotion", fdr_passed=True
    )
    assert applied is TransitionResult.APPLIED


@pytest.mark.asyncio
async def test_record_transition_unknown_concept_raises():
    with pytest.raises(ConceptNotFoundError):
        await _transition(_FakeConn(row=None))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "overrides",
    [
        {"to_status": "deprecated", "reason": "demotion_performance"},
        {"to_status": "deprecated", "reason": "promotion"},
        {"reason": "not_a_reason"},
    ],
)
async def test_record_transition_guards_raise_before_any_write(overrides):
    conn = _FakeConn(row=_TARGET)
    with pytest.raises(ValueError):
        await _transition(conn, **overrides)
    assert conn.executed == [] and conn.tx_entered == 0


@pytest.mark.asyncio
async def test_operator_override_may_deprecate():
    conn = _FakeConn(row=_TARGET)
    result = await _transition(conn, to_status="deprecated", reason="operator_override")
    assert result is TransitionResult.APPLIED


@pytest.mark.asyncio
async def test_record_transition_accepts_data_quality_reasons():
    conn = _FakeConn(row=_TARGET)
    demoted = await _transition(conn, reason="data_quality_fail")
    assert demoted is TransitionResult.APPLIED


@pytest.mark.asyncio
async def test_data_quality_restored_is_exempt_from_the_fdr_guard():
    conn = _FakeConn(row=_TARGET)
    applied = await _transition(
        conn, from_status="shadow_only", to_status="active", reason="data_quality_restored"
    )
    assert applied is TransitionResult.APPLIED


@pytest.mark.asyncio
@pytest.mark.parametrize("domain", ["signal", "recipe", "plugin"])
async def test_data_quality_restored_exemption_is_feature_domain_only(domain):
    conn = _FakeConn(row=_TARGET)
    result = await _transition(
        conn,
        domain=domain,
        from_status="shadow_only",
        to_status="active",
        reason="data_quality_restored",
    )
    assert result is TransitionResult.FDR_BLOCKED
    assert conn.executed == []


@pytest.mark.asyncio
@pytest.mark.parametrize("reason", ["data_quality_fail", "data_quality_restored"])
async def test_data_quality_reasons_cannot_deprecate(reason):
    conn = _FakeConn(row=_TARGET)
    with pytest.raises(ValueError):
        await _transition(conn, to_status="deprecated", reason=reason)
    assert conn.executed == []
