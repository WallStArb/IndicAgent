"""D7 nightly reconciliation audit (phase 185 plan 23, D-26, todo 462).

One oneshot, on its own daily timer (indicagent-bar-reconciliation-audit.timer, 06:00 UTC,
since the 189-06 cutover; it was chained from the nightly backfill before), that audits each
independent view of a bar against the others and surfaces drift, including the failure
modes phase 185 itself introduces (skipped nightlies, stray writers, switches out of sync
with the venue study):

- route_disagreement: a venue-routed D1 close vs the SMART close for the same day.
- adjusted_vs_trades: a step in the ADJUSTED_LAST / TRADES ratio on a day with no recorded
  dividend or corporate action.
- daily_vs_intraday: the IBKR daily bar vs the regular-session 5m bars (open exact, close
  within the bp tolerance, volume within the measured tolerance).
- unexplained_seams: a close-to-close jump beyond the robust-scale threshold with no
  corporate action and no quarantine flag.
- late_heads: a moved name whose canonical history starts after its first known trade.
- listing_venue_coverage: a moved 1d-eligible name with no listing_venue rows or no closed
  former-venue span (D6, plan 185-24).
- unconfirmed_empty: an ohlcv_empty_history row no set of every-route answers confirms.
- dividend_freshness: Yahoo dividend coverage trailing the last session.
- nightly_skipped: the last IBKR history fetcher run (its status file) did not finish with
  success recently.
- stray_sources: 1d/15m/1h rows with a source the derivation does not write.
- switches: venue switches differing from the venue study verdict.
- completeness and masked_slots (todo 462): per (symbol, timeframe, year) the share of
  expected session slots that hold a real bar or lie inside an answered request window,
  and the 15m/1h slots that hide real 5m volume behind a placeholder or a hole.
- vendor_agreement: Tradier vs IBKR SMART TRADES closes and volumes in D1, per year
  (Tradier is the primary 1d source since migration 438).
- tradier_refused: a Tradier-owned name whose latest daily load was refused (gated,
  short_history, no_data or failed; plan 185-26). Its stored bars stay as they were.

Observability only, the classification-coverage contract: a finding is reported loudly
(an integrity_monitor fact, an OTel metric labeled by check, and by timeframe or year
where the plan says so, never by symbol; the per-symbol detail goes to the log at error
level), never through the exit code. Only a runtime error fails the run (BaseBatch D-06).

The checks are pure functions (no connection, no clock) so each is tested on fixtures;
the class below only loads their inputs and reports their results.
"""

from __future__ import annotations

import asyncio
import json
import math
import statistics
from array import array
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any, NamedTuple

import asyncpg
import structlog

from services._batch_utils import cfg as _cfg
from services._batch_utils import load_apr_dict_async
from src.config.settings import Settings, dimension_where_clause
from src.core.agent.base_batch import BaseBatch
from src.core.bar_accumulator import _TF_MINUTES
from src.core.bar_normalizer import SOURCE_SYNTHETIC_FILL
from src.core.integrity_monitor import emit_integrity_fact_async
from src.core.models import AssetClass
from src.intelligence.bars.derivation import SOURCE_NAMED, SOURCE_VENUE
from src.intelligence.bars.gap_plan import (
    ANSWERED_OUTCOMES,
    COVERAGE_ROUTE,
    COVERAGE_WHAT_TO_SHOW,
    AnsweredWindows,
    confirmed_empty_spans,
)
from src.intelligence.bars.sessions import nyse_sessions
from src.intelligence.bars.sources import GRID_SOURCE_TF, GRID_TIMEFRAMES, SOURCE_DERIVED_5M
from src.observability.metrics import counter, point_gauge
from src.observability.otel import OTelInitError, init_otel_providers
from src.providers.base import VENUE_ROUTE_ALIASES
from src.providers.tradier import SOURCE as SOURCE_TRADIER

logger = structlog.get_logger(__name__)

_JOB = "bar-reconciliation-audit"

# Labeled {check} only: never by symbol (cardinality, T-185-23-04); the per-symbol detail
# stays in the log and integrity_monitor.
FINDINGS_TOTAL = counter(
    "bar_reconciliation_findings_total",
    "D7 reconciliation audit findings per run, labeled by check only (never by symbol).",
)

# Sources the derivation (and the Tradier loader, migration 438) may leave in each
# derivation-owned timeframe. Identifiers, not tunables (schema values).
ALLOWED_SOURCES: dict[str, frozenset[str]] = {
    "1d": frozenset({SOURCE_NAMED, SOURCE_VENUE, SOURCE_TRADIER, SOURCE_SYNTHETIC_FILL}),
    **{tf: frozenset({SOURCE_DERIVED_5M, SOURCE_SYNTHETIC_FILL}) for tf in GRID_TIMEFRAMES},
}

# The venue study verdict's timeframe for each switch (scripts/ops/bars/ops_venue_study.py).
_SWITCH_VERDICT_TF = {"venue_bars_1d": "1d", "venue_bars_intraday": "5m"}

# MAD to standard deviation under normality (a mathematical constant).
_MAD_TO_SIGMA = 1.4826
_BP = 1e4


class CheckResult(NamedTuple):
    """A check's finding count and the subjects behind it (for the log and facts)."""

    n_findings: int
    samples: tuple[str, ...]


def _bp(a: float, b: float) -> float:
    return abs(a / b - 1.0) * _BP


# ---------------------------------------------------------------------------
# Pure checks
# ---------------------------------------------------------------------------


def check_route_disagreement(
    rows: Iterable[tuple[str, date, str, float]],
    rel: float,
    *,
    listing: Mapping[str, str] | None = None,
) -> CheckResult:
    """Venue-routed closes that differ from the same day's SMART close by more than `rel`.

    rows: (symbol, bar_date, route, close). A venue row with no SMART row for its
    (symbol, date) has nothing to disagree with and is not judged. With `listing`
    (symbol -> SMART's primary exchange) only the listing venue is judged: the D3 study
    found only the listing venue's close matches SMART's (criterion b), so a non-listing
    venue disagreeing is the expected state, not drift. Venue codes are compared through
    VENUE_ROUTE_ALIASES (route ISLAND is primary exchange NASDAQ).
    """
    rows = list(rows)
    smart = {(s, d): c for s, d, route, c in rows if route == COVERAGE_ROUTE}

    def judged(symbol: str, day: date, route: str) -> bool:
        if route == COVERAGE_ROUTE or (symbol, day) not in smart:
            return False
        return listing is None or VENUE_ROUTE_ALIASES.get(route, route) == listing.get(symbol)

    samples = sorted(
        f"{s}|{d.isoformat()}|{route}"
        for s, d, route, c in rows
        if judged(s, d, route) and abs(c / smart[(s, d)] - 1.0) > rel
    )
    return CheckResult(len(samples), tuple(samples))


def check_adjusted_vs_trades(
    pairs: Mapping[str, Sequence[tuple[date, float, float]]],
    explained_dates: set[tuple[str, date]],
    rel: float,
) -> CheckResult:
    """Steps in the ADJUSTED_LAST / TRADES ratio no dividend or corporate action explains.

    pairs: symbol -> date-sorted (date, trades_close, adjusted_close). IBKR scales every
    adjusted close before an ex-date, so a dividend's step lands on the ex-date itself; a
    recorded split's effective_date is the last day on the old scale (corporate_actions.
    SplitInference), the day before its step. A date on either side of the step explains it.
    """
    samples: list[str] = []
    for symbol in sorted(pairs):
        prev: tuple[date, float] | None = None
        for day, trades, adjusted in pairs[symbol]:
            if trades <= 0 or adjusted <= 0:
                prev = None
                continue
            ratio = adjusted / trades
            if (
                prev is not None
                and abs(ratio / prev[1] - 1.0) > rel
                and (symbol, day) not in explained_dates
                and (symbol, prev[0]) not in explained_dates
            ):
                samples.append(f"{symbol}|{day.isoformat()}")
            prev = (day, ratio)
    return CheckResult(len(samples), tuple(samples))


def check_daily_vs_intraday(
    daily: Mapping[tuple[str, date], tuple[float, float, int | None]],
    agg: Mapping[tuple[str, date], tuple[float, float, int | None]],
    close_tol_bp: float,
    volume_tol_rel: float,
) -> CheckResult:
    """Daily bars vs the regular-session 5m aggregate: (open, close, volume) per (symbol, day).

    Open must match exactly (the first 5m open is the daily open), close within
    `close_tol_bp`, volume within `volume_tol_rel` of the daily volume (a NULL volume, as
    on venue bars, is not judged). Days present on one side only are not judged here;
    completeness owns holes.
    """
    samples: list[str] = []
    for key in sorted(daily.keys() & agg.keys()):
        d_open, d_close, d_vol = daily[key]
        a_open, a_close, a_vol = agg[key]
        fields: list[str] = []
        if not math.isclose(d_open, a_open, rel_tol=1e-9):
            fields.append("open")
        if _bp(d_close, a_close) > close_tol_bp:
            fields.append("close")
        if d_vol is not None and a_vol is not None:
            if abs(d_vol - a_vol) > volume_tol_rel * abs(d_vol):
                fields.append("volume")
        if fields:
            symbol, day = key
            samples.append(f"{symbol}|{day.isoformat()}|{'+'.join(fields)}")
    return CheckResult(len(samples), tuple(samples))


def check_unexplained_seams(
    closes: Mapping[str, Sequence[tuple[date, float]]],
    actions: set[tuple[str, date]],
    flags: set[tuple[str, date]],
    sigma: float,
    *,
    judge_from: date,
) -> CheckResult:
    """Close-to-close jumps beyond `sigma` robust scales with no explanation.

    The scale is the MAD of the symbol's log returns over the whole series read (robust to
    the jump itself). Only returns ending on or after `judge_from` are judged. A corporate
    action on either day of the pair explains it (a split's effective_date is the last day
    on the old scale, the pair's first day), and so does a quarantine flag anywhere from the
    pair's first day to its last: the tradeable view drops quarantined bars, so a pair can
    span one.
    """
    flag_days: dict[str, list[date]] = defaultdict(list)
    for flag_symbol, flag_day in flags:
        flag_days[flag_symbol].append(flag_day)
    samples: list[str] = []
    for symbol in sorted(closes):
        series = [(d, c) for d, c in closes[symbol] if c > 0]
        if len(series) < 3:
            continue
        returns = [
            (series[i][0], series[i - 1][0], math.log(series[i][1] / series[i - 1][1]))
            for i in range(1, len(series))
        ]
        values = [r for _, _, r in returns]
        center = statistics.median(values)
        scale = _MAD_TO_SIGMA * statistics.median(abs(v - center) for v in values)
        if scale <= 0:
            continue
        for day, prev_day, r in returns:
            if day < judge_from or abs(r) <= sigma * scale:
                continue
            if (symbol, day) in actions or (symbol, prev_day) in actions:
                continue
            if any(prev_day <= f <= day for f in flag_days.get(symbol, ())):
                continue
            samples.append(f"{symbol}|{day.isoformat()}")
    return CheckResult(len(samples), tuple(samples))


def check_late_heads(inventory: Mapping[str, date], lineage: Mapping[str, date]) -> CheckResult:
    """Names whose canonical 1d head is later than their first known trade.

    inventory: symbol -> first known trade (the earliest venue-routed D1 observation);
    lineage: symbol -> earliest canonical 1d bar. A moved name without recovery fails.
    """
    samples: list[str] = []
    for symbol in sorted(inventory):
        first = inventory[symbol]
        head = lineage.get(symbol)
        if head is None or head > first:
            shown = head.isoformat() if head is not None else "none"
            samples.append(f"{symbol}|first_trade={first.isoformat()}|head={shown}")
    return CheckResult(len(samples), tuple(samples))


def check_listing_venue_coverage(
    inventory: Iterable[str], stored: Mapping[str, tuple[int, int]]
) -> CheckResult:
    """Moved names (the inventory: former-venue spans before the SMART head) that D6's
    listing_venue does not explain: no rows at all, or no closed former-venue span.

    stored: symbol -> (n_rows, n_closed_spans) in listing_venue (plan 185-24, D-25).
    """
    samples: list[str] = []
    for symbol in sorted(set(inventory)):
        n_rows, n_closed = stored.get(symbol, (0, 0))
        if n_rows == 0:
            samples.append(f"{symbol}|no_rows")
        elif n_closed == 0:
            samples.append(f"{symbol}|no_closed_span")
    return CheckResult(len(samples), tuple(samples))


def check_unconfirmed_empty(
    empty_rows: Iterable[tuple[str, datetime, datetime]],
    confirmed: Mapping[str, Sequence[tuple[datetime, datetime]]],
    *,
    slack: timedelta,
) -> CheckResult:
    """ohlcv_empty_history rows no confirmed every-route span covers (D-20).

    empty_rows: (symbol, verified_from, empty_through); confirmed: symbol -> spans every
    required route answered no_data for. Covered within `slack`, the same rule
    reconcile_empty_history keeps a row by.
    """
    samples: list[str] = []
    for symbol, verified_from, empty_through in sorted(empty_rows):
        covered = any(
            start - slack <= verified_from and end + slack >= empty_through
            for start, end in confirmed.get(symbol, ())
        )
        if not covered:
            samples.append(f"{symbol}|{verified_from.date().isoformat()}")
    return CheckResult(len(samples), tuple(samples))


def check_dividend_freshness(
    coverage_end: Mapping[str, date | None],
    last_session: date,
    max_sessions: int,
    *,
    session_dates: Sequence[date],
) -> CheckResult:
    """Symbols whose Yahoo dividend coverage ends more than `max_sessions` sessions before
    `last_session`, or that have no coverage at all (their dividends are unknown)."""
    samples: list[str] = []
    for symbol in sorted(coverage_end):
        end = coverage_end[symbol]
        if end is None:
            samples.append(f"{symbol}|no_coverage")
            continue
        behind = sum(1 for d in session_dates if end < d <= last_session)
        if behind > max_sessions:
            samples.append(f"{symbol}|covered_to={end.isoformat()}")
    return CheckResult(len(samples), tuple(samples))


def check_stray_sources(source_counts: Mapping[tuple[str, str | None], int]) -> CheckResult:
    """Rows in a derivation-owned timeframe with a source nothing sanctioned writes.

    source_counts: (timeframe, source) -> row count. Timeframes the derivation does not own
    are not judged. The finding count is the stray row count.
    """
    n = 0
    samples: list[str] = []
    for (tf, source), count in sorted(
        source_counts.items(), key=lambda kv: (kv[0][0], str(kv[0][1]))
    ):
        allowed = ALLOWED_SOURCES.get(tf)
        if allowed is None or source in allowed or count <= 0:
            continue
        n += count
        samples.append(f"{tf}:{source if source is not None else 'NULL'}={count}")
    return CheckResult(n, tuple(samples))


def check_switches(apr: Mapping[str, bool], verdict: Mapping[str, bool]) -> CheckResult:
    """Venue switches that differ from the venue study verdict (D-17). The intraday
    recovery unlock is reported when true but is informational, not a finding."""
    samples: list[str] = []
    n = 0
    for key, tf in _SWITCH_VERDICT_TF.items():
        value = bool(apr.get(key, False))
        passed = bool(verdict.get(tf, False))
        if value != passed:
            n += 1
            samples.append(f"{key}={str(value).lower()}|verdict_passed={str(passed).lower()}")
    if apr.get("intraday_recovery_unlocked"):
        samples.append("intraday_recovery_unlocked=true (informational)")
    return CheckResult(n, tuple(samples))


def check_nightly_skipped(
    last_nightly_status: Mapping[str, Any] | None, *, now: datetime, max_age_hours: int
) -> CheckResult:
    """The nightly's last status file: anything but a recent success is a finding.

    A missing file, a run that never finished (status 'started'), a failure (a leg's
    failed_lease_timeout included, D-29) or a success older than `max_age_hours` (a
    skipped night) each count once.
    """
    if not last_nightly_status:
        return CheckResult(1, ("no_status",))
    status = str(last_nightly_status.get("status"))
    if status != "success":
        sample = f"status={status}"
        legs = last_nightly_status.get("lease_timeout_legs") or []
        if legs:
            sample += f"|legs={','.join(legs)}"
        return CheckResult(1, (sample,))
    finished_raw = last_nightly_status.get("finished_at")
    finished = datetime.fromisoformat(finished_raw) if finished_raw else None
    if finished is None or now - finished > timedelta(hours=max_age_hours):
        return CheckResult(1, (f"stale|finished_at={finished_raw}",))
    return CheckResult(0, ())


def check_tradier_refused(latest: Mapping[str, tuple[str, str | None]]) -> CheckResult:
    """Tradier-owned names whose latest daily load was not accepted (plan 185-26).

    latest: symbol -> (outcome, detail) of its most recent ohlcv_load row, for names some
    load was accepted for. A refusal keeps the stored bars; it is reported here, never
    applied and never a nightly failure.
    """
    samples = [
        f"{symbol}|{outcome}|{detail or ''}"
        for symbol, (outcome, detail) in sorted(latest.items())
        if outcome != "loaded"
    ]
    return CheckResult(len(samples), tuple(samples))


# ---------------------------------------------------------------------------
# Completeness and masked slots (todo 462)
# ---------------------------------------------------------------------------


def session_slots(
    sessions: Mapping[date, tuple[datetime, datetime]],
    minutes: int,
    start: datetime,
    end: datetime,
) -> list[datetime]:
    """Session-anchored slot starts in [start, end): open, open + minutes, ... before close.

    The derived 15m/1h grid's edges (D-15) and the 5m grid alike; half days and DST come
    from the session bounds."""
    interval = timedelta(minutes=minutes)
    slots: list[datetime] = []
    for _day, (open_dt, close_dt) in sorted(sessions.items()):
        slot = open_dt
        while slot < close_dt:
            if start <= slot < end:
                slots.append(slot)
            slot += interval
    return slots


def bucket_fine_volume(
    fine: Iterable[tuple[datetime, int]],
    sessions: Mapping[date, tuple[datetime, datetime]],
    minutes: int,
) -> dict[datetime, int]:
    """Sum fine-bar volume into the session-anchored coarse slot each bar falls in.
    Bars outside a regular session are dropped (they belong to no derived slot)."""
    interval = timedelta(minutes=minutes)
    out: dict[datetime, int] = defaultdict(int)
    for ts, volume in fine:
        bounds = sessions.get(ts.date())
        if bounds is None or not bounds[0] <= ts < bounds[1]:
            continue
        slot = bounds[0] + ((ts - bounds[0]) // interval) * interval
        out[slot] += int(volume)
    return dict(out)


@dataclass(frozen=True)
class CompletenessCell:
    symbol: str
    timeframe: str
    year: int
    n_expected: int
    n_complete: int

    @property
    def share(self) -> float:
        return self.n_complete / self.n_expected if self.n_expected else 1.0


def completeness_cells(
    symbol: str,
    timeframe: str,
    expected_slots: Iterable[datetime],
    stored: Iterable[datetime],
    answered_windows: AnsweredWindows,
    interval: timedelta,
    sessions: Mapping[date, tuple[datetime, datetime]] | None = None,
) -> list[CompletenessCell]:
    """Per-year completeness for one (symbol, timeframe): a slot is complete when a stored
    real bar sits on it or the whole slot lies inside an answered request window. With
    `sessions`, a slot ends at the session close when that comes first (the last 1h slot
    of a 16:00 close is 15:30-16:00, and an answered window ends at the close)."""
    stored_set = set(stored)
    expected: dict[int, int] = defaultdict(int)
    complete: dict[int, int] = defaultdict(int)
    for slot in expected_slots:
        expected[slot.year] += 1
        length = interval
        if sessions is not None and slot.date() in sessions:
            length = min(interval, sessions[slot.date()][1] - slot)
        if slot in stored_set or answered_windows.covers(slot, length):
            complete[slot.year] += 1
    return [
        CompletenessCell(symbol, timeframe, year, expected[year], complete[year])
        for year in sorted(expected)
    ]


def check_completeness(
    cells: Iterable[CompletenessCell], min_share: float
) -> tuple[CheckResult, dict[str, float]]:
    """Cells below `min_share` (reported by symbol, timeframe and year) and the pooled share
    per timeframe (the only shape the metric carries)."""
    cells = list(cells)
    samples = tuple(
        f"{c.symbol}|{c.timeframe}|{c.year}|share={c.share:.4f}"
        for c in sorted(cells, key=lambda c: (c.symbol, c.timeframe, c.year))
        if c.n_expected and c.share < min_share
    )
    totals: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for c in cells:
        totals[c.timeframe][0] += c.n_complete
        totals[c.timeframe][1] += c.n_expected
    pooled = {tf: done / total for tf, (done, total) in totals.items() if total}
    return CheckResult(len(samples), samples), pooled


def check_masked_slots(
    coarse_rows: Mapping[datetime, str], fine_volume_by_slot: Mapping[datetime, int]
) -> CheckResult:
    """Coarse slots that hide real fine volume: a placeholder or a missing row where the 5m
    bars over the slot carry volume above zero.

    coarse_rows: slot -> 'real' | 'placeholder' | 'partial'. A partial_constituents bar
    carries the real volume of the constituents it has, so it hides nothing; the IO layer
    counts those separately.
    """
    samples = tuple(
        slot.isoformat()
        for slot in sorted(fine_volume_by_slot)
        if fine_volume_by_slot[slot] > 0 and coarse_rows.get(slot) not in ("real", "partial")
    )
    return CheckResult(len(samples), samples)


# ---------------------------------------------------------------------------
# Vendor agreement (Tradier vs IBKR SMART TRADES)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class VendorYear:
    n_both: int
    n_differ: int
    median_volume_ratio: float | None

    @property
    def share_differ(self) -> float:
        return self.n_differ / self.n_both if self.n_both else 0.0


class VendorAgreementAccumulator:
    """Per-year agreement between IBKR SMART TRADES and Tradier daily observations.

    Fed one symbol's overlapping days at a time so the whole D1 overlap never sits in
    memory as Python tuples; only the per-year volume ratios (needed for the exact median)
    are kept, as packed doubles.
    """

    def __init__(self, close_tol_bp: float) -> None:
        self._tol = close_tol_bp
        self._n_both: dict[int, int] = defaultdict(int)
        self._n_differ: dict[int, int] = defaultdict(int)
        self._ratios: dict[int, array] = defaultdict(lambda: array("d"))

    def add(self, rows: Iterable[tuple[int, float, float, int | None, int | None]]) -> None:
        """rows: (year, ibkr_close, tradier_close, ibkr_volume, tradier_volume)."""
        for year, ibkr_close, tradier_close, ibkr_volume, tradier_volume in rows:
            if tradier_close <= 0:
                continue
            self._n_both[year] += 1
            if _bp(ibkr_close, tradier_close) > self._tol:
                self._n_differ[year] += 1
            if ibkr_volume is not None and tradier_volume:
                self._ratios[year].append(ibkr_volume / tradier_volume)

    def result(self) -> dict[int, VendorYear]:
        return {
            year: VendorYear(
                n,
                self._n_differ[year],
                statistics.median(self._ratios[year]) if self._ratios[year] else None,
            )
            for year, n in sorted(self._n_both.items())
        }


# ---------------------------------------------------------------------------
# Pure input shaping used by the IO layer
# ---------------------------------------------------------------------------


def aggregate_sessions(
    fine: Iterable[tuple[str, datetime, float, float, int]],
    sessions: Mapping[date, tuple[datetime, datetime]],
    interval: timedelta,
) -> dict[tuple[str, date], tuple[float, float, int]]:
    """Regular-session aggregate per (symbol, day) of (symbol, ts)-ordered fine bars: first
    open, last close, summed volume. Bars outside the session are dropped, and so is a
    session whose bars stop before its final slot (a feed that ended mid-session is a
    completeness gap, not a disagreement about the close)."""
    out: dict[tuple[str, date], tuple[float, float, int]] = {}
    last: dict[tuple[str, date], datetime] = {}
    for symbol, ts, open_, close, volume in fine:
        bounds = sessions.get(ts.date())
        if bounds is None or not bounds[0] <= ts < bounds[1]:
            continue
        key = (symbol, ts.date())
        prev = out.get(key)
        out[key] = (
            (open_, close, int(volume)) if prev is None else (prev[0], close, prev[2] + int(volume))
        )
        last[key] = ts
    return {key: bar for key, bar in out.items() if last[key] >= sessions[key[1]][1] - interval}


def check_partial_daily(
    latest: Iterable[tuple[str, date, datetime]],
    sessions: Mapping[date, tuple[datetime, datetime]],
) -> CheckResult:
    """Latest daily observations fetched before their own session closed.

    latest: (symbol, bar_date, fetched_at) of each (symbol, day)'s most recent D1 answer.
    A fetch made mid-session returns the session so far as that day's bar; if nothing
    re-fetched the day afterwards, D1's latest view of it is a partial bar.
    """
    samples = sorted(
        f"{symbol}|{day.isoformat()}|fetched_at={fetched_at.isoformat()}"
        for symbol, day, fetched_at in latest
        if day in sessions and fetched_at < sessions[day][1]
    )
    return CheckResult(len(samples), tuple(samples))


def confirmed_spans_from_requests(
    rows: Iterable[tuple[Any, str, str | None, datetime, datetime]],
    venues: Sequence[str],
    *,
    slack: timedelta,
) -> list[tuple[datetime, datetime]]:
    """Spans SMART and every former venue other than the run's primary answered no_data for,
    within one fetch run, merged across runs (D-20).

    rows: (fetch_run_id, route, primary_exchange, window_start, window_end) of the
    symbol's TRADES requests that answered no_data, plus SMART's `bars` answers (SMART
    answers a head with bars from the listing on, so the span before it is implied). Same
    rule as scripts/infrastructure/backfill/_empty_history.py's _confirmed_spans; services/
    does not import from scripts/, so the request grouping lives here and the confirmation
    itself is gap_plan's. The caller drops spans that hold a real bar.
    """
    runs: dict[Any, dict[str, list[tuple[datetime, datetime]]]] = defaultdict(
        lambda: defaultdict(list)
    )
    primaries: dict[Any, str] = {}
    for run, route, primary, window_start, window_end in rows:
        runs[run][route].append((window_start, window_end))
        if route == COVERAGE_ROUTE and primary:
            primaries[run] = primary
    spans: list[tuple[datetime, datetime]] = []
    for run, windows in runs.items():
        primary = primaries.get(run)
        required = [COVERAGE_ROUTE] + [
            v for v in venues if VENUE_ROUTE_ALIASES.get(v, v) != primary
        ]
        spans.extend(
            (s.start, s.end) for s in confirmed_empty_spans(windows, required, slack=slack)
        )
    merged: list[tuple[datetime, datetime]] = []
    for start, end in sorted(spans):
        if merged and start <= merged[-1][1] + slack:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


# ---------------------------------------------------------------------------
# BaseBatch oneshot. A finding never raises; a runtime error propagates.
# ---------------------------------------------------------------------------

_MONITOR_TYPE = "bar_reconciliation"
_REPO_ROOT = Path(__file__).resolve().parents[1]
# Written by the IBKR history fetcher at the end of every run (service identity, APR-exempt).
NIGHTLY_STATUS_FILE = _REPO_ROOT / "logs" / "nightly_backfill_status.json"
_VERDICT_FILE = _REPO_ROOT / "config" / "bars" / "venue_study_verdict.json"
# bar_derivation's flag rule for a derived bar with an unanswered constituent slot.
_PARTIAL_RULE = "partial_constituents"
_GRID_MINUTES: dict[str, int] = {GRID_SOURCE_TF: 5, **GRID_TIMEFRAMES}

COMPLETENESS_SHARE = point_gauge(
    "bar_reconciliation_completeness_share",
    "D7 pooled share of expected session slots holding a real bar or inside an answered "
    "request window, labeled by check and timeframe only (todo 462).",
)
VENDOR_CLOSE_DIFFER_SHARE = point_gauge(
    "bar_reconciliation_vendor_close_differ_share",
    "Share of daily closes where Tradier and IBKR SMART TRADES differ beyond the close "
    "tolerance, labeled by check and year only.",
)
VENDOR_VOLUME_RATIO = point_gauge(
    "bar_reconciliation_vendor_volume_ratio_median",
    "Median IBKR / Tradier daily volume ratio, labeled by check and year only.",
)

_APR_PATTERNS = [
    "threshold.bar_reconciliation.%",
    "infra.bar_derivation.%",
    "infra.ibkr.venue_fallback.%",
]

_SMART_OBS_SQL = """
SELECT DISTINCT ON (symbol, bar_date) symbol, bar_date, open, close, volume, fetched_at
FROM ohlcv_observation
WHERE symbol = ANY($1::text[]) AND bar_date >= $2
  AND source = 'ibkr' AND route = 'SMART' AND what_to_show = $3
ORDER BY symbol, bar_date, fetched_at DESC
"""
_VENUE_OBS_SQL = """
SELECT DISTINCT ON (o.symbol, o.bar_date, o.route) o.symbol, o.bar_date, o.route, o.close
FROM ohlcv_request r
JOIN ohlcv_observation o ON o.request_id = r.request_id
WHERE r.timeframe = '1d' AND r.source = 'ibkr' AND r.what_to_show = 'TRADES'
  AND r.outcome = 'bars' AND r.route = ANY($2::text[]) AND o.bar_date >= $1
ORDER BY o.symbol, o.bar_date, o.route, o.fetched_at DESC
"""
# The latest ADJUSTED_LAST answer per symbol paired with the TRADES answer of the same fetch
# run: a fetch made mid-session holds a partial last bar in both series, so pairing across
# runs compares a partial bar with a final one (seen live: AMPH 2026-09-30, fetched 18:02 UTC).
_ADJUSTED_PAIRS_SQL = """
WITH latest AS (
    SELECT DISTINCT ON (symbol) symbol, request_id, fetch_run_id
    FROM ohlcv_request
    WHERE timeframe = '1d' AND source = 'ibkr' AND route = 'SMART'
      AND what_to_show = 'ADJUSTED_LAST' AND outcome = 'bars'
    ORDER BY symbol, answered_at DESC
), paired AS (
    SELECT l.symbol, l.request_id AS adjusted_id, t.request_id AS trades_id
    FROM latest l
    JOIN LATERAL (
        SELECT r.request_id FROM ohlcv_request r
        WHERE r.fetch_run_id = l.fetch_run_id AND r.symbol = l.symbol AND r.timeframe = '1d'
          AND r.source = 'ibkr' AND r.route = 'SMART' AND r.what_to_show = 'TRADES'
          AND r.outcome = 'bars'
        ORDER BY r.answered_at DESC LIMIT 1
    ) t ON true
)
SELECT p.symbol, a.bar_date, t.close AS trades_close, a.close AS adjusted_close
FROM paired p
JOIN ohlcv_observation a ON a.request_id = p.adjusted_id AND a.bar_date >= $1
JOIN ohlcv_observation t ON t.request_id = p.trades_id AND t.bar_date = a.bar_date
ORDER BY p.symbol, a.bar_date
"""
_LISTING_SQL = """
SELECT DISTINCT ON (symbol) symbol, primary_exchange FROM ohlcv_request
WHERE symbol = ANY($1::text[]) AND timeframe = '1d' AND source = 'ibkr' AND route = 'SMART'
  AND what_to_show = 'TRADES' AND primary_exchange IS NOT NULL AND caller NOT LIKE 'test-%'
ORDER BY symbol, answered_at DESC
"""
_EXPLAINED_DATES_SQL = """
SELECT symbol, ex_date AS day FROM dividend_events WHERE symbol = ANY($1::text[]) AND ex_date >= $2
UNION
SELECT symbol, effective_date FROM corporate_action
WHERE symbol = ANY($1::text[]) AND effective_date >= $2
"""
_UNIVERSE_SQL = "SELECT i.symbol FROM instruments i WHERE {clause} ORDER BY i.symbol"
_FINE_TRADEABLE_SQL = """
SELECT symbol, timestamp, open, close, volume FROM market_data_ohlcv_tradeable
WHERE timeframe = $1 AND symbol = ANY($2::text[]) AND timestamp >= $3 AND timestamp < $4
ORDER BY symbol, timestamp
"""
_DAILY_CLOSES_SQL = """
SELECT symbol, timestamp, close FROM market_data_ohlcv_tradeable
WHERE timeframe = '1d' AND symbol = ANY($1::text[]) AND timestamp >= $2
ORDER BY symbol, timestamp
"""
_QUARANTINE_1D_SQL = """
SELECT symbol, timestamp FROM bar_quality_flag
WHERE timeframe = '1d' AND quarantine AND timestamp >= $1
"""
_VENUE_FIRST_SQL = """
SELECT r.symbol, min(o.bar_date) AS first_bar
FROM ohlcv_request r JOIN ohlcv_observation o ON o.request_id = r.request_id
WHERE r.timeframe = '1d' AND r.source = 'ibkr' AND r.what_to_show = 'TRADES'
  AND r.outcome = 'bars' AND r.route = ANY($1::text[])
GROUP BY r.symbol
"""
_SMART_HEAD_SQL = """
SELECT min(bar_date) FROM ohlcv_observation
WHERE symbol = $1 AND source = 'ibkr' AND route = 'SMART' AND what_to_show = 'TRADES'
"""
# Raw table (allow-listed): the earliest canonical row of any real source.
_CANONICAL_HEAD_SQL = """
SELECT min(timestamp) FROM market_data_ohlcv
WHERE symbol = $1 AND timeframe = '1d' AND source IS DISTINCT FROM 'synthetic_fill'
"""
# The moved-name inventory restricted to the 1d-eligible names D6 writes, and what
# listing_venue holds for each.
_LISTING_COVERAGE_SQL = """
WITH moved AS (
    SELECT DISTINCT h.symbol FROM ohlcv_venue_head h
    JOIN instruments i ON i.symbol = h.symbol
    WHERE {clause} AND h.route = ANY($1::text[]) AND h.pre_move
      AND h.smart_head_date IS NOT NULL
)
SELECT m.symbol, count(lv.symbol) AS n_rows, count(lv.valid_to) AS n_closed
FROM moved m LEFT JOIN listing_venue lv ON lv.symbol = m.symbol
GROUP BY m.symbol
"""
_EMPTY_HISTORY_SQL = """
SELECT symbol, timeframe, verified_from, empty_through FROM ohlcv_empty_history
WHERE provider = 'ibkr'
"""
_EMPTY_ANSWERS_SQL = """
SELECT fetch_run_id, route, primary_exchange, window_start, window_end
FROM ohlcv_request
WHERE symbol = $1 AND timeframe = $2 AND what_to_show = 'TRADES' AND window_start IS NOT NULL
  AND (outcome = 'no_data' OR (route = 'SMART' AND outcome = 'bars'))
"""
_HAS_REAL_BAR_SQL = """
SELECT EXISTS (
    SELECT 1 FROM market_data_ohlcv_tradeable
    WHERE symbol = $1 AND timeframe = $2 AND timestamp >= $3 AND timestamp <= $4
)
"""
_DIVIDEND_COVERAGE_SQL = """
SELECT i.symbol, c.covered_to
FROM instruments i
LEFT JOIN dividend_event_coverage c ON c.symbol = i.symbol AND c.source = 'yahoo'
WHERE {clause} AND i.contract_details->>'asset_class' = $1
"""
# Raw table (allow-listed): counts every source, including the ones the view hides.
_SOURCE_COUNTS_SQL = """
SELECT timeframe, source, symbol, count(*) AS n FROM market_data_ohlcv
WHERE timeframe = ANY($1::text[]) AND timestamp >= $2
GROUP BY 1, 2, 3
"""
# Raw table (allow-listed): placeholders and zero-volume provider bars are what the
# completeness and masked-slot checks classify.
_GRID_ROWS_SQL = """
SELECT timestamp, volume, source FROM market_data_ohlcv
WHERE symbol = $1 AND timeframe = $2 AND timestamp >= $3 AND timestamp < $4
"""
_HAS_REAL_BEFORE_SQL = """
SELECT EXISTS (
    SELECT 1 FROM market_data_ohlcv
    WHERE symbol = $1 AND timeframe = $2 AND timestamp < $3
      AND source IS DISTINCT FROM 'synthetic_fill'
)
"""
_PARTIAL_FLAGS_SQL = """
SELECT timeframe, timestamp FROM bar_quality_flag
WHERE symbol = $1 AND timeframe = ANY($2::text[]) AND rule = $3
  AND timestamp >= $4 AND timestamp < $5
"""
# Same shape as services/bar_auditor.py's answered-window reader: a `bars` answer covers
# its window only when a stored row corroborates it (a lost insert never looks covered).
_ANSWERED_5M_SQL = """
SELECT r.window_start, r.window_end
FROM ohlcv_request r
WHERE r.symbol = $1 AND r.timeframe = $2 AND r.route = $3 AND r.what_to_show = $4
  AND r.outcome = ANY($5::text[]) AND r.window_start IS NOT NULL
  AND (
    r.outcome = 'no_data'
    OR EXISTS (
      SELECT 1 FROM market_data_ohlcv m
      WHERE m.symbol = r.symbol AND m.timeframe = r.timeframe
        AND m.timestamp >= r.window_start AND m.timestamp < r.window_end
    )
  )
"""
_VENDOR_SYMBOLS_SQL = """
SELECT DISTINCT symbol FROM ohlcv_request
WHERE timeframe = '1d' AND source = $1 AND outcome = 'bars'
ORDER BY symbol
"""
_VENDOR_PAIRS_SQL = """
WITH i AS (
    SELECT DISTINCT ON (bar_date) bar_date, close, volume FROM ohlcv_observation
    WHERE symbol = $1 AND source = 'ibkr' AND route = 'SMART' AND what_to_show = 'TRADES'
    ORDER BY bar_date, fetched_at DESC
), t AS (
    SELECT DISTINCT ON (bar_date) bar_date, close, volume FROM ohlcv_observation
    WHERE symbol = $1 AND source = $2
    ORDER BY bar_date, fetched_at DESC
)
SELECT extract(year FROM i.bar_date)::int AS year, i.close, t.close, i.volume, t.volume
FROM i JOIN t USING (bar_date)
"""
# The latest load of every Tradier-owned name (the ever-loaded predicate D2 uses).
_TRADIER_LATEST_LOAD_SQL = """
SELECT DISTINCT ON (l.symbol) l.symbol, l.outcome, l.detail
FROM ohlcv_load l
WHERE EXISTS (SELECT 1 FROM ohlcv_load o WHERE o.symbol = l.symbol AND o.outcome = 'loaded')
ORDER BY l.symbol, l.loaded_at DESC
"""
_ALREADY_RECORDED_SQL = """
SELECT 1 FROM integrity_monitor WHERE monitor_type = $1 AND training_window_end = $2 LIMIT 1
"""


class _Judged(NamedTuple):
    """A check's result and how many items it judged (zero means it saw nothing)."""

    result: CheckResult
    n_judged: int


@dataclass(frozen=True)
class _Params:
    close_tol_bp: float
    venue_close_rel: float
    adjusted_step_rel: float
    jump_sigma: float
    seam_scale_sessions: int
    dividend_sessions: int
    lookback_sessions: int
    volume_tol_rel: float
    completeness_min_share: float
    completeness_years: int
    nightly_max_age_hours: int
    venues: tuple[str, ...]
    venue_timeframes: tuple[str, ...]
    switches: dict[str, bool]

    @classmethod
    def from_apr(cls, apr: Mapping[str, Any]) -> _Params:
        """Fallbacks are the migration 407 seeds (and 401/437 for the switches and lists)."""
        key = "threshold.bar_reconciliation."
        return cls(
            close_tol_bp=float(_cfg(apr, key + "close_tolerance_bp", 15.0)),
            venue_close_rel=float(_cfg(apr, key + "venue_close_tolerance_rel", 0.0005)),
            adjusted_step_rel=float(_cfg(apr, key + "adjusted_ratio_step_rel", 0.02)),
            jump_sigma=float(_cfg(apr, key + "unexplained_jump_sigma", 8.0)),
            seam_scale_sessions=int(_cfg(apr, key + "seam_scale_sessions", 60)),
            dividend_sessions=int(_cfg(apr, key + "dividend_freshness_sessions", 3)),
            lookback_sessions=int(_cfg(apr, key + "lookback_sessions", 5)),
            volume_tol_rel=float(_cfg(apr, key + "volume_tolerance_rel", 0.005)),
            completeness_min_share=float(_cfg(apr, key + "completeness_min_share", 0.996)),
            completeness_years=int(_cfg(apr, key + "completeness_years", 1)),
            nightly_max_age_hours=int(_cfg(apr, key + "nightly_max_age_hours", 26)),
            venues=tuple(
                _cfg(
                    apr,
                    "infra.ibkr.venue_fallback.exchanges",
                    ["NYSE", "ARCA", "ISLAND", "AMEX", "BATS"],
                )
            ),
            venue_timeframes=tuple(_cfg(apr, "infra.ibkr.venue_fallback.timeframes", ["1d"])),
            switches={
                name: bool(_cfg(apr, f"infra.bar_derivation.{name}", False))
                for name in ("venue_bars_1d", "venue_bars_intraday", "intraday_recovery_unlocked")
            },
        )


@dataclass(frozen=True)
class _Window:
    """The audit's session calendar, fixed once per run from `now`."""

    sessions: dict[date, tuple[datetime, datetime]]
    completed: tuple[date, ...]  # completed session dates, ascending
    lookback: tuple[date, ...]
    year_start: datetime

    @property
    def last_session(self) -> date:
        return self.completed[-1]

    @property
    def judge_from(self) -> date:
        return self.lookback[0]

    def session_before(self, n: int) -> date:
        """The completed session `n` sessions before the first judged one (clamped)."""
        index = max(0, len(self.completed) - len(self.lookback) - n)
        return self.completed[index]

    @property
    def end(self) -> datetime:
        return self.sessions[self.last_session][1]

    @property
    def training_window_end(self) -> datetime:
        return datetime.combine(self.last_session, time.min, UTC)

    @classmethod
    def build(cls, now: datetime, params: _Params) -> _Window:
        # One year earlier than the completeness window needs: early in January the last
        # completed session (and so the window) still belongs to the previous year.
        first_year = now.year - params.completeness_years
        # Enough calendar days for the seam scale window ahead of the judged sessions.
        span_days = 2 * (params.seam_scale_sessions + params.lookback_sessions) + 14
        start = min(date(first_year, 1, 1), now.date() - timedelta(days=span_days))
        sessions = nyse_sessions(start, now.date())
        completed = tuple(d for d, (_, close) in sorted(sessions.items()) if close <= now)
        if not completed:
            raise RuntimeError(f"no completed NYSE session between {start} and {now.date()}")
        return cls(
            sessions=sessions,
            completed=completed,
            lookback=completed[-params.lookback_sessions :],
            year_start=datetime(
                completed[-1].year - params.completeness_years + 1, 1, 1, tzinfo=UTC
            ),
        )


def _day_start(day: date) -> datetime:
    return datetime.combine(day, time.min, UTC)


class BarReconciliationAudit(BaseBatch):
    """D7 nightly reconciliation audit, chained after every nightly backfill run."""

    job_name = _JOB
    compute_version = "1.0.0"

    async def execute(self, pool: asyncpg.Pool) -> None:
        now = datetime.now(UTC)
        async with pool.acquire() as conn:
            params = _Params.from_apr(await load_apr_dict_async(conn, _APR_PATTERNS))
            window = _Window.build(now, params)
            compute = await self._universe(conn, dimension_where_clause("compute", "i"))
            compute_1d = await self._universe(conn, dimension_where_clause("compute_1d", "i"))
            active = await self._universe(conn, dimension_where_clause("backfill", "i"))

            checks: dict[str, _Judged] = {
                "route_disagreement": await self._route_disagreement(conn, params, window),
                "adjusted_vs_trades": await self._adjusted_vs_trades(conn, params, window),
                "daily_vs_intraday": await self._daily_vs_intraday(conn, params, window, compute),
                "unexplained_seams": await self._seams(conn, params, window, compute_1d),
                "late_heads": await self._late_heads(conn, params),
                "listing_venue_coverage": await self._listing_venue_coverage(conn, params),
                "unconfirmed_empty": await self._unconfirmed_empty(conn, params),
                "partial_daily": await self._partial_daily(conn, window, active),
                "dividend_freshness": await self._dividend_freshness(conn, params, window),
                "nightly_skipped": self._nightly_skipped(params, now),
                "stray_sources": await self._stray_sources(conn, window),
                "switches": self._switches(params),
                "tradier_refused": await self._tradier_refused(conn),
            }
            grid = await self._grid_checks(conn, params, window, compute)
            checks["completeness"] = grid.completeness
            checks["masked_slots"] = grid.masked
            vendor = await self._vendor_agreement(conn, params)

        await self._report(pool, window, params, checks, grid, vendor)

    # -- loaders -------------------------------------------------------------

    @staticmethod
    async def _universe(conn: Any, clause: str) -> list[str]:
        rows = await conn.fetch(_UNIVERSE_SQL.format(clause=clause))
        return [r["symbol"] for r in rows]

    @staticmethod
    async def _route_disagreement(conn: Any, params: _Params, window: _Window) -> _Judged:
        venue_rows = await conn.fetch(_VENUE_OBS_SQL, window.judge_from, list(params.venues))
        symbols = sorted({r["symbol"] for r in venue_rows})
        if not symbols:
            return _Judged(CheckResult(0, ()), 0)
        smart_rows = await conn.fetch(_SMART_OBS_SQL, symbols, window.judge_from, "TRADES")
        listing = {
            r["symbol"]: r["primary_exchange"] for r in await conn.fetch(_LISTING_SQL, symbols)
        }
        venue = [(r["symbol"], r["bar_date"], r["route"], r["close"]) for r in venue_rows]
        smart = [(r["symbol"], r["bar_date"], COVERAGE_ROUTE, r["close"]) for r in smart_rows]
        smart_keys = {(s, d) for s, d, _, _ in smart}
        n_judged = sum(
            1
            for s, d, route, _ in venue
            if (s, d) in smart_keys and VENUE_ROUTE_ALIASES.get(route, route) == listing.get(s)
        )
        result = check_route_disagreement(venue + smart, params.venue_close_rel, listing=listing)
        logger.info(
            "bar_reconciliation.route_disagreement_non_listing",
            n_disagreeing=check_route_disagreement(venue + smart, params.venue_close_rel).n_findings
            - result.n_findings,
        )
        return _Judged(result, n_judged)

    @staticmethod
    async def _adjusted_vs_trades(conn: Any, params: _Params, window: _Window) -> _Judged:
        pair_from = window.session_before(1)
        pairs: dict[str, list[tuple[date, float, float]]] = defaultdict(list)
        for r in await conn.fetch(_ADJUSTED_PAIRS_SQL, pair_from):
            pairs[r["symbol"]].append((r["bar_date"], r["trades_close"], r["adjusted_close"]))
        if not pairs:
            return _Judged(CheckResult(0, ()), 0)
        explained = {
            (r["symbol"], r["day"])
            for r in await conn.fetch(_EXPLAINED_DATES_SQL, sorted(pairs), pair_from)
        }
        n_judged = sum(max(0, len(p) - 1) for p in pairs.values())
        return _Judged(
            check_adjusted_vs_trades(pairs, explained, params.adjusted_step_rel), n_judged
        )

    @staticmethod
    async def _partial_daily(conn: Any, window: _Window, active: list[str]) -> _Judged:
        lookback = set(window.lookback)
        latest = [
            (r["symbol"], r["bar_date"], r["fetched_at"])
            for r in await conn.fetch(_SMART_OBS_SQL, active, window.judge_from, "TRADES")
            if r["bar_date"] in lookback
        ]
        return _Judged(check_partial_daily(latest, window.sessions), len(latest))

    @staticmethod
    async def _daily_vs_intraday(
        conn: Any, params: _Params, window: _Window, compute: list[str]
    ) -> _Judged:
        """IBKR's own two views of a session: the D1 SMART TRADES daily observation vs the
        regular-session 5m bars. The canonical 1d row is not used: most names' canonical
        daily source is Tradier now (migration 438), whose volume is a different count.
        A daily observation fetched before its session closed is partial_daily's finding
        and is not judged again here."""
        lookback = set(window.lookback)
        daily = {
            (r["symbol"], r["bar_date"]): (r["open"], r["close"], r["volume"])
            for r in await conn.fetch(_SMART_OBS_SQL, compute, window.judge_from, "TRADES")
            if r["bar_date"] in lookback and r["fetched_at"] >= window.sessions[r["bar_date"]][1]
        }
        fine = await conn.fetch(
            _FINE_TRADEABLE_SQL,
            GRID_SOURCE_TF,
            compute,
            window.sessions[window.judge_from][0],
            window.end,
        )
        agg = aggregate_sessions(
            ((r["symbol"], r["timestamp"], r["open"], r["close"], r["volume"]) for r in fine),
            window.sessions,
            timedelta(minutes=_GRID_MINUTES[GRID_SOURCE_TF]),
        )
        result = check_daily_vs_intraday(daily, agg, params.close_tol_bp, params.volume_tol_rel)
        return _Judged(result, len(daily.keys() & agg.keys()))

    @staticmethod
    async def _seams(conn: Any, params: _Params, window: _Window, compute_1d: list[str]) -> _Judged:
        seam_from = window.session_before(params.seam_scale_sessions)
        closes: dict[str, list[tuple[date, float]]] = defaultdict(list)
        for r in await conn.fetch(_DAILY_CLOSES_SQL, compute_1d, _day_start(seam_from)):
            closes[r["symbol"]].append((r["timestamp"].date(), r["close"]))
        actions = {
            (r["symbol"], r["day"])
            for r in await conn.fetch(_EXPLAINED_DATES_SQL, compute_1d, seam_from)
        }
        flags = {
            (r["symbol"], r["timestamp"].date())
            for r in await conn.fetch(_QUARANTINE_1D_SQL, _day_start(seam_from))
        }
        n_judged = sum(1 for series in closes.values() for d, _ in series if d >= window.judge_from)
        result = check_unexplained_seams(
            closes, actions, flags, params.jump_sigma, judge_from=window.judge_from
        )
        return _Judged(result, n_judged)

    @staticmethod
    async def _late_heads(conn: Any, params: _Params) -> _Judged:
        inventory: dict[str, date] = {}
        lineage: dict[str, date] = {}
        for r in await conn.fetch(_VENUE_FIRST_SQL, list(params.venues)):
            symbol = r["symbol"]
            smart_head = await conn.fetchval(_SMART_HEAD_SQL, symbol)
            inventory[symbol] = min(d for d in (r["first_bar"], smart_head) if d is not None)
            head = await conn.fetchval(_CANONICAL_HEAD_SQL, symbol)
            if head is not None:
                lineage[symbol] = head.date()
        return _Judged(check_late_heads(inventory, lineage), len(inventory))

    @staticmethod
    async def _listing_venue_coverage(conn: Any, params: _Params) -> _Judged:
        rows = await conn.fetch(
            _LISTING_COVERAGE_SQL.format(clause=dimension_where_clause("compute_1d", "i")),
            list(params.venues),
        )
        stored = {r["symbol"]: (r["n_rows"], r["n_closed"]) for r in rows}
        return _Judged(check_listing_venue_coverage(stored, stored), len(stored))

    @staticmethod
    async def _unconfirmed_empty(conn: Any, params: _Params) -> _Judged:
        """Rows of the timeframes venue fallback covers are judged; the others cannot be
        confirmed by every route until verify-only reaches them (D-20) and are logged."""
        rows = await conn.fetch(_EMPTY_HISTORY_SQL)
        judged = [r for r in rows if r["timeframe"] in params.venue_timeframes]
        if len(judged) < len(rows):
            logger.info(
                "bar_reconciliation.unconfirmable_empty_history",
                n_rows=len(rows) - len(judged),
                timeframes=sorted({r["timeframe"] for r in rows} - set(params.venue_timeframes)),
            )
        result_rows: list[tuple[str, datetime, datetime]] = []
        confirmed: dict[str, list[tuple[datetime, datetime]]] = {}
        for r in judged:
            symbol, tf = r["symbol"], r["timeframe"]
            slack = timedelta(days=1) + timedelta(minutes=_TF_MINUTES[tf])
            answers = await conn.fetch(_EMPTY_ANSWERS_SQL, symbol, tf)
            spans = confirmed_spans_from_requests(
                [tuple(a) for a in answers], params.venues, slack=slack
            )
            confirmed[f"{symbol}|{tf}"] = [
                span
                for span in spans
                if not await conn.fetchval(_HAS_REAL_BAR_SQL, symbol, tf, span[0], span[1])
            ]
            result_rows.append((f"{symbol}|{tf}", r["verified_from"], r["empty_through"]))
        # Slack for the cover test is the 1d one: venue fallback is 1d-only (migration 437).
        slack_1d = timedelta(days=1) + timedelta(minutes=_TF_MINUTES["1d"])
        result = check_unconfirmed_empty(result_rows, confirmed, slack=slack_1d)
        return _Judged(result, len(result_rows))

    @staticmethod
    async def _dividend_freshness(conn: Any, params: _Params, window: _Window) -> _Judged:
        rows = await conn.fetch(
            _DIVIDEND_COVERAGE_SQL.format(clause=dimension_where_clause("compute_1d", "i")),
            AssetClass.EQUITY.value,
        )
        coverage = {r["symbol"]: r["covered_to"] for r in rows}
        result = check_dividend_freshness(
            coverage,
            window.last_session,
            params.dividend_sessions,
            session_dates=window.completed,
        )
        return _Judged(result, len(coverage))

    @staticmethod
    def _nightly_skipped(params: _Params, now: datetime) -> _Judged:
        try:
            status = json.loads(NIGHTLY_STATUS_FILE.read_text())
        except FileNotFoundError:
            status = None
        except (OSError, ValueError) as error:
            status = {"status": f"unreadable:{type(error).__name__}"}
        result = check_nightly_skipped(status, now=now, max_age_hours=params.nightly_max_age_hours)
        return _Judged(result, 1)

    @staticmethod
    async def _stray_sources(conn: Any, window: _Window) -> _Judged:
        rows = await conn.fetch(
            _SOURCE_COUNTS_SQL, sorted(ALLOWED_SOURCES), _day_start(window.judge_from)
        )
        counts: dict[tuple[str, str | None], int] = defaultdict(int)
        # One row per (timeframe, source, symbol) from the GROUP BY: a list holds each once.
        names_by_key: dict[tuple[str, str | None], list[str]] = defaultdict(list)
        for r in rows:
            key = (r["timeframe"], r["source"])
            counts[key] += r["n"]
            names_by_key[key].append(r["symbol"])
        result = check_stray_sources(counts)
        stray = {
            f"{tf}:{source}": sorted(names)
            for (tf, source), names in names_by_key.items()
            if source not in ALLOWED_SOURCES[tf]
        }
        if stray:
            logger.error("bar_reconciliation.stray_source_symbols", symbols_by_source=stray)
        return _Judged(result, sum(counts.values()))

    @staticmethod
    async def _tradier_refused(conn: Any) -> _Judged:
        latest = {
            r["symbol"]: (r["outcome"], r["detail"])
            for r in await conn.fetch(_TRADIER_LATEST_LOAD_SQL)
        }
        return _Judged(check_tradier_refused(latest), len(latest))

    @staticmethod
    def _switches(params: _Params) -> _Judged:
        """The study verdict file; absent, nothing passed (D-17: venue bars stay unused)."""
        try:
            results = json.loads(_VERDICT_FILE.read_text())["results"]
            verdict = {tf: bool(results[tf]["passed"]) for tf in results}
        except FileNotFoundError:
            verdict = {}
        return _Judged(check_switches(params.switches, verdict), len(_SWITCH_VERDICT_TF))

    async def _grid_checks(
        self, conn: Any, params: _Params, window: _Window, compute: list[str]
    ) -> _GridOutcome:
        """Completeness (5m, 15m, 1h) and masked 15m/1h slots over the completeness years,
        one symbol at a time from the same reads."""
        start, end = window.year_start, window.end
        grid_tfs = list(GRID_TIMEFRAMES)
        cells: list[CompletenessCell] = []
        masked_by_tf: dict[str, int] = defaultdict(int)
        # Every grid timeframe gets a fact, zero included (a clean run is a recorded pass).
        masked_derived: dict[str, int] = dict.fromkeys(grid_tfs, 0)
        partial_by_tf: dict[str, int] = defaultdict(int)
        masked_samples: list[str] = []
        no_history: list[str] = []
        for symbol in compute:
            stored_rows = {
                tf: await conn.fetch(_GRID_ROWS_SQL, symbol, tf, start, end) for tf in _GRID_MINUTES
            }
            answered = AnsweredWindows.from_rows(
                (r["window_start"], r["window_end"])
                for r in await conn.fetch(
                    _ANSWERED_5M_SQL,
                    symbol,
                    GRID_SOURCE_TF,
                    COVERAGE_ROUTE,
                    COVERAGE_WHAT_TO_SHOW,
                    list(ANSWERED_OUTCOMES),
                )
            )
            for tf, minutes in _GRID_MINUTES.items():
                real = [
                    r["timestamp"] for r in stored_rows[tf] if r["source"] != SOURCE_SYNTHETIC_FILL
                ]
                has_before = await conn.fetchval(_HAS_REAL_BEFORE_SQL, symbol, tf, start)
                if not real and not has_before:
                    no_history.append(f"{symbol}|{tf}")
                    continue
                first = start if has_before else min(real)
                slots = session_slots(window.sessions, minutes, first, end)
                cells += completeness_cells(
                    symbol, tf, slots, real, answered, timedelta(minutes=minutes), window.sessions
                )

            fine = [
                (r["timestamp"], r["volume"])
                for r in stored_rows[GRID_SOURCE_TF]
                if r["source"] != SOURCE_SYNTHETIC_FILL and r["volume"] > 0
            ]
            if not fine:
                continue
            partial = {
                (r["timeframe"], r["timestamp"])
                for r in await conn.fetch(
                    _PARTIAL_FLAGS_SQL, symbol, grid_tfs, _PARTIAL_RULE, start, end
                )
            }
            for tf in grid_tfs:
                coarse = {
                    r["timestamp"]: (
                        "placeholder"
                        if r["source"] == SOURCE_SYNTHETIC_FILL
                        else "partial" if (tf, r["timestamp"]) in partial else "real"
                    )
                    for r in stored_rows[tf]
                }
                by_slot = bucket_fine_volume(fine, window.sessions, GRID_TIMEFRAMES[tf])
                masked = check_masked_slots(coarse, by_slot)
                partial_by_tf[tf] += sum(
                    1 for slot, v in by_slot.items() if v > 0 and coarse.get(slot) == "partial"
                )
                if masked.n_findings:
                    derived = any(r["source"] == SOURCE_DERIVED_5M for r in stored_rows[tf])
                    masked_by_tf[tf] += masked.n_findings
                    if derived:
                        masked_derived[tf] += masked.n_findings
                    masked_samples.append(
                        f"{symbol}|{tf}|masked={masked.n_findings}|derived={str(derived).lower()}"
                    )

        completeness, pooled = check_completeness(cells, params.completeness_min_share)
        if no_history:
            logger.info("bar_reconciliation.completeness_no_history", cells=no_history)
        n_masked = sum(masked_by_tf.values())
        return _GridOutcome(
            completeness=_Judged(completeness, len(cells)),
            shortfalls=[
                c for c in cells if c.n_expected and c.share < params.completeness_min_share
            ],
            masked=_Judged(CheckResult(n_masked, tuple(masked_samples)), len(compute)),
            pooled_share=pooled,
            masked_by_tf=dict(masked_by_tf),
            masked_derived_by_tf=dict(masked_derived),
            partial_by_tf=dict(partial_by_tf),
        )

    @staticmethod
    async def _vendor_agreement(conn: Any, params: _Params) -> dict[int, VendorYear]:
        """Tradier vs IBKR SMART TRADES over every name with both, one symbol per query
        (index-driven; the whole overlap is about 4M days)."""
        acc = VendorAgreementAccumulator(params.close_tol_bp)
        for r in await conn.fetch(_VENDOR_SYMBOLS_SQL, SOURCE_TRADIER):
            acc.add(
                tuple(row)
                for row in await conn.fetch(_VENDOR_PAIRS_SQL, r["symbol"], SOURCE_TRADIER)
            )
        return acc.result()

    # -- reporting -----------------------------------------------------------

    async def _report(
        self,
        pool: asyncpg.Pool,
        window: _Window,
        params: _Params,
        checks: Mapping[str, _Judged],
        grid: _GridOutcome,
        vendor: Mapping[int, VendorYear],
    ) -> None:
        for name, judged in checks.items():
            n = judged.result.n_findings
            FINDINGS_TOTAL.add(n, {"check": name})
            if n:
                logger.error(
                    "bar_reconciliation.findings",
                    check=name,
                    n_findings=n,
                    n_judged=judged.n_judged,
                    subjects=list(judged.result.samples),
                )
            else:
                logger.info(
                    "bar_reconciliation.clean",
                    check=name,
                    n_judged=judged.n_judged,
                    notes=list(judged.result.samples),
                )
        for tf, share in grid.pooled_share.items():
            COMPLETENESS_SHARE.set(share, {"check": "completeness", "timeframe": tf})
        for year, v in vendor.items():
            attrs = {"check": "vendor_agreement", "year": str(year)}
            VENDOR_CLOSE_DIFFER_SHARE.set(v.share_differ, attrs)
            if v.median_volume_ratio is not None:
                VENDOR_VOLUME_RATIO.set(v.median_volume_ratio, attrs)
        logger.info(
            "bar_reconciliation.grid",
            pooled_completeness=grid.pooled_share,
            masked_by_tf=grid.masked_by_tf,
            masked_derived_by_tf=grid.masked_derived_by_tf,
            partial_with_volume_by_tf=grid.partial_by_tf,
        )
        logger.info(
            "bar_reconciliation.vendor_agreement",
            by_year={
                y: {
                    "n_both": v.n_both,
                    "share_differ": round(v.share_differ, 4),
                    "median_volume_ratio": v.median_volume_ratio,
                }
                for y, v in vendor.items()
            },
        )

        twe = window.training_window_end
        async with pool.acquire() as conn:
            if await conn.fetchval(_ALREADY_RECORDED_SQL, _MONITOR_TYPE, twe):
                logger.info("bar_reconciliation.facts_already_recorded", session=str(twe.date()))
            else:
                # All or nothing: a run killed mid-emission leaves no facts, so the retry's
                # already-recorded guard cannot skip the facts it never wrote.
                async with conn.transaction():
                    await self._emit_facts(conn, twe, params, checks, grid, vendor)

        self._print_report(window, checks, grid, vendor)

    @staticmethod
    async def _emit_facts(
        conn: Any,
        twe: datetime,
        params: _Params,
        checks: Mapping[str, _Judged],
        grid: _GridOutcome,
        vendor: Mapping[int, VendorYear],
    ) -> None:
        """One summary fact per check (its own metric name, so the session-date idempotency
        guard keeps each), plus the per-cell detail the metrics deliberately omit."""
        for name, judged in checks.items():
            n = judged.result.n_findings
            subject = f"check={name}"
            await emit_integrity_fact_async(
                conn,
                _MONITOR_TYPE,
                subject,
                f"{name}_findings",
                float(n),
                0.0,
                n == 0,
                twe,
                idempotency_check=True,
            )
            await emit_integrity_fact_async(
                conn,
                _MONITOR_TYPE,
                subject,
                f"{name}_judged",
                float(judged.n_judged),
                None,
                True,
                twe,
                idempotency_check=True,
            )
        for cell in grid.shortfalls:
            await emit_integrity_fact_async(
                conn,
                _MONITOR_TYPE,
                f"check=completeness|symbol={cell.symbol}|tf={cell.timeframe}|year={cell.year}",
                "completeness_share",
                cell.share,
                params.completeness_min_share,
                False,
                twe,
            )
        for tf, n in grid.masked_derived_by_tf.items():
            await emit_integrity_fact_async(
                conn,
                _MONITOR_TYPE,
                f"check=masked_slots|tf={tf}",
                "masked_slots_derived_symbols",
                float(n),
                0.0,
                n == 0,
                twe,
            )
        for year, v in vendor.items():
            subject = f"check=vendor_agreement|year={year}"
            await emit_integrity_fact_async(
                conn,
                _MONITOR_TYPE,
                subject,
                "vendor_close_differ_share",
                v.share_differ,
                None,
                True,
                twe,
            )
            if v.median_volume_ratio is not None:
                await emit_integrity_fact_async(
                    conn,
                    _MONITOR_TYPE,
                    subject,
                    "vendor_volume_ratio_median",
                    v.median_volume_ratio,
                    None,
                    True,
                    twe,
                )

    @staticmethod
    def _print_report(
        window: _Window,
        checks: Mapping[str, _Judged],
        grid: _GridOutcome,
        vendor: Mapping[int, VendorYear],
    ) -> None:
        print("# Bar reconciliation audit (D7)\n")
        print(
            f"Last session: {window.last_session}; judged sessions: {', '.join(map(str, window.lookback))}"
        )
        print(f"Completeness window from {window.year_start.date()}\n")
        print(f"{'check':<22} {'findings':>9} {'judged':>9}")
        for name, judged in checks.items():
            print(f"{name:<22} {judged.result.n_findings:>9} {judged.n_judged:>9}")
        print(f"\nPooled completeness by timeframe: {grid.pooled_share}")
        print(f"Masked slots by timeframe: {grid.masked_by_tf}")
        print(f"Masked slots on derived symbols: {grid.masked_derived_by_tf}")
        print(f"Partial-constituent slots with 5m volume (not masked): {grid.partial_by_tf}")
        print("\nVendor agreement (Tradier vs IBKR SMART TRADES):")
        print(f"{'year':<6} {'n_both':>8} {'differ':>8} {'median_vol_ratio':>17}")
        for year, v in vendor.items():
            ratio = f"{v.median_volume_ratio:.3f}" if v.median_volume_ratio is not None else "-"
            print(f"{year:<6} {v.n_both:>8} {v.share_differ:>8.4f} {ratio:>17}")
        total = sum(j.result.n_findings for j in checks.values())
        print(f"\n{'FINDINGS' if total else 'CLEAN'} -- observability only, never a hard gate.")


class _GridOutcome(NamedTuple):
    completeness: _Judged
    shortfalls: list[CompletenessCell]
    masked: _Judged
    pooled_share: dict[str, float]
    masked_by_tf: dict[str, int]
    masked_derived_by_tf: dict[str, int]
    partial_by_tf: dict[str, int]


if __name__ == "__main__":
    try:
        init_otel_providers("indicagent-bar-reconciliation-audit")
    except OTelInitError as error:
        logger.warning("bar_reconciliation.otel_init_failed", error=str(error))

    settings = Settings()
    db_dsn = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
    asyncio.run(BarReconciliationAudit(db_dsn=db_dsn).run())
