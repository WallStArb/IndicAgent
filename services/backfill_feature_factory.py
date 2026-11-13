#!/usr/bin/env python3
"""Backfill Feature Factory: the feature_vectors rebuild writer (the IBKR fetch stage was removed
2026-11-13 with the IBKR lane; bars arrive through the raw-capture loaders).

The single rebuild writer for feature_vectors (phase 186, D-28).
A unit of work is (symbol chunk, tf, calendar-year range), recorded as one provenance_batch row
(D-24) with target_table feature_vectors; a rerun after a kill skips every unit whose record is
completed and recomputes the rest (D-32a). Workers are compute-only: one task per symbol runs the
kernel registry ONCE over the symbol's whole history (regime and regime_volatility included, in
the same pass: no UPDATE path exists, no separate regime pass, R-10) and writes one spool
file per (symbol, unit) under a directory the main process owns; they return paths and row
counts, never row lists (todo 339). The main process merges a unit's symbol spools in time order
and streams them through bulk_load() on one serial writer connection.

Default: both stages run in sequence. Source invariant (T1/D-05): only market_data_ohlcv (via the
market_data_ohlcv_tradeable view, todo 124) is read for compute.

Kill and resume (CLAUDE.md orphan-worker rules). Killing the main process leaves its forkserver
workers running and a backend possibly mid-COPY:

    kill <main_pid>
    ps -eo pid,cmd | awk '/backfill_feature_factory/ && !/awk/ {print $1}' | xargs kill
    # confirm zero remain, then look for a leftover write backend and terminate it:
    #   select pid, state, wait_event from pg_stat_activity
    #    where state = 'active' and wait_event = 'ClientWrite' and query like 'COPY feature_vectors%';
    #   select pg_terminate_backend(<pid>);

then relaunch the same command: completed units are skipped, a killed unit left a `started`
provenance row and zero data rows (the COPY and the completed record commit together) and is
retaken. Never edit this module, the kernels it runs or anything they import while a run is live
or resumable: the unit code key hashes them, so one edit renames every unit. Never launch a
second run while one is live: startup purges every group-* spool directory, which would delete
the live run's in-flight spools (186-26's precondition check enforces this).

The data horizon (--data-horizon, default the first day of the current UTC month) is the exclusive
end of every unit. It is pinned so nightly bars landing between a kill and its resume cannot move
a completed unit's identity; a resume must pass the same horizon.

Usage:
    python services/backfill_feature_factory.py --data-horizon 2026-10-01
    python services/backfill_feature_factory.py --symbols SPY,TLT --tf 1d
"""

from __future__ import annotations

import argparse
import dataclasses
import functools
import hashlib
import heapq
import math
import operator
import shutil
import sys
import tempfile
import time
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from datetime import UTC, date, datetime, timedelta
from datetime import time as dt_time
from pathlib import Path
from typing import Any, NamedTuple

import numpy as np
import psycopg
import structlog

# Set up sys.path before project imports
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


from services._batch_utils import (
    _BULK_LOAD_COMPRESS_ON_COMPLETE_APR_KEY,
    _BULK_LOAD_DEFAULT_COMPRESS_ON_COMPLETE,
    BAR_DIGEST_ABSENT_SYMBOL,
    BulkLoadSpec,
    parse_run_id,
)
from services._batch_utils import bar_content_digests as _bar_content_digests
from services._batch_utils import bulk_load as _bulk_load
from services._batch_utils import completed_provenance_batch as _completed_provenance_batch
from services._batch_utils import compress_completed_chunks as _compress_completed_chunks
from services._batch_utils import get_dict_config as _get_dict_config
from services._batch_utils import get_list_config as _get_list_config
from services._batch_utils import kernel_code_key as _kernel_code_key
from services._batch_utils import load_config_service_sync as _load_config_service
from services._batch_utils import make_worker_pool as _make_worker_pool
from services._batch_utils import short_lived_conn as _short_lived_conn
from services.corpus_rerun_apr import load_corpus_rerun_apr
from services.corpus_rerun_budget import DiskGuardRefused, UnitDiskGuard
from services.rebuild_preconditions import CoverageRow
from src.config.config_service import ConfigService
from src.config.settings import Settings, get_active_contracts
from src.core.market_calendar import get_market_calendar
from src.core.real_column_range import clamp_to_real_range_array
from src.core.service_utils import format_iso_ts, setup_service_logging
from src.intelligence.bars.integrity_checks import INFO_PROVEN_START
from src.intelligence.bars.sources import DERIVATION_OWNED_TIMEFRAMES, GRID_TIMEFRAMES
from src.intelligence.bars.vendor_kind import DERIVED_PAIR, grid_volume_basis, volume_basis
from src.intelligence.bars.verdict_gate import MONITOR_TYPE
from src.intelligence.feature_factory import (
    DailySeriesRecord,
    FeatureFactoryConfig,
    _batch_kernel_inputs,
    _cross_tf_kernel_inputs,
    _daily_records_kernel_inputs,
    _macro_kernel_inputs,
)
from src.intelligence.features.contract.registry import (
    Kernel,
    KernelRegistry,
    compute_kernels,
    default_registry,
)
from src.intelligence.features.feature_vector_persistence import (
    feature_vector_row_values,
    feature_vectors_columns,
    feature_vectors_numeric_columns,
    feature_vectors_output_columns,
)
from src.intelligence.features.kernels._hmm import HmmConfig
from src.intelligence.features.kernels._primitives import none_mask_name
from src.intelligence.features.kernels.cross_tf import (
    _build_ctf_series,
    _rekey_ctf_series_to_actual_close,
)
from src.intelligence.features.kernels.distribution import build_distribution_series
from src.intelligence.features.kernels.dividend import (
    build_dividend_yield_series,
    reconciled_amounts,
)
from src.intelligence.features.kernels.macro import (
    HYG,
    LQD,
    SHY,
    SPY,
    TIP,
    TLT,
    bar_ts_ns,
    build_cross_asset_series,
    build_symbol_beta_series,
)
from src.intelligence.features.kernels.residual import build_market_residual_series
from src.observability.metrics import JOB_COMPLETED_TOTAL, flush_and_shutdown_metrics
from src.observability.otel import OTelInitError, init_otel_providers

setup_service_logging("logs/backfill_feature_factory.log")

_logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_JOB = "backfill-feature-factory"

# Target timeframes for backfill (1m is NOT a backfill target — live pipeline owns 1m,
# confirmed intentional, todo 199). This literal is now only the APR fallback default --
# the live driver is feature.factory.target_timeframes, loaded via _get_target_timeframes()
# below (todo 199: behavioral-list APR migration, CLAUDE.md APR mandate category 2).
_TARGET_TIMEFRAMES_DEFAULT: list[str] = ["5m", "15m", "1h", "1d"]

# Timeframes whose market_data_ohlcv rows are owned by services/bar_derivation
# (D-06/D-15 single writer, plan 185-18 task 1b): the fetch stage refuses them
# outright instead of racing the derivation. DERIVATION_OWNED_TIMEFRAMES in
# src/intelligence/bars/sources.py is the single definition; this module
# imports the fence instead of restating the set.
#
# The refusal warning fires once per timeframe per process: the APR default
# list legitimately still names the owned timeframes (the rebuild stage reads
# the same key and processes them), so every fetch run narrows through this
# fence -- per-run warnings would be noise, not signal.
_OWNED_TF_WARNED: set[str] = set()


def _restrict_timeframes(
    configured: list[str],
    only: list[str] | None,
    *,
    refuse_derivation_owned: bool = False,
) -> list[str]:
    """`only` (the --tf flag) narrows the APR set, keeping its order; a tf outside it raises
    rather than being silently skipped (todo 421: rebuild 1d alone without recomputing
    every intraday bar).

    With refuse_derivation_owned=True (the fetch stage, plan 185-18 task 1b):
    an owned tf named explicitly by `only` raises -- the operator asked for a
    timeframe this stage never writes -- while owned tfs arriving via the
    configured list are dropped with one warning per tf (older deployments,
    onboarding cohorts). The rebuild stage passes the default: it reads
    stored bars, the derived grid included, and writes none of them."""
    if only is None:
        narrowed = configured
    else:
        unknown = [tf for tf in only if tf not in configured]
        if unknown:
            raise ValueError(
                f"--tf {unknown!r} not in feature.factory.target_timeframes {configured!r}"
            )
        narrowed = [tf for tf in configured if tf in only]
    if not refuse_derivation_owned:
        return narrowed
    explicit_owned = [tf for tf in (only or []) if tf in DERIVATION_OWNED_TIMEFRAMES]
    if explicit_owned:
        raise ValueError(
            f"--tf {explicit_owned!r} is owned by services/bar_derivation "
            "(plan 185-18 task 1b): the fetch stage never writes 15m/1h/1d"
        )
    kept = [tf for tf in narrowed if tf not in DERIVATION_OWNED_TIMEFRAMES]
    for tf in narrowed:
        if tf in DERIVATION_OWNED_TIMEFRAMES and tf not in _OWNED_TF_WARNED:
            _OWNED_TF_WARNED.add(tf)
            _logger.warning(
                "fetch_stage_refuses_derivation_owned_tf",
                tf=tf,
                reason="market_data_ohlcv rows at this timeframe are owned by "
                "services/bar_derivation (plan 185-18 task 1b)",
            )
    return kept


TARGET_TIMEFRAMES_KEY = "feature.factory.target_timeframes"


def _get_target_timeframes(cfg: ConfigService) -> list[str]:
    """Load the APR-backed set of timeframes backfill_feature_factory processes.

    feature.factory.target_timeframes (migration 278, todo 199) -- JSON array,
    default ["5m", "15m", "1h", "1d"], byte-identical to the prior hardcoded
    _TARGET_TIMEFRAMES module constant unless an operator explicitly reconfigures it.

    Validated here against _BARS_PER_DAY.keys(): every configured tf needs a bars-per-day
    entry, or bars_to_fetch_window raises partway through a run (silent or late failure is
    worse than a loud one at load time).
    """
    tfs = _get_list_config(cfg, TARGET_TIMEFRAMES_KEY, list(_TARGET_TIMEFRAMES_DEFAULT))
    _unknown = [tf for tf in tfs if tf not in _BARS_PER_DAY]
    if _unknown:
        raise AssertionError(
            f"feature.factory.target_timeframes contains {_unknown!r}, which has no "
            f"_BARS_PER_DAY entry ({sorted(_BARS_PER_DAY)}) -- add one before enabling this tf"
        )
    return tfs


# Bars per trading day per TF (objective formula)
_BARS_PER_DAY: dict[str, int] = {
    "5m": 78,
    "15m": 26,
    "1h": 6,
    "1d": 1,
}

# Rows per memory block of the rebuild: one fetch round trip of a symbol's bars and one spool
# write block. APR fallback; the live value is infra.feature_factory.rebuild_block_rows
# (migration 429).
_REBUILD_BLOCK_ROWS_KEY = "infra.feature_factory.rebuild_block_rows"
_REBUILD_BLOCK_ROWS_DEFAULT: int = 10_000

# Cross-asset symbols for FeatureCache.update_cross_asset() -- SPY/TLT/SHY/TIP/HYG/LQD
# and CROSS_ASSET_SYMBOLS now live in src.intelligence.features.kernels.macro
# (Plan 151-09 Task 1 moved them there alongside build_cross_asset_series/
# build_symbol_beta_series -- single definition project-wide).

# CTF (cross-timeframe) higher-timeframe source mapping (config.ctf_higher_tf_map,
# feature.ctf.higher_tf_map, todo 242) is shared with feature_vector_pipeline.py's
# live-path update (todo 241). 1d uses itself as HTF: CTF at bar T computed from daily
# bars up to T (causal; bisect_right selects the current bar's CTF which is valid since
# the bar has closed at computation time).

# ---------------------------------------------------------------------------
# DB helpers (psycopg sync — mirrors run_historical_pipeline.py pattern)
# ---------------------------------------------------------------------------

_FETCH_BARS_SQL = """
SELECT timestamp, open, high, low, close, volume, vendor, kind
FROM market_data_ohlcv_tradeable
WHERE symbol = %s AND timeframe = %s
ORDER BY timestamp ASC
"""

_FETCH_BARS_SINCE_SQL = _FETCH_BARS_SQL.replace("ORDER BY", "  AND timestamp >= %s\nORDER BY")
_FETCH_BARS_UNTIL_SQL = _FETCH_BARS_SQL.replace("ORDER BY", "  AND timestamp < %s\nORDER BY")
# Until the horizon and from the name's proven start (design D4): the rebuild's series.
_FETCH_BARS_UNTIL_FLOOR_SQL = _FETCH_BARS_UNTIL_SQL.replace(
    "ORDER BY", "  AND timestamp >= %s\nORDER BY"
)


# The 5m rows a derived grid bar was built from, by (vendor, kind): the evidence for the grid
# bar's volume basis (bars/vendor_kind.grid_volume_basis). Read from the canonical table, not the
# tradeable view: a constituent later quarantined or zero-volume still built the derived bar, and
# hiding it would fail the series with "no constituent" for a basis that is known.
_FETCH_5M_PROVENANCE_SQL = """
SELECT timestamp, vendor, kind
FROM market_data_ohlcv
WHERE symbol = %s AND timeframe = '5m' AND timestamp >= %s AND timestamp < %s
ORDER BY timestamp ASC
"""


def _pair_bases(pairs: Iterable[tuple[str, str]]) -> np.ndarray:
    """The volume basis of each (vendor, kind), mapped once per distinct pair. A derived pair has
    no basis of its own and reads -1 (the caller takes it from the 5m constituents)."""
    rows = list(pairs)
    table = {p: -1 if p == DERIVED_PAIR else volume_basis(*p) for p in set(rows)}
    return np.fromiter((table[p] for p in rows), dtype=np.int64, count=len(rows))


def _epoch_seconds(times: Iterable[datetime]) -> np.ndarray:
    return np.fromiter((int(t.timestamp()) for t in times), dtype=np.int64)


def _volume_basis_codes(
    conn: Any,
    symbol: str,
    tf: str,
    times: Sequence[datetime],
    vendors: Sequence[str],
    kinds: Sequence[str],
) -> np.ndarray:
    """The `volume_basis` code of each bar (todo 555), derived from its canonical (vendor, kind)
    through the one mapping in bars/vendor_kind.py. A derived grid bar takes its basis from its
    5m constituents. An unmapped pair raises: a basis never defaults."""
    codes = _pair_bases(zip(vendors, kinds))
    derived = np.flatnonzero(codes < 0)
    if derived.size:
        minutes = GRID_TIMEFRAMES[tf]
        with conn.cursor() as cur:
            cur.execute(
                _FETCH_5M_PROVENANCE_SQL,
                (symbol, times[derived[0]], times[derived[-1]] + timedelta(minutes=minutes)),
            )
            constituents = cur.fetchall()
        codes[derived] = grid_volume_basis(
            _epoch_seconds(times[i] for i in derived),
            minutes,
            _epoch_seconds(t for t, _, _ in constituents),
            _pair_bases((vendor, kind) for _, vendor, kind in constituents),
        )
    return codes


def _nan_if_null(value: Any) -> float:
    """A NULL volume is NaN, never filled. The tradeable view serves none since migration 543;
    one that appears reaches compute as NaN and raises there (todo 564)."""
    return float("nan") if value is None else float(value)


# open, high, low, close, volume: only volume is nullable in the view.
_BAR_CONVERTERS = (float, float, float, float, _nan_if_null)


def _connect_db(settings: Settings) -> Any:
    """Synchronous psycopg connection."""
    conn = psycopg.connect(settings.database_url)
    conn.autocommit = True
    # No register_uuid() equivalent needed -- psycopg adapts uuid.UUID (e.g.
    # feature_vector_id, a content-key UUID) natively, unlike psycopg2.
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
        power_hour_start_utc_hour=int(
            cfg.get_sync("feature.session.power_hour_start_utc_hour", 19)
        ),
        power_hour_end_utc_hour=int(cfg.get_sync("feature.session.power_hour_end_utc_hour", 21)),
        opening_range_start_minute=int(
            cfg.get_sync("feature.session.opening_range_start_minute", 810)
        ),
        opening_range_end_minute=int(cfg.get_sync("feature.session.opening_range_end_minute", 900)),
        ret_lag_fast=int(cfg.get_sync("feature.ret_lag.fast", 5)),
        ret_lag_mid=int(cfg.get_sync("feature.ret_lag.mid", 20)),
        ret_lag_slow=int(cfg.get_sync("feature.ret_lag.slow", 60)),
        overnight_gap_window=int(cfg.get_sync("feature.overnight_gap.window", 20)),
        dollar_vol_window=int(cfg.get_sync("feature.dollar_vol.window", 20)),
        vol_range_ratio_window=int(cfg.get_sync("feature.vol_range_ratio.window", 20)),
        vol_trend_fast=int(cfg.get_sync("feature.vol_trend.fast", 5)),
        vol_trend_slow=int(cfg.get_sync("feature.vol_trend.slow", 20)),
        up_vol_ratio_fast=int(cfg.get_sync("feature.up_vol_ratio.fast", 5)),
        up_vol_ratio_slow=int(cfg.get_sync("feature.up_vol_ratio.slow", 20)),
        vol_percentile_window=int(cfg.get_sync("feature.vol_percentile.window", 20)),
        vol_persistence_window=int(cfg.get_sync("feature.vol_persistence.window", 20)),
        vol_std_window=int(cfg.get_sync("feature.vol_std.window", 20)),
        mfi_fast=int(cfg.get_sync("feature.mfi.fast", 7)),
        mfi_slow=int(cfg.get_sync("feature.mfi.slow", 14)),
        obv_window=int(cfg.get_sync("feature.obv.window", 20)),
        dist_window_fast=int(cfg.get_sync("feature.breakout.dist_window_fast", 20)),
        dist_window_slow=int(cfg.get_sync("feature.breakout.dist_window_slow", 50)),
        range_window_fast=int(cfg.get_sync("feature.breakout.range_window_fast", 20)),
        range_window_slow=int(cfg.get_sync("feature.breakout.range_window_slow", 50)),
        stoch_window_fast=int(cfg.get_sync("feature.breakout.stoch_window_fast", 14)),
        stoch_window_slow=int(cfg.get_sync("feature.breakout.stoch_window_slow", 50)),
        percentile_window_fast=int(cfg.get_sync("feature.breakout.percentile_window_fast", 50)),
        percentile_window_slow=int(cfg.get_sync("feature.breakout.percentile_window_slow", 200)),
        efficiency_window_fast=int(cfg.get_sync("feature.breakout.efficiency_window_fast", 10)),
        efficiency_window_slow=int(cfg.get_sync("feature.breakout.efficiency_window_slow", 50)),
        ret_kurtosis_fast=int(cfg.get_sync("feature.ret_kurtosis.fast", 10)),
        ret_kurtosis_slow=int(cfg.get_sync("feature.ret_kurtosis.slow", 40)),
        ret_kurtosis_zscore_window=int(cfg.get_sync("feature.ret_kurtosis.zscore_window", 20)),
        updown_ratio_fast=int(cfg.get_sync("feature.updown_ratio.fast", 5)),
        updown_ratio_slow=int(cfg.get_sync("feature.updown_ratio.slow", 20)),
        streak_window=int(cfg.get_sync("feature.streak.window", 20)),
        realized_var_fast=int(cfg.get_sync("feature.realized_var.fast", 5)),
        realized_var_slow=int(cfg.get_sync("feature.realized_var.slow", 20)),
        vol_of_vol_window=int(cfg.get_sync("feature.vol_of_vol.window", 20)),
        high_low_corr_window=int(cfg.get_sync("feature.high_low_corr.window", 20)),
        variance_ratio_fast=int(cfg.get_sync("feature.variance_ratio.fast", 5)),
        variance_ratio_slow=int(cfg.get_sync("feature.variance_ratio.slow", 20)),
        vol_asymmetry_window=int(cfg.get_sync("feature.vol_asymmetry.window", 20)),
        bb_pct_b_fast=int(cfg.get_sync("feature.bb_pct_b.fast", 20)),
        bb_pct_b_slow=int(cfg.get_sync("feature.bb_pct_b.slow", 50)),
        hv_fast=int(cfg.get_sync("feature.hv.fast", 10)),
        hv_slow=int(cfg.get_sync("feature.hv.slow", 30)),
        hv_ratio_window=int(cfg.get_sync("feature.hv.ratio_window", 20)),
        parkinson_vol_window=int(cfg.get_sync("feature.parkinson_vol.window", 10)),
        parkinson_vol_zscore_window=int(cfg.get_sync("feature.parkinson_vol.zscore_window", 20)),
        garman_klass_vol_window=int(cfg.get_sync("feature.garman_klass_vol.window", 10)),
        garman_klass_vol_zscore_window=int(
            cfg.get_sync("feature.garman_klass_vol.zscore_window", 20)
        ),
        yang_zhang_vol_window=int(cfg.get_sync("feature.yang_zhang_vol.window", 20)),
        yang_zhang_vol_zscore_window=int(cfg.get_sync("feature.yang_zhang_vol.zscore_window", 20)),
        vol_velocity_window=int(cfg.get_sync("feature.vol_velocity.window", 20)),
        intraday_noise_window=int(cfg.get_sync("feature.intraday_noise.window", 20)),
        price_vol_corr_fast=int(cfg.get_sync("feature.price_vol_corr.fast", 10)),
        price_vol_corr_slow=int(cfg.get_sync("feature.price_vol_corr.slow", 30)),
        momentum_velocity_window=int(cfg.get_sync("feature.momentum_velocity.window", 14)),
        vwap_velocity_window=int(cfg.get_sync("feature.vwap_velocity.window", 14)),
        rsi_velocity_window=int(cfg.get_sync("feature.rsi_velocity.window", 14)),
        ofi_velocity_window=int(cfg.get_sync("feature.ofi_velocity.window", 14)),
        cvd_velocity_window=int(cfg.get_sync("feature.cvd_velocity.window", 14)),
        volume_velocity_window=int(cfg.get_sync("feature.volume_velocity.window", 14)),
        extreme_move_sigma_threshold=float(
            cfg.get_sync("feature.bars_since_extreme_move.sigma_threshold", 2.0)
        ),
        vol_spike_threshold=float(cfg.get_sync("feature.bars_since_vol_spike.threshold", 2.0)),
        tip_tlt_zscore_window=int(cfg.get_sync("feature.tip_tlt.zscore_window", 252)),
        hyg_lqd_zscore_window=int(cfg.get_sync("feature.hyg_lqd.zscore_window", 252)),
        sb_corr_window_fast=int(cfg.get_sync("feature.sb_corr.window_fast", 30)),
        sb_corr_window_slow=int(cfg.get_sync("feature.sb_corr.window_slow", 60)),
        sb_corr_zscore_window=int(cfg.get_sync("feature.sb_corr.zscore_window", 252)),
        factor_beta_window=int(cfg.get_sync("feature.factor_beta.window", 60)),
        factor_beta_zscore_window=int(cfg.get_sync("feature.factor_beta.zscore_window", 252)),
        canary_rng_seed=int(cfg.get_sync("alpha.ic.canary_rng_seed", 90042)),
        session_vp_value_area_pct=float(cfg.get_sync("feature.session_vp.value_area_pct", 0.70)),
        session_vp_n_buckets=int(cfg.get_sync("feature.session_vp.n_buckets", 50)),
        session_vp_hvn_threshold=float(cfg.get_sync("feature.session_vp.hvn_threshold", 0.80)),
        session_vp_lvn_threshold=float(cfg.get_sync("feature.session_vp.lvn_threshold", 0.20)),
        session_vp_rolling_window=int(cfg.get_sync("feature.session_vp.rolling_window", 480)),
        sr_window=int(cfg.get_sync("feature.sr.window", 10)),
        sr_cluster_atr_mult=float(cfg.get_sync("feature.sr.cluster_atr_mult", 0.5)),
        sr_lookback_by_tf=_get_dict_config(
            cfg, "feature.sr.lookback_by_tf", {"1m": 60, "5m": 60, "15m": 80, "1h": 120, "1d": 60}
        ),
        smc_order_blocks_lookback=int(cfg.get_sync("feature.smc.order_blocks.lookback", 100)),
        smc_order_blocks_impulse_bars=int(cfg.get_sync("feature.smc.order_blocks.impulse_bars", 3)),
        smc_order_blocks_significant_move_pct=float(
            cfg.get_sync("feature.smc.order_blocks.significant_move_pct", 0.003)
        ),
        smc_order_blocks_opposing_candle_lookback=int(
            cfg.get_sync("feature.smc.order_blocks.opposing_candle_lookback", 10)
        ),
        smc_order_blocks_strength_fallback=float(
            cfg.get_sync("feature.smc.order_blocks.strength_fallback", 0.5)
        ),
        smc_fvg_lookback=int(cfg.get_sync("feature.smc.fvg.lookback", 100)),
        smc_liquidity_sweeps_lookback=int(
            cfg.get_sync("feature.smc.liquidity_sweeps.lookback", 120)
        ),
        smc_liquidity_sweeps_swing_neighbor=int(
            cfg.get_sync("feature.smc.liquidity_sweeps.swing_neighbor", 5)
        ),
        smc_liquidity_sweeps_reclaim_bars=int(
            cfg.get_sync("feature.smc.liquidity_sweeps.reclaim_bars", 3)
        ),
        smc_liquidity_sweeps_depth_ramp_max_pct=float(
            cfg.get_sync("feature.smc.liquidity_sweeps.depth_ramp_max_pct", 2.0)
        ),
        smc_liquidity_sweeps_reclaim_velocity_ramp_max=float(
            cfg.get_sync("feature.smc.liquidity_sweeps.reclaim_velocity_ramp_max", 0.5)
        ),
        smc_liquidity_pools_lookback=int(cfg.get_sync("feature.smc.liquidity_pools.lookback", 150)),
        smc_liquidity_pools_swing_neighbor=int(
            cfg.get_sync("feature.smc.liquidity_pools.swing_neighbor", 5)
        ),
        smc_liquidity_pools_equal_level_tolerance_atr_mult=float(
            cfg.get_sync("feature.smc.liquidity_pools.equal_level_tolerance_atr_mult", 0.75)
        ),
        smc_liquidity_pools_session_bars=int(
            cfg.get_sync("feature.smc.liquidity_pools.session_bars", 390)
        ),
        smc_liquidity_pools_significance_weights=_get_dict_config(
            cfg,
            "feature.smc.liquidity_pools.significance_weights",
            {
                "eq_highs_3": 0.75,
                "eq_lows_3": 0.75,
                "eq_highs_2": 0.60,
                "eq_lows_2": 0.60,
                "session_high": 0.50,
                "session_low": 0.50,
            },
        ),
        smc_zones_lookback=int(cfg.get_sync("feature.smc.zones.lookback", 150)),
        smc_zones_impulse_atr_mult=float(cfg.get_sync("feature.smc.zones.impulse_atr_mult", 1.5)),
        smc_zones_base_body_ratio=float(cfg.get_sync("feature.smc.zones.base_body_ratio", 0.5)),
        smc_zones_base_atr_mult=float(cfg.get_sync("feature.smc.zones.base_atr_mult", 1.0)),
        smc_zones_max_base_bars=int(cfg.get_sync("feature.smc.zones.max_base_bars", 5)),
        smc_zones_zone_height_cap_atr_mult=float(
            cfg.get_sync("feature.smc.zones.zone_height_cap_atr_mult", 2.5)
        ),
        smc_zones_impulse_overlap_atr_mult=float(
            cfg.get_sync("feature.smc.zones.impulse_overlap_atr_mult", 0.4)
        ),
        smc_zones_freshness_decay_k=float(cfg.get_sync("feature.smc.zones.freshness_decay_k", 0.5)),
        smc_zones_strength_premium_align_mult=float(
            cfg.get_sync("feature.smc.zones.strength_premium_align_mult", 1.20)
        ),
        smc_zones_strength_fvg_align_mult=float(
            cfg.get_sync("feature.smc.zones.strength_fvg_align_mult", 1.15)
        ),
        smc_zones_age_penalty_floor=float(
            cfg.get_sync("feature.smc.zones.age_penalty_floor", 0.70)
        ),
        smc_zones_age_penalty_window_bars=int(
            cfg.get_sync("feature.smc.zones.age_penalty_window_bars", 200)
        ),
        smc_zones_age_penalty_max_pct=float(
            cfg.get_sync("feature.smc.zones.age_penalty_max_pct", 0.30)
        ),
        smc_zones_max_tracked_zones=int(cfg.get_sync("feature.smc.zones.max_tracked_zones", 5)),
        smc_bos_choch_lookback=int(cfg.get_sync("feature.smc.bos_choch.lookback", 120)),
        smc_bos_choch_swing_neighbor=int(cfg.get_sync("feature.smc.bos_choch.swing_neighbor", 5)),
        swing_pivot_window=int(cfg.get_sync("feature.swing.pivot_window", 5)),
        swing_lookback_bars=int(cfg.get_sync("feature.swing.lookback_bars", 120)),
        trend_structure_atr_strength_divisor=float(
            cfg.get_sync("feature.trend_structure.atr_strength_divisor", 5.0)
        ),
        trend_structure_range_lookback_bars=int(
            cfg.get_sync("feature.trend_structure.range_lookback_bars", 20)
        ),
        swing_momentum_confirm_n=int(cfg.get_sync("feature.swing_momentum.confirm_n", 3)),
        swing_momentum_max_extremes=int(cfg.get_sync("feature.swing_momentum.max_extremes", 6)),
        swing_momentum_lookback_bars=int(cfg.get_sync("feature.swing_momentum.lookback_bars", 60)),
        swing_momentum_reference_bars=int(
            cfg.get_sync("feature.swing_momentum.reference_bars", 20)
        ),
        swing_momentum_speed_factor_min=float(
            cfg.get_sync("feature.swing_momentum.speed_factor_min", 0.1)
        ),
        swing_momentum_speed_factor_max=float(
            cfg.get_sync("feature.swing_momentum.speed_factor_max", 3.0)
        ),
        swing_momentum_energy_divisor=float(
            cfg.get_sync("feature.swing_momentum.energy_divisor", 3.0)
        ),
        swing_momentum_intensity_ramp_lo=float(
            cfg.get_sync("feature.swing_momentum.intensity_ramp_lo", 1.0)
        ),
        swing_momentum_intensity_ramp_hi=float(
            cfg.get_sync("feature.swing_momentum.intensity_ramp_hi", 2.0)
        ),
        fib_cluster_atr_divisor=float(cfg.get_sync("feature.fib.cluster_atr_divisor", 2.0)),
        atr_normalization_min_pct=float(
            cfg.get_sync("feature.atr_normalization.min_atr_pct", 0.0001)
        ),
        ctf_higher_tf_map=_get_dict_config(
            cfg, "feature.ctf.higher_tf_map", {"5m": "1h", "15m": "1h", "1h": "1d", "1d": "1d"}
        ),
        ctf_vwap_window=int(cfg.get_sync("feature.ctf.vwap_window", 20)),
        market_residual_z_window=int(cfg.get_sync("feature.market_residual.z_window", 252)),
        idiosyncratic_volatility_window=int(
            cfg.get_sync("feature.idiosyncratic_volatility.window", 21)
        ),
        market_residual_lag1_acf_window=int(
            cfg.get_sync("feature.market_residual.lag1_acf_window", 63)
        ),
        residual_beta_stability_window=int(
            cfg.get_sync("feature.residual_beta_stability.window", 60)
        ),
        max_daily_return_window=int(cfg.get_sync("feature.max_daily_return.window", 21)),
        max_drawdown_window=int(cfg.get_sync("feature.max_drawdown.window", 252)),
        downside_deviation_window=int(cfg.get_sync("feature.downside_deviation.window", 252)),
        size_proxy_window=int(cfg.get_sync("feature.size_proxy.window", 63)),
        dividend_yield_window=int(cfg.get_sync("feature.dividend_yield.window", 252)),
        earnings_season_start_days=int(cfg.get_sync("feature.earnings_season.start_days", 14)),
        earnings_season_end_days=int(cfg.get_sync("feature.earnings_season.end_days", 42)),
        high_low_spread_window=int(cfg.get_sync("feature.high_low_spread.window", 21)),
        roll_spread_window=int(cfg.get_sync("feature.roll_spread.window", 252)),
        amihud_min_valid_fraction=float(cfg.get_sync("feature.amihud.min_valid_fraction", 0.8)),
        hmm=HmmConfig.from_values(cfg.get_sync),
    )


def _fetch_bars_from_db(
    conn: Any,
    symbol: str,
    tf: str,
    since: datetime | None = None,
    until: datetime | None = None,
    floor: datetime | None = None,
) -> list[dict]:
    """Fetch OHLCV bars from market_data_ohlcv_tradeable ordered oldest-first, optionally from
    `since` and strictly before `until` (the rebuild's data horizon; never both). `floor` is the
    name's proven start (design D4) and combines with `until` only: nothing before it is read."""
    if since is not None and until is not None:
        raise ValueError("_fetch_bars_from_db takes since or until, not both")
    if floor is not None and until is None:
        raise ValueError("_fetch_bars_from_db takes floor only with until")
    with conn.cursor() as cur:
        if until is not None and floor is not None:
            cur.execute(_FETCH_BARS_UNTIL_FLOOR_SQL, (symbol, tf, until, floor))
        elif until is not None:
            cur.execute(_FETCH_BARS_UNTIL_SQL, (symbol, tf, until))
        elif since is not None:
            cur.execute(_FETCH_BARS_SINCE_SQL, (symbol, tf, since))
        else:
            cur.execute(_FETCH_BARS_SQL, (symbol, tf))
        rows = cur.fetchall()
    times = [r[0] if r[0].tzinfo else r[0].replace(tzinfo=UTC) for r in rows]
    basis = _volume_basis_codes(conn, symbol, tf, times, [r[6] for r in rows], [r[7] for r in rows])
    return [
        {
            "ts": t,
            "open": float(r[1]),
            "high": float(r[2]),
            "low": float(r[3]),
            "close": float(r[4]),
            "volume": _nan_if_null(r[5]),
            "volume_basis": int(code),
        }
        for t, r, code in zip(times, rows, basis, strict=True)
    ]


# ---------------------------------------------------------------------------
# Rebuild unit design (D-32a): a unit is (symbol chunk, tf, calendar-year range), keyed by a
# provenance_batch record, so a kill-and-resume skips every completed unit.
# ---------------------------------------------------------------------------

# APR fallbacks: the live values are infra.feature_factory.rebuild_symbols_per_chunk and
# infra.feature_factory.max_unit_rows (migration 428).
_REBUILD_SYMBOLS_PER_CHUNK_KEY = "infra.feature_factory.rebuild_symbols_per_chunk"
_REBUILD_SYMBOLS_PER_CHUNK_DEFAULT: int = 25
_REBUILD_MAX_UNIT_ROWS_KEY = "infra.feature_factory.max_unit_rows"
_REBUILD_MAX_UNIT_ROWS_DEFAULT: int = 1_000_000

# Calendar slack when a memory in bars becomes a fetch window: weekends and holidays make a
# trading-bar count span more wall-clock days than bars / bars-per-day.
_FETCH_CALENDAR_SLACK_DAYS: int = 7


def load_rebuild_unit_apr(cfg: ConfigService) -> tuple[int, int]:
    """(symbols per chunk, max rows per unit) from APR, each at least 1."""
    symbols_per_chunk = int(
        cfg.get_sync(_REBUILD_SYMBOLS_PER_CHUNK_KEY, _REBUILD_SYMBOLS_PER_CHUNK_DEFAULT)
    )
    max_unit_rows = int(cfg.get_sync(_REBUILD_MAX_UNIT_ROWS_KEY, _REBUILD_MAX_UNIT_ROWS_DEFAULT))
    if symbols_per_chunk < 1 or max_unit_rows < 1:
        raise ValueError(
            f"{_REBUILD_SYMBOLS_PER_CHUNK_KEY}={symbols_per_chunk} and "
            f"{_REBUILD_MAX_UNIT_ROWS_KEY}={max_unit_rows} must both be at least 1"
        )
    return symbols_per_chunk, max_unit_rows


def split_symbol_chunks(symbols: Sequence[str], chunk_size: int) -> list[tuple[str, ...]]:
    """Sorted, de-duplicated symbols in consecutive chunks of `chunk_size` (the last may be
    short). Deterministic, so a resumed run rebuilds the same chunks and the same unit keys."""
    if chunk_size < 1:
        raise ValueError(f"chunk_size must be at least 1, got {chunk_size}")
    ordered = sorted(set(symbols))
    return [tuple(ordered[i : i + chunk_size]) for i in range(0, len(ordered), chunk_size)]


def rebuild_unit_ranges(
    tf: str, first_bar_ts: datetime, horizon: datetime
) -> list[tuple[datetime, datetime]]:
    """Half-open UTC ranges covering [first_bar_ts, horizon) for one (symbol chunk, tf).

    Intraday tfs: one range per calendar year, Jan 1 UTC to Jan 1 UTC (the last one ends at
    `horizon`). The ranges are unit identity keys, not chunk boundaries: the hypertable's chunk
    interval is 360 days (TimescaleDB's 1-year interval), not Jan-1 aligned. Daily: one range
    for the whole span (RESEARCH "Unit design consequence": a 1d chunk is small, so a year split
    buys nothing). Both start on Jan 1 of the first bar's year, so a deeper backfill inside that
    year does not rename the unit (the input digest still moves, which is what should flip it).
    `horizon` is the data horizon the run pins: a unit never reads past it, so nightly bars
    landing between a kill and its resume cannot change a completed unit's identity.
    """
    for name, value in (("first_bar_ts", first_bar_ts), ("horizon", horizon)):
        if value.tzinfo is None:
            raise ValueError(f"rebuild_unit_ranges: {name} must be tz-aware")
    first = first_bar_ts.astimezone(UTC)
    end = horizon.astimezone(UTC)
    if first >= end:
        return []
    start_year = datetime(first.year, 1, 1, tzinfo=UTC)
    if tf == "1d":
        return [(start_year, end)]
    ranges: list[tuple[datetime, datetime]] = []
    year = first.year
    while True:
        range_start = datetime(year, 1, 1, tzinfo=UTC)
        if range_start >= end:
            break
        ranges.append((range_start, min(datetime(year + 1, 1, 1, tzinfo=UTC), end)))
        year += 1
    return ranges


def bars_to_fetch_window(tf: str, bars: int) -> timedelta:
    """A wall-clock window guaranteed to hold at least `bars` bars of `tf` (never fewer).

    Uses the regular-session bars per day, which is at most the real count (extended-hours bars
    only add), so the window errs long: bars / per-day trading days, scaled by 7/5 for weekends,
    plus a holiday slack. A bare `bars * tf_seconds` would cover a night and a weekend with no
    bars and under-warm the first rows of a unit.
    """
    per_day = _BARS_PER_DAY.get(tf)
    if per_day is None:
        raise ValueError(f"no bars-per-day for timeframe {tf!r}; known: {sorted(_BARS_PER_DAY)}")
    if bars <= 0:
        return timedelta(0)
    trading_days = math.ceil(bars / per_day)
    return timedelta(days=math.ceil(trading_days * 7 / 5) + _FETCH_CALENDAR_SLACK_DAYS)


def path_dependent_contributors(
    registry: KernelRegistry, columns: Sequence[str]
) -> tuple[str, ...]:
    """Names of the kernels, among those contributing `columns` (upstream included), that are
    declared path dependent: no finite memory reproduces their output (D-26)."""
    return tuple(
        sorted(k.name for k in registry.topological_order(list(columns)) if k.path_dependent)
    )


def unit_fetch_start(
    registry: KernelRegistry,
    columns: Sequence[str],
    tf: str,
    range_start: datetime,
    series_start: datetime,
    config: FeatureFactoryConfig,
) -> datetime:
    """Where a unit's bar fetch must start so its first row is as if computed from the series
    start (D-26): `range_start` less the max declared memory over the kernels contributing
    `columns`, never before `series_start`.

    A contributing kernel that is path dependent (an expanding window, an accumulator anchored
    at row 0, a refit cadence counted from the first bar) has no finite memory, so the answer is
    `series_start`; `path_dependent_contributors` names them. With every column requested the
    registry has 14 such contributing kernels (the HMM regime pair and their labels, session VP and
    levels, the weekly VWAP, the statistics refresh and autocorrelation kernels, among
    them), so a full rebuild unit computes from the series start and the memory branch serves a
    subset of columns. External inputs (daily macro records, HTF
    values) are built by the caller from the full source history on the row grid, so their
    warmup is not the fetch start's concern; their pass-through kernels declare memory 0.
    """
    if path_dependent_contributors(registry, columns):
        return series_start
    contributors = registry.topological_order(list(columns))
    memory = max((registry.effective_memory_bars(k.name, config) for k in contributors), default=0)
    return max(series_start, range_start - bars_to_fetch_window(tf, memory))


@functools.cache
def _kernel_module_key(module: str) -> str:
    """Code key of one kernel module and its first-party import closure (D-23)."""
    return _kernel_code_key([module])


# The writer's own identity: this module (hashed as a file, without its imports) and the row
# contract with its import closure, so a change to how rows are built or spooled renames every
# unit it would have produced differently.
_WRITER_OWN_MODULE = "services.backfill_feature_factory"
_ROW_CONTRACT_MODULE = "src.intelligence.features.feature_vector_persistence"


def unit_code_key(registry: KernelRegistry, columns: Sequence[str]) -> str:
    """sha256 hex over the sorted (kernel name, module code key) of every kernel contributing
    `columns`, plus the writer's own modules; matches BulkLoadSpec.code_key's 32-64 hex rule."""
    contributors: list[Kernel] = list(registry.topological_order(list(columns)))
    lines = sorted(f"{k.name}:{_kernel_module_key(k.module)}" for k in contributors)
    lines.append("writer:" + _kernel_code_key([_ROW_CONTRACT_MODULE], own=[_WRITER_OWN_MODULE]))
    return hashlib.sha256("\n".join(lines).encode()).hexdigest()


# ---------------------------------------------------------------------------
# Stage 2: the rebuild writer (D-28). feature_vectors only, through bulk_load().
# ---------------------------------------------------------------------------

_FEATURE_TABLE = "feature_vectors"
_FEATURE_TIME_COLUMN = "bar_ts"
# ETFs trade on NYSE/NASDAQ/ARCA with identical hours; the v1 table filtered non-trading bars at
# source and the rebuild keeps the same row set.
_TRADING_EXCHANGE = "NYSE"
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
# A name with no proven start reads from the beginning of its series.
_NO_FLOOR = _EPOCH


_PROVEN_STARTS_SQL = """
SELECT DISTINCT ON (subject) split_part(subject, '|', 1), metric_value, passed
FROM integrity_monitor
WHERE monitor_type = %s AND metric_name = %s AND subject = ANY(%s)
ORDER BY subject, evaluated_at DESC
"""


def proven_starts(conn: Any, symbols: Sequence[str]) -> dict[str, datetime]:
    """Each name's proven start (design D4, todo 532): the latest `proven_start_1d` fact the 1d
    verdict run wrote for it, as midnight UTC of the session date. A name whose latest fact is a
    failure (no start: its latest session is unanswered) or that has no fact is absent from the
    result; the caller counts and reports those. Depends on bar presence only."""
    with conn.cursor() as cur:
        cur.execute(
            _PROVEN_STARTS_SQL,
            (MONITOR_TYPE, INFO_PROVEN_START, [f"{symbol}|1d" for symbol in symbols]),
        )
        return {
            symbol: datetime.combine(date.fromordinal(int(ordinal)), dt_time.min, tzinfo=UTC)
            for symbol, ordinal, passed in cur.fetchall()
            if passed
        }


_ONE_MICROSECOND = timedelta(microseconds=1)
_SPOOL_ROOT_DEFAULT = project_root / "logs" / "rebuild_spool"
_SPOOL_GROUP_PREFIX = "group-"


def default_data_horizon(now: datetime | None = None) -> datetime:
    """The exclusive end of every rebuild unit when --data-horizon is not given: midnight UTC at
    the start of the current month. Whole months only, because the bar content digest is
    month-granular (`bar_content_digests`): a horizon inside a month would digest that month
    whole and flip the unit's identity when later bars of it land."""
    moment = (now or datetime.now(UTC)).astimezone(UTC)
    return datetime(moment.year, moment.month, 1, tzinfo=UTC)


class SeriesColumns(NamedTuple):
    """One (symbol, tf) series' computed columns on the bar grid."""

    # (n_bars, n_numeric) float32 in feature_vectors_numeric_columns() order; NaN is missing.
    numeric: np.ndarray
    regime: np.ndarray  # object, None where unlabeled
    regime_volatility: np.ndarray
    # (n_bars, len(object_columns)) bool: the object-dependent column's own object or validity
    # state is true at the row (its none mask is 0) and the row is storable (past its warmup)
    present: np.ndarray | None = None
    object_columns: tuple[str, ...] = ()


def column_warmup_bars(
    registry: KernelRegistry, columns: Sequence[str], config: FeatureFactoryConfig
) -> dict[str, int]:
    """Declared memory in bars per column, for the columns whose kernels have a finite memory.

    Rows of a series before this index are not yet what a long-history computation gives
    (the kernel's declared window has not filled): the rebuild writes them as missing. A
    path-dependent column has no finite memory and is absent here (its kernel emits its own
    NaN while it has no state, D-26).
    """
    warmups: dict[str, int] = {}
    for column in columns:
        kernel = registry.by_output(column)
        if registry.is_path_dependent(column):
            continue
        warmups[column] = registry.effective_memory_bars(kernel.name, config)
    return warmups


def stored_first_row(
    registry: KernelRegistry, column: str, config: FeatureFactoryConfig, tf: str
) -> int:
    """The first row of a series the rebuild can store for `column` on `tf`: a column with a
    finite memory is written missing inside it (column_warmup_bars, no_fill), so its first
    storable row is that memory; a path-dependent column is stored from where its value can
    first exist (the registry's definition_warmup). The corpus gates G2 and G6 measure from here."""
    defined = registry.definition_warmup(column, config, tf)
    if registry.is_path_dependent(column):
        return defined
    return max(defined, registry.effective_memory_bars(registry.by_output(column).name, config))


def _compute_series_columns(
    inputs: Mapping[str, np.ndarray],
    config: FeatureFactoryConfig,
    registry: KernelRegistry | None = None,
) -> SeriesColumns:
    """Every feature_vectors feature column of one series from ONE `compute_kernels` call.

    The call runs from the series start over the registry's full output set, regime and
    regime_volatility included (the HMM walk-forward kernels, R-10); the session VP, session
    levels, weekly VWAP, hurst, shannon, garch, hma, adx and product columns are registry
    kernels too, so no FeatureCache is built or read and a pre-warmed cache cannot change a row.
    A nullable column's none mask turns its NaN into missing; a column with a finite declared
    memory is missing for rows inside that memory (no_fill). The result is float32 (the table's
    type) with out-of-range values clamped the way bulk_load clamps.
    """
    registry = registry if registry is not None else default_registry()
    numeric_names = feature_vectors_numeric_columns()
    outputs = list(feature_vectors_output_columns())
    out = compute_kernels(registry, inputs, config, outputs=outputs)
    n = len(inputs["close"])
    warmups = column_warmup_bars(registry, numeric_names, config)
    matrix = np.empty((n, len(numeric_names)), dtype=np.float32)
    objects = tuple(c for c in numeric_names if c in registry.object_dependent_outputs())
    present = np.zeros((n, len(objects)), dtype=bool)
    with np.errstate(over="ignore", under="ignore", invalid="ignore"):
        for j, name in enumerate(numeric_names):
            column = np.array(out[name], dtype=np.float64)
            mask = out.get(none_mask_name(name))
            if mask is not None:
                column[np.asarray(mask) > 0.5] = np.nan
            warmup = warmups.get(name, 0)
            if warmup:
                column[: min(warmup, n)] = np.nan
            matrix[:, j] = clamp_to_real_range_array(column)
    for k, name in enumerate(objects):
        # counted only, never written: the none mask is the kernel's own presence state
        present[:, k] = np.asarray(out[none_mask_name(name)]) <= 0.5
        present[: min(warmups.get(name, 0), n), k] = False
    return SeriesColumns(
        numeric=matrix,
        regime=np.asarray(out["regime"], dtype=object),
        regime_volatility=np.asarray(out["regime_volatility"], dtype=object),
        present=present,
        object_columns=objects,
    )


_DIVIDEND_COVERAGE_SQL = (
    "SELECT covered_from, covered_to FROM dividend_event_coverage "
    "WHERE source = 'yahoo' AND symbol = %s"
)
# One amount per ex-date, Yahoo first with the IBKR-derived event as the fallback (the
# reconciled view's documented naive default); the dispute rule is a research-layer concern.
_DIVIDEND_AMOUNTS_SQL = (
    "SELECT ex_date, COALESCE(max(amount) FILTER (WHERE source = 'yahoo'), "
    "max(amount) FILTER (WHERE source = 'ibkr_adjusted_last_ratio')) "
    "FROM dividend_events WHERE symbol = %s GROUP BY ex_date"
)


def build_daily_records(
    conn,
    symbol: str,
    symbol_1d_bars: list[dict],
    spy_1d_bars: list[dict],
    config: FeatureFactoryConfig,
) -> DailySeriesRecord:
    """The item-8 daily families of one symbol (todo 584 D2): market residual against SPY,
    return distribution, dividend yield. `conn` is a read-only connection; a symbol with no Yahoo
    coverage row gets an all-NaN dividend yield (unknown, never 0.0)."""
    with conn.cursor() as cur:
        cur.execute(_DIVIDEND_COVERAGE_SQL, (symbol,))
        coverage_rows = cur.fetchall()
        cur.execute(_DIVIDEND_AMOUNTS_SQL, (symbol,))
        amounts = dict(cur.fetchall())
    coverage = (coverage_rows[0][0], coverage_rows[0][1]) if coverage_rows else None
    bar_dates = [bar["ts"].date() for bar in symbol_1d_bars]
    return DailySeriesRecord(
        residual=build_market_residual_series(symbol_1d_bars, spy_1d_bars, symbol, config),
        distribution=build_distribution_series(symbol_1d_bars, config),
        dividend_yield=build_dividend_yield_series(
            symbol_1d_bars, reconciled_amounts(bar_dates, coverage, amounts), config
        ),
    )


def _series_kernel_inputs(
    symbol: str,
    tf: str,
    bars: Mapping[str, np.ndarray],
    config: FeatureFactoryConfig,
    cross_asset_by_date: dict,
    beta_by_date: dict,
    htf_bars: list[dict],
    daily_records: DailySeriesRecord | None = None,
) -> dict[str, np.ndarray]:
    """The bar arrays and every external input of one series, built as compute_batch builds them
    (the same three helpers, so one definition of each alignment): the symbol and tf constants,
    the ten daily macro columns as-of the bar end (NaN before the first record, no_fill), and the
    higher-timeframe externals. `bars` holds ts (UTC nanoseconds), open, high, low, close,
    volume and volume_basis arrays.

    An empty `htf_bars` yields an empty CTF series (the kernels' own pre-first-HTF-close values),
    never a fabricated record. The cache argument of the two helpers is read only on the live
    path (no daily dicts), which this never takes, so it is None.
    """
    htf_tf = config.ctf_higher_tf_map.get(tf)
    if not htf_tf:
        raise ValueError(f"no higher timeframe configured for {tf!r} in feature.ctf.higher_tf_map")
    ctf_series = _rekey_ctf_series_to_actual_close(
        _build_ctf_series(htf_bars, config) if htf_bars else {}, tf, htf_tf
    )
    row_ns = bars["ts"]
    return {
        **_batch_kernel_inputs(
            row_ns,
            bars["open"],
            bars["high"],
            bars["low"],
            bars["close"],
            bars["volume"],
            symbol,
            tf,
            bars["volume_basis"],
        ),
        **_macro_kernel_inputs(
            row_ns,
            symbol,
            tf,
            None,  # type: ignore[arg-type]
            cross_asset_by_date,
            beta_by_date,
        ),
        **_cross_tf_kernel_inputs(
            row_ns,
            tf,
            None,  # type: ignore[arg-type]
            ctf_series,
        ),
        **_daily_records_kernel_inputs(row_ns, tf, daily_records),
    }


def _spool_line(row: tuple) -> str:
    """One feature_vectors row as a CSV line: bar_ts as epoch microseconds, a missing value
    (None) as an empty field, floats with 9 significant digits (round-trips float32 exactly)."""
    symbol, tf, bar_ts, regime, regime_volatility = row[:5]
    for text in (symbol, tf, regime, regime_volatility):
        if text and ("," in text or "\n" in text):
            raise ValueError(f"cannot spool {text!r}: it holds a separator")
    return (
        ",".join(
            (
                symbol,
                tf,
                str((bar_ts - _EPOCH) // _ONE_MICROSECOND),
                regime or "",
                regime_volatility or "",
                *("" if v is None else format(v, ".9g") for v in row[5:]),
            )
        )
        + "\n"
    )


def read_spool_rows(path: Path) -> Iterator[tuple]:
    """Stream a spool file back as the tuples bulk_load COPYs: a datetime bar_ts, None for an
    empty field, floats otherwise. One row in memory at a time."""
    with open(path) as handle:
        for line in handle:
            parts = line.rstrip("\n").split(",")
            yield (
                parts[0],
                parts[1],
                _EPOCH + timedelta(microseconds=int(parts[2])),
                parts[3] or None,
                parts[4] or None,
                *(None if cell == "" else float(cell) for cell in parts[5:]),
            )


_spool_row_time = operator.itemgetter(2)


def _write_unit_spool(
    path: Path,
    symbol: str,
    tf: str,
    row_ns: np.ndarray,
    bar_times: Sequence[datetime],
    series: SeriesColumns,
    range_start: datetime,
    range_end: datetime,
    first_row: int,
    block_rows: int,
    stats_out: dict[str, list[int]] | None = None,
) -> int:
    """Write one symbol's rows of the half-open range [range_start, range_end) to `path`; return
    the row count. With `stats_out`, also count over the written rows, per object-dependent
    column, [present, nan_present]: rows where its object or validity state is true, and of
    those the ones stored missing (the unit's provenance unit_stats, 186-31).

    Rows before `first_row` (the dominant-window warmup the old table also skipped) and bars the
    market calendar does not call trading bars are left out. The trading filter runs once over
    the range's bar times; only the kept rows are converted to Python (a dropped row costs one
    calendar call, not 307 float conversions). Kept rows go to disk in blocks of `block_rows`,
    so the buffer is one block however long the symbol's history is (todo 339).
    """
    lo = max(int(np.searchsorted(row_ns, bar_ts_ns(range_start), side="left")), first_row)
    hi = int(np.searchsorted(row_ns, bar_ts_ns(range_end), side="left"))
    calendar = get_market_calendar()
    kept = [
        k for k in range(lo, hi) if calendar.is_trading_bar(_TRADING_EXCHANGE, bar_times[k], tf)
    ]
    if stats_out is not None and series.object_columns and kept:
        names = feature_vectors_numeric_columns()
        index = {name: j for j, name in enumerate(names)}
        rows = np.asarray(kept)
        for k, name in enumerate(series.object_columns):
            present = series.present[rows, k]
            missing = np.isnan(series.numeric[rows, index[name]])
            stats_out[name] = [int(present.sum()), int((present & missing).sum())]
    with open(path, "w") as handle:
        for b in range(0, len(kept), block_rows):
            block = kept[b : b + block_rows]
            numeric_rows = series.numeric[block].tolist()
            regime_rows = series.regime[block]
            volatility_rows = series.regime_volatility[block]
            handle.write(
                "".join(
                    _spool_line(
                        feature_vector_row_values(
                            symbol,
                            tf,
                            bar_times[k],
                            regime_rows[j],
                            volatility_rows[j],
                            numeric_rows[j],
                        )
                    )
                    for j, k in enumerate(block)
                )
            )
    return len(kept)


def _fetch_bar_arrays(
    conn: Any,
    symbol: str,
    tf: str,
    horizon: datetime,
    block_rows: int,
    floor: datetime = _NO_FLOOR,
) -> tuple[dict[str, np.ndarray], list[datetime]]:
    """One series' bars from `floor` (the name's proven start; design D4) strictly before
    `horizon` from market_data_ohlcv_tradeable, streamed
    through a server-side cursor in blocks (never a full-history fetchall), as numpy arrays plus
    the aware bar times. `ts` is UTC int64 nanoseconds, the registry's timestamp input."""
    times: list[datetime] = []
    columns: list[list[float]] = [[], [], [], [], []]
    vendors: list[str] = []
    kinds: list[str] = []
    with conn.cursor(name="rebuild_bars") as cur:
        cur.itersize = block_rows
        cur.execute(_FETCH_BARS_UNTIL_FLOOR_SQL, (symbol, tf, horizon, floor))
        while True:
            block = cur.fetchmany(block_rows)
            if not block:
                break
            # zip(*block) transposes the block C-side; one extend per column replaces the
            # five interpreted appends per row.
            transposed = list(zip(*block))
            times.extend(t if t.tzinfo else t.replace(tzinfo=UTC) for t in transposed[0])
            for column, out, convert in zip(transposed[1:6], columns, _BAR_CONVERTERS, strict=True):
                out.extend(map(convert, column))
            vendors.extend(transposed[6])
            kinds.extend(transposed[7])
    arrays = {
        "ts": np.array([bar_ts_ns(t) for t in times], dtype=np.int64),
        **{
            name: np.array(columns[k], dtype=np.float64)
            for k, name in enumerate(("open", "high", "low", "close", "volume"))
        },
        "volume_basis": _volume_basis_codes(conn, symbol, tf, times, vendors, kinds),
    }
    return arrays, times


# The shared macro externals, installed once per worker by the pool initializer instead of
# pickled into every task submit (they are identical for the whole run; a task carries only
# its per-symbol work). None means the initializer has not run.
_WORKER_EXTERNALS: tuple[dict, list[dict], list[dict]] | None = None


def _rebuild_worker_init(
    cross_asset_by_date: dict, spy_1d_bars: list[dict], tlt_1d_bars: list[dict]
) -> None:
    """Pool initializer payload: runs in each worker process before its first task."""
    global _WORKER_EXTERNALS
    _WORKER_EXTERNALS = (cross_asset_by_date, spy_1d_bars, tlt_1d_bars)


def _rebuild_worker(args: tuple) -> dict:
    """Compute one (symbol, tf) series and spool its units; runs in a pool subprocess.

    Compute-only (CLAUDE.md invariant): the connection is read-only, nothing is written to the
    database. Returns {symbol, units: {unit_index: {path, rows}}, error}: spool paths and counts,
    never rows, so the IPC payload does not grow with the symbol's history (todo 339). The spool
    directory belongs to the main process, which removes it after the group's units load or fail.
    """
    (
        symbol,
        tf,
        dsn,
        config,
        horizon,
        unit_ranges,
        spool_dir,
        block_rows,
        floor,
    ) = args
    setup_service_logging("logs/backfill_feature_factory.log")
    worker_log = structlog.get_logger(__name__)
    result: dict = {"symbol": symbol, "units": {}, "error": None}
    if _WORKER_EXTERNALS is None:
        raise RuntimeError(
            "_rebuild_worker: macro externals not installed (the pool initializer "
            "_rebuild_worker_init did not run)"
        )
    cross_asset_by_date, spy_1d_bars, tlt_1d_bars = _WORKER_EXTERNALS
    try:
        with _short_lived_conn(dsn) as conn:  # read only; a server cursor needs its transaction
            bars, bar_times = _fetch_bar_arrays(conn, symbol, tf, horizon, block_rows, floor)
            first_row = config.momentum_zscore_window
            if len(bars["ts"]) < first_row + 2:
                worker_log.warning(
                    "insufficient_bars",
                    symbol=symbol,
                    tf=tf,
                    bars=len(bars["ts"]),
                    need=first_row + 2,
                )
                for index, _range in unit_ranges:
                    path = Path(spool_dir) / f"u{index:05d}-{symbol}.csv"
                    path.write_text("")
                    result["units"][index] = {"path": str(path), "rows": 0}
                return result
            symbol_1d_bars = _fetch_bars_from_db(conn, symbol, "1d", until=horizon, floor=floor)
            beta_by_date = build_symbol_beta_series(
                symbol_1d_bars, spy_1d_bars, tlt_1d_bars, symbol, config
            )
            daily_records = build_daily_records(conn, symbol, symbol_1d_bars, spy_1d_bars, config)
            htf_tf = config.ctf_higher_tf_map.get(tf)
            htf_bars = (
                symbol_1d_bars
                if htf_tf == "1d"
                else _fetch_bars_from_db(conn, symbol, htf_tf, until=horizon, floor=floor)
            )
            inputs = _series_kernel_inputs(
                symbol,
                tf,
                bars,
                config,
                cross_asset_by_date,
                beta_by_date,
                htf_bars,
                daily_records,
            )
            series = _compute_series_columns(inputs, config)
            del inputs
            for index, (range_start, range_end) in unit_ranges:
                path = Path(spool_dir) / f"u{index:05d}-{symbol}.csv"
                stats: dict[str, list[int]] = {}
                rows = _write_unit_spool(
                    path,
                    symbol,
                    tf,
                    bars["ts"],
                    bar_times,
                    series,
                    range_start,
                    range_end,
                    first_row,
                    block_rows,
                    stats_out=stats,
                )
                result["units"][index] = {"path": str(path), "rows": rows, "stats": stats}
    except Exception as error:
        result["error"] = f"{type(error).__name__}: {error}"
        worker_log.error("rebuild_worker_failed", symbol=symbol, tf=tf, error=str(error))
    return result


_UNIT_STATS_SQL = """
SELECT m.symbol,
       (extract(year FROM m.timestamp AT TIME ZONE 'UTC'))::int AS yr,
       count(*), min(m.timestamp), max(m.timestamp)
FROM market_data_ohlcv_tradeable m
JOIN unnest(%s::text[], %s::timestamptz[]) AS s(symbol, floor_ts) ON s.symbol = m.symbol
WHERE m.timeframe = %s AND m.timestamp >= s.floor_ts AND m.timestamp < %s
GROUP BY m.symbol, yr
"""


def open_chunk_floor(horizon: datetime) -> datetime:
    """Jan 1 of the horizon year: the chunk holding the horizon stays open for later writes, so
    compression never reaches past this instant."""
    return datetime(horizon.year, 1, 1, tzinfo=UTC)


def compression_bound(
    conn: Any,
    full_chunks: Sequence[tuple[str, ...]],
    timeframes: Sequence[str],
    horizon: datetime,
    code_key: str,
    apr_snapshot: Mapping[str, Any],
    starts: Mapping[str, datetime],
    known: Mapping[tuple[tuple[str, ...], str], Sequence[tuple[datetime, bool]]],
) -> datetime:
    """Chunks ending at or before this instant can be compressed (todo 584 item 4): the open
    chunk floor, pulled back to the earliest `range_start` of any unit of the full scope (every
    universe chunk, every target tf) that is not completed. "Completed" is the planner's own test,
    the unit's batch_key (code key, APR snapshot, input digest, symbol chunk), so a restated bar,
    an APR change or a reshuffled chunk keeps its unit pending here exactly as the planner sees it.

    `known` carries the stage's own groups, (chunk, tf) -> [(range_start, completed)], so a
    full-scope stage plans nothing again; groups outside its --symbols/--tf scope are planned
    here. A unit renamed after its chunk was compressed is refused loudly by bulk_load (compressed
    chunk in range), never written silently.
    """
    bound = open_chunk_floor(horizon)
    for chunk_index, chunk in enumerate(full_chunks):
        for tf in timeframes:
            units = known.get((chunk, tf))
            if units is None:
                plan = _plan_group(
                    conn, chunk_index, chunk, tf, horizon, code_key, apr_snapshot, starts
                )
                units = (
                    []
                    if plan is None
                    else [
                        (u.spec.range_start, _completed_provenance_batch(conn, u.spec) is not None)
                        for u in plan.units
                    ]
                )
            for range_start, completed in units:
                if not completed:
                    bound = min(bound, range_start)
    return bound


def _year_span(range_start: datetime, range_end: datetime) -> range:
    """The calendar years a half-open [range_start, range_end) touches: the end minus one
    microsecond, so a Jan 1 00:00:00 end does not include that year."""
    return range(range_start.year, (range_end - _ONE_MICROSECOND).year + 1)


@dataclasses.dataclass(frozen=True)
class RebuildUnit:
    """One unit of the rebuild: its position in the group and its provenance identity."""

    index: int
    spec: BulkLoadSpec

    @property
    def years(self) -> range:
        """The calendar years this unit's rows fall in (checklist identity; the hypertable's
        360-day chunk interval is not year aligned, so this is not a chunk list)."""
        return _year_span(self.spec.range_start, self.spec.range_end)


@dataclasses.dataclass
class _GroupPlan:
    chunk_index: int
    chunk: tuple[str, ...]
    tf: str
    units: list[RebuildUnit]
    blind_symbols: set[str]


def _unit_input_digest(
    digests: Mapping[str, str],
    stats: Mapping[str, CoverageRow],
    starts: Mapping[str, datetime],
) -> str:
    """sha256 hex over, per symbol with bars in the unit, the month-composed content digest
    (phase 185's `bar_content_digest_current`, the one definition) and the bar count and first
    and last bar time. The counts are supplementary identity: while a symbol's digest is absent
    (revision detection blind) a changed bar count still renames the unit."""
    lines = [
        f"{symbol}|{digests[symbol]}|{stat.count}|{stat.first.isoformat()}|{stat.last.isoformat()}"
        + f"|start={starts.get(symbol, _NO_FLOOR).isoformat()}"
        for symbol, stat in sorted(stats.items())
    ]
    return hashlib.sha256("\n".join(lines).encode()).hexdigest()


def _plan_group(
    conn: Any,
    chunk_index: int,
    chunk: tuple[str, ...],
    tf: str,
    horizon: datetime,
    code_key: str,
    apr_snapshot: Mapping[str, Any],
    starts: Mapping[str, datetime],
) -> _GroupPlan | None:
    """The units of one (symbol chunk, tf) group with their provenance identities, or None when
    the chunk has no bars before the horizon. Reads bar statistics and month digests only; no bar
    is fetched and no kernel runs, so a fully completed group costs two cheap queries."""
    with conn.cursor() as cur:
        cur.execute(
            _UNIT_STATS_SQL,
            (list(chunk), [starts.get(name, _NO_FLOOR) for name in chunk], tf, horizon),
        )
        rows = cur.fetchall()
    if not rows:
        return None
    by_year: dict[int, dict[str, CoverageRow]] = {}
    for symbol, year, count, first, last in rows:
        by_year.setdefault(year, {})[symbol] = CoverageRow(int(count), first, last)
    first_bar = min(stat.first for per_symbol in by_year.values() for stat in per_symbol.values())
    units: list[RebuildUnit] = []
    blind: set[str] = set()
    for range_start, range_end in rebuild_unit_ranges(tf, first_bar, horizon):
        merged: dict[str, CoverageRow] = {}
        for year in _year_span(range_start, range_end):
            for symbol, stat in by_year.get(year, {}).items():
                prior = merged.get(symbol)
                merged[symbol] = (
                    stat
                    if prior is None
                    else CoverageRow(
                        prior.count + stat.count,
                        min(prior.first, stat.first),
                        max(prior.last, stat.last),
                    )
                )
        if not merged:
            continue
        digests = _bar_content_digests(conn, tf, sorted(merged), range_start, range_end)
        blind |= {s for s in merged if digests[s] == BAR_DIGEST_ABSENT_SYMBOL}
        spec = BulkLoadSpec(
            writer=_JOB,
            target_table=_FEATURE_TABLE,
            time_column=_FEATURE_TIME_COLUMN,
            tf=tf,
            range_start=range_start,
            range_end=range_end,
            symbols=chunk,
            code_key=code_key,
            apr_snapshot=apr_snapshot,
            input_digest=_unit_input_digest(digests, merged, starts),
        )
        units.append(RebuildUnit(len(units), spec))
    return _GroupPlan(chunk_index, chunk, tf, units, blind)


@dataclasses.dataclass
class _PreparedGroup:
    plan: _GroupPlan
    pending: list[RebuildUnit]
    futures: list[Any]
    spool_dir: Path


def _purge_spool_root(root: Path) -> None:
    """Remove the spool directories a killed run left behind (spools are derived, rebuildable)."""
    root.mkdir(parents=True, exist_ok=True)
    for stale in root.glob(f"{_SPOOL_GROUP_PREFIX}*"):
        shutil.rmtree(stale, ignore_errors=True)


_TABLE_BYTES_SQL = "SELECT hypertable_size(%s::regclass)"
_MAX_WAL_BYTES_SQL = (
    "SELECT setting::bigint * pg_size_bytes('1' || unit) FROM pg_settings "
    "WHERE name = 'max_wal_size'"
)
# The filesystem holding the database volume (the compressed write session's own key).
_DISK_PATH_KEY = "infra.compressed_hypertable_write_session.disk_path"
_DISK_PATH_DEFAULT = "/"


def rebuild_apr_keys() -> tuple[str, ...]:
    """The APR keys besides the feature config (whose values every unit carries in its
    apr_snapshot) that shape what a stage plans, guards and compresses; the corpus rerun pins
    their values (186-31). Throughput keys (workers, block rows, BLAS threads) are not here:
    they change how fast a unit is computed, never what it holds."""
    return (
        TARGET_TIMEFRAMES_KEY,
        _REBUILD_SYMBOLS_PER_CHUNK_KEY,
        _REBUILD_MAX_UNIT_ROWS_KEY,
        _BULK_LOAD_COMPRESS_ON_COMPLETE_APR_KEY,
        _DISK_PATH_KEY,
    )


def feature_table_bytes(conn: Any) -> int:
    """feature_vectors' stored bytes now (hypertable_size: every chunk, indexes included)."""
    with conn.cursor() as cur:
        cur.execute(_TABLE_BYTES_SQL, (_FEATURE_TABLE,))
        return int(cur.fetchone()[0] or 0)


def max_wal_bytes(conn: Any) -> int:
    """max_wal_size, read live: the WAL the server may hold before a checkpoint."""
    with conn.cursor() as cur:
        cur.execute(_MAX_WAL_BYTES_SQL)
        return int(cur.fetchone()[0])


def database_free_bytes(cfg: ConfigService) -> int:
    """Free bytes of the filesystem holding the database volume, now (statvfs)."""
    return int(shutil.disk_usage(str(cfg.get_sync(_DISK_PATH_KEY, _DISK_PATH_DEFAULT))).free)


def standalone_disk_guard(cfg: ConfigService, conn: Any) -> UnitDiskGuard:
    """The unit guard of a stage run outside a corpus run: the budget base is the free space at
    stage start, every limit from the same APR keys the run uses (migration 579)."""
    apr = load_corpus_rerun_apr(cfg)
    return UnitDiskGuard(
        free_bytes_at_launch=database_free_bytes(cfg),
        max_disk_fraction=apr.max_disk_fraction,
        reserve_bytes=apr.disk_reserve_bytes,
        wal_bytes=max_wal_bytes(conn),
        stored_bytes_per_spool_byte=apr.stored_bytes_per_spool_byte,
        free_bytes=lambda: database_free_bytes(cfg),
    )


def _unit_stats(results: Sequence[dict], index: int) -> dict[str, dict[str, int]]:
    """Per object-dependent column, the unit's present and nan_present rows summed over its
    symbols (each worker counts its own written rows)."""
    totals: dict[str, list[int]] = {}
    for result in results:
        for name, (present, nan_present) in result["units"][index].get("stats", {}).items():
            pair = totals.setdefault(name, [0, 0])
            pair[0] += present
            pair[1] += nan_present
    return {
        name: {"present": present, "nan_present": nan_present}
        for name, (present, nan_present) in sorted(totals.items())
    }


def _spool_bytes(results: Sequence[dict], index: int) -> int:
    paths = (Path(r["units"][index]["path"]) for r in results)
    return sum(path.stat().st_size for path in paths if path.exists())


def _write_group(
    prepared: _PreparedGroup,
    write_conn: Any,
    max_unit_rows: int,
    summary: dict[str, Any],
    completed_keys: set[str],
    guard: UnitDiskGuard,
    table_bytes: Callable[[], int],
) -> None:
    """Wait for a group's workers, then load its pending units one by one with bulk_load.

    One unit's failure leaves its provenance row failed and the group's other units loading; a
    worker that failed for any symbol fails every pending unit of the group (a unit's identity
    is its whole symbol chunk, so it cannot complete without every symbol). The spool values
    are real-range clamped upstream (`clamp_to_real_range_array`), so bulk_load is told and
    skips its per-row clamp. Removes the group's spool directory when done, whatever happened.

    Before each COPY the disk guard projects the unit's stored bytes from its spool bytes; a
    refusal counts the unit failed (reason disk_guard), writes no provenance row (the unit stays
    pending and resumable) and raises DiskGuardRefused so the stage stops dispatching. After
    each load the table's size delta over the unit's rows and spool bytes is recorded; the
    largest stored-per-spool ratio seen tightens the guard from then on.
    """
    group = prepared.plan
    columns = feature_vectors_columns()
    try:
        results = [future.result() for future in prepared.futures]
        failures = [r for r in results if r["error"]]
        if failures:
            for unit in prepared.pending:
                summary["units_failed"] += 1
                summary["failed_units"].append(
                    {"batch_key": unit.spec.batch_key, "tf": group.tf, "reason": "worker_failed"}
                )
            _logger.error(
                "backfill_feature_factory.group_failed",
                tf=group.tf,
                chunk_index=group.chunk_index,
                failed_symbols=[r["symbol"] for r in failures],
                errors=[r["error"] for r in failures][:3],
                units=len(prepared.pending),
            )
            return
        for position, unit in enumerate(prepared.pending):
            declared = sum(r["units"][unit.index]["rows"] for r in results)
            if declared > max_unit_rows:
                raise ValueError(
                    f"rebuild unit {unit.spec.batch_key[:12]} (tf {group.tf}, "
                    f"{unit.spec.range_start:%Y-%m-%d} to {unit.spec.range_end:%Y-%m-%d}, "
                    f"{len(group.chunk)} symbols) spooled {declared} rows, above "
                    f"{_REBUILD_MAX_UNIT_ROWS_KEY}={max_unit_rows}; refusing before any write"
                )
            spool_bytes = _spool_bytes(results, unit.index)
            try:
                guard.check(spool_bytes)
            except DiskGuardRefused as refusal:
                summary["units_failed"] += 1
                summary["disk_refused"] = {"batch_key": unit.spec.batch_key, **refusal.detail}
                summary["failed_units"].append(
                    {
                        "batch_key": unit.spec.batch_key,
                        "tf": group.tf,
                        "reason": "disk_guard",
                        **refusal.detail,
                    }
                )
                _logger.error(
                    "backfill_feature_factory.disk_guard_refused",
                    batch_key=unit.spec.batch_key[:12],
                    tf=group.tf,
                    range_start=unit.spec.range_start.isoformat(),
                    **refusal.detail,
                )
                summary["units_abandoned"] += len(prepared.pending) - position - 1
                raise
            streams = [read_spool_rows(Path(r["units"][unit.index]["path"])) for r in results]
            size_before = table_bytes()
            started = time.monotonic()
            try:
                loaded = _bulk_load(
                    write_conn,
                    unit.spec,
                    columns,
                    heapq.merge(*streams, key=_spool_row_time),
                    preclamped_real=True,
                    unit_stats=_unit_stats(results, unit.index),
                )
            except Exception as error:
                summary["units_failed"] += 1
                summary["failed_units"].append(
                    {"batch_key": unit.spec.batch_key, "tf": group.tf, "reason": str(error)[:300]}
                )
                _logger.error(
                    "backfill_feature_factory.unit_failed",
                    batch_key=unit.spec.batch_key[:12],
                    tf=group.tf,
                    range_start=unit.spec.range_start.isoformat(),
                    error=str(error)[:300],
                )
                continue
            if loaded.status == "skipped":
                # A concurrent session completed the unit between planning and the load:
                # it is complete, but this run wrote none of its rows.
                summary["units_skipped"] += 1
                completed_keys.add(unit.spec.batch_key)
                continue
            if loaded.row_count != declared:
                raise RuntimeError(
                    f"rebuild unit {unit.spec.batch_key[:12]}: bulk_load wrote {loaded.row_count} "
                    f"rows but the spool declared {declared}"
                )
            summary["units_loaded"] += 1
            summary["rows_loaded"] += loaded.row_count
            completed_keys.add(unit.spec.batch_key)
            grown = table_bytes() - size_before
            if loaded.row_count and spool_bytes:
                summary["bytes_per_row_max"] = max(
                    summary["bytes_per_row_max"], grown / loaded.row_count
                )
                summary["stored_per_spool_max"] = max(
                    summary["stored_per_spool_max"], grown / spool_bytes
                )
                guard.observe(grown / spool_bytes)
            _logger.info(
                "backfill_feature_factory.unit_loaded",
                batch_key=unit.spec.batch_key[:12],
                tf=group.tf,
                rows=loaded.row_count,
                elapsed_s=round(time.monotonic() - started, 1),
            )
    finally:
        shutil.rmtree(prepared.spool_dir, ignore_errors=True)


def _span_filter(
    span: tuple[datetime, datetime] | None, timeframes: Sequence[str]
) -> Callable[[BulkLoadSpec], bool]:
    """The span's execution test: a unit executes when its range_start is in [start, end). Each
    intraday unit is one calendar year from Jan 1 UTC (`rebuild_unit_ranges`), so Jan-1 bounds
    place every unit in exactly one of a partition's spans. A 1d unit covers the whole history,
    so a stage holding 1d refuses a span; a bound off Jan 1 UTC is refused too."""
    if span is None:
        return lambda spec: True
    start, end = span
    for name, bound in (("start", start), ("end", end)):
        if bound.tzinfo is None or bound != datetime(bound.astimezone(UTC).year, 1, 1, tzinfo=UTC):
            raise ValueError(f"run_rebuild_stage: span {name} {bound} is not Jan 1 00:00 UTC")
    if start >= end:
        raise ValueError(f"run_rebuild_stage: span start {start} is not before its end {end}")
    if "1d" in timeframes:
        raise ValueError(
            "run_rebuild_stage: a span applies to intraday timeframes only; the 1d unit covers "
            f"the whole history (timeframes {list(timeframes)})"
        )
    return lambda spec: start <= spec.range_start < end


def _chunk_filter(chunk_indices: Sequence[int] | None, n_chunks: int) -> frozenset[int] | None:
    """The symbol chunks that execute (None: all). An index outside the stage's chunking is
    refused, never silently ignored."""
    if chunk_indices is None:
        return None
    chosen = frozenset(chunk_indices)
    outside = sorted(i for i in chosen if not 0 <= i < n_chunks)
    if not chosen or outside:
        raise ValueError(
            f"run_rebuild_stage: chunk_indices {sorted(chosen)} must be a non-empty subset of "
            f"0..{n_chunks - 1}"
        )
    return chosen


def rebuild_code_key() -> str:
    """The code key every rebuild unit carries (the registry's kernels for the table's outputs,
    this module and the row contract), as the stage computes it."""
    return unit_code_key(default_registry(), list(feature_vectors_output_columns()))


@dataclasses.dataclass(frozen=True)
class _StageContext:
    """What a stage plans with: one definition shared by the stage and `planned_units`."""

    cfg: ConfigService
    config: FeatureFactoryConfig
    all_timeframes: list[str]
    target_timeframes: list[str]
    max_unit_rows: int
    code_key: str
    apr_snapshot: dict[str, Any]
    universe: list[str]
    chunks: list[tuple[str, ...]]
    starts: dict[str, datetime]


def _stage_context(
    settings: Settings, db_conn: Any, symbols: list[str] | None, timeframes: list[str] | None
) -> _StageContext:
    cfg = _load_config_service(db_conn)
    config = _build_feature_factory_config(cfg)
    all_timeframes = _get_target_timeframes(cfg)
    symbols_per_chunk, max_unit_rows = load_rebuild_unit_apr(cfg)
    contracts = get_active_contracts(settings, dimension="compute_1d")
    universe = [c.symbol for c in _filter_etf_contracts(contracts, symbols)]
    return _StageContext(
        cfg=cfg,
        config=config,
        all_timeframes=all_timeframes,
        target_timeframes=_restrict_timeframes(all_timeframes, timeframes),
        max_unit_rows=max_unit_rows,
        code_key=rebuild_code_key(),
        apr_snapshot=dataclasses.asdict(config),
        universe=universe,
        chunks=split_symbol_chunks(universe, symbols_per_chunk),
        starts=proven_starts(db_conn, universe),
    )


def symbol_chunks(settings: Settings, db_conn: Any) -> list[tuple[str, ...]]:
    """The full-universe symbol chunks every stage plans with (chunk 0 is the pilot's)."""
    return _stage_context(settings, db_conn, None, None).chunks


def planned_units(
    settings: Settings, db_conn: Any, horizon: datetime
) -> tuple[list[BulkLoadSpec], set[str]]:
    """Every unit of the full rebuild scope (every universe chunk, every target tf) with the
    identity a stage would give it now, and the digest-blind symbols; plans only, computes and
    writes nothing (the corpus rerun's feature_complete check, 186-31)."""
    ctx = _stage_context(settings, db_conn, None, None)
    specs: list[BulkLoadSpec] = []
    blind: set[str] = set()
    for chunk_index, chunk in enumerate(ctx.chunks):
        for tf in ctx.all_timeframes:
            plan = _plan_group(
                db_conn, chunk_index, chunk, tf, horizon, ctx.code_key, ctx.apr_snapshot, ctx.starts
            )
            if plan is not None:
                specs.extend(unit.spec for unit in plan.units)
                blind |= plan.blind_symbols
    return specs, blind


def run_rebuild_stage(
    settings: Settings,
    symbols: list[str] | None,
    db_conn: Any,
    n_workers: int = 1,
    timeframes: list[str] | None = None,
    *,
    horizon: datetime | None = None,
    spool_root: Path | None = None,
    run_id: str | None = None,
    span: tuple[datetime, datetime] | None = None,
    chunk_indices: Sequence[int] | None = None,
    disk_guard: UnitDiskGuard | None = None,
) -> dict[str, Any]:
    """Rebuild feature_vectors for the compute_eligible_1d universe (D-28, D-32a).

    Chunk-major: for each symbol chunk, for each tf, one group. A group is planned from bar
    statistics and month digests alone, each unit's provenance row is consulted
    (`completed_provenance_batch`), and only a group with a pending unit dispatches workers; the
    next group's workers run while this group's units load. Compute reads the whole series from
    its start (the path-dependent kernels need it, see `unit_fetch_start`), once per (symbol,
    tf), and each unit takes its year of rows from that one pass.

    Compression runs at the end of every full-universe stage (any --tf, failed units or not); a
    --symbols stage defers it, because its unit keys follow its own chunks. A chunk can hold rows
    from any symbol chunk and tf (the 360-day interval is not year aligned), so only chunks ending
    before the earliest not-completed unit of the full scope are compressed
    (`compression_bound`); a compressed chunk would make bulk_load refuse a later unit, and the
    chunk containing the horizon stays open for later writes.

    `run_id` (a corpus_run id, migration 578) goes onto every spec this stage loads. `span` and
    `chunk_indices` are execution filters only (186-30): `span` [start, end), Jan 1 UTC bounds,
    intraday tfs only, executes the units whose range_start falls in it (each intraday unit is a
    calendar year, so spans that partition the history execute every unit exactly once);
    `chunk_indices` executes only those symbol chunks without changing the chunking, so unit
    identities match the full stage. Neither changes what is planned: every unit of the stage is
    planned and takes its completion from its own provenance row, filtered out or not, so the
    compression bound sees the true state of the whole stage, never an assumed one.

    `disk_guard` (186-31) is checked before every unit's COPY; without one the stage builds its
    own from the free space at its start and the corpus rerun APR (`standalone_disk_guard`). A
    refusal stops the stage dispatching; the groups not yet loaded stay pending (no provenance
    row) and the stage still compresses what it can, since compression frees space.

    Returns the stage summary (units total, skipped, loaded, failed, abandoned and out of scope;
    rows; digest-blind symbols; the per (tf, year) chunk checklist of the executed scope; the
    executed scope's batch keys and the units adopted from another run; the largest measured
    bytes per row and stored bytes per spool byte; the disk refusal; compression).
    """
    horizon = horizon or default_data_horizon()
    if horizon.tzinfo is None:
        raise ValueError("run_rebuild_stage: horizon must be tz-aware")
    if run_id is not None:
        run_id = parse_run_id(run_id)
    ctx = _stage_context(settings, db_conn, symbols, timeframes)
    cfg, config, chunks, starts = ctx.cfg, ctx.config, ctx.chunks, ctx.starts
    all_timeframes, target_timeframes = ctx.all_timeframes, ctx.target_timeframes
    code_key, apr_snapshot, universe = ctx.code_key, ctx.apr_snapshot, ctx.universe
    in_span = _span_filter(span, target_timeframes)
    max_unit_rows = ctx.max_unit_rows
    block_rows = int(cfg.get_sync(_REBUILD_BLOCK_ROWS_KEY, _REBUILD_BLOCK_ROWS_DEFAULT))
    blas_threads_per_worker = int(cfg.get_sync("infra.blas_threads_per_worker", 1))
    registry = default_registry()
    feature_outputs = list(feature_vectors_output_columns())
    guard = disk_guard if disk_guard is not None else standalone_disk_guard(cfg, db_conn)
    spool_root = spool_root or _SPOOL_ROOT_DEFAULT
    _purge_spool_root(spool_root)

    executed_chunks = _chunk_filter(chunk_indices, len(chunks))
    without_start = sorted(set(universe) - set(starts))
    if without_start:
        _logger.warning(
            "backfill_feature_factory.names_without_proven_start",
            names=len(without_start),
            sample=without_start[:10],
            reason="no passing proven_start_1d fact: these names read from the start of their "
            "series; run the 1d verdict audit first if that is not intended",
        )

    _logger.info(
        "backfill_feature_factory.rebuild_start",
        symbols=len(universe),
        proven_starts=len(starts),
        names_without_proven_start=len(without_start),
        chunks=len(chunks),
        tfs=target_timeframes,
        horizon=horizon.isoformat(),
        run_id=run_id,
        span=None if span is None else [format_iso_ts(bound) for bound in span],
        chunk_indices=None if executed_chunks is None else sorted(executed_chunks),
        n_workers=n_workers,
        code_key=code_key[:12],
        path_dependent=list(path_dependent_contributors(registry, feature_outputs)),
    )

    summary: dict[str, Any] = {
        "units_total": 0,
        "units_skipped": 0,
        "units_loaded": 0,
        "units_failed": 0,
        "units_out_of_scope": 0,
        "rows_loaded": 0,
        "failed_units": [],
        "empty_groups": 0,
        "digest_blind_symbols": [],
        "chunk_checklist": {},
        "chunks_compressed": 0,
        "compression": "not_run",
        "horizon": horizon.isoformat(),
        # The executed scope's units by batch key, and those already completed under another
        # run (adopted: their rows stay, their provenance row keeps its run, 186-31).
        "scope_batch_keys": [],
        "adopted": [],
        "units_abandoned": 0,
        "disk_refused": None,
        "bytes_per_row_max": 0.0,
        "stored_per_spool_max": 0.0,
    }
    blind: set[str] = set()
    planned: dict[tuple[tuple[str, ...], str], list[RebuildUnit]] = {}
    expected: dict[tuple[str, int], set[str]] = {}
    completed_keys: set[str] = set()
    write_conn = psycopg.connect(settings.database_url)  # bulk_load commits; not autocommit
    pool = None
    try:
        # The pool and its shared macro externals are built on the FIRST pending group, so a
        # resume with nothing to do pays neither: the daily cross-asset records are built once
        # from the reference ETFs' 1d bars before the horizon, installed per worker by the
        # pool initializer (never pickled into every task submit), and shared by every symbol.
        waiting: _PreparedGroup | None = None
        load = (guard, lambda: feature_table_bytes(db_conn))
        try:
            for chunk_index, chunk in enumerate(chunks):
                for tf in target_timeframes:
                    plan = _plan_group(
                        db_conn, chunk_index, chunk, tf, horizon, code_key, apr_snapshot, starts
                    )
                    planned[(chunk, tf)] = [] if plan is None else plan.units
                    if plan is None:
                        summary["empty_groups"] += 1
                        continue
                    blind |= plan.blind_symbols
                    chunk_executes = executed_chunks is None or chunk_index in executed_chunks
                    pending: list[RebuildUnit] = []
                    for unit in plan.units:
                        # Every planned unit takes its completion from its own provenance row before
                        # any filter applies: `planned`, and so the compression bound, never assumes.
                        row = _completed_provenance_batch(db_conn, unit.spec)
                        completed = row is not None
                        if completed:
                            completed_keys.add(unit.spec.batch_key)
                        if not (chunk_executes and in_span(unit.spec)):
                            summary["units_out_of_scope"] += 1
                            continue
                        summary["units_total"] += 1
                        summary["scope_batch_keys"].append(unit.spec.batch_key)
                        owner = (
                            None if row is None or row.get("run_id") is None else str(row["run_id"])
                        )
                        if run_id is not None and completed and owner != run_id:
                            summary["adopted"].append(
                                {
                                    "unit_key": unit.spec.unit_key,
                                    "batch_key": unit.spec.batch_key,
                                    "adopted_from_run_id": owner,
                                }
                            )
                        for year in unit.years:
                            expected.setdefault((tf, year), set()).add(unit.spec.batch_key)
                        if completed:
                            summary["units_skipped"] += 1
                        else:
                            spec = dataclasses.replace(unit.spec, run_id=run_id)
                            pending.append(dataclasses.replace(unit, spec=spec))
                    if not pending:
                        continue
                    if pool is None:
                        reference = {
                            name: _fetch_bars_from_db(db_conn, name, "1d", until=horizon)
                            for name in (SPY, TLT, SHY, TIP, HYG, LQD)
                        }
                        cross_asset_by_date = build_cross_asset_series(
                            reference[SPY],
                            reference[TLT],
                            reference[SHY],
                            reference[TIP],
                            reference[HYG],
                            reference[LQD],
                            config,
                        )
                        pool = _make_worker_pool(
                            n_workers,
                            blas_threads_per_worker,
                            initializer=_rebuild_worker_init,
                            initargs=(cross_asset_by_date, reference[SPY], reference[TLT]),
                        )
                    spool_dir = Path(
                        tempfile.mkdtemp(
                            prefix=f"{_SPOOL_GROUP_PREFIX}{tf}-{chunk_index:04d}-", dir=spool_root
                        )
                    )
                    unit_ranges = [
                        (unit.index, (unit.spec.range_start, unit.spec.range_end))
                        for unit in pending
                    ]
                    futures = [
                        pool.submit(
                            _rebuild_worker,
                            (
                                symbol,
                                tf,
                                settings.database_url,
                                config,
                                horizon,
                                unit_ranges,
                                str(spool_dir),
                                block_rows,
                                starts.get(symbol, _NO_FLOOR),
                            ),
                        )
                        for symbol in chunk
                    ]
                    previous, waiting = waiting, _PreparedGroup(plan, pending, futures, spool_dir)
                    if previous is not None:
                        _write_group(
                            previous, write_conn, max_unit_rows, summary, completed_keys, *load
                        )
            if waiting is not None:
                last, waiting = waiting, None
                _write_group(last, write_conn, max_unit_rows, summary, completed_keys, *load)
        except DiskGuardRefused:
            # Stop dispatching: the group whose workers are still running is abandoned (its
            # units have no provenance row and stay pending); compression below still runs.
            if waiting is not None:
                for future in waiting.futures:
                    future.cancel()
                summary["units_abandoned"] += len(waiting.pending)
        summary["digest_blind_symbols"] = sorted(blind)
        if blind:
            _logger.warning(
                "backfill_feature_factory.digest_blind",
                symbols=len(blind),
                reason="bar_content_digest_current has no row for these symbols, so a revised "
                "bar inside a completed unit cannot be detected; the bar count and span still "
                "name the unit",
            )
        for (tf, year), keys in sorted(expected.items()):
            summary["chunk_checklist"][f"{tf}:{year}"] = {
                "expected_units": len(keys),
                "completed_units": len(keys & completed_keys),
            }
        if not cfg.get_sync(
            _BULK_LOAD_COMPRESS_ON_COMPLETE_APR_KEY, _BULK_LOAD_DEFAULT_COMPRESS_ON_COMPLETE
        ):
            summary["compression"] = f"off: {_BULK_LOAD_COMPRESS_ON_COMPLETE_APR_KEY} is false"
        elif symbols:
            # A --symbols stage keys its units by its own chunks, which no full-universe plan
            # matches, so the bound would replan the whole corpus and still find nothing to free.
            summary["compression"] = "deferred: --symbols scope; a full-universe stage compresses"
        else:
            known = {
                key: [(u.spec.range_start, u.spec.batch_key in completed_keys) for u in units]
                for key, units in planned.items()
            }
            bound = compression_bound(
                db_conn, chunks, all_timeframes, horizon, code_key, apr_snapshot, starts, known
            )
            summary["chunks_compressed"] = _compress_completed_chunks(
                write_conn, _FEATURE_TABLE, bound
            )
            summary["compressed_before"] = format_iso_ts(bound)
            clean = bound == open_chunk_floor(horizon) and not summary["units_failed"]
            summary["compression"] = "done" if clean else "partial: units pending"
    finally:
        if pool is not None:
            pool.shutdown(wait=True)
        write_conn.close()
        shutil.rmtree(spool_root, ignore_errors=True)
    _logger.info(
        "backfill_feature_factory.rebuild_complete",
        **{
            k: v
            for k, v in summary.items()
            if k not in ("failed_units", "chunk_checklist", "digest_blind_symbols")
        },
    )
    return summary


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def _completion_status(summary: dict[str, Any]) -> str:
    """The job_completed_total status label: a run whose units failed is not a success
    (monitoring must distinguish it from a clean run; the nonzero exit makes it loud)."""
    return "partial" if summary.get("units_failed") else "success"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=("Backfill Feature Factory: the feature_vectors rebuild writer")
    )
    parser.add_argument(
        "--symbols",
        default=None,
        help="Comma-separated symbols to limit scope, e.g. SPY,TLT (default: all active ETFs)",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=None,
        help="Number of parallel workers (default: APR infra.feature_factory.workers, fallback 1)",
    )
    parser.add_argument(
        "--tf",
        default=None,
        help="Comma-separated timeframes to limit scope, e.g. 1d (default: every tf in "
        "feature.factory.target_timeframes; one outside it is an error)",
    )
    parser.add_argument(
        "--data-horizon",
        default=None,
        help=(
            "Exclusive end (UTC, YYYY-MM-DD) of every rebuild unit (default: the first day "
            "of the current UTC month). A resume must pass the same horizon or the units' "
            "identities change."
        ),
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()

    symbols: list[str] | None = None
    if args.symbols:
        symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]
    timeframes = [t.strip() for t in args.tf.split(",") if t.strip()] if args.tf else None
    horizon = (
        datetime.strptime(args.data_horizon, "%Y-%m-%d").replace(tzinfo=UTC)
        if args.data_horizon
        else None
    )

    settings = Settings()
    db_conn = _connect_db(settings)

    # n_workers from the CLI arg or APR, read once on the main connection before the workers
    # spawn. run_rebuild_stage opens its own serial writer connection and closes it.
    n_workers: int = 1
    if args.workers is not None:
        n_workers = args.workers
    else:
        cfg_tmp = _load_config_service(db_conn)
        n_workers = int(cfg_tmp.get_sync("infra.feature_factory.workers", 1))

    _logger.info(
        "backfill_start",
        symbols=symbols,
        n_workers=n_workers,
    )

    try:
        _logger.info("stage2_start")
        summary = run_rebuild_stage(
            settings=settings,
            symbols=symbols,
            db_conn=db_conn,
            n_workers=n_workers,
            timeframes=timeframes,
            horizon=horizon,
        )
        _logger.info(
            "stage2_complete",
            units_loaded=summary["units_loaded"],
            units_skipped=summary["units_skipped"],
            units_failed=summary["units_failed"],
            rows_loaded=summary["rows_loaded"],
        )

        status = _completion_status(summary)
        JOB_COMPLETED_TOTAL.add(1, {"job": _JOB, "status": status})
        _logger.info("backfill_complete", status=status)
        if status != "success":
            raise SystemExit(1)

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
