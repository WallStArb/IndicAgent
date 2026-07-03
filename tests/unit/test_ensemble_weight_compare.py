"""Unit tests: D-12 ensemble weight_version A/B win-decision comparison.

_evaluate_win_rule and _regime_caveat are pure importable helpers in
scripts/ops/alpha/ops_ensemble_weight_compare.py. Given a challenger's CI lower bound,
a champion's CI upper bound, and the challenger's walk_forward_stable flag, the win rule
returns True iff the CIs do not overlap (challenger strictly above champion) AND the
challenger is walk-forward stable (D-10, both conditions ANDed). The regime-caveat
helper tags every non-'_pooled' regime stratum with the HMM regime-label look-ahead
caveat (D-14).

No DB, no Kafka. Pure Python.
"""

from __future__ import annotations

import sys
from pathlib import Path

_scripts_alpha_dir = Path(__file__).parent.parent.parent / "scripts" / "ops" / "alpha"
if str(_scripts_alpha_dir) not in sys.path:
    sys.path.insert(0, str(_scripts_alpha_dir))

from ops_ensemble_weight_compare import (
    _COMPARE_SQL,
    _D14_REGIME_CAVEAT,
    _evaluate_win_rule,
    _regime_caveat,
)


def test_win_when_ci_non_overlapping_and_stable():
    """challenger_ci_lower=0.30 > champion_ci_upper=0.20, stable=True -> win True."""
    win = _evaluate_win_rule(
        challenger_ci_lower=0.30, champion_ci_upper=0.20, challenger_stable=True
    )
    assert win is True


def test_no_win_when_ci_overlaps():
    """challenger_ci_lower=0.15 <= champion_ci_upper=0.20, stable=True -> False."""
    win = _evaluate_win_rule(
        challenger_ci_lower=0.15, champion_ci_upper=0.20, challenger_stable=True
    )
    assert win is False


def test_no_win_when_unstable_even_if_ci_non_overlapping():
    """Critical AND-veto regression (D-10): challenger_ci_lower=0.30 > 0.20 but
    stable=False -> False. If _evaluate_win_rule were ever changed from AND to OR, this
    test would flip to True and fail to catch a false promotion.
    """
    win = _evaluate_win_rule(
        challenger_ci_lower=0.30, champion_ci_upper=0.20, challenger_stable=False
    )
    assert win is False


def test_win_rule_boundary_equal_cis_is_not_a_win():
    """challenger_ci_lower == champion_ci_upper is NOT strictly non-overlapping -> False."""
    win = _evaluate_win_rule(
        challenger_ci_lower=0.20, champion_ci_upper=0.20, challenger_stable=True
    )
    assert win is False


def test_regime_caveat_tag_applied_when_regime_not_pooled():
    """regime='trending_up' -> caveat string non-empty; regime='_pooled' -> empty."""
    assert _regime_caveat("trending_up") == _D14_REGIME_CAVEAT
    assert _regime_caveat("high_bear") == _D14_REGIME_CAVEAT
    assert _regime_caveat("_pooled") == ""


def test_sql_groups_by_weight_version():
    """Regression: the per-version latest-vintage CTE must GROUP BY weight_version
    (deterministic latest scored_at PER weight_version), not a single global max --
    otherwise champion and challenger could be compared at mismatched vintages.
    """
    assert "GROUP BY weight_version" in _COMPARE_SQL
    assert "latest_per_version" in _COMPARE_SQL


def test_sql_filters_pooled_rows():
    """SQL must scope to the pooled cross-sectional rows only (symbol='POOLED' AND
    is_pooled=true) -- the win decision reads the statistically clean pooled grain,
    never mixing in per-symbol rows.
    """
    assert "symbol = 'POOLED'" in _COMPARE_SQL
    assert "is_pooled = true" in _COMPARE_SQL


def test_sql_scopes_to_single_lookahead_scale():
    """SQL must filter both the vintage CTE and the row fetch to a single lookahead
    scale (alpha.ensemble_ic.gate_lookahead APR value passed as $3) -- otherwise CIs
    measured at different lookahead horizons could be compared against each other
    within one (tf, regime) stratum.
    """
    assert _COMPARE_SQL.count("lookahead = $3") == 2
