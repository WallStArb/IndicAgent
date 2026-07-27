"""Unit tests: cross_sectional_spread_tracker's pure construction primitives -- the decile
split, tied and missing feature values (Codex review's HIGH concern), run-boundary turnover
(Pitfall 4), the cost-hurdle sweep (D-05), and APR range validation (T-167-01).

No live DB required -- these tests exercise pure functions with synthetic in-memory inputs.
"""

from __future__ import annotations

import random
import sys
from pathlib import Path

_project_root = Path(__file__).parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

import pytest

from services.cross_sectional_spread_tracker import (
    decile_legs,
    net_spread_by_cost_bps,
    one_way_turnover,
    spread_from_legs,
    validate_construction_config,
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
