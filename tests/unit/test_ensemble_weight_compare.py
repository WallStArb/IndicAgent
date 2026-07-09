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

_project_root = Path(__file__).parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

_scripts_alpha_dir = _project_root / "scripts" / "ops" / "alpha"
if str(_scripts_alpha_dir) not in sys.path:
    sys.path.insert(0, str(_scripts_alpha_dir))

from ops_ensemble_weight_compare import (
    _COMPARE_SQL,
    _D14_REGIME_CAVEAT,
    _D15_WINNERS_CURSE_CAVEAT,
    _evaluate_win_rule,
    _final_verdict,
    _regime_caveat,
    _winners_curse_flag,
)

from src.intelligence.statistics.ic_math import apply_bh_fdr


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


def test_winners_curse_flag_applied_only_on_win():
    """D-15: only a WIN verdict is actionable (drives a promotion), so only WIN carries
    the winner's-curse caveat -- a LOSS or HOLD doesn't select the challenger's IC as a
    representative estimate of anything, so there's nothing to caveat.
    """
    assert _winners_curse_flag("WIN") == _D15_WINNERS_CURSE_CAVEAT
    assert _winners_curse_flag("LOSS") == ""
    assert _winners_curse_flag("HOLD") == ""


def test_winners_curse_flag_not_applied_on_win_fdr_veto():
    """A WIN-FDR-VETO already failed multiplicity correction -- it is not a promotable
    win, so there is no promotion decision left to caveat (todo 069).
    """
    assert _winners_curse_flag("WIN-FDR-VETO") == ""


def test_sql_selects_ic_value_and_n_independent():
    """Regression (todo 069): the comparison SQL must select ic_value and n_independent
    -- these feed fisher_z_difference_p's per-stratum BH-FDR pass. Without them the
    multiplicity correction silently has nothing to compute on.
    """
    assert "ae.ic_value" in _COMPARE_SQL
    assert "ae.n_independent" in _COMPARE_SQL


# ---------------------------------------------------------------------------
# _final_verdict (todo 069: D-10 win rule + BH-FDR multiplicity correction)
# ---------------------------------------------------------------------------


def test_final_verdict_loss_regardless_of_bh():
    """win=False -> LOSS no matter what BH says. Multiplicity correction can only
    downgrade a D-10 win; it can never manufacture one that wasn't there.
    """
    assert _final_verdict(win=False, bh_reject=True) == "LOSS"
    assert _final_verdict(win=False, bh_reject=False) == "LOSS"
    assert _final_verdict(win=False, bh_reject=None) == "LOSS"


def test_final_verdict_win_and_bh_reject_is_win():
    """win=True, BH survives (reject=True) -> WIN. Both the pairwise test and the
    corrected family-wise multiplicity check passed.
    """
    assert _final_verdict(win=True, bh_reject=True) == "WIN"


def test_final_verdict_win_but_bh_fail_is_win_fdr_veto():
    """win=True, BH does not survive (reject=False) -> WIN-FDR-VETO, a distinct verdict
    from LOSS -- silently folding this into LOSS would hide exactly the multiplicity
    information this fix exists to surface.
    """
    assert _final_verdict(win=True, bh_reject=False) == "WIN-FDR-VETO"


def test_final_verdict_win_with_degenerate_p_is_hold():
    """win=True but bh_reject is None (p-value was degenerate, e.g. n_independent <= 3
    on one side, and was excluded from the BH correction pool) -> HOLD. No verdict can
    be rendered without a testable p-value.
    """
    assert _final_verdict(win=True, bh_reject=None) == "HOLD"


def test_bh_fdr_vetoes_lone_marginal_win_among_null_strata():
    """Integration test of apply_bh_fdr + _final_verdict composed together, the same
    pairing main() uses: a single marginally-significant p-value (p=0.04) surrounded
    by many null strata (p~0.5-0.9) must be vetoed once corrected across the full
    family -- the concrete "fluke WIN in one stratum out of ~36" scenario todo 069
    exists to catch. apply_bh_fdr's own correctness (statsmodels' BH-FDR behavior in
    isolation) is covered directly in tests/unit/test_ensemble_ic_math.py; this test
    only proves the two functions compose correctly.
    """
    p_values = [0.04] + [0.5, 0.6, 0.7, 0.8, 0.9, 0.55, 0.65, 0.75, 0.85] * 4  # 41 strata
    reject, _ = apply_bh_fdr(p_values, alpha=0.05)

    verdict = _final_verdict(win=True, bh_reject=bool(reject[0]))
    assert verdict == "WIN-FDR-VETO"


def test_bh_fdr_passes_multi_stratum_win():
    """Integration test of apply_bh_fdr + _final_verdict composed together: a
    challenger winning strongly (p << 0.05) across many strata should survive
    correction and report WIN, not be vetoed as a broad-based improvement.
    """
    p_values = [0.0001, 0.0003, 0.0002, 0.0005] + [0.5, 0.6, 0.7, 0.8, 0.9] * 6  # 34 strata
    reject, _ = apply_bh_fdr(p_values, alpha=0.05)

    for i in range(4):
        assert _final_verdict(win=True, bh_reject=bool(reject[i])) == "WIN"
