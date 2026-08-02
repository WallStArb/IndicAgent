---
status: pending
priority: P1
filed: 2026-08-02
source: final whole-branch review of the todo-226-step-1 instrumentation branch
  (docs/superpowers/plans/2026-08-02-regime-writer-convergence-iteration-logging.md)
  -- reviewer flagged that the new log's `converged` field would always read `true`,
  which led to checking hmmlearn's actual `converged` semantics directly
---

# `regime_writer.py`'s same-seed HMM convergence retry (todo 108) has been
# unreachable dead code since it shipped -- `monitor_.converged` is always
# `True` after any completed `.fit()`, in hmmlearn 0.3.3

## Problem

Verified directly against the installed hmmlearn 0.3.3 source
(`hmmlearn.base.ConvergenceMonitor.converged`):

```python
@property
def converged(self):
    return (self.iter == self.n_iter or
            (len(self.history) >= 2 and
             self.history[-1] - self.history[-2] < self.tol))
```

and `BaseHMM.fit()`'s EM loop:

```python
for iter in range(self.n_iter):
    ...
    self.monitor_.report(lower_bound)
    if self.monitor_.converged:
        break
```

`report()` increments `self.iter` every call. If the loop breaks early, it's
because `converged` was already `True` (the tolerance disjunct fired). If the
loop runs to completion without breaking, `self.iter == self.n_iter` exactly,
which makes `converged` `True` via the *first* disjunct regardless of whether
the fit actually converged in any meaningful sense. **There is no code path
in hmmlearn where `.fit()` completes and `monitor_.converged` is `False`.**

`regime_writer.py:570-596` (`_compute_symbol_tf`, todo 108's multi-seed-restart
change) reads `candidate_converged = bool(candidate.monitor_.converged)` and
only enters the same-seed retry-at-`n_iter*2` branch `if not candidate_converged`.
That branch is structurally unreachable -- it has never fired and cannot fire,
regardless of whether the underlying EM fit is any good.

## Why this matters

Todo 216's closing evidence ("zero cells hit `hmm_not_converged_retry` across
244 fits -- clean convergence, not a retry-inflation artifact") is not actually
evidence of clean convergence. It's a tautology: the retry code cannot fire no
matter what the fit quality is. The same is true of every prior run that ever
logged "0 retries" -- that log line has never meant what it appeared to mean.

This also affects todo 226 (the convergence-iteration logging this review
branch just added): the new log's `converged` field will read `true` on every
single cell, including ones that hit the `n_iter` cap without real convergence.
The only trustworthy cap-hit signal in the new log is `iters_used == n_iter_cap`,
not the `converged` field -- documented as a comment at the log site in this
branch, but the deeper bug (the retry logic itself being unreachable) needs a
real fix, not just a warning comment.

## What to do

This needs a genuine EM-quality check, not `monitor_.converged`. Options to
evaluate (design decision, not mechanical):
1. Check `monitor_.iter < monitor_.n_iter` instead of `monitor_.converged` --
   true early-break (tolerance-based convergence) implies `iter < n_iter`
   strictly, so this correctly detects "did NOT hit the cap." Cheapest fix,
   but conflates "hit the cap" with "poor fit quality" (a fit could hit the
   cap while still being numerically fine, just slow to satisfy `tol`).
2. Track the log-likelihood delta at the final iteration directly (what
   `ConvergenceMonitor.converged`'s second disjunct actually checks) and
   compare against `tol` explicitly in `regime_writer.py`, independent of
   hmmlearn's conflated property.
3. File upstream: this may be a hmmlearn API footgun worth flagging to that
   project, but don't block on it -- this codebase needs its own fix regardless.

Any fix changes when the retry path fires, which changes the set of cells
that get retried at `n_iter*2` -- this touches the same load-bearing
`HMM_RANDOM_STATE`/fit-determinism territory as todo 226, so it requires the
same discipline: verify Viterbi output before/after on a held-out sample, and
budget for a full corpus re-run once the fix lands (regime labels could
change for any cell that was silently under-converged and would now actually
retry).

## Sizing

Investigation + design decision: small. Fix: small (a few lines). Verification
+ full corpus re-run: same order of cost as todo 216's re-run -- batch it into
the next scheduled full rebuild rather than triggering one standalone, unless
this is judged urgent enough to jump the queue (Renaissance principle:
"silent wrong answers are worse than loud crashes" argues for urgency --
recommend P1, not P2, on that basis).
