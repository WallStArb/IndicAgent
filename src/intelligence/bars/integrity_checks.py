"""Pure arithmetic of the 1d integrity verdict report (phase 185 plan 33; data layer integrity
design section 6). D7 (services/bar_reconciliation_audit.py) reads the inputs and writes the
verdicts; nothing here touches a database or the APR.
"""

from __future__ import annotations

import statistics
import time
from bisect import bisect_left
from collections import defaultdict
from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Protocol

import numpy as np

from src.intelligence.bars.daily_rule import (
    FALLBACK_PAIR,
    PRIMARY_PAIR,
    ROUTE_LEGACY,
    ROUTE_SMART,
    RULE_VERSION,
    VENDOR_ALPACA,
    VENDOR_IBKR,
    PolicyRow,
    alpaca_era_start,
    derive_daily_v2,
    primary_pair,
    resolve_policy,
    servable_primary_dates,
    vendor_basis_closes,
)
from src.intelligence.bars.derivation import Observation, SplitRecord
from src.intelligence.bars.digest import bar_content_digest, month_ranges
from src.intelligence.bars.gap_plan import AnsweredWindows
from src.intelligence.bars.sources import ROUTE_ALPACA
from src.intelligence.bars.vendor_arbitration import ARBITRATED_THROUGH
from src.intelligence.bars.vendor_basis import BasisRun, find_basis_runs
from src.intelligence.bars.write_contract import BarValues, classify


@dataclass(frozen=True)
class Verdict:
    """One integrity verdict row: a (symbol, timeframe, check) judged against its threshold."""

    symbol: str
    timeframe: str
    check: str
    passed: bool
    metric_value: float
    threshold_value: float


def session_coverage(
    bar_dates: Collection[date], empty_dates: Collection[date], sessions: Collection[date]
) -> float:
    """Share of sessions that hold a bar or an answered-empty record; 1.0 when there are none."""
    if not sessions:
        return 1.0
    answered = set(bar_dates) | set(empty_dates)
    return len(answered.intersection(sessions)) / len(sessions)


# The vendor whose raw rows an observation's route stands for (the vendor of a request is its
# `source`).
_ROUTE_VENDOR: Mapping[str, str] = {
    ROUTE_SMART: VENDOR_IBKR,
    ROUTE_LEGACY: VENDOR_IBKR,
    ROUTE_ALPACA: VENDOR_ALPACA,
}


def answered_window_spans(
    windows: Iterable[tuple[str, datetime, datetime]], observations: Iterable[Observation]
) -> list[tuple[date, date]]:
    """Date spans a successful canonical-vendor 1d answer covers (the vendor's "no trade that
    day"), from `windows` of (vendor, window_start, window_end): the windows of requests with
    outcome `bars` and the ranges of applied raw loads (gap_plan.DAILY_ANSWER_*).

    A session inside such a window with no bar is an answer, but only where the window is
    corroborated by the vendor's own raw bars on both sides of it: the span runs from the
    vendor's first raw bar to its last inside the window. A window holding none of the
    vendor's bars is a failed or lost insert and answers nothing, and the days before the first
    or after the last bar (a pre-listing head, a stale tail) stay unanswered.

    A day lies in the window when any part of it does; the window end is exclusive (measured
    2026-10-29: of 147 IBKR 1d requests whose raw rows are linked, none holds a bar on or after
    its window_end date), so a midnight end excludes its own date and a mid-day end (an Alpaca
    nightly) includes it. IBKR's window_start can sit after its first bar (22 of the 147); the
    load range of the same answer starts at that bar and covers the head.
    """
    bar_dates: dict[str, list[date]] = defaultdict(list)
    for observation in observations:
        vendor = _ROUTE_VENDOR.get(observation.route)
        if vendor is not None:
            bar_dates[vendor].append(observation.bar_date)
    for dates in bar_dates.values():
        dates.sort()
    spans: list[tuple[date, date]] = []
    for vendor, window_start, window_end in windows:
        dates = bar_dates.get(vendor)
        if not dates:
            continue
        first_day = window_start.astimezone(UTC).date()
        # exclusive end day: a midnight end is its own date, any later time takes that day in
        end_day = (window_end.astimezone(UTC) - timedelta(microseconds=1)).date() + timedelta(
            days=1
        )
        low = bisect_left(dates, first_day)
        high = bisect_left(dates, end_day)
        if high > low:
            spans.append((dates[low], dates[high - 1]))
    return spans


def no_trade_sessions(
    sessions: Sequence[date],
    stored_volumes: Mapping[date, float | None],
    window_spans: Sequence[tuple[date, date]],
    served: Collection[date],
    partial: Collection[date],
    *,
    run_max_sessions: int,
    neighbor_window_sessions: int,
    neighbor_median_volume_max_shares: float,
) -> set[date]:
    """Sessions a corroborated vendor window honestly answers as "no trade that day".

    A candidate is a judged session with no stored bar that lies in `window_spans`
    (answered_window_spans), that the vendor served no raw bar on (`served`; a served session with
    no stored bar is a derivation gap) and that no incomplete bar covers (`partial`: an Alpaca
    request that returned the day as a partial bar did not answer it). A candidate counts as
    answered only when both hold, because a vendor history hole looks identical to a no-trade day
    inside a window and only a thin name can have had no trades:

    - the run of consecutive judged sessions with no stored bar that contains it is at most
      `run_max_sessions` long (a multi-week hole is a hole, not a quiet spell);
    - the median volume of the `neighbor_window_sessions` nearest stored bars on each side of the
      run is at most `neighbor_median_volume_max_shares` (a liquid name trades every session).

    A run with no neighbouring volume at all is not answered. Thresholds are APR values passed in
    (threshold.bar_integrity.no_trade_*); the rule holds no literal.
    """
    candidates = {
        s
        for s in sessions
        if s not in stored_volumes
        and s not in served
        and s not in partial
        and _in_any(s, window_spans)
    }
    if not candidates:
        return set()
    answered: set[date] = set()
    count = len(sessions)
    start = 0
    while start < count:
        if sessions[start] in stored_volumes:
            start += 1
            continue
        end = start
        while end < count and sessions[end] not in stored_volumes:
            end += 1
        run = sessions[start:end]
        if len(run) <= run_max_sessions and any(s in candidates for s in run):
            neighbours = _neighbour_volumes(
                sessions, stored_volumes, start, end, neighbor_window_sessions
            )
            if neighbours and statistics.median(neighbours) <= neighbor_median_volume_max_shares:
                answered.update(s for s in run if s in candidates)
        start = end
    return answered


def _neighbour_volumes(
    sessions: Sequence[date],
    stored_volumes: Mapping[date, float | None],
    start: int,
    end: int,
    per_side: int,
) -> list[float]:
    """Volumes of the `per_side` nearest stored bars before `sessions[start]` and from
    `sessions[end]` on (a missing volume is skipped)."""
    volumes: list[float] = []
    for indexes in (range(start - 1, -1, -1), range(end, len(sessions))):
        taken = 0
        for i in indexes:
            if taken >= per_side:
                break
            if sessions[i] not in stored_volumes:
                continue
            volume = stored_volumes[sessions[i]]
            taken += 1
            if volume is not None:
                volumes.append(float(volume))
    return volumes


def alpaca_basis_runs(
    observations: Sequence[Observation],
    splits: Sequence[SplitRecord],
    policy_rows: Sequence[PolicyRow],
    *,
    symbol: str,
    since: date,
    tolerance_bp: float,
    min_sessions: int,
) -> list[BasisRun]:
    """Runs of at least min_sessions sessions after `since` where IBKR's and Alpaca's 1d closes
    (current scale, session dates, zero-volume Alpaca bars dropped) differ by more than
    tolerance_bp, and nothing recorded explains them (todo 545 step 5a; the successor of the
    retired Tradier-against-IBKR vendor_basis_run check). Such a run is a spin-off, split or
    ticker event since the D-191-Q arbitration. Explained, and not reported: a corporate action whose effective date
    falls inside the run or on the first common session after it (the event that ends it; a
    recorded spin-off factor is the judge), or an IBKR symbol row covering
    the whole run."""
    closes = vendor_basis_closes(observations, splits)
    alpaca, ibkr = closes["alpaca"], closes["ibkr"]
    pairs = [(d, ibkr[d], alpaca[d]) for d in sorted(ibkr.keys() & alpaca.keys()) if d > since]
    common = [d for d, _i, _a in pairs]

    def explained(run: BasisRun) -> bool:
        after = next((d for d in common if d > run.end), None)
        if any(
            run.start <= s.effective_date and (after is None or s.effective_date <= after)
            for s in splits
        ):
            return True
        return any(
            r.timeframe == TIMEFRAME_1D
            and r.symbol == symbol
            and r.primary_source == "ibkr"
            and r.valid_from <= run.start
            and (r.valid_to is None or r.valid_to > run.end)
            for r in policy_rows
        )

    runs = find_basis_runs(pairs, tolerance_bp=tolerance_bp, min_sessions=min_sessions)
    return [run for run in runs if not explained(run)]


def policy_conformance(
    rows: Sequence[tuple[date, str, str]],
    policy_rows: Sequence[PolicyRow],
    primary_dates: Mapping[str, Collection[date]],
    *,
    symbol: str,
) -> list[date]:
    """Dates of (date, vendor, kind) rows whose identity contradicts the policy open on that date.

    The pair must be the policy primary's; (ibkr, fallback) is accepted only under a policy
    that names IBKR as fallback, on a date the primary cannot serve on the current scale
    (primary_dates[primary], daily_rule.servable_primary_dates: a hole, a head, a date answered
    only on a stale scale, d2-v3; for Alpaca also a zero-volume or pre-listing date, d2-v4).
    """
    bad: list[date] = []
    era_start = alpaca_era_start(policy_rows)
    for bar_date, vendor, kind in rows:
        policy = resolve_policy(policy_rows, symbol, bar_date)
        if policy.primary_source in PRIMARY_PAIR and (vendor, kind) == primary_pair(
            policy.primary_source, bar_date, era_start
        ):
            continue
        if (
            (vendor, kind) == FALLBACK_PAIR
            and policy.fallback_source == "ibkr"
            and bar_date not in primary_dates.get(policy.primary_source, ())
        ):
            continue
        bad.append(bar_date)
    return sorted(bad)


# ---------------------------------------------------------------------------
# The per-name 1d verdict report (plan 185-33 Task 2)
# ---------------------------------------------------------------------------

TIMEFRAME_1D = "1d"
# Gates the phase 186 rebuild only (verdict_gate.REBUILD_ONLY_CHECKS), never promotion (185-46).
CHECK_FRESHNESS_1D = "freshness_1d"
# The checks one 1d name is judged on, in report order. Identifiers, not tunables.
CHECKS_1D = (
    "session_coverage",
    "policy_conformance",
    "lineage_missing",
    "canonical_recompute",
    "digest_fresh",
    "unexplained_seam",
    "alpaca_basis_run",
    "report_age",
    CHECK_FRESHNESS_1D,
)
# Reported per name, never a verdict that can fail (the name's history starts at its first
# primary bar; the count is what the report shows).
INFO_REFUSED_HEAD = "refused_head_1d"
# Reported per name, never a gate check (plan 185-51): fails while the name is held
# (bar_hold_current); the metric is the number of open holds.
INFO_HELD = "held_1d"


class IntegrityThresholds(Protocol):
    """The APR-sourced thresholds the 1d report reads (D7's _IntegrityParams satisfies it)."""

    session_coverage_min: float
    vendor_run_min_sessions: int
    report_max_age_hours: int
    basis_window_sessions: int
    basis_tolerance_bp: float
    freshness_max_lag_sessions_1d: int
    no_trade_run_max_sessions: int
    no_trade_neighbor_window_sessions: int
    no_trade_neighbor_median_volume_max_shares: float


@dataclass(frozen=True)
class StoredBar:
    """One stored canonical 1d row (market_data_ohlcv, a CANONICAL_1D_SOURCES pair)."""

    timestamp: datetime
    open: float | None
    high: float | None
    low: float | None
    close: float | None
    volume: float | None
    vendor: str
    kind: str


@dataclass(frozen=True)
class NameInputs1d:
    """Everything the 1d report reads for one name; the loader fills it, the judge only reads."""

    symbol: str
    observations: Sequence[Observation]
    policy_rows: Sequence[PolicyRow]
    splits: Sequence[SplitRecord]
    stored: Sequence[StoredBar]
    # (timestamp, rule, quarantine) of the name's 1d bar_quality_flag rows
    flags: Sequence[tuple[datetime, str, bool]]
    # current digest per month start: range_start -> (digest, rule_version)
    current_digests: Mapping[datetime, tuple[str, str]]
    # visible 1d bars whose canonical_bar_lineage row has no request ids
    lineage_missing_dates: Collection[date]
    # [start, end] date spans the name's answered-empty records cover
    empty_spans: Sequence[tuple[date, date]]
    # (vendor, window_start, window_end) of the name's successful canonical-vendor 1d answers:
    # request windows and applied raw load ranges
    answered_windows: Sequence[tuple[str, datetime, datetime]]
    # dates an answered request served as an incomplete bar (ohlcv_request.partial_bars): never
    # an answer to "no trade that day"
    partial_dates: Collection[date]
    # unexplained_seam findings D7's existing rule found for this name
    seam_findings: int
    latest_load_at: datetime | None
    # the name's recorded last session (listing_end_current, todo 519); None while listed
    listing_end: date | None = None


@dataclass(frozen=True)
class NameReport1d:
    verdicts: list[Verdict]
    refused_head: int
    # unexplained Alpaca/IBKR runs after the arbitration (alpaca_basis_run)
    alpaca_runs: list[BasisRun] = field(default_factory=list)


def month_digests(
    stored: Sequence[StoredBar], flags: Sequence[tuple[datetime, str, bool]]
) -> dict[datetime, str]:
    """range_start -> digest of every calendar month the stored bars span, empty months included.

    The same recipe as services/bar_derivation.write_1d_digests: each row carries the rules of
    its non-quarantine flags, rows sort by timestamp, months run first to last bar.
    """
    if not stored:
        return {}
    rules: dict[int, set[str]] = {}
    for stamp, rule, quarantine in flags:
        if not quarantine:
            rules.setdefault(int(stamp.timestamp()), set()).add(rule)
    ordered = sorted(stored, key=lambda b: b.timestamp)
    ts = np.array([int(b.timestamp.timestamp()) for b in ordered], dtype=np.int64)
    columns = {
        name: np.array([getattr(b, name) for b in ordered], dtype=np.float64)
        for name in ("open", "high", "low", "close", "volume")
    }
    per_row = [tuple(sorted(rules.get(int(t), ()))) for t in ts]
    out: dict[datetime, str] = {}
    for start, end in month_ranges(ts):
        mask = (ts >= int(start.timestamp())) & (ts < int(end.timestamp()))
        out[start] = bar_content_digest(
            ts[mask],
            columns["open"][mask],
            columns["high"][mask],
            columns["low"][mask],
            columns["close"][mask],
            columns["volume"][mask],
            [per_row[i] for i in np.flatnonzero(mask)],
        )
    return out


def stale_digest_months(
    recomputed: Mapping[datetime, str], current: Mapping[datetime, tuple[str, str]]
) -> list[datetime]:
    """Months whose current digest is missing, differs from the recompute, or has another rule
    version than daily_rule.RULE_VERSION."""
    return [
        start
        for start, digest in sorted(recomputed.items())
        if current.get(start, (None, None)) != (digest, RULE_VERSION)
    ]


def recompute_findings(
    derived: Mapping[date, BarValues], stored: Mapping[date, BarValues]
) -> list[date]:
    """Dates where the rule's bar and the stored bar differ in any field, or only one exists."""
    delta = classify(derived, stored, removal_scope=stored.keys())
    return sorted(set(delta.new) | set(delta.changed) | set(delta.removed))


def _in_any(day: date, spans: Sequence[tuple[date, date]]) -> bool:
    return any(start <= day <= end for start, end in spans)


def freshness_1d(
    latest_bar: date | None,
    answered_empty: Sequence[tuple[date, date]],
    last_session: date,
    sessions: Sequence[date],
    max_lag: int,
    *,
    symbol: str,
    listing_end: date | None = None,
) -> Verdict:
    """Is the name's canonical 1d series current? The metric is the number of NYSE sessions after
    the latest canonical bar, up to `last_session` (the last completed session), that no
    answered-empty span covers; it passes while that number is at most `max_lag`. `sessions`
    holds trading dates only, so a Friday bar judged on the weekend is 0 behind. A name with no
    bar fails, counting every uncovered session up to `last_session`. A name whose listing ended
    (todo 519) is judged up to its recorded last session, never past it."""
    judged_to = last_session if listing_end is None else min(last_session, listing_end)
    behind = sum(
        1
        for s in sessions
        if (latest_bar is None or s > latest_bar)
        and s <= judged_to
        and not _in_any(s, answered_empty)
    )
    passed = latest_bar is not None and behind <= max_lag
    return Verdict(symbol, TIMEFRAME_1D, CHECK_FRESHNESS_1D, passed, float(behind), float(max_lag))


def judge_name_1d(
    inputs: NameInputs1d,
    sessions: Sequence[date],
    last_session: date,
    run_start: datetime,
    thresholds: IntegrityThresholds,
    *,
    timings: dict[str, float] | None = None,
) -> NameReport1d:
    """The nine 1d verdicts of one name (design section 6; freshness_1d from 185-46). Pure; timings, when given, collects
    seconds per check. Thresholds that are definitions (zero tolerance) live here as 0.0."""
    symbol = inputs.symbol

    def timed(check: str, started: float) -> None:
        if timings is not None:
            timings[check] = timings.get(check, 0.0) + (time.perf_counter() - started)

    stored: dict[date, BarValues] = {
        b.timestamp.date(): BarValues(b.open, b.high, b.low, b.close, b.volume, b.vendor, b.kind)
        for b in inputs.stored
    }

    def verdict(check: str, passed: bool, metric: float, threshold: float) -> Verdict:
        return Verdict(symbol, TIMEFRAME_1D, check, passed, float(metric), float(threshold))

    verdicts: list[Verdict] = []

    started = time.perf_counter()
    if stored:
        first = min(stored)
        judged_sessions = [s for s in sessions if first <= s <= last_session]
        # A vendor answer says "no trade" only for a session it served no bar on: a session with a
        # raw observation but no stored bar is a derivation gap, never an answer.
        served = {o.bar_date for o in inputs.observations}
        no_trade = no_trade_sessions(
            judged_sessions,
            {d: values.volume for d, values in stored.items()},
            answered_window_spans(inputs.answered_windows, inputs.observations),
            served,
            inputs.partial_dates,
            run_max_sessions=thresholds.no_trade_run_max_sessions,
            neighbor_window_sessions=thresholds.no_trade_neighbor_window_sessions,
            neighbor_median_volume_max_shares=thresholds.no_trade_neighbor_median_volume_max_shares,
        )
        coverage = session_coverage(
            stored.keys(),
            [s for s in judged_sessions if s in no_trade or _in_any(s, inputs.empty_spans)],
            judged_sessions,
        )
    else:
        coverage = 0.0  # a compute_1d name with no stored bar has no history at all
    verdicts.append(
        verdict(
            "session_coverage",
            coverage >= thresholds.session_coverage_min,
            coverage,
            thresholds.session_coverage_min,
        )
    )
    timed("session_coverage", started)

    started = time.perf_counter()
    contradicted = policy_conformance(
        [(d, values.vendor, values.kind) for d, values in stored.items()],
        inputs.policy_rows,
        servable_primary_dates(inputs.observations, inputs.splits),
        symbol=symbol,
    )
    verdicts.append(verdict("policy_conformance", not contradicted, len(contradicted), 0.0))
    timed("policy_conformance", started)

    verdicts.append(
        verdict(
            "lineage_missing",
            not inputs.lineage_missing_dates,
            len(inputs.lineage_missing_dates),
            0.0,
        )
    )

    started = time.perf_counter()
    derived = derive_daily_v2(
        inputs.observations,
        inputs.policy_rows,
        inputs.splits,
        symbol=symbol,
        basis_window_sessions=thresholds.basis_window_sessions,
        basis_tolerance_bp=thresholds.basis_tolerance_bp,
    )
    incoming = {
        b.bar_date: BarValues(b.open, b.high, b.low, b.close, b.volume, b.vendor, b.kind)
        for b in derived.bars
    }
    drifted = recompute_findings(incoming, stored)
    verdicts.append(verdict("canonical_recompute", not drifted, len(drifted), 0.0))
    timed("canonical_recompute", started)

    started = time.perf_counter()
    stale = stale_digest_months(month_digests(inputs.stored, inputs.flags), inputs.current_digests)
    verdicts.append(verdict("digest_fresh", not stale, len(stale), 0.0))
    timed("digest_fresh", started)

    verdicts.append(
        verdict("unexplained_seam", inputs.seam_findings == 0, inputs.seam_findings, 0.0)
    )

    started = time.perf_counter()
    alpaca_runs = alpaca_basis_runs(
        inputs.observations,
        inputs.splits,
        inputs.policy_rows,
        symbol=symbol,
        since=ARBITRATED_THROUGH,
        tolerance_bp=thresholds.basis_tolerance_bp,
        min_sessions=thresholds.vendor_run_min_sessions,
    )
    verdicts.append(verdict("alpaca_basis_run", not alpaca_runs, len(alpaca_runs), 0.0))
    timed("alpaca_basis_run", started)

    age_hours = (
        0.0
        if inputs.latest_load_at is None
        else (run_start - inputs.latest_load_at).total_seconds() / 3600.0
    )
    verdicts.append(
        verdict(
            "report_age",
            inputs.latest_load_at is None or inputs.latest_load_at <= run_start,
            age_hours,
            thresholds.report_max_age_hours,
        )
    )
    verdicts.append(
        freshness_1d(
            max(stored) if stored else None,
            inputs.empty_spans,
            last_session,
            sessions,
            thresholds.freshness_max_lag_sessions_1d,
            symbol=symbol,
            listing_end=inputs.listing_end,
        )
    )
    return NameReport1d(verdicts, len(derived.refused_head), alpaca_runs)


# ---------------------------------------------------------------------------
# The intraday checks (plan 185-40; design sections 5 and 6)
# ---------------------------------------------------------------------------

TIMEFRAME_5M = "5m"
# Checks one name with 5m bars is judged on, in report order (identifiers, not tunables).
CHECKS_INTRADAY = (
    "slot_coverage",
    "digest_fresh",
    "grid_parity",
    "stray_vendor_rows",
    "coverage_cache",
)
# Written when a run recomputed every digest month of every name, so the next run can tell when
# the last full sweep happened. Informational: it never fails.
INFO_DIGEST_FULL_SWEEP = "digest_full_sweep"
SWEEP_SUBJECT = "intraday|sweep"

_FIVE_MINUTES = 300
_BUCKET_SECONDS = {"15m": 900, "1h": 3600}
Values = tuple[float, float, float, float, float]


def answered_slots(
    expected: Iterable[datetime],
    stored: Collection[datetime],
    answered: AnsweredWindows,
    interval: timedelta,
    session_closes: Mapping[date, datetime],
) -> set[datetime]:
    """Expected slots that hold an answer: a stored bar (real or zero-volume provider bar, never
    a placeholder: the caller passes those out) or a slot wholly inside an answered window.

    A slot ends at its session's close when that comes first (a half-day's last slot).
    """
    stored_set = set(stored)
    out: set[datetime] = set()
    for slot in expected:
        close = session_closes.get(slot.date())
        length = interval if close is None else min(interval, close - slot)
        if slot in stored_set or answered.covers(slot, length):
            out.add(slot)
    return out


def slot_coverage_by_year(
    slots_expected: Iterable[datetime], slots_answered: Collection[datetime]
) -> dict[int, float]:
    """Per calendar year, the share of expected slots that are answered; years without expected
    slots are absent. An answered slot outside the expected set never inflates a year."""
    expected: dict[int, int] = defaultdict(int)
    done: dict[int, int] = defaultdict(int)
    for slot in slots_expected:
        expected[slot.year] += 1
        if slot in slots_answered:
            done[slot.year] += 1
    return {year: done[year] / n for year, n in sorted(expected.items())}


def grid_parity(
    derived: Mapping[datetime, Values],
    archived: Mapping[datetime, Values],
    *,
    timeframe: str,
) -> tuple[int, int]:
    """(n_compared, n_mismatched) over the buckets both sides hold, on the archive's keys.

    15m must match exactly on every shared bucket. 1h is compared on shared buckets only (the
    vendor's 1h grid lacks the 09:30 half hour on 39 of 231 measured names); a bucket one side
    lacks is never counted either way. Values are (open, high, low, close, volume), exact.

    The caller decides which derived buckets are like-for-like: the audit passes only buckets made
    entirely of ibkr-sourced 5m bars, because the reference is IBKR's own trades aggregate and SIP
    5m bars (canonical from 2016-01-04) legitimately differ from it. Exactness is never loosened.
    """
    if timeframe not in _BUCKET_SECONDS:
        raise ValueError(f"grid_parity is defined for {sorted(_BUCKET_SECONDS)}, not {timeframe!r}")
    shared = derived.keys() & archived.keys()
    mismatched = sum(
        1 for key in shared if tuple(map(float, derived[key])) != tuple(map(float, archived[key]))
    )
    return len(shared), mismatched


def rebucket_5m(
    ts_seconds: np.ndarray,
    open_: np.ndarray,
    high: np.ndarray,
    low: np.ndarray,
    close: np.ndarray,
    volume: np.ndarray,
    bucket_starts: Sequence[int],
    *,
    timeframe: str,
) -> dict[int, Values]:
    """Aggregate sorted 5m bars into the vendor archive's own buckets (epoch seconds -> values).

    The archive's 1h grid sits on clock hours (a half-hour bar at 09:30, then 10:00, 11:00, ...)
    while the derived grid is session anchored (09:30, 10:30, ...), so stored derived 1h rows
    share only the 09:30 key with the archive and differ there by span. Re-aggregating the 5m
    bars over each archive bucket's own span (to the next clock boundary of the timeframe) gives
    the like-for-like comparison. A bucket is returned only when every 5m constituent is present.
    """
    width = _BUCKET_SECONDS[timeframe]
    if not len(bucket_starts) or not ts_seconds.size:
        return {}
    starts = np.array(sorted(set(bucket_starts)), dtype=np.int64)
    ends = (starts // width + 1) * width
    idx = np.searchsorted(starts, ts_seconds, side="right") - 1
    inside = (idx >= 0) & (ts_seconds < ends[np.clip(idx, 0, None)])
    if not inside.any():
        return {}
    ids = idx[inside]
    first = np.concatenate(([0], np.flatnonzero(np.diff(ids)) + 1))
    counts = np.diff(np.concatenate((first, [ids.size])))
    bucket = ids[first]
    expected = (ends[bucket] - starts[bucket]) // _FIVE_MINUTES
    full = counts == expected
    o, h, lo, c, v = (a[inside] for a in (open_, high, low, close, volume))
    last = first + counts - 1
    out_high = np.maximum.reduceat(h, first)
    out_low = np.minimum.reduceat(lo, first)
    out_volume = np.add.reduceat(v, first)
    return {
        int(starts[bucket[i]]): (
            float(o[first[i]]),
            float(out_high[i]),
            float(out_low[i]),
            float(c[last[i]]),
            float(out_volume[i]),
        )
        for i in np.flatnonzero(full)
    }


def digest_scope(
    *,
    full_sweep: bool,
    previous_at: datetime | None,
    previous_passed: bool | None,
    loads: Iterable[tuple[datetime, date | None, date | None]],
) -> frozenset[datetime] | None:
    """The calendar months (UTC month starts) the intraday digest_fresh check must recompute for
    one name, or None for every month.

    Every month when a full sweep is due, when the name has no previous verdict (nothing was ever
    checked) or its previous verdict failed (a failure stays a failure until a recompute clears
    it, never because no bar was written since). Otherwise the months spanned by each load with
    changes (loaded_at, first_bar, last_bar) written after the previous report; a load with no
    span means every month.
    """
    if full_sweep or previous_at is None or previous_passed is not True:
        return None
    months: set[datetime] = set()
    for loaded_at, first_bar, last_bar in loads:
        if loaded_at <= previous_at:
            continue
        if first_bar is None or last_bar is None:
            return None
        year, month = first_bar.year, first_bar.month
        while (year, month) <= (last_bar.year, last_bar.month):
            months.add(datetime(year, month, 1, tzinfo=UTC))
            year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return frozenset(months)
