"""The daily residual family's E17 battery module (prereg 2026-10-27, B2): shape and wiring."""

import numpy as np

from src.intelligence.research import null_battery_daily_residual as b


def test_every_cell_scores_every_member_and_the_book():
    sc = b.DailyScenario("tiny", sessions=700, names=40, market_mean=0.04)
    out = b.simulate(sc, 3)
    assert set(out) == {m[0] for m in b.MEMBERS} | {"book_equal"}
    assert all(np.isfinite(t) and 0 <= p <= 1 for t, p in out.values())


def test_the_target_is_open_to_open_over_the_next_five_sessions():
    """Row d: intraday d+1 .. d+5 plus overnight d+2 .. d+6, as the S1 path's price panel."""
    overnight = np.arange(12, dtype=float)[:, None] * 100
    intraday = np.arange(12, dtype=float)[:, None]
    fwd = b._forward(overnight, intraday)
    assert fwd[0, 0] == (1 + 2 + 3 + 4 + 5) + 100 * (2 + 3 + 4 + 5 + 6)
    assert np.isnan(fwd[-6:]).all() and np.isfinite(fwd[:-6]).all()
    listed = np.ones((12, 1), dtype=bool)
    panel = b._price_panel(overnight / 100, intraday / 100, listed)
    want = np.log(panel.open[6, 0] / panel.open[1, 0]) / b._PRICE_SCALE
    assert np.isclose(want, fwd[0, 0] / 100)


def test_gate_is_the_largest_gating_cell():
    gate = b.static_gate()
    assert gate.cell_rows == 1
    assert gate.static_sd == (b.GATE_STATIC_SD,)
    assert gate.time_of_day == (b.GATE_MARKET_MEAN,)


def test_horizon_defaults_to_the_spec_and_a_longer_one_shortens_the_target():
    import dataclasses

    import numpy as np

    from src.intelligence.research import null_battery_daily_residual as nb

    base = nb.scenarios()[0]
    assert base.horizon == nb.HORIZON == 5
    _, t5 = nb.null_panel(base, 1)
    _, t21 = nb.null_panel(dataclasses.replace(base, horizon=21), 1)
    assert np.isfinite(t5).sum() > np.isfinite(t21).sum()  # 21 rows lost at the end, not 5
    assert np.isfinite(t5).sum() - np.isfinite(t21).sum() == 16 * base.names
