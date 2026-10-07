"""Pure arithmetic of the 1d integrity verdict report (phase 185 plan 33; data layer integrity
design section 6). D7 (services/bar_reconciliation_audit.py) reads the inputs and writes the
verdicts; nothing here touches a database or the APR.
"""

from __future__ import annotations

import time
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date, datetime
from typing import Protocol

import numpy as np

from src.intelligence.bars.daily_rule import (
    ROUTE_TRADIER,
    RULE_VERSION,
    PolicyRow,
    current_closes,
    derive_daily_v2,
    resolve_policy,
)
from src.intelligence.bars.derivation import Observation, SplitRecord
from src.intelligence.bars.digest import bar_content_digest, month_ranges
from src.intelligence.bars.sources import SOURCE_IBKR_FALLBACK
from src.intelligence.bars.vendor_basis import (
    BasisRun,
    blocking,
    canonical_vendor,
    classify_run,
    find_basis_runs,
    ratio_pairs,
)
from src.intelligence.bars.write_contract import BarValues, classify

_PRIMARY_LABEL = {"tradier": "tradier", "ibkr": "ibkr_named"}


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


def policy_conformance(
    rows: Sequence[tuple[date, str]],
    policy_rows: Sequence[PolicyRow],
    tradier_dates: Collection[date],
    *,
    symbol: str,
) -> list[date]:
    """Dates of (date, source) rows whose source contradicts the policy row open on that date.

    The source must be the policy's primary label; ibkr_fallback is accepted only under a policy
    that names IBKR as fallback, on a date with no Tradier observation.
    """
    bad: list[date] = []
    for bar_date, source in rows:
        policy = resolve_policy(policy_rows, symbol, bar_date)
        if source == _PRIMARY_LABEL.get(policy.primary_source):
            continue
        if (
            source == SOURCE_IBKR_FALLBACK
            and policy.fallback_source == "ibkr"
            and bar_date not in tradier_dates
        ):
            continue
        bad.append(bar_date)
    return sorted(bad)


# ---------------------------------------------------------------------------
# The per-name 1d verdict report (plan 185-33 Task 2)
# ---------------------------------------------------------------------------

TIMEFRAME_1D = "1d"
# The checks one 1d name is judged on, in report order. Identifiers, not tunables.
CHECKS_1D = (
    "session_coverage",
    "policy_conformance",
    "lineage_missing",
    "canonical_recompute",
    "digest_fresh",
    "unexplained_seam",
    "vendor_basis_run",
    "report_age",
)
# Reported per name, never a verdict that can fail (the name's history starts at its first
# primary bar; the count is what the report shows).
INFO_REFUSED_HEAD = "refused_head_1d"


class IntegrityThresholds(Protocol):
    """The APR-sourced thresholds the 1d report reads (D7's _IntegrityParams satisfies it)."""

    session_coverage_min: float
    vendor_run_min_sessions: int
    report_max_age_hours: int
    basis_window_sessions: int
    basis_tolerance_bp: float


@dataclass(frozen=True)
class StoredBar:
    """One stored canonical 1d row (market_data_ohlcv, a CANONICAL_1D_SOURCES source)."""

    timestamp: datetime
    open: float | None
    high: float | None
    low: float | None
    close: float | None
    volume: float | None
    source: str


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
    # unexplained_seam findings D7's existing rule found for this name
    seam_findings: int
    latest_load_at: datetime | None


@dataclass(frozen=True)
class NameReport1d:
    verdicts: list[Verdict]
    refused_head: int
    basis_runs: list[BasisRun]
    blocking_runs: list[BasisRun]


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
    """Months whose current digest is missing, differs from the recompute, or is not d2-v2."""
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


def judge_name_1d(
    inputs: NameInputs1d,
    sessions: Sequence[date],
    last_session: date,
    run_start: datetime,
    thresholds: IntegrityThresholds,
    *,
    timings: dict[str, float] | None = None,
) -> NameReport1d:
    """The eight 1d verdicts of one name (design section 6). Pure; timings, when given, collects
    seconds per check. Thresholds that are definitions (zero tolerance) live here as 0.0."""
    symbol = inputs.symbol

    def timed(check: str, started: float) -> None:
        if timings is not None:
            timings[check] = timings.get(check, 0.0) + (time.perf_counter() - started)

    stored: dict[date, BarValues] = {
        b.timestamp.date(): (b.open, b.high, b.low, b.close, b.volume, b.source)  # type: ignore[misc]
        for b in inputs.stored
    }

    def verdict(check: str, passed: bool, metric: float, threshold: float) -> Verdict:
        return Verdict(symbol, TIMEFRAME_1D, check, passed, float(metric), float(threshold))

    verdicts: list[Verdict] = []

    started = time.perf_counter()
    if stored:
        first = min(stored)
        judged_sessions = [s for s in sessions if first <= s <= last_session]
        coverage = session_coverage(
            stored.keys(),
            [s for s in judged_sessions if _in_any(s, inputs.empty_spans)],
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
    tradier_dates = {o.bar_date for o in inputs.observations if o.route == ROUTE_TRADIER}
    contradicted = policy_conformance(
        [(d, values[5]) for d, values in stored.items()],
        inputs.policy_rows,
        tradier_dates,
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
        b.bar_date: (b.open, b.high, b.low, b.close, b.volume, b.source) for b in derived.bars
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
    tradier_closes, ibkr_closes = current_closes(inputs.observations, inputs.splits)
    runs = [
        replace(
            run,
            continuous_vendor=classify_run(
                run,
                ibkr_closes,
                tradier_closes,
                inputs.splits,
                tolerance_bp=thresholds.basis_tolerance_bp,
            ),
        )
        for run in find_basis_runs(
            ratio_pairs(ibkr_closes, tradier_closes),
            tolerance_bp=thresholds.basis_tolerance_bp,
            min_sessions=thresholds.vendor_run_min_sessions,
        )
    ]
    blocking_runs = [
        run
        for run in runs
        if blocking(
            run,
            {
                v
                for d, values in stored.items()
                if run.start <= d <= run.end and (v := canonical_vendor(values[5])) is not None
            },
        )
    ]
    verdicts.append(verdict("vendor_basis_run", not blocking_runs, len(blocking_runs), 0.0))
    timed("vendor_basis_run", started)

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
    return NameReport1d(verdicts, len(derived.refused_head), runs, blocking_runs)
