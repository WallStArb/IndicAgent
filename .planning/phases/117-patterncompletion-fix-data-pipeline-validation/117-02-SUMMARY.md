---
phase: 117-patterncompletion-fix-data-pipeline-validation
plan: "02"
subsystem: observability
tags: [otel, systemd, asyncpg, timescaledb, pattern-detection, jsonb, oneshot]

requires:
  - phase: 117-01
    provides: Write-path fix ensuring I5 pattern fields land in pattern_detections JSONB column

provides:
  - FeatureParityAuditor oneshot service with 5-minute systemd timer
  - FEATURE_PARITY_NULL_FIELDS_TOTAL point_gauge and FEATURE_PARITY_AUDITS_RUN_TOTAL counter in metrics.py
  - Regression guard catching 100% NULL pattern fields within one 5-minute cycle
  - service_auditor _DAG_ORDER registration for indicagent-feature-parity-auditor

affects:
  - 117-03
  - observability
  - service_auditor

tech-stack:
  added: []
  patterns:
    - "Oneshot validation service mirrors shadow_auditor.py structure: _run_audit returns testable list, main() wraps with JOB_COMPLETED_TOTAL + flush_and_shutdown_metrics"
    - "asyncpg JSONB key-existence query: COUNT(*) FILTER (WHERE col ? $1) for presence-without-decode"

key-files:
  created:
    - services/feature_parity_auditor.py
    - production/systemd/indicagent-feature-parity-auditor.service
    - production/systemd/indicagent-feature-parity-auditor.timer
    - tests/unit/services/test_feature_parity_auditor.py
  modified:
    - src/observability/metrics.py
    - services/service_auditor.py

key-decisions:
  - "OTel instruments placed under canonical _meter (indicagent.metrics) via point_gauge() helper — no inline get_meter() call in the service file"
  - "_run_audit() returns violations list for direct testability without patching OTel internals"
  - "_EXPECTED_FIELDS defined as module-level constant (not local var) for clarity and reuse"
  - "5-minute timer interval — fast enough to catch regression within one on-call rotation window"

patterns-established:
  - "Audit oneshots use pool.acquire() context manager, not a conn passed in, for testability"

requirements-completed:
  - VAL-02

duration: 4min
completed: "2026-06-09"
---

# Phase 117 Plan 02: FeatureParityAuditor — Regression Guard Summary

**5-minute timer-triggered oneshot auditing JSONB key presence for dt_db_confidence/hs_confidence/tri_confidence in intelligence_features, with OTel gauge on violation**

## Performance

- **Duration:** 4 min
- **Started:** 2026-06-09T00:20:09Z
- **Completed:** 2026-06-09T00:24:15Z
- **Tasks:** 3
- **Files modified:** 6

## Accomplishments

- Added `FEATURE_PARITY_NULL_FIELDS_TOTAL` (point_gauge) and `FEATURE_PARITY_AUDITS_RUN_TOTAL` (counter) to metrics.py under the canonical `indicagent.metrics` meter
- Created `services/feature_parity_auditor.py`: queries `intelligence_features` for the last hour, checks `pattern_detections ? $1` key existence for each expected field, sets gauge to violation count, emits `job_completed_total{job=feature-parity-auditor}`
- Created systemd `.service` + `.timer` pair (OnCalendar=*:0/5) and registered bare service name in `_DAG_ORDER` at priority 8, matching shadow-auditor convention
- 4 unit tests covering violation path, clean path, no-rows early-return, and all-fields-missing

## Task Commits

1. **Task 1: OTel instruments + FeatureParityAuditor service** - `eeea2037` (feat)
2. **Task 2: systemd .service + .timer + _DAG_ORDER entry** - `7fd17f3b` (feat)
3. **Task 3: Unit tests for audit logic** - `38469c0c` (test)

## Files Created/Modified

- `src/observability/metrics.py` - Added FEATURE_PARITY_NULL_FIELDS_TOTAL and FEATURE_PARITY_AUDITS_RUN_TOTAL under shadow-auditor block
- `services/feature_parity_auditor.py` - Oneshot service mirroring shadow_auditor.py structure
- `production/systemd/indicagent-feature-parity-auditor.service` - Type=oneshot, ExecStart targeting .venv python
- `production/systemd/indicagent-feature-parity-auditor.timer` - OnCalendar=*:0/5, Persistent=true
- `services/service_auditor.py` - Bare name "indicagent-feature-parity-auditor" at priority 8 in _DAG_ORDER
- `tests/unit/services/test_feature_parity_auditor.py` - 4 async tests with @pytest.mark.asyncio

## Decisions Made

- OTel instruments placed under canonical `_meter` via `point_gauge()` helper — not an inline `get_meter()` call in the service (consistent with all other instruments in metrics.py).
- `_run_audit()` returns the violations list so tests assert behavior directly, without patching OTel internals.
- `_EXPECTED_FIELDS` as a module-level constant rather than a local variable inside `_run_audit`, enabling future extension without refactoring the function signature.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing Critical] Added @pytest.mark.asyncio to all test functions**
- **Found during:** Task 3 (unit tests)
- **Issue:** pytest-asyncio 1.4.0 in STRICT mode (the default in this worktree) requires explicit `@pytest.mark.asyncio` on async test functions — the `--asyncio-mode=auto` addopts from pytest.ini was not being picked up in STRICT mode
- **Fix:** Added `@pytest.mark.asyncio` decorator to all 4 async test functions
- **Files modified:** tests/unit/services/test_feature_parity_auditor.py
- **Verification:** All 4 tests pass with `pytest tests/unit/services/test_feature_parity_auditor.py -v`
- **Committed in:** 38469c0c (Task 3 commit)

---

**Total deviations:** 1 auto-fixed (1 missing critical)
**Impact on plan:** Required for tests to run; no scope change.

## Issues Encountered

- Worktree lacked `.venv` symlink; pre-commit hook searches `$REPO_ROOT/.venv/bin/ruff` where REPO_ROOT is the worktree dir. Created symlink `/worktree-dir/.venv -> /home/bg/dev/indicagent/.venv` to allow hook to find linting tools.

## Next Phase Readiness

- VAL-02 satisfied: FeatureParityAuditor is built and tested; systemd pair created
- Operator install step required: `sudo systemctl enable --now indicagent-feature-parity-auditor.timer`
- 117-03 can proceed independently

---
*Phase: 117-patterncompletion-fix-data-pipeline-validation*
*Completed: 2026-06-09*
