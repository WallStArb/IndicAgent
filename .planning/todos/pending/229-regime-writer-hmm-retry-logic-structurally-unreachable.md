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

## Design decision: SETTLED 2026-08-02 -- `monitor_.iter < monitor_.n_iter`, proven exact

Of the three options originally listed here, option 1 is not merely cheapest --
it is **exact**, not an approximation, and dominates option 2 on every axis.
Proof (verified against hmmlearn 0.3.3, both by reading `BaseHMM.fit()`'s loop
and by direct empirical test -- see below, not just source-reading):

`for iter in range(self.n_iter): ...; self.monitor_.report(lower_bound); if
self.monitor_.converged: break`. `report()` increments `self.monitor_.iter` by
1 every call. The loop can only break early (leaving `iter < n_iter`) if
`converged` was already `True` at that point -- and since `iter < n_iter`
there, the property's first disjunct (`iter == n_iter`) is false, so it MUST
have been the tolerance disjunct (`history[-1] - history[-2] < tol`) that
fired. **`iter < n_iter` therefore implies genuine tolerance-convergence by
strict logical entailment, not correlation.** Conversely `iter == n_iter`
means the loop ran to completion (cap hit); whether the tolerance criterion
also happened to be satisfied on that exact final step is unknowable from
`iter`/`n_iter` alone and irrelevant -- treating a cap-hit as "not confirmed
converged, correct to retry" is the right conservative call per Renaissance's
"never drop a case that could contain signal," not a hack.

Empirically confirmed on real `GaussianHMM` fits (not just derived from
source): tested both branches -- pure-noise data that always hits the cap
across `n_iter` in {1, 5, 50, 500}, and well-separated two-cluster data with
`tol` swept from 1.0 to 1e-8 to force early breaks -- and independently
recomputed the tolerance criterion from `monitor_.history` in every case.
`iter < n_iter` and "tolerance criterion actually satisfied" matched on every
trial, no exceptions.

This also **kills option 2** (tracking the log-likelihood delta directly):
it would just reimplement hmmlearn's own internal `tol` comparison against
its semi-private `history` deque -- strictly more code, more fragile to a
future hmmlearn version change, for a result option 1 already gets exactly by
reading two integers hmmlearn already exposes (`monitor_.iter`,
`monitor_.n_iter`). No remaining ambiguity to file upstream (option 3) either
-- this is a straightforward misuse of a genuinely confusing hmmlearn API,
not a hmmlearn bug.

**The fix:** in `regime_writer.py`, replace both
`candidate_converged = bool(candidate.monitor_.converged)` (~line 570) and
the retry model's equivalent check (~line 586) with
`candidate.monitor_.iter < candidate.monitor_.n_iter`.

## Two second-order consequences to account for when this is implemented

1. **Todo 108's multi-seed comparison logic (`n_restarts > 1`) is also
   silently degraded by the same bug**, not just the retry path. The
   selection tuple `(candidate_converged, candidate_ll)` at
   `regime_writer.py:614` is supposed to rank "any converged candidate over
   any non-converged one, log-likelihood as tiebreaker" -- but since
   `candidate_converged` has always been `True` for every seed, this has
   silently degraded to pure log-likelihood ranking the entire time
   `n_restarts > 1` has been used. Fixing the convergence check correctly
   also revives this intended behavior -- flag this explicitly in the fix's
   commit message/tests, it's a second real behavior change bundled into
   what looks like one bug fix.
2. **The comment this session's branch just added** (`services/regime_writer.py`,
   near the `regime_writer.hmm_convergence_iters` log call) explaining that
   `converged` is structurally always `True` and that `iters_used ==
   n_iter_cap` is the only trustworthy cap-hit signal **becomes stale once
   this fix lands** -- `converged` will be a real signal again. Remove that
   comment (and consider whether the log's `converged` field should keep
   using the same `converged` local variable, which will now be correct) as
   part of this fix, not as a separate followup.

## Recommended sequencing: measure blast radius before committing to the fix + re-run

This session's todo-226-step-1 branch already instruments `iters_used` /
`n_iter_cap` per cell, zero extra cost, no behavior change. **Every cell
where the next full corpus run logs `iters_used == n_iter_cap` is exactly a
cell that would newly trigger a real retry once this fix lands** -- that
count is a direct, free preview of the fix's throughput cost (each such cell
would then pay a second EM fit at `n_iter*2`) before spending anything on the
fix itself or the mandatory re-run. Renaissance discipline says measure
before paying a cost you can measure for free -- don't implement this fix
blind. Sequence: (1) let the next full corpus run populate
`regime_writer.hmm_convergence_iters` logs (already shipped, no action
needed); (2) `grep`/aggregate `iters_used == n_iter_cap` counts from that
run's log before deciding whether to implement this fix immediately or batch
it into a later rebuild; (3) implement the one-line fix from the settled
design decision above; (4) verify Viterbi output on a held-out sample
before/after (same discipline as todo 216); (5) full corpus re-run, since
regime labels can legitimately change for any cell that was silently
under-converged and will now actually retry.

## Sizing

Design decision: DONE, proven exact, zero remaining ambiguity. Fix
implementation: small (two one-line changes + removing one now-stale
comment + updating tests that assert on the old always-True behavior).
Verification + full corpus re-run: same order of cost as todo 216's re-run --
batch into the next scheduled full rebuild rather than triggering one
standalone, informed by step 2 of the sequencing above (a near-zero
cap-hit count argues for batching; a large one argues for treating this as
urgent, per "silent wrong answers are worse than loud crashes" -- recommend
P1, not P2, either way, since the current state silently misrepresents fit
quality regardless of how many cells are actually affected).
