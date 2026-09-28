"""Two-pass feature-matrix fetch from feature_vectors, without the wide DataFrame
(plan 186-04).

Promoted from scripts/analysis/_nonlinear_interaction_combiner_shared.py's
`fetch_training_matrix` (the fetch pattern only -- none of the combiner's LightGBM,
ensemble or stratum_fit code comes along) so the pattern survives 186-16's deletion of
scripts/analysis/. Expected consumers: todo 445's incremental-IC script (186-07) and the
fresh IC jobs -- this module notes them without importing them.

Load-bearing properties kept from the original (see CLAUDE.md's wide-frame and
asyncpg-dtype rules):

- Feature columns come from the PREPARED statement's `get_attributes()` -- the schema,
  never a dtype inferred from fetched data (an all-NULL early chunk silently mistypes a
  column inferred from data; Phase 164/165).
- `X` is allocated once at exactly its final size and filled in place; the wide frame is
  never materialized (each full-frame pandas op on 200+ columns x millions of rows costs
  another full-width copy; five OOMs at five different lines, todo 234).
- Two cursor passes stream the same total order `ORDER BY fv.bar_ts ASC, fv.symbol ASC`
  (a total order because feature_vectors' PK is (symbol, tf, bar_ts) and tf is fixed by
  the filter). Pass 2 asserts every row's symbol and bar_ts against pass 1 row for row
  and the row counts must agree -- a future query change that broke the ordering fails
  loudly instead of silently training on a row-shuffled matrix.
- Batch scatter via a destination row index (-1 for dropped rows), and the
  `.astype(feature_dtype)` cast that maps an all-None object column to NaN rather than
  erroring (NaN is what a missing feature is).

Three deliberate changes from the original, each with its reason:

1. No target join. The queries read only `feature_vectors fv`; the caller supplies
   `keep(symbol_object_array, bar_ts_int64_epoch_ns) -> boolean survivor mask` computed
   from ITS target. A caller builds its target with the `panel.forward_returns` kernel
   (`src/intelligence/research/panel.py`, read-only use) and passes "target is finite" as
   the mask. Reason: the `forward_returns` table is dropped in 186-23 and new code never
   reads it (CLAUDE.md executable-returns rule, UD-25). The combiner's causal per-symbol
   demeaning was target math, not fetch math, and moves out with the target.

2. Explicit universe and span. `symbols`, `start` (inclusive) and `end` (exclusive) are
   required so every caller states its span -- an in-sample caller passes
   `alpha.validation.oos_start` as `end`, so lookahead cannot enter by omission. The
   original's `is_active AND asset_class = 'equity'` universe filter is replaced by the
   caller's symbol list (universe membership is point-in-time data the caller owns).

3. The caller owns the connection (no DSN, no connect/close inside), so one session can
   be reused across symbol chunks. `work_mem` is applied with a session-scoped SET and
   skipped when None -- never any server-level configuration statement.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime

import asyncpg
import numpy as np
import pandas as pd

# Identifier, text-regime and canary_* columns from the original EXCLUDE_COLS, without
# `hmm_duration` -- that was a combiner-specific choice (documented there); a caller that
# wants it out passes it in `extra_exclude_cols`. float4/float8 columns are otherwise
# candidates; text/int columns are rejected by the type filter regardless.
NON_FEATURE_COLS = frozenset(
    {
        "symbol",
        "tf",
        "bar_ts",
        "feature_vector_id",
        "feature_factory_version",
        "bar_close_ts",
        "regime",
        "regime_rolling",
        "canary_acausal_placebo",
        "canary_constant",
        "canary_near_constant",
        "canary_noise_gaussian",
        "canary_noise_uniform",
    }
)

# Same WHERE clause for the schema probe and both passes, so the column list, the key
# stream and the feature stream all describe the identical row set. Parameter order:
# $1 tf, $2 symbols, $3 start (inclusive), $4 end (exclusive).
_FROM_WHERE = """
    FROM feature_vectors fv
    WHERE fv.tf = $1
      AND fv.symbol = ANY($2)
      AND fv.bar_ts >= $3
      AND fv.bar_ts < $4
    ORDER BY fv.bar_ts ASC, fv.symbol ASC
"""

# Prepared only (never executed): exists to read the column schema via get_attributes().
_SCHEMA_SQL = "SELECT fv.*" + _FROM_WHERE
_KEY_SQL = "SELECT fv.symbol, fv.bar_ts" + _FROM_WHERE

# work_mem must be a bare size literal (e.g. "128MB"); it cannot be a bound parameter in
# a SET, so anything else is refused rather than interpolated.
_WORK_MEM_PATTERN = re.compile(r"^[A-Za-z0-9]+$")


@dataclass
class FeatureMatrix:
    """What a caller needs out of feature_vectors, and nothing else."""

    X: np.ndarray  # [n_kept, n_features] feature_dtype, bar_ts-major
    meta: pd.DataFrame  # [n_kept] symbol + bar_ts, row-aligned with X
    feature_cols: list[str]
    n_raw: int  # rows in the (tf, symbols, span) window before the keep mask
    n_symbols: int
    n_bar_ts: int


def _epoch_ns(values) -> np.ndarray:
    """Exact int64 epoch-ns for a sequence of datetimes. Unit-explicit on purpose:
    pandas 3's default datetime resolution is microseconds and `DatetimeIndex.asi8`
    returns the index's own unit, so the original's bare `.asi8` is NOT epoch-ns there --
    `keep` and the pass-2 assertion would silently see a different unit than the
    epoch-ns contract promises (and meta reconstruction would land in 1970)."""
    return pd.DatetimeIndex(list(values)).to_numpy(dtype="datetime64[ns]").astype(np.int64)


def select_feature_columns(
    attrs: list[tuple[str, str]],
    extra_exclude_cols: frozenset[str] = frozenset(),
    force_include_cols: frozenset[str] = frozenset(),
) -> list[str]:
    """Filter a prepared statement's (name, pg_type_name) column attributes down to the
    feature columns: float4/float8, not in NON_FEATURE_COLS or the caller's
    `extra_exclude_cols`, with `force_include_cols` winning over both (same precedence as
    the original `_select_feature_columns`: applied last so a caller explicitly asking a
    column back in is never silently overridden by an exclusion list).

    Pure function (schema attributes in, column names out) -- unit-testable without a
    live DB connection.
    """
    exclude = (NON_FEATURE_COLS | extra_exclude_cols) - force_include_cols
    return [
        name
        for name, type_name in attrs
        if type_name in ("float4", "float8") and name not in exclude
    ]


async def fetch_feature_matrix(
    conn: asyncpg.Connection,
    tf: str,
    symbols: Sequence[str],
    *,
    start: datetime,
    end: datetime,
    keep: Callable[[np.ndarray, np.ndarray], np.ndarray] | None = None,
    feature_dtype: type = np.float32,
    extra_exclude_cols: frozenset[str] = frozenset(),
    force_include_cols: frozenset[str] = frozenset(),
    cursor_rows: int = 25_000,
    work_mem: str | None = "128MB",
) -> FeatureMatrix:
    """Build X/meta directly from asyncpg rows, never a wide DataFrame (see module
    docstring for the pattern's provenance and the three changes).

    `keep` receives pass 1's key arrays (symbol as an object array, bar_ts as int64
    epoch-ns) and returns the boolean survivor mask -- typically "target is finite" for a
    target computed with the `panel.forward_returns` kernel. With `keep=None` every row
    in the window survives. `end` is exclusive; `end <= start` is refused.
    """
    if end <= start:
        raise ValueError(f"end must be strictly after start, got start={start!r} end={end!r}")

    if work_mem is not None:
        if not _WORK_MEM_PATTERN.fullmatch(work_mem):
            raise ValueError(f"work_mem must be a bare size literal, got {work_mem!r}")
        # Session-scoped only (a SET, which reverts when the caller's
        # connection closes) -- never touches the live default any other backend sees. At
        # the original's 5m scale the 8MB default forced Postgres into a heavily
        # disk-spilled external sort for ORDER BY (bar_ts, symbol) over ~24.6M rows
        # (confirmed via pg_stat_activity's wait_event=BuffileRead, not guessed); 128MB
        # keeps the worst case bounded while the fetch's own X allocation holds the
        # bulk of the host's free memory.
        await conn.execute(f"SET work_mem = '{work_mem}'")

    schema = await conn.prepare(_SCHEMA_SQL)
    feature_cols = select_feature_columns(
        [(attr.name, attr.type.name) for attr in schema.get_attributes()],
        extra_exclude_cols=extra_exclude_cols,
        force_include_cols=force_include_cols,
    )

    # ---- Pass 1: keys.
    sym_parts: list[np.ndarray] = []
    ts_parts: list[np.ndarray]

    def _flush_keys(records: list) -> None:
        sym_parts.append(np.array([r[0] for r in records], dtype=object))
        # int64 epoch-ns (see _epoch_ns), not datetime objects: 8 bytes/row instead of
        # ~48 for a boxed tz-aware datetime, which matters at millions of rows.
        ts_parts.append(_epoch_ns([r[1] for r in records]))

    ts_parts = []
    buffer: list = []
    async with conn.transaction():
        async for record in conn.cursor(
            _KEY_SQL, tf, list(symbols), start, end, prefetch=cursor_rows
        ):
            buffer.append(record)
            if len(buffer) >= cursor_rows:
                _flush_keys(buffer)
                buffer = []
        if buffer:
            _flush_keys(buffer)

    symbol_raw = np.concatenate(sym_parts) if sym_parts else np.array([], dtype=object)
    bar_ts_raw = np.concatenate(ts_parts) if ts_parts else np.array([], dtype=np.int64)
    sym_parts.clear()
    ts_parts.clear()
    n_raw = len(symbol_raw)

    # ---- Survivor mask (caller's target logic) and the destination index.
    if keep is None:
        sel = np.ones(n_raw, dtype=bool)
    else:
        sel = keep(symbol_raw, bar_ts_raw)
        sel = np.asarray(sel)
        if sel.dtype != bool or sel.shape != (n_raw,):
            raise ValueError(
                f"keep must return a boolean mask of shape ({n_raw},), "
                f"got dtype={sel.dtype} shape={sel.shape}"
            )
    n_kept = int(sel.sum())
    dest = np.full(n_raw, -1, dtype=np.int64)
    dest[sel] = np.arange(n_kept, dtype=np.int64)

    meta = pd.DataFrame(
        {
            "symbol": symbol_raw[sel],
            "bar_ts": pd.DatetimeIndex(bar_ts_raw[sel].astype("datetime64[ns]")).tz_localize("UTC"),
        }
    )

    # ---- Pass 2: fill X in place.
    X = np.empty((n_kept, len(feature_cols)), dtype=feature_dtype)
    block_cols = ["symbol", "bar_ts", *feature_cols]
    feature_sql = (
        "SELECT fv.symbol, fv.bar_ts, " + ", ".join(f'fv."{c}"' for c in feature_cols) + _FROM_WHERE
    )

    def _scatter(records: list, row: int) -> int:
        end_row = row + len(records)
        block = pd.DataFrame(records, columns=block_cols)
        if not np.array_equal(block["symbol"].to_numpy(), symbol_raw[row:end_row]):
            raise RuntimeError(
                f"row order diverged between fetch passes at rows {row}:{end_row} (symbol)"
            )
        if not np.array_equal(
            block["bar_ts"].to_numpy(dtype="datetime64[ns]").astype(np.int64),
            bar_ts_raw[row:end_row],
        ):
            raise RuntimeError(
                f"row order diverged between fetch passes at rows {row}:{end_row} (bar_ts)"
            )
        targets = dest[row:end_row]
        keep_rows = targets >= 0
        if keep_rows.any():
            # `.astype` rather than `to_numpy(dtype=...)`: a feature that is all-NULL
            # across this batch arrives as an object column of Nones, which numpy cannot
            # cast but pandas maps to NaN -- and NaN is what a missing feature is.
            cast = block[feature_cols].astype(feature_dtype).to_numpy()[keep_rows]
            X[targets[keep_rows]] = cast
        return end_row

    row = 0
    buffer = []
    async with conn.transaction():
        async for record in conn.cursor(
            feature_sql, tf, list(symbols), start, end, prefetch=cursor_rows
        ):
            buffer.append(record)
            if len(buffer) >= cursor_rows:
                row = _scatter(buffer, row)
                buffer = []
        if buffer:
            row = _scatter(buffer, row)
    if row != n_raw:
        raise RuntimeError(f"fetch passes disagree on row count: {n_raw} then {row}")

    return FeatureMatrix(
        X=X,
        meta=meta,
        feature_cols=feature_cols,
        n_raw=n_raw,
        n_symbols=len(pd.unique(symbol_raw)),
        n_bar_ts=len(np.unique(bar_ts_raw)),
    )
