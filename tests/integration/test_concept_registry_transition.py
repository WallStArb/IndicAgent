"""Integration tests: ConceptRegistryService.record_transition against indicagent_test
(todo 402; replaces the Phase 170 Plan 04 sync-path tests, whose psycopg twins and
concept_gate run counters were deleted with ic_engine's lifecycle hook).

Setup and assertions use a plain psycopg connection; the call under test runs on an
asyncpg connection, its real driver. Each test creates its own throwaway concept and
the fixture removes it. Never touches the live `indicagent` database.

The derivation rules the counters used to carry (hysteresis, recovery floors) are pure
now and covered in tests/unit/test_feature_lifecycle.py.

Run: pytest tests/integration/test_concept_registry_transition.py -m integration
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from uuid import uuid4

import asyncpg
import psycopg
import pytest

from src.intelligence.concept_registry_service import ConceptRegistryService

pytestmark = [pytest.mark.integration, pytest.mark.requires_db]

_TEST_DB_URL = "postgresql://postgres:postgres@localhost:5432/indicagent_test"
_DOMAIN = "feature"


def _name() -> str:
    return f"_t402_{uuid4().hex[:8]}"


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
                    "todo 402 record_transition test fixture",
                    status,
                    status == "active",
                ),
            )
            concept_id = cur.fetchone()[0]
            cur.execute(
                "INSERT INTO concept_gate "
                "(concept_id, gate_metric_name, gate_eval_method, min_gate_metric, "
                " min_gate_n, fdr_required) "
                "VALUES (%s, %s, %s, %s, %s, %s)",
                (
                    concept_id,
                    "ic_sharpe_hac",
                    "bootstrap_ci",
                    min_gate_metric,
                    min_gate_n,
                    fdr_required,
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


def _transition(**kwargs) -> bool:
    async def _go() -> bool:
        conn = await asyncpg.connect(_TEST_DB_URL)
        try:
            return await ConceptRegistryService().record_transition(conn, domain=_DOMAIN, **kwargs)
        finally:
            await conn.close()

    return asyncio.run(_go())


def test_demotion_flips_status_and_enabled_and_logs(db: _Db) -> None:
    name = db.make_concept(status="active")
    applied = _transition(
        name=name,
        from_status="active",
        to_status="shadow_only",
        reason="demotion_performance",
        gate_metric=-0.2,
        gate_n=4000.0,
        ci_lower=-0.03,
    )
    assert applied is True
    assert db.fetch_registry_row(name) == ("shadow_only", False)
    assert db.transition_log_rows(name) == [
        ("active", "shadow_only", "demotion_performance", -0.2, 4000.0, -0.03)
    ]


def test_stale_from_status_is_noop(db: _Db) -> None:
    name = db.make_concept(status="shadow_only")
    applied = _transition(
        name=name, from_status="active", to_status="shadow_only", reason="demotion_performance"
    )
    assert applied is False
    assert db.fetch_registry_row(name) == ("shadow_only", False)
    assert db.transition_log_rows(name) == []


def test_promotion_blocked_when_fdr_required_and_unproven(db: _Db) -> None:
    name = db.make_concept(status="shadow_only", fdr_required=True)
    assert (
        _transition(name=name, from_status="shadow_only", to_status="active", reason="promotion")
        is False
    )
    assert db.fetch_registry_row(name) == ("shadow_only", False)
    assert (
        _transition(
            name=name,
            from_status="shadow_only",
            to_status="active",
            reason="promotion",
            fdr_passed=True,
        )
        is True
    )
    assert db.fetch_registry_row(name) == ("active", True)


def test_operator_override_can_deprecate(db: _Db) -> None:
    name = db.make_concept(status="active")
    assert _transition(
        name=name, from_status="active", to_status="deprecated", reason="operator_override"
    )
    assert db.fetch_registry_row(name) == ("deprecated", False)
