"""Massive admission step 4: split reconciliation and the seam detector (todo 600).

Admission design section 5 (docs/plans/2026-11-10-massive-admission-db-design.md): before any
Massive raw load, (1) reconcile Massive's two captured splits families against corporate_action
for every active instrument, and (2) scan the Massive day archive for close steps no recorded
split explains, judged by level over spans (the todo 592 rule). Read-only: nothing is written to
the database. Outputs land in --out (default data/massive_split_audit/<capture date>/, git-ignored):

- reconciliation.csv: the complete partition (split_reconciliation.OUTCOMES) of every attributed
  Massive event and every corporate_action_current split row of an active instrument, each with
  the Massive tape reading (level_seams.tape_reading) as the vendor-internal witness;
- attribution_excluded.csv: Massive events on an active string attributed elsewhere
  (reused_elsewhere, predates_entity) and the family conflicts;
- proposed_rows.csv: the massive_only events the tape confirms, as corporate_action rows
  (inferred_by massive_reference, recorded_at = the capture's served_at), the input of
  ops_split_calendar_audit --apply-massive; review_rows.csv: the massive_only events it does not;
- disagreement_ledger.csv: every date_offset, ratio_disagree, ours_only and tape-contradicted
  case with its witnesses, in the design's precedence order (section 8a amendment);
- seams_active.csv: every level step of every active instrument's stitched Massive series,
  classified and ranked; seams_strings.csv: the same over every ticker string in the archive;
- canonical_witness.csv: canonical 1d against Massive (adjusted by the recorded splits) at every
  lone canonical break of a 592 sweep CSV (--sweep-csv) and at the named 592 cases; and
  level_census.csv: every active instrument's canonical 1d spans whose level sits off Massive's;
- summary.json: counts, parameters, input digests.

The archive is untrusted input: it is only read, through src/intelligence/bars/massive_flat.py,
and this script is run as `python -I` from the repo root (never from inside data/).

Identity (input preparation; the pure functions take it as data): an active instrument's series is
stitched from its Massive events chain (the X@active events answer: each later ticker_change
opens a span of that string until the next) and starts at the overview list date. The head
event's date is not a start: it is floored at the archive start, and some heads date an uplisting
or a reorganisation of a string that traded before (OKE's only event is 2026-09-11), so the head
span reaches back to the list date. A chain whose latest string is not the instrument's symbol is
inconsistent and falls back to the symbol's own string from the list date. The ticker_event table
(step 3b, another lane) supersedes this preparation once it is populated.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import sys
import time
from bisect import bisect_left, bisect_right
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import date, datetime
from fractions import Fraction
from functools import cache
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

project_root = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(project_root))

import numpy as np  # noqa: E402
import polars as pl  # noqa: E402
import psycopg  # noqa: E402

# Owned by the writer: its split-continuity key, its same-event window (a pair here is a pair
# there, and a proposed row is never one its guard skips), and the splits endpoints it may cite.
from scripts.ops.bars.ops_split_calendar_audit import (  # noqa: E402
    MASSIVE_SPLITS_ENDPOINTS,
    PROPOSED_COLUMNS,
    REL_TOL_KEY,
    SAME_EVENT_DAYS,
    SPIN_OFF_EXCLUSIONS,
    listed_spin_off,
    operator_list,
)
from scripts.ops.bars.ops_split_detect import SPLIT_RULE_KEYS, split_rule_from_apr  # noqa: E402
from src.config.settings import Settings  # noqa: E402
from src.intelligence.bars.corporate_actions import (  # noqa: E402
    is_market_split,
    recognised_split_ratio,
)
from src.intelligence.bars.level_seams import (  # noqa: E402
    SEAM_CLASSES,
    RecordedFactor,
    SeamParams,
    classify_step,
    find_level_steps,
    incumbent_reading,
    junction_levels,
    span_verdict,
    tape_reading,
)
from src.intelligence.bars.massive_flat import file_trading_date, read_day_file  # noqa: E402
from src.intelligence.bars.sessions import nyse_sessions  # noqa: E402
from src.intelligence.bars.split_reconciliation import (  # noqa: E402
    BULK,
    OWN_ATTRIBUTIONS,
    V3,
    IdentityIndex,
    ReconciledSplit,
    ReconcileParams,
    RecordedSplit,
    StringSpan,
    VendorSplit,
    attribute,
    collapse_vendor_duplicates,
    merge_split_families,
    partition_counts,
    proposal_status,
    reconcile,
)
from src.intelligence.bars.split_rescale import SplitFactor, scales_for_sessions  # noqa: E402

DAY_ARCHIVE = project_root / "data" / "massive" / "files" / "day_aggs_v1"
DEFAULT_OUT = project_root / "data" / "massive_split_audit"
MASSIVE = "massive"
OURS = "corporate_action"
# Execution dates are New York session dates, so a serve time is read on New York's calendar.
SESSION_ZONE = ZoneInfo("America/New_York")
# The endpoint labels of the two captured families (reference_raw.endpoint), the writer's own list.
_FAMILY_OF_ENDPOINT = dict(zip(MASSIVE_SPLITS_ENDPOINTS, (V3, BULK), strict=True))

# The detector's definitional cuts (level_seams.SeamParams; recorded in summary.json). A 5:4
# split steps ln 1.25 = 0.223, the smallest common forward ratio, so the junction cut sits just
# under it; stock dividends (x1.05) are below any detectable step and rest on the endpoint and the
# tape reading. Ten sessions a side is two trading weeks of level. A recorded split explains a
# step within five sessions (the todo 516 vendor-offset class is one to three). One week missing
# is a halt; three months missing before a step means the string may have changed hands. The
# 592 sweep's one-bar reversal tolerance (0.1) is reused.
JUNCTION_CUT = 0.2
TRANSIENT_TOL = 0.1
LEVEL_SESSIONS = 10
EXPLAIN_SESSIONS = 5
HALT_GAP = 5
MAX_HALT_GAP = 60
THIN_VOLUME = 1000.0
# A session on which more distinct strings step unexplained than this is market-wide (the 592
# sweep's lone-break cap, 20 names of ~1,500, scaled to the archive's ~8,000 strings).
MARKET_DAY_STRINGS = 100
# Canonical against Massive: a span level off by more than this (log) is off (592 sweep scale
# tolerance); an off run shorter than LEVEL_SESSIONS is a print, not a span.
LEVEL_TOL = 0.1
# Ratio terms for the ranking's simplicity, the smaller term of p/q in lowest terms (the APR
# split-ratio rule's smaller term reaches 4; a bound of 50 covers both orientations).
SIMPLICITY_DENOMINATOR = 50
# The named todo 592 cases (the brief's sanity list): (symbol, date, what 592 says).
NAMED_CASES: tuple[tuple[str, str, str], ...] = (
    ("OKE", "2005-04-12", "587 quarantine vs sweep rescale x1.985 (ruling 6, held)"),
    ("OKE", "2012-06-01", "landed inseries rescale x0.504"),
    ("OKE", "2015-12-31", "landed junction rescale x2.836 (an earlier row voided)"),
    ("NEXN", "2025-02-14", "587 quarantine vs junction rescale x2.0 (ruling 6, held)"),
    ("INSM", "2000-07-28", "calendar 0.25 vs measured 0.199 (held, a witness decides)"),
    ("TMUS", "2015-10-27", "hole span 2013-04-30..2015-10-27 (held)"),
    ("HSIC", "2013-03-12", "single tape, 1.53x (held)"),
    ("OVV", "2009-12-03", "single tape, 1.96x, Encana spin-off era (held)"),
    ("XPO", "2021-07-30", "spin-off suspect 1.718 calendar (no rescale)"),
    ("GSAT", "2021-02-08", "landed unrecorded split x0.610; D7 red known-accepted"),
    ("MVBF", "2014-04-02", "split unconfirmed pending a Massive witness"),
    ("BHP", "2001-07-12", "spin-off suspect (no rescale)"),
    ("F", "2000-08-02", "spin-off suspect (no rescale)"),
)

_APR_SQL = "SELECT config_key, config_value FROM config_state WHERE config_key = ANY(%s)"
_ACTIVE_SQL = "SELECT symbol FROM instruments WHERE is_active ORDER BY symbol"
_SPLITS_SQL = """
SELECT reference_raw_id::text, endpoint, served_at, body
FROM reference_raw_current
WHERE vendor = 'massive' AND endpoint = ANY(%s)
ORDER BY endpoint, page
"""
_EVENTS_SQL = """
SELECT split_part(request_key, '@', 1), body FROM reference_raw_current
WHERE vendor = 'massive' AND endpoint = 'events' AND request_key LIKE '%%@active'
"""
_OVERVIEW_SQL = """
SELECT split_part(request_key, '@', 1), body->'results'->>'list_date' FROM reference_raw_current
WHERE vendor = 'massive' AND endpoint = 'overview' AND request_key LIKE '%%@active'
  AND body->>'status' = 'OK'
"""
_DELISTED_SQL = """
SELECT x->>'ticker', (x->>'delisted_utc')::date
FROM reference_raw_current r, jsonb_array_elements(r.body->'results') x
WHERE r.vendor = 'massive' AND r.endpoint = 'tickers_delisted' AND x ? 'delisted_utc'
"""
_ACTIONS_SQL = """
SELECT action_id::text, symbol, action_type, effective_date, factor, inferred_by,
       detail ? 'rows_file' AS operator_rows_file, current
FROM (
    SELECT c.*, EXISTS (SELECT 1 FROM corporate_action_current k
                        WHERE k.action_id = c.action_id) AS current
    FROM corporate_action c
) a
ORDER BY symbol, effective_date
"""
_CANONICAL_COPY = """
COPY (
    SELECT symbol, ("timestamp" AT TIME ZONE 'UTC')::date AS d, close
    FROM market_data_ohlcv_tradeable
    WHERE timeframe = '1d' AND close > 0 AND "timestamp" >= '{start}'::date
) TO STDOUT (FORMAT csv)
"""


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ---------------------------------------------------------------- inputs


@dataclass(frozen=True)
class Reference:
    """Everything the audit reads from the database, once."""

    active: frozenset[str]
    splits: list[VendorSplit]
    conflicts: list[Any]
    served_at: dict[str, datetime]  # reference_raw_id -> served_at
    chains: dict[str, list[tuple[date, str]]]  # active symbol -> ascending (start, string)
    list_dates: dict[str, date]
    delisted: dict[str, list[date]]  # string -> delisting dates
    actions: list[tuple]  # every corporate_action row (current or not), _ACTIONS_SQL order
    apr: dict[str, Any]


def load_reference(conn: Any) -> Reference:
    active = frozenset(r[0] for r in conn.execute(_ACTIVE_SQL))
    rows, served = [], {}
    pages = Counter()
    for raw_id, endpoint, served_at, body in conn.execute(
        _SPLITS_SQL, (list(_FAMILY_OF_ENDPOINT),)
    ):
        if body.get("status") != "OK":
            raise ValueError(f"splits page {raw_id} ({endpoint}) answered {body.get('status')!r}")
        served[raw_id] = served_at
        pages[endpoint] += 1
        rows.extend((_FAMILY_OF_ENDPOINT[endpoint], raw_id, r) for r in body["results"])
    if set(pages) != set(_FAMILY_OF_ENDPOINT):
        raise ValueError(f"both splits families are required, found {dict(pages)}")
    splits, conflicts = merge_split_families(rows)
    chains: dict[str, list[tuple[date, str]]] = {}
    for symbol, body in conn.execute(_EVENTS_SQL):
        if body.get("status") != "OK" or symbol not in active:
            continue
        events = (body.get("results") or {}).get("events") or []
        chain = sorted(
            (date.fromisoformat(e["date"]), e["ticker_change"]["ticker"])
            for e in events
            if e.get("type") == "ticker_change" and (e.get("ticker_change") or {}).get("ticker")
        )
        if chain:
            chains[symbol] = chain
    list_dates = {
        s: date.fromisoformat(d) for s, d in conn.execute(_OVERVIEW_SQL) if d and s in active
    }
    delisted: dict[str, list[date]] = defaultdict(list)
    for ticker, day in conn.execute(_DELISTED_SQL):
        delisted[ticker].append(day)
    actions = list(conn.execute(_ACTIONS_SQL))
    apr = dict(conn.execute(_APR_SQL, ([*SPLIT_RULE_KEYS, REL_TOL_KEY],)).fetchall())
    return Reference(
        active, splits, conflicts, served, chains, list_dates, dict(delisted), actions, apr
    )


def load_archive(root: Path) -> tuple[list[date], pl.DataFrame, dict[str, Any]]:
    """Every day file through the committed reader: (sessions, frame, digest). The frame holds
    (ticker, s, close, volume) sorted by (ticker, s), s the session ordinal."""
    files = sorted(root.rglob("*.csv.gz"))
    if not files:
        raise ValueError(f"no day files under {root}")
    days = [file_trading_date(f) for f in files]
    if len(set(days)) != len(days):
        raise ValueError("two day files for one session")
    order = sorted(range(len(files)), key=lambda i: days[i])
    sessions = [days[i] for i in order]
    frames, rows = [], 0
    digest = hashlib.sha256()
    for ordinal, i in enumerate(order):
        bars = read_day_file(files[i])
        rows += len(bars)
        digest.update(f"{files[i].relative_to(root)}:{files[i].stat().st_size}\n".encode())
        frames.append(
            pl.DataFrame(
                {
                    "ticker": bars.tickers[bars.ticker_index].astype(str),
                    "s": np.full(len(bars), ordinal, dtype=np.int32),
                    "close": bars.close,
                    "volume": bars.volume.astype(np.float64),
                }
            )
        )
    frame = pl.concat(frames).sort(["ticker", "s"])
    expected = sorted(nyse_sessions(sessions[0], sessions[-1]))
    if expected != sessions:
        missing = sorted(set(expected) - set(sessions))[:5]
        extra = sorted(set(sessions) - set(expected))[:5]
        raise ValueError(f"archive sessions are not the NYSE calendar: missing {missing} {extra}")
    info = {"files": len(files), "rows": rows, "listing_sha256": digest.hexdigest()}
    return sessions, frame, info


# ---------------------------------------------------------------- identity


@dataclass(frozen=True)
class Identity:
    """An active instrument's string spans (dates, half-open) and how its chain read."""

    spans: tuple[StringSpan, ...]
    chain: str  # consistent, inconsistent, absent

    def ordinals(self, sessions: Sequence[date]) -> list[tuple[str, int, int]]:
        """(string, first ordinal, end ordinal) per span, empty spans left out."""
        out = []
        for span in self.spans:
            lo = bisect_left(sessions, span.valid_from)
            hi = len(sessions) if span.valid_to is None else bisect_left(sessions, span.valid_to)
            if lo < hi:
                out.append((span.string, lo, hi))
        return out


def build_identity(
    symbol: str, chain: Sequence[tuple[date, str]] | None, list_date: date | None
) -> Identity:
    floor = list_date or date.min
    if chain and chain[-1][1] == symbol:
        spans = []
        for i, (start, string) in enumerate(chain):
            stop = chain[i + 1][0] if i + 1 < len(chain) else None
            lo = floor if i == 0 else max(start, floor)
            if stop is None or lo < stop:
                spans.append(StringSpan(symbol, string, lo, stop))
        return Identity(tuple(spans), "consistent")
    status = "inconsistent" if chain else "absent"
    return Identity((StringSpan(symbol, symbol, floor, None),), status)


def string_breaks(
    ref: Reference, identities: Mapping[str, Identity], sessions: Sequence[date]
) -> dict[str, set[int]]:
    """Per ticker string, the ordinals at which it may have changed hands: an active security
    starting or leaving it (its span edges, the head at the list date) and the string's
    delistings (a delisting breaks the session after it)."""
    breaks: dict[str, set[int]] = defaultdict(set)
    for ident in identities.values():
        for string, lo, hi in ident.ordinals(sessions):
            breaks[string].update((lo, hi))
    for string, days in ref.delisted.items():
        for day in days:
            breaks[string].add(bisect_right(sessions, day))
    return breaks


# ---------------------------------------------------------------- series


@dataclass
class Series:
    key: str  # an active symbol, or a ticker string
    s: np.ndarray
    close: np.ndarray
    volume: np.ndarray
    strings: np.ndarray | None = None  # per observation, for a stitched series


def string_series(frame: pl.DataFrame) -> dict[str, Series]:
    """Per ticker string, zero-copy views of the (ticker, s)-sorted frame."""
    tickers = frame["ticker"].to_numpy()
    s, close, volume = (frame[c].to_numpy() for c in ("s", "close", "volume"))
    starts = np.flatnonzero(np.r_[True, tickers[1:] != tickers[:-1]])
    ends = np.r_[starts[1:], len(tickers)]
    return {
        str(tickers[a]): Series(str(tickers[a]), s[a:b], close[a:b], volume[a:b])
        for a, b in zip(starts, ends, strict=True)
    }


def stitched_series(
    symbol: str, spans: Sequence[tuple[str, int, int]], strings: Mapping[str, Series]
) -> Series | None:
    parts = []
    for string, lo, hi in spans:
        series = strings.get(string)
        if series is None:
            continue
        a, b = np.searchsorted(series.s, lo), np.searchsorted(series.s, hi)
        if a < b:
            parts.append((string, series.s[a:b], series.close[a:b], series.volume[a:b]))
    if not parts:
        return None
    parts.sort(key=lambda p: p[1][0])
    return Series(
        symbol,
        np.concatenate([p[1] for p in parts]),
        np.concatenate([p[2] for p in parts]),
        np.concatenate([p[3] for p in parts]),
        np.concatenate([np.full(len(p[1]), p[0], dtype=object) for p in parts]),
    )


# ---------------------------------------------------------------- the audit


def first_new_ordinal(day: date, sessions: Sequence[date], *, inclusive: bool) -> int:
    """The first session on the new scale: the execution date (inclusive) or the session after
    an effective date (exclusive)."""
    return bisect_left(sessions, day) if inclusive else bisect_right(sessions, day)


def vendor_factor(split: VendorSplit, sessions: Sequence[date]) -> RecordedFactor:
    """A vendor split as the detector reads it: its new scale starts on the execution date."""
    o = first_new_ordinal(split.execution_date, sessions, inclusive=True)
    return RecordedFactor(o, split.factor, MASSIVE, split.event_id)


def ours_factor(row: RecordedSplit, sessions: Sequence[date]) -> RecordedFactor:
    """A corporate_action split as the detector reads it: its new scale starts after the
    effective date (the last old-scale session, migration 400)."""
    o = first_new_ordinal(row.effective_date, sessions, inclusive=False)
    return RecordedFactor(o, row.factor, OURS, row.action_id)


def seam_params(apr: Mapping[str, Any]) -> SeamParams:
    return SeamParams(
        junction_cut=JUNCTION_CUT,
        transient_tol=TRANSIENT_TOL,
        level_sessions=LEVEL_SESSIONS,
        explain_sessions=EXPLAIN_SESSIONS,
        halt_gap=HALT_GAP,
        max_halt_gap=MAX_HALT_GAP,
        thin_volume=THIN_VOLUME,
        rel_tol=float(apr[REL_TOL_KEY]),
        ratio_rule=split_rule_from_apr(apr),
    )


def _bounded(factors: Sequence[RecordedFactor], ordinal: int) -> tuple[int, int]:
    """The neighbouring recorded splits' first new-scale sessions around one at `ordinal`."""
    others = sorted({f.first_new_session for f in factors} - {ordinal})
    i = bisect_left(others, ordinal)
    return (others[i - 1] if i else -1, others[i] if i < len(others) else 1 << 30)


def tape_of(
    series: Series | None,
    ordinal: int,
    factor: float,
    factors: Sequence[RecordedFactor],
    params: SeamParams,
) -> tuple[str, float | None]:
    if series is None:
        return "no_tape", None
    return tape_reading(series.s, series.close, ordinal, factor, _bounded(factors, ordinal), params)


def classify_series(
    series: Series,
    factors: Sequence[RecordedFactor],
    breaks: Iterable[int],
    params: SeamParams,
    sessions: Sequence[date],
) -> tuple[list[dict[str, Any]], int]:
    steps, printed = find_level_steps(series.s, series.close, series.volume, params)
    ordered_breaks = sorted(breaks)
    rows = []
    for step in steps:
        verdict = classify_step(step, factors, ordered_breaks, params)
        row = {
            "series": series.key,
            "date": sessions[step.session].isoformat(),
            "prev_date": sessions[step.prev_session].isoformat(),
            **{k: v for k, v in vars(step).items() if k not in ("session", "prev_session")},
            **vars(verdict),
        }
        if series.strings is not None:
            row["string_before"] = series.strings[step.position - 1]
            row["string_after"] = series.strings[step.position]
        rows.append(row)
    return rows, printed


def incumbent_cols(
    row: Mapping[str, Any],
    incumbent: tuple[np.ndarray, np.ndarray] | None,
    sessions: Sequence[date],
    params: SeamParams,
) -> dict[str, Any]:
    """The incumbent's level step at a seam's junction and its reading (unexplained seams only;
    an explained seam needs no witness, and a suspect one is judged on identity first)."""
    if row["seam_class"] != "unexplained":
        return {}
    levels = (
        None
        if incumbent is None
        else junction_levels(
            incumbent[0],
            incumbent[1],
            bisect_left(sessions, date.fromisoformat(row["date"])),
            params.level_sessions,
        )
    )
    if levels is None:
        return {"incumbent": "no_incumbent"}
    step = levels[1] - levels[0]
    reading, ratio = incumbent_reading(
        row["level_step"], step, params.ratio_rule, params.rel_tol, LEVEL_TOL
    )
    return {
        "incumbent": reading,
        "incumbent_level_step": round(step, 6),
        "incumbent_implied_ratio": ratio,
    }


@cache
def _smaller_term(ratio: float) -> int:
    terms = Fraction(ratio).limit_denominator(SIMPLICITY_DENOMINATOR)
    return min(terms.numerator, terms.denominator)


def rank_key(row: Mapping[str, Any]) -> tuple:
    """Unexplained first, those the incumbent contradicts (flat where the vendor steps) first
    among them; within a class, off market days, share volume moving by the implied
    ratio (a split multiplies the share count), the simpler implied ratio, an instant step (the
    junction carries the whole level step, where a real move drifts), the larger step."""
    order = {"unexplained": 0, "identity_suspect": 1, "thin_halted": 2, "explained": 3}
    witness = {"incumbent_flat": 0, "incumbent_other": 1, "no_incumbent": 2, "incumbent_moves": 3}
    ratio = row.get("incumbent_implied_ratio") or row.get("implied_ratio")
    size = _smaller_term(ratio) if ratio else 99
    return (
        order[row["seam_class"]],
        witness.get(row.get("incumbent", ""), 2),
        bool(row.get("market_day")),
        row.get("volume_agrees") is not True,
        size,
        round(abs(row["junction_step"] - row["level_step"]), 2),
        -abs(row["level_step"]),
        row["series"],
        row["date"],
    )


def write_csv(path: Path, rows: Sequence[Mapping[str, Any]], fieldnames: Sequence[str]) -> None:
    with path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(fieldnames), extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {k: (";".join(v) if isinstance(v, tuple) else v) for k, v in row.items()}
            )


def _fields(rows: Sequence[Mapping[str, Any]]) -> list[str]:
    seen: dict[str, None] = {}
    for row in rows:
        seen.update(dict.fromkeys(row))
    return list(seen)


# ---------------------------------------------------------------- canonical witness


def load_canonical(conn: Any, sessions: Sequence[date]) -> dict[str, tuple[np.ndarray, np.ndarray]]:
    """Canonical tradeable 1d closes per symbol as (session ordinals, closes), archive sessions
    only (a canonical date off the archive calendar has no Massive counterpart)."""
    buf = io.BytesIO()
    with conn.cursor() as cur, cur.copy(_CANONICAL_COPY.format(start=sessions[0])) as cp:
        for chunk in cp:
            buf.write(chunk)
    buf.seek(0)
    frame = pl.read_csv(
        buf,
        has_header=False,
        new_columns=["symbol", "d", "close"],
        schema_overrides={"symbol": pl.Utf8, "d": pl.Date, "close": pl.Float64},
    ).sort(["symbol", "d"])
    axis = np.array(sessions, dtype="datetime64[D]")
    days = frame["d"].to_numpy().astype("datetime64[D]")
    ords = np.searchsorted(axis, days)
    exact = (ords < len(axis)) & (axis[np.minimum(ords, len(axis) - 1)] == days)
    symbols, closes = frame["symbol"].to_numpy()[exact], frame["close"].to_numpy()[exact]
    ords = ords[exact]
    starts = np.flatnonzero(np.r_[True, symbols[1:] != symbols[:-1]]) if len(symbols) else []
    ends = np.r_[starts[1:], len(symbols)] if len(symbols) else []
    return {str(symbols[a]): (ords[a:b], closes[a:b]) for a, b in zip(starts, ends, strict=True)}


def adjusted_close(
    series: Series, factors: Sequence[RecordedFactor], sessions: Sequence[date]
) -> np.ndarray:
    """Massive closes on today's scale through selection's own arithmetic
    (split_rescale.scales_for_sessions): a split whose new scale starts at ordinal o has its last
    old-scale session at o - 1; one whose new scale starts at the archive's first session divides
    no archived bar."""
    splits = [
        SplitFactor(sessions[f.first_new_session - 1], f.factor)
        for f in factors
        if f.first_new_session > 0
    ]
    days = [sessions[o] for o in series.s.tolist()]
    scales = scales_for_sessions(days, splits)
    return series.close / np.array([scales[d] for d in days])


def log_k(
    canonical: tuple[np.ndarray, np.ndarray], massive: tuple[Series, np.ndarray]
) -> tuple[np.ndarray, np.ndarray]:
    """(ordinals, ln(canonical / Massive-adjusted)) over the sessions both carry."""
    c_ords, c_close = canonical
    series, adjusted = massive
    common, ci, mi = np.intersect1d(c_ords, series.s, assume_unique=True, return_indices=True)
    return common, np.log(c_close[ci] / adjusted[mi])


def witness_rows(
    cases: Sequence[tuple[str, date, str]],
    canonical: Mapping[str, tuple[np.ndarray, np.ndarray]],
    massive: Mapping[str, tuple[Series, np.ndarray]],
    sessions: Sequence[date],
    k: int,
) -> list[dict[str, Any]]:
    """Canonical 1d against Massive-adjusted at each (symbol, break date), by span level."""
    out = []
    ratios: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    for symbol, day, note in cases:
        row: dict[str, Any] = {"symbol": symbol, "date": day.isoformat(), "note": note}
        if day < sessions[0]:
            out.append({**row, "verdict": "before_archive"})
            continue
        if symbol not in canonical or symbol not in massive:
            why = "no canonical 1d" if symbol not in canonical else "no Massive series"
            out.append({**row, "verdict": "no_witness", "why": why})
            continue
        if symbol not in ratios:
            ratios[symbol] = log_k(canonical[symbol], massive[symbol])
        ords, logk = ratios[symbol]
        levels = junction_levels(ords, logk, bisect_left(sessions, day), k)
        if levels is None:
            first = sessions[int(massive[symbol][0].s[0])]
            why = (
                f"before the instrument's Massive series starts ({first}: list date or rename)"
                if day <= first
                else "a side has no session common to canonical and Massive"
            )
            out.append({**row, "verdict": "no_witness", "why": why})
            continue
        before, after = levels
        out.append(
            {
                **row,
                "verdict": span_verdict(before, after, LEVEL_TOL),
                "log_k_before": round(before, 6),
                "log_k_after": round(after, 6),
                "implied_factor_before": round(math.exp(before), 6),
                "implied_factor_after": round(math.exp(after), 6),
            }
        )
    return out


def level_census(
    canonical: Mapping[str, tuple[np.ndarray, np.ndarray]],
    massive: Mapping[str, tuple[Series, np.ndarray]],
    sessions: Sequence[date],
    k: int,
) -> list[dict[str, Any]]:
    """Every run of at least k common sessions where canonical 1d sits more than LEVEL_TOL (log)
    off Massive-adjusted, per active instrument (the 592 level check)."""
    out = []
    for symbol in sorted(set(canonical) & set(massive)):
        ords, logk = log_k(canonical[symbol], massive[symbol])
        off = np.abs(logk) > LEVEL_TOL
        edges = np.flatnonzero(np.diff(np.r_[0, off.astype(np.int8), 0]))
        for a, b in zip(edges[::2], edges[1::2], strict=True):
            if b - a >= k:
                med = float(np.median(logk[a:b]))
                out.append(
                    {
                        "symbol": symbol,
                        "first": sessions[int(ords[a])].isoformat(),
                        "last": sessions[int(ords[b - 1])].isoformat(),
                        "sessions": int(b - a),
                        "median_log_k": round(med, 6),
                        "implied_factor": round(math.exp(med), 6),
                    }
                )
    return out


# ---------------------------------------------------------------- main


def run(settings: Settings, out_root: Path, sweep_csv: Path | None, archive: Path) -> dict:
    t0 = time.monotonic()
    with psycopg.connect(settings.database_url) as conn:
        ref = load_reference(conn)
        print(f"reference: {len(ref.splits)} events, {len(ref.conflicts)} family conflicts")
        sessions, frame, archive_info = load_archive(archive)
        print(f"archive: {archive_info['files']} files, {archive_info['rows']} rows")
        canonical = load_canonical(conn, sessions)
    params = seam_params(ref.apr)
    capture = max(ref.served_at.values())
    capture_date = capture.date()
    out = out_root / capture_date.isoformat()
    out.mkdir(parents=True, exist_ok=True)

    identities = {
        s: build_identity(s, ref.chains.get(s), ref.list_dates.get(s)) for s in sorted(ref.active)
    }
    index = IdentityIndex.build(
        (span for ident in identities.values() for span in ident.spans),
        {s: ref.list_dates.get(s) for s in ref.active},
    )

    # (1) Attribution and reconciliation.
    own, excluded = [], []
    for split in ref.splits:
        hit = attribute(split, index)
        if hit is None:
            continue
        symbol, how = hit
        (own if how in OWN_ATTRIBUTIONS else excluded).append((split, symbol, how))
    own, duplicates = collapse_vendor_duplicates(own, SAME_EVENT_DAYS)
    # The market-split meaning selection and the daily rule apply (corporate_actions).
    recorded = [
        RecordedSplit(
            aid, sym, eff, float(fac), by, not is_market_split(by, operator_rows_file=rows_file)
        )
        for aid, sym, kind, eff, fac, by, rows_file, current in ref.actions
        if current and kind != "void" and sym in ref.active
    ]
    calendar = sorted(nyse_sessions(date(1970, 1, 2), max(capture_date, sessions[-1])))
    served_on = {i: t.astimezone(SESSION_ZONE).date() for i, t in ref.served_at.items()}

    def executed(split: VendorSplit) -> bool:
        """Executed by the time a page that served it was served (else an announcement)."""
        return split.execution_date <= max(served_on[e] for e in split.evidence)

    rparams = ReconcileParams(
        ratio_rel_tol=float(ref.apr["infra.backfill.split_ratio_rel_tol"]),
        same_event_days=SAME_EVENT_DAYS,
        served_on=served_on,
        archive_start=sessions[0],
        sessions=calendar,
    )
    members = reconcile(own, recorded, rparams)

    # (2) Series and recorded factors.
    strings = string_series(frame)
    del frame
    # Recorded factors: per active instrument (its own Massive events, after the duplicate
    # collapse, and our split facts), and per ticker string for the all-strings scan (every
    # Massive label, one factor per (session, ratio) since the vendor serves some splits twice).
    massive_factors: dict[str, list[RecordedFactor]] = defaultdict(list)
    for split, symbol, _how in own:
        if executed(split):
            massive_factors[symbol].append(vendor_factor(split, sessions))
    ours_factors: dict[str, list[RecordedFactor]] = defaultdict(list)
    for row in recorded:
        if not row.vendor_correction:
            ours_factors[row.symbol].append(ours_factor(row, sessions))
    by_string: dict[str, dict[tuple[int, float], RecordedFactor]] = defaultdict(dict)
    for split in ref.splits:
        if executed(split):
            f = vendor_factor(split, sessions)
            for string in {split.bulk_ticker, split.v3_ticker} - {None}:
                by_string[string].setdefault((f.first_new_session, f.factor), f)
    for symbol, factors in ours_factors.items():
        for f in factors:
            by_string[symbol].setdefault((f.first_new_session, f.factor), f)
    string_factors = {string: list(fs.values()) for string, fs in by_string.items()}
    stitched = {
        s: series
        for s, ident in identities.items()
        if (series := stitched_series(s, ident.ordinals(sessions), strings)) is not None
    }

    # (3) Tape readings for the reconciliation members.
    rec_rows = []
    for m in members:
        series = stitched.get(m.symbol)
        mf = massive_factors.get(m.symbol, [])
        row = reconciled_row(m)
        if m.vendor is not None and m.outcome not in ("announced", "before_archive"):
            o = first_new_ordinal(m.vendor.execution_date, sessions, inclusive=True)
            row["tape"], row["tape_level_step"] = tape_of(series, o, m.vendor.factor, mf, params)
        elif m.ours is not None and m.ours.effective_date >= sessions[0]:
            o = ours_factor(m.ours, sessions).first_new_session
            row["tape"], row["tape_level_step"] = tape_of(series, o, m.ours.factor, mf, params)
        else:
            row["tape"], row["tape_level_step"] = "no_tape", None
        rec_rows.append(row)
    member_rows = list(zip(members, rec_rows, strict=True))
    rec_rows = sorted(rec_rows, key=lambda r: (r["symbol"], r["date"] or "", r["outcome"]))
    write_csv(out / "reconciliation.csv", rec_rows, _fields(rec_rows))
    excl_rows = (
        [
            {**vendor_cols(split), "symbol": symbol, "attribution": how}
            for split, symbol, how in excluded
        ]
        + [
            {
                "symbol": "",
                "attribution": "family_conflict",
                "event_id": c.event_id,
                "readings": json.dumps([[f, t, d.isoformat(), x] for f, t, d, x in c.readings]),
            }
            for c in ref.conflicts
        ]
        + [
            {
                "symbol": d.symbol,
                "attribution": "vendor_duplicate" if d.kept else "vendor_internal_conflict",
                "event_id": d.kept or "",
                "readings": json.dumps(
                    [[i, day.isoformat(), f] for i, (day, f) in zip(d.ids, d.readings, strict=True)]
                ),
            }
            for d in duplicates
        ]
    )
    write_csv(out / "attribution_excluded.csv", excl_rows, _fields(excl_rows))

    # (4) Proposed rows and the review list.
    guard = defaultdict(list)  # the writer's existing-row guard reads every row, current or not
    for _aid, sym, kind, eff, _fac, by, _vc, _current in ref.actions:
        guard[sym].append((eff, kind, by))
    spin_offs = operator_list(SPIN_OFF_EXCLUSIONS)
    proposed, review = [], []
    for m, row in member_rows:
        if m.outcome != "massive_only":
            continue
        assert m.vendor is not None and m.vendor_effective_date is not None
        line = proposed_line(m, ref.served_at, row)
        near = [
            g
            for g in guard.get(m.symbol, [])
            if abs((g[0] - m.vendor_effective_date).days) <= rparams.same_event_days
        ]
        line["guard_skip"] = ";".join(f"{e}:{k}:{b}" for e, k, b in near)
        status = proposal_status(m, row["tape"], params.ratio_rule)
        if status == "proposed" and listed_spin_off(m.symbol, m.vendor.execution_date, spin_offs):
            # The vendor serves some spin-offs as splits (SNX 2020-12-01, Concentrix).
            status = "excluded_spin_off"
        elif status == "proposed" and near:
            # The writer's existing-row guard would skip it: a lead ruling, never a silent skip.
            status = "writer_guard"
        line["status"] = status
        if status == "proposed":
            # The exact ratio the writer re-judges (a vendor 1.333 is 4/3).
            line["factor"] = recognised_split_ratio(m.vendor.factor, params.ratio_rule)
        (proposed if status == "proposed" else review).append(line)
    write_csv(out / "proposed_rows.csv", proposed, PROPOSED_COLUMNS)
    write_csv(out / "review_rows.csv", review, PROPOSED_COLUMNS)

    # (5) Seams: every string, then every active instrument's stitched series, the latter read
    # against canonical 1d (the incumbent) at each junction.
    canonical_logs = {symbol: (o, np.log(c)) for symbol, (o, c) in canonical.items()}
    breaks = string_breaks(ref, identities, sessions)
    seam_rows_all, printed_all = [], 0
    for key, series in strings.items():
        rows, printed = classify_series(
            series, string_factors.get(key, []), breaks.get(key, ()), params, sessions
        )
        seam_rows_all.extend(rows)
        printed_all += printed
    per_day = Counter(r["date"] for r in seam_rows_all if r["seam_class"] == "unexplained")
    market_days = {d for d, n in per_day.items() if n > MARKET_DAY_STRINGS}
    seam_rows_active, printed_active = [], 0
    for symbol, series in stitched.items():
        factors = massive_factors.get(symbol, []) + ours_factors.get(symbol, [])
        span_breaks = {lo for _s, lo, _hi in identities[symbol].ordinals(sessions)[1:]}
        rows, printed = classify_series(series, factors, span_breaks, params, sessions)
        incumbent = canonical_logs.get(symbol)
        for r in rows:
            r.update(incumbent_cols(r, incumbent, sessions, params))
        seam_rows_active.extend(rows)
        printed_active += printed
    for rows in (seam_rows_all, seam_rows_active):
        for r in rows:
            r["market_day"] = r["date"] in market_days
        rows.sort(key=rank_key)
    for i, r in enumerate(seam_rows_active, 1):
        r["rank"] = i
    write_csv(out / "seams_active.csv", seam_rows_active, ["rank", *_fields(seam_rows_active)])
    write_csv(out / "seams_strings.csv", seam_rows_all, _fields(seam_rows_all))

    # (6) Canonical against Massive.
    # Massive on today's scale: every Massive event of the instrument, plus our split facts no
    # Massive event matched (a split the endpoint lacks still divides its unadjusted tape).
    for m in members:
        if m.outcome == "ours_only" and m.ours is not None:
            massive_factors[m.symbol].append(ours_factor(m.ours, sessions))
    adjusted = {
        s: (series, adjusted_close(series, massive_factors.get(s, []), sessions))
        for s, series in stitched.items()
    }
    cases = [(s, date.fromisoformat(d), note) for s, d, note in NAMED_CASES]
    sweep_lines = []
    if sweep_csv is not None:
        with sweep_csv.open() as fh:
            sweep_lines = list(csv.DictReader(fh))
        cases += [
            (
                line["symbol"],
                date.fromisoformat(line["break_date"]),
                f"592 sweep {line['verdict']}: {line['evidence'][:120]}",
            )
            for line in sweep_lines
        ]
    witness = witness_rows(cases, canonical, adjusted, sessions, params.level_sessions)
    write_csv(out / "canonical_witness.csv", witness, _fields(witness))
    census = level_census(canonical, adjusted, sessions, params.level_sessions)
    write_csv(out / "level_census.csv", census, _fields(census))

    # (7) The disagreement ledger.
    ledger = disagreement_ledger(rec_rows)
    write_csv(out / "disagreement_ledger.csv", ledger, _fields(ledger))

    summary = {
        "capture_served_at": capture.isoformat(),
        "archive": archive_info,
        "parameters": {
            "seam": asdict(params),
            "same_event_days": rparams.same_event_days,
            "ratio_rel_tol": rparams.ratio_rel_tol,
            "market_day_strings": MARKET_DAY_STRINGS,
            "level_tol": LEVEL_TOL,
        },
        "reference": {
            "events_merged": len(ref.splits),
            "family_conflicts": len(ref.conflicts),
            "families": dict(Counter(",".join(sorted(s.families)) for s in ref.splits)),
            "attributed_own": len(own),
            "attributed_own_names": len({s for _x, s, _h in own}),
            "attribution": dict(Counter(h for _x, _s, h in own + excluded)),
        },
        "identity": dict(Counter(i.chain for i in identities.values())),
        "active": len(ref.active),
        "active_with_massive_series": len(stitched),
        "corporate_action_rows_active": len(recorded),
        "partition": partition_counts(members),
        "partition_total": len(members),
        "tape_by_outcome": {
            o: dict(Counter(r["tape"] for r in rec_rows if r["outcome"] == o))
            for o in partition_counts(members)
        },
        "proposed_rows": len(proposed),
        "proposed_guard_skips": sum(1 for p in proposed if p["guard_skip"]),
        "review_rows": len(review),
        "review_by_status": dict(Counter(r["status"] for r in review)),
        "vendor_duplicates": sum(1 for d in duplicates if d.kept),
        "vendor_internal_conflicts": sum(1 for d in duplicates if not d.kept),
        "seams_active": dict(Counter(r["seam_class"] for r in seam_rows_active)),
        "seams_active_names": {
            c: len({r["series"] for r in seam_rows_active if r["seam_class"] == c})
            for c in SEAM_CLASSES
        },
        "seams_active_printed_junctions": printed_active,
        "seams_active_unexplained_by_incumbent": dict(
            Counter(r["incumbent"] for r in seam_rows_active if r["seam_class"] == "unexplained")
        ),
        "seams_active_unexplained_off_market_days": sum(
            1 for r in seam_rows_active if r["seam_class"] == "unexplained" and not r["market_day"]
        ),
        "seams_strings": dict(Counter(r["seam_class"] for r in seam_rows_all)),
        "seams_strings_printed_junctions": printed_all,
        "market_days": len(market_days),
        "canonical_witness": dict(Counter(w["verdict"] for w in witness)),
        "canonical_witness_yahoo_holes": dict(
            Counter(
                w["verdict"]
                for w, line in zip(witness[len(NAMED_CASES) :], sweep_lines, strict=True)
                if line["evidence"].startswith("Yahoo's adjusted close cannot be bracketed")
            )
        ),
        "level_census_runs": len(census),
        "level_census_names": len({c["symbol"] for c in census}),
        "inputs": {
            "sweep_csv": str(sweep_csv) if sweep_csv else None,
            "sweep_sha256": sha256_of(sweep_csv) if sweep_csv else None,
        },
        "elapsed_s": round(time.monotonic() - t0, 1),
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True, default=str))
    print(json.dumps(summary, indent=2, sort_keys=True, default=str))
    print(f"outputs in {out}")
    return summary


def vendor_cols(split: VendorSplit) -> dict[str, Any]:
    return {
        "event_id": split.event_id,
        "execution_date": split.execution_date.isoformat(),
        "massive_factor": split.factor,
        "bulk_ticker": split.bulk_ticker,
        "v3_ticker": split.v3_ticker,
        "adjustment_type": split.adjustment_type,
        "families": ",".join(sorted(split.families)),
        "evidence": ";".join(split.evidence),
    }


def reconciled_row(m: ReconciledSplit) -> dict[str, Any]:
    row: dict[str, Any] = {"symbol": m.symbol, "outcome": m.outcome}
    row["date"] = (
        m.vendor_effective_date
        or (m.ours.effective_date if m.ours else None)
        or (m.vendor.execution_date if m.vendor else None)
    )
    row["date"] = row["date"].isoformat() if row["date"] else None
    row["vendor_effective_date"] = m.vendor_effective_date
    row["attribution"] = m.attribution
    if m.vendor is not None:
        row.update(vendor_cols(m.vendor))
    if m.ours is not None:
        row.update(
            {
                "action_id": m.ours.action_id,
                "ours_effective_date": m.ours.effective_date.isoformat(),
                "ours_factor": m.ours.factor,
                "ours_inferred_by": m.ours.inferred_by,
            }
        )
    row["session_offset"] = m.session_offset
    row["log_ratio_gap"] = m.log_ratio_gap
    return row


def proposed_line(
    m: ReconciledSplit, served_at: Mapping[str, datetime], row: Mapping[str, Any]
) -> dict[str, Any]:
    """One massive_only event as a corporate_action row: recorded_at is the latest serve time of
    the pages that served it (the announcement-time rule: the fact was knowable then, never at
    its effective date)."""
    assert m.vendor is not None and m.vendor_effective_date is not None
    cols = vendor_cols(m.vendor)
    return {
        "symbol": m.symbol,
        "action_type": "split" if m.vendor.factor > 1 else "reverse_split",
        "effective_date": m.vendor_effective_date.isoformat(),
        "factor": m.vendor.factor,
        "recorded_at": max(served_at[e] for e in m.vendor.evidence).isoformat(),
        **{k: cols[k] for k in ("event_id", "execution_date", "bulk_ticker", "v3_ticker")},
        **{k: cols[k] for k in ("adjustment_type", "families")},
        "attribution": m.attribution,
        "reference_raw_ids": cols["evidence"],
        "tape": row["tape"],
        "tape_level_step": row["tape_level_step"],
    }


# The design's precedence order (section 8a amendment): a filing-dated corporate action first,
# then the exchange-official close, then Massive's own continuity; Alpaca (2016+) corroborates and
# never outranks. Here the witnesses available per case are named in that order.
_LEDGER_OUTCOMES = ("date_offset", "ratio_disagree", "ours_only")


def disagreement_ledger(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for r in rows:
        contradicted = r["outcome"] in ("agree", "massive_only") and r["tape"] in (
            "tape_flat",
            "tape_conflict",
        )
        if r["outcome"] not in _LEDGER_OUTCOMES and not contradicted:
            continue
        witnesses = [
            "filing-dated action: none captured (SEC filings are a stage 2 input)",
            "exchange-official close: Massive day file close (Massive, not a third party; the "
            "independent pre-2016 witness is IBKR 1d, see canonical_witness.csv)",
            f"Massive continuity: tape {r['tape']} (level step {r['tape_level_step']})",
        ]
        if r["outcome"] == "date_offset":
            claim = (
                f"same event {r['session_offset']:+d} sessions apart: ours "
                f"{r['ours_effective_date']}, Massive {r['vendor_effective_date']}"
            )
        elif r["outcome"] == "ratio_disagree":
            claim = f"ratio ours x{r['ours_factor']} vs Massive x{r['massive_factor']}"
        elif r["outcome"] == "ours_only":
            claim = f"ours x{r['ours_factor']} at {r['ours_effective_date']}, no Massive event"
        else:
            claim = f"Massive x{r['massive_factor']} at {r['vendor_effective_date']} not on tape"
        if r["tape"] == "tape_step":
            verdict = "tape witnesses the step" + (
                ": the Massive endpoint lacks a split its own tape carries"
                if r["outcome"] == "ours_only"
                else ""
            )
        elif r["tape"] == "no_tape":
            verdict = "unresolved: no Massive tape at the date"
        else:
            verdict = f"unresolved: Massive tape reads {r['tape']}"
        out.append(
            {
                "symbol": r["symbol"],
                "span": r["date"],
                "outcome": r["outcome"],
                "claim": claim,
                "witnesses": " | ".join(witnesses),
                "verdict": verdict,
                "deciding_session": "pending lead ruling",
            }
        )
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument(
        "--sweep-csv",
        type=Path,
        default=None,
        help="an ops_split_calendar_audit --sweep CSV whose breaks get the Massive witness",
    )
    parser.add_argument("--archive", type=Path, default=DAY_ARCHIVE)
    args = parser.parse_args(argv)
    run(Settings(), args.out, args.sweep_csv, args.archive)
    return 0


if __name__ == "__main__":
    sys.exit(main())
