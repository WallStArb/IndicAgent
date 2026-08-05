# IndicAgent V3.0 — AlphaEngine: Statistical Alpha Discovery Architecture (Architecture Generation 2)

> **Status (as of 2026-08-05): active development, measurement/discovery phase. No construction
> in this project has a currently-confirmed, live proof of edge.** This doc describes the
> architecture and how each layer is being approached — not a finished, validated system. Where
> a claim below is "designed" vs. "built" vs. "measured," it says so explicitly. For the prior
> generation this replaced — a fully-built, real-time event-driven pipeline, dormant since this
> rebuild began 2026-06-20 — see
> [`architecture-v2-event-driven-pipeline.md`](architecture-v2-event-driven-pipeline.md).

## Why V3.0 Exists

V2's intelligence pipeline had a structural flaw no amount of tuning could fix: researchers encoded hypotheses about what constitutes edge directly into the pipeline — named chart patterns, confluence rules, signal-firing conditions. 138 plugins produced roughly 15 genuinely independent views, because a human had already decided what "confluence" meant before any data was measured. The system could only discover edges the researcher already believed in, and its own training data was selection-biased — outcomes were only recorded for bars the researcher's filter let through.

That's confirmation bias with extra steps. V3.0's fix isn't better plugins — it's a different epistemology:

> The researcher proposes feature dimensions. The data validates or rejects each. No human defines which combinations matter — the IC engine measures what predicts, and the ensemble discovers what combinations work.

Every architectural decision in V3.0 is evaluated against one question: **who decides what matters here?** If the answer is "the researcher," that's a design smell to be reconceived. The answer has to be "the data, measured."

This document walks the pipeline layer by layer — what each one is, where it sits in the stack, why it exists, how it's currently approached, and where more than one approach has genuinely been tried.

---

## The Shape of the Pipeline

```
Raw OHLCV                    market_data_ohlcv (TimescaleDB) — IBKR historical backfill,
                              currently corpus-driven (batch), not real-time streaming
      │
      ▼
Feature Factory               compute_features() — atomic, orthogonal primitives
                              → feature_vectors (259 columns as of 2026-08-04, 11 groups)
      │
      ▼
Regime Layer (HMM)             two systems, answering different questions:
                              per-symbol idiosyncratic regime (regime_writer)
                              cross-sectional systematic regime (cross_sectional_regime_model)
      │
      ▼
IC Measurement                 ic_engine — per feature × symbol × TF × regime × lookahead,
                              first at single-symbol grain, then pooled/cross-sectional
      │
      ▼
Combination / Ensemble         ic_shrinkage → ensemble_trainer → ensemble_alpha
                              (linear IC-weighted, live; nonlinear tree-based, tested,
                              open question — see below)
      │
      ▼
Trade Construction             turns a scored edge into a tradeable position —
                              per-symbol directional (tested, failed) vs.
                              cross-sectional relative value (tested, pending re-verification)
      │
      ▼
Governance                     Concept Registry, APR, shadow/promotion gates —
                              decides what's allowed to reach the next stage
```

Nothing here is a straight line drawn once and never revisited. Nearly every stage below has at least one place where a second approach was tried, measured, and kept as a live alternative rather than discarded — that's deliberate, and covered stage by stage.

---

## Layer 0: Data Foundation

**What it is:** raw OHLCV bars in `market_data_ohlcv`, sourced from IBKR's historical data API.

**Where it sits:** the base of the stack. Nothing above computes anything without this being correct first.

**Why it's there:** every downstream number — a feature value, an IC estimate, a backtested return — is only as trustworthy as the bars it was computed from. Data integrity here has no IC, no statistical gate, no Concept Registry row; its correctness bar is simpler and stricter: no gaps, no duplicate writes, no silent drops, no synthetic fill masquerading as a real trade.

**How it's approached today:** this is corpus-driven, not real-time. V2's real-time ingestion chain (`indicagent-ibkr-provider`, sub-10ms bar-to-signal) is intentionally stopped — deliberate, not an outage; see [`architecture-v2-event-driven-pipeline.md`](architecture-v2-event-driven-pipeline.md)'s status banner for why it may run again as a second path once edge is proven. Live data isn't required to find edge; historical depth is what IC measurement actually needs, and IBKR's historical API (`reqHistoricalDataAsync`, paced by IBKR's own rate limits rather than the live-subscription cap) supplies it. Backfill runs via `scripts/infrastructure/backfill/infrastructure_run_historical_pipeline.py`, targeting 20-year depth on 1d/1h/15m/5m and 90-day depth on 1m (enough to capture time-of-day/day-of-week structure without the storage cost of 20 years of 1m bars).

`market_data_ohlcv_tradeable` (a view filtering `volume > 0`) is the read path for any compute or measurement — the raw table is a continuous calendar grid that includes synthetic-fill and provider flat-carry-forward placeholder bars for roughly 82% of intraday rows. Reading the raw table for anything except a documented exception is treated as a data-integrity bug, enforced by a CI allow-list test.

**Universe:** started at 58 ETFs (Phase A scope), expanded to 80 via the 2026-06-27 ETF universe expansion, then to 111 as of 2026-08-05 with the addition of single-name blue-chip equities (AAPL, JPM, CAT, XOM, BHP, and others) spanning sectors the ETF-only universe under-covered — energy, mining, industrials. The long-term direction is a maximal tradeable universe, scaled as compute allows, not a fixed ceiling.

---

## Layer 1: Feature Factory — Atomic Feature Vectors

**What it is:** a library of pure, typed functions (`compute_features()`) that each compute one measured quantity from price, volume, and structure — no directional opinion, no firing condition, no "this means buy." A `FeatureVector` is a flat, wide row of these measurements for one symbol, one timeframe, one bar.

**Where it sits:** directly above raw data, below regime and IC. It's the sole source of what gets measured — nothing enters the IC engine that didn't come through here first.

**Why it's there:** this is the "researcher proposes feature dimensions" half of the North Star. A feature is a hypothesis, not a fact — "this quantity might carry information about future returns" — and the Feature Factory's only job is to compute the hypothesis cleanly and unconditionally, on every bar, regardless of whether anything downstream ever finds it useful. Whether it *actually* carries information is answered two layers down, by IC, not by the researcher writing the function.

**Why atomic and orthogonal, not composite:** Renaissance's documented experience is that simple features with modest, stable, real IC beat complex features with impressive in-sample IC, because complexity is exactly where overfitting hides. A researcher who builds a feature that "should" predict based on market-structure intuition has smuggled a hypothesis about *combinations* back into a layer that's only supposed to measure *dimensions*. So each primitive is built to have (1) a documented statistical rationale independent of this corpus — short-term momentum exploiting behavioral under-reaction, range position as a mean-reversion predictor, volume deviation as an attention proxy — and (2) as close to zero mutual correlation with the others as the underlying phenomenon allows. None of these primitives is individually tradeable. The combination is where any edge would have to live, and that combination step is IC's job, not the Feature Factory's.

**Current state:** 259 live features across 11 groups (structure 64, session 62, volume 31, volatility 31, calendar 27, momentum 17, regime 10, oscillator 6, control 5, cross_tf 3, macro 3). The `control` group is deliberately not signal — five canary columns (`canary_constant`, `canary_noise_gaussian`, `canary_acausal_placebo`, etc.) exist purely to catch measurement bugs: if a canary that's supposed to be structurally uninformative shows real IC, something upstream leaked information, not discovered it.

**How it's built:** `compute_features()` is O(1) per bar — incremental, not batch, so it can eventually run in a real-time daemon the same way it runs in backfill today. Every field is `float | None`, never a fake numeric default standing in for "not computed yet" — a `None` has to mean something different from a `0.0`, or degenerate-feature detection downstream (`std(X) < 1e-8`) can't tell a genuinely flat series from a column that silently never got populated.

---

## Layer 2: Regime Layer — Two HMM Systems, Not One

**What it is:** Hidden Markov Model regime classification, answering "what state is the market in right now?" — but answered twice, at two different scopes, because the question means something different at each.

**Where it sits:** parallel to Feature Factory output, feeding into IC measurement as a stratification variable — not a gate.

### Why regime conditioning, not regime gating

This distinction is load-bearing enough to state plainly: **gating discards data, conditioning keeps all of it.** A feature might have IC = 0.04 in a trending regime and IC = -0.01 in a ranging one. Gating would mean "only trade this feature when trending" — which throws away every ranging-regime observation and never lets you learn what actually happens to the feature there. Conditioning means every IC estimate is computed *per regime state*, so the ranging-regime behavior is measured, not discarded, and the ensemble applies regime-appropriate weights at inference time rather than a blanket on/off switch.

### Two systems, two questions

**Idiosyncratic (per-symbol) regime** — `regime_writer.py` fits one Gaussian HMM per `(symbol, timeframe)` pair, independently, on log-returns and an ATR-based realized-volatility proxy. This answers "what state is *this specific instrument* in?" — AAPL trending while TLT ranges is a completely coherent, expected outcome, because each gets its own model. K=5 states (`trending_up`, `transition_up`, `ranging`, `transition_down`, `trending_down`), chosen via a BIC study over K=2 through K=5 rather than picked by convention.

**Systematic (cross-sectional) regime** — `cross_sectional_regime_model.py` answers a different question: "what's the *market-wide* backdrop right now?" — driven by VIX and breadth-style signals across a peer group, not any single symbol's own price history. A symbol can be in its own idiosyncratic uptrend while the systematic regime reads risk-off; both facts are true at once and both are kept, not collapsed into one number.

**Why two, not one:** conflating them would mean a broad market selloff and an idiosyncratic single-name breakdown look identical to the ensemble, when they're different phenomena with (presumably) different forward-return implications. Keeping them separate lets IC be measured against each independently and lets the ensemble learn whether either one — or their interaction — actually carries information, rather than assuming the answer in advance.

### The causal-correctness discipline

The single most consequential correctness rule in this layer: **regime decoding must be causal.** `regime_writer` uses forward-filter (alpha-pass) HMM decoding only — `model.predict()` (full-sequence Viterbi) is never used for the live labels, because Viterbi decodes the *whole* sequence at once, meaning the regime label assigned to bar T can be informed by bars *after* T. That's look-ahead bias, and it's exactly the mistake V2's `intelligence_features` table made — its regime labels used Viterbi decoding, which is a documented reason that entire table is not reused in V3.0. The schema enforces this structurally: `feature_vectors.regime_label_source` only accepts `{'filtered', 'unknown'}` — there is no code path that can write a Viterbi-derived label into a column the IC engine will read.

**A design question still open here, not yet settled by measurement:** the per-symbol HMM currently fits its emission/transition parameters on the full training-window history before decoding causally forward. That's a *parameter*-level lookahead — subtler than the label-level Viterbi mistake above, but real: the model "knows" its own future-fitted statistics while decoding early bars. A walk-forward variant (refit periodically on the training-slice prefix only, never the full series) was built and unit-tested specifically to close this gap — but when measured on live SPY/1h data, it did not show a clear improvement in downstream prediction quality (Gate 4 measurement FAILED). The instability the fix targets is real; whether fixing it actually helps wasn't confirmed. It's parked, not wired into production, and not being re-litigated without new evidence — a concrete example of this project's standing rule that a plausible-sounding fix still has to clear a real measurement, not just sound right.

---

## Layer 3: IC Measurement — Single Symbol First, Then Cross-Sectional

**What it is:** the empirical arbiter. For every feature, at every timeframe, in every regime state, at every forward-return lookahead horizon, the IC engine computes the Spearman rank correlation between the feature's value at bar T and the realized return from T to T+N.

**Where it sits:** directly downstream of Feature Factory + Regime Layer. This is the layer that actually decides whether a proposed feature dimension means anything — nothing upstream of this makes that call, and very little downstream re-opens it.

**Why it's there:** this is the whole point of the "data validates or rejects each" half of the North Star. IC = 0.03 is weakly meaningful; IC = 0.05 is meaningful; IC = 0.10 is exceptional at daily resolution. No feature earns influence in the ensemble by looking sensible to a researcher — it earns influence by clearing a statistical bar, measured the same way for every feature, without exception.

### The grain progression: symbol → cross-section

IC is measured first **per individual symbol** — AAPL's `momentum_z_fast` gets its own IC estimate, separate from JPM's. This matters because a feature's predictive power can genuinely differ by instrument (a momentum feature might behave differently on a high-beta single name than on a broad ETF), and averaging that away before measuring it would hide real structure.

Then IC is measured again **pooled across the cross-section** — the same feature's IC computed jointly across the peer universe (`is_pooled=true`, `regime='_pooled'` sentinel rows). Pooled cross-sectional IC is a first-class ensemble-training-eligibility source in this system, not a fallback for symbols with too little individual history — pooling adds statistical power by increasing the effective sample and is treated as a legitimate, separate measurement, sitting alongside single-symbol IC rather than replacing it.

**Executable returns, not theoretical:** forward returns use `ln(open[T+N+1] / open[T+1])` — market-on-open entry, market-on-open exit — never `ln(close[T+N] / close[T])`. Close-to-close returns capture overnight gaps that can't actually be traded and systematically overstate IC, especially at short horizons. Every IC query filters `forward_returns.return_type = 'executable_open_to_open'`; there is no code path to a theoretical-return IC number in the live measurement.

### What guards against false positives here

A few mechanisms compound to keep IC honest rather than just impressive-looking:

- **Circular block bootstrap confidence intervals**, not an asymptotic (Fisher-z) approximation — an empirical-null calibration check found the asymptotic assumption's standard-error estimate was measurably miscalibrated on this corpus's real autocorrelation structure (38% of evaluated strata flagged SUSPECT), so the bootstrap replaced it.
- **60-bar purge/embargo** between walk-forward training-fold end and test-fold start, sized to the longest forward-return lookahead (60 bars), preventing overlapping return labels from leaking across the fold boundary.
- **Benjamini-Hochberg FDR correction** across the multiple-testing problem inherent in scoring 259 features simultaneously — without it, some fraction of features would clear a naive p<0.05 bar by chance alone, not because they carry real information.
- **IC Sharpe (mean IC / IC standard deviation over rolling windows)**, not raw IC, as the primary ensemble weight — this penalizes a feature that's high on average but unstable, which is exactly the shape overfitting tends to produce.
- **Degenerate-feature skipping** (`std(feature) < 1e-8`) before rank correlation is even computed, so a column that's silently constant in some window doesn't produce a spurious rank correlation.

---

## Layer 4: Combination — Two Approaches Genuinely Tried

**What it is:** turning many individually-weak, individually-measured feature scores into one combined estimate of expected return per bar (`ensemble_alpha`).

**Where it sits:** directly downstream of IC measurement, upstream of trade construction.

**Why it's there:** no single feature in this corpus is even close to independently tradeable — the edge, if it exists, has to come from combining many small, IC-Sharpe-weighted, decorrelated views. This is the layer where "many small independent ICs beat one hand-crafted theory" either proves out or doesn't.

### Approach 1 — linear IC-weighted ensemble (live)

`ensemble_trainer.py` combines features into `ensemble_alpha` via a shrunk-IC-weighted linear sum: each feature's weight is a function of that feature's own marginal IC, computed independently of every other feature, with a per-feature exposure cap (20%) so no single feature can dominate the combined score. This is the production path today — `EnsembleICEngine` separately validates that the *combined* ensemble output itself has real IC (not just that its inputs did), writing to `alpha_ensemble_ic`.

**What a linear combiner structurally cannot express:** "feature X predicts returns, but only when feature Y is above its 70th percentile." Any conditional or interaction structure across features is invisible to a linear combiner by construction — not an oversight, a property of the model class. Regime is the one interaction axis the system explicitly does model (every IC estimate is regime-stratified, as described above) — the open question was whether there's real interaction structure *beyond* regime that a linear model is leaving on the table.

### Approach 2 — nonlinear tree-based interaction combiner (tested, result complicated)

A gradient-boosted tree combiner was built and measured specifically to test that question, since trees can express interaction structure a linear sum cannot. The initial result looked substantial — until it was checked properly. A batch-join bug (`ctf_momentum`'s HTF-alignment join using the wrong bar) had leaked forward-looking information into one of the input features, and the tree — because it has no per-feature exposure cap, unlike the linear ensemble's 20% cap — rode that single leaked feature far harder than the linear model would have. Once the join was fixed and remeasured, the "substantial" headline uplift collapsed 43.8%-90.6% depending on timeframe (worse collapse at coarser timeframes — 1h worst at 90.6%, 5m least at 43.8% — because the leak's roughly fixed absolute magnitude is a proportionally larger share of the tree's total predictive power at coarser resolution, where real edge is smaller to begin with). A small, genuinely real residual survives at every timeframe tested — this was not a total null — but it's roughly an order of magnitude smaller than first reported, and the incident surfaced a real structural question that's still open: **is an unconstrained gradient-boosted tree the right model for interaction discovery on a corpus this size at all, or does the lack of a per-feature cap mean it will keep concentrating on whatever the single noisiest or most leak-prone feature is?** A regime-conditional linear approach — keeping the 20%-cap discipline but allowing weights to vary by regime, a middle ground between "pure linear" and "unconstrained tree" — is the next design under consideration, not yet built.

**Why this is left in as a live example rather than cleaned up into a single "here's how it works" paragraph:** this is exactly the kind of result this project's principles ask to be surfaced honestly rather than smoothed over — an approach that looked good, turned out to be mostly an artifact of a data bug once checked, and still left behind a real, smaller, worth-pursuing signal plus a genuine open design question. That's a more accurate picture of where this layer actually stands than declaring either approach a clean winner.

---

## Layer 5: Trade Construction — Two Approaches, One Failed, One Pending

**What it is:** turning a scored edge (`ensemble_alpha`, or in the tested cases below, a single feature directly) into an actual position — what to be long, what to be short, how much, and against what benchmark.

**Where it sits:** downstream of a validated edge signal. Nothing here should be attempted before IC is measured and positive — the roadmap's explicit rule is that trade construction and portfolio sizing never get ahead of a proven predictive signal.

**Why it's there:** a positive IC on a feature doesn't automatically imply a profitable trade — cost hurdles, position sizing, correlation across simultaneous positions, and what exactly gets bought or sold against what benchmark are separate design decisions, each of which can destroy an edge that looked real at the measurement stage.

### Approach 1 — per-symbol directional (tested, failed)

The most direct construction: does the ensemble's alpha score, applied to a single symbol, predict that symbol's own forward return well enough to trade it directionally? This passed the signal-proof gate (Gate 1) but failed the execution-proof gate (Gate 2) — meaning the underlying predictive signal was real by the Gate 1 measure, but building an actual executable trade around it, once realistic costs and execution constraints entered the picture, didn't hold up. Verdict: do not promote to live capital. This is a settled result, not still open.

### Approach 2 — cross-sectional relative value (tested, verdict currently under re-verification)

A different construction, working at the asset-class/cross-sectional level rather than per-symbol: rank all symbols in the universe by a feature value on a given bar, go long the top decile, short the bottom decile, dollar-neutral, flat equal-weight legs (not vol-scaled — that's a separate, not-yet-tested enhancement). The idea is to isolate the *cross-sectional* information in a feature — which symbols look best/worst *relative to their peers right now* — independent of whatever the whole universe is doing directionally, which a per-symbol directional bet doesn't isolate.

This passed both validation gates when first measured (2026-07-27) — the first construction in this project to clear both. But the sole ranking feature it uses, `ctf_momentum`, is the same feature identified above as carrying the batch-join lookahead leak. That means this construction's "both gates passed" result is not currently trustworthy as stated — it needs to be re-measured against the corrected feature before the verdict can be treated as settled. The fix is coded; the corpus recompute and gate re-run are scoped and ready, gated on deliberate go-ahead rather than run reflexively, because a run-once statistical gate like this deserves one clean look under corrected data, not a rushed one.

**Why both approaches are described here rather than just the currently-favored one:** per-symbol and cross-sectional are answering genuinely different questions about where edge might live — "is this symbol going up" versus "is this symbol going to outperform its peers" — and the fact that the first failed and the second is pending, rather than the second having obviously been the right idea from the start, is itself informative about how this kind of research actually proceeds.

### Asset-class-level construction — where this is headed

Both approaches above operate within a single asset class (currently all-equity, since the universe is ETFs and single-name equities). A natural next question this raises but hasn't yet been tested empirically: does the same cross-sectional relative-value logic hold *across* asset classes — ranking, say, an equity ETF against a rates ETF against an FX pair on some common ground rather than only within an equity peer group? That's a real extension of the same construction concept, not yet attempted, and any measurement of it would go through exactly the same IC-then-gate discipline as everything above it.

---

## Governance: Concept Registry, APR, and Shadow Gates

**What it is:** the system that decides what's allowed to be "live" at any given moment, why, and with what evidence — spanning features, regime model variants, ensemble strategies, and (eventually) trade constructions under one shared discipline.

**Where it sits:** orthogonal to the pipeline above rather than a stage within it — it governs promotion/demotion decisions at multiple points in the stack (which features enter the ensemble, which ensemble weighting recipe is active, which HMM variant is in use), not just at the end.

**Why it's there:** the same discipline V2 relied on (APR for every tunable parameter, Shadow Governance for promotion) needed a version that spans more than parameters — feature lifecycle, ensemble strategy versioning, and eventually regime-model variants, all under one auditable promote/demote/decay history rather than each tier reinventing its own governance table. The Renaissance framing this is built on: ten years from now, "why don't we use this feature/strategy anymore" should have an answer in a database row — demotion date, held-out statistic, sample size — not in someone's memory or a deleted Slack thread.

**Current state:** the `ensemble_strategy` domain is live — `ConceptRegistryService` is wired as the status-flipper for ensemble weighting-recipe comparisons. The `feature` domain (migrating `feature_registry`'s 259 rows into this same unified system) is in progress as of this writing — a separate concurrent work session is executing that migration now. Two more domains (`hmm_variant`, `regime_model`) are fully specified but not yet built, waiting on real candidates to govern rather than being built speculatively ahead of need.

**Adaptive Parameter Registry (APR)** carries forward unchanged in spirit from V2: every tunable threshold, weight, period, and count lives as a versioned database row with a documented provenance (`[initial_estimate]`, `[conventional]`, `[rca_analysis]`, `[user_preference]`), not a hardcoded constant. A hardcoded numeric threshold anywhere in `src/` or `services/` is treated as an architecture violation, not a style nit.

---

## Multiple Data Input Vectors — Quant Is the First, Not the Only

Everything described above operates on one kind of input: price and volume, read from OHLCV bars. That's deliberate and sequential, not a permanent scope limit. The system is designed around a broader concept — **intelligence vectors** — where each vector is an orthogonal source of scored, measured prediction, and price/volume is simply the first one being built because it's the cheapest to get right and the one every other vector's infrastructure (IC engine, ensemble, governance) has to work correctly before it's worth spending money on the next.

| Vector | Domain | Reads | Cadence | Status |
|--------|--------|-------|---------|--------|
| **V1 Quant** | Price/volume | OHLCV-derived features (everything above) | Per bar | **Being built now — this doc** |
| **V2 Microstructure** | Order flow | Bar-level proxies today (close position in bar, body/wick ratio, volume deviation); true tick-level order flow later | Per bar | Bar-level proxies exist as V1 features; genuine tick upgrade (`reqTickByTickData`) deferred until proxy IC is measured |
| **V3 Macro** | Cross-asset | VIX, yield curve, sector rotation | Per bar / daily | Partially built — some macro features exist in the Feature Factory today |
| **V4 Calendar** | Time structure | Expiry cycles, rebalance windows, day-of-week/month-end effects | Daily | Built — zero new data required, pure timestamp arithmetic |
| **V5 Flow/Positioning** | Institutional flow | COT positioning, dark pool prints, short interest | Weekly/daily/intraday | Designed, not built — data sourcing (CFTC public, paid exchange feeds) not yet in place |
| **V6 Derivatives/Gamma** | Options market | GEX, vanna/charm, vol surface, VRP | Intraday | Designed, not built — needs an options data feed |
| **V7 Qualitative** | Sentiment/narrative | News flow, analyst tone, social/positioning chatter | Event-driven | Designed, not built |
| **V8 Fundamental** | Financials | Earnings, macro releases, analyst revisions | Quarterly/scheduled | Designed, not built |

**Why this order:** V1-V4 are buildable entirely from data already flowing through the pipeline — no new vendor, no new cost, no new infrastructure. V5-V8 each require new paid or semi-structured data sources, and the discipline this project applies uniformly is that a vector doesn't earn a data-cost commitment until the cheaper vectors already in hand have demonstrated the IC-measurement infrastructure actually works — proving the substrate on free data before paying for more of it.

**Why orthogonality matters here specifically:** V1 responds to price patterns, V2 to who's trading, V3 to cross-asset flow, V4 to time structure, V5 to institutional positioning, V6 to what options markets are pricing in, V7 to narrative, V8 to fundamentals. These read genuinely different phenomena through different instruments at different frequencies — combining orthogonal vectors compounds edge; adding a *correlated* predictor (a fifth momentum variant that behaves like the four already in the ensemble) doesn't add anything the effective-N adjustment wouldn't already discount. The same IC-measurement gate applies uniformly regardless of which vector a feature comes from: a vector's contribution doesn't enter the live ensemble until it clears `bootstrap_CI_lower(IC) > 0` at sufficient N, exactly like every V1 feature above had to.

---

## Honest Current Status

Worth stating plainly, in the same place as everything above rather than only in an internal planning doc: **no construction in this project currently has a confirmed, live proof of edge.**

- The per-symbol directional construction (Layer 5, Approach 1) was tested and failed its execution-proof gate. Settled.
- The cross-sectional relative-value construction (Layer 5, Approach 2) passed both gates once, but that result rests on a feature since found to carry a lookahead leak — not yet re-verified under the corrected data. Pending, not confirmed.
- The nonlinear interaction combiner (Layer 4, Approach 2) had its headline result mostly explained by the same leak; a small real residual survives, smaller than first published, with an open design question about whether the model class fits this corpus at all.
- Everything upstream of trade construction — the Feature Factory, the dual regime system, the IC engine's measurement discipline — is comparatively mature and not itself in question; what's unresolved is specifically whether the *combination and construction* layers built on top of it produce something tradeable.

The single question gating everything downstream right now: does the cross-sectional construction survive a clean re-measurement under the corrected feature? Both outcomes have a defined next step. A pass unblocks cost-hurdle-adjusted construction refinement and execution/sizing infrastructure. A fail returns priority to discovery — several untested signal-extraction candidates (cointegrated pairs residuals, statistical factor residuals, cross-asset lead-lag, adaptive combiner weights, jump-diffusion decomposition) and the nonlinear combiner's next design iteration. Either branch converges on the same standing principle this project runs on: prove edge before production infrastructure, never the reverse.

---

## What Carries Forward from V2, and What Doesn't

| V2 mechanism | V3.0 status |
|---|---|
| Adaptive Parameter Registry (every tunable value versioned, provenanced) | Carries forward unchanged in spirit |
| Content-addressed keys, idempotent reprocessing | Extended — SHA-256 keys on every new table, keyed to natural identity |
| OTel observability (crash/DLQ/heartbeat/watchdog signals) | Carries forward unchanged — every `BaseDaemon` subclass inherits it |
| Signal Ledger (`signal_events`/`trade_frames`/`trade_executions`) | Superseded — `alpha_events` replaces `signal_events`; no researcher-defined "signal fired" concept survives |
| I5/I6/I7 (patterns, confluence, signal plugins) | Fully archived, no transitional shim — replaced by threshold-crossing on the IC-weighted `alpha_score` |
| CIS bucket weighting (hand-assigned bucket weights) | Superseded — IC Sharpe replaces researcher-assigned weights entirely |
| Shadow Governance (n≥100, bootstrap CI gate) | Carries forward as the model for feature/ensemble/construction promotion gates |
| Vector Intelligence Layer (pgvector analog retrieval) | Designed in V2, not built in either generation — remains a future layer, domain-agnostic to whichever generation eventually builds it |
| Evolvable AI (eAI genome/backtest/evolve loop) | Designed in V2, not built in either generation — the concept is generation-agnostic and would apply to V3.0 feature/construction candidates the same way it was designed for V2 signal plugins |
| Real-time event-driven ingestion (sub-10ms bar-to-signal) | Not currently in use — V3.0 is corpus/batch-driven during this measurement phase; the real-time chain is V2's, dormant, and may run again as a parallel path once edge is proven |

---

## See Also

- **Prior generation, full detail:** [`architecture-v2-event-driven-pipeline.md`](architecture-v2-event-driven-pipeline.md)
- **AlphaEngine concept + vocabulary (canonical):** [`docs/intelligence/intelligence-alphaengine.md`](../intelligence/intelligence-alphaengine.md)
- **IC/ensemble methodology (canonical, current):** [`docs/intelligence/intelligence-alphaengine-methodology.md`](../intelligence/intelligence-alphaengine-methodology.md)
- **North Star / intelligence vectors (V1-V8) full spec:** [`docs/foundation/v3-north-star.md`](../foundation/v3-north-star.md)
- **Candidate edge theses catalog (trade constructions + signal-extraction candidates, each falsifiable):** [`docs/research/data-edge-source-thesis.md`](../research/data-edge-source-thesis.md)
- **Nonlinear interaction combiner — full incident + design question:** [`docs/research/measurement-nonlinear-interaction-combiner.md`](../research/measurement-nonlinear-interaction-combiner.md)
- **Concept Registry — governance system design:** [`docs/research/concept-unified-registry.md`](../research/concept-unified-registry.md)
- **Adaptive Parameter Registry:** [`docs/foundation/adaptive-parameter-registry.md`](../foundation/adaptive-parameter-registry.md)
- **Live current position / what's blocked on what:** [`.planning/STATE.md`](../../.planning/STATE.md)
- **Root overview:** [`README.md`](../../README.md)

### AI Assistant

- [CLAUDE.md](../../CLAUDE.md) — architecture, commands, conventions, gotchas
