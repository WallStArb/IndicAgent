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
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass
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
class References:
    """The captured facts security continuity reads (8c amendment)."""

    list_date: Mapping[str, date]  # by symbol
    figi: Mapping[str, str]  # composite FIGI by symbol
    events: Mapping[str, Sequence[tuple[date, str]]]  # the FIGI's ticker_change events
    delisted: Mapping[str, Sequence[tuple[str | None, date | None]]]  # by ticker: (figi, date)


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
                for row in csv.DictReader(handle):
                    if row["ticker"] in tickers and float(row["close"]) > 0:
                        out[row["ticker"]][day] = float(row["close"])
        day += timedelta(days=1)
    return out


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
    return References(list_date, figi, events, dict(delisted))


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


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--gap-list", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--day-dir", type=Path, default=DEFAULT_DAY_DIR)
    parser.add_argument(
        "--calibrate",
        type=Path,
        metavar="PREDECESSORS_JSON",
        help="run the 8c calibration only: the predecessor names (symbol, first, last) must not "
        "place and the declared long-listed set must",
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
