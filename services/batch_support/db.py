"""Connection and APR-loading helpers for the batch oneshot services."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any

import psycopg
import structlog

from src.config.config_service import ConfigService

_logger = structlog.get_logger()


_NULL_MARKER = r"\N"

_CONFIG_QUERY = (
    "SELECT cs.config_key, cs.config_value, csc.value_type "
    "FROM config_state cs "
    "JOIN config_schema csc USING (config_key)"
)


def connect_db_from_url(db_url: str) -> Any:
    """Open a psycopg connection from a raw DB URL, autocommit off.

    Shared by ic_engine.py and ensemble_ic_engine.py's ProcessPoolExecutor workers
    (each opens its own read-only connection per dispatch) and by ic_engine's
    higher-level _connect_db(settings) wrapper (todo 047 follow-up, 2026-07-02).
    """
    conn = psycopg.connect(db_url)
    conn.autocommit = False
    return conn


@contextmanager
def short_lived_conn(dsn: str):
    """Worker-side sibling of ic_engine.py's Settings-based `_short_lived_conn` (todo 129).

    Takes a dsn string (picklable, crosses a ProcessPoolExecutor boundary) instead of a
    `Settings` object -- `_short_lived_conn` is main-process only since a `Settings`
    object doesn't cross that boundary. Guarantees `conn.close()` exactly once, even
    when the caller's body raises mid-fetch: the 3 hand-rolled dsn `open -> use ->
    close` sites this replaces (`_compute_symbol_tf` x2, `_compute_cross_sectional_tf`
    x1 in services/ic_engine.py) had no try/finally, so any exception between open and
    the nearest explicit `conn.close()` call leaked a connection.
    """
    conn = connect_db_from_url(dsn)
    try:
        yield conn
    finally:
        conn.close()


def load_config_service_sync(conn: Any) -> ConfigService:
    """Load all APR keys from config_state into a cache-only ConfigService.

    conn: open psycopg connection. No DB reference is stored in the returned
    ConfigService — only the in-memory cache is populated.
    """
    cfg = ConfigService(database_url="")
    with conn.cursor() as cur:
        cur.execute(_CONFIG_QUERY)
        rows = cur.fetchall()
    for config_key, config_value, value_type in rows:
        cfg._cache[config_key] = cfg._parse_value(config_value, value_type)
    _logger.info("config_service_loaded", key_count=len(cfg._cache))
    return cfg


_BULK_LOAD_COLUMNS_SQL = (
    "SELECT column_name, data_type FROM information_schema.columns "
    "WHERE table_schema = current_schema() AND table_name = %s"
)


def table_column_types(conn: Any, table: str) -> dict[str, str]:
    """{column_name: data_type} of `table` in the connection's current schema, from
    information_schema (dtype comes from the schema, never from row data). A table with no
    columns does not exist, and raises, so a schema identifier that will be composed into SQL
    is validated by the same read that types its columns. The one sync read of this catalog:
    bulk_load and the IC writer use it; `fetch_table_columns` is its asyncpg twin over the
    public schema."""
    with conn.cursor() as cur:
        cur.execute(_BULK_LOAD_COLUMNS_SQL, (table,))
        types: dict[str, str] = dict(cur.fetchall())
    if not types:
        raise ValueError(f"table {table} does not exist in the current schema")
    return types


# ---------------------------------------------------------------------------
# Async APR loading (asyncpg-based batch services)
# ---------------------------------------------------------------------------
#
# Consolidates a pattern previously copy-pasted verbatim across ensemble_trainer.py,
# alpha_publisher.py, and ensemble_ic_engine.py: load alpha.* (+ each service's own
# infra.<name>.* keys) into a raw dict, then cast with a small type-inferring helper
# (todo 048, 2026-07-02).


# table_schema filter is mandatory: omitting it returns same-named tables from other schemas
# (e.g. timescaledb_internal), producing false "column exists" verdicts.
_TABLE_COLUMNS_SQL = (
    "SELECT column_name, data_type FROM information_schema.columns"
    " WHERE table_schema = 'public' AND table_name = $1"
)


async def fetch_table_columns(conn: Any, table: str) -> dict[str, str]:
    """{column_name: data_type} of a public-schema table, from information_schema.

    `conn` is anything with an asyncpg-style `fetch(sql, *args)` (a connection, a pool or the
    DatabaseManager). dtype comes from the schema, never from inferred row data."""
    rows = await conn.fetch(_TABLE_COLUMNS_SQL, table)
    return {row["column_name"]: row["data_type"] for row in rows}


async def load_apr_dict_async(conn: Any, extra_like_patterns: list[str] | None = None) -> Any:
    """Load alpha.* (+ optional extra LIKE patterns, e.g. a service's own infra.<name>.*)
    APR keys via asyncpg into a raw {config_key: config_value} dict.

    conn: open asyncpg connection or pool-acquired connection.
    extra_like_patterns: additional SQL LIKE patterns (e.g. "infra.ic_measure.%"),
        OR'd in alongside the default "alpha.%". Bound as a single array parameter via
        LIKE ANY($1::text[]) -- the codebase's established idiom for a dynamic-length
        pattern list (see bar_auditor.py, signal_probe_auditor.py), not a
        hand-rolled OR-chain of positional placeholders.

    Returns a plain dict, not a ConfigService -- callers cast values with cfg().
    """
    patterns = ["alpha.%", *(extra_like_patterns or [])]
    rows = await conn.fetch(
        "SELECT config_key, config_value FROM config_state WHERE config_key LIKE ANY($1::text[])",
        patterns,
    )
    return {r["config_key"]: r["config_value"] for r in rows}
