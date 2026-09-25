"""V5 canary controls (pre-reg section 10)."""

import numpy as np

from scripts.analysis.sleeve_walk_forward.results import RefitOutput, StratumWeights
from scripts.analysis.sleeve_walk_forward.v5 import check_refits


def _row(feature, h=1, sign=1, lower=0.05, reliable=True, fdr=None, regime="hi"):
    return {
        "feature_name": feature,
        "regime": regime,
        "lookahead_bars": h,
        "ic_value": 0.3,
        "ic_sign": sign,
        "ic_ci_lower": lower,
        "reliable": reliable,
        "passes_ci_gate": lower > 0,
        "passes_fdr": fdr,
    }


def _refit(rows, strata=None):
    return RefitOutput(np.datetime64("2015-01-02"), strata or {}, {}, rows, 0)


def _noise(n_pass, n_total):
    return [_row("canary_noise_gaussian", fdr=i < n_pass, lower=-0.1) for i in range(n_total)]


def test_pass_when_placebo_detected_and_noise_quiet():
    rows = [_row("canary_acausal_placebo"), _row("canary_acausal_placebo", h=5, lower=-0.01)]
    out = check_refits([_refit(rows + _noise(2, 100))], fast=1, fdr_alpha=0.05)
    assert out["v5_pass"]
    # The slow-horizon miss is reported, not gating.
    assert out["placebo_hit_rate_by_lookahead"]["5"] == {"hits": 0, "cells": 1}


def test_one_fast_placebo_miss_fails():
    rows = [_row("canary_acausal_placebo"), _row("canary_acausal_placebo", regime="lo", lower=0.0)]
    out = check_refits([_refit(rows + _noise(0, 50))], fast=1, fdr_alpha=0.05)
    assert not out["detection_ok"] and not out["v5_pass"]
    assert out["placebo_misses"][0]["regime"] == "lo"


def test_unreliable_placebo_cell_is_not_gated():
    rows = [
        _row("canary_acausal_placebo"),
        _row("canary_acausal_placebo", lower=-1, reliable=False),
    ]
    assert check_refits([_refit(rows + _noise(0, 50))], fast=1, fdr_alpha=0.05)["detection_ok"]


def test_noise_fdr_rate_above_alpha_fails():
    rows = [_row("canary_acausal_placebo")] + _noise(20, 100)
    out = check_refits([_refit(rows)], fast=1, fdr_alpha=0.05)
    assert not out["noise_ok"] and out["noise_binomial_p"] < 0.05


def test_rows_without_fdr_flag_are_not_counted():
    rows = [_row("canary_acausal_placebo")] + _noise(1, 40) + [_row("canary_noise_uniform")] * 5
    out = check_refits([_refit(rows)], fast=1, fdr_alpha=0.05)
    assert out["noise_fdr_flagged"] == 40


def test_weighted_canary_fails():
    s = StratumWeights(["canary_noise_uniform", "x"], np.ones(2), np.ones(2), "ic", 2.0)
    rows = [_row("canary_acausal_placebo")] + _noise(0, 50)
    out = check_refits([_refit(rows, {"hi": s})], fast=1, fdr_alpha=0.05)
    assert not out["never_weighted_ok"] and not out["v5_pass"]


def test_no_placebo_cells_fails_rather_than_passing_vacuously():
    out = check_refits([_refit(_noise(0, 50))], fast=1, fdr_alpha=0.05)
    assert not out["detection_ok"]


def test_containing_lookahead_is_the_smallest_label_spanning_the_placebo():
    from scripts.analysis.sleeve_walk_forward.v5 import containing_lookahead

    assert containing_lookahead([1, 2, 5, 10]) == 2
    assert containing_lookahead([1, 3, 10]) == 3
