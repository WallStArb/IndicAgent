"""Ticker-entity map writer: the one writer of ``security_identifier`` and ``ticker_event``.

Admission design section 6, step 3b (stage 1, current names). Reads the reference answers
(``reference_raw_current``: Massive overview, events and the delisted universe; IBKR contract
details; OpenFIGI's ISIN mapping), hands them to the pure
``src.intelligence.bars.ticker_entity_map.propose_ticker_entity_map``, and inserts what it
proposes: identifiers first, then the spans that resolve to them, in one transaction.

The gate is checked before anything is written: every instrument is mapped (it has a span) or
is on the gap list, and the counts add up to the instrument count. The gap list and the
partition are written to ``data/ticker_entity_map/<YYYYMMDD>_<digest12>/`` on every run. A run
over tables already holding exactly the proposed rows is a no-op; any other existing row
refuses the run (a correction retires and replaces rows, which is not this writer's job yet).
A run without --apply does everything inside the transaction and rolls it back.

    .venv/bin/python -m services.ticker_entity_map_writer            # rolled-back rehearsal
    .venv/bin/python -m services.ticker_entity_map_writer --apply    # write

``--amend SPANS_CSV --amend-sha256 HEX --amend-candidates CSV --gap-list CSV`` is the additive
amendment of design section 8c (identity witness, lead ruling 2026-11-13): each ``placed`` span
of the witness run becomes one ``ticker_event`` row under the name's existing composite FIGI
identifier, with the witness evidence; a name without one gets its FIGI identifiers minted from
its captured OpenFIGI answer only when exactly one entry matches its ticker on exchange US (any
other name stays a gap, listed). Any overlap with a live span (of the name, or of the ticker
under another name) refuses the run. The gap list is rewritten without the placed spans into a
new dated map directory. One transaction; rehearsal by default, --apply to write.

``--documentary PLACEMENTS_CSV`` is the documentary amendment of design section 8c (2026-11-14):
the pinned map (its gap list directory plus the live ``ticker_event`` spans, read only) and the
witness's ``documentary_placements.csv`` and ``documentary_spans.csv`` give a new map version
under ``--out``, never the database and never ``data/ticker_entity_map``. Inside each witness
span that holds a placement, the old spans are cut out and the placements put in (a rename splits
a span at the first and last file day of each ticker); what the cut removed and no placement
re-covers becomes an ``identity_unplaced`` gap row; spans of unplaced witness decisions are left
as they are. Every old span, gap row and placement is accounted in ``span_accounting.csv``.
``--install MAP_DIR --install-digest D --untouched NAMES --lost-1d/--lost-5m/--coverage-summary``
applies a scratch map version to the live rows (design 8c; section "Install" below): rehearsal
unless ``--apply``; ``--rollback INSTALL_ID`` undoes a recorded install. Both refuse loudly and
write nothing on any gate failure.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import hashlib
import io
import json
import os
import re
import shutil
from collections import Counter
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import asyncpg

from src.config.settings import Settings
from src.core.agent.base_batch import BaseBatch
from src.core.canonical_json import canonical_json
from src.intelligence.bars.ticker_entity_map import (
    SPAN_SCHEME,
    Answer,
    DelistedTicker,
    MapInputs,
    Proposal,
    propose_ticker_entity_map,
)
from src.observability.otel import OTelInitError, init_otel_providers

_JOB = "ticker-entity-map-writer"
_REPO_ROOT = Path(__file__).resolve().parents[1]
_OUT_ROOT = _REPO_ROOT / "data" / "ticker_entity_map"

_INSTRUMENTS_SQL = "SELECT symbol, contract_details->>'asset_class' AS asset_class FROM instruments"
_ANSWERS_SQL = """
SELECT reference_raw_id::text AS id, request_key, served_at, body
  FROM reference_raw_current
 WHERE vendor = $1 AND endpoint = $2
   AND ($3::text[] IS NULL OR split_part(request_key, '@', 1) = ANY($3))
"""
_DELISTED_SQL = """
SELECT r.reference_raw_id::text AS id, x->>'ticker' AS ticker, x->>'delisted_utc' AS delisted_utc
  FROM reference_raw_current r, jsonb_array_elements(r.body->'results') AS x
 WHERE r.vendor = 'massive' AND r.endpoint = 'tickers_delisted'
"""
# Every page of the delisted universe must be an OK answer: a failed page would silently take
# its tickers out of the reused-ticker check.
_DELISTED_PAGES_SQL = """
SELECT count(*) FILTER (WHERE body->>'status' = 'OK' AND jsonb_typeof(body->'results') = 'array')
           AS ok,
       count(*) AS pages
  FROM reference_raw_current WHERE vendor = 'massive' AND endpoint = 'tickers_delisted'
"""
_EVENTS_STATUS_SQL = """
SELECT CASE WHEN split_part(request_key, '@', 2) = 'active' THEN 'active' ELSE 'dated' END
           AS query, body->>'status' AS status, count(*) AS n
  FROM reference_raw_current WHERE vendor = 'massive' AND endpoint = 'events' GROUP BY 1, 2
"""
_CURRENT_IDENTIFIERS_SQL = """
SELECT symbol, scheme, value, valid_from, valid_to, reference_raw_id::text AS id
  FROM security_identifier_current
"""
_CURRENT_SPANS_SQL = """
SELECT symbol, ticker, valid_from, valid_to, reference_raw_id::text AS id, evidence
  FROM ticker_event_current WHERE vendor = 'massive'
"""
_INSERT_IDENTIFIERS_SQL = """
INSERT INTO security_identifier (symbol, scheme, value, valid_from, reference_raw_id)
SELECT * FROM unnest($1::text[], $2::text[], $3::text[], $4::date[], $5::uuid[])
RETURNING security_identifier_id, symbol, scheme
"""
_INSERT_SPANS_SQL = """
INSERT INTO ticker_event (security_identifier_id, symbol, vendor, ticker, valid_from, valid_to,
                          reference_raw_id, evidence)
SELECT i, s, 'massive', t, f, v, r, e::jsonb
  FROM unnest($1::uuid[], $2::text[], $3::text[], $4::date[], $5::date[], $6::uuid[], $7::text[])
       AS u(i, s, t, f, v, r, e)
"""


_AMEND_OVERVIEW_SQL = """
SELECT split_part(request_key, '@', 1) AS symbol, reference_raw_id::text AS id
  FROM reference_raw_current
 WHERE vendor = 'massive' AND endpoint = 'overview' AND request_key LIKE '%@active'
"""
_AMEND_FIGI_SQL = """
SELECT request_key AS isin, reference_raw_id::text AS id, body
  FROM reference_raw_current WHERE vendor = 'openfigi' AND endpoint = 'mapping_isin_us'
"""
_AMEND_IDS_SQL = """
SELECT security_identifier_id, symbol, scheme, value FROM security_identifier_current
"""
_AMEND_SPANS_SQL = """
SELECT symbol, ticker, valid_from, valid_to FROM ticker_event_current WHERE vendor = 'massive'
"""
WITNESS_CODE, WITNESS_RULE = "07bfd963b", "8d10bd030"


@dataclass(frozen=True)
class PlacedSpan:
    symbol: str
    reason: str
    start: date
    end: date
    ticker: str
    evidence: dict[str, Any]


@dataclass
class Amendment:
    """What an --amend run writes: identifiers to mint, spans to insert, gap rows removed, and the
    placed names left as gaps (no unambiguous FIGI)."""

    mint: list[tuple[str, str, str, str]] = field(
        default_factory=list
    )  # symbol, scheme, value, ref
    spans: list[PlacedSpan] = field(default_factory=list)
    removed_gaps: list[dict[str, str]] = field(default_factory=list)
    kept_as_gap: list[tuple[str, str]] = field(default_factory=list)  # symbol, why


def read_placed(spans_csv: bytes, candidates_csv: bytes, sha256: str) -> list[PlacedSpan]:
    """The witness run's placed spans with their placing candidate's evidence; refuses unless the
    spans file hashes to ``sha256``."""
    digest = hashlib.sha256(spans_csv).hexdigest()
    if digest != sha256:
        raise ValueError(f"witness spans file sha256 {digest} is not the pinned {sha256}")
    evidence: dict[tuple[str, str, str], dict[str, str]] = {
        (c["symbol"], c["span_start"], c["candidate"]): c
        for c in csv.DictReader(io.StringIO(candidates_csv.decode()))
    }
    out = []
    for r in csv.DictReader(io.StringIO(spans_csv.decode())):
        if r["decision"] != "placed":
            continue
        c = evidence[(r["symbol"], r["span_start"], r["placing_ticker"])]
        out.append(
            PlacedSpan(
                r["symbol"],
                r["reason"],
                date.fromisoformat(r["span_start"]),
                date.fromisoformat(r["span_end"]),
                r["placing_ticker"],
                {
                    "amendment": "design 8c identity witness (lead ruling 2026-11-13)",
                    "witness_code": WITNESS_CODE,
                    "witness_rule": WITNESS_RULE,
                    "witness_spans_sha256": digest,
                    "gap_reason": r["reason"],
                    "list_date": r["list_date"],
                    "ibkr_sessions": int(r["ibkr_sessions"]),
                    **{k: c[k] for k in ("pairs", "agreeing", "correlation", "level_median",
                                         "level_iqr", "n_splits")},  # fmt: skip
                },
            )
        )
    return out


def single_figi(body: Any, ticker: str) -> tuple[str, str] | None:
    """(composite, share class) when exactly one captured OpenFIGI entry names ``ticker`` on
    exchange US, else None."""
    entries = [
        e
        for block in (body or [])
        for e in (block.get("data") or [])
        if e.get("ticker") == ticker and e.get("exchCode") == "US"
    ]
    pairs = {(e.get("compositeFIGI"), e.get("shareClassFIGI")) for e in entries}
    if len(entries) != 1 or None in next(iter(pairs)):
        return None
    return next(iter(pairs))


def _overlaps(a: date, b: date | None, c: date, d: date | None) -> bool:
    return (b is None or c < b) and (d is None or a < d)


def plan_amendment(
    placed: Sequence[PlacedSpan],
    identifiers: Mapping[str, Mapping[str, str]],
    isin_answers: Mapping[str, tuple[str, Any]],
    live_spans: Sequence[tuple[str, str, date, date | None]],
    gap_rows: Sequence[dict[str, str]],
    archive_start: date,
    archive_end: date,
) -> Amendment:
    """The amendment (module docstring). Raises on any overlap with a live span."""
    amendment = Amendment()
    clashes = [
        f"{p.symbol} {p.ticker} {p.start}..{p.end} overlaps {sym} {tick} {a}..{b}"
        for p in placed
        for sym, tick, a, b in live_spans
        if (sym == p.symbol or tick == p.ticker) and _overlaps(p.start, p.end, a, b)
    ]
    clashes += [
        f"{p.symbol} {p.start}..{p.end} overlaps placed {q.symbol} {q.start}..{q.end}"
        for i, p in enumerate(placed)
        for q in placed[i + 1 :]
        if (p.symbol == q.symbol or p.ticker == q.ticker)
        and _overlaps(p.start, p.end, q.start, q.end)
    ]
    if clashes:
        raise ValueError(f"{len(clashes)} overlap(s) with live or placed spans: {clashes}")
    placed_keys = set()
    for p in placed:
        ids = identifiers.get(p.symbol, {})
        if SPAN_SCHEME not in ids:
            isin = ids.get("isin")
            answer = isin_answers.get(isin) if isin else None
            figi = single_figi(answer[1], p.symbol) if answer else None
            if figi is None:
                amendment.kept_as_gap.append((p.symbol, "no single captured OpenFIGI answer"))
                continue
            for scheme, value in zip(("composite_figi", "share_class_figi"), figi, strict=True):
                if (p.symbol, scheme, value, answer[0]) not in amendment.mint:
                    amendment.mint.append((p.symbol, scheme, value, answer[0]))
        amendment.spans.append(p)
        placed_keys.add((p.symbol, p.reason, p.start, p.end))
    for g in gap_rows:
        start = max(date.fromisoformat(g["valid_from"]) if g["valid_from"] else archive_start,
                    archive_start)  # fmt: skip
        end = min(date.fromisoformat(g["valid_to"]) if g["valid_to"] else archive_end, archive_end)
        if (g["symbol"], g["reason"], start, end) in placed_keys:
            amendment.removed_gaps.append(g)
    return amendment


# ---------------------------------------------------------------------------------------------
# Documentary amendment (design 8c, 2026-11-14): pure planning, then one render.
# ---------------------------------------------------------------------------------------------

_OPEN = date.max  # an open end inside the interval algebra; written back as an empty cell
IDENTITY_UNPLACED = "identity_unplaced"
DOC_PLACED = frozenset({"placed", "placed_partial"})
DOC_AMENDMENT = "design 8c documentary witness (lead ruling 2026-11-14)"
GAP_FIELDS = ("symbol", "scope", "reason", "valid_from", "valid_to", "detail")
SPAN_FIELDS = (
    "symbol", "ticker", "valid_from", "valid_to", "origin", "composite_figi", "reference_raw_id",
    "evidence",
)  # fmt: skip
ACCOUNT_FIELDS = (
    "kind", "symbol", "ticker", "valid_from", "valid_to", "disposition", "reason", "pieces",
)  # fmt: skip

Interval = tuple[date, date]  # [start, end), end date.max when open


@dataclass(frozen=True)
class OldSpan:
    symbol: str
    ticker: str
    start: date
    end: date  # date.max when open
    composite_figi: str
    reference_raw_id: str
    evidence: str  # canonical JSON


@dataclass(frozen=True)
class WitnessRegion:
    """One row of ``documentary_spans.csv``: the span the witness judged."""

    symbol: str
    start: date
    end: date
    decision: str
    placed_sessions: int


@dataclass(frozen=True)
class DocPlacement:
    """One row of ``documentary_placements.csv``."""

    symbol: str
    ticker: str
    start: date
    end: date
    sessions: int
    reason: str
    documentary_identity: str
    corroboration: str
    lead_read: str


@dataclass(frozen=True)
class NewSpan:
    symbol: str
    ticker: str
    start: date
    end: date
    origin: str  # kept | clipped | placement
    composite_figi: str
    reference_raw_id: str
    evidence: str


@dataclass(frozen=True)
class GapRow:
    symbol: str
    scope: str
    reason: str
    start: date | None
    end: date | None
    detail: str


@dataclass
class DocumentaryMap:
    spans: list[NewSpan]
    gaps: list[GapRow]
    accounting: list[dict[str, str]]


def _cut(a: date, b: date, c: date, d: date) -> list[Interval]:
    """[a, b) minus [c, d)."""
    if c >= b or d <= a:
        return [(a, b)]
    return [p for p in ((a, min(b, c)), (max(a, d), b)) if p[0] < p[1]]


def _minus(base: Sequence[Interval], cuts: Sequence[Interval]) -> list[Interval]:
    out = list(base)
    for c, d in cuts:
        out = [piece for a, b in out for piece in _cut(a, b, c, d)]
    return out


def _union(items: Sequence[Interval]) -> list[Interval]:
    """Sorted, touching and overlapping intervals merged."""
    merged: list[Interval] = []
    for a, b in sorted(items):
        if merged and a <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], b))
        else:
            merged.append((a, b))
    return merged


def _meet(a: Sequence[Interval], b: Sequence[Interval]) -> list[Interval]:
    return [(max(x, z), min(y, w)) for x, y in a for z, w in b if max(x, z) < min(y, w)]


def _iso(d: date | None) -> str:
    return "" if d is None or d in (_OPEN, date.min) else d.isoformat()


def _pieces(items: Sequence[Interval]) -> str:
    return ";".join(f"{_iso(a)}..{_iso(b)}" for a, b in items)


def _doc_date(cell: str) -> date:
    return date.fromisoformat(cell) if cell else _OPEN


def read_old_spans(rows: Sequence[Mapping[str, str]]) -> list[OldSpan]:
    return [
        OldSpan(
            r["symbol"], r["ticker"], date.fromisoformat(r["valid_from"]),
            _doc_date(r["valid_to"]), r["composite_figi"], r["reference_raw_id"], r["evidence"],
        )
        for r in rows
    ]  # fmt: skip


def _require_sha(data: bytes, sha256: str, what: str) -> None:
    digest = hashlib.sha256(data).hexdigest()
    if digest != sha256:
        raise ValueError(f"{what} sha256 {digest} is not the pinned {sha256}")


def read_witness_regions(csv_bytes: bytes, sha256: str) -> list[WitnessRegion]:
    _require_sha(csv_bytes, sha256, "documentary_spans.csv")
    return [
        WitnessRegion(
            r["symbol"], date.fromisoformat(r["span_start"]), date.fromisoformat(r["span_end"]),
            r["decision"], int(r["placed_sessions"]),
        )
        for r in csv.DictReader(io.StringIO(csv_bytes.decode()))
    ]  # fmt: skip


def read_doc_placements(csv_bytes: bytes, sha256: str) -> list[DocPlacement]:
    _require_sha(csv_bytes, sha256, "documentary_placements.csv")
    return [
        DocPlacement(
            r["symbol"], r["file_ticker"], date.fromisoformat(r["start"]),
            date.fromisoformat(r["end"]), int(r["sessions"]), r["reason"],
            r["documentary_identity"], r["corroboration"], r["lead_read"],
        )
        for r in csv.DictReader(io.StringIO(csv_bytes.decode()))
    ]  # fmt: skip


def read_gap_rows(gap_bytes: bytes) -> list[GapRow]:
    return [
        GapRow(
            r["symbol"], r["scope"], r["reason"],
            date.fromisoformat(r["valid_from"]) if r["valid_from"] else None,
            date.fromisoformat(r["valid_to"]) if r["valid_to"] else None, r["detail"],
        )
        for r in csv.DictReader(io.StringIO(gap_bytes.decode()))
    ]  # fmt: skip


def check_pinned_map(map_dir_name: str, gap_bytes: bytes, claimed_digest: str) -> None:
    """The placements were made against the pinned map ``claimed_digest`` (12 hex digits of its
    gap list); refuses unless the map directory is that map and is internally consistent."""
    actual = hashlib.sha256(gap_bytes).hexdigest()[:12]
    if not map_dir_name.endswith(f"_{actual}"):
        raise ValueError(f"map directory {map_dir_name} holds a gap list with digest {actual}")
    if actual != claimed_digest:
        raise ValueError(
            f"the placements are pinned to map digest {claimed_digest}, the map given is {actual}"
        )


def _validate_documentary_inputs(
    regions: Sequence[WitnessRegion],
    placements: Sequence[DocPlacement],
    figi_by_symbol: Mapping[str, str],
) -> dict[WitnessRegion, list[DocPlacement]]:
    """Each placement sits inside one placed witness span of its name, the sessions add up, no
    placements overlap, and every placed name has a composite FIGI. Returns placements by span."""
    by_region: dict[WitnessRegion, list[DocPlacement]] = {r: [] for r in regions}
    if len(by_region) != len(regions):
        raise ValueError("duplicate witness span rows")
    for p in placements:
        homes = [
            r for r in regions if r.symbol == p.symbol and r.start <= p.start and p.end <= r.end
        ]
        if len(homes) != 1:
            raise ValueError(
                f"placement {p.symbol} {p.ticker} {p.start}..{p.end} lies in {len(homes)} "
                "witness spans, not one"
            )
        if homes[0].decision not in DOC_PLACED:
            raise ValueError(f"placement {p.symbol} {p.start} sits in a {homes[0].decision} span")
        if p.symbol not in figi_by_symbol:
            raise ValueError(f"placement {p.symbol} {p.ticker}: no composite FIGI in the map")
        by_region[homes[0]].append(p)
    for r, held in by_region.items():
        if (r.decision in DOC_PLACED) != bool(held):
            raise ValueError(
                f"witness span {r.symbol} {r.start} is {r.decision} with {len(held)} placements"
            )
        if sum(p.sessions for p in held) != r.placed_sessions:
            raise ValueError(
                f"witness span {r.symbol} {r.start}: placements hold "
                f"{sum(p.sessions for p in held)} sessions, the span says {r.placed_sessions}"
            )
        ranges = sorted((p.start, p.end) for p in held)
        if any(ranges[i][1] > ranges[i + 1][0] for i in range(len(ranges) - 1)):
            raise ValueError(f"placements overlap inside {r.symbol} {r.start}")
    return by_region


def _gap_account(
    g: GapRow, disposition: str, reason: str, pieces: Sequence[Interval]
) -> dict[str, str]:
    return {
        "kind": "gap", "symbol": g.symbol, "ticker": g.reason, "valid_from": _iso(g.start),
        "valid_to": _iso(g.end), "disposition": disposition, "reason": reason,
        "pieces": _pieces(pieces),
    }  # fmt: skip


def plan_documentary_map(
    old_spans: Sequence[OldSpan],
    gap_rows: Sequence[GapRow],
    regions: Sequence[WitnessRegion],
    placements: Sequence[DocPlacement],
    placements_sha256: str,
) -> DocumentaryMap:
    """The new map version (module docstring). Pure; raises on any input it cannot account."""
    figi = {s.symbol: s.composite_figi for s in old_spans}
    by_region = _validate_documentary_inputs(regions, placements, figi)
    cuts: dict[str, list[Interval]] = {}
    for r, held in by_region.items():
        if held:
            cuts.setdefault(r.symbol, []).append((r.start, r.end))
    placed_of: dict[str, list[Interval]] = {}
    for p in placements:
        placed_of.setdefault(p.symbol, []).append((p.start, p.end))

    spans: list[NewSpan] = []
    accounting: list[dict[str, str]] = []
    for s in sorted(old_spans, key=lambda x: (x.symbol, x.start, x.ticker)):
        pieces = _minus([(s.start, s.end)], cuts.get(s.symbol, ()))
        whole = pieces == [(s.start, s.end)]
        spans.extend(
            NewSpan(
                s.symbol, s.ticker, a, b, "kept" if whole else "clipped", s.composite_figi,
                s.reference_raw_id, s.evidence,
            )
            for a, b in pieces
        )  # fmt: skip
        if whole:
            disposition, reason = "kept", ""
        elif not pieces:
            disposition, reason = "removed", "inside a witness span that holds placements"
        else:
            disposition = "split" if len(pieces) > 1 else "clipped"
            reason = "witness span cut out"
        accounting.append(
            {
                "kind": "span", "symbol": s.symbol, "ticker": s.ticker,
                "valid_from": _iso(s.start), "valid_to": _iso(s.end),
                "disposition": disposition, "reason": reason, "pieces": _pieces(pieces),
            }
        )  # fmt: skip
    for p in sorted(placements, key=lambda x: (x.symbol, x.start, x.ticker)):
        evidence = {
            "amendment": DOC_AMENDMENT,
            "placements_sha256": placements_sha256,
            "gap_reason": p.reason,
            "documentary_identity": p.documentary_identity,
            "corroboration": p.corroboration,
            "lead_read": p.lead_read,
            "sessions": p.sessions,
        }
        spans.append(
            NewSpan(
                p.symbol, p.ticker, p.start, p.end, "placement", figi[p.symbol], "",
                canonical_json(evidence),
            )
        )  # fmt: skip
        accounting.append(
            {
                "kind": "placement", "symbol": p.symbol, "ticker": p.ticker,
                "valid_from": _iso(p.start), "valid_to": _iso(p.end), "disposition": "added",
                "reason": f"{p.sessions} sessions, {p.documentary_identity}",
                "pieces": _pieces([(p.start, p.end)]),
            }
        )  # fmt: skip

    gaps: list[GapRow] = []
    for g in gap_rows:
        own = placed_of.get(g.symbol, ())
        whole_range = [(g.start or date.min, g.end or _OPEN)]
        pieces = _minus(whole_range, own) if g.scope == "span" else whole_range
        for a, b in pieces:
            gaps.append(
                GapRow(
                    g.symbol, g.scope, g.reason, None if a == date.min else a,
                    None if b == _OPEN else b, g.detail,
                )
            )  # fmt: skip
        disposition = "kept" if pieces == whole_range else ("clipped" if pieces else "removed")
        reason = "" if disposition == "kept" else "placements cover it"
        accounting.append(_gap_account(g, disposition, reason, pieces))
    for r, held in by_region.items():
        if r.decision != "placed_partial":
            continue
        lost = _meet(
            [(s.start, s.end) for s in old_spans if s.symbol == r.symbol], [(r.start, r.end)]
        )
        # Only dated gap rows that overlap this witness span already record lost coverage here;
        # a name-wide undated row (start and end empty) records none of it.
        existing = [
            (g.start or date.min, g.end or _OPEN)
            for g in gaps
            if g.symbol == r.symbol
            and (g.start or g.end)
            and (g.start or date.min) < r.end
            and (g.end or _OPEN) > r.start
        ]
        for a, b in _union(_minus(_minus(lost, [(p.start, p.end) for p in held]), existing)):
            detail = canonical_json(
                {"decision": r.decision, "witness_span": [_iso(r.start), _iso(r.end)]}
            )
            row = GapRow(r.symbol, "span", IDENTITY_UNPLACED, a, b, detail)
            gaps.append(row)
            accounting.append(
                _gap_account(row, "added", "old coverage cut out, not placed", [(a, b)])
            )
    result = DocumentaryMap(
        sorted(spans, key=lambda x: (x.symbol, x.start, x.ticker)),
        sorted(gaps, key=lambda g: (g.symbol, g.start or date.min, g.reason, g.end or _OPEN)),
        accounting,
    )
    _audit(result, old_spans, cuts, placed_of, len(gap_rows))
    return result


def _audit(
    result: DocumentaryMap,
    old_spans: Sequence[OldSpan],
    cuts: Mapping[str, Sequence[Interval]],
    placed_of: Mapping[str, Sequence[Interval]],
    n_gap_rows: int,
) -> None:
    """The new map is the old one with the witness spans cut out and the placements put in, per
    name; spans of a name never overlap; a ticker is held by one name at a time."""
    for symbol in sorted({s.symbol for s in old_spans}):
        old = [(s.start, s.end) for s in old_spans if s.symbol == symbol]
        expect = _union(_minus(old, cuts.get(symbol, ())) + list(placed_of.get(symbol, ())))
        new = sorted((s.start, s.end) for s in result.spans if s.symbol == symbol)
        if any(new[i][1] > new[i + 1][0] for i in range(len(new) - 1)):
            raise RuntimeError(f"{symbol}: spans of one name overlap")
        if _union(new) != expect:
            raise RuntimeError(
                f"{symbol}: new coverage differs from old minus cuts plus placements"
            )
    holders: dict[str, list[tuple[date, date, str]]] = {}
    for s in result.spans:
        holders.setdefault(s.ticker, []).append((s.start, s.end, s.symbol))
    for ticker, held in holders.items():
        for a, b, sym in held:
            for c, d, other in held:
                if sym < other and a < d and c < b:
                    raise RuntimeError(
                        f"ticker {ticker} held by {sym} and {other} over {max(a, c)}"
                    )
    spans_in = sum(r["kind"] == "span" for r in result.accounting)
    gaps_in = sum(r["kind"] == "gap" and r["disposition"] != "added" for r in result.accounting)
    if (spans_in, gaps_in) != (len(old_spans), n_gap_rows):
        raise RuntimeError(f"accounted {spans_in} spans and {gaps_in} gap rows of the input")


def _csv_bytes(fields: Sequence[str], rows: Sequence[Mapping[str, str]]) -> bytes:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, list(fields), lineterminator="\r\n")
    writer.writeheader()
    writer.writerows(rows)
    return buf.getvalue().encode()


def spans_csv(spans: Sequence[NewSpan | OldSpan]) -> bytes:
    return _csv_bytes(
        SPAN_FIELDS,
        [
            {
                "symbol": s.symbol, "ticker": s.ticker, "valid_from": _iso(s.start),
                "valid_to": _iso(s.end), "origin": getattr(s, "origin", "pinned"),
                "composite_figi": s.composite_figi, "reference_raw_id": s.reference_raw_id,
                "evidence": s.evidence,
            }
            for s in spans
        ],
    )  # fmt: skip


def gap_list_csv(gaps: Sequence[GapRow]) -> bytes:
    return _csv_bytes(
        GAP_FIELDS,
        [
            {
                "symbol": g.symbol, "scope": g.scope, "reason": g.reason,
                "valid_from": _iso(g.start), "valid_to": _iso(g.end), "detail": g.detail,
            }
            for g in gaps
        ],
    )  # fmt: skip


def map_diff(old_spans: Sequence[OldSpan], result: DocumentaryMap) -> dict[str, Any]:
    """Old map against new: span rows added and removed, what became of each old span, and the
    sessions the placements cover (as the witness counted them)."""
    old_keys = {(s.symbol, s.ticker, s.start, s.end) for s in old_spans}
    new_keys = {(s.symbol, s.ticker, s.start, s.end) for s in result.spans}
    by_disposition = Counter(r["disposition"] for r in result.accounting if r["kind"] == "span")
    placements = [r for r in result.accounting if r["kind"] == "placement"]
    changed = {
        r["symbol"] for r in result.accounting if r["kind"] != "gap" and r["disposition"] != "kept"
    }
    return {
        "old_spans": len(old_spans),
        "new_spans": len(result.spans),
        "span_rows_removed": len(old_keys - new_keys),
        "span_rows_added": len(new_keys - old_keys),
        "old_spans_by_disposition": dict(sorted(by_disposition.items())),
        "placements_added": len(placements),
        "sessions_newly_covered": sum(int(r["reason"].split()[0]) for r in placements),
        "gap_rows": len(result.gaps),
        "gap_rows_identity_unplaced": sum(g.reason == IDENTITY_UNPLACED for g in result.gaps),
        "names_changed": sorted(changed),
    }


def reconcile_coverage(
    spans: Sequence[NewSpan],
    rows: Mapping[str, Sequence[tuple[str, str, str]]],
    expected: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    """Per timeframe, how many map_gap rows (symbol, session, file ticker) a new span of that
    name and ticker holds, against ``coverage_summary.json``."""
    held: dict[tuple[str, str], list[Interval]] = {}
    for s in spans:
        held.setdefault((s.symbol, s.ticker), []).append((s.start, s.end))
    out: dict[str, Any] = {}
    for tf, items in rows.items():
        covered = sum(
            any(a <= date.fromisoformat(session) < b for a, b in held.get((symbol, ticker), ()))
            for symbol, session, ticker in items
        )
        want = expected[tf]
        out[tf] = {
            "map_gap_rows": len(items),
            "covered": covered,
            "expected_map_gap_rows": want["map_gap_rows"],
            "expected_covered": want["covered"],
            "reconciles": (len(items), covered) == (want["map_gap_rows"], want["covered"]),
        }
    return out


def render_documentary_map(
    old_spans: Sequence[OldSpan],
    result: DocumentaryMap,
    inputs: Mapping[str, Any],
    reconciliation: Mapping[str, Any] | None,
    version_date: str,
) -> tuple[str, dict[str, bytes]]:
    """The directory name (``<version_date>_<digest12>``, the digest of the gap list as the
    amender derives it) and every file's bytes. No clock is read."""
    gap = gap_list_csv(result.gaps)
    new_spans = spans_csv(result.spans)
    pinned = spans_csv(old_spans)
    doc = {
        "inputs": dict(inputs),
        "pinned_spans_sha256": hashlib.sha256(pinned).hexdigest(),
        "gap_list_sha256": hashlib.sha256(gap).hexdigest(),
        "spans_sha256": hashlib.sha256(new_spans).hexdigest(),
        "diff": map_diff(old_spans, result),
        "reconciliation": reconciliation,
    }
    files = {
        "gap_list.csv": gap,
        "spans.csv": new_spans,
        "pinned_spans.csv": pinned,
        "span_accounting.csv": _csv_bytes(ACCOUNT_FIELDS, result.accounting),
        "map_diff.json": (json.dumps(doc, indent=2, sort_keys=True) + "\n").encode(),
    }
    return f"{version_date}_{hashlib.sha256(gap).hexdigest()[:12]}", files


def _answers(rows: list) -> dict[str, Answer]:
    return {r["request_key"]: Answer(r["id"], r["served_at"], r["body"]) for r in rows}


def _identifier_rows(proposal: Proposal) -> set[tuple]:
    return {
        (i.symbol, i.scheme, i.value, i.valid_from, None, i.reference_raw_id)
        for i in proposal.identifiers
    }


def _span_rows(proposal: Proposal) -> set[tuple]:
    return {
        (
            s.symbol,
            s.ticker,
            s.valid_from,
            s.valid_to,
            s.reference_raw_id,
            canonical_json(s.evidence),
        )
        for s in proposal.spans
    }


def write_gap_list(proposal: Proposal, partition: dict, out_root: Path) -> Path:
    """The gap list (one row per gap) and the partition, under a directory named by digest."""
    out = out_root / f"{datetime.now(UTC):%Y%m%d}_{proposal.digest[:12]}"
    out.mkdir(parents=True, exist_ok=True)
    with (out / "gap_list.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["symbol", "scope", "reason", "valid_from", "valid_to", "detail"])
        for gap in proposal.gaps:
            writer.writerow(
                [
                    gap.symbol,
                    "instrument" if gap.valid_from is None else "span",
                    gap.reason,
                    gap.valid_from.isoformat() if gap.valid_from else "",
                    gap.valid_to.isoformat() if gap.valid_to else "",
                    canonical_json(gap.detail),
                ]
            )
    (out / "partition.json").write_text(json.dumps(partition, indent=2, sort_keys=True) + "\n")
    return out


class TickerEntityMapWriter(BaseBatch):
    """Batch service: reference answers -> security_identifier and ticker_event."""

    job_name = _JOB
    compute_version = "1.0.0"

    def __init__(self, db_dsn: str, apply: bool, out_root: Path = _OUT_ROOT):
        super().__init__(db_dsn)
        self._apply = apply
        self._out_root = out_root

    async def _inputs(self, conn: asyncpg.Connection) -> MapInputs:
        instruments = {r["symbol"]: r["asset_class"] for r in await conn.fetch(_INSTRUMENTS_SQL)}
        pages = await conn.fetchrow(_DELISTED_PAGES_SQL)
        if not pages["pages"] or pages["ok"] != pages["pages"]:
            raise RuntimeError(f"delisted universe pages: {pages['ok']} OK of {pages['pages']}")
        delisted = tuple(
            DelistedTicker(r["ticker"], r["delisted_utc"], r["id"])
            for r in await conn.fetch(_DELISTED_SQL)
        )
        return MapInputs(
            instruments=instruments,
            # Overview: our symbols' answers only. Events: every answer, which the
            # FIGI-grouping needs.
            overview=_answers(
                await conn.fetch(_ANSWERS_SQL, "massive", "overview", sorted(instruments))
            ),
            events=_answers(await conn.fetch(_ANSWERS_SQL, "massive", "events", None)),
            delisted=delisted,
            contract_details=_answers(
                await conn.fetch(_ANSWERS_SQL, "ibkr", "contract_details", None)
            ),
            figi_mapping=_answers(
                await conn.fetch(_ANSWERS_SQL, "openfigi", "mapping_isin_us", None)
            ),
        )

    async def _write(self, conn: asyncpg.Connection, proposal: Proposal) -> str:
        current_ids = {tuple(r.values()) for r in await conn.fetch(_CURRENT_IDENTIFIERS_SQL)}
        current_spans = {
            (
                r["symbol"],
                r["ticker"],
                r["valid_from"],
                r["valid_to"],
                r["id"],
                canonical_json(r["evidence"]),
            )
            for r in await conn.fetch(_CURRENT_SPANS_SQL)
        }
        if current_ids or current_spans:
            if current_ids == _identifier_rows(proposal) and current_spans == _span_rows(proposal):
                return "already_applied"
            raise RuntimeError(
                f"security_identifier/ticker_event already hold {len(current_ids)}/"
                f"{len(current_spans)} unretired rows that differ from the proposal; a "
                "correction retires and replaces rows and is not this writer's job"
            )
        ids = proposal.identifiers
        returned = await conn.fetch(
            _INSERT_IDENTIFIERS_SQL,
            [i.symbol for i in ids],
            [i.scheme for i in ids],
            [i.value for i in ids],
            [i.valid_from for i in ids],
            [i.reference_raw_id for i in ids],
        )
        id_for = {(r["symbol"], r["scheme"]): r["security_identifier_id"] for r in returned}
        spans = proposal.spans
        evidence = [canonical_json(s.evidence) for s in spans]
        await conn.execute(
            _INSERT_SPANS_SQL,
            [id_for[(s.symbol, SPAN_SCHEME)] for s in spans],
            [s.symbol for s in spans],
            [s.ticker for s in spans],
            [s.valid_from for s in spans],
            [s.valid_to for s in spans],
            [s.reference_raw_id for s in spans],
            evidence,
        )
        return "inserted"

    async def execute(self, pool: asyncpg.Pool) -> None:
        async with pool.acquire() as conn:
            inputs = await self._inputs(conn)
            proposal = propose_ticker_entity_map(inputs)
            partition = proposal.partition()
            if sum(partition.values()) != len(inputs.instruments):
                raise RuntimeError(
                    f"partition {partition} does not cover {len(inputs.instruments)}"
                )
            status_rows = await conn.fetch(_EVENTS_STATUS_SQL)
            events_status = {f"{r['query']}:{r['status']}": r["n"] for r in status_rows}
            not_found = sum(r["n"] for r in status_rows if r["status"] == "NOT_FOUND")
            report = {
                "digest": proposal.digest,
                "apply": self._apply,
                "instruments": len(inputs.instruments),
                "partition": partition,
                "span_gaps": proposal.span_gaps(),
                "identifiers": len(proposal.identifiers),
                "spans": len(proposal.spans),
                "unreadable_events_chains": list(proposal.unreadable_chains),
                "events_answers_by_query_and_body_status": events_status,
                "events_not_found_rate": round(not_found / max(sum(events_status.values()), 1), 6),
            }
            out = write_gap_list(proposal, report, self._out_root)
            # The cross-security check is only as complete as the chains it could read: an
            # unreadable chain or a failed events ask (neither OK nor NOT_FOUND) could hide a
            # rival claim, so the apply refuses while any exists.
            failed = {
                k: n for k, n in events_status.items() if not k.endswith((":OK", ":NOT_FOUND"))
            }
            if self._apply and (proposal.unreadable_chains or failed):
                raise RuntimeError(
                    f"refusing --apply: unreadable chains {list(proposal.unreadable_chains)}, "
                    f"failed events answers {failed}"
                )
            try:
                async with conn.transaction():
                    outcome = await self._write(conn, proposal)
                    if not self._apply:
                        raise _Rehearsal
            except _Rehearsal:
                outcome = "rolled_back"
        self.logger.info("ticker_entity_map.run_done", outcome=outcome, out=str(out), **report)
        print(json.dumps({"outcome": outcome, "out": str(out), **report}, indent=2, default=str))


class TickerEntityMapAmender(BaseBatch):
    """The --amend run (module docstring): additive rows from the identity witness."""

    job_name = _JOB
    compute_version = "1.0.0"

    def __init__(self, db_dsn: str, apply: bool, args: argparse.Namespace,
                 out_root: Path = _OUT_ROOT):  # fmt: skip
        super().__init__(db_dsn)
        self._apply = apply
        self._args = args
        self._out_root = out_root

    async def execute(self, pool: asyncpg.Pool) -> None:
        from scripts.ops.bars.ops_massive_policy_plan import archive_end_of
        from src.intelligence.bars.ticker_entity_map import MASSIVE_ARCHIVE_START

        args = self._args
        placed = read_placed(
            args.amend.read_bytes(), args.amend_candidates.read_bytes(), args.amend_sha256
        )
        gap_bytes = args.gap_list.read_bytes()
        gap_rows = list(csv.DictReader(io.StringIO(gap_bytes.decode())))
        archive_end = archive_end_of(args.manifest.read_bytes())
        async with pool.acquire() as conn:
            identifiers: dict[str, dict[str, str]] = {}
            id_rows = {}
            for r in await conn.fetch(_AMEND_IDS_SQL):
                identifiers.setdefault(r["symbol"], {})[r["scheme"]] = r["value"]
                id_rows[(r["symbol"], r["scheme"])] = r["security_identifier_id"]
            isin_answers = {
                r["isin"]: (r["id"], r["body"]) for r in await conn.fetch(_AMEND_FIGI_SQL)
            }
            live = [tuple(r.values()) for r in await conn.fetch(_AMEND_SPANS_SQL)]
            overview = {r["symbol"]: r["id"] for r in await conn.fetch(_AMEND_OVERVIEW_SQL)}
            plan = plan_amendment(
                placed, identifiers, isin_answers, live, gap_rows, MASSIVE_ARCHIVE_START,
                archive_end,
            )  # fmt: skip
            if len(plan.removed_gaps) != len(plan.spans):
                raise RuntimeError(
                    f"{len(plan.spans)} spans placed but {len(plan.removed_gaps)} gap rows "
                    "match them: the gap list is not the one the witness read"
                )
            missing = sorted({p.symbol for p in plan.spans} - overview.keys())
            if missing:
                raise RuntimeError(f"no captured overview answer to cite for {missing}")
            report = {
                "apply": self._apply,
                "spans_to_insert": len(plan.spans),
                "identifiers_to_mint": len(plan.mint),
                "gap_rows_removed": len(plan.removed_gaps),
                "kept_as_gap": plan.kept_as_gap,
                "gap_list_in": {"path": str(args.gap_list),
                                "sha256": hashlib.sha256(gap_bytes).hexdigest()},
                "witness_spans_sha256": args.amend_sha256,
            }  # fmt: skip
            removed = {id(g) for g in plan.removed_gaps}
            kept_rows = [g for g in gap_rows if id(g) not in removed]
            buf = io.StringIO()
            writer = csv.DictWriter(buf, list(gap_rows[0]), lineterminator="\r\n")
            writer.writeheader()
            writer.writerows(kept_rows)
            new_gap = buf.getvalue().encode()
            out = self._out_root / (
                f"{datetime.now(UTC):%Y%m%d}_{hashlib.sha256(new_gap).hexdigest()[:12]}"
            )
            try:
                async with conn.transaction():
                    if plan.mint:
                        for r in await conn.fetch(
                            _INSERT_IDENTIFIERS_SQL,
                            [m[0] for m in plan.mint],
                            [m[1] for m in plan.mint],
                            [m[2] for m in plan.mint],
                            [datetime.now(UTC).date()] * len(plan.mint),
                            [m[3] for m in plan.mint],
                        ):
                            id_rows[(r["symbol"], r["scheme"])] = r["security_identifier_id"]
                    spans = plan.spans
                    await conn.execute(
                        _INSERT_SPANS_SQL,
                        [id_rows[(p.symbol, SPAN_SCHEME)] for p in spans],
                        [p.symbol for p in spans],
                        [p.ticker for p in spans],
                        [p.start for p in spans],
                        [p.end for p in spans],
                        [overview[p.symbol] for p in spans],
                        [canonical_json(p.evidence) for p in spans],
                    )
                    if not self._apply:
                        raise _Rehearsal
                outcome = "inserted"
            except _Rehearsal:
                outcome = "rolled_back"
        if self._apply:
            out.mkdir(parents=True, exist_ok=True)
            (out / "gap_list.csv").write_bytes(new_gap)
            (out / "amendment.json").write_text(
                json.dumps({**report, "outcome": outcome, "minted": plan.mint}, indent=2,
                           default=str) + "\n")  # fmt: skip
        self.logger.info("ticker_entity_map.amend_done", outcome=outcome, out=str(out))
        print(json.dumps({"outcome": outcome, "out": str(out), **report}, indent=2, default=str))


_DOC_SPANS_SQL = """
SELECT e.ticker_event_id, e.symbol, e.ticker, e.valid_from, e.valid_to,
       e.reference_raw_id::text AS reference_raw_id, e.evidence, e.security_identifier_id,
       i.value AS composite_figi
  FROM ticker_event_current e
  JOIN security_identifier_current i
    ON i.security_identifier_id = e.security_identifier_id AND i.scheme = 'composite_figi'
 WHERE e.vendor = 'massive'
"""


def live_old_spans(rows: Sequence[Mapping[str, Any]]) -> list[OldSpan]:
    """The live spans (``_DOC_SPANS_SQL`` rows) as the pinned map's ``OldSpan`` list, in the
    pinned file's order, so ``spans_csv`` of it is byte-comparable to ``pinned_spans.csv``."""
    return read_old_spans(
        sorted(
            (
                {
                    "symbol": r["symbol"],
                    "ticker": r["ticker"],
                    "valid_from": r["valid_from"].isoformat(),
                    "valid_to": r["valid_to"].isoformat() if r["valid_to"] else "",
                    "composite_figi": r["composite_figi"],
                    "reference_raw_id": r["reference_raw_id"],
                    "evidence": canonical_json(r["evidence"]),
                }
                for r in rows
            ),
            key=lambda r: (r["symbol"], r["valid_from"], r["ticker"]),
        )
    )


def refuse_install_path(out: Path, out_root: Path) -> None:
    """The documentary run writes a scratch directory only; installing a map is a separate step."""
    if out.resolve().is_relative_to(out_root.resolve()):
        raise ValueError(f"--out {out} is inside {out_root}: this run writes a scratch map only")


def write_map_files(out: Path, files: Mapping[str, bytes]) -> None:
    """Write the files; an existing file with other bytes refuses (a map version is immutable)."""
    out.mkdir(parents=True, exist_ok=True)
    for name, data in files.items():
        target = out / name
        if target.exists() and target.read_bytes() != data:
            raise RuntimeError(f"{target} exists with other bytes")
        target.write_bytes(data)


def _read_lost_rows(path: Path, ticker_column: str) -> list[tuple[str, str, str]]:
    """The map_gap rows of a classified lost-slot file as (symbol, session, file ticker)."""
    with path.open(newline="", encoding="utf-8") as handle:
        return [
            (r["symbol"], r["session"], r[ticker_column])
            for r in csv.DictReader(handle)
            if r["class"] == "map_gap"
        ]


class TickerEntityMapDocumentary(BaseBatch):
    """The --documentary run (module docstring): a new map version in a scratch directory. Reads
    the live spans; writes no table."""

    job_name = _JOB
    compute_version = "1.0.0"

    def __init__(self, db_dsn: str, args: argparse.Namespace, out_root: Path = _OUT_ROOT):
        super().__init__(db_dsn)
        self._args = args
        self._out_root = out_root

    async def execute(self, pool: asyncpg.Pool) -> None:
        args = self._args
        refuse_install_path(args.out, self._out_root)
        gap_bytes = (args.map_dir / "gap_list.csv").read_bytes()
        check_pinned_map(args.map_dir.name, gap_bytes, args.pinned_map_digest)
        placements = read_doc_placements(args.documentary.read_bytes(), args.documentary_sha256)
        regions = read_witness_regions(args.regions.read_bytes(), args.regions_sha256)
        async with pool.acquire() as conn:
            rows = await conn.fetch(_DOC_SPANS_SQL)
        old_spans = live_old_spans(rows)
        live_sha = hashlib.sha256(spans_csv(old_spans)).hexdigest()
        if args.pinned_spans_sha256 and args.pinned_spans_sha256 != live_sha:
            raise ValueError(f"live spans sha256 {live_sha} is not {args.pinned_spans_sha256}")
        result = plan_documentary_map(
            old_spans, read_gap_rows(gap_bytes), regions, placements, args.documentary_sha256
        )
        reconciliation = None
        if args.lost_1d and args.lost_5m and args.coverage_summary:
            hidden = [tuple(h.split(":")) for h in args.hidden_1d]
            reconciliation = reconcile_coverage(
                result.spans,
                {
                    "1d": _read_lost_rows(args.lost_1d, "file_ticker") + hidden,
                    "5m": _read_lost_rows(args.lost_5m, "alt_ticker"),
                },
                json.loads(args.coverage_summary.read_text()),
            )
        require_reconciled(reconciliation)
        inputs = {
            "pinned_map": args.map_dir.name,
            "pinned_map_gap_list_sha256": hashlib.sha256(gap_bytes).hexdigest(),
            "placements_sha256": args.documentary_sha256,
            "witness_spans_sha256": args.regions_sha256,
        }
        name, files = render_documentary_map(
            old_spans, result, inputs, reconciliation, args.version_date
        )
        write_map_files(args.out / name, files)
        self.logger.info("ticker_entity_map.documentary_done", out=str(args.out / name))
        print(json.dumps({"out": str(args.out / name), **json.loads(files["map_diff.json"])},
                         indent=2, sort_keys=True))  # fmt: skip


# ---------------------------------------------------------------------------------------------
# Install (design 8c, 2026-11-14): a scratch map version becomes the live ``ticker_event`` rows.
# ---------------------------------------------------------------------------------------------

INSTALL_REASON = "ticker_map_install"
ROLLBACK_REASON = "ticker_map_rollback"
MAP_FILES = (
    "gap_list.csv", "spans.csv", "pinned_spans.csv", "span_accounting.csv", "map_diff.json",
)  # fmt: skip
_MAP_NAME = re.compile(r"^\d{8}_([0-9a-f]{12})$")
_ROLLED_BACK_ROOT = _REPO_ROOT / "data" / "ticker_entity_map_rolled_back"

SpanKey = tuple[str, str, date, date]  # symbol, ticker, start, end (date.max when open)


class InstallRefused(ValueError):
    """The install or rollback cannot proceed; nothing was written."""


@dataclass(frozen=True)
class MapFiles:
    """A scratch map directory, read and checked against its own recorded hashes."""

    name: str
    digest: str
    raw: Mapping[str, bytes]
    diff: Mapping[str, Any]

    @property
    def pinned_sha256(self) -> str:
        return hashlib.sha256(self.raw["pinned_spans.csv"]).hexdigest()


@dataclass(frozen=True)
class InstallPlan:
    status: str  # install | already_installed
    retire: tuple[tuple[SpanKey, str], ...]  # key, disposition of the old span
    insert: tuple[NewSpan, ...]
    live_before: int
    live_after: int
    new_keys: frozenset[SpanKey]

    @property
    def touched_symbols(self) -> set[str]:
        return {k[0] for k, _ in self.retire} | {s.symbol for s in self.insert}


@dataclass(frozen=True)
class HistoryRow:
    """One ``ticker_event`` row as the rollback reads it."""

    ticker_event_id: str
    security_identifier_id: Any
    symbol: str
    ticker: str
    start: date
    end: date | None
    reference_raw_id: str
    evidence: dict[str, Any]
    retired_reason: str | None

    @property
    def key(self) -> SpanKey:
        return (self.symbol, self.ticker, self.start, self.end or _OPEN)


@dataclass(frozen=True)
class RollbackPlan:
    install_id: str
    retire_ids: tuple[str, ...]  # the rows the install inserted, to retire
    restore: tuple[HistoryRow, ...]  # the rows the install retired, to insert back as copies
    pre_install_sha256: str
    map_dir: str


def require_reconciled(reconciliation: Mapping[str, Any] | None) -> None:
    """A map whose spans do not reproduce the lost-slot coverage counts is refused."""
    if not reconciliation:
        raise InstallRefused("the map carries no coverage reconciliation")
    bad = sorted(tf for tf, v in reconciliation.items() if not v["reconciles"])
    if bad:
        raise InstallRefused(f"coverage does not reconcile for {bad}: {reconciliation}")


def read_map_dir(path: Path) -> MapFiles:
    """The scratch map's files, refused unless the name, gap list digest and every hash its own
    ``map_diff.json`` records agree."""
    match = _MAP_NAME.match(path.name)
    if not match:
        raise InstallRefused(f"{path.name} is not a <YYYYMMDD>_<digest12> map directory")
    raw = {name: (path / name).read_bytes() for name in MAP_FILES}
    extra = sorted(p.name for p in path.iterdir() if p.name not in MAP_FILES)
    if extra:
        raise InstallRefused(f"{path} holds files that are not part of a map version: {extra}")
    doc = json.loads(raw["map_diff.json"])
    for name, field_name in (
        ("gap_list.csv", "gap_list_sha256"),
        ("spans.csv", "spans_sha256"),
        ("pinned_spans.csv", "pinned_spans_sha256"),
    ):
        if hashlib.sha256(raw[name]).hexdigest() != doc[field_name]:
            raise InstallRefused(f"{path / name} does not hash to {field_name} in map_diff.json")
    if not doc["gap_list_sha256"].startswith(match.group(1)):
        raise InstallRefused(f"{path.name} does not carry its gap list digest")
    return MapFiles(path.name, match.group(1), raw, doc)


def _span_rows(csv_bytes: bytes) -> dict[SpanKey, dict[str, str]]:
    listed = list(csv.DictReader(io.StringIO(csv_bytes.decode())))
    rows = {
        (r["symbol"], r["ticker"], date.fromisoformat(r["valid_from"]), _doc_date(r["valid_to"])): r
        for r in listed
    }
    if len(rows) != len(listed):
        raise InstallRefused("a span file holds a duplicate (symbol, ticker, valid_from, valid_to)")
    return rows


def verify_install_reconciliation(
    files: MapFiles,
    rows: Mapping[str, Sequence[tuple[str, str, str]]],
    expected: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    """Recompute the coverage reconciliation from the map's own ``spans.csv`` and the lost-slot
    inputs, refuse unless it holds and equals what the map recorded."""
    spans = [
        NewSpan(k[0], k[1], k[2], k[3], r["origin"], r["composite_figi"], "", "")
        for k, r in _span_rows(files.raw["spans.csv"]).items()
    ]
    recomputed = reconcile_coverage(spans, rows, expected)
    require_reconciled(recomputed)
    if files.diff.get("reconciliation") != recomputed:
        raise InstallRefused("the recomputed coverage reconciliation is not the one the map holds")
    return recomputed


def plan_install(
    files: MapFiles, live_old: Sequence[OldSpan], untouched: Collection[str]
) -> InstallPlan:
    """Retire the old spans the map cut and insert the spans it adds; the kept spans are not
    touched. Refuses when the live spans are not the pinned ones (drift), when the plan does not
    reconcile to ``span_accounting.csv`` and ``map_diff.json``, or when it touches a name in
    ``untouched``. A live set that already equals the map is a no-op."""
    live_keys = {(s.symbol, s.ticker, s.start, s.end) for s in live_old}
    new_rows = _span_rows(files.raw["spans.csv"])
    new_keys = frozenset(new_rows)
    if live_keys == new_keys:
        return InstallPlan("already_installed", (), (), len(live_keys), len(live_keys), new_keys)
    live_sha = hashlib.sha256(spans_csv(live_old)).hexdigest()
    if live_sha != files.pinned_sha256:
        raise InstallRefused(
            f"the live spans (sha256 {live_sha}) are not the map's pinned spans "
            f"({files.pinned_sha256}): the table moved since the map was built"
        )
    old_keys = set(_span_rows(files.raw["pinned_spans.csv"]))
    accounted = {
        (r["symbol"], r["ticker"], date.fromisoformat(r["valid_from"]), _doc_date(r["valid_to"])): r
        for r in csv.DictReader(io.StringIO(files.raw["span_accounting.csv"].decode()))
        if r["kind"] == "span"
    }
    retire_keys = old_keys - new_keys
    insert_keys = new_keys - old_keys
    cut = {k for k, r in accounted.items() if r["disposition"] != "kept"}
    diff = files.diff["diff"]
    if (
        set(accounted) != old_keys
        or cut != retire_keys
        or len(retire_keys) != diff["span_rows_removed"]
        or len(insert_keys) != diff["span_rows_added"]
        or len(new_keys) != diff["new_spans"]
        or len(old_keys) != diff["old_spans"]
    ):
        raise InstallRefused(
            "the span diff does not reconcile to span_accounting.csv/map_diff.json"
        )
    insert = tuple(
        NewSpan(
            k[0], k[1], k[2], k[3], new_rows[k]["origin"], new_rows[k]["composite_figi"],
            new_rows[k]["reference_raw_id"], new_rows[k]["evidence"],
        )
        for k in sorted(insert_keys)
    )  # fmt: skip
    if any(s.origin == "kept" for s in insert):
        raise InstallRefused("a span the map marks kept is not among the live spans")
    plan = InstallPlan(
        "install",
        tuple((k, accounted[k]["disposition"]) for k in sorted(retire_keys)),
        insert,
        len(old_keys),
        len(new_keys),
        new_keys,
    )
    hit = sorted(plan.touched_symbols & set(untouched))
    if hit:
        raise InstallRefused(f"the plan touches names that must stay as they are: {hit}")
    if len(old_keys) - len(plan.retire) + len(plan.insert) != len(new_keys):
        raise InstallRefused("row balance: live - retired + inserted is not the map's span count")
    return plan


def verify_balance(plan: InstallPlan, live_after: Collection[SpanKey]) -> None:
    """After the writes, before the commit: the live rows are exactly the map's spans."""
    keys = set(live_after)
    if len(live_after) != plan.live_after or keys != plan.new_keys:
        raise InstallRefused(
            f"row balance: {len(live_after)} live rows after the writes, the map has "
            f"{plan.live_after}; {len(keys - plan.new_keys)} extra, "
            f"{len(plan.new_keys - keys)} missing"
        )


def new_install_id(digest: str, now: datetime) -> str:
    return f"{digest}-{now:%Y%m%dT%H%M%SZ}"


def content_sha256(rows: Sequence[Mapping[str, Any]]) -> str:
    """Hash of a live span set by content, not by row id or recorded_at: what a rollback must
    reproduce."""
    lines = sorted(
        "|".join(
            (
                r["symbol"], r["ticker"], r["valid_from"].isoformat(),
                r["valid_to"].isoformat() if r["valid_to"] else "",
                str(r["security_identifier_id"]), str(r["reference_raw_id"]),
                canonical_json(r["evidence"]),
            )
        )
        for r in rows
    )  # fmt: skip
    return hashlib.sha256("\n".join(lines).encode()).hexdigest()


def install_evidence(span: NewSpan, lineage: Mapping[str, Any]) -> str:
    """The new row's evidence: the map's own, plus the install lineage under ``map_install``."""
    body = json.loads(span.evidence)
    if "map_install" in body:
        raise InstallRefused(f"{span.symbol} {span.ticker}: evidence already holds map_install")
    return canonical_json({**body, "map_install": {**lineage, "origin": span.origin}})


def retire_reason(install_id: str, digest: str, disposition: str) -> str:
    return f"{INSTALL_REASON} {install_id} map {digest}: old span {disposition}"


def plan_rollback(install_id: str, rows: Sequence[HistoryRow]) -> RollbackPlan:
    """Undo an install: retire the rows it inserted and insert back copies of the rows it
    retired. Refuses unless the table still holds exactly the install's result (a later install
    or amendment must be rolled back first)."""
    mark = f"{INSTALL_REASON} {install_id} "
    inserted = [
        r for r in rows if r.evidence.get("map_install", {}).get("install_id") == install_id
    ]
    live_inserted = [r for r in inserted if r.retired_reason is None]
    retired = [r for r in rows if r.retired_reason and r.retired_reason.startswith(mark)]
    if not inserted:
        raise InstallRefused(f"no rows were inserted by install {install_id}")
    lineage = {k: v for k, v in inserted[0].evidence["map_install"].items() if k != "origin"}
    if any(
        {k: v for k, v in r.evidence["map_install"].items() if k != "origin"} != lineage
        for r in inserted
    ):
        raise InstallRefused(f"install {install_id}: rows carry inconsistent lineage")
    if len(retired) != lineage["rows_retired"]:
        raise InstallRefused(
            f"install {install_id} retired {len(retired)} rows now, {lineage['rows_retired']} "
            "recorded: it was already rolled back or the history is damaged"
        )
    if len(live_inserted) != lineage["rows_inserted"]:
        raise InstallRefused(
            f"only {len(live_inserted)} of the {lineage['rows_inserted']} rows install "
            f"{install_id} inserted are live: it was already rolled back, or a later change retired them "
            "(roll that back first)"
        )
    return RollbackPlan(
        install_id,
        tuple(r.ticker_event_id for r in live_inserted),
        tuple(sorted(retired, key=lambda r: r.key)),
        lineage["pre_install_sha256"],
        lineage["map_dir"],
    )


def check_install_target(target: Path, raw: Mapping[str, bytes]) -> bool:
    """True when ``target`` already holds exactly the map (nothing to copy); False when absent;
    refuses when it exists with other content."""
    if not target.exists():
        return False
    held = {p.name: p.read_bytes() for p in target.iterdir() if p.is_file()}
    if held != dict(raw):
        raise InstallRefused(f"{target} exists with content other than this map")
    return True


_INSTALL_ROWS_SQL = """
SELECT ticker_event_id::text AS id, security_identifier_id, symbol, ticker, valid_from, valid_to,
       reference_raw_id::text AS reference_raw_id, evidence, retired_reason
  FROM ticker_event
 WHERE vendor = 'massive'
   AND (evidence->'map_install'->>'install_id' = $1 OR retired_reason LIKE $2)
"""
_RETIRE_SQL = """
UPDATE ticker_event SET retired_reason = u.reason
  FROM unnest($1::uuid[], $2::text[]) AS u(id, reason)
 WHERE ticker_event.ticker_event_id = u.id AND ticker_event.retired_at IS NULL
"""
_LOCK_SQL = "LOCK TABLE ticker_event IN SHARE ROW EXCLUSIVE MODE"
_LIVE_SQL = """
SELECT symbol, ticker, valid_from, valid_to, security_identifier_id,
       reference_raw_id::text AS reference_raw_id, evidence
  FROM ticker_event_current WHERE vendor = 'massive'
"""


def _row_key(r: Mapping[str, Any]) -> SpanKey:
    return (r["symbol"], r["ticker"], r["valid_from"], r["valid_to"] or _OPEN)


async def _retire(conn: asyncpg.Connection, ids: Sequence[Any], reasons: Sequence[str]) -> None:
    status = await conn.execute(_RETIRE_SQL, list(ids), list(reasons))
    if status != f"UPDATE {len(ids)}":
        raise InstallRefused(f"{status} rows retired, expected {len(ids)}")


def _stage(staging: Path, raw: Mapping[str, bytes]) -> None:
    shutil.rmtree(staging, ignore_errors=True)
    write_map_files(staging, raw)


def _install_report(
    plan: InstallPlan, files: MapFiles, install_id: str, apply: bool
) -> dict[str, Any]:
    return {
        "mode": "install", "apply": apply, "install_id": install_id, "map": files.name,
        "status": plan.status, "pinned_spans_sha256": files.pinned_sha256,
        "balance": {"live_before": plan.live_before, "retire": len(plan.retire),
                    "insert": len(plan.insert), "live_after_expected": plan.live_after},
        "retire_by_disposition": dict(Counter(d for _, d in plan.retire)),
        "insert_by_origin": dict(Counter(s.origin for s in plan.insert)),
        "names_touched": sorted(plan.touched_symbols),
        "retire": [[k[0], k[1], k[2].isoformat(), _iso(k[3]), d] for k, d in plan.retire],
        "insert": [[s.symbol, s.ticker, s.start.isoformat(), _iso(s.end), s.origin]
                   for s in plan.insert],
    }  # fmt: skip


class TickerEntityMapInstaller(BaseBatch):
    """The --install and --rollback runs (module docstring). One transaction on one connection,
    a table lock for its whole length, rehearsal (rolled back) unless --apply."""

    job_name = _JOB
    compute_version = "1.0.0"

    def __init__(self, db_dsn: str, args: argparse.Namespace, out_root: Path = _OUT_ROOT,
                 rolled_back_root: Path = _ROLLED_BACK_ROOT):  # fmt: skip
        super().__init__(db_dsn)
        self._args = args
        self._apply = args.apply
        self._out_root = out_root
        self._rolled_back_root = rolled_back_root

    async def execute(self, pool: asyncpg.Pool) -> None:
        report = await (self._rollback(pool) if self._args.rollback else self._install(pool))
        self.logger.info(
            "ticker_entity_map.install_done", mode=report["mode"], outcome=report["outcome"]
        )
        print(json.dumps(report, indent=2, sort_keys=True, default=str))

    def _verified_map(self) -> MapFiles:
        args = self._args
        files = read_map_dir(args.install)
        if files.digest != args.install_digest:
            raise InstallRefused(
                f"the map is {files.digest}, --install-digest says {args.install_digest}"
            )
        hidden = [tuple(h.split(":")) for h in args.hidden_1d]
        verify_install_reconciliation(
            files,
            {
                "1d": _read_lost_rows(args.lost_1d, "file_ticker") + hidden,
                "5m": _read_lost_rows(args.lost_5m, "alt_ticker"),
            },
            json.loads(args.coverage_summary.read_text()),
        )
        return files

    async def _install(self, pool: asyncpg.Pool) -> dict[str, Any]:
        files = self._verified_map()
        untouched = [s for s in self._args.untouched.split(",") if s]
        target = self._out_root / files.name
        present = check_install_target(target, files.raw)
        install_id = new_install_id(files.digest, datetime.now(UTC))
        staging = self._out_root.parent / f".staging_{install_id}"
        pre_sha = ""
        async with pool.acquire() as conn:
            try:
                async with conn.transaction():
                    await conn.execute(_LOCK_SQL)
                    rows = await conn.fetch(_DOC_SPANS_SQL)
                    plan = plan_install(files, live_old_spans(rows), untouched)
                    report = _install_report(plan, files, install_id, self._apply)
                    if plan.status == "already_installed":
                        return {**report, "outcome": "no_op"}
                    ids = {_row_key(r): r["ticker_event_id"] for r in rows}
                    pre_sha = content_sha256(
                        [{**r, "security_identifier_id": r["security_identifier_id"]}
                         for r in rows]  # fmt: skip
                    )
                    lineage = {
                        "install_id": install_id, "map_digest": files.digest,
                        "map_dir": files.name, "pre_install_sha256": pre_sha,
                        "rows_retired": len(plan.retire), "rows_inserted": len(plan.insert),
                    }  # fmt: skip
                    await _retire(
                        conn,
                        [ids[k] for k, _ in plan.retire],
                        [retire_reason(install_id, files.digest, d) for _, d in plan.retire],
                    )
                    await self._insert(conn, plan, lineage)
                    live_after = await conn.fetch(_LIVE_SQL)
                    verify_balance(plan, [_row_key(r) for r in live_after])
                    if not self._apply:
                        raise _Rehearsal
                    if not present:
                        _stage(staging, files.raw)
                outcome = "installed"
            except _Rehearsal:
                outcome = "rolled_back"
            except BaseException:
                shutil.rmtree(staging, ignore_errors=True)
                raise
        if outcome == "installed" and not present:
            self._out_root.mkdir(parents=True, exist_ok=True)
            os.rename(staging, target)
        return {**report, "outcome": outcome, "pre_install_sha256": pre_sha,
                "map_dir_installed": str(target) if outcome == "installed" else None}  # fmt: skip

    async def _insert(
        self, conn: asyncpg.Connection, plan: InstallPlan, lineage: Mapping[str, Any]
    ) -> None:
        sids = {
            (r["symbol"], r["value"]): r["security_identifier_id"]
            for r in await conn.fetch(_AMEND_IDS_SQL)
            if r["scheme"] == SPAN_SCHEME
        }
        overview = {r["symbol"]: r["id"] for r in await conn.fetch(_AMEND_OVERVIEW_SQL)}
        spans = plan.insert
        missing = [
            (s.symbol, s.composite_figi) for s in spans if (s.symbol, s.composite_figi) not in sids
        ]
        if missing:
            raise InstallRefused(f"no live {SPAN_SCHEME} identifier for {missing}")
        absent = sorted({s.symbol for s in spans if not s.reference_raw_id} - overview.keys())
        if absent:
            raise InstallRefused(f"no captured overview answer to cite for {absent}")
        await conn.execute(
            _INSERT_SPANS_SQL,
            [sids[(s.symbol, s.composite_figi)] for s in spans],
            [s.symbol for s in spans],
            [s.ticker for s in spans],
            [s.start for s in spans],
            [None if s.end == _OPEN else s.end for s in spans],
            [s.reference_raw_id or overview[s.symbol] for s in spans],
            [install_evidence(s, lineage) for s in spans],
        )

    async def _rollback(self, pool: asyncpg.Pool) -> dict[str, Any]:
        install_id = self._args.rollback
        async with pool.acquire() as conn:
            try:
                async with conn.transaction():
                    await conn.execute(_LOCK_SQL)
                    rows = [
                        HistoryRow(r["id"], r["security_identifier_id"], r["symbol"], r["ticker"],
                                   r["valid_from"], r["valid_to"], r["reference_raw_id"],
                                   r["evidence"], r["retired_reason"])
                        for r in await conn.fetch(
                            _INSTALL_ROWS_SQL, install_id, f"{INSTALL_REASON} {install_id} %"
                        )
                    ]  # fmt: skip
                    plan = plan_rollback(install_id, rows)
                    live_before = await conn.fetch(_LIVE_SQL)
                    before_keys = {_row_key(r) for r in live_before}
                    reason = f"{ROLLBACK_REASON} {install_id}: restores the rows it retired"
                    await _retire(conn, plan.retire_ids, [reason] * len(plan.retire_ids))
                    await conn.execute(
                        _INSERT_SPANS_SQL,
                        [r.security_identifier_id for r in plan.restore],
                        [r.symbol for r in plan.restore],
                        [r.ticker for r in plan.restore],
                        [r.start for r in plan.restore],
                        [r.end for r in plan.restore],
                        [r.reference_raw_id for r in plan.restore],
                        [canonical_json(r.evidence) for r in plan.restore],
                    )
                    live_after = await conn.fetch(_LIVE_SQL)
                    inserted_keys = {r.key for r in rows if r.ticker_event_id in plan.retire_ids}
                    expected = (before_keys - inserted_keys) | {r.key for r in plan.restore}
                    after_sha = content_sha256(live_after)
                    after_keys = [_row_key(r) for r in live_after]
                    if set(after_keys) != expected or len(after_keys) != len(expected):
                        raise InstallRefused("rollback row balance does not reconcile")
                    if after_sha != plan.pre_install_sha256:
                        raise InstallRefused(
                            f"the rows after the rollback (sha256 {after_sha}) are not the rows "
                            f"before the install ({plan.pre_install_sha256})"
                        )
                    if not self._apply:
                        raise _Rehearsal
                outcome = "rolled_back_install"
            except _Rehearsal:
                outcome = "rehearsed_rollback"
        if outcome == "rolled_back_install":
            source = self._out_root / plan.map_dir
            if source.exists():
                self._rolled_back_root.mkdir(parents=True, exist_ok=True)
                os.rename(source, self._rolled_back_root / f"{plan.map_dir}__{install_id}")
        return {
            "mode": "rollback", "install_id": install_id, "apply": self._apply,
            "outcome": outcome, "rows_retired": len(plan.retire_ids),
            "rows_restored": len(plan.restore), "live_before": len(live_before),
            "live_after": len(live_after), "post_rollback_sha256": after_sha,
            "pre_install_sha256": plan.pre_install_sha256,
        }  # fmt: skip


class _Rehearsal(Exception):
    """Raised inside the transaction to roll it back on a run without --apply."""


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the stage 1 ticker-entity map")
    parser.add_argument("--apply", action="store_true", help="commit; default rolls back")
    parser.add_argument("--amend", type=Path, help="the identity witness spans CSV (design 8c)")
    parser.add_argument("--amend-sha256", help="--amend: the pinned sha256 of the spans CSV")
    parser.add_argument("--amend-candidates", type=Path, help="--amend: the candidates CSV")
    parser.add_argument("--gap-list", type=Path, help="--amend: the gap list the witness read")
    parser.add_argument(
        "--manifest", type=Path, default=_REPO_ROOT / "data/massive/manifest/manifest.jsonl"
    )
    parser.add_argument("--documentary", type=Path, help="documentary_placements.csv (design 8c)")
    parser.add_argument("--documentary-sha256", help="--documentary: the pinned sha256")
    parser.add_argument("--regions", type=Path, help="--documentary: documentary_spans.csv")
    parser.add_argument("--regions-sha256", help="--documentary: its pinned sha256")
    parser.add_argument("--map-dir", type=Path, help="--documentary: the pinned map directory")
    parser.add_argument("--pinned-map-digest", help="--documentary: its 12-digit digest")
    parser.add_argument("--pinned-spans-sha256", help="--documentary: sha256 of the live spans")
    parser.add_argument("--out", type=Path, help="--documentary: scratch output root")
    parser.add_argument("--version-date", help="--documentary: YYYYMMDD of the new map name")
    parser.add_argument("--lost-1d", type=Path, help="--documentary: 1d classified lost rows")
    parser.add_argument("--lost-5m", type=Path, help="--documentary: 5m classified lost rows")
    parser.add_argument(
        "--hidden-1d",
        action="append",
        default=[],
        help="--documentary: SYMBOL:SESSION:TICKER, a 1d row the classification hid as no bar",
    )
    parser.add_argument(
        "--coverage-summary", type=Path, help="--documentary: coverage_summary.json"
    )
    parser.add_argument("--install", type=Path, help="install this scratch map version (8c)")
    parser.add_argument("--install-digest", help="--install: the map's 12-digit digest")
    parser.add_argument(
        "--untouched",
        help="--install: comma-separated names the plan must not touch (may be empty)",
    )
    parser.add_argument("--rollback", metavar="INSTALL_ID", help="undo a recorded install")
    args = parser.parse_args()
    if args.install and args.rollback:
        parser.error("--install and --rollback are separate runs")
    if (args.install or args.rollback) and (args.documentary or args.amend):
        parser.error("--install and --rollback take no --documentary or --amend")
    if args.install:
        needed = ("install_digest", "lost_1d", "lost_5m", "coverage_summary")
        if [n for n in needed if not getattr(args, n)] or args.untouched is None:
            parser.error(f"--install needs --untouched and {needed}")
    if args.documentary:
        needed = ("documentary_sha256", "regions", "regions_sha256", "map_dir",
                  "pinned_map_digest", "out", "version_date", "pinned_spans_sha256", "lost_1d", "lost_5m",
                  "coverage_summary")  # fmt: skip
        if args.apply or args.amend or [n for n in needed if not getattr(args, n)]:
            parser.error(f"--documentary needs {needed} and takes no --apply or --amend")
    if args.amend and not (args.amend_sha256 and args.amend_candidates and args.gap_list):
        parser.error("--amend needs --amend-sha256, --amend-candidates and --gap-list")
    try:
        init_otel_providers(f"indicagent-{_JOB}")
    except OTelInitError:
        pass
    settings = Settings()
    db_dsn = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
    if args.install or args.rollback:
        asyncio.run(TickerEntityMapInstaller(db_dsn, args).run())
    elif args.documentary:
        asyncio.run(TickerEntityMapDocumentary(db_dsn, args).run())
    elif args.amend:
        asyncio.run(TickerEntityMapAmender(db_dsn, args.apply, args).run())
    else:
        asyncio.run(TickerEntityMapWriter(db_dsn, args.apply).run())


if __name__ == "__main__":
    main()
