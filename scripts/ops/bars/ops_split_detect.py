"""Sanctioned split corrections: supersede, void, hold and release corporate_action rows (plan 185-51).

The overlap detection and the IBKR re-fetch that fed it were removed 2026-11-13 with the IBKR
lane; what remains is the by-hand correction path.

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
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import Mapping, Sequence
from datetime import date
from typing import Any
from uuid import uuid4

import asyncpg
import structlog

from services import bar_hold
from src.intelligence.bars.corporate_actions import (
    MASSIVE_REFERENCE_SOURCE,
    SplitRatioRule,
    recognised_split_ratio,
)

_logger = structlog.get_logger(__name__)

_INFERRED_BY = "nightly_overlap"
_FACT_MONITOR = "bar_split_detection"
_RESCALE_METRIC = "unclassified_rescale"
_RECORDED_BY = "ops_split_detect"
_TIMEFRAME = "1d"

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
SELECT action_id::text AS action_id, symbol, action_type, effective_date, factor, inferred_by
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
    # An operator row stales the incumbents (corporate_actions.RESTATEMENT_SOURCES); a reference
    # row records a market split they carry adjusted, so replacing it here would change its
    # meaning. It is corrected by --void and a new --apply-massive line (todo 600).
    reference = [r["action_id"] for r in rows if r.get("inferred_by") == MASSIVE_REFERENCE_SOURCE]
    if reference:
        raise ValueError(f"--supersede cannot replace massive_reference rows {reference}")
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
    if row.get("inferred_by") == MASSIVE_REFERENCE_SOURCE:
        # A reference row records a market split, never a vendor rescale to hold (todo 600).
        raise ValueError(f"--hold-rescale cannot take massive_reference row {action_id}")
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


async def _load_apr(conn: Any) -> dict[str, str]:
    rows = await conn.fetch(
        "SELECT config_key, config_value FROM config_state WHERE config_key = ANY($1::text[])",
        list(_APR_KEYS),
    )
    missing = set(_APR_KEYS) - {r["config_key"] for r in rows}
    if missing:
        raise RuntimeError(f"APR keys not set: {sorted(missing)}")
    return {r["config_key"]: r["config_value"] for r in rows}


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
        print(json.dumps(await _correct(conn, args, rule), default=str, indent=2))
        return 0
    finally:
        await conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
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
    if not any(corrections):
        parser.error("give one of --supersede, --void, --hold-rescale, --release-hold")
    return asyncio.run(_main(args))


if __name__ == "__main__":
    sys.exit(main())
