"""D7 nightly reconciliation audit (phase 185 plan 23, D-26, todo 462).

One oneshot, chained as the last step of every nightly backfill run, that audits each
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
- unconfirmed_empty: an ohlcv_empty_history row no set of every-route answers confirms.
- dividend_freshness: Yahoo dividend coverage trailing the last session.
- nightly_skipped: the nightly did not finish with success recently (D-29 lease timeout
  included).
- stray_sources: 1d/15m/1h rows with a source the derivation does not write.
- switches: venue switches differing from the venue study verdict.
- completeness and masked_slots (todo 462): per (symbol, timeframe, year) the share of
  expected session slots that hold a real bar or lie inside an answered request window,
  and the 15m/1h slots that hide real 5m volume behind a placeholder or a hole.
- vendor_agreement: Tradier vs IBKR SMART TRADES closes and volumes in D1, per year
  (Tradier is the primary 1d source since migration 438).

Observability only, the classification-coverage contract: a finding is reported loudly
(an integrity_monitor fact, an OTel metric labeled by check, and by timeframe or year
where the plan says so, never by symbol; the per-symbol detail goes to the log at error
level), never through the exit code. Only a runtime error fails the run (BaseBatch D-06).

The checks are pure functions (no connection, no clock) so each is tested on fixtures;
the class below only loads their inputs and reports their results.
"""

from __future__ import annotations

import asyncio
import math
import statistics
from array import array
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, NamedTuple

import asyncpg
import structlog

from src.config.settings import Settings
from src.core.agent.base_batch import BaseBatch
from src.core.bar_normalizer import SOURCE_SYNTHETIC_FILL
from src.intelligence.bars.derivation import SOURCE_NAMED, SOURCE_VENUE
from src.intelligence.bars.gap_plan import AnsweredWindows
from src.intelligence.bars.sources import GRID_TIMEFRAMES, SOURCE_DERIVED_5M
from src.observability.metrics import counter
from src.observability.otel import OTelInitError, init_otel_providers
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
    rows: Iterable[tuple[str, date, str, float]], rel: float
) -> CheckResult:
    """Venue-routed closes that differ from the same day's SMART close by more than `rel`.

    rows: (symbol, bar_date, route, close). A venue row with no SMART row for its
    (symbol, date) has nothing to disagree with and is not judged.
    """
    rows = list(rows)
    smart = {(s, d): c for s, d, route, c in rows if route == "SMART"}
    samples = sorted(
        f"{s}|{d.isoformat()}|{route}"
        for s, d, route, c in rows
        if route != "SMART" and (s, d) in smart and abs(c / smart[(s, d)] - 1.0) > rel
    )
    return CheckResult(len(samples), tuple(samples))


def check_adjusted_vs_trades(
    pairs: Mapping[str, Sequence[tuple[date, float, float]]],
    explained_dates: set[tuple[str, date]],
    rel: float,
) -> CheckResult:
    """Steps in the ADJUSTED_LAST / TRADES ratio no dividend or corporate action explains.

    pairs: symbol -> date-sorted (date, trades_close, adjusted_close). IBKR scales every
    adjusted close before an ex-date, so the step lands on the ex-date itself.
    """
    samples: list[str] = []
    for symbol in sorted(pairs):
        prev: float | None = None
        for day, trades, adjusted in pairs[symbol]:
            if trades <= 0 or adjusted <= 0:
                prev = None
                continue
            ratio = adjusted / trades
            if (
                prev is not None
                and abs(ratio / prev - 1.0) > rel
                and (symbol, day) not in explained_dates
            ):
                samples.append(f"{symbol}|{day.isoformat()}")
            prev = ratio
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
    action on the jump day, or a quarantine flag on either bar of the pair, explains it.
    """
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
            if (symbol, day) in actions or (symbol, day) in flags or (symbol, prev_day) in flags:
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
) -> list[CompletenessCell]:
    """Per-year completeness for one (symbol, timeframe): a slot is complete when a stored
    real bar sits on it or the whole slot lies inside an answered request window."""
    stored_set = set(stored)
    expected: dict[int, int] = defaultdict(int)
    complete: dict[int, int] = defaultdict(int)
    for slot in expected_slots:
        expected[slot.year] += 1
        if slot in stored_set or answered_windows.covers(slot, interval):
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
# BaseBatch oneshot. A finding never raises; a runtime error propagates.
# ---------------------------------------------------------------------------


class BarReconciliationAudit(BaseBatch):
    """D7 nightly reconciliation audit, chained after every nightly backfill run."""

    job_name = _JOB
    compute_version = "1.0.0"

    async def execute(self, pool: asyncpg.Pool) -> None:
        raise NotImplementedError("IO lands in plan 185-23 task 2")


if __name__ == "__main__":
    try:
        init_otel_providers("indicagent-bar-reconciliation-audit")
    except OTelInitError as error:
        logger.warning("bar_reconciliation.otel_init_failed", error=str(error))

    settings = Settings()
    db_dsn = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
    asyncio.run(BarReconciliationAudit(db_dsn=db_dsn).run())
