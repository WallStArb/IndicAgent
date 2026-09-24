---
phase: 176-earnings-season-calendar-primitive-todo-353
plan: 08
subsystem: ic_engine measurement / planning record
tags: [ic-gate, bh-fdr, earnings-season, verdict, todo-353]
requires: [176-04, 176-05, 176-06, 176-07]
provides:
  - measured feature_ic_scores gate verdict for earnings_season_flag and days_since_quarter_end
  - measured conditioning verdict for regime_scope='earnings_season'
  - live isolation proof for the ensemble eligibility exclusion
affects: [alpha.ic.earnings_season_conditioned, concept_registry lifecycle (not evaluated), todo 353]
tech-stack:
  added: []
  patterns: [decision rules pinned in the verdict doc before queries, matched-triple conditioning comparison]
key-files:
  created:
    - .planning/phases/176-earnings-season-calendar-primitive-todo-353/176-GATE-VERDICT.md
    - .planning/todos/pending/402-ic-engine-lifecycle-hook-guard-keyed-on-window-only.md
    - .planning/todos/pending/403-earnings-season-conditioning-re-decision-null-controlled.md
  modified:
    - .planning/todos/completed/353-earnings-season-calendar-primitive-candidate.md (moved from pending/)
    - .planning/todos/PRIORITIES.md
    - .planning/STATE.md
    - .planning/ROADMAP.md
decisions:
  - "Both Phase 176 primitives FAIL the ic_engine gate: reliable in every cell, zero FDR passes; subsumed by quarter_cycle_sin / quarter_position under cluster-representative BH-FDR"
  - "CONDITIONING_VERDICT=SHARPENS recorded as the pinned rule produced it; support is thin, so the APR key is retained and a null-controlled re-decision is filed (todo 403)"
  - "Lifecycle hook idempotency keyed on training_window_end alone skips every recompute at the pinned OOS window (todo 402); concept_registry not touched"
metrics:
  completed: 2026-09-24
  tasks: 3 (Task 1 by the orchestrator)
  files: 7
---

# Phase 176 Plan 08: Corpus IC gate verdict Summary

The ic_engine corpus run (233 symbols x 4 tfs, window end 2025-12-24 05:15 UTC) says both new
calendar primitives FAIL the FDR/walk-forward gate. The pinned conditioning rule returns
SHARPENS on thin support, so the conditioning switch stays on and a null-controlled re-decision
is filed.

## Verdict tokens

- `GATE_VERDICT_EARNINGS_SEASON_FLAG=FAIL`
- `GATE_VERDICT_DAYS_SINCE_QUARTER_END=FAIL`
- `CONDITIONING_VERDICT=SHARPENS`
- `CONDITIONING_ROLLBACK=RETAINED` (`config_state` value `true`, last `config_history` row is the
  migration_350 seed; no write made)

## Key numbers

- Both features: 40,308 rows each at this window, all `reliable = true`, zero `passes_fdr`.
- `days_since_quarter_end` shares a cluster with `quarter_position` in 40,308 of 40,308 cells and
  is never the BH-FDR representative (0 `bh_adjusted_p` rows). `earnings_season_flag` is the
  representative in 648 cells (min BH p 0.1395), otherwise mostly `quarter_cycle_sin`.
- Conditioning: population median in-season / parent `|ic_sharpe_hac|` is 1.028 / 0.982 / 1.000 /
  0.957 (5m/15m/1h/1d). Six features qualify in two or more tfs, each on 1-10 matched triples,
  none in 176-01's sweep survivors. `up_vol_body_diff` qualifies nowhere.
- A1 comparison: disagreement. The proxy's 1.94x (1d) reproduces only in cross-sectional 1d raw
  mean IC (0.0177 vs 0.0077), not per-symbol and not on the HAC metric (1.10x).
- Isolation: the live eligibility predicate admits 0 of 2,399,040 earnings-season rows; without
  176-05's clause it would admit 1,339. `regime_label_unmapped` during the run: 0.
- Scope: cross-sectional season sub-cells computed for 21/31 (5m), 27/31 (15m), 30/31 (1h),
  29/31 (1d) parent cells; 14 skipped as disk-backed, 3 below min N.

## Deviations from plan

1. **Rule 2 operationalization written into the verdict doc before its numbers.** The plan's
   conditioning rule does not define how cells are aggregated; the matched-triple median
   definition was pinned in the doc before Query 2 ran.
2. **Lifecycle finding filed as todo 402** (P1): the hook's idempotency guard keyed on
   `training_window_end` has skipped every recompute since 2026-07-22 at the pinned OOS window,
   so the two failing concepts stay `active`.
3. **Todo 403 filed** (P2) for a pre-registered, size-matched-null re-decision of
   `alpha.ic.earnings_season_conditioned`, because the SHARPENS token rests on a rule with no
   minimum-N or null arm.
4. **PRIORITIES.md 353 table row stripped rather than relinked**, following the file's own
   convention that closed rows leave the tier tables; the drift-catch note link now points at
   `completed/`.
5. **Plan's partial-IC reading unavailable**: `partial_ic` / `passes_partial_fdr` are null for
   both features (and for `quarter_position`) at this window; recorded as a limitation.
6. STATE.md already carried no 4.3x / p=1.2e-17 figures (an earlier edit removed them); the
   Phase 176 bullet was rewritten to the executed state with D-04's figures.

## Commits

- `4ece653e5` docs(176-08): gate verdict, todos 402/403
- `944980c9f` docs(176-08): close todo 353, correct STATE.md Phase 176 record

## Known stubs

None.

## Self-Check: PASSED

All created files present; commits 4ece653e5 and 944980c9f in history; todo 353 absent from pending/.
