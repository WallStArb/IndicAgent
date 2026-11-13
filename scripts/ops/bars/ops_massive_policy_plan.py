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
selection). The 1d plan pins every live default id it retires (three after stage 1) and
carries the raw fingerprint through the latest end of any symbol row, as --plan requires.

8a input (runbook A2 amendment 2026-11-13): ``--load-checks-out DIR`` is the section 8a runner's
out dir, pinned by path and sha256 (summary.json, stageC_stop_eras.json, stageC_era_tables.csv;
never "newest"). A partial or self-calibrated run, an unknown timeframe key or an era outside the
archive refuses. Each (era, timeframe) of the Massive span takes its source from the verdict
(``VERDICT_SOURCE``, the one table, declared in the runbook): a stopped (era, timeframe) keeps its
incumbent default (IBKR before 2016-01-04, Alpaca from it), so the Massive default becomes a set
of spans per timeframe. The plan lists every span edge it creates (``seam_edges``) for the Part D
``ops_seam_witness`` runs.

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


ARCHIVE_FIRST_ERA = MASSIVE_ARCHIVE_START.year
MASSIVE, INCUMBENT = "massive", "incumbent"
SLIVER_DAYS = 7  # an era overlapping the Massive span by fewer days is a sliver (era_spans)
CLOSE_DEFINITION = "close_definition_witnessed"
#: (timeframe or "*", verdict, reason or "*") -> the source of that (era, timeframe). First match
#: wins, the most specific rows first; an unlisted combination refuses. Declared in the runbook
#: (A2 amendment 2026-11-13). `unresolved` 1d: a witnessed close definition takes Massive (one
#: definition across the span, todo 610); a close convention without a witness keeps the
#: incumbent until a third witness exists. A thin era or no detector is a coverage fact, not a
#: failure: Massive stays the source (the owner ruling: sole pre-2016 5m source).
VERDICT_SOURCE: tuple[tuple[str, str, str, str], ...] = (
    ("1d", "unresolved", CLOSE_DEFINITION, MASSIVE),
    ("1d", "unresolved", "close_convention", INCUMBENT),
    ("*", "unresolved", "thin_era", MASSIVE),
    ("*", "ok", "*", MASSIVE),
    ("*", "ok_convention", "*", MASSIVE),
    ("*", "no_detector", "*", MASSIVE),
    ("*", "stop", "*", INCUMBENT),
)


def source_of(timeframe: str, verdict: str, reasons: Sequence[str]) -> str:
    """The source table lookup (``VERDICT_SOURCE``)."""
    for tf, v, reason, source in VERDICT_SOURCE:
        if tf in ("*", timeframe) and v == verdict and (reason == "*" or reason in reasons):
            return source
    raise ValueError(f"no source rule for {timeframe} verdict {verdict!r} reasons {list(reasons)}")


@dataclass(frozen=True)
class LoadChecks:
    """The 8a result the plan consumes: the source of every (era, timeframe) and the pins."""

    eras: tuple[int, ...]
    source: dict[tuple[int, str], str]
    stopped: dict[tuple[int, str], str]
    provenance: dict[str, Any]


def read_load_checks(out_dir: Path, archive_end: date = ARCHIVE_END) -> LoadChecks:
    """Read and validate an 8a out dir. Refuses a partial run, a run that did not cover every era
    of the archive, a self-calibrated run, an unknown timeframe key and an era outside the
    archive."""
    files = {
        name: out_dir / name
        for name in ("summary.json", "stageC_stop_eras.json", "stageC_era_tables.csv")
    }
    for path in files.values():
        if not path.is_file():
            raise ValueError(f"{out_dir}: {path.name} is missing; not an 8a out dir")
    summary = json.loads(files["summary.json"].read_text())
    if summary.get("status") != "complete":
        raise ValueError(f"{out_dir}: summary status {summary.get('status')!r}, need complete")
    if sorted(summary.get("stages_requested", [])) != ["A", "B", "C"]:
        raise ValueError(f"{out_dir}: the run did not cover stages A, B and C")
    if tuple(summary.get("eras", ())) != tuple(range(2003, archive_end.year + 1)):
        raise ValueError(
            f"{out_dir}: eras {summary.get('eras')} are not the full 2003 to archive end"
        )
    if (summary.get("partition") or {}).get("status") != "complete":
        raise ValueError(f"{out_dir}: the partition did not close")
    eras = tuple(summary["eras"])
    stopped: dict[tuple[int, str], str] = {}
    for key, reason in json.loads(files["stageC_stop_eras.json"].read_text()).items():
        era_text, _, tf = key.partition("/")
        if tf not in TIMEFRAMES or not era_text.isdigit():
            raise ValueError(f"stop key {key!r} is not era/timeframe with a known timeframe")
        if int(era_text) not in eras:
            raise ValueError(f"stop key {key!r}: era outside the archive {eras[0]}-{eras[-1]}")
        stopped[(int(era_text), tf)] = reason
    source: dict[tuple[int, str], str] = {}
    with files["stageC_era_tables.csv"].open(newline="") as handle:
        for row in csv.DictReader(handle):
            if row["calibrated_on"] == "self":
                raise ValueError(f"{out_dir}: era {row['era']} is self-calibrated, not a verdict")
            if row["timeframe"] not in TIMEFRAMES or int(row["era"]) not in eras:
                raise ValueError(
                    f"era table row {row['era']}/{row['timeframe']} is not in the archive"
                )
            key = (int(row["era"]), row["timeframe"])
            source[key] = source_of(
                key[1], row["verdict"], [x for x in row["reasons"].split(";") if x]
            )
    for key in stopped:
        source[key] = INCUMBENT  # a stage A or B systemic stop is in the stop file, not the table
    missing = [(e, tf) for e in eras for tf in TIMEFRAMES if (e, tf) not in source]
    if missing:
        raise ValueError(f"{out_dir}: no verdict for {missing[:3]}")
    provenance = {
        "out_dir": str(out_dir),
        **{name: {"path": str(path), "sha256": file_digest(path)} for name, path in files.items()},
        "stopped": sorted(f"{e}/{tf}" for e, tf in stopped),
    }
    return LoadChecks(eras, source, stopped, provenance)


def era_spans(
    checks: LoadChecks, stage: int, timeframe: str, archive_end: date
) -> list[tuple[date, date, str]]:
    """[(start, end, "massive" or "incumbent")] tiling the Massive span, adjacent equal sources
    merged. The head (before the archive start) is not part of it: it keeps its seam."""
    first, end = massive_span(stage, archive_end)
    pieces: list[tuple[date, date, str]] = []
    for era in checks.eras:
        start, stop = max(date(era, 1, 1), first), min(date(era + 1, 1, 1), end)
        if start < stop and (stop - start).days < SLIVER_DAYS and pieces:
            # a sliver of an era (stage 1 ends 2016-01-04: three non-session days of 2016) is no
            # era of its own: it takes the source of the era before it
            pieces[-1] = (pieces[-1][0], stop, pieces[-1][2])
        elif start < stop:
            pieces.append((start, stop, checks.source[(era, timeframe)]))
    merged: list[tuple[date, date, str]] = []
    for start, stop, src in pieces:
        if merged and merged[-1][2] == src and merged[-1][1] == start:
            merged[-1] = (merged[-1][0], stop, src)
        else:
            merged.append((start, stop, src))
    return merged


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


def _incumbent_primary(start: date) -> str:
    """The incumbent default over a stopped span: IBKR before 2016-01-04, Alpaca from it."""
    return "ibkr" if start < ALPACA_SEAM else "alpaca"


def defaults_for(
    stage: int,
    live_defaults: Sequence[LiveRow],
    archive_end: date,
    spans: Sequence[tuple[date, date, str]] | None = None,
) -> list[dict]:
    """The new defaults (module docstring). ``spans`` (``era_spans``) split the Massive span per
    timeframe: a stopped (era, timeframe) keeps its incumbent. Stage 1 copies the live open
    default unchanged."""
    first, end = massive_span(stage, archive_end)
    spans = spans if spans is not None else [(first, end, MASSIVE)]
    head = [{"valid_from": FAR_PAST.isoformat(), "valid_to": first.isoformat(), "primary": "ibkr"}]
    middle = [
        {
            "valid_from": a.isoformat(),
            "valid_to": b.isoformat(),
            "primary": "massive" if src == MASSIVE else _incumbent_primary(a),
        }
        for a, b, src in spans
    ]
    # an incumbent span straddling 2016-01-04 (stage 2) is cut there: IBKR then Alpaca
    cut: list[dict] = []
    for row in middle:
        a, b = date.fromisoformat(row["valid_from"]), date.fromisoformat(row["valid_to"])
        if row["primary"] != "massive" and a < ALPACA_SEAM < b:
            cut += [
                {**row, "valid_to": ALPACA_SEAM.isoformat(), "primary": "ibkr"},
                {**row, "valid_from": ALPACA_SEAM.isoformat(), "primary": "alpaca"},
            ]
        else:
            cut.append(row)
    rows = [*head, *cut]
    if stage == 2:
        return [*rows, {"valid_from": end.isoformat(), "valid_to": None, "primary": "alpaca"}]
    open_rows = [r for r in live_defaults if r.valid_to is None]
    if len(open_rows) != 1 or open_rows[0].valid_from != ALPACA_SEAM:
        raise ValueError(f"expected one live open default from {ALPACA_SEAM}, got {open_rows}")
    tail = open_rows[0]
    return [
        *rows,
        {
            "valid_from": ALPACA_SEAM.isoformat(),
            "valid_to": None,
            "primary": tail.primary,
            "fallback": tail.fallback,
        },
    ]


def seam_edges(defaults: Sequence[Mapping[str, Any]], timeframe: str) -> list[dict[str, Any]]:
    """Every boundary of the new defaults where the primary source changes (the 2003 archive start
    and the 2016 seam included): Part D runs ``ops_seam_witness`` at each."""
    ordered = sorted(defaults, key=lambda r: r["valid_from"])
    return [
        {
            "timeframe": timeframe,
            "seam": after["valid_from"],
            "from_source": before["primary"],
            "to_source": after["primary"],
        }
        for before, after in zip(ordered, ordered[1:], strict=False)
        if before["primary"] != after["primary"]
    ]


def build_plan(
    *,
    stage: int,
    timeframe: str,
    live: Sequence[LiveRow],
    gaps: Sequence[GapRow],
    gap_list: Mapping[str, str],
    archive_end: date = ARCHIVE_END,
    checks: LoadChecks | None = None,
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
        "load_checks": checks.provenance if checks else None,
    }
    defaults = [r for r in live if r.symbol is None]
    spans = era_spans(checks, stage, timeframe, archive_end) if checks else None
    new_defaults = defaults_for(stage, defaults, archive_end, spans)
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
        "defaults": new_defaults,
        "seam_edges": seam_edges(new_defaults, timeframe),
        "symbol_rows": sorted(new_rows, key=lambda r: (r["symbol"], r["valid_from"])),
        "retire_symbol_rows": retire,
        "keep_symbol_rows": keep,
    }
    return plan


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
            retire.append(_retired(row, disposition, 0))
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
            gap_path = Path(args.gap_list)
            plan = build_plan(
                stage=args.stage,
                timeframe=args.timeframe,
                live=live,
                gaps=read_gap_list(gap_path),
                gap_list={"path": str(gap_path), "sha256": file_digest(gap_path)},
                archive_end=date.fromisoformat(args.archive_end),
                checks=read_load_checks(
                    Path(args.load_checks_out), date.fromisoformat(args.archive_end)
                ),
            )
        if args.timeframe == "1d":
            plan["raw_fingerprint"] = await read_raw_fingerprint(conn, through_needed(plan))
    finally:
        await conn.close()
    parse_plan(plan)  # the writer's own validation, before anyone reviews the file
    out.write_text(json.dumps(plan, indent=2, sort_keys=True) + "\n")
    if plan.get("seam_edges"):  # the Part D seam witness list, one row per span edge
        edges = out.with_suffix(".seams.csv")
        with edges.open("w", newline="") as handle:
            writer = csv.DictWriter(handle, ["timeframe", "seam", "from_source", "to_source"])
            writer.writeheader()
            writer.writerows(plan["seam_edges"])
        print(f"seam edges for ops_seam_witness: {len(plan['seam_edges'])}; wrote {edges}")
    rows = plan["symbol_rows"]
    print(
        f"{'restore' if args.restore else f'stage {args.stage}'} {args.timeframe}: "
        f"{len(plan['defaults'])} defaults, "
        f"{len(rows)} symbol rows on {len({r['symbol'] for r in rows})} names "
        f"({sum(r['primary'] == 'ibkr' for r in rows)} ibkr, "
        f"{sum(r['primary'] == 'alpaca' for r in rows)} alpaca), "
        f"retire {len(plan['retire_symbol_rows'])}, keep {len(plan['keep_symbol_rows'])}; "
        f"wrote {out} (sha256 {file_digest(out)})"
    )
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--stage", type=int, choices=STAGES, help="build the stage's switch plan")
    mode.add_argument(
        "--snapshot", action="store_true", help="write the live rows (rollback input)"
    )
    mode.add_argument("--restore", metavar="SNAPSHOT", help="build the plan back to a snapshot")
    parser.add_argument("--timeframe", choices=TIMEFRAMES, required=True)
    parser.add_argument(
        "--gap-list",
        help="--stage: the identity map's gap_list.csv the load sweep used (pin it; never 'newest')",
    )
    parser.add_argument(
        "--load-checks-out",
        help="--stage: the 8a runner's out dir (summary.json, stageC_stop_eras.json, "
        "stageC_era_tables.csv; pinned by path and sha256, never 'newest')",
    )
    parser.add_argument("--archive-end", default=ARCHIVE_END.isoformat())
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    if args.stage and not args.gap_list:
        parser.error("--stage needs --gap-list")
    if args.stage and not args.load_checks_out:
        parser.error("--stage needs --load-checks-out (the 8a verdicts)")
    return asyncio.run(_main(args))


if __name__ == "__main__":
    sys.exit(main())
