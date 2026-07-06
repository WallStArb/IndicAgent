# Scripts Organization Audit

**Status:** completed (2026-06-28)
**Created:** 2026-06-28
**Type:** Architecture audit + reorganization plan

---

## Current State

**Two directories with unclear split:**
- `scripts/` — 1 Python file (`corpus_final_verification.py`)
- `production/scripts/` — 21 Python files + 10 shell scripts + SQL files

**Total:** 21 Python scripts, 10 shell scripts, mixed operational/infrastructure/domain code

---

## Problems

### 1. Unclear Directory Split

The `scripts/` vs `production/scripts/` boundary has no clear principle:

**All corpus-related code lives in `production/scripts/`:**
- `corpus_pipeline_run.sh` — main corpus orchestrator
- `corpus_progress.py` — corpus pipeline status
- `backfill_feature_factory.py` — (in services/, but run by corpus script)

**Except one outlier:**
- `scripts/corpus_final_verification.py` — why separate?

**Infrastructure/setup code mixed with operational code:**
- One-time setup: `db_setup.sh`, `init_kafka_topics.sh`, `add_instruments_trigger.sql`
- Operational tools: `redpanda_watchdog.sh`, `pipeline_status.py`, `roll_batch.py`

These should live in different directories.

---

### 2. Naming Inconsistencies

**Snake_case is correct** — all Python and shell scripts follow this. **But purpose is unclear from names:**

| Scripts | Question |
|---|---|
| `pipeline_audit.py` vs `pipeline_status.py` | What's the difference? Both check pipeline state? |
| `signal_corpus_snapshot.py` vs `signal_ledger_snapshot.py` | Why both? Same domain, slightly different outputs? |
| `feature_replay.py` vs `lifecycle_replay.py` | What is "replay" — backfill? Debugging? Analysis? |
| `replay_all.sh`, `replay_post.py`, `replay_prep.py` | Three replay phases — why? What's the workflow? |
| `validate_alpha.py` vs `validate_roll_detection.py` | Both validation, different targets — should be `validate_<domain>.py` |

The names don't answer: **what does this do, for whom, and when is it run?**

---

### 3. Purpose Overlap & Duplication

**Multiple "replay" scripts** with unclear boundaries:
- `feature_replay.py`
- `lifecycle_replay.py`
- `replay_all.sh`
- `replay_post.py`
- `replay_prep.py`

Five scripts named "replay" — no clear sense of which does what, or whether they're redundant.

**Multiple "snapshot" scripts:**
- `signal_corpus_snapshot.py`
- `signal_ledger_snapshot.py`

Both export signal data to files. Why two?

**Multiple "pipeline" scripts:**
- `pipeline_audit.py`
- `pipeline_status.py`
- `run_historical_pipeline.py`
- `corpus_pipeline_run.sh`

Four ways to inspect or run pipelines. Some overlap in function.

---

### 4. Dead or One-Time Code Mixed with Operational Tools

**One-time setup in production/scripts/:**
- `db_setup.sh` — database schema initialization (run once, never again)
- `init_kafka_topics.sh` — Kafka topic creation (run once per schema change)
- `add_instruments_trigger.sql` — one-time trigger addition
- `db_verify.sh` — ad-hoc verification (belongs in ops/, not production code)

**Operational tools (run regularly):**
- `roll_batch.py` — nightly futures roll
- `redpanda_watchdog.sh` — operational monitoring
- `pipeline_status.py` — pipeline health checks

These categories should not be mixed. Setup scripts belong in `infrastructure/setup/`. Operational tools belong in `ops/`.

---

### 5. No Ring Structure

The naming system document defines Ring 0 (portable infrastructure) vs Ring 1 (domain) vs Ring 2 (services) vs Ring 3 (external interfaces). Scripts have no such organization:

**Infrastructure scripts** (could be Ring 0 portable):
- `db_setup.sh` — database schema
- `init_kafka_topics.sh` — Kafka infrastructure
- `enforce_topic_retention.py` — Kafka retention policy

**Domain scripts** (Ring 1):
- `roll_batch.py` — futures rolling (domain-specific logic)
- `context_features_writer.py` — context features (domain logic)

**Mixed together** — no clear boundary, no portable infrastructure layer.

---

## Renaissance-Grade Organization

### Directory Structure

```
scripts/
├── ops/                    # operational tools (run regularly by operators)
│   ├── corpus/
│   │   ├── corpus_pipeline_run.sh          # main corpus pipeline orchestrator
│   │   ├── corpus_progress.py              # corpus pipeline status/progress
│   │   └── corpus_final_verification.py     # corpus verification gates (move from scripts/)
│   ├── roll/
│   │   ├── roll_batch.py                   # nightly futures roll
│   │   └── validate_roll_detection.py
│   ├── pipeline/
│   │   ├── pipeline_status.py             # pipeline health checks (operational monitoring)
│   │   └── pipeline_audit.py              # pipeline data quality audits (periodic checks)
│   └── signal/
│       ├── signal_corpus_snapshot.py       # signal data exports (consistency: signal_<purpose>)
│       └── signal_ledger_snapshot.py       # signal ledger exports (consistency: signal_<purpose>)
├── infrastructure/         # one-time setup and infrastructure
│   ├── setup/
│   │   ├── db_setup.sh                    # database schema initialization
│   │   ├── init_kafka_topics.sh           # Kafka topic creation
│   │   └── add_instruments_trigger.sql    # one-time trigger additions
│   ├── backfill/
│   │   ├── backfill_missing_etfs.sh       # fill gaps in ETF coverage
│   │   ├── backfill_missing_timeframes.sh # fill gaps in timeframe coverage
│   │   └── run_historical_pipeline.py     # historical backfill orchestration
│   └── kafka/
│       ├── enforce_topic_retention.py      # Kafka retention enforcement
│       ├── ensure_topics.sh               # Kafka topic existence checks
│       └── redpanda_watchdog.sh           # Redpanda health monitoring
└── debug/                  # debugging and analysis tools (run when investigating issues)
    ├── replay/
    │   ├── replay_all.sh                  # full pipeline replay (debugging)
    │   ├── replay_prep.py                 # replay preparation
    │   ├── replay_post.py                 # replay post-processing
    │   ├── feature_replay.py              # feature layer replay
    │   └── lifecycle_replay.py            # signal lifecycle replay
    ├── validate/
    │   ├── validate_alpha.py              # alpha signal validation
    │   └── validate_roll_detection.py     # (duplicate with ops/roll/ — consolidate)
    └── snapshot/
        ├── signal_corpus_snapshot.py      # (move from root)
        └── signal_ledger_snapshot.py      # (move from root)
```

**Services (`services/`) are NOT scripts** — they are systemd-managed daemons. The current scripts directory is for oneshot or manually invoked tools.

---

## Naming Conventions

### Python Scripts

**Pattern:** `<domain>_<action>_<object>.py`

| Current | Proposed | Why |
|---|---|---|
| `pipeline_status.py` | `ops_pipeline_status.py` | Domain + purpose + object; moves to ops/ |
| `pipeline_audit.py` | `ops_pipeline_audit.py` | Domain + purpose + object; moves to ops/ |
| `roll_batch.py` | `ops_roll_batch.py` | Already follows pattern; moves to ops/roll/ |
| `corpus_progress.py` | `ops_corpus_progress.py` | Domain + purpose; moves to ops/corpus/ |
| `signal_corpus_snapshot.py` | `debug_signal_corpus_snapshot.py` | Domain + purpose + object; moves to debug/snapshot/ |
| `validate_alpha.py` | `debug_validate_alpha.py` | Purpose + object; moves to debug/validate/ |

### Shell Scripts

**Pattern:** `<domain>_<action>_<object>.sh`

| Current | Proposed | Why |
|---|---|---|
| `corpus_pipeline_run.sh` | `ops_corpus_pipeline_run.sh` | Already clear; moves to ops/corpus/ |
| `backfill_missing_etfs.sh` | `infrastructure_backfill_missing_etfs.sh` | Domain + action + object; moves to infrastructure/backfill/ |
| `truncate_derived_tables.sh` | `infrastructure_truncate_derived_tables.sh` | Domain + action + object; moves to infrastructure/ |

---

## Migration Plan

### Phase 1 — Restructure directories (non-breaking)

1. Create new directory structure under `scripts/`:
   ```bash
   mkdir -p scripts/ops/{corpus,roll,pipeline,signal}
   mkdir -p scripts/infrastructure/{setup,backfill,kafka}
   mkdir -p scripts/debug/{replay,validate,snapshot}
   ```

2. Move scripts to new locations:
   ```bash
   # ops/
   mv production/scripts/corpus_pipeline_run.sh scripts/ops/corpus/ops_corpus_pipeline_run.sh
   mv production/scripts/corpus_progress.py scripts/ops/corpus/ops_corpus_progress.py
   mv scripts/corpus_final_verification.py scripts/ops/corpus/ops_corpus_final_verification.py
   mv production/scripts/pipeline_status.py scripts/ops/pipeline/ops_pipeline_status.py
   mv production/scripts/pipeline_audit.py scripts/ops/pipeline/ops_pipeline_audit.py
   mv production/scripts/roll_batch.py scripts/ops/roll/ops_roll_batch.py
   mv production/scripts/validate_roll_detection.py scripts/ops/roll/ops_validate_roll_detection.py

   # infrastructure/
   mv production/scripts/db_setup.sh scripts/infrastructure/setup/infrastructure_db_setup.sh
   mv production/scripts/init_kafka_topics.sh scripts/infrastructure/setup/infrastructure_init_kafka_topics.sh
   mv production/scripts/backfill_missing_etfs.sh scripts/infrastructure/backfill/infrastructure_backfill_missing_etfs.sh
   mv production/scripts/backfill_missing_timeframes.sh scripts/infrastructure/backfill/infrastructure_backfill_missing_timeframes.sh
   mv production/scripts/run_historical_pipeline.py scripts/infrastructure/backfill/infrastructure_run_historical_pipeline.py
   mv production/scripts/enforce_topic_retention.py scripts/infrastructure/kafka/infrastructure_enforce_topic_retention.py
   mv production/scripts/ensure_topics.sh scripts/infrastructure/kafka/infrastructure_ensure_topics.sh
   mv production/scripts/redpanda_watchdog.sh scripts/infrastructure/kafka/infrastructure_redpanda_watchdog.sh

   # debug/
   mv production/scripts/replay_all.sh scripts/debug/replay/debug_replay_all.sh
   mv production/scripts/replay_prep.py scripts/debug/replay/debug_replay_prep.py
   mv production/scripts/replay_post.py scripts/debug/replay/debug_replay_post.py
   mv production/scripts/feature_replay.py scripts/debug/replay/debug_feature_replay.py
   mv production/scripts/lifecycle_replay.py scripts/debug/replay/debug_lifecycle_replay.py
   mv production/scripts/validate_alpha.py scripts/debug/validate/debug_validate_alpha.py
   mv production/scripts/signal_corpus_snapshot.py scripts/debug/snapshot/debug_signal_corpus_snapshot.py
   mv production/scripts/signal_ledger_snapshot.py scripts/debug/snapshot/debug_signal_ledger_snapshot.py
   ```

3. Update shebangs and imports to reflect new structure
4. Update any documentation or runbooks that reference old paths

### Phase 2 — Cleanup and consolidation

**Remove duplicates:**
- Consolidate `validate_roll_detection.py` (keep one copy in ops/roll/)
- Audit `replay_*` scripts for functional overlap; merge if redundant

**Consolidate snapshot scripts:**
- If `signal_corpus_snapshot.py` and `signal_ledger_snapshot.py` serve different purposes, clarify in names:
  - `debug_signal_corpus_snapshot.py` — raw signal data export
  - `debug_signal_ledger_snapshot.py` — signal ledger (joined view) export

**Clarify pipeline vs corpus:**
- `run_historical_pipeline.py` — v2.x I1-I7 backfill
- `corpus_pipeline_run.sh` — v3.0 corpus pipeline
- These are different systems; ensure naming reflects `v2_` vs `v3_` distinction if they share a directory

### Phase 3 — Documentation

1. Update `docs/operations/operations-infrastructure.md` with new script locations
2. Add `docs/operations/scripts-reference.md` as a catalog of all scripts with purpose and usage
3. Update any runbooks or SOPs that reference old script paths

---

## Principles

### Directory Split Criteria

| Directory | What goes here | Run frequency | Example |
|---|---|---|
| `ops/` | Operational tools run regularly by operators | Daily/weekly/hourly | `ops_roll_batch.py`, `ops_corpus_progress.py` |
| `infrastructure/` | One-time setup and infrastructure configuration | Once or rare | `infrastructure_db_setup.sh`, `infrastructure_init_kafka_topics.sh` |
| `debug/` | Debugging and analysis tools for investigation | When investigating | `debug_validate_alpha.py`, `debug_replay_all.sh` |

**NOT:** portable infrastructure (that belongs in `src/core/`)
**NOT:** services (those live in `services/` with systemd units)

### Naming Pattern

**Python:** `<domain>_<purpose>_<object>.py`
- Domain: ops, infrastructure, debug
- Purpose: status, audit, validate, replay, snapshot
- Object: pipeline, corpus, roll, signal, alpha

**Shell:** `<domain>_<purpose>_<object>.sh`
- Same pattern as Python

---

## Benefits

1. **Clear purpose** — directory name tells you when and why to run something
2. **No duplication** — one canonical location per category of tool
3. **Discoverable** — looking for ops tools? Check `ops/`. Debugging? Check `debug/`
4. **Portable infrastructure** — infrastructure scripts are separated and reusable
5. **Renaissance-grade** — organization reflects system structure, not historical accident
