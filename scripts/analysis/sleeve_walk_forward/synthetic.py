"""Synthetic panels and the V2 (null calibration) / V3 (power) runs of pre-registration
section 10.

Returns follow an equicorrelated Gaussian with a per-asset drift. With alpha_kind="ar1", alpha
is an AR(1) noise process plus a planted multiple of the standardized forward return. With a
signal source's name (signals.SIGNALS), alpha is that signal computed from the synthetic closes
exactly as the real run computes it, and the planted edge is a latent persistent drift in the
returns themselves, the process the signal is meant to detect. V2 keeps the alpha
persistent and the assets drifting on purpose: a null that stays calibrated there is the one
section 1 argues for (drift earns nothing systematic in either the real or shifted runs).
Each seed tests on a random subsample of admissible shifts, a valid Monte Carlo permutation
test; the real run uses them all.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from scripts.analysis.sleeve_walk_forward.config import DEFAULT_CONFIG, HarnessConfig
from scripts.analysis.sleeve_walk_forward.evaluate import evaluate
from scripts.analysis.sleeve_walk_forward.score import FWD_SPAN_SESSIONS
from scripts.analysis.sleeve_walk_forward.signals import SIGNALS
from scripts.analysis.sleeve_walk_forward.verdict import decide, safe_evaluate
from services._batch_utils import make_worker_pool
from src.intelligence.statistics.panel_null import admissible_shifts

_DAILY_VOL = 0.01
_START = np.datetime64("2011-01-03")
# Pinned synthetic-world constants for V2/V3 (APR-exempt, same status as config.py).
_MV_CONDITION_MAX = 1000.0
_IC_SHRINKAGE_K = 100.0
# Per-session persistence of the planted latent drift for signal-source panels: a half-life of
# about 6 months, the horizon at which TSMOM's published effect lives.
_LATENT_DRIFT_AR1 = 0.995


def synthetic_panel(
    seed: int,
    *,
    n: int = 3750,
    m: int = 13,
    signal_ic: float = 0.0,
    alpha_ar1: float = 0.98,
    drift_sd: float = 0.0003,
    corr: float = 0.3,
    alpha_kind: str = "ar1",
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """(alpha, fwd_ret, closes, dates), all [n, m] except dates [n] (business days).
    fwd_ret[d] = r[d+2] = ln(close[d+2] / close[d+1]); the last two rows are NaN.

    For a signal source, `signal_ic` is the stationary sd of the latent drift in units of daily
    vol, and the source's lookback is simulated before the panel and dropped, so the signal has
    a full lookback from row 0 as it does on the real snapshot."""
    rng = np.random.default_rng(seed)
    chol = np.linalg.cholesky(np.full((m, m), corr) + (1 - corr) * np.eye(m))
    drift = rng.normal(0.0, drift_sd, m)
    source = None if alpha_kind == "ar1" else SIGNALS[alpha_kind]
    history = 0 if source is None else source.lookback
    r = drift + _DAILY_VOL * rng.standard_normal((n + history, m)) @ chol.T
    if source is not None:
        r += signal_ic * _DAILY_VOL * _ar1(rng, n + history, m, _LATENT_DRIFT_AR1)
    all_closes = 100.0 * np.exp(np.cumsum(r, axis=0))
    r, closes = r[history:], all_closes[history:]
    fwd = np.full((n, m), np.nan)
    fwd[:-FWD_SPAN_SESSIONS] = r[FWD_SPAN_SESSIONS:]
    if source is None:
        alpha = _ar1(rng, n, m, alpha_ar1) + signal_ic * np.nan_to_num((fwd - drift) / _DAILY_VOL)
    else:
        alpha = source.compute(all_closes)[history:]
    dates = np.busday_offset(_START, np.arange(n), roll="forward")
    return alpha, fwd, closes, dates


def _ar1(rng: np.random.Generator, n: int, m: int, phi: float) -> np.ndarray:
    """Unit-variance stationary AR(1) paths, [n, m]."""
    innovations = rng.standard_normal((n, m)) * np.sqrt(1 - phi**2)
    out = np.empty((n, m))
    out[0] = rng.standard_normal(m)
    for t in range(1, n):
        out[t] = phi * out[t - 1] + innovations[t]
    return out


def _one_seed(
    seed: int, n_shifts: int, cfg: HarnessConfig, signal_ic: float, panel_kw: dict
) -> tuple[str | None, float]:
    alpha, fwd, closes, dates = synthetic_panel(seed, signal_ic=signal_ic, **panel_kw)
    eval_kw = _eval_kwargs(panel_kw)
    shifts = np.sort(
        np.random.default_rng(seed).choice(
            admissible_shifts(len(dates), cfg.min_shift, eval_kw.get("memory", 0)),
            n_shifts,
            replace=False,
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
        **eval_kw,
    )
    if error is not None:
        return None, float("nan")
    return decide(res, cfg, fidelity_ok=True)["sleeve_verdict"], float(
        res.excess[res.arms.index(_reported_arm(panel_kw))]
    )


def _eval_kwargs(panel_kw: dict) -> dict:
    kind = panel_kw.get("alpha_kind", "ar1")
    return {} if kind == "ar1" else SIGNALS[kind].evaluate_kwargs()


def _reported_arm(panel_kw: dict) -> str:
    """vol_normalized for the calibrated arms, the signal source's own arm otherwise."""
    kind = panel_kw.get("alpha_kind", "ar1")
    return "vol_normalized" if kind == "ar1" else SIGNALS[kind].arm


def _run_seeds(
    seeds: range, n_shifts: int, workers: int, cfg: HarnessConfig, signal_ic: float, panel_kw: dict
) -> list[tuple[str | None, float]]:
    args = [(s, n_shifts, cfg, signal_ic, panel_kw) for s in seeds]
    if workers <= 1:
        return [_one_seed(*a) for a in args]
    with make_worker_pool(workers, cfg.blas_threads_per_worker) as pool:
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
        f"mean_excess_sharpe_{_reported_arm(panel_kw)}": float(
            np.nanmean([e for _, e in outcomes])
        ),
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
