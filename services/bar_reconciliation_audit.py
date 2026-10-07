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

- the 1d verdict report (plan 185-33, data layer integrity design section 6): one integrity_monitor
  row per (symbol, 1d, check) with monitor_type bar_integrity, written every run, for every
  compute_1d name: session_coverage, policy_conformance, lineage_missing, canonical_recompute
  (d2-v2 recomputed equals stored, bit-exact), digest_fresh, unexplained_seam, vendor_basis_run
  and report_age, plus refused_head_1d as an informational row. The pure judgement is
  src/intelligence/bars/integrity_checks.judge_name_1d; the gates (185-41) read the rows.

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
from time import perf_counter
from typing import Any, NamedTuple

import asyncpg
import numpy as np
import psycopg
import structlog

from scripts.infrastructure.backfill._fetcher_lock import FetcherLock
from services._batch_utils import cfg as _cfg
from services._batch_utils import load_apr_dict_async
from services.bar_derivation import (
    _D2V2_ROUTES,
    _SELECT_1D_FLAG_RULES_SQL,
    _SELECT_5M_FLAGS_SQL,
    _SELECT_5M_SQL,
    _SELECT_CURRENT_1D_DIGESTS_SQL,
    _SELECT_CURRENT_GRID_DIGESTS_SQL,
    _SELECT_DAILY_OBSERVATIONS_SQL,
    _SELECT_DAILY_SPLITS_SQL,
    _SELECT_POLICY_1D_SQL,
    _SELECT_STORED_1D_SQL,
    _derive_for_tf,
    _month_digest_rows,
)
from services.ohlcv_coverage_writer import rebuild_from_stored_state
from src.config.settings import Settings, dimension_where_clause
from src.core.agent.base_batch import BaseBatch
from src.core.bar_accumulator import _TF_MINUTES
from src.core.bar_normalizer import SOURCE_SYNTHETIC_FILL
from src.core.integrity_monitor import emit_integrity_fact_async, emit_integrity_facts_async
from src.core.models import AssetClass
from src.intelligence.bars.daily_rule import PolicyRow
from src.intelligence.bars.derivation import SOURCE_NAMED, SOURCE_VENUE, Observation, SplitRecord
from src.intelligence.bars.digest import EMPTY_INPUT_DIGEST, month_ranges
from src.intelligence.bars.gap_plan import (
    ANSWERED_OUTCOMES,
    COVERAGE_ROUTE,
    COVERAGE_WHAT_TO_SHOW,
    AnsweredWindows,
    confirmed_empty_spans,
)
from src.intelligence.bars.integrity_checks import (
    CHECKS_1D,
    CHECKS_INTRADAY,
    INFO_DIGEST_FULL_SWEEP,
    INFO_REFUSED_HEAD,
    SWEEP_SUBJECT,
    NameInputs1d,
    StoredBar,
    Values,
    answered_slots,
    digest_scope,
    grid_parity,
    judge_name_1d,
    rebucket_5m,
    slot_coverage_by_year,
)
from src.intelligence.bars.sessions import nyse_sessions
from src.intelligence.bars.sources import (
    CANONICAL_1D_SOURCES,
    GRID_SOURCE_TF,
    GRID_TIMEFRAMES,
    SOURCE_DERIVED_5M,
    SOURCE_IBKR_FALLBACK,
)
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
    "1d": frozenset(
        {SOURCE_NAMED, SOURCE_VENUE, SOURCE_TRADIER, SOURCE_IBKR_FALLBACK, SOURCE_SYNTHETIC_FILL}
    ),
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

# Alert inputs (plan 185-41, design section 8). Labels are check or source only: the collector
# drops a metric that carries a `job` label (todo 498). A oneshot's gauges leave the Prometheus
# exporter minutes after the run, so the Grafana rules read them through last_over_time.
BAR_INTEGRITY_FAILING_NAMES = point_gauge(
    "bar_integrity_failing_names",
    "Names failing each bar_integrity check in the latest D7 report, labeled by check only.",
)
BAR_INTEGRITY_REPORT_AGE_SECONDS = point_gauge(
    "bar_integrity_report_age_seconds",
    "Seconds between the previous bar_integrity report and this D7 run's start (no labels).",
)
BAR_INTEGRITY_REPORT_MAX_AGE_SECONDS = point_gauge(
    "bar_integrity_report_max_age_seconds",
    "threshold.bar_integrity.report_max_age_hours in seconds, the limit the age is judged "
    "against (no labels).",
)
OHLCV_LOAD_REFUSED_24H = point_gauge(
    "ohlcv_load_refused_24h",
    "ohlcv_load rows with outcome refused or gated in the 24 h before this D7 run, labeled by "
    "source only.",
)
# ohlcv_load.source values (the table's CHECK constraint); each gets a gauge point every run.
LOAD_SOURCES = ("tradier", "ibkr", "derived")
_REFUSED_LOADS_24H_SQL = """
SELECT source, count(*) AS n FROM ohlcv_load
WHERE outcome IN ('refused', 'gated') AND loaded_at >= $1 GROUP BY source
"""
# Newest verdict row before this run writes any (the report age's start).
_NEWEST_VERDICT_SQL = """
SELECT max(evaluated_at) FROM integrity_monitor WHERE monitor_type = $1
"""

_APR_PATTERNS = [
    "threshold.bar_reconciliation.%",
    "infra.bar_derivation.%",
    "infra.ibkr.venue_fallback.%",
    "threshold.bar_integrity.%",
    "infra.bar_integrity.%",
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
WHERE l.source = 'tradier'
  AND EXISTS (SELECT 1 FROM ohlcv_load o
              WHERE o.symbol = l.symbol AND o.source = 'tradier' AND o.outcome = 'loaded')
ORDER BY l.symbol, l.loaded_at DESC
"""
_ALREADY_RECORDED_SQL = """
SELECT 1 FROM integrity_monitor WHERE monitor_type = $1 AND training_window_end = $2 LIMIT 1
"""


# ---------------------------------------------------------------------------
# The 1d verdict report (plan 185-33, data layer integrity design section 6): per-name loaders.
# The per-name reads are bar_derivation's own SQL (imported above), so the audit judges the same
# inputs the daily stage derives from.
# ---------------------------------------------------------------------------

_MONITOR_TYPE_VERDICT = "bar_integrity"
# Informational facts: reported, never failing (the name's history simply starts later).
_INFORMATIONAL_CHECKS = frozenset({"untraced_quarantined_1d"})
_VERDICT_GROUP_NAMES = 50

# Visible bars of the canonical lineage view with no request ids, and whether the tradeable view
# shows them (a hidden one is quarantined, counted in untraced_quarantined_1d instead). One
# set-based read: 185-38 measured the full view at 42 s, under the plan's 10 minute line.
_LINEAGE_MISSING_SQL = """
SELECT l.symbol, (l."timestamp" AT TIME ZONE 'UTC')::date AS bar_date,
       (t."timestamp" IS NOT NULL) AS visible
FROM canonical_bar_lineage l
LEFT JOIN market_data_ohlcv_tradeable t
  ON t.symbol = l.symbol AND t.timeframe = '1d' AND t."timestamp" = l."timestamp"
WHERE l.request_ids IS NULL
"""
# Sessions an answer says are empty: IBKR's confirmed empty history, and Tradier no_data
# windows. A lone IBKR SMART no_data is not evidence (IBKR history starts at the last venue
# move), so ohlcv_request rows of IBKR do not count here.
_EMPTY_SESSIONS_SQL = """
SELECT symbol, (verified_from AT TIME ZONE 'UTC')::date AS span_start,
       (empty_through AT TIME ZONE 'UTC')::date AS span_end
FROM ohlcv_empty_history WHERE timeframe = '1d' AND provider = 'ibkr'
UNION ALL
SELECT symbol, (window_start AT TIME ZONE 'UTC')::date, (window_end AT TIME ZONE 'UTC')::date
FROM ohlcv_request
WHERE source = 'tradier' AND timeframe = '1d' AND outcome = 'no_data' AND window_start IS NOT NULL
"""
_LATEST_1D_LOAD_SQL = """
SELECT symbol, max(loaded_at) AS loaded_at FROM ohlcv_load WHERE timeframe = '1d' GROUP BY symbol
"""
_FIRST_1D_BAR_SQL = """
SELECT min("timestamp") AS first_bar FROM market_data_ohlcv
WHERE timeframe = '1d' AND source = ANY($1::text[])
"""


def merge_failing_by_check(*reports: Mapping[str, int]) -> dict[str, int]:
    """Failing name counts per check across the 1d and intraday reports (a check that runs in
    both, such as digest_fresh, sums)."""
    merged: dict[str, int] = {}
    for report in reports:
        for check, n in report.items():
            merged[check] = merged.get(check, 0) + n
    return merged


def record_alert_gauges(
    *,
    failing_by_check: Mapping[str, int],
    previous_verdict_at: datetime | None,
    run_start: datetime,
    max_age_hours: float,
    refused_by_source: Mapping[str, int],
) -> None:
    """Record the four alert gauges. The age is how long the previous report had stood when this
    run began (none on the first run); every load source records a point so a clear reads 0."""
    for check, n in failing_by_check.items():
        BAR_INTEGRITY_FAILING_NAMES.set(n, {"check": check})
    if previous_verdict_at is not None:
        BAR_INTEGRITY_REPORT_AGE_SECONDS.set((run_start - previous_verdict_at).total_seconds())
    BAR_INTEGRITY_REPORT_MAX_AGE_SECONDS.set(max_age_hours * 3600.0)
    for source in LOAD_SOURCES:
        OHLCV_LOAD_REFUSED_24H.set(refused_by_source.get(source, 0), {"source": source})


class _Judged(NamedTuple):
    """A check's result and how many items it judged (zero means it saw nothing)."""

    result: CheckResult
    n_judged: int


def findings_by_symbol(samples: Iterable[str]) -> dict[str, int]:
    """Per-symbol finding counts from 'SYMBOL|detail' samples (the seam rule's output)."""
    counts: dict[str, int] = defaultdict(int)
    for sample in samples:
        counts[sample.split("|", 1)[0]] += 1
    return dict(counts)


def _policy_rows(rows: Iterable[Mapping[str, Any]]) -> list[PolicyRow]:
    return [
        PolicyRow(
            timeframe=r["timeframe"],
            symbol=r["symbol"],
            valid_from=r["valid_from"],
            valid_to=r["valid_to"],
            ingress_mode=r["ingress_mode"],
            primary_source=r["primary_source"],
            fallback_source=r["fallback_source"],
        )
        for r in rows
    ]


def _observations(rows: Iterable[Mapping[str, Any]]) -> list[Observation]:
    return [
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
        for r in rows
    ]


def _splits(rows: Iterable[Mapping[str, Any]]) -> list[SplitRecord]:
    return [
        SplitRecord(
            effective_date=r["effective_date"],
            recorded_at=r["recorded_at"],
            factor=r["factor"],
            evidence_request_ids=tuple(r["evidence_request_ids"] or ()),
        )
        for r in rows
    ]


class _VerdictRun(NamedTuple):
    """The 1d report of one audit run: the rows to write and the numbers the log reports."""

    facts: list[tuple[str, str | None, str, float | None, float | None, bool, Any]]
    failing_by_check: dict[str, int]
    passing_by_check: dict[str, int]
    timings: dict[str, float]
    untraced_hidden: _Judged
    n_names: int
    n_basis_runs: int
    blocking_samples: list[str]


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
class _IntegrityParams:
    """Thresholds of the verdict report (migration 449 for 1d, 450 for intraday; basis keys are
    185-36's)."""

    session_coverage_min: float
    vendor_run_min_sessions: int
    report_max_age_hours: int
    basis_window_sessions: int
    basis_tolerance_bp: float
    slot_coverage_min_intraday: float = 0.995
    intraday_full_sweep_days: int = 7

    @classmethod
    def from_apr(cls, apr: Mapping[str, Any]) -> _IntegrityParams:
        return cls(
            slot_coverage_min_intraday=float(
                _cfg(apr, "threshold.bar_integrity.slot_coverage_min_intraday", 0.995)
            ),
            intraday_full_sweep_days=int(
                _cfg(apr, "infra.bar_integrity.intraday_full_sweep_days", 7)
            ),
            session_coverage_min=float(
                _cfg(apr, "threshold.bar_integrity.session_coverage_min_1d", 0.999)
            ),
            vendor_run_min_sessions=int(
                _cfg(apr, "threshold.bar_integrity.vendor_ratio_run_min_sessions", 5)
            ),
            report_max_age_hours=int(_cfg(apr, "threshold.bar_integrity.report_max_age_hours", 30)),
            basis_window_sessions=int(
                _cfg(apr, "threshold.bar_integrity.fallback_basis_window_sessions", 20)
            ),
            basis_tolerance_bp=float(
                _cfg(apr, "threshold.bar_integrity.fallback_basis_tolerance_bp", 10.0)
            ),
        )


# ---------------------------------------------------------------------------
# The intraday verdicts (plan 185-40, data layer integrity design sections 5 and 6)
# ---------------------------------------------------------------------------

_INTRADAY_NAMES_SQL = """
SELECT i.symbol FROM instruments i
WHERE EXISTS (SELECT 1 FROM market_data_ohlcv m WHERE m.symbol = i.symbol AND m.timeframe = '5m')
ORDER BY i.symbol
"""
# Stored 5m stamps that hold an answer: real bars and zero-volume provider bars; the placeholders
# ($2) are the only rows left out. Raw table (allow-listed): the tradeable view hides zero volume.
_RAW_5M_SLOTS_SQL = """
SELECT "timestamp" FROM market_data_ohlcv
WHERE symbol = $1 AND timeframe = '5m' AND source IS DISTINCT FROM $2
"""
_ARCHIVE_ROWS_SQL = """
SELECT timeframe, "timestamp", open, high, low, close, volume
FROM ohlcv_intraday_raw_archive
WHERE symbol = $1 AND timeframe = ANY($2::text[])
"""
# Raw table (allow-listed): the stray vendor rows are exactly what the tradeable view would hide.
_STRAY_VENDOR_SQL = """
SELECT symbol, timeframe, count(*) AS n FROM market_data_ohlcv
WHERE timeframe = ANY($1::text[]) AND source IS DISTINCT FROM $2 AND symbol = ANY($3::text[])
GROUP BY 1, 2
"""
_PREVIOUS_DIGEST_VERDICT_SQL = """
SELECT DISTINCT ON (subject) subject, passed, evaluated_at FROM integrity_monitor
WHERE monitor_type = $1 AND metric_name = $2 AND subject LIKE '%|5m'
ORDER BY subject, evaluated_at DESC
"""
_LATEST_SWEEP_SQL = """
SELECT max(evaluated_at) FROM integrity_monitor WHERE monitor_type = $1 AND metric_name = $2
"""
# Loads that changed something: the months a digest recompute has to look at.
_CHANGING_LOADS_SQL = """
SELECT symbol, loaded_at, first_bar, last_bar FROM ohlcv_load
WHERE timeframe = ANY($1::text[]) AND loaded_at > $2
  AND (n_new + n_changed + coalesce(n_removed, 0)) > 0
"""
_COVERAGE_ROWS_SQL = """
SELECT symbol, timeframe, earliest_timestamp, latest_timestamp, row_count, last_fetch_status
FROM ohlcv_coverage WHERE symbol = ANY(%s)
"""
_SESSION_MARGIN_DAYS = 3
_FIVE_MINUTES = timedelta(minutes=5)
_INTRADAY_DIGEST_TFS = (GRID_SOURCE_TF, *sorted(GRID_TIMEFRAMES))
_WRITER_ROLE = "bar_derivation_writer"


@dataclass(frozen=True)
class _FiveMinute:
    """A name's tradeable 5m bars with the rules of their non-quarantine flags, as
    bar_derivation reads them (quarantined bars are left out)."""

    ts: np.ndarray
    open: np.ndarray
    high: np.ndarray
    low: np.ndarray
    close: np.ndarray
    volume: np.ndarray
    rules: list[tuple[str, ...]]

    @classmethod
    def from_rows(
        cls, rows: Sequence[Mapping[str, Any]], flag_rows: Sequence[Mapping[str, Any]]
    ) -> _FiveMinute:
        quarantined = {int(r["timestamp"].timestamp()) for r in flag_rows if r["quarantine"]}
        rules_by_ts: dict[int, set[str]] = defaultdict(set)
        for r in flag_rows:
            if not r["quarantine"]:
                rules_by_ts[int(r["timestamp"].timestamp())].add(r["rule"])
        kept = [r for r in rows if int(r["timestamp"].timestamp()) not in quarantined]
        ts = np.array([int(r["timestamp"].timestamp()) for r in kept], dtype=np.int64)

        def column(name: str) -> np.ndarray:
            return np.array([r[name] for r in kept], dtype=np.float64)

        return cls(
            ts,
            column("open"),
            column("high"),
            column("low"),
            column("close"),
            column("volume"),
            [tuple(sorted(rules_by_ts.get(int(t), ()))) for t in ts],
        )


@dataclass(frozen=True)
class _IntradayInputs:
    """Everything the intraday verdicts read for one name; the loader fills it."""

    symbol: str
    five: _FiveMinute
    stored_slots: Sequence[datetime]
    answered: AnsweredWindows
    archive: Mapping[str, Mapping[datetime, Values]]
    current_digests: Mapping[str, Mapping[datetime, str]]
    scope: frozenset[datetime] | None
    stray: Mapping[str, int]


class _IntradayVerdict(NamedTuple):
    timeframe: str
    check: str
    passed: bool
    metric: float | None
    threshold: float


class _SessionCalendar:
    """NYSE sessions up to the audit's last completed one, built once and extended backwards only
    when a name starts earlier than anything seen so far."""

    def __init__(self, last: date) -> None:
        self._last = last + timedelta(days=_SESSION_MARGIN_DAYS)
        self._floor: date | None = None
        self._sessions: dict[date, tuple[datetime, datetime]] = {}

    def between(self, first: date, last: date) -> dict[date, tuple[datetime, datetime]]:
        first -= timedelta(days=_SESSION_MARGIN_DAYS)
        if self._floor is None or first < self._floor:
            self._floor = first - timedelta(days=365)
            self._sessions = nyse_sessions(self._floor, self._last)
        last += timedelta(days=_SESSION_MARGIN_DAYS)
        return {d: b for d, b in self._sessions.items() if first <= d <= last}


def intraday_month_digests(
    five: _FiveMinute,
    sessions: Mapping[date, tuple[datetime, datetime]],
    scope: frozenset[datetime] | None,
) -> tuple[dict[str, dict[datetime, str]], frozenset[datetime]]:
    """Recomputed month digests per timeframe (5m, 15m, 1h) for the scoped months, by
    bar_derivation's own recipe, and the months actually checked.

    The checked months are the scope's months inside the 5m series' first-to-last range
    (all of them when scope is None). A month with no rows has no recomputed digest.
    """
    out: dict[str, dict[datetime, str]] = {tf: {} for tf in _INTRADAY_DIGEST_TFS}
    if not five.ts.size:
        return out, frozenset()
    targets = frozenset(start for start, _ in month_ranges(five.ts))
    if scope is not None:
        targets &= scope
    if not targets:
        return out, targets
    months = five.ts.astype("datetime64[s]").astype("datetime64[M]")
    wanted = np.array([np.datetime64(f"{d.year:04d}-{d.month:02d}") for d in targets])
    rows = np.flatnonzero(np.isin(months, wanted))
    ts, o, h, lo, c, v = (
        a[rows] for a in (five.ts, five.open, five.high, five.low, five.close, five.volume)
    )
    rules = [five.rules[i] for i in rows]
    out[GRID_SOURCE_TF] = {s: d for s, _, d, _ in _month_digest_rows(ts, o, h, lo, c, v, rules)}
    for tf, minutes in GRID_TIMEFRAMES.items():
        grid, grid_rules = _derive_for_tf(ts, o, h, lo, c, v, rules, dict(sessions), minutes)
        out[tf] = {
            s: d
            for s, _, d, _ in _month_digest_rows(
                grid.ts_seconds, grid.open, grid.high, grid.low, grid.close, grid.volume, grid_rules
            )
        }
    return out, targets


def stale_intraday_months(
    recomputed: Mapping[datetime, str], current: Mapping[datetime, str], targets: Iterable[datetime]
) -> list[datetime]:
    """Checked months whose stored digest is missing or differs from the recompute. A month the
    recompute has no rows for is stale only when a non-empty digest is still stored for it."""
    stale = []
    for month in sorted(targets):
        fresh, stored = recomputed.get(month), current.get(month)
        if fresh is None:
            if stored not in (None, EMPTY_INPUT_DIGEST):
                stale.append(month)
        elif stored != fresh:
            stale.append(month)
    return stale


def judge_name_intraday(
    inputs: _IntradayInputs,
    calendar: _SessionCalendar,
    end: datetime,
    min_slot_coverage: float,
    *,
    timings: dict[str, float] | None = None,
) -> list[_IntradayVerdict]:
    """The slot_coverage, digest_fresh, grid_parity and stray_vendor_rows verdicts of one name
    (coverage_cache needs the fetcher lock and is judged for all names at once). Pure."""

    def timed(check: str, started: float) -> None:
        if timings is not None:
            timings[check] = timings.get(check, 0.0) + (perf_counter() - started)

    verdicts: list[_IntradayVerdict] = []

    started = perf_counter()
    if inputs.stored_slots:
        first = min(inputs.stored_slots)
        sessions = calendar.between(first.date(), end.date())
        expected = session_slots(sessions, 5, first, end)
        answered = answered_slots(
            expected,
            set(inputs.stored_slots),
            inputs.answered,
            _FIVE_MINUTES,
            {day: close for day, (_open, close) in sessions.items()},
        )
        worst = min(slot_coverage_by_year(expected, answered).values(), default=1.0)
    else:
        worst = 0.0  # a name listed for its 5m rows with none stored has no history at all
    verdicts.append(
        _IntradayVerdict(
            GRID_SOURCE_TF, "slot_coverage", worst >= min_slot_coverage, worst, min_slot_coverage
        )
    )
    timed("slot_coverage", started)

    started = perf_counter()
    five = inputs.five
    if five.ts.size:
        derive_sessions = calendar.between(
            datetime.fromtimestamp(int(five.ts[0]), tz=UTC).date(),
            datetime.fromtimestamp(int(five.ts[-1]), tz=UTC).date(),
        )
    else:
        derive_sessions = {}
    recomputed, targets = intraday_month_digests(five, derive_sessions, inputs.scope)
    for tf in _INTRADAY_DIGEST_TFS:
        stale = stale_intraday_months(recomputed[tf], inputs.current_digests.get(tf, {}), targets)
        verdicts.append(_IntradayVerdict(tf, "digest_fresh", not stale, float(len(stale)), 0.0))
    timed("digest_fresh", started)

    started = perf_counter()
    for tf in sorted(GRID_TIMEFRAMES):
        archived = inputs.archive.get(tf, {})
        if not archived or not five.ts.size:
            # No archived vendor bucket to compare against: a pass that says nothing was measured.
            verdicts.append(_IntradayVerdict(tf, "grid_parity", True, None, 0.0))
            continue
        rebucketed = rebucket_5m(
            five.ts,
            five.open,
            five.high,
            five.low,
            five.close,
            five.volume,
            [int(stamp.timestamp()) for stamp in archived],
            timeframe=tf,
        )
        ours = {datetime.fromtimestamp(t, tz=UTC): values for t, values in rebucketed.items()}
        _compared, mismatched = grid_parity(ours, archived, timeframe=tf)
        verdicts.append(
            _IntradayVerdict(tf, "grid_parity", mismatched == 0, float(mismatched), 0.0)
        )
    timed("grid_parity", started)

    for tf in sorted(GRID_TIMEFRAMES):
        n = inputs.stray.get(tf, 0)
        verdicts.append(_IntradayVerdict(tf, "stray_vendor_rows", n == 0, float(n), 0.0))
    return verdicts


def coverage_cache_drift(
    dsn: str,
    symbols: Sequence[str],
    *,
    lock_factory: Any = FetcherLock,
    connect: Any = psycopg.connect,
    rebuild: Any = rebuild_from_stored_state,
) -> dict[str, int] | None:
    """Ledger series per symbol whose stored row differs from the rebuild, or None when the
    fetcher lock is held elsewhere (the check is skipped, never run unlocked).

    The rebuild's docstring requires the fetcher lock, so this takes it with the non-blocking
    try-lock, runs the rebuild inside a transaction that is always rolled back (the rebuilt
    rows are read before the rollback and nothing reaches the ledger), and releases the lock in
    a finally. last_fetched_at and consecutive_failures are the fetcher's own and are not
    compared. A ledger row for a series with no bars and no requests is untouched by the
    rebuild and so cannot show here.
    """
    lock = lock_factory(dsn, holder=_JOB)
    if not lock.acquire():
        return None
    try:
        conn = connect(dsn)
        try:
            with conn.cursor() as cur:
                cur.execute(_COVERAGE_ROWS_SQL, (list(symbols),))
                committed = {(r[0], r[1]): tuple(r[2:]) for r in cur.fetchall()}
                cur.execute(f"SET LOCAL ROLE {_WRITER_ROLE}")
                rebuild(cur, list(symbols))
                cur.execute(_COVERAGE_ROWS_SQL, (list(symbols),))
                rebuilt = {(r[0], r[1]): tuple(r[2:]) for r in cur.fetchall()}
        finally:
            conn.rollback()
            conn.close()
    finally:
        lock.release()
    drift: dict[str, int] = defaultdict(int)
    for key in committed.keys() | rebuilt.keys():
        if committed.get(key) != rebuilt.get(key):
            drift[key[0]] += 1
    return dict(drift)


class _IntradayRun(NamedTuple):
    """The intraday report of one audit run: the rows to write and the numbers the log reports."""

    facts: list[tuple[str, str | None, str, float | None, float | None, bool, Any]]
    failing_by_check: dict[str, int]
    passing_by_check: dict[str, int]
    timings: dict[str, float]
    n_names: int
    coverage_skipped: int
    full_sweep: bool
    n_without_archive: dict[str, int]
    parity_failing: list[str]


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
            apr = await load_apr_dict_async(conn, _APR_PATTERNS)
            params = _Params.from_apr(apr)
            window = _Window.build(now, params)
            compute = await self._universe(conn, dimension_where_clause("compute", "i"))
            compute_1d = await self._universe(conn, dimension_where_clause("compute_1d", "i"))
            active = await self._universe(conn, dimension_where_clause("backfill", "i"))
            previous_verdict_at = await conn.fetchval(_NEWEST_VERDICT_SQL, _MONITOR_TYPE_VERDICT)

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
            integ = _IntegrityParams.from_apr(apr)
            verdicts = await self._verdict_report_1d(
                conn, integ, window, compute_1d, checks["unexplained_seams"].result.samples, now
            )
            checks["untraced_quarantined_1d"] = verdicts.untraced_hidden

        await self._report(pool, window, params, checks, grid, vendor)
        async with pool.acquire() as conn:
            await self._write_verdicts(conn, verdicts, now)
        self._log_verdicts(verdicts)
        intraday = await self._intraday_report(
            pool, integ, window, now, already=len(verdicts.facts)
        )
        async with pool.acquire() as conn:
            refused = await conn.fetch(_REFUSED_LOADS_24H_SQL, now - timedelta(hours=24))
        record_alert_gauges(
            failing_by_check=merge_failing_by_check(
                verdicts.failing_by_check, intraday.failing_by_check
            ),
            previous_verdict_at=previous_verdict_at,
            run_start=now,
            max_age_hours=integ.report_max_age_hours,
            refused_by_source={r["source"]: r["n"] for r in refused},
        )

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

    # -- the 1d verdict report ----------------------------------------------------

    @staticmethod
    async def _verdict_report_1d(
        conn: Any,
        integ: _IntegrityParams,
        window: _Window,
        compute_1d: list[str],
        seam_samples: Iterable[str],
        run_start: datetime,
    ) -> _VerdictRun:
        """Judge every compute_1d name on the eight 1d checks (design section 6).

        Whole-corpus reads happen once (policy, lineage, answered-empty spans, latest loads);
        each name's observations, splits, stored rows, flags and digests are read, judged and
        dropped in turn, never as a corpus frame. A finding never raises.
        """
        policy_rows = _policy_rows(await conn.fetch(_SELECT_POLICY_1D_SQL))
        first_bar = await conn.fetchval(_FIRST_1D_BAR_SQL, list(CANONICAL_1D_SOURCES))
        sessions = sorted(nyse_sessions(first_bar.date(), window.last_session)) if first_bar else []

        missing: dict[str, list[date]] = defaultdict(list)
        hidden: dict[str, int] = defaultdict(int)
        for r in await conn.fetch(_LINEAGE_MISSING_SQL):
            if r["visible"]:
                missing[r["symbol"]].append(r["bar_date"])
            else:
                hidden[r["symbol"]] += 1
        spans: dict[str, list[tuple[date, date]]] = defaultdict(list)
        for r in await conn.fetch(_EMPTY_SESSIONS_SQL):
            spans[r["symbol"]].append((r["span_start"], r["span_end"]))
        latest_load = {r["symbol"]: r["loaded_at"] for r in await conn.fetch(_LATEST_1D_LOAD_SQL)}
        seams = findings_by_symbol(seam_samples)

        facts: list[tuple[str, str | None, str, float | None, float | None, bool, Any]] = []
        failing: dict[str, int] = defaultdict(int)
        passing: dict[str, int] = defaultdict(int)
        timings: dict[str, float] = {}
        n_runs = 0
        blocking_samples: list[str] = []
        twe = window.training_window_end
        for symbol in compute_1d:
            inputs = await BarReconciliationAudit._name_inputs_1d(
                conn,
                symbol,
                policy_rows=policy_rows,
                lineage_missing=missing.get(symbol, ()),
                empty_spans=spans.get(symbol, ()),
                seam_findings=seams.get(symbol, 0),
                latest_load_at=latest_load.get(symbol),
            )
            report = judge_name_1d(
                inputs, sessions, window.last_session, run_start, integ, timings=timings
            )
            subject = f"{symbol}|1d"
            for v in report.verdicts:
                facts.append(
                    (
                        _MONITOR_TYPE_VERDICT,
                        subject,
                        v.check,
                        v.metric_value,
                        v.threshold_value,
                        v.passed,
                        twe,
                    )
                )
                (passing if v.passed else failing)[v.check] += 1
            facts.append(
                (
                    _MONITOR_TYPE_VERDICT,
                    subject,
                    INFO_REFUSED_HEAD,
                    float(report.refused_head),
                    None,
                    True,
                    twe,
                )
            )
            n_runs += len(report.basis_runs)
            blocking_samples.extend(
                f"{symbol}|{run.start}..{run.end}|{run.continuous_vendor}"
                for run in report.blocking_runs
            )
        n_hidden = sum(hidden.values())
        untraced = _Judged(
            CheckResult(n_hidden, tuple(f"{s}={n}" for s, n in sorted(hidden.items()))),
            n_hidden,
        )
        return _VerdictRun(
            facts,
            dict(failing),
            dict(passing),
            timings,
            untraced,
            len(compute_1d),
            n_runs,
            blocking_samples,
        )

    @staticmethod
    async def _name_inputs_1d(
        conn: Any,
        symbol: str,
        *,
        policy_rows: list[PolicyRow],
        lineage_missing: Iterable[date],
        empty_spans: Iterable[tuple[date, date]],
        seam_findings: int,
        latest_load_at: datetime | None,
    ) -> NameInputs1d:
        digests = {
            r["range_start"]: (r["digest"], r["rule_version"])
            for r in await conn.fetch(_SELECT_CURRENT_1D_DIGESTS_SQL, symbol)
        }
        return NameInputs1d(
            symbol=symbol,
            observations=_observations(
                await conn.fetch(_SELECT_DAILY_OBSERVATIONS_SQL, symbol, list(_D2V2_ROUTES))
            ),
            policy_rows=policy_rows,
            splits=_splits(await conn.fetch(_SELECT_DAILY_SPLITS_SQL, symbol)),
            stored=[
                StoredBar(
                    r["timestamp"],
                    r["open"],
                    r["high"],
                    r["low"],
                    r["close"],
                    r["volume"],
                    r["source"],
                )
                for r in await conn.fetch(_SELECT_STORED_1D_SQL, symbol, list(CANONICAL_1D_SOURCES))
            ],
            flags=[
                (r["timestamp"], r["rule"], r["quarantine"])
                for r in await conn.fetch(_SELECT_1D_FLAG_RULES_SQL, symbol)
            ],
            current_digests=digests,
            lineage_missing_dates=list(lineage_missing),
            empty_spans=list(empty_spans),
            seam_findings=seam_findings,
            latest_load_at=latest_load_at,
        )

    @staticmethod
    async def _write_verdicts(
        conn: Any, run: _VerdictRun | _IntradayRun, run_start: datetime, *, already: int = 0
    ) -> None:
        """Write the verdict rows in groups of names, then confirm every row landed.

        `already` is the number of verdict rows this run wrote earlier (the 1d report), so the
        read-back of a second write counts both.

        integrity_monitor's writer swallows an insert failure into a warning, so the count is
        read back: a short write raises (a silent gap in the report would read as a missing
        verdict, which the gates treat as failing, but the cause must be loud).
        """
        per_group = _VERDICT_GROUP_NAMES * (len(CHECKS_1D) + 1)
        for i in range(0, len(run.facts), per_group):
            await emit_integrity_facts_async(conn, run.facts[i : i + per_group])
        written = await conn.fetchval(
            "SELECT count(*) FROM integrity_monitor WHERE monitor_type = $1 AND evaluated_at >= $2",
            _MONITOR_TYPE_VERDICT,
            run_start,
        )
        if written < already + len(run.facts):
            raise RuntimeError(
                f"bar_integrity verdicts: wrote {written} of {already + len(run.facts)} rows"
            )

    # -- intraday verdicts (plan 185-40) -----------------------------------------

    async def _intraday_report(
        self,
        pool: asyncpg.Pool,
        integ: _IntegrityParams,
        window: _Window,
        run_start: datetime,
        *,
        already: int,
    ) -> _IntradayRun:
        async with pool.acquire() as conn:
            run = await self._verdict_report_intraday(
                conn,
                integ,
                window,
                run_start,
                coverage_drift=lambda names: asyncio.to_thread(
                    coverage_cache_drift, self._db_dsn, names
                ),
            )
        async with pool.acquire() as conn:
            await self._write_verdicts(conn, run, run_start, already=already)
        self._log_intraday(run)
        return run

    @staticmethod
    async def _verdict_report_intraday(
        conn: Any,
        integ: _IntegrityParams,
        window: _Window,
        run_start: datetime,
        *,
        coverage_drift: Any,
    ) -> _IntradayRun:
        """Judge every name holding 5m bars on the intraday checks (design section 6), then the
        coverage ledger of all of them under the fetcher lock. A finding never raises."""
        names = [r["symbol"] for r in await conn.fetch(_INTRADAY_NAMES_SQL)]
        previous = {
            r["subject"]: (r["passed"], r["evaluated_at"])
            for r in await conn.fetch(
                _PREVIOUS_DIGEST_VERDICT_SQL, _MONITOR_TYPE_VERDICT, "digest_fresh"
            )
        }
        last_sweep = await conn.fetchval(
            _LATEST_SWEEP_SQL, _MONITOR_TYPE_VERDICT, INFO_DIGEST_FULL_SWEEP
        )
        full_sweep = last_sweep is None or run_start - last_sweep >= timedelta(
            days=integ.intraday_full_sweep_days
        )
        loads: dict[str, list[tuple[datetime, date | None, date | None]]] = defaultdict(list)
        if not full_sweep and previous:
            since = min(at for _, at in previous.values())
            for r in await conn.fetch(_CHANGING_LOADS_SQL, list(_INTRADAY_DIGEST_TFS), since):
                loads[r["symbol"]].append((r["loaded_at"], r["first_bar"], r["last_bar"]))
        stray: dict[str, dict[str, int]] = defaultdict(dict)
        for r in await conn.fetch(
            _STRAY_VENDOR_SQL, sorted(GRID_TIMEFRAMES), SOURCE_DERIVED_5M, names
        ):
            stray[r["symbol"]][r["timeframe"]] = r["n"]

        calendar = _SessionCalendar(window.last_session)
        twe = window.training_window_end
        facts: list[tuple[str, str | None, str, float | None, float | None, bool, Any]] = []
        failing: dict[str, int] = defaultdict(int)
        passing: dict[str, int] = defaultdict(int)
        timings: dict[str, float] = {}
        without_archive: dict[str, int] = defaultdict(int)
        parity_failing: list[str] = []

        def record(symbol: str, v: _IntradayVerdict) -> None:
            facts.append(
                (
                    _MONITOR_TYPE_VERDICT,
                    f"{symbol}|{v.timeframe}",
                    v.check,
                    v.metric,
                    v.threshold,
                    v.passed,
                    twe,
                )
            )
            (passing if v.passed else failing)[v.check] += 1

        for symbol in names:
            before, at = previous.get(f"{symbol}|{GRID_SOURCE_TF}", (None, None))
            inputs = await BarReconciliationAudit._intraday_inputs(
                conn,
                symbol,
                scope=digest_scope(
                    full_sweep=full_sweep,
                    previous_at=at,
                    previous_passed=before,
                    loads=loads.get(symbol, ()),
                ),
                stray=stray.get(symbol, {}),
            )
            for v in judge_name_intraday(
                inputs, calendar, window.end, integ.slot_coverage_min_intraday, timings=timings
            ):
                record(symbol, v)
                if v.check == "grid_parity":
                    if v.metric is None:
                        without_archive[v.timeframe] += 1
                    elif not v.passed:
                        parity_failing.append(f"{symbol}|{v.timeframe}|mismatched={int(v.metric)}")

        skipped = 0
        started = perf_counter()
        drift = await coverage_drift(names) if names else {}
        timings["coverage_cache"] = perf_counter() - started
        if drift is None:
            skipped = len(names)
        else:
            for symbol in names:
                record(
                    symbol,
                    _IntradayVerdict(
                        GRID_SOURCE_TF,
                        "coverage_cache",
                        not drift.get(symbol),
                        float(drift.get(symbol, 0)),
                        0.0,
                    ),
                )
        if full_sweep:
            facts.append(
                (
                    _MONITOR_TYPE_VERDICT,
                    SWEEP_SUBJECT,
                    INFO_DIGEST_FULL_SWEEP,
                    float(len(names)),
                    None,
                    True,
                    twe,
                )
            )
        return _IntradayRun(
            facts,
            dict(failing),
            dict(passing),
            timings,
            len(names),
            skipped,
            full_sweep,
            dict(without_archive),
            parity_failing,
        )

    @staticmethod
    async def _intraday_inputs(
        conn: Any, symbol: str, *, scope: frozenset[datetime] | None, stray: Mapping[str, int]
    ) -> _IntradayInputs:
        five = _FiveMinute.from_rows(
            await conn.fetch(_SELECT_5M_SQL, symbol), await conn.fetch(_SELECT_5M_FLAGS_SQL, symbol)
        )
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
        archive: dict[str, dict[datetime, Values]] = defaultdict(dict)
        for r in await conn.fetch(_ARCHIVE_ROWS_SQL, symbol, sorted(GRID_TIMEFRAMES)):
            archive[r["timeframe"]][r["timestamp"]] = (
                r["open"],
                r["high"],
                r["low"],
                r["close"],
                r["volume"],
            )
        digests: dict[str, dict[datetime, str]] = defaultdict(dict)
        for r in await conn.fetch(
            _SELECT_CURRENT_GRID_DIGESTS_SQL, symbol, list(_INTRADAY_DIGEST_TFS)
        ):
            digests[r["timeframe"]][r["range_start"]] = r["digest"]
        return _IntradayInputs(
            symbol=symbol,
            five=five,
            stored_slots=[
                r["timestamp"]
                for r in await conn.fetch(_RAW_5M_SLOTS_SQL, symbol, SOURCE_SYNTHETIC_FILL)
            ],
            answered=answered,
            archive=archive,
            current_digests=digests,
            scope=scope,
            stray=stray,
        )

    @staticmethod
    def _log_intraday(run: _IntradayRun) -> None:
        """Per-check pass and fail name counts, the skip count and the timings."""
        for check in CHECKS_INTRADAY:
            FINDINGS_TOTAL.add(
                run.failing_by_check.get(check, 0), {"check": f"bar_integrity_intraday_{check}"}
            )
        logger.info(
            "bar_integrity.report_intraday",
            n_names=run.n_names,
            full_sweep=run.full_sweep,
            failing_by_check=run.failing_by_check,
            passing_by_check=run.passing_by_check,
            coverage_cache_skipped=run.coverage_skipped,
            grid_parity_without_archive=run.n_without_archive,
            seconds_by_check={k: round(v, 1) for k, v in run.timings.items()},
        )
        if run.parity_failing:
            logger.error("bar_integrity.grid_parity_mismatches", names=run.parity_failing)
        print("\n# Intraday verdict report (bar_integrity)\n")
        print(f"{'check':<20} {'pass':>7} {'fail':>7} {'seconds':>9}")
        for check in CHECKS_INTRADAY:
            print(
                f"{check:<20} {run.passing_by_check.get(check, 0):>7} "
                f"{run.failing_by_check.get(check, 0):>7} {run.timings.get(check, 0.0):>9.1f}"
            )
        print(
            f"names {run.n_names}; full digest sweep {run.full_sweep}; "
            f"coverage_cache skipped (fetcher lock held) {run.coverage_skipped}"
        )

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
            if n and name not in _INFORMATIONAL_CHECKS:
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
                n == 0 or name in _INFORMATIONAL_CHECKS,
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
    def _log_verdicts(run: _VerdictRun) -> None:
        """The report's per-check pass and fail name counts, its timings and the blocking runs."""
        for check in CHECKS_1D:
            FINDINGS_TOTAL.add(
                run.failing_by_check.get(check, 0), {"check": f"bar_integrity_{check}"}
            )
        logger.info(
            "bar_integrity.report_1d",
            n_names=run.n_names,
            failing_by_check=run.failing_by_check,
            passing_by_check=run.passing_by_check,
            seconds_by_check={k: round(v, 1) for k, v in run.timings.items()},
            n_basis_runs=run.n_basis_runs,
        )
        if run.blocking_samples:
            logger.error("bar_integrity.blocking_basis_runs", runs=run.blocking_samples)
        print("\n# 1d verdict report (bar_integrity)\n")
        print(f"{'check':<22} {'pass':>7} {'fail':>7} {'seconds':>9}")
        for check in CHECKS_1D:
            print(
                f"{check:<22} {run.passing_by_check.get(check, 0):>7} "
                f"{run.failing_by_check.get(check, 0):>7} {run.timings.get(check, 0.0):>9.1f}"
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
