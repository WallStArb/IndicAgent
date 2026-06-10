# Phase 121: Lifecycle Replay & Validation - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-06-10
**Phase:** 121-lifecycle-replay-validation
**Areas discussed:** Replay scope, Before/after comparison, Report format & structure

---

## Replay Scope

| Option | Description | Selected |
|--------|-------------|----------|
| lifecycle_replay.py only | Process 1.54M pending outcomes for existing signals. Faster, surgical. Before/after uses shadow vs. old-code metrics. | |
| Both: backfill first, then lifecycle replay | Complete 8-change backfill integrity plan, run historical_backfill.py --replay-only --clean, then lifecycle replay. Achieves literal signal count reduction. | ✓ |
| You decide | Apply first-principles reasoning | |

**User's choice:** Free-text — Renaissance-grade design. Jim Simons demands stopping noise at the source. The signal ledger must reflect corrected reality, not preserve historical noise.

**Notes:** User rejected tracking noise signals in favor of deleting and regenerating them with corrected code. User also clarified that both `lifecycle_replay.py` and `historical_backfill.py` need redesign due to new columns and schema changes from Phases 104-120. The redesign is real work, not a minor patch.

---

## Before/After Comparison

| Option | Description | Selected |
|--------|-------------|----------|
| Snapshot before deletes, compare after | Atomically capture metrics before any deletes. Store as baseline. Post-replay queries compare same metrics. | ✓ |
| RCA doc numbers are the baseline | 7.85M / 0.19% SNR numbers from RCA doc are authoritative. No new snapshot needed. | |

**User's choice:** "You decide"

**Claude's discretion applied:** Snapshot before deletes. RCA doc numbers are stale (16K shadow signals added since, live signals accumulating). Measuring is truth; trusting documentation is assumptions. Snapshot written atomically before any delete executes.

**Scope:** All 30 setups — user selected. The 8 GOOD setups act as control group (should be unchanged post-replay, validating methodology didn't regress them).

---

## Report Format & Structure

| Option | Description | Selected |
|--------|-------------|----------|
| Python script → markdown doc | production/scripts/phase_121_report.py → docs/plans/phase-121-validation-report.md | ✓ |
| Update RCA doc only | Add Part VIII to RCA doc with actual results | |
| Both: script + RCA update | Script for reproducibility + RCA for institutional record | ✓ |

**User's choice:** "You decide" (Renaissance framing)

**Claude's discretion applied:** Both. Script is reproducible machinery; RCA doc is the institutional record. SoC: keep concerns separate but both serve a purpose.

**Report metrics selected by user:** Calibration correlation per setup, stopped_at_entry count, SNR per cluster (all three).

---

## Claude's Discretion

- **Before-snapshot approach:** Snapshot before deletes (not relying on stale RCA doc numbers)
- **Baseline handling:** Atomic capture inside advisory lock transaction
- **Report delivery:** Both standalone script/doc AND RCA doc update
- **lifecycle_replay.py redesign scope:** Remove all hardcoded date windows; handle all new signal_outcomes columns from migrations 115-121

## Deferred Ideas

- 3-table schema migration (signal_events + trade_framing + trade_execution) — v2.10 Phases 123-125
- Extrinsic composite confidence layer — Phase 4.1 per RCA doc
- Per-symbol magnitude threshold tuning — Phase 117.5, probe data still accumulating
