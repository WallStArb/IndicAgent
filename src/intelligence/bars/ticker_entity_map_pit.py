"""Ticker-to-entity map, pit anchor: the names stage 1 could not reach (todo 609, stage 2).

One pure planner, ``plan_pit_map``, turns the captured Massive point-in-time ticker lists (one
``@active`` and one ``@inactive`` snapshot per NYSE month-end) and the live map's state into the
new securities, identifiers and ``ticker_event`` spans a stage 2 install would add. No I/O, no
clock, no bar and no return: the same inputs give the same plan, byte for byte.

The rules are the 2026-11-13 key rule and its 2026-11-15 details
(``docs/plans/2026-11-15-pit-anchor-map-and-stage2-instruments.md``, section 1):

* A record's key is its composite FIGI; where none is served, its CIK with its ticker string.
  A record with neither is unplaced. ``type`` is evidence, never identity.
* A ticker string appears once per snapshot, so a record has one key; a composite FIGI served
  under two tickers in one snapshot is claimed twice and both records are unplaced that month.
* A ticker's consecutive month-ends form a run while the identity holds: equal composite FIGIs,
  or, when either side lacks one, equal CIKs. A broken identity starts a new run, which is a new
  security. Runs that share a composite FIGI are one security (a rename); runs with no composite
  FIGI are one security per (CIK, ticker).
* A ticker missing from exactly one month-end (absent from the active list, or its record
  dropped as claimed twice with the same identity) between two observations of one identity is
  one run: the month is bridged and counted, so no listing has a hole inside it.
* A span starts at the run's first month-end (the archive start when the run is in the first
  snapshot) and ends at the delisting date of the matching ``@inactive`` record when that date
  is after the last month-end and not after the first month-end the ticker is absent from; with
  no such date it ends at that first absent month-end, exclusive, when the ticker left the list
  with no other holder in its place (the final bars of a delisting are inside the span), and the
  day after its last month-end when another holder took the ticker at that month-end. A run
  still present in the last snapshot is open. A bar between one holder's end and the next
  holder's first belongs to no span.
* Additive: a run whose composite FIGI or share-class FIGI is a live identifier is left to the
  live map, and a window in which a live span holds the ticker is not given to a new security.
"""

from __future__ import annotations

import hashlib
import re
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from itertools import pairwise
from typing import Any

from src.core.canonical_json import canonical_json

PIT_MAP_VERSION = "pit-1"
# Research-design constants of the preregistration amendment, not APR keys: a tunable identity
# rule would invite tuning after seeing results. Changing one is a dated amendment and a new id.
PIT_RULE_ID = "pit-anchor-2026-11-15"
# The first session of the Massive flat-file archive (the same date as ticker_entity_map).
MASSIVE_ARCHIVE_START = date(2003, 9, 10)
# A missing month-end would silently bridge two runs; snapshot dates further apart than this
# (a month-end to the next is at most 31 days) refuse the build.
MAX_SNAPSHOT_GAP_DAYS = 35

COMPOSITE_FIGI = "composite_figi"
SHARE_CLASS_FIGI = "share_class_figi"
CIK_TICKER = "cik_ticker"

_FIGI = re.compile(r"[B-DF-HJ-NP-TV-Z]{2}G[B-DF-HJ-NP-TV-Z0-9]{8}[0-9]")
_CIK = re.compile(r"[0-9]{10}")
_TICKER = re.compile(r"\S+")

# Why a record or a run did not become a span (counted by year and served type).
PLACED = "placed"
PLACED_PARTIAL = "placed_partial"
NO_KEY = "no_key"
BAD_TICKER = "bad_ticker"
CLAIMED_TWICE = "claimed_twice"
ALREADY_LIVE = "already_live"
CLIPPED_BY_LIVE_SPAN = "clipped_by_live_span"


class PitPlanError(ValueError):
    """The snapshots or the planner's own result break an invariant: nothing is planned."""


@dataclass(frozen=True, slots=True)
class PitRecord:
    """One served ticker record, reduced to what identity and the instrument row use."""

    ticker: str
    cik: str | None
    composite_figi: str | None
    share_class_figi: str | None
    type: str | None
    name: str | None
    primary_exchange: str | None
    delisted_on: date | None
    reference_raw_id: str


@dataclass(frozen=True, slots=True)
class PitSnapshot:
    as_of: date
    active: tuple[PitRecord, ...]
    inactive: tuple[PitRecord, ...]


@dataclass(frozen=True)
class LiveState:
    """What the live map already holds: every instrument symbol, every live identifier
    ``(scheme, value) -> symbol``, and every live span ``(ticker, start, end)``, end None open."""

    symbols: frozenset[str]
    identifiers: Mapping[tuple[str, str], str]
    spans: Sequence[tuple[str, date, date | None]]
    # (key kind, key value) -> the symbol of a stage 2 instrument row an earlier install created
    # for that key and a rollback left in place; a plan reuses it so a reinstall is the same plan
    stage2_symbols: Mapping[tuple[str, str], str] = field(default_factory=dict)
    # symbols that hold at least one live span; an instrument outside this set (the stage 1 gap
    # list) has a ticker and no span, and the latest holder of that ticker is that instrument
    span_symbols: frozenset[str] = frozenset()


@dataclass(frozen=True)
class PitSpan:
    symbol: str
    ticker: str
    start: date
    end: date | None  # exclusive; None is open
    reference_raw_id: str
    evidence: str  # canonical JSON


@dataclass(frozen=True)
class PitIdentifier:
    symbol: str
    scheme: str
    value: str
    valid_from: date
    valid_to: date | None
    reference_raw_id: str


@dataclass(frozen=True)
class PitSecurity:
    symbol: str
    key_kind: str
    key_value: str
    cik: str | None
    composite_figi: str | None
    share_class_figi: str | None
    name: str | None
    exchange: str | None
    types: tuple[str, ...]
    first: date
    last: date | None
    tickers: tuple[str, ...]


@dataclass(frozen=True)
class PitPlan:
    securities: tuple[PitSecurity, ...]
    identifiers: tuple[PitIdentifier, ...]
    spans: tuple[PitSpan, ...]
    accounting: tuple[dict[str, str], ...]
    # (year, served type or "none", reason) -> record or observation count
    residual: Mapping[tuple[int, str, str], int]
    # year -> month-end records keyed (CIK, ticker) whose CIK is served under another ticker in
    # the same snapshot (a multi-class issuer). They are placed, each under its own ticker; the
    # count is the share of the placed set the (CIK, ticker) key rests on without a share-class FIGI.
    ambiguous_cik_ticker: Mapping[int, int]
    snapshots: int
    first_as_of: date
    last_as_of: date
    # single missing month-ends bridged inside a listing, and (CIK, ticker) securities whose CIK
    # continues under another ticker within 70 days (a rename the key rule does not link)
    bridged_months: int = 0
    cik_renames_split: int = 0

    def residual_report(self) -> list[dict[str, Any]]:
        rows: dict[tuple[int, str], dict[str, Any]] = {}
        for (year, typ, reason), n in sorted(self.residual.items()):
            row = rows.setdefault((year, typ), {"year": year, "type": typ, "total": 0})
            row[reason] = n
            row["total"] += n
        return [rows[k] for k in sorted(rows)]


# ---------------------------------------------------------------------------------------------
# Snapshots from captured pages
# ---------------------------------------------------------------------------------------------


def _clean(value: Any, pattern: re.Pattern[str]) -> str | None:
    return value if isinstance(value, str) and pattern.fullmatch(value) else None


def pit_record(result: Mapping[str, Any], reference_raw_id: str) -> PitRecord:
    """One element of a page's ``results``. A malformed identifier is treated as not served."""
    delisted = result.get("delisted_utc")
    return PitRecord(
        ticker=str(result.get("ticker") or ""),
        cik=_clean(result.get("cik"), _CIK),
        composite_figi=_clean(result.get("composite_figi"), _FIGI),
        share_class_figi=_clean(result.get("share_class_figi"), _FIGI),
        type=result.get("type") or None,
        name=result.get("name") or None,
        primary_exchange=result.get("primary_exchange") or None,
        delisted_on=date.fromisoformat(delisted[:10]) if isinstance(delisted, str) else None,
        reference_raw_id=reference_raw_id,
    )


def records_from_pages(
    as_of: date, kind: str, pages: Sequence[tuple[int, str, Mapping[str, Any]]]
) -> tuple[PitRecord, ...]:
    """One list of one month-end from its pages ``(page, reference_raw_id, body)``.

    Refuses unless the pages are 1..N, every status is OK, every body holds a results list and
    only the last page lacks ``next_url``: a partial capture would silently take names out."""
    if not pages:
        raise PitPlanError(f"{as_of} {kind}: no pages")
    ordered = sorted(pages, key=lambda p: p[0])
    if [p[0] for p in ordered] != list(range(1, len(ordered) + 1)):
        raise PitPlanError(f"{as_of} {kind}: pages {[p[0] for p in ordered]} are not 1..N")
    records: list[PitRecord] = []
    for index, (page, raw_id, body) in enumerate(ordered):
        if body.get("status") != "OK" or not isinstance(body.get("results"), list):
            raise PitPlanError(f"{as_of} {kind} page {page}: status {body.get('status')!r}")
        last = index == len(ordered) - 1
        if bool(body.get("next_url")) == last:
            raise PitPlanError(
                f"{as_of} {kind} page {page}: next_url {'present' if not last else 'absent'} "
                f"on the {'last' if last else 'non-last'} page"
            )
        records.extend(pit_record(r, raw_id) for r in body["results"])
    return tuple(records)


# ---------------------------------------------------------------------------------------------
# Runs
# ---------------------------------------------------------------------------------------------


@dataclass
class _Run:
    ticker: str
    first: date
    last: date
    first_ref: str
    cik: str | None
    composite: str | None
    share_class: str | None
    name: str | None
    exchange: str | None
    types: set[str]
    obs: Counter[tuple[int, str]]  # (year, type or "none") -> month-ends observed
    n: int
    starts_at_capture: bool
    start_hint: date | None = None  # a first-snapshot run starts after another holder's delisting
    end_hint: date | None = None  # a delisting date inside (last, next snapshot]
    open: bool = False
    next_as_of: date | None = None
    absent_at: date | None = None  # the first month-end the ticker was missing from the placed set
    bridged: int = 0  # single missing month-ends the run bridges
    absent_unkeyed: bool = False  # another record with no key held the ticker at absent_at


def _same_identity(run: _Run, rec: PitRecord) -> bool:
    if run.composite and rec.composite_figi:
        return run.composite == rec.composite_figi
    return bool(run.cik and rec.cik and run.cik == rec.cik)


def _extend(run: _Run, rec: PitRecord, as_of: date) -> None:
    run.last = as_of
    run.n += 1
    run.composite = run.composite or rec.composite_figi
    run.share_class = run.share_class or rec.share_class_figi
    run.cik = run.cik or rec.cik
    run.name = rec.name or run.name
    run.exchange = rec.primary_exchange or run.exchange
    typ = rec.type or "none"
    if rec.type:
        run.types.add(rec.type)
    run.obs[(as_of.year, typ)] += 1


def _new_run(rec: PitRecord, as_of: date, first_snapshot: bool) -> _Run:
    run = _Run(
        ticker=rec.ticker, first=as_of, last=as_of, first_ref=rec.reference_raw_id,
        cik=rec.cik, composite=rec.composite_figi, share_class=rec.share_class_figi,
        name=rec.name, exchange=rec.primary_exchange, types=set(), obs=Counter(), n=1,
        starts_at_capture=first_snapshot,
    )  # fmt: skip
    typ = rec.type or "none"
    if rec.type:
        run.types.add(rec.type)
    run.obs[(as_of.year, typ)] += 1
    return run


def _start_hint(run: _Run, snap: PitSnapshot, by_ticker: dict[str, list[PitRecord]]) -> None:
    """A run present in the first snapshot starts at the archive start, unless another holder of
    the ticker (an inactive record with a different CIK, or any CIK when the run has none) was
    delisted on or after it and before the snapshot: the days up to that delisting are its."""
    if snap.inactive and not by_ticker:
        for rec in snap.inactive:
            by_ticker.setdefault(rec.ticker, []).append(rec)
    others = [
        r.delisted_on
        for r in by_ticker.get(run.ticker, ())
        if r.delisted_on
        and MASSIVE_ARCHIVE_START <= r.delisted_on <= snap.as_of
        and (r.cik != run.cik or not run.cik)
    ]
    if others:
        run.start_hint = max(others)


def _delisting_hint(run: _Run, snap: PitSnapshot, by_ticker: dict[str, list[PitRecord]]) -> None:
    """The delisting date of the run's own record in ``snap``'s inactive list, when exactly one
    record of that ticker carries the run's CIK and its date falls after the run's last
    month-end and not after ``snap``: the run was delisted in the month it is absent from."""
    if not run.cik:
        return
    if snap.inactive and not by_ticker:
        for rec in snap.inactive:
            by_ticker.setdefault(rec.ticker, []).append(rec)
    own = [r for r in by_ticker.get(run.ticker, ()) if r.cik == run.cik and r.delisted_on]
    if len(own) == 1 and run.last < own[0].delisted_on <= snap.as_of:  # type: ignore[operator]
        run.end_hint = own[0].delisted_on


def build_runs(
    snapshots: Iterable[PitSnapshot],
) -> tuple[list[_Run], Counter[tuple[int, str, str]], Counter[int], int, date, date]:
    """Runs of every ticker over the snapshots, in order, plus the record-level residual."""
    runs: list[_Run] = []
    residual: Counter[tuple[int, str, str]] = Counter()
    ambiguous: Counter[int] = Counter()
    open_runs: dict[str, _Run] = {}
    pending: dict[str, _Run] = {}  # runs missing from exactly one month-end so far
    previous: date | None = None
    first: date | None = None
    count = 0
    for snap in snapshots:
        if previous is not None:
            if snap.as_of <= previous:
                raise PitPlanError(f"snapshots out of order: {snap.as_of} after {previous}")
            if (snap.as_of - previous).days > MAX_SNAPSHOT_GAP_DAYS:
                raise PitPlanError(f"a month-end is missing between {previous} and {snap.as_of}")
        first = first or snap.as_of
        claims = Counter(r.composite_figi for r in snap.active if r.composite_figi)
        cik_tickers = Counter(r.cik for r in snap.active if r.cik and not r.composite_figi)
        seen: set[str] = set()
        unkeyed: set[str] = set()  # tickers whose record this month has no usable key or ticker
        by_ticker: dict[str, list[PitRecord]] = {}
        for ticker, gone in list(pending.items()):  # missing two month-ends running: closed
            if gone.absent_at != previous:
                gone.next_as_of = gone.absent_at
                runs.append(pending.pop(ticker))
        for rec in snap.active:
            typ = rec.type or "none"
            reason = None
            if not _TICKER.fullmatch(rec.ticker):
                reason = BAD_TICKER
            elif not (rec.composite_figi or rec.cik):
                reason = NO_KEY
            elif rec.composite_figi and claims[rec.composite_figi] > 1:
                reason = CLAIMED_TWICE
            if reason:
                residual[(snap.as_of.year, typ, reason)] += 1
                if reason in (NO_KEY, BAD_TICKER):
                    unkeyed.add(rec.ticker)
                continue  # the ticker is absent from the placed set: an open run closes below
            seen.add(rec.ticker)
            if rec.cik and not rec.composite_figi and cik_tickers[rec.cik] > 1:
                ambiguous[snap.as_of.year] += 1
            run = open_runs.get(rec.ticker)
            if run is not None and run.last == previous and _same_identity(run, rec):
                _extend(run, rec, snap.as_of)
                continue
            gone = pending.pop(rec.ticker, None)
            if gone is not None and not gone.absent_unkeyed and _same_identity(gone, rec):
                gone.end_hint = None  # it was a missing month, not a delisting
                gone.absent_at = None
                gone.bridged += 1
                _extend(gone, rec, snap.as_of)
                open_runs[rec.ticker] = gone
                continue
            if gone is not None:
                gone.next_as_of = gone.absent_at
                runs.append(gone)
            if run is not None:
                _delisting_hint(run, snap, by_ticker)
                run.next_as_of = snap.as_of
                runs.append(run)
            new = _new_run(rec, snap.as_of, first == snap.as_of)
            if new.starts_at_capture:
                _start_hint(new, snap, by_ticker)
            open_runs[rec.ticker] = new
        for ticker in [t for t in open_runs if t not in seen]:
            run = open_runs.pop(ticker)
            _delisting_hint(run, snap, by_ticker)
            run.absent_at = snap.as_of
            run.absent_unkeyed = ticker in unkeyed
            pending[ticker] = run
        previous = snap.as_of
        count += 1
    if previous is None or first is None:
        raise PitPlanError("no snapshots")
    for run in pending.values():
        run.next_as_of = run.absent_at
        runs.append(run)
    for run in open_runs.values():
        run.open = True
        runs.append(run)
    return runs, residual, ambiguous, count, first, previous


# ---------------------------------------------------------------------------------------------
# Securities, spans, symbols
# ---------------------------------------------------------------------------------------------

Interval = tuple[date, date]


def _span_interval(run: _Run) -> Interval | None:
    start = (run.start_hint or MASSIVE_ARCHIVE_START) if run.starts_at_capture else run.first
    if run.open:
        return (start, date.max)
    return (start, run.end_hint or run.absent_at or run.last + timedelta(days=1))


def _minus(base: Interval, cuts: Sequence[Interval]) -> list[Interval]:
    pieces = [base]
    for c0, c1 in sorted(cuts):
        nxt: list[Interval] = []
        for a, b in pieces:
            if c1 <= a or c0 >= b:
                nxt.append((a, b))
                continue
            if a < c0:
                nxt.append((a, c0))
            if c1 < b:
                nxt.append((c1, b))
        pieces = nxt
    return [p for p in pieces if p[0] < p[1]]


def _key(run: _Run) -> tuple[str, str]:
    if run.composite:
        return (COMPOSITE_FIGI, run.composite)
    assert run.cik is not None  # a run exists only for a record with a composite FIGI or a CIK
    return (CIK_TICKER, f"{run.cik}:{run.ticker}")


def _tag(kind: str, value: str) -> str:
    return value[-8:] if kind == COMPOSITE_FIGI else str(int(value.split(":", 1)[0]))


def _evidence(run: _Run, kind: str, value: str, symbol: str) -> str:
    return canonical_json(
        {
            "map_version": PIT_MAP_VERSION, "rule": PIT_RULE_ID, "anchor": "pit_snapshots",
            "key_kind": kind, "key": value, "symbol": symbol, "cik": run.cik,
            "composite_figi": run.composite, "share_class_figi": run.share_class,
            "observed_first": run.first.isoformat(), "observed_last": run.last.isoformat(),
            "observations": run.n, "types": sorted(run.types),
            "delisted_on": run.end_hint.isoformat() if run.end_hint else None,
            "open": run.open, "first_snapshot_answer": run.first_ref,
        }
    )  # fmt: skip


def _account(kind: str, run: _Run, symbol: str, disposition: str, note: str) -> dict[str, str]:
    return {
        "kind": kind, "symbol": symbol, "ticker": run.ticker,
        "valid_from": run.first.isoformat(), "valid_to": run.last.isoformat(),
        "disposition": disposition, "reason": note, "pieces": str(run.n),
    }  # fmt: skip


def plan_pit_map(snapshots: Iterable[PitSnapshot], live: LiveState) -> PitPlan:
    runs, residual, ambiguous, count, first_as_of, last_as_of = build_runs(snapshots)
    live_by_ticker: dict[str, list[Interval]] = {}
    for ticker, start, end in live.spans:
        live_by_ticker.setdefault(ticker, []).append((start, end or date.max))
    accounting: list[dict[str, str]] = []

    def drop(run: _Run, reason: str, note: str) -> None:
        for (year, typ), n in run.obs.items():
            residual[(year, typ, reason)] += n
        accounting.append(_account("pit_run", run, "", reason, note))

    # An instrument with no live span (the stage 1 gap list) still owns its ticker string: the
    # latest holder of that string in the capture is that instrument, wherever its run ended (a
    # name can leave the vendor's active list and stay ours), and so is every earlier run of the
    # same key. A second, inactive instrument under a suffixed symbol would split the name. An
    # instrument that has spans is handled by the clips and identifiers; a stage 2 symbol is ours.
    reused = dict(live.stage2_symbols)
    spanless = live.symbols - live.span_symbols - set(reused.values())
    latest: dict[str, _Run] = {}
    for r in runs:
        if r.ticker in spanless and (r.ticker not in latest or r.last >= latest[r.ticker].last):
            latest[r.ticker] = r
    held_by_instrument: dict[tuple[str, str], str] = {}
    for r in runs:
        mine = latest.get(r.ticker)
        # the latest holder's key, and every run of the string under the same issuer: a gap in
        # the vendor's list or a FIGI that arrived late splits one listing into runs with
        # different keys, and each of them is still that instrument
        if mine is not None and (_key(r) == _key(mine) or (mine.cik and r.cik == mine.cik)):
            held_by_instrument[_key(r)] = r.ticker
    entities: dict[tuple[str, str], list[_Run]] = {}
    for run in sorted(runs, key=lambda r: (r.first, r.ticker)):
        kind, value = _key(run)
        if (kind, value) in held_by_instrument:
            drop(
                run,
                ALREADY_LIVE,
                f"the key's active run is the instrument {held_by_instrument[(kind, value)]}",
            )
            continue
        live_symbol = live.identifiers.get((kind, value))
        if live_symbol is None and run.share_class:
            live_symbol = live.identifiers.get((SHARE_CLASS_FIGI, run.share_class))
        if live_symbol is not None:
            drop(run, ALREADY_LIVE, f"identifier is live on {live_symbol}")
            continue
        entities.setdefault((kind, value), []).append(run)

    pieces: dict[tuple[str, str], list[tuple[_Run, Interval]]] = {}
    for key, group in entities.items():
        intervals = [_span_interval(run) for run in group]
        for run, interval in zip(group, intervals, strict=True):
            assert interval is not None
            after_live = _minus(interval, live_by_ticker.get(run.ticker, ()))
            # a composite FIGI held by two tickers over the same days is claimed twice: the
            # overlap is given to neither (the per-snapshot check sees only the months in which
            # both records serve the FIGI; a run keeps its FIGI across a month that omits it)
            rivals = [
                iv for r, iv in zip(group, intervals, strict=True) if r.ticker != run.ticker and iv
            ]
            kept = _minus(interval, [*live_by_ticker.get(run.ticker, ()), *rivals])
            if not kept:
                if not after_live:
                    drop(run, CLIPPED_BY_LIVE_SPAN, "a live span holds the ticker throughout")
                else:
                    drop(
                        run,
                        CLAIMED_TWICE,
                        "the composite FIGI is held by another ticker throughout",
                    )
                continue
            reason = PLACED if kept == [interval] else PLACED_PARTIAL
            for piece in kept:
                pieces.setdefault(key, []).append((run, piece))
            for (year, typ), n in run.obs.items():
                residual[(year, typ, reason)] += n

    # sequential runs of one ticker, and runs of one security, never overlap
    held: dict[str, list[Interval]] = {}
    for key in sorted(pieces):
        group = sorted(pieces[key], key=lambda rp: rp[1])
        for (ra, (a0, a1)), (rb, (b0, b1)) in pairwise(group):
            if b0 < a1:
                raise PitPlanError(f"security {key} holds {ra.ticker} and {rb.ticker} at once")
        for run, interval in group:
            held.setdefault(run.ticker, []).append(interval)
    for ticker, intervals in held.items():
        ordered = sorted(intervals)
        for (a0, a1), (b0, b1) in pairwise(ordered):
            if b0 < a1:
                raise PitPlanError(f"ticker {ticker} is given to two securities over {b0}")

    if len(set(reused.values())) != len(reused):
        raise PitPlanError("two keys share one stage 2 instrument symbol")
    taken = set(live.symbols)  # includes every reused stage 2 symbol: no other key takes one
    assigned: set[str] = set()
    securities: list[PitSecurity] = []
    identifiers: list[PitIdentifier] = []
    spans: list[PitSpan] = []

    def order(key: tuple[str, str]) -> tuple[date, str, str]:
        return (min(iv[0] for _, iv in pieces[key]), key[0], key[1])

    for key in sorted(pieces, key=order):
        kind, value = key
        group = sorted(pieces[key], key=lambda rp: rp[1])
        runs_of = [r for r, _ in group]
        last_run = max(runs_of, key=lambda r: (r.last, r.ticker))
        if key in reused:
            symbol = reused[key]
        else:
            symbol = last_run.ticker
            if symbol in taken:
                symbol = f"{symbol}~{_tag(kind, value)}"
        if (key not in reused and symbol in taken) or symbol in assigned:
            raise PitPlanError(f"symbol {symbol} for {key} is already taken")
        taken.add(symbol)
        assigned.add(symbol)
        first_start = min(iv[0] for _, iv in group)
        end = None if any(iv[1] == date.max for _, iv in group) else max(iv[1] for _, iv in group)
        composite = next((r.composite for r in runs_of if r.composite), None)
        share_class = next((r.share_class for r in runs_of if r.share_class), None)
        cik = next((r.cik for r in runs_of if r.cik), None)
        types = tuple(sorted({t for r in runs_of for t in r.types}))
        securities.append(
            PitSecurity(
                symbol, kind, value, cik, composite, share_class, last_run.name, last_run.exchange,
                types, first_start, end, tuple(sorted({r.ticker for r in runs_of})),
            )
        )  # fmt: skip
        ref = group[0][0].first_ref
        identifiers.append(PitIdentifier(symbol, kind, value, first_start, end, ref))
        if (
            kind == COMPOSITE_FIGI
            and share_class
            and (SHARE_CLASS_FIGI, share_class) not in live.identifiers
        ):
            identifiers.append(
                PitIdentifier(symbol, SHARE_CLASS_FIGI, share_class, first_start, end, ref)
            )
        for run, (s0, s1) in group:
            spans.append(
                PitSpan(
                    symbol, run.ticker, s0, None if s1 == date.max else s1, run.first_ref,
                    _evidence(run, kind, value, symbol),
                )
            )  # fmt: skip
            accounting.append(
                _account(
                    "pit_span",
                    run,
                    symbol,
                    "added",
                    f"{s0.isoformat()} to {s1.isoformat() if s1 != date.max else 'open'}",
                )
            )
    # a share-class FIGI served under two planned securities identifies neither: it decides
    # nothing (amendment item 1), so it is not stored
    claimants = Counter(i.value for i in identifiers if i.scheme == SHARE_CLASS_FIGI)
    identifiers = [
        i for i in identifiers if not (i.scheme == SHARE_CLASS_FIGI and claimants[i.value] > 1)
    ]
    _check_identifier_uniqueness(identifiers)
    bridged = sum(r.bridged for key in pieces for r in {id(r): r for r, _ in pieces[key]}.values())
    return PitPlan(
        tuple(securities), tuple(identifiers), tuple(sorted(spans, key=lambda s: (s.symbol, s.start, s.ticker))),
        tuple(accounting), dict(residual), dict(ambiguous), count, first_as_of, last_as_of,
        bridged, _cik_renames_split(pieces),
    )  # fmt: skip


def _cik_renames_split(pieces: Mapping[tuple[str, str], Sequence[tuple[_Run, Interval]]]) -> int:
    """(CIK, ticker) securities whose CIK continues under a different ticker within 70 days of
    their end: a rename of a name with no composite FIGI, split in two by the key rule. Counted so
    the continuity cost is a number before membership is built; the rule does not merge them."""
    by_cik: dict[str, list[tuple[date, date, str]]] = {}
    for (kind, value), group in pieces.items():
        if kind == CIK_TICKER:
            cik = value.split(":", 1)[0]
            for run, (a, b) in group:
                by_cik.setdefault(cik, []).append((a, b, run.ticker))
    count = 0
    for spans in by_cik.values():
        spans.sort()
        for (_, end, ticker), (start, _, other) in pairwise(spans):
            if (
                other != ticker
                and end != date.max
                and timedelta(0) <= start - end <= timedelta(days=70)
            ):
                count += 1
    return count


def _check_identifier_uniqueness(identifiers: Sequence[PitIdentifier]) -> None:
    """One live row per (scheme, value): the table's exclusion constraint, checked here."""
    seen: dict[tuple[str, str], str] = {}
    for i in identifiers:
        other = seen.setdefault((i.scheme, i.value), i.symbol)
        if other != i.symbol:
            raise PitPlanError(f"{i.scheme} {i.value} is planned for {other} and {i.symbol}")


def pins(plan: PitPlan) -> dict[str, str]:
    """Digests of the plan's own content, for the map's ``map_diff.json``."""

    def digest(rows: Iterable[Any]) -> str:
        return hashlib.sha256("\n".join(canonical_json(r) for r in rows).encode()).hexdigest()

    return {
        "spans_sha256": digest(
            (s.symbol, s.ticker, s.start.isoformat(), s.end.isoformat() if s.end else "")
            for s in plan.spans
        ),
        "identifiers_sha256": digest(
            (i.symbol, i.scheme, i.value, i.valid_from.isoformat()) for i in plan.identifiers
        ),
    }


__all__ = [
    "ALREADY_LIVE", "BAD_TICKER", "CIK_TICKER", "CLAIMED_TWICE", "CLIPPED_BY_LIVE_SPAN",
    "COMPOSITE_FIGI", "LiveState", "MASSIVE_ARCHIVE_START", "NO_KEY", "PIT_MAP_VERSION",
    "PIT_RULE_ID", "PLACED", "PLACED_PARTIAL", "PitIdentifier", "PitPlan", "PitPlanError",
    "PitRecord", "PitSecurity", "PitSnapshot", "PitSpan", "SHARE_CLASS_FIGI", "build_runs",
    "pins", "pit_record", "plan_pit_map", "records_from_pages",
]  # fmt: skip
