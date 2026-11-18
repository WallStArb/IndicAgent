"""The member mask on an intraday panel (todo 609 I2): per session, repeated over every bar of the
session; S1 never sees a name before its first membership; targets are NaN for a non-member."""

import dataclasses

import numpy as np

from src.intelligence.measure.targets import chunk_targets
from src.intelligence.research import membership, runner
from src.intelligence.research.panel import Panel

BPS, SESSIONS, M, LATE = 3, 520, 10, 300


def _panel(drop_late: bool = False, with_member: bool = True) -> Panel:
    rng = np.random.default_rng(5)
    n = BPS * SESSIONS
    market = rng.normal(0, 0.004, (n, 1))
    ret = market + rng.normal(0, 0.004, (n, M))
    close = 100 * np.exp(np.cumsum(ret, axis=0))
    open_ = np.vstack([close[:1], close[:-1]])
    if drop_late:
        close[:, -1] = np.nan
        open_[:, -1] = np.nan
    days = np.busday_offset(np.datetime64("2010-01-04"), np.arange(SESSIONS))
    stamps = (
        days.astype("datetime64[m]")[:, None]
        + np.timedelta64(14 * 60 + 30, "m")
        + np.arange(BPS)[None, :] * np.timedelta64(5, "m")
    ).ravel()
    panel = Panel(
        tf="5m",
        symbols=tuple(f"s{j}" for j in range(M)),
        timestamps=stamps.astype("datetime64[ns]"),
        bars_per_session=BPS,
        valid=np.ones(n, dtype=bool),
        open=open_,
        close=close,
        volume=np.ones((n, M)),
    )
    if not with_member:
        return panel
    member = np.ones((SESSIONS, M), dtype=bool)
    member[:LATE, -1] = False  # the late name is a tier member from session LATE
    member[450:, 0] = False  # name 0 leaves the tier at session 450
    return dataclasses.replace(panel, member=member)


def _residuals(panel):
    return runner.compute_residuals(panel, horizon=1, factor_spec=runner.FACTOR_SPECS["vintage_1"])


def test_the_mask_is_per_session_and_repeats_over_every_bar_of_the_session():
    panel = _panel()
    target = chunk_targets(panel, 1)
    rows = np.repeat(panel.member, BPS, axis=0)
    assert np.isnan(target[~rows]).all()
    assert np.isfinite(target[rows][:1000]).any()
    plain = chunk_targets(_panel(with_member=False), 1)
    keep = rows & np.isfinite(plain)
    assert np.array_equal(target[keep], plain[keep])


def test_s1_never_sees_a_name_before_its_first_membership_on_an_intraday_panel():
    with_name = _residuals(_panel())
    without = _residuals(_panel(drop_late=True))
    rows = LATE * BPS
    assert np.array_equal(with_name.bar[:rows, :-1], without.bar[:rows, :-1], equal_nan=True)
    assert np.isnan(with_name.bar[:rows, -1]).all()
    assert np.isnan(with_name.fwd[:rows, -1]).all()
    assert np.isnan(with_name.fwd[450 * BPS :, 0]).all()


def test_the_session_calendar_gives_one_member_row_per_session_in_the_panels_session_dates():
    from src.intelligence.research import snapshot

    panel = _panel()
    dates = snapshot.session_dates(panel)
    assert len(dates) == SESSIONS == panel.member.shape[0]
    mask = membership.member_mask(dates[:5], ["s0"], {dates[0].astype(object): frozenset({"s0"})})
    assert mask.shape == (5, 1) and not mask[0, 0] and mask[1:, 0].all()
