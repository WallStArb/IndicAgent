import numpy as np
import pandas as pd
import pytest
from scipy.stats import spearmanr

from scripts.analysis.sleeve_walk_forward.config import HarnessConfig
from src.intelligence.portfolio import weighting as W
from src.intelligence.research.portfolio import (
    arm_returns,
    fixed_sign_returns,
    plan_covariance,
)

CFG = HarnessConfig(warmup_sessions=60, calibration_refit_sessions=30)
MV_COND = 1000.0
K = 100.0


def _panel(seed, n=200, m=5, nan_frac=0.02):
    rng = np.random.default_rng(seed)
    closes = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, (n, m)), axis=0))
    alpha = rng.normal(size=(n, m))
    fwd = rng.normal(0, 0.01, (n, m))
    alpha[rng.random((n, m)) < nan_frac] = np.nan
    fwd[rng.random((n, m)) < nan_frac] = np.nan
    return closes, alpha, fwd


def reference(closes, alpha, fwd, cfg=CFG):
    n, m = alpha.shape
    rets = W.log_returns(pd.DataFrame(closes))
    rets.index = range(1, n)
    a = pd.DataFrame(alpha)
    out = {
        arm: np.full(n, np.nan) for arm in ("ic_proportional", "vol_normalized", "mean_variance")
    }
    state = None
    for d in range(n):
        if (
            d >= cfg.warmup_sessions
            and (d - cfg.warmup_sessions) % cfg.calibration_refit_sessions == 0
        ):
            b = d - 2
            hist = rets.loc[:b].tail(cfg.warmup_sessions)
            cov, syms = W.instrument_covariance(hist, min_coverage_fraction=cfg.coverage_fraction)
            if len(syms) >= 2:
                ic_raw, n_eff = [], []
                for s in syms:
                    z = W.standardize_scores(a[s].loc[:b].tail(cfg.warmup_sessions))
                    f = pd.Series(fwd[:, s]).loc[:b].tail(cfg.warmup_sessions)
                    p = pd.concat([z, f], axis=1).dropna()
                    n_alpha = int(a[s].loc[:b].tail(cfg.warmup_sessions).notna().sum())
                    ok = len(p) >= 2 and len(p) >= cfg.coverage_fraction * n_alpha
                    r = spearmanr(p.iloc[:, 0], p.iloc[:, 1])[0] if ok else 0.0
                    ic_raw.append(0.0 if not np.isfinite(r) else float(r))
                    n_eff.append(float(len(p)))
                ic = W.shrink_instrument_ic(np.array(ic_raw), np.array(n_eff), K)
                state = (cov, list(syms), ic)
        if state is None:
            continue
        cov, syms, ic = state
        sigma = np.sqrt(np.maximum(np.diag(cov), 1e-12))
        z = np.array(
            [
                (
                    W.standardize_scores(a[s].loc[:d].tail(cfg.warmup_sessions)).iloc[-1]
                    if np.isfinite(alpha[d, s])
                    else 0.0
                )
                for s in syms
            ]
        )
        mu = W.compute_mu(ic, sigma, z)
        r = np.nan_to_num(fwd[d, syms])
        out["ic_proportional"][d] = W.ic_proportional_arm(mu) @ r
        out["vol_normalized"][d] = W.vol_normalized_arm(mu, sigma) @ r
        w, _m, _c = W.mean_variance_arm(
            cov, mu, MV_COND, ridge_epsilon_fraction=CFG.ridge_epsilon_fraction
        )
        out["mean_variance"][d] = w @ r
    return out


@pytest.mark.parametrize("seed", [0, 1, 2])
def test_engine_matches_reference(seed):
    closes, alpha, fwd = _panel(seed)
    plan = plan_covariance(closes, CFG, MV_COND)
    got = arm_returns(alpha, fwd, plan, CFG, K)
    want = reference(closes, alpha, fwd)
    for arm in want:
        np.testing.assert_allclose(got[arm], want[arm], rtol=1e-9, atol=1e-12, equal_nan=True)


def test_symbol_without_alpha_takes_no_signal_position():
    closes, alpha, fwd = _panel(3, nan_frac=0.0)
    alpha[:, 2] = np.nan
    plan = plan_covariance(closes, CFG, MV_COND)
    got = arm_returns(alpha, fwd, plan, CFG, K)
    want = reference(closes, alpha, fwd)
    np.testing.assert_allclose(
        got["vol_normalized"], want["vol_normalized"], rtol=1e-9, equal_nan=True
    )


def test_plan_is_shared_across_shifts():
    closes, alpha, fwd = _panel(4)
    plan = plan_covariance(closes, CFG, MV_COND)
    a1 = arm_returns(alpha, fwd, plan, CFG, K)
    a2 = arm_returns(np.roll(alpha, 70, axis=0), fwd, plan, CFG, K)
    assert not np.allclose(
        np.nan_to_num(a1["ic_proportional"]), np.nan_to_num(a2["ic_proportional"])
    )


def test_fixed_sign_is_direction_times_sign_over_sigma_gross_one():
    closes, alpha, fwd = _panel(4, nan_frac=0.0)
    plan = plan_covariance(closes, CFG, MV_COND)
    out = fixed_sign_returns(alpha, fwd, plan, direction=1.0)["fixed_sign"]
    p = plan.refit_positions[0]
    idx, sig = plan.symbol_idx[0], plan.sigma[0]
    w = np.sign(alpha[p, idx]) / sig
    w /= np.abs(w).sum()
    assert out[p] == pytest.approx(float(w @ fwd[p, idx]))
    assert np.isnan(out[:p]).all()  # nothing before the first calibration refit
    flipped = fixed_sign_returns(alpha, fwd, plan, direction=-1.0)["fixed_sign"]
    np.testing.assert_allclose(flipped[p:], -out[p:])


def test_fixed_sign_missing_alpha_takes_no_position():
    closes, alpha, fwd = _panel(5, nan_frac=0.0)
    alpha[:, 0] = np.nan
    plan = plan_covariance(closes, CFG, MV_COND)
    base = fixed_sign_returns(alpha, fwd, plan, direction=1.0)["fixed_sign"]
    moved = fwd.copy()
    moved[:, 0] += 1.0
    np.testing.assert_allclose(
        fixed_sign_returns(alpha, moved, plan, direction=1.0)["fixed_sign"], base
    )


def test_arm_weights_reproduce_arm_returns():
    """The stored weights are the ones the returns were built from (section 11 inputs)."""
    from src.intelligence.research.portfolio import arm_returns, arm_weights

    closes, alpha, fwd = _panel(4)
    plan = plan_covariance(closes, CFG, MV_COND)
    ret = arm_returns(alpha, fwd, plan, CFG, K)
    w = arm_weights(alpha, fwd, plan, CFG, K)
    for arm, r in ret.items():
        rebuilt = np.where(
            np.isnan(w[arm]).all(axis=1),
            np.nan,
            (np.nan_to_num(w[arm]) * np.nan_to_num(fwd)).sum(axis=1),
        )
        np.testing.assert_allclose(rebuilt, r, rtol=1e-12, atol=1e-15, equal_nan=True)


def test_gappy_alpha_still_calibrates():
    """Todo 425: alpha missing on a third of days (no-weight strata) must not zero the IC; the
    coverage bar is over the days alpha is defined, returns fully present there."""
    from src.intelligence.research.portfolio import _calibrate

    rng = np.random.default_rng(7)
    n, m = 300, 3
    fwd = rng.normal(0, 0.01, (n, m))
    alpha = fwd + rng.normal(0, 0.01, (n, m))  # informative
    alpha[rng.random((n, m)) < 0.33] = np.nan
    ic = _calibrate(alpha, fwd, np.arange(m), n - 1, CFG, K)
    assert (ic > 0.2).all()


def test_missing_returns_on_alpha_days_zero_the_ic():
    from src.intelligence.research.portfolio import _calibrate

    rng = np.random.default_rng(8)
    n, m = 300, 3
    fwd = rng.normal(0, 0.01, (n, m))
    alpha = fwd + rng.normal(0, 0.01, (n, m))
    fwd[rng.random((n, m)) < 0.2] = np.nan  # 20% of alpha days lack a return: below 95%
    ic = _calibrate(alpha, fwd, np.arange(m), n - 1, CFG, K)
    np.testing.assert_allclose(ic, 0.0)
