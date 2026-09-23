"""Unit coverage for stratified_sample() -- reproducibility, stratum balance, and
the unset-target-size guard (Phase 174 Plan 08, D-01/D-02).

Every test below exercises stratified_sample() directly against synthetic
population frames -- no database, no network, no APR reads. This proves the draw
itself is reproducible and seed-sensitive (D-02's requirement) independent of
whatever live alpha.universe.* values happen to be configured when this suite runs.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[3]))

import numpy as np
import pandas as pd
import pytest

from scripts.infrastructure.universe_expansion_stratified_sourcing import (  # noqa: E402
    exclude_set_sha256,
    stratified_sample,
)

_RESULT_COLUMNS = [
    "symbol",
    "name",
    "index_position_value",
    "cap_bucket",
    "cap_bucket_min",
    "cap_bucket_max",
]


def _make_population(n: int = 500, prefix: str = "SYM") -> pd.DataFrame:
    """500 synthetic symbols with a wide, log-spaced market-cap distribution --
    ample per-bucket capacity for a 10-decile split (~50 names/bucket), and a
    wide enough spread that bucket-ordering assertions are meaningful.
    """
    symbols = [f"{prefix}{i:04d}" for i in range(n)]
    caps = np.logspace(6, 12, n)  # $1M .. $1T, deterministic ascending spread
    return pd.DataFrame(
        {"symbol": symbols, "name": [f"Name {i}" for i in range(n)], "index_position_value": caps}
    )


def _make_shortfall_population() -> pd.DataFrame:
    """Constructs a population where pandas.qcut(q=5, duplicates="drop") produces
    exactly 4 buckets of UNEQUAL size (20/50/10/20) -- the 40-row block of
    identical index_position_value=50.0 collapses two quantile edges, leaving one bucket
    with only 10 rows. Verified empirically: this exact construction reliably
    yields bucket capacities [20, 50, 10, 20] under q=5/duplicates="drop".
    """
    caps = list(np.linspace(1, 40, 30)) + [50.0] * 40 + list(np.linspace(60, 100, 30))
    symbols = [f"SH{i:04d}" for i in range(len(caps))]
    return pd.DataFrame({"symbol": symbols, "name": symbols, "index_position_value": caps})


def _assert_bounds_correct(sample: pd.DataFrame) -> None:
    assert list(sample.columns) == _RESULT_COLUMNS
    assert (
        (sample["index_position_value"] >= sample["cap_bucket_min"])
        & (sample["index_position_value"] <= sample["cap_bucket_max"])
    ).all()


def test_reproducibility_same_seed_returns_identical_ordered_list():
    """D-02: two calls with the same population, target_size, bucket_count and
    seed return identical symbol lists in identical ORDER (list equality, not
    set equality) -- a silently-shuffled-but-same-set result would still fail
    this test.
    """
    pop = _make_population()
    first = stratified_sample(pop, target_size=50, bucket_count=10, seed=42, exclude=set())
    second = stratified_sample(pop, target_size=50, bucket_count=10, seed=42, exclude=set())
    assert list(first["symbol"]) == list(second["symbol"])


def test_seed_sensitivity_different_seed_returns_different_list():
    """A different seed must produce a different draw -- guards against a seed
    argument that is silently ignored (e.g. a hardcoded default_rng()).
    """
    pop = _make_population()
    first = stratified_sample(pop, target_size=50, bucket_count=10, seed=42, exclude=set())
    second = stratified_sample(pop, target_size=50, bucket_count=10, seed=43, exclude=set())
    assert list(first["symbol"]) != list(second["symbol"])


def test_stratum_balance_even_split_with_ample_capacity():
    """target_size=100, bucket_count=10, every bucket has ample capacity (~50
    names each) -- each bucket contributes exactly 10 symbols.
    """
    pop = _make_population()
    sample = stratified_sample(pop, target_size=100, bucket_count=10, seed=1, exclude=set())
    counts = sample["cap_bucket"].value_counts().sort_index()
    assert counts.tolist() == [10] * 10
    _assert_bounds_correct(sample)


def test_remainder_allocation_is_deterministic_not_random():
    """target_size=103, bucket_count=10 -- the remainder (3 names) goes to the
    first 3 buckets, giving 11/11/11/10/10/10/10/10/10/10. Re-running with a
    DIFFERENT seed produces the identical allocation shape (only the drawn
    symbols within each bucket change) -- allocation must not consume RNG
    draws, or it would stop being reproducible under a changed target size.
    """
    pop = _make_population()
    sample_a = stratified_sample(pop, target_size=103, bucket_count=10, seed=7, exclude=set())
    counts_a = sample_a["cap_bucket"].value_counts().sort_index().tolist()
    assert counts_a == [11, 11, 11, 10, 10, 10, 10, 10, 10, 10]

    sample_b = stratified_sample(pop, target_size=103, bucket_count=10, seed=999, exclude=set())
    counts_b = sample_b["cap_bucket"].value_counts().sort_index().tolist()
    assert counts_b == counts_a


def test_remainder_goes_to_smallest_cap_buckets():
    """The three buckets receiving the +1 remainder (target_size=103,
    bucket_count=10) are buckets 0, 1, 2 -- the smallest-cap ones, not the
    largest. This pins the direction of the deliberate design choice (down-cap
    segment gets the extra draws), not just that SOME three buckets get 11.
    """
    pop = _make_population()
    sample = stratified_sample(pop, target_size=103, bucket_count=10, seed=7, exclude=set())
    counts = sample["cap_bucket"].value_counts().sort_index()
    buckets_with_11 = sorted(counts[counts == 11].index.tolist())
    assert buckets_with_11 == [0, 1, 2]


def test_capacity_shortfall_redistributes_to_buckets_with_room():
    """A population where one bucket holds fewer names than its even-split
    allocation still returns exactly target_size symbols, with the shortfall
    absorbed by buckets that have remaining capacity. Verified construction:
    _make_shortfall_population() yields bucket capacities [20, 50, 10, 20]
    under bucket_count=5 (duplicates="drop" collapses to 4 actual buckets);
    target_size=80 forces bucket 2 (capacity 10) to be fully drawn while bucket
    1 (capacity 50) absorbs the redistributed shortfall.
    """
    pop = _make_shortfall_population()
    sample = stratified_sample(pop, target_size=80, bucket_count=5, seed=11, exclude=set())
    assert len(sample) == 80
    counts = sample["cap_bucket"].value_counts().sort_index()
    # Bucket 2 (the shortfall bucket, true capacity 10) must be fully drawn.
    shortfall_bucket = counts.idxmin()
    assert counts[shortfall_bucket] == 10
    # No bucket's draw exceeds its own true population capacity.
    true_capacities = pop.assign(
        cap_bucket=pd.qcut(pop["index_position_value"], q=5, labels=False, duplicates="drop")
    )["cap_bucket"].value_counts()
    for bucket_idx, drawn in counts.items():
        assert drawn <= true_capacities[bucket_idx]
    _assert_bounds_correct(sample)


def test_population_exhaustion_returns_all_available_without_duplicates():
    """target_size far larger than the population returns every available
    symbol without raising and without duplicates.
    """
    pop = _make_population(n=50)
    sample = stratified_sample(pop, target_size=1000, bucket_count=5, seed=3, exclude=set())
    assert len(sample) == 50
    assert sample["symbol"].nunique() == 50


def test_exclusion_applies_before_bucketing():
    """Symbols in `exclude` never appear in the result, and the bucket
    boundaries are computed over the POST-exclusion population -- constructed
    so pre- vs post-exclusion boundaries differ measurably: excluding the 30
    lowest-cap symbols out of 100 shifts bucket 0's minimum from 1.0 (the raw
    population's true minimum) to a materially higher value.
    """
    pop = _make_population(n=100).assign(index_position_value=np.linspace(1.0, 1000.0, 100))
    exclude = set(pop["symbol"].iloc[:30])

    sample = stratified_sample(pop, target_size=20, bucket_count=5, seed=5, exclude=exclude)

    assert exclude.isdisjoint(set(sample["symbol"]))

    pre_exclusion_min = pop["index_position_value"].min()
    post_exclusion_bucket0_min = sample.loc[sample["cap_bucket"] == 0, "cap_bucket_min"].iloc[0]
    assert post_exclusion_bucket0_min > pre_exclusion_min
    # The post-exclusion population's true minimum (row 30, 0-indexed) is what
    # bucket 0's floor should actually be, confirming boundaries are computed
    # over the population the draw can actually use, not the raw input.
    expected_post_exclusion_min = pop["index_position_value"].iloc[30]
    assert post_exclusion_bucket0_min == pytest.approx(expected_post_exclusion_min)


def test_unset_target_size_raises_value_error():
    """D-01: target_size=0 raises ValueError naming the parameter -- this must
    fire before any draw, not after.
    """
    pop = _make_population(n=50)
    with pytest.raises(ValueError, match="target_size"):
        stratified_sample(pop, target_size=0, bucket_count=5, seed=1, exclude=set())


def test_negative_target_size_raises_value_error():
    """D-01: a negative target_size is equally invalid, not just zero."""
    pop = _make_population(n=50)
    with pytest.raises(ValueError, match="target_size"):
        stratified_sample(pop, target_size=-1, bucket_count=5, seed=1, exclude=set())


def test_no_duplicate_symbols_in_result():
    """The returned symbol column has no repeated values, across a balanced
    draw, a remainder-allocation draw, and an exhaustion draw.
    """
    pop = _make_population()
    balanced = stratified_sample(pop, target_size=100, bucket_count=10, seed=1, exclude=set())
    assert balanced["symbol"].is_unique

    remainder = stratified_sample(pop, target_size=103, bucket_count=10, seed=7, exclude=set())
    assert remainder["symbol"].is_unique

    exhausted = stratified_sample(
        _make_population(n=50), target_size=1000, bucket_count=5, seed=3, exclude=set()
    )
    assert exhausted["symbol"].is_unique


def test_bucket_ordering_ascending_by_market_cap():
    """pandas.qcut(labels=False) assigns ascending codes by binned value --
    bucket 0's mean market cap must be strictly less than the largest bucket's,
    and per-bucket means must be monotonically non-decreasing in bucket index.
    This pins the "lowest bucket = smallest cap" direction every downstream
    document relies on.
    """
    pop = _make_population()
    sample = stratified_sample(pop, target_size=100, bucket_count=10, seed=5, exclude=set())
    means = sample.groupby("cap_bucket")["index_position_value"].mean().sort_index()
    assert means.iloc[0] < means.iloc[-1]
    diffs = means.diff().dropna()
    assert (diffs >= 0).all()


def test_bucket_bounds_carried_and_correct():
    """Every returned row's index_position_value lies within its own
    [cap_bucket_min, cap_bucket_max], and the bounds are computed over the
    post-exclusion population -- constructed so pre- vs post-exclusion bounds
    differ measurably (same construction as the exclusion test above).
    """
    pop = _make_population(n=100).assign(index_position_value=np.linspace(1.0, 1000.0, 100))
    exclude = set(pop["symbol"].iloc[:30])
    sample = stratified_sample(pop, target_size=20, bucket_count=5, seed=5, exclude=exclude)
    _assert_bounds_correct(sample)

    # Post-exclusion bound differs measurably from the pre-exclusion population
    # minimum -- same assertion shape as test_exclusion_applies_before_bucketing,
    # scoped here to the bounds-carrying contract specifically.
    pre_exclusion_min = pop["index_position_value"].min()
    bucket0_min = sample.loc[sample["cap_bucket"] == 0, "cap_bucket_min"].iloc[0]
    assert bucket0_min > pre_exclusion_min


def test_exclude_set_sha256_is_order_independent_and_content_sensitive():
    """174 review IN-06: provenance must pin the exact exclude set, not just its size."""
    assert exclude_set_sha256({"B", "A"}) == exclude_set_sha256({"A", "B"})
    assert exclude_set_sha256({"A", "B"}) != exclude_set_sha256({"A", "C"})
