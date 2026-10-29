"""Contribution kernels (phase 187 plan 14 Task 1): exact identities and the counterfactual
measures on cheap fake value functions. Pure numpy; no database."""

import numpy as np
import pytest

from src.intelligence.research import contribution as c


def _data(seed=0, n=40, m=12, k=4, holes=True):
    rng = np.random.default_rng(seed)
    terms = rng.standard_normal((n, m, k))
    target = rng.standard_normal((n, m))
    if holes:
        terms[rng.random((n, m)) < 0.2] = np.nan  # unscored cells
        terms[:, :, 1][rng.random((n, m)) < 0.1] = np.nan  # an absent member of a scored cell
        target[rng.random((n, m)) < 0.05] = np.nan
    return terms, target


def _cov(forecast, target):
    scored = np.isfinite(forecast) & np.isfinite(target)
    rows = scored.sum(1)
    rbar = np.where(rows > 0, np.where(scored, target, 0).sum(1) / np.maximum(rows, 1), 0)
    return float(
        (np.where(scored, forecast, 0) * np.where(scored, target - rbar[:, None], 0)).sum()
        / scored.sum()
    )


def test_member_terms_sum_to_the_forecast_covariance_exactly():
    terms, target = _data()
    per_member, total = c.attribution(terms, target)
    forecast = np.where(np.isfinite(terms).any(2), np.nansum(terms, axis=2), np.nan)
    assert total == pytest.approx(_cov(forecast, target), rel=1e-12)
    assert per_member.sum() == pytest.approx(total, rel=1e-12)


def test_group_totals_equal_the_sum_of_their_members():
    terms, target = _data(1)
    per, total = c.attribution(terms, target)
    groups = c.group_totals(per, ["a", "b", "a", "b"])
    assert groups["a"] == pytest.approx(per[0] + per[2]) and sum(groups.values()) == pytest.approx(
        total
    )


def test_attribution_of_no_scored_cell_is_nan():
    per, total = c.attribution(np.full((3, 3, 2), np.nan), np.zeros((3, 3)))
    assert np.isnan(per).all() and np.isnan(total)


def _additive(weights):
    return lambda subset: float(sum(weights[i] for i in subset))


def test_shapley_efficiency_and_null_player_on_an_additive_game():
    w = [3.0, 0.0, 1.5, -0.5]
    phi = c.shapley_exact(_additive(w), 4)
    assert phi == pytest.approx(w)
    assert phi.sum() == pytest.approx(_additive(w)((0, 1, 2, 3)) - 0.0)


def test_shapley_symmetry_for_duplicated_families():
    def value(s):
        return 1.0 if (0 in s or 1 in s) else 0.0

    phi = c.shapley_exact(value, 3)
    assert phi[0] == pytest.approx(phi[1]) and phi[2] == pytest.approx(0.0)
    assert phi.sum() == pytest.approx(1.0)


def test_sampled_shapley_agrees_with_exact_within_its_error_and_is_seeded():
    rng = np.random.default_rng(3)
    pair = rng.standard_normal((6, 6))

    def value(s):
        return float(sum(pair[i, j] for i in s for j in s))

    exact = c.shapley_exact(value, 6)
    est, se = c.shapley_sampled(value, 6, samples=4000, seed=7)
    assert np.all(np.abs(est - exact) < 4 * se + 1e-9)
    again, _ = c.shapley_sampled(value, 6, samples=4000, seed=7)
    assert np.array_equal(est, again)


def test_leave_one_out_shows_the_drop_on_the_signal_carrier_only():
    def value(s):
        return 5.0 if 2 in s else 0.1 * len(s)

    drop = c.leave_one_out(value, 4)
    assert drop[2] == pytest.approx(4.7) and np.all(np.delete(drop, 2) == 0.0)


def test_uniqueness_is_zero_for_a_linear_combination_and_one_for_orthogonal():
    rng = np.random.default_rng(0)
    a, b = rng.standard_normal((2, 500))
    u = c.uniqueness(np.stack([a, b, a + 2 * b], axis=1))
    assert np.all(u < 1e-9)
    centred = rng.standard_normal((500, 3))
    centred -= centred.mean(axis=0)
    assert np.all(c.uniqueness(np.linalg.qr(centred)[0]) > 0.99)


def test_effective_breadth_is_k_for_orthogonal_and_one_for_identical():
    rng = np.random.default_rng(1)
    centred = rng.standard_normal((400, 4))
    centred -= centred.mean(axis=0)
    ortho = np.linalg.qr(centred)[0] * 20
    assert c.effective_breadth(ortho) == pytest.approx(4.0, rel=1e-6)
    x = rng.standard_normal(400)
    assert c.effective_breadth(np.stack([x, x, x], axis=1)) == pytest.approx(1.0)


def test_sign_stability_is_the_modal_sign_share():
    w = np.array([[1.0, -1.0], [2.0, 1.0], [0.5, 1.0], [-1.0, np.nan]])
    out = c.sign_stability(w)
    assert out[0] == pytest.approx(0.75) and out[1] == pytest.approx(2 / 3)


def test_clusters_read_only_the_rows_given():
    rng = np.random.default_rng(2)
    base = rng.standard_normal((300, 2))
    z = np.column_stack([base[:, 0], base[:, 0] + 0.01 * rng.standard_normal(300), base[:, 1]])
    labels = c.correlation_clusters(z, 0.9)
    assert labels[0] == labels[1] != labels[2]
    poisoned = z.copy()
    poisoned[200:] = rng.standard_normal((100, 3))  # future rows differ
    assert np.array_equal(
        c.correlation_clusters(poisoned[:200], 0.9), c.correlation_clusters(z[:200], 0.9)
    )


# ---------------------------------------------------------------------------
# Applied member terms: the combiner's own additive decomposition of its forecast
# ---------------------------------------------------------------------------

from src.intelligence.research.combiner import EqualWeight, RidgeSpec  # noqa: E402


def _stack(seed=0, n=300, m=30, k=3, holes=0.0):
    rng = np.random.default_rng(seed)
    base = rng.standard_normal((n, m, 1))
    stack = base + rng.standard_normal((n, m, k))
    target = 0.3 * base[:, :, 0] + rng.standard_normal((n, m))
    if holes:
        stack[rng.random(stack.shape) < holes] = np.nan
    return stack, target


def _assert_identity(combiner, stack, target):
    forecast = combiner.combine(stack, target)
    terms = combiner.member_terms(stack, target)
    finite = np.isfinite(forecast)
    assert finite.any()
    summed = np.nansum(terms, axis=2)
    assert np.allclose(summed[finite], forecast[finite], rtol=1e-12, atol=1e-12)
    assert np.isfinite(terms).any(axis=2)[finite].all()  # every predicted cell has terms
    assert not np.isfinite(terms).any(axis=2)[~finite].any()  # and no other cell does


@pytest.mark.parametrize("min_members", [None, 2])
@pytest.mark.parametrize("holes", [0.0, 0.15])
def test_equal_weight_terms_sum_to_combine(min_members, holes):
    stack, target = _stack(holes=holes)
    _assert_identity(EqualWeight((1.0, -1.0, 1.0), min_members=min_members), stack, target)


@pytest.mark.parametrize("min_members", [None, 2])
@pytest.mark.parametrize("holes", [0.0, 0.1])
def test_ridge_terms_sum_to_combine(min_members, holes):
    stack, target = _stack(1, holes=holes)
    spec = RidgeSpec(
        window_rows=100, refit_rows=20, penalty=1.0, embargo=2, min_obs=50, min_members=min_members
    )
    _assert_identity(spec, stack, target)


def test_combine_is_unchanged_by_asking_for_terms():
    stack, target = _stack(2, holes=0.1)
    spec = RidgeSpec(window_rows=100, refit_rows=20, penalty=1.0, embargo=2, min_obs=50)
    before = spec.combine(stack, target)
    spec.member_terms(stack, target)
    spec.fold_weights(stack, target)
    assert np.array_equal(before, spec.combine(stack, target), equal_nan=True)


def test_ridge_fold_weights_have_one_row_per_refit_and_feed_sign_stability():
    stack, target = _stack(3)
    spec = RidgeSpec(window_rows=100, refit_rows=20, penalty=1.0, embargo=2, min_obs=50)
    weights = spec.fold_weights(stack, target)
    assert weights.shape[1] == 3 and weights.shape[0] >= 8
    assert np.all(c.sign_stability(weights) >= 0.5)


def test_attribution_of_a_real_book_sums_to_its_forecast_covariance():
    stack, target = _stack(4, holes=0.1)
    spec = RidgeSpec(
        window_rows=100, refit_rows=20, penalty=1.0, embargo=2, min_obs=50, min_members=2
    )
    terms = spec.member_terms(stack, target)
    per, total = c.attribution(terms, target)
    forecast = spec.combine(stack, target)
    assert per.sum() == pytest.approx(total, rel=1e-12)
    assert total == pytest.approx(_cov(forecast, target), rel=1e-9)


# ---------------------------------------------------------------------------
# account(): the block a book test records
# ---------------------------------------------------------------------------


def _block_inputs(n_families, members_per_family=2):
    rng = np.random.default_rng(5)
    k = n_families * members_per_family
    terms = rng.standard_normal((60, 10, k))
    target = rng.standard_normal((60, 10))
    fams = [f"f{i // members_per_family}" for i in range(k)]
    keys = [f"{f}.m{i}" for i, f in enumerate(fams)]
    return terms, target, keys, fams


def test_required_subsets_by_family_count():
    assert c.required_subsets(1, 12) == []
    assert c.required_subsets(2, 12) == [(0,), (1,)] and len(c.required_subsets(3, 12)) == 3
    four = c.required_subsets(4, 12)  # every nonempty proper subset: 2^4 - 2
    assert len(four) == 14 and four[0] == (0,) and four[-1] == (1, 2, 3)
    assert len(c.required_subsets(9, 8)) == 9  # above the APR exact limit: leave-one-out only


def test_single_family_book_has_attribution_uniqueness_and_breadth_only():
    terms, target, keys, fams = _block_inputs(1)
    block = c.account(terms, target, keys, fams, 2.0, {}, exact_max_families=12)
    assert "lofo" not in block and "shapley" not in block
    assert block["headline"]["n_families"] == 1 and block["headline"]["lofo_max_t_drop"] is None
    assert block["attribution"]["total"] == pytest.approx(
        sum(block["attribution"]["members"].values())
    )


def test_four_family_book_records_lofo_exact_shapley_and_headline():
    terms, target, keys, fams = _block_inputs(4)
    weights = [3.0, 1.0, 0.0, -1.0]  # an additive game over families
    subset_t = {s: float(sum(weights[i] for i in s)) for s in c.required_subsets(4, 12)}
    block = c.account(terms, target, keys, fams, 3.0, subset_t, exact_max_families=12)
    assert block["shapley"]["method"] == "exact"
    assert list(block["shapley"]["values"].values()) == pytest.approx(weights)
    assert block["lofo"]["f0"]["t_drop"] == pytest.approx(3.0)
    assert block["headline"]["lofo_max_t_drop"] == pytest.approx(3.0)
    assert block["pnl_split"]["sum"] == pytest.approx(3.0)
    assert set(block["attribution"]["groups"]) == {"f0", "f1", "f2", "f3"}


def test_above_the_caps_shapley_is_not_computed_and_says_why():
    terms, target, keys, fams = _block_inputs(9, 1)
    subset_t = {s: 1.0 for s in c.required_subsets(9, 8)}
    block = c.account(terms, target, keys, fams, 2.0, subset_t, exact_max_families=8)
    assert block["shapley"]["method"] == "not_computed" and "families" in block["shapley"]["reason"]
    assert "lofo" in block


def test_sign_stability_feeds_the_headline_minimum():
    terms, target, keys, fams = _block_inputs(2)
    folds = np.array([[1.0, 1.0, -1.0, 1.0], [1.0, -1.0, -1.0, 1.0], [1.0, 1.0, -1.0, 1.0]])
    block = c.account(
        terms,
        target,
        keys,
        fams,
        1.0,
        {(0,): 0.5, (1,): 0.2},
        exact_max_families=12,
        fold_weights=folds,
    )
    assert block["headline"]["sign_stability_min"] == pytest.approx(2 / 3)


def test_a_constant_member_does_not_crash_breadth_or_uniqueness():
    rng = np.random.default_rng(0)
    z = np.column_stack([rng.standard_normal(100), np.zeros(100), rng.standard_normal(100)])
    assert np.isnan(c.effective_breadth(z))
    assert c.uniqueness(z).shape == (3,)


def test_cells_with_an_absent_member_are_left_out_of_uniqueness_and_breadth():
    terms, target, keys, fams = _block_inputs(1, 3)
    present = np.ones(terms.shape, dtype=bool)
    present[:, :5, 1] = False  # member 1 absent on half the names
    zeroed = np.where(present, terms, 0.0)  # absent members contribute 0 to the forecast
    left_out = c.account(
        zeroed, target, keys, fams, 1.0, {}, exact_max_families=12, present=present
    )
    as_zero_signal = c.account(zeroed, target, keys, fams, 1.0, {}, exact_max_families=12)
    assert left_out["effective_breadth"] != as_zero_signal["effective_breadth"]
    assert left_out["attribution"]["total"] == as_zero_signal["attribution"]["total"]
