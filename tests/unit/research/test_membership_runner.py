"""Membership gates alpha and target only; S1 never sees a name before its first membership
(todo 609 I1, ruling A with the point-in-time condition)."""

import dataclasses
from pathlib import Path

import numpy as np

from src.intelligence.research import panel as panel_mod
from src.intelligence.research import runner
from src.intelligence.research.spec import parse_spec_text

N, M, LATE = 700, 10, 300  # name M-1 first becomes a member at session LATE


def _panel(with_member: bool, drop_late_name: bool = False):
    rng = np.random.default_rng(7)
    market = rng.normal(0, 0.01, N)[:, None]
    r = market + rng.normal(0, 0.01, (N, M))
    close = 100 * np.exp(np.cumsum(r, axis=0))
    open_ = np.vstack([close[:1], close[:-1]])
    if drop_late_name:
        close[:, -1] = np.nan
        open_[:, -1] = np.nan
    panel = panel_mod.daily_panel(close, opens=open_, volume=np.full((N, M), 1e6))
    if not with_member:
        return panel
    member = np.ones((N, M), dtype=bool)
    member[:LATE, -1] = False  # the late name is not a member before LATE
    member[500:, 0] = False  # name 0 leaves at 500
    return dataclasses.replace(panel, member=member)


def _residuals(panel):
    return runner.compute_residuals(panel, horizon=5, factor_spec=runner.FACTOR_SPECS["vintage_1"])


def test_a_name_with_a_later_first_membership_is_not_in_any_earlier_s1_statistic():
    with_name = _residuals(_panel(True))
    without = _residuals(_panel(True, drop_late_name=True))
    # Before the late name's first membership, every other name's residual is exactly what it is
    # with that name absent from the panel: it entered no market mean, cluster or PC.
    assert np.array_equal(with_name.bar[:LATE, :-1], without.bar[:LATE, :-1], equal_nan=True)
    assert np.isnan(with_name.bar[:LATE, -1]).all()


def test_target_is_nan_for_non_members_and_unchanged_for_members_elsewhere():
    res = _residuals(_panel(True))
    assert np.isnan(res.fwd[:LATE, -1]).all()
    assert np.isnan(res.fwd[500:, 0]).all()
    assert np.isfinite(res.fwd[LATE + 200 : N - 10, -1]).any()
    assert np.isfinite(res.fwd[400:440, 1]).all()


def test_a_panel_without_a_member_array_is_computed_exactly_as_before():
    plain = _panel(False)
    res = _residuals(plain)
    assert np.isfinite(res.fwd[300:340, -1]).all()
    assert np.isfinite(res.bar[300:340, -1]).all()


def test_alpha_is_masked_to_members():
    spec_text = Path("research/specs/daily_residual_h5.yaml").read_text()
    spec = parse_spec_text(spec_text)
    panel = _panel(True)
    res = _residuals(panel)
    alphas = runner.compute_members(spec, res.bar, bars_per_session=1, panel=panel)
    for alpha in alphas.values():
        assert np.isnan(alpha[:LATE, -1]).all()
        assert np.isnan(alpha[500:, 0]).all()
