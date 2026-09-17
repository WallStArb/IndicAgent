# Cross-instrument covariance-aware portfolio diagnostic — design

Author: Claude (Sonnet 5), 2026-09-16, brainstormed with Brandon.

## Problem

Phase 174's cross-asset follow-on (`docs/research/phase174-cross-asset-diversification-prereg-2026-09-16.md`)
proposes a fixed 13-symbol "investable universe" (GLD, DBA, DBB, DBC, URA, TLT, UUP, VIXY, EMLC,
HYG, XOM, DHI, PGR), validated once via a static group-correlation check (Gate A, not yet run).

Brandon's objection: why should universe membership be a fixed list decided once via a group-level
correlation snapshot, rather than instruments being included/weighted dynamically based on their
actual covariance with whatever else is held, at the time? Correlation structure is regime-dependent
(Gate A's own split between unconditional and `high_bear` thresholds proves this) — a list validated
once can go stale silently, the same failure mode ITR's tag weights just had (measured once in
Phase 146, never re-run for two months).

Investigation confirmed the underlying gap is bigger than "Gate A is too static": **there is currently
no portfolio-construction layer anywhere downstream of `alpha_events` in v3.0 at all.**
`alpha_frame_writer` writes per-instrument diagnostic expected-R snapshots (`alpha_frames`) but has
"no live consumer." Zero `kelly` hits in the codebase; zero portfolio/cross-instrument APR keys. The
"Kelly" mention in root `CLAUDE.md`'s `alpha.*` namespace description is aspirational text, not built.

This document scopes the first cross-instrument covariance-aware measurement — a shadow-mode
diagnostic, not a live sizing engine — to test whether covariance-aware combination actually beats
static-list / naive approaches, before any of it goes near a real decision.

## Scope decisions (from brainstorming)

- **Shadow-mode diagnostic, not production sizing.** Per "prove edge before production infra" (gates
  downstream alpha consumers, not discovery/measurement work) and "shadow mode first": this measures
  whether covariance-aware weighting helps, historically. It does not size any real position.
- **Universe: 13-symbol cross-asset candidates first, full compute-eligible book second.** Validates
  the mechanism cheaply before the expensive run.
- **Artifact type: standalone script in `scripts/analysis/`, not a new service or table.** Matches
  every other Phase 174 diagnostic (`universe_expansion_correlation_structure_check.py` = Gate A,
  `alpha_score_residual_diagnostic_15m.py`, `cross_tf_signal_correlation_screen.py`, etc.). Reads
  existing tables, writes a JSON report, touches nothing in the live DAG — no new Kafka topic, no new
  compute daemon, no persistence writer. Consistent with "earn promotion through proof": don't build
  infrastructure before the idea is validated.
- **Gate B (per-instrument IC) becomes a hard prerequisite, not a parallel track.** See calibration
  note below — the diagnostic cannot run without it.

## Component reuse (the core of the design)

`src/intelligence/ensemble/` (`covariance.py`, `weights.py`) is a set of pure functions — no DB/Kafka
imports — that `services/ensemble_trainer.py` already uses to combine *features* within one instrument
via Ledoit-Wolf shrinkage covariance and `Sigma^-1 . ic_shrunk` (Grinold-Kahn signal combination), with
`cluster_deflate_weights` capping any correlated cluster's combined weight so collinear features don't
double-count.

Portfolio construction (allocating across *instruments*) and feature combination (allocating across
*signals for one instrument*) are the same underlying problem — `w ~ Sigma^-1 . mu` — this is not a
coincidental analogy, it's why Grinold-Kahn signal combination and Markowitz mean-variance portfolio
construction share the identical functional form. The plan reuses these functions unchanged, one level
up:

- `compute_shrinkage_covariance(X)` — `X` = instrument return matrix `[n_obs, n_instruments]` instead
  of feature matrix. Produces the instrument covariance/correlation matrix.
- `resolve_stratum_weights(...)` (mean_variance path) — instrument-level `mu` (see calibration below)
  plays the role each feature's `ic_shrunk` plays today. Falls back to `cluster_deflate_weights` on an
  ill-conditioned covariance matrix, exactly as it does for features (same repudiation-risk logging
  discipline: `method_used == 'mean_variance_fallback'` must never be silent).
- `effective_n` — reused directly to report portfolio-level effective breadth over time, comparable to
  Gate A's `n_eff`.

No new covariance or combination math is written. This is the single biggest "component reuse / SoC"
win in the design and the reason a second, independent implementation of covariance math never gets
created to drift out of sync with the first.

## Critical correction found during brainstorming: mu calibration

`alpha_events.alpha_score = X @ signed_weights` — a composite ranking score (its own predictive power
is what `EnsembleICEngine` measures via IC against forward returns), **not an expected-return-unit
quantity**. Feeding it directly into `Sigma^-1 . alpha_score` would let feature-composite-scale
artifacts, not genuine risk-adjusted economics, drive portfolio weights — two instruments with the same
raw `alpha_score` but different volatility or different score-to-return calibration do not deserve the
same dollar allocation.

Fix: convert each instrument's score into a real expected-return estimate before combination, standard
Grinold-Kahn form:

```
mu_i = IC_i * sigma_i * score_i
```

where `IC_i` is that instrument's own measured score-to-return correlation (from Gate B) and `sigma_i`
is its realized return volatility (the diagonal of the same covariance matrix already being computed).
This makes Gate B a hard input dependency, not an independent parallel track — the calibration cannot
happen without it.

**`IC_i` itself must be out-of-sample per walk-forward segment** — computed from the trailing window
only, never from the segment being evaluated. Using a full-sample IC to calibrate weights, then
evaluating performance on that same full sample, double-dips and inflates the apparent benefit.

## Method

- **Returns: `forward_returns`, `return_type = 'executable_open_to_open'`** (CLAUDE.md Invariant 1).
  Explicitly NOT Gate A's close-to-close descriptive definition — Gate A is a pure correlation-structure
  characterization and says so explicitly ("must never import the executable_open_to_open invariant
  into this script"); this diagnostic measures expected-return/alpha, so the invariant applies here.
- **Walk-forward, not in-sample.** Refit `Sigma` and weights on a trailing window every N bars, apply
  causally forward, roll. Same shape as `regime_writer.py`'s `_walk_forward_hmm_labels` (refit-then-
  causally-decode pattern) — not literal code reuse (HMM-specific), but the same discipline: the
  portfolio actually changes over time as covariance and alpha shift, which is the direct answer to
  "shouldn't this change over time."
- **Regime split for reporting only.** Join to `market_regimes` (same as Gate A: `regime_group`, `tf`)
  to report unconditional vs. `high_bear` behavior separately.
  - **Known caveat, must appear in the report, not be hidden:** `regime_writer.py`'s regime labels
    currently carry a confirmed non-causal contamination (full-series HMM fit; walk-forward fix exists
    behind `alpha.hmm.walk_forward.enabled`, currently `false` — todo 248). This diagnostic inherits
    that same limitation for its regime-conditioned split, same as Gate A already does. Fixing it is
    todo 248's own deployment decision, out of scope here — but the report must state the caveat
    explicitly.
- **No hyperparameter search.** Refit cadence and minimum trailing-coverage threshold are chosen once
  as literal constants, not grid-searched — matches Gate A's own "hardcode, don't fit" doctrine and
  "resist overfitting."
- **Coverage filter, logged not silent.** Each walk-forward refit step includes whatever instruments
  have sufficient trailing coverage *as of that point in time* (Gate A's own `_MIN_DAILY_COVERAGE`
  pattern). Never restrict the whole run to instruments with complete history over the *entire* period
  — that implicitly selects on "survived to the end," reintroducing the survivorship bias already
  flagged as the one open risk in the personal-scale-edge program closure.

## Comparison arms

Three arms computed side by side, to isolate what's actually adding value (a result that only shows
"a portfolio beats one instrument" is not evidence covariance-awareness specifically helps):

1. **Naive equal-weight** — no covariance adjustment, no IC weighting.
2. **IC-proportional independent** — each instrument weighted by its own calibrated `mu_i`, no
   cross-instrument covariance adjustment. This is what's implicit in today's architecture (each
   instrument scored independently).
3. **Full mean-variance covariance-aware** — the proposal: `resolve_stratum_weights` over the
   instrument covariance matrix and calibrated `mu` vector.

## Output

JSON report (`--json-out`, Gate A's convention). Per walk-forward step: refit date, covariance
condition number, `method_used` (flag any `mean_variance_fallback`, never silent), portfolio weights
per instrument. Aggregate: `effective_n` over time, realized executable-return performance per arm,
split unconditional vs. `high_bear`.

**No `--gate` / pass-fail exit code in this first version.** This is a measurement tool, not a
promotion gate. With ~13 instruments the walk-forward sample is likely powered for a directional read
only, not a p<0.05 verdict — the report must say this honestly rather than overclaim significance it
doesn't have. A promotion decision, if any, is a separate later step made by a human/model reading the
report.

## What this does not do

Does not size any live position. Does not modify `alpha_publisher`, `alpha_events`, or any live
consumer. Does not deploy todo 248's walk-forward HMM fix (uses existing regime labels with the caveat
noted above). Does not run Gate A or Gate B — both are prerequisites, run separately, before this
script can produce real numbers. Does not decide the final 13-symbol vs. full-book question — that's
what the report's results are for.

## Open items for review

- Is `mu_i = IC_i * sigma_i * score_i` the right calibration, or is there a reason to prefer a
  different scaling (e.g., shrinking `IC_i` itself given small-N per-instrument, similar to how
  `ic_shrunk` already shrinks feature-level IC)?
- Is daily (`1d`) the right rebalance/refit cadence for this cross-asset instrument mix, or should it
  vary by instrument class?
- Should the walk-forward warmup/refit-cadence constants be picked to match `alpha.hmm.walk_forward.*`
  APR keys' existing values (if any exist) for consistency, or independently since this is a different
  subsystem?
