---
status: partial
phase: 131-signal-generation-integrity
source: [131-VERIFICATION.md]
started: 2026-06-17T15:30:00Z
updated: 2026-06-17T15:30:00Z
---

## Current Test

[awaiting human testing]

## Tests

### 1. ctf_score gate confirmation
expected: ≥85% of non-null signal_events.ctf_score > 0.05 over a clean 1-week replay window (not including pre-fix rows)
result: [pending] — 87.3% confirmed for ts >= 2026-06-14, but 68.1% for ts > 2026-06-10 window; gate passes on recent rows but human should confirm scope

### 2. 35/35 plugin firing check (mandatory before Phase 133)
expected: SELECT setup_plugin, COUNT(*) FROM signal_events GROUP BY 1 shows exactly 35 distinct plugins (excluding trad_CrossAssetDivergence); zero other zero-emission plugins
result: [pending] — not run due to session quota exhaustion

### 3. Validation report append
expected: docs/plans/phase-127-validation-report.md has a Phase 131 section with ctf_score distribution, plugin firing counts, and explicit PASS/FAIL verdict
result: [pending] — section missing; append after plugin check completes

## Summary

total: 3
passed: 0
issues: 0
pending: 3
skipped: 0
blocked: 0

## Gaps
