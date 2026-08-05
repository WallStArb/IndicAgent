# Edge Source Thesis -- Where Does Our Edge Come From?

**Version:** 2.1
**Status:** draft -- standing document; every claim here is falsifiable and must be revisited
as evidence lands
**Priority:** high -- **cross_sectional_relative_value's Phase 167 PASS is UNVERIFIED as of
2026-08-04, not confirmed** (both live Validation Gates were recorded as PASSED 2026-07-27, but
the sole ranking feature, `ctf_momentum`, was confirmed 2026-08-04 to carry real lookahead in
its batch join -- todo 243. A diagnostic-tier re-verification under the corrected join found
Gate 1 now FAILS, both scales' CI negative, shuffled-null no longer clearing -- see
cross_sectional_relative_value's own note below and `docs/research/trade-construction-layer.md`
for full detail. **Do not start Phase 168 until an authoritative re-verification lands.**);
**nonlinear_interaction_combiner's original "SUBSTANTIAL at 1h and 15m" verdict is SUPERSEDED --
confirmed overwhelmingly leak-driven at every tf tested** (todo 245, CLOSED 2026-08-04: 1h
collapsed 90.6%, 15m 79.1%, 5m 43.8% once the same leaked `ctf_momentum`-family columns were
excluded from the training matrix; a small, real, statistically significant residual survives at
every tf -- see nonlinear_interaction_combiner's own section below for the corrected numbers, not
"SUBSTANTIAL"). Two pre-registration gaps in nonlinear_interaction_combiner's own evidence found
and fixed the same investigation
([todo 240](../../.planning/todos/pending/240-nonlinear-interaction-combiner-baseline-is-single-feature-not-the-linear-ensemble.md),
[todo 239](../../.planning/todos/pending/239-nonlinear-interaction-combiner-embargo-passed-in-pooled-panel-rows-not-bars.md)).
Next step pre-registered, not yet run: does cross_sectional_relative_value's construction improve ranked by nonlinear_interaction_combiner's tree score instead of
`ctf_momentum` ([todo 238](../../.planning/todos/pending/238-nonlinear-interaction-combiner-ranked-cross-sectional-relative-value-pre-registration.md))
-- gated on cross_sectional_relative_value's own re-verification landing first, since it inherits
the same leaked ranking feature question.
Five Signal-Extraction candidates added 2026-08-03 (`cointegrated_pairs_residual`,
`statistical_factor_residual`, `cross_asset_lead_lag`, `adaptive_combiner_weights`,
`jump_diffusion_decomposition`) and three Trade Constructions the same day
(`stale_reference_price_adjustment`, `overnight_futures_information_transfer`,
`dealer_hedging_flow`) -- none tested. horizon_risk_premium remains untested and is the only
thesis here whose falsification criterion still lacks a pre-registered numeric bar.
**Milestone:** standing -- not tied to a phase
**Last Updated:** 2026-08-04
**Tags:** edge, thesis, counterparty, renaissance, falsifiable, first-principles

**Reorganized 2026-08-03** -- this doc always implicitly mixed two different kinds of claim
(see "What is deliberately NOT on this list" below, which already named "type #1" vs "type #2"
theses without ever visually separating them). Split into two groups: **Trade Constructions**
(retail_immediacy_provision, cross_sectional_relative_value, horizon_risk_premium, plus
stale_reference_price_adjustment / overnight_futures_information_transfer / dealer_hedging_flow
added later the same day -- each proposes a specific trade with a named counterparty) and **Signal-Extraction
Questions** (regime_conditional_persistence, nonlinear_interaction_combiner, and five new candidates
-- `cointegrated_pairs_residual`, `statistical_factor_residual`, `cross_asset_lead_lag`,
`adaptive_combiner_weights`, `jump_diffusion_decomposition` -- each asks whether processing the
*same* feature corpus differently reveals predictive power the current linear/pooled approach
misses). A positive Signal-Extraction result isn't a strategy on its own -- it feeds into a Trade
Construction (e.g., ranking by a non-linear combined score instead of a raw feature). Thesis names
were renamed from the original T1-T10 ticket numbers to descriptive concept names 2026-08-03; only
the grouping, headings, and labels moved, the content is unchanged. The five new candidates
(cointegrated pairs, statistical factor residual, lead-lag structure, continuously-adaptive
combiner weights, jump/diffusion decomposition) were proposed and written up in full the same
session, not yet tested. cointegrated_pairs_residual/adaptive_combiner_weights/jump_diffusion_decomposition name explicit stochastic-process constructs (Ornstein-
Uhlenbeck half-life, Kalman state-space, jump-diffusion decomposition) -- the closest this doc
gets to continuous-time stochastic calculus; none of it applies further than this (no SDEs, no
options-style path-dependent payoffs anywhere in scope).

**Reviewed 2026-07-25** -- re-read in full against todo 179's 2026-07-24 finding (an exhaustive
234-cell regime × symbol_hmm × lookahead-scale sweep for any absolute-direction, regime-
conditional edge in the current champion population). This doc's own regime_conditional_persistence falsification
criterion, written 2026-07-01 before that sweep existed, predicted exactly the test that
killed it -- see regime_conditional_persistence below. Still the correct standing doc; nothing here is stale, it's now
partially *resolved*. Added candidate thesis nonlinear_interaction_combiner (non-linear interaction structure) below,
prompted by the same finding: the one interaction axis the system already models explicitly
(regime × feature) just failed exhaustively, which raises the question of whether the *linear*
combiner is blind to interaction structure the 150 features already contain, independent of
whether more features (Phase 164/165) get added.

**Updated 2026-07-26** -- ran both cheap falsification scripts item 5 (below) recommended
before committing to Phase 164/165. cross_sectional_relative_value passed decisively; nonlinear_interaction_combiner came back with a suspiciously
large uplift that needs one more check before it's trustworthy. See cross_sectional_relative_value/nonlinear_interaction_combiner sections below for
full results. cross_sectional_relative_value's falsification script was archived once Phase 167 productionized it into
`services/cross_sectional_spread_tracker.py`; nonlinear_interaction_combiner's script is `scripts/analysis/nonlinear_interaction_combiner_lightgbm_check.py`.
**Also caught and flagged a methodology gap in regime_conditional_persistence** (below), since resolved: its original
falsification ran under cross-sectional regime labels that were themselves found miscalibrated
(todo 092). Re-run 2026-07-27 against the genuinely corrected, live production labels
(`market_regimes.regime_label`, post-recompute) -- confirmed dead, not provisional. See regime_conditional_persistence
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

- **The features are public.** All 263 `feature_vectors` columns are OHLCV-derived quantities
  (momentum z-scores, VWAP deviation, ATR, calendar position, VP/SR structure, SMC footprint)
  computable by anyone with a market data subscription. The corpus has grown ~5x since this
  line first read "all 54" -- the count changed, the argument did not. Every systematic shop
  has tested this class of quantity.
- **The universe is the most efficient corner of the market.** 80 of the most liquid,
  most-studied ETFs on earth. SPY's order book is the most competitive pricing environment
  in existence.
- **There is no non-equity data in the corpus at all** (verified live 2026-08-03). `instruments`
  registers 18 futures and 4 FX contracts, but **all 22 are `is_active = false` and have zero
  rows in `market_data_ohlcv`**. Every result in this doc is 80 equity ETFs, RTH only. Anywhere
  this doc or its neighbours describe the universe as "ETFs + futures/FX," that is a
  target-state description, not the measured corpus -- which matters directly for
  overnight_futures_information_transfer below, whose whole claim is that this absence is the
  single largest category-#1 (Information) gap in the setup.
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

#### Retail Immediacy Provision (counterparty: constrained flow)
At this account size (retail, no capacity pressure), the system can take the other side of
flows too small for institutions to bother with: end-of-day rebalance pressure in
lower-liquidity sector ETFs, overnight-gap mean reversion where market makers widen out.
**Why we might win:** capacity constraints don't bind at this size; institutions leave
crumbs below their minimum ticket. **Falsification:** the surviving cells should
concentrate in the less-liquid half of the universe and around session boundaries; if edge
concentrates in SPY/QQQ mid-session, retail_immediacy_provision is wrong.

**Status honestly stated (2026-08-03): the criterion above has never actually been run.** Item 1
of "What This Doc Demands From the Roadmap" describes retail_immediacy_provision as "killed or badly wounded," but
what killed it was todo 030's *cost-floor* test -- an orthogonal argument (short-horizon gross
edge doesn't clear spread), not the liquidity-and-session-boundary concentration test this
thesis pre-registered for itself. Those are different claims: the cost floor says the trade is
uneconomic at 5m/15m fast, the concentration test would say whether the mechanism is real at
all. **retail_immediacy_provision is therefore best described as "wounded on economics, untested on mechanism,"
not falsified.** It is also the vaguest thesis on this list -- "flows too small for institutions
to bother with" names a counterparty category, not a counterparty -- which is why the
sharpening below matters more than another cost re-run.

**Sharpening, added 2026-08-03: name the mechanical flow instead of "rebalance pressure."** The
one end-of-day flow in this universe that is genuinely mandatory, price-insensitive, dated, and
directionally *predictable from the day's own return* is **leveraged/inverse ETF issuers'
close rebalance**. A 3x fund must buy exposure after an up day and sell after a down day, into
the close, in size proportional to the day's move and to its own AUM -- it has no discretion and
no price target. None of those funds are in this universe (verified 2026-08-03: the 80 active
symbols contain no leveraged or inverse products), but that is exactly what makes the test clean:
**the flow lands on the underlying, which IS in the universe.** XLF, XLE, SMH, XBI, GDX, TLT,
IWM, QQQ, SPY all carry large levered sleeves; SCHD, SDOG, USMV, QUAL, MUB, PFF, DBA and similar
carry none or negligible ones. **Falsification (pre-registered here, before running):** the
last-bar-of-session return must be positively related to the same session's prior return,
**and that relationship must be materially stronger in the levered-sleeve group than in the
no-sleeve control group**, held to the same day-clustered bootstrap + BH-FDR bar as everything
else here. If the effect is present but uniform across both groups, it is ordinary intraday
momentum and this mechanism is not what produces it -- the control group is the whole test.
**Cost:** cheap -- existing 5m/15m OHLCV, plus a one-time hand-built symbol -> has-levered-sleeve
mapping (a static list, not a data feed). **Untested.**

**Suggestive, explicitly not a test of the above:** cross_sectional_relative_value's Gate 2 static leg-membership
vector (`docs/research/trade-construction-layer.md`) puts EWT/BIL/EWY/EEM/CIBR at the most-long
end and BTAL/KWEB/FXY/FXI/INDA at the most-short end -- none of them SPY or QQQ. That is
consistent with retail_immediacy_provision's "less-liquid half" prediction, but it is a retrospective summary of a
*different* construction's realized leg membership, not a run of retail_immediacy_provision's criterion, and it says
nothing about session boundaries. Do not cite it as evidence for retail_immediacy_provision.

#### Cross-Sectional Relative Value (counterparty: single-name flows) -- **PASSED 2026-07-26, PRODUCTIONIZED 2026-07-27, GATE VERDICT UNVERIFIED as of 2026-08-04 (todo 243/253)**
Individual ETFs get pushed off fair relative value by idiosyncratic flows (sector rotation,
thematic retail); the *ranking* across 80 correlated instruments mean-reverts even when no
single instrument is predictable directionally. **Why we might win:** relative-value noise
cancellation is statistically much easier than directional prediction; this is the
lowest-IC-requirement thesis on the list. **Falsification:** cross-sectional long-short
spread portfolios built from feature rankings must show positive net return where per-symbol
directional trades on the same features don't. Requires the cross-sectional rank IC measurement
mode (`docs/research/measurement-ic-engine.md`, "Addendum: Cross-Sectional Rank IC") to even
test. If the spread portfolio is no better than directional, cross_sectional_relative_value is dead.

**Result (`scripts/analysis/t3_cross_sectional_long_short_ctf_momentum_check.py`, 2026-07-26 --
script deleted 2026-07-28 in `8a9bdf32`, "remove 19 stale one-off analysis scripts"; recover
from git history, the path no longer resolves in a working tree):**
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

**Productionized 2026-07-27, gate verdict UNVERIFIED as of 2026-08-04 (todo 243/253) --
see `docs/research/trade-construction-layer.md`'s "Correction, 2026-08-04" for full detail, not
duplicated here.** The falsification script became a real service,
`services/cross_sectional_spread_tracker.py`, ranked solely on `ctf_momentum`. A full 2006-2026
backfill populated `construction_spreads` (24,924 bars), and both live Validation Gates were
recorded 2026-07-27 as PASSED against the real OOS population -- Gate 1 (shadow spread Sharpe,
net of cost) at the most conservative 10bp round-trip tier, Gate 2 (attribution honesty). **That
record is not currently trustworthy**: `ctf_momentum`, the sole ranking feature, was confirmed
2026-08-04 to carry real lookahead in its batch HTF join (todo 243). A diagnostic-tier
re-verification under the corrected join found Gate 1 now FAILS (both scales' CI negative,
shuffled-null no longer clearing) -- not yet authoritative-tier confirmed, but consistent with a
SPY single-symbol pilot showing the same collapse. **Do not cite either gate as PASSED, and do
not start Phase 168, until an authoritative re-verification lands.** Full numeric detail for both
the original and corrected-join numbers: `docs/research/trade-construction-layer.md`'s Validation
Gates section (one doc owns the gate numbers).

**Two scope limits worth carrying with the headline, both from that same section:** (1) the
gates were evaluated on the **OOS segment only -- 650 bars across 130 day-clusters**, not the
24,924-bar backfill (the full-history figures are an explicitly-labelled in-sample diagnostic
there, never fed into `gate1_passes`); the backfill's size is the corpus, not the sample size of
the verdict. (2) Gate 2 falsifies in **one direction only** -- its static-tilt benchmark is a
retrospective, time-averaged summary of realized leg membership over the same window it
explains, so a low `static_r2` plus a surviving residual rules out *that* explanation without
establishing what does generate the return. "PASSED" here means "not shown to be a disguised
static tilt," not "mechanism identified."

**Both gates clearing was recorded as meeting the Phase 156-159 execution/sizing chain's stated
precondition for this construction** -- unlike Phase 148's per-symbol directional construction,
which passed Gate 1 but failed Gate 2. **That clearance is not currently valid** (see the
correction above) -- re-verification under the corrected `ctf_momentum` join is now the
precondition, not a cleared one. No capital has been deployed anywhere in this project regardless;
Phase 156-159 (the actual execution/sizing layer) has not been started.

**Open question, found 2026-08-03: `_TF="15m"` (`services/cross_sectional_spread_tracker.py:105`)
is an inherited default, not a comparative finding.** It came from whichever tf the original
falsification script happened to test first, not from testing cross_sectional_relative_value's actual netted spread
construction at other tfs. The one existing 5m result (todo 030) measured *standalone
directional* IC against cost floors, not cross_sectional_relative_value's dollar-neutral netted spread -- which this doc's
own item 1 (below) already notes has different cost dynamics. Todo 235 tracks running cross_sectional_relative_value's real
methodology at 5m before treating 15m as the right choice rather than just the first one tried.

**Sibling CTF features tested, both rejected (`scripts/analysis/t3_ctf_family_check.py`,
2026-07-27 -- also deleted in `8a9bdf32`, recover from git history):** `ctf_momentum` has two untested siblings from the same `_build_ctf_series()`
function (`services/backfill_feature_factory.py`) -- `ctf_vwap_align` (sign of close vs. HTF
cumulative VWAP) and `ctf_regime_align` (HTF HMM forward-pass state, 0=ranging/1=trending) --
already computed and sitting in `feature_vectors`, zero new data cost to test through the
identical cross_sectional_relative_value methodology (same bootstrap, same shuffled-null guard, same cost-hurdle sweep).
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

#### Horizon Risk Premium at 1h/1d (counterparty: nobody -- risk premium)
The honest fallback: at longer horizons with low turnover, small conditional tilts
(vol-conditioned momentum, flight-to-quality) earn modest risk-adjusted returns that are
partly repackaged risk premia. **Why we might win:** we don't need to win against anyone;
we need to harvest systematically without behavioral errors. This thesis caps expectations at
"good systematic beta," which is a legitimate but different product.

**Falsification, restated 2026-08-03 because the original was not falsifiable as written.** It
read: "returns should survive but shrink substantially when regressed against standard factor
exposures." That names no factor set, no threshold, and no failing outcome -- under it, a large
shrink confirms the thesis and a small shrink also confirms something, so nothing kills it. It
is the only criterion in this doc that no result could have contradicted. Replacement, to be
pre-registered in full before any run:

1. **Name the factor set up front, from symbols already in the corpus** -- market (SPY),
   size (IWM minus SPY), value/growth (VTV minus VUG), momentum (MTUM minus SPY), low-vol
   (USMV minus SPY), duration (TLT), credit (HYG minus IEF), dollar (UUP). Chosen because they
   are all in the 80-symbol universe, so the regression needs no new data and no vendor factor
   file. Fixed before seeing any result; no adding or dropping a factor after the fact.
2. **Two thresholds, both stated before running.** (a) *Kill:* if the strategy's return, net of
   the same cost-hurdle sweep cross_sectional_relative_value's gates use, does not clear zero on a day-clustered bootstrap
   CI **before** any factor adjustment, horizon_risk_premium is dead -- there is nothing to attribute.
   (b) *Reclassify:* if it clears (a) but the factor-model intercept does not clear zero on the
   same CI, the result IS horizon_risk_premium -- harvested beta -- and must be described as such,
   sized as such, and never counted as alpha anywhere downstream.
3. **The residual case is the informative one.** If the intercept survives with an R-squared low
   enough that the factors explain little, horizon_risk_premium is the *wrong* label for the result and the
   return belongs to some other thesis on this list, which then has to be named. "Unexplained"
   is not an answer; it inherits the skeptical prior, per item 2 of "What This Doc Demands."

**Untested.** Nothing in this doc has ever run a factor regression against this system's
returns; item 4 below currently treats horizon_risk_premium as a fallback conclusion, which is a judgement
about what to do if everything else fails, not evidence that horizon_risk_premium itself holds.

#### Three New Trade Constructions, added 2026-08-03, none tested yet

The three theses above were written before the universe was verified as 80 equity ETFs, RTH only,
and they share a blind spot because of it: **every one of them proposes a trade that lives
entirely inside the US regular session on US-listed equity products.** The five source categories
at the top of this doc are not evenly attacked -- category #3 (counterparty constraint) has one
vague entry (retail_immediacy_provision), #5 has one (horizon_risk_premium), #2 has the whole Signal-Extraction
group, and **#1 (Information someone else doesn't have) has nothing at all**, which is precisely
the category this doc's own opening says was most of Renaissance's moat. The three below are
picked to attack #1 and #3 specifically, and each one is falsifiable against a **control group
already in the universe** rather than against a bare threshold -- a control group is much harder
to fool than a p-value.

**Stale Reference Price Adjustment (counterparty: investors trading a fund whose underlying
market is closed).** 13 of the 80 symbols track markets that are shut for most or all of US RTH:
EWJ, EWT, EWY, FXI, MCHI, KWEB, INDA (Asia -- closed the entire US session), EWG, EZU, EFA
(Europe -- closed from ~11:30 ET), EEM, VWO, EMB (mixed), against EWZ (Brazil -- essentially
fully overlapping) and the ~66 domestic ETFs (fully overlapping by construction). When the home
market is shut, the ETF's US price is not a print of the underlying; it is a *forecast* of where
the underlying will open, made by whoever is willing to trade the wrapper. **Why we might win:**
the mispricing is structural and mechanical rather than behavioral -- the reference price is
literally stale, and the marginal US-hours participant in a thin Asia-tracking fund is not the
one arbitraging it against home-market futures. **Falsification (pre-registered here):** this is
a **dose-response** test, not a two-group one. Rank the universe by fraction of the US session
during which the home market is closed (Asia 1.0 -> Europe ~0.4 -> Americas 0.0), and require
the predictive power of the US-session signal for the ETF's next executable open-to-open return
to **decline monotonically across that gradient**, day-clustered bootstrap + BH-FDR as always.
If the effect is flat across the gradient, it is ordinary momentum or reversal and this mechanism
is not what produces it -- flatness kills the thesis even if the raw effect is large and
significant. **Honest prior, stated before running: this is likely to fail, and the reason is
specific.** ETF authorized participants hedge exactly this exposure against home-market futures
all day, so most of the adjustment should already be impounded in the US closing price; and
whatever remains gets released in the opening auction -- which is the *entry* price under
Invariant 1's executable open-to-open definition, so it is structurally uncapturable here. The
test is worth running anyway because it is cheap and because the failure mode is informative,
not because the prior is favourable. **Cost:** cheap -- existing OHLCV plus a static
symbol -> home-session-overlap mapping. Note the existing `asian_session_*` / `overnight_*` /
`opening_gap_pct` columns do **not** already encode this: they are computed from the ETF's own
US-listed bars, so they capture thin US pre-market prints in the wrapper, not the home index's
actual session.

**Overnight Futures Information Transfer (counterparty: participants priced off RTH-only
instruments).** The corpus is RTH-only US equity, so roughly two-thirds of every 24-hour period
is a hole in the data. Index futures trade through that hole. **Why we might win:** this is the
only genuine category-#1 (Information) claim available at retail cost -- not data nobody has,
but data this system provably does not have while the instruments it trades are demonstrably
driven by it. **The naive version is wrong and should be rejected up front:** the overnight *gap*
itself is already in `open[T+1]`, which under Invariant 1 is the entry price, so predicting the
gap is worth nothing. The claim is narrower: the **path** through the overnight session --
realized overnight variance, whether the move was one directional drift or a reversal, how much
of the range was retraced by the open -- is information about the *state* of the market at the
moment of entry that is entirely absent from any RTH bar, and it predicts what happens *after*
the open. **Falsification (pre-registered here):** overnight futures path statistics must add
incremental IC to the executable open-to-open target **beyond** the ETF's own prior-session
features (the same incremental-IC bar jump_diffusion_decomposition uses, not "is it predictive alone"), and the
uplift must scale with the symbol's beta to the index future -- large for SPY/QQQ/IWM/DIA/RSP,
near zero for MUB/BIL/DBA. A uniform uplift across high- and low-beta symbols means the path
statistics are proxying something else. **Cost: the most expensive item in this doc, and the
only one that is data-blocked rather than work-blocked.** Verified 2026-08-03: `instruments`
holds 18 futures and 4 FX contracts, all `is_active = false`, with **zero rows in
`market_data_ohlcv`**. This needs an ingestion path stood up and backfilled before a single
number can be produced. Sequence it behind everything cheap; file it here so the gap is named
rather than silently inherited.

**Dealer Hedging Flow (counterparty: options market makers under a delta-hedging mandate).**
Options dealers who are net long gamma must trade against price moves to stay delta-neutral
(sell strength, buy weakness -- mechanically dampening realized volatility and manufacturing
intraday mean reversion); net short gamma forces the opposite, amplifying moves. The flow is
mandatory, price-insensitive, and sized by an exposure that changes discretely when large open
interest expires. **Why we might win:** it is category #3 in its purest available form -- a
counterparty who must trade for a non-price reason on a schedule known in advance -- and it is
the one such flow that reaches the ETFs in this universe rather than single names. **Falsification
(pre-registered here):** a measurable OHLCV proxy for intraday mean-reversion strength (e.g. the
ratio of close-to-close realized variance to range-based variance over the session, or the
autocorrelation of intraday bar returns) must differ between the sessions preceding and following
monthly option expiry, **and that difference must concentrate in the heavily-optioned
underlyings (SPY, QQQ, IWM, TLT, GLD, SMH) versus near-zero in the negligibly-optioned ones
(SDOG, SPHB, CIBR, IPO, QUAL)**. Uniform across both groups, or absent, kills it. **This is not
a re-skin of the calendar features that already top the IC list:** those are `month_position`,
`quarter_position`, `dow_sin/cos`, `week_of_month_sin/cos` -- smooth positional encodings that
cannot isolate a specific third-Friday date (a sin/cos week index does not identify which week
contains the third Friday, since that varies with the month's start weekday). No expiry
indicator exists in `feature_vectors`; verified 2026-08-03. **Cost:** the calendar-proxy screen
above is cheap and uses only existing OHLCV. The real version -- actual dealer gamma exposure
from options open interest and skew -- needs an options-chain data source this project does not
have and should not buy on spec. **The cheap screen is a gate on the expensive data, not a
substitute for it:** a negative screen closes the thesis, a positive screen is the only thing
that would justify paying for chains.

### Signal-Extraction Questions

#### Regime-Conditional Persistence (counterparty: unconditional models) -- **FALSIFIED, CONFIRMED 2026-07-27 on live corrected labels -- no longer provisional**
Features with zero pooled IC but real conditional IC (the whole stratification premise).
Participants running unconditional models mis-price bars in minority regimes.
**Why we might win:** most simple systematic flows are not regime-conditioned; conditioning
is our one genuine structural bet. **Falsification:** regime-stratified IC must materially
exceed pooled IC for the same features OOS (not just in-sample, where stratification
mechanically inflates cell significance), and the regime labels themselves must pass the
026 validation. If conditional ≈ pooled OOS, regime_conditional_persistence is dead and most of the stratification
machinery is measurement theater.

**Result (todo 179, 2026-07-24):** this exact test was run, at full rigor. All 9
cross-sectional regimes × 6 symbol_hmm states × 3 lookahead scales (234 cells, 126 with
sufficient day-cluster coverage), day-clustered bootstrap + BH-FDR. Exactly 2 cells passed
initially (`low_bull`×`trending_down`, 5m, both lookahead scales, `ci_lower` positive). Neither
survived out-of-window replication against 12 independent historical episodes back to 2008 -- critically, the finding didn't even hold in its *own* discovery window once the ensemble's own
`alpha_score > 0` conditioning was removed (`ci_lower` negative at every scale on raw regime
labels alone). **Zero cells, at any granularity tested, show real non-circular positive
expectancy.** regime_conditional_persistence is dead by this doc's own pre-registered criterion -- regime conditioning,
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
floor, genuinely untestable in the current OOS window, not a new negative finding. **regime_conditional_persistence's death
is now confirmed on live, non-stale data -- no longer provisional.** Full detail:
`.planning/todos/completed/179-gate166-concurrent-exposure-diagnostic.md`'s live-label
re-verification section. Separately, this test also only covers the feature set live as of
2026-07-24 (through Phase 163, with the 17 new structural columns still incomplete on
historical rows per todo 176) -- it says nothing about features Phase 164/165 hasn't built yet.

**What regime_conditional_persistence's death does NOT prove:** that regime information is worthless, or that no
interaction effect involving regime exists -- only that a *linear*, single-dimension,
categorical treatment of it doesn't clear a bar. See nonlinear_interaction_combiner below.

#### Nonlinear Interaction Combiner (counterparty: linear-model participants) -- small, real residual survives at every tf once the CTF leak is excluded; "SUBSTANTIAL" is SUPERSEDED
(Heading corrected 2026-08-04, todo 247, superseding the 2026-08-03 correction below -- that
correction's "real and substantial at 15m/1h" verdict is itself now known to have been
overwhelmingly leak-driven, not a re-baselining issue. See "Correction, 2026-08-04 (todo
245/247)" immediately below for the current numbers. The 2026-08-03 heading text and its
rationale are preserved as the next paragraph for the historical record, not because it is still
current.)

*(Original 2026-08-03 heading, preserved for history: "real and substantial at 15m/1h, small at
1d, and measured against the wrong baseline throughout." It previously read "confirmed SMALL, not
LARGE (small only at 1d; substantial at 1h/15m)" -- a leftover from the window when 1d was the
only replication, self-contradicting once 15m landed. Separately, every run at that time compared
the tree to `ctf_momentum` alone rather than to the linear ensemble this thesis's own
falsification bar names -- fixed by todo 240 the same day this section was superseded.)*

**Correction, 2026-08-04 (todo 245/247):** the 1h/15m "substantial" magnitude above was measured
before anyone checked whether the tree's advantage depended on the same lookahead-leaking
`ctf_momentum`/`ctf_vwap_align`/`ctf_regime_align` columns todo 243 found in the batch HTF join.
It did, overwhelmingly. Excluding all three CTF columns from the training matrix at every tf
(same corpus, same walk-forward methodology, todo 245's with/without-CTF diagnostic):

| tf | point_ic with CTF | point_ic without CTF | collapse | n_pass_fdr_positive (80 max) | residual tree-vs-linear diff | residual ci_lower |
|---|---|---|---|---|---|---|
| 1h | 0.1811 | 0.0171 | 90.6% | 80 -> 21 | 0.0106 | 0.0064 |
| 15m | 0.2504 | 0.0524 | 79.1% | 80 -> 73 | 0.0348 | 0.0330 |
| 5m | 0.1741 | 0.0979 | 43.8% | 80 -> 79 | 0.0710 | 0.0701 |

A small, real, statistically significant residual edge (tree beats the fold-local linear
ensemble baseline, not just `ctf_momentum` alone -- todo 240's fix) survives at every tf, roughly
15-70x smaller than the pre-correction numbers below, not a total null. **Pattern**: collapse %
shrinks as tf gets finer while the absolute surviving residual grows -- consistent with the
leak's magnitude being roughly bounded by HTF bar duration (~constant across tf) while the tree's
total predictive power grows at finer granularity, so the leak's proportional share shrinks even
as the real edge grows. Verified separately: the live production ensemble (`ensemble_weights`) is
NOT contaminated -- `ctf_momentum` has zero rows there, fails BH-FDR eligibility at every tf; the
exposure was this research script's own training matrix and Phase 167's live ranking feature
(see cross_sectional_relative_value's correction above), not the live signal path. **The strategic
read this reframes**: the tree's core failure mode (no per-feature exposure cap, unlike the
linear arm's 20% cap) is why it rode the CTF leak this hard -- a structural argument against
unconstrained-tree interaction discovery on this corpus generally, not just a one-off bug to
patch. `docs/research/measurement-nonlinear-interaction-combiner.md` has the deepened design
critique and two pre-registered alternative test designs (N1 residual-form, N2 regime-conditional
linear) not yet run. The historical result narrative below (pre-correction numbers, the canary
checks, the embargo/baseline fixes) is preserved as an accurate record of what was measured at
each stage -- read it as history, not as the current verdict.
The ensemble combiner (`ensemble_trainer.py`) is a linear, shrunk-IC-weighted sum of
per-feature marginal predictive power. It can express "feature X predicts returns" but
structurally cannot express "feature X predicts returns only when feature Y crosses a
threshold" -- any conditional/interaction structure across the feature corpus is invisible to
it by construction, the same way regime_conditional_persistence's single categorical regime axis was one narrow,
already-tested instance of exactly this blind spot. **Why we might win:** this is a specific,
named processing advantage (per the "deliberately NOT on this list" rule below) -- not "our ML
is better" in general, but "the current combiner is linear and 150 features have 11,175
pairwise-interaction slots it never evaluates" (as written 2026-07-25; at today's 263 columns
the count is ~34,000, which makes the gap wider, not narrower). **Falsification:** a non-linear combiner
(gradient-boosted trees or a shallow net) over the identical `feature_vectors`/
`forward_returns` corpus, evaluated with the same walk-forward OOS discipline, day-clustered
bootstrap CI, and BH-FDR correction as everything else in this doc, must show a statistically
significant Sharpe/IC uplift over the existing linear ensemble on the *same* features. If it
doesn't, nonlinear_interaction_combiner is dead -- the bottleneck isn't the combiner's linearity, which strengthens the
case for either cross_sectional_relative_value (construction, not modeling) or that this feature set genuinely has no
edge to extract regardless of how it's combined. Original design proposal and overfitting
controls: `docs/research/measurement-nonlinear-interaction-combiner.md` (un-archived 2026-08-03 --
the CTF-leak finding below reopened the question of whether an unconstrained tree is even the
right model choice here; see that doc's Status header for the current framing).

**Result (`scripts/analysis/nonlinear_interaction_combiner_lightgbm_check.py`, 2026-07-26): canary-leakage
check clears this specific failure mode -- genuinely interesting, still not a confirmed pass.**
Equity/1h, shallow regularized LightGBM (200 trees, depth 4, walk-forward folds via
`ic_math.py`'s `build_walk_forward_folds`, `_EMBARGO_BARS = 24` -- see the embargo-units
correction below, this is 24 *rows* of a pooled panel, not 24 bars), compared against
`ctf_momentum` alone on identical OOS rows. During development this run already caught one real leak: naive
pooled training showed mean_ic≈0.30 with 80/80 symbols passing, traced to the tree implicitly
learning each ETF's own persistent long-run drift (a fixed-membership factor-exposure leak, not
bar-level signal) -- fixed by subtracting each symbol's own causal (shift(1), expanding) mean
return before training/measuring. **After that fix, the tree still comes back at mean OOS
point_ic=0.30 (80/80 symbols pass CI) vs. `ctf_momentum`'s 0.09 (79/80 pass)** -- a ~3.4x
uplift, and a within-bar_ts cross-sectional-neutral decomposition confirms it isn't purely a
common-market-factor artifact (tree: point_ic=0.258, `ci_lower`=0.254; feature: point_ic=0.080,
`ci_lower`=0.076).

**Canary-leakage check (todo 184, `scripts/analysis/t5_canary_leakage_check.py`, 2026-07-26 --
script deleted in `8a9bdf32`, recover from git history):**
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
a look-ahead-leakage artifact.** This does not, by itself, prove nonlinear_interaction_combiner is real -- the result is
still ~3x anything else measured in this corpus and warrants continued skepticism (independent
replication across other tfs/periods, per this project's resist-overfitting discipline) before
any production consideration. But the specific failure mode todo 184 was filed to rule out is
ruled out with real evidence, not absence of a red flag. nonlinear_interaction_combiner moves from "preliminary, blocked on
this check" to "genuinely interesting lead, not yet a confirmed pass" -- the next legitimate
step is independent replication (a different tf, a different OOS window), not further leakage
investigation on this same result.

**Independent replication at equity/1d (`scripts/analysis/nonlinear_interaction_combiner_replication_1d.py`,
2026-07-27): PARTIALLY replicates, at a much smaller magnitude -- NOT the same finding.** Same
pipeline (identical causal per-symbol demeaning fix, walk-forward folds, block-bootstrap CI),
recalibrated embargo (5 bars vs 1h's 24) and per-symbol row floor (100 vs 300) for 1d's cadence,
plus a genuine methodological addition the original script and its leak-check never had: BH-FDR
correction across the ~80 per-symbol tests (`ic_math.py`'s `apply_bh_fdr`, sign-gated -- the
research doc's own nonlinear_interaction_combiner falsification bar requires "the same... BH-FDR correction as everything
else in this doc," which neither prior nonlinear_interaction_combiner script applied).

Result, raw per-symbol: tree mean `point_ic`=0.0183 (11/80 pass `ci_lower>0`, 5/80 survive
BH-FDR with correct sign); `ctf_momentum` mean `point_ic`=**-0.0244** (1/80 pass, negative on
average at this tf). Cross-sectional-neutral rigor pass (the component most relevant to a
cross_sectional_relative_value-style dollar-neutral construction): tree `point_ic`=0.0164, `ci_lower`=0.0081, **clears
zero**; `ctf_momentum` `point_ic`=-0.0084, `ci_lower`=-0.0174, **does not clear zero (trends
negative)**. Full per-symbol table: `docs/analysis/t5-replication-1d-per-symbol.csv`.

**Two findings, not one:**
1. **The tree DOES show a real, FDR-surviving cross-sectional-neutral uplift at 1d** -- this is
   a genuine replication in direction, in a tf far enough from 1h to rule out "succeeded for
   boring reasons like shared regime artifacts." nonlinear_interaction_combiner is not dead.
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

**Revised verdict: nonlinear_interaction_combiner is neither confirmed nor dead -- it is confirmed SMALL, not confirmed
LARGE.** The original 1h finding likely overstated the effect's true, tf-general size.

**UPDATE 2026-08-02: both the 1h and 1d numbers above independently re-verified under a
corrected corpus -- both hold, both come down moderately, nonlinear_interaction_combiner's verdict is unchanged.** Two real
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
Fix: `_nonlinear_interaction_combiner_shared.py` rewritten to build the training matrix directly from
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
construction trades. Read: nonlinear_interaction_combiner's magnitude is not uniformly small across timeframes -- it's
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

**Three caveats on nonlinear_interaction_combiner's evidence, found 2026-08-03 by checking each run against the
criterion pre-registered for it. None of them is a new result, none of them overturns the
finding, and all three should travel with the headline number.**

1. **The pre-registered baseline was never used.** The falsification bar above says the tree must
   beat "**the existing linear ensemble** on the *same* features." Every run -- 1h, 1d, both
   re-verifications, 15m, the 5m in flight -- compares the tree to `ctf_momentum` alone
   (`scripts/analysis/_nonlinear_interaction_combiner_shared.py:516`, `baseline_feature: str =
   "ctf_momentum"`). No script anywhere compares it to `ensemble_trainer.py`'s
   shrunk-IC-weighted linear combination. **What has actually been demonstrated is that a
   263-column gradient-boosted model beats one hand-picked column** -- a much weaker claim than
   "the combiner's linearity is the bottleneck," because an unknown share of the 4x gap is
   breadth of inputs, which the existing linear ensemble already has. This does not make the
   result uninteresting (the 15m tree score is a strong ranking candidate for todo 238 on its
   own merits, where `ctf_momentum` is the correct reference because it is what the live tracker
   ranks by) -- it means the *thesis as stated* is untested.
   [Todo 240](../../.planning/todos/pending/240-nonlinear-interaction-combiner-baseline-is-single-feature-not-the-linear-ensemble.md).
2. **The embargo is in rows, not bars.** `_nonlinear_interaction_combiner_shared.py` passes
   `embargo_bars` into `build_walk_forward_folds(n_valid=len(X), ...)` where `X` is the pooled
   panel (~80 rows per `bar_ts`, `ORDER BY bar_ts, symbol`), so `build_walk_forward_folds` does
   its `test_start = train_end + embargo_bars` arithmetic in **row** units. The intended ~1-day
   separations are 24 / 96 / 5 rows at 1h / 15m / 1d, which is ~0.3 / ~1.2 / ~0.06 bars of
   actual wall-clock separation, and the fold boundary lands mid-`bar_ts` so one bar's symbols
   split across train and test. **Blast radius is bounded by arithmetic, not by assumption:**
   5 fold boundaries x ~2 bars of target horizon x ~80 symbols ≈ 800 rows against 2M-8.5M
   training rows, so it does **not** plausibly explain a 0.18-0.25 cross-sectional-neutral
   `point_ic`. It is still wrong, it is still quoted above as a rigor credential, and it is
   cheap to fix.
   [Todo 239](../../.planning/todos/pending/239-nonlinear-interaction-combiner-embargo-passed-in-pooled-panel-rows-not-bars.md).
3. **"80/80 symbols pass" is not 80 independent confirmations.** This doc's own "Breadth Is the
   Binding Constraint" section puts effective breadth at ~8-15 across these 80 correlated ETFs.
   The same arithmetic applies to the per-symbol test family: 80 highly-correlated per-symbol
   ICs measured on a shared, largely common return process carry closer to ~10 independent tests
   worth of evidence, so unanimity is roughly what a single strong common effect would produce
   and is weaker corroboration than the raw count suggests. BH-FDR remains valid here (it holds
   under positive dependence), so the *significance* claims stand -- what is overstated is the
   intuitive reading of 80/80 as breadth of replication. The cross-sectional-neutral
   decomposition is the part of the evidence that genuinely addresses this, and it is the number
   to quote.

**Candidate input-feature extension, added 2026-08-03 (from reviewing arXiv:2512.21804, "S&P 500
Stock's Movement Prediction using CNN"; full critique in
`docs/ideas/signal-convolutional-raw-window-representation.md`).** The paper's core method
(raw price levels as CNN input, per-symbol training, shuffled train/test split) is rejected
outright -- it collides directly with [[project_v3_feature_port_raw_price_antipattern]] and
several other methodological problems documented in that idea doc. But stripped of the flawed
execution, one narrow, honestly-scoped question survives: does the tree combiner's existing
263-column input set already capture everything about a rolling window's *return-path shape*
(realized skewness of the intra-window return path, path convexity/local-reversal count, etc.),
or would causal, stationary path-shape statistics add incremental IC beyond what's already
there? This is NOT a change to the combiner itself (linear vs. non-linear, the question
nonlinear_interaction_combiner already answers) -- it's a candidate addition to the *input*
feature set, tested through the same incremental-IC-over-existing-features bar
jump_diffusion_decomposition already uses, not "is it predictive alone." Given most OHLC-shape
information is plausibly already captured
by the existing 263-column corpus (VP/SR, SMC, momentum, volatility families), the honest prior
is that this adds little -- not filed as its own thesis, just parked here as a cheap thing to
check if a future feature-primitives pass (Phase 151-style) is already in motion, not a reason
to start one.

**UPDATE 2026-08-03: 5m gap found, not yet closed -- two OOM kills, two different causes, root
cause fixed, empirical result still outstanding.** `scripts/analysis/nonlinear_interaction_combiner_replication_5m.py`
was built in the same commit that fixed 15m's OOM (`28083dd7`, "replicate at 15m/5m") but was
never actually run -- no output CSV, not reflected above.

Attempt 1 (float16 feature matrix, same mitigation as 15m; 5m is ~2.9x 15m's row count):
OOM-killed on the last, largest walk-forward fold. Root-caused via
`superpowers:systematic-debugging`, not re-guessed: LightGBM's Python bridge
(`lightgbm/basic.py`'s `_np2d_to_np1d`) silently upcasts any non-float32/float64 array to a full
float32 COPY before every `Dataset`/`predict()` call, so float16 storage didn't reduce what
LightGBM actually trained on -- it added a second, transient float32 copy of the active fold ON
TOP of the resident float16 array, worse than storing float32 to begin with. Fixed: reverted to
float32 (matching 1h/1d/15m exactly), deleted the now-dead float16 support path rather than
leaving it as inert complexity.

Attempt 2 (float32, post-fix): OOM-killed again, but at only ~14.85GB anon-rss -- well under the
~24GB float32 `X` should need -- confirmed via kernel log (`journalctl -k`) simultaneously with a
**separate Docker container OOM-killing in a different cgroup the same second**. This is
host-wide memory contention (Postgres shared_buffers/checkpointer/autovacuum, concurrent sessions,
the full observability stack all sharing this 29GB host), not a defect in the fix -- environmental,
not a second code bug. Logs from both failed attempts cleared 2026-08-03 for a clean rerun; no
5m CSV exists in `docs/analysis/` yet. Result to be recorded here once a run completes. It
inherits all three caveats above, including the row-unit embargo (todo 239), which at 5m is 96
rows ≈ 1.2 bars.

**Next step, pre-registered before running (not yet started): does cross_sectional_relative_value's construction improve if
ranked by nonlinear_interaction_combiner's tree score instead of `ctf_momentum`?** Both halves are independently proven at
15m -- the obvious combination is untested. Explicitly NOT a mechanical column swap: needs the
full falsification bar (shuffled null, cost-hurdle sweep, turnover, a Gate-2-equivalent
factor-attribution check, and an effective-breadth-preservation check, since a trained model's
ranking output can silently encode a static factor tilt or narrow effective breadth in ways
`ctf_momentum` doesn't) written down before running, not after seeing the number -- same
discipline as cross_sectional_relative_value's shuffled-null and nonlinear_interaction_combiner's own todo-184 canary-leakage check. Full pre-registered
design: [todo 238](../../.planning/todos/pending/238-nonlinear-interaction-combiner-ranked-cross-sectional-relative-value-pre-registration.md).
Gated on the 5m result above landing first, since it may change which tf(s) are worth testing.

#### Five New Signal-Extraction Candidates, added 2026-08-03, none tested yet

(`cointegrated_pairs_residual`, `statistical_factor_residual`, `cross_asset_lead_lag`,
`adaptive_combiner_weights`, `jump_diffusion_decomposition` -- named T6-T10 in earlier prose;
renamed 2026-08-03 so the label itself carries the mechanism, not just a ticket number.)

regime_conditional_persistence tested one grouping (discrete price-trend regime) and one combination rule (linear). nonlinear_interaction_combiner
tested one combination rule (non-linear tree) on the same grouping (none -- pooled). That leaves
real gaps: different **groupings** (pairwise structural relationships, orthogonalized factors),
different **temporal structure** (lead-lag, not contemporaneous), and different **combination
dynamics** (continuous adaptation, not a discrete regime switch or a static fit). Ideas that
would just re-run regime_conditional_persistence's regime-conditioning against a different regime definition (liquidity
regime, volume regime) were considered and dropped -- too close to an already-falsified instance
to justify a new T-number without first checking whether the falsification generalizes.

This universe's binding constraint (see "Breadth Is the Binding Constraint" below) matters here:
effective breadth ~8-15 across 80 correlated ETFs. That rules out some classic stat-arb
approaches at face value (true cointegration wants economically related PAIRS, not a broad
basket) but doesn't rule out others (factor decomposition works fine on a small, correlated
universe -- that's exactly the regime PCA is built for).

**Cointegrated Pairs Residual (counterparty: basket/index flows that ignore pairwise structure).**
A genuinely different grouping than regime_conditional_persistence (regime) or cross_sectional_relative_value (broad cross-sectional rank): specific,
economically-linked pairs (sector leveraged/inverse pairs, a miner ETF vs. the metal it tracks,
`TLT`/`IEF`) tested for a stable cointegrating relationship whose short-run deviations
mean-revert -- the classical Engle-Granger/Johansen stat-arb structure. **Falsification:** (1)
screen candidate pairs by economic relatedness, not a blind correlation scan across all 80
symbols (a blind scan risks the exact multiple-comparisons trap this project's own FDR
discipline exists to catch). (2) Engle-Granger test for cointegration on log-price pairs, with an
OOS stability check -- a pair cointegrated in-sample but not OOS is noise, not structure. (3) For
pairs that pass, day-clustered bootstrap CI on whether the residual z-score predicts forward
reversion, same statistical bar as every other thesis here. If zero pairs both cointegrate OOS
and show predictive residual reversion, cointegrated_pairs_residual is dead. (4) **A turnover and cost gate,
pre-registered with the rest rather than added after a promising gross number** -- cross_sectional_relative_value already
killed two sibling features (`ctf_vwap_align`, `ctf_regime_align`) that cleared their CI and
died on turnover and the cost floor, and a mean-reverting spread traded off a z-score band is
structurally a high-turnover construction. The same cost-hurdle sweep cross_sectional_relative_value's Gate 1 uses,
applied to the netted pair spread, at the most conservative tier. **Tighten "economically
related" before screening, or the screen is a correlation scan in disguise:** admit only pairs
with a *structural* linkage -- two funds tracking the same index or overlapping baskets
(`EEM`/`VWO`, `EFA`/`EZU`, `MCHI`/`FXI`, `IEF`/`TLT` on the same curve), or a fund and the
commodity it holds (`GDX`/`GLD`, `OIH`/`XOP`). Two merely-correlated distinct sector ETFs are
not a cointegration candidate; their relationship is a factor exposure, which is
statistical_factor_residual's question, not this one. **Cost:** cheap -- existing daily closes are
sufficient for the cointegration screen; only pairs that pass need the full IC/bootstrap
treatment. **Stochastic-calculus detail (added 2026-08-03):** for pairs that cointegrate, model
the spread as an Ornstein-Uhlenbeck process (`dX_t = θ(μ - X_t)dt + σdW_t`) rather than trading
off an arbitrary lookback window -- the fitted `θ` gives a closed-form mean-reversion half-life
(`ln(2)/θ`), the standard stat-arb sizing/holding-period signal for a cointegrated spread, more
principled than a fixed z-score lookback chosen by hand.

**Statistical Factor Residual (counterparty: index/factor-only investors).** Decompose the
cross-sectional return matrix into its top-K statistical factors (PCA over the correlated
80-ETF universe) and test whether the idiosyncratic residual -- what's left after removing the
common factors -- is more predictable than the raw or simply-demeaned return. The classical
Avellaneda-Lee stat-arb structure: instead of ranking by a feature (cross_sectional_relative_value) or conditioning on a
discrete regime (regime_conditional_persistence), this asks whether orthogonalizing away the shared market/sector factors
first reveals structure invisible in the raw cross-section. **Falsification:** fit PCA (or a
simpler factor model) causally -- no look-ahead in the factor loadings, same discipline as nonlinear_interaction_combiner's
per-symbol demeaning fix -- and test whether `ctf_momentum` (or the nonlinear_interaction_combiner tree score) computed on
the residual return series shows a materially higher IC than on raw returns. If residualizing
doesn't change the IC picture, statistical_factor_residual is dead. **The bar has to be cross_sectional_relative_value, not raw returns
(tightened 2026-08-03), or this thesis can pass trivially.** cross_sectional_relative_value's productionized
dollar-neutral decile construction is *already* a crude one-factor residualization -- going
long the top decile and short the bottom removes most of the common market factor by
construction. Beating raw per-symbol returns therefore proves nothing that Phase 167 has not
already proven. The question statistical_factor_residual actually asks is whether a **K-factor** orthogonalization beats
that existing **one-factor** one, so the comparison must be against
`services/cross_sectional_spread_tracker.py`'s realized spread on the identical OOS rows, same
day-clustered bootstrap, same cost-hurdle sweep. **Risk to flag up front:** with effective breadth
~8-15, a PCA over 80 highly-correlated ETFs may only have 3-5 meaningful factors before hitting
noise -- the K-selection question needs a real answer (parallel to HMM's K=5 BIC study, not a
guess) before this result can be trusted.

**Cross-Asset Lead-Lag (counterparty: participants who don't
cross-reference correlated instruments in real time).** Existing broadcast features (`vix_z`,
`yield_slope_z`, `flight_quality`) encode *contemporaneous* market-level context only. Nothing
tests whether one equity ETF's move at time *t* predicts a **different, specific** ETF's move at
*t+1* -- a genuine pairwise temporal lead-lag relationship (a large, liquid sector ETF leading a
smaller/less liquid one). Every other thesis on this list is contemporaneous (same-bar); cross_asset_lead_lag is
specifically about information propagating across symbols with a lag. **Falsification:**
cross-correlation or Granger-causality screen across symbol pairs at 15m, held to the same
day-clustered bootstrap + BH-FDR bar as everything else here -- critically, tested against
`ctf_momentum` as a covariate, since a lagging symbol's own `ctf_momentum` might already explain
an apparent lead-lag effect. If no pair shows lead-lag power beyond what the lagging symbol's own
existing features already capture, cross_asset_lead_lag is dead. **Cost:** most expensive of the five -- **6,320**
candidate ordered pairs across 80 symbols (80 x 79; the 3,160 figure originally written here was
the *unordered* count, and lead-lag is inherently directional -- A leading B is a different
hypothesis from B leading A) needs a pre-filter (economic relatedness or
liquidity-tier proximity) before FDR correction even applies, to avoid a multiple-comparisons
trap. **Note the overlap with stale_reference_price_adjustment above, and keep them distinct:**
that thesis predicts a *specific* lead-lag (US session -> closed home market) from a named
structural cause with a pre-specified direction and a dose-response control, and should be run
first precisely because it does not need a 6,320-pair screen. cross_asset_lead_lag is the general,
mechanism-free version; if the specific one fails, that is a mark against the general one too.

**Adaptive Combiner Weights (counterparty: participants on stale,
periodically-refit weights).** `ensemble_trainer.py`'s shrunk-IC weights are re-estimated in
discrete batch runs, not continuously. regime_conditional_persistence tested discrete regime-conditional weight switching
and it failed; adaptive_combiner_weights asks whether letting weights drift smoothly and continuously (an
exponentially-weighted rolling IC, or a Kalman filter -- the discrete-time analog of a
continuous-time linear stochastic system, with weights as latent, slowly-varying state)
captures real time-variation a periodic step-function re-fit misses between recompute cycles.
Orthogonal to both regime_conditional_persistence (continuous drift vs. discrete regime switch) and nonlinear_interaction_combiner (adaptive linear
weights vs. static non-linear combination) -- no new grouping or model family, just a different
update dynamic on the existing linear combiner. **Falsification:** build a walk-forward EWMA (or
Kalman-filtered) weight update over the same per-feature IC series `ensemble_trainer.py` already
computes, with a pre-specified halflife (not tuned to the result), and compare OOS IC/Sharpe
against the current periodic-batch weights over the identical held-out window. If it doesn't
clear a real uplift, adaptive_combiner_weights is dead -- feature predictive power is stable enough on the existing
recompute cadence. **"A pre-specified halflife" needs teeth (tightened 2026-08-03):** write down
the exact grid before running (e.g. three halflives spanning an order of magnitude, motivated by
the current recompute cadence rather than by a scan), report **every** cell, and BH-FDR across
the grid. Reporting the best halflife out of an unstated search is the single easiest way to
manufacture an uplift here, and it would be indistinguishable from a real one in the writeup.
**Prioritization caveat:** a positive result has no current consumer. The live construction
(`services/cross_sectional_spread_tracker.py`) ranks by a **single raw feature**,
`ctf_momentum`, not by the ensemble's combined weights, so improving how those weights adapt
changes nothing that trades today. This is a reason to sequence it as a cheap diagnostic of
whether feature predictive power is time-varying at all -- which is genuinely useful -- not as a
step toward a trade. **Cost:** cheapest of the five -- reuses `feature_ic_scores`' existing time
series directly, no new grouping or pairwise screen.

**Jump/Diffusion Decomposition (counterparty: participants who conflate gap risk with
trend risk).** All existing volatility features (`garch_volatility`, `hurst_exponent`) treat
price movement as one undifferentiated process. Realized-variance theory splits it into two
economically distinct components: a continuous diffusion part (steady drift/trend) and a jump
part (discontinuous, news-driven gaps) -- separable via bipower variation vs. total realized
variance (Barndorff-Nielsen/Shephard) or an explicit jump-diffusion fit. **Why we might win:** a
symbol whose recent volatility is jump-dominated (news risk) behaves differently going forward
than one whose volatility is diffusion-dominated (trend continuation) -- if the current single
undifferentiated vol features blend these, they may be averaging away a real distinction, the
same "combiner/grouping is blind to structure that exists" pattern as regime_conditional_persistence/nonlinear_interaction_combiner, applied to feature
*construction* instead of combination. **Falsification:** compute a jump-ratio feature (jump
variation / total variation) per symbol per bar from existing intraday OHLCV, test whether it
adds incremental IC beyond the existing GARCH/Hurst features on the same target -- not whether
it's predictive alone (a new feature that only duplicates existing information isn't evidence of
anything). If it adds nothing beyond what GARCH/Hurst already capture, jump_diffusion_decomposition is dead.
**Two construction constraints to fix before computing anything (added 2026-08-03), because
getting either wrong produces a feature that measures the wrong thing while still looking
plausible:** (1) Bipower variation is a *sub-bar* estimator -- it needs the returns *inside* the
bar being labelled, so a 15m jump ratio must be built from the 1m or 5m bars within that 15m
window, not from a rolling window of 15m bars, and it must read
`market_data_ohlcv_tradeable` so synthetic-fill and flat-carry-forward placeholder bars don't
register as zero-return "diffusion." (2) At daily cadence the single largest discontinuity in
any ETF's price path is the **overnight gap**, which under Invariant 1 sits inside the entry
price and is not tradeable -- so a naive jump measure at 1d would be dominated by exactly the
component the executable-return definition excludes. Compute the jump ratio from intraday
returns only, and treat the overnight gap as a separate, separately-named quantity
(`overnight_gap_z` already exists) rather than folding it into the jump term. **Cost:**
cheap -- pure feature-engineering exercise on data already in `market_data_ohlcv`, no new
grouping, no new data source; closer in shape to a Phase 151 primitive candidate than a new
combiner or construction, but named here since the *specific processing/decomposition
advantage* (separating jump from diffusion risk) is the falsifiable claim, not just "add a
feature."

**Sequencing, cheapest-first:** adaptive_combiner_weights (reuses existing IC time series) -> jump_diffusion_decomposition (feature-engineering
only, existing OHLCV) -> statistical_factor_residual (PCA on existing closes) -> cointegrated_pairs_residual (pairs screen, existing closes,
narrow candidate list) -> cross_asset_lead_lag (most expensive, needs the multiple-comparisons pre-filter done
carefully first). None are urgent -- independent of the in-flight nonlinear_interaction_combiner-at-15m/cross_sectional_relative_value-at-5m work, pick
up whenever that settles.

**Combined sequencing across both groups (added 2026-08-03, after the three new Trade
Constructions).** Cost is not the only ordering criterion -- a Trade Construction that fails
tells you something about the market, while a Signal-Extraction result only tells you about your
own pipeline, so at equal cost the Trade Construction is worth more. Ordering on that basis:
**retail_immediacy_provision's levered-sleeve sharpening** and **dealer_hedging_flow's calendar
screen** first (both cheap, both have a control group already in the universe, both attack
category #3 where this doc is thinnest), then
**stale_reference_price_adjustment** (cheap, but carries an explicitly unfavorable prior),
then the five Signal-Extraction candidates in their own order above, then
**overnight_futures_information_transfer** last -- it is the most valuable claim on the doc and
the only one that is data-blocked, so it belongs in a phase, not a session.

### What is deliberately NOT on this list
"Our features are better" (they are public) and "our ML is better" (we run a linear
IC-weighted combiner; the institutions we'd be beating run more) as *unqualified* claims. Any
future Signal-Extraction Question must name the specific processing advantage -- e.g.,
regime-conditional structure (regime_conditional_persistence, now falsified), the AnalogEngine's non-parametric
retrieval, nonlinear_interaction_combiner's named linear-vs-non-linear gap, or the newest five
candidates' named grouping/association/dynamic/decomposition -- not assert generic model
superiority.

**Also deliberately not on this list: execution and cost improvements (added 2026-08-03).** They
do not belong here -- they name no counterparty and no processing gap, so by this doc's own bar
they are not edge. But the arithmetic deserves recording once, in the place where it is most
likely to be misread. Every gross effect this project has actually measured lives in the
0.27-1.1 bps/bar range (cross_sectional_relative_value's spread, `ctf_vwap_align`'s rejected 0.27, todo 030's 0.26-0.84),
against cost floors of 1-10 bps. At those magnitudes **a 1bp reduction in realized trading cost
is worth more than any plausible IC improvement on this list, and is far more certain to
materialize.** `ctf_vwap_align` was killed by turnover, not by a missing signal;
retail_immediacy_provision was wounded by the cost floor, not by a failed mechanism test. Two
theses out of the ones examined so far died at the cost boundary rather than the signal
boundary. The right conclusion is *not* to add an execution thesis here -- it is that the
execution/sizing layer (Phase 156-159, unstarted) is competing for priority against everything
on this page on better expected-value terms than its "downstream plumbing" framing suggests.
Recorded so the framing is a decision rather than an oversight.

## Breadth Is the Binding Constraint (added 2026-07-01, Simons-lens review)

Whatever thesis survives, the arithmetic above it is fixed: IR ≈ IC × √(effective breadth).
This universe has effective breadth ~8-15 (80 correlated ETFs live as of 2026-08-03; the
completed ETF Universe Expansion barely moved it -- more sector funds are more of the same
bets). At IC ≈ 0.03 and breadth 10, there is almost
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
   table. **This badly
   wounds retail_immediacy_provision (immediacy provision) as a short-horizon thesis** -- if the crumbs institutions
   leave below their minimum ticket can't clear spread either, retail_immediacy_provision only survives at longer
   holds, which changes what "small-scale immediacy" means. **Corrected 2026-08-03: "kills" was
   too strong and is withdrawn.** This is an economic verdict on short-horizon *directional*
   cells, not a run of retail_immediacy_provision's own pre-registered
   liquidity-and-session-boundary concentration criterion, which has never been executed -- see
   the status note in retail_immediacy_provision's section above.
   regime_conditional_persistence/cross_sectional_relative_value/horizon_risk_premium are horizon-agnostic
   and unaffected in direction, though cross_sectional_relative_value (cross-sectional) may specifically rescue some of
   the dead directional cells -- a spread portfolio's cost dynamics differ from a directional
   trade's (see `docs/research/trade-construction-layer.md`).
2. **Every future analysis report tags which thesis its result supports or damages.** A
   qualifying feature is not evidence of edge; it is evidence *for a specific thesis* or it
   is unexplained (and unexplained results get the skeptical prior).
3. **cross_sectional_relative_value requires the PortfolioTrack to be testable at all** -- this is the strongest
   argument for scoping intel-11's PortfolioTrack, stronger than "firms do it."
4. **If, after 142A OOS + cost hurdle, no thesis has supporting evidence** -- the honest
   conclusion is horizon_risk_premium-only: reframe the system as systematic conditional risk-premium
   harvesting at 1h/1d, cut the 5m/15m compute, and stop calling it alpha. That outcome is
   a success of the process, not a failure of the project.
5. **Added 2026-07-25, post-regime_conditional_persistence-falsification.** With retail_immediacy_provision mostly killed by the cost hurdle and
   regime_conditional_persistence now dead, the live decision is no longer "which thesis wins" in the abstract -- it's a
   concrete choice between three cheap-to-test candidates before committing to Phase 164/165's
   multi-week feature-expansion effort: **cross_sectional_relative_value** (cross-sectional relative value -- construction
   change, no new features, `docs/research/trade-construction-layer.md`, now unblocked since
   Phase 142A's OOS gate cleared 2026-07-22) and **nonlinear_interaction_combiner** (non-linear combiner -- modeling change,
   no new features, `docs/research/archive/measurement-nonlinear-interaction-combiner.md`). Both attack
   the *construction/modeling* side of the failure with the existing 150 features; Phase
   164/165 attacks the *feature* side using the same linear/absolute-direction construction
   that regime_conditional_persistence just falsified. cross_sectional_relative_value and nonlinear_interaction_combiner are cheaper to test (reuse existing corpus and
   infrastructure, no multi-week build) and directly target what's actually confirmed broken -- recommend running both before deciding whether 164/165 is warranted at all.
6. **Added 2026-07-26, post-cross_sectional_relative_value-pass.** Both cheap tests from item 5 ran. **cross_sectional_relative_value passed
   decisively** (see cross_sectional_relative_value above) -- this is now the strongest evidence-backed candidate on the
   whole doc, and the recommended next move is scoping `docs/research/trade-construction-layer.md`
   as a real phase (cost-hurdle-adjusted spread construction, then shadow measurement), ahead
   of Phase 164/165. **nonlinear_interaction_combiner came back suspicious**, not confirmed -- a 0.30 mean OOS IC is far
   outside this corpus's observed range and needs the canary-leakage check (see nonlinear_interaction_combiner above)
   before it can support or damage anything. Until that check runs, nonlinear_interaction_combiner is neither evidence
   for nor against committing to Phase 164/165 -- don't cite it either way.
7. **Added 2026-08-03, post-taxonomy-reorg.** Five new Signal-Extraction candidates
   (`cointegrated_pairs_residual`, `statistical_factor_residual`, `cross_asset_lead_lag`,
   `adaptive_combiner_weights`, `jump_diffusion_decomposition`)
   proposed, full design and cheapest-first sequencing above. None are urgent -- they're
   independent of the in-flight nonlinear_interaction_combiner-at-15m/cross_sectional_relative_value-at-5m work and can be picked
   up whenever that settles.
8. **Added 2026-08-03, post-rigor-review.** nonlinear_interaction_combiner-at-5m closes the last tf gap (in progress). The
   real next step is testing cross_sectional_relative_value's construction ranked by nonlinear_interaction_combiner's tree score instead of
   `ctf_momentum` -- both proven independently, combination untested, highest expected value on
   this doc. Pre-registered design (todo 238) written down before running, per this project's
   own discipline of specifying the falsification bar before seeing the number. The five newest
   candidates and todo 235 (cross_sectional_relative_value at 5m under the *current*
   `ctf_momentum` ranking) both wait behind this, since
   the tree-ranked result may change which signal/tf combination is even worth comparing.
9. **Added 2026-08-03, from re-checking each result against the criterion pre-registered for
   it.** Two gaps in nonlinear_interaction_combiner's evidence, both filed, both cheap, and
   [todo 240](../../.planning/todos/pending/240-nonlinear-interaction-combiner-baseline-is-single-feature-not-the-linear-ensemble.md)
   gates todo 238: the tree has never been compared to the linear ensemble its own falsification
   bar names (only to `ctf_momentum` alone), and the walk-forward embargo is applied in
   pooled-panel rows rather than bars
   ([todo 239](../../.planning/todos/pending/239-nonlinear-interaction-combiner-embargo-passed-in-pooled-panel-rows-not-bars.md)).
   Neither overturns the finding; both change how it should be described until they are closed.
   Separately, horizon_risk_premium's falsification criterion was replaced because the original
   could not be contradicted by any outcome, and retail_immediacy_provision's status was
   corrected from "killed" to "wounded on economics, untested on mechanism."
10. **Added 2026-08-03.** Three new Trade Constructions
   (`stale_reference_price_adjustment`, `overnight_futures_information_transfer`,
   `dealer_hedging_flow`) plus a named mechanism for retail_immediacy_provision, targeting the
   two source categories this doc barely attacks (#1 Information, #3 counterparty constraint).
   Combined cheapest-and-most-informative-first ordering is in the Signal-Extraction sequencing
   note above. One structural finding worth surfacing on its own:
   **overnight_futures_information_transfer is data-blocked, not work-blocked** -- the 18
   futures and 4 FX contracts in `instruments` are all inactive with zero rows in
   `market_data_ohlcv`, so any non-equity claim in this project is currently unfalsifiable for
   want of data rather than unproven.

## References

- `docs/intelligence/intelligence-alphaengine.md` -- the epistemology this doc completes:
  "the data discovers confluence" answers HOW to find edge; this doc asks WHY edge should
  exist at all
- `docs/research/measurement-ic-engine.md` -- Cross-Sectional Rank IC addendum (cross_sectional_relative_value's test
  vehicle; retired from `intel-11`, see `docs/research/archive/intel-11-dual-system-discrete-vs-portfolio.md`)
- Todo 030 (cost-hurdle APR calibration) -- the first falsification pass against realistic cost
  floors; closed and removed from `.planning/todos/`, its result summarized in this doc above
- `docs/plans/archive/2026-06-29-feature-scoring-beyond-ic.md` -- marginal contribution / shrinkage
  (the machinery that keeps thesis evidence honest)
- `.planning/todos/completed/179-gate166-concurrent-exposure-diagnostic.md` -- regime_conditional_persistence's falsification
  evidence, full 234-cell sweep and historical replication check
- `docs/research/trade-construction-layer.md` -- cross_sectional_relative_value's construction and validation design
- `docs/research/archive/measurement-nonlinear-interaction-combiner.md` -- nonlinear_interaction_combiner's original design
  proposal and overfitting controls (2026-07-25, archived 2026-08-03, fully absorbed above)
- `services/cross_sectional_spread_tracker.py` -- cross_sectional_relative_value productionized (Phase 167); `_TF = "15m"` at
  line 105 is the inherited default todo 235 questions
- `scripts/analysis/nonlinear_interaction_combiner_lightgbm_check.py` -- nonlinear_interaction_combiner's falsification script and
  2026-07-26 preliminary (pending canary check) result
- `scripts/analysis/_nonlinear_interaction_combiner_shared.py` -- shared orchestration for all four
  nonlinear_interaction_combiner tf runs; `baseline_feature` (line 516) and the `n_valid=len(X)` fold call are the
  subjects of todos 240 and 239
- `scripts/analysis/nonlinear_interaction_combiner_replication_15m.py` / `_1d.py` / `_5m.py` -- the
  per-tf replication entry points; only tf-calibrated constants differ between them
- **Deleted scripts, cited above as evidence, recoverable only from git history** (all removed
  2026-07-28 in `8a9bdf32`, "remove 19 stale one-off analysis scripts" -- verified 2026-08-03,
  these paths do not resolve in a working tree):
  `scripts/analysis/t3_cross_sectional_long_short_ctf_momentum_check.py` (cross_sectional_relative_value's falsification
  script and 2026-07-26 pass result), `scripts/analysis/t3_ctf_family_check.py` (the CTF-sibling
  rejections), `scripts/analysis/t5_canary_leakage_check.py` (todo 184's canary check)
- [Todo 239](../../.planning/todos/pending/239-nonlinear-interaction-combiner-embargo-passed-in-pooled-panel-rows-not-bars.md)
  and [todo 240](../../.planning/todos/pending/240-nonlinear-interaction-combiner-baseline-is-single-feature-not-the-linear-ensemble.md)
  -- nonlinear_interaction_combiner's two open pre-registration gaps
- [Todo 235](../../.planning/todos/pending/235-cross-sectional-relative-value-5m-construction-never-tested-15m-is-a-default-not-a-finding.md)
  -- cross_sectional_relative_value at 5m under the current `ctf_momentum` ranking
- `docs/ideas/signal-convolutional-raw-window-representation.md` -- the rejected CNN paper
  critique behind the path-shape input-feature note in nonlinear_interaction_combiner's section
