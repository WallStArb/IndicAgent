# Test Remediation: Triage-First Strategy

**Date:** 2026-03-30
**Status:** Design Approved
**Next:** Implementation Plan

---

## Overview

Fix all 138 test failures through systematic triage. Each failing test is either fixed, migrated, or deleted with justification. Goal: 0 failures, 91.6% → 100% pass rate.

**Renaissance principles applied:**
- Data integrity is non-negotiable — SQL position tests must pass
- Ruthless efficiency — Quick scan before deep investigation
- Scientific method — Categorize based on evidence, then act
- Degrade gracefully — If a test can't be fixed in time budget, delete it consciously

---

## Current State

| Metric | Value |
|--------|-------|
| Tests passing | 2720 (91.6%) |
| Tests failing | 138 |
| Tests skipped | 11 |
| Errors | 6 (runtime, not collection blockers) |

**Failure distribution:**
| Category | Estimated Count | Files |
|----------|----------------|-------|
| Deleted service/module imports | ~70 | 3 files |
| Data integrity (SQL positions) | 3 | 1 file |
| Framework issues | 8 | 1 file |
| Logic/unknown | ~57 | ~12 files |

---

## Architecture: Triage Pipeline

```
Quick Scan (10 min)
    ↓
Categorize into 4 buckets
    ↓
┌─────────────┬──────────────┬─────────────┬──────────────┐
│ DELETE      │ MUST FIX     │ QUICK FIX   │ CASE-BY-CASE│
│ (~70 tests) │ (3 tests)    │ (8 tests)   │ (~57 tests)  │
└─────────────┴──────────────┴─────────────┴──────────────┘
    │              │              │              │
    ↓              ↓              ↓              ↓
 Delete files   Fix SQL      Fix test      Investigate
                positions    framework   & decide
```

---

## Triage Rules

| Bucket | Criteria | Action | Time Budget |
|--------|----------|--------|-------------|
| **DELETE** | Imports deleted module/service; tests deleted functionality | `git rm` file | 5 min |
| **MUST FIX** | Data integrity (SQL positions, schema contracts, DB writes) | Fix positions, verify against actual schema | 30 min |
| **QUICK FIX** | Framework issues, test setup problems (<5 min to fix) | Patch test code, use correct lifecycle methods | 15 min |
| **CASE-BY-CASE** | Logic tests that may have migrated; unknown errors | Investigate where logic went → migrate or delete | 60-90 min |

---

## Execution Plan

### Step 1: Quick Scan (10 minutes)

Run pytest on all failing files to capture error patterns:

```bash
# Capture all failures with error types
pytest tests/ --tb=no -q > /tmp/failures.txt 2>&1

# Categorize by error message pattern
grep "FAILED" /tmp/failures.txt | grep "ModuleNotFoundError"  # DELETE candidates
grep "FAILED" /tmp/failures.txt | grep "AttributeError.*running"  # QUICK FIX
grep "FAILED" /tmp/failures.txt | grep "AssertionError.*params\["  # MUST FIX
```

### Step 2: Batch DELETE (5 minutes)

**Files to delete immediately:**

| File | Failures | Reason |
|------|----------|--------|
| `tests/unit/intelligence/test_smc_new_plugins.py` | 26 | Imports `src.intelligence.smart_money` (deleted Phase 30) |
| `tests/unit/service_tests/test_signal_lifecycle_service.py` | 35 | Imports `services.signal_lifecycle_service` (renamed to `signal_tracker_agent`) |

**Command:**
```bash
git rm tests/unit/intelligence/test_smc_new_plugins.py
git rm tests/unit/service_tests/test_signal_lifecycle_service.py
```

### Step 3: MUST FIX — Data Integrity (30 minutes)

**File:** `tests/unit/intelligence/test_signal_ledger.py`

**Failures:**
- `test_to_insert_params` — params[9] expects targets, position shifted
- `test_to_insert_params_with_cis_fields` — Similar position issue
- `test_ledger_entry_to_insert_params_includes_attribution` — Similar position issue

**Root cause:** `LedgerEntry.to_insert_params()` returns a positional list that must match SQL `$1, $2, $3...` positions. Schema evolution (Phase 57 added 2 attribution fields) shifted all positions.

**Fix:**
```python
# In test file, recalculate positions:
from src.persistence.repository.signal_ledger_repository import LedgerEntry
fields = list(LedgerEntry.__dataclass_fields__.keys())

# Find new positions:
targets_index = fields.index('targets')  # Was 9, now ?
supporting_factors_index = fields.index('supporting_factors')
# Update assertions with correct indices
```

**Verification:**
```bash
pytest tests/unit/intelligence/test_signal_ledger.py::TestLedgerEntry::test_to_insert_params -v
```

### Step 4: QUICK FIX — Framework Issues (15 minutes)

**File:** `tests/unit/service_tests/test_signal_tracker_agent.py`

**Failures:** 8 tests fail with `AttributeError: property 'running' has no setter`

**Root cause:** Test helper `_make_agent()` bypasses `__init__` then tries to set read-only property:

```python
def _make_agent():
    agent = SignalTrackerAgent.__new__(SignalTrackerAgent)
    agent.running = True  # ← Error: running is read-only
```

**Fix:** Use agent's lifecycle methods instead of bypassing:

```python
async def _make_agent():
    from unittest.mock import AsyncMock, MagicMock
    agent = SignalTrackerAgent()
    agent._consumer = AsyncMock()
    agent._db = MagicMock()
    # Don't set running directly - agent controls its own lifecycle
    return agent
```

Or, if test must control lifecycle directly, mock the start/stop methods.

### Step 5: CASE-BY-CASE Investigation (60-90 minutes)

**Priority order:**

1. **`test_feature_pipeline_service.py` (10 failures)**
   - Error: `ImportError: cannot import name '_INSERT_OHLCV_SQL' from 'services.feature_compute_agent'`
   - Investigation: Does this SQL constant exist elsewhere? Was this query moved?
   - Decision: Migrate to new location OR delete if query no longer used

2. **`test_correctness_audit.py` (7 failures)**
   - Investigation: Are these testing deleted I5 plugins or current ones?
   - If deleted plugins → DELETE
   - If current plugins → FIX import or test logic

3. **Script tests:** `test_validate_alpha.py`, `test_rebuild_ohlcv.py`, `test_plugin_state_migration.py`
   - Investigation: Do these scripts exist? Are they integration tests in disguise?
   - If scripts deleted → DELETE tests
   - If scripts exist → FIX or migrate to integration test directory

4. **Remaining ~30 failures**
   - Pattern-match against known categories
   - Apply appropriate fix strategy

### Step 6: Verification (10 minutes)

```bash
# Full test suite
pytest tests/ -v --tb=short

# Confirm metrics:
# - 0 failures
# - Pass rate increased from 91.6% to ~95%+
```

---

## Risk Mitigation

| Risk | Mitigation |
|------|------------|
| Deleting valuable test coverage | Case-by-case bucket preserves logic tests; investigate before deleting |
| Fixing SQL positions incorrectly | Verify against actual `LedgerEntry.__dataclass_fields__` order |
| Breaking tests that currently pass | Run full suite after each batch; commit incrementally |
| Time overrun on case-by-case | Set 90-min hard limit; escalate remaining failures to user decision |
| Introduced regressions | Run signal_writer_agent tests (already passing) as canary |

---

## Success Criteria

- ✅ **0 test failures** — Full suite passes
- ✅ All data integrity tests pass — SQL contracts verified
- ✅ No tests for deleted services remain
- ✅ Valuable logic tests migrated to correct services
- ✅ Full test suite runs in under 60 seconds
- ✅ Commit message documents each deletion/fix with rationale

---

## Open Questions

**Q1:** What if `test_feature_pipeline_service.py` tests functionality that moved to `IntelligencePipelineComputeAgent`?
**A1:** Migrate the test to `test_intelligence_compute_agent.py` and update imports.

**Q2:** What if script tests (`test_validate_alpha.py`) are actually integration tests?
**A2:** Move to `tests/integration/` directory and update to use real services instead of mocks.

**Q3:** Time budget overrun on case-by-case investigation?
**A3:** Document remaining failures in `docs/technical-debt/test-failures.md` and defer to next phase.

---

## Next Steps

1. Execute Steps 1-6 as documented
2. After each step, run partial test suite to verify improvement
3. Commit incrementally with descriptive messages
4. Final verification: Full suite passes
5. Transition to implementation phase (write detailed task breakdown)

---

**Spec complete.** Ready for implementation planning.
