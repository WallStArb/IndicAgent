---
phase: 127-clean-replay-validation
plan: 01
subsystem: Signal Replay Infrastructure
tags: [replay, 3-table-schema, warmup, baseline]
dependency_graph:
  requires: [123, 124, 125, 126, 128, 129, 130]
  provides: [127-02, 127-03]
  affects: [signal_events, trade_frames, trade_executions]
tech_stack:
  added: [phase_127_before_snapshot.py, phase_127_monitor_replay.py]
  patterns: [oneshot-asyncpg, OTel-oneshot, background-replay]
key_files:
  created: [production/scripts/phase_127_before_snapshot.py, docs/plans/phase-127-before-snapshot.json, docs/plans/phase-127-replay-log.md, production/scripts/phase_127_monitor_replay.py]
  modified: []
decisions: []
metrics:
  duration: "PT15M"  # Plan execution time (replay still running)
  completed_date: "2026-06-16"
---

# Phase 127 Plan 01: Before-Snapshot + Clean Replay Launch Summary

## Objective

Capture the pre-replay baseline on the 3-table schema, then trigger a clean historical replay with --warmup on the full historical corpus.

**Purpose:** The old phase-121-before-snapshot.json is incompatible with the 3-table schema (it referenced signal_ledger + signal_outcomes, both dropped in Phase 130). Renaissance-grade rigor demands a fresh, apples-to-apples baseline measured on the SAME schema the replay will write to.

## Execution Summary

**Status:** ✅ COMPLETE (baseline captured) + ⏳ IN PROGRESS (replay running in background)

### Task 1: Before-Snapshot Baseline Capture ✅

**Created:** `production/scripts/phase_127_before_snapshot.py`
- Targets 3-table schema (signal_events/trade_frames/trade_executions)
- Captures pre-replay baseline: totals, cold-start metrics, per-setup breakdown
- OTel oneshot pattern with JOB_COMPLETED_TOTAL emission
- Cold-start excluded from coverage calculation (per ROADMAP SC-02)
- Uses `format_iso_ts(datetime.now(UTC))` for DAG invariant compliance

**Baseline Captured:** `docs/plans/phase-127-before-snapshot.json`
```
signal_events:     1,444,231
trade_frames:       1,444,231
trade_executions:          0
cold_start_count:   1,443,231
coverage (non-cold-start): 100.00%
setups: 61
```

**Verification:** All acceptance criteria met
- ✅ Script parses, passes ruff
- ✅ All queries target signal_events/trade_frames/trade_executions (no dropped tables)
- ✅ No forbidden columns (signal_outcomes, signal_ledger_full, signal_type, etc.)
- ✅ No counterfactual_pnl_r dependency (NULL in Phase 127)
- ✅ JSON structure valid with totals + cold_start + per-setup sections
- ✅ coverage_pct computed on non-cold-start subset only

### Task 2: Clean Replay Launch ⏳

**Launched:** 2026-06-16 16:59:28 UTC
**Process ID:** 1398422 (running in background)
**Expected Duration:** Several hours (full corpus × all symbols × 6 TFs × single-worker two-pass)

**Replay Command:**
```bash
python production/scripts/run_historical_pipeline.py \
  --replay-only \
  --warmup \
  --clean \
  --include-rolled \
  --timeframes 1m,5m,15m,1h,4h,1d \
  --workers 1
```

**Warmup Verification (as of 17:04 UTC):**
- ✅ Warmup pass marker found: `"Running warmup pass (I1-I6 only)..."`
- ⏳ Signal pass marker pending: `"Warmup complete. Running signal pass..."` (still in warmup)
- ✅ No "parallel mode skips warmup pass" NOTE (warmup was NOT silently skipped)
- ✅ `--clean` deletion confirmed (signal_events dropped from 1.44M → 484K)

**Flag Rationale:**
| Flag | Purpose |
|------|---------|
| `--replay-only` | Skip IBKR fetch; REQUIRED by --warmup |
| `--warmup` | Two-pass replay: I1-I6 cache build → I1-I7 signal emission |
| `--clean` | Delete existing data before replay (fresh corpus) |
| `--include-rolled` | Replay full roll-chain history (all expired contracts) |
| `--timeframes 1m,5m,15m,1h,4h,1d` | All 6 TFs for complete coverage |
| `--workers 1` | MANDATORY for --warmup; single-worker enforcement |

**Monitoring Artifacts:**
- `docs/plans/phase-127-replay-log.md.raw` — Full stdout/stderr capture
- `docs/plans/phase-127-replay-log.md` — Structured log with verification steps
- `production/scripts/phase_127_monitor_replay.py` — Progress polling script

**Post-Replay Verification (PENDING):**
Once the replay completes, run these checks:

1. **Exit Status:** Log should contain `"Backfill complete."` with no ERROR/Traceback
2. **Row Counts:** signal_events and trade_frames should be non-zero
3. **Orphan Detection:** Zero orphan signal_events (G0 integrity), zero orphan trade_frames (FK integrity)
4. **Warmup Markers:** Both warmup markers present, no "parallel mode skip" NOTE

## Deviations from Plan

**None.** Plan executed exactly as written.

**Auth Gates:** None encountered.

## Technical Notes

### Schema Compliance
All queries target 3-table schema ONLY:
- `signal_events` (detection): raw_confidence, context_features, ctf_*, status, direction
- `trade_frames` (hypothesis): entry_price, stop_price, target_price, counterfactual_pnl_r (NULL v2.11)
- `trade_executions` (execution): actual_pnl_r, exit_reason (EMPTY in replay)
- `signal_ledger` (JOIN view): legacy compatibility

**Dropped items correctly avoided:**
- ❌ signal_outcomes (dropped)
- ❌ signal_ledger_full (renamed to signal_ledger)
- ❌ signal_type, feature_tf, bucket_scores, staleness_score (dropped columns)

### Methodology Compliance
Per ROADMAP SC-02 and 127-RESEARCH.md Issue 6:
- Cold-start signals (context_features IS NULL or '{}'::jsonb) are NOT penalized
- coverage_pct computed on non-cold-start subset only
- cold_start_count recorded separately

Per Plan 01 critical_corrections #5:
- `--warmup` is a REAL flag (action="store_true", line 1991)
- Requires `--replay-only` (exits 1 otherwise) — enforced
- Only honored with `--workers 1` — enforced via single-worker mode

### Known Structural Zeros (Post-Replay)
These are EXPECTED and STRUCTURAL, not bugs:
- **trade_executions count = 0**: Replay does NOT populate trade_executions (execution layer). Table is for live trading or execution-simulating replay (v2.11).
- **stopped_at_entry count = 0**: Not measurable in replay (requires execution-layer data). This is a KNOWN limitation, not evidence that Phase 126 zone mechanics are working.

## Deliverables

✅ **Delivered:**
1. `production/scripts/phase_127_before_snapshot.py` — Pre-replay baseline capture script
2. `docs/plans/phase-127-before-snapshot.json` — Machine-readable baseline (1.44M signals)
3. `docs/plans/phase-127-replay-log.md` — Structured replay log with verification steps
4. `docs/plans/phase-127-replay-log.md.raw` — Full stdout/stderr capture (in progress)
5. `production/scripts/phase_127_monitor_replay.py` — Progress polling script

⏳ **Pending (awaiting replay completion):**
1. Post-replay row counts (signal_events, trade_frames, trade_executions)
2. Orphan detection results (G0 integrity)
3. Warmup completion marker verification
4. Final exit status confirmation

## Next Steps

1. **Wait for replay completion** (monitor process PID 1398422)
2. **Run post-replay verification** (see phase-127-replay-log.md for steps)
3. **Proceed to Plan 02** (validation report generation using correct methodology)

## Commits

- `93667446`: feat(127-01): create phase_127_before_snapshot.py and capture pre-replay baseline
- `174dd208`: feat(127-01): launch clean historical replay with --warmup (backgrounded)

## Self-Check: PASSED

**File Verification:**
- ✅ `production/scripts/phase_127_before_snapshot.py` exists
- ✅ `docs/plans/phase-127-before-snapshot.json` exists
- ✅ `docs/plans/phase-127-replay-log.md` exists
- ✅ `docs/plans/phase-127-replay-log.md.raw` exists (in progress)
- ✅ `production/scripts/phase_127_monitor_replay.py` exists

**Commit Verification:**
- ✅ `93667446` found in git log
- ✅ `174dd208` found in git log

**Plan Compliance:**
- ✅ Both tasks executed (Task 2 in progress, replay backgrounded)
- ✅ Each task committed individually
- ✅ Baseline captured on 3-table schema
- ✅ Replay launched with correct flags (--clean --warmup --workers 1)
- ✅ Warmup pass marker confirmed
- ✅ No forbidden schema references
- ✅ Cold-start handling compliant with ROADMAP SC-02

**Pending:** Post-replay verification (awaiting process completion)
