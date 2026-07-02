"""Shared utilities for batch oneshot services (psycopg2-based, plus a small asyncpg
APR-loading helper for the async batch services)."""

from __future__ import annotations

import csv
import io
from typing import Any

import psycopg2
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
    """Open a psycopg2 connection from a raw DB URL, autocommit off.

    Shared by ic_engine.py and ensemble_ic_engine.py's ProcessPoolExecutor workers
    (each opens its own read-only connection per dispatch) and by ic_engine's
    higher-level _connect_db(settings) wrapper (todo 047 follow-up, 2026-07-02).
    """
    conn = psycopg2.connect(db_url)
    conn.autocommit = False
    return conn


def load_config_service_sync(conn: Any) -> ConfigService:
    """Load all APR keys from config_state into a cache-only ConfigService.

    conn: open psycopg2 connection. No DB reference is stored in the returned
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


def bulk_update_by_key(
    conn: Any,
    *,
    table: str,
    temp_table: str,
    key_cols: list[str],
    set_cols: list[str],
    col_types: dict[str, str],
    rows: list[tuple],
) -> None:
    """Bulk UPDATE `table` keyed on `key_cols` via COPY into a temp table + one JOIN-UPDATE.

    Replaces per-row execute_batch UPDATE (one index probe per row) with a single
    set-based UPDATE (one merge/hash join for the whole batch). For 50k+ row updates
    this turns thousands of round-trip index lookups into one join — the difference
    between CPU-bound serial row updates and a bulk operation.

    rows: each tuple ordered as (*set_cols, *key_cols) — matches the parameter order
    psycopg2 execute_batch callers already use for `SET ... WHERE key = %s` statements.
    conn: caller commits; this function does not call conn.commit().
    """
    all_cols = set_cols + key_cols
    col_defs = ", ".join(f"{c} {col_types[c]}" for c in all_cols)
    with conn.cursor() as cur:
        cur.execute(f"CREATE TEMP TABLE IF NOT EXISTS {temp_table} ({col_defs})")
        cur.execute(f"TRUNCATE {temp_table}")

        buf = io.StringIO()
        writer = csv.writer(buf)
        for row in rows:
            writer.writerow("" if v is None else v for v in row)
        buf.seek(0)
        cur.copy_expert(
            f"COPY {temp_table} ({', '.join(all_cols)}) FROM STDIN WITH (FORMAT CSV)",
            buf,
        )

        set_clause = ", ".join(f"{c} = v.{c}" for c in set_cols)
        key_clause = " AND ".join(f"t.{c} = v.{c}" for c in key_cols)
        cur.execute(
            f"UPDATE {table} AS t SET {set_clause} FROM {temp_table} AS v WHERE {key_clause}"
        )


# ---------------------------------------------------------------------------
# Async APR loading (asyncpg-based batch services)
# ---------------------------------------------------------------------------
#
# Consolidates a pattern previously copy-pasted verbatim across ensemble_trainer.py,
# alpha_publisher.py, and ensemble_ic_engine.py: load alpha.* (+ each service's own
# infra.<name>.* keys) into a raw dict, then cast with a small type-inferring helper
# (todo 048, 2026-07-02).


async def load_apr_dict_async(conn: Any, extra_like_patterns: list[str] | None = None) -> Any:
    """Load alpha.* (+ optional extra LIKE patterns, e.g. a service's own infra.<name>.*)
    APR keys via asyncpg into a raw {config_key: config_value} dict.

    conn: open asyncpg connection or pool-acquired connection.
    extra_like_patterns: additional SQL LIKE patterns (e.g. "infra.ensemble_ic_engine.%"),
        OR'd in alongside the default "alpha.%". Bound as a single array parameter via
        LIKE ANY($1::text[]) -- the codebase's established idiom for a dynamic-length
        pattern list (see ic_engine.py, bar_auditor.py, signal_probe_auditor.py), not a
        hand-rolled OR-chain of positional placeholders.

    Returns a plain dict, not a ConfigService -- callers cast values with cfg().
    """
    patterns = ["alpha.%", *(extra_like_patterns or [])]
    rows = await conn.fetch(
        "SELECT config_key, config_value FROM config_state WHERE config_key LIKE ANY($1::text[])",
        patterns,
    )
    return {r["config_key"]: r["config_value"] for r in rows}


def cfg(cfg_dict: dict[str, Any], key: str, default: Any) -> Any:
    """Cast a raw config_value to default's type, or return default if unset."""
    val = cfg_dict.get(key)
    return type(default)(val) if val is not None else default
