#!/usr/bin/env python3
"""TagCalibrator -- generic 3-pass measurement engine for the Empirical Instrument Tag
Calibrator (Phase 146, TAG-01).

Measures the full instrument x measurable-tag matrix (F8 Simons inversion) generically
off the (symbol, factor_series, measurement_type) contract in tag_vocabulary (D-12,
migration 238), applies run-level BH-FDR (F1) once over the whole p-vector, and decides
keep/expire/discover per (symbol, tag) pair with hysteresis (F2) -- replacing
human-asserted tags with measured, falsifiable OLS loadings.

CORRECTNESS INVARIANTS:
- Self-regression pairs (symbol == factor_series) are always skipped (F6.1).
- Definitional tags (measurement_type='definitional', e.g. fed_policy/geopolitical) are
  never measured or written by this loop -- they are seed priors per tag_vocabulary's
  own philosophy (owner-annotated, migration 238), not calibration targets.
- A measurement_type='beta_regression' row with factor_series IS NULL is a
  data-integrity anomaly migration 238's Option A sweep guarantees does not exist --
  this loop still defends against it (skip + WARNING, never crash) as defense-in-depth
  (T-146-11).
- BH-FDR (statsmodels multipletests, via ic_math.apply_bh_fdr) is applied exactly ONCE
  per run over the full measured p-vector, never per-hypothesis (F1).
- A tag only expires (valid_to = now()) after consecutive_fails >=
  expiry_consecutive_fails -- a single failing run never expires an empirical tag (F2
  hysteresis, T-146-08).
- Human-asserted rows (instrument_tags.source = 'human') are never overwritten by this
  loop, keep or fail -- a failing measurement against a human row is annotated only,
  never expired (seed priors are never auto-expired).
- Daily-return reads are exclusively against market_data_ohlcv_tradeable (D-11) --
  never the raw market_data_ohlcv calendar grid.
- weight = |loading| (satisfies instrument_tags' existing [0, 1] CHECK); empirical rows
  are written source='empirical' with loading/p_value/bh_adjusted_p/passes_fdr/
  sample_n/estimated_at populated.

DAG invariant note: this oneshot is exempt from the "only writer subclasses touch DB"
rule exactly as ic_engine.py / ensemble_ic_engine.py are -- it is a batch measurement
tool, not a real-time daemon.

Usage:
    python services/tag_calibrator.py
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import math
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

import asyncpg
import numpy as np
import pandas as pd
import structlog

from services._batch_utils import cfg as _cfg
from services._batch_utils import load_apr_dict_async as _load_apr_dict
from src.config.settings import Settings
from src.core.agent.base_batch import BaseBatch
from src.core.rng import hash_key_to_int
from src.intelligence.statistics.factor_math import (
    loading_hac_pvalue,
    long_short_daily_returns,
    partial_loading,
    partial_loading_ci_low,
    partial_loading_null_arm_p,
    sign_stable_window_count,
    spy_realized_vol_factor,
    standardized_loading,
)

# apply_bh_fdr has no factor_math re-export (Plan 03's public surface is limited to the
# four measurement-kernel functions above) -- the plan's own interfaces note sanctions
# importing it directly from ic_math in that case ("importable from ic_math (or
# re-exported via factor_math)").
from src.intelligence.statistics.ic_math import apply_bh_fdr
from src.observability.metrics import counter
from src.observability.otel import OTelInitError, init_otel_providers

_logger = structlog.get_logger(__name__)

_JOB = "tag-calibrator"

# Vol proxy sentinel (D-02/D-08): not a tradeable symbol -- maps to breadth_vol's causal
# SPY-realized-vol proxy via factor_math.spy_realized_vol_factor.
_VOL_SENTINEL = "SPY_REALIZED_VOL"

# F6.4: labels are {tag, outcome} ONLY -- never per-symbol (would explode cardinality
# and isn't the diagnostic grain anyone needs; per-tag aggregate outcome counts are).
_TAG_CALIBRATION_TOTAL = counter(
    "tag_calibration_total",
    "TagCalibrator per-run decision outcome, aggregated by tag (F6.4): kept/expired/"
    "discovered/failing/contradiction/confirmed_human/no_op. Never labeled by symbol.",
)

# decision action -> OTel outcome label (F6.4 vocabulary).
_DECISION_OUTCOME_LABELS: dict[str, str] = {
    "upsert_empirical": "kept",
    "insert_discovery": "discovered",
    "expire": "expired",
    "increment_fails": "failing",
    "annotate_contradiction": "contradiction",
    "confirm_human": "confirmed_human",
    "no_op": "no_op",
}


# ---------------------------------------------------------------------------
# APR compile-time binding
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class TagCalibratorConfig:
    """Frozen config snapshot bound once at startup from the alpha.tag_calibrator.*
    APR namespace (migration 238)."""

    fdr_alpha: float
    expiry_consecutive_fails: int
    discovery_oos_days: int
    min_sample_n: int
    hac_max_lag: int
    half_life_min_days: int
    half_life_max_days: int

    @classmethod
    def from_apr(cls, cfg: dict[str, Any]) -> TagCalibratorConfig:
        """Load all 7 alpha.tag_calibrator.* APR parameters from the raw config dict."""
        return cls(
            fdr_alpha=_cfg(cfg, "alpha.tag_calibrator.fdr_alpha", 0.05),
            expiry_consecutive_fails=_cfg(cfg, "alpha.tag_calibrator.expiry_consecutive_fails", 3),
            discovery_oos_days=_cfg(cfg, "alpha.tag_calibrator.discovery_oos_days", 63),
            min_sample_n=_cfg(cfg, "alpha.tag_calibrator.min_sample_n", 60),
            hac_max_lag=_cfg(cfg, "alpha.tag_calibrator.hac_max_lag", 5),
            half_life_min_days=_cfg(cfg, "alpha.tag_calibrator.half_life_min_days", 30),
            half_life_max_days=_cfg(cfg, "alpha.tag_calibrator.half_life_max_days", 365),
        )


@dataclasses.dataclass(frozen=True)
class MaterialityConfig:
    """Frozen config snapshot bound once at startup from the materiality APR
    namespace (migration 346, Phase 175 Task 1b).

    A sibling dataclass to TagCalibratorConfig, not an extension of it -- the two
    namespaces are separately calibrated and TagCalibratorConfig's existing
    7-field shape is asserted against by existing tests.

    The ten gate threshold fields (every field below except null_arm_seed) are
    [initial_estimate] values from Codex's D-05 proposal, not corpus-calibrated
    -- see docs/foundation/apr-calibration-backlog.md for the recalibration
    tracking record.

    null_arm_seed is [conventional] (42, this project's standing default seed)
    rather than an uncalibrated statistical estimate, but it is still
    APR-backed per CLAUDE.md's APR mandate category 1 (seeds that affect
    algorithm output must be APR-backed). Changing null_arm_seed invalidates
    every previously computed null_arm_p_value.
    """

    min_partial_loading: float
    min_partial_loading_ci_low: float
    min_incremental_r2: float
    min_sample_n: int
    sign_stability_window_days: int
    sign_stability_window_count: int
    min_sign_stable_windows: int
    null_arm_alpha: float
    null_arm_draws: int
    null_arm_seed: int
    control_factor_series: tuple[str, ...]

    @classmethod
    def from_apr(cls, cfg: dict[str, Any]) -> MaterialityConfig:
        """Load all 11 materiality-namespace APR parameters from the raw config
        dict. control_factor_series is parsed from its JSON-string APR value
        into a tuple (hashable, so the frozen dataclass stays hashable)."""
        control_factor_series_json = _cfg(
            cfg,
            "alpha.tag_calibrator.materiality.control_factor_series",
            '["SPY","TLT","HYG-IEF","UUP"]',
        )
        return cls(
            min_partial_loading=_cfg(
                cfg, "alpha.tag_calibrator.materiality.min_partial_loading", 0.35
            ),
            min_partial_loading_ci_low=_cfg(
                cfg, "alpha.tag_calibrator.materiality.min_partial_loading_ci_low", 0.20
            ),
            min_incremental_r2=_cfg(
                cfg, "alpha.tag_calibrator.materiality.min_incremental_r2", 0.05
            ),
            min_sample_n=_cfg(cfg, "alpha.tag_calibrator.materiality.min_sample_n", 756),
            sign_stability_window_days=_cfg(
                cfg, "alpha.tag_calibrator.materiality.sign_stability_window_days", 252
            ),
            sign_stability_window_count=_cfg(
                cfg, "alpha.tag_calibrator.materiality.sign_stability_window_count", 4
            ),
            min_sign_stable_windows=_cfg(
                cfg, "alpha.tag_calibrator.materiality.min_sign_stable_windows", 3
            ),
            null_arm_alpha=_cfg(cfg, "alpha.tag_calibrator.materiality.null_arm_alpha", 0.05),
            null_arm_draws=_cfg(cfg, "alpha.tag_calibrator.materiality.null_arm_draws", 1000),
            null_arm_seed=_cfg(cfg, "alpha.tag_calibrator.materiality.null_arm_seed", 42),
            control_factor_series=tuple(json.loads(control_factor_series_json)),
        )


# ---------------------------------------------------------------------------
# Pass 1 support: measurement-contract filtering (T-146-11 defensive guard)
# ---------------------------------------------------------------------------


_IMPLEMENTED_MEASUREMENT_TYPE = "beta_regression"


def filter_measurable_tag_rows(
    vocab_rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[str]]:
    """Pure split of tag_vocabulary rows into the measurable matrix vs. the
    null-factor_series data-integrity anomaly (Blocker-2 / T-146-11).

    Measurable = measurement_type == 'beta_regression' (the only measurement math this
    engine implements) AND factor_series IS NOT NULL -- the self-describing contract
    migration 238's Option A sweep guarantees. `measurement_type == 'definitional'` is
    the expected, silent non-measurable case (owner-annotated seed priors, e.g.
    fed_policy/geopolitical -- not a calibration target). Migration 238's CHECK
    constraint also allows 3 not-yet-implemented values (correlation,
    cross_correlation, mutual_information) for future owner-annotated tags; an
    explicit allow-list here (rather than an implicit "!= definitional") stops a
    future row using one of those from being silently measured with the wrong
    (beta-regression) math -- a silent wrong answer is worse than a loud crash, so
    unimplemented types are logged and skipped via the same anomaly path as a null
    factor_series, never crashed on and never mismeasured.

    A row with measurement_type == 'beta_regression' but factor_series IS NULL should
    never exist post-238, but this loop defends against it anyway (defense-in-depth)
    rather than trusting the schema invariant blindly. Same defense-in-depth logic
    applies to loading_threshold IS NULL: tag_vocabulary has no NOT NULL constraint on
    that column, and the pass-3 keep gate (`abs(loading) >= loading_threshold`) would
    raise TypeError against a future beta_regression row that omits it (code review
    finding WR-04) -- caught here instead of crashing the whole run mid-loop.

    Returns (measurable_rows, skipped_tags) -- the caller logs exactly one WARNING per
    tag in the second list (once per vocabulary row, never inside the per-symbol hot
    loop).
    """
    measurable: list[dict[str, Any]] = []
    skipped_tags: list[str] = []
    for row in vocab_rows:
        if row["measurement_type"] == "definitional":
            continue
        if row["measurement_type"] != _IMPLEMENTED_MEASUREMENT_TYPE:
            skipped_tags.append(row["tag"])
            continue
        if row["factor_series"] is None or row["loading_threshold"] is None:
            skipped_tags.append(row["tag"])
            continue
        measurable.append(row)
    return measurable, skipped_tags


def _is_self_regression(symbol: str, factor_series: str) -> bool:
    """F6.1: an instrument can never be regressed against a factor series it is itself
    a component of -- single-symbol match (symbol == factor_series) OR one leg of a
    long-short spread (e.g. symbol='HYG' vs factor_series='HYG-IEF'). Checking leg
    membership via _factor_leg_symbols rather than raw string equality is required:
    four of migration 238's Phase-1 tags (credit_risk/HYG-IEF, inflation/TIP-IEF,
    yield_curve/IEF-SHY, oil_price/XLE-SPY) are long-short factor series whose value
    never string-equals a bare symbol even when that symbol is one of the two legs --
    a plain == check would let e.g. HYG get regressed against a "factor" containing
    HYG's own return as an additive term, a tautologically inflated loading almost
    certain to clear both FDR and loading_threshold (code review finding CR-01)."""
    return symbol in _factor_leg_symbols(factor_series)


def _factor_leg_symbols(factor_series: str) -> tuple[str, ...]:
    """Which raw price symbols must be fetched to build this factor_series' return
    series -- one symbol (single-symbol beta), two legs (hyphenated long-short), or
    SPY (the SPY_REALIZED_VOL sentinel)."""
    if factor_series == _VOL_SENTINEL:
        return ("SPY",)
    if "-" in factor_series:
        long_sym, short_sym = factor_series.split("-", 1)
        return (long_sym, short_sym)
    return (factor_series,)


# ---------------------------------------------------------------------------
# Pass 4 support: exclusion-aware control set + aligned control return matrix
# (Phase 175 Task 1c/1d)
# ---------------------------------------------------------------------------


def select_control_factor_series(
    symbol: str, tag_factor_series: str, control_factor_series: Sequence[str]
) -> list[str]:
    """Retained control legs for one (symbol, tag) Pass 4 partial-loading
    measurement. Two mandatory exclusions, both silent-wrong-answer guards:

    - drop a control equal to tag_factor_series -- residualizing the target
      factor against itself drives the partial loading identically to zero.
    - drop a control the candidate symbol is itself a leg of, via
      _is_self_regression -- the same F6.1/CR-01 tautology guard Pass 1
      already applies to its own target factor, extended here to the control
      legs.

    Preserves input order (determinism). Returns an empty list when every
    control is excluded -- the caller treats that as unmeasurable.
    """
    return [
        control
        for control in control_factor_series
        if control != tag_factor_series and not _is_self_regression(symbol, control)
    ]


def build_control_return_matrix(
    instrument_ret: pd.Series | None,
    factor_ret: pd.Series | None,
    control_series_list: list[pd.Series | None],
) -> tuple[np.ndarray, np.ndarray, np.ndarray] | None:
    """Align the candidate's return series, the target factor's return series,
    and every retained control's return series on a single shared index.

    Returns None, never raises, in every one of these cases:
      - instrument_ret is None -- the candidate symbol has no price_cache entry
      - factor_ret is None -- the target tag's factor_series produced no series
      - control_series_list is empty (every control was excluded upstream) or
        contains any None (a retained control's own return series is missing
        from the cache)

    On success, returns (instrument_arr, factor_arr, controls_2d) -- all three
    arrays share an identical length (one pd.concat(..., join="inner").dropna()
    call over the candidate, the factor, and every control column), and
    controls_2d has shape [n_obs, k].
    """
    if instrument_ret is None or factor_ret is None:
        return None
    if not control_series_list or any(control is None for control in control_series_list):
        return None

    frames = [instrument_ret.rename("instrument"), factor_ret.rename("factor")]
    control_names = [f"control_{i}" for i in range(len(control_series_list))]
    for name, control in zip(control_names, control_series_list, strict=True):
        frames.append(control.rename(name))

    aligned = pd.concat(frames, axis=1, join="inner").dropna()
    instrument_arr = aligned["instrument"].to_numpy()
    factor_arr = aligned["factor"].to_numpy()
    controls_2d = np.column_stack([aligned[name].to_numpy() for name in control_names])
    return instrument_arr, factor_arr, controls_2d


# ---------------------------------------------------------------------------
# Pass 1: factor-series construction + per-pair measurement (pure, DB-free)
# ---------------------------------------------------------------------------


def _log_returns(close: pd.Series) -> pd.Series:
    """Daily log-return series from a close-price series, with +/-inf swept to NaN
    before dropna(). np.log(close/close.shift(1)) produces -inf (not NaN) for any
    zero-or-negative close in the ratio, which plain .dropna() does not remove --
    an inf could otherwise flow into standardized_loading's std()/cov() and get
    silently clipped to exactly +/-1.0 by np.clip rather than surfacing as the NaN
    this module's guards are meant to guarantee (code review finding WR-05)."""
    return np.log(close / close.shift(1)).replace([np.inf, -np.inf], np.nan).dropna()


def _build_factor_return_series(
    factor_series: str,
    price_cache: dict[str, pd.Series],
    realized_vol_window: int,
    vix_z_window: int,
) -> tuple[pd.Series | None, int]:
    """Build the factor_series' return/level series from cached daily closes.

    Returns (series, extra_fitted_params) -- extra_fitted_params is forwarded to
    loading_hac_pvalue's df adjustment (1 for the long-short construction's implicit
    extra fitted parameter from differencing two legs, 0 otherwise). Returns
    (None, ...) when a required leg's price series isn't in the cache (missing data).
    """
    if factor_series == _VOL_SENTINEL:
        spy_close = price_cache.get("SPY")
        if spy_close is None:
            return None, 0
        # D-02/T-146-06: reuse breadth_vol's causal proxy verbatim via the factor_math
        # adapter -- never re-derive a non-causal whole-series percentile rank.
        #
        # spy_realized_vol_factor() returns a LEVEL (a z-scored realized-vol reading),
        # unlike every other factor_series branch here, which returns a RETURN series
        # (log-returns for a single symbol, long-short spread returns for a hyphenated
        # pair). _measure_pair always regresses instrument log-returns against
        # whatever this function returns -- pairing returns against a level is a units
        # mismatch, not merely weak signal: verified live that VIXY (an ETF whose sole
        # mandate is tracking equity vol) loads at -0.037 (wrong sign, below threshold)
        # against the raw level but 0.252 (correctly signed, clears loading_threshold)
        # once the level is differenced into a day-over-day change series -- the same
        # transform every other factor_series branch already applies implicitly by
        # being return-based from the start. Differencing here, not in
        # spy_realized_vol_factor() itself, keeps this fix scoped to TagCalibrator's
        # return-vs-return contract without disturbing the level this factor's other
        # consumer (regime classification) legitimately needs.
        vol_series = spy_realized_vol_factor(spy_close, realized_vol_window, vix_z_window)
        return vol_series.diff().dropna(), 0

    if "-" in factor_series:
        long_sym, short_sym = factor_series.split("-", 1)
        long_close = price_cache.get(long_sym)
        short_close = price_cache.get(short_sym)
        if long_close is None or short_close is None:
            return None, 1
        aligned_legs = pd.concat(
            [long_close.rename("long"), short_close.rename("short")], axis=1, join="inner"
        ).dropna()
        if len(aligned_legs) < 2:
            return None, 1
        spread_ret = long_short_daily_returns(
            aligned_legs["long"].to_numpy(), aligned_legs["short"].to_numpy()
        )
        return pd.Series(spread_ret, index=aligned_legs.index[1:]), 1

    factor_close = price_cache.get(factor_series)
    if factor_close is None:
        return None, 0
    return _log_returns(factor_close), 0


def _measure_pair(
    instrument_ret: pd.Series | None,
    factor_ret: pd.Series | None,
    extra_fitted_params: int,
    config: TagCalibratorConfig,
    condition_max: float,
) -> dict[str, Any] | None:
    """Measure one (symbol, tag) pair's standardized loading + HAC p-value + sample_n.

    Takes both the tag's factor_series return series (via measure_matrix's
    once-per-unique-factor_series cache) and the symbol's instrument return series
    (via measure_matrix's once-per-(symbol, lookback_days) cache) pre-built --
    neither depends on the other axis of the (symbol, tag) matrix, so rebuilding
    either one inside this per-pair function would redundantly recompute the
    identical series once per tag sharing a lookback_days (currently all 12
    measurable tags share lookback_days=252, so every symbol's log-return series
    would otherwise be rebuilt 12x).

    Returns None when the pair cannot be measured: fewer than lookback_days bars
    (instrument_ret is None), missing factor-leg data (factor_ret is None), a
    degenerate/ill-conditioned pair (factor_math's own NaN guards), or fewer than
    min_sample_n paired observations after alignment.
    """
    if instrument_ret is None or factor_ret is None:
        return None

    aligned = pd.concat(
        [instrument_ret.rename("instrument"), factor_ret.rename("factor")], axis=1, join="inner"
    ).dropna()
    n = len(aligned)
    if n < config.min_sample_n:
        return None

    instrument_arr = aligned["instrument"].to_numpy()
    factor_arr = aligned["factor"].to_numpy()

    loading = standardized_loading(instrument_arr, factor_arr, condition_max)
    if math.isnan(loading):
        return None
    p_value = loading_hac_pvalue(
        instrument_arr, factor_arr, config.hac_max_lag, extra_fitted_params=extra_fitted_params
    )
    if math.isnan(p_value):
        return None

    return {"loading": loading, "p_value": p_value, "sample_n": n}


def build_factor_series_cache(
    measurable_rows: list[dict[str, Any]],
    price_cache: dict[str, pd.Series],
    realized_vol_window: int,
    vix_z_window: int,
) -> dict[str, tuple[pd.Series | None, int]]:
    """Build every unique factor_series' return series exactly once.

    A factor_series' return series depends only on tag_row, never on symbol -- building
    each unique one exactly once rather than once per (symbol, tag) pair avoids every
    active symbol carrying a given tag (e.g. all ~58 equities for SPY_REALIZED_VOL)
    redundantly rebuilding the identical series, including breadth_vol's O(n^2) causal
    expanding-rank scan for the vol proxy.

    Extracted as its own function (not inlined in measure_matrix) so
    compute_factor_correlations() can reuse the identical, single-source-of-truth
    construction logic (single-symbol return, long-short spread return, or the vol
    sentinel's differenced level) rather than a second script re-deriving the same
    spreads from scratch -- exactly the sibling-script-drift class of bug
    methodology-change-ledger.md E12 already caught once for a hardcoded constant.
    """
    unique_factor_series = {tag_row["factor_series"] for tag_row in measurable_rows}
    return {
        factor_series: _build_factor_return_series(
            factor_series, price_cache, realized_vol_window, vix_z_window
        )
        for factor_series in unique_factor_series
    }


def compute_factor_correlations(
    factor_series_cache: dict[str, tuple[pd.Series | None, int]], min_sample_n: int
) -> list[dict[str, Any]]:
    """Pairwise raw correlation among every measurable factor_series' own return series.

    Pure, DB-free -- consumes the exact cache build_factor_series_cache() produces (never
    rebuilds a factor's return series independently). Canonical (factor_a < factor_b)
    ordering so each unordered pair appears exactly once; self-pairs are never emitted
    (skipped by the a < b iteration itself, not filtered after the fact). A pair with
    fewer than min_sample_n overlapping observations after alignment is skipped, matching
    _measure_pair's own sample-size floor rather than inventing a second threshold.
    """
    names = sorted(k for k, (series, _extra) in factor_series_cache.items() if series is not None)
    rows: list[dict[str, Any]] = []
    for i, factor_a in enumerate(names):
        series_a = factor_series_cache[factor_a][0]
        assert series_a is not None  # names filtered above
        for factor_b in names[i + 1 :]:
            series_b = factor_series_cache[factor_b][0]
            assert series_b is not None
            aligned = pd.concat(
                [series_a.rename("a"), series_b.rename("b")], axis=1, join="inner"
            ).dropna()
            if len(aligned) < min_sample_n:
                continue
            correlation = aligned["a"].corr(aligned["b"])
            if math.isnan(correlation):
                continue
            rows.append(
                {
                    "factor_a": factor_a,
                    "factor_b": factor_b,
                    "correlation": float(correlation),
                    "n_obs": len(aligned),
                }
            )
    return rows


_UPSERT_FACTOR_CORRELATION_SQL = """
    INSERT INTO factor_series_correlation (factor_a, factor_b, correlation, n_obs, computed_at)
    VALUES ($1, $2, $3, $4, $5)
    ON CONFLICT (factor_a, factor_b) DO UPDATE SET
        correlation = EXCLUDED.correlation,
        n_obs = EXCLUDED.n_obs,
        computed_at = EXCLUDED.computed_at
"""


async def _write_factor_correlations(
    conn: asyncpg.Connection, run_ts: datetime, rows: list[dict[str, Any]]
) -> None:
    """Upsert the full factor-correlation matrix computed this run. Always overwrites --
    this is a refreshed descriptive measurement (like instrument_tags' empirical rows),
    not an append-only ledger; no hysteresis or hold-out logic applies here."""
    for row in rows:
        await conn.execute(
            _UPSERT_FACTOR_CORRELATION_SQL,
            row["factor_a"],
            row["factor_b"],
            row["correlation"],
            row["n_obs"],
            run_ts,
        )


def measure_matrix(
    active_symbols: list[str],
    measurable_rows: list[dict[str, Any]],
    price_cache: dict[str, pd.Series],
    config: TagCalibratorConfig,
    condition_max: float,
    realized_vol_window: int,
    vix_z_window: int,
) -> tuple[list[dict[str, Any]], int, int]:
    """Pass 1: measure the full instrument x measurable-tag matrix (F8).

    Returns (measured, n_self_regression_skipped, n_insufficient_data_skipped) --
    per-pair skip reasons are accumulated as counters, never logged per-row (CLAUDE.md:
    never log per-row inside a loop over the full corpus).
    """
    measured: list[dict[str, Any]] = []
    n_self_regression = 0
    n_insufficient = 0

    factor_series_cache = build_factor_series_cache(
        measurable_rows, price_cache, realized_vol_window, vix_z_window
    )

    # A symbol's windowed log-return series depends only on (symbol, lookback_days),
    # never on which tag is being measured -- build each unique combination exactly
    # once per symbol rather than once per (symbol, tag) pair. Every measurable tag
    # currently shares lookback_days=252, so without this cache every symbol's
    # return series would be redundantly rebuilt once per tag (12x today).
    unique_lookback_days = {tag_row["lookback_days"] for tag_row in measurable_rows}

    for symbol in active_symbols:
        symbol_close = price_cache.get(symbol)
        if symbol_close is None:
            n_insufficient += len(measurable_rows)
            continue
        instrument_ret_cache: dict[int, pd.Series | None] = {
            lookback_days: (
                _log_returns(symbol_close.tail(lookback_days))
                if len(symbol_close) >= lookback_days
                else None
            )
            for lookback_days in unique_lookback_days
        }
        for tag_row in measurable_rows:
            if _is_self_regression(symbol, tag_row["factor_series"]):
                n_self_regression += 1
                continue
            factor_ret, extra_fitted_params = factor_series_cache[tag_row["factor_series"]]
            instrument_ret = instrument_ret_cache[tag_row["lookback_days"]]
            result = _measure_pair(
                instrument_ret,
                factor_ret,
                extra_fitted_params,
                config,
                condition_max,
            )
            if result is None:
                n_insufficient += 1
                continue
            measured.append(
                {
                    "symbol": symbol,
                    "tag": tag_row["tag"],
                    "loading_threshold": tag_row["loading_threshold"],
                    "half_life_days": tag_row["half_life_days"],
                    **result,
                }
            )
    return measured, n_self_regression, n_insufficient


# ---------------------------------------------------------------------------
# Pass 2: correct once (F1)
# ---------------------------------------------------------------------------


def apply_run_level_fdr(
    measured: list[dict[str, Any]],
    fdr_alpha: float,
    *,
    p_key: str = "p_value",
    reject_key: str = "passes_fdr",
    adjusted_key: str = "bh_adjusted_p",
) -> None:
    """F1 invariant: exactly ONE apply_bh_fdr call per p-vector, one p-vector per
    pass -- mutates each measured dict in place with reject_key/adjusted_key.
    No-op for an empty list.

    p_key/reject_key/adjusted_key default to Pass 1's own field names
    (p_value/passes_fdr/bh_adjusted_p) so this stays a pure generalization --
    Pass 1's existing call sites and tests are unaffected. Pass 4 (Task 2e)
    calls this a second time with p_key="null_arm_p_value" to correct the
    null-arm p-vector under its own field names, still exactly one
    apply_bh_fdr call for that p-vector."""
    if not measured:
        return
    p_values = [m[p_key] for m in measured]
    reject, p_corrected = apply_bh_fdr(p_values, fdr_alpha)
    for m, rej, p_corr in zip(measured, reject, p_corrected, strict=True):
        m[reject_key] = bool(rej)
        m[adjusted_key] = float(p_corr)


# ---------------------------------------------------------------------------
# Pass 4: orthogonalized materiality evidence (Phase 175 Task 2) -- measured
# unconditionally for every pair Pass 1-3 kept (D-01a). Statistical gate only;
# discovery_state/valid_to are separate, read-time-ANDed gates (R-04).
# ---------------------------------------------------------------------------


def measure_partial_loadings(
    kept_measurements: list[dict[str, Any]],
    factor_series_by_tag: dict[str, str],
    factor_series_cache: dict[str, tuple[pd.Series | None, int]],
    control_series_by_name: dict[str, tuple[pd.Series | None, int]],
    instrument_full_ret: dict[str, pd.Series],
    materiality: MaterialityConfig,
    hac_max_lag: int,
    condition_max: float,
) -> tuple[list[dict[str, Any]], int, int]:
    """Pass 4: measure the orthogonalized partial-loading evidence for every kept
    (symbol, tag) pair (D-01a's measurement universe -- Pass 1-3's keep gate).

    Shaped exactly like measure_matrix (Pass 1): accumulate skip counters,
    never log per-row (CLAUDE.md). Returns (pass4_rows, n_no_controls,
    n_insufficient_sample).

    Uses each symbol's FULL-history log-return series (instrument_full_ret),
    not a lookback_days-truncated slice (R-07) -- Pass 4 is a deliberately
    longer-horizon materiality judgment than Pass 1's per-tag bivariate
    measurement.
    """
    pass4_rows: list[dict[str, Any]] = []
    n_no_controls = 0
    n_insufficient_sample = 0

    for m in kept_measurements:
        symbol = m["symbol"]
        tag = m["tag"]
        tag_factor_series = factor_series_by_tag[tag]

        retained = select_control_factor_series(
            symbol, tag_factor_series, materiality.control_factor_series
        )
        if not retained:
            n_no_controls += 1
            continue

        candidate_ret = instrument_full_ret.get(symbol)
        factor_ret = factor_series_cache[tag_factor_series][0]
        control_series_list = [control_series_by_name[c][0] for c in retained]

        aligned = build_control_return_matrix(candidate_ret, factor_ret, control_series_list)
        if aligned is None:
            n_no_controls += 1
            continue
        instrument_arr, factor_arr, controls_2d = aligned

        materiality_sample_n = len(instrument_arr)
        if materiality_sample_n < materiality.min_sample_n:
            n_insufficient_sample += 1
            continue

        pl, inc_r2, _n = partial_loading(instrument_arr, factor_arr, controls_2d, condition_max)
        if math.isnan(pl):
            n_insufficient_sample += 1
            continue

        pl_ci_low = partial_loading_ci_low(
            instrument_arr,
            factor_arr,
            controls_2d,
            condition_max,
            hac_max_lag,
            materiality.null_arm_alpha,
        )
        n_stable, n_total = sign_stable_window_count(
            instrument_arr,
            factor_arr,
            controls_2d,
            condition_max,
            materiality.sign_stability_window_days,
            materiality.sign_stability_window_count,
        )

        # Per-pair deterministic RNG (T-175-16a): materiality.null_arm_seed is the
        # ONLY numeric seed input here -- mixed with a per-pair hash so a pair's
        # null p-value is reproducible independent of iteration order, while the
        # whole run stays re-randomizable from one APR write.
        rng = np.random.default_rng(
            materiality.null_arm_seed
            + hash_key_to_int(f"tag_calibrator_materiality_null_{symbol}_{tag}")
        )
        null_p = partial_loading_null_arm_p(
            instrument_arr,
            factor_arr,
            controls_2d,
            condition_max,
            materiality.null_arm_draws,
            rng,
        )

        pass4_rows.append(
            {
                "symbol": symbol,
                "tag": tag,
                "partial_loading": pl,
                "incremental_r2": inc_r2,
                "partial_loading_ci_low": pl_ci_low,
                "sign_stable_windows": n_stable,
                "sign_stable_windows_total": n_total,
                "null_arm_p_value": null_p,
                "materiality_sample_n": materiality_sample_n,
            }
        )

    return pass4_rows, n_no_controls, n_insufficient_sample


def decide_materiality(row: dict[str, Any], materiality: MaterialityConfig) -> bool:
    """The Pass 4 STATISTICAL gate only (R-04) -- deliberately does NOT consider
    discovery_state or valid_to (RESEARCH.md Pitfall 4): merging the temporal gate
    in here would make passes_materiality change value with no new measurement
    having run. is_materiality_eligible() ANDs all three gates at read time.

    Returns True only when ALL SIX conditions hold:
      1. materiality_sample_n >= min_sample_n
      2. abs(partial_loading) >= min_partial_loading
      3. partial_loading_ci_low >= min_partial_loading_ci_low
      4. incremental_r2 >= min_incremental_r2
      5. sign_stable_windows >= min_sign_stable_windows AND
         sign_stable_windows_total >= min_sign_stable_windows
      6. null_arm_passes_fdr is True

    Any NaN or missing required field -> False (never raises).

    Condition 5's agreement bar is a deliberate discrete step at n=1008, not a
    gradual slide (R-07, resolved 2026-09-18 D-07 review). min_sample_n (756) is
    exactly 3 x sign_stability_window_days (252), so a symbol at the sample
    floor has only three evaluable windows and must show 100% sign agreement
    (3 of 3) to pass, while a symbol with a full four evaluable windows needs
    only 75% (3 of 4) and may carry one disagreement -- the agreement bar
    slides STRICTER for shorter-history symbols, not looser. This is retained
    deliberately, not a bug: requiring a full four windows would make the
    min_sample_n floor unreachable (756 observations can never produce four
    disjoint 252-day windows), and this phase is shadow-mode measurement
    (D-02/D-03) with nothing downstream gated yet, so per D-04/D-05 the
    threshold stays conservative pending real corpus evidence rather than
    being adjusted on intuition. Plan 04's near-miss reporting (the
    sign-stable-windows distribution of FAILING candidates) is the mechanism
    that will supply that evidence; docs/foundation/apr-calibration-backlog.md
    tracks the eventual recalibration. Do not substitute
    sign_stable_windows_total == materiality.sign_stability_window_count and do
    not change either default.
    """
    sample_n = row.get("materiality_sample_n")
    pl = row.get("partial_loading")
    pl_ci_low = row.get("partial_loading_ci_low")
    inc_r2 = row.get("incremental_r2")
    n_stable = row.get("sign_stable_windows")
    n_total = row.get("sign_stable_windows_total")
    null_arm_passes_fdr = row.get("null_arm_passes_fdr")

    for value in (sample_n, pl, pl_ci_low, inc_r2, n_stable, n_total):
        if value is None or (isinstance(value, float) and math.isnan(value)):
            return False

    if sample_n < materiality.min_sample_n:
        return False
    if abs(pl) < materiality.min_partial_loading:
        return False
    if pl_ci_low < materiality.min_partial_loading_ci_low:
        return False
    if inc_r2 < materiality.min_incremental_r2:
        return False
    if n_stable < materiality.min_sign_stable_windows:
        return False
    if n_total < materiality.min_sign_stable_windows:
        return False
    return bool(null_arm_passes_fdr)


def is_materiality_eligible(row: dict[str, Any]) -> bool:
    """THE canonical read-time predicate (D-02's "one measurement engine, N
    read-time cutoffs") -- the shadow diagnostic (plan 04) and any future
    consumer cutover import this rather than re-deriving the conjunction.

    ANDs all three gates, stored separately by design:
      - statistical: passes_materiality (this phase's Pass 4)
      - temporal: discovery_state == 'confirmed' (todo 125)
      - expiry: valid_to IS NULL (todo 126)
    """
    return (
        bool(row.get("passes_materiality"))
        and row.get("discovery_state") == "confirmed"
        and row.get("valid_to") is None
    )


# ---------------------------------------------------------------------------
# Pass 3: decide (F2 hysteresis, keep/expire/discover)
# ---------------------------------------------------------------------------


def decide_outcome(
    *,
    keep: bool,
    existing_row: dict[str, Any] | None,
    expiry_consecutive_fails: int,
) -> dict[str, Any]:
    """Pure decision function -- the revised calibration loop's pass 3 branch logic.

    Human-asserted rows (source='human') are seed priors, never auto-expired and never
    overwritten by this loop: a keep decision against one is confirmed without a write;
    a fail decision only annotates the contradiction.

    Empirical rows follow F2 hysteresis: a fail only expires (valid_to = now()) once
    consecutive_fails >= expiry_consecutive_fails; a single failing run only increments
    the counter. Once expired, a repeated failing run is a no-op rather than
    re-expiring -- without this guard, every subsequent failing run would re-execute
    the expire SQL and reset valid_to to that run's timestamp, silently corrupting the
    recorded expiry time into "most recent calibration run" rather than "the run this
    tag actually became invalid" (code review finding WR-01).

    A keep with no existing row at all is a fresh discovery (no prior human assertion
    either, since existing_row is None) -- inserted and gap-annotated.

    Returns {"action": one of upsert_empirical/insert_discovery/expire/increment_fails/
    annotate_contradiction/confirm_human/no_op, "consecutive_fails": int}.
    """
    if existing_row is not None and existing_row.get("source") == "human":
        if keep:
            return {"action": "confirm_human", "consecutive_fails": 0}
        return {
            "action": "annotate_contradiction",
            "consecutive_fails": existing_row.get("consecutive_fails", 0),
        }

    if keep:
        if existing_row is not None:
            return {"action": "upsert_empirical", "consecutive_fails": 0}
        return {"action": "insert_discovery", "consecutive_fails": 0}

    if existing_row is None:
        return {"action": "no_op", "consecutive_fails": 0}

    if existing_row.get("valid_to") is not None:
        return {"action": "no_op", "consecutive_fails": existing_row.get("consecutive_fails", 0)}

    new_fails = existing_row.get("consecutive_fails", 0) + 1
    if new_fails >= expiry_consecutive_fails:
        return {"action": "expire", "consecutive_fails": new_fails}
    return {"action": "increment_fails", "consecutive_fails": new_fails}


def _next_evidence(
    existing_row: dict[str, Any] | None,
    run_ts: datetime,
    discovery_oos_days: int,
    clamped_half_life: int,
) -> dict[str, Any]:
    """Evidence JSONB payload for a keep decision -- tracks first_measured_at across
    runs (no dedicated schema column for discovery state exists; JSONB carries it) and
    derives discovery_state from elapsed calendar days vs. discovery_oos_days (F5)."""
    prev_evidence = (existing_row or {}).get("evidence") or {}
    first_measured_at_raw = prev_evidence.get("first_measured_at")
    first_measured_at = (
        datetime.fromisoformat(first_measured_at_raw) if first_measured_at_raw else run_ts
    )
    elapsed_days = (run_ts - first_measured_at).days
    discovery_state = "confirmed" if elapsed_days >= discovery_oos_days else "pending_oos"
    return {
        "first_measured_at": first_measured_at.isoformat(),
        "discovery_state": discovery_state,
        "half_life_days": clamped_half_life,
    }


_UPSERT_EMPIRICAL_SQL = """
    INSERT INTO instrument_tags (
        symbol, tag, weight, source, evidence, assigned_at,
        loading, p_value, bh_adjusted_p, passes_fdr, consecutive_fails, sample_n,
        estimated_at, valid_from, valid_to
    ) VALUES ($1, $2, $3, 'empirical', $4, now(), $5, $6, $7, $8, 0, $9, $10, now(), NULL)
    ON CONFLICT (symbol, tag) DO UPDATE SET
        weight = EXCLUDED.weight,
        source = 'empirical',
        evidence = EXCLUDED.evidence,
        loading = EXCLUDED.loading,
        p_value = EXCLUDED.p_value,
        bh_adjusted_p = EXCLUDED.bh_adjusted_p,
        passes_fdr = EXCLUDED.passes_fdr,
        consecutive_fails = 0,
        sample_n = EXCLUDED.sample_n,
        estimated_at = EXCLUDED.estimated_at,
        valid_to = NULL
"""

_UPDATE_FAILING_OR_EXPIRE_EMPIRICAL_SQL = """
    UPDATE instrument_tags SET
        consecutive_fails = $3,
        loading = $4,
        p_value = $5,
        bh_adjusted_p = $6,
        passes_fdr = $7,
        sample_n = $8,
        estimated_at = $9,
        valid_to = CASE WHEN $10 THEN now() ELSE valid_to END
    WHERE symbol = $1 AND tag = $2
"""

_INSERT_ANNOTATION_SQL = """
    INSERT INTO instrument_annotations (symbol, annotation_type, content, source, model_id)
    VALUES ($1, 'ai_insight', $2, 'ai', $3)
"""


async def _apply_decision(
    conn: asyncpg.Connection,
    run_ts: datetime,
    config: TagCalibratorConfig,
    measurement: dict[str, Any],
    existing_row: dict[str, Any] | None,
    decision: dict[str, Any],
) -> None:
    """Execute the DB write(s), if any, implied by one pair's pass-3 decision."""
    action = decision["action"]
    symbol = measurement["symbol"]
    tag = measurement["tag"]

    if action in ("upsert_empirical", "insert_discovery"):
        clamped_half_life = min(
            max(measurement["half_life_days"], config.half_life_min_days),
            config.half_life_max_days,
        )
        evidence = _next_evidence(
            existing_row, run_ts, config.discovery_oos_days, clamped_half_life
        )
        weight = abs(measurement["loading"])
        await conn.execute(
            _UPSERT_EMPIRICAL_SQL,
            symbol,
            tag,
            weight,
            evidence,
            measurement["loading"],
            measurement["p_value"],
            measurement["bh_adjusted_p"],
            measurement["passes_fdr"],
            measurement["sample_n"],
            run_ts,
        )
        if action == "insert_discovery":
            await conn.execute(
                _INSERT_ANNOTATION_SQL,
                symbol,
                (
                    f"TagCalibrator empirically discovered '{tag}' for {symbol} "
                    f"(loading={measurement['loading']:.3f}, "
                    f"bh_adjusted_p={measurement['bh_adjusted_p']:.4f}, "
                    f"sample_n={measurement['sample_n']}). No prior human assertion "
                    f"existed for this pair; pending_oos until "
                    f"{config.discovery_oos_days} days of out-of-sample confirmation."
                ),
                _JOB,
            )
    elif action in ("increment_fails", "expire"):
        await conn.execute(
            _UPDATE_FAILING_OR_EXPIRE_EMPIRICAL_SQL,
            symbol,
            tag,
            decision["consecutive_fails"],
            measurement["loading"],
            measurement["p_value"],
            measurement["bh_adjusted_p"],
            measurement["passes_fdr"],
            measurement["sample_n"],
            run_ts,
            action == "expire",
        )
        if action == "expire":
            await conn.execute(
                _INSERT_ANNOTATION_SQL,
                symbol,
                (
                    f"TagCalibrator expired empirical tag '{tag}' for {symbol}: "
                    f"{decision['consecutive_fails']} consecutive failing runs >= "
                    f"expiry_consecutive_fails={config.expiry_consecutive_fails}. Latest "
                    f"measurement: loading={measurement['loading']:.3f}, "
                    f"bh_adjusted_p={measurement['bh_adjusted_p']:.4f}."
                ),
                _JOB,
            )
    elif action == "annotate_contradiction":
        await conn.execute(
            _INSERT_ANNOTATION_SQL,
            symbol,
            (
                f"TagCalibrator measurement contradicts human-asserted tag '{tag}' for "
                f"{symbol}: loading={measurement['loading']:.3f}, "
                f"bh_adjusted_p={measurement['bh_adjusted_p']:.4f} does not clear the "
                "empirical gate this run. Human assertion is never auto-expired; "
                "flagged for review."
            ),
            _JOB,
        )
    # "confirm_human" and "no_op": no DB write -- human seed priors are never touched,
    # and a failing pair with no existing row has nothing to expire or annotate.


# ---------------------------------------------------------------------------
# TagCalibrator
# ---------------------------------------------------------------------------


class TagCalibrator(BaseBatch):
    """Batch compute service: tag_vocabulary + market_data_ohlcv_tradeable ->
    instrument_tags (empirical rows) + instrument_annotations (discovery/expiry/
    contradiction notes).

    Generic 3-pass engine: measure the full instrument x measurable-tag matrix (F8),
    correct once via run-level BH-FDR (F1), decide keep/expire/discover per pair with
    hysteresis (F2).
    """

    job_name = _JOB
    compute_version = "1.0.0"

    async def execute(self, pool: asyncpg.Pool) -> None:
        run_ts = datetime.now(UTC)
        self.logger.info("tag_calibrator.run_ts_locked", run_ts=str(run_ts))

        async with pool.acquire() as conn:
            apr_cfg = await _load_apr_dict(conn)
            config = TagCalibratorConfig.from_apr(apr_cfg)
            # Constructed once, here, and reused by both the price_symbols assembly
            # below and Pass 4's wiring later in execute() (Task 2(e)) -- never
            # constructed a second time (the same forward-reference-ordering
            # discipline the D-07 review applied to factor_series_cache).
            materiality = MaterialityConfig.from_apr(apr_cfg)
            # Reuse of existing APR keys (not new alpha.tag_calibrator.* additions):
            # mv_condition_max is ensemble_trainer's own ill-conditioning gate default,
            # reused here for the identical class of problem (Sigma^-1/correlation
            # solve on estimated data); realized_vol_window/vix_z_window are the
            # regime-model's existing SPY-realized-vol proxy window params (D-02,
            # T-146-06) -- never re-derived, always the same causal proxy.
            condition_max = _cfg(apr_cfg, "alpha.ensemble.mv_condition_max", 1000.0)
            realized_vol_window = _cfg(apr_cfg, "alpha.regime.realized_vol_window", 20)
            vix_z_window = _cfg(apr_cfg, "alpha.regime.vix_z_window", 252)

            vocab_rows = [
                dict(r)
                for r in await conn.fetch(
                    "SELECT tag, factor_series, measurement_type, lookback_days, "
                    "loading_threshold, half_life_days FROM tag_vocabulary"
                )
            ]
            measurable_rows, skipped_tags = filter_measurable_tag_rows(vocab_rows)
            for tag in skipped_tags:
                self.logger.warning(
                    "tag_calibrator.tag_not_measurable",
                    tag=tag,
                    note=(
                        "not measurable this run -- one of: measurement_type is not "
                        "yet 'beta_regression' (no dispatch implemented for it); "
                        "factor_series IS NULL despite a non-definitional "
                        "measurement_type (migration 238's Option A sweep should make "
                        "this impossible); or loading_threshold IS NULL (no NOT NULL "
                        "constraint on that column) -- data-integrity anomaly in all "
                        "three cases"
                    ),
                )

            active_symbols = [
                r["symbol"]
                for r in await conn.fetch(
                    "SELECT symbol FROM instruments WHERE is_active = true "
                    "AND contract_details->>'asset_class' = 'equity'"
                )
            ]

            price_symbols: set[str] = set(active_symbols)
            for row in measurable_rows:
                price_symbols.update(_factor_leg_symbols(row["factor_series"]))
            # The control set is APR-configurable (materiality.control_factor_series)
            # and not necessarily covered by the measured tags' own factor_series
            # values -- a future edit (e.g. appending DBC per R-03) must not silently
            # produce a missing-price cache miss.
            for control in materiality.control_factor_series:
                price_symbols.update(_factor_leg_symbols(control))

            price_cache = await self._fetch_price_cache(conn, sorted(price_symbols))

            existing_by_pair = {
                (r["symbol"], r["tag"]): dict(r)
                for r in await conn.fetch(
                    "SELECT symbol, tag, source, weight, evidence, consecutive_fails, "
                    "valid_to FROM instrument_tags"
                )
            }

        measured, n_self_regression, n_insufficient = measure_matrix(
            active_symbols,
            measurable_rows,
            price_cache,
            config,
            condition_max,
            realized_vol_window,
            vix_z_window,
        )

        apply_run_level_fdr(measured, config.fdr_alpha)

        # D-01a's measurement universe: a measurement is "kept" when it clears
        # Pass 1-3's existing keep gate. Computed ONCE per measurement here and
        # reused for both Pass 4 selection below and decide_outcome further down
        # -- never evaluated twice.
        for m in measured:
            m["keep"] = m["passes_fdr"] and abs(m["loading"]) >= m["loading_threshold"]
        kept_measurements = [m for m in measured if m["keep"]]

        # Pass 4 wiring (Task 2e): reuse the `materiality` config already
        # constructed above (never re-constructed here). factor_series_cache
        # (the TARGET-factor cache, keyed by each measured tag's own
        # factor_series), factor_series_by_tag, control_series_by_name (the
        # control-LEG cache, keyed by control name), and instrument_full_ret are
        # NOT otherwise in scope at this point -- required by
        # measure_partial_loadings, not optional; omitting any of them is a
        # NameError, not a style question.
        factor_series_cache = build_factor_series_cache(
            measurable_rows, price_cache, realized_vol_window, vix_z_window
        )
        factor_series_by_tag = {r["tag"]: r["factor_series"] for r in measurable_rows}
        control_series_by_name = build_factor_series_cache(
            [{"factor_series": control} for control in materiality.control_factor_series],
            price_cache,
            realized_vol_window,
            vix_z_window,
        )
        instrument_full_ret = {sym: _log_returns(close) for sym, close in price_cache.items()}

        pass4_rows, n_materiality_no_controls, n_materiality_insufficient_sample = (
            measure_partial_loadings(
                kept_measurements,
                factor_series_by_tag,
                factor_series_cache,
                control_series_by_name,
                instrument_full_ret,
                materiality,
                config.hac_max_lag,
                condition_max,
            )
        )
        apply_run_level_fdr(
            pass4_rows,
            materiality.null_arm_alpha,
            p_key="null_arm_p_value",
            reject_key="null_arm_passes_fdr",
            adjusted_key="null_arm_bh_p",
        )
        for pass4_row in pass4_rows:
            pass4_row["passes_materiality"] = decide_materiality(pass4_row, materiality)
        n_passes_materiality = sum(1 for row in pass4_rows if row["passes_materiality"])

        outcome_counts: dict[str, int] = {}
        async with pool.acquire() as conn:
            for m in measured:
                existing = existing_by_pair.get((m["symbol"], m["tag"]))
                decision = decide_outcome(
                    keep=m["keep"],
                    existing_row=existing,
                    expiry_consecutive_fails=config.expiry_consecutive_fails,
                )
                await _apply_decision(conn, run_ts, config, m, existing, decision)
                outcome = _DECISION_OUTCOME_LABELS[decision["action"]]
                _TAG_CALIBRATION_TOTAL.add(1, {"tag": m["tag"], "outcome": outcome})
                outcome_counts[outcome] = outcome_counts.get(outcome, 0) + 1

            # Reuses build_factor_series_cache() -- the same single-source-of-truth
            # construction logic measure_matrix() already ran above -- rather than a
            # second script re-deriving the same factor spreads independently (E12-class
            # drift risk). Rebuilding here (a cheap, pure, no-IO computation on the
            # already-fetched price_cache) is deliberately preferred over threading a
            # returned cache through measure_matrix()'s tested public signature.
            factor_cache = build_factor_series_cache(
                measurable_rows, price_cache, realized_vol_window, vix_z_window
            )
            factor_correlations = compute_factor_correlations(factor_cache, config.min_sample_n)
            await _write_factor_correlations(conn, run_ts, factor_correlations)

        self.logger.info(
            "tag_calibrator.run_complete",
            n_measured=len(measured),
            n_self_regression_skipped=n_self_regression,
            n_insufficient_data_skipped=n_insufficient,
            n_tags_not_measurable=len(skipped_tags),
            outcome_counts=outcome_counts,
            n_factor_correlations_written=len(factor_correlations),
            n_materiality_measured=len(pass4_rows),
            n_materiality_no_controls=n_materiality_no_controls,
            n_materiality_insufficient_sample=n_materiality_insufficient_sample,
            n_passes_materiality=n_passes_materiality,
        )

    async def _fetch_price_cache(
        self, conn: asyncpg.Connection, symbols: list[str]
    ) -> dict[str, pd.Series]:
        """Fetch every needed symbol's full daily-close history in one query, from
        market_data_ohlcv_tradeable ONLY (D-11) -- never the raw market_data_ohlcv
        calendar grid."""
        if not symbols:
            return {}
        rows = await conn.fetch(
            "SELECT symbol, timestamp, close FROM market_data_ohlcv_tradeable "
            "WHERE symbol = ANY($1::text[]) AND timeframe = '1d' ORDER BY symbol, timestamp ASC",
            symbols,
        )
        grouped: dict[str, list[tuple[Any, float]]] = {}
        for row in rows:
            grouped.setdefault(row["symbol"], []).append((row["timestamp"], float(row["close"])))
        return {
            sym: pd.Series([c for _, c in entries], index=[t for t, _ in entries], name=sym)
            for sym, entries in grouped.items()
        }


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    try:
        init_otel_providers("indicagent-tag-calibrator")
    except OTelInitError as error:
        _logger.warning("tag_calibrator.otel_init_failed", error=str(error))

    settings = Settings()
    db_dsn = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
    asyncio.run(TagCalibrator(db_dsn=db_dsn).run())
