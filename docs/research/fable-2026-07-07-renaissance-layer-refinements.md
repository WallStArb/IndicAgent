# Renaissance Layer Refinements - Additive Ideation Across L0-L7 + Governance

**Date:** 2026-07-07
**Author:** Fable 5 (dispatched via Claude Code Agent tool)
**Type:** research/ideation, read-only - additive proposals only; deliberately does not
re-litigate the restructuring decisions in `fable-2026-07-02-v3-topdown-architecture.md`
(layer taxonomy used here) or `fable-2026-07-02-v3-bottomup-audit.md` (ground truth).
**Method:** full read of the two prior Fable passes, STATE.md, ROADMAP v3.15/v3.2/154 sections,
`catalog.md` and the layer-relevant research docs it indexes, plus direct inspection of the live
pipeline (`ic_engine.py`, `ensemble_trainer.py`, `alpha_publisher.py`, `forward_return_writer.py`,
`equity_regime_model.py`, `regime_writer.py`, `feature_factory.py`, `src/intelligence/ensemble/*`)
and live DB state (feature_registry group counts, feature_vectors column population,
forward_returns schema). Every proposal cites what it would mechanically touch.
**Filter applied per idea:** (F) falsifiable with existing or cheap machinery; (O) overfitting
surface named and disciplined; (W) weak-signal diversification, not strong-signal concentration;
(C) cheap-to-falsify path stated before any expensive build.

---

## 1. Executive Summary - Highest-Conviction Ideas Across All Layers

1. **Build the cross-sectional relative-value feature family - the single biggest structural
   hole in L1 (L1-1).** All 152 live features are per-symbol time-series transforms; the system
   has literally zero features that encode "how does this symbol look *relative to the universe
   right now*." Worse, the family already half-exists as ghost schema: `momentum_rank_z` /
   `volume_rank_z` / `volatility_rank_z` were designed in Phase 139, are declared in
   `schemas.py:1453` and the persistence SQL (`feature_vector_persistence.py:91,296` - "None
   until Phase 139 enrichment"), and are 0/36.7M populated with no writer anywhere (grep
   verified). Meanwhile the edge-source thesis (`data-edge-source-thesis.md`) identifies T3
   (cross-sectional relative mispricing) as the *lowest-IC-bar thesis on the list*, and the
   ensemble already trains exclusively on cross-sectional POOLED strata. The features that would
   most directly serve the most winnable thesis are the ones that don't exist.
2. **Register negative-control (canary) predictors in every corpus run (G-1).** A handful of
   pure-noise features and deliberately acausal (time-shifted) features, run through the
   identical gate stack every rerun. If any canary ever passes `ic_ci_lower > 0 AND passes_fdr`,
   the multiple-testing discipline is broken and the alarm fires before a real decision is
   contaminated. This is the cheapest integrity instrument available: a few columns, zero new
   services, and it converts "we believe our FDR is calibrated" into a standing measurement.
3. **Add residual (beta-hedged) and vol-normalized outcome targets at measurement time (L3-1,
   L3-2).** Raw executable returns conflate market beta with everything else; for cross-sectional
   and pooled measurement, high-vol symbols dominate raw-return ranks. Both transforms are
   measurement-time joins (no new writer, `forward_returns` stays immutable), and Phase 145's
   tag calibrator is already about to produce the measured betas the residual target needs.
   Pairs directly with the still-unbuilt cross-sectional rank IC mode
   (`measurement-ic-engine.md` Addendum) as T3's honest test.
4. **Add the OHLCV microstructure-proxy family (L1-2): Corwin-Schultz spread, Roll spread,
   Amihud illiquidity.** Computable from bars alone, a genuinely distinct information family
   (liquidity/friction, not price/vol/volume level), and dual-use: the same estimators give
   per-(symbol, tf) empirical spread numbers the canonical simulator's cost kernel currently
   lacks (today's cost hurdles are externally calibrated constants per tf).
5. **Queue regime-posterior soft blending as an E-candidate (L5-1).** `feature_vectors` already
   stores `hmm_prob_trending_up/ranging/trending_down` and `hmm_entropy`; the ensemble discards
   them and keys weights on the hard argmax label, so alpha_score is discontinuous at every
   regime boundary exactly where labels are least certain. Blending stratum alphas by posterior
   is one new `weight_version` variant testable through the already-built
   `ops_ensemble_weight_compare.py` A/B machinery with zero new judge infrastructure.
6. **Adopt anytime-valid sequential testing (e-values) for the corpus-rerun cadence (L4-1).**
   Every corpus rerun re-tests the same ~150 features x strata on overlapping data, and the gate
   stack treats each run as a fresh experiment. E-processes compose across looks by design:
   evidence accumulates or decays monotonically per cell, and "how many reruns have we peeked
   at" stops being an unaccounted-for multiplicity dimension.
7. **Fix the embedding geometry before Phase 148 locks `embedding_version = 1` (L1a-2).** The
   serialization law z-scores per feature then L2-normalizes, which silently weights the distance
   metric by *family population*: 31 volatility columns vs 3 macro columns means "similar" is
   ~10x more about volatility than macro by construction. Family-balanced scaling costs one line
   and zero estimation risk; discovering this after the corpus is embedded costs a full re-embed.
8. **Emit continuous conviction alongside the binary threshold (L6-1).** `alpha_events` already
   carries `alpha_score`, CI bounds, and `cost_hurdle`; a derived conviction column (CI margin
   over hurdle, later replaced by 0c-calibrated probability) lets 142B frames measure whether
   conviction-weighted counterfactual P&L beats flat-weighted, which is the empirical
   prerequisite for v4.0 sizing being anything other than a guess.

Everything below is the per-layer detail plus the cheapest-to-test-first ordering (§12).

---

## 2. L0 Market Facts

The session-mask problem (81% synthetic zero-volume padding, bottomup audit §1.6/§5.9, todo 035,
partial fix `26efb75b`) is already identified and owned; not re-proposed. Two additions:

### L0-1. Dollar-bar shadow clock (information-time sampling pilot)

Time bars sample the market on a wall-clock grid; volume/dollar bars sample per unit of
transacted value, which normalizes for activity bursts and produces returns closer to IID (less
heteroskedastic, thinner tails), improving every downstream estimator without changing any of
them. This is the one L0 idea with plausible direct IC impact rather than hygiene value.

- **Mechanism:** aggregate existing 5m bars into dollar bars (threshold pre-committed: trailing
  median daily dollar volume / 78, one APR key `feature.dollar_bar.divisor`) for a 5-symbol
  pilot. Compute a small existing feature subset (the lagged-return and variance-ratio families)
  on the dollar-bar clock, then join each dollar-bar feature to the *next time-bar* and measure
  against the canonical time-bar executable returns. No change to `forward_returns`, Invariant 1
  untouched, outcomes stay executable.
- (F) Verdict = same feature family, dollar clock vs time clock, side-by-side `ic_engine` run;
  dollar-clock features must show materially tighter IC CIs or higher IC Sharpe to earn a fuller
  build. (O) One new degree of freedom (the divisor), pre-committed before measurement; the
  features themselves are unchanged. (W) A resampling of data already owned, diversifying the
  sampling clock, not a new bet. (C) A one-off script over `market_data_ohlcv` plus a standard
  `ic_engine` invocation; no new service, no schema change beyond a scratch table.

### L0-2. Sub-bar path summaries for HTF bars (realized variance from constituent bars)

The corpus holds 5m bars under every 15m/1h/1d bar, and the HTF feature set never looks inside
its own bars: 1h volatility features are OHLC-estimator approximations (Parkinson/GK/YZ, shipped
in 142.5) of a quantity the 5m data measures directly. Realized variance from constituent 5m
returns, plus intrabar return skew and the signed path (fraction of intrabar movement in the
close's direction), are strictly more information than any single-bar OHLC estimator.

- (F) The GK-vs-realized-variance *gap* is itself a candidate feature (jump/noise decomposition);
  all of it is standard IC screening. (O) 3-4 columns, standard FDR pool; they will cluster with
  the 142.5 vol estimators and LW cluster deflation handles the redundancy. (W) Small incremental
  columns in an existing family. (C) Computable in `backfill_feature_factory` where the LTF data
  already streams past; the one real cost is a cross-TF read, which `feature_cache.py` already
  supports for the `ret_div_*` cross-TF divergences 142.5 deferred (todo 066) - build them in the
  same pass.

---

## 3. L1 Feature Fabric

Live registry by family: volatility 31, volume 30, structure 29, calendar 22, momentum 14,
regime 10, oscillator 6, session 4, cross_tf 3, macro 3 (152 total). Calendar/seasonality is
well covered post-142.5 (sin/cos coordinates, empirically discovered, no theory baked in) -
nothing to add there. Higher moments (skew, kurtosis, vol asymmetry) shipped in 142.5. What is
structurally missing is everything *relational*: every one of the 152 features is a function of
one symbol's own history.

### L1-1. Cross-sectional relative-value family (the ghost columns, finished properly)

**The finding:** `momentum_rank_z`, `volume_rank_z`, `volatility_rank_z` exist in the
`FeatureVector` dataclass, the persistence SQL, and 36.7M database rows - as permanent NULLs.
The comment trail says "populated by Phase 139 enrichment"; no such enrichment was ever built
(grep: zero writers). The corpus audit script even normalized this away ("100% NaN rate ...
expected"). The family was designed, scaffolded, and silently dropped.

**The proposal:** build the cross-sectional enrichment stage and widen the family while at it:

- Per-bar universe percentile rank (causal, current bar across 80 symbols) of: `ret_lag_1`,
  `ret_lag_fast/mid/slow`, `volume_z`, `overnight_gap`, `atr_z` - both against the full equity
  universe and within the symbol's `regime_group` once Phase 144 ships.
- Peer-relative return: symbol return minus regime_group mean return at the same lags
  (the raw material of sector-relative momentum/reversal).
- Cross-sectional dispersion contribution: symbol's |return| rank within the bar's
  cross-sectional return distribution.

**Mechanics:** this cannot live in `FeatureFactory` (per-symbol single-pass, correctly so). It
is a new batch step in the corpus DAG after `backfill_feature_factory` and before
`forward_return_writer`, shaped exactly like `equity_regime_model.py` (cross-sectional reader,
one writer, one fact). Grain note: a per-(symbol, tf, bar_ts) value, so it can legally UPDATE the
reserved `feature_vectors` columns it was always meant to own, or land in a sibling table if the
one-writer-per-table reading of the DAG invariant is preferred - decide at planning, both defensible.

- (F) Standard `ic_engine` measurement; additionally these are the features for which the
  cross-sectional rank IC mode (`measurement-ic-engine.md` Addendum, T3's falsification
  instrument, still unbuilt) gives the honest read - build both in the same phase and each
  validates the other. (O) ~15-20 new columns in the standard corpus-level FDR pool; ranks are
  bounded, no new normalization freedom. (W) This is the canonical Renaissance move: many small
  relative-value signals across a correlated universe rather than one directional conviction.
  (C) Pure derivation from data already in `feature_vectors`; one new batch service + one
  corpus rerun.

### L1-2. Microstructure proxy family from OHLCV

Liquidity and trading friction are an information dimension none of the 152 features measures
(closest existing: `vol_range_ratio`). All estimable from bars alone:

| Feature | Estimator | Notes |
|---|---|---|
| `cs_spread_z` | Corwin-Schultz (2012) high-low spread estimator over 2-bar pairs | z-scored per symbol |
| `roll_spread_z` | Roll (1984): `2*sqrt(-cov(Δp_t, Δp_{t-1}))` where cov is negative | rolling window, APR-backed |
| `amihud_z` | Amihud (2002): mean(`abs(ret) / dollar_volume`) | must respect the synthetic-bar mask (volume=0 rows poison it) |
| `spread_regime_pct` | expanding percentile of `cs_spread` | doubles as an L2 candidate |

**Dual use is the point:** the canonical simulator's one build item is a cost kernel
(`platform-canonical-simulator.md`), currently fed by externally calibrated per-tf constants
(`alpha.quant.cost_hurdle.*`, todo 030). Corwin-Schultz gives a *measured, per-symbol,
per-regime* spread from data already owned - the cost kernel's inputs stop being guesses the
moment this family exists.

- (F) IC screening as usual; separately, the CS spread estimates can be sanity-checked against
  todo 030's external spread table (agreement is the estimator's own validation). (O) 4-6
  columns, standard pool. (W) Adds an orthogonal information family; even if the features carry
  zero IC, the cost-kernel payoff stands alone. (C) Pure `FeatureFactory` additions except
  `amihud_z`'s session-mask dependency, which todo 035 owns anyway.

### L1-3. Lead-lag / peer-influence family (primitive grade)

The archived `cross-group-lead-lag-ic.md` proposed group-state Granger-style tests gated on
Phase 144; it was bulk-archived 2026-07-06 without individual review (catalog Cluster 2 note).
This proposal is deliberately smaller and primitive-grade, per the 142.5 philosophy: no state
machinery, no hypothesis about which pairs lead - just lagged *peer* returns as columns:

- `leader_ret_lag_1/2/3`: SPY's lagged returns as features on every non-SPY symbol (the
  market-leader lag structure; for SPY itself, NULL).
- `group_ret_lag_1/2/3`: the symbol's regime_group mean return at lags 1-3 (Phase 144
  dependency), and `group_ret_div`: own return minus group return at lag 1.

Let IC discover whether industrial-metals-lead-bonds exists rather than encoding it. Same
cross-sectional batch stage as L1-1 (needs other symbols' bars at the same ts).

- (F) Standard IC machinery; the archived doc's candidate-pair table becomes the *interpretation*
  layer for whatever survives, not the input. (O) ~8 columns; lag-1 peer returns will correlate
  with own `ret_lag_1` in high-correlation regimes, which is exactly what LW deflation and the
  (proposed) marginal-contribution 0a screen exist for. (W) Textbook weak-signal add. (C) Rides
  L1-1's infrastructure once it exists; near-zero marginal cost.

### L1-4. Path-complexity / information-theoretic features (small, disciplined)

`efficiency_ratio` and `variance_ratio` (142.5) measure linear trendiness. One nonlinear
complement is worth screening: **permutation entropy** of the last-N returns (distribution of
ordinal patterns; low entropy = structured/predictable path, high = noise). Cheap (O(N) per
bar), bounded [0,1], no distributional assumptions. Deliberately stop there: mutual-information
and transfer-entropy features are expensive, estimator-fragile at these window sizes, and would
be premature before the cheap member of the family shows anything.

- (F/O/C) One column, standard pool, standard screening; it will cluster with efficiency_ratio,
  and if it adds nothing after clustering, it dies at zero cost. (W) One more small candidate.

---

## 4. L1a Analog Substrate

`intel-analog-engine.md` already covers retrieval design, definedness rules, OOD monitoring, and
correctly defers IC-weighted re-ranking. Three additions, all pre-Phase-148-relevant because
embedding decisions are one-way doors (`embedding_version` bump = full re-embed):

### L1a-1. Family-balanced embedding geometry (fix before `embedding_version = 1`)

Per-feature z-score + L2-normalize makes every feature contribute equal expected weight to
cosine distance - which means feature *families* contribute in proportion to their column count.
With today's registry (31 volatility, 30 volume, 29 structure vs 3 macro, 3 cross_tf), "the most
similar historical bar" is dominated by vol/volume/structure resemblance roughly 10:1 over macro
context, as an accident of how many columns each family happened to get. And the ratio changes
every time the feature set grows, silently redefining "similar" between embedding versions.

**Fix:** scale each feature by `1/sqrt(n_family)` (group_name from `feature_registry`) before
L2 normalization, so each family contributes equal total variance. Zero estimation risk, zero
look-ahead surface, one line in the serialization law. The alternative (point-in-time PCA
whitening) is strictly more principled and strictly more fragile (estimated rotation, rolling
recompute, version churn); pre-register it as the challenger, not the default.

- (F) ANALOG-01's calibration study (recall@10, MRR on known-outcome bars) already measures
  retrieval quality across candidates; run it with and without family balancing - the study is
  the test. (O) Adds no tunable beyond family definitions that already exist. (C) Free inside
  the already-planned calibration study; expensive forever if skipped.

### L1a-2. Ensemble-of-metrics retrieval as parallel predictor variants

Rather than one monolithic distance, compute analog predictors from *family sub-vector*
retrievals too: `analog_expected_r_vol` (neighbors by volatility-state similarity only),
`analog_expected_r_momentum`, etc. Each sub-metric answers a different question ("what happened
after similar vol states" vs "after similar momentum states"), and each is just another
predictor column measured by the standard machinery. This is the weak-signal-diversification
answer to metric learning: instead of learning one optimal metric (a large, overfittable
choice), measure several cheap fixed metrics and let the ensemble weight them.

- (F) Each variant is an independently measured predictor; dead variants get zero weight.
  (O) 3-4 extra predictor columns, same FDR pool; retrieval cost scales linearly but the nightly
  batch is offline. (W) Exactly. (C) Marginal: pgvector supports multiple indexes/expressions;
  the pilot can run sub-vector retrieval brute-force on a 6-month window before committing
  indexes.

### L1a-3. Conformal coverage as the analog family's calibration test

The K-neighbor forward-return distribution is a free nonparametric prediction interval. Persist
per-bar analog quantiles (q10/q90) alongside `analog_expected_r`, then measure *empirical
coverage* OOS: the realized forward return should fall inside the 80% interval 80% of the time.
This is layer 0c (calibration, unbuilt, unscheduled per `measurement-ic-engine.md`) arriving for
free for one predictor family - and a coverage failure is an OOD/regime-break signal with a
cleaner statistical interpretation than the raw null-rate monitor.

- (F) Coverage vs nominal is a single scalar per (symbol, tf, regime); binomial test, no new
  math. (O) No tunables. (C) Two extra columns in the planned nightly analog batch plus one
  audit query.

---

## 5. L2 Conditioning / Stratification

The unification contract, candidate list (8 percentile-rank dims, E1-E4, `ood_distance`), and
the demote-to-shadow fallback are settled (`regime-multi-regime-layer.md`,
`fable-2026-07-07-phase144-conditioning-decision.md`); the substitution-test + orthogonality
gate is the entry door for anything below. Two new candidate dimensions and one methodological
refinement:

### L2-1. Realized-correlation regime (co-movement structure, not vol level)

Cross-sectional mean pairwise correlation of universe returns (rolling window, expanding
percentile rank). VIX x breadth measures fear level and participation; average pairwise
correlation measures whether the universe is *one trade or many* - which is precisely the
condition under which cross-sectional features (L1-1) should gain or lose IC, and the
documented precursor of momentum crashes. This is the stratification-shaped descendant of the
archived `comomentum-crowding-metric.md` (whose own recommendation was to decompose crowding
into primitives rather than build the paper's index); a conditioning axis through the standard
gate instead of a bespoke crowding metric.

- (F) Substitution test + orthogonality vs the incumbent dimensions, the machinery v3.15 is
  building anyway. Sharpest pre-registered prediction: L1-1's cross-sectional features show
  materially lower IC in the top correlation decile (nothing to rank when everything co-moves).
  (O) One window APR key; labels are terciles/quintiles, standard N-budget guard applies.
  (W) A conditioning refinement, not a signal. (C) Computed from the same close series
  `equity_regime_model.py` already fetches (`_fetch_spy_bars` generalizes); one more provider
  under the Phase 144 dispatcher.

### L2-2. Liquidity regime (participation percentile)

Expanding percentile rank of universe median dollar volume per bar. Distinct axis from vol and
correlation; directly tests T1 (small-scale immediacy provision), whose falsification condition
is "edge concentrates in less-liquid conditions." If the tag calibrator or emission analysis
ever needs to answer "does our edge live where liquidity is thin," this stratum is the cheap way
to make that a standing measurement. Same mechanics as L2-1, same gate.

### L2-3. Soft stratification: posterior-weighted IC as a variance-reduction refinement

`feature_vectors` already stores full HMM posteriors (`hmm_prob_*`, `hmm_entropy`). Hard-label
stratification throws observations near regime boundaries into one cell at full weight; a
fractional-membership IC (each observation contributes to each stratum weighted by posterior)
uses the same data with strictly more information, shrinking cell-estimate variance exactly
where labels are least certain. Not a new dimension - a refinement of how any *fitted* dimension
(`causality_basis='fitted'`) is consumed by the measurement layer.

- (F) Same corpus, both estimators, compare CI widths and OOS fold stability per cell; the
  posterior-weighted estimator must produce tighter CIs at equal OOS accuracy to win. (O) Zero
  new parameters (posteriors already exist). (W) Pure estimator efficiency. (C) A weighted-rank
  variant inside the kernel (`ic_math.py`); measurable on the existing corpus with no schema
  change. Sequencing note: only worth doing after the Phase 144 widened Step 1 verdicts, since
  demoted-to-shadow HMM groups won't consume it.

---

## 6. L3 Outcomes

`forward_returns` (executable open-to-open, fast/mid/slow/extended, immutable, one writer) is
correct and untouched. All proposals here are *measurement-time transforms* - joins computed
inside the measurement layer, never new columns in the canonical fact table, so Invariant 1 and
the writer contract stay intact.

### L3-1. Vol-normalized return target

`return_x / trailing_sigma(symbol)` (sigma from the already-stored `atr_z` denominator or a
trailing realized vol). Per-symbol time-series Spearman IC is only partially affected (vol
varies through time, so ranks do shift), but the real payoff is cross-sectional and POOLED
measurement, where raw-return ranks are dominated by whichever symbols run hot. Given the
ensemble trains exclusively on POOLED strata (`ensemble_trainer.py:317,430,469,540`), the
pooled IC the whole system keys on is currently vol-biased.

- (F) Re-run the POOLED strata with both targets; if rankings of qualifying features are
  materially identical, the transform is unnecessary and dies. (O) Zero new parameters beyond
  the sigma window, which reuses an existing feature's window. (C) A join + divide inside
  `ic_engine`'s existing corpus load; no migration.

### L3-2. Residual (beta-hedged) return target

`return_x(symbol) - beta * return_x(SPY)`, beta from Phase 145's Instrument Tag Calibrator -
which is already committed to producing measured, FDR-corrected factor betas
(`data-instrument-tag-calibrator.md`). This is the outcome definition T3 actually requires: a
cross-sectional edge is a claim about *idiosyncratic* mispricing, and measuring candidate
features against raw returns lets market-timing leak into what looks like relative-value IC.
The attribution-honesty gate in `trade-construction-layer.md` (spread P&L must not be a static
factor tilt) becomes partially testable at the IC layer, years before a portfolio exists.

- (F) Features whose IC survives against raw returns but dies against residual returns are
  market-timing features wearing relative-value costume; that verdict is the test. (O) Beta
  estimation is owned by Phase 145's own gate discipline; this proposal adds no estimator.
  (W) Sharpens the weakest-signal thesis (T3). (C) Measurement-time join once 145 lands;
  sequence it into the same v3.15 batched rerun.

### L3-3. Frame-outcome labels as a second outcome definition (post-142B, zero new infra)

142B's `alpha_frames` are triple-barrier labels in all but name (stop/target/hold-expiry with
exit-trigger priority). Once frames exist, register the frame outcome (barrier-hit sign,
counterfactual R) as a measurement target alongside fixed-horizon returns for the same events.
Fixed-horizon IC and path-aware outcome agreement/disagreement is diagnostic gold: a predictor
with horizon-IC but negative frame expectancy is being killed by path (stopped out before the
horizon pays), which is an execution-geometry problem, not a signal problem, and the two are
currently indistinguishable.

- (F/C) Pure read over `alpha_frames` x `alpha_events` after 142B ships; explicitly not a
  reason to touch 142B's frozen design now. (O) None; it reuses pre-committed frame geometry.

### L3-4. Overnight/intraday decomposition of the forward horizon

142.5 decomposed *backward-looking* returns (`open_ret`, `intraday_ret`). The same split on the
forward horizon (how much of `return_fast` accrues overnight vs in-session) tells you where the
alpha lives and whether it is capturable at all under different execution styles - overnight
alpha and intraday alpha have different cost/risk profiles. Measurement-time computation from
`market_data_ohlcv` opens/closes; report as a decomposition column in IC diagnostics, not a gate.

---

## 7. L4 Measurement

The known gap list (P1 trailing IC, P5 vintage, P6 cross-sectional effective-N, 0a marginal
contribution, 0c calibration, cross-sectional rank IC mode) is fully catalogued in
`measurement-ic-engine.md` and not repeated - those remain the highest-priority measurement
builds. Additions beyond that list:

### L4-1. Anytime-valid inference (e-values) across corpus reruns

The corpus has been rebuilt 3+ times and reruns are now routine cadence. Each rerun recomputes
p-values over heavily overlapping data, and the BH-FDR correction is *within-run* only: nothing
accounts for the fact that the same hypothesis ("momentum_z_fast predicts 5m returns in
high_bear") has now been examined N times, with promotion possible after whichever look happens
to flatter it. Classical p-values do not compose across looks; e-values do (multiply across
runs, Ville's inequality gives always-valid error control). Concretely: persist a per-cell
e-process updated each corpus run (a likelihood-ratio or universal-inference e-value on the IC
sign is enough); promotion requires cumulative e-value > 1/alpha, demotion symmetric. Evidence
becomes a running account rather than a per-run snapshot, and "wait for another rerun and see if
it passes" stops being a free re-roll. This directly hardens the Concept Registry invariant #2
("no re-roll on same corpus build") into its stronger form: no free re-roll on *any* build.

- (F) The e-process is itself checkable: canary features (G-1) must show e-values that decay
  toward zero. (O) This *removes* an unaccounted multiplicity surface rather than adding one.
  (W) Discipline, not signal. (C) A kernel function (`ic_math.py` sibling) + one column per
  cell + manifest plumbing; no new service. Genuinely new math for the codebase, so pilot on
  one tf first.

### L4-2. Empirical null calibration via circular-shift permutation

The analytic inference chain (stride subsampling -> Spearman -> Fisher-z CI -> HAC Sharpe) rests
on assumptions (post-stride independence, Fisher-z normality at these Ns) that have never been
validated end-to-end on this data. One corpus-run-cadence diagnostic: circularly shift the
forward-return series by a random large offset (preserving all autocorrelation structure,
destroying all alignment), recompute the full IC pipeline, repeat ~200 times for a sample of
cells, and compare the empirical null IC distribution against what the analytic p-values assume.
Related dead weight to resolve in the same pass: the `alpha.ic.bootstrap_*` APR keys exist with
zero readers (bottomup §2.3). The permutation study answers whether a block-bootstrap CI is
needed at all - if analytic and empirical nulls agree, delete the keys with evidence; if not,
implement the block bootstrap in the kernel and the keys finally get their reader.

- (F) The study is self-verdicting. (O) None; it is a calibration audit. (C) A one-off script
  over the existing corpus + kernel functions; expensive only in CPU-hours, which the
  ProcessPoolExecutor pattern already handles.

### L4-3. Winner's-curse correction at champion selection (concretize open question 7)

`measurement-ic-engine.md` OQ7 already flags that the pending E1/E2 A/B judgment selects a
champion per stratum without shrinking the winner's measured IC. The concrete mechanism is
already on the shelf: `shrink_ic()` is grain-agnostic; apply it with peer group = {the variants
compared within that stratum} before `ops_ensemble_weight_compare.py` renders a verdict, or at
minimum record the winner's IC as selection-biased in the decision log. Raised here because the
judgment is the *next pending act* and this is cheaper to do before than to unwind after.

### L4-4. IC decomposition reporting: hit rate x magnitude

A single Spearman IC conflates two economically different properties: directional accuracy
(fraction of sign agreements) and magnitude alignment (are the big predictions the big moves).
Two predictors with identical IC can have opposite profiles, and they decay differently
(magnitude alignment usually dies first as an edge crowds). Report both per cell as diagnostic
columns (no gate change): `sign_hit_rate` and IC-conditional-on-large-|prediction|. Cheap kernel
additions; the decay monitors (Phase 143) get sharper eyes for free.

---

## 8. L5 Combination / Ensemble

E1 (shrunk-IC) and E2 (mean-variance Σ⁻¹·IC) are built; E3 is tentatively pooled-prior
shrinkage (topdown OQ2, unresolved human call). Candidates for the E4+ queue, all expressible as
`weight_version` variants judged by the existing A/B machinery, all inside one-model-one-book:

### L5-1. Regime-posterior soft blending (highest-conviction E-candidate)

Today: `alpha_score(bar) = w[regime_label(bar)] . features(bar)` with hard argmax labels. The
HMM's own posteriors say the label is often 55/45 - and the system already stores them
(`hmm_prob_trending_up/ranging/trending_down`, `hmm_entropy`, and Phase 143's `hmm_churn`).
Proposal: `alpha_score = Σ_r P(r|bar) . (w_r . features)`. Removes the alpha discontinuity at
every boundary crossing (which today manufactures emission churn from label noise), degrades
gracefully exactly where the Phase 144 decision doc worries labels are weakest, and uses zero
new data. Cross-sectional strata get the analogous treatment from `market_regimes.regime_prob_vector`
(already stored as JSONB).

- (F) One new `weight_version`, judged per-stratum by the existing D-10 win rule
  (`challenger.ic_ci_lower > champion.ic_ci_upper AND walk_forward_stable`). (O) Zero new
  parameters; posteriors and per-regime weights both already exist. (W) Softens a hard decision
  boundary - variance reduction, not a bigger bet. (C) A scoring-path change in
  `ensemble_trainer`/`alpha_publisher` behind a variant flag; no new tables.

### L5-2. Hierarchical family-then-feature allocation (HRP-lite)

The 152-feature registry is family-imbalanced (31 vol vs 3 macro), and `cluster_deflate_weights`
caps only *pairwise-correlated* clusters - a family of 31 moderately-correlated features can
still absorb a large total weight through sheer population. Hierarchical alternative: allocate
across families first (by family-level aggregate IC Sharpe), then within family - the ensemble's
weak-signal diversification applied at the family grain, structurally preventing "the ensemble
is secretly one volatility bet." This is hierarchical risk parity's clustering insight with the
tree given by `feature_registry.group_name` instead of estimated (cheaper, stabler, no
estimation risk; an estimated-dendrogram variant can be a later challenger).

- (F) Same A/B judge; additionally compare realized `effective_n` and family weight-share
  concentration between variants. (O) No new estimated quantities in the registry-tree version.
  (C) A pure function in `src/intelligence/ensemble/weights.py` + a variant flag.

### L5-3. Bayesian averaging over variants instead of champion selection

Champion selection per stratum is itself strong-signal concentration at the meta level, with the
winner's-curse bias L4-3 documents. Once 3+ variants exist, the alternative is to *blend*
variants with weights proportional to their accumulated evidence (the L4-1 e-values slot in
naturally as unnormalized evidence weights). No single variant needs to be right; regime-varying
variant quality is handled automatically because evidence is tracked per stratum.

- (F) The blend is just another `weight_version` in the A/B framework - if the blend can't beat
  its own best constituent OOS, averaging loses and champion selection stands. (O) One
  temperature/normalization choice, pre-committed. (W) Weak-signal diversification applied to
  methodologies, not just features - very Renaissance. (C) Post-E1/E2-judgment; a small script
  over `alpha_ensemble_ic`.

### L5-4. Trailing-IC adaptive weighting (gated on P1)

Exponentially-weighted trailing IC as the weighter input (fast adaptation to decay,
regime-shift responsiveness) is the obvious online-learning move - and it is *blocked on P1
(trailing IC series)*, which does not exist. Queue it explicitly behind P1 rather than letting
it float as an idea; the one design constraint worth pre-committing: the decay half-life must be
an APR key calibrated against measured feature decay curves (Phase 143's monitors), not chosen
by eye. Also note `measurement-ic-engine.md` OQ8: trailing/vintage/shrunk are three competing
recency mechanisms - a composition decision is required before more than one feeds the weighter.

---

## 9. L6 Emission

`alpha_publisher` today: per-tf score threshold, CI-vs-cost-hurdle directional gate,
effective-n gate, binary direction out (`alpha_publisher.py:84-105,142`).

### L6-1. Continuous conviction column

Emit `conviction ∈ [0,1]` alongside the binary decision. v1 definition (no new models): the CI
margin over the cost hurdle, e.g. `(alpha_ci_lower - cost_hurdle) / (alpha_ci_upper - alpha_ci_lower)`
clamped, for longs (mirrored for shorts) - pure geometry over columns already emitted. v2
replaces it with 0c-calibrated P(sign correct) when calibration ships. The consumer that makes
this falsifiable already has a home: 142B frames can score conviction-weighted vs flat-weighted
counterfactual P&L, and v4.0's Kelly sizing needs a validated conviction input or it will be
invented under deadline pressure later.

- (F) Conviction-weighted counterfactual Sharpe must beat flat-weighted on OOS frames, else the
  column is decoration and says so. (O) v1 has zero fitted parameters. (C) One column in
  `alpha_events` + ~20 lines in the publisher.

### L6-2. Emission hysteresis

A score oscillating around the threshold emits a flip-flopping event stream; every flip is
turnover downstream. Standard fix: entry threshold + lower exit threshold (two APR keys per tf,
e.g. `alpha.quant.threshold_exit.{tf}`), so an emission persists until the score decays
materially. Falsified the same way as L6-1: turnover-adjusted counterfactual P&L with vs without
hysteresis, once frames exist. Cheap, and it converts an implicit assumption (events are
independent) into an explicit persistence model.

### L6-3. Meta-labeling gate (post-142B, queued not built)

A secondary model that takes the primary emission's context (regime, conviction, dispersion,
recent frame outcomes) and predicts P(this event's frame pays), used to size or veto. This is
the classic Lopez de Prado meta-labeling structure and it is a genuinely new model class in the
stack - which is exactly why it must wait for its training data (`alpha_frames` outcomes, which
0/2-plan 142B produces) and enter as a governed predictor with its own OOS gate and shadow
period. Named now so the frames schema keeps what it needs (it does: frame outcome + event
context join is sufficient).

---

## 10. L7 Simulation / Validation

142B's frame design and SHADOW-REVIEW pre-commitment are untouched (kept-by-design per topdown
§4). Additional lenses, all reads over machinery 142B produces:

### L7-1. Standing permutation nulls in every shadow review

Generalize `trade-construction-layer.md`'s shuffled-ranking null to the frame population:
every SHADOW-REVIEW scoring run also scores (a) a sign-permuted frame population and (b) a
random-entry population matched on (symbol, tf, regime) frequencies. Report the real
population's percentile against both nulls. A pre-committed Sharpe threshold can be passed by a
lucky draw; a percentile-vs-null cannot be argued with as cheaply.

- (F/O/C) Reuses frame machinery wholesale; ~2x-3x compute on an offline batch; zero new
  judgment surface because the nulls are mechanical.

### L7-2. Regime-conditional drawdown and contribution attribution

Counterfactual equity curve segmented by regime-at-entry (both dimensions): max drawdown, P&L
share, and frame count per stratum. The Renaissance question it answers: is the aggregate P&L
one regime's bet wearing a diversified costume? A single populated cell dominating - exactly
what EIC-05 found at the IC layer (`5m`/`high_bear` concentration) - would otherwise reappear at
the P&L layer unnoticed. Pure SQL over `alpha_frames` x `market_regimes`.

### L7-3. Crowding proxy: alpha overlap with public-factor signals

Regress `alpha_score` (per stratum, per epoch) on 2-3 canonical public signals computed from the
same bars: 12-1 momentum, 5-day reversal, low-vol tilt. High R² does not invalidate the edge,
but it prices its decay risk: alpha explainable by the most public factors in existence is alpha
the crowd already trades, and its half-life should be assumed short. Report R² per epoch as a
standing manifest metric; a rising trend is a crowding alarm no IC decay monitor would catch
until later.

- (F) The regression is the measurement; the falsifiable claim is "our alpha is not just public
  factors," and the number says so or doesn't. (O) None (diagnostic). (C) One script; factor
  signals are trivial derivations of existing columns.

### L7-4. Cost-sensitivity sweep instead of point costs

When the cost kernel lands (canonical simulator's build item), report frame P&L as a *curve*
over cost multipliers (0.5x, 1x, 2x, 4x calibrated cost) rather than a single net number. The
system's own history shows why: todo 030 moved the cost picture materially once, and a strategy
whose profitability dies at 2x assumed cost is a different asset from one that survives 4x.
One loop around existing arithmetic; pre-commit the multiplier grid in SHADOW-REVIEW.

---

## 11. Governance (cross-cutting)

The three-registry taxonomy and the six self-improvement invariants stand. Three additions to
make the system self-correcting rather than merely well-governed:

### G-1. Canary predictors (negative controls as standing infrastructure)

Register 5-10 permanent control features, run through the full pipeline every corpus run:

- **Pure noise:** seeded RNG columns (seed in APR per the HMM_RANDOM_STATE precedent).
- **Acausal placebos:** an existing feature shifted *forward* (deliberate look-ahead, e.g.
  `ret_lag_1` from T+2). These must show spectacular IC; their measured IC is a live calibration
  of what look-ahead contamination looks like in this exact pipeline, and any *causal* feature
  approaching placebo-level IC deserves immediate suspicion.
- **Dead features:** a constant and a near-constant column, verifying degenerate-input handling.

Gate: any noise canary passing `ic_ci_lower > 0 AND passes_fdr` in any stratum fails the corpus
run loudly (manifest error, not a warning). This system has already had one real look-ahead
incident and one near-miss; canaries convert that class of bug from "found by audit months
later" to "found by the next corpus run."

- (F) Self-verdicting by construction. (O) Reduces overfitting risk; adds none. (C) A handful of
  feature-registry rows flagged `is_control=true` (excluded from ensemble eligibility by the
  existing status filter) + one orchestrator assertion. Cheapest integrity purchase available.

### G-2. Pre-committed ablation protocol for ensemble degradation

When ensemble OOS IC degrades between epochs, the current response is ad-hoc forensics
(EIC-05-style diagnosis). Pre-commit the mechanical first pass: leave-one-family-out re-scoring
(zero one `group_name`'s weights, recompute alpha on the OOS window, re-measure) across all ~10
families, producing a marginal-attribution table per stratum. Answers "what died" in one batch
run before any human hypothesis enters the room - the SHADOW-REVIEW discipline applied to
postmortems. Also the cheap precursor of 0a (marginal contribution): same computation shape,
coarser grain, so building it first derisks 0a's eventual implementation.

- (C) A script over existing `ensemble_weights`/`feature_vectors`/`forward_returns`; no new
  tables (results go in the run manifest).

### G-3. Adversarial review as cadence, not event

The cross-AI review muscle already exists (AGY/Codex headless, Fable passes, 142.5-REVIEWS).
Make one variant a standing cadence with an inverted mandate: per corpus epoch, a red-team pass
whose deliverable is, for each top-weighted predictor, (a) the strongest available argument that
its IC is artifact (leakage, session mask, synthetic bars, selection pressure, crowding) and
(b) a concrete cheap test that would kill it. File the tests as todos; run the cheap ones.
Promotion machinery is symmetric on evidence, but *proposal* flow today is all-positive - people
and models propose predictors, nobody's job is proposing their deaths. This closes that
asymmetry at near-zero mechanism cost (it is a prompt template and a calendar rule, not
infrastructure).

---

## 12. Cheapest-to-Falsify-First Ordering

Ordered by (marginal infrastructure) x (time to verdict), with the mechanical path named. Items
already owned by scheduled phases (P1/P5/P6/0a/0c, cross-sectional rank IC mode, cost kernel)
are excluded - they are prior art, not this doc's proposals.

| # | Idea | Infra needed | Verdict path |
|---|---|---|---|
| 1 | **G-1 canary predictors** | None new | Feature-registry rows + orchestrator assert; verdict every corpus run, forever |
| 2 | **L4-3 winner's-curse shrink before E1/E2 judgment** | None (`shrink_ic` exists) | Apply before the pending `ops_ensemble_weight_compare.py` run - time-sensitive, the judgment is the next act |
| 3 | **L1a-1 family-balanced embedding** | One line in ANALOG-02 spec | Decide before Phase 148 locks `embedding_version=1`; validated inside ANALOG-01's already-planned calibration study |
| 4 | **L3-1 vol-normalized target** | Measurement-time transform in `ic_engine` | One comparative corpus measurement on POOLED strata |
| 5 | **L6-1 conviction column (v1 geometry)** | 1 column + ~20 lines in `alpha_publisher` | Emitted immediately; falsified by 142B frames when they exist |
| 6 | **L7-3 crowding-proxy regression** | One script | Runs against current `alpha_events`/`ensemble_alpha` today |
| 7 | **L4-2 permutation-null calibration** | One script + kernel fns | CPU-bound one-off; also settles the dead `alpha.ic.bootstrap_*` keys with evidence |
| 8 | **L1-2 microstructure proxies** | `FeatureFactory` columns + APR keys | Next corpus rerun; CS-vs-todo-030 agreement check is a bonus validation |
| 9 | **L1-1 cross-sectional family** (+ L1-3 riding it) | One new cross-sectional batch step in the corpus DAG | Standard IC screening + the cross-sectional rank IC mode; highest expected value on this list, medium build |
| 10 | **L2-1 correlation regime** (+ L2-2) | One provider under the Phase 144 dispatcher | Substitution test, batched into the v3.15 rerun window |
| 11 | **L5-1 posterior-blended variant** (+ L5-2 HRP-lite) | Variant flag in trainer/publisher, pure functions in `weights.py` | Existing A/B judge; one corpus run per variant |
| 12 | **L3-2 residual-return target** | Measurement-time join | Gated on Phase 145 betas; batch into the same v3.15 rerun |
| 13 | **L4-1 e-values** | Kernel fn + per-cell column + manifest plumbing | Pilot one tf; compounds in value with every future rerun |
| 14 | **L0-2 sub-bar path features** (+ deferred `ret_div_*`, todo 066) | Cross-TF reads in backfill | Next corpus rerun after implementation |
| 15 | **L0-1 dollar-bar pilot** | One-off aggregation script | 5-symbol pilot through `ic_engine`; fuller build only on a positive verdict |
| 16 | **L7-1/L7-2/L7-4, L6-2, L3-3, L6-3, L5-3/L5-4, L1a-2/L1a-3, G-2** | Post-142B / post-P1 / post-cost-kernel respectively | Queued behind their named prerequisites; none should be built speculatively |

Two sequencing notes that matter more than the ordering itself:

- **The v3.15 batched rerun is the natural landing window** for everything measurement-shaped
  here (L3-1, L3-2, L2-1/2, L1-2, and the first L1-1 corpus). The topdown doc's D5 logic
  (batch conditioning changes into one ic_engine re-run) applies verbatim: each of these
  changes IC numbers corpus-wide, and running them piecemeal burns rerun cycles and clutters
  the methodology-change ledger.
- **Nothing above touches the current critical path** (E1/E2 judgment -> EIC-04 re-run -> 142B),
  except #2, which exists to make that path's first act statistically honest.
