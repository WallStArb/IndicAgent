"""Live-DB schema checks for the Layer 1 security classification tables (Phase 182, D-01, D-03).

These tests query the live `indicagent` DB, not the scratch `indicagent_test` DB. They are
marked `integration` and are NOT GitHub-CI-enforced (CI runs `tests/unit/` only, with no DB).
Run them locally with `--noconftest` until todo 413 fixes the conftest's scratch-DB rebuild
(it currently fails on migration 322):

    .venv/bin/pytest tests/integration/test_classification_schema.py -m integration --noconftest -q

Every write happens inside an explicit transaction that is always rolled back, so a run leaves
no trace in the live reference data.
"""

from __future__ import annotations

import asyncpg
import pytest

from src.config.classification_seed import NodeSeed, render_node_guard_sql
from src.config.classification_service import DEFAULT_SCHEME
from src.config.settings import get_settings

pytestmark = pytest.mark.integration


async def _connect() -> asyncpg.Connection:
    dsn = get_settings().database_url.replace("postgresql+asyncpg://", "postgresql://")
    return await asyncpg.connect(dsn)


async def _index_columns(conn: asyncpg.Connection, index_name: str) -> list[str]:
    rows = await conn.fetch(
        """
        SELECT a.attname
        FROM pg_index ix
        JOIN pg_class c ON c.oid = ix.indexrelid
        JOIN LATERAL unnest(ix.indkey) WITH ORDINALITY AS k(attnum, ord) ON true
        JOIN pg_attribute a ON a.attrelid = ix.indrelid AND a.attnum = k.attnum
        WHERE c.relname = $1
        ORDER BY k.ord
        """,
        index_name,
    )
    return [row["attname"] for row in rows]


async def test_instrument_classification_primary_key() -> None:
    conn = await _connect()
    try:
        pk_name = await conn.fetchval(
            "SELECT conname FROM pg_constraint "
            "WHERE conrelid = 'instrument_classification'::regclass AND contype = 'p'"
        )
        assert pk_name is not None
        assert await _index_columns(conn, pk_name) == ["symbol", "scheme", "valid_from"]
    finally:
        await conn.close()


async def test_current_row_unique_partial_index() -> None:
    conn = await _connect()
    try:
        row = await conn.fetchrow("""
            SELECT ix.indisunique, pg_get_expr(ix.indpred, ix.indrelid) AS predicate
            FROM pg_index ix JOIN pg_class c ON c.oid = ix.indexrelid
            WHERE c.relname = 'uq_instrument_classification_current'
            """)
        assert row is not None, "uq_instrument_classification_current missing"
        assert row["indisunique"] is True
        assert row["predicate"] == "(valid_to IS NULL)"
        assert await _index_columns(conn, "uq_instrument_classification_current") == [
            "symbol",
            "scheme",
        ]
    finally:
        await conn.close()


async def test_foreign_keys() -> None:
    conn = await _connect()
    try:
        symbol_fk = await conn.fetchval("""
            SELECT confdeltype FROM pg_constraint
            WHERE conrelid = 'instrument_classification'::regclass
              AND contype = 'f' AND confrelid = 'instruments'::regclass
            """)
        assert symbol_fk in ("r", b"r"), f"expected RESTRICT, got {symbol_fk!r}"

        self_fk = await conn.fetchval("""
            SELECT count(*) FROM pg_constraint
            WHERE conrelid = 'classification_node'::regclass
              AND contype = 'f' AND confrelid = 'classification_node'::regclass
            """)
        assert self_fk == 1

        node_pk = await conn.fetchval(
            "SELECT conname FROM pg_constraint "
            "WHERE conrelid = 'classification_node'::regclass AND contype = 'p'"
        )
        assert await _index_columns(conn, node_pk) == ["scheme", "code"]
    finally:
        await conn.close()


async def test_second_current_row_is_rejected() -> None:
    """Append-only: a second current row for the same (symbol, scheme) violates the index."""
    conn = await _connect()
    try:
        tr = conn.transaction()
        await tr.start()
        try:
            # Triggers off (migration 368 would refuse the scheduled date first) so this
            # exercises the constraints: the partial unique index or the 367 exclusion
            # constraint rejects a second open row, whichever Postgres checks first.
            await conn.execute("SET LOCAL session_replication_role = replica")
            with pytest.raises(asyncpg.IntegrityConstraintViolationError):
                await conn.execute(
                    "INSERT INTO instrument_classification "
                    "(symbol, scheme, code, valid_from, valid_to, source_ref) "
                    "VALUES ('SPY', $1, 'EQ.BROAD', DATE '2099-01-01', NULL, 'fund_mandate')",
                    DEFAULT_SCHEME,
                )
        finally:
            await tr.rollback()
    finally:
        await conn.close()


async def _run_guard_rolled_back(conn: asyncpg.Connection, sql: str) -> None:
    tr = conn.transaction()
    await tr.start()
    try:
        await conn.execute(sql)
    finally:
        await tr.rollback()


async def test_node_immutability_guard_raises_on_parent_change() -> None:
    conn = await _connect()
    try:
        bad = render_node_guard_sql(DEFAULT_SCHEME, [NodeSeed("EQ.IT.SEMI", "EQ.HC", 3, "Semis")])
        with pytest.raises(asyncpg.RaiseError, match="immutability violated"):
            await _run_guard_rolled_back(conn, bad)

        true_parent = await conn.fetchval(
            "SELECT parent_code FROM classification_node WHERE scheme = $1 AND code = 'EQ.IT.SEMI'",
            DEFAULT_SCHEME,
        )
        assert true_parent == "EQ.IT"
        good = render_node_guard_sql(
            DEFAULT_SCHEME, [NodeSeed("EQ.IT.SEMI", true_parent, 3, "Semis")]
        )
        await _run_guard_rolled_back(conn, good)
    finally:
        await conn.close()


async def test_node_paths_match_parent_chain() -> None:
    conn = await _connect()
    try:
        mismatches = await conn.fetch("""
            WITH RECURSIVE chain AS (
                SELECT scheme, code, ARRAY[code] AS rebuilt
                FROM classification_node WHERE parent_code IS NULL
                UNION ALL
                SELECT n.scheme, n.code, c.rebuilt || n.code
                FROM classification_node n
                JOIN chain c ON c.scheme = n.scheme AND c.code = n.parent_code
            )
            SELECT n.scheme, n.code, n.path, c.rebuilt
            FROM classification_node n
            LEFT JOIN chain c USING (scheme, code)
            WHERE c.rebuilt IS DISTINCT FROM n.path
            """)
        assert mismatches == [], [dict(r) for r in mismatches]
        assert await conn.fetchval("SELECT count(*) FROM classification_node") > 0
    finally:
        await conn.close()


async def test_no_scheme_named_gics() -> None:
    conn = await _connect()
    try:
        offenders = await conn.fetch(
            "SELECT scheme FROM classification_scheme "
            "WHERE name ILIKE '%gics%' OR authority ILIKE '%gics%' "
            "OR coalesce(source_ref, '') ILIKE '%gics%' OR scheme ILIKE '%gics%'"
        )
        assert offenders == []
        authority = await conn.fetchval(
            "SELECT authority FROM classification_scheme WHERE scheme = $1", DEFAULT_SCHEME
        )
        assert authority == "IndicAgent"
    finally:
        await conn.close()


# Migrations 367 and 368: point-in-time invariants enforced in the DB. Probes run rolled back.
_TODAY = "(now() AT TIME ZONE 'UTC')::date"
_REPLICA = "SET LOCAL session_replication_role = replica"
_ORIGIN = "SET LOCAL session_replication_role = origin"


@pytest.mark.parametrize(
    ("statements", "match"),
    [
        (
            [
                "INSERT INTO instrument_classification (symbol, scheme, code, valid_from, "
                "source_ref) VALUES ('SPY', 'indicagent_v1', 'EQ.BROAD', DATE '2026-01-01', "
                "'fund_mandate')"
            ],
            "must have valid_from = today",
        ),
        (
            [
                "INSERT INTO instrument_classification (symbol, scheme, code, valid_from, "
                f"source_ref) VALUES ('SPY', 'indicagent_v1', 'EQ.IT', {_TODAY} + 5, "
                "'fund_mandate')"
            ],
            "must have valid_from = today",
        ),
        (
            ["UPDATE instrument_classification SET code = 'EQ.IT' WHERE symbol = 'SPY'"],
            "only valid_to may change",
        ),
        (
            [f"UPDATE instrument_classification SET valid_to = {_TODAY} + 5 WHERE symbol = 'SPY'"],
            "valid_to = today",
        ),
        (
            [
                "UPDATE instrument_classification SET valid_to = DATE '2026-09-01' "
                "WHERE symbol = 'SPY'"
            ],
            "valid_to",
        ),
        (["DELETE FROM instrument_classification WHERE symbol = 'SPY'"], "append-only"),
        (["TRUNCATE instrument_classification"], "append-only"),
        (
            ["UPDATE classification_node SET parent_code = 'EQ.HC' " "WHERE code = 'EQ.IT.SEMI'"],
            "identity columns are immutable",
        ),
        (
            [
                "INSERT INTO classification_node (scheme, code, parent_code, level, name, "
                "path, valid_from) VALUES ('indicagent_v1', 'EQ.IT.ZZ', 'EQ.IT', 3, 'Test', "
                f"ARRAY['EQ', 'EQ.FIN', 'EQ.IT.ZZ'], {_TODAY})"
            ],
            "does not extend parent",
        ),
        (
            [
                _REPLICA,
                "INSERT INTO instrument_classification (symbol, scheme, code, valid_from, "
                "valid_to, source_ref) VALUES ('SPY', 'indicagent_v1', 'EQ.IT', "
                "DATE '2020-01-01', DATE '2030-01-01', 'fund_mandate')",
            ],
            "ex_instrument_classification_no_overlap",
        ),
    ],
)
async def test_point_in_time_guards_reject_history_rewrites(statements, match) -> None:
    conn = await _connect()
    try:
        tr = conn.transaction()
        await tr.start()
        try:
            with pytest.raises(asyncpg.PostgresError, match=match):
                for sql in statements:
                    await conn.execute(sql)
        finally:
            await tr.rollback()
    finally:
        await conn.close()


async def test_same_day_reclassification_and_node_insert_are_allowed() -> None:
    """Close the current row today and open the next one today; add a node whose path
    extends its parent's. The existing row is backdated with triggers off first, because a
    row opened today cannot also be closed today (valid_to > valid_from)."""
    conn = await _connect()
    try:
        tr = conn.transaction()
        await tr.start()
        try:
            await conn.execute(_REPLICA)
            await conn.execute(
                f"UPDATE instrument_classification SET valid_from = {_TODAY} - 3 "
                "WHERE symbol = 'SPY' AND valid_to IS NULL"
            )
            await conn.execute(_ORIGIN)
            await conn.execute(
                f"UPDATE instrument_classification SET valid_to = {_TODAY} "
                "WHERE symbol = 'SPY' AND valid_to IS NULL"
            )
            await conn.execute(
                "INSERT INTO instrument_classification (symbol, scheme, code, valid_from, "
                f"source_ref) VALUES ('SPY', 'indicagent_v1', 'EQ.IT', {_TODAY}, 'fund_mandate')"
            )
            await conn.execute(
                "INSERT INTO classification_node (scheme, code, parent_code, level, name, "
                "path, valid_from) VALUES ('indicagent_v1', 'EQ.IT.ZZ', 'EQ.IT', 3, 'Test', "
                f"ARRAY['EQ', 'EQ.IT', 'EQ.IT.ZZ'], {_TODAY})"
            )
        finally:
            await tr.rollback()
    finally:
        await conn.close()
