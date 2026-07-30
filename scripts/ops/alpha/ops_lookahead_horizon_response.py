#!/usr/bin/env python3
"""
ops_lookahead_horizon_response.py -- Q1 (todo 091/097 follow-up) horizon-response
diagnostic: how does forward-return coverage and IC actually behave across a dense,
session-feasible per-tf horizon grid, instead of the four fixed 1/5/20/60-bar
`[initial_estimate]` lookahead points production uses today?

Design: Fable 5's 2026-07-19 review
(docs/research/fable-2026-07-19-lookahead-and-target-calibration-review.md), Q1(c)
Step 1. That review found the uniform 1/5/20/60-bar grid (identical bar counts on
every tf, never scaled per-tf the way _tf_window() scales day-denominated window
params) structurally amputates the design grid on intraday tfs: 1h slow/extended and
15m extended have ZERO forward-return rows (the intraday same-ET-session completeness
gate, a deliberate and correct Invariant-1 constraint, has nothing left to measure at
those horizons), and 5m extended silently measures only first-~90-minutes bars (a
morning-entry selection bias with no downstream signal that it happened). This script
is the empirical instrument to replace those four guessed bar-counts with a real
IC-decay curve per tf, dense enough to show where coverage collapses and whether IC is
still rising or already flat at the session boundary.

Read-only, no persistence. Computes forward returns itself via the SAME LEAD()-based
construction and same-ET-session completeness gate as
forward_return_writer._build_forward_return_sql (deliberately re-derived here rather
than imported, since that function's column-naming is hard-coupled to the fixed
fast/mid/slow/extended forward_returns schema -- this script needs an arbitrary
per-tf grid of raw bar counts). Reads from market_data_ohlcv_tradeable (the
CLAUDE.md-mandated volume>0 view for measurement reads), not the raw table.

Stride-corrected (2026-07-20, Fable 5 review of the todo-146 full-corpus run): per-symbol
observations are subsampled at stride = max(min_stride, horizon_bars) before ranking/CI,
mirroring ic_engine.py's production `scale_stride = max(subsample_min_stride,
lookahead_bars)` discipline. Without this, consecutive forward returns at a long horizon
overlap by (horizon-1) bars and are serially dependent, so an unstrided Fisher-z CI is
computed on effective N << n_valid and understates its own half-width -- the flat CI
half-width across 1d's whole grid in the original (unstrided) run was this artifact, not
real. min-stride defaults to alpha.ic.subsample_min_stride's production default (5).

Deliberately NOT regime-stratified (a difference from Fable's suggested design):
horizon-response is a property of the return-generating process and the session-
completeness gate at a given tf, not a regime-conditional question -- pooling every
regime maximizes power for what is otherwise a small, thin diagnostic sample. Component
F's regime-conditional question is a separate, already-built script
(ops_vol_normalized_target_ab.py).

IC magnitude and CI width are reported as SEPARATE columns (median |IC| across all
`_FEATURE_NAMES`, and median Fisher-z CI half-width across the same features) so power
(N, hence CI width) and signal (IC magnitude) are never conflated when reading the
curve -- exactly Fable's stated requirement. Fisher-z (not bootstrap) is used
deliberately: this is a cheap, non-gating, one-shot diagnostic script (not a second
corpus-wide re-run), and todo 091 already established Fisher-z is directionally usable
even where its exact width is imperfect for some autocorrelation-heavy features -- a
diagnostic curve does not need the same rigor as a promotion gate.

No production writes, no config_state changes. Exit code always 0 -- informational,
matching ops_ic_null_calibration.py's house style.

Per-feature breakdown (2026-07-29): median_abs_ic/median_ci_halfwidth describe the
TYPICAL feature and are structurally blind to a concentrated signal in a minority of
the ~244 active features -- a median can sit inside its own CI at every horizon while
a handful of individual features have real, CI-distinguishable IC the aggregate
statistic outvotes. Each horizon row now also reports, restricted to
`feature_registry.status = 'active'` features (excludes the 5 `candidate`-status
canary/placebo controls from the "is there real signal" count): how many individually
clear a raw CI-excludes-zero bar, and how many survive Benjamini-Hochberg FDR
correction across that horizon's active-feature family (`alpha.ic.fdr_alpha`, same
correction `apply_bh_fdr` applies in production). The 5 canary features are tracked
separately as a calibration sanity check -- they are guaranteed-null by construction,
so a nonzero raw-CI hit rate on them is expected noise at ~5%/feature/horizon (not a
bug), but a persistently elevated rate across many horizons would indicate the CI
itself is miscalibrated, not that canaries have real signal. Top-10 active features by
|IC| are printed per horizon regardless of significance, so a reader can eyeball which
specific features are closest to distinguishable, not just the aggregate curve.

Shortlist bootstrap recheck (2026-07-29): --features restricts the per-feature report
to a specific comma-separated list (e.g. features that showed up repeatedly across many
horizons' top-10 in a first Fisher-z pass); --bootstrap (requires --features, to bound
cost) replaces Fisher-z with the circular block bootstrap CI (_circular_block_bootstrap_ic,
the SAME CI method ic_engine.py's real promotion gate uses -- alpha.ic.bootstrap_resamples/
bootstrap_block_size.{tf}/bootstrap_seed/cross_sectional_bootstrap_threads.{tf}, all loaded
from APR) for just the shortlisted + 5 canary columns, leaving the other ~239 active
columns on Fisher-z (median_abs_ic/median_ci_halfwidth stay full-244, effectively
unaffected by swapping a handful of columns). This exists because Fisher-z was found
empirically miscalibrated on this corpus's canaries at a rate (~30%) matching the
already-documented ~38% SUSPECT rate from ops_ic_null_calibration.py -- a raw/FDR
"significant" count built on Fisher-z cannot be trusted feature-by-feature, only as an
aggregate curve-shape signal.

IMPORTANT CAVEAT even when --bootstrap is used: this recheck runs on the SAME sample
that produced the shortlist. Fixing the CI calibration does not fix winner's-curse
selection bias from having scanned 244 features x many horizons and picked the
survivors -- a feature clearing this bar is evidence worth a real out-of-sample /
walk-forward check through ic_engine.py's own production pipeline, not itself
promotion-grade proof. Treat a pass here as "worth escalating," not "confirmed."

Usage:
    python scripts/ops/alpha/ops_lookahead_horizon_response.py
    python scripts/ops/alpha/ops_lookahead_horizon_response.py --tf 1h
    python scripts/ops/alpha/ops_lookahead_horizon_response.py --max-symbols 20
    python scripts/ops/alpha/ops_lookahead_horizon_response.py --tf 1h --allow-overnight \\
        --features vix_z,range_pct_slow,hmm_regime_prob,hmm_entropy,garch_ratio,yield_slope_z \\
        --bootstrap
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

import asyncpg
import numpy as np
from scipy.stats import rankdata

from services._batch_utils import cfg as _cfg
from services._batch_utils import load_apr_dict_async
from services.ic_engine import _FEATURE_NAMES, _derive_worker_rng_seed
from src.config.settings import Settings
from src.intelligence.statistics.ic_math import (
    _circular_block_bootstrap_ic,
    _fisher_z_ci,
    _p_values_from_ic,
    _vectorized_ic,
    apply_bh_fdr,
)

# Per-tf dense horizon grid, denominated in session-feasible bar counts (Fable 5
# Q1c Step 1). Bars-per-session: 5m=78, 15m=26, 1h=7 (from
# src/intelligence/regime_signals/tf_window.py's _BARS_PER_DAY, the project's own
# existing per-tf bar-count constant). 1d has no session boundary.
_HORIZON_GRIDS: dict[str, tuple[int, ...]] = {
    "5m": (1, 3, 6, 12, 26, 39, 66),
    "15m": (1, 2, 5, 10, 22),
    "1h": (1, 2, 4, 6),
    "1d": (1, 2, 5, 10, 20, 40, 60, 90),
}
_TFS = ("5m", "15m", "1h", "1d")

# 2026-07-29 addition: multi-day horizon grids for the "should 1h/15m be allowed to
# extend overnight instead of session-bounded" question (user pushback on the
# same-ET-session completeness gate for 1h -- and by extension 15m -- being treated
# as a hard structural ceiling rather than a debatable design choice). Only used
# when --allow-overnight is passed for that tf; default (no flag) behavior above is
# byte-identical to what todo 146 already ran and cited. Denominated in bars-per-
# session (15m=26, 1h=7, from tf_window.py's _BARS_PER_DAY) x N trading days, same
# day-count spacing as _HORIZON_GRIDS["1d"] (1,2,5,10,20) for direct comparability.
_OVERNIGHT_HORIZON_GRIDS: dict[str, tuple[int, ...]] = {
    "5m": (1, 3, 6, 12, 26, 39, 66, 78, 156, 390, 780),  # +1,2,5,10-day multi-day points
    "15m": (1, 2, 5, 10, 22, 26, 52, 130, 260),  # +1,2,5,10-day multi-day points
    "1h": (1, 2, 4, 6, 7, 14, 35, 70),  # +1,2,5,10-day multi-day points
}
"""2026-07-30 gap fix (docs/research/2026-07-30-forward-return-horizon-grid-refactor.md
sec. 6.1): 5m was missing from this table, so --allow-overnight rejected it outright --
without the flag, a default-mode 5m run still applied the same-ET-session completeness
gate that forward_return_writer.py removed (todo 208), measuring a different
completeness definition than production now uses. 78 bars/session (tf_window.py's
_BARS_PER_DAY), same 1,2,5,10-day multi-day spacing as the 15m/1h grids."""
_DEFAULT_MAX_SYMBOLS = 30
_MIN_RELIABLE_N_DEFAULT = 100
_MIN_STRIDE_DEFAULT = 5
_DEFAULT_MAX_BARS_PER_SYMBOL = 20_000
_FV_CHUNK_TS = 2_000

_LATEST_VINTAGE_SQL = "SELECT max(training_window_end) FROM feature_ic_scores"
_SYMBOLS_SQL = """
    SELECT DISTINCT symbol FROM feature_vectors WHERE tf = $1 ORDER BY symbol LIMIT $2
"""
_FEATURE_REGISTRY_SQL = "SELECT feature_name, status FROM feature_registry"
_TOP_N_FEATURES = 10


def _build_horizon_response_sql(
    horizons: tuple[int, ...], tf: str, *, allow_overnight: bool = False
) -> str:
    """LEAD()-based SQL computing forward log-returns at an arbitrary set of raw bar
    counts, generalizing forward_return_writer._build_forward_return_sql (which is
    hard-coupled to the fixed fast/mid/slow/extended schema) for a dense diagnostic
    grid. Same ROWS BETWEEN explicit frame (avoids default range-frame tie semantics,
    RESEARCH.md F8), same same-ET-session completeness gate for intraday tfs by
    default, no session gate for 1d. Column names are h{n} (n = raw bar count), not
    scale names.

    allow_overnight (2026-07-29, default False -- original behavior unchanged):
    when True, skips the same-ET-session completeness check for this tf, same as 1d's
    no-gate treatment -- testing whether a same-day-only forward-return convention is
    the right invariant for 1h/15m specifically, or an overly conservative default
    that structurally amputates their slow/extended tiers for no real reason. Every
    other diagnostic mechanic (stride subsampling, Fisher-z CI, rank IC) is identical
    either way -- only the completeness definition changes, so an "IC exists at a
    30-bar overnight-inclusive horizon" result is directly comparable to the
    session-bounded numbers already on record for this tf.

    Bounded to the most recent $4 bars per symbol (via `recent`), not the full
    corpus history -- an early unbounded version of this script (full history x up
    to 30 symbols on 5m, ~78 bars/session over years) got OOM-killed. This is a
    diagnostic, not a corpus measurement; a bounded recent window is plenty of power
    for a completeness/IC-decay curve and keeps this cheap by construction.
    """
    max_n = max(horizons)
    frame_size = max_n + 1
    is_intraday = tf in ("5m", "15m", "1h") and not allow_overnight

    lead_col_list = [f"LEAD(open, {n + 1}) OVER w AS open_h{n}" for n in horizons]
    lead_cols = ",\n        ".join(lead_col_list)
    lead_t1 = "LEAD(open, 1) OVER w AS open_entry"

    return_col_list = [
        f"CASE WHEN open_entry > 0 AND open_h{n} > 0 "
        f"THEN ln(open_h{n} / open_entry) END AS return_h{n}"
        for n in horizons
    ]
    return_cols = ",\n    ".join(return_col_list)

    if is_intraday:
        fwd_ts_col_list = [f"LEAD(timestamp, {n + 1}) OVER w AS fwd_ts_h{n}" for n in horizons]
        fwd_ts_cols = ",\n        ".join(fwd_ts_col_list)
        fwd_ts_select = f",\n        {fwd_ts_cols}"
        complete_col_list = [
            f"(\n        open_h{n} IS NOT NULL\n"
            f"        AND (fwd_ts_h{n} AT TIME ZONE 'America/New_York')::date\n"
            f"            = (bar_ts AT TIME ZONE 'America/New_York')::date\n"
            f"    ) AS complete_h{n}"
            for n in horizons
        ]
    else:
        fwd_ts_select = ""
        complete_col_list = [f"(open_h{n} IS NOT NULL) AS complete_h{n}" for n in horizons]

    complete_cols = ",\n    ".join(complete_col_list)

    return f"""
WITH recent AS (
    SELECT m.timestamp, m.symbol, m.open
    FROM market_data_ohlcv_tradeable m
    WHERE m.symbol    = $1
      AND m.timeframe  = $2
      AND m.timestamp <= $3
    ORDER BY m.timestamp DESC
    LIMIT $4
),
windowed AS (
    SELECT
        timestamp                              AS bar_ts,
        symbol,
        {lead_t1},
        {lead_cols}{fwd_ts_select}
    FROM recent
    WINDOW w AS (
        PARTITION BY symbol
        ORDER BY timestamp
        ROWS BETWEEN CURRENT ROW AND {frame_size} FOLLOWING
    )
)
SELECT bar_ts, symbol, {return_cols}, {complete_cols}
FROM windowed
ORDER BY bar_ts
"""


def _feature_significance(
    ic_vec: np.ndarray,
    ci_lower: np.ndarray,
    ci_upper: np.ndarray,
    p_vec: np.ndarray,
    mask: np.ndarray,
    fdr_alpha: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Per-feature significance under `mask` (e.g. active-only or candidate-only),
    restricted to features with a finite IC and p-value this horizon.

    Returns (idxs, raw_sig, fdr_sig): `idxs` are positions into the full
    _FEATURE_NAMES-aligned arrays; `raw_sig`/`fdr_sig` are boolean arrays aligned to
    `idxs` (not to the full feature list). raw_sig = the Fisher-z CI excludes zero
    (uncorrected, single-feature test). fdr_sig = survives Benjamini-Hochberg
    correction across this call's family (all features passed under `mask`) --
    the same `apply_bh_fdr` production uses, so the false-positive-control discipline
    matches ic_engine.py's own promotion gate, not a looser diagnostic-only bar.
    """
    idxs = np.where(mask & np.isfinite(ic_vec) & np.isfinite(p_vec))[0]
    if len(idxs) == 0:
        return idxs, np.array([], dtype=bool), np.array([], dtype=bool)
    raw_sig = (ci_lower[idxs] > 0) | (ci_upper[idxs] < 0)
    reject, _ = apply_bh_fdr(p_vec[idxs].tolist(), alpha=fdr_alpha)
    return idxs, raw_sig, np.asarray(reject, dtype=bool)


def _stride_for_horizon(min_stride: int, horizon_bars: int) -> int:
    """Per-horizon subsample stride, mirroring ic_engine.py's production
    `scale_stride = max(subsample_min_stride, lookahead_bars)` discipline (2026-07-20 fix,
    Fable 5 review of the todo-146 full-corpus run)."""
    return max(min_stride, horizon_bars)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--tf", choices=_TFS, default=None, help="Restrict to one timeframe (default: all 4)."
    )
    parser.add_argument("--max-symbols", type=int, default=_DEFAULT_MAX_SYMBOLS)
    parser.add_argument("--min-reliable-n", type=int, default=None)
    parser.add_argument(
        "--min-stride",
        type=int,
        default=None,
        help="Per-symbol subsample stride floor, mirroring ic_engine.py's "
        "alpha.ic.subsample_min_stride (default: load from config_state, fallback 5). "
        "Actual stride per horizon is max(min_stride, horizon_bars), same as production.",
    )
    parser.add_argument(
        "--max-bars-per-symbol",
        type=int,
        default=_DEFAULT_MAX_BARS_PER_SYMBOL,
        help="Most recent N bars per (symbol, tf) to pull -- bounds cost; see "
        "_build_horizon_response_sql docstring.",
    )
    parser.add_argument(
        "--allow-overnight",
        action="store_true",
        help="Skip the same-ET-session completeness gate for intraday tfs (5m/15m/1h "
        "-- see _OVERNIGHT_HORIZON_GRIDS) and use the extended multi-day horizon grid "
        "instead of the session-bounded default. Tests whether the session-bounded "
        "convention is the right invariant for that tf, or an overly conservative "
        "default. Original (no-flag) behavior is unchanged.",
    )
    parser.add_argument(
        "--features",
        type=str,
        default=None,
        help="Comma-separated feature names (must match _FEATURE_NAMES) to restrict "
        "the per-feature report to, instead of all feature_registry active features. "
        "Canaries are always reported separately regardless of this flag.",
    )
    parser.add_argument(
        "--bootstrap",
        action="store_true",
        help="Use the circular block bootstrap CI (production's real promotion-gate "
        "method) instead of Fisher-z for the --features columns (+ the 5 canaries), "
        "since Fisher-z was found empirically miscalibrated on this corpus (see module "
        "docstring). Requires --features -- bootstrapping all ~244 active features x "
        "every horizon is orders of magnitude more expensive than Fisher-z and is not "
        "what this flag is for; use a shortlist from a prior Fisher-z pass instead.",
    )
    parser.add_argument(
        "--vintage",
        type=str,
        default=None,
        help="ISO 8601 UTC timestamp to use as the sample's upper time bound, overriding "
        "the default MAX(training_window_end) lookup from feature_ic_scores. Needed "
        "because that table is empty between a forward_returns rebuild and the next "
        "ic_engine run -- this diagnostic recomputes forward returns directly from "
        "market_data_ohlcv_tradeable and never reads feature_ic_scores/forward_returns "
        "for anything but this cutoff, so a known corpus training_window_end (e.g. from "
        "the pipeline run that's populating it) works just as well as feature_ic_scores' "
        "own vintage.",
    )
    args = parser.parse_args()
    if args.bootstrap and not args.features:
        parser.error("--bootstrap requires --features (a shortlist) -- see module docstring.")
    return args


async def _fetch_horizon_response_rows(
    pool: asyncpg.Pool,
    tf: str,
    symbol: str,
    vintage,
    horizons: tuple[int, ...],
    max_bars_per_symbol: int,
    *,
    allow_overnight: bool = False,
) -> list[asyncpg.Record]:
    sql = _build_horizon_response_sql(horizons, tf, allow_overnight=allow_overnight)
    return await pool.fetch(sql, symbol, tf, vintage, max_bars_per_symbol)


async def _fetch_all_symbols_horizon_rows(
    pool: asyncpg.Pool,
    tf: str,
    symbols: list[str],
    vintage,
    horizons: tuple[int, ...],
    max_bars_per_symbol: int,
    *,
    allow_overnight: bool = False,
) -> list[tuple[str, list[asyncpg.Record]]]:
    """Fetch horizon-response rows for every symbol concurrently (asyncio.gather) --
    each symbol's query is independent and this is a one-shot diagnostic script, not
    a hot production path, so no throttling/semaphore is applied. gather preserves
    input order, so the (symbol, rows) pairing survives regardless of completion order."""
    all_rows = await asyncio.gather(
        *[
            _fetch_horizon_response_rows(
                pool,
                tf,
                symbol,
                vintage,
                horizons,
                max_bars_per_symbol,
                allow_overnight=allow_overnight,
            )
            for symbol in symbols
        ]
    )
    return list(zip(symbols, all_rows))


async def main() -> int:
    args = _parse_args()
    settings = Settings()
    dsn = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
    pool = await asyncpg.create_pool(dsn=dsn)

    try:
        if args.vintage:
            vintage = datetime.fromisoformat(args.vintage)
            if vintage.tzinfo is None:
                print("ERROR: --vintage must be timezone-aware (e.g. end with +00:00 or Z).")
                return 0
        else:
            vintage = await pool.fetchval(_LATEST_VINTAGE_SQL)
        if vintage is None:
            print(
                "ERROR: feature_ic_scores is empty -- no vintage to anchor the sample. "
                "Pass --vintage <ISO8601 UTC timestamp> to override."
            )
            return 0
        apr = await load_apr_dict_async(pool)
        min_reliable_n = args.min_reliable_n or int(
            _cfg(apr, "alpha.ic.min_reliable_n", _MIN_RELIABLE_N_DEFAULT)
        )
        min_stride = args.min_stride or int(
            _cfg(apr, "alpha.ic.subsample_min_stride", _MIN_STRIDE_DEFAULT)
        )
        fdr_alpha = float(_cfg(apr, "alpha.ic.fdr_alpha", 0.05))

        registry_rows = await pool.fetch(_FEATURE_REGISTRY_SQL)
        status_by_feature = {r["feature_name"]: r["status"] for r in registry_rows}
        active_mask = np.array([status_by_feature.get(f) == "active" for f in _FEATURE_NAMES])
        candidate_mask = np.array([status_by_feature.get(f) == "candidate" for f in _FEATURE_NAMES])
        n_active = int(active_mask.sum())
        n_candidate = int(candidate_mask.sum())

        feature_index = {f: i for i, f in enumerate(_FEATURE_NAMES)}
        if args.features:
            requested = [f.strip() for f in args.features.split(",") if f.strip()]
            unknown = [f for f in requested if f not in feature_index]
            if unknown:
                print(f"ERROR: unknown feature name(s) in --features: {unknown}")
                return 0
            report_mask = np.zeros(len(_FEATURE_NAMES), dtype=bool)
            report_mask[[feature_index[f] for f in requested]] = True
            report_label = "shortlist"
        else:
            report_mask = active_mask
            report_label = "active"
        n_report = int(report_mask.sum())

        bootstrap_resamples = int(_cfg(apr, "alpha.ic.bootstrap_resamples", 2000))
        bootstrap_seed = int(_cfg(apr, "alpha.ic.bootstrap_seed", 42))
        bootstrap_block_size = {
            tf_key: int(_cfg(apr, f"alpha.ic.bootstrap_block_size.{tf_key}", 10)) for tf_key in _TFS
        }
        bootstrap_threads = {
            tf_key: int(_cfg(apr, f"alpha.ic.cross_sectional_bootstrap_threads.{tf_key}", 4))
            for tf_key in _TFS
        }

        tfs = (args.tf,) if args.tf else _TFS

        if args.allow_overnight:
            if not args.tf or args.tf not in _OVERNIGHT_HORIZON_GRIDS:
                print(
                    "ERROR: --allow-overnight requires --tf 5m, 15m, or 1h "
                    "(1d not supported -- it never had a same-session gate, see "
                    "_OVERNIGHT_HORIZON_GRIDS)."
                )
                return 0

        print("# Lookahead Horizon-Response Diagnostic\n")
        if args.allow_overnight:
            print(
                f"** --allow-overnight: same-ET-session completeness gate DISABLED for "
                f"tf={args.tf} -- forward returns may span multiple trading sessions. "
                "Extended multi-day horizon grid in use. **\n"
            )
        if args.bootstrap:
            print(
                f"** --bootstrap: circular block bootstrap CI (n_boot={bootstrap_resamples}, "
                f"seed={bootstrap_seed}) replaces Fisher-z for the {n_report} shortlisted + "
                f"{n_candidate} canary columns only -- the other ~{n_active - n_report} "
                "active columns stay on Fisher-z. CAVEAT: this is an in-sample recheck on "
                "the SAME data that produced the shortlist -- it fixes CI miscalibration, "
                "NOT winner's-curse selection bias. A pass here means 'worth an "
                "out-of-sample/walk-forward check,' not 'confirmed.' **\n"
            )
        print(
            f"vintage: {vintage}, max_symbols={args.max_symbols}, "
            f"min_reliable_n={min_reliable_n}, min_stride={min_stride}, "
            f"fdr_alpha={fdr_alpha}\n"
        )
        print(
            "Pooled across ALL regimes (not regime-stratified -- see module docstring). "
            "completeness = share of bars with a valid same-session forward return at "
            "that horizon. median_abs_ic / median_ci_halfwidth are medians across all "
            f"{len(_FEATURE_NAMES)} features ({n_active} active, {n_candidate} candidate/"
            "canary) -- read them together, not the magnitude alone: a rising "
            "median_abs_ic with a widening CI is consistent with pure noise, not real "
            "signal growth. Observations are stride-subsampled per horizon (stride = "
            "max(min_stride, horizon_bars), mirroring ic_engine.py's production "
            "discipline) before CI computation, so n_valid/median_ci_halfwidth reflect "
            "effective independent N, not raw overlapping-window count.\n"
            f"{report_label}_raw_sig / {report_label}_fdr_sig = count (out of "
            f"{n_report} {report_label} features) whose CI excludes zero, "
            f"uncorrected / after BH-FDR correction across that horizon's {report_label}-"
            f"feature family -- the median can look null while individual features "
            f"aren't. canary_raw_sig = same raw count over the {n_candidate} known-zero "
            "canary/placebo controls (a calibration sanity check, not a signal count) "
            "-- expect ~0-1 by chance per horizon under a correctly-calibrated CI, "
            "not zero.\n"
        )

        feature_cols_sql = ", ".join(f'"{f}"' for f in _FEATURE_NAMES)
        for tf in tfs:
            tf_allow_overnight = args.allow_overnight and tf in _OVERNIGHT_HORIZON_GRIDS
            horizons = _OVERNIGHT_HORIZON_GRIDS[tf] if tf_allow_overnight else _HORIZON_GRIDS[tf]
            symbol_rows = await pool.fetch(_SYMBOLS_SQL, tf, args.max_symbols)
            symbols = [r["symbol"] for r in symbol_rows]
            if not symbols:
                print(f"WARNING: no symbols found for tf={tf}")
                continue

            # Pool bar_ts+return_h{n}+complete_h{n} across symbols.
            per_horizon_returns: dict[int, list[float]] = {n: [] for n in horizons}
            per_horizon_complete: dict[int, list[bool]] = {n: [] for n in horizons}
            per_horizon_keys: dict[int, list[tuple]] = {n: [] for n in horizons}
            n_bars_total = 0

            observed_bar_ts: set = set()
            symbol_rows_pairs = await _fetch_all_symbols_horizon_rows(
                pool,
                tf,
                symbols,
                vintage,
                horizons,
                args.max_bars_per_symbol,
                allow_overnight=tf_allow_overnight,
            )
            for symbol, rows in symbol_rows_pairs:
                n_bars_total += len(rows)
                for n in horizons:
                    # Per-horizon stride subsample (not a shared stride across horizons):
                    # consecutive forward returns at horizon n overlap by n-1 bars and are
                    # serially dependent, so Fisher-z CI needs effective independent N, not
                    # raw row count. Mirrors ic_engine.py's per-scale
                    # scale_stride = max(subsample_min_stride, lookahead_bars).
                    stride = _stride_for_horizon(min_stride, n)
                    for r in rows[::stride]:
                        observed_bar_ts.add(r["bar_ts"])
                        per_horizon_returns[n].append(r[f"return_h{n}"])
                        per_horizon_complete[n].append(r[f"complete_h{n}"])
                        per_horizon_keys[n].append((r["bar_ts"], symbol))

            # Fetch feature_vectors ONCE per tf (not once per horizon -- an earlier
            # version re-fetched and re-parsed up to 8x per tf, dominating runtime),
            # restricted to the exact bar_ts set the bounded raw-return fetch above
            # actually observed -- not an open-ended bar_ts<=vintage range, which
            # would re-pull full corpus history regardless of --max-bars-per-symbol
            # and was the actual cause of an earlier OOM kill.
            #
            # Chunked (not one bar_ts=ANY(...) over the whole set) -- an unchunked
            # fetch hit asyncpg's ProgramLimitExceededError (1GB wire-protocol string
            # buffer) on tf=1h despite a modest ~20K-element array and ~395K matching
            # rows, similar order to tf=5m/15m's successful larger fetches; root cause
            # not isolated, but chunking (matching this project's existing
            # cs_chunk_ts convention in ops_vol_normalized_target_ab.py /
            # _compute_cross_sectional_tf) sidesteps it regardless of cause.
            bar_ts_list = list(observed_bar_ts)
            fv_rows: list[asyncpg.Record] = []
            for chunk_start in range(0, len(bar_ts_list), _FV_CHUNK_TS):
                ts_chunk = bar_ts_list[chunk_start : chunk_start + _FV_CHUNK_TS]
                fv_rows.extend(
                    await pool.fetch(
                        f"""
                        SELECT bar_ts, symbol, {feature_cols_sql}
                        FROM feature_vectors
                        WHERE tf = $1 AND bar_ts = ANY($2::timestamptz[])
                          AND symbol = ANY($3::text[])
                        """,
                        tf,
                        ts_chunk,
                        symbols,
                    )
                )
            fv_index: dict[tuple, int] = {}
            X_all = np.empty((len(fv_rows), len(_FEATURE_NAMES)), dtype=np.float64)
            for i, r in enumerate(fv_rows):
                fv_index[(r["bar_ts"], r["symbol"])] = i
                X_all[i] = [r[f] for f in _FEATURE_NAMES]

            print(
                f"## tf={tf} ({len(symbols)} symbols, {n_bars_total} bars fetched, "
                f"{len(fv_rows)} feature_vectors rows indexed)\n"
            )
            print(
                "| horizon_bars | completeness | n_valid | median_abs_ic | "
                f"median_ci_halfwidth | {report_label}_raw_sig | {report_label}_fdr_sig | "
                "canary_raw_sig |"
            )
            print("|---|---|---|---|---|---|---|---|")

            for n in horizons:
                complete_arr = np.array(per_horizon_complete[n], dtype=bool)
                completeness = float(complete_arr.mean()) if len(complete_arr) else 0.0
                if not complete_arr.any():
                    print(f"| {n} | {completeness:.3f} | 0 | n/a | n/a | n/a | n/a | n/a |")
                    continue

                keys_valid = [k for k, c in zip(per_horizon_keys[n], complete_arr) if c]
                returns_valid = [v for v, c in zip(per_horizon_returns[n], complete_arr) if c]

                row_idx: list[int] = []
                y_valid: list[float] = []
                for key, ret in zip(keys_valid, returns_valid):
                    idx = fv_index.get(key)
                    if idx is None or ret is None:
                        continue
                    row_idx.append(idx)
                    y_valid.append(ret)

                n_valid = len(y_valid)
                if n_valid < min_reliable_n:
                    print(
                        f"| {n} | {completeness:.3f} | {n_valid} | below floor | "
                        "below floor | -- | -- | -- |"
                    )
                    continue

                X = X_all[row_idx]
                Y = np.array(y_valid, dtype=np.float64)
                ranks_X = rankdata(X, axis=0)
                ranks_Y = rankdata(Y)
                ic_vec = _vectorized_ic(ranks_X, ranks_Y)
                ci_lower, ci_upper = _fisher_z_ci(ic_vec, n_valid)

                if args.bootstrap:
                    # Only the report shortlist + canaries get the expensive, correctly-
                    # calibrated CI -- the other ~239 active columns stay on Fisher-z
                    # (median_abs_ic/median_ci_halfwidth below are barely affected by
                    # overriding a handful of 244 columns). Cell-keyed RNG seed mirrors
                    # ic_engine.py's own _derive_worker_rng_seed convention exactly, so
                    # this recheck is reproducible run-to-run given a fixed bootstrap_seed.
                    boot_idxs = np.where(report_mask | candidate_mask)[0]
                    if len(boot_idxs):
                        cell_rng = np.random.default_rng(
                            _derive_worker_rng_seed(f"{tf}:{n}", bootstrap_seed)
                        )
                        boot_lo, boot_hi = _circular_block_bootstrap_ic(
                            X[:, boot_idxs],
                            Y,
                            bootstrap_block_size[tf],
                            bootstrap_resamples,
                            cell_rng,
                            max_workers=bootstrap_threads[tf],
                        )
                        ci_lower[boot_idxs] = boot_lo
                        ci_upper[boot_idxs] = boot_hi

                finite_ic = ic_vec[np.isfinite(ic_vec)]
                halfwidths = (ci_upper - ci_lower) / 2.0
                finite_hw = halfwidths[np.isfinite(halfwidths)]
                median_abs_ic = (
                    float(np.median(np.abs(finite_ic))) if len(finite_ic) else float("nan")
                )
                median_hw = float(np.median(finite_hw)) if len(finite_hw) else float("nan")

                p_vec = _p_values_from_ic(ic_vec, n_valid)
                report_idxs, report_raw_sig, report_fdr_sig = _feature_significance(
                    ic_vec, ci_lower, ci_upper, p_vec, report_mask, fdr_alpha
                )
                _canary_idxs, canary_raw_sig, _canary_fdr_sig = _feature_significance(
                    ic_vec, ci_lower, ci_upper, p_vec, candidate_mask, fdr_alpha
                )
                n_report_raw = int(report_raw_sig.sum())
                n_report_fdr = int(report_fdr_sig.sum())
                n_canary_raw = int(canary_raw_sig.sum())

                print(
                    f"| {n} | {completeness:.3f} | {n_valid} | {median_abs_ic:.4f} | "
                    f"{median_hw:.4f} | {n_report_raw}/{n_report} | "
                    f"{n_report_fdr}/{n_report} | {n_canary_raw}/{n_candidate} |"
                )

                if len(report_idxs):
                    top_k = min(_TOP_N_FEATURES, len(report_idxs))
                    order = np.argsort(-np.abs(ic_vec[report_idxs]))[:top_k]
                    ci_source = "bootstrap" if args.bootstrap else "Fisher-z"
                    print(
                        f"  Top {len(order)} {report_label} features by |IC| at horizon={n} "
                        f"({ci_source} CI; * = raw CI excludes zero, ** = also survives BH-FDR):"
                    )
                    for pos in order:
                        i = report_idxs[pos]
                        flag = (
                            "**" if report_fdr_sig[pos] else ("* " if report_raw_sig[pos] else "  ")
                        )
                        print(
                            f"    {flag} {_FEATURE_NAMES[i]:<32} ic={ic_vec[i]:+.4f}  "
                            f"ci=[{ci_lower[i]:+.4f}, {ci_upper[i]:+.4f}]"
                        )
                if n_canary_raw > 0:
                    print(
                        f"  NOTE: {n_canary_raw}/{n_candidate} canary/placebo features "
                        "show raw CI excluding zero at this horizon -- expected noise at "
                        "this rate for a handful of tests, only a concern if it recurs "
                        "persistently across many horizons."
                    )
            print()

        print(
            "---\nThis is a bounded diagnostic (--max-symbols caps cost). completeness=0.000 "
            "means the same-ET-session completeness gate leaves zero rows at that horizon on "
            "this tf -- a structural ceiling, not a sample-size artifact. Use the curve to "
            "decide per-tf fast/mid/slow/extended grids where completeness/CI-width are still "
            "reasonable, per docs/research/fable-2026-07-19-lookahead-and-target-calibration-"
            "review.md Q1(c)."
        )
        return 0
    finally:
        await pool.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
