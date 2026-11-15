"""bulk_update_by_key: the keyed UPDATE writer with float32 clamping for real columns."""

from __future__ import annotations

import csv
import io
from typing import Any

from services.batch_support.write_session import (
    _active_write_session_hypertable,
    _known_compressed_hypertables,
)
from src.core.real_column_range import REAL_MAX_MAGNITUDE, REAL_MIN_MAGNITUDE, clamp_to_real_range

# Postgres `real` (IEEE 754 float4) range clamp -- promoted to src/core/real_column_range.py
# (2026-09-22, underflow-7symbol-real-column debug session) so a Ring 1 module
# (feature_vector_persistence.py) can share it too without importing services/ (Ring rule).
# Aliased here under the original private names so this module's existing callers/tests don't
# need to change; the implementation lives in exactly one place now.
_REAL_MIN_MAGNITUDE = REAL_MIN_MAGNITUDE
_REAL_MAX_MAGNITUDE = REAL_MAX_MAGNITUDE
_clamp_to_real_range = clamp_to_real_range


def bulk_update_by_key(
    conn: Any,
    *,
    table: str,
    temp_table: str,
    key_cols: list[str],
    set_cols: list[str],
    col_types: dict[str, str],
    rows: list[tuple],
) -> int:
    """Bulk UPDATE `table` keyed on `key_cols` via COPY into a temp table + one JOIN-UPDATE.

    Returns the JOIN-UPDATE's rowcount (rows of `table` actually updated), so a caller can
    report what changed without a follow-up count query.

    Replaces per-row execute_batch UPDATE (one index probe per row) with a single
    set-based UPDATE (one merge/hash join for the whole batch). For 50k+ row updates
    this turns thousands of round-trip index lookups into one join — the difference
    between CPU-bound serial row updates and a bulk operation.

    rows: each tuple ordered as (*set_cols, *key_cols) — matches the parameter order
    psycopg executemany() callers already use for `SET ... WHERE key = %s` statements.
    conn: caller commits; this function does not call conn.commit().

    Raises RuntimeError if `table` is a known compressed hypertable
    (`_known_compressed_hypertables`, below) and no `compressed_hypertable_write_session` is
    currently active for it -- turns "caller forgot to wrap this write in a session" from a
    silent ~1000x-slower forced full-chunk scan (the 2026-08-14 incident: a full night's
    regime_writer.py run converged its HMM compute cleanly and wrote zero rows) into an
    immediate, loud failure at the first UPDATE attempt instead of a multi-hour hang only
    an EXPLAIN would have revealed.

    col_types: also the single source of truth for which columns get float-range-clamped
    (todo 312, 2026-08-14) -- any column declared "real" here has _clamp_to_real_range()
    applied to its value before it reaches the COPY buffer, protecting every current and
    future caller from Postgres's underflow/overflow rejection uniformly, in the shared
    write primitive, rather than requiring each caller to remember its own clamp. This
    makes col_types load-bearing for correctness, not just the temp table's DDL -- keep it
    in sync with the target table's actual column types (a caller that still declares
    "double precision" for a column migrated to "real" gets neither Postgres's DDL-level
    type check nor this clamp).
    """
    if (
        table in _known_compressed_hypertables(conn)
        and _active_write_session_hypertable.get() != table
    ):
        raise RuntimeError(
            f"bulk_update_by_key: {table!r} is a compressed hypertable -- wrap this call in "
            f"compressed_hypertable_write_session(conn, {table!r}) (or the async sibling) "
            "first. See that function's docstring for why a bare UPDATE against a compressed "
            "chunk is ~1000x more expensive than it looks (2026-08-14 incident)."
        )
    all_cols = set_cols + key_cols
    col_defs = ", ".join(f"{c} {col_types[c]}" for c in all_cols)
    real_positions = frozenset(i for i, c in enumerate(all_cols) if col_types[c] == "real")

    with conn.cursor() as cur:
        cur.execute(f"CREATE TEMP TABLE IF NOT EXISTS {temp_table} ({col_defs})")
        cur.execute(f"TRUNCATE {temp_table}")

        buf = io.StringIO()
        writer = csv.writer(buf)
        for row in rows:
            if real_positions:
                row = tuple(
                    _clamp_to_real_range(v) if i in real_positions else v for i, v in enumerate(row)
                )
            writer.writerow("" if v is None else v for v in row)
        buf.seek(0)
        with cur.copy(
            f"COPY {temp_table} ({', '.join(all_cols)}) FROM STDIN WITH (FORMAT CSV)"
        ) as copy:
            copy.write(buf.getvalue())

        set_clause = ", ".join(f"{c} = v.{c}" for c in set_cols)
        key_clause = " AND ".join(f"t.{c} = v.{c}" for c in key_cols)
        cur.execute(
            f"UPDATE {table} AS t SET {set_clause} FROM {temp_table} AS v WHERE {key_clause}"
        )
        return int(cur.rowcount)
