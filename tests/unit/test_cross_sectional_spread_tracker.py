"""Unit tests: cross_sectional_spread_tracker's pure construction primitives -- the decile
split, tied and missing feature values (Codex review's HIGH concern), run-boundary turnover
(Pitfall 4), the cost-hurdle sweep (D-05), and APR range validation (T-167-01). Plan 04 adds
the Validation Gate 1 evaluation core, the live shuffled-ranking null's edge cases (Codex
review's HIGH concern on ties and degenerate bars), and the verdict artifact's strict-JSON
audit-trail contract.

No live DB required -- these tests exercise pure functions with synthetic in-memory inputs.
"""

from __future__ import annotations

import inspect
import json
import math
import random
import sys
from datetime import date, timedelta
from pathlib import Path

_project_root = Path(__file__).parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

import numpy as np
import pytest

from services.cross_sectional_spread_tracker import (
    attribution_verdict,
    decile_legs,
    evaluate_spread_gate,
    mean_gross_spread_over_bars,
    net_spread_by_cost_bps,
    one_way_turnover,
    shuffled_ranking_null_p,
    spread_from_legs,
    static_tilt_series,
    static_tilt_weights,
    validate_construction_config,
    write_verdict_artifact,
)

# ---------------------------------------------------------------------------
# test_decile_split (167-VALIDATION.md row 167-02-01)
# ---------------------------------------------------------------------------


def test_decile_split():
    symbols = [f"S{i:02d}" for i in range(20)]
    values = list(range(20))  # S00 lowest .. S19 highest
    result = decile_legs(symbols, values, decile_fraction=0.10)
    assert result is not None
    short_leg, long_leg = result
    assert len(short_leg) == 2
    assert len(long_leg) == 2
    assert set(short_leg) == {"S00", "S01"}
    assert set(long_leg) == {"S18", "S19"}
    assert set(short_leg).isdisjoint(set(long_leg))

    # Degenerate case: a universe of 1 symbol at decile_fraction=0.10 -- n_leg=1, n<2*n_leg.
    assert decile_legs(["A"], [1.0], decile_fraction=0.10) is None

    # n_leg=1 still passes at 3 symbols / decile_fraction=0.40 (3 >= 2*1)...
    three_syms = ["A", "B", "C"]
    three_vals = [1.0, 2.0, 3.0]
    assert decile_legs(three_syms, three_vals, decile_fraction=0.40) is not None

    # ...but 1 symbol at 0.40 does not (1 < 2*1).
    assert decile_legs(["A"], [1.0], decile_fraction=0.40) is None

    # Deterministic tie-break at the coarse level: two symbols sharing an identical feature
    # value produce the same leg assignment regardless of input order.
    tie_symbols = ["A", "B", "C", "D", "E", "F", "G", "H", "I", "J"]
    tie_values = [1.0, 1.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0]
    forward = decile_legs(tie_symbols, tie_values, decile_fraction=0.10)
    reversed_order = decile_legs(
        list(reversed(tie_symbols)), list(reversed(tie_values)), decile_fraction=0.10
    )
    assert forward == reversed_order


# ---------------------------------------------------------------------------
# test_decile_split_tied_and_missing_values (167-VALIDATION.md row 167-02-04, Codex review)
# ---------------------------------------------------------------------------


def test_decile_split_tied_and_missing_values():
    # (a) Tie ON the leg boundary: 10 symbols, decile_fraction=0.20 (n_leg=2). C and D share
    # the EXACT same feature value (2.0), which straddles the short-leg cut: sorted ascending
    # by (value, symbol) the order is A(1), C(2), D(2), E(4), F(5), G(6), H(7), I(8), J(9),
    # B(10) -- so the short leg (first 2) takes A and C, leaving D just outside.
    boundary_values = {
        "A": 1.0,
        "B": 10.0,
        "C": 2.0,
        "D": 2.0,
        "E": 4.0,
        "F": 5.0,
        "G": 6.0,
        "H": 7.0,
        "I": 8.0,
        "J": 9.0,
    }
    as_given_symbols = list(boundary_values.keys())
    as_given_values = [boundary_values[s] for s in as_given_symbols]
    reversed_symbols = list(reversed(as_given_symbols))
    reversed_values = [boundary_values[s] for s in reversed_symbols]
    shuffled_symbols = list(as_given_symbols)
    random.Random(42).shuffle(shuffled_symbols)
    shuffled_values = [boundary_values[s] for s in shuffled_symbols]

    result_as_given = decile_legs(as_given_symbols, as_given_values, decile_fraction=0.20)
    result_reversed = decile_legs(reversed_symbols, reversed_values, decile_fraction=0.20)
    result_shuffled = decile_legs(shuffled_symbols, shuffled_values, decile_fraction=0.20)

    assert result_as_given is not None
    short_leg, long_leg = result_as_given
    assert "C" in short_leg
    assert "D" not in short_leg
    assert len(short_leg) == 2
    assert len(long_leg) == 2
    assert set(short_leg).isdisjoint(set(long_leg))
    assert result_as_given == result_reversed == result_shuffled, (
        "the (feature_value, symbol) tie-break must resolve a boundary-straddling tie "
        "identically regardless of input ordering -- this is the assertion that the "
        "tie-break actually determines leg membership, not merely a stable output for a "
        "non-boundary-straddling tie"
    )

    # (b) All-tied universe: every symbol shares one identical feature value. The split is
    # still returned (not None), and since every value is equal the sort order is purely
    # alphabetical -- this degenerate input carries zero ranking information and its spread
    # is expected to be noise; this assertion pins determinism, not meaningfulness.
    all_tied_symbols = ["A", "B", "C", "D", "E", "F", "G", "H", "I", "J"]
    all_tied_values = [5.0] * 10
    result_all_tied = decile_legs(all_tied_symbols, all_tied_values, decile_fraction=0.20)
    assert result_all_tied is not None
    short_all_tied, long_all_tied = result_all_tied
    assert short_all_tied == ["A", "B"]
    assert long_all_tied == ["I", "J"]
    result_all_tied_reversed = decile_legs(
        list(reversed(all_tied_symbols)), list(reversed(all_tied_values)), decile_fraction=0.20
    )
    assert result_all_tied == result_all_tied_reversed

    # (c) Missing value: a None feature value anywhere raises ValueError naming the offending
    # symbol.
    with pytest.raises(ValueError, match="Q"):
        decile_legs(["P", "Q", "R"], [1.0, None, 3.0], decile_fraction=0.20)

    # (d) Non-finite value: NaN, +inf, and -inf each raise ValueError. Python's tuple sort on
    # a NaN key is partition-dependent and non-transitive -- it raises nothing and yields a
    # plausible-looking but arbitrary leg assignment, exactly the silent wrong answer this
    # guard exists to prevent.
    for bad_value in (float("nan"), float("inf"), float("-inf")):
        with pytest.raises(ValueError):
            decile_legs(["P", "Q", "R"], [1.0, bad_value, 3.0], decile_fraction=0.20)


# ---------------------------------------------------------------------------
# test_turnover_across_run_boundary (167-VALIDATION.md row 167-02-02, Pitfall 4 regression)
# ---------------------------------------------------------------------------


def test_turnover_across_run_boundary():
    # (a) No predecessor: turnover must be None, NOT 0.0 -- Pitfall 4's named symptom of a
    # service that treats "first bar this run" as having no predecessor.
    result = one_way_turnover(frozenset(), frozenset(), {"A", "B"}, {"C", "D"})
    assert result is None, "Pitfall 4: no-predecessor turnover must be None, never 0.0"

    # (b) Run-boundary continuity: prior legs loaded from a simulated persisted row.
    prev_long = frozenset({"A", "B"})
    prev_short = frozenset({"C", "D"})
    cur_long = frozenset({"A", "E"})
    cur_short = frozenset({"C", "D"})
    turnover = one_way_turnover(prev_long, prev_short, cur_long, cur_short)
    assert turnover == pytest.approx(0.25)
    assert turnover not in (0.0, 1.0), (
        "Pitfall 4: 0.0 and 1.0 are the two literal values that symptomize a service "
        "treating 'first bar this run' as having no predecessor"
    )

    # (c) Full rotation: entirely disjoint prior and current legs return 1.0.
    full_rotation = one_way_turnover(
        frozenset({"A", "B"}), frozenset({"C", "D"}), frozenset({"E", "F"}), frozenset({"G", "H"})
    )
    assert full_rotation == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# test_cost_hurdle_sweep (167-VALIDATION.md row 167-02-03, D-05)
# ---------------------------------------------------------------------------


def test_cost_hurdle_sweep():
    gross_spread = 0.00059  # T3's measured 5.9bp/bar fast-scale gross spread
    turnover = 0.195  # T3's measured mean one-way leg turnover
    cost_bps = [1, 3, 5, 10]

    result = net_spread_by_cost_bps(gross_spread, turnover, cost_bps)
    assert result is not None
    assert set(result.keys()) == {"1", "3", "5", "10"}
    for bps in cost_bps:
        expected = gross_spread - (bps / 10000) * turnover
        assert result[str(bps)] == pytest.approx(expected)

    # D-05: net spread survives at every tested cost floor at T3's measured turnover -- this
    # is the live-computation guard against anyone hardcoding "it survives".
    assert all(v > 0 for v in result.values())

    # A None input never fabricates a dict of zeros.
    assert net_spread_by_cost_bps(None, turnover, cost_bps) is None
    assert net_spread_by_cost_bps(gross_spread, None, cost_bps) is None


# ---------------------------------------------------------------------------
# test_config_validation (T-167-01)
# ---------------------------------------------------------------------------


def test_config_validation():
    with pytest.raises(ValueError, match="decile_fraction"):
        validate_construction_config(0.0, [1, 3, 5, 10], 40, 0.50)
    with pytest.raises(ValueError, match="decile_fraction"):
        validate_construction_config(0.6, [1, 3, 5, 10], 40, 0.50)
    with pytest.raises(ValueError, match="cost_bps"):
        validate_construction_config(0.10, [], 40, 0.50)
    with pytest.raises(ValueError, match="cost_bps"):
        validate_construction_config(0.10, [1, 0, 5], 40, 0.50)
    with pytest.raises(ValueError, match="cost_bps"):
        validate_construction_config(0.10, [1, -3, 5], 40, 0.50)
    with pytest.raises(ValueError, match="null_shuffles"):
        validate_construction_config(0.10, [1, 3, 5, 10], 0, 0.50)
    with pytest.raises(ValueError, match="attribution_max_static_r2"):
        validate_construction_config(0.10, [1, 3, 5, 10], 40, 0.0)
    with pytest.raises(ValueError, match="attribution_max_static_r2"):
        validate_construction_config(0.10, [1, 3, 5, 10], 40, 1.0)

    # Plan 01's seeded APR defaults must raise nothing.
    validate_construction_config(0.10, [1, 3, 5, 10], 40, 0.50)


# ---------------------------------------------------------------------------
# test_spread_is_flat_equal_weight (Pitfall 1 regression guard)
# ---------------------------------------------------------------------------


def test_spread_is_flat_equal_weight():
    returns_by_symbol = {"L1": 0.02, "L2": 0.00, "S1": -0.01, "S2": -0.03}
    long_leg = ["L1", "L2"]
    short_leg = ["S1", "S2"]

    result = spread_from_legs(returns_by_symbol, long_leg, short_leg)
    # mean(0.02, 0.00) - mean(-0.01, -0.03) = 0.01 - (-0.02) = 0.03. A vol-scaled
    # implementation would fail this assertion -- that is intentional: the flat version is
    # what T3 proved.
    assert result == pytest.approx(0.03)

    # A None return is skipped, never coerced to 0.0.
    returns_with_missing = {"L1": 0.02, "L2": None, "S1": -0.01, "S2": -0.03}
    result_missing = spread_from_legs(returns_with_missing, long_leg, short_leg)
    assert result_missing == pytest.approx(0.02 - (-0.02))

    # A leg with zero usable returns returns None, never a fabricated spread.
    all_missing = {"L1": None, "L2": None, "S1": -0.01, "S2": -0.03}
    assert spread_from_legs(all_missing, long_leg, short_leg) is None


# ---------------------------------------------------------------------------
# test_evaluate_gate (167-VALIDATION.md row 167-04-01)
# ---------------------------------------------------------------------------


def _gate_rows_two_scale_positive_negative(cost_tiers=(1, 3, 5, 10), n_dates=45):
    """40+ distinct cluster_id dates, 2 scales x 4 cost tiers -- enough to clear both the
    min_n=30 sufficiency floor and the 2-day-cluster bootstrap floor. `fast` gets an
    unambiguously positive pnl_r distribution (mean +0.01, nonzero variance); `slow` gets an
    unambiguously negative one (mean -0.01), so the two scales must land on opposite sides of
    the gate."""
    rows = []
    for d in range(n_dates):
        cluster_id = date(2026, 1, 1) + timedelta(days=d)
        offset = 0.001 * ((d % 5) - 2)  # symmetric per 5-day cycle -- averages to exactly 0
        for cost_bps in cost_tiers:
            rows.append(
                {
                    "scale": "fast",
                    "cost_bps": cost_bps,
                    "cluster_id": cluster_id,
                    "pnl_r": 0.01 + offset,
                }
            )
            rows.append(
                {
                    "scale": "slow",
                    "cost_bps": cost_bps,
                    "cluster_id": cluster_id,
                    "pnl_r": -0.01 + offset,
                }
            )
    return rows


def test_evaluate_gate():
    rows = _gate_rows_two_scale_positive_negative()
    verdicts = evaluate_spread_gate(
        rows, min_n=30, bootstrap_max_n=5000, bootstrap_batch=1000, bootstrap_random_state=42
    )

    # All 8 cells (2 scales x 4 cost tiers), each with the renamed field set -- the SHAPE
    # CONSTRAINT rename from alpha_scorer.py's own module docstring is the specific thing
    # under test here, not merely a formality.
    assert len(verdicts) == 8
    for v in verdicts:
        assert set(v.keys()) == {
            "scale",
            "cost_bps",
            "n_bars",
            "n_clusters",
            "ci_lower",
            "ci_upper",
            "passes",
            "coverage",
        }
        assert "tf" not in v, "evaluate_frame_gate's raw 'tf' field must be renamed to 'scale'"
        assert (
            "regime" not in v
        ), "evaluate_frame_gate's raw 'regime' field must be renamed to 'cost_bps'"

    by_cell = {(v["scale"], v["cost_bps"]): v for v in verdicts}
    fast_10 = by_cell[("fast", 10)]
    slow_10 = by_cell[("slow", 10)]
    assert fast_10["passes"] is True
    assert fast_10["ci_lower"] > 0
    assert slow_10["passes"] is False

    # Below the min_n floor: passes is False with a NaN ci_lower -- the sufficiency floor is
    # respected rather than bypassed, matching frame_gate_passes' own (False, nan, nan)
    # early-return contract.
    below_floor_rows = [
        {
            "scale": "fast",
            "cost_bps": 10,
            "cluster_id": date(2026, 1, 1) + timedelta(days=i),
            "pnl_r": 0.01,
        }
        for i in range(5)
    ]
    below_floor_verdicts = evaluate_spread_gate(
        below_floor_rows,
        min_n=30,
        bootstrap_max_n=5000,
        bootstrap_batch=1000,
        bootstrap_random_state=42,
    )
    assert len(below_floor_verdicts) == 1
    assert below_floor_verdicts[0]["passes"] is False
    assert math.isnan(below_floor_verdicts[0]["ci_lower"])


def test_evaluate_gate_group_key_is_a_two_tuple():
    """Source-level contract test (test_counterfactual_tracker.py's own style): the
    group_key lambda passed to evaluate_frame_gate must return exactly two elements --
    evaluate_frame_gate unpacks it as `for (dim_a, dim_b), bucket in groups.items()`, and a
    3-tuple would raise `ValueError: too many values to unpack`."""
    source = inspect.getsource(evaluate_spread_gate)
    assert 'group_key=lambda row: (row["scale"], row["cost_bps"])' in source, (
        "evaluate_spread_gate's group_key lambda must return exactly a 2-tuple; a 3rd "
        "element would make evaluate_frame_gate's `for (dim_a, dim_b), bucket in "
        "groups.items()` raise ValueError: too many values to unpack"
    )


# ---------------------------------------------------------------------------
# test_shuffled_ranking_null (167-VALIDATION.md row 167-04-02 family)
# ---------------------------------------------------------------------------


def test_shuffled_ranking_null():
    n_bars = 30
    n_symbols = 20
    symbols = [f"S{i:02d}" for i in range(n_symbols)]

    # Panel 1: ctf_momentum PERFECTLY correlated with return_fast -- a maximally informative
    # ranking. Same at every bar, so the observed decile split extracts the true maximum
    # achievable spread.
    informative_panel = {}
    for b in range(n_bars):
        feature_values = [float(i) for i in range(n_symbols)]
        returns_by_symbol = {f"S{i:02d}": float(i) * 0.001 for i in range(n_symbols)}
        informative_panel[b] = (symbols, feature_values, returns_by_symbol)

    observed_mean, _ = mean_gross_spread_over_bars(informative_panel, decile_fraction=0.10)
    null_p, _, _, _ = shuffled_ranking_null_p(
        informative_panel,
        decile_fraction=0.10,
        observed_mean_spread=observed_mean,
        n_shuffles=20,
        seed=42,
    )
    assert null_p < 0.05, "a real, maximally informative ranking must beat its own permutation null"

    # Panel 2: ctf_momentum generated INDEPENDENTLY of the returns (a meaningless ranking) --
    # a per-bar random permutation unrelated to the fixed return assignment. This is the
    # case that matters: it proves the null check can actually fail, which is what makes the
    # informative case's pass evidence rather than a formality.
    rng = random.Random(99)
    meaningless_panel = {}
    for b in range(n_bars):
        shuffled_feature_values = list(range(n_symbols))
        rng.shuffle(shuffled_feature_values)
        feature_values = [float(v) for v in shuffled_feature_values]
        returns_by_symbol = {f"S{i:02d}": float(i) * 0.001 for i in range(n_symbols)}
        meaningless_panel[b] = (symbols, feature_values, returns_by_symbol)

    observed_mean_meaningless, _ = mean_gross_spread_over_bars(
        meaningless_panel, decile_fraction=0.10
    )
    null_p_meaningless, _, _, _ = shuffled_ranking_null_p(
        meaningless_panel,
        decile_fraction=0.10,
        observed_mean_spread=observed_mean_meaningless,
        n_shuffles=20,
        seed=42,
    )
    assert null_p_meaningless >= 0.05, "a meaningless ranking must not clear the null"

    # Reproducibility: identical seed -> identical null_p (and the rest of the tuple).
    null_p_again, null_mean_again, null_std_again, n_again = shuffled_ranking_null_p(
        informative_panel,
        decile_fraction=0.10,
        observed_mean_spread=observed_mean,
        n_shuffles=20,
        seed=42,
    )
    assert null_p_again == null_p


def test_shuffled_null_permutes_within_bar_only(monkeypatch):
    """A cross-bar permutation would destroy the cross-sectional structure being tested, not
    just the ranking information. `numpy.random.Generator` is an immutable C-extension type
    (its methods cannot be monkeypatched directly), so this wraps `numpy.random.default_rng`
    itself in a recording proxy that records every `.permutation()` call's input array while
    delegating to the real generator -- directly observing the internal draw-generation step
    rather than assuming it from the outside."""
    panel = {
        "bar0": (
            ["A", "B", "C", "D"],
            [1.0, 2.0, 3.0, 4.0],
            {"A": 0.1, "B": 0.2, "C": 0.3, "D": 0.4},
        ),
        "bar1": (
            ["E", "F", "G", "H"],
            [100.0, 200.0, 300.0, 400.0],
            {"E": 0.5, "F": 0.6, "G": 0.7, "H": 0.8},
        ),
    }
    calls: list[np.ndarray] = []
    real_default_rng = np.random.default_rng

    class _RecordingRNG:
        def __init__(self, real_rng: np.random.Generator) -> None:
            self._real_rng = real_rng

        def permutation(self, x, *args, **kwargs):
            calls.append(np.asarray(x).copy())
            return self._real_rng.permutation(x, *args, **kwargs)

    def fake_default_rng(seed):
        return _RecordingRNG(real_default_rng(seed))

    monkeypatch.setattr(np.random, "default_rng", fake_default_rng)

    observed_mean, _ = mean_gross_spread_over_bars(panel, decile_fraction=0.5)
    shuffled_ranking_null_p(
        panel, decile_fraction=0.5, observed_mean_spread=observed_mean, n_shuffles=3, seed=7
    )

    assert len(calls) == 3 * 2  # 3 shuffles x 2 bars
    bar0_values = sorted(panel["bar0"][1])
    bar1_values = sorted(panel["bar1"][1])
    for call_array in calls:
        sorted_call = sorted(call_array.tolist())
        assert sorted_call == bar0_values or sorted_call == bar1_values, (
            "each permutation call's input array must be exactly one bar's own feature "
            "values -- a cross-bar permutation would mix bar0's and bar1's values into a "
            "single call, destroying the cross-sectional structure being tested"
        )
        assert len(call_array) in (
            len(bar0_values),
            len(bar1_values),
        ), "universe size per bar must be unchanged by permutation"


def test_shuffled_null_ties_and_degenerate_bars(monkeypatch):
    """The Codex HIGH-concern coverage -- VERIFIES design decision 6 rather than assuming it.
    A panel containing three deliberately awkward bars alongside ordinary ones: (i) a
    DEGENERATE bar too small for decile_fraction, (ii) a FULLY TIED bar where every symbol
    shares one identical feature value, and (iii) a BOUNDARY-TIED bar where exactly two
    symbols share the value straddling the leg cut."""

    def _ordinary_bar(offset: float) -> tuple[list[str], list[float], dict[str, float]]:
        symbols = [f"S{i:02d}" for i in range(10)]
        feature_values = [float(i) for i in range(10)]
        returns_by_symbol = {f"S{i:02d}": float(i) * 0.001 + offset for i in range(10)}
        return symbols, feature_values, returns_by_symbol

    degenerate_bar = (["Z"], [1.0], {"Z": 0.1})  # 1 symbol at decile_fraction=0.20 -> None

    tied_symbols = ["A", "B", "C", "D", "E", "F", "G", "H", "I", "J"]
    fully_tied_bar = (
        tied_symbols,
        [5.0] * 10,
        {s: 0.001 * i for i, s in enumerate(tied_symbols)},
    )

    boundary_values = {
        "A": 1.0,
        "B": 10.0,
        "C": 2.0,
        "D": 2.0,
        "E": 4.0,
        "F": 5.0,
        "G": 6.0,
        "H": 7.0,
        "I": 8.0,
        "J": 9.0,
    }
    boundary_symbols = list(boundary_values.keys())
    boundary_tied_bar = (
        boundary_symbols,
        [boundary_values[s] for s in boundary_symbols],
        {s: 0.001 * i for i, s in enumerate(boundary_symbols)},
    )

    panel = {
        "ord0": _ordinary_bar(0.0),
        "ord1": _ordinary_bar(0.001),
        "ord2": _ordinary_bar(0.002),
        "ord3": _ordinary_bar(0.003),
        "ord4": _ordinary_bar(0.004),
        "degenerate": degenerate_bar,
        "fully_tied": fully_tied_bar,
        "boundary_tied": boundary_tied_bar,
    }
    decile_fraction = 0.20

    # (a) The degenerate bar is excluded from n_eligible_bars; the two tied bars are
    # structurally valid (decile_legs returns a real split for both) and are INCLUDED --
    # silently dropping them would change the denominator.
    observed_mean, observed_n_eligible_bars = mean_gross_spread_over_bars(panel, decile_fraction)
    assert observed_n_eligible_bars == 7  # 5 ordinary + fully_tied + boundary_tied

    # (b) shuffled_ranking_null_p's eligible-bar count is IDENTICAL to the observed pass's
    # count. This is the parity assertion: it proves the null and the observed value are
    # averages over the SAME bar set, so null_p compares like with like.
    null_p, null_mean, null_std, null_n_eligible_bars = shuffled_ranking_null_p(
        panel, decile_fraction, observed_mean, n_shuffles=50, seed=11
    )
    assert null_n_eligible_bars == observed_n_eligible_bars, (
        "an unequal count means the null distribution is being compared against an observed "
        "value computed over a different set of bars, which would silently invalidate the "
        "Gate 1 null verdict"
    )

    # (c) The degenerate bar is skipped in EVERY draw, not just on average -- the n_shuffles=50
    # call above did not raise the function's own internal eligible-bar-count-differs
    # ValueError. Prove the guard is LIVE (not merely assumed) by monkeypatching the shared
    # reduction to simulate a divergent eligible-bar count on one draw and confirming the
    # guard trips.
    import services.cross_sectional_spread_tracker as cst_module

    real_reduction = cst_module.mean_gross_spread_over_bars
    call_count = {"n": 0}

    def flaky_reduction(panel_by_bar, decile_fraction_arg):
        call_count["n"] += 1
        mean_val, n_val = real_reduction(panel_by_bar, decile_fraction_arg)
        if call_count["n"] == 2:
            n_val = n_val - 1  # simulate a divergent eligible-bar count on the 2nd draw
        return mean_val, n_val

    monkeypatch.setattr(cst_module, "mean_gross_spread_over_bars", flaky_reduction)
    with pytest.raises(ValueError, match="eligible-bar count varies across draws"):
        shuffled_ranking_null_p(panel, decile_fraction, observed_mean, n_shuffles=3, seed=11)
    monkeypatch.undo()

    # (d) Ties do not crash and do not produce non-deterministic draws: two calls with the
    # same seed over the tie-containing panel return identical null_p, null_mean, null_std,
    # and n_eligible_bars.
    result_a = shuffled_ranking_null_p(panel, decile_fraction, observed_mean, n_shuffles=20, seed=5)
    result_b = shuffled_ranking_null_p(panel, decile_fraction, observed_mean, n_shuffles=20, seed=5)
    assert result_a == result_b


# ---------------------------------------------------------------------------
# test_verdict_artifact_is_strict_json (design decision 7, T-167-17)
# ---------------------------------------------------------------------------


def test_verdict_artifact_is_strict_json(tmp_path, monkeypatch):
    from datetime import UTC, datetime

    import services.cross_sectional_spread_tracker as cst_module

    # Force two distinct timestamps across the two calls below -- write_verdict_artifact's
    # filename has only second-level precision, and two calls issued back-to-back inside a
    # single test could otherwise collide on the same second, which would make the
    # accumulate-never-overwrite property untestable (rather than proving it).
    fixed_times = iter(
        [datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC), datetime(2026, 1, 1, 0, 0, 1, tzinfo=UTC)]
    )

    class _FakeDatetime:
        @classmethod
        def now(cls, tz=None):
            return next(fixed_times)

    monkeypatch.setattr(cst_module, "datetime", _FakeDatetime)

    payload_one = {
        "nested": {"a": 1, "b": [1, 2, 3]},
        "items": [{"x": 1}, {"x": 2}],
        "d": date(2026, 1, 1),
        "n": float("nan"),
        "inf_val": float("inf"),
    }
    path_one = write_verdict_artifact("gate1_test", payload_one, out_dir=tmp_path)
    assert path_one.exists()

    loaded_one = json.loads(path_one.read_text())  # default STRICT parser -- no parse_constant
    assert loaded_one["n"] is None
    assert loaded_one["inf_val"] is None
    assert loaded_one["d"] == "2026-01-01"
    assert loaded_one["nested"] == {"a": 1, "b": [1, 2, 3]}
    assert loaded_one["items"] == [{"x": 1}, {"x": 2}]

    latest_path = tmp_path / "gate1_test_latest.json"
    assert latest_path.exists()
    assert json.loads(latest_path.read_text()) == loaded_one

    # A second call with a DIFFERENT payload must never overwrite the first timestamped
    # file -- the accumulate-never-overwrite property is what makes this an audit trail
    # rather than a scratch file.
    payload_two = {"different": True}
    path_two = write_verdict_artifact("gate1_test", payload_two, out_dir=tmp_path)
    assert path_two != path_one
    assert path_one.exists()
    assert json.loads(path_one.read_text()) == loaded_one
    assert json.loads(latest_path.read_text()) == {"different": True}


# ---------------------------------------------------------------------------
# test_static_tilt_weights (167-VALIDATION.md row 167-05-01 family, design decision 1)
# ---------------------------------------------------------------------------


def test_static_tilt_weights():
    # 4-bar leg history: AL always long (weight 1.0), AS always short (weight -1.0), H long in
    # half the bars and short in the other half (weight 0.0), O appears in only one bar, long
    # (weight 0.25).
    leg_rows = [
        {"long_leg_symbols": ["AL", "H", "O"], "short_leg_symbols": ["AS"]},
        {"long_leg_symbols": ["AL", "H"], "short_leg_symbols": ["AS"]},
        {"long_leg_symbols": ["AL"], "short_leg_symbols": ["AS", "H"]},
        {"long_leg_symbols": ["AL"], "short_leg_symbols": ["AS", "H"]},
    ]
    weights = static_tilt_weights(leg_rows)
    assert weights["AL"] == pytest.approx(1.0)
    assert weights["AS"] == pytest.approx(-1.0)
    assert weights["H"] == pytest.approx(0.0)
    assert weights["O"] == pytest.approx(0.25)

    with pytest.raises(ValueError, match="empty"):
        static_tilt_weights([])


# ---------------------------------------------------------------------------
# test_attribution_honesty (167-VALIDATION.md row 167-05-01) -- the gate's central test
# ---------------------------------------------------------------------------


def test_attribution_honesty():
    n = 50
    cluster_ids = [date(2026, 1, 1) + timedelta(days=i) for i in range(n)]
    bar_keys = list(range(n))
    bootstrap_kwargs = dict(
        min_n=5, bootstrap_max_n=5000, bootstrap_batch=1000, bootstrap_random_state=42
    )

    # Case A: PURELY a static tilt. spread_t = 2.0 * static_t + negligible noise. This is the
    # "factor exposure in disguise" case the design doc's Gate 2 exists to catch -- a Gate 2
    # implementation that passes this input is broken regardless of what else it does.
    rng_a = np.random.default_rng(1)
    static_a = rng_a.normal(loc=0.0, scale=0.01, size=n)
    noise_a = rng_a.normal(loc=0.0, scale=1e-6, size=n)
    spread_a = 2.0 * static_a + noise_a
    verdict_a = attribution_verdict(
        spread_a.tolist(), static_a.tolist(), cluster_ids, bar_keys, 0.50, **bootstrap_kwargs
    )
    assert verdict_a["static_r2"] > 0.9, (
        "a construction whose entire P&L is a static tilt must show a near-total static_r2 -- "
        "this is the direction Gate 2 exists to catch"
    )
    assert verdict_a["static_dominates"] is True
    assert verdict_a["beta"] == pytest.approx(2.0, rel=1e-2)
    assert verdict_a["gate2_passes"] is False, (
        "a Gate 2 implementation that passes a purely static tilt is broken regardless of "
        "what else it does"
    )
    assert verdict_a["benchmark_kind"] == "retrospective_time_averaged_membership"

    # Case B: spread_t is INDEPENDENT of static_t -- a positive constant plus independent
    # noise, static_t itself independent noise. Must PASS: low static_r2, surviving positive
    # residual.
    rng_b = np.random.default_rng(2)
    static_b = rng_b.normal(loc=0.0, scale=1.0, size=n)
    spread_b = 0.02 + rng_b.normal(loc=0.0, scale=0.001, size=n)
    verdict_b = attribution_verdict(
        spread_b.tolist(), static_b.tolist(), cluster_ids, bar_keys, 0.50, **bootstrap_kwargs
    )
    assert verdict_b["static_r2"] < 0.50
    assert verdict_b["static_dominates"] is False
    assert verdict_b["residual_passes"] is True
    assert verdict_b["residual_ci_lower"] > 0
    assert verdict_b["gate2_passes"] is True
    assert verdict_b["benchmark_kind"] == "retrospective_time_averaged_membership"

    # Case C: low static_r2 but NO surviving residual -- zero-mean noise independent of
    # static_t. Proves the gate is not satisfiable by low R-squared alone (design decision 3).
    rng_c = np.random.default_rng(3)
    static_c = rng_c.normal(loc=0.0, scale=1.0, size=n)
    spread_c = rng_c.normal(loc=0.0, scale=0.001, size=n)
    verdict_c = attribution_verdict(
        spread_c.tolist(), static_c.tolist(), cluster_ids, bar_keys, 0.50, **bootstrap_kwargs
    )
    assert verdict_c["static_dominates"] is False
    assert verdict_c["residual_passes"] is False, (
        "low static_r2 alone must not satisfy the gate -- something must also survive in the "
        "residual (design decision 3)"
    )
    assert verdict_c["gate2_passes"] is False
    assert verdict_c["benchmark_kind"] == "retrospective_time_averaged_membership"


# ---------------------------------------------------------------------------
# test_attribution_verdict_rejects_misaligned_series (design decision 9)
# ---------------------------------------------------------------------------


def test_attribution_verdict_rejects_misaligned_series():
    bootstrap_kwargs = dict(
        min_n=5, bootstrap_max_n=5000, bootstrap_batch=1000, bootstrap_random_state=42
    )

    # (a) Mismatched lengths -- message names the mismatch. A silently misaligned regression
    # returns a confident, plausible, wrong static_r2, which is why this is a raise and not a
    # warning.
    with pytest.raises(ValueError, match="mismatched"):
        attribution_verdict(
            [0.1, 0.2, 0.3], [0.05, 0.06], [1, 2, 3], [1, 2, 3], 0.50, **bootstrap_kwargs
        )

    # (b) Duplicate bar_keys -- message names the offending key.
    with pytest.raises(ValueError, match="duplicate bar key"):
        attribution_verdict(
            [0.1, 0.2, 0.3],
            [0.05, 0.06, 0.07],
            [1, 2, 3],
            [1, 2, 2],
            0.50,
            **bootstrap_kwargs,
        )

    # (c) Non-increasing bar_keys -- message names the offending key.
    with pytest.raises(ValueError, match="strictly increasing"):
        attribution_verdict(
            [0.1, 0.2, 0.3],
            [0.05, 0.06, 0.07],
            [1, 2, 3],
            [3, 2, 1],
            0.50,
            **bootstrap_kwargs,
        )


# ---------------------------------------------------------------------------
# test_static_tilt_series_rejects_duplicate_bars (design decision 9, one layer earlier)
# ---------------------------------------------------------------------------


def test_static_tilt_series_rejects_duplicate_bars():
    class _FakeDuplicateKeysPanel:
        """A minimal Mapping-like stand-in whose `.keys()` can yield a duplicate -- a real
        `dict` cannot structurally hold a duplicate key, so this simulates the case a
        differently-sourced panel mapping (e.g. a join producing two distinct-but-equal
        timestamp objects) could still produce."""

        def keys(self):
            return [1, 2, 2, 3]

        def __getitem__(self, key):
            return {"A": 0.01}

    with pytest.raises(ValueError, match="duplicate bar key"):
        static_tilt_series(_FakeDuplicateKeysPanel(), {"A": 1.0})


# ---------------------------------------------------------------------------
# test_attribution_intercept_is_not_subtracted_from_residual (design decision 3 regression)
# ---------------------------------------------------------------------------


def test_attribution_intercept_is_not_subtracted_from_residual():
    n = 60
    rng = np.random.default_rng(7)
    static_t = rng.normal(loc=0.0, scale=1.0, size=n)
    true_intercept = 0.05
    true_beta = 1.5
    tiny_noise = rng.normal(loc=0.0, scale=1e-6, size=n)
    spread_t = true_intercept + true_beta * static_t + tiny_noise
    cluster_ids = list(range(n))
    bar_keys = list(range(n))

    verdict = attribution_verdict(
        spread_t.tolist(),
        static_t.tolist(),
        cluster_ids,
        bar_keys,
        max_static_r2=0.99,
        min_n=5,
        bootstrap_max_n=5000,
        bootstrap_batch=1000,
        bootstrap_random_state=42,
    )
    assert verdict["beta"] == pytest.approx(true_beta, rel=1e-3)
    assert verdict["intercept"] == pytest.approx(true_intercept, rel=1e-2)

    # The residual mean implied by the returned beta must equal mean(spread) - beta*mean(static)
    # -- NOT zero. If a future refactor subtracts the intercept too, the residual mean
    # collapses toward zero and Gate 2 becomes impossible to pass by construction; this
    # assertion is what catches that silently catastrophic change.
    mean_spread = float(np.mean(spread_t))
    mean_static = float(np.mean(static_t))
    expected_residual_mean = mean_spread - verdict["beta"] * mean_static
    assert expected_residual_mean == pytest.approx(true_intercept, abs=1e-3)
    assert expected_residual_mean != pytest.approx(0.0, abs=1e-3), (
        "the residual mean must equal the retained intercept, not collapse to zero -- a "
        "refactor that subtracts the intercept too would make Gate 2 unsatisfiable by "
        "construction"
    )

    # Direct evidence from the function's own output (not merely the sequence-arithmetic
    # assertion above): the residual's bootstrap CI is centered near the retained intercept,
    # never near zero.
    assert verdict["residual_ci_lower"] > true_intercept / 2
