"""Research page: what has been tested, what it concluded, and how many looks each vintage spent.

`research_run` is the ledger (S6 is its only writer; append-only, every attempt is a row). The
page reads it three ways:

- `vintages`: attempts per (vintage, kind, mode) by status, and the looks charged against the
  vintage (every attempt but the ledger's `UNCHARGED_STATUSES`, the rule its budget applies; an
  attempt still `started` is charged, and one whose runner died stays `started`);
- `runs`: one row per attempt, newest first, with its stored headline: the decision statistic, t,
  p, gross annualized Sharpe, mean session P&L, sessions and span, and why it was refused or
  failed. Rows
  written before migration 515 added the headline columns carry the same numbers in
  `evidence.decision`, so each headline reads the column and falls back to that object (the
  mapping the ledger's own `_headline` uses; the table is append-only, so the old rows can never
  be backfilled);
- `gates`: the pre-v3.5 `gate_evaluations` verdicts, kept as the record they are.

Nothing here judges a run: pass or fail at any alpha is the spec's call, stored by the runner.
"""

from typing import Any

from fastapi import APIRouter, Depends

from ...core.database_manager import DatabaseManager
from ...intelligence.research.ledger import UNCHARGED_STATUSES
from ..apr import refresh_seconds
from ..cache import cached
from ..dependencies import get_config_service, get_db_manager
from ..envelope import Envelope, all_ok, envelope, gather_sections, newest

router = APIRouter()


async def vintages(db: DatabaseManager) -> Envelope:
    rows = await db.execute_query(
        "SELECT vintage, kind, mode, count(*) AS attempts, "
        "count(*) FILTER (WHERE status <> ALL($1::text[])) AS charged, "
        "count(*) FILTER (WHERE status = 'completed') AS completed, "
        "count(*) FILTER (WHERE status = 'failed') AS failed, "
        "count(*) FILTER (WHERE status = 'guard_failed') AS guard_failed, "
        "count(*) FILTER (WHERE status = 'refused') AS refused, "
        "count(*) FILTER (WHERE status = 'started') AS unfinished, "
        "max(coalesce(finished_at, started_at)) AS newest "
        "FROM research_run GROUP BY vintage, kind, mode ORDER BY vintage, kind, mode",
        list(UNCHARGED_STATUSES),
    )
    return envelope("research_run", rows, newest(rows, "newest"))


def _headline(column: str, key: str) -> str:
    """A headline number: the 515 column, else the same field of the stored decision."""
    return f"coalesce(r.{column}, (r.evidence->'decision'->>'{key}')::float8) AS {column}"


_RUNS_SQL = f"""
SELECT r.run_group, r.started_at, r.finished_at, r.kind, r.mode, r.status,
       r.spec_path, c.name AS concept, r.evidence->'decision'->>'statistic' AS statistic,
       {_headline("decision_t", "t")}, {_headline("decision_p", "p")},
       {_headline("gross_sharpe", "annualized_sharpe")},
       {_headline("mean_session_pnl", "mean_session_pnl")},
       coalesce(r.n_sessions, (r.evidence->'decision'->>'n_sessions')::int) AS n_sessions,
       r.span_start, r.span_end, coalesce(r.evidence->>'refusal', r.evidence->>'error') AS note
FROM research_run r JOIN concept_registry c USING (concept_id)
ORDER BY r.started_at DESC, r.spec_path, c.name
"""


async def runs(db: DatabaseManager) -> Envelope:
    rows = await db.execute_query(_RUNS_SQL)
    as_of = max(
        (t for t in (newest(rows, "started_at"), newest(rows, "finished_at")) if t), default=None
    )
    return envelope(
        "research_run, concept_registry",
        rows,
        as_of,
        run_groups=len({r["run_group"] for r in rows}),
    )


async def gates(db: DatabaseManager) -> Envelope:
    rows = await db.execute_query(
        "SELECT gate_id, result, run_ts FROM gate_evaluations ORDER BY run_ts DESC"
    )
    return envelope("gate_evaluations", rows, newest(rows, "run_ts"))


async def _compute(db: DatabaseManager) -> dict[str, Any]:
    return await gather_sections({"vintages": vintages(db), "runs": runs(db), "gates": gates(db)})


@router.get("/summary")
async def summary(
    db: DatabaseManager = Depends(get_db_manager),
    config: Any = Depends(get_config_service),
) -> dict[str, Any]:
    """All three Research sections in one cached response; a failing section reports meta.error."""
    return await cached(
        "research", lambda: refresh_seconds(config), lambda: _compute(db), keep=all_ok
    )
