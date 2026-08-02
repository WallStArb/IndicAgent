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
