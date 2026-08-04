"""Executed proof that the Phase 170 Plan 07 parent-list reorder is inert.

Plan 07 repointed ops_interaction_primitives_pilot.py's lineage read from
feature_registry.parent_features (a bare TEXT[] preserving whatever order the row
was written in) to a concept_registry/concept_parent join returning
array_agg(p.name ORDER BY p.name) -- alphabetical order, which is NOT necessarily
the original insertion order (2 of the 8 live interaction primitives actually
differ, live-verified). concept_parent carries no ordinality column by design
(migration 283's header: "no consumer of lineage depends on parent order"), so this
module is the standing evidence for that claim, not just a plan-doc assertion.

Two independent invariance checks, matching the two places parent order could
matter in the pilot's measurement path:
  1. partial_spearman_ic's OLS residualisation against a 2-column control design
     matrix -- residuals depend only on the controls' COLUMN SPACE, which is
     identical under column permutation (proven here on correlated, not
     independent, controls so the residualisation actually removes shared
     variance and would show an order effect if one existed).
  2. _compute_not_null_mask's boolean AND over the two parent columns' isnan()
     masks -- `&` is commutative, so swapping parent_1/parent_2 cannot change the
     result.

If either test ever fails, the alphabetical array_agg is unsafe and the correct
fix is an explicit ordinality column on concept_parent (seeded from
unnest(parent_features) WITH ORDINALITY in a follow-up migration) -- not silently
accepting a changed statistic.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

_project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_project_root))
sys.path.insert(0, str(_project_root / "scripts" / "ops" / "alpha"))

from ops_interaction_primitives_pilot import _compute_not_null_mask  # noqa: E402

from src.intelligence.statistics.ic_math import partial_spearman_ic  # noqa: E402


def test_partial_ic_invariant_under_parent_swap():
    """partial_spearman_ic(x, y, controls) must return the SAME (partial_ic,
    p_value, n) triple whether the two control columns are passed as
    [parent_1, parent_2] or [parent_2, parent_1].

    Controls are deliberately CORRELATED with each other and with x/y (not
    independent noise) so the residualisation actually removes shared variance --
    an order-sensitive bug would show up as a materially different partial_ic
    here, not be masked by both controls carrying zero real signal.
    """
    rng = np.random.default_rng(2170)
    n = 3000
    z1 = rng.normal(size=n)
    # z2 correlated with z1 (shared latent factor) plus its own noise -- controls
    # are not independent of each other, matching real parent-atomic pairs
    # (e.g. ret_lag_fast/atr_z, both derived from the same price series).
    z2 = 0.6 * z1 + rng.normal(scale=0.8, size=n)
    s = rng.normal(size=n)  # genuine incremental signal beyond z1/z2
    x = z1 + z2 + 0.5 * s + rng.normal(scale=0.1, size=n)
    y = z1 - 0.3 * z2 + 0.5 * s + rng.normal(scale=0.1, size=n)

    controls_forward = np.column_stack([z1, z2])
    controls_swapped = controls_forward[:, ::-1]

    ic_forward, p_forward, n_forward = partial_spearman_ic(
        x, y, controls_forward, condition_max=1000.0
    )
    ic_swapped, p_swapped, n_swapped = partial_spearman_ic(
        x, y, controls_swapped, condition_max=1000.0
    )

    assert n_forward == n_swapped == n
    assert np.isclose(ic_forward, ic_swapped, rtol=0.0, atol=1e-9)
    assert np.isclose(p_forward, p_swapped, rtol=0.0, atol=1e-9)
    # Sanity: this is a real, measurable partial IC, not a degenerate NaN case
    # that would trivially satisfy the invariance assertions above.
    assert not np.isnan(ic_forward)
    assert ic_forward > 0.1


def test_not_null_mask_invariant_under_parent_swap():
    """_compute_not_null_mask(dataset, fname, p1, p2) must equal
    _compute_not_null_mask(dataset, fname, p2, p1) -- boolean AND over the two
    parent isnan() masks is commutative, so which column is named "parent_1" vs
    "parent_2" cannot change the resulting non-null mask. Fixture carries NaNs in
    BOTH parent columns (at different row positions) so the test would notice an
    order-sensitive implementation, not just confirm both sides are trivially
    all-True."""
    dataset = {
        "SPY": {
            "some_feature": np.array([1.0, 2.0, 3.0, 4.0, 5.0]),
            "parent_a": np.array([1.0, np.nan, 3.0, 4.0, 5.0]),
            "parent_b": np.array([1.0, 2.0, 3.0, np.nan, 5.0]),
        },
        "QQQ": {
            "some_feature": np.array([np.nan, 2.0, 3.0]),
            "parent_a": np.array([1.0, 2.0, np.nan]),
            "parent_b": np.array([1.0, np.nan, 3.0]),
        },
    }

    mask_forward = _compute_not_null_mask(dataset, "some_feature", "parent_a", "parent_b")
    mask_swapped = _compute_not_null_mask(dataset, "some_feature", "parent_b", "parent_a")

    assert set(mask_forward.keys()) == set(mask_swapped.keys()) == {"SPY", "QQQ"}
    for sym in mask_forward:
        assert np.array_equal(mask_forward[sym], mask_swapped[sym])

    # Sanity: the fixture actually has both True and False entries (not a
    # vacuously-passing all-True or all-False mask).
    assert mask_forward["SPY"].tolist() == [True, False, True, False, True]
    assert mask_forward["QQQ"].tolist() == [False, False, False]
