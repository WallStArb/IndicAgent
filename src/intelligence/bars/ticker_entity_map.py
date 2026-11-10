"""Ticker-to-entity map, stage 1: current names only (admission design section 6, step 3b).

One pure function, ``propose_ticker_entity_map``, turns reference answers into the proposed
``security_identifier`` and ``ticker_event`` rows plus the gap list. No I/O; the same answers
give the same rows and the same digest.

Identity is anchored outside Massive, and each identifier row comes from its own outside
source: the ISIN from IBKR's contract details for our symbol, the US composite and share-class
FIGI from OpenFIGI's mapping of that ISIN (OpenFIGI is the FIGI registry). Massive's answer for
the same ticker today must carry the same FIGIs (every FIGI Massive serves must agree; the
share-class FIGI decides where served, else the composite); that agreement gates the spans,
never the identifiers. CIK is an issuer key and is never read (one CIK covers BRK.A and BRK.B).

History comes from FIGI-grouping the Massive events answers: every OK events answer whose body
names the matched composite FIGI. Events are ``ticker_change`` rows, newest first, each "from
this session the ticker is X" (checked against the day files: FB to META on 2022-06-09, BHGE to
BKR on 2019-10-18). Spans are ``[date_i, date_{i+1})``, the newest one open. A chain is refused
whole when its newest event is not today's ticker (BRK.B's chain names the root BRK, which the
files never serve; A's names AWD, which the files never serve for Agilent; HEI's root is a
different share class). A span is dropped, and listed, when its ticker is not a listed ticker
string (blank, or a vendor placeholder such as S974), when the delisted universe shows another
security giving up the same string inside the span (a reused ticker), or when any other
security's events chain (ours or not) claims the string over part of the span: one vendor row
must never load under two securities. Two kinds of evidence are cited in the span's evidence
and judge nothing: an undated delisted row (it cannot place its holder in time) and a
root-labelled chain's claim (its newest event is a prefix of its own ticker, GEF.B naming GEF).
Before a name's first event the vendor gives no evidence, so a listing earlier than it is a
listed coverage gap, never a span. Price continuity is not evidence here; it is a load check
(design section 8a).
"""

from __future__ import annotations

import hashlib
import re
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field, replace
from datetime import UTC, date, datetime
from typing import Any

from src.core.canonical_json import canonical_json

MAP_VERSION = "1"
# The first session of the Massive flat-file archive (design section 2): no coverage gap
# reaches before it.
MASSIVE_ARCHIVE_START = date(2003, 9, 10)
# The asset classes the Massive stock flat files hold, and the only ones IBKR is asked about as
# a Stock: a futures symbol spelled like a stock ticker (ES) must never resolve to the stock.
MASSIVE_ASSET_CLASSES = frozenset({"equity"})
# The identifier every span resolves to: the events bodies carry only it.
SPAN_SCHEME = "composite_figi"
_FIGI_SCHEMES = ("composite_figi", "share_class_figi")
# A listed equity ticker string: capitals, an optional class suffix (BRK.B), as the day files
# serve them. Anything else (blank, S974) is not a string a day file row can be keyed by.
_LISTED_TICKER = re.compile(r"[A-Z]+(\.[A-Z]+)?")  # used with fullmatch

# Instrument-level gap reasons (the name gets no span), in the order they are judged.
ASSET_CLASS_OUTSIDE_VENDOR = "asset_class_outside_vendor"
IBKR_UNANSWERED = "ibkr_unanswered"
IBKR_NOT_FOUND = "ibkr_not_found"
IBKR_ERROR = "ibkr_error"
IBKR_NO_ISIN = "ibkr_no_isin"
IBKR_ISIN_AMBIGUOUS = "ibkr_isin_ambiguous"
OPENFIGI_UNANSWERED = "openfigi_unanswered"
OPENFIGI_NO_MATCH = "openfigi_no_match"
OPENFIGI_ERROR = "openfigi_error"
OPENFIGI_AMBIGUOUS = "openfigi_ambiguous"
MASSIVE_UNANSWERED = "massive_unanswered"
MASSIVE_OVERVIEW_ERROR = "massive_overview_error"
MASSIVE_TICKER_NOT_ACTIVE = "massive_ticker_not_active"
MASSIVE_NO_FIGI = "massive_no_figi"
FIGI_DISAGREES_WITH_ISIN = "figi_disagrees_with_isin"
EVENTS_UNANSWERED = "events_unanswered"
EVENTS_FIGI_DISAGREES = "events_figi_disagrees"
EVENTS_GROUP_CONFLICT = "events_group_conflict"
EVENTS_MALFORMED = "events_malformed"
EVENT_CHAIN_HEAD_MISMATCH = "event_chain_head_mismatch"
IDENTIFIER_CLAIMED_TWICE = "identifier_claimed_twice"
NO_SPAN_SURVIVED = "no_span_survived"
# Span-level coverage gaps on a mapped name.
BEFORE_FIRST_EVENT = "before_first_event"
EVENT_TICKER_UNUSABLE = "event_ticker_unusable"
TICKER_HELD_BY_DELISTED_SECURITY = "ticker_held_by_delisted_security"
TICKER_CLAIMED_BY_OTHER_SECURITY = "ticker_claimed_by_other_security"


@dataclass(frozen=True)
class Answer:
    """One ``reference_raw_current`` row: its id, serve time and parsed body."""

    reference_raw_id: str
    served_at: datetime
    body: Any


@dataclass(frozen=True)
class DelistedTicker:
    """One row of Massive's delisted universe as served: the string, ``delisted_utc``, the page."""

    ticker: str
    delisted_utc: str | None
    reference_raw_id: str

    @property
    def delisted_on(self) -> date | None:
        if not self.delisted_utc:
            return None
        moment = datetime.fromisoformat(self.delisted_utc)
        if moment.tzinfo is None:
            raise ValueError(f"delisted_utc without a zone: {self.delisted_utc!r}")
        return moment.astimezone(UTC).date()


@dataclass(frozen=True)
class MapInputs:
    instruments: Mapping[str, str]  # symbol -> asset class
    overview: Mapping[str, Answer]  # Massive ticker overview by request key (A@active)
    events: Mapping[str, Answer]  # Massive ticker events by request key
    delisted: Sequence[DelistedTicker]
    contract_details: Mapping[str, Answer]  # IBKR, keyed by our symbol
    figi_mapping: Mapping[str, Answer]  # OpenFIGI US mapping, keyed by ISIN


@dataclass(frozen=True)
class ProposedIdentifier:
    symbol: str
    scheme: str
    value: str
    valid_from: date
    reference_raw_id: str


@dataclass(frozen=True)
class ProposedSpan:
    symbol: str
    ticker: str
    valid_from: date
    valid_to: date | None
    reference_raw_id: str  # the events answer that asserts the span
    evidence: dict = field(hash=False, compare=False)


@dataclass(frozen=True)
class Gap:
    """A name, or a span of a mapped name, the map gives no evidenced span for.

    ``valid_from`` None means the whole history (the name has no span at all)."""

    symbol: str
    reason: str
    valid_from: date | None
    valid_to: date | None
    detail: dict = field(hash=False)


@dataclass(frozen=True)
class Proposal:
    identifiers: tuple[ProposedIdentifier, ...]
    spans: tuple[ProposedSpan, ...]
    gaps: tuple[Gap, ...]
    # Events answers whose chain could not be read, so their ticker claims judge nothing.
    unreadable_chains: tuple[str, ...]
    digest: str

    def partition(self) -> dict[str, int]:
        """Each instrument once: ``mapped`` or its instrument-level gap reason."""
        counts = Counter(g.reason for g in self.gaps if g.valid_from is None)
        counts["mapped"] = len({s.symbol for s in self.spans})
        return dict(sorted(counts.items()))

    def span_gaps(self) -> dict[str, int]:
        """Coverage gaps on mapped names, by reason."""
        return dict(sorted(Counter(g.reason for g in self.gaps if g.valid_from).items()))


class _Refused(Exception):
    def __init__(self, reason: str, **detail: Any):
        super().__init__(reason)
        self.reason = reason
        self.detail = detail


@dataclass
class _Name:
    """One instrument's working result before the cross-instrument checks."""

    symbol: str
    identifiers: list[ProposedIdentifier] = field(default_factory=list)
    spans: list[ProposedSpan] = field(default_factory=list)
    gaps: list[Gap] = field(default_factory=list)
    composite: str | None = None  # the matched composite FIGI, when the ISIN mapped

    def date_composite(self) -> None:
        """The composite FIGI holds from the first surviving span: the events answers asserting
        the spans name it. The share-class FIGI and the ISIN rest on today's answers only, so
        they keep their answers' dates. Without a span, the composite keeps OpenFIGI's date."""
        if self.spans:
            first = min(s.valid_from for s in self.spans)
            self.identifiers = [
                replace(i, valid_from=first) if i.scheme == SPAN_SCHEME else i
                for i in self.identifiers
            ]


@dataclass(frozen=True)
class _Figi:
    """OpenFIGI's FIGIs for one ISIN."""

    composite: str
    share_class: str | None
    answer: Answer


def _ok(answer: Answer | None) -> bool:
    return (
        answer is not None and isinstance(answer.body, dict) and answer.body.get("status") == "OK"
    )


def isins_of(contract_details_body: dict) -> set[str]:
    """Every ISIN an IBKR contract-details body serves (``secIdList`` of each result)."""
    return {
        value
        for result in contract_details_body.get("results") or []
        for tag, value in result.get("secIdList") or []
        if tag == "ISIN"
    }


def _isin(symbol: str, inputs: MapInputs) -> tuple[str, Answer]:
    answer = inputs.contract_details.get(symbol)
    if answer is None:
        raise _Refused(IBKR_UNANSWERED)
    status = answer.body.get("status")
    if status == "NOT_FOUND":
        raise _Refused(IBKR_NOT_FOUND, ibkr_answer=answer.reference_raw_id)
    if status != "OK":
        raise _Refused(IBKR_ERROR, ibkr_answer=answer.reference_raw_id, status=status)
    isins = isins_of(answer.body)
    if not isins:
        raise _Refused(IBKR_NO_ISIN, ibkr_answer=answer.reference_raw_id)
    if len(isins) > 1:
        raise _Refused(
            IBKR_ISIN_AMBIGUOUS, ibkr_answer=answer.reference_raw_id, isins=sorted(isins)
        )
    return isins.pop(), answer


def _openfigi(isin: str, inputs: MapInputs) -> _Figi:
    """The ISIN's US composite FIGI and share-class FIGI, as OpenFIGI serves them."""
    answer = inputs.figi_mapping.get(isin)
    if answer is None:
        raise _Refused(OPENFIGI_UNANSWERED, isin=isin)
    body = answer.body
    job = body[0] if isinstance(body, list) and len(body) == 1 else None
    if not isinstance(job, dict) or "error" in job:
        # A job-level error, or a body that is not one job's answer: a failed ask, not a verdict.
        raise _Refused(OPENFIGI_ERROR, isin=isin, openfigi_answer=answer.reference_raw_id)
    records = job.get("data")
    if not records:
        raise _Refused(OPENFIGI_NO_MATCH, isin=isin, openfigi_answer=answer.reference_raw_id)
    composites = {r.get("compositeFIGI") for r in records}
    share_classes = {r.get("shareClassFIGI") for r in records}
    if len(composites) != 1 or None in composites or len(share_classes) != 1:
        raise _Refused(
            OPENFIGI_AMBIGUOUS,
            isin=isin,
            openfigi_answer=answer.reference_raw_id,
            composites=sorted(map(str, composites)),
            share_classes=sorted(map(str, share_classes)),
        )
    return _Figi(composites.pop(), share_classes.pop(), answer)


def _massive_overview(symbol: str, inputs: MapInputs) -> Answer:
    key = f"{symbol}@active"
    answer = inputs.overview.get(key)
    if _ok(answer):
        return answer
    if answer is not None and not (
        isinstance(answer.body, dict) and answer.body.get("status") == "NOT_FOUND"
    ):
        # A failed ask, not a verdict on the ticker.
        raise _Refused(MASSIVE_OVERVIEW_ERROR, overview_answer=answer.reference_raw_id)
    others = sorted(k for k in inputs.overview if k.split("@", 1)[0] == symbol and k != key)
    if others:
        raise _Refused(MASSIVE_TICKER_NOT_ACTIVE, massive_requests=others)
    raise _Refused(MASSIVE_UNANSWERED)


def _agreement(overview: Answer, figi: _Figi) -> str:
    """The FIGI Massive's answer is matched on; every FIGI it serves must equal OpenFIGI's."""
    served = overview.body["results"]
    composite, share = served.get("composite_figi"), served.get("share_class_figi")
    if not composite and not share:
        raise _Refused(MASSIVE_NO_FIGI, overview_answer=overview.reference_raw_id)
    disagree = {
        scheme: [massive, openfigi]
        for scheme, massive, openfigi in (
            ("composite_figi", composite, figi.composite),
            ("share_class_figi", share, figi.share_class),
        )
        if massive and massive != openfigi
    }
    if disagree:
        raise _Refused(FIGI_DISAGREES_WITH_ISIN, disagree=disagree)
    return "share_class_figi" if share else "composite_figi"


def _events_index(events: Mapping[str, Answer]) -> dict[str, list[Answer]]:
    """FIGI-grouping: every OK events answer by the composite FIGI its body names."""
    index: dict[str, list[Answer]] = defaultdict(list)
    for key in sorted(events):
        answer = events[key]
        if _ok(answer) and answer.body["results"].get("composite_figi"):
            index[answer.body["results"]["composite_figi"]].append(answer)
    return index


def _chain(
    symbol: str, composite: str, inputs: MapInputs, index: Mapping
) -> tuple[list[tuple[date, str]], Answer, list[str]]:
    """The validated event chain oldest first, its own answer and the group's answer ids."""
    own = inputs.events.get(f"{symbol}@active")
    if not _ok(own):
        raise _Refused(EVENTS_UNANSWERED)
    if own.body["results"].get("composite_figi") != composite:
        raise _Refused(
            EVENTS_FIGI_DISAGREES,
            events_answer=own.reference_raw_id,
            events_composite=own.body["results"].get("composite_figi"),
        )
    group = index.get(composite, [])
    if len({canonical_json(a.body["results"].get("events")) for a in group}) != 1:
        raise _Refused(EVENTS_GROUP_CONFLICT, events_group=[a.reference_raw_id for a in group])
    events = own.body["results"].get("events") or []
    try:
        dates = [date.fromisoformat(e["date"]) for e in events]
        tickers = [e["ticker_change"]["ticker"] for e in events]
        well_formed = (
            bool(events)
            and all(e["type"] == "ticker_change" for e in events)
            and all(isinstance(t, str) for t in tickers)
        )
    except (KeyError, TypeError, ValueError):
        well_formed = False
    if not well_formed or any(a <= b for a, b in zip(dates, dates[1:], strict=False)):
        raise _Refused(EVENTS_MALFORMED, events_answer=own.reference_raw_id)
    if tickers[0] != symbol:
        raise _Refused(
            EVENT_CHAIN_HEAD_MISMATCH,
            events_answer=own.reference_raw_id,
            head=tickers[0],
            chain=[[d.isoformat(), t] for d, t in zip(dates, tickers, strict=True)],
        )
    return sorted(zip(dates, tickers, strict=True)), own, [a.reference_raw_id for a in group]


def _spans(
    name: _Name, chain: list[tuple[date, str]], events: Answer, delisted: Mapping, cited: dict
) -> None:
    """One span per chain link, unless the link's ticker is blank or held by another security."""
    for position, (start, ticker) in enumerate(chain):
        following = chain[position + 1] if position + 1 < len(chain) else None
        end = following[0] if following else None
        if not _LISTED_TICKER.fullmatch(ticker):
            detail = {"ticker": ticker}
            name.gaps.append(Gap(name.symbol, EVENT_TICKER_UNUSABLE, start, end, detail))
            continue
        holders = delisted.get(ticker, ())
        clash = [
            [d.delisted_on.isoformat(), d.reference_raw_id]
            for d in holders
            if d.delisted_on and d.delisted_on > start and (end is None or d.delisted_on < end)
        ]
        if clash:
            detail = {"ticker": ticker, "delisted": clash}
            name.gaps.append(Gap(name.symbol, TICKER_HELD_BY_DELISTED_SECURITY, start, end, detail))
            continue
        evidence = {
            **cited,
            "map_version": MAP_VERSION,
            "events_answer": events.reference_raw_id,
            "event": {"date": start.isoformat(), "ticker": ticker},
            "next_event": following and {"date": end.isoformat(), "ticker": following[1]},
            "delisted_check": "no dated delisted row gives this ticker up inside the span",
            "undated_delisted": sorted({d.reference_raw_id for d in holders if not d.delisted_on}),
            "price_continuity": "not judged here: a load check by level over the span (design 8a)",
        }
        name.spans.append(
            ProposedSpan(name.symbol, ticker, start, end, events.reference_raw_id, evidence)
        )


def _before_first_event(name: _Name, overview: Answer, first: date) -> None:
    listed = overview.body["results"].get("list_date")
    gap_from = max(date.fromisoformat(listed) if listed else date.min, MASSIVE_ARCHIVE_START)
    if gap_from < first:
        detail = {"list_date": listed, "first_event": first.isoformat()}
        name.gaps.append(Gap(name.symbol, BEFORE_FIRST_EVENT, gap_from, first, detail))


def _one_name(
    symbol: str, asset_class: str, inputs: MapInputs, index: Mapping, delisted: Mapping
) -> _Name:
    name = _Name(symbol)
    figi = None
    try:
        if asset_class not in MASSIVE_ASSET_CLASSES:
            raise _Refused(ASSET_CLASS_OUTSIDE_VENDOR, asset_class=asset_class)
        isin, ibkr = _isin(symbol, inputs)
        name.identifiers.append(
            ProposedIdentifier(symbol, "isin", isin, ibkr.served_at.date(), ibkr.reference_raw_id)
        )
        figi = _openfigi(isin, inputs)
        overview = _massive_overview(symbol, inputs)
        basis = _agreement(overview, figi)
        chain, events, group = _chain(symbol, figi.composite, inputs, index)
    except _Refused as error:
        name.gaps.append(Gap(symbol, error.reason, None, None, error.detail))
    else:
        cited = {
            "match": {
                "basis": basis,
                "isin": isin,
                "composite_figi": figi.composite,
                "share_class_figi": figi.share_class,
                "cik_used": False,
            },
            "overview_answer": overview.reference_raw_id,
            "ibkr_answer": ibkr.reference_raw_id,
            "openfigi_answer": figi.answer.reference_raw_id,
            "events_group": group,
        }
        _spans(name, chain, events, delisted, cited)
        _before_first_event(name, overview, chain[0][0])
    if figi is not None:
        # Each FIGI is dated by its answer; date_composite moves the composite to the first
        # span once the cross-instrument checks have dropped spans.
        name.composite = figi.composite
        served_on = figi.answer.served_at.date()
        for scheme, value in zip(_FIGI_SCHEMES, (figi.composite, figi.share_class), strict=True):
            if value:
                name.identifiers.append(
                    ProposedIdentifier(
                        symbol, scheme, value, served_on, figi.answer.reference_raw_id
                    )
                )
    return name


def _drop_identifier_collisions(names: list[_Name]) -> None:
    """A value naming two of our instruments refuses both names whole (no rows at all)."""
    owners: dict[tuple[str, str], set[str]] = defaultdict(set)
    for name in names:
        for ident in name.identifiers:
            owners[(ident.scheme, ident.value)].add(name.symbol)
    for name in names:
        shared = sorted(
            [scheme, value, sorted(owners[(scheme, value)])]
            for scheme, value in {(i.scheme, i.value) for i in name.identifiers}
            if len(owners[(scheme, value)]) > 1
        )
        if shared:
            name.identifiers, name.spans = [], []
            name.gaps = [Gap(name.symbol, IDENTIFIER_CLAIMED_TWICE, None, None, {"shared": shared})]


@dataclass(frozen=True)
class _Claim:
    """One link of an events chain: a security held a ticker string over a span."""

    composite: str | None  # None: the vendor serves the claiming security without a FIGI
    start: date
    end: date | None
    reference_raw_id: str
    root_label: bool  # the chain's root label (its head, a prefix of its own ticker)


def _claims(events: Mapping[str, Answer]) -> tuple[dict[str, list[_Claim]], list[str]]:
    """Every ticker string every OK events chain claims, by ticker; and the unreadable chains.

    A chain whose newest event is a strict prefix of its own request ticker is root-labelled:
    BRK.B's chain names BRK, GEF.B's names GEF, a warrant's names its stock's ticker. Those
    strings are the vendor's root labels, not what the day files serve for that security (the
    files serve BRK.B, and HEI for a different share class than HEI.A), so such a chain's
    claims on that string are cited but never refuse another security's span. Every other
    claim judges, a chain's older links included, and a chain served without a FIGI judges as
    an unknown security."""
    claims: dict[str, list[_Claim]] = defaultdict(list)
    unreadable: list[str] = []
    for key in sorted(events):
        answer = events[key]
        if not _ok(answer):
            continue
        composite = answer.body["results"].get("composite_figi") or None
        try:
            links = sorted(
                (date.fromisoformat(e["date"]), str(e["ticker_change"]["ticker"]))
                for e in answer.body["results"]["events"]
            )
            head = links[-1][1]
        except (KeyError, IndexError, TypeError, ValueError, AttributeError):
            unreadable.append(answer.reference_raw_id)
            continue
        asked = key.split("@", 1)[0]
        root = (
            head
            if _LISTED_TICKER.fullmatch(head) and head != asked and asked.startswith(head)
            else None
        )
        for position, (start, ticker) in enumerate(links):
            end = links[position + 1][0] if position + 1 < len(links) else None
            claims[ticker].append(
                _Claim(composite, start, end, answer.reference_raw_id, ticker == root)
            )
    return claims, unreadable


def _drop_claimed_spans(names: list[_Name], claims: Mapping[str, list[_Claim]]) -> None:
    """A span another security's chain claims over any part of it is dropped and listed."""
    for name in names:
        keep = []
        for span in name.spans:
            rivals = [
                c
                for c in claims.get(span.ticker, ())
                if c.composite != name.composite
                and c.start < (span.valid_to or date.max)
                and span.valid_from < (c.end or date.max)
            ]
            cited = [
                [c.composite, c.start.isoformat(), c.end and c.end.isoformat(), c.reference_raw_id]
                for c in rivals
            ]
            if any(not c.root_label for c in rivals):
                detail = {"ticker": span.ticker, "claimed_by": cited}
                name.gaps.append(
                    Gap(
                        name.symbol,
                        TICKER_CLAIMED_BY_OTHER_SECURITY,
                        span.valid_from,
                        span.valid_to,
                        detail,
                    )
                )
                continue
            if cited:
                evidence = {**span.evidence, "root_labelled_claims_not_judged": cited}
                span = replace(span, evidence=evidence)
            keep.append(span)
        name.spans = keep


def _plain(value: Any) -> Any:
    """Dates to ISO text, recursively, so the canonical JSON needs no fallback."""
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_plain(item) for item in value]
    return value


def proposal_digest(
    identifiers: Sequence[ProposedIdentifier],
    spans: Sequence[ProposedSpan],
    gaps: Sequence[Gap],
    unreadable_chains: Sequence[str],
) -> str:
    """sha256 over the canonical JSON of the whole proposal (rows in their sorted order)."""
    document = {
        "map_version": MAP_VERSION,
        "identifiers": [asdict(i) for i in identifiers],
        "spans": [asdict(s) for s in spans],
        "gaps": [asdict(g) for g in gaps],
        "unreadable_chains": list(unreadable_chains),
    }
    return hashlib.sha256(canonical_json(_plain(document)).encode("utf-8")).hexdigest()


def propose_ticker_entity_map(inputs: MapInputs) -> Proposal:
    """The stage 1 map: proposed identifier rows, spans and the gap list, with its digest."""
    index = _events_index(inputs.events)
    delisted: dict[str, list[DelistedTicker]] = defaultdict(list)
    for row in sorted(
        inputs.delisted, key=lambda d: (d.ticker, d.delisted_utc or "", d.reference_raw_id)
    ):
        delisted[row.ticker].append(row)
    names = [
        _one_name(symbol, inputs.instruments[symbol], inputs, index, delisted)
        for symbol in sorted(inputs.instruments)
    ]
    claims, unreadable = _claims(inputs.events)
    _drop_identifier_collisions(names)
    _drop_claimed_spans(names, claims)
    for name in names:
        name.date_composite()
        if not name.spans and not any(g.valid_from is None for g in name.gaps):
            detail = {"span_gaps": [g.reason for g in name.gaps]}
            name.gaps.append(Gap(name.symbol, NO_SPAN_SURVIVED, None, None, detail))

    identifiers = tuple(
        sorted((i for n in names for i in n.identifiers), key=lambda i: (i.symbol, i.scheme))
    )
    spans = tuple(
        sorted((s for n in names for s in n.spans), key=lambda s: (s.symbol, s.valid_from))
    )
    gaps = tuple(
        sorted(
            (g for n in names for g in n.gaps),
            key=lambda g: (g.symbol, g.valid_from or date.min, g.reason),
        )
    )
    unread = tuple(sorted(unreadable))
    return Proposal(
        identifiers, spans, gaps, unread, proposal_digest(identifiers, spans, gaps, unread)
    )
