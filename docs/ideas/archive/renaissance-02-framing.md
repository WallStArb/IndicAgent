# The Renaissance Framing — How Simons Would Build This

**Version:** 1.0
**Status:** draft
**Priority:** high
**Milestone:** future
**Last Updated:** 2026-03-04
**Tags:** renaissance, jim-simons, philosophy, architecture, medallion, data-first, pattern-recognition

---

## The question

If Jim Simons and the Renaissance team sat down to build a market intelligence and autonomous trading platform for the modern trader — not a proprietary fund, but a platform that gives individual and institutional traders access to the same kind of infrastructure Medallion runs on — what would they build? How would they think about it?

This document answers that question and maps every major architectural decision to a Renaissance principle.

---

## The Simons method in one paragraph

Simons didn't have a thesis about markets. He had a method. Hire the best mathematicians and scientists. Collect every data set you can find. Let the data reveal structure that human intuition can't see. Validate every signal statistically — discard most of them. Combine the surviving signals into a unified model that knows what state the market is in before it does anything else. Size positions using the mathematics of edge (Kelly). Execute with precision. Let the machine learn continuously. Never override the model. Repeat 150,000 times a day.

The result: 66% gross annual returns over 30 years. 50.75% win rate. 0.01–0.05% edge per trade. The most profitable trading operation in history — built not on prediction, but on pattern recognition, discipline, and infrastructure.

---

## Principle 1: Data first. Always.

> "We don't start with models. We start with data. We don't have any preconceived notions. We look for things that can be replicated thousands of times." — Simons

Simons didn't start with a thesis about the economy. He didn't hire macro traders with strong views. He hired codebreakers, linguists, and mathematicians who knew how to find patterns in noise. The strategy emerged from the data, not the other way around.

**What this means for our platform:**

- IndicAgent's 88+ plugins don't start with an opinion. They measure: momentum, structure, deviation from statistical anchors, pattern completion, regime state. The signals emerge from the data.
- QualAgent doesn't say "rates rising means sell equities." It measures the economic surprise index, the prediction market probability, the COT positioning extreme, and asks: *what is the data actually saying right now?*
- DerivAgent doesn't predict market direction. It reads what the options market *already has priced in* — the vol surface, the GEX, the VRP — and harvests structural mispricings that show up repeatedly.
- Every new plugin, every new signal source, every new qualitative input enters through the same door: *can we measure it? Can we validate it? Does it repeat?* If not, it doesn't get wired in.

The data spine — the hot/warm/cold bus — is built for exactly this. Raw data flows in unfiltered. Intelligence emerges from it layer by layer.

---

## Principle 2: Small edge. High repetition. Never override.

Medallion's 50.75% win rate sounds unimpressive. It isn't. At 150,000 trades per day, a 0.75% edge advantage over coin-flip compounds to extraordinary returns. Simons never looked for the big win. He looked for the small, repeatable, diversifiable edge — and then executed it with machine precision, thousands of times, without emotion.

The corollary: **never override the model.** During the 2007 quant quake, Medallion lost 20% in three days. They didn't override. They didn't panic-close. They trusted the math. They finished the year up 85.9%.

**What this means for our platform:**

The four products each have a primary edge:

| Product | Primary edge | Expected individual win rate |
|---------|-------------|------------------------------|
| IndicAgent | Technical structure + pattern recognition | ~55–60% on validated setups |
| QualAgent | Macro regime alignment + qualitative positioning extreme | ~5–10% confidence modifier when aligned |
| DerivAgent | Volatility Risk Premium (VRP) harvesting | ~52–55% on premium collection across cycles |
| TradeAgent | Execution precision: routing, timing, Kelly sizing | Reduces slippage and oversizing drag |

None of these is a crystal ball. Together, when they align, the combined signal is multiplicative.

**The never-override rule translates directly:** Guardrails are enforced before execution. The lead agent's suggestion is bounded. Automation levels are explicit. Humans can pause the system but not flip individual trades. In drawdowns, the system runs. The math runs.

---

## Principle 3: Regime detection before everything else

Renaissance's greatest single innovation may have been recognizing early that markets are non-stationary. The same signal means completely different things in a trending market versus a range-bound market versus a volatility-expansion regime. They used Hidden Markov Models — originally developed for speech recognition — to detect which "state" the market was in before applying any trading logic.

Knowing the state is the alpha filter. The signal doesn't create the edge; *applying the right signal in the right regime* creates the edge.

**What this means for our platform:**

Regime detection is not one feature — it is the foundation that every other layer is built on.

```
Before any trade decision:

  IndicAgent I4       → Technical regime (trending / ranging / volatile / quiet)
  QualAgent           → Macro regime (bullish / bearish / neutral / risk-off / transitioning)
  DerivAgent          → Vol regime (elevated / compressed / expanding / term-structure shape)

  Combined regime state = the HMM equivalent for our platform
```

A momentum setup from IndicAgent means something different in a macro regime-off environment (QualAgent) than in a macro tailwind. A premium collection setup from DerivAgent is valid in compressed vol; it is not valid in an expanding vol regime regardless of how strong the technical setup looks.

The regime state gates every signal. The more regimes that align, the higher the conviction tier. This is the cross-domain alpha advantage — and it only exists because all three regime states are on the same bus.

**The three-domain regime stack:**

| Regime layer | Source | What it gates |
|---|---|---|
| Technical regime | IndicAgent I4 | Which setup types are active (momentum vs mean-reversion) |
| Macro regime | QualAgent | Directional bias adjustment, risk-off filter |
| Vol regime | DerivAgent | Premium collection on/off, hedging posture |

---

## Principle 4: The unified model beats the siloed strategies

Simons didn't run a momentum book, a mean-reversion book, and a macro book that each had their own P&L and their own risk limits. He ran one model. Every signal — whatever its origin — fed into one combined prediction engine. Improvements in one domain benefited all domains. Cross-domain correlations were discoverable because everything ran together.

Most multi-strategy funds run siloed books with separate PMs who don't talk to each other. This is exactly the structure Medallion's unified model outperformed for 30 years.

**What this means for our platform:**

The TradeAgent lead agent is the unified model interface. It doesn't run "the IndicAgent strategy" separately from "the QualAgent strategy." It subscribes to all warm-tier streams — `intelligence:SYMBOL:TF`, `qual:regime:SYMBOL`, `deriv:vol_regime:SYMBOL` — and reasons over the full combined picture before any position decision is made.

```
TradeAgent lead agent sees simultaneously:

  IndicAgent signal:   I6 confluence HIGH, I7 setup CONFIRMED, trend regime STRONG
  QualAgent signal:    Macro regime BULLISH, QualScore 74, no catalyst event within 48h
  DerivAgent signal:   Vol compressed, GEX positive (market-maker pinning), VRP elevated

  → Combined conviction: TIER 1 (all three domains aligned)
  → Kelly sizing: full allocation per risk rules
  → Execute
```

If instead:

```
  IndicAgent signal:   I7 setup CONFIRMED
  QualAgent signal:    Macro regime RISK-OFF (Fed meeting tomorrow, uncertainty elevated)
  DerivAgent signal:   Vol expanding

  → Combined conviction: REDUCED (two of three domains against the trade)
  → Kelly sizing: half allocation or skip
  → Log to signal_ledger for learning
```

The intelligence bus is what makes this possible. Without it, you have four separate products making four separate decisions. With it, you have a single unified decision engine with three independent intelligence streams feeding it.

---

## Principle 5: The Volatility Risk Premium is our Medallion-grade edge

Simons' deepest statistical discovery — the bedrock of Medallion — was mean reversion. Temporary mispricings that revert to statistical anchors. Thousands of times a day, at small scale, consistently. He called mean reversion "the lowest-hanging fruit."

For options markets, the equivalent lowest-hanging fruit is the **Volatility Risk Premium (VRP)**: the consistent, empirically documented tendency for implied volatility to exceed realized volatility over the same forward period.

This is not a prediction. It is a structural feature of options markets — the same reason insurance companies are consistently profitable. The market systematically overpays for protection. That overpayment is the premium that options sellers collect.

```
Implied vol  >  Realized vol   →   premium exists   →   harvest it systematically

Evidence:
  - VIX (30-day implied) has exceeded subsequent realized vol ~75% of months since 1990
  - The premium averages 3-5 vol points across normal market conditions
  - It persists across underlyings, timeframes, and geographies
  - It survives regime changes (though it compresses in vol spikes — hence regime filtering)
```

**Why this is Medallion-grade:**

- Statistically validated (30+ years of data, multiple researchers, multiple markets)
- Mean-reverting in nature (just like Simons' stat-arb: the mispricing resolves)
- Small but persistent edge: 52–55% win rate on premium collection cycles
- Diversifiable across underlyings, expiries, and strike structures
- Regime-dependent: pause when vol is expanding, harvest when vol is elevated or compressing
- Does not require directional prediction — the edge exists regardless of whether the market goes up or down

DerivAgent is built to harvest this premium systematically, with three protections that Simons would require:

1. **Regime filter** — only collect premium when the vol regime qualifies (compressed or elevated with downward trajectory)
2. **Greeks management** — portfolio delta, gamma, and vega kept within strict bounds at all times
3. **Learning loop** — every strategy outcome is tracked; strike selection, timing, and regime entry conditions are continuously improved

---

## Principle 6: Signal validation before production — the promotion gate

Simons' team discarded most signals they found. The bar to enter the model was high: statistical significance, out-of-sample validity, plausible causal mechanism, scalability. "Not every pattern is tradeable."

**What this means for our platform:**

Every signal source — every IndicAgent plugin, every QualAgent data feed, every DerivAgent vol metric — must pass through a validation gate before being wired into live decision-making.

```
Signal promotion criteria:

  Minimum sample size:        N >= 50 independent occurrences
  Statistical significance:   p < 0.05 on win rate vs. coin-flip
  Out-of-sample validation:   Edge holds in walk-forward test
  Regime behavior:            Does the edge change across regime states?
                              If so, is the regime-conditional version still valid?
  Causal mechanism:           Can we articulate why this signal should predict price?
                              (Not required, but a strong-plus — Simons ran without it,
                              but causal stories help identify when signals will break)
  Drawdown profile:           Max drawdown within acceptable bounds
```

No signal gets full weight in the aggregator without meeting this bar. New QualAgent inputs (a new prediction market feed, a new alt-data source) are monitored in shadow mode before being wired into regime state calculations. New DerivAgent vol metrics are tracked against outcomes before affecting strategy selection.

This is the discipline that keeps the system honest. Simons' team was brilliant at finding patterns and equally disciplined about rejecting the ones that didn't survive scrutiny.

---

## Principle 7: Infrastructure is the edge

> "Your mathematical edge is only as strong as the infrastructure supporting it." — Renaissance Technologies

Simons invested massively in infrastructure: co-location, atomic-clock synchronization, 50,000 cores, 40TB/day data processing, petabyte-scale history. Not because they were in the HFT game (they were, but infrastructure mattered at every speed tier). Because **a 50.75% win rate disappears if your execution is unreliable, your data is stale, or your risk systems are slow**.

**What this means for our platform:**

The hot/warm/cold tier architecture is not an engineering aesthetic. It is a competitive advantage.

```
Hot tier  (sub-millisecond):
  Raw market events never touch a database. They flow straight through DragonflyDB
  streams to the analytics layer. Zero latency from market event to signal computation.
  
  Competitive edge: by the time a retail trader opens their charting app, our system
  has already computed 88 indicators, classified the regime, evaluated 40+ pattern
  detectors, and published a signal.

Warm tier  (processed intelligence):
  All intelligence outputs — IndicAgent, QualAgent, DerivAgent — live on the same
  in-memory bus. TradeAgent's lead agent can reason over the full combined picture
  in a single pass. No inter-service HTTP calls in the critical path.
  
  Competitive edge: the combined regime state is computed and available before
  any execution decision is made.

Cold tier  (TimescaleDB — institutional memory):
  Every signal, every trade, every outcome is stored. The system can compute
  "what was the regime state 6 months ago when this signal appeared, and what
  happened?" Backtesting, learning, and research all draw from the same source.
  
  Competitive edge: the longer the system runs, the more data it has, the more
  it learns, the better it performs. A new user who connects today benefits from
  all historical signal/outcome correlation data.
```

The canonical stream namespace — every product publishing to pre-agreed keys — is the infrastructure contract that makes this work. When QualAgent and DerivAgent are built, they plug into the same bus. TradeAgent subscribes without any integration work.

---

## Principle 8: The learning machine — the system never stops improving

Medallion's model parameters were time-varying. The system was continuously updated as new data came in. It was never "done." After the 1989 drawdown, Simons didn't tweak the model — he rebuilt it from scratch with Berlekamp. The willingness to redesign, not just adjust, is part of the culture.

At a platform level: every trade outcome is data. Every signal that fired and was not taken is data. Every regime state at every entry is data. The system that doesn't use this data is leaving its own institutional memory on the floor.

**What this means for our platform:**

```
Cold tier → Learning loop → System improvement

  signal_ledger outcomes    →  Setup win rate by regime state
                               → TradeAgent adjusts conviction weights

  strategy_performance      →  Strategy P&L by vol regime at entry
                               → DerivAgent adjusts strategy selection

  strike_selection_quality  →  Fill vs theoretical value
                               → DerivAgent tightens strike/expiry logic

  qual_outcomes             →  QualScore accuracy vs subsequent price action
                               → QualAgent refines signal weights

  execution_quality         →  Slippage by broker/session
                               → Routing rules optimized

  portfolio_snapshots       →  Greek drift patterns
                               → Greek management thresholds tuned
```

Nothing is retuned manually. Data flows in. Correlations are computed. Weights are updated. The system gets better the longer it runs. This is what Simons built. This is what we are building.

---

## Principle 9: Diversification of edges, not just positions

Simons held thousands of small positions across equities, futures, currencies, commodities, bonds. No single position was oversized. The Sharpe came from diversification — many small uncorrelated edges, not a few large bets.

**The platform version of this principle:**

We don't diversify only within positions. We diversify across *edge types*:

| Edge type | Source | Correlation to other edges |
|-----------|--------|---------------------------|
| Technical pattern recognition | IndicAgent | Low correlation to macro or vol |
| Macro regime alignment | QualAgent | Low correlation to technical patterns |
| Volatility Risk Premium | DerivAgent | Near-zero correlation to directional edges |
| Execution quality | TradeAgent routing | Orthogonal to signal quality |

Four independent domains, each with its own validated edge, each near-orthogonal to the others. When they align, the combined conviction is high and the probability of being wrong on all four dimensions simultaneously is very low. When they diverge, the system reduces size or skips — it doesn't bet against the signals.

This is portfolio construction at the edge level, not just the position level. It is the platform version of Simons' diversification mandate.

---

## Principle 10: The human stays in control — but doesn't override the model

Simons was famous for "never override the computer." But Medallion still had humans — reviewing the model, redesigning it when needed, setting the risk parameters. The humans operated at the *system* level, not the *trade* level.

**The distinction for our platform:**

```
Humans operate at the system level:
  ✓ Set risk limits (max drawdown, max position size, allowed strategy types)
  ✓ Set automation level (Notify → Propose → Semi-auto → Full-auto)
  ✓ Review learning loop outputs and approve major model changes
  ✓ Pause the system during extraordinary events
  ✓ Configure broker routing rules and capital allocation budgets
  ✓ Approve new signals for promotion to production weight

Humans do not operate at the trade level:
  ✗ Override an individual signal because it "feels wrong"
  ✗ Skip a risk management rule "just this once"
  ✗ Hold a losing position past the defined stop because "it will come back"
  ✗ Override the bot's strike selection because of a personal preference
  ✗ Disable a guardrail to "take a bigger shot"
```

The HITL (Human-in-the-Loop) framework in TradeAgent and DerivAgent enforces this distinction. The human approves at the *strategy and system* level. The machine executes at the *trade and lifecycle* level. This is how Medallion operated. This is how we build.

---

## How the four products map to the Medallion architecture

```
MEDALLION ARCHITECTURE          →    OUR PLATFORM

Data collection (all sources)   →    Hot tier: IBKR TWS daemon
                                      + QualAgent ingestion (COT, Kalshi, news)
                                      + DerivAgent ingestion (options chains)

Signal generation (hundreds     →    IndicAgent: 88+ plugins (I1–I7)
of signals across domains)            QualAgent: 15+ qualitative signals
                                      DerivAgent: 8 vol/GEX/VRP metrics

Regime detection (HMM states)   →    IndicAgent I4 (technical regime)
                                      QualAgent (macro regime)
                                      DerivAgent (vol regime)
                                      Combined regime state on warm bus

Unified model (all signals →    →    TradeAgent lead agent
one prediction engine)                (reasons over ALL warm streams)

Position sizing (Kelly)         →    Kelly-adjusted sizer
                                      (win rate × edge from signal_ledger)
                                      Fractional Kelly cap

Execution (precision)           →    Canonical order model
                                      Smart routing
                                      Fill quality monitoring

Risk management                 →    Portfolio Greeks (options)
                                      VaR, drawdown limits
                                      Margin monitoring
                                      Cross-product exposure view

Learning loop (continuous       →    signal_ledger outcomes →
model update)                         weight updates → all products improve

Signal validation (discard      →    Promotion gate: statistical bar
unless proven)                        before production weight
```

---

## The compounding insight

Simons understood compound growth mathematically. A 50.75% win rate at 150,000 trades per day is world-beating not because the edge is large, but because it compounds.

Our platform version of compounding works at three levels:

**1. Trade-level compounding:** Small consistent edge (VRP harvesting, technical confluence) at high repetition (0DTE bots, weekly cycles) = geometric growth.

**2. System-level compounding:** Every outcome improves the model. Month 12 of operation is more accurate than Month 1. The longer the system runs, the better it gets. Early adopters benefit most.

**3. Cross-domain compounding:** Adding QualAgent doesn't just add QualAgent's individual edge. It adds the *intersection signal* — the moments when three independent domains align simultaneously. The combined signal is non-linear. 1 + 1 + 1 doesn't equal 3 in edge terms; it equals substantially more because simultaneous multi-domain alignment is a much stronger filter than any individual signal.

---

## The founding principle

Everything else follows from this:

> **Markets are information-processing machines with predictable inefficiencies in the short run, at scale, across domains. The edge is not in prediction. The edge is in measurement, validation, pattern recognition, regime awareness, execution discipline, and continuous learning. Infrastructure is not a support function — it is the competitive moat.**

Simons proved this with 30 years of data. We are building the platform that operationalizes these principles for the modern trader.

---

## Summary: The Renaissance checklist for every decision

Before adding a new plugin, a new signal source, a new strategy type, a new feature — ask these questions:

| Question | Renaissance principle |
|----------|----------------------|
| Can we measure it precisely? | Data first |
| Does it repeat statistically? | Signal validation |
| What regime is it valid in? | State-based / HMM |
| Does it add to the unified picture or duplicate something? | Unified model |
| Is it correlated with existing edges or orthogonal? | Diversification |
| How does it size? | Kelly |
| What's the infrastructure cost? | Infrastructure as edge |
| Will it feed the learning loop? | Continuous improvement |
| Can a human explain why it works? | Causal mechanism (nice to have) |

If a candidate signal can't answer most of these questions, it's not ready. It goes into shadow mode, not production.

This is how Simons built Medallion. This is how we build this.
