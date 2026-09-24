#!/usr/bin/env python3
"""
ops_concept_registry_override.py — operator actuator for concept_registry lifecycle
transitions (todo 117; Phase 170 Plan 07 repoint from this script's predecessor,
git-renamed to this filename).

`ConceptRegistryService.record_transition` guards that automated transitions
(`promotion`/`demotion_performance`, both driven by `services/feature_lifecycle.py`)
may never target `deprecated` -- deprecated is operator-only. This script is the only
sanctioned path to that transition: it reads the concept's current status, calls
record_transition with reason='operator_override' (a CHECK-permitted
concept_transition_log.trigger_reason value), and prints the result. Every manual
intervention now goes through the same optimistic-locked, transactional write path
as an automated transition, and lands in concept_transition_log -- a manual SQL
UPDATE against concept_registry directly bypasses that audit trail entirely and is
forbidden.

--domain (new in this repoint, default 'feature'): the actuator now sits on a
cross-domain registry (concept_registry also carries domain='ensemble_strategy'
rows), so the domain is never hard-coded into the script itself.

Note on --reason: concept_transition_log.trigger_reason is a CHECK-constrained enum
with no free-text column -- there's nowhere in the schema to persist an operator's
free-text justification today (same gap todo 011 closed out noting; see todo 117's
own writeup). --reason is therefore logged to stdout/structlog for the operator's
own audit trail, not written to the DB row itself.

Usage:
    python scripts/ops/alpha/ops_concept_registry_override.py \
        --domain feature --feature-name days_to_month_end --to-status deprecated \
        --reason "exact affine complement of month_position, removed structurally (todo 115)"
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

import structlog

from src.config.settings import Settings
from src.core.database_manager import connect_with_codecs
from src.intelligence.concept_registry_service import ConceptRegistryService, TransitionResult

_logger = structlog.get_logger()

_VALID_STATUSES = ("candidate", "active", "shadow_only", "deprecated")
_DEFAULT_DOMAIN = "feature"


# JOIN concept_gate: the same population record_transition can act on (migration 284's
# gate-less tombstone rows report not-found here instead of raising there).
_CURRENT_STATUS_SQL = """
    SELECT r.status FROM concept_registry r JOIN concept_gate g USING (concept_id)
    WHERE r.domain = $1 AND r.name = $2
"""


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--domain",
        default=_DEFAULT_DOMAIN,
        help=(
            "concept_registry domain to target (default: 'feature'). The actuator "
            "sits on a cross-domain registry -- do not hard-code one domain into it."
        ),
    )
    parser.add_argument("--feature-name", required=True, help="concept_registry.name value.")
    parser.add_argument(
        "--to-status",
        required=True,
        choices=_VALID_STATUSES,
        help=(
            "Target lifecycle status. 'active' additionally requires --fdr-passed "
            "whenever the concept's concept_gate.fdr_required is true (the default "
            "for every seeded concept) -- see --fdr-passed."
        ),
    )
    parser.add_argument(
        "--reason",
        required=True,
        help="Free-text justification, logged but not persisted to the DB row (see module docstring).",
    )
    parser.add_argument(
        "--fdr-passed",
        action="store_true",
        help=(
            "Operator attestation that this concept's promotion to 'active' has been "
            "separately verified to survive BH-FDR multiplicity correction. Required "
            "to promote any concept whose concept_gate.fdr_required is true (the "
            "seeded default) -- record_transition fail-closes without it."
        ),
    )
    args = parser.parse_args()

    settings = Settings()
    dsn = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
    return asyncio.run(_override(dsn, args))


async def _override(dsn: str, args: argparse.Namespace) -> int:
    conn = await connect_with_codecs(dsn)
    try:
        from_status = await conn.fetchval(_CURRENT_STATUS_SQL, args.domain, args.feature_name)
        if from_status is None:
            _logger.error(
                "ops_concept_registry_override.not_found",
                domain=args.domain,
                feature_name=args.feature_name,
            )
            return 1

        if from_status == args.to_status:
            _logger.warning(
                "ops_concept_registry_override.noop_already_at_target",
                domain=args.domain,
                feature_name=args.feature_name,
                status=from_status,
            )
            return 0

        # record_transition runs in its own transaction and commits on success.
        result = await ConceptRegistryService().record_transition(
            conn,
            domain=args.domain,
            name=args.feature_name,
            from_status=from_status,
            to_status=args.to_status,
            reason="operator_override",
            fdr_passed=args.fdr_passed,
            notes=args.reason,
        )

        if result is TransitionResult.FDR_BLOCKED:
            _logger.error(
                "ops_concept_registry_override.blocked_fdr_unverified",
                domain=args.domain,
                feature_name=args.feature_name,
                hint=(
                    "concept_gate.fdr_required is true for this concept -- rerun with "
                    "--fdr-passed once BH-FDR correction has been separately verified "
                    "for this promotion"
                ),
            )
            return 1
        if result is TransitionResult.LOCK_MISS:
            _logger.error(
                "ops_concept_registry_override.optimistic_lock_miss",
                domain=args.domain,
                feature_name=args.feature_name,
                expected_from_status=from_status,
                hint="status changed between read and write -- rerun to pick up the new status",
            )
            return 1

        _logger.info(
            "ops_concept_registry_override.applied",
            domain=args.domain,
            feature_name=args.feature_name,
            from_status=from_status,
            to_status=args.to_status,
            operator_reason=args.reason,
        )
        return 0
    finally:
        await conn.close()


if __name__ == "__main__":
    sys.exit(main())
