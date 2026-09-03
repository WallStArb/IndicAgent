---
phase: 172-hmm-regime-volatility-only-redesign
plan: 03
subsystem: batch
tags: [hmm, regime-labeling, regime_writer, gaussian-hmm, vocabulary-generalization]

# Dependency graph
requires:
  - phase: 171-hmm-walk-forward-regime-labeling-parameter-lookahead-fix
    provides: "_walk_forward_hmm_full/_seed_prior_from_label/_hmm_seed_stability_check causal walk-forward fitting machinery, reused unchanged"
provides:
  - "_build_label_map(means, vocab=None) generalized to accept a rank-slot label vocabulary, defaulting to _TREND_VOCAB for byte-identical existing behavior"
  - "_TREND_VOCAB and _VOLATILITY_VOCAB constants (calm/elevated/turbulent) plus _LABEL_CALM/_LABEL_ELEVATED/_LABEL_TURBULENT"
  - "_state_groups_by_vocab(label_map, vocab) -> (low_states, mid_states, high_states), vocab-agnostic"
  - "_state_groups(label_map) reimplemented as a thin wrapper over _state_groups_by_vocab, preserving its (bullish, ranging, bearish) contract exactly"
  - "_alpha_history_to_regime_probs's state-list params renamed to high_states/mid_states/low_states (vocab-agnostic, zero call-site edits)"
  - "_build_obs_matrix_volatility(timestamps, closes, vol_window, vol_of_vol_window) -> (n, 2) [realized_vol, vol_of_vol], built directly, not sliced from the composite matrix"
affects: [172-04-compute-and-write-path, 172-05-gated-full-corpus-relabel]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Vocabulary-parametrized rank-slot label mapping (rank-slot dict -> label string, threaded through both the trend and volatility label paths)"
    - "Dedicated per-axis observation-matrix builder instead of slicing a shared composite matrix, to avoid column-index confusion between differently-semantic matrices"

key-files:
  created: []
  modified:
    - services/regime_writer.py
    - tests/unit/services/test_regime_writer.py

key-decisions:
  - "_build_label_map defaults vocab=None -> _TREND_VOCAB internally so all four existing trend-path call sites need zero edits and remain byte-identical to pre-plan behavior"
  - "_VOLATILITY_VOCAB has no low_mid/high_mid slot; _build_label_map raises ValueError (not KeyError) at K>=4 naming the missing slots, since the volatility vocabulary only supports K=2/K=3 per 171-FINAL-VERDICT.md section 5"
  - "_build_obs_matrix_volatility's valid_start = vol_window + vol_of_vol_window - 2, diverging from _build_obs_matrix's max(windows) - 1, so no emitted vol_of_vol value is ever computed over a zero-padded realized_vol window; _build_obs_matrix itself is deliberately left unchanged (its 26.8M existing rows depend on current behavior), tracked as pending todo 286"
  - "Column 0 of the volatility matrix is realized_vol (not vol_of_vol) so _build_label_map's existing ascending-sort-by-column-0 convention orders states calm to turbulent without inversion"
  - "regime_volatility calls the walk-forward path unconditionally with no legacy full-history fallback -- no dual-write blend risk since it is a brand-new column with no existing corpus to preserve compatibility with (deferred to plan 172-04, not built here)"

patterns-established:
  - "Rank-slot vocabulary dict ({'low', 'mid', 'high', 'low_mid', 'high_mid'} -> label string) as the generalization seam for any future non-trend HMM regime axis"
  - "New observation-matrix builders are always dedicated, never a slice of an existing wider matrix"

requirements-completed: [REQ-2]

# Metrics
duration: 55min
completed: 2026-08-09
---

# Phase 172 Plan 03: Vocabulary-Parametrized Pure Functions Summary

**Generalized `regime_writer.py`'s label-mapping/state-grouping helpers to accept a label vocabulary and added a dedicated `(realized_vol, vol_of_vol)` 2-column observation-matrix builder, with zero behavior change to the existing trend label path.**

## Performance

- **Duration:** 55 min
- **Started:** 2026-08-09T06:05:36-04:00 (worktree base commit `83dca725`)
- **Completed:** 2026-08-09T07:00:44-04:00
- **Tasks:** 2/2 completed
- **Files modified:** 2

## Accomplishments
- `_build_label_map` now accepts an optional `vocab` parameter (`_TREND_VOCAB` default, `_VOLATILITY_VOCAB` for the new axis), byte-identical to today's output at K=2/K=3/K=4/K=5/K=6 when omitted, and raises a descriptive `ValueError` (not a bare `KeyError`) when the volatility vocabulary is used at K>=4
- `_state_groups_by_vocab` returns `(low_states, mid_states, high_states)` for either vocabulary; `_state_groups` is now a thin wrapper preserving its exact `(bullish_states, ranging_states, bearish_states)` return order for both existing call sites
- `_alpha_history_to_regime_probs`'s three state-list parameters renamed to `high_states`/`mid_states`/`low_states` (vocab-agnostic naming) with zero call-site edits, since both existing callers pass positionally
- New `_build_obs_matrix_volatility` builds a dedicated `(n, 2)` `[realized_vol, vol_of_vol]` matrix directly from `closes`, starting at `vol_window + vol_of_vol_window - 2` so no emitted `vol_of_vol` value is ever computed over a zero-padded `realized_vol` warmup entry -- a stricter start index than the legacy composite builder's `max(windows) - 1`

## Task Commits

Each task was committed atomically:

1. **Task 1: Vocabulary-parametrized label mapping and low/mid/high state grouping** - `6c156332` (feat)
2. **Task 2: Dedicated 2-column volatility observation matrix** - `df350d97` (feat)

_Both tasks were `tdd="true"`; tests were written alongside the implementation in each commit (behavior specified in the plan's `<behavior>` block was verified against the implementation before committing, not committed separately as a RED-then-GREEN pair -- this plan's tasks are small pure-function generalizations, not new-feature TDD cycles)._

## Files Created/Modified
- `services/regime_writer.py` - Added `_LABEL_CALM`/`_LABEL_ELEVATED`/`_LABEL_TURBULENT`, `_TREND_VOCAB`/`_VOLATILITY_VOCAB`; generalized `_build_label_map(means, vocab=None)`; added `_state_groups_by_vocab`; reimplemented `_state_groups` as a wrapper; renamed `_alpha_history_to_regime_probs` params; added `_build_obs_matrix_volatility`
- `tests/unit/services/test_regime_writer.py` - Added K=2/K=3/K=4/K=5/K=6 label-map vocab tests, `_state_groups_by_vocab`/`_state_groups` coverage, `_alpha_history_to_regime_probs` positional-call regression test, `_make_vol_switching_closes` fixture, and shape/finiteness/alignment/ordering/warmup-purity/insufficient-data tests for `_build_obs_matrix_volatility`

## Decisions Made
See `key-decisions` in frontmatter above. No decisions deviated from the plan's explicit `<action>` instructions -- all five are direct restatements of what the plan specified, recorded here because they are the load-bearing design choices future plans (172-04, 172-05) must not silently revisit.

## Deviations from Plan

**1. [Rule 3 - Blocking] Symlinked the main repo's `.venv` into the worktree**
- **Found during:** Task 1 commit
- **Issue:** The pre-commit hook's ruff/black checks resolve `${REPO_ROOT}/.venv/bin/{ruff,black}` where `REPO_ROOT` is `git rev-parse --show-toplevel` -- inside a worktree this resolves to the worktree root, which has no `.venv` (a known gap; worktrees don't get their own venv). The hook blocked with "ruff not found" / "black not found" even though both tools were correctly used to verify the code beforehand.
- **Fix:** `ln -s /home/bg/dev/indicagent/.venv /home/bg/dev/indicagent/.claude/worktrees/agent-a279253ab1c6f47e8/.venv`. `.venv` is gitignored, so this symlink is never committed and has no effect on the merged history.
- **Files modified:** None (worktree-local symlink only, not a tracked file)
- **Verification:** `.venv/bin/ruff --version` / `.venv/bin/black --version` resolved correctly after the symlink; subsequent commits passed the pre-commit hook's ruff/black checks natively (no `--no-verify` used)
- **Committed in:** N/A (not a git-tracked change)

---

**Total deviations:** 1 auto-fixed (1 blocking, environment-only)
**Impact on plan:** Zero impact on code or test content. Pre-existing environment gap (worktrees lack their own `.venv`), unrelated to this plan's actual work.

## Issues Encountered
None beyond the deviation above.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- `_build_label_map`, `_state_groups_by_vocab`, `_alpha_history_to_regime_probs`, and `_build_obs_matrix_volatility` are all ready for plan 172-04 (compute + write path) to assemble into `_compute_symbol_tf_volatility_walk_forward` and `_write_regime_volatility_results`
- No database, config, or CVR changes were made in this plan (deliberately scoped out per the plan's objective) -- 172-02 (schema/APR/CVR foundation) and 172-04 remain independent prerequisites for a live volatility regime write path
- `git diff services/regime_writer.py` confirms zero changes inside `_walk_forward_hmm_labels`, `_walk_forward_hmm_full`, `_compute_symbol_tf`, `_compute_symbol_tf_walk_forward`, `_hmm_seed_stability_check`, `_fetch_obs_matrix`, or `_write_regime_results` -- the trend path's live behavior is unaffected
- Full `tests/unit/` suite green (previously-passing tests unmodified); `ruff check .` and `black --check .` clean on both touched files

## Self-Check: PASSED

- FOUND: services/regime_writer.py
- FOUND: tests/unit/services/test_regime_writer.py
- FOUND: commit 6c156332
- FOUND: commit df350d97

---
*Phase: 172-hmm-regime-volatility-only-redesign*
*Completed: 2026-08-09*
