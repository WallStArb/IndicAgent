# Predictive Feature Intelligence — I1-I7 State as Forward Price Predictor

**Archived 2026-07-02.** Superseded by the Measurement Engine unification (D4/D1) — feature-level
IC measurement is now one estimator shared with `ic_engine.py`, not a parallel factory. The
Analog Finder wrapper concept survives in `docs/research/intel-13-analog-engine.md`. Kept here for
reference (IC methodology detail already covered by `ic_engine.py`/Measurement Engine design).

**Version:** 1.2
**Status:** under-review
**Priority:** medium
**Last Updated:** 2026-05-31
**Tags:** pgvector, ic-analysis, feature-correlation, predictive, analog-finder, shadow-registry, scoring, vil

---

## Foundation

This document is an application of the **Vector Intelligence Layer** (`analog-engine-substrate.md`). VIL is the shared substrate — embed and retrieve. This document defines the **Predictive Feature Intelligence Layer**: the measurement factory that turns VIL retrievals into ground truth and trust weights.

**Scope boundary — read this before anything else.** Two IC measurements exist in the v3.0 architecture and they are not the same thing:

- **analog-engine-ic-factory (this doc)** measures **feature-level IC** — which individual dimensions of the bar embedding predict forward returns. This determines which features deserve more weight in k-NN similarity re-ranking (`feature_ic_stats`). It answers: *which bar-state features define good analogs?*
- **AlphaEngine** measures **plugin-level IC** — whether a plugin's confidence score, as a time series, predicts forward returns (`plugin_ic_scores`). This determines ensemble weights and emission thresholds. It answers: *does this plugin carry edge?*

These answer different questions at different granularities and must never be merged. A feature can have high embedding IC (it reliably distinguishes analog quality) while the plugin that computes it has zero ensemble IC (its directional score doesn't predict returns). analog-engine-ic-factory has no opinion on plugin predictiveness — that is AlphaEngine's domain.

VIL owns the infrastructure (embed, retrieve). The **Scoring Engine** (`analog-engine-scoring-engine.md`) owns the transformation of analogs into scores. This layer sits between them and owns three things:
- **Outcome Labeler** — labels each historical bar with forward R-multiples at T+5/10/20 (the ground truth)
- **IC Factory** — continuously measures *feature-level* predictiveness (IC, IC Sharpe, FDR correction, IC decay) — used by analog-engine-scoring-engine to re-rank the k-NN candidate set, not to weight the emission ensemble
- **Analog Finder** — a thin VIL k-NN retrieval wrapper that returns the **raw analog set**; analog-engine-scoring-engine transforms it into scores

This layer does not compute scores, distributions, or emission decisions — those belong to analog-engine-scoring-engine and AlphaEngine respectively. Do not read this as a standalone design. Without VIL beneath it and analog-engine-scoring-engine above it, it is only half a system.

---

## The Problem

The I1-I7 pipeline is a sophisticated intelligence machine. It computes indicators, classifies regimes, detects patterns, scores confluence, and produces plugin alpha scores. What the AnalogEngine retrieval substrate has never done is ask: **given that the current bar looks like this, find the historical bars that looked most similar — and weight that similarity so that features which actually predict returns dominate the distance metric.**

Every k-NN retrieval without feature IC weighting treats RSI and volume profile as equally relevant to similarity. They may not be. A feature with zero forward-return predictiveness should contribute ~zero to cosine distance; a feature with stable IC should dominate. Without measuring which features deserve that weight, the embedding is a uniformly-weighted noise machine.

This means:
- k-NN retrieval without feature IC weighting returns neighbors defined by noisy dimensions alongside predictive ones
- LLM swarm agents receive analog sets drawn from misleading similarity — matched on irrelevant features
- eAI fitness comparison uses Score Objects built on imprecise analog retrieval
- Research cannot ask "which bar-state features define the best analogs at 10-bar horizon in trending regime"

This measurement layer closes that loop. It does not measure plugin predictiveness — AlphaEngine does that. It measures which features in the embedding make retrieval better.

---

## The Core Question

Given the full I1-I7 intelligence state at bar T — RSI value, volume profile, regime classification, SMC structure, confluence scores — **which of these features, individually, have stable, regime-conditioned Spearman correlation with forward returns, measured out-of-sample?**

This is not the same question as "does plugin X carry edge?" (AlphaEngine's question). It is: **which dimensions of the embedding define good analogs?** A feature with IC 0.05 at T+10 in trending regime should pull the k-NN distance metric toward it; a feature with IC near zero is noise in the similarity computation and should contribute ~nothing.

---

## The General Idea

The solution is non-parametric and does not require a predictive model. It requires a substrate and a question.

**The substrate:** embed each bar's I1-I7 intelligence state as a vector, store it alongside what price did afterward. This is the VIL foundation — `intelligence_features` encoded, `forward_returns` computed, both indexed for retrieval.

**The question:** when the current bar's intelligence state looks like this, find the K historical bars that looked most similar and ask what price did. The answer is a set of K analogs and their realized forward returns — the raw material everything else is built from.

analog-engine-ic-factory produces that raw material: the embedded bars (via VIL), the forward-return labels (Outcome Labeler), the trustworthiness of each feature (IC Factory), and the retrieval that pulls the K analogs (Analog Finder). It stops there. The transformation of those analogs into a score — the distribution, the sub-scores, the composite, the conviction envelope — is owned by the **Scoring Engine** (`analog-engine-scoring-engine`). The granularity dial (plugin / TF / symbol / cross-asset) also lives there.

**The result:** an empirical memory for the intelligence pipeline. Every bar's intelligence state is connected to what price did next, and every feature carries a continuously-measured verdict on whether it predicts. analog-engine-scoring-engine reads these to produce the consumer-facing scores; LLM swarm agents, eAI fitness, and research tooling consume those.

---

## What This Unlocks

| Consumer | What they gain |
|---|---|
| **analog-engine-scoring-engine (k-NN re-ranking)** | `feature_ic_stats` weights the candidate re-rank step: retrieve 200 by plain cosine, re-rank to final K by IC-weighted distance. The analog set that flows into Score Objects is defined by predictive similarity, not uniform similarity. |
| **LLM swarm agents** | Analog sets grounded in historically predictive similarity — the evidence injected into prompts is "47 bars that looked like this in the ways that matter, and here is what followed." |
| **eAI fitness** | Score Objects built on IC-weighted retrieval are a tighter ground truth — agent predictions are measured against analog sets that reflect genuine similarity, not noisy feature parity. |
| **Research / Superset** | "Which features define the best analogs at 10-bar horizon in trending regime?" is a query on `feature_ic_stats`. The IC Factory is the research surface for embedding quality, not plugin quality. |

---

## What Simons Would Demand

**1. IC is the unit of measure. IC Sharpe is the unit of trust.**
Information Coefficient (Spearman rank correlation between feature value and forward return) tells you a signal exists. IC Sharpe (IC / std(IC) over rolling time windows) tells you whether it is *stable*. IC 0.08 with IC Sharpe 0.3 is intermittent luck. IC 0.04 with IC Sharpe 0.8 is tradeable edge. Only IC Sharpe distinguishes signal from noise.

**2. Rolling walk-forward, never in-sample.**
IC is always computed on data not used to find it. Expanding window: compute IC for month M using only months 1..M-1. A feature whose IC chart is erratic or sign-flipping has no edge.

**3. Multiple comparison correction is a hard requirement.**
N feature dimensions × 3 horizons × R regimes = hundreds of hypothesis tests. Without Benjamini-Hochberg FDR correction (APR: `analog.ic.fdr_alpha`, default 0.05), spurious "discoveries" are guaranteed. The features that survive correction are the only ones worth trusting.

**4. Effect size over p-values.**
A p < 0.001 IC of 0.02 is real and useless. Report IC level, IC Sharpe, and the Sharpe ratio of a hypothetical signal built on this feature. If you cannot build a Sharpe > 0.5 strategy from it after transaction costs, it has no practical value.

**5. Regime-condition everything.**
RSI > 70 in a trending regime is a continuation signal. The same reading in a ranging regime is a reversal signal. Global correlations hide this. All IC computations are stratified by regime class from I4.

**6. Timestamp alignment is a hard gate.**
`intelligence_features` at timestamp T must use only data available strictly before T closes. Our `pipeline_latency_ms` field verifies this. Look-ahead contamination invalidates the entire study. Verify before computing a single IC.

**7. Confluence is discovered, not enumerated.**
Searching all pairs and triples of 132 features is combinatorially intractable and statistically poisoned by multiple comparisons. PCA over the feature matrix finds natural confluences — principal components that explain variance in forward returns. Each PC is a data-discovered linear combination of features. No manual search, no false discovery from enumeration.

**8. Signals have half-lives. Monitor continuously.**
A feature with IC 0.07 today may be zero in six months as the edge gets arbitraged. analog-engine-ic-factory *tracks* decay as a stored number — rolling 30-day and 90-day IC — and stops there. Acting on decay (down-weighting is automatic and continuous in analog-engine-scoring-engine; any hard gate is a separate governance consumer) is a decision, made downstream, not in the measurement factory.

---

## What analog-engine-ic-factory Hands to the Scoring Engine

The Analog Finder returns a raw analog set — the K most similar historical bars and their realized forward returns at each horizon — plus the IC Factory's per-feature trust weights. That is the boundary. Everything downstream is owned by `analog-engine-scoring-engine`:

- **The granularity dial** (plugin / TF / symbol / cross-asset scoping) — analog-engine-scoring-engine
- **The return distribution** (shape, percentiles, moments, null result) — analog-engine-scoring-engine
- **The sub-scores and composite** (directional HR, expected R, Sharpe-at-horizon, IC-Sharpe-weighted blend) — analog-engine-scoring-engine

analog-engine-ic-factory's contract is narrow and testable: given a query bar, return `list[AnalogResult]` (neighbor id, distance, forward returns, regime) and the current `feature_ic_stats`. It does not aggregate, rank, or score. See `analog-engine-scoring-engine` for what is built on top.

---

## Supporting Infrastructure

Three pieces of machinery support the scoring layer. All build on VIL substrate — they do not redefine it.

### Outcome Labeler (nightly batch)

Joins `intelligence_features` to `market_data_ohlcv` to compute forward returns for each bar. Uses VIL's `forward_returns` table (see analog-engine-substrate schema). Forward return in **R-multiples** (forward move / ATR at bar T) — normalizes across regimes and instruments, directly comparable to `pnl_r` in `signal_ledger`.

### IC Factory (weekly batch)

Reads `intelligence_features` + `forward_returns`. Computes Spearman IC per feature × horizon × regime, rolling walk-forward. Applies Benjamini-Hochberg FDR correction. Computes IC Sharpe. **It makes no decisions.** The IC Factory measures and stores; it never suppresses, gates, or thresholds. A feature with no edge is simply recorded as having no edge — what to do with that fact is a consumer's concern. analog-engine-scoring-engine weights features continuously by IC Sharpe (a zero-IC feature contributes ~0 with no hard switch); any hard on/off would be a separate, explicit governance consumer, never the factory.

> **Measurement layers are append-only, assumption-free fact records. Decision layers are stateful, reversible, and live separately. A threshold is a decision; it never belongs in a measurement table.** Decisions live in `shadow_registry` (plugin-grain EV and correlation suppression); measurements live in `feature_ic_stats` and the VIL tables.

Output feeds analog-engine-scoring-engine as quality metadata: which features have genuine predictive power, with what stability, at which horizon and regime. analog-engine-scoring-engine uses feature IC Sharpe to weight the **retrieval metric** (which features define similarity).

**The IC computation is generic over "predictor."** analog-engine-scoring-engine's composite blends four sub-scores and weights them by *their* IC Sharpe — each sub-score treated as a predictor and measured by the identical machinery (rolling Spearman vs realized returns, FDR-corrected). The IC math is one stateless utility: hand it a feature's history or a sub-score's history, same computation. The two differ only in *grain* and *ownership* — feature IC (`feature × horizon × regime`) is analog-engine-ic-factory's and lands in `feature_ic_stats`; sub-score IC (`sub-score × scope × level × horizon`) is analog-engine-scoring-engine's and lands in an analog-engine-scoring-engine-owned table. Shared utility and shared weekly cadence, separate owned sinks — never a shared table. Feature IC weights the retrieval metric; sub-score IC weights the blend (see analog-engine-scoring-engine → The Composite Z-Score). One tool, two levels.

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

A thin VIL k-NN wrapper. Serializes the current bar's feature vector (via the VIL embedding spec), runs k-NN retrieval from `embeddings`, joins to `forward_returns`, and returns the **raw analog set** — `list[AnalogResult]` (neighbor id, cosine distance, forward returns at each horizon, regime). It does **not** compute directional HR, distributions, or composite scores; analog-engine-scoring-engine does that.

The Analog Finder is non-parametric. No functional form assumed. It answers exactly one question: in the K most similar past situations, what happened? Exposed on `BaseAIWorker` as `_find_analogs(k, scope, regime)` so the scoring engine and swarm agents share one retrieval path.

---

## Relationship to Existing Infrastructure

| Component | Relationship |
|---|---|
| `analog-engine-substrate` (VIL substrate) | Foundation beneath. All embedding, retrieval, and table infrastructure is defined there. |
| `analog-engine-scoring-engine` (Scoring Engine) | Consumer above. Reads analog-engine-ic-factory's `list[AnalogResult]` + `feature_ic_stats` and transforms them into the Score Object. analog-engine-ic-factory produces; analog-engine-scoring-engine scores. |
| `analog-engine-correlation` (Correlation Intelligence) | Sibling measurement layer. analog-engine-ic-factory measures prediction (IC); analog-engine-correlation measures independence (effective-N) — the two orthogonal questions about any signal source. Shares the embedding pipeline and substrate. |
| `shadow_registry` | A decision table (plugin-grain EV + correlation suppression). analog-engine-ic-factory does **not** write to it — it produces IC facts a governance consumer may act on. The reuse with shadow_registry is conceptual (a future IC governance consumer could mirror its flag + self-expiry pattern), not a write path from the factory. |
| `signal_ledger.pnl_r` | R-multiple convention shared. `forward_returns.ret_N` is directly comparable to `pnl_r` — same unit, same meaning. |
| `BaseAIWorker` | Analog Finder exposed as `_find_analogs(k, scope, regime)` — grounded historical context injected into LLM prompts. |
| ML batch services | IC Factory runs on the same weekly timer cadence as `ml-training`. Could share infrastructure. |

---

## What This Is Not

- **Not an action layer.** analog-engine-ic-factory is a compute/transform agent: it reads data, computes IC, and writes facts to its own table. It takes no live action and has no blast radius — so the calibration-and-action gate lives entirely with the consumer, never here.
- **Not a new signal plugin.** The outputs are facts, not signals — analog-engine-ic-factory emits no I7 signals and takes no action. Downstream use of high-IC features as signal inputs is a separate decision, made by a consumer.
- **Not a replacement for shadow governance.** Shadow registry governs plugin EV. IC Factory *measures* feature predictiveness — it does not govern anything. These are different things — a plugin can have high EV and low IC (consistent small wins, direction not proportional to reading strength) or vice versa — and only EV governance acts; IC is a fact a consumer may choose to act on.
- **Not a model.** The Analog Finder is retrieval, not parametric prediction. It provides empirical context for LLM inference, not a mechanical trading rule.

---

## Open Questions

_Embedding serialization (what makes two states "similar"), vector dimension/PCA, regime-conditioned retrieval, and analog distance-weighting are owned by `analog-engine-substrate` (representation/retrieval) and `analog-engine-scoring-engine` (scoring). The questions below are specific to the measurement factory._

- **Horizon declaration:** Should a feature declare its relevant horizon, or does the IC Factory always measure all horizons and let analog-engine-scoring-engine surface the full profile?
- **Minimum history gate:** IC computation requires sufficient history for statistical power. → Governed by APR: `analog.ic.min_n_observations` (default 100). Rolling window length: APR `analog.ic.rolling_window_days` (default 90).
- **(Deferred — now specified in `docs/research/feature-vector-lifecycle.md`):** hard IC on/off governance — what IC Sharpe floor, over how many consecutive cycles, mirroring shadow_registry's demotion rule. Explicitly out of the measurement factory's scope; analog-engine-ic-factory only stores the facts that consumer reads. Threshold constants in APR under `alpha.ic.*`.
- **PCA refresh cadence:** Recompute principal components every weekly run, or hold them fixed across a longer window for stability?
- **Sub-score IC grain (cross-doc) — resolved:** analog-engine-scoring-engine weights its composite sub-scores by *their* IC Sharpe, measured by this same machinery. Because a sub-score is a different grain (sub-score × scope × level × horizon) than a feature, sub-score IC lives in an **analog-engine-scoring-engine-owned table**, not in `feature_ic_stats` — the two share only the stateless IC computation utility (and the same weekly batch), never a table. analog-engine-ic-factory owns feature IC; analog-engine-scoring-engine owns sub-score IC. See analog-engine-scoring-engine → The Composite Z-Score.

---

## Principles Alignment

| Principle | How this satisfies it |
|---|---|
| **Modularity** | Outcome Labeler, IC Factory, Analog Finder each have one job. The boundary to analog-engine-scoring-engine is a narrow `list[AnalogResult]` + `feature_ic_stats` contract. |
| **Reuse** | Builds entirely on VIL substrate. The IC *measurement* machinery is generic over predictor (feature or sub-score — analog-engine-scoring-engine's second client). Shares R-multiple convention with signal_ledger. Hands one retrieval path (`_find_analogs`) to both analog-engine-scoring-engine and swarm agents. |
| **Separation of concerns** | Labeling (Outcome Labeler), discovery (IC Factory), and retrieval (Analog Finder) are distinct jobs. Scoring is a separate concern entirely — owned by analog-engine-scoring-engine, not conflated here. |
| **Instrument everything** | IC stats, IC Sharpe, IC decay, FDR p-values, k-NN query latency — all stored as facts and Grafana/Superset visible. No decision events here; those are emitted by whatever consumer acts on the facts. |
| **No action, no blast radius** | analog-engine-ic-factory is a pure compute layer: it reads, measures, and writes facts to `feature_ic_stats`. It actions nothing and feeds no live lever, so there is no operational risk to guard against here — the decision to act on any fact is the consumer's, gated at the consumer's boundary. |
| **Data quality over model complexity** | IC Sharpe and FDR correction enforce rigor. Probability spectrum surfaces uncertainty honestly rather than collapsing to a point estimate. |
| **Compounding** | Every bar added to embeddings improves analog retrieval. IC Factory improves with more history. The substrate compounds in value with age. |
