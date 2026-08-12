# Regime Label Transition Quality - Measurement-First Design

**Goal:** Determine, empirically and out-of-sample, whether cross-sectional regime-label
smoothing (hysteresis at the label source) and/or a post-transition purge window
(downstream in IC measurement) actually improve IC - before touching any live
label-generation or measurement code.

**Non-goal:** implementing production changes to `services/cross_sectional_regime_model.py`
or `services/ic_engine.py`. This spec covers only the measurement phase. A follow-on
implementation spec is scoped only if this measurement clears the promotion gate defined
below.

---

## Background

Todo 005 (`.planning/todos/pending/005-ic-regime-transition-purge.md`, filed 2026-06-28)
proposed a purge window in `ic_engine.py` based on a 2026-06-26 roadmap doc's claim that
it would increase `ic_sharpe` 10-20% for regime-dependent features, at a 5-10%
sample-size cost. That claim was never checked against this codebase's actual data -
traced to source, it is asserted in a planning document, not measured. It is not a valid
design input and this spec does not carry it forward.

What is actually live: `cross_sectional_regime_model.py` (Phase 144's dispatcher,
replacing the deprecated `equity_regime_model.py`) assigns regime labels via pure per-bar
threshold bucketing - `_bucket()` at `services/cross_sectional_regime_model.py:197`,
combined into `"{tier1}_{tier2}"` by `_assign_labels()` at line 208 - with zero
hysteresis. This is unlike `services/regime_writer.py`'s per-symbol HMM path, which
already applies a `_smooth_states()` min-hold-period smoother
(`services/regime_writer.py:306`).

### The measurement population (this is load-bearing, read it before anything else)

`market_regimes` is a continuous 24/7 calendar grid. It is **not** the population IC
measurement consumes. Measured 2026-08-02 against live data for `regime_group='equity'`,
`tf='5m'`:

| quantity | value |
|---|---|
| `market_regimes` rows | 2,083,837 |
| of those, falling on a Saturday or Sunday | 595,008 (28.6%) |
| of those, whose `ts` exists in `feature_vectors.bar_ts` for that tf | **387,974 (18.6%)** |

Only that 18.6% can ever contribute an IC observation, because
`_compute_cross_sectional_tf` joins `feature_vectors` on `bar_ts` and `forward_returns`
on `(symbol, tf, bar_ts)`. The other 81.4% are labels attached to timestamps at which no
feature vector and no forward return exist.

Every transition statistic in this spec is therefore computed **after** restricting
`market_regimes.ts` to the set of `feature_vectors.bar_ts` values present for that tf.
Recomputed on that correct (joinable) population, equity/5m has:

- **6,998 label transitions** (6,999 contiguous runs)
- **3,647 of them (52.1%) do not survive 3 consecutive joinable bars** before flipping again
- median run length: 2 joinable bars; mean 55.4 (a small number of very long runs pull the mean)

The same census on `rates`/5m (174,417 joinable rows) is far starker: **139,660 runs,
133,664 of them (95.7%) under 3 bars.** The rates labeler is essentially flickering every
bar on the population IC actually sees.

An earlier draft of this spec cited "15,734 transitions, 24% short" for equity/5m. That
number was computed on the full 24/7 grid and is wrong for this purpose: the calendar
grid interpolates long quiet stretches (weekends, overnight) that suppress the apparent
flicker rate and inflate the apparent transition count. The joinable-population numbers
above supersede it.

The joinable restriction also changes the stratum occupancy materially - it is not a
uniform thinning. Equity/5m, joinable rows per label:

| regime_label | joinable rows | rank on full grid |
|---|---|---|
| high_bull | 13,035 | 4th largest |
| low_bear | 20,929 | smallest |
| high_neutral | 31,017 | 7th |
| mid_bear | 33,058 | 5th |
| mid_bull | 36,049 | 2nd largest |
| low_neutral | 57,374 | 8th |
| high_bear | 60,333 | 3rd |
| low_bull | 67,628 | **largest on the full grid (556,911)** |
| mid_neutral | 68,551 | 6th |

`low_bull` is the dominant label on the raw grid and merely mid-pack on the joinable
population. Any reasoning about "which regimes are thin" that used raw counts was
reasoning about the wrong thing.

**Named, out of scope:** a labeler that emits labels for weekend and off-hours timestamps
at which no market data exists is a separate upstream defect. It costs storage, distorts
every naive census of `market_regimes`, and was directly responsible for the wrong
headline statistic in this spec's first draft. It deserves its own todo. This spec does
not fix it - it works around it with the joinable restriction - but it must not be
silently inherited by the next reader.

**Sibling diagnostic, different consumer:** `docs/plans/archive/2026-07-15-regime-boundary-churn-diagnostic-design.md`
(todo 080/L5-1) investigates the same hard-threshold `_bucket()`/`_assign_labels()`
mechanics from a different angle - whether hard-argmax regime *scoring* in
`ensemble_trainer.py` churns `alpha_score` at boundary crossings, not whether regime
*labels* contaminate IC *measurement* (this spec's question). Its diagnostic script
(`scripts/analysis/regime_boundary_churn_check.py`) exists and is tested but has never
been run against real data - no results to reuse. Both diagnostics stem from the same root
cause (hard-threshold labeling, zero hysteresis) surfacing in two different downstream
systems; neither supersedes the other.

### Two problems todo 005 conflated

- **Noise-driven mislabeling** - the label flickers near a threshold boundary. Smoothing
  at the source addresses this, for every consumer of `market_regimes`, not just IC
  measurement.
- **Genuine-transition settling contamination** - even a real, confirmed regime change
  has bars where the old regime's dynamics still linger. Smoothing does not fix this.
  This is what todo 005's purge-window proposal actually targets.

Without addressing the first, a purge window sized against today's data quarantines bars
around a transition set that is roughly half spurious on equity/5m and almost entirely
spurious on rates/5m.

**Caveat on the 52.1% figure itself:** it is a descriptive statistic, not proof that
sub-3-bar runs are noise rather than genuine but brief regime changes. A rigorous null
baseline - phase-randomizing the underlying signal via `_circular_shift_null`
(`src/intelligence/statistics/ic_math.py:180`) and re-bucketing it to get the run-length
distribution expected under a no-real-regime-structure null - would settle that. It is
deliberately out of scope here, because nothing in this design gates on the 52.1% number:
the design tests smoothing's IC effect directly. If that number is ever used as
standalone evidence for a decision, build the null baseline first.

---

## Why measure before implementing

Both candidate mechanisms are hypotheses, not obviously-good engineering hygiene.
Smoothing "looks like" a fix because `regime_writer.py` already does it for a different
signal (HMM posterior vs. threshold bucketing) - that is an analogy, not evidence.
Smoothing trades noise-reduction against responsiveness: for a 5m momentum feature,
suppressing a genuine fast regime shift to kill flicker could cost more IC than it saves.
Which effect dominates is unknown until it is measured, and it plausibly differs by
timeframe.

The durable precedent for this discipline in this codebase:

- `docs/foundation/principles.md`: "Earn the right through proof. No model, strategy, or
  feature gets promoted to production without statistically significant evidence
  (p < 0.05, sufficient N). Shadow mode first, always."
- `scripts/ops/alpha/ops_lookahead_horizon_response.py`'s own module docstring, on the
  limit of what a diagnostic like this can prove: *"this recheck runs on the SAME sample
  that produced the shortlist. Fixing the CI calibration does not fix winner's-curse
  selection bias… Treat a pass here as 'worth escalating,' not 'confirmed.'"* This spec
  answers that caveat structurally by adding a real held-out period (see Component 5),
  which that script does not have.

Applied here one level earlier than usual: to the mechanism's *value*, not just its
safety.

---

## Architecture

One new read-only diagnostic script,
`scripts/ops/alpha/ops_regime_transition_quality.py`, modeled directly on the existing
`ops_lookahead_horizon_response.py` precedent: read-only, no persistence, no production
writes, exit code always 0 (informational). A cheap Fisher-z sweep over a parameter grid
narrows to a shortlist; a `--bootstrap`-gated confirmation pass on a held-out period
produces the actual verdict using a paired ΔIC block bootstrap.

It computes IC under three label-quality treatments - `baseline` (today's, unchanged),
`smoothed`, and `smoothed_purged` - and reports whether either treatment moves IC by a
real, statistically distinguishable amount on data the parameter search never saw.

Order of operations is fixed and non-negotiable, because several of the findings this
design corrects were caused by doing these in the wrong order:

```
1. Restrict market_regimes.ts to feature_vectors.bar_ts for that tf   (population fix)
2. Build the contiguous combined-label series over the joinable bars   (ordered by ts)
3. Apply combined-label smoothing over the FULL contiguous series      (once, not per-split)
4. Compute the post-treatment transition census                        (per grid point)
5. Build purge_back / purge_fwd masks around surviving transitions
6. Split into selection / holdout periods at --split-date
7. Fetch feature_vectors x forward_returns for the group's peer symbols
8. Per scale: stride-subsample (mirroring production)
9. Per stratum: Fisher-z sweep (selection) -> shortlist -> paired ΔIC bootstrap (holdout)
```

---

## Components

### 1. Label-quality variant generator (in-script, never persisted)

Input: for one `(regime_group, tf)`, the `market_regimes.regime_label` series restricted
to joinable `ts` (step 1 above) and ordered by `ts`. Note that "consecutive bars" from
here on means consecutive *joinable* bars - which is the right unit, since that is the
sequence IC actually consumes.

Three parallel label sequences:

- **`baseline`** - unchanged, exactly as `market_regimes` has it today.

- **`smoothed`** - the **combined categorical label** run through a min-hold-period
  confirmation smoother: `_smooth_states()`'s exact algorithm
  (`services/regime_writer.py:306`) generalized from `np.ndarray[int]` to string dtype.
  The generalization is trivial (the function only ever does equality comparison and
  assignment; `np.all(window == raw[t])` works unchanged on an object/`<U16` array), and
  the causal, no-look-ahead property carries over unchanged.

- **`smoothed_purged`** - `smoothed`, plus an exclusion mask around each *surviving*
  (already noise-filtered) transition. See Component 3 for the mask's two-sided
  construction.

#### Why the combined label, not the two tier dimensions independently

An earlier draft smoothed the two underlying tier dimensions (e.g. equity's vix
percentile tier × breadth tier) separately and recombined them. **That does not have the
property the mechanism exists to provide.** Worked counterexample with equity's live tier
vocabularies from `breadth_vol.build_tiers()` - `{low, mid, high}` × `{bear, neutral,
bull}` - at `min_hold=3`:

| t | event | combined label |
|---|---|---|
| ≤5 | - | `low_bull` |
| 6 | vix dimension confirms low→mid | `mid_bull` |
| 7 | breadth dimension confirms bull→neutral | `mid_neutral` |
| 9 | vix dimension confirms mid→high | `high_neutral` |
| 10 | breadth dimension confirms neutral→bull | `high_bull` |

Combined-label run lengths: 1, 2, 1, 2 - the exact sub-3-bar flicker the mechanism exists
to eliminate, produced *by* a mechanism nominally configured at `min_hold=3`. Each
dimension independently honors its 3-bar hold; their interleaving does not. **The
combined label's guaranteed minimum hold under independent per-dimension smoothing is 1
bar, not `min_hold`.** Since the combined label is what `feature_ic_scores.regime`
stores, what `_compute_cross_sectional_tf` strata by, and what every downstream consumer
of `market_regimes` reads, per-dimension smoothing measures a guarantee nobody gets.

Smoothing the combined label directly gives the guarantee by construction: a run in the
smoothed output is, by the smoother's own invariant, at least `min_hold` bars long.

This is also the strictly simpler design (Musk step 2 - delete before optimizing):

- It needs only `market_regimes.regime_label`, which the script already reads. No
  dependency on `src/intelligence/regime_signals/REGISTRY`, no `build_tiers()` call, no
  re-derivation of tier components, no `regime_prob_vector` read.
- It has no stale-schema failure mode (see the `regime_prob_vector` note below).
- It sidesteps the "is splitting `regime_label` on `_` safe?" question entirely - the
  string is never decomposed. (It would not have been safe: `commodity_momentum_ts`'s
  tier vocabulary includes `up_primary`, `down_secondary`, etc., which themselves contain
  underscores.)
- It is 30 lines of dtype generalization instead of a second, parallel data path.

Both correctness and simplicity point the same way. Combined-label smoothing is the
chosen design; per-dimension smoothing is rejected, not deferred.

#### `regime_prob_vector` is a landmine - flagged, not this spec's problem

Because of the decision above, this diagnostic never reads `regime_prob_vector`. It is
worth recording anyway, since the next consumer will hit it. Verified 2026-08-02 by
direct query: **`regime_prob_vector`'s stored keys are inconsistent within every
`(regime_group, tf)` cell for `rates`** - the same cell contains rows keyed
`curve_z`/`credit_z` (the pre-2026-07-24 z-score construction) and rows keyed
`curve_pct`/`credit_pct` (the current percentile-rank construction, per
`curve_credit.PROB_KEYS`):

| regime_group | tf | rows with `curve_pct` | rows with `curve_z` |
|---|---|---|---|
| rates | 5m | 170,618 | 763,644 |
| rates | 15m | 56,891 | 254,531 |
| rates | 1h | 15,321 | 64,754 |
| rates | 1d | 2,195 | 1,018 |

Worse than a clean time cutover: the two key sets' `ts` ranges overlap almost completely
(rates/15m `_z` spans 2017-08-19 → 2026-07-07, `_pct` spans 2017-10-27 → 2026-07-28), so
the mixture is interleaved, not partitioned by date - the signature of partial backfill
re-runs, not a single migration. `equity` is uniformly `vix_pct`/`breadth_pct` across all
four tfs (no `_z` rows), so this is currently rates-only, but nothing in the schema
prevents it recurring anywhere. Any future consumer of `regime_prob_vector` that assumes
one key set per `(regime_group, tf)` will silently drop or mis-key the majority of rows.
Worth its own todo. Out of scope here.

#### Parameter grid - per-tf, never uniform

`min_hold_bars` is denominated per tf, not shared. A 3-bar hold is 15 minutes at 5m and
3 days at 1d - the same number measures different real-world hysteresis per tf. This is
the same defect class `ops_lookahead_horizon_response.py` was corrected for on 2026-07-20
(its module docstring: a uniform bar-count grid *"structurally amputates the design grid
on intraday tfs"*), and the same reason `alpha.ic.lookahead.{tf}.{scale}` exists as a
per-tf key family rather than the four legacy global `alpha.ic.lookahead.{scale}` keys.

```
_MIN_HOLD_GRIDS = {
    "5m":  (1, 3, 6, 12, 26),    # 1 bar .. 1/3 session (78 bars/session)
    "15m": (1, 2, 4, 8, 13),     # 1 bar .. 1/2 session (26 bars/session)
    "1h":  (1, 2, 3, 5, 7),      # 1 bar .. 1 session   (7 bars/session)
    "1d":  (1, 2, 3, 5, 10),     # 1 day  .. 2 weeks
}
```

`min_hold_bars = 1` is the "off" control and is mandatory in every grid: without it the
sweep can only say which non-zero value is best, never whether the mechanism helps at
all. Bars-per-session values are `_BARS_PER_DAY` from
`src/intelligence/regime_signals/tf_window.py`, the project's existing per-tf bar-count
constant - do not re-derive them.

### 2. Post-treatment transition census (reported for every grid point)

For every `(regime_group, tf, min_hold_bars)` cell, report alongside the IC numbers:

- `n_transitions` on the joinable series after treatment
- run-length distribution: count, mean, median, and share of runs under 3 bars
- `n_strata` (distinct labels surviving) and per-stratum occupancy fraction
- any `regime_label` present in `baseline` that is **absent entirely** after treatment

This is not decoration. Without it, a treatment that reduces IC because it failed to
reduce flicker at all is indistinguishable from one that reduced flicker and lost IC
anyway - opposite conclusions with opposite follow-ups. On rates/5m, where 95.7% of
baseline runs are already under 3 bars, a `min_hold=3` treatment reshapes essentially the
entire series; on equity/1d it may change almost nothing. The census is how the reader
knows which regime they are in.

The disappearing-label check is the sharp edge (see Component 7).

### 3. Purge mask - two mechanisms, split apart, per-tf

The earlier draft used a single symmetric `purge_bars` on both sides of a transition.
That conflates two different contaminations with two different correct widths:

- **`purge_back`** - bars *before* a transition whose forward return spans the
  transition. A bar at `T` labeled regime A, whose `return_extended` is measured over
  `[T+1, T+1+L]` where the regime flips at `T+k` for `k < L`, is attributed to A but its
  outcome is partly generated by B. The correct width is not a free parameter: it is
  **`max(purge_back_grid_value, lookahead_bars)` evaluated per scale**, because a
  `purge_back` shorter than the scale's own lookahead does not remove the contamination
  it exists for. Live per-tf lookaheads (`alpha.ic.lookahead.{tf}.{scale}`, verified
  2026-08-02): 5m = 1/6/12/39, 15m = 1/2/5/10, 1h = 1/2/20/60, 1d = 1/2/5/10. So 5m's
  `extended` scale needs `purge_back ≥ 39` regardless of what the grid says, and 1h's
  needs `≥ 60`. This mirrors `ic_engine.py`'s existing per-scale embargo
  (`embargo_bars = lookahead_bars`, `services/ic_engine.py:2838`) - same reasoning, one
  step further.

- **`purge_fwd`** - bars *after* a transition where the new regime's label is correct but
  the old regime's dynamics are still settling. Width unknown; this is exactly what
  Component 6's decay curve exists to estimate. It is a free grid parameter.

```
_PURGE_FWD_GRIDS = {          # purge_back grid; effective width = max(value, lookahead_bars)
    "5m":  (0, 3, 6, 12, 26),
    "15m": (0, 2, 4, 8, 13),
    "1h":  (0, 2, 3, 5, 7),
    "1d":  (0, 1, 2, 3, 5),
}
_PURGE_BACK_GRIDS = same shape   # 0 is the off-control on both axes
```

`0` on both axes is the mandatory off-control, for the same reason `min_hold=1` is.

**On acausality:** `purge_back` looks forward from the excluded bar to decide whether to
exclude it. That is acausal by design and it is fine here, because this is a measurement
diagnostic reading a fixed historical corpus, not a live execution path - `ic_engine.py`
itself already applies a lookahead-sized embargo on the same basis. Note carefully that
the causal/no-look-ahead unit-test requirement in the Testing section applies to **the
smoother**, where it is a real correctness property, and must not bleed into the purge
design. A purge is allowed to see the future; a label generator is not.

### 4. IC computation - mirror production exactly, do not reinvent

The production join this must reproduce is `_compute_cross_sectional_tf`
(`services/ic_engine.py:3006`). Its actual shape, per timestamp chunk:

```sql
SELECT fv.bar_ts, {feature_cols}, {return_cols}, {complete_cols}
FROM feature_vectors fv
INNER JOIN forward_returns fr
    ON fr.symbol = fv.symbol
   AND fr.tf     = fv.tf
   AND fr.bar_ts = fv.bar_ts
   AND fr.return_type = 'executable_open_to_open'
WHERE fv.tf     = %(tf)s
  AND fv.bar_ts = ANY(%(ts_chunk)s)
  AND fv.symbol = ANY(%(symbol_list)s)
ORDER BY fv.bar_ts
```

Non-negotiable details to carry over verbatim:

- **`feature_vectors`' time column is `bar_ts`, not `ts`.** (`market_regimes`' is `ts`;
  `market_data_ohlcv`'s is `timestamp`. All three differ. The earlier draft of this spec
  had `feature_vectors (symbol, tf, ts, ...)`, which is wrong and would not compile.)
- **`fr.return_type = 'executable_open_to_open'`** - Invariant 1. Theoretical
  close-to-close returns overstate IC and must never be used.
- **`complete_{scale}` gating** per scale, exactly as production does.
- **Chunk the `bar_ts = ANY(...)` list** (`cs_chunk_ts`, default 5000). The unchunked
  form OOM-kills the PostgreSQL backend on large cells; this is documented at
  `ic_engine.py:3160`.
- **Symbol routing must reuse `_build_symbol_regime_class`
  (`services/ic_engine.py:272`) verbatim** - import it, do not reimplement it. It maps
  each symbol to exactly one regime group by tag prefix, **raises
  `AmbiguousRegimeGroupError` (`ic_engine.py:261`) when a symbol matches more than one
  enabled group**, and **omits symbols matching no enabled group** rather than defaulting
  them to `equity`. Both behaviors are load-bearing (the default-to-equity bug silently
  put bonds, gold and bitcoin ETFs under the SPY-vol × equity-breadth regime). A
  diagnostic whose peer set diverges from production's is measuring a different
  experiment than the one whose result it claims to inform.

**Stride subsampling (mandatory, was entirely absent from the earlier draft).** Mirror
`ic_engine.py:2839` exactly:

```python
scale_stride = max(config.subsample_min_stride, lookaheads[scale])   # alpha.ic.subsample_min_stride = 5
X_sub = X_raw[0:n_raw:scale_stride]     # slice, not fancy-index: returns a view, not a copy
```

Two reasons it is mandatory here specifically:

1. It is what production does, so omitting it measures a different quantity.
2. **The Fisher-z sweep is biased toward the hypothesis without it.** Fisher-z's
   half-width is a function of nominal `N` only. Smoothing increases within-stratum
   serial autocorrelation *by construction* - that is literally its mechanism, converting
   scattered short runs into contiguous ones - so at equal nominal `N` the smoothed arm's
   effective independent `N` is lower while its Fisher-z CI is identical. Fisher-z
   therefore overstates precision *more* for the smoothed arm, in exactly the direction
   being tested. `ops_lookahead_horizon_response.py` was corrected for the same omission
   on 2026-07-20 ("*the flat CI half-width across 1d's whole grid in the original
   (unstrided) run was this artifact, not real*"). Do not repeat it.

Honest caveat on stride in the cross-sectional path: production strides over the pooled
`(bar_ts, symbol)` row matrix ordered by `bar_ts`, so with many peer symbols per
timestamp a stride of 39 does not advance a full timestamp. Its decorrelation effect is
consequently weaker here than in the per-symbol path. That is production's behavior and
this diagnostic mirrors it rather than "improving" it - and for the Δ comparison the
identical stride is applied to both arms over a shared row index, so whatever residual
dependence it leaves cannot bias the difference in either direction. It is the *level* of
each arm's Fisher-z CI that is untrustworthy, which is precisely why the verdict comes
from Component 5's paired bootstrap and not from Fisher-z.

**What the Fisher-z sweep may and may not be used for.** It selects the shortlist by
**IC magnitude and aggregate curve shape only** - median `|IC|` across the active feature
family, and how that median moves across the grid. It must **not** rank grid points by
per-feature significant-count. `ops_lookahead_horizon_response.py`'s own documented
rationale: Fisher-z was found empirically miscalibrated on this corpus at a rate (~30% on
canaries) matching `ops_ic_null_calibration.py`'s ~38% SUSPECT rate, so a raw or FDR
"significant" count built on Fisher-z *"cannot be trusted feature-by-feature, only as an
aggregate curve-shape signal."*

**Per-arm columns reported separately, never conflated.** For each arm at each grid point,
per `(regime_group, tf, regime_label, scale)`:

| column | meaning |
|---|---|
| `n_obs` | strided, complete-gated observation count entering IC |
| `median_abs_ic` | median `\|IC\|` across the 244 `status='active'` features |
| `median_ci_halfwidth` | median Fisher-z CI half-width across the same 244 |
| `n_transitions`, `pct_runs_lt3` | post-treatment census (Component 2) |
| `n_strata`, `occupancy` | post-treatment stratum shape (Component 7) |
| `canary_raw_sig` | of the 5 `status='candidate'` canaries (Component 8) |

Power (`n_obs`, hence CI width) and signal (`median_abs_ic`) are separate columns because
a treatment that shrinks `N` mechanically widens CIs, and reading a single conflated
"significant count" as a signal measurement is how that becomes a false conclusion. Same
requirement `ops_lookahead_horizon_response.py` states for itself.

`feature_registry` currently has 244 `active` and 5 `candidate` rows (verified
2026-08-02). Load these from the table at runtime, never hardcode the counts.

### 5. Paired ΔIC bootstrap - new code, and the only thing the verdict may rest on

The quantity that answers this spec's question is `ΔIC = IC_treatment − IC_baseline` for
the same feature, in the same stratum, measured on **mostly the same bars**. No existing
function computes this correctly.

`fisher_z_difference_p` (`src/intelligence/statistics/ic_math.py:507`) exists and looks
applicable, but is **not sufficient here, by its own docstring**: it implements the
standard two-*independent*-correlations Fisher-z difference test, and states explicitly
that *"when the two estimates are measured on the same bars with largely overlapping
alpha constructions… their estimation errors are positively correlated, so the true
standard error of the difference is smaller than this formula assumes - the returned
p-value is therefore an overestimate, biased toward NOT rejecting H0."* Baseline vs.
smoothed labels on the same corpus is that overlapping case in its purest form: the two
strata often share the large majority of their bars. Using it would systematically fail
to detect a real effect, and - worse for a spec that also wants to detect *harm* - would
do so in a way that superficially resembles a clean null result.

So the diagnostic implements a genuine paired bootstrap. New function, to live beside the
script (or in `ic_math.py` if a second caller appears; one caller does not justify Ring-0
placement yet):

```python
def paired_delta_ic_bootstrap(
    X_raw: np.ndarray,          # [n, p]  RAW (unranked) features, rows ordered by bar_ts
    Y_raw: np.ndarray,          # [n]     RAW forward returns, row-aligned to X_raw
    member_a: np.ndarray,       # [n]     bool: row is in this stratum under arm A (baseline)
    member_b: np.ndarray,       # [n]     bool: row is in this stratum under arm B (treatment)
    block_size: int,            # APR: alpha.ic.bootstrap_block_size.{tf}
    n_boot: int,                # APR: alpha.ic.bootstrap_resamples (2000)
    rng: np.random.Generator,   # seeded via ic_engine._derive_worker_rng_seed(cell_key, seed)
    min_reliable_n: int,        # APR: alpha.ic.min_reliable_n (100)
    max_workers: int = 1,       # APR: alpha.ic.cross_sectional_bootstrap_threads.{tf}
) -> PairedDeltaResult:
    """Percentile CI and two-sided p-value for IC_b - IC_a, per feature, on paired
    block resamples of a COMMON row index shared by both arms."""
```

Returning:

```python
@dataclass(frozen=True)
class PairedDeltaResult:
    delta_ic:   np.ndarray   # [p] point estimate on the full sample: IC(b) - IC(a)
    delta_lo:   np.ndarray   # [p] 2.5th percentile of the paired Δ replicate distribution
    delta_hi:   np.ndarray   # [p] 97.5th percentile
    p_two:      np.ndarray   # [p] two-sided p-value, for apply_bh_fdr
    n_a: int; n_b: int       # full-sample stratum membership counts, reported not hidden
    n_degenerate: int        # replicates dropped for falling under min_reliable_n
```

Mechanics, per replicate `b` (block-resampling identical to
`_circular_block_bootstrap_ic` at `ic_math.py:207`; what is new is doing two arms inside
one replicate):

1. Draw block starts over the **common** index once:
   `starts = rng.integers(0, n, n_blocks)`;
   `idx = (starts[:, None] + offsets).ravel()[:n] % n`.
   The circular wrap eliminates series-edge discontinuities (D-15). Drawing **once per
   replicate and reusing `idx` for both arms is the pairing** - it is the entire point,
   and the one thing that must not be "simplified" later.
2. `mask_a = member_a[idx]`, `mask_b = member_b[idx]`.
3. If `mask_a.sum() < min_reliable_n` or `mask_b.sum() < min_reliable_n`, this replicate
   contributes `NaN` and increments `n_degenerate`. Report `n_degenerate`; a cell where
   it exceeds 10% of `n_boot` is reported as unreliable rather than silently
   percentile-ed over a thin surviving subset.
4. `ic_a = _vectorized_ic(rankdata(X_raw[idx][mask_a], axis=0), rankdata(Y_raw[idx][mask_a]))`;
   `ic_b` likewise with `mask_b`.
   **Re-ranking inside the loop is mandatory** - `_circular_block_bootstrap_ic`'s
   docstring documents this as the exact bug that caused its original 2026-06-26 removal:
   reusing globally-precomputed ranks and indexing into them with a non-contiguous
   resample silently narrows the CI.
5. `deltas[:, b] = ic_b - ic_a`.

After the loop:

- `delta_ic` = full-sample `IC(member_b) − IC(member_a)`, not the bootstrap mean.
- `delta_lo`, `delta_hi` = 2.5 / 97.5 percentiles over finite replicates.
- `p_two = 2 * min(mean(Δ ≤ 0), mean(Δ ≥ 0))`, floored at `1 / n_boot` - a hard zero
  breaks BH-FDR's ordering and must not be emitted.

Per-iteration allocation, not an `(n_boot, n_blocks, block_size)` broadcast: at
production cell sizes the broadcast form allocates ~7.5 GB per worker and OOM-kills
(`ic_math.py:242`). Threading, if used, must keep the RNG draw strictly serial and write
results back at absolute iteration index, never in completion order - same contract as
`_circular_block_bootstrap_ic`.

`p_two` is what feeds `apply_bh_fdr` (`ic_math.py:545`). The gate is on ΔIC, never on a
difference of two independently-computed significant-feature counts.

### 6. Out-of-sample split (`--split-date`)

Hard rules, stated as rules and not as guidance, because each one is a degree of freedom
that would otherwise silently invalidate the result:

1. **Smoothing and purging are applied once, over the FULL contiguous joinable series,
   and only then split.** Re-applying the smoother per split corrupts its warmup: the
   first `min_hold` bars of the holdout would be forced to the holdout's own first
   observed label rather than carrying the state the smoother genuinely held coming in
   (`_smooth_states` initializes `current = raw_states[0]` and holds it through
   `t < min_hold`). At `min_hold=26` on 5m that is a fabricated 26-bar block at exactly
   the boundary the holdout's credibility depends on.
2. **The holdout is the LATER period.** Selecting on late data and confirming on early
   data leaks in the direction that matters.
3. **`--split-date` is fixed before any result from either period is read.** Not tuned,
   not re-picked after a disappointing holdout. It is chosen from data availability alone
   - e.g. a date leaving ≥ 30% of joinable bars in the holdout for the thinnest
   `(regime_group, tf)` in the run. The script prints the chosen date, both period row
   counts, and both periods' per-stratum `n_obs` **before** printing any IC.
4. The Fisher-z sweep runs on the selection period only. The paired bootstrap runs on the
   holdout period only. Neither ever sees the other's period.

Rule 3 is the one most likely to be quietly violated by a future operator re-running the
script. State it in the script's `--split-date` help text, not only here.

### 7. Blast-radius diagnostics (first-class output, not an appendix)

Smoothing at the label source changes `market_regimes` for **every** consumer, not just
this diagnostic's IC numbers. Two specific risks must be measured and reported per
variant:

**(a) A rare label can vanish entirely.** Equity/5m's thinnest joinable strata are
`high_bull` (13,035 bars) and `low_bear` (20,929 bars). If a stratum's runs are all
shorter than `min_hold`, the smoother never confirms it and the label disappears from the
series. Downstream that means its `feature_ic_scores` rows are never written, which
changes cross-sectional POOLED ensemble eligibility - `_compute_cross_sectional_tf` keys
results on `regime=regime_label`, and group identity is *implicit in regime_label string
uniqueness* (there is no `regime_group` column on `feature_ic_scores`; see
`_assign_labels`' LABEL-VOCABULARY-UNIQUENESS INVARIANT docstring at
`cross_sectional_regime_model.py:224`). A silently vanishing stratum is therefore a
silent change to what the ensemble is allowed to train on. Report every label present in
`baseline` and absent after treatment, explicitly and loudly, per grid point.

**(b) Occupancy shifts across all strata.** Report per-variant `n_strata` and the full
per-stratum occupancy fraction, so a treatment that "improves IC" by quietly reallocating
half of one stratum into its neighbor is visible as what it is.

Neither of these gates this script's verdict on its own. Both are mandatory inputs to the
follow-on implementation spec, which is where a source-side change would actually be
made.

### 8. Controls

- **Canary carry-through (mandatory).** The 5 `feature_registry.status='candidate'`
  canary/placebo features are null by construction. They must be carried through **every
  arm and every grid point**, with their significant-count reported per arm as a separate
  column. Their purpose here is not the usual CI-calibration check - it is a
  **confound detector**: canaries have no real signal under any labeling, so if the canary
  significant-count *moves* between the baseline and smoothed arms, the measurement
  apparatus is responding to the treatment rather than to signal, and the whole comparison
  is invalid regardless of what the active features show. A stable canary count across
  arms is a precondition for reading the active-feature result at all.
- **Off-controls in the grid**: `min_hold_bars = 1`, `purge_fwd = 0`, `purge_back = 0`.
  Already specified in Components 1 and 3; restated because they are controls, not just
  grid endpoints.
- **`min_reliable_n` floor**: use production's `alpha.ic.min_reliable_n` (= 100, verified
  2026-08-02), applied per stratum per scale after striding and complete-gating, exactly
  as `ic_engine.py:2852` and `:2861` do. **This is a real risk of the purge treatment,
  not a formality:** purging is subtractive by definition, and it subtracts hardest from
  exactly the thin strata (`high_bull`, `low_bear`) where transitions are proportionally
  most frequent. A wide `purge_back` on 5m's `extended` scale - floored at 39 bars, so
  79 bars removed per transition two-sided - can push a thin stratum under the floor and
  drop it from the comparison. Report `n_obs` before and after purge per stratum, and
  report which strata fell under the floor, rather than letting them disappear from the
  output table.
- **Shortlist size - decided, not left open.** The Fisher-z selection pass emits
  **exactly one** shortlisted grid point per `(regime_group, tf)` per treatment family
  (`smoothed`, `smoothed_purged`) - the one with the best aggregate curve position by
  `median_abs_ic`. One point per cell per family means the holdout's BH-FDR family is
  cleanly "the 244 active features for this cell under this treatment", which is the same
  family shape production's own gate uses. If a future revision wants a multi-point
  shortlist, BH-FDR on the holdout must then correct across `(shortlist member × feature)`
  jointly, not per-member - but that is not this design. One point.

### 9. Decay-curve diagnostic (informational)

Independent of the parameter grid: on the joinable series, compute median `|IC|` binned
by "joinable bars since the last surviving transition" (0, 1, 2, … up to a per-tf cap of
one session's bars, or 20 for 1d), per `(regime_group, tf, scale)`.

Purpose: distinguish a step function (supporting a hard `purge_fwd` width) from a smooth
decay (favoring a graded weight, or a different width than any grid value). This is the
only direct evidence available for how wide `purge_fwd` should be - `purge_back` is
pinned by the lookahead and needs no curve.

Informational only. It informs the follow-on implementation spec's mechanism choice and
does not gate this script's verdict.

---

## Data Flow

```
market_regimes (regime_group, tf, ts, regime_label)
  |
  +-- restrict ts to feature_vectors.bar_ts for that tf         <-- FIRST, always
  |     equity/5m: 2,083,837 -> 387,974 rows (18.6%)
  |
  +-- order by ts -> contiguous combined-label series over joinable bars
  |
  +-- combined-label min-hold smoother (string-dtype _smooth_states), FULL series
  |     -> post-treatment census: n_transitions, run-lengths, n_strata, occupancy,
  |        vanished labels
  |
  +-- purge masks around surviving transitions:
  |     purge_back = max(grid_value, lookahead_bars[tf][scale])   (per scale)
  |     purge_fwd  = grid_value                                    (per tf)
  |
  +-- split at --split-date: selection (earlier) | holdout (later)
  |
  v
per (regime_group, tf): symbols = _build_symbol_regime_class(tags, alpha.regime.groups)
  |
  v
feature_vectors fv INNER JOIN forward_returns fr
    ON fr.symbol=fv.symbol AND fr.tf=fv.tf AND fr.bar_ts=fv.bar_ts
   AND fr.return_type='executable_open_to_open'
  WHERE fv.tf=$tf AND fv.bar_ts = ANY($ts_chunk) AND fv.symbol = ANY($symbol_list)
  |
  +-- per scale: stride = max(alpha.ic.subsample_min_stride, lookahead_bars[tf][scale])
  |              gate on complete_{scale}
  |
  +-- SELECTION period: Fisher-z sweep over the full per-tf grid
  |     rank by median_abs_ic / aggregate curve shape ONLY (never by sig-count)
  |     -> exactly 1 shortlisted grid point per (regime_group, tf) per treatment
  |
  +-- HOLDOUT period: paired_delta_ic_bootstrap(baseline vs. treatment) per stratum
  |     -> delta_ic, delta_lo, delta_hi, p_two per feature
  |     -> apply_bh_fdr(p_two, alpha.ic.fdr_alpha) over the 244 active features
  |
  v
per-(regime_group, tf) verdict: IMPROVES | HARMS | NO EFFECT | INSUFFICIENT
```

No writes anywhere. No `config_state` changes. No mutation of `market_regimes`. Exit code
always 0.

---

## Error Handling / Edge Cases

- **Groups with no data are out of scope, explicitly.** `alpha.regime.groups` currently
  enables `equity`, `rates`, and `fx`; the three `commodity_*` sub-groups are
  `enabled:false`. `market_regimes` has rows for `equity` and `rates` only - **`fx` was
  enabled 2026-08-01 (todo 224) and has zero rows.** The diagnostic enumerates enabled
  groups, reports `insufficient_history` for any with zero joinable rows, and continues.
  It never crashes the whole run on one empty group, and it never reports a verdict for
  one.
- **Latent bug flagged, not fixed here:** `_bucket()`
  (`cross_sectional_regime_model.py:197`) requires tier lists sorted **ascending** by
  upper bound with the last entry `inf`. `breadth_vol.build_tiers` and
  `curve_credit.build_tiers` satisfy this. `commodity_momentum_ts.build_tiers` returns
  `[("up_primary", primary), ("up_secondary", 0.0), ("down_secondary", -primary)]` -
  descending, no `inf` terminator - and `fx_dollar_carry.build_tiers` returns
  `[("strong_dollar", d), ("weak_dollar", -d)]` and a single-element `[("risk_on", c)]`,
  likewise. Under `_bucket` these do not mean what their names suggest. This diagnostic
  never calls `build_tiers()` (Component 1's combined-label design removed that
  dependency), so it is not blocked by this, but the diagnostic does enumerate groups and
  the next person to enable a commodity or fx group will ship wrong labels. One line,
  worth its own todo.
- **Thin cells**: report `n_obs`, `n_transitions`, and `n_degenerate` per cell explicitly,
  so a thin cell's result is never read with the same confidence as equity/5m's. A cell
  under `min_reliable_n` after striding, gating, and purging is reported as
  `below_floor`, not omitted - a silently missing row and a measured-and-too-thin row are
  different facts.
- **Label vanishing**: a stratum present in baseline and absent under treatment produces
  an explicit `VANISHED` row in the output, never a silently missing comparison.
- **`AmbiguousRegimeGroupError`** from `_build_symbol_regime_class` propagates and aborts
  the run. It signals a genuine `tag_filter` config error; catching it would mean
  measuring against a peer set that differs from production's. Loud crash over silent
  wrong answer.

---

## Testing

All tests here are **new**. An earlier draft said to "mirror `regime_writer.py`'s existing
smoother tests" - verified 2026-08-02, those do not exist. `_smooth_states` has exactly
two references in the entire repo (its definition at `services/regime_writer.py:306` and
its single call site at `:662`) and zero test callers.
`tests/unit/test_regime_writer_occupation_gate.py` has a local variable named
`smoothed_states` but constructs it by hand and never invokes the function.

So this work must:

1. **Add the missing tests for the production integer `_smooth_states` too.** This is
   currently untested load-bearing code on the live per-symbol HMM label path. Since this
   work generalizes the function for string dtype anyway, backfilling the integer tests
   is nearly free and closes a real gap rather than adding coverage only to the new
   variant. Cover: `min_hold <= 1` returns an unchanged copy; a run shorter than
   `min_hold` never appears in the output; a run of exactly `min_hold` does; the first
   `min_hold - 1` bars hold the initial state; and - the property that matters most -
   **causality: `smoothed[:t]` is identical whether the input is truncated at `t` or
   extends past it.** No look-ahead.
2. **String-dtype smoother tests**: the same five properties on a `<U16` / object array,
   plus the specific guarantee this design depends on - **every run in the output is at
   least `min_hold` bars long** - asserted directly, and the Component 1 counterexample
   encoded as a regression test (per-dimension smoothing at `min_hold=3` producing 1- and
   2-bar combined runs) so nobody re-introduces the rejected design.
3. **Purge-mask tests**: `purge_back` uses `max(grid_value, lookahead_bars)` per scale
   (assert that a grid value below the lookahead is overridden upward, the whole reason
   the split exists); `purge_fwd` uses the grid value; both are zero-width at their
   off-control; masks land on the correct side of a transition; a transition near a series
   edge does not index out of range.
4. **`paired_delta_ic_bootstrap` tests**: identical `member_a`/`member_b` yields
   `delta_ic == 0` exactly and a CI straddling zero; a synthetic injected IC difference is
   recovered with the CI excluding zero; the same `rng` seed reproduces bit-identical
   output; `n_degenerate` increments when a stratum falls under `min_reliable_n`; `p_two`
   is never exactly 0.
5. **No integration or DB-durability test.** This is a read-only diagnostic with no
   persistence contract. The DB-shaped risk here is the *join*, not durability - covered
   by reusing `_build_symbol_regime_class` and the production query shape verbatim rather
   than by a new test.

---

## Promotion Gate

Evaluated **per `(regime_group, tf)`**, never pooled. This spec's own reasoning is that
smoothing plausibly helps slow tfs and hurts fast ones; a pooled verdict would average
those into an uninformative null and is therefore structurally incapable of answering the
question asked. Each tf gets its own answer.

For a given `tf` and a given treatment (`smoothed` or `smoothed_purged`), on the
**holdout period only**, using the shortlisted grid point from the selection period:

**PROMOTE** - worth a follow-on implementation spec for that tf - requires all of:

1. **≥ 15% of the 244 `status='active'` features** have paired ΔIC that is
   **BH-FDR-significant at `alpha.ic.fdr_alpha` (0.05) and positive**, in **both**
   `regime_group='equity'` **and** `regime_group='rates'`, for that tf.
   Replication across both groups is required - two timeframes of one group are the same
   underlying signal series over the same peer set and are not independent replication.
2. Canary significant-count is **stable between the baseline and treatment arms**
   (Component 8). A moving canary count invalidates the comparison; the result is reported
   as `INVALID`, not as a pass or a fail.
3. No stratum vanished, or every vanished stratum is explicitly accepted with its
   downstream ensemble-eligibility consequence stated (Component 7a).
4. `n_degenerate ≤ 10%` of `n_boot` in every cell contributing to the count.

**HARM** - a distinct, decision-relevant outcome, not a subset of "did not pass":
**≥ 15% of active features** have BH-FDR-significant **negative** ΔIC in both groups for
that tf. This closes todo 005 differently from, and just as validly as, a null result: it
says the mechanism is actively costly at that tf and should not be revisited without a
new argument. Absorbing it into "did not clear the bar" would throw away the more useful
of the two findings.

**NO EFFECT** - neither threshold met, canaries stable, cells adequately powered. Closes
todo 005 as "measured, no detectable effect at this tf," replacing the roadmap doc's
unverified 10-20% claim with an actual measured number.

**INSUFFICIENT** - cells under `min_reliable_n`, `n_degenerate` over threshold, or a group
with no data. Not a verdict. Reported as such, and specifically not reported as
NO EFFECT.

A mixed per-tf outcome (e.g. PROMOTE at 1d, HARM at 5m) is an expected and useful result,
not a failure of the design. It is the single most likely shape of the true answer given
that a `min_hold` of 3 bars means 15 minutes at 5m and 3 days at 1d.

Whatever the verdict, todo 005 closes with a measured number attached, and the
`ops_lookahead_horizon_response.py` caveat still applies in one direction: a PROMOTE here
is evidence worth an implementation spec and a shadow-mode run through
`ic_engine.py`'s own pipeline, not a licence to change `cross_sectional_regime_model.py`
directly.
