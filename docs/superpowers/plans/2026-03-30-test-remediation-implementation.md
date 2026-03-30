# Test Remediation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix all 138 test failures through systematic triage — delete, fix, or migrate each failing test to achieve 0 failures and 100% pass rate.

**Architecture:** Triage-First approach — Quick scan to categorize failures into 4 buckets (DELETE, MUST FIX, QUICK FIX, CASE-BY-CASE), then execute batch operations per category.

**Tech Stack:** pytest 9.0, Python 3.13, git

---

## Task 1: Capture All Test Failures

**Files:**
- Create: `/tmp/test_failures.txt`

**Goal:** Run full test suite and capture all failures with error types for categorization.

- [ ] **Step 1: Run pytest and capture failures**

```bash
cd /home/bg/dev/indicagent
.venv/bin/pytest tests/ --tb=no -q 2>&1 | tee /tmp/test_failures.txt
```

Expected output: Last line shows `138 failed, 2720 passed, 11 skipped`

- [ ] **Step 2: Extract failure patterns**

```bash
grep "FAILED" /tmp/test_failures.txt | awk -F'::' '{print $1}' | sort | uniq -c | sort -rn > /tmp/failure_by_file.txt
cat /tmp/failure_by_file.txt
```

Expected: Shows top failing files with counts (test_signal_lifecycle_service.py: 35, etc.)

- [ ] **Step 3: Categorize by error type**

```bash
# ModuleNotFoundError (DELETE candidates)
grep "ModuleNotFoundError.*signal_lifecycle_service" /tmp/test_failures.txt | wc -l
grep "ModuleNotFoundError.*smart_money" /tmp/test_failures.txt | wc -l

# AttributeError (QUICK FIX)
grep "AttributeError.*running.*has no setter" /tmp/test_failures.txt | wc -l

# AssertionError in test_signal_ledger (MUST FIX)
grep "test_signal_ledger.*AssertionError" /tmp/test_failures.txt | wc -l
```

Expected output: Confirms categorization counts match spec estimates

---

## Task 2: Delete test_smc_new_plugins.py (26 failures)

**Files:**
- Delete: `tests/unit/intelligence/test_smc_new_plugins.py`

**Goal:** Remove tests for deleted smart_money module (Phase 30 Redpanda migration removed this module).

- [ ] **Step 1: Verify file imports deleted module**

```bash
grep "from src.intelligence.smart_money" tests/unit/intelligence/test_smc_new_plugins.py | head -3
```

Expected: Shows imports like `from src.intelligence.smart_money import ...`

- [ ] **Step 2: Delete file via git**

```bash
git rm tests/unit/intelligence/test_smc_new_plugins.py
```

Expected: `rm 'tests/unit/intelligence/test_smc_new_plugins.py'`

- [ ] **Step 3: Verify deletion**

```bash
ls tests/unit/intelligence/test_smc_new_plugins.py 2>&1
```

Expected: `No such file or directory`

---

## Task 3: Delete test_signal_lifecycle_service.py (35 failures)

**Files:**
- Delete: `tests/unit/service_tests/test_signal_lifecycle_service.py`

**Goal:** Remove tests for deleted signal_lifecycle_service (renamed to signal_tracker_agent; new tests should target the actual agent).

- [ ] **Step 1: Verify file imports deleted service**

```bash
grep "from services.signal_lifecycle_service" tests/unit/service_tests/test_signal_lifecycle_service.py | head -3
```

Expected: Shows imports from deleted service

- [ ] **Step 2: Delete file via git**

```bash
git rm tests/unit/service_tests/test_signal_lifecycle_service.py
```

Expected: `rm 'tests/unit/service_tests/test_signal_lifecycle_service.py'`

- [ ] **Step 3: Verify deletion and check remaining failures**

```bash
ls tests/unit/service_tests/test_signal_lifecycle_service.py 2>&1
.venv/bin/pytest tests/ --tb=no -q 2>&1 | tail -1
```

Expected: File not found; failure count reduced from 138 to ~77

---

## Task 4: Verify Batch Deletions

**Files:**
- None (verification only)

**Goal:** Confirm deletions reduced failure count as expected.

- [ ] **Step 1: Run test suite and check new baseline**

```bash
.venv/bin/pytest tests/ --tb=no -q 2>&1 | grep -E "passed|failed"
```

Expected: Approximately `~77 failed, ~2694 passed` (61 failures eliminated)

- [ ] **Step 2: Confirm no regressions in passing tests**

```bash
.venv/bin/pytest tests/unit/service_tests/test_signal_writer_agent.py tests/unit/intelligence/test_aggregator.py -v --tb=short
```

Expected: All previously passing tests still pass

---

## Task 5: Investigate LedgerEntry Field Order

**Files:**
- Read: `src/persistence/repository/signal_ledger_repository.py`
- Modify: `tests/unit/intelligence/test_signal_ledger.py`

**Goal:** Determine correct field positions for to_insert_params() assertions.

- [ ] **Step 1: Get LedgerEntry dataclass field order**

```python
cd /home/bg/dev/indicagent
python3 << 'EOF'
from src.persistence.repository.signal_ledger_repository import LedgerEntry
fields = list(LedgerEntry.__dataclass_fields__.keys())
for i, field in enumerate(fields):
    print(f"{i}: {field}")
EOF
```

Expected output: Lists all 60 fields with indices

- [ ] **Step 2: Find positions for tested fields**

```python
python3 << 'EOF'
from src.persistence.repository.signal_ledger_repository import LedgerEntry
fields = list(LedgerEntry.__dataclass_fields__.keys())
print(f"targets index: {fields.index('targets')}")
print(f"supporting_factors index: {fields.index('supporting_factors')}")
print(f"cis_attribution index: {fields.index('cis_attribution')}")
print(f"raw_cis_score index: {fields.index('raw_cis_score')}")
print(f"filtered_cis_score index: {fields.index('filtered_cis_score')}")
print(f"calibrated_confidence index: {fields.index('calibrated_confidence')}")
print(f"regime_type_at_fire index: {fields.index('regime_type_at_fire')}")
EOF
```

Expected: Shows current indices (e.g., targets might be position 11 now, not 9)

---

## Task 6: Fix test_to_insert_params Position Assertions

**Files:**
- Modify: `tests/unit/intelligence/test_signal_ledger.py`

**Goal:** Update hardcoded array indices to match current LedgerEntry schema.

- [ ] **Step 1: Read the failing test**

```bash
grep -A 20 "def test_to_insert_params(self):" tests/unit/intelligence/test_signal_ledger.py
```

Expected: Shows test with assertions like `assert json.loads(params[9]) == [5110.0, 5120.0]`

- [ ] **Step 2: Run test to see exact failure**

```bash
.venv/bin/pytest tests/unit/intelligence/test_signal_ledger.py::TestLedgerEntry::test_to_insert_params -v --tb=short
```

Expected: FAIL with AssertionError on params[9] or similar

- [ ] **Step 3: Edit test - update params[9] to correct targets position**

```python
# Read the file first to see context
sed -n '66,80p' tests/unit/intelligence/test_signal_ledger.py
```

Then edit line ~74 (the targets assertion):

```python
# OLD (example):
assert json.loads(params[9]) == [5110.0, 5120.0]

# NEW (use actual index from Task 5):
assert json.loads(params[11]) == [5110.0, 5120.0]  # Updated to correct position
```

- [ ] **Step 4: Run test to verify fix**

```bash
.venv/bin/pytest tests/unit/intelligence/test_signal_ledger.py::TestLedgerEntry::test_to_insert_params -v
```

Expected: PASS

---

## Task 7: Fix test_to_insert_params_with_cis_fields Position Assertions

**Files:**
- Modify: `tests/unit/intelligence/test_signal_ledger.py`

**Goal:** Update CIS field position assertions.

- [ ] **Step 1: Run failing test**

```bash
.venv/bin/pytest tests/unit/intelligence/test_signal_ledger.py::TestLedgerEntry::test_to_insert_params_with_cis_fields -v --tb=short
```

Expected: FAIL on CIS field position assertions

- [ ] **Step 2: Update CIS field positions**

```python
# Find the assertions around lines 107-113
sed -n '107,113p' tests/unit/intelligence/test_signal_ledger.py
```

Edit based on actual indices from Task 5:

```python
# Example update (use actual positions from Task 5):
assert params[24] == pytest.approx(0.47)   # cis_score (index from Task 5)
assert parsed["trend"] == pytest.approx(0.4)  # bucket_scores parsed from JSON
```

- [ ] **Step 3: Run test to verify**

```bash
.venv/bin/pytest tests/unit/intelligence/test_signal_ledger.py::TestLedgerEntry::test_to_insert_params_with_cis_fields -v
```

Expected: PASS

---

## Task 8: Fix test_ledger_entry_to_insert_params_includes_attribution Position Assertion

**Files:**
- Modify: `tests/unit/intelligence/test_signal_ledger.py`

**Goal:** Update cis_attribution field position assertion.

- [ ] **Step 1: Run failing test**

```bash
.venv/bin/pytest tests/unit/intelligence/test_signal_ledger.py::test_ledger_entry_to_insert_params_includes_attribution -v --tb=short
```

Expected: FAIL on cis_attribution position

- [ ] **Step 2: Update cis_attribution position**

```python
# Find the assertion around line 238
sed -n '236,239p' tests/unit/intelligence/test_signal_ledger.py
```

Edit:

```python
# OLD (example):
assert '"psar_direction"' in params[36]

# NEW (use actual index from Task 5):
assert '"psar_direction"' in params[38]  # cis_attribution index from Task 5
```

- [ ] **Step 3: Run test to verify**

```bash
.venv/bin/pytest tests/unit/intelligence/test_signal_ledger.py::test_ledger_entry_to_insert_params_includes_attribution -v
```

Expected: PASS

---

## Task 9: Verify All Data Integrity Tests Pass

**Files:**
- None (verification)

**Goal:** Confirm all test_signal_ledger.py position tests are fixed.

- [ ] **Step 1: Run all test_signal_ledger tests**

```bash
.venv/bin/pytest tests/unit/intelligence/test_signal_ledger.py -v --tb=short
```

Expected: All tests pass (0 failures in this file)

- [ ] **Step 2: Check remaining failure count**

```bash
.venv/bin/pytest tests/ --tb=no -q 2>&1 | tail -1
```

Expected: Reduced to ~74 failed (eliminated 3 data integrity failures + 61 deletion failures)

---

## Task 10: Fix test_signal_tracker_agent.py _make_agent Helper

**Files:**
- Modify: `tests/unit/service_tests/test_signal_tracker_agent.py`

**Goal:** Fix test helper that tries to set read-only `running` property.

- [ ] **Step 1: Examine current _make_agent helper**

```bash
grep -A 20 "def _make_agent" tests/unit/service_tests/test_signal_tracker_agent.py
```

Expected: Shows bypass of `__init__` and attempt to set `agent.running = True`

- [ ] **Step 2: Run one failing test to confirm error**

```bash
.venv/bin/pytest tests/unit/service_tests/test_signal_tracker_agent.py -v --tb=line -k "test_" | head -20
```

Expected: `AttributeError: property 'running' of 'SignalTrackerAgent' object has no setter`

- [ ] **Step 3: Check how other tests handle agent lifecycle**

```bash
grep -A 10 "def _make_agent" tests/unit/service_tests/test_signal_writer_agent.py
```

Expected: Shows pattern of initializing instance attributes but not setting read-only properties

- [ ] **Step 4: Edit _make_agent to not set running property**

```python
# Find the exact line (likely around line 64)
grep -n "agent.running = True" tests/unit/service_tests/test_signal_tracker_agent.py
```

Remove or comment out the line that sets running:

```python
# OLD:
agent.running = True  # <- This causes error

# NEW:
# Don't set running - agent controls its own lifecycle
# Or use: await agent.start() if async context available
```

- [ ] **Step 5: Run tests to verify fix**

```bash
.venv/bin/pytest tests/unit/service_tests/test_signal_tracker_agent.py -v --tb=short
```

Expected: All 8 tests in this file now pass

---

## Task 11: Investigate test_feature_pipeline_service.py Failures (10 failures)

**Files:**
- Read: `tests/unit/service_tests/test_feature_pipeline_service.py`
- Read: `services/feature_compute_agent.py`

**Goal:** Determine if _INSERT_OHLCV_SQL constant exists elsewhere or if tests are obsolete.

- [ ] **Step 1: Check the import error**

```bash
grep "_INSERT_OHLCV_SQL" tests/unit/service_tests/test_feature_pipeline_service.py
```

Expected: Shows import from `services.feature_compute_agent`

- [ ] **Step 2: Search for constant in current codebase**

```bash
grep -r "_INSERT_OHLCV_SQL" src/ services/ --include="*.py" 2>/dev/null
```

Expected two outcomes:
- **If found:** Note the new location → Task 12 will fix import
- **If not found:** Constant was deleted → tests are obsolete → Task 12 will delete

- [ ] **Step 3: Check what FeaturePipelineService actually does**

```bash
head -50 services/feature_pipeline_service.py
```

Expected: Shows whether OHLCV insertion is still part of this service

---

## Task 12: Fix or Delete test_feature_pipeline_service.py

**Files:**
- Modify or Delete: `tests/unit/service_tests/test_feature_pipeline_service.py`

**Decision based on Task 11 findings.**

**If constant was deleted (tests obsolete):**
- [ ] **Step 1: Delete test file**

```bash
git rm tests/unit/service_tests/test_feature_pipeline_service.py
```

**If constant exists elsewhere (fix import):**
- [ ] **Step 1: Update import to new location**

```python
# OLD:
from services.feature_compute_agent import _INSERT_OHLCV_SQL

# NEW (example):
from services.intelligence_pipeline_agent import _INSERT_OHLCV_SQL
```

- [ ] **Step 2: Run tests to verify**

```bash
.venv/bin/pytest tests/unit/service_tests/test_feature_pipeline_service.py -v --tb=short
```

---

## Task 13: Investigate test_correctness_audit.py Failures (7 failures)

**Files:**
- Read: `tests/unit/intelligence/test_correctness_audit.py`

**Goal:** Determine if tests verify deleted I5 plugins or current ones.

- [ ] **Step 1: Run tests with detailed error output**

```bash
.venv/bin/pytest tests/unit/intelligence/test_correctness_audit.py -v --tb=line 2>&1 | head -40
```

- [ ] **Step 2: Check what plugins are being tested**

```bash
grep "class.*Test\|def test_" tests/unit/intelligence/test_correctness_audit.py | head -20
```

Expected: Shows test classes for BOS, CHoCH, FVG, liquidity sweeps, etc.

- [ ] **Step 3: Verify if tested plugins still exist**

```bash
grep -l "class.*CHoCH\|class.*FVG\|class.*LiquiditySweep" src/intelligence/trading/*.py 2>/dev/null
```

Expected two outcomes:
- **If plugins exist:** Tests are valid → fix import/usage
- **If plugins deleted:** Tests are obsolete → delete

---

## Task 14: Fix or Delete test_correctness_audit.py

**Files:**
- Modify or Delete: `tests/unit/intelligence/test_correctness_audit.py`

**Decision based on Task 13 findings.**

**If plugins deleted (obsolete tests):**
- [ ] **Step 1: Delete test file**

```bash
git rm tests/unit/intelligence/test_correctness_audit.py
```

**If plugins exist (fix imports):**
- [ ] **Step 1: Update imports and fix test usage**

```python
# Update plugin imports based on actual location
# Fix any mock usage to match current plugin interface
```

- [ ] **Step 2: Run tests to verify**

```bash
.venv/bin/pytest tests/unit/intelligence/test_correctness_audit.py -v --tb=short
```

---

## Task 15: Handle Script Tests (~20 failures)

**Files:**
- Investigate: `tests/unit/scripts/test_validate_alpha.py`
- Investigate: `tests/unit/scripts/test_rebuild_ohlcv.py`
- Investigate: `tests/unit/test_plugin_state_migration.py`

**Goal:** Determine if these are unit tests for scripts that should be integration tests.

- [ ] **Step 1: Check if scripts still exist**

```bash
ls -la production/scripts/validate_alpha.py 2>&1
ls -la production/scripts/rebuild_ohlcv.py 2>&1
ls -la tools/plugin_state_migration.py 2>&1
```

- [ ] **Step 2: Run script tests to see actual errors**

```bash
.venv/bin/pytest tests/unit/scripts/test_validate_alpha.py -v --tb=line 2>&1 | head -30
```

- [ ] **Step 3: Categorize and act**

| Scenario | Action |
|----------|--------|
| Script deleted | Delete test file |
| Script exists, test has import issues | Fix imports |
| Test is actually integration test | Move to `tests/integration/` and update |

---

## Task 16: Handle Remaining Failures (~30 failures)

**Files:**
- Various (investigation required)

**Goal:** Pattern-match and fix/delete remaining failures.

- [ ] **Step 1: Get list of remaining failing files**

```bash
.venv/bin/pytest tests/ --tb=no -q 2>&1 | grep "FAILED" | awk -F'::' '{print $1}' | sort -u > /tmp/remaining_failures.txt
cat /tmp/remaining_failures.txt
```

- [ ] **Step 2: For each remaining file, run and categorize**

```bash
# Example loop:
for file in $(cat /tmp/remaining_failures.txt); do
    echo "=== $file ==="
    .venv/bin/pytest "$file" -v --tb=line 2>&1 | head -15
done
```

- [ ] **Step 3: Apply appropriate fix pattern:**
  - Import error → Fix import or delete
  - Mock mismatch → Update mock to match current interface
  - Schema change → Update test expectations
  - Deleted functionality → Delete test

---

## Task 17: Full Test Suite Verification

**Files:**
- None (verification)

**Goal:** Confirm 0 failures across entire test suite.

- [ ] **Step 1: Run full test suite**

```bash
.venv/bin/pytest tests/ -v --tb=no 2>&1 | tee /tmp/final_run.txt
```

Expected: `0 failed, ~2800+ passed`

- [ ] **Step 2: Verify no regressions in previously passing tests**

```bash
# Check signal_writer_agent still passes
.venv/bin/pytest tests/unit/service_tests/test_signal_writer_agent.py -v

# Check aggregator tests still pass
.venv/bin/pytest tests/unit/intelligence/test_aggregator.py -v
```

Expected: All pass

- [ ] **Step 3: Generate summary report**

```bash
cat > /tmp/test_remediation_summary.txt << 'EOF'
Test Remediation Summary
========================
Before: 138 failed, 2720 passed (91.6% pass rate)
After:  0 failed, ~2800 passed (100% pass rate)

Files deleted: X
Files modified: Y
Tests fixed: Z
EOF
cat /tmp/test_remediation_summary.txt
```

---

## Task 18: Commit All Changes

**Files:**
- Commit: All modified and deleted test files

**Goal:** Commit remediation work with descriptive message documenting each change.

- [ ] **Step 1: Review staged changes**

```bash
git status
git diff --cached --stat
```

- [ ] **Step 2: Commit with comprehensive message**

```bash
git add -A
git commit -m "$(cat <<'EOF'
test: remediate all 138 test failures via triage-first approach

Deleted tests for removed functionality:
- test_smc_new_plugins.py (26 failures) - smart_money module deleted in Phase 30
- test_signal_lifecycle_service.py (35 failures) - service renamed to signal_tracker_agent
- test_feature_pipeline_service.py (10 failures) - _INSERT_OHLCV_SQL constant removed
- test_correctness_audit.py (7 failures) - tested deleted I5 plugins
- [Other files as needed]

Fixed data integrity tests:
- test_signal_ledger.py - Updated to_insert_params position assertions to match
  current LedgerEntry schema (Phase 57 added 2 attribution fields, shifted positions)

Fixed framework issues:
- test_signal_tracker_agent.py - Removed read-only property setter from _make_agent helper

Migrated/updated tests:
- [Document any migrations or test updates]

Result: 0 failures, 100% pass rate (2720 → ~2800 passing tests)

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 3: Push to remote**

```bash
git push origin main
```

---

## Task 19: Create Technical Debt Documentation (If Needed)

**Files:**
- Create: `docs/technical-debt/test-remediation-gaps.md` (only if any failures remain)

**Goal:** Document any failures that couldn't be resolved in this session for future follow-up.

- [ ] **Step 1: Check if any failures remain**

```bash
.venv/bin/pytest tests/ --tb=no -q 2>&1 | grep "failed"
```

- [ ] **Step 2: If failures remain, document them**

```bash
cat > docs/technical-debt/test-remediation-gaps.md << 'EOF'
# Test Remediation Gaps

Date: 2026-03-30

## Remaining Failures

[Document each remaining failure with:
- File name
- Test name
- Error
- Why it wasn't fixed
- Suggested next steps]

EOF
```

Only create this file if failures exist after Task 17.

---

**Plan complete.** Total estimated time: 2-3 hours for full remediation.
