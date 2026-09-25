"""S5: the arms on the real alpha panel and on every admissible whole-panel shift.

Phase 179 pre-registration section 7, generalized to any (universe, tf). The covariance plan
depends only on returns, so it is built once and shared by the real run and every shift;
everything that depends on alpha (calibration, standardization, weights) reruns per shift
inside the construction. The construction is a parameter, (alpha, fwd_ret, plan) -> {arm:
per-row returns}: phase 179's calibrated arms by default, a signal source's pinned construction
otherwise (signals.SignalSource).

Rows and sessions. A 1d panel has one row per session. An intraday panel is a regular grid of
`bars_per_session` rows per session (panel.Panel), so a shift of k whole sessions moves every
row by k * bars_per_session and each bar keeps its time of day: the null breaks the signal's
alignment with future returns, not the intraday volatility pattern or the overnight gap
(architecture doc section 3.5). The config's lengths are in sessions and are converted to rows
here (rows_config); `memory` is in rows and rounds up to whole sessions. Rows that are not
bars (`valid` False: a slot no symbol traded, as on a half day) never enter a statistic.

With bars_per_session = 1, every array operation is the one phase 179 and phase 181 ran.
"""

from __future__ import annotations

import dataclasses
import functools
import warnings
from collections.abc import Callable
from concurrent.futures import Executor
from typing import Protocol

import numpy as np
from scipy.stats import kurtosis, skew

from src.intelligence.research.portfolio import (
    DAILY_EMBARGO,
    CovariancePlan,
    PortfolioConfig,
    arm_returns,
    arm_weights,
    plan_covariance,
)
from src.intelligence.statistics.panel_null import (
    admissible_shifts,
    shift_panel,
    westfall_young_adjusted_p,
)

SESSIONS_PER_YEAR = 252

Construction = Callable[[np.ndarray, np.ndarray, CovariancePlan], dict[str, np.ndarray]]
# workers -> an executor whose workers are compute-only; callers in scripts/ and services/ pass
# functools.partial(make_worker_pool, blas_threads_per_worker=...) (todo 216).
PoolFactory = Callable[[int], Executor]


class EvaluationConfig(PortfolioConfig, Protocol):
    """The evaluator's knobs, lengths in sessions (phase 179's HarnessConfig satisfies it).
    Must be a dataclass: rows_config rescales it with dataclasses.replace. Every field is
    classified below as converted to rows or not; a test fails on an unclassified one."""

    trading_start: str
    sub_periods: tuple[tuple[str, str], ...]
    min_shift: int
    bootstrap_mean_block: int
    bootstrap_reps: int
    seed: int


# Session lengths the arms and the bootstrap count in rows.
ROW_SCALED_FIELDS = ("warmup_sessions", "calibration_refit_sessions", "bootstrap_mean_block")
# Dates, fractions, counts, and min_shift (shifts are drawn in sessions, then scaled).
UNSCALED_FIELDS = (
    "trading_start",
    "sub_periods",
    "min_shift",
    "coverage_fraction",
    "ridge_epsilon_fraction",
    "bootstrap_reps",
    "seed",
)


@dataclasses.dataclass(frozen=True)
class EvaluationResult:
    arms: tuple[str, ...]
    sharpe_obs: np.ndarray  # [J]
    sharpe_null: np.ndarray  # [K, J]
    shifts: np.ndarray  # [K], in rows
    adjusted_p: np.ndarray  # [J]
    excess: np.ndarray  # [J], observed minus null-median Sharpe
    sub_period_excess: np.ndarray  # [J, n_sub_periods], mean per-row excess return
    excess_ci: np.ndarray  # [J, 2], stationary-bootstrap 95% CI of the excess Sharpe
    # Section 11 shape measures per arm, {"observed": {...}, "null_median": {...}}. Reported
    # for sizing; no decision rule reads them.
    diagnostics: dict = dataclasses.field(default_factory=dict)
    # observed_daily / null_median_daily: [J, n] per-row returns, or [J, n_sessions]
    # per-session sums under session scoring. observed_weights: {arm: [n, m]}, set for the
    # calibrated arms only.
    observed_daily: np.ndarray | None = None
    null_median_daily: np.ndarray | None = None
    observed_weights: dict = dataclasses.field(default_factory=dict)
    # [J] standard deviation of the stationary-bootstrap Sharpe draws behind excess_ci (the
    # evidence record's standard error, evidence framework section 5).
    excess_se: np.ndarray | None = None


class EvaluatorMisuse(TypeError):
    """A caller broke evaluate()'s contract. Deliberately not a ValueError: safe_evaluate turns
    ValueError (a degenerate null, an undefined Sharpe) into FIDELITY BROKEN, and a programming
    error must crash instead of becoming a verdict record."""


def _days(dates: np.ndarray) -> np.ndarray:
    """Calendar day of each row, so a date bound covers every intraday bar on that day."""
    return dates.astype("datetime64[D]")


def sub_period_masks(dates: np.ndarray, periods: tuple[tuple[str, str], ...]) -> list[np.ndarray]:
    days = _days(dates)
    return [(days >= np.datetime64(a)) & (days <= np.datetime64(b)) for a, b in periods]


def annualized_sharpe(
    r: np.ndarray, mask: np.ndarray, periods_per_year: int = SESSIONS_PER_YEAR
) -> float:
    x = r[mask & np.isfinite(r)]
    if len(x) < 2:
        raise ValueError(f"Sharpe needs at least 2 finite returns, got {len(x)}")
    sd = float(np.std(x, ddof=1))
    if sd == 0.0:
        raise ValueError("Sharpe undefined: zero return variance")
    return float(np.mean(x)) / sd * np.sqrt(periods_per_year)


def shape_diagnostics(r: np.ndarray, periods_per_year: int = SESSIONS_PER_YEAR) -> dict[str, float]:
    """Return-shape measures over the finite per-row returns: annualized Sortino (downside
    deviation over all rows, NaN with no losing row), max drawdown of the cumulative log-wealth
    path from 0, skew, excess kurtosis, and the share of positive rows."""
    x = r[np.isfinite(r)]
    downside = float(np.sqrt(np.mean(np.minimum(x, 0.0) ** 2)))
    wealth = np.concatenate([[0.0], np.cumsum(x)])
    return {
        "sortino": (
            float(np.mean(x)) / downside * np.sqrt(periods_per_year)
            if downside > 0
            else float("nan")
        ),
        "max_drawdown": float(np.max(np.maximum.accumulate(wealth) - wealth)),
        "skew": float(skew(x)),
        "excess_kurtosis": float(kurtosis(x)),
        "hit_rate": float(np.mean(x > 0)),
    }


def aggregate_sessions(
    r: np.ndarray, trade: np.ndarray, bars_per_session: int
) -> tuple[np.ndarray, np.ndarray]:
    """Per-session sums of the finite rows in `trade` (NaN for a session with none), and
    session_trade: True where any row of the session is in `trade`. R2's scoring unit (family 1
    prereg section 4): a book trading several slots a day is scored on its daily P&L."""
    in_trade = trade.reshape(-1, bars_per_session)
    x = np.where(in_trade, r.reshape(-1, bars_per_session), np.nan)
    has = np.isfinite(x).any(axis=1)
    sums = np.where(has, np.nansum(np.where(np.isfinite(x), x, 0.0), axis=1), np.nan)
    return sums, in_trade.any(axis=1)


def scored_sharpe(
    r: np.ndarray,
    trade: np.ndarray,
    *,
    periods_per_year: int,
    bars_per_session: int,
    session_scoring: bool,
) -> float:
    """The annualized Sharpe evaluate() scores: per row, or per session with 252 periods."""
    if not session_scoring:
        return annualized_sharpe(r, trade, periods_per_year)
    return annualized_sharpe(*aggregate_sessions(r, trade, bars_per_session), SESSIONS_PER_YEAR)


def trade_mask(dates: np.ndarray, cfg: EvaluationConfig) -> np.ndarray:
    """Rows in the scored span: trading_start through the last sub-period's end. The panel's
    last rows have no forward return and must not enter the Sharpe as zero-return rows."""
    days = _days(dates)
    return (days >= np.datetime64(cfg.trading_start)) & (
        days <= np.datetime64(cfg.sub_periods[-1][1])
    )


def rows_config(cfg: EvaluationConfig, bars_per_session: int) -> EvaluationConfig:
    """cfg with its session lengths expressed in rows; cfg itself on a 1d panel. min_shift stays
    in sessions: shifts are drawn in sessions and scaled (session_shifts)."""
    if bars_per_session == 1:
        return cfg
    return dataclasses.replace(
        cfg, **{f: getattr(cfg, f) * bars_per_session for f in ROW_SCALED_FIELDS}
    )


def session_shifts(n: int, bars_per_session: int, min_shift: int, memory: int) -> np.ndarray:
    """Admissible shifts in rows, each a whole number of sessions. `min_shift` is in sessions,
    `memory` in rows (rounded up to whole sessions)."""
    if n % bars_per_session:
        raise EvaluatorMisuse(f"{n} rows is not a whole number of {bars_per_session}-bar sessions")
    memory_sessions = -(-memory // bars_per_session)
    return admissible_shifts(n // bars_per_session, min_shift, memory_sessions) * bars_per_session


def _run_shifts(
    alpha: np.ndarray,
    fwd_ret: np.ndarray,
    plan: CovariancePlan,
    construction: Construction,
    arms: tuple[str, ...],
    shifts: np.ndarray,
    trade: np.ndarray,
    periods_per_year: int,
    bars_per_session: int = 1,
    session_scoring: bool = False,
) -> tuple[np.ndarray, np.ndarray]:
    """Compute-only worker: per shift, each arm's Sharpe and its per-row returns (float32), or
    its per-session sums under session scoring."""
    width = alpha.shape[0] // bars_per_session if session_scoring else alpha.shape[0]
    sharpe = np.empty((len(shifts), len(arms)))
    daily = np.empty((len(shifts), len(arms), width), dtype=np.float32)
    for i, shift in enumerate(shifts):
        out = construction(shift_panel(alpha, int(shift)), fwd_ret, plan)
        for j, arm in enumerate(arms):
            sharpe[i, j] = scored_sharpe(
                out[arm],
                trade,
                periods_per_year=periods_per_year,
                bars_per_session=bars_per_session,
                session_scoring=session_scoring,
            )
            daily[i, j] = (
                aggregate_sessions(out[arm], trade, bars_per_session)[0]
                if session_scoring
                else out[arm]
            )
    return sharpe, daily


def evaluate(
    alpha: np.ndarray,
    fwd_ret: np.ndarray,
    closes: np.ndarray,
    dates: np.ndarray,
    cfg: EvaluationConfig,
    *,
    mv_condition_max: float,
    ic_shrinkage_k: float,
    shifts: np.ndarray | None = None,
    workers: int = 1,
    construction: Construction | None = None,
    memory: int = 0,
    bars_per_session: int = 1,
    valid: np.ndarray | None = None,
    embargo: int = DAILY_EMBARGO,
    pool_factory: PoolFactory | None = None,
    session_scoring: bool = False,
) -> EvaluationResult:
    """`memory` (rows) feeds the shift set when `shifts` is not given; a picklable
    `construction` (module-level function or functools.partial) replaces the calibrated arms.
    `embargo` is the forward return's span in rows. `workers` > 1 needs `pool_factory`.
    `session_scoring` (R2) sums each construction's per-row P&L per session before the Sharpe,
    for the observed book and every shift alike; the bootstrap, sub-period and shape readouts
    then run on the per-session series."""
    n = alpha.shape[0]
    rcfg = rows_config(cfg, bars_per_session)
    periods_per_year = SESSIONS_PER_YEAR * bars_per_session
    trade = trade_mask(dates, cfg)
    if valid is not None:
        trade = trade & valid
    plan = plan_covariance(closes, rcfg, mv_condition_max, embargo)
    calibrated = construction is None
    if calibrated:
        construction = functools.partial(arm_returns, cfg=rcfg, ic_shrinkage_k=ic_shrinkage_k)
    obs = construction(alpha, fwd_ret, plan)
    arms = tuple(obs)
    obs_daily = np.stack([obs[arm] for arm in arms])
    score = functools.partial(
        scored_sharpe,
        periods_per_year=periods_per_year,
        bars_per_session=bars_per_session,
        session_scoring=session_scoring,
    )
    sharpe_obs = np.array([score(r, trade) for r in obs_daily])

    if shifts is None:
        shifts = session_shifts(n, bars_per_session, cfg.min_shift, memory)
    shifts = np.asarray(shifts)
    if bars_per_session > 1 and (shifts % bars_per_session).any():
        raise EvaluatorMisuse(
            "intraday shifts must be whole sessions (multiples of bars_per_session)"
        )
    args = (alpha, fwd_ret, plan, construction, arms)
    tail = (trade, periods_per_year, bars_per_session, session_scoring)
    if workers > 1:
        if pool_factory is None:
            raise EvaluatorMisuse("workers > 1 needs a pool_factory")
        chunks = np.array_split(shifts, workers)
        with pool_factory(workers) as pool:
            parts = list(pool.map(_run_shifts, *zip(*[(*args, c, *tail) for c in chunks])))
        sharpe_null = np.concatenate([p[0] for p in parts])
        null_daily = np.concatenate([p[1] for p in parts])
    else:
        sharpe_null, null_daily = _run_shifts(*args, shifts, *tail)

    if session_scoring:
        obs_daily = np.stack([aggregate_sessions(r, trade, bars_per_session)[0] for r in obs_daily])
    scored, readout_dates, readout_ppy, block = _readout_units(
        trade, dates, cfg, rcfg, bars_per_session, periods_per_year, session_scoring
    )
    # nanmedian: the circular shift rolls the pre-scoring NaN alpha into every scored session
    # for some shift, and a plain median would then blank nearly every session's null.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)  # a session no shift traded stays NaN
        null_median_daily = np.nanmedian(null_daily, axis=0)  # [J, n] (or [J, n_sessions])
    excess_daily = obs_daily - null_median_daily
    sub_masks = [m & scored for m in sub_period_masks(readout_dates, cfg.sub_periods)]
    draws = [
        _bootstrap_sharpe_draws(row[scored], block, cfg.bootstrap_reps, cfg.seed, readout_ppy)
        for row in excess_daily
    ]
    return EvaluationResult(
        observed_daily=obs_daily,
        null_median_daily=null_median_daily,
        observed_weights=(
            arm_weights(alpha, fwd_ret, plan, rcfg, ic_shrinkage_k) if calibrated else {}
        ),
        arms=arms,
        sharpe_obs=sharpe_obs,
        sharpe_null=sharpe_null,
        shifts=shifts,
        adjusted_p=westfall_young_adjusted_p(sharpe_obs, sharpe_null),
        excess=sharpe_obs - np.median(sharpe_null, axis=0),
        sub_period_excess=np.array(
            [[np.nanmean(row[m]) for m in sub_masks] for row in excess_daily]
        ),
        excess_ci=np.array([np.percentile(d, [2.5, 97.5]) for d in draws]),
        excess_se=np.array([np.std(d, ddof=1) for d in draws]),
        diagnostics={
            arm: {
                "observed": shape_diagnostics(obs_daily[j][scored], readout_ppy),
                "null_median": shape_diagnostics(null_median_daily[j][scored], readout_ppy),
            }
            for j, arm in enumerate(arms)
        },
    )


def _readout_units(
    trade: np.ndarray,
    dates: np.ndarray,
    cfg: EvaluationConfig,
    rcfg: EvaluationConfig,
    bars_per_session: int,
    periods_per_year: int,
    session_scoring: bool,
) -> tuple[np.ndarray, np.ndarray, int, int]:
    """The readouts' unit in one place (mask, dates, periods per year, bootstrap block), so the
    bootstrap, sub-periods and shape diagnostics cannot disagree: rows, or sessions under R2
    (block in sessions, 252 periods, each session dated by its first row)."""
    if not session_scoring:
        return trade, dates, periods_per_year, rcfg.bootstrap_mean_block
    session_trade = trade.reshape(-1, bars_per_session).any(axis=1)
    return session_trade, dates[::bars_per_session], SESSIONS_PER_YEAR, cfg.bootstrap_mean_block


def _bootstrap_sharpe_draws(
    x: np.ndarray,
    mean_block: int,
    reps: int,
    seed: int,
    periods_per_year: int = SESSIONS_PER_YEAR,
) -> np.ndarray:
    """The annualized Sharpe of each Politis-Romano stationary-bootstrap resample (geometric
    blocks, circular) of the finite values. The 95% interval and standard error are read off
    these draws; both are reported only, the permutation p decides."""
    x = x[np.isfinite(x)]
    n = len(x)
    rng = np.random.default_rng(seed)
    idx = np.empty((reps, n), dtype=np.int64)
    idx[:, 0] = rng.integers(0, n, reps)
    restart = rng.random((reps, n)) < 1.0 / mean_block
    fresh = rng.integers(0, n, (reps, n))
    for t in range(1, n):
        idx[:, t] = np.where(restart[:, t], fresh[:, t], (idx[:, t - 1] + 1) % n)
    sample = x[idx]
    sd = sample.std(axis=1, ddof=1)
    sharpe = np.where(sd > 0, sample.mean(axis=1) / np.where(sd > 0, sd, 1.0), 0.0)
    return sharpe * np.sqrt(periods_per_year)
