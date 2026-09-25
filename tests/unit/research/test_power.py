"""Exact power-decision primitives (D-12, D-23): b_max, early-stopped replicates, curtailment."""

import math
from fractions import Fraction

import numpy as np
import pytest

from src.intelligence.research.power import (
    ReplicateOutcome,
    b_max,
    curtail,
    replicate_passes,
)


def _brute(k, alpha, m):
    bar = Fraction(str(alpha)) / m
    best = -1
    for b in range(0, k + 1):
        if Fraction(1 + b, 1 + k) < bar:
            best = b
    return best


def test_b_max_known_values():
    assert b_max(4461, 0.05, 30) == 6
    assert b_max(599, 0.05, 30) == -1
    assert b_max(600, 0.05, 30) == 0


def test_b_max_matches_brute_force():
    for k in range(1, 6001, 7):
        assert b_max(k, 0.05, 30) == _brute(k, 0.05, 30), k
    for k in (599, 1199, 1799, 2399):
        assert b_max(k, 0.05, 30) == _brute(k, 0.05, 30)
        assert (Fraction(1, 600) * (1 + k)).denominator == 1


class _Counter:
    def __init__(self, null):
        self.null = null
        self.calls = []

    def __call__(self, k):
        self.calls.append(k)
        return float(self.null[k])


def test_early_stop_equals_full_count():
    rng = np.random.default_rng(0)
    for _ in range(500):
        k = int(rng.integers(50, 2001))
        null = rng.normal(size=k)
        s_obs = float(rng.normal(1.0, 1.0))
        bmax = int(rng.integers(-1, 20))
        counter = _Counter(null)
        out = replicate_passes(s_obs, np.arange(k), counter, bmax, np.random.default_rng(1))
        full = int((null >= s_obs).sum())
        assert out.passed == (full <= bmax)
        assert not out.aborted
        seen = int((null[counter.calls] >= s_obs).sum())
        if not out.passed:
            assert seen == bmax + 1
            if counter.calls:
                assert null[counter.calls[-1]] >= s_obs  # stopped on the deciding exceedance
        else:
            assert len(counter.calls) == k


def test_visit_order_is_seeded_permutation():
    null = np.linspace(-1, 1, 300)
    shifts = np.arange(300) * 26
    lookup = {int(s): v for s, v in zip(shifts, null)}
    a, b = [], []
    replicate_passes(0.5, shifts, lambda s: a.append(s) or lookup[s], 3, np.random.default_rng(9))
    replicate_passes(0.5, shifts, lambda s: b.append(s) or lookup[s], 3, np.random.default_rng(9))
    assert a == b
    assert a == list(np.random.default_rng(9).permutation(shifts)[: len(a)])


def test_stop_aborts_and_curtail_ignores_aborted():
    out = replicate_passes(
        0.0,
        np.arange(100),
        lambda k: -1.0,
        5,
        np.random.default_rng(0),
        stop=lambda: True,
        stop_check_every=10,
    )
    assert out.aborted and not out.passed
    outcomes = [ReplicateOutcome(False, 0, 3, aborted=True)] + [ReplicateOutcome(True, 0, 1)] * 2
    decision = curtail(iter(outcomes), replicates=2, min_power=0.5)
    assert decision.powered and decision.passes == 1


def test_curtail_equals_fixed_r():
    rng = np.random.default_rng(3)
    for _ in range(300):
        seq = rng.random(100) < rng.uniform(0.2, 0.8)
        consumed = []

        def gen(seq=seq, consumed=consumed):
            for passed in seq:
                consumed.append(passed)
                yield ReplicateOutcome(bool(passed), 0, 1)

        decision = curtail(gen(), replicates=100, min_power=0.5)
        assert decision.powered == (seq.sum() >= 50)
        cum_pass = np.cumsum(seq)
        cum_fail = np.cumsum(~seq)
        first = int(np.flatnonzero((cum_pass >= 50) | (cum_fail >= 51))[0]) + 1
        assert len(consumed) == first == decision.decided_after


def test_curtail_needs_exact_ceiling():
    decision = curtail(iter([ReplicateOutcome(True, 0, 1)] * 34), replicates=100, min_power=0.335)
    assert decision.powered and decision.passes == math.ceil(Fraction("0.335") * 100)


def test_curtail_raises_when_undecided():
    with pytest.raises(ValueError):
        curtail(iter([ReplicateOutcome(True, 0, 1)] * 10), replicates=100, min_power=0.5)
