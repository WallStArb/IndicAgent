"""Read-only measurement for the 1d primary swap, Tradier to IBKR SMART (plan 185-46 Task 2).

The reproduction of docs/research/1d-primary-swap-evidence.md. The rules it measures against
(R1 to R6) were committed in that document before this script first ran against the data.

Modes (combinable; JSON to --out, per-name rows to --tsv):
- --rate: the IBKR SMART TRADES 1d request rate from ohlcv_request (requests per hour as the
  median over hours holding at least --min-hour-requests, latency mean, median and p90, no_data
  and failed shares), the same for 5m, the fetcher's `run summary:` lines, and the nightly cost of
  the update lane (1d and 5m, one request per name per timeframe) against R4.
- --volume: IBKR SMART over Tradier daily volume per name (median over the last
  --recent-sessions common sessions and over full history), p10, p50, p90, and by-year medians.
- --census: the plan-time counts (names, routes, late starts, Tradier-only interior dates,
  policy rows).
- --classify: per active name, the swap class (A, B, C) and the head candidate, with the count of
  distinct SMART TRADES dates on or after D.

Apply criteria for plan 185-47 (R6; each exits 1 on a breach):
- --export-verdicts OUT: the latest D7 run's per-name bar_integrity verdicts to a TSV.
- --check-dryrun BEFORE AFTER --classes TSV: C1 over two daily-stage dry-run reports, judged
  per name against its effective policy from D (185-47 amendment 2).
- --compare-verdicts BEFORE AFTER: C3, C4 and C6, and the C5 transitions (no connection).

Every connection opens with default_transaction_read_only = on; the module holds no statement
that changes a row. Thresholds come from APR at run time (the evidence doc's R2); a missing key
stops the run instead of falling back to a copied number.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import re
import statistics
import sys
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, NamedTuple

project_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(project_root))

_BP = 1e4
CLASS_A = "A"
CLASS_B = "B"
CLASS_C = "C"


# --- pure API -----------------------------------------------------------------------------


class LedgerRow(NamedTuple):
    requested_at: datetime
    answered_at: datetime
    outcome: str


@dataclass(frozen=True)
class RateSummary:
    n_requests: int
    requests_per_hour: float | None
    n_hours_used: int
    mean_latency_s: float
    median_latency_s: float
    p90_latency_s: float
    no_data_share: float
    failed_share: float


def _quantile(values: Sequence[float], q: float) -> float:
    """Linear-interpolation quantile (percentile_cont)."""
    ordered = sorted(values)
    if not ordered:
        raise ValueError("quantile of nothing")
    pos = q * (len(ordered) - 1)
    lo = int(pos)
    hi = min(lo + 1, len(ordered) - 1)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (pos - lo)


def request_rate_summary(rows: Sequence[LedgerRow], *, min_hour_requests: int) -> RateSummary:
    """Requests per hour (median over hours holding at least min_hour_requests, by request
    hour), latency in seconds, and outcome shares. An empty ledger raises."""
    if not rows:
        raise ValueError("no ledger rows")
    per_hour: dict[datetime, int] = defaultdict(int)
    for r in rows:
        per_hour[r.requested_at.replace(minute=0, second=0, microsecond=0)] += 1
    busy = [n for n in per_hour.values() if n >= min_hour_requests]
    latency = [(r.answered_at - r.requested_at).total_seconds() for r in rows]
    n = len(rows)
    return RateSummary(
        n_requests=n,
        requests_per_hour=float(statistics.median(busy)) if busy else None,
        n_hours_used=len(busy),
        mean_latency_s=statistics.fmean(latency),
        median_latency_s=_quantile(latency, 0.5),
        p90_latency_s=_quantile(latency, 0.9),
        no_data_share=sum(1 for r in rows if r.outcome == "no_data") / n,
        failed_share=sum(1 for r in rows if r.outcome in ("failed", "timeout")) / n,
    )


def nightly_cost_minutes(
    n_names: int, requests_per_hour: float, inter_item_pause_s: float, mean_latency_s: float
) -> float:
    """Minutes for one request per name: the larger of the pacing bound and the serial bound."""
    if requests_per_hour <= 0:
        raise ValueError("requests_per_hour must be positive")
    pacing = n_names / requests_per_hour * 60.0
    serial = n_names * (inter_item_pause_s + mean_latency_s) / 60.0
    return max(pacing, serial)


@dataclass(frozen=True)
class VolumeSummary:
    n_names: int
    p10: float | None
    p50: float | None
    p90: float | None
    share_below_half: float | None
    unusable: tuple[str, ...]
    per_name: dict[str, float] = field(default_factory=dict)


def volume_ratio_summary(
    by_name: Mapping[str, Iterable[tuple[int | None, int | None]]],
) -> VolumeSummary:
    """Per-name median IBKR/Tradier volume ratio over sessions with both volumes positive, then
    the distribution over names. A name with no usable session is listed, not dropped."""
    per_name: dict[str, float] = {}
    unusable: list[str] = []
    for name in sorted(by_name):
        ratios = [
            i / t for i, t in by_name[name] if i is not None and t is not None and i > 0 and t > 0
        ]
        if ratios:
            per_name[name] = statistics.median(ratios)
        else:
            unusable.append(name)
    values = list(per_name.values())
    return VolumeSummary(
        n_names=len(values),
        p10=_quantile(values, 0.1) if values else None,
        p50=_quantile(values, 0.5) if values else None,
        p90=_quantile(values, 0.9) if values else None,
        share_below_half=sum(1 for v in values if v < 0.5) / len(values) if values else None,
        unusable=tuple(unusable),
        per_name=per_name,
    )


@dataclass(frozen=True)
class SwapDecision:
    cls: str
    n_common: int
    median_ratio: float | None
    recent_agree_share: float | None


def _within(ratio: float, tolerance_bp: float) -> bool:
    return abs(ratio - 1.0) * _BP <= tolerance_bp + 1e-9


def classify_swap(
    pairs: Sequence[tuple[date, float, float]],
    *,
    window_sessions: int,
    tolerance_bp: float,
    min_overlap: int,
    min_agree_share: float,
) -> SwapDecision:
    """Class A, B or C over (date, Tradier close, IBKR close) pairs (evidence doc, R2)."""
    from src.intelligence.bars.source_admission import tradier_admission

    ordered = sorted(pairs)
    admission = tradier_admission(
        ordered, min_overlap=min_overlap, min_agree_share=min_agree_share, tolerance_bp=tolerance_bp
    )
    if not ordered:
        return SwapDecision(CLASS_C, 0, None, admission.recent_agree_share)
    recent = ordered[-min(window_sessions, len(ordered)) :]
    median = statistics.median(i / t for _d, t, i in recent)
    if _within(median, tolerance_bp):
        cls = CLASS_A
    elif admission.recent_disagrees and len(ordered) >= min_overlap:
        cls = CLASS_B
    else:
        cls = CLASS_C
    return SwapDecision(cls, len(ordered), median, admission.recent_agree_share)


@dataclass(frozen=True)
class HeadCandidate:
    keep: bool
    first: date | None
    last: date | None
    n_bars: int
    median_ratio: float | None


def head_candidate(
    pairs_from_ibkr_start: Sequence[tuple[date, float, float]],
    tradier_head_dates: Sequence[date],
    *,
    window_sessions: int,
    tolerance_bp: float,
) -> HeadCandidate:
    """Keep the Tradier head (its dates before IBKR's first bar) only when the median ratio over
    the first window_sessions common sessions from IBKR's first bar is within tolerance. No
    common session, or no head, is never kept."""
    head = sorted(tradier_head_dates)
    first_window = sorted(pairs_from_ibkr_start)[:window_sessions]
    median = statistics.median(i / t for _d, t, i in first_window) if first_window else None
    return HeadCandidate(
        keep=bool(head) and median is not None and _within(median, tolerance_bp),
        first=head[0] if head else None,
        last=head[-1] if head else None,
        n_bars=len(head),
        median_ratio=median,
    )


# --- 185-47 apply criteria (evidence doc R6) --------------------------------------------------

ZERO_TOLERANCE_CHECKS = (
    "policy_conformance",
    "lineage_missing",
    "canonical_recompute",
    "digest_fresh",
)
_IDENTITY_COLUMNS = (
    "new", "changed", "changed_source_only", "removed", "head", "refused_head",
    "admitted_interior", "refused_interior", "refused_dates",
)  # fmt: skip


@dataclass(frozen=True)
class Violation:
    symbol: str
    column: str
    detail: str


def _int(row: Mapping[str, str], column: str) -> int:
    return int(row.get(column) or 0)


def _dates(row: Mapping[str, str]) -> set[date]:
    return {date.fromisoformat(x) for x in (row.get("refused_dates") or "").split(",") if x}


def check_dryrun(
    before_rows: Sequence[Mapping[str, str]],
    after_rows: Sequence[Mapping[str, str]],
    classes: Mapping[str, str],
    expected_new: Mapping[str, int],
    *,
    d: date,
) -> list[Violation]:
    """C1 on two daily-stage dry-run reports (185-47, amendment 2: judged per name against its
    effective policy from D).

    A name in expected_new switches to IBKR primary at D; its value is the count of distinct
    SMART TRADES dates on or after D. Each such date must surface either as a new bar (it was a
    refused fallback date) or as a source-label-only change (a stored ibkr_fallback bar now
    ibkr_named); no stored value changes, nothing is removed, head and refused head are equal,
    and the refused dates before D are the same. Every other name keeps its policy at D and its
    report must equal the before report. Class B names are reported by the caller, never flagged.
    """
    before = {r["symbol"]: r for r in before_rows}
    after = {r["symbol"]: r for r in after_rows}
    out: list[Violation] = []
    for symbol in sorted(set(before) ^ set(after)):
        where = "before" if symbol in before else "after"
        out.append(Violation(symbol, "symbol", f"only in the {where} report"))
    for symbol in sorted(set(after) | set(before)):
        if symbol not in classes:
            out.append(Violation(symbol, "class", "missing from the classes file"))
    for symbol in sorted(set(before) & set(after)):
        if classes.get(symbol) == CLASS_B:
            continue
        b, a = before[symbol], after[symbol]
        if symbol not in expected_new:
            for col in _IDENTITY_COLUMNS:
                if (a.get(col) or "") != (b.get(col) or "") and not (
                    col != "refused_dates" and _int(a, col) == _int(b, col)
                ):
                    out.append(Violation(symbol, col, f"{b.get(col)} -> {a.get(col)}"))
            continue
        value_changes = _int(a, "changed") - _int(a, "changed_source_only")
        if value_changes:
            out.append(Violation(symbol, "changed", f"{value_changes} stored values change"))
        if _int(a, "removed"):
            out.append(Violation(symbol, "removed", f"{_int(a, 'removed')} bars removed"))
        for col in ("head", "refused_head"):
            if _int(a, col) != _int(b, col):
                out.append(Violation(symbol, col, f"{_int(b, col)} -> {_int(a, col)}"))
        before_dates, after_dates = _dates(b), _dates(a)
        if after_dates != {x for x in before_dates if x < d}:
            out.append(
                Violation(
                    symbol,
                    "refused_dates",
                    f"before D {sorted(x for x in before_dates if x < d)} -> {sorted(after_dates)}",
                )
            )
        new_delta = _int(a, "new") - _int(b, "new")
        label_delta = _int(a, "changed_source_only") - _int(b, "changed_source_only")
        if new_delta + label_delta != expected_new[symbol]:
            out.append(
                Violation(
                    symbol,
                    "new",
                    f"new {new_delta} + relabelled {label_delta} != "
                    f"{expected_new[symbol]} SMART dates on or after {d}",
                )
            )
        admitted_drop = _int(b, "admitted_interior") - _int(a, "admitted_interior")
        if admitted_drop != label_delta:
            out.append(
                Violation(
                    symbol,
                    "admitted_interior",
                    f"admitted fallback dates fell by {admitted_drop}, relabelled {label_delta}",
                )
            )
    return out


class VerdictRow(NamedTuple):
    subject: str
    check: str
    passed: bool


@dataclass(frozen=True)
class VerdictDiff:
    pass_to_fail: list[tuple[str, str]]
    fail_to_pass: list[tuple[str, str]]
    new_rows: list[tuple[str, str]]
    failing_by_check_before: dict[str, int]
    failing_by_check_after: dict[str, int]


def _failing_by_check(rows: Iterable[VerdictRow]) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for r in rows:
        counts[r.check] += 0 if r.passed else 1
    return dict(sorted(counts.items()))


def compare_verdicts(before: Sequence[VerdictRow], after: Sequence[VerdictRow]) -> VerdictDiff:
    """Per (subject, check): pass to fail, fail to pass, rows absent before; failing names per
    check on both sides. An empty after set raises: an empty comparison proves nothing."""
    if not after:
        raise ValueError("no verdict rows after: an empty comparison proves nothing")
    b = {(r.subject, r.check): r.passed for r in before}
    a = {(r.subject, r.check): r.passed for r in after}
    return VerdictDiff(
        pass_to_fail=sorted(k for k, ok in a.items() if k in b and b[k] and not ok),
        fail_to_pass=sorted(k for k, ok in a.items() if k in b and not b[k] and ok),
        new_rows=sorted(k for k in a if k not in b),
        failing_by_check_before=_failing_by_check(before),
        failing_by_check_after=_failing_by_check(after),
    )


def verdict_failures(diff: VerdictDiff) -> list[str]:
    """The R6 breaches in a comparison (C3, C4, C6); empty means pass."""
    out = [f"pass_to_fail: {s} {c}" for s, c in diff.pass_to_fail]
    for check, n in diff.failing_by_check_after.items():
        if check in ZERO_TOLERANCE_CHECKS and n:
            out.append(f"zero-tolerance: {check} {n} failing")
        elif n > diff.failing_by_check_before.get(check, 0):
            out.append(f"count rose: {check} {diff.failing_by_check_before.get(check, 0)} -> {n}")
    return out


_VERDICT_COLUMNS = ("subject", "check", "passed", "metric_value", "threshold_value", "evaluated_at")


def read_verdicts(path: Path) -> list[VerdictRow]:
    with path.open(newline="") as handle:
        return [
            VerdictRow(r["subject"], r["check"], r["passed"] == "true")
            for r in csv.DictReader(handle, delimiter="\t")
        ]


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


# --- IO (read-only) -------------------------------------------------------------------------

_KEY_WINDOW = "threshold.bar_integrity.fallback_basis_window_sessions"
_KEY_TOL = "threshold.bar_integrity.fallback_basis_tolerance_bp"
_KEY_OVERLAP = "threshold.bar_integrity.tradier_admission_min_overlap_sessions"
_KEY_SHARE = "threshold.bar_integrity.tradier_admission_min_agree_share"
_KEY_PAUSE = "infra.ibkr.inter_item_pause_s"
_KEY_BUDGET = "infra.backfill.run_budget_minutes"
_KEY_LIMIT = "infra.ibkr.rate_limit_max_requests"
_KEY_LIMIT_TF = "infra.ibkr.rate_limit_max_requests_by_tf"
_KEY_WINDOW_S = "infra.ibkr.rate_limit_window_sec"
_APR_KEYS = (
    _KEY_WINDOW, _KEY_TOL, _KEY_OVERLAP, _KEY_SHARE, _KEY_PAUSE, _KEY_BUDGET, _KEY_LIMIT,
    _KEY_LIMIT_TF, _KEY_WINDOW_S,
)  # fmt: skip

_APR_SQL = "SELECT config_key, config_value FROM config_state WHERE config_key = ANY($1::text[])"
_ACTIVE_SQL = "SELECT symbol, compute_eligible_1d, compute_eligible FROM instruments WHERE is_active ORDER BY symbol"
_LEDGER_SQL = """
SELECT requested_at, answered_at, outcome,
       extract(epoch FROM window_end - coalesce(window_start, window_end)) / 86400.0 AS span_days
FROM ohlcv_request
WHERE source = 'ibkr' AND timeframe = $1 AND route = 'SMART' AND what_to_show = 'TRADES'
  AND caller NOT LIKE 'test-%'
"""
_ALL_1D_HOURLY_SQL = """
SELECT date_trunc('hour', requested_at) AS h, count(*) AS n FROM ohlcv_request
WHERE source = 'ibkr' AND timeframe = '1d' AND caller NOT LIKE 'test-%'
GROUP BY 1 HAVING count(*) >= $1 ORDER BY 1
"""
_LATEST_VERDICTS_SQL = """
SELECT DISTINCT ON (subject, metric_name) subject, metric_name, passed
FROM integrity_monitor
WHERE monitor_type = 'bar_integrity' AND metric_name = ANY($1::text[])
ORDER BY subject, metric_name, evaluated_at DESC
"""
_VOLUME_PAIRS_SQL = """
WITH i AS (
    SELECT DISTINCT ON (bar_date) bar_date, volume FROM ohlcv_observation
    WHERE symbol = $1 AND timeframe = '1d' AND route = 'SMART' AND what_to_show = 'TRADES'
    ORDER BY bar_date, fetched_at DESC
), t AS (
    SELECT DISTINCT ON (bar_date) bar_date, volume FROM ohlcv_observation
    WHERE symbol = $1 AND timeframe = '1d' AND route = 'TRADIER'
    ORDER BY bar_date, fetched_at DESC
)
SELECT bar_date, i.volume AS ibkr_volume, t.volume AS tradier_volume
FROM i JOIN t USING (bar_date) ORDER BY bar_date
"""
_SMART_NAMES_SQL = """
SELECT DISTINCT symbol FROM ohlcv_observation
WHERE timeframe = '1d' AND route = 'SMART' AND what_to_show = 'TRADES'
"""
_MAX_TRADIER_SQL = (
    "SELECT max(bar_date) FROM ohlcv_observation WHERE timeframe = '1d' AND route = 'TRADIER'"
)
_CENSUS_SQL = """
WITH a AS (SELECT symbol, compute_eligible_1d AS c1 FROM instruments WHERE is_active),
t AS (SELECT symbol, min(bar_date) AS tf, max(bar_date) AS tl FROM ohlcv_observation
      WHERE timeframe = '1d' AND route = 'TRADIER' GROUP BY symbol),
s AS (SELECT symbol, min(bar_date) AS sf, max(bar_date) AS sl FROM ohlcv_observation
      WHERE timeframe = '1d' AND route = 'SMART' AND what_to_show = 'TRADES' GROUP BY symbol),
q AS (SELECT symbol, bool_or(outcome = 'bars') AS answered FROM ohlcv_request
      WHERE source = 'ibkr' AND timeframe = '1d' AND caller NOT LIKE 'test-%' GROUP BY symbol)
SELECT a.symbol, a.c1, t.tf, t.tl, s.sf, s.sl, q.symbol IS NOT NULL AS asked,
       coalesce(q.answered, false) AS answered
FROM a LEFT JOIN t USING (symbol) LEFT JOIN s USING (symbol) LEFT JOIN q USING (symbol)
ORDER BY a.symbol
"""
_HEAD_BARS_SQL = """
SELECT count(DISTINCT bar_date) FROM ohlcv_observation
WHERE symbol = $1 AND timeframe = '1d' AND route = 'TRADIER' AND bar_date < $2
"""
_INTERIOR_SQL = """
SELECT count(*) FROM (
    SELECT DISTINCT bar_date FROM ohlcv_observation
    WHERE symbol = $1 AND timeframe = '1d' AND route = 'TRADIER' AND bar_date BETWEEN $2 AND $3
    EXCEPT
    SELECT DISTINCT bar_date FROM ohlcv_observation
    WHERE symbol = $1 AND timeframe = '1d' AND route = 'SMART' AND what_to_show = 'TRADES'
      AND bar_date BETWEEN $2 AND $3
) x
"""
_POLICY_SQL = """
SELECT symbol IS NULL AS is_default, primary_source, fallback_source, valid_to IS NULL AS open,
       count(*) AS n, min(valid_from) AS first_from
FROM bar_source_policy WHERE timeframe = '1d' GROUP BY 1, 2, 3, 4 ORDER BY 1 DESC, 2, 3, 4
"""
_SMART_DATES_FROM_SQL = """
SELECT count(DISTINCT bar_date) FROM ohlcv_observation
WHERE symbol = $1 AND timeframe = '1d' AND route = 'SMART' AND what_to_show = 'TRADES'
  AND bar_date >= $2
"""
_RUN_SUMMARY = re.compile(r"run summary: (\{.*\})")
# The per-name verdicts of the latest D7 run: the newest row per (subject, check) within
# $1 minutes of the newest bar_integrity row (one run writes 1d, then 5m, minutes apart).
_EXPORT_VERDICTS_SQL = """
SELECT DISTINCT ON (subject, metric_name) subject, metric_name, passed, metric_value,
       threshold_value, evaluated_at
FROM integrity_monitor
WHERE monitor_type = 'bar_integrity' AND subject LIKE '%|%' AND subject NOT LIKE 'check=%'
  AND evaluated_at >= (SELECT max(evaluated_at) FROM integrity_monitor
                       WHERE monitor_type = 'bar_integrity') - make_interval(mins => $1)
ORDER BY subject, metric_name, evaluated_at DESC
"""
# Names whose 1d symbol row covers date $1: their effective policy does not move at D.
_COVERED_AT_SQL = """
SELECT DISTINCT symbol FROM bar_source_policy
WHERE timeframe = '1d' AND symbol IS NOT NULL AND valid_from <= $1
  AND (valid_to IS NULL OR valid_to > $1)
"""


def _apr(rows: Iterable[Any]) -> dict[str, str]:
    values = {r["config_key"]: r["config_value"] for r in rows}
    missing = [k for k in _APR_KEYS if k not in values]
    if missing:
        raise SystemExit(f"missing APR keys: {missing}")
    return values


async def _connect() -> Any:
    import asyncpg

    from src.config.settings import Settings

    dsn = Settings().database_url.replace("postgresql+asyncpg://", "postgresql://")
    conn = await asyncpg.connect(dsn, server_settings={"default_transaction_read_only": "on"})
    if await conn.fetchval("SHOW default_transaction_read_only") != "on":
        await conn.close()
        raise SystemExit("connection is not read-only")
    return conn


def _first_session_after(day: date) -> date:
    from src.intelligence.bars.sessions import nyse_sessions

    return min(nyse_sessions(day + timedelta(days=1), day + timedelta(days=14)))


def _fetcher_run_summaries(log_path: Path) -> list[dict[str, Any]]:
    if not log_path.exists():
        return []
    out: list[dict[str, Any]] = []
    for line in log_path.read_text(errors="replace").splitlines():
        match = _RUN_SUMMARY.search(line)
        if match:
            try:
                out.append(json.loads(match.group(1)))
            except json.JSONDecodeError:
                continue
    return out


def _ledger(rows: Iterable[Any], max_span_days: float | None = None) -> list[LedgerRow]:
    return [
        LedgerRow(r["requested_at"], r["answered_at"], r["outcome"])
        for r in rows
        if max_span_days is None or (r["span_days"] is not None and r["span_days"] <= max_span_days)
    ]


async def measure_rate(conn: Any, apr: dict[str, str], args: argparse.Namespace) -> dict[str, Any]:
    active = await conn.fetch(_ACTIVE_SQL)
    n_active = len(active)
    n_compute_1d = sum(1 for r in active if r["compute_eligible_1d"])
    n_intraday = sum(1 for r in active if r["compute_eligible"])
    pause = float(apr[_KEY_PAUSE])
    budget = float(apr[_KEY_BUDGET])
    window_s = float(apr[_KEY_WINDOW_S])
    per_hour = 3600.0 / window_s
    floor_rph = {
        "1d": float(json.loads(apr[_KEY_LIMIT_TF]).get("1d", apr[_KEY_LIMIT])) * per_hour,
        "5m": float(json.loads(apr[_KEY_LIMIT_TF]).get("5m", apr[_KEY_LIMIT])) * per_hour,
    }
    rows_1d = await conn.fetch(_LEDGER_SQL, "1d")
    rows_5m = await conn.fetch(_LEDGER_SQL, "5m")
    rate_1d = request_rate_summary(_ledger(rows_1d), min_hour_requests=args.min_hour_requests)
    rate_1d_short = request_rate_summary(
        _ledger(rows_1d, args.update_span_days), min_hour_requests=args.min_hour_requests
    )
    rate_5m = request_rate_summary(_ledger(rows_5m), min_hour_requests=args.min_hour_requests)
    short_5m_rows = _ledger(rows_5m, args.update_span_days)
    rate_5m_short = (
        request_rate_summary(short_5m_rows, min_hour_requests=args.min_hour_requests)
        if short_5m_rows
        else None
    )
    all_hours = [
        {"hour": r["h"].isoformat(), "n": r["n"]}
        for r in await conn.fetch(_ALL_1D_HOURLY_SQL, args.min_hour_requests)
    ]

    def lane(tf: str, n: int, rph: float, latency: float) -> dict[str, Any]:
        return {"timeframe": tf, "names": n, "rph": rph, "latency_s": latency,
                "minutes": nightly_cost_minutes(n, rph, pause, latency)}  # fmt: skip

    lat_1d = rate_1d_short.mean_latency_s
    lat_5m = rate_5m_short.mean_latency_s if rate_5m_short else rate_5m.mean_latency_s
    measured_1d = rate_1d.requests_per_hour or floor_rph["1d"]
    update_lane = {
        "1d_measured_rate": lane("1d", n_active, measured_1d, lat_1d),
        "1d_limiter": lane("1d", n_active, floor_rph["1d"], lat_1d),
        "5m_today": lane("5m", n_intraday, floor_rph["5m"], lat_5m),
        "5m_after_drain": lane("5m", n_compute_1d, floor_rph["5m"], lat_5m),
    }
    combos = {
        "today_measured": update_lane["1d_measured_rate"]["minutes"]
        + update_lane["5m_today"]["minutes"],
        "today_limiter": update_lane["1d_limiter"]["minutes"] + update_lane["5m_today"]["minutes"],
        "after_drain_measured": update_lane["1d_measured_rate"]["minutes"]
        + update_lane["5m_after_drain"]["minutes"],
        "after_drain_limiter": update_lane["1d_limiter"]["minutes"]
        + update_lane["5m_after_drain"]["minutes"],
    }
    verdicts = await conn.fetch(_LATEST_VERDICTS_SQL, ["session_coverage", "slot_coverage"])
    failing = defaultdict(int)
    for v in verdicts:
        if not v["passed"]:
            failing[v["metric_name"]] += 1
    gap_fill = {
        "1d_names_failing_session_coverage": failing["session_coverage"],
        "1d_minutes": nightly_cost_minutes(
            failing["session_coverage"], floor_rph["1d"], pause, rate_1d.mean_latency_s
        ),
        "5m_names_failing_slot_coverage": failing["slot_coverage"],
        "5m_minutes_one_chunk_each": nightly_cost_minutes(
            failing["slot_coverage"], floor_rph["5m"], pause, rate_5m.mean_latency_s
        ),
    }
    r4_bound = budget / 2.0
    return {
        "n_active": n_active,
        "n_compute_1d": n_compute_1d,
        "n_intraday": n_intraday,
        "inter_item_pause_s": pause,
        "run_budget_minutes": budget,
        "r4_bound_minutes": r4_bound,
        "limiter_rph": floor_rph,
        "rate_1d": asdict(rate_1d),
        "rate_1d_update_span": asdict(rate_1d_short),
        "rate_5m": asdict(rate_5m),
        "rate_5m_update_span": asdict(rate_5m_short) if rate_5m_short else None,
        "update_span_days": args.update_span_days,
        "all_route_1d_busy_hours": all_hours,
        "fetcher_run_summaries": _fetcher_run_summaries(Path(args.fetcher_log)),
        "update_lane": update_lane,
        "update_lane_total_minutes": combos,
        "r4_pass": {k: v <= r4_bound for k, v in combos.items()},
        "gap_fill_lane": gap_fill,
    }


async def measure_volume(conn: Any, args: argparse.Namespace) -> dict[str, Any]:
    active = {r["symbol"] for r in await conn.fetch(_ACTIVE_SQL)}
    names = sorted(active & {r["symbol"] for r in await conn.fetch(_SMART_NAMES_SQL)})
    recent: dict[str, list[tuple[int | None, int | None]]] = {}
    full: dict[str, list[tuple[int | None, int | None]]] = {}
    by_year: dict[int, dict[str, list[tuple[int | None, int | None]]]] = defaultdict(dict)
    for symbol in names:
        rows = await conn.fetch(_VOLUME_PAIRS_SQL, symbol)
        pairs = [(r["ibkr_volume"], r["tradier_volume"]) for r in rows]
        full[symbol] = pairs
        recent[symbol] = pairs[-args.recent_sessions :]
        for r in rows:
            by_year[r["bar_date"].year].setdefault(symbol, []).append(
                (r["ibkr_volume"], r["tradier_volume"])
            )
    s_recent = volume_ratio_summary(recent)
    s_full = volume_ratio_summary(full)
    years = {}
    for year in sorted(by_year):
        s = volume_ratio_summary(by_year[year])
        years[year] = {"n_names": s.n_names, "p10": s.p10, "p50": s.p50, "p90": s.p90}

    def brief(s: VolumeSummary) -> dict[str, Any]:
        d = asdict(s)
        d.pop("per_name")
        return d

    return {
        "n_overlap_names": len(names),
        "recent_sessions": args.recent_sessions,
        "recent": brief(s_recent),
        "full": brief(s_full),
        "by_year": years,
        "_per_name": {k: (s_recent.per_name.get(k), s_full.per_name.get(k)) for k in names},
    }


async def measure_census(conn: Any, args: argparse.Namespace) -> dict[str, Any]:
    rows = await conn.fetch(_CENSUS_SQL)
    no_smart = [r for r in rows if r["sf"] is None]
    late = [
        r
        for r in rows
        if r["sf"] and r["tf"] and r["sf"] > r["tf"] + timedelta(days=args.late_days)
    ]
    head_bars = 0
    for r in late:
        head_bars += await conn.fetchval(_HEAD_BARS_SQL, r["symbol"], r["sf"])
    interior_total, interior_names = 0, 0
    for r in rows:
        if r["sf"] and r["tf"]:
            n = await conn.fetchval(_INTERIOR_SQL, r["symbol"], r["sf"], r["sl"])
            interior_total += n
            interior_names += 1 if n else 0
    policy = [
        {k: (v.isoformat() if isinstance(v, date) else v) for k, v in dict(p).items()}
        for p in await conn.fetch(_POLICY_SQL)
    ]
    return {
        "n_active": len(rows),
        "n_compute_1d": sum(1 for r in rows if r["c1"]),
        "tradier_names": sum(1 for r in rows if r["tf"]),
        "tradier_last_date": max((r["tl"] for r in rows if r["tl"]), default=None),
        "smart_trades_names": sum(1 for r in rows if r["sf"]),
        "no_smart_trades": len(no_smart),
        "no_smart_never_asked": sum(1 for r in no_smart if not r["asked"]),
        "no_smart_never_asked_compute_1d": sum(1 for r in no_smart if not r["asked"] and r["c1"]),
        "no_smart_asked_never_answered": sum(1 for r in no_smart if r["asked"]),
        "late_start_days": args.late_days,
        "late_start_names": len(late),
        "late_start_tradier_bars_before_ibkr": head_bars,
        "tradier_only_interior_dates": interior_total,
        "tradier_only_interior_names": interior_names,
        "ibkr_first_bar_earliest": min((r["sf"] for r in rows if r["sf"]), default=None),
        "policy_1d": policy,
    }


async def measure_classify(conn: Any, apr: dict[str, str], tsv: Path | None) -> dict[str, Any]:
    from services.bar_derivation import _SELECT_DAILY_OBSERVATIONS_SQL, _SELECT_DAILY_SPLITS_SQL
    from src.intelligence.bars.daily_rule import current_closes
    from src.intelligence.bars.derivation import Observation, SplitRecord
    from src.intelligence.bars.source_admission import common_session_closes

    window = int(apr[_KEY_WINDOW])
    tol = float(apr[_KEY_TOL])
    overlap = int(apr[_KEY_OVERLAP])
    share = float(apr[_KEY_SHARE])
    max_tradier = await conn.fetchval(_MAX_TRADIER_SQL)
    d = _first_session_after(max_tradier)
    out_rows: list[dict[str, Any]] = []
    for r in await conn.fetch(_ACTIVE_SQL):
        symbol = r["symbol"]
        obs = [
            Observation(
                request_id=o["request_id"], route=o["route"], bar_date=o["bar_date"],
                open=o["open"], high=o["high"], low=o["low"], close=o["close"],
                volume=o["volume"], fetched_at=o["fetched_at"], legacy=o["legacy"],
                what_to_show=o["what_to_show"],
            )  # fmt: skip
            for o in await conn.fetch(_SELECT_DAILY_OBSERVATIONS_SQL, symbol, ["TRADIER", "SMART"])
        ]
        splits = [
            SplitRecord(
                effective_date=s["effective_date"], recorded_at=s["recorded_at"],
                factor=s["factor"], evidence_request_ids=tuple(s["evidence_request_ids"] or ()),
            )  # fmt: skip
            for s in await conn.fetch(_SELECT_DAILY_SPLITS_SQL, symbol)
        ]
        tradier, ibkr = current_closes(obs, splits)
        smart_dates = sorted(
            {o.bar_date for o in obs if o.route == "SMART" and o.what_to_show == "TRADES"}
        )
        pairs = common_session_closes(obs, splits)
        decision = classify_swap(
            pairs,
            window_sessions=window,
            tolerance_bp=tol,
            min_overlap=overlap,
            min_agree_share=share,
        )
        ibkr_first = min(ibkr) if ibkr else None
        head = head_candidate(
            pairs,
            (
                [day for day in tradier if ibkr_first is None or day < ibkr_first]
                if ibkr_first
                else []
            ),
            window_sessions=window,
            tolerance_bp=tol,
        )
        if not smart_dates:
            reason = "no_ibkr_yet"
        elif decision.n_common == 0:
            reason = "no_common"
        elif decision.cls == CLASS_C and decision.n_common < overlap:
            reason = "few_common"
        elif decision.cls == CLASS_C:
            reason = "off_recent_admission_agrees"
        else:
            reason = ""
        out_rows.append(
            {
                "symbol": symbol,
                "compute_1d": bool(r["compute_eligible_1d"]),
                "cls": decision.cls,
                "reason": reason,
                "n_common": decision.n_common,
                "median_ratio": decision.median_ratio,
                "recent_agree_share": decision.recent_agree_share,
                "tradier_first": min(tradier) if tradier else None,
                "tradier_last": max(tradier) if tradier else None,
                "ibkr_first": ibkr_first,
                "head_n_bars": head.n_bars,
                "head_keep": head.keep,
                "head_median_ratio": head.median_ratio,
                "smart_dates_from_d": sum(1 for day in smart_dates if day >= d),
            }
        )
    if tsv is not None:
        with tsv.open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(out_rows[0]), delimiter="\t")
            writer.writeheader()
            for row in out_rows:
                writer.writerow({k: ("" if v is None else v) for k, v in row.items()})
    with_smart = [row for row in out_rows if row["reason"] != "no_ibkr_yet"]
    counts = defaultdict(int)
    for row in with_smart:
        counts[row["cls"]] += 1
    reasons = defaultdict(int)
    for row in out_rows:
        if row["cls"] == CLASS_C:
            reasons[row["reason"]] += 1
    return {
        "params": {"window_sessions": window, "tolerance_bp": tol, "min_overlap": overlap,
                   "min_agree_share": share},  # fmt: skip
        "max_tradier_date": max_tradier,
        "d": d,
        "n_names": len(out_rows),
        "n_with_smart": len(with_smart),
        "classes_with_smart": dict(counts),
        "classes_all": {
            c: sum(1 for x in out_rows if x["cls"] == c) for c in (CLASS_A, CLASS_B, CLASS_C)
        },
        "class_c_reasons": dict(reasons),
        "heads_present": sum(1 for x in with_smart if x["head_n_bars"] > 0),
        "heads_keepable": sum(1 for x in with_smart if x["head_keep"]),
        "heads_keepable_class_b": sorted(
            x["symbol"] for x in with_smart if x["head_keep"] and x["cls"] == CLASS_B
        ),
        "class_b": sorted(x["symbol"] for x in with_smart if x["cls"] == CLASS_B),
        "class_c_with_smart": sorted(x["symbol"] for x in with_smart if x["cls"] == CLASS_C),
        "smart_dates_from_d_total": sum(x["smart_dates_from_d"] for x in out_rows),
    }


async def _main(args: argparse.Namespace) -> int:
    conn = await _connect()
    try:
        apr = _apr(await conn.fetch(_APR_SQL, list(_APR_KEYS)))
        result: dict[str, Any] = {"measured_at": datetime.now(UTC).isoformat()}
        if args.rate:
            result["rate"] = await measure_rate(conn, apr, args)
        if args.volume:
            result["volume"] = await measure_volume(conn, args)
        if args.census:
            result["census"] = await measure_census(conn, args)
        if args.classify:
            result["classify"] = await measure_classify(
                conn, apr, Path(args.tsv) if args.tsv else None
            )
    finally:
        await conn.close()
    text = json.dumps(result, default=str, indent=2)
    if args.out:
        Path(args.out).write_text(text)
    print(text if not args.out else f"wrote {args.out}")
    return 0


async def _export_verdicts(out: Path, run_window_minutes: int) -> int:
    conn = await _connect()
    try:
        rows = await conn.fetch(_EXPORT_VERDICTS_SQL, run_window_minutes)
    finally:
        await conn.close()
    if not rows:
        raise SystemExit("no bar_integrity verdict rows to export")
    with out.open("w", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t")
        writer.writerow(_VERDICT_COLUMNS)
        for r in rows:
            writer.writerow(
                [r["subject"], r["metric_name"], str(r["passed"]).lower(), r["metric_value"],
                 r["threshold_value"], r["evaluated_at"].isoformat()]
            )  # fmt: skip
    first = min(r["evaluated_at"] for r in rows)
    print(f"wrote {out}: {len(rows)} verdicts, evaluated {first.isoformat()} onward")
    return 0


async def _check_dryrun(before: Path, after: Path, classes_path: Path) -> int:
    classes_rows = read_tsv(classes_path)
    classes = {r["symbol"]: r["cls"] for r in classes_rows}
    conn = await _connect()
    try:
        d = _first_session_after(await conn.fetchval(_MAX_TRADIER_SQL))
        covered = {r["symbol"] for r in await conn.fetch(_COVERED_AT_SQL, d)}
    finally:
        await conn.close()
    expected = {
        r["symbol"]: int(r["smart_dates_from_d"])
        for r in classes_rows
        if r["symbol"] not in covered
    }
    before_rows, after_rows = read_tsv(before), read_tsv(after)
    violations = check_dryrun(before_rows, after_rows, classes, expected, d=d)
    judged = {r["symbol"] for r in after_rows}
    switching = sorted(judged & set(expected))
    print(f"D {d}; judged {len(judged)}; switching to IBKR at D {len(switching)}; "
          f"policy unchanged at D {len(judged) - len(switching)}")  # fmt: skip
    totals: dict[str, int] = defaultdict(int)
    for r in after_rows:
        if r["symbol"] in expected:
            for col in ("new", "changed_source_only"):
                totals[col] += _int(r, col)
    print(f"switching names: new {totals['new']}, relabelled {totals['changed_source_only']}, "
          f"SMART dates on or after D {sum(expected[s] for s in switching)}")  # fmt: skip
    print("class B (reported, never a violation): symbol new changed removed refused_head")
    for r in after_rows:
        if classes.get(r["symbol"]) == CLASS_B:
            print(f"  {r['symbol']} {r['new']} {r['changed']} {r['removed']} {r['refused_head']}")
    for v in violations:
        print(f"VIOLATION {v.symbol} {v.column}: {v.detail}")
    print(f"C1 {'FAIL' if violations else 'pass'}: {len(violations)} violations")
    return 1 if violations else 0


def _compare_verdicts(before: Path, after: Path) -> int:
    diff = compare_verdicts(read_verdicts(before), read_verdicts(after))
    checks = sorted(set(diff.failing_by_check_before) | set(diff.failing_by_check_after))
    print("check\tfailing_before\tfailing_after")
    for c in checks:
        print(
            f"{c}\t{diff.failing_by_check_before.get(c, 0)}\t{diff.failing_by_check_after.get(c, 0)}"
        )
    for label, pairs in (("pass_to_fail", diff.pass_to_fail), ("fail_to_pass", diff.fail_to_pass),
                         ("new_rows", diff.new_rows)):  # fmt: skip
        print(f"{label} {len(pairs)}")
        for subject, check in pairs:
            print(f"  {subject}\t{check}")
    failures = verdict_failures(diff)
    for f in failures:
        print(f"FAIL {f}")
    print(f"C3/C4/C6 {'FAIL' if failures else 'pass'}")
    return 1 if failures else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--export-verdicts", metavar="OUT", default=None,
                        help="185-47: the latest D7 run's per-name verdicts to a TSV")  # fmt: skip
    parser.add_argument("--run-window-minutes", type=int, default=60)
    parser.add_argument("--check-dryrun", nargs=2, metavar=("BEFORE", "AFTER"), default=None)
    parser.add_argument("--classes", default=None, help="check-dryrun: the --classify TSV")
    parser.add_argument("--compare-verdicts", nargs=2, metavar=("BEFORE", "AFTER"), default=None)
    parser.add_argument("--rate", action="store_true")
    parser.add_argument("--volume", action="store_true")
    parser.add_argument("--census", action="store_true")
    parser.add_argument("--classify", action="store_true")
    parser.add_argument("--out", default=None, help="JSON result path")
    parser.add_argument("--tsv", default=None, help="classify: per-name TSV path")
    parser.add_argument("--min-hour-requests", type=int, default=50)
    parser.add_argument("--update-span-days", type=float, default=10.0,
                        help="a request spanning at most this many days counts as an update-lane request")  # fmt: skip
    parser.add_argument("--recent-sessions", type=int, default=250)
    parser.add_argument("--late-days", type=int, default=7)
    parser.add_argument(
        "--fetcher-log", default=str(project_root / "logs" / "ibkr_history_fetcher.log")
    )
    args = parser.parse_args(argv)
    if args.export_verdicts:
        return asyncio.run(_export_verdicts(Path(args.export_verdicts), args.run_window_minutes))
    if args.check_dryrun:
        if not args.classes:
            parser.error("--check-dryrun needs --classes")
        before, after = (Path(p) for p in args.check_dryrun)
        return asyncio.run(_check_dryrun(before, after, Path(args.classes)))
    if args.compare_verdicts:
        before, after = (Path(p) for p in args.compare_verdicts)
        return _compare_verdicts(before, after)
    if not (args.rate or args.volume or args.census or args.classify):
        parser.error("choose at least one of --rate, --volume, --census, --classify")
    return asyncio.run(_main(args))


if __name__ == "__main__":
    sys.exit(main())
