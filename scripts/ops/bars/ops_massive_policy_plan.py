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
never "newest"), and ``--manifest`` the archive manifest the run hashed. The verdicts are the
summary's (``stage_c.era_verdicts``, ``stop_eras_all_sources``); the era table and the stop file
must match them exactly. A partial or self-calibrated run, eras other than the archive's own
(``ARCHIVE_FIRST_ERA`` to the manifest's last year, the runner's rule), an unknown timeframe key or
a duplicate (era, timeframe) row refuses. Each (era, timeframe) of the Massive span takes its
source from one rule: a stopped (era, timeframe) keeps its incumbent default (IBKR before
2016-01-04, Alpaca from it); every other verdict reads ``VERDICT_SOURCE`` (the one table, declared
in the runbook). So the default is a set of spans PER TIMEFRAME: with no stop the stage's three
defaults; each stopped run of eras adds its incumbent span. The count is one more than the
timeframe's ``seam_edges``, plus one when the 2003 era is stopped (the head and the first span are
both IBKR with no edge between them; the head stays its own row so 2003-09-10 stays a boundary). Eras run from 1
January, except that the 2016 era starts at 2016-01-04 (1 to 3 January are no sessions), so no
default covers only non-session days. A stopped pre-2016 5m era keeps the IBKR default (lead
ruling 2026-11-13): an explicit exception to the sole-source ruling for that era only, printed
and listed in the evidence as ``sole_source_exception``. The plan lists every span edge
(``seam_edges``, with the ``ops_seam_witness`` ``incoming`` series) for Part D.

Rollback (runbook A9 and every abort rule after C2): --snapshot writes a timeframe's live rows
to JSON before the switch; --restore SNAPSHOT builds the plan that puts the policy back (the
snapshot's defaults, its symbol rows kept or re-inserted, the switch's rows retired).
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import hashlib
import io
import json
import sys
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
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
STOP = "stop"
CLOSE_DEFINITION = "close_definition_witnessed"
LOAD_CHECK_FILES = ("summary.json", "stageC_stop_eras.json", "stageC_era_tables.csv")
DEFAULT_MANIFEST = project_root / "data/massive/manifest/manifest.jsonl"
#: (timeframe or "*", verdict, reason or "*") -> the source of that (era, timeframe). First match
#: wins, the most specific rows first; an unlisted combination refuses. Declared in the runbook
#: (A2 amendment 2026-11-13). `unresolved` 1d: a witnessed close definition takes Massive (one
#: definition across the span, todo 610); a close convention without a witness keeps the
#: incumbent until a third witness exists. A thin era or no detector is a coverage fact, not a
#: failure: Massive stays the source (the owner ruling: sole pre-2016 5m source). A stop is not
#: here: the stop set is the one stop mechanism (``LoadChecks.stopped``).
VERDICT_SOURCE: tuple[tuple[str, str, str, str], ...] = (
    ("1d", "unresolved", CLOSE_DEFINITION, MASSIVE),
    ("1d", "unresolved", "close_convention", INCUMBENT),
    ("*", "unresolved", "thin_era", MASSIVE),
    ("*", "ok", "*", MASSIVE),
    ("*", "ok_convention", "*", MASSIVE),
    ("*", "no_detector", "*", MASSIVE),
)
#: The raw kind of each incumbent arm, a copy of the 8a runner's ``ARM_KINDS`` (on
#: massive-8a-load-checks until it lands; ``vendor_kind`` has no raw-arm table: its 1d IBKR kind
#: is ``named``, the arm is ``smart_trades``): the ``--incoming`` series of a seam witness at the
#: archive start or end, where Massive has no reference on one side.
INCUMBENT_KIND = {
    ("1d", "ibkr"): "smart_trades",
    ("1d", "alpaca"): "sip_rth",
    ("5m", "ibkr"): "named",
    ("5m", "alpaca"): "sip_rth",
}


def source_of(timeframe: str, verdict: str, reasons: Sequence[str]) -> str:
    """The source table lookup (``VERDICT_SOURCE``). A rule naming a reason matches only a row
    whose reasons are exactly that one: a second reason beside a benign one refuses."""
    for tf, v, reason, source in VERDICT_SOURCE:
        exact = reason == "*" or list(reasons) == [reason]
        if tf in ("*", timeframe) and v == verdict and exact:
            return source
    raise ValueError(f"no source rule for {timeframe} verdict {verdict!r} reasons {list(reasons)}")


@dataclass(frozen=True)
class LoadChecks:
    """The 8a result the plan consumes: the source of every (era, timeframe) and the pins."""

    eras: tuple[int, ...]
    source: dict[tuple[int, str], str]
    stopped: frozenset[tuple[int, str]]
    provenance: dict[str, Any]


def _era_key(key: str) -> tuple[int, str]:
    era_text, _, tf = key.partition("/")
    if tf not in TIMEFRAMES or not era_text.isdigit():
        raise ValueError(f"key {key!r} is not era/timeframe with a known timeframe")
    return int(era_text), tf


def manifest_last_day(data: bytes) -> date:
    """The latest file date of the archive manifest (the runner's ``load_archive`` key rule)."""
    stamps = [
        Path(json.loads(line)["key"]).name.removesuffix(".csv.gz")
        for line in data.decode().splitlines()
        if line.strip()
    ]
    if not stamps:
        raise ValueError("the archive manifest is empty")
    return max(date.fromisoformat(stamp) for stamp in stamps)


def read_load_checks(
    out_dir: Path, manifest: Path = DEFAULT_MANIFEST, archive_end: date = ARCHIVE_END
) -> LoadChecks:
    """Read and validate an 8a out dir: one run or a refusal (module docstring). Each input is
    read once; its hash and its parse come from the same bytes."""
    blobs: dict[str, bytes] = {}
    for name in LOAD_CHECK_FILES:
        path = out_dir / name
        if not path.is_file():
            raise ValueError(f"{out_dir}: {name} is missing; not an 8a out dir")
        blobs[name] = path.read_bytes()
    manifest_bytes = manifest.read_bytes()
    summary = json.loads(blobs["summary.json"])
    if summary.get("status") != "complete":
        raise ValueError(f"{out_dir}: summary status {summary.get('status')!r}, need complete")
    if not {"A", "B", "C"} <= set(summary.get("stages_requested", [])):
        raise ValueError(f"{out_dir}: the run did not cover stages A, B and C")
    if (summary.get("partition") or {}).get("status") != "complete":
        raise ValueError(f"{out_dir}: the partition did not close")
    manifest_sha = hashlib.sha256(manifest_bytes).hexdigest()
    if (summary.get("inputs") or {}).get("manifest.jsonl") != manifest_sha:
        raise ValueError(f"{out_dir}: the run hashed another manifest than {manifest}")
    last_day = manifest_last_day(manifest_bytes)
    first_after = min(nyse_sessions(last_day + timedelta(days=1), last_day + timedelta(days=15)))
    if archive_end != first_after:
        raise ValueError(
            f"archive end {archive_end} is not the first session {first_after} after the "
            f"manifest's last day {last_day}"
        )
    systemic = sorted(
        k
        for k, v in (summary.get("systemic_verdicts") or {}).items()
        if v == STOP and k.startswith(("stage_a.", "stage_b."))
    )
    if systemic:
        raise ValueError(f"{out_dir}: stage A or B systemic stop {systemic}: abort (runbook A2)")
    want = tuple(range(ARCHIVE_FIRST_ERA, last_day.year + 1))
    stage_c = summary.get("stage_c") or {}
    if tuple(summary.get("eras", ())) != want or tuple(stage_c.get("eras", ())) != want:
        raise ValueError(f"{out_dir}: eras {summary.get('eras')} are not the archive's {want}")
    verdicts = {_era_key(k): v for k, v in stage_c.get("era_verdicts", {}).items()}
    stop_view = stage_c.get("stop_eras_all_sources", {})
    if json.loads(blobs["stageC_stop_eras.json"]) != stop_view:
        raise ValueError(f"{out_dir}: stageC_stop_eras.json differs from the summary's stops")
    stopped = frozenset(_era_key(k) for k in stop_view)
    reasons: dict[tuple[int, str], list[str]] = {}
    for row in csv.DictReader(io.StringIO(blobs["stageC_era_tables.csv"].decode())):
        key = (int(row["era"]), row["timeframe"])
        if key in reasons:
            raise ValueError(f"era table: duplicate row {key[0]}/{key[1]}")
        if row["calibrated_on"] == "self":
            raise ValueError(f"{out_dir}: era {row['era']} is self-calibrated, not a verdict")
        if verdicts.get(key) != row["verdict"]:
            raise ValueError(f"era table {key[0]}/{key[1]}: verdict differs from the summary")
        reasons[key] = [x for x in row["reasons"].split(";") if x]
    expected = {(e, tf) for e in want for tf in TIMEFRAMES}
    if set(reasons) != expected or set(verdicts) != expected or not stopped <= expected:
        raise ValueError(f"{out_dir}: the verdicts do not cover exactly the archive's eras")
    unstopped = sorted(k for k, v in verdicts.items() if v == STOP and k not in stopped)
    if unstopped:
        raise ValueError(f"{out_dir}: stop verdicts {unstopped} are not in the stop file")
    source = {
        key: INCUMBENT if key in stopped else source_of(key[1], verdicts[key], reasons[key])
        for key in sorted(expected)
    }
    provenance = {
        "out_dir": str(out_dir),
        **{
            name: {"path": str(out_dir / name), "sha256": hashlib.sha256(data).hexdigest()}
            for name, data in blobs.items()
        },
        "manifest": {"path": str(manifest), "sha256": manifest_sha},
        "stopped": sorted(f"{e}/{tf}" for e, tf in stopped),
    }
    return LoadChecks(want, source, stopped, provenance)


def sole_source_exceptions(checks: LoadChecks, timeframe: str) -> list[str]:
    """The stopped pre-2016 5m eras: they keep IBKR, the one exception to the owner's sole-source
    ruling for that era only (lead ruling 2026-11-13). Empty for 1d."""
    return sorted(
        f"{e}/{tf}" for e, tf in checks.stopped if tf == "5m" == timeframe and e < ALPACA_SEAM.year
    )


def era_start(era: int) -> date:
    """1 January, except the 2016 era: it starts at the Alpaca seam (1 to 3 January 2016 are no
    sessions), so no default and no edge falls on non-session days only."""
    return ALPACA_SEAM if era == ALPACA_SEAM.year else date(era, 1, 1)


def era_spans(
    checks: LoadChecks, stage: int, timeframe: str, archive_end: date
) -> list[tuple[date, date, str]]:
    """[(start, end, primary)] tiling the Massive span: "massive", or the incumbent of a stopped
    era (``_incumbent_primary``: IBKR before 2016-01-04, Alpaca from it, so a stopped run across
    the seam splits there), adjacent equal primaries merged. The head (before the archive start)
    is not part of it: it keeps its seam."""
    first, end = massive_span(stage, archive_end)
    merged: list[tuple[date, date, str]] = []
    for era in checks.eras:
        start, stop = max(era_start(era), first), min(era_start(era + 1), end)
        if start >= stop:
            continue
        src = checks.source[(era, timeframe)]
        src = MASSIVE if src == MASSIVE else _incumbent_primary(start)
        if src != MASSIVE and start < ALPACA_SEAM < stop:
            raise ValueError(f"era {era} straddles the Alpaca seam: its incumbent is ambiguous")
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
    spans: Sequence[tuple[date, date, str]],
) -> list[dict]:
    """The new defaults (module docstring). ``spans`` (``era_spans``) split the Massive span per
    timeframe: a stopped (era, timeframe) keeps its incumbent. Stage 1 copies the live open
    default unchanged."""
    first, end = massive_span(stage, archive_end)
    head = [{"valid_from": FAR_PAST.isoformat(), "valid_to": first.isoformat(), "primary": "ibkr"}]
    middle = [
        {"valid_from": a.isoformat(), "valid_to": b.isoformat(), "primary": primary}
        for a, b, primary in spans
    ]
    rows = [*head, *middle]
    if stage == 2:
        if middle[-1]["primary"] == "alpaca":  # a stopped last era runs on into the open tail
            return [*rows[:-1], {**middle[-1], "valid_to": None}]
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


SEAM_EDGE_FIELDS = ("timeframe", "seam", "from_source", "to_source", "incoming")


def witness_incoming(timeframe: str, seam: str, before: str, after: str, span_end: date) -> str:
    """The ``ops_seam_witness --incoming`` series of one edge. Its reference is always Massive
    raw: an edge strictly inside the Massive archive witnesses canonical on both sides; at the
    archive start or end Massive has no reference on one side, so the non-Massive side's own raw
    kind is the incoming series (the 2003-09-10 IBKR and archive-end Alpaca witnesses)."""
    day = date.fromisoformat(seam)
    if MASSIVE_ARCHIVE_START < day < span_end:
        return "canonical"
    other = before if after == MASSIVE else after
    return f"raw:{other}/{INCUMBENT_KIND[(timeframe, other)]}"


def seam_edges(
    defaults: Sequence[Mapping[str, Any]], timeframe: str, archive_end: date
) -> list[dict[str, Any]]:
    """Every boundary of the new defaults where the primary source changes (the 2003 archive start
    and the 2016 seam included), with its witness series: Part D runs ``ops_seam_witness`` at
    each. ``archive_end`` is the end of Massive's reference, whatever the stage."""
    ordered = sorted(defaults, key=lambda r: r["valid_from"])
    return [
        {
            "timeframe": timeframe,
            "seam": after["valid_from"],
            "from_source": before["primary"],
            "to_source": after["primary"],
            "incoming": witness_incoming(
                timeframe, after["valid_from"], before["primary"], after["primary"], archive_end
            ),
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
    checks: LoadChecks,
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
        "load_checks": checks.provenance,
        "sole_source_exception": sole_source_exceptions(checks, timeframe),
    }
    defaults = [r for r in live if r.symbol is None]
    spans = era_spans(checks, stage, timeframe, archive_end)
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
        "seam_edges": seam_edges(new_defaults, timeframe, archive_end),
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
                    Path(args.load_checks_out),
                    Path(args.manifest),
                    date.fromisoformat(args.archive_end),
                ),
            )
            exceptions = plan["evidence"]["sole_source_exception"]
            if exceptions:
                print(
                    f"SOLE-SOURCE EXCEPTION: {len(exceptions)} stopped pre-2016 5m era(s) keep "
                    f"the IBKR default: {', '.join(exceptions)}"
                )
        if args.timeframe == "1d":
            plan["raw_fingerprint"] = await read_raw_fingerprint(conn, through_needed(plan))
    finally:
        await conn.close()
    parse_plan(plan)  # the writer's own validation, before anyone reviews the file
    out.write_text(json.dumps(plan, indent=2, sort_keys=True) + "\n")
    if not args.restore:  # the Part D seam witness list, one row per span edge, always rewritten
        edges = out.with_suffix(".seams.csv")
        with edges.open("w", newline="") as handle:  # \n: the runbook loop reads it with `read`
            writer = csv.DictWriter(handle, SEAM_EDGE_FIELDS, lineterminator="\n")
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
    parser.add_argument(
        "--manifest",
        default=str(DEFAULT_MANIFEST),
        help="--stage: the archive manifest the 8a run hashed (its last year bounds the eras)",
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
