"""Concepts page: every concept in the registry, its lifecycle state and the evidence behind it.

`concepts` is one row per `concept_registry` entry with its most recent evaluation (the
`concept_evaluation` row for the newest window `feature_lifecycle` evaluated, the window the
lifecycle judges status on: evidence kind, the stored pass/fail, the IC regime guard, statistic and
cells) and its most recent lifecycle transition (`concept_transition_log`). The page reads states
the registry's writers stored; it never judges a concept itself (UCR: only
`ConceptRegistryService` flips a status).

`ic` is the fresh IC store `ic_measure` writes (`feature_ic_scores_v2`), one row per (timeframe,
regime scope, horizon) at that group's newest training window (the current measurement, not the
pile-up of every window ever written): rows, features, and features with a cell passing FDR.
It is empty until the 186-26 feature rebuild lands, and the page says so.
"""

from typing import Any

from fastapi import APIRouter, Depends

from ...core.database_manager import DatabaseManager
from ..apr import refresh_seconds
from ..cache import cached
from ..dependencies import get_config_service, get_db_manager
from ..envelope import Envelope, all_ok, envelope, gather_sections, newest

router = APIRouter()

_CONCEPTS_SQL = """
SELECT c.domain, c.name, c.group_name, c.status, c.enabled, c.is_control,
       c.control_expectation,
       e.evidence_kind, e.passed, e.guard_status, e.statistic, e.n_cells, e.evaluated_at,
       t.from_status, t.to_status, t.trigger_reason, t.triggered_at
FROM concept_registry c
LEFT JOIN LATERAL (
    SELECT evidence_kind, guard_status, passed, statistic, n_cells, evaluated_at
    FROM concept_evaluation WHERE concept_id = c.concept_id
    ORDER BY window_end DESC, evaluated_at DESC, evidence_key LIMIT 1
) e ON true
LEFT JOIN LATERAL (
    SELECT from_status, to_status, trigger_reason, triggered_at
    FROM concept_transition_log WHERE concept_id = c.concept_id
    ORDER BY triggered_at DESC LIMIT 1
) t ON true
ORDER BY c.domain, c.group_name NULLS LAST, c.name
"""


async def concepts(db: DatabaseManager) -> Envelope:
    rows = await db.execute_query(_CONCEPTS_SQL)
    as_of = max(
        (t for t in (newest(rows, "evaluated_at"), newest(rows, "triggered_at")) if t),
        default=None,
    )
    return envelope("concept_registry, concept_evaluation, concept_transition_log", rows, as_of)


async def ic(db: DatabaseManager) -> Envelope:
    rows = await db.execute_query(
        "WITH latest AS (SELECT tf, regime_scope, lookahead_bars, "
        "max(training_window_end) AS training_window_end FROM feature_ic_scores_v2 "
        "GROUP BY tf, regime_scope, lookahead_bars) "
        "SELECT tf, regime_scope, lookahead_bars, count(*) AS rows, "
        "count(DISTINCT feature_name) AS features, "
        "count(DISTINCT feature_name) FILTER (WHERE passes_fdr) AS features_passing_fdr, "
        "training_window_end AS window_end, max(computed_at) AS computed_at "
        "FROM feature_ic_scores_v2 "
        "JOIN latest USING (tf, regime_scope, lookahead_bars, training_window_end) "
        "GROUP BY tf, regime_scope, lookahead_bars, training_window_end "
        "ORDER BY tf, regime_scope, lookahead_bars"
    )
    return envelope(
        "feature_ic_scores_v2",
        rows,
        newest(rows, "computed_at"),
        detail="ic_measure writes it once the 186-26 feature rebuild lands",
    )


async def _compute(db: DatabaseManager) -> dict[str, Any]:
    return await gather_sections({"concepts": concepts(db), "ic": ic(db)})


@router.get("/summary")
async def summary(
    db: DatabaseManager = Depends(get_db_manager),
    config: Any = Depends(get_config_service),
) -> dict[str, Any]:
    """Both Concepts sections in one cached response; a failing section reports meta.error."""
    return await cached(
        "concepts", lambda: refresh_seconds(config), lambda: _compute(db), keep=all_ok
    )
