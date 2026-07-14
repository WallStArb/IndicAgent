"""Integration test: production/migrations/ must reproduce the live schema (todo 119).

Phase 160 shipped two committed migration files that were NOT the SQL actually applied
to the `indicagent` database - a worktree-executed migration got regenerated from a plan
description instead of merged when folded into main, silently drifting on column types,
missing columns, CHECK vocabulary, and an APR key namespace. It survived a full plan
review and unit tests undetected; only a later code-review pass caught it via manual git
archaeology. See commit 6f1b4257 and feedback_gsd_worktree_venv_missing.md (second
pattern) in project memory.

This test closes that gap mechanically: tests/integration/conftest.py's
`migrated_test_database` fixture rebuilds `indicagent_test` from empty by replaying every
file in production/migrations/ (also fixes todo 064 - indicagent_test previously had only
3 legacy tables, so tests/integration/test_instrument_registry.py etc. failed). This test
then diffs the resulting schema against the live `indicagent` database. Any divergence -
column type, nullability, CHECK/PK/FK/UNIQUE constraint definition, or table existence -
means the committed migrations no longer describe production truth, which is exactly the
kind of silent, non-announcing defect this project's audit-trail tables (concept_registry,
feature_registry, config_history, ...) depend on not having.

Run: pytest tests/integration/test_migration_schema_sync.py -m integration
"""

from __future__ import annotations

import asyncpg
import pytest

pytestmark = pytest.mark.integration

# Bypasses get_settings()/conftest.py's cached indicagent_test DATABASE_URL - this test
# needs both databases open at once (test_feature_vectors_schema.py documents the same
# override idiom for the same reason).
_PROD_DB_URL = "postgresql://postgres:postgres@localhost:5432/indicagent"
_TEST_DB_URL = "postgresql://postgres:postgres@localhost:5432/indicagent_test"

_COLUMNS_SQL = """
    SELECT table_name, column_name, udt_name, is_nullable
    FROM information_schema.columns
    WHERE table_schema = 'public'
    ORDER BY table_name, column_name
"""

_CONSTRAINTS_SQL = """
    SELECT conrelid::regclass::text AS table_name, pg_get_constraintdef(oid) AS definition
    FROM pg_constraint
    WHERE connamespace = 'public'::regnamespace
    ORDER BY conrelid::regclass::text, definition
"""

_TABLES_SQL = """
    SELECT table_name FROM information_schema.tables
    WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
"""


async def _fetch_schema(dsn: str) -> tuple[set[str], dict[str, set[tuple]], dict[str, set[str]]]:
    conn = await asyncpg.connect(dsn)
    try:
        tables = {r["table_name"] for r in await conn.fetch(_TABLES_SQL)}

        columns: dict[str, set[tuple]] = {}
        for row in await conn.fetch(_COLUMNS_SQL):
            columns.setdefault(row["table_name"], set()).add(
                (row["column_name"], row["udt_name"], row["is_nullable"])
            )

        constraints: dict[str, set[str]] = {}
        for row in await conn.fetch(_CONSTRAINTS_SQL):
            constraints.setdefault(row["table_name"], set()).add(row["definition"])

        return tables, columns, constraints
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_migrated_schema_matches_production():
    """Every table/column/constraint in production must be reproducible from migrations alone."""
    prod_tables, prod_columns, prod_constraints = await _fetch_schema(_PROD_DB_URL)
    test_tables, test_columns, test_constraints = await _fetch_schema(_TEST_DB_URL)

    failures: list[str] = []

    only_in_prod = sorted(prod_tables - test_tables)
    only_in_test = sorted(test_tables - prod_tables)
    if only_in_prod:
        failures.append(
            f"tables in production but NOT reproduced by replaying migrations: {only_in_prod}"
        )
    if only_in_test:
        failures.append(f"tables produced by migrations but absent from production: {only_in_test}")

    for table in sorted(prod_tables & test_tables):
        prod_cols = prod_columns.get(table, set())
        test_cols = test_columns.get(table, set())
        missing = sorted(prod_cols - test_cols)
        extra = sorted(test_cols - prod_cols)
        if missing:
            failures.append(
                f"{table}: columns in production, missing from migrated schema: {missing}"
            )
        if extra:
            failures.append(
                f"{table}: columns produced by migrations, absent from production: {extra}"
            )

        prod_cons = prod_constraints.get(table, set())
        test_cons = test_constraints.get(table, set())
        missing_cons = sorted(prod_cons - test_cons)
        extra_cons = sorted(test_cons - prod_cons)
        if missing_cons:
            failures.append(
                f"{table}: constraints in production, missing from migrated schema: {missing_cons}"
            )
        if extra_cons:
            failures.append(
                f"{table}: constraints produced by migrations, absent from production: {extra_cons}"
            )

    assert not failures, (
        "production/migrations/ does not reproduce the live schema "
        f"({len(failures)} divergence(s)):\n" + "\n".join(f"  - {f}" for f in failures)
    )
