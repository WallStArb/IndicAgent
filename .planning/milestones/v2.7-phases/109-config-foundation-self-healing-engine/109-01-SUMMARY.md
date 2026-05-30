---
phase: 109-config-foundation-self-healing-engine
plan: "01"
subsystem: config
tags: [config, database, pydantic, transactional-outbox, ops-config]
dependency_graph:
  requires: []
  provides:
    - config_foundation_db_schema
    - ConfigService
    - config_schema_models
  affects:
    - 109-02-outbox-dispatcher
    - 109-03-api
tech_stack:
  added:
    - asyncpg (config pool)
    - TimescaleDB hypertable (config_history)
  patterns:
    - Transactional outbox (config_history + config_state + config_outbox in one tx)
    - SELECT FOR UPDATE inside transaction (optimistic locking)
    - OPS-only key domain (INFRA in .env, STRUCT in code)
    - Secret redaction (is_secret column honored in logs + return values)
key_files:
  created:
    - production/migrations/109_config_foundation.sql
    - src/config/config_schema.py
    - src/config/config_service.py
  modified: []
decisions:
  - "NO category column in config_schema (OPS-only invariant; category is implicit)"
  - "NO depends_on column (Codex LOW finding: semantics unclear; omit until enforced)"
  - "CONFIG_SET_TOTAL emit is try/except ImportError (defined in 109-02; 109-01 self-contained)"
  - "OPS_PREFIXES covers 9 prefixes: regime, swarm, alert, ai, feature, threshold, roll, cross_asset, macro"
  - "ALTER TABLE ... SET timescaledb.compress=true required before add_compression_policy on this TimescaleDB version"
metrics:
  duration_minutes: 6
  completed_date: "2026-05-29"
  tasks_completed: 3
  files_created: 3
  files_modified: 0
---

# Phase 109 Plan 01: Config Foundation Summary

**One-liner:** Transactional config foundation with 4-table schema (OPS only), Pydantic v2 validation models, and ConfigService enforcing key domain isolation, optimistic locking, and secret redaction.

## What Was Built

### Task 1: Config Database Schema (577aea1a)

Migration `production/migrations/109_config_foundation.sql` creates:

| Table | Purpose |
|-------|---------|
| `config_schema` | Defines valid OPS keys with type/range/allowed_values constraints |
| `config_state` | Current live value per key (config_key PK) |
| `config_history` | Immutable audit log (hypertable, 1yr retention, 7d compression) |
| `config_outbox` | Transactional outbox for Kafka propagation (OutboxDispatcher in 109-02) |

Row counts post-migration:
- `config_schema`: 15 rows (regime.*, swarm.*, roll.*, cross_asset.*, macro.*)
- `config_state`: 15 rows (matching schema seed, version=1)
- `config_history`: 0 (no changes yet)
- `config_outbox`: 0 (no changes yet)

Schema verification:
- `\d config_schema` has NO `category` column (OPS-only invariant)
- `\d config_schema` has NO `depends_on` column (Codex LOW finding addressed)
- `config_history` is a hypertable (TimescaleDB)
- Idempotency confirmed: migration re-runs with only "already exists, skipping" NOTICEs

### Task 2: Config Schema Models (cd1f93a2)

`src/config/config_schema.py` exports:
- `ConfigSchemaEntry` - mirrors DB table (no category, no depends_on)
- `ConfigChange` - result of a successful set()
- `ConfigState` - mirrors config_state table
- `ConfigValidationError(Exception)` - with `.message` attribute
- `ConfigVersionConflict(Exception)` - with `.expected_version` and `.actual_version`
- `ValidationResult` - dataclass with `valid: bool, reason: str | None`
- `validate_value(value, schema)` - type/range/allowed_values enforcement

Behavior verified:
- `validate_value(0.05, schema_with_min_0.1)` → `ValidationResult(valid=False, reason='Value 0.05 is below min_value=0.1')`
- `validate_value(0.5, schema_with_min_0.1_max_1.0)` → `ValidationResult(valid=True)`
- mypy clean (on config_schema.py)

### Task 3: ConfigService (b0a08f18)

`src/config/config_service.py` implements:

```python
OPS_PREFIXES = ("regime.", "swarm.", "alert.", "ai.", "feature.",
                "threshold.", "roll.", "cross_asset.", "macro.")
```

**Key domain validation test outputs:**
```
set("DATABASE_URL", ...) → ConfigValidationError:
  "Key 'DATABASE_URL' is not an OPS config key. INFRA keys (DATABASE_URL, KAFKA_BROKERS)
   must be set via .env. STRUCT keys (plugin tiers, DAG order) must be changed via code
   deployment. Valid OPS prefixes: regime., swarm., alert., ..."
```

**Version conflict test output:**
```
set("regime.test_key", "0.50")  → version=2
set("regime.test_key", "0.60", expected_version=1)  → ConfigVersionConflict(expected=1, actual=2)
```

**Secret redaction test output:**
```
change = set("regime.test_secret", "my_secret_value")
change.value == "**REDACTED**"   # no plaintext leak
log: config_value=**REDACTED**   # structlog field redacted
```

**Concurrency proof:**
- `SELECT ... FOR UPDATE` is on source line 186
- `async with conn.transaction()` is on source line 182
- FOR UPDATE is textually AFTER transaction context manager (confirmed by grep)

**Three-table write verification:**
```
After set("regime.test_key", "0.42"):
  config_history: 1 row (timestamp, key, version=1, value, changed_by)
  config_state: 1 row (key, value, version=1, updated_at)
  config_outbox: 1 row (status='pending', retry_count=0, next_attempt_at=NOW())
```

**All acceptance criteria met:**
- Key domain rejection for INFRA keys with ".env" in message
- OPS_PREFIXES contains exactly 9 entries (roll., cross_asset., macro. included)
- Transactional write to all 3 tables verified by COUNT queries
- FOR UPDATE inside transaction confirmed by source line numbers
- ConfigVersionConflict raised on stale expected_version
- Secret values redacted in logs and ConfigChange.value
- CONFIG_SET_TOTAL emit in try/except ImportError (self-contained for 109-01)
- Pool init via module-level `create_pool()` from `src.core.database_manager`

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] TimescaleDB compression requires explicit columnstore enable**
- **Found during:** Task 1 migration application
- **Issue:** `add_compression_policy()` failed with "columnstore not enabled on hypertable" - this TimescaleDB version requires `ALTER TABLE ... SET (timescaledb.compress = true)` before adding compression policy
- **Fix:** Added `ALTER TABLE config_history SET (timescaledb.compress = true, timescaledb.compress_segmentby = 'config_key')` before `add_compression_policy()` call in migration
- **Files modified:** `production/migrations/109_config_foundation.sql`
- **Impact:** Migration now idempotent; compression policy applied correctly

**2. [Rule 1 - Bug] mypy type narrowing for numeric variable in validate_value**
- **Found during:** Task 2 mypy verification
- **Issue:** `numeric` was typed as `int` then reassigned as `float` in different branches; mypy reported incompatible assignment; also `numeric < schema.min_value` comparison failed when mypy couldn't narrow `None` case
- **Fix:** Declared `numeric: float | None = None` at top of function; changed int branch to `float(int(value))` for uniform numeric type; added `numeric is not None` guard before range check
- **Files modified:** `src/config/config_schema.py`
- **Impact:** mypy clean on config_schema.py

**3. [Rule 3 - Blocking] .venv symlink missing in worktree**
- **Found during:** Task 2 commit (pre-commit hook blocked)
- **Issue:** Pre-commit hook looks for `.venv/bin/ruff` relative to `git rev-parse --show-toplevel` which resolves to the worktree directory, not the main repo; no `.venv` exists in worktree
- **Fix:** Created symlink `.claude/worktrees/agent-addcf32b1be47939a/.venv -> /home/bg/dev/indicagent/.venv`
- **Impact:** Pre-commit hooks pass for all subsequent commits

## Self-Check: PASSED

All files and commits verified:
- `production/migrations/109_config_foundation.sql` - FOUND
- `src/config/config_schema.py` - FOUND
- `src/config/config_service.py` - FOUND
- Commit 577aea1a (migration) - FOUND
- Commit cd1f93a2 (schema models) - FOUND
- Commit b0a08f18 (ConfigService) - FOUND
