# Scripts Reorganization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reorganize `scripts/` and `production/scripts/` into Renaissance-grade structure (ops/infrastructure/debug) with clear naming and minimal descriptions.

**Architecture:** Create new directory hierarchy, move/rename all scripts following `<domain>_<purpose>_<object>` pattern, update references, add minimal descriptions.

**Tech Stack:** Bash (file moves), Python (import updates), Markdown (documentation)

## Global Constraints

- **Naming pattern:** `<domain>_<purpose>_<object>.py|.sh` where domain ∈ {ops, infrastructure, debug}
- **Directory structure:** scripts/{ops/{corpus,roll,pipeline,signal}, infrastructure/{setup,backfill,kafka}, debug/{replay,validate,snapshot}}
- **Description format:** 2-4 lines max — what it does, when to run it, non-obvious dependencies
- **No algorithm changes:** File moves and renames only, no logic modifications
- **Feature branch:** Work on `scripts-reorganization` branch, verify with grep before merge

---

## File Structure

**New directories to create:**
- `scripts/ops/corpus/`
- `scripts/ops/roll/`
- `scripts/ops/pipeline/`
- `scripts/ops/signal/`
- `scripts/infrastructure/setup/`
- `scripts/infrastructure/backfill/`
- `scripts/infrastructure/kafka/`
- `scripts/debug/replay/`
- `scripts/debug/validate/`
- `scripts/debug/snapshot/`

**Files to move and rename (21 scripts):**

| Source | Destination |
|---|---|
| `production/scripts/corpus_pipeline_run.sh` | `scripts/ops/corpus/ops_corpus_pipeline_run.sh` |
| `production/scripts/corpus_progress.py` | `scripts/ops/corpus/ops_corpus_progress.py` |
| `scripts/corpus_final_verification.py` | `scripts/ops/corpus/ops_corpus_final_verification.py` |
| `production/scripts/pipeline_status.py` | `scripts/ops/pipeline/ops_pipeline_status.py` |
| `production/scripts/pipeline_audit.py` | `scripts/ops/pipeline/ops_pipeline_audit.py` |
| `production/scripts/roll_batch.py` | `scripts/ops/roll/ops_roll_batch.py` |
| `production/scripts/validate_roll_detection.py` | `scripts/ops/roll/ops_validate_roll_detection.py` |
| `production/scripts/db_setup.sh` | `scripts/infrastructure/setup/infrastructure_db_setup.sh` |
| `production/scripts/init_kafka_topics.sh` | `scripts/infrastructure/setup/infrastructure_init_kafka_topics.sh` |
| `production/scripts/backfill_missing_etfs.sh` | `scripts/infrastructure/backfill/infrastructure_backfill_missing_etfs.sh` |
| `production/scripts/backfill_missing_timeframes.sh` | `scripts/infrastructure/backfill/infrastructure_backfill_missing_timeframes.sh` |
| `production/scripts/run_historical_pipeline.py` | `scripts/infrastructure/backfill/infrastructure_run_historical_pipeline.py` |
| `production/scripts/enforce_topic_retention.py` | `scripts/infrastructure/kafka/infrastructure_enforce_topic_retention.py` |
| `production/scripts/ensure_topics.sh` | `scripts/infrastructure/kafka/infrastructure_ensure_topics.sh` |
| `production/scripts/redpanda_watchdog.sh` | `scripts/infrastructure/kafka/infrastructure_redpanda_watchdog.sh` |
| `production/scripts/replay_all.sh` | `scripts/debug/replay/debug_replay_all.sh` |
| `production/scripts/replay_prep.py` | `scripts/debug/replay/debug_replay_prep.py` |
| `production/scripts/replay_post.py` | `scripts/debug/replay/debug_replay_post.py` |
| `production/scripts/feature_replay.py` | `scripts/debug/replay/debug_feature_replay.py` |
| `production/scripts/lifecycle_replay.py` | `scripts/debug/replay/debug_lifecycle_replay.py` |
| `production/scripts/validate_alpha.py` | `scripts/debug/validate/debug_validate_alpha.py` |
| `production/scripts/signal_corpus_snapshot.py` | `scripts/debug/snapshot/debug_signal_corpus_snapshot.py` |
| `production/scripts/signal_ledger_snapshot.py` | `scripts/debug/snapshot/debug_signal_ledger_snapshot.py` |

**Documentation to update:**
- `docs/operations/operations-infrastructure.md` — references to script paths
- `docs/ideas/scripts-organization-audit.md` — can archive after completion
- Any runbooks or SOPs that reference old paths (to be discovered via grep)

---

### Task 1: Create feature branch and directory structure

**Files:**
- Create: directories under `scripts/`

**Interfaces:**
- Produces: Empty directory structure for subsequent file moves

- [ ] **Step 1: Create feature branch**

```bash
git checkout -b scripts-reorganization
```

Expected: Branch created and checked out

- [ ] **Step 2: Create ops directory structure**

```bash
mkdir -p scripts/ops/corpus
mkdir -p scripts/ops/roll
mkdir -p scripts/ops/pipeline
mkdir -p scripts/ops/signal
```

Expected: Directories created

- [ ] **Step 3: Create infrastructure directory structure**

```bash
mkdir -p scripts/infrastructure/setup
mkdir -p scripts/infrastructure/backfill
mkdir -p scripts/infrastructure/kafka
```

Expected: Directories created

- [ ] **Step 4: Create debug directory structure**

```bash
mkdir -p scripts/debug/replay
mkdir -p scripts/debug/validate
mkdir -p scripts/debug/snapshot
```

Expected: Directories created

- [ ] **Step 5: Verify directory structure**

```bash
tree scripts/ -d
```

Expected output:
```
scripts/
├── ops
│   ├── corpus
│   ├── pipeline
│   ├── roll
│   └── signal
├── infrastructure
│   ├── backfill
│   ├── kafka
│   └── setup
└── debug
    ├── replay
    ├── snapshot
    └── validate
```

- [ ] **Step 6: Commit directory structure**

```bash
git add scripts/
git commit -m "feat(scripts): create reorganized directory structure"
```

Expected: Commit created

---

### Task 2: Move and rename ops/corpus scripts

**Files:**
- Move: `production/scripts/corpus_pipeline_run.sh` → `scripts/ops/corpus/ops_corpus_pipeline_run.sh`
- Move: `production/scripts/corpus_progress.py` → `scripts/ops/corpus/ops_corpus_progress.py`
- Move: `scripts/corpus_final_verification.py` → `scripts/ops/corpus/ops_corpus_final_verification.py`

**Interfaces:**
- Consumes: Directory structure from Task 1
- Produces: Moved files with new names in ops/corpus/

- [ ] **Step 1: Move corpus_pipeline_run.sh**

```bash
mv production/scripts/corpus_pipeline_run.sh scripts/ops/corpus/ops_corpus_pipeline_run.sh
```

Expected: File moved

- [ ] **Step 2: Move corpus_progress.py**

```bash
mv production/scripts/corpus_progress.py scripts/ops/corpus/ops_corpus_progress.py
```

Expected: File moved

- [ ] **Step 3: Move corpus_final_verification.py**

```bash
mv scripts/corpus_final_verification.py scripts/ops/corpus/ops_corpus_final_verification.py
```

Expected: File moved

- [ ] **Step 4: Verify files moved**

```bash
ls -la scripts/ops/corpus/
```

Expected: Three files present

- [ ] **Step 5: Commit**

```bash
git add scripts/ops/corpus/ production/scripts/ scripts/
git commit -m "feat(scripts): move corpus scripts to ops/corpus/"
```

Expected: Commit created

---

### Task 3: Move and rename ops/pipeline scripts

**Files:**
- Move: `production/scripts/pipeline_status.py` → `scripts/ops/pipeline/ops_pipeline_status.py`
- Move: `production/scripts/pipeline_audit.py` → `scripts/ops/pipeline/ops_pipeline_audit.py`

**Interfaces:**
- Consumes: Directory structure from Task 1
- Produces: Moved files with new names in ops/pipeline/

- [ ] **Step 1: Move pipeline_status.py**

```bash
mv production/scripts/pipeline_status.py scripts/ops/pipeline/ops_pipeline_status.py
```

Expected: File moved

- [ ] **Step 2: Move pipeline_audit.py**

```bash
mv production/scripts/pipeline_audit.py scripts/ops/pipeline/ops_pipeline_audit.py
```

Expected: File moved

- [ ] **Step 3: Verify files moved**

```bash
ls -la scripts/ops/pipeline/
```

Expected: Two files present

- [ ] **Step 4: Commit**

```bash
git add scripts/ops/pipeline/ production/scripts/
git commit -m "feat(scripts): move pipeline scripts to ops/pipeline/"
```

Expected: Commit created

---

### Task 4: Move and rename ops/roll scripts

**Files:**
- Move: `production/scripts/roll_batch.py` → `scripts/ops/roll/ops_roll_batch.py`
- Move: `production/scripts/validate_roll_detection.py` → `scripts/ops/roll/ops_validate_roll_detection.py`

**Interfaces:**
- Consumes: Directory structure from Task 1
- Produces: Moved files with new names in ops/roll/

- [ ] **Step 1: Move roll_batch.py**

```bash
mv production/scripts/roll_batch.py scripts/ops/roll/ops_roll_batch.py
```

Expected: File moved

- [ ] **Step 2: Move validate_roll_detection.py**

```bash
mv production/scripts/validate_roll_detection.py scripts/ops/roll/ops_validate_roll_detection.py
```

Expected: File moved

- [ ] **Step 3: Verify files moved**

```bash
ls -la scripts/ops/roll/
```

Expected: Two files present

- [ ] **Step 4: Commit**

```bash
git add scripts/ops/roll/ production/scripts/
git commit -m "feat(scripts): move roll scripts to ops/roll/"
```

Expected: Commit created

---

### Task 5: Move and rename infrastructure/setup scripts

**Files:**
- Move: `production/scripts/db_setup.sh` → `scripts/infrastructure/setup/infrastructure_db_setup.sh`
- Move: `production/scripts/init_kafka_topics.sh` → `scripts/infrastructure/setup/infrastructure_init_kafka_topics.sh`

**Interfaces:**
- Consumes: Directory structure from Task 1
- Produces: Moved files with new names in infrastructure/setup/

- [ ] **Step 1: Move db_setup.sh**

```bash
mv production/scripts/db_setup.sh scripts/infrastructure/setup/infrastructure_db_setup.sh
```

Expected: File moved

- [ ] **Step 2: Move init_kafka_topics.sh**

```bash
mv production/scripts/init_kafka_topics.sh scripts/infrastructure/setup/infrastructure_init_kafka_topics.sh
```

Expected: File moved

- [ ] **Step 3: Verify files moved**

```bash
ls -la scripts/infrastructure/setup/
```

Expected: Two files present

- [ ] **Step 4: Commit**

```bash
git add scripts/infrastructure/setup/ production/scripts/
git commit -m "feat(scripts): move setup scripts to infrastructure/setup/"
```

Expected: Commit created

---

### Task 6: Move and rename infrastructure/backfill scripts

**Files:**
- Move: `production/scripts/backfill_missing_etfs.sh` → `scripts/infrastructure/backfill/infrastructure_backfill_missing_etfs.sh`
- Move: `production/scripts/backfill_missing_timeframes.sh` → `scripts/infrastructure/backfill/infrastructure_backfill_missing_timeframes.sh`
- Move: `production/scripts/run_historical_pipeline.py` → `scripts/infrastructure/backfill/infrastructure_run_historical_pipeline.py`

**Interfaces:**
- Consumes: Directory structure from Task 1
- Produces: Moved files with new names in infrastructure/backfill/

- [ ] **Step 1: Move backfill_missing_etfs.sh**

```bash
mv production/scripts/backfill_missing_etfs.sh scripts/infrastructure/backfill/infrastructure_backfill_missing_etfs.sh
```

Expected: File moved

- [ ] **Step 2: Move backfill_missing_timeframes.sh**

```bash
mv production/scripts/backfill_missing_timeframes.sh scripts/infrastructure/backfill/infrastructure_backfill_missing_timeframes.sh
```

Expected: File moved

- [ ] **Step 3: Move run_historical_pipeline.py**

```bash
mv production/scripts/run_historical_pipeline.py scripts/infrastructure/backfill/infrastructure_run_historical_pipeline.py
```

Expected: File moved

- [ ] **Step 4: Verify files moved**

```bash
ls -la scripts/infrastructure/backfill/
```

Expected: Three files present

- [ ] **Step 5: Commit**

```bash
git add scripts/infrastructure/backfill/ production/scripts/
git commit -m "feat(scripts): move backfill scripts to infrastructure/backfill/"
```

Expected: Commit created

---

### Task 7: Move and rename infrastructure/kafka scripts

**Files:**
- Move: `production/scripts/enforce_topic_retention.py` → `scripts/infrastructure/kafka/infrastructure_enforce_topic_retention.py`
- Move: `production/scripts/ensure_topics.sh` → `scripts/infrastructure/kafka/infrastructure_ensure_topics.sh`
- Move: `production/scripts/redpanda_watchdog.sh` → `scripts/infrastructure/kafka/infrastructure_redpanda_watchdog.sh`

**Interfaces:**
- Consumes: Directory structure from Task 1
- Produces: Moved files with new names in infrastructure/kafka/

- [ ] **Step 1: Move enforce_topic_retention.py**

```bash
mv production/scripts/enforce_topic_retention.py scripts/infrastructure/kafka/infrastructure_enforce_topic_retention.py
```

Expected: File moved

- [ ] **Step 2: Move ensure_topics.sh**

```bash
mv production/scripts/ensure_topics.sh scripts/infrastructure/kafka/infrastructure_ensure_topics.sh
```

Expected: File moved

- [ ] **Step 3: Move redpanda_watchdog.sh**

```bash
mv production/scripts/redpanda_watchdog.sh scripts/infrastructure/kafka/infrastructure_redpanda_watchdog.sh
```

Expected: File moved

- [ ] **Step 4: Verify files moved**

```bash
ls -la scripts/infrastructure/kafka/
```

Expected: Three files present

- [ ] **Step 5: Commit**

```bash
git add scripts/infrastructure/kafka/ production/scripts/
git commit -m "feat(scripts): move kafka scripts to infrastructure/kafka/"
```

Expected: Commit created

---

### Task 8: Move and rename debug/replay scripts

**Files:**
- Move: `production/scripts/replay_all.sh` → `scripts/debug/replay/debug_replay_all.sh`
- Move: `production/scripts/replay_prep.py` → `scripts/debug/replay/debug_replay_prep.py`
- Move: `production/scripts/replay_post.py` → `scripts/debug/replay/debug_replay_post.py`
- Move: `production/scripts/feature_replay.py` → `scripts/debug/replay/debug_feature_replay.py`
- Move: `production/scripts/lifecycle_replay.py` → `scripts/debug/replay/debug_lifecycle_replay.py`

**Interfaces:**
- Consumes: Directory structure from Task 1
- Produces: Moved files with new names in debug/replay/

- [ ] **Step 1: Move replay_all.sh**

```bash
mv production/scripts/replay_all.sh scripts/debug/replay/debug_replay_all.sh
```

Expected: File moved

- [ ] **Step 2: Move replay_prep.py**

```bash
mv production/scripts/replay_prep.py scripts/debug/replay/debug_replay_prep.py
```

Expected: File moved

- [ ] **Step 3: Move replay_post.py**

```bash
mv production/scripts/replay_post.py scripts/debug/replay/debug_replay_post.py
```

Expected: File moved

- [ ] **Step 4: Move feature_replay.py**

```bash
mv production/scripts/feature_replay.py scripts/debug/replay/debug_feature_replay.py
```

Expected: File moved

- [ ] **Step 5: Move lifecycle_replay.py**

```bash
mv production/scripts/lifecycle_replay.py scripts/debug/replay/debug_lifecycle_replay.py
```

Expected: File moved

- [ ] **Step 6: Verify files moved**

```bash
ls -la scripts/debug/replay/
```

Expected: Five files present

- [ ] **Step 7: Commit**

```bash
git add scripts/debug/replay/ production/scripts/
git commit -m "feat(scripts): move replay scripts to debug/replay/"
```

Expected: Commit created

---

### Task 9: Move and rename debug/validate script

**Files:**
- Move: `production/scripts/validate_alpha.py` → `scripts/debug/validate/debug_validate_alpha.py`

**Interfaces:**
- Consumes: Directory structure from Task 1
- Produces: Moved file with new name in debug/validate/

- [ ] **Step 1: Move validate_alpha.py**

```bash
mv production/scripts/validate_alpha.py scripts/debug/validate/debug_validate_alpha.py
```

Expected: File moved

- [ ] **Step 2: Verify file moved**

```bash
ls -la scripts/debug/validate/
```

Expected: One file present

- [ ] **Step 3: Commit**

```bash
git add scripts/debug/validate/ production/scripts/
git commit -m "feat(scripts): move validate scripts to debug/validate/"
```

Expected: Commit created

---

### Task 10: Move and rename debug/snapshot scripts

**Files:**
- Move: `production/scripts/signal_corpus_snapshot.py` → `scripts/debug/snapshot/debug_signal_corpus_snapshot.py`
- Move: `production/scripts/signal_ledger_snapshot.py` → `scripts/debug/snapshot/debug_signal_ledger_snapshot.py`

**Interfaces:**
- Consumes: Directory structure from Task 1
- Produces: Moved files with new names in debug/snapshot/

- [ ] **Step 1: Move signal_corpus_snapshot.py**

```bash
mv production/scripts/signal_corpus_snapshot.py scripts/debug/snapshot/debug_signal_corpus_snapshot.py
```

Expected: File moved

- [ ] **Step 2: Move signal_ledger_snapshot.py**

```bash
mv production/scripts/signal_ledger_snapshot.py scripts/debug/snapshot/debug_signal_ledger_snapshot.py
```

Expected: File moved

- [ ] **Step 3: Verify files moved**

```bash
ls -la scripts/debug/snapshot/
```

Expected: Two files present

- [ ] **Step 4: Commit**

```bash
git add scripts/debug/snapshot/ production/scripts/
git commit -m "feat(scripts): move snapshot scripts to debug/snapshot/"
```

Expected: Commit created

---

### Task 11: Update Python imports in moved scripts

**Files:**
- Modify: All moved `.py` files (14 files total)

**Interfaces:**
- Consumes: Moved files from Tasks 2-10
- Produces: Updated imports reflecting new file locations

- [ ] **Step 1: Find Python files with imports to update**

```bash
find scripts/ -name "*.py" -type f
```

Expected: List of 14 Python files

- [ ] **Step 2: Check for relative imports that need updating**

```bash
grep -r "from production.scripts\|import production.scripts" scripts/
grep -r "from scripts\|import scripts" scripts/ | grep -v "# "
```

Expected: Output showing files needing import updates (or empty if none)

- [ ] **Step 3: Update imports in each file that needs them**

For each file found in Step 2, update the import path. Example:

```bash
# If a file has: from production.scripts.corpus_progress import X
# Change to: from scripts.ops.corpus.ops_corpus_progress import X
```

Use `sed` or manual edit per file found.

- [ ] **Step 4: Verify no broken imports remain**

```bash
grep -r "from production.scripts\|import production.scripts" scripts/
```

Expected: No output (all imports updated)

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat(scripts): update imports for new file locations"
```

Expected: Commit created (or nothing to commit if no imports needed updating)

---

### Task 12: Check for remaining files in production/scripts/

**Files:**
- Verify: `production/scripts/` directory

**Interfaces:**
- Consumes: File moves from Tasks 2-10
- Produces: Clean production/scripts/ or list of remaining files

- [ ] **Step 1: List remaining files in production/scripts/**

```bash
find production/scripts/ -type f
```

Expected: List of any remaining files (SQL files, config files, etc.)

- [ ] **Step 2: Handle remaining files appropriately**

For each remaining file:
- If SQL file: consider moving to `infrastructure/setup/` or appropriate location
- If config file: determine correct destination
- If obsolete: delete or archive

- [ ] **Step 3: Commit any additional moves or deletions**

```bash
git add -A
git commit -m "feat(scripts): handle remaining production/scripts/ files"
```

Expected: Commit created (or nothing to commit)

---

### Task 13: Grep for old script path references in codebase

**Files:**
- Search: All documentation, config, and source files
- Modify: Files referencing old script paths

**Interfaces:**
- Consumes: Moved files from Tasks 2-10
- Produces: Updated references throughout codebase

- [ ] **Step 1: Search for references to old script paths**

```bash
grep -r "production/scripts/" . --exclude-dir=.git --exclude-dir=node_modules --exclude-dir=.venv --exclude-dir=dashboard
```

Expected: List of files containing old path references

- [ ] **Step 2: Search for references to old script names**

```bash
grep -r "corpus_pipeline_run\|corpus_progress\|pipeline_status\|pipeline_audit\|roll_batch\|validate_roll_detection\|backfill_missing\|run_historical_pipeline\|enforce_topic_retention\|ensure_topics\|redpanda_watchdog\|replay_all\|replay_prep\|replay_post\|feature_replay\|lifecycle_replay\|validate_alpha\|signal_corpus_snapshot\|signal_ledger_snapshot" . --exclude-dir=.git --exclude-dir=node_modules --exclude-dir=.venv --exclude-dir=dashboard | grep -v "scripts/"
```

Expected: List of files containing old script name references

- [ ] **Step 3: Update each file with new paths/names**

For each file found, update references to use new paths. Example:

```bash
# In operations-infrastructure.md:
# Old: See production/scripts/corpus_pipeline_run.sh
# New: See scripts/ops/corpus/ops_corpus_pipeline_run.sh
```

- [ ] **Step 4: Verify no old references remain**

```bash
grep -r "production/scripts/" . --exclude-dir=.git --exclude-dir=node_modules --exclude-dir=.venv --exclude-dir=dashboard
```

Expected: No output (or only in git history/comments)

- [ ] **Step 5: Commit documentation updates**

```bash
git add -A
git commit -m "docs(scripts): update references to new script paths"
```

Expected: Commit created

---

### Task 14: Verify critical scripts work after moves

**Files:**
- Test: Selected scripts to verify they still execute

**Interfaces:**
- Consumes: All moved and updated files from Tasks 2-13
- Produces: Verified working scripts

- [ ] **Step 1: Test corpus script help**

```bash
python scripts/ops/corpus/ops_corpus_progress.py --help
```

Expected: Help output or script executes without import errors

- [ ] **Step 2: Test roll script**

```bash
python scripts/ops/roll/ops_roll_batch.py --help
```

Expected: Help output or script executes without import errors

- [ ] **Step 3: Test infrastructure script**

```bash
python scripts/infrastructure/backfill/infrastructure_run_historical_pipeline.py --help
```

Expected: Help output or script executes without import errors

- [ ] **Step 4: Verify shell script syntax**

```bash
bash -n scripts/ops/corpus/ops_corpus_pipeline_run.sh
```

Expected: No syntax errors

- [ ] **Step 5: Note any issues found**

If any script fails, note the issue and fix before proceeding.

- [ ] **Step 6: Commit (if fixes needed)**

```bash
git add -A
git commit -m "fix(scripts): fix issues found during verification"
```

Expected: Commit created (or nothing to commit)

---

### Task 15: Add descriptions to Python scripts

**Files:**
- Modify: All moved `.py` files (14 files)

**Interfaces:**
- Consumes: Moved and verified files from Tasks 2-14
- Produces: Python scripts with 2-4 line docstring descriptions

- [ ] **Step 1: List all Python scripts**

```bash
find scripts/ -name "*.py" -type f | sort
```

Expected: 14 Python files listed

- [ ] **Step 2: For each Python script, add description docstring at top**

Read each file and add/replace the first docstring with format:

```python
"""
ops_<purpose>_<object>.py — <one-line description>

<What it does — one sentence>
<When to run it — one line>
<Non-obvious dependencies — one line if applicable>
"""
```

Examples for specific scripts:

```python
# ops_corpus_progress.py:
"""
ops_corpus_progress.py — v3.0 corpus pipeline progress tracker

Reports current progress of corpus pipeline runs including completed steps,
time elapsed, and estimated remaining time. Run during corpus pipeline execution
to monitor progress without querying the database directly.
Requires corpus pipeline run ID or active process detection.
"""

# ops_roll_batch.py:
"""
ops_roll_batch.py — nightly futures contract roll automation

Executes futures contract rolling for all active contracts including front-month
promotion, open interest transfer, and metadata updates. Run nightly via cron
or systemd timer. Requires TimescaleDB connection and IBKR Gateway available.
"""

# debug_validate_alpha.py:
"""
debug_validate_alpha.py — alpha signal validation and diagnostics

Validates alpha signal quality including confidence distribution, regime
stratification, and temporal consistency. Run when debugging signal quality
issues or after signal logic changes. Requires signal_events table populated.
"""
```

- [ ] **Step 3: Verify all scripts have descriptions**

```bash
for file in $(find scripts/ -name "*.py" -type f); do
    echo "=== $file ==="
    head -5 "$file"
done
```

Expected: All scripts show description docstring at top

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "docs(scripts): add descriptions to Python scripts"
```

Expected: Commit created

---

### Task 16: Add descriptions to shell scripts

**Files:**
- Modify: All moved `.sh` files (10 files)

**Interfaces:**
- Consumes: Moved and verified files from Tasks 2-14
- Produces: Shell scripts with header comment descriptions

- [ ] **Step 1: List all shell scripts**

```bash
find scripts/ -name "*.sh" -type f | sort
```

Expected: 10 shell scripts listed

- [ ] **Step 2: For each shell script, add description header after shebang**

Read each file and add header comment after `#!/usr/bin/env bash`:

```bash
#!/usr/bin/env bash
#
# ops_<purpose>_<object>.sh — <one-line description>
#
# <What it does — one sentence>
# <When to run it — one line>
# <Non-obvious dependencies — one line if applicable>
#
```

Examples for specific scripts:

```bash
# ops_corpus_pipeline_run.sh:
#!/usr/bin/env bash
#
# ops_corpus_pipeline_run.sh — v3.0 corpus pipeline orchestrator
#
# Runs feature_factory → regime_writer → ic_engine → ensemble_trainer sequence
# for corpus generation. Use for initial population or incremental updates.
# Requires Redpanda + TimescaleDB running.
#

# infrastructure_db_setup.sh:
#!/usr/bin/env bash
#
# infrastructure_db_setup.sh — database schema initialization
#
# Initializes TimescaleDB schema including tables, hypertables, and triggers.
# Run once on fresh database installation or after major schema migrations.
# Requires psql client and TimescaleDB extension installed.
#

# debug_replay_all.sh:
#!/usr/bin/env bash
#
# debug_replay_all.sh — full pipeline replay for debugging
#
# Replays entire pipeline from raw bars to signals for specified time window.
# Use when debugging pipeline behavior or reproducing historical issues.
# Requires market_data_ohlcv backfill for target period.
#
```

- [ ] **Step 3: Verify all scripts have descriptions**

```bash
for file in $(find scripts/ -name "*.sh" -type f); do
    echo "=== $file ==="
    head -8 "$file"
done
```

Expected: All scripts show description header after shebang

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "docs(scripts): add descriptions to shell scripts"
```

Expected: Commit created

---

### Task 17: Final verification and merge preparation

**Files:**
- Verify: All changes complete
- Modify: Any remaining issues

**Interfaces:**
- Consumes: All work from Tasks 1-16
- Produces: Clean branch ready for merge

- [ ] **Step 1: Verify no old path references remain**

```bash
grep -r "production/scripts/" . --exclude-dir=.git --exclude-dir=node_modules --exclude-dir=.venv --exclude-dir=dashboard --exclude-dir=.claude
```

Expected: No output

- [ ] **Step 2: Verify all scripts are in new structure**

```bash
tree scripts/
```

Expected: All 25 files (14 Python + 10 shell + 1 other) in new directories

- [ ] **Step 3: Verify production/scripts/ is empty or has only intentional files**

```bash
ls -la production/scripts/
```

Expected: Empty or only intentionally-remaining files (document these)

- [ ] **Step 4: Run linter on Python files**

```bash
.venv/bin/ruff check scripts/
```

Expected: No lint errors (or fix any found)

- [ ] **Step 5: Verify branch commits**

```bash
git log --oneline main..HEAD
```

Expected: List of ~17 commits from Tasks 1-16

- [ ] **Step 6: Final commit if any fixes needed**

```bash
git add -A
git commit -m "chore(scripts): final cleanup and verification fixes"
```

Expected: Commit created (or nothing to commit)

- [ ] **Step 7: Merge to main**

```bash
git checkout main
git merge --ff-only scripts-reorganization
```

Expected: Clean merge

- [ ] **Step 8: Delete feature branch**

```bash
git branch -d scripts-reorganization
```

Expected: Branch deleted

---

### Task 18: Archive audit doc and update todo

**Files:**
- Move: `docs/ideas/scripts-organization-audit.md` → archive
- Update: `.planning/todos/pending/028-scripts-organization.md`

**Interfaces:**
- Consumes: Completed reorganization from Tasks 1-17
- Produces: Cleaned up documentation and completed todo

- [ ] **Step 1: Move audit doc to archive**

```bash
mkdir -p docs/ideas/archive
mv docs/ideas/scripts-organization-audit.md docs/ideas/archive/
```

Expected: File moved to archive

- [ ] **Step 2: Update todo to completed**

```bash
mv .planning/todos/pending/028-scripts-organization.md .planning/todos/completed/
```

Expected: Todo moved to completed

- [ ] **Step 3: Commit cleanup**

```bash
git add docs/ideas/archive/scripts-organization-audit.md docs/ideas/ .planning/todos/
git commit -m "chore(scripts): archive audit doc, complete todo 028"
```

Expected: Commit created

- [ ] **Step 4: Verify git status**

```bash
git status
```

Expected: Clean working directory

---

## Plan Summary

**Total tasks:** 18
**Estimated time:** 2-3 hours
**Commits:** ~18-20 atomic commits
**Risk:** Low (file moves only, no algorithm changes)

**Verification checkpoints:**
- Task 11: Imports updated
- Task 13: Documentation references updated
- Task 14: Critical scripts execute
- Task 17: Final grep verification

**Rollback plan:** If issues arise, `git reset --hard main` before merge, or revert merge commit after.
