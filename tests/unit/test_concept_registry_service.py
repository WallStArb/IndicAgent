"""Unit tests: ConceptRegistryService (todo 058).

decide_comparison_action is the pure invariant-enforcement core: invariant 2
(re-evaluation needs new evidence: corpus-advance precondition + F3 evidence-mass
floor), invariant 7 (initial effective-N floor), F8 (baseline_metric = mean of the
consecutive winning evals, never the final one), and the deprecated-is-operator-only
rule. No DB, no Kafka. Pure Python.
"""

from __future__ import annotations

import sys
from pathlib import Path

_project_root = Path(__file__).parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

import pytest

from src.intelligence.concept_registry_service import (
    GateState,
    decide_comparison_action,
)


def _state(**overrides) -> GateState:
    base = dict(
        status="candidate",
        promotion_consecutive=0,
        promotion_eval_metrics=(),
        last_eval_corpus_build_ref=None,
        last_eval_n=None,
        min_promotion_consecutive=2,
        min_new_observations=2000.0,
        min_gate_n=1000.0,
    )
    base.update(overrides)
    return GateState(**base)


def test_deprecated_is_untouchable():
    """Automated path never acts on a deprecated concept (operator-only status)."""
    decision = decide_comparison_action(
        _state(status="deprecated"),
        won=True,
        eval_metric=0.05,
        eval_n=5000.0,
        corpus_build_ref="run_A",
    )
    assert decision.action == "noop_deprecated"


def test_same_corpus_build_is_blocked():
    """Invariant 2 precondition: never evaluate twice against the same corpus build."""
    decision = decide_comparison_action(
        _state(last_eval_corpus_build_ref="run_A", last_eval_n=3000.0),
        won=True,
        eval_metric=0.05,
        eval_n=9000.0,
        corpus_build_ref="run_A",
    )
    assert decision.action == "blocked_same_corpus"


def test_initial_effective_n_floor_blocks():
    """Invariant 7: eval_n below min_gate_n blocks regardless of the win."""
    decision = decide_comparison_action(
        _state(),
        won=True,
        eval_metric=0.05,
        eval_n=999.0,
        corpus_build_ref="run_A",
    )
    assert decision.action == "blocked_min_n"


def test_evidence_mass_floor_blocks_reeval():
    """F3: re-evaluation needs >= min_new_observations NEW independent observations
    since the last recorded eval; corpus-advance alone is insufficient."""
    decision = decide_comparison_action(
        _state(last_eval_corpus_build_ref="run_A", last_eval_n=5000.0),
        won=True,
        eval_metric=0.05,
        eval_n=6999.0,
        corpus_build_ref="run_B",
    )
    assert decision.action == "blocked_evidence_floor"


def test_first_eval_skips_evidence_mass_floor():
    """The F3 floor governs RE-evaluation. A first-ever eval (last_eval_n None) is
    governed by min_gate_n only."""
    decision = decide_comparison_action(
        _state(),
        won=True,
        eval_metric=0.05,
        eval_n=1500.0,
        corpus_build_ref="run_A",
    )
    assert decision.action == "record_win"


def test_loss_resets_consecutive_and_metrics():
    decision = decide_comparison_action(
        _state(
            promotion_consecutive=1,
            promotion_eval_metrics=(0.04,),
            last_eval_corpus_build_ref="run_A",
            last_eval_n=3000.0,
        ),
        won=False,
        eval_metric=None,
        eval_n=6000.0,
        corpus_build_ref="run_B",
    )
    assert decision.action == "record_loss"
    assert decision.new_promotion_consecutive == 0
    assert decision.new_promotion_eval_metrics == ()
    assert decision.baseline_metric is None


def test_win_below_consecutive_floor_records_but_does_not_promote():
    decision = decide_comparison_action(
        _state(),
        won=True,
        eval_metric=0.04,
        eval_n=3000.0,
        corpus_build_ref="run_A",
    )
    assert decision.action == "record_win"
    assert decision.new_promotion_consecutive == 1
    assert decision.new_promotion_eval_metrics == (0.04,)
    assert decision.baseline_metric is None


def test_promotion_baseline_is_mean_of_consecutive_evals_not_final():
    """F8 winner's-curse guard: baseline_metric = mean(promotion_eval_metrics including
    this eval), NEVER the final (selection-inflated) eval alone."""
    decision = decide_comparison_action(
        _state(
            promotion_consecutive=1,
            promotion_eval_metrics=(0.02,),
            last_eval_corpus_build_ref="run_A",
            last_eval_n=3000.0,
        ),
        won=True,
        eval_metric=0.06,
        eval_n=6000.0,
        corpus_build_ref="run_B",
    )
    assert decision.action == "promote"
    assert decision.new_promotion_consecutive == 2
    assert decision.new_promotion_eval_metrics == (0.02, 0.06)
    assert decision.baseline_metric == 0.04  # mean(0.02, 0.06), not 0.06


def test_win_on_already_active_concept_records_win_not_promote():
    """F2: a WIN for an already-active recipe updates the eval cache; it neither
    re-promotes nor displaces anything (redundancy displacement is disabled here)."""
    decision = decide_comparison_action(
        _state(
            status="active",
            promotion_consecutive=3,
            promotion_eval_metrics=(0.02, 0.03, 0.04),
            last_eval_corpus_build_ref="run_A",
            last_eval_n=3000.0,
        ),
        won=True,
        eval_metric=0.05,
        eval_n=6000.0,
        corpus_build_ref="run_B",
    )
    assert decision.action == "record_win"


def test_won_requires_eval_metric():
    with pytest.raises(ValueError):
        decide_comparison_action(
            _state(),
            won=True,
            eval_metric=None,
            eval_n=3000.0,
            corpus_build_ref="run_A",
        )
