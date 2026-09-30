"""Split-seam audit (phase 185 plan 15, D-21, D-24).

Compares each name's stored 1d closes (market_data_ohlcv_scrub_input, ibkr_named, quarantined
bars included) with the fresh TRADES closes of one bootstrap fetch run held in D1, on the days
both have. A seam is a constant-ratio run (src.intelligence.bars.seams.find_seams); a seam whose
factor snaps to a rational p/q with p, q <= 50 becomes a corporate_action row (inferred_by
seam_audit) and every stored bar up to the effective date gets a quarantine split_seam flag until
D2 re-derives it on one scale. A disagreement that is not a constant ratio, does not snap, or
runs to the last compared day is reported as unexplained and never forced into a split.

MRNA and ALMS run first and lead the report (D-24: their large one-day moves are events, not
splits, unless the ratio says otherwise). Default is a dry run; --apply writes corporate_action,
split_seam flags, one seam_audit provenance batch and integrity facts. One transaction per symbol.
Seam thresholds are the threshold.seam.* APR keys.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import Awaitable, Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import asyncpg
import numpy as np
import structlog

from services._batch_utils import load_apr_dict_async
from services.bar_derivation_batch import close_batch, open_batch
from services.bar_scrub import FlagRow, write_flags
from src.config.settings import Settings
from src.core.integrity_monitor import emit_integrity_fact_async
from src.intelligence.bars.corporate_actions import SplitInference, infer_split
from src.intelligence.bars.seams import Seam, find_seams

_logger = structlog.get_logger(__name__)

_RULE = "split_seam"
_RULE_VERSION = "seam-v1"
_MONITOR_TYPE = "bar_seam_audit"
_FIRST_NAMES = ("MRNA", "ALMS")
_EVENT_DATES = {"MRNA": date(2026, 8, 19), "ALMS": date(2026, 9, 1)}
_APR_REL_TOL = "threshold.seam.rel_tol"
_APR_MIN_RUN = "threshold.seam.min_run"
_APR_SNAP = "threshold.seam.ratio_snap_tol"
_APR_QUARANTINE = "threshold.bar_scrub.quarantine_rules"
_WriteFlags = Callable[..., Awaitable[int]]


@dataclass(frozen=True)
class Unexplained:
    seam: Seam
    reason: str


@dataclass
class SymbolAudit:
    """One symbol's audit outcome; skipped is set when no comparison was possible."""

    n_common_days: int = 0
    seams: list[Seam] = field(default_factory=list)
    splits: list[SplitInference] = field(default_factory=list)
    unexplained: list[Unexplained] = field(default_factory=list)
    skipped: str | None = None
    ratio_by_day: dict[date, float] = field(default_factory=dict)


# --- pure pieces -----------------------------------------------------------------


def order_symbols(symbols: Iterable[str]) -> list[str]:
    unique = sorted(set(symbols))
    head = [s for s in _FIRST_NAMES if s in unique]
    return head + [s for s in unique if s not in head]


def audit_symbol(
    stored: Mapping[date, float],
    fresh: Mapping[date, float],
    *,
    rel_tol: float,
    min_run: int,
    ratio_snap_tol: float,
) -> SymbolAudit:
    """Seams and splits of one symbol from its stored and fresh close series (pure)."""
    days = sorted(
        d
        for d in stored.keys() & fresh.keys()
        if np.isfinite(stored[d]) and np.isfinite(fresh[d]) and stored[d] > 0 and fresh[d] > 0
    )
    audit = SymbolAudit(n_common_days=len(days))
    if len(days) < min_run:
        audit.skipped = f"only {len(days)} common days (need at least {min_run})"
        return audit
    stored_close = np.array([stored[d] for d in days])
    fresh_close = np.array([fresh[d] for d in days])
    audit.ratio_by_day = {d: float(s / f) for d, s, f in zip(days, stored_close, fresh_close)}
    audit.seams = find_seams(days, stored_close, fresh_close, rel_tol=rel_tol, min_run=min_run)
    for seam in audit.seams:
        if seam.end == days[-1]:
            audit.unexplained.append(
                Unexplained(seam, "constant ratio runs to the last compared day; no seam date")
            )
            continue
        split = infer_split(seam, ratio_snap_tol=ratio_snap_tol)
        if split is None:
            audit.unexplained.append(
                Unexplained(seam, f"factor {seam.factor:.6f} snaps to no split ratio")
            )
        else:
            audit.splits.append(split)
    audit.unexplained.extend(_uncovered_disagreements(audit, days, rel_tol))
    return audit


def _uncovered_disagreements(
    audit: SymbolAudit, days: Sequence[date], rel_tol: float
) -> list[Unexplained]:
    """Off-scale days that no seam run covers, grouped into runs of adjacent common days.

    A disagreement that is not a constant ratio never becomes a split; it is listed here.
    """
    covered = [(s.start, s.end) for s in audit.seams]
    groups: list[list[date]] = []
    previous_idx = -2
    for idx, day in enumerate(days):
        ratio = audit.ratio_by_day[day]
        if abs(ratio - 1.0) <= rel_tol or any(a <= day <= b for a, b in covered):
            continue
        if idx == previous_idx + 1 and groups:
            groups[-1].append(day)
        else:
            groups.append([day])
        previous_idx = idx
    out: list[Unexplained] = []
    for group in groups:
        ratios = np.array([audit.ratio_by_day[d] for d in group])
        factor = float(np.median(ratios))
        seam = Seam(
            start=group[0],
            end=group[-1],
            factor=factor,
            n_days=len(group),
            max_rel_dev=float(np.max(np.abs(ratios / factor - 1.0))),
        )
        out.append(Unexplained(seam, "non-constant disagreement"))
    return out


def split_seam_flags(
    stored_timestamps: Sequence[datetime],
    splits: Sequence[SplitInference],
    *,
    quarantine: bool,
) -> list[FlagRow]:
    """One split_seam flag per stored bar on or before the latest effective date.

    Every split that follows a bar is listed in its detail with the product of their factors
    (the stored/consistent-scale ratio of that bar).
    """
    if not splits:
        return []
    latest = max(s.effective_date for s in splits)
    flags: list[FlagRow] = []
    for ts in sorted(stored_timestamps):
        day = ts.astimezone(UTC).date()
        if day > latest:
            break
        following = [s for s in splits if day <= s.effective_date]
        cumulative = float(np.prod([s.factor for s in following]))
        flags.append(
            FlagRow(
                timestamp=ts,
                rule=_RULE,
                rule_version=_RULE_VERSION,
                fields=("open", "high", "low", "close"),
                quarantine=quarantine,
                detail={
                    "cumulative_factor": cumulative,
                    "splits": [
                        {"effective_date": s.effective_date.isoformat(), "factor": s.factor}
                        for s in following
                    ],
                },
            )
        )
    return flags


_EXISTING_SQL = """
SELECT action_id::text, factor FROM corporate_action_current
WHERE symbol = $1 AND effective_date = $2 AND inferred_by = 'seam_audit'
"""

_INSERT_SQL = """
INSERT INTO corporate_action
    (symbol, action_type, effective_date, factor, inferred_by, evidence_request_ids,
     detail, supersedes, batch_id)
VALUES ($1, $2, $3, $4, 'seam_audit', $5::uuid[], $6::jsonb, $7::uuid, $8::uuid)
"""


async def apply_symbol(
    conn: Any,
    *,
    symbol: str,
    audit: SymbolAudit,
    stored_timestamps: Sequence[datetime],
    evidence_request_ids: Sequence[str],
    batch_id: str,
    quarantine: bool,
    write_flags_fn: _WriteFlags = write_flags,
) -> int:
    """Record the symbol's splits and replace its split_seam flags, in one transaction.

    Idempotent: a split already recorded with the same factor is skipped, a different factor
    is recorded as a superseding row. Returns the number of corporate_action rows inserted.
    """
    if audit.splits and not evidence_request_ids:
        raise ValueError(f"{symbol}: refusing to record a split without evidence request ids")
    flags = split_seam_flags(stored_timestamps, audit.splits, quarantine=quarantine)
    inserted = 0
    async with conn.transaction():
        await conn.execute("SET LOCAL ROLE bar_derivation_writer")
        for split in audit.splits:
            existing = await conn.fetch(_EXISTING_SQL, symbol, split.effective_date)
            if any(abs(float(factor) - split.factor) < 1e-9 for _, factor in existing):
                continue
            supersedes = existing[0][0] if existing else None
            await _insert(conn, symbol, split, evidence_request_ids, supersedes, batch_id)
            inserted += 1
        if stored_timestamps:
            ordered = sorted(stored_timestamps)
            await write_flags_fn(
                conn,
                tf="1d",
                symbol=symbol,
                rules_evaluated=frozenset({_RULE}),
                flags=flags,
                start=ordered[0],
                end=ordered[-1] + timedelta(days=1),
                batch_id=batch_id,
            )
    return inserted


async def _insert(
    conn: Any,
    symbol: str,
    split: SplitInference,
    evidence_request_ids: Sequence[str],
    supersedes: str | None,
    batch_id: str,
) -> None:
    await conn.execute(
        _INSERT_SQL,
        symbol,
        split.kind,
        split.effective_date,
        split.factor,
        list(evidence_request_ids),
        json.dumps({"evidence_days": split.evidence_days}),
        supersedes,
        batch_id,
    )


# --- reads -----------------------------------------------------------------------


async def _stored(conn: Any, symbol: str) -> tuple[dict[date, float], list[datetime]]:
    rows = await conn.fetch(
        'SELECT "timestamp", close FROM market_data_ohlcv_scrub_input '
        "WHERE symbol = $1 AND timeframe = '1d' AND source = 'ibkr_named' "
        'ORDER BY "timestamp"',
        symbol,
    )
    stamps = [r["timestamp"] for r in rows]
    return {ts.astimezone(UTC).date(): float(r["close"]) for ts, r in zip(stamps, rows)}, stamps


async def _fresh(conn: Any, symbol: str, run_id: str) -> tuple[dict[date, float], list[str]]:
    rows = await conn.fetch(
        """
        SELECT o.bar_date, o.close, o.request_id::text
        FROM ohlcv_observation o JOIN ohlcv_request r USING (request_id)
        WHERE r.fetch_run_id = $1::uuid AND r.symbol = $2 AND r.what_to_show = 'TRADES'
          AND r.outcome = 'bars' AND r.timeframe = '1d'
        ORDER BY o.fetched_at
        """,
        run_id,
        symbol,
    )
    return {r["bar_date"]: float(r["close"]) for r in rows}, sorted({r["request_id"] for r in rows})


async def _legacy_request_ids(conn: Any, symbol: str) -> list[str]:
    rows = await conn.fetch(
        "SELECT request_id::text FROM ohlcv_request "
        "WHERE symbol = $1 AND route = 'LEGACY_IMPORT' AND caller = 'd1-bootstrap'",
        symbol,
    )
    return [r[0] for r in rows]


# --- report ----------------------------------------------------------------------


def _verdict(symbol: str, audit: SymbolAudit) -> str:
    event = _EVENT_DATES.get(symbol)
    if audit.skipped:
        return f"no verdict: {audit.skipped}"
    near = [s for s in audit.splits if event and abs((s.effective_date - event).days) <= 5]
    if near:
        return f"split (factor {near[0].factor:g}, last old-scale day {near[0].effective_date})"
    if audit.splits or audit.unexplained:
        return "an event on the date, plus seams elsewhere (listed below)"
    return "event, not a split: the stored/fresh ratio stays 1 through the date"


def _ratio_window(audit: SymbolAudit, event: date | None) -> list[str]:
    if event is None or not audit.ratio_by_day:
        return []
    days = sorted(audit.ratio_by_day)
    near = [d for d in days if abs((d - event).days) <= 4]
    return [f"    {d} ratio {audit.ratio_by_day[d]:.6f}" for d in near]


def render_report(
    results: Mapping[str, SymbolAudit],
    skipped_missing: Sequence[str],
    run_id: str,
    thresholds: Mapping[str, float],
    today: date,
    *,
    top_unexplained: int = 30,
) -> str:
    lines = [
        "# Split-seam audit",
        "",
        "Author: phase 185 plan 15 (ops_seam_audit.py)",
        "Informed by: D-21, D-24, D1 ohlcv_observation (fresh TRADES run and stored corpus), "
        "src/intelligence/bars/seams.py, corporate_actions.py",
        "",
        f"Generated {today.isoformat()} against fetch run {run_id}. Thresholds: "
        + ", ".join(f"{k}={v:g}" for k, v in thresholds.items())
        + ".",
        "",
        "## First-audited names (D-24)",
        "",
    ]
    first = [s for s in _FIRST_NAMES if s in results]
    if not first:
        lines.append("MRNA and ALMS were not part of this run.")
    for symbol in first:
        audit = results[symbol]
        event = _EVENT_DATES[symbol]
        lines.append(f"- {symbol} ({event}): {_verdict(symbol, audit)}")
        lines.append(f"  - common days compared: {audit.n_common_days}; seams: {len(audit.seams)}")
        window = _ratio_window(audit, event)
        if window:
            lines.append("  - stored/fresh close ratio around the date:")
            lines.extend(window)
    audited = {s: a for s, a in results.items() if not a.skipped}
    n_seams = sum(len(a.seams) for a in audited.values())
    n_splits = sum(len(a.splits) for a in audited.values())
    unexplained = [(s, u) for s, a in audited.items() for u in a.unexplained]
    lines += [
        "",
        "## Counts",
        "",
        f"- names audited: {len(audited)}",
        f"- seams found: {n_seams}",
        f"- splits inferred (corporate_action rows): {n_splits}",
        f"- unexplained disagreements: {len(unexplained)}",
        f"- names skipped for missing fresh data or overlap: "
        f"{len(skipped_missing) + sum(1 for a in results.values() if a.skipped)}",
        "",
        "## Splits inferred",
        "",
        "| Symbol | Last old-scale day | Kind | Factor | Run days |",
        "| --- | --- | --- | --- | --- |",
    ]
    for symbol in sorted(audited):
        for s in audited[symbol].splits:
            lines.append(
                f"| {symbol} | {s.effective_date} | {s.kind} | {s.factor:g} | {s.evidence_days} |"
            )
    lines += [
        "",
        f"## Unexplained disagreements (top {top_unexplained} by run length)",
        "",
        "| Symbol | Run | Factor | Days | Max rel dev | Reason |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for symbol, item in sorted(unexplained, key=lambda x: -x[1].seam.n_days)[:top_unexplained]:
        seam = item.seam
        lines.append(
            f"| {symbol} | {seam.start} to {seam.end} | {seam.factor:.6f} | {seam.n_days} "
            f"| {seam.max_rel_dev:.4f} | {item.reason} |"
        )
    lines += ["", "## Skipped names", ""]
    skipped = sorted(skipped_missing) + sorted(s for s, a in results.items() if a.skipped)
    lines.append(", ".join(skipped) if skipped else "none")
    reasons = {s: a.skipped for s, a in results.items() if a.skipped}
    if reasons:
        lines += [
            "",
            "Overlap skips: " + "; ".join(f"{s}: {r}" for s, r in sorted(reasons.items())),
        ]
    return "\n".join(lines) + "\n"


# --- main ------------------------------------------------------------------------


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--fetch-run-id", required=True, help="bootstrap fresh-fetch run to audit")
    parser.add_argument("--symbols", nargs="*", default=None)
    parser.add_argument("--apply", action="store_true", help="write (default is a dry run)")
    parser.add_argument("--report", type=Path, default=None)
    return parser.parse_args()


async def _run(args: argparse.Namespace) -> int:
    settings = Settings()
    dsn = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
    pool = await asyncpg.create_pool(dsn=dsn, min_size=1, max_size=2)
    try:
        async with pool.acquire() as conn:
            apr = await load_apr_dict_async(conn, ["threshold.seam.%", "threshold.bar_scrub.%"])
            thresholds = {
                _APR_REL_TOL: float(apr[_APR_REL_TOL]),
                _APR_MIN_RUN: int(apr[_APR_MIN_RUN]),
                _APR_SNAP: float(apr[_APR_SNAP]),
            }
            quarantine = _RULE in json.loads(apr[_APR_QUARANTINE])
            run_symbols = [
                r[0]
                for r in await conn.fetch(
                    "SELECT DISTINCT symbol FROM ohlcv_request WHERE fetch_run_id = $1::uuid "
                    "AND what_to_show = 'TRADES' AND outcome = 'bars'",
                    args.fetch_run_id,
                )
            ]
            universe = [
                r[0]
                for r in await conn.fetch(
                    "SELECT symbol FROM instruments WHERE compute_eligible_1d AND is_active"
                )
            ]
        wanted = set(args.symbols) if args.symbols else set(universe)
        no_fresh = sorted(wanted - set(run_symbols))
        symbols = order_symbols(wanted & set(run_symbols))
        print(f"names: {len(symbols)}; without fresh TRADES in the run: {len(no_fresh)}")

        batch_id = ""
        if args.apply:
            async with pool.acquire() as conn:
                batch_id = await open_batch(
                    conn,
                    stage="seam_audit",
                    rule_version=_RULE_VERSION,
                    apr_snapshot={**thresholds, _APR_QUARANTINE: quarantine},
                    n_symbols=len(symbols),
                    detail={"fetch_run_id": args.fetch_run_id, "limited": bool(args.symbols)},
                )
        results: dict[str, SymbolAudit] = {}
        try:
            for symbol in symbols:
                async with pool.acquire() as conn:
                    stored, stamps = await _stored(conn, symbol)
                    fresh, fresh_ids = await _fresh(conn, symbol, args.fetch_run_id)
                    legacy_ids = await _legacy_request_ids(conn, symbol)
                    audit = audit_symbol(
                        stored,
                        fresh,
                        rel_tol=thresholds[_APR_REL_TOL],
                        min_run=int(thresholds[_APR_MIN_RUN]),
                        ratio_snap_tol=thresholds[_APR_SNAP],
                    )
                    results[symbol] = audit
                    if args.apply and not audit.skipped:
                        await apply_symbol(
                            conn,
                            symbol=symbol,
                            audit=audit,
                            stored_timestamps=stamps,
                            evidence_request_ids=[*fresh_ids, *legacy_ids],
                            batch_id=batch_id,
                            quarantine=quarantine,
                        )
                if audit.splits or audit.unexplained:
                    print(
                        f"{symbol}: {len(audit.splits)} splits, "
                        f"{len(audit.unexplained)} unexplained"
                    )
        except Exception as error:
            if args.apply:
                async with pool.acquire() as conn:
                    await close_batch(conn, batch_id, status="failed", detail={"error": str(error)})
            raise

        audited = [a for a in results.values() if not a.skipped]
        counts = {
            "names_audited": len(audited),
            "seams": sum(len(a.seams) for a in audited),
            "splits": sum(len(a.splits) for a in audited),
            "unexplained": sum(len(a.unexplained) for a in audited),
            "skipped": len(no_fresh) + len(results) - len(audited),
        }
        print(json.dumps(counts))
        report = render_report(
            results, no_fresh, args.fetch_run_id, thresholds, datetime.now(UTC).date()
        )
        if args.report is not None:
            args.report.write_text(report)
            print(f"report written: {args.report}")
        if args.apply:
            async with pool.acquire() as conn:
                for name, value in counts.items():
                    await emit_integrity_fact_async(
                        conn, _MONITOR_TYPE, None, name, float(value), None, True, None
                    )
                if not args.symbols:
                    await emit_integrity_fact_async(
                        conn, _MONITOR_TYPE, None, "seam_audit_complete", 1.0, None, True, None
                    )
                await close_batch(conn, batch_id, status="completed", detail=counts)
        return 0
    finally:
        await pool.close()


def main() -> None:
    sys.exit(asyncio.run(_run(_parse_args())))


if __name__ == "__main__":
    main()
