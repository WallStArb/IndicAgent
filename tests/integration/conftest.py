"""Shared fixtures for tests/integration/.

Rebuilds `indicagent_test` from a pinned schema baseline before any integration test
runs (session-scoped, autouse) - see todo 064/119. Fixes 064 (indicagent_test
previously had only 3 legacy tables, so tests/integration/test_instrument_registry.py
etc. failed) and gives test_migration_schema_sync.py a freshly-rebuilt database to
diff against production.

Why a pinned baseline instead of replaying production/migrations/ from empty:
attempting a true from-empty replay (all 226 files) surfaced that ~25% of migrations
cannot apply to an empty database at all - `signal_ledger` and `instruments` are
referenced by dozens of early migrations but their original CREATE TABLE predates this
migrations/ directory existing as the source of truth, plus a handful of genuine bugs
(missing pg_trgm/pgvector extensions, CREATE INDEX CONCURRENTLY inside a hypertable,
one bad RAISE call). Reconstructing 20 years of lost DDL history is high-risk guesswork
for zero forward value. The standard fix for exactly this situation: pin a schema-only
snapshot of production as of a known date (tests/integration/fixtures/schema_baseline_*),
and only require true replay-reproducibility for migrations added AFTER that date - which
is exactly the class of drift (Phase 160's migrations 233/234) this check exists to catch.

Deliberately a directory-level conftest.py (not folded into tests/conftest.py) so the
rebuild cost is only paid for the tests/integration/ suite, never the unit test loop.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from pathlib import Path

import asyncpg
import pytest

_MAINTENANCE_DB_URL = "postgresql://postgres:postgres@localhost:5432/postgres"
_TEST_DB_URL = "postgresql://postgres:postgres@localhost:5432/indicagent_test"
_TEST_DB_NAME = "indicagent_test"

_FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
_BASELINE_SCHEMA_SQL = _FIXTURES_DIR / "schema_baseline_2026-07-14.sql"
_BASELINE_HYPERTABLES_SQL = _FIXTURES_DIR / "schema_baseline_2026-07-14_hypertables.sql"
_SEED_INSTRUMENTS_SQL = _FIXTURES_DIR / "seed_instruments_2026-07-14.sql"

# Highest migration number folded into the baseline snapshot above. Only migrations
# numbered above this need to be replayed on top - everything <= this is already
# reflected in the pinned schema dump. Bump this (and regenerate the baseline files)
# periodically, or whenever this drifts far enough to be annoying.
_BASELINE_MIGRATION_CUTOFF = 234

_MIGRATIONS_DIR = Path(__file__).resolve().parent.parent.parent / "production" / "migrations"


def _migration_number(path: Path) -> int:
    digits = "".join(ch for ch in path.name.split("_", 1)[0] if ch.isdigit())
    return int(digits) if digits else 0


async def _recreate_test_database() -> None:
    conn = await asyncpg.connect(_MAINTENANCE_DB_URL)
    try:
        await conn.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            "WHERE datname = $1 AND pid <> pg_backend_pid()",
            _TEST_DB_NAME,
        )
        await conn.execute(f"DROP DATABASE IF EXISTS {_TEST_DB_NAME}")
        await conn.execute(f"CREATE DATABASE {_TEST_DB_NAME}")
    finally:
        await conn.close()


def _run_psql_file(path: Path, *, tolerate_stderr_substrings: tuple[str, ...] = ()) -> None:
    env = {**os.environ, "PGPASSWORD": "postgres"}
    result = subprocess.run(
        [
            "psql",
            "-U",
            "postgres",
            "-h",
            "localhost",
            "-d",
            _TEST_DB_NAME,
            "-v",
            "ON_ERROR_STOP=1",
            "-f",
            str(path),
        ],
        env=env,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0 and not any(s in result.stderr for s in tolerate_stderr_substrings):
        raise RuntimeError(f"applying {path.name} failed:\n{result.stderr}")


async def _run_sql(sql: str) -> None:
    conn = await asyncpg.connect(_TEST_DB_URL)
    try:
        await conn.execute(sql)
    finally:
        await conn.close()


def _apply_baseline() -> None:
    asyncio.run(_run_sql("SELECT timescaledb_pre_restore();"))
    _run_psql_file(_BASELINE_SCHEMA_SQL)
    asyncio.run(_run_sql("SELECT timescaledb_post_restore();"))
    # Baseline dump is schema-only; TimescaleDB's hypertable registration lives in
    # extension-owned catalog tables that --schema-only excludes, so re-register
    # explicitly. Several already come out of the dump as natively partitioned
    # (recent TimescaleDB stores hypertables via Postgres declarative partitioning),
    # which create_hypertable() then correctly refuses to convert further - the
    # structural partitioning is already present from the dump either way.
    _run_psql_file(
        _BASELINE_HYPERTABLES_SQL,
        tolerate_stderr_substrings=("already a hypertable", "already partitioned"),
    )
    # Schema alone isn't a usable test database - a green test against zero rows is a
    # false-confidence signal, not a real check. instruments is small (~100 rows) and a
    # correctness-relevant reference table (get_active_contracts() reads it), so seed it
    # from a real production snapshot rather than leaving tests/integration/test_instrument_
    # registry.py passing against fabricated data or failing against none.
    _run_psql_file(_SEED_INSTRUMENTS_SQL)


def _replay_post_baseline_migrations() -> None:
    new_migrations = sorted(
        p
        for p in _MIGRATIONS_DIR.glob("*.sql")
        if _migration_number(p) > _BASELINE_MIGRATION_CUTOFF
    )
    for path in new_migrations:
        _run_psql_file(path)


@pytest.fixture(scope="session", autouse=True)
def migrated_test_database() -> None:
    """Rebuild indicagent_test from the pinned baseline + any post-baseline migrations."""
    if sys.platform not in ("linux", "darwin"):
        pytest.skip("schema rebuild fixture requires a local psql client")

    asyncio.run(_recreate_test_database())
    _apply_baseline()
    _replay_post_baseline_migrations()
