"""ConceptRegistryService - Concept Registry lifecycle governance (todo 058).

Invariant 1 (canonical doc, docs/research/concept-unified-registry.md):
proposal and decision are different roles, structurally. The ONLY code path that
flips concept_registry.status for domain='ensemble_strategy' is
record_comparison_outcome() below, called by ops_ensemble_weight_compare.py's
deterministic win-decision gate (no LLM anywhere in the path). No other caller,
human or AI, gets a code path that both writes annotation content and flips status.

Structure: decide_comparison_action() is the pure invariant-enforcement core
(unit-tested without DB); record_comparison_outcome() reads the registry+gate row,
delegates the decision, and applies it transactionally with a compare-and-swap
status write (invariant 9).
"""

from __future__ import annotations

from dataclasses import dataclass

import structlog

_logger = structlog.get_logger()

# Automated comparison outcomes may never target 'deprecated' - deprecated is
# operator-only (same rule as FeatureRegistryService._AUTOMATED_REASONS).


@dataclass(frozen=True)
class GateState:
    """Snapshot of one concept's registry status + gate/eval-cache state.

    min_* fields arrive APR-resolved by the caller (per-concept concept_gate
    override when non-NULL, else the alpha.concept_registry.<domain>_* default) -
    never hard-coded here.
    """

    status: str
    promotion_consecutive: int
    promotion_eval_metrics: tuple[float, ...]
    last_eval_corpus_build_ref: str | None
    last_eval_n: float | None
    min_promotion_consecutive: int
    min_new_observations: float
    min_gate_n: float


@dataclass(frozen=True)
class ComparisonDecision:
    """What the registry should do with one A/B comparison outcome.

    action vocabulary:
        'promote'                - CAS candidate -> active + transition log row
        'record_win'             - update eval cache, advance consecutive counter
        'record_loss'            - update eval cache, reset consecutive counter
        'blocked_same_corpus'    - invariant 2 precondition: corpus has not advanced
        'blocked_min_n'          - invariant 7: initial effective-N floor unmet
        'blocked_evidence_floor' - F3: < min_new_observations new evidence since last eval
        'noop_deprecated'        - deprecated is operator-only; automated path never touches it
    Blocked/noop decisions write nothing to the DB. The service layer (Task 4's
    record_comparison_outcome) additionally produces 'blocked_status_race' when its
    compare-and-swap promotion UPDATE matches zero rows; the pure core never emits it.
    """

    action: str
    new_promotion_consecutive: int
    new_promotion_eval_metrics: tuple[float, ...]
    baseline_metric: float | None


def decide_comparison_action(
    state: GateState,
    *,
    won: bool,
    eval_metric: float | None,
    eval_n: float,
    corpus_build_ref: str,
) -> ComparisonDecision:
    """Pure decision core for one A/B comparison outcome against one concept.

    Ordering matters: status guard, then invariant 2's corpus-advance precondition,
    then invariant 7's initial floor, then F3's evidence-mass floor, then the
    win/loss bookkeeping. eval_metric is the challenger's mean ic_ci_lower over WIN
    strata (D-15 citation rule: never ic_value); eval_n is the challenger's summed
    n_independent over all compared strata (effective N, not raw bars).
    """
    if won and eval_metric is None:
        raise ValueError("won=True requires eval_metric (mean ic_ci_lower over WIN strata)")

    if state.status == "deprecated":
        return ComparisonDecision(
            "noop_deprecated",
            state.promotion_consecutive,
            state.promotion_eval_metrics,
            None,
        )

    # L-1 (Phase 160 cross-AI review, accepted risk): this guard compares only
    # against last_eval_corpus_build_ref, so an A-B-A corpus_build_ref replay
    # would pass it (a complete replay check would need to consult the full
    # transition log). Accepted because WEIGHT_EPOCHs are monotone in practice,
    # so A-B-A does not occur.
    if corpus_build_ref == state.last_eval_corpus_build_ref:
        return ComparisonDecision(
            "blocked_same_corpus",
            state.promotion_consecutive,
            state.promotion_eval_metrics,
            None,
        )

    if eval_n < state.min_gate_n:
        return ComparisonDecision(
            "blocked_min_n",
            state.promotion_consecutive,
            state.promotion_eval_metrics,
            None,
        )

    if state.last_eval_n is not None and (eval_n - state.last_eval_n) < state.min_new_observations:
        return ComparisonDecision(
            "blocked_evidence_floor",
            state.promotion_consecutive,
            state.promotion_eval_metrics,
            None,
        )

    if not won:
        return ComparisonDecision("record_loss", 0, (), None)

    new_consecutive = state.promotion_consecutive + 1
    # L-10 (Phase 160 cross-AI review, accepted risk): promotion_eval_metrics
    # grows unboundedly for an active concept (every record_win appends, never
    # trimmed). Accepted as cosmetic at this domain's eval cadence.
    new_metrics = state.promotion_eval_metrics + (float(eval_metric),)

    if state.status == "candidate" and new_consecutive >= state.min_promotion_consecutive:
        baseline = sum(new_metrics) / len(new_metrics)
        return ComparisonDecision("promote", new_consecutive, new_metrics, baseline)

    return ComparisonDecision("record_win", new_consecutive, new_metrics, None)
