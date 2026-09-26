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

Source "ibkr_adjusted_last_ratio": IBKR's ADJUSTED_LAST close is the TRADES close times a
cumulative dividend factor; with r_t = adjusted_t / close_t, an ex-date t steps the ratio by
r_t / r_{t-1} = 1 / (1 - amount / close_{t-1}). ADJUSTED_LAST is quoted to the cent, so with no
dividend r moves by at most 0.005/close_t + 0.005/close_{t-1}. A step counts only if it exceeds
that bound times threshold.dividend_event.noise_margin AND still holds the next day; a one-day
excursion (transient) and a downward step are counted, never stored. The newest row waits for
the next run, so coverage ends one day short.

Every source writes first-derivation-wins (IBKR re-bases its ratio with every new dividend, so
re-derived amounts differ by rounding); a re-derived yield outside the source's tolerance is
logged, not overwritten. Readers use amount / prev_close (the yield on the ex-date): a later
split re-scales both, so only the ratio is stable.

Reconciliation (inside each symbol's write transaction, over everything stored for it): the
same dividend reported on different dates by the two sources would be counted twice by the
reconciled view, so a near-miss rolls the symbol back and fails the run. Yield disagreements beyond
threshold.dividend_event.source_yield_rel_tolerance and each source's holes are logged and
counted.

Usage:
    python services/dividend_event_writer.py                          # both sources
    python services/dividend_event_writer.py --sources yahoo          # nightly-cheap
    python services/dividend_event_writer.py --sources ibkr --years 25 --symbols SPY
"""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import math
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta

import asyncpg

from services._batch_utils import cfg as _cfg
from services._batch_utils import load_apr_dict_async
from src.config.settings import Settings, get_active_contracts
from src.core.agent.base_batch import BaseBatch
from src.core.models import AssetClass
from src.observability.otel import OTelInitError, init_otel_providers
from src.providers import yahoo
from src.providers.ibkr import HIST_RATE_LIMIT_KEYS, IBKRProvider, apply_hist_rate_limit_config

_JOB = "dividend-event-writer"
SOURCE_IBKR = "ibkr_adjusted_last_ratio"
SOURCE_YAHOO = "yahoo"
_CLI_SOURCES = {"ibkr": SOURCE_IBKR, "yahoo": SOURCE_YAHOO}
# ADJUSTED_LAST is quoted to the cent: half a cent of rounding per close.
_HALF_TICK = 0.005
# The rounding bound is attained exactly when an unrounded adjusted close ends in half a cent;
# this relative slack keeps floating-point error at that tie from reading as a step.
_FLOAT_SLACK = 1e-9


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
    n_transient_steps: int = 0


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
    pairs: Sequence[tuple[date, float, float]], noise_margin: float
) -> Derivation:
    """Dividend events from (day, TRADES close, ADJUSTED_LAST close) rows sorted by day.

    Pure. Raises ValueError on fewer than 3 rows or a non-positive price (skipping the row
    would attribute a dividend inside the gap to the wrong day).
    """
    if len(pairs) < 3:
        raise ValueError("too few daily rows")
    if not all(_positive(c) and _positive(a) for _, c, a in pairs):
        raise ValueError("non-finite or non-positive close in adjustment pairs")
    days = [d for d, _, _ in pairs]
    closes = [c for _, c, _ in pairs]
    ratios = [a / c for _, c, a in pairs]
    events: list[DividendEvent] = []
    n_down = n_transient = 0
    # Row 0 has no prior day and the last row has no next day to confirm a step.
    for i in range(1, len(pairs) - 1):
        step = ratios[i] - ratios[i - 1]
        if abs(step) <= _bound(closes[i], closes[i - 1], noise_margin):
            continue
        if step < 0:
            n_down += 1
            continue
        if ratios[i + 1] - ratios[i - 1] <= _bound(closes[i + 1], closes[i - 1], noise_margin):
            n_transient += 1
            continue
        amount = closes[i - 1] * (1.0 - ratios[i - 1] / ratios[i])
        # Each derivation's amount carries up to 0.01 / ratio of rounding, and a later fetch
        # sees this ex-date at an equal or smaller ratio, so twice the bound covers both.
        tolerance = noise_margin * 2 * (2 * _HALF_TICK) / (ratios[i - 1] * closes[i - 1])
        events.append(DividendEvent(days[i], amount, closes[i - 1], tolerance))
    return Derivation(events, days[1], days[-2], n_down, n_transient)


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
    yield_rel_tolerance: float,
) -> Reconciliation:
    """Compare two sources' stored events (ex_date -> yield) for one symbol. Pure."""

    def inside(d: date, span: tuple[date, date] | None) -> bool:
        return span is not None and span[0] <= d <= span[1]

    ibkr_only = sorted(ibkr.keys() - yahoo_events.keys())
    yahoo_only = sorted(yahoo_events.keys() - ibkr.keys())
    near = [(i, y) for i in ibkr_only for y in yahoo_only if abs((i - y).days) <= match_days]
    near_dates = {i for i, _ in near} | {y for _, y in near}
    disagreements = sorted(
        d
        for d in ibkr.keys() & yahoo_events.keys()
        if abs(ibkr[d] - yahoo_events[d]) > yield_rel_tolerance * yahoo_events[d]
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
    compute_version = "1.0.0"

    def __init__(
        self,
        db_dsn: str,
        settings: Settings,
        sources: list[str],
        client_id: int,
        years: int | None,
        symbols: list[str],
    ) -> None:
        super().__init__(db_dsn)
        self._settings = settings
        self._sources = sources
        self._client_id = client_id
        self._years = years
        self._symbols = symbols

    async def execute(self, pool: asyncpg.Pool) -> None:
        async with pool.acquire() as conn:
            apr = await load_apr_dict_async(
                conn,
                ["threshold.dividend_event.%", "infra.dividend_event.%", "infra.ibkr.rate_limit%"],
            )
        apply_hist_rate_limit_config({k: apr[k] for k in HIST_RATE_LIMIT_KEYS if k in apr})
        margin = float(_cfg(apr, "threshold.dividend_event.noise_margin", 1.25))
        match_days = int(_cfg(apr, "threshold.dividend_event.ex_date_match_days", 5))
        rel_tol = float(_cfg(apr, "threshold.dividend_event.source_yield_rel_tolerance", 0.10))
        years = self._years or int(_cfg(apr, "infra.dividend_event.lookback_years", 1))

        instruments = [
            i
            for i in get_active_contracts(self._settings, dimension="backfill")
            if i.asset_class == AssetClass.EQUITY
            and (not self._symbols or i.symbol in self._symbols)
        ]
        provider = None
        if SOURCE_IBKR in self._sources:
            provider = IBKRProvider(
                host=self._settings.ib_host,
                port=self._settings.ib_port,
                client_id=self._client_id,
            )
            if not await provider.connect():
                raise RuntimeError("dividend_event_writer: cannot connect to IBKR")

        failed: list[str] = []
        totals = dict.fromkeys(
            (
                "events",
                "downward",
                "transient",
                "rederived_moved",
                "yield_disagreements",
                "ibkr_holes",
                "yahoo_holes",
            ),
            0,
        )
        try:
            for instrument in instruments:
                symbol = instrument.symbol
                derivations: dict[str, Derivation] = {}
                for source in self._sources:
                    try:
                        derivations[source] = await self._derive(
                            provider, instrument, source, years, margin
                        )
                    except _SymbolFailure as error:
                        failed.append(f"{symbol}/{source}: {error}")
                if not derivations:
                    continue
                # One transaction per symbol, reconciliation included: a near-miss (one
                # dividend on two dates) rolls the symbol back before the view can see it.
                try:
                    async with pool.acquire() as conn, conn.transaction():
                        moved = 0
                        for source, derivation in derivations.items():
                            moved += await self._write(conn, symbol, source, derivation)
                        rec = await self._reconcile(conn, symbol, match_days, rel_tol)
                        if rec.near_misses:
                            raise _SymbolFailure(
                                "one dividend on two dates (ibkr, yahoo): "
                                + ", ".join(f"{i} / {y}" for i, y in rec.near_misses)
                            )
                except _SymbolFailure as error:
                    failed.append(f"{symbol}: {error}")
                    continue
                for derivation in derivations.values():
                    totals["events"] += len(derivation.events)
                    totals["downward"] += derivation.n_downward_steps
                    totals["transient"] += derivation.n_transient_steps
                    if derivation.n_downward_steps or derivation.n_transient_steps:
                        self.logger.warning(
                            "dividend_event_writer.rejected_steps",
                            symbol=symbol,
                            downward=derivation.n_downward_steps,
                            transient=derivation.n_transient_steps,
                        )
                totals["rederived_moved"] += moved
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
        finally:
            if provider is not None:
                await provider.disconnect()

        self.logger.info(
            "dividend_event_writer.done",
            symbols=len(instruments),
            sources=self._sources,
            failed=len(failed),
            years=years,
            **totals,
        )
        if failed:
            raise RuntimeError(f"dividend_event_writer: {len(failed)} failures: {failed}")

    @staticmethod
    async def _derive(
        provider: IBKRProvider | None, instrument, source: str, years: int, margin: float
    ) -> Derivation:
        """Fetch one source for one symbol and derive its events; raises _SymbolFailure."""
        symbol = instrument.symbol
        if source == SOURCE_YAHOO:
            rows, error = await yahoo.fetch_daily_close_and_dividends(symbol)
            if error is not None:
                raise _SymbolFailure(error)
            try:
                return derive_yahoo_events(rows)
            except ValueError as invalid:
                raise _SymbolFailure(str(invalid)) from invalid
        assert provider is not None
        if not await provider.qualify_instrument(instrument):
            raise _SymbolFailure("qualify failed")
        # Both series in the same run: IBKR re-bases ADJUSTED_LAST on every new dividend.
        now = datetime.now(UTC)
        trades = await provider.fetch_historical_bars(
            symbol, "1d", start=now - timedelta(days=365 * years), end=now
        )
        if provider.last_fetch_failed_chunks:
            raise _SymbolFailure(f"TRADES: {provider.last_fetch_failed_chunks} chunks failed")
        adjusted, error = await provider.fetch_adjusted_daily_closes(symbol, years)
        if error is not None:
            raise _SymbolFailure(error)
        closes = {bar.timestamp.date(): bar.close for bar in trades}
        try:
            return derive_ibkr_events(join_adjustment_pairs(closes, adjusted), margin)
        except ValueError as invalid:
            raise _SymbolFailure(str(invalid)) from invalid

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
        conn: asyncpg.Connection, symbol: str, match_days: int, rel_tol: float
    ) -> Reconciliation:
        events: dict[str, dict[date, float]] = {SOURCE_IBKR: {}, SOURCE_YAHOO: {}}
        for r in await conn.fetch(
            "SELECT source, ex_date, amount / prev_close AS y FROM dividend_events "
            "WHERE symbol = $1",
            symbol,
        ):
            events[r["source"]][r["ex_date"]] = r["y"]
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
            rel_tol,
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Derive and reconcile dividend events")
    parser.add_argument(
        "--sources", nargs="+", choices=sorted(_CLI_SOURCES), default=sorted(_CLI_SOURCES)
    )
    parser.add_argument("--years", type=int, default=None, help="IBKR history (default APR)")
    parser.add_argument("--symbols", nargs="*", default=[], help="limit to these symbols")
    parser.add_argument("--client-id", type=int, default=45)
    args = parser.parse_args()
    try:
        init_otel_providers(f"indicagent-{_JOB}")
    except OTelInitError:
        pass
    settings = Settings()
    db_dsn = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
    sources = [_CLI_SOURCES[s] for s in args.sources]
    writer = DividendEventWriter(
        db_dsn, settings, sources, args.client_id, args.years, args.symbols
    )
    asyncio.run(writer.run())


if __name__ == "__main__":
    main()
