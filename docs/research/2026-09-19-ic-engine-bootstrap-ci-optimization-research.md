# IC engine bootstrap CI: Numba speedup vs HAC-for-rank-IC replacement (2026-09-19)

**Author:** Fable 5.1, Claude subagent, tasked with researching two independent optimization
levers for `services/ic_engine.py::_blocked_bootstrap_ci` while a multi-day corpus recompute
was in flight. No production code touched; no DB connection made; the live `ic_engine.py`
process (PID 359172 and its forkserver workers, started 2026-09-17) was left untouched.

**Informed by:** Sonnet 5 (main session), 2026-09-19: committed the benchmark script, swept em dashes, and added the corpus-scale framing in todo 385.

## Scope

`_blocked_bootstrap_ci` (services/ic_engine.py:2050) computes a 95% circular block bootstrap
CI for the rank-IC statistic, up to `bootstrap_resamples=2000` resamples per feature block, via
`_resample_ic` (rankdata + `_vectorized_ic`, a Pearson-on-pre-ranked-data implementation of
Spearman's rho, `src/intelligence/statistics/ic_math.py:160`). This function already carries
two documented optimization passes (162 simplify-pass: shared `ThreadPoolExecutor` across
feature blocks; todo 227: early-stopping once the running CI estimate stabilizes) - it is
reviewed, non-naive code, not a target for an "obviously dumb" fix.

Two independently-answerable questions were investigated:

1. Would Numba JIT-compiling the resampling loop speed it up, with **zero change to the
   statistical method**?
2. Does a Newey-West/HAC-style analytical CI exist for a **rank-based** IC statistic, as a
   cheaper replacement for the bootstrap entirely?

---

## Question 1: Numba JIT - real, measured, but modest speedup

**Numba is already a first-class dependency in this codebase**, not a new one this would
introduce. `requirements.txt` pins `numba>=0.65.0` with an explicit `numpy<2.5.0` compatibility
note ("numba's runtime check hard-fails to import above 2.4"), and there is a live precedent:
`src/intelligence/hmm_jit.py::alpha_pass_jit`, a `@numba.njit(cache=True)` forward-filter
described as "numerically identical" to its pre-JIT Python sibling, living in Ring 1
(`src/intelligence/`) with the same "no DB, no Ring 2 imports" constraint that would apply
here. The venv has `numba==0.67.0`, `numpy==2.4.6`, `scipy==1.18.0` installed and working.

### What's actually being computed per resample

`_resample_ic` does three things per resample `b`: (1) build an index array from
`starts_matrix`/`offsets` (cheap numpy), (2) `rankdata(X_raw_block[idx], axis=0)` - average-tie
ranking of an `[n_valid, block_p]` array, column-wise, via scipy's C implementation
(argsort-based), (3) `rankdata(Y_scale[idx])` (1-D, same), then `_vectorized_ic` - a handful of
vectorized numpy reductions (mean-center, sum-of-squares, dot product). This whole sequence
runs up to `bootstrap_resamples` times per feature block, serially in a Python `for` loop when
`pool is None` (the per-symbol `ProcessPoolExecutor` worker path - `per_symbol_bootstrap_threads`
defaults to 1 for every tf), or via `ThreadPoolExecutor.map` for the cross-sectional path.

Two competing hypotheses going in: (a) the bottleneck is per-resample **Python-level call/dispatch
overhead** (2000 iterations × many thousands of cells), which JIT-compiling the whole loop into
one compiled function would eliminate - or (b) `rankdata` is already a near-optimal C routine
(argsort-based, same big-O as anything a hand-rolled Numba rank function could do), so the
bottleneck is the genuine `O(n_boot × n_valid × block_p × log n_valid)` algorithmic cost, which
JIT compilation doesn't change.

### Benchmark

Wrote a benchmark script (committed as `scripts/analysis/ic_engine_bootstrap_ci_numba_benchmark.py`; not re-run since it would contend with the live corpus run) that:
- Reimplements `_blocked_bootstrap_ci`'s serial (`pool=None`) path verbatim as the "current" arm.
- Implements a `@numba.njit(cache=True)` version: a hand-written average-tie `rankdata`
  equivalent (argsort + tie-run averaging, matching scipy's `method='average'`), a JIT
  `_vectorized_ic`, and the **entire** resample loop fused into one compiled function (so there
  is zero per-resample Python call overhead at all, not just per-rankdata-call overhead).
- Validates correctness first: the JIT rank function is checked against
  `scipy.stats.rankdata` on data with real injected ties (rounded floats), and the full CI
  output is checked end-to-end against the scipy path - **both passed with `max abs diff =
  0.000e+00`, i.e. genuinely byte-identical**, not just "close."
- Benchmarks at realistic scale, using this codebase's actual `ICEngineConfig` defaults:
  `bootstrap_resamples=2000`, `feature_block_columns=32`, `bootstrap_block_size` per tf
  (`5m=78, 15m=26, 1h=10, 1d=10`), and representative `n_valid` (2000 for a typical 5m pooled
  cell, 400 for a thin regime slice, 1000 for a 1h cell, plus a 290-feature/9-block full-cell
  run).

**This benchmark ran on the same live machine while the real corpus `ic_engine.py` run was
maxing all 10 workers (load average ~20/24 during the run) - absolute wall-clock numbers below
are inflated by that contention, but the scipy-vs-numba *ratio* is still meaningful since both
arms shared the same contention.**

| Scenario | n_valid | block_p | n_boot | scipy path | Numba path | Speedup | Output diff |
|---|---|---|---|---|---|---|---|
| 5m pooled cell, 1 feature block | 2000 | 32 | 2000 | 21.22s | 13.82s | **1.54x** | 0.0 |
| Thin 15m regime cell, 1 feature block | 400 | 32 | 2000 | 3.21s | 2.32s | **1.39x** | 0.0 |
| 1h cell, 1 feature block | 1000 | 32 | 2000 | 8.62s | 6.84s | **1.26x** | 0.0 |
| 5m pooled cell, full ~290 features (9 blocks) | 2000 | 290 | 2000 | 162.32s | 120.50s | **1.35x** | 0.0 |

### Verdict on Question 1

**Real, but modest.** ~1.3-1.5x wall-time reduction, byte-identical output, zero new dependency
risk (numba is already vendored and precedented). The "eliminate per-resample Python overhead"
hypothesis was only partially right: fusing the whole loop into one compiled call *does* help
(no per-call Python dispatch, no scipy call overhead, no intermediate array allocation churn),
but scipy's `rankdata` is not naive - its own argsort-based C implementation is close to
algorithmically optimal, so there's no 10x-or-more win sitting there. The bottleneck is
genuinely the `O(n_boot × n_valid × block_p × log n_valid)` work itself, not incidental Python
overhead, which is why this isn't an "obviously dumb, easy fix" - the docstring's own framing
(two prior optimization passes) was accurate; this is a third real-but-bounded increment, not a
correction of an oversight.

One structural note worth flagging for whoever picks this up: the codebase's own comment on
`cross_sectional_bootstrap_threads` (services/ic_engine.py:583-598) states "scipy's
rankdata/argsort releases the GIL; threading gave a real 2-6x wall-time reduction" for the
existing `ThreadPoolExecutor` path - i.e., the threading lever already in place is a **bigger**
win than Numba alone. A Numba `njit` function does not release the GIL by default when called
from Python threads unless declared `nogil=True`; this benchmark did not test a
`nogil=True` + `ThreadPoolExecutor` combination, nor a `numba.prange`-parallel version, both of
which could stack with or replace existing threading for a larger combined number. That's a
follow-up measurement, not assumed here - don't cite a bigger number than what was actually run.

**Practical implication:** at ~1.3-1.5x, this is worth landing only if the wall-clock cost of a
multi-day corpus run is itself the pain point and the engineering cost (writing + testing a
byte-identical Numba rank/IC kernel, verifying tie-handling edge cases, adding it to the Ring 1
JIT precedent alongside `hmm_jit.py`) is acceptable for that return. It is not a slam-dunk
10x win; size the investment to the real number above, not to the framing in the original
"is this an easy win" question.

---

## Question 2: HAC for rank-IC - no established closed form, but a very recent candidate exists (unvetted, not production-ready)

### Why this is a real open question, not an obvious no

The standard Newey-West HAC sandwich estimator is built for **linear** statistics - a sample
mean, an OLS coefficient - where the estimator is a simple average of per-observation
contributions and the sandwich variance is a kernel-weighted sum of empirical
autocovariances of those per-observation terms. A rank correlation (Spearman's rho / the
rank-IC computed here) is a **nonlinear, U-statistic-type** functional of the joint order of
the sample: computing it requires first ranking the whole sample, so it does not decompose into
a simple sum of i.i.d.-style per-observation contributions the way a mean does. This is exactly
why the question can't be answered by "just apply Newey-West to it" - it genuinely isn't the
same kind of statistic.

**This codebase's own existing HAC usage confirms this distinction rather than blurring it.**
`_hac_sharpe_nd` (`src/intelligence/statistics/ic_math.py:967`, the thing behind
`ic_sharpe_hac`) computes a Newey-West Bartlett-kernel-corrected Sharpe ratio of a **time series
of already-computed window-level IC point estimates** - i.e. it HAC-corrects the variance of a
**mean of a sequence of numbers**, a textbook-linear-statistic use of Newey-West. It says
nothing about the sampling variance of a single rank correlation computed once over `n_valid`
paired observations, which is the quantity `_blocked_bootstrap_ci` actually targets. Citing
`ic_sharpe_hac` as precedent for "we already do HAC here" would be a category error - same
tool name, different statistical object entirely.

### This codebase already tried the closed-form alternative and rejected it, empirically

Critical context found in `docs/plans/methodology-change-ledger.md` entry **E6 (2026-07-11,
todo 091)**: the *current* Fisher z-transform analytical CI (`_fisher_z_ci`,
`src/intelligence/statistics/ic_math.py:124`) - an O(p), no-resampling, exact-asymptotic CI
for Spearman IC ("Exact asymptotic CI equivalent to the bootstrap limit as n → ∞" per its own
docstring) - **is the direct analytical predecessor the block bootstrap replaced in
`ic_engine.py` specifically because it was empirically miscalibrated on this corpus**: a
2026-07-09 null-calibration diagnostic found `_fisher_z_ci` SUSPECT (`se_ratio > 1.2`) on 38%
(11/29) of evaluated cells, spanning 4 of 8 `(tf, is_pooled)` strata - not confined to thin-N
corners. The bootstrap CI that replaced it *improved* this (20.7% SUSPECT) but did **not**
fully clear it - 6/29 cells remained SUSPECT even after the fix, concentrated in
autocorrelation/momentum-family features (`ret_autocorr_1`, `ctf_momentum`, `month_sin`) at
`tf=5m` specifically, and increasing `bootstrap_block_size` from 78 to 780 bars did not resolve
it. This residual is still an open, non-blocking todo (099, per `.planning/todos/PRIORITIES.md`
line 487: "why 5m autocorrelation/momentum features resist both Fisher-z and block-bootstrap
remains open").

**Implication:** the project has direct, corpus-specific empirical evidence that a "clean"
asymptotic analytical CI for this exact statistic (Spearman IC) can silently under-cover on
real data, and that even the bootstrap doesn't fully solve it for autocorrelated feature
families. Any HAC-style analytical replacement is not competing against a theoretical ideal -
it's competing against a bootstrap that itself has a known, documented, unresolved residual
failure mode on this corpus. A new analytical method would need to clear the *same*
`ops_ic_null_calibration.py` diagnostic bar the bootstrap was validated against, not just look
correct on paper.

### What the literature actually says

Searched genuinely rather than assuming an answer either way:

- **Borkowf (2002)**, *Computational Statistics & Data Analysis* 39(3): derives the nonnull
  asymptotic variance of Spearman's rank correlation for general bivariate distributions - but
  under the standard **i.i.d. observations** assumption (relaxing only the null-independence
  assumption between X and Y, not the independence-across-observations assumption). Doesn't
  address serial dependence.
- Simulation literature (Wayne State JMASM, "Constructing Confidence Intervals for Spearman's
  Rank Correlation with Ordinal Data") confirms analytical CIs for Spearman's rho have known
  coverage problems even in the *i.i.d.* case with ordinal/discrete data, and that bootstrap CIs
  "usually achieve as good or better coverage than analytical methods" generally - consistent
  with this project's own E6 finding.
- **Pohle, Wermuth & Weiß, "Asymptotic Inference for Rank Correlations"** (arXiv:2512.14609,
  submitted 2025-12-16, revised 2026-02-10 - i.e. roughly 7 months old as of this research,
  essentially brand new) is the first paper that actually closes this gap. Its own abstract
  states plainly that before this work, "asymptotic confidence intervals are not available" for
  rank correlations (Kendall's tau, Spearman's rho, and others) under **time series
  dependence**. It derives asymptotic distributions for both i.i.d. and dependent (time series)
  data via U-statistics theory, and - notably - **the dependent-data variance estimator it
  proposes is itself explicitly HAC-style**: a Newey-West-form Bartlett-kernel-weighted sum of
  empirical autocovariances of estimated Hoeffding-decomposition kernel terms, with bandwidth
  `b_n = floor(2·n^(1/3))`.
  - Required assumptions: strictly stationary, ergodic, **absolutely regular (β-mixing)**
    processes with summable mixing coefficients - described by the authors as classical/standard
    time series assumptions, not unusually restrictive, but they do need to be argued for this
    codebase's actual feature/return series (which include regime-conditional, HMM-labeled
    subsets - stationarity within a regime cell is plausible but not free of scrutiny, especially
    for the `tf=5m` momentum/autocorrelation features already flagged as the residual failure
    mode above).
  - **Software**: an R package exists (`RCor`,
    `github.com/jan-lukas-wermuth/RCor`) implementing the CIs and tests. **No Python
    implementation exists.** This codebase is pure Python/asyncpg/numpy; adopting this would mean
    either porting the estimator from scratch or shelling out to R, neither of which is a small
    lift.
  - **Own simulation honesty**: the paper itself states variance estimation under temporal
    dependence is "a notoriously difficult problem, usually plagued by oversized tests and
    confidence intervals with undercoverage," and explicitly says block bootstrap "also exhibits
    this behaviour" - i.e. the authors do **not** claim their HAC estimator solves what block
    bootstrap gets wrong; they present both as known alternatives with similar finite-sample
    limitations under strong dependence. There is no head-to-head simulation in the paper showing
    the new HAC estimator beats block bootstrap on coverage for the sample sizes/dependence
    strengths this project would actually be using it at.

### Verdict on Question 2

**A theoretically defensible analytical form for HAC-style rank-IC inference under time-series
dependence now exists in the literature - but it is a preprint-fresh (7-month-old, still v2 as
of Feb 2026), R-only, unvalidated-against-this-corpus result, not an established or
production-ready technique.** This is not a "no, rank statistics can't have HAC, stick with the
bootstrap" answer, and it's not a "yes, go implement it" answer either - it's a genuine "a door
just opened, and nobody has walked through it yet, including the paper's own authors" answer.
Three concrete blockers before this could ever replace the bootstrap here:

1. **No Python implementation** - would require either a from-scratch port of the
   U-statistics/Hoeffding-kernel variance estimator (real statistical implementation risk, not
   just engineering) or calling out to R, which this codebase does not do anywhere today.
2. **Assumptions need per-cell justification** - β-mixing/stationarity claims would need to be
   argued (or empirically tested) for this project's actual regime-conditional, HMM-labeled
   feature/return series, not just asserted by analogy to generic time-series econometrics.
3. **No evidence it clears this project's own bar** - the bootstrap CI it would replace already
   has a documented, unresolved residual miscalibration (todo 099) on exactly the kind of
   autocorrelated feature family (5m momentum/autocorrelation) where this question matters most.
   The paper's own authors report the new HAC estimator has similar undercoverage tendencies
   under strong dependence as block bootstrap - there's no literature basis to expect it would
   fix todo 099's residual, only to expect it might perform *comparably*, at a fraction of the
   compute cost, if implemented and validated correctly.

---

## Recommendation

**Only Question 1 is fit for near-term action, and it should be scoped to its real number, not
an assumed one.** A Numba-JIT'd `_blocked_bootstrap_ci` kernel gives a measured, byte-identical
1.3-1.5x wall-time reduction on this dependency-already-vendored, already-precedented
(`hmm_jit.py`) stack - a legitimate, low-risk optimization worth landing as ordinary engineering
work (implement + unit-test the tie-handling edge cases + `/code-review`), but not one that
changes the shape of a multi-day corpus run by itself; if the threading lever
(`cross_sectional_bootstrap_threads`/`per_symbol_bootstrap_threads`, already documented as
giving 2-6x) hasn't been fully exploited on the per-symbol path yet, that is very likely a
bigger and cheaper lever to pull first, and combining it with a `nogil=True` Numba kernel is
worth a follow-up benchmark before committing engineering time to Numba alone. **Question 2 is
not ready for implementation and should not be scheduled as follow-on engineering work yet** -
it is a live, real, recently-opened statistical research question (the Pohle/Wermuth/Weiß
paper is barely half a year old and has no Python implementation, no validation against this
project's own null-calibration diagnostic, and no evidence in its own simulations that it beats
the bootstrap's known 5m-momentum residual). The correct next step for Question 2, if pursued at
all, is a dedicated statistical validation pass - port or reimplement the estimator, run it
through `ops_ic_null_calibration.py` against the same 5m residual cells that broke Fisher-z and
still partially break the bootstrap, and only then decide whether it's a real replacement - not
a code change made on the strength of the paper's abstract alone.
