#!/usr/bin/env python3
"""infrastructure_run_tradier_daily.py - load daily history from Tradier into market_data_ohlcv.

Tradier is the primary 1d source (owner decision 2026-10-03, migration 438). One request returns a
name's whole history. A name keeps one daily source for its whole history: the load refuses a short
history (PEP, 2026-10-03), a history that starts after existing bars, and a reload that changes more
than infra.tradier.max_changed_bar_ratio of existing bars unless --rebase says the source change is
deliberate. Every attempt writes one ohlcv_load row; a changed canonical bar's old values go to
ohlcv_revision. Fetches run concurrently; writes are serial on one connection.

A refetch of a name already on Tradier whose changes are one constant close ratio across every
earlier overlapping bar (and nothing after them) is the vendor back-adjusting a split (plan 185-26):
the ratio is snapped with the seam rule (src/intelligence/bars/seams.py, corporate_actions.py,
threshold.seam.* APR), recorded in corporate_action (inferred_by tradier_refetch, the request id
as evidence, the load id in detail) and the history is accepted; ohlcv_revision keeps the old
scale. Any other change set above the gate stays gated and is never applied.

--nightly selects the nightly leg's names (plan 185-26): the default missing names plus every name
Tradier owns (TRADIER_OWNED_SQL), each refetched in full so vendor revisions and splits surface the
night they happen.

Every answer lands in D1 first (ohlcv_request/ohlcv_observation, source tradier, route TRADIER, raw
including null volume), beside IBKR's observations, so the two vendors compare by (symbol, date, source).
D1 elision (plan 185-27): a bar lands as an observation only when no non-test TRADIER observation
of its date exists or one of open, high, low, close, volume differs exactly from the latest one
(null volume compares as a value), so a nightly full-history refetch adds only the vendor's new
and revised bars, not the whole history again. The request row still records the full answer
(n_bars is the answer's length); the latest observation of every date stays the vendor's
current value, which is what every D1 reader takes. The canonical write is planned from the
fetched bars and upserts only the new and changed ones (market_data_ohlcv is compressed: each
write into a compressed chunk decompresses it).

The write path does what D2 does for IBKR names (plan 185-27). In the bar write's transaction,
under bar_derivation_writer, every stored Tradier bar of the name gets canonical_bar_lineage at
rule tradier-v1 naming the latest equal TRADIER observation of its date; a stored Tradier bar
with no equal observation aborts the load (recorded failed). A write run is one
bar_derivation_batch (stage tradier); after the fetch loop it reruns the D2a scrub over the
names it changed and writes fresh 1d content digests for every loaded name.

An accepted load also sets backfill_status.fetch_complete for the name's 1d through the one
writer of that flag (mark_fetch_complete in infrastructure_run_historical_pipeline.py, whose
EXISTS guard needs stored tradeable bars). The compute_1d promotion predicate requires it, so a
name onboarded through this loader needs no manual bookkeeping step before promotion.

--raw-only lands D1 and stops: every bar lands, no canonical write, no ohlcv_load row and no
batch, so D2 does not treat the name as Tradier-owned. Used to backfill raw Tradier for
comparison against IBKR.

Usage:
  python scripts/infrastructure/backfill/infrastructure_run_tradier_daily.py            # names with no 1d bars
  python scripts/infrastructure/backfill/infrastructure_run_tradier_daily.py --symbols AAPL,SPY [--rebase]
  python scripts/infrastructure/backfill/infrastructure_run_tradier_daily.py --nightly
Exit codes: 0 every name loaded; EXIT_REFUSED (4) some names refused or failed (recorded in
ohlcv_load, a finding, not an error); 1 a runtime error.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import asyncpg
import numpy as np
import psycopg
import structlog

project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from scripts.infrastructure.backfill.infrastructure_run_historical_pipeline import (
    mark_fetch_complete,
)
from services._batch_utils import load_apr_dict_async
from services.bar_derivation import write_1d_digests
from services.bar_derivation_batch import close_batch, open_batch
from services.bar_scrub import scrub_symbols
from services.ohlcv_observation_writer import AsyncObservationSink, new_fetch_run_id
from src.config.settings import get_settings
from src.core.database_manager import create_pool
from src.core.service_utils import setup_service_logging
from src.intelligence.bars.corporate_actions import SplitInference, infer_split
from src.intelligence.bars.seams import Seam
from src.intelligence.bars.sources import TRADIER_RULE_VERSION
from src.observability.metrics import JOB_COMPLETED_TOTAL, flush_and_shutdown_metrics
from src.providers.base import RequestRecord
from src.providers.tradier import SOURCE, DailyBar, TradierError, fetch_daily_history, make_client

logger = structlog.get_logger(__name__)

_CALLER = "tradier-daily-loader"
_VALUE_TOLERANCE = 1e-9
_INFERRED_BY = "tradier_refetch"
# Some names refused or failed: recorded in ohlcv_load and reported by the D7 audit, a finding
# the nightly does not fail on. Distinct from 1 (an uncaught runtime error) and 2 (argparse).
EXIT_REFUSED = 4

# A name Tradier owns: some daily load of it was accepted. D2 (services/bar_derivation.py
# tradier_owned) and the nightly's IBKR 1d skip use the same predicate; a later refused load
# (gated, short_history, failed) does not hand the name back to IBKR, so its stored bars stay.
TRADIER_OWNED_SQL = (
    "EXISTS (SELECT 1 FROM ohlcv_load l WHERE l.symbol = {col} AND l.outcome = 'loaded')"
)

# The systemd unit's %n suffix (indicagent-tradier-daily.service, plan 189-06): the D-06
# job_completed_total label. The nightly ran this leg until the 189 cutover; the unit is its
# own caller now.
JOB = "tradier-daily"
_NIGHTLY_ENABLED_KEY = "infra.tradier.nightly_enabled"
_TRUTHY = ("true", "1", "t", "yes")


def nightly_enabled(apr: dict[str, str]) -> bool:
    """The operator switch for the --nightly leg (migration 440). A missing key raises: the
    migration seeds it, and a silent default would hide a lost switch."""
    return str(apr[_NIGHTLY_ENABLED_KEY]).strip().lower() in _TRUTHY


def job_status(returncode: int) -> str:
    """job_completed_total status for an exit code: refusals are findings, not failures."""
    if returncode == 0:
        return "success"
    if returncode == EXIT_REFUSED:
        return "partial"
    return "failure"


# (open, high, low, close, volume, source) of one stored bar
StoredBar = tuple[float, float, float, float, int, str]


@dataclass(frozen=True)
class LoadParams:
    min_session_ratio: float
    first_date_tolerance_days: int
    max_changed_bar_ratio: float
    rebase: bool
    # threshold.seam.rel_tol, threshold.seam.min_run, threshold.seam.ratio_snap_tol
    split_rel_tol: float
    split_min_run: int
    ratio_snap_tol: float


@dataclass
class LoadPlan:
    outcome: str  # loaded | short_history | no_data | gated
    detail: str | None
    bars: list[DailyBar] = field(default_factory=list)
    revisions: list[tuple[datetime, StoredBar]] = field(default_factory=list)
    n_new: int = 0
    n_changed: int = 0
    n_orphan: int = 0  # existing bars on dates Tradier does not have
    first_bar: date | None = None
    split: SplitInference | None = None  # a vendor back-adjustment the refetch carried
    # The bars the canonical upsert carries: new dates and changed bars only (plan 185-27).
    writes: list[DailyBar] = field(default_factory=list)


def _differs(bar: DailyBar, stored: StoredBar) -> bool:
    o, h, lo, c, v, _ = stored
    return (
        any(
            abs(a - b) > _VALUE_TOLERANCE * max(1.0, abs(b))
            for a, b in ((bar.open, o), (bar.high, h), (bar.low, lo), (bar.close, c))
        )
        or bar.volume != v
    )


def _refetch_split(
    overlap: list[tuple[DailyBar, StoredBar, bool]], params: LoadParams
) -> SplitInference | None:
    """The split a same-source refetch carries, or None.

    overlap is (fresh bar, stored bar, changed) in date order. A split back-adjusts every bar
    before its ex-date by one ratio: the changed bars must be exactly a prefix of the overlap
    (at least split_min_run long), all stored by Tradier, and their stored/fresh close ratio
    must stay within split_rel_tol of itself and snap to a rational p/q (infer_split). The
    effective date is the last changed bar, the last day stored on the old scale.
    """
    n_changed = sum(1 for _, _, changed in overlap if changed)
    if n_changed < params.split_min_run or not all(c for _, _, c in overlap[:n_changed]):
        return None
    prefix = overlap[:n_changed]
    if any(stored[5] != SOURCE for _, stored, _ in prefix):
        return None
    ratios = []
    for bar, stored, _ in prefix:
        if not (bar.close > 0 and stored[3] > 0):
            return None
        ratios.append(stored[3] / bar.close)
    if max(ratios) / min(ratios) - 1.0 > params.split_rel_tol:
        return None
    factor = float(np.median(ratios))
    seam = Seam(
        start=prefix[0][0].timestamp.date(),
        end=prefix[-1][0].timestamp.date(),
        factor=factor,
        n_days=len(prefix),
        max_rel_dev=float(max(abs(r / factor - 1.0) for r in ratios)),
    )
    return infer_split(seam, ratio_snap_tol=params.ratio_snap_tol)


def plan_symbol_load(
    fetched: list[DailyBar], existing: dict[datetime, StoredBar], params: LoadParams
) -> LoadPlan:
    """Decide one name's load from its Tradier bars and its stored non-placeholder 1d bars."""
    if not fetched:
        return LoadPlan("no_data", "Tradier returned no bars")
    # volume is NOT NULL in market_data_ohlcv and a missing value is never filled: drop the bar.
    bars = [bar for bar in fetched if bar.volume is not None]
    n_dropped = len(fetched) - len(bars)
    if not bars:
        return LoadPlan("no_data", f"all {len(fetched)} bars had null volume")
    first, last = bars[0].timestamp.date(), bars[-1].timestamp.date()
    weekdays = int(np.busday_count(first, last + timedelta(days=1)))
    ratio = len(bars) / weekdays
    if ratio < params.min_session_ratio:
        return LoadPlan(
            "short_history",
            f"{len(bars)} bars over {weekdays} weekdays ({ratio:.3f} < {params.min_session_ratio})",
        )
    if existing:
        earliest = min(existing).date()
        if first > earliest + timedelta(days=params.first_date_tolerance_days):
            return LoadPlan(
                "short_history",
                f"Tradier starts {first}, existing bars start {earliest} "
                f"(tolerance {params.first_date_tolerance_days} d)",
            )
    revisions: list[tuple[datetime, StoredBar]] = []
    overlap: list[tuple[DailyBar, StoredBar, bool]] = []
    writes: list[DailyBar] = []
    n_new = 0
    for bar in bars:
        stored = existing.get(bar.timestamp)
        if stored is None:
            n_new += 1
            writes.append(bar)
            continue
        changed = _differs(bar, stored) or stored[5] != SOURCE
        overlap.append((bar, stored, changed))
        if changed:
            revisions.append((bar.timestamp, stored))
            writes.append(bar)
    n_overlap = len(overlap)
    changed_ratio = len(revisions) / n_overlap if n_overlap else 0.0
    detail = f"{n_dropped} null-volume bars dropped" if n_dropped else None
    split = None
    if changed_ratio > params.max_changed_bar_ratio and not params.rebase:
        split = _refetch_split(overlap, params)
    if split is not None:
        split_note = f"{split.kind} {split.factor:g} effective {split.effective_date} (refetch)"
        detail = f"{detail}; {split_note}" if detail else split_note
    elif changed_ratio > params.max_changed_bar_ratio and not params.rebase:
        return LoadPlan(
            "gated",
            f"{len(revisions)} of {n_overlap} existing bars change ({changed_ratio:.3f} > "
            f"{params.max_changed_bar_ratio}); pass --rebase for a deliberate source change",
        )
    returned = {bar.timestamp for bar in bars}
    n_orphan = sum(1 for ts in existing if ts not in returned)
    return LoadPlan(
        "loaded", detail, bars, revisions, n_new, len(revisions), n_orphan, first, split, writes
    )


# (open, high, low, close, volume) of the latest TRADIER observation of one date
ObservedBar = tuple[float, float, float, float, int | None]


def d1_bars_to_land(bars: list[DailyBar], latest: dict[date, ObservedBar]) -> list[DailyBar]:
    """The answer's bars D1 does not already hold as its latest TRADIER observation.

    A bar lands when its date has no observation or any of open, high, low, close, volume
    differs exactly from the latest one (null volume compares as a value). Exact on purpose: D1
    is the raw record, so any vendor revision, however small, is kept. An empty map (a first
    load) lands every bar.
    """
    return [
        bar
        for bar in bars
        if latest.get(bar.timestamp.date()) != (bar.open, bar.high, bar.low, bar.close, bar.volume)
    ]


_SELECT_EXISTING_SQL = """
SELECT "timestamp", open, high, low, close, volume, source
FROM market_data_ohlcv
WHERE symbol = $1 AND timeframe = '1d'
"""

_SELECT_MISSING_SQL = """
SELECT i.symbol FROM instruments i
WHERE i.is_active AND i.contract_details->>'asset_class' = 'equity'
  AND NOT EXISTS (SELECT 1 FROM market_data_ohlcv m
                  WHERE m.symbol = i.symbol AND m.timeframe = '1d')
  AND NOT EXISTS (SELECT 1 FROM ohlcv_load l WHERE l.symbol = i.symbol AND l.outcome = 'loaded')
ORDER BY i.symbol
"""

# The nightly leg (plan 185-26): the missing names above plus every name Tradier owns.
_SELECT_NIGHTLY_SQL = f"""
SELECT i.symbol FROM instruments i
WHERE i.is_active AND i.contract_details->>'asset_class' = 'equity'
  AND ({TRADIER_OWNED_SQL.format(col="i.symbol")}
       OR NOT EXISTS (SELECT 1 FROM market_data_ohlcv m
                      WHERE m.symbol = i.symbol AND m.timeframe = '1d'))
ORDER BY i.symbol
"""

_SELECT_NO_RAW_SQL = """
SELECT i.symbol FROM instruments i
WHERE i.is_active AND i.contract_details->>'asset_class' = 'equity'
  AND NOT EXISTS (SELECT 1 FROM ohlcv_request r
                  WHERE r.symbol = i.symbol AND r.source = 'tradier' AND r.outcome = 'bars')
ORDER BY i.symbol
"""

_INSERT_LOAD_SQL = """
INSERT INTO ohlcv_load (load_id, symbol, timeframe, source, requested_start, requested_end, outcome,
                        n_bars, n_new, n_changed, first_bar, last_bar, detail, caller)
VALUES ($1, $2, '1d', $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
"""

_INSERT_REVISION_SQL = """
INSERT INTO ohlcv_revision (load_id, symbol, timeframe, "timestamp", old_open, old_high, old_low,
                            old_close, old_volume, old_source)
VALUES ($1, $2, '1d', $3, $4, $5, $6, $7, $8, $9)
"""

# Written under bar_derivation_writer, the role that owns corporate_action (migration 400).
_INSERT_SPLIT_SQL = f"""
INSERT INTO corporate_action
    (symbol, action_type, effective_date, factor, inferred_by, evidence_request_ids, detail)
VALUES ($1, $2, $3, $4, '{_INFERRED_BY}', $5::uuid[], $6::jsonb)
"""

# Carries only the plan's new and changed bars (LoadPlan.writes, plan 185-27).
_UPSERT_SQL = """
INSERT INTO market_data_ohlcv ("timestamp", symbol, timeframe, open, high, low, close, volume, source)
VALUES ($1, $2, '1d', $3, $4, $5, $6, $7, $8)
ON CONFLICT ("timestamp", symbol, timeframe) DO UPDATE SET
    open = EXCLUDED.open, high = EXCLUDED.high, low = EXCLUDED.low, close = EXCLUDED.close,
    volume = EXCLUDED.volume, source = EXCLUDED.source
"""


# The latest non-test TRADIER observation of each date (D1 elision, plan 185-27). Test fixtures
# (caller 'test-%') are provenance-excluded, as in D2's observation read.
_SELECT_LATEST_OBSERVED_SQL = """
SELECT DISTINCT ON (o.bar_date) o.bar_date, o.open, o.high, o.low, o.close, o.volume
FROM ohlcv_observation o
JOIN ohlcv_request q ON q.request_id = o.request_id
WHERE o.symbol = $1 AND o.timeframe = '1d' AND o.route = 'TRADIER' AND o.what_to_show = 'TRADES'
  AND q.caller NOT LIKE 'test-%'
ORDER BY o.bar_date, o.fetched_at DESC, o.request_id DESC
"""

# The stored Tradier 1d bars of $1, each with its date, and the observation-match predicate: a
# non-test TRADIER TRADES observation of the bar's date whose prices equal the stored ones within
# _VALUE_TOLERANCE (the loader's own change test) and whose volume is equal.
_STORED_TRADIER_CTE = """stored AS (
    SELECT m."timestamp", (m."timestamp" AT TIME ZONE 'UTC')::date AS bar_date,
           m.open, m.high, m.low, m.close, m.volume
    FROM market_data_ohlcv m
    WHERE m.symbol = $1 AND m.timeframe = '1d' AND m.source = 'tradier'
)"""
_LINEAGE_MATCH_SQL = f"""o.symbol = $1 AND o.timeframe = '1d' AND o.bar_date = s.bar_date
    AND o.route = 'TRADIER' AND o.what_to_show = 'TRADES'
    AND q.caller NOT LIKE 'test-%'
    AND abs(o.open - s.open) <= {_VALUE_TOLERANCE!r} * greatest(1.0, abs(s.open))
    AND abs(o.high - s.high) <= {_VALUE_TOLERANCE!r} * greatest(1.0, abs(s.high))
    AND abs(o.low - s.low) <= {_VALUE_TOLERANCE!r} * greatest(1.0, abs(s.low))
    AND abs(o.close - s.close) <= {_VALUE_TOLERANCE!r} * greatest(1.0, abs(s.close))
    AND o.volume = s.volume"""

# canonical_bar_lineage for every stored Tradier 1d bar of $1 at rule tradier-v1: request_ids is
# the latest equal observation of its date (plan 185-27). $2 is the bar_derivation_batch id.
# Rows whose rule and provenance are already current are left alone, so a refetch that changed
# nothing rewrites no lineage. Run under bar_derivation_writer; reused by 185-30's backfill.
TRADIER_LINEAGE_UPSERT_SQL = f"""
WITH {_STORED_TRADIER_CTE},
matched AS (
    SELECT DISTINCT ON (s."timestamp") s."timestamp", o.request_id
    FROM stored s
    CROSS JOIN ohlcv_observation o
    JOIN ohlcv_request q ON q.request_id = o.request_id
    WHERE {_LINEAGE_MATCH_SQL}
    ORDER BY s."timestamp", o.fetched_at DESC, o.request_id DESC
)
INSERT INTO canonical_bar_lineage
    (symbol, timeframe, "timestamp", rule_version, request_ids, batch_id)
SELECT $1, '1d', "timestamp", '{TRADIER_RULE_VERSION}', ARRAY[request_id], $2::uuid
FROM matched
ON CONFLICT (symbol, timeframe, "timestamp") DO UPDATE SET
    rule_version = EXCLUDED.rule_version,
    request_ids = EXCLUDED.request_ids,
    batch_id = EXCLUDED.batch_id,
    derived_at = now()
WHERE canonical_bar_lineage.rule_version IS DISTINCT FROM EXCLUDED.rule_version
   OR canonical_bar_lineage.request_ids IS DISTINCT FROM EXCLUDED.request_ids
"""

# The stored Tradier bars of $1 with no equal observation: no lineage row can name their
# provenance, so the load that would leave them aborts.
_TRADIER_LINEAGE_UNMATCHED_SQL = f"""
/* tradier_lineage_unmatched */
WITH {_STORED_TRADIER_CTE}
SELECT s.bar_date FROM stored s
WHERE NOT EXISTS (
    SELECT 1 FROM ohlcv_observation o
    JOIN ohlcv_request q ON q.request_id = o.request_id
    WHERE {_LINEAGE_MATCH_SQL}
)
ORDER BY s.bar_date
"""


class LineageGapError(RuntimeError):
    """A stored Tradier bar has no equal TRADIER observation: its load rolls back."""


async def _record_load(
    conn: Any,
    symbol: str,
    start: date,
    end: date,
    plan: LoadPlan,
    n_fetched: int,
    outcome: str | None = None,
    detail: str | None = None,
    request_id: str | None = None,
    batch_id: str | None = None,
) -> int:
    """One ohlcv_load row and, for an accepted load, its canonical write in one transaction.

    The upsert carries only plan.writes (new and changed bars). Then, under
    bar_derivation_writer (placed after the ohlcv_load and ohlcv_revision writes, which that
    role cannot make), the name's tradier-v1 lineage and any inferred split. A stored Tradier
    bar with no equal observation raises LineageGapError and the whole load rolls back.
    Returns the number of lineage rows inserted or rewritten.
    """
    load_id = uuid.uuid4()
    outcome = outcome or plan.outcome
    detail = detail or plan.detail
    stored = plan.bars if outcome == "loaded" else []
    n_lineage = 0
    async with conn.transaction():
        await conn.execute(
            _INSERT_LOAD_SQL,
            load_id,
            symbol,
            SOURCE,
            start,
            end,
            outcome,
            len(stored) if stored else n_fetched,
            plan.n_new if stored else 0,
            plan.n_changed if stored else 0,
            stored[0].timestamp.date() if stored else None,
            stored[-1].timestamp.date() if stored else None,
            detail,
            _CALLER,
        )
        if not stored:
            return 0
        if plan.revisions:
            await conn.executemany(
                _INSERT_REVISION_SQL,
                [(load_id, symbol, ts, *old[:5], old[5]) for ts, old in plan.revisions],
            )
        if plan.writes:
            await conn.executemany(
                _UPSERT_SQL,
                [
                    (b.timestamp, symbol, b.open, b.high, b.low, b.close, b.volume, SOURCE)
                    for b in plan.writes
                ],
            )
        # The role switch holds until commit: everything after it is the derivation role's
        # (canonical_bar_lineage, corporate_action), nothing before it is.
        await conn.execute("SET LOCAL ROLE bar_derivation_writer")
        n_lineage = _rowcount(await conn.execute(TRADIER_LINEAGE_UPSERT_SQL, symbol, batch_id))
        unmatched = [
            r["bar_date"] for r in await conn.fetch(_TRADIER_LINEAGE_UNMATCHED_SQL, symbol)
        ]
        if unmatched:
            shown = ", ".join(str(d) for d in unmatched[:5])
            raise LineageGapError(
                f"{symbol}: {len(unmatched)} stored tradier bar(s) have no equal TRADIER "
                f"observation (first: {shown})"
            )
        if plan.split is not None:
            if request_id is None:
                raise ValueError(f"{symbol}: refusing to record a split without its request id")
            split = plan.split
            await conn.execute(
                _INSERT_SPLIT_SQL,
                symbol,
                split.kind,
                split.effective_date,
                split.factor,
                [request_id],
                json.dumps(
                    {
                        "load_id": str(load_id),
                        "evidence_days": split.evidence_days,
                        "n_changed": plan.n_changed,
                    }
                ),
            )
    return n_lineage


def _rowcount(status: str) -> int:
    """The row count of an asyncpg command status such as 'INSERT 0 12'."""
    return int(status.rsplit(None, 1)[-1])


async def _land_in_d1(
    conn: Any,
    sink: AsyncObservationSink,
    fetch_run_id: str,
    symbol: str,
    end: date,
    start: date,
    result: list[DailyBar] | str,
    requested_at: datetime,
    latest: dict[date, ObservedBar] | None = None,
) -> tuple[str, int]:
    """Raw answer (or failure) into D1 before any canonical decision.

    The request row records the full answer (n_bars); observations land only for the bars
    d1_bars_to_land keeps against `latest` (every bar when latest is None). Returns the
    request id and the number of observations landed.
    """
    failed = isinstance(result, str)
    bars = [] if failed else result
    record = RequestRecord(
        request_id=str(uuid.uuid4()),
        fetch_run_id=fetch_run_id,
        symbol=symbol,
        timeframe="1d",
        route="TRADIER",
        what_to_show="TRADES",
        primary_exchange=None,
        window_start=datetime(start.year, start.month, start.day, tzinfo=UTC),
        window_end=datetime(end.year, end.month, end.day, tzinfo=UTC),
        ib_req_id=None,
        outcome="failed" if failed else ("bars" if bars else "no_data"),
        error_code=None,
        error_text=result if failed else None,
        n_bars=len(bars),
        client_id=None,
        requested_at=requested_at,
        answered_at=datetime.now(UTC),
    )
    sink.on_request(record)
    landed = bars if latest is None else d1_bars_to_land(bars, latest)
    if landed:
        sink.on_observation(record, landed)
    await sink.flush(conn)
    return record.request_id, len(landed)


async def _latest_observed(conn: Any, symbol: str) -> dict[date, ObservedBar]:
    rows = await conn.fetch(_SELECT_LATEST_OBSERVED_SQL, symbol)
    return {r["bar_date"]: (r["open"], r["high"], r["low"], r["close"], r["volume"]) for r in rows}


async def _existing_bars(conn: Any, symbol: str) -> dict[datetime, StoredBar]:
    rows = await conn.fetch(_SELECT_EXISTING_SQL, symbol)
    return {
        r["timestamp"]: (r["open"], r["high"], r["low"], r["close"], r["volume"], r["source"])
        for r in rows
    }


def mark_loaded_fetch_complete(database_url: str, symbols: list[str], since: date) -> None:
    """Set 1d fetch_complete for each accepted load through the flag's one writer.

    mark_fetch_complete takes a psycopg connection, so this opens one (committed on exit) rather
    than restating its SQL for asyncpg. `since` is the load's requested start: every bar the
    load stored is at or after it, which bounds the writer's EXISTS guard.
    """
    since_dt = datetime(since.year, since.month, since.day, tzinfo=UTC)
    with psycopg.connect(database_url) as pg:
        for symbol in symbols:
            mark_fetch_complete(pg, symbol, "1d", since_dt)


async def _scrub_and_digest(
    conn: Any,
    database_url: str,
    *,
    scrub_names: list[str],
    loaded: list[str],
    batch_id: str,
) -> tuple[list[str], dict[str, Any]]:
    """After the fetch loop: the D2a scrub over the changed names, then digests for every
    loaded name (D-12 on this write path, plan 185-27). Returns failures and a detail dict."""
    failed: list[str] = []
    scrub_counts: dict[str, int] = {}
    if scrub_names:
        # One connection: scrub_symbols holds a single acquire for its read and write; the pool
        # exists for the jsonb codecs create_pool registers (the bare loader connection has none).
        pool = await create_pool(database_url, "tradier_daily_scrub", min_size=1, max_size=1)
        try:
            scrub_counts = await scrub_symbols(
                pool,
                tf="1d",
                symbols=scrub_names,
                rules=None,
                start=None,
                end=None,
                batch_id=batch_id,
                write=True,
            )
        except Exception as error:
            failed.append(f"scrub: {error}")
        finally:
            await pool.close()
    n_digest_rows = 0
    for symbol in loaded:
        try:
            n_digest_rows += await write_1d_digests(
                conn, symbol=symbol, batch_id=batch_id, rule_version=TRADIER_RULE_VERSION
            )
        except Exception as error:
            failed.append(f"digest {symbol}: {error}")
    return failed, {
        "n_scrubbed": len(scrub_names),
        "scrub_counts": scrub_counts,
        "n_digested": len(loaded),
        "digest_rows": n_digest_rows,
    }


async def run(
    symbols: list[str] | None,
    rebase: bool,
    raw_only: bool,
    dry_run: bool,
    nightly: bool = False,
) -> int:
    settings = get_settings()
    conn = await asyncpg.connect(settings.database_url)
    batch_id: str | None = None
    batch_status = "failed"
    batch_detail: dict[str, Any] = {}
    try:
        apr = await load_apr_dict_async(conn, ["infra.tradier.%", "threshold.seam.%"])
        if nightly and not nightly_enabled(apr):
            logger.info("tradier_daily.nightly_disabled", key=_NIGHTLY_ENABLED_KEY)
            print(f"tradier daily load: --nightly skipped, {_NIGHTLY_ENABLED_KEY} is off")
            return 0
        params = LoadParams(
            min_session_ratio=float(apr["infra.tradier.min_session_ratio"]),
            first_date_tolerance_days=int(apr["infra.tradier.first_date_tolerance_days"]),
            max_changed_bar_ratio=float(apr["infra.tradier.max_changed_bar_ratio"]),
            rebase=rebase,
            split_rel_tol=float(apr["threshold.seam.rel_tol"]),
            split_min_run=int(apr["threshold.seam.min_run"]),
            ratio_snap_tol=float(apr["threshold.seam.ratio_snap_tol"]),
        )
        start = date.fromisoformat(apr["infra.tradier.history_start"])
        end = datetime.now(UTC).date() - timedelta(days=1)  # completed sessions only
        if raw_only:
            default_sql = _SELECT_NO_RAW_SQL
        elif nightly:
            default_sql = _SELECT_NIGHTLY_SQL
        else:
            default_sql = _SELECT_MISSING_SQL
        todo = symbols or [r["symbol"] for r in await conn.fetch(default_sql)]
        logger.info(
            "tradier_daily.start",
            n_symbols=len(todo),
            rebase=rebase,
            start=str(start),
            end=str(end),
        )
        write_run = not (dry_run or raw_only)
        if write_run:
            # One provenance row per write run (migration 441); stage tradier keeps D2's
            # changed-since watermark (stage daily) untouched.
            batch_id = await open_batch(
                conn,
                stage="tradier",
                rule_version=TRADIER_RULE_VERSION,
                apr_snapshot={k: v for k, v in apr.items() if k.startswith("infra.tradier.")},
                n_symbols=len(todo),
            )
        semaphore = asyncio.Semaphore(int(apr["infra.tradier.concurrency"]))
        client = make_client(
            settings.tradier_base_url,
            settings.tradier_api_token,
            float(apr["infra.tradier.request_timeout_s"]),
        )

        async def fetch(symbol: str) -> tuple[str, list[DailyBar] | str]:
            async with semaphore:
                try:
                    return symbol, await fetch_daily_history(client, symbol, start, end)
                except TradierError as error:
                    return symbol, str(error)

        counts: dict[str, int] = {}
        totals = {
            "new": 0,
            "changed": 0,
            "orphan": 0,
            "extended_back": 0,
            "splits": 0,
            "d1_land": 0,
        }
        loaded: list[str] = []
        scrub_names: list[str] = []
        n_landed = n_lineage_rows = 0
        sink = AsyncObservationSink(caller=_CALLER, source=SOURCE)
        fetch_run_id = new_fetch_run_id()
        async with client:
            for pending in asyncio.as_completed([fetch(s) for s in todo]):
                symbol, result = await pending
                if dry_run:
                    outcome = "failed"
                    if not isinstance(result, str):
                        latest = await _latest_observed(conn, symbol)
                        totals["d1_land"] += len(d1_bars_to_land(result, latest))
                        existing = await _existing_bars(conn, symbol)
                        plan = plan_symbol_load(result, existing, params)
                        outcome = plan.outcome
                        if plan.outcome == "loaded":
                            totals["new"] += plan.n_new
                            totals["changed"] += plan.n_changed
                            totals["orphan"] += plan.n_orphan
                            totals["splits"] += plan.split is not None
                            if existing and plan.first_bar < min(existing).date():
                                totals["extended_back"] += 1
                    counts[outcome] = counts.get(outcome, 0) + 1
                    continue
                latest = (
                    None
                    if raw_only or isinstance(result, str)
                    else await _latest_observed(conn, symbol)
                )
                request_id, n_obs = await _land_in_d1(
                    conn, sink, fetch_run_id, symbol, end, start, result, datetime.now(UTC), latest
                )
                n_landed += n_obs
                if raw_only:
                    outcome = "failed" if isinstance(result, str) else "raw_landed"
                    counts[outcome] = counts.get(outcome, 0) + 1
                    continue
                n_lineage = 0
                if isinstance(result, str):
                    plan = LoadPlan("failed", result)
                    await _record_load(conn, symbol, start, end, plan, 0)
                else:
                    plan = plan_symbol_load(result, await _existing_bars(conn, symbol), params)
                    try:
                        n_lineage = await _record_load(
                            conn,
                            symbol,
                            start,
                            end,
                            plan,
                            len(result),
                            request_id=request_id,
                            batch_id=batch_id,
                        )
                    except LineageGapError as error:
                        # The load rolled back: its bars, revisions and lineage are not written.
                        plan = LoadPlan("failed", str(error))
                        await _record_load(conn, symbol, start, end, plan, len(result))
                if plan.outcome == "loaded":
                    loaded.append(symbol)
                    n_lineage_rows += n_lineage
                    if plan.n_new + plan.n_changed > 0 or n_lineage > 0:
                        scrub_names.append(symbol)
                counts[plan.outcome] = counts.get(plan.outcome, 0) + 1
                logger.info(
                    "tradier_daily.symbol",
                    symbol=symbol,
                    outcome=plan.outcome,
                    n_bars=len(plan.bars),
                    n_new=plan.n_new,
                    n_changed=plan.n_changed,
                    n_d1_landed=n_obs,
                    n_lineage=n_lineage,
                    split=plan.split.factor if plan.split else None,
                    detail=plan.detail,
                )
        post_failed: list[str] = []
        if batch_id is not None:
            post_failed, post_detail = await _scrub_and_digest(
                conn,
                settings.database_url,
                scrub_names=sorted(scrub_names),
                loaded=sorted(loaded),
                batch_id=batch_id,
            )
            if loaded:
                try:
                    await asyncio.to_thread(
                        mark_loaded_fetch_complete, settings.database_url, sorted(loaded), start
                    )
                    post_detail["n_fetch_complete_marked"] = len(loaded)
                except Exception as error:
                    post_failed.append(f"fetch_complete: {error}")
            batch_detail = {
                "counts": counts,
                "d1_observations_landed": n_landed,
                "lineage_rows": n_lineage_rows,
                **post_detail,
                "post_failures": post_failed[:20],
            }
            if post_failed:
                logger.error("tradier_daily.post_load_failed", failures=post_failed[:20])
        logger.info("tradier_daily.done", d1_observations_landed=n_landed, **counts)
        label = " (dry run)" if dry_run else ""
        print(f"tradier daily load{label}: {counts}" + (f" totals {totals}" if dry_run else ""))
        if batch_detail:
            print(f"tradier daily post-load: {batch_detail}")
        if post_failed:
            return 1
        batch_status = "completed"
        return 0 if set(counts) <= {"loaded", "raw_landed"} else EXIT_REFUSED
    finally:
        try:
            if batch_id is not None:
                await close_batch(conn, batch_id, status=batch_status, detail=batch_detail)
        finally:
            await conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--symbols", help="comma-separated; default: active equities with no 1d bars"
    )
    parser.add_argument(
        "--rebase", action="store_true", help="deliberate source change: skip the changed-bar gate"
    )
    parser.add_argument(
        "--raw-only",
        action="store_true",
        help="land D1 raw observations only: no canonical write, no ohlcv_load row",
    )
    parser.add_argument(
        "--nightly",
        action="store_true",
        help="the nightly leg: names with no 1d bars plus every Tradier-owned name, in full",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="fetch and plan only: print outcome counts and totals, write nothing",
    )
    args = parser.parse_args()
    setup_service_logging("logs/tradier_daily_loader.log")
    symbols = [s.strip() for s in args.symbols.split(",") if s.strip()] if args.symbols else None
    if args.nightly and (symbols or args.raw_only or args.rebase):
        parser.error("--nightly takes no --symbols, --raw-only or --rebase")
    returncode = 1
    try:
        returncode = asyncio.run(
            run(symbols, args.rebase, args.raw_only, args.dry_run, args.nightly)
        )
        return returncode
    finally:
        if not args.dry_run:
            JOB_COMPLETED_TOTAL.add(1, {"job": JOB, "status": job_status(returncode)})
        flush_and_shutdown_metrics()


if __name__ == "__main__":
    from src.observability.otel import OTelInitError, init_otel_providers

    try:
        init_otel_providers(JOB)
    except OTelInitError as error:
        print(f"[warn] OTel init failed, metrics disabled: {error}")
    sys.exit(main())
