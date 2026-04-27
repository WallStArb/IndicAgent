# AI Integration Paths

Date: 2026-04-24
Status: Idea — not scheduled

## Key Insight

The wiring is already done. SwarmBaseAgent (Phase 066) provides the base class with DLQ, timeouts, shadow recording, OTel spans. SwarmDispatchService owns the Kafka/pub-sub infrastructure. SkepticAgent proves the pattern — new AI agents just subclass `SwarmBaseAgent`, implement `_compute()`, and register.

I1-I7 results publish to tiered Kafka topics (`intelligence.i{N}`). Any new AI agent subscribes independently — no pipeline modification needed.

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
Since I1-I7 publish to `intelligence.i{N}` topics, dedicated AI consumers could:
- Subscribe to `intelligence.i5` (pattern detection) for pattern confirmation/validation
- Subscribe to `intelligence.i7` (trading signals) for regime-aware filtering
- Subscribe to `intelligence.i6` (confluence) for cross-timeframe consensus scoring

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
