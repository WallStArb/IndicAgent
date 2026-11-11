"""Split reconciliation: a vendor's splits endpoint against `corporate_action` (admission step 4).

Massive admission design section 5 (docs/plans/2026-11-10-massive-admission-db-design.md): Massive
bars are unadjusted, so canonical rescales them by every recorded split, and a split missing from
`corporate_action` would leave an unseen price step in permanent adjusted data. This module is the
pure half of the first gate: it merges the two captured splits families, attributes each event to
an active instrument, and partitions every event of either side into one outcome.

Conventions (migration 400): a split's factor is old-scale price / new-scale price, so a 2-for-1
records 2.0 and a 1-for-10 records 0.1; its effective date is the last session on the old scale. A
vendor's execution date is the first session on the new scale, so the vendor's effective date is
the session before it.

The two families (captured 2026-11-10, both kept as the two witnesses they are, design section 6):
``v3`` (``/v3/reference/splits``) and ``bulk`` (``/stocks/v1/splits``, which adds
``adjustment_type``). One event id names the same event in both. A family pair that disagrees on
date or ratio is a conflict: the event is listed and never proposed.

Neither family's ticker is reliably the string the event traded under (measured 2026-11-10): the
bulk family labels AXON's 2004 splits ``AXON`` (it traded as TASR) and BR's 2004 split ``BR``
(Burlington Resources, not Broadridge, which listed in 2007); the v3 family labels Chevron's 2004
split ``CHV`` and Cummins' 2008 split ``CUM`` (both pre-2001 strings), ``SCCO`` for the 2008 PCU
split (the current string), and drops share-class dots (``HEIA`` for HEI.A). A label is therefore
evidence, never an identity, and attribution goes through the instrument's identity:

- ``span``: the bulk ticker is a string the instrument held at the execution date (its string
  spans, from the ticker-entity evidence), the strongest reading;
- ``span_v3``: the same through the v3 ticker only;
- ``current_label``: no span covers the date under either label, but a label is the instrument's
  own symbol and the date is on or after its list date: the vendor restated the event under the
  current string;
- ``predates_entity`` (excluded): a label is the symbol but the date precedes the list date: the
  string belonged to another security then (BR 2004);
- ``ambiguous`` (excluded): the labels resolve to two different instruments;
- ``unanchored`` (excluded): the instrument has no list date, so no identity evidence dates its
  hold on the string, and a reused string's older events cannot be told from its own.

Tickers are compared with share-class dots removed (the v3 spelling).

Outcomes, one per event (the partition sums to every attributed vendor event plus every recorded
row):

- ``agree``: same symbol, same effective date, ratio within the split-ratio tolerance.
- ``date_offset``: the same event (within ``same_event_days``, the writer's existing-row window) a
  number of sessions apart.
- ``ratio_disagree``: the same event at a different ratio (dated or not).
- ``massive_only``: a vendor split with no recorded row: the proposal candidates.
- ``ours_only``: a recorded split fact with no vendor event.
- ``vendor_correction``: a recorded row that rescales an incumbent's mis-scaled route and records
  no market split (corporate_actions.is_market_split: a todo 592 operator row); it is never
  compared as one, and a vendor event at its date stays massive_only.
- ``announced``: a vendor split whose execution date is after the serve date of the pages that
  served it: an announcement whose
  old scale has not ended (the announcement-time rule, design section 5 amendment). Listed, never
  proposed until a re-capture after the execution date.
- ``before_archive``: an unpaired vendor split whose new scale starts before the archive's first session: no
  Massive bar is rescaled by it, so it is listed and never proposed.

Pure: values in, records out; no database, no I/O, tolerances are parameters from APR.
"""

from __future__ import annotations

import math
from bisect import bisect_left
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date
from typing import Any, Literal, get_args

from src.intelligence.bars.corporate_actions import SplitRatioRule, recognised_split_ratio

V3 = "v3"
BULK = "bulk"

Attribution = Literal[
    "span", "span_v3", "current_label", "predates_entity", "ambiguous", "unanchored"
]
# Attributions that make an event the instrument's own.
OWN_ATTRIBUTIONS = frozenset({"span", "span_v3", "current_label"})

Outcome = Literal[
    "agree",
    "date_offset",
    "ratio_disagree",
    "massive_only",
    "ours_only",
    "vendor_correction",
    "announced",
    "before_archive",
]
OUTCOMES: tuple[Outcome, ...] = get_args(Outcome)


def split_factor(split_to: float, split_from: float) -> float:
    """Old-scale / new-scale price of a vendor split (2-for-1: split_to 2, split_from 1 -> 2.0)."""
    to, frm = float(split_to), float(split_from)
    if not (math.isfinite(to) and math.isfinite(frm) and to > 0 and frm > 0):
        raise ValueError(f"unusable split terms {split_to!r}/{split_from!r}")
    return to / frm


@dataclass(frozen=True)
class VendorSplit:
    """One vendor split event, merged across the families that served it."""

    event_id: str
    execution_date: date  # first session on the new scale
    factor: float  # old-scale / new-scale price
    bulk_ticker: str | None  # the bulk family's label (as-of or current, module docstring)
    v3_ticker: str | None  # the v3 family's label
    adjustment_type: str | None  # bulk family only
    families: frozenset[str]
    evidence: tuple[str, ...]  # reference_raw ids of the pages that served it


@dataclass(frozen=True)
class FamilyConflict:
    """An event id the families (or one family's pages) served with different facts."""

    event_id: str
    readings: tuple[tuple[str, str, date, float], ...]  # (family, ticker, execution date, factor)


def merge_split_families(
    rows: Iterable[tuple[str, str, Mapping[str, Any]]],
) -> tuple[list[VendorSplit], list[FamilyConflict]]:
    """Merge (family, reference_raw_id, result) rows by event id.

    A repeated row with identical facts collapses (the v3 pull serves six ids twice); an id whose
    readings differ on execution date, factor or adjustment type, or whose family serves two
    tickers, is a conflict
    and is left out of the merged list. Sorted by (execution date, id)."""
    readings: dict[str, list[tuple[str, str, Mapping[str, Any]]]] = {}
    for family, raw_id, result in rows:
        if family not in (V3, BULK):
            raise ValueError(f"unknown splits family {family!r}")
        readings.setdefault(str(result["id"]), []).append((family, raw_id, result))
    merged: list[VendorSplit] = []
    conflicts: list[FamilyConflict] = []
    for event_id, served in sorted(readings.items()):
        facts = [
            (
                family,
                str(r["ticker"]),
                date.fromisoformat(r["execution_date"]),
                split_factor(r["split_to"], r["split_from"]),
            )
            for family, _raw, r in served
        ]
        dates = {f[2] for f in facts}
        factors = {f[3] for f in facts}
        tickers = {family: {f[1] for f in facts if f[0] == family} for family in (V3, BULK)}
        bulk_types = {r.get("adjustment_type") for family, _raw, r in served if family == BULK}
        if (
            len(dates) > 1
            or len(factors) > 1
            or len(bulk_types) > 1
            or any(len(t) > 1 for t in tickers.values())
        ):
            conflicts.append(FamilyConflict(event_id, tuple(sorted(set(facts)))))
            continue
        merged.append(
            VendorSplit(
                event_id=event_id,
                execution_date=dates.pop(),
                factor=factors.pop(),
                bulk_ticker=next(iter(tickers[BULK]), None),
                v3_ticker=next(iter(tickers[V3]), None),
                adjustment_type=next(iter(bulk_types), None),
                families=frozenset(f[0] for f in facts),
                evidence=tuple(sorted({raw for _f, raw, _r in served})),
            )
        )
    merged.sort(key=lambda s: (s.execution_date, s.event_id))
    return merged, conflicts


def ticker_key(ticker: str) -> str:
    """A ticker compared across spellings: share-class dots removed (the v3 family's spelling)."""
    return ticker.replace(".", "")


@dataclass(frozen=True)
class StringSpan:
    """One ticker string an active instrument's security held over [valid_from, valid_to)."""

    symbol: str
    string: str
    valid_from: date
    valid_to: date | None  # None: still held


@dataclass(frozen=True)
class IdentityIndex:
    """The attribution's view of identity: string spans by ticker key, list dates by symbol key."""

    spans: Mapping[str, Sequence[StringSpan]]
    list_dates: Mapping[str, date | None]  # ticker_key(symbol) -> list date (None: unknown)
    symbols: Mapping[str, str]  # ticker_key(symbol) -> symbol

    @classmethod
    def build(
        cls, spans: Iterable[StringSpan], list_dates: Mapping[str, date | None]
    ) -> IdentityIndex:
        by_key: dict[str, list[StringSpan]] = {}
        for span in spans:
            by_key.setdefault(ticker_key(span.string), []).append(span)
        return cls(
            by_key,
            {ticker_key(s): d for s, d in list_dates.items()},
            {ticker_key(s): s for s in list_dates},
        )

    def held(self, ticker: str, day: date) -> set[str]:
        """The instruments whose security held the ticker string on the day."""
        return {
            s.symbol
            for s in self.spans.get(ticker_key(ticker), ())
            if s.valid_from <= day and (s.valid_to is None or day < s.valid_to)
        }


def attribute(split: VendorSplit, index: IdentityIndex) -> tuple[str, Attribution] | None:
    """The active instrument a vendor split concerns and how (module docstring), or None when
    neither label names one. Pure."""
    day = split.execution_date
    labels = [t for t in (split.bulk_ticker, split.v3_ticker) if t is not None]
    held_by = {t: index.held(t, day) for t in labels}
    every = set().union(*held_by.values())
    unanchored = {s for s in every if index.list_dates.get(ticker_key(s)) is None}
    if unanchored and len(every) == 1:
        return min(unanchored), "unanchored"
    if len(every) > 1:
        return min(every), "ambiguous"
    for ticker, how in ((split.bulk_ticker, "span"), (split.v3_ticker, "span_v3")):
        if ticker is not None and held_by[ticker]:
            return min(held_by[ticker]), how  # type: ignore[return-value]
    named = sorted({index.symbols[ticker_key(t)] for t in labels if ticker_key(t) in index.symbols})
    if len(named) > 1:
        return named[0], "ambiguous"
    if not named:
        return None
    symbol = named[0]
    listed = index.list_dates.get(ticker_key(symbol))
    if listed is None:
        return symbol, "unanchored"
    if day < listed:
        return symbol, "predates_entity"
    return symbol, "current_label"


# Strongest attribution first: a duplicate keeps the strongest reading among its ids.
_ATTRIBUTION_RANK = {"span": 0, "span_v3": 1, "current_label": 2}


@dataclass(frozen=True)
class VendorDuplicate:
    """Vendor event ids that are one split of one instrument (kept) or contradict each other."""

    symbol: str
    kept: str | None  # the surviving id; None when the group conflicts and none survives
    ids: tuple[str, ...]  # every id of the group
    readings: tuple[tuple[date, float], ...]  # (execution date, factor) per id


def collapse_vendor_duplicates(
    attributed: Sequence[tuple[VendorSplit, str, Attribution]], same_event_days: int
) -> tuple[list[tuple[VendorSplit, str, Attribution]], list[VendorDuplicate]]:
    """One event per split of an instrument (measured 2026-11-10: the vendor serves some splits
    under two ids, CMI 2007-04-10 and TAP 2007-10-04 among them, and its own
    historical_adjustment_factor compounds both, so two rows would rescale twice).

    Attributed events of one symbol within same_event_days of each other form a group. A group
    whose members share execution date and factor collapses to one event (the strongest
    attribution, then the smallest id) carrying the union of families and evidence; a group
    that disagrees on date or factor is a vendor-internal conflict and no member survives.
    Returns (events, groups of more than one id). Pure."""
    by_symbol: dict[str, list[tuple[VendorSplit, Attribution]]] = {}
    for split, symbol, how in attributed:
        by_symbol.setdefault(symbol, []).append((split, how))
    kept: list[tuple[VendorSplit, str, Attribution]] = []
    groups: list[VendorDuplicate] = []
    for symbol, events in sorted(by_symbol.items()):
        events.sort(key=lambda e: (e[0].execution_date, e[0].event_id))
        run: list[tuple[VendorSplit, Attribution]] = []
        for event in [*events, None]:
            if event is not None and (
                not run
                or (event[0].execution_date - run[-1][0].execution_date).days <= same_event_days
            ):
                run.append(event)
                continue
            if len(run) == 1:
                kept.append((run[0][0], symbol, run[0][1]))
            elif run:
                readings = tuple((s.execution_date, s.factor) for s, _h in run)
                ids = tuple(s.event_id for s, _h in run)
                if len(set(readings)) == 1:
                    best, how = min(run, key=lambda e: (_ATTRIBUTION_RANK[e[1]], e[0].event_id))
                    merged = replace(
                        best,
                        families=frozenset().union(*(s.families for s, _h in run)),
                        evidence=tuple(sorted({e for s, _h in run for e in s.evidence})),
                    )
                    kept.append((merged, symbol, how))
                    groups.append(VendorDuplicate(symbol, best.event_id, ids, readings))
                else:
                    groups.append(VendorDuplicate(symbol, None, ids, readings))
            run = [] if event is None else [event]
    kept.sort(key=lambda k: (k[0].execution_date, k[0].event_id))
    return kept, groups


def proposal_status(
    member: ReconciledSplit, tape: str, rule: SplitRatioRule
) -> Literal["proposed", "not_a_split_ratio", "tape_flat", "tape_conflict", "no_tape"]:
    """Whether a massive_only event becomes a proposed corporate_action row: its factor must be a
    recognised split ratio (the vendor serves spin-off adjustments as forward splits, YUM
    2016-11-01 x1.391, and stock dividends; neither is a split row) and the vendor's own
    unadjusted tape must step by it (level_seams.tape_reading). Anything else is a review row."""
    if member.outcome != "massive_only" or member.vendor is None:
        raise ValueError(f"only a massive_only event is proposed, got {member.outcome}")
    if recognised_split_ratio(member.vendor.factor, rule) is None:
        return "not_a_split_ratio"
    if tape == "tape_step":
        return "proposed"
    if tape not in ("tape_flat", "tape_conflict", "no_tape"):
        raise ValueError(f"unknown tape reading {tape!r}")
    return tape  # type: ignore[return-value]


@dataclass(frozen=True)
class RecordedSplit:
    """One corporate_action_current split row as the reconciliation reads it."""

    action_id: str
    symbol: str
    effective_date: date  # last session on the old scale
    factor: float
    inferred_by: str
    vendor_correction: bool  # not corporate_actions.is_market_split: rescales one incumbent


@dataclass(frozen=True)
class ReconciledSplit:
    """One partition member: a vendor event, a recorded row, or a pair of both."""

    symbol: str
    outcome: Outcome
    vendor: VendorSplit | None = None
    attribution: Attribution | None = None
    ours: RecordedSplit | None = None
    vendor_effective_date: date | None = None
    session_offset: int | None = None  # ours minus vendor, in sessions
    log_ratio_gap: float | None = None  # ln(ours factor / vendor factor)


@dataclass(frozen=True)
class ReconcileParams:
    """The reconciliation's tolerances (APR, read by the caller)."""

    ratio_rel_tol: float  # infra.backfill.split_ratio_rel_tol: two ratios are one ratio
    same_event_days: int  # calendar days: the corporate_action writer's existing-row window
    served_on: Mapping[str, date]  # reference page id -> its serve date (America/New_York)
    archive_start: date  # the first session a vendor bar exists for
    sessions: Sequence[date]  # sorted NYSE sessions


def vendor_effective_date(execution_date: date, sessions: Sequence[date]) -> date:
    """The last session before the execution date (the vendor's effective date, migration 400)."""
    i = bisect_left(sessions, execution_date)
    if i == 0:
        raise ValueError(f"no session before {execution_date}")
    return sessions[i - 1]


def _session_offset(ours: date, theirs: date, sessions: Sequence[date]) -> int:
    return bisect_left(sessions, ours) - bisect_left(sessions, theirs)


def _ratio_agrees(a: float, b: float, rel_tol: float) -> bool:
    return abs(a / b - 1.0) <= rel_tol


def reconcile(
    vendor: Sequence[tuple[VendorSplit, str, Attribution]],
    recorded: Sequence[RecordedSplit],
    params: ReconcileParams,
) -> list[ReconciledSplit]:
    """The complete partition of the attributed vendor events (own attributions only) and the
    recorded rows, one member each (a pair counts once). Pairs are matched per symbol, nearest
    calendar distance first, within same_event_days; a vendor event announced after the capture is
    never paired, and an unpaired one whose new scale starts before the archive is before_archive
    (paired, it reconciles like any other). Deterministic: ties break by date, then id.
    """
    out: list[ReconciledSplit] = []
    open_vendor: dict[str, list[tuple[VendorSplit, Attribution, date]]] = {}
    for split, symbol, how in vendor:
        if how not in OWN_ATTRIBUTIONS:
            raise ValueError(f"{split.event_id}: {how} is not the instrument's own event")
        # An announcement until a page that served it was served on or after its execution date.
        if split.execution_date > max(params.served_on[e] for e in split.evidence):
            out.append(ReconciledSplit(symbol, "announced", split, how))
            continue
        effective = vendor_effective_date(split.execution_date, params.sessions)
        open_vendor.setdefault(symbol, []).append((split, how, effective))
    # A vendor correction (corporate_actions.is_market_split: a todo 592 operator row) rescales
    # one incumbent's route and is no market fact, even at the split's own ratio (UHAL
    # 2022-11-09 x10): selection and the daily rule never rescale Massive by it, so the market's
    # split stays massive_only and needs its own row.
    facts: dict[str, list[RecordedSplit]] = {}
    for row in recorded:
        if row.vendor_correction:
            out.append(ReconciledSplit(row.symbol, "vendor_correction", ours=row))
        else:
            facts.setdefault(row.symbol, []).append(row)
    for symbol in sorted(set(open_vendor) | set(facts)):
        theirs = sorted(open_vendor.get(symbol, []), key=lambda t: (t[2], t[0].event_id))
        ours = sorted(facts.get(symbol, []), key=lambda r: (r.effective_date, r.action_id))
        pairs = sorted(
            (abs((o.effective_date - t[2]).days), t[2], o.effective_date, ti, oi)
            for ti, t in enumerate(theirs)
            for oi, o in enumerate(ours)
            if abs((o.effective_date - t[2]).days) <= params.same_event_days
        )
        used_t: set[int] = set()
        used_o: set[int] = set()
        for _dist, _td, _od, ti, oi in pairs:
            if ti in used_t or oi in used_o:
                continue
            used_t.add(ti)
            used_o.add(oi)
            split, how, effective = theirs[ti]
            row = ours[oi]
            offset = _session_offset(row.effective_date, effective, params.sessions)
            if not _ratio_agrees(row.factor, split.factor, params.ratio_rel_tol):
                outcome: Outcome = "ratio_disagree"
            elif offset != 0:
                outcome = "date_offset"
            else:
                outcome = "agree"
            out.append(
                ReconciledSplit(
                    symbol,
                    outcome,
                    split,
                    how,
                    row,
                    effective,
                    offset,
                    round(math.log(row.factor / split.factor), 6),
                )
            )
        for ti, (split, how, effective) in enumerate(theirs):
            if ti not in used_t:
                unpaired: Outcome = (
                    "before_archive"
                    if split.execution_date <= params.archive_start
                    else "massive_only"
                )
                out.append(ReconciledSplit(symbol, unpaired, split, how, None, effective))
        for oi, row in enumerate(ours):
            if oi not in used_o:
                out.append(ReconciledSplit(symbol, "ours_only", ours=row))
    return out


def partition_counts(members: Sequence[ReconciledSplit]) -> dict[str, int]:
    """Members per outcome, every outcome named (a zero is a reading, not an absence)."""
    counts = {outcome: 0 for outcome in OUTCOMES}
    for member in members:
        counts[member.outcome] += 1
    return counts
