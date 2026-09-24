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


def test_output_keeps_the_audit_tables():
    out = run_track1(_synthetic(0.5), n_boot=20, n_null=20, seed=1)
    row = out["per_symbol"][0]
    assert {"symbol_id", "n", "ic", "p", "by_reject", "bh_reject"} <= set(row)
    assert len(out["per_symbol"]) == out["n_family"]
    assert out["negative_qualifiers"] >= 0


def test_no_blocks_names_the_missing_symbols():
    from scripts.analysis.extreme_volume_divergence_track1 import _concat_blocks

    with pytest.raises(SystemExit, match="SPYY"):
        _concat_blocks([None], requested=["SPYY"])


# --- H-B confirmed_reversal (forward-scan anchor), pre-reg "H-B statistic" ---------------------


def _hb(low_flags, high_flags, vz, k, warmup=0):
    from scripts.analysis.extreme_volume_divergence_track1 import h_b_statistic

    low = np.where(np.array(low_flags, bool), 0, 5)
    high = np.where(np.array(high_flags, bool), 0, 5)
    return h_b_statistic(low, high, np.array(vz, float), k_confirm=k, warmup_bars=warmup)


def test_h_b_fires_k_bars_after_a_low_with_the_leg_mean():
    got = _hb([0, 1, 0, 0, 0, 0], [0] * 6, [9.0, 9.0, 1.0, 2.0, 3.0, 4.0], k=3)
    # anchor at 1 (low); fires at i = 4 with mean(vz[2..4]); anchor bar's own volume excluded
    assert np.isnan(got[[0, 1, 2, 3, 5]]).all()
    assert got[4] == pytest.approx(2.0)


def test_h_b_high_anchor_is_negative():
    got = _hb([0] * 4, [1, 0, 0, 0], [0.0, 1.0, 2.0, 3.0], k=2)
    assert got[2] == pytest.approx(-1.5)


def test_h_b_outside_bar_hard_resets_the_anchor():
    got = _hb([1, 0, 1, 0, 0], [0, 0, 1, 0, 0], [0.0, 1.0, 1.0, 1.0, 1.0], k=3)
    assert np.isnan(got).all()  # bar 2 is a tie: the low anchored at 0 never reaches k=3


def test_h_b_new_same_side_extreme_restarts_the_leg():
    got = _hb([1, 0, 1, 0, 0, 0], [0] * 6, [0.0, 5.0, 0.0, 1.0, 1.0, 1.0], k=3)
    assert np.isnan(got[3]) and got[5] == pytest.approx(1.0)


def test_h_b_opposite_extreme_replaces_the_anchor():
    got = _hb([1, 0, 0, 0], [0, 1, 0, 0], [0.0, 0.0, 2.0, 4.0], k=2)
    assert np.isnan(got[2]) and got[3] == pytest.approx(-3.0)


def test_h_b_warmup_bars_never_set_an_anchor():
    got = _hb([1, 0, 0, 0, 0], [0] * 5, [0.0, 1.0, 1.0, 1.0, 1.0], k=3, warmup=2)
    assert np.isnan(got).all()


def test_h_b_missing_volume_in_the_leg_is_undefined():
    got = _hb([1, 0, 0, 0], [0] * 4, [0.0, 1.0, np.nan, 1.0], k=3)
    assert np.isnan(got[3])


def _h_b_prereg_loop(low_flag, high_flag, vz, k, warmup):
    """The pre-registration's pseudocode, transcribed literally."""
    n = len(vz)
    out = np.full(n, np.nan)
    anchor_idx = anchor_type = None
    for i in range(n):
        lo, hi = (low_flag[i], high_flag[i]) if i >= warmup else (False, False)
        tie = lo and hi
        if lo and not tie:
            anchor_idx, anchor_type = i, "low"
        elif hi and not tie:
            anchor_idx, anchor_type = i, "high"
        elif tie:
            anchor_idx, anchor_type = None, None
        if anchor_idx is not None and i - anchor_idx == k:
            leg = vz[anchor_idx + 1 : anchor_idx + k + 1]
            sign = 1.0 if anchor_type == "low" else -1.0
            out[i] = sign * leg.mean() if np.isfinite(leg).all() else np.nan
    return out


@pytest.mark.parametrize("seed", range(20))
def test_h_b_matches_the_prereg_pseudocode(seed):
    from scripts.analysis.extreme_volume_divergence_track1 import h_b_statistic

    rng = np.random.default_rng(seed)
    n = 400
    low_flag = rng.random(n) < 0.12
    high_flag = rng.random(n) < 0.12
    vz = rng.standard_normal(n)
    vz[rng.random(n) < 0.02] = np.nan
    for k in (1, 2, 3, 5):
        want = _h_b_prereg_loop(low_flag, high_flag, vz, k, warmup=40)
        got = h_b_statistic(
            np.where(low_flag, 0, 3), np.where(high_flag, 0, 3), vz, k_confirm=k, warmup_bars=40
        )
        np.testing.assert_allclose(got, want, equal_nan=True)


def test_reported_only_run_has_no_verdict():
    from scripts.analysis.extreme_volume_divergence_track1 import run_reported

    out = run_reported(_synthetic(0.5))
    assert set(out) == {"family_ic", "sub_ics", "n_family"} and len(out["sub_ics"]) == 3
