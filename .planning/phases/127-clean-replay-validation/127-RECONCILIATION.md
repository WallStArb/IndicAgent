---
phase: 127-clean-replay-validation
created: 2026-06-17
status: authoritative
purpose: Reconcile GSD Plans 01/02/03 against the parallel manual rebuild (the actual corpus producer). Supersedes stale claims in 127-01-SUMMARY.md.
---

# Phase 127 Plan Reconciliation vs. the Parallel Rebuild

## Context

GSD execute-phase 127 (wave 0) ran **concurrently** with a parallel manual clean-slate
rebuild launched the same session. They collided. Only Plan 00 (read-path 3-table
migration) produced durable, non-conflicting value. This document records how Plans
01, 02, and 03 relate to the rebuild corpus and what work actually remains.

**Source of truth for the corpus:** the rebuild's `lifecycle_replay`
(`--workers 8`, no warmup), NOT the GSD-launched `--warmup --workers 1` replay.

## The discredited premise

Plan 01 Task 2 (and its `critical_corrections` #5) were authored on the belief that
`run_historical_pipeline.py --warmup` performs real cold-start correction via a
two-pass I1-I6 cache build. **This is disproven.**

Proof (recorded in memory `warmup-noop-finding` and rebuild finding #3):
`plugin_states` and `intelligence_cache` are local variables inside `replay_symbol()`,
re-initialized on every call. Pass 1's caches die before Pass 2 begins, so the second
pass gets zero cold-start benefit. Cold-start is already handled by the chronological
lower-TF-first event merge + the `min_bars_for_tf()` guard. The warmup flag just
writes features twice and forces `--workers 1` (2x compute, no correctness gain).

Consequence: Plan 01's acceptance gate "warmup markers found in log" would have
**certified success for a no-op.** The GSD-launched replay (PID 1398422) is dead and
must not be re-run.

## Plan-by-plan verdict

### Plan 01 (REPLAY-02: baseline + clean replay) — PARTIALLY DONE, Task 2 SUPERSEDED

| Task | Verdict | Action |
|------|---------|--------|
| Task 1: `phase_127_before_snapshot.py` script | DURABLE | Retain the script as a reusable 3-table integrity/coverage probe. |
| Task 1: pre-rebuild `phase-127-before-snapshot.json` baseline | STALE | The before/after-delta framing is moot: the corpus was wiped and rebuilt in one operation, so there is no clean "before" to pair against retroactively. Retire the delta goal. |
| Task 2: `--warmup --workers 1` replay | SUPERSEDED + DISCREDITED | Do NOT re-run. The rebuild (`--workers 8`, no warmup) is the clean replay. |

**Note:** the original `127-01-SUMMARY.md` asserts Task 2 succeeded (warmup markers
found, "no deviation from plan"). That claim is corrected by the
`## Correction (2026-06-17)` block appended to that file.

### Plan 02 (validation report) — NOT SUPERSEDED; FOLDS IN THE REBUILD CHECKLIST

Plan 02 is the formal RCA report that *consumes* the rebuild corpus. It is
methodologically sound: it explicitly refuses to fake signal-quality measures on a
no-outcome corpus (`counterfactual_pnl_r` is NULL by design; CounterfactualTracker is
v2.11). Its integrity/coverage queries are exactly the rebuild validation checklist's
section 5 (`.planning/todos/pending/2026-06-16-replay-issues-and-findings.md`).

**Action:** Gate Plan 02 on rebuild completion. Run the checklist's section-5 queries
as Plan 02's data-gathering step, then write the formal report + RCA Part VI update.
The rebuild IS Plan 01's clean replay; Plan 02 is the report on its output.

### Plan 03 (calibration-retrain v2.11 blocker log) — INDEPENDENT, VALID

Doc-only. Confirms no populated PnL outcome in the Phase 127 corpus and records the
v2.11 dependency. No dependency on the rebuild's runtime state. **Proceed anytime.**

## Remaining work (ordered)

1. **(blocking) Let rebuild `lifecycle_replay` (PID 1736187) finish** — `trade_executions`
   climbing toward ~1,036,513; `signal_events`/`trade_frames` already at 1,036,513 with
   0 orphans. ETA ~13 min at ~271 rows/sec (measured 2026-06-17 04:43 UTC).
2. **Run rebuild validation checklist section 5** (= Plan 02 data gathering) once complete.
3. **Write Plan 02 validation report** consuming those results.
4. **Plan 03** calibration blocker log (independent — can run in parallel with 2/3).
5. **Restore services** only after validation passes (remove `Restart=no` drop-ins,
   daemon-reload, reset-failed, start writers + auditor + self-healing).
6. **Cleanup:** orphan worktree `agent-a88695d6c7efc3f22` + branch; obsolete scripts
   per rebuild finding #4.

## Process lesson

A confidently-authored plan (with line-number citations and an explicit
critical_correction) defended a flag that turned out to be a no-op, and its acceptance
gate would have certified the no-op as success. Empirical/mechanistic verification (the
rebuild's proof that caches are call-local) overrode the plan. Lesson: when a plan's
correctness hinges on a runtime behavior it claims but does not demonstrate, verify the
behavior before trusting gates built on it.
