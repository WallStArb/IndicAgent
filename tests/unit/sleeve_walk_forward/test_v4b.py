"""V4b: IC shrinkage prior sizing (pre-reg D7)."""

import numpy as np

from scripts.analysis.sleeve_walk_forward.v4b import compare_priors

RAW = {"alpha.ensemble.ic_input": "ic_shrunk", "alpha.ensemble.min_passing_features": "2"}


def _row(feature, symbol, sharpe, lower=0.02, regime="hi", lookahead=1):
    pooled = symbol == "POOLED"
    return {
        "feature_name": feature,
        "symbol": symbol,
        "tf": "1d",
        "regime": regime,
        "lookahead_bars": lookahead,
        "training_window_end": np.datetime64("2025-12-24"),
        "n_independent": 500,
        "ic_sharpe_hac": sharpe,
        "ic_sign": 1,
        "ic_ci_lower": lower,
        "ic_ci_upper": lower + 0.05,
        "reliable": True,
        "regime_scope": "cross_sectional" if pooled else "per_symbol",
        "is_pooled": pooled,
        "passes_walkforward": True,
        "passes_fdr": True,
    }


F2G = {"a": "g", "b": "g", "c": "g"}


def test_identical_priors_when_there_are_no_per_symbol_rows():
    rows = [_row("a", "POOLED", 0.30), _row("b", "POOLED", 0.20), _row("c", "POOLED", 0.10)]
    out = compare_priors(rows, F2G, RAW, labels=["hi"])
    hi = out["strata"]["hi"]
    assert hi["production"] == hi["harness"] and hi["quality_rank_corr"] == 1.0
    assert out["sets_differ"] is False


def test_per_symbol_rows_move_the_production_prior_only():
    pooled = [_row("a", "POOLED", 0.30), _row("b", "POOLED", 0.20), _row("c", "POOLED", 0.10)]
    # Many strongly negative per-symbol rows drag production's leave-one-out prior down.
    per_symbol = [_row(f, f"S{i}", -0.8) for i in range(50) for f in ("a", "b", "c")]
    out = compare_priors(pooled + per_symbol, F2G, RAW, labels=["hi"])
    shrunk = out["ic_shrunk_examples"]["hi"]
    assert all(shrunk[f]["production"] < shrunk[f]["harness"] for f in ("a", "b", "c"))
    assert set(out["strata"]["hi"]) >= {"production", "harness", "only_production", "only_harness"}
