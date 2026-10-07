"""BarDerivation: the D2b derived 15m/1h grid writer (phase 185 plans 11 and 31, D-15)
and the D2 canonical 1d stage (phase 185 plan 17, D-06).

Grid stage. Oneshot batch. For each symbol it re-derives 15m and 1h bars from the symbol's
tradeable 5m bars on session-anchored edges (plan 06's aggregate_session_grid) and writes them by
the write contract (plan 185-31; data layer integrity design section 4,
src/intelligence/bars/write_contract.py). One transaction per symbol:

1. read the stored 15m/1h rows with their source, the grid's flags and the current digests;
   classify the derived rows against the stored derived rows by exact value (new, changed,
   unchanged, removed: a stored derived slot no longer derived);
2. refuse the symbol when (changed + removed) / stored derived rows exceeds
   threshold.bar_integrity.max_revision_ratio over at least revision_ratio_min_stored stored
   rows: its ohlcv_load rows commit with outcome refused, nothing else is written, and the batch
   fails (a broad 5m restatement is a finding to look at, never auto-applied);
3. under SET LOCAL ROLE bar_derivation_writer: one ohlcv_load row per grid timeframe (source
   derived, outcome applied, the four counts);
4. stored vendor rows (IBKR 15m/1h, any source but derived_5m) are archived into
   ohlcv_intraday_raw_archive; a vendor row whose archived observation under the same key is
   not equal (IBKR restated it inside its revision window; todo 490) goes to ohlcv_revision with
   origin archive_segment; the verify then requires every vendor row to have an equal archive or
   revision row before the vendor rows are deleted (raw observations are permanent);
5. old values of changed and removed derived rows go to ohlcv_revision (origin load); new rows
   are inserted, changed rows upserted (ON CONFLICT DO UPDATE on the changed set only, never a
   raw UPDATE of the compressed hypertable), stale rows deleted by key;
6. constituent_flag and partial_constituents flags are written or deleted only where they differ
   from the stored ones (a later answered 5m window clears a stale partial flag, todo 462), and a
   bar_content_digest row lands only for a (timeframe, month) whose digest differs from
   bar_content_digest_current (5m, 15m and 1h, rule version beside it; D-07).

A second run over unchanged 5m therefore writes no bar, flag or digest, only its load rows.
Quarantined 5m bars are excluded from aggregation (RESEARCH finding 11); a symbol with no
tradeable 5m bars is skipped with outcome no_5m and its stored rows stay as they are.
--changed-only skips symbols whose 5m month digests all equal bar_content_digest_current and no
answered 5m window arrived since. Default is a dry run: the same reads and classification, zero
writes, no batch row; --apply is the explicit opt-in.

Daily stage (plan 17). Per symbol: load the D1 TRADES observations and the
corporate_action_current splits, run the pure derive_daily rule (Ring 1), and
upsert into market_data_ohlcv only the rows that differ from or are missing in
the stored IBKR-source 1d rows (185-01 measurement b, native upsert).
Lineage for EVERY canonical bar goes to canonical_bar_lineage (side table,
design 12.1), pre_split_unrefetched / no_provider_volume flags go through
bar_scrub's write_flags, the D2a rules are rerun through
bar_scrub.scrub_symbols (one call for the run's symbols so cross-symbol
corroboration spans them), and after that scrub (plan 185-27) a
bar_content_digest row lands for each 1d month whose digest differs from
bar_content_digest_current (first run: every month). Default is a dry run:
same computation, zero writes, no batch row, and a report by reason.
"""

from __future__ import annotations

import argparse
import asyncio
import calendar
import json
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, NamedTuple
from uuid import uuid4

import asyncpg
import numpy as np

from services._batch_utils import cfg as _cfg
from services._batch_utils import load_apr_dict_async
from services.bar_derivation_batch import close_batch, open_batch
from services.bar_scrub import FlagRow, scrub_symbols, write_flags
from services.intraday_raw_archive import ARCHIVE_FROM_TABLE_SQL
from src.config.settings import Settings
from src.core.agent.base_batch import BaseBatch
from src.intelligence.bars.derivation import (
    RULE_VERSION,
    CanonicalBar,
    Observation,
    SplitRecord,
    derive_daily,
    split_staleness_threshold,
)
from src.intelligence.bars.digest import DIGEST_ALGORITHM, bar_content_digest, month_ranges
from src.intelligence.bars.gap_plan import (
    ANSWERED_OUTCOMES,
    COVERAGE_ROUTE,
    COVERAGE_WHAT_TO_SHOW,
    AnsweredWindows,
)
from src.intelligence.bars.session_grid import GridBars, aggregate_session_grid
from src.intelligence.bars.sessions import nyse_sessions
from src.intelligence.bars.sources import (
    CANONICAL_1D_SOURCES,
    GRID_RULE_VERSION,
    GRID_SOURCE_TF,
    GRID_TIMEFRAMES,
    SOURCE_DERIVED_5M,
)
from src.intelligence.bars.write_contract import (
    BarValues,
    WriteDelta,
    classify,
    revision_ratio,
    should_refuse,
)
from src.observability.metrics import counter
from src.observability.otel import OTelInitError, init_otel_providers

_JOB = "bar-derivation"
# Per-run outcomes, labeled {stage, outcome} only: never per symbol (cardinality);
# per-symbol detail (failures, outside-session drops) stays in the log.
_OUTCOME_TOTAL = counter(
    "bar_derivation_outcome_total",
    "bar_derivation per-run outcome counts: symbols derived, skipped unchanged by "
    "--changed-only, skipped with no tradeable 5m, skipped as an excluded lane, and "
    "failed. Never labeled by symbol.",
)
_WRITER_ROLE_SQL = "SET LOCAL ROLE bar_derivation_writer"
_CONSTITUENT_RULE = "constituent_flag"
# A derived bar whose constituent 5m slot is neither stored nor inside an
# answered SMART TRADES request window (todo 462): the hole stops at the
# derivation edge as a quarantine-false flag, never silently as a complete bar.
_PARTIAL_RULE = "partial_constituents"
_GRID_TF_LIST = sorted(GRID_TIMEFRAMES)
_GRID_FLAG_RULES = (_CONSTITUENT_RULE, _PARTIAL_RULE)
_WRITE_METHOD = "write_contract"
_DEFAULT_SYMBOL_BATCH = 10
# Fallbacks equal to migration 443's seeds; the run reads threshold.bar_integrity.* from APR.
_DEFAULT_MAX_REVISION_RATIO = 0.02
_DEFAULT_REVISION_MIN_STORED = 500
# The grid stage's ohlcv_load segment (tests/unit/test_ohlcv_load_revision_writer_boundary.py).
_GRID_LOAD_SOURCE = "derived"
_GRID_LOAD_CALLER = "bar_derivation-grid"
_GRID_LOAD_DESTINATION = "market_data_ohlcv"
_GRID_OUTCOMES = ("derived", "unchanged", "no_5m", "excluded_lane", "refused", "failed")
_GRID_ROW_COUNTS = (
    "rows_new",
    "rows_changed",
    "rows_unchanged",
    "rows_removed",
    "vendor_rows_removed",
    "archive_segment_rows",
)
_SESSION_MARGIN_DAYS = 3

_DISCOVER_SYMBOLS_SQL = """
SELECT DISTINCT symbol FROM market_data_ohlcv_tradeable WHERE timeframe = '5m' ORDER BY symbol
"""

_SELECT_5M_SQL = """
SELECT "timestamp", open, high, low, close, volume, base
FROM market_data_ohlcv_tradeable
WHERE symbol = $1 AND timeframe = '5m'
ORDER BY "timestamp"
"""

_SELECT_5M_FLAGS_SQL = """
SELECT "timestamp", rule, quarantine
FROM bar_quality_flag
WHERE symbol = $1 AND timeframe = '5m'
"""

_SELECT_CURRENT_DIGESTS_SQL = """
SELECT range_start, digest FROM bar_content_digest_current
WHERE symbol = $1 AND timeframe = '5m'
"""

# Answered SMART TRADES 5m windows (todo 462's coverage rule, plan 185-18: the
# outcome set, the covered route and the merge/cover semantics all come from the
# shared planner module, src/intelligence/bars/gap_plan.py). A `bars` answer
# counts only when a stored 5m row corroborates it: the request record and the
# bars still commit separately at 5m in this daemon's read path, so a lost
# chunk must not make a window look covered.
_SELECT_ANSWERED_WINDOWS_SQL = """
SELECT r.window_start, r.window_end
FROM ohlcv_request r
WHERE r.symbol = $1 AND r.timeframe = '5m' AND r.route = $3
  AND r.what_to_show = $4 AND r.outcome = ANY($2::text[])
  AND r.window_start IS NOT NULL
  AND (
    r.outcome = 'no_data'
    OR EXISTS (
      SELECT 1 FROM market_data_ohlcv m
      WHERE m.symbol = r.symbol AND m.timeframe = r.timeframe
        AND m.timestamp >= r.window_start AND m.timestamp < r.window_end
    )
  )
ORDER BY r.window_start
"""

# --changed-only must also re-derive when an answered 5m window arrived after
# the symbol's last derivation: the new answer can clear a stale
# partial_constituents flag even though no stored bar changed.
_SELECT_ANSWERED_SINCE_SQL = """
SELECT EXISTS (
    SELECT 1 FROM ohlcv_request r
    WHERE r.symbol = $1 AND r.timeframe = '5m' AND r.route = $3
      AND r.what_to_show = $4 AND r.outcome = ANY($2::text[])
      AND r.answered_at IS NOT NULL
      AND r.answered_at > COALESCE(
          (SELECT max(computed_at) FROM bar_content_digest WHERE symbol = $1),
          '-infinity'::timestamptz)
) AS answered_since
"""

# The archive's single owner module (services/intraday_raw_archive.py, plan 12) defines this
# INSERT ... SELECT of a symbol's stored vendor 15m/1h rows; the archive writer-boundary CI test
# fails on any other INSERT into it.
_INSERT_ARCHIVE_SQL = ARCHIVE_FROM_TABLE_SQL

# The stored 15m/1h rows of a symbol, vendor and derived, with their source: the write
# contract's "stored" side (read inside the symbol's transaction on --apply).
_SELECT_STORED_GRID_SQL = """
/* stored_grid */
SELECT timeframe, "timestamp", open, high, low, close, volume, source
FROM market_data_ohlcv
WHERE symbol = $1 AND timeframe = ANY($2::text[])
"""

_SELECT_STORED_GRID_FLAGS_SQL = """
/* stored_grid_flags */
SELECT timeframe, "timestamp", rule, rule_version, detail
FROM bar_quality_flag
WHERE symbol = $1 AND timeframe = ANY($2::text[]) AND rule = ANY($3::text[])
"""

_SELECT_CURRENT_GRID_DIGESTS_SQL = """
/* current_grid_digests */
SELECT timeframe, range_start, digest FROM bar_content_digest_current
WHERE symbol = $1 AND timeframe = ANY($2::text[])
"""

_INSERT_GRID_LOAD_SQL = """
INSERT INTO ohlcv_load (load_id, symbol, timeframe, source, requested_start, requested_end, outcome, n_bars, n_new, n_changed, n_unchanged, n_removed, first_bar, last_bar, detail, caller, batch_id, destination)
VALUES ($1::uuid, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, $17::uuid, $18)
"""

# A stored vendor row whose archived observation under the same key is not equal (IBKR restated
# the bar inside its revision window after the archive kept the first write; todo 490): its
# stored value is the second observation, kept here before the row leaves market_data_ohlcv.
# One statement per grid timeframe, under that timeframe's load row ($3).
_INSERT_ARCHIVE_SEGMENT_REVISION_SQL = """
INSERT INTO ohlcv_revision
    (load_id, symbol, timeframe, "timestamp", old_open, old_high, old_low, old_close,
     old_volume, old_source, origin)
SELECT $3::uuid, m.symbol, m.timeframe, m."timestamp", m.open, m.high, m.low, m.close,
       m.volume, m.source, 'archive_segment'
FROM market_data_ohlcv m
LEFT JOIN ohlcv_intraday_raw_archive a
    ON a.symbol = m.symbol AND a.timeframe = m.timeframe AND a."timestamp" = m."timestamp"
WHERE m.symbol = $1 AND m.timeframe = $2 AND m.source IS DISTINCT FROM 'derived_5m'
  AND (a."timestamp" IS NULL
       OR a.open <> m.open OR a.high <> m.high OR a.low <> m.low OR a.close <> m.close
       OR a.volume <> m.volume OR a.source IS DISTINCT FROM m.source)
"""

# Removal is verified by value, row by row: a stored vendor row may leave only when the archive
# holds an equal row under its key or this transaction's loads ($3) hold an equal
# archive_segment revision of it. n_unmatched must be 0 and n_removable must equal the vendor
# rows the classification read. IS NOT DISTINCT FROM keeps a NULL from passing as a match.
_VENDOR_REMOVAL_VERIFY_SQL = """
/* vendor_removal_verify */
SELECT count(*)::bigint AS n_removable,
       count(*) FILTER (WHERE NOT (
           (a."timestamp" IS NOT NULL
            AND a.open IS NOT DISTINCT FROM m.open AND a.high IS NOT DISTINCT FROM m.high
            AND a.low IS NOT DISTINCT FROM m.low AND a.close IS NOT DISTINCT FROM m.close
            AND a.volume IS NOT DISTINCT FROM m.volume AND a.source IS NOT DISTINCT FROM m.source)
           OR (r."timestamp" IS NOT NULL
            AND r.old_open IS NOT DISTINCT FROM m.open AND r.old_high IS NOT DISTINCT FROM m.high
            AND r.old_low IS NOT DISTINCT FROM m.low AND r.old_close IS NOT DISTINCT FROM m.close
            AND r.old_volume IS NOT DISTINCT FROM m.volume
            AND r.old_source IS NOT DISTINCT FROM m.source)
       ))::bigint AS n_unmatched
FROM market_data_ohlcv m
LEFT JOIN ohlcv_intraday_raw_archive a
    ON a.symbol = m.symbol AND a.timeframe = m.timeframe AND a."timestamp" = m."timestamp"
LEFT JOIN ohlcv_revision r
    ON r.load_id = ANY($3::uuid[]) AND r.origin = 'archive_segment'
   AND r.symbol = m.symbol AND r.timeframe = m.timeframe AND r."timestamp" = m."timestamp"
WHERE m.symbol = $1 AND m.timeframe = ANY($2::text[]) AND m.source IS DISTINCT FROM 'derived_5m'
"""

_DELETE_VENDOR_ROWS_SQL = """
/* delete_vendor_rows */
DELETE FROM market_data_ohlcv
WHERE symbol = $1 AND timeframe = ANY($2::text[]) AND source IS DISTINCT FROM 'derived_5m'
"""

_INSERT_DERIVED_SQL = """
INSERT INTO market_data_ohlcv
    ("timestamp", symbol, timeframe, open, high, low, close, volume, source, base)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
"""

# The changed set only, the daily stage's idiom: a raw UPDATE of the compressed hypertable is
# fenced (test_compressed_hypertable_write_boundary.py).
_UPSERT_DERIVED_SQL = """
INSERT INTO market_data_ohlcv
    ("timestamp", symbol, timeframe, open, high, low, close, volume, source, base)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
ON CONFLICT ("timestamp", symbol, timeframe) DO UPDATE SET
    open = EXCLUDED.open,
    high = EXCLUDED.high,
    low = EXCLUDED.low,
    close = EXCLUDED.close,
    volume = EXCLUDED.volume,
    source = EXCLUDED.source
"""

_INSERT_LOAD_REVISION_SQL = """
INSERT INTO ohlcv_revision
    (load_id, symbol, timeframe, "timestamp", old_open, old_high, old_low, old_close,
     old_volume, old_source, origin)
VALUES ($1::uuid, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
"""

# Stale derived rows by key; the literal range ahead of ANY() keeps chunk exclusion on the
# compressed hypertable (gotchas, todo 356).
_DELETE_STALE_DERIVED_SQL = """
/* delete_stale_derived */
DELETE FROM market_data_ohlcv
WHERE symbol = $1 AND timeframe = $2 AND source = 'derived_5m'
  AND "timestamp" BETWEEN $4 AND $5 AND "timestamp" = ANY($3::timestamptz[])
"""

_INSERT_FLAG_SQL = """
INSERT INTO bar_quality_flag
    (symbol, timeframe, "timestamp", rule, rule_version, fields, quarantine, detail, batch_id)
VALUES ($1, $2, $3, $4, $5, $6::text[], $7, $8::text::jsonb, $9::uuid)
ON CONFLICT (symbol, timeframe, "timestamp", rule) DO UPDATE SET
    rule_version = EXCLUDED.rule_version,
    fields = EXCLUDED.fields,
    detail = EXCLUDED.detail,
    batch_id = EXCLUDED.batch_id
"""

# A grid flag the derivation no longer produces (its bar is gone, its constituents lost their
# rules, or a later answered window covers the hole) is deleted by key.
_DELETE_GRID_FLAG_SQL = """
DELETE FROM bar_quality_flag
WHERE symbol = $1 AND timeframe = $2 AND "timestamp" = $3 AND rule = $4
"""

_INSERT_DIGEST_SQL = """
INSERT INTO bar_content_digest
    (symbol, timeframe, range_start, range_end, digest, algorithm, rule_version, n_rows, batch_id)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9::uuid)
"""

# --- D2 daily stage (plan 17) -------------------------------------------

_DEFAULT_DAILY_SYMBOL_BATCH = 25
_DAILY_WRITE_METHOD = "upsert"
_PRE_SPLIT_RULE = "pre_split_unrefetched"
_NO_VOLUME_RULE = "no_provider_volume"
# Informational flag fields each rule concerns; identifiers, not tunables.
_PRE_SPLIT_FIELDS = ("open", "high", "low", "close")

_DISCOVER_DAILY_SYMBOLS_SQL = """
SELECT symbol FROM instruments
WHERE is_active AND compute_eligible_1d
ORDER BY symbol
"""

# All TRADES observations of the symbol: SMART, venue routes and the legacy
# import (legacy flag derived from the route). ohlcv_observation carries its
# own route/what_to_show/fetched_at; observation rows exist only for requests
# that returned bars. The request join exists for one reason: D1 is append-only,
# so a fixture row a test appended on a real symbol and date can never be
# removed, and the latest observation wins a bar. Requests whose caller is a
# test ('test-' prefix) are provenance-excluded here and in the changed-since
# probe, so they can never become a canonical bar (2026-10-03: fixture rows on
# SPY 2024-01-02 to 01-04 would have replaced closes of 472 with 100.5).
_SELECT_DAILY_OBSERVATIONS_SQL = """
SELECT o.request_id::text AS request_id, o.route, o.bar_date,
       o.open, o.high, o.low, o.close, o.volume, o.fetched_at,
       o.what_to_show, (o.route = 'LEGACY_IMPORT') AS legacy
FROM ohlcv_observation o
JOIN ohlcv_request q ON q.request_id = o.request_id
WHERE o.symbol = $1 AND o.timeframe = '1d' AND o.what_to_show = 'TRADES'
  AND q.caller NOT LIKE 'test-%'
ORDER BY o.bar_date, o.fetched_at, o.request_id
"""

_SELECT_DAILY_SPLITS_SQL = """
SELECT effective_date, recorded_at, factor
FROM corporate_action_current
WHERE symbol = $1
ORDER BY effective_date
"""

# D2's value comparison: the stored IBKR-source 1d rows (a Tradier-owned name never
# reaches the comparison, so Tradier rows stay out of it).
_SELECT_STORED_1D_SQL = """
SELECT "timestamp", open, high, low, close, volume, base
FROM market_data_ohlcv
WHERE symbol = $1 AND timeframe = '1d'
  AND source IN ('ibkr_named', 'ibkr_venue')
ORDER BY "timestamp"
"""

# The 1d digest's content: stored rows of every canonical 1d source ($2 =
# CANONICAL_1D_SOURCES), so the digest covers a Tradier-owned name's bars too.
_SELECT_DIGEST_1D_SQL = """
SELECT "timestamp", open, high, low, close, volume
FROM market_data_ohlcv
WHERE symbol = $1 AND timeframe = '1d' AND source = ANY($2::text[])
ORDER BY "timestamp"
"""

_SELECT_BASE_SQL = """
SELECT base FROM market_data_ohlcv WHERE symbol = $1 AND base IS NOT NULL LIMIT 1
"""

_SELECT_CURRENT_1D_DIGESTS_SQL = """
SELECT range_start, digest FROM bar_content_digest_current
WHERE symbol = $1 AND timeframe = '1d'
"""

_SELECT_1D_FLAG_RULES_SQL = """
SELECT "timestamp", rule, quarantine
FROM bar_quality_flag
WHERE symbol = $1 AND timeframe = '1d'
"""

# --changed-only: a symbol is due when any TRADES request was answered after
# the last completed daily batch, or a corporate action was recorded after it.
_SELECT_DAILY_CHANGED_SINCE_SQL = """
/* changed_since */
SELECT EXISTS (
    SELECT 1 FROM ohlcv_observation o
    JOIN ohlcv_request q ON q.request_id = o.request_id
    WHERE o.symbol = $1 AND o.timeframe = '1d' AND o.what_to_show = 'TRADES'
      AND q.caller NOT LIKE 'test-%'
) AS has_obs,
EXISTS (
    SELECT 1 FROM ohlcv_request r
    WHERE r.symbol = $1 AND r.timeframe = '1d' AND r.what_to_show = 'TRADES'
      AND r.outcome IN ('bars', 'legacy_import')
      AND r.caller NOT LIKE 'test-%'
      AND r.answered_at > COALESCE(
          (SELECT max(finished_at) FROM bar_derivation_batch
           WHERE stage = 'daily' AND status = 'completed'),
          '-infinity'::timestamptz)
) AS obs_since,
EXISTS (
    SELECT 1 FROM corporate_action_current c
    WHERE c.symbol = $1
      AND c.recorded_at > COALESCE(
          (SELECT max(finished_at) FROM bar_derivation_batch
           WHERE stage = 'daily' AND status = 'completed'),
          '-infinity'::timestamptz)
) AS action_since,
-- A name some Tradier daily load was accepted for keeps that source for its whole history
-- (migration 438); D2 never overwrites it with IBKR observations. A later refused load
-- (gated, short_history, failed; plan 185-26) does not hand it back: its stored bars stay.
-- Same predicate as TRADIER_OWNED_SQL in infrastructure_run_tradier_daily.py (the nightly's
-- IBKR 1d skip). source = 'tradier' because ohlcv_load records every canonical writer since
-- migration 443 (plan 185-31): a grid or ingress load row never makes a name Tradier-owned.
-- The IBKR history fetcher imports this statement, so it inherits the predicate.
EXISTS (SELECT 1 FROM ohlcv_load l
        WHERE l.symbol = $1 AND l.source = 'tradier' AND l.outcome = 'loaded') AS tradier_owned
"""

# Native upsert, 185-01 measurement b.
_UPSERT_1D_SQL = """
INSERT INTO market_data_ohlcv
    ("timestamp", symbol, timeframe, open, high, low, close, volume, source, base)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
ON CONFLICT ("timestamp", symbol, timeframe) DO UPDATE SET
    open = EXCLUDED.open,
    high = EXCLUDED.high,
    low = EXCLUDED.low,
    close = EXCLUDED.close,
    volume = EXCLUDED.volume,
    source = EXCLUDED.source
"""

_UPSERT_LINEAGE_SQL = """
INSERT INTO canonical_bar_lineage
    (symbol, timeframe, "timestamp", rule_version, request_ids, batch_id)
VALUES ($1, '1d', $2, $3, $4::uuid[], $5::uuid)
ON CONFLICT (symbol, timeframe, "timestamp") DO UPDATE SET
    rule_version = EXCLUDED.rule_version,
    request_ids = EXCLUDED.request_ids,
    batch_id = EXCLUDED.batch_id,
    derived_at = now()
"""


class _SymbolFailure(Exception):
    """One symbol's derivation or write failed; the run continues and fails at the end."""


class _SymbolResult(NamedTuple):
    """One symbol's grid outcome and its write-contract counts (summed into the batch detail)."""

    outcome: str
    error: str | None
    n_derived: int
    rows_new: int = 0
    rows_changed: int = 0
    rows_unchanged: int = 0
    rows_removed: int = 0
    vendor_rows_removed: int = 0
    archive_segment_rows: int = 0


class _RevisionLimits(NamedTuple):
    """threshold.bar_integrity.max_revision_ratio and revision_ratio_min_stored, read per run."""

    max_ratio: float
    min_stored: int


@dataclass(frozen=True)
class _GridPlan:
    """The write contract applied to one symbol's grid: what the transaction will write."""

    deltas: dict[str, WriteDelta[int]]
    n_stored_derived: dict[str, int]
    n_vendor: dict[str, int]
    refusals: tuple[str, ...]
    flag_writes: list[tuple[tuple[str, int, str], dict[str, Any]]]
    flag_deletes: list[tuple[str, int, str]]
    digest_writes: list[tuple[str, datetime, datetime, str, int]]

    def result(
        self,
        symbol: str,
        n_derived: int,
        *,
        n_vendor_removed: int = 0,
        n_archive_segment: int = 0,
    ) -> _SymbolResult:
        counts = {
            "rows_new": sum(len(d.new) for d in self.deltas.values()),
            "rows_changed": sum(len(d.changed) for d in self.deltas.values()),
            "rows_unchanged": sum(d.unchanged for d in self.deltas.values()),
            "rows_removed": sum(len(d.removed) for d in self.deltas.values()),
        }
        if self.refusals:
            error = f"{symbol}: refused: {'; '.join(self.refusals)}"
            return _SymbolResult("refused", error, n_derived, **counts)
        return _SymbolResult(
            "derived",
            None,
            n_derived,
            **counts,
            vendor_rows_removed=n_vendor_removed,
            archive_segment_rows=n_archive_segment,
        )


class _DailyResult(NamedTuple):
    """One symbol's daily-stage outcome plus its change accounting."""

    outcome: str
    error: str | None
    n_canonical: int
    n_stored: int
    n_changed: int
    reasons: dict[str, int]
    n_pre_split: int
    n_no_volume: int
    sample_diffs: tuple[tuple[date, float, float, str, str], ...] = ()


def _rowcount(status: str) -> int:
    """Parse the count out of an asyncpg command status like 'DELETE 2'."""
    try:
        return int(status.rsplit(None, 1)[-1])
    except (IndexError, ValueError) as error:
        raise ValueError(f"cannot parse rowcount from status {status!r}") from error


def _diff_fields(stored: Any, bar: CanonicalBar) -> tuple[str, ...]:
    """The fields where a stored 1d row differs from the canonical bar.

    Bit-exact on purpose: the same provider re-fetching an unchanged bar must
    compare equal, and any drift (the seam audit's 74 unexplained days) must
    surface as a change, not be rounded away. Empty tuple means equal.
    """
    fields = []
    for name in ("open", "high", "low", "close", "volume"):
        if stored[name] != getattr(bar, name):
            fields.append(name)
    return tuple(fields)


def _epoch_seconds(dt: datetime) -> int:
    """Epoch seconds for an aware datetime (naive is treated as UTC)."""
    if dt.tzinfo is None:
        return calendar.timegm(dt.timetuple())
    return int(dt.timestamp())


async def write_1d_digests(
    conn: Any, *, symbol: str, batch_id: str | None, rule_version: str
) -> int:
    """Insert a bar_content_digest row for each 1d month whose digest changed (D-07).

    Content is read back from the stored rows of every canonical 1d source
    (CANONICAL_1D_SOURCES, so a Tradier-owned name digests its Tradier bars), with
    each row's non-quarantine flag rules beside it (the grid convention). Callers
    run it after their scrub so the flags it adds or clears are in the digest.
    Shared by D2's daily stage (rule d2-v1) and the Tradier daily loader
    (tradier-v1, plan 185-27); returns the number of rows inserted.
    """
    rows = await conn.fetch(_SELECT_DIGEST_1D_SQL, symbol, list(CANONICAL_1D_SOURCES))
    if not rows:
        return 0
    flag_rows = await conn.fetch(_SELECT_1D_FLAG_RULES_SQL, symbol)
    rules_by_ts: dict[int, set[str]] = {}
    for r in flag_rows:
        if not r["quarantine"]:
            rules_by_ts.setdefault(_epoch_seconds(r["timestamp"]), set()).add(r["rule"])
    ts_seconds = np.array([_epoch_seconds(r["timestamp"]) for r in rows], dtype=np.int64)
    open_ = np.array([r["open"] for r in rows], dtype=np.float64)
    high = np.array([r["high"] for r in rows], dtype=np.float64)
    low = np.array([r["low"] for r in rows], dtype=np.float64)
    close = np.array([r["close"] for r in rows], dtype=np.float64)
    volume = np.array([r["volume"] for r in rows], dtype=np.float64)
    rules_per_row = [tuple(sorted(rules_by_ts.get(int(ts), ()))) for ts in ts_seconds]
    current = {
        r["range_start"]: r["digest"]
        for r in await conn.fetch(_SELECT_CURRENT_1D_DIGESTS_SQL, symbol)
    }
    digest_args: list[tuple] = []
    for start, end in month_ranges(ts_seconds):
        mask = (ts_seconds >= int(start.timestamp())) & (ts_seconds < int(end.timestamp()))
        digest = bar_content_digest(
            ts_seconds[mask],
            open_[mask],
            high[mask],
            low[mask],
            close[mask],
            volume[mask],
            [rules_per_row[i] for i in np.flatnonzero(mask)],
        )
        if current.get(start) != digest:
            digest_args.append(
                (
                    symbol,
                    "1d",
                    start,
                    end,
                    digest,
                    DIGEST_ALGORITHM,
                    rule_version,
                    int(mask.sum()),
                    batch_id,
                )
            )
    if digest_args:
        async with conn.transaction():
            await conn.execute(_WRITER_ROLE_SQL)
            await conn.executemany(_INSERT_DIGEST_SQL, digest_args)
    return len(digest_args)


def _read_exclude_file(path: str | None, logger: Any) -> frozenset[str]:
    """Symbols one-per-line from an operator exclude list; a missing file excludes nothing."""
    if not path:
        return frozenset()
    exclude_path = Path(path)
    if not exclude_path.exists():
        logger.info("bar_derivation.no_exclude_file", path=path)
        return frozenset()
    symbols = {
        line.strip()
        for line in exclude_path.read_text().splitlines()
        if line.strip() and not line.strip().startswith("#")
    }
    if symbols:
        logger.info("bar_derivation.excluded_lanes", n=len(symbols))
    return frozenset(symbols)


def _derive_for_tf(
    ts_seconds: np.ndarray,
    open_: np.ndarray,
    high: np.ndarray,
    low: np.ndarray,
    close: np.ndarray,
    volume: np.ndarray,
    rules_per_row: list[tuple[str, ...]],
    sessions: dict[date, tuple[datetime, datetime]],
    minutes: int,
) -> tuple[GridBars, list[tuple[str, ...]]]:
    """Aggregate one timeframe plus, per derived bar, its constituent rule union."""
    grid = aggregate_session_grid(ts_seconds, open_, high, low, close, volume, sessions, minutes)
    constituent_rules: list[tuple[str, ...]] = []
    for first, last in zip(grid.first_index, grid.last_index):
        union: set[str] = set()
        for i in range(int(first), int(last) + 1):
            union.update(rules_per_row[i])
        constituent_rules.append(tuple(sorted(union)))
    return grid, constituent_rules


def _missing_constituent_slots(
    bar_ts_seconds: int,
    minutes: int,
    session_close: datetime | None,
    stored_slots: frozenset[int],
    answered: AnsweredWindows,
) -> list[datetime]:
    """The bar's expected 5m slots that are neither stored nor inside an
    answered SMART TRADES window (todo 462). A stored-but-quarantined slot
    counts as present (its absence from the aggregate is already flagged by
    the constituent rules); a placeholder-shaped hole is not present."""
    interval = 300
    end = bar_ts_seconds + minutes * 60
    if session_close is not None:
        end = min(end, _epoch_seconds(session_close))
    missing: list[datetime] = []
    slot = bar_ts_seconds
    while slot < end:
        if slot not in stored_slots and not answered.covers(
            datetime.fromtimestamp(slot, tz=UTC), timedelta(seconds=interval)
        ):
            missing.append(datetime.fromtimestamp(slot, tz=UTC))
        slot += interval
    return missing


def _month_digest_rows(
    ts_seconds: np.ndarray,
    open_: np.ndarray,
    high: np.ndarray,
    low: np.ndarray,
    close: np.ndarray,
    volume: np.ndarray,
    rules_per_row: list[tuple[str, ...]],
) -> list[tuple[datetime, datetime, str, int]]:
    """(range_start, range_end, digest, n_rows) per calendar month of the slice."""
    rows: list[tuple[datetime, datetime, str, int]] = []
    for start, end in month_ranges(ts_seconds):
        mask = (ts_seconds >= int(start.timestamp())) & (ts_seconds < int(end.timestamp()))
        rows.append(
            (
                start,
                end,
                bar_content_digest(
                    ts_seconds[mask],
                    open_[mask],
                    high[mask],
                    low[mask],
                    close[mask],
                    volume[mask],
                    [rules_per_row[i] for i in np.flatnonzero(mask)],
                ),
                int(mask.sum()),
            )
        )
    return rows


class BarDerivation(BaseBatch):
    """Batch service: tradeable 5m bars -> derived 15m/1h grid + digests (D2b),
    and D1 TRADES observations -> canonical 1d bars + lineage (D2, plan 17)."""

    job_name = _JOB
    # Both stage versions: the tag is audit metadata; each batch row records
    # its own stage's rule_version exactly (open_batch takes it explicitly).
    compute_version = f"{GRID_RULE_VERSION},{RULE_VERSION}"

    def __init__(
        self,
        db_dsn: str,
        *,
        stage: str,
        symbols: list[str] | None,
        changed_only: bool,
        apply: bool,
        exclude_symbols_file: str | None,
        report_path: str | None = None,
    ) -> None:
        super().__init__(db_dsn)
        if stage not in ("grid", "daily"):
            raise ValueError(f"unknown stage {stage!r}; 'grid' and 'daily' exist")
        self._stage = stage
        self._symbols = symbols
        self._changed_only = changed_only
        self._apply = apply
        self._exclude_symbols_file = exclude_symbols_file
        self._report_path = report_path

    async def execute(self, pool: asyncpg.Pool) -> dict[str, int]:
        if self._stage == "daily":
            return await self._execute_daily(pool)
        return await self._execute_grid(pool)

    async def _execute_grid(self, pool: asyncpg.Pool) -> dict[str, int]:
        async with pool.acquire() as conn:
            apr = await load_apr_dict_async(
                conn, ["infra.bar_derivation.%", "threshold.bar_integrity.%"]
            )
            symbol_batch = int(
                _cfg(apr, "infra.bar_derivation.grid_symbol_batch", _DEFAULT_SYMBOL_BATCH)
            )
            method = str(_cfg(apr, "infra.bar_derivation.grid_write_method", _WRITE_METHOD))
            if method != _WRITE_METHOD:
                raise ValueError(
                    f"infra.bar_derivation.grid_write_method={method!r}: only "
                    f"{_WRITE_METHOD!r} is implemented (plan 185-31)"
                )
            limits = _RevisionLimits(
                max_ratio=float(
                    _cfg(
                        apr,
                        "threshold.bar_integrity.max_revision_ratio",
                        _DEFAULT_MAX_REVISION_RATIO,
                    )
                ),
                min_stored=int(
                    _cfg(
                        apr,
                        "threshold.bar_integrity.revision_ratio_min_stored",
                        _DEFAULT_REVISION_MIN_STORED,
                    )
                ),
            )
            symbols = (
                list(self._symbols)
                if self._symbols
                else [r[0] for r in await conn.fetch(_DISCOVER_SYMBOLS_SQL)]
            )
            excluded = _read_exclude_file(self._exclude_symbols_file, self.logger)
            targets = [s for s in symbols if s not in excluded]

            apr_snapshot = {
                k: v
                for k, v in apr.items()
                if k.startswith(("infra.bar_derivation.", "threshold.bar_integrity."))
            }
            batch_id: str | None = None
            if self._apply:
                batch_id = await open_batch(
                    conn,
                    stage="grid",
                    rule_version=GRID_RULE_VERSION,
                    apr_snapshot=apr_snapshot,
                    n_symbols=len(targets),
                )
            totals = dict.fromkeys(_GRID_OUTCOMES, 0)
            totals["excluded_lane"] = len(symbols) - len(targets)
            rows = dict.fromkeys(_GRID_ROW_COUNTS, 0)
            n_derived_rows = 0
            failed: list[str] = []
            try:
                for offset in range(0, len(targets), symbol_batch):
                    chunk = targets[offset : offset + symbol_batch]
                    for symbol in chunk:
                        result = await self._run_symbol(
                            conn, symbol=symbol, batch_id=batch_id, limits=limits
                        )
                        totals[result.outcome] += 1
                        n_derived_rows += result.n_derived
                        for key in _GRID_ROW_COUNTS:
                            rows[key] += getattr(result, key)
                        if result.error:
                            failed.append(result.error)
                    self.logger.info(
                        "bar_derivation.chunk_complete",
                        stage=self._stage,
                        symbols_done=min(offset + symbol_batch, len(targets)),
                        symbols_total=len(targets),
                        failed_so_far=len(failed),
                    )
            finally:
                if batch_id is not None:
                    await close_batch(
                        conn,
                        batch_id,
                        status="failed" if failed else "completed",
                        detail={
                            "totals": {k: n for k, n in totals.items() if n},
                            "n_derived_rows": n_derived_rows,
                            # Stored vendor 15m/1h rows the verify matched by value and the
                            # vendor DELETE removed (archive or archive_segment revision).
                            "n_archive_rows": rows["vendor_rows_removed"],
                            "rows": rows,
                            "apply": self._apply,
                            "changed_only": self._changed_only,
                        },
                    )

        self.logger.info(
            "bar_derivation.done",
            stage=self._stage,
            symbols=len(symbols),
            apply=self._apply,
            changed_only=self._changed_only,
            **totals,
            **rows,
            derived_rows=n_derived_rows,
        )
        for outcome in _GRID_OUTCOMES:
            if totals[outcome]:
                _OUTCOME_TOTAL.add(totals[outcome], {"stage": self._stage, "outcome": outcome})
        if failed:
            raise RuntimeError(f"bar_derivation: {len(failed)} symbol failure(s): {failed}")
        return {**totals, **rows, "derived_rows": n_derived_rows}

    async def _load_answered_windows(
        self, conn: asyncpg.Connection, symbol: str
    ) -> AnsweredWindows:
        """Answered SMART TRADES 5m windows for `symbol`, read once per symbol."""
        rows = await conn.fetch(
            _SELECT_ANSWERED_WINDOWS_SQL,
            symbol,
            list(ANSWERED_OUTCOMES),
            COVERAGE_ROUTE,
            COVERAGE_WHAT_TO_SHOW,
        )
        return AnsweredWindows.from_rows([(r["window_start"], r["window_end"]) for r in rows])

    async def _plan_grid(
        self,
        conn: asyncpg.Connection,
        *,
        symbol: str,
        derived_values: dict[str, dict[int, BarValues]],
        desired_flags: dict[tuple[str, int, str], dict[str, Any]],
        digest_rows: list[tuple[str, datetime, datetime, str, int]],
        limits: _RevisionLimits,
    ) -> _GridPlan:
        """Read the stored grid, flags and digests; classify by the write contract.

        Pure comparison over three reads; no writes. Called inside the symbol's transaction on
        --apply (so the classification and the writes see the same rows) and alone on a dry run.
        """
        stored_derived: dict[str, dict[int, BarValues]] = {tf: {} for tf in _GRID_TF_LIST}
        n_vendor: dict[str, int] = dict.fromkeys(_GRID_TF_LIST, 0)
        for r in await conn.fetch(_SELECT_STORED_GRID_SQL, symbol, _GRID_TF_LIST):
            tf = r["timeframe"]
            if r["source"] == SOURCE_DERIVED_5M:
                stored_derived[tf][_epoch_seconds(r["timestamp"])] = (
                    r["open"],
                    r["high"],
                    r["low"],
                    r["close"],
                    r["volume"],
                    r["source"],
                )
            else:
                n_vendor[tf] += 1
        deltas: dict[str, WriteDelta[int]] = {}
        refusals: list[str] = []
        for tf in _GRID_TF_LIST:
            stored = stored_derived[tf]
            delta = classify(derived_values[tf], stored, removal_scope=stored.keys())
            deltas[tf] = delta
            if should_refuse(
                delta, len(stored), limits.max_ratio, min_stored=limits.min_stored, waived=False
            ):
                refusals.append(
                    f"{tf} revision ratio {revision_ratio(delta, len(stored)):.4f} "
                    f"({len(delta.changed)} changed + {len(delta.removed)} removed of "
                    f"{len(stored)} stored) > {limits.max_ratio}"
                )

        stored_flags: dict[tuple[str, int, str], tuple[str, Any]] = {}
        for r in await conn.fetch(
            _SELECT_STORED_GRID_FLAGS_SQL, symbol, _GRID_TF_LIST, list(_GRID_FLAG_RULES)
        ):
            detail = r["detail"]
            if isinstance(detail, str):  # a bare connection without the jsonb codec
                detail = json.loads(detail)
            key = (r["timeframe"], _epoch_seconds(r["timestamp"]), r["rule"])
            stored_flags[key] = (r["rule_version"], detail)
        flag_writes = [
            (key, detail)
            for key, detail in desired_flags.items()
            if stored_flags.get(key) != (GRID_RULE_VERSION, detail)
        ]
        flag_deletes = [key for key in stored_flags if key not in desired_flags]

        current = {
            (r["timeframe"], r["range_start"]): r["digest"]
            for r in await conn.fetch(
                _SELECT_CURRENT_GRID_DIGESTS_SQL, symbol, [GRID_SOURCE_TF, *_GRID_TF_LIST]
            )
        }
        digest_writes = [row for row in digest_rows if current.get((row[0], row[1])) != row[3]]
        return _GridPlan(
            deltas=deltas,
            n_stored_derived={tf: len(stored_derived[tf]) for tf in _GRID_TF_LIST},
            n_vendor=n_vendor,
            refusals=tuple(refusals),
            flag_writes=flag_writes,
            flag_deletes=flag_deletes,
            digest_writes=digest_writes,
        )

    async def _run_symbol(
        self,
        conn: asyncpg.Connection,
        *,
        symbol: str,
        batch_id: str | None,
        limits: _RevisionLimits,
    ) -> _SymbolResult:
        rows = await conn.fetch(_SELECT_5M_SQL, symbol)
        if not rows:
            return _SymbolResult("no_5m", None, 0)
        flag_rows = await conn.fetch(_SELECT_5M_FLAGS_SQL, symbol)
        quarantined = {_epoch_seconds(r["timestamp"]) for r in flag_rows if r["quarantine"]}
        rules_by_ts: dict[int, set[str]] = {}
        for r in flag_rows:
            if not r["quarantine"]:
                rules_by_ts.setdefault(_epoch_seconds(r["timestamp"]), set()).add(r["rule"])

        kept = [r for r in rows if _epoch_seconds(r["timestamp"]) not in quarantined]
        if not kept:
            # Every 5m bar is quarantined: no tradeable input, same contract as no_5m.
            return _SymbolResult("no_5m", None, 0)
        ts_seconds = np.array([_epoch_seconds(r["timestamp"]) for r in kept], dtype=np.int64)
        open_ = np.array([r["open"] for r in kept], dtype=np.float64)
        high = np.array([r["high"] for r in kept], dtype=np.float64)
        low = np.array([r["low"] for r in kept], dtype=np.float64)
        close = np.array([r["close"] for r in kept], dtype=np.float64)
        volume = np.array([r["volume"] for r in kept], dtype=np.float64)
        base = kept[0]["base"]
        rules_per_row = [tuple(sorted(rules_by_ts.get(int(ts), ()))) for ts in ts_seconds]
        first_day = datetime.fromtimestamp(int(ts_seconds[0]), tz=UTC).date()
        last_day = datetime.fromtimestamp(int(ts_seconds[-1]), tz=UTC).date()

        sessions = nyse_sessions(
            first_day - timedelta(days=_SESSION_MARGIN_DAYS),
            last_day + timedelta(days=_SESSION_MARGIN_DAYS),
        )
        digest_5m = _month_digest_rows(ts_seconds, open_, high, low, close, volume, rules_per_row)
        if self._changed_only:
            current_5m = {
                r["range_start"]: r["digest"]
                for r in await conn.fetch(_SELECT_CURRENT_DIGESTS_SQL, symbol)
            }
            if current_5m == {start: digest for start, _, digest, _ in digest_5m}:
                answered_since = await conn.fetchrow(
                    _SELECT_ANSWERED_SINCE_SQL,
                    symbol,
                    list(ANSWERED_OUTCOMES),
                    COVERAGE_ROUTE,
                    COVERAGE_WHAT_TO_SHOW,
                )
                if not answered_since["answered_since"]:
                    return _SymbolResult("unchanged", None, 0)

        derived: dict[str, tuple[GridBars, list[tuple[str, ...]]]] = {
            tf: _derive_for_tf(
                ts_seconds, open_, high, low, close, volume, rules_per_row, sessions, minutes
            )
            for tf, minutes in GRID_TIMEFRAMES.items()
        }
        n_derived = sum(grid.ts_seconds.size for grid, _ in derived.values())
        n_outside = sum(grid.n_outside_session for grid, _ in derived.values())
        if n_outside:
            self.logger.warning(
                "bar_derivation.bars_outside_session", symbol=symbol, dropped=n_outside
            )

        # The write contract's incoming side, keyed by epoch seconds per timeframe.
        derived_values: dict[str, dict[int, BarValues]] = {
            tf: {
                int(ts): (float(o), float(h), float(lo), float(c), int(v), SOURCE_DERIVED_5M)
                for ts, o, h, lo, c, v in zip(
                    grid.ts_seconds, grid.open, grid.high, grid.low, grid.close, grid.volume
                )
            }
            for tf, (grid, _rules) in derived.items()
        }

        # Desired grid flags: constituent rules, and coverage-aware partial flags over stored-
        # but-unanswered 5m holes (todo 462; the windows are read once per symbol and the pure
        # merge/cover logic is the shared planner's, gap_plan, plan 185-18).
        desired_flags: dict[tuple[str, int, str], dict[str, Any]] = {}
        stored_slots = frozenset(_epoch_seconds(r["timestamp"]) for r in rows)
        answered = await self._load_answered_windows(conn, symbol)
        session_close_by_date = {day: close for day, (_open, close) in sessions.items()}
        for tf, (grid, constituent_rules) in derived.items():
            minutes = GRID_TIMEFRAMES[tf]
            for i, (ts, rules) in enumerate(zip(grid.ts_seconds, constituent_rules)):
                n_constituents = int(grid.n_constituents[i])
                if rules:
                    desired_flags[(tf, int(ts), _CONSTITUENT_RULE)] = {
                        "constituent_rules": list(rules),
                        "n_constituents": n_constituents,
                    }
                missing = _missing_constituent_slots(
                    int(ts),
                    minutes,
                    session_close_by_date.get(datetime.fromtimestamp(int(ts), tz=UTC).date()),
                    stored_slots,
                    answered,
                )
                if missing:
                    desired_flags[(tf, int(ts), _PARTIAL_RULE)] = {
                        "missing_slots": len(missing),
                        "n_constituents": n_constituents,
                    }

        digest_rows: list[tuple[str, datetime, datetime, str, int]] = [
            (GRID_SOURCE_TF, start, end, digest, n) for start, end, digest, n in digest_5m
        ]
        for tf, (grid, constituent_rules) in derived.items():
            digest_rows.extend(
                (tf, start, end, digest, n)
                for start, end, digest, n in _month_digest_rows(
                    grid.ts_seconds,
                    grid.open,
                    grid.high,
                    grid.low,
                    grid.close,
                    grid.volume,
                    constituent_rules,
                )
            )

        planning = {
            "symbol": symbol,
            "derived_values": derived_values,
            "desired_flags": desired_flags,
            "digest_rows": digest_rows,
            "limits": limits,
        }
        if not self._apply:
            plan = await self._plan_grid(conn, **planning)
            return plan.result(symbol, n_derived, n_vendor_removed=sum(plan.n_vendor.values()))

        assert batch_id is not None  # --apply always opens a batch
        try:
            async with conn.transaction():
                plan = await self._plan_grid(conn, **planning)
                await conn.execute(_WRITER_ROLE_SQL)
                load_ids = {tf: str(uuid4()) for tf in _GRID_TF_LIST}
                outcome = "refused" if plan.refusals else "applied"
                for tf in _GRID_TF_LIST:
                    delta = plan.deltas[tf]
                    grid_ts = derived[tf][0].ts_seconds
                    await conn.execute(
                        _INSERT_GRID_LOAD_SQL,
                        load_ids[tf],
                        symbol,
                        tf,
                        _GRID_LOAD_SOURCE,
                        first_day,
                        last_day,
                        outcome,
                        len(derived_values[tf]),
                        len(delta.new),
                        len(delta.changed),
                        delta.unchanged,
                        len(delta.removed),
                        (
                            datetime.fromtimestamp(int(grid_ts[0]), tz=UTC).date()
                            if grid_ts.size
                            else None
                        ),
                        (
                            datetime.fromtimestamp(int(grid_ts[-1]), tz=UTC).date()
                            if grid_ts.size
                            else None
                        ),
                        json.dumps(
                            {
                                "rule_version": GRID_RULE_VERSION,
                                "n_stored_derived": plan.n_stored_derived[tf],
                                "n_vendor_rows": plan.n_vendor[tf],
                                "refusals": list(plan.refusals),
                            }
                        ),
                        _GRID_LOAD_CALLER,
                        batch_id,
                        _GRID_LOAD_DESTINATION,
                    )
                if plan.refusals:
                    # The load rows are the recorded finding; nothing else is written.
                    return plan.result(symbol, n_derived)
                n_vendor = sum(plan.n_vendor.values())
                n_archive_segment = 0
                if n_vendor:
                    n_archive_segment = await self._remove_vendor_rows(
                        conn,
                        symbol=symbol,
                        batch_id=batch_id,
                        load_ids=load_ids,
                        n_vendor=n_vendor,
                    )
                await self._write_derived(
                    conn, symbol=symbol, base=base, plan=plan, load_ids=load_ids
                )
                if plan.flag_deletes:
                    await conn.executemany(
                        _DELETE_GRID_FLAG_SQL,
                        (
                            (symbol, tf, datetime.fromtimestamp(ts, tz=UTC), rule)
                            for tf, ts, rule in plan.flag_deletes
                        ),
                    )
                if plan.flag_writes:
                    await conn.executemany(
                        _INSERT_FLAG_SQL,
                        (
                            (
                                symbol,
                                tf,
                                datetime.fromtimestamp(ts, tz=UTC),
                                rule,
                                GRID_RULE_VERSION,
                                [],
                                False,
                                json.dumps(detail),
                                batch_id,
                            )
                            for (tf, ts, rule), detail in plan.flag_writes
                        ),
                    )
                if plan.digest_writes:
                    await conn.executemany(
                        _INSERT_DIGEST_SQL,
                        (
                            (
                                symbol,
                                tf,
                                start,
                                end,
                                digest,
                                DIGEST_ALGORITHM,
                                GRID_RULE_VERSION,
                                n,
                                batch_id,
                            )
                            for tf, start, end, digest, n in plan.digest_writes
                        ),
                    )
        except Exception as error:
            return _SymbolResult("failed", f"{symbol}: {error}", 0)
        return plan.result(
            symbol, n_derived, n_vendor_removed=n_vendor, n_archive_segment=n_archive_segment
        )

    async def _remove_vendor_rows(
        self,
        conn: asyncpg.Connection,
        *,
        symbol: str,
        batch_id: str,
        load_ids: dict[str, str],
        n_vendor: int,
    ) -> int:
        """Archive, record differing observations, verify by value, then delete (todo 490).

        Runs inside the symbol's transaction; any mismatch raises _SymbolFailure and the whole
        symbol rolls back, so nothing leaves market_data_ohlcv without a kept equal copy.
        Returns the number of archive_segment revision rows written.
        """
        await conn.execute(_INSERT_ARCHIVE_SQL, symbol, _GRID_TF_LIST, batch_id)
        n_segment = 0
        for tf in _GRID_TF_LIST:
            n_segment += _rowcount(
                await conn.execute(_INSERT_ARCHIVE_SEGMENT_REVISION_SQL, symbol, tf, load_ids[tf])
            )
        verify = await conn.fetchrow(
            _VENDOR_REMOVAL_VERIFY_SQL, symbol, _GRID_TF_LIST, list(load_ids.values())
        )
        if verify["n_unmatched"] or verify["n_removable"] != n_vendor:
            raise _SymbolFailure(
                f"vendor removal verify failed: {verify['n_unmatched']} of "
                f"{verify['n_removable']} stored vendor rows have no equal archive or revision "
                f"row (classification read {n_vendor})"
            )
        n_deleted = _rowcount(await conn.execute(_DELETE_VENDOR_ROWS_SQL, symbol, _GRID_TF_LIST))
        if n_deleted != n_vendor:
            raise _SymbolFailure(f"vendor delete removed {n_deleted} rows, verified {n_vendor}")
        return n_segment

    async def _write_derived(
        self,
        conn: asyncpg.Connection,
        *,
        symbol: str,
        base: str | None,
        plan: _GridPlan,
        load_ids: dict[str, str],
    ) -> None:
        """Old values to ohlcv_revision first, then stale deletes, new inserts, changed upserts."""

        def _bar(tf: str, ts: int, values: BarValues) -> tuple:
            return (datetime.fromtimestamp(ts, tz=UTC), symbol, tf, *values, base)

        def _revision(tf: str, ts: int, old: BarValues) -> tuple:
            return (load_ids[tf], symbol, tf, datetime.fromtimestamp(ts, tz=UTC), *old, "load")

        revisions = [
            _revision(tf, ts, old)
            for tf, delta in plan.deltas.items()
            for ts, (_new, old) in delta.changed.items()
        ]
        revisions += [
            _revision(tf, ts, old)
            for tf, delta in plan.deltas.items()
            for ts, old in delta.removed.items()
        ]
        if revisions:
            await conn.executemany(_INSERT_LOAD_REVISION_SQL, revisions)
        for tf, delta in plan.deltas.items():
            if not delta.removed:
                continue
            stale = [datetime.fromtimestamp(ts, tz=UTC) for ts in sorted(delta.removed)]
            n_deleted = _rowcount(
                await conn.execute(
                    _DELETE_STALE_DERIVED_SQL, symbol, tf, stale, stale[0], stale[-1]
                )
            )
            if n_deleted != len(stale):
                raise _SymbolFailure(f"{tf} stale delete removed {n_deleted} of {len(stale)}")
        new_rows = [
            _bar(tf, ts, values)
            for tf, delta in plan.deltas.items()
            for ts, values in delta.new.items()
        ]
        if new_rows:
            await conn.executemany(_INSERT_DERIVED_SQL, new_rows)
        changed_rows = [
            _bar(tf, ts, new)
            for tf, delta in plan.deltas.items()
            for ts, (new, _old) in delta.changed.items()
        ]
        if changed_rows:
            await conn.executemany(_UPSERT_DERIVED_SQL, changed_rows)

    # --- D2 daily stage (plan 17, D-06/D-07/D-12/D-21) -------------------

    async def _execute_daily(self, pool: asyncpg.Pool) -> dict[str, int]:
        started = datetime.now(UTC)
        async with pool.acquire() as conn:
            apr = await load_apr_dict_async(
                conn, ["infra.bar_derivation.%", "threshold.bar_scrub.%"]
            )
            symbol_batch = int(
                _cfg(apr, "infra.bar_derivation.daily_symbol_batch", _DEFAULT_DAILY_SYMBOL_BATCH)
            )
            method = str(_cfg(apr, "infra.bar_derivation.daily_write_method", _DAILY_WRITE_METHOD))
            if method != _DAILY_WRITE_METHOD:
                raise ValueError(
                    f"infra.bar_derivation.daily_write_method={method!r}: only "
                    f"{_DAILY_WRITE_METHOD!r} is implemented (185-01 measurement b)"
                )
            venue_enabled = (
                str(_cfg(apr, "infra.bar_derivation.venue_bars_1d", "false")).strip().lower()
                == "true"
            )
            quarantine_rules = set(
                json.loads(str(_cfg(apr, "threshold.bar_scrub.quarantine_rules", "[]")))
            )
            symbols = (
                list(self._symbols)
                if self._symbols
                else [r[0] for r in await conn.fetch(_DISCOVER_DAILY_SYMBOLS_SQL)]
            )
            excluded = _read_exclude_file(self._exclude_symbols_file, self.logger)
            targets = [s for s in symbols if s not in excluded]

            apr_snapshot = {k: v for k, v in apr.items() if k.startswith("infra.bar_derivation.")}
            batch_id: str | None = None
            if self._apply:
                batch_id = await open_batch(
                    conn,
                    stage="daily",
                    rule_version=RULE_VERSION,
                    apr_snapshot=apr_snapshot,
                    n_symbols=len(targets),
                )
            totals = dict.fromkeys(
                ("derived", "unchanged", "no_observations", "tradier_owned", "failed"), 0
            )
            reasons_total: dict[str, int] = {}
            n_canonical = n_stored = n_changed = n_pre_split = n_no_volume = 0
            per_symbol: dict[str, dict[str, int]] = {}
            samples: list[tuple[str, date, float, float, str, str]] = []
            failed: list[str] = []
            derived_symbols: list[str] = []
            try:
                for offset in range(0, len(targets), symbol_batch):
                    chunk = targets[offset : offset + symbol_batch]
                    for symbol in chunk:
                        try:
                            result = await self._run_daily_symbol(
                                conn,
                                symbol=symbol,
                                batch_id=batch_id,
                                venue_enabled=venue_enabled,
                                quarantine_rules=quarantine_rules,
                            )
                        except Exception as error:
                            result = _DailyResult("failed", f"{symbol}: {error}", 0, 0, 0, {}, 0, 0)
                        totals[result.outcome] += 1
                        n_canonical += result.n_canonical
                        n_stored += result.n_stored
                        n_changed += result.n_changed
                        n_pre_split += result.n_pre_split
                        n_no_volume += result.n_no_volume
                        for reason, count in result.reasons.items():
                            reasons_total[reason] = reasons_total.get(reason, 0) + count
                        if result.outcome == "derived":
                            derived_symbols.append(symbol)
                            per_symbol[symbol] = {
                                "changed": result.n_changed,
                                "missing": result.reasons.get("missing", 0),
                                "d1_value_differs": result.reasons.get("d1_value_differs", 0),
                                "volume_differs": result.reasons.get("volume_differs", 0),
                                "split_rescale": result.reasons.get("split_rescale", 0),
                                "pre_split": result.n_pre_split,
                                "canonical": result.n_canonical,
                                "stored": result.n_stored,
                            }
                            for diff in result.sample_diffs:
                                if len(samples) < 30:
                                    samples.append((symbol, *diff))
                        if result.error:
                            failed.append(result.error)
                    self.logger.info(
                        "bar_derivation.chunk_complete",
                        stage=self._stage,
                        symbols_done=min(offset + symbol_batch, len(targets)),
                        symbols_total=len(targets),
                        failed_so_far=len(failed),
                    )
                # D2a rerun: one scrub_symbols call over the run's symbols so
                # cross-symbol corroboration (D-11) spans the whole run.
                if self._apply and derived_symbols:
                    try:
                        await scrub_symbols(
                            pool,
                            tf="1d",
                            symbols=derived_symbols,
                            rules=None,
                            start=None,
                            end=None,
                            batch_id=batch_id,
                            write=True,
                        )
                    except Exception as error:
                        failed.append(f"scrub: {error}")
                    # Digests after the scrub (plan 185-27), so a flag the scrub
                    # adds or clears is inside the digest this run writes.
                    for symbol in derived_symbols:
                        try:
                            await write_1d_digests(
                                conn, symbol=symbol, batch_id=batch_id, rule_version=RULE_VERSION
                            )
                        except Exception as error:
                            failed.append(f"digest {symbol}: {error}")
            finally:
                if batch_id is not None:
                    await close_batch(
                        conn,
                        batch_id,
                        status="failed" if failed else "completed",
                        detail={
                            "totals": {k: n for k, n in totals.items() if n},
                            "reasons": reasons_total,
                            "changed_bars": n_changed,
                            "canonical_bars": n_canonical,
                            "pre_split_bars": n_pre_split,
                            "no_volume_bars": n_no_volume,
                            "apply": self._apply,
                            "changed_only": self._changed_only,
                        },
                    )

        if self._report_path:
            self._write_daily_report(
                started=started,
                totals=totals,
                reasons=reasons_total,
                n_canonical=n_canonical,
                n_stored=n_stored,
                n_changed=n_changed,
                n_pre_split=n_pre_split,
                n_no_volume=n_no_volume,
                per_symbol=per_symbol,
                samples=samples,
                venue_enabled=venue_enabled,
                failed=failed,
            )
        self.logger.info(
            "bar_derivation.done",
            stage=self._stage,
            symbols=len(symbols),
            apply=self._apply,
            changed_only=self._changed_only,
            changed_bars=n_changed,
            pre_split_bars=n_pre_split,
            **totals,
        )
        for outcome in ("derived", "unchanged", "no_observations", "tradier_owned", "failed"):
            if totals[outcome]:
                _OUTCOME_TOTAL.add(totals[outcome], {"stage": self._stage, "outcome": outcome})
        if failed:
            raise RuntimeError(f"bar_derivation: {len(failed)} symbol failure(s): {failed}")
        return {
            "totals": totals,
            "reasons": reasons_total,
            "canonical_bars": n_canonical,
            "stored_rows": n_stored,
            "changed_bars": n_changed,
            "n_pre_split_bars": n_pre_split,
            "n_no_volume_bars": n_no_volume,
        }

    async def _run_daily_symbol(
        self,
        conn: asyncpg.Connection,
        *,
        symbol: str,
        batch_id: str | None,
        venue_enabled: bool,
        quarantine_rules: set[str],
    ) -> _DailyResult:
        # Probe first (cheap EXISTS, one round trip): the nightly --changed-only
        # pass skips the observation load and the whole derivation for symbols
        # with nothing new since the last completed daily batch. has_obs mirrors
        # _SELECT_DAILY_OBSERVATIONS_SQL's WHERE so the probe alone preserves
        # the no_observations-vs-unchanged distinction; n_canonical is 0 for
        # unchanged symbols by construction (nothing was derived).
        probe = await conn.fetchrow(_SELECT_DAILY_CHANGED_SINCE_SQL, symbol)
        if probe["tradier_owned"]:
            return _DailyResult("tradier_owned", None, 0, 0, 0, {}, 0, 0)
        if not probe["has_obs"]:
            return _DailyResult("no_observations", None, 0, 0, 0, {}, 0, 0)
        if self._changed_only and not (probe["obs_since"] or probe["action_since"]):
            return _DailyResult("unchanged", None, 0, 0, 0, {}, 0, 0)
        obs_rows = await conn.fetch(_SELECT_DAILY_OBSERVATIONS_SQL, symbol)
        if not obs_rows:
            return _DailyResult("no_observations", None, 0, 0, 0, {}, 0, 0)
        split_rows = await conn.fetch(_SELECT_DAILY_SPLITS_SQL, symbol)
        splits = [
            SplitRecord(
                effective_date=r["effective_date"],
                recorded_at=r["recorded_at"],
                factor=r["factor"],
            )
            for r in split_rows
        ]
        observations = [
            Observation(
                request_id=r["request_id"],
                route=r["route"],
                bar_date=r["bar_date"],
                open=r["open"],
                high=r["high"],
                low=r["low"],
                close=r["close"],
                volume=r["volume"],
                fetched_at=r["fetched_at"],
                legacy=r["legacy"],
                what_to_show=r["what_to_show"],
            )
            for r in obs_rows
        ]
        canonical = derive_daily(observations, splits, venue_bars_enabled=venue_enabled)

        stored_rows = await conn.fetch(_SELECT_STORED_1D_SQL, symbol)
        stored = {r["timestamp"].date(): r for r in stored_rows}
        # base is NULL across market_data_ohlcv today (the grid stage writes
        # the same NULL), so the upsert carries the symbol's stored value or
        # NULL -- never a failure; base is provenance the table does not hold.
        base = (
            stored_rows[0]["base"] if stored_rows else await conn.fetchval(_SELECT_BASE_SQL, symbol)
        )

        reasons = {
            "split_rescale": 0,
            "d1_value_differs": 0,
            "volume_differs": 0,
            "missing": 0,
        }
        changes: list[tuple[CanonicalBar, str]] = []
        sample_diffs: list[tuple[date, float, float, str, str]] = []
        n_pre_split = n_no_volume = 0
        for bar in canonical:
            if _PRE_SPLIT_RULE in bar.flags:
                n_pre_split += 1
            if _NO_VOLUME_RULE in bar.flags:
                n_no_volume += 1
            srow = stored.get(bar.bar_date)
            if srow is None:
                reasons["missing"] += 1
                changes.append((bar, "missing"))
            else:
                fields = _diff_fields(srow, bar)
                if fields:
                    affects_split = split_staleness_threshold(bar.bar_date, splits) is not None
                    if affects_split and _PRE_SPLIT_RULE not in bar.flags:
                        reason = "split_rescale"
                    elif fields == ("volume",):
                        # IBKR daily volume is not stable across fetches
                        # (late odd-lot corrections; measured 2026-10-02:
                        # 1-share drift on AAPL 2026-07-29). Prices equal,
                        # volume only: still written, reported as what it is.
                        reason = "volume_differs"
                    else:
                        reason = "d1_value_differs"
                    reasons[reason] += 1
                    changes.append((bar, reason))
                    if len(sample_diffs) < 10:
                        sample_diffs.append(
                            (
                                bar.bar_date,
                                float(srow["close"]),
                                float(bar.close),
                                reason,
                                ",".join(fields),
                            )
                        )

        if not self._apply:
            return _DailyResult(
                "derived",
                None,
                len(canonical),
                len(stored),
                len(changes),
                reasons,
                n_pre_split,
                n_no_volume,
                tuple(sample_diffs),
            )

        try:
            async with conn.transaction():
                await conn.execute(_WRITER_ROLE_SQL)
                if changes:
                    await conn.executemany(
                        _UPSERT_1D_SQL,
                        (
                            (
                                datetime(
                                    b.bar_date.year, b.bar_date.month, b.bar_date.day, tzinfo=UTC
                                ),
                                symbol,
                                "1d",
                                b.open,
                                b.high,
                                b.low,
                                b.close,
                                b.volume,
                                b.source,
                                base,
                            )
                            for b, _reason in changes
                        ),
                    )
                # Lineage for EVERY canonical bar, changed or not (D-07).
                await conn.executemany(
                    _UPSERT_LINEAGE_SQL,
                    (
                        (
                            symbol,
                            datetime(b.bar_date.year, b.bar_date.month, b.bar_date.day, tzinfo=UTC),
                            RULE_VERSION,
                            list(b.request_ids),
                            batch_id,
                        )
                        for b in canonical
                    ),
                )
            # pre_split / no_volume flags through the shared write_flags path
            # (delete-then-insert of the evaluated rules, so re-derivations
            # clear stale flags; D-21 quarantine per the APR list).
            flag_rows = [
                FlagRow(
                    timestamp=datetime(
                        b.bar_date.year, b.bar_date.month, b.bar_date.day, tzinfo=UTC
                    ),
                    rule=rule,
                    rule_version=RULE_VERSION,
                    fields=_PRE_SPLIT_FIELDS if rule == _PRE_SPLIT_RULE else ("volume",),
                    quarantine=(rule == _PRE_SPLIT_RULE and rule in quarantine_rules),
                    detail={"source": b.source},
                )
                for b in canonical
                for rule in b.flags
                if rule in (_PRE_SPLIT_RULE, _NO_VOLUME_RULE)
            ]
            await write_flags(
                conn,
                tf="1d",
                symbol=symbol,
                rules_evaluated=frozenset({_PRE_SPLIT_RULE, _NO_VOLUME_RULE}),
                flags=flag_rows,
                start=None,
                end=None,
                batch_id=batch_id,
            )
        except Exception as error:
            return _DailyResult(
                "failed",
                f"{symbol}: {error}",
                len(canonical),
                len(stored),
                0,
                {},
                n_pre_split,
                n_no_volume,
            )
        return _DailyResult(
            "derived",
            None,
            len(canonical),
            len(stored),
            len(changes),
            reasons,
            n_pre_split,
            n_no_volume,
            tuple(sample_diffs),
        )

    def _write_daily_report(
        self,
        *,
        started: datetime,
        totals: dict[str, int],
        reasons: dict[str, int],
        n_canonical: int,
        n_stored: int,
        n_changed: int,
        n_pre_split: int,
        n_no_volume: int,
        per_symbol: dict[str, dict[str, int]],
        samples: list[tuple[str, date, float, float, str, str]],
        venue_enabled: bool,
        failed: list[str],
    ) -> None:
        """The measured change report (committed as docs/research artifact)."""
        mode = (
            "apply (writes executed)"
            if self._apply
            else "dry run (no writes; --apply is plan 185-18)"
        )
        lines = [
            "# D2 1d derivation dry run report",
            "",
            f"Generated: {started.isoformat()}",
            f"Mode: {mode}",
            f"Rule version: {RULE_VERSION}; write method: {_DAILY_WRITE_METHOD}",
            f"Venue bars gate (infra.bar_derivation.venue_bars_1d): {str(venue_enabled).lower()}",
            "",
            "## Totals",
            "",
            "| measure | count |",
            "|---|---|",
            f"| symbols considered | {sum(totals.values())} |",
            f"| derived | {totals.get('derived', 0)} |",
            f"| unchanged (changed-only) | {totals.get('unchanged', 0)} |",
            f"| no D1 observations | {totals.get('no_observations', 0)} |",
            f"| failed | {totals.get('failed', 0)} |",
            f"| canonical bars | {n_canonical} |",
            f"| stored canonical-source 1d rows compared | {n_stored} |",
            f"| changed bars | {n_changed} |",
            f"| pre_split_unrefetched bars | {n_pre_split} |",
            f"| no_provider_volume bars | {n_no_volume} |",
            "",
            "## Changed bars by reason",
            "",
            "| reason | bars |",
            "|---|---|",
        ]
        for reason in ("missing", "d1_value_differs", "volume_differs", "split_rescale"):
            lines.append(f"| {reason} | {reasons.get(reason, 0)} |")
        lines.extend(
            [
                "",
                "## Top 20 symbols by changed bars",
                "",
                "| symbol | changed | missing | d1_value_differs | volume_differs | split_rescale | pre_split |",
                "|---|---|---|---|---|---|---|",
            ]
        )
        top = sorted(per_symbol.items(), key=lambda kv: (-kv[1]["changed"], kv[0]))[:20]
        for symbol, stats in top:
            lines.append(
                f"| {symbol} | {stats['changed']} | {stats['missing']} "
                f"| {stats['d1_value_differs']} | {stats['volume_differs']} "
                f"| {stats['split_rescale']} | {stats['pre_split']} |"
            )
        lines.extend(["", "## Symbols with pre_split_unrefetched bars", ""])
        flagged = [(s, k) for s, k in sorted(per_symbol.items()) if k["pre_split"]]
        if flagged:
            for symbol, stats in flagged:
                lines.append(f"- {symbol} ({stats['pre_split']} bars)")
        else:
            lines.append("None: no symbol has a pre_split_unrefetched bar.")
        lines.extend(
            [
                "",
                "## Sample differing bars (up to 30)",
                "",
                "| symbol | date | stored close | canonical close | reason | fields |",
                "|---|---|---|---|---|---|",
            ]
        )
        for symbol, bar_date, stored_close, close, reason, fields in samples:
            lines.append(
                f"| {symbol} | {bar_date.isoformat()} | {stored_close} | {close} "
                f"| {reason} | {fields} |"
            )
        if not samples:
            lines.append("| (none) | | | | | |")
        if failed:
            lines.extend(["", "## Failures", ""])
            lines.extend(f"- {error}" for error in failed[:20])
        Path(self._report_path).write_text("\n".join(lines) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Derive the 15m/1h grid from tradeable 5m bars, and canonical 1d from D1"
    )
    parser.add_argument("--stage", choices=["grid", "daily"], default="grid")
    parser.add_argument(
        "--symbols",
        nargs="*",
        default=None,
        help="limit to these symbols (default: all eligible for the stage)",
    )
    parser.add_argument(
        "--changed-only",
        action="store_true",
        help="grid: skip unchanged 5m digests; daily: skip symbols with no "
        "observations or corporate actions after the last completed daily batch",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="write the replacement (default: dry run, compute and report only)",
    )
    parser.add_argument(
        "--exclude-symbols-file",
        default=None,
        help="operator exclude list: one symbol per line to skip with outcome excluded_lane",
    )
    parser.add_argument(
        "--report",
        default=None,
        help="daily stage: write the markdown change report to this path",
    )
    args = parser.parse_args()
    # Accept both `--symbols SPY,AAPL` (the pipeline/plan convention) and
    # `--symbols SPY AAPL`; nargs="*" alone would take the comma form as one
    # bogus symbol and skip it as no_5m.
    if args.symbols:
        args.symbols = [
            sym for part in args.symbols for sym in (t.strip() for t in part.split(",")) if sym
        ]
    try:
        init_otel_providers(f"indicagent-{_JOB}")
    except OTelInitError:
        pass
    settings = Settings()
    db_dsn = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
    writer = BarDerivation(
        db_dsn,
        stage=args.stage,
        symbols=args.symbols,
        changed_only=args.changed_only,
        apply=args.apply,
        exclude_symbols_file=args.exclude_symbols_file,
        report_path=args.report,
    )
    asyncio.run(writer.run())


if __name__ == "__main__":
    main()
