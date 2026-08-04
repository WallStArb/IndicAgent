#!/usr/bin/env python3
"""
ops_concept_feature_migration_verify.py -- Phase 170 Plan 03 parity verifier (todo 118).

Re-runnable, self-failing assertion of full parity between feature_registry and its
concept_registry/concept_gate/concept_parent fold-in (migration 284). Exits 1 on ANY
mismatch, 0 only on total agreement across all eleven checks below. Exists so the parity
claim is a command anyone can re-run, not a one-time eyeball at migration time -- Plan 06
and Plan 08 both re-run this as a gate before repointing consumers / dropping
feature_registry.

Checks, each independently reported PASS/FAIL:
   1. row-count parity
   2. name-set parity (symmetric difference reported on failure)
   3. per-feature status parity
   4. enabled invariant (enabled = (status='active'))
   5. gate parity (min_gate_metric/min_gate_n/fdr_required/fdr_alpha/
      consecutive_shadow_passes/observations_since_demotion)
   6. lineage parity (parent-name sets, not counts -- a count check would pass on a
      swapped pair)
   7. control parity (is_control/control_expectation)
   8. group_name parity
   9. metadata completeness (tier/normalization/formula_short all non-NULL)
  10. transition-log replay completeness (count parity + per-row match)
  11. no-duplication check (genesis_seed and replay rows each appear at most once) --
      catches a migration 284 re-applied without its idempotency guards, the failure mode
      that would otherwise surface only as a confusing assertion abort inside the
      migration itself or Plan 08's pre-drop guard.

TOMBSTONE ROWS: migration 284 seeds a small number of concept_registry rows
(metadata->>'migrated_from'='feature_transition_log') for feature_transition_log
feature_names with no corresponding feature_registry row (features fully removed from
feature_registry, not just deprecated). These carry no feature_registry counterpart and
are deliberately EXCLUDED from checks 1-9 (row-count/name-set/status/gate/control/
group_name/metadata parity all compare feature_registry against its
metadata->>'migrated_from'='feature_registry' counterpart); they are exactly what checks
10/11 need to exist so the transition-log replay has somewhere to attach.

Gracefully reports (not crash) once feature_registry has been dropped (Phase 170 Plan 08):
prints a SKIPPED line and exits 0, so this never becomes a permanently-broken command.

Usage:
    python scripts/ops/alpha/ops_concept_feature_migration_verify.py
    python scripts/ops/alpha/ops_concept_feature_migration_verify.py --json
"""

from __future__ import annotations

import argparse
import asyncio
import json as json_module
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from src.config.settings import Settings
from src.core.database_manager import connect_with_codecs

# Scopes checks 1-9 to the 249 real feature-domain rows, excluding the tombstone rows
# seeded for orphaned feature_transition_log entries (see module docstring).
_REAL_ROW_SCOPE = "domain='feature' AND metadata->>'migrated_from'='feature_registry'"


async def _check_row_count_parity(conn: Any) -> dict[str, Any]:
    fr_count = await conn.fetchval("SELECT count(*) FROM feature_registry")
    cr_count = await conn.fetchval(f"SELECT count(*) FROM concept_registry WHERE {_REAL_ROW_SCOPE}")
    passed = fr_count == cr_count
    return {
        "name": "row_count_parity",
        "passed": passed,
        "detail": f"feature_registry={fr_count}, concept_registry(feature, non-tombstone)={cr_count}",
    }


async def _check_name_set_parity(conn: Any) -> dict[str, Any]:
    fr_names = {
        r["feature_name"] for r in await conn.fetch("SELECT feature_name FROM feature_registry")
    }
    cr_names = {
        r["name"]
        for r in await conn.fetch(f"SELECT name FROM concept_registry WHERE {_REAL_ROW_SCOPE}")
    }
    only_fr = sorted(fr_names - cr_names)
    only_cr = sorted(cr_names - fr_names)
    passed = not only_fr and not only_cr
    detail = (
        "exact match"
        if passed
        else f"only_in_feature_registry={only_fr}, only_in_concept_registry={only_cr}"
    )
    return {"name": "name_set_parity", "passed": passed, "detail": detail}


async def _check_status_parity(conn: Any) -> dict[str, Any]:
    rows = await conn.fetch("""
        SELECT fr.feature_name
        FROM feature_registry fr
        JOIN concept_registry cr ON cr.domain='feature' AND cr.name = fr.feature_name
        WHERE cr.status IS DISTINCT FROM fr.status
        """)
    passed = len(rows) == 0
    detail = (
        "zero mismatches"
        if passed
        else f"{len(rows)} mismatches: {sorted(r['feature_name'] for r in rows)}"
    )
    return {"name": "status_parity", "passed": passed, "detail": detail}


async def _check_enabled_invariant(conn: Any) -> dict[str, Any]:
    rows = await conn.fetch(
        "SELECT name FROM concept_registry WHERE domain='feature' AND enabled <> (status='active')"
    )
    passed = len(rows) == 0
    detail = (
        "invariant holds"
        if passed
        else f"{len(rows)} violations: {sorted(r['name'] for r in rows)}"
    )
    return {"name": "enabled_invariant", "passed": passed, "detail": detail}


async def _check_gate_parity(conn: Any) -> dict[str, Any]:
    rows = await conn.fetch("""
        SELECT fr.feature_name
        FROM feature_registry fr
        JOIN concept_registry cr ON cr.domain='feature' AND cr.name = fr.feature_name
        JOIN concept_gate cg ON cg.concept_id = cr.concept_id
        WHERE cg.min_gate_metric IS DISTINCT FROM fr.min_ic_sharpe
           OR cg.min_gate_n IS DISTINCT FROM fr.min_ic_n
           OR cg.fdr_required IS DISTINCT FROM fr.fdr_required
           OR cg.fdr_alpha IS DISTINCT FROM fr.fdr_alpha
           OR cg.consecutive_shadow_passes IS DISTINCT FROM fr.consecutive_shadow_passes
           OR cg.observations_since_demotion IS DISTINCT FROM fr.observations_since_demotion
        """)
    passed = len(rows) == 0
    detail = (
        "zero mismatches"
        if passed
        else f"{len(rows)} mismatches: {sorted(r['feature_name'] for r in rows)}"
    )
    return {"name": "gate_parity", "passed": passed, "detail": detail}


async def _check_lineage_parity(conn: Any) -> dict[str, Any]:
    fr_rows = await conn.fetch(
        "SELECT feature_name, parent_features FROM feature_registry WHERE parent_features IS NOT NULL"
    )
    mismatches: list[str] = []
    for r in fr_rows:
        expected_parents = set(r["parent_features"])
        actual_rows = await conn.fetch(
            """
            SELECT p.name
            FROM concept_parent cp
            JOIN concept_registry c ON c.concept_id = cp.child_concept_id AND c.domain='feature' AND c.name = $1
            JOIN concept_registry p ON p.concept_id = cp.parent_concept_id
            """,
            r["feature_name"],
        )
        actual_parents = {a["name"] for a in actual_rows}
        if actual_parents != expected_parents:
            mismatches.append(
                f"{r['feature_name']}: expected={sorted(expected_parents)} actual={sorted(actual_parents)}"
            )
    passed = len(mismatches) == 0
    detail = "all lineage sets match" if passed else f"{len(mismatches)} mismatches: {mismatches}"
    return {"name": "lineage_parity", "passed": passed, "detail": detail}


async def _check_control_parity(conn: Any) -> dict[str, Any]:
    rows = await conn.fetch("""
        SELECT fr.feature_name
        FROM feature_registry fr
        JOIN concept_registry cr ON cr.domain='feature' AND cr.name = fr.feature_name
        WHERE cr.is_control IS DISTINCT FROM fr.is_control
           OR cr.control_expectation IS DISTINCT FROM fr.control_expectation
        """)
    passed = len(rows) == 0
    detail = (
        "zero mismatches"
        if passed
        else f"{len(rows)} mismatches: {sorted(r['feature_name'] for r in rows)}"
    )
    return {"name": "control_parity", "passed": passed, "detail": detail}


async def _check_group_name_parity(conn: Any) -> dict[str, Any]:
    rows = await conn.fetch("""
        SELECT fr.feature_name
        FROM feature_registry fr
        JOIN concept_registry cr ON cr.domain='feature' AND cr.name = fr.feature_name
        WHERE cr.group_name IS DISTINCT FROM fr.group_name
        """)
    passed = len(rows) == 0
    detail = (
        "zero mismatches"
        if passed
        else f"{len(rows)} mismatches: {sorted(r['feature_name'] for r in rows)}"
    )
    return {"name": "group_name_parity", "passed": passed, "detail": detail}


async def _check_metadata_completeness(conn: Any) -> dict[str, Any]:
    rows = await conn.fetch(f"""
        SELECT name FROM concept_registry
        WHERE {_REAL_ROW_SCOPE}
          AND (metadata->>'tier' IS NULL OR metadata->>'normalization' IS NULL
               OR metadata->>'formula_short' IS NULL)
        """)
    passed = len(rows) == 0
    detail = (
        "all metadata complete"
        if passed
        else f"{len(rows)} incomplete: {sorted(r['name'] for r in rows)}"
    )
    return {"name": "metadata_completeness", "passed": passed, "detail": detail}


async def _check_replay_completeness(conn: Any) -> dict[str, Any]:
    ftl_count = await conn.fetchval("SELECT count(*) FROM feature_transition_log")
    replayed_count = await conn.fetchval(
        "SELECT count(*) FROM concept_transition_log "
        "WHERE domain='feature' AND notes LIKE 'Replayed from feature_transition_log%'"
    )
    count_ok = ftl_count == replayed_count

    missing = await conn.fetch("""
        SELECT ftl.id, ftl.feature_name
        FROM feature_transition_log ftl
        WHERE NOT EXISTS (
            SELECT 1 FROM concept_transition_log t
            WHERE t.domain = 'feature'
              AND t.name = ftl.feature_name
              AND t.from_status = ftl.from_status
              AND t.to_status = ftl.to_status
              AND t.triggered_at = ftl.triggered_at
              AND t.notes = 'Replayed from feature_transition_log id=' || ftl.id
                            || ' (Phase 170, todo 118).'
        )
        """)
    passed = count_ok and len(missing) == 0
    if passed:
        detail = f"count parity ok ({ftl_count}=={replayed_count}), all rows matched"
    else:
        missing_desc = [f"id={m['id']} ({m['feature_name']})" for m in missing]
        detail = (
            f"count parity={count_ok} ({ftl_count} vs {replayed_count}), missing={missing_desc}"
        )
    return {"name": "replay_completeness", "passed": passed, "detail": detail}


async def _check_no_duplication(conn: Any) -> dict[str, Any]:
    genesis_dupes = await conn.fetch("""
        SELECT domain, name, count(*) AS n
        FROM concept_transition_log
        WHERE domain='feature' AND trigger_reason='genesis_seed'
        GROUP BY domain, name HAVING count(*) > 1
        """)
    replay_dupes = await conn.fetch("""
        SELECT notes, count(*) AS n
        FROM concept_transition_log
        WHERE domain='feature' AND notes LIKE 'Replayed from feature_transition_log%'
        GROUP BY notes HAVING count(*) > 1
        """)
    passed = len(genesis_dupes) == 0 and len(replay_dupes) == 0
    if passed:
        detail = "no duplicates found"
    else:
        genesis_desc = [f"{d['name']}x{d['n']}" for d in genesis_dupes]
        replay_desc = [f"{d['notes']}x{d['n']}" for d in replay_dupes]
        detail = f"genesis_dupes={genesis_desc}, replay_dupes={replay_desc}"
    return {"name": "no_duplication", "passed": passed, "detail": detail}


_CHECKS = [
    _check_row_count_parity,
    _check_name_set_parity,
    _check_status_parity,
    _check_enabled_invariant,
    _check_gate_parity,
    _check_lineage_parity,
    _check_control_parity,
    _check_group_name_parity,
    _check_metadata_completeness,
    _check_replay_completeness,
    _check_no_duplication,
]


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit a machine-readable JSON result dict alongside the human summary.",
    )
    return parser.parse_args()


async def main() -> int:
    args = _parse_args()
    settings = Settings()
    dsn = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
    conn = await connect_with_codecs(dsn)

    try:
        fr_exists = await conn.fetchval("SELECT to_regclass('public.feature_registry')")
        if fr_exists is None:
            print(
                "SKIPPED: feature_registry has been dropped (Phase 170 Plan 08 complete); "
                "parity is no longer checkable"
            )
            if args.json:
                print(json_module.dumps({"skipped": True, "reason": "feature_registry dropped"}))
            return 0

        print("# feature_registry <-> concept_registry Parity Report\n")

        results = []
        for check in _CHECKS:
            result = await check(conn)
            results.append(result)
            status = "PASS" if result["passed"] else "FAIL"
            print(f"[{status}] {result['name']}: {result['detail']}")

        n_failed = sum(1 for r in results if not r["passed"])
        ok = n_failed == 0

        print()
        if ok:
            print("VERDICT: PASS")
        else:
            print(f"VERDICT: FAIL ({n_failed} checks failed)")

        if args.json:
            print(
                json_module.dumps({"ok": ok, "n_failed": n_failed, "checks": results}, default=str)
            )

        return 0 if ok else 1
    finally:
        await conn.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
