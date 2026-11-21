"""DividendEventWriter: two independent dividend sources -> dividend_events, reconciled.

Oneshot batch (todo 428). Stored equity bars are split-adjusted, not dividend-adjusted, so any
return spanning an ex-date carries the dividend as a loss. Readers correct returns with
dividend_events_reconciled; this job keeps it filled and checks the two sources against each
other.

Why two sources (measured 2026-09-26 on SPY, HYG, TLT, TSLA): each has holes the other fills.
IBKR's adjustment record misses all SPY dividends before 2006 and its December 2006 and 2007
dividends, and five HYG months; Yahoo misses HYG's November 2012 distribution. Neither source's
holes are visible from its own data.

Source "yahoo": declared cash dividends by ex-date with the split-adjusted close, full history.

Source "ibkr_adjusted_last_ratio" (D5, phase 185 plan 21): derived from the paired TRADES and
ADJUSTED_LAST closes of one fetch run read from ohlcv_raw and ohlcv_revision (plan 191-10,
pair_d1_series), never from a live IBKR fetch. IBKR's ADJUSTED_LAST close is the TRADES close times a cumulative dividend
factor; with r_t = adjusted_t / close_t, an ex-date t steps the ratio by
r_t / r_{t-1} = 1 / (1 - amount / close_{t-1}). ADJUSTED_LAST is quoted to the cent, so with no
dividend r moves by at most 0.005/close_t + 0.005/close_{t-1} when both series use the same
close. They do not always: in parts of IBKR's early history the two series use different
closing prices and the ratio wanders far beyond rounding (NVR 2004: 0.3% a day). So a step
counts only if it exceeds the bound times threshold.dividend_event.noise_margin AND the ratio is
flat within the bound for threshold.dividend_event.stable_sessions rows on each side, which
shows the series in lockstep. Unstable steps and downward steps are counted, never stored. The
newest rows wait for the next run, so coverage ends stable_sessions rows short.

Every source writes first-derivation-wins (IBKR re-bases its ratio with every new dividend, so
re-derived amounts differ by rounding); a re-derived yield outside the source's tolerance is
logged, not overwritten. Readers use amount / prev_close (the yield on the ex-date): a later
split re-scales both, so only the ratio is stable.

Reconciliation (inside each symbol's write transaction, over everything stored for it): the
same dividend reported 1-5 days apart by the two sources would be counted twice by the
reconciled view, so it becomes a dividend_date_dispute record (both dates, both sources) in the
same transaction and both events stand; the research reader marks returns spanning the disputed
window unknown (the reader change is the phase 183 hand-off). Yield disagreements beyond
threshold.dividend_event.source_yield_rel_tolerance and each source's holes are logged and
counted.

Source "massive" (MassiveDividendWriter, run alone and by hand): the latest Massive dividend
capture in reference_raw (endpoint dividends), mapped to symbols through ticker_event_current,
USD cash only, amounts over the raw Massive prior close, with a coverage claim built from each
name's own cadence plus its holes (dividend_event_coverage_gap). The rule is pure in
src/intelligence/bars/massive_dividends.py; the measurement behind it is
docs/plans/2026-11-21-massive-dividend-coverage-rule.md. The source is not reconciled against
the other two here: rows carry their source label and the research reader decides. Every
reader of dividend_events names the sources it reads (todo 651; CI-enforced by
tests/unit/test_dividend_events_source_readers.py), so a massive row reaches only the readers
written for it.

Usage:
    python services/dividend_event_writer.py                          # yahoo and ibkr
    python services/dividend_event_writer.py --sources yahoo          # nightly-cheap
    python services/dividend_event_writer.py --sources ibkr --fetch-run-id <uuid>
    python services/dividend_event_writer.py --sources massive --dry-run   # counts, no writes
"""

from __future__ import annotations

import argparse
import asyncio
import bisect
import collections
import dataclasses
import json
import math
import uuid
from collections.abc import Sequence
from datetime import UTC, date, datetime
from typing import Any

import asyncpg

from services.batch_support.config import cfg as _cfg
from services.batch_support.db import load_apr_dict_async
from src.config.settings import Settings, get_active_contracts
from src.core.agent.base_batch import BaseBatch
from src.core.models import AssetClass
from src.intelligence.bars import massive_dividends
from src.intelligence.bars.corporate_actions import disputed_dates
from src.intelligence.bars.massive_symbol_map import TickerSpan
from src.intelligence.research.dividends import DisputeRule, ibkr_rounding_bound
from src.observability.metrics import counter
from src.observability.otel import OTelInitError, init_otel_providers
from src.providers import yahoo

_JOB = "dividend-event-writer"
# Per-run reconciliation outcomes, labeled {sources, outcome} only: never per symbol (cardinality),
# and the per-symbol detail stays in the log.
_OUTCOME_TOTAL = counter(
    "dividend_event_outcome_total",
    "dividend_event_writer per-run outcome counts: events derived, downward and unstable IBKR "
    "steps rejected, re-derived yields that moved, cross-source yield disagreements beyond "
    "rounding, holes in either source, failed symbols. Never labeled by symbol.",
)
SOURCE_IBKR = "ibkr_adjusted_last_ratio"
SOURCE_YAHOO = "yahoo"
SOURCE_MASSIVE = massive_dividends.SOURCE
_CLI_SOURCES = {"ibkr": SOURCE_IBKR, "yahoo": SOURCE_YAHOO, "massive": SOURCE_MASSIVE}
# The sources reconcile() compares; other sources' rows (massive) are not read by it.
_RECONCILED_SOURCES = f"('{SOURCE_IBKR}', '{SOURCE_YAHOO}')"
# The default run (no --sources) is the two original sources; massive runs alone, by hand.
_DEFAULT_CLI_SOURCES = ["ibkr", "yahoo"]
# ADJUSTED_LAST is quoted to the cent: half a cent of rounding per close.
_HALF_TICK = 0.005
# The rounding bound is attained exactly when an unrounded adjusted close ends in half a cent;
# this relative slack keeps floating-point error at that tie from reading as a step.
_FLOAT_SLACK = 1e-9
# The IBKR inputs as raw series (plan 191-10). Vendor and kinds are CVR codes (bar_vendor,
# bar_kind; todo 504): the writer refuses to run when the vocabulary lacks one.
IBKR_VENDOR = "ibkr"
TRADES_KIND = "smart_trades"
ADJUSTED_KIND = "smart_adjusted"
_CVR_SQL = (
    "SELECT namespace, code FROM controlled_vocabulary "
    "WHERE namespace IN ('bar_vendor', 'bar_kind')"
)
# Every recorded 1d answer of one raw series: the current ohlcv_raw row (last-wins by serve
# time, D-191-N) and the displaced values ohlcv_revision holds (old_close, served by the
# revision's request). A legacy row without a request keeps its served_at. Test callers never
# count.
_D1_ANSWERS_SQL = """
SELECT (r."timestamp" AT TIME ZONE 'UTC')::date AS bar_date, r.close,
       COALESCE(r.served_at, q.answered_at) AS served_at, q.fetch_run_id, q.route,
       TRUE AS current, NULL::text AS origin
FROM ohlcv_raw r LEFT JOIN ohlcv_request q ON q.request_id = r.request_id
WHERE r.symbol = $1 AND r.timeframe = '1d' AND r.vendor = $2 AND r.kind = $3
  AND (q.caller IS NULL OR q.caller NOT LIKE 'test-%')
UNION ALL
SELECT (v."timestamp" AT TIME ZONE 'UTC')::date, v.old_close, q.answered_at, q.fetch_run_id,
       q.route, FALSE, v.origin
FROM ohlcv_revision v JOIN ohlcv_request q ON q.request_id = v.request_id
WHERE v.symbol = $1 AND v.timeframe = '1d' AND v.vendor = $2 AND v.kind = $3
  AND q.caller NOT LIKE 'test-%'
"""
# The latest fetch run holding both series for a symbol (the --fetch-run-id default).
_D1_LATEST_RUN_SQL = (
    "SELECT r.fetch_run_id FROM ohlcv_request r "
    "WHERE r.symbol = $1 AND r.timeframe = '1d' AND r.route = 'SMART' "
    "AND r.outcome = 'bars' AND r.what_to_show IN ('TRADES', 'ADJUSTED_LAST') "
    "GROUP BY r.fetch_run_id HAVING count(DISTINCT r.what_to_show) = 2 "
    "ORDER BY max(r.answered_at) DESC LIMIT 1"
)


@dataclasses.dataclass(frozen=True)
class DividendEvent:
    ex_date: date
    amount: float
    prev_close: float
    yield_tolerance: float  # how far a re-derivation of this event may move its yield

    @property
    def dividend_yield(self) -> float:
        """amount / prev_close: unit-free, so a later split re-scaling the bars cannot break it."""
        return self.amount / self.prev_close


@dataclasses.dataclass(frozen=True)
class Derivation:
    events: list[DividendEvent]
    covered_from: date  # first and last ex-date examined
    covered_to: date
    n_downward_steps: int = 0
    n_unstable_steps: int = 0


def _positive(x: float) -> bool:
    return math.isfinite(x) and x > 0


def _yahoo_tolerance(dividend: float, prev_close: float) -> float:
    """A split makes Yahoo re-scale and re-round its history: closes to the cent, amounts to
    about six decimals. Bound the re-derived yield's move by both roundings."""
    return (dividend / prev_close) * (2 * _HALF_TICK / prev_close + 1e-6 / dividend)


def join_adjustment_pairs(
    trades: dict[date, float], adjusted: dict[date, float]
) -> list[tuple[date, float, float]]:
    """(day, TRADES close, ADJUSTED_LAST close) rows over the two series' overlap. Raises
    ValueError if a day inside the overlap is missing from either: the ratio step of a dividend
    on that day would otherwise land on the next common day, a wrong ex-date."""
    if not trades or not adjusted:
        raise ValueError("empty daily series")
    lo = max(min(trades), min(adjusted))
    hi = min(max(trades), max(adjusted))
    t_days = {d for d in trades if lo <= d <= hi}
    a_days = {d for d in adjusted if lo <= d <= hi}
    if t_days != a_days:
        raise ValueError(
            f"TRADES and ADJUSTED_LAST disagree on {len(t_days ^ a_days)} days in {lo}..{hi}"
        )
    return [(d, trades[d], adjusted[d]) for d in sorted(t_days)]


def require_cvr_codes(rows: Sequence[Any]) -> None:
    """Raise unless CVR holds the IBKR vendor and both raw kinds the writer reads (todo 504:
    the inputs are vocabulary, not an in-code route list)."""
    have = {(r["namespace"], r["code"]) for r in rows}
    want = {
        ("bar_vendor", IBKR_VENDOR),
        ("bar_kind", TRADES_KIND),
        ("bar_kind", ADJUSTED_KIND),
    }
    missing = sorted(want - have)
    if missing:
        raise RuntimeError(f"controlled_vocabulary lacks the dividend writer's inputs: {missing}")


def _run_values(rows: Sequence[Any], fetch_run_id: uuid.UUID, what: str) -> dict[date, Any]:
    """The answers one fetch run gave for a series that raw stored, by bar_date (route SMART).
    A superseded offer (older than raw when offered) was never stored and never counts
    (review of 191-10, finding 2). Rows are read in a fixed order (current first, then by serve
    time), so the result never depends on the query's row order. Identical repeats collapse;
    two different stored values for one day in one run raise."""
    out: dict[date, Any] = {}
    stored = [
        r
        for r in rows
        if r["fetch_run_id"] == fetch_run_id
        and r["route"] == "SMART"
        and r["origin"] != "superseded"
    ]
    for row in sorted(stored, key=lambda r: (not r["current"], r["served_at"], r["close"])):
        earlier = out.get(row["bar_date"])
        if earlier is not None and earlier["close"] != row["close"]:
            raise ValueError(
                f"fetch run {fetch_run_id} answered {what} {row['bar_date']} twice with "
                f"different closes ({earlier['close']} and {row['close']})"
            )
        out.setdefault(row["bar_date"], row)
    return out


def pair_d1_series(
    trades: Sequence[Any], adjusted: Sequence[Any], fetch_run_id: uuid.UUID
) -> tuple[dict[date, float], dict[date, float]]:
    """({bar_date: TRADES close}, {bar_date: ADJUSTED_LAST close}) for `fetch_run_id` from raw
    answers (_D1_ANSWERS_SQL rows). Pure.

    The ADJUSTED_LAST series is the run's own answers of complete sessions (a bar answered on
    its own UTC date may be forming, D-191-J): IBKR re-bases it with every new dividend, so
    one run is one basis. Each date's TRADES close pairs by D-191-D, read through the revision
    log:
    1. the run's own TRADES answer (same fetch_run_id through request_id, raw or revision);
    2. otherwise the TRADES value stored when the adjusted answer was served: the latest
       TRADES answer, current or displaced, served no later than it. A TRADES row restated
       after the adjusted serve never pairs; its displaced earlier value does. Last-wins raw
       keeps the request of the first serve on an unchanged re-serve, so step 1 alone would
       miss dates.
    Superseded offers (older than raw when offered) were never stored and never pair. A date
    with neither is left out, which join_adjustment_pairs refuses loudly inside the overlap.
    """
    adj = {
        day: row
        for day, row in _run_values(adjusted, fetch_run_id, "ADJUSTED_LAST").items()
        if day < row["served_at"].astimezone(UTC).date()
    }
    if not adj:
        raise ValueError(f"no ADJUSTED_LAST answers in fetch run {fetch_run_id}")
    own_trades = _run_values(trades, fetch_run_id, "TRADES")
    stored: dict[date, list[Any]] = {}
    for row in trades:
        if row["origin"] != "superseded" and row["served_at"] is not None:
            stored.setdefault(row["bar_date"], []).append(row)
    paired: dict[date, float] = {}
    for day, a in adj.items():
        if day in own_trades:
            paired[day] = own_trades[day]["close"]
            continue
        before = [r for r in stored.get(day, ()) if r["served_at"] <= a["served_at"]]
        if before:
            paired[day] = max(before, key=lambda r: r["served_at"])["close"]
    for day, row in own_trades.items():
        paired.setdefault(day, row["close"])
    if not paired:
        raise ValueError(f"no TRADES answers pair with fetch run {fetch_run_id}")
    return paired, {day: row["close"] for day, row in adj.items()}


def vanished_ex_dates(stored: set[date], derivation: Derivation) -> list[date]:
    """Stored ex-dates inside the new derivation's examined span that it no longer reports: the
    source moved or withdrew the event. Kept, the old row next to a moved one would count one
    dividend twice."""
    current = {e.ex_date for e in derivation.events}
    return sorted(
        d
        for d in stored
        if derivation.covered_from <= d <= derivation.covered_to and d not in current
    )


def _bound(close_a: float, close_b: float, margin: float) -> float:
    return margin * (_HALF_TICK / close_a + _HALF_TICK / close_b) * (1 + _FLOAT_SLACK)


def derive_ibkr_events(
    pairs: Sequence[tuple[date, float, float]], noise_margin: float, stable_sessions: int
) -> Derivation:
    """Dividend events from (day, TRADES close, ADJUSTED_LAST close) rows sorted by day.

    Pure. A step counts only if the two series are in lockstep around it: the ratio holds
    within the rounding bound for `stable_sessions` rows before the step and after it. Where
    IBKR's two series use different closing prices (measured: NVR 2004, ratio wandering 0.3% a
    day, up to 150x the bound) no step is stable and none becomes an event. Raises ValueError on
    too few rows or a non-positive price (skipping the row would attribute a dividend inside the
    gap to the wrong day).
    """
    k = stable_sessions
    if len(pairs) < 2 * k + 2:
        raise ValueError("too few daily rows")
    if not all(_positive(c) and _positive(a) for _, c, a in pairs):
        raise ValueError("non-finite or non-positive close in adjustment pairs")
    days = [d for d, _, _ in pairs]
    closes = [c for _, c, _ in pairs]
    ratios = [a / c for _, c, a in pairs]

    def flat(anchor: int, rows: range) -> bool:
        return all(
            abs(ratios[r] - ratios[anchor]) <= _bound(closes[r], closes[anchor], noise_margin)
            for r in rows
        )

    events: list[DividendEvent] = []
    n_down = n_unstable = 0
    # A step at i needs k rows before i - 1 and k rows after i to show the series in lockstep.
    for i in range(1 + k, len(pairs) - k):
        step = ratios[i] - ratios[i - 1]
        if abs(step) <= _bound(closes[i], closes[i - 1], noise_margin):
            continue
        if step < 0:
            n_down += 1
            continue
        if not (flat(i - 1, range(i - 1 - k, i - 1)) and flat(i, range(i + 1, i + 1 + k))):
            n_unstable += 1
            continue
        amount = closes[i - 1] * (1.0 - ratios[i - 1] / ratios[i])
        # A later fetch sees this ex-date at an equal or smaller ratio, so the bound at this
        # ratio covers both derivations.
        tolerance = ibkr_rounding_bound(closes[i - 1] * ratios[i - 1], noise_margin)
        events.append(DividendEvent(days[i], amount, closes[i - 1], tolerance))
    return Derivation(events, days[1 + k], days[-1 - k], n_down, n_unstable)


def derive_yahoo_events(rows: Sequence[tuple[date, float, float]]) -> Derivation:
    """Dividend events from Yahoo (day, split-adjusted close, dividend) rows sorted by day.

    Pure. A dividend needs the prior close for its yield, so row 0 is not examined. Raises
    ValueError on fewer than 2 rows or invalid values.
    """
    if not all(math.isfinite(d) and d >= 0 for _, _, d in rows):
        raise ValueError("non-finite or negative dividend in Yahoo history")
    # yfinance emits an empty (NaN) row for some untraded days, e.g. HUBB 1977-08-08. Harmless
    # unless it is the ex-date or the close a yield is taken from: then it must fail, never
    # become a NaN or wrong-day yield.
    for i, (day, close, dividend) in enumerate(rows):
        next_pays = i + 1 < len(rows) and rows[i + 1][2] > 0
        if not _positive(close) and (dividend > 0 or next_pays or math.isfinite(close)):
            raise ValueError(f"unusable close on {day} next to a dividend (or non-positive)")
    rows = [r for r in rows if _positive(r[1])]
    if len(rows) < 2:
        raise ValueError("too few daily rows")
    events = [
        DividendEvent(day, dividend, prev, _yahoo_tolerance(dividend, prev))
        for i, (day, _, dividend) in enumerate(rows)
        if i > 0 and dividend > 0
        for prev in (rows[i - 1][1],)
    ]
    return Derivation(events, rows[1][0], rows[-1][0])


def disagreeing_yields(existing: dict[date, float], derivation: Derivation) -> list[date]:
    """Ex-dates already stored (ex_date -> stored yield) whose re-derived yield moved by more
    than the event's own tolerance."""
    return [
        e.ex_date
        for e in derivation.events
        if e.ex_date in existing and abs(existing[e.ex_date] - e.dividend_yield) > e.yield_tolerance
    ]


@dataclasses.dataclass(frozen=True)
class Reconciliation:
    near_misses: list[tuple[date, date]]  # (ibkr ex-date, yahoo ex-date): one dividend, two dates
    yield_disagreements: list[date]
    ibkr_holes: list[date]  # yahoo events inside IBKR's examined span that IBKR lacks
    yahoo_holes: list[date]  # the reverse


def reconcile(
    ibkr: dict[date, float],
    yahoo_events: dict[date, float],
    ibkr_span: tuple[date, date] | None,
    yahoo_span: tuple[date, date] | None,
    match_days: int,
    rule: DisputeRule,
    ibkr_prev_close: dict[date, float],
) -> Reconciliation:
    """Compare two sources' stored events (ex_date -> yield) for one symbol. Pure. A yield
    disagreement is rule.disagree, the same predicate the research reader applies."""

    def inside(d: date, span: tuple[date, date] | None) -> bool:
        return span is not None and span[0] <= d <= span[1]

    ibkr_only = sorted(ibkr.keys() - yahoo_events.keys())
    yahoo_only = sorted(yahoo_events.keys() - ibkr.keys())
    near = [(i, y) for i in ibkr_only for y in yahoo_only if abs((i - y).days) <= match_days]
    near_dates = {i for i, _ in near} | {y for _, y in near}
    disagreements = sorted(
        d
        for d in ibkr.keys() & yahoo_events.keys()
        if rule.disagree(yahoo_events[d], ibkr[d], ibkr_prev_close[d])
    )
    return Reconciliation(
        near_misses=near,
        yield_disagreements=disagreements,
        ibkr_holes=[d for d in yahoo_only if d not in near_dates and inside(d, ibkr_span)],
        yahoo_holes=[d for d in ibkr_only if d not in near_dates and inside(d, yahoo_span)],
    )


class _SymbolFailure(Exception):
    """One symbol's fetch, derivation or write failed; the run continues and fails at the end."""


@dataclasses.dataclass(frozen=True)
class FailedSymbol:
    """One symbol's recorded failure (D-191-O per-name isolation): the successes of a pass are
    written, the failures are collected here, and the fraction of failed symbols gates the run's
    end state against threshold.dividend.max_failure_fraction (partial vs nonzero exit)."""

    symbol: str
    source: str  # "" for a write-phase failure (the whole symbol's transaction)
    reason: str


class DividendEventWriter(BaseBatch):
    """Batch service: IBKR and Yahoo -> dividend_events + dividend_event_coverage, reconciled."""

    job_name = _JOB
    compute_version = "1.1.0"  # 1.1.0: IBKR source reads D1 (185-21); 1.0.0 fetched live

    def __init__(
        self,
        db_dsn: str,
        settings: Settings,
        sources: list[str],
        fetch_run_id: uuid.UUID | None,
        symbols: list[str],
    ) -> None:
        super().__init__(db_dsn)
        self._settings = settings
        self._sources = sources
        self._fetch_run_id = fetch_run_id
        self._symbols = symbols

    def _record_failure(
        self, failed: list[FailedSymbol], symbol: str, source: str, error: _SymbolFailure
    ) -> None:
        """Collect one symbol's failure and log it (D-191-O): the reason is the exception's
        message, stringified once for both the record and the structured warning."""
        reason = str(error)
        failed.append(FailedSymbol(symbol, source, reason))
        self.logger.warning(
            "dividend_event_writer.symbol_failed", symbol=symbol, source=source, reason=reason
        )

    async def execute(self, pool: asyncpg.Pool) -> None:
        async with pool.acquire() as conn:
            apr = await load_apr_dict_async(
                conn, ["threshold.dividend_event.%", "threshold.dividend.%"]
            )
            if SOURCE_IBKR in self._sources:
                require_cvr_codes(await conn.fetch(_CVR_SQL))
        margin = float(_cfg(apr, "threshold.dividend_event.noise_margin", 1.25))
        stable = int(_cfg(apr, "threshold.dividend_event.stable_sessions", 3))
        match_days = int(_cfg(apr, "threshold.dividend_event.ex_date_match_days", 5))
        rel_tol = float(_cfg(apr, "threshold.dividend_event.source_yield_rel_tolerance", 0.10))
        max_failure_fraction = float(_cfg(apr, "threshold.dividend.max_failure_fraction", 0.05))

        instruments = [
            i
            for i in get_active_contracts(self._settings, dimension="backfill")
            if i.asset_class == AssetClass.EQUITY
            and (not self._symbols or i.symbol in self._symbols)
        ]

        failed: list[FailedSymbol] = []
        totals = dict.fromkeys(
            (
                "events",
                "downward",
                "unstable",
                "rederived_moved",
                "disputes",
                "yield_disagreements",
                "ibkr_holes",
                "yahoo_holes",
            ),
            0,
        )
        for instrument in instruments:
            symbol = instrument.symbol
            derivations: dict[str, Derivation] = {}
            run_id = self._fetch_run_id
            for source in self._sources:
                try:
                    if source == SOURCE_IBKR:
                        async with pool.acquire() as conn:
                            run_id = await self._resolve_fetch_run(conn, symbol, self._fetch_run_id)
                            derivations[source] = await self._derive(
                                conn, instrument, source, run_id, margin, stable
                            )
                    else:
                        derivations[source] = await self._derive(
                            None, instrument, source, None, margin, stable
                        )
                except _SymbolFailure as error:
                    self._record_failure(failed, symbol, source, error)
            if not derivations:
                continue
            # One transaction per symbol, reconciliation included: a near miss (one
            # dividend on two dates) becomes a dispute record here, keeping both events.
            try:
                async with pool.acquire() as conn, conn.transaction():
                    moved = 0
                    for source, derivation in derivations.items():
                        moved += await self._write(conn, symbol, source, derivation)
                    rec = await self._reconcile(
                        conn, symbol, match_days, DisputeRule(rel_tol, margin)
                    )
                    disputes = disputed_dates(symbol, rec.near_misses) if rec.near_misses else []
                    if disputes:
                        await self._write_disputes(conn, disputes, run_id)
            except _SymbolFailure as error:
                self._record_failure(failed, symbol, "", error)
                continue
            for derivation in derivations.values():
                totals["events"] += len(derivation.events)
                totals["downward"] += derivation.n_downward_steps
                totals["unstable"] += derivation.n_unstable_steps
                if derivation.n_downward_steps or derivation.n_unstable_steps:
                    self.logger.warning(
                        "dividend_event_writer.rejected_steps",
                        symbol=symbol,
                        downward=derivation.n_downward_steps,
                        unstable=derivation.n_unstable_steps,
                    )
            totals["rederived_moved"] += moved
            totals["disputes"] += len(disputes)
            if disputes:
                self.logger.warning(
                    "dividend_event_writer.date_disputes",
                    symbol=symbol,
                    disputes=[
                        f"{d.first_date}..{d.last_date} "
                        + "/".join(f"{s}={day}" for s, day in sorted(d.dates_by_source.items()))
                        for d in disputes
                    ],
                )
            totals["yield_disagreements"] += len(rec.yield_disagreements)
            totals["ibkr_holes"] += len(rec.ibkr_holes)
            totals["yahoo_holes"] += len(rec.yahoo_holes)
            if rec.yield_disagreements or rec.yahoo_holes:
                self.logger.warning(
                    "dividend_event_writer.reconciliation",
                    symbol=symbol,
                    yield_disagreements=[str(d) for d in rec.yield_disagreements],
                    yahoo_holes=[str(d) for d in rec.yahoo_holes],
                    ibkr_holes=len(rec.ibkr_holes),
                )

        self.logger.info(
            "dividend_event_writer.done",
            symbols=len(instruments),
            sources=self._sources,
            failed=len(failed),
            fetch_run_id=str(self._fetch_run_id) if self._fetch_run_id else "latest-per-symbol",
            **totals,
        )
        sources = ",".join(self._sources)
        for outcome, n in {**totals, "failed": len(failed)}.items():
            _OUTCOME_TOTAL.add(n, {"sources": sources, "outcome": outcome})
        # Per-name isolation (D-191-O): a minority of dead or thin names must not poison the
        # unit while the data work of the other ~1,525 completed. The run still ends loud: the
        # per-name failures are logged as they happen, and a nonzero failure fraction turns the
        # pass into a nonzero exit instead of a partial completion.
        failed_symbols = {f.symbol for f in failed}
        failure_fraction = len(failed_symbols) / len(instruments) if instruments else 0.0
        if failed_symbols:
            if failure_fraction > max_failure_fraction:
                raise RuntimeError(
                    f"dividend_event_writer: {len(failed_symbols)}/{len(instruments)} symbols "
                    f"failed (fraction {failure_fraction:.4f} exceeds "
                    f"threshold.dividend.max_failure_fraction {max_failure_fraction}): {failed}"
                )
            self.completion_status = "partial"
            self.logger.warning(
                "dividend_event_writer.partial_run",
                failed_symbols=len(failed_symbols),
                symbols=len(instruments),
                failure_fraction=round(failure_fraction, 6),
                max_failure_fraction=max_failure_fraction,
            )

    @staticmethod
    async def _resolve_fetch_run(
        conn: asyncpg.Connection, symbol: str, requested: uuid.UUID | None = None
    ) -> uuid.UUID:
        """The D1 fetch run to read for `symbol`: the requested one, or the latest run
        holding both a TRADES and an ADJUSTED_LAST answer. Raises _SymbolFailure."""
        if requested is not None:
            return requested
        row = await conn.fetchrow(_D1_LATEST_RUN_SQL, symbol)
        if row is None:
            raise _SymbolFailure("no fetch run with both TRADES and ADJUSTED_LAST observations")
        return row["fetch_run_id"]

    @staticmethod
    async def _derive(
        conn: asyncpg.Connection | None,
        instrument,
        source: str,
        run_id: uuid.UUID | None,
        margin: float,
        stable: int,
    ) -> Derivation:
        """Read one source for one symbol and derive its events; raises _SymbolFailure.

        The IBKR branch reads the TRADES and ADJUSTED_LAST raw series instead of fetching
        them and pairs them for `run_id` (pair_d1_series, D-191-D): the adjusted series is
        one run's, because IBKR re-bases ADJUSTED_LAST on every new dividend."""
        symbol = instrument.symbol
        if source == SOURCE_YAHOO:
            rows, error = await yahoo.fetch_daily_close_and_dividends(symbol)
            if error is not None:
                raise _SymbolFailure(error)
            try:
                return derive_yahoo_events(rows)
            except ValueError as invalid:
                raise _SymbolFailure(str(invalid)) from invalid
        assert conn is not None and run_id is not None
        trades_rows = await conn.fetch(_D1_ANSWERS_SQL, symbol, IBKR_VENDOR, TRADES_KIND)
        adjusted_rows = await conn.fetch(_D1_ANSWERS_SQL, symbol, IBKR_VENDOR, ADJUSTED_KIND)
        try:
            trades, adjusted = pair_d1_series(trades_rows, adjusted_rows, run_id)
            return derive_ibkr_events(join_adjustment_pairs(trades, adjusted), margin, stable)
        except ValueError as invalid:
            raise _SymbolFailure(str(invalid)) from invalid

    async def _write_disputes(
        self,
        conn: asyncpg.Connection,
        disputes: Sequence,
        run_id: uuid.UUID | None,
    ) -> None:
        """Record near-miss pairs as dividend_date_dispute rows in the caller's
        transaction. First recording wins (ON CONFLICT DO NOTHING): a dispute replayed
        on a rerun keeps its original recorded_at."""
        await conn.executemany(
            "INSERT INTO dividend_date_dispute "
            "(symbol, first_date, last_date, dates_by_source, fetch_run_id) "
            "VALUES ($1, $2, $3, $4::text::jsonb, $5) ON CONFLICT DO NOTHING",
            [
                (
                    d.symbol,
                    d.first_date,
                    d.last_date,
                    json.dumps({s: day.isoformat() for s, day in d.dates_by_source.items()}),
                    run_id,
                )
                for d in disputes
            ],
        )

    async def _write(
        self, conn: asyncpg.Connection, symbol: str, source: str, derivation: Derivation
    ) -> int:
        """Insert new events and extend coverage in the caller's transaction; returns how many
        re-derived events moved their yield. Raises _SymbolFailure when the window starts after
        the stored coverage ends: extending over the gap would claim days nobody examined."""
        stored = await conn.fetchrow(
            "SELECT covered_from, covered_to FROM dividend_event_coverage "
            "WHERE symbol = $1 AND source = $2",
            symbol,
            source,
        )
        if stored is not None and derivation.covered_from > stored["covered_to"]:
            raise _SymbolFailure(
                f"{source} window starts {derivation.covered_from}, after stored coverage ends "
                f"{stored['covered_to']}; rerun with a larger --years"
            )
        existing = {
            r["ex_date"]: r["dividend_yield"]
            for r in await conn.fetch(
                "SELECT ex_date, amount / prev_close AS dividend_yield "
                "FROM dividend_events WHERE symbol = $1 AND source = $2",
                symbol,
                source,
            )
        }
        vanished = vanished_ex_dates(set(existing), derivation)
        if vanished:
            raise _SymbolFailure(
                f"{source} no longer reports stored ex-dates {[str(d) for d in vanished]}; "
                "resolve by hand (a moved date would double count)"
            )
        moved = disagreeing_yields(existing, derivation)
        if moved:
            self.logger.warning(
                "dividend_event_writer.rederived_yield_moved",
                symbol=symbol,
                source=source,
                ex_dates=[str(d) for d in moved],
            )
        await conn.executemany(
            "INSERT INTO dividend_events "
            "(symbol, ex_date, source, amount, prev_close, compute_version) "
            "VALUES ($1, $2, $3, $4, $5, $6)",
            [
                (symbol, e.ex_date, source, e.amount, e.prev_close, self.compute_version)
                for e in derivation.events
                if e.ex_date not in existing
            ],
        )
        await conn.execute(
            "INSERT INTO dividend_event_coverage "
            "(symbol, source, covered_from, covered_to, checked_at) "
            "VALUES ($1, $2, $3, $4, $5) ON CONFLICT (symbol, source) DO UPDATE SET "
            "covered_from = LEAST(dividend_event_coverage.covered_from, EXCLUDED.covered_from), "
            "covered_to = GREATEST(dividend_event_coverage.covered_to, EXCLUDED.covered_to), "
            "checked_at = EXCLUDED.checked_at",
            symbol,
            source,
            derivation.covered_from,
            derivation.covered_to,
            datetime.now(UTC),
        )
        return len(moved)

    @staticmethod
    async def _reconcile(
        conn: asyncpg.Connection, symbol: str, match_days: int, rule: DisputeRule
    ) -> Reconciliation:
        events: dict[str, dict[date, float]] = {SOURCE_IBKR: {}, SOURCE_YAHOO: {}}
        ibkr_prev_close: dict[date, float] = {}
        for r in await conn.fetch(
            "SELECT source, ex_date, amount / prev_close AS y, prev_close FROM dividend_events "
            f"WHERE symbol = $1 AND source IN {_RECONCILED_SOURCES}",
            symbol,
        ):
            events[r["source"]][r["ex_date"]] = r["y"]
            if r["source"] == SOURCE_IBKR:
                ibkr_prev_close[r["ex_date"]] = r["prev_close"]
        spans = {
            r["source"]: (r["covered_from"], r["covered_to"])
            for r in await conn.fetch(
                "SELECT source, covered_from, covered_to FROM dividend_event_coverage "
                f"WHERE symbol = $1 AND source IN {_RECONCILED_SOURCES}",
                symbol,
            )
        }
        return reconcile(
            events[SOURCE_IBKR],
            events[SOURCE_YAHOO],
            spans.get(SOURCE_IBKR),
            spans.get(SOURCE_YAHOO),
            match_days,
            rule,
            ibkr_prev_close,
        )


# The latest capture of the full Massive dividend list (every page of one manifest).
_MASSIVE_PAGES_SQL = """
SELECT reference_raw_id, page, manifest_path, served_at, http_status FROM reference_raw_current
WHERE vendor = 'massive' AND endpoint = 'dividends' AND request_key = 'all'
ORDER BY page
"""
_MASSIVE_BODY_SQL = "SELECT body::text FROM reference_raw WHERE reference_raw_id = $1"
_MASSIVE_SPANS_SQL = (
    "SELECT ticker_event_id::text, symbol, ticker, valid_from, valid_to FROM ticker_event_current "
    "WHERE vendor = 'massive'"
)
# Raw Massive 1d closes (session date = the UTC date of the bar's midnight-ET stamp) for a
# chunk of symbols. Raw, not canonical: Massive's cash amount is in the units of its ex-date,
# and so is the raw close before it (canonical is split-adjusted to today), so the yield is
# unit-free. Read whole per symbol chunk: a per-event lateral lookup decompresses a chunk per
# row (measured 2026-11-21: about 40 s per 5,000 events, an hour for the capture).
_MASSIVE_RAW_CLOSES_SQL = """
SELECT symbol, ("timestamp" AT TIME ZONE 'UTC')::date AS bar_date, close FROM ohlcv_raw
WHERE symbol = ANY($1::text[]) AND timeframe = '1d' AND vendor = 'massive' AND kind = 'sip_flat'
ORDER BY symbol, "timestamp"
"""
_MASSIVE_SYMBOL_CHUNK = 200  # symbols per raw read (ANY arrays go superlinear when large)
_MEMBER_MONTHS_SQL = "SELECT symbol, as_of FROM universe_membership"
_MASSIVE_STORED_CLAIMS_SQL = (
    f"SELECT symbol FROM dividend_event_coverage WHERE source = '{SOURCE_MASSIVE}'"
)


@dataclasses.dataclass(frozen=True)
class MassiveCapture:
    """The capture a Massive load reads: its manifest, the date it was served (no ex-date
    after it is knowable from it) and the reference_raw row of each page."""

    manifest_path: str
    capture_date: date
    page_ids: dict[int, uuid.UUID]


def massive_capture(rows: Sequence[Any]) -> MassiveCapture:
    """Validate the page rows of the latest capture: one manifest, pages 1..N without a gap,
    every answer HTTP 200. Raises RuntimeError otherwise (a partial capture would read as
    missing dividends)."""
    if not rows:
        raise RuntimeError("no Massive dividend capture in reference_raw_current")
    manifests = {r["manifest_path"] for r in rows}
    pages = [r["page"] for r in rows]
    if len(manifests) != 1:
        raise RuntimeError(f"Massive dividend capture spans manifests {sorted(manifests)}")
    if pages != list(range(1, len(rows) + 1)):
        raise RuntimeError(f"Massive dividend capture pages are not 1..{len(rows)}")
    bad = [r["page"] for r in rows if r["http_status"] != 200]
    if bad:
        raise RuntimeError(f"Massive dividend capture pages without HTTP 200: {bad}")
    return MassiveCapture(
        manifest_path=manifests.pop(),
        capture_date=max(r["served_at"] for r in rows).astimezone(UTC).date(),
        page_ids={r["page"]: r["reference_raw_id"] for r in rows},
    )


def prior_closes(
    bars: Sequence[tuple[date, float]], ex_dates: Sequence[date], max_age_days: int
) -> dict[date, float]:
    """{ex_date: close of the last bar strictly before it} from (session date, close) bars
    sorted by date, for the ex-dates whose prior bar is at most `max_age_days` calendar days
    older. Pure."""
    days = [d for d, _ in bars]
    out = {}
    for ex in ex_dates:
        i = bisect.bisect_left(days, ex) - 1
        if i >= 0 and (ex - days[i]).days <= max_age_days:
            out[ex] = bars[i][1]
    return out


@dataclasses.dataclass(frozen=True)
class MassiveSymbolLoad:
    """One symbol's Massive rows: events with their raw prior close, and the coverage claim."""

    symbol: str
    events: list[tuple[massive_dividends.MassiveEvent, float]]
    claim: massive_dividends.Coverage


def plan_massive_loads(
    collapsed: massive_dividends.Collapsed,
    spans: massive_dividends.SpanIndex,
    prev_close: dict[str, dict[date, float]],
    instruments: set[str],
    capture_date: date,
) -> tuple[list[MassiveSymbolLoad], collections.Counter]:
    """Per-symbol loads from collapsed events. Pure. An event without a prior close is dropped
    and its ex-date becomes a hole; a symbol missing from instruments is dropped whole (its
    rows could not reference it). Returns the loads (sorted by symbol) and the event-level
    drop counts."""
    drops: collections.Counter = collections.Counter()
    loads = []
    for symbol in sorted(collapsed.reported_dates):
        events = collapsed.events.get(symbol, [])
        if symbol not in instruments:
            drops["no_instrument"] += len(events)
            continue
        kept = []
        dropped = set(collapsed.dropped_dates.get(symbol, ()))
        for event in events:
            close = prev_close.get(symbol, {}).get(event.ex_date)
            if close is None or not _positive(close):
                drops[massive_dividends.DROP_NO_PREV_CLOSE] += 1
                dropped.add(event.ex_date)
            else:
                kept.append((event, close))
        claim = massive_dividends.coverage(
            collapsed.reported_dates[symbol], dropped, spans.by_symbol[symbol], capture_date
        )
        if claim is None:  # unreachable: the symbol reported at least one ex-date
            raise RuntimeError(f"{symbol}: reported ex-dates but no coverage claim")
        loads.append(MassiveSymbolLoad(symbol, kept, claim))
    return loads, drops


def covered_member_months(
    loads: Sequence[MassiveSymbolLoad], member_months: Sequence[Any]
) -> list[tuple[str, date]]:
    """The (symbol, month-end) universe members whose month-end date the claims cover. Pure."""
    claims = {load.symbol: load.claim for load in loads}
    return [
        (r["symbol"], r["as_of"])
        for r in member_months
        if r["symbol"] in claims and claims[r["symbol"]].covers(r["as_of"])
    ]


class MassiveDividendWriter(BaseBatch):
    """Batch service: the Massive dividend capture -> dividend_events, dividend_event_coverage
    and dividend_event_coverage_gap (source massive). Idempotent: a rerun on the same capture
    inserts nothing and rewrites each claim to the same values. --dry-run reads everything,
    reports the counts and writes nothing."""

    job_name = _JOB
    compute_version = f"massive-1.0.0+{massive_dividends.RULE_ID}"

    def __init__(self, db_dsn: str, symbols: list[str], dry_run: bool) -> None:
        super().__init__(db_dsn)
        self._symbols = set(symbols)
        self._dry_run = dry_run

    async def execute(self, pool: asyncpg.Pool) -> None:
        async with pool.acquire() as conn:
            apr = await load_apr_dict_async(
                conn, ["threshold.dividend_event.%", "threshold.dividend.%"]
            )
            max_age = int(_cfg(apr, "threshold.dividend_event.prev_close_max_age_days", 7))
            max_failure_fraction = float(_cfg(apr, "threshold.dividend.max_failure_fraction", 0.05))
            capture = massive_capture(await conn.fetch(_MASSIVE_PAGES_SQL))
            spans = massive_dividends.SpanIndex(
                TickerSpan(
                    r["ticker_event_id"], r["symbol"], r["ticker"], r["valid_from"], r["valid_to"]
                )
                for r in await conn.fetch(_MASSIVE_SPANS_SQL)
            )
            instruments = {r["symbol"] for r in await conn.fetch("SELECT symbol FROM instruments")}
            records: list[massive_dividends.DividendRecord] = []
            for page, raw_id in sorted(capture.page_ids.items()):
                body = json.loads(await conn.fetchval(_MASSIVE_BODY_SQL, raw_id))
                records += massive_dividends.parse_page(body, page)
            collapsed = massive_dividends.collapse_events(records, spans, capture.capture_date)
            if self._symbols:
                collapsed = _only_symbols(collapsed, self._symbols)
            prev_close = await self._prev_closes(conn, collapsed, instruments, max_age)
            loads, event_drops = plan_massive_loads(
                collapsed, spans, prev_close, instruments, capture.capture_date
            )
            member_months = await conn.fetch(_MEMBER_MONTHS_SQL)

        covered = covered_member_months(loads, member_months)
        summary = {
            "manifest": capture.manifest_path,
            "capture_date": str(capture.capture_date),
            "records": len(records),
            "record_drops": dict(sorted(collapsed.drops.items())),
            "event_drops": dict(sorted(event_drops.items())),
            "events": sum(len(load.events) for load in loads),
            "names": len(loads),
            "holes": sum(len(load.claim.holes) for load in loads),
            "member_months_covered": len(covered),
            "member_years_covered": len({(s, d.year) for s, d in covered}),
            "dry_run": self._dry_run,
        }
        self.logger.info("dividend_event_writer.massive_plan", **summary)
        print(json.dumps(summary, indent=2, default=str))  # noqa: T201 - operator-facing counts
        for reason, n in {**collapsed.drops, **event_drops}.items():
            _OUTCOME_TOTAL.add(n, {"sources": SOURCE_MASSIVE, "outcome": f"dropped_{reason}"})
        if self._dry_run:
            self.completion_status = "dry_run"
            return

        failed: list[FailedSymbol] = []
        inserted = moved = 0
        for load in loads:
            try:
                async with pool.acquire() as conn, conn.transaction():
                    n_new, n_moved = await self._write_symbol(
                        conn, load, capture.manifest_path, capture.page_ids
                    )
            except _SymbolFailure as error:
                self._record_failure(failed, load.symbol, str(error))
                continue
            inserted += n_new
            moved += n_moved
        # A stored claim whose symbol left the capture (spans retired or remapped) cannot be
        # refreshed from it; it fails loud rather than standing on an old capture.
        async with pool.acquire() as conn:
            stored = {r["symbol"] for r in await conn.fetch(_MASSIVE_STORED_CLAIMS_SQL)}
        loaded = {load.symbol for load in loads}
        for symbol in sorted(stored - loaded):
            if self._symbols and symbol not in self._symbols:
                continue
            self._record_failure(
                failed,
                symbol,
                "stored massive claim, symbol no longer in the capture; resolve by hand",
            )
        self.logger.info(
            "dividend_event_writer.massive_done",
            names=len(loads),
            inserted=inserted,
            rederived_moved=moved,
            failed=len(failed),
        )
        for outcome, n in {
            "events": inserted,
            "rederived_moved": moved,
            "failed": len(failed),
        }.items():
            _OUTCOME_TOTAL.add(n, {"sources": SOURCE_MASSIVE, "outcome": outcome})
        if failed:
            attempted = len(loaded | {f.symbol for f in failed})
            fraction = len(failed) / attempted
            if fraction > max_failure_fraction:
                raise RuntimeError(
                    f"dividend_event_writer massive: {len(failed)}/{attempted} symbols failed "
                    f"(fraction {fraction:.4f} exceeds threshold.dividend.max_failure_fraction "
                    f"{max_failure_fraction}): {failed[:20]}"
                )
            self.logger.warning(
                "dividend_event_writer.partial_run",
                failed_symbols=len(failed),
                symbols=attempted,
                failure_fraction=round(fraction, 6),
                max_failure_fraction=max_failure_fraction,
            )
            self.completion_status = "partial"

    def _record_failure(self, failed: list[FailedSymbol], symbol: str, reason: str) -> None:
        """Collect one symbol's failure and log it, as the Yahoo and IBKR path does."""
        failed.append(FailedSymbol(symbol, SOURCE_MASSIVE, reason))
        self.logger.warning(
            "dividend_event_writer.symbol_failed",
            symbol=symbol,
            source=SOURCE_MASSIVE,
            reason=reason,
        )

    @staticmethod
    async def _prev_closes(
        conn: asyncpg.Connection,
        collapsed: massive_dividends.Collapsed,
        instruments: set[str],
        max_age: int,
    ) -> dict[str, dict[date, float]]:
        """{symbol: {ex_date: raw prior close}} for every storable collapsed event, one symbol
        chunk at a time (only the chunk's bars are held)."""
        symbols = sorted(s for s, events in collapsed.events.items() if events and s in instruments)
        out: dict[str, dict[date, float]] = {}
        for i in range(0, len(symbols), _MASSIVE_SYMBOL_CHUNK):
            chunk = symbols[i : i + _MASSIVE_SYMBOL_CHUNK]
            bars: dict[str, list[tuple[date, float]]] = {}
            for r in await conn.fetch(_MASSIVE_RAW_CLOSES_SQL, chunk):
                bars.setdefault(r["symbol"], []).append((r["bar_date"], r["close"]))
            for symbol in chunk:
                days = [e.ex_date for e in collapsed.events[symbol]]
                out[symbol] = prior_closes(bars.get(symbol, []), days, max_age)
        return out

    async def _write_symbol(
        self,
        conn: asyncpg.Connection,
        load: MassiveSymbolLoad,
        manifest_path: str,
        page_ids: dict[int, uuid.UUID],
    ) -> tuple[int, int]:
        """Insert new events, replace the claim and its holes, in the caller's transaction.
        First derivation wins for events (a moved yield is logged, never overwritten); the
        claim is a function of the capture, so it is replaced. Raises _SymbolFailure when a
        stored event is no longer in the capture (a moved date would double count)."""
        symbol = load.symbol
        existing = {
            r["ex_date"]: r["dividend_yield"]
            for r in await conn.fetch(
                "SELECT ex_date, amount / prev_close AS dividend_yield FROM dividend_events "
                "WHERE symbol = $1 AND source = $2",
                symbol,
                SOURCE_MASSIVE,
            )
        }
        current = {event.ex_date: event.amount / close for event, close in load.events}
        vanished = sorted(set(existing) - set(current))
        if vanished:
            raise _SymbolFailure(
                f"massive no longer reports stored ex-dates {[str(d) for d in vanished]}; "
                "resolve by hand (a moved date would double count)"
            )
        moved = [d for d, y in existing.items() if not math.isclose(y, current[d], rel_tol=1e-9)]
        if moved:
            self.logger.warning(
                "dividend_event_writer.rederived_yield_moved",
                symbol=symbol,
                source=SOURCE_MASSIVE,
                ex_dates=[str(d) for d in sorted(moved)],
            )
        new = [(event, close) for event, close in load.events if event.ex_date not in existing]
        await conn.executemany(
            "INSERT INTO dividend_events (symbol, ex_date, source, amount, prev_close, "
            "compute_version, declared_on, vendor_record_ids, reference_raw_ids) "
            "VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)",
            [
                (
                    symbol,
                    event.ex_date,
                    SOURCE_MASSIVE,
                    event.amount,
                    close,
                    self.compute_version,
                    event.declared_on,
                    list(event.record_ids),
                    [page_ids[p] for p in event.pages],
                )
                for event, close in new
            ],
        )
        claim = load.claim
        await conn.execute(
            "INSERT INTO dividend_event_coverage (symbol, source, covered_from, covered_to, "
            "checked_at, reference_capture, rule_id) VALUES ($1, $2, $3, $4, $5, $6, $7) "
            "ON CONFLICT (symbol, source) DO UPDATE SET covered_from = EXCLUDED.covered_from, "
            "covered_to = EXCLUDED.covered_to, checked_at = EXCLUDED.checked_at, "
            "reference_capture = EXCLUDED.reference_capture, rule_id = EXCLUDED.rule_id",
            symbol,
            SOURCE_MASSIVE,
            claim.covered_from,
            claim.covered_to,
            datetime.now(UTC),
            manifest_path,
            massive_dividends.RULE_ID,
        )
        await conn.execute(
            "DELETE FROM dividend_event_coverage_gap WHERE symbol = $1 AND source = $2",
            symbol,
            SOURCE_MASSIVE,
        )
        await conn.executemany(
            "INSERT INTO dividend_event_coverage_gap (symbol, source, gap_from, gap_to, reasons) "
            "VALUES ($1, $2, $3, $4, $5)",
            [(symbol, SOURCE_MASSIVE, h.gap_from, h.gap_to, list(h.reasons)) for h in claim.holes],
        )
        return len(new), len(moved)


def _only_symbols(
    collapsed: massive_dividends.Collapsed, symbols: set[str]
) -> massive_dividends.Collapsed:
    """The collapsed capture restricted to `symbols` (a --symbols run); drop counts stay whole."""
    return massive_dividends.Collapsed(
        events={s: v for s, v in collapsed.events.items() if s in symbols},
        reported_dates={s: v for s, v in collapsed.reported_dates.items() if s in symbols},
        dropped_dates={s: v for s, v in collapsed.dropped_dates.items() if s in symbols},
        drops=collapsed.drops,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Derive and reconcile dividend events")
    parser.add_argument(
        "--sources", nargs="+", choices=sorted(_CLI_SOURCES), default=_DEFAULT_CLI_SOURCES
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="massive only: read the capture and report the counts, write nothing",
    )
    parser.add_argument(
        "--fetch-run-id",
        type=uuid.UUID,
        default=None,
        help="D1 fetch run to read the IBKR series from (default: latest paired run per symbol)",
    )
    parser.add_argument("--symbols", nargs="*", default=[], help="limit to these symbols")
    args = parser.parse_args()
    try:
        init_otel_providers(f"indicagent-{_JOB}")
    except OTelInitError:
        pass
    settings = Settings()
    db_dsn = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
    sources = [_CLI_SOURCES[s] for s in args.sources]
    if SOURCE_MASSIVE in sources:
        if len(sources) > 1:
            parser.error("--sources massive runs alone")
        writer: BaseBatch = MassiveDividendWriter(db_dsn, args.symbols, args.dry_run)
    else:
        if args.dry_run:
            parser.error("--dry-run applies to --sources massive only")
        writer = DividendEventWriter(db_dsn, settings, sources, args.fetch_run_id, args.symbols)
    asyncio.run(writer.run())


if __name__ == "__main__":
    main()
