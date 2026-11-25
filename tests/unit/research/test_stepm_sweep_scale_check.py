"""The sweep-scale StepM check (todo 670): the null cells' declared properties and the shipped
StepM running over them. Synthetic only; no database."""

from __future__ import annotations

import numpy as np
import pytest

from scripts.research import stepm_sweep_scale_check as chk
from src.intelligence.statistics.stepm import stepm

S = 4000


def _autocorr(x: np.ndarray, lag: int) -> float:
    x = x[np.isfinite(x)]
    x = x - x.mean()
    return float(x[lag:] @ x[:-lag] / (x @ x))


def test_block_is_mirrored_mean_zero_and_seeded_by_position():
    block = chk.null_block(S, 40, n_eff=8, tail="t5", seed=11)
    assert block.shape == (S, 80)
    np.testing.assert_array_equal(block[:, 40:], -block[:, :40])
    np.testing.assert_array_equal(block, chk.null_block(S, 40, n_eff=8, tail="t5", seed=11))
    assert not np.array_equal(block, chk.null_block(S, 40, n_eff=8, tail="t5", seed=12))
    means = np.nanmean(block[:, :40], axis=0)
    sd = np.nanstd(block[:, :40], axis=0)
    assert np.abs(means / sd).max() < 0.25  # mean zero up to sampling noise (autocorrelated)


def test_each_horizon_has_its_overlap_memory():
    block = chk.null_block(20000, 8, n_eff=0, tail="normal", seed=3)
    horizon = np.resize(np.array(chk.CELL_HORIZONS), 8)
    for col, h in enumerate(horizon):
        x = block[:, col]
        if h == 1:
            assert abs(_autocorr(x, 1)) < 0.05
        else:
            assert _autocorr(x, 1) == pytest.approx((h - 1) / h, abs=0.06)
            assert abs(_autocorr(x, h)) < 0.06  # no memory beyond the overlap


def test_group_structure_follows_n_eff():
    grouped = chk.null_block(S, 16, n_eff=4, tail="normal", seed=5)[:, :16]
    warm = grouped[chk.WARMUP_MAX :]
    corr = np.corrcoef(np.nan_to_num(warm).T)
    same = [corr[i, j] for i in range(16) for j in range(i + 1, 16) if i % 4 == j % 4]
    other = [corr[i, j] for i in range(16) for j in range(i + 1, 16) if i % 4 != j % 4]
    assert np.mean(same) > 0.5 and abs(np.mean(other)) < 0.1
    independent = chk.null_block(S, 16, n_eff=0, tail="normal", seed=5)[:, :16]
    corr = np.corrcoef(np.nan_to_num(independent[chk.WARMUP_MAX :]).T)
    assert np.abs(corr[np.triu_indices(16, 1)]).max() < 0.12


def test_warmup_is_missing_and_t_tails_are_heavier():
    block = chk.null_block(S, 30, n_eff=0, tail="t5", seed=2)[:, :30]
    assert np.isnan(block).any() and np.isnan(block[: chk.WARMUP_MAX + 1]).any()
    assert np.isfinite(block[chk.WARMUP_MAX + 1 :]).all()
    t = chk.null_block(60000, 1, n_eff=0, tail="t5", seed=4)[:, 0]
    n = chk.null_block(60000, 1, n_eff=0, tail="normal", seed=4)[:, 0]
    z = lambda x: np.nanmean(((x - np.nanmean(x)) / np.nanstd(x)) ** 4)  # noqa: E731
    assert z(t) > z(n) + 0.1


def test_sweep_scale_check_refusals():
    with pytest.raises(ValueError):
        chk.null_block(S, 5, n_eff=0, tail="cauchy", seed=1)
    with pytest.raises(ValueError):
        chk.null_block(5, 5, n_eff=0, tail="t5", seed=1)


def _recorded(seed=1, k=3):
    rng = np.random.default_rng(seed)
    x = rng.standard_normal((1200, k)) * 0.02
    x[:, 0] += 0.012  # a strong planted series
    return x


def _job(**overrides):
    base = {
        "recorded": _recorded(),
        "max_horizon": 5,
        "block_mean": 20.0,
        "reps": 200,
        "fwer": 0.05,
        "stepm_seed": 187,
        "n_cells": 0,
        "n_eff": 0,
        "tail": "normal",
        "null_seed": 9,
    }
    return base | overrides


def test_no_null_cells_reproduces_the_shipped_stepm_exactly():
    job = _job()
    got = chk.run_replicate(job)
    direct = stepm(
        job["recorded"], block_mean=20.0, max_horizon_sessions=5, reps=200, fwer=0.05, seed=187
    )
    assert got["recorded_selected"] == direct.selected.tolist()
    assert got["recorded_adjusted_p"] == direct.adjusted_p.tolist()
    assert got["false_selections"] == 0


def test_a_planted_series_survives_and_a_borderline_one_is_priced_out():
    keep = chk.run_replicate(_job(n_cells=60, n_eff=0))
    assert keep["recorded_selected"][0] is True and keep["false_selections"] == 0
    recorded = _recorded()
    recorded[:, 1] += 0.0025  # borderline
    few = chk.run_replicate(_job(recorded=recorded))
    many = chk.run_replicate(_job(recorded=recorded, n_cells=600, n_eff=0))
    assert many["recorded_adjusted_p"][1] >= few["recorded_adjusted_p"][1]


def test_summary_shares():
    replicates = [
        {
            "recorded_selected": [True, False],
            "recorded_adjusted_p": [0.01, 0.4],
            "false_selections": 0,
        },
        {
            "recorded_selected": [True, True],
            "recorded_adjusted_p": [0.02, 0.04],
            "false_selections": 1,
        },
    ]
    out = chk.summarize(replicates, ["a", "b"])
    assert out["false_selection_replicates"] == 1 and out["false_selections_total"] == 1
    assert [s["share_selected"] for s in out["series"]] == [1.0, 0.5]
    assert out["series"][1]["adjusted_p_min"] == 0.04


def test_the_block_length_covers_the_null_cells_overlap_whatever_the_recorded_horizon():
    # recorded attempts at horizon 1, null cells overlapping by up to 10 sessions: StepM must be
    # given the longer one (it refuses a block mean that does not exceed it).
    out = chk.run_replicate(_job(max_horizon=1, n_cells=20, n_eff=0, block_mean=20.0))
    assert out["false_selections"] >= 0
    with pytest.raises(ValueError, match="block_mean"):
        chk.run_replicate(_job(max_horizon=1, n_cells=20, n_eff=0, block_mean=9.0))
