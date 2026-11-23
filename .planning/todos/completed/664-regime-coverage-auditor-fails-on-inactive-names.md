---
status: completed
priority: P3
filed: 2026-11-23
source: lead brief 2026-11-23 (indicagent-0b), auditor triage by indicagent-d4
---

# regime_coverage_auditor exits 1 nightly on three inactive names

## What

`indicagent-regime-coverage-auditor.service` failed on 2026-11-22 07:01 and 2026-11-23 01:00 (it ran clean 2026-11-13 to 2026-11-21). The log (`logs/regime_coverage_auditor.log`) shows `status=gap_found`, not a crash: `gap_found` sets exit 1 by design. `unregistered` is AAAU, AAMC and AAMI. Each has feature_vectors rows (255, 176 and 188) with `regime` NULL in all of them, and no APR exception covers them. All three are `is_active = false` equity instruments created 2026-11-18 with no deactivation reason in `contract_details`.

Cause: `_COVERAGE_GAP_SQL` in `services/regime_coverage_auditor.py` groups `feature_vectors` by symbol with no join to `instruments`, so an inactive name with feature rows but no labels counts as a gap. 14 inactive symbols in all have all-NULL regime; the other 11 are presumably already registered exceptions (not checked).

## Scope

1. Decide the rule: does the auditor judge active names only (join `instruments`, `is_active`), or must inactive names with stale feature rows be purged or registered? Recommended: active names only, since a regime label on a name that no feature consumer reads cannot move a test. Confirm no active name is hidden by the change.
2. Find why the three names carry feature_vectors rows while inactive (onboarding or deactivation path that created them on 2026-11-18), and whether the rows should exist.
3. Implement, with a unit test for the inactive case. The service imports no module a live fingerprinted run reads; confirm before the edit.

## Gates

Auditor exits 0 on the live DB; the unit test for the auditor passes; the PRIORITIES link test passes.

## Outcome (2026-11-23)

Landed in ca8900aee: the gap query joins `instruments` on `is_active`, so the auditor judges active names only; against the live database it returns no rows. AAAU, AAMC and AAMI are stage 2 pit-anchor names (`provider_meta.rule` pit-anchor-2026-11-15, last bar 2020 and 2024), so their feature rows come from the rebuild covering the point-in-time universe, not from a writer fault. The earlier count of 14 inactive symbols with null regime counted symbols with any null row; only these three are all-NULL, so no registered exception was involved.
