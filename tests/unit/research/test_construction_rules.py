"""Each construction rule reproduces its portfolio.py function bit for bit (phase 187 plan 07)."""

import numpy as np
import pytest
from pydantic import ValidationError

from scripts.research.determinism.config import HarnessConfig
from src.intelligence.research.construction import (
    CalibratedArm,
    FixedSign,
    RankVolNeutral,
    resolve_rule,
)
from src.intelligence.research.portfolio import (
    ARMS,
    arm_returns,
    arm_weights,
    fixed_sign_returns,
    plan_covariance,
    rank_vol_neutral_returns,
    rank_vol_neutral_weights,
)
from src.intelligence.research.spec import load_spec_from_file
from tests.unit.research.test_spec_hashes_pinned import ROOT

CFG = HarnessConfig(warmup_sessions=60, calibration_refit_sessions=30)
MV_COND = 1000.0
K = 100.0


def _panel(seed, n=200, m=8):
    rng = np.random.default_rng(seed)
    closes = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, (n, m)), axis=0))
    alpha = rng.normal(size=(n, m)).round(1)  # ties
    alpha[rng.random((n, m)) < 0.1] = np.nan
    alpha[5] = np.nan  # a row below the floor
    alpha[6, 1:] = np.nan
    fwd = rng.normal(0, 0.01, (n, m))
    fwd[rng.random((n, m)) < 0.05] = np.nan
    vol = rng.uniform(0.005, 0.02, (n, m))
    vol[rng.random((n, m)) < 0.05] = np.nan
    return closes, alpha, fwd, vol


@pytest.mark.parametrize("seed", [0, 1])
@pytest.mark.parametrize("direction", [1.0, -1.0])
def test_r1_is_rank_vol_neutral(seed, direction):
    _, alpha, fwd, vol = _panel(seed)
    rule = RankVolNeutral(direction, 3)
    w, has = rule.weights(alpha, vol=vol, fwd=fwd, plan=None)
    ew, ehas = rank_vol_neutral_weights(alpha, vol=vol, direction=direction, coverage_floor=3)
    assert np.array_equal(w, ew) and np.array_equal(has, ehas)
    got = rule.returns(alpha, fwd, None, vol=vol)
    want = rank_vol_neutral_returns(
        alpha, fwd, None, vol=vol, direction=direction, coverage_floor=3
    )
    assert np.array_equal(got["rank_vol_neutral"], want["rank_vol_neutral"], equal_nan=True)


@pytest.mark.parametrize("arm", ARMS)
def test_calibrated_arms_are_the_phase_179_arms(arm):
    closes, alpha, fwd, vol = _panel(2)
    plan = plan_covariance(closes, CFG, MV_COND)
    rule = CalibratedArm(arm, CFG, K)
    got = rule.returns(alpha, fwd, plan, vol=vol)
    assert list(got) == [arm]
    want = arm_returns(alpha, fwd, plan, CFG, K)[arm]
    assert np.array_equal(got[arm], want, equal_nan=True)
    w, has = rule.weights(alpha, vol=vol, fwd=fwd, plan=plan)
    ew = arm_weights(alpha, fwd, plan, CFG, K)[arm]
    assert np.array_equal(has, ~np.isnan(ew).all(axis=1))
    assert np.array_equal(w[has], ew[has]) and not w[~has].any()


@pytest.mark.parametrize("direction", [1.0, -1.0])
def test_fixed_sign_weights_carry_its_returns(direction):
    closes, alpha, fwd, vol = _panel(3)
    plan = plan_covariance(closes, CFG, MV_COND)
    rule = FixedSign(direction)
    got = rule.returns(alpha, fwd, plan, vol=vol)["fixed_sign"]
    want = fixed_sign_returns(alpha, fwd, plan, direction=direction)["fixed_sign"]
    assert np.array_equal(got, want, equal_nan=True)
    w, has = rule.weights(alpha, vol=vol, fwd=fwd, plan=plan)
    # A calibrated row with no finite nonzero forecast holds nothing: zero return, no position.
    assert np.array_equal(has, np.isfinite(want) & (np.abs(w).sum(axis=1) > 0))
    assert not w[~has].any() and not np.nan_to_num(want[~has]).any()
    # Same products, more zero terms in the sum: equal to the last few ulps.
    np.testing.assert_allclose((w * np.nan_to_num(fwd)).sum(axis=1)[has], want[has], rtol=1e-12)


def _spec(file, **changes):
    loaded = load_spec_from_file(ROOT / "research/specs" / file, root=ROOT)
    construction = loaded.model.construction.model_copy(update=changes)
    return loaded.model.model_copy(update={"construction": construction})


def test_resolve_rule_maps_every_name():
    c = _spec("family1_h2.yaml").construction
    assert resolve_rule(_spec("family1_h2.yaml"), 26) == RankVolNeutral(
        float(c.direction), c.coverage_floor
    )
    assert isinstance(resolve_rule(_spec("family1_h2.yaml", name="fixed_sign"), 26), FixedSign)
    for arm in ARMS:
        rule = resolve_rule(_spec("family1_h2.yaml", name=arm), 26)
        assert isinstance(rule, CalibratedArm) and rule.name == arm


def test_unknown_rule_name_is_a_spec_error():
    from src.intelligence.research.spec import ConstructionSpec

    base = _spec("family1_h2.yaml").construction.model_dump()
    with pytest.raises(ValidationError):
        ConstructionSpec(**{**base, "name": "equal_weight"})


def test_calibrated_arm_reads_its_calibration_in_rows():
    """evaluate() calibrates the arms on rows_config: a session-unit cfg would refit 26x too
    often on a 15m panel."""
    spec = _spec("family1_h2.yaml", name="mean_variance")
    s = spec.scoring
    rule = resolve_rule(spec, 26)
    assert rule.cfg.warmup_sessions == s.warmup_sessions * 26
    assert rule.cfg.calibration_refit_sessions == s.calibration_refit_sessions * 26


def test_plan_sized_rules_refuse_a_missing_plan():
    _, alpha, fwd, vol = _panel(4)
    for rule in (FixedSign(1.0), CalibratedArm("mean_variance", CFG, K)):
        with pytest.raises(ValueError, match="covariance plan"):
            rule.weights(alpha, vol=vol, fwd=fwd, plan=None)
