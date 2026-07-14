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
from datetime import UTC, datetime
from typing import Any

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


# ---------------------------------------------------------------------------
# Transactional apply (asyncpg)
# ---------------------------------------------------------------------------

_LOAD_CONCEPT_SQL = """
    SELECT r.concept_id, r.status,
           g.promotion_consecutive, g.promotion_eval_metrics,
           g.last_eval_corpus_build_ref, g.last_eval_n,
           g.min_promotion_consecutive, g.min_new_observations, g.min_gate_n
    FROM concept_registry r
    JOIN concept_gate g USING (concept_id)
    WHERE r.domain = $1 AND r.name = $2
"""

# Invariant 9: compare-and-swap. Zero rows updated means the status changed under
# us (or a rerun raced). L-5 correction (Phase 160 cross-AI review): the CAS
# matched zero rows, so no status change, transition, or gate update is executed -
# the empty transaction commits harmlessly (it does NOT roll back/abort; returning
# from inside `async with conn.transaction()` commits an empty transaction).
_CAS_PROMOTE_SQL = """
    UPDATE concept_registry SET status = $1
    WHERE concept_id = $2 AND status = $3
"""

_TRANSITION_INSERT_SQL = """
    INSERT INTO concept_transition_log
        (concept_id, domain, name, from_status, to_status, trigger_reason,
         corpus_build_ref, gate_metric, gate_n, ci_lower, triggered_at, notes)
    VALUES ($1, $2, $3, $4, $5, 'promotion', $6, $7, $8, $9, $10, $11)
"""

# L-2 (Phase 160 cross-AI review, accepted risk): this read-modify-write is NOT
# compare-and-swapped - the gate row is loaded outside any transaction, so
# concurrent evaluators can lose a gate-cache update. Accepted for this
# near-static, manually triggered domain (fails conservative: at worst a stale
# eval cache, never a wrong status flip). This MUST be CAS'd before the
# domain='feature' hot path (ic_engine.py write pressure) inherits this pattern.
_GATE_CACHE_UPDATE_SQL = """
    UPDATE concept_gate
    SET last_eval_metric = $2, last_eval_n = $3, last_eval_at = $4,
        last_eval_corpus_build_ref = $5,
        promotion_consecutive = $6, promotion_eval_metrics = $7,
        updated_at = $4
    WHERE concept_id = $1
"""

_GATE_PROMOTE_UPDATE_SQL = """
    UPDATE concept_gate
    SET last_eval_metric = $2, last_eval_n = $3, last_eval_at = $4,
        last_eval_corpus_build_ref = $5,
        promotion_consecutive = $6, promotion_eval_metrics = $7,
        baseline_metric = $8, decay_ratio = 1.0,
        updated_at = $4
    WHERE concept_id = $1
"""


class ConceptNotFoundError(Exception):
    """No concept_registry+concept_gate row for the given (domain, name)."""


def _rowcount(execute_status: str) -> int:
    """Parse asyncpg's execute() status string ('UPDATE 1' -> 1)."""
    return int(execute_status.rsplit(" ", 1)[-1])


class ConceptRegistryService:
    """Narrowly-scoped Concept Registry writer (invariant 1).

    Stateless: every method takes an asyncpg connection. The only status-flipping
    path is record_comparison_outcome; it can only ever write
    candidate -> active with trigger_reason='promotion'. It structurally cannot
    target 'deprecated' (operator-only) or write annotation content.

    L-7 (Phase 160 cross-AI review): this service never reads
    concept_gate.fdr_required. BH-FDR enforcement lives entirely upstream in
    ops_ensemble_weight_compare.py - a future second caller of
    record_comparison_outcome must not assume this service enforces FDR itself.
    """

    async def record_comparison_outcome(
        self,
        conn: Any,
        *,
        domain: str,
        name: str,
        won: bool,
        eval_metric: float | None,
        eval_n: float,
        corpus_build_ref: str,
        default_min_promotion_consecutive: int,
        default_min_new_observations: float,
        default_min_gate_n: float,
        notes: str | None = None,
    ) -> ComparisonDecision:
        """Apply one A/B comparison outcome for one concept, transactionally.

        The default_* floors are APR-resolved by the caller
        (alpha.concept_registry.<domain>_* keys); a non-NULL concept_gate column
        overrides its default. Blocked/noop decisions write nothing.
        """
        row = await conn.fetchrow(_LOAD_CONCEPT_SQL, domain, name)
        if row is None:
            raise ConceptNotFoundError(
                f"no concept_registry+concept_gate row for domain={domain!r} name={name!r}"
            )

        state = GateState(
            status=row["status"],
            promotion_consecutive=row["promotion_consecutive"],
            promotion_eval_metrics=tuple(row["promotion_eval_metrics"] or ()),
            last_eval_corpus_build_ref=row["last_eval_corpus_build_ref"],
            last_eval_n=row["last_eval_n"],
            min_promotion_consecutive=(
                row["min_promotion_consecutive"]
                if row["min_promotion_consecutive"] is not None
                else default_min_promotion_consecutive
            ),
            min_new_observations=(
                row["min_new_observations"]
                if row["min_new_observations"] is not None
                else default_min_new_observations
            ),
            min_gate_n=(row["min_gate_n"] if row["min_gate_n"] is not None else default_min_gate_n),
        )

        decision = decide_comparison_action(
            state,
            won=won,
            eval_metric=eval_metric,
            eval_n=eval_n,
            corpus_build_ref=corpus_build_ref,
        )

        if decision.action in (
            "noop_deprecated",
            "blocked_same_corpus",
            "blocked_min_n",
            "blocked_evidence_floor",
        ):
            _logger.info(
                "concept_registry.comparison_blocked",
                domain=domain,
                name=name,
                action=decision.action,
                corpus_build_ref=corpus_build_ref,
            )
            return decision

        now = datetime.now(UTC)
        metrics_list = list(decision.new_promotion_eval_metrics)

        if decision.action == "promote":
            async with conn.transaction():
                cas_status = await conn.execute(
                    _CAS_PROMOTE_SQL, "active", row["concept_id"], "candidate"
                )
                if _rowcount(cas_status) == 0:
                    _logger.warning(
                        "concept_registry.promotion_cas_race",
                        domain=domain,
                        name=name,
                        corpus_build_ref=corpus_build_ref,
                    )
                    return ComparisonDecision(
                        "blocked_status_race",
                        state.promotion_consecutive,
                        state.promotion_eval_metrics,
                        None,
                    )
                await conn.execute(
                    _TRANSITION_INSERT_SQL,
                    row["concept_id"],
                    domain,
                    name,
                    "candidate",
                    "active",
                    corpus_build_ref,
                    decision.baseline_metric,
                    eval_n,
                    eval_metric,
                    now,
                    notes,
                )
                await conn.execute(
                    _GATE_PROMOTE_UPDATE_SQL,
                    row["concept_id"],
                    eval_metric,
                    eval_n,
                    now,
                    corpus_build_ref,
                    decision.new_promotion_consecutive,
                    metrics_list,
                    decision.baseline_metric,
                )
            _logger.info(
                "concept_registry.promoted",
                domain=domain,
                name=name,
                baseline_metric=decision.baseline_metric,
                corpus_build_ref=corpus_build_ref,
            )
            return decision

        # record_win / record_loss: eval-cache bookkeeping only.
        await conn.execute(
            _GATE_CACHE_UPDATE_SQL,
            row["concept_id"],
            eval_metric,
            eval_n,
            now,
            corpus_build_ref,
            decision.new_promotion_consecutive,
            metrics_list,
        )
        _logger.info(
            "concept_registry.comparison_recorded",
            domain=domain,
            name=name,
            action=decision.action,
            corpus_build_ref=corpus_build_ref,
        )
        return decision
