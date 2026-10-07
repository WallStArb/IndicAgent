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

Daily stage (plans 17 and 36). Per symbol: load the D1 TRADES observations of routes TRADIER,
SMART and LEGACY_IMPORT, the 1d bar_source_policy rows (read once per run) and the
corporate_action_current splits with their evidence, and run the pure d2-v2 rule
(src/intelligence/bars/daily_rule.py): Tradier primary for every name, IBKR as a recorded head
or a basis-tested interior fallback (data layer integrity design section 2). The canonical bars
are classified by the write contract against the stored 1d rows of every canonical source, with
removal inside the name's derived span (its first to last observed date). A dry run (the default)
writes nothing and reports per name (--report writes a TSV). The apply path, one transaction per
symbol under SET LOCAL ROLE bar_derivation_writer: one ohlcv_load row (source derived, outcome
applied or refused, the four counts), old values of changed and removed rows to ohlcv_revision
(origin load), removed rows deleted by key, new rows inserted, changed rows upserted (the changed
set only, never a raw UPDATE of the compressed hypertable), and the fallback_seam,
pre_split_unrefetched and no_provider_volume flags through bar_scrub's write_flags; then one
scrub_symbols call over the run's symbols and write_1d_digests at rule d2-v2. A revision ratio
above threshold.bar_integrity.max_revision_ratio over at least revision_ratio_min_stored stored
rows refuses the symbol (only its refused load row commits) unless a corporate action or a 1d
bar_source_policy row was recorded after the symbol's previous applied daily load, or no such
load exists. No canonical_bar_lineage row is written: apply refuses to start while that table
exists (185-38 replaces it with the lineage view and makes this stage the single 1d writer).
"""

from __future__ import annotations

import argparse
import asyncio
import calendar
import csv
import gzip
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
from src.intelligence.bars.daily_rule import (
    FLAG_FALLBACK_SEAM,
    FLAG_NO_VOLUME,
    FLAG_PRE_SPLIT,
    RULE_VERSION,
    DailyV2Result,
    PolicyRow,
    derive_daily_v2,
)
from src.intelligence.bars.derivation import Observation, SplitRecord
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

_INSERT_LOAD_SQL = """
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

_INSERT_BAR_SQL = """
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

# --- D2 daily stage (plans 17 and 36) ----------------------------------

_DEFAULT_DAILY_SYMBOL_BATCH = 25
_DAILY_WRITE_METHOD = "upsert"
# Fallbacks equal to migration 446's seeds; the run reads threshold.bar_integrity.* from APR.
_DEFAULT_BASIS_WINDOW_SESSIONS = 20
_DEFAULT_BASIS_TOLERANCE_BP = 10.0
# The daily stage's ohlcv_load rows (source derived, the grid's segment; caller tells the stage).
_DAILY_LOAD_CALLER = "bar_derivation-daily"
# A restore from the pre-cutover 1d snapshot (plan 185-38): same contract, its own caller.
_RESTORE_LOAD_CALLER = "bar_derivation-restore"
_DAILY_FLAG_RULES = frozenset({FLAG_FALLBACK_SEAM, FLAG_PRE_SPLIT, FLAG_NO_VOLUME})
# D1 routes d2-v2 reads: Tradier, IBKR SMART, and the stored corpus's import as IBKR's lowest
# rank. Venue routes stay out (the D-17 venue study failed).
_D2V2_ROUTES = ("TRADIER", "SMART", "LEGACY_IMPORT")
_DAILY_OUTCOMES = ("derived", "unchanged", "no_observations", "refused", "failed")
_DAILY_ROW_COUNTS = ("new", "changed", "unchanged", "removed")
_DAILY_REPORT_COLUMNS = (
    "symbol",
    "group",
    "outcome",
    "n_stored",
    "n_canonical",
    "new",
    "changed",
    "changed_source_only",
    "unchanged",
    "removed",
    "outside_span",
    "head",
    "refused_head",
    "admitted_interior",
    "refused_interior",
    "refused_dates",
    "stale_only",
    "revision_ratio",
    "would_refuse",
    "waived",
    "error",
)

_DISCOVER_DAILY_SYMBOLS_SQL = """
SELECT symbol FROM instruments
WHERE is_active AND compute_eligible_1d
ORDER BY symbol
"""

# The d2-v2 routes' TRADES observations ($2 = _D2V2_ROUTES). The request join keeps test
# fixtures out: a request whose caller starts 'test-' never becomes a canonical bar (2026-10-03:
# fixture rows on SPY 2024-01-02 to 01-04 would have replaced closes of 472 with 100.5).
_SELECT_DAILY_OBSERVATIONS_SQL = """
SELECT o.request_id::text AS request_id, o.route, o.bar_date,
       o.open, o.high, o.low, o.close, o.volume, o.fetched_at,
       o.what_to_show, (o.route = 'LEGACY_IMPORT') AS legacy
FROM ohlcv_observation o
JOIN ohlcv_request q ON q.request_id = o.request_id
WHERE o.symbol = $1 AND o.timeframe = '1d' AND o.what_to_show = 'TRADES'
  AND o.route = ANY($2::text[])
  AND q.caller NOT LIKE 'test-%'
ORDER BY o.bar_date, o.fetched_at, o.request_id
"""

_SELECT_DAILY_SPLITS_SQL = """
SELECT effective_date, recorded_at, factor,
       COALESCE(evidence_request_ids::text[], '{}'::text[]) AS evidence_request_ids
FROM corporate_action_current
WHERE symbol = $1
ORDER BY effective_date
"""

# The 1d source decisions (migration 446), read once per run.
_SELECT_POLICY_1D_SQL = """
SELECT timeframe, symbol, valid_from, valid_to, ingress_mode, primary_source, fallback_source
FROM bar_source_policy
WHERE timeframe = '1d'
"""

# The write contract's stored side: every canonical 1d source ($2 = CANONICAL_1D_SOURCES).
_SELECT_STORED_1D_SQL = """
/* stored_1d */
SELECT "timestamp", open, high, low, close, volume, source, base
FROM market_data_ohlcv
WHERE symbol = $1 AND timeframe = '1d' AND source = ANY($2::text[])
ORDER BY "timestamp"
"""

# The 1d digest's content: stored rows of every canonical 1d source ($2 =
# CANONICAL_1D_SOURCES).
_SELECT_DIGEST_1D_SQL = """
SELECT "timestamp", open, high, low, close, volume
FROM market_data_ohlcv
WHERE symbol = $1 AND timeframe = '1d' AND source = ANY($2::text[])
ORDER BY "timestamp"
"""

_SELECT_CURRENT_1D_DIGESTS_SQL = """
SELECT range_start, digest, rule_version FROM bar_content_digest_current
WHERE symbol = $1 AND timeframe = '1d'
"""

_SELECT_1D_FLAG_RULES_SQL = """
SELECT "timestamp", rule, quarantine
FROM bar_quality_flag
WHERE symbol = $1 AND timeframe = '1d'
"""

# A name Tradier owns (plan 185-38): its open 1d bar_source_policy row (the symbol's open row,
# else the timeframe default) names Tradier primary, and a Tradier observation exists. Format
# with col = the symbol expression. The Tradier loader's nightly selects these names; the IBKR
# history fetcher (phase 189) skips their IBKR 1d through tradier_owned below.
TRADIER_OWNED_SQL = (
    "(COALESCE("
    "(SELECT p.primary_source FROM bar_source_policy p WHERE p.timeframe = '1d'"
    " AND p.symbol = {col} AND p.valid_to IS NULL),"
    " (SELECT p.primary_source FROM bar_source_policy p WHERE p.timeframe = '1d'"
    " AND p.symbol IS NULL AND p.valid_to IS NULL)) = 'tradier'"
    " AND EXISTS (SELECT 1 FROM ohlcv_observation o WHERE o.symbol = {col}"
    " AND o.timeframe = '1d' AND o.route = 'TRADIER'))"
)

# --changed-only: a symbol is due when any TRADES request was answered after the last completed
# daily batch, or a corporate action or a 1d source policy row was recorded after it.
_SELECT_DAILY_CHANGED_SINCE_SQL = f"""
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
EXISTS (
    SELECT 1 FROM bar_source_policy p
    WHERE p.timeframe = '1d' AND (p.symbol = $1 OR p.symbol IS NULL)
      AND p.recorded_at > COALESCE(
          (SELECT max(finished_at) FROM bar_derivation_batch
           WHERE stage = 'daily' AND status = 'completed'),
          '-infinity'::timestamptz)
) AS policy_since,
-- The IBKR history fetcher (phase 189) imports this statement as _DAILY_SOURCE_PROBE_SQL and
-- reads tradier_owned to skip IBKR 1d fetches. Since plan 185-38 it is TRADIER_OWNED_SQL: the
-- name's open 1d policy row names Tradier primary and a Tradier observation exists. The daily
-- stage does not read it; 189-10 replaces the fetcher's use with the weekly IBKR 1d reconcile.
{TRADIER_OWNED_SQL.format(col='$1')} AS tradier_owned
"""

# The revision-ratio waiver: no applied daily load yet, or a corporate action or a 1d policy
# row (the symbol's or the default) recorded after the symbol's latest applied daily load, or a
# snapshot restore (plan 185-38) after it: the restore is a recorded operator rollback, and the
# re-derivation that follows re-applies the reviewed state. Only the daily stage's own loads
# are the baseline.
_SELECT_REVISION_WAIVER_SQL = """
/* revision_waiver */
WITH last_load AS (
    SELECT max(loaded_at) AS at FROM ohlcv_load
    WHERE symbol = $1 AND timeframe = '1d' AND source = 'derived' AND outcome = 'applied'
      AND caller = 'bar_derivation-daily'
)
SELECT (SELECT at FROM last_load) IS NULL
    OR EXISTS (SELECT 1 FROM corporate_action c, last_load l
               WHERE c.symbol = $1 AND c.recorded_at > l.at)
    OR EXISTS (SELECT 1 FROM bar_source_policy p, last_load l
               WHERE p.timeframe = '1d' AND (p.symbol = $1 OR p.symbol IS NULL)
                 AND p.recorded_at > l.at)
    OR EXISTS (SELECT 1 FROM ohlcv_load r, last_load l
               WHERE r.symbol = $1 AND r.timeframe = '1d' AND r.source = 'derived'
                 AND r.outcome = 'applied' AND r.caller = 'bar_derivation-restore'
                 AND r.loaded_at > l.at)
"""

# 185-38 drops the table for a view of the same name; until then apply refuses ('r' = table).
_SELECT_LINEAGE_RELKIND_SQL = """
SELECT relkind::text FROM pg_class
WHERE relname = 'canonical_bar_lineage' AND relnamespace = 'public'::regnamespace
"""

# Native upsert, 185-01 measurement b; the changed set only.
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

# Removed 1d rows by key; the literal range ahead of ANY() keeps chunk exclusion (todo 356).
_DELETE_1D_ROWS_SQL = """
/* delete_1d_rows */
DELETE FROM market_data_ohlcv
WHERE symbol = $1 AND timeframe = '1d'
  AND "timestamp" BETWEEN $3 AND $4 AND "timestamp" = ANY($2::timestamptz[])
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
class _DailyResult:
    """One symbol's daily-stage outcome and its write-contract accounting (the report row)."""

    symbol: str
    outcome: str
    error: str | None = None
    group: str = ""
    n_stored: int = 0
    n_canonical: int = 0
    new: int = 0
    changed: int = 0
    changed_source_only: int = 0
    unchanged: int = 0
    removed: int = 0
    outside_span: int = 0
    head: int = 0
    refused_head: int = 0
    admitted_interior: int = 0
    refused_dates: tuple[date, ...] = ()
    stale_only: int = 0
    revision_ratio: float = 0.0
    would_refuse: bool = False
    waived: bool | None = None

    def report_row(self) -> dict[str, str]:
        values: dict[str, Any] = {
            **{name: getattr(self, name) for name in _DAILY_REPORT_COLUMNS if hasattr(self, name)},
            "refused_interior": len(self.refused_dates),
            "refused_dates": ",".join(d.isoformat() for d in self.refused_dates),
            "revision_ratio": f"{self.revision_ratio:.6f}",
            "would_refuse": str(self.would_refuse).lower(),
            "waived": "" if self.waived is None else str(self.waived).lower(),
            "error": self.error or "",
        }
        return {name: str(values[name]) for name in _DAILY_REPORT_COLUMNS}


def _stored_group(sources: set[str]) -> str:
    """Which vendors a name's stored 1d rows come from before the run."""
    if not sources:
        return "none"
    if "tradier" not in sources:
        return "ibkr_only"
    return "tradier_only" if sources == {"tradier"} else "mixed"


def _utc_day(day: date) -> datetime:
    return datetime(day.year, day.month, day.day, tzinfo=UTC)


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


def _rowcount(status: str) -> int:
    """Parse the count out of an asyncpg command status like 'DELETE 2'."""
    try:
        return int(status.rsplit(None, 1)[-1])
    except (IndexError, ValueError) as error:
        raise ValueError(f"cannot parse rowcount from status {status!r}") from error


def _epoch_seconds(dt: datetime) -> int:
    """Epoch seconds for an aware datetime (naive is treated as UTC)."""
    if dt.tzinfo is None:
        return calendar.timegm(dt.timetuple())
    return int(dt.timestamp())


async def write_1d_digests(
    conn: Any,
    *,
    symbol: str,
    batch_id: str | None,
    rule_version: str,
    force_rule_version: bool = False,
    write: bool = True,
) -> int:
    """Insert a bar_content_digest row for each 1d month whose digest changed (D-07).

    Content is read back from the stored rows of every canonical 1d source
    (CANONICAL_1D_SOURCES, so a Tradier-owned name digests its Tradier bars), with
    each row's non-quarantine flag rules beside it (the grid convention). Callers
    run it after their scrub so the flags it adds or clears are in the digest.
    The daily stage's writer (rule d2-v2). force_rule_version also writes a month whose
    content is unchanged but whose current digest carries another rule version (the 185-38
    cutover relabels every month). write=False counts without inserting. Returns the number
    of rows inserted (or that would be).
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
        r["range_start"]: (r["digest"], r["rule_version"])
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
        stored_digest, stored_rule = current.get(start, (None, None))
        if stored_digest != digest or (force_rule_version and stored_rule != rule_version):
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
    if digest_args and write:
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
        rewrite_digests: bool = False,
        restore_snapshot: str | None = None,
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
        self._rewrite_digests = rewrite_digests
        self._restore_snapshot = restore_snapshot
        if rewrite_digests and restore_snapshot:
            raise ValueError("--rewrite-digests and --restore-snapshot are separate runs")
        if (rewrite_digests or restore_snapshot) and stage != "daily":
            raise ValueError("--rewrite-digests and --restore-snapshot belong to --stage daily")

    async def execute(self, pool: asyncpg.Pool) -> dict[str, int]:
        if self._restore_snapshot:
            return await self._execute_restore(pool)
        if self._rewrite_digests:
            return await self._execute_rewrite_digests(pool)
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
                        _INSERT_LOAD_SQL,
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
            await conn.executemany(_INSERT_BAR_SQL, new_rows)
        changed_rows = [
            _bar(tf, ts, new)
            for tf, delta in plan.deltas.items()
            for ts, (new, _old) in delta.changed.items()
        ]
        if changed_rows:
            await conn.executemany(_UPSERT_DERIVED_SQL, changed_rows)

    # --- D2 daily stage (plans 17 and 36; d2-v2) ---------------------------

    async def _execute_daily(self, pool: asyncpg.Pool) -> dict[str, Any]:
        async with pool.acquire() as conn:
            apr = await load_apr_dict_async(
                conn,
                ["infra.bar_derivation.%", "threshold.bar_integrity.%", "threshold.bar_scrub.%"],
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
            params = _DailyParams(
                window=int(
                    _cfg(
                        apr,
                        "threshold.bar_integrity.fallback_basis_window_sessions",
                        _DEFAULT_BASIS_WINDOW_SESSIONS,
                    )
                ),
                tolerance_bp=float(
                    _cfg(
                        apr,
                        "threshold.bar_integrity.fallback_basis_tolerance_bp",
                        _DEFAULT_BASIS_TOLERANCE_BP,
                    )
                ),
                limits=_RevisionLimits(
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
                ),
                quarantine_rules=frozenset(
                    json.loads(str(_cfg(apr, "threshold.bar_scrub.quarantine_rules", "[]")))
                ),
                policy=tuple(
                    PolicyRow(
                        timeframe=r["timeframe"],
                        symbol=r["symbol"],
                        valid_from=r["valid_from"],
                        valid_to=r["valid_to"],
                        ingress_mode=r["ingress_mode"],
                        primary_source=r["primary_source"],
                        fallback_source=r["fallback_source"],
                    )
                    for r in await conn.fetch(_SELECT_POLICY_1D_SQL)
                ),
            )
            symbols = (
                list(self._symbols)
                if self._symbols
                else [r[0] for r in await conn.fetch(_DISCOVER_DAILY_SYMBOLS_SQL)]
            )
            excluded = _read_exclude_file(self._exclude_symbols_file, self.logger)
            targets = [s for s in symbols if s not in excluded]

            batch_id: str | None = None
            if self._apply:
                batch_id = await self._open_daily_batch(conn, apr, len(targets))
            totals = dict.fromkeys(_DAILY_OUTCOMES, 0)
            rows = dict.fromkeys(_DAILY_ROW_COUNTS, 0)
            results: list[_DailyResult] = []
            failed: list[str] = []
            applied: list[str] = []
            try:
                for offset in range(0, len(targets), symbol_batch):
                    for symbol in targets[offset : offset + symbol_batch]:
                        try:
                            result = await self._run_daily_symbol(
                                conn, symbol=symbol, batch_id=batch_id, params=params
                            )
                        except Exception as error:
                            result = _DailyResult(symbol, "failed", f"{symbol}: {error}")
                        results.append(result)
                        totals[result.outcome] += 1
                        for key in _DAILY_ROW_COUNTS:
                            rows[key] += getattr(result, key)
                        if result.error:
                            failed.append(result.error)
                        if self._apply and result.outcome == "derived":
                            applied.append(symbol)
                    self.logger.info(
                        "bar_derivation.chunk_complete",
                        stage=self._stage,
                        symbols_done=min(offset + symbol_batch, len(targets)),
                        symbols_total=len(targets),
                        failed_so_far=len(failed),
                    )
                if applied:
                    # D2a rerun: one scrub_symbols call over the run's symbols so cross-symbol
                    # corroboration (D-11) spans the whole run; digests after it (plan 185-27).
                    try:
                        await scrub_symbols(
                            pool,
                            tf="1d",
                            symbols=applied,
                            rules=None,
                            start=None,
                            end=None,
                            batch_id=batch_id,
                            write=True,
                        )
                    except Exception as error:
                        failed.append(f"scrub: {error}")
                    for symbol in applied:
                        try:
                            await write_1d_digests(
                                conn, symbol=symbol, batch_id=batch_id, rule_version=RULE_VERSION
                            )
                        except Exception as error:
                            failed.append(f"digest {symbol}: {error}")
            finally:
                summary = _daily_summary(results)
                if batch_id is not None:
                    await close_batch(
                        conn,
                        batch_id,
                        status="failed" if failed else "completed",
                        detail={
                            "totals": {k: n for k, n in totals.items() if n},
                            "rows": rows,
                            **summary,
                            "apply": self._apply,
                            "changed_only": self._changed_only,
                        },
                    )

        if self._report_path:
            _write_daily_report(self._report_path, results)
        self.logger.info(
            "bar_derivation.done",
            stage=self._stage,
            symbols=len(symbols),
            apply=self._apply,
            changed_only=self._changed_only,
            **totals,
            **{f"rows_{k}": n for k, n in rows.items()},
            **summary,
        )
        for outcome in _DAILY_OUTCOMES:
            if totals[outcome]:
                _OUTCOME_TOTAL.add(totals[outcome], {"stage": self._stage, "outcome": outcome})
        if failed:
            raise RuntimeError(f"bar_derivation: {len(failed)} symbol failure(s): {failed}")
        return {"totals": totals, "rows": rows, **summary}

    async def _run_daily_symbol(
        self,
        conn: asyncpg.Connection,
        *,
        symbol: str,
        batch_id: str | None,
        params: _DailyParams,
    ) -> _DailyResult:
        # Probe first (cheap EXISTS, one round trip): the nightly --changed-only pass skips the
        # observation load and the derivation for symbols with nothing new since the last
        # completed daily batch.
        probe = await conn.fetchrow(_SELECT_DAILY_CHANGED_SINCE_SQL, symbol)
        if not probe["has_obs"]:
            return _DailyResult(symbol, "no_observations")
        if self._changed_only and not (
            probe["obs_since"] or probe["action_since"] or probe["policy_since"]
        ):
            return _DailyResult(symbol, "unchanged")
        obs_rows = await conn.fetch(_SELECT_DAILY_OBSERVATIONS_SQL, symbol, list(_D2V2_ROUTES))
        if not obs_rows:
            return _DailyResult(symbol, "no_observations")
        splits = [
            SplitRecord(
                effective_date=r["effective_date"],
                recorded_at=r["recorded_at"],
                factor=r["factor"],
                evidence_request_ids=tuple(r["evidence_request_ids"] or ()),
            )
            for r in await conn.fetch(_SELECT_DAILY_SPLITS_SQL, symbol)
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
        derived = derive_daily_v2(
            observations,
            params.policy,
            splits,
            symbol=symbol,
            basis_window_sessions=params.window,
            basis_tolerance_bp=params.tolerance_bp,
        )

        stored_rows = await conn.fetch(_SELECT_STORED_1D_SQL, symbol, list(CANONICAL_1D_SOURCES))
        stored: dict[date, BarValues] = {
            r["timestamp"].date(): (
                r["open"],
                r["high"],
                r["low"],
                r["close"],
                r["volume"],
                r["source"],
            )
            for r in stored_rows
        }
        # base is NULL on every 1d row today; the write carries the stored value if one exists.
        base = next((r["base"] for r in stored_rows if r["base"] is not None), None)
        incoming: dict[date, BarValues] = {
            b.bar_date: (b.open, b.high, b.low, b.close, b.volume, b.source) for b in derived.bars
        }
        span_start = min(o.bar_date for o in observations)
        span_end = max(o.bar_date for o in observations)
        scope = [d for d in stored if span_start <= d <= span_end]
        delta = classify(incoming, stored, removal_scope=scope)
        ratio = revision_ratio(delta, len(stored))
        would_refuse = should_refuse(
            delta,
            len(stored),
            params.limits.max_ratio,
            min_stored=params.limits.min_stored,
            waived=False,
        )
        waived = (
            bool(await conn.fetchval(_SELECT_REVISION_WAIVER_SQL, symbol)) if would_refuse else None
        )
        refuse = would_refuse and not waived
        result = _DailyResult(
            symbol=symbol,
            outcome="refused" if refuse else "derived",
            error=(
                f"{symbol}: refused: revision ratio {ratio:.4f} over {len(stored)} stored rows "
                f"exceeds {params.limits.max_ratio} with no recorded corporate action or policy "
                "change since the last applied daily load"
                if refuse
                else None
            ),
            group=_stored_group({values[5] for values in stored.values()}),
            n_stored=len(stored),
            n_canonical=len(derived.bars),
            new=len(delta.new),
            changed=len(delta.changed),
            changed_source_only=sum(1 for new, old in delta.changed.values() if new[:5] == old[:5]),
            unchanged=delta.unchanged,
            removed=len(delta.removed),
            outside_span=len(stored) - len(scope),
            head=len(derived.head),
            refused_head=len(derived.refused_head),
            admitted_interior=len(derived.admitted_interior),
            refused_dates=tuple(derived.refused_interior),
            stale_only=len(derived.stale_only),
            revision_ratio=ratio,
            would_refuse=would_refuse,
            waived=waived,
        )
        if not self._apply:
            return result
        assert batch_id is not None  # --apply always opens a batch
        await self._write_daily(
            conn,
            symbol=symbol,
            batch_id=batch_id,
            base=base,
            derived=derived,
            delta=delta,
            result=result,
            span=(span_start, span_end),
            quarantine_rules=params.quarantine_rules,
        )
        return result

    async def _write_daily(
        self,
        conn: asyncpg.Connection,
        *,
        symbol: str,
        batch_id: str,
        base: str | None,
        derived: DailyV2Result,
        delta: WriteDelta[date],
        result: _DailyResult,
        span: tuple[date, date],
        quarantine_rules: frozenset[str],
    ) -> None:
        """One transaction: the load row, then (unless refused) revisions, bars and flags."""
        load_id = str(uuid4())
        async with conn.transaction():
            await conn.execute(_WRITER_ROLE_SQL)
            await conn.execute(
                _INSERT_LOAD_SQL,
                load_id,
                symbol,
                "1d",
                _GRID_LOAD_SOURCE,
                span[0],
                span[1],
                "refused" if result.outcome == "refused" else "applied",
                len(derived.bars),
                result.new,
                result.changed,
                result.unchanged,
                result.removed,
                derived.bars[0].bar_date if derived.bars else None,
                derived.bars[-1].bar_date if derived.bars else None,
                json.dumps(
                    {
                        "rule_version": RULE_VERSION,
                        "n_stored": result.n_stored,
                        "revision_ratio": result.revision_ratio,
                        "waived": result.waived,
                        "head": result.head,
                        "refused_head": [d.isoformat() for d in derived.refused_head],
                        "admitted_interior": result.admitted_interior,
                        "refused_interior": [d.isoformat() for d in result.refused_dates],
                        "stale_only": [d.isoformat() for d in derived.stale_only],
                    }
                ),
                _DAILY_LOAD_CALLER,
                batch_id,
                _GRID_LOAD_DESTINATION,
            )
            if result.outcome == "refused":
                return
            await _apply_1d_delta(conn, symbol=symbol, load_id=load_id, base=base, delta=delta)
            # Replace the stage's flag rules for the symbol (delete-then-insert of the evaluated
            # rules, so a re-derivation clears a stale flag; D-21 quarantine per the APR list).
            await write_flags(
                conn,
                tf="1d",
                symbol=symbol,
                rules_evaluated=_DAILY_FLAG_RULES,
                flags=[
                    FlagRow(
                        timestamp=_utc_day(flag.bar_date),
                        rule=flag.rule,
                        rule_version=RULE_VERSION,
                        fields=flag.fields,
                        quarantine=flag.rule in quarantine_rules,
                        detail=flag.detail,
                    )
                    for flag in derived.flags
                ],
                start=None,
                end=None,
                batch_id=batch_id,
            )

    async def _open_daily_batch(self, conn: asyncpg.Connection, apr: dict, n: int) -> str:
        relkind = await conn.fetchval(_SELECT_LINEAGE_RELKIND_SQL)
        if relkind == "r":
            raise RuntimeError(
                "daily --apply refused: canonical_bar_lineage is still a table. d2-v2 "
                "writes no lineage row; 185-38 replaces the table with the lineage view "
                "and makes this stage the single 1d writer"
            )
        return await open_batch(
            conn,
            stage="daily",
            rule_version=RULE_VERSION,
            apr_snapshot={
                k: v
                for k, v in apr.items()
                if k.startswith(
                    ("infra.bar_derivation.", "threshold.bar_integrity.", "threshold.bar_scrub.")
                )
            },
            n_symbols=n,
        )

    async def _execute_rewrite_digests(self, pool: asyncpg.Pool) -> dict[str, Any]:
        """Every 1d month digest of each symbol at rule d2-v2 (the 185-38 cutover's step 5b):
        a month is written when its content or its rule version differs from the current row."""
        async with pool.acquire() as conn:
            apr = await load_apr_dict_async(
                conn,
                ["infra.bar_derivation.%", "threshold.bar_integrity.%", "threshold.bar_scrub.%"],
            )
            symbols = (
                list(self._symbols)
                if self._symbols
                else [r[0] for r in await conn.fetch(_DISCOVER_DAILY_SYMBOLS_SQL)]
            )
            batch_id = (
                await self._open_daily_batch(conn, apr, len(symbols)) if self._apply else None
            )
            written, failed = 0, []
            try:
                for symbol in symbols:
                    try:
                        written += await write_1d_digests(
                            conn,
                            symbol=symbol,
                            batch_id=batch_id,
                            rule_version=RULE_VERSION,
                            force_rule_version=True,
                            write=self._apply,
                        )
                    except Exception as error:
                        failed.append(f"digest {symbol}: {error}")
            finally:
                if batch_id is not None:
                    await close_batch(
                        conn,
                        batch_id,
                        status="failed" if failed else "completed",
                        detail={"rewrite_digests": True, "digests_written": written},
                    )
        self.logger.info(
            "bar_derivation.rewrite_digests_done",
            symbols=len(symbols),
            apply=self._apply,
            digests_written=written,
            failed=len(failed),
        )
        if failed:
            raise RuntimeError(f"bar_derivation: {len(failed)} digest failure(s): {failed}")
        return {"digests_written": written, "symbols": len(symbols)}

    async def _execute_restore(self, pool: asyncpg.Pool) -> dict[str, Any]:
        """Rewrite the named symbols' 1d rows from the pre-cutover snapshot (185-38 rollback).

        Snapshot rows are the incoming side and every stored 1d key of the symbol is in the
        removal scope, so the result equals the snapshot. Same contract as a derivation: one
        ohlcv_load row (caller bar_derivation-restore, waiver restore), old values to
        ohlcv_revision, deletes by key, inserts, the changed-set upsert; then the scrub and the
        digests. Flags are left as they are; a following re-derivation rewrites the stage's own.
        """
        if not self._symbols:
            raise ValueError(
                "--restore-snapshot needs --symbols (never the whole corpus by default)"
            )
        snapshot = _read_1d_snapshot(str(self._restore_snapshot), set(self._symbols))
        async with pool.acquire() as conn:
            apr = await load_apr_dict_async(
                conn,
                ["infra.bar_derivation.%", "threshold.bar_integrity.%", "threshold.bar_scrub.%"],
            )
            batch_id = (
                await self._open_daily_batch(conn, apr, len(self._symbols)) if self._apply else None
            )
            rows = dict.fromkeys(_DAILY_ROW_COUNTS, 0)
            failed: list[str] = []
            applied: list[str] = []
            try:
                for symbol in self._symbols:
                    try:
                        delta, n_stored = await self._restore_symbol(
                            conn,
                            symbol=symbol,
                            incoming=snapshot.get(symbol, {}),
                            batch_id=batch_id,
                        )
                    except Exception as error:
                        failed.append(f"{symbol}: {error}")
                        continue
                    rows["new"] += len(delta.new)
                    rows["changed"] += len(delta.changed)
                    rows["unchanged"] += delta.unchanged
                    rows["removed"] += len(delta.removed)
                    if self._apply:
                        applied.append(symbol)
                if applied:
                    try:
                        await scrub_symbols(
                            pool,
                            tf="1d",
                            symbols=applied,
                            rules=None,
                            start=None,
                            end=None,
                            batch_id=batch_id,
                            write=True,
                        )
                    except Exception as error:
                        failed.append(f"scrub: {error}")
                    for symbol in applied:
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
                        detail={"restore_snapshot": self._restore_snapshot, "rows": rows},
                    )
        self.logger.info(
            "bar_derivation.restore_done",
            symbols=len(self._symbols),
            apply=self._apply,
            **{f"rows_{k}": n for k, n in rows.items()},
        )
        if failed:
            raise RuntimeError(f"bar_derivation: {len(failed)} restore failure(s): {failed}")
        return {"rows": rows, "symbols": len(self._symbols)}

    async def _restore_symbol(
        self,
        conn: asyncpg.Connection,
        *,
        symbol: str,
        incoming: dict[date, BarValues],
        batch_id: str | None,
    ) -> tuple[WriteDelta[date], int]:
        stored_rows = await conn.fetch(_SELECT_STORED_1D_SQL, symbol, list(CANONICAL_1D_SOURCES))
        stored: dict[date, BarValues] = {
            r["timestamp"].date(): (
                r["open"],
                r["high"],
                r["low"],
                r["close"],
                r["volume"],
                r["source"],
            )
            for r in stored_rows
        }
        base = next((r["base"] for r in stored_rows if r["base"] is not None), None)
        delta = classify(incoming, stored, removal_scope=list(stored))
        if not self._apply:
            return delta, len(stored)
        assert batch_id is not None
        days = sorted(set(incoming) | set(stored))
        load_id = str(uuid4())
        async with conn.transaction():
            await conn.execute(_WRITER_ROLE_SQL)
            await conn.execute(
                _INSERT_LOAD_SQL,
                load_id,
                symbol,
                "1d",
                _GRID_LOAD_SOURCE,
                days[0] if days else None,
                days[-1] if days else None,
                "applied",
                len(incoming),
                len(delta.new),
                len(delta.changed),
                delta.unchanged,
                len(delta.removed),
                min(incoming) if incoming else None,
                max(incoming) if incoming else None,
                json.dumps(
                    {
                        "snapshot": self._restore_snapshot,
                        "n_stored": len(stored),
                        "waiver": "restore",
                    }
                ),
                _RESTORE_LOAD_CALLER,
                batch_id,
                _GRID_LOAD_DESTINATION,
            )
            await _apply_1d_delta(conn, symbol=symbol, load_id=load_id, base=base, delta=delta)
        return delta, len(stored)


async def _apply_1d_delta(
    conn: Any, *, symbol: str, load_id: str, base: str | None, delta: WriteDelta[date]
) -> None:
    """Inside the caller's transaction: old values of changed and removed rows to ohlcv_revision
    (origin load) first, then removed rows deleted by key, new rows inserted, changed rows
    upserted (the changed set only, never a raw UPDATE of the compressed hypertable)."""
    revisions = [
        (load_id, symbol, "1d", _utc_day(day), *old, "load")
        for day, (_new, old) in delta.changed.items()
    ] + [(load_id, symbol, "1d", _utc_day(day), *old, "load") for day, old in delta.removed.items()]
    if revisions:
        await conn.executemany(_INSERT_LOAD_REVISION_SQL, revisions)
    if delta.removed:
        keys = [_utc_day(day) for day in sorted(delta.removed)]
        n_deleted = _rowcount(
            await conn.execute(_DELETE_1D_ROWS_SQL, symbol, keys, keys[0], keys[-1])
        )
        if n_deleted != len(keys):
            raise _SymbolFailure(f"1d delete removed {n_deleted} of {len(keys)}")
    if delta.new:
        await conn.executemany(
            _INSERT_BAR_SQL,
            [(_utc_day(day), symbol, "1d", *v, base) for day, v in sorted(delta.new.items())],
        )
    if delta.changed:
        await conn.executemany(
            _UPSERT_1D_SQL,
            [
                (_utc_day(day), symbol, "1d", *new, base)
                for day, (new, _old) in sorted(delta.changed.items())
            ],
        )


def _read_1d_snapshot(path: str, symbols: set[str]) -> dict[str, dict[date, BarValues]]:
    """The named symbols' 1d rows from the gzip CSV snapshot (header row, market_data_ohlcv's
    columns in table order, written by psql \\copy ... CSV HEADER). An empty field is NULL."""
    out: dict[str, dict[date, BarValues]] = {}
    with gzip.open(path, "rt", newline="") as handle:
        for row in csv.DictReader(handle):
            if row["symbol"] not in symbols or row["timeframe"] != "1d":
                continue
            day = datetime.fromisoformat(row["timestamp"]).astimezone(UTC).date()
            out.setdefault(row["symbol"], {})[day] = (
                float(row["open"]),
                float(row["high"]),
                float(row["low"]),
                float(row["close"]),
                int(row["volume"]) if row["volume"] != "" else None,
                row["source"] or None,
            )
    return out


class _DailyParams(NamedTuple):
    """The daily stage's per-run inputs: APR thresholds and the 1d policy rows."""

    window: int
    tolerance_bp: float
    limits: _RevisionLimits
    quarantine_rules: frozenset[str]
    policy: tuple[PolicyRow, ...]


def _daily_summary(results: list[_DailyResult]) -> dict[str, int]:
    """Run-level fallback and refusal counts (the batch detail and the dry run's return)."""
    return {
        "head": sum(r.head for r in results),
        "refused_head": sum(r.refused_head for r in results),
        "admitted_interior": sum(r.admitted_interior for r in results),
        "refused_interior": sum(len(r.refused_dates) for r in results),
        "stale_only": sum(r.stale_only for r in results),
        "would_refuse": sum(r.would_refuse for r in results),
        "would_refuse_unwaived": sum(r.would_refuse and not r.waived for r in results),
    }


def _write_daily_report(path: str, results: list[_DailyResult]) -> None:
    """One TSV row per symbol (the dry-run measurement plan 185-36 records)."""
    with Path(path).open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=_DAILY_REPORT_COLUMNS, delimiter="\t")
        writer.writeheader()
        for result in results:
            writer.writerow(result.report_row())


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
        help="daily stage: write the per-symbol TSV report (d2-v2 dry run measurement) to this path",
    )
    parser.add_argument(
        "--rewrite-digests",
        action="store_true",
        help="daily stage: write every 1d month digest at rule d2-v2 (content or rule differs)",
    )
    parser.add_argument(
        "--restore-snapshot",
        default=None,
        help="daily stage: rewrite --symbols' 1d rows from this gzip CSV snapshot (185-38 rollback)",
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
        rewrite_digests=args.rewrite_digests,
        restore_snapshot=args.restore_snapshot,
    )
    asyncio.run(writer.run())


if __name__ == "__main__":
    main()
