"""Unit tests: todo 084 leave-one-family-out ensemble ablation protocol.

All statistical kernels in scripts/ops/alpha/ops_ensemble_ablation.py are pure
module-level functions tested here without any DB or Kafka (project unit-test rule).
The load-bearing properties under test are statistical-correctness properties:
identical code path for baseline and ablated arms, sign convention, complete-gating,
pooling equivalence with ensemble_ic_engine._aggregate_pooled_series, degenerate-arm
handling, and the SQL invariants (executable returns filter, OOS >= boundary).
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

_project_root = Path(__file__).parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

_scripts_alpha_dir = _project_root / "scripts" / "ops" / "alpha"
if str(_scripts_alpha_dir) not in sys.path:
    sys.path.insert(0, str(_scripts_alpha_dir))

from ops_ensemble_ablation import (
    _BASELINE_ARM,
    _CONTROL_FAMILY,
    signed_weights_from_rows,
    weight_mass_fraction,
    zero_family,
)

# ---------------------------------------------------------------------------
# Task 1: weight-vector kernels
# ---------------------------------------------------------------------------


def test_signed_weights_sign_convention():
    """sign comes from stored ensemble_weights.ic_sharpe: negative ic_sharpe flips
    the weight (sign-symmetric challenger case); non-negative keeps it positive
    (champion case, where all eligible features have ic_ci_lower > 0)."""
    weights = np.array([0.2, 0.3, 0.5])
    ic_sharpes = np.array([0.8, -0.4, 0.0])
    signed = signed_weights_from_rows(weights, ic_sharpes)
    assert signed.dtype == np.float64
    np.testing.assert_allclose(signed, [0.2, -0.3, 0.5])


def test_zero_family_zeroes_only_that_family_and_copies():
    signed = np.array([0.2, -0.3, 0.5])
    groups = ["momentum", "volume", "momentum"]
    ablated = zero_family(signed, groups, "momentum")
    np.testing.assert_allclose(ablated, [0.0, -0.3, 0.0])
    # input untouched (must be a copy, or arms contaminate each other)
    np.testing.assert_allclose(signed, [0.2, -0.3, 0.5])


def test_zero_family_absent_family_is_identity():
    signed = np.array([0.2, -0.3])
    ablated = zero_family(signed, ["momentum", "volume"], _CONTROL_FAMILY)
    np.testing.assert_allclose(ablated, signed)


def test_weight_mass_fraction_uses_absolute_mass():
    """|-0.3| counts as mass 0.3: a contrarian feature's contribution share must not
    be understated (or netted against longs) by signed summation."""
    signed = np.array([0.2, -0.3, 0.5])
    groups = ["momentum", "volume", "momentum"]
    assert weight_mass_fraction(signed, groups, "volume") == 0.3 / 1.0
    assert weight_mass_fraction(signed, groups, "momentum") == 0.7 / 1.0
    assert weight_mass_fraction(signed, groups, _CONTROL_FAMILY) == 0.0


def test_weight_mass_fraction_zero_total_returns_zero():
    assert weight_mass_fraction(np.zeros(3), ["a", "b", "c"], "a") == 0.0


def test_baseline_arm_sentinel_is_not_a_plausible_group_name():
    assert _BASELINE_ARM == "__baseline__"


# ---------------------------------------------------------------------------
# Task 2: pooling kernel
# ---------------------------------------------------------------------------


def test_apply_complete_gate_nans_incomplete_and_copies():
    """ic_engine convention (lines 1848-1850): a return is usable only when
    complete AND finite. Gate applied pre-pooling; input untouched."""
    from ops_ensemble_ablation import apply_complete_gate

    returns = np.array([0.01, 0.02, np.nan, 0.04])
    complete = np.array([True, False, True, True])
    gated = apply_complete_gate(returns, complete)
    assert np.isfinite(gated[0]) and gated[0] == 0.01
    assert np.isnan(gated[1])  # complete=False censored even though value present
    assert np.isnan(gated[2])  # already NaN stays NaN
    assert gated[3] == 0.04
    assert returns[1] == 0.02  # input not mutated


def test_pool_means_by_bar_matches_aggregate_pooled_series():
    """Equivalence oracle: our vectorized pooling must produce the exact same
    cross-symbol means as ensemble_ic_engine._aggregate_pooled_series (the
    alpha_ensemble_ic POOLED convention, Pitfall 5: group before averaging),
    including None/NaN-skipping semantics. Two symbols, three bars, one missing
    value and one bar with a single member."""
    from datetime import UTC, datetime

    from ops_ensemble_ablation import pool_means_by_bar

    from services.ensemble_ic_engine import _aggregate_pooled_series

    t1 = datetime(2026, 1, 5, 14, 30, tzinfo=UTC)
    t2 = datetime(2026, 1, 5, 14, 35, tzinfo=UTC)
    t3 = datetime(2026, 1, 5, 14, 40, tzinfo=UTC)
    oracle_rows = [
        {
            "bar_ts": t1,
            "regime_label": "low_bull",
            "alpha_score": 1.0,
            "return_fast": 0.01,
            "return_mid": None,
            "return_slow": None,
            "return_extended": None,
        },
        {
            "bar_ts": t1,
            "regime_label": "low_bull",
            "alpha_score": 3.0,
            "return_fast": 0.03,
            "return_mid": None,
            "return_slow": None,
            "return_extended": None,
        },
        {
            "bar_ts": t2,
            "regime_label": "low_bull",
            "alpha_score": 5.0,
            "return_fast": None,
            "return_mid": None,
            "return_slow": None,
            "return_extended": None,
        },
        {
            "bar_ts": t3,
            "regime_label": "low_bull",
            "alpha_score": 2.0,
            "return_fast": 0.02,
            "return_mid": None,
            "return_slow": None,
            "return_extended": None,
        },
        {
            "bar_ts": t3,
            "regime_label": "low_bull",
            "alpha_score": 4.0,
            "return_fast": 0.06,
            "return_mid": None,
            "return_slow": None,
            "return_extended": None,
        },
    ]
    oracle = _aggregate_pooled_series(oracle_rows, "5m")  # sorted by bar_ts

    bar_ts_arr = np.array([t1, t1, t2, t3, t3], dtype=object)
    unique_ts, bar_idx = np.unique(bar_ts_arr, return_inverse=True)
    alpha = np.array([1.0, 3.0, 5.0, 2.0, 4.0])
    ret_fast = np.array([0.01, 0.03, np.nan, 0.02, 0.06])

    pooled_alpha = pool_means_by_bar(bar_idx, len(unique_ts), alpha)
    pooled_fast = pool_means_by_bar(bar_idx, len(unique_ts), ret_fast)

    assert list(unique_ts) == [r["bar_ts"] for r in oracle]
    np.testing.assert_allclose(pooled_alpha, [r["alpha_score"] for r in oracle])
    # oracle returns None for the all-missing bar; ours returns NaN
    oracle_fast = [np.nan if r["return_fast"] is None else r["return_fast"] for r in oracle]
    np.testing.assert_allclose(pooled_fast, oracle_fast)


def test_pool_means_by_bar_all_nan_bar_is_nan_not_zero():
    """A bar with zero finite members must pool to NaN (unmeasurable), never a
    silent 0.0 -- 0.0 would enter downstream rank correlations as fake data."""
    from ops_ensemble_ablation import pool_means_by_bar

    bar_idx = np.array([0, 0, 1])
    values = np.array([np.nan, np.nan, 5.0])
    pooled = pool_means_by_bar(bar_idx, 2, values)
    assert np.isnan(pooled[0])
    assert pooled[1] == 5.0


# ---------------------------------------------------------------------------
# Task 3: arm IC measurement + reconstruction check
# ---------------------------------------------------------------------------


def _monotone_series(n: int) -> tuple[np.ndarray, np.ndarray]:
    """Perfectly rank-aligned alpha/returns pair: Spearman IC exactly 1.0."""
    rng = np.random.default_rng(42)
    alpha = np.sort(rng.normal(size=n))
    returns = np.sort(rng.normal(size=n))
    return alpha, returns


def test_compute_arm_ic_perfect_rank_alignment():
    from ops_ensemble_ablation import compute_arm_ic

    alpha, returns = _monotone_series(300)
    arm = compute_arm_ic(alpha, returns, stride=1, min_reliable_n=100)
    assert arm is not None
    assert arm.n == 300
    assert arm.ic == 1.0
    # CI machinery present, never a bare correlation (project rule)
    assert arm.ci_lower is not None and arm.ci_upper is not None
    assert arm.ci_lower <= arm.ic <= arm.ci_upper


def test_clamp_ci_to_ic_absorbs_boundary_noise_silently():
    """Float64 tanh/arctanh round-trip noise (e.g. the ~8e-11 case observed at
    IC=1.0 in _monotone_series(300)) is within tolerance -- clamps silently,
    same behavior as the pre-fix inline np.clip."""
    from ops_ensemble_ablation import _clamp_ci_to_ic

    lower, upper = _clamp_ci_to_ic(ci_lower=0.5, ci_upper=0.9 - 1e-11, ic=0.9)
    assert lower == 0.5
    assert upper == 0.9


def test_clamp_ci_to_ic_raises_on_material_violation():
    """A violation far larger than float64 noise (e.g. a sign error in
    _fisher_z_ci) must raise loudly, not silently clamp into a tight, misleading
    range around ic -- 'silent wrong answers are worse than loud crashes'."""
    from ops_ensemble_ablation import _clamp_ci_to_ic

    with pytest.raises(ValueError, match="ci_upper"):
        _clamp_ci_to_ic(ci_lower=0.1, ci_upper=0.5, ic=0.9)


def test_compute_arm_ic_stride_subsamples_before_gating():
    """stride = max(subsample_min_stride, lookahead_bars) applied to the pooled
    series (ensemble_ic_engine lines 770-773): 300 bars at stride 60 -> 5 obs,
    below min_reliable_n -> None, even though the raw series was long enough."""
    from ops_ensemble_ablation import compute_arm_ic

    alpha, returns = _monotone_series(300)
    assert compute_arm_ic(alpha, returns, stride=60, min_reliable_n=100) is None


def test_compute_arm_ic_nan_pairs_excluded_from_n():
    from ops_ensemble_ablation import compute_arm_ic

    alpha, returns = _monotone_series(300)
    returns = returns.copy()
    returns[:150] = np.nan
    arm = compute_arm_ic(alpha, returns, stride=1, min_reliable_n=100)
    assert arm is not None
    assert arm.n == 150


def test_compute_arm_ic_degenerate_series_is_none_not_zero():
    """Zeroing the only weighted family makes the composite constant; Spearman on a
    constant is UNDEFINED. Must return None (rendered DEGENERATE), never IC=0.0 --
    an IC of 0.0 would fake 'family removal made the model exactly neutral'."""
    from ops_ensemble_ablation import compute_arm_ic

    returns = np.linspace(-1.0, 1.0, 300)
    constant_alpha = np.zeros(300)
    assert compute_arm_ic(constant_alpha, returns, stride=1, min_reliable_n=100) is None


def test_compute_arm_ic_identical_code_path_for_identical_inputs():
    """The zero-delta property the control family relies on: an arm whose weights
    equal the baseline's must produce the bit-identical ArmIC (same function, same
    inputs). Guards against any future baseline-only shortcut."""
    from ops_ensemble_ablation import compute_arm_ic

    alpha, returns = _monotone_series(300)
    a = compute_arm_ic(alpha, returns, stride=3, min_reliable_n=50)
    b = compute_arm_ic(alpha.copy(), returns.copy(), stride=3, min_reliable_n=50)
    assert a == b


def test_reconstruction_check_pass_and_mismatch():
    from ops_ensemble_ablation import reconstruction_check

    stored = np.array([1.0, 2.0, 3.0, 4.0])
    n, diff, ok = reconstruction_check(stored.copy(), stored, tol=0.01)
    assert (n, diff, ok) == (4, 0.0, True)
    off = stored + np.array([0.0, 0.0, 0.0, 1.0])  # 1.0 abs diff vs std ~1.118
    n, diff, ok = reconstruction_check(off, stored, tol=0.01)
    assert n == 4 and diff is not None and diff > 0.01 and ok is False


def test_reconstruction_check_no_stored_overlap_is_skipped_not_failed():
    """Stored ensemble_alpha may not cover OOS bars (e.g. trainer ran before those
    bars existed): zero overlap is SKIPPED (ok=True, diff None), not a mismatch."""
    from ops_ensemble_ablation import reconstruction_check

    recomputed = np.array([1.0, 2.0])
    stored = np.array([np.nan, np.nan])
    assert reconstruction_check(recomputed, stored, tol=0.01) == (0, None, True)


# ---------------------------------------------------------------------------
# Task 4: SQL invariants + config + panel preparation
# ---------------------------------------------------------------------------


def test_fetch_sql_statistical_invariants():
    """The three non-negotiable measurement invariants, pinned as SQL text so a
    refactor cannot silently drop them: executable returns filter, OOS >= boundary,
    complete_* columns fetched for gating. Plus weight_version scoping on the
    stored-baseline join (never blend another variant's alpha into the check)."""
    from ops_ensemble_ablation import build_stratum_fetch_sql

    sql = build_stratum_fetch_sql(["momentum_z_fast", "obv_z"])
    assert "return_type = 'executable_open_to_open'" in sql
    assert "fv.bar_ts >= $4" in sql
    for scale in ("fast", "mid", "slow", "extended"):
        assert f"fr.return_{scale}" in sql
        assert f"fr.complete_{scale}" in sql
    assert 'fv."momentum_z_fast"' in sql and 'fv."obv_z"' in sql
    assert "ea.weight_version = $3" in sql
    # trainer's exact stratum join: market_regimes on (asset_class, tf, ts)
    assert "mr.asset_class = 'equity'" in sql
    assert "ORDER BY fv.bar_ts, fv.symbol" in sql


def test_weights_and_strata_sql_scope_to_universe_and_version():
    from ops_ensemble_ablation import _FAMILIES_SQL, _STRATA_SQL, _WEIGHTS_SQL

    assert "symbol = 'UNIVERSE'" in _STRATA_SQL
    assert "weight_version = $1" in _STRATA_SQL
    assert "ew.symbol = 'UNIVERSE'" in _WEIGHTS_SQL
    assert "ew.weight_version = $1" in _WEIGHTS_SQL
    assert "freg.group_name" in _WEIGHTS_SQL
    assert "group_name" in _FAMILIES_SQL


def test_ablation_config_from_apr_defaults_match_engines():
    """Fallback defaults must be byte-identical to EnsembleICConfig.from_apr's --
    a divergent fallback would silently measure with different gates on a DB
    missing a key."""
    from ops_ensemble_ablation import AblationConfig

    config = AblationConfig.from_apr({})
    assert config.subsample_min_stride == 5
    assert config.min_reliable_n == 100
    assert config.fdr_alpha == 0.05
    assert config.lookaheads == {"fast": 1, "mid": 5, "slow": 20, "extended": 60}


def test_ablation_config_from_apr_reads_keys():
    from ops_ensemble_ablation import AblationConfig

    config = AblationConfig.from_apr(
        {
            "alpha.ic.subsample_min_stride": 7,
            "alpha.ic.min_reliable_n": 150,
            "alpha.ic.fdr_alpha": 0.10,
            "alpha.ic.lookahead.fast": 2,
            "alpha.ic.lookahead.mid": 10,
            "alpha.ic.lookahead.slow": 40,
            "alpha.ic.lookahead.extended": 120,
        }
    )
    assert config.subsample_min_stride == 7
    assert config.min_reliable_n == 150
    assert config.fdr_alpha == 0.10
    assert config.lookaheads == {"fast": 2, "mid": 10, "slow": 40, "extended": 120}


def test_prepare_stratum_arrays_trainer_conventions():
    """X follows ensemble_trainer.py lines 823-826 exactly: NULL -> 0.0, float32.
    Returns are complete-gated per row; stored alpha NaN where the LEFT JOIN
    found no ensemble_alpha row."""
    from datetime import UTC, datetime

    from ops_ensemble_ablation import prepare_stratum_arrays

    t1 = datetime(2026, 1, 5, 14, 30, tzinfo=UTC)
    t2 = datetime(2026, 1, 5, 14, 35, tzinfo=UTC)
    rows = [
        {
            "symbol": "SPY",
            "bar_ts": t1,
            "f_a": 1.5,
            "f_b": None,
            "return_fast": 0.01,
            "return_mid": 0.02,
            "return_slow": 0.03,
            "return_extended": 0.04,
            "complete_fast": True,
            "complete_mid": False,
            "complete_slow": True,
            "complete_extended": True,
            "stored_alpha": 0.7,
        },
        {
            "symbol": "TLT",
            "bar_ts": t2,
            "f_a": -0.5,
            "f_b": 2.0,
            "return_fast": None,
            "return_mid": 0.05,
            "return_slow": None,
            "return_extended": 0.06,
            "complete_fast": True,
            "complete_mid": True,
            "complete_slow": True,
            "complete_extended": False,
            "stored_alpha": None,
        },
    ]
    bar_ts_arr, X, gated, stored = prepare_stratum_arrays(rows, ["f_a", "f_b"])
    assert X.dtype == np.float32
    np.testing.assert_allclose(X, [[1.5, 0.0], [-0.5, 2.0]])
    assert list(bar_ts_arr) == [t1, t2]
    assert gated["fast"][0] == 0.01
    assert np.isnan(gated["mid"][0])  # complete_mid=False censored
    assert np.isnan(gated["fast"][1])  # NULL return
    assert gated["mid"][1] == 0.05
    assert np.isnan(gated["extended"][1])  # complete_extended=False censored
    assert stored[0] == 0.7 and np.isnan(stored[1])


from ops_ensemble_ablation import (
    _FLAG_ABSENT,
    _FLAG_BASELINE_UNMEASURABLE,
    _FLAG_CONTROL_BREACH,
    _FLAG_DEGENERATE,
    AblationConfig,
    AttributionRow,
    apply_delta_fdr,
    compute_stratum_attribution,
)

# ---------------------------------------------------------------------------
# Task 5: attribution assembly
# ---------------------------------------------------------------------------

_TEST_CONFIG = AblationConfig(
    subsample_min_stride=1,
    min_reliable_n=50,
    fdr_alpha=0.05,
    lookahead_fast=1,
    lookahead_mid=1,
    lookahead_slow=1,
    lookahead_extended=1,
)


def _one_symbol_panel(n_bars: int = 400):
    """Single-symbol panel (pooling is identity): 2 features, feature 0
    ('momentum') is a perfect rank predictor of returns, feature 1 ('volume') is
    seeded noise. bar_idx = arange since one row per bar."""
    rng = np.random.default_rng(7)
    returns = rng.normal(size=n_bars)
    predictor = returns.copy()  # rank-identical to returns
    noise = rng.normal(size=n_bars)
    X = np.column_stack([predictor, noise]).astype(np.float32)
    bar_idx = np.arange(n_bars)
    pooled_returns = {s: returns.astype(np.float64) for s in ("fast", "mid", "slow", "extended")}
    return X, bar_idx, n_bars, pooled_returns


def test_attribution_zeroing_predictive_family_drops_ic():
    X, bar_idx, n_bars, pooled_returns = _one_symbol_panel()
    rows = compute_stratum_attribution(
        tf="5m",
        regime="low_bull",
        families=["momentum", "volume", "control"],
        group_names=["momentum", "volume"],
        signed_weights=np.array([1.0, 0.05]),
        X=X,
        bar_idx=bar_idx,
        n_bars=n_bars,
        pooled_returns_by_scale=pooled_returns,
        config=_TEST_CONFIG,
    )
    fast = {r.family: r for r in rows if r.scale == "fast"}
    baseline = fast["__baseline__"]
    assert baseline.ic_baseline is not None and baseline.ic_baseline > 0.9
    momentum = fast["momentum"]
    # removing the predictive family must reduce IC: positive marginal contribution
    assert momentum.delta_ic is not None and momentum.delta_ic > 0.5
    assert momentum.ic_ablated is not None and momentum.ic_ablated < 0.3
    assert momentum.diff_p is not None
    # noise family removal barely moves IC
    volume = fast["volume"]
    assert volume.delta_ic is not None and abs(volume.delta_ic) < 0.1
    # both arms measured on the identical bar set
    assert momentum.n_obs == baseline.n_obs == volume.n_obs


def test_attribution_absent_family_is_flagged_not_computed():
    X, bar_idx, n_bars, pooled_returns = _one_symbol_panel()
    rows = compute_stratum_attribution(
        tf="5m",
        regime="low_bull",
        families=["momentum", "volume", "control"],
        group_names=["momentum", "volume"],
        signed_weights=np.array([1.0, 0.05]),
        X=X,
        bar_idx=bar_idx,
        n_bars=n_bars,
        pooled_returns_by_scale=pooled_returns,
        config=_TEST_CONFIG,
    )
    control = [r for r in rows if r.family == "control" and r.scale == "fast"][0]
    assert control.flag == _FLAG_ABSENT
    assert control.n_features_zeroed == 0
    assert control.delta_ic is None and control.ic_ablated is None


def test_attribution_control_family_with_weight_is_governance_breach():
    X, bar_idx, n_bars, pooled_returns = _one_symbol_panel()
    rows = compute_stratum_attribution(
        tf="5m",
        regime="low_bull",
        families=["momentum", "control"],
        group_names=["momentum", "control"],  # canary somehow carries weight
        signed_weights=np.array([1.0, 0.05]),
        X=X,
        bar_idx=bar_idx,
        n_bars=n_bars,
        pooled_returns_by_scale=pooled_returns,
        config=_TEST_CONFIG,
    )
    control = [r for r in rows if r.family == "control" and r.scale == "fast"][0]
    assert control.flag == _FLAG_CONTROL_BREACH
    assert control.n_features_zeroed == 1
    assert control.delta_ic is not None  # still measured: near-zero delta expected


def test_attribution_sole_family_zeroed_is_degenerate_not_zero_ic():
    X, bar_idx, n_bars, pooled_returns = _one_symbol_panel()
    rows = compute_stratum_attribution(
        tf="5m",
        regime="low_bull",
        families=["momentum"],
        group_names=["momentum", "momentum"],
        signed_weights=np.array([1.0, 0.05]),
        X=X,
        bar_idx=bar_idx,
        n_bars=n_bars,
        pooled_returns_by_scale=pooled_returns,
        config=_TEST_CONFIG,
    )
    momentum = [r for r in rows if r.family == "momentum" and r.scale == "fast"][0]
    assert momentum.flag == _FLAG_DEGENERATE
    assert momentum.ic_ablated is None and momentum.delta_ic is None


def test_attribution_unmeasurable_baseline_short_circuits_scale():
    """min_reliable_n above the bar count: baseline unmeasurable -> exactly one
    row per scale (the flagged baseline row), no family rows computed against a
    nonexistent baseline."""
    X, bar_idx, n_bars, pooled_returns = _one_symbol_panel(n_bars=30)
    rows = compute_stratum_attribution(
        tf="5m",
        regime="low_bull",
        families=["momentum", "volume"],
        group_names=["momentum", "volume"],
        signed_weights=np.array([1.0, 0.05]),
        X=X,
        bar_idx=bar_idx,
        n_bars=n_bars,
        pooled_returns_by_scale=pooled_returns,
        config=_TEST_CONFIG,
    )
    fast_rows = [r for r in rows if r.scale == "fast"]
    assert len(fast_rows) == 1
    assert fast_rows[0].family == "__baseline__"
    assert fast_rows[0].flag == _FLAG_BASELINE_UNMEASURABLE


def test_apply_delta_fdr_one_corpus_wide_pass():
    """One multipletests family across ALL delta p-values (project convention);
    rows without a diff_p (baseline/absent/degenerate) stay None."""
    base = dict(
        tf="5m",
        regime="low_bull",
        scale="fast",
        n_features_zeroed=1,
        weight_mass_zeroed=0.5,
        n_obs=200,
        ic_baseline=0.5,
        ci_lower=0.4,
        ci_upper=0.6,
        ic_ablated=0.1,
        delta_ic=0.4,
        bh_adjusted_p=None,
        delta_passes_fdr=None,
        flag="",
    )
    rows = [
        AttributionRow(family="momentum", diff_p=0.001, **base),
        AttributionRow(family="volume", diff_p=0.90, **base),
        AttributionRow(family="__baseline__", diff_p=None, **base),
    ]
    corrected = apply_delta_fdr(rows, fdr_alpha=0.05)
    assert corrected[0].delta_passes_fdr is True
    assert corrected[0].bh_adjusted_p is not None
    assert corrected[1].delta_passes_fdr is False
    assert corrected[2].bh_adjusted_p is None and corrected[2].delta_passes_fdr is None


def test_apply_delta_fdr_empty_is_noop():
    assert apply_delta_fdr([], fdr_alpha=0.05) == []
