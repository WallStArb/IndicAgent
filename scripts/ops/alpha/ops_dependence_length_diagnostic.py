#!/usr/bin/env python3
"""
ops_dependence_length_diagnostic.py -- todo 145 standing instrumentation for the
mechanism Fable 5's 2026-07-19 review confirmed behind todo 091's residual 21%
bootstrap-CI SUSPECT rate: every residual SUSPECT cell is a feature whose true
autocorrelation dependence length exceeds its timeframe's circular block bootstrap
block size (`alpha.ic.bootstrap_block_size.{5m,15m,1h,1d}`, live values 78/26/10/10
bars). Examples measured live: `ctf_momentum` runs ~4x its block size across tfs
(structural, HTF-derived); `flight_quality` (a TLT/SPY macro-divergence feature)
runs ~750x at 1h -- a months-scale decorrelation no feasible block size fixes.

Per this project's principles (resist overfitting, instrument everything): the fix is
NOT per-feature block-size tuning (one dial overfit to one symptom, and it does not
help flight_quality at all) -- it is standing instrumentation that flags affected
cells as lower-trust, the same way `reliable`/`passes_walkforward` already gate
downstream consumers today. This script computes that flag, once per (feature, tf),
and writes it to `integrity_monitor` (todo 144's `subject`-as-stratum-key precedent,
`monitor_type='ic_bootstrap'`).

Standalone by design (todo 145's explicit instruction), NOT a change inside
`services/ic_engine.py`: that file is 3,600+ lines and Phase 162 is already
restructuring its compute functions -- this avoids adding a fifth concern to the same
file mid-refactor. Mirrors `ops_lookahead_horizon_response.py`'s house style: reads
`feature_vectors` directly, computes its own diagnostic rather than importing private
functions from `ic_engine.py` (only `_FEATURE_NAMES`, the column-name list, is
imported -- a read-only reference, not a private compute function).

Dependence-length proxy: the 1/e decorrelation lag (first lag k>=1 at which the
autocorrelation function's magnitude drops to or below 1/e), a standard cheap proxy
for the integrated autocorrelation time. Per the todo: "sufficient for a flag, not a
publication-grade estimate" -- this is deliberately not a rigorous IAT estimator (no
windowing/tapering correction, no bias adjustment). Computed via FFT-based
autocorrelation, O(n log n) per (symbol, feature) series, aggregated to one
per-(feature, tf) value via the median across sampled symbols.

No idempotency pre-check (unlike ic_engine.py's lifecycle hook or
forward_return_writer.py's price-sanity fact): those guard an automated pipeline step
against a same-window rerun; this is a standalone, manually-invoked diagnostic where a
repeat run legitimately produces a fresh measurement, not a duplicate to suppress.

Usage:
    python scripts/ops/alpha/ops_dependence_length_diagnostic.py
    python scripts/ops/alpha/ops_dependence_length_diagnostic.py --tf 5m
    python scripts/ops/alpha/ops_dependence_length_diagnostic.py --max-symbols 15
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

import asyncpg
import numpy as np

from services.ic_engine import _FEATURE_NAMES
from src.config.settings import Settings

_TFS = ("5m", "15m", "1h", "1d")
_DEFAULT_MAX_SYMBOLS = 30
_DEFAULT_MAX_BARS_PER_SYMBOL = 20_000
_MIN_SERIES_LEN = 40  # below this, the ACF proxy is too noisy to trust for even a floor
_MAX_LAG_CAP_DEFAULT = 10_000  # bounds FFT/search cost; see _decorrelation_lag_1_over_e
_DECORRELATION_THRESHOLD = 1.0 / np.e

# [initial_estimate] pre-migration fallback ONLY -- alpha.ic.dependence_length_flag_ratio
# (migration 239, seed 2.0, [conventional]) is the live source of truth once applied.
_FLAG_RATIO_FALLBACK = 2.0
# Mirrors ops_ic_null_calibration.py's _BOOTSTRAP_BLOCK_SIZE_DEFAULTS -- same APR keys,
# same fallback values, kept in sync deliberately (both read
# alpha.ic.bootstrap_block_size.{tf}, the live block sizes _circular_block_bootstrap_ic
# actually uses in production).
_BLOCK_SIZE_DEFAULTS = {"5m": 78, "15m": 26, "1h": 10, "1d": 10}

_LATEST_VINTAGE_SQL = "SELECT max(training_window_end) FROM feature_ic_scores"
_SYMBOLS_SQL = """
    SELECT DISTINCT symbol FROM feature_vectors WHERE tf = $1 ORDER BY symbol LIMIT $2
"""

# One row per (feature, tf) per run. subject follows todo 144's
# `subject`-as-generic-stratum-key precedent (src/config/vocabulary_drift.py:182-215)
# -- 'feature=<name>|tf=<tf>', no new table, no new column on feature_ic_scores.
# ON CONFLICT target matches the integrity_monitor_idempotency_uq index exactly (same
# 5-tuple used by ic_engine.py's and vocabulary_drift.py's existing raw INSERTs).
_INSERT_SQL = """
    INSERT INTO integrity_monitor
        (monitor_type, subject, metric_name, metric_value, threshold_value, passed, training_window_end)
    VALUES ('ic_bootstrap', $1, 'dependence_length_ratio', $2, $3, $4, $5)
    ON CONFLICT (monitor_type, training_window_end, metric_name, COALESCE(subject, ''), evaluated_at) DO NOTHING
"""


def _decorrelation_lag_1_over_e(series: np.ndarray, max_lag: int | None = None) -> int:
    """1/e decorrelation lag: the first lag k>=1 at which the autocorrelation
    function's magnitude drops to or below 1/e (~0.368) -- a standard cheap proxy for
    integrated autocorrelation time (todo 145: "sufficient for a flag, not a
    publication-grade estimate"). FFT-based, O(n log n).

    NaN values (e.g. feature_vectors warmup rows) are dropped before computing --
    autocorrelation of a padded-with-NaN series is meaningless via FFT.

    Returns `max_lag` itself (a floor, not an exact value) if the ACF never drops
    below 1/e within the searched window -- dependence is AT LEAST that long, which
    is exactly the case this diagnostic exists to flag (e.g. flight_quality's real
    decorrelation lag is thousands of bars; "very long, exact value TBD" is sufficient
    to trip the downstream ratio flag).

    Returns 0 for degenerate input: fewer than 4 finite values, or zero variance
    (a constant series has no decay to measure).
    """
    x = np.asarray(series, dtype=np.float64)
    x = x[np.isfinite(x)]
    n = len(x)
    if n < 4:
        return 0

    if max_lag is None:
        max_lag = min(n - 1, _MAX_LAG_CAP_DEFAULT)
    max_lag = max(1, min(max_lag, n - 1))

    x = x - x.mean()
    var0 = float(np.dot(x, x))
    if var0 <= 0.0:
        return 0

    size = 1
    while size < 2 * n:
        size *= 2
    fx = np.fft.rfft(x, n=size)
    acf_full = np.fft.irfft(fx * np.conjugate(fx))[:n]
    acf = acf_full / acf_full[0]

    for lag in range(1, max_lag + 1):
        if abs(acf[lag]) <= _DECORRELATION_THRESHOLD:
            return lag
    return max_lag


def _dependence_length_ratio(decorrelation_lag: float, block_size: int) -> float:
    """ratio = decorrelation_lag / block_size (todo 145's flag metric). NaN if
    block_size is non-positive -- should never happen with APR-seeded values, but a
    diagnostic loop over ~50 features x 4 tfs must not crash on a single bad config
    read."""
    if block_size <= 0:
        return float("nan")
    return float(decorrelation_lag) / float(block_size)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--tf", choices=_TFS, default=None, help="Restrict to one timeframe (default: all 4)."
    )
    parser.add_argument("--max-symbols", type=int, default=_DEFAULT_MAX_SYMBOLS)
    parser.add_argument(
        "--max-bars-per-symbol",
        type=int,
        default=_DEFAULT_MAX_BARS_PER_SYMBOL,
        help="Most recent N bars per (symbol, tf) to pull -- bounds cost, mirrors "
        "ops_lookahead_horizon_response.py's --max-bars-per-symbol.",
    )
    return parser.parse_args()


async def _load_config_float(pool: asyncpg.Pool, key: str, default: float) -> float:
    row = await pool.fetchval("SELECT config_value FROM config_state WHERE config_key = $1", key)
    return float(row) if row is not None else default


async def _load_config_int(pool: asyncpg.Pool, key: str, default: int) -> int:
    row = await pool.fetchval("SELECT config_value FROM config_state WHERE config_key = $1", key)
    return int(row) if row is not None else default


def _feature_series_sql(feature_cols_sql: str) -> str:
    """Most recent N bars per (symbol, tf), oldest-first for ACF computation --
    mirrors ops_lookahead_horizon_response.py's bounded-recent-window `recent` CTE
    (an earlier unbounded full-history version of that script got OOM-killed; the
    same bound applies here for the same reason)."""
    return f"""
        WITH recent AS (
            SELECT bar_ts, {feature_cols_sql}
            FROM feature_vectors
            WHERE tf = $1 AND symbol = $2 AND bar_ts <= $3
            ORDER BY bar_ts DESC
            LIMIT $4
        )
        SELECT * FROM recent ORDER BY bar_ts
    """


async def main() -> int:
    args = _parse_args()
    settings = Settings()
    dsn = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
    pool = await asyncpg.create_pool(dsn=dsn)

    try:
        vintage = await pool.fetchval(_LATEST_VINTAGE_SQL)
        if vintage is None:
            print("ERROR: feature_ic_scores is empty -- no vintage to anchor the sample.")
            return 0

        flag_ratio = await _load_config_float(
            pool, "alpha.ic.dependence_length_flag_ratio", _FLAG_RATIO_FALLBACK
        )
        block_sizes = {
            tf: await _load_config_int(pool, f"alpha.ic.bootstrap_block_size.{tf}", default)
            for tf, default in _BLOCK_SIZE_DEFAULTS.items()
        }

        tfs = (args.tf,) if args.tf else _TFS
        feature_cols_sql = ", ".join(f'"{f}"' for f in _FEATURE_NAMES)
        series_sql = _feature_series_sql(feature_cols_sql)

        print("# Dependence-Length Diagnostic (todo 145)\n")
        print(
            f"vintage: {vintage}, max_symbols={args.max_symbols}, "
            f"flag_ratio_threshold={flag_ratio}, block_sizes={block_sizes}\n"
        )
        print(
            "Per (feature, tf): decorrelation_lag_bars is the median 1/e decorrelation "
            "lag across sampled symbols (cheap proxy for integrated autocorrelation "
            "time, see module docstring). ratio = decorrelation_lag_bars / "
            "bootstrap_block_size. FLAG means ratio exceeds the APR-seeded threshold "
            "-- the bootstrap CI for this (feature, tf) is likely too narrow.\n"
        )
        print("| feature | tf | decorrelation_lag_bars | block_size | ratio | flag |")
        print("|---|---|---|---|---|---|")

        n_written = 0
        n_flagged = 0

        for tf in tfs:
            block_size = block_sizes[tf]
            symbol_rows = await pool.fetch(_SYMBOLS_SQL, tf, args.max_symbols)
            symbols = [r["symbol"] for r in symbol_rows]
            if not symbols:
                print(f"WARNING: no symbols found for tf={tf}")
                continue

            per_feature_lags: dict[str, list[int]] = {f: [] for f in _FEATURE_NAMES}
            for symbol in symbols:
                rows = await pool.fetch(series_sql, tf, symbol, vintage, args.max_bars_per_symbol)
                if len(rows) < _MIN_SERIES_LEN:
                    continue
                x_matrix = np.array(
                    [[r[f] for f in _FEATURE_NAMES] for r in rows], dtype=np.float64
                )
                for i, feature_name in enumerate(_FEATURE_NAMES):
                    lag = _decorrelation_lag_1_over_e(x_matrix[:, i])
                    per_feature_lags[feature_name].append(lag)

            for feature_name in _FEATURE_NAMES:
                lags = per_feature_lags[feature_name]
                if not lags:
                    continue
                median_lag = float(np.median(lags))
                ratio = _dependence_length_ratio(median_lag, block_size)
                passed = bool(ratio <= flag_ratio)
                flag_label = "ok" if passed else "FLAG"
                if not passed:
                    n_flagged += 1

                print(
                    f"| {feature_name} | {tf} | {median_lag:.1f} | {block_size} | "
                    f"{ratio:.3f} | {flag_label} |"
                )

                await pool.execute(
                    _INSERT_SQL,
                    f"feature={feature_name}|tf={tf}",
                    ratio,
                    flag_ratio,
                    passed,
                    vintage,
                )
                n_written += 1

        print(
            f"\n---\nWrote {n_written} integrity_monitor rows "
            f"(monitor_type='ic_bootstrap'), {n_flagged} flagged "
            f"(ratio > {flag_ratio}). Downstream consumers (ensemble eligibility, "
            "quality-weight computation) can read this as a lower-trust signal -- "
            "wiring an actual consumer is a separate, later decision (todo 145 only "
            "scopes the measurement + flag)."
        )
        return 0
    finally:
        await pool.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
