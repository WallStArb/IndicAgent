#!/usr/bin/env python3
"""
portfolio_covariance_weighting_diagnostic.py -- shadow-mode diagnostic for whether cross-instrument
covariance-aware portfolio weighting beats naive/IC-proportional/volatility-normalized baselines.

See docs/superpowers/specs/2026-09-16-cross-instrument-covariance-aware-portfolio-diagnostic-design.md
for the full design, including why resolve_stratum_weights/derive_weights are NOT reused (they zero
non-positive inputs, which is wrong for a signed instrument book -- confirmed against the actual code
during design review) and why Sigma is estimated from realized historical returns, never forward_returns.

Method (must match the spec exactly -- do not "fix" any of this without updating the spec first):
- mu_i = IC_shrunk_i * sigma_i * z_i, where z_i is instrument i's OWN trailing score history
  standardized to zero mean / unit variance (fixes cross-instrument score-scale mismatch), IC_shrunk_i
  is instrument i's trailing rank-IC shrunk via empirical-Bayes toward the leave-one-out peer mean, and
  sigma_i is the diagonal of the realized-return covariance matrix.
- Sigma: Ledoit-Wolf shrinkage covariance of REALIZED historical log returns
  (ln(close_t/close_{t-1})) -- never forward_returns, which are targets/labels, not observations.
- Embargo: any refit at boundary T uses forward-return rows with bar_ts <= T - 2 trading days only.
- Two decoupled cadences: covariance/IC refit every _REFIT_EVERY_BARS trading days (coarse), weight
  recomputation from that day's alpha_score every trading day (fine).
- Four comparison arms: equal-weight, IC-proportional, volatility-normalized (diagonal-Sigma special
  case), full mean-variance (off-diagonal Sigma).
- No --gate: this is a measurement tool, not a promotion gate.

Exit-code contract: 0 = ran successfully. 1 = the script errored (DB connection failure, unhandled
exception, bad arguments). No gate exit code (2) -- see spec's "Output" section.

Usage:
    .venv/bin/python scripts/analysis/portfolio_covariance_weighting_diagnostic.py \\
        --symbols GLD,DBA,DBB,DBC,URA,TLT,UUP,VIXY,EMLC,HYG,XOM,DHI,PGR \\
        --weight-version v1 --json-out /var/tmp/portfolio_covariance_diagnostic.json
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import psycopg  # noqa: E402
import structlog  # noqa: E402
from scipy.stats import spearmanr  # noqa: E402

from src.config.settings import Settings  # noqa: E402
from src.core.service_utils import setup_service_logging  # noqa: E402
from src.intelligence.ensemble.covariance import (  # noqa: E402
    compute_shrinkage_covariance,
    covariance_to_correlation,
)
from src.intelligence.ensemble.shrinkage import (  # noqa: E402
    leave_one_out_group_prior,
    shrink_ic,
)
from src.intelligence.ensemble.weights import effective_n as ensemble_effective_n  # noqa: E402
from src.intelligence.ensemble.weights import mean_variance_weights  # noqa: E402
from src.intelligence.statistics.ic_math import check_condition_number  # noqa: E402
from src.observability.metrics import JOB_COMPLETED_TOTAL, flush_and_shutdown_metrics  # noqa: E402

setup_service_logging("logs/portfolio_covariance_weighting_diagnostic.log")
_logger = structlog.get_logger(__name__)

_JOB_NAME = "portfolio-covariance-weighting-diagnostic"
_TIMEFRAME = "1d"
_SYMBOL_BATCH_SIZE = 25
_CORR_MIN_PERIODS = 20

# Reused verbatim from alpha.hmm.walk_forward.{refit_every_bars,initial_warmup_bars}.1d -- todo 248's
# only existing walk-forward precedent in this codebase. Not APR-backed here (see module docstring):
# a diagnostic's own methodology constants must require a code edit to change so its numbers stay
# comparable run-to-run.
_REFIT_EVERY_BARS = 252
_INITIAL_WARMUP_BARS = 504

# executable_open_to_open at bar T is ln(open[T+2]/open[T+1]) -- the value is not fully known
# until open[T+2] prints, i.e. the START of bar T+2. Convention used throughout this module:
# a refit/rebalance "at" position `pos` happens AS OF THE CLOSE of day `pos` (the same
# inclusive-of-today convention run_walk_forward's z_today already uses for alpha_wide, since
# alpha_score(pos) is itself computed from data through pos's own close) -- so open[pos] and
# close[pos] are both already known by the time we are "at" pos. A refit at boundary `pos` may
# therefore use any forward-return row with bar_ts S where S+2 <= pos (i.e. S <= pos - 2):
# that row's required open[S+2] is <= open[pos], already printed. Do not change this value
# without re-deriving against the SAME end-of-day convention z_today uses -- a stricter
# start-of-day convention would require _EMBARGO_BARS = 3, but would then be inconsistent with
# z_today's own inclusive-of-rebal_date alpha usage a few lines below.
_EMBARGO_BARS = 2

# Matches alpha.ensemble.mv_condition_max's live default (1000) -- hardcoded per this module's own
# non-APR methodology-constant convention (see docstring), not because it disagrees with that key.
_MV_CONDITION_MAX = 1000.0

# Matches alpha.ic.shrinkage_k's live default (100).
_IC_SHRINKAGE_K = 100.0

# Ridge fallback for an ill-conditioned instrument covariance: Sigma + epsilon * I, epsilon scaled to
# 10% of the matrix's own average variance (trace/n) so the ridge term is meaningful regardless of the
# instruments' absolute return-variance scale.
_RIDGE_EPSILON_FRACTION = 0.10

# Causal regime proxy: trailing SPY SMA window, shifted 1 bar so today's regime label never uses
# today's own close.
_REGIME_SMA_WINDOW = 200


# ---------------------------------------------------------------------------
# Pure functions -- no I/O, no logging. Unit-tested directly against synthetic data in
# tests/unit/scripts/test_portfolio_covariance_weighting_diagnostic.py.
# ---------------------------------------------------------------------------


def standardize_scores(score_history: pd.Series) -> pd.Series:
    """Per-instrument time-series z-score: (score - mean) / std, using this instrument's OWN
    trailing score history. Fixes the cross-instrument score-scale mismatch the design review
    found -- different instruments' alpha_score composites have different variance (different
    active-feature counts, different feature volatility), so standardization must happen
    per-instrument, not globally across instruments.

    A zero-variance (degenerate/constant) score history returns an all-zero series rather than
    dividing by zero -- "no signal" is the correct z-score for "no variation to standardize".
    """
    std = score_history.std(ddof=0)
    if not np.isfinite(std) or std < 1e-12:
        return pd.Series(0.0, index=score_history.index)
    return (score_history - score_history.mean()) / std


def shrink_instrument_ic(ic_raw: np.ndarray, n_eff: np.ndarray, k: float) -> np.ndarray:
    """Empirical-Bayes shrink each instrument's trailing IC toward the leave-one-out
    cross-sectional mean of the other instruments in the same refit, reusing shrink_ic()/
    leave_one_out_group_prior() unchanged (src/intelligence/ensemble/shrinkage.py) rather than
    reimplementing the shrinkage math -- same reasoning as reusing compute_shrinkage_covariance.
    """
    n = len(ic_raw)
    shrunk = np.zeros(n, dtype=float)
    for i in range(n):
        prior = leave_one_out_group_prior(ic_raw, i)
        shrunk[i], _weight = shrink_ic(float(ic_raw[i]), float(n_eff[i]), prior, k)
    return shrunk


def compute_mu(ic_shrunk: np.ndarray, sigma: np.ndarray, z_latest: np.ndarray) -> np.ndarray:
    """mu_i = IC_shrunk_i * sigma_i * z_i -- the corrected Grinold-Kahn calibration (spec's
    "Critical correction... REVISED after review" section). z_latest is each instrument's
    standardized score AT the current rebalance date (the most recent value of the
    standardize_scores() series), sigma is the diagonal of the realized-return covariance matrix.
    """
    return ic_shrunk * sigma * z_latest


def log_returns(close_wide: pd.DataFrame) -> pd.DataFrame:
    """(dates x symbols) log-return frame from a (dates x symbols) close-price frame. First row
    is always dropped (no prior bar to diff against)."""
    return np.log(close_wide / close_wide.shift(1)).iloc[1:]


def instrument_covariance(returns: pd.DataFrame) -> tuple[np.ndarray, np.ndarray, list[str]]:
    """Ledoit-Wolf shrinkage covariance/correlation of REALIZED historical log returns (never
    forward_returns -- see module docstring). Drops any symbol with fewer than
    _CORR_MIN_PERIODS non-null observations before fitting, same reliability floor
    correlation_structure() uses in universe_expansion_correlation_structure_check.py.
    """
    counts = returns.count()
    kept = sorted(counts[counts >= _CORR_MIN_PERIODS].index.tolist())
    X = returns[kept].fillna(0.0).to_numpy()
    cov, _shrinkage = compute_shrinkage_covariance(X)
    corr = covariance_to_correlation(cov)
    return cov, corr, kept


def equal_weight_arm(n: int) -> np.ndarray:
    """Arm 1: naive equal-weight. No covariance adjustment, no IC weighting."""
    if n == 0:
        return np.zeros(0)
    return np.full(n, 1.0 / n)


def _normalize_by_abs_sum(raw: np.ndarray) -> np.ndarray:
    total = float(np.sum(np.abs(raw)))
    if total < 1e-10:
        return np.zeros_like(raw)
    return raw / total


def ic_proportional_arm(mu: np.ndarray) -> np.ndarray:
    """Arm 2: each instrument weighted by its own calibrated mu_i, no cross-instrument
    covariance adjustment -- what's implicit in today's architecture (each instrument scored
    independently). Signed (long/short) -- normalized by sum of ABSOLUTE weights, since mu can
    be negative and a signed book's total exposure convention is gross, not net."""
    return _normalize_by_abs_sum(mu)


def vol_normalized_arm(mu: np.ndarray, sigma: np.ndarray) -> np.ndarray:
    """Arm 2b (added after design review): w_i ~ mu_i / sigma_i^2 -- the diagonal-only special
    case of mean-variance (inverse-volatility scaling, no off-diagonal correlation term).
    Isolates "just scale by volatility" from real covariance/correlation-awareness (Arm 4);
    without this arm, an apparent Arm 4 win over Arm 2 can't be attributed to correlation
    modeling instead of trivial vol scaling."""
    sigma_safe = np.where(sigma > 1e-12, sigma, np.inf)
    raw = mu / sigma_safe**2
    return _normalize_by_abs_sum(raw)


def mean_variance_arm(
    cov_matrix: np.ndarray, mu: np.ndarray, condition_max: float
) -> tuple[np.ndarray, str, float]:
    """Arm 4: full mean-variance covariance-aware weighting -- the primitive
    mean_variance_weights() solve (Sigma^-1 . mu), NOT resolve_stratum_weights (see spec's
    Component reuse revision: that wrapper's derive_weights zeroes non-positive inputs, which
    is wrong for a signed instrument book).

    On an ill-conditioned Sigma, falls back to ridge regularization (Sigma + epsilon*I, epsilon
    scaled to 10% of the matrix's own average variance) and re-solves -- never
    cluster_deflate_weights/derive_weights, which assume a feature-staleness input this
    diagnostic doesn't have. If even the ridge-regularized matrix is unusable, falls back
    further to vol_normalized_arm (the diagonal-only special case) rather than reimplementing
    a second, independent diagonal solve -- one source of truth for "volatility-only weighting"
    in this file. The fallback is always returned in method_used, matching ensemble_trainer.py's
    "mean_variance_fallback must never be silent" discipline -- callers (the walk-forward
    orchestrator) are responsible for logging it.
    """
    raw, cond = mean_variance_weights(cov_matrix, mu, condition_max)
    if raw is not None:
        return _normalize_by_abs_sum(raw), "mean_variance", cond

    n = cov_matrix.shape[0]
    epsilon = _RIDGE_EPSILON_FRACTION * float(np.trace(cov_matrix)) / max(n, 1)
    ridge_cov = cov_matrix + epsilon * np.eye(n)
    ridge_ok, _ridge_cond = check_condition_number(ridge_cov, condition_max)
    if ridge_ok:
        raw_ridge = np.linalg.solve(ridge_cov, mu)
        return _normalize_by_abs_sum(raw_ridge), "mean_variance_ridge_fallback", cond

    sigma = np.sqrt(np.maximum(np.diag(cov_matrix), 1e-12))
    return vol_normalized_arm(mu, sigma), "mean_variance_ridge_fallback", cond


def portfolio_exposure_stats(weights: np.ndarray) -> dict[str, float]:
    """gross/net exposure, effective_n, and Herfindahl for a (possibly signed) weight vector.

    effective_n = 1/sum(w^2) is reused from the feature-combination case, but reported alongside
    gross/net exposure rather than alone -- the design review found 1/sum(w^2) misleading in
    isolation once weights are signed and non-unit-sum (Arms 3-4 can carry negative entries;
    the feature-combination case this formula was built for is always non-negative and unit-sum).
    """
    gross = float(np.sum(np.abs(weights)))
    net = float(np.sum(weights))
    herfindahl = float(np.sum(weights**2))
    return {
        "gross_exposure": gross,
        "net_exposure": net,
        "herfindahl": herfindahl,
        "effective_n": ensemble_effective_n(weights),
    }


def l1_turnover(w_prev: np.ndarray, w_curr: np.ndarray) -> float:
    """sum(|w_t - w_{t-1}|) -- L1 turnover between two consecutive rebalance weight vectors.
    Reported per arm per rebalance (Output section, spec) so a mean-variance arm's tendency to
    churn on small mu/Sigma shifts is visible, not hidden behind a gross-return-only report."""
    return float(np.sum(np.abs(w_curr - w_prev)))


def causal_regime_labels(spy_close: pd.Series, window: int = _REGIME_SMA_WINDOW) -> pd.Series:
    """Causal bull/bear regime proxy: trailing SMA of SPY close, SHIFTED one bar so today's
    label never depends on today's own close (avoids same-bar lookahead entirely, by
    construction -- no walk-forward loop needed for this proxy, unlike Sigma/IC).

    Used instead of market_regimes/regime_writer.py's HMM labels, which carry a confirmed
    non-causal contamination (full-series fit; walk-forward fix exists but is disabled -- todo
    248). Cheap, causal by construction, avoids inheriting that unresolved bug rather than just
    disclosing it (spec's Method section, "Regime split on a causal proxy").

    Returns NaN for any date before the trailing window is full.
    """
    trailing_sma = spy_close.rolling(window).mean().shift(1)
    label = pd.Series(np.where(spy_close > trailing_sma, "bull", "bear"), index=spy_close.index)
    return label.where(trailing_sma.notna())


_ARM_FUNCS = ("equal_weight", "ic_proportional", "vol_normalized", "mean_variance")


def run_walk_forward(
    close_wide: pd.DataFrame,
    alpha_wide: pd.DataFrame,
    fwd_return_wide: pd.DataFrame,
    cost_hurdle_wide: pd.DataFrame,
    spy_close: pd.Series,
) -> dict[str, Any]:
    """Full walk-forward diagnostic over already-fetched, already-aligned (dates x symbols)
    frames -- no DB access here, so this is directly unit-testable against synthetic data.

    Two decoupled cadences (spec's Method section):
    - Sigma/IC refit every _REFIT_EVERY_BARS trading days, using data through the embargo
      boundary (current index position - _EMBARGO_BARS) only.
    - Weight recomputation from that day's alpha_score every trading day, using the most
      recent refit's Sigma/IC_shrunk.

    Returns the full report dict: per-arm rebalance-step history, per-arm aggregate stats
    (unconditional + causal regime split), and refit-level diagnostics (condition number,
    fallback flag, ic_shrunk -- so a caller can audit exactly what each refit saw).
    """
    dates = close_wide.index
    symbols = sorted(close_wide.columns.tolist())
    returns = log_returns(close_wide[symbols])
    regime_labels = causal_regime_labels(spy_close)
    # Aligned to the full row AND column set once outside the loop. Row alignment was a
    # per-iteration single-row reindex; column alignment to the full `symbols` list (rather
    # than whatever columns alpha_events/forward_returns happened to return) guards against a
    # KeyError if any instrument that cleared the price-coverage bar has zero alpha_events rows
    # for this weight_version/tf/window -- its column becomes all-NaN instead of missing, and
    # existing NaN handling (standardize_scores' zero-variance guard, .fillna(0.0) below)
    # already degrades it to "no signal" gracefully.
    alpha_wide = alpha_wide.reindex(columns=symbols)
    fwd_return_aligned = fwd_return_wide.reindex(index=dates, columns=symbols)
    cost_hurdle_aligned = cost_hurdle_wide.reindex(index=dates, columns=symbols)

    prev_weights: dict[str, dict[str, float]] = {a: {} for a in _ARM_FUNCS}
    steps_by_arm: dict[str, list[dict[str, Any]]] = {a: [] for a in _ARM_FUNCS}
    refits: list[dict[str, Any]] = []
    fallback_count = 0
    refit_ill_conditioned = False

    current_cov: np.ndarray | None = None
    current_corr_symbols: list[str] | None = None
    current_ic_shrunk: dict[str, float] | None = None
    last_refit_pos = -_REFIT_EVERY_BARS  # force a refit on the first eligible day

    for pos, rebal_date in enumerate(dates):
        if pos < _INITIAL_WARMUP_BARS:
            continue

        if pos - last_refit_pos >= _REFIT_EVERY_BARS:
            embargo_boundary = pos - _EMBARGO_BARS
            hist_returns = returns.loc[returns.index <= dates[embargo_boundary]].tail(
                _INITIAL_WARMUP_BARS
            )
            cov, _corr, cov_symbols = instrument_covariance(hist_returns)
            if len(cov_symbols) < 2:
                continue

            ic_raw_list = []
            n_eff_list = []
            for sym in cov_symbols:
                z_hist = standardize_scores(
                    alpha_wide[sym]
                    .loc[alpha_wide.index <= dates[embargo_boundary]]
                    .tail(_INITIAL_WARMUP_BARS)
                )
                fwd_hist = (
                    fwd_return_wide[sym]
                    .loc[fwd_return_wide.index <= dates[embargo_boundary]]
                    .tail(_INITIAL_WARMUP_BARS)
                )
                paired = pd.concat([z_hist, fwd_hist], axis=1, keys=["z", "fwd"]).dropna()
                if len(paired) >= _CORR_MIN_PERIODS:
                    ic_raw, _p = spearmanr(paired["z"], paired["fwd"])
                    ic_raw = 0.0 if not np.isfinite(ic_raw) else float(ic_raw)
                else:
                    ic_raw = 0.0
                ic_raw_list.append(ic_raw)
                n_eff_list.append(float(len(paired)))

            ic_shrunk_arr = shrink_instrument_ic(
                np.array(ic_raw_list), np.array(n_eff_list), _IC_SHRINKAGE_K
            )
            ic_shrunk_vals = dict(zip(cov_symbols, ic_shrunk_arr.tolist(), strict=True))

            current_cov, current_corr_symbols, current_ic_shrunk = cov, cov_symbols, ic_shrunk_vals
            last_refit_pos = pos

            # Condition number depends only on cov_matrix (mean_variance_weights' own gate),
            # so it -- and therefore whether the mean-variance arm will fall back -- is fixed
            # for this entire refit period. Determine and log it ONCE here, not once per
            # rebalance day inside the arm loop below (CLAUDE.md: never log per-row inside a
            # loop over a run; accumulate/report once instead).
            refit_cond_ok, refit_cond = check_condition_number(cov, _MV_CONDITION_MAX)
            refit_ill_conditioned = not refit_cond_ok
            if refit_ill_conditioned:
                _logger.warning(
                    "portfolio_covariance_weighting_diagnostic.refit_ill_conditioned",
                    refit_date=str(rebal_date.date()),
                    condition_number=refit_cond,
                )
            refits.append(
                {
                    "refit_date": str(rebal_date.date()),
                    "symbols": cov_symbols,
                    "ic_shrunk": ic_shrunk_arr.tolist(),
                    "condition_number": refit_cond,
                    "ill_conditioned": refit_ill_conditioned,
                }
            )

        if current_cov is None or current_corr_symbols is None:
            continue

        active_symbols = current_corr_symbols
        sigma = np.sqrt(np.maximum(np.diag(current_cov), 1e-12))
        z_today = np.array(
            [
                (
                    standardize_scores(
                        alpha_wide[sym]
                        .loc[alpha_wide.index <= rebal_date]
                        .tail(_INITIAL_WARMUP_BARS)
                    ).iloc[-1]
                    if rebal_date in alpha_wide.index and pd.notna(alpha_wide.loc[rebal_date, sym])
                    else 0.0
                )
                for sym in active_symbols
            ]
        )
        ic_shrunk_today = np.array([current_ic_shrunk[sym] for sym in active_symbols])
        mu = compute_mu(ic_shrunk_today, sigma, z_today)

        realized = fwd_return_aligned.loc[rebal_date, active_symbols].fillna(0.0).to_numpy()
        # Full-row cost_hurdle lookup (covers every symbol in `symbols`, not just today's
        # active_symbols) -- needed below to price the unwind cost of a symbol that dropped out
        # of active_symbols at the most recent refit (see prev_dict handling).
        cost_hurdle_row = cost_hurdle_aligned.loc[rebal_date].fillna(0.0)
        regime = regime_labels.get(rebal_date)

        for arm in _ARM_FUNCS:
            if arm == "equal_weight":
                w = equal_weight_arm(len(active_symbols))
            elif arm == "ic_proportional":
                w = ic_proportional_arm(mu)
            elif arm == "vol_normalized":
                w = vol_normalized_arm(mu, sigma)
            else:
                w, method, _cond = mean_variance_arm(current_cov, mu, _MV_CONDITION_MAX)
                if method == "mean_variance_ridge_fallback":
                    fallback_count += 1

            # active_symbols can change composition between refits (instrument_covariance's
            # own trailing-coverage filter is point-in-time, per the spec, so this is expected
            # behavior, not an edge case). Track prev weights by SYMBOL, not position -- a
            # positional array would silently misalign turnover/cost (or crash on a symbol-
            # count change) the moment the active set differs from the previous refit's.
            w_dict = dict(zip(active_symbols, w.tolist(), strict=True))
            prev_dict = prev_weights[arm]
            union_symbols = sorted(set(w_dict) | set(prev_dict))
            per_symbol_turnover = {
                sym: abs(w_dict.get(sym, 0.0) - prev_dict.get(sym, 0.0)) for sym in union_symbols
            }
            turnover = float(sum(per_symbol_turnover.values()))
            # Cost model: each instrument's own cost_hurdle applied to the size of its OWN
            # rebalance trade (spec's Output section: "using alpha_events' existing cost_hurdle
            # as the per-instrument cost proxy"), summed to one scalar cost for the step. Covers
            # entries (0 -> w), exits (prev -> 0, symbol no longer in active_symbols), and
            # ordinary rebalances alike, since union_symbols spans both.
            cost = float(
                sum(per_symbol_turnover[sym] * cost_hurdle_row[sym] for sym in union_symbols)
            )
            prev_weights[arm] = w_dict

            exposure = portfolio_exposure_stats(w)
            gross_return = float(np.dot(w, realized))
            steps_by_arm[arm].append(
                {
                    "date": str(rebal_date.date()),
                    "regime": regime,
                    "weights": w_dict,
                    "turnover": turnover,
                    "cost": cost,
                    "realized_return": gross_return,
                    "net_realized_return": gross_return - cost,
                    **exposure,
                }
            )

    arms_report: dict[str, Any] = {}
    for arm in _ARM_FUNCS:
        steps = steps_by_arm[arm]
        arms_report[arm] = {
            "rebalance_steps": steps,
            "aggregate": _aggregate_arm(steps),
        }

    return {
        "arms": arms_report,
        "refits": refits,
        "mean_variance_fallback_count": fallback_count,
        "n_rebalance_steps": len(steps_by_arm["equal_weight"]),
    }


_AGGREGATE_MEAN_FIELDS = (
    ("mean_realized_return", "realized_return"),
    ("mean_net_realized_return", "net_realized_return"),
    ("mean_cost", "cost"),
    ("mean_turnover", "turnover"),
    ("mean_effective_n", "effective_n"),
)


def _aggregate_arm(steps: list[dict[str, Any]]) -> dict[str, Any]:
    """Unconditional + causal-regime-split aggregate stats for one arm's rebalance history."""

    def _summary(subset: list[dict[str, Any]]) -> dict[str, float]:
        result: dict[str, float] = {"n": len(subset)}
        for out_key, step_key in _AGGREGATE_MEAN_FIELDS:
            result[out_key] = float(np.mean([s[step_key] for s in subset])) if subset else 0.0
        return result

    out = {"unconditional": _summary(steps)}
    for label in ("bull", "bear"):
        out[label] = _summary([s for s in steps if s["regime"] == label])
    return out


# ---------------------------------------------------------------------------
# I/O shell -- DB fetch, coverage filter, CLI, main().
# ---------------------------------------------------------------------------


def _batched(items: list[str], size: int) -> list[list[str]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


def _fetch_daily_closes(
    conn: psycopg.Connection, symbols: list[str], start: str, end_exclusive: str
) -> pd.DataFrame:
    """(date x symbol) wide frame of daily closes from market_data_ohlcv_tradeable -- never the
    raw market_data_ohlcv table (~82% synthetic-fill/flat-carry-forward placeholder bars
    intraday). Matches universe_expansion_correlation_structure_check.py's _fetch_daily_closes."""
    frames: list[pd.DataFrame] = []
    for batch in _batched(symbols, _SYMBOL_BATCH_SIZE):
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT timestamp, symbol, close
                FROM market_data_ohlcv_tradeable
                WHERE timeframe = %(timeframe)s AND symbol = ANY(%(symbols)s)
                  AND timestamp >= %(start)s AND timestamp < %(end_exclusive)s
                """,
                {
                    "timeframe": _TIMEFRAME,
                    "symbols": batch,
                    "start": start,
                    "end_exclusive": end_exclusive,
                },
            )
            rows = cur.fetchall()
        if rows:
            frames.append(pd.DataFrame(rows, columns=["timestamp", "symbol", "close"]))
    if not frames:
        return pd.DataFrame()
    long = pd.concat(frames, ignore_index=True)
    long["timestamp"] = pd.to_datetime(long["timestamp"], utc=True)
    return long.pivot(index="timestamp", columns="symbol", values="close").sort_index()


def _fetch_alpha_scores_and_cost_hurdle(
    conn: psycopg.Connection,
    symbols: list[str],
    tf: str,
    weight_version: str,
    start: str,
    end_exclusive: str,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(date x symbol) wide frames of alpha_events.alpha_score and .cost_hurdle -- fetched
    together in one query (identical WHERE clause, previously two separate round trips over
    the same rows) since both are read from the same table for the same cohort/window.

    alpha_score is already signed (positive=long, negative=short per alpha_publisher.py's own
    direction derivation), so no separate direction-sign combination is needed. cost_hurdle is
    the per-instrument cost proxy used by run_walk_forward's cost-adjusted net-return
    calculation (spec's Output section).
    """
    frames: list[pd.DataFrame] = []
    for batch in _batched(symbols, _SYMBOL_BATCH_SIZE):
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT bar_ts, symbol, alpha_score, cost_hurdle
                FROM alpha_events
                WHERE tf = %(tf)s AND weight_version = %(weight_version)s
                  AND symbol = ANY(%(symbols)s)
                  AND bar_ts >= %(start)s AND bar_ts < %(end_exclusive)s
                """,
                {
                    "tf": tf,
                    "weight_version": weight_version,
                    "symbols": batch,
                    "start": start,
                    "end_exclusive": end_exclusive,
                },
            )
            rows = cur.fetchall()
        if rows:
            frames.append(
                pd.DataFrame(rows, columns=["bar_ts", "symbol", "alpha_score", "cost_hurdle"])
            )
    if not frames:
        return pd.DataFrame(), pd.DataFrame()
    long = pd.concat(frames, ignore_index=True)
    long["bar_ts"] = pd.to_datetime(long["bar_ts"], utc=True)
    alpha_wide = long.pivot(index="bar_ts", columns="symbol", values="alpha_score").sort_index()
    cost_hurdle_wide = long.pivot(
        index="bar_ts", columns="symbol", values="cost_hurdle"
    ).sort_index()
    return alpha_wide, cost_hurdle_wide


def _fetch_forward_returns(
    conn: psycopg.Connection, symbols: list[str], tf: str, start: str, end_exclusive: str
) -> pd.DataFrame:
    """(date x symbol) wide frame of forward_returns.return_fast, filtered to
    return_type='executable_open_to_open' (CLAUDE.md Invariant 1) AND complete_fast AND NOT
    return_fast_suspect. return_fast (1-bar-ahead) matches this diagnostic's daily rebalance
    cadence -- the horizon that matches the rebalance cadence, per the design review's
    covariance-horizon-alignment finding."""
    frames: list[pd.DataFrame] = []
    for batch in _batched(symbols, _SYMBOL_BATCH_SIZE):
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT bar_ts, symbol, return_fast
                FROM forward_returns
                WHERE tf = %(tf)s AND symbol = ANY(%(symbols)s)
                  AND return_type = 'executable_open_to_open'
                  AND complete_fast AND NOT return_fast_suspect
                  AND bar_ts >= %(start)s AND bar_ts < %(end_exclusive)s
                """,
                {"tf": tf, "symbols": batch, "start": start, "end_exclusive": end_exclusive},
            )
            rows = cur.fetchall()
        if rows:
            frames.append(pd.DataFrame(rows, columns=["bar_ts", "symbol", "return_fast"]))
    if not frames:
        return pd.DataFrame()
    long = pd.concat(frames, ignore_index=True)
    long["bar_ts"] = pd.to_datetime(long["bar_ts"], utc=True)
    return long.pivot(index="bar_ts", columns="symbol", values="return_fast").sort_index()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Shadow-mode diagnostic: does cross-instrument covariance-aware portfolio weighting "
            "beat naive/IC-proportional/volatility-normalized baselines, walk-forward? Measurement "
            "tool only -- no --gate, no pass/fail exit code. Exit codes: 0=ran, 1=error."
        ),
    )
    parser.add_argument("--symbols", required=True, help="Comma-separated symbol list.")
    parser.add_argument("--tf", default=_TIMEFRAME)
    parser.add_argument(
        "--weight-version", required=True, help="alpha_events.weight_version to read."
    )
    parser.add_argument("--start", default="2018-01-01", help="Window start (inclusive).")
    parser.add_argument("--end", default="2026-09-02", help="Window end (inclusive).")
    parser.add_argument("--regime-factor-symbol", default="SPY")
    parser.add_argument("--json-out", type=Path, help="Write the full result structure as JSON.")
    args = parser.parse_args(argv)

    status = "success"
    try:
        symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]
        settings = Settings()
        conn = psycopg.connect(settings.database_url)
        conn.autocommit = True
        try:
            end_exclusive = (date.fromisoformat(args.end) + timedelta(days=1)).isoformat()

            close_wide = _fetch_daily_closes(conn, symbols, args.start, end_exclusive)
            if close_wide.empty:
                print(
                    "FAILED: no daily bars found for the requested symbols/window.", file=sys.stderr
                )
                status = "failure"
                return 1
            # No full-window coverage filter here -- deliberately. A symbol below some coverage
            # threshold over the ENTIRE --start/--end window (e.g. one with a later inception
            # date) would otherwise be permanently excluded before the walk-forward loop even
            # starts, reintroducing the survivorship bias the spec explicitly forbids ("never
            # restrict the whole run to instruments with complete history over the entire
            # period"). instrument_covariance()'s own point-in-time trailing-coverage filter
            # (run_walk_forward, per refit) is the only coverage gate this diagnostic applies --
            # it naturally admits an instrument once it has sufficient TRAILING history, not
            # before, and drops it again if trailing coverage later degrades. retained_symbols
            # here is just whichever requested symbols returned any price data at all (pandas'
            # pivot never creates a column for a symbol with zero rows).
            retained_symbols = sorted(close_wide.columns.tolist())
            _logger.info(
                "portfolio_covariance_weighting_diagnostic.symbols_with_price_data",
                n_population=len(symbols),
                n_with_data=len(retained_symbols),
                missing_symbols=sorted(set(symbols) - set(retained_symbols)),
            )
            close_filtered = close_wide

            alpha_wide, cost_hurdle_wide = _fetch_alpha_scores_and_cost_hurdle(
                conn, retained_symbols, args.tf, args.weight_version, args.start, end_exclusive
            )
            fwd_wide = _fetch_forward_returns(
                conn, retained_symbols, args.tf, args.start, end_exclusive
            )
            spy_close_wide = _fetch_daily_closes(
                conn, [args.regime_factor_symbol], args.start, end_exclusive
            )
            if spy_close_wide.empty:
                print(
                    f"FAILED: no bars for regime-factor symbol {args.regime_factor_symbol}.",
                    file=sys.stderr,
                )
                status = "failure"
                return 1
            spy_close = spy_close_wide[args.regime_factor_symbol]

            report = run_walk_forward(
                close_filtered, alpha_wide, fwd_wide, cost_hurdle_wide, spy_close
            )
            report["cohort"] = {
                "n_population": len(symbols),
                "n_with_price_data": len(retained_symbols),
                "missing_symbols": sorted(set(symbols) - set(retained_symbols)),
                "retained_symbols": retained_symbols,
            }
            report["window"] = {"start": args.start, "end": args.end}
            report["caveats"] = [
                "Universe membership conditioned on Gate B passing over this same measurement "
                "period is itself a selection effect -- these numbers are conditional on the "
                "Gate-B-selected universe, not evidence this method would discover these "
                "instruments from an unfiltered pool.",
                "IC is measured as Spearman rank correlation, used as a linear mu-scaling "
                "coefficient -- a heuristic, not an exact Pearson-slope calibration.",
                "Sample size at this instrument count is likely powered for a directional read "
                "only, not a p<0.05 verdict.",
            ]

            print(
                f"Rebalance steps: {report['n_rebalance_steps']}, "
                f"mean_variance ridge-fallback count: {report['mean_variance_fallback_count']}"
            )
            for arm, arm_report in report["arms"].items():
                agg = arm_report["aggregate"]["unconditional"]
                print(
                    f"  {arm}: n={agg['n']} mean_realized_return={agg['mean_realized_return']:.6f} "
                    f"mean_net_realized_return={agg['mean_net_realized_return']:.6f} "
                    f"mean_turnover={agg['mean_turnover']:.4f} mean_effective_n={agg['mean_effective_n']:.2f}"
                )

            if args.json_out:
                args.json_out.write_text(json.dumps(report, indent=2, default=str))

            return 0
        finally:
            conn.close()
    except Exception as error:
        status = "failure"
        _logger.error("portfolio_covariance_weighting_diagnostic.failed", error=str(error))
        print(f"FAILED: {error}", file=sys.stderr)
        return 1
    finally:
        JOB_COMPLETED_TOTAL.add(1, {"job": _JOB_NAME, "status": status})
        flush_and_shutdown_metrics()


if __name__ == "__main__":
    from src.observability.otel import OTelInitError, init_otel_providers

    try:
        init_otel_providers(_JOB_NAME)
    except OTelInitError as error:
        print(f"[warn] OTel init failed -- metrics disabled: {error}")
    sys.exit(main())
