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
    intent (T-161-07).
    """
    try:
        code_rows = await db_manager.fetch(
            "SELECT code, label, description, sort_order, is_deprecated "
            "FROM controlled_vocabulary WHERE namespace = $1 ORDER BY sort_order, code",
            namespace,
        )
    except Exception as error:
        logger.warning("vocabulary endpoint: DB query error", namespace=namespace, error=str(error))
        raise HTTPException(status_code=404, detail=f"Unknown namespace: {namespace}") from error

    if not code_rows:
        raise HTTPException(status_code=404, detail=f"Unknown namespace: {namespace}")

    try:
        group_rows = await db_manager.fetch(
            "SELECT group_name, code FROM vocabulary_group_member WHERE namespace = $1",
            namespace,
        )
    except Exception as error:
        logger.warning(
            "vocabulary endpoint: group DB query error", namespace=namespace, error=str(error)
        )
        group_rows = []

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

    groups: dict[str, list[str]] = {}
    for row in group_rows:
        groups.setdefault(row["group_name"], []).append(row["code"])

    return {
        "namespace": namespace,
        "codes": codes,
        "groups": groups,
    }
