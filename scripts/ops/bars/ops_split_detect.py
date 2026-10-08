"""Record splits found in the nightly overlap, re-fetch their history, re-derive it (plan 185-22, D-21).

For each fetch run it is given, services/split_detection.detect_overlap_splits compares the run's
fresh 1d observations with the earlier ones for the same dates. A constant ratio is a split:

1. corporate_action gets one row (inferred_by nightly_overlap, evidence request ids), idempotent per
   (symbol, effective date, factor), in a transaction under bar_derivation_writer;
2. the symbol's full 1d history is re-fetched into D1 (ibkr_history_fetcher.py with the symbols
   named and a large --overlap-sessions re-asks sessions D1 already answers) so every
   observation is on the new scale;
3. the daily stage re-derives it, which clears pre_split_unrefetched because a fetch now exists
   after the action was recorded. The order matters: D2 counts only a fetch made after the
   recording as post-split.

A non-constant difference is never recorded as a split: it becomes an integrity fact
(bar_split_detection) for a human. A constant ratio that is no recognised split ratio
(recognised_split_ratio, APR infra.backfill.split_ratio_*; plan 185-51, todo 515: CTVA's 39/7
spin-off rescale) is never a split either: it is an integrity fact unclassified_rescale and the
name is held (services/bar_hold.py), so the daily stage applies no rewrite until a decision
releases it; the same rescale seen again is not held or reported twice. A failed re-fetch or
derivation exits non-zero; D2 keeps flagging the symbol's older bars until it succeeds, and
`--refetch-only SYM,SYM` repeats steps 2 and 3 by hand.

Sanctioned corrections (plan 185-51). corporate_action stays append-only; every correction is a
new row (inferred_by operator), a dry run by default, and --apply writes it in one transaction
under bar_derivation_writer:

- --supersede ID[,ID...] --effective-date D --factor F --evidence REQ[,REQ...] --reason TEXT:
  one correct row superseding the first id and a void row for each further id, so one current
  row remains. The factor must be a recognised split ratio, the ids current rows of one symbol
  and the evidence requests that symbol's (they are the answers on the new scale: d2-v2 counts
  them as current). effective_date is the last day on the old scale (migration 400).
- --void ID --reason TEXT: retract a row (a void row supersedes it; the current view hides both).
- --hold-rescale ID --reason TEXT: the row was no split. Void it and hold its symbol as an
  unclassified rescale, with the vendors' ratios over the affected dates.
- --release-hold HOLD_ID --reason TEXT: end a hold (a release row).

The fetcher runs this sequence itself, in-process and under its own lock, after every run that
fetched 1d (plan 189-10, todo 507: its update lane's overlap escalation records with
record_split, re-fetches on the open connection, then derives). This script is the by-hand path
for a fetch run judged later or a split to re-fetch again. Its re-fetch takes FetcherLock like
every IBKR history fetch (plan 189-08), so while a fetcher run holds the lock it is refused: the
refusal line maps to exit 3 (LOCK_HELD_EXIT), the derivation is skipped, and the split stays
recorded and loudly quarantined (pre_split_unrefetched) until a rerun after the fetcher exits.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from datetime import date
from pathlib import Path
from typing import Any
from uuid import uuid4

import asyncpg
import structlog

from scripts.infrastructure.backfill._fetcher_lock import LOCK_HELD_MESSAGE
from services import bar_hold
from services.split_detection import DetectedSplit, detect_overlap_splits
from src.intelligence.bars.corporate_actions import SplitRatioRule, recognised_split_ratio

_logger = structlog.get_logger(__name__)

_INFERRED_BY = "nightly_overlap"
_FACT_MONITOR = "bar_split_detection"
_RESCALE_METRIC = "unclassified_rescale"
_RECORDED_BY = "ops_split_detect"
_TIMEFRAME = "1d"
_REPO_ROOT = Path(__file__).resolve().parents[3]
_FETCHER = _REPO_ROOT / "scripts" / "infrastructure" / "backfill" / "ibkr_history_fetcher.py"
# Exit code for a re-fetch the fetcher refused because its lock is held (the fetcher itself
# exits 0 and prints LOCK_HELD_MESSAGE). Non-zero, so the derivation is skipped.
LOCK_HELD_EXIT = 3
# Sessions per year used to turn APR split_refetch_years into --overlap-sessions: a calendar
# fact (the NYSE trades about 252 days a year), with slack so the window clears the listing.
_SESSIONS_PER_YEAR = 260

# The split recognition rule (migration 461); the fetcher's overlap judge reads the same keys.
SPLIT_RULE_KEYS = (
    "infra.backfill.split_ratio_max_numerator",
    "infra.backfill.split_ratio_max_denominator",
    "infra.backfill.split_ratio_rel_tol",
)

_APR_KEYS = (
    "threshold.seam.rel_tol",
    "threshold.seam.min_run",
    "threshold.seam.ratio_snap_tol",
    "infra.bar_derivation.split_refetch_years",
    *SPLIT_RULE_KEYS,
)

# Current rows of the symbol on or after the detection's last old-scale overlap date: a split
# the overlap shows happened after that date, so a current row of the same factor there (an
# earlier detection, or an operator correction at the true date) is the same event.
_EXISTING_SQL = """
SELECT action_id::text AS action_id, factor, effective_date, inferred_by
FROM corporate_action_current
WHERE symbol = $1 AND effective_date >= $2
"""

_INSERT_SQL = """
INSERT INTO corporate_action
    (symbol, action_type, effective_date, factor, inferred_by, evidence_request_ids,
     detail, supersedes)
VALUES ($1, $2, $3, $4, 'nightly_overlap', $5::uuid[], $6::text::jsonb, $7::uuid)
"""

# A by-hand correction or void (plan 185-51): inferred_by operator, the id chosen here so the
# void rows can name the correcting row. Detail goes in as text: one JSON encoding whatever
# codecs the connection carries.
_INSERT_OPERATOR_SQL = """
INSERT INTO corporate_action
    (action_id, symbol, action_type, effective_date, factor, inferred_by, evidence_request_ids,
     detail, supersedes)
VALUES ($1::uuid, $2, $3, $4, $5, 'operator', $6::uuid[], $7::text::jsonb, $8::uuid)
"""

_CURRENT_ROWS_SQL = """
SELECT action_id::text AS action_id, symbol, action_type, effective_date, factor
FROM corporate_action_current
WHERE action_id = ANY($1::uuid[])
"""

_EVIDENCE_SQL = """
SELECT request_id::text AS request_id FROM ohlcv_request
WHERE symbol = $1 AND request_id = ANY($2::uuid[])
"""


def split_rule_from_apr(apr: Mapping[str, Any]) -> SplitRatioRule:
    """The recognition rule from APR (raises KeyError on a missing key: migration 461 seeds them)."""
    return SplitRatioRule(
        max_numerator=int(apr["infra.backfill.split_ratio_max_numerator"]),
        max_denominator=int(apr["infra.backfill.split_ratio_max_denominator"]),
        rel_tol=float(apr["infra.backfill.split_ratio_rel_tol"]),
    )


async def record_split(conn: Any, split: DetectedSplit) -> bool:
    """Insert the split unless it is already recorded; True if a row was added.

    Already recorded: a current row of the same factor dated on or after the detection's
    effective date (plan 185-51: re-judging ETHA's 2026-10-08 run must not bring back the row
    the 2026-10-05 correction voided). A different factor on the same date from an earlier
    overlap detection is superseded rather than edited (corporate_action is append-only).
    Refuses to record a split without evidence.
    """
    if not split.request_ids:
        raise ValueError(f"{split.symbol}: refusing to record a split without evidence request ids")
    async with conn.transaction():
        await conn.execute("SET LOCAL ROLE bar_derivation_writer")
        existing = await conn.fetch(_EXISTING_SQL, split.symbol, split.effective_date)
        if any(abs(float(r["factor"]) - split.factor) < 1e-9 for r in existing):
            return False
        replaced = next(
            (
                r["action_id"]
                for r in existing
                if r["effective_date"] == split.effective_date and r["inferred_by"] == _INFERRED_BY
            ),
            None,
        )
        await conn.execute(
            _INSERT_SQL,
            split.symbol,
            "split" if split.factor > 1.0 else "reverse_split",
            split.effective_date,
            split.factor,
            list(split.request_ids),
            json.dumps({"detected_by": "overlap", "n_evidence_requests": len(split.request_ids)}),
            replaced,
        )
    return True


async def act_on_detections(
    conn: Any,
    detected: Sequence[DetectedSplit],
    *,
    split_rule: SplitRatioRule,
    report_unexplained: Callable[[DetectedSplit], None],
    report_rescale: Callable[[DetectedSplit], None],
    recorded_by: str,
    fetch_run_id: str | None = None,
) -> dict[str, str]:
    """Record, hold or report each detection; the reason per symbol that needs a re-fetch.

    A split is recorded (split_recorded, only when new). An unclassified rescale is held
    (services/bar_hold.record_hold, with the vendors' ratios over the overlap dates) and
    reported as an integrity fact, only when new (unclassified_rescale); never a corporate
    action. An unexplained difference is reported (unexplained_difference).
    """
    reasons: dict[str, str] = {}
    for split in detected:
        if split.unexplained:
            report_unexplained(split)
            reasons[split.symbol] = "unexplained_difference"
        elif split.unclassified:
            first = split.first_date or split.effective_date
            ratios = await bar_hold.vendor_rescale_ratios(
                conn, split.symbol, first, split.effective_date, rel_tol=split_rule.rel_tol
            )
            hold_id = await bar_hold.record_hold(
                conn,
                symbol=split.symbol,
                timeframe=_TIMEFRAME,
                reason=bar_hold.REASON_UNCLASSIFIED_RESCALE,
                factor=split.factor,
                first_affected_date=first,
                last_affected_date=split.effective_date,
                detail={
                    "detected_by": "overlap",
                    "fetch_run_id": fetch_run_id,
                    "evidence_request_ids": list(split.request_ids),
                    "vendor_ratios": ratios,
                    "rule": {
                        "max_numerator": split_rule.max_numerator,
                        "max_denominator": split_rule.max_denominator,
                        "rel_tol": split_rule.rel_tol,
                    },
                },
                recorded_by=recorded_by,
                rel_tol=split_rule.rel_tol,
            )
            if hold_id is not None:
                report_rescale(split)
                reasons[split.symbol] = bar_hold.REASON_UNCLASSIFIED_RESCALE
        elif await record_split(conn, split):
            reasons[split.symbol] = "split_recorded"
    return reasons


# -- sanctioned corrections (plan 185-51) -----------------------------------------------------


def _action_type(factor: float) -> str:
    return "split" if factor > 1.0 else "reverse_split"


async def _current_rows(conn: Any, action_ids: Sequence[str]) -> list[dict[str, Any]]:
    rows = {r["action_id"]: dict(r) for r in await conn.fetch(_CURRENT_ROWS_SQL, list(action_ids))}
    missing = [i for i in action_ids if i not in rows]
    if missing:
        raise LookupError(
            f"not current corporate_action rows (superseded, void or unknown): {missing}"
        )
    return [rows[i] for i in action_ids]


def _void_row(row: Mapping[str, Any], reason: str, **detail: Any) -> dict[str, Any]:
    return {
        "action_id": str(uuid4()),
        "symbol": row["symbol"],
        "action_type": "void",
        "effective_date": row["effective_date"].isoformat(),
        "factor": float(row["factor"]),
        "evidence_request_ids": [],
        "detail": {"reason": reason, **detail},
        "supersedes": row["action_id"],
    }


async def _insert_operator_rows(conn: Any, rows: Sequence[Mapping[str, Any]]) -> None:
    for row in rows:
        await conn.execute(
            _INSERT_OPERATOR_SQL,
            row["action_id"],
            row["symbol"],
            row["action_type"],
            date.fromisoformat(row["effective_date"]),
            row["factor"],
            list(row["evidence_request_ids"]),
            json.dumps(row["detail"], sort_keys=True),
            row["supersedes"],
        )


def _need_reason(reason: str) -> None:
    if not reason.strip():
        raise ValueError("a correction needs a reason (its evidence, in words)")


async def supersede(
    conn: Any,
    *,
    action_ids: Sequence[str],
    effective_date: date,
    factor: float,
    evidence_request_ids: Sequence[str],
    reason: str,
    split_rule: SplitRatioRule,
    apply: bool,
) -> dict[str, Any]:
    """Replace current rows of one symbol with one correct row; the plan, written when apply.

    The correct row supersedes action_ids[0]; each further id gets a void row naming it.
    """
    _need_reason(reason)
    if not action_ids:
        raise ValueError("--supersede needs at least one action id")
    ratio = recognised_split_ratio(factor, split_rule)
    if ratio is None:
        raise ValueError(f"factor {factor!r} is not a recognised split ratio under {split_rule}")
    if not evidence_request_ids:
        raise ValueError("a correcting row needs evidence request ids (answers on the new scale)")
    rows = await _current_rows(conn, action_ids)
    symbols = {r["symbol"] for r in rows}
    if len(symbols) != 1:
        raise ValueError(f"--supersede takes rows of one symbol, got {sorted(symbols)}")
    (symbol,) = symbols
    found = {
        r["request_id"] for r in await conn.fetch(_EVIDENCE_SQL, symbol, list(evidence_request_ids))
    }
    unknown = sorted(set(evidence_request_ids) - found)
    if unknown:
        raise ValueError(f"evidence requests not found for {symbol}: {unknown}")
    correct = {
        "action_id": str(uuid4()),
        "symbol": symbol,
        "action_type": _action_type(ratio),
        "effective_date": effective_date.isoformat(),
        "factor": ratio,
        "evidence_request_ids": list(evidence_request_ids),
        "detail": {"reason": reason, "voids": list(action_ids[1:])},
        "supersedes": action_ids[0],
    }
    voids = [_void_row(r, reason, superseded_by=correct["action_id"]) for r in rows[1:]]
    plan = {
        "apply": apply,
        "replaces": rows,
        "insert": [correct, *voids],
        "current_after": [correct["action_id"]],
    }
    if apply:
        async with conn.transaction():
            await conn.execute("SET LOCAL ROLE bar_derivation_writer")
            await _insert_operator_rows(conn, plan["insert"])
    return plan


async def void(conn: Any, *, action_id: str, reason: str, apply: bool) -> dict[str, Any]:
    """Retract one current row with a void row; the plan, written when apply."""
    _need_reason(reason)
    (row,) = await _current_rows(conn, [action_id])
    plan = {"apply": apply, "replaces": [row], "insert": [_void_row(row, reason)]}
    if apply:
        async with conn.transaction():
            await conn.execute("SET LOCAL ROLE bar_derivation_writer")
            await _insert_operator_rows(conn, plan["insert"])
    return plan


async def hold_rescale(
    conn: Any, *, action_id: str, reason: str, split_rule: SplitRatioRule, apply: bool
) -> dict[str, Any]:
    """A recorded split that was no split: void it and hold its symbol as an unclassified
    rescale (factor and effective date from the row, the affected span and the vendors' ratios
    from D1 against the canonical bars). One transaction; the plan, written when apply."""
    _need_reason(reason)
    (row,) = await _current_rows(conn, [action_id])
    last = row["effective_date"]
    ratios = await bar_hold.vendor_rescale_ratios(
        conn, row["symbol"], None, last, rel_tol=split_rule.rel_tol
    )
    firsts = [date.fromisoformat(r["first_date"]) for r in ratios.values() if r["first_date"]]
    first = min(firsts, default=last)
    void_row = _void_row(row, reason, held_as=bar_hold.REASON_UNCLASSIFIED_RESCALE)
    hold = {
        "symbol": row["symbol"],
        "factor": float(row["factor"]),
        "first_affected_date": first.isoformat(),
        "last_affected_date": last.isoformat(),
        "action_id": action_id,
        "detail": {"reason": reason, "voided_action_id": action_id, "vendor_ratios": ratios},
    }
    plan = {"apply": apply, "replaces": [row], "void": void_row, "hold": hold}
    if apply:
        async with conn.transaction():
            await conn.execute("SET LOCAL ROLE bar_derivation_writer")
            await _insert_operator_rows(conn, [void_row])
            plan["hold_id"] = await bar_hold.record_hold(
                conn,
                symbol=row["symbol"],
                timeframe=_TIMEFRAME,
                reason=bar_hold.REASON_UNCLASSIFIED_RESCALE,
                factor=float(row["factor"]),
                first_affected_date=first,
                last_affected_date=last,
                detail=hold["detail"],
                recorded_by=_RECORDED_BY,
                rel_tol=split_rule.rel_tol,
                action_id=action_id,
            )
    return plan


async def process(
    conn: Any,
    run_ids: Sequence[str],
    *,
    rel_tol: float,
    min_run: int,
    ratio_snap_tol: float,
    split_rule: SplitRatioRule,
    refetch: Callable[[list[str]], int],
    derive: Callable[[list[str]], int],
    report_unexplained: Callable[[DetectedSplit], None],
    report_rescale: Callable[[DetectedSplit], None],
) -> dict[str, Any]:
    """Detect over `run_ids`, record splits and hold unclassified rescales, then re-fetch and
    re-derive the recorded symbols (a held name is not re-derived: the daily stage skips it)."""
    reasons: dict[str, str] = {}
    for run_id in run_ids:
        detected = await detect_overlap_splits(
            conn,
            fetch_run_id=run_id,
            rel_tol=rel_tol,
            min_run=min_run,
            ratio_snap_tol=ratio_snap_tol,
            split_rule=split_rule,
        )
        reasons.update(
            await act_on_detections(
                conn,
                detected,
                split_rule=split_rule,
                report_unexplained=report_unexplained,
                report_rescale=report_rescale,
                recorded_by=_RECORDED_BY,
                fetch_run_id=run_id,
            )
        )

    def having(reason: str) -> list[str]:
        return sorted(s for s, r in reasons.items() if r == reason)

    symbols = having("split_recorded")
    returncode = 0
    if symbols:
        returncode = refetch(symbols) or derive(symbols)
    return {
        "recorded": symbols,
        "unexplained": having("unexplained_difference"),
        "held": having(bar_hold.REASON_UNCLASSIFIED_RESCALE),
        "returncode": returncode,
    }


def refetch_command(symbols: Sequence[str], *, years: int, client_id: int) -> list[str]:
    """The fetcher invocation that re-asks `years` of 1d history for `symbols`.

    Named symbols are asked even when their series is current; --full-scan plans the full
    depth window as the pipeline did, and the overlap re-asks sessions D1 already answers.
    """
    return [
        sys.executable,
        str(_FETCHER),
        "--symbols",
        ",".join(symbols),
        "--timeframes",
        "1d",
        "--dimension",
        "backfill",
        "--client-id",
        str(client_id),
        "--full-scan",
        "--overlap-sessions",
        str(years * _SESSIONS_PER_YEAR),
    ]


def _run(command: list[str]) -> int:
    return subprocess.run(
        command, cwd=str(_REPO_ROOT), env={**os.environ, "PYTHONPATH": str(_REPO_ROOT)}
    ).returncode


def run_refetch(command: list[str], popen: Callable[..., Any] = subprocess.Popen) -> int:
    """Run the fetcher, echoing its output; LOCK_HELD_EXIT when it reports its lock held.
    The fetcher bootstraps its own import path, so no environment is passed."""
    proc = popen(
        command,
        cwd=str(_REPO_ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    lock_held = False
    assert proc.stdout is not None
    for line in proc.stdout:
        print(line, end="")
        lock_held = lock_held or line.strip() == LOCK_HELD_MESSAGE
    rc = proc.wait()
    if lock_held:
        _logger.error("split_detection.refetch_refused_lock_held", command=command)
        return LOCK_HELD_EXIT
    return int(rc)


def _derive_command(symbols: Sequence[str]) -> list[str]:
    return [
        sys.executable,
        str(_REPO_ROOT / "services" / "bar_derivation.py"),
        "--stage",
        "daily",
        "--symbols",
        ",".join(symbols),
        "--apply",
    ]


async def _load_apr(conn: Any) -> dict[str, str]:
    rows = await conn.fetch(
        "SELECT config_key, config_value FROM config_state WHERE config_key = ANY($1::text[])",
        list(_APR_KEYS),
    )
    missing = set(_APR_KEYS) - {r["config_key"] for r in rows}
    if missing:
        raise RuntimeError(f"APR keys not set: {sorted(missing)}")
    return {r["config_key"]: r["config_value"] for r in rows}


def _unexplained_reporter(settings: Any) -> Callable[[DetectedSplit], None]:
    def report(split: DetectedSplit) -> None:
        import psycopg

        from src.core.integrity_monitor import emit_integrity_fact_sync

        with psycopg.connect(settings.database_url, autocommit=True) as fact_conn:
            emit_integrity_fact_sync(
                fact_conn,
                _FACT_MONITOR,
                split.symbol,
                "unexplained_overlap_difference",
                float(split.factor),
                1.0,
                False,
                None,
            )
        _logger.warning(
            "split_detection.unexplained",
            symbol=split.symbol,
            effective_date=str(split.effective_date),
            median_ratio=split.factor,
        )

    return report


def rescale_reporter(settings: Any) -> Callable[[DetectedSplit], None]:
    """An unclassified rescale as an integrity fact (metric unclassified_rescale, value the
    measured factor); the hold row carries the dates and the vendors' ratios."""

    def report(split: DetectedSplit) -> None:
        import psycopg

        from src.core.integrity_monitor import emit_integrity_fact_sync

        with psycopg.connect(settings.database_url, autocommit=True) as fact_conn:
            emit_integrity_fact_sync(
                fact_conn,
                _FACT_MONITOR,
                split.symbol,
                _RESCALE_METRIC,
                float(split.factor),
                None,
                False,
                None,
            )
        _logger.error(
            "split_detection.unclassified_rescale_held",
            symbol=split.symbol,
            factor=split.factor,
            first_date=str(split.first_date),
            last_date=str(split.effective_date),
        )

    return report


def _ids(value: str) -> list[str]:
    return [part.strip() for part in value.split(",") if part.strip()]


async def _correct(conn: Any, args: argparse.Namespace, rule: SplitRatioRule) -> dict[str, Any]:
    if args.supersede:
        if args.effective_date is None or args.factor is None or not args.evidence:
            raise SystemExit("--supersede needs --effective-date, --factor and --evidence")
        return await supersede(
            conn,
            action_ids=_ids(args.supersede),
            effective_date=date.fromisoformat(args.effective_date),
            factor=float(args.factor),
            evidence_request_ids=_ids(args.evidence),
            reason=args.reason,
            split_rule=rule,
            apply=args.apply,
        )
    if args.void:
        return await void(conn, action_id=args.void, reason=args.reason, apply=args.apply)
    if args.hold_rescale:
        return await hold_rescale(
            conn, action_id=args.hold_rescale, reason=args.reason, split_rule=rule, apply=args.apply
        )
    plan: dict[str, Any] = {"apply": args.apply, "release": args.release_hold}
    if args.apply:
        plan["release_id"] = await bar_hold.release_hold(
            conn, hold_id=args.release_hold, why=args.reason, recorded_by=_RECORDED_BY
        )
    return plan


async def _main(args: argparse.Namespace) -> int:
    from src.config.settings import Settings

    settings = Settings()
    conn = await asyncpg.connect(settings.database_url)
    try:
        apr = await _load_apr(conn)
        rule = split_rule_from_apr(apr)
        if args.supersede or args.void or args.hold_rescale or args.release_hold:
            print(json.dumps(await _correct(conn, args, rule), default=str, indent=2))
            return 0
        years = int(apr["infra.bar_derivation.split_refetch_years"])

        def refetch(symbols: list[str]) -> int:
            return run_refetch(refetch_command(symbols, years=years, client_id=args.client_id))

        def derive(symbols: list[str]) -> int:
            return _run(_derive_command(symbols))

        if args.refetch_only:
            symbols = sorted({s.strip().upper() for s in args.refetch_only.split(",") if s.strip()})
            rc = refetch(symbols) or derive(symbols)
            print(json.dumps({"refetched": symbols, "returncode": rc}))
            return rc
        report = await process(
            conn,
            args.fetch_run_id,
            rel_tol=float(apr["threshold.seam.rel_tol"]),
            min_run=int(apr["threshold.seam.min_run"]),
            ratio_snap_tol=float(apr["threshold.seam.ratio_snap_tol"]),
            split_rule=rule,
            refetch=refetch,
            derive=derive,
            report_unexplained=_unexplained_reporter(settings),
            report_rescale=rescale_reporter(settings),
        )
        print(json.dumps(report))
        return int(report["returncode"])
    finally:
        await conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--fetch-run-id", action="append", default=[], help="a fetch run to judge (repeatable)"
    )
    parser.add_argument(
        "--refetch-only",
        default=None,
        help="comma-separated symbols: skip detection, re-fetch and re-derive them",
    )
    parser.add_argument("--client-id", type=int, default=45, help="IBKR client id (nightly lane)")
    fix = parser.add_argument_group("sanctioned corrections (dry run unless --apply)")
    fix.add_argument("--supersede", default=None, help="ACTION_ID[,ACTION_ID...]: one correct row")
    fix.add_argument(
        "--effective-date", default=None, help="last day on the old scale (--supersede)"
    )
    fix.add_argument("--factor", default=None, help="stored/fresh split ratio (--supersede)")
    fix.add_argument("--evidence", default=None, help="REQUEST_ID[,...] on the new scale")
    fix.add_argument("--void", default=None, help="ACTION_ID: retract a row")
    fix.add_argument("--hold-rescale", default=None, help="ACTION_ID: no split; void and hold")
    fix.add_argument("--release-hold", default=None, help="HOLD_ID: end a hold")
    fix.add_argument("--reason", default="", help="the correction's evidence, in words")
    fix.add_argument("--apply", action="store_true", help="write (default: print the plan)")
    args = parser.parse_args()
    corrections = [args.supersede, args.void, args.hold_rescale, args.release_hold]
    if sum(bool(c) for c in corrections) > 1:
        parser.error("give one of --supersede, --void, --hold-rescale, --release-hold")
    if not any(corrections) and not args.fetch_run_id and not args.refetch_only:
        parser.error("give at least one --fetch-run-id, or --refetch-only, or a correction")
    return asyncio.run(_main(args))


if __name__ == "__main__":
    sys.exit(main())
