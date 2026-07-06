# v3.0 North Star — Intelligence Vectors Concept

**Version:** 1.1
**Status:** Canonical — foundational v3.0 philosophy
**Last Updated:** 2026-06-20
**Tags:** intelligence-vectors, alphaengine, analogengine, ic, signal-layer, v3.0, renaissance

**Location:** Moved to `docs/foundation/` as canonical v3.0 origin document (2026-07-06). This establishes the Renaissance-grade principle that governs all v3.0 architectural decisions.

---

## North Star

> **The researcher proposes feature dimensions. The data validates or rejects each. No human defines which combinations matter — ensemble IC discovers confluence. Stability matters as much as magnitude. If IC decays, weight decays with it. Walk-forward validation is the only gate. In-sample IC is noise.**

This is the design principle that governs every architectural decision in this refactor. When a design choice requires a human to define what feature combinations are predictive — which patterns "confirm" a setup, which conditions make a signal "higher conviction," what confluence looks like — it violates this principle and must be rejected or reconceived.

Every tier, every component, every schema decision should be evaluated against this statement. If the answer to "who decides what matters here?" is "the researcher," that is a red flag. The answer must always be "the IC engine, on the data."

### What Changed and Why

The refined North Star adds three Renaissance-grade dimensions that the original statement lacked:

| Addition | Renaissance Principle | Why It Matters |
|----------|----------------------|----------------|
| *"Proposes feature dimensions"* | Features are hypotheses, not facts | IC decides validity, not the researcher |
| *"Stability matters as much as magnitude"* | IC Sharpe > raw IC | Volatile IC is intermittent luck, not edge |
| *"If IC decays, weight decays with it"* | Automated governance, no human gates | Manual response is too slow; hysteresis prevents oscillation |
| *"Walk-forward validation is the only gate"* | Primary guard, not FDR | In-sample IC is not evidence — it's data mining |

---

## Renaissance Invariants

These are the non-negotiable methodological constraints. Violating any of them produces IC measurements that are either wrong, biased, or meaningless. No exceptions.

### Invariant 1: Executable Returns, Not Theoretical

**Rule:** Forward returns MUST use executable entry/exit prices.

```
R(T, N) = ln(open[T+N+1] / open[T+1])  -- CORRECT
R(T, N) = ln(close[T+N] / close[T])    -- WRONG
```

**Why:** Close[T] is the observation price, not the executable entry. Theoretical returns capture overnight gaps and opening moves that cannot be traded. IC measured this way is overstated, especially for short-horizon predictors.

**Enforcement:** `forward_returns` schema constrains `return_type = 'executable_open_to_open'`. Any row with a different return type is excluded from IC computation.

**Status:** ✅ Specified in `docs/plans/2026-06-20-alphaengine-ic-spec.md` §V.1
**Implementation:** ⚠️ NOT YET IMPLEMENTED — currently using theoretical returns

---

### Invariant 2: Walk-Forward Before Live

**Rule:** No feature enters the live ensemble without passing walk-forward validation on held-out data.

**Why:** In-sample IC is meaningless. A feature with IC=0.08 in-sample can have IC=-0.02 out-of-sample. Walk-forward is the primary statistical guard. FDR correction is necessary but not sufficient.

**Protocol:**
- Training window: 70% of available data
- Validation folds: 3 folds of 10% each
- Pass criteria: IC > 0 in >= 2 of 3 folds, IC Sharpe >= 0.4, consistent sign
- Holdout is burned exactly once — re-using it after disappointing results is p-hacking

**Status:** ✅ Specified in `docs/plans/2026-06-20-alphaengine-ic-spec.md` §IX.3
**Implementation:** ✅ Implemented in `services/ic_engine.py`

---

### Invariant 3: IC Sharpe, Not Raw IC

**Rule:** Ensemble weights use IC Sharpe (mean/std of IC over time), not raw IC.

**Why:** A feature with IC=0.06 and std=0.10 is volatile luck — high one month, flat the next, negative after. A feature with IC=0.03 and std=0.01 is stable edge. Raw IC cannot distinguish them. IC Sharpe penalizes volatility.

**Computation:**
```
IC Sharpe = mean(IC_t) / std(IC_t)
Where IC_t is computed on non-overlapping windows of 2,000 independent observations
Minimum: 10 IC observations (20,000 independent obs required)
```

**Status:** ✅ Specified in `docs/plans/2026-06-20-alphaengine-ic-spec.md` §X
**Implementation:** ✅ Implemented in `services/ic_engine.py`

---

### Invariant 4: Regime-Stratified, Not Pooled

**Rule:** IC measurement is stratified by HMM regime state. Pooled IC is a diagnostic statistic, not a production weight.

**Why:** A feature can have IC=0.06 in trending regimes and IC=-0.02 in ranging regimes. Averaging them produces pooled IC ≈ 0.02, which discards the regime-dependent signal. The ensemble would incorrectly downweight or discard a feature that is highly predictive in specific regimes.

**Enforcement:** `feature_ic_scores` regime column is NOT NULL. Pooled rows use `is_pooled=true` + `regime='_pooled'` sentinel. The ensemble reads only regime-stratified rows.

**Status:** ✅ Specified in `docs/plans/2026-06-20-alphaengine-ic-spec.md` §III.3
**Implementation:** ✅ Implemented

---

### Invariant 5: Automated Decay, No Human Gates

**Rule:** When rolling IC drops below threshold, weight is reduced to zero automatically. No human approval required.

**Why:** If decay requires human action, response is slow. If it responds instantly to every fluctuation, it oscillates. Hysteresis is the correct answer: decay triggers reduction; recovery requires sustained IC improvement over a non-overlapping window.

**Protocol:**
- Decay trigger: `rolling_ic_ci_lower <= 0.0` AND `weight × |ci_lower| > materiality_threshold`
- Weight update: automatic re-solve excluding decayed cell
- Recovery gate: requires 2,000 NEW independent observations (non-overlapping with decay window)
- No partial restoration — full Ledoit-Wolf re-solve assigns correct weight

**Status:** ✅ Specified in `docs/plans/2026-06-20-alphaengine-ic-spec.md` §XIII
**Implementation:** ⚠️ Partially implemented — hysteresis verification needed

---

### Invariant 6: Causal Regime Labels Only

**Rule:** HMM regime labels in `feature_vectors` MUST be causal (forward-filtered), not smoothed (backward-filtered).

**Why:** Backward smoothing uses future observations to refine past regime assignments. IC measured on smoothed labels overstates live performance because live trading only has access to forward-filtered labels.

**Enforcement:** `feature_vectors.regime_label_source` is schema-constrained to `{'filtered', 'unknown'}`. Any row with `regime_label_source = 'viterbi_batch'` or `'smoothed'` is rejected. IC engine filters `WHERE regime_label_source = 'filtered'`.

**Status:** ✅ Specified in `docs/plans/2026-06-20-alphaengine-ic-spec.md` §IV.1
**Implementation:** ✅ Enforced at schema level

---

### Invariant 7: Non-Overlapping IC Windows

**Rule:** IC time series for IC Sharpe computation uses non-overlapping observation windows.

**Why:** Consecutive bars are not independent. The 5-bar return at T and T+1 share 4 bars. Using every bar as an observation inflates effective N and understates standard errors. IC Sharpe on overlapping windows is meaningless.

**Sub-sampling:**
```
For lookahead N, sample every Nth bar:
observations = rows where (row_index % N) == 0
```

**Status:** ✅ Specified in `docs/plans/2026-06-20-alphaengine-ic-spec.md` §VIII.2
**Implementation:** ✅ Implemented in `services/ic_engine.py`

---

### Invariant Summary

| Invariant | Spec | Implementation | Blocker |
|-----------|------|-----------------|---------|
| 1. Executable returns | ✅ | ⚠️ | `forward_returns` computation |
| 2. Walk-forward gate | ✅ | ✅ | None |
| 3. IC Sharpe weights | ✅ | ✅ | None |
| 4. Regime-stratified | ✅ | ✅ | None |
| 5. Automated decay | ✅ | ⚠️ | Hysteresis verification |
| 6. Causal regimes | ✅ | ✅ | None |
| 7. Non-overlapping windows | ✅ | ✅ | None |

---

## The Problem Is the Signal Concept Itself

The current indicator-to-signal pipeline is excellent feature engineering. I1 through I6 produce a rich intelligence state per bar: mathematical indicators, composites, market structure, cross-timeframe context, patterns, and confluence scores. But at I7 the architecture makes a mistake that cannot be fixed by tuning weights or adding more plugins.

I7 encodes the concept of a **signal** — a researcher's predefined theory about which feature combinations constitute a tradeable edge. A plugin decides that RSI divergence plus volume confirmation plus CTF alignment constitutes edge, writes that logic, and the plugin fires. 138 plugins, 138 human theories.

The problem is not that the theories are wrong. Some are correct. The problem is that **the signal concept itself predisposes what the system can discover.**

By requiring a feature combination to be named and encoded as a plugin before the system will observe its outcomes, you guarantee:

**The system can only discover edges the researcher already believed in.** If RSI divergence plus volume acceleration plus a Wednesday in options expiry week plus macro risk-off produces a 65% win rate, the system will never find it — because no researcher thought to write that plugin. The IC engine can find it. A signal plugin cannot.

**Outcomes are only observed for bars that match the researcher's filter.** You cannot measure IC on outcomes you never observed. If a plugin only fires when hand-crafted conditions are met, you have a sample of outcomes selected by the researcher's prior. That is not an empirical measurement — it is confirmation bias with extra steps.

**Correlated theories amplify noise instead of multiplying information.** 138 plugins each responding to price patterns on the same chart are watching the same underlying phenomena from slightly different angles. The effective number of independent views is far lower than 138. The system believes it has 138 independent signals; it has perhaps 15.

**The signal concept is not just a flawed implementation. It is the wrong abstraction.** Even a sophisticated IC-weighted ensemble that uses I7 plugins as score producers has not escaped the problem — the plugins still define which features are grouped together, which combinations are worth scoring, which patterns deserve a name. The ensemble re-weights the researcher's theories. It does not replace them with empirical discovery.

---

## The Renaissance Method: Many Small ICs, Not Predefined Confluence

Before describing the replacement architecture, the council must agree on what Renaissance actually does — because it is frequently misunderstood.

Renaissance does not propose a trading hypothesis and then search for confluence that supports it. They do not say "RSI divergence is the signal; let's find which additional conditions make it more predictive." That is still the researcher's theory driving everything. It is hypothesis-first thinking dressed up in quantitative language.

What they do: **produce many simple features, measure IC on each one independently, and let the ensemble discover what combinations matter.**

The "insight" at Renaissance is not "we found a great signal." It is "we found 400 features that each have IC between 0.02 and 0.06, and when combined in an IC-weighted ensemble they produce a Sharpe of 1.8." No single feature is impressive. The edge is in the aggregate of many small, genuinely orthogonal sources of prediction.

This has a specific implication for confluence: **confluence is not defined by the researcher — it is measured by the ensemble.** When three features with independently positive IC all point in the same direction simultaneously, the ensemble alpha for that bar is high. That IS confluence. But it emerged from the data. No researcher sat down and decided "when these three features agree, that's a high-conviction setup." The IC engine found it by observing that those features' scores tend to co-occur at bars where forward returns are positive.

The reverse is also true: two features the researcher believes are complementary (CTF alignment and zone proximity, for example) may turn out to have near-identical IC profiles — they're measuring the same phenomenon from two angles. Their joint contribution to the ensemble is not 2× — it's approximately 1× because effective-N penalizes correlated sources. The researcher's intuition that "both being true means more confluence" is not automatically correct. The data decides.

**The researcher's role in this system is narrow and well-defined:** generate candidate features across orthogonal domains. Not design confluence rules. Not define what combinations of features constitute edge. Just produce the raw ingredients and let the measurement layer decide what is worth combining.

This reframes the entire I1-I7 pipeline. Every tier produces candidate features. The IC engine measures which features predict. The ensemble discovers which combinations matter. The output is alpha — not a signal, not a confluence score, not a hand-curated setup.

---

## The Renaissance Answer: Replace Signals with Scores

Simons's answer was not to build better signals. It was to eliminate the signal as a concept and replace it with something fundamentally different: **a continuous score per feature per bar, measured against forward returns, combined empirically.**

The insight: **you don't need complex signals. You need many simple, orthogonal feature scores with positive measured IC, aggregated by the data into an ensemble.**

IC — Information Coefficient — is the Spearman rank correlation between a feature score and subsequent N-bar returns. IC = 0.05 is meaningful. IC = 0.10 is exceptional. The IC engine becomes the empirical arbiter of which features carry predictive power, with no researcher required to define what the combinations should look like.

What replaces the signal:

- Every feature in I1-I6 produces a **continuous score** on every bar, unconditionally. No firing logic. No conditions to satisfy. A score on every bar, always.
- The IC Engine measures every score against forward returns across regimes and lookahead windows.
- The Ensemble aggregates scores weighted by IC Sharpe × orthogonality.
- When ensemble conviction crosses an empirically derived threshold, the system produces an **alpha emission** — a record of "at this bar, the aggregate of measured predictors indicated sufficient edge to act."

An alpha emission is not a signal. It carries no predefined theory about what features combined to produce it. It is the ensemble's output — a measured statement that this bar state, across all available score dimensions, had sufficient aggregate predictive power. The decomposition (which scores contributed, at what weights, in what regime) is stored alongside it, but it is attribution after the fact, not a predefined rule.

This matters because the system can now find edges that no researcher named. The combination of low momentum score, unusual volume, calendar proximity to options expiry, and risk-off macro score may produce IC 0.07 in trending regimes. The IC Engine finds this. A signal plugin cannot — it can only find what a researcher encoded.

---

## Intelligence Vectors

The system produces alpha by aggregating independent views of the same market. Each view is a **vector** — an orthogonal source of scored prediction. Every agent concept in the vision docs (QualAgent, FundAgent, FlowAgent, DerivAgent) is a vector at a different data granularity. The "agent" framing describes implementation; the "vector" framing describes what each contributes to the ensemble.

The full vector set:

| Vector | Domain | What it reads | Cadence | Data source |
|--------|--------|---------------|---------|-------------|
| **V1 Quant** | Price/volume | I1-I7 plugin scores | Per bar (real-time) | OHLCV — already built |
| **V2 Microstructure** | Order flow | Bar proxies; tick data upgrade | Per bar (real-time) | IBKR bars now; `reqTickByTickData` later |
| **V3 Macro** | Cross-asset | VIX, yield curve, sector rotation | Per bar / daily | Multi-instrument bars — mostly built |
| **V4 Calendar** | Time structure | Expiry cycles, rebalance windows | Daily (pre-computed) | Timestamp arithmetic — zero new data |
| **V5 Flow/Positioning** | Institutional flow | COT, dark pools, short interest | Weekly / daily / intraday | CFTC public; exchange feeds; paid providers |
| **V6 Derivatives/Gamma** | Options market | GEX, VANNA/CHARM, vol surface, VRP | Intraday | OPRA feed; options analytics provider |
| **V7 Qualitative** | Sentiment/narrative | News flow, analyst tone, social | Event-driven / intraday | News API; earnings call transcripts |
| **V8 Fundamental** | Financials | Earnings, macro releases, revisions | Quarterly / scheduled | FRED, SEC filings, earnings providers |

The vectors split into two fundamentally different kinds:

**Bar-aligned vectors (V1-V4):** produce a score per bar, per symbol, per timeframe. They update every time a new bar closes and are directly composable with the signal emission decision.

**Ambient vectors (V5-V8):** produce a score per symbol at their own cadence — not per bar, not per TF. COT updates weekly. GEX updates intraday but not at bar boundaries. Earnings fundamentals update quarterly. These are contextual conditions that hold across many bars until something changes them.

The ensemble treats these two kinds differently. Bar-aligned scores feed the emission decision directly. Ambient scores act as a regime-level modifier — they tilt ensemble weights up or down for all bars in the symbol until the ambient score is refreshed. A strong V6 bearish gamma signal doesn't fire a signal; it increases the conviction threshold required for a V1 bullish signal to emit.

### Cadence by Vector

| Vector | Update trigger | Score scope |
|--------|---------------|-------------|
| V1 Quant | Every bar close | Symbol × TF |
| V2 Microstructure | Every bar close | Symbol × TF |
| V3 Macro | Every bar close (some components daily) | Symbol / asset class |
| V4 Calendar | Daily | All symbols |
| V5 Flow/Positioning | Weekly (COT) / daily (short interest) / intraday (dark pools) | Symbol / sector |
| V6 Derivatives/Gamma | Intraday, event-driven (GEX flips, vol surface shifts) | Symbol |
| V7 Qualitative | Event-driven (news, earnings calls) | Symbol / sector |
| V8 Fundamental | Quarterly (earnings) / scheduled (macro releases) | Symbol / macro |

Ambient scores carry a `valid_until` timestamp. When a score expires without refresh it falls to neutral (zero), not the last known value.

### Orthogonality by Design

V1 responds to price patterns. V2 responds to who is trading. V3 responds to cross-asset flow. V4 responds to time. V5 responds to where institutions are positioned. V6 responds to what the options market is pricing in. V7 responds to narrative. V8 responds to fundamentals.

These are genuinely uncorrelated sources by construction — they read different phenomena through different instruments at different frequencies. Combining them multiplies edge rather than amplifying noise. Adding a correlated predictor does not add edge; adding an orthogonal one does.

### Build Order and Data Dependencies

V1-V4 are buildable with existing data now. V5-V8 require new data infrastructure:

- **V1-V4**: existing IBKR feeds, no new sources
- **V5**: CFTC public data (free), exchange feeds for dark pools (paid), short interest providers
- **V6**: OPRA options feed or analytics provider (~$300-500/month); high signal-to-cost ratio given GEX's documented mechanical effect
- **V7**: News API (various tiers), earnings transcript providers
- **V8**: FRED (free for macro), SEC EDGAR (free), earnings providers for clean structured data

The IC measurement gate applies to all: a vector does not enter the live ensemble until its score demonstrates `bootstrap_CI_lower(IC) > 0.0` at `n >= 100` observations. Data cost is only justified when IC is demonstrated.

### V2 Bar-Level Proxies (Current Implementation)

True microstructure (bid-ask spread, L2 order book, trade-by-trade flow) requires tick data. What we build now from OHLCV bars:

- Close position within bar `(close - low) / (high - low)` — buying pressure approximation
- Bar body vs wick ratio — conviction proxy
- Volume deviation from rolling average — attention/participation proxy
- Open-to-close vs overnight gap decomposition — informed vs uninformed flow separation

The upgrade path is IBKR `reqTickByTickData`, deferred until bar-level proxies have been IC-measured and the marginal value of tick data is justified empirically.

---

## Component Architecture

The full system decomposes into six distinct layers, each with a single responsibility. No layer does another's job. Data flows one direction through the DAG — no cycles, no feedback from governance into the hot path except through APR as the slow control plane.

```
RAW DATA
  ├── IBKR bars → V1, V2, V3 Score Producers (hot path, in-process)
  ├── Timestamp → V4 Score Producer (pre-computed daily)
  └── External feeds → V5-V8 Score Producers (async daemons, future)
          │
          ▼
SCORE NORMALIZATION
  └── Cross-sectional z-score per vector, rolling point-in-time window
          │
          ▼
  ┌───────┴──────────────────────────┐
  │                                  │
  ▼                                  ▼
ENSEMBLE (hot path)         MEASUREMENT (batch)
  ├── Bar-aligned agg        ├── IC Utility (shared stateless fn)
  │   V1-V4 IC-weighted      │   ├── AlphaEngine: plugin-grain IC
  ├── Ambient cache read     │   ├── IC Factory: feature-grain IC
  │   V5-V8 pre-loaded       │   └── Sub-score IC (Scoring Engine)
  ├── Regime gate (HMM)      ├── Correlation Engine: effective-N
  └── Emission gate          └── Alpha Decay Monitor (rolling IC)
          │                           │
          ▼                           ▼ (writes to APR)
  signal_events          APR (control plane — read at init only)
          │
          ▼
ECL ANNOTATOR (cold path batch)
  ├── AlphaEngine: alpha_score_quant, ensemble_ci_lower
  └── AnalogEngine: analog_score, analog_count, ood_flagged
          │
          ▼
GOVERNANCE (cold path)
  ├── Shadow Registry: outcome P&L per plugin/vector
  └── AnalogEngine: k-NN retrieval, Score Object, score_cache
```

### Layer 1 — Score Producers

One producer per vector. Each is isolated: it reads its own data source and emits a raw score. No producer knows about any other producer.

The critical invariant: **every plugin produces a score on every bar, whether or not it would have historically fired a signal.** If a plugin only computes its score when its hand-crafted conditions are partially met, IC measurement on that score is still subject to selection bias. Continuous scoring must be total — every bar, every plugin, unconditionally.

V1-V4 producers run in-process in `IntelligencePipeline`, per bar close. V5-V8 producers are async Ring 2 daemons that publish to Kafka; scores are consumed and held in an in-memory cache — never read from DB per bar.

### Layer 2 — Score Normalization

Raw scores from different vectors are not comparable. V1 ICC produces scores calibrated around historical plugin confidence. V6 GEX scores are on an entirely different scale. Before ensemble combination, every vector's scores are normalized to a common scale via rolling cross-sectional z-score, point-in-time:

```
normalized_score(v, t) = (raw_score(v, t) - rolling_mean(v, t)) / rolling_std(v, t)
```

Rolling window uses only data prior to bar T. Global normalization (mean/std computed over the full history including future bars) is look-ahead contamination and silently invalidates every downstream IC study. This is a hard requirement, not a preference.

### Layer 3 — Measurement (batch, not hot path)

Three components, one shared utility:

**IC Utility** — a single stateless function: takes a time series of `(normalized_score, forward_return)` pairs, outputs IC, IC Sharpe, bootstrap CI bounds. Called by three consumers at different grains:
- AlphaEngine: plugin × regime × TF × lookahead — answers "does this plugin predict returns?"
- IC Factory (AnalogEngine): feature × regime × horizon — answers "does this feature define good analogs?"
- Scoring Engine: sub-score × scope × horizon — answers "does this sub-score earn composite weight?"

One function. Three callers. Three output tables. Never one shared table — grain and ownership differ.

**Correlation Engine** — measures Spearman correlation between every vector pair's normalized score time series. Produces an effective-N adjustment per vector pair. Two vectors with correlation 0.8 do not contribute 2× information to the ensemble — their joint effective-N is approximately 1.3. This is not optional: an ensemble without effective-N correction silently amplifies correlated noise and produces overconfident alpha estimates.

**Alpha Decay Monitor** — not a separate component. It is the IC Engine running on a trailing window. When rolling IC for a plugin falls below the APR threshold, the IC Engine writes a reduced weight to APR. The slow control plane propagates it to the ensemble at next startup. No direct hot-path feedback.

IC measurement runs on **all bars where a score was produced**, not just bars where a signal was emitted. Measuring IC only on `signal_events` rows is selection bias — it measures the IC of scores that passed the researcher's hand-crafted filter, not the IC of the scores themselves.

FDR correction (Benjamini-Hochberg) is mandatory. With 138 plugins × 4 lookaheads × 6 regimes, the multiple comparison problem guarantees false discoveries without it. Plugins that survive FDR correction are the only ones that enter the ensemble.

### Layer 4 — Ensemble (hot path, in-process)

The only component that touches signal emission. It reads from APR (IC weights, thresholds — loaded at init, not per-bar) and from in-memory ambient cache (V5-V8 scores — pre-loaded, refreshed via Kafka subscription).

```
alpha_ensemble = Σ (normalized_score[p] × ic_weight[p][regime]) / effective_n
                  for p in active_plugins where ic_ci_lower[p][regime] > 0
```

Where `ic_weight` is IC Sharpe-normalized per regime, and `effective_n` is the correlation-adjusted count from the Correlation Engine. Ambient scores (V5-V8) modify the emission threshold, not the alpha score — a bearish gamma environment raises the threshold required for a long signal to emit.

Emission: `alpha_ensemble > threshold[regime]` → write to `signal_events`. One write path. The ensemble does not touch the DB otherwise.

Every emitted signal stores its decomposition: contributing plugin scores, IC weights used, effective-N, ambient modifiers applied, regime in effect. This is mandatory — not for audit, but because unexplainable signals cannot be debugged. Silent wrong answers are worse than loud crashes.

### Layer 5 — ECL Annotator (cold path)

A batch process that enriches `signal_events` after emission. Two systems contribute, each owning distinct fields:

- **AlphaEngine** annotates: `alpha_score_quant`, `ensemble_ci_lower`, per-vector IC summary
- **AnalogEngine** annotates: `analog_score`, `analog_count`, `ood_flagged`

Neither annotates the other's fields. Neither gates emission. The ECL boundary invariant is absolute: extrinsic confidence is training signal, never a live gate.

### Layer 6 — Governance (cold path)

**Shadow Registry** measures outcome P&L per plugin/vector. This is a separate question from IC: IC measures whether a score predicts returns as a raw predictor. Shadow measures whether the trade that resulted from the emitted signal made money. A plugin can have high IC and poor shadow (the edge exists but execution doesn't capture it). Both are necessary; neither replaces the other.

**AnalogEngine** — the non-parametric complement to AlphaEngine. Embeds the full I1-I7 bar state as a vector in pgvector. Finds K most similar historical bars. Returns what price did. No model assumptions. The null result — "no close analogs exist for this bar state" — is a named, surfaced output, not a fallback. When AnalogEngine and AlphaEngine agree, conviction is high. When they disagree, that disagreement is itself a signal worth examining before acting.

---

## IC as the Unit of Truth

IC is the Spearman rank correlation between a predictor score and subsequent forward returns. It is the single empirical arbiter across the entire architecture.

What Simons would insist on:

**IC Sharpe over raw IC.** IC = 0.08 with IC Sharpe = 0.3 is intermittent luck — the edge exists on average but is unreliable bar-to-bar. IC = 0.04 with IC Sharpe = 0.8 is tradeable — it is stable and compounds. IC Sharpe is the trust weight in the ensemble, not raw IC.

**Rolling walk-forward, never in-sample.** IC computed over the full history including the period being predicted is look-ahead contamination. IC for month M is computed using only months 1 through M-1. An IC number without a walk-forward construction date attached to it is not a valid IC number.

**FDR correction is a hard gate.** 138 plugins × 4 lookaheads × 6 regimes = over 3,000 hypothesis tests. At α = 0.05, 150 false discoveries are expected by chance alone. Benjamini-Hochberg correction is the minimum acceptable standard. Plugins that do not survive correction at `fdr_alpha` (APR-governed) do not enter the ensemble.

**Effect size over p-values.** A p < 0.001 IC of 0.01 is real and useless. Report IC level, IC Sharpe, and the hypothetical Sharpe of a signal built on this predictor after estimated transaction costs. If you cannot construct a Sharpe > 0.5 strategy from it, it has no practical value regardless of statistical significance.

**Regime conditioning everywhere.** Global IC hides the fact that a predictor may have IC = 0.06 in trending regimes and IC = -0.02 in ranging regimes. The global average of 0.02 enters the ensemble and destroys value in ranging regimes. Every IC measurement is stratified by HMM regime. Every ensemble weight is regime-specific.

**Score is always produced.** A plugin that only computes a score when its conditions are partially met introduces the same selection bias as the binary signal model, just one layer earlier. Every plugin must produce a score for every bar — the IC Engine measures that score's predictive power unconditionally.

---

## What Replaces the Signal

**Before:**
```
I1-I6 features → I7 plugin (researcher's rule) → fires/doesn't fire → signal_events row
```

**After:**
```
I1-I6 features → Score Producers (every feature, every bar, no firing logic)
               → Score Normalization
               → IC-weighted Ensemble
               → Alpha Emission (when conviction > regime threshold)
               → alpha_events row
```

No signal. No plugin firing logic. No predefined theory about which feature combinations matter. The researcher's role shifts from "define what constitutes a signal" to "define what features to produce" — and the IC Engine decides empirically which of those features carry predictive power.

### What Changes in the Data Model

`signal_events` → `alpha_events`. The record is no longer "a plugin decided conditions were met." It is "the ensemble had sufficient conviction at this bar, with these contributing scores and weights."

`alpha_events` schema (concept):
- `ts` — bar timestamp
- `symbol`, `timeframe`
- `alpha_score` — ensemble conviction `[-1, +1]`
- `alpha_ci_lower` — bootstrap confidence interval lower bound
- `regime` — HMM regime in effect at emission
- `effective_n` — number of independent predictors that contributed
- `score_decomposition` — JSONB: contributing feature scores, IC weights, ambient modifier values
- `ood_flagged` — AnalogEngine: no close historical analogs exist for this bar state

`trade_frames` and `trade_executions` remain. They capture what was done with the alpha emission — entry type, stop, target, counterfactual P&L, actual P&L. The emission is the opportunity; the frames are the hypothesis about how to act on it.

### What Happens to I7

I7 plugins are not deleted — they are **reconceived**. Instead of encoding firing logic, each I7 plugin becomes a **score producer**: a function that takes the I1-I6 intelligence state and emits a directional conviction score for that bar. No conditions. No thresholds. No binary output. A score on every bar, unconditionally.

The IC Engine then measures whether that score predicts returns. Plugins whose scores have no predictive power (IC near zero, failed FDR correction) contribute zero weight to the ensemble automatically. They do not need to be removed — they self-eliminate through IC weighting. Plugins that do carry predictive power earn their weight empirically.

This also means the 138 existing plugins are not replaced all at once. Each is migrated from "fires when conditions met" to "produces score unconditionally." The ensemble builds up as scores accumulate sufficient history for IC measurement. The transition is incremental and reversible.

---

## The Extrinsic Confidence Layer (ECL)

AlphaEngine and AnalogEngine are annotators, not gates. They enrich `signal_events` cold-path after emission, feeding the ML training matrix.

- AlphaEngine annotates: `alpha_score_quant`, `ensemble_ci_lower`, per-vector IC weights
- AnalogEngine annotates: `analog_score`, `analog_count`, `ood_flagged`

The ECL boundary invariant is absolute: no extrinsic score gates emission in the hot path. The hot path stays DB-ignorant. Extrinsic context is always cold-path enrichment.

---

## What the North Star Implies for Each Tier

Tracing the north star through the existing pipeline reveals which tiers survive unchanged, which need reconception, and which are replaced.

**I1 — Mathematical Indicators:** Survive unchanged in purpose. They produce raw feature scores (RSI, ATR, MACD, etc.) per bar. In the new model they continue to do exactly this — but every indicator produces a continuous score on every bar unconditionally, not a binary "condition met" flag. Minor reconception; no structural change.

**I2 — Composites:** Mostly survive. Composite features (volume profiles, multi-indicator summaries) are legitimate feature production. The question to ask per composite: "does this encode a researcher's theory about what combination matters, or does it produce a raw measurement?" Raw measurements stay. Encoded theories get decomposed back into their components and let the IC engine determine the weighting.

**I3 — Market Structure:** Survives. Structure detection (support/resistance, trend, SMC zones) produces proximity and structural state features. These are measurements of market geometry, not theories about what geometry constitutes edge. They enter the ensemble as independent scores.

**I4 — Regime / HMM:** Partially reconceived. HMM regime classification is legitimate and valuable — it stratifies all IC measurements and selects ensemble weight sets. But the regime class itself (trending, ranging, etc.) should also be a feature score entering the ensemble, not only a hard gate that switches between fixed rule sets. Regime features as continuous inputs; regime conditioning of IC weights as the mechanism.

**I5 — Patterns:** Reconceived. Pattern detection currently produces binary outputs ("pattern found" / "pattern not found"). In the new model, every pattern detector produces a continuous strength score on every bar. The IC engine measures whether that score predicts returns. Patterns with positive IC earn ensemble weight. Patterns with zero IC are not removed — they self-eliminate through zero IC weighting.

**I6 — Confluence: the tier that violates the north star most directly.**

I6 currently encodes researcher theories about which combinations of I1-I5 features together constitute "confluence." CTF alignment plus zone proximity plus regime agreement all being "on" simultaneously — the researcher decided that combination matters. This is the same category of mistake as I7 signal plugins: a human defining what feature combinations constitute predictive edge.

In the new architecture, I6 as a confluence-defining tier does not exist. What replaces it:

- Every I1-I5 feature score enters the ensemble independently
- The IC engine measures each score's predictive power
- When multiple high-IC scores co-occur pointing the same direction, ensemble alpha is high — this IS confluence, discovered by the data
- I6-tier features (CTF sub-scores, zone proximity scores, structural confluence measures) become additional independent score inputs, not confluence gates
- The effective-N correction in the ensemble handles correlated features — two features measuring the same phenomenon don't get double weight

The insight: if CTF alignment and zone proximity genuinely capture independent information, the IC engine will confirm it by showing they each have positive IC independently, and the ensemble will weight them both. If they're correlated — measuring the same thing from two angles — the correlation engine will reduce their joint effective-N and they'll contribute approximately 1× together. The researcher doesn't need to decide. The data shows it.

**I7 — Signals:** Replaced entirely. I7 is reconceived as additional score producers (directional conviction functions over I1-I6 state), or eliminated if I1-I6 already produce sufficient features for the ensemble. No signal firing logic. No confluence gates. No binary output. The ensemble is I7.

### What the Tier Structure Becomes

The I1-I7 pipeline does not disappear. It is reconceived:

```
I1-I5:  Feature production — mathematical, structural, regime, pattern scores
        Every feature produces a continuous score on every bar, unconditionally

I6:     Additional feature production — cross-timeframe and structural meta-features
        NOT confluence definition — just more scores for the ensemble

Ensemble: The new I7 — IC-weighted aggregation of all scores
          This is where confluence is discovered, not defined
          Produces alpha emission when aggregate conviction exceeds threshold
```

---

## What the North Star Implies for the Data Model

If there are no signals, there is no `signal_events`. What replaces it:

**`alpha_events`** — records when the ensemble's conviction crossed the emission threshold. Contains the ensemble alpha score, regime, effective-N, score decomposition (which features contributed at what weight), and ambient modifiers. No predefined theory about what fired. Attribution is stored as a decomposition, not as a cause.

**`feature_scores`** — a record of every feature's score on every bar, for every symbol. This is the raw material the IC engine operates on. Currently the analog of this is `intelligence_features` — it already exists and is the right concept. The shift is ensuring it contains continuous scores from all producers, not just features that were "active" when a signal fired.

**`trade_frames` and `trade_executions`** — unchanged in concept. They capture what was done with the alpha emission: how it was acted on, at what prices, with what outcome. The emission is the opportunity; the frames are the hypothesis about how to act.

`signal_ledger` becomes `alpha_ledger` — the join view across alpha_events, trade_frames, trade_executions. Same three-table architecture, different first table.

---

## What Doesn't Change

The infrastructure beneath the refactor is unchanged:

- I1-I5 compute exactly the features they compute today — they just emit continuous scores unconditionally instead of selectively
- HMM regime detection remains the stratification mechanism for IC measurement and ensemble weight selection
- APR governs all thresholds, weights, valid_until windows, and decay parameters
- Shadow governance tracks outcome P&L and governs promotion — now at the feature/vector level rather than the signal level
- AnalogEngine / VIL operates on the same `intelligence_features` bar state embeddings
- The three-table architecture persists: emissions → trade hypotheses → executions

---

## Phasing Concept

The refactor unfolds in stages, each independently valuable:

**Phase A — IC Measurement**
Pure analysis on existing data. No pipeline changes. Measure Spearman IC per plugin, regime, TF, lookahead on the current `signal_events` corpus. Immediately answers: which of 138 plugins carry information? Phase 133 (corpus rebuild) is superseded — IC measurement will eventually run on `intelligence_features` (all bars, unbiased) starting in Phase B.

**Phase B — Plugin Scores**
I7 plugins emit `alpha_score` alongside existing binary signal. Zero behavior change to emission. Schema additive.

**Phase C — Ensemble Layer**
IC-weighted ensemble aggregates plugin scores into a Quant Vector alpha. Replaces hand-crafted plugin confidence. Runs in-process in IntelligencePipeline after the signal tier.

**Phase D — Vector 2 (Microstructure)**
Order flow, CVD, trade size distribution scored per bar. Orthogonal to technical signals by construction. IC measured independently.

**Phase E — Vector 3 and 4 (Macro + Calendar)**
Calendar vector first (trivially orthogonal, time-based only). Macro vector second (cross-asset relationships already partially in context tier, shift to continuous scoring).

**AnalogEngine** runs in parallel with Phase C onward. It requires pgvector infrastructure (higher build cost) but is fully independent of AlphaEngine — either can run without the other.

---

## Related Docs

- `docs/plans/2026-06-20-intelligence-vectors-architecture.md` — AlphaEngine technical design (Phases A-E detail)
- `docs/plans/2026-06-20-v30-reference-architecture.md` — v3.0 reference: both systems, 10 Simons demands, full microservice DAG
- `docs/ideas/analog-engine-01-substrate.md` — VIL substrate: embedding, retrieval, pgvector
- `docs/ideas/analog-engine-02-ic-factory.md` — IC Factory: feature-level IC, Outcome Labeler, Analog Finder
- `docs/ideas/analog-engine-03-scoring-engine.md` — Score Object: transformation from analog set to scored conviction
- `docs/ideas/analog-engine-04-correlation.md` — Correlation Intelligence: effective-N measurement
- `docs/foundation/glossary.md` — canonical term definitions (IC, ECL, AlphaEngine, AnalogEngine, VIL)
