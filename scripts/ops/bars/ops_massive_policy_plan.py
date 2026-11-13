"""Build the `ops_source_policy --plan` files of the Massive switch without IBKR (todo 600 step 7).

Owner rulings 2026-11-13 (todo 600, "IBKR is removed entirely", then "use Massive for every
date it has"): canonical is Massive from its first file (2003-09-10) to the archive end and Alpaca
from the archive end, with no IBKR default, symbol row or fallback anywhere and no fallback at
all. The archive end is the first NYSE session after the manifest's last file day
(``archive_end_of``). Runbook docs/operations/massive-step7-runbook.md. Read-only: this script
reads the live policy rows, the archive manifest, the identity gap list (evidence only) and (1d)
the raw fingerprint, and writes one JSON plan per timeframe. `ops_source_policy --plan FILE` (dry run,
then --apply) is the writer; this script never writes the database.

The defaults per timeframe (``defaults_for``):

  5m, 1d   [1990-01-01, archive end) massive | [archive end, open) alpaca   seam: archive end
  1m, 4h   [1990-01-01, open) massive                                       seam: 1990-01-01

Massive holds no bar before its first file (2003-09-10) and no 1m or 4h bar, so those slots
select nothing and leave canonical by construction. The Massive default still starts at
1990-01-01 because selection raises on a slot no policy row covers (``rank_vendors``,
``resolve_policy``), and IBKR raw stays in the database through the rebuild: a policy that left
the pre-2003 span uncovered would crash the rebuild, where this one keeps selection loud on a real
coverage hole. 15m and 1h are derived and keep their policy.

Every live default of the timeframe is retired by id and every live symbol row (the D-191-Q IBKR
rows) is retired: the plan leaves no IBKR row live. The identity gap list (spans Massive cannot
place) gives Alpaca symbol rows over each span clipped to [2016-01-04, archive end), no fallback
(lead ruling 2026-11-13, ``gap_rows``): those names keep exactly what Alpaca serves today. Before
2016-01-04 a gap span is a gap (no source). The list is pinned by path and sha256 in the
evidence.

Rollback (runbook A9 and every abort rule after C2): --snapshot writes a timeframe's live rows
to JSON before the switch; --restore SNAPSHOT builds the plan that puts the policy back (the
snapshot's defaults, its symbol rows kept or re-inserted, the switch's rows retired).
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import hashlib
import json
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

project_root = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(project_root))

import asyncpg  # noqa: E402

from scripts.ops.bars.ops_source_policy import parse_plan, read_raw_fingerprint  # noqa: E402
from src.config.settings import Settings  # noqa: E402
from src.intelligence.bars.sessions import nyse_sessions  # noqa: E402
from src.intelligence.bars.ticker_entity_map import MASSIVE_ARCHIVE_START  # noqa: E402
from src.intelligence.bars.vendor_arbitration import SEAM as ALPACA_FIRST_DAY  # noqa: E402

FAR_PAST = date(1990, 1, 1)
MASSIVE, ALPACA, IBKR = "massive", "alpaca", "ibkr"
#: timeframes whose Massive span hands over to Alpaca at the archive end; the others have no
#: Massive or Alpaca bar at all (1m and 4h leave canonical, owner ruling 2026-11-13)
HANDOVER_TIMEFRAMES = ("5m", "1d")
TIMEFRAMES = (*HANDOVER_TIMEFRAMES, "1m", "4h")
DEFAULT_MANIFEST = project_root / "data/massive/manifest/manifest.jsonl"

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


def archive_end_of(manifest: bytes) -> date:
    """The first NYSE session after the manifest's last file day (its key's date stamp, the load
    path's rule): Massive serves before it, Alpaca from it."""
    stamps = [
        date.fromisoformat(Path(json.loads(line)["key"]).name.removesuffix(".csv.gz"))
        for line in manifest.decode().splitlines()
        if line.strip()
    ]
    if not stamps:
        raise ValueError("the archive manifest is empty")
    last = max(stamps)
    return min(nyse_sessions(last + timedelta(days=1), last + timedelta(days=15)))


def defaults_for(timeframe: str, archive_end: date) -> list[dict[str, Any]]:
    """The new defaults of a timeframe (module docstring): no fallback, the last open-ended."""
    if timeframe not in TIMEFRAMES:
        raise ValueError(f"timeframe {timeframe} has no Massive switch plan")
    if timeframe not in HANDOVER_TIMEFRAMES:
        return [{"valid_from": FAR_PAST.isoformat(), "valid_to": None, "primary": MASSIVE}]
    end = archive_end.isoformat()
    return [
        {"valid_from": FAR_PAST.isoformat(), "valid_to": end, "primary": MASSIVE},
        {"valid_from": end, "valid_to": None, "primary": ALPACA},
    ]


def gap_rows(
    gaps: Sequence[GapRow], archive_end: date, gap_list: Mapping[str, str]
) -> list[dict[str, Any]]:
    """Alpaca symbol rows over the gap-list spans clipped to [2016-01-04, archive end), a name's
    spans merged; none before Alpaca's first day (module docstring)."""
    by_symbol: dict[str, list[tuple[date, date]]] = {}
    reasons: dict[str, set[str]] = {}
    for g in gaps:
        start = max(g.valid_from or ALPACA_FIRST_DAY, ALPACA_FIRST_DAY)
        stop = min(g.valid_to or archive_end, archive_end)
        if start < stop:
            by_symbol.setdefault(g.symbol, []).append((start, stop))
            reasons.setdefault(g.symbol, set()).add(g.reason)
    rows: list[dict[str, Any]] = []
    for symbol in sorted(by_symbol):
        merged: list[tuple[date, date]] = []
        for start, stop in sorted(by_symbol[symbol]):
            if merged and start <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(merged[-1][1], stop))
            else:
                merged.append((start, stop))
        rows += [
            {
                "symbol": symbol,
                "valid_from": a.isoformat(),
                "valid_to": b.isoformat(),
                "primary": ALPACA,
                "fallback": None,
                "evidence": {"gap_list": dict(gap_list), "gap_reasons": sorted(reasons[symbol])},
            }
            for a, b in merged
        ]
    return rows


def build_plan(
    *,
    timeframe: str,
    live: Sequence[LiveRow],
    gaps: Sequence[GapRow],
    gap_list: Mapping[str, str],
    archive_end: date,
    manifest: Mapping[str, str],
) -> dict[str, Any]:
    """The plan JSON for one timeframe, without the 1d raw fingerprint (the caller adds it through
    ``through_needed``: the latest gap row end)."""
    new_defaults = defaults_for(timeframe, archive_end)
    new_rows = gap_rows(gaps, archive_end, gap_list) if timeframe in HANDOVER_TIMEFRAMES else []
    new_symbols = {r["symbol"] for r in new_rows}
    defaults = [r for r in live if r.symbol is None]
    if not defaults:
        raise ValueError(f"{timeframe}: no live default to retire")
    evidence = {
        "ruling": (
            "owner 2026-11-13, todo 600: IBKR removed entirely; Massive for every date it has; "
            "no fallback"
        ),
        "archive_end": archive_end.isoformat(),
        "manifest": dict(manifest),
        "design": "docs/plans/2026-11-10-massive-admission-db-design.md",
        "runbook": "docs/operations/massive-step7-runbook.md",
        "coverage": (
            f"Massive holds no bar before {MASSIVE_ARCHIVE_START} and no 1m or 4h bar: those "
            "slots select nothing and leave canonical by construction"
        ),
        "gap_list": dict(gap_list),
        "gap_rule": (
            "gap-list spans: Alpaca symbol rows over [2016-01-04, archive end), no fallback; "
            "before 2016-01-04 a gap (lead ruling 2026-11-13)"
        ),
    }
    return {
        "timeframe": timeframe,
        "seam": new_defaults[-1]["valid_from"],
        "reason": "Massive switch without IBKR (todo 600 admission step 7, owner ruling 2026-11-13)",
        "evidence": evidence,
        "retire_defaults": True,
        "retire_default_ids": sorted(r.policy_id for r in defaults),
        "defaults": new_defaults,
        "symbol_rows": new_rows,
        "retire_symbol_rows": [
            _retired(r, "replaced" if r.symbol in new_symbols else "superseded_by_default")
            for r in live
            if r.symbol is not None
        ],
        "keep_symbol_rows": [],
    }


def ibkr_rows(plan: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    """Every row the plan would leave or make live with IBKR as primary or fallback: empty for
    a switch plan (the failure mode the tests pin)."""
    return [
        r
        for r in (*plan["defaults"], *plan["symbol_rows"], *plan.get("keep_symbol_rows", ()))
        if IBKR in (r.get("primary"), r.get("fallback"))
    ]


def snapshot_rows(live: Sequence[LiveRow]) -> list[dict[str, Any]]:
    """The live rows of a timeframe as JSON (the rollback input, taken before any switch)."""
    return [
        {
            "policy_id": r.policy_id,
            "symbol": r.symbol,
            "valid_from": r.valid_from.isoformat(),
            "valid_to": _iso(r.valid_to),
            "primary": r.primary,
            "fallback": r.fallback,
            "reason": r.reason,
            "evidence": r.evidence,
        }
        for r in live
    ]


def read_snapshot(rows: Sequence[Mapping[str, Any]]) -> list[LiveRow]:
    return [
        LiveRow(
            r["policy_id"],
            r["symbol"],
            date.fromisoformat(r["valid_from"]),
            date.fromisoformat(r["valid_to"]) if r["valid_to"] else None,
            r["primary"],
            r["fallback"],
            r["reason"],
            r["evidence"],
        )
        for r in rows
    ]


def build_restore_plan(
    *, timeframe: str, snapshot: Sequence[LiveRow], live: Sequence[LiveRow], source: str
) -> dict[str, Any]:
    """The reverse plan (step 7 rollback): the policy back to a pre-switch snapshot. Every live
    default is retired and the snapshot's defaults re-inserted; a live symbol row still in the
    snapshot is kept, a snapshot row no longer live is re-inserted with its own evidence, and every
    other live symbol row (the switch's) is retired. Without the 1d raw fingerprint, as
    build_plan."""
    defaults = sorted((r for r in snapshot if r.symbol is None), key=lambda r: r.valid_from)
    if not defaults or defaults[-1].valid_to is not None:
        raise ValueError("the snapshot holds no open-ended default; it is not a policy snapshot")
    if not any(r.symbol is None for r in live):
        raise ValueError("the live policy holds no default to retire")
    snapshot_ids = {r.policy_id for r in snapshot}
    live_ids = {r.policy_id for r in live}
    new_rows = [
        {
            "symbol": r.symbol,
            "valid_from": r.valid_from.isoformat(),
            "valid_to": _iso(r.valid_to),
            "primary": r.primary,
            "fallback": r.fallback,
            "evidence": {**r.evidence, "restored_from": r.policy_id},
        }
        for r in snapshot
        if r.symbol is not None and r.policy_id not in live_ids
    ]
    new_symbols = {r["symbol"] for r in new_rows}
    keep, retire = [], []
    for row in (r for r in live if r.symbol is not None):
        if row.policy_id in snapshot_ids:
            keep.append(
                {
                    "policy_id": row.policy_id,
                    "symbol": row.symbol,
                    "reason": "unchanged since the pre-switch snapshot",
                    "valid_from": row.valid_from.isoformat(),
                    "valid_to": _iso(row.valid_to),
                }
            )
        else:
            disposition = "replaced" if row.symbol in new_symbols else "superseded_by_default"
            retire.append(_retired(row, disposition))
    return {
        "timeframe": timeframe,
        "seam": defaults[-1].valid_from.isoformat(),
        "reason": "restore the pre-switch policy (Massive step 7 rollback)",
        "evidence": {"restore_of": source, "runbook": "docs/operations/massive-step7-runbook.md"},
        "retire_defaults": True,
        "retire_default_ids": sorted(r.policy_id for r in live if r.symbol is None),
        "defaults": [
            {
                "valid_from": r.valid_from.isoformat(),
                "valid_to": _iso(r.valid_to),
                "primary": r.primary,
                "fallback": r.fallback,
            }
            for r in defaults
        ],
        "symbol_rows": sorted(new_rows, key=lambda r: (r["symbol"], r["valid_from"])),
        "retire_symbol_rows": retire,
        "keep_symbol_rows": keep,
    }


def through_needed(plan: Mapping[str, Any]) -> date:
    """The latest end of any new symbol row: the 1d raw fingerprint must reach it (parse_plan)."""
    ends = [r["valid_to"] for r in plan["symbol_rows"] if r["valid_to"]]
    return date.fromisoformat(max(ends, default=plan["seam"]))


def _retired(row: LiveRow, disposition: str) -> dict[str, Any]:
    return {
        "policy_id": row.policy_id,
        "symbol": row.symbol,
        "disposition": disposition,
        "evidence": {
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
    settings = Settings()
    conn = await asyncpg.connect(
        settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
    )
    out = Path(args.out)
    try:
        live = await _read_live(conn, args.timeframe)
        if args.snapshot:
            out.write_text(json.dumps(snapshot_rows(live), indent=2, sort_keys=True) + "\n")
            print(f"snapshot {args.timeframe}: {len(live)} live rows; wrote {out}")
            return 0
        if args.restore:
            source = Path(args.restore)
            plan = build_restore_plan(
                timeframe=args.timeframe,
                snapshot=read_snapshot(json.loads(source.read_text())),
                live=live,
                source=f"{source} (sha256 {file_digest(source)})",
            )
        else:
            gap_path, manifest = Path(args.gap_list), Path(args.manifest)
            manifest_bytes = manifest.read_bytes()
            plan = build_plan(
                timeframe=args.timeframe,
                live=live,
                gaps=read_gap_list(gap_path),
                gap_list={"path": str(gap_path), "sha256": file_digest(gap_path)},
                archive_end=archive_end_of(manifest_bytes),
                manifest={
                    "path": str(manifest),
                    "sha256": hashlib.sha256(manifest_bytes).hexdigest(),
                },
            )
            if ibkr_rows(plan):
                raise ValueError(f"the plan leaves IBKR rows live: {ibkr_rows(plan)}")
        if args.timeframe == "1d":
            plan["raw_fingerprint"] = await read_raw_fingerprint(conn, through_needed(plan))
    finally:
        await conn.close()
    parse_plan(plan)  # the writer's own validation, before anyone reviews the file
    out.write_text(json.dumps(plan, indent=2, sort_keys=True) + "\n")
    spans = ", ".join(f"{r['valid_from']} {r['primary']}" for r in plan["defaults"])
    print(
        f"{'restore' if args.restore else 'switch'} {args.timeframe}: "
        f"{len(plan['defaults'])} defaults ({spans}), "
        f"retire {len(plan['retire_default_ids'])} defaults and "
        f"{len(plan['retire_symbol_rows'])} symbol rows, keep {len(plan['keep_symbol_rows'])}; "
        f"wrote {out} (sha256 {file_digest(out)})"
    )
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--switch", action="store_true", help="build the no-IBKR switch plan")
    mode.add_argument(
        "--snapshot", action="store_true", help="write the live rows (rollback input)"
    )
    mode.add_argument("--restore", metavar="SNAPSHOT", help="build the plan back to a snapshot")
    parser.add_argument("--timeframe", choices=TIMEFRAMES, required=True)
    parser.add_argument(
        "--gap-list",
        help="--switch: the identity map's gap_list.csv (recorded as the spans that become "
        "gaps; pin it, never 'newest')",
    )
    parser.add_argument(
        "--manifest",
        default=str(DEFAULT_MANIFEST),
        help="--switch: the archive manifest; its last file day sets the archive end",
    )
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    if args.switch and not args.gap_list:
        parser.error("--switch needs --gap-list")
    return asyncio.run(_main(args))


if __name__ == "__main__":
    sys.exit(main())
