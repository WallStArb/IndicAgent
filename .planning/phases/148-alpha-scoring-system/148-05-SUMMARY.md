---
phase: 148-alpha-scoring-system
plan: 05
subsystem: measurement
tags: [oos-gate, forward-returns, promotion-decision, path-dependent-statistics, jsonb-serialization, run-once-safety]

# Dependency graph
requires:
  - phase: 148-03
    provides: scripts/ops/corpus/ops_oos_gate1_signal_eval.py (Gate 1, run for real in this plan)
  - phase: 148-04
    provides: scripts/analysis/score03_gate2_execution_eval.py (Gate 2, run for real in this plan)
provides:
  - Gate 1 (gate_id='gate1_signal') PASS verdict recorded in gate_evaluations
  - Gate 2 (gate_id='gate2_execution') FAIL verdict recorded in gate_evaluations
  - docs/plans/archive/2026-07-22-phase148-promotion-decision.md -- the milestone's synthesized
    promotion decision (do not promote to live capital)
  - A corrected, deterministic per-bar_ts-aggregation max-drawdown methodology in
    score03_gate2_execution_eval.py, superseding an initial (also-committed, then-superseded)
    row-level tie-break attempt
  - A jsonb-safe evidence serializer (_json_safe) fixing a genuine write-path crash on
    non-finite floats (+inf/-inf/nan), latent since 148-04, only reachable on a real run
affects: [v3.1-milestone-close, any-future-phase-reading-alpha_frames-cumulative-statistics]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "aggregate-before-cumulative-walk for path-dependent statistics over cross-sectional
      concurrent-timestamp data -- SUM same-bar_ts rows first, THEN run the order-sensitive
      cumulative computation, rather than picking any per-row tie-break ordering"
    - "recursive non-finite-float JSON sanitizer (_json_safe) before jsonb writes -- RFC 8259
      has no Infinity/NaN representation; Python's json.dumps emits invalid bare tokens for
      them by default, silently working until the exact non-finite value combination hits a
      strict jsonb parser"

key-files:
  created:
    - docs/plans/archive/2026-07-22-phase148-promotion-decision.md
    - .planning/todos/pending/172-path-dependent-frame-statistics-order-sensitivity-sweep.md
    - .planning/todos/pending/173-ensemble-alpha-1h-1d-oos-scoring-gap.md
  modified:
    - scripts/analysis/score03_gate2_execution_eval.py
    - .planning/gate_look_log.jsonl
    - .planning/todos/PRIORITIES.md

key-decisions:
  - "Halted before Gate 1's real run when its mandated --dry-run pre-flight found forward_returns had ZERO OOS-side rows for every symbol/timeframe (not the partial insufficient-N the plan anticipated) -- root-caused to Phase 141.1's OOS-holdout clamp on forward_return_writer.py never having been overridden for the OOS side; reported to the coordinator rather than self-authorizing a previously-unscoped infrastructure backfill given D-04's irreversibility stakes"
  - "Coordinator independently verified the diagnosis, obtained explicit human sign-off, and backfilled forward_returns (forward_return_writer.py --training-window-end 2026-07-07T16:45:00Z, full active universe, no threshold/parameter changes, in-sample side untouched via ON CONFLICT DO NOTHING) -- resumed from Task 1's dry-run pre-flight per the coordinator's explicit instruction, did not redo already-verified reasoning"
  - "Gate 1 real run (irreversible, D-04): PASS -- 640 5m/15m cells, all reliable (zero insufficient-N once the label substrate existed), 140/640 (21.875%) qualify against a 2% floor. Discovered AFTER this irreversible run (cannot be corrected, D-04 forbids re-running) that ensemble_alpha itself has zero OOS rows at 1h (any weight_version) and zero at 1d (champion/default weight_version) -- the PASS verdict covers only 5m/15m, disclosed explicitly in the promotion decision record rather than presented as a full 4-timeframe pass; filed as todo 173"
  - "Gate 2's mandated --dry-run pre-flight found c2/c3 reproduced the frozen 143.1-08 baseline exactly but c4_max_dd missed the plan's 1e-6 tolerance by four orders of magnitude (9.597 vs 9.598) -- root-caused via alpha_frames.measured_at (proving the underlying data was byte-identical, unchanged since 143.1-08's original 2026-07-21 measurement) to ~22-way bar_ts ties (33,892 rows across only 1,534 distinct bar_ts) feeding an order-sensitive cumulative-drawdown statistic with no deterministic tie-break in either the original 143.1-08 script or the new Gate 2 script -- the frozen baseline itself was never a reproducible number, just whatever TimescaleDB parallel-chunk-scan interleaving happened on 2026-07-21"
  - "First fix attempt (frame_id row-level tie-break, commit 7e3c8913) made the query deterministic but was conceptually wrong -- same-bar_ts frames are genuinely SIMULTANEOUS positions (multiple symbols opened at the identical 5-minute bar), and treating them as sequential via ANY row ordering is not economically meaningful. Coordinator identified and directed the correct fix: aggregate (SUM) pnl_r per distinct bar_ts BEFORE the cumulative walk (commit 51a05f10, superseding 7e3c8913) -- eliminates the tie-break question structurally since SUM is order-independent and the aggregated series has exactly one row per bar_ts"
  - "Gate 2's first real-run attempt crashed (asyncpg.exceptions.InvalidTextRepresentationError: Token 'Infinity' is invalid) -- Python's json.dumps emits bare Infinity/-Infinity/NaN tokens for non-finite floats by default, which are legitimate values here (one-sided CI upper bounds) but not valid JSON per RFC 8259, which Postgres's jsonb parser correctly rejects. Confirmed this was a genuine system fault, not a statistical result: the transaction rolled back cleanly (zero partial rows, zero look-log entries), so the one-shot gate was not consumed by the failed attempt. Fixed with a recursive _json_safe() sanitizer (commit 92544222) converting non-finite floats to their string representations before serialization; verified standalone (json round-trip + direct Postgres ::jsonb cast) before retrying"
  - "Gate 2 real run (irreversible, D-04), retried successfully after both fixes: FAIL -- 3 of 5 SHADOW-REVIEW criteria fail (c2/c3/c4), matching D-06's known-going-in framing exactly. c4_max_dd=9.596266492204732, a third distinct number from both the non-reproducible frozen baseline (9.598...) and the wrong frame_id-tie-break fix (9.606...), but the verdict is identical under all three: catastrophic ~960% drawdown against a 0.25 threshold, never a borderline call"
  - "Filed two follow-up todos rather than silently noting findings in prose only: todo 172 (broader sweep for other path-dependent statistics elsewhere in the codebase, plus an unfixed related order-sensitivity symptom in frame_gate_passes/evaluate_frame_gate's cluster-mean array construction, observed as CI drift for a coverage-excluded regime cell) and todo 173 (the ensemble_alpha 1h/1d OOS coverage gap found after Gate 1's irreversible run) -- both per this project's 'capture todos immediately' convention, both explicitly non-blocking to this phase's verdict"

requirements-completed: [SCORE-02, SCORE-03, SCORE-04]

# Metrics
duration: ~3h45min (includes a coordinator round-trip for the forward_returns backfill decision and a second round-trip for the c4 methodology fix)
completed: 2026-07-22
---

# Phase 148 Plan 05: OOS Gate Promotion Decision Summary

**Both irreversible OOS proof gates run exactly once (D-04): Gate 1 (signal proof) PASS on 640 5m/15m cells (21.875% qualifying against a 2% floor); Gate 2 (execution proof) FAIL on 3 of 5 SHADOW-REVIEW criteria, after root-causing and correctly fixing a genuine max-drawdown non-reproducibility bug (same-bar_ts frames are simultaneous positions, not sequential -- aggregate before the cumulative walk) and a jsonb serialization crash on non-finite floats. Promotion decision: do not promote the v3.0 AlphaEngine to live trading capital.**

## Performance

- **Duration:** ~3h45min (includes two coordinator round-trips: one for the forward_returns
  backfill authorization, one for the c4 max-drawdown methodology correction)
- **Started:** 2026-07-22T~20:15Z (first dry-run pre-flight attempt)
- **Completed:** 2026-07-23T00:33:00Z
- **Tasks:** 3/3 completed
- **Files modified:** 3 created (promotion decision doc, 2 follow-up todos), 3 modified
  (`score03_gate2_execution_eval.py`, `.planning/gate_look_log.jsonl`, `PRIORITIES.md`)

## Accomplishments

- **Gate 1 (SCORE-02, signal proof): PASS.** Recorded in `gate_evaluations`
  (`gate_id='gate1_signal'`). 640 (symbol, tf, scale) cells across the active 80-symbol
  universe, all reliable (`n_valid` 536-7,455), 140 (21.875%) qualifying against
  `alpha.ensemble_ic.min_qualifying_fraction=0.02` -- signal concentrates at longer forward-return
  lookaheads (`extended` scale strongest, `fast` weakest/near-zero).
- **Gate 2 (SCORE-03, execution proof): FAIL.** Recorded in `gate_evaluations`
  (`gate_id='gate2_execution'`), strictly after Gate 1 per D-02. 3 of 5 pooled SHADOW-REVIEW
  criteria fail (c2 mean-P&L CI, c3 Sharpe, c4 max drawdown); c1 (69 OOS days) and c5
  (`c7_confident_loss` proxy) pass -- matching D-06's known-going-in "3 of 5" framing exactly.
  Mandatory regime-stratified companion present: only 2 of 8 champion cells clear
  `min_clusters=20` coverage, both `mid_bull`, both fail.
- **`docs/plans/archive/2026-07-22-phase148-promotion-decision.md`** synthesizes both independent
  verdicts, discloses every material finding from this plan's execution in full (the
  `forward_returns` prerequisite gap, the `c4` non-reproducibility investigation and fix, the
  jsonb crash and fix, the post-hoc-discovered `ensemble_alpha` 1h/1d coverage gap, the
  regime-cell CI order-sensitivity symptom), and states the overall decision: do not promote
  to live trading capital.
- Fixed a genuine, previously-latent bug in the already-committed 148-04 script: `_max_drawdown`
  computed over a population with ~22-way `bar_ts` ties (concurrent cross-symbol positions)
  produced a non-reproducible number because neither the frozen `143.1-08` script nor the new
  Gate 2 script had a deterministic ordering for a path-dependent statistic. Coordinator
  identified the economically-correct fix (aggregate same-`bar_ts` rows by SUM before the
  cumulative walk) after an initial row-level tie-break attempt was found conceptually wrong
  (treats simultaneous positions as sequential).
- Fixed a second genuine bug found on Gate 2's first real-run attempt: `json.dumps()`'s default
  handling of non-finite floats (`Infinity`/`NaN` bare tokens) is invalid per RFC 8259 and
  crashed on Postgres's strict `jsonb` parser -- confirmed this was a system fault (transaction
  rolled back cleanly, one-shot gate not consumed) and fixed with a recursive sanitizer before
  retrying the real, irreversible write.
- Filed 2 follow-up todos (172, 173) capturing non-blocking findings for later investigation,
  per project convention.

## Task Commits

Each task was committed atomically (plus 2 mid-execution bug-fix commits and 2 todo-filing
commits, all attributable to Task 1/2's own execution):

1. **Task 1: Run Gate 1 exactly once** - `240d9bf6` (feat) -- result PASS
   - Preceded by `68b1209d` (docs): documented the `forward_returns` blocker found during
     Task 1's own mandated dry-run pre-flight, before the coordinator's backfill resolved it
2. **Task 2: Run Gate 2 exactly once, after Gate 1** - `14c0f9e9` (feat) -- result FAIL
   - Preceded by `7e3c8913` (fix, superseded): initial frame_id tie-break attempt
   - Preceded by `51a05f10` (fix): correct per-bar_ts aggregation, superseding `7e3c8913`
   - Preceded by `92544222` (fix): non-finite-float jsonb sanitizer, fixing the crashed first
     real-run attempt
   - Followed by `a432b0e4` (docs) and `4d7053a1` (docs): todos 172/173 filed
3. **Task 3: Write the promotion decision record** - `be44902c` (docs)

## Files Created/Modified

- `docs/plans/archive/2026-07-22-phase148-promotion-decision.md` (new) -- the milestone's synthesized
  two-gate promotion verdict and overall decision
- `scripts/analysis/score03_gate2_execution_eval.py` (modified, 3 commits) -- `_json_safe()`
  non-finite-float sanitizer; `_aggregate_pnl_by_bar_ts()` per-timestamp aggregation superseding
  a row-level tie-break; `_OOS_QUERY_SQL` reverted to plain `ORDER BY bar_ts ASC` (no longer
  load-bearing given the aggregation fix)
- `.planning/gate_look_log.jsonl` (modified) -- 2 entries appended (Gate 1, Gate 2), each with
  a pre-run integrity snapshot
- `.planning/todos/pending/172-path-dependent-frame-statistics-order-sensitivity-sweep.md` (new)
- `.planning/todos/pending/173-ensemble-alpha-1h-1d-oos-scoring-gap.md` (new)
- `.planning/todos/PRIORITIES.md` (modified) -- 2 new P2 entries

## Decisions Made

See `key-decisions` in frontmatter for the full chain (forward_returns blocker -> coordinator
resolution -> Gate 1 run -> c4 non-reproducibility -> wrong-then-correct fix -> jsonb crash fix
-> Gate 2 run -> post-hoc coverage-gap disclosure). Every irreversible action was preceded by a
`--dry-run` pre-flight per the plan's own safety protocol; every anomaly surfaced by a pre-flight
was root-caused (not guessed) before either proceeding or escalating.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Non-deterministic max-drawdown statistic in the already-committed Gate 2 script**
- **Found during:** Task 2's mandated `--dry-run` pre-flight, before the real irreversible run
- **Issue:** `_max_drawdown` computed over `ORDER BY bar_ts ASC`-fetched rows with ~22-way ties
  at each `bar_ts` (concurrent cross-symbol positions), no deterministic tie-break -- produced a
  different number on every execution, missing the plan's 1e-6 reproduction tolerance against
  the frozen 143.1-08 baseline by 4 orders of magnitude
- **Fix:** Aggregate (SUM) `counterfactual_pnl_r` per distinct `bar_ts` before the cumulative
  equity walk (`_aggregate_pnl_by_bar_ts`), per the coordinator's identified correct approach --
  superseded an initial, conceptually-wrong `frame_id` row-level tie-break attempt
- **Files modified:** `scripts/analysis/score03_gate2_execution_eval.py`
- **Verification:** Reproduced `9.596266492204732` (~1e-15 noise) across 3 independent dry-runs;
  7/7 unit tests still GREEN; verdict unaffected under all 4 numbers tested (frozen baseline,
  unfixed re-run, wrong tie-break, correct aggregation)
- **Committed in:** `51a05f10` (superseding `7e3c8913`)

**2. [Rule 1 - Bug] jsonb write crash on non-finite float evidence values**
- **Found during:** Task 2's first real (irreversible) run attempt
- **Issue:** `json.dumps(evidence)` emits bare `Infinity`/`NaN` tokens for non-finite floats
  (legitimate values here -- one-sided CI upper bounds) -- invalid per RFC 8259, rejected by
  Postgres's `jsonb` parser (`InvalidTextRepresentationError`). Never caught by the dry-run path
  since it never exercises `json.dumps` (only prints formatted text)
- **Fix:** `_json_safe()` recursively converts non-finite floats to string representations
  before serialization
- **Files modified:** `scripts/analysis/score03_gate2_execution_eval.py`
- **Verification:** Confirmed the failed attempt's transaction rolled back cleanly (zero
  partial rows, zero look-log entries -- the one-shot gate was not consumed); standalone
  round-trip test (json.dumps -> json.loads, and a direct Postgres `::jsonb` cast) before
  retrying; 7/7 unit tests still GREEN; real run succeeded on retry
- **Committed in:** `92544222`

---

**Total deviations:** 2 auto-fixed (both Rule 1 - bugs in the already-committed 148-04 script,
both discovered via this plan's own mandated safety pre-flights/real-run attempts, both fixed
and verified before any irreversible action was taken on unverified code).
**Impact on plan:** Both fixes were necessary for Gate 2 to produce a trustworthy, reproducible
result at all. Neither changed the substantive gate verdict (FAIL, 3 of 5 criteria, under every
methodology variant tested). No scope creep -- both fixes are narrowly scoped to the specific
bugs found, plus the coordinator explicitly directed the c4 fix's exact shape.

## Issues Encountered

Two genuine blockers requiring coordinator involvement, both resolved:

1. **`forward_returns` OOS-coverage gap** (Task 1). Halted before Gate 1's real run; reported
   the finding rather than self-authorizing a backfill given the scope/stakes; coordinator
   independently verified, obtained human sign-off, and backfilled. See "Root Cause" detail
   preserved in this plan's earlier commit history (`68b1209d`).
2. **`c4_max_dd` tolerance failure** (Task 2). Halted before Gate 2's real run when the initial
   `frame_id` tie-break fix produced a third distinct (still non-matching) number; reported
   rather than deciding unilaterally that the divergence was immaterial, given the coordinator's
   explicit "not optional" framing of the tolerance check. Coordinator identified the correct
   fix (aggregate-per-bar_ts) and directed its implementation.

Both blockers were caught by this plan's own mandated `--dry-run` pre-flights or an irreversible
action's own atomic-transaction safety net, exactly as designed -- neither resulted in any
partial/inconsistent state in `gate_evaluations`.

## Known Stubs

None. Both gates ran against live, unmodified production data with real, verified computations.

## Threat Flags

None beyond what the plan's own `<threat_model>` already registered (T-148-07 through T-148-10,
all mitigated as designed: dry-run pre-flights + atomic check+INSERT + append-only look-log +
statistical-FAIL-is-not-a-crash all worked correctly in practice, including through two real
system faults that were correctly distinguished from statistical outcomes).

## User Setup Required

None -- no external service configuration required.

## Next Phase Readiness

Phase 148 (Alpha Scoring System) is now COMPLETE (5/5 plans). The milestone's promotion
decision is final: do not promote the v3.0 AlphaEngine to live trading capital at this time.
Gate 1 (signal proof) is real; Gate 2 (execution proof) fails decisively. Diagnosing why Gate 2
fails and whether a frame/execution recalibration could help is explicitly out of scope for this
phase (per `148-CONTEXT.md`'s deferred scope) -- real follow-on work for a future phase.

Two non-blocking follow-ups filed: todo 172 (path-dependent statistics sweep + an unfixed
regime-cell CI order-sensitivity symptom in `frame_gate_passes`/`evaluate_frame_gate`) and todo
173 (`ensemble_alpha` zero rows at 1h for any weight_version, zero at 1d for the champion/default
weight_version -- Gate 1's PASS verdict covers 5m/15m only, disclosed in the promotion record).

## Self-Check: PASSED

Verified `docs/plans/archive/2026-07-22-phase148-promotion-decision.md` exists and passes all of the
plan's required grep acceptance checks (`0.38512018365944`, `9.598299843093644`, "Gate 1",
"Gate 2", "v2.x", "cliff" -- all present) plus zero em-dash characters (CLAUDE.md convention).
Verified both `.planning/todos/pending/172-*.md` and `173-*.md` exist on disk. Verified all 9
commits from this plan (`68b1209d`, `240d9bf6`, `7e3c8913`, `51a05f10`, `92544222`, `14c0f9e9`,
`a432b0e4`, `4d7053a1`, `be44902c`) present in `git log --oneline`. Verified `gate_evaluations`
has exactly 1 row for `gate1_signal` (result='pass') and exactly 1 row for `gate2_execution`
(result='fail'), zero rows for `gate_id='FRAME-04'`, and `gate1_signal.run_ts` precedes
`gate2_execution.run_ts` (D-02 ordering held). Verified `.planning/gate_look_log.jsonl` has
exactly 2 entries, each carrying a pre-run integrity snapshot. Verified the full
`.venv/bin/pytest tests/unit/ -q` suite passes (exit code 0; 3 pre-existing skips unrelated to
this plan, zero failures).

---
*Phase: 148-alpha-scoring-system*
*Completed: 2026-07-22*
