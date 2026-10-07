"""Read-only vendor adjustment basis study (plan 185-37 Task 2).

The reproduction of docs/research/vendor-adjustment-basis-study.md. Its decision rule and
operational definitions were committed in that document (a2d9ca6e1) before this script first ran
against the data.

Per name holding both TRADIER and SMART TRADES 1d observations: the latest current-scale close of
each vendor per date (`current_closes`, the D7 verdict's input), basis runs from
`find_basis_runs` with the APR tolerance and run minimum, each run's boundaries judged by the
pre-registered rule (a vendor's boundary move against the 99th percentile of its own moves over
the surrounding 250 common sessions), D7's `classify_run` recorded next to it, and the proposed
action. The spec's disagreement figure (raw latest closes differing by more than 1%) is
re-measured and decomposed into inside a run, isolated and other.

Outputs: one TSV row per run (--tsv), a JSON summary (--out), and one evidence JSON per proposed
exception row (--evidence-dir), which ops_source_policy.py --add reads in Task 3.

Every connection opens with default_transaction_read_only = on; the module holds no statement
that changes a row. Thresholds come from APR at run time; a missing key stops the run.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import math
import sys
import time
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import numpy as np

project_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(project_root))

from src.intelligence.bars.vendor_basis import (  # noqa: E402
    VENDOR_IBKR,
    VENDOR_TRADIER,
    BasisRun,
    classify_run,
    find_basis_runs,
    ratio_pairs,
)

_BP = 1e4
# Study parameters (the doc's "Study parameters"; not APR keys, the study is a one-off).
PERCENTILE = 99.0
HALF_WINDOW = 125
DISAGREE_SHARE = 0.01

_KEY_TOL = "threshold.bar_integrity.fallback_basis_tolerance_bp"
_KEY_MIN = "threshold.bar_integrity.vendor_ratio_run_min_sessions"
_APR_KEYS = (_KEY_TOL, _KEY_MIN)

ACTION_ROW = "row_ibkr"
ACTION_TRADIER_OK = "none_tradier_continuous"
ACTION_LIST_IBKR_STORED = "listed_tradier_continuous_ibkr_stored"
ACTION_ALREADY_IBKR = "none_already_ibkr"
ACTION_UNDECIDED = "undecided"
# Added after the first run (doc: "Range ends", a deviation that only withholds rows): a decided
# ibkr run whose bounded row would meet Tradier at an end where no common session measures the
# two vendors agreeing (a Tradier head or tail on the stale basis) would move the false return
# to that seam, where no check judges it. Such a row is withheld and listed.
ACTION_ROW_WITHHELD = "withheld_unmeasured_seam"
# Added after the first run, the same kind of deviation: an IBKR series whose run sessions are
# mostly zero-volume prints is not observing trades, so its continuity is no evidence (WBD 2016:
# a flat close of 25 on zero volume while Tradier trades millions of shares a day).
ACTION_ROW_WITHHELD_NO_TRADE = "withheld_ibkr_no_trade"
NO_TRADE_MAX_SHARE = 0.5

PLAN = "185-37"


# --- pure API -----------------------------------------------------------------------------


@dataclass(frozen=True)
class Boundary:
    side: str  # "before" or "after"
    prev: date
    cur: date
    ibkr_move: float
    ibkr_p99: float | None
    tradier_move: float
    tradier_p99: float | None
    explained_by: tuple[str, ...]
    vote: str | None


@dataclass(frozen=True)
class RunVerdict:
    run: BasisRun
    boundaries: tuple[Boundary, ...]
    continuous_vendor: str | None
    d7_continuous_vendor: str | None


@dataclass
class Decomposition:
    raw_disagree: int = 0
    raw_in_run: int = 0
    raw_isolated: int = 0
    raw_other: int = 0
    current_disagree: int = 0
    current_in_run: int = 0
    current_isolated: int = 0
    names_raw_disagree: set[str] = field(default_factory=set)

    def add(self, other: Decomposition) -> None:
        for name in (
            "raw_disagree",
            "raw_in_run",
            "raw_isolated",
            "raw_other",
            "current_disagree",
            "current_in_run",
            "current_isolated",
        ):
            setattr(self, name, getattr(self, name) + getattr(other, name))
        self.names_raw_disagree |= other.names_raw_disagree


def common_sessions(ibkr: Mapping[date, float], tradier: Mapping[date, float]) -> list[date]:
    """Dates where both closes are positive, in order (find_basis_runs' measurable pairs)."""
    return sorted(d for d in ibkr.keys() & tradier.keys() if ibkr[d] > 0 and tradier[d] > 0)


def log_moves(closes: Mapping[date, float], sessions: Sequence[date]) -> list[float]:
    """|ln(close[i] / close[i-1])| for i >= 1; index i is the move ending at sessions[i]."""
    return [
        abs(math.log(closes[sessions[i]] / closes[sessions[i - 1]]))
        for i in range(1, len(sessions))
    ]


def ordinary_ceiling(
    moves: Sequence[float],
    cur_index: int,
    exclude: Collection[int],
    *,
    half_window: int = HALF_WINDOW,
    percentile: float = PERCENTILE,
) -> float | None:
    """The percentile of a vendor's moves around a boundary (doc: ordinary range).

    `moves[k]` ends at session k + 1 (log_moves drops index 0). The boundary move ends at session
    cur_index; the sample is the half_window moves ending at or before cur_index - 1 and the
    half_window moves ending at or after cur_index + 1, minus the run's boundary moves. None when
    the sample is empty.
    """
    # move ending at session s sits at moves[s - 1]
    before = range(max(1, cur_index - half_window), cur_index)
    after = range(cur_index + 1, min(len(moves) + 1, cur_index + 1 + half_window))
    sample = [moves[s - 1] for s in (*before, *after) if s not in exclude]
    if not sample:
        return None
    return float(np.percentile(np.asarray(sample, dtype=np.float64), percentile))


def judge_run(
    run: BasisRun,
    ibkr: Mapping[date, float],
    tradier: Mapping[date, float],
    action_dates: Mapping[date, str],
    *,
    half_window: int = HALF_WINDOW,
    percentile: float = PERCENTILE,
) -> tuple[tuple[Boundary, ...], str | None]:
    """The run's boundaries and the pre-registered verdict (doc: boundary votes, run verdict)."""
    sessions = common_sessions(ibkr, tradier)
    index = {d: i for i, d in enumerate(sessions)}
    ibkr_moves = log_moves(ibkr, sessions)
    tradier_moves = log_moves(tradier, sessions)
    start, end = index[run.start], index[run.end]
    pairs: list[tuple[str, int]] = []
    if start > 0:
        pairs.append(("before", start))
    if end + 1 < len(sessions):
        pairs.append(("after", end + 1))
    exclude = {cur for _, cur in pairs}
    boundaries: list[Boundary] = []
    for side, cur in pairs:
        prev_day, cur_day = sessions[cur - 1], sessions[cur]
        explained = tuple(
            sorted(
                f"{a}@{d.isoformat()}" for d, a in action_dates.items() if prev_day < d <= cur_day
            )
        )
        i_move, t_move = ibkr_moves[cur - 1], tradier_moves[cur - 1]
        i_cap = ordinary_ceiling(
            ibkr_moves, cur, exclude, half_window=half_window, percentile=percentile
        )
        t_cap = ordinary_ceiling(
            tradier_moves, cur, exclude, half_window=half_window, percentile=percentile
        )
        vote: str | None = None
        if not explained and i_cap is not None and t_cap is not None:
            i_ok, t_ok = i_move < i_cap, t_move < t_cap
            if i_ok and not t_ok:
                vote = VENDOR_IBKR
            elif t_ok and not i_ok:
                vote = VENDOR_TRADIER
        boundaries.append(
            Boundary(side, prev_day, cur_day, i_move, i_cap, t_move, t_cap, explained, vote)
        )
    votes = {b.vote for b in boundaries if b.vote is not None}
    verdict = votes.pop() if len(votes) == 1 else None
    return tuple(boundaries), verdict


def isolated_dates(
    pairs: Sequence[tuple[date, float, float]], *, tolerance_bp: float, min_sessions: int
) -> set[date]:
    """Out-of-tolerance dates in stretches shorter than min_sessions (find_basis_runs' complement).

    Non-positive pairs are skipped exactly as find_basis_runs skips them.
    """
    out: set[date] = set()
    current: list[date] = []
    for session, i_close, t_close in pairs:
        if i_close <= 0 or t_close <= 0:
            continue
        if abs(i_close / t_close - 1.0) * _BP > tolerance_bp:
            current.append(session)
        else:
            if len(current) < min_sessions:
                out.update(current)
            current = []
    if len(current) < min_sessions:
        out.update(current)
    return out


def decompose(
    symbol: str,
    raw_ibkr: Mapping[date, float],
    raw_tradier: Mapping[date, float],
    cur_ibkr: Mapping[date, float],
    cur_tradier: Mapping[date, float],
    runs: Sequence[BasisRun],
    *,
    tolerance_bp: float,
    min_sessions: int,
    share: float = DISAGREE_SHARE,
) -> Decomposition:
    """The doc's decomposition of name-dates differing by more than `share`."""
    in_run: set[date] = set()
    cur_sessions = common_sessions(cur_ibkr, cur_tradier)
    for run in runs:
        in_run.update(d for d in cur_sessions if run.start <= d <= run.end)
    cur_pairs = ratio_pairs(cur_ibkr, cur_tradier)
    isolated = isolated_dates(cur_pairs, tolerance_bp=tolerance_bp, min_sessions=min_sessions)
    out = Decomposition()
    for d in common_sessions(raw_ibkr, raw_tradier):
        if abs(raw_ibkr[d] / raw_tradier[d] - 1.0) > share:
            out.raw_disagree += 1
            out.names_raw_disagree.add(symbol)
            if d in in_run:
                out.raw_in_run += 1
            elif d in isolated:
                out.raw_isolated += 1
            else:
                out.raw_other += 1
    for d in cur_sessions:
        if abs(cur_ibkr[d] / cur_tradier[d] - 1.0) > share:
            out.current_disagree += 1
            if d in in_run:
                out.current_in_run += 1
            elif d in isolated:
                out.current_isolated += 1
    return out


@dataclass(frozen=True)
class PolicySpan:
    valid_from: date
    valid_to: date | None
    primary_source: str


def ibkr_policy_overlaps(run: BasisRun, symbol_rows: Sequence[PolicySpan]) -> bool:
    """Does a primary-ibkr symbol row cover any date of the run?"""
    for row in symbol_rows:
        if row.primary_source != VENDOR_IBKR:
            continue
        if row.valid_from <= run.end and (row.valid_to is None or row.valid_to > run.start):
            return True
    return False


@dataclass(frozen=True)
class RangeEnds:
    """What a row bounded to the run meets at each end (doc: range ends)."""

    entry_ratio: float | None  # IBKR/Tradier at the last common session before the run
    exit_ratio: float | None  # IBKR/Tradier at the first common session after the run
    tradier_head: int  # Tradier dates before the run when no common session precedes it
    tradier_tail: int  # Tradier dates after the run when no common session follows it
    measured: bool


def range_ends(
    run: BasisRun,
    ibkr: Mapping[date, float],
    tradier: Mapping[date, float],
    *,
    tolerance_bp: float,
) -> RangeEnds:
    """Each end is measured when a common session next to it agrees within the tolerance, or
    when Tradier holds no date beyond it (nothing to splice against)."""
    sessions = common_sessions(ibkr, tradier)
    before = [d for d in sessions if d < run.start]
    after = [d for d in sessions if d > run.end]

    def agrees(ratio: float) -> bool:
        return abs(ratio - 1.0) * _BP <= tolerance_bp

    entry = ibkr[before[-1]] / tradier[before[-1]] if before else None
    exit_ = ibkr[after[0]] / tradier[after[0]] if after else None
    head = 0 if before else sum(1 for d in tradier if d < run.start)
    tail = 0 if after else sum(1 for d in tradier if d > run.end)
    entry_ok = agrees(entry) if entry is not None else head == 0
    exit_ok = agrees(exit_) if exit_ is not None else tail == 0
    return RangeEnds(entry, exit_, head, tail, entry_ok and exit_ok)


def zero_volume_share(volumes: Mapping[date, float | None], run: BasisRun) -> float | None:
    """Share of the vendor's answered sessions in the run whose volume is zero or missing."""
    days = [d for d in volumes if run.start <= d <= run.end]
    if not days:
        return None
    return sum(1 for d in days if not volumes[d]) / len(days)


def proposed_action(verdict: str | None, stored_vendors: Collection[str], ibkr_policy: bool) -> str:
    """Rule 3 (doc: proposed row)."""
    if verdict is None:
        return ACTION_UNDECIDED
    if verdict == VENDOR_TRADIER:
        return ACTION_LIST_IBKR_STORED if VENDOR_IBKR in stored_vendors else ACTION_TRADIER_OK
    if ibkr_policy or VENDOR_TRADIER not in stored_vendors:
        return ACTION_ALREADY_IBKR
    return ACTION_ROW


def evidence_record(
    symbol: str, rv: RunVerdict, *, tolerance_bp: float, min_sessions: int, measured_at: datetime
) -> dict[str, Any]:
    """The exception row's evidence (doc: proposed row)."""
    run = rv.run
    return {
        "plan": PLAN,
        "rule": "vendor_basis_study decision rule (docs/research/vendor-adjustment-basis-study.md)",
        "measured_at": measured_at.isoformat(),
        "symbol": symbol,
        "run": {
            "start": run.start.isoformat(),
            "end": run.end.isoformat(),
            "n_sessions": run.n_sessions,
            "median_ratio_ibkr_over_tradier": run.median_ratio,
        },
        "boundaries": [
            {
                "side": b.side,
                "prev": b.prev.isoformat(),
                "cur": b.cur.isoformat(),
                "ibkr_abs_log_move": b.ibkr_move,
                "ibkr_p99": b.ibkr_p99,
                "tradier_abs_log_move": b.tradier_move,
                "tradier_p99": b.tradier_p99,
                "explained_by": list(b.explained_by),
                "vote": b.vote,
            }
            for b in rv.boundaries
        ],
        "continuous_vendor": rv.continuous_vendor,
        "d7_classify_run": rv.d7_continuous_vendor,
        "tolerance_bp": tolerance_bp,
        "run_min_sessions": min_sessions,
        "percentile": PERCENTILE,
        "surrounding_sessions": 2 * HALF_WINDOW,
    }


def _fmt(value: float | None, digits: int = 6) -> str:
    return "" if value is None else f"{value:.{digits}f}"


# --- database edge ------------------------------------------------------------------------

_BOTH_VENDOR_NAMES_SQL = """
SELECT symbol FROM ohlcv_observation
WHERE timeframe = '1d' AND what_to_show = 'TRADES' AND route IN ('TRADIER', 'SMART')
GROUP BY symbol HAVING count(DISTINCT route) = 2
ORDER BY symbol
"""
_STORED_SOURCES_SQL = """
SELECT timestamp::date AS d, source FROM market_data_ohlcv_tradeable
WHERE symbol = $1 AND timeframe = '1d'
"""
_SYMBOL_POLICY_SQL = """
SELECT valid_from, valid_to, primary_source FROM bar_source_policy
WHERE timeframe = '1d' AND symbol = $1
"""
_APR_SQL = "SELECT config_key, config_value FROM config_state WHERE config_key = ANY($1::text[])"

TSV_COLUMNS = (
    "symbol",
    "compute_1d",
    "run_start",
    "run_end",
    "n_sessions",
    "median_ratio",
    "before_prev",
    "before_cur",
    "before_ibkr_move",
    "before_ibkr_p99",
    "before_tradier_move",
    "before_tradier_p99",
    "before_vote",
    "after_prev",
    "after_cur",
    "after_ibkr_move",
    "after_ibkr_p99",
    "after_tradier_move",
    "after_tradier_p99",
    "after_vote",
    "continuous_vendor",
    "d7_continuous_vendor",
    "corporate_action_on_boundary",
    "stored_vendors",
    "ibkr_policy",
    "d7_blocking",
    "tradier_only_dates_in_range",
    "entry_ratio",
    "exit_ratio",
    "tradier_head",
    "tradier_tail",
    "ibkr_zero_volume_share",
    "proposed_action",
)


def _row(
    symbol: str,
    compute: bool,
    rv: RunVerdict,
    stored: Collection[str],
    ibkr_policy: bool,
    d7_blocking: bool,
    tradier_only_in_range: int,
    ends: RangeEnds,
    ibkr_zero_share: float | None,
    action: str,
) -> dict[str, str]:
    run = rv.run
    out = {
        "symbol": symbol,
        "compute_1d": str(compute).lower(),
        "run_start": run.start.isoformat(),
        "run_end": run.end.isoformat(),
        "n_sessions": str(run.n_sessions),
        "median_ratio": _fmt(run.median_ratio),
        "continuous_vendor": rv.continuous_vendor or "",
        "d7_continuous_vendor": rv.d7_continuous_vendor or "",
        "corporate_action_on_boundary": ";".join(e for b in rv.boundaries for e in b.explained_by),
        "stored_vendors": ",".join(sorted(stored)),
        "ibkr_policy": str(ibkr_policy).lower(),
        "d7_blocking": str(d7_blocking).lower(),
        "tradier_only_dates_in_range": str(tradier_only_in_range),
        "entry_ratio": _fmt(ends.entry_ratio),
        "exit_ratio": _fmt(ends.exit_ratio),
        "tradier_head": str(ends.tradier_head),
        "tradier_tail": str(ends.tradier_tail),
        "ibkr_zero_volume_share": _fmt(ibkr_zero_share, 4),
        "proposed_action": action,
    }
    for side in ("before", "after"):
        b = next((x for x in rv.boundaries if x.side == side), None)
        out[f"{side}_prev"] = b.prev.isoformat() if b else ""
        out[f"{side}_cur"] = b.cur.isoformat() if b else ""
        out[f"{side}_ibkr_move"] = _fmt(b.ibkr_move if b else None)
        out[f"{side}_ibkr_p99"] = _fmt(b.ibkr_p99 if b else None)
        out[f"{side}_tradier_move"] = _fmt(b.tradier_move if b else None)
        out[f"{side}_tradier_p99"] = _fmt(b.tradier_p99 if b else None)
        out[f"{side}_vote"] = (b.vote or "") if b else ""
    return out


async def _connect() -> Any:
    import asyncpg

    from src.config.settings import Settings

    dsn = Settings().database_url.replace("postgresql+asyncpg://", "postgresql://")
    conn = await asyncpg.connect(dsn, server_settings={"default_transaction_read_only": "on"})
    if await conn.fetchval("SHOW default_transaction_read_only") != "on":
        await conn.close()
        raise SystemExit("connection is not read-only")
    return conn


def _raw_latest_volume(observations: Sequence[Any], route: str) -> dict[date, float | None]:
    """Latest raw volume per date of one route (same ordering as _raw_latest)."""
    out: dict[date, float | None] = {}
    for o in observations:
        if o.route == route:
            out[o.bar_date] = None if o.volume is None else float(o.volume)
    return out


def _raw_latest(observations: Sequence[Any], route: str) -> dict[date, float]:
    """Latest raw close per date of one route (observations arrive ordered by date, fetched_at)."""
    out: dict[date, float] = {}
    for o in observations:
        if o.route == route and o.close is not None:
            out[o.bar_date] = float(o.close)
    return out


async def run_study(args: argparse.Namespace) -> int:
    from services.bar_derivation import (
        _DISCOVER_DAILY_SYMBOLS_SQL,
        _SELECT_DAILY_OBSERVATIONS_SQL,
        _SELECT_DAILY_SPLITS_SQL,
    )
    from src.intelligence.bars.daily_rule import current_closes
    from src.intelligence.bars.derivation import Observation, SplitRecord
    from src.intelligence.bars.vendor_basis import blocking, canonical_vendor

    started = time.perf_counter()
    measured_at = datetime.now(UTC)
    conn = await _connect()
    try:
        apr = {
            r["config_key"]: r["config_value"] for r in await conn.fetch(_APR_SQL, list(_APR_KEYS))
        }
        missing = [k for k in _APR_KEYS if k not in apr]
        if missing:
            raise SystemExit(f"missing APR keys: {missing}")
        tolerance_bp = float(apr[_KEY_TOL])
        min_sessions = int(apr[_KEY_MIN])
        compute = {r[0] for r in await conn.fetch(_DISCOVER_DAILY_SYMBOLS_SQL)}
        names = [r[0] for r in await conn.fetch(_BOTH_VENDOR_NAMES_SQL)]
        if args.symbols:
            wanted = {s.strip() for part in args.symbols for s in part.split(",") if s.strip()}
            names = [n for n in names if n in wanted]
        total = Decomposition()
        rows: list[dict[str, str]] = []
        n_runs_by_name: dict[str, int] = {}
        evidence_dir = Path(args.evidence_dir) if args.evidence_dir else None
        if evidence_dir:
            evidence_dir.mkdir(parents=True, exist_ok=True)
        for symbol in names:
            obs = [
                Observation(
                    request_id=r["request_id"],
                    route=r["route"],
                    bar_date=r["bar_date"],
                    open=r["open"],
                    high=r["high"],
                    low=r["low"],
                    close=r["close"],
                    volume=r["volume"],
                    fetched_at=r["fetched_at"],
                    legacy=r["legacy"],
                    what_to_show=r["what_to_show"],
                )
                for r in await conn.fetch(
                    _SELECT_DAILY_OBSERVATIONS_SQL, symbol, ["TRADIER", "SMART"]
                )
            ]
            action_rows = await conn.fetch(_SELECT_DAILY_SPLITS_SQL, symbol)
            splits = [
                SplitRecord(
                    effective_date=r["effective_date"],
                    recorded_at=r["recorded_at"],
                    factor=r["factor"],
                    evidence_request_ids=tuple(r["evidence_request_ids"] or ()),
                )
                for r in action_rows
            ]
            action_dates = {r["effective_date"]: "corporate_action" for r in action_rows}
            cur_tradier, cur_ibkr = current_closes(obs, splits)
            runs = find_basis_runs(
                ratio_pairs(cur_ibkr, cur_tradier),
                tolerance_bp=tolerance_bp,
                min_sessions=min_sessions,
            )
            total.add(
                decompose(
                    symbol,
                    _raw_latest(obs, "SMART"),
                    _raw_latest(obs, "TRADIER"),
                    cur_ibkr,
                    cur_tradier,
                    runs,
                    tolerance_bp=tolerance_bp,
                    min_sessions=min_sessions,
                )
            )
            n_runs_by_name[symbol] = len(runs)
            if not runs:
                continue
            stored_rows = await conn.fetch(_STORED_SOURCES_SQL, symbol)
            stored = {r["d"]: r["source"] for r in stored_rows}
            policy = [
                PolicySpan(r["valid_from"], r["valid_to"], r["primary_source"])
                for r in await conn.fetch(_SYMBOL_POLICY_SQL, symbol)
            ]
            ibkr_dates = set(cur_ibkr)
            ibkr_volume = _raw_latest_volume(obs, "SMART")
            for run in runs:
                boundaries, verdict = judge_run(run, cur_ibkr, cur_tradier, action_dates)
                d7 = classify_run(run, cur_ibkr, cur_tradier, splits, tolerance_bp=tolerance_bp)
                rv = RunVerdict(run, boundaries, verdict, d7)
                in_range = [d for d in stored if run.start <= d <= run.end]
                vendors = {v for d in in_range if (v := canonical_vendor(stored[d])) is not None}
                ibkr_pol = ibkr_policy_overlaps(run, policy)
                d7_block = blocking(replace(run, continuous_vendor=d7), vendors)
                tradier_only = sum(
                    1 for d in cur_tradier if run.start <= d <= run.end and d not in ibkr_dates
                )
                ends = range_ends(run, cur_ibkr, cur_tradier, tolerance_bp=tolerance_bp)
                action = proposed_action(verdict, vendors, ibkr_pol)
                zero_share = zero_volume_share(ibkr_volume, run)
                if action == ACTION_ROW and not ends.measured:
                    action = ACTION_ROW_WITHHELD
                elif action == ACTION_ROW and (zero_share or 0.0) > NO_TRADE_MAX_SHARE:
                    action = ACTION_ROW_WITHHELD_NO_TRADE
                rows.append(
                    _row(
                        symbol,
                        symbol in compute,
                        rv,
                        vendors,
                        ibkr_pol,
                        d7_block,
                        tradier_only,
                        ends,
                        zero_share,
                        action,
                    )
                )
                if action == ACTION_ROW and evidence_dir:
                    record = evidence_record(
                        symbol,
                        rv,
                        tolerance_bp=tolerance_bp,
                        min_sessions=min_sessions,
                        measured_at=measured_at,
                    )
                    record["tradier_only_dates_in_range"] = tradier_only
                    record["entry_ratio"] = ends.entry_ratio
                    record["exit_ratio"] = ends.exit_ratio
                    record["tradier_head"] = ends.tradier_head
                    record["tradier_tail"] = ends.tradier_tail
                    record["ibkr_zero_volume_share"] = zero_share
                    path = evidence_dir / f"{symbol}_{run.start.isoformat()}.json"
                    path.write_text(json.dumps(record, indent=2))
    finally:
        await conn.close()
    if args.tsv:
        with Path(args.tsv).open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=TSV_COLUMNS, delimiter="\t")
            writer.writeheader()
            writer.writerows(rows)
    elapsed = time.perf_counter() - started
    by_action: dict[str, int] = {}
    for r in rows:
        by_action[r["proposed_action"]] = by_action.get(r["proposed_action"], 0) + 1
    summary = {
        "measured_at": measured_at.isoformat(),
        "elapsed_seconds": round(elapsed, 1),
        "tolerance_bp": tolerance_bp,
        "run_min_sessions": min_sessions,
        "percentile": PERCENTILE,
        "surrounding_sessions": 2 * HALF_WINDOW,
        "names_both_vendors": len(names),
        "names_with_runs": sum(1 for n in n_runs_by_name.values() if n),
        "runs": len(rows),
        "runs_by_action": by_action,
        "runs_by_verdict": {
            v: sum(1 for r in rows if r["continuous_vendor"] == v) for v in ("ibkr", "tradier", "")
        },
        "rule_vs_d7_disagree": sum(
            1 for r in rows if r["continuous_vendor"] != r["d7_continuous_vendor"]
        ),
        "d7_blocking_runs": sum(1 for r in rows if r["d7_blocking"] == "true"),
        "d7_blocking_names_compute_1d": sorted(
            {r["symbol"] for r in rows if r["d7_blocking"] == "true" and r["compute_1d"] == "true"}
        ),
        "decomposition": {
            "raw_disagree": total.raw_disagree,
            "raw_disagree_names": len(total.names_raw_disagree),
            "raw_in_run": total.raw_in_run,
            "raw_isolated": total.raw_isolated,
            "raw_other": total.raw_other,
            "current_disagree": total.current_disagree,
            "current_in_run": total.current_in_run,
            "current_isolated": total.current_isolated,
        },
    }
    text = json.dumps(summary, indent=2)
    if args.out:
        Path(args.out).write_text(text)
    print(text)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--symbols", nargs="*", default=None)
    parser.add_argument("--tsv", default=None, help="one row per basis run")
    parser.add_argument("--out", default=None, help="JSON summary")
    parser.add_argument("--evidence-dir", default=None, help="one JSON per proposed row")
    return asyncio.run(run_study(parser.parse_args(argv)))


if __name__ == "__main__":
    sys.exit(main())
