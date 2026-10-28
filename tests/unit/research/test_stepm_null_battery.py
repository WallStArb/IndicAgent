"""StepM battery driver (phase 187 plan 05): one cell end to end, and the size rule."""

from scripts.research.stepm_null_battery import (
    _POOLED_TOLERANCE,
    pooled_rate,
    simulate_stepm,
    summarize,
)
from src.intelligence.research.null_battery import scenarios


def test_one_null_simulation_runs_through_stepm():
    sc = scenarios()[0]
    name, hit, p = simulate_stepm(
        ("src.intelligence.research.null_battery", sc, 1, 50, 20.0, 0.05, "draw")
    )
    assert name == "gaussian" and isinstance(hit, bool) and 0.0 <= p <= 1.0


def test_size_rule_uses_the_bonferroni_binomial_quantile():
    ok = summarize("gaussian", [True] * 70 + [False] * 930, 0.05, frozenset())
    bad = summarize("gaussian", [True] * 80 + [False] * 920, 0.05, frozenset())
    assert ok["bound"] == 74
    diag = summarize(
        "hostile_stress", [True] * 80 + [False] * 920, 0.05, frozenset({"hostile_stress"})
    )
    assert ok["holds"] and not bad["holds"] and not diag["gating"]


def test_pooled_rate_counts_gating_cells_only():
    rows = [
        summarize("a", [True] * 50 + [False] * 950, 0.05, frozenset({"c"})),
        summarize("b", [True] * 70 + [False] * 930, 0.05, frozenset({"c"})),
        summarize("c", [True] * 900 + [False] * 100, 0.05, frozenset({"c"})),
    ]
    assert pooled_rate(rows) == 0.06
    assert _POOLED_TOLERANCE == 0.06
