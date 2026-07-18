"""
Controlled Vocabulary API Routes — Phase 161

Read-only metadata endpoint over the Controlled Vocabulary tables
(`controlled_vocabulary` / `vocabulary_group_member`, migration 239/240). Lets any
external consumer enumerate a namespace's codes/labels/groups over HTTP without
importing Python or hardcoding labels. Not a dashboard/UI — see
`.planning/phases/161-controlled-vocabulary-system-planned/161-04-PLAN.md`.

T-161-01 (SQL-injection mitigation): `namespace` is bound as a parameterized query
argument ($1) and never string-interpolated into SQL.
"""

from __future__ import annotations

import asyncio
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException

from ...core.database_manager import DatabaseManager
from ..dependencies import get_db_manager

logger = structlog.get_logger(__name__)

router = APIRouter()


@router.get("/{namespace}")
async def get_vocabulary(
    namespace: str,
    db_manager: DatabaseManager = Depends(get_db_manager),
) -> dict[str, Any]:
    """Return codes/labels/groups for a Controlled Vocabulary namespace.

    Unknown namespaces (zero matching rows) return a 404 rather than a raw SQL error
    or an empty 200 — the design doc's "validate namespace against the known set"
    intent (T-161-07). A genuine backend failure on the primary codes query (pool
    exhaustion, DB unreachable, query timeout) returns 503 instead, since collapsing
    both cases into 404 makes a transient outage indistinguishable from "this
    namespace was never registered" to any caller/monitor.
    """
    # Both queries are independent (neither depends on the other's result) -- fetch
    # concurrently instead of paying two sequential round-trips. The group query is a
    # single LEFT JOIN so a real-but-currently-empty group still appears with an empty
    # codes list, matching VocabularyService.group_codes()'s same "known vs unknown"
    # distinction.
    code_result, group_result = await asyncio.gather(
        db_manager.fetch(
            "SELECT code, label, description, sort_order, is_deprecated "
            "FROM controlled_vocabulary WHERE namespace = $1 ORDER BY sort_order, code",
            namespace,
        ),
        db_manager.fetch(
            "SELECT vg.group_name, vg.label, vg.description, vgm.code "
            "FROM vocabulary_group vg "
            "LEFT JOIN vocabulary_group_member vgm "
            "  ON vgm.namespace = vg.namespace AND vgm.group_name = vg.group_name "
            "WHERE vg.namespace = $1 "
            "ORDER BY vg.sort_order, vg.group_name",
            namespace,
        ),
        return_exceptions=True,
    )

    if isinstance(code_result, BaseException):
        logger.error(
            "vocabulary endpoint: DB query error", namespace=namespace, error=str(code_result)
        )
        raise HTTPException(status_code=503, detail="Vocabulary service temporarily unavailable")

    code_rows = code_result
    if not code_rows:
        raise HTTPException(status_code=404, detail=f"Unknown namespace: {namespace}")

    groups_available = not isinstance(group_result, BaseException)
    if not groups_available:
        logger.warning(
            "vocabulary endpoint: group DB query error",
            namespace=namespace,
            error=str(group_result),
        )
        group_rows = []
    else:
        group_rows = group_result

    codes = [
        {
            "code": row["code"],
            "label": row["label"],
            "description": row["description"],
            "sort_order": row["sort_order"],
            "is_deprecated": row["is_deprecated"],
        }
        for row in code_rows
    ]

    groups: dict[str, dict[str, Any]] = {}
    for row in group_rows:
        group = groups.setdefault(
            row["group_name"],
            {"label": row["label"], "description": row["description"], "codes": []},
        )
        if row["code"] is not None:
            group["codes"].append(row["code"])

    return {
        "namespace": namespace,
        "codes": codes,
        "groups": groups,
        "groups_available": groups_available,
    }
