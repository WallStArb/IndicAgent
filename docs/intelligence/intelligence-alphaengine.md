# AlphaEngine — IC-Weighted Factor Model

**Version:** 1.0.0
**Last Updated:** 2026-06-22
**Status:** current
**Milestone:** v3.0

**Companion doc:** `docs/intelligence/intelligence-layer-architecture.md` describes
the same pipeline generically — each layer's contract, separate from IC/HMM/Ledoit-Wolf
as this milestone's specific mechanism for filling it. Read that first if the question
is "what does this layer do," read this doc for "how is it computed today."

---

## The Core Idea

The v2.x intelligence pipeline had a structural flaw that could not be fixed by tuning: researchers encoded hypotheses about what constitutes edge into I5/I6/I7 — named patterns, confluence rules, signal firing conditions. The system could only discover edges the researcher already believed in. Outcomes were only observed for bars the researcher's filter allowed through. 138 plugins produced approximately 15 independent views.

This is confirmation bias with extra steps. The fix is not better plugins. The fix is a different epistemology.

**AlphaEngine** is the name for v3.0's approach. The core idea:

> The researcher produces features. The data discovers confluence. The IC engine arbitrates.

No human defines what feature combinations constitute edge. The ensemble finds it.

---

## What Gets Cut

I5, I6, I7, and the plugin registry are fully archived. No transitional shims, no parallel operation.

| Tier | Status |
|------|--------|
| **I1-I4** | Concepts survive. Implementation is a clean rewrite — 54 pure functions in the Feature Factory, replacing the plugin-based I1-I4 orchestration entirely. |
| **I5** (chart patterns, divergences) | Archived. |
| **I6** (confluence scoring) | Archived. |
| **I7** (signal plugins, signal emission) | Archived. Replaced by threshold crossing on `alpha_score`. |
| **Plugin registry** | Replaced by a typed function library. Adding a feature = schema migration, not a registration. |

The IntelligencePipeline service continues to run every bar in-process, but instead of orchestrating the plugin registry, it calls `compute_features()` from the Feature Factory, which produces a `FeatureVector` (54 typed fields). Nothing from the old plugin implementation carries over.

---

## Vocabulary

### Information Coefficient (IC)

IC is the Spearman rank correlation between a feature value at bar T and the forward return at bar T+N. A feature with IC=0.03 is slightly predictive. IC=0.05 is meaningful. IC=0.10 is exceptional at daily resolution.

IC is not computed once. It is computed per feature, per timeframe, per regime, per lookahead horizon. A feature can have strong IC in trending regimes and zero IC in ranging ones. The IC engine stratifies by HMM regime state so these differences are measured, not averaged away.

**IC Sharpe** (mean IC divided by IC standard deviation over rolling windows) is the primary ensemble weight. It penalizes IC that is high on average but unstable — exactly the features most likely to represent overfitting.

### IC Decay

IC degrades. A feature that was predictive 12 months ago may be arbitraged away, regime-shifted, or seasonally invalid now. The `alpha_decay_monitor` rolls IC over time and writes updated weights to APR. The ensemble reweights continuously without researcher intervention.

### Effective N

Correlated features double-count the same information. A portfolio of 10 features with pairwise correlation 0.9 has effective N ≈ 1.2, not 10. The Correlation Engine measures all pairwise IC correlations among active features and computes `effective_n` — the adjustment denominator in the ensemble. This prevents concentrated bets from appearing diversified.

### Alpha Score

The ensemble output per bar:

```
alpha_score = Σ(normalized_score[f] × ic_sharpe[f][regime]) / effective_n
```

This is a continuous estimate of expected return, regime-conditioned, corrected for feature redundancy. It is not a binary signal. It carries confidence bounds (IC standard error propagated through the ensemble).

When `alpha_score` crosses a per-timeframe threshold, an `alpha_event` is emitted. The threshold is an APR parameter (`alpha.quant.threshold.{tf}`), not a fixed constant — it has no symbol or regime granularity today.

### Feature vs Signal

The vocabulary distinction is deliberate and non-negotiable:

| Term | Meaning |
|------|---------|
| **feature** | A measured quantity derived from price/volume/structure. Has no directional opinion on its own. |
| **IC score** | The measured predictive relationship between a feature and forward return. Empirical, not designed. |
| **alpha_score** | The IC-weighted ensemble across all features for a given bar. A probability estimate. |
| **alpha_event** | An emission when alpha_score crosses threshold. The v3.0 replacement for signal_events. |

There is no "signal" in v3.0. The word is retired. It implied a researcher-defined qualitative judgment about regime. AlphaEngine has no such judgments.

---

## Why Simple Features

Medallion's documented approach is instructive: simple features with positive IC beat complex features with higher in-sample IC because they are more robust. Complex features overfit. A researcher who engineers a feature that "should" predict based on market structure intuition has smuggled their hypothesis back in.

The Feature Factory is built from primitives with two properties:

1. **Known statistical property** — short-term momentum exploits behavioral under-reaction. Range position is a mean-reversion predictor. Informed flow separates overnight positioning from intraday noise. The literature documents why these work.

2. **Near-zero mutual correlation** — each feature measures a different dimension of regime. Correlated features give the appearance of evidence while actually delivering one view.

None of these primitives is individually tradeable. Their IC-weighted combination — conditioned on regime, corrected for effective N — is the edge.

---

## What the IC Engine Replaces

| v2.x component | Why it was wrong | v3.0 replacement |
|---|---|---|
| **I5 patterns** (H&S, divergence) | Binary researcher-defined detection. IC never measured. | Features that capture the same price geometry mathematically |
| **I6 confluence** | Researcher-defined combination rules. "3 of 6 buckets agree" is a hypothesis, not a measurement. | Ensemble: confluence is discovered, not defined |
| **I7 signal plugins** | Firing conditions encode researcher opinion about what constitutes a trade. | Threshold crossing on `alpha_score` (APR parameter, empirically tuned) |
| **CIS / ICC scoring** | Weighted by researcher-assigned bucket weights. Weights change slowly via logistic regression on biased sample. | IC Sharpe: weights derived entirely from forward return correlation |
| **shadow_registry binary promotion** | n>=100 AND bootstrap_ci_lower > 0. Binary gate on a signal that was already selection-biased. | IC gate: feature survives if IC Sharpe is positive at n>=100, measured unconditionally on every bar |
| **setup_performance weights** | 30-day rolling Sharpe on signal outcomes. Conditions on selection-biased sample. | IC decay monitor: rolls IC on the unconditional feature matrix |

---

## The Unconditional Training Set

v2.x trained on signal outcomes — bars where I7 plugins fired. This is selection-biased: the training set is drawn from bars the researcher's filter approved. The model learns to predict performance conditional on the researcher's criteria being met. It cannot find edges the researcher did not look for.

v3.0 trains on `feature_vectors` — every bar, every symbol, every timeframe, produced by the Feature Factory running against raw `market_data_ohlcv`. No firing filter. `forward_returns` computes N-bar returns for every row. IC is measured on this unconditional matrix. The system can find predictive structure the researcher never hypothesized.

The existing `intelligence_features` table (v2.x output) is not used. It was populated with backward-looking Viterbi HMM regime labels, which introduce look-ahead bias — the regime label for a bar used information from future bars. The Feature Factory uses only causal, forward-computed regime state.

This is the most important architectural change. Everything else follows from it.

---

## Regime Conditioning

Every IC estimate is stratified by HMM regime. A feature with IC=0.04 in a trending regime and IC=-0.01 in a ranging regime should not be used in ranging markets. The IC engine computes separate estimates per `regime_state` value. The ensemble applies regime-appropriate weights at inference time.

HMM regime is not a gate. It is a conditioning variable. The distinction matters: gating discards data. Conditioning keeps all data and uses regime state as a stratum label.

---

## Three-Layer Architecture

The v2.x "signal fired" event collapsed three distinct decisions into one. They are now separated absolutely:

```
Layer 0: Data             What actually happened in the market, and is it persisted correctly?
                          → IBKR TWS → Redpanda (hot) → ProviderMerger → market.bars →
                            BarWriter/feature_writer (cold) → TimescaleDB

Layer 1: Prediction       What will happen, and how confident are we?
                          → Feature Factory → IC Engine → Ensemble → alpha_events

Layer 2: Portfolio        Where and when do we act, and at what size?
                          → Kelly sizing, correlation constraints, trade framing

Layer 3: Execution        How do we get filled?
                          → IBKR orders, slippage feedback, fill tracking
```

Layer 0 was previously implicit — described in `CLAUDE.md`'s Data Flow section (Hot/Warm/Cold)
and the DAG Invariants (`ProviderMerger` is the sole writer to `market.bars`), but never given a
layer number alongside Prediction/Portfolio/Execution. Made explicit here so "layer" always means
one of these four, not three-plus-an-implicit-zeroth. Layer 0 is infrastructure, not a research
domain — no IC, no lifecycle governance, no Concept Registry row; its correctness bar is data
integrity (no gaps, no duplicate writes, no silent drops), not statistical proof.

Layer 2 was entirely absent from v2.x. A position size of "one unit" because a signal fired is not portfolio construction — it is the absence of it.

**Not to be confused with** AlphaEngine's own internal Stage 0-4 breakdown (Primitive Measurement
→ Stratification → Edge Measurement → Combination → Emission), which all live *inside* Layer 1
here. See `docs/intelligence/intelligence-layer-architecture.md` and the glossary's `Stage 0`-`Stage 4`
entries. Two numbering schemes, deliberately different words ("Layer" outer, "Stage" inner) so
they're never ambiguous in prose.

---

## Observability and Traceability

### What Carries Forward from v2.x

Every traceability mechanism that exists in v2.x is load-bearing. None is dropped.

| v2.x mechanism | Location | v3.0 status |
|---|---|---|
| **SHA-256 content key** (`signal_id`) | `signal_schema.py:make_signal_id()` | Extended to all new tables - each keyed on its natural identity inputs |
| **Pipeline version stamp** (`pipeline_version`, `signal_schema_version`) | `feature_vectors`, `signal_events` | Mandatory on every new table. `compute_version` stamped per service. |
| **Signal lineage** (`LineageEvent` → `signal_lineage`) | `src/core/ai/lineage.py` | Pattern reused for alpha lineage: which features fired which alpha_events |
| **BaseDaemon mandatory OTel** (5 signals: crash, DLQ, last message, watchdog) | `src/core/agent/base_daemon.py` | All new daemons inherit; all new oneshots emit D-06 `job_completed_total` |
| **BaseWriter DLQ routing** | `src/core/agent/base_writer.py` | All new writers extend BaseWriter; parse failures → `{service}.dlq` topic |
| **Drift detection** (`drift_state`, KS + CUSUM) | migration 030 | Extended to feature distributions: KS per feature column, not just per symbol/tf |
| **Bar gap detection** (`gap_preceding` flag) | `bar_message.py` | Feature gap detection added: coverage gate (≥80% theoretical max per symbol/tf) |
| **4-gate data quality validator** | `src/intelligence/metrics/validator.py` | Equivalent for feature values: degenerate feature detection (std < 1e-8) before IC measurement |

### What v3.0 Adds

**Content-addressed keys on every new table.** Not random UUIDs. SHA-256 of the row's natural identity:

| Table | Key inputs |
|---|---|
| `feature_vectors` | `symbol \| tf \| bar_ts_ns \| pipeline_version` |
| `forward_returns` | `symbol \| tf \| bar_ts_ns \| lookahead_bars` |
| `feature_ic_scores` | `feature_name \| tf \| regime \| lookahead \| engine_version` |
| `alpha_events` | `symbol \| tf \| bar_ts_ns \| ensemble_version` |

Idempotent reprocessing. Duplicate detection without DB round-trips. Same inputs always produce the same key.

**Causal correctness enforcement.** `feature_vectors.regime_label_source` is schema-constrained to `{'filtered', 'unknown'}`. `'filtered'` means causal forward-filter HMM. No `'viterbi_batch'` row can enter the table. The IC engine filters `WHERE regime_label_source = 'filtered'` to exclude unresolvable regime rows. This makes the Viterbi look-ahead mistake structurally impossible.

**IC health as real-time OTel gauges.** IC is not just a batch measurement - it needs continuous monitoring:

```
IC_SCORE_GAUGE           per feature × TF × regime  — is IC decaying?
EFFECTIVE_N_GAUGE        per TF × regime             — is feature set becoming correlated?
FEATURES_SURVIVING_FDR   per TF × regime             — how many features pass BH at α=0.05?
IC_SHARPE_GAUGE          per feature × TF × regime  — IC stability (mean/std)
```

These are point gauges updated at the end of each IC engine run. Grafana alerts fire if `EFFECTIVE_N_GAUGE` drops below a threshold (concentrated bets masquerading as diversification) or if `FEATURES_SURVIVING_FDR` drops sharply (regime shift or data quality event).

**Alpha decomposition on every emission.** `alpha_events.top_features` JSONB stores per-feature score, IC Sharpe weight, and normalized contribution to the final alpha score. `ensemble_version` stores the APR snapshot active at fire time. Every emission is fully auditable.

---

## Base Class Architecture

v2.x established three foundational base classes. v3.0 adds a fourth for the new compute primitive.

```
BaseDaemon                        hot-path streaming (every bar)
  ├── IntelligencePipeline
  └── BaseAlphaEmitter             (Phase C)
       └── EnsembleService

BaseWriter                        Kafka consumer → DB persistence
  ├── FeatureVectorWriter          (Phase 137, exists)
  ├── ForwardReturnWriter          (Phase 138)
  ├── ICScoreWriter                (Phase 138)
  └── AlphaEventWriter             (Phase C)

BaseBatch                 DB → compute → DB, idempotent, versioned
  ├── RegimeWriter                 (Phase 138)
  ├── ForwardReturnLabeler         (Phase 138)
  ├── ICEngine                    (Phase 138)
  ├── CorrelationEngine            (Phase 139)
  └── AlphaDecayMonitor            (Phase B)

BaseAIWorker                      LLM inference (unchanged from v2.x)
```

**SoC invariant:** No class crosses boundaries. `BaseBatch` services never touch Kafka. `BaseWriter` services never compute. `BaseDaemon` services never write to DB directly.

### `BaseBatch` (`src/core/agent/base_batch.py`)

The new primitive. Standardizes what v2.x oneshot services each reimplemented by hand:

```python
class BaseBatch:
    job_name: str          # matches systemd unit suffix; used in D-06 job_completed_total label
    compute_version: str   # bumped when algorithm changes; stamped on every output row

    # Provided to all subclasses:
    async def run(self) -> None            # template method: setup → execute → teardown + D-06 emit
    async def _setup_pool(self)            # asyncpg pool lifecycle
    async def _teardown_pool(self)
    def content_key(self, *parts) -> str   # SHA-256 deterministic row key
    def _emit_completion(self, status)     # D-06 job_completed_total{job, status}

    # Subclass implements:
    @abstractmethod
    async def execute(self, pool: Pool) -> None
```

Every Phase 138 oneshot (`regime_writer`, `forward_return_writer`, `ic_engine`) extends `BaseBatch`. The result: consistent DB pool lifecycle, D-06 emission, error handling, and structured logging across all batch compute services. New batch services in Phase 139+ get the same for free.

---

## Build Sequence

```
Phase A: Measurement Foundation (current)
  0. feature_vectors backfill — Feature Factory runs against market_data_ohlcv (prerequisite)
  1. forward_returns — N-bar forward returns per (symbol, tf, ts)
  2. feature extraction spec — which feature_vectors columns → V1 predictor scores
  3. feature_ic_scores — Spearman IC per feature × TF × regime × lookahead, FDR-corrected
  4. effective_n_scores — pairwise IC correlation → independence adjustment

Phase B: Ensemble
  5. ic_shrinkage — empirical-Bayes IC shrinkage + out-of-fold acceptance gate (may flip
     alpha.ensemble.ic_input to 'ic_shrunk'; live as of 2026-07-15)
  6. ensemble_trainer — feature_ic_scores → ensemble_weights + ensemble_alpha (per-bar alpha score)
  7. EnsembleICEngine — validates the ensemble's own composite output has real IC → alpha_ensemble_ic
  8. alpha_events emission — threshold crossing events
  9. alpha_decay_monitor — rolling IC → APR alpha.weights.* (designed, not yet built)

  Full mechanics (shrinkage math, weight combination methods, the champion/challenger
  promotion gate, and the `concept_registry` table that records which weighting recipe is
  live) are in `intelligence-alphaengine-methodology.md` — not reproduced here.

  Note: this differs slightly from the live nightly corpus pipeline's step order
  (`scripts/ops/corpus/ops_corpus_pipeline_run.sh`, 8 steps: feature_factory →
  regime_writer → forward_return_writer → cross_sectional_regime_model → ic_engine →
  ic_shrinkage → ensemble_trainer → alpha_publisher) — that script is the operational
  sequencing; this list is the conceptual build order.

Phase C: Hot Path (after Phase B IC is validated)
  8. Ensemble in-process (replaces I7 aggregator)
  9. alpha_events replaces signal_events in downstream consumers

Phase D: Portfolio Construction (shadow mode)
  10. Kelly sizing, correlation constraints, VaR, trade framing

Phase E: Live
  11. Live execution after Phase D shadow validates
```

Nothing in Phase C or beyond starts before IC is measured and positive. Shadow mode gates every promotion.

---

## See Also

- **IC + ensemble methodology (canonical, current):** `docs/intelligence/intelligence-alphaengine-methodology.md` — IC estimation, IC shrinkage, weight combination methods, ensemble output validation, weighting recipe governance. Self-contained; no need to read `ensemble_trainer.py`/`ops_ic_shrinkage.py` or historical plan docs to understand how the live ensemble is computed.
- **Live weighting recipe state:** `concept_registry` table, `domain='ensemble_strategy'` — query directly rather than trusting any doc's snapshot of "what's active."
- **Architecture spec (historical):** `docs/plans/2026-06-20-alphaengine-architecture.md` — full design with feature list
- **IC methodology (historical, superseded by the methodology doc above):** `docs/plans/2026-06-20-alphaengine-ic-spec.md`
- **AnalogEngine:** `docs/plans/2026-06-20-analogengine-design.md` — deferred; pgvector similarity search
- **Feature Factory foundation:** `src/intelligence/features/` (Phase A implementation)
- **Prior art:** `docs/research/archive/renaissance-alpha-pipeline.md`
