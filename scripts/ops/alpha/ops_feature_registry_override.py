#!/usr/bin/env python3
"""
ops_feature_registry_override.py — operator actuator for feature_registry lifecycle
transitions (todo 117).

`FeatureRegistryService.record_transition_sync` correctly guards that automated
transitions (`ic_promotion`/`ic_demotion`, both driven by `ic_engine.py`) may never
target `deprecated` -- deprecated is operator-only. But before this script, nothing
called `record_transition_sync` with `reason='operator_override'` anywhere in the
codebase: an operator who wanted to kill a bad feature had no way to do it except a
manual SQL UPDATE against feature_registry directly, bypassing feature_transition_log
entirely and defeating the audit trail the whole registry exists for.

This script is that actuator. It reads the feature's current status, calls
record_transition_sync with reason='operator_override' (the only trigger_reason value
CHECK-permitted for a manual transition), and prints the result. Every manual
intervention now goes through the same optimistic-locked, transactional write path as
an automated transition, and lands in feature_transition_log.

Note on --reason: feature_transition_log.trigger_reason is a CHECK-constrained enum
(ic_promotion/ic_demotion/parent_cascade/operator_override) with no free-text column --
there's nowhere in the schema to persist an operator's free-text justification today
(same gap todo 011 closed out noting; see todo 117's own writeup). --reason is
therefore logged to stdout/structlog for the operator's own audit trail, not written to
the DB row itself.

Usage:
    python scripts/ops/alpha/ops_feature_registry_override.py \
        --feature-name days_to_month_end --to-status deprecated \
        --reason "exact affine complement of month_position, removed structurally (todo 115)"
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

import structlog

from services._batch_utils import connect_db_from_url
from src.config.settings import Settings
from src.intelligence.feature_registry_service import FeatureRegistryService

_logger = structlog.get_logger()

_VALID_STATUSES = ("candidate", "active", "shadow_only", "deprecated")


def _current_status(conn, feature_name: str) -> str | None:
    with conn.cursor() as cur:
        cur.execute("SELECT status FROM feature_registry WHERE feature_name = %s", (feature_name,))
        row = cur.fetchone()
    return row[0] if row else None


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--feature-name", required=True)
    parser.add_argument("--to-status", required=True, choices=_VALID_STATUSES)
    parser.add_argument(
        "--reason",
        required=True,
        help="Free-text justification, logged but not persisted to the DB row (see module docstring).",
    )
    args = parser.parse_args()

    settings = Settings()
    dsn = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
    conn = connect_db_from_url(dsn)

    try:
        from_status = _current_status(conn, args.feature_name)
        if from_status is None:
            _logger.error(
                "ops_feature_registry_override.feature_not_found", feature_name=args.feature_name
            )
            return 1

        if from_status == args.to_status:
            _logger.warning(
                "ops_feature_registry_override.noop_already_at_target",
                feature_name=args.feature_name,
                status=from_status,
            )
            return 0

        registry = FeatureRegistryService()
        applied = registry.record_transition_sync(
            conn,
            feature_name=args.feature_name,
            from_status=from_status,
            to_status=args.to_status,
            reason="operator_override",
        )

        if not applied:
            _logger.error(
                "ops_feature_registry_override.optimistic_lock_miss",
                feature_name=args.feature_name,
                expected_from_status=from_status,
                hint="status changed between read and write -- rerun to pick up the new status",
            )
            return 1

        _logger.info(
            "ops_feature_registry_override.applied",
            feature_name=args.feature_name,
            from_status=from_status,
            to_status=args.to_status,
            operator_reason=args.reason,
        )
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
