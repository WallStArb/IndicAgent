"""Build the `ops_source_policy --plan` files of the Massive switch (todo 600, admission step 7).

Design: docs/plans/2026-11-10-massive-admission-db-design.md section 8 step 7 (stage 1) and
section 8b (stage 2); runbook docs/operations/massive-step7-runbook.md. Read-only: this script
reads the live policy rows, the identity gap list and (1d) the raw fingerprint, and writes one
JSON plan per (stage, timeframe). `ops_source_policy --plan FILE` (dry run, then --apply) is the
writer; this script never writes the database.

The defaults, per stage (5m and 1d alike; the 2003-09-10 boundary keeps the IBKR-only daily
history before Massive's first file under IBKR, where no other vendor answers):

  stage 1  [1990-01-01, 2003-09-10) ibkr | [2003-09-10, 2016-01-04) massive, no fallback |
           [2016-01-04, open) the live post-2016 default, copied unchanged (alpaca, ibkr)
  stage 2  [1990-01-01, 2003-09-10) ibkr | [2003-09-10, archive end) massive, no fallback |
           [archive end, open) alpaca, no fallback (IBKR retired from selection)

No fallback under Massive (ruling 2): a fallback vendor would judge Massive incomplete against
its own zero-volume bars and take whole sessions. Names and spans on the identity gap list keep
an incumbent through symbol rows over the part of the Massive span they cover: IBKR before
2016-01-04; from 2016-01-04 Alpaca in stage 2, except `asset_class_outside_vendor` names
(futures, fx), which no Massive or Alpaca kind serves and which keep IBKR.

Live symbol rows are named explicitly (ops_source_policy requires it for 1d, and for 5m an
implicit plan would retire every symbol row unread). Stage 1 keeps every live row (the 2016+ rows
are outside its change; --plan refuses a kept row that overlaps a new row of its name). Stage 2
retires each: `replaced` when its name gets new rows, else `superseded_by_default` (IBKR leaves
selection). The 1d plan pins the two live default ids and
carries the raw fingerprint through the latest end of any symbol row, as --plan requires.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import hashlib
import json
import sys
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

project_root = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(project_root))

import asyncpg  # noqa: E402

from scripts.ops.bars.ops_source_policy import parse_plan, read_raw_fingerprint  # noqa: E402
from src.config.settings import Settings  # noqa: E402
from src.intelligence.bars.ticker_entity_map import MASSIVE_ARCHIVE_START  # noqa: E402
from src.intelligence.bars.vendor_arbitration import SEAM as ALPACA_SEAM  # noqa: E402

FAR_PAST = date(1990, 1, 1)
# The first session after the archive's last file (2026-11-09): Alpaca's nightly from here on.
ARCHIVE_END = date(2026, 11, 10)
OUTSIDE_VENDOR = "asset_class_outside_vendor"  # gap reason: no Massive or Alpaca kind serves it
TIMEFRAMES = ("5m", "1d")
STAGES = (1, 2)

_LIVE_SQL = """
SELECT policy_id::text AS policy_id, symbol, valid_from, valid_to, primary_source,
       fallback_source, reason, evidence::text AS evidence
FROM bar_source_policy_current WHERE timeframe = $1
ORDER BY symbol NULLS FIRST, valid_from
"""


@dataclass(frozen=True)
class GapRow:
    """One identity gap-list row: the whole Massive span of a name (instrument scope) or a dated
    span [valid_from, valid_to) of it."""

    symbol: str
    scope: str
    reason: str
    valid_from: date | None
    valid_to: date | None


@dataclass(frozen=True)
class LiveRow:
    """A bar_source_policy_current row as read (symbol None for a default)."""

    policy_id: str
    symbol: str | None
    valid_from: date
    valid_to: date | None
    primary: str
    fallback: str | None
    reason: str
    evidence: dict[str, Any]


def read_gap_list(path: Path) -> list[GapRow]:
    def day(text: str) -> date | None:
        return date.fromisoformat(text) if text else None

    with path.open(newline="") as handle:
        return [
            GapRow(r["symbol"], r["scope"], r["reason"], day(r["valid_from"]), day(r["valid_to"]))
            for r in csv.DictReader(handle)
        ]


def massive_span(stage: int, archive_end: date) -> tuple[date, date]:
    """[first, end) of the span Massive serves by default in the stage."""
    return MASSIVE_ARCHIVE_START, ALPACA_SEAM if stage == 1 else archive_end


def _merge(spans: Iterable[tuple[date, date]]) -> list[tuple[date, date]]:
    out: list[tuple[date, date]] = []
    for start, end in sorted(spans):
        if out and start <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], end))
        else:
            out.append((start, end))
    return out


def incumbent_rows(
    gaps: Sequence[GapRow], stage: int, archive_end: date, evidence: Mapping[str, Any]
) -> list[dict[str, Any]]:
    """The symbol rows that keep an incumbent over each gap-listed span inside the Massive span:
    the spans of a name merged, clipped to the Massive span and cut at 2016-01-04 (IBKR before
    it; Alpaca after it, except names outside every vendor kind, which keep IBKR)."""
    first, end = massive_span(stage, archive_end)
    by_symbol: dict[str, list[tuple[date, date]]] = defaultdict(list)
    reasons: dict[str, set[str]] = defaultdict(set)
    for g in gaps:
        start = max(g.valid_from or first, first)
        stop = min(g.valid_to or end, end)
        if start < stop:
            by_symbol[g.symbol].append((start, stop))
            reasons[g.symbol].add(g.reason)
    rows = []
    for symbol in sorted(by_symbol):
        outside = OUTSIDE_VENDOR in reasons[symbol]
        for start, stop in _merge(by_symbol[symbol]):
            cuts = [(start, min(stop, ALPACA_SEAM)), (max(start, ALPACA_SEAM), stop)]
            for i, (a, b) in enumerate(cuts):
                if a >= b:
                    continue
                primary = "ibkr" if i == 0 or outside else "alpaca"
                rows.append(
                    {
                        "symbol": symbol,
                        "valid_from": a.isoformat(),
                        "valid_to": b.isoformat(),
                        "primary": primary,
                        "fallback": None,
                        "evidence": {**evidence, "gap_reasons": sorted(reasons[symbol])},
                    }
                )
    return rows


def defaults_for(stage: int, live_defaults: Sequence[LiveRow], archive_end: date) -> list[dict]:
    """The new defaults (module docstring). Stage 1 copies the live open default unchanged."""
    first, end = massive_span(stage, archive_end)
    head = [
        {"valid_from": FAR_PAST.isoformat(), "valid_to": first.isoformat(), "primary": "ibkr"},
        {"valid_from": first.isoformat(), "valid_to": end.isoformat(), "primary": "massive"},
    ]
    if stage == 2:
        return [*head, {"valid_from": end.isoformat(), "valid_to": None, "primary": "alpaca"}]
    open_rows = [r for r in live_defaults if r.valid_to is None]
    if len(open_rows) != 1 or open_rows[0].valid_from != ALPACA_SEAM:
        raise ValueError(f"expected one live open default from {ALPACA_SEAM}, got {open_rows}")
    tail = open_rows[0]
    return [
        *head,
        {
            "valid_from": ALPACA_SEAM.isoformat(),
            "valid_to": None,
            "primary": tail.primary,
            "fallback": tail.fallback,
        },
    ]


def build_plan(
    *,
    stage: int,
    timeframe: str,
    live: Sequence[LiveRow],
    gaps: Sequence[GapRow],
    gap_list: Mapping[str, str],
    archive_end: date = ARCHIVE_END,
) -> dict[str, Any]:
    """The plan JSON for one (stage, timeframe), without the 1d raw fingerprint (the caller adds
    it once the latest symbol-row end, `through_needed`, is known)."""
    if stage not in STAGES or timeframe not in TIMEFRAMES:
        raise ValueError(f"stage {stage} / timeframe {timeframe} is not a Massive switch plan")
    reason = (
        f"Massive switch stage {stage} (todo 600 admission step 7, design section "
        f"{'8 step 7' if stage == 1 else '8b'})"
    )
    evidence = {
        "stage": stage,
        "design": "docs/plans/2026-11-10-massive-admission-db-design.md",
        "runbook": "docs/operations/massive-step7-runbook.md",
        "gap_list": dict(gap_list),
    }
    defaults = [r for r in live if r.symbol is None]
    new_rows = incumbent_rows(gaps, stage, archive_end, {"gap_list": dict(gap_list)})
    new_symbols = {r["symbol"] for r in new_rows}
    retire, keep = [], []
    for row in (r for r in live if r.symbol is not None):
        if stage == 1:
            keep.append(
                {
                    "policy_id": row.policy_id,
                    "symbol": row.symbol,
                    "reason": "outside the Massive span; stage 1 leaves 2016+ rows unchanged",
                    "valid_from": row.valid_from.isoformat(),
                    "valid_to": _iso(row.valid_to),
                }
            )
        else:
            disposition = "replaced" if row.symbol in new_symbols else "superseded_by_default"
            retire.append(_retired(row, disposition, stage))
    plan: dict[str, Any] = {
        "timeframe": timeframe,
        # a boundary of the new defaults (parse_plan); the one both stages share
        "seam": MASSIVE_ARCHIVE_START.isoformat(),
        "reason": reason,
        "evidence": evidence,
        "retire_defaults": True,
        "retire_default_ids": sorted(r.policy_id for r in defaults),
        "defaults": defaults_for(stage, defaults, archive_end),
        "symbol_rows": sorted(new_rows, key=lambda r: (r["symbol"], r["valid_from"])),
        "retire_symbol_rows": retire,
        "keep_symbol_rows": keep,
    }
    return plan


def through_needed(plan: Mapping[str, Any]) -> date:
    """The latest end of any new symbol row: the 1d raw fingerprint must reach it (parse_plan)."""
    ends = [r["valid_to"] for r in plan["symbol_rows"] if r["valid_to"]]
    return date.fromisoformat(max(ends, default=plan["seam"]))


def _retired(row: LiveRow, disposition: str, stage: int) -> dict[str, Any]:
    return {
        "policy_id": row.policy_id,
        "symbol": row.symbol,
        "disposition": disposition,
        "evidence": {
            "stage": stage,
            "was": [row.valid_from.isoformat(), _iso(row.valid_to)],
            "primary": row.primary,
        },
    }


def _iso(day: date | None) -> str | None:
    return day.isoformat() if day else None


def file_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


async def _read_live(conn: Any, timeframe: str) -> list[LiveRow]:
    return [
        LiveRow(
            r["policy_id"],
            r["symbol"],
            r["valid_from"],
            r["valid_to"],
            r["primary_source"],
            r["fallback_source"],
            r["reason"],
            json.loads(r["evidence"]),
        )
        for r in await conn.fetch(_LIVE_SQL, timeframe)
    ]


async def _main(args: argparse.Namespace) -> int:
    gap_path = Path(args.gap_list)
    gap_list = {"path": str(gap_path), "sha256": file_digest(gap_path)}
    settings = Settings()
    conn = await asyncpg.connect(
        settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
    )
    try:
        live = await _read_live(conn, args.timeframe)
        plan = build_plan(
            stage=args.stage,
            timeframe=args.timeframe,
            live=live,
            gaps=read_gap_list(gap_path),
            gap_list=gap_list,
            archive_end=date.fromisoformat(args.archive_end),
        )
        if args.timeframe == "1d":
            plan["raw_fingerprint"] = await read_raw_fingerprint(conn, through_needed(plan))
    finally:
        await conn.close()
    parse_plan(plan)  # the writer's own validation, before anyone reviews the file
    out = Path(args.out)
    out.write_text(json.dumps(plan, indent=2, sort_keys=True) + "\n")
    rows = plan["symbol_rows"]
    print(
        f"stage {args.stage} {args.timeframe}: {len(plan['defaults'])} defaults, "
        f"{len(rows)} symbol rows on {len({r['symbol'] for r in rows})} names "
        f"({sum(r['primary'] == 'ibkr' for r in rows)} ibkr, "
        f"{sum(r['primary'] == 'alpaca' for r in rows)} alpaca), "
        f"retire {len(plan['retire_symbol_rows'])}, keep {len(plan['keep_symbol_rows'])}; "
        f"wrote {out} (sha256 {file_digest(out)})"
    )
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--stage", type=int, choices=STAGES, required=True)
    parser.add_argument("--timeframe", choices=TIMEFRAMES, required=True)
    parser.add_argument(
        "--gap-list",
        required=True,
        help="the identity map's gap_list.csv the load sweep used (pin it; never 'newest')",
    )
    parser.add_argument("--archive-end", default=ARCHIVE_END.isoformat())
    parser.add_argument("--out", required=True)
    return asyncio.run(_main(parser.parse_args(argv)))


if __name__ == "__main__":
    sys.exit(main())
