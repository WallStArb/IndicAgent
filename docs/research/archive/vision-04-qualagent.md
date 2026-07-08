# QualAgent — Qualitative Intelligence Platform (Vision)

**Status:** draft
**Version:** 1.0
**Created:** 2026-03-04
**Last Updated:** 2026-06-17
**Context:** Qualitative intelligence layer — macro, fundamentals, sentiment, positioning, prediction markets
**Priority:** low
**Milestone:** future (post-v2.8)
**Tags:** qualagent, qualitative, macro, sentiment, cot, fundamentals, platform, vision

---

## Purpose of this doc

Capture and develop the vision for **QualAgent**: a **standalone qualitative intelligence platform** that sits alongside IndicAgent (quantitative) in the product family. While IndicAgent answers *"What is the market doing?"* (price, structure, momentum, patterns), QualAgent answers *"Why is it doing it, and what is the context?"* (macro regime, fundamentals, sentiment, news, positioning, catalysts).

This is a vision and ideation document. We are not building yet — we are clarifying scope, identifying the highest-value data sources, and recording ideas so the product can be designed rigorously when the time comes.

---

## Product family

| Product | Role | Status |
|---------|------|--------|
| **IndicAgent** | Quantitative market intelligence: I1–I8 pipeline, indicators, patterns, signals | Live / active development |
| **QualAgent** | Qualitative intelligence: macro, fundamentals, sentiment, news, positioning, prediction markets, alt data | Vision — future build |
| **TradeAgent** | Autonomous trading: consumes IndicAgent + QualAgent signals, manages trade lifecycle, risk, execution | Vision — separate repo |
| **DerivAgent** | Derivatives intelligence: options pricing, vol surface, term structure, GEX, skew, risk-reversal | Vision — separate repo (name confirmed) |

**Key architectural decision:** QualAgent is a **separate application** — not a layer inside IndicAgent. It has its own data ingestion, storage, services, and output streams. IndicAgent's bus is designed to accept optional exogenous inputs (regime signals, confidence modifiers), and QualAgent can publish to that interface; but QualAgent is independently useful without IndicAgent as a consumer.

---

## The Renaissance framing

Jim Simons' core principle: *"We don't start with models. We start with data."* But he also built one of the most rigorous validation frameworks in finance — the vast majority of signals they found were **discarded** unless they were statistically valid and scalable.

QualAgent must be designed with the same discipline:

> **Every data source must answer three questions before it is wired into anything:**
> 1. Can it be **measured** — expressed as a number, score, or categorical state?
> 2. Can it be **validated** — does it show statistically significant lift in backtest, or against a baseline of random noise?
> 3. Can it be **operationalized** — updated systematically, at predictable cadence, without manual intervention?

This is the filter. Not "is this interesting?" but "is this measurable, validated, and operational?" Sources that cannot pass all three stay in the research/monitoring tier until they do.

---

## What QualAgent is NOT

To be precise about scope, especially given the product family:

- **Not a trading execution layer** — that is TradeAgent.
- **Not a derivatives pricing / vol surface engine** — that is DerivAgent. *However*: raw options flow (put/call ratios, net premium) as a **sentiment and positioning signal** belongs in QualAgent. The difference is: QualAgent asks "what is the crowd's positioning telling us about fear/greed/regime?" — DerivAgent asks "what is the vol surface telling us about mispricing and derivative structure?"
- **Not a replacement for IndicAgent's technical pipeline** — it augments and contextualizes it, but the quant signals remain IndicAgent's domain.

---

## Core value propositions

QualAgent delivers value through three distinct mechanisms, which should be developed in sequence:

### 1. Regime and state layer (primary value — build first)

Macro and fundamental context defines *what kind of market we are in*, so the quant pipeline (IndicAgent) can adjust signal weights, gating, and confidence accordingly. This maps directly to IndicAgent's existing I4 regime/context layer as an optional exogenous input.

Examples:
- Prediction market consensus shifts from 40% → 70% probability of rate hike → macro tightening regime activated → VWAP-deviation mean-reversion setups downweighted
- COT data shows commercials aggressively net-long futures → bullish regime bias for trend-following setups
- CPI print surprises consensus by +0.3σ → economic surprise index spikes → volatility regime elevated

**Renaissance alignment:** Principle 8 (state-based, HMM) and Principle 11 (adaptive models). The quant model doesn't change — its parameters adapt by regime state.

### 2. Quantamental alpha sources (validated, measurable edges — build second)

Data sources that independently predict short-term market direction or volatility, validated by backtest before wiring into any live signal path. These must pass the three-question filter above.

**Renaissance alignment:** Principle 1 (data first), Principle 5 (discard unless proven), Principle 9 (alternative data). Only sources with demonstrated lift make it here.

### 3. Human context and narrative layer (AI synthesis — build third)

Rich "why" narratives for operators, traders, and eventually TradeAgent's HITL layer. Earnings call tone, macro backdrop, upcoming catalyst calendar, cross-asset relationships. Primarily human-readable output; feeds TradeAgent's lead agent context window and dashboard panels.

**Renaissance alignment:** Principle 13 (continuous monitoring). Humans need context to make good override / pause decisions without disrupting the systematic logic.

---

## Data sources — tiered Renaissance analysis

Each source is evaluated against: **signal quality for futures**, **measurability**, **validatability**, **operational feasibility**, and **cost**.

---

### Tier 1 — High signal, futures-relevant, statistically validatable

#### COT Reports (CFTC Commitment of Traders)

- **What:** Weekly CFTC report showing positioning of Commercials, Large Speculators (managed money), and Small Speculators in futures markets. Directly covers ES, NQ, and VX instruments IndicAgent trades.
- **Signal logic:** Commercial positions (hedgers) are the "smart money" in futures — they know their underlying business. When commercials are extreme net-long while small specs are extreme net-short, reversals follow historically. This is the "Simons stat-arb" intuition: temporary mispricings created by non-price-motivated actors.
- **Renaissance score:** ✅ Measurable (net positions, net change, Z-score vs history). ✅ Validatable (decades of history; well-studied). ✅ Operational (free, weekly, CFTC API).
- **Cost:** Free (CFTC public data)
- **Implementation:** COT ingestion service → normalize as percentage-of-open-interest Z-scores → publish to QualAgent bus as `positioning:SYMBOL:weekly` → regime modifier for IndicAgent.

#### Economic Surprise Index

- **What:** Services like Citi Economic Surprise Index (CESI) measure whether macro data prints (CPI, NFP, GDP, PMI) are surprising consensus estimates — and by how much. A positive reading means data is consistently beating expectations.
- **Signal logic:** Markets price *change in expectations*, not absolute levels. A market that has been in a negative-surprise regime and flips to positive surprises is a regime shift, not a noise event.
- **Renaissance score:** ✅ Measurable (numerical score, Z-score vs baseline). ✅ Validatable (well-researched; predicts short-term equity/rates direction). ✅ Operational (Bloomberg, Refinitiv, or construct synthetically from public prints vs consensus).
- **Cost:** Free version constructible from public consensus data; Bloomberg for real-time
- **Implementation:** Economic calendar ingestion (consensus estimates) + print data → compute surprise score → publish as macro regime modifier.

#### Prediction Markets (Kalshi, Polymarket)

- **What:** Real-money prediction markets where participants buy/sell contracts on the probability of future events. Kalshi is regulated US (CFTC); Polymarket is decentralized. Covered events: Fed rate decisions, CPI prints, GDP, election outcomes, geopolitical events.
- **Signal logic:** The "price" of a Kalshi contract IS the market's probability estimate — backed by real money, not opinion polls. Compare Kalshi's implied probability to what rates futures are pricing in for the same event, and you have a **macro dislocation signal**. Example: Kalshi prices a 73% chance of a 25bps hike; Fed funds futures imply 60%. That gap is actionable.
- **Why this is Renaissance-grade:** This is exactly the type of alternative, non-price, unconventional data Simons sought. It's measurable (a probability 0–100), it can be compared to market-implied probabilities for dislocation detection, and it updates in real time.
- **Renaissance score:** ✅ Measurable (contract probability, spread to market-implied). ✅ Validatable (events resolve — we can backtest whether prediction market dislocations predicted price moves). ✅ Operational (Kalshi and Polymarket have APIs).
- **Cost:** Free API access (both Kalshi and Polymarket offer public APIs)
- **Key use cases:**
  - Fed decision probability → macro regime state (tightening/easing/neutral)
  - CPI print probability distribution → pre-event volatility regime signal
  - Geopolitical risk → tail-risk regime modifier
  - Dislocation detection: `prediction_market_prob - market_implied_prob` → regime alert when gap exceeds threshold
- **Futures-specific edge:** Index futures (ES, NQ) are acutely sensitive to rate decisions. A prediction market saying the probability of a hike just jumped 20 points is more timely and actionable than waiting for Fed speak to be parsed by a news NLP model.

---

### Tier 2 — Novel, high potential, needs validation

#### Options Flow as Sentiment Signal

> **Important boundary note:** QualAgent uses options flow as a *crowd positioning and sentiment indicator*. DerivAgent will handle deep options analytics (vol surface, term structure, GEX as market-making mechanic, skew, risk-reversal). The distinction: QualAgent asks "are people buying or selling protection?" — DerivAgent asks "what does the structure of volatility tell us about pricing opportunity?"

- **What:** Aggregate put/call ratios on SPX/SPY/QQQ options; net premium (dollar volume of puts vs calls); unusual options activity (large block trades, high IV strikes).
- **Signal logic:** Put/call ratio at extremes (e.g. >1.5 puts/calls) historically precedes reversals — extreme fear is a contrarian buy signal. Net premium flowing into calls signals institutional accumulation. Unusual activity at specific strikes can signal information-driven positioning ahead of events.
- **Renaissance score:** ✅ Measurable (numeric ratios, net premium). ⚠️ Validatable (mixed; requires careful backtesting — not all put/call signals are predictive). ✅ Operational (CBOE public data, or services like Market Chameleon, Unusual Whales API).
- **Cost:** CBOE daily ratios (free); detailed flow data requires subscription

#### Social Sentiment — Honest Renaissance Assessment

- **What:** Reddit (r/wallstreetbets, r/investing), StockTwits, X/Twitter. Measured as bullish/bearish/neutral sentiment, volume of mentions, sentiment momentum.
- **Signal logic for index futures:** Weak to moderate. Individual stocks show stronger social-sentiment effects (meme stocks, short squeezes). For ES and NQ, the crowd's social opinion is a small fraction of what moves the index. However: **sentiment extremes are useful contrarian signals** — when WSB is near-unanimously bullish, that is often a top; extreme fear in retail chatter can mark bottoms.
- **The Renaissance test — honest verdict:** Simons would demand statistical demonstration before wiring this in. For *equities*, social sentiment passes. For *index futures*, the evidence is mixed. Social sentiment for futures may be most useful as a **regime modifier** (is retail overextended? are we in a fear/greed extreme?) rather than a directional predictor.
- **Renaissance score:** ⚠️ Measurable (NLP sentiment scores). ⚠️ Validatable (mixed evidence for futures; strong for individual equities). ✅ Operational (APIs: Reddit API, StockTwits API, X API).
- **Recommended treatment:** Include in QualAgent as a *monitoring and extreme-detection signal* only. Do not wire as a primary alpha source until validated on `signal_ledger` data against outcome history.
- **Cost:** Free tiers available; Reddit API and StockTwits are free with rate limits.

#### News Sentiment (NLP-classified)

- **What:** Financial news headlines (Reuters, Bloomberg RSS, SEC EDGAR filings, earnings PRs) → LLM classification → bullish/bearish/neutral per instrument and per macro topic. Detect sentiment shifts and topic drift (e.g. Fed officials shift from "patient" to "concerned").
- **Signal logic:** Pre-announcement drift; post-announcement overreaction and reversion. Earnings surprise detection. Management tone shifts in transcripts (CEO switches from growth language to cost-cutting language is a leading indicator of guidance cuts).
- **Renaissance score:** ✅ Measurable (classification score, sentiment velocity). ⚠️ Validatable (event-driven signals are well-studied; chronic sentiment less so). ✅ Operational (RSS feeds are free; EDGAR is free; SEC filings are public).
- **Cost:** RSS/EDGAR free; faster feeds (Bloomberg, Refinitiv) require subscription.

---

### Tier 3 — Strategic / longer horizon

#### Corporate Intelligence (SEC Filings + Earnings)

- **What:** Automated parsing of 10-Ks, 10-Qs, earnings call transcripts. Goals: (1) detect earnings date and consensus estimate for catalyst calendar, (2) detect sentiment shifts and management confidence in transcripts, (3) track guidance vs actuals for earnings surprise scoring.
- **Most relevant for:** Individual equities (direct signal), and index-level for earnings season regime detection.
- **Renaissance score:** ✅ Measurable (quantified tone scores, earnings surprise %). ✅ Validatable (earnings surprise effect on price is one of the most well-studied phenomena in finance). ✅ Operational (EDGAR API free).
- **Tech requirement:** RAG pipeline over PDFs; LLM for tone extraction; structured earnings calendar.

#### Knowledge Graph (Relationship Intelligence)

- **What:** A graph database (e.g. Neo4j) mapping entity relationships: company → suppliers → customers → geographies → macro sensitivities. Example: port closure in Shanghai → instantly surface US retailers with highest supply-chain exposure → proxy futures basket.
- **Why it matters:** Price data is blind to these structural relationships until they show up in earnings. The graph sees them first.
- **Renaissance score:** ✅ Measurable (relationship strength, exposure scores). ⚠️ Validatable (hard to backtest relationship-graph-derived signals without historical graph data). ⚠️ Operational (high build cost; Neo4j requires dedicated infrastructure).
- **Recommendation:** Deferred. High value but high cost and complex. Design the data model now; build later.

#### Alternative Data (Satellite, Shipping, Credit Card)

- **What:** Satellite imagery of retail parking lots and oil tank levels; shipping manifest data for supply chain; credit card transaction aggregates for consumer spending.
- **Why it matters:** These signals predict economic data *before* the official prints — the original "alternative data" vision.
- **Renaissance score:** ✅ Measurable. ✅ Validatable (well-studied in quant hedge funds). ❌ Operational for now (high cost — providers charge $10k–$100k+/year; only worth it at larger AUM scale).
- **Recommendation:** Vision item. Include in architecture design as a data connector placeholder. Build when revenue/AUM justifies the data cost.

#### Geopolitical Risk Index (GPR)

- **What:** The Geopolitical Risk Index (Caldara & Iacoviello, now published by the Fed) quantifies geopolitical risk from news article frequency. Spikes in GPR historically precede equity drawdowns and volatility regime changes.
- **Renaissance score:** ✅ Measurable (numerical index). ✅ Validatable (published academic research showing predictive power for asset prices). ✅ Operational (free, public).
- **Recommendation:** Low-hanging fruit. Easy to ingest, directly usable as a macro tail-risk modifier.

---

## The quantamental bridge

This is where QualAgent's highest-value, most differentiated work happens — the intersection of qualitative regime intelligence and quantitative signal execution. Three mechanisms:

### Regime detection and quant weight adjustment

QualAgent publishes a **macro regime state** (e.g. `{regime: "tightening_cycle", confidence: 0.82, drivers: ["cot_commercial_extreme", "prediction_market_rate_hike_73pct", "economic_surprise_negative"]}`) to an output stream. IndicAgent's I4 or aggregator layer reads this as an optional exogenous input and adjusts signal weights accordingly.

This is the Jim Simons Principle 8 (state-based, HMM) applied to qualitative data: the quant model stays constant, but it knows what state it is operating in.

### Catalyst calendar and pre-event gating

QualAgent maintains a forward-looking calendar of macro and corporate catalysts (Fed meetings, CPI/PCE release dates, earnings, major option expiries). Before a high-impact event, it publishes a pre-event risk flag. IndicAgent can use this to reduce position sizing or gate new signals in the hours before the event.

This is signal validation (Principle 5) applied temporally — avoid new positions when outcome uncertainty is maximally high.

### Fundamental backtesting (regime-specific performance)

An offline research capability: given a set of IndicAgent's `signal_ledger` outcomes, segment performance by QualAgent regime labels (e.g. "how did VWAP-deviation setups perform specifically during COT-extreme-short regimes vs normal regimes?"). This allows regime-conditional strategy evaluation — a capability no pure-quant backtester can provide.

---

## Architecture overview (standalone application)

QualAgent is its own application with its own services, storage, and API. It publishes outputs that IndicAgent and TradeAgent can optionally consume.

### Services

| Service | Responsibility |
|---------|----------------|
| **Ingestion service(s)** | Pull from COT, Kalshi/Polymarket, news RSS, EDGAR, CBOE, social APIs. Normalize, deduplicate, store. |
| **Regime engine** | Aggregate ingested signals into regime states. Publish `regime:MACRO`, `regime:POSITIONING`, `regime:SENTIMENT` streams. |
| **Catalyst calendar** | Maintain forward-looking event calendar. Publish pre-event flags. |
| **NLP / LLM pipeline** | Classify news/transcripts. Detect topic drift. Produce sentiment scores. |
| **RAG service** | Index and query SEC filings / earnings transcripts via vector DB. |
| **Synthesis agent** | LLM orchestrator: combines regime, sentiment, catalyst, and corporate signals into a narrative. |
| **API / output** | REST + SSE endpoints. Consumed by TradeAgent, IndicAgent (optional), and dashboards. |

### Storage tiers

| Tier | Technology | Purpose |
|------|-----------|---------|
| **Time series** | TimescaleDB (shared or own instance) | Numeric signals: COT positions, sentiment scores, surprise indices over time |
| **Document store** | PostgreSQL JSONB or dedicated doc store | News articles, classified headlines, filing summaries |
| **Vector DB** | pgvector (PostgreSQL extension) or Qdrant | RAG embeddings for SEC filings / earnings transcripts |
| **Graph DB** | Neo4j (deferred) | Entity relationships (supply chain, sector, geography) |
| **Cache / streams** | Redpanda (stream) / Redis (cache) | Output stream publishing; hot cache for regime state |

### Output streams (published by QualAgent)

| Stream | Contents | Consumers |
|--------|----------|-----------|
| `qual:regime:macro` | Current macro regime state + confidence + drivers | IndicAgent I4, TradeAgent lead agent |
| `qual:regime:positioning` | COT extremes, options flow sentiment | IndicAgent aggregator, TradeAgent risk agent |
| `qual:regime:sentiment` | News/social sentiment aggregate | IndicAgent I8 narrative, TradeAgent lead agent |
| `qual:catalyst:upcoming` | Next N calendar events + impact tier | IndicAgent pre-event gating, TradeAgent sizing |
| `qual:surprise:econ` | Economic surprise index, latest print delta | IndicAgent regime, TradeAgent risk |
| `qual:narrative:SYMBOL` | LLM-synthesized qualitative narrative | Dashboard, TradeAgent HITL context |
| `qual:prediction:EVENT` | Prediction market probabilities + dislocation score | Macro regime, TradeAgent lead agent |

---

## Proposed development structure (revised)

### Phase A: Macro regime foundation

Build the data-first regime layer with the three highest-confidence, lowest-cost sources:

1. **COT ingestion** — weekly CFTC data → normalized Z-scores → `qual:regime:positioning`
2. **Economic surprise index** — calendar + consensus + actuals → surprise score → `qual:regime:macro`
3. **Geopolitical risk index** — public GPR feed → tail-risk modifier

*Success criterion:* IndicAgent's I4 regime layer can optionally read `qual:regime:macro` and adjust signal confidence. Validate: do signals in high-GPR / negative-surprise / commercial-extreme periods have statistically different win rates?

### Phase B: Prediction markets intelligence

1. **Kalshi + Polymarket ingestion** — real-time probability feeds → `qual:prediction:EVENT`
2. **Dislocation detector** — compute gap between prediction market probability and market-implied probability for same event
3. **Pre-event gating signal** — publish high-impact events to `qual:catalyst:upcoming`

*Success criterion:* Prediction market dislocation signals can be backtested against event-day price moves to validate predictive lift.

### Phase C: Sentiment layer

1. **News NLP pipeline** — RSS ingestion → LLM classification → `qual:regime:sentiment`
2. **Options flow positioning** — CBOE put/call ratios, net premium → extreme detection → regime modifier
3. **Social sentiment monitoring** — Reddit/StockTwits → extreme sentiment detection only (not primary signal until validated)

*Success criterion:* Sentiment extremes (social + put/call) can be validated against `signal_ledger` outcomes from IndicAgent. Are mean-reversion signals more profitable at sentiment extremes?

### Phase D: Corporate and fundamental intelligence

1. **Earnings calendar** — upcoming earnings dates + consensus estimates
2. **Earnings surprise tracker** — actuals vs consensus → surprise score → I8 / narrative
3. **SEC filing RAG pipeline** — 10-K/10-Q/transcript ingestion → vector DB → topic drift and tone extraction

*Success criterion:* Earnings surprise signals can be validated. LLM tone extraction from transcripts detects shifts that precede guidance cuts.

### Phase E: Synthesis and TradeAgent integration

1. **Regime synthesis agent** — LLM orchestrator combining all qual signals into a structured context object
2. **TradeAgent API** — structured context endpoint for lead agent's context window
3. **Fundamental backtesting** — regime-conditional performance analysis of IndicAgent setups

---

## Agent suite

| Agent | Role |
|-------|------|
| **Ingestion agents** | Per-source workers (COT, Kalshi, news RSS, EDGAR, CBOE). Each is independently deployable and failure-isolated. |
| **Regime agent** | Aggregates signals into regime state. Responsible for `qual:regime:*` streams. Runs on cadence matching source update frequency. |
| **Catalyst agent** | Maintains event calendar. Publishes pre-event flags. Monitors for unexpected high-impact events. |
| **NLP / sentiment agent** | Classifies news and social signals. Runs continuously or on publication-triggered cadence. |
| **RAG / document agent** | Indexes filings. Responds to queries. Detects topic drift in long-form documents. |
| **Prediction markets agent** | Monitors Kalshi/Polymarket. Computes dislocation scores. Publishes to `qual:prediction:*`. |
| **Synthesis agent** | LLM orchestrator. Combines all signals into a human-readable narrative and structured context object. |
| **Research agent** | Offline: pattern mining on `signal_ledger` × `qual:regime:*` history. Validates lift claims. |

---

## Renaissance-grade validation framework

Before any QualAgent data source is promoted to a live signal path (i.e., published to IndicAgent or TradeAgent as anything other than informational), it must pass:

| Gate | Requirement |
|------|-------------|
| **Sample size** | Minimum N events (e.g. ≥50 regime periods, ≥100 signal instances) |
| **Statistical significance** | p < 0.05 on lift vs random baseline |
| **Signal stability** | Consistent performance across sub-periods (not a single-period artifact) |
| **Operational reliability** | Source updates at claimed cadence; failure modes handled; no silent staleness |
| **Cost justification** | If paid source: demonstrated lift justifies cost at current trading scale |

Sources that do not pass stay in the monitoring tier — they are ingested and stored but not wired into any signal path. This is "discard unless proven" (Principle 5) applied to qualitative data.

---

## Boundary: QualAgent vs DerivAgent

As the product family grows, this boundary matters:

| Signal type | Lives in |
|-------------|----------|
| Put/call ratios as crowd sentiment | **QualAgent** |
| Net options premium as positioning signal | **QualAgent** |
| Volatility surface and term structure | **DerivAgent** |
| GEX (Gamma Exposure) as market-making mechanic | **DerivAgent** |
| Skew, risk-reversal, vol spread trades | **DerivAgent** |
| Implied volatility regime (IV rank/percentile) | **DerivAgent** (but may publish regime flag to QualAgent bus) |

The conceptual split: QualAgent uses options data to understand *crowd behavior and regime*. DerivAgent uses options data to understand *derivative pricing structure*.

---

## Open questions (active)

1. **Bus architecture:** Does QualAgent publish to its own Redpanda instance, or to a shared bus? The regime stream interface to IndicAgent needs to be defined (probably a thin API / shared stream key, not a full stream consumer relationship).
2. **LLM provider:** QualAgent will need LLM calls for NLP classification and synthesis. Use LiteLLM + OpenRouter (as per user rules) — which models? Larger context window models for SEC filing RAG.
3. **Update cadences:** COT = weekly; economic surprise = per-print (8–10x/month); prediction markets = real-time; news = continuous; social = continuous. These require different service architectures. A unified scheduler (e.g. Celery beat or APScheduler) vs per-source daemons.
4. **First data source to validate:** COT is the most directly relevant, free, and well-understood for futures. Prediction markets are the most novel and potentially highest-alpha. Which goes first in Phase A?
5. **Backtest infrastructure:** Regime-conditional backtesting requires `signal_ledger` outcomes from IndicAgent × `qual:regime:*` history. Does this run in QualAgent or as a shared offline research tool?
6. **Primary consumer (near term):** Before TradeAgent exists, who benefits from QualAgent output? The IndicAgent AI narrative (I8) could consume a qualitative context object as an additional input. The dashboard can surface regime state. These should drive Phase A design.

---

## The quantamental feedback loop — deep architecture

This is the "Medallion secret sauce" equivalent for the platform. Not a single insight but a **compounding system**: the more signals the platform generates, the more outcome data accumulates, the better the qual weights become, the more precisely the system knows which qualitative context actually predicts performance on *these instruments*, in *this time period*, with *this exact setup suite*.

### The join: `signal_ledger` × `qual:regime:history`

The core data operation that makes the loop possible. For every resolved signal in `signal_ledger`, we need to know: what was the qualitative regime state during the period this signal was active?

**signal_ledger schema (IndicAgent):**
```
signal_id, symbol, timeframe, setup_type,
entry_ts, exit_ts, outcome (win/loss/breakeven),
pnl_r, mae, mfe, confidence_at_entry
```

**qual:regime:history (QualAgent — stored in TimescaleDB):**
```
ts, macro_regime, macro_confidence,
positioning_regime, positioning_z_score,
sentiment_regime, sentiment_velocity,
qual_score, transition_probability,
prediction_market_dislocation,
economic_surprise_index,
cot_commercial_z_score,
crowding_score
```

**The join:** For each signal, find the qual regime snapshot that was active at `entry_ts`. The regime state at the moment the signal was taken is what gets attributed to the outcome. Not the regime at exit (that could be influenced by the trade itself), and not an average over the trade's lifetime (too noisy) — the regime when the decision was made.

```
enriched_signal = JOIN signal_ledger ON qual_history
WHERE qual_history.ts = (
  SELECT MAX(ts) FROM qual_history
  WHERE ts <= signal_ledger.entry_ts
)
```

This produces a table of every historical signal with its concurrent qual regime state. This is the training dataset for the feedback loop.

### Computing lift — what actually improves win rates

With the enriched signal table, compute **conditional win rates** for each qual signal component:

```
For each qual component X (e.g. cot_commercial_z_score):
  For each state bucket S (e.g. "extreme_long" / "neutral" / "extreme_short"):

    baseline_win_rate = wins / total (all signals)
    conditional_win_rate = wins / total (where X is in state S)
    lift = conditional_win_rate - baseline_win_rate
    n = number of signals in that condition

    statistical test:
      chi-squared or Fisher's exact for win rate difference
      t-test or Mann-Whitney U for pnl_r distribution difference
      p-value < 0.05 required; ideally < 0.01 with N > 100
```

**Lift, not just correlation.** The question is not "are qual signals correlated with outcomes?" — it is "when this qual signal is in this state, do IndicAgent signals produce *better* outcomes than they do on average?" Lift is the incremental contribution.

**Stability requirement:** The lift must be consistent across rolling sub-periods, not a single-period artifact. Compute lift in:
- The full historical window
- 12-month sub-windows
- By market regime (trending vs range)

If lift is significant overall but zero or negative in two of three sub-periods, it is suspect — probably an overfitted coincidence.

### Preventing overfitting — the discipline layer

This is where most "adaptive" systems fail. The feedback loop must be built with these hard constraints:

| Constraint | Rule |
|-----------|------|
| **Minimum sample size** | No weight update until N ≥ 100 signals in a given condition |
| **Holdout validation** | Last 20% of the history window is never used for training — only for out-of-sample validation |
| **Maximum weight delta** | Per update cycle, a weight can move at most ±15% of its current value — prevents large swings from small-sample noise |
| **Stability gate** | Lift must be directionally consistent in at least 2 of 3 sub-period splits |
| **Version control** | Every weight update is a versioned record: `{update_id, date, window_used, holdout_lift, weights_before, weights_after, approval_status}` |
| **Manual review flag** | Any weight change > 10% in a single update cycle is flagged for human review before going live |

The last point is important — this is the "never fully automatic" rule. The loop accelerates learning; humans approve the learning before it goes live. This mirrors how Renaissance managed model updates: the system suggests, the researchers validate, the change is committed.

### Signal promotion and demotion protocol

Every qualitative data source moves through a formal tier system. Transitions require evidence, not just interest.

```
Tier 0: Hypothesis
  → Ingested and stored, but not computed or published
  → Condition to promote: initial exploratory analysis shows non-trivial signal structure

Tier 1: Monitoring
  → Computed and stored internally; not included in QualScore
  → Condition to promote: sufficient history accumulated (N ≥ 50 events), 
    correlation with outcome observed but not yet validated

Tier 2: Research validation
  → Full lift analysis run; statistical tests performed
  → Condition to promote: p < 0.05 on lift vs baseline, stable across sub-periods
  → Condition to stay: borderline significance; continue accumulating data
  → Condition to demote back to Tier 0: consistently negative or zero lift

Tier 3: Live (included in QualScore)
  → Active component with assigned weight
  → Continuous alpha decay monitoring via rolling 90-day lift
  → Condition to demote to Tier 2: rolling lift drops below 50% of initial validated lift
  → Condition to demote to Monitoring: lift consistently negative for 2+ rolling windows
```

This is "discard unless proven" (Renaissance Principle 5) operationalized as a formal protocol, not just a principle. Each transition generates a record. The system maintains institutional memory of why signals were promoted, how they performed, and what caused any demotion.

### Weight update mechanism

**Initial weights: analytically set.** Before any data is collected, define a prior based on what we *believe* each component contributes. Example:

```
v1.0 initial weights (analytical prior):
  cot_commercial_z_score:      0.25  (strong prior: institutional positioning for futures)
  prediction_market_dislocn:   0.20  (strong prior: novel, futures-event linkage)
  economic_surprise_index:     0.15  (moderate prior: macro regime signal)
  sentiment_velocity:          0.15  (moderate prior: narrative momentum)
  crowding_score:              0.15  (moderate prior: fragility signal)
  geopolitical_risk_index:     0.10  (weak prior: tail risk only)
```

This is the starting point. It reflects our qualitative judgment before outcomes prove or disprove it. Version this belief. When the data disagrees, the weight shifts — and we document what the data said.

**Update rule:** Weighted average of prior and data-derived optimal weight:

```
new_weight = α × data_derived_weight + (1 - α) × prior_weight
```

Where `α` = confidence in the data (function of sample size and stability). When N is small, α is low and the prior dominates. As N grows and stability is confirmed, α increases and the data takes over. This is Bayesian updating applied to signal weights.

**Update cadence:** Monthly. This balances responsiveness with stability — weekly is too reactive to noise; quarterly is too slow to adapt.

### The compounding mechanism

This is the key insight that makes the feedback loop more than just an engineering exercise. Each improvement compounds:

1. Better QualScore → TradeAgent takes higher-quality setups → better outcomes
2. Better outcomes → more signal_ledger data with favorable qual conditions → more statistical power for weight updates
3. Higher statistical power → more precisely calibrated weights → QualScore is more predictive
4. More instruments in IndicAgent → more signals in signal_ledger → broader coverage for conditional analysis → better regime segmentation
5. DerivAgent gamma regime catches risk that QualScore misses → saves losing trades → those outcomes feed back as "qual-state-X is not sufficient when gamma is negative"

This is Renaissance Principle 6 (unified model improvements compound) applied across the entire product family. The system gets smarter about itself — not through manual tuning, but through structured outcome learning.

---

## Product family integration — the complete picture

The four products are designed to be **independently useful** but **exponentially more powerful together**. This section describes the full integration architecture: every interface, every data flow, and how the synthesis happens at the TradeAgent decision point.

### Independence guarantee

A critical design constraint:

| Platform | Works without | Degrades without |
|----------|--------------|-----------------|
| **IndicAgent** | All others | Nothing — it is the foundation |
| **QualAgent** | IndicAgent, DerivAgent, TradeAgent | No feedback loop (needs signal_ledger), no trading context |
| **DerivAgent** | All others | No regime coordination with QualAgent |
| **TradeAgent** | QualAgent, DerivAgent | Signal quality unchanged; context richness reduced; sizing less precise |

Consumers can adopt incrementally. A trader using TradeAgent with only IndicAgent connected gets a capable automated system. Adding QualAgent improves regime-awareness. Adding DerivAgent improves volatility-adjusted sizing. The full four-platform integration is the institutional-grade configuration.

### Complete data flow diagram

```
═══════════════════════════════════════════════════════════════════
EXTERNAL DATA SOURCES
═══════════════════════════════════════════════════════════════════

  ┌─────────────┐  ┌──────────────┐  ┌─────────────────────────┐
  │  IBKR TWS   │  │ CFTC / COT   │  │ Kalshi / Polymarket     │
  │ (tick bars) │  │ (weekly)     │  │ (real-time probability) │
  └──────┬──────┘  └──────┬───────┘  └────────────┬────────────┘
         │                │                        │
  ┌──────▼──────┐  ┌──────▼───────┐  ┌────────────▼────────────┐
  │ News RSS    │  │ Economic     │  │ CBOE Options Flow       │
  │ EDGAR SEC   │  │ Calendar     │  │ (put/call, net premium) │
  │ Social APIs │  │ (CPI/NFP/Fed)│  │                         │
  └──────┬──────┘  └──────┬───────┘  └────────────┬────────────┘
         │                │                        │
         └────────────────┴────────────────────────┘
                          │
═══════════════════════════════════════════════════════════════════
LAYER 1: INDICAGENT (Quantitative)       [Live — separate repo]
═══════════════════════════════════════════════════════════════════
         │
  ┌──────▼───────────────────────────────────────────────────┐
  │  TWS Daemon → indicator_service (I1: 23 plugins)         │
  │  → market_analysis (I3→I6) → signal_generator (I7)       │
  │  → signal_lifecycle → feature_writer → intelligence_bus  │
  │  → AI narrative (I8, optional QualAgent context)         │
  └──────────────────────────────────────────────────────────┘
         │ publishes                          │ reads (optional)
         ▼                                    ▼
  signals:SYMBOL:TF:aggregated        qual:context:SYMBOL (from QualAgent)
  intelligence:SYMBOL:TF              qual:regime:macro
  signal_ledger (TimescaleDB)         qual:score:SYMBOL
  intelligence_features (TimescaleDB) qual:catalyst:upcoming

═══════════════════════════════════════════════════════════════════
LAYER 2A: QUALAGENT (Qualitative)        [Future — separate repo]
═══════════════════════════════════════════════════════════════════

  ┌──────────────────────────────────────────────────────────┐
  │  Ingestion daemons (COT, Kalshi, news, EDGAR, CBOE)      │
  │  → Regime engine → NLP pipeline → RAG service            │
  │  → Synthesis agent → Research scheduler (feedback loop)  │
  └──────────────────────────────────────────────────────────┘
         │ publishes                          │ reads
         ▼                                    ▼
  qual:regime:macro                   signal_ledger (batch, weekly)
  qual:regime:positioning             deriv:regime:gamma_env
  qual:regime:sentiment               deriv:vrp:current
  qual:score:SYMBOL (QualScore 0-100) deriv:skew:percentile
  qual:catalyst:upcoming
  qual:prediction:EVENT
  qual:narrative:SYMBOL
  qual:analog:current

═══════════════════════════════════════════════════════════════════
LAYER 2B: DERIVAGENT (Derivatives)       [Future — separate repo]
═══════════════════════════════════════════════════════════════════

  ┌──────────────────────────────────────────────────────────┐
  │  Options data ingestion (CBOE/OPRA)                      │
  │  → Vol surface construction → GEX computation            │
  │  → VANNA/CHARM flow → VRP tracking → Skew/term structure │
  └──────────────────────────────────────────────────────────┘
         │ publishes                          │ reads
         ▼                                    ▼
  deriv:regime:gamma_env              qual:regime:macro (macro context)
  deriv:vrp:current                   qual:score:SYMBOL (sentiment)
  deriv:skew:percentile               signal_ledger (for VRP backtest)
  deriv:term_structure:shape
  deriv:expiry:next_major
  deriv:gex:levels

═══════════════════════════════════════════════════════════════════
LAYER 3: TRADEAGENT (Execution)          [Future — separate repo]
═══════════════════════════════════════════════════════════════════

  ┌──────────────────────────────────────────────────────────┐
  │  Lead agent (LLM) receives full context object:          │
  │  IndicAgent signal + QualScore + DerivAgent gamma +      │
  │  pre-event flags + current positions + risk budget       │
  │                                                          │
  │  → Synthesis → Lifecycle → Risk management               │
  │  → Portfolio optimizer → Learning agent                  │
  └──────────────────────────────────────────────────────────┘
         │ reads                              │ publishes
         ▼                                    ▼
  signals:SYMBOL:TF:aggregated        orders → broker adapters
  qual:score:SYMBOL                   trade_outcomes → signal_ledger
  deriv:regime:gamma_env              (closes the compounding loop)
  qual:catalyst:upcoming
  qual:narrative:SYMBOL (HITL context)
```

### The synthesis moment — TradeAgent's lead agent context window

This is the most important decision point in the entire platform. When TradeAgent's lead agent evaluates whether to take a signal, it has access to:

```json
{
  "signal": {
    "setup_type": "vwap_deviation_long",
    "symbol": "ES",
    "timeframe": "5m",
    "confluence_score": 0.74,
    "entry_level": 5241.50,
    "stop_level": 5238.25,
    "target_level": 5248.00,
    "expected_rr": 2.0
  },
  "qual_context": {
    "qual_score": 71,
    "qual_bias": "bullish",
    "top_drivers": [
      "cot_commercial_extreme_long (z=+2.3)",
      "prediction_market_fed_pause_68pct (vs 55pct implied)",
      "economic_surprise_recovering (+0.4 this week)"
    ],
    "macro_regime": "transition",
    "transition_probability_7d": 0.38,
    "crowding_score": 0.22,
    "narrative_analog": {
      "best_match": "Q1_2016",
      "similarity": 0.83,
      "fwd_10d_median": "+1.8%",
      "fwd_10d_p20": "-1.2%",
      "fwd_10d_p80": "+4.1%"
    }
  },
  "deriv_context": {
    "gamma_environment": "positive",
    "gex_level": "+2.3B",
    "nearest_pin_strike": 5245,
    "vrp_percentile": 62,
    "skew_percentile": 38,
    "term_structure": "contango"
  },
  "catalyst_context": {
    "pre_event_flag": true,
    "next_event": "CPI_print",
    "event_ts": "2026-03-12T13:30:00Z",
    "hours_until": 18.5
  },
  "portfolio_context": {
    "daily_pnl_r": +1.4,
    "daily_drawdown_pct": 0.0,
    "open_positions": 0,
    "available_risk_budget": "100%"
  }
}
```

The lead agent produces:

```json
{
  "decision": "TAKE",
  "size_multiplier": 0.65,
  "reasoning": "VWAP deviation long with 74% confluence. QualScore 71 (bullish) — COT commercial extreme and prediction market dislocation on Fed pause both supportive. Positive gamma environment supports mean-reversion thesis. Pre-event flag active (CPI in 18.5h) — sizing reduced 35% from full allocation. Transition probability moderate at 38%; acceptable. Narrative analog Q1 2016 (83% similarity): median +1.8% forward 10 days. Taking at 65% normal size."
}
```

No retail trader has access to this level of integrated reasoning. No institutional trader produces it this quickly and consistently. This is the product.

### Interface specifications (preliminary)

The four platforms communicate through well-defined interfaces. These are design principles, not final specs:

| Interface | Protocol | Direction | Latency requirement |
|-----------|----------|-----------|-------------------|
| IndicAgent → TradeAgent | SSE stream + REST | Real-time signals | < 100ms |
| QualAgent → TradeAgent | REST API (polling or webhook) | Regime state, QualScore | < 1s acceptable |
| QualAgent → IndicAgent | Shared Redis key | Regime state only | < 5s acceptable |
| DerivAgent → TradeAgent | REST API | Gamma regime, VRP | < 1s acceptable |
| DerivAgent → QualAgent | Redis key / REST | IV regime flag | < 5s acceptable |
| signal_ledger → QualAgent | Batch SQL read | Feedback loop | Weekly, async |
| TradeAgent → Brokers | Order API | Execution | < 50ms target |

**Principle:** Each platform is a black box to the others. They communicate only through published interfaces. IndicAgent doesn't know if QualAgent is running. QualAgent doesn't know what TradeAgent does with its QualScore. This clean separation means any platform can be upgraded, replaced, or versioned independently without breaking the others.

### Commercial evolution — from IndicAgent SaaS to intelligence platform

The existing commercialization vision (in `docs/research/commercialization-retail-saas.md`) describes a solid IndicAgent SaaS product. With the expanded product family, the commercial story changes substantially.

**Phase 1 — IndicAgent SaaS (existing plan):** Shared-brain quant signals, tiered subscriptions, CIS-gated premium. Good unit economics. The data licensing change (IBKR → Databento) is the blocker. This plan stands as written.

**Phase 2 — QualAgent context layer (add-on):** QualScore and regime context become a premium subscription upgrade. "Pro +" or "Intelligence" tier. The God View dashboard — IndicAgent signals + QualScore regime + narrative analog — is the killer feature that no competitor offers. Price point: $199–399/mo.

**Phase 3 — DerivAgent overlay (specialist tier):** Options-aware subscribers (prop traders, options traders using futures for hedges) pay for gamma regime awareness and vol surface intelligence. "Derivatives" tier. Price point: $299–599/mo.

**Phase 4 — TradeAgent (execution layer):** Automated trading as a service. This is a fundamentally different commercial model — not a data/intelligence product but an autonomous trading product. Higher compliance complexity, higher liability, much higher value. Subscription + performance fee model for later-stage offering.

**The platform play:** The moat is not any individual signal or dataset. It is the **integration and compounding**. The QualScore gets better because IndicAgent signals flow back through signal_ledger. DerivAgent calibrates better because it reads QualAgent's macro regime. TradeAgent gets smarter because all three platforms feed its learning agent. A competitor can copy one platform; they cannot copy the compounding intelligence of all four connected.

**Target customer evolution:**

| Phase | Customer | Pain point | Offering |
|-------|---------|-----------|---------|
| Phase 1 | Discretionary futures trader | "I miss setups; my timing is bad" | Real-time signals + dashboard |
| Phase 2 | Systematic trader, small fund | "I don't know what regime I'm in" | QualScore regime context API |
| Phase 3 | Options-aware trader | "I keep getting run over by gamma" | DerivAgent overlay |
| Phase 4 | Affluent trader, family office | "I want the system to run itself" | TradeAgent (HITL mode) |

---

## Extended ideas — deep riff

This section captures ambitious ideas, research directions, and novel concepts that extend QualAgent beyond the core vision. These range from near-term additions to long-horizon research bets. All are worth recording and revisiting.

---

### Narrative momentum — the second derivative of sentiment

The original vision captures sentiment *direction* (bullish/bearish/neutral). But hedge funds care about sentiment *velocity and acceleration* — the same second-derivative intuition behind IndicAgent's MomentumAcceleration plugin (I2).

**The idea:** Track not just "what is the current narrative?" but "how fast is the narrative changing, and is that rate of change accelerating or decelerating?"

- **Linguistic velocity:** Week-over-week change in sentiment score magnitude. A market moving from +0.1 sentiment to +0.6 over three weeks is more interesting than one sitting at +0.6 for two months.
- **Narrative inflection detection:** When a strongly bullish narrative starts softening — even before it turns bearish — that inflection is often a leading signal. Analogous to RSI divergence but in language space.
- **Fed communication drift:** Track FOMC minutes, speeches, and press conferences for vocabulary shifts. A Fed that is gradually replacing "patient" with "data-dependent" and then "concerned" is telegraphing a hawkish pivot over months before markets fully price it. The velocity of language change IS the signal.
- **Earnings call transcript drift:** CEO uses "challenging environment" more frequently over successive quarters → guidance cut is coming. The NLP model tracks year-over-year vocabulary drift per company, not just point-in-time sentiment.
- **Implementation:** Sentiment velocity = `(sentiment_t - sentiment_t-N) / N`; sentiment acceleration = second derivative. Publish alongside raw sentiment score. Flag inflection points (acceleration crossing zero from positive to negative).

---

### Crowded trade detection — composite crowding intelligence

One of the most consistent edges in hedge fund research: **the crowd is eventually wrong at extremes**. When a trade is overcrowded — everyone is positioned the same way — the reversal is violent when it unwinds.

QualAgent can build a composite **crowding score** by combining signals that no single source can produce alone:

| Signal | What it captures |
|--------|-----------------|
| COT: Large spec net position Z-score | Managed money (hedge funds, CTAs) positioning extremes |
| Put/call ratio extreme | Retail and institutional hedging direction |
| Social sentiment extreme | Retail conviction level |
| News volume vs average | Is this trade getting media attention? Attention = crowding. |
| Prediction market consensus | Is there a dominant narrative everyone is betting on? |

**The composite:** When all five signals align in the same direction at extremes, the crowding score hits maximum. This is not a directional signal on its own — it is a **fragility signal**. The market is over-extended; the question is only what the trigger will be.

**Use case:** When crowding score is extreme-long, IndicAgent's mean-reversion setups should be upweighted. Trend-following setups should be downweighted or gated. The crowd's positioning becomes the fuel for the reversion.

**Renaissance connection:** Simons understood that obvious edges get crowded away ("The logical strategies are arbed away"). The crowding score is a real-time monitor of crowdedness — when a trade appears here, its edge is probably compressed.

---

### Reflexivity detection — when sentiment drives price drives sentiment

George Soros' theory of reflexivity describes a feedback loop: market participants' beliefs affect prices, and prices affect beliefs, creating self-reinforcing cycles. Trend manias and crashes are reflexivity cycles.

**The quant version:** QualAgent can detect when this feedback loop is active by comparing the lead/lag relationship between sentiment changes and price changes over rolling windows.

- **Normal (price-driven sentiment):** Price moves first → news follows → sentiment follows. Typical cause-and-effect.
- **Reflexive (sentiment-driven price):** Sentiment moves first → price follows → more sentiment. Narrative is in the driver's seat.
- **Reflexivity cycle signature:** Both price and sentiment are trending in the same direction, with sentiment *leading* by consistent N bars across multiple lookback windows. This is a bubble condition — price is being driven by belief, not by fundamental change.
- **Reflexivity break:** When price moves sharply but sentiment does not follow (or moves opposite), the feedback loop is breaking. This is the moment mean-reversion setups have maximum expected value.
- **Implementation:** Cross-correlation analysis between sentiment velocity and price velocity, with dynamic lag estimation. Publish `reflexivity_index` (0 = normal, 1 = fully reflexive) and `reflexivity_break_flag`.

This is one of the most sophisticated ideas in the doc. It requires both price data (from IndicAgent) and sentiment data (from QualAgent) to compute — a genuine cross-platform intelligence product.

---

### Information half-life — signal freshness weighting

Different qualitative signals have radically different decay rates. A COT positioning signal might remain valid for 3-4 weeks; a news headline sentiment signal might decay within hours. Using stale signals as if they were fresh is a major source of alpha leakage.

**The idea:** Assign each signal type an estimated half-life. Weight signal contributions to the regime score by `exp(-t / half_life)` where `t` is time since the signal was generated.

| Signal | Estimated half-life | Notes |
|--------|-------------------|-------|
| COT positioning extreme | 3–4 weeks | Institutional position changes slowly |
| Prediction market probability | Hours to event | Decays to zero once event resolves |
| Economic surprise index | 2–3 weeks | Resets on next data print |
| News sentiment | 4–24 hours | Headlines are stale by next session |
| Earnings call transcript tone | 6–12 weeks | Until next earnings report |
| Social sentiment extreme | 1–4 days | Crowd has short memory |
| GPR geopolitical risk | Days to weeks | Depends on event resolution |
| Fed language drift | Weeks to months | Structural shift; long-lived |

**Regime score = weighted sum of active signals × their current freshness weight.** Signals approaching their half-life decay gracefully rather than suddenly expiring.

**Practical benefit:** The system never relies on a stale Friday COT reading as if it were a Tuesday signal with equal confidence. Information age matters.

---

### The QualScore — unified quantamental intelligence number

Rather than requiring downstream consumers (IndicAgent, TradeAgent) to parse multiple independent regime streams, QualAgent can publish a single **QualScore** (0–100) per symbol/market:

- **0–20:** Strong bearish qualitative context (macro tightening, crowded longs, negative surprise streak, prediction markets pricing fear)
- **40–60:** Neutral / mixed — qualitative context does not add strong directional weight
- **80–100:** Strong bullish qualitative context (easing cycle, extreme spec shorts / COT extreme long, positive surprise streak)

The QualScore is a weighted composite, decomposable into its components for transparency. TradeAgent's lead agent doesn't need to understand COT Z-scores — it just reads QualScore and the top 3 contributing factors.

**Critically:** QualScore is not a *trading signal*. It is a **context multiplier** for quant signals. An IndicAgent long signal with QualScore=85 has a higher expected win rate than the same signal at QualScore=30. This is the quantamental bridge operationalized as a number.

**Dynamic weighting:** The contribution weights of each component should be regime-dependent and periodically re-estimated from `signal_ledger` outcomes. Which qual signals actually improve win rates at this point in the cycle? The weights update accordingly — this is the self-improving loop.

---

### Regime transition probability — Bayesian, not just state

Most regime models answer: "What regime are we in?" QualAgent should also answer: "What is the probability of regime transition in the next N days?"

This is more useful for trading than a point-in-time label, because:
- Setups entered *near* a regime transition have the worst risk/reward (uncertainty is maximum)
- Setups entered *after* a clear transition has been confirmed have historically better performance
- The probability of transition is itself a signal — a volatile probability means the system is uncertain, which is a risk-off flag

**Implementation approach:**
- Maintain a Bayesian prior over regime states, updated as new qual signals arrive
- Compute `p_transition_7d` and `p_transition_30d` via state-transition probabilities estimated from historical data
- Publish alongside current regime state
- When `p_transition_7d > 0.4`, flag as "regime uncertainty" — IndicAgent can reduce signal confidence, TradeAgent can reduce position sizing

**Example:** COT is at a short extreme. Economic surprise just turned negative. Prediction market is pricing 65% probability of a rate pause (up from 40% two weeks ago). These signals together say: transition probability is rising. The system doesn't need to know *what* the new regime will be — the rising uncertainty itself is actionable.

---

### Historical narrative analog matching — semantic time travel

This is one of the most powerful ideas in this doc, and it's enabled by modern LLM embedding technology.

**The idea:** Embed the current market narrative (synthesized from all QualAgent signals — sentiment, macro regime, COT positioning, news flow, prediction markets) as a high-dimensional vector. Then search historical embedded narratives for the closest analogs.

**Output:** "The current market narrative most closely resembles Q4 2018 (correlation 0.87), followed by Q2 2022 (0.81) and Q1 2016 (0.74)."

Each historical analog comes with known outcomes: what happened to ES, NQ, VX over the following 5/10/20 trading days in each analog period? The distribution of those outcomes becomes a probability-weighted forward path.

**Why this is powerful:**
- It combines all qualitative signals into a single "what does this feel like historically?" answer
- It provides context no pure technical analysis can — technicals are blind to macro regime similarity
- It is honest about uncertainty: it presents a *distribution* of analogs, not a single prediction
- It surfaces non-obvious historical periods ("this is more like 2016 than 2022, even though the chart looks like 2022")

**Renaissance alignment:** Principle 11 (pattern recognition from vast history) + Principle 9 (unconventional data). Simons and team used World Bank data back to the 1700s. We use semantic embeddings over regime history.

**Implementation:** Vector store (pgvector or Qdrant) indexed by date; narrative embeddings generated by QualAgent's synthesis agent after each market session; similarity search against full history; top-N analogs published to `qual:analog:current` stream with outcome distributions.

---

### Cross-asset macro intelligence — the interconnected regime

Index futures do not trade in isolation. The regime of the dollar, rates, credit, and commodities is the water the fish swims in. QualAgent should track these cross-asset relationships systematically.

**Key macro intelligence signals:**

| Signal | What it measures | Why it matters for ES/NQ |
|--------|----------------|--------------------------|
| **2s10s yield curve spread** | Short vs long rate relationship | Inversion precedes recessions; steepening after inversion signals recovery |
| **Credit spreads (HY vs IG)** | Risk appetite / credit stress | When HY spreads widen → risk-off regime; equities typically follow |
| **DXY (Dollar Index)** | Global liquidity proxy | Strong dollar = global liquidity tightening; negative for risk assets |
| **Fed balance sheet week-over-week change** | Quantitative tightening vs easing | QT reduces liquidity; most correlated with equity multiple compression |
| **M2 money supply growth rate** | Monetary regime | M2 contraction preceded the 2022 equity drawdown by ~6 months |
| **VIX term structure (M1/M2 ratio)** | Near-term vs medium-term fear | Inverted term structure = panic; normal = complacency |
| **Gold/dollar ratio** | Real vs nominal return preference | Gold outperforming = inflation expectations rising; regime shift signal |
| **Copper/Gold ratio** | Global growth proxy | Copper (industrial demand) vs Gold (safe haven) — leading growth indicator |

These are all price-derived but represent *qualitative regime states*, not trading signals. The credit spread is not telling you where to put your stop — it is telling you what kind of market you are operating in.

**Policy divergence signals:**
When the Fed is hiking while the ECB is cutting (or vice versa), structural regime divergence creates predictable cross-asset flows — dollar strengthens, dollar-denominated assets reprice, capital flows from one region to another. QualAgent tracks central bank policy divergence across major economies as a standalone regime modifier.

---

### Global liquidity intelligence — M2 and central bank balance sheets

Simons reportedly tracked datasets going back centuries, including data most analysts ignore. One of the most underutilized systematic signals is **global liquidity** — the aggregate expansion or contraction of central bank balance sheets and M2 money supply worldwide.

**The idea:**
- Track Fed, ECB, BoJ, PBOC balance sheet size week-over-week
- Track US M2 growth rate (12-month rolling)
- Track global M2 aggregate (in USD terms, adjusting for FX)
- Publish `liquidity_regime: {expanding | contracting | neutral}` with rate-of-change

**Why it matters:** The 2020-2021 equity mania was a global liquidity surge. The 2022 crash was a liquidity drain. These are not surprises in hindsight — the signals were visible in M2 and balance sheet data. A system that tracks these in real time would have flagged the regime shift months before the price move completed.

**Signal half-life:** Long. Monetary regime changes over months, not days. But the early signals — when balance sheet growth decelerates for the first time, when M2 growth turns negative — are highly predictive.

---

### Legal insider intelligence — SEC Form 4 cluster detection

Corporate insiders (executives, directors) must file SEC Form 4 within two business days of a trade in their own company's stock. These filings are public, free, and contain genuine information about what people with the best information think the stock is worth.

**The signal:** It is not one executive buying a small amount — that is noise. The signal is **cluster buying**: multiple insiders at multiple companies in the same sector, all buying within a short window. This is sector rotation intelligence that precedes price.

**Why futures-relevant:** Sector rotation signals are relevant for index futures through their sector component weights. A cluster of insider buying across semiconductor companies suggests the sector is bottoming — which matters for NQ composition.

**Implementation:** EDGAR Form 4 ingestion → filter for open-market purchases (not option exercises or grants) → aggregate by sector and time window → detect clusters where N ≥ threshold insiders in a sector buy within M days → publish as `qual:insider:SECTOR` regime signal.

**Renaissance score:** ✅ Measurable. ✅ Validatable (insider cluster buying has well-documented alpha, especially for smaller caps; less so for mega-cap index composition). ✅ Operational (EDGAR API, free, 2-day delay).

---

### Earnings whisper intelligence — the real consensus

The official consensus earnings estimate (e.g. from FactSet, Refinitiv) is what analysts formally publish. The "whisper number" is what the market actually expects — the informal, trading-desk consensus that determines whether a beat or miss is really a beat or miss.

**The edge:** A company can beat the official consensus by $0.05 but miss the whisper by $0.15. The stock sells off — confusing everyone who only watched the official number. The real reaction is always to the whisper, not the published consensus.

**Data source:** EarningsWhispers.com publishes whisper numbers for major stocks. Estimize is a crowdsourced consensus platform. The spread between official and whisper is itself a signal — a large positive spread means the market is more optimistic than analysts; a large negative spread means hidden skepticism.

**For index futures:** The aggregate whisper spread for S&P 500 companies during earnings season is a macro signal — are expectations for the index running ahead of analyst consensus? That gap determines how much "beat" is actually priced in.

---

### News-price velocity divergence — stored potential energy

**The observation:** Sometimes news volume spikes dramatically but price barely moves. Sometimes price moves sharply with very little news. These divergences have predictive value.

- **High news volume + low price reaction:** The market has absorbed the news without moving — either the news was already priced, or a large institutional player is absorbing the selling/buying. This is often a sign of a strong underlying bid or offer. The "coiled spring" scenario.
- **Sharp price move + low news volume:** Technical or positioning-driven move, not narrative-driven. These moves have higher mean-reversion probability because they lack fundamental backing.
- **Implementation:** Compute `news_velocity` (rate of new articles per hour on a topic) and `price_velocity` (absolute price change rate per hour). Track their ratio. Extreme divergence in either direction is a signal.

This is a cross-platform signal that requires IndicAgent price data and QualAgent news data to compute — a genuine integration between the two platforms.

---

### Alpha decay tracking — when edges erode

Simons knew that once an edge becomes known, it gets arbed away. He tracked this systematically. QualAgent should do the same for qualitative signals.

**The idea:** Every signal that has been validated and promoted to the live path should be monitored for alpha decay:
- Track rolling win rate uplift of `IndicAgent signal + qual signal` vs `IndicAgent signal alone`
- If the lift is deteriorating over rolling 90-day windows → flag for review → potentially demote from live path back to monitoring tier
- Log the date of demotion and the reason — this is institutional memory

**Why it matters:** A qualitative signal that worked in a tightening cycle may not work in an easing cycle. A prediction market signal that had edge in 2024 may be fully efficient by 2027 as more participants discover it. The system should notice and adapt — rather than blindly continuing to apply a signal whose lift has decayed to noise.

**Renaissance alignment:** Principle 11 (adaptive models; redesign when the edge changes, don't tweak). This is the QualAgent equivalent of "Simons insisted on reevaluation" rather than tuning.

---

### Self-improving signal selection — the qual feedback loop

The highest-leverage architectural idea in this doc: QualAgent should **learn from outcomes** and adjust its own signal weights automatically.

**The loop:**
1. QualAgent publishes regime state and QualScore
2. IndicAgent executes signals; outcomes land in `signal_ledger`
3. Periodically (weekly), a research job joins `signal_ledger` outcomes with `qual:regime:*` history
4. Compute: for each qual signal component, what was the incremental win rate lift when that signal was active vs when it was absent?
5. Update QualScore component weights to reflect observed lift
6. Signals that consistently lift win rates get higher weight; signals that show no lift or negative lift get downweighted
7. Over time, the QualScore becomes increasingly predictive — it is learning which qualitative context actually matters for *this system*, on *these instruments*, in *this time period*

**This is Renaissance Principle 6 (unified model improvements compound) applied to the qualitative layer.** Every new instrument, every new market regime, every new data source produces feedback that improves the system's understanding of what qualitative context actually predicts performance.

**Important constraint:** The loop must include holdout periods and out-of-sample validation. Overfitting the qual weights to recent history is the failure mode. Minimum sample size and significance requirements (from the validation framework above) apply to weight updates.

---

### DerivAgent — extended vision

*DerivAgent is a separate product (own codebase, own repo). Ideas captured here for the record.*

DerivAgent takes over where QualAgent's options boundary ends. While QualAgent asks "what is options flow telling us about crowd sentiment?", DerivAgent asks "what is the structure of volatility and derivatives pricing telling us about where the market is going and where there are pricing inefficiencies?"

**Core capabilities:**

| Capability | Description |
|-----------|-------------|
| **Volatility surface modeling** | Implied volatility across strikes and expiries → construct full 3D vol surface. Track surface evolution over time. |
| **GEX (Gamma Exposure)** | Compute dealer net gamma by strike. Positive GEX = market pinned (MM will sell rallies, buy dips). Negative GEX = market unstable (MM amplifies moves). Key for understanding intraday ES/NQ dynamics. |
| **VANNA / CHARM flows** | Second-order Greeks. As price moves and time decays, dealer hedging flows shift mechanically. VANNA flow (price moves → delta of option changes due to vol change → dealer must hedge) creates predictable price pressure at specific levels. |
| **Volatility risk premium (VRP)** | Realized vol vs implied vol. VRP is one of the most persistent edges in options — selling vol when IV > realized vol has been profitable historically. DerivAgent tracks VRP systematically. |
| **Skew intelligence** | Put skew vs call skew. A market with elevated put skew is hedging against downside; a market with compressed skew is complacent. Track skew percentile vs history. |
| **Term structure of volatility** | VIX M1 vs M2 vs M3 roll. Contango = normal (market calmer in future); backwardation = fear (market more worried near-term). The shape of term structure predicts volatility regime evolution. |
| **Options-derived probability distribution** | The options market implies a full probability distribution of future price outcomes (risk-neutral density). Extract this distribution and compare to historically realized distributions — divergences are pricing inefficiencies. |
| **Expiry-aware signal gating** | Know when major option expiries occur (monthly OPEX, quarterly). These create predictable flow dynamics (pinning, vol crush, post-expiry directional release). Gate or adjust IndicAgent signals around expiry mechanics. |

**DerivAgent x TradeAgent integration:** TradeAgent's lead agent should know the current GEX level when making sizing decisions — low GEX (negative gamma) environments warrant smaller position sizes and wider stops because dealer flows amplify moves. This is institutional-grade risk management that retail traders simply don't have.

**DerivAgent x QualAgent relationship:** DerivAgent publishes `deriv:regime:gamma_env` (positive/negative gamma), `deriv:vrp:current`, `deriv:skew:percentile`. QualAgent incorporates these as inputs to its regime synthesis — the volatility structure IS qualitative context about how the market is positioned and what it fears.

---

### The God View — unified intelligence platform commercial vision

Step back from the technical architecture and ask: what is the commercial product?

The full platform — IndicAgent + QualAgent + DerivAgent feeding into TradeAgent — is something that **does not exist as an integrated, accessible product for independent traders and small funds**. The pieces exist separately (Bloomberg for macro/news, SqueezeMetrics for GEX, Sentiment Trader for COT, Kalshi for prediction markets, TradingView for charts), but no one has integrated them into a coherent, AI-synthesized intelligence platform.

**What "God View" means:**

A trader opening their morning session sees:
- **QualScore: 72 (Bullish Bias)** — top contributors: COT extreme short spec position, positive prediction market shift on Fed pause, economic surprise recovering
- **Volatility Regime: Positive Gamma** (from DerivAgent) — market will naturally dampen moves; fade extremes
- **Macro Regime: Transition** — yield curve steepening; liquidity marginally expanding; transition probability 43%
- **Narrative Analog: Most similar to Q1 2016** — forward distribution across analogs: median +2.3% over 10 days, 80th percentile +5.1%, 20th percentile -1.8%
- **Catalyst Calendar:** CPI print Thursday 8:30am; Fed speaker Friday 2pm. Pre-event flag active from Wednesday close.
- **IndicAgent signals:** 3 active long setups (VWAP deviation, session extreme fade, candlestick confluence) — all aligned with QualScore bullish bias. Aggregated confidence: 74%.
- **AI Narrative:** "Market is in early recovery from tech-led drawdown. Institutions are quietly covering shorts (COT) while retail sentiment remains bearish (social). Prediction markets price 68% probability of Fed pause — market has only priced 55%. This dislocation is the key tail risk. Mean-reversion setups have historically outperformed in positive gamma + COT extreme environments."

**That is the product.** No individual retail trader has access to anything close to this. No single SaaS tool provides this integration. This is a genuine moat — the value is not in any single data source, but in the integration, synthesis, and validation layer that connects all of them.

**Commercial implications:**
- **Independent traders / prop firms:** Pay for the God View dashboard + signals. This is a subscription product (SaaS).
- **Small hedge funds:** License the API layer. QualScore, regime streams, and narrative analogs are valuable inputs to their own systems.
- **TradeAgent integration:** The God View dashboard becomes TradeAgent's primary UI — the operator sees everything before making the call to let the system trade.

---

### Research bets — longer horizon, lower certainty

Ideas that are harder to validate but worth capturing:

**Satellite imagery for macro regime:** Monitoring industrial activity (factory rooftops, power plant emissions, oil storage tank shadow analysis) at a macro scale — not individual companies, but whole regions. A spike in industrial activity across the Shanghai Economic Zone is a leading indicator for global supply chain recovery. Currently expensive (~$50k/year for commercial providers), but cost is falling. Architecture should accommodate this as a data connector when price becomes acceptable.

**Shipping and logistics intelligence:** Baltic Dry Index (free, public) as a global trade volume proxy. Container shipping rates (Freightos Baltic Index, free). Supply chain pressure index (NY Fed publishes this). These are unconventional macro signals that preceded both the 2021 inflation surge and its subsequent normalization.

**Credit card and spending data:** Aggregated, anonymized transaction data from credit card processors (Mastercard SpendingPulse, BofA consumer spending data) shows real-time consumer behavior before official retail sales prints. Expensive for real-time; monthly academic releases are free.

**Lunar cycles and seasonality:** Simons famously tested lunar cycles. The academic evidence for lunar effects on market returns is mixed at best, but systematic seasonality (day-of-week, month-of-year, pre/post-holiday, options expiry week effects) is well-documented. QualAgent's catalyst calendar should include systematic seasonality patterns as low-confidence regime modifiers.

**Whisper networks (alternative news):** Telegram channels, Discord servers, private Substacks where market participants share analysis before it reaches mainstream financial media. This is harder to quantify but represents early information diffusion. The pattern-recognition challenge: distinguish informed early analysis from noise. Research direction, not a near-term data source.

---

## External Research Validation — JPMorgan Patent Patterns

**Source:** JPMorgan patent application for AI-generated stock ratings (published April 2026, filed Feb 2025)

This patent describes an LLM-based system that generates analyst-style ratings (Strong Buy → Strong Sell) using fundamentals, market data, news, and sentiment. Key empirical findings from their testing:

**Validation results:**
- LLMs outperformed analysts at short horizons (1-3 months); analysts were slightly better at 18 months
- Fundamentals alone beat news alone
- Fundamentals + sentiment performed best (modest lift over fundamentals alone)
- News alone skewed positive and underperformed
- Chain-of-verification (date check + explanation consistency) improved LLM reliability

### Pattern 1: Sentiment Calibration / Positivity Bias Detection

**Problem:** News-derived sentiment alone pushed ratings toward positive values.

**Solution:** Track `positivity_drift` per news source — average sentiment when market is flat. Subtract this bias from all future readings.

```sql
CREATE TABLE source_calibration (
    source TEXT PRIMARY KEY,
    bias_mean FLOAT,
    bias_std FLOAT,
    sample_size INT,
    last_calibrated_at TIMESTAMPTZ,
    is_active BOOLEAN DEFAULT TRUE
);
```

**Integration:** Calibrate at news_provider level; emit `sentiment_raw` and `sentiment_calibrated` to `ctx_snapshots`.

---

### Pattern 2: Chain-of-Verification for LLM Outputs

**Problem:** LLMs can generate coherent but unsupported outputs.

**Solution:** Before accepting any LLM-derived signal, validate:
1. **Date consistency:** Did the model correctly calculate future dates referenced in the output?
2. **Explanation coherence:** Does the explanation reference factors that actually exist in the input context?

**Integration with skeptic_agent:**
- Add `coherence_score` to validation output
- If validation fails, return `neutral` with `error="verification_failed"`
- Store verification results in `llm_calls` for analysis

---

### Pattern 3: Multi-Horizon Confidence Decay

**Problem:** LLM performance degrades over longer prediction horizons.

**Solution:** Apply horizon-based confidence penalty when QualScore is used as signal modifier:

| Horizon | Confidence Multiplier |
|---------|----------------------|
| ≤1 month | 1.0 (full) |
| 1-3 months | 0.95 |
| 3-6 months | 0.85 |
| 6-12 months | 0.70 |
| ≥12 months | 0.50 (strong penalty) |

**Integration:** Store `confidence_raw`, `confidence_adjusted`, and `decay_factor` in `qual_regime_history`.

---

### Pattern 4: News Freshness Weighting

**Finding:** News more useful for short-term predictions; fundamentals better across 3/6/12-month horizons.

**Solution:** Apply exponential decay to news-derived features: `weight = exp(-days_old / tau)`

| Signal Type | Tau (half-life) |
|-------------|----------------|
| News sentiment | 1 day |
| Earnings surprise | 30 days |
| Fundamental metrics | 45 days |

**Integration:** Add `freshness_weight` and `weighted_value` to `ctx_snapshots` for time-sensitive features.

---

### Pattern 5: Quintile-Based Signal Normalization

**Finding:** Future returns divided into quintiles and mapped to rating categories created sector-neutral rankings.

**Solution:** Map fundamental metrics to quintiles within sector/universe before using as signals:

```sql
SELECT symbol, ntile(5) OVER (PARTITION BY sector ORDER BY pe_ratio) as pe_quintile
FROM fundamental_metrics;
```

**Integration:** Add `sector_quintile` to `intelligence_features`. Use quintile instead of raw value for fundamental confluence.

---

### Pattern 6: Fundamentals × Sentiment Interaction Terms

**Finding:** Fundamentals + sentiment performed best, but the patent may have missed interaction effects.

**Solution:** Compute interaction matrix:

| Fundamentals | Sentiment | Signal Interpretation |
|-------------|-----------|----------------------|
| Strong (Q4-5) | Positive | Momentum_long |
| Strong (Q4-5) | Negative | Value_long (contrarian opportunity) |
| Weak (Q1-2) | Positive | Hope_short (fade the optimism) |
| Weak (Q1-2) | Negative | Confirm_short |

**Integration:** Add `fundamental_sentiment_interaction` to `ctx_snapshots`. Use interaction state as a regime modifier.

---

### Pattern 7: Peer-Relative Forward Returns for Ground Truth

**Finding:** Patent used `stock_return - sector_return` to reduce regime noise in ground truth labels.

**Solution:** In `signal_ledger`, add:
- `sector_return_r` — sector performance over trade period
- `excess_return_r` — `pnl_r - sector_return_r`

Use `excess_return_r` as target for ML training to separate alpha from beta.

---

### Pattern 8: Pre-Processing LLM for News Filtering

**Finding:** Lightweight LLM pass filtered/summarized news before main prediction model.

**Solution:** News summarization stage that:
1. Filters articles irrelevant to instrument (symbol matching, sector relevance)
2. Summarizes to 3-5 key developments per ticker per day
3. Tags each summary: `["earnings", "guidance", "macro", "sector_news", "company_specific"]`

**Integration:** Add to `narrative_compute_agent`. Downstream agents consume compressed, tagged signals.

---

### Extended Ideas — Beyond the Patent

Based on the patent patterns plus IndicAgent's architecture:

**Idea 1: Regime-Dependent Signal Weights**

Instead of fixed QualScore weights, make them regime-dependent:
- Tightening cycle: upweight COT positioning, downwidth sentiment
- Easing cycle: upweight prediction market dislocations, downwidth crowding
- High volatility: upweight economic surprise, downwidth news sentiment

Store weight schedules in `regime_weight_profiles` table.

**Idea 2: Sentiment Velocity + Acceleration**

Track not just sentiment level but its rate of change:
- `sentiment_velocity = (sentiment_t - sentiment_t-N) / N`
- `sentiment_acceleration` = second derivative

Flag inflection points (acceleration crossing zero) as regime transition signals.

**Idea 3: Cross-Asset Sentiment Contagion**

When sentiment shifts in one asset (e.g., tech stocks), measure propagation speed to correlated assets (ES, NQ). Fast contagion = regime instability; slow contagion = disciplined rotation.

**Idea 4: LLM Hallucination Detection via Consensus**

Run multiple LLMs (different providers/models) on the same context. If outputs diverge significantly, flag as low-confidence and reduce signal weight.

**Idea 5: Causal Inference for Qual Signals**

Use Granger causality tests to determine whether qual signals *cause* price moves or just *correlate*. Only promote signals with causal precedence to live path.

---

## Updated open questions

1. **Bus architecture:** Shared Redpanda instance with IndicAgent, or QualAgent-owned? The interface needs to be defined precisely — probably a lightweight REST API for regime state + optional shared stream keys for real-time signals.

2. **LLM provider strategy:** LiteLLM + OpenRouter for all inference. Near-term NLP classification tasks (headline sentiment, transcript tone) → smaller, faster models. RAG over SEC filings → larger context window models. Narrative synthesis → highest quality available. Different tasks, different model tiers, all through one LiteLLM interface.

3. **Update cadences and service architecture:** COT (weekly), economic data (per-print), prediction markets (real-time), news (continuous), social (continuous), M2/Fed balance sheet (weekly). Separate daemon per cadence tier, unified into a scheduler (APScheduler or Celery beat). Failure isolation: a stale news feed should not block COT publishing.

4. **First data source to validate:** COT (free, futures-relevant, well-studied, easy to operationalize) vs Prediction Markets (novel, highest potential alpha, also free APIs). Recommendation: COT first to prove the pipeline plumbing, prediction markets second to prove the novel thesis.

5. **Regime-conditional backtest infrastructure:** Requires joining `signal_ledger` (IndicAgent) with `qual:regime:*` history (QualAgent). This cross-system join is the research tool that proves QualAgent's lift. Should be a standalone offline job, not part of either live system.

6. **Self-improving loop timing:** Weekly weight updates is a reasonable cadence. Minimum sample size before any weight update should be enforced. This should be a separate "research scheduler" job, clearly separated from live signal path.

7. **QualScore v1 component definition:** Before building, define the initial component weights analytically (not just empirically). What do we *believe* each signal contributes? Version this belief explicitly — then let the feedback loop revise it. This prevents the loop from starting with random weights.

8. **DerivAgent coordination:** When DerivAgent's vol regime conflicts with QualAgent's sentiment regime (e.g. negative gamma but bullish QualScore), how does TradeAgent resolve the conflict? Define the priority hierarchy before integration.

---

## Relationship to Existing Architecture

QualAgent extends the platform as the qualitative intelligence layer. It is a separate application (own repo, own services, own storage) that publishes onto the shared intelligence bus:

- **Unified Data Bus compliance** — Services never call each other. QualAgent publishes `qual:*` events; IndicAgent and TradeAgent subscribe optionally. No coupling beyond the bus. See `docs/data/` for bus architecture.
- **DAG invariants preserved** — Qualitative data flows one direction: ingestion → regime synthesis → Kafka → consumers. No cycles. No service touches the database except Writers/Trackers. See `docs/concepts/dag-execution.md`.
- **APR-governed** — All QualScore component weights, lift thresholds, and decay parameters live in `config_state` under the `qual.*` namespace. No hardcoded values. See `docs/foundation/adaptive-parameter-registry.md`.
- **Shadow Governance (SG)** — Every qualitative source enrolls in shadow. Promotion to a live signal path requires `n >= 100` and `bootstrap_ci_lower > 0` at 95% CI; demotion on `EV[R] < -0.05` for 3 consecutive cycles. See `docs/foundation/glossary.md`.
- **Signal Ledger Architecture integration** — The quantamental feedback loop joins `signal_ledger` (the SLA join view over `signal_events` / `trade_frames` / `trade_executions`) with `qual:regime:*` history. Outcome attribution uses `counterfactual_pnl_r` so regime-suppressed signals are not excluded. See `docs/foundation/glossary.md`.
- **Typed events via `stream_keys.py`** — All topic keys constructed centrally. No hardcoded strings. See `src/core/stream_keys.py`.

## Foundation Concepts Referenced

- **Principles** — `docs/foundation/principles.md`: Data quality over model complexity, never drop data that could contain signal, segment relentlessly, earn the right through proof
- **Naming System** — `docs/foundation/naming-system.md`: `QualAgent` is a product name, not a code class; the Ring 2 daemon class/file is derived per the naming system when built
- **APR** — `docs/foundation/adaptive-parameter-registry.md`: QualScore weights and decay parameters governed by APR
- **Documentation System** — `docs/foundation/documentation-system.md`: Idea docs live in `ideas/`, not authoritative until verified
- **Glossary** — `docs/foundation/glossary.md`: SLA, SG, APR, alpha, regime, edge — canonical definitions for the terms used throughout this doc
- **Renaissance Framing** — `docs/research/renaissance-02-framing.md`: unified model, regime detection before everything, signal validation before production

## References

- `docs/research/renaissance-01-simons-principles.md` — validation framework, alternative data, adaptive models
- `docs/research/vision-05-tradeagent.md` — primary consumer of QualAgent output
- `.planning/milestones/v1.0-REQUIREMENTS.md` — PLAT-01/02/03/04 (original multi-platform requirements)
- `.planning/IDEAS.md` — News Sentiment Integration (early idea, now superseded by this vision)
- `docs/intelligence/market-intelligence-strategy.md` — Sentiment Analysis Agent
- [CFTC COT data](https://www.cftc.gov/MarketReports/CommitmentsofTraders/index.htm)
- [Kalshi API](https://kalshi.com/docs/kalshi-api/b3A6OTExMTE2-get-markets)
- [Polymarket API](https://docs.polymarket.com/)
- [Geopolitical Risk Index](https://www.matteoiacoviello.com/gpr.htm) — Caldara & Iacoviello (Fed)
- [Citi Economic Surprise Index](https://www.investopedia.com/terms/c/citi-economic-surprise-index.asp)
- [EarningsWhispers](https://www.earningswhispers.com/) — whisper number vs consensus
- [Baltic Dry Index](https://www.balticexchange.com/en/data/baltic-dry-index.html) — global shipping / trade volume
- [NY Fed Supply Chain Pressure Index](https://www.newyorkfed.org/research/policy/gscpi)
- [Freightos Baltic Index](https://fbx.freightos.com/) — container shipping rates
- [SEC EDGAR Form 4](https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&type=4&dateb=&owner=include&count=40) — insider transactions
- [SqueezeMetrics GEX](https://squeezemetrics.com/monitor/dix) — gamma exposure reference
- [VIX term structure](https://vixcentral.com/) — VIX futures term structure monitoring
