"""The family 10 E17 battery (todo 663): the registered members on a synthetic volume panel."""

import dataclasses

import numpy as np

from src.intelligence.research import null_battery_daily_residual as daily
from src.intelligence.research import null_battery_volume_shock as battery


def test_members_and_floors_come_from_the_registered_spec():
    got = battery.members()
    assert [name for name, *_ in got] == ["volume_shock_1_50", "volume_shock_5_50"]
    assert {memory for *_, memory in got} == {50}
    assert got[1][2] == {"window": 50, "short": 5, "min_finite": 40, "min_finite_short": 37}
    assert all(m.orthogonalize.min_names == 200 for m in battery._spec().members)


def test_scenarios_are_the_declared_cells_and_panels_clear_the_fit_floor_and_memory():
    cells = battery.scenarios()
    assert [c.name for c in cells] == [
        "volume_gaussian",
        "volume_static_means",
        "volume_late_listings",
        "volume_hostile",
        "volume_hostile_no_static",
        "volume_s1_hostile",
        "volume_convex_stress",
        "volume_unit_root_stress",
    ]
    assert battery.DIAGNOSTIC_CELLS == {"volume_convex_stress", "volume_unit_root_stress"}
    floor = max(m.orthogonalize.min_names for m in battery._spec().members)
    for sc in cells:
        assert sc.names == battery.NAMES > floor, sc.name  # a 100-name panel would be all NaN
        assert sc.sessions >= 323 + 1408 + 252 + 126, sc.name
    gate = battery.static_gate()
    assert gate.battery == battery.__name__ and gate.static_sd == (0.06,)


def test_the_volume_generator_is_deterministic_positive_and_h0():
    sc = battery.scenarios()[0]
    resid, _ = battery.daily.null_panel(sc, 4)
    a = battery.synthetic_volume(sc, resid, 4)
    np.testing.assert_array_equal(a, battery.synthetic_volume(sc, resid, 4))
    assert (a[np.isfinite(a)] > 0).all() and np.isnan(a[~np.isfinite(resid)]).all()
    # H0: volume is unrelated to the NEXT signed return (the dependence is on move sizes only)
    ok = np.isfinite(a[:-1]) & np.isfinite(resid[1:])
    corr = np.corrcoef(np.log(a[:-1][ok]), resid[1:][ok])[0, 1]
    assert abs(corr) < 0.02
    # and it does depend on the same-session move size (what the orthogonalization removes)
    ok = np.isfinite(a) & np.isfinite(resid)
    assert np.corrcoef(np.log(a[ok]), np.abs(resid[ok]))[0, 1] > 0.05


def test_hostile_volume_has_holes_steps_and_keeps_the_short_means_defined():
    hostile = next(c for c in battery.scenarios() if c.name == "volume_hostile_no_static")
    resid, _ = battery.daily.null_panel(hostile, 5)
    v = battery.synthetic_volume(hostile, resid, 5)
    holes = np.isnan(v) & np.isfinite(resid)
    assert abs(holes.mean() / np.isfinite(resid).mean() - battery.HOLE_FRACTION) < 0.005
    arrays = battery.member_arrays(battery._spec(), v, resid)
    # V2 needs 37 of 46 finite short means: at the declared hole rate it is defined, not all NaN
    assert np.isfinite(arrays["volume_shock_5_50"]).mean() > 0.3


def test_one_simulation_scores_both_members_and_the_book_with_finite_statistics():
    sc = battery.scenarios()[0]
    out = battery.simulate(sc, 3)
    assert set(out) == {"volume_shock_1_50", "volume_shock_5_50", "book_equal"}
    assert all(np.isfinite(t) and 0.0 <= p <= 1.0 for t, p in out.values())
    series = battery.simulate_series(sc, 3)
    assert all(np.isfinite(s).any() for s in series.values())


def test_inputs_mismatch_refuses_a_member_the_battery_does_not_run():
    spec = battery._spec()
    assert battery.inputs_mismatch(spec) == []
    plain = spec.members[0].model_copy(update={"orthogonalize": None})
    bad = spec.model_copy(update={"members": [plain, *spec.members[1:]]})
    assert any(m.startswith("members") for m in battery.inputs_mismatch(bad))
    assert "horizon" in battery.inputs_mismatch(spec.model_copy(update={"horizon": 21}))


def test_the_s1_cell_carries_the_same_move_size_dependence_as_the_other_cells():
    """The S1 cell's residuals are at the price scale; the generator puts them back at unit sd, so
    the volume-on-|move| dependence the stage exists to remove is the same size in every cell."""
    sc = battery.scenarios()[0]
    s1 = dataclasses.replace(sc, s1=True)
    rng = np.random.default_rng(4)
    u = rng.standard_normal((1500, 40))
    plain = battery.synthetic_volume(sc, u, 7)
    scaled = battery.synthetic_volume(s1, u * daily._PRICE_SCALE, 7)
    assert np.allclose(plain, scaled)
