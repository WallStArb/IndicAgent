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
from datetime import UTC, datetime
from pathlib import Path

import asyncpg
import numpy as np
import pandas as pd

from src.core.database_manager import create_pool
from src.core.market_calendar import get_market_calendar
from src.intelligence.research import panel as panel_mod
from src.intelligence.research.panel import Panel

_POOL_SIZE = 6
_EXCHANGE_TZ = "America/New_York"
_EXCHANGE = "NYSE"
_MINUTES_PER_DAY = 1440
# Structural, not tunable: a time of day is part of the regular schedule when it occurs on at
# least this share of sessions (a majority), which excludes stray pre- and post-market bars.
_SLOT_MIN_SESSION_SHARE = 0.5

_OOS_START_SQL = (
    "SELECT config_value::timestamptz FROM config_state "
    "WHERE config_key = 'alpha.validation.oos_start'"
)
_SECTOR_SQL = (
    "SELECT symbol, coalesce(contract_details->>'sector', '') FROM instruments "
    "WHERE symbol = ANY($1)"
)
_BARS_SQL = (
    "SELECT timestamp, open, close, volume FROM market_data_ohlcv_tradeable "
    "WHERE symbol = $1 AND timeframe = $2 AND timestamp >= $3 AND timestamp < $4 "
    "ORDER BY timestamp"
)

# instruments' universe eligibility columns (migration 337). universe_symbols accepts only these,
# so a column name never comes from caller text.
UNIVERSE_DIMENSIONS = ("compute_eligible", "compute_eligible_1d", "live_tradeable")

Bars = dict[str, tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]]  # ts[ns UTC], o, c, v


async def read_only_pool(dsn: str) -> asyncpg.Pool:
    return await create_pool(
        dsn,
        pool_name="research_read_only",
        min_size=1,
        max_size=_POOL_SIZE,
        server_settings={"default_transaction_read_only": "on"},
    )


def build_grid(bars: Bars, tf: str) -> Panel:
    """Pure: per-symbol bars -> a dense Panel on the session grid. Symbols keep input order."""
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
    arrays = {f: np.full((n, m), np.nan) for f in ("open", "close", "volume")}
    for j, s in enumerate(symbols):
        keep = keys[s] >= 0
        rows = keys[s][keep] * bars_per_session + slot_of[s][keep]
        if len(np.unique(rows)) != len(rows):
            raise ValueError(f"{s}: two bars map to one grid slot")
        for f, values in zip(("open", "close", "volume"), bars[s][1:]):
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


def _utc(dt: datetime) -> datetime:
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


async def build_panel(
    dsn: str,
    out_dir: Path,
    *,
    symbols: list[str],
    tf: str,
    start: str,
    end_exclusive: str,
    manifest_extra: dict | None = None,
) -> Path:
    """Fetch, grid, and write a content-hashed panel directory; returns its path.
    `manifest_extra` (for example the universe dimension) is merged into the manifest."""
    lo, hi = (_utc(datetime.fromisoformat(x)) for x in (start, end_exclusive))
    pool = await read_only_pool(dsn)
    try:
        oos = await pool.fetchval(_OOS_START_SQL)
        if oos is None:
            raise ValueError("alpha.validation.oos_start is not set")
        if hi > oos:
            raise ValueError(f"end_exclusive {end_exclusive} is past oos_start {oos.isoformat()}")

        async def fetch(sym: str):
            rows = await pool.fetch(_BARS_SQL, sym, tf, lo, hi)
            if not rows:
                return sym, None
            ts, o, c, v = zip(*rows)  # one pass over the records
            stamps = pd.DatetimeIndex(ts).tz_convert(UTC).tz_localize(None)
            return sym, (
                stamps.values.astype("datetime64[ns]"),
                np.array(o, dtype=float),
                np.array(c, dtype=float),
                np.array(v, dtype=float),
            )

        fetched = await asyncio.gather(*(fetch(s) for s in sorted(symbols)))
        sectors = dict(await pool.fetch(_SECTOR_SQL, sorted(symbols)))
    finally:
        await pool.close()
    empty = [s for s, b in fetched if b is None]
    grid = build_grid({s: b for s, b in fetched if b is not None}, tf)
    manifest = {
        **grid.manifest,
        "source": "market_data_ohlcv_tradeable",
        "start": start,
        "end_exclusive": end_exclusive,
        "oos_start": oos.isoformat(),
        "symbols_without_bars": empty,
        **(manifest_extra or {}),
    }
    missing = [s for s in grid.symbols if s not in sectors]
    if missing:
        raise ValueError(f"symbols not in instruments: {missing[:5]}")
    grid = dataclasses.replace(
        grid, sectors=tuple(sectors[s] for s in grid.symbols), manifest=manifest
    )
    return panel_mod.save(grid, Path(out_dir))
