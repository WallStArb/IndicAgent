"""Shared utilities for batch oneshot services (psycopg2-based, plus a small asyncpg
APR-loading helper for the async batch services)."""

from __future__ import annotations

import csv
import io
import json
from contextlib import contextmanager
from typing import Any

import numpy as np
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
    """Cast a raw config_value to default's type, or return default if unset.

    bool is special-cased: config_value is always TEXT (e.g. "false"), and
    `bool("false")` is True in Python since any non-empty string is truthy --
    `type(default)(val)` would silently invert every falsy bool APR flag. Parsed
    via the same `str(val).lower() == "true"` idiom ic_engine.py's ConfigService
    path already uses for `alpha.regime.equity_model_enabled`.

    list/dict defaults are also special-cased (todo 187): `type(default)(val)` against
    a raw JSON-array/object string is a documented-broken cast (e.g.
    `list("[1,3,5,10]")` splits into individual characters, not the parsed list) --
    already fixed for dict defaults via `get_dict_config` below, generalized here so
    `cfg()` itself is safe for any json-typed default instead of every list-typed
    caller needing its own local `json.loads` workaround.
    """
    val = cfg_dict.get(key)
    if val is None:
        return default
    if isinstance(default, bool):
        return str(val).strip().lower() == "true"
    if isinstance(default, (list, dict)):
        return json.loads(val) if isinstance(val, str) else val
    return type(default)(val)


LOOKAHEAD_FALLBACKS_BY_TF: dict[str, dict[str, int]] = {
    "5m": {"fast": 1, "mid": 6, "slow": 12, "extended": 39},
    "15m": {"fast": 1, "mid": 2, "slow": 5, "extended": 10},
    "1h": {"fast": 1, "mid": 2, "slow": 20, "extended": 60},
    "1d": {"fast": 1, "mid": 2, "slow": 5, "extended": 10},
}
"""Todo 146's confirmed per-tf IC lookahead grid. 1h's slow/extended are UNCHANGED
from the old global default (20/60) -- 1h has no viable slow/extended tier at all
(session-bounded completeness collapses to 0%), but structurally removing that tier
requires touching ic_engine.py's fixed _SCALES-indexed compute loops (deferred to a
separate follow-up todo). Single source of truth for ICEngineConfig, EnsembleICConfig,
and forward_return_writer.py's from_apr()/loading logic -- do not re-literal this grid
in any of those files; import it from here."""


def lookaheads_for_tf(
    lookahead_fast: dict[str, int],
    lookahead_mid: dict[str, int],
    lookahead_slow: dict[str, int],
    lookahead_extended: dict[str, int],
    tf: str,
) -> dict[str, int]:
    """Shared resolver behind ICEngineConfig.lookaheads_for/EnsembleICConfig.lookaheads_for
    (todo 146). Both classes stay independent frozen+picklable dataclasses (separate
    ProcessPoolExecutor pools) -- only the per-tf lookup logic itself is shared."""
    return {
        "fast": lookahead_fast[tf],
        "mid": lookahead_mid[tf],
        "slow": lookahead_slow[tf],
        "extended": lookahead_extended[tf],
    }


def get_dict_config(cfg_service: ConfigService, key: str, default: dict) -> dict:
    """Read a JSON-object APR key via `ConfigService.get_sync()`, tolerating either a
    pre-parsed dict (the normal case -- `load_config_service_sync`'s `_parse_value`
    already `json.loads()`s `value_type='json'` keys at cache-load time) or a raw JSON
    string (test/fallback default path). `cfg()` above can't be reused here: its
    `type(default)(val)` cast breaks for a dict default against a raw JSON-string value.
    """
    v = cfg_service.get_sync(key, default)
    if isinstance(v, dict):
        return v
    if isinstance(v, str):
        return json.loads(v)
    return default


_CANONICAL_SCALE_ORDER: tuple[str, ...] = ("fast", "mid", "slow", "extended")


def canonicalize_active_scales(scales: list[str] | tuple[str, ...]) -> tuple[str, ...]:
    """Normalize a configured active-scale list to _CANONICAL_SCALE_ORDER, deduped.

    The APR value's configured order is never semantically meaningful -- an
    operator editing alpha.ic.active_scales.{tf} via /config/parameters could
    write ["mid","fast"] or ["fast","mid"] and mean the identical active set.
    Canonicalizing here (rather than sorting inside _compute_apr_snapshot_key)
    keeps the fingerprint hash deterministic without special-casing tuple-valued
    dict entries in a function shared by every other COMPUTATIONAL config field.

    Raises ValueError on any name outside _CANONICAL_SCALE_ORDER -- a typo'd scale
    name must fail loud, not silently shrink the active set (CLAUDE.md: silent
    wrong answers are worse than loud crashes).
    """
    scale_set = set(scales)
    unknown = scale_set - set(_CANONICAL_SCALE_ORDER)
    if unknown:
        raise ValueError(
            f"canonicalize_active_scales: unknown scale name(s) {sorted(unknown)} -- "
            f"must be a subset of {_CANONICAL_SCALE_ORDER}."
        )
    return tuple(s for s in _CANONICAL_SCALE_ORDER if s in scale_set)


ACTIVE_SCALES_FALLBACKS_BY_TF: dict[str, tuple[str, ...]] = {
    "5m": _CANONICAL_SCALE_ORDER,
    "15m": _CANONICAL_SCALE_ORDER,
    "1h": ("fast", "mid"),
    "1d": _CANONICAL_SCALE_ORDER,
}
"""Per-tf active-scale set (2026-07-30 design, docs/superpowers/specs/2026-07-30-
per-tf-active-scale-set-design.md). 1h excludes slow/extended: live-measured
0.000 completeness under the current same-ET-session completeness gate (see
LOOKAHEAD_FALLBACKS_BY_TF's docstring above and todo 208). This reflects today's
measured data, not a permanent commitment -- reversible via a single config
change (alpha.ic.active_scales.1h) alone, no code change, if todo 208's
investigation into removing the session gate changes what's measurable. Single
source of truth for ICEngineConfig/EnsembleICConfig's from_apr() -- do not
re-literal this table in either file; import it from here."""


def get_list_config(cfg_service: ConfigService, key: str, default: list) -> list:
    """Read a JSON-array APR key via ConfigService.get_sync(), tolerating either a
    pre-parsed list (the normal case -- load_config_service_sync's _parse_value
    already json.loads()s value_type='json' keys at cache-load time) or a raw JSON
    string (test/fallback default path). Sibling of get_dict_config above -- same
    isinstance-guard shape, list instead of dict."""
    v = cfg_service.get_sync(key, default)
    if isinstance(v, list):
        return v
    if isinstance(v, str):
        return json.loads(v)
    return default


class Float32ChunkAccumulator:
    """Buffers rows into vstack-ready float32 chunks, freeing each chunk's Python-list
    intermediate as soon as it's converted (todo 087).

    Shared 'accumulate rows -> np.array chunk -> vstack once at the end, discarding
    intermediates' idiom behind ic_engine.py's per-symbol OOM fix (`_compute_symbol_tf`,
    a named server-side cursor streaming rows one at a time) and its cross-sectional
    OOM fix (`_compute_cross_sectional_tf`, a plain cursor re-executed per explicit
    timestamp chunk, fetching a whole batch per query). The query/cursor/pagination
    mechanics genuinely differ between those two callers and are left entirely to
    them; this owns only the buffer-to-float32-array bookkeeping both duplicated.

    Two append modes, matching the two callers' shapes:
    - append_row(): one row at a time, auto-flushed into a chunk every `flush_at` rows
      (the streaming-cursor shape).
    - append_chunk(): one pre-fetched batch at a time, converted to a chunk immediately
      (the re-executed-per-query-chunk shape). Ignores an empty batch.
    """

    def __init__(self, flush_at: int | None = None) -> None:
        self._flush_at = flush_at
        self._chunks: list[np.ndarray] = []
        self._buf: list = []

    def append_row(self, row: Any) -> None:
        self._buf.append(row)
        if self._flush_at is not None and len(self._buf) >= self._flush_at:
            self._flush_buf()

    def append_chunk(self, rows: Any) -> None:
        if len(rows):
            self._chunks.append(np.array(rows, dtype=np.float32))

    def _flush_buf(self) -> None:
        if self._buf:
            self._chunks.append(np.array(self._buf, dtype=np.float32))
            self._buf = []

    def finalize(self) -> np.ndarray | None:
        """vstack every chunk and free them; None if nothing was ever appended."""
        self._flush_buf()
        if not self._chunks:
            return None
        result = np.vstack(self._chunks)
        self._chunks = []
        return result
