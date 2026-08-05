import numpy as np

from services.ic_engine import _build_regime_passes, _cluster_features


def test_correlated_pairs_cluster_together():
    """Two perfectly-correlated pairs + one independent feature -> 3 clusters."""
    rng = np.random.default_rng(0)
    n = 100
    a = rng.standard_normal(n)
    b = rng.standard_normal(n)
    c = rng.standard_normal(n)
    # pair1: a and a (identical), pair2: b and b, independent: c
    X_nd = np.column_stack([a, a, b, b, c])
    labels = _cluster_features(X_nd, cluster_max_corr=0.70)
    assert labels[0] == labels[1]  # pair1 same cluster
    assert labels[2] == labels[3]  # pair2 same cluster
    assert len(set(labels)) == 3  # 3 distinct clusters


def test_single_feature():
    """Single column -> length-1 label array."""
    X_nd = np.random.default_rng(1).standard_normal((50, 1))
    labels = _cluster_features(X_nd, cluster_max_corr=0.70)
    assert labels.shape == (1,)
    assert len(set(labels)) == 1


def test_all_identical_features():
    """All columns identical -> single cluster."""
    col = np.random.default_rng(2).standard_normal(50)
    X_nd = np.column_stack([col] * 5)
    labels = _cluster_features(X_nd, cluster_max_corr=0.70)
    assert len(set(labels)) == 1


# ---------------------------------------------------------------------------
# Phase 151 Plan 02: widen the symbol_hmm regime_passes gate via the new
# alpha.ensemble.cluster_regime_conditioned APR key (migration 286).
#
# regime_passes construction was extracted from _compute_symbol_tf into the
# pure, DB-free _build_regime_passes helper (Phase 151 Plan 02 simplify pass)
# specifically so these tests can assert on it directly without a live DB
# connection -- _compute_symbol_tf itself opens real short-lived connections
# internally and is not a practical unit-test target.
# ---------------------------------------------------------------------------


def _synthetic_pass_inputs():
    """Minimal synthetic (regime_aligned_market, distinct_regimes,
    regime_aligned) inputs -- regime_aligned deliberately uses a DIFFERENT
    label ("ranging") than regime_aligned_market ("trending_up") since in
    production these are genuinely different arrays whenever cross_sectional
    is True (market_regimes label vs feature_vectors.regime label)."""
    regime_aligned_market = np.array(["trending_up"] * 10)
    distinct_regimes = ["trending_up"]
    regime_aligned = np.array(["ranging"] * 10)
    return regime_aligned_market, distinct_regimes, regime_aligned


def test_symbol_hmm_pass_runs_when_cluster_regime_conditioned_true():
    """cross_sectional=True, dual_write_symbol_hmm=False,
    cluster_regime_conditioned=True: regime_passes gets a second entry whose
    resolved_scope is the literal "symbol_hmm"."""
    regime_aligned_market, distinct_regimes, regime_aligned = _synthetic_pass_inputs()
    regime_passes = _build_regime_passes(
        regime_aligned_market,
        distinct_regimes,
        regime_aligned,
        cross_sectional=True,
        dual_write_symbol_hmm=False,
        cluster_regime_conditioned=True,
        primary_resolved_scope="cross_sectional",
    )
    assert len(regime_passes) == 2
    assert regime_passes[1][2] == "symbol_hmm"


def test_symbol_hmm_pass_not_duplicated_when_both_flags_true():
    """Both dual_write_symbol_hmm=True and cluster_regime_conditioned=True:
    regime_passes still has length 2 -- the `or` must not double-append."""
    regime_aligned_market, distinct_regimes, regime_aligned = _synthetic_pass_inputs()
    regime_passes = _build_regime_passes(
        regime_aligned_market,
        distinct_regimes,
        regime_aligned,
        cross_sectional=True,
        dual_write_symbol_hmm=True,
        cluster_regime_conditioned=True,
        primary_resolved_scope="cross_sectional",
    )
    assert len(regime_passes) == 2
    assert regime_passes[1][2] == "symbol_hmm"
    scope_counts = [p[2] for p in regime_passes].count("symbol_hmm")
    assert scope_counts == 1, "the `or` must not double-append a second symbol_hmm entry"


def test_no_symbol_hmm_pass_when_both_flags_false():
    """Both flags False: regime_passes has length 1, preserving today's
    pre-Phase-151 behavior."""
    regime_aligned_market, distinct_regimes, regime_aligned = _synthetic_pass_inputs()
    regime_passes = _build_regime_passes(
        regime_aligned_market,
        distinct_regimes,
        regime_aligned,
        cross_sectional=True,
        dual_write_symbol_hmm=False,
        cluster_regime_conditioned=False,
        primary_resolved_scope="cross_sectional",
    )
    assert len(regime_passes) == 1


def test_cluster_ids_differ_across_symbol_hmm_states():
    """Behavioral proof clustering is actually regime-sensitive, not just a
    pass-count no-op: construct two feature columns that are near-uncorrelated
    under one HMM-state mask and near-perfectly correlated under another, and
    assert _cluster_features returns a DIFFERENT number of distinct cluster
    ids for the two state-masked slices. This is the behavioral claim the
    whole plan rests on -- a passing pass-count test alone does not prove the
    second stratification axis changes what gets clustered together.
    """
    rng = np.random.default_rng(3)
    n = 200
    # State A: two independent columns -> 2 distinct clusters expected.
    a_state_a = rng.standard_normal(n)
    b_state_a = rng.standard_normal(n)
    # State B: b is a's near-perfect copy (tiny noise) -> 1 cluster expected.
    a_state_b = rng.standard_normal(n)
    b_state_b = a_state_b + rng.standard_normal(n) * 0.001

    X_state_a = np.column_stack([a_state_a, b_state_a])
    X_state_b = np.column_stack([a_state_b, b_state_b])

    labels_state_a = _cluster_features(X_state_a, cluster_max_corr=0.70)
    labels_state_b = _cluster_features(X_state_b, cluster_max_corr=0.70)

    assert len(set(labels_state_a)) == 2, "independent columns must form 2 distinct clusters"
    assert len(set(labels_state_b)) == 1, "near-perfectly-correlated columns must form 1 cluster"
    assert len(set(labels_state_a)) != len(set(labels_state_b)), (
        "cluster count must differ across the two HMM-state-masked slices -- "
        "proof that clustering is regime-sensitive, not a fixed pass-count no-op"
    )
