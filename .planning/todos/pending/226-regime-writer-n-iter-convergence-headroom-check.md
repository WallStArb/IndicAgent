---
status: pending
priority: P2
filed: 2026-08-02
source: throughput brainstorm following todo 216's BLAS thread-cap fix -- todo 216 found
  zero hmm_not_converged_retry cells across 244 fits (clean convergence), but never
  checked how far under the n_iter=200 cap those fits actually landed
---

# `regime_writer.py`'s `GaussianHMM(n_iter=200)` cap may be far above actual convergence
# -- check before assuming 200 is load-bearing

## Status

**step 1 DONE 2026-08-02** — log call added (commits 5c86ffeb, 7a0d7de1); measurement instrumentation ready for live corpus run.

**Step 2 partial data 2026-08-05**: this todo's own premise ("todo 216 found zero
hmm_not_converged_retry cells across 244 fits") is exactly the tautology todo 229
exposed -- the retry path was structurally unreachable before that fix landed, so
"zero retries" never meant "clean convergence." Ran a small read-only sample
(8 symbols x {1h,1d}, `_compute_symbol_tf` called directly, zero DB writes) AFTER
todo 229's fix landed, using the live APR n_iter=200 (**note: the live corpus's
actual `feature.hmm.n_iter` value is 200, but 2 of these 15 cells logged
`n_iter_cap=400`** -- QQQ/1h and XLE/1h genuinely hit the 200 cap on their first
fit and the now-functional retry kicked in at n_iter*2=400, converging at
236/260 iterations. First live confirmation the retry path actually fires and
works, not just synthetic unit test coverage).

Results (15 measured, 1 skipped -- RSP/1h returned None, likely occupation-gate
or insufficient-data, not investigated further):
- 13/15 cells converged well under 200 (range 72-131 iterations, i.e. 36-65% of cap)
- 2/15 cells (QQQ/1h, XLE/1h) needed the retry, converging at 236/260 -- OVER the
  original 200 cap, under the doubled 400
- 0/15 hit the final (possibly-doubled) cap without converging

**Revised read**: n_iter=200 is NOT uniformly oversized the way this todo's title
assumed -- most cells have real headroom, but a real minority of cells (~13% in
this small sample) need MORE than 200 to genuinely converge, and would have been
silently mislabeled "converged" at a hard cap-hit before todo 229's fix. Lowering
the cap based on the majority's headroom would push more cells into needing the
retry -- fine now that retry is real, but the case for lowering the default is
weaker than the todo's original framing suggested. Sample is small (8 symbols,
2 tfs, no 5m/15m -- excluded from this pass since a single 5m HMM fit on ~20yr of
data takes minutes even with BLAS capped to 1 thread, todo 216's finding) and not
authoritative -- a real full-corpus measurement (all symbols x all tfs) is still
needed before any cap change, per this todo's own "don't change n_iter blind" rule.
Leaning toward: don't lower the cap without much more data; the retry mechanism
existing (and now working) is doing real work, not just a safety net that never
fires.

## Problem

Todo 216 (BLAS thread cap, closed 2026-08-02) found that all 244 successful HMM fits in
the last full corpus run converged cleanly -- zero cells hit the documented
same-seed-retry-at-`n_iter*2` path. That refutes "retries inflate cost," but nobody has
checked the complementary question: of the 200 iterations allowed, how many did each
fit actually use? `hmmlearn`'s `GaussianHMM` exposes `monitor_.iter` (or equivalent)
after `.fit()` -- if the real distribution is e.g. mean 40 / p99 90, the 200 cap is
pure wasted EM-iteration cost on every cell, not a safety margin.

## What to do

Next time `regime_writer.py --refit` runs (or a dedicated small-N dry run), log
`model.monitor_.iter` per (symbol, tf) cell alongside the existing convergence-retry
counter. If the distribution shows real headroom (e.g. p99 well under 200), lower the
cap via `alpha.hmm.n_iter` (check it's already an APR key -- if not, that's itself an
APR migration violation per CLAUDE.md's migrate-as-you-go rule) to something like
p99 + 20% margin, re-verify Viterbi output is unaffected on a held-out sample (same
byte-identical check todo 216 already did at thread=1 vs thread=24 -- do the same
comparison at n_iter=200 vs the proposed lower cap), and re-run a full corpus pass to
confirm.

**Do NOT change n_iter blind.** This is a measure-first todo, same discipline as todo
215/216 -- no fix without a profile in hand.

## Constraint

`HMM_RANDOM_STATE = 42` / n_iter are both APR-governed, load-bearing values --
[[project_hmm_improvement_decisions]] and CLAUDE.md's Phase 138 section: changing either
invalidates all `feature_ic_scores` and requires a full re-run. Frame this as a
one-time, deliberate re-run, not a casual tune.

## Sizing

Small measurement step (add one log line, read it after one run) + a contingent full
re-run only if the data justifies changing the cap. Don't size the re-run until the
headroom is actually confirmed.
