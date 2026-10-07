"""The verdict gate (plan 185-41; data layer integrity design sections 6 and 8, step 4).

Promotion (`compute_1d`, `compute`) and the phase 186 rebuild read the same computed verdict rows
D7 writes (`integrity_monitor`, monitor_type `bar_integrity`, subject `SYM|tf`, one row per check).
One pure function decides both, so the two cannot disagree. A symbol passes a timeframe when every
required check has a verdict that is passed, no older than `max_age`, and no older than the
series' latest load that changed bars. A missing, failed or stale verdict fails and is named.

`ready_predicate_sql` renders the same rule as a SQL fragment (alias `i` is the instruments row)
from REQUIRED_CHECKS, so the Python gate and the promotion predicate share one constant.

Pure: no database, no APR reads (the age is a parameter). The SQL text constants are for the
callers' cursors; this module executes nothing.
"""

from __future__ import annotations

from collections.abc import Collection, Iterable, Mapping, Sequence
from datetime import datetime, timedelta
from types import MappingProxyType
from typing import NamedTuple

MONITOR_TYPE = "bar_integrity"

REQUIRED_CHECKS: Mapping[str, frozenset[str]] = MappingProxyType(
    {
        "1d": frozenset(
            {
                "session_coverage",
                "policy_conformance",
                "lineage_missing",
                "canonical_recompute",
                "digest_fresh",
                "unexplained_seam",
                "vendor_basis_run",
            }
        ),
        "5m": frozenset({"slot_coverage", "digest_fresh", "coverage_cache"}),
        "15m": frozenset({"digest_fresh", "grid_parity"}),
        "1h": frozenset({"digest_fresh", "grid_parity"}),
    }
)

# Checks that gate the 186 rebuild only (design section 6): the vendor rows must be out of
# market_data_ohlcv before the rebuild reads it, but promotion does not wait for that.
REBUILD_ONLY_CHECKS: Mapping[str, frozenset[str]] = MappingProxyType(
    {"15m": frozenset({"stray_vendor_rows"}), "1h": frozenset({"stray_vendor_rows"})}
)

# A load changes a series only when it wrote, changed or removed bars.
CHANGING_LOAD_PREDICATE = "(l.n_new + l.n_changed + coalesce(l.n_removed, 0)) > 0"

# Latest verdict per (subject, check); ties at one instant sort the failing row first.
LATEST_VERDICTS_SQL = f"""
SELECT DISTINCT ON (subject, metric_name) subject, metric_name, passed, evaluated_at
FROM integrity_monitor
WHERE monitor_type = '{MONITOR_TYPE}' AND subject = ANY(%(subjects)s)
  AND metric_name = ANY(%(checks)s)
ORDER BY subject, metric_name, evaluated_at DESC, passed ASC
"""

LATEST_LOADS_SQL = f"""
SELECT l.symbol, l.timeframe, max(l.loaded_at)
FROM ohlcv_load l
WHERE l.symbol = ANY(%(symbols)s) AND l.timeframe = ANY(%(timeframes)s)
  AND {CHANGING_LOAD_PREDICATE}
GROUP BY l.symbol, l.timeframe
"""


class VerdictRow(NamedTuple):
    """One verdict: a check's result for a (symbol, timeframe) at an evaluation time."""

    symbol: str
    timeframe: str
    check: str
    passed: bool
    evaluated_at: datetime


def all_check_names() -> frozenset[str]:
    """Every check name a gate can read, for loaders that fetch the rows."""
    names: set[str] = set()
    for group in (REQUIRED_CHECKS, REBUILD_ONLY_CHECKS):
        for checks in group.values():
            names |= checks
    return frozenset(names)


def verdict_row_from_record(subject: str, check: str, passed: bool, at: datetime) -> VerdictRow:
    """A VerdictRow from an integrity_monitor record (`SYM|tf` subject)."""
    symbol, _, timeframe = subject.rpartition("|")
    return VerdictRow(symbol, timeframe, check, bool(passed), at)


def _required_for(
    timeframes: Iterable[str], extra_checks: Collection[str]
) -> dict[str, frozenset[str]]:
    unknown = set(extra_checks) - {c for checks in REBUILD_ONLY_CHECKS.values() for c in checks}
    if unknown:
        raise ValueError(f"unknown extra checks: {sorted(unknown)}")
    required: dict[str, frozenset[str]] = {}
    for tf in timeframes:
        if tf not in REQUIRED_CHECKS:
            raise ValueError(f"no required checks for timeframe {tf!r}; refusing to pass it")
        required[tf] = REQUIRED_CHECKS[tf] | (
            REBUILD_ONLY_CHECKS.get(tf, frozenset()) & extra_checks
        )
    return required


def gate_symbols(
    rows: Iterable[VerdictRow],
    *,
    symbols: Sequence[str],
    timeframes: Sequence[str],
    now: datetime,
    max_age: timedelta,
    latest_load: Mapping[tuple[str, str], datetime],
    extra_checks: frozenset[str] = frozenset(),
) -> dict[str, list[str]]:
    """Symbols that fail the gate, each with its reasons (`tf:check failed|missing|stale ...`).

    An empty result means every symbol passes. The latest verdict per (symbol, tf, check) wins;
    at one instant a failing row beats a passing one.
    """
    required = _required_for(timeframes, extra_checks)
    wanted = set(symbols)
    latest: dict[tuple[str, str, str], VerdictRow] = {}
    for row in rows:
        if row.symbol not in wanted:
            continue
        key = (row.symbol, row.timeframe, row.check)
        held = latest.get(key)
        if (
            held is None
            or row.evaluated_at > held.evaluated_at
            or (row.evaluated_at == held.evaluated_at and not row.passed)
        ):
            latest[key] = row

    failures: dict[str, list[str]] = {}
    for symbol in sorted(wanted):
        reasons: list[str] = []
        for tf, checks in required.items():
            loaded = latest_load.get((symbol, tf))
            for check in sorted(checks):
                reason = _reason(latest.get((symbol, tf, check)), now, max_age, loaded)
                if reason:
                    reasons.append(f"{tf}:{check} {reason}")
        if reasons:
            failures[symbol] = reasons
    return failures


def _reason(
    row: VerdictRow | None, now: datetime, max_age: timedelta, loaded: datetime | None
) -> str | None:
    if row is None:
        return "missing"
    if not row.passed:
        return "failed"
    if now - row.evaluated_at > max_age:
        hours = (now - row.evaluated_at).total_seconds() / 3600
        return f"stale (verdict {hours:.1f}h old, older than {max_age.total_seconds() / 3600:g}h)"
    if loaded is not None and row.evaluated_at < loaded:
        return f"stale (newer load at {loaded:%Y-%m-%d %H:%M}Z)"
    return None


def ready_predicate_sql(timeframes: Sequence[str] | None = None) -> str:
    """The promotion predicate over the latest verdicts, rendered from REQUIRED_CHECKS.

    `i` is the instruments row of the caller's outer query. With `timeframes=None` the fragment
    covers every timeframe in REQUIRED_CHECKS and binds `%(timeframes)s` (the APR compute stack);
    with a fixed tuple it renders only those and binds nothing for them. Both bind
    `%(max_age_hours)s` (`threshold.bar_integrity.report_max_age_hours`).

    A bound timeframe with no required checks cannot pass: the count guard compares the number of
    distinct required timeframes found against the number bound (the 174 T-174-41 rule).
    """
    selected = list(REQUIRED_CHECKS) if timeframes is None else list(timeframes)
    for tf in selected:
        if tf not in REQUIRED_CHECKS:
            raise ValueError(f"no required checks for timeframe {tf!r}")
    pairs = ",\n            ".join(
        f"('{tf}', '{check}')" for tf in selected for check in sorted(REQUIRED_CHECKS[tf])
    )
    tf_filter = "req.tf = ANY(%(timeframes)s)" if timeframes is None else "TRUE"
    guard = (
        """
    AND (
        SELECT count(DISTINCT g.tf) FROM (VALUES """
        + ", ".join(f"('{tf}')" for tf in selected)
        + """) AS g(tf)
        WHERE g.tf = ANY(%(timeframes)s)
    ) = cardinality(%(timeframes)s::text[])"""
        if timeframes is None
        else ""
    )
    return f"""
    NOT EXISTS (
        SELECT 1
        FROM (VALUES
            {pairs}
        ) AS req(tf, chk)
        WHERE {tf_filter}
          AND NOT EXISTS (
            SELECT 1 FROM (
                SELECT v.passed, v.evaluated_at
                FROM integrity_monitor v
                WHERE v.monitor_type = '{MONITOR_TYPE}'
                  AND v.subject = i.symbol || '|' || req.tf
                  AND v.metric_name = req.chk
                ORDER BY v.evaluated_at DESC, v.passed ASC
                LIMIT 1
            ) latest
            WHERE latest.passed
              AND latest.evaluated_at >= now() - %(max_age_hours)s * interval '1 hour'
              AND latest.evaluated_at >= coalesce((
                  SELECT max(l.loaded_at) FROM ohlcv_load l
                  WHERE l.symbol = i.symbol AND l.timeframe = req.tf
                    AND {CHANGING_LOAD_PREDICATE}
              ), '-infinity'::timestamptz)
          )
    ){guard}
""".strip()
