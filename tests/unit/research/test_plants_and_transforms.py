"""Research seams: panel transforms resolved from the spec, family-owned power plants, and the
step 0 breadth measure (synthetic.participation_ratio)."""

from __future__ import annotations

import pickle
import types

import numpy as np
import pytest

from src.intelligence.research import synthetic, transforms
from src.intelligence.research.families import overnight_intraday as f2
from src.intelligence.research.families.intraday_periodicity import SameSlotPlant
from src.intelligence.research.runner import Residuals, RunRefused, family_plant

POWER = types.SimpleNamespace(participation_ratio=20.0, n_common_factors=3, plant_lags_sessions=20)


def test_resolve_names_the_two_transforms_and_refuses_others():
    assert transforms.resolve(None) is transforms.IDENTITY
    assert transforms.resolve("session_legs") is transforms.SESSION_LEGS
    with pytest.raises(ValueError, match="unknown panel transform"):
        transforms.resolve("daily")


@pytest.mark.parametrize("t", [transforms.IDENTITY, transforms.SESSION_LEGS])
def test_transforms_pickle_for_process_pools(t):
    assert pickle.loads(pickle.dumps(t)).name == t.name


def _family(signal_module: str, n_members: int = 2):
    bps = 3 if signal_module.endswith("overnight_intraday") else 26
    members = [
        types.SimpleNamespace(signal=f"{signal_module}.fn{k}", name=f"m{k}")
        for k in range(n_members)
    ]
    return types.SimpleNamespace(
        family="f",
        members=members,
        panel=types.SimpleNamespace(analysis_bars_per_session=bps),
    )


def _residuals(sessions: int = 30, m: int = 25, seed: int = 0) -> Residuals:
    rng = np.random.default_rng(seed)
    bar = rng.normal(0, [[0.004], [0.001], [0.008]] * np.ones((1, m)), (sessions, 3, m))
    return Residuals(bar=bar.reshape(sessions * 3, m), fwd=np.full((sessions * 3, m), np.nan))


def test_family_plant_comes_from_the_family_module():
    res = _residuals()
    p2 = family_plant(
        [_family("src.intelligence.research.families.overnight_intraday")], POWER, res, 3
    )
    assert isinstance(p2, f2.LegsPlant) and p2.leg_sd.shape == (3, 25)
    p1 = family_plant(
        [_family("src.intelligence.research.families.intraday_periodicity")], POWER, res, 26
    )
    assert isinstance(p1, SameSlotPlant) and p1.plant_lags_sessions == 20


def test_family_plant_refuses_mixed_modules_and_multi_family_books():
    res = _residuals()
    mixed = _family("src.intelligence.research.families.overnight_intraday")
    mixed.members.append(
        types.SimpleNamespace(signal="src.intelligence.research.families.common.x", name="z")
    )
    with pytest.raises(RunRefused, match="span modules"):
        family_plant([mixed], POWER, res, 3)
    fam = _family("src.intelligence.research.families.overnight_intraday")
    with pytest.raises(RunRefused, match="2 families"):
        family_plant([fam, fam], POWER, res, 3)


def test_make_plant_pins_the_window_and_fills_missing_scales():
    res = _residuals()
    res.bar[:, 5] = np.nan  # name 5 never has a residual
    plant = f2.make_plant(POWER, res, 3)
    assert np.isfinite(plant.leg_sd).all()
    np.testing.assert_allclose(plant.leg_sd[:, 5], np.median(plant.leg_sd[:, :5], axis=1), rtol=0.3)
    with pytest.raises(ValueError, match="20 sessions"):
        f2.make_plant(types.SimpleNamespace(**{**vars(POWER), "plant_lags_sessions": 40}), res, 3)


S, M = 400, 40


def _plant() -> f2.LegsPlant:
    sd = np.array([[0.004], [0.001], [0.008]]) * np.ones((1, M))
    return f2.LegsPlant(participation_ratio=20.0, n_common_factors=3, leg_sd=sd)


def test_legs_plant_target_is_row_2_on_row_1_and_masks_apply():
    mask = np.random.default_rng(1).random((S * 3, M)) > 0.05
    resid, target = _plant().generate(mask, plant_coef=0.0, seed=3)
    assert np.isnan(target[0::3]).all() and np.isnan(target[2::3]).all()
    both = mask[2::3]
    np.testing.assert_array_equal(target[1::3][both], resid[2::3][both])
    assert np.isnan(resid[~mask]).all()


def test_legs_plant_only_moves_row_2_and_keeps_the_draws():
    mask = np.ones((S * 3, M), dtype=bool)
    r0, _ = _plant().generate(mask, plant_coef=0.0, seed=4)
    r1, _ = _plant().generate(mask, plant_coef=0.01, seed=4)
    np.testing.assert_array_equal(r0[0::3], r1[0::3])
    np.testing.assert_array_equal(r0[1::3], r1[1::3])
    assert not np.array_equal(r0[2::3], r1[2::3])


def _members():
    return [
        (f2.intraday_persistence, {"window_sessions": 20}),
        (f2.overnight_to_intraday, {"window_sessions": 20}),
        (f2.gap_fade, {}),
    ]


def _ic(coef: float, seed: int = 5) -> float:
    mask = np.ones((S * 3, M), dtype=bool)
    resid, target = _plant().generate(mask, plant_coef=coef, seed=seed)
    stack = synthetic._member_stack(resid, _members(), 3, coverage_floor=20)
    return synthetic.combo_rank_ic(stack, target, coverage_floor=20, bars_per_session=3)


def test_legs_plant_is_detected_by_the_members_and_grows_with_strength():
    ics = [_ic(c) for c in (0.0, 0.002, 0.02)]
    assert abs(ics[0]) < 0.03
    assert ics[0] < ics[1] < ics[2] and ics[2] > 0.3


def test_calibrate_plant_reaches_the_family_2_target_ic():
    mask = np.ones((S * 3, M), dtype=bool)
    got = synthetic.calibrate_plant(
        _plant(),
        mask,
        members=_members(),
        coverage_floor=20,
        target_ic=0.05,
        tolerance=0.01,
        n_panels=2,
        seed=7,
    )
    assert abs(got.achieved_ic - 0.05) <= 0.01


def test_participation_ratio_matches_step_0_definition():
    rng = np.random.default_rng(0)
    iid = rng.normal(size=(5000, 30))
    assert synthetic.participation_ratio(iid) == pytest.approx(30, rel=0.05)
    common = rng.normal(size=(5000, 1)) + 0.01 * rng.normal(size=(5000, 30))
    assert synthetic.participation_ratio(common) == pytest.approx(1, rel=0.05)
    sparse = iid.copy()
    sparse[:4500, 0] = np.nan  # 10% coverage: dropped by the 80% rule
    assert synthetic.participation_ratio(sparse) == pytest.approx(29, rel=0.05)


def test_check_family_plant_runs_the_static_checks():
    from src.intelligence.research.runner import check_family_plant

    fam = _family("src.intelligence.research.families.overnight_intraday")
    fam.panel = types.SimpleNamespace(analysis_bars_per_session=3)
    assert check_family_plant([fam], POWER) is f2
    wrong = types.SimpleNamespace(**{**vars(POWER), "plant_lags_sessions": 40})
    with pytest.raises(RunRefused, match="20 sessions"):
        check_family_plant([fam], wrong)
    fam.panel = types.SimpleNamespace(analysis_bars_per_session=26)
    with pytest.raises(RunRefused, match="legs panel"):
        check_family_plant([fam], POWER)


def test_run_book_refuses_a_bad_plant_before_the_ledger(tmp_path):
    import asyncio

    from src.intelligence.research.runner import BudgetConfig, RunContext, run_book
    from src.intelligence.research.spec import BookSpec
    from tests.unit.research.test_runner_legs import _load, _spec_text

    fam = _load(tmp_path, _spec_text())
    book = BookSpec.model_construct(
        power=types.SimpleNamespace(**{**vars(POWER), "plant_lags_sessions": 40})
    )
    loaded = types.SimpleNamespace(model=book, families=[fam])

    class Ledger:
        async def start_runs(self, *args, **kwargs):
            raise AssertionError("the ledger was reached")

    ctx = RunContext(root=tmp_path, budget=BudgetConfig("test", 1, 0.05), ledger=Ledger())
    with pytest.raises(RunRefused, match="20 sessions"):
        asyncio.run(run_book(loaded, ctx, mode="real"))
