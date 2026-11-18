"""IC targets on a membership panel are NaN for non-members (todo 609 I1)."""

import dataclasses

import numpy as np

from src.intelligence.measure.targets import chunk_targets
from src.intelligence.research import panel as panel_mod


def _panel(member):
    n, m = 12, 2
    close = 100 + np.arange(n * m, dtype=float).reshape(n, m)
    panel = panel_mod.daily_panel(close, opens=close, volume=np.ones((n, m)))
    return dataclasses.replace(panel, member=member)


def test_non_member_cells_are_nan_and_member_cells_equal_the_unmasked_target():
    member = np.ones((12, 2), dtype=bool)
    member[4:8, 1] = False
    masked = chunk_targets(_panel(member), 2)
    plain = chunk_targets(_panel(None), 2)
    assert np.isnan(masked[4:8, 1]).all()
    keep = np.ones_like(member)
    keep[4:8, 1] = False
    assert np.array_equal(masked[keep], plain[keep], equal_nan=True)


def test_without_a_member_array_the_target_is_unchanged():
    assert np.isfinite(chunk_targets(_panel(None), 2)[:5]).all()
