"""BarDerivation: the D2b derived 15m/1h grid writer (phase 185 plans 11 and 31, D-15)
and the D2 canonical 1d stage (phase 185 plan 17, D-06).

Grid stage. Oneshot batch. For each symbol it re-derives 15m and 1h bars from the symbol's
tradeable 5m bars on session-anchored edges (plan 06's aggregate_session_grid) and writes them by
the write contract (plan 185-31; data layer integrity design section 4,
src/intelligence/bars/write_contract.py). One transaction per symbol:

1. read the stored 15m/1h rows with their (vendor, kind), the grid's flags and the current
   digests;
   classify the derived rows against the stored derived rows by exact value (new, changed,
   unchanged, removed: a stored derived slot no longer derived);
2. a restatement is applied last-wins (D-191-O): (changed + removed) / stored derived rows above
   threshold.bar_integrity.max_revision_ratio over at least revision_ratio_min_stored stored
   rows only flags the load (revision_flags in its detail, a warning log); removed rows alone
   above that share refuse that one symbol (its ohlcv_load rows commit with outcome refused,
   nothing else is written). A refused or failed symbol never discards another symbol's writes:
   each symbol is its own transaction and the batch closes partial;
3. under SET LOCAL ROLE bar_derivation_writer: one ohlcv_load row per grid timeframe (source
   derived, outcome applied, the four counts);
4. a vendor 15m/1h row in canonical fails the symbol loud: vendor answers live in ohlcv_raw
   (phase 191 plan 08 deleted the archive-from-table step), and only this stage writes the grid
   timeframes;
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

Daily stage (plans 17 and 36; reads ohlcv_raw since phase 191 plan 08). Per symbol: load the
current raw 1d rows of Tradier consolidated and IBKR smart_trades (daily_rule.RAW_DAILY_SERIES;
the corpus import is told by its request's route), the 1d bar_source_policy rows (read once per run) and the
corporate_action_current splits with their evidence, and run the pure d2-v3 rule
(src/intelligence/bars/daily_rule.py): the source the policy row of each date names, IBKR as a
recorded head, a basis-tested interior fallback, or the basis-tested restated answer where the
Tradier primary answered only on a stale scale (data layer integrity design section 2 and the
Amendment 2026-10-07; plan 185-52). The canonical bars
are classified by the write contract against the stored 1d rows of every canonical
(vendor, kind) pair (CANONICAL_1D_SOURCES), with
removal inside the name's derived span (its first to last raw date). A dry run (the default)
writes nothing and reports per name (--report writes a TSV). The apply path, one transaction per
symbol under SET LOCAL ROLE bar_derivation_writer: one ohlcv_load row (source derived, outcome
applied or refused, the four counts), old values of changed and removed rows to ohlcv_revision
(origin load), removed rows deleted by key, new rows inserted, changed rows upserted (the changed
set only, never a raw UPDATE of the compressed hypertable), and the fallback_seam,
pre_split_unrefetched and no_provider_volume flags through bar_scrub's write_flags; then one
scrub_symbols call over the run's symbols and write_1d_digests at RULE_VERSION. A revision ratio
above threshold.bar_integrity.max_revision_ratio over at least revision_ratio_min_stored stored
rows is applied and flagged (revision_flag in the load detail, a warning log; D-191-O, vendor
restatements are last-wins). Removed rows alone above that share refuse the symbol (only its
refused load row commits) unless a corporate action or a 1d
bar_source_policy row was recorded or closed (closed_at, migration 460) after the symbol's
previous applied daily load, or no such load exists. A refused or failed symbol is recorded and
the batch closes partial; other symbols' writes stand. --changed-only skips a symbol with no
answer, corporate action or policy record or close after that same per-symbol baseline. A held
name (bar_hold_current, services/bar_hold.py; plan 185-51) is skipped whatever the scope: its
report row has outcome held, the cause and zero counts, and nothing is read or written for it. No
canonical_bar_lineage row is written (185-38 replaced the table with the
lineage view and made this stage the single 1d writer).
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
from services.bar_hold import held as read_held
from services.bar_scrub import FlagRow, scrub_symbols, write_flags
from src.config.settings import Settings
from src.core.agent.base_batch import BaseBatch
from src.intelligence.bars.daily_rule import (
    FLAG_FALLBACK_SEAM,
    FLAG_NO_VOLUME,
    FLAG_PRE_SPLIT,
    RAW_DAILY_SERIES,
    RULE_VERSION,
    DailyV2Result,
    PolicyRow,
    derive_daily_v2,
    observation_from_raw,
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
from src.intelligence.bars.vendor_kind import label_to_vendor_kind
from src.intelligence.bars.write_contract import (
    BarValues,
    WriteDelta,
    classify,
    refuse_removal,
    revision_flagged,
    revision_ratio,
)
from src.observability.metrics import counter
from src.observability.otel import OTelInitError, init_otel_providers

_JOB = "bar-derivation"
# Per-run outcomes, labeled {stage, outcome} only: never per symbol (cardinality);
# per-symbol detail (failures, outside-session drops) stays in the log.
_OUTCOME_TOTAL = counter(
    "bar_derivation_outcome_total",
    "bar_derivation per-run outcome counts: symbols derived, skipped unchanged by "
    "--changed-only, skipped with no tradeable 5m, refused and "
    "failed. Never labeled by symbol.",
)
_WRITER_ROLE_SQL = "SET LOCAL ROLE bar_derivation_writer"
_CONSTITUENT_RULE = "constituent_flag"
# A derived bar whose constituent 5m slot is neither stored nor inside an
# answered SMART TRADES request window (todo 462): the hole stops at the
# derivation edge as a quarantine-false flag, never silently as a complete bar.
_PARTIAL_RULE = "partial_constituents"
_GRID_TF_LIST = sorted(GRID_TIMEFRAMES)
# The derived grid's canonical identity (derived, 5m_grid), derived once from the label map.
_DERIVED_PAIR = label_to_vendor_kind(SOURCE_DERIVED_5M)
# The two ANY arrays every canonical 1d read filters on (plan 191-13): the vendors and kinds of
# CANONICAL_1D_SOURCES, zipped nowhere (a pair is admitted only when both sides match a stored
# row's own vendor and kind; the cross product holds no canonical rows).
_1D_VENDORS = tuple(sorted({vendor for vendor, _kind in CANONICAL_1D_SOURCES}))
_1D_KINDS = tuple(sorted({kind for _vendor, kind in CANONICAL_1D_SOURCES}))
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
_GRID_OUTCOMES = ("derived", "unchanged", "no_5m", "refused", "failed")
_GRID_ROW_COUNTS = (
    "rows_new",
    "rows_changed",
    "rows_unchanged",
    "rows_removed",
)
_SESSION_MARGIN_DAYS = 3
# The gap planner's request-to-load match window (scripts/infrastructure/backfill/_d1_gaps.py);
# required, never defaulted: a missing key fails the run.
_MATCH_S_KEY = "infra.selection_gate.request_load_match_s"

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
# counts only when the answering vendor holds a raw 5m row in its window (a lost
# chunk must not make a window look covered), and never when the contract refused
# the load that persisted it (todo 535 item 26: the gap planner's rule, finding 3 of
# the third 191-07 review, in scripts/infrastructure/backfill/_d1_gaps.py; a load
# persists the latest request of its series answered at most $5 seconds earlier,
# APR infra.selection_gate.request_load_match_s).
_SELECT_ANSWERED_WINDOWS_SQL = """
SELECT r.window_start, r.window_end
FROM ohlcv_request r
WHERE r.symbol = $1 AND r.timeframe = '5m' AND r.route = $3
  AND r.what_to_show = $4 AND r.outcome = ANY($2::text[])
  AND r.window_start IS NOT NULL
  AND (
    r.outcome = 'no_data'
    OR EXISTS (
      SELECT 1 FROM ohlcv_raw m
      WHERE m.symbol = r.symbol AND m.timeframe = r.timeframe AND m.vendor = r.source
        AND m."timestamp" >= r.window_start AND m."timestamp" < r.window_end
    )
  )
  AND NOT EXISTS (
    SELECT 1 FROM ohlcv_load l
    WHERE l.symbol = r.symbol AND l.timeframe = r.timeframe AND l.source = r.source
      AND l.outcome = 'refused' AND l.loaded_at >= r.answered_at
      AND l.loaded_at <= r.answered_at + make_interval(secs => $5)
      AND NOT EXISTS (
        SELECT 1 FROM ohlcv_request q
        WHERE q.symbol = r.symbol AND q.timeframe = r.timeframe AND q.source = r.source
          AND q.answered_at > r.answered_at AND q.answered_at <= l.loaded_at
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

# The stored 15m/1h rows of a symbol, vendor and derived, with their (vendor, kind): the
# write contract's "stored" side (read inside the symbol's transaction on --apply).
_SELECT_STORED_GRID_SQL = """
/* stored_grid */
SELECT timeframe, "timestamp", open, high, low, close, volume, vendor, kind
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

_INSERT_BAR_SQL = """
INSERT INTO market_data_ohlcv
    ("timestamp", symbol, timeframe, open, high, low, close, volume, vendor, kind, base)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
"""

# The changed set only, the daily stage's idiom: a raw UPDATE of the compressed hypertable is
# fenced (test_compressed_hypertable_write_boundary.py).
_UPSERT_DERIVED_SQL = """
INSERT INTO market_data_ohlcv
    ("timestamp", symbol, timeframe, open, high, low, close, volume, vendor, kind, base)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
ON CONFLICT ("timestamp", symbol, timeframe) DO UPDATE SET
    open = EXCLUDED.open,
    high = EXCLUDED.high,
    low = EXCLUDED.low,
    close = EXCLUDED.close,
    volume = EXCLUDED.volume,
    vendor = EXCLUDED.vendor,
    kind = EXCLUDED.kind
"""

_INSERT_LOAD_REVISION_SQL = """
INSERT INTO ohlcv_revision
    (load_id, symbol, timeframe, "timestamp", old_open, old_high, old_low, old_close,
     old_volume, old_source, origin, vendor, kind)
VALUES ($1::uuid, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
"""

# Stale derived rows by key; the literal range ahead of ANY() keeps chunk exclusion on the
# compressed hypertable (gotchas, todo 356).
_DELETE_STALE_DERIVED_SQL = """
/* delete_stale_derived */
DELETE FROM market_data_ohlcv
WHERE symbol = $1 AND timeframe = $2 AND vendor = 'derived'
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
_RAW_DAILY_VENDORS = [vendor for vendor, _kind in RAW_DAILY_SERIES]
_RAW_DAILY_KINDS = [kind for _vendor, kind in RAW_DAILY_SERIES]
_DAILY_OUTCOMES = ("derived", "unchanged", "no_observations", "refused", "failed", "held")
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
    "revision_flag",
    "would_refuse",
    "waived",
    "error",
    "held",
    "restated",
)

_DISCOVER_DAILY_SYMBOLS_SQL = """
SELECT symbol FROM instruments
WHERE is_active AND compute_eligible_1d
ORDER BY symbol
"""

# The current raw 1d rows of the d2-v3 series ($2 vendors, $3 kinds, zipped pairwise:
# daily_rule.RAW_DAILY_SERIES). The request join keeps test fixtures out: a value first served
# by a request whose caller starts 'test-' never becomes a canonical bar (2026-10-03: fixture
# rows on SPY 2024-01-02 to 01-04 would have replaced closes of 472 with 100.5). A row with no
# request (a legacy migrated row) is no test row. legacy marks the corpus import.
_SELECT_DAILY_RAW_SQL = """
SELECT r.request_id::text AS request_id, r.vendor, r.kind,
       (r."timestamp" AT TIME ZONE 'UTC')::date AS bar_date,
       r.open, r.high, r.low, r.close, r.volume, r.served_at,
       COALESCE(q.route = 'LEGACY_IMPORT', false) AS legacy
FROM ohlcv_raw r
JOIN unnest($2::text[], $3::text[]) AS s(vendor, kind)
  ON s.vendor = r.vendor AND s.kind = r.kind
LEFT JOIN ohlcv_request q ON q.request_id = r.request_id
WHERE r.symbol = $1 AND r.timeframe = '1d'
  AND (q.caller IS NULL OR q.caller NOT LIKE 'test-%')
ORDER BY r."timestamp", r.vendor, r.kind
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

# The write contract's stored side: every canonical 1d (vendor, kind) pair
# ($2 = _1D_VENDORS, $3 = _1D_KINDS, both from CANONICAL_1D_SOURCES).
_SELECT_STORED_1D_SQL = """
/* stored_1d */
SELECT "timestamp", open, high, low, close, volume, vendor, kind, base
FROM market_data_ohlcv
WHERE symbol = $1 AND timeframe = '1d' AND vendor = ANY($2::text[]) AND kind = ANY($3::text[])
ORDER BY "timestamp"
"""

# The 1d digest's content: stored rows of every canonical 1d (vendor, kind) pair ($2/$3 as
# _SELECT_STORED_1D_SQL).
_SELECT_DIGEST_1D_SQL = """
SELECT "timestamp", open, high, low, close, volume
FROM market_data_ohlcv
WHERE symbol = $1 AND timeframe = '1d' AND vendor = ANY($2::text[]) AND kind = ANY($3::text[])
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

# The symbol's baseline: when the daily stage last read the inputs it applied, the start of the
# batch that wrote its latest applied daily load (the policy is read once at run start, the
# observations before the write), else that load's loaded_at (a load with no batch). No row
# when the symbol has no applied daily load. Only the daily stage's own loads count. A
# completed batch over other symbols never moves it (plan 185-50: the 38-name batch of 185-49
# finished after the FTV, IP and STE closes and hid them under a global watermark).
_LAST_DAILY_LOAD_CTE = """
last_load AS (
    SELECT COALESCE(b.started_at, l.loaded_at) AS at
    FROM ohlcv_load l
    LEFT JOIN bar_derivation_batch b ON b.batch_id = l.batch_id
    WHERE l.symbol = $1 AND l.timeframe = '1d' AND l.source = 'derived'
      AND l.outcome = 'applied' AND l.caller = 'bar_derivation-daily'
    ORDER BY l.loaded_at DESC
    LIMIT 1
)"""

# When a 1d policy row last changed: its insert (recorded_at) or its close (closed_at, stamped
# by the append-only trigger since migration 460; NULL on rows closed before it, which then
# count as changed at recorded_at only). GREATEST ignores NULL. Format with p = the alias.
_POLICY_CHANGED_AT = "GREATEST({p}.recorded_at, {p}.closed_at)"

# --changed-only: a symbol is due when a raw value of its d2-v3 series was served (served_at moves
# only when the value changes, and the rule reads nothing else of a serve), or a corporate action
# or a 1d source policy row (the symbol's or the default) was recorded or closed, after its
# baseline. $2/$3 as _SELECT_DAILY_RAW_SQL.
_SELECT_DAILY_CHANGED_SINCE_SQL = f"""
/* changed_since */
WITH {_LAST_DAILY_LOAD_CTE}
SELECT EXISTS (
    SELECT 1 FROM ohlcv_raw r
    JOIN unnest($2::text[], $3::text[]) AS s(vendor, kind)
      ON s.vendor = r.vendor AND s.kind = r.kind
    LEFT JOIN ohlcv_request q ON q.request_id = r.request_id
    WHERE r.symbol = $1 AND r.timeframe = '1d'
      AND (q.caller IS NULL OR q.caller NOT LIKE 'test-%')
) AS has_obs,
EXISTS (
    SELECT 1 FROM ohlcv_raw r
    JOIN unnest($2::text[], $3::text[]) AS s(vendor, kind)
      ON s.vendor = r.vendor AND s.kind = r.kind
    WHERE r.symbol = $1 AND r.timeframe = '1d'
      AND r.served_at > COALESCE((SELECT at FROM last_load), '-infinity'::timestamptz)
) AS obs_since,
EXISTS (
    SELECT 1 FROM corporate_action_current c
    WHERE c.symbol = $1
      AND c.recorded_at > COALESCE((SELECT at FROM last_load), '-infinity'::timestamptz)
) AS action_since,
EXISTS (
    SELECT 1 FROM bar_source_policy p
    WHERE p.timeframe = '1d' AND (p.symbol = $1 OR p.symbol IS NULL)
      AND {_POLICY_CHANGED_AT.format(p='p')}
          > COALESCE((SELECT at FROM last_load), '-infinity'::timestamptz)
) AS policy_since
"""

# The revision-ratio waiver: no applied daily load yet, or a corporate action or a 1d policy
# row (the symbol's or the default) recorded or closed after the symbol's baseline
# (_LAST_DAILY_LOAD_CTE), or a snapshot restore (plan 185-38) after it: the restore is a
# recorded operator rollback, and the re-derivation that follows re-applies the reviewed state.
# Narrow on purpose: a vendor revision on a name with no such record stays refused.
_SELECT_REVISION_WAIVER_SQL = f"""
/* revision_waiver */
WITH {_LAST_DAILY_LOAD_CTE}
SELECT (SELECT at FROM last_load) IS NULL
    OR EXISTS (SELECT 1 FROM corporate_action c, last_load l
               WHERE c.symbol = $1 AND c.recorded_at > l.at)
    OR EXISTS (SELECT 1 FROM bar_source_policy p, last_load l
               WHERE p.timeframe = '1d' AND (p.symbol = $1 OR p.symbol IS NULL)
                 AND {_POLICY_CHANGED_AT.format(p='p')} > l.at)
    OR EXISTS (SELECT 1 FROM ohlcv_load r, last_load l
               WHERE r.symbol = $1 AND r.timeframe = '1d' AND r.source = 'derived'
                 AND r.outcome = 'applied' AND r.caller = 'bar_derivation-restore'
                 AND r.loaded_at > l.at)
"""

# Native upsert, 185-01 measurement b; the changed set only.
_UPSERT_1D_SQL = """
INSERT INTO market_data_ohlcv
    ("timestamp", symbol, timeframe, open, high, low, close, volume, vendor, kind, base)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
ON CONFLICT ("timestamp", symbol, timeframe) DO UPDATE SET
    open = EXCLUDED.open,
    high = EXCLUDED.high,
    low = EXCLUDED.low,
    close = EXCLUDED.close,
    volume = EXCLUDED.volume,
    vendor = EXCLUDED.vendor,
    kind = EXCLUDED.kind
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
    revision_flag: bool = False
    would_refuse: bool = False
    waived: bool | None = None
    held: str = ""
    restated: int = 0

    def report_row(self) -> dict[str, str]:
        values: dict[str, Any] = {
            **{name: getattr(self, name) for name in _DAILY_REPORT_COLUMNS if hasattr(self, name)},
            "refused_interior": len(self.refused_dates),
            "refused_dates": ",".join(d.isoformat() for d in self.refused_dates),
            "revision_ratio": f"{self.revision_ratio:.6f}",
            "revision_flag": str(self.revision_flag).lower(),
            "would_refuse": str(self.would_refuse).lower(),
            "waived": "" if self.waived is None else str(self.waived).lower(),
            "error": self.error or "",
        }
        return {name: str(values[name]) for name in _DAILY_REPORT_COLUMNS}


def _stored_group(vendors: set[str]) -> str:
    """Which vendors a name's stored 1d rows come from before the run."""
    if not vendors:
        return "none"
    if "tradier" not in vendors:
        return "ibkr_only"
    return "tradier_only" if vendors == {"tradier"} else "mixed"


def _batch_status(failed: list[str], n_written: int) -> str:
    """Per-name isolation (D-191-O): a failed or refused name never fails the names that wrote.

    completed: nothing failed; partial: some names failed and at least one wrote; failed:
    names failed and none wrote.
    """
    if not failed:
        return "completed"
    return "partial" if n_written else "failed"


def _utc_day(day: date) -> datetime:
    return datetime(day.year, day.month, day.day, tzinfo=UTC)


@dataclass(frozen=True)
class _GridPlan:
    """The write contract applied to one symbol's grid: what the transaction will write."""

    deltas: dict[str, WriteDelta[int]]
    n_stored_derived: dict[str, int]
    n_vendor: dict[str, int]
    refusals: tuple[str, ...]
    revision_flags: tuple[str, ...]
    flag_writes: list[tuple[tuple[str, int, str], dict[str, Any]]]
    flag_deletes: list[tuple[str, int, str]]
    digest_writes: list[tuple[str, datetime, datetime, str, int]]

    def result(self, symbol: str, n_derived: int) -> _SymbolResult:
        counts = {
            "rows_new": sum(len(d.new) for d in self.deltas.values()),
            "rows_changed": sum(len(d.changed) for d in self.deltas.values()),
            "rows_unchanged": sum(d.unchanged for d in self.deltas.values()),
            "rows_removed": sum(len(d.removed) for d in self.deltas.values()),
        }
        if self.refusals:
            error = f"{symbol}: refused: {'; '.join(self.refusals)}"
            return _SymbolResult("refused", error, n_derived, **counts)
        return _SymbolResult("derived", None, n_derived, **counts)


def _vendor_rows_error(symbol: str, plan: _GridPlan) -> str:
    """A vendor 15m/1h row in canonical is a defect: vendor answers live in ohlcv_raw and the
    grid timeframes are derivation-owned (DERIVATION_OWNED_TIMEFRAMES); the stage stops loud
    rather than overwrite or delete a row it did not write (phase 191 plan 08)."""
    found = ", ".join(f"{tf} {n}" for tf, n in plan.n_vendor.items() if n)
    return (
        f"{symbol}: vendor rows in canonical derivation-owned timeframes ({found}); "
        "no writer but bar_derivation may write 15m/1h canonical rows"
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

    Content is read back from the stored rows of every canonical 1d (vendor, kind) pair
    (CANONICAL_1D_SOURCES, so a Tradier-owned name digests its Tradier bars), with
    each row's non-quarantine flag rules beside it (the grid convention). Callers
    run it after their scrub so the flags it adds or clears are in the digest.
    The daily stage's writer (daily_rule.RULE_VERSION). force_rule_version also writes a month
    whose content is unchanged but whose current digest carries another rule version (the
    185-38 cutover and the 185-52 d2-v3 bump relabel every month). write=False counts without inserting. Returns the number
    of rows inserted (or that would be).
    """
    rows = await conn.fetch(_SELECT_DIGEST_1D_SQL, symbol, list(_1D_VENDORS), list(_1D_KINDS))
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
        self._report_path = report_path
        self._rewrite_digests = rewrite_digests
        self._restore_snapshot = restore_snapshot
        self._match_s = 0.0  # read from APR at the grid run's start
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
                conn, ["infra.bar_derivation.%", "threshold.bar_integrity.%", _MATCH_S_KEY]
            )
            if _MATCH_S_KEY not in apr:
                raise RuntimeError(f"{_MATCH_S_KEY} missing from config_state")
            self._match_s = float(apr[_MATCH_S_KEY])
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
            targets = (
                list(self._symbols)
                if self._symbols
                else [r[0] for r in await conn.fetch(_DISCOVER_SYMBOLS_SQL)]
            )

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
                        status=_batch_status(failed, totals["derived"]),
                        detail={
                            "totals": {k: n for k, n in totals.items() if n},
                            "failed": failed,
                            "n_derived_rows": n_derived_rows,
                            "rows": rows,
                            "apply": self._apply,
                            "changed_only": self._changed_only,
                        },
                    )

        self.logger.info(
            "bar_derivation.done",
            stage=self._stage,
            symbols=len(targets),
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
            self._match_s,
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
            if (r["vendor"], r["kind"]) == _DERIVED_PAIR:
                stored_derived[tf][_epoch_seconds(r["timestamp"])] = (
                    r["open"],
                    r["high"],
                    r["low"],
                    r["close"],
                    r["volume"],
                    r["vendor"],
                    r["kind"],
                )
            else:
                n_vendor[tf] += 1
        deltas: dict[str, WriteDelta[int]] = {}
        refusals: list[str] = []
        revision_flags: list[str] = []
        for tf in _GRID_TF_LIST:
            stored = stored_derived[tf]
            delta = classify(derived_values[tf], stored, removal_scope=stored.keys())
            deltas[tf] = delta
            counts = (
                f"({len(delta.changed)} changed + {len(delta.removed)} removed of "
                f"{len(stored)} stored) > {limits.max_ratio}"
            )
            if revision_flagged(delta, len(stored), limits.max_ratio, min_stored=limits.min_stored):
                revision_flags.append(
                    f"{tf} revision ratio {revision_ratio(delta, len(stored)):.4f} {counts}"
                )
            if refuse_removal(
                delta, len(stored), limits.max_ratio, min_stored=limits.min_stored, waived=False
            ):
                refusals.append(f"{tf} removal {counts}")

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
            revision_flags=tuple(revision_flags),
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
                int(ts): (float(o), float(h), float(lo), float(c), int(v), *_DERIVED_PAIR)
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
            if sum(plan.n_vendor.values()):
                return _SymbolResult("failed", _vendor_rows_error(symbol, plan), 0)
            return plan.result(symbol, n_derived)

        assert batch_id is not None  # --apply always opens a batch
        try:
            async with conn.transaction():
                plan = await self._plan_grid(conn, **planning)
                if sum(plan.n_vendor.values()):
                    raise _SymbolFailure(_vendor_rows_error(symbol, plan))
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
                                "revision_flags": list(plan.revision_flags),
                            }
                        ),
                        _GRID_LOAD_CALLER,
                        batch_id,
                        _GRID_LOAD_DESTINATION,
                    )
                if plan.refusals:
                    # The load rows are the recorded finding; nothing else is written.
                    return plan.result(symbol, n_derived)
                if plan.revision_flags:
                    self.logger.warning(
                        "bar_derivation.revision_flag",
                        stage=self._stage,
                        symbol=symbol,
                        flags=list(plan.revision_flags),
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
        return plan.result(symbol, n_derived)

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
            # New revision rows carry the composite "vendor/kind" token in old_source (the D2
            # digest rule token); historical rows keep their labels.
            return (
                load_ids[tf],
                symbol,
                tf,
                datetime.fromtimestamp(ts, tz=UTC),
                *old[:5],
                f"{old[5]}/{old[6]}",
                "load",
                old[5],
                old[6],
            )

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

    # --- D2 daily stage (plans 17, 36 and 52; d2-v3) ----------------------

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
            params = await read_daily_params(conn, apr)
            targets = (
                list(self._symbols)
                if self._symbols
                else [r[0] for r in await conn.fetch(_DISCOVER_DAILY_SYMBOLS_SQL)]
            )
            # Held names (services/bar_hold.py, plan 185-51): skipped scoped or not, so no run
            # applies a rewrite a decision is still pending on. Read once per run.
            holds = await read_held(conn, "1d")

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
                        if symbol in holds:
                            cause = "; ".join(h.cause() for h in holds[symbol])
                            self.logger.warning(
                                "bar_derivation.daily_held", symbol=symbol, cause=cause
                            )
                            result = _DailyResult(symbol, "held", held=cause)
                        else:
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
                        status=_batch_status(failed, totals["derived"]),
                        detail={
                            "totals": {k: n for k, n in totals.items() if n},
                            "rows": rows,
                            "failed": failed,
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
            symbols=len(targets),
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
        # observation load and the derivation for symbols with nothing new since their own last
        # applied daily load (_LAST_DAILY_LOAD_CTE).
        probe = await conn.fetchrow(
            _SELECT_DAILY_CHANGED_SINCE_SQL, symbol, _RAW_DAILY_VENDORS, _RAW_DAILY_KINDS
        )
        if not probe["has_obs"]:
            return _DailyResult(symbol, "no_observations")
        if self._changed_only and not (
            probe["obs_since"] or probe["action_since"] or probe["policy_since"]
        ):
            return _DailyResult(symbol, "unchanged")
        observations, splits = await read_daily_inputs(conn, symbol)
        if not observations:
            return _DailyResult(symbol, "no_observations")
        derived = derive_daily_v2(
            observations,
            params.policy,
            splits,
            symbol=symbol,
            basis_window_sessions=params.window,
            basis_tolerance_bp=params.tolerance_bp,
        )

        stored_rows = await conn.fetch(
            _SELECT_STORED_1D_SQL, symbol, list(_1D_VENDORS), list(_1D_KINDS)
        )
        stored: dict[date, BarValues] = {
            r["timestamp"].date(): (
                r["open"],
                r["high"],
                r["low"],
                r["close"],
                r["volume"],
                r["vendor"],
                r["kind"],
            )
            for r in stored_rows
        }
        # base is NULL on every 1d row today; the write carries the stored value if one exists.
        base = next((r["base"] for r in stored_rows if r["base"] is not None), None)
        incoming: dict[date, BarValues] = {
            b.bar_date: (b.open, b.high, b.low, b.close, b.volume, b.vendor, b.kind)
            for b in derived.bars
        }
        span_start = min(o.bar_date for o in observations)
        span_end = max(o.bar_date for o in observations)
        scope = [d for d in stored if span_start <= d <= span_end]
        delta = classify(incoming, stored, removal_scope=scope)
        ratio = revision_ratio(delta, len(stored))
        flagged = revision_flagged(
            delta, len(stored), params.limits.max_ratio, min_stored=params.limits.min_stored
        )
        would_refuse = refuse_removal(
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
                f"{symbol}: refused: {len(delta.removed)} removed of {len(stored)} stored rows "
                f"exceeds {params.limits.max_ratio} with no recorded corporate action or policy "
                "change since the last applied daily load"
                if refuse
                else None
            ),
            group=_stored_group({values[5] for values in stored.values()}),  # values[5] = vendor
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
            restated=len(derived.restated),
            revision_ratio=ratio,
            revision_flag=flagged,
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
                        "revision_flag": result.revision_flag,
                        "waived": result.waived,
                        "head": result.head,
                        "refused_head": [d.isoformat() for d in derived.refused_head],
                        "admitted_interior": result.admitted_interior,
                        "refused_interior": [d.isoformat() for d in result.refused_dates],
                        "stale_only": [d.isoformat() for d in derived.stale_only],
                        "restated": [d.isoformat() for d in derived.restated],
                    }
                ),
                _DAILY_LOAD_CALLER,
                batch_id,
                _GRID_LOAD_DESTINATION,
            )
            if result.outcome == "refused":
                return
            if result.revision_flag:
                self.logger.warning(
                    "bar_derivation.revision_flag",
                    stage=self._stage,
                    symbol=symbol,
                    revision_ratio=round(result.revision_ratio, 6),
                    changed=result.changed,
                    removed=result.removed,
                    n_stored=result.n_stored,
                )
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
        """Every 1d month digest of each symbol at the rule's version (185-38 step 5b, 185-52):
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
        stored_rows = await conn.fetch(
            _SELECT_STORED_1D_SQL, symbol, list(_1D_VENDORS), list(_1D_KINDS)
        )
        stored: dict[date, BarValues] = {
            r["timestamp"].date(): (
                r["open"],
                r["high"],
                r["low"],
                r["close"],
                r["volume"],
                r["vendor"],
                r["kind"],
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
    # ohlcv_revision is keyed by (vendor, kind) since plan 191-04; new rows carry the composite
    # "vendor/kind" token in old_source (the D2 digest rule token).
    olds = [(day, old) for day, (_new, old) in delta.changed.items()]
    olds += list(delta.removed.items())
    revisions = [
        (
            load_id,
            symbol,
            "1d",
            _utc_day(day),
            *old[:5],
            f"{old[5]}/{old[6]}",
            "load",
            old[5],
            old[6],
        )
        for day, old in olds
    ]
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
            # The snapshot predates the (vendor, kind) columns and carries the label; the map
            # restores it, so a pre-cutover snapshot stays restorable (plan 191-13).
            out.setdefault(row["symbol"], {})[day] = (
                float(row["open"]),
                float(row["high"]),
                float(row["low"]),
                float(row["close"]),
                int(row["volume"]) if row["volume"] != "" else None,
                *label_to_vendor_kind(row["source"]),
            )
    return out


class _DailyParams(NamedTuple):
    """The daily stage's per-run inputs: APR thresholds and the 1d policy rows."""

    window: int
    tolerance_bp: float
    limits: _RevisionLimits
    quarantine_rules: frozenset[str]
    policy: tuple[PolicyRow, ...]


async def read_daily_params(conn: Any, apr: dict) -> _DailyParams:
    """The daily stage's per-run inputs: APR thresholds and every 1d policy row."""
    return _DailyParams(
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


async def read_daily_inputs(conn: Any, symbol: str) -> tuple[list[Observation], list[SplitRecord]]:
    """The symbol's d2-v3 inputs: its current raw 1d rows of RAW_DAILY_SERIES as observations
    (daily_rule.observation_from_raw) and its current corporate actions."""
    rows = await conn.fetch(_SELECT_DAILY_RAW_SQL, symbol, _RAW_DAILY_VENDORS, _RAW_DAILY_KINDS)
    observations = [
        observation_from_raw(
            request_id=r["request_id"],
            vendor=r["vendor"],
            kind=r["kind"],
            bar_date=r["bar_date"],
            open=r["open"],
            high=r["high"],
            low=r["low"],
            close=r["close"],
            volume=r["volume"],
            served_at=r["served_at"],
            legacy=r["legacy"],
        )
        for r in rows
    ]
    if not observations:
        return [], []
    splits = [
        SplitRecord(
            effective_date=r["effective_date"],
            recorded_at=r["recorded_at"],
            factor=r["factor"],
            evidence_request_ids=tuple(r["evidence_request_ids"] or ()),
        )
        for r in await conn.fetch(_SELECT_DAILY_SPLITS_SQL, symbol)
    ]
    return observations, splits


def _daily_summary(results: list[_DailyResult]) -> dict[str, int]:
    """Run-level fallback and refusal counts (the batch detail and the dry run's return)."""
    return {
        "head": sum(r.head for r in results),
        "refused_head": sum(r.refused_head for r in results),
        "admitted_interior": sum(r.admitted_interior for r in results),
        "refused_interior": sum(len(r.refused_dates) for r in results),
        "stale_only": sum(r.stale_only for r in results),
        "restated": sum(r.restated for r in results),
        "revision_flag": sum(r.revision_flag for r in results),
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
        "answers, corporate actions or policy records or closes after the symbol's "
        "last applied daily load",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="write the replacement (default: dry run, compute and report only)",
    )
    parser.add_argument(
        "--report",
        default=None,
        help="daily stage: write the per-symbol TSV report (dry run measurement) to this path",
    )
    parser.add_argument(
        "--rewrite-digests",
        action="store_true",
        help="daily stage: write every 1d month digest at RULE_VERSION (content or rule differs)",
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
        report_path=args.report,
        rewrite_digests=args.rewrite_digests,
        restore_snapshot=args.restore_snapshot,
    )
    asyncio.run(writer.run())


if __name__ == "__main__":
    main()
