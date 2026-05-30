# Jim Simons / Renaissance Principles (Research)

**Version:** 1.2.0
**Status:** draft
**Priority:** high
**Milestone:** future
**Last Updated:** 2026-02-27
**Tags:** renaissance, jim-simons, principles, medallion, data-first, edge, philosophy

**Sources:**
- [QuantVPS – Jim Simons Trading Strategy Explained](https://www.quantvps.com/blog/jim-simons-trading-strategy)
- [Hedge Fund Alpha – Jim Simons’ Portfolio: A Blueprint For Wealth Accumulation](https://hedgefundalpha.com/strategies/jim-simons-portfolio/)

---

## Overview

Renaissance Technologies runs multiple strategies. The **Medallion Fund** (closed to external investors since 1993; employees/families only) is the flagship: ~66% gross (39% net) annual returns (1988–2018), **50.75% win rate**, **0.01–0.05% edge per trade**, 150k–300k trades/day. Medallion is quantitative, high-frequency, and market-neutral. Renaissance also manages **public equity portfolios** (e.g. ~$66.5B AUM, sector-diversified, top holdings in tech and pharma); that arm is distinct from Medallion’s stat-arb engine. These principles are distilled for relevance to a systematic, data-driven platform like IndicAgent — not a copy of their strategy.

---

## 1. Data First, Not Models

> "We don't start with models. We start with data. We don't have any preconceived notions. We look for things that can be replicated thousands of times." — Jim Simons

- **Idea:** Let the data lead. Find patterns that repeat; avoid fitting a story first.
- **Relevance:** Our pipeline is data-first: ticks → bars → indicators → structure/context/patterns → signals. New ideas should be tested as repeatable patterns in our data (e.g. signal_ledger, intelligence_features) before hardening into "models."

---

## 2. Small Edge, High Volume, No Override

- **Edge:** 50.75% win rate; 0.01–0.05% profit per trade; leverage amplifies.
- **Volume:** 150k–300k trades/day so small edges compound.
- **Discipline:** "Never override the computer." Automation removes emotional bias; consistency over discretion.

**Relevance:** We run automated signal generation and lifecycle; position sizing and risk rules should be systematic. Track win rate and edge per setup (e.g. by plugin) in signal_ledger; avoid ad-hoc overrides.

---

## 3. Statistical Arbitrage and Mean Reversion

- **Concept:** Temporary misalignments between related securities (or price vs. "fair value"); long the cheap, short the rich; hold seconds to days until reversion.
- **Evolution:** From pairs to large, diversified portfolios; sector/region matching to reduce systemic risk.

**Relevance:** Our mean-reversion and deviation setups (e.g. VWAP deviation, Kalman fair value) are in the same spirit: trade temporary deviation from a statistical anchor, not directional story. Cross-asset or cross-timeframe "pairs" could be a future research direction.

---

## 4. Market Neutral / Risk Control

- **Concept:** Balanced long/short so performance is not tied to market direction (Medallion beta ~ -1.0 vs broad index).
- **Crisis behavior:** In 2007 "quant quake" they lost ~20% in three days but did not override; finished the year up 85.9%. In 2008 (S&P -38%) Medallion was +74.6% net.

**Relevance:** We are single-asset futures (directional). The transferable idea is **risk discipline**: defined stops, position sizing (e.g. Kelly-inspired sizer), and trusting the system in drawdowns rather than turning off or overriding.

---

## 5. Signal Validation Before Scale

- **Concept:** Most signals they find are **discarded** unless they are statistically valid and scalable in backtesting.
- **Implication:** Not every pattern is tradeable; quality over quantity.

**Relevance:** We have many I7 setups and an aggregator. A formal "promotion" rule could mirror this: only allow a setup into the live aggregator (or give it weight) after it meets a statistical bar in historical or live signal_ledger (e.g. win rate, Sharpe, or pnl_r distribution). ML scoring (future) could implement this.

---

## 6. Unified Model Across Contexts

- **Concept:** One unified model; improvements in one asset class or area improve others (e.g. currencies helping equities).
- **Benefit:** Compounding of research; no siloed edges.

**Relevance:** We have one pipeline and one plugin set across symbols and timeframes. Improvements to I1/I3/I4/I5/I6 benefit all instruments. Keep shared features and a single DAG rather than per-symbol or per-TF models unless there is a clear reason to split.

---

## 7. Position Sizing and Kelly

- **Concept:** Renaissance uses the **Kelly Criterion** (and balanced portfolios) to size positions from their estimated edge.
- **Effect:** Controls risk while maximizing growth when edge is present.

**Relevance:** We have a position sizer (risk-based). Aligning it with a Kelly-style formulation (or fractional Kelly) for our signal win rate and payoff could be a research task. See `src/intelligence/trading/position_sizer.py`.

---

## 8. State-Based and Non-Linear Structure

- **Concept:** They use stochastic processes, Hidden Markov Models (from speech recognition), and **kernel methods** (mapping data to higher dimensions) to capture market "states" and non-linear relationships.
- **ML techniques (from Hedge Fund Alpha):** Unsupervised learning for hidden patterns and groupings; regression for relationships between variables; time series analysis for predicting future trends. Models "quickly recognize new patterns and make trading decisions based on short-term signals."
- **Quote:** "I don't know why planets orbit the sun. That doesn't mean I can't predict them." — Simons

**Relevance:** We already have regime/state ideas: HMM regime (smc_HMMRegime), trend regime, volatility regime. Research ideas: kernel or other non-linear methods for regime or for feature expansion before ML; more explicit "state" features in intelligence_features; unsupervised grouping of regimes or setups.

---

## 9. Alternative and Unconventional Data

- **Concept:** Beyond price/volume: historical data back centuries, weather, shipping, lunar cycles, etc., with strict validation.
- **Idea:** Broader data can reveal structure that price alone does not.

**Relevance:** We are price/volume/derived-feature based. Future ideas: optional exogenous inputs (e.g. VIX term structure, basis, sentiment or news) as I4/I5 inputs or as regime/confidence modifiers. Validate rigorously before wiring in.

---

## 10. Infrastructure and Execution

- **Concept:** Low latency, co-location, atomic-clock sync; order slicing and masking to reduce impact; internal matching where possible. "Your mathematical edge is only as strong as the infrastructure supporting it."
- **Scale:** ~50k cores, 40 TB/day, petabyte-scale history.

**Relevance:** We are not HFT, but the principles apply: reliable execution (TWS/Redis/services), no unnecessary latency in the hot path, and robust deployment (e.g. systemd, health checks) so the system runs consistently and does not "override" itself with downtime.

---

## 11. Pattern Recognition and Adaptive Models

- **Background:** Simons worked as a codebreaker (pattern recognition) before academia and finance. That skill translated directly to finding recurring patterns in market data.
- **Data depth:** With James Ax, Renaissance used World Bank and Federal Reserve data **dating back to the 1700s** to identify cyclical trading patterns. Vast history supports pattern validation.
- **Dynamic models:** Parameters are **time-varying and adjustable**; the model adapts rather than staying static. "The model is dynamic and adjustable. Parameters change with time."
- **Crisis and redesign:** After Medallion lost ~30% by April 1989, Simons insisted on reevaluation; Ax left. With Berlekamp and Laufer, the system was **redesigned in six months**; 1990 delivered 55.9%. From 1993 to April 2005 the fund had only 17 negative months and three losing quarters.

**Relevance:** We iterate on plugins and pipeline (I1–I8); new patterns should be validated on history and then allowed to adapt (e.g. regime-dependent parameters). Long history in our DB (market_data_ohlcv, intelligence_features) supports cycle and pattern research. Willingness to redesign after drawdowns, not just tweak, is a cultural takeaway.

---

## 12. Liquidity and Diversification

- **Liquidity:** Renaissance focuses on **highly liquid assets**; illiquid assets do not fit HFT and fast execution. "Jim Simons does not frequently resort to investing in illiquid assets."
- **Diversification:** Thousands of small holdings; no single large bet. Diversified by **asset class** (equities, currencies, commodities, and recently crypto and futures), **geography**, and **industry** (e.g. tech 21.3%, healthcare 17.1%, consumer discretionary 20.6%). Top 20 positions ≈ 83% of one portfolio; even then no name is oversized.
- **Position sizing:** Actively limits capital per investment so that one rough holding does not damage the whole portfolio.

**Relevance:** We trade liquid futures; symbol set is already liquid. For future expansion (e.g. more instruments or strategies), prefer liquid names and many small edges rather than concentration. Our position sizer and risk rules enforce per-trade limits; keep that discipline.

---

## 13. Stress Testing and Continuous Monitoring

- **Stress testing:** Before committing larger capital, Renaissance **stress-tests** targets under different market conditions. Only after passing do they consider the investment.
- **Monitoring:** "Both managers and algorithms are monitoring the current condition of all holdings, making necessary adjustments accordingly." Continuous feedback, not set-and-forget.

**Relevance:** Before promoting a new setup or increasing allocation, we could run it through historical stress periods (e.g. high vol, trend vs range) and check pnl_r and drawdown. Once live, monitor signal_ledger and plugin performance (win rate, Sharpe by setup) and adjust weights or disable setups that degrade.

---

## 14. Lessons and Quotes (Zuckerman and Simons)

From *The Man Who Solved the Market* (Gregory Zuckerman) and Simons’ own statements:

- **Mean reversion is the lowest-hanging fruit.** — Directly supports our VWAP deviation, Kalman mean-reversion, and similar setups.
- **Most quant traders fail.** — Edge is hard; discipline and infrastructure matter as much as the idea.
- **Leverage bites.** — Size with care; our position sizer should cap exposure.
- **The logical strategies are arbored away.** — Obvious edges get crowded; we need many small, less obvious signals.
- **Many data points are required** for a meaningful strategy. — Aligns with "data first" and our reliance on bars, indicators, and signal history.
- **Diversify across markets and time frames; trade different markets for uncorrelated returns.** — We already multi-timeframe and multi-symbol; could extend to more asset classes later.
- **Trade frequently.** — Let the edge compound; our pipeline is built for continuous signals.
- **Aim for market-neutral.** — We are directional; the takeaway is to control beta and risk, not necessarily go short.

Simons’ life principles (paraphrased): luck can’t be avoided; persistence pays; let beauty guide you (e.g. in math); partner with good people; don’t follow the crowd.

**Relevance:** Double down on mean-reversion and deviation ideas; keep position sizing and leverage in check; value data depth and diversification; automate and trade frequently within risk limits.

---

## Summary Table

| Principle              | Renaissance practice              | IndicAgent relevance                              |
|------------------------|-----------------------------------|---------------------------------------------------|
| Data first             | Start with data, not models       | Pipeline is data-driven; keep it that way         |
| Small edge, volume     | 50.75% win, 0.01–0.05%/trade      | Track edge per setup; automate, don’t override    |
| Stat arb / reversion   | Temporary mispricings             | VWAP/Kalman deviation, mean-reversion setups      |
| Market neutral         | Long/short balance                | We’re directional; take risk discipline           |
| Signal validation      | Discard unless proven             | Gate setups by stats before full weight           |
| Unified model          | One model, all assets             | One pipeline, all symbols/TFs                    |
| Kelly sizing           | Optimal position size             | Align sizer with edge (e.g. Kelly)               |
| State / non-linear     | HMM, kernel methods               | Regime plugins; explore kernel/ML                |
| Alternative data       | Weather, shipping, etc.           | Optional exogenous inputs later                   |
| Infrastructure         | Low latency, reliability          | Reliable services and execution path              |
| Adaptive models        | Dynamic parameters; redesign after crisis | Validate patterns on history; iterate plugins   |
| Liquidity & diversification | Liquid assets; thousands of small positions | Trade liquid futures; many small edges       |
| Stress testing & monitoring | Test before capital; monitor continuously | Stress-test setups; monitor signal_ledger   |
| Lessons (Zuckerman)    | Mean reversion, many data points, trade frequently | Prioritise mean-reversion; use full data; automate |

---

## Implementable Ideas (Derived From These Principles)

Concrete strategies, features, and agents we could add to the intelligence platform, inspired directly by the principles above.

### Indicators and Intelligence

| Idea | Principle | What to build |
|------|-----------|----------------|
| **Regime-adaptive parameters** | Adaptive models (11); state-based (8) | Let I1/I4 plugin parameters (e.g. ATR period, Kalman R) depend on `hmm_regime` or `garch_vol_regime`. One pipeline, but coefficients that adapt by state. |
| **Momentum acceleration (second derivative)** | Pattern recognition (11); many data points (14) | I1 plugin: `rsi_accel`, `macd_accel`, `roc_accel`, `inflection_flag`. Early exhaustion signal before price/RSI cross. See `docs/ideas/momentum-acceleration-second-derivative.md`. |
| **Explicit “state” features for ML** | State-based (8); data first (1) | Publish a small set of canonical state features (e.g. `regime_id`, `vol_regime`, `trend_regime`, `inflection_flag`) in `intelligence_features` so any future ML layer can use them without parsing the full payload. |
| **Cross-symbol / cross-TF “pairs” style signals** | Stat arb (3); diversify (12) | I7 or I6 plugin: relative strength or mean reversion between e.g. ES vs NQ, or 5m vs 15m for same symbol. “Cheap vs rich” in a Renaissance sense, adapted to our universe. |

### Signals and Setups

| Idea | Principle | What to build |
|------|-----------|----------------|
| **More mean-reversion setups** | Mean reversion is lowest-hanging fruit (14) | Double down: additional I7 setups that trade deviation from VWAP, Kalman fair value, or session range midpoint, with strict entry/exit rules. |
| **Signal promotion gate** | Signal validation (5) | Before a setup is allowed full weight in the aggregator, require it to meet a statistical bar in backtest or live (e.g. min sample size, win rate, or pnl_r distribution). “Discard unless proven.” |
| **Setup weights from recent performance** | Continuous monitoring (13); small edge (2) | Periodically (e.g. weekly) compute win rate and avg pnl_r per setup from `signal_ledger`; feed weights into the aggregator so better-performing setups get higher rank. |
| **Stress-test new setups before go-live** | Stress testing (13) | Run new I7 setups through historical high-vol and trend/range regimes; only enable in production if pnl_r and drawdown pass a threshold. |

### Position Sizing and Risk

| Idea | Principle | What to build |
|------|-----------|----------------|
| **Kelly (or fractional Kelly) in position sizer** | Kelly sizing (7); leverage bites (14) | In `position_sizer.py`, add an option to size using estimated win rate and payoff from `signal_ledger` (or from setup-specific stats), with a cap (e.g. half-Kelly). |
| **Per-setup exposure caps** | Liquidity & diversification (12) | Limit not only total risk per trade but max allocation to a single setup (e.g. “mean reversion can’t be more than 40% of today’s risk budget”). |

### Data and Validation

| Idea | Principle | What to build |
|------|-----------|----------------|
| **Pattern mining on signal_ledger** | Data first (1); many data points (14) | Offline job or notebook: find repeatable patterns (e.g. “after 3 consecutive VWAP-deviation wins, next signal of type X has higher win rate”). No preconceived model; let the data suggest the next setup or filter. |
| **Cycle detection on long history** | Pattern recognition (11); data depth | Use long `market_data_ohlcv` / `intelligence_features` history to detect cyclical behavior (e.g. time-of-day, day-of-week, or regime recurrence) and feed cycle phase into I4 or I7 as an optional feature. |
| **Optional exogenous inputs** | Alternative data (9) | Add optional fields (e.g. VIX level, basis, or roll premium) to intelligence payload; I4 or I7 plugins can use them as regime/confidence modifiers. Validate impact before making them mandatory. |

### Agents and Automation

| Idea | Principle | What to build |
|------|-----------|----------------|
| **“Never override” dashboard** | No override (2); continuous monitoring (13) | Dashboard view: current live signals and open positions with a clear “system decision” and no manual override button for production. Alerts only; human can pause the system but not flip individual trades. |
| **Automated setup health report** | Continuous monitoring (13); signal validation (5) | Scheduled report (e.g. daily): win rate, avg pnl_r, and drawdown by setup from `signal_ledger`; flag setups that fall below a threshold for review or auto-disable. |
| **Backtest-on-demand for new setups** | Stress testing (13); discard unless proven (5) | When adding a new I7 plugin, run it on N days of stored bars/features and produce a small report (hit rate, pnl_r, max drawdown). Gate promotion to live on that report. |

---

This document is a reference for research and product thinking. It does not constitute investment or trading advice.
