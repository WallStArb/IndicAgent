#!/usr/bin/env python3
"""infrastructure_run_tradier_daily.py - land Tradier daily history in D1 and chain the daily stage.

Raw only (plan 185-38; data layer integrity design section 4). One request returns a name's whole
history. The answer lands in D1 (ohlcv_request/ohlcv_observation, source tradier, route TRADIER,
raw including null volume) with D1 elision (plan 185-27): a bar lands as an observation only when
no non-test TRADIER observation of its date exists or one of open, high, low, close, volume
differs exactly from the latest one, so a nightly full-history refetch adds only the vendor's new
and revised bars. The request row records the full answer (n_bars). Every attempt writes one
ohlcv_load row (source tradier, destination d1, n_new and n_changed against the latest
observations). The loader writes no canonical bar, no lineage, no revision and no digest: the
daily stage (services/bar_derivation.py --stage daily, rule d2-v2) is the only 1d writer, and
after the fetch loop one subprocess runs it with --apply for the names whose D1 changed.

Refusal on the raw record: an answer that revises more than threshold.bar_integrity.max_revision_ratio
of the name's latest TRADIER observations lands nothing (outcome gated; only the request row is
recorded) unless --rebase, or unless its changes are one constant close ratio over a prefix of
the history (a split the vendor back-adjusted, plan 185-26): the ratio is snapped with the seam
rule (src/intelligence/bars/seams.py, corporate_actions.py, threshold.seam.* APR) and recorded in
corporate_action (inferred_by tradier_refetch, the request id as evidence, the load id in detail)
in the load row's transaction, and the answer lands.

A short answer (sessions under infra.tradier.min_session_ratio of the weekdays it spans, or a
first bar more than infra.tradier.first_date_tolerance_days after the earliest Tradier
observation) is no longer a refusal: source ownership lives in bar_source_policy (migration 446),
so the load lands D1 and records outcome loaded with short_history in its detail.

--nightly selects names with no 1d bars plus every name whose open 1d policy is Tradier primary
and that has a Tradier observation (TRADIER_OWNED_SQL), each refetched in full so vendor
revisions and splits surface the night they happen.

No load writes backfill_status: promotion reads bar_integrity verdicts since plan 185-41,
and plan 189-08 retired the fetch_complete writer.

Usage:
  python scripts/infrastructure/backfill/infrastructure_run_tradier_daily.py            # names with no 1d bars
  python scripts/infrastructure/backfill/infrastructure_run_tradier_daily.py --symbols AAPL,SPY [--rebase]
  python scripts/infrastructure/backfill/infrastructure_run_tradier_daily.py --nightly
Exit codes: 0 every name loaded; EXIT_REFUSED (4) some names refused or failed (recorded in
ohlcv_load, a finding, not an error); 1 a runtime error or a failed daily stage.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import sys
import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import asyncpg
import numpy as np
import structlog

project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from services._batch_utils import load_apr_dict_async
from services.bar_derivation import TRADIER_OWNED_SQL
from services.ohlcv_observation_writer import AsyncObservationSink, new_fetch_run_id
from src.config.settings import get_settings
from src.core.service_utils import setup_service_logging
from src.intelligence.bars.corporate_actions import SplitInference, infer_split
from src.intelligence.bars.seams import Seam
from src.observability.metrics import JOB_COMPLETED_TOTAL, flush_and_shutdown_metrics
from src.providers.base import RequestRecord
from src.providers.tradier import SOURCE, DailyBar, TradierError, fetch_daily_history, make_client

logger = structlog.get_logger(__name__)

_CALLER = "tradier-daily-loader"
_INFERRED_BY = "tradier_refetch"
_DESTINATION = "d1"
# Some names refused or failed: recorded in ohlcv_load and reported by the D7 audit, a finding
# the nightly does not fail on. Distinct from 1 (an uncaught runtime error) and 2 (argparse).
EXIT_REFUSED = 4

# The systemd unit's %n suffix (indicagent-tradier-daily.service, plan 189-06): the D-06
# job_completed_total label. The nightly ran this leg until the 189 cutover; the unit is its
# own caller now.
JOB = "tradier-daily"
_NIGHTLY_ENABLED_KEY = "infra.tradier.nightly_enabled"
_TRUTHY = ("true", "1", "t", "yes")
# The chained single 1d writer (plan 185-38).
DAILY_STAGE_ARGS = ("-m", "services.bar_derivation", "--stage", "daily")


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


# (open, high, low, close, volume) of the latest TRADIER observation of one date
ObservedBar = tuple[float, float, float, float, int | None]


@dataclass(frozen=True)
class LoadParams:
    min_session_ratio: float
    first_date_tolerance_days: int
    # threshold.bar_integrity.max_revision_ratio: the write contract's refusal on the raw record
    max_revision_ratio: float
    rebase: bool
    # threshold.seam.rel_tol, threshold.seam.min_run, threshold.seam.ratio_snap_tol
    split_rel_tol: float
    split_min_run: int
    ratio_snap_tol: float


@dataclass
class LoadPlan:
    outcome: str  # loaded | no_data | gated | failed
    detail: str | None
    bars: list[DailyBar] = field(default_factory=list)  # the full answer
    # The bars D1 takes: new dates and revised bars only (185-27 elision); empty when gated.
    landed: list[DailyBar] = field(default_factory=list)
    n_new: int = 0
    n_changed: int = 0  # dates whose latest observation the answer revises
    first_bar: date | None = None
    split: SplitInference | None = None  # a vendor back-adjustment the refetch carried


def _values(bar: DailyBar) -> ObservedBar:
    return (bar.open, bar.high, bar.low, bar.close, bar.volume)


def d1_bars_to_land(bars: list[DailyBar], latest: dict[date, ObservedBar]) -> list[DailyBar]:
    """The answer's bars D1 does not already hold as its latest TRADIER observation.

    A bar lands when its date has no observation or any of open, high, low, close, volume
    differs exactly from the latest one (null volume compares as a value). Exact on purpose: D1
    is the raw record, so any vendor revision, however small, is kept. An empty map (a first
    load) lands every bar.
    """
    return [bar for bar in bars if latest.get(bar.timestamp.date()) != _values(bar)]


def _refetch_split(
    overlap: list[tuple[DailyBar, ObservedBar, bool]], params: LoadParams
) -> SplitInference | None:
    """The split a refetch carries against the latest Tradier observations, or None.

    overlap is (fresh bar, latest observation, revised) in date order. A split back-adjusts
    every bar before its ex-date by one ratio: the revised bars must be exactly a prefix of the
    overlap (at least split_min_run long) and their old/fresh close ratio must stay within
    split_rel_tol of itself and snap to a rational p/q (infer_split). The effective date is the
    last revised bar, the last day observed on the old scale.
    """
    n_changed = sum(1 for _, _, changed in overlap if changed)
    if n_changed < params.split_min_run or not all(c for _, _, c in overlap[:n_changed]):
        return None
    prefix = overlap[:n_changed]
    ratios = []
    for bar, old, _ in prefix:
        if not (bar.close > 0 and old[3] > 0):
            return None
        ratios.append(old[3] / bar.close)
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


def _short_history_note(
    bars: list[DailyBar], latest: dict[date, ObservedBar], params: LoadParams
) -> str | None:
    first, last = bars[0].timestamp.date(), bars[-1].timestamp.date()
    weekdays = int(np.busday_count(first, last + timedelta(days=1)))
    ratio = len(bars) / weekdays if weekdays else 1.0
    if ratio < params.min_session_ratio:
        return (
            f"short_history: {len(bars)} bars over {weekdays} weekdays "
            f"({ratio:.3f} < {params.min_session_ratio})"
        )
    if latest:
        earliest = min(latest)
        if first > earliest + timedelta(days=params.first_date_tolerance_days):
            return (
                f"short_history: answer starts {first}, Tradier observations start {earliest} "
                f"(tolerance {params.first_date_tolerance_days} d)"
            )
    return None


def plan_symbol_load(
    fetched: list[DailyBar], latest: dict[date, ObservedBar], params: LoadParams
) -> LoadPlan:
    """Decide one name's D1 load from its Tradier answer and its latest Tradier observations."""
    if not fetched:
        return LoadPlan("no_data", "Tradier returned no bars")
    bars = sorted(fetched, key=lambda b: b.timestamp)
    landed = d1_bars_to_land(bars, latest)
    overlap = [
        (bar, latest[bar.timestamp.date()], latest[bar.timestamp.date()] != _values(bar))
        for bar in bars
        if bar.timestamp.date() in latest
    ]
    n_changed = sum(1 for _, _, changed in overlap if changed)
    ratio = n_changed / len(latest) if latest else 0.0
    notes = [n for n in (_short_history_note(bars, latest, params),) if n]
    split = None
    if ratio > params.max_revision_ratio and not params.rebase:
        split = _refetch_split(overlap, params)
        if split is None:
            return LoadPlan(
                "gated",
                f"{n_changed} of {len(latest)} latest Tradier observations revised "
                f"({ratio:.3f} > {params.max_revision_ratio}); pass --rebase to accept a "
                "deliberate restatement",
                bars=bars,
            )
        notes.append(f"{split.kind} {split.factor:g} effective {split.effective_date} (refetch)")
    elif ratio > params.max_revision_ratio:
        notes.append(f"rebase: {n_changed} of {len(latest)} latest observations revised")
    return LoadPlan(
        "loaded",
        "; ".join(notes) or None,
        bars=bars,
        landed=landed,
        n_new=len(landed) - n_changed,
        n_changed=n_changed,
        first_bar=bars[0].timestamp.date(),
        split=split,
    )


_SELECT_MISSING_SQL = """
SELECT i.symbol FROM instruments i
WHERE i.is_active AND i.contract_details->>'asset_class' = 'equity'
  AND NOT EXISTS (SELECT 1 FROM market_data_ohlcv_tradeable m
                  WHERE m.symbol = i.symbol AND m.timeframe = '1d')
  AND NOT EXISTS (SELECT 1 FROM ohlcv_load l
                  WHERE l.symbol = i.symbol AND l.source = 'tradier' AND l.outcome = 'loaded')
ORDER BY i.symbol
"""

# The nightly leg (plan 185-26): the missing names above plus every name Tradier owns.
_SELECT_NIGHTLY_SQL = f"""
SELECT i.symbol FROM instruments i
WHERE i.is_active AND i.contract_details->>'asset_class' = 'equity'
  AND ({TRADIER_OWNED_SQL.format(col="i.symbol")}
       OR NOT EXISTS (SELECT 1 FROM market_data_ohlcv_tradeable m
                      WHERE m.symbol = i.symbol AND m.timeframe = '1d'))
ORDER BY i.symbol
"""

_INSERT_LOAD_SQL = """
INSERT INTO ohlcv_load (load_id, symbol, timeframe, source, requested_start, requested_end, outcome,
                        n_bars, n_new, n_changed, first_bar, last_bar, detail, caller, destination)
VALUES ($1, $2, '1d', $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14)
"""

# Written under bar_derivation_writer, the role that owns corporate_action (migration 400).
_INSERT_SPLIT_SQL = f"""
INSERT INTO corporate_action
    (symbol, action_type, effective_date, factor, inferred_by, evidence_request_ids, detail)
VALUES ($1, $2, $3, $4, '{_INFERRED_BY}', $5::uuid[], $6::jsonb)
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


async def _record_load(
    conn: Any,
    symbol: str,
    start: date,
    end: date,
    plan: LoadPlan,
    n_fetched: int,
    request_id: str | None = None,
) -> None:
    """One ohlcv_load row (destination d1) and, for a load that carried a split, its
    corporate_action row under bar_derivation_writer, in one transaction."""
    load_id = uuid.uuid4()
    loaded = plan.outcome == "loaded"
    async with conn.transaction():
        await conn.execute(
            _INSERT_LOAD_SQL,
            load_id,
            symbol,
            SOURCE,
            start,
            end,
            plan.outcome,
            n_fetched,
            plan.n_new if loaded else 0,
            plan.n_changed if loaded else 0,
            plan.bars[0].timestamp.date() if loaded and plan.bars else None,
            plan.bars[-1].timestamp.date() if loaded and plan.bars else None,
            plan.detail,
            _CALLER,
            _DESTINATION,
        )
        if loaded and plan.split is not None:
            if request_id is None:
                raise ValueError(f"{symbol}: refusing to record a split without its request id")
            split = plan.split
            # The role switch holds until commit: corporate_action is the derivation role's.
            await conn.execute("SET LOCAL ROLE bar_derivation_writer")
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


async def _land_in_d1(
    conn: Any,
    sink: AsyncObservationSink,
    fetch_run_id: str,
    symbol: str,
    end: date,
    start: date,
    result: list[DailyBar] | str,
    requested_at: datetime,
    landed: list[DailyBar],
) -> str:
    """The request row (full answer count, or the failure) and the landed observations."""
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
    if landed:
        sink.on_observation(record, landed)
    await sink.flush(conn)
    return record.request_id


async def _latest_observed(conn: Any, symbol: str) -> dict[date, ObservedBar]:
    rows = await conn.fetch(_SELECT_LATEST_OBSERVED_SQL, symbol)
    return {r["bar_date"]: (r["open"], r["high"], r["low"], r["close"], r["volume"]) for r in rows}


def run_daily_stage(symbols: list[str]) -> int:
    """The single 1d writer over the names whose D1 changed: one subprocess, its exit code."""
    cmd = [sys.executable, *DAILY_STAGE_ARGS, "--symbols", ",".join(symbols), "--apply"]
    logger.info("tradier_daily.daily_stage_start", n_symbols=len(symbols))
    return subprocess.run(cmd, cwd=project_root, check=False).returncode


async def run(
    symbols: list[str] | None,
    rebase: bool,
    dry_run: bool,
    nightly: bool = False,
) -> int:
    settings = get_settings()
    conn = await asyncpg.connect(settings.database_url)
    try:
        apr = await load_apr_dict_async(
            conn, ["infra.tradier.%", "threshold.seam.%", "threshold.bar_integrity.%"]
        )
        if nightly and not nightly_enabled(apr):
            logger.info("tradier_daily.nightly_disabled", key=_NIGHTLY_ENABLED_KEY)
            print(f"tradier daily load: --nightly skipped, {_NIGHTLY_ENABLED_KEY} is off")
            return 0
        params = LoadParams(
            min_session_ratio=float(apr["infra.tradier.min_session_ratio"]),
            first_date_tolerance_days=int(apr["infra.tradier.first_date_tolerance_days"]),
            max_revision_ratio=float(apr["threshold.bar_integrity.max_revision_ratio"]),
            rebase=rebase,
            split_rel_tol=float(apr["threshold.seam.rel_tol"]),
            split_min_run=int(apr["threshold.seam.min_run"]),
            ratio_snap_tol=float(apr["threshold.seam.ratio_snap_tol"]),
        )
        start = date.fromisoformat(apr["infra.tradier.history_start"])
        end = datetime.now(UTC).date() - timedelta(days=1)  # completed sessions only
        default_sql = _SELECT_NIGHTLY_SQL if nightly else _SELECT_MISSING_SQL
        todo = symbols or [r["symbol"] for r in await conn.fetch(default_sql)]
        logger.info(
            "tradier_daily.start",
            n_symbols=len(todo),
            rebase=rebase,
            start=str(start),
            end=str(end),
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
        totals = {"new": 0, "changed": 0, "splits": 0}
        changed_names: list[str] = []
        n_landed = 0
        sink = AsyncObservationSink(caller=_CALLER, source=SOURCE)
        fetch_run_id = new_fetch_run_id()
        async with client:
            for pending in asyncio.as_completed([fetch(s) for s in todo]):
                symbol, result = await pending
                if isinstance(result, str):
                    plan = LoadPlan("failed", result)
                else:
                    plan = plan_symbol_load(result, await _latest_observed(conn, symbol), params)
                counts[plan.outcome] = counts.get(plan.outcome, 0) + 1
                if dry_run:
                    if plan.outcome == "loaded":
                        totals["new"] += plan.n_new
                        totals["changed"] += plan.n_changed
                        totals["splits"] += plan.split is not None
                    continue
                request_id = await _land_in_d1(
                    conn,
                    sink,
                    fetch_run_id,
                    symbol,
                    end,
                    start,
                    result,
                    datetime.now(UTC),
                    plan.landed,
                )
                n_landed += len(plan.landed)
                await _record_load(
                    conn,
                    symbol,
                    start,
                    end,
                    plan,
                    0 if isinstance(result, str) else len(result),
                    request_id=request_id,
                )
                if plan.outcome == "loaded" and (plan.landed or plan.split is not None):
                    changed_names.append(symbol)
                logger.info(
                    "tradier_daily.symbol",
                    symbol=symbol,
                    outcome=plan.outcome,
                    n_bars=len(plan.bars),
                    n_new=plan.n_new,
                    n_changed=plan.n_changed,
                    n_d1_landed=len(plan.landed),
                    split=plan.split.factor if plan.split else None,
                    detail=plan.detail,
                )
        label = " (dry run)" if dry_run else ""
        print(f"tradier daily load{label}: {counts}" + (f" totals {totals}" if dry_run else ""))
        if dry_run:
            return 0 if set(counts) <= {"loaded"} else EXIT_REFUSED
        logger.info("tradier_daily.done", d1_observations_landed=n_landed, **counts)
        failures: list[str] = []
        if changed_names:
            stage_code = await asyncio.to_thread(run_daily_stage, sorted(changed_names))
            print(f"tradier daily: daily stage over {len(changed_names)} names exited {stage_code}")
            if stage_code != 0:
                failures.append(f"daily stage exit {stage_code}")
        if failures:
            logger.error("tradier_daily.post_load_failed", failures=failures)
            return 1
        return 0 if set(counts) <= {"loaded"} else EXIT_REFUSED
    finally:
        await conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--symbols", help="comma-separated; default: active equities with no 1d bars"
    )
    parser.add_argument(
        "--rebase",
        action="store_true",
        help="accept an answer that revises more than the max revision ratio (no split found)",
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
    if args.nightly and (symbols or args.rebase):
        parser.error("--nightly takes no --symbols or --rebase")
    returncode = 1
    try:
        returncode = asyncio.run(run(symbols, args.rebase, args.dry_run, args.nightly))
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
