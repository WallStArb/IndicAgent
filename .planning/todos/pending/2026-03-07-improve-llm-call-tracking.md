# Improve LLM Call Tracking — Real Token Counts, Error Details, Fill Empty Fields

**Priority:** Medium (observability improvement, not blocking)
**Created:** 2026-03-07

## Context

`llm_calls` hypertable captures a solid baseline but has several gaps that limit cost analysis, debugging, and model optimization.

## What Already Exists

- `model`, `provider`, `called_at`, `latency_ms`, `succeeded` — populated
- `tokens_est` — word count proxy (`len(response.split())`)
- `prompt`, `response` — full text stored
- Outcome back-fill: `pnl_r`, `mae`, `mfe`, `win`, `outcome`
- `session`, `cis_score`, `entry_zone_low/high` — columns exist but always empty

## Gaps to Fix

### 1. Real token counts (High value)
`tokens_est` is a word-count proxy. Ollama's `/api/generate` response already includes:
- `prompt_eval_count` → tokens in
- `eval_count` → tokens out

**Action:** Read these fields in `ai_narrative_service.py` and pass them through to `llm_writer_service.py`. May need DB migration to add `tokens_in` / `tokens_out` columns (or repurpose `tokens_est` as `tokens_out` and add `tokens_in`).

### 2. Error message on failures
`succeeded=False` records have no detail — impossible to distinguish timeout vs OOM vs bad response format.

**Action:** Capture exception message or HTTP error text in a new `error_message` column (or reuse an existing nullable text field). Populate in the `except` block in `ai_narrative_service.py`.

### 3. Fill empty fields
`cis_score`, `entry_zone_low`, `entry_zone_high` are columns but never written. The values exist in the aggregated signal context passed to the narrative service.

**Action:** Wire these through the publish payload in `ai_narrative_service.py` → include in the `llm_calls:stream` message → `llm_writer_service.py` reads and inserts them.

### 4. Retry/fallback chain visibility
Only the winning provider is stored. Intermediate failures (e.g., primary Ollama timeout → fallback) are silently discarded.

**Action:** Log each attempt as a separate row with `succeeded=False` + error detail, or add an `attempt_number` + `is_final_attempt` flag. Consider a separate `llm_attempts` table to avoid bloating `llm_calls`.

### 5. Request parameters
`temperature` and `max_tokens` are not logged — relevant when tuning or comparing model configs.

**Action:** Add these to the `llm_calls:stream` payload and store in new columns (or a `request_params` JSONB column).

## Scope

- `services/ai_narrative_service.py` — publish side (read Ollama response fields, pass through context)
- `services/llm_writer_service.py` — schema/insert side
- `production/migrations/` — new migration for any new columns
- `src/intelligence/schemas.py` — possibly extend LLM call event schema

## Implementation Order

1. Real token counts (highest signal-to-effort ratio — Ollama already returns them)
2. Error message on failures (cheap, high debug value)
3. Fill `cis_score` / zone fields (already available in context)
4. Request params (low effort, useful for tuning)
5. Retry chain (most complex — evaluate table design before implementing)
