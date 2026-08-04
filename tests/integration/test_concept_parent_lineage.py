"""Integration tests: concept_parent lineage, cycle guard, cascade trigger (Phase 170 Plan 01).

Proves the four DB-level mechanisms migration 283 adds (todo 118 items L-5/L-8/L-9/L-10)
actually behave, against a real database -- a trigger nobody has fired is a claim, not a
mechanism. This is the first DB-touching test in the concept-registry family (unlike
tests/unit/test_concept_registry_service.py, which covers decide_comparison_action as a pure
helper with no DB); it lives under tests/integration/ and the migrated_test_database fixture
(tests/integration/conftest.py) rather than a new fixture mechanism. Migration 283 (numbered
above conftest.py's _BASELINE_MIGRATION_CUTOFF) is replayed into indicagent_test by that
session-scoped autouse fixture before this module's tests run.

Every test creates its own throwaway concept rows with unique names
(f"_t170_{uuid4().hex[:8]}"), domain='ensemble_strategy' (already-allowed, keeps this test
independent of Plan 03's feature seeding), and cleans up afterward. The 5 real seeded
domain='ensemble_strategy' rows are never touched.

NOT covered here, deliberately: a concurrent two-transaction cycle (A->B and B->A inserted
simultaneously by two sessions) is NOT tested and NOT prevented, because
fn_concept_parent_cycle_guard()'s recursive check reads only committed edges. This is a
documented, bounded limit recorded in migration 283's header and the guard's own function
comment, and is acceptable because concept_parent's only writer is migration 284's
single-transaction seed -- no runtime service writes lineage edges. Any future writer outside a
single-transaction seed MUST take pg_advisory_xact_lock() on a fixed key covering concept_parent
first, per that same contract.

Run: pytest tests/integration/test_concept_parent_lineage.py -m integration
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from uuid import uuid4

import asyncpg
import pytest

pytestmark = [pytest.mark.integration, pytest.mark.requires_db]

_TEST_DB_URL = "postgresql://postgres:postgres@localhost:5432/indicagent_test"


def _name() -> str:
    return f"_t170_{uuid4().hex[:8]}"


class _TrackedConnection:
    """Thin wrapper: asyncpg.Connection has __slots__ (no ad-hoc attributes), so created
    concept_ids are tracked here instead of on the connection object itself."""

    def __init__(self, connection: asyncpg.Connection) -> None:
        self.connection = connection
        self.created_concept_ids: list[str] = []

    def __getattr__(self, item):
        return getattr(self.connection, item)


@pytest.fixture
async def conn() -> AsyncIterator[_TrackedConnection]:
    connection = await asyncpg.connect(_TEST_DB_URL)
    tracked = _TrackedConnection(connection)
    try:
        yield tracked
    finally:
        created_concept_ids = tracked.created_concept_ids
        if created_concept_ids:
            # concept_parent rows have no ON DELETE CASCADE, so child edges are removed
            # first, then the concept_transition_log/concept_gate/concept_registry rows.
            await connection.execute(
                "DELETE FROM concept_parent WHERE child_concept_id = ANY($1::uuid[]) "
                "OR parent_concept_id = ANY($1::uuid[])",
                created_concept_ids,
            )
            await connection.execute(
                "DELETE FROM concept_transition_log WHERE concept_id = ANY($1::uuid[])",
                created_concept_ids,
            )
            await connection.execute(
                "DELETE FROM concept_gate WHERE concept_id = ANY($1::uuid[])",
                created_concept_ids,
            )
            await connection.execute(
                "DELETE FROM concept_registry WHERE concept_id = ANY($1::uuid[])",
                created_concept_ids,
            )
        await connection.close()


async def _make_concept(
    connection: _TrackedConnection, *, status: str = "active", enabled: bool = True
) -> str:
    """Insert one throwaway domain='ensemble_strategy' concept_registry row and return its id."""
    concept_id = await connection.connection.fetchval(
        "INSERT INTO concept_registry (domain, name, description, status, enabled) "
        "VALUES ('ensemble_strategy', $1, 'phase 170 plan 01 lineage test fixture', $2, $3) "
        "RETURNING concept_id",
        _name(),
        status,
        enabled,
    )
    connection.created_concept_ids.append(concept_id)
    return concept_id


async def _link(connection: _TrackedConnection, *, child: str, parent: str) -> None:
    await connection.execute(
        "INSERT INTO concept_parent (child_concept_id, parent_concept_id) VALUES ($1, $2)",
        child,
        parent,
    )


@pytest.mark.asyncio
async def test_multi_parent_lineage_allowed(conn: _TrackedConnection) -> None:
    """A single child may have TWO parents -- the capability concept_registry.parent_concept_id
    (a single-value FK column) could never structurally express."""
    parent_a = await _make_concept(conn)
    parent_b = await _make_concept(conn)
    child = await _make_concept(conn)

    await _link(conn, child=child, parent=parent_a)
    await _link(conn, child=child, parent=parent_b)

    count = await conn.fetchval(
        "SELECT count(*) FROM concept_parent WHERE child_concept_id = $1", child
    )
    assert count == 2, f"expected 2 parent edges for {child}, got {count}"

    parent_ids = {
        row["parent_concept_id"]
        for row in await conn.fetch(
            "SELECT parent_concept_id FROM concept_parent WHERE child_concept_id = $1", child
        )
    }
    assert parent_ids == {parent_a, parent_b}


@pytest.mark.asyncio
async def test_cycle_rejected(conn: _TrackedConnection) -> None:
    """A -> B (B child of A), then inserting A as a child of B must be rejected. A direct
    self-edge (child == parent) must also be rejected, by concept_parent_no_self_check."""
    concept_a = await _make_concept(conn)
    concept_b = await _make_concept(conn)

    await _link(conn, child=concept_b, parent=concept_a)

    with pytest.raises(asyncpg.exceptions.PostgresError, match="concept_parent cycle rejected"):
        await _link(conn, child=concept_a, parent=concept_b)

    with pytest.raises(asyncpg.exceptions.CheckViolationError):
        await _link(conn, child=concept_a, parent=concept_a)


@pytest.mark.asyncio
async def test_cascade_single_level_audits_true_from_status(conn: _TrackedConnection) -> None:
    """Parent P (active) with two children C1 (active) and C2 (shadow_only); deprecating P
    must deprecate both, and each child's concept_transition_log row must carry that child's
    TRUE prior status -- not a fabricated 'active' for both (the BUG-2 regression this test
    exists to close: the old feature_registry trigger hard-coded 'active' for every cascaded
    row regardless of the child's real prior status)."""
    parent = await _make_concept(conn, status="active")
    child_active = await _make_concept(conn, status="active")
    child_shadow = await _make_concept(conn, status="shadow_only")

    await _link(conn, child=child_active, parent=parent)
    await _link(conn, child=child_shadow, parent=parent)

    await conn.execute(
        "UPDATE concept_registry SET status = 'deprecated' WHERE concept_id = $1", parent
    )

    statuses = {
        row["concept_id"]: (row["status"], row["enabled"])
        for row in await conn.fetch(
            "SELECT concept_id, status, enabled FROM concept_registry WHERE concept_id = ANY($1::uuid[])",
            [child_active, child_shadow],
        )
    }
    assert statuses[child_active] == ("deprecated", False)
    assert statuses[child_shadow] == ("deprecated", False)

    log_rows = {
        row["concept_id"]: row
        for row in await conn.fetch(
            "SELECT concept_id, from_status, to_status, trigger_reason, domain, name "
            "FROM concept_transition_log "
            "WHERE concept_id = ANY($1::uuid[]) AND trigger_reason = 'parent_cascade'",
            [child_active, child_shadow],
        )
    }
    assert set(log_rows) == {
        child_active,
        child_shadow,
    }, f"expected exactly one parent_cascade row per child, got: {log_rows}"

    assert log_rows[child_active]["from_status"] == "active"
    assert log_rows[child_shadow]["from_status"] == "shadow_only", (
        "BUG-2 regression: cascaded shadow_only child must record from_status='shadow_only', "
        f"got {log_rows[child_shadow]['from_status']!r}"
    )
    for row in log_rows.values():
        assert row["to_status"] == "deprecated"
        assert row["domain"] == "ensemble_strategy"


@pytest.mark.asyncio
async def test_cascade_multi_level(conn: _TrackedConnection) -> None:
    """Chain G -> P -> C (C child of P, P child of G), all active. Deprecating G must cascade
    through BOTH levels: P and C both end up deprecated, each with its own parent_cascade log
    row. Without the trigger's self-recursive re-fire (safe only because of the cycle guard),
    only P would flip and C would incorrectly stay active."""
    grandparent = await _make_concept(conn, status="active")
    parent = await _make_concept(conn, status="active")
    child = await _make_concept(conn, status="active")

    await _link(conn, child=parent, parent=grandparent)
    await _link(conn, child=child, parent=parent)

    await conn.execute(
        "UPDATE concept_registry SET status = 'deprecated' WHERE concept_id = $1", grandparent
    )

    statuses = {
        row["concept_id"]: row["status"]
        for row in await conn.fetch(
            "SELECT concept_id, status FROM concept_registry WHERE concept_id = ANY($1::uuid[])",
            [parent, child],
        )
    }
    assert statuses[parent] == "deprecated"
    assert statuses[child] == "deprecated"

    cascade_concept_ids = {
        row["concept_id"]
        for row in await conn.fetch(
            "SELECT concept_id FROM concept_transition_log "
            "WHERE concept_id = ANY($1::uuid[]) AND trigger_reason = 'parent_cascade'",
            [parent, child],
        )
    }
    assert cascade_concept_ids == {
        parent,
        child,
    }, f"expected a parent_cascade row for both {parent} and {child}, got {cascade_concept_ids}"


@pytest.mark.asyncio
async def test_cycle_rejected_on_update_path(conn: _TrackedConnection) -> None:
    """The cycle guard is declared BEFORE INSERT OR UPDATE -- an insert-only test suite leaves
    half its declared surface unexercised. Build A -> B -> C (no cycle), then attempt to
    repoint B's parent from A to its own descendant C via an actual UPDATE (not a second
    INSERT). Assert the same cycle rejection fires, and assert the original edge survived the
    failed UPDATE (no partial state)."""
    concept_a = await _make_concept(conn)
    concept_b = await _make_concept(conn)
    concept_c = await _make_concept(conn)

    await _link(conn, child=concept_b, parent=concept_a)
    await _link(conn, child=concept_c, parent=concept_b)

    with pytest.raises(asyncpg.exceptions.PostgresError, match="concept_parent cycle rejected"):
        await conn.execute(
            "UPDATE concept_parent SET parent_concept_id = $1 "
            "WHERE child_concept_id = $2 AND parent_concept_id = $3",
            concept_c,
            concept_b,
            concept_a,
        )

    surviving_parent = await conn.fetchval(
        "SELECT parent_concept_id FROM concept_parent WHERE child_concept_id = $1", concept_b
    )
    assert surviving_parent == concept_a, (
        "the original A->B edge must survive an UPDATE rejected by the cycle guard, "
        f"got parent_concept_id={surviving_parent}"
    )
