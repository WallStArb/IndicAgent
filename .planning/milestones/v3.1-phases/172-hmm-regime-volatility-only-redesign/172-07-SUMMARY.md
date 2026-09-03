---
phase: 172-hmm-regime-volatility-only-redesign
plan: 07
subsystem: database
tags: [ic_engine, ensemble_trainer, regime_volatility, glossary, controlled-vocabulary, config-service]

# Dependency graph
requires:
  - phase: 172-hmm-regime-volatility-only-redesign
    plan: 06
    provides: "ic_engine.py's crash-loud startup gate and per-symbol feature-matrix fetch repointed to feature_vectors.regime_volatility"
provides:
  - "Real, observed proof (not just unit tests) that a post-cutover ic_engine.py --refresh run writes feature_ic_scores rows keyed on the calm/elevated/turbulent vocabulary"
  - "A mechanical diagnosis of why 1d-timeframe symbol_hmm regime cells structurally under-produce reliable rows today (min_reliable_n/subsample_min_stride vs thin post-relabel coverage), independent of the phase 172 cutover itself"
  - "Regression test proving ensemble_trainer.py's stratum source is cross-sectional POOLED IC and requires no repoint"
  - "docs/foundation/glossary.md's regime entry rewritten to describe the volatility-only system, standing on its own"
  - "172-DOWNSTREAM-VERIFICATION.md recording both halves with real numbers"
affects: [172-phase-completion, todo-285-full-scope-verification]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Source-inspection regression tests (inspect.getsource + regex block extraction) for pinning a downstream consumer's independence from a repointed upstream column, extending plan 172-06's established pattern"
    - "Behavioral drive-through-the-real-function test (not just source grep) as the strongest tier of regression proof: calling _process_stratum() twice with identical synthetic data and only the regime label varied"

key-files:
  created:
    - tests/unit/services/test_ensemble_trainer_regime_source.py
    - .planning/milestones/v3.1-phases/172-hmm-regime-volatility-only-redesign/172-DOWNSTREAM-VERIFICATION.md
    - .planning/milestones/v3.1-phases/172-hmm-regime-volatility-only-redesign/evidence/172-07-ic-refresh-scoped.json
  modified:
    - docs/foundation/glossary.md
    - .planning/corpus_manifests/ic_engine.json

key-decisions:
  - "Widened the scoped smoke test from the plan's literal 4 symbols (SPY/QQQ/IWM/GLD at 1d) to 5, adding XLF, after the primary 4 produced zero symbol_hmm rows for a mechanical reason (stride-adjusted independent-sample count below alpha.ic.min_reliable_n=100 for every one of their regime buckets) -- XLF's turbulent bucket (527 raw rows, the corpus's largest labeled-1d cell) was the only one confirmed in advance to clear the floor, and adding it produces a real observed proof point rather than settling for a diagnosed-but-unproven claim"
  - "Fixed two pre-existing, phase-172-unrelated data-authoring gaps (EWZ and FXA each matching two enabled alpha.regime.groups tag_filters, raising AmbiguousRegimeGroupError on every ic_engine.py invocation regardless of scope) via the config's own documented exclude_symbols carve-out, applied through ConfigService.set() with a full config_history audit trail rather than a raw SQL UPDATE"
  - "Flagged two defects in the plan's own automated verify scripts rather than silently working around them: Task 1's >=2-distinct-asset-class assertion (unsatisfiable -- all 80 relabel-eligible symbols are asset_class=equity) and Task 3's whole-file em-dash-count-must-stay-identical assertion (unsatisfiable once em dashes are actually removed from an entry that had them before this task, per the plan's own explicit no-em-dash instruction)"

requirements-completed: [REQ-7]

# Metrics
duration: ~50min (resumed session; original session hit a usage-limit interruption mid-Task-1 investigation, see Deviations)
completed: 2026-08-09
---

# Phase 172 Plan 07: Downstream Re-Verification + Glossary Rewrite Summary

**A real scoped `ic_engine.py --refresh` run wrote 876 `feature_ic_scores` rows carrying `regime_scope='symbol_hmm', regime='turbulent'` (XLF, 1d) after diagnosing why the plan's originally-specified 4-symbol scope produced zero such rows; `ensemble_trainer.py`'s independence from the per-symbol regime column is now pinned by a 9-test regression suite including one test that drives the real stratum-processing function end-to-end; and the glossary's `regime` entry now describes the volatility-only system that exists, with its null-arm rationale stated in its own words.**

## Performance

- **Duration:** ~50 min of visible tool-call work in this resumed session (commits span 16:13:41-16:31:15 local); the two real `ic_engine.py` batch runs alone accounted for 510.52s (352.55s + 157.97s) of that. The session was interrupted mid-Task-1 by a usage-limit reset and resumed from a coordinator message with no commits yet landed -- total wall-clock across both session halves is not a clean single span; see Deviations.
- **Started:** 2026-08-09T19:40:00Z (approx, first `ic_engine.py --dry-run-validity` invocation, pre-interruption)
- **Completed:** 2026-08-09T20:31:15Z
- **Tasks:** 3/3 completed
- **Files modified:** 5 (1 evidence JSON, 1 corpus manifest, 1 new test file, 1 new verification doc, 1 glossary doc)

## Accomplishments

- **Task 1:** Ran a real, scoped `ic_engine.py --refresh` smoke test. Before launching, hit and fixed
  a genuine pre-existing blocker unrelated to this phase: `EWZ` and, after a full-universe
  ambiguity re-scan, `FXA` each matched two enabled `alpha.regime.groups` tag filters
  (`AmbiguousRegimeGroupError`), which fires on *any* `ic_engine.py` invocation regardless of
  `--symbols` scope since the ambiguity check runs over the whole `instrument_tags` universe
  before scoping. Fixed via the config's own documented `exclude_symbols` carve-out (already used
  for `AMLP`/`GDX`/`OIH`/`XLE`/`XOP`), applied through `ConfigService.set()` with a real
  `config_history` audit trail (versions 11, 12), not a raw `UPDATE`. Ran the primary scope
  (`SPY`, `QQQ`, `IWM`, `GLD` at `1d`, `--training-window-end 2025-12-24T05:15:00Z`, `--refresh`)
  and it committed successfully (28,956 rows, elapsed 352.55s) -- but produced **zero**
  `symbol_hmm`-scope rows despite per-symbol clustering visibly running against all three
  volatility regimes for every symbol. Diagnosed mechanically rather than accepting it as an
  unexplained gap: `alpha.ic.min_reliable_n=100` combined with `alpha.ic.subsample_min_stride=5`
  requires roughly 500+ raw regime-labeled rows in a cell before the stride-adjusted independent
  sample count clears the floor, and every one of the four symbols' three regime buckets (measured
  directly: SPY calm=177/elevated=18/turbulent=57 down to QQQ's largest at 365) fell short. Rather
  than report a diagnosed-but-unproven finding, added `XLF` (the single highest-labeled-row-count
  `1d` cell in the full 172-05 evidence, 1008 rows) as a fifth, cheap supplementary run
  specifically because its `turbulent` bucket (527 raw rows) was the only one across all 44 labeled
  `1d` cells confirmed in advance to clear the floor -- and it did: 876 real rows now carry
  `regime_scope='symbol_hmm', regime='turbulent', reliable=true`. Built
  `evidence/172-07-ic-refresh-scoped.json` covering the full 5-symbol scope with `run_type:
  smoke_test`, the symbol-selection rationale (including the corpus-wide 100%-equity
  asset-class finding), before/after row counts, distinct regimes, and regime_scope breakdown.
  Confirmed zero rows anywhere in scope carry a retired trend label, confirmed the one
  `symbol_hmm` code (`turbulent`) is CVR-registered, confirmed `cross_sectional`-scope rows
  correctly still carry `market_regimes` labels (not a leak), and confirmed zero orphaned
  `ic_engine.py` processes after both runs.
- **Task 2:** Wrote `tests/unit/services/test_ensemble_trainer_regime_source.py` (9 tests, all
  passing) pinning that `ensemble_trainer.py`'s stratum source is cross-sectional POOLED IC in
  `feature_ic_scores` (`symbol='POOLED' AND is_pooled=true AND regime != '_pooled'`), never
  `feature_vectors.regime`/`.regime_volatility`. Combined source-inspection tests (extracting the
  real strata-discovery SQL and `_process_stratum`'s query blocks via `inspect.getsource` + regex,
  confirming no reference to `feature_vectors`/`regime_volatility`/`regime_scope` in the strata
  query and no literal comparison against any of 8 known regime label strings anywhere in
  `_process_stratum`) with one genuinely behavioral test: drove the real `_process_stratum()`
  end-to-end twice with byte-identical synthetic IC/feature data, varying only the regime label
  (`'trending_up'` vs `'calm'`), and asserted the resulting `ensemble_weights` AND `ensemble_alpha`
  INSERT rows are identical except for the regime field itself. Verified the mutation-test
  acceptance criterion manually: temporarily removed the `regime != '_pooled'` clause from
  `_eligibility_where()`, confirmed the relevant test went red, restored the clause, confirmed
  green again -- `services/ensemble_trainer.py` itself carries zero diff. Wrote
  `172-DOWNSTREAM-VERIFICATION.md` with both required sections.
- **Task 3:** Rewrote `docs/foundation/glossary.md`'s `### regime` entry's idiosyncratic bullet
  to describe the 2-dimensional (`realized_vol`, `vol_of_vol`) observation vector, `K` from
  `alpha.hmm_volatility.n_components`, `calm`/`elevated`/`turbulent` vocabulary, walk-forward
  expanding-window fit, and `feature_vectors.regime_volatility` storage -- with the null-arm
  rationale (+0.6 real-vs-null margin for realized volatility vs. a margin indistinguishable from
  zero for trend) stated in the entry's own words, no reference to `171-FINAL-VERDICT.md` or any
  `.planning/` path. Resolved the `volatility_regime` disambiguation collision by pointing it at
  `idiosyncratic regime` instead of defining a second overlapping concept. Updated the `Code
  surface` line (`feature_vectors.regime_volatility`, `regime_writer.py --regime-column
  regime_volatility`, `cross_sectional_regime_model.py` replacing the stale
  `equity_regime_model.py`), `regime_group`'s contrast paragraph, `conditioning layer`'s Code
  surface line, and `regime classifier`'s implementations list (found via
  `grep -n 'feature_vectors\.regime\b'`) to match. Confirmed the `**Banned:**` line is
  byte-identical to its pre-edit value via `git show` diff.

## Task Commits

Each task was committed atomically:

1. **Task 1: Scoped ic_engine --refresh smoke test** - `90ca0dc4` (chore; amended from an
   initial `test(...)` typing to `chore(...)` before finalizing)
2. **Task 2: Pin ensemble_trainer's stratum source with a regression test** - `41602c1a` (test)
3. **Task 3: Rewrite the regime glossary entry** - `c8ee00e5` (docs)

## Files Created/Modified

- `.planning/milestones/v3.1-phases/172-hmm-regime-volatility-only-redesign/evidence/172-07-ic-refresh-scoped.json` -
  smoke-test evidence for the 5-symbol (SPY/QQQ/IWM/GLD/XLF) 1d scope: before/after row counts,
  distinct regimes, regime_scope breakdown, symbol-selection rationale including the corpus
  asset-class-composition finding.
- `.planning/corpus_manifests/ic_engine.json` - refreshed from the real XLF run (status=success,
  1,091,788 total rows), mirroring plan 172-06's precedent of committing this tool-managed
  artifact when a real run changes it.
- `tests/unit/services/test_ensemble_trainer_regime_source.py` - new file, 9 tests: 2 on
  `_eligibility_where()`'s live return value, 2 source-inspection on the strata-discovery query,
  3 source-inspection on `_process_stratum`, 2 behavioral (drives the real function end-to-end).
- `.planning/milestones/v3.1-phases/172-hmm-regime-volatility-only-redesign/172-DOWNSTREAM-VERIFICATION.md` -
  new file, both required sections with real numbers.
- `docs/foundation/glossary.md` - `### regime` entry rewritten; `regime_group`, `conditioning
  layer`, `regime classifier` entries updated to match; `**Banned:**` line unchanged.

## Decisions Made

See `key-decisions` in frontmatter. Load-bearing for downstream work:

- The scoped smoke test's real proof point (XLF's 876 `turbulent` rows) came from a
  deliberately-added 5th symbol, not the plan's literal 4-symbol list -- the 4-symbol scope's
  own result (zero `symbol_hmm` rows, precisely diagnosed) is preserved in the evidence and
  SUMMARY as a legitimate finding in its own right, per the plan's own "zero rows is a finding,
  not a pass" framing.
- `alpha.regime.groups`'s `exclude_symbols` carve-out now also covers `EWZ` and `FXA` (config
  versions 11, 12) -- a real, durable fix to a genuine pre-existing gap, not scoped to this
  plan's own symbols; any future `ic_engine.py` run against the full universe benefits.
- Two automated-verify-script defects were flagged in the SUMMARY/evidence rather than silently
  patched or worked around: they encode assumptions (>=2 distinct asset classes exist in this
  corpus; the whole glossary file's em-dash count must stay unchanged even when the task's own
  instruction is to remove em dashes from the entry being rewritten) that are factually
  unsatisfiable given the real corpus/document state. Both are documented with the exact
  numbers so a future editor of these plan artifacts can see the contradiction directly.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking issue] `EWZ` and `FXA` each matched two enabled `alpha.regime.groups`, blocking every `ic_engine.py` invocation**
- **Found during:** Task 1, first `--dry-run-validity` attempt
- **Issue:** `EWZ` carries both an `intl_em` tag (matches the `equity` group's `intl_*` prefix)
  and a `commodity_broad` tag (matches the `commodity` group's exact-tag list),
  raising `AmbiguousRegimeGroupError` -- this check runs over the full `instrument_tags`
  universe before any `--symbols` scoping, so it blocked the scoped run entirely, not just a
  run touching EWZ. Fixed via `exclude_symbols`, re-ran the ambiguity check across the whole
  universe, and found `FXA` was the one remaining ambiguous symbol (`commodity_broad` vs.
  `fx_commodity`/`fx_*`), fixed the same way.
- **Fix:** Added both symbols to the `commodity` group's `exclude_symbols` list via
  `ConfigService.set()` (versions 11, 12), mirroring the existing carve-out for
  `AMLP`/`GDX`/`OIH`/`XLE`/`XOP`. Re-ran the full-universe ambiguity scan afterward: 0
  ambiguous symbols remain.
- **Files modified:** none (a `config_state`/`config_history` DB write, not a code or migration
  change -- `alpha.regime.groups` is an APR key, and this is exactly the sanctioned
  human-precedented use of its `exclude_symbols` field)
- **Commit:** n/a (DB config change, not itself committed to git; recorded in `config_history`
  with `changed_by='gsd-executor-172-07'` and a full reason string)

**2. [Rule 2 - auto-add missing critical functionality, applied to evidence-gathering, not code] Added a 5th symbol (XLF) after the primary 4-symbol scope produced zero symbol_hmm rows**
- **Found during:** Task 1, after the primary run completed successfully but with 0
  `symbol_hmm`-scope rows
- **Issue:** The plan's central Purpose ("prove a real `feature_ic_scores` row now carries
  `calm` instead of `ranging`") was not demonstrated by the literally-specified 4-symbol/1d
  scope -- every regime bucket across all 4 symbols fell short of the reliability floor after
  stride subsampling, a mechanical, well-understood, non-cutover-code reason, but still a gap
  against the plan's own stated purpose.
- **Fix:** Computed (from `evidence/172-05-relabel-coverage.json` and direct DB queries) which
  of the 44 labeled `1d` cells corpus-wide had at least one regime bucket large enough to clear
  the floor, found exactly one (`XLF`'s `turbulent` bucket, 527 raw rows), and ran it as a
  cheap, additional, clearly-labeled supplementary check. Produced 876 real proof-point rows.
- **Files modified:** `evidence/172-07-ic-refresh-scoped.json` scope widened to 5 symbols with
  the rationale documented inline; `172-DOWNSTREAM-VERIFICATION.md`'s Scoped ic_engine refresh
  section states both the primary-scope finding and the supplementary XLF proof explicitly.
- **Commit:** `90ca0dc4`

---

**Total deviations:** 2 (1 blocking-issue config fix, 1 evidence-scope widening to satisfy the
plan's own stated purpose). Neither touched `services/ic_engine.py`,
`services/ensemble_trainer.py`, or any migration.
**Impact on plan:** Both were necessary to complete Task 1 honestly -- the config fix because
the run could not execute at all otherwise, the XLF addition because the plan's own Purpose
paragraph would otherwise have gone unmet by a technically-passing-but-empty smoke test.

## Known Plan-Script Defects (flagged, not silently patched)

**1. Task 1's automated verify script asserts `len({asset_class values}) >= 2`.** Unsatisfiable:
all 80 symbols in the 172-05-labeled corpus (and, checked separately, in the entire relabel-
eligible universe) carry `instruments.contract_details->>'asset_class' = 'equity'`. The DB does
have `futures`/`fx` rows (22 symbols, confirmed by direct query), but none are part of this ETF
corpus or its relabel. All 8 other assertions in the script pass; only this one is structurally
unreachable. The plan's own prose acceptance criterion explicitly allows this outcome when
documented ("The scope spans at least three distinct asset classes, or the SUMMARY records how
many asset classes had labeled 1d cells and why fewer were used") -- this SUMMARY and the
evidence JSON's `scope.note`/`symbol_selection_rationale` do exactly that.

**2. Task 3's automated verify script asserts the whole-file em-dash count stays identical
pre/post-edit.** Contradicts the same task's own explicit prose instruction ("no em dashes").
The `regime` entry carried 11 em dashes before this task; rewriting it per instruction removes
all 11, dropping the whole-file count from 186 to 175. Verified precisely that this is the only
source of the delta: the `regime_group`/`conditioning layer`/`regime classifier` entries, each
touched only by a single surgical clause replacement, keep their pre-existing counts (7/4/0)
unchanged. Zero em dashes remain within the rewritten `regime` entry itself, and zero new ones
were introduced anywhere else in the document.

Neither defect was corrected in the plan file itself (out of scope for an executor to edit its
own acceptance bar mid-run); both are recorded here with exact numbers for whoever next revises
these verify blocks.

## Issues Encountered

**Session interruption mid-Task-1.** The original session hit a usage-limit reset while
investigating the `AmbiguousRegimeGroupError` (had identified the CVR codes and confirmed the
error, not yet applied the `exclude_symbols` fix). Resumed from a coordinator message
confirming no commits had landed yet (`git log` still at the wave-4 merge tip, `e80870d3`) and
that `.planning/corpus_manifests/ic_engine.json`'s uncommitted diff was the expected artifact
of the failed dry-run attempt. Continued from exactly that point -- applied the `EWZ` fix, found
and fixed `FXA` via a fresh full-universe scan, then proceeded through the rest of Task 1 and
all of Tasks 2-3 without further interruption. No work was lost or duplicated; the pre-fix
`AmbiguousRegimeGroupError` log lines are visible in `logs/ic_engine.log`'s history as
expected artifacts of that investigation, not re-triggered.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Phase 172's downstream re-verification is complete: a real post-cutover `ic_engine.py`
  run has been observed writing volatility-keyed `feature_ic_scores` rows (not just passing
  unit tests), `ensemble_trainer.py`'s independence from the repointed column is proven by a
  regression test that would catch a future inversion, and the canonical glossary entry now
  matches the shipped system.
- **Full-scope corpus verification remains open, tracked as pending todo 285** -- this plan's
  smoke test proves the cutover mechanism works on sampled cells; it does not and was not meant
  to establish correctness across the full 80-symbol/4-timeframe corpus.
- **New, corpus-wide-relevant finding for whoever picks up todo 285 or any future `1d`-cadence
  regime-stratified IC work:** `1d` timeframe symbol_hmm cells need roughly 500+ raw
  regime-labeled rows in a single bucket to clear `alpha.ic.min_reliable_n=100` after
  `alpha.ic.subsample_min_stride=5` subsampling. Given 172-05's current relabel coverage (a few
  hundred rows per symbol per bucket for most of the 80-symbol corpus, per the per-symbol
  min/max labeled date ranges observed during this plan's investigation), most `1d` symbol_hmm
  cells will likely under-produce reliable rows the same way SPY/QQQ/IWM/GLD did here -- this is
  not a phase 172 defect, but it is a real constraint on what a full-scope `1d` verification
  pass can expect to see, worth surfacing to todo 285 explicitly rather than being rediscovered
  cell-by-cell.
- No blockers. Phase 172's plan sequence (07/07) is complete.

---
*Phase: 172-hmm-regime-volatility-only-redesign*
*Completed: 2026-08-09*

## Self-Check: PASSED

- FOUND: .planning/milestones/v3.1-phases/172-hmm-regime-volatility-only-redesign/evidence/172-07-ic-refresh-scoped.json
- FOUND: .planning/milestones/v3.1-phases/172-hmm-regime-volatility-only-redesign/172-DOWNSTREAM-VERIFICATION.md
- FOUND: tests/unit/services/test_ensemble_trainer_regime_source.py
- FOUND: docs/foundation/glossary.md
- FOUND: commit 90ca0dc4
- FOUND: commit 41602c1a
- FOUND: commit c8ee00e5
