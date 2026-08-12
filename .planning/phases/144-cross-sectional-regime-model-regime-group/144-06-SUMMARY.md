---
phase: 144-cross-sectional-regime-model-regime-group
plan: 06
subsystem: intelligence
tags: [ic-engine, regime-group, acceptance-gate, hmm, rates, feature-ic-scores]

# Dependency graph
requires:
  - phase: 144-05
    provides: services/ic_engine.py regime_group routing (AmbiguousRegimeGroupError, _build_symbol_regime_class, symbol_list cross-sectional peer-scoping fix) -- the code that must actually run against a rebuilt corpus before this plan's measurement can execute
provides:
  - "scripts/analysis/phase144_regime_separation_gate.py: TLT per-symbol HMM vs rates cross-sectional IC separation gate, freshly written (RESEARCH.md Open Question 3 had no pre-registered SQL), STEP 0 precondition check + STEP 1-3 measurement/classification/F1-F2 verdict logic, all code-complete and verified against the live BLOCKED path"
  - "Live confirmation (2026-07-12) that the D-05 acceptance gate is correctly BLOCKED-ON-143.1-07: zero feature_ic_scores rows carry any rates cross-sectional label, corpus max(computed_at) is still 2026-07-09 (stale), and the in-flight rebuild (PID 3152282) is 44/80 symbols through its run"
affects: [143.1-08, phase-144-final-acceptance]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Freshness-marker precondition pattern: instead of gating on a hardcoded row count or date (D-08 explicitly forbids this), the script checks for the EXISTENCE of a label vocabulary that can only have been written by the code under test -- rates cross-sectional labels (steep_tight/steep_wide/flat_tight/flat_wide/inverted_tight/inverted_wide) cannot exist in feature_ic_scores until Phase 144's regime_group routing has actually executed against a rebuilt corpus. Zero matching rows is unambiguous proof the corpus predates the fix or the rebuild's corpus-wide BH-FDR write hasn't landed yet."
    - "Spread/range separation metric (max(mean_ic) - min(mean_ic) across a side's regime labels) reused from todo 026 Step 2(c)'s own terminology, applied uniformly to both the 5-label per-symbol HMM trend vocabulary and the 6-label rates cross-sectional tier vocabulary; a separate signed trending_up-minus-trending_down metric is computed only for the per-symbol HMM side (the only side with a natural bullish/bearish label pairing), matching the exact metric todo 026 originally reported."

key-files:
  created:
    - scripts/analysis/phase144_regime_separation_gate.py
  modified: []

key-decisions:
  - "STEP 0 precondition check gates on label-vocabulary existence (rates cross-sectional tier labels), not a hardcoded row count or date, per D-08's explicit requirement. Verified against live data: this correctly returns BLOCKED as of 2026-07-12T20:00Z."
  - "STEP 1-3 (measurement, band classification, F1/F2 falsifier verdict) were coded and unit-verified against the failure path (BLOCKED-ON-143.1-07 output confirmed correct) but were NOT run to completion, since the corpus rebuild they depend on is still in flight -- running them now would violate D-07's single-writer discipline and would produce numbers computed against a stale/partial corpus, exactly what this gate exists to prevent."
  - "Did not kill, signal, or otherwise interfere with the external 143.1-07 process (PID 3152282 and forkserver children) -- confirmed still running after this plan's work, untouched, per the plan's explicit instruction that this is unrelated in-flight work belonging to a separate workstream (todo 102)."
  - "Separation metric design (spread = max-min across regime labels, matching todo 026's own 'range' terminology) and the signed trending_up/trending_down gap for the per-symbol side only (curve_credit's steep/flat/inverted x wide/tight vocabulary has no natural directional pairing) -- both documented inline in the script's module docstring since RESEARCH.md Open Question 3 explicitly left the SQL/metric design as this task's own deliverable."

patterns-established:
  - "Label-vocabulary-existence as a freshness marker: a strong, non-hardcoded precondition check for 'has code path X actually run against this data' -- reusable any time a schema-compatible-but-behaviorally-new value can only be written by the code under test."

requirements-completed: []

# Metrics
duration: ~55min
completed: 2026-07-12
---

# Phase 144 Plan 06: D-05 Acceptance Gate (TLT vs rates regime separation) Summary

**Wrote the freshly-designed `scripts/analysis/phase144_regime_separation_gate.py` (D-05's acceptance-gate measurement, no pre-registered SQL existed per RESEARCH.md Open Question 3) and confirmed via a live query and process check that Phase 144's own final verification step is correctly BLOCKED-ON-143.1-07 as of 2026-07-12T20:00Z -- the corpus rebuild the gate depends on is still mid-run (44/80 symbols, zero corpus-level BH-FDR rows written yet).**

## Performance

- **Duration:** ~55 min
- **Started:** 2026-07-12T19:11:00Z (approx, after worktree reset to base commit 0ff17bb8)
- **Completed:** 2026-07-12T20:07:00Z
- **Tasks:** 1/1 completed
- **Files modified:** 1 (created)

## Accomplishments
- `scripts/analysis/phase144_regime_separation_gate.py` written end-to-end: STEP 0 precondition check, STEP 1 measurement queries (per-symbol HMM side and rates cross-sectional side), STEP 2 spread/gap computation and 0.01/0.05 band classification, STEP 3 F1/F2 falsifier verdict rendering -- all code-complete, `ast.parse`-valid, ruff/black clean.
- Live-verified the precondition check correctly identifies the current corpus as stale: zero `feature_ic_scores` rows carry any of the 6 rates cross-sectional tier labels (`steep_tight`, `steep_wide`, `flat_tight`, `flat_wide`, `inverted_tight`, `inverted_wide`) that only Phase 144's regime_group routing code can produce; `max(computed_at)` across all 920,649 rows is still `2026-07-09 10:45:27+00`, three days stale relative to today.
- Live-verified the in-flight `143.1-07` corpus rebuild (`services/ic_engine.py --training-window-end 2025-12-24 05:15:00+00 --workers 4`, PID 3152282) is still actively running: 44/80 symbols logged as `symbol_computed` as of 2026-07-12T19:52-19:58Z, process CPU time ~7h14m and climbing, forkserver children still at ~99% CPU. Per `pool.map`'s submission-order + corpus-wide-BH-FDR-write design (documented in todo 102), zero rows will land in `feature_ic_scores` until all 80 symbols finish -- consistent with the observed state.
- Ran the script against live data: it correctly printed `BLOCKED-ON-143.1-07` with the freshness evidence and exited 1, confirming the precondition-check code path works as designed.
- Confirmed the external rebuild process was left completely untouched throughout this plan's execution (`ps -p 3152282` before and after showed the same PID, steadily increasing elapsed time).

## Task Commits

Each task was committed atomically:

1. **Task 1: Verify corpus freshness + run dispatcher/ic_engine + separation gate measurement** - `966a03fc` (feat)
   - STEP 0 ran and correctly returned BLOCKED. Per the task's own `<action>` (and the plan-dispatch's `<critical_precondition_note>`), STEP 1-3's dispatcher full-run / ic_engine re-run / measurement execution were NOT run, since STEP 0 failed. The deliverable script itself (containing STEP 1-3's logic, verified correct against the failure path) was written and committed as required.

## Files Created/Modified
- `scripts/analysis/phase144_regime_separation_gate.py` - D-05 acceptance-gate script: precondition check, mean-IC-by-regime queries for both sides of the comparison, spread/band classification, F1/F2 verdict renderer

## Decisions Made

**Precondition check design (D-08 compliance):** rather than gating on a hardcoded row count or `computed_at` cutoff date, the script checks for the *existence* of any `feature_ic_scores` row carrying one of curve_credit.py's 6 rates cross-sectional tier labels (`steep_tight`/`steep_wide`/`flat_tight`/`flat_wide`/`inverted_tight`/`inverted_wide`). This label vocabulary literally cannot exist in the table until Phase 144's `regime_group` routing (Plan 05) has executed against a rebuilt corpus -- it is schema-compatible with pre-144 rows (same `regime_scope='cross_sectional'`, same `feature_ic_scores.regime` text column) but behaviorally impossible to produce under the old equity-only routing. Zero matching rows is therefore unambiguous, self-updating proof of staleness without any date/count to keep in sync.

**Separation metric design (RESEARCH.md Open Question 3 -- no pre-registered SQL existed):** used "spread" = `max(mean_ic) - min(mean_ic)` across a side's regime labels per timeframe, matching todo 026 Step 2(c)'s own "range" terminology ("cross-sectional range (0.0457) vs per-symbol HMM range (0.0327)"), classified against todo 026's existing 0.01/0.05 bands. For the per-symbol HMM side specifically, an additional *signed* gap (`mean_ic(trending_up) - mean_ic(trending_down)`) is computed, since that vocabulary (from `regime_writer.py`'s `_build_label_map`) has a natural bullish/bearish pairing and this is the exact metric todo 026 originally reported (SPY +0.024 "correct sign", TLT -0.003 "inverted"). The rates cross-sectional vocabulary (`steep`/`flat`/`inverted` x `wide`/`tight`) has no equivalent natural up/down pairing, so only the unsigned spread is computed for that side; sign coherence there is left as a qualitative read of the script's printed per-label breakdown table rather than a forced boolean.

**F1/F2 verdict logic:** implemented per the Fable decision doc's §4 decision tree -- F1 (TLT per-symbol HMM signed gap >= 0.01 with correct/positive sign) checked first; if it does not trigger on any timeframe, the script falls through to F2 (rates cross-sectional spread also < 0.01 on the deficient band), which is the pre-registered build trigger for the factor-augmented HMM challenger (option c), pending a `volatility_pct` substitution-gate check this script does not itself perform.

**No writes attempted; external process left untouched.** Per the plan's explicit STEP 0 abort instruction and the dispatch prompt's `<critical_precondition_note>`, no dispatcher full-run or batched `ic_engine` re-run was executed, and the in-flight `143.1-07` PID (3152282 and forkserver children) was never signaled, killed, or otherwise interfered with -- confirmed via `ps -p 3152282` immediately before and after this plan's git commit.

## Deviations from Plan

None - plan executed exactly as written. The plan's own `<action>` anticipated the precondition-fail path explicitly ("If the rebuild is still in flight, STOP... record BLOCKED-ON-143.1-07 in the SUMMARY with the freshness evidence and exit"), and that is exactly what happened after a genuine live check (not an assumption carried over from the dispatch prompt, which itself warned its own timestamp might be stale by the time this plan actually ran -- re-verified independently via a fresh `ps aux` and a fresh SQL query at execution time, ~5 hours after the dispatch note's snapshot, and the block still held).

## Issues Encountered

None beyond the expected external blocker. The pre-commit hook's ruff/black checks initially reported "BLOCKED: ruff not found" / "BLOCKED: black not found" because the worktree's `PATH` did not include `.venv/bin` by default (the worktree has no `.venv` directory of its own; it uses the main repo's shared `.venv`). Resolved by prepending `/home/bg/dev/indicagent/.venv/bin` to `PATH` for the commit command -- not a deviation from plan content, just an environment/tooling fix needed to satisfy the project's own pre-commit hook.

## Known Stubs

None. The script's STEP 1-3 logic (measurement queries, spread computation, band classification, F1/F2 verdict rendering) is fully implemented, not stubbed -- it simply has not been exercised against real post-rebuild data yet, which is the correct, plan-mandated state given the precondition failure. No placeholder values, no hardcoded "TODO" branches, no empty-data fallbacks that would silently mask a real measurement.

## Threat Flags

None beyond what 144-06-PLAN.md's own `<threat_model>` already registered:
- T-144-06-SW (single-writer discipline vs the in-flight rebuild): mitigated as specified -- STEP 0 aborted loudly before any write path was reached; the script itself is read-only (`conn.rollback()` unconditionally in `main()`'s `finally` block, never `conn.commit()`).
- T-144-06-SQL (parameterized query surface): implemented as specified -- every `%(name)s`-bound value (`symbol`, `regime_scope`, `is_pooled`, `regimes`, `tfs`) is passed via psycopg2's parameter dict, never string-interpolated into SQL text.
- T-144-06-BIAS (pre-committed bands/falsifiers before the number is seen): implemented as specified -- `_GAP_DEFICIENT`/`_GAP_ADEQUATE` and the F1/F2 decision tree are module-level constants and functions fixed before any query result is read, matching the doc's pre-registered thresholds verbatim.

## User Setup Required

None - no external service configuration required. The one external dependency (the `143.1-07` corpus rebuild completing) is a separate, already-tracked workstream (`.planning/todos/pending/102-ic-engine-idle-session-timeout-writes-zero-rows.md`) that this plan correctly did not touch.

## Next Phase Readiness

- `scripts/analysis/phase144_regime_separation_gate.py` is code-complete and ready to run to completion the moment the `143.1-07` rebuild finishes and `feature_ic_scores` starts carrying today's `computed_at` rows with the new rates cross-sectional labels. No further code changes are anticipated to be needed -- re-running the script (`.venv/bin/python scripts/analysis/phase144_regime_separation_gate.py`) is the entire remaining action.
- **Phase 144 is NOT yet done per its own D-05 acceptance criterion.** Code-complete (Plans 01-05) is confirmed; the empirical re-measurement (this plan's actual purpose) is blocked on external state outside this phase's control. This matches D-06/D-07's explicit design -- the phase's own final verification step is allowed to be the one that stays open pending an external corpus rebuild, and this SUMMARY documents exactly why with live evidence rather than asserting completion prematurely.
- Recommended next action: once `143.1-07` completes (monitor via `.planning/todos/pending/102-ic-engine-idle-session-timeout-writes-zero-rows.md`'s own status entries, or a fresh `SELECT max(computed_at) FROM feature_ic_scores`), re-run this script with no `--force` flag; STEP 0 should then pass automatically (no code change needed) and STEP 1-3 will produce the actual gap numbers and F1/F2 verdict. That output should be appended to this phase's final closure record (likely a short addendum to this SUMMARY or a new dated finding, per the orchestrator's judgment at that time).
- No blockers introduced by this plan itself. The orchestrator/user is the one who owns the decision of when to re-check `143.1-07`'s completion and re-run this gate; this plan does not create any new automation to poll it (matching the "no human checkpoints" but also "do not interfere with unrelated in-flight compute" instructions).

## Self-Check: PASSED

- FOUND: scripts/analysis/phase144_regime_separation_gate.py
- FOUND commit: 966a03fc (Task 1)
- Verified: `python3 -c "import ast; ast.parse(open('scripts/analysis/phase144_regime_separation_gate.py').read())"` passes
- Verified: `grep -c "regime_scope" scripts/analysis/phase144_regime_separation_gate.py` returns 13 (> 0)
- Verified: `grep -c "TLT" scripts/analysis/phase144_regime_separation_gate.py` returns 13 (> 0)
- Verified: `.venv/bin/ruff check scripts/analysis/phase144_regime_separation_gate.py` -- All checks passed
- Verified: `.venv/bin/black --check scripts/analysis/phase144_regime_separation_gate.py` -- no reformatting needed after applying black once
- Verified: live run of the script against the actual database printed `BLOCKED-ON-143.1-07` with freshness evidence and exited 1, exactly matching the plan's required failure-path behavior
- Verified: `ps -p 3152282` before and after this plan's commit shows the same external PID still running, untouched

---
*Phase: 144-cross-sectional-regime-model-regime-group*
*Completed: 2026-07-12*
