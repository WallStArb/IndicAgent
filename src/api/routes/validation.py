"""Validation Results API Routes — Phase 82 D-05.

Read-only endpoint exposing the latest per-plugin IC/p-value decisions written by
FeatureValidationAnalyzer to the validation_results hypertable.

Routes:
    GET /api/validation/results — latest validation decisions, optionally filtered by plugin_name
"""

from __future__ import annotations

import re
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from ...core.database_manager import DatabaseManager
from ...core.service_utils import format_iso_ts
from ..dependencies import get_db_manager
from ..utils import translate_db_errors

router = APIRouter()

# Regex used to validate plugin_name query param: printable ASCII, no SQL metacharacters.
_PLUGIN_NAME_RE = re.compile(r"^[A-Za-z0-9_\-]{1,128}$")


@router.get("/results")
@translate_db_errors
async def get_validation_results(
    plugin_name: str | None = Query(
        default=None,
        description="Filter by plugin name (alphanumeric + underscore/hyphen, max 128 chars)",
    ),
    limit: int = Query(
        default=50,
        ge=1,
        le=500,
        description="Maximum number of rows to return (1–500)",
    ),
    db_manager: DatabaseManager = Depends(get_db_manager),
) -> list[dict[str, Any]]:
    """Return latest validation_results rows ordered by computed_at DESC.

    Query params:
        plugin_name: Optional filter. Must match ^[A-Za-z0-9_\\-]{1,128}$.
        limit: Maximum rows returned (1–500, default 50).

    Returns:
        List of dicts with keys: plugin_name, timeframe, regime_type, ic, p_value,
        n, decision, bonferroni_corrected, computed_at (ISO-8601 string).

    Security:
        - plugin_name is validated against a strict regex before use.
        - SQL uses $1/$2 parameter binding — no string interpolation of user input.
        - Read-only endpoint: no POST/PUT/DELETE routes exist on this router.
    """
    # Validate plugin_name if provided — ASVS L1 input validation
    if plugin_name is not None and not _PLUGIN_NAME_RE.match(plugin_name):
        raise HTTPException(
            status_code=422,
            detail=(
                "plugin_name must match ^[A-Za-z0-9_\\-]{1,128}$ — "
                "alphanumeric characters, underscores, and hyphens only"
            ),
        )

    # Parameterized query — $1 is plugin_name (NULL or text), $2 is limit.
    # The ($1::text IS NULL OR plugin_name = $1) idiom handles optional filtering
    # without string interpolation.
    query = """
        SELECT
            plugin_name,
            timeframe,
            regime_type,
            ic,
            p_value,
            n,
            decision,
            bonferroni_corrected,
            computed_at
        FROM validation_results
        WHERE ($1::text IS NULL OR plugin_name = $1)
        ORDER BY computed_at DESC
        LIMIT $2
    """
    rows = await db_manager.fetch(query, plugin_name, limit)

    return [
        {
            "plugin_name": row["plugin_name"],
            "timeframe": row["timeframe"],
            "regime_type": row["regime_type"],
            "ic": row["ic"],
            "p_value": row["p_value"],
            "n": row["n"],
            "decision": row["decision"],
            "bonferroni_corrected": row["bonferroni_corrected"],
            "computed_at": format_iso_ts(row["computed_at"]),
        }
        for row in rows
    ]
