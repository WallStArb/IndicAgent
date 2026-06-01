# Predictive Feature Intelligence — I1-I7 State as Forward Price Predictor

**Version:** 1.2
**Status:** under-review
**Priority:** medium
**Last Updated:** 2026-05-31
**Tags:** pgvector, ic-analysis, feature-correlation, predictive, analog-finder, shadow-registry, scoring, vil

---

## Foundation

This document is an application of the **Vector Intelligence Layer** (`vil-01-vector-intelligence-layer.md`). VIL is the shared substrate — embed and retrieve. This document defines the **Predictive Feature Intelligence Layer**: the measurement factory that turns VIL retrievals into ground truth and trust weights.

VIL owns the infrastructure (embed, retrieve). The **Scoring Engine** (`intel-12-scoring-engine.md`) owns the transformation of analogs into scores. This layer sits between them and owns three things:
- **Outcome Labeler** — labels each historical bar with forward R-multiples at T+5/10/20 (the ground truth)
- **IC Factory** — continuously measures feature predictiveness (IC, IC Sharpe, FDR correction, PCA confluence, IC decay) — the trust weights intel-12 uses
- **Analog Finder** — a thin VIL k-NN retrieval wrapper that returns the **raw analog set**; intel-12 transforms it into scores

This layer does not compute scores, distributions, or the granularity dial — those belong to intel-12. It produces the empirical inputs intel-12 scores. Do not read this as a standalone design. Without VIL beneath it and intel-12 above it, it is only half a system.

---

## The Problem

The I1-I7 pipeline is a sophisticated intelligence machine. It computes indicators, classifies regimes, detects patterns, scores confluence, and fires signals. What it has never done is ask the most fundamental question: **does any of this actually predict price?**

Every bar is processed as if it is the first bar. RSI reads 67, volume profile shows a developing POC, regime is trending, SMC structure shows a bullish order block — the system computes all of this, fires a confluence score, maybe generates a signal. Then the bar closes, price moves, and the system forgets. The intelligence state at that bar and the outcome that followed are never connected.

This means:
- The 132 I7 plugins have no empirical validation of predictive power — only EV from resolved signals, which is a coarser measure
- LLM swarm agents reason from pattern recognition in a vacuum, not from grounded evidence about what similar conditions historically produced
- I7 governance decisions (raise/suppress) have no empirical basis for which intelligence states actually precede favorable moves
- eAI fitness evaluation has no ground truth to measure against — it measures narrative quality, not predictive accuracy
- There is no research surface for asking "which features have genuine edge, at which horizons, in which regimes"

Renaissance would identify this as the most important missing infrastructure in the system. The Medallion fund's edge is not in having better models — it is in having more observations per model and measuring every signal's IC continuously. Without that measurement fabric, you are flying blind.

---

## The Core Question

Given the full I1-I7 intelligence state at bar T — RSI value, volume profile, regime classification, SMC structure, confluence scores, all 132 plugin outputs — what does price do at T+5, T+10, T+20?

This is not "does RSI > 50 predict price." That is a weak, single-feature question with a noisy answer. The Renaissance-correct question is: **which feature states, individually and in combination, have stable, statistically significant, regime-conditioned predictive power over forward returns, measured out-of-sample?**

Every bar processed by the I1-I7 pipeline is implicitly a prediction about forward price. This system closes that feedback loop — for the first time connecting what the intelligence pipeline believed with what actually happened next.

---

## The General Idea

The solution is non-parametric and does not require a predictive model. It requires a substrate and a question.

**The substrate:** embed each bar's I1-I7 intelligence state as a vector, store it alongside what price did afterward. This is the VIL foundation — `intelligence_features` encoded, `outcome_labels` computed, both indexed for retrieval.

**The question:** when the current bar's intelligence state looks like this, find the K historical bars that looked most similar and ask what price did. The answer is a set of K analogs and their realized forward returns — the raw material everything else is built from.

intel-11 produces that raw material: the embedded bars (via VIL), the forward-return labels (Outcome Labeler), the trustworthiness of each feature (IC Factory), and the retrieval that pulls the K analogs (Analog Finder). It stops there. The transformation of those analogs into a score — the distribution, the sub-scores, the composite, the conviction envelope — is owned by the **Scoring Engine** (`intel-12`). The granularity dial (plugin / TF / symbol / cross-asset) also lives there.

**The result:** an empirical memory for the intelligence pipeline. Every bar's intelligence state is connected to what price did next, and every feature carries a continuously-measured verdict on whether it predicts. intel-12 reads these to produce the consumer-facing scores; I7 governance, LLM swarm prompts, eAI fitness, and research tooling consume those.

---

## What This Unlocks

| Consumer | What they gain |
|---|---|
| **LLM swarm agents** | Grounded historical evidence injected into prompts: "47 similar bars found — 63% up at T+10, avg +0.4R." The agent reasons over evidence, not pattern intuition. |
| **I7 governance** | Suppress or elevate based on whether current intelligence state historically precedes favorable moves — evidence-based, not rule-based. |
| **eAI fitness evaluation** | Empirical ground truth: an agent's predictions are measured against the analog distribution for the same bars. Calibration is a SQL query, not a narrative judgment. |
| **shadow_registry** | intel-11 supplies the IC *facts*; a governance consumer may build an IC-based dimension from them alongside EV-based suppression. A plugin can have positive EV but zero IC — they measure different things. The measurement is intel-11's; any suppression decision is the consumer's. |
| **Research / Superset** | "Which features have genuine predictive power at 10-bar horizon in trending regime?" becomes a query. The IC Factory is the research surface. |
| **Signal quality** | Signals generated under high-conviction analog conditions (tight distribution, 200+ analogs) are empirically distinguished from those generated in unprecedented conditions (no close analogs). |

---

## What Simons Would Demand

**1. IC is the unit of measure. IC Sharpe is the unit of trust.**
Information Coefficient (Spearman rank correlation between feature value and forward return) tells you a signal exists. IC Sharpe (IC / std(IC) over rolling time windows) tells you whether it is *stable*. IC 0.08 with IC Sharpe 0.3 is intermittent luck. IC 0.04 with IC Sharpe 0.8 is tradeable edge. Only IC Sharpe distinguishes signal from noise.

**2. Rolling walk-forward, never in-sample.**
IC is always computed on data not used to find it. Expanding window: compute IC for month M using only months 1..M-1. A feature whose IC chart is erratic or sign-flipping has no edge.

**3. Multiple comparison correction is a hard requirement.**
132 plugins × 3 horizons × N regimes = hundreds of hypothesis tests. Without Benjamini-Hochberg FDR correction, spurious "discoveries" are guaranteed. The features that survive correction are the only ones worth trusting.

**4. Effect size over p-values.**
A p < 0.001 IC of 0.02 is real and useless. Report IC level, IC Sharpe, and the Sharpe ratio of a hypothetical signal built on this feature. If you cannot build a Sharpe > 0.5 strategy from it after transaction costs, it has no practical value.

**5. Regime-condition everything.**
RSI > 70 in a trending regime is a continuation signal. The same reading in a ranging regime is a reversal signal. Global correlations hide this. All IC computations are stratified by regime class from I4.

**6. Timestamp alignment is a hard gate.**
`intelligence_features` at timestamp T must use only data available strictly before T closes. Our `pipeline_latency_ms` field verifies this. Look-ahead contamination invalidates the entire study. Verify before computing a single IC.

**7. Confluence is discovered, not enumerated.**
Searching all pairs and triples of 132 features is combinatorially intractable and statistically poisoned by multiple comparisons. PCA over the feature matrix finds natural confluences — principal components that explain variance in forward returns. Each PC is a data-discovered linear combination of features. No manual search, no false discovery from enumeration.

**8. Signals have half-lives. Monitor continuously.**
A feature with IC 0.07 today may be zero in six months as the edge gets arbitraged. intel-11 *tracks* decay as a stored number — rolling 30-day and 90-day IC — and stops there. Acting on decay (down-weighting is automatic and continuous in intel-12; any hard gate is a separate governance consumer) is a decision, made downstream, not in the measurement factory.

---

## What intel-11 Hands to the Scoring Engine

The Analog Finder returns a raw analog set — the K most similar historical bars and their realized forward returns at each horizon — plus the IC Factory's per-feature trust weights. That is the boundary. Everything downstream is owned by `intel-12`:

- **The granularity dial** (plugin / TF / symbol / cross-asset scoping) — intel-12
- **The return distribution** (shape, percentiles, moments, null result) — intel-12
- **The sub-scores and composite** (directional HR, expected R, Sharpe-at-horizon, IC-Sharpe-weighted blend) — intel-12

intel-11's contract is narrow and testable: given a query bar, return `list[AnalogResult]` (neighbor id, distance, forward returns, regime) and the current `feature_ic_stats`. It does not aggregate, rank, or score. See `intel-12` for what is built on top.

---

## Supporting Infrastructure

Three pieces of machinery support the scoring layer. All build on VIL substrate — they do not redefine it.

### Outcome Labeler (nightly batch)

Joins `intelligence_features` to `market_data_ohlcv` to compute forward returns for each bar. Uses VIL's `outcome_labels` table (see vil-01 schema). Forward return in **R-multiples** (forward move / ATR at bar T) — normalizes across regimes and instruments, directly comparable to `pnl_r` in `signal_ledger`.

### IC Factory (weekly batch)

Reads `intelligence_features` + `outcome_labels`. Computes Spearman IC per feature × horizon × regime, rolling walk-forward. Applies Benjamini-Hochberg FDR correction. Computes IC Sharpe. **It makes no decisions.** The IC Factory measures and stores; it never suppresses, gates, or thresholds. A feature with no edge is simply recorded as having no edge — what to do with that fact is a consumer's concern. intel-12 weights features continuously by IC Sharpe (a zero-IC feature contributes ~0 with no hard switch); any hard on/off would be a separate, explicit governance consumer, never the factory.

> **Measurement layers are append-only, assumption-free fact records. Decision layers are stateful, reversible, and live separately. A threshold is a decision; it never belongs in a measurement table.** Decisions live in `shadow_registry` (plugin-grain EV and correlation suppression); measurements live in `feature_ic_stats` and the VIL tables.

Output feeds intel-12 as quality metadata: which features have genuine predictive power, with what stability, at which horizon and regime. intel-12 uses feature IC Sharpe to weight the **retrieval metric** (which features define similarity).

**The IC computation is generic over "predictor."** intel-12's composite blends four sub-scores and weights them by *their* IC Sharpe — each sub-score treated as a predictor and measured by the identical machinery (rolling Spearman vs realized returns, FDR-corrected). The IC math is one stateless utility: hand it a feature's history or a sub-score's history, same computation. The two differ only in *grain* and *ownership* — feature IC (`feature × horizon × regime`) is intel-11's and lands in `feature_ic_stats`; sub-score IC (`sub-score × scope × level × horizon`) is intel-12's and lands in an intel-12-owned table. Shared utility and shared weekly cadence, separate owned sinks — never a shared table. Feature IC weights the retrieval metric; sub-score IC weights the blend (see intel-12 → The Composite Z-Score). One tool, two levels.

```
feature_ic_stats (
  feature_name TEXT,
  horizon_bars INTEGER,
  regime TEXT,
  ic DOUBLE PRECISION,
  ic_sharpe DOUBLE PRECISION,
  ic_std DOUBLE PRECISION,
  n_obs INTEGER,
  fdr_adjusted_pvalue DOUBLE PRECISION,
  computed_at TIMESTAMPTZ
)
-- Facts only. No `suppressed` flag and no derived `is_significant` —
-- a significance flag bakes an alpha (a decision). Store the raw
-- fdr_adjusted_pvalue; each consumer applies its own threshold.
```

Queryable in Superset: "top 20 most stable features in trending regime at 10-bar horizon."

### Analog Finder (per-bar, at inference time)

A thin VIL k-NN wrapper. Serializes the current bar's feature vector (via the VIL embedding spec), runs k-NN retrieval from `embeddings`, joins to `outcome_labels`, and returns the **raw analog set** — `list[AnalogResult]` (neighbor id, cosine distance, forward returns at each horizon, regime). It does **not** compute directional HR, distributions, or composite scores; intel-12 does that.

The Analog Finder is non-parametric. No functional form assumed. It answers exactly one question: in the K most similar past situations, what happened? Exposed on `BaseAIWorker` as `_find_analogs(k, scope, regime)` so the scoring engine and swarm agents share one retrieval path.

---

## Relationship to Existing Infrastructure

| Component | Relationship |
|---|---|
| `vil-01` (VIL substrate) | Foundation beneath. All embedding, retrieval, and table infrastructure is defined there. |
| `intel-12` (Scoring Engine) | Consumer above. Reads intel-11's `list[AnalogResult]` + `feature_ic_stats` and transforms them into the Score Object. intel-11 produces; intel-12 scores. |
| `intel-10` (plugin correlation) | Sibling application of VIL. Shares the embedding pipeline and substrate. Different question: plugin independence rather than forward price prediction. |
| `shadow_registry` | A decision table (plugin-grain EV + correlation suppression). intel-11 does **not** write to it — it produces IC facts a governance consumer may act on. The reuse with shadow_registry is conceptual (a future IC governance consumer could mirror its flag + self-expiry pattern), not a write path from the factory. |
| `signal_ledger.pnl_r` | R-multiple convention shared. `outcome_labels.ret_N` is directly comparable to `pnl_r` — same unit, same meaning. |
| `BaseAIWorker` | Analog Finder exposed as `_find_analogs(k, scope, regime)` — grounded historical context injected into LLM prompts. |
| ML batch services | IC Factory runs on the same weekly timer cadence as `ml-training`. Could share infrastructure. |

---

## What This Is Not

- **Not a new signal plugin.** The outputs are observational. intel-11 does not emit I7 signals directly. Downstream use of high-IC features as signal inputs is a separate decision.
- **Not a replacement for shadow governance.** Shadow registry governs plugin EV. IC Factory *measures* feature predictiveness — it does not govern anything. These are different things — a plugin can have high EV and low IC (consistent small wins, direction not proportional to reading strength) or vice versa — and only EV governance acts; IC is a fact a consumer may choose to act on.
- **Not a model.** The Analog Finder is retrieval, not parametric prediction. It provides empirical context for LLM inference, not a mechanical trading rule.

---

## Open Questions

_Embedding serialization (what makes two states "similar"), vector dimension/PCA, regime-conditioned retrieval, and analog distance-weighting are owned by `vil-01` (representation/retrieval) and `intel-12` (scoring). The questions below are specific to the measurement factory._

- **Horizon declaration:** Should a feature declare its relevant horizon, or does the IC Factory always measure all horizons and let intel-12 surface the full profile?
- **Minimum history gate:** IC computation requires sufficient history for statistical power. Minimum `n_obs` before a feature is considered (100 bars? 252 bars?)?
- **(Deferred to a future governance consumer, not intel-11):** if anyone ever wants a *hard* IC on/off — what IC Sharpe floor, over how many consecutive cycles, mirroring shadow_registry's demotion rule? This is explicitly out of the measurement factory's scope; intel-11 only stores the facts such a consumer would read.
- **PCA refresh cadence:** Recompute principal components every weekly run, or hold them fixed across a longer window for stability?
- **Sub-score IC grain (cross-doc) — resolved:** intel-12 weights its composite sub-scores by *their* IC Sharpe, measured by this same machinery. Because a sub-score is a different grain (sub-score × scope × level × horizon) than a feature, sub-score IC lives in an **intel-12-owned table**, not in `feature_ic_stats` — the two share only the stateless IC computation utility (and the same weekly batch), never a table. intel-11 owns feature IC; intel-12 owns sub-score IC. See intel-12 → The Composite Z-Score.

---

## Principles Alignment

| Principle | How this satisfies it |
|---|---|
| **Modularity** | Outcome Labeler, IC Factory, Analog Finder each have one job. The boundary to intel-12 is a narrow `list[AnalogResult]` + `feature_ic_stats` contract. |
| **Reuse** | Builds entirely on VIL substrate. The IC *measurement* machinery is generic over predictor (feature or sub-score — intel-12's second client). Shares R-multiple convention with signal_ledger. Hands one retrieval path (`_find_analogs`) to both intel-12 and swarm agents. |
| **Separation of concerns** | Labeling (Outcome Labeler), discovery (IC Factory), and retrieval (Analog Finder) are distinct jobs. Scoring is a separate concern entirely — owned by intel-12, not conflated here. |
| **Instrument everything** | IC stats, IC Sharpe, IC decay, FDR p-values, k-NN query latency — all stored as facts and Grafana/Superset visible. No decision events here; those are emitted by whatever consumer acts on the facts. |
| **Shadow mode first** | Score primitive operates in analytical/observational mode. No live pipeline action until I7 governance consumer is explicitly wired. |
| **Data quality over model complexity** | IC Sharpe and FDR correction enforce rigor. Probability spectrum surfaces uncertainty honestly rather than collapsing to a point estimate. |
| **Compounding** | Every bar added to embeddings improves analog retrieval. IC Factory improves with more history. The substrate compounds in value with age. |
