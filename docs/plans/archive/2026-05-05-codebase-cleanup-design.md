# Codebase Cleanup Design

**Date:** 2026-05-05  
**Scope:** Dead code removal, test consolidation, permanent CI guards  
**Approach:** Cleanup-first, then wire automated enforcement

## Goal

Maximize signal-to-noise ratio in the codebase. Remove dead code, consolidate duplicate tests, and wire automated detection so noise never accumulates again. Renaissance principle: dead code is noise; noise degrades the system's ability to reason about itself.

## Non-goals

- `.planning/` directory — historical planning artifacts are the research trail, kept as-is
- `docs/plans/archive/` — already organized, not touched
- Integration test count or coverage

---

## Section 1: Baseline

Before any deletion, capture a reproducible baseline.

```bash
# Unit tests — CI gate (deterministic, no infra dependency)
.venv/bin/coverage run -m pytest tests/unit/ -q
.venv/bin/coverage report --format=markdown > /tmp/coverage_baseline.md

# Integration tests — local only (requires live TimescaleDB + Redpanda)
.venv/bin/pytest tests/integration/ -v --tb=short 2>&1 | tee /tmp/baseline_integration.txt
```

**Rule:** Any cleanup step that causes a unit test failure is immediately reverted — no exceptions. Coverage floor is set from this baseline; no PR may drop below it.

---

## Section 2: Cleanup Execution

Steps are sequential. Each step must produce a green unit test suite before proceeding.

### Step 1 — Delete phase-numbered stream_keys tests

**Files to delete:**
- `tests/unit/test_stream_keys_57.py`
- `tests/unit/test_stream_keys_61.py`

**Rationale:** Added at phase boundaries to test Kafka topic functions new at the time. The organized `tests/unit/core/test_stream_keys_*.py` suite covers the same topic functions as part of normal regression. Phase-numbered names are noise — they signal historical context, not test purpose.

**Verification:** Run `pytest tests/unit/` after deletion. Green = proceed.

### Step 2 — Audit and remove `src/indicators/`

**Module:** `src/indicators/` (6 files: `backend_manager.py`, `calculations.py`, `incremental_manager.py`, `utils.py`, `calc_modules/`)

**Audit method:**
```bash
# Check all external imports into the module
grep -r "from src.indicators\|import indicators" src/ services/ tests/ \
  --include="*.py" -l | grep -v "src/indicators/"
```

If no external consumers exist outside `src/indicators/` itself and its own tests, the module is dead — superseded by the intelligence plugin system. Delete `src/indicators/` and `tests/unit/indicators/` together as a unit.

**If any live external consumer is found:** leave the module, document the dependency, defer to a dedicated audit.

**Verification:** Run `pytest tests/unit/` after deletion. Green = proceed.

### Step 3 — Merge root-level duplicate test files

Six test files exist at both `tests/unit/` root and in organized subdirectories with divergent content (not identical copies). For each pair, merge unique test cases from the root file into the organized file, then delete the root file.

| Root file (delete) | Organized file (keep + merge into) |
|---|---|
| `tests/unit/test_bar_auditor_agent.py` | `tests/unit/service_tests/test_bar_auditor_agent.py` |
| `tests/unit/test_contract_metadata_writer_agent.py` | `tests/unit/service_tests/test_contract_metadata_writer_agent.py` |
| `tests/unit/test_historical_backfill.py` | `tests/unit/scripts/test_historical_backfill.py` |
| `tests/unit/test_kafka_utils.py` | `tests/unit/core/test_kafka_utils.py` |
| `tests/unit/test_models.py` | `tests/unit/core/test_models.py` |
| `tests/unit/test_bar_message.py` | `tests/unit/core/test_bar_message.py` |

**Process per pair:**
1. Diff the two files
2. Identify test functions in the root file not present (by name or equivalent coverage) in the organized file
3. Move unique test functions into the organized file
4. Delete the root file
5. Run `pytest tests/unit/` — green = proceed to next pair

---

## Section 3: CI/Pre-commit Guards

Wire four automated guards after cleanup is verified green. These enforce cleanliness on every future commit and PR.

### Guard 1 — `vulture` dead code (pre-commit)

Add to `.githooks/pre-commit`:
```bash
.venv/bin/vulture src/ services/ --min-confidence 80
```

Create `vulture_whitelist.py` at project root for intentional false positives (plugin protocol methods called via registry, `__all__` exports, etc.).

**Blocks commit** if unreachable code is introduced.

### Guard 2 — `ruff` unused imports (verify existing pre-commit)

`ruff` is already in `.githooks/pre-commit`. Verify `pyproject.toml` or `ruff.toml` enables:
- `F401` — unused imports
- `F811` — redefinition of unused name

No new wiring needed if already enabled. If not, add these rule codes to the `select` list.

### Guard 3 — Duplicate test detector (CI)

New script: `tools/check_duplicate_tests.py`

Logic: collect all `def test_*` function names across `tests/unit/`, report any name appearing in more than one file. Exit non-zero if duplicates found.

Add to `.github/workflows/` CI job after pytest step. Fails CI if a test function name is duplicated — forces the author to either rename (intentionally different behavior) or consolidate.

### Guard 4 — Coverage floor (CI)

Add to pytest CI invocation:
```bash
.venv/bin/pytest tests/unit/ --cov=src --cov=services \
  --cov-fail-under=<baseline_pct>
```

Set `<baseline_pct>` from the coverage baseline captured in Section 1, rounded down to the nearest integer. Any PR that deletes tests without replacing coverage fails automatically.

---

## Success Criteria

- Unit test suite green before and after cleanup
- Integration tests pass locally (no regressions in live pipeline paths)
- `src/indicators/` removed if confirmed dead, or documented if live consumer found
- 8 test files deleted (2 phase-numbered + 6 root-level duplicates), unique cases merged
- 4 CI guards active on main branch
- `git status` produces no unexpected noise
