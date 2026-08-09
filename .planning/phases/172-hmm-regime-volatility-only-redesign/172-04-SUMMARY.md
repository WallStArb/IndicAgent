---
phase: 172-hmm-regime-volatility-only-redesign
plan: 04
subsystem: batch
tags: [hmm, regime-labeling, regime_writer, gaussian-hmm, walk-forward, cli-dispatch]

# Dependency graph
requires:
  - phase: 172-hmm-regime-volatility-only-redesign
    plan: 02
    provides: "migration 307 schema/APR/CVR foundation, REGIME_VOLATILITY_WRITER_OWNED_COLUMN_NAMES"
  - phase: 172-hmm-regime-volatility-only-redesign
    plan: 03
    provides: "vocabulary-parametrized _build_label_map/_state_groups_by_vocab/_alpha_history_to_regime_probs, _build_obs_matrix_volatility"
provides:
  - "_walk_forward_hmm_full(vocab=) -- vocabulary-threaded walk-forward fit, byte-identical trend output when vocab omitted"
  - "_fetch_obs_matrix_volatility -- 2-column (timestamp, close)-only OHLCV fetch for the volatility axis"
  - "_compute_symbol_tf_volatility_walk_forward -- single-cell volatility compute, same (update_rows, converged, heldout_ll) | None contract as the trend walk-forward path"
  - "_write_regime_volatility_results -- writes only the 8 regime_volatility columns via a dedicated staging table"
  - "services/regime_writer.py --regime-column {regime,regime_volatility} CLI dispatch"
affects: [172-05-gated-full-corpus-relabel]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Vocabulary-threaded shared fitting function (_walk_forward_hmm_full) reused across two label axes via a defaulted keyword parameter, not duplicated"
    - "Mutually exclusive CLI column-family dispatch (--regime-column) with a parser.error() guard enforcing an axis-specific precondition (walk-forward-only) before any DB connection opens"
    - "Positional-tuple arity/position pin via a dedicated unit test, chosen over a dataclass refactor to stay inside this plan's blast radius"

key-files:
  created: []
  modified:
    - services/regime_writer.py
    - tests/unit/services/test_regime_writer.py

key-decisions:
  - "_walk_forward_hmm_full's vocab parameter is placed after tf and defaults to None -> _TREND_VOCAB internally, so every existing positional and keyword call site (including the Gate 4 pilot scripts) reproduces today's trend output byte-for-byte, unchanged"
  - "_compute_symbol_tf_volatility_walk_forward has no momentum_window, n_restarts, or heldout_fraction parameter -- the volatility observation matrix has no momentum column, multi-seed restarts belong to the single-fit path this function does not have, and walk-forward has no single unified model whose held-out score is well-defined across segment boundaries (heldout_ll is always NaN)"
  - "_run_symbol_worker dispatches on regime_column == 'regime_volatility' FIRST, before checking walk_forward_enabled at all -- the volatility axis runs walk-forward unconditionally regardless of the alpha.hmm.walk_forward.enabled APR key's value for that invocation"
  - "--regime-column regime_volatility --no-walk-forward is a parser.error() (exit 2), not a runtime skip -- the volatility axis has no legacy corpus to protect via a soft fallback; a bare --walk-forward on a volatility run is a logged no-op, not an error, since walk-forward already runs unconditionally there"
  - "_discover_symbols's label_column is validated against a module-level frozenset before SQL interpolation, even though its only caller (main(), via an argparse choices=-constrained flag) can never pass an untrusted value -- defense-in-depth per the plan's threat model (T-172-04-SQL)"
  - "The worker args tuple grows to 20 positional elements rather than being refactored into a dataclass -- out of this phase's blast radius per the plan's own scoping; the arity/position pin (index 19 == regime_column, truncation-to-19 raises ValueError) is the chosen containment for the resulting mis-binding risk"

requirements-completed: [REQ-4]

# Metrics
duration: 30min
completed: 2026-08-09
---

# Phase 172 Plan 04: Compute + Write Path Summary

**Wired the volatility labeling path end to end for a single (symbol, tf) cell -- fetch, vocabulary-threaded walk-forward fit, and an 8-column `regime_volatility` write -- behind a new `--regime-column` CLI dispatch that writes exactly one column family per invocation and structurally cannot touch the other.**

## Performance

- **Duration:** ~30 min
- **Started:** 2026-08-09T10:45 (approx, first task commit)
- **Completed:** 2026-08-09T10:59:16-04:00
- **Tasks:** 3/3 completed
- **Files modified:** 2 (`services/regime_writer.py`, `tests/unit/services/test_regime_writer.py`)

## Accomplishments

- `_walk_forward_hmm_full` accepts an optional `vocab` parameter, defaulting to `_TREND_VOCAB`
  internally -- every pre-existing test and call site (including the Gate 4 pilot scripts)
  reproduces today's trend-path output byte-for-byte when the parameter is omitted, verified by
  an equivalence test plus a temporarily-swapped `(high, mid, low)` argument-order check
  confirmed to go red and then restored to green.
- `_fetch_obs_matrix_volatility` streams `(timestamp, close)` only (never `volume`) into the
  2-column volatility observation matrix, mirroring `_fetch_obs_matrix`'s streaming-cursor and
  logging conventions on a distinct named cursor.
- `_compute_symbol_tf_volatility_walk_forward` computes one (symbol, tf) cell's worth of
  11-element row tuples in `REGIME_VOLATILITY_WRITER_OWNED_COLUMN_NAMES` order
  (`hmm_vol_prob_calm` from `p_down`, `hmm_vol_prob_elevated` from `p_ranging`,
  `hmm_vol_prob_turbulent` from `p_up`) -- the probability-column mapping is pinned by a test
  verified to go red when `p_down`/`p_up` are swapped, then restored.
- `_write_regime_volatility_results` writes only the 8 `regime_volatility` columns through a
  dedicated `_regime_volatility_writer_staging` temp table, imported column list, and a
  `regime_column`-tagged `REGIME_WRITER_NULL_REGIME_REMAINING` gauge attribute so the two
  families' time series never conflate.
- `services/regime_writer.py --regime-column {regime,regime_volatility}` (default `regime`)
  dispatches the entire run: APR reads (volatility overrides `n_components`/`vol_window`/
  `vol_of_vol_window`/`covariance_type` from `alpha.hmm_volatility.*`, reuses every other key
  unchanged per migration 307's recorded decision), symbol discovery
  (`regime_volatility IS NULL` vs `regime IS NULL`), per-cell compute dispatch, and the write
  function -- all column-family-aware. `--regime-column regime_volatility --no-walk-forward`
  exits non-zero (`parser.error`) before any DB connection opens.
- `_run_symbol_worker`'s args tuple grows to a docstring-enumerated 20 positional elements
  (`regime_column` at index 19); a test pins the arity and position, confirming a
  truncated-to-19 tuple raises `ValueError` rather than silently mis-binding.
- Live-verified: `feature_vectors` `regime IS NOT NULL` count is unchanged at `26,791,341`
  (same value plan 172-02 recorded); `regime_volatility IS NOT NULL` count is `0` -- this plan
  built the path, no corpus rows were relabeled.

## Task Commits

Each task was committed atomically:

1. **Task 1: Thread the label vocabulary through the walk-forward fit and add the volatility fetch wrapper** -
   `96e5992b` (feat, tdd)
2. **Task 2: Single-cell volatility compute and the regime_volatility write path** -
   `62ba0486` (feat, tdd)
3. **Task 3: --regime-column dispatch, volatility APR reads, and column-aware symbol discovery** -
   `6bb05ab3` (feat, tdd)

_All three tasks are `type="auto" tdd="true"`; tests were authored alongside the implementation
in each commit and verified via manual temporary-reversion red/green cycles for every
discriminating assertion the plan's acceptance criteria named (equivalence, probability-mapping,
argument-order swaps) rather than committed as separate RED-then-GREEN commits._

## Files Created/Modified

- `services/regime_writer.py` -- `_walk_forward_hmm_full(vocab=)`, `_fetch_obs_matrix_volatility`,
  `_compute_symbol_tf_volatility_walk_forward`, `_write_regime_volatility_results`,
  `_discover_symbols(label_column=)`, `_run_symbol_worker`'s 20-element args tuple and
  volatility-first dispatch branch, `main()`'s `--regime-column` flag/guard/APR
  branch/discovery call/worker-args/write-loop dispatch. +563/-42 lines net across the plan.
- `tests/unit/services/test_regime_writer.py` -- vocab-equivalence, K=2/K=3 volatility label
  restriction, high-vol-half probability-mass tests (each with a documented swap-and-confirm-red
  verification), `_fetch_obs_matrix_volatility` shape/None/single-query/no-volume tests,
  volatility compute-function structure/mapping/K=2-elevated-zero/None-path tests, write-path
  set_cols/staging-table/query-column tests, discovery default/volatility/invalid-column tests,
  volatility dispatch and args-tuple arity/position-pin tests, a subprocess-level CLI guard
  test, and the two pre-existing dispatch-test call sites updated to append `"regime"`.
  +783/-2 lines net.

## Decisions Made

See `key-decisions` in frontmatter above -- all six are direct restatements of what the plan's
`<action>` blocks specified, recorded here because they are the load-bearing design choices
plan 172-05 (the gated full-corpus relabel) must not silently revisit.

## Deviations from Plan

None -- plan executed exactly as written. Every acceptance-criteria check specified in the plan
(signature checks, diff-scope checks, grep checks, swap-and-confirm-red verifications, the CLI
`--help`/`--no-walk-forward` checks, the live DB count checks) was run directly and passed; no
auto-fixes were required.

## Issues Encountered

- Worktree had no `.venv` (same known GSD worktree gap prior Phase 172 plans hit) --
  symlinked `/home/bg/dev/indicagent/.venv` into the worktree root, gitignored, no tracked-file
  footprint. Pre-commit hooks then ran real `ruff`/`black` via the symlinked venv on all three
  commits.
- `git merge-base` at agent startup found the worktree's spawn-time HEAD one commit behind the
  expected base (`996f60c3`, plan 172-02's post-wave-1 tracking-update commit); `git reset --hard`
  to the expected base was safe since it was a descendant of the worktree's actual HEAD, not a
  divergent history.

## User Setup Required

None -- no external service configuration required.

## Next Phase Readiness

- `regime_writer.py --regime-column regime_volatility` is a runnable, walk-forward-only labeling
  path: fetch, fit, write, all structurally incapable of touching the legacy `regime` family
  (separate compute function, separate write function, separate staging table, separate
  discovery query, separate gauge time series).
- Plan 172-05's gated full-corpus relabel can now invoke this CLI path directly -- no compute or
  write-path work remains to be built. The `alpha.hmm_volatility.*` APR defaults this plan reads
  (`n_components=3`, `vol_window=20`, `vol_of_vol_window=60`, `covariance_type=full`) are the
  same ones migration 307 seeded; plan 172-01's measured recommendation reconciliation against
  those defaults (if any adjustment is warranted) remains 172-05's job, not this plan's.
- No blockers for 172-05. `git diff services/regime_writer.py` confirms zero changes inside
  `_compute_symbol_tf`, `_write_regime_results`, `_fetch_obs_matrix`, or `_walk_forward_hmm_labels`
  across all three of this plan's commits -- the legacy trend path's live behavior is unaffected.
- Full `tests/unit/` suite green throughout (2 pre-existing, unrelated skips); `ruff check .` and
  `black --check .` clean repo-wide after every commit.

---
*Phase: 172-hmm-regime-volatility-only-redesign*
*Completed: 2026-08-09*

## Self-Check: PASSED

- FOUND: services/regime_writer.py
- FOUND: tests/unit/services/test_regime_writer.py
- FOUND: commit 96e5992b
- FOUND: commit 62ba0486
- FOUND: commit 6bb05ab3
