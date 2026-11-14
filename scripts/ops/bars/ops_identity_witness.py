"""Identity witness for gap-list spans (design section 8c, todo 600 step 7): read-only.

Per gap-list span clipped to [2003-09-10, archive end), and per candidate ticker (the name's own
symbol, its map tickers, the tickers in the gap row's detail), Massive's 1d day files under that
ticker are compared with the IBKR 1d raw stored for the instrument (``ibkr``/``smart_trades``).
IBKR's stored raw is used once here as evidence, before its deletion; it is never a source of
canonical. Massive's close is divided by the frozen market split scale of its session (the
selection helpers), then:

- return agreement: consecutive matched sessions, ``|r_M - r_I| <= tau(c_t)/c_t + tau(c_t-1)/c_t-1``
  with ``tau(p) = WITNESS_INCREMENT / 2 + 1e-4 * p``;
- level: the per-session ``ln(c_M / c_I)`` has an interquartile range at most
  ``WITNESS_LEVEL_IQR`` and a median within ``WITNESS_LEVEL_TOL`` of zero.

``placed`` needs ``WITNESS_MIN_PAIRS`` pairs, ``WITNESS_RETURN_SHARE`` agreement and the level
test; one placing candidate per span, two is ``ambiguous``. Agreement proves the same ticker tape,
not the same security (8c amendment), so a span is placed only with security continuity read from
the captured references (``continuity``): the name's own list_date on or before the span start and
no predecessor marker inside the span. ``--calibrate`` runs the declared two-direction calibration.
The constants are pre-registered in the design table (section 8c), not APR parameters.

Documentary rule (default, 8c amendment 2026-11-14; ``--rule legacy`` keeps the rule above):
a ticker is placed on a span by documentary identity, not by the IBKR tape. Its captured Massive
reference record must carry the name's CIK and share-class FIGI (a missing FIGI passes, but the
ticker never takes a session the name's own ticker also carries, so a sibling share class places
on none; a unit, warrant or right never places; another issuer's record, a record with no CIK or no record never passes; a same-CIK
shell's delisting day, not list_date, bounds the name's tape). Placement is coverage-aware:
only the sessions the day files carry under that ticker, inside its documented tenure, are placed,
so a rename splits a span at the first and last file day of each ticker, not at an event date.
IBKR agreement stays corroboration; only a measured disagreement holds a placement.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import json
import math
import statistics
import sys
from collections import Counter, defaultdict
from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

project_root = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(project_root))

import psycopg  # noqa: E402

from scripts.ops.bars.ops_massive_policy_plan import (  # noqa: E402
    DEFAULT_MANIFEST,
    archive_end_of,
)
from services.bar_selection import read_split_rows  # noqa: E402
from src.config.settings import get_settings  # noqa: E402
from src.intelligence.bars.split_rescale import scales_for_sessions, splits_known_at  # noqa: E402
from src.intelligence.bars.ticker_entity_map import MASSIVE_ARCHIVE_START  # noqa: E402

#: the 8a identity gate (8c amendment after the first calibration): the decision rule
IDENTITY_MIN_CORRELATION = 0.9
IDENTITY_MIN_RETURNS = 20
IDENTITY_SPLIT_LOG_RETURN = math.log(1.5)
SPLIT_LIKE_TOL = 0.005
SPLIT_LIKE_RATIOS = tuple(sorted({float(n) for n in range(2, 21)} | {1.5, 2.5, 3.5, 4 / 3, 5 / 3}))
#: evidence only since that amendment (the first calibration's decision rule)
WITNESS_MIN_PAIRS = 100
WITNESS_RETURN_SHARE = 0.99
WITNESS_INCREMENT = 0.01
WITNESS_LEVEL_IQR = 0.005
WITNESS_LEVEL_TOL = 0.01
PRICE_REL_TOL = 1e-4
OUT_OF_SCOPE = "asset_class_outside_vendor"
PLACED, THIN, AMBIGUOUS = "placed", "thin", "ambiguous"
RETURNS_DISAGREE, LEVEL_UNEXPLAINED = "returns_disagree", "level_unexplained"
PREDECESSOR, MARKER, MISSING = (
    "predecessor_history",
    "predecessor_marker",
    "identity_evidence_missing",
)
MIXED_IDENTITY_REASONS = frozenset(
    {"ticker_claimed_by_other_security", "event_chain_head_mismatch"}
)
#: documentary rule decisions (8c amendment 2026-11-14)
IDENTITY_NO_REFERENCE = "identity_no_reference"
IDENTITY_OTHER_ISSUER = "identity_other_issuer"
IDENTITY_REUSE_UNDATED = "identity_reuse_undated"
NON_EQUITY_SECURITY = "non_equity_security_type"
NO_FILE_COVERAGE = "no_file_coverage"
CORROBORATION_CONFLICT = "corroboration_conflict"
AMBIGUOUS_SESSIONS = "ambiguous_sessions"
LOST_CONTESTED = "lost_contested_sessions"
AGREES, DISAGREES, UNCLEAR = "agrees", "disagrees", "unclear"
ADMISSIBLE = "admissible"
EVIDENCE_OWN, EVIDENCE_FIGI_SAME, EVIDENCE_FIGI_ABSENT = (
    "own_record",
    "cik_and_share_class_figi_same",
    "cik_same_figi_absent",
)
ACTIVE_SOURCE = "overview_active"
#: Massive security types that are never a name's tape (a blank-check shell's units, warrants, rights)
NON_EQUITY_TYPES = frozenset({"UNIT", "WARRANT", "RIGHT"})
#: flag only, never a gate: a calendar-day gap in a placed ticker's file tenure beyond which the
#: ticker reads as reused (a continuously listed ticker is never absent for a full week)
TENURE_GAP_DAYS = 7
TENURE_UNCAPTURED = "tenure_uncaptured"
CALIBRATION_LIST_BEFORE = date(1995, 1, 1)
CALIBRATION_SIZE = 10
DEFAULT_DAY_DIR = project_root / "data/massive/files/day_aggs_v1"

_IBKR_SQL = """
SELECT ("timestamp" AT TIME ZONE 'UTC')::date, close FROM ohlcv_raw
WHERE symbol = %s AND timeframe = '1d' AND vendor = 'ibkr' AND kind = 'smart_trades'
  AND "timestamp" >= %s AND "timestamp" < %s AND close > 0
"""
_OVERVIEW_SQL = """
SELECT DISTINCT ON (request_key) split_part(request_key, '@', 1),
       body->'results'->>'list_date'
FROM reference_raw WHERE vendor = 'massive' AND endpoint = 'overview' AND request_key LIKE '%%@active'
ORDER BY request_key, served_at DESC
"""
_EVENTS_SQL = """
SELECT DISTINCT ON (request_key) split_part(request_key, '@', 1), body->'results'
FROM reference_raw WHERE vendor = 'massive' AND endpoint = 'events' AND request_key LIKE '%%@active'
ORDER BY request_key, served_at DESC
"""
_DELISTED_SQL = """
SELECT r->>'ticker', r->>'composite_figi', r->>'delisted_utc'
FROM reference_raw, jsonb_array_elements(body->'results') AS r
WHERE vendor = 'massive' AND endpoint = 'tickers_delisted'
"""
_ISSUER_OVERVIEW_SQL = """
SELECT DISTINCT ON (request_key) split_part(request_key, '@', 1), split_part(request_key, '@', 2),
       body->'results'->>'cik', body->'results'->>'share_class_figi',
       body->'results'->>'type'
FROM reference_raw WHERE vendor = 'massive' AND endpoint = 'overview'
ORDER BY request_key, served_at DESC
"""
_ISSUER_DELISTED_SQL = """
SELECT DISTINCT r->>'ticker', r->>'cik', r->>'share_class_figi', r->>'type', r->>'delisted_utc'
FROM reference_raw, jsonb_array_elements(body->'results') AS r
WHERE vendor = 'massive' AND endpoint = 'tickers_delisted'
"""
_MAP_TICKERS_SQL = """
SELECT symbol, ticker FROM ticker_event_current WHERE vendor = 'massive' AND retired_at IS NULL
"""


@dataclass(frozen=True)
class Span:
    symbol: str
    reason: str
    start: date
    end: date
    candidates: tuple[str, ...]


@dataclass(frozen=True)
class Witness:
    symbol: str
    span_start: date
    span_end: date
    candidate: str
    matched: int
    pairs: int
    agreeing: int
    return_share: float
    correlation: float
    level_median: float
    level_iqr: float
    n_splits: int
    decision: str


@dataclass(frozen=True)
class IssuerRecord:
    """One captured Massive reference record of a ticker (an overview answer or a delisted row):
    the issuer it names and, when dated, the day the ticker was given up."""

    ticker: str
    cik: str
    share_class_figi: str
    security_type: str
    gone: date | None
    source: str


@dataclass(frozen=True)
class References:
    """The captured facts security continuity and documentary identity read (8c amendments)."""

    list_date: Mapping[str, date]  # by symbol
    figi: Mapping[str, str]  # composite FIGI by symbol
    events: Mapping[str, Sequence[tuple[date, str]]]  # the FIGI's ticker_change events
    delisted: Mapping[str, Sequence[tuple[str | None, date | None]]]  # by ticker: (figi, date)
    issuers: Mapping[str, Sequence[IssuerRecord]] = field(default_factory=dict)  # by ticker


def continuity(refs: References, symbol: str, reason: str, start: date, end: date,
               candidate: str) -> str | None:  # fmt: skip
    """The gap decision security continuity forces on a span and candidate, or None when the
    references allow placement (8c amendment order: listing, then markers)."""
    listed = refs.list_date.get(symbol)
    if listed is None:
        return MISSING
    if listed > start:
        return PREDECESSOR
    if reason in MIXED_IDENTITY_REASONS:
        return MARKER
    if any(start < d < end for d, _ in refs.events.get(symbol, ())):
        return MARKER
    own = refs.figi.get(symbol)
    for figi, gone in refs.delisted.get(candidate, ()):
        if figi != own and (gone is None or gone > start):
            return MARKER
    return None


def _tau(price: float) -> float:
    return WITNESS_INCREMENT / 2 + PRICE_REL_TOL * price


def split_sized(r: float) -> bool:
    """A split-sized log return (8a identity gate): above ln 1.5, or a split ratio's factor."""
    a = abs(r)
    return a > IDENTITY_SPLIT_LOG_RETURN or any(
        abs(math.exp(a) / ratio - 1.0) <= SPLIT_LIKE_TOL for ratio in SPLIT_LIKE_RATIOS
    )


def identity_correlation(r_m: Sequence[float], r_i: Sequence[float]) -> float:
    """The 8a identity correlation of paired returns, split-sized ones dropped on either arm;
    NaN under ``IDENTITY_MIN_RETURNS`` (thin); a flat side correlates 0, both flat and equal 1."""
    kept = [(a, b) for a, b in zip(r_m, r_i, strict=True) if not (split_sized(a) or split_sized(b))]
    if len(kept) < IDENTITY_MIN_RETURNS:
        return math.nan
    xs, ys = [a for a, _ in kept], [b for _, b in kept]
    sx, sy = statistics.pstdev(xs), statistics.pstdev(ys)
    if sx == 0 or sy == 0:
        return 1.0 if sx == sy == 0 and xs == ys else 0.0
    return statistics.correlation(xs, ys)


def judge(
    massive: Mapping[date, float], ibkr: Mapping[date, float], scales: Mapping[date, float]
) -> tuple[int, int, int, float, float, float, str]:
    """(matched, pairs, agreeing, correlation, level median, level IQR, decision) of one
    candidate series. ``massive`` is the raw close by session, ``scales`` its frozen split scale
    by session. The decision reads the identity correlation and the level (8c amendment); the
    pair agreement is evidence."""
    m_days, i_days = sorted(massive), sorted(ibkr)
    m_prev = dict(zip(m_days[1:], m_days, strict=False))
    i_prev = dict(zip(i_days[1:], i_days, strict=False))
    matched = sorted(set(massive) & set(ibkr))
    adj = {d: massive[d] / scales.get(d, 1.0) for d in matched}
    pairs = agreeing = 0
    returns_m: list[float] = []
    returns_i: list[float] = []
    for day in matched:
        before = m_prev.get(day)
        if before is None or before != i_prev.get(day) or before not in adj:
            continue
        pairs += 1
        r_m = math.log(adj[day] / adj[before])
        r_i = math.log(ibkr[day] / ibkr[before])
        tol = _tau(ibkr[day]) / ibkr[day] + _tau(ibkr[before]) / ibkr[before]
        agreeing += abs(r_m - r_i) <= tol
        returns_m.append(r_m)
        returns_i.append(r_i)
    correlation = identity_correlation(returns_m, returns_i)
    levels = [math.log(adj[d] / ibkr[d]) for d in matched if adj[d] > 0]
    if len(levels) >= 4:
        q1, median, q3 = statistics.quantiles(levels, n=4)
        iqr = q3 - q1
    else:
        median, iqr = (statistics.median(levels) if levels else math.nan), math.nan
    if math.isnan(correlation):
        decision = THIN
    elif correlation < IDENTITY_MIN_CORRELATION:
        decision = RETURNS_DISAGREE
    elif not (iqr <= WITNESS_LEVEL_IQR and abs(median) <= WITNESS_LEVEL_TOL):
        decision = LEVEL_UNEXPLAINED
    else:
        decision = PLACED
    return len(matched), pairs, agreeing, correlation, median, iqr, decision


def span_decision(decisions: Sequence[str]) -> str:
    """One span's decision over its candidates: one placing candidate places it, two are
    ambiguous; otherwise the most informative failure (identity first, then returns, level,
    thin)."""
    placed = decisions.count(PLACED)
    if placed == 1:
        return PLACED
    if placed > 1:
        return AMBIGUOUS
    for decision in (PREDECESSOR, MISSING, MARKER, RETURNS_DISAGREE, LEVEL_UNEXPLAINED, THIN):
        if decision in decisions:
            return decision
    return THIN


# ---- documentary rule (8c amendment 2026-11-14): pure helpers ----


def issuer_match(current: IssuerRecord, record: IssuerRecord) -> str | None:
    """The evidence label when ``record`` names the same issuer as the name's current record, else
    None. Same CIK is necessary; the share-class FIGI must agree when both carry one, and a
    missing FIGI passes; a record with no CIK, another CIK or another security type never does
    (never by name similarity)."""
    if record == current:
        return EVIDENCE_OWN
    if not current.cik or record.cik != current.cik:
        return None
    if (
        current.security_type
        and record.security_type
        and current.security_type != record.security_type
    ):
        return None
    ours, theirs = current.share_class_figi, record.share_class_figi
    if ours and theirs:
        return EVIDENCE_FIGI_SAME if ours == theirs else None
    return EVIDENCE_FIGI_ABSENT


@dataclass(frozen=True)
class Tenure:
    """What the references say about one ticker for one name: the evidence label (or the
    rejection), and the documented window ``(lower, upper)`` the name held the ticker in: strictly
    after the last day of another issuer's record, strictly before the name's own last day (None is
    open). ``reused`` marks a ticker whose records name more than one issuer."""

    evidence: str | None
    reject: str | None
    lower: date | None = None
    upper: date | None = None
    reused: bool = False


def documentary_tenure(
    current: IssuerRecord,
    records: Sequence[IssuerRecord],
) -> Tenure:
    """The documentary identity of a ticker's captured records against the name's current record.
    No record, or only other issuers', rejects. The window ends at the latest delisting date of
    the name's own records (open when one is undated) and starts at the latest delisting date of
    another issuer's record that precedes it. The active overview is the latest holder, so
    another issuer's dated record precedes it; an undated record of the name's own, or of another
    issuer, cannot be placed in time against a dated one, so it rejects (it cannot be excluded)."""
    matches = [(issuer_match(current, r), r) for r in records]
    same = [(label, r) for label, r in matches if label]
    other = [r for label, r in matches if not label]
    if not records:
        return Tenure(None, IDENTITY_NO_REFERENCE)
    if not same:
        return Tenure(None, IDENTITY_OTHER_ISSUER)
    if any(r.gone is None for r in other):
        return Tenure(None, IDENTITY_REUSE_UNDATED)
    open_own = [r for _, r in same if r.gone is None]
    if (
        open_own
        and not any(r.source == ACTIVE_SOURCE for r in open_own)
        and any(r.gone for r in other)
    ):
        return Tenure(None, IDENTITY_REUSE_UNDATED)  # an undated own row cannot be ordered
    own_ends = [r.gone for _, r in same]
    upper = None if None in own_ends else max(d for d in own_ends if d)
    lower = max(
        (r.gone for r in other if r.gone and (upper is None or r.gone < upper)), default=None
    )
    labels = {label for label, _ in same}
    evidence = next(
        label
        for label in (EVIDENCE_OWN, EVIDENCE_FIGI_SAME, EVIDENCE_FIGI_ABSENT)
        if label in labels
    )
    reused = len({r.cik for r in records if r.cik}) > 1
    return Tenure(evidence, None, lower, upper, reused)


def contested_sessions(claims: Mapping[str, Sequence[date]]) -> dict[date, tuple[str, ...]]:
    """The sessions two or more admissible tickers both claim, with the claimants. One security
    trades under one ticker a session, so a documentary pass cannot place both: a class of
    shares, a when-issued line or another issuer's reused ticker sits behind each such session."""
    by_day: dict[date, list[str]] = defaultdict(list)
    for ticker, days in sorted(claims.items()):
        for day in days:
            by_day[day].append(ticker)
    return {d: tuple(ts) for d, ts in sorted(by_day.items()) if len(ts) > 1}


def settle_sessions(
    claims: Mapping[str, Sequence[date]],
    verdicts: Mapping[str, str],
    no_win: Collection[str] = (),
) -> tuple[dict[str, tuple[date, ...]], dict[str, tuple[date, ...]], set[str]]:
    """(assigned, dropped, lost) after the contested sessions are settled. ``verdicts`` is what
    the independent witness says of each claimant's tape over its contested sessions (``AGREES``,
    ``DISAGREES``, anything else is unclear). A claimant the witness contradicts is out; a
    contested session goes to the one claimant left, or when several are left to the one that
    agrees; the other claimants are ``lost`` (a ticker shown not to be the name's tape is placed
    nowhere in the span). With no one left the session goes to no one. A claimant in ``no_win`` (a
    same-CIK ticker with no share-class FIGI) never takes a contested session, by default or by
    agreeing, while a claimant outside ``no_win`` is not contradicted: a sibling class that trades
    beside the name is placed on none of the sessions they share. When the witness contradicts the
    name's own tape (another issuer's reused ticker), the predecessor is the one left and wins."""
    contested = contested_sessions(claims)
    won: dict[date, str] = {}
    lost: set[str] = set()
    for day, claimants in contested.items():
        left = [t for t in claimants if verdicts.get(t) != DISAGREES]
        winners = left if len(left) == 1 else [t for t in left if verdicts.get(t) == AGREES]
        if any(t not in no_win for t in left):  # a sibling is barred while the name is not
            winners = [t for t in winners if t not in no_win]  # contradicted; else it may win
        if len(winners) == 1:
            won[day] = winners[0]
            lost |= set(claimants) - set(winners)
    assigned: dict[str, set[date]] = defaultdict(set)
    dropped: dict[str, set[date]] = defaultdict(set)
    for ticker, days in claims.items():
        for day in days:
            if ticker in lost or (day in contested and won.get(day) != ticker):
                dropped[ticker].add(day)
            else:
                assigned[ticker].add(day)
    return (
        {t: tuple(sorted(d)) for t, d in sorted(assigned.items()) if d},
        {t: tuple(sorted(d)) for t, d in sorted(dropped.items()) if d},
        lost,
    )


def placement_runs(
    assigned: Mapping[str, Sequence[date]], dropped: Mapping[str, Sequence[date]]
) -> list[tuple[str, date, date, int]]:
    """(ticker, first, last + 1 day, sessions) runs: consecutive claimed sessions of one ticker.
    A session another ticker owns or that was dropped ends a run, so the ranges of one name never
    overlap and never cover a session withheld from placement."""
    owner: dict[date, str | None] = {d: None for ds in dropped.values() for d in ds}
    owner.update({d: t for t, ds in assigned.items() for d in ds})
    runs: list[list[Any]] = []
    for day in sorted(owner):
        t = owner[day]
        if t is not None and runs and runs[-1][0] == t:
            runs[-1][2] = day
            runs[-1][3] += 1
        else:
            runs.append([t, day, day, 1])
    return [(t, a, b + timedelta(days=1), n) for t, a, b, n in runs if t is not None]


@dataclass(frozen=True)
class Candidate:
    ticker: str
    decision: str  # ADMISSIBLE, or the reason the ticker is not placed
    evidence: str
    file_sessions: int  # sessions the day files carry under the ticker inside the span
    admissible: tuple[date, ...]  # those inside the ticker's documented tenure
    lead_read: str = ""  # TENURE_UNCAPTURED when the ticker reads as reused with no captured end


def candidate_tickers(
    symbol: str,
    current: IssuerRecord | None,
    named: Iterable[str],
    issuers: Mapping[str, Sequence[IssuerRecord]],
) -> tuple[str, ...]:
    """The name's own symbol, the tickers the map and the gap row name, and every ticker whose
    captured records document the same issuer (the predecessors the map never named)."""
    found = {symbol, *named}
    if current is not None:
        found |= {t for t, rs in issuers.items() if any(issuer_match(current, r) for r in rs)}
    return tuple(sorted(found))


def shell_delisting(
    symbol: str, current: IssuerRecord | None, issuers: Mapping[str, Sequence[IssuerRecord]]
) -> date | None:
    """The day a blank-check shell of the name's CIK was delisted, or None. The shell is a
    same-CIK common-stock ticker that has a same-CIK unit, warrant or right ticker named after it
    (the ticker starts with the shell's); its earliest dated delisting is the combination. A
    renamed predecessor with unrelated rights or warrants is not a shell. The name's ``list_date``
    can be the shell's IPO, so its tape from the shell era is another business's and the lower
    bound of the name's tape is this day, not list_date."""
    if current is None or not current.cik:
        return None
    records = [r for t, rs in issuers.items() if t != symbol for r in rs if r.cik == current.cik]
    derivative = {r.ticker for r in records if r.security_type in NON_EQUITY_TYPES}
    return min(
        (
            r.gone
            for r in records
            if r.gone
            and r.security_type == "CS"
            and any(t != r.ticker and t.startswith(r.ticker) for t in derivative)
        ),
        default=None,
    )


def _tape_gap(days: Sequence[date]) -> bool:
    return any((b - a).days > TENURE_GAP_DAYS for a, b in zip(days, days[1:], strict=False))


def place_span(
    refs: References, span: Span, sessions: Mapping[str, Sequence[date]]
) -> tuple[list[Candidate], dict[str, tuple[date, ...]]]:
    """Documentary placement of one span: (candidates, the sessions each admissible ticker claims).
    ``sessions`` holds the day-file sessions per ticker. Every candidate also needs the name's
    captured listing date on or before the session (the 8c listing guard: a blank-check shell's or
    another security's tape before the name listed is not the name's history, even when the CIK
    carries over) and, when a same-CIK shell exists, strictly after the shell's delisting day; a
    ticker with a unit, warrant or right record never places; a same-CIK ticker with no share-class
    FIGI never takes a session the name's own ticker also carries (``settle_sessions`` ``no_win``,
    so a sibling share class places on none of them, a renamed predecessor on all of its own); and
    the name's own ticker needs a gap reason that does not itself record mixed identity."""
    current = next(
        (r for r in refs.issuers.get(span.symbol, ()) if r.source == ACTIVE_SOURCE), None
    )
    listed = refs.list_date.get(span.symbol)
    shell = shell_delisting(span.symbol, current, refs.issuers)
    cik = current.cik if current else ""
    candidates: list[Candidate] = []
    claims: dict[str, tuple[date, ...]] = {}
    for ticker in candidate_tickers(span.symbol, current, span.candidates, refs.issuers):
        inside = tuple(d for d in sessions.get(ticker, ()) if span.start <= d < span.end)
        own = ticker == span.symbol
        records = refs.issuers.get(ticker, ())
        tenure = documentary_tenure(current, records) if current else None
        reject = (
            MISSING
            if tenure is None or listed is None
            else (
                NON_EQUITY_SECURITY
                if any(r.security_type in NON_EQUITY_TYPES and r.cik == cik for r in records)
                else tenure.reject
                or (MARKER if own and span.reason in MIXED_IDENTITY_REASONS else None)
            )
        )
        if reject or tenure is None:
            candidates.append(Candidate(ticker, reject or MISSING, "", len(inside), ()))
            continue
        window = tuple(
            d
            for d in inside
            if (listed is None or d >= listed)
            and (shell is None or d > shell)
            and (tenure.lower is None or d > tenure.lower)
            and (tenure.upper is None or d < tenure.upper)
        )
        evidence = tenure.evidence or ""
        reused = tenure.reused or _tape_gap(window)
        candidates.append(
            Candidate(
                ticker, ADMISSIBLE if window else NO_FILE_COVERAGE, evidence, len(inside), window,
                TENURE_UNCAPTURED if reused and tenure.lower is None else "",
            )
        )  # fmt: skip
        if window:
            claims[ticker] = window
    return candidates, claims


def _detail_tickers(detail: str) -> set[str]:
    """Tickers a gap row's detail names: its events chain, head and first-event ticker."""
    try:
        data = json.loads(detail) if detail else {}
    except json.JSONDecodeError:
        return set()
    out = {t for _, t in data.get("chain", []) if isinstance(t, str)}
    for key in ("head", "ticker", "first_ticker"):
        if isinstance(data.get(key), str):
            out.add(data[key])
    return out


def read_spans(path: Path, archive_end: date, map_tickers: Mapping[str, set[str]]) -> list[Span]:
    spans = []
    with path.open(newline="") as handle:
        for r in csv.DictReader(handle):
            if r["reason"] == OUT_OF_SCOPE:
                continue
            start = max(
                date.fromisoformat(r["valid_from"]) if r["valid_from"] else MASSIVE_ARCHIVE_START,
                MASSIVE_ARCHIVE_START,
            )
            end = min(
                date.fromisoformat(r["valid_to"]) if r["valid_to"] else archive_end, archive_end
            )
            if start >= end:
                continue
            names = (
                {r["symbol"]}
                | map_tickers.get(r["symbol"], set())
                | _detail_tickers(r.get("detail", ""))
            )
            spans.append(Span(r["symbol"], r["reason"], start, end, tuple(sorted(names))))
    return spans


def read_day_files(
    day_dir: Path, tickers: set[str], start: date, end: date
) -> dict[str, dict[date, float]]:
    """Massive's 1d close per ticker and session over [start, end), from the day files."""
    out: dict[str, dict[date, float]] = defaultdict(dict)
    day = start
    while day < end:
        path = day_dir / f"{day:%Y/%m/%Y-%m-%d}.csv.gz"
        if path.is_file():
            with gzip.open(path, "rt", newline="") as handle:
                header = handle.readline().rstrip("\n").split(",")
                if header[0] != "ticker":
                    raise ValueError(f"{path}: the first column is {header[0]!r}, not 'ticker'")
                close_at = header.index("close")
                for line in handle:
                    if line.partition(",")[0] in tickers:
                        row = line.rstrip("\n").split(",")
                        if float(row[close_at]) > 0:
                            out[row[0]][day] = float(row[close_at])
        day += timedelta(days=1)
    return out


def _day(text: str | None) -> date | None:
    try:
        return date.fromisoformat(text[:10]) if text else None
    except ValueError:  # the overview's 'active' tail
        return None


def read_issuer_records(conn: Any) -> dict[str, tuple[IssuerRecord, ...]]:
    """Every captured overview answer (``TICKER@active`` or ``TICKER@<delisting date>``) and
    delisted row, by ticker: the issuer each names (8c amendment 2026-11-14)."""
    found: dict[str, set[IssuerRecord]] = defaultdict(set)
    for ticker, tail, cik, scf, kind in conn.execute(_ISSUER_OVERVIEW_SQL).fetchall():
        source = ACTIVE_SOURCE if tail == "active" else "overview_dated"
        if cik or scf or kind:  # an empty answer names no issuer: absent, not another's
            found[ticker].add(
                IssuerRecord(ticker, cik or "", scf or "", kind or "", _day(tail), source)
            )
    for ticker, cik, scf, kind, gone in conn.execute(_ISSUER_DELISTED_SQL).fetchall():
        found[ticker].add(
            IssuerRecord(ticker, cik or "", scf or "", kind or "", _day(gone), "delisted")
        )
    return {t: tuple(sorted(rs, key=repr)) for t, rs in found.items()}


def read_references(conn: Any) -> References:
    list_date = {
        sym: date.fromisoformat(d) for sym, d in conn.execute(_OVERVIEW_SQL).fetchall() if d
    }
    figi: dict[str, str] = {}
    events: dict[str, list[tuple[date, str]]] = {}
    for sym, body in conn.execute(_EVENTS_SQL).fetchall():
        body = body or {}
        if body.get("composite_figi"):
            figi[sym] = body["composite_figi"]
        events[sym] = [
            (date.fromisoformat(e["date"]), (e.get("ticker_change") or {}).get("ticker", ""))
            for e in body.get("events") or ()
            if e.get("type") == "ticker_change" and e.get("date")
        ]
    delisted: dict[str, list[tuple[str | None, date | None]]] = defaultdict(list)
    for ticker, f, gone in conn.execute(_DELISTED_SQL).fetchall():
        delisted[ticker].append((f, date.fromisoformat(gone[:10]) if gone else None))
    return References(list_date, figi, events, dict(delisted), read_issuer_records(conn))


def calibration_spans(
    gap_spans: Sequence[Span], refs: References, predecessors: Sequence[Mapping[str, Any]],
    map_tickers: Mapping[str, set[str]], ibkr_sessions: Mapping[str, int],
) -> tuple[list[Span], list[Span]]:  # fmt: skip
    """(must not place, must place), the 8c amendment's two calibration sets, the second by the
    rule fixed before any result: before_first_event from 2003-09-10, list_date before 1995, a
    chain of only its own symbol, no delisted row of another FIGI, at least
    ``WITNESS_MIN_PAIRS`` IBKR sessions in the span and a candidate ticker in the captured events
    chain (the second amendment); the first 10 by symbol."""
    negative = [
        Span(
            p["symbol"],
            "predecessor_check",
            date.fromisoformat(p["first"]),
            date.fromisoformat(p["last"]) + timedelta(days=1),
            tuple(sorted({p["symbol"]} | map_tickers.get(p["symbol"], set()))),
        )
        for p in predecessors
    ]
    positive = [
        s
        for s in sorted(gap_spans, key=lambda s: s.symbol)
        if s.reason == "before_first_event"
        and s.start == MASSIVE_ARCHIVE_START
        and (refs.list_date.get(s.symbol) or date.max) < CALIBRATION_LIST_BEFORE
        and {t for _, t in refs.events.get(s.symbol, ())} <= {s.symbol}
        and all(f == refs.figi.get(s.symbol) for f, _ in refs.delisted.get(s.symbol, ()))
        and ibkr_sessions.get(s.symbol, 0) >= WITNESS_MIN_PAIRS
        and bool(set(s.candidates) & {t for _, t in refs.events.get(s.symbol, ())})
    ][:CALIBRATION_SIZE]
    return negative, positive


def evaluate(
    conn: Any, spans: Sequence[Span], refs: References, closes: Mapping[str, Mapping[date, float]]
) -> tuple[list[Witness], list[dict[str, Any]]]:
    now = datetime.now(UTC)
    rows: list[Witness] = []
    span_rows: list[dict[str, Any]] = []
    with conn.cursor() as cur:
        for s in spans:
            lo = datetime(s.start.year, s.start.month, s.start.day, tzinfo=UTC)
            hi = datetime(s.end.year, s.end.month, s.end.day, tzinfo=UTC)
            cur.execute(_IBKR_SQL, (s.symbol, lo, hi))
            ibkr = {d: float(c) for d, c in cur.fetchall()}
            splits = splits_known_at(read_split_rows(cur, s.symbol), now)
            decisions, placing = [], []
            for ticker in s.candidates:
                massive = {d: c for d, c in closes.get(ticker, {}).items() if s.start <= d < s.end}
                matched, pairs, agreeing, corr, median, iqr, decision = judge(
                    massive, ibkr, scales_for_sessions(massive, splits)
                )
                gate = continuity(refs, s.symbol, s.reason, s.start, s.end, ticker)
                decision = gate or decision
                decisions.append(decision)
                if decision == PLACED:
                    placing.append(ticker)
                rows.append(Witness(s.symbol, s.start, s.end, ticker, matched, pairs, agreeing,
                                    agreeing / pairs if pairs else math.nan, corr, median, iqr,
                                    len(splits), decision))  # fmt: skip
            span_rows.append(
                {
                    "symbol": s.symbol,
                    "reason": s.reason,
                    "span_start": s.start.isoformat(),
                    "span_end": s.end.isoformat(),
                    "list_date": _iso(refs.list_date.get(s.symbol)),
                    "ibkr_sessions": len(ibkr),
                    "decision": span_decision(decisions),
                    "placing_ticker": placing[0] if len(placing) == 1 else "",
                }
            )
    return rows, span_rows


EVIDENCE_OWN_PRE_EVENT = "own_record_pre_event"


def own_run_evidence(refs: References, symbol: str, first: date, evidence: str) -> str:
    """The evidence label of an own-ticker run: ``own_record_pre_event`` when it starts before the
    first captured ``ticker_change`` event that gave the name that ticker. The placement stands
    (boundaries follow the day files, lead ruling 2), but the run rests on the list_date clip
    alone, not on a reference record of its own, so the lead's read sees it labelled."""
    events = [d for d, ticker in refs.events.get(symbol, ()) if ticker == symbol]
    return EVIDENCE_OWN_PRE_EVENT if events and first < min(events) else evidence


def corroboration_label(verdict: str, median: float) -> str:
    """The reported corroboration of a placed ticker: ``agrees``, or the ``judge`` verdict, with a
    thin series whose measured level offset exceeds the declared tolerance named, not hidden."""
    if verdict == PLACED:
        return AGREES
    if verdict == THIN and abs(median) > WITNESS_LEVEL_TOL:
        return "thin_level_offset"
    return verdict


#: the span decision of a documentary run when nothing is placed: the most informative failure
_NOT_PLACED_ORDER = (
    MISSING,
    MARKER,
    NON_EQUITY_SECURITY,
    IDENTITY_OTHER_ISSUER,
    IDENTITY_NO_REFERENCE,
    IDENTITY_REUSE_UNDATED,
    CORROBORATION_CONFLICT,
    LOST_CONTESTED,
    AMBIGUOUS_SESSIONS,
    NO_FILE_COVERAGE,
)
PLACED_PARTIAL = "placed_partial"


def tape_verdict(verdict: Sequence[Any]) -> str:
    """What a ``judge`` verdict says of a contested tape: ``DISAGREES`` below the 8a identity
    correlation, ``AGREES`` at it with a stable level (the IQR bound; the offset itself is IBKR's
    adjustment, not tested; a different share class correlates but floats against the name's
    level), else unclear. A thin series (NaN) is unclear."""
    corr, iqr = verdict[3], verdict[5]
    if math.isnan(corr):
        return UNCLEAR
    if corr < IDENTITY_MIN_CORRELATION:
        return DISAGREES
    return AGREES if iqr <= WITNESS_LEVEL_IQR else UNCLEAR


def evaluate_documentary(
    conn: Any,
    spans: Sequence[Span],
    refs: References,
    closes: Mapping[str, Mapping[date, float]],
    as_of: datetime,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """(placements, span rows, candidate rows) of a documentary run. Placement is
    ``place_span``. IBKR is read only to corroborate: it settles a session two documented tickers
    both claim (``tape_verdict`` over that ticker's contested sessions) and a measured
    returns disagreement holds a placed ticker; it never places. The split scales are as of
    ``as_of`` so the output is the same on every run."""
    sessions = {t: sorted(c) for t, c in closes.items()}
    placements: list[dict[str, Any]] = []
    span_rows: list[dict[str, Any]] = []
    cand_rows: list[dict[str, Any]] = []
    with conn.cursor() as cur:
        for s in spans:
            candidates, claims = place_span(refs, s, sessions)
            lo = datetime(s.start.year, s.start.month, s.start.day, tzinfo=UTC)
            hi = datetime(s.end.year, s.end.month, s.end.day, tzinfo=UTC)
            cur.execute(_IBKR_SQL, (s.symbol, lo, hi))
            ibkr = {d: float(c) for d, c in cur.fetchall()}
            splits = splits_known_at(read_split_rows(cur, s.symbol), as_of)

            def corroborate(ticker: str, days: Iterable[date], _ibkr=ibkr, _splits=splits) -> Any:
                massive = {d: closes[ticker][d] for d in days}
                return judge(massive, _ibkr, scales_for_sessions(massive, _splits))

            contested = contested_sessions(claims)
            verdicts = {
                t: tape_verdict(corroborate(t, [d for d, ts in contested.items() if t in ts]))
                for t in sorted({t for ts in contested.values() for t in ts})
            }
            no_win = {
                c.ticker
                for c in candidates
                if c.evidence == EVIDENCE_FIGI_ABSENT and c.ticker != s.symbol
            }
            assigned, dropped, lost = settle_sessions(claims, verdicts, no_win)
            evidence: dict[str, dict[str, Any]] = {}
            for ticker in sorted(assigned):
                matched, pairs, _, corr, median, iqr, verdict = corroborate(
                    ticker, assigned[ticker]
                )
                evidence[ticker] = {
                    "corroboration": corroboration_label(verdict, median),
                    "ibkr_matched": matched, "ibkr_pairs": pairs,
                    "correlation": corr, "level_median": median, "level_iqr": iqr,
                }  # fmt: skip
            held = {t for t, e in evidence.items() if e["corroboration"] == RETURNS_DISAGREE}
            for ticker in held:
                dropped[ticker] = tuple(sorted({*dropped.get(ticker, ()), *assigned.pop(ticker)}))
            placed_days = {d for days in assigned.values() for d in days}
            carried = {
                d for c in candidates for d in sessions.get(c.ticker, ()) if s.start <= d < s.end
            }
            finals: dict[str, str] = {}
            for c in candidates:
                final = finals[c.ticker] = (
                    PLACED if c.ticker in assigned
                    else CORROBORATION_CONFLICT if c.ticker in held
                    else LOST_CONTESTED if c.ticker in lost
                    else AMBIGUOUS_SESSIONS if c.ticker in dropped
                    else c.decision
                )  # fmt: skip
                cand_rows.append(
                    {
                        "symbol": s.symbol, "span_start": s.start.isoformat(),
                        "span_end": s.end.isoformat(), "candidate": c.ticker,
                        "decision": final, "evidence": c.evidence,
                        "file_sessions": c.file_sessions, "admissible_sessions": len(c.admissible),
                        "lead_read": c.lead_read,
                        "placed_sessions": len(assigned.get(c.ticker, ())),
                        "dropped_sessions": len(dropped.get(c.ticker, ())),
                        **{
                            k: evidence.get(c.ticker, {}).get(k, "")
                            for k in ("corroboration", "ibkr_matched", "ibkr_pairs",
                                      "correlation", "level_median", "level_iqr")
                        },
                    }
                )  # fmt: skip
            for ticker, first, last, count in placement_runs(assigned, dropped):
                c = next(c for c in candidates if c.ticker == ticker)
                identity = (
                    own_run_evidence(refs, s.symbol, first, c.evidence)
                    if ticker == s.symbol
                    else c.evidence
                )
                corroboration = evidence[ticker]["corroboration"]
                placements.append(
                    {
                        "symbol": s.symbol, "file_ticker": ticker, "start": first.isoformat(),
                        "end": last.isoformat(), "sessions": count, "reason": s.reason,
                        "documentary_identity": identity, "corroboration": corroboration,
                        "lead_read": "|".join(
                            filter(
                                None,
                                (
                                    # a run on the listing guard alone and not corroborated
                                    "pre_event_not_corroborated"
                                    if identity == EVIDENCE_OWN_PRE_EVENT
                                    and corroboration != AGREES
                                    else "",
                                    c.lead_read,
                                ),
                            )
                        ),
                    }
                )  # fmt: skip
            unplaced = len(carried - placed_days)
            if placed_days:
                decision = PLACED if not unplaced else PLACED_PARTIAL
            else:
                seen = [finals[c.ticker] for c in candidates if c.file_sessions]
                decision = next((d for d in _NOT_PLACED_ORDER if d in seen), NO_FILE_COVERAGE)
            span_rows.append(
                {
                    "symbol": s.symbol, "reason": s.reason, "span_start": s.start.isoformat(),
                    "span_end": s.end.isoformat(), "list_date": _iso(refs.list_date.get(s.symbol)),
                    "decision": decision, "placed_sessions": len(placed_days),
                    "unplaced_file_sessions": unplaced, "placing_tickers": "|".join(sorted(assigned)),
                }
            )  # fmt: skip
    placements.sort(key=lambda r: (r["symbol"], r["start"], r["file_ticker"]))
    return placements, span_rows, cand_rows


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--gap-list", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--day-dir", type=Path, default=DEFAULT_DAY_DIR)
    parser.add_argument(
        "--calibrate",
        type=Path,
        metavar="PREDECESSORS_JSON",
        help="run the 8c calibration only, under --rule: the predecessor names (symbol, first, last) must not "
        "place and the declared long-listed set must",
    )
    parser.add_argument(
        "--rule",
        choices=("documentary", "legacy"),
        default="documentary",
        help="documentary (8c amendment 2026-11-14, default) or the first declared IBKR rule",
    )
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    archive_end = archive_end_of(args.manifest.read_bytes())
    args.out.mkdir(parents=True, exist_ok=True)
    dsn = get_settings().database_url.replace("postgresql+asyncpg://", "postgresql://")
    with psycopg.connect(dsn) as conn:
        conn.read_only = True
        map_tickers: dict[str, set[str]] = defaultdict(set)
        for symbol, ticker in conn.execute(_MAP_TICKERS_SQL).fetchall():
            map_tickers[symbol].add(ticker)
        refs = read_references(conn)
        spans = read_spans(args.gap_list, archive_end, map_tickers)
        sets: dict[str, list[Span]] = {"spans": spans}
        if args.calibrate:
            sessions = {s.symbol: _ibkr_sessions(conn, s) for s in spans}
            negative, positive = calibration_spans(
                spans, refs, json.loads(args.calibrate.read_text()), map_tickers, sessions
            )
            sets = {"must_not_place": negative, "must_place": positive}
        if args.rule == "documentary":
            return _run_documentary(conn, sets, refs, args, archive_end)
        every = [s for group in sets.values() for s in group]
        print(f"{len(every)} spans; reading day files", flush=True)
        closes = read_day_files(
            args.day_dir,
            {t for s in every for t in s.candidates},
            min(s.start for s in every),
            max(s.end for s in every),
        )
        results = {name: evaluate(conn, group, refs, closes) for name, group in sets.items()}
    summary: dict[str, Any] = {
        "archive_end": archive_end.isoformat(),
        "gap_list": str(args.gap_list),
    }
    for name, (rows, span_rows) in results.items():
        _write(args.out / f"identity_witness_{name}_candidates.csv", [asdict(w) for w in rows])
        _write(args.out / f"identity_witness_{name}.csv", span_rows)
        summary[name] = {
            "spans": len(span_rows),
            "decisions": dict(Counter(r["decision"] for r in span_rows)),
        }
    if args.calibrate:
        must_not = results["must_not_place"][1]
        must = results["must_place"][1]
        summary["calibration"] = {
            "must_not_place_ok": all(r["decision"] != PLACED for r in must_not),
            "must_place_ok": len(must) == CALIBRATION_SIZE
            and all(r["decision"] == PLACED for r in must),
            "must_place_symbols": [r["symbol"] for r in must],
        }
    (args.out / "identity_witness_summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))
    return 0


def _run_documentary(
    conn: Any,
    sets: Mapping[str, Sequence[Span]],
    refs: References,
    args: argparse.Namespace,
    archive_end: date,
) -> int:
    every = [s for group in sets.values() for s in group]
    tickers: set[str] = set()
    for s in every:
        current = next(
            (r for r in refs.issuers.get(s.symbol, ()) if r.source == ACTIVE_SOURCE), None
        )
        tickers |= set(candidate_tickers(s.symbol, current, s.candidates, refs.issuers))
    print(f"{len(every)} spans, {len(tickers)} tickers; reading day files", flush=True)
    closes = read_day_files(
        args.day_dir, tickers, min(s.start for s in every), max(s.end for s in every)
    )
    as_of = datetime(archive_end.year, archive_end.month, archive_end.day, tzinfo=UTC)
    summary: dict[str, Any] = {
        "archive_end": archive_end.isoformat(),
        "gap_list": str(args.gap_list),
        "rule": "documentary",
    }
    span_rows_by_set: dict[str, list[dict[str, Any]]] = {}
    for name, group in sets.items():
        placements, span_rows, cand_rows = evaluate_documentary(conn, group, refs, closes, as_of)
        base = "documentary" if name == "spans" else f"documentary_{name}"
        _write(args.out / f"{base}_placements.csv", placements)
        _write(args.out / f"{base}_spans.csv", span_rows)
        _write(args.out / f"{base}_candidates.csv", cand_rows)
        span_rows_by_set[name] = span_rows
        summary[name] = {
            "spans": len(span_rows),
            "decisions": dict(sorted(Counter(r["decision"] for r in span_rows).items())),
            "placements": len(placements),
            "placed_sessions": sum(r["sessions"] for r in placements),
            "unplaced_file_sessions": sum(r["unplaced_file_sessions"] for r in span_rows),
        }
    if args.calibrate:
        must_not, must = span_rows_by_set["must_not_place"], span_rows_by_set["must_place"]
        summary["calibration"] = {
            "must_not_place_ok": all(r["placed_sessions"] == 0 for r in must_not),
            "must_place_ok": len(must) == CALIBRATION_SIZE
            and all(r["decision"] in (PLACED, PLACED_PARTIAL) for r in must),
            "must_place_symbols": [r["symbol"] for r in must],
        }
    (args.out / "documentary_summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))
    return 0


def _ibkr_sessions(conn: Any, span: Span) -> int:
    lo = datetime(span.start.year, span.start.month, span.start.day, tzinfo=UTC)
    hi = datetime(span.end.year, span.end.month, span.end.day, tzinfo=UTC)
    return len(conn.execute(_IBKR_SQL, (span.symbol, lo, hi)).fetchall())


def _iso(day: date | None) -> str | None:
    return day.isoformat() if day else None


def _write(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    rows = list(rows)
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, list(rows[0]) if rows else ["symbol"], lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    sys.exit(main())
