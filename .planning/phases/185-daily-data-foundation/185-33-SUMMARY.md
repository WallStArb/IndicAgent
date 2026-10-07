---
phase: 185-daily-data-foundation
plan: 33
subsystem: data-integrity
tags: [d7, bar_integrity, verdicts, apr, vendor-basis]
requires: [185-28, 185-30, 185-31, 185-38]
provides:
  - "bar_integrity verdict rows (symbol|1d, one per check) written by D7 every run"
  - "judge_name_1d, month_digests, recompute_findings (pure, src/intelligence/bars/integrity_checks.py)"
  - "find_basis_runs, classify_run, blocking (src/intelligence/bars/vendor_basis.py)"
affects: [185-37, 185-40, 185-41]
key-files:
  created:
    - production/migrations/449_bar_integrity_verdict_apr.sql
    - src/intelligence/bars/vendor_basis.py
    - src/intelligence/bars/integrity_checks.py
    - tests/unit/bars/test_vendor_basis.py
    - tests/unit/bars/test_integrity_checks.py
    - tests/unit/test_bar_integrity_apr_migration_contract.py
  modified:
    - services/bar_reconciliation_audit.py
    - tests/unit/services/test_bar_reconciliation_audit.py
decisions:
  - "The per-name judge lives in src/intelligence/bars/integrity_checks.py (pure), not in D7, so D7 only loads inputs and the Ring rule holds (src never imports services)"
  - "lineage_missing reads the canonical_bar_lineage view in one set-based pass (measured 37 s)"
  - "refused_head_1d is a ninth, informational bar_integrity row per name (passed true); untraced_quarantined_1d stays a bar_reconciliation fact marked informational"
  - "Verdict rows are read back after the write and a short write raises, because the integrity_monitor writer swallows insert errors into a warning"
metrics:
  completed: 2026-10-07
---

# Phase 185 Plan 33: 1d verdict report Summary

D7 now writes, for every compute_1d name (1,502), eight 1d verdict rows (`monitor_type bar_integrity`, subject `SYM|1d`) plus an informational `refused_head_1d` row, every run. The three zero-tolerance corpus checks and policy_conformance all pass on the re-derived corpus.

## Commits

- 12ae5a9ab: migration 449 (applied live), vendor_basis, integrity_checks arithmetic, tests (earlier session)
- a51df6fb3: D7 verdict report, per-name judge, loaders by import of bar_derivation's SQL, read-back guard, ibkr_fallback allowed source

## Tests

- Task 1 files (vendor_basis, integrity_checks, migration contract): 30 passed at resume.
- tests/unit/bars, test_bar_reconciliation_audit, migration contract, migration number uniqueness: green.
- Full `tests/unit/ -q`: green (5 pre-existing skips). ruff and black clean. Unit tests for the report use a fake connection (todo 494); none touches live D1.

## Live run (2026-10-07 12:38 UTC, by hand, outside the 06:00 window)

Run time 4 min 37 s (user 3 min 12 s) against the 54 s baseline; the unit has no TimeoutStartSec (oneshot default, no timeout), so no unit change. Run directly as `.venv/bin/python services/bar_reconciliation_audit.py`; exit 0. 13,518 rows written (1,502 x 9), all read back.

| check | pass | fail | seconds |
|---|---|---|---|
| session_coverage | 1262 | 240 | 1.8 |
| policy_conformance | 1502 | 0 | 32.7 |
| lineage_missing | 1502 | 0 | 37 s set-based read (measured by hand, not in the loop) |
| canonical_recompute | 1502 | 0 | 60.3 |
| digest_fresh | 1502 | 0 | 18.6 |
| unexplained_seam | 1494 | 8 | 0.0 |
| vendor_basis_run | 1456 | 46 | 21.7 |
| report_age | 1502 | 0 | 0.0 |

Zero-tolerance acceptance (lineage_missing, canonical_recompute, digest_fresh, policy_conformance): 0 failures.

lineage_missing used the view (set-based pass over `canonical_bar_lineage` left-joined to the tradeable view); the full read took 37.4 s, under the plan's 10 minute line. It returned 0 NULL-lineage rows, visible or hidden, so untraced_quarantined_1d is 0.

## Findings

- session_coverage, 240 names fail 0.999: 173 sit between 0.90 and 1.0 (small holes), 25 are under 0.10 (the lowest: FLUT 0.0015, TGTX 0.0015, EU 0.0020, VSEC 0.0020, LEA 0.0021, CC 0.0028, LGND 0.0075, CFR 0.0100). Reported, not adjusted. Not yet separated into dead-name tails versus real interior holes.
- unexplained_seam, 8 names with one finding each: AVBP, EWZ, LQDA, MTG, PAGS, PCVX, PTC, XP.
- vendor_basis_run, 46 names block: in 44 the continuous vendor is IBKR and the canonical (Tradier) side steps (for example ABT, BAX, CHD, COP, EBAY 2006-10-06..2011-05-20; EWJ and its country ETF peers 2006..2016-11-04; DOV 2006..2018-05-08), in KDP and PATK the continuous vendor is Tradier while the stored bars of those dates are IBKR (ibkr_named, among the IBKR-primary exception rows), so the canonical side is the stepping one there. These are 185-37's input. The list is in `logs/bar_reconciliation_audit.log` under `bar_integrity.blocking_basis_runs`.
- refused_head_1d: 1 name carries refused head dates, 276 dates in total (informational; the history of that name starts at its first primary bar).

## ibkr_fallback and stray_sources

D7's `ALLOWED_SOURCES["1d"]` lacked `ibkr_fallback`. The corpus holds 128,777 such rows, 4 of them inside the 5-session stray window, so the 1d count was small but nonzero before the fix; added as a Rule 1 fix (test included). After the fix the live stray list has no 1d entry. The remaining 16,917 stray findings are vendor `15m:ibkr_named` (294 names) and `1h:ibkr_named` (295 names) rows: 185-40's `stray_vendor_rows` and the 189 cleanup, not this plan.

## Deviations from plan

- [Rule 1 - Bug] ALLOWED_SOURCES["1d"] gained ibkr_fallback (above). Commit a51df6fb3.
- The judge is in integrity_checks.py instead of D7 (layering; listed in decisions). `files_modified` did not list a D7-side judge, so nothing else moves.
- `refused_head_1d` is a ninth informational row rather than a log-only count, so the per-name count is visible in the report as the plan requires.
- The plan's Task 3 file `indicagent-bar-reconciliation-audit.service` is unchanged: no TimeoutStartSec exists, so there is nothing to raise.
- check_d2_landed and the 186 note (orchestrator brief) are 185-41's per the amended plan; not done here. `mixed_source_names` is dropped by the plan.
- The 185-33 plan's `must_haves` asks for report_age as "newest verdict newer than the latest ohlcv_load"; implemented as passed when the latest 1d load is not after the run start, metric = hours since that load, threshold = report_max_age_hours. The gates (185-41) re-evaluate age against now.

## Known stubs

None.

## Self-Check

Files exist: migration 449, vendor_basis.py, integrity_checks.py, the three Task 1 tests, the extended D7 test file. Commits 12ae5a9ab and a51df6fb3 are in `git log`. Migration 449 keys are in config_schema. 13,518 verdict rows are in integrity_monitor.

Self-Check: PASSED
