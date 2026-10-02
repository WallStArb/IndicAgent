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
ADJUSTED_LAST closes D1 stored for one fetch run (ohlcv_observation, route SMART), never from a
live IBKR fetch. IBKR's ADJUSTED_LAST close is the TRADES close times a cumulative dividend
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

Usage:
    python services/dividend_event_writer.py                          # both sources
    python services/dividend_event_writer.py --sources yahoo          # nightly-cheap
    python services/dividend_event_writer.py --sources ibkr --fetch-run-id <uuid>
"""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import json
import math
import uuid
from collections.abc import Sequence
from datetime import UTC, date, datetime

import asyncpg

from services._batch_utils import cfg as _cfg
from services._batch_utils import load_apr_dict_async
from src.config.settings import Settings, get_active_contracts
from src.core.agent.base_batch import BaseBatch
from src.core.models import AssetClass
from src.intelligence.bars.corporate_actions import disputed_dates
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
_CLI_SOURCES = {"ibkr": SOURCE_IBKR, "yahoo": SOURCE_YAHOO}
# ADJUSTED_LAST is quoted to the cent: half a cent of rounding per close.
_HALF_TICK = 0.005
# The rounding bound is attained exactly when an unrounded adjusted close ends in half a cent;
# this relative slack keeps floating-point error at that tie from reading as a step.
_FLOAT_SLACK = 1e-9
# One D1 series (TRADES or ADJUSTED_LAST closes) for one symbol and fetch run: the two series
# pair only within one fetch_run_id, because IBKR re-bases ADJUSTED_LAST on every new dividend.
_D1_SERIES_SQL = (
    "SELECT r.fetch_run_id, o.bar_date, o.close FROM ohlcv_observation o "
    "JOIN ohlcv_request r ON r.request_id = o.request_id "
    "WHERE o.symbol = $1 AND r.timeframe = '1d' AND r.route = 'SMART' "
    "AND r.what_to_show = $2 AND r.outcome = 'bars' AND r.fetch_run_id = $3 "
    "ORDER BY o.bar_date"
)
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


def d1_close_series(
    rows: Sequence[tuple[uuid.UUID, date, float]], fetch_run_id: uuid.UUID
) -> dict[date, float]:
    """{bar_date: close} from one D1 series (fetch_run_id, bar_date, close rows). Pure.

    Refuses a row from any other fetch run: TRADES and ADJUSTED_LAST pair only within
    one run, and a cross-run pair would step the ratio at re-basing seams, not dividends.
    Refuses an empty series and a duplicate bar_date (two requests of one run answering
    the same day would silently pick one close).
    """
    if not rows:
        raise ValueError(f"no observations in fetch run {fetch_run_id}")
    closes: dict[date, float] = {}
    for run_id, bar_date, close in rows:
        if run_id != fetch_run_id:
            raise ValueError(
                f"observation from fetch run {run_id} inside series for {fetch_run_id}: "
                "TRADES and ADJUSTED_LAST pair only within one fetch run"
            )
        if bar_date in closes:
            raise ValueError(f"duplicate observation for {bar_date} in fetch run {fetch_run_id}")
        closes[bar_date] = close
    return closes


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

    async def execute(self, pool: asyncpg.Pool) -> None:
        async with pool.acquire() as conn:
            apr = await load_apr_dict_async(conn, ["threshold.dividend_event.%"])
        margin = float(_cfg(apr, "threshold.dividend_event.noise_margin", 1.25))
        stable = int(_cfg(apr, "threshold.dividend_event.stable_sessions", 3))
        match_days = int(_cfg(apr, "threshold.dividend_event.ex_date_match_days", 5))
        rel_tol = float(_cfg(apr, "threshold.dividend_event.source_yield_rel_tolerance", 0.10))

        instruments = [
            i
            for i in get_active_contracts(self._settings, dimension="backfill")
            if i.asset_class == AssetClass.EQUITY
            and (not self._symbols or i.symbol in self._symbols)
        ]

        failed: list[str] = []
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
                    failed.append(f"{symbol}/{source}: {error}")
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
                failed.append(f"{symbol}: {error}")
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
        if failed:
            raise RuntimeError(f"dividend_event_writer: {len(failed)} failures: {failed}")

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

        The IBKR branch reads the paired TRADES and ADJUSTED_LAST closes D1 holds for
        `run_id` (route SMART) instead of fetching them: both series come from one fetch
        run, because IBKR re-bases ADJUSTED_LAST on every new dividend."""
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
        trades_rows = await conn.fetch(_D1_SERIES_SQL, symbol, "TRADES", run_id)
        if not trades_rows:
            raise _SymbolFailure(f"no TRADES observations for {symbol} in fetch run {run_id}")
        adjusted_rows = await conn.fetch(_D1_SERIES_SQL, symbol, "ADJUSTED_LAST", run_id)
        if not adjusted_rows:
            raise _SymbolFailure(
                f"no ADJUSTED_LAST observations for {symbol} in fetch run {run_id}"
            )
        try:
            return derive_ibkr_events(
                join_adjustment_pairs(
                    d1_close_series(trades_rows, run_id),
                    d1_close_series(adjusted_rows, run_id),
                ),
                margin,
                stable,
            )
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
            "WHERE symbol = $1",
            symbol,
        ):
            events[r["source"]][r["ex_date"]] = r["y"]
            if r["source"] == SOURCE_IBKR:
                ibkr_prev_close[r["ex_date"]] = r["prev_close"]
        spans = {
            r["source"]: (r["covered_from"], r["covered_to"])
            for r in await conn.fetch(
                "SELECT source, covered_from, covered_to FROM dividend_event_coverage "
                "WHERE symbol = $1",
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


def main() -> None:
    parser = argparse.ArgumentParser(description="Derive and reconcile dividend events")
    parser.add_argument(
        "--sources", nargs="+", choices=sorted(_CLI_SOURCES), default=sorted(_CLI_SOURCES)
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
    writer = DividendEventWriter(db_dsn, settings, sources, args.fetch_run_id, args.symbols)
    asyncio.run(writer.run())


if __name__ == "__main__":
    main()
