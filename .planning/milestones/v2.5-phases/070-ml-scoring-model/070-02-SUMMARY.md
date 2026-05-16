---
phase: 070-ml-scoring-model
plan: "02"
subsystem: persistence
tags: [ai-sep-01, writer-migration, signal-ai-enrichment, intelligence-ai-enrichment, swarm-ledger, llm-writer]
dependency_graph:
  requires:
    - signal_ai_enrichment table (070-01)
    - intelligence_ai_enrichment table (070-01)
  provides:
    - SwarmLedgerWriterAgent writes to signal_ai_enrichment (not signal_ledger)
    - LlmWriterService._flush_i8 writes to intelligence_ai_enrichment (not intelligence_features)
  affects:
    - services/swarm_ledger_writer_agent.py
    - services/llm_writer_service.py
tech_stack:
  added: []
  patterns:
    - asyncpg JSONB native dict binding (no json.dumps)
    - UPSERT ON CONFLICT for idempotent AI enrichment writes
    - Application-layer FK enforcement (TimescaleDB hypertable constraint limitation)
key_files:
  created: []
  modified:
    - services/swarm_ledger_writer_agent.py
    - services/llm_writer_service.py
decisions:
  - SwarmLedgerWriterAgent now UPSERTs to signal_ai_enrichment; signal_ledger quant table immutable after quant writer INSERT
  - LlmWriterService._flush_i8 now UPSERTs to intelligence_ai_enrichment; intelligence_features immutable after FeatureWriter INSERT
  - _RETRY_BACKOFF_S loop preserved in SwarmLedgerWriterAgent for application-layer FK race handling
  - json.dumps removed from _process_i8_message; asyncpg receives dict natively for JSONB
  - ForeignKeyViolationError and InvalidTextRepresentationError handled explicitly in SwarmLedgerWriterAgent
key_decisions:
  - signal_ledger.adjusted_confidence, swarm_multiplier, swarm_agent_count columns are legacy nullable; no new writes; downstream readers must LEFT JOIN signal_ai_enrichment
  - intelligence_features.i8 column no longer written by LlmWriterService; i8 now lives exclusively in intelligence_ai_enrichment
  - Auditor advisory: signal_auditor_agent.py and parity_auditor_agent.py contain zero references to swarm_multiplier/adjusted_confidence — no downstream risk from this migration (confirmed, see below)
metrics:
  duration_minutes: 2
  completed_date: "2026-05-13"
  tasks_completed: 2
  files_changed: 2
---

# Phase 70 Plan 02: AI Writer Migration to Enrichment Tables Summary

**One-liner:** Both AI writer services migrated off quant tables to AI-owned enrichment tables — SwarmLedgerWriterAgent UPSERTs to signal_ai_enrichment, LlmWriterService UPSERTs to intelligence_ai_enrichment (AI-SEP-01).

## What Was Built

Migrated two AI writer services from mutating quant tables to writing exclusively to the AI-owned enrichment tables created in Plan 01. Jim Simons principle: quant tables are now immutable after the quant writer's INSERT; AI annotations live in separate tables joined at read time.

### Task 1: SwarmLedgerWriterAgent (services/swarm_ledger_writer_agent.py)

**SQL constants added:**

```
_UPSERT_ENRICHMENT_SQL  — INSERT INTO signal_ai_enrichment ... ON CONFLICT (signal_id) DO UPDATE
_UPSERT_ML_SCORE_SQL    — INSERT INTO signal_ai_enrichment (ml_score, ml_model_id) ... ON CONFLICT (signal_id) DO UPDATE
```

**What changed:**
- Module-level docstring updated to reflect AI-SEP-01 intent
- `_UPSERT_ENRICHMENT_SQL` and `_UPSERT_ML_SCORE_SQL` constants added above the class
- `_handle_event()`: extracts `agent_outputs` list from aggregate swarm event, scans for `ml_scorer_v1` agent payload, passes `ml_score` / `ml_model_id` to `_apply_projection()`
- `_apply_projection()`: rewritten to use UPSERT constants inside existing `_RETRY_BACKOFF_S` loop; now catches `ForeignKeyViolationError` (retry) and `InvalidTextRepresentationError` (no retry); same Prometheus metric labels preserved
- The old inline `UPDATE signal_ledger ... WHERE signal_id = $1` is fully removed

**Preserved unchanged:**
- `_RETRY_BACKOFF_S = (0.1, 0.25, 0.5, 1.0, 2.0)` — retry schedule identical
- `SWARM_SIGNAL_LEDGER_UPDATE_TOTAL.labels(status="success"|"retry"|"miss")` — metric name kept for continuity
- `_setup()`, `_run()`, `_teardown()`, `_handle_event()` structure (only ml_score extraction added)

### Task 2: LlmWriterService (services/llm_writer_service.py)

**SQL constant renamed/replaced:**

```
_UPDATE_I8_SQL  (UPDATE intelligence_features SET i8 = $4::jsonb WHERE ts/symbol/tf)
  →
_UPSERT_I8_SQL  (INSERT INTO intelligence_ai_enrichment (ts, symbol, tf, i8, enriched_at)
                  VALUES ... ON CONFLICT (ts, symbol, tf) DO UPDATE SET i8, enriched_at)
```

**What changed:**
- `_UPDATE_I8_SQL` constant replaced with `_UPSERT_I8_SQL` at module level (lines 111-117)
- `_process_i8_message()`: `json.dumps(i8_dict)` removed; dict passed directly — asyncpg handles JSONB natively
- `_flush_i8()`: SQL reference updated from `_UPDATE_I8_SQL` to `_UPSERT_I8_SQL`; docstring updated to remove phantom-row caveat (AI-owned table has no FK dependency on intelligence_features)

**Preserved unchanged:**
- `_flush_batch()`, `_process_outcome_message()`, `_recompute_scores()`, `_score_recompute_loop()`, `_run()`, `_teardown()`, `_health_monitor_loop()`, `_stall_watchdog()` — all unmodified
- `_INSERT_LLM_CALL_SQL`, `_UPDATE_OUTCOME_SQL`, `_UPSERT_SCORE_SQL` — unchanged
- `BATCH_SIZE = 50`, `FLUSH_INTERVAL_SECS = 5.0` — unchanged
- `i8_writes_total`, `i8_update_miss_total` Prometheus metrics — retained (update_miss no longer fires but metric retained for continuity)
- `json` import retained — still used by `_load_config()` via `json.load()`

## Verification Results

| Check | Result |
|-------|--------|
| `grep "UPDATE signal_ledger" swarm_ledger_writer_agent.py` | 0 matches — PASS |
| `grep "INSERT INTO signal_ai_enrichment" swarm_ledger_writer_agent.py` | 2 matches — PASS |
| `grep "ON CONFLICT (signal_id) DO UPDATE" swarm_ledger_writer_agent.py` | 2 matches — PASS |
| `grep "_RETRY_BACKOFF_S" swarm_ledger_writer_agent.py` | 4 matches — PASS |
| `grep "SWARM_SIGNAL_LEDGER_UPDATE_TOTAL.labels" swarm_ledger_writer_agent.py` | 4 matches — PASS |
| `ruff check swarm_ledger_writer_agent.py` | All checks passed |
| AST parse swarm_ledger_writer_agent.py | PASS |
| `grep "_UPDATE_I8_SQL" llm_writer_service.py` | 0 matches — PASS |
| `grep "_UPSERT_I8_SQL" llm_writer_service.py` | 2 matches — PASS |
| `grep "INSERT INTO intelligence_ai_enrichment" llm_writer_service.py` | 1 match — PASS |
| `grep "UPDATE intelligence_features" llm_writer_service.py` | 0 matches — PASS |
| `grep "ON CONFLICT (ts, symbol, tf) DO UPDATE" llm_writer_service.py` | 1 match — PASS |
| `ruff check llm_writer_service.py` | All checks passed |
| AST parse llm_writer_service.py | PASS |
| No `event=` kwargs in structlog calls (either file) | PASS |
| No `json.dumps` in _flush_i8 path | PASS |

## Smoke Test Note

Service restart and live event smoke tests require the live intelligence pipeline to be running. The worktree environment does not run live services. Smoke tests must be performed after these changes are merged and services are restarted:

```bash
# Task 1 smoke test:
sudo systemctl restart indicagent-swarm-ledger-writer
tail -50 logs/swarm_ledger_writer_agent.log
psql -c "SELECT signal_id, swarm_multiplier, ml_score FROM signal_ai_enrichment ORDER BY enriched_at DESC LIMIT 5"

# Task 2 smoke test:
sudo systemctl restart indicagent-llm-writer
tail -50 logs/llm_writer_service.log
psql -c "SELECT ts, symbol, tf, i8 IS NOT NULL AS has_i8 FROM intelligence_ai_enrichment ORDER BY enriched_at DESC LIMIT 5"
```

## Downstream Auditor Advisory (Plan 04 Task 3 Input)

**IMPORTANT for Plan 04 Task 3:** After this migration, `signal_ledger.swarm_multiplier` and `signal_ledger.adjusted_confidence` will be NULL for all new signals. Any auditor reading these columns from `signal_ledger` directly (rather than via LEFT JOIN signal_ai_enrichment) will silently see NULLs.

**Advisory grep result (captured 2026-05-13):**

```
grep -nE "swarm_multiplier|adjusted_confidence" services/signal_auditor_agent.py services/parity_auditor_agent.py
(no output — zero matches)
```

**Classification:** Neither `signal_auditor_agent.py` nor `parity_auditor_agent.py` currently references `swarm_multiplier` or `adjusted_confidence`. Zero risk of silent NULL reads from this migration at the time of Plan 02 execution. Plan 04 Task 3 should re-run this grep after any auditor changes and classify any new references found.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing Critical Functionality] Explicit asyncpg exception handling in SwarmLedgerWriterAgent**

- **Found during:** Task 1 implementation
- **Issue:** The old `UPDATE signal_ledger` approach relied on asyncpg returning "UPDATE N" — the row count was parsed to detect the FK race. The new UPSERT to signal_ai_enrichment will throw `ForeignKeyViolationError` (application-layer FK) instead of returning "UPDATE 0". The original retry loop had no exception handling.
- **Fix:** Wrapped the UPSERT in try/except inside the retry loop: `ForeignKeyViolationError` → retry with backoff (same semantic as before); `InvalidTextRepresentationError` → no retry (malformed UUID). The `status="success"` path and `status="miss"` path are preserved.
- **Files modified:** services/swarm_ledger_writer_agent.py
- **Commit:** ee76847c

**2. [Rule 1 - Bug] json.dumps() in _process_i8_message bypassed asyncpg JSONB native path**

- **Found during:** Task 2 implementation
- **Issue:** `self._i8_buffer.append((ts_dt, symbol, tf, json.dumps(i8_dict)))` was passing a pre-serialized JSON string to asyncpg. The `_UPSERT_I8_SQL` constant uses `$4::jsonb` cast, and asyncpg expects a Python dict for JSONB columns — not a string. The old UPDATE path accidentally worked because PostgreSQL accepts both, but the explicit `::jsonb` cast on a Python string causes asyncpg to pass it as text and rely on PostgreSQL implicit cast.
- **Fix:** Removed `json.dumps()` wrapper; pass `i8_dict` directly. asyncpg handles JSONB serialisation natively (CLAUDE.md canonical rule: "Pass dicts for jsonb columns — never json.dumps()").
- **Files modified:** services/llm_writer_service.py
- **Commit:** 428b766b

## Commits

| Task | Commit | Description |
|------|--------|-------------|
| Task 1 | ee76847c | feat(070-02): migrate SwarmLedgerWriterAgent to UPSERT signal_ai_enrichment |
| Task 2 | 428b766b | feat(070-02): migrate LlmWriterService._flush_i8 to UPSERT intelligence_ai_enrichment |
