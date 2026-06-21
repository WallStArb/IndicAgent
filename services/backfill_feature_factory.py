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
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import psycopg2
import psycopg2.extras
import structlog

# Set up sys.path before project imports
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.config.config_service import ConfigService
from src.config.settings import Settings, get_active_contracts
from src.core.service_utils import setup_service_logging
from src.intelligence.feature_cache import FeatureCache
from src.intelligence.feature_factory import FeatureFactory, FeatureFactoryConfig
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
_TARGET_TFS: list[str] = ["5m", "15m", "1h", "1d"]

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
WHERE symbol = %s AND timeframe = %s
ORDER BY timestamp ASC
"""

_FETCH_BARS_SINCE_SQL = """
SELECT timestamp, open, high, low, close, volume
FROM market_data_ohlcv
WHERE symbol = %s AND timeframe = %s AND timestamp >= %s
ORDER BY timestamp ASC
"""

_FETCH_BARS_WINDOW_SQL = """
SELECT timestamp, open, high, low, close, volume
FROM market_data_ohlcv
WHERE symbol = %s AND timeframe = %s
  AND timestamp >= %s AND timestamp < %s
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

_INSERT_FEATURE_VECTORS_SQL = """
INSERT INTO feature_vectors (
    symbol, tf, bar_ts, pipeline_version, regime, regime_label_source,
    momentum_z_5, momentum_z_20, range_position, bar_close_pos,
    gap_z, informed_flow, volume_z, ofi_z, ofi_div, cvd_slope_z, cmf,
    rel_volume, vwap_dev_sigma, atr_z, vol_ratio,
    poc_dist_atr, va_position, sr_support_dist, sr_resist_dist,
    hmm_regime_prob, hmm_entropy, hmm_duration, hurst, shannon, garch_ratio,
    hma_slope_z, adx, aroon_fast, aroon_slow,
    rsi_fast, rsi_mid, rsi_slow, cci_fast, cci_mid, cci_slow,
    vix_z, flight_quality, yield_slope_z,
    in_ny_session, in_london_kz, in_overlap, power_hour, opening_range,
    above_wk_vwap, dow_sin, dow_cos, month_position,
    ctf_momentum, ctf_vwap_align, ctf_regime_align,
    amihud_illiq_z, high_52w_dist, ret_skew_z, ret_acf1_z
) VALUES (
    %s, %s, %s, %s, %s, %s,
    %s, %s, %s, %s,
    %s, %s, %s, %s, %s, %s, %s,
    %s, %s, %s, %s,
    %s, %s, %s, %s,
    %s, %s, %s, %s, %s, %s,
    %s, %s, %s, %s,
    %s, %s, %s, %s, %s, %s,
    %s, %s, %s,
    %s, %s, %s, %s, %s,
    %s, %s, %s, %s,
    %s, %s, %s,
    %s, %s, %s, %s
)
ON CONFLICT (symbol, tf, bar_ts) DO NOTHING
"""


def _connect_db(settings: Settings) -> Any:
    """Synchronous psycopg2 connection."""
    conn = psycopg2.connect(dsn=settings.database_url)
    conn.autocommit = True
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


def _load_config_service(conn: Any) -> ConfigService:
    """Load APR feature.* keys into ConfigService cache-only mode."""
    cfg = ConfigService(database_url="")
    with conn.cursor() as cur:
        cur.execute(
            "SELECT cs.config_key, cs.config_value, csc.value_type "
            "FROM config_state cs "
            "JOIN config_schema csc USING (config_key)"
        )
        rows = cur.fetchall()
    for config_key, config_value, value_type in rows:
        cfg._cache[config_key] = cfg._parse_value(config_value, value_type)
    _logger.info("config_service_loaded", key_count=len(cfg._cache))
    return cfg


def _build_feature_factory_config(cfg: ConfigService) -> FeatureFactoryConfig:
    """Build FeatureFactoryConfig from APR keys. All fields from feature.* namespace."""
    return FeatureFactoryConfig(
        momentum_window_short=int(cfg.get_sync("feature.momentum.window_short", 5)),
        momentum_window_long=int(cfg.get_sync("feature.momentum.window_long", 20)),
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
    """Serialize a FeatureVector to a psycopg2 INSERT tuple."""
    return (
        symbol,
        tf,
        bar_ts,
        pipeline_version,
        regime,
        "filtered",  # regime_label_source always 'filtered' (D-07/SC-5)
        fv.momentum_z_5,
        fv.momentum_z_20,
        fv.range_position,
        fv.bar_close_pos,
        fv.gap_z,
        fv.informed_flow,
        fv.volume_z,
        fv.ofi_z,
        fv.ofi_div,
        fv.cvd_slope_z,
        fv.cmf,
        fv.rel_volume,
        fv.vwap_dev_sigma,
        fv.atr_z,
        fv.vol_ratio,
        fv.poc_dist_atr,
        fv.va_position,
        fv.sr_support_dist,
        fv.sr_resist_dist,
        fv.hmm_regime_prob,
        fv.hmm_entropy,
        fv.hmm_duration,
        fv.hurst,
        fv.shannon,
        fv.garch_ratio,
        fv.hma_slope_z,
        fv.adx,
        fv.aroon_fast,
        fv.aroon_slow,
        fv.rsi_fast,
        fv.rsi_mid,
        fv.rsi_slow,
        fv.cci_fast,
        fv.cci_mid,
        fv.cci_slow,
        fv.vix_z,
        fv.flight_quality,
        fv.yield_slope_z,
        fv.in_ny_session,
        fv.in_london_kz,
        fv.in_overlap,
        fv.power_hour,
        fv.opening_range,
        fv.above_wk_vwap,
        fv.dow_sin,
        fv.dow_cos,
        fv.month_position,
        fv.ctf_momentum,
        fv.ctf_vwap_align,
        fv.ctf_regime_align,
        fv.amihud_illiq_z,
        fv.high_52w_dist,
        fv.ret_skew_z,
        fv.ret_acf1_z,
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
    status_map = _load_status_map(db_conn, all_symbols, _TARGET_TFS)

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

                for tf in _TARGET_TFS:
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
) -> dict[tuple[str, str], dict]:
    """Compute FeatureVectors from market_data_ohlcv and batch-insert into feature_vectors.

    Reads bars in chunked sliding windows (T3: never full history at once).
    Checkpointed per (symbol, tf): skips status='complete' pairs.
    Records per-pair coverage vs theoretical_max (D-06 gate).

    Returns coverage map: {(symbol, tf): {"rows_written": N, "theoretical_max": M, "pct": P}}
    """
    cfg = _load_config_service(db_conn)
    config = _build_feature_factory_config(cfg)

    # Warm-up bars = dominant rolling window (momentum_zscore_window = 252)
    warm_up_bars = config.momentum_zscore_window

    # Pre-load cross-asset ETF bars for FeatureCache.update_cross_asset()
    spy_bars = _fetch_bars_from_db(db_conn, _SPY, "1d")
    tlt_bars = _fetch_bars_from_db(db_conn, _TLT, "1d")
    shy_bars = _fetch_bars_from_db(db_conn, _SHY, "1d")
    _logger.info(
        "cross_asset_loaded",
        spy=len(spy_bars),
        tlt=len(tlt_bars),
        shy=len(shy_bars),
    )

    contracts = get_active_contracts(settings)
    etf_contracts = _filter_etf_contracts(contracts, symbols)
    all_symbols = [c.symbol for c in etf_contracts]
    status_map = _load_status_map(db_conn, all_symbols, _TARGET_TFS)
    coverage: dict[tuple[str, str], dict] = {}

    for instrument in etf_contracts:
        symbol = instrument.symbol

        for tf in _TARGET_TFS:
            key = (symbol, tf)
            existing = status_map.get(key, {})

            # Skip if already computed
            if existing.get("status") == "complete":
                _logger.info("compute_skip_complete", symbol=symbol, tf=tf)
                rows_written = existing.get("rows_written", 0) or 0
                theoretical = existing.get("theoretical_max", 0) or 0
                pct = rows_written / theoretical if theoretical > 0 else 0.0
                coverage[key] = {
                    "rows_written": rows_written,
                    "theoretical_max": theoretical,
                    "pct": pct,
                }
                continue

            # Only compute if fetch is complete
            if not existing.get("fetch_complete"):
                _logger.warning("compute_skip_no_fetch", symbol=symbol, tf=tf)
                continue

            _logger.info("compute_start", symbol=symbol, tf=tf)

            # Mark in_progress
            with db_conn.cursor() as cur:
                cur.execute(_MARK_COMPUTE_STATUS_SQL, (symbol, tf, "in_progress"))
            db_conn.commit()

            try:
                rows_written = _compute_symbol_tf(
                    conn=db_conn,
                    symbol=symbol,
                    tf=tf,
                    config=config,
                    pipeline_version=pipeline_version,
                    warm_up_bars=warm_up_bars,
                    spy_bars=spy_bars,
                    tlt_bars=tlt_bars,
                    shy_bars=shy_bars,
                )

                depth_years = _DEPTH_YEARS[tf]
                theoretical = _theoretical_max(tf, depth_years, warm_up_bars)
                pct = rows_written / theoretical if theoretical > 0 else 0.0

                with db_conn.cursor() as cur:
                    cur.execute(
                        _MARK_COMPUTE_COMPLETE_SQL,
                        (rows_written, theoretical, symbol, tf),
                    )
                db_conn.commit()

                coverage[key] = {
                    "rows_written": rows_written,
                    "theoretical_max": theoretical,
                    "pct": pct,
                }

                if pct < 0.80:
                    _logger.warning(
                        "coverage_below_gate",
                        symbol=symbol,
                        tf=tf,
                        rows_written=rows_written,
                        theoretical_max=theoretical,
                        pct=round(pct, 4),
                    )
                else:
                    _logger.info(
                        "compute_complete",
                        symbol=symbol,
                        tf=tf,
                        rows_written=rows_written,
                        theoretical_max=theoretical,
                        pct=round(pct, 4),
                    )

            except Exception as error:
                error_msg = str(error)
                with db_conn.cursor() as cur:
                    cur.execute(_MARK_COMPUTE_FAILED_SQL, (error_msg, symbol, tf))
                db_conn.commit()
                _logger.error("compute_failed", symbol=symbol, tf=tf, error=error_msg)
                coverage[key] = {"rows_written": 0, "theoretical_max": 0, "pct": 0.0}

    return coverage


def _compute_symbol_tf(
    conn: Any,
    symbol: str,
    tf: str,
    config: FeatureFactoryConfig,
    pipeline_version: str,
    warm_up_bars: int,
    spy_bars: list[dict],
    tlt_bars: list[dict],
    shy_bars: list[dict],
) -> int:
    """Compute FeatureVectors for one (symbol, tf) pair.

    Reads bars in a growing sliding window (keep full history for compute
    correctness — FeatureFactory.compute is stateless and needs full array).
    Writes in batches of _INSERT_BATCH_SIZE.

    Returns total rows inserted into feature_vectors.
    """
    cache = FeatureCache()

    # Pre-seed cross-asset state from daily cross-asset bars
    cache.update_cross_asset(spy_bars, tlt_bars, shy_bars, config)

    # Load all bars — sliding window to avoid OOM on large sets
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

    insert_batch: list[tuple] = []
    total_inserted = 0

    for i in range(1, total_bars):
        window_start = max(0, i - _READ_CHUNK_BARS)
        window = bars[window_start : i + 1]

        # Refresh regime features periodically (cross-asset seeded once before loop)
        if i % config.regime_cache_refresh_bars == 0:
            cache.refresh_regime(window, config)

        # Skip warm-up bars (insufficient history for stable features)
        if i < warm_up_bars:
            continue

        bar_ts = window[-1]["ts"]
        last_bar = window[-1]
        fv = FeatureFactory.compute(window, symbol, tf, cache, config)

        cache.advance_bar(
            bar_ts, last_bar["high"], last_bar["low"], last_bar["close"], last_bar["volume"]
        )

        row = _vector_to_params(
            symbol=symbol,
            tf=tf,
            bar_ts=bar_ts,
            pipeline_version=pipeline_version,
            regime=None,  # Regime label assigned by HMM downstream (Phase 138)
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

    # Flush remaining batch
    if insert_batch:
        _batch_insert(conn, insert_batch)
        total_inserted += len(insert_batch)

    return total_inserted


def _batch_insert(conn: Any, rows: list[tuple]) -> None:
    """Batch-insert feature_vectors rows via psycopg2 execute_batch."""
    if not rows:
        return
    with conn.cursor() as cur:
        psycopg2.extras.execute_batch(cur, _INSERT_FEATURE_VECTORS_SQL, rows)
    conn.commit()


def _log_coverage_report(coverage: dict[tuple[str, str], dict]) -> None:
    """Log per-pair coverage vs theoretical_max; flag pairs below 80%."""
    below_gate: list[tuple[str, str, int, int, float]] = []
    for (symbol, tf), data in sorted(coverage.items()):
        pct = data.get("pct", 0.0)
        rows = data.get("rows_written", 0)
        theoretical = data.get("theoretical_max", 0)
        if pct < 0.80:
            below_gate.append((symbol, tf, rows, theoretical, pct))

    _logger.info(
        "coverage_report",
        total_pairs=len(coverage),
        below_80pct=len(below_gate),
    )

    if below_gate:
        _logger.warning(
            "d06_gate_candidates_below_80pct",
            pairs=[
                {"symbol": s, "tf": t, "rows": r, "theoretical": th, "pct": round(p, 4)}
                for s, t, r, th, p in below_gate
            ],
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

    _logger.info(
        "backfill_start",
        run_fetch=run_fetch,
        run_compute=run_compute,
        client_id=args.client_id,
        symbols=symbols,
        pipeline_version=args.pipeline_version,
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
            coverage = run_compute_stage(
                settings=settings,
                symbols=symbols,
                db_conn=db_conn,
                pipeline_version=args.pipeline_version,
            )
            _log_coverage_report(coverage)
            _logger.info("stage2_complete", pairs_computed=len(coverage))

        JOB_COMPLETED_TOTAL.add(1, {"job": _JOB, "status": "success"})
        _logger.info("backfill_complete")

    except Exception as error:
        JOB_COMPLETED_TOTAL.add(1, {"job": _JOB, "status": "failure"})
        _logger.error("backfill_failed", error=str(error))
        raise
    finally:
        db_conn.close()
        flush_and_shutdown_metrics()


if __name__ == "__main__":
    try:
        init_otel_providers("backfill-feature-factory")
    except OTelInitError as error:
        print(f"[warn] OTel init failed — metrics disabled: {error}")
    main()
