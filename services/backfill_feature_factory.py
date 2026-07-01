#!/usr/bin/env python3
"""Backfill Feature Factory — two-stage oneshot.

Stage 1 (--fetch-only flag): Fetch IBKR OHLCV history for 58 active ETFs
into market_data_ohlcv at target depths. Checkpointed per (symbol, tf) via
backfill_status.fetch_complete.

Stage 2 (--compute-only flag): Read market_data_ohlcv in chunked sliding
windows, call FeatureFactory.compute() per bar, batch-insert into
feature_vectors. Checkpointed per (symbol, tf) via backfill_status.status.

Default: both stages run in sequence.

IBKR client-id: 40 (provider uses 35; default 56 exceeds _MAX_CLIENT_ID=50).

Source invariant (T1/D-05): Only market_data_ohlcv is read for compute.
Never intelligence_features.

Usage:
    python services/backfill_feature_factory.py
    python services/backfill_feature_factory.py --fetch-only
    python services/backfill_feature_factory.py --compute-only
    python services/backfill_feature_factory.py --symbols SPY,TLT
    python services/backfill_feature_factory.py --client-id 40
"""

from __future__ import annotations

import argparse
import asyncio
import bisect
import math
import sys
from collections import deque
from concurrent.futures import ProcessPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import psycopg2
import psycopg2.extras
import structlog

# Set up sys.path before project imports
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


from services._batch_utils import load_config_service_sync as _load_config_service
from src.config.config_service import ConfigService
from src.config.settings import Settings, get_active_contracts
from src.core.market_calendar import get_market_calendar
from src.core.service_utils import setup_service_logging
from src.intelligence.feature_cache import (
    _HMM_K,
    FeatureCache,
    _hmm_forward_step,
    _wilder_rsi_series,
    _zscore_from_deque,
)
from src.intelligence.feature_factory import (
    FEATURE_FACTORY_VERSION,
    FeatureFactory,
    FeatureFactoryConfig,
)
from src.intelligence.features.feature_vector_persistence import (
    FEATURE_VECTOR_INSERT_SQL_PSYCOPG2,
    feature_vector_to_insert_params,
)
from src.intelligence.schemas import FeatureVector
from src.observability.metrics import JOB_COMPLETED_TOTAL, flush_and_shutdown_metrics
from src.observability.otel import OTelInitError, init_otel_providers
from src.providers import IBKRProvider

setup_service_logging("logs/backfill_feature_factory.log")

_logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_JOB = "backfill-feature-factory"

# Default IBKR client-id — 40 per CLAUDE.md. Provider uses 35. 56+ exceeds cap.
_DEFAULT_CLIENT_ID: int = 40

# Target timeframes for backfill (1m is NOT a backfill target — live pipeline owns 1m)
_TARGET_TIMEFRAMES: list[str] = ["5m", "15m", "1h", "1d"]

# Depth years per TF (D-09, phase 137 spec)
_DEPTH_YEARS: dict[str, int] = {
    "5m": 5,
    "15m": 10,
    "1h": 15,
    "1d": 20,
}

# Bars per trading day per TF (objective formula)
_BARS_PER_DAY: dict[str, int] = {
    "5m": 78,
    "15m": 26,
    "1h": 6,
    "1d": 1,
}

_TRADING_DAYS_PER_YEAR: int = 252

# Batch size for feature_vectors INSERT
_INSERT_BATCH_SIZE: int = 500

# Chunk read size from market_data_ohlcv (T3: never load full history at once)
_READ_CHUNK_BARS: int = 2000

# Warm-up guard: number of bars needed before first valid feature vector.
# Use the momentum_zscore_window (252) as the dominant window + headroom.
# Read from config at runtime via FeatureFactoryConfig.
_FALLBACK_WARM_UP_BARS: int = 252

# Cross-asset symbols for FeatureCache.update_cross_asset()
_SPY = "SPY"
_TLT = "TLT"
_SHY = "SHY"

# CTF higher-timeframe mapping: source TF → HTF used for CTF features
# 1d uses itself as HTF: CTF at bar T computed from daily bars up to T (causal; bisect_right
# selects the current bar's CTF which is valid since the bar has closed at computation time).
_CTF_HIGHER_TF: dict[str, str] = {
    "5m": "1h",
    "15m": "1h",
    "1h": "1d",
    "1d": "1d",
}

# ---------------------------------------------------------------------------
# DB helpers (psycopg2 sync — mirrors run_historical_pipeline.py pattern)
# ---------------------------------------------------------------------------

_STORE_OHLCV_SQL = """
INSERT INTO market_data_ohlcv
    (timestamp, symbol, timeframe, open, high, low, close, volume, source)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (timestamp, symbol, timeframe) DO NOTHING
"""

_FETCH_BARS_SQL = """
SELECT timestamp, open, high, low, close, volume
FROM market_data_ohlcv
WHERE symbol = %s AND timeframe = %s AND volume > 0
ORDER BY timestamp ASC
"""

_FETCH_BARS_SINCE_SQL = """
SELECT timestamp, open, high, low, close, volume
FROM market_data_ohlcv
WHERE symbol = %s AND timeframe = %s AND timestamp >= %s AND volume > 0
ORDER BY timestamp ASC
"""

_FETCH_BARS_WINDOW_SQL = """
SELECT timestamp, open, high, low, close, volume
FROM market_data_ohlcv
WHERE symbol = %s AND timeframe = %s
  AND timestamp >= %s AND timestamp < %s AND volume > 0
ORDER BY timestamp ASC
"""

_UPSERT_STATUS_SQL = """
INSERT INTO backfill_status (symbol, tf, status, fetch_complete, started_at)
VALUES (%s, %s, %s, %s, NOW())
ON CONFLICT (symbol, tf) DO UPDATE SET
    status = EXCLUDED.status,
    fetch_complete = GREATEST(backfill_status.fetch_complete, EXCLUDED.fetch_complete),
    started_at = COALESCE(backfill_status.started_at, EXCLUDED.started_at)
"""

_MARK_FETCH_COMPLETE_SQL = """
INSERT INTO backfill_status (symbol, tf, fetch_complete, status)
VALUES (%s, %s, true, 'pending')
ON CONFLICT (symbol, tf) DO UPDATE SET fetch_complete = true
"""

_MARK_COMPUTE_STATUS_SQL = """
INSERT INTO backfill_status (symbol, tf, status, started_at)
VALUES (%s, %s, %s, NOW())
ON CONFLICT (symbol, tf) DO UPDATE SET
    status = EXCLUDED.status,
    started_at = COALESCE(backfill_status.started_at, NOW())
"""

_MARK_COMPUTE_COMPLETE_SQL = """
UPDATE backfill_status
SET status = 'complete',
    rows_written = %s,
    theoretical_max = %s,
    completed_at = NOW()
WHERE symbol = %s AND tf = %s
"""

_MARK_COMPUTE_FAILED_SQL = """
UPDATE backfill_status
SET status = 'failed', error_msg = %s
WHERE symbol = %s AND tf = %s
"""

_SELECT_STATUS_SQL = """
SELECT symbol, tf, status, fetch_complete, rows_written, theoretical_max
FROM backfill_status
WHERE symbol = ANY(%s) AND tf = ANY(%s)
"""

# Canonical INSERT SQL imported from shared persistence module.
# Do not inline SQL here — feature_vector_persistence.py is the single source of truth.
_INSERT_FEATURE_VECTORS_SQL = FEATURE_VECTOR_INSERT_SQL_PSYCOPG2


def _build_cross_asset_series(
    spy_bars: list[dict],
    tlt_bars: list[dict],
    shy_bars: list[dict],
    config: FeatureFactoryConfig,
) -> dict:
    """Build date → (vix_z, flight_quality, yield_slope_z) incrementally in O(D).

    Uses a single aligned dict structure (no parallel lists) and maintains
    incremental state instead of re-materializing full bar slices each date.

    Assumption: SPY/TLT/SHY trade the same US calendar days, so min(spy_end, tlt_end)
    equals spy_end for every date. flight_quality anchors to the first available close
    for each symbol (equivalent to the batch formula when all series start together).
    """
    symbol_bars: dict[str, list[dict]] = {"spy": spy_bars, "tlt": tlt_bars, "shy": shy_bars}
    symbol_dates: dict[str, list] = {k: [b["ts"].date() for b in v] for k, v in symbol_bars.items()}
    all_dates = sorted(set().union(*symbol_dates.values()))

    # Incremental state — O(1) per date
    cursors: dict[str, int] = {k: 0 for k in symbol_bars}
    spy_log_rets: deque = deque(maxlen=config.cross_asset_rv_window)
    yield_ratio_history: deque = deque(maxlen=config.yield_curve_zscore_window)
    spy_realized_vol_history: deque = deque(maxlen=config.vix_zscore_window)

    spy_prev_close: float = 0.0
    tlt_prev_close: float = 0.0
    shy_prev_close: float = 0.0
    spy_first_close: float = 0.0  # flight_quality period-start anchor
    tlt_first_close: float = 0.0

    vix_z: float = 0.0
    flight_quality: float = 0.0
    yield_slope_z: float = 0.0
    result: dict = {}

    for d in all_dates:
        for k in symbol_bars:
            cursors[k] = bisect.bisect_right(symbol_dates[k], d)

        spy_end = cursors["spy"]
        tlt_end = cursors["tlt"]
        shy_end = cursors["shy"]

        if spy_end < 2 or tlt_end < 2 or shy_end < 2:
            # Advance prev_close trackers even during skip so first diff is correct
            if spy_end >= 1:
                spy_prev_close = float(spy_bars[spy_end - 1]["close"])
            if tlt_end >= 1:
                tlt_prev_close = float(tlt_bars[tlt_end - 1]["close"])
            if shy_end >= 1:
                shy_prev_close = float(shy_bars[shy_end - 1]["close"])
            continue

        spy_close = float(spy_bars[spy_end - 1]["close"])
        tlt_close = float(tlt_bars[tlt_end - 1]["close"])
        shy_close = float(shy_bars[shy_end - 1]["close"])

        # Set period-start anchors once (first date with ≥2 bars for all three)
        if spy_first_close == 0.0:
            spy_first_close = float(spy_bars[0]["close"])
            tlt_first_close = float(tlt_bars[0]["close"])

        # vix_z: append new SPY log return; compute realized vol; z-score over history
        if spy_prev_close > 1e-10:
            spy_ret = math.log(spy_close / spy_prev_close)
            spy_log_rets.append(spy_ret)
            realized_vol = float(np.std(spy_log_rets))
            spy_realized_vol_history.append(realized_vol)
            vix_z = _zscore_from_deque(spy_realized_vol_history, config.vix_zscore_window)

        # flight_quality: cumulative TLT/SPY divergence from period start (O(1))
        if spy_first_close > 1e-10 and tlt_first_close > 1e-10:
            tlt_ret_total = tlt_close / tlt_first_close - 1.0
            spy_ret_total = spy_close / spy_first_close - 1.0
            flight_quality = tlt_ret_total - spy_ret_total

        # yield_slope_z: one-period TLT/SHY log-return ratio; z-score over history
        if tlt_prev_close > 1e-10 and shy_prev_close > 1e-10:
            tlt_log_ret = math.log(tlt_close / tlt_prev_close)
            shy_log_ret = math.log(shy_close / shy_prev_close)
            yield_ratio_history.append(tlt_log_ret - shy_log_ret)
            yield_slope_z = _zscore_from_deque(
                yield_ratio_history, config.yield_curve_zscore_window
            )

        result[d] = (vix_z, flight_quality, yield_slope_z)

        spy_prev_close = spy_close
        tlt_prev_close = tlt_close
        shy_prev_close = shy_close

    return result


def _build_ctf_series(
    htf_bars: list[dict],
    config: FeatureFactoryConfig,
) -> dict:
    """Build {htf_bar_ts: (ctf_momentum, ctf_vwap_align, ctf_regime_align)} in O(n).

    Single-pass streaming computation: Wilder RSI + cumulative VWAP + HMM forward.
    Avoids O(n²) slice reprocessing. All values are causal — bar k uses only bars 0..k.
    """
    n = len(htf_bars)
    if n < 2:
        return {}

    closes = np.array([b["close"] for b in htf_bars], dtype=float)
    highs = np.array([b["high"] for b in htf_bars], dtype=float)
    lows = np.array([b["low"] for b in htf_bars], dtype=float)
    volumes = np.array([b["volume"] for b in htf_bars], dtype=float)

    period = config.rsi_mid_period

    # ctf_momentum: Wilder RSI per bar, normalized to [-1, +1]. Single shared impl.
    rsi_series = _wilder_rsi_series(closes, period)
    ctf_mom = np.clip((rsi_series - 50.0) / 50.0, -1.0, 1.0)

    # ctf_vwap_align: sign(close - cumulative VWAP)
    typical = (highs + lows + closes) / 3.0
    cum_tp_vol = np.cumsum(typical * volumes)
    cum_vol = np.cumsum(volumes)
    vwap = np.where(cum_vol > 1e-10, cum_tp_vol / cum_vol, closes)
    ctf_vwap = np.where(closes > vwap + 1e-10, 1.0, np.where(closes < vwap - 1e-10, -1.0, 0.0))

    # ctf_regime_align: HMM forward pass — 0.0 (ranging) or 1.0 (trending)
    ctf_regime = np.zeros(n, dtype=float)
    hmm_alpha = np.full(_HMM_K, 1.0 / _HMM_K, dtype=float)
    log_rets = np.diff(np.log(np.maximum(closes, 1e-10)))
    log_rets = np.where(np.isfinite(log_rets), log_rets, 0.0)
    ret_buf: deque = deque(maxlen=20)
    obs_buf = np.zeros(2, dtype=float)
    for i, ret in enumerate(log_rets):
        ret_buf.append(float(ret))
        obs_buf[0] = float(ret)
        obs_buf[1] = float(np.std(ret_buf)) if len(ret_buf) >= 2 else 0.005
        _hmm_forward_step(obs_buf, hmm_alpha)
        label = int(np.argmax(hmm_alpha))
        ctf_regime[i + 1] = 0.0 if label == 0 else 1.0

    return {
        htf_bars[k]["ts"]: (float(ctf_mom[k]), float(ctf_vwap[k]), float(ctf_regime[k]))
        for k in range(n)
    }


def _connect_db(settings: Settings) -> Any:
    """Synchronous psycopg2 connection."""
    conn = psycopg2.connect(dsn=settings.database_url)
    conn.autocommit = True
    # Register UUID adapter so psycopg2 can serialize uuid.UUID objects.
    # Without this, feature_vector_id (content-key UUID) raises can not adapt type UUID.
    psycopg2.extras.register_uuid()
    return conn


def _filter_etf_contracts(contracts: list, symbols: list[str] | None) -> list:
    """Return active ETF contracts, excluding futures and FX, optionally filtered to symbols."""
    etf = [
        c
        for c in contracts
        if not str(getattr(c, "asset_class", "")).lower().startswith("futures")
        and not str(getattr(c, "asset_class", "")).lower().startswith("fx")
    ]
    if symbols:
        wanted = set(symbols)
        etf = [c for c in etf if c.symbol in wanted]
    return etf


def _build_feature_factory_config(cfg: ConfigService) -> FeatureFactoryConfig:
    """Build FeatureFactoryConfig from APR keys. All fields from feature.* namespace."""
    return FeatureFactoryConfig(
        momentum_window_fast=int(cfg.get_sync("feature.momentum.window_fast", 5)),
        momentum_window_mid=int(cfg.get_sync("feature.momentum.window_mid", 20)),
        momentum_window_slow=int(cfg.get_sync("feature.momentum.window_slow", 60)),
        momentum_zscore_window=int(cfg.get_sync("feature.momentum.zscore_window", 252)),
        volume_zscore_window=int(cfg.get_sync("feature.volume.zscore_window", 20)),
        ofi_zscore_window=int(cfg.get_sync("feature.ofi.zscore_window", 20)),
        cvd_slope_bars=int(cfg.get_sync("feature.cvd.slope_bars", 5)),
        cmf_period=int(cfg.get_sync("feature.cmf.period", 20)),
        vol_short_bars=int(cfg.get_sync("feature.vol.short_bars", 5)),
        vol_long_bars=int(cfg.get_sync("feature.vol.long_bars", 20)),
        hma_period=int(cfg.get_sync("feature.hma.period", 20)),
        adx_period=int(cfg.get_sync("feature.adx.period", 14)),
        hurst_window=int(cfg.get_sync("feature.hurst.window", 252)),
        garch_window=int(cfg.get_sync("feature.garch.window", 100)),
        vix_zscore_window=int(cfg.get_sync("feature.vix.zscore_window", 252)),
        yield_curve_zscore_window=int(cfg.get_sync("feature.yield_curve.zscore_window", 252)),
        regime_cache_refresh_bars=int(cfg.get_sync("feature.regime.cache_refresh_bars", 30)),
        rsi_fast_period=int(cfg.get_sync("feature.period.rsi.fast", 7)),
        rsi_mid_period=int(cfg.get_sync("feature.period.rsi.mid", 14)),
        rsi_slow_period=int(cfg.get_sync("feature.period.rsi.slow", 28)),
        cci_fast_period=int(cfg.get_sync("feature.period.cci.fast", 10)),
        cci_mid_period=int(cfg.get_sync("feature.period.cci.mid", 20)),
        cci_slow_period=int(cfg.get_sync("feature.period.cci.slow", 40)),
        aroon_fast_period=int(cfg.get_sync("feature.period.aroon.fast", 14)),
        aroon_slow_period=int(cfg.get_sync("feature.period.aroon.slow", 25)),
        amihud_zscore_window=int(cfg.get_sync("feature.amihud.zscore_window", 252)),
        ret_skew_window=int(cfg.get_sync("feature.ret_skew.window", 60)),
        ret_skew_zscore_window=int(cfg.get_sync("feature.ret_skew.zscore_window", 252)),
        ret_acf_window=int(cfg.get_sync("feature.ret_acf.window", 30)),
        ret_acf_zscore_window=int(cfg.get_sync("feature.ret_acf.zscore_window", 252)),
        high_52w_window=int(cfg.get_sync("feature.high_52w.window", 252)),
        min_bars_warmup=int(cfg.get_sync("feature.cache.min_bars_warmup", 16)),
        cross_asset_rv_window=int(cfg.get_sync("feature.cross_asset.rv_window", 20)),
        ny_session_start_utc_hour=int(cfg.get_sync("feature.session.ny_start_utc_hour", 13)),
        ny_session_start_utc_minute=int(cfg.get_sync("feature.session.ny_start_utc_minute", 30)),
        ny_session_end_utc_hour=int(cfg.get_sync("feature.session.ny_end_utc_hour", 20)),
        overlap_start_utc_hour=int(cfg.get_sync("feature.session.overlap_start_utc_hour", 12)),
        overlap_end_utc_hour=int(cfg.get_sync("feature.session.overlap_end_utc_hour", 15)),
        london_kz_start_utc_hour=int(cfg.get_sync("feature.session.london_kz_start_utc_hour", 7)),
        london_kz_end_utc_hour=int(cfg.get_sync("feature.session.london_kz_end_utc_hour", 10)),
        power_hour_start_utc_hour=int(
            cfg.get_sync("feature.session.power_hour_start_utc_hour", 19)
        ),
        power_hour_end_utc_hour=int(cfg.get_sync("feature.session.power_hour_end_utc_hour", 21)),
        opening_range_start_minute=int(
            cfg.get_sync("feature.session.opening_range_start_minute", 810)
        ),
        opening_range_end_minute=int(cfg.get_sync("feature.session.opening_range_end_minute", 900)),
    )


def _theoretical_max(tf: str, depth_years: int, warm_up_bars: int) -> int:
    """Compute theoretical max feature rows.

    Formula: (depth_years * 252 * bars_per_trading_day(tf)) - warm_up_bars

    Parameters
    ----------
    tf: Timeframe string (5m/15m/1h/1d)
    depth_years: Fetch depth in years
    warm_up_bars: Bars consumed by rolling window seed (dominant window)
    """
    bars_per_day = _BARS_PER_DAY[tf]
    return max(0, depth_years * _TRADING_DAYS_PER_YEAR * bars_per_day - warm_up_bars)


def _vector_to_params(
    symbol: str,
    tf: str,
    bar_ts: datetime,
    pipeline_version: str,
    regime: str | None,
    fv: FeatureVector,
) -> tuple:
    """Delegate to the canonical shared serializer.

    Backfill rows always use regime_label_source='filtered': all rows are
    computed from market_data_ohlcv with causal forward-filter HMM only (D-07).
    FEATURE_FACTORY_VERSION is injected here so all batch rows are version-stamped.
    """
    return feature_vector_to_insert_params(
        symbol=symbol,
        tf=tf,
        bar_ts=bar_ts,
        pipeline_version=pipeline_version,
        feature_factory_version=FEATURE_FACTORY_VERSION,
        regime=regime,
        regime_label_source="filtered",
        vector=fv,
    )


def _fetch_bars_from_db(
    conn: Any, symbol: str, tf: str, since: datetime | None = None
) -> list[dict]:
    """Fetch OHLCV bars from market_data_ohlcv ordered oldest-first."""
    with conn.cursor() as cur:
        if since is not None:
            cur.execute(_FETCH_BARS_SINCE_SQL, (symbol, tf, since))
        else:
            cur.execute(_FETCH_BARS_SQL, (symbol, tf))
        rows = cur.fetchall()
    return [
        {
            "ts": r[0] if r[0].tzinfo else r[0].replace(tzinfo=UTC),
            "open": float(r[1]),
            "high": float(r[2]),
            "low": float(r[3]),
            "close": float(r[4]),
            "volume": float(r[5]),
        }
        for r in rows
    ]


def _load_status_map(conn: Any, symbols: list[str], tfs: list[str]) -> dict[tuple[str, str], dict]:
    """Load backfill_status rows for all (symbol, tf) pairs."""
    with conn.cursor() as cur:
        cur.execute(_SELECT_STATUS_SQL, (symbols, tfs))
        rows = cur.fetchall()
    result: dict[tuple[str, str], dict] = {}
    for sym, tf, status, fetch_complete, rows_written, theoretical_max in rows:
        result[(sym, tf)] = {
            "status": status,
            "fetch_complete": fetch_complete,
            "rows_written": rows_written,
            "theoretical_max": theoretical_max,
        }
    return result


# ---------------------------------------------------------------------------
# Stage 1: IBKR Fetch
# ---------------------------------------------------------------------------


async def run_fetch_stage(
    settings: Settings,
    client_id: int,
    symbols: list[str] | None,
    db_conn: Any,
) -> None:
    """Fetch IBKR OHLCV history for ETFs into market_data_ohlcv.

    Skips (symbol, tf) pairs that already have fetch_complete=true.
    On success marks fetch_complete=true BEFORE compute can begin (checkpoint).
    """
    from src.core.bar_normalizer import normalize_bars

    contracts = get_active_contracts(settings)
    etf_contracts = _filter_etf_contracts(contracts, symbols)
    _logger.info("fetch_stage_start", contracts=len(etf_contracts), client_id=client_id)

    # Load existing status to skip already-fetched pairs
    all_symbols = [c.symbol for c in etf_contracts]
    status_map = _load_status_map(db_conn, all_symbols, _TARGET_TIMEFRAMES)

    provider = IBKRProvider(
        host=settings.ib_host,
        port=settings.ib_port,
        client_id=client_id,
    )

    connected = await provider.connect()
    if not connected:
        _logger.error("ibkr_connect_failed")
        raise RuntimeError("Cannot connect to IBKR TWS — aborting fetch stage")

    end_dt = datetime.now(tz=UTC)
    total_bars_fetched = 0

    try:
        for instrument in etf_contracts:
            try:
                qualified = await provider.qualify_instrument(instrument)
                if not qualified:
                    _logger.warning("qualify_failed", symbol=instrument.symbol)
                    continue

                for tf in _TARGET_TIMEFRAMES:
                    key = (instrument.symbol, tf)
                    existing = status_map.get(key, {})

                    # Skip if already fetched (checkpoint resume)
                    if existing.get("fetch_complete"):
                        _logger.info(
                            "fetch_skip_complete",
                            symbol=instrument.symbol,
                            tf=tf,
                        )
                        continue

                    depth_years = _DEPTH_YEARS[tf]
                    fetch_days = depth_years * 365
                    start_dt = (end_dt - timedelta(days=fetch_days)).replace(
                        hour=0, minute=0, second=0, microsecond=0
                    )

                    _logger.info(
                        "fetch_start",
                        symbol=instrument.symbol,
                        tf=tf,
                        depth_years=depth_years,
                    )

                    try:
                        ohlcv_bars = await provider.fetch_historical_bars(
                            symbol=instrument.symbol,
                            timeframe=tf,
                            start=start_dt,
                            end=end_dt,
                            continuous=False,
                        )
                        bar_dicts = [
                            {
                                "timestamp": b.timestamp,
                                "open": b.open,
                                "high": b.high,
                                "low": b.low,
                                "close": b.close,
                                "volume": b.volume,
                                "source": getattr(b, "source", "historical_backfill"),
                            }
                            for b in ohlcv_bars
                        ]

                        canonical = normalize_bars(
                            bar_dicts,
                            symbol=instrument.symbol,
                            timeframe=tf,
                            start=start_dt,
                            end=end_dt,
                        )

                        if canonical:
                            params = [
                                (
                                    b["timestamp"],
                                    instrument.symbol,
                                    tf,
                                    b["open"],
                                    b["high"],
                                    b["low"],
                                    b["close"],
                                    b.get("volume", 0),
                                    b.get("source", "historical_backfill"),
                                )
                                for b in canonical
                            ]
                            with db_conn.cursor() as cur:
                                psycopg2.extras.execute_batch(cur, _STORE_OHLCV_SQL, params)
                            db_conn.commit()
                            total_bars_fetched += len(params)
                            _logger.info(
                                "fetch_stored",
                                symbol=instrument.symbol,
                                tf=tf,
                                bars=len(params),
                            )

                        # Mark fetch_complete BEFORE starting compute (two-stage checkpoint)
                        with db_conn.cursor() as cur:
                            cur.execute(_MARK_FETCH_COMPLETE_SQL, (instrument.symbol, tf))
                        db_conn.commit()

                    except Exception as error:
                        _logger.error(
                            "fetch_error",
                            symbol=instrument.symbol,
                            tf=tf,
                            error=str(error),
                        )

                    await asyncio.sleep(1)  # IBKR pacing between TFs

            except Exception as error:
                _logger.error("instrument_error", symbol=instrument.symbol, error=str(error))

            await asyncio.sleep(2)  # IBKR pacing between instruments

    finally:
        await provider.disconnect()

    _logger.info("fetch_stage_complete", total_bars=total_bars_fetched)


# ---------------------------------------------------------------------------
# Stage 2: FeatureFactory Compute
# ---------------------------------------------------------------------------


def run_compute_stage(
    settings: Settings,
    symbols: list[str] | None,
    db_conn: Any,
    pipeline_version: str = "3.0.0",
    n_workers: int = 1,
) -> tuple[dict[tuple[str, str], dict], float]:
    """Compute FeatureVectors from market_data_ohlcv and batch-insert into feature_vectors.

    Reads bars in chunked sliding windows (T3: never full history at once).
    Checkpointed per (symbol, tf): skips status='complete' pairs.
    Records per-pair coverage vs theoretical_max (D-06 gate).
    Uses ProcessPoolExecutor for symbol-level parallelism when n_workers > 1.

    Returns coverage map: {(symbol, tf): {"rows_written": N, "theoretical_max": M, "pct": P}}
    """
    cfg = _load_config_service(db_conn)
    config = _build_feature_factory_config(cfg)
    coverage_threshold = float(cfg.get_sync("threshold.backfill.coverage_threshold", 0.80))

    # Warm-up bars = dominant rolling window (momentum_zscore_window = 252)
    warm_up_bars = config.momentum_zscore_window

    # Pre-load cross-asset ETF bars and build incremental causal series (once for all symbols)
    spy_bars = _fetch_bars_from_db(db_conn, _SPY, "1d")
    tlt_bars = _fetch_bars_from_db(db_conn, _TLT, "1d")
    shy_bars = _fetch_bars_from_db(db_conn, _SHY, "1d")
    _logger.info(
        "cross_asset_loaded",
        spy=len(spy_bars),
        tlt=len(tlt_bars),
        shy=len(shy_bars),
    )
    cross_asset_by_date = _build_cross_asset_series(spy_bars, tlt_bars, shy_bars, config)
    _logger.info("cross_asset_series_built", dates=len(cross_asset_by_date))

    contracts = get_active_contracts(settings)
    etf_contracts = _filter_etf_contracts(contracts, symbols)
    all_symbols = [c.symbol for c in etf_contracts]
    status_map = _load_status_map(db_conn, all_symbols, _TARGET_TIMEFRAMES)
    coverage: dict[tuple[str, str], dict] = {}
    dsn = settings.database_url

    # Collect symbols that need compute (skip already-complete and unfetched)
    pending_symbols: list[str] = []
    for instrument in etf_contracts:
        symbol = instrument.symbol
        needs_compute = False
        for tf in _TARGET_TIMEFRAMES:
            key = (symbol, tf)
            existing = status_map.get(key, {})
            if existing.get("status") == "complete":
                rows_written = existing.get("rows_written", 0) or 0
                theoretical = existing.get("theoretical_max", 0) or 0
                pct = rows_written / theoretical if theoretical > 0 else 0.0
                coverage[key] = {
                    "rows_written": rows_written,
                    "theoretical_max": theoretical,
                    "pct": pct,
                }
                _logger.info("compute_skip_complete", symbol=symbol, tf=tf)
            elif not existing.get("fetch_complete"):
                _logger.warning("compute_skip_no_fetch", symbol=symbol, tf=tf)
            else:
                needs_compute = True
                # Mark in_progress on main connection before handing off to worker
                with db_conn.cursor() as cur:
                    cur.execute(_MARK_COMPUTE_STATUS_SQL, (symbol, tf, "in_progress"))
                # db_conn.autocommit=True — no explicit commit needed

        if needs_compute:
            pending_symbols.append(symbol)

    if not pending_symbols:
        return coverage, coverage_threshold

    # Close main connection before spawning workers — connections are not picklable
    db_conn.close()

    worker_args = [
        (
            symbol,
            _TARGET_TIMEFRAMES,
            dsn,
            config,
            pipeline_version,
            warm_up_bars,
            cross_asset_by_date,
        )
        for symbol in pending_symbols
    ]

    _logger.info(
        "compute_stage_parallel",
        pending_symbols=len(pending_symbols),
        n_workers=n_workers,
    )

    with ProcessPoolExecutor(max_workers=n_workers) as pool:
        for result in pool.map(_run_compute_worker, worker_args, chunksize=1):
            symbol = result["symbol"]
            if result["error"]:
                _logger.error(
                    "compute_worker_failed",
                    symbol=symbol,
                    error=result["error"],
                )
            for cell in result["results"]:
                tf = cell["tf"]
                key = (symbol, tf)
                coverage[key] = {
                    "rows_written": cell["rows_written"],
                    "theoretical_max": cell["theoretical_max"],
                    "pct": cell["pct"],
                }
                if cell.get("error"):
                    _logger.error(
                        "compute_cell_failed",
                        symbol=symbol,
                        tf=tf,
                        error=cell["error"],
                    )
                elif cell["pct"] < coverage_threshold:
                    _logger.warning(
                        "coverage_below_threshold",
                        symbol=symbol,
                        tf=tf,
                        rows_written=cell["rows_written"],
                        theoretical_max=cell["theoretical_max"],
                        pct=round(cell["pct"], 4),
                        threshold=coverage_threshold,
                    )
                else:
                    _logger.info(
                        "compute_complete",
                        symbol=symbol,
                        tf=tf,
                        rows_written=cell["rows_written"],
                        theoretical_max=cell["theoretical_max"],
                        pct=round(cell["pct"], 4),
                    )

    return coverage, coverage_threshold


def _run_compute_worker(args: tuple) -> dict:
    """Worker function for ProcessPoolExecutor — runs in subprocess.

    Opens its own psycopg2 connection (connections are not picklable and
    must not be shared across processes). No OTel tracer — workers log only;
    main process aggregates results and emits metrics.

    Args:
        args: (symbol, tfs, dsn, config, pipeline_version, warm_up_bars,
               cross_asset_by_date)
               Packed as a tuple for ProcessPoolExecutor.map compatibility.

    Returns:
        dict with keys: symbol, results (list of {tf, rows_written, theoretical_max,
        pct, error?}), error (str|None)
    """
    (
        symbol,
        tfs,
        dsn,
        config,
        pipeline_version,
        warm_up_bars,
        cross_asset_by_date,
    ) = args

    # Initialize logging in subprocess (each process needs its own handler)
    setup_service_logging("logs/backfill_feature_factory.log")
    worker_log = structlog.get_logger(__name__)

    conn = None
    results = []
    error_msg = None

    try:
        conn = psycopg2.connect(dsn)
        # autocommit=True prevents InFailedSqlTransaction from poisoning later TFs
        # on per-cell exceptions; no conn.rollback() needed.
        conn.autocommit = True
        psycopg2.extras.register_uuid()

        for tf in tfs:
            try:
                rows_written = _compute_symbol_tf(
                    conn=conn,
                    symbol=symbol,
                    tf=tf,
                    config=config,
                    pipeline_version=pipeline_version,
                    warm_up_bars=warm_up_bars,
                    cross_asset_by_date=cross_asset_by_date,
                )

                depth_years = _DEPTH_YEARS[tf]
                theoretical = _theoretical_max(tf, depth_years, warm_up_bars)
                pct = rows_written / theoretical if theoretical > 0 else 0.0

                with conn.cursor() as cur:
                    cur.execute(
                        _MARK_COMPUTE_COMPLETE_SQL,
                        (rows_written, theoretical, symbol, tf),
                    )

                results.append(
                    {
                        "tf": tf,
                        "rows_written": rows_written,
                        "theoretical_max": theoretical,
                        "pct": pct,
                    }
                )

            except Exception as error:
                error_str = str(error)
                worker_log.error(
                    "worker_cell_failed",
                    symbol=symbol,
                    tf=tf,
                    error=error_str,
                )
                try:
                    with conn.cursor() as cur:
                        cur.execute(_MARK_COMPUTE_FAILED_SQL, (error_str, symbol, tf))
                except Exception:
                    pass
                results.append(
                    {
                        "tf": tf,
                        "rows_written": 0,
                        "theoretical_max": 0,
                        "pct": 0.0,
                        "error": error_str,
                    }
                )

    except Exception as error:
        error_msg = str(error)
        worker_log.error("worker_failed", symbol=symbol, error=error_msg)
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass

    return {"symbol": symbol, "results": results, "error": error_msg}


def _compute_symbol_tf(
    conn: Any,
    symbol: str,
    tf: str,
    config: FeatureFactoryConfig,
    pipeline_version: str,
    warm_up_bars: int,
    cross_asset_by_date: dict,
) -> int:
    """Compute FeatureVectors for one (symbol, tf) pair.

    Post-injects three groups of corrected values into every FeatureVector:
      1. Cross-asset (vix_z, flight_quality, yield_slope_z): from pre-built
         incremental causal series keyed by date.
      2. CTF (ctf_momentum, ctf_vwap_align, ctf_regime_align): from O(n) single-pass
         series keyed by HTF bar timestamp; looked up by bisect for each source bar.
      3. VP/SR (poc_dist_atr, va_position, sr_support_dist, sr_resist_dist): NULL —
         not computable from OHLCV batch without intraday I3 injection.

    Returns total rows inserted into feature_vectors.
    """
    # Build CTF series for this symbol (O(n) single pass over HTF bars)
    htf_tf = _CTF_HIGHER_TF.get(tf)
    ctf_by_ts: dict = {}
    htf_ts_list: list = []
    if htf_tf:
        htf_bars = _fetch_bars_from_db(conn, symbol, htf_tf)
        if htf_bars:
            ctf_by_ts = _build_ctf_series(htf_bars, config)
            htf_ts_list = sorted(ctf_by_ts.keys())
            _logger.debug(
                "ctf_series_built", symbol=symbol, tf=tf, htf_tf=htf_tf, htf_bars=len(htf_bars)
            )

    cache = FeatureCache()
    bars = _fetch_bars_from_db(conn, symbol, tf)
    total_bars = len(bars)

    if total_bars < warm_up_bars + 2:
        _logger.warning(
            "insufficient_bars",
            symbol=symbol,
            tf=tf,
            bars=total_bars,
            warm_up_bars=warm_up_bars,
        )
        return 0

    _logger.info("compute_bars_loaded", symbol=symbol, tf=tf, total_bars=total_bars)

    batch_results = FeatureFactory.compute_batch(
        bars,
        symbol,
        tf,
        cache,
        config,
        warm_up_bars=warm_up_bars,
        cross_asset_by_date=cross_asset_by_date,
        ctf_by_ts=ctf_by_ts or None,
        ctf_ts_list=htf_ts_list or None,
    )

    insert_batch: list[tuple] = []
    total_inserted = 0
    skipped_non_trading = 0

    # Market calendar for trading day filtering (Renaissance: filter at source)
    calendar = get_market_calendar()
    exchange = "NYSE"  # ETFs trade on NYSE/NASDAQ/ARCA with identical hours

    for bar_ts, fv in batch_results:
        if not calendar.is_trading_bar(exchange, bar_ts, tf):
            skipped_non_trading += 1
            continue

        row = _vector_to_params(
            symbol=symbol,
            tf=tf,
            bar_ts=bar_ts,
            pipeline_version=pipeline_version,
            regime=None,
            fv=fv,
        )
        insert_batch.append(row)

        if len(insert_batch) >= _INSERT_BATCH_SIZE:
            _batch_insert(conn, insert_batch)
            total_inserted += len(insert_batch)
            insert_batch = []
            _logger.debug(
                "compute_progress",
                symbol=symbol,
                tf=tf,
                inserted=total_inserted,
                total_bars=total_bars,
            )

    if insert_batch:
        _batch_insert(conn, insert_batch)
        total_inserted += len(insert_batch)

    _logger.info(
        "compute_complete",
        symbol=symbol,
        tf=tf,
        total_bars=total_bars,
        inserted=total_inserted,
        skipped_non_trading=skipped_non_trading,
        skip_pct=round(skipped_non_trading / total_bars * 100, 2) if total_bars > 0 else 0,
    )

    return total_inserted


def _batch_insert(conn: Any, rows: list[tuple]) -> None:
    """Batch-insert feature_vectors rows via psycopg2 execute_batch."""
    if not rows:
        return
    with conn.cursor() as cur:
        psycopg2.extras.execute_batch(cur, _INSERT_FEATURE_VECTORS_SQL, rows)
    conn.commit()


def _log_coverage_report(coverage: dict[tuple[str, str], dict], coverage_threshold: float) -> None:
    """Log per-pair coverage vs theoretical_max; flag pairs below the APR coverage threshold."""
    below_threshold: list[tuple[str, str, int, int, float]] = []
    for (symbol, tf), data in sorted(coverage.items()):
        pct = data.get("pct", 0.0)
        rows = data.get("rows_written", 0)
        theoretical = data.get("theoretical_max", 0)
        if pct < coverage_threshold:
            below_threshold.append((symbol, tf, rows, theoretical, pct))

    _logger.info(
        "coverage_report",
        total_pairs=len(coverage),
        below_threshold=len(below_threshold),
        threshold=coverage_threshold,
    )

    if below_threshold:
        _logger.warning(
            "coverage_below_threshold",
            pairs=[
                {"symbol": s, "tf": t, "rows": r, "theoretical": th, "pct": round(p, 4)}
                for s, t, r, th, p in below_threshold
            ],
            threshold=coverage_threshold,
        )


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Backfill Feature Factory — two-stage IBKR fetch + FeatureFactory compute"
    )
    parser.add_argument(
        "--fetch-only",
        action="store_true",
        help="Only run Stage 1 (IBKR fetch into market_data_ohlcv), skip compute",
    )
    parser.add_argument(
        "--compute-only",
        action="store_true",
        help="Only run Stage 2 (FeatureFactory compute into feature_vectors), skip IBKR fetch",
    )
    parser.add_argument(
        "--client-id",
        type=int,
        default=_DEFAULT_CLIENT_ID,
        help=f"IBKR client ID (default: {_DEFAULT_CLIENT_ID}; provider uses 35; max 50)",
    )
    parser.add_argument(
        "--symbols",
        default=None,
        help="Comma-separated symbols to limit scope, e.g. SPY,TLT (default: all active ETFs)",
    )
    parser.add_argument(
        "--pipeline-version",
        default="3.0.0",
        help="Pipeline version string stamped on feature_vectors rows (default: 3.0.0)",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=None,
        help="Number of parallel workers (default: APR infra.feature_factory.workers, fallback 1)",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()

    symbols: list[str] | None = None
    if args.symbols:
        symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]

    settings = Settings()
    db_conn = _connect_db(settings)

    run_fetch = not args.compute_only
    run_compute = not args.fetch_only

    # Load n_workers from CLI arg or APR. Use a short-lived query on the main
    # connection before workers spawn; run_compute_stage closes db_conn itself.
    n_workers: int = 1
    if args.workers is not None:
        n_workers = args.workers
    elif run_compute:
        cfg_tmp = _load_config_service(db_conn)
        n_workers = int(cfg_tmp.get_sync("infra.feature_factory.workers", 1))

    _logger.info(
        "backfill_start",
        run_fetch=run_fetch,
        run_compute=run_compute,
        client_id=args.client_id,
        symbols=symbols,
        pipeline_version=args.pipeline_version,
        n_workers=n_workers,
    )

    coverage: dict[tuple[str, str], dict] = {}

    try:
        if run_fetch:
            _logger.info("stage1_start")
            asyncio.run(
                run_fetch_stage(
                    settings=settings,
                    client_id=args.client_id,
                    symbols=symbols,
                    db_conn=db_conn,
                )
            )
            _logger.info("stage1_complete")

        if run_compute:
            _logger.info("stage2_start")
            # run_compute_stage closes db_conn before spawning workers.
            # Do not close db_conn in finally when compute ran.
            coverage, coverage_threshold = run_compute_stage(
                settings=settings,
                symbols=symbols,
                db_conn=db_conn,
                pipeline_version=args.pipeline_version,
                n_workers=n_workers,
            )
            db_conn = None  # already closed inside run_compute_stage
            _log_coverage_report(coverage, coverage_threshold)
            _logger.info("stage2_complete", pairs_computed=len(coverage))

        JOB_COMPLETED_TOTAL.add(1, {"job": _JOB, "status": "success"})
        _logger.info("backfill_complete")

    except Exception as error:
        JOB_COMPLETED_TOTAL.add(1, {"job": _JOB, "status": "failure"})
        _logger.error("backfill_failed", error=str(error))
        raise
    finally:
        if db_conn is not None:
            db_conn.close()
        flush_and_shutdown_metrics()


if __name__ == "__main__":
    try:
        init_otel_providers("backfill-feature-factory")
    except OTelInitError as error:
        print(f"[warn] OTel init failed — metrics disabled: {error}")
    main()
