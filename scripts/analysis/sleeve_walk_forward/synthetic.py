"""Synthetic panels and the V2 (null calibration) / V3 (power) runs of pre-registration
section 10.

Returns follow an equicorrelated Gaussian with a per-asset drift; alpha is an AR(1) noise
process plus a planted multiple of the standardized forward return. V2 keeps the alpha
persistent and the assets drifting on purpose: a null that stays calibrated there is the one
section 1 argues for (drift earns nothing systematic in either the real or shifted runs).
Each seed tests on a random subsample of admissible shifts, a valid Monte Carlo permutation
test; the real run uses them all.
"""

from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor
from typing import Any

import numpy as np

from scripts.analysis.sleeve_walk_forward.config import DEFAULT_CONFIG, HarnessConfig
from scripts.analysis.sleeve_walk_forward.evaluate import evaluate
from scripts.analysis.sleeve_walk_forward.portfolio import ARMS
from scripts.analysis.sleeve_walk_forward.verdict import decide, safe_evaluate
from src.intelligence.statistics.panel_null import admissible_shifts

_DAILY_VOL = 0.01
_START = np.datetime64("2011-01-03")
# Pinned synthetic-world constants for V2/V3 (APR-exempt, same status as config.py).
_MV_CONDITION_MAX = 1000.0
_IC_SHRINKAGE_K = 100.0


def synthetic_panel(
    seed: int,
    *,
    n: int = 3750,
    m: int = 13,
    signal_ic: float = 0.0,
    alpha_ar1: float = 0.98,
    drift_sd: float = 0.0003,
    corr: float = 0.3,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """(alpha, fwd_ret, closes, dates), all [n, m] except dates [n] (business days).
    fwd_ret[d] = r[d+2] = ln(close[d+2] / close[d+1]); the last two rows are NaN."""
    rng = np.random.default_rng(seed)
    chol = np.linalg.cholesky(np.full((m, m), corr) + (1 - corr) * np.eye(m))
    drift = rng.normal(0.0, drift_sd, m)
    r = drift + _DAILY_VOL * rng.standard_normal((n, m)) @ chol.T
    closes = 100.0 * np.exp(np.cumsum(r, axis=0))
    fwd = np.full((n, m), np.nan)
    fwd[:-2] = r[2:]
    innovations = rng.standard_normal((n, m)) * np.sqrt(1 - alpha_ar1**2)
    noise = np.empty((n, m))
    noise[0] = rng.standard_normal(m)
    for t in range(1, n):
        noise[t] = alpha_ar1 * noise[t - 1] + innovations[t]
    alpha = noise + signal_ic * np.nan_to_num((fwd - drift) / _DAILY_VOL)
    dates = np.busday_offset(_START, np.arange(n), roll="forward")
    return alpha, fwd, closes, dates


def _one_seed(
    seed: int, n_shifts: int, cfg: HarnessConfig, signal_ic: float, panel_kw: dict
) -> tuple[str | None, float]:
    alpha, fwd, closes, dates = synthetic_panel(seed, signal_ic=signal_ic, **panel_kw)
    shifts = np.sort(
        np.random.default_rng(seed).choice(
            admissible_shifts(len(dates), cfg.min_shift), n_shifts, replace=False
        )
    )
    res, error = safe_evaluate(
        evaluate,
        alpha,
        fwd,
        closes,
        dates,
        cfg,
        mv_condition_max=_MV_CONDITION_MAX,
        ic_shrinkage_k=_IC_SHRINKAGE_K,
        shifts=shifts,
    )
    if error is not None:
        return None, float("nan")
    return decide(res, cfg, fidelity_ok=True)["sleeve_verdict"], float(
        res.excess[ARMS.index("vol_normalized")]
    )


def _run_seeds(
    seeds: range, n_shifts: int, workers: int, cfg: HarnessConfig, signal_ic: float, panel_kw: dict
) -> list[tuple[str | None, float]]:
    args = [(s, n_shifts, cfg, signal_ic, panel_kw) for s in seeds]
    if workers <= 1:
        return [_one_seed(*a) for a in args]
    with ProcessPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(_one_seed, *zip(*args)))


def run_v2(
    seeds: range,
    n_shifts: int,
    workers: int,
    cfg: HarnessConfig = DEFAULT_CONFIG,
    signal_ic: float = 0.0,
    **panel_kw: Any,
) -> dict[str, Any]:
    """PASS rate over seeds with a binomial 95% band. A degenerate seed (FIDELITY BROKEN) is
    counted separately, never as a FAIL."""
    outcomes = _run_seeds(seeds, n_shifts, workers, cfg, signal_ic, panel_kw)
    tokens = [t for t, _ in outcomes if t is not None]
    rate = sum(t == "PASS" for t in tokens) / len(tokens) if tokens else float("nan")
    half = 1.96 * np.sqrt(rate * (1 - rate) / len(tokens)) if tokens else float("nan")
    return {
        "signal_ic": signal_ic,
        "n_seeds": len(outcomes),
        "n_degenerate": len(outcomes) - len(tokens),
        "pass_rate": rate,
        "pass_rate_ci": [rate - half, rate + half],
        "mean_excess_sharpe_vol_normalized": float(np.nanmean([e for _, e in outcomes])),
    }


def calibrate_signal_ic(
    target_excess: float,
    *,
    seeds: range,
    n_shifts: int,
    workers: int,
    cfg: HarnessConfig = DEFAULT_CONFIG,
    iterations: int = 7,
    **panel_kw: Any,
) -> float:
    """Bisection on signal_ic so the mean vol_normalized excess Sharpe over `seeds` hits the
    target (V3's planted excess IR)."""
    lo, hi = 0.0, 0.3
    for _ in range(iterations):
        mid = (lo + hi) / 2
        got = np.nanmean([e for _, e in _run_seeds(seeds, n_shifts, workers, cfg, mid, panel_kw)])
        lo, hi = (mid, hi) if got < target_excess else (lo, mid)
    return (lo + hi) / 2


def run_v3(
    target_irs: tuple[float, ...],
    seeds: range,
    n_shifts: int,
    workers: int,
    cfg: HarnessConfig = DEFAULT_CONFIG,
    calibration_seeds: range = range(10_000, 10_020),
    **panel_kw: Any,
) -> dict[float, dict[str, Any]]:
    out = {}
    for target in target_irs:
        ic = calibrate_signal_ic(
            target, seeds=calibration_seeds, n_shifts=n_shifts, workers=workers, cfg=cfg, **panel_kw
        )
        out[target] = run_v2(seeds, n_shifts, workers, cfg, signal_ic=ic, **panel_kw)
    return out
