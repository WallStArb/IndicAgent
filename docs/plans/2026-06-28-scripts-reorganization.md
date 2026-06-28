# Scripts Reorganization Design

**Status:** Approved
**Created:** 2026-06-28
**Type:** Infrastructure reorganization
**Priority:** Medium (Renaissance continuous refinement)

---

## Purpose

Reorganize `scripts/` and `production/scripts/` into a clean, Renaissance-grade structure with clear purpose boundaries and minimal descriptions. Eliminate confusion, duplication, and operational ambiguity.

---

## Current State Problems

1. **Unclear directory split** — `scripts/` (1 file) vs `production/scripts/` (21 files) with no organizing principle
2. **Naming inconsistencies** — `pipeline_audit.py` vs `pipeline_status.py` (both check pipeline state, unclear difference)
3. **Purpose overlap** — 5 "replay" scripts, 2 "snapshot" scripts, 4 "pipeline" scripts
4. **Dead code mixed with ops** — `db_setup.sh`, `init_kafka_topics.sh` belong in infrastructure/, not production/
5. **Missing descriptions** — many scripts lack clear docstrings explaining purpose/when to run

---

## Target Structure

```
scripts/
├── ops/                    # Operational tools (run regularly by operators)
│   ├── corpus/
│   ├── roll/
│   ├── pipeline/
│   └── signal/
├── infrastructure/         # One-time setup and infrastructure configuration
│   ├── setup/
│   ├── backfill/
│   └── kafka/
└── debug/                  # Debugging and analysis tools (run when investigating)
    ├── replay/
    ├── validate/
    └── snapshot/
```

**Directory split criteria:**

| Directory | What goes here | Run frequency |
|---|---|---|
| `ops/` | Operational tools run regularly | Daily/weekly/hourly |
| `infrastructure/` | One-time setup and infrastructure | Once or rare |
| `debug/` | Debugging and analysis tools | When investigating |

---

## Naming Convention

**Pattern:** `<domain>_<purpose>_<object>.py|.sh`

- Domain: `ops`, `infrastructure`, `debug`
- Purpose: `status`, `audit`, `validate`, `replay`, `snapshot`, `progress`
- Object: `pipeline`, `corpus`, `roll`, `signal`, `alpha`

**Examples:**
- `ops_corpus_progress.py` — corpus pipeline status checking
- `infrastructure_db_setup.sh` — database schema initialization
- `debug_validate_alpha.py` — alpha signal validation

---

## Execution Phases

### Phase 1: Restructure

Create new directory structure and move all scripts to new locations with updated names.

**New locations per audit mapping:**

```bash
# ops/
production/scripts/corpus_pipeline_run.sh → scripts/ops/corpus/ops_corpus_pipeline_run.sh
production/scripts/corpus_progress.py → scripts/ops/corpus/ops_corpus_progress.py
scripts/corpus_final_verification.py → scripts/ops/corpus/ops_corpus_final_verification.py
production/scripts/pipeline_status.py → scripts/ops/pipeline/ops_pipeline_status.py
production/scripts/pipeline_audit.py → scripts/ops/pipeline/ops_pipeline_audit.py
production/scripts/roll_batch.py → scripts/ops/roll/ops_roll_batch.py
production/scripts/validate_roll_detection.py → scripts/ops/roll/ops_validate_roll_detection.py

# infrastructure/
production/scripts/db_setup.sh → scripts/infrastructure/setup/infrastructure_db_setup.sh
production/scripts/init_kafka_topics.sh → scripts/infrastructure/setup/infrastructure_init_kafka_topics.sh
production/scripts/backfill_missing_etfs.sh → scripts/infrastructure/backfill/infrastructure_backfill_missing_etfs.sh
production/scripts/backfill_missing_timeframes.sh → scripts/infrastructure/backfill/infrastructure_backfill_missing_timeframes.sh
production/scripts/run_historical_pipeline.py → scripts/infrastructure/backfill/infrastructure_run_historical_pipeline.py
production/scripts/enforce_topic_retention.py → scripts/infrastructure/kafka/infrastructure_enforce_topic_retention.py
production/scripts/ensure_topics.sh → scripts/infrastructure/kafka/infrastructure_ensure_topics.sh
production/scripts/redpanda_watchdog.sh → scripts/infrastructure/kafka/infrastructure_redpanda_watchdog.sh

# debug/
production/scripts/replay_all.sh → scripts/debug/replay/debug_replay_all.sh
production/scripts/replay_prep.py → scripts/debug/replay/debug_replay_prep.py
production/scripts/replay_post.py → scripts/debug/replay/debug_replay_post.py
production/scripts/feature_replay.py → scripts/debug/replay/debug_feature_replay.py
production/scripts/lifecycle_replay.py → scripts/debug/replay/debug_lifecycle_replay.py
production/scripts/validate_alpha.py → scripts/debug/validate/debug_validate_alpha.py
production/scripts/signal_corpus_snapshot.py → scripts/debug/snapshot/debug_signal_corpus_snapshot.py
production/scripts/signal_ledger_snapshot.py → scripts/debug/snapshot/debug_signal_ledger_snapshot.py
```

**Updates required:**
- Shebangs in shell scripts
- Imports in Python files
- Documentation references

### Phase 2: Consolidation Audit

Before merging scripts, audit usage to avoid breaking workflows:

1. **Check script references across codebase** — grep for old paths and script names
2. **Check documentation** — ops-infrastructure.md, runbooks, SOPs
3. **Identify actual duplicates vs apparent duplicates**

**Consolidate only what's clearly redundant:**
- `validate_roll_detection.py` — if duplicate exists, consolidate
- Replay scripts — determine if they're a workflow chain or truly redundant
- Snapshot scripts — already serve different purposes (raw vs joined), just clarify naming

### Phase 3: Add Descriptions

Add minimal 2-4 line descriptions to scripts lacking them. Renaissance-grade means essential clarity, not bureaucracy.

**Description format:**

```python
"""
ops_corpus_pipeline_run.sh — v3.0 corpus pipeline orchestrator

Runs feature_factory → regime_writer → ic_engine → ensemble_trainer sequence.
Use for initial corpus population or incremental updates after schema changes.
Requires Redpanda + TimescaleDB running.
"""
```

**Shell script format:**

```bash
#!/usr/bin/env bash
#
# ops_corpus_pipeline_run.sh — v3.0 corpus pipeline orchestrator
#
# Runs feature_factory → regime_writer → ic_engine → ensemble_trainer sequence.
# Use for initial corpus population or incremental updates after schema changes.
# Requires Redpanda + TimescapeDB running.
#
```

**Answers three questions:**
- What does it do?
- When do I run it?
- What's non-obvious (dependencies)?

---

## Verification

After all phases:

1. **Grep for old paths** — ensure no references to `production/scripts/` or old script names
2. **Check imports** — Python scripts import correctly from new locations
3. **Test critical scripts** — run `ops_corpus_pipeline_run.sh`, `ops_roll_batch.py` to verify
4. **Update documentation** — operations-infrastructure.md, corpus-related docs

---

## Risk Assessment

**Risk:** Low

- File moves only, no algorithm changes
- Feature branch with revert capability
- No data migration or schema changes

**Mitigation:**
- Feature branch: `scripts-reorganization`
- Verification via grep before merge
- Test critical scripts after changes

---

## Principles Applied

1. **Renaissance continuous refinement** — clean as you go, don't defer debt
2. **Clear purpose boundaries** — ops vs infrastructure vs debug
3. **Essential clarity** — minimal descriptions that answer what/when/dependencies
4. **No bureaucracy** — 2-4 line descriptions, not exhaustive flag catalogs
5. **Deterministic moves** — every file has one canonical destination
