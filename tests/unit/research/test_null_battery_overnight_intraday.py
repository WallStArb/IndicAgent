"""Family 2's E17 H0 battery module: its S1 path reproduces the drawn legs exactly through the
production transform, and simulate scores every registered member plus the book."""

from __future__ import annotations

import numpy as np

from src.intelligence.research import legs
from src.intelligence.research import null_battery_overnight_intraday as nb
from src.intelligence.research.panel import bar_returns


def test_source_panel_legs_and_target_are_the_drawn_legs():
    sc = nb.LegsScenario(
        "chk", sessions=40, names=25, leg_means=(0.1, -0.05, 0.02), late_fraction=0.3
    )
    rng = np.random.default_rng(0)
    u = nb._legs(sc, rng)
    listed = nb._listing_mask(sc, rng)
    lp = legs.session_legs(nb._source_panel(u, listed, rng))
    r = bar_returns(lp).reshape(40, 3, 25) / nb._PRICE_SCALE
    live = listed.reshape(40, 3, 25)[:, 0]
    np.testing.assert_allclose(r[:, 1][live], u[:, 1][live])
    np.testing.assert_allclose(r[:, 2][live], u[:, 2][live])
    both = live[1:] & live[:-1]  # the overnight leg needs the previous session listed
    np.testing.assert_allclose(r[1:, 0][both], u[1:, 0][both])
    np.testing.assert_allclose(legs.raw_target(lp)[live] / nb._PRICE_SCALE, u[:, 2][live])


def test_simulate_scores_every_member_and_the_book():
    sc = nb.LegsScenario("small", sessions=700, names=30)
    out = nb.simulate(sc, 3)
    assert set(out) == {m[0] for m in nb.MEMBERS} | {"book_equal"}
    assert all(np.isfinite(t) and 0 <= p <= 1 for t, p in out.values())


def test_registered_members_match_the_spec():
    from pathlib import Path

    from src.intelligence.research.spec import load_spec_from_file

    root = Path(__file__).resolve().parents[3]
    spec = load_spec_from_file(root / "research/specs/family2_overnight_intraday.yaml", root=root)
    got = {
        (m.name, m.signal.rsplit(".", 1)[1], m.slot_history_sessions) for m in spec.model.members
    }
    want = {(name, fn.__name__, memory) for name, fn, _, memory in nb.MEMBERS}
    assert got == want
