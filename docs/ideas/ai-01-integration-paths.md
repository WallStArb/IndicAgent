# AI Integration Paths

**Version:** 1.0
**Status:** draft
**Priority:** high
**Milestone:** v2.8
**Last Updated:** 2026-05-18
**Tags:** ai, integration, swarm, llm, shadow-mode, kafka, signal-quality

## Key Insight

The wiring is already done. SwarmBaseAgent (Phase 066) provides the base class with DLQ, timeouts, shadow recording, OTel spans. SwarmDispatchService owns the Kafka/pub-sub infrastructure. SkepticAgent proves the pattern — new AI agents just subclass `SwarmBaseAgent`, implement `_compute()`, and register.

Current production contract: I1-I7 results are available through `intelligence.journal`, `intelligence_features`, and `intelligence.i7.signals`. Tiered Kafka topics (`intelligence.i1`, `intelligence.i2`, etc.) are a target architecture, not the current canonical integration path unless they are added to `src/core/stream_keys.py`.

Any new AI agent should subscribe to current canonical topics or read from the feature store first. Add tier-specific streams only when a concrete AI consumer, replay requirement, or scaling bottleneck justifies the extra topic surface.

Shared storage for training data and shadow outputs is fine, but no AI agent should depend on another agent's runtime being available.

## Tier 1: Zero Infra Change (Do Now)

### I8 Prompt Enrichment
Feed richer I1-I7 context into the Ollama/gemma4:e4b narrative prompt: regime state, confluence scores, volume profile position, CTF alignment. The model is already wired; the prompts just need more signal context.

### SkepticAgent Activation
Phase 066 built SwarmDispatchService + SkepticAgent. Already wired to Kafka. If not active, enable it for a second-opinion filter on signal quality before ledger write.

### Simple Outcome Classifier
Weeks of `signal_ledger` + `intelligence_features` data exist. A scikit-learn model (random forest or logistic regression) predicting `outcome` from I1-I7 feature vectors would produce a signal quality score. No deep learning, no GPU.

## Tier 2: Post Data Gate (~May 10, 30+ days clean data)

### LightGBM Signal Scoring
Train on `(I1-I7 features → pnl_r)` with accumulated data. Pluggable into aggregator's `perf_multiplier` chain. This is what Phase 64/70 target.

### Ollama Model Swap
Newer small models with better reasoning drop regularly. Swap is one config line. Evaluate gemma variants or mistral at similar sizes.

### Kafka-Subscribed AI Agents
Dedicated AI consumers can subscribe independently without pipeline modification:
- Subscribe to `intelligence.journal` for full per-bar I1-I7 context.
- Subscribe to `intelligence.i7.signals` for ranked signal candidates.
- Read `intelligence_features` for batch/shadow analysis and model training.
- Use future tier topics (`intelligence.i5`, `intelligence.i6`, etc.) only after those topics exist in `stream_keys.py` and have a documented producer.

Each agent is independent, stateless, and scales by adding consumers.

## Tier 3: Exploration (v2.x+)

### Recurrent-Depth Transformer for I8
Loop the same transformer layers N times at inference — small model (770M), deep reasoning. Fits the hardware constraint (single server). Would need training data and fine-tuning, so depends on ML Foundation (v2.3) completing first.

### Novel Architecture Notes
- RDT (Recurrent-Depth Transformers): scale inference compute, not params
- Prelude/Loop/Coda architecture: small prelude, repeated loop block, small coda
- MoE (Mixture of Experts) at small scale: 384 experts, sparse routing
- All require training infrastructure and labeled data we don't have yet

## Dependency Chain

```
Now:     Prompt enrichment, SkepticAgent activation, simple classifiers
May 10:  LightGBM scoring, model swap, Kafka-subscribed agents
v2.3+:   Novel architectures (RDT, MoE) once ML Foundation is proven
```

## Renaissance Check

- "Data quality over model complexity" — logistic regression on clean data beats transformer on no data
- "Shadow mode first, always" — any AI model runs in shadow before influencing signals
- "Earn the right through proof" — p < 0.05, sufficient N before production promotion
