# Platform Architecture — Unified Intelligence & Execution Suite (Vision)

**Version:** 1.0
**Status:** draft
**Priority:** high
**Milestone:** future (post-v2.8)
**Last Updated:** 2026-05-02
**Tags:** platform, architecture, event-bus, redpanda, product-family, vision, intelligence, execution

> **Living document.** The data flow section and canonical stream namespace are the source of truth for stream contracts across all products. Update these whenever a stream is added, renamed, or retired.

---

## Executive Summary

**TLDR:** The entire platform — all six products across intelligence, execution, portfolio, and risk — is unified by a single shared event bus (Redpanda). Every piece of market data, every intelligence signal, every execution event, and every risk action flows through this bus. Products don't call each other; they publish to streams and subscribe from them. This means any new product or external system can be integrated simply by subscribing to the streams it needs and publishing the signals it produces. No existing code changes, no tight coupling, no data duplication. The bus is the spine. Everything else is a consumer or producer attached to it.

### What the shared bus enables

The architecture was designed around a single architectural insight inspired by Renaissance Technologies: **signal value compounds at the intersections**. A volatility compression signal alone is useful. A confirmed macro regime shift alone is useful. A technical confluence score peaking alone is useful. All three aligning simultaneously — and a system that can see all three because they flow through the same bus — that is where institutional-grade edge comes from.

The shared data spine makes this possible:

- **IndicAgent** (live today) produces the full I1–I8 quantitative intelligence stack — indicators, patterns, regime confluence, trading signals, AI narrative — and publishes it all to the bus. Any product, now or future, can subscribe to `intelligence:SYMBOL:TF` and immediately consume 88 plugins worth of signal without any integration work.
- **QualAgent** (vision) will subscribe to the same market data streams and publish qualitative regime states (`qual:regime`, `qual:score`, `qual:event`) to the same bus. TradeAgent and DerivAgent can then combine quantitative and qualitative signals in a single reasoning step — without either product knowing anything about the other's internal implementation.
- **DerivAgent** (vision) will publish derivatives intelligence (`deriv:vol_regime`, `deriv:gex`, `deriv:vrp`) to the bus. The cross-product signal — IndicAgent I6 confluence HIGH + QualAgent macro BULLISH + DerivAgent VRP ELEVATED — becomes readable by any downstream system as a single composite regime view.
- **TradeAgent and DerivAgent Execution** (vision) subscribe to all warm-tier intelligence streams and publish execution events (`execution:open`, `execution:fill`, `execution:close`) back to the bus, where PrimeAgent and AegisAgent pick them up for portfolio management and risk enforcement.
- **External systems** — a research tool, a third-party signal consumer, a backtesting engine, a custom strategy bot — can integrate by subscribing to any combination of streams. Redpanda consumer groups allow multiple independent consumers to read the same stream without interfering with each other. Replay from offset 0 means a new system can bootstrap on full historical data from day one.

The three-tier model (hot → warm → cold) mirrors how institutional quant shops structure their data infrastructure. Hot tier is raw, sub-millisecond market data. Warm tier is enriched intelligence outputs and regime states. Cold tier is the institutional memory — TimescaleDB — where every signal, every outcome, and every portfolio snapshot accumulates as the training dataset for the learning loop. The system improves without manual retuning because all the raw material for learning flows through the same bus and lands in the same database.

Integration cost for a new product: subscribe to the streams you need, publish what you produce. The contract is the stream namespace. No existing products change.

---

## Purpose of this doc

Capture the architectural vision for how all six products — IndicAgent, QualAgent, DerivAgent, TradeAgent, PrimeAgent, and AegisAgent — fit together as a unified, event-driven intelligence and execution platform. This doc covers the shared data spine, product boundaries, the Renaissance-style data flow, the canonical stream contract, portfolio and risk management, trade execution, and strategy automation.

---

## The Renaissance framing

Jim Simons and Medallion didn't build separate silos for equities, futures, and currencies. They built **one data spine** where everything landed — price, fundamentals, macro, alternative data, all of it — and strategies consumed from that single source.

The insight: signal value compounds at the intersections. A vol surface dislocation alone is useful. COT positioning at an extreme alone is useful. Technical confluence with a confirmed regime shift alone is useful. All three aligned simultaneously is a materially stronger signal than any individual input.

That combination is only discoverable if all signals flow through a shared bus that every downstream consumer can subscribe to. Siloed products with private data pipelines cannot see across domain boundaries.

The architecture built for IndicAgent already has the right DNA. The hot/warm/cold tier model maps directly to how a quantitative hedge fund structures its data infrastructure.

---

## Product family

| Product | Domain | Role | Status |
|---------|--------|------|--------|
| **IndicAgent** | Quantitative intelligence | I1–I8 technical pipeline: indicators, patterns, confluence, signals, narratives | Live |
| **QualAgent** | Qualitative intelligence | COT, prediction markets, macro surprise, news NLP, QualScore, qualitative regime | Vision |
| **DerivAgent** | Derivatives intelligence + execution | Vol surface, GEX, VRP, skew — + autonomous options execution | Vision |
| **TradeAgent** | Directional execution | Autonomous futures/equity trading, consumes all three intelligence products | Vision |
| **PrimeAgent** | Portfolio management | Unified P&L, Greek aggregation, capital allocation, Kelly sizing, performance attribution, SMA/fund management | Vision |
| **AegisAgent** | Independent risk | Real-time VaR, drawdown enforcement, margin monitoring, stress testing, emergency halt, pre-trade check. Override authority over all execution products. | Vision |

Each intelligence product (IndicAgent, QualAgent, DerivAgent) is independently useful as a signal source. Each execution product (TradeAgent, DerivAgent execution layer) requires PrimeAgent for portfolio management and AegisAgent for risk before deploying real capital at scale. All six together form the complete institutional-grade stack.

---

## The shared data spine: hot/warm/cold tiers

The streams **are** the shared data spine. No separate "MarketCore" service is needed. The architecture provides the right plumbing through three tiers. Every product reads from and writes to the same bus.

```
HOT  (Redpanda topics)
  Raw events, durable and replayable
  Real-time market data, data-triggered actions
  IBKR provides 1m bars only — timeframes_builder_service aggregates to 5m→1D
  ↓

WARM  (Redpanda topics, processed)
  Intelligence outputs, regime states, cross-product signal bus
  All products publish here, all products can subscribe
  New products bootstrap by replaying from offset 0
  ↓

COLD  (TimescaleDB + pgvector)
  Institutional memory
  Historical feature vectors, signal ledger, outcomes
  ML training dataset, backtest data, learning loop
  Vector embeddings for regime analog matching
```

The streams are the nervous system. Every event that matters flows through them. Actions are triggered by data events, never by polling.

Shared storage is acceptable and often preferable when schemas and retention rules align. That does not imply shared runtimes: each product should remain independently runnable, with its own ingestion, compute, and persistence processes.

> **Infrastructure note:** The event bus is **Redpanda** (Kafka-compatible, single binary, no ZooKeeper). Target infrastructure: **Redpanda + PostgreSQL** (TimescaleDB + pgvector extensions). DragonflyDB is not in the initial target stack — it will be added only when a specific trigger is real (tick SaaS fan-out, DerivAgent options chain state, or scale fan-out bottleneck). See `docs/research/tech-stack.md`.

---

## Full platform architecture

```
┌─────────────────────────────────────────────────────────────────┐
│               SHARED DATA SPINE  (Redpanda)                     │
│                                                                 │
│  IBKR TWS Daemon → publishes 1m bars + ticks only               │
│    hot: market.ticks      SYMBOL          all products          │
│    hot: market.bars       SYMBOL:1m       all products          │
│                                                                 │
│  timeframes_builder_service → aggregates 1m → higher TFs        │
│    hot: market.bars       SYMBOL:5m   ┐                         │
│    hot: market.bars       SYMBOL:15m  │  IndicAgent             │
│    hot: market.bars       SYMBOL:1h   │  DerivAgent             │
│    hot: market.bars       SYMBOL:4h   │  (keyed by SYMBOL:TF    │
│    hot: market.bars       SYMBOL:1d   ┘   for partition order)  │
└────────────┬─────────────────────┬────────────────┬────────────┘
             │                     │                │
             ▼                     ▼                ▼
   ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐
   │   INDICAGENT     │  │    QUALAGENT     │  │   DERIVAGENT     │
   │                  │  │                  │  │                  │
   │  I1-I8 technical │  │  COT ingestion   │  │  Options chain   │
   │  pipeline        │  │  Prediction      │  │  subscription    │
   │                  │  │  markets (Kalshi │  │                  │
   │  Indicators      │  │  Polymarket)     │  │  Vol surface     │
   │  Patterns        │  │                  │  │  construction    │
   │  Confluence      │  │  News NLP        │  │                  │
   │  Setups (I7)     │  │  Macro surprise  │  │  GEX, VANNA      │
   │  AI narrative    │  │  index           │  │  CHARM, skew     │
   │  (I8)            │  │                  │  │  term structure  │
   │                  │  │  QualScore       │  │  VRP             │
   │  Dashboard       │  │  Regime states   │  │                  │
   │  SSE/API         │  │                  │  │  Derivatives     │
   │                  │  │                  │  │  regime states   │
   └────────┬─────────┘  └────────┬─────────┘  └────────┬─────────┘
            │                     │                     │
            ▼                     ▼                     ▼
   warm: intelligence:      warm: qual:regime:    warm: deriv:vol_regime:
         SYMBOL:TF                SYMBOL                SYMBOL
         signals:                 qual:score:           deriv:gex:
         SYMBOL:TF:agg            GLOBAL                SYMBOL
         narratives:              qual:event:           deriv:vanna:
         SYMBOL:TF                SYMBOL                SYMBOL
                                  qual:catalyst:        deriv:vrp:
                                  GLOBAL                SYMBOL
            │                     │                     │
            └─────────────────────┴─────────────────────┘
                                  │
                                  ▼
          ┌────────────────────────────────────────────────┐
          │           CROSS-PRODUCT SYNTHESIS              │
          │                                                │
          │  Combined regime view (all three domains)      │
          │  Signal alignment detection                    │
          │  Multi-domain conviction scoring               │
          └────────────────┬───────────────────────────────┘
                           │
             ┌─────────────┴────────────────┐
             ▼                              ▼
   ┌──────────────────────┐      ┌──────────────────────────┐
   │     TRADEAGENT       │      │  DERIVAGENT EXECUTION    │
   │                      │      │                          │
   │  Futures / equities  │      │  Options execution       │
   │  Lead agent (LLM)    │      │  Strategy bots (0DTE,    │
   │  Trade synthesis     │      │  weekly MEIC, etc.)      │
   │  Lifecycle mgmt      │      │  Multi-leg order mgmt    │
   │  Broker adapters     │      │  Greeks lifecycle        │
   │                      │      │  Roll/adjust/exit        │
   │                      │      │  Broker adapters         │
   └──────────┬───────────┘      └────────────┬─────────────┘
              │  execution events              │  execution events
              └──────────────┬────────────────┘
                             │
                             ▼
          ┌────────────────────────────────────────────────┐
          │                 PRIMEAGENT                     │
          │           (portfolio management)               │
          │                                                │
          │  Unified P&L across all products               │
          │  Portfolio Greeks aggregation                  │
          │  Capital allocation + Kelly sizing inputs      │
          │  Strategy budget management                    │
          │  Performance attribution by source/regime      │
          │  Multi-account / SMA / fund management         │
          │                                                │
          │  Publishes: portfolio:state:ACCOUNT            │
          │             portfolio:allocation:ACCOUNT       │
          └────────────────┬───────────────────────────────┘
                           │  portfolio state
                           ▼
          ┌────────────────────────────────────────────────┐
          │                 AEGISAGENT                     │
          │      (independent risk — override authority)   │
          │                                                │
          │  Real-time VaR and exposure monitoring         │
          │  Drawdown limit enforcement                    │
          │  Margin monitoring and alerts                  │
          │  Stress testing (pre-trade + continuous)       │
          │  Pre-trade check: HTTP API (synchronous)       │
          │  Emergency trading halt                        │
          │  Correlation and concentration limits          │
          │                                                │
          │  Publishes: risk:halt:ACCOUNT      ──→  ALL    │
          │             risk:block:ACCOUNT     ──→  execution│
          │             risk:reduce:ACCOUNT    ──→  products│
          └────────────────────────────────────────────────┘
                            │
                            ▼
          ┌────────────────────────────────────────────────┐
          │              COLD TIER                         │
          │           TimescaleDB                          │
          │                                                │
          │  intelligence_features (all product signals)   │
          │  signal_ledger (all trades, outcomes)          │
          │  portfolio_snapshots (Greeks, P&L, exposure)   │
          │  strategy_performance (per-strategy metrics)   │
          │                                                │
          │  → ML training dataset for all products        │
          │  → Backtesting engine input                    │
          │  → Learning loop: system improves over time    │
          └────────────────────────────────────────────────┘
```

---

## The clean separation

### Shared — on the bus, any product can subscribe

| Stream | Publisher | Consumers |
|--------|-----------|-----------|
| `market:price:SYMBOL:TF` | IBKR TWS daemon | All products |
| `market:bar:SYMBOL:TF` | IBKR TWS daemon | All products |
| `intelligence:SYMBOL:TF` | IndicAgent | TradeAgent, DerivAgent, QualAgent |
| `signals:SYMBOL:TF:aggregated` | IndicAgent | TradeAgent, DerivAgent |
| `qual:regime:SYMBOL` | QualAgent | TradeAgent, DerivAgent |
| `qual:score:GLOBAL` | QualAgent | TradeAgent, DerivAgent |
| `qual:event:SYMBOL` | QualAgent | TradeAgent, DerivAgent |
| `deriv:vol_regime:SYMBOL` | DerivAgent | TradeAgent |
| `deriv:gex:SYMBOL` | DerivAgent | TradeAgent |
| `deriv:vrp:SYMBOL` | DerivAgent | DerivAgent Execution |

### Product-owned — internal data, never shared raw

| Data | Owner | Why not shared |
|------|-------|----------------|
| COT raw files | QualAgent | Consumers get regime state, not COT CSV |
| Prediction market feeds | QualAgent | Consumers get probability signal, not raw contracts |
| News NLP corpus | QualAgent | Consumers get sentiment score, not raw text |
| Options chain ticks | DerivAgent | Consumers get vol regime/GEX, not 10k rows of strike data |
| Vol surface model | DerivAgent | Consumers get surface state and VRP, not raw fit parameters |
| Broker account state | TradeAgent / DerivAgent Execution | Per-tenant, private — never on shared bus |
| Open positions | TradeAgent / DerivAgent Execution | Per-tenant, private |

### The principle

> Each product distills its domain into a regime state or scored signal and publishes that to the bus. Consumers get the intelligence, not the raw data. The raw pipelines stay inside the product that owns them.

Cross-product synthesis is a **read model**, not a controller. It may materialize a combined regime view for TradeAgent, DerivAgent, PrimeAgent, dashboard, or ML consumers, but it must never become required infrastructure for IndicAgent, QualAgent, or DerivAgent ingestion/compute to run. If the synthesis layer is down, domain products keep publishing their own streams and consumers degrade by missing combined context.

---

## Renaissance-style data flow — stream subscriptions

> **This is the canonical living reference for all stream publish/subscribe relationships.**  
> Update this section whenever a stream is added, renamed, retired, or a new subscriber is added.  
> All keys are environment-prefixed in practice: `development:market:price:ES:5m`, `production:intelligence:ES:5m`, etc.

Everything is event-driven. Nothing polls. Data flows down through the tiers — each layer enriches it, publishes it, and moves on. Actions are triggered by events on the bus, not by timers or HTTP calls.

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  HOT TIER — raw market data, sub-millisecond
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

IBKR TWS Daemon  (one connection, lives in IndicAgent)
  │
  ├─→ PUBLISHES: market:price:SYMBOL:TF      (real-time last/bid/ask)
  │     SUBSCRIBERS: IndicAgent · QualAgent · DerivAgent · AegisAgent
  │
  ├─→ PUBLISHES: market:bar:SYMBOL:TF        (completed OHLCV bar)
  │     SUBSCRIBERS: IndicAgent · QualAgent · DerivAgent
  │
  └─→ PUBLISHES: market:tick:SYMBOL          (raw tick: price + size)
        SUBSCRIBERS: IndicAgent · DerivAgent

DerivAgent  (options-specific data, separate ingestion)
  │
  └─→ PUBLISHES: market:option_chain:SYMBOL:expiry  (full chain snapshot)
        SUBSCRIBERS: DerivAgent (internal analytics only)


━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  WARM TIER — intelligence outputs and regime signals
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

IndicAgent  (consumes hot: market:bar + market:tick)
  │
  ├─→ PUBLISHES: intelligence:SYMBOL:TF       (full I1–I8 IntelligenceEvent)
  │     SUBSCRIBERS: TradeAgent · DerivAgent Execution · QualAgent · AegisAgent
  │
  ├─→ PUBLISHES: signals:SYMBOL:TF:aggregated (selected I7 setup signal)
  │     SUBSCRIBERS: TradeAgent · DerivAgent Execution
  │
  └─→ PUBLISHES: narratives:SYMBOL:TF         (I8 AI narrative)
        SUBSCRIBERS: TradeAgent (lead agent context) · Dashboard

QualAgent  (consumes hot: market:bar + own ingestion: COT, Kalshi, news)
  │
  ├─→ PUBLISHES: qual:regime:SYMBOL           (BULLISH/BEARISH/NEUTRAL/UNCERTAIN)
  │     SUBSCRIBERS: TradeAgent · DerivAgent Execution · AegisAgent
  │
  ├─→ PUBLISHES: qual:score:GLOBAL            (QualScore 0–100)
  │     SUBSCRIBERS: TradeAgent · DerivAgent Execution
  │
  ├─→ PUBLISHES: qual:event:SYMBOL            (upcoming catalyst: type, date, impact)
  │     SUBSCRIBERS: TradeAgent · DerivAgent Execution · AegisAgent
  │
  └─→ PUBLISHES: qual:narrative:GLOBAL        (macro narrative summary)
        SUBSCRIBERS: TradeAgent (lead agent context) · Dashboard

DerivAgent Analytics  (consumes hot: market:bar + market:option_chain)
  │
  ├─→ PUBLISHES: deriv:vol_regime:SYMBOL      (HIGH/LOW/COMPRESSING/EXPANDING)
  │     SUBSCRIBERS: TradeAgent · DerivAgent Execution · AegisAgent
  │
  ├─→ PUBLISHES: deriv:gex:SYMBOL             (gamma exposure + flip point)
  │     SUBSCRIBERS: TradeAgent · DerivAgent Execution · AegisAgent
  │
  ├─→ PUBLISHES: deriv:vrp:SYMBOL             (vol risk premium state)
  │     SUBSCRIBERS: DerivAgent Execution · TradeAgent
  │
  ├─→ PUBLISHES: deriv:skew:SYMBOL            (put/call skew reading)
  │     SUBSCRIBERS: DerivAgent Execution
  │
  └─→ PUBLISHES: deriv:term_structure:SYMBOL  (contango/backwardation/flat)
        SUBSCRIBERS: DerivAgent Execution · TradeAgent


━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  EXECUTION TIER — actions triggered by warm-tier events
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

TradeAgent  (subscribes to: all intelligence + qual + deriv warm streams)
  │
  ├─→ PUBLISHES: execution:fill:ACCOUNT       (fill confirmed)
  │     SUBSCRIBERS: PrimeAgent · AegisAgent
  │
  ├─→ PUBLISHES: execution:open:ACCOUNT       (new position opened)
  │     SUBSCRIBERS: PrimeAgent · AegisAgent
  │
  └─→ PUBLISHES: execution:close:ACCOUNT      (position closed + outcome)
        SUBSCRIBERS: PrimeAgent · AegisAgent · Learning loop (cold tier)

DerivAgent Execution  (subscribes to: all intelligence + qual + deriv warm streams)
  │
  ├─→ PUBLISHES: execution:fill:ACCOUNT       (same contract as TradeAgent)
  │     SUBSCRIBERS: PrimeAgent · AegisAgent
  │
  ├─→ PUBLISHES: execution:open:ACCOUNT
  │     SUBSCRIBERS: PrimeAgent · AegisAgent
  │
  └─→ PUBLISHES: execution:close:ACCOUNT
        SUBSCRIBERS: PrimeAgent · AegisAgent · Learning loop

  ↑ Both execution products call AegisAgent via HTTP before acting:
  │   POST /risk/pretrade  →  {approved, approved_size, warnings}
  │   Synchronous, blocking. If AegisAgent is unreachable, order is rejected (fail-safe).
  │   Rule: the bus is for events (async, many consumers).
  │         HTTP is for requests (need an answer now, one caller, one responder).
  │
  AegisAgent  (subscribes to: market:price + all warm streams + portfolio:state)
  │
  ├─→ HTTP API: POST /risk/pretrade             (synchronous pre-trade check)
  │     CALLERS: TradeAgent · DerivAgent Execution  [BLOCKING before every order]
  │
  ├─→ PUBLISHES: risk:alert:ACCOUNT            (non-blocking warning)
  │     SUBSCRIBERS: Dashboard · PrimeAgent
  │
  ├─→ PUBLISHES: risk:block:ACCOUNT            (soft halt — no new positions)
  │     SUBSCRIBERS: TradeAgent · DerivAgent Execution  [BINDING]
  │
  ├─→ PUBLISHES: risk:halt:ACCOUNT             (full emergency halt)
  │     SUBSCRIBERS: TradeAgent · DerivAgent Execution  [BINDING — immediate stop]
  │
  └─→ PUBLISHES: risk:reduce:ACCOUNT           (instruct position reduction)
        SUBSCRIBERS: TradeAgent · DerivAgent Execution  [BINDING]


━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  PORTFOLIO TIER — unified view and capital allocation
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

PrimeAgent  (subscribes to: all execution events + intelligence + qual + deriv)
  │
  ├─→ PUBLISHES: portfolio:state:ACCOUNT       (live positions, Greeks, deployment %)
  │     SUBSCRIBERS: AegisAgent · Dashboard
  │
  ├─→ PUBLISHES: portfolio:allocation:ACCOUNT  (current capital budget per strategy)
  │     SUBSCRIBERS: TradeAgent · DerivAgent Execution
  │
  ├─→ PUBLISHES: portfolio:performance:ACCOUNT (P&L by strategy, attribution)
  │     SUBSCRIBERS: Dashboard · Learning loop
  │
  └─→ PUBLISHES: portfolio:signal:ACCOUNT      (regime-adaptive allocation recommendations)
        SUBSCRIBERS: TradeAgent · DerivAgent Execution


━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  COLD TIER — institutional memory, all products write here
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

TimescaleDB  (async batch writes from all warm/execution/portfolio streams)

  intelligence_features    ← IndicAgent (I1–I8 per bar)
  qual_features            ← QualAgent (regime, score, events per timestamp)
  deriv_features           ← DerivAgent (vol surface, Greeks snapshots)
  signal_ledger            ← TradeAgent + DerivAgent Execution (all trades + outcomes)
  position_ledger          ← TradeAgent + DerivAgent Execution (fills, lifecycle)
  portfolio_snapshots      ← PrimeAgent (point-in-time portfolio state)
  strategy_performance     ← Learning loop (per-strategy metrics, Sharpe, win rate)
  risk_events              ← AegisAgent (all alerts, halts, breaches, pre-trade results)
  var_snapshots            ← AegisAgent (daily VaR calculations)

  → All products can query cold tier for backtesting, research, and model training
  → Learning loop reads outcomes and feeds updated weights back to warm tier consumers
```

---

## The cross-product alpha advantage

Individual signals have value. Combined signals are where institutional-grade edge lives:

| Combination | Why it matters |
|-------------|---------------|
| IndicAgent I6 confluence HIGH + QualAgent macro regime BULLISH | Technical + fundamental alignment |
| DerivAgent vol regime COMPRESSED + VRP ELEVATED + IndicAgent trend STRONG | Classic vol premium harvest setup |
| QualAgent catalyst EVENT (Fed) + DerivAgent vol ELEVATED + IndicAgent range-bound | Pre-event straddle / strangle opportunity |
| All three alignment score > threshold | Highest-conviction signal tier |

TradeAgent's lead agent (LLM-assisted) has access to all three warm-tier streams simultaneously and reasons over the full combined picture before any position is taken.

---

## Portfolio and risk management

Portfolio management is a cross-product concern — a user running both TradeAgent futures and DerivAgent options needs a unified risk view.

### Capital allocation

- **Kelly sizing:** Signal confidence + edge estimate → position size. Kelly fraction calculated per-strategy, with a fractional Kelly cap to prevent over-sizing.
- **Volatility-adjusted sizing:** Scale down position size when realized or implied volatility expands. System automatically de-risks in regime-uncertain environments.
- **Strategy allocation budget:** Capital allocated by strategy type (directional futures, delta-neutral options, premium collection), with hard limits per category.
- **Cross-product capital view:** TradeAgent and DerivAgent Execution share a single capital ledger. Total deployment % is tracked and enforced at the platform level, not per-product.

### Greek management (for options)

- **Portfolio Greeks:** Delta, gamma, theta, vega aggregated across all open options positions in real time.
- **Delta neutralization:** Platform monitors net portfolio delta. When delta exceeds threshold (from options positions accumulating directionality), the system alerts or auto-hedges via the underlying future.
- **Theta decay targeting:** Portfolio theta target set as a function of capital deployed. Positions selected to maintain target theta income per day.
- **Vega exposure limits:** Hard limits on total portfolio vega. Prevents over-concentration in long or short vol.
- **Gamma risk:** Elevated near expiration. System tracks net gamma by expiry date and warns/reduces before critical gamma risk windows.

### Risk limits and monitoring

- **Max drawdown limits:** Per-strategy, per-account, and portfolio-wide drawdown caps. Breach → auto-reduce or full halt.
- **VaR:** 1-day Value at Risk at 95% and 99% confidence, calculated from position-level sensitivities and historical scenario analysis.
- **Margin monitoring:** Real-time margin utilization tracking. Alert at 70%, reduce at 85%, halt new positions at 90%.
- **Concentration limits:** Maximum % of capital in any single underlying, sector, or strategy type.
- **Correlation checks:** Before adding a new position, correlation to existing portfolio is checked. Prevents unintentional doubling of exposure.
- **Stress testing:** Pre-trade stress scenarios (e.g. +/-5% gap open, vol spike +10 points, liquidity halt) evaluated against portfolio before execution.

### Real-time attribution

- P&L attributed per strategy, per underlying, per product (futures P&L vs options theta P&L vs options delta P&L)
- Daily/weekly performance reports by category
- Strategy-level Sharpe, win rate, avg MAE/MFE, drawdown — the same metrics used in the learning loop

---

## Trade execution layer

### Canonical order model (broker-agnostic)

All execution logic — whether from TradeAgent (futures) or DerivAgent (options) — outputs a canonical order that is broker-agnostic. Broker adapters translate the canonical form to broker-specific API calls. No execution logic touches broker APIs directly.

```
Canonical order:
{
  side: BUY | SELL | BUY_TO_OPEN | SELL_TO_OPEN | BUY_TO_CLOSE | SELL_TO_CLOSE,
  symbol: string,
  instrument_type: FUTURE | OPTION | EQUITY,
  quantity: int,
  order_type: MARKET | LIMIT | STOP | STOP_LIMIT,
  limit_price?: float,
  stop_price?: float,
  time_in_force: DAY | GTC | IOC | FOK,
  legs?: [canonical_order]   // multi-leg for options spreads
}
```

Multi-leg orders (spreads, condors, calendars) are first-class citizens. The execution engine submits them as combo/spread orders to brokers that support it, or as sequential legs with hedging logic where it doesn't.

### Smart order routing

Orders are routed by tenant-configured rules. Examples:
- `instrument_type = FUTURE` → IBKR
- `instrument_type = OPTION AND underlying = SPX` → Tastyworks
- `instrument_type = OPTION AND 0DTE = true` → Schwab (best 0DTE fill quality)
- Default → configured fallback broker

### Fill quality monitoring

- Slippage tracked per strategy type, per broker, per market session
- Fill quality score per broker → informs routing rule optimization
- Poor fill quality on a strategy triggers alert for human review

---

## Strategy automation — bots

Repetitive, well-defined strategies are prime automation candidates. The platform supports a **strategy bot framework**: pre-configured strategy programs that run on schedule or trigger, with full lifecycle automation.

### Bot types

**Scheduled bots** — run at a defined time
- `0DTE MEIC Bot`: Monday–Friday, 9:50am ET. Evaluate regime. If vol regime qualifies (IV Rank >30, GEX neutral-to-negative), enter the MEIC spread. Auto-manage through expiry.
- `Weekly Premium Collection Bot`: Monday open. Select and enter iron condors / strangles on the defined underlying list for the expiry cycle. Roll or close on Friday.
- `Pre-market regime check Bot`: 8:30am ET daily. Reads vol regime, QualAgent macro state, IndicAgent overnight signal. Outputs regime brief + recommended strategy set for the day.

**Event-triggered bots** — run when a signal condition fires
- `Regime shift bot`: When QualAgent regime flips BEARISH, scan for defensive spread opportunities (long put spreads, ratio spreads). Notify or auto-execute based on automation level.
- `VRP opportunity bot`: When `deriv:vrp:SYMBOL` crosses a threshold and IndicAgent shows low-volatility regime, initiate premium collection strategy evaluation.
- `Earnings play bot`: When an earnings catalyst event is detected 2–5 days out, evaluate the vol crush opportunity. Propose pre-earnings premium collection with defined exit at event.

### Automation levels (human-in-the-loop spectrum)

| Level | Description |
|-------|-------------|
| **Notify** | Bot evaluates conditions, sends alert — human decides |
| **Propose** | Bot builds full trade proposal (strikes, expiry, size, risk) — one-click approve/reject |
| **Semi-auto** | Bot executes entry automatically; lifecycle events (adjust, roll, close) require approval |
| **Full auto** | Bot executes entry and manages full lifecycle autonomously within defined guardrails |

Default level is **Propose**. Users unlock Semi-auto and Full-auto through a configuration step that requires acknowledgment of risk. Guardrails are always enforced regardless of automation level.

### Recurring strategy lifecycle (0DTE MEIC example)

```
09:45 ET  Regime check
          → Read deriv:vol_regime, deriv:gex, qual:regime, intelligence
          → Score opportunity: PASS | SKIP | REDUCED_SIZE

09:50 ET  Entry decision (if PASS)
          → Strike selection agent (ATM ± delta target, width based on IV)
          → Position sizing (Kelly-adjusted, account for existing portfolio Greeks)
          → Multi-leg order construction (4-leg MEIC)
          → Pre-trade stress test
          → Submit to execution engine

Active    Lifecycle monitoring (every 5 min)
          → P&L vs target
          → Delta drift check → hedge if delta > threshold
          → Early exit if 50% profit captured
          → Stop loss if loss > 2× credit received

14:00 ET  Gamma risk check (elevated near close)
          → If net gamma risk exceeds threshold → close position

15:45 ET  Final exit window
          → Close all 0DTE positions before close
          → Record outcome → signal_ledger

EOD       Learning loop update
          → Outcome fed back to strategy performance tracker
          → Regime-at-entry correlated with outcome
          → Strike selection quality scored
```

---

## Learning loop — the system improves over time

Every executed trade, every resolved position, every strategy outcome lands in the cold tier. The learning loop reads outcomes and improves future decisions:

| Input | What it improves |
|-------|-----------------|
| Strategy P&L by regime state | Regime-to-strategy mapping weights |
| Strike selection quality (fill vs theo) | Strike/expiry selection intelligence |
| Bot entry timing vs outcome | Entry condition threshold calibration |
| Portfolio Greek drift patterns | Greek management limit tuning |
| Slippage by broker/session | Routing rule optimization |
| QualAgent regime at entry vs outcome | Qualitative regime signal weight |

The system doesn't require manual retuning. Data flows in, correlations are identified, weights are updated.

---

## Canonical stream namespace

Defined upfront so all products can be built to the same contract. All keys are environment-prefixed (`development:`, `production:`).

### Hot tier — raw market data

| Key | Publisher | Description |
|-----|-----------|-------------|
| `market:price:SYMBOL:TF` | TWS daemon | Real-time price (last, bid, ask) |
| `market:bar:SYMBOL:TF` | TWS daemon | Completed OHLCV bar |
| `market:tick:SYMBOL` | TWS daemon | Raw tick (price + size) |
| `market:option_chain:SYMBOL:expiry` | DerivAgent | Full options chain snapshot |

### Warm tier — intelligence outputs

| Key | Publisher | Description |
|-----|-----------|-------------|
| `intelligence:SYMBOL:TF` | IndicAgent | Full I1–I8 typed IntelligenceEvent |
| `signals:SYMBOL:TF:aggregated` | IndicAgent | Selected I7 setup signal |
| `narratives:SYMBOL:TF` | IndicAgent | I8 AI narrative |
| `qual:regime:SYMBOL` | QualAgent | Qualitative regime state (BULLISH / BEARISH / NEUTRAL / UNCERTAIN) |
| `qual:score:GLOBAL` | QualAgent | QualScore 0–100 across all qualitative sources |
| `qual:event:SYMBOL` | QualAgent | Upcoming catalyst event (type, date, expected impact) |
| `qual:narrative:GLOBAL` | QualAgent | Macro narrative summary |
| `deriv:vol_regime:SYMBOL` | DerivAgent | Volatility regime (HIGH / LOW / COMPRESSING / EXPANDING) |
| `deriv:gex:SYMBOL` | DerivAgent | Gamma exposure level and flip point |
| `deriv:vrp:SYMBOL` | DerivAgent | Volatility risk premium state |
| `deriv:skew:SYMBOL` | DerivAgent | Put/call skew reading |
| `deriv:term_structure:SYMBOL` | DerivAgent | Vol term structure shape (contango/backwardation/flat) |
| `execution:fill:ACCOUNT` | TradeAgent / DerivAgent | Fill confirmed |
| `execution:open:ACCOUNT` | TradeAgent / DerivAgent | New position opened |
| `execution:close:ACCOUNT` | TradeAgent / DerivAgent | Position closed + outcome |
| `portfolio:state:ACCOUNT` | PrimeAgent | Live positions, Greek aggregates, deployment % |
| `portfolio:allocation:ACCOUNT` | PrimeAgent | Current capital budget per strategy |
| `portfolio:performance:ACCOUNT` | PrimeAgent | P&L by strategy and source |
| `portfolio:signal:ACCOUNT` | PrimeAgent | Regime-adaptive allocation recommendations |
| `risk:state:ACCOUNT` | AegisAgent | Live risk metrics snapshot |
| `risk:alert:ACCOUNT` | AegisAgent | Non-blocking risk warning |
| `risk:block:ACCOUNT` | AegisAgent | Soft halt — block new positions **(binding)** |
| `risk:halt:ACCOUNT` | AegisAgent | Full emergency halt **(binding, immediate)** |
| `risk:reduce:ACCOUNT` | AegisAgent | Instruct position reduction **(binding)** |

> **Bus vs HTTP rule:** Everything in the table above flows through Redpanda — events (things that happened), async, many potential consumers. The one exception: **AegisAgent pre-trade check** is a synchronous HTTP call (`POST /risk/pretrade`). Request/reply patterns with one caller and one responder belong on HTTP, not the bus.

### Cold tier — TimescaleDB tables

| Table | Owner | Content |
|-------|-------|---------|
| `intelligence_features` | IndicAgent | I1–I8 feature vectors per bar |
| `qual_features` | QualAgent | Qualitative signals per timestamp |
| `deriv_features` | DerivAgent | Vol surface + Greek snapshots |
| `signal_ledger` | All execution | All trade signals + outcomes |
| `position_ledger` | TradeAgent / DerivAgent | All positions, fills, lifecycle events |
| `portfolio_snapshots` | PrimeAgent | Point-in-time portfolio state (Greeks, P&L, deployment) |
| `strategy_performance` | Learning loop | Per-strategy metrics: Sharpe, win rate, MAE/MFE |
| `risk_events` | AegisAgent | All alerts, halts, limit breaches, pre-trade results |
| `var_snapshots` | AegisAgent | Daily VaR calculations at 95% and 99% |
| `performance_attribution` | PrimeAgent | P&L attributed by strategy, regime, and intelligence source |

---

## Deployment model

**Phase 0 (pre-QualAgent — recommended):** Migrate IndicAgent's event bus from DragonflyDB Streams to Redpanda. Replace `price:SYMBOL:latest` Redis hash with in-process state in signal_generator. Drop DragonflyDB from the stack — it has no remaining role at this scale. Infrastructure becomes: **Redpanda + PostgreSQL**. All 8 IndicAgent services updated, 1083 tests verify migration. See `docs/research/tech-stack.md` for migration detail and the three specific triggers when DragonflyDB gets added back. Add pgvector extension to existing PostgreSQL.

**Phase 1 (now — live):** IndicAgent runs standalone. TWS daemon publishes 1m bars + ticks. `timeframes_builder_service` aggregates to 5m→1D. Dashboard and SSE/API serve signals to external consumers.

**Phase 2:** QualAgent built as a separate service. Subscribes to `market.bars` Redpanda topics. Publishes `qual.*` topics. First cross-product signal combination possible.

**Phase 3:** DerivAgent built as a separate service. Subscribes to market data and `intelligence` topics. Publishes `deriv.*` topics. Three-domain intelligence stack complete.

**Phase 4:** TradeAgent built. Subscribes to `intelligence`, `qual.*`, `deriv.*` topics. Lead agent reasons over full combined picture. Broker adapters connect to brokers. **Basic risk guardrails must be built in at this phase** — drawdown limits and position sizing live inside TradeAgent until AegisAgent exists.

**Phase 5:** PrimeAgent and AegisAgent built as the first execution products go live with real capital. PrimeAgent provides unified portfolio view. AegisAgent provides the independent risk layer — pre-trade check protocol, VaR, drawdown enforcement, emergency halt. **AegisAgent is a prerequisite for production deployment at any meaningful scale.**

**Phase 6 (optional extraction):** If any product needs to run without IndicAgent, the TWS daemon and timeframes_builder_service are extracted into a minimal shared `MarketCore` service. Until then, they live in IndicAgent.

Adding a new product is always additive — subscribe to what you need, publish what you produce. No existing products need to change.

---

## Technology stack

> Full reasoning, migration guide, and decision log: `docs/research/tech-stack.md`

### The two-component infrastructure (target)

The initial target platform runs on two infrastructure components. Everything else is a Python service or library.

```
Redpanda          Event bus — ALL streams (hot + warm + execution + portfolio + risk)
                  Kafka-compatible. Single binary. No ZooKeeper. Apache 2.0.
                  Durable, replayable log. Consumer groups for work distribution.
                  Replaces all DragonflyDB Streams.

PostgreSQL        Cold tier — institutional memory
+ TimescaleDB       Time-series feature store, signal ledger, continuous aggregates
+ pgvector          Vector/embedding search for regime analog matching (extension, zero new infra)
                  Apache 2.0 (TimescaleDB core). MIT (pgvector).
```

**DragonflyDB added as a third component when a specific trigger is real** — tick SaaS fan-out tier, DerivAgent options chain state store, or high-scale external subscriber fan-out. See `docs/research/tech-stack.md` for the three triggers and when each applies.

### Why Redpanda over Apache Kafka

Same Kafka API — 100% compatible, no code changes to switch. But:

| | Apache Kafka | Redpanda |
|---|---|---|
| **Requires ZooKeeper** | Yes (or KRaft in newer versions) | Never |
| **Runtime** | JVM (GC pauses, tuning overhead) | C++ single binary |
| **Latency** | ~5–15ms | ~1–5ms |
| **Deployment** | Complex cluster setup | Single binary locally, simple 3-node cluster in prod |
| **License** | Apache 2.0 | Apache 2.0 (core) |

### Why DragonflyDB is not in the initial target stack

DragonflyDB (Redis-compatible) currently serves two roles:

1. **Streams** — all 9 stream types (ticks, bars, indicators, intelligence, signals, narratives, …) → **migrate to Redpanda**
2. **One Redis hash** — `price:SYMBOL:latest` (live bid/ask, read by signal_generator) → **replaced with in-process state** — signal_generator maintains a `{symbol: {bid, ask}}` dict updated from the tick stream. No external lookup needed.

At current scale DragonflyDB has no remaining role. Three infrastructure components become two.

DragonflyDB is well-suited for three specific use cases that don't exist yet: tick streaming SaaS fan-out (push pub/sub, < 5ms), DerivAgent options chain state (random-access key/value for 20K+ contracts), and high-scale external subscriber fan-out. It gets added back when one of those triggers is real.

### Why pgvector over a dedicated vector database

pgvector is a PostgreSQL extension (MIT). It adds a `vector` column type and approximate nearest-neighbor search to the existing database. Zero new service, zero new operational overhead.

Use cases: QualAgent regime analog matching ("find the 5 most historically similar macro configurations to today's"), DerivAgent vol surface pattern matching, TradeAgent lead agent historical context.

Upgrade to Qdrant only if pgvector is measurably insufficient at scale — unlikely for years.

### The bus vs HTTP rule

Not everything belongs on the bus. The rule:

> **Bus (Redpanda):** events — things that happened, async, potentially many consumers.  
> **HTTP (FastAPI):** requests — I need an answer right now, one caller, one responder.

| Pattern | Transport | Example |
|---------|-----------|---------|
| Intelligence signal published | Bus | `intelligence:ES:5m` → TradeAgent subscribes |
| Risk limit breached | Bus | `risk:halt:ACCOUNT` → all execution products |
| Pre-trade check before an order | **HTTP** | `POST /risk/pretrade` → AegisAgent responds synchronously |
| Health check | HTTP | `GET /health` |

AegisAgent's pre-trade check is the clearest example: TradeAgent needs a blocking answer before submitting an order. That is HTTP. If AegisAgent is unreachable, the order is rejected (fail-safe default) — this can't be achieved with an async bus event.

### What is NOT in the stack (and why)

| Rejected | Reason |
|----------|--------|
| **Apache Kafka** | Redpanda is 100% compatible with dramatically lower operational overhead |
| **DragonflyDB / Redis** | Not in initial target stack — added only when a specific trigger is real (see `tech-stack.md`) |
| **RabbitMQ / ActiveMQ** | No traditional MQ patterns needed. Redpanda consumer groups handle work distribution |
| **ClickHouse** | TimescaleDB continuous aggregates cover analytics. Add only when provably insufficient |
| **Qdrant / Weaviate** | pgvector in existing PostgreSQL is sufficient for near-term scale |
| **Temporal** | LangGraph + APScheduler cover strategy workflows. Temporal is the institutional-scale upgrade |
| **Elasticsearch / OpenSearch** | pgvector + pg_trgm handle search inside PostgreSQL |
| **MongoDB / Cassandra** | PostgreSQL + TimescaleDB handles all data model needs |

### Current stack vs target stack

| Layer | Current (IndicAgent live) | Target (before QualAgent) |
|-------|--------------------------|--------------------------|
| Event bus | DragonflyDB Streams | **Redpanda** |
| Key/value cache | DragonflyDB | **Dropped** (in-process state in signal_generator) |
| Time-series DB | PostgreSQL + TimescaleDB | Same — keep |
| Vector search | — | **pgvector** (PostgreSQL extension) |
| Workflows | systemd services | LangGraph + APScheduler |
| Observability | Prometheus | Prometheus + **Grafana** |
| Service APIs | FastAPI | Same — keep |

Migration scope: 2 core files (`stream_utils.py` 51 lines, `stream_keys.py` 136 lines) + 8 service files. Estimated 1–2 weeks. 1083 tests verify the migration. DragonflyDB is not replaced by anything — it's just dropped. See `docs/research/tech-stack.md` for the full migration breakdown and the three DragonflyDB triggers.

---

## Key principles (the Renaissance rules for this platform)

1. **Data first.** Raw data is collected once, published to the shared bus, consumed by any product that needs it. No duplication.
2. **The bus is the contract.** Products don't call each other — they publish to and subscribe from streams. Loose coupling, high cohesion.
3. **Intelligence at the edge.** Each product distills its domain into a clean signal before publishing. Consumers get regime states and scores, not raw data.
4. **Cross-domain alpha.** The real edge is in the intersections. The platform is designed to surface multi-domain signal alignment, not single-source signals.
5. **Events drive actions.** Nothing polls. When a regime shifts, that event fires. Downstream systems react immediately.
6. **Everything learns.** Every outcome lands in the cold tier. The system gets better without manual retuning.
7. **Risk is a first-class citizen.** Portfolio risk management is cross-product, not per-product. Capital, Greeks, and drawdown are tracked at the platform level.
8. **Humans stay in control.** Automation levels are explicit. Guardrails are always enforced. The human can always see what the system is doing and why.
