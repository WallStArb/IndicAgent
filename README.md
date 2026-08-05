# IndicAgent

A Renaissance-inspired market intelligence platform, engineered end-to-end to the same proof-before-promotion discipline a quant fund would demand of a full research team. Every decision is measured, every component earns its place through statistical proof, and the system learns from every outcome, winners and counterfactuals alike.

Trading signals are one visible output, not the reason this exists. **The actual goal is a multi-vector intelligence layer built to train AI — with a closed feedback loop where that AI's own learning reaches back into the intelligence layer and improves it:** re-tuning the parameters, computation frequency, and temporal structure that generate the layer in the first place, not just the trading decisions built on top of it. This isn't a new idea bolted on late — self-improvement, promotion, demotion, and decay are the throughline across every layer of both architecture generations, described below: the researcher proposes candidate features and hypotheses, the system itself decides empirically what predicts, and where the loop is fully built out, closes itself — tuning its own machinery rather than waiting for a human to notice and adjust it by hand.

---

## Core Philosophy

Most trading systems are black boxes: rules that fire, signals that vanish into noise, models that degrade silently and nobody notices until the drawdown does. This platform is built on a different premise — a market intelligence system should behave like a scientific instrument: observable, reproducible, and continuously self-auditing.

Two named disciplines govern every design decision here, applied deliberately rather than absorbed by osmosis:

**Renaissance Technologies / Jim Simons — proof before belief.** Nothing gets called "edge" on the strength of a good argument. Every claim survives the same statistical gauntlet (detail below) or it doesn't exist yet. Intuition proposes; measurement disposes.

**Musk's 5-step mandate — question, delete, simplify, accelerate, automate, strictly in that order.** Before any requirement gets engineered around, it gets questioned. Before anything gets optimized, ask whether it should exist at all — don't accelerate a process that should have been deleted, and don't automate a manual step that hasn't been proven worth keeping. This ordering is enforced deliberately, not just referenced: every non-trivial design decision in this system gets run through it before implementation starts.

Two structural commitments follow from combining them:

**Edge is discovered, not designed.** Nothing in this system encodes a human's theory about what confluence looks like or what a good setup is. The pipeline produces candidate features across orthogonal domains; a statistical engine measures which ones actually predict outcomes; an ensemble discovers which combinations matter. The question "who decides what matters here?" has exactly one acceptable answer at every layer: *the data, measured* — never the researcher's intuition.

**Counterfactuals are training data too.** Every candidate the system considers — not just the ones it acts on — gets recorded with its full context and its eventual outcome. A model trained only on what it acted on has never seen what it correctly rejected, which means it can't learn the boundary between the two. This shows up structurally everywhere: the signal ledger records rejected signals, the IC engine measures every feature unconditionally on every bar rather than only on bars a filter approved.

**The intelligence layer is built to improve itself, not just to be consumed.** Promotion, demotion, and decay aren't features bolted onto one component — they're the same governing pattern applied everywhere: a feature, an agent, or a model earns influence through proof (n ≥ 100, positive bootstrap CI) and loses it automatically when its measured edge degrades, with deliberate hysteresis so recovery requires new proof rather than one lucky reading. The substrate this writes back into already exists and is live: every feature's period, computation frequency, and temporal/lookback window is a versioned, hot-reloadable Adaptive Parameter Registry row, not a hardcoded constant — exactly what an automated optimizer needs to act on directly. What's designed to close that loop autonomously (evolving those parameters via automated search rather than a human tuning a lookback window by hand) is eAI, covered in Agent Orchestration below.

**Even classification is a falsifiable hypothesis, not an assumed fact — except where it explicitly isn't.** Every instrument carries tags (71 live today, 983 assignments, weighted, multi-valued, each sourced as human/empirical/AI) describing what it's exposed to — cycle position, macro sensitivity, factor regime. These are hypotheses, subject to the same audit-and-falsify discipline as any predictive feature, and a soft internal taxonomy built by nesting tags inherits that same falsifiability. The one thing deliberately *not* treated this way is an external classification scheme like GICS: sector membership there is a fact to sync from an authority, not a hypothesis to test — and even that gets handled with real care, because a scheme reclassifies securities over time (GICS created an entirely new sector in 2018), so membership is effective-dated rather than treated as a static label. Joining a backtest against today's membership would silently leak future information into the past, the exact same failure mode a Viterbi-decoded regime label produces — one consistent worldview about causal correctness, applied to metadata and to predictive features alike, not two different standards for two different kinds of claim.

---

## Architecture Pillars

**A shared, durable event bus — not services calling services.** Every component publishes typed events to a durable, replayable stream (Redpanda/Kafka-compatible); nothing calls anything else directly. A service going down means messages queue; on restart it resumes from its committed offset. A new consumer — a research notebook, a trading bot, a downstream product — bootstraps by replaying the stream from offset zero. No migration, no special onboarding, no pipeline changes. This is what makes the microservice split real instead of cosmetic: in a conventional system, services call each other via REST or RPC and end up coupled in operation even when decoupled in name. Here the coupling doesn't exist to begin with.

**Deterministic DAG topology, enforced, not assumed.** The service dependency graph is derived by topological sort at startup, not hand-maintained — a circular dependency hard-crashes before any live data flows, rather than silently corrupting downstream state. A short list of invariants holds regardless of which architecture generation is running: exactly one designated writer per table (a single merger process is the sole writer to raw market data — no two services ever race to write the same row), compute stages never touch the database directly (a DB outage can't take down signal generation), every timestamp is UTC with no exceptions, and topic keys are never hardcoded strings. Compute tiers run in-process rather than hopping through the bus between every stage — the bus is a sink for finished output, not a relay between steps of the same computation, which avoids paying a Kafka round-trip N times per bar for an N-tier pipeline. Scaling is driven by measured consumer lag on the bus, not a container-orchestration autoscaler bolted on for its own sake — simpler infrastructure, same elasticity, at this system's actual scale.

**Microservices as real separation of concerns, not just a deployment topology.** Every service does exactly one of three things — compute, persist, or transport — and never two. A compute daemon that discovers something never writes it to the database itself; that always goes through a dedicated writer class built for exactly that job. This isn't a style preference: a service that both computes and persists can't be scaled, tested, or replaced independently, and a bug in its persistence logic corrupts its compute logic's blast radius along with it. Splitting them means either one can fail, restart, or be rewritten without touching the other.

**Data-source agnostic by construction.** The bus doesn't know or care what produced an event. IBKR is today's market-data source, but nothing downstream is written against IBKR specifically — a new provider, or several providers feeding different instruments simultaneously, attaches by publishing to the same typed topics. This same agnosticism is designed to extend across entire *data domains*, not just data vendors within one domain — price/volume today, with institutional positioning, options flow, news sentiment, and fundamentals each designed to plug in later as independent, differently-sourced vectors (detail below). Nothing already running has to change when a new source or domain attaches.

**API-first.** Every signal, feature value, regime classification, and AI narrative is available over standard REST and Server-Sent Events the moment it's computed — no separate reporting layer, no batch export step. Any HTTP client, from a Jupyter notebook to a production trading bot, gets the same intelligence the internal pipeline sees, in real time, with zero effect on pipeline throughput.

**Self-healing and observable by default, not bolted on after an incident.** Every service auto-inherits five mandatory health signals — crash count, dead-letter-queue depth, last-heartbeat timestamp, and watchdog notifications — with zero per-service code required to opt in. A meta-service monitors the full DAG and restarts failed components in dependency order; replay auditors independently detect data gaps and resolve orphaned state without a human paging in at 2am. This is the concrete mechanism behind the "behaves like a scientific instrument" claim above — not an aspiration, an enforced default every new service gets for free.

---

## Intelligence Layers: Two Generations, One Discipline

### Generation 1 (V2) — Event-Driven Real-Time Pipeline

Built and run in production starting early 2026, processing eight analytical tiers end-to-end in under 10ms per bar, live across 60 instruments spanning futures, ETFs, FX, and crypto. Currently dormant — deliberately paused, not decommissioned, to concentrate on Generation 2's more rigorous discovery epistemology before scaling infrastructure further. Full detail: [`docs/architecture/architecture-v2-event-driven-pipeline.md`](docs/architecture/architecture-v2-event-driven-pipeline.md).

| Tier | What it does |
|------|--------------|
| **I1** Raw Indicators | 28 plugins, ~50 data points — RSI, MACD, Bollinger, ATR, VWAP, OFI, CVD, computed incrementally per bar |
| **I2** Composite Events | Second-derivative signals — momentum inflection points and trend-exhaustion scoring *before* they complete |
| **I3** Market Structure | Swing detection, S/R zones, Market Profile (POC/value area), anchored VWAP, session levels |
| **I4** Regime Classification | Six independent statistical models — GARCH (vol regime), Kalman filter (denoised trend), HMM (regime probability distribution), BOCPD (changepoint detection), Hurst exponent (persistence vs. mean-reversion), Shannon entropy (predictability) |
| **I5** Pattern Detection | RSI/MACD/CMF divergence, volatility squeeze, classical chart patterns |
| **I6** Smart Money Concepts + Confluence | Institutional order-flow model — BOS/CHoCH, fair value gaps, order blocks, liquidity pools, aggregated across 6 timeframes |
| **I7** Trading Setups | 36 setups, each a full trade thesis with entry/stop/target, adjudicated by a 6-bucket confluence scorer requiring cross-tier agreement |
| **I8** AI Narrative | Structured LLM analysis of full signal context for every high-confidence signal, plus scheduled cross-asset group synthesis |

**~729 data points computed per bar, per symbol, per timeframe**, every one persisted and streamed live.

Every I7 signal passes through a deterministic 10-stage quality pipeline before it's ever emitted — clamp confidence to a sane range, decay it for autocorrelated re-fires, score it against six confluence buckets, gate it against structural quality and regime alignment, adjust for time-of-day win-rate history, calibrate it against real historical outcomes (isotonic regression, not a hand-picked curve), rank it against other candidates by rolling Sharpe, and run it past the specialist swarm — before a single structural-completeness check confirms nothing required is missing. No stage trusts the previous one's output blindly; each one is independently auditable.

### Generation 2 (V3.0) — AlphaEngine: Statistical Alpha Discovery

The current, active build. V2's flaw wasn't its engineering — it was epistemological: 138 signal plugins encoded 138 human theories about what confluence means, and could only ever discover edges a researcher already believed in. V3.0's answer:

> The researcher proposes feature dimensions. The data validates or rejects each. No human defines which combinations matter — the IC engine measures what predicts, the ensemble discovers what combines.

| Layer | What it does |
|-------|--------------|
| **Feature Factory** | 277 orthogonal feature primitives as of today (growing — Phase 151 is expanding this set right now) across 11 groups (structure, session, volume, volatility, calendar, momentum, regime, and more) — each with a documented statistical rationale, computed unconditionally on every bar, no directional opinion baked in. Every primitive is registry-tiered by construction level: 163 *atomic* (built from raw price/volume alone, no other feature as an input — the clear majority), 106 *theory-derived* (composed from atomic primitives under a stated hypothesis), 8 *interaction* (explicit cross-feature conjunctions) — enforced by a database constraint, not a naming convention |
| **Regime Layer** | Two independent HMM systems: per-symbol idiosyncratic regime (5-state, BIC-validated, causal forward-filter decoding — never Viterbi, which would leak future information) and cross-sectional systematic regime (VIX/breadth-driven market backdrop) |
| **IC Measurement** | Spearman rank correlation between every feature and forward returns, measured per symbol first, then pooled cross-sectionally — walk-forward validated with purge/embargo, FDR-corrected across the multiple-testing problem, weighted by IC Sharpe rather than raw magnitude |
| **Ensemble Combination** | IC-Sharpe-weighted linear combination (live), with a per-feature exposure cap so no single feature dominates. A nonlinear tree-based alternative was built and tested specifically to check for interaction structure a linear model can't express — an instructive result, not a clean win: a data-quality bug initially made it look far stronger than it was, and once corrected, a small but genuinely real residual survived, leaving an open design question about model fit that's actively being worked |
| **Trade Construction** | Two genuinely different constructions tested empirically: per-symbol directional (signal proved real, execution economics didn't hold up) and cross-sectional relative value — ranking the universe and going long/short the extremes, dollar-neutral — which cleared both statistical gates once and is now being re-verified after a data-correctness fix |

Full layer-by-layer detail, including exactly what didn't work and why: [`docs/architecture/architecture-v3-alphaengine-pipeline.md`](docs/architecture/architecture-v3-alphaengine-pipeline.md).

**Price and volume is the first data input vector, not the only one planned.** The system is architected around a broader concept of orthogonal *intelligence vectors* — each an independent, differently-sourced view of the market:

| Vector | Reads | Status |
|--------|-------|--------|
| V1 Quant | Price/volume | **Built — the table above** |
| V2 Microstructure | Order-flow proxies (tick data later) | Partially built |
| V3 Macro | Cross-asset (VIX, yield curve, sector rotation) | Partially built |
| V4 Calendar | Expiry cycles, rebalance windows, time-of-day effects | Built |
| V5 Flow/Positioning | COT, dark pools, short interest | Designed |
| V6 Derivatives/Gamma | GEX, vol surface, VRP | Designed |
| V7 Qualitative | News, sentiment, positioning narrative | Designed |
| V8 Fundamental | Earnings, macro releases, revisions | Designed |

Each vector clears the same bar before entering the live ensemble: no exceptions, no vector gets to skip the IC-measurement gate because it's expensive or exciting.

**Universe: 111 instruments as of today** (growing — a snapshot, not a ceiling), spanning broad-market and sector ETFs through single-name equities across technology, financials, energy, mining, and industrials, backfilled to 20 years of historical depth on the core timeframes. Live trading data isn't required to find edge — historical depth is what IC measurement actually needs, so this corpus is built and validated entirely against historical data before any real-time infrastructure gets switched back on.

---

## Agent Orchestration: Council, Not Oracle

No single model or single agent is ever trusted to make a unilateral call — this holds at every scale in the system, from a single signal's confidence score to how future evolutionary agents will be selected.

**The specialist swarm (built, live in V2).** Five independent specialist agents each assess one analytical dimension of a signal — cross-asset correlation, regime coherence, the counterfactual bear case, historical analog scoring, and a mandatory adversarial skeptic that challenges every other agent's conclusion. Their outputs compose into a calibrated multiplier; no single agent's opinion moves the needle alone, and a swarm without the skeptic collapses into groupthink by design — which is exactly why it's mandatory, not optional. `BaseGroupCoordinator` is the shared dispatcher underneath every agent group (alpha, narrative, risk), and the LLM layer itself is multi-provider (local Ollama on GPU, OpenRouter cloud fallback, per-provider circuit breakers) — no single vendor is a dependency either.

**Head Trader — the missing synthesis role (designed now, not yet built).** Today the swarm produces a confidence multiplier, and downstream application agents (`TradeAgent`, `PortfolioAgent`, `RiskAgent`) each act on their own slice independently — nobody actually owns "make the final call." The Head Trader formalizes that: a synthesis agent that takes the swarm's composite view, portfolio state, and regime context, and issues the actual trade decision — the way a desk's PM synthesizes input from a technician, a risk manager, and a flow trader rather than any one of them acting unilaterally. Critically, `RiskAgent`'s binding halt authority sits *above* the Head Trader, not below it — the Head Trader decides whether to trade, never whether risk limits apply. Same principle real trading desks run on: the PM can't override the risk desk.

**Evolvable AI (eAI) — the swarm's next layer.** The specialist-swarm architecture above — a population of independently-scored agents, shadow-governed, promoted only on proven fitness — is the substrate eAI is designed to evolve autonomously rather than by hand. The concept: seed a population with candidate ideas, auto-backtest each one against historical data with zero human in the loop, select on out-of-sample fitness (not in-sample score), reproduce the survivors via mutation, recombination, or LLM-directed targeted mutation, and repeat across generations until a genome proves out — at which point it's a candidate to seed a live `TradeAgent` or a promoted strategy. This isn't scoped as a generic AI-agent-improvement exercise; the concrete first application is **alpha ideation itself** — using the exact same seed → auto-backtest → select → evolve loop to explore the combination and construction design space described above (which feature-combination approach actually predicts, which construction actually trades) automatically, rather than one human-proposed design at a time. The infrastructure that loop would backtest against — the IC engine, the walk-forward gates, the statistical proof bar — already exists and is already proven; what's designed next is closing the loop so the search itself runs unattended. A concrete first slice (evolving APR parameters specifically, the tractable narrow case before full agent-genome evolution) is already scoped in a written design doc.

---

## Institutional Rigor

Every claim of "edge" in this system has to survive the same gauntlet before it's allowed to matter:

- **Bootstrap confidence intervals, not asymptotic approximations.** A circular block bootstrap, chosen after an empirical calibration check found the standard asymptotic (Fisher-z) assumption measurably wrong on this corpus's real autocorrelation structure — a real bug caught by checking rather than trusting the textbook default.
- **Benjamini-Hochberg FDR correction** wherever multiple hypotheses are tested simultaneously (277 features scored at once, for instance) — without it, some fraction of "significant" results would be chance alone, not signal.
- **Non-overlapping observation windows for stability estimates.** Consecutive bars aren't independent — a 5-bar return at T and T+1 shares 4 bars of the same data. Treating every bar as its own observation silently inflates the effective sample size and understates the true standard error. IC stability is measured on windows that don't overlap, the less convenient but statistically honest way.
- **Walk-forward validation with a purge/embargo window**, sized to the longest forward-return horizon, so no overlapping label ever leaks across a training/test boundary.
- **Automated decay with hysteresis, not a symmetric on/off switch.** When a feature's measured edge degrades, its weight is cut immediately and automatically — no human approval in the loop, because a slow response to real decay bleeds real edge. But recovery is deliberately harder than decay: restoring a cut weight requires a full new block of independent observations proving the edge is back, not just one good reading after a bad streak — otherwise the system would oscillate on noise instead of tracking a real regime change.
- **Shadow governance before any promotion** — n ≥ 100 resolved observations and a positive bootstrap CI at 95% confidence, for every plugin, agent, and feature. Nothing gets promoted on a good-looking p-value alone; automatic demotion triggers on sustained negative expected value.
- **Every parameter is a versioned, provenanced database row** (the Adaptive Parameter Registry) — no hardcoded threshold, weight, or period anywhere in the codebase. Every value that changes gets a `changed_by` and a `reason`, permanently queryable.
- **Drift detection in production** — KS tests and CUSUM control charts watch for feature-distribution and performance drift continuously, not on a quarterly review cycle.
- **Content-addressed identity, not random IDs.** Every row's key is a hash of its own natural identity (symbol, timeframe, bar time, computation version) rather than a random UUID. Reprocessing the same inputs always produces the same key — duplicate detection and idempotent replay come for free, without a database round-trip to check "have I seen this before."
- **Executable returns only.** Forward returns are computed market-on-open-to-market-on-open, never close-to-close — theoretical returns that assume you can trade the closing print overstate edge, especially at short horizons, and this system's IC numbers are never allowed to be inflated that way.

The Renaissance-style question this is all built to answer, ten years from now: *why don't we use this feature/strategy/model anymore?* The answer needs to live in a database row — demotion date, held-out statistic, sample size — not in someone's memory or a deleted conversation.

---

## Keeping a Growing System Legible

Rigor about statistics is worth little if the codebase itself decays into inconsistent naming and duplicate concepts as it grows. Three governance systems, each enforced, not just documented:

**A naming system with a falsifiable invariant, not a style guide.** *The vocabulary IS the model; the model IS the vocabulary* — a name is correct if and only if a domain expert who has never seen the implementation can predict the object's mathematical role, inputs, and output contract from the name alone. Three concrete tests apply it: the **Whiteboard Test** (would a quant immediately understand it, written on a whiteboard), the **Survival Test** (would the name still be true if the implementation were swapped out — an LLM for a neural net, Kafka for another queue), and the **Portability Test** (could this be extracted unchanged into an unrelated system, for foundational infrastructure). One concept name mechanically derives every layer's label — the class name, the service name, the topic name — rather than each layer inventing its own. The whole naming document is designed to be portable: it travels unchanged into a new project alongside the shared infrastructure it governs.

**A single-definition glossary, with a real conflict-resolution rule.** Every domain term has exactly one canonical definition; where two terms could mean the same thing, one is retired. *A term is a mathematical claim — using two terms for the same concept introduces two competing claims, and one is wrong.* When new code and the glossary disagree, the glossary wins, not the code that happens to exist — a real, enforced tie-breaker, not a soft suggestion.

**Concept Registry — one lifecycle-governance system, not a dozen bespoke ones.** V2 grew a sprawl of ad hoc tables, one per governed thing, no shared promotion/demotion schema between them — a real anti-pattern this project hit once and deliberately didn't repeat. Concept Registry unifies feature and ensemble-strategy lifecycle governance under one schema and one service: 279 features and 5 ensemble strategies tracked today, same promotion/demotion/decay discipline as everywhere else in this system, one place to ask "what's live and why" instead of N different tables with N different conventions.

---

## Two More Systems Built in V2

**Empirical Memory — Vector Intelligence Layer.** A pgvector-backed substrate that embeds market and signal context as vectors and retrieves the K most similar historical episodes at query time — grounding AI agent decisions in empirical precedent rather than pattern intuition, the same way a trader draws on lived experience rather than starting cold on every new setup. Real embedding pipeline (768-dimensional, via the same LLM-routing infrastructure every other AI call in the system uses), HNSW-indexed retrieval, a Markov regime-transition model for regime priors, and a statistical-process-control layer watching for drift — all with the same n ≥ 30 promotion discipline as everywhere else in this system before any calibration is trusted. Built in V2, dormant along with the rest of that generation's AI layer.

**The Learning Agent Council — a dedicated ML layer, orchestrated, not a single notebook model.** The same council pattern from Agent Orchestration above, applied to a different question: not "is this signal good," but "what should the model's weights actually be." A real, tested LightGBM training pipeline — walk-forward 60/20/20 temporal split with no shuffling, per-regime segmentation gated at n ≥ 100 observations before a segment is trusted, delta-gated so it skips retraining on insufficient new data rather than overfitting to noise, and every trained model versioned into an MLflow registry. Orchestrated via LangGraph, with data-quality validation and feature discovery (tsfresh extraction, regime-conditional IC) as their own dedicated stages ahead of training. Built in V2, dormant along with the rest of that generation's AI layer.

---

## Current Position

Stated plainly, because the rigor above only means something if it's applied to this project's own claims too, at the resolution that actually matters: **feature-level edge is real and already measured; construction-level, capital-deployable edge is not confirmed yet — and those are different bars, not the same claim stated twice.**

A concrete number, not an assertion: 163 of the 277 feature primitives are atomic — built from raw price/volume alone, no other feature as an input, the registry's own lowest construction tier, and already the clear majority of the corpus. Of the ones measured so far, 102 clear FDR-corrected statistical significance on at least one symbol/timeframe/regime cell, several with walk-forward-validated IC on sample sizes past 100K independent observations — and 40 are already weighted into the live ensemble computation today. That's real, earned statistical edge at the feature level, the exact thing this system exists to measure. The primitive count itself is still growing — a new expansion is landing right now.

What's still open is the harder, more capital-relevant question one layer up: does *combining* those measured features into an actual tradeable construction survive real trading costs and execution constraints? That's a strictly higher bar — proven feature-level IC is necessary but not sufficient for a deployable strategy — and it's the one still gated. The specific open question right now: does the cross-sectional trade construction survive a clean re-measurement after a data-correctness fix to its ranking feature? Both branches of that answer have a defined next step already planned. Live status: [`.planning/STATE.md`](.planning/STATE.md).

---

## Documentation

Docs in `docs/foundation/` and domain folders carry a verification contract: a document marked `Status: current` has had every factual claim traced to a source file, table, or live system state as of the date shown. A wrong claim is treated as corrupted data, not a stale draft.

| Document | Covers |
|----------|--------|
| [Architecture V3.0 — AlphaEngine](docs/architecture/architecture-v3-alphaengine-pipeline.md) | The current architecture, layer by layer, including every place more than one approach was tried |
| [Architecture V2 — Event-Driven Pipeline](docs/architecture/architecture-v2-event-driven-pipeline.md) | The prior, fully-built real-time generation — dormant, not dead |
| [Principles](docs/foundation/principles.md) | The invariants behind every design decision, both generations |
| [Naming System](docs/foundation/naming-system.md) | The falsifiable naming invariant, the three governing tests, mechanical name derivation |
| [Glossary](docs/foundation/glossary.md) | The single-definition controlled vocabulary every term in this system is checked against |
| [Concept Registry](docs/research/concept-unified-registry.md) | Unified feature/strategy lifecycle governance — one system, not a dozen bespoke ones |
| [Adaptive Parameter Registry](docs/foundation/adaptive-parameter-registry.md) | Every tunable value as a versioned DB row — the mechanism, not just the claim |
| [North Star — Intelligence Vectors](docs/foundation/v3-north-star.md) | The full V1-V8 data-vector roadmap and Renaissance invariants |
| [Candidate Edge Theses](docs/research/data-edge-source-thesis.md) | Every trade-construction and signal-extraction idea tried or queued, each falsifiable, with real results |
| [Swarm Intelligence](docs/concepts/swarm-intelligence.md) | The specialist/composite agent pattern in full — how and why it's built the way it is |
| [eAI Design (archived from V2, concept carries forward)](docs/research/archive/ai-03-evolvable-ai-agents.md) | Genome model, reproductive operators, fitness function — the full original design |

### AI Assistant

- [CLAUDE.md](CLAUDE.md) — architecture, commands, conventions, gotchas
