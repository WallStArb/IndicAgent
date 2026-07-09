---
title: Investigate 33 pre-existing HMM causal-decode / regime-writer test failures
status: completed
discovered_by: phase-142A (142A-01 execution)
discovered: 2026-07-02
resolved: 2026-07-08
---

**Resolved 2026-07-08:** all three subsets in this todo's final scope are now closed.

- `test_regime_writer.py` / `test_causal_hmm_decoding.py` (14 failures): do NOT reproduce.
  `pytest tests/unit/test_causal_hmm_decoding.py tests/unit/test_regime_writer.py
  tests/unit/services/test_regime_writer.py` → 39 passed, 1 skipped. Root cause was a test
  signature mismatch, already fixed by commit `771324d9` ("fix(143-01): update
  test_causal_decode for _alpha_pass signature") before this todo's 2026-07-08
  "re-confirmed live" note was written — that note was stale, not current at the time it was
  added. No numeric/JIT precision drift; the regime-label correctness concern this todo raised
  does not hold.
- `test_fetch_htf_bars.py` (3 failures): fixed today — stale module path
  (`scripts.debug.replay.debug_fetch_htf_bars` → `scripts.infrastructure.backfill.infrastructure_fetch_htf_bars`).
- `test_roll_batch.py` (1 failure): fixed today — not a stale fixture as suspected, a real bug:
  `detect_rolls()` in `ops_roll_batch.py` failed to pass `ref_year`/`ref_month` through to
  `derive_roll_chain()`, silently falling back to wall-clock "now" instead of its own `today`
  argument. Fixed in `ops_roll_batch.py`; test updated to the now-correct expected values.
- `test_run_historical_pipeline.py` (14 failures): covered by todo 062 (also resolved today).

## What

**Scope narrowed 2026-07-08:** the `test_run_historical_pipeline.py` subset (14 failures,
stale `production.scripts.run_historical_pipeline` mock patch paths from a since-completed
scripts reorg) is now fully diagnosed with a concrete fix, tracked separately as todo 062 —
don't duplicate that work here. **Re-confirmed live 2026-07-08** (full `tests/unit/` run,
`git stash` comparison): the `test_regime_writer.py`/`test_causal_hmm_decoding.py` subset (14
failures) still reproduces identically, still pre-existing, still unexplained by anything in
this session's changes. This todo's remaining scope is that subset plus
`test_fetch_htf_bars.py`/`test_roll_batch.py` (4 more, likely unrelated causes — a missing
debug module and a date-dependent contract-roll assertion respectively; worth splitting into
their own todos if this is ever picked up rather than treating all ~18 as one investigation).

**Why the regime_writer/causal_hmm subset matters more than "pre-existing test failure"
suggests:** if this really is numeric/JIT precision drift in `regime_writer.py`'s causal
decode path (as suspected below), it means the per-symbol HMM regime labels
(`feature_vectors.regime`) — one of the two live regime systems, and the exact machinery
central to today's Phase 144 conditioning decision
(`docs/research/fable-2026-07-07-phase144-conditioning-decision.md`) — may already be
computing degraded output in production, silently. Worth prioritizing the bisect below over
its current P3-adjacent treatment, given that connection.

33 test failures originally discovered running the full `tests/unit/` suite during Phase 142A
execution (post-merge gate, confirmed reproducible twice — identical failure set
before and after merging plan 142A-01). Confirmed via `git diff --stat` against
these files that none were touched by 142A-01's commits — pre-existing on `main`
at `8cd562f6`, not caused by any recent phase.

Full breakdown logged in
`.planning/phases/142A-ensemble-ic-measurement-planned/deferred-items.md`.

**Affected files (original 33; see narrowing note above for current scope):**
- `tests/unit/scripts/test_fetch_htf_bars.py` (3 failures)
- `tests/unit/scripts/test_roll_batch.py` (1 failure)
- `tests/unit/scripts/test_run_historical_pipeline.py` (14 failures — now todo 062's scope)
- `tests/unit/services/test_regime_writer.py` (8 failures)
- `tests/unit/test_causal_hmm_decoding.py` (6 failures)
- `tests/unit/test_regime_writer.py` (1 failure)

**Suspected cause:** HMM causal-decode numeric/JIT precision drift — test names
reference `causal_decode_vectorized_matches_original`, `causal_pre_switch_bars_consistent`,
`causal_is_truly_causal`. Likely an environment-level numeric or Numba JIT precision
issue in `regime_writer.py`'s causal decode path, not a logic regression from any
specific phase.

## Why it matters

`regime_writer.py` feeds the per-symbol HMM regime labels (`feature_vectors.regime`)
used as one of two live regime systems (see MEMORY.md Dual Regime System). If the
causal decode path is numerically drifting, downstream regime-stratified IC
measurements (including Phase 142A's ensemble IC engine) could be silently
consuming degraded regime labels in production, even though this specific test
suite run isn't blocking on it.

## Suggested approach

- Bisect when these started failing (`git log -- services/regime_writer.py` +
  rerun suite at a few historical commits) to rule in/out a recent numpy/numba/
  scipy dependency bump vs. a long-standing environment issue.
- Compare local vs CI test environment (numba JIT caching, BLAS backend) if the
  failures are non-deterministic across machines.
