"""V4 fidelity comparison (pre-reg section 10)."""

import numpy as np

from scripts.analysis.sleeve_walk_forward.v4 import compare_rows


def _row(feature, ic=0.1, lower=0.05, cluster=1, reliable=True):
    return {
        "feature_name": feature,
        "regime": "hi",
        "lookahead_bars": 1,
        "ic_value": ic,
        "ic_sharpe": 0.2,
        "ic_sharpe_hac": 0.2,
        "ic_sortino": 0.3,
        "ic_win_rate": 0.6,
        "sign_hit_rate": 0.55,
        "magnitude_conditional_ic": 0.1,
        "p_value": 1e-4,
        "n_independent": 900,
        "cluster_id": cluster,
        "reliable": reliable,
        "passes_walkforward": True,
        "wf_fold_count": 5,
        "wf_pass_count": 4,
        "ic_sign": 1,
        "ic_sharpe_n_windows": 30,
        "ic_ci_lower": lower,
        "ic_ci_upper": lower + 0.1,
        "passes_ci_gate": True,
    }


def test_identical_rows_match():
    rows = [_row("a"), _row("b")]
    out = compare_rows(rows, [dict(r) for r in rows])
    assert out["deterministic_ok"] and out["keys_equal"]
    assert out["rng"]["ic_ci_lower"]["max_abs"] == 0.0


def test_deterministic_float_beyond_tolerance_fails():
    prod = [_row("a", ic=0.1)]
    out = compare_rows([_row("a", ic=0.1 + 2e-6)], prod)
    assert not out["deterministic_ok"] and out["deterministic"]["ic_value"]["n_bad"] == 1


def test_float32_storage_rounding_passes():
    out = compare_rows([_row("a", ic=0.123456789)], [_row("a", ic=float(np.float32(0.123456789)))])
    assert out["deterministic_ok"]


def test_integer_field_must_match_exactly():
    out = compare_rows([_row("a", cluster=2)], [_row("a", cluster=3)])
    assert not out["deterministic_ok"] and out["deterministic"]["cluster_id"]["n_bad"] == 1


def test_rng_fields_are_reported_not_gated():
    out = compare_rows([_row("a", lower=0.05)], [_row("a", lower=0.06)])
    assert out["deterministic_ok"]
    assert abs(out["rng"]["ic_ci_lower"]["max_abs"] - 0.01) < 1e-12


def test_key_mismatch_is_reported():
    out = compare_rows([_row("a"), _row("b")], [_row("a"), _row("c")])
    assert not out["keys_equal"]
    assert out["only_harness"] == [["b", "hi", 1]] and out["only_production"] == [["c", "hi", 1]]
