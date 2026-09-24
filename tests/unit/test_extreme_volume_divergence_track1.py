"""H-A Track 1 (docs/plans/2026-09-06-extreme-volume-divergence-confirmed-reversal-prereg.md)."""

import numpy as np
import pytest

from scripts.analysis._date_panel import Panel
from scripts.analysis.extreme_volume_divergence_track1 import (
    PASS_RULE,
    diurnal_masks,
    h_a_statistic,
    qualifying_fraction,
    run_track1,
    verdict,
)


def test_h_a_sign_and_domain():
    low = np.array([0, 5, 0, 3, 0])
    high = np.array([4, 0, 0, 2, 7])
    vz = np.array([-1.0, -1.0, 2.0, 1.0, np.nan])
    got = h_a_statistic(low, high, vz)
    # fresh low on light volume -> +1 (upside reversal warning); fresh high on light volume -> -1
    assert got[0] == 1.0 and got[1] == -1.0
    # outside bar (both extremes), non-extreme bar, missing volume_z: undefined
    assert np.isnan(got[2]) and np.isnan(got[3]) and np.isnan(got[4])


def test_qualifying_fraction_needs_by_rejection_and_positive_ic():
    table = [
        {"ic": 0.05, "p": 1e-6},
        {"ic": -0.05, "p": 1e-6},
        {"ic": 0.01, "p": 0.5},
        {"ic": 0.04, "p": 1e-5},
    ]
    assert qualifying_fraction(table, alpha=0.05) == pytest.approx(2 / 4)


GOOD = dict(
    ci_lower=0.001, null_p=0.01, sub_ics=[0.01, 0.02, 0.005], qual_frac=0.2, family_ic=0.004
)


def test_verdict_pass_when_all_five_hold():
    assert verdict(**GOOD)["pass"] is True


@pytest.mark.parametrize(
    "override",
    [
        {"ci_lower": 0.0},
        {"null_p": 0.05},
        {"sub_ics": [0.01, -0.001, 0.02]},
        {"qual_frac": 0.099},
        {"family_ic": 0.0029},
    ],
)
def test_verdict_fails_when_any_criterion_fails(override):
    out = verdict(**{**GOOD, **override})
    assert out["pass"] is False and not all(out["criteria"].values())


def test_pass_rule_pins_prereg_constants():
    assert PASS_RULE == {
        "alpha": 0.05,
        "qualifying_floor": 0.10,
        "ic_min": 0.003,
        "n_subperiods": 3,
    }


def test_diurnal_masks_use_new_york_session_time():
    ts = np.array(
        ["2024-03-01T14:45", "2024-03-01T16:30", "2024-03-01T16:45", "2024-03-01T20:45"],
        dtype="datetime64[m]",
    )  # UTC; EST (UTC-5): 9:45, 11:30, 11:45, 15:45
    morning, afternoon = diurnal_masks(ts)
    assert morning.tolist() == [True, True, False, False]
    assert afternoon.tolist() == [False, False, True, True]


def _synthetic(signal, seed=0, n_sym=30, n_days=240, per_day=4):
    rng = np.random.default_rng(seed)
    n = n_sym * n_days * per_day
    sym = np.repeat(np.arange(n_sym), n_days * per_day)
    days = np.tile(np.repeat(np.arange(n_days), per_day), n_sym)
    dates = 20200101 + days
    score = np.where(rng.random(n) < 0.3, rng.standard_normal(n), np.nan)
    ret = rng.standard_normal(n) + signal * np.nan_to_num(score)
    return Panel(sym, dates, score, ret, min_rows=50, max_workers=2)


def test_planted_signal_passes_and_noise_does_not():
    strong = run_track1(_synthetic(0.5), n_boot=60, n_null=60, seed=1)
    noise = run_track1(_synthetic(0.0, seed=2), n_boot=60, n_null=60, seed=1)
    assert strong["verdict"]["pass"] is True
    assert noise["verdict"]["pass"] is False
    assert len(strong["sub_ics"]) == 3
