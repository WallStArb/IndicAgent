# Edge Source Thesis -- Where Does Our Edge Come From?

**Version:** 1.8
**Status:** draft -- standing document; every claim here is falsifiable and must be revisited
as evidence lands
**Priority:** high -- **T3 PASSED 2026-07-26, PRODUCTIONIZED AND GATED 2026-07-27** (Phase 167,
both live Validation Gates PASSED against the real OOS population -- first thesis on this list
to clear its own bar AND reach production, though which tf it should trade at is itself now an
open question, see T3's own note below); **T5 confirmed real and SUBSTANTIAL at 1h and 15m (the
actionable tf), small specifically at 1d** -- full replication across all three tfs now complete
(2026-08-03); five new Signal-Extraction candidates added (T6-T10, none tested yet); T4 remains
the only untested thesis.
**Milestone:** standing -- not tied to a phase
**Last Updated:** 2026-08-03
**Tags:** edge, thesis, counterparty, renaissance, falsifiable, first-principles

**Reorganized 2026-08-03** -- this doc always implicitly mixed two different kinds of claim
(see "What is deliberately NOT on this list" below, which already named "type #1" vs "type #2"
theses without ever visually separating them). Split into two groups: **Trade Constructions**
(T1, T3, T4 -- each proposes a specific trade with a named counterparty) and **Signal-Extraction
Questions** (T2, T5, and new candidates T6-T10 -- each asks whether processing the *same* feature
corpus differently reveals predictive power the current linear/pooled approach misses). A
positive Signal-Extraction result isn't a strategy on its own -- it feeds into a Trade
Construction (e.g., ranking by a non-linear combined score instead of a raw feature). T-numbers
are unchanged from prior versions; only the grouping and headings moved. New candidates T6-T10
(cointegrated pairs, statistical factor residual, lead-lag structure, continuously-adaptive
combiner weights, jump/diffusion decomposition) proposed and written up in full the same
session, not yet tested. T6/T9/T10 name explicit stochastic-process constructs (Ornstein-
Uhlenbeck half-life, Kalman state-space, jump-diffusion decomposition) -- the closest this doc
gets to continuous-time stochastic calculus; none of it applies further than this (no SDEs, no
options-style path-dependent payoffs anywhere in scope).

**Reviewed 2026-07-25** -- re-read in full against todo 179's 2026-07-24 finding (an exhaustive
234-cell regime × symbol_hmm × lookahead-scale sweep for any absolute-direction, regime-
conditional edge in the current champion population). This doc's own T2 falsification
criterion, written 2026-07-01 before that sweep existed, predicted exactly the test that
killed it -- see T2 below. Still the correct standing doc; nothing here is stale, it's now
partially *resolved*. Added candidate thesis T5 (non-linear interaction structure) below,
prompted by the same finding: the one interaction axis the system already models explicitly
(regime × feature) just failed exhaustively, which raises the question of whether the *linear*
combiner is blind to interaction structure the 150 features already contain, independent of
whether more features (Phase 164/165) get added.

**Updated 2026-07-26** -- ran both cheap falsification scripts item 5 (below) recommended
before committing to Phase 164/165. T3 passed decisively; T5 came back with a suspiciously
large uplift that needs one more check before it's trustworthy. See T3/T5 sections below for
full results. T3's falsification script was archived once Phase 167 productionized it into
`services/cross_sectional_spread_tracker.py`; T5's script is `scripts/analysis/t5_nonlinear_combiner_lightgbm_check.py`.
**Also caught and flagged a methodology gap in T2** (below), since resolved: its original
falsification ran under cross-sectional regime labels that were themselves found miscalibrated
(todo 092). Re-run 2026-07-27 against the genuinely corrected, live production labels
(`market_regimes.regime_label`, post-recompute) -- confirmed dead, not provisional. See T2
section below.

---

## The Question Nobody Has Answered

The entire v3.0 stack -- Feature Factory, IC engine, ensemble, frames -- assumes edge exists
in this feature × universe × horizon combination and pours rigor into *measuring* it. No
document states what the edge *is*: a falsifiable claim about **who is on the other side of
the trade and why they are systematically wrong**.

Every durable trading edge is one of a small number of things:
1. **Information** someone else doesn't have (unique data, faster data, better-cleaned data)
2. **Processing** someone else can't do (better models on the same data)
3. **A counterparty constraint** -- someone must trade for non-price reasons (index rebalance,
   fund flows, hedging mandates, tax, margin calls) and pays for immediacy
4. **A behavioral bias** stable enough to persist after being published
5. **A risk premium** -- compensation for bearing a risk others won't (this is beta wearing a
   costume, and it's fine, but it should be named as such, not called alpha)

Renaissance's actual moat was overwhelmingly #1 and #2 at a time when almost nobody else did
either -- data nobody else had cleaned, on instruments nobody else priced carefully. It was
never "better statistical validation of features everyone can compute."

## The Uncomfortable Facts About Our Setup

Stated plainly so they can be argued with, not glossed:

- **The features are public.** All 54 are OHLCV-derived quantities (momentum z-scores, VWAP
  deviation, ATR, calendar position) computable by anyone with a market data subscription.
  Every systematic shop has tested them.
- **The universe is the most efficient corner of the market.** 58 of the most liquid,
  most-studied ETFs on earth. SPY's order book is the most competitive pricing environment
  in existence.
- **The horizons are heavily mined.** 5m-1d is exactly where institutional stat-arb operates.
- **The early evidence is consistent with the skeptical read.** Top qualifying features are
  calendar effects (`quarter_position`, `days_to_month_end`, `dow_sin`) and macro proxies
  (`yield_slope_z`), ICs 0.02-0.08 gross. Calendar anomalies are the most published, most
  arbitraged effects in the literature.

None of this proves there is no edge. It proves the *default hypothesis must be no edge*,
and the burden of proof sits on every positive result -- which is exactly the posture the
gate stack (FDR, shrinkage, OOS, cost hurdle) implements. This doc's job is to name what a
surviving result would actually *be*.

## Candidate Edge Theses (each falsifiable)

Two different kinds of claim live here. **Trade Constructions** propose a specific trade with a
named counterparty -- why the mispricing exists and who's systematically on the other side of
it. **Signal-Extraction Questions** don't propose a new trade at all -- they ask whether
processing the *same* feature corpus differently (a different grouping, a different combination
rule, a different temporal structure) reveals predictive power the current linear/pooled
approach misses. A positive Signal-Extraction result feeds *into* a Trade Construction (e.g.,
ranking by a non-linear combined score instead of a raw feature); it isn't a strategy on its
own. See "What is deliberately NOT on this list" below for the bar a new Signal-Extraction claim
must clear.

### Trade Constructions

#### T1 -- Small-scale immediacy provision (counterparty: constrained flow)
At this account size (retail, no capacity pressure), the system can take the other side of
flows too small for institutions to bother with: end-of-day rebalance pressure in
lower-liquidity sector ETFs, overnight-gap mean reversion where market makers widen out.
**Why we might win:** capacity constraints don't bind at this size; institutions leave
crumbs below their minimum ticket. **Falsification:** the surviving cells should
concentrate in the less-liquid half of the universe and around session boundaries; if edge
concentrates in SPY/QQQ mid-session, T1 is wrong.

#### T3 -- Cross-sectional relative mispricing (counterparty: single-name flows) -- **PASSED 2026-07-26, PRODUCTIONIZED AND GATED 2026-07-27**
Individual ETFs get pushed off fair relative value by idiosyncratic flows (sector rotation,
thematic retail); the *ranking* across 58 correlated instruments mean-reverts even when no
single instrument is predictable directionally. **Why we might win:** relative-value noise
cancellation is statistically much easier than directional prediction; this is the
lowest-IC-requirement thesis on the list. **Falsification:** cross-sectional long-short
spread portfolios built from feature rankings must show positive net return where per-symbol
directional trades on the same features don't. Requires the cross-sectional rank IC measurement
mode (`docs/research/measurement-ic-engine.md`, "Addendum: Cross-Sectional Rank IC") to even
test. If the spread portfolio is no better than directional, T3 is dead.

**Result (`scripts/analysis/t3_cross_sectional_long_short_ctf_momentum_check.py`, 2026-07-26):**
equity/15m, `ctf_momentum` (the strongest, most cross-regime-consistent-sign symbol-varying
feature per a live `feature_ic_scores` query), top/bottom decile, dollar-neutral,
day-clustered bootstrap (`services/counterfactual_tracker.py`'s `frame_gate_passes`,
verbatim -- no new statistics). **Passed decisively at both lookahead scales:**

| Scale | n_bars | mean spread | ci_lower | shuffled-null P(null ≥ observed) |
|---|---|---|---|---|
| fast (lookahead=1) | 24,924 | 0.000587 | 0.000562 | 0.0000 |
| slow (lookahead=20) | 24,924 | 0.001115 | 0.000969 | 0.0000 |

The shuffled-ranking null (permute feature-to-symbol assignment within each bar, rebuild the
identical decile construction, 40 draws) is the required guard against this being a pure
dollar-neutral-bucketing artifact -- it isn't; the real result clears every null draw. This is
the first thesis on this list to clear its own pre-registered bar convincingly. Gross spread
only (no cost model applied yet) -- before treating this as an actionable finding it still
needs: (1) the todo 030 cost-hurdle treatment applied to the spread construction specifically
(a long-short spread's cost dynamics differ from a directional trade's), and (2) scoping
`docs/research/trade-construction-layer.md` as a real phase rather than a one-off script.

**Productionized and gated (Phase 167, 2026-07-27):** the falsification script became a real
service, `services/cross_sectional_spread_tracker.py`, and both items above are now done. A
full 2006-2026 backfill populated `construction_spreads` (24,924 bars), and both live
Validation Gates ran against the real OOS population with the cost-hurdle sweep applied at
every tier: Gate 1 (shadow spread Sharpe, net of cost) PASSED, and Gate 2 (attribution
honesty -- is the P&L a disguised static factor tilt) PASSED. Full numeric detail, the binding
Gate 1 pass rule, and the Gate 2 retrospective-versus-causal caveat are recorded in
`docs/research/trade-construction-layer.md`'s Validation Gates section (not duplicated here --
one doc owns the gate numbers). **Both gates clearing means the Phase 156-159
execution/sizing chain's stated precondition is now met for this construction** -- unlike
Phase 148's per-symbol directional construction, which passed Gate 1 but failed Gate 2. **Note
this only means the construction is statistically validated, not that it is live -- no capital
has been deployed anywhere in this project; Phase 156-159 (the actual execution/sizing layer)
has not been started.**

**Open question, found 2026-08-03: `_TF="15m"` (`services/cross_sectional_spread_tracker.py:105`)
is an inherited default, not a comparative finding.** It came from whichever tf the original
falsification script happened to test first, not from testing T3's actual netted spread
construction at other tfs. The one existing 5m result (todo 030) measured *standalone
directional* IC against cost floors, not T3's dollar-neutral netted spread -- which this doc's
own item 1 (below) already notes has different cost dynamics. Todo 235 tracks running T3's real
methodology at 5m before treating 15m as the right choice rather than just the first one tried.

**Sibling CTF features tested, both rejected (`scripts/analysis/t3_ctf_family_check.py`,
2026-07-27):** `ctf_momentum` has two untested siblings from the same `_build_ctf_series()`
function (`services/backfill_feature_factory.py`) -- `ctf_vwap_align` (sign of close vs. HTF
cumulative VWAP) and `ctf_regime_align` (HTF HMM forward-pass state, 0=ranging/1=trending) --
already computed and sitting in `feature_vectors`, zero new data cost to test through the
identical T3 methodology (same bootstrap, same shuffled-null guard, same cost-hurdle sweep).
Neither survives:

| Feature | Scale | ci_lower | shuffled-null p | mean 1-way turnover/bar | Best net spread (1bp) |
|---|---|---|---|---|---|
| `ctf_vwap_align` | fast | 0.0000094 (passes) | 0.0000 (real, not artifact) | 0.719 | **-0.45 bps/bar (fails every cost tier)** |
| `ctf_vwap_align` | slow | -0.0000759 (fails) | 0.075 | 0.719 | n/a |
| `ctf_regime_align` | fast | -0.0000230 (fails) | 0.975 | 0.872 | n/a |
| `ctf_regime_align` | slow | -0.0000651 (fails) | 0.025 | 0.872 | n/a |

`ctf_vwap_align`'s fast-scale result is a genuine, non-artifact cross-sectional signal (clears
both the bootstrap CI and the shuffled-ranking null) -- but it flips leg membership on ~72% of
symbols per bar, so its gross edge (0.27 bps/bar) is smaller than even the cheapest 1bp
round-trip cost floor. `ctf_regime_align` doesn't clear its own CI at either scale and churns
even harder (~87-90% turnover) -- a binary HMM state is not a stable enough per-bar ranking
signal for this construction. **Verdict: `ctf_momentum` is not one member of a productive
"CTF family" -- it is the only one of the three that survives real trading frictions.** Answers
the "should we run multiple CTF-style features" question empirically rather than by building
more of them speculatively: no, not from this specific family. A different cross-timeframe
primitive (not derived from `_build_ctf_series()`) would need its own from-scratch case, not an
assumed extension of this result.

#### T4 -- Horizon arbitrage at 1h/1d (counterparty: nobody -- risk premium)
The honest fallback: at longer horizons with low turnover, small conditional tilts
(vol-conditioned momentum, flight-to-quality) earn modest risk-adjusted returns that are
partly repackaged risk premia. **Why we might win:** we don't need to win against anyone;
we need to harvest systematically without behavioral errors. **Falsification:** returns
should survive but shrink substantially when regressed against standard factor exposures.
This thesis caps expectations at "good systematic beta," which is a legitimate but
different product.

### Signal-Extraction Questions

#### T2 -- Regime-conditional persistence (counterparty: unconditional models) -- **FALSIFIED, CONFIRMED 2026-07-27 on live corrected labels -- no longer provisional**
Features with zero pooled IC but real conditional IC (the whole stratification premise).
Participants running unconditional models mis-price bars in minority regimes.
**Why we might win:** most simple systematic flows are not regime-conditioned; conditioning
is our one genuine structural bet. **Falsification:** regime-stratified IC must materially
exceed pooled IC for the same features OOS (not just in-sample, where stratification
mechanically inflates cell significance), and the regime labels themselves must pass the
026 validation. If conditional ≈ pooled OOS, T2 is dead and most of the stratification
machinery is measurement theater.

**Result (todo 179, 2026-07-24):** this exact test was run, at full rigor. All 9
cross-sectional regimes × 6 symbol_hmm states × 3 lookahead scales (234 cells, 126 with
sufficient day-cluster coverage), day-clustered bootstrap + BH-FDR. Exactly 2 cells passed
initially (`low_bull`×`trending_down`, 5m, both lookahead scales, `ci_lower` positive). Neither
survived out-of-window replication against 12 independent historical episodes back to 2008 -- critically, the finding didn't even hold in its *own* discovery window once the ensemble's own
`alpha_score > 0` conditioning was removed (`ci_lower` negative at every scale on raw regime
labels alone). **Zero cells, at any granularity tested, show real non-circular positive
expectancy.** T2 is dead by this doc's own pre-registered criterion -- regime conditioning,
as currently implemented (a single categorical stratification dimension feeding a linear
IC-weighted combiner), is not where this system's edge lives. Full trail:
`.planning/todos/completed/179-gate166-concurrent-exposure-diagnostic.md`.

**Original test (2026-07-24) ran against old, pre-todo-092 labels; re-verified live 2026-07-27,
caveat now closed.** The original 234-cell sweep used the raw-value cross-sectional cuts
(`breadth_frac` 0.40/0.60, `curve_z`/`credit_z` ±0.5/0.0) later found miscalibrated and fixed
the same day (migrations 257/258). Todo 183's full corpus recompute completed 2026-07-27T21:55
UTC (`ic_engine.run_complete`, both equity/rates groups, zero errors); the same day, todo 179's
sweep was re-run directly against the genuinely corrected, live production
`market_regimes.regime_label` (270 cells, 108 with sufficient day-cluster coverage, **zero
pass**). The `high_bear` lead surfaced by the earlier offline re-derivation (conflating
buyable-dip vs. structural-bear) does not survive on live data either -- all 36 `high_bear`
cells sit at 12-13 day-clusters, below the `alpha.validation.regime_gate_min_clusters` coverage
floor, genuinely untestable in the current OOS window, not a new negative finding. **T2's death
is now confirmed on live, non-stale data -- no longer provisional.** Full detail:
`.planning/todos/completed/179-gate166-concurrent-exposure-diagnostic.md`'s live-label
re-verification section. Separately, this test also only covers the feature set live as of
2026-07-24 (through Phase 163, with the 17 new structural columns still incomplete on
historical rows per todo 176) -- it says nothing about features Phase 164/165 hasn't built yet.

**What T2's death does NOT prove:** that regime information is worthless, or that no
interaction effect involving regime exists -- only that a *linear*, single-dimension,
categorical treatment of it doesn't clear a bar. See T5 below.

#### T5 -- Non-linear interaction structure (counterparty: linear-model participants) -- confirmed SMALL, not LARGE
The ensemble combiner (`ensemble_trainer.py`) is a linear, shrunk-IC-weighted sum of
per-feature marginal predictive power. It can express "feature X predicts returns" but
structurally cannot express "feature X predicts returns only when feature Y crosses a
threshold" -- any conditional/interaction structure across the 150 features is invisible to
it by construction, the same way T2's single categorical regime axis was one narrow,
already-tested instance of exactly this blind spot. **Why we might win:** this is a specific,
named processing advantage (per the "deliberately NOT on this list" rule below) -- not "our ML
is better" in general, but "the current combiner is linear and 150 features have 11,175
pairwise-interaction slots it never evaluates." **Falsification:** a non-linear combiner
(gradient-boosted trees or a shallow net) over the identical `feature_vectors`/
`forward_returns` corpus, evaluated with the same walk-forward OOS discipline, day-clustered
bootstrap CI, and BH-FDR correction as everything else in this doc, must show a statistically
significant Sharpe/IC uplift over the existing linear ensemble on the *same* features. If it
doesn't, T5 is dead -- the bottleneck isn't the combiner's linearity, which strengthens the
case for either T3 (construction, not modeling) or that this feature set genuinely has no
edge to extract regardless of how it's combined. Original design proposal and overfitting
controls (archived 2026-08-03, fully absorbed below -- not the live reference):
`docs/research/archive/measurement-nonlinear-interaction-combiner.md`.

**Result (`scripts/analysis/t5_nonlinear_combiner_lightgbm_check.py`, 2026-07-26): canary-leakage
check clears this specific failure mode -- genuinely interesting, still not a confirmed pass.**
Equity/1h, shallow regularized LightGBM (200 trees, depth 4, walk-forward folds via
`ic_math.py`'s `build_walk_forward_folds`, 24-bar embargo), compared against `ctf_momentum`
alone on identical OOS rows. During development this run already caught one real leak: naive
pooled training showed mean_ic≈0.30 with 80/80 symbols passing, traced to the tree implicitly
learning each ETF's own persistent long-run drift (a fixed-membership factor-exposure leak, not
bar-level signal) -- fixed by subtracting each symbol's own causal (shift(1), expanding) mean
return before training/measuring. **After that fix, the tree still comes back at mean OOS
point_ic=0.30 (80/80 symbols pass CI) vs. `ctf_momentum`'s 0.09 (79/80 pass)** -- a ~3.4x
uplift, and a within-bar_ts cross-sectional-neutral decomposition confirms it isn't purely a
common-market-factor artifact (tree: point_ic=0.258, `ci_lower`=0.254; feature: point_ic=0.080,
`ci_lower`=0.076).

**Canary-leakage check (todo 184, `scripts/analysis/t5_canary_leakage_check.py`, 2026-07-26):**
reran the identical walk-forward pipeline with the corpus's 5 built-in leakage canaries included
as features. Negative controls (`canary_constant`, `canary_near_constant`,
`canary_noise_gaussian`, `canary_noise_uniform`) all come back clean by the calibrated,
unambiguous statistic -- standalone per-symbol IC, not gain importance, which turned out to be
poorly discriminating in this shallow/152-feature regime (median real feature's own gain
importance is only 2.0, barely above what a noise column gets by chance -- two rounds of
tuning an importance-based threshold produced misleading verdicts before this was caught and
the check was rebuilt around IC instead). All 4 negative controls: 0/10 symbols clear
`ci_lower>0`, mean IC negative or (`canary_constant`) correctly undefined (zero variance).
`canary_acausal_placebo` (the deliberate look-ahead-leak positive control -- pairs bar i with
bars i+1→i+2's return) shows a small standalone IC (0.016, 5/10 symbols pass) and moderate
gain-importance rank (13.4/152) -- expected, correct behavior for a working positive control
(it genuinely contains future-return information via market autocorrelation), not evidence of
a pipeline bug. **The decisive check: aggregate tree IC is unchanged whether or not this
maximally-leaky feature is available (0.2992 → 0.2999, Δ=+0.0007).** If look-ahead-style
leakage were a meaningful driver of the 0.30 result, adding a stronger version of that exact
leak class should have moved the needle; it didn't.

**Verdict: this specific, well-targeted leak-detection test does NOT explain the 0.30 result as
a look-ahead-leakage artifact.** This does not, by itself, prove T5 is real -- the result is
still ~3x anything else measured in this corpus and warrants continued skepticism (independent
replication across other tfs/periods, per this project's resist-overfitting discipline) before
any production consideration. But the specific failure mode todo 184 was filed to rule out is
ruled out with real evidence, not absence of a red flag. T5 moves from "preliminary, blocked on
this check" to "genuinely interesting lead, not yet a confirmed pass" -- the next legitimate
step is independent replication (a different tf, a different OOS window), not further leakage
investigation on this same result.

**Independent replication at equity/1d (`scripts/analysis/t5_nonlinear_combiner_replication_1d.py`,
2026-07-27): PARTIALLY replicates, at a much smaller magnitude -- NOT the same finding.** Same
pipeline (identical causal per-symbol demeaning fix, walk-forward folds, block-bootstrap CI),
recalibrated embargo (5 bars vs 1h's 24) and per-symbol row floor (100 vs 300) for 1d's cadence,
plus a genuine methodological addition the original script and its leak-check never had: BH-FDR
correction across the ~80 per-symbol tests (`ic_math.py`'s `apply_bh_fdr`, sign-gated -- the
research doc's own T5 falsification bar requires "the same... BH-FDR correction as everything
else in this doc," which neither prior T5 script applied).

Result, raw per-symbol: tree mean `point_ic`=0.0183 (11/80 pass `ci_lower>0`, 5/80 survive
BH-FDR with correct sign); `ctf_momentum` mean `point_ic`=**-0.0244** (1/80 pass, negative on
average at this tf). Cross-sectional-neutral rigor pass (the component most relevant to a
T3-style dollar-neutral construction): tree `point_ic`=0.0164, `ci_lower`=0.0081, **clears
zero**; `ctf_momentum` `point_ic`=-0.0084, `ci_lower`=-0.0174, **does not clear zero (trends
negative)**. Full per-symbol table: `docs/analysis/t5-replication-1d-per-symbol.csv`.

**Two findings, not one:**
1. **The tree DOES show a real, FDR-surviving cross-sectional-neutral uplift at 1d** -- this is
   a genuine replication in direction, in a tf far enough from 1h to rule out "succeeded for
   boring reasons like shared regime artifacts." T5 is not dead.
2. **The magnitude collapsed ~16x** (1d cross-sectional-neutral `point_ic`=0.0164 vs 1h's
   0.258) -- nowhere near "3x anything else in the corpus" anymore; comparable to or only
   modestly better than typical single-feature ICs measured elsewhere. The huge 1h number does
   NOT look like a stable, tf-independent phenomenon; it looks tf-dependent, in a way the leak
   check (which ruled out look-ahead leakage specifically, not all forms of overfitting) doesn't
   explain.

**Separately, resolved 2026-07-27 (todo 189): `ctf_momentum`'s negative mean IC at 1d is a
measurement artifact, not a timeframe-instability of one coherent feature.**
`services/backfill_feature_factory.py`'s `_CTF_HIGHER_TF` mapping sets each tf's higher
timeframe for the CTF group as `5m/15m -> 1h`, `1h -> 1d`, but `1d -> 1d` (self-referential --
the corpus has no timeframe above 1d, confirmed via `SELECT DISTINCT timeframe FROM
market_data_ohlcv`). `ctf_momentum` is a Wilder RSI computed over the HTF bars; at every other
tf this is a genuine cross-timeframe momentum-context feature, but at 1d it silently degenerates
into a plain same-timeframe RSI oscillator -- a structurally different statistic sharing the
same column name. Same-tf RSI is a classic short-term mean-reversion signal (high RSI predicts
a pullback), which plausibly explains the negative 1d IC directly with no market-regime story
needed. **This means the 1d result says nothing about the 15m feature Phase 167 actually
trades** (5m/15m/1h all use a genuine, different-tf HTF and are unaffected) -- it was comparing
two different features under one name. Do not treat `ctf_momentum` as timeframe-portable at 1d
specifically; every other tf is fine. Full detail and recommended fix: todo 189.

**Revised verdict: T5 is neither confirmed nor dead -- it is confirmed SMALL, not confirmed
LARGE.** The original 1h finding likely overstated the effect's true, tf-general size.

**UPDATE 2026-08-02: both the 1h and 1d numbers above independently re-verified under a
corrected corpus -- both hold, both come down moderately, T5's verdict is unchanged.** Two real
changes accumulated since the numbers above were first measured, neither reflected in either
prior run: (1) `forward_returns` was truncated and rebuilt under todo 208's corrected
same-session-boundary definition (~2026-07-30), changing the target variable itself; (2)
`feature_vectors` grew from ~150 to 263 columns (migrations 266/267, Phase 164/165 SMC +
swing/fib/trend primitives, 2026-07-27/28) -- the 1d replication above ran before the historical
backfill for those columns completed. Re-ran both original scripts with identical logic (only a
memory-safety fix to the data-loading/training layer, todo 231 -- confirmed byte-identical
results across repeated runs of the fixed code, so this is a data re-verification, not a
methodology change):

- **1h:** tree mean `point_ic`=0.2139 (80/80 pass, was 0.2992) vs `ctf_momentum`'s 0.0533 (79/80
  pass, was 0.0887). Cross-sectional-neutral: tree 0.1822 (`ci_lower`=0.1791, was 0.258/0.254)
  vs baseline 0.0511 (`ci_lower`=0.0476, was 0.080/0.076) -- both drop ~30-40%, both still clear
  CI decisively.
- **1d:** cross-sectional-neutral tree `point_ic`=0.0127 (`ci_lower`=0.0048, was 0.0164/0.0081)
  vs `ctf_momentum` -0.0105 (`ci_lower`=-0.0198, still negative -- the known same-tf-RSI
  artifact, todo 189, unaffected by today's changes) -- a ~22% dip, smaller than 1h's drop,
  still clears zero. Per-symbol BH-FDR-positive count remains thin either way (1/80).

**Read: both prior numbers were partly inflated by the pre-correction data, but the qualitative
verdict does not change** -- confirmed real, confirmed SMALL at both tfs measured.

**UPDATE 2026-08-03: 15m completed successfully -- and the result is NOT small, it's close to
1h's magnitude.** 15m OOM-killed four times in a row across two sessions, each time after the
prior fix closed one memory sink and exposed the next (data-fetch materialization, todo 231;
per-fold model retention; two transient-copy steps in the causal-demeaning sort). Root-caused
properly (not patched further) via `superpowers:systematic-debugging`: the wide ~8.5M-row x
264-col pandas DataFrame's *existence* was the defect, not any one operation on it -- measured,
not estimated, the fetch alone consumed 18.5GB before any processing started, and every
subsequent full-frame pandas op stacked another ~9.3GB on top; no patch ordering fit in 29GB.
Fix: `_t5_nonlinear_combiner_shared.py` rewritten to build the training matrix directly from
asyncpg rows (two-pass: narrow key/target columns first, then wide feature columns scattered
into a preallocated array), matching `services/ensemble_trainer.py:909-928`'s existing
production pattern instead of declining it. Verified architecture-only: the 1d re-run under the
new code is bit-identical to its pre-change output. 15m itself: peak 14.65GB (was killed at
~21.8GB), zero OOMs, `pytest tests/unit/` green.

**15m result: tree mean `point_ic`=0.2899 (80/80 pass CI, 80/80 survive BH-FDR positive) vs
`ctf_momentum`'s 0.0677 (uplift mean 0.2222, 80/80 symbols tree-better). Cross-sectional-neutral:
tree 0.2506 (`ci_lower`=0.2489) vs baseline 0.0610 (`ci_lower`=0.0593), both clear CI
decisively.** This is much closer to 1h's magnitude (0.1822 cross-sectional-neutral) than to
1d's (0.0127) -- and 15m is the tf that actually matters, since it's what Phase 167's live
construction trades. Read: T5's magnitude is not uniformly small across timeframes -- it's
small specifically at 1d (and 1d's own `ctf_momentum` baseline is separately known-degenerate,
todo 189), and substantial at both 1h and, now confirmed, 15m. The one prior open
question -- "does the huge 1h number generalize, or was it an artifact of that specific tf" --
is answered: it generalizes to the tf that's actually tradeable. (Note: the script's own printed
VERDICT string reads "Mixed/weak" here due to a pre-existing, unrelated threshold-logic bug in
the verdict heuristic -- `tree_pass_rate > baseline_pass_rate * 1.5` can't fire when both rates
already saturate near 1.0 -- the numbers above are the substantive result, not that string.)

Full per-symbol tables: `docs/analysis/t5-1h-per-symbol.csv`,
`docs/analysis/t5-replication-1d-per-symbol.csv`,
`docs/analysis/t5-replication-15m-per-symbol.csv` (all current as of 2026-08-03).

#### T6-T10 -- Five new Signal-Extraction candidates, added 2026-08-03, none tested yet

T2 tested one grouping (discrete price-trend regime) and one combination rule (linear). T5
tested one combination rule (non-linear tree) on the same grouping (none -- pooled). That leaves
real gaps: different **groupings** (pairwise structural relationships, orthogonalized factors),
different **temporal structure** (lead-lag, not contemporaneous), and different **combination
dynamics** (continuous adaptation, not a discrete regime switch or a static fit). Ideas that
would just re-run T2's regime-conditioning against a different regime definition (liquidity
regime, volume regime) were considered and dropped -- too close to an already-falsified instance
to justify a new T-number without first checking whether the falsification generalizes.

This universe's binding constraint (see "Breadth Is the Binding Constraint" below) matters here:
effective breadth ~8-15 across 80 correlated ETFs. That rules out some classic stat-arb
approaches at face value (true cointegration wants economically related PAIRS, not a broad
basket) but doesn't rule out others (factor decomposition works fine on a small, correlated
universe -- that's exactly the regime PCA is built for).

**T6 -- Cointegrated pairs residual (counterparty: basket/index flows that ignore pairwise structure).**
A genuinely different grouping than T2 (regime) or T3 (broad cross-sectional rank): specific,
economically-linked pairs (sector leveraged/inverse pairs, a miner ETF vs. the metal it tracks,
`TLT`/`IEF`) tested for a stable cointegrating relationship whose short-run deviations
mean-revert -- the classical Engle-Granger/Johansen stat-arb structure. **Falsification:** (1)
screen candidate pairs by economic relatedness, not a blind correlation scan across all 80
symbols (a blind scan risks the exact multiple-comparisons trap this project's own FDR
discipline exists to catch). (2) Engle-Granger test for cointegration on log-price pairs, with an
OOS stability check -- a pair cointegrated in-sample but not OOS is noise, not structure. (3) For
pairs that pass, day-clustered bootstrap CI on whether the residual z-score predicts forward
reversion, same statistical bar as every other thesis here. If zero pairs both cointegrate OOS
and show predictive residual reversion, T6 is dead. **Cost:** cheap -- existing daily closes are
sufficient for the cointegration screen; only pairs that pass need the full IC/bootstrap
treatment. **Stochastic-calculus detail (added 2026-08-03):** for pairs that cointegrate, model
the spread as an Ornstein-Uhlenbeck process (`dX_t = θ(μ - X_t)dt + σdW_t`) rather than trading
off an arbitrary lookback window -- the fitted `θ` gives a closed-form mean-reversion half-life
(`ln(2)/θ`), the standard stat-arb sizing/holding-period signal for a cointegrated spread, more
principled than a fixed z-score lookback chosen by hand.

**T7 -- Statistical factor residual (counterparty: index/factor-only investors).** Decompose the
cross-sectional return matrix into its top-K statistical factors (PCA over the correlated
80-ETF universe) and test whether the idiosyncratic residual -- what's left after removing the
common factors -- is more predictable than the raw or simply-demeaned return. The classical
Avellaneda-Lee stat-arb structure: instead of ranking by a feature (T3) or conditioning on a
discrete regime (T2), this asks whether orthogonalizing away the shared market/sector factors
first reveals structure invisible in the raw cross-section. **Falsification:** fit PCA (or a
simpler factor model) causally -- no look-ahead in the factor loadings, same discipline as T5's
per-symbol demeaning fix -- and test whether `ctf_momentum` (or the T5 tree score) computed on
the residual return series shows a materially higher IC than on raw returns. If residualizing
doesn't change the IC picture, T7 is dead. **Risk to flag up front:** with effective breadth
~8-15, a PCA over 80 highly-correlated ETFs may only have 3-5 meaningful factors before hitting
noise -- the K-selection question needs a real answer (parallel to HMM's K=5 BIC study, not a
guess) before this result can be trusted.

**T8 -- Lead-lag / cross-asset temporal precedence (counterparty: participants who don't
cross-reference correlated instruments in real time).** Existing broadcast features (`vix_z`,
`yield_slope_z`, `flight_quality`) encode *contemporaneous* market-level context only. Nothing
tests whether one equity ETF's move at time *t* predicts a **different, specific** ETF's move at
*t+1* -- a genuine pairwise temporal lead-lag relationship (a large, liquid sector ETF leading a
smaller/less liquid one). Every other thesis on this list is contemporaneous (same-bar); T8 is
specifically about information propagating across symbols with a lag. **Falsification:**
cross-correlation or Granger-causality screen across symbol pairs at 15m, held to the same
day-clustered bootstrap + BH-FDR bar as everything else here -- critically, tested against
`ctf_momentum` as a covariate, since a lagging symbol's own `ctf_momentum` might already explain
an apparent lead-lag effect. If no pair shows lead-lag power beyond what the lagging symbol's own
existing features already capture, T8 is dead. **Cost:** most expensive of the four -- ~3,160
candidate ordered pairs across 80 symbols needs a pre-filter (economic relatedness or
liquidity-tier proximity) before FDR correction even applies, to avoid a multiple-comparisons
trap.

**T9 -- Continuously-adaptive combiner weights (counterparty: participants on stale,
periodically-refit weights).** `ensemble_trainer.py`'s shrunk-IC weights are re-estimated in
discrete batch runs, not continuously. T2 tested discrete regime-conditional weight switching
and it failed; T9 asks whether letting weights drift smoothly and continuously (an
exponentially-weighted rolling IC, or a Kalman filter -- the discrete-time analog of a
continuous-time linear stochastic system, with weights as latent, slowly-varying state)
captures real time-variation a periodic step-function re-fit misses between recompute cycles.
Orthogonal to both T2 (continuous drift vs. discrete regime switch) and T5 (adaptive linear
weights vs. static non-linear combination) -- no new grouping or model family, just a different
update dynamic on the existing linear combiner. **Falsification:** build a walk-forward EWMA (or
Kalman-filtered) weight update over the same per-feature IC series `ensemble_trainer.py` already
computes, with a pre-specified halflife (not tuned to the result), and compare OOS IC/Sharpe
against the current periodic-batch weights over the identical held-out window. If it doesn't
clear a real uplift, T9 is dead -- feature predictive power is stable enough on the existing
recompute cadence. **Cost:** cheapest of the four -- reuses `feature_ic_scores`' existing time
series directly, no new grouping or pairwise screen.

**T10 -- Jump/diffusion decomposition (counterparty: participants who conflate gap risk with
trend risk).** All existing volatility features (`garch_volatility`, `hurst_exponent`) treat
price movement as one undifferentiated process. Realized-variance theory splits it into two
economically distinct components: a continuous diffusion part (steady drift/trend) and a jump
part (discontinuous, news-driven gaps) -- separable via bipower variation vs. total realized
variance (Barndorff-Nielsen/Shephard) or an explicit jump-diffusion fit. **Why we might win:** a
symbol whose recent volatility is jump-dominated (news risk) behaves differently going forward
than one whose volatility is diffusion-dominated (trend continuation) -- if the current single
undifferentiated vol features blend these, they may be averaging away a real distinction, the
same "combiner/grouping is blind to structure that exists" pattern as T2/T5, applied to feature
*construction* instead of combination. **Falsification:** compute a jump-ratio feature (jump
variation / total variation) per symbol per bar from existing intraday OHLCV, test whether it
adds incremental IC beyond the existing GARCH/Hurst features on the same target -- not whether
it's predictive alone (a new feature that only duplicates existing information isn't evidence of
anything). If it adds nothing beyond what GARCH/Hurst already capture, T10 is dead. **Cost:**
cheap -- pure feature-engineering exercise on data already in `market_data_ohlcv`, no new
grouping, no new data source; closer in shape to a Phase 151 primitive candidate than a new
combiner or construction, but named here since the *specific processing/decomposition
advantage* (separating jump from diffusion risk) is the falsifiable claim, not just "add a
feature."

**Sequencing, cheapest-first:** T9 (reuses existing IC time series) -> T10 (feature-engineering
only, existing OHLCV) -> T7 (PCA on existing closes) -> T6 (pairs screen, existing closes,
narrow candidate list) -> T8 (most expensive, needs the multiple-comparisons pre-filter done
carefully first). None are urgent -- independent of the in-flight T5-at-15m/T3-at-5m work, pick
up whenever that settles.

### What is deliberately NOT on this list
"Our features are better" (they are public) and "our ML is better" (we run a linear
IC-weighted combiner; the institutions we'd be beating run more) as *unqualified* claims. Any
future Signal-Extraction Question must name the specific processing advantage -- e.g.,
regime-conditional structure (T2, now falsified), the AnalogEngine's non-parametric
retrieval, T5's named linear-vs-non-linear gap, or T6-T10's named
grouping/association/dynamic/decomposition -- not assert generic model superiority.

## Breadth Is the Binding Constraint (added 2026-07-01, Simons-lens review)

Whatever thesis survives, the arithmetic above it is fixed: IR ≈ IC × √(effective breadth).
This universe has effective breadth ~8-15 (58 correlated ETFs; the completed ETF Universe Expansion's 79 barely moves it -- more sector funds are more of the same bets). At IC ≈ 0.03 and breadth 10, there is almost
nothing to harvest; at breadth 300, the *same IC* is a business. Medallion's expansion to
higher frequency and thousands of instruments was this arithmetic, not bigger edges. The
concrete long-term move this pipeline is well-positioned for: liquid single-name equities
(e.g., S&P 500 constituents) for cross-sectional work -- the pipeline is symbol-agnostic and
the trade-construction layer is exactly what monetizes wide universes.

**Sequencing decision (operator, 2026-07-01):** universe expansion waits until the end-to-end
system is proven -- pipeline through P&L, validated through the canonical simulator
(`docs/research/platform-canonical-simulator.md`). Multiplying the universe before the path is trusted
multiplies unvalidated machinery, not returns. Breadth is the biggest lever; it is deliberately
pulled last.

## What This Doc Demands From the Roadmap

1. **Todo 030's external cost floor runs first -- DONE 2026-07-01, verdict recorded.**
   5m fast/mid and 15m fast are net-negative-to-marginal against realistic spread (0.26,
   0.84, 0.55 bps gross vs 1-10bp cost floors, on unshrunk IC -- the real numbers are worse).
   1h/1d and the longer-lookahead 5m/15m cells clear comfortably. Todo 030 itself is closed and
   removed from `.planning/todos/`; this paragraph is now the only surviving record of its full
   table. **This kills or badly
   wounds T1 (immediacy provision) as a short-horizon thesis** -- if the crumbs institutions
   leave below their minimum ticket can't clear spread either, T1 only survives at longer
   holds, which changes what "small-scale immediacy" means. T2/T3/T4 are horizon-agnostic
   and unaffected in direction, though T3 (cross-sectional) may specifically rescue some of
   the dead directional cells -- a spread portfolio's cost dynamics differ from a directional
   trade's (see `docs/research/trade-construction-layer.md`).
2. **Every future analysis report tags which thesis its result supports or damages.** A
   qualifying feature is not evidence of edge; it is evidence *for a specific thesis* or it
   is unexplained (and unexplained results get the skeptical prior).
3. **T3 requires the PortfolioTrack to be testable at all** -- this is the strongest
   argument for scoping intel-11's PortfolioTrack, stronger than "firms do it."
4. **If, after 142A OOS + cost hurdle, no thesis has supporting evidence** -- the honest
   conclusion is T4-only: reframe the system as systematic conditional risk-premium
   harvesting at 1h/1d, cut the 5m/15m compute, and stop calling it alpha. That outcome is
   a success of the process, not a failure of the project.
5. **Added 2026-07-25, post-T2-falsification.** With T1 mostly killed by the cost hurdle and
   T2 now dead, the live decision is no longer "which thesis wins" in the abstract -- it's a
   concrete choice between three cheap-to-test candidates before committing to Phase 164/165's
   multi-week feature-expansion effort: **T3** (cross-sectional relative value -- construction
   change, no new features, `docs/research/trade-construction-layer.md`, now unblocked since
   Phase 142A's OOS gate cleared 2026-07-22) and **T5** (non-linear combiner -- modeling change,
   no new features, `docs/research/archive/measurement-nonlinear-interaction-combiner.md`). Both attack
   the *construction/modeling* side of the failure with the existing 150 features; Phase
   164/165 attacks the *feature* side using the same linear/absolute-direction construction
   that T2 just falsified. T3 and T5 are cheaper to test (reuse existing corpus and
   infrastructure, no multi-week build) and directly target what's actually confirmed broken -- recommend running both before deciding whether 164/165 is warranted at all.
6. **Added 2026-07-26, post-T3-pass.** Both cheap tests from item 5 ran. **T3 passed
   decisively** (see T3 above) -- this is now the strongest evidence-backed candidate on the
   whole doc, and the recommended next move is scoping `docs/research/trade-construction-layer.md`
   as a real phase (cost-hurdle-adjusted spread construction, then shadow measurement), ahead
   of Phase 164/165. **T5 came back suspicious**, not confirmed -- a 0.30 mean OOS IC is far
   outside this corpus's observed range and needs the canary-leakage check (see T5 above)
   before it can support or damage anything. Until that check runs, T5 is neither evidence
   for nor against committing to Phase 164/165 -- don't cite it either way.
7. **Added 2026-08-03, post-taxonomy-reorg.** Five new Signal-Extraction candidates (T6-T10)
   proposed, full design and cheapest-first sequencing above. None are urgent -- they're
   independent of the in-flight T5-at-15m/T3-at-5m work and can be picked
   up whenever that settles.

## References

- `docs/intelligence/intelligence-alphaengine.md` -- the epistemology this doc completes:
  "the data discovers confluence" answers HOW to find edge; this doc asks WHY edge should
  exist at all
- `docs/research/measurement-ic-engine.md` -- Cross-Sectional Rank IC addendum (T3's test
  vehicle; retired from `intel-11`, see `docs/research/archive/intel-11-dual-system-discrete-vs-portfolio.md`)
- Todo 030 (cost-hurdle APR calibration) -- the first falsification pass against realistic cost
  floors; closed and removed from `.planning/todos/`, its result summarized in this doc above
- `docs/plans/archive/2026-06-29-feature-scoring-beyond-ic.md` -- marginal contribution / shrinkage
  (the machinery that keeps thesis evidence honest)
- `.planning/todos/completed/179-gate166-concurrent-exposure-diagnostic.md` -- T2's falsification
  evidence, full 234-cell sweep and historical replication check
- `docs/research/trade-construction-layer.md` -- T3's construction and validation design
- `docs/research/archive/measurement-nonlinear-interaction-combiner.md` -- T5's original design
  proposal and overfitting controls (2026-07-25, archived 2026-08-03, fully absorbed above)
- `scripts/analysis/t3_cross_sectional_long_short_ctf_momentum_check.py` -- T3's falsification
  script and 2026-07-26 pass result
- `scripts/analysis/t5_nonlinear_combiner_lightgbm_check.py` -- T5's falsification script and
  2026-07-26 preliminary (pending canary check) result
