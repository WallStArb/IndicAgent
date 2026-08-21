"""Integration tests: ConceptRegistryService's synchronous psycopg lifecycle path
(Phase 170 Plan 04, todo 118 scope item 2).

These are real psycopg-connection tests against `indicagent_test`, matching the sync
API's real driver (ic_engine.py's actual caller is psycopg, no event loop) -- unlike
tests/unit/test_concept_registry_service.py, which covers the async
decide_comparison_action/record_comparison_outcome path with pure helpers and asyncpg
FakeConn stubs. Lives under tests/integration/ (not tests/unit/) because the DB
fixture (migrated_test_database, tests/integration/conftest.py) that replays
migrations 283/284 into indicagent_test only exists there.

Each test creates its own domain='feature' concept + concept_gate row with a unique
name (f"_t170sync_{uuid4().hex[:8]}") via the `db` fixture below, and the fixture
cleans up afterward. Never touches the live `indicagent` database.

Coverage-parity mapping vs tests/unit/intelligence/test_feature_registry_service.py
(that file is DELETED in Plan 08 -- its record_transition_sync/
advance_shadow_counters_sync/is_promotion_eligible coverage would otherwise vanish
silently):

  FeatureRegistryService test (old)                         -> ConceptRegistryService test (new)
  ---------------------------------------------------------------------------------------------
  test_transactional_insert_and_update_commit               -> test_transition_active_to_shadow_only_writes_log_and_flips_status
  test_optimistic_lock_noop_on_rowcount_zero                -> test_cas_stale_from_status_is_noop
  test_counter_reset_on_second_demotion                      -> test_demotion_to_shadow_only_resets_both_counters
  test_active_to_active_style_update_does_not_touch_counters -> test_promotion_to_active_does_not_reset_counters
  test_rejects_automated_transition_to_deprecated  +
    test_operator_override_to_deprecated_is_allowed          -> test_automated_reason_cannot_target_deprecated
  test_passing_run_increments_passes_and_adds_observations +
    test_failing_run_resets_passes_but_still_adds_observations -> test_advance_shadow_counters_increments_on_pass_and_resets_on_fail
  TestIsPromotionEligible (all 6 cases)                      -> test_is_promotion_eligible_requires_both_floors
  (new, todo 118 L-6 sync-side)                              -> test_promotion_blocked_when_fdr_required_and_unproven
  (new)                                                      -> test_invalid_trigger_reason_raises_before_write
  test_cache_coherency_after_commit                          -> test_cache_mutation_visible_to_is_promotion_eligible
  (new -- bare `with conn:` connection-closing trap regression) -> test_reused_connection_survives_multiple_transitions

Deliberately NOT ported: FeatureRegistryService's get_active_features/get_feature/
get_status/get_ic_sharpe_gate tests. Those accessors have zero production callers
(verified via grep in the plan's <interfaces> block) and are deliberately NOT ported
onto ConceptRegistryService (Musk step 2 -- delete before adding); porting their
tests would pin dead surface area that this plan explicitly excludes.

Run: pytest tests/integration/test_concept_registry_sync_lifecycle.py -m integration
"""

from __future__ import annotations

from collections.abc import Iterator
from uuid import uuid4

import psycopg
import pytest

from src.intelligence.concept_registry_service import ConceptRegistryService

pytestmark = [pytest.mark.integration, pytest.mark.requires_db]

_TEST_DB_URL = "postgresql://postgres:postgres@localhost:5432/indicagent_test"
_DOMAIN = "feature"


def _name() -> str:
    return f"_t170sync_{uuid4().hex[:8]}"


class _Db:
    """Bundles a real psycopg connection with the throwaway names this test created,
    so the fixture teardown below can clean up exactly what each test made."""

    def __init__(self, conn: psycopg.Connection) -> None:
        self.conn = conn
        self.created_names: list[str] = []

    def make_concept(
        self,
        *,
        status: str = "active",
        consecutive_shadow_passes: int = 0,
        observations_since_demotion: int = 0,
        fdr_required: bool = False,
        min_gate_metric: float | None = None,
        min_gate_n: float | None = None,
    ) -> str:
        """Insert one throwaway domain='feature' concept_registry + concept_gate row
        pair and return its name. enabled is set to match status = 'active', mirroring
        migration 284's invariant -- the fixture is a snapshot of a pre-existing row,
        not a call through the service under test."""
        name = _name()
        self.created_names.append(name)
        with self.conn.cursor() as cur:
            cur.execute(
                "INSERT INTO concept_registry "
                "(domain, name, description, status, enabled) "
                "VALUES (%s, %s, %s, %s, %s) RETURNING concept_id",
                (
                    _DOMAIN,
                    name,
                    "Phase 170 Plan 04 sync lifecycle test fixture",
                    status,
                    status == "active",
                ),
            )
            concept_id = cur.fetchone()[0]
            cur.execute(
                "INSERT INTO concept_gate "
                "(concept_id, gate_metric_name, gate_eval_method, min_gate_metric, "
                " min_gate_n, fdr_required, consecutive_shadow_passes, "
                " observations_since_demotion) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    concept_id,
                    "ic_sharpe_hac",
                    "bootstrap_ci",
                    min_gate_metric,
                    min_gate_n,
                    fdr_required,
                    consecutive_shadow_passes,
                    observations_since_demotion,
                ),
            )
        self.conn.commit()
        return name

    def fetch_registry_row(self, name: str) -> tuple[str, bool]:
        with self.conn.cursor() as cur:
            cur.execute(
                "SELECT status, enabled FROM concept_registry WHERE domain = %s AND name = %s",
                (_DOMAIN, name),
            )
            row = cur.fetchone()
        assert row is not None, f"no concept_registry row for {name!r}"
        return row[0], row[1]

    def fetch_gate_row(self, name: str) -> tuple[int, int]:
        with self.conn.cursor() as cur:
            cur.execute(
                "SELECT g.consecutive_shadow_passes, g.observations_since_demotion "
                "FROM concept_gate g JOIN concept_registry r USING (concept_id) "
                "WHERE r.domain = %s AND r.name = %s",
                (_DOMAIN, name),
            )
            row = cur.fetchone()
        assert row is not None, f"no concept_gate row for {name!r}"
        return row[0], row[1]

    def fetch_active_fails(self, name: str) -> int:
        with self.conn.cursor() as cur:
            cur.execute(
                "SELECT g.consecutive_active_fails "
                "FROM concept_gate g JOIN concept_registry r USING (concept_id) "
                "WHERE r.domain = %s AND r.name = %s",
                (_DOMAIN, name),
            )
            row = cur.fetchone()
        assert row is not None, f"no concept_gate row for {name!r}"
        return row[0]

    def transition_log_rows(self, name: str) -> list[tuple]:
        with self.conn.cursor() as cur:
            cur.execute(
                "SELECT from_status, to_status, trigger_reason, gate_metric, gate_n, ci_lower "
                "FROM concept_transition_log WHERE domain = %s AND name = %s "
                "ORDER BY triggered_at",
                (_DOMAIN, name),
            )
            return cur.fetchall()


@pytest.fixture
def db() -> Iterator[_Db]:
    conn = psycopg.connect(_TEST_DB_URL)
    conn.autocommit = False
    wrapper = _Db(conn)
    try:
        yield wrapper
    finally:
        if wrapper.created_names:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM concept_transition_log WHERE domain = %s AND name = ANY(%s)",
                    (_DOMAIN, wrapper.created_names),
                )
                cur.execute(
                    "DELETE FROM concept_gate g USING concept_registry r "
                    "WHERE g.concept_id = r.concept_id AND r.domain = %s AND r.name = ANY(%s)",
                    (_DOMAIN, wrapper.created_names),
                )
                cur.execute(
                    "DELETE FROM concept_registry WHERE domain = %s AND name = ANY(%s)",
                    (_DOMAIN, wrapper.created_names),
                )
            conn.commit()
        conn.close()


# ---------------------------------------------------------------------------
# record_transition_sync
# ---------------------------------------------------------------------------


def test_transition_active_to_shadow_only_writes_log_and_flips_status(db: _Db) -> None:
    name = db.make_concept(status="active")
    service = ConceptRegistryService()

    result = service.record_transition_sync(
        db.conn,
        domain=_DOMAIN,
        name=name,
        from_status="active",
        to_status="shadow_only",
        reason="demotion_performance",
        gate_metric=0.0123,
        gate_n=1500.0,
        ci_lower=0.004,
    )

    assert result is True
    status, enabled = db.fetch_registry_row(name)
    assert status == "shadow_only"
    assert enabled is False

    rows = db.transition_log_rows(name)
    assert len(rows) == 1
    from_status, to_status, trigger_reason, gate_metric, gate_n, ci_lower = rows[0]
    assert from_status == "active"
    assert to_status == "shadow_only"
    assert trigger_reason == "demotion_performance"
    assert gate_metric == pytest.approx(0.0123)
    assert gate_n == pytest.approx(1500.0)
    assert ci_lower == pytest.approx(0.004)


def test_cas_stale_from_status_is_noop(db: _Db) -> None:
    name = db.make_concept(status="active")
    service = ConceptRegistryService()

    result = service.record_transition_sync(
        db.conn,
        domain=_DOMAIN,
        name=name,
        from_status="shadow_only",  # stale -- real status is 'active'
        to_status="shadow_only",
        reason="demotion_performance",
    )

    assert result is False
    status, _ = db.fetch_registry_row(name)
    assert status == "active"
    # The rollback property: zero orphan transition-log rows, not merely a False return.
    assert db.transition_log_rows(name) == []


def test_demotion_to_shadow_only_resets_both_counters(db: _Db) -> None:
    name = db.make_concept(
        status="active",
        consecutive_shadow_passes=3,
        observations_since_demotion=9999,
    )
    service = ConceptRegistryService()

    result = service.record_transition_sync(
        db.conn,
        domain=_DOMAIN,
        name=name,
        from_status="active",
        to_status="shadow_only",
        reason="demotion_performance",
    )

    assert result is True
    passes, observations = db.fetch_gate_row(name)
    assert passes == 0
    assert observations == 0


def test_promotion_to_active_does_not_reset_counters(db: _Db) -> None:
    name = db.make_concept(
        status="shadow_only",
        consecutive_shadow_passes=2,
        observations_since_demotion=5000,
    )
    service = ConceptRegistryService()

    result = service.record_transition_sync(
        db.conn,
        domain=_DOMAIN,
        name=name,
        from_status="shadow_only",
        to_status="active",
        reason="promotion",
    )

    assert result is True
    passes, observations = db.fetch_gate_row(name)
    assert passes == 2
    assert observations == 5000


def test_automated_reason_cannot_target_deprecated(db: _Db) -> None:
    name = db.make_concept(status="shadow_only")
    service = ConceptRegistryService()

    with pytest.raises(ValueError, match="operator-only"):
        service.record_transition_sync(
            db.conn,
            domain=_DOMAIN,
            name=name,
            from_status="shadow_only",
            to_status="deprecated",
            reason="demotion_performance",
        )

    status, _ = db.fetch_registry_row(name)
    assert status == "shadow_only"
    assert db.transition_log_rows(name) == []

    # operator_override to 'deprecated' is the legitimate path.
    result = service.record_transition_sync(
        db.conn,
        domain=_DOMAIN,
        name=name,
        from_status="shadow_only",
        to_status="deprecated",
        reason="operator_override",
    )
    assert result is True
    status, enabled = db.fetch_registry_row(name)
    assert status == "deprecated"
    assert enabled is False


def test_promotion_blocked_when_fdr_required_and_unproven(db: _Db) -> None:
    name = db.make_concept(status="shadow_only", fdr_required=True)
    service = ConceptRegistryService()

    for fdr_passed in (None, False):
        result = service.record_transition_sync(
            db.conn,
            domain=_DOMAIN,
            name=name,
            from_status="shadow_only",
            to_status="active",
            reason="promotion",
            fdr_passed=fdr_passed,
        )
        assert result is False, f"expected block for fdr_passed={fdr_passed!r}"
        status, _ = db.fetch_registry_row(name)
        assert status == "shadow_only"
        assert db.transition_log_rows(name) == []

    result = service.record_transition_sync(
        db.conn,
        domain=_DOMAIN,
        name=name,
        from_status="shadow_only",
        to_status="active",
        reason="promotion",
        fdr_passed=True,
    )
    assert result is True
    status, enabled = db.fetch_registry_row(name)
    assert status == "active"
    assert enabled is True
    assert len(db.transition_log_rows(name)) == 1


def test_invalid_trigger_reason_raises_before_write(db: _Db) -> None:
    name = db.make_concept(status="active")
    service = ConceptRegistryService()

    with pytest.raises(ValueError, match="bogus_reason"):
        service.record_transition_sync(
            db.conn,
            domain=_DOMAIN,
            name=name,
            from_status="active",
            to_status="shadow_only",
            reason="bogus_reason",
        )

    status, _ = db.fetch_registry_row(name)
    assert status == "active"
    assert db.transition_log_rows(name) == []


# ---------------------------------------------------------------------------
# advance_shadow_counters_sync
# ---------------------------------------------------------------------------


def test_advance_shadow_counters_increments_on_pass_and_resets_on_fail(db: _Db) -> None:
    name = db.make_concept(
        status="shadow_only",
        consecutive_shadow_passes=1,
        observations_since_demotion=500,
    )
    service = ConceptRegistryService()

    service.advance_shadow_counters_sync(
        db.conn,
        domain=_DOMAIN,
        name=name,
        passed=True,
        new_observations=300,
        expected_status="shadow_only",
    )
    passes, observations = db.fetch_gate_row(name)
    assert passes == 2
    assert observations == 800

    # A failing run zeroes the pass streak but STILL adds observations (asymmetric,
    # deliberate in the ported original).
    service.advance_shadow_counters_sync(
        db.conn,
        domain=_DOMAIN,
        name=name,
        passed=False,
        new_observations=300,
        expected_status="shadow_only",
    )
    passes, observations = db.fetch_gate_row(name)
    assert passes == 0
    assert observations == 1100


def test_advance_shadow_counters_stale_status_is_noop(db: _Db) -> None:
    """Todo 337: the concept is actually 'active' (already promoted by a concurrent
    writer since the caller's in-memory read) -- advancing shadow counters against a
    stale expected_status='shadow_only' must not touch the row."""
    name = db.make_concept(
        status="active",
        consecutive_shadow_passes=1,
        observations_since_demotion=500,
    )
    service = ConceptRegistryService()

    result = service.advance_shadow_counters_sync(
        db.conn,
        domain=_DOMAIN,
        name=name,
        passed=True,
        new_observations=300,
        expected_status="shadow_only",  # stale -- real status is 'active'
    )

    assert result is False
    passes, observations = db.fetch_gate_row(name)
    assert passes == 1
    assert observations == 500


# ---------------------------------------------------------------------------
# advance_active_counters_sync
# ---------------------------------------------------------------------------


def test_advance_active_counters_increments_on_fail_and_resets_on_pass(db: _Db) -> None:
    name = db.make_concept(status="active")
    service = ConceptRegistryService()

    service.advance_active_counters_sync(
        db.conn, domain=_DOMAIN, name=name, passed=False, expected_status="active"
    )
    assert db.fetch_active_fails(name) == 1

    service.advance_active_counters_sync(
        db.conn, domain=_DOMAIN, name=name, passed=False, expected_status="active"
    )
    assert db.fetch_active_fails(name) == 2

    # A passing run resets the fail streak to 0.
    service.advance_active_counters_sync(
        db.conn, domain=_DOMAIN, name=name, passed=True, expected_status="active"
    )
    assert db.fetch_active_fails(name) == 0


def test_advance_active_counters_stale_status_is_noop(db: _Db) -> None:
    """Todo 337: the concept is actually 'shadow_only' (already demoted by a
    concurrent writer since the caller's in-memory read) -- advancing active counters
    against a stale expected_status='active' must not touch the row."""
    name = db.make_concept(status="shadow_only")
    service = ConceptRegistryService()

    result = service.advance_active_counters_sync(
        db.conn,
        domain=_DOMAIN,
        name=name,
        passed=False,
        expected_status="active",  # stale -- real status is 'shadow_only'
    )

    assert result is False
    assert db.fetch_active_fails(name) == 0


# ---------------------------------------------------------------------------
# is_promotion_eligible
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "passes,observations,min_passes,min_observations,expected",
    [
        (2, 2000, 2, 2000, True),
        (1, 2000, 2, 2000, False),  # passes unmet
        (2, 1999, 2, 2000, False),  # observations unmet
        (0, 0, 2, 2000, False),  # neither met
    ],
)
def test_is_promotion_eligible_requires_both_floors(
    passes: int, observations: int, min_passes: int, min_observations: int, expected: bool
) -> None:
    service = ConceptRegistryService()
    service._concepts["_t170sync_eligibility"] = {
        "name": "_t170sync_eligibility",
        "consecutive_shadow_passes": passes,
        "observations_since_demotion": observations,
    }
    assert (
        service.is_promotion_eligible(
            "_t170sync_eligibility",
            recovery_min_observations=min_observations,
            recovery_min_passes=min_passes,
        )
        is expected
    )


def test_is_promotion_eligible_false_for_unknown_name() -> None:
    service = ConceptRegistryService()
    assert (
        service.is_promotion_eligible(
            "ghost_concept", recovery_min_observations=2000, recovery_min_passes=2
        )
        is False
    )


# ---------------------------------------------------------------------------
# load_sync + cache coherency
# ---------------------------------------------------------------------------


def test_cache_mutation_visible_to_is_promotion_eligible(db: _Db) -> None:
    name = db.make_concept(
        status="shadow_only",
        consecutive_shadow_passes=1,
        observations_since_demotion=1800,
    )
    service = ConceptRegistryService()
    service.load_sync(db.conn, domain=_DOMAIN)

    assert (
        service.is_promotion_eligible(name, recovery_min_observations=2000, recovery_min_passes=2)
        is False
    )

    # Advance past both floors without reloading -- the in-process cache mutation
    # must be visible to an immediately-following is_promotion_eligible read.
    service.advance_shadow_counters_sync(
        db.conn,
        domain=_DOMAIN,
        name=name,
        passed=True,
        new_observations=300,
        expected_status="shadow_only",
    )

    assert (
        service.is_promotion_eligible(name, recovery_min_observations=2000, recovery_min_passes=2)
        is True
    )


# ---------------------------------------------------------------------------
# Connection reuse (bare `with conn:` regression guard)
# ---------------------------------------------------------------------------


def test_reused_connection_survives_multiple_transitions(db: _Db) -> None:
    name_a = db.make_concept(status="active")
    name_b = db.make_concept(status="shadow_only")
    name_c = db.make_concept(status="shadow_only", fdr_required=False)
    service = ConceptRegistryService()

    assert (
        service.record_transition_sync(
            db.conn,
            domain=_DOMAIN,
            name=name_a,
            from_status="active",
            to_status="shadow_only",
            reason="demotion_performance",
        )
        is True
    )
    assert (
        service.record_transition_sync(
            db.conn,
            domain=_DOMAIN,
            name=name_b,
            from_status="shadow_only",
            to_status="active",
            reason="promotion",
        )
        is True
    )
    assert (
        service.record_transition_sync(
            db.conn,
            domain=_DOMAIN,
            name=name_c,
            from_status="shadow_only",
            to_status="deprecated",
            reason="operator_override",
        )
        is True
    )

    # The connection must still be open and usable -- a bare `with conn:` exit
    # would have closed it after the first transition (psycopg, unlike psycopg2,
    # closes the connection on that exit).
    assert not db.conn.closed
    with db.conn.cursor() as cur:
        cur.execute("SELECT 1")
        assert cur.fetchone() == (1,)
