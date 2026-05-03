# 078-07-SUMMARY: NarrativeComputeAgent → API Endpoint

**Status:** COMPLETE
**Date:** 2026-05-03

## What shipped
- `GET /api/signals/{signal_id}/narrative` — on-demand LLM narrative endpoint
- `signal_narratives` hypertable (migration 080) — every narrative persisted, idempotent per signal_id
- DB-first lookup: repeat requests return cached row (zero LLM cost)
- Typed AIContext construction from joined signal_ledger + intelligence_features rows
- 9 route tests passing (200/200-cached/404/422/502/500/chain-cache/typed-context/null-bar)

## Files created
- `production/migrations/080_signal_narratives.sql` — hypertable with FK to signal_ledger, 7-day compression
- `src/api/routes/narrative.py` — FastAPI route with DB-first lookup, persistence, typed AIContext
- `tests/unit/api/test_narrative_route.py` — 9 tests

## Files deleted
- `services/ai_narrative_agent.py` — Kafka consumer wrapper (git rm)
- `production/systemd/indicagent-ai-narrative.service` — systemd unit (git rm)
- `tests/unit/service_tests/test_ai_narrative_agent.py` — old agent tests (git rm)

## Files modified
- `src/api/main.py` — registered narrative router
- `services/service_auditor_agent.py` — removed 3 DAG entries (ai-narrative from _DAG_ORDER, _LAG_THRESHOLDS, _AGENT_ID_TO_UNIT)
- `production/scripts/pipeline_reset.py` — removed ai-narrative from stop/start lists
- `tests/unit/service_tests/test_service_auditor_agent.py` — removed ai-narrative from test fixture
- `CLAUDE.md` — status line +78, L7 DAG layer updated

## Untouched (per D-31)
- `src/intelligence/ai/narrative/narrative_agent.py` — NarrativeComputeAgent class unchanged

## intelligence_features JSONB columns
bar, i1, i3, i4, i5, smc, i6 (no i2 column). Route queries all available tiers.

## Operator deploy steps
After merging to main and deploying:
```
sudo systemctl stop indicagent-ai-narrative
sudo systemctl disable indicagent-ai-narrative
sudo rm /etc/systemd/system/indicagent-ai-narrative.service
sudo systemctl daemon-reload
```
Then apply migration 080:
```
docker exec -i timescaledb psql -U postgres -d indicagent < production/migrations/080_signal_narratives.sql
```

## Renaissance refinement
Original plan returned ephemeral narratives. Refined to persist every generation:
- **Idempotent:** same signal_id always returns same narrative, zero repeat LLM cost
- **Auditable:** full provenance (model, latency, prompt_hash) in signal_narratives
- **Backtestable:** JOIN signal_narratives to signal_ledger outcomes
- **Training data:** every narrative is a labeled sample for future quality models
