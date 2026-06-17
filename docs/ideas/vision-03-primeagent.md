# PrimeAgent — Unified Portfolio Management Platform (Vision)

**Status:** draft
**Version:** 1.0
**Created:** 2026-03-04
**Last Updated:** 2026-06-17
**Context:** Unified cross-product portfolio management, capital allocation, and performance attribution
**Priority:** low
**Milestone:** future (post-v2.8)
**Tags:** primeagent, portfolio, capital-management, prime-brokerage, platform, vision, performance

---

## The name

**Prime** from prime brokerage — the institutional service that provides unified portfolio oversight, capital management, margin, risk services, and performance reporting to hedge funds and multi-strategy managers. That is exactly what this product does: it is the prime-brokerage-equivalent layer of our platform, sitting above all execution products.

---

## Purpose

PrimeAgent solves the cross-product portfolio problem. When a user runs **both** TradeAgent (futures) and DerivAgent (options) simultaneously, neither product has a unified view of the combined portfolio. PrimeAgent owns that view.

It is not an execution product. It does not place trades. It is the **capital management and performance layer** — the CFO and portfolio manager function of the platform.

### Renaissance Frame

PrimeAgent embodies Renaissance principles:

- **The unified model beats siloed strategies:** Renaissance ran one combined book, not separate PM silos with independent P&L and risk limits. PrimeAgent is the unified-book view — every position, every Greek, every dollar of capital across all execution products in one model, so cross-product exposure is always visible and never silently concentrated.
- **Diversification of edges, not just positions:** Allocating capital across uncorrelated edge types (VRP harvesting, directional momentum, mean reversion) is portfolio construction at the edge level, the platform analogue of Simons holding thousands of small, diversified positions.
- **Position sizing is the mathematics of edge (Kelly):** Deployment sized from per-strategy win rate and payoff — fed from the Signal Ledger Architecture outcomes — is Kelly discipline applied to capital, not discretionary bet sizing.
- **The learning machine:** Performance attribution by regime, strategy, and source is the feedback signal. Strategies that degrade in a regime lose allocation weight automatically; the system improves the longer it runs.
- **Separation of concerns is non-negotiable:** PrimeAgent optimizes and reports. It does not execute (TradeAgent/DerivAgent) and does not enforce hard risk limits (AegisAgent). One job per component; PrimeAgent is advisory, AegisAgent is binding.

---

## The problem it solves

Without PrimeAgent:

- A user running TradeAgent futures AND DerivAgent options has two separate P&L views, two separate position lists, two separate capital pools
- Portfolio-level Greek exposure (the combined delta/gamma/theta/vega of futures + options simultaneously) is invisible
- Capital allocation across strategies is manual
- Performance attribution — "did the edge come from technical signals, vol premium, or macro regime?" — is impossible
- Multi-account, fund management, and SMA structures have no infrastructure

With PrimeAgent:

- One unified portfolio view across all products and all strategies
- Combined Greek exposure in real time
- Systematic capital allocation with Kelly-adjusted strategy budgets
- Full performance attribution by source, strategy, product, and regime
- Institutional-grade fund and SMA management

---

## Where PrimeAgent sits in the platform

```
                    INTELLIGENCE LAYER
         IndicAgent    QualAgent    DerivAgent
              │              │             │
              └──────────────┴─────────────┘
                             │
                    WARM BUS (streams)
                             │
              ┌──────────────┴──────────────┐
              │                             │
         TRADEAGENT                  DERIVAGENT EXECUTION
         (futures/equity)            (options)
              │                             │
              └──────────────┬──────────────┘
                             │
                      PRIMEAGENT
                  (unified portfolio view)
                             │
                       AEGISAGENT
                   (independent risk layer)
```

PrimeAgent subscribes to:
- All warm-tier intelligence streams — to understand the regime context of every position
- Execution event streams from TradeAgent and DerivAgent — fills, opens, closes, adjustments
- Cold tier — for historical P&L, attribution, backtesting strategy allocation

PrimeAgent publishes to:
- `portfolio:state:ACCOUNT` — current position snapshot, Greek aggregates, capital allocation
- `portfolio:performance:ACCOUNT` — daily/weekly P&L by strategy and source
- `portfolio:allocation:ACCOUNT` — current capital budget per strategy and per product

AegisAgent subscribes to PrimeAgent's `portfolio:state:*` streams as one of its primary risk inputs.

---

## Core capabilities

### 1. Unified position and P&L view

Aggregate all open positions across TradeAgent (futures) and DerivAgent (options) into a single real-time portfolio view.

- Live unrealized P&L per position, per strategy, per product
- Realized P&L by session, by day, by strategy cycle
- Combined cost basis and notional exposure
- Multi-account and multi-broker aggregation (same tenant, multiple broker connections)

### 2. Portfolio Greeks aggregation

When a user holds futures positions (directional delta) alongside options positions (complex Greeks), the net portfolio Greek exposure is the sum of all — and it is not visible anywhere unless explicitly computed.

PrimeAgent computes and maintains in real time:

| Greek | What it measures | Why it matters |
|-------|-----------------|----------------|
| **Net delta** | Directional exposure in dollar terms | Am I net long or short? By how much? |
| **Net gamma** | Rate of delta change | How fast does my risk change as price moves? |
| **Net theta** | Daily P&L from time decay | Am I earning or paying theta across all positions? |
| **Net vega** | Exposure to volatility changes | Am I net long or short vol? |
| **Net charm** | How delta changes as time passes | Expiry-day delta drift risk |

Target ranges are set per account. PrimeAgent monitors breaches and alerts (or auto-hedges if configured).

**Delta neutralization:** When portfolio net delta drifts outside the target range (from options accumulating delta as price moves), PrimeAgent can flag for manual hedge or instruct TradeAgent to submit a delta-hedge order automatically.

### 3. Capital allocation and strategy budgets

Capital is a finite resource. PrimeAgent enforces how it is deployed across competing strategies.

- **Total deployment %:** How much of account capital is currently at risk (combined across TradeAgent and DerivAgent)
- **Per-strategy budgets:** Maximum capital allocated to 0DTE, weekly premium, directional futures, etc.
- **Per-product budgets:** Maximum % deployed in options vs futures
- **Kelly-adjusted sizing inputs:** PrimeAgent maintains signal performance statistics from the cold tier (win rate, avg payoff per strategy) and feeds them to TradeAgent and DerivAgent's position sizers as Kelly inputs

When a strategy bot or execution agent requests capital, PrimeAgent checks:
1. Is total deployment below the cap?
2. Is the relevant strategy budget available?
3. Does the new position stay within Greek limits?
4. Is the position correlated with existing holdings beyond the correlation limit?

If any check fails, the allocation is rejected or reduced.

### 4. Performance attribution

Knowing P&L is not enough. Knowing *where* P&L came from is how the system improves.

PrimeAgent attributes P&L across multiple dimensions:

| Dimension | What it answers |
|-----------|----------------|
| By strategy type | Was profit from VRP harvesting, directional momentum, or mean reversion? |
| By intelligence source | Did IndicAgent alignment, QualAgent regime, or DerivAgent vol regime predict the winners? |
| By market regime | Which strategies perform best in trending vs range-bound vs vol-expansion regimes? |
| By product | Futures P&L vs options theta P&L vs options delta P&L |
| By time | Time-of-day, day-of-week, session effects |
| By setup quality | High-conviction (3-domain aligned) vs single-domain signal outcomes |

Attribution data feeds the learning loop: strategies that perform better in specific regimes get higher allocation weight during those regimes. Strategies that degrade get reduced allocation automatically.

### 5. Multi-account and fund management

For institutional users, family offices, and fund managers running multiple accounts or SMAs:

- **Multi-account view:** Aggregate P&L, positions, and Greeks across all accounts, or drill down to any single account
- **SMA (Separately Managed Account) management:** Replicate strategy execution across multiple accounts simultaneously, each with their own capital allocation, risk limits, and Greek targets
- **Fund-level reporting:** Consolidated performance, drawdown, attribution, and risk metrics at the fund level — across all underlying accounts
- **Investor reporting:** Exportable performance reports for fund investors (NAV, drawdown, Sharpe, attribution summary)
- **Fee calculation:** Management fee and performance fee tracking per investor account

### 6. Strategy allocation optimization

Over time, PrimeAgent can recommend (or automatically implement) shifts in strategy allocation based on regime and historical performance data.

- **Regime-adaptive allocation:** In a vol-expansion regime, reduce premium collection budget and increase defensive/hedged budget
- **Performance-adaptive allocation:** Strategies with degrading win rates get reduced allocation; improving strategies get increased allocation
- **Correlation-aware diversification:** Prevent over-allocation to strategies that are correlated (both long vol, or both short delta) even if they appear to be different strategy types

This is the portfolio equivalent of IndicAgent's I7 signal aggregator: not "which signal fired" but "given what we know, how should capital be distributed?"

---

## What PrimeAgent does NOT do

- **Does not place trades.** It allocates capital and manages the portfolio view; TradeAgent and DerivAgent execute.
- **Does not manage individual trade lifecycle.** That stays in the execution products.
- **Does not enforce risk limits.** That is AegisAgent's domain. PrimeAgent tracks and optimizes; AegisAgent enforces and halts.
- **Does not perform market analysis.** It consumes intelligence from IndicAgent, QualAgent, and DerivAgent. It does not generate it.

---

## PrimeAgent vs AegisAgent — the boundary

| Concern | PrimeAgent | AegisAgent |
|---------|-----------|-----------|
| Unified P&L view | ✓ | — |
| Capital allocation | ✓ | — |
| Kelly sizing inputs | ✓ | — |
| Strategy budgets | ✓ | — |
| Performance attribution | ✓ | — |
| Greek aggregation | ✓ monitors | ✓ enforces limits |
| Drawdown monitoring | — | ✓ enforces halts |
| VaR calculation | — | ✓ |
| Margin monitoring | — | ✓ |
| Stress testing | — | ✓ |
| Emergency trading halt | — | ✓ |
| Override authority over execution | — | ✓ |

PrimeAgent optimizes. AegisAgent protects. Both are necessary. Neither can substitute for the other.

---

## Stream interface

### Subscribes to

| Stream | From | Purpose |
|--------|------|---------|
| `intelligence:SYMBOL:TF` | IndicAgent | Regime context for attribution |
| `qual:regime:SYMBOL` | QualAgent | Macro regime for attribution |
| `deriv:vol_regime:SYMBOL` | DerivAgent | Vol regime for allocation adjustment |
| `execution:fill:ACCOUNT` | TradeAgent / DerivAgent | Position updates |
| `execution:open:ACCOUNT` | TradeAgent / DerivAgent | New positions |
| `execution:close:ACCOUNT` | TradeAgent / DerivAgent | Closed positions + outcome |

### Publishes

| Stream | Consumers | Content |
|--------|-----------|---------|
| `portfolio:state:ACCOUNT` | AegisAgent, Dashboard | Live positions, Greek aggregates, deployment % |
| `portfolio:performance:ACCOUNT` | Dashboard, Learning loop | P&L by strategy, attribution |
| `portfolio:allocation:ACCOUNT` | TradeAgent, DerivAgent | Current capital budget per strategy |
| `portfolio:signal:ACCOUNT` | TradeAgent, DerivAgent | Allocation recommendations (regime-adaptive) |

---

## Cold tier tables

| Table | Content |
|-------|---------|
| `portfolio_snapshots` | Point-in-time portfolio state (Greeks, P&L, allocation) |
| `performance_attribution` | P&L attributed by strategy, regime, source |
| `strategy_allocation_history` | Historical allocation weights and changes |
| `account_nav` | Daily NAV per account for fund management |
| `investor_records` | SMA/fund investor records for institutional tier |

---

## User tiers

| User type | PrimeAgent features |
|-----------|-------------------|
| **Individual trader** | Unified P&L, Greek aggregation, capital allocation, performance attribution |
| **Active multi-strategy** | All above + strategy budget optimization, regime-adaptive allocation |
| **Professional / fund** | All above + multi-account, SMA management, fund-level reporting, fee tracking |
| **Institutional** | All above + investor reporting, compliance exports, API access |

---

## Status and phasing

PrimeAgent is a vision-stage product. It is not in the current build roadmap.

**Prerequisite:** At least one execution product (TradeAgent or DerivAgent) must be live before PrimeAgent adds meaningful value. The cross-product portfolio problem only exists once two execution products are running simultaneously.

**Phase 1 (when first execution product ships):** Unified position view, basic P&L, capital deployment tracker. Lightweight — could be a service within TradeAgent or DerivAgent initially.

**Phase 2 (when both execution products are live):** Full PrimeAgent as a standalone product: Greek aggregation, strategy budgets, performance attribution.

**Phase 3 (institutional scale):** Multi-account, SMA, fund management, investor reporting.
