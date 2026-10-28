"""ConceptRegistryService - Concept Registry writer for identity and status (todo 058, 187-12).

Invariant 1 (docs/foundation/unified-concept-registry.md): proposal and decision are
different roles, structurally. This service is the only code path that flips
concept_registry.status (record_transition) and the only one that logs a new idea
(register_idea). Recipes and attempts are the S6 ledger's; feature evaluations reach the
registry through feature_lifecycle. No LLM anywhere in the path.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

import structlog

from src.core.service_utils import format_iso_ts

_logger = structlog.get_logger()

# Automated transition reasons (the feature_lifecycle node writes data_quality_fail and
# data_quality_restored, migration 387). 'operator_override' is the only path to
# 'deprecated' (ops_concept_registry_override.py).
_AUTOMATED_REASONS = frozenset(
    {"promotion", "demotion_performance", "data_quality_fail", "data_quality_restored"}
)

# concept_transition_log.trigger_reason's full CHECK vocabulary (migrations 225, 387).
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
        "data_quality_fail",
        "data_quality_restored",
    }
)


# ---------------------------------------------------------------------------
# Generic lifecycle transition (record_transition below)
# ---------------------------------------------------------------------------
#
# Todo 402: the one status-flip path. Called by the feature_lifecycle node (automated promotion/demotion derived from concept_evaluation)
# and by ops_concept_registry_override.py (operator_override). The psycopg twins
# ic_engine's in-process lifecycle hook used, and the concept_gate run counters they
# advanced, were deleted with that hook.

# FOR UPDATE: the row stays locked from
# the fdr_required read through the CAS write inside one transaction.
_LOAD_TRANSITION_TARGET_SQL = """
    SELECT r.concept_id, g.fdr_required
    FROM concept_registry r
    JOIN concept_gate g USING (concept_id)
    WHERE r.domain = $1 AND r.name = $2
    FOR UPDATE OF r
"""

# CAS UPDATE (invariant 9): `AND status = $4` is the optimistic lock. `enabled` tracks
# status in the same statement (migration 284's enabled = (status = 'active') invariant).
_CAS_TRANSITION_SQL = """
    UPDATE concept_registry
    SET status = $1, enabled = ($1 = 'active')
    WHERE concept_id = $2 AND domain = $3 AND status = $4
"""

_TRANSITION_LOG_INSERT_SQL = """
    INSERT INTO concept_transition_log
        (concept_id, domain, name, from_status, to_status, trigger_reason,
         corpus_build_ref, gate_metric, gate_n, ci_lower, notes)
    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
"""


# The typed domains (concept_registry_domain_check, design 10.2.5).
TYPED_DOMAINS = frozenset(
    {"feature", "family", "member", "combiner", "construction_rule", "book", "method"}
)

# Domains an idea can be logged in. A feature row needs a concept_gate row and a kernel, which
# arrive with the feature kernel registry, so a feature idea is refused here (a gate-less
# candidate could never pass record_transition's inner join).
IDEA_DOMAINS = TYPED_DOMAINS - {"feature"}

# ON CONFLICT DO NOTHING returns no row on a duplicate, so the check and the insert are one
# statement and two concurrent callers cannot both win.
_REGISTER_IDEA_SQL = """
    INSERT INTO concept_registry (domain, name, description, status, enabled, metadata)
    VALUES ($1, $2, $3, 'candidate', false, $4)
    ON CONFLICT (domain, name) DO NOTHING
    RETURNING concept_id
"""


class TransitionResult(StrEnum):
    """What record_transition did. The two refusals are distinct because only a lock
    miss is fixed by rerunning; an FDR block needs the caller to attest fdr_passed."""

    APPLIED = "applied"
    LOCK_MISS = "lock_miss"
    FDR_BLOCKED = "fdr_blocked"


class ConceptNotFoundError(Exception):
    """No concept_registry+concept_gate row for the given (domain, name)."""


class ConceptExistsError(Exception):
    """register_idea found the (domain, name) already registered."""


def _rowcount(execute_status: str) -> int:
    """Parse asyncpg's execute() status string ('UPDATE 1' -> 1)."""
    return int(execute_status.rsplit(" ", 1)[-1])


class ConceptRegistryService:
    """Narrowly-scoped Concept Registry writer (invariant 1).

    Stateless: every method takes an asyncpg connection. record_transition is the one
    status-flipping path (the feature_lifecycle node's derived promotions and demotions,
    and operator overrides); it cannot target 'deprecated' with an automated reason or
    write annotation content. register_idea logs a new candidate with no recipe.

    FDR enforcement is fail-closed (todo 118 L-6): concept_gate.fdr_required is read
    under the row lock, and a caller that cannot prove multiplicity correction survived
    (fdr_passed is not True) cannot promote a concept whose gate requires it.
    """

    async def register_idea(
        self,
        conn: Any,
        *,
        domain: str,
        name: str,
        description: str,
        sources: list[str],
        author: str,
    ) -> str:
        """Log an idea the day it is had: one `candidate` row, no recipe, no gate.

        Returns the new concept_id. An unknown domain raises before any SQL; an existing
        (domain, name) raises ConceptExistsError, never an overwrite. Recipes and attempts
        are the S6 ledger's to write.
        """
        if domain not in IDEA_DOMAINS:
            raise ValueError(f"invalid idea domain {domain!r}: not one of {sorted(IDEA_DOMAINS)}")
        if not name.strip() or not description.strip():
            raise ValueError("an idea needs a non-empty name and description")
        metadata = {
            "description": description,
            "sources": sources,
            "author": author,
            "logged_at": format_iso_ts(datetime.now(UTC)),
        }
        concept_id = await conn.fetchval(_REGISTER_IDEA_SQL, domain, name, description, metadata)
        if concept_id is None:
            raise ConceptExistsError(f"concept_registry already has {domain}/{name}")
        _logger.info("concept_registry.idea_registered", domain=domain, name=name, author=author)
        return str(concept_id)

    async def record_transition(
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
    ) -> TransitionResult:
        """Transactional, optimistic-locked lifecycle transition (todo 402).

        Guards, each raising ValueError before any write:
          - to_status == 'deprecated' with an automated reason -- deprecated is
            operator-only.
          - reason outside concept_transition_log's CHECK vocabulary -- named here
            instead of surfacing as an opaque CHECK violation mid-transaction.

        L-6 fail-closed promotion guard (todo 118): when to_status == 'active' and the
        concept's concept_gate.fdr_required is true, a caller that cannot prove
        fdr_passed is True is refused -- logged at WARNING, returns FDR_BLOCKED, writes
        nothing.

        The CAS UPDATE carries `AND status = from_status`: zero rows matched means the
        concept already moved (a prior or concurrent writer), so nothing is written and
        this returns LOCK_MISS -- a rerun is a safe no-op, never a duplicate transition or
        an orphan log row. Raises ConceptNotFoundError for an unknown (domain, name).
        """
        if to_status == "deprecated" and reason in _AUTOMATED_REASONS:
            raise ValueError(
                "automated transitions may not target deprecated; deprecated is operator-only"
            )
        if reason not in _VALID_TRANSITION_REASONS:
            raise ValueError(
                f"invalid trigger_reason {reason!r}: not in concept_transition_log's "
                f"CHECK vocabulary {sorted(_VALID_TRANSITION_REASONS)}"
            )

        async with conn.transaction():
            target = await conn.fetchrow(_LOAD_TRANSITION_TARGET_SQL, domain, name)
            if target is None:
                raise ConceptNotFoundError(
                    f"no concept_registry+concept_gate row for {domain}/{name}"
                )
            # data_quality_restored is exempt for feature concepts only: feature status is
            # data quality (design 11), not a statistical selection, and selection
            # multiplicity is counted in research (E15-E17), so an FDR attestation would be
            # false. Any other domain passing that reason is still fail-closed.
            if (
                to_status == "active"
                and not (reason == "data_quality_restored" and domain == "feature")
                and target["fdr_required"]
                and fdr_passed is not True
            ):
                _logger.warning(
                    "concept_registry.promotion_blocked_fdr_unverified",
                    domain=domain,
                    name=name,
                    fdr_passed=fdr_passed,
                )
                return TransitionResult.FDR_BLOCKED
            updated = await conn.execute(
                _CAS_TRANSITION_SQL, to_status, target["concept_id"], domain, from_status
            )
            if _rowcount(updated) == 0:
                _logger.info(
                    "concept_registry.transition_noop",
                    domain=domain,
                    name=name,
                    from_status=from_status,
                    to_status=to_status,
                    reason=reason,
                )
                return TransitionResult.LOCK_MISS
            await conn.execute(
                _TRANSITION_LOG_INSERT_SQL,
                target["concept_id"],
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
            )

        _logger.info(
            "concept_registry.transition_recorded",
            domain=domain,
            name=name,
            from_status=from_status,
            to_status=to_status,
            reason=reason,
        )
        return TransitionResult.APPLIED
