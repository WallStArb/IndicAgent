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
import math
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
from src.intelligence.statistics.factor_math import (
    loading_hac_pvalue,
    long_short_daily_returns,
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
    rather than trusting the schema invariant blindly.

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
        if row["factor_series"] is None:
            skipped_tags.append(row["tag"])
            continue
        measurable.append(row)
    return measurable, skipped_tags


def _is_self_regression(symbol: str, factor_series: str) -> bool:
    """F6.1: an instrument can never be regressed against itself."""
    return symbol == factor_series


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
# Pass 1: factor-series construction + per-pair measurement (pure, DB-free)
# ---------------------------------------------------------------------------


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
        vol_series = spy_realized_vol_factor(spy_close, realized_vol_window, vix_z_window)
        return vol_series.dropna(), 0

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
    factor_ret = np.log(factor_close / factor_close.shift(1)).dropna()
    return factor_ret, 0


def _measure_pair(
    symbol_close: pd.Series,
    tag_row: dict[str, Any],
    factor_ret: pd.Series | None,
    extra_fitted_params: int,
    config: TagCalibratorConfig,
    condition_max: float,
) -> dict[str, Any] | None:
    """Measure one (symbol, tag) pair's standardized loading + HAC p-value + sample_n.

    Takes the tag's factor_series return series pre-built (via measure_matrix's
    once-per-unique-factor_series cache, not rebuilt per symbol -- the factor_series
    depends only on tag_row, never on symbol).

    Returns None when the pair cannot be measured: fewer than lookback_days bars,
    missing factor-leg data (factor_ret is None), a degenerate/ill-conditioned pair
    (factor_math's own NaN guards), or fewer than min_sample_n paired observations
    after alignment.
    """
    lookback_days = tag_row["lookback_days"]
    if len(symbol_close) < lookback_days:
        return None
    windowed_close = symbol_close.tail(lookback_days)
    instrument_ret = np.log(windowed_close / windowed_close.shift(1)).dropna()

    if factor_ret is None:
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

    # A factor_series' return series depends only on tag_row, never on symbol --
    # build each unique one exactly once rather than once per (symbol, tag) pair.
    # Otherwise every active symbol carrying a given tag (e.g. all ~58 equities for
    # SPY_REALIZED_VOL) would redundantly rebuild the identical series, including
    # breadth_vol's O(n^2) causal expanding-rank scan for the vol proxy.
    unique_factor_series = {tag_row["factor_series"] for tag_row in measurable_rows}
    factor_series_cache: dict[str, tuple[pd.Series | None, int]] = {
        factor_series: _build_factor_return_series(
            factor_series, price_cache, realized_vol_window, vix_z_window
        )
        for factor_series in unique_factor_series
    }

    for symbol in active_symbols:
        symbol_close = price_cache.get(symbol)
        if symbol_close is None:
            n_insufficient += len(measurable_rows)
            continue
        for tag_row in measurable_rows:
            if _is_self_regression(symbol, tag_row["factor_series"]):
                n_self_regression += 1
                continue
            factor_ret, extra_fitted_params = factor_series_cache[tag_row["factor_series"]]
            result = _measure_pair(
                symbol_close,
                tag_row,
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


def apply_run_level_fdr(measured: list[dict[str, Any]], fdr_alpha: float) -> None:
    """F1: exactly ONE apply_bh_fdr call over the full run's p-vector -- mutates each
    measured dict in place with bh_adjusted_p/passes_fdr. No-op for an empty list."""
    if not measured:
        return
    p_values = [m["p_value"] for m in measured]
    reject, p_corrected = apply_bh_fdr(p_values, fdr_alpha)
    for m, rej, p_corr in zip(measured, reject, p_corrected, strict=True):
        m["passes_fdr"] = bool(rej)
        m["bh_adjusted_p"] = float(p_corr)


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
    the counter.

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

    def __init__(self, db_dsn: str) -> None:
        super().__init__(db_dsn)

    async def execute(self, pool: asyncpg.Pool) -> None:
        try:
            await self._execute_inner(pool)
        except Exception as error:  # CLAUDE.md: exception variable name is `error`
            self.logger.error("tag_calibrator.failed", error=str(error))
            raise

    async def _execute_inner(self, pool: asyncpg.Pool) -> None:
        run_ts = datetime.now(UTC)
        self.logger.info("tag_calibrator.run_ts_locked", run_ts=str(run_ts))

        async with pool.acquire() as conn:
            apr_cfg = await _load_apr_dict(conn)
            config = TagCalibratorConfig.from_apr(apr_cfg)
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
                        "not measurable this run -- either measurement_type is not yet "
                        "'beta_regression' (no dispatch implemented for it) or "
                        "factor_series IS NULL despite a non-definitional "
                        "measurement_type (migration 238's Option A sweep should make "
                        "the latter impossible; data-integrity anomaly either way)"
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

        outcome_counts: dict[str, int] = {}
        async with pool.acquire() as conn:
            for m in measured:
                keep = m["passes_fdr"] and abs(m["loading"]) >= m["loading_threshold"]
                existing = existing_by_pair.get((m["symbol"], m["tag"]))
                decision = decide_outcome(
                    keep=keep,
                    existing_row=existing,
                    expiry_consecutive_fails=config.expiry_consecutive_fails,
                )
                await _apply_decision(conn, run_ts, config, m, existing, decision)
                outcome = _DECISION_OUTCOME_LABELS[decision["action"]]
                _TAG_CALIBRATION_TOTAL.add(1, {"tag": m["tag"], "outcome": outcome})
                outcome_counts[outcome] = outcome_counts.get(outcome, 0) + 1

        self.logger.info(
            "tag_calibrator.run_complete",
            n_measured=len(measured),
            n_self_regression_skipped=n_self_regression,
            n_insufficient_data_skipped=n_insufficient,
            n_tags_not_measurable=len(skipped_tags),
            outcome_counts=outcome_counts,
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
