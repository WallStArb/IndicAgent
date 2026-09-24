# Cross-instrument covariance-aware portfolio diagnostic — design

Author: Claude (Sonnet 5), 2026-09-16, brainstormed with Brandon.

**Revision note (2026-09-16):** independently reviewed by Codex (gpt-5.5) and AGY after the first draft.
Both found the same core defect — the original "reuse `resolve_stratum_weights` unchanged" and
"`mu_i = IC_i * sigma_i * score_i`" claims were each incomplete/wrong in ways confirmed against the
actual code — plus complementary findings neither caught alone (Codex: rank-IC-vs-Pearson-slope gap,
covariance-horizon alignment; AGY: Gate-B selection lookahead, missing embargo, VIXY roll-decay
confound, missing turnover/cost, insufficient regime-label handling). All incorporated below; sections
below are marked "REVISED after review" where the content materially changed from the first draft.

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

## Component reuse (the core of the design) — REVISED after Codex + AGY review

`src/intelligence/ensemble/` (`covariance.py`, `weights.py`, `shrinkage.py`) is a set of pure functions
— no DB/Kafka imports — that `services/ensemble_trainer.py` uses to combine *features* within one
instrument via Ledoit-Wolf shrinkage covariance and `Sigma^-1 . ic_shrunk` (Grinold-Kahn signal
combination).

Portfolio construction (allocating across *instruments*) and feature combination (allocating across
*signals for one instrument*) share the same unconstrained first-order form, `w ~ Sigma^-1 . mu` — that
part of the original claim holds. **What does not hold, confirmed independently by two reviewers against
the actual code, is reusing `resolve_stratum_weights`/`derive_weights` wholesale:**

- `derive_weights` (`src/intelligence/ensemble/weights.py:28`) does
  `w = np.where(np.isfinite(weight_inputs) & (weight_inputs > 0), weight_inputs, 0.0)` — it zeroes every
  non-positive input. For features (always fed a positive-magnitude-convention input by the caller) this
  is correct. For a signed instrument alpha book, this is fatal: a bearish `mu_i < 0` gets zeroed
  outright, and if every instrument is bearish on a given day the function returns an all-zero vector.
  This was verified by reading the function, not assumed.
- `resolve_stratum_weights`'s ill-conditioned-covariance fallback path calls
  `derive_weights(aged_quality_weights, ...)` — `aged_quality_weights` is ensemble feature-staleness
  data that has no instrument-level analog. The fallback contract does not port.
- The `ic_signs = ic_signs * mv_raw` re-signing step exists to handle contrarian *features* whose
  reference direction is independent of the unconstrained solve's own sign. At the instrument level,
  `mu_i` is already signed going in — re-applying a separate sign convention on the output corrupts the
  solution rather than correcting it.

**Revised reuse boundary:** reuse `compute_shrinkage_covariance(X)` and the bare `mean_variance_weights`
solve (`Sigma^-1 . mu`, condition-number gated) as primitives only. Do not call
`resolve_stratum_weights` or `derive_weights`. Build a dedicated instrument-weight step on top of the
primitive:
- If long-only: solve the constrained problem properly (NNLS or QP, `w >= 0`, `sum(w) = 1`) — truncating
  the unconstrained solve's negative entries to zero does not solve the constrained Markowitz problem
  and violates KKT conditions when assets are correlated (a negative unconstrained weight can represent
  a legitimate hedge against common factor exposure that a truncate-and-renormalize step destroys).
- If long/short (the more natural fit here, since `alpha_events.direction` already carries sign): keep
  the unconstrained `Sigma^-1 . mu` solve's sign as-is; do not re-apply a second sign convention.
- On an ill-conditioned `Sigma`, fall back to ridge regularization (`Sigma + epsilon*I`) or eigenvalue
  clipping before re-solving — not `cluster_deflate_weights`/`derive_weights`, which assume a feature
  staleness input this diagnostic doesn't have. Log the fallback exactly as loud as `ensemble_trainer.py`
  does (`mean_variance_fallback` must never be silent — same repudiation-risk discipline).
- `effective_n` is reused, but its interpretation must be widened for a portfolio (see Output section):
  report gross exposure, net exposure, and Herfindahl-on-absolute-weights alongside it — `1/sum(w^2)` on
  signed, non-unit-sum weights is misleading on its own.

This is a smaller reuse footprint than originally proposed, but it's the *correct* footprint — the
covariance estimator and the raw linear-algebra solve are genuinely shared math; the feature-specific
sign/positivity/fallback conventions wrapped around them in `ensemble_trainer.py` are not.

## Critical correction found during brainstorming: mu calibration — REVISED after review

`alpha_events.alpha_score = X @ signed_weights` — a composite ranking score (its own predictive power
is what `EnsembleICEngine` measures via IC against forward returns), **not an expected-return-unit
quantity**. Feeding it directly into `Sigma^-1 . alpha_score` would let feature-composite-scale
artifacts, not genuine risk-adjusted economics, drive portfolio weights.

The original fix proposed here (`mu_i = IC_i * sigma_i * score_i`) was incomplete — both Codex and AGY
independently caught the same gap: this is the correct Grinold-Kahn form only when `score_i` is itself a
standardized (zero-mean, unit-variance) forecast. `alpha_score`'s variance is not comparable across
instruments (different active-feature counts, different feature volatility), so the missing step is
standardizing the score *before* the IC/vol scaling — otherwise an instrument with a wide-variance
composite score gets a proportionally inflated `mu_i` purely from scale, not from real predictive
content. Corrected form:

```
z_i    = (score_i - mean(score_i)) / std(score_i)     # standardize within the trailing window
mu_i   = IC_shrunk_i * sigma_i * z_i
```

where `sigma_i` is the instrument's realized return volatility (diagonal of the covariance matrix
already being computed) and `IC_shrunk_i` is described next.

**`IC_i` must be shrunk, not used raw.** AGY's finding, and correct on inspection: at a daily trailing
window of ~1-2 years, `SE(IC) ~ 1/sqrt(T) ~ 0.045-0.063`, while realistic daily alpha IC is commonly
~0.02-0.05 — signal-to-noise is under 1. Across 13 instruments, unshrunk trailing IC will swing sign on
noise alone (Michaud's "estimation-error maximizer" problem: `Sigma^-1` amplifies exactly the noisiest
inputs). The codebase already has the right tool for this — `src/intelligence/ensemble/shrinkage.py`'s
`shrink_ic()` (empirical-Bayes, James-Stein toward a leave-one-out peer prior, APR-backed `k`) — reuse it
directly: shrink each instrument's trailing IC toward the cross-sectional mean IC across the candidate
set (or a Gate B pooled prior) before it enters the `mu_i` formula.

**`IC_i` itself must be out-of-sample per walk-forward segment** — computed from the trailing window
only, never from the segment being evaluated. Using a full-sample IC to calibrate weights, then
evaluating performance on that same full sample, double-dips and inflates the apparent benefit.

**Rank-IC caveat (Codex):** `EnsembleICEngine` measures IC via `rankdata` (Spearman rank correlation),
not a Pearson slope. Using a rank IC directly as the linear scaling coefficient in `mu_i` is a heuristic,
not an exact calibration — acceptable for a first-pass diagnostic, but the report must say so rather
than imply `mu_i` is a precise expected-return estimate. A more exact alternative (trailing causal
regression of realized return on standardized score, i.e. an actual OLS/ridge beta) is a candidate
follow-up, not required for this version.

**Selection-lookahead risk from Gate B itself (AGY):** making Gate B a hard prerequisite means universe
membership is conditioned on instruments having demonstrated significant IC over the measurement period
— this is itself a selection effect. This diagnostic's absolute performance numbers must be reported as
*conditional on the Gate-B-selected universe*, not as evidence the method would have discovered these
instruments from an unfiltered candidate pool. Making Gate B itself walk-forward/OOS-respecting is a
larger, separate change (to `ic_engine`), explicitly out of scope here — the report must state this
limitation plainly rather than imply the numbers are selection-bias-free.

## Method — REVISED after review

- **Two distinct return series — do not conflate them (both reviewers flagged this ambiguity in the
  original draft, which used "instrument return matrix" and "`forward_returns`,
  `executable_open_to_open`" interchangeably):**
  1. **Covariance estimation input**: `Sigma` is estimated from realized, non-overlapping, single-period
     historical returns (`ln(price_t / price_{t-1})`, strictly backward-looking as of the refit boundary)
     — never from `forward_returns`. Forward returns are targets/labels, not historical observations;
     estimating asset covariance on overlapping forward-looking windows induces artificial
     autocorrelation and cross-sectional covariance that isn't real co-movement.
  2. **Mu calibration and performance scoring**: `forward_returns`, `return_type =
     'executable_open_to_open'` (CLAUDE.md Invariant 1) — used for measuring each segment's trailing
     `IC_i` and for scoring realized out-of-sample portfolio performance. Explicitly NOT Gate A's
     close-to-close descriptive definition (Gate A says its own method must never import this invariant;
     this diagnostic is an alpha/expected-return measurement, so the invariant applies here, inverted
     from Gate A's case).
- **Explicit embargo.** `executable_open_to_open` at bar `T` is `ln(open[T+2]/open[T+1])` — not realized
  until `T+1`'s open. Any refit at boundary `T` must only use data through `T - 2`, not `T - 1`. No
  embargo was specified in the original draft; this is now a hard requirement, checked in code, not just
  documented.
- **Two decoupled cadences, not one** (the original draft's "refit every N bars" conflated them):
  - *Covariance/IC refit cadence*: slow-moving parameters (`Sigma`, shrunk `IC_i`) refit on a coarser
    schedule (e.g. monthly, trailing ~1-2yr window) — this is the walk-forward boundary, same
    refit-then-apply-forward discipline as `regime_writer.py`'s `_walk_forward_hmm_labels`.
  - *Weight/rebalance cadence*: `mu_i` is recomputed causally at each rebalance step (daily) from that
    step's current `alpha_score`, combined with the most recent refit's `Sigma`/`IC_shrunk`. The
    portfolio weight vector changes daily even though `Sigma` itself only refits monthly. This is the
    literal, implemented answer to "shouldn't the portfolio change over time" — it does, on both axes,
    at different speeds, matching how covariance (slow) and alpha (fast) actually move.
- **Regime split on a causal proxy, not `market_regimes` (changed after review).** The original draft
  used `market_regimes` for "reporting only" with a caveat. Both reviewers judged a caveat insufficient:
  `regime_writer.py`'s labels carry a confirmed non-causal contamination (full-series HMM fit; the
  walk-forward fix exists behind `alpha.hmm.walk_forward.enabled = false`, todo 248) — if a `high_bear`
  split is computed from a model that saw the crash in advance, the reported bear-regime performance is
  itself lookahead-biased, not just caveated. Fix: condition the regime split on a strictly causal proxy
  instead — e.g. trailing SPY 200-day SMA sign, or trailing realized volatility/drawdown — computed
  independently of `regime_writer.py`. Cheap, causal by construction, avoids inheriting todo 248's
  unresolved bug rather than just disclosing it.
- **No hyperparameter search.** Refit cadence and minimum trailing-coverage threshold are chosen once
  as literal constants, not grid-searched — matches Gate A's own "hardcode, don't fit" doctrine and
  "resist overfitting."
- **Coverage filter, logged not silent.** Each walk-forward refit step includes whatever instruments
  have sufficient trailing coverage *as of that point in time* (Gate A's own `_MIN_DAILY_COVERAGE`
  pattern). Never restrict the whole run to instruments with complete history over the *entire* period
  — that implicitly selects on "survived to the end," reintroducing the survivorship bias already
  flagged as the one open risk in the personal-scale-edge program closure.
- **Revision 2026-09-24 (Phase 179 build step 3): coverage means a full trailing window, and gaps
  are never zero-filled.** The original filter admitted an instrument with 20 non-null returns in
  the 504-day window and filled the rest with 0.0, which understates a new listing's variance and
  inflates its `vol_normalized` weight (measured: TLT at 46% coverage in a 2017 refit, sigma ~0.68x,
  weight ~1.47x). Now an instrument is admitted only if it has a return on the window's last row
  and on >= 95% of the window; if the rows where every admitted instrument has a return still fall
  below 95%, the lowest-coverage instrument is dropped (ties by name) until they don't; the
  covariance is fitted on those complete rows. Deterministic, never skips a refit, never
  zero-fills. Still point-in-time (trailing window), so the survivorship guard above is
  unchanged. The 2026-09-22 result (todo 378) is unaffected: its data starts 2018-01-01 and all 13
  instruments had full coverage at every refit. The primitives now live in
  `src/intelligence/portfolio/weighting.py`.

## Comparison arms — REVISED after review (AGY: 3 arms confound volatility-scaling with covariance)

Four arms computed side by side. The original 3-arm design had a specific, confirmed gap: Arm 2
(`mu_i = IC_i * sigma_i * z_i`) scales *with* volatility, while Arm 3 (`Sigma^-1 . mu`) divides *by*
variance — so any apparent Arm 3 win over Arm 2 could be nothing more than trivial inverse-volatility
scaling, not real covariance/correlation awareness. The literature AGY cites (Asness/Frazzini/Pedersen,
Roncalli) makes this exactly the standard confound to control for. Fix: add a volatility-normalized arm
between them so covariance-awareness specifically can be isolated:

1. **Naive equal-weight** — no covariance adjustment, no IC weighting. (Caveat for interpretation, not a
   design change: this arm is structurally disadvantaged by VIXY's persistent negative roll yield from
   VIX futures contango — a forced permanent 1/13 allocation to a structurally decaying instrument makes
   this baseline look artificially weak. Note this in the report; do not silently let it inflate the
   apparent benefit of the other arms.)
2. **IC-proportional independent** — each instrument weighted by its own calibrated `mu_i`, no
   cross-instrument covariance adjustment. What's implicit in today's architecture.
3. **Volatility-normalized / diagonal-covariance (new — Arm 2b)** — `w_i ~ mu_i / sigma_i^2`, i.e. the
   diagonal-only special case of mean-variance (inverse-vol scaling, no off-diagonal correlation term).
   Isolates the "just scale by volatility" effect.
4. **Full mean-variance covariance-aware** — the proposal: the primitive `mean_variance_weights` solve
   (not `resolve_stratum_weights`, see Component reuse revision above) over the full instrument
   covariance matrix and calibrated `mu` vector, including off-diagonal correlation.

Arm 4 beating Arm 3 is the specific, isolated evidence that correlation-awareness (not just volatility
normalization) adds value — the comparison this whole design exists to make. Arm 4 beating Arm 1/2 alone
is not sufficient evidence of that.

## Output — REVISED after review (turnover/cost and exposure reporting added)

JSON report (`--json-out`, Gate A's convention). Per walk-forward step: refit date, covariance condition
number, fallback method used (flag any ridge/eigenvalue-clipping fallback, never silent — same
repudiation-risk discipline as `ensemble_trainer.py`'s `mean_variance_fallback` logging), portfolio
weights per instrument.

Aggregate, per arm: 
- `effective_n` over time, but no longer reported alone — pair it with **gross exposure**
  (`sum(abs(w))`) and **net exposure** (`sum(w)`), since `1/sum(w^2)` on a signed, non-unit-sum weight
  vector is misleading by itself (AGY's finding: the original design's `effective_n` reuse assumed the
  feature-combination case's unit-sum, non-negative convention, which no longer holds once Arms 3-4 can
  carry negative weights).
- **Turnover and cost, not just gross realized return** (missing entirely from the original draft — both
  reviewers flagged this independently). Report L1 turnover per rebalance
  (`sum(abs(w_t - w_{t-1}))`) and both gross and cost-adjusted net return per arm, using `alpha_events`'
  existing `cost_hurdle` as the per-instrument cost proxy. Mean-variance weighting is known to churn hard
  on small `mu`/`Sigma` shifts; a diagnostic that reports only gross return is easy to overread as a
  bigger win than it is once realistic friction is applied.
- Regime split: unconditional vs. the causal trailing-SPY/volatility proxy described above (not
  `market_regimes`/`high_bear`).

**No `--gate` / pass-fail exit code in this first version.** This is a measurement tool, not a
promotion gate. With ~13 instruments the walk-forward sample is likely powered for a directional read
only, not a p<0.05 verdict — the report must say this honestly rather than overclaim significance it
doesn't have. A promotion decision, if any, is a separate later step made by a human/model reading the
report, and must account for the Gate-B selection-conditioning caveat above before treating any arm's
apparent edge as clean.

## What this does not do

Does not size any live position. Does not modify `alpha_publisher`, `alpha_events`, or any live
consumer. Does not deploy todo 248's walk-forward HMM fix, and does not use `market_regimes` at all
(revised: uses an independent causal proxy for regime splitting instead — see Method). Does not solve
Gate B's own full-sample selection-lookahead property — that's flagged as a reporting caveat, not fixed
here; making Gate B itself walk-forward is a separate, larger change to `ic_engine`, out of scope. Does
not run Gate A or Gate B — both are prerequisites, run separately, before this script can produce real
numbers. Does not decide the final 13-symbol vs. full-book question — that's what the report's results
are for. Does not implement a full constrained portfolio optimizer (QP/NNLS) in this first version if
long/short is the chosen mode — the unconstrained signed solve is sufficient for a shadow-mode
diagnostic; QP is only required if a long-only variant is later added.

## Open items for review

- Long-only or long/short for the first version? Long/short avoids needing a QP/NNLS solver (the signed
  `Sigma^-1 . mu` output is directly usable) and matches `alpha_events.direction` already carrying sign;
  long-only is more realistic for an eventual production analog but adds real optimizer complexity this
  diagnostic doesn't strictly need yet. Recommend long/short for v1.
- Is daily (`1d`) the right rebalance cadence, and monthly the right covariance/IC refit cadence, for
  this cross-asset instrument mix, or should either vary by instrument class?
- Should the walk-forward warmup/refit-cadence constants be picked to match `alpha.hmm.walk_forward.*`
  APR keys' existing values (if any exist) for consistency, or independently since this is a different
  subsystem?
- Is the causal regime proxy (trailing SPY 200d SMA sign, or trailing realized vol/drawdown) the right
  choice, or is there a better already-existing causal series in the corpus to condition on instead?
