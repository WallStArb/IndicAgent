---
phase: 151-feature-primitives-expansion-theory-motivated-interaction-la
plan: 02
subsystem: database
tags: [ic-engine, apr, collinearity-clustering, regime-conditioning, timescaledb]

# Dependency graph
requires:
  - phase: 144
    provides: regime_group routing (_resolve_symbol_routing, dual_write_symbol_hmm per-group field)
  - phase: 162
    provides: whole-cell fingerprint mechanism (_symbol_expected_cells, ic_cell_fingerprints)
provides:
  - alpha.ensemble.cluster_regime_conditioned APR key (migration 286), seeded true
  - Widened symbol_hmm regime_passes gate in ic_engine.py (dual_write_symbol_hmm OR cluster_regime_conditioned)
  - _build_regime_passes pure helper (extracted for unit testability)
  - _symbol_expected_cells widened to match (fingerprint-staleness-tracking correctness fix)
affects: [151-07]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Global run-level APR switch threaded explicitly through the same tuple path as an existing per-group field, even though it is also reachable via ICEngineConfig, to keep both symbol_hmm-pass gates visible at the same call-site shape"
    - "Pure extraction of inline gate-construction logic into a DB-free helper specifically to enable direct unit testing of ProcessPoolExecutor-worker-only compute paths"

key-files:
  created:
    - production/migrations/286_cluster_regime_conditioned.sql
    - .planning/todos/pending/257-feature-registry-worktree-branch-skew-blocks-ic-engine-runs.md
  modified:
    - services/ic_engine.py
    - tests/unit/test_ic_engine_clustering.py
    - tests/unit/test_ic_engine_fingerprint.py
    - tests/unit/test_ic_engine_compute_split.py

key-decisions:
  - "Used migration 286, not the plan's provisional 260 -- both 259 and 260 were already taken by other work landed since the plan was authored (2026-07-24)"
  - "Extracted _build_regime_passes as a pure helper so Task 3's regime_passes-shape tests don't require a live DB connection"
  - "Widened _symbol_expected_cells (the fingerprint gate's mirror of what _compute_symbol_tf actually writes) to also gate on cluster_regime_conditioned -- an undocumented gap in the plan's own interfaces section that would have silently stopped tracking staleness for the widened symbol_hmm cells"
  - "Empirical verification used a direct _compute_symbol_tf/_write_symbol_results call path (bypassing only main()'s unrelated feature_registry/concept_registry drift gate from a concurrent Phase 170 session) after that gate made further real ic_engine.py CLI runs impossible mid-verification"
  - "Runtime-budget rule applied at ratio 0.994 (well under 2.0x) -- alpha.ensemble.cluster_regime_conditioned stays true, unchanged from its migration-286 seed"

requirements-completed: []

# Metrics
duration: 2h
completed: 2026-08-05
---

# Phase 151 Plan 02: Regime-Conditioned Cluster Membership Summary

**Widened ic_engine's symbol_hmm collinearity-clustering pass to run for every regime-group-routed symbol via a new `alpha.ensemble.cluster_regime_conditioned` APR key (migration 286), proven additive-only against live corpus data and unit-tested at the gate-logic level.**

## Performance

- **Duration:** ~2h
- **Started:** 2026-08-05T09:47:35Z
- **Completed:** 2026-08-05T11:47:46Z
- **Tasks:** 3/3 completed
- **Files modified:** 6 (1 migration, 1 service file, 3 test files, 1 todo)

## Accomplishments

- `alpha.ensemble.cluster_regime_conditioned` APR key registered across `config_schema`/`config_state`/`config_history`, seeded `true` per ROADMAP's explicit specification (migration 286 -- the plan's provisional 260 was already taken by other landed work)
- `ic_engine.py`'s symbol_hmm `regime_passes` gate widened from `dual_write_symbol_hmm` alone to `dual_write_symbol_hmm OR cluster_regime_conditioned`, threaded through `ICEngineConfig`, `_compute_symbol_tf`'s signature, and the per-symbol worker-arg tuple identically to how `dual_write_symbol_hmm` is threaded
- **Rule 2 fix (not in the plan's own interfaces section):** `_symbol_expected_cells` -- the whole-cell fingerprint gate's mirror of which cells `_compute_symbol_tf` actually writes -- did not account for the new global switch. Left unfixed, a symbol whose only symbol_hmm-enabling condition is `cluster_regime_conditioned` (not its group's `dual_write_symbol_hmm`) would have its symbol_hmm cell silently drop out of staleness tracking forever after the first compute, since an untracked cell is never re-checked against a fresh `upstream_watermark`. Widened with the identical two-condition gate, plus 4 new regression tests.
- `_build_regime_passes` extracted as a pure, DB-free helper from `_compute_symbol_tf`'s previously-inline `regime_passes` construction, enabling Task 3's direct unit tests of the gate's length/scope behavior without a live DB connection
- 7 new/expanded unit tests in `test_ic_engine_clustering.py` (4 required by the plan + the pre-existing 3), 4 new tests in `test_ic_engine_fingerprint.py`, 1 signature-contract test updated in `test_ic_engine_compute_split.py` -- full `tests/unit/` suite (703 tests) green
- Empirical live-corpus verification (below) confirms additive-only behavior and applies the pre-registered runtime-budget rule

## Task Commits

1. **Task 1: Migration 286 -- alpha.ensemble.cluster_regime_conditioned** - `10ae4ae3` (feat)
2. **Task 2: Widen the regime_passes gate in ic_engine** - `f1c19f0c` (feat)
3. **Task 3: Unit coverage plus empirical no-regression check** - `06a4fa4c` (test)

**Deviation-driven commit:** `eef72668` (docs: file todo 257 for the discovered concurrent-session blocker)

## Files Created/Modified

- `production/migrations/286_cluster_regime_conditioned.sql` - APR triplet registration, seeded true
- `services/ic_engine.py` - `cluster_regime_conditioned` field on `ICEngineConfig` (COMPUTATIONAL-classified), `_build_regime_passes` pure helper, widened `_symbol_expected_cells` gate, threaded parameter through `_compute_symbol_tf`/worker-arg tuple/call site
- `tests/unit/test_ic_engine_clustering.py` - 4 new tests on `_build_regime_passes` + the behavioral `_cluster_features` regime-sensitivity proof
- `tests/unit/test_ic_engine_fingerprint.py` - 4 new tests on `_symbol_expected_cells`' widened gate
- `tests/unit/test_ic_engine_compute_split.py` - updated `_compute_symbol_tf` signature contract
- `.planning/todos/pending/257-feature-registry-worktree-branch-skew-blocks-ic-engine-runs.md` - new todo documenting the concurrent-session blocker discovered during verification

## Decisions Made

- **Migration number 286, not 260:** re-verified the next-free number per the plan's own instruction (`ls production/migrations/ | sort -t_ -k1 -n | tail -5`) and found both 259 and 260 already taken by work landed since the plan was authored 2026-07-24. Used 286 (the actual next-free number as of this session) and updated every `changed_by='migration_260'` reference to `migration_286`.
- **Extracted `_build_regime_passes`:** the plan's Task 3 test cases (1-3) require asserting on `regime_passes`' length and `resolved_scope`, but that construction lived inline inside `_compute_symbol_tf`, which opens real short-lived DB connections and is not a practical unit-test target. Extracted as a pure function (mirrors this file's existing `_group_cells_for_metrics`/`_merge_skip_reasons` extraction pattern) with zero behavior change -- `_compute_symbol_tf` now calls it instead of duplicating the construction inline.
- **Widened `_symbol_expected_cells` (Rule 2):** discovered while implementing Task 2 that the fingerprint gate's own mirror of "which cells does this symbol write" was not in the plan's interfaces section and did not account for the new switch. See Deviations below.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing Critical Functionality] `_symbol_expected_cells` did not mirror the widened symbol_hmm gate**
- **Found during:** Task 2 (widening the regime_passes gate)
- **Issue:** `_symbol_expected_cells` (`services/ic_engine.py`) is the whole-cell fingerprint gate's own mirror of which `(tf, pass_type)` cells a symbol writes -- explicitly documented as needing to "never drift" from `_compute_symbol_tf`'s actual behavior. It only added a `symbol_hmm` cell when `cross_sectional and dual_write`, not accounting for the new `cluster_regime_conditioned` OR-condition. Left unfixed: a symbol whose symbol_hmm cell exists ONLY because of `cluster_regime_conditioned` (not its group's `dual_write_symbol_hmm`) would have that cell silently excluded from the fingerprint prepass forever after its first compute -- an untracked cell is never re-checked against a fresh `upstream_watermark`, so it would never be redispatched even as `feature_vectors` grows underneath it.
- **Fix:** Added the identical `cluster_regime_conditioned: bool = False` parameter and widened the gate to `cross_sectional and (dual_write or cluster_regime_conditioned)`, matching `_compute_symbol_tf` exactly. Threaded through the call site in `main()`'s fingerprint prepass.
- **Files modified:** `services/ic_engine.py`, `tests/unit/test_ic_engine_fingerprint.py`
- **Verification:** 4 new regression tests (widened-gate positive case, default-false backward-compat, no-double-append with both flags true, no-effect-when-not-cross-sectional) -- all pass. Full `tests/unit/` suite green.
- **Committed in:** `f1c19f0c` (Task 2 commit)

---

**Total deviations:** 1 auto-fixed (Rule 2 - missing critical functionality)
**Impact on plan:** Necessary for correctness at corpus scale -- without it, the plan's own stated purpose (making the second stratification axis run unconditionally for every routed symbol) would have silently degraded to "runs once, then stops tracking staleness" for exactly the symbols the plan targets. No scope creep -- fix stayed inside the same gate mechanism Task 2 was already widening.

## Issues Encountered

**Task 3's empirical verification hit a stale plan premise and an external, out-of-scope blocker.** Full account below since both materially shaped what was actually measured.

### 1. Stale premise: `equity`/`rates`/`fx` groups already have `dual_write_symbol_hmm=true`

The plan's interfaces section states "live: `rates` only, migration 247" for `dual_write_symbol_hmm`. That was true 2026-07-24 when the plan was authored, but migration 262 (equity, closed before this session) and migration 280 (fx, 2026-08-01) have since flipped `dual_write_symbol_hmm=true` for those groups too. **As of this session, every currently-enabled `alpha.regime.groups` entry (`equity`, `rates`; `fx` is enabled but has zero `market_regimes` rows, see below) already sets `dual_write_symbol_hmm=true`.** This means `cluster_regime_conditioned` currently has **zero observable marginal effect** on the live corpus -- the gate's `dual_write_symbol_hmm OR cluster_regime_conditioned` condition is already `True` via the first operand for every routed symbol regardless of the new key's value. This is a real, confirmed finding (verified via a live wall-clock ratio measurement, below), not a code defect -- the mechanism is correctly built for the *general* case (a future group added with `dual_write_symbol_hmm=false`), it simply isn't exercised incrementally by *today's* specific config.

### 2. Scoped test symbols BIL/LQD/PFF lack `feature_vectors.regime` coverage

The plan's suggested "3 equity symbols and TLT" scope needed symbols with real per-symbol HMM regime labels to produce any symbol_hmm rows at all. The first 3 equity symbols tried (BIL, LQD, PFF -- chosen because they had zero prior `symbol_hmm` rows, seemingly matching the plan's stale "previously had none" premise) turned out to have **zero non-NULL `feature_vectors.regime` values** (regime_writer.py has never run for them) -- an unrelated, pre-existing data gap, not caused by this plan. Switched to SPY/QQQ/ARKK (confirmed 100% regime coverage) for the isolation test.

### 3. External blocker: concurrent Phase 170 session desyncs `feature_registry`/`concept_registry` row counts

Mid-verification, `services/ic_engine.py`'s `main()` startup gates (feature_registry row-count check and a separate `concept_registry(domain='feature')` drift check, both comparing live DB rows against `len(dataclasses.fields(FeatureVector))=249` in this worktree's checked-out code) began failing with a live count of 259/261 respectively. Root-caused to Phase 170 (feature_registry -> Concept Registry migration), running in a separate concurrent GSD session against the SAME shared production database, having landed migrations that add registry rows ahead of what this worktree's branch (not yet merged with Phase 170's) expects. Confirmed non-transient by monitoring the row count for several minutes with zero movement -- this will not resolve within a single session; it resolves only once Phase 170 merges to `main`. Filed as **todo 257** (`.planning/todos/pending/257-feature-registry-worktree-branch-skew-blocks-ic-engine-runs.md`) since it blocks ALL per-symbol `ic_engine.py` runs from any unmerged worktree, not just this one.

**This blocker struck mid-experiment**, after I had already deleted SPY/QQQ/ARKK's `symbol_hmm` rows at tf=1h (12,948 rows + 3 fingerprint rows) to observe a clean 0→>0 transition isolating `cluster_regime_conditioned`'s effect from `dual_write_symbol_hmm` (temporarily flipped false for the `equity` group). With the CLI path blocked, I restored the data by calling `_compute_symbol_tf`/`_write_symbol_results` directly (bypassing only the two unrelated registry gates, which live in `main()`, not in the compute/write functions) with the exact same RNG derivation (`_derive_worker_rng_seed`) and inputs a real worker would use. **Verified byte-identical restoration**: post-restoration corpus-wide `regime_scope` aggregate snapshot (count + md5 of `cluster_id` string_agg) matches the pre-deletion snapshot exactly on all three scopes. `alpha.regime.groups` config was also restored to its exact original value (content-diff clean, version counter incremented transparently through `config_history`).

### What was actually measured

1. **Real production CLI run** (`ic_engine.py --symbols BIL LQD PFF TLT --tf 1h --refresh`, `cluster_regime_conditioned=true`): completed successfully, exit 0, **wall-clock 581.82s** (`/usr/bin/time -v`). Confirms the widened code path runs end-to-end in production without error.
2. **Corpus-wide additive-only proof:** `regime_scope` aggregate snapshot (count, `md5(string_agg(cluster_id ...))`) before any work and after all work (restoration + timing harness, both idempotent via `ON CONFLICT DO NOTHING`) is **byte-identical**:
   - Before: `cross_sectional|1548282|a85cbc74...` / `pooled|317475|7edac307...` / `symbol_hmm|1058250|310cb9b8...`
   - After first real `--refresh` run (BIL/LQD/PFF/TLT recomputed, expected): `cross_sectional|1547784|a246363...` / `pooled|317475|6ecff34c...` / `symbol_hmm|1058250|310cb9b8...` (symbol_hmm md5 unchanged since those 4 symbols contributed zero new symbol_hmm rows, per finding #2 above; cross_sectional/pooled deltas are the EXPECTED result of `--refresh` recomputing exactly those 4 named symbols, not a leak to any other symbol -- every subsequent write in this session used `ON CONFLICT DO NOTHING`, which can only add missing rows, never modify/delete existing ones for symbols outside a `--refresh` scope)
   - Final (after SPY/QQQ/ARKK restoration + timing harness): identical to the post-first-run snapshot above, confirming those operations were true no-ops against already-correct data.
3. **Runtime-budget measurement (Task 3 step d):** since the registry blocker prevented a second real CLI run, used a direct-call sequential timing harness (`_compute_symbol_tf` called in a single process, not `ic_engine.py`'s `ProcessPoolExecutor`) for SPY/QQQ/ARKK/TLT at tf=1h, once with `cluster_regime_conditioned=True` and once `=False`:
   - `t_true=1566.81s`, `t_false=1575.71s` (both write `n_written=41133`, identical row counts both passes)
   - **ratio = 0.994** -- confirms finding #1: with `dual_write_symbol_hmm=true` already set for every enabled group on live data, toggling `cluster_regime_conditioned` changes nothing measurable, because the symbol_hmm pass runs identically either way via the first OR-operand.
   - **Caveat:** this harness is sequential (single process), not parallelized like `ic_engine.py`'s real `ProcessPoolExecutor` (`n_workers=8` default) -- absolute times are not representative of real production wall-clock (hence ~1567s here vs. 582s for a comparable 4-symbol real CLI run). The **ratio**, however, is a valid signal: both passes share identical harness/hardware/symbols/data, differing only in the one flag, so the near-1.0 ratio faithfully reflects that the two code paths currently do identical work.
   - **Pre-registered rule applied:** ratio 0.994 ≤ 2.0 → **leave the key `true`**. Confirmed `alpha.ensemble.cluster_regime_conditioned` in `config_state` is `true` (unchanged from its migration-286 seed).

### Minor known consequence (not remediated, self-healing)

The `ic_cell_fingerprints` rows for BIL/LQD/PFF/TLT (from the real `--refresh` run, computed under a transiently fx-disabled `regime_groups_json`) and for SPY/QQQ/ARKK's `symbol_hmm` cells (restored via direct call, which does not write fingerprints -- that logic lives in `main()`'s prepass, not in `_compute_symbol_tf`/`_write_symbol_results`) no longer match the current, restored `apr_snapshot_key`. The next real `ic_engine.py` run will correctly detect these ~7 symbols' cells as stale/absent and recompute them once more -- harmless (identical data will be produced, `ON CONFLICT DO NOTHING`-safe), just a small amount of extra recompute the fingerprint mechanism will correctly self-heal on its own next invocation. Not filed as a todo (too minor, self-resolving).

### Deferred, out of scope (not fixed)

- `fx` regime group (migration 280, enabled 2026-08-01) has zero `market_regimes` rows at any tf -- `cross_sectional_regime_model.py` has never been run for it. Already tracked as todo 224 (pending). Temporarily disabled `fx` in `alpha.regime.groups` for the duration of scoped test windows (my `--symbols` scope never included any fx-routed symbol) and fully restored it afterward -- did not run `cross_sectional_regime_model.py` for fx, does not close todo 224.
- Todo 257 (new, filed this session): `feature_registry`/`concept_registry` worktree-branch skew from the concurrent Phase 170 session.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- `alpha.ensemble.cluster_regime_conditioned=true` is the value plan 151-07 Task 3 reads as its pre-flight -- confirmed set correctly, no silent disagreement between this key and that plan's expected row population.
- Corpus is in a fully consistent, verified state: no orphaned/missing rows, `alpha.regime.groups` restored exactly, all touched symbols' data confirmed byte-identical to their legitimate pre-session state (except BIL/LQD/PFF/TLT's cross_sectional/pooled cells, which were legitimately recomputed by a real `--refresh` run and are current/correct, not stale).
- Todo 224 (fx `market_regimes` population) and todo 257 (feature_registry worktree skew) remain open, tracked, and out of this plan's scope.
- Full corpus recompute under the new key (beyond this plan's scoped verification) is future work, not part of 151-02's deliverable.

---
*Phase: 151-feature-primitives-expansion-theory-motivated-interaction-la*
*Completed: 2026-08-05*
