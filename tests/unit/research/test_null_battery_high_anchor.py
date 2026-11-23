"""The family 9 E17 battery: the production member on the daily battery's synthetic closes."""

import numpy as np
import pytest

from src.intelligence.research import null_battery_daily_residual as daily
from src.intelligence.research import null_battery_high_anchor as battery
from src.intelligence.research.families import high_anchor


def test_the_battery_reads_the_registered_spec_and_names_itself_in_the_family_module():
    """The member, window and memory pins live in test_published_prior_specs."""
    assert high_anchor.NULL_BATTERY == battery.__name__
    assert battery.inputs_mismatch(battery._spec()) == []


def test_scenarios_are_the_daily_cells_renamed_with_two_diagnostics():
    names = [c.name for c in battery.scenarios()]
    assert names == [
        "high_anchor_gaussian",
        "high_anchor_static_means",
        "high_anchor_late_listings",
        "high_anchor_hostile",
        "high_anchor_hostile_no_static",
        "high_anchor_s1_hostile",
        "high_anchor_static_vol_stress",
        "high_anchor_hostile_stress",
    ]
    assert battery.DIAGNOSTIC_CELLS == {
        "high_anchor_static_vol_stress",
        "high_anchor_hostile_stress",
    }
    assert [c.name for c in daily.scenarios()][0] == "daily_gaussian"
    gate, base = battery.static_gate(), daily.static_gate()
    assert gate.battery == battery.__name__
    assert (gate.static_sd, gate.time_of_day) == (base.static_sd, base.time_of_day)


@pytest.mark.parametrize(
    "cell", [c.name for c in battery.scenarios() if not c.s1], ids=lambda name: name
)
def test_the_closes_are_the_same_draw_as_the_residual_returns_the_member_is_scored_against(cell):
    """price_panel replays the generator calls of daily.null_panel on one seed: for a cell with no
    S1 step the log close-to-close return is the residual return times the price scale."""
    sc = next(c for c in battery.scenarios() if c.name == cell)
    resid, _ = daily.null_panel(sc, 11)
    close = battery.price_panel(sc, 11).close
    step = np.log(close[1:] / close[:-1]) / daily._PRICE_SCALE
    both = np.isfinite(step) & np.isfinite(resid[1:])
    assert both.sum() > 1000
    assert np.allclose(step[both], resid[1:][both])
    assert np.array_equal(np.isfinite(close), np.isfinite(resid))


def test_the_s1_cell_replays_the_panel_s1_actually_saw(monkeypatch):
    """In the S1 cell the price panel is the generator: the closes the member reads must be the
    panel null_panel hands runner.compute_residuals."""
    from src.intelligence.research import runner

    seen = []
    real = runner.compute_residuals
    monkeypatch.setattr(
        runner, "compute_residuals", lambda panel, **kw: (seen.append(panel), real(panel, **kw))[1]
    )
    sc = next(c for c in battery.scenarios() if c.name == "high_anchor_s1_hostile")
    daily.null_panel(sc, 5)
    mine = battery.price_panel(sc, 5)
    assert np.array_equal(seen[0].close, mine.close, equal_nan=True)
    assert np.array_equal(seen[0].open, mine.open, equal_nan=True)


def test_the_member_route_has_no_orthogonalization_stage_to_skip():
    """The battery calls compute_panel_members; the runner also runs orthogonalize_members. They
    agree only while no member declares the stage."""
    assert all(m.orthogonalize is None for m in battery._spec().members)


def test_one_simulation_scores_the_member_with_finite_statistics():
    sc = battery.scenarios()[0]
    out = battery.simulate(sc, 3)
    assert set(out) == {"high_distance_252"}
    t, p = out["high_distance_252"]
    assert np.isfinite(t) and 0.0 <= p <= 1.0
    series = battery.simulate_series(sc, 3)
    assert np.isfinite(series["high_distance_252"]).any()


def test_inputs_mismatch_refuses_a_member_the_battery_does_not_run():
    spec = battery._spec()
    plain = spec.members[0].model_copy(update={"panel_source": None})
    bad = spec.model_copy(update={"members": [plain]})
    assert any(m.startswith("members") for m in battery.inputs_mismatch(bad))
    assert battery.inputs_mismatch(spec) == []
    longer = spec.model_copy(update={"horizon": 21})
    assert "horizon" in battery.inputs_mismatch(longer)
