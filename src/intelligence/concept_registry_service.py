"""ConceptRegistryService - Concept Registry lifecycle governance (todo 058).

Invariant 1 (canonical doc, docs/research/concept-unified-registry.md):
proposal and decision are different roles, structurally. The ONLY code path that
flips concept_registry.status for domain='ensemble_strategy' is
record_comparison_outcome() below, called by ops_ensemble_weight_compare.py's
deterministic win-decision gate (no LLM anywhere in the path). No other caller,
human or AI, gets a code path that both writes annotation content and flips status.

Structure: decide_comparison_action() is the pure invariant-enforcement core
(unit-tested without DB); record_comparison_outcome() reads the registry+gate row
under FOR UPDATE inside one transaction, delegates the decision, and applies it
with a compare-and-swap status write (invariant 9) before releasing the lock.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import structlog

_logger = structlog.get_logger()

# Automated comparison outcomes may never target 'deprecated' - deprecated is
# operator-only (same rule as FeatureRegistryService._AUTOMATED_REASONS).


class _TransitionNoOp(Exception):
    """Internal sentinel: optimistic lock missed (rowcount == 0) on the sync CAS path.

    Raised inside record_transition_sync's `conn.transaction()` block to force a
    rollback of the CAS UPDATE (and any as-yet-unexecuted shadow-counter reset or
    transition-log INSERT) without inserting a log row, then caught by the caller
    to return False. Never escapes the method. Same rationale as
    FeatureRegistryService's `_TransitionNoOp` (feature_registry_service.py).
    """


# Automated sync-path transition reasons (ic_engine's no-event-loop lifecycle hook,
# Plan 06). These are the concept-table equivalents of feature_registry_service's
# {'ic_promotion', 'ic_demotion'} -- concept_transition_log's trigger_reason CHECK
# does not accept the 'ic_*' spellings at all (migration 225): promotion/demotion
# map to 'promotion'/'demotion_performance' respectively. 'operator_override'
# targeting 'deprecated' remains the only legitimate automated-adjacent path to
# that status (a human decision recorded through the sync API, not an automated
# reason).
_AUTOMATED_SYNC_REASONS = frozenset({"promotion", "demotion_performance"})

# concept_transition_log.trigger_reason's full CHECK vocabulary (migration 225).
# Validated in Python before any write so a typo'd reason surfaces as a ValueError
# with the offending value named, not an opaque Postgres CHECK violation raised
# mid-transaction.
_VALID_TRANSITION_REASONS = frozenset(
    {
        "promotion",
        "demotion_performance",
        "demotion_decay",
        "demotion_redundancy",
        "operator_override",
        "parent_cascade",
        "candidate_timeout",
        "implementation_change",
        "genesis_seed",
    }
)


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
    fdr_required: bool


@dataclass(frozen=True)
class ComparisonDecision:
    """What the registry should do with one A/B comparison outcome.

    action vocabulary:
        'promote'                - CAS candidate -> active + transition log row
        'record_win'             - update eval cache, advance consecutive counter
        'record_win_not_promotable' - like record_win, but the status can never
                                     reach 'promote' (e.g. 'shadow_only'); service
                                     logs a warning instead of info
        'record_loss'            - update eval cache, reset consecutive counter
        'blocked_same_corpus'    - invariant 2 precondition: corpus has not advanced
        'blocked_min_n'          - invariant 7: initial effective-N floor unmet
        'blocked_evidence_floor' - F3: < min_new_observations new evidence since last eval
        'blocked_fdr_unverified' - a win whose concept_gate.fdr_required is True but the
                                   caller did not prove (fdr_passed is not True) that BH-FDR
                                   multiplicity correction was actually applied and survived
                                   this round (todo 118 L-6); the guard applies to wins only
                                   -- a loss is always recorded regardless of fdr_required
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
    fdr_passed: bool | None = None,
) -> ComparisonDecision:
    """Pure decision core for one A/B comparison outcome against one concept.

    Ordering matters: status guard, then invariant 2's corpus-advance precondition,
    then invariant 7's initial floor, then F3's evidence-mass floor, then the
    FDR-verification guard (todo 118 L-6), then the win/loss bookkeeping.
    eval_metric is the challenger's mean ic_ci_lower over WIN strata (D-15 citation
    rule: never ic_value); eval_n is the challenger's summed n_independent over all
    compared strata (effective N, not raw bars).

    fdr_passed means "this outcome's win determination survived an actually-executed
    multiplicity correction across the strata compared this round". None means the
    caller ran no such correction -- which is NOT the same as False and must be
    treated as unproven, i.e. blocked, whenever state.fdr_required is True.
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

    # T-170-04 / todo 118 L-6: this guard applies to WINS only. A loss is never a
    # promotion and must still be recorded -- swallowing losses would keep a
    # decaying concept's consecutive counter alive, the opposite of fail-closed.
    if won and state.fdr_required and fdr_passed is not True:
        return ComparisonDecision(
            "blocked_fdr_unverified",
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

    if new_consecutive >= state.min_promotion_consecutive:
        if state.status == "candidate":
            baseline = sum(new_metrics) / len(new_metrics)
            return ComparisonDecision("promote", new_consecutive, new_metrics, baseline)
        if state.status != "active":
            # e.g. shadow_only (or any future non-candidate, non-active status):
            # only 'candidate' can ever reach 'promote' above, so this status is
            # stuck accumulating wins forever without this action. Distinct
            # action so the service layer logs it loudly instead of silently
            # recording another win (Phase 160 review finding 2).
            return ComparisonDecision(
                "record_win_not_promotable", new_consecutive, new_metrics, None
            )

    return ComparisonDecision("record_win", new_consecutive, new_metrics, None)


# ---------------------------------------------------------------------------
# Transactional apply (asyncpg)
# ---------------------------------------------------------------------------

# FOR UPDATE: locks both joined rows for the duration of the caller's
# transaction, so a concurrent evaluator for the same concept blocks here
# instead of reading a state this call is about to invalidate (Phase 160
# review finding 1 -- see record_comparison_outcome).
_LOAD_CONCEPT_SQL = """
    SELECT r.concept_id, r.status,
           g.promotion_consecutive, g.promotion_eval_metrics,
           g.last_eval_corpus_build_ref, g.last_eval_n,
           g.min_promotion_consecutive, g.min_new_observations, g.min_gate_n,
           g.fdr_required
    FROM concept_registry r
    JOIN concept_gate g USING (concept_id)
    WHERE r.domain = $1 AND r.name = $2
    FOR UPDATE
"""

# Invariant 9: compare-and-swap. _LOAD_CONCEPT_SQL's FOR UPDATE already makes a
# zero-row match unreachable in normal operation (the row is locked from load
# through this write in the same transaction) -- the `AND status = $3` predicate
# is kept as defense-in-depth against any future caller that reads this row
# without that lock. Zero rows updated means the status changed under us (or a
# rerun raced). L-5 correction (Phase 160 cross-AI review): the CAS matched zero
# rows, so no status change, transition, or gate update is executed - the empty
# transaction commits harmlessly (it does NOT roll back/abort; returning from
# inside `async with conn.transaction()` commits an empty transaction).
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

# L-2 (Phase 160 cross-AI review, finding 1): this read-modify-write carries no
# CAS of its own -- it is safe only because _LOAD_CONCEPT_SQL's FOR UPDATE holds
# the gate row locked from load through this write inside record_comparison_outcome's
# single transaction. Without that lock, a promote path racing a concurrent
# record_loss could commit a wrong status flip, not just a stale cache.
# L-2 closed by verification under Phase 170: no second CAS was added; the FOR
# UPDATE lock already provides the guarantee, and test_load_concept_sql_holds_row_lock
# pins both halves (the lock clause and the single conn.transaction() scope) as a
# regression test that fails if either is ever removed.
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


# ---------------------------------------------------------------------------
# Synchronous lifecycle path (psycopg, ic_engine's no-event-loop context)
# ---------------------------------------------------------------------------
#
# Ports FeatureRegistryService.record_transition_sync / advance_shadow_counters_sync /
# is_promotion_eligible (src/intelligence/feature_registry_service.py) onto the concept
# tables for todo 118 scope item 2 (Phase 170 Plan 04). Sits alongside the async
# record_comparison_outcome path above without disturbing it -- both halves of this
# class share the same concept_registry/concept_gate/concept_transition_log tables but
# serve different callers (asyncpg for ops_ensemble_weight_compare.py's ensemble_strategy
# domain, psycopg for ic_engine's feature-domain lifecycle hook in a no-event-loop
# context). This plan adds the capability only -- ic_engine/ensemble_trainer still call
# FeatureRegistryService until Plan 06 cuts the writers over.

_LOAD_CONCEPTS_SYNC_SQL = """
    SELECT r.name, r.status, r.group_name, r.is_control, r.control_expectation,
           g.min_gate_metric, g.min_gate_n, g.fdr_required, g.fdr_alpha,
           g.consecutive_shadow_passes, g.observations_since_demotion
    FROM concept_registry r
    JOIN concept_gate g USING (concept_id)
    WHERE r.domain = %s
"""

# CAS UPDATE: `AND status = %s` is the optimistic lock (invariant 9, mirrors
# _CAS_PROMOTE_SQL above) -- a stale from_status matches zero rows, the caller raises
# _TransitionNoOp, and the whole transaction (including any log INSERT) rolls back.
# `enabled = (%s = 'active')` maintains migration 284's enabled-tracks-status invariant
# in the SAME statement as the status write, never as a separate follow-up UPDATE.
_CAS_TRANSITION_SYNC_SQL = """
    UPDATE concept_registry
    SET status = %s, enabled = (%s = 'active')
    WHERE domain = %s AND name = %s AND status = %s
"""

# Demotion counter reset (Fable review N1, HIGH -- ported from feature_registry_service's
# record_transition_sync): whenever to_status == 'shadow_only', the recovery counters
# reset to 0 in the SAME transaction as the CAS UPDATE above, so a feature that decayed,
# recovered, and decayed again must re-earn the full evidence bar rather than re-promoting
# off a single passing run. Two statements rather than feature_registry's single one
# (the counters now live on concept_gate, a different table than status), but still
# inside the same conn.transaction() -- the atomicity property that made the original
# correct is preserved.
_RESET_SHADOW_COUNTERS_SYNC_SQL = """
    UPDATE concept_gate g
    SET consecutive_shadow_passes = 0,
        observations_since_demotion = 0
    FROM concept_registry r
    WHERE g.concept_id = r.concept_id AND r.domain = %s AND r.name = %s
"""

_TRANSITION_LOG_INSERT_SYNC_SQL = """
    INSERT INTO concept_transition_log
        (concept_id, domain, name, from_status, to_status, trigger_reason,
         corpus_build_ref, gate_metric, gate_n, ci_lower, notes)
    SELECT concept_id, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
    FROM concept_registry
    WHERE domain = %s AND name = %s
"""

_ADVANCE_SHADOW_COUNTERS_SYNC_SQL = """
    UPDATE concept_gate g
    SET consecutive_shadow_passes = CASE
            WHEN %s THEN g.consecutive_shadow_passes + 1
            ELSE 0
        END,
        observations_since_demotion = g.observations_since_demotion + %s
    FROM concept_registry r
    WHERE g.concept_id = r.concept_id AND r.domain = %s AND r.name = %s
"""

# Fallback lookup for record_transition_sync's L-6 FDR guard when the concept was never
# load_sync'ed (cold cache) -- the guard must not silently skip fail-closed enforcement
# just because the caller happened not to call load_sync first.
_FDR_REQUIRED_LOOKUP_SYNC_SQL = """
    SELECT g.fdr_required
    FROM concept_registry r
    JOIN concept_gate g USING (concept_id)
    WHERE r.domain = %s AND r.name = %s
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

    FDR enforcement is fail-closed inside this method (todo 118 L-6, Phase 170):
    concept_gate.fdr_required IS read here (_LOAD_CONCEPT_SQL), and a caller that
    cannot prove multiplicity correction was applied and survived this round
    (fdr_passed is not True) cannot record a win or a promotion for a concept whose
    gate requires it -- record_comparison_outcome's fdr_passed argument, threaded
    into decide_comparison_action's 'blocked_fdr_unverified' guard, makes this an
    invariant of the service, not a documented assumption a second caller could
    forget.
    """

    def __init__(self) -> None:
        """Initialise the sync-path in-memory cache.

        Does not disturb the async side above: record_comparison_outcome is fully
        stateless (every call takes its own conn) and continues to work correctly on
        an instance that was never load_sync'ed. self._concepts / self._loaded_domain
        exist solely for the synchronous psycopg path below.
        """
        self._concepts: dict[str, dict[str, Any]] = {}
        self._loaded_domain: str | None = None

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
        fdr_passed: bool | None = None,
    ) -> ComparisonDecision:
        """Apply one A/B comparison outcome for one concept, transactionally.

        The default_* floors are APR-resolved by the caller
        (alpha.concept_registry.<domain>_* keys); a non-NULL concept_gate column
        overrides its default. Blocked/noop decisions write nothing.

        fdr_passed (todo 118 L-6): "this outcome's win determination survived an
        actually-executed multiplicity correction across the strata compared this
        round". None means the caller ran none -- treated as unproven, i.e. blocked,
        whenever this concept's concept_gate.fdr_required is True. A caller whose
        gate does not require FDR (fdr_required=False) is unaffected regardless of
        what it passes here.

        The entire read-decide-write sequence runs inside one transaction, with
        _LOAD_CONCEPT_SQL's FOR UPDATE row lock held throughout: a concurrent
        evaluator for the same concept blocks on the lock instead of reading a
        state this call is about to invalidate (Phase 160 review finding 1).
        """
        async with conn.transaction():
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
                min_gate_n=(
                    row["min_gate_n"] if row["min_gate_n"] is not None else default_min_gate_n
                ),
                fdr_required=row["fdr_required"],
            )

            decision = decide_comparison_action(
                state,
                won=won,
                eval_metric=eval_metric,
                eval_n=eval_n,
                corpus_build_ref=corpus_build_ref,
                fdr_passed=fdr_passed,
            )

            if decision.action in (
                "noop_deprecated",
                "blocked_same_corpus",
                "blocked_min_n",
                "blocked_evidence_floor",
                "blocked_fdr_unverified",
            ):
                _logger.info(
                    "concept_registry.comparison_blocked",
                    domain=domain,
                    name=name,
                    action=decision.action,
                    corpus_build_ref=corpus_build_ref,
                    fdr_required=state.fdr_required,
                    fdr_passed=fdr_passed,
                )
                return decision

            now = datetime.now(UTC)
            metrics_list = list(decision.new_promotion_eval_metrics)

            async def _update_gate(sql: str, *args: Any, stage: str) -> None:
                """Run a gate UPDATE and crash loudly if the row vanished mid-transaction."""
                status = await conn.execute(sql, *args)
                if _rowcount(status) != 1:
                    raise RuntimeError(
                        f"concept_gate row vanished {stage} for domain={domain!r} "
                        f"name={name!r} concept_id={row['concept_id']!r}"
                    )

            if decision.action == "promote":
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
                await _update_gate(
                    _GATE_PROMOTE_UPDATE_SQL,
                    row["concept_id"],
                    eval_metric,
                    eval_n,
                    now,
                    corpus_build_ref,
                    decision.new_promotion_consecutive,
                    metrics_list,
                    decision.baseline_metric,
                    stage="mid-promote",
                )
                _logger.info(
                    "concept_registry.promoted",
                    domain=domain,
                    name=name,
                    baseline_metric=decision.baseline_metric,
                    corpus_build_ref=corpus_build_ref,
                )
                return decision

            # record_win / record_win_not_promotable / record_loss: eval-cache
            # bookkeeping only.
            await _update_gate(
                _GATE_CACHE_UPDATE_SQL,
                row["concept_id"],
                eval_metric,
                eval_n,
                now,
                corpus_build_ref,
                decision.new_promotion_consecutive,
                metrics_list,
                stage="mid-update",
            )
            if decision.action == "record_win_not_promotable":
                _logger.warning(
                    "concept_registry.win_not_promotable",
                    domain=domain,
                    name=name,
                    status=state.status,
                    promotion_consecutive=decision.new_promotion_consecutive,
                    corpus_build_ref=corpus_build_ref,
                )
            else:
                _logger.info(
                    "concept_registry.comparison_recorded",
                    domain=domain,
                    name=name,
                    action=decision.action,
                    corpus_build_ref=corpus_build_ref,
                )
            return decision

    # ------------------------------------------------------------------
    # Synchronous lifecycle path (psycopg, ic_engine's no-event-loop context)
    # ------------------------------------------------------------------

    def load_sync(self, conn: Any, domain: str) -> None:
        """Load all concept_registry+concept_gate rows for one domain via psycopg.

        Populates the in-memory cache keyed by name. Required by ic_engine.py
        (Plan 06), which uses psycopg throughout and has no running event loop.

        Deliberately NO row-count gate inside this method: FeatureRegistryService
        hard-coded `len(rows) == len(dataclasses.fields(FeatureVector))`, which
        imports a feature-domain dataclass into a cross-domain governance service.
        The alignment gate (registry names vs FeatureVector fields) stays the
        CALLER's responsibility -- it already is, since ic_engine/ensemble_trainer
        each run their own comparison against dataclasses.fields(FeatureVector).
        """
        with conn.cursor() as cur:
            cur.execute(_LOAD_CONCEPTS_SYNC_SQL, (domain,))
            rows = cur.fetchall()
            col_names = [desc[0] for desc in cur.description]

        self._concepts = {row[0]: dict(zip(col_names, row)) for row in rows}
        self._loaded_domain = domain
        _logger.info(
            "concept_registry.loaded_sync",
            domain=domain,
            n_concepts=len(self._concepts),
        )

    def _fdr_required_sync(self, conn: Any, domain: str, name: str) -> bool:
        """Resolve concept_gate.fdr_required for the L-6 promotion guard.

        Reads the in-memory cache when load_sync populated it; falls back to a
        direct DB read (inside the caller's transaction) when the cache is cold,
        so the fail-closed guard is never silently skipped just because the
        caller happened not to call load_sync first.
        """
        cached = self._concepts.get(name)
        if cached is not None:
            return bool(cached.get("fdr_required", False))
        with conn.cursor() as cur:
            cur.execute(_FDR_REQUIRED_LOOKUP_SYNC_SQL, (domain, name))
            row = cur.fetchone()
        return bool(row[0]) if row is not None else False

    def record_transition_sync(
        self,
        conn: Any,
        *,
        domain: str,
        name: str,
        from_status: str,
        to_status: str,
        reason: str,
        gate_metric: float | None = None,
        gate_n: float | None = None,
        ci_lower: float | None = None,
        corpus_build_ref: str | None = None,
        fdr_passed: bool | None = None,
        notes: str | None = None,
    ) -> bool:
        """Blocking, transactional, optimistic-locked lifecycle transition.

        Ports FeatureRegistryService.record_transition_sync's semantics onto the
        concept tables (todo 118 scope item 2). Deliberately `with conn.transaction():`,
        NEVER a bare `with conn:` -- ic_engine calls this repeatedly across many
        concepts on the SAME caller-owned connection, and psycopg (unlike psycopg2)
        closes the connection on a bare `with conn:` exit; conn.transaction()
        commits/rolls back the same way without closing (confirmed empirically for
        feature_registry_service's identical pattern).

        Guards, each raising ValueError BEFORE any write:
          - to_status == 'deprecated' and reason in _AUTOMATED_SYNC_REASONS --
            deprecated is operator-only.
          - reason not in concept_transition_log's CHECK vocabulary -- caught here
            in Python, with the offending value named, instead of as an opaque
            Postgres CHECK violation mid-transaction.

        L-6 fail-closed promotion guard (todo 118, mirrors Plan 02's async guard):
        when to_status == 'active' and this concept's concept_gate.fdr_required is
        true, a caller that cannot prove fdr_passed is True is refused -- logged at
        WARNING and returns False WITHOUT writing anything.

        CAS UPDATE carries `AND status = %s` (from_status) as an optimistic lock:
        zero rows matched means the concept was already transitioned by a prior or
        concurrent run, so the whole transaction (including the log INSERT) rolls
        back and this method returns False -- a rerun against an already-transitioned
        concept is a safe no-op, never a duplicate transition or orphan log row. The
        SAME UPDATE statement also maintains migration 284's `enabled = (status =
        'active')` invariant.

        Demotion counter reset (Fable review N1, HIGH): whenever to_status ==
        'shadow_only', a second statement (same transaction) resets
        consecutive_shadow_passes and observations_since_demotion to 0 on
        concept_gate -- without it, a concept that previously satisfied the
        recovery floors, got promoted, and later decays again would re-promote
        after a single passing run on its second shadow period instead of
        re-earning the full evidence bar.

        On a successful commit, mutates self._concepts[name] so a subsequent
        is_promotion_eligible read within the same process sees fresh state
        immediately, never stale data.

        Returns True if the transition was applied, False on optimistic-lock no-op
        or FDR-unverified block. Re-raises any other exception after the
        transaction rolls back.
        """
        if to_status == "deprecated" and reason in _AUTOMATED_SYNC_REASONS:
            raise ValueError(
                "automated transitions may not target deprecated; deprecated is operator-only"
            )
        if reason not in _VALID_TRANSITION_REASONS:
            raise ValueError(
                f"invalid trigger_reason {reason!r}: not in concept_transition_log's "
                f"CHECK vocabulary {sorted(_VALID_TRANSITION_REASONS)}"
            )

        reset_counters = to_status == "shadow_only"

        try:
            with conn.transaction():
                if to_status == "active":
                    fdr_required = self._fdr_required_sync(conn, domain, name)
                    if fdr_required and fdr_passed is not True:
                        _logger.warning(
                            "concept_registry.promotion_blocked_fdr_unverified",
                            domain=domain,
                            name=name,
                            fdr_passed=fdr_passed,
                        )
                        return False

                with conn.cursor() as cur:
                    cur.execute(
                        _CAS_TRANSITION_SYNC_SQL,
                        (to_status, to_status, domain, name, from_status),
                    )
                    if cur.rowcount == 0:
                        raise _TransitionNoOp()

                    if reset_counters:
                        cur.execute(_RESET_SHADOW_COUNTERS_SYNC_SQL, (domain, name))

                    cur.execute(
                        _TRANSITION_LOG_INSERT_SYNC_SQL,
                        (
                            domain,
                            name,
                            from_status,
                            to_status,
                            reason,
                            corpus_build_ref,
                            gate_metric,
                            gate_n,
                            ci_lower,
                            notes,
                            domain,
                            name,
                        ),
                    )
        except _TransitionNoOp:
            _logger.info(
                "concept_registry.transition_noop_sync",
                domain=domain,
                name=name,
                from_status=from_status,
                to_status=to_status,
                reason=reason,
            )
            return False
        except Exception as error:
            _logger.error(
                "concept_registry.transition_write_error_sync",
                domain=domain,
                name=name,
                from_status=from_status,
                to_status=to_status,
                error=str(error),
            )
            raise

        concept = self._concepts.get(name)
        if concept is not None:
            concept["status"] = to_status
            if reset_counters:
                concept["consecutive_shadow_passes"] = 0
                concept["observations_since_demotion"] = 0
        _logger.info(
            "concept_registry.transition_recorded_sync",
            domain=domain,
            name=name,
            from_status=from_status,
            to_status=to_status,
            reason=reason,
        )
        return True

    def advance_shadow_counters_sync(
        self,
        conn: Any,
        *,
        domain: str,
        name: str,
        passed: bool,
        new_observations: int,
    ) -> None:
        """Advance a shadow_only concept's recovery counters after a corpus run.

        The ONLY counter mutation path outside record_transition_sync's reset --
        there is no fail-counter for active concepts; demotion is decided by the
        caller's per-run materiality check, not by any registry counter (mirrors
        FeatureRegistryService.advance_shadow_counters_sync exactly).

        One conn.transaction() block: increments consecutive_shadow_passes if
        passed else resets it to 0, and always adds new_observations to
        observations_since_demotion. Mutates the in-memory cache to match on
        commit. Not a bare `with conn:` -- see record_transition_sync's docstring
        for why (psycopg closes the connection on that exit; this caller-owned
        connection is reused across many concepts per run).
        """
        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute(
                    _ADVANCE_SHADOW_COUNTERS_SYNC_SQL,
                    (passed, new_observations, domain, name),
                )

        concept = self._concepts.get(name)
        if concept is not None:
            if passed:
                concept["consecutive_shadow_passes"] = (
                    concept.get("consecutive_shadow_passes", 0) + 1
                )
            else:
                concept["consecutive_shadow_passes"] = 0
            concept["observations_since_demotion"] = (
                concept.get("observations_since_demotion", 0) + new_observations
            )
        _logger.info(
            "concept_registry.shadow_counters_advanced_sync",
            domain=domain,
            name=name,
            passed=passed,
            new_observations=new_observations,
        )

    def is_promotion_eligible(
        self,
        name: str,
        recovery_min_observations: int,
        recovery_min_passes: int,
    ) -> bool:
        """Evidence-only shadow_only -> active promotion predicate.

        True iff consecutive_shadow_passes >= recovery_min_passes AND
        observations_since_demotion >= recovery_min_observations, read from the
        in-memory cache. Both floors are caller-supplied (APR-sourced by the
        caller) -- never hard-coded here. No calendar/date input is consulted;
        recovery is evidence-only.

        Returns False for an unknown name.
        """
        concept = self._concepts.get(name)
        if concept is None:
            return False
        passes = concept.get("consecutive_shadow_passes", 0)
        observations = concept.get("observations_since_demotion", 0)
        return passes >= recovery_min_passes and observations >= recovery_min_observations

    def get_all_concepts(self) -> list[dict[str, Any]]:
        """Return ALL loaded concepts regardless of status.

        The alignment-gate/status-map read ic_engine and ensemble_trainer need in
        Plan 06 (mirrors FeatureRegistryService.get_all_features). Empty before
        load_sync is called.
        """
        return list(self._concepts.values())

    def get_concept(self, name: str) -> dict[str, Any] | None:
        """O(1) single-concept lookup (mirrors FeatureRegistryService.get_feature).

        Callers needing one concept's record must use this, not
        `next((c for c in get_all_concepts() if c["name"] == name), None)` --
        that pattern materializes and linearly scans the full concept list
        (2026-08-04 simplify-pass finding, ~249 rows) for what should be a
        single dict lookup. Returns None for an unknown name.
        """
        return self._concepts.get(name)
