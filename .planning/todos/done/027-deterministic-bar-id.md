# 027 - Remove bar_id from DB Schema; Use Natural Key

## Decision (made)

`(symbol, timeframe, ts)` is the natural key for a bar. It is deterministic by definition. Adding a surrogate `bar_id` to the DB schema is redundant — it aliases a natural key that already exists and is more auditable.

- **DB join/dedup**: use `(symbol, timeframe, ts)` composite natural key with a unique constraint on `intelligence_features`
- **Hot-path log correlation**: keep `bar_id` as UUID4 in `BarMessage` and `IntelligenceEvent` for log correlation across services — never write it to the DB
- **Do not add `bar_id` to `signal_events` or `trade_frames`** in the SLA migration

## What Needs Doing Before Phase 128 DDL

1. **`intelligence_features` unique constraint** — add `UNIQUE (symbol, timeframe, ts)` to `intelligence_features` (new migration or include in 137). This is the idempotent write gate for feature writers and replay.

2. **Drop `bar_id` columns from existing tables** — `intelligence_features.bar_id` and `signal_ledger.bar_id` are NULL for all rows (persistence layer never wrote them, per `src/persistence/` having zero `bar_id` references). Drop both columns in migration 137 or a companion migration.

3. **Phase 128 CONTEXT.md** — confirm `bar_id` does NOT appear in `signal_events`, `trade_frames`, or `trade_executions` column lists.

4. **`BarMessage.bar_id`** — keep as `uuid4()`, but clarify in the docstring it is a log-correlation trace handle only, not a DB key. No code changes needed.

## Current State

- `bar_id` flows hot path: `BarMessage` → `IntelligenceEvent` → signal dict (`signal_processor.py:447`) — correct, keep
- `bar_id` NOT persisted: `src/persistence/` has zero references — `intelligence_features.bar_id` and `signal_ledger.bar_id` are NULL for all rows
- Migration 063 added `bar_id` columns and indexes — both should be dropped

## Resolve Before

Phase 128 DDL (`production/migrations/137_3table_schema.sql`) is finalized.
