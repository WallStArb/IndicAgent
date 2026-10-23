"""ops_tradier_residue.py - readiness gate, residue measurement, no-Tradier proof (191-19).

Read-only ops script for the Tradier retirement (todo 533 steps 2 and 3, plan 191-19). D is
2026-10-07, the day canonical 1d primary moved from Tradier to IBKR (migration 456); before D
the closed policy row is primary tradier, fallback ibkr. Four modes:

- --readiness: ready only when, for every name with Tradier 1d raw rows, an IBKR 1d ask
  (ohlcv_request, outcome bars or no_data) starts at or before max(first Tradier bar, today
  minus 9800 days) and was answered after the depth change (config_history of
  infra.backfill.depth_days.1d, 7300 to 9800). Not ready lists the unanswered names, exits 2.
- --measure: per name, the Tradier sessions no IBKR answer covers (no smart_trades or
  listing-venue route raw row, no ohlcv_empty_history window over the date), the first-bar
  change the deletion would cause, and the Tradier/IBKR value distribution at common smart
  sessions (owner context for todo 518: pre-D canonical values become IBKR's after 191-20).
- --prove: the UNCHANGED d2-v3 rule per name, run through the same readers the live daily
  stage uses (services.bar_derivation.read_daily_inputs and read_daily_params), over the raw
  candidates with vendor tradier removed and the real bar_source_policy rows, writing nothing.
  A name is proven when every pre-D session where IBKR holds a smart_trades or venue-route bar
  is served. Venue-route sessions are never rule inputs (the D-17 venue study failed), so
  venue-only sessions are the expected residue (todo 433) and are flagged separately. Post-D,
  where IBKR is already primary, the harness output digest must equal the stored canonical 1d
  digest on a name sample: the self-check that the harness reproduces the rule.
- --report: renders the measure and prove outputs as the owner-facing record.

The connection is read-only at the session level; the module holds no data-modifying SQL.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

project_root = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(project_root))

import asyncpg  # noqa: E402
import numpy as np  # noqa: E402

from services._batch_utils import load_apr_dict_async  # noqa: E402
from services.bar_derivation import read_daily_inputs, read_daily_params  # noqa: E402
from src.config.settings import Settings  # noqa: E402
from src.intelligence.bars.daily_rule import (  # noqa: E402
    FLAG_FALLBACK_SEAM,
    FLAG_NO_VOLUME,
    FLAG_PRE_SPLIT,
    ROUTE_TRADIER,
    derive_daily_v2,
)
from src.intelligence.bars.digest import bar_content_digest  # noqa: E402
from src.intelligence.bars.vendor_kind import VENUE_ROUTE_KINDS  # noqa: E402

D = date(2026, 10, 7)
DEPTH_KEY = "infra.backfill.depth_days.1d"
DEPTH_DAYS = 9800
SMART_KIND = "smart_trades"
# The raw kinds that mean IBKR answered a daily session: the SMART TRADES answer plus every
# listing-venue route kind (migration 476; the bare `venue` raw kind no longer exists, so a
# predicate on it would silently match zero rows). smart_adjusted is never canonical, never
# coverage.
IBKR_RAW_KINDS: tuple[str, ...] = (SMART_KIND, *VENUE_ROUTE_KINDS)
# The daily stage's own flag rules (bar_derivation._DAILY_FLAG_RULES). The digest overlay swaps
# them for the harness's own because the harness re-derives them itself.
DAILY_FLAG_RULES = frozenset({FLAG_FALLBACK_SEAM, FLAG_PRE_SPLIT, FLAG_NO_VOLUME})
DEFAULT_SELF_CHECK_SAMPLE = 50
DEFAULT_REPORT_PATH = ".planning/phases/191-unified-raw-bar-table/191-TRADIER-RESIDUE.md"


# --- readiness (T-191-41: no residue claim before the gap-fill cycle finished) ------------------


def readiness_threshold(first_tradier: date, today: date) -> date:
    """The window start an IBKR ask must reach: the deeper of the first Tradier bar and the
    9800-day depth horizon at `today`."""
    return max(first_tradier, today - timedelta(days=DEPTH_DAYS))


def readiness_answered(
    first_tradier: date,
    asks: Sequence[tuple[date, datetime]],
    depth_at: datetime,
    today: date,
) -> bool:
    """True when an ask (window start, answered time) both starts at or before the threshold
    and was answered after the depth change: an ask answered earlier used the shallower depth
    and says nothing about the deeper span."""
    threshold = readiness_threshold(first_tradier, today)
    return any(start <= threshold and at > depth_at for start, at in asks)


@dataclass(frozen=True)
class NameReadiness:
    """One Tradier name and whether IBKR has been asked deep enough since the depth change."""

    symbol: str
    first_tradier: date
    answered: bool


def classify_readiness(rows: Sequence[NameReadiness]) -> tuple[list[str], list[str]]:
    """(answered symbols, unanswered symbols) in input order."""
    answered = [row.symbol for row in rows if row.answered]
    unanswered = [row.symbol for row in rows if not row.answered]
    return answered, unanswered


# --- measure (the residue and the value-difference context) --------------------------------------


@dataclass(frozen=True)
class NameMeasure:
    """One name's Tradier residue: sessions only Tradier answers, and the first-bar change."""

    symbol: str
    n_tradier: int
    n_smart_sessions: int
    n_venue_sessions: int
    n_residue: int
    residue_first: date | None
    residue_last: date | None
    residue_dates: list[date]
    first_bar_current: date | None
    first_bar_after: date | None
    n_common: int
    close_bp_median: float | None
    close_bp_p10: float | None
    close_bp_p90: float | None
    volume_ratio_median: float | None


def _percentile(values: Sequence[float], q: float) -> float | None:
    """numpy's linear-interpolation percentile, or None for an empty sample."""
    if not values:
        return None
    return float(np.percentile(np.asarray(values, dtype=np.float64), q))


def measure_name(
    symbol: str,
    tradier: Sequence[tuple[date, float, int | None]],
    ibkr: Sequence[tuple[date, str, float, int | None]],
    empty: Sequence[tuple[datetime, datetime]],
    stored_first: date | None,
) -> NameMeasure:
    """Pure --measure arithmetic.

    A Tradier session is residue when no IBKR answer covers it: no smart_trades or venue-route
    raw row that day and no ohlcv_empty_history no_data window over it. The post-deletion first
    bar is the first smart_trades day (venue rows are never rule inputs, so they serve nothing);
    None means the name loses its whole 1d history. The value distribution compares IBKR's
    smart close and volume with Tradier's at common smart sessions only.
    """
    tradier_by_day = {day: (close, volume) for day, close, volume in tradier}
    smart_close = {day: close for day, kind, close, _v in ibkr if kind == SMART_KIND}
    smart_volume = {day: volume for day, kind, _c, volume in ibkr if kind == SMART_KIND}
    venue_days = {day for day, kind, _c, _v in ibkr if kind in VENUE_ROUTE_KINDS}
    covered = set(smart_close) | venue_days
    for empty_from, empty_through in empty:
        lo, hi = empty_from.date(), empty_through.date()
        covered |= {day for day in tradier_by_day if lo <= day <= hi}
    residue_dates = sorted(day for day in tradier_by_day if day not in covered)

    common = sorted(day for day in tradier_by_day if day in smart_close)
    close_bp: list[float] = []
    volume_ratio: list[float] = []
    for day in common:
        tradier_close, tradier_volume = tradier_by_day[day]
        if tradier_close > 0:
            close_bp.append((smart_close[day] - tradier_close) / tradier_close * 1e4)
        if tradier_volume and smart_volume.get(day) is not None:
            volume_ratio.append(smart_volume[day] / tradier_volume)

    return NameMeasure(
        symbol=symbol,
        n_tradier=len(tradier_by_day),
        n_smart_sessions=len(smart_close),
        n_venue_sessions=len(venue_days),
        n_residue=len(residue_dates),
        residue_first=residue_dates[0] if residue_dates else None,
        residue_last=residue_dates[-1] if residue_dates else None,
        residue_dates=residue_dates,
        first_bar_current=stored_first,
        first_bar_after=min(smart_close) if smart_close else None,
        n_common=len(common),
        close_bp_median=_percentile(close_bp, 50.0),
        close_bp_p10=_percentile(close_bp, 10.0),
        close_bp_p90=_percentile(close_bp, 90.0),
        volume_ratio_median=_percentile(volume_ratio, 50.0),
    )


# --- prove (the unchanged rule with Tradier removed; T-191-42 and T-191-43) ----------------------


@dataclass(frozen=True)
class NameProof:
    """One name's no-Tradier proof verdict."""

    symbol: str
    proven: bool
    n_required: int
    served_named: int
    served_fallback: int
    unserved: list[date]
    unserved_smart: int
    unserved_venue_only: int
    venue_moved: bool
    exception: str | None


def classify_proof(
    symbol: str,
    *,
    smart_dates: Sequence[date],
    venue_dates: Sequence[date],
    bars: Sequence[Any],
    error: BaseException | None = None,
) -> NameProof:
    """The proof verdict: a name is proven when every pre-D session where IBKR holds a
    smart_trades or venue-route bar has a harness bar at that date and the rule raised nothing.
    An exception fails the name outright and leaves `unserved` empty: the rule never finished,
    so which sessions it would have missed is not knowable. A name whose only unserved sessions
    are venue-only is the listing-venue move case (todo 433), flagged by `venue_moved`."""
    smart = set(smart_dates)
    required = sorted(day for day in smart | set(venue_dates) if day < D)
    served_named = sum(1 for bar in bars if bar.kind != "fallback")
    served_fallback = sum(1 for bar in bars if bar.kind == "fallback")
    if error is not None:
        return NameProof(
            symbol,
            False,
            len(required),
            served_named,
            served_fallback,
            [],
            0,
            0,
            False,
            str(error),
        )
    served = {bar.bar_date for bar in bars}
    unserved = [day for day in required if day not in served]
    unserved_smart = sum(1 for day in unserved if day in smart)
    unserved_venue_only = len(unserved) - unserved_smart
    venue_moved = unserved_venue_only > 0 and unserved_smart == 0
    return NameProof(
        symbol,
        not unserved,
        len(required),
        served_named,
        served_fallback,
        unserved,
        unserved_smart,
        unserved_venue_only,
        venue_moved,
        None,
    )


@dataclass(frozen=True)
class SelfCheck:
    """The harness-vs-stored digest comparison for one name's post-D window."""

    symbol: str
    equal: bool
    n_harness: int
    n_stored: int
    harness_digest: str
    stored_digest: str
    harness_kinds: dict[str, int]
    stored_kinds: dict[str, int]


def _epoch_seconds(day: date) -> int:
    return int(datetime(day.year, day.month, day.day, tzinfo=UTC).timestamp())


def digest_self_check(
    symbol: str,
    bars: Sequence[Any],
    harness_flags: dict[date, Sequence[str]],
    stored_rows: Sequence[Any],
    stored_rules: dict[int, set[str]],
) -> SelfCheck:
    """The harness reproduces the rule (T-191-42): post-D, where IBKR is already primary, the
    harness output and the stored canonical rows must digest identically.

    The rule overlay gives the harness side the stored rules minus the daily-stage flag rules
    (the harness re-derives those itself) plus the harness's own flags; the stored side keeps
    its rules as written. Both digests are the one bar content digest definition (D-07) over
    all rows sorted by timestamp, so count or value or rule differences all break equality.
    Stored rows are (timestamp, vendor, kind, open, high, low, close, volume)."""
    harness = sorted(bars, key=lambda bar: bar.bar_date)
    harness_ts = np.array([_epoch_seconds(bar.bar_date) for bar in harness], dtype=np.int64)
    harness_rules = [
        tuple(
            sorted(
                (stored_rules.get(int(ts), set()) - DAILY_FLAG_RULES)
                | set(harness_flags.get(bar.bar_date, ()))
            )
        )
        for ts, bar in zip(harness_ts, harness, strict=True)
    ]
    harness_digest = bar_content_digest(
        harness_ts,
        np.array([bar.open for bar in harness], dtype=np.float64),
        np.array([bar.high for bar in harness], dtype=np.float64),
        np.array([bar.low for bar in harness], dtype=np.float64),
        np.array([bar.close for bar in harness], dtype=np.float64),
        np.array([bar.volume for bar in harness], dtype=np.float64),
        harness_rules,
    )
    stored = sorted(stored_rows, key=lambda row: row[0])
    stored_ts = np.array([int(row[0].timestamp()) for row in stored], dtype=np.int64)
    stored_digest = bar_content_digest(
        stored_ts,
        np.array([row[3] for row in stored], dtype=np.float64),
        np.array([row[4] for row in stored], dtype=np.float64),
        np.array([row[5] for row in stored], dtype=np.float64),
        np.array([row[6] for row in stored], dtype=np.float64),
        np.array([row[7] for row in stored], dtype=np.float64),
        [tuple(sorted(stored_rules.get(int(ts), ()))) for ts in stored_ts],
    )
    harness_kinds: dict[str, int] = {}
    for bar in harness:
        harness_kinds[bar.kind] = harness_kinds.get(bar.kind, 0) + 1
    stored_kinds: dict[str, int] = {}
    for row in stored:
        stored_kinds[row[2]] = stored_kinds.get(row[2], 0) + 1
    return SelfCheck(
        symbol,
        harness_digest == stored_digest,
        len(harness),
        len(stored),
        harness_digest,
        stored_digest,
        harness_kinds,
        stored_kinds,
    )


# --- the database reads (SELECT only; every other query in this module is read-only too) ----------

_TRADIER_NAMES_SQL = """
SELECT symbol, min(day) AS first_day FROM (
    SELECT r.symbol, (r."timestamp" AT TIME ZONE 'UTC')::date AS day
    FROM ohlcv_raw r
    LEFT JOIN ohlcv_request q ON q.request_id = r.request_id
    WHERE r.vendor = 'tradier' AND r.timeframe = '1d'
      AND (q.caller IS NULL OR q.caller NOT LIKE 'test-%')
) served GROUP BY symbol ORDER BY symbol
"""

_DEPTH_CHANGE_SQL = """
SELECT "timestamp", config_value FROM config_history
WHERE config_key = $1 ORDER BY "timestamp" DESC LIMIT 1
"""

_REQUESTS_SQL = """
SELECT symbol, window_start, answered_at FROM ohlcv_request
WHERE source = 'ibkr' AND timeframe = '1d'
  AND outcome = ANY($1::text[]) AND answered_at > $2
"""

_TRADIER_ROWS_SQL = """
SELECT (r."timestamp" AT TIME ZONE 'UTC')::date AS day, r.close, r.volume
FROM ohlcv_raw r
LEFT JOIN ohlcv_request q ON q.request_id = r.request_id
WHERE r.symbol = $1 AND r.vendor = 'tradier' AND r.timeframe = '1d'
  AND (q.caller IS NULL OR q.caller NOT LIKE 'test-%')
ORDER BY r."timestamp"
"""

_IBKR_ROWS_SQL = """
SELECT (r."timestamp" AT TIME ZONE 'UTC')::date AS day, r.kind, r.close, r.volume
FROM ohlcv_raw r
LEFT JOIN ohlcv_request q ON q.request_id = r.request_id
WHERE r.symbol = $1 AND r.vendor = 'ibkr' AND r.timeframe = '1d'
  AND r.kind = ANY($2::text[])
  AND (q.caller IS NULL OR q.caller NOT LIKE 'test-%')
ORDER BY r."timestamp"
"""

_EMPTY_SQL = """
SELECT empty_from, empty_through FROM ohlcv_empty_history
WHERE symbol = $1 AND timeframe = '1d' AND provider = 'ibkr'
"""

_STORED_FIRST_SQL = """
SELECT min("timestamp" AT TIME ZONE 'UTC')::date AS first_day FROM market_data_ohlcv
WHERE symbol = $1 AND timeframe = '1d'
"""

# The self-check's stored side: post-D canonical rows and their non-quarantine flag rules.
_STORED_POST_D_SQL = """
SELECT "timestamp", vendor, kind, open, high, low, close, volume
FROM market_data_ohlcv
WHERE symbol = $1 AND timeframe = '1d' AND "timestamp" >= $2
ORDER BY "timestamp"
"""

_STORED_RULES_SQL = """
SELECT "timestamp", rule, quarantine FROM bar_quality_flag
WHERE symbol = $1 AND timeframe = '1d' AND "timestamp" >= $2
"""


async def open_readonly_connection() -> asyncpg.Connection:
    """A serial read-only connection; this script writes nothing, ever."""
    dsn = Settings().database_url.replace("postgresql+asyncpg://", "postgresql://")
    conn = await asyncpg.connect(dsn)
    await conn.execute("SET default_transaction_read_only = on")
    return conn


async def tradier_names(conn: asyncpg.Connection) -> list[tuple[str, date]]:
    return [(row["symbol"], row["first_day"]) for row in await conn.fetch(_TRADIER_NAMES_SQL)]


async def fetch_depth_change(conn: asyncpg.Connection) -> tuple[datetime, int]:
    """The depth change to 9800 days: the instant after which an IBKR ask counts as deep."""
    rows = await conn.fetch(_DEPTH_CHANGE_SQL, DEPTH_KEY)
    if not rows:
        raise SystemExit(f"config_history has no row for {DEPTH_KEY}")
    value = str(rows[0]["config_value"])
    if value != str(DEPTH_DAYS):
        raise SystemExit(f"{DEPTH_KEY} latest value is {value!r}, expected {DEPTH_DAYS}")
    return rows[0]["timestamp"], int(value)


async def run_readiness(conn: asyncpg.Connection, today: date | None = None) -> dict[str, Any]:
    depth_at, depth_days = await fetch_depth_change(conn)
    today = today or datetime.now(UTC).date()
    names = await tradier_names(conn)
    asks: dict[str, list[tuple[date, datetime]]] = {}
    for row in await conn.fetch(_REQUESTS_SQL, ["bars", "no_data"], depth_at):
        asks.setdefault(row["symbol"], []).append((row["window_start"].date(), row["answered_at"]))
    rows = [
        NameReadiness(
            symbol,
            first_day,
            readiness_answered(first_day, asks.get(symbol, ()), depth_at, today),
        )
        for symbol, first_day in names
    ]
    answered, unanswered = classify_readiness(rows)
    return {
        "mode": "readiness",
        "today": today.isoformat(),
        "depth_key": DEPTH_KEY,
        "depth_changed_at": depth_at.isoformat(),
        "depth_days": depth_days,
        "n_tradier_names": len(rows),
        "n_answered": len(answered),
        "n_unanswered": len(unanswered),
        "unanswered": unanswered,
    }


async def run_measure(
    conn: asyncpg.Connection, symbols: Sequence[str] | None = None
) -> dict[str, Any]:
    names = [s for s, _f in await tradier_names(conn)] if symbols is None else list(symbols)
    measures: list[NameMeasure] = []
    for i, symbol in enumerate(names, 1):
        tradier = [
            (row["day"], row["close"], row["volume"])
            for row in await conn.fetch(_TRADIER_ROWS_SQL, symbol)
        ]
        if not tradier:
            continue
        ibkr = [
            (row["day"], row["kind"], row["close"], row["volume"])
            for row in await conn.fetch(_IBKR_ROWS_SQL, symbol, list(IBKR_RAW_KINDS))
        ]
        empty = [
            (row["empty_from"], row["empty_through"])
            for row in await conn.fetch(_EMPTY_SQL, symbol)
        ]
        stored = await conn.fetchrow(_STORED_FIRST_SQL, symbol)
        measures.append(
            measure_name(symbol, tradier, ibkr, empty, stored["first_day"] if stored else None)
        )
        if i % 100 == 0:
            print(f"measure: {i}/{len(names)}", file=sys.stderr, flush=True)
    return {
        "mode": "measure",
        "n_names": len(measures),
        "n_names_with_residue": sum(1 for m in measures if m.n_residue),
        "n_residue_sessions": sum(m.n_residue for m in measures),
        "n_venue_sessions": sum(m.n_venue_sessions for m in measures),
        "n_first_bar_changes": sum(1 for m in measures if m.first_bar_after != m.first_bar_current),
        "names": [_jsonable(m) for m in measures],
    }


async def run_prove(
    conn: asyncpg.Connection,
    *,
    sample: int = DEFAULT_SELF_CHECK_SAMPLE,
    symbols: Sequence[str] | None = None,
) -> dict[str, Any]:
    """The proof pass: the unchanged rule over every Tradier name's inputs minus vendor
    tradier, the per-name verdicts, and the post-D digest self-check on the first `sample`
    names (deterministic: the alphabetical name list)."""
    names = [s for s, _f in await tradier_names(conn)] if symbols is None else list(symbols)
    apr = await load_apr_dict_async(conn, ["threshold.%"])
    params = await read_daily_params(conn, apr)
    d_utc = datetime(D.year, D.month, D.day, tzinfo=UTC)
    proofs: list[NameProof] = []
    checks: list[SelfCheck] = []
    for i, symbol in enumerate(names, 1):
        result = None
        error: BaseException | None = None
        try:
            observations, splits = await read_daily_inputs(conn, symbol)
            kept = [o for o in observations if o.route != ROUTE_TRADIER]
            result = derive_daily_v2(
                kept,
                params.policy,
                splits,
                symbol=symbol,
                basis_window_sessions=params.window,
                basis_tolerance_bp=params.tolerance_bp,
            )
        except Exception as error_found:
            error = error_found
        ibkr_rows = await conn.fetch(_IBKR_ROWS_SQL, symbol, list(IBKR_RAW_KINDS))
        smart_dates = [row["day"] for row in ibkr_rows if row["kind"] == SMART_KIND]
        venue_dates = [row["day"] for row in ibkr_rows if row["kind"] in VENUE_ROUTE_KINDS]
        bars = list(result.bars) if result is not None else []
        proofs.append(
            classify_proof(
                symbol, smart_dates=smart_dates, venue_dates=venue_dates, bars=bars, error=error
            )
        )
        if i <= sample:
            stored_rows = [
                (
                    row["timestamp"],
                    row["vendor"],
                    row["kind"],
                    row["open"],
                    row["high"],
                    row["low"],
                    row["close"],
                    row["volume"],
                )
                for row in await conn.fetch(_STORED_POST_D_SQL, symbol, d_utc)
            ]
            rules: dict[int, set[str]] = {}
            for row in await conn.fetch(_STORED_RULES_SQL, symbol, d_utc):
                if not row["quarantine"]:
                    rules.setdefault(int(row["timestamp"].timestamp()), set()).add(row["rule"])
            flags: dict[date, set[str]] = {}
            if result is not None:
                for flag in result.flags:
                    if flag.bar_date >= D:
                        flags.setdefault(flag.bar_date, set()).add(flag.rule)
            checks.append(
                digest_self_check(
                    symbol,
                    [b for b in bars if b.bar_date >= D],
                    flags,
                    stored_rows,
                    rules,
                )
            )
        if i % 25 == 0:
            print(f"prove: {i}/{len(names)}", file=sys.stderr, flush=True)
    not_proven = [p.symbol for p in proofs if not p.proven]
    return {
        "mode": "prove",
        "n_names": len(proofs),
        "n_proven": sum(1 for p in proofs if p.proven),
        "n_not_proven": len(not_proven),
        "not_proven": not_proven,
        "n_venue_moved": sum(1 for p in proofs if p.venue_moved),
        "n_exceptions": sum(1 for p in proofs if p.exception is not None),
        "self_check_sample": len(checks),
        "self_check_equal": sum(1 for c in checks if c.equal),
        "names": [_jsonable(p) for p in proofs],
        "self_checks": [_jsonable(c) for c in checks],
    }


# --- output helpers and the CLI -------------------------------------------------------------------


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, date):
        return value.isoformat()
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if hasattr(value, "__dict__") and not isinstance(value, type):
        return _jsonable(vars(value))
    return str(value)


def _render_report(args: argparse.Namespace) -> int:
    """Render the measure and prove payloads as the owner-facing record."""
    measure = json.loads(Path(args.measure_json).read_text()) if args.measure_json else None
    prove = json.loads(Path(args.prove_json).read_text()) if args.prove_json else None
    lines: list[str] = [
        "# Tradier residue and the no-Tradier proof (plan 191-19)",
        "",
        f"Generated {datetime.now(UTC).isoformat()} by scripts/ops/bars/ops_tradier_residue.py"
        " (read-only; the database was not touched).",
        "",
    ]
    if measure is not None:
        lines += [
            "## Residue",
            "",
            f"- names measured: {measure['n_names']}",
            f"- names with Tradier-only sessions: {measure['n_names_with_residue']}",
            f"- Tradier-only sessions total: {measure['n_residue_sessions']}",
            f"- sessions with a venue-route answer: {measure['n_venue_sessions']}",
            f"- names whose first 1d bar moves: {measure['n_first_bar_changes']}",
            "",
            "| symbol | tradier | residue | residue span | first bar now | first bar after |"
            " close bp p50 | vol ratio p50 |",
            "|---|---|---|---|---|---|---|---|",
        ]
        for m in measure["names"]:
            if m["n_residue"] or m["first_bar_after"] != m["first_bar_current"]:
                lines.append(
                    f"| {m['symbol']} | {m['n_tradier']} | {m['n_residue']} |"
                    f" {m['residue_first']}..{m['residue_last']} |"
                    f" {m['first_bar_current']} | {m['first_bar_after']} |"
                    f" {m['close_bp_median']} | {m['volume_ratio_median']} |"
                )
        lines.append("")
    if prove is not None:
        lines += [
            "## Proof",
            "",
            f"- names proven: {prove['n_proven']} of {prove['n_names']}",
            f"- names not proven: {prove['n_not_proven']}"
            f" (venue-moved: {prove['n_venue_moved']}, rule exceptions: {prove['n_exceptions']})",
            f"- harness self-check: {prove['self_check_equal']} of"
            f" {prove['self_check_sample']} sampled names digest-equal to stored post-D rows",
            "",
        ]
        for p in prove["names"]:
            if not p["proven"]:
                lines.append(
                    f"- {p['symbol']}: {len(p['unserved'])} unserved"
                    f" ({p['unserved_smart']} smart, {p['unserved_venue_only']} venue-only,"
                    f" venue_moved={p['venue_moved']})"
                    + (f"; exception: {p['exception']}" if p["exception"] else "")
                )
        lines.append("")
    out = Path(args.out) if args.out else Path(DEFAULT_REPORT_PATH)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines))
    print(f"report written to {out}")
    return 0


async def _run_mode(args: argparse.Namespace) -> dict[str, Any]:
    conn = await open_readonly_connection()
    try:
        if args.readiness:
            return await run_readiness(conn)
        if args.measure:
            return await run_measure(conn, args.symbols)
        return await run_prove(conn, sample=args.sample, symbols=args.symbols)
    finally:
        await conn.close()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--readiness", action="store_true", help="the gap-fill cycle gate")
    mode.add_argument("--measure", action="store_true", help="per-name residue measurement")
    mode.add_argument("--prove", action="store_true", help="the no-Tradier fallback proof")
    mode.add_argument("--report", action="store_true", help="render the report from payloads")
    parser.add_argument("--out", default=None, help="write the full JSON payload here")
    parser.add_argument("--symbols", nargs="+", default=None, help="limit to these names")
    parser.add_argument("--sample", type=int, default=DEFAULT_SELF_CHECK_SAMPLE)
    parser.add_argument("--measure-json", default=None, help="report input")
    parser.add_argument("--prove-json", default=None, help="report input")
    args = parser.parse_args(argv)

    if args.report:
        return _render_report(args)

    payload = asyncio.run(_run_mode(args))
    if args.out:
        Path(args.out).write_text(json.dumps(payload, indent=1))
    summary = {k: v for k, v in payload.items() if k not in ("names", "self_checks")}
    if "unanswered" in summary:
        summary["unanswered"] = summary["unanswered"][:50]
        summary["unanswered_truncated"] = payload["n_unanswered"] > 50
    print(json.dumps(summary))
    if payload.get("mode") == "readiness" and payload["n_unanswered"]:
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
