"""Residual-space generator (D-19, D-20): breadth, bar/slot/target consistency, plant
monotonicity, calibration, determinism, price-panel integrity."""

import functools

import numpy as np
import pytest

from src.intelligence.research.factors import FactorSpec, residual_returns
from src.intelligence.research.families.intraday_periodicity import SameSlotPlant, same_slot_mean
from src.intelligence.research.guards import integrity
from src.intelligence.research.panel import bar_returns
from src.intelligence.research.synthetic import (
    _member_stack,
    calibrate_plant,
    combo_rank_ic,
    loading_scale_for_pr,
    synthetic_price_panel,
)

SPEC26 = SameSlotPlant(
    bars_per_session=26, participation_ratio=60.0, n_common_factors=10, plant_lags_sessions=40
)
SMALL = SameSlotPlant(
    bars_per_session=6, participation_ratio=8.0, n_common_factors=5, plant_lags_sessions=5
)
MEMBERS = tuple((same_slot_mean, {"window_sessions": w}) for w in (1, 5, 20, 40))


def _pr(s, m, k):
    lam = np.array([1 + s] * k + [1.0] * (m - k))
    return lam.sum() ** 2 / (lam**2).sum()


@pytest.mark.parametrize("m,k,p", [(233, 10, 60.0), (100, 5, 30.0)])
def test_loading_scale_hits_participation_ratio(m, k, p):
    assert _pr(loading_scale_for_pr(m, k, p), m, k) == pytest.approx(p, abs=1e-9)


def test_unattainable_participation_ratio_raises():
    with pytest.raises(ValueError):
        loading_scale_for_pr(100, 5, 2.0)
    with pytest.raises(ValueError):
        loading_scale_for_pr(100, 5, 150.0)


def test_sample_participation_ratio_near_target():
    spec = SameSlotPlant(
        bars_per_session=26, participation_ratio=60.0, n_common_factors=10, plant_lags_sessions=40
    )
    mask = np.ones((2400 * 26 // 26 * 26, 233), dtype=bool)[: 60_008 // 26 * 26]
    resid, _ = spec.generate(mask, plant_coef=0.0, seed=0)
    slots = resid.reshape(-1, 2, 233).sum(axis=1)
    lam = np.linalg.eigvalsh(np.corrcoef(slots, rowvar=False))
    assert lam.sum() ** 2 / (lam**2).sum() == pytest.approx(60.0, abs=5.0)


def test_bars_slots_and_target_are_consistent():
    n_sessions, m = 12, 8
    mask = np.ones((n_sessions * 6, m), dtype=bool)
    mask[7, 2] = False  # session 1, bar 1 -> slot 0 of session 1 masked for name 2
    resid, target = SMALL.generate(mask, plant_coef=0.3, seed=1)
    assert np.isnan(resid[~mask]).all() and np.isfinite(resid[mask]).all()
    slot = resid.reshape(n_sessions, 3, 2, m).sum(axis=2)
    for d in range(n_sessions):
        for j in range(3):
            row = d * 6 + 2 * j - 1
            if row < 0:
                continue
            if d == 1 and j == 0:
                assert np.isnan(target[row, 2])
                np.testing.assert_allclose(
                    target[row, [0, 1, 3]], slot[d, j, [0, 1, 3]], rtol=1e-12, atol=1e-12
                )
            else:
                np.testing.assert_allclose(target[row], slot[d, j], rtol=1e-12, atol=1e-12)
    placed = {d * 6 + 2 * j - 1 for d in range(n_sessions) for j in range(3)} - {-1}
    assert np.isnan(target[[t for t in range(n_sessions * 6) if t not in placed]]).all()


def test_determinism():
    mask = np.ones((60, 10), dtype=bool)
    a = SMALL.generate(mask, plant_coef=0.2, seed=5)
    b = SMALL.generate(mask, plant_coef=0.2, seed=5)
    for x, y in zip(a, b):
        np.testing.assert_array_equal(x, y)


def _ic(coef, seed, sessions=200, m=60):
    mask = np.ones((sessions * 26, m), dtype=bool)
    resid, target = SPEC26.generate(mask, plant_coef=coef, seed=seed)
    stack = _member_stack(resid, MEMBERS, 26, 20)
    return combo_rank_ic(stack, target, coverage_floor=20, bars_per_session=26)


def test_no_plant_gives_zero_ic_and_ic_grows_with_plant():
    null = np.array([_ic(0.0, s) for s in range(4)])
    se = null.std(ddof=1) / 2
    assert abs(null.mean()) < 3 * max(se, 1e-3)
    ics = [np.mean([_ic(c, s) for s in range(2)]) for c in (0.0, 0.2, 0.4, 0.8)]
    assert ics[1] > 0 and all(b > a for a, b in zip(ics, ics[1:]))


def test_calibrate_plant_hits_target():
    mask = np.ones((200 * 26, 60), dtype=bool)
    plant = calibrate_plant(
        SPEC26,
        mask,
        members=MEMBERS,
        coverage_floor=20,
        target_ic=0.02,
        tolerance=0.002,
        n_panels=2,
        seed=7,
    )
    assert abs(plant.achieved_ic - 0.02) <= 0.002
    assert plant.iterations >= 1 and plant.plant_coef > 0 and np.isfinite(plant.ic_se)


def test_synthetic_price_panel_residualizes_and_passes_integrity():
    spec = SameSlotPlant(
        bars_per_session=4, participation_ratio=20.0, n_common_factors=5, plant_lags_sessions=5
    )
    panel = synthetic_price_panel(
        spec,
        n_sessions=120,
        n_names=30,
        plant_coef=0.3,
        seed=2,
        start="2012-01-02",
        missing_fraction=0.02,
    )
    fs = FactorSpec(
        window_sessions=20,
        refit_sessions=5,
        n_components=2,
        min_finite_sessions=10,
        min_group_size=5,
    )
    resid = residual_returns(bar_returns(panel), bars_per_session=4, spec=fs).residual
    late = resid[40 * 4 :]
    assert np.isfinite(late).mean() > 0.8
    alpha = functools.partial(
        same_slot_mean, bars_per_session=4, coverage_floor=20, window_sessions=5
    )(resid)
    integrity(panel, alpha)


def test_target_mask_blanks_the_target_only():
    mask = np.ones((60, 12), dtype=bool)
    target_mask = np.ones((60, 12), dtype=bool)
    target_mask[:30] = False
    resid_a, target_a = SMALL.generate(mask, plant_coef=0.2, seed=3)
    resid_b, target_b = SMALL.generate(mask, plant_coef=0.2, seed=3, target_mask=target_mask)
    np.testing.assert_array_equal(resid_a, resid_b)
    assert np.isnan(target_b[:30]).all()
    np.testing.assert_array_equal(target_a[30:], target_b[30:])
