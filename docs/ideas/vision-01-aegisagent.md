# AegisAgent — Independent Risk Management Platform (Vision)

**Status:** draft
**Version:** 1.0
**Created:** 2026-03-04
**Last Updated:** 2026-06-17
**Context:** Independent risk layer with override authority over all execution products
**Priority:** low
**Milestone:** future (post-v2.8)
**Tags:** risk-management, portfolio, execution, platform, vision, autonomous

---

## Core Concept

**Aegis** — the divine shield of Zeus and Athena in Greek mythology. Wielded not for offense but for protection; impenetrable, independent, authoritative. In financial markets, the term is used by risk systems and protective overlays at institutional scale.

The name is intentional: AegisAgent is not a strategy product. It does not optimize for returns. Its sole mandate is **protection** — of capital, of accounts, of the platform. It has override authority over every other product.

AegisAgent subscribes to every relevant data stream — market data, intelligence, portfolio state, execution events — and continuously monitors for risk limit breaches, structural vulnerabilities, and system-level threats.

When a limit is breached, AegisAgent has the authority to:
- Alert the user
- Block new positions
- Force position reductions
- Trigger an emergency trading halt

It does not ask permission. It does not wait for execution products to respond. It acts.

### Renaissance Frame

AegisAgent embodies Renaissance principles:

- **Ruthlessly eliminate unnecessary complexity:** Risk is not a feature to be added to each product. It is a single, authoritative system that all products obey. Complexity in risk management is dangerous — it creates loopholes.
- **Guard against hidden biases and edge-case failures:** The most dangerous failure mode in trading is a smart person who is confident and wrong. Independent risk enforcement prevents this.
- **Silent failures are worse than loud crashes:** A risk system that fails silently (allows violations it should block) is worse than one that halts everything. AegisAgent defaults to blocking on failure — fail-safe, not fail-dangerous.
- **What fails silently here, and how would we know?** AegisAgent logs every risk event, every pre-trade check, every halt. Complete audit trail. Nothing is hidden.
- **Separation of concerns is non-negotiable:** Risk management is separate from execution, separate from portfolio optimization, separate from signal generation. Each component has one job.
- **Microservices over monoliths:** AegisAgent is an independent Ring 2 daemon. It can be deployed, scaled, and failed independently. Its independence is architectural, not just a design principle.

### Architectural Positioning

AegisAgent fits the shared spine architecture:

- **Ring 2 daemon** — Would live under `services/` when implemented; class and file names derive from the naming system at build time (the `_agent` suffix is retired)
- **Event subscriber** — Subscribes to `portfolio:*`, `execution:*`, `market:*`, `deriv:*`, `qual:*`, `intelligence:*` topics
- **Event publisher** — Publishes to `risk:*` topics via `stream_keys.py`
- **Independent authority** — Not called by other services. Publishes binding events that execution products must obey.
- **DAG-compliant** — Data flows one direction: streams → risk assessment → Kafka → consumers. No cycles.
- **APR-governed** — All risk limits, thresholds, and parameters live in `config_state` under `risk.*` namespace. No hardcoded values.
- **Shadow-governed** — Risk enforcement cannot be shadowed (it's binary), but risk *limits* are APR-governed and adjust based on statistical validation.
- **Fail-safe default** — If AegisAgent is unavailable, new positions are blocked. The safe default is "stop."

---

## Why risk must be independent

In institutional finance, the risk desk has **independent authority** over portfolio managers and traders. The PM cannot override the risk limit. The risk desk can force the PM to reduce or close positions even if the PM disagrees. This independence is not bureaucracy — it is the structural protection against the most dangerous failure mode in trading: a smart person who is confident and wrong.

If risk management lives inside the execution products, it can be circumvented. If it lives inside PrimeAgent, the portfolio optimization logic can suppress risk signals during drawdowns to "give the trade more room." The risk system must be separate and must have final authority.

This mirrors how Medallion operated: risk limits were enforced at the system level. "Never override the model" applied in both directions — you couldn't override the signal generator, and you couldn't override the risk limit.

AegisAgent subscribes to the shared bus independently. It makes its own assessment of risk. Its outputs cannot be suppressed by other products.

---

## Where AegisAgent sits in the platform

```
MARKET DATA + INTELLIGENCE BUS
  (all warm streams: IndicAgent, QualAgent, DerivAgent)
                    │
         ┌──────────┴──────────┐
         │                     │
    TRADEAGENT          DERIVAGENT EXECUTION
         │                     │
         └──────────┬──────────┘
                    │
              PRIMEAGENT
           (portfolio state)
                    │
              AEGISAGENT  ←── subscribes independently to:
           (risk layer)        - portfolio:state:ACCOUNT
                    │          - market:price:SYMBOL:TF
                    │          - deriv:vol_regime:SYMBOL
                    │          - qual:regime:SYMBOL
                    ↓
            can publish to:
         risk:alert:ACCOUNT
         risk:halt:ACCOUNT       ← TradeAgent and DerivAgent
         risk:reduce:ACCOUNT     ← are required to listen to these
```

AegisAgent's `risk:halt:*` and `risk:reduce:*` stream events are binding. All execution products must implement listeners for these events and respond immediately.

---

## Core capabilities

### 1. Real-time exposure monitoring

AegisAgent tracks live exposure across all accounts and all products:

- **Net delta exposure** (combined futures + options) in dollar terms and as % of account NAV
- **Net vega exposure** — is the account net long or short volatility?
- **Net theta** — is the account earning or paying time decay?
- **Concentration** — what % of capital is in any single underlying, sector, or strategy type?
- **Gross notional** — total notional value of all positions (important for leverage monitoring)
- **Margin utilization** — current margin used vs available, per broker and aggregate

All computed in real time from `portfolio:state:ACCOUNT` and execution events.

### 2. Limit enforcement

Hard limits that AegisAgent enforces. When breached, it does not just alert — it acts:

| Limit | Action on breach |
|-------|-----------------|
| Max drawdown (daily) | Block new positions → alert |
| Max drawdown (weekly) | Force reduce open positions → alert |
| Max drawdown (account) | Emergency halt → require human reset |
| Max delta exposure | Alert → block directional trades |
| Max vega exposure | Alert → block vol-selling strategies |
| Margin utilization > 80% | Alert |
| Margin utilization > 90% | Block new positions |
| Margin utilization > 95% | Emergency reduce: close smallest positions first |
| Single position > X% of NAV | Block size increase → alert |
| Strategy concentration > X% | Block additional allocation → alert |
| Correlated position limit | Block positions that exceed correlation threshold |

Limits are configurable per account. Default values are conservative. Users can widen limits (within bounds) but cannot disable them entirely.

### 3. Value at Risk (VaR)

- **1-day VaR at 95%:** What is the worst expected daily loss 95% of the time?
- **1-day VaR at 99%:** The tail scenario
- Computed from position-level sensitivities and historical return distributions
- Updated continuously as positions change
- Compared against the account's declared risk budget — when VaR exceeds budget, alert and optionally reduce

### 4. Stress testing

Pre-trade and continuous stress scenarios run against the live portfolio:

| Scenario | Instruments affected | Why it matters |
|----------|---------------------|----------------|
| Gap open ±5% | All equity/index positions | Overnight risk |
| Vol spike +15 points | All options positions | Short gamma/short vega exposure |
| Vol crush −10 points | All long options | Long vol exposure |
| Yield curve shift +100bps | Rates-sensitive positions | Macro shock |
| Liquidity halt (1 hour) | Illiquid positions | Can we exit? |
| 2008-style drawdown (−40%) | Portfolio-level | Catastrophic scenario |
| 2020 vol spike (VIX→80) | Options Greeks | Extreme vol event |

Stress test results feed into the pre-trade check: before a new position is added, AegisAgent runs all relevant stress scenarios including the candidate position and flags if any scenario produces an unacceptable outcome.

### 5. Margin monitoring

- Real-time margin utilization per broker connection and aggregate
- Alerts at defined thresholds
- Automatic position reduction protocol when approaching margin call territory
- Overnight margin check: before market close, verify that current positions can be held overnight without a margin call risk given expected overnight moves

### 6. Emergency trading halt

The most important capability. AegisAgent can trigger a full trading halt:

**Conditions that trigger auto-halt:**
- Account drawdown exceeds maximum drawdown limit
- Margin utilization reaches critical threshold
- Market circuit breaker or exchange halt detected
- Execution system error rate exceeds threshold (bad fills, rejected orders)
- Manual trigger from user

**What halt does:**
1. Publishes `risk:halt:ACCOUNT` to the bus immediately
2. TradeAgent and DerivAgent immediately stop accepting new signals and orders
3. Current orders in-flight are cancelled where possible
4. Open positions remain (halt does not auto-liquidate unless specifically configured)
5. Human notification sent via all configured channels
6. System remains in halt state until human explicitly resets

**Gradual halt (partial):**
- Block only new position openings while allowing lifecycle management of existing positions (e.g. close, roll, adjust still allowed)
- Useful when the issue is exposure-based (too much risk) rather than a system failure

### 7. Correlation and concentration analysis

Markets have a tendency to become highly correlated during stress events — the moment diversification is most needed, it often disappears. AegisAgent monitors:

- **Cross-position correlation matrix:** Updated daily from historical data, updated intraday during stress events
- **Effective diversification score:** How uncorrelated are current holdings on a portfolio basis?
- **Concentration limits:** No single underlying > X% of NAV, no single strategy type > Y% of NAV
- **Hidden correlation detection:** Two strategies that appear different (momentum futures + short put spreads) may both be net long delta in a rally — AegisAgent detects and flags the combined exposure

### 8. Pre-trade risk check

Before any execution product submits an order, it sends a pre-trade check request to AegisAgent:

```
Request: {
  account_id: ...,
  proposed_position: { symbol, strategy_type, size, Greeks impact },
  current_portfolio_state: portfolio:state:ACCOUNT snapshot
}

Response: {
  approved: true | false,
  reason: string,
  approved_size: (may be reduced),
  stress_test_results: { scenario: outcome },
  warnings: [ list of non-blocking concerns ]
}
```

This check is synchronous and fast. It is in the critical path before execution. The execution product must receive approval before submitting the order. If AegisAgent is unavailable, new positions are blocked (fail-safe default).

### 9. Risk reporting and audit trail

Every risk event is logged:
- Limit breaches (with timestamp, level, action taken)
- Halt events (cause, duration, resolution)
- Pre-trade check outcomes (approved, rejected, reduced)
- Stress test failures (scenario, position that failed, margin of breach)
- Margin warning events

This creates a complete audit trail for institutional compliance, fund manager review, and regulatory reporting.

---

## What AegisAgent does NOT do

- **Does not optimize portfolios.** That is PrimeAgent.
- **Does not generate signals.** That is the intelligence layer.
- **Does not execute trades.** That is TradeAgent and DerivAgent.
- **Does not manage position lifecycle.** Halts stop new positions; it does not micro-manage open ones (except in emergency reduction protocol).
- **Does not replace human judgment.** It enforces the limits the human set. It alerts to conditions the human needs to know. It is not an AI that decides independently whether the portfolio is "right."

---

## AegisAgent vs PrimeAgent — the boundary

The clearest way to state it:

> **PrimeAgent asks: "How should we allocate capital to maximize performance?"**  
> **AegisAgent asks: "Are we about to blow up, and if so, how do we stop it?"**

These are different questions with different answers and different authorities. PrimeAgent is advisory to the execution products. AegisAgent is binding.

---

## Stream interface

### Subscribes to

| Stream | From | Purpose |
|--------|------|---------|
| `portfolio:state:ACCOUNT` | PrimeAgent | Live positions, Greeks, capital |
| `execution:fill:ACCOUNT` | TradeAgent / DerivAgent | Position changes |
| `market:price:SYMBOL:TF` | IBKR TWS daemon | Mark-to-market |
| `deriv:vol_regime:SYMBOL` | DerivAgent | Vol stress scenarios |
| `qual:regime:SYMBOL` | QualAgent | Macro stress context |
| `intelligence:SYMBOL:TF` | IndicAgent | Regime for stress context |
| `portfolio:performance:ACCOUNT` | PrimeAgent | Drawdown tracking |

### Publishes

| Stream | Consumers | Content |
|--------|-----------|---------|
| `risk:state:ACCOUNT` | Dashboard, PrimeAgent | Live risk metrics snapshot |
| `risk:alert:ACCOUNT` | Dashboard, all products | Non-blocking risk warning |
| `risk:block:ACCOUNT` | TradeAgent, DerivAgent | Block new positions (soft halt) |
| `risk:halt:ACCOUNT` | TradeAgent, DerivAgent | Full trading halt |
| `risk:reduce:ACCOUNT` | TradeAgent, DerivAgent | Instruct reduction of specific positions |
| `risk:pretrade:response` | TradeAgent, DerivAgent | Pre-trade check result |

---

## Cold tier tables

| Table | Content |
|-------|---------|
| `risk_events` | All limit breaches, alerts, halts with full context |
| `pretrade_checks` | All pre-trade check requests and outcomes |
| `var_snapshots` | Daily VaR calculations |
| `stress_test_results` | Stress scenario outcomes by date and portfolio state |
| `margin_history` | Margin utilization over time by broker |

---

## Relationship to Existing Architecture

AegisAgent extends the existing architecture as the independent risk layer:

- **Unified Data Bus compliance** — Services never call each other. AegisAgent subscribes to relevant streams; execution products must listen to its `risk:halt` and `risk:reduce` events. No coupling beyond the bus. See `docs/data/` for bus architecture.
- **DAG invariants preserved** — Risk assessment flows one direction: streams → analysis → Kafka → consumers. No cycles. No service touches the database except Writers/Trackers. See `docs/concepts/dag-execution.md`.
- **APR-governed** — All risk limits, thresholds, and parameters live in `config_state` under `risk.*` namespace. No hardcoded values. See `docs/foundation/adaptive-parameter-registry.md`.
- **Ring compliance** — Lives in Ring 2 as `services/aegis_agent.py`. See `docs/foundation/naming-system.md`.
- **Typed events via `stream_keys.py`** — All topic keys constructed centrally. No hardcoded strings. See `src/core/stream_keys.py`.
- **Independent authority** — Cannot be paused by other products. Only human with explicit authority can disable an AegisAgent limit. This is enforced architecturally, not by convention.
- **Fail-safe default** — If unavailable, blocks new positions. The safe default is "stop."

## Foundation Concepts Referenced

- **Principles** — `docs/foundation/principles.md`: Ruthlessly eliminate complexity, guard against hidden biases, silent failures, separation of concerns
- **Naming System** — `docs/foundation/naming-system.md`: `AegisAgent` is a product name, not a code class; the Ring 2 daemon class/file is derived per the naming system when built. `Agent` is permitted only for genuine autonomous AI agents — AegisAgent is deterministic risk enforcement, so its daemon class will be named by role (e.g. a `RiskAuditor`/`RiskTracker` category), not inherited from the product label
- **APR** — `docs/foundation/adaptive-parameter-registry.md`: Risk limits as parameters, governed by APR
- **Documentation System** — `docs/foundation/documentation-system.md`: Idea docs live in `ideas/`, not authoritative until verified
- **Bus Architecture** — `docs/data/`: Unified event stream, typed events, no direct service calls
- **DAG Execution** — `docs/concepts/dag-execution.md`: One-directional data flow, no cycles

---

## The independence principle — enforced in architecture

AegisAgent's independence is not just a design principle — it must be enforced architecturally:

1. **AegisAgent has no dependency on PrimeAgent being operational.** It subscribes to execution events directly. If PrimeAgent is down, AegisAgent still monitors and can still halt.
2. **AegisAgent cannot be paused by other products.** Only a human with explicit authority can disable an AegisAgent limit.
3. **Execution products cannot proceed without pre-trade check.** If AegisAgent is unavailable, the default behavior is to block new positions, not to allow them.
4. **Risk limits cannot be changed in real time through automated means.** Changing a risk limit requires a deliberate human action — it cannot be triggered by any automated signal or agent.

---

## Status and phasing

AegisAgent is a vision-stage product. It is not in the current build roadmap.

**Phase 1 (within execution products):** Basic risk checks (drawdown limit, max position size, margin alert) live inside TradeAgent and DerivAgent as internal guardrails. This is the minimum viable risk system.

**Phase 2 (as standalone service):** AegisAgent extracted as an independent service with the pre-trade check protocol, VaR, and halt capability. Required before any autonomous execution product goes to production with real capital.

**Phase 3 (full capability):** Stress testing, correlation analysis, multi-account risk aggregation, institutional audit trail.

> **AegisAgent is a prerequisite for production deployment of TradeAgent or DerivAgent at any meaningful scale. The moment real capital is at risk in an automated system, an independent risk layer is not optional.**
