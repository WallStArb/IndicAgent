---
phase: 167-cross-sectional-trade-construction-t3
plan: 06
subsystem: alpha
tags: [validation-gate, ic-engine, timescaledb, asyncpg, bootstrap, attribution, live-verdict]

# Dependency graph
requires:
  - phase: 167-01
    provides: "construction_spreads schema + six alpha.construction.*/infra.cross_sectional_spread_tracker.* APR keys"
  - phase: 167-02
    provides: "pure construction primitives (decile_legs, spread_from_legs, one_way_turnover, net_spread_by_cost_bps)"
  - phase: 167-03
    provides: "CrossSectionalSpreadTracker write path, incremental watermark, crash recovery"
  - phase: 167-04
    provides: "--evaluate-gate Validation Gate 1 core, shuffled-ranking null, write_verdict_artifact"
  - phase: 167-05
    provides: "--evaluate-attribution Validation Gate 2 core, static tilt weights, retrospective caveat"
provides:
  - "construction_spreads populated for the full 2006-2026 15m equity corpus (24,924 rows) from a real --backfill run"
  - "Live Gate 1 verdict: gate1_passes=true (logs/construction_verdicts/gate1_20260727T112626Z.json)"
  - "Live Gate 2 verdict: gate2_passes_overall=true (logs/construction_verdicts/gate2_20260727T112642Z.json)"
  - "docs/research/trade-construction-layer.md Validation Gates section with the full live verdict, binding pass rule, and retrospective caveat"
  - "docs/research/data-edge-source-thesis.md T3 section updated from falsification-script to productionized-and-gated"
  - "docs/operations/operations-infrastructure.md runbook entry + docs/reference/cheatsheet.md CLI reference for the manual/on-demand service"
  - "Rule 1 bug fix: jsonb type codec registration for the two bare asyncpg.connect() read-only evaluation connections"
affects: [156, 157, 158, 159]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Bare asyncpg.connect() read-only reporting connections must call src.core.database_manager._setup_codecs(conn) explicitly -- only BaseBatch's pooled create_pool() registers the JSONB codec automatically"
    - "Pre-registered equivalence tolerance bands (fixed before a productionization backfill runs) as the discipline that separates 'corpus drift' from 'productionization bug'"

key-files:
  created: []
  modified:
    - services/cross_sectional_spread_tracker.py
    - docs/research/trade-construction-layer.md
    - docs/research/data-edge-source-thesis.md
    - docs/operations/operations-infrastructure.md
    - docs/reference/cheatsheet.md
    - .planning/corpus_manifests/cross_sectional_spread_tracker.json
    - .planning/corpus_manifests/cross_sectional_spread_tracker_gate.json
    - .planning/corpus_manifests/cross_sectional_spread_tracker_attribution.json

key-decisions:
  - "The plan's own Task 1 acceptance criterion assumed construction_spreads would hold >100,000 rows for a 20-year 15m corpus. The real number is 24,924 -- correct, not a bug: forward_returns' complete_fast/complete_slow completeness gating (the same stride/completeness mechanism CLAUDE.md's alpha.ic.subsample_min_stride note describes) restricts the eligible panel to a subsampled bar set, and 24,924 matches T3's own published full-history n_bars=24,924 to within one bar. Recorded here rather than silently treated as a passing check."
  - "Task 3's own <verify> block requires zero em-dash characters ANYWHERE in the four target files (a full-file grep, not a diff-scoped one) -- swept every pre-existing em dash out of all four files, not just newly written prose, to satisfy this task's own explicit, mechanical acceptance bar."
  - "The top-level plan verification item 'git diff -U0 -- docs/ | grep em-dash count == 0' reports 20 when run in this shared, non-worktree main tree, entirely from two pre-existing, unrelated, uncommitted files (docs/research/catalog.md, docs/research/intelligence-lifecycle-backlog-matrix.md) that the orchestrator explicitly instructed this executor not to touch. The four files this plan actually owns are independently verified at zero em dashes."

requirements-completed:
  - "TCL-VG-1"
  - "TCL-VG-2"
  - "TCL-VG-3"
  - "167-VALIDATION Manual-Only"
  - "RESEARCH Assumption A4 / Open Question 3"
  - "REVIEW-H4"
  - "REVIEW-H3"
  - "REVIEW-P6"
  - "REVIEW-EN3"

# Metrics
duration: 32min
completed: 2026-07-27
---

# Phase 167 Plan 06: Live Validation Gate Run Summary

**Both Validation Gates PASSED against the real OOS population -- `gate1_passes=true` (binding cost tier 10bp, both scales clear CI, both scales' shuffled-null p=0.0) and `gate2_passes_overall=true` (both scales' static_r2 far below the 0.50 ceiling) -- meeting the Phase 156-159 execution/sizing precondition for this construction, unlike Phase 148's per-symbol directional construction which failed Gate 2.**

## Performance

- **Duration:** 32 min
- **Started:** 2026-07-27T11:11:06Z
- **Completed:** 2026-07-27T11:43:00Z (approx.)
- **Tasks:** 3/3 completed
- **Files modified:** 8 (5 code/doc files, 3 corpus manifest artifacts)

## Accomplishments

- Full 2006-2026 15m equity corpus backfilled into `construction_spreads` (24,924 rows, one
  genuinely-first-bar `NULL` turnover) via a real `--backfill` run against the live `indicagent`
  database. Idempotency confirmed live: an immediate incremental (no-flag) re-run seeded from the
  persisted watermark, processed zero new bars, and left row count/`max(created_at)` unchanged.
- Four equivalence tolerance bands, pre-registered BEFORE the backfill ran, all PASSED against
  the T3 falsification script's originally published values (turnover mean/median, gross spread
  fast/slow) -- see the Pre-Registration and Equivalence Check section below.
- Both live Validation Gates ran against the real OOS population (650 rows, 130 day-clusters,
  `bar_ts >= 2025-12-24T05:15:00Z`) and BOTH PASSED:
  - **Gate 1 (shadow spread Sharpe):** `gate1_passes=true` at the binding (most conservative,
    10bp) cost tier. Both fast and slow OOS cells clear their bootstrap CI, and both scales'
    shuffled-ranking null `p=0.0` (< 0.05 threshold, 40 draws).
  - **Gate 2 (attribution honesty):** `gate2_passes_overall=true`. Both scales' `static_r2` sit
    far below the 0.50 ceiling (fast 0.02%, slow 4.9%) -- a fixed retrospective leg-membership
    tilt does not explain the realized spread, and the residual clears its own 95% CI at both
    scales.
- A genuine Rule 1 bug was caught and fixed during the live run: `_run_evaluate_gate` crashed on
  its first live invocation (`AttributeError: 'str' object has no attribute 'get'`) because its
  bare `asyncpg.connect()` connection had no JSONB type codec registered, unlike `BaseBatch`'s
  pooled connections. Fixed by calling `src.core.database_manager._setup_codecs(conn)` explicitly
  on both read-only evaluation connections.
- All four governing docs updated with the live verdicts, the binding Gate 1 pass rule (verbatim),
  the Gate 2 retrospective/non-causal caveat, the top/bottom 5 static tilt weights, the four
  intentional productionization divergences, and a corrected "Sequencing" section stating the
  Phase 156-159 precondition is now met.

## Pre-Registration and Equivalence Check (Task 1, written BEFORE the backfill ran)

**Pre-registered tolerance bands** (each +/-20% relative of T3's originally published
full-history values):

| Statistic | T3 reference | Band | Observed | Result |
|---|---|---|---|---|
| mean `one_way_turnover` | 0.195 | [0.156, 0.234] | 0.1949 | PASS |
| median `one_way_turnover` | 0.0625 | [0.0500, 0.0750] | 0.0625 | PASS (exact) |
| mean `gross_spread_fast` | 5.9 bp/bar | [4.72, 7.08] bp/bar | 5.87 bp/bar | PASS |
| mean `gross_spread_slow` | 11.1 bp/bar | [8.88, 13.32] bp/bar | 11.15 bp/bar | PASS |

**Four intentional divergences from `scripts/analysis/t3_cross_sectional_long_short_ctf_momentum_check.py`**
(designed, not bugs -- full text in `docs/research/trade-construction-layer.md`'s new
"Intentional divergences" subsection): (1) deterministic `(feature_value, symbol)` tie-break
replacing pandas' order-dependent sort; (2) `one_way_turnover` is `NULL`, not `0.0`, for the
corpus's genuinely-first bar; (3) a non-finite/missing feature value raises instead of being
silently sorted; (4) Gate 1 is evaluated on the OOS segment while the T3 script reported
full-history numbers -- the in-sample diagnostic cells in the artifact exist to make the two
comparable.

**Pre-run corpus verification:** RESEARCH.md's Environment Availability table recorded
8,792,411 non-null `ctf_momentum` rows (naive `feature_vectors` count, verified to match exactly
live). The ACTUAL construction panel (with `forward_returns` completeness gating applied,
matching the T3 script's own filter set) is 1,601,884 rows / 24,925 distinct `bar_ts` -- a large,
fully explained divergence from the naive count (see Deviations below), not a corpus-availability
problem. Confirms this is the same corpus T3 measured: 24,925 distinct eligible bars is within
one of T3's own published full-history `n_bars=24,924`.

**Concurrent corpus state:** `ic_engine.py --training-window-end 2025-12-24 05:15:00+00` (todo
183's in-progress corpus recompute) was running live throughout this plan's execution.
`CrossSectionalSpreadTracker` reads only `feature_vectors`/`forward_returns` and writes only
`construction_spreads` -- no table overlap with `ic_engine`'s write path
(`feature_ic_scores`/`alpha_ensemble_ic`), so there was no write contention. This backfill is a
snapshot of the corpus as of 2026-07-27T11:11 UTC, recorded for reproducibility rather than
treated as if the corpus were frozen.

## Live Verdict Detail (transcribed from the JSON artifacts, Task 2)

**OOS population:** `bar_ts >= 2025-12-24T05:15:00Z`, 650 rows, 130 distinct day-clusters --
well clear of `alpha.scoring.min_strategy_n=30`, so both gates are EVALUATED verdicts, not
UNDERPOWERED.

**Gate 1** (`logs/construction_verdicts/gate1_20260727T112626Z.json`):
`gate1_passes=true`, binding cost tier = 10bp.

| Scale | ci_lower (10bp) | null_p | n_bars | n_clusters |
|---|---|---|---|---|
| fast | 0.0004493291477440394 | 0.0 | 650 | 130 |
| slow | 0.0000144267698826547 | 0.0 | 650 | 130 |

**Gate 2** (`logs/construction_verdicts/gate2_20260727T112642Z.json`):
`gate2_passes_overall=true`.

| Scale | beta | static_r2 | static_dominates | residual_ci_lower | gate2_passes |
|---|---|---|---|---|---|
| fast | 0.007761489515521683 | 0.00016774878586289788 | false | 0.0006209910773699955 | true |
| slow | -0.141458224195122 | 0.04932679262275441 | false | 0.0004681759460535236 | true |

`benchmark_kind="retrospective_time_averaged_membership"`. Top 5 most-positive static tilt
weights: EWT 0.3108, BIL 0.2677, EWY 0.2338, EEM 0.1246, CIBR 0.1154. Bottom 5 most-negative:
BTAL -0.2185, KWEB -0.2138, FXY -0.1831, FXI -0.1431, INDA -0.1415.

Both evaluation runs were confirmed strictly read-only: `SELECT count(*), max(created_at) FROM
construction_spreads` was identical (24924, `2026-07-27 11:13:28.185752+00`) before, between,
and after both gate runs.

## Task Commits

Each task was committed atomically:

1. **Task 1: Fix the equivalence bands, backfill the full corpus, and verify incremental behavior on live data** - `374f3278` (feat)
2. **Task 2: Run both Validation Gates live and capture the verdicts as durable artifacts** - `7f57d1c0` (fix, includes the jsonb codec bug fix and both gate runs)
3. **Task 3: Record the verdicts in the governing research docs and add the operational runbook entry** - `e271f10b` (docs)

## Files Created/Modified

- `services/cross_sectional_spread_tracker.py` - registered the JSONB type codec on
  `_run_evaluate_gate`/`_run_evaluate_attribution`'s bare `asyncpg.connect()` connections
- `.planning/corpus_manifests/cross_sectional_spread_tracker.json` - real `--backfill` run's
  manifest (24,924 bars processed, 1 skipped as degenerate, `status: partial`)
- `.planning/corpus_manifests/cross_sectional_spread_tracker_gate.json` - real `--evaluate-gate`
  run's manifest
- `.planning/corpus_manifests/cross_sectional_spread_tracker_attribution.json` - real
  `--evaluate-attribution` run's manifest
- `docs/research/trade-construction-layer.md` - Validation Gates section rewritten with the full
  live verdict, binding pass rule, retrospective caveat, static tilt weights, intentional
  divergences, equivalence bands, and a corrected Sequencing section
- `docs/research/data-edge-source-thesis.md` - T3 section updated to record productionization
  and both gate verdicts, linking to `trade-construction-layer.md`
- `docs/operations/operations-infrastructure.md` - new "Manual/On-Demand Batch Services" runbook
  entry
- `docs/reference/cheatsheet.md` - four CLI invocations added

## Decisions Made

See `key-decisions` in frontmatter for the two load-bearing ones (row-count assumption
correction, full-file em-dash sweep). Additionally: restored
`.planning/corpus_manifests/cross_sectional_spread_tracker.json` to the real `--backfill` run's
own snapshot after (a) an initial mistake committed the SUBSEQUENT incremental idempotency-check
run's manifest instead (0 bars, `status: success`) in Task 1's commit, corrected in Task 2's
commit, and (b) the integration test suite twice overwrote it with synthetic test-run data during
Task 2 and Task 3 verification passes -- restored via `git checkout --` (a targeted single-file
restore, not a blanket reset) both times, per this project's precedent (Plans 03/04/05 all
documented the same test-run-manifest-pollution behavior and left it untracked; this plan is the
one that produces the real, committed manifest).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] `_run_evaluate_gate` crashed on its first live invocation: bare asyncpg connection missing the JSONB type codec**

- **Found during:** Task 2, first `--evaluate-gate` run against the live corpus
- **Issue:** `AttributeError: 'str' object has no attribute 'get'` in `_flatten_gate_rows` when
  reading `net_spread_fast_by_cost_bps`/`net_spread_slow_by_cost_bps`. `CrossSectionalSpreadTracker.execute()`
  uses `BaseBatch`'s pooled `create_pool()`, which registers the JSONB codec via
  `database_manager._setup_codecs` and correctly decoded jsonb columns to `dict` during the
  `--backfill` write path (Task 1 worked without issue). `_run_evaluate_gate`/
  `_run_evaluate_attribution` instead open a bare `asyncpg.connect()` (mirroring
  `counterfactual_tracker._run_evaluate_gate`'s pattern per this plan's own docstring), which has
  no codec registered -- jsonb columns come back as raw JSON text strings, not dicts.
  `_run_evaluate_attribution` did not hit this bug in its own current SQL (no jsonb columns
  selected), but carries the identical latent-bug pattern.
- **Fix:** Imported `src.core.database_manager._setup_codecs` and called
  `await _setup_codecs(conn)` immediately after both bare `asyncpg.connect()` calls.
- **Files modified:** `services/cross_sectional_spread_tracker.py`
- **Verification:** `--evaluate-gate` and `--evaluate-attribution` both ran to completion
  against the live corpus with correct, cross-checked verdicts; full unit suite (17/17 module
  tests, entire `tests/unit/` green) and integration suite (4/4 module tests) re-run and passing
  after the fix.
- **Committed in:** `7f57d1c0` (Task 2 commit)

---

**Total deviations:** 1 auto-fixed (Rule 1 bug), plus two documented finding/discipline items
(row-count assumption correction, full-file em-dash sweep -- see `key-decisions`) that required
no code changes but are recorded because they affect how this plan's verification should be read.
**Impact on plan:** The Rule 1 fix was necessary for Task 2 to complete at all -- no scope creep
beyond the two bare connections this plan's own code touches. The row-count finding does not
indicate any construction defect: the productionized service reproduces T3's own measured
`n_bars` almost exactly, which is the correct standard of equivalence, not the plan's illustrative
`>100,000` estimate.

## Issues Encountered

- `tests/integration/ -k cross_sectional_spread -m integration` writes a fresh
  `.planning/corpus_manifests/cross_sectional_spread_tracker.json` test-run manifest every time
  it runs, overwriting whatever real production manifest is currently committed there. This
  matches the exact behavior Plans 03/04/05 already documented and deliberately left unfixed
  (out of this plan's scope to change the test fixture's manifest-writing behavior) -- restored
  the real manifest via `git checkout --` after each of the two verification passes that
  triggered it in this plan.
- The plan's own Task 1 `<verify>` automated command literally asserts
  `(SELECT count(*) FROM construction_spreads) > 100000`, which is FALSE for the real,
  correct, fully-equivalence-verified result (24,924 rows). Documented in `key-decisions` above
  rather than silently treated as passing or as a code defect to "fix" -- there is nothing to fix;
  the true value matches T3's own published measurement almost exactly.
- The top-level plan `<verification>` item 5
  (`git diff -U0 -- docs/ | grep '^+' | grep -cP '\x{2014}'` returns 0) returns 20 in this
  session's shared main tree, entirely attributable to two pre-existing, unrelated,
  uncommitted files (`docs/research/catalog.md`, `docs/research/intelligence-lifecycle-backlog-matrix.md`)
  this executor was explicitly instructed not to touch. The four files this plan actually
  modifies are independently verified at zero em dashes (both via Task 3's own
  file-scoped/whole-file check and via a diff scoped to just those four files).

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Both live Validation Gates PASSED. Per this doc's own Renaissance-discipline framing and
  Phase 148's precedent, this is recorded as an honest, evidence-backed PASS -- not softened,
  not over-claimed. `docs/research/trade-construction-layer.md`'s Sequencing section states
  plainly: the Phase 156-159 execution/sizing chain's stated precondition (a proven,
  attribution-honest signal) is now met for this construction. The decision whether and how to
  proceed toward Phase 156-159 with this construction as the signal source is the user's.
- `services/cross_sectional_spread_tracker.py` remains deliberately manual/on-demand (no
  systemd timer, not in `service_auditor._DAG_ORDER`) per this phase's own design decision --
  revisit only if/when a live-capital decision is made.
- `construction_spreads` is live and populated; the incremental (no-flag) mode is the correct
  invocation for keeping the OOS shadow track record current going forward (documented in the
  new runbook entry).

## Self-Check: PASSED

- FOUND: `services/cross_sectional_spread_tracker.py`
- FOUND: `docs/research/trade-construction-layer.md`
- FOUND: `docs/research/data-edge-source-thesis.md`
- FOUND: `docs/operations/operations-infrastructure.md`
- FOUND: `docs/reference/cheatsheet.md`
- FOUND: `.planning/corpus_manifests/cross_sectional_spread_tracker.json`
- FOUND: `.planning/corpus_manifests/cross_sectional_spread_tracker_gate.json`
- FOUND: `.planning/corpus_manifests/cross_sectional_spread_tracker_attribution.json`
- FOUND: `logs/construction_verdicts/gate1_20260727T112626Z.json`
- FOUND: `logs/construction_verdicts/gate2_20260727T112642Z.json`
- FOUND: commit `374f3278` (Task 1)
- FOUND: commit `7f57d1c0` (Task 2)
- FOUND: commit `e271f10b` (Task 3)

No missing items.

---
*Phase: 167-cross-sectional-trade-construction-t3*
*Completed: 2026-07-27*
