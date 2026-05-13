---
phase: 82-ml-intelligence-quality-qualitative-foundation
plan: "06"
subsystem: ctx-infrastructure
tags: [ctx, qualitative-foundation, database, kafka, writer-agent, timescaledb]
dependency_graph:
  requires: []
  provides:
    - ctx_events TimescaleDB hypertable (migration 085)
    - ctx_snapshots table with valid_from/valid_to chaining (migration 085)
    - intelligence_features.ctx nullable JSONB column (migration 085)
    - topic_ctx_snapshot() stream key
    - CtxWriterAgent (L6 persistence writer)
    - feature_writer as-of join resolving active ctx snapshot per bar
  affects:
    - services/feature_writer_agent.py (INSERT SQL extended with ctx subquery)
    - services/service_auditor_agent.py (DAG registration)
tech_stack:
  added: []
  patterns:
    - BaseWriterAgent subclass with dual buffers (event + snapshot)
    - as-of join correlated subquery in INSERT VALUES
    - valid_from/valid_to chaining for snapshot lineage
key_files:
  created:
    - production/migrations/085_ctx_schema.sql
    - services/ctx_writer_agent.py
    - production/systemd/indicagent-ctx-writer.service
    - tests/unit/test_ctx_writer_agent.py
    - tests/unit/test_stream_keys_ctx.py
  modified:
    - src/core/stream_keys.py (added topic_ctx_snapshot)
    - services/feature_writer_agent.py (ctx column + as-of subquery in INSERT)
    - services/service_auditor_agent.py (_DAG_ORDER, _LAG_THRESHOLDS, _AGENT_ID_TO_UNIT)
decisions:
  - Migration 085 scoped to CTX tables only; validation_results stays in 086
  - CtxWriterAgent uses dual internal buffers rather than overriding _parse_payload buffer pattern
  - valid_to chaining done via separate UPDATE SQL per snapshot (not a CTE) for clarity
  - As-of subquery uses existing $1 (ts) and $2 (symbol) params from INSERT — no new parameters
metrics:
  duration: "~8 minutes"
  completed: "2026-05-13"
  tasks_completed: 3
  tasks_total: 3
  files_created: 5
  files_modified: 3
---

# Phase 82 Plan 06: CTX Schema Foundation Summary

CTX qualitative data infrastructure established: `ctx_events` hypertable + `ctx_snapshots` table + `intelligence_features.ctx` column (migration 085), `topic_ctx_snapshot()` stream key, `CtxWriterAgent` with event_type allowlist and payload size validation, feature_writer as-of join resolving active snapshots at bar insert time, and full DAG L6 registration.

## What Was Built

### Migration 085 (`production/migrations/085_ctx_schema.sql`)

Idempotent DDL establishing the complete CTX schema substrate:

- **`ctx_events`** TimescaleDB hypertable (partition on `event_ts`): append-only log of raw qualitative events. `symbol NULL` = global event (e.g. FOMC). `event_type` constrained to `{earnings, macro, news}` at application layer.
- **`ctx_events_symbol_type_idx`** on `(symbol, event_type, event_ts DESC)` for time-descending symbol/type lookups.
- **`ctx_snapshots`** regular table: current and historical context snapshots with `valid_from`/`valid_to` chaining. `valid_to IS NULL` = currently active. PRIMARY KEY `(symbol, event_type, valid_from)` prevents duplicate snapshot rows.
- **`ctx_snapshots_lookup_idx`** on `(symbol, valid_from, valid_to)`: critical for the as-of join hot path in feature_writer.
- **`intelligence_features.ctx JSONB`** (nullable): resolved at bar insert time; NULL when no active snapshot exists.

6 `IF NOT EXISTS` / `if_not_exists => TRUE` guards confirm full idempotency.

### Stream Key (`src/core/stream_keys.py`)

`topic_ctx_snapshot(env_name: str) -> str` returns `f"{env_prefix(env_name)}ctx.snapshot"` — dots-only topic naming per CLAUDE.md rule.

### CtxWriterAgent (`services/ctx_writer_agent.py`)

`BaseWriterAgent` subclass (`BATCH_SIZE=50`, `FLUSH_INTERVAL_SECS=10.0`). Consumer group: `ctx_writer_group`.

**Validation (threat model enforcement):**
- Required keys: `event_ts`, `event_type`, `source`, `payload` — drop with structlog warning on missing.
- `event_type` allowlist: `frozenset({"earnings", "macro", "news"})` — reject with warning and metric increment.
- Payload size cap: `len(json.dumps(payload)) > 64 KiB` — reject with warning.

**Dual-buffer architecture:** Messages produce rows for two separate buffers:
- `_event_buffer`: always-buffered `(event_ts, symbol, event_type, source, payload)` tuples for `ctx_events`.
- `_snapshot_buffer`: conditionally-buffered `(symbol, event_type, valid_from, ctx_data)` tuples for `ctx_snapshots` when message contains `valid_from` and `ctx` keys.

**Transaction flush:** `_flush()` acquires a single connection and runs `CLOSE_PRIOR_SNAPSHOT_SQL` (UPDATE `valid_to = new valid_from` WHERE `valid_to IS NULL`) followed by `UPSERT_CTX_SNAPSHOT_SQL` per snapshot row, plus `executemany` for all event rows — all within one `async with conn.transaction()`.

**JSONB compliance:** `inner_payload` and `ctx_data` are passed as Python dicts to asyncpg — never `json.dumps()`.

**As-of join SQL (in `_INSERT_FEATURE_SQL`):**
```sql
(
    SELECT jsonb_object_agg(event_type, ctx ORDER BY event_type)
    FROM ctx_snapshots
    WHERE (symbol = $2 OR symbol IS NULL)
      AND valid_from <= $1
      AND (valid_to IS NULL OR valid_to > $1)
)
```
Reuses existing `$1` (ts) and `$2` (symbol) parameters — no index churn, no new bind positions.

### DAG Registration (`services/service_auditor_agent.py`)

- `_DAG_ORDER["indicagent-ctx-writer"] = 6` (L6, parallel with other writers)
- `_LAG_THRESHOLDS["indicagent-ctx-writer"] = 500`
- `_AGENT_ID_TO_UNIT["ctx_writer_agent"] = "indicagent-ctx-writer"`

### Systemd Unit (`production/systemd/indicagent-ctx-writer.service`)

`Type=simple`, `Restart=on-failure`, `RestartSec=5`, `ExecStart=...python -m services.ctx_writer_agent`.

## Test Coverage

**`tests/unit/test_stream_keys_ctx.py`** (3 tests):
- `test_topic_ctx_snapshot_dev`: `"dev.ctx.snapshot"`
- `test_topic_ctx_snapshot_prod`: `"production.ctx.snapshot"`
- `test_topic_ctx_snapshot_uses_dots_not_colons`: no `:` in topic name

**`tests/unit/test_ctx_writer_agent.py`** (12 tests):
- `test_inserts_ctx_event_on_valid_message` — event buffer row verified
- `test_upserts_ctx_snapshot_and_closes_prior_valid_to` — 4 SQL execute calls (2×close+upsert)
- `test_rejects_disallowed_event_type` + `test_allowed_event_types_pass`
- `test_rejects_oversize_payload` + `test_borderline_payload_within_limit_passes`
- `test_rejects_missing_required_keys[event_ts/event_type/payload/source]` (parametrized)
- `test_passes_dict_to_asyncpg_jsonb_not_string` — both event payload and snapshot ctx verified
- `test_feature_writer_insert_includes_ctx_column` — static SQL assertion

All 15 tests pass; ruff clean.

## Deviations from Plan

None — plan executed exactly as written.

## Self-Check: PASSED

Checked file existence:
- `production/migrations/085_ctx_schema.sql` — FOUND
- `src/core/stream_keys.py` contains `topic_ctx_snapshot` — FOUND
- `services/ctx_writer_agent.py` defines `CtxWriterAgent` — FOUND
- `services/service_auditor_agent.py` contains `indicagent-ctx-writer` — FOUND (3 entries)
- `production/systemd/indicagent-ctx-writer.service` — FOUND
- `tests/unit/test_ctx_writer_agent.py` — FOUND
- `tests/unit/test_stream_keys_ctx.py` — FOUND

Checked commits exist:
- `4f6b6b5c` — feat(82-06): migration 085
- `ac72256c` — feat(82-06): stream key + writer agent + DAG + tests
- `faea3c6c` — feat(82-06): as-of join + unit tests
