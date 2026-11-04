"""S0: the only research node that reads Postgres. Read-only, content-hashed.

Every connection runs with default_transaction_read_only = on. Prices come from
market_data_ohlcv_tradeable (never the raw table: synthetic and carry-forward bars are not
bars). `end_exclusive` may not pass alpha.validation.oos_start, checked before any fetch.

Sessions are the dates on which any universe symbol has a bar (America/New_York dates
intraday), and every one must be an NYSE trading day (src/core/market_calendar.py): a bar on a
weekend or holiday raises. Intraday slots are the times of day present on at least half of those sessions, which is the regular
session's bar schedule. A bar at any other time is dropped and counted in the manifest; a slot
with no bar is NaN. The grid is built from data, so a tf's schedule is never hand-typed.
"""

from __future__ import annotations

import asyncio
import dataclasses
import hashlib
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

import asyncpg
import numpy as np
import pandas as pd

from src.config.classification_service import DEFAULT_SCHEME, SECTOR_LEVEL
from src.core.database_manager import create_pool
from src.core.market_calendar import get_market_calendar
from src.intelligence.bars.label_inputs import load_label_inputs
from src.intelligence.bars.sessions import nyse_sessions
from src.intelligence.features.contract.registry import default_registry
from src.intelligence.research import (
    align,
    clock,
    data_quality,
    feature_inputs,
    kernel_source,
    store,
)
from src.intelligence.research import dividends as dividends_mod
from src.intelligence.research import panel as panel_mod
from src.intelligence.research.panel import Panel
from src.intelligence.statistics.feature_coverage import SymbolCounts

_POOL_SIZE = 6
_EXCHANGE_TZ = "America/New_York"
_EXCHANGE = "NYSE"
_MINUTES_PER_DAY = 1440
# Structural, not tunable: a time of day is part of the regular schedule when it occurs on at
# least this share of sessions (a majority), which excludes stray pre- and post-market bars.
_SLOT_MIN_SESSION_SHARE = 0.5

PRICE_SOURCE = "market_data_ohlcv_tradeable"  # the manifest's "source" on every real snapshot

_OOS_START_SQL = (
    "SELECT config_value::timestamptz FROM config_state "
    "WHERE config_key = 'alpha.validation.oos_start'"
)
# Plan 184-08: symbols per feature-read chunk (migration 564), and the timestamps pass that builds a
# finer source's one grid axis before any chunk is read.
_CHUNK_SQL = (
    "SELECT config_value::int FROM config_state "
    "WHERE config_key = 'infra.research.snapshot_feature_chunk_symbols'"
)
_AXIS_SQL = (
    "SELECT timestamp, close FROM market_data_ohlcv_tradeable "
    "WHERE symbol = $1 AND timeframe = $2 AND timestamp >= $3 AND timestamp < $4 "
    "ORDER BY timestamp"
)
_KNOWN_SQL = "SELECT symbol FROM instruments WHERE symbol = ANY($1)"
_BARS_SQL = (
    "SELECT timestamp, open, close, volume{extra} FROM market_data_ohlcv_tradeable "
    "WHERE symbol = $1 AND timeframe = $2 AND timestamp >= $3 AND timestamp < $4 "
    "ORDER BY timestamp"
)

# Plan 184-07 (B1d): the (vendor, kind) pairs serving a 15m or 1h span, a separate pinned query so
# the bar SELECT keeps its exact text.
_VENDOR_SET_SQL = (
    "SELECT DISTINCT vendor, kind FROM market_data_ohlcv_tradeable "
    "WHERE timeframe = $1 AND symbol = ANY($2) AND timestamp >= $3 AND timestamp < $4"
)

# Plan 187-15: each name's SCH sector (the level-SECTOR_LEVEL ancestor of its classification)
# over every assignment the span touches. Assignments never overlap (exclusion constraint), so a
# session is covered by at most one; sector_grid refuses a traded session covered by none.
_SECTOR_SQL = (
    "SELECT ic.symbol, anc.code, anc.name, ic.valid_from, ic.valid_to "
    "FROM instrument_classification ic "
    "JOIN classification_node n ON (n.scheme, n.code) = (ic.scheme, ic.code) "
    "JOIN classification_node anc ON anc.scheme = ic.scheme AND anc.code = n.path[$2] "
    "WHERE ic.scheme = $1 AND ic.symbol = ANY($3) AND ic.valid_from < $5 "
    "AND (ic.valid_to IS NULL OR ic.valid_to > $4)"
)

# Dividends (todo 428, migrations 376 and 379): Yahoo's coverage span decides known vs unknown;
# events come from the reconciled view as both sources' facts, resolved by
# dividends.resolve_event (agreement, dispute, one source).
_DIV_COVERAGE_SQL = (
    "SELECT symbol, covered_from, covered_to FROM dividend_event_coverage "
    "WHERE source = 'yahoo' AND symbol = ANY($1)"
)
# The writer's dispute parameters (dividends.DisputeRule), read once per snapshot and recorded in
# its manifest, so research applies the writer's definition and a snapshot stays reproducible.
_DISPUTE_RULE_SQL = (
    "SELECT config_key, config_value FROM config_state WHERE config_key IN "
    "('threshold.dividend_event.source_yield_rel_tolerance', "
    "'threshold.dividend_event.noise_margin')"
)
_DIV_EVENTS_SQL = (
    "SELECT symbol, ex_date, yahoo_yield, ibkr_yield, ibkr_prev_close "
    "FROM dividend_events_reconciled WHERE symbol = ANY($1) AND ex_date >= $2 AND ex_date < $3"
)

# Data-quality pinning (todo 501): the content digest ranges the span touches and the latest
# bar_integrity verdict per subject and metric (integrity_monitor keeps every evaluation).
_DIGESTS_SQL = (
    "SELECT symbol, range_start, digest FROM bar_content_digest_current "
    "WHERE symbol = ANY($1) AND timeframe = $2 AND range_start < $3 AND range_end >= $4"
)
_VERDICTS_SQL = (
    "SELECT DISTINCT ON (subject, metric_name) subject, metric_name, passed "
    "FROM integrity_monitor WHERE monitor_type = 'bar_integrity' AND subject = ANY($1) "
    "ORDER BY subject, metric_name, evaluated_at DESC"
)

# instruments' universe eligibility columns (migration 337). universe_symbols accepts only these,
# so a column name never comes from caller text.
UNIVERSE_DIMENSIONS = ("compute_eligible", "compute_eligible_1d", "live_tradeable")

# ts[ns UTC], o, c, v, then one array per requested optional bar field (high, low) in order.
Bars = dict[str, tuple[np.ndarray, ...]]


async def read_only_pool(dsn: str) -> asyncpg.Pool:
    return await create_pool(
        dsn,
        pool_name="research_read_only",
        min_size=1,
        max_size=_POOL_SIZE,
        server_settings={"default_transaction_read_only": "on"},
    )


async def _fetch_bars(pool, sql: str, sym: str, tf: str, lo: datetime, hi: datetime):
    """(symbol, bars tuple or None when the symbol has no bars in [lo, hi))."""
    rows = await pool.fetch(sql, sym, tf, lo, hi)
    if not rows:
        return sym, None
    ts, *values = zip(*rows)  # one pass over the records
    stamps = pd.DatetimeIndex(ts).tz_convert(UTC).tz_localize(None)
    return sym, (
        stamps.values.astype("datetime64[ns]"),
        *(np.array(x, dtype=float) for x in values),
    )


def build_grid(bars: Bars, tf: str, fields: tuple[str, ...] = ()) -> Panel:
    """Pure: per-symbol bars -> a dense Panel on the session grid. Symbols keep input order.
    `fields` names the optional bar arrays each tuple carries after volume (high, low)."""
    symbols = tuple(bars)
    stamps = {s: pd.DatetimeIndex(b[0]).tz_localize(UTC) for s, b in bars.items()}
    if tf == "1d":
        days = {
            s: ts.normalize().tz_localize(None).values.astype("datetime64[D]")
            for s, ts in stamps.items()
        }
        sessions = np.unique(np.concatenate(list(days.values())))
        _reject_non_trading_days(sessions)
        keys = {s: np.searchsorted(sessions, d) for s, d in days.items()}
        timestamps, bars_per_session, dropped = sessions, 1, 0
        slot_of = {s: np.zeros(len(d), dtype=int) for s, d in days.items()}
    else:
        local = {s: ts.tz_convert(_EXCHANGE_TZ) for s, ts in stamps.items()}
        dates = {
            s: t.normalize().tz_localize(None).values.astype("datetime64[D]")
            for s, t in local.items()
        }
        tods = {s: (t - t.normalize()).values.astype("timedelta64[m]") for s, t in local.items()}
        sessions = np.unique(np.concatenate(list(dates.values())))
        _reject_non_trading_days(sessions)
        # Sessions on which each time of day occurs, in any symbol: distinct (date, minute) keys.
        keys_dm = np.unique(
            np.concatenate(
                [
                    dates[s].astype(np.int64) * _MINUTES_PER_DAY + tods[s].astype(np.int64)
                    for s in symbols
                ]
            )
        )
        tod_minutes, n_sessions_seen = np.unique(keys_dm % _MINUTES_PER_DAY, return_counts=True)
        slots = tod_minutes[n_sessions_seen >= _SLOT_MIN_SESSION_SHARE * len(sessions)].astype(
            "timedelta64[m]"
        )
        bars_per_session = len(slots)
        keys, slot_of, dropped = {}, {}, 0
        for s in symbols:
            on_grid = np.isin(tods[s], slots)
            dropped += int((~on_grid).sum())
            keys[s] = np.where(on_grid, np.searchsorted(sessions, dates[s]), -1)
            slot_of[s] = np.where(on_grid, np.searchsorted(slots, tods[s]), -1)
        local_rows = pd.DatetimeIndex((sessions[:, None] + slots[None, :]).ravel()).tz_localize(
            _EXCHANGE_TZ
        )
        timestamps = local_rows.tz_convert(UTC).tz_localize(None).values.astype("datetime64[m]")

    n, m = len(sessions) * bars_per_session, len(symbols)
    names = ("open", "close", "volume", *fields)
    arrays = {f: np.full((n, m), np.nan) for f in names}
    for j, s in enumerate(symbols):
        if len(bars[s]) != 1 + len(names):
            raise ValueError(f"{s}: {len(bars[s]) - 1} bar arrays for fields {names}")
        keep = keys[s] >= 0
        rows = keys[s][keep] * bars_per_session + slot_of[s][keep]
        if len(np.unique(rows)) != len(rows):
            raise ValueError(f"{s}: two bars map to one grid slot")
        for f, values in zip(names, bars[s][1:], strict=True):
            arrays[f][rows, j] = np.asarray(values, dtype=float)[keep]
    valid = np.isfinite(arrays["close"]).any(axis=1)
    return Panel(
        tf=tf,
        symbols=symbols,
        timestamps=timestamps,
        bars_per_session=bars_per_session,
        valid=valid,
        manifest={"dropped_off_grid_bars": dropped, "n_sessions": int(len(sessions))},
        **arrays,
    )


def sector_grid(
    sessions: np.ndarray, symbols: tuple[str, ...], traded: np.ndarray, rows: list[tuple]
) -> tuple[np.ndarray, list[list[str]]]:
    """Pure (plan 187-15): ([n_sessions, m] int16 index into the code table, the code table as
    [code, name] pairs sorted by code). `rows` are (symbol, sector code, sector name,
    valid_from, valid_to) assignments, half open [valid_from, valid_to). A session in which a
    name traded (`traded` [n_sessions, m]) must be covered by exactly one assignment, or this
    raises: a sector is never assumed for a session the classification history does not cover.
    A session the name did not trade is -1. Codes are point in time (a node's path never
    changes; a reparent mints a new code); the table's names are as read when S0 ran."""
    dates = np.asarray(sessions, dtype="datetime64[D]")
    table = sorted({(code, name) for _, code, name, _, _ in rows})
    index = {code: i for i, (code, _) in enumerate(table)}
    column = {sym: j for j, sym in enumerate(symbols)}
    out = np.full((len(dates), len(symbols)), -1, dtype=np.int16)
    covered = np.zeros(out.shape, dtype=np.int16)
    for sym, code, _name, valid_from, valid_to in rows:
        j = column.get(sym)
        if j is None:
            continue
        inside = dates >= np.datetime64(valid_from, "D")
        if valid_to is not None:
            inside &= dates < np.datetime64(valid_to, "D")
        out[inside, j] = index[code]
        covered[inside, j] += 1
    bad = traded & (covered != 1)
    if bad.any():
        i, j = np.argwhere(bad)[0]
        raise ValueError(
            f"sector_pit: {int(bad.sum())} traded (session, name) cells without exactly one SCH "
            f"classification, first {symbols[j]} on {dates[i]}"
        )
    return np.where(traded, out, -1).astype(np.int16), [list(t) for t in table]


def warmup_fetch_start(start: datetime, tf: str, sessions: int) -> datetime:
    """Plan 184-07 (B1c): where S0 starts fetching so `sessions` whole NYSE sessions precede
    `start`: the open of the `sessions`-th session before it (the session date's midnight UTC on
    1d, where bars are stamped by date). `sessions == 0` returns `start` unchanged."""
    if sessions < 0:
        raise ValueError(f"warmup_sessions must be >= 0, got {sessions}")
    if sessions == 0:
        return start
    day = start.date()
    window = sessions * 7 // 5 + 14  # calendar days; widened until enough sessions exist
    while True:
        before = [d for d in nyse_sessions(day - timedelta(days=window), day) if d < day]
        if len(before) >= sessions:
            break
        window *= 2
    first = before[-sessions]
    if tf == "1d":
        return datetime(first.year, first.month, first.day, tzinfo=UTC)
    return nyse_sessions(first, first)[first][0]


def session_dates(panel: Panel) -> np.ndarray:
    """datetime64[D] [S], each session's exchange-local date (the dates build_grid keyed on)."""
    first = panel.timestamps[:: panel.bars_per_session]
    if panel.bars_per_session == 1:
        return np.asarray(first).astype("datetime64[D]")
    local = pd.DatetimeIndex(first).tz_localize(UTC).tz_convert(_EXCHANGE_TZ)
    return local.normalize().tz_localize(None).values.astype("datetime64[D]")


def utc(dt: datetime) -> datetime:
    """A naive bound is UTC; an explicit offset is kept."""
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def _reject_non_trading_days(sessions: np.ndarray) -> None:
    calendar = get_market_calendar()
    bad = [d for d in sessions.tolist() if not calendar.is_trading_day(_EXCHANGE, d)]
    if bad:
        raise ValueError(f"bars on {len(bad)} non-{_EXCHANGE}-trading dates, e.g. {bad[:5]}")


async def universe_symbols(dsn: str, dimension: str) -> list[str]:
    """Symbols whose instruments row has `dimension` true, sorted (a pinned universe query)."""
    if dimension not in UNIVERSE_DIMENSIONS:
        raise ValueError(f"unknown universe dimension {dimension!r}; one of {UNIVERSE_DIMENSIONS}")
    pool = await read_only_pool(dsn)
    try:
        rows = await pool.fetch(
            f"SELECT symbol FROM instruments WHERE {dimension} = true ORDER BY symbol"
        )
    finally:
        await pool.close()
    return [r["symbol"] for r in rows]


# Family 2's members' universe rule (docs/plans/2026-09-25-family2-overnight-intraday-
# prereg.md section 2, B3): current level-1 node EQ, no current
# international exposure tag. Pinned SQL, never built from caller text.
_US_SESSION_EQUITY_SQL = """
SELECT ic.symbol
FROM instrument_classification ic
JOIN classification_node n ON n.scheme = ic.scheme AND n.code = ic.code
WHERE ic.scheme = 'indicagent_v1' AND ic.valid_to IS NULL AND n.path[1] = 'EQ'
  AND NOT EXISTS (
    SELECT 1 FROM instrument_tags t
    WHERE t.symbol = ic.symbol AND t.valid_to IS NULL
      AND t.tag IN ('intl_developed', 'intl_em')
  )
ORDER BY ic.symbol
"""


# The daily residual family's members' universe (docs/plans/2026-10-27-daily-residual-momentum-
# reversal-prereg.md section 2, B1): daily-eligible names created on or after the 2026-09-13
# screen, so none of the 231 symbols it measured, and none of the 13-symbol sleeve the
# 2026-09-24 TSMOM look read (scripts/research/determinism/config.py; two of them, EMLC and
# VIXY, were created after the cutoff). Pinned SQL, never built from caller text.
DAILY_UNSEEN_CUTOFF = "2026-09-13"
DAILY_SEEN_SLEEVE = (
    "GLD",
    "DBA",
    "DBB",
    "DBC",
    "URA",
    "TLT",
    "UUP",
    "VIXY",
    "EMLC",
    "HYG",
    "XOM",
    "DHI",
    "PGR",
)
# The screen ran on the 231 then-active instruments, all created before the cutoff. Every
# instrument created before it (253, active or not, 2026-10-27) is excluded; the rule is exact
# only while that set reproduces, so a different set (a rewritten created_at, a deleted row)
# refuses (B1). Deactivating a name never changes it.
DAILY_SEEN_BEFORE_CUTOFF_SHA256 = "60adb95610903c45b7f14700485ae8e6fec16c29b5b398368617b137eff5d3d2"
_DAILY_UNSEEN_SQL = """
SELECT symbol FROM instruments
WHERE compute_eligible_1d AND is_active AND created_at >= $1
  AND symbol <> ALL($2::text[])
ORDER BY symbol
"""
_DAILY_SEEN_SQL = """
SELECT symbol FROM instruments WHERE created_at < $1 ORDER BY symbol
"""


async def daily_unseen_symbols(dsn: str) -> list[str]:
    """The daily residual family's members' universe, sorted (B1). Raises when the screened
    names no longer reproduce exactly."""
    pool = await read_only_pool(dsn)
    try:
        # Midnight UTC, whatever the session's TimeZone.
        cutoff = datetime.fromisoformat(DAILY_UNSEEN_CUTOFF).replace(tzinfo=UTC)
        seen = [r["symbol"] for r in await pool.fetch(_DAILY_SEEN_SQL, cutoff)]
        rows = await pool.fetch(_DAILY_UNSEEN_SQL, cutoff, list(DAILY_SEEN_SLEEVE))
    finally:
        await pool.close()
    digest = hashlib.sha256("\n".join(seen).encode()).hexdigest()
    if digest != DAILY_SEEN_BEFORE_CUTOFF_SHA256:
        raise ValueError(
            f"the {len(seen)} instruments created before {DAILY_UNSEEN_CUTOFF} are not the pinned "
            "set: the daily_unseen rule no longer excludes the screen exactly (B1)"
        )
    return [r["symbol"] for r in rows]


async def us_session_equity_symbols(dsn: str) -> list[str]:
    """The members' universe rule's names, sorted (B3)."""
    pool = await read_only_pool(dsn)
    try:
        rows = await pool.fetch(_US_SESSION_EQUITY_SQL)
    finally:
        await pool.close()
    return [r["symbol"] for r in rows]


# ---------------------------------------------------------------------------
# Plan 184-08: feature and kernel members on source timeframes
# ---------------------------------------------------------------------------

_TF_MINUTES = {**clock.TF_MINUTES, clock.DAILY_TF: _MINUTES_PER_DAY}
_AXIS = "__axis__"  # the pseudo-symbol that gives every chunk panel the one shared grid
_PROBE_SYMBOLS = 3


@dataclasses.dataclass(frozen=True)
class MemberSourceRequest:
    """One research member's source input: a stored feature column or a research kernel."""

    member: str
    kind: Literal["feature", "kernel"]
    column: str
    windows: Mapping[str, int] | None
    max_age_rows: int
    max_gap_rows: int | None
    coverage_floor: float | None


@dataclasses.dataclass(frozen=True)
class SourceRequest:
    """All members reading one source timeframe, with that tf's one config-hash pin."""

    tf: str
    pinned_config_projection_hash: str
    members: tuple[MemberSourceRequest, ...]
    need_high_low: bool


def _check_requests(sources: Sequence[SourceRequest], registry) -> None:
    """Refuse every bad column before any SQL is sent."""
    seen = set()
    for req in sources:
        if req.tf not in _TF_MINUTES:
            raise ValueError(f"unknown source tf {req.tf!r}")
        if req.tf in seen:
            raise ValueError(f"two source requests for tf {req.tf}: one pin per tf")
        seen.add(req.tf)
        stored = [m.column for m in req.members if m.kind == "feature"]
        if stored:
            try:
                feature_inputs.check_columns(sorted(set(stored)), registry, req.tf)
            except feature_inputs.FeatureInputRefused as error:
                raise ValueError(str(error)) from error
        for m in req.members:
            if m.kind == "kernel" and m.max_gap_rows is None:
                raise ValueError(f"kernel member {m.member} needs max_gap_rows")


async def _tf_configs(
    pool, sources: Sequence[SourceRequest], symbols: Sequence[str], spans, registry
) -> dict[str, dict]:
    """tf -> {"block": provenance block, "config": FeatureFactoryConfig}; `spans` maps tf to its
    (start, end). Refuses (B1f, B1j) before any bar or feature row is fetched."""
    out = {}
    for req in sorted(sources, key=lambda r: r.tf):
        start, end = spans[req.tf]
        rows = await pool.fetch(
            feature_inputs.PROVENANCE_SQL,
            list(feature_inputs.PROVENANCE_TARGET_TABLES),
            req.tf,
            start,
            end,
        )
        batches = [dict(r) for r in rows]
        try:
            block = feature_inputs.provenance_pin(
                batches,
                symbols=sorted(symbols),
                span_start=start,
                span_end=end,
                pinned_config_projection_hash=req.pinned_config_projection_hash,
            )
            feature_inputs.refuse_regime_columns(
                [m.column for m in req.members if m.kind == "feature"], registry, batches
            )
            out[req.tf] = {"block": block, "config": feature_inputs.feature_config(block)}
        except feature_inputs.FeatureInputRefused as error:
            raise ValueError(str(error)) from error
    return out


async def source_configs(
    dsn: str,
    sources: Sequence[SourceRequest],
    start: str,
    end: str,
    *,
    symbols: Sequence[str],
) -> dict[str, dict]:
    """The verified provenance block and FeatureFactoryConfig per source tf over [start, end),
    before any bar is fetched, so the runner can compute member memory and the warmup prefix
    from them (184-09). `symbols` are the names the provenance must cover."""
    registry = default_registry()
    _check_requests(sources, registry)
    lo, hi = utc(datetime.fromisoformat(start)), utc(datetime.fromisoformat(end))
    pool = await read_only_pool(dsn)
    try:
        return await _tf_configs(
            pool, sources, symbols, {r.tf: (lo, hi) for r in sources}, registry
        )
    finally:
        await pool.close()


@dataclasses.dataclass
class _Ctx:
    pool: Any
    registry: Any
    book: Panel
    book_closes: np.ndarray
    scored_lo: datetime
    hi: datetime
    warmup_sessions: int
    chunk: int


def _scored_rows(grid_ts: np.ndarray, scored_lo: datetime) -> np.ndarray:
    cut = np.datetime64(scored_lo.astimezone(UTC).replace(tzinfo=None), "ns")
    return np.asarray(grid_ts).astype("datetime64[ns]") >= cut


def _floors(members: Sequence[MemberSourceRequest], key) -> dict[str, float | None]:
    """The strictest declared coverage floor per key (None when no member declares one)."""
    out: dict[str, float | None] = {}
    for m in members:
        floor = m.coverage_floor
        current = out.get(key(m))
        out[key(m)] = (
            floor if current is None else (current if floor is None else max(current, floor))
        )
    return out


def _block_info(tf: str, kind: str, tried: dict) -> dict:
    return {
        "tf": tf,
        "relation": kind,
        "config_hash": tried["block"]["projection_hash"],
        "projection": tried["block"]["projection"],
        "provenance": tried["block"],
    }


def _feature_rows_to_grid(rows, grid: Panel, symbols, columns, registry, config, scored):
    """Scatter, mask warmup and return {column: float32 [n, k]}, present, counts, per-column
    manifest pieces. Pure over fetched rows."""
    arrays, unmatched = feature_inputs.scatter_rows(rows, grid.timestamps, symbols, columns)
    present = feature_inputs.present_mask(rows, grid.timestamps, symbols)
    masked, warm = {}, {}
    for column in columns:
        memory = feature_inputs.column_memory_bars(column, config, registry)
        masked[column], warm[column] = feature_inputs.warmup_mask(
            arrays[column], memory, present=present
        )
    return masked, present & scored[:, None], unmatched, warm


async def _whole_source(
    ctx: _Ctx, req: SourceRequest, tried: dict
) -> tuple[dict, dict, Panel | None]:
    """A source at the book's clock or coarser: its arrays on its own grid (the book's when equal)
    and its manifest block; the child panel is returned for the caller to save."""
    tf, registry, config = req.tf, ctx.registry, tried["config"]
    symbols = ctx.book.symbols
    if tf == ctx.book.tf:
        grid, child = ctx.book, None
    else:
        grid = await _read_source_grid(ctx, tf, req.need_high_low, symbols)
        child = grid
    lo = warmup_fetch_start(ctx.scored_lo, tf, ctx.warmup_sessions)
    scored = _scored_rows(grid.timestamps, ctx.scored_lo)
    arrays: dict[str, np.ndarray] = {}
    info = _block_info(tf, "equal" if child is None else "coarser", tried)
    info["columns"], info["unmatched_rows"] = {}, 0
    stored = [m for m in req.members if m.kind == "feature"]
    if stored:
        columns = sorted({m.column for m in stored})
        sql = feature_inputs.feature_select_sql(columns, registry, tf=tf)
        rows = await ctx.pool.fetch(sql, tf, list(symbols), lo, ctx.hi)
        masked, present, unmatched, warm = _feature_rows_to_grid(
            rows, grid, symbols, columns, registry, config, scored
        )
        floors = _floors(stored, lambda m: m.column)
        info["unmatched_rows"] = unmatched
        for column in columns:
            cov = None
            if floors[column] is not None:
                cov = _coverage(
                    feature_inputs.symbol_counts(masked[column], symbols, present=present),
                    column,
                    tf,
                    floors[column],
                )
            info["columns"][column] = {"warmup": warm[column], "coverage": cov}
            arrays[feature_inputs.feature_array_name(tf, column)] = masked[column]
    for m in (k for k in req.members if k.kind == "kernel"):
        result = _run_kernel(grid, m, config, req.need_high_low)
        values = result.values[m.column]
        cov = None
        if m.coverage_floor is not None:
            present = np.isfinite(np.asarray(grid.close)) & scored[:, None]
            cov = _coverage(
                feature_inputs.symbol_counts(values, symbols, present=present),
                m.column,
                tf,
                m.coverage_floor,
            )
        arrays[f"kernel__{tf}__{m.member}"] = values
        info["columns"][m.member] = {
            "memory_bars": result.memory_bars[m.column],
            "gap_masked": result.gap_masked[m.column],
            "warmup_masked": result.warmup_masked[m.column],
            "coverage": cov,
        }
    return arrays, info, child


def _coverage(counts, column: str, tf: str, floor: float) -> dict:
    try:
        return feature_inputs.coverage_from_counts(counts, feature=column, tf=tf, floor=floor)
    except feature_inputs.FeatureInputRefused as error:
        raise ValueError(str(error)) from error


def _run_kernel(grid: Panel, m: MemberSourceRequest, config, need_high_low: bool):
    try:
        return kernel_source.kernel_source(
            grid,
            [m.column],
            dict(m.windows or {}),
            config,
            max_gap_rows=int(m.max_gap_rows),  # type: ignore[arg-type]
            high=grid.high if need_high_low else None,
            low=grid.low if need_high_low else None,
        )
    except kernel_source.KernelSourceRefused as error:
        raise ValueError(str(error)) from error


def _source_fields(need_high_low: bool) -> tuple[str, ...]:
    return panel_mod.OPTIONAL_BAR_FIELDS if need_high_low else ()


def _bars_sql(fields: tuple[str, ...]) -> str:
    return _BARS_SQL.format(extra="".join(f", {f}" for f in fields))


def _empty_bars(n_fields: int):
    return (np.array([], dtype="datetime64[ns]"), *(np.array([]) for _ in range(3 + n_fields)))


async def _read_source_grid(ctx: _Ctx, tf: str, need_high_low: bool, symbols) -> Panel:
    """The source grid for exactly the book's symbols (a name without source bars is a NaN
    column), with closes_at."""
    fields = _source_fields(need_high_low)
    lo = warmup_fetch_start(ctx.scored_lo, tf, ctx.warmup_sessions)
    sql = _bars_sql(fields)
    got = dict(
        await asyncio.gather(*(_fetch_bars(ctx.pool, sql, s, tf, lo, ctx.hi) for s in symbols))
    )
    bars = {s: got[s] if got[s] is not None else _empty_bars(len(fields)) for s in symbols}
    grid = build_grid(bars, tf, fields)
    closes = clock.closes_at(grid.timestamps, grid.valid, tf, grid.bars_per_session)
    return dataclasses.replace(grid, closes_at=closes)


async def _finer_source(ctx: _Ctx, req: SourceRequest, tried: dict) -> tuple[dict, dict]:
    """A source finer than the book: per symbol chunk, its values on the source clock, reduced to
    the int32 source-row index align_index produced plus the referenced source rows and values.
    No aligned value array is persisted (S2b replays the index)."""
    tf, registry, config = req.tf, ctx.registry, tried["config"]
    symbols, m_book = ctx.book.symbols, len(ctx.book.symbols)
    fields = _source_fields(req.need_high_low)
    lo = warmup_fetch_start(ctx.scored_lo, tf, ctx.warmup_sessions)
    sql = _bars_sql(fields)
    chunks = [symbols[i : i + ctx.chunk] for i in range(0, m_book, ctx.chunk)]

    # pass 1: the one grid axis, from timestamps (and finite closes) of every symbol
    all_ts, finite_ts = [], []
    for chunk in chunks:
        for rows in await asyncio.gather(
            *(ctx.pool.fetch(_AXIS_SQL, s, tf, lo, ctx.hi) for s in chunk)
        ):
            if rows:
                ts, close = zip(*rows)
                stamps = (
                    pd.DatetimeIndex(ts)
                    .tz_convert(UTC)
                    .tz_localize(None)
                    .values.astype("datetime64[ns]")
                )
                all_ts.append(stamps)
                finite_ts.append(stamps[np.isfinite(np.array(close, dtype=float))])
    union = np.unique(np.concatenate(all_ts)) if all_ts else np.array([], dtype="datetime64[ns]")
    finite = np.concatenate(finite_ts) if finite_ts else union[:0]
    axis_close = np.where(np.isin(union, finite), 1.0, np.nan)
    ones = np.ones(len(union))
    axis_bars = (union, ones, axis_close, ones, *(ones for _ in fields))
    axis = build_grid({_AXIS: axis_bars}, tf, fields)
    src_ts, src_valid = axis.timestamps, axis.valid
    src_closes = clock.closes_at(src_ts, src_valid, tf, axis.bars_per_session)
    scored = _scored_rows(src_ts, ctx.scored_lo)
    n_src, n_book = len(src_ts), len(ctx.book_closes)

    stored = [m for m in req.members if m.kind == "feature"]
    columns = sorted({m.column for m in stored})
    feature_sql = feature_inputs.feature_select_sql(columns, registry, tf=tf) if columns else None
    floors_col = _floors(stored, lambda m: m.column)
    floors_kernel = {m.member: m.coverage_floor for m in req.members if m.kind == "kernel"}
    counts: dict[str, list[SymbolCounts]] = {k: [] for k in (*columns, *floors_kernel)}
    warm = {k: {"memory_bars": 0, "masked_rows": 0, "masked_finite": 0} for k in columns}
    kernel_info = {m: {"gap_masked": 0, "warmup_masked": 0} for m in floors_kernel}
    unmatched = 0
    idx = {m.member: np.full((n_book, m_book), -1, dtype=np.int32) for m in req.members}
    pieces: dict[str, list] = {m.member: [] for m in req.members}
    probe = (
        np.full((n_src, min(_PROBE_SYMBOLS, m_book), 5), np.nan)
        if any(m.kind == "kernel" for m in req.members)
        else None
    )
    col0 = 0
    for chunk in chunks:
        got = dict(
            await asyncio.gather(*(_fetch_bars(ctx.pool, sql, s, tf, lo, ctx.hi) for s in chunk))
        )
        bars = {s: got[s] if got[s] is not None else _empty_bars(len(fields)) for s in chunk}
        grid = _chunk_grid(axis_bars, bars, tf, fields)
        sl = slice(col0, col0 + len(chunk))
        values: dict[str, np.ndarray] = {}
        if feature_sql:
            rows = await ctx.pool.fetch(feature_sql, tf, list(chunk), lo, ctx.hi)
            masked, present, miss, w = _feature_rows_to_grid(
                rows, grid, chunk, columns, registry, config, scored
            )
            unmatched += miss
            for c in columns:
                values[c] = masked[c]
                counts[c] += feature_inputs.symbol_counts(masked[c], chunk, present=present)
                for key, v in w[c].items():
                    warm[c][key] = v if key == "memory_bars" else warm[c][key] + v
        for m in req.members:
            if m.kind == "kernel":
                result = _run_kernel(grid, m, config, req.need_high_low)
                arr = result.values[m.column]
                kernel_info[m.member]["gap_masked"] += result.gap_masked[m.column]
                kernel_info[m.member]["warmup_masked"] += result.warmup_masked[m.column]
                kernel_info[m.member]["memory_bars"] = result.memory_bars[m.column]
                present = np.isfinite(np.asarray(grid.close)) & scored[:, None]
                counts[m.member] += feature_inputs.symbol_counts(arr, chunk, present=present)
            else:
                arr = values[m.column]
            ix = align.align_index(np.isfinite(arr), src_closes, ctx.book_closes, m.max_age_rows)
            idx[m.member][:, sl] = ix
            rows_c = np.unique(ix[ix >= 0])
            pieces[m.member].append((sl, rows_c, arr[rows_c]))
        if probe is not None:
            for j in range(col0, min(col0 + len(chunk), probe.shape[1])):
                k = j - col0
                hl = (grid.high[:, k], grid.low[:, k]) if req.need_high_low else (None, None)
                for f, col in enumerate(
                    (grid.open[:, k], hl[0], hl[1], grid.close[:, k], grid.volume[:, k])
                ):
                    if col is not None:
                        probe[:, j, f] = col
        col0 += len(chunk)

    info = _block_info(tf, "finer", tried)
    info["columns"], info["unmatched_rows"] = {}, unmatched
    for c in columns:
        info["columns"][c] = {
            "warmup": warm[c],
            "coverage": (
                _coverage(counts[c], c, tf, floors_col[c]) if floors_col[c] is not None else None
            ),
        }
    for name, floor in floors_kernel.items():
        info["columns"][name] = {
            **kernel_info[name],
            "coverage": _coverage(counts[name], name, tf, floor) if floor is not None else None,
        }
    info["members"] = {m.member: {"max_age_rows": m.max_age_rows} for m in req.members}
    arrays: dict[str, np.ndarray] = {f"src_ts__{tf}": src_ts, f"src_valid__{tf}": src_valid}
    for m in req.members:
        used = [p[1] for p in pieces[m.member]]
        union_rows = np.unique(np.concatenate(used)) if used else np.zeros(0, dtype=np.int64)
        ref = np.full((len(union_rows), m_book), np.nan, dtype=np.float32)
        for sl, rows_c, vals in pieces[m.member]:
            ref[np.searchsorted(union_rows, rows_c), sl] = vals
        arrays[f"idx__{m.member}"] = idx[m.member]
        arrays[f"ref_rows__{m.member}"] = union_rows.astype(np.int32)
        arrays[f"ref_values__{m.member}"] = ref
    if probe is not None:
        arrays[f"probe_bars__{tf}"] = probe
        info["probe_symbols"] = list(symbols[: probe.shape[1]])
    return arrays, info


def _chunk_grid(axis_bars, bars, tf: str, fields: tuple[str, ...]) -> Panel:
    """A chunk's panel on the shared grid: the axis pseudo-symbol joins the build so every chunk
    sees the whole union of timestamps, then is dropped."""
    full = build_grid({**bars, _AXIS: axis_bars}, tf, fields)
    keep = len(bars)
    names = ("open", "close", "volume", *fields)
    return dataclasses.replace(
        full,
        symbols=full.symbols[:keep],
        **{f: getattr(full, f)[:, :keep] for f in names},
    )


def verify_sources(book_path: Path) -> dict[str, Path]:
    """Re-verify every child source dir against the digest the book manifest recorded; returns
    tf -> dir. A changed byte in a child raises."""
    book_path = Path(book_path)
    sources = store.read_meta(book_path)["manifest"].get("sources", {})
    out = {}
    for tf, info in sorted(sources.items()):
        if "dir" not in info:
            continue
        path = book_path.parent / info["dir"]
        if store.verify(path) != info["sha256"]:
            raise ValueError(f"source {tf} digest differs from the book manifest")
        out[tf] = path
    return out


async def build_panel(
    dsn: str,
    out_dir: Path,
    *,
    symbols: list[str],
    tf: str,
    start: str,
    end_exclusive: str,
    manifest_extra: dict | None = None,
    dividends: bool = False,
    fields: tuple[str, ...] = (),
    warmup_sessions: int = 0,
    sources: Sequence[SourceRequest] | None = None,
) -> Path:
    """Fetch, grid, and write a content-hashed panel directory; returns its path.
    `manifest_extra` (for example the universe dimension) is merged into the manifest.
    `dividends` also captures the per-session dividend grid a total-return spec needs, so the
    snapshot hash covers the dividend facts the run used. `fields` (PanelSpec.fields) adds the
    high and low arrays and each name's point-in-time sector; without it the bytes are those of
    every earlier snapshot. `fields` may also name closes_at (each row's availability time,
    plan 184-07 B1b). `warmup_sessions` fetches that many NYSE sessions before `start` so
    declared member memory is filled at the first scored row (B1c); the manifest records
    fetch_start and scored_start, and 0 writes the bytes of every earlier snapshot. `sources`
    (plan 184-08) adds each source tf's gated feature and kernel inputs under the one verified
    config per tf: arrays of a source at or coarser than the book's clock (a child dir per coarser
    tf), and for a finer source compact evidence plus an align_index source-row index. Without
    `sources` the bytes are those of every earlier snapshot."""
    registry = default_registry()
    sources = tuple(sources or ())
    _check_requests(sources, registry)
    unknown = set(fields) - {
        *panel_mod.OPTIONAL_BAR_FIELDS,
        panel_mod.SECTOR_PIT,
        panel_mod.CLOSES_AT,
    }
    if unknown:
        raise ValueError(f"unknown panel fields: {sorted(unknown)}")
    want_high_low = any(r.need_high_low and r.tf == tf for r in sources)
    bar_fields = tuple(f for f in panel_mod.OPTIONAL_BAR_FIELDS if f in fields or want_high_low)
    bars_sql = _BARS_SQL.format(extra="".join(f", {f}" for f in bar_fields))
    scored_lo, hi = (utc(datetime.fromisoformat(x)) for x in (start, end_exclusive))
    lo = warmup_fetch_start(scored_lo, tf, warmup_sessions)
    pool = await read_only_pool(dsn)
    try:
        oos = await pool.fetchval(_OOS_START_SQL)
        if oos is None:
            raise ValueError("alpha.validation.oos_start is not set")
        if hi > oos:
            raise ValueError(f"end_exclusive {end_exclusive} is past oos_start {oos.isoformat()}")

        vendor_kinds = None
        if fields or tf in feature_inputs.INTRADAY_DERIVED_TFS:
            vendor_rows = await pool.fetch(_VENDOR_SET_SQL, tf, sorted(symbols), lo, hi)
            try:
                vendor_kinds = feature_inputs.check_intraday_vendors(
                    tf, [(r["vendor"], r["kind"]) for r in vendor_rows]
                )
            except feature_inputs.FeatureInputRefused as error:
                raise ValueError(f"{tf} snapshot refused (B1d): {error}") from error

        requested = sorted(symbols)
        chunk = 0
        if sources:
            chunk = await pool.fetchval(_CHUNK_SQL)
            if not chunk or chunk < 1:
                raise ValueError("infra.research.snapshot_feature_chunk_symbols is not set")
            spans = {
                r.tf: (warmup_fetch_start(scored_lo, r.tf, warmup_sessions), hi) for r in sources
            }
            configs = await _tf_configs(pool, sources, requested, spans, registry)
        fetched = await asyncio.gather(
            *(_fetch_bars(pool, bars_sql, sym, tf, lo, hi) for sym in requested)
        )
        known = {r["symbol"] for r in await pool.fetch(_KNOWN_SQL, requested)}
        async with pool.acquire() as conn:
            label_inputs = await load_label_inputs(conn, symbols=requested, tf=tf, start=lo, end=hi)
        pinned = data_quality.snapshot_manifest(
            label_inputs,
            symbols=requested,
            tf=tf,
            digest_rows=[tuple(r) for r in await pool.fetch(_DIGESTS_SQL, requested, tf, hi, lo)],
            verdict_rows=[
                tuple(r) for r in await pool.fetch(_VERDICTS_SQL, [f"{s}|{tf}" for s in requested])
            ],
        )
        if dividends:
            coverage = {
                r["symbol"]: (r["covered_from"], r["covered_to"])
                for r in await pool.fetch(_DIV_COVERAGE_SQL, requested)
            }
            rule_values = dict(await pool.fetch(_DISPUTE_RULE_SQL))
            if len(rule_values) != 2:
                raise ValueError(
                    f"dividend dispute parameters missing from config_state: {rule_values}"
                )
            rule = dividends_mod.DisputeRule(
                rel_tolerance=float(
                    rule_values["threshold.dividend_event.source_yield_rel_tolerance"]
                ),
                noise_margin=float(rule_values["threshold.dividend_event.noise_margin"]),
            )
            events = [
                (r["symbol"], r["ex_date"], r["yahoo_yield"], r["ibkr_yield"], r["ibkr_prev_close"])
                for r in await pool.fetch(_DIV_EVENTS_SQL, requested, lo.date(), hi.date())
            ]
        if panel_mod.SECTOR_PIT in fields:
            sector_rows = [
                tuple(r)
                for r in await pool.fetch(
                    _SECTOR_SQL, DEFAULT_SCHEME, SECTOR_LEVEL, requested, lo.date(), hi.date()
                )
            ]
        empty = [s for s, b in fetched if b is None]
        grid = build_grid({s: b for s, b in fetched if b is not None}, tf, bar_fields)
        source_arrays: dict[str, np.ndarray] = {}
        source_info: dict[str, dict] = {}
        children: dict[str, Panel] = {}
        if sources:
            book_closes = clock.closes_at(grid.timestamps, grid.valid, tf, grid.bars_per_session)
            ctx = _Ctx(
                pool, registry, grid, book_closes, scored_lo, hi, warmup_sessions, int(chunk)
            )
            for req in sorted(sources, key=lambda r: r.tf):
                if _TF_MINUTES[req.tf] < _TF_MINUTES[tf]:
                    arrays, info = await _finer_source(ctx, req, configs[req.tf])
                    source_arrays.update(arrays)
                else:
                    arrays, info, child = await _whole_source(ctx, req, configs[req.tf])
                    if child is None:
                        source_arrays.update(arrays)
                    else:
                        children[req.tf] = child
                        info["_child_arrays"] = arrays
                source_info[req.tf] = info
    finally:
        await pool.close()
    manifest = {
        **grid.manifest,
        "source": PRICE_SOURCE,
        "start": start,
        "end_exclusive": end_exclusive,
        "oos_start": oos.isoformat(),
        "symbols_without_bars": empty,
        **pinned,
        **(manifest_extra or {}),
    }
    missing = [s for s in grid.symbols if s not in known]
    if missing:
        raise ValueError(f"symbols not in instruments: {missing[:5]}")
    extra = None
    if dividends:
        extra = dividends_mod.dividend_grid(
            session_dates(grid), grid.symbols, coverage, events, rule
        ).arrays()
        manifest["dividends"] = {
            "source": "dividend_events_reconciled",
            "coverage_source": "yahoo",
            "events": len(events),
            "dispute_rule": dataclasses.asdict(rule),
        }
    sector_pit = None
    if panel_mod.SECTOR_PIT in fields:
        traded = (
            np.isfinite(grid.close)
            .reshape(grid.n_sessions, grid.bars_per_session, len(grid.symbols))
            .any(axis=1)
        )
        sector_pit, codes = sector_grid(session_dates(grid), grid.symbols, traded, sector_rows)
        manifest["sector_codes"] = codes
        manifest["sector_source"] = {"scheme": DEFAULT_SCHEME, "level": SECTOR_LEVEL}
    closes_at = None
    if panel_mod.CLOSES_AT in fields:
        closes_at = clock.closes_at(grid.timestamps, grid.valid, tf, grid.bars_per_session)
    if fields:
        manifest["bar_vendor_kinds"] = vendor_kinds
    if warmup_sessions > 0:
        manifest["warmup_prefix"] = {
            "sessions": warmup_sessions,
            "fetch_start": lo.isoformat(),
            "scored_start": scored_lo.isoformat(),
        }
    if sources:
        for req_tf, info in source_info.items():
            child_arrays = info.pop("_child_arrays", None)
            if child_arrays is not None:
                child = dataclasses.replace(
                    children[req_tf],
                    manifest={**children[req_tf].manifest, "source": PRICE_SOURCE, "tf": req_tf},
                )
                path = panel_mod.save(child, Path(out_dir) / "sources" / req_tf, child_arrays)
                info["dir"] = str(path.relative_to(Path(out_dir)))
                info["sha256"] = store.verify(path)
        manifest["sources"] = source_info
        extra = {**(extra or {}), **source_arrays}
    grid = dataclasses.replace(grid, manifest=manifest, sector_pit=sector_pit, closes_at=closes_at)
    return panel_mod.save(grid, Path(out_dir), extra)
