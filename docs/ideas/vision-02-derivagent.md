# DerivAgent — Derivatives Intelligence & Autonomous Options Execution Platform (Vision)

**Status:** draft
**Version:** 1.0
**Created:** 2026-03-04
**Last Updated:** 2026-06-17
**Context:** Derivatives market structure intelligence + autonomous options execution
**Priority:** low
**Milestone:** future (post-v2.8)
**Tags:** derivagent, options, derivatives, vol-surface, gex, execution, platform

---

## Core Concept

DerivAgent is a full-stack autonomous derivatives platform with two tightly coupled layers:

1. **DerivAgent Intelligence** — reads the options market structure (vol surface, GEX, VANNA/CHARM, VRP, skew, term structure) and publishes derivatives regime signals for the broader product family
2. **DerivAgent Execution** — an agentic options trading platform that uses the intelligence layer to autonomously select, execute, manage, and learn from options strategies

While IndicAgent reads price/volume (the *what*) and QualAgent reads macro/sentiment (the *why*), DerivAgent reads **derivatives market structure** (the *how the market is positioned and what it fears*) — and then acts on that intelligence autonomously through options strategies.

### Renaissance Frame

DerivAgent embodies Renaissance principles:

- **Let the system run:** Options markets are an information market about the future. Every option price embeds collective belief about probability. DerivAgent reads those beliefs systematically and acts on them — not through discretionary judgment, but through measured structural features.
- **Earn the right through proof:** The Volatility Risk Premium (VRP) is a documented, persistent edge. But DerivAgent strategies start in shadow mode. Promotion requires statistical proof (p < 0.05, n ≥ 100) that the edge persists in the current regime.
- **Segment relentlessly:** VRP varies by regime. GEX effects vary by expiry. Skew signals vary by volatility environment. Every strategy is conditioned on regime context — no global rules.
- **Data quality over model complexity:** The options market publishes its full state every day. The surface, the Greeks, the positioning — all measurable. DerivAgent starts with clean data and simple models before adding complexity.
- **Instrument everything:** Every options trade, every surface snapshot, every GEX flip — captured. Nothing is dropped. The training set is complete.

### Architectural Positioning

DerivAgent fits the shared spine architecture:

- **Ring 2 daemon** — Would live under `services/` when implemented; class and file names derive from the naming system at build time (the `_agent` suffix is retired)
- **Two-layer architecture**: Intelligence layer (publishes `deriv:*` events) + Execution layer (autonomous options trading)
- **Event publisher** — Publishes to `deriv:*` topics via `stream_keys.py`
- **Event subscriber** — Subscribes to options chain data (OPRA feeds), market data for hedge calculation
- **DAG-compliant** — Data flows one direction: options data → surface construction → regime signals → Kafka → consumers
- **APR-governed** — All thresholds, VRP filters, strategy parameters live in `config_state` under `deriv.*` namespace
- **Shadow-governed** — Every strategy enrolls in shadow. Promotion requires bootstrap CI > 0 at 95% confidence
- **Aegis-aware** — All execution respects AegisAgent pre-trade checks and risk limits


## Product family (updated)

| Product | Role | Status |
|---------|------|--------|
| **IndicAgent** | Quantitative market intelligence: I1–I8 pipeline, indicators, patterns, signals | Live |
| **QualAgent** | Qualitative intelligence: macro, COT, prediction markets, sentiment, QualScore | Vision |
| **DerivAgent** | Derivatives intelligence + autonomous options execution platform | Vision |
| **TradeAgent** | Autonomous futures trading: consumes IndicAgent + QualAgent + DerivAgent signals | Vision |

**DerivAgent is a peer of TradeAgent, not a dependency.** TradeAgent trades futures directionally. DerivAgent trades options with a primarily volatility-driven edge. They consume the same intelligence platform but operate in different markets with different mechanics, different strategy types, and a different primary edge source (VRP + vol regime vs technical structure + qualitative context).

---

## The two-layer architecture

```
┌─────────────────────────────────────────────────────────────┐
│  DERIVAGENT INTELLIGENCE LAYER                              │
│  Vol surface · GEX · VANNA/CHARM · VRP · Skew · Term       │
│  structure · PDF extraction · Expiry calendar               │
│  → Publishes: deriv:regime:* streams for all consumers      │
└────────────────────────┬────────────────────────────────────┘
                         │ feeds
┌────────────────────────▼────────────────────────────────────┐
│  DERIVAGENT EXECUTION LAYER                                 │
│  Strategy selection agent · Strike/expiry optimizer ·       │
│  Portfolio Greeks manager · Execution engine ·              │
│  Lifecycle agent (adjust/roll/exit) · Learning agent        │
│  → Trades options autonomously within user guardrails       │
└─────────────────────────────────────────────────────────────┘
```

The intelligence layer is the foundation — it would exist even if the execution layer were never built (its outputs feed IndicAgent, QualAgent, and TradeAgent). The execution layer is the full product expression: intelligence-driven autonomous options trading.

---

## The core insight

Options markets are an **information market about the future**. Every option price embeds the market's collective belief about the probability of a given price range over a given timeframe. That belief is not static — it shifts as information flows in, as hedging demand changes, as dealer positioning evolves.

**DerivAgent Intelligence reads those beliefs systematically.**  
**DerivAgent Execution acts on them as a primary edge source.**

The options market has a structural feature that most traders miss: there is a **persistent, measurable edge in selling volatility**. On average, implied volatility (what the market charges for options) exceeds realized volatility (what options are actually worth) — the Volatility Risk Premium. This premium is not a fluke; it exists because option buyers pay for insurance and peace of mind. Systematically selling that overpriced insurance — intelligently, with precise regime filtering — is the primary edge DerivAgent Execution harvests.

> *"The options market knows things the price chart doesn't. DerivAgent listens, and then trades."*

---

## The boundary: DerivAgent vs QualAgent

This distinction matters for architecture and design. Both platforms touch options data. The split:

| Signal | Belongs to |
|--------|-----------|
| Put/call ratio as crowd sentiment (are people buying fear?) | **QualAgent** |
| Net options premium — dollars flowing into puts vs calls | **QualAgent** |
| Unusual options activity as positioning signal | **QualAgent** |
| IV rank/percentile as a sentiment extreme flag | **QualAgent** (receives from DerivAgent via published stream) |
| Volatility surface construction across strikes/expiries | **DerivAgent** |
| GEX (Gamma Exposure) as market-making mechanic | **DerivAgent** |
| VANNA / CHARM / dealer hedging flows | **DerivAgent** |
| Volatility risk premium (implied vs realized vol spread) | **DerivAgent** |
| Skew, risk-reversal, risk-neutral probability density | **DerivAgent** |
| Term structure shape and evolution | **DerivAgent** |
| Expiry mechanics, pin risk, post-expiry release | **DerivAgent** |

**The conceptual line:** QualAgent uses options data to understand *crowd psychology and sentiment*. DerivAgent uses options data to understand *market structure, mechanical flows, and pricing efficiency*.

---

## Core capabilities

### 1. Volatility surface — the full picture

The volatility surface is a three-dimensional map: implied volatility (Z-axis) across option strike (X-axis) and expiry (Y-axis). A single IV number (like VIX) is just one point on this surface — the surface contains far more information.

**What the surface reveals:**
- **Skew:** The difference in IV between OTM puts and OTM calls at the same expiry. High put skew = the market is paying a premium to hedge downside. Compressed skew = complacency.
- **Term structure:** IV across different expiry months. Normal contango (near-term < far-term = calm market). Backwardation (near-term > far-term = active fear — the market is more worried about the next 30 days than the next 6 months).
- **Vol smile / smirk:** How IV changes as you move away from at-the-money in either direction. The shape encodes the market's perceived tail risk.
- **Surface evolution:** How the surface changes day over day, week over week. A surface that is steepening on the put side while the market rallies is a warning sign — smart money is hedging into strength.

**Implementation:** Construct the surface daily (or intraday) from options chain data (CBOE/OPRA). Store as a snapshot. Compute diffs. Publish surface metrics as structured regime signals.

---

### 2. GEX — Gamma Exposure as a market microstructure signal

Gamma Exposure (GEX) is one of the most powerful, most misunderstood signals in modern markets. It describes **how options market makers must hedge their books as price moves**, creating a mechanical feedback loop between options positioning and spot price behavior.

**The mechanics:**
- Options market makers (MMs) are typically short options to customers (who buy puts for protection, buy calls for leverage)
- Being short options means being short gamma: as price rises, MMs must buy more futures; as price falls, MMs must sell more futures
- This creates **price stabilization in positive gamma regimes**: MM hedging dampens moves (sell rallies, buy dips)
- In **negative gamma regimes** (when MMs are net long options, often near large expiries or tail events), MM hedging amplifies moves (buy strength, sell weakness)

**The GEX number:** Aggregate net gamma across all options on an underlying, converted to dollar terms. Positive = dealers are short gamma = market is pin-prone and mean-reverting. Negative = dealers are long gamma = market is unstable and trend-prone.

**Why it matters for IndicAgent signals:**
- Mean-reversion setups (VWAP deviation, Kalman, session extremes) have higher expected value in positive gamma environments — the MM community is mechanically doing the same trade
- Trend-following setups have higher expected value in negative gamma environments — MMs amplify the move rather than dampen it
- This is a direct regime modifier for IndicAgent's aggregator

**Key levels:** GEX is not just a single number — it has concentration at specific strikes (gamma walls). Near these strikes, dealer hedging creates gravitational pull (the market tends to pin). Above the top gamma wall, dealers flip long gamma above that level, changing the regime for moves beyond it.

**Published outputs:**
- `deriv:gex:total` — aggregate GEX in dollar terms
- `deriv:gex:regime` — `positive` / `negative` / `transitioning`
- `deriv:gex:key_levels` — strikes with highest gamma concentration (pin magnets)
- `deriv:gex:flip_level` — price at which the gamma regime changes sign

---

### 3. VANNA and CHARM — second-order hedging flows

GEX captures gamma hedging (how MMs hedge as price moves). VANNA and CHARM capture how hedging flows shift over time and as volatility changes — the second-order Greeks that create predictable price pressure at specific times.

**VANNA (∂Delta/∂IV or ∂Vega/∂Spot):**
When volatility changes, the delta of options changes (VANNA). This means dealers must rehedge not just when price moves, but when IV moves. In a falling volatility environment (e.g. post-event vol crush), VANNA flows create predictable buying pressure as dealers unwind hedges. In a rising vol environment, VANNA creates selling pressure.

**The VANNA rally:** When a risk event passes and IV collapses, VANNA flows force dealers to buy equities/futures back. This is the mechanical explanation for many "relief rallies" after Fed meetings, CPI prints, and earnings. DerivAgent can predict the direction and approximate magnitude of these flows before they happen.

**CHARM (∂Delta/∂Time):**
As time passes, option deltas decay — specifically OTM options lose delta as expiry approaches. Dealers must rehedge this daily. CHARM flows are **predictable by calendar** — they happen every day, but concentrate around weekly/monthly expiry as large numbers of options approach zero delta.

- Near weekly expiry (Thursday–Friday): CHARM flows can create directional pressure if large OI is positioned away from ATM
- Monthly OPEX: larger CHARM effect, often creates the "OPEX drift" traders observe

**Published outputs:**
- `deriv:vanna:flow_direction` — buying or selling pressure from current IV regime
- `deriv:charm:daily_flow` — estimated daily directional flow from time decay
- `deriv:second_order:summary` — combined VANNA + CHARM expected flow for the session

---

### 4. Volatility Risk Premium (VRP) — the persistent options edge

The Volatility Risk Premium is one of the most documented, persistent edges in financial markets: **implied volatility consistently overestimates realized volatility** on average. The market pays more for protection than the protection is mathematically worth.

This premium exists because:
- Option buyers pay for insurance and peace of mind (they accept paying slightly too much)
- Market makers charge a risk premium for taking the other side of uncertain outcomes
- Systematic option sellers have historically earned excess returns vs. equivalent futures positions

**VRP measurement:**
- `VRP = IV_1month_implied - realized_vol_1month_historical`
- When VRP is high (options are expensive relative to recent realized vol) → mean reversion toward lower IV is likely → environment favors IndicAgent mean-reversion setups over trend
- When VRP is low or negative (options are cheap) → low-premium environment; possible vol expansion ahead

**VRP percentile vs history:** A VRP at the 85th percentile over 2 years is a different signal than a VRP at the 30th percentile. Track it in context.

**Connection to IndicAgent:** High VRP environments correlate with elevated put/call ratios and often precede market stabilization. Low VRP environments (cheap options) often precede volatility events. This is a regime signal for IndicAgent's signal confidence.

**Published outputs:**
- `deriv:vrp:current` — current VRP in vol points
- `deriv:vrp:percentile` — VRP percentile vs 2-year history
- `deriv:vrp:regime` — `elevated` / `normal` / `compressed`

---

### 5. Skew — what the market fears (and doesn't fear)

Skew measures the asymmetry of the volatility smile — specifically how much more expensive OTM puts are vs OTM calls at the same expiry and distance from ATM.

**Reading skew:**
- **High put skew (steep):** The market is aggressively hedging downside. Institutions are paying a premium for protection. This often signals that smart money is defensively positioned while price may still be elevated — a fragility signal.
- **Low put skew (flat/compressed):** Complacency. The market is not paying for downside protection. Historically, compressed skew environments precede sharp downside moves when the catalyst arrives — no one is hedged.
- **Call skew elevation:** Unusual — suggests the market is hedging or speculating on a large upside move. Seen before short squeezes, acquisition announcements, or macro regime reversals.

**Skew evolution:** Not just the current level but how skew is changing. If the market is rallying but put skew is steepening simultaneously, smart money is hedging into strength — a warning sign worth flagging.

**25-delta risk reversal:** The most common skew summary. Negative risk-reversal = puts more expensive than calls = downside hedging premium. Track its percentile vs history.

**Published outputs:**
- `deriv:skew:25d_rr` — 25-delta risk reversal value
- `deriv:skew:percentile` — put skew percentile vs 2-year history
- `deriv:skew:regime` — `steep` / `normal` / `compressed`
- `deriv:skew:evolution_flag` — `steepening_into_rally` / `flattening_into_selloff` (the warning signals)

---

### 6. Vol term structure — near-term vs long-term fear

The shape of the VIX term structure (or equivalent for the underlying) reveals how the market distributes fear across time.

**Normal contango:** M1 (near-term) < M2 < M3. The market is calm near-term; some uncertainty further out. Standard. Options selling strategies work well.

**Flat:** M1 ≈ M2 ≈ M3. Unusual. Often a transitional state.

**Backwardation:** M1 > M2 > M3. Near-term panic — the market is more worried about the next 30 days than the next 6 months. This is the signal structure of crisis. Seen in March 2020, August 2015, October 2008.

**M1/M2 ratio** as a single number: values below 1.0 are backwardation. Track the ratio and its rate of change (the market moving toward backwardation is as important as being in backwardation).

**Term structure and IndicAgent:** In backwardation, mean-reversion setups have historically lower win rates — the elevated near-term fear creates violent moves that stop out tight positions. IndicAgent's position sizer should reduce size in backwardation regimes.

**Published outputs:**
- `deriv:term_structure:m1m2_ratio` — VX1/VX2 ratio
- `deriv:term_structure:shape` — `contango` / `flat` / `backwardation`
- `deriv:term_structure:evolution` — `steepening_toward_backwardation` (warning flag)

---

### 7. Options-implied probability distribution — the market's probability forecast

The most sophisticated capability in DerivAgent. The options market implies a complete **risk-neutral probability distribution** of future price outcomes — not just "will it go up or down" but a full PDF of where price might land at expiry.

**How it works:** By extracting IV at each strike across an expiry, and applying the Breeden-Litzenberger formula (or similar), we can derive the market's implied probability density function for the underlying at that expiry date.

**What this reveals:**
- **Fat tails:** Are tail probabilities being priced more or less than a normal distribution would suggest?
- **Bimodal distributions:** When IV is elevated at both OTM puts and OTM calls, the distribution is bimodal — the market thinks price is going to move meaningfully, but doesn't know in which direction (e.g., pre-earnings, pre-Fed decision)
- **Skewed distribution:** When put-side IV is much higher than call-side, the probability density is skewed left — the market assigns higher probability to downside scenarios
- **Comparison to historical:** Compare the implied distribution to the historically realized distribution over equivalent periods — divergences are potential pricing inefficiencies

**TradeAgent application:** Before taking a signal, know the market's implied probability that price reaches the target level. If the market implies only 20% probability of reaching target but IndicAgent's setup has historically achieved it 45% of the time — that's a legitimate edge. The options market is underpricing the probability of this specific setup's outcome.

**Published outputs:**
- `deriv:pdf:current` — implied probability distribution for nearest monthly expiry
- `deriv:pdf:bimodal_flag` — binary, elevated when distribution is bimodal (pre-event uncertainty)
- `deriv:pdf:tail_premium` — how much fat-tail risk is priced vs historical baseline

---

### 8. Expiry calendar and mechanics

Options expiry creates predictable mechanical events. DerivAgent maintains the full expiry calendar and publishes flags ahead of key expiry events.

**Key expiry events:**
- **Weekly expiry (Friday):** SPX/SPY options expire every Friday. Largest OI concentrations create pin risk (price gravitates toward high-OI strikes) and post-expiry release (once pinning force is gone, price can move freely in the direction of the next catalyst).
- **Monthly OPEX (third Friday):** Larger than weekly; more significant CHARM and VANNA flows.
- **Quarterly OPEX (March, June, September, December):** Largest of all. Triple witching (futures + equity options + index options expire simultaneously). Significant volume, potential for unusual price action.
- **VIX settlement (Wednesday before monthly OPEX):** VIX futures settle on Wednesday; can cause unusual vol dynamics in the days preceding.

**Published outputs:**
- `deriv:expiry:next_weekly` — days until next weekly expiry
- `deriv:expiry:next_monthly` — days until next monthly OPEX
- `deriv:expiry:next_quarterly` — days until next quarterly
- `deriv:expiry:vix_settlement` — days until next VIX settlement
- `deriv:expiry:active_pin_risk` — flag when price is within N points of a major gamma concentration strike

---

## DerivAgent Execution Layer — Agentic Options Trading Platform

This is the second layer of DerivAgent: an autonomous options strategy execution platform that uses the intelligence layer as its primary edge source. The concept is similar to Option Alpha's bot platform but at a fundamentally different intelligence tier — instead of user-defined if-then rules, the agent uses vol regime intelligence to autonomously select, size, execute, manage, and learn from options strategies.

---

### The primary edge: Volatility Risk Premium harvesting

The core edge is structural and well-documented: **implied volatility persistently exceeds realized volatility** on average across major indices and ETFs (SPX, SPY, QQQ, IWM, and their futures equivalents). This VRP exists because:
- Institutional investors pay for portfolio insurance regardless of price efficiency
- Market makers charge a risk premium to take the other side of uncertain outcomes
- Retail buyers pay convenience and leverage premiums

Systematically selling this overpriced insurance is the primary profit engine. But naive vol selling — selling options indiscriminately — is dangerous (the "picking up nickels in front of a steamroller" problem). **Intelligence-gated vol selling** — only selling when VRP is elevated, regime is favorable, gamma environment is supportive, and macro context is calm — is the edge DerivAgent Execution provides.

**Renaissance principle applied:** This is measurable (VRP in vol points), validatable (decades of backtested data), and operational (systematic, rules-based with AI-assisted regime gating). It passes all three validation gates.

---

### Options strategy taxonomy — when to run what

The intelligence layer maps current market conditions to the optimal strategy type. Not every strategy works in every regime — the agent must know when to deploy each.

#### Volatility selling strategies (primary income engine)

Run when: **VRP elevated (>60th percentile), positive gamma environment, no pre-event flags, QualScore neutral to bullish, term structure in contango.**

| Strategy | Structure | Profit from | Max loss |
|----------|-----------|------------|---------|
| **Iron condor** | Short OTM call + long further OTM call + short OTM put + long further OTM put | Price staying in range + vol crush | Spread width minus premium |
| **Short strangle** | Short OTM call + short OTM put (undefined risk) | Price staying in range + vol crush | Theoretically large (must have tight risk rules) |
| **Iron butterfly** | Short ATM call + long OTM call + short ATM put + long OTM put | Price pinning near ATM | Spread width minus premium |
| **Credit spread (vertical)** | Short closer strike + long further strike (put or call side only) | Directional + vol crush | Spread width minus premium |
| **Cash-secured put** | Short OTM put | Price staying above strike + vol crush | Strike minus premium (large; needs capital) |
| **Covered call** | Long underlying + short OTM call | Price staying below strike + time decay | Downside on underlying |

#### Directional strategies (secondary, signal-triggered)

Run when: **IndicAgent generates a high-confidence directional signal + DerivAgent surface shows favorable entry (OTM options fairly priced, vol not overpriced in the target direction).**

| Strategy | Structure | Profit from | Use when |
|----------|-----------|------------|---------|
| **Long call vertical (debit spread)** | Long lower strike call + short higher strike call | Directional move up | Bullish signal, IV moderate — cheaper than outright call |
| **Long put vertical (debit spread)** | Long higher strike put + short lower strike put | Directional move down | Bearish signal, IV moderate |
| **Long call** | Single long OTM or ATM call | Large directional move up | Pre-breakout setup, VRP compressed (options cheap) |
| **Long put** | Single long OTM or ATM put | Large directional move down | Bearish catalyst, VRP compressed |
| **Risk reversal** | Short OTM put + long OTM call (or reverse) | Directional with skew edge | When skew extreme creates asymmetric cost |

#### Volatility expansion strategies (tail / event plays)

Run when: **PDF bimodal flag (pre-event uncertainty), VRP compressed, term structure flat or inverted — options are cheap relative to expected move.**

| Strategy | Structure | Profit from | Use when |
|----------|-----------|------------|---------|
| **Long straddle** | Long ATM call + long ATM put | Large move in either direction | Pre-earnings, pre-Fed, bimodal PDF detected |
| **Long strangle** | Long OTM call + long OTM put | Large move in either direction | Cheaper than straddle; wider break-evens |
| **Calendar spread** | Short near-term option + long same-strike further-term option | Near-term vol decaying faster; position for post-event direction | Steep contango + pre-event |

#### Theta harvesting with structure-aware entries

Run when: **High OI concentration near GEX pin level — the market is likely to pin near a specific strike at expiry.**

- **Pin trade:** Sell short-dated straddle or strangle centred on the highest-OI/GEX strike
- **Wing hedge:** Defined risk always — buy OTM protection on both sides
- The GEX map tells you where the gravity is. Enter the position that profits from the market staying near that gravity.

#### Skew trades

Run when: **Put skew at extreme (>85th percentile) — puts are historically expensive relative to calls.**

- **Risk reversal:** Sell the expensive OTM put, buy the cheap OTM call — net credit or small debit, directional neutral to slightly bullish
- The edge: skew mean-reverts. Selling rich puts and buying cheap calls captures the spread as skew normalizes.
- Requires macro context support (QualAgent not in risk-off mode)

#### Calendar and term structure trades

Run when: **VIX term structure in steep contango — near-term vol is cheap relative to far-term, or vice versa.**

- **VIX calendar:** Buy near-term VIX futures / sell far-term (in backwardation) or sell near-term / buy far-term (in steep contango)
- **Options calendar spread:** Sell near-term option, buy same-strike far-term option. Profits when near-term vol decays faster than far-term.
- The term structure IS the edge here — no directional bet required.

---

### The agentic execution loop

The execution layer operates as a continuous agentic loop, running on a defined cadence (e.g., at market open, at market close, and on event triggers):

```
┌─────────────────────────────────────────────────────────┐
│  1. REGIME ASSESSMENT                                   │
│  Read all DerivAgent intelligence streams:              │
│  VRP regime, gamma env, skew, term structure, PDF,      │
│  expiry flags, GEX levels                               │
│  + Read QualAgent streams: macro regime, QualScore,     │
│    pre-event flags, crowding score                      │
│  + Read IndicAgent: current directional signals,        │
│    confidence, regime                                   │
└────────────────────┬────────────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────────────┐
│  2. STRATEGY SELECTION AGENT                            │
│  Based on regime confluence, select strategy type:      │
│  → VRP high + gamma positive + calm macro = iron condor │
│  → IndicAgent bullish + vol moderate = call spread      │
│  → PDF bimodal + VRP compressed = long straddle         │
│  → GEX pin detected + near expiry = pin trade           │
│  → Skew extreme = risk reversal                         │
└────────────────────┬────────────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────────────┐
│  3. STRIKE AND EXPIRY OPTIMIZER                         │
│  Select specific strikes and expiry:                    │
│  → Short strikes: use GEX levels as natural targets     │
│  → Long strikes (wings): beyond PDF tail probability    │
│  → DTE (days to expiry): regime + event calendar aware  │
│  → Expected return vs risk: surface-derived EV calc     │
│  → SmartPricing: target mid or better; avoid chasing   │
└────────────────────┬────────────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────────────┐
│  4. PORTFOLIO RISK GATE                                 │
│  Before sending any order:                              │
│  → Check portfolio delta within limits                  │
│  → Check portfolio vega within limits                   │
│  → Check new trade's theta contribution vs target       │
│  → Check max loss on this position fits risk budget     │
│  → Check correlation with existing positions            │
│  → Check HITL guardrails (user-defined)                 │
└────────────────────┬────────────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────────────┐
│  5. EXECUTION ENGINE                                    │
│  Multi-leg order management:                            │
│  → Submit as combo order (atomic multi-leg where        │
│    supported) or sequenced with smart pricing           │
│  → Dynamic mid-price adjustment with intervals          │
│  → Fill confirmation, position record creation          │
│  → Greeks capture at fill                               │
└────────────────────┬────────────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────────────┐
│  6. LIFECYCLE AGENT (continuous monitoring)             │
│  Runs every 15min / on event triggers:                  │
│  → Check P&L vs stop-loss threshold (max loss rule)     │
│  → Check delta drift (re-hedge if needed)               │
│  → Check DTE — initiate roll if within N days           │
│  → Check regime change — does strategy still fit?       │
│  → Check vol expansion — should we take profit early?   │
│  → Check GEX shift — have the pin levels moved?         │
│  → Manage adjustments (add leg, convert, roll)          │
│  → Target profit and exit gracefully                    │
└────────────────────┬────────────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────────────┐
│  7. OUTCOME CAPTURE AND LEARNING AGENT                  │
│  On position close:                                     │
│  → Record: strategy type, entry regime, exit regime,    │
│    P&L, edge realized vs edge expected, regime label    │
│  → Compare: expected EV at entry vs actual outcome      │
│  → Feed into strategy performance analytics             │
│  → Update strategy selection weights over time          │
│  → Flag strategies with decaying edge for review        │
└─────────────────────────────────────────────────────────┘
```

---

### Portfolio Greeks management — the risk spine

Options create multi-dimensional risk. The portfolio risk manager tracks and enforces limits on all Greeks continuously:

| Greek | What it measures | Limit type | Why it matters |
|-------|----------------|-----------|---------------|
| **Delta** | Directional exposure (like being long/short N shares) | Max net delta vs portfolio value | Prevents DerivAgent from becoming a directional bet disguised as an options strategy |
| **Gamma** | Rate of delta change (acceleration of directional exposure) | Max net gamma | Negative portfolio gamma = dangerous in large moves; must be limited |
| **Theta** | Daily time decay (profit for short options, cost for long) | Target theta range | The income engine — too low means the strategy isn't earning; too high means too much risk |
| **Vega** | Sensitivity to IV change | Max net vega | Limits vol regime exposure; prevents being short too much vega before a potential vol expansion |
| **Vanna** | Delta sensitivity to IV change | Monitor, alert | Captures second-order risk; important near vol events |
| **Charm** | Delta sensitivity to time | Monitor | Important near expiry |

**Daily Greeks dashboard:** Portfolio-level Greeks tracked in real time. If any breach a soft limit, the lifecycle agent flags it. If a hard limit is breached, the system automatically reduces exposure.

**Target profile for a neutral income strategy:**
```
Delta:   near zero (±1% of portfolio value)
Gamma:   negative, but limited (not extreme short gamma)
Theta:   positive (income generating)
Vega:    negative, limited (short vol, but not dangerously so)
```

---

### Strike and expiry selection intelligence

This is where DerivAgent Execution goes beyond rule-based platforms. Strike and expiry selection is not "sell the 16-delta strike every time" — it is informed by the intelligence layer:

**Strike selection:**
- **Short strikes:** Place near GEX key levels (natural gravitational pin points). An iron condor with short strikes AT the top and bottom GEX walls is structurally different from one placed at arbitrary deltas.
- **Long strikes (wings):** Place beyond the market-implied tail probability (from the PDF extraction). If the PDF shows only 3% probability of reaching a strike, that strike is cheap and serves as a well-priced hedge.
- **Delta targeting with regime adjustment:** In high-VRP environments (sell rich), sell slightly higher-delta options for more premium. In normal VRP environments, stay at the standard 16-delta (1 standard deviation). In low-VRP (cheap options, vol expansion risk), widen strikes or pass on the trade.

**DTE (days to expiry) selection:**
- **Income strategies:** Target 30–45 DTE for entry. Exit at 21 DTE or 50% of max profit, whichever comes first. This is the theta acceleration zone — time decay accelerates in the final 3 weeks.
- **Pre-event plays:** Enter 1–5 DTE before a catalyst (from QualAgent catalyst calendar). The pre-event vol premium is highest just before the event.
- **Post-event plays:** Enter 1–2 DTE after a major event. Vol crush is immediate; short-dated premium selling captures maximum speed of decay.
- **GEX-guided DTE:** If monthly OPEX has the highest GEX concentration, enter strategies targeting that expiry for maximum pin-risk tailwind.

---

### Multi-leg order management

Options strategies often involve 2, 4, or more legs that must be executed together. Poor multi-leg execution destroys the edge before it starts.

**Atomic combo orders:** Where the broker supports multi-leg combo orders (IBKR, TD Ameritrade, TastyTrade), submit the entire strategy as one order. This eliminates leg risk (the first leg filling and the market moving before the second fills).

**Sequential execution with hedging:** For brokers without combo order support, execute the leg that creates the most risk first, with the hedge leg following immediately. If selling a straddle: sell the put first (more downside risk), then sell the call.

**SmartPricing:**
- Target mid-price of the spread initially
- If no fill after N seconds, adjust toward the ask by M cents
- Repeat up to K times before widening the limit to ensure a fill
- Never market order multi-leg strategies — always limit orders with smart adjustment

**Fill quality tracking:** Record slippage (expected mid vs actual fill) per strategy type and per broker. Use this to calibrate entry EV estimates over time.

---

### Lifecycle management — the full trade arc

Most options traders enter well and exit poorly. DerivAgent Execution automates the full lifecycle:

**Profit taking:**
- Iron condors and credit spreads: close at 50% of max profit (well-documented as the optimal closure point for high-probability strategies)
- Short straddles/strangles: close at 25% of max profit (lower threshold because of undefined risk)
- Long premium positions: close at 2× premium paid or at the target delta

**Loss management (the rules that save accounts):**
- Iron condors: close if loss reaches 2× the premium received (stops out before max loss)
- Short strangles: close if price reaches the short strike (maximum acceptable move)
- Hard stop: any position hitting 3× credit received is closed immediately, no exceptions
- "Never hold short premium through a major unknown event" — close or roll before QualAgent pre-event flag activates if the strategy would be hurt by the event

**Rolling:**
- **Roll for time:** When DTE drops below 21 on an income position that hasn't reached profit target, roll to next monthly expiry. This extends duration and resets theta decay acceleration.
- **Roll for strikes:** If price challenges a short strike and vol is still elevated, roll the threatened side further OTM and out in time. Collect enough credit to make the roll worthwhile.
- **Do not roll indefinitely:** Maximum N rolls per position before accepting the loss and moving on. Continuous rolling hoping for a return to the original range is a classic emotional trap — the system must have a limit.

**Adjustments:**
- **Convert strangle to iron condor:** If price moves toward one short strike, buy the opposing side's OTM wing to define risk and reduce margin requirement
- **Add spread on threatened side:** Turn an untested vertical into a butterfly by adding a long further-OTM option
- **Remove one side (legout):** If price has moved decisively in one direction and one side is worthless, close the threatened side and let the safe side run to expiry

---

### HITL guardrails and user configuration

DerivAgent Execution operates within user-defined guardrails. Unlike a rule engine (Option Alpha's model), the guardrails constrain the agent's autonomous decisions rather than defining them:

| Guardrail category | Example parameters |
|-------------------|-------------------|
| **Instruments** | Which underlyings to trade (SPX, SPY, QQQ, IWM, individual tickers) |
| **Strategy whitelist** | Which strategies the agent is allowed to deploy (e.g., "iron condors only" or "no undefined risk") |
| **Max portfolio delta** | Net delta as % of account cannot exceed X |
| **Max portfolio vega** | Net vega cannot exceed Y in vol points |
| **Max margin utilization** | Agent cannot use more than Z% of available margin |
| **Min VRP threshold** | Only sell premium if VRP > N percentile |
| **Min confidence threshold** | Only take directional plays if IndicAgent confidence > M% |
| **Pre-event rule** | Auto-close or auto-pause N hours before any major event |
| **Daily trade limit** | Max N new positions per day |
| **Max positions open** | Agent cannot hold more than N positions simultaneously |
| **Profit target** | Monthly theta target (e.g., target 2–4% monthly on deployed capital) |
| **Max drawdown** | Pause agent if account drawdown exceeds P% |

**Guardrails are enforced before any order is sent.** The agent can propose a trade; the guardrail layer validates it. If it violates any guardrail, the trade is blocked. This is not optional — the enforcement is in the order layer, not in the agent's reasoning.

---

### Competitive positioning vs Option Alpha

Option Alpha is the most visible automated options trading platform. The distinction is fundamental:

| Dimension | Option Alpha | DerivAgent Execution |
|-----------|-------------|---------------------|
| Strategy selection | User writes if-then rules | Agent selects based on vol regime intelligence |
| Strike selection | User specifies (e.g., "16 delta always") | Intelligence-optimized: GEX levels, PDF tails, VRP tier |
| Regime awareness | None | Full: VRP, gamma environment, skew, term structure |
| Pre-event intelligence | "Earnings date" flag only | QualAgent full catalyst calendar + prediction markets |
| Greeks management | Basic position limits | Full portfolio Greeks engine (delta, gamma, theta, vega) |
| Lifecycle intelligence | User-defined rules | Regime-aware: vol expansion = early exit; regime flip = adjust |
| Learning loop | None | Outcome history → strategy weight updates |
| Pricing | Free (broker acquisition) | Premium subscription (intelligence is the product) |

The key framing: **Option Alpha automates execution. DerivAgent automates intelligence-driven selection and execution.** These are different products serving different needs.

---

### Learning loop — DerivAgent's self-improvement

Analogous to QualAgent's quantamental feedback loop, but for options strategy performance:

**What gets recorded on every trade:**
```
strategy_type, underlying, entry_dte, entry_vrp_pct, entry_skew_pct,
entry_gamma_env, entry_qual_score, entry_mac_regime,
strikes_vs_gex_levels, fill_quality (slippage),
lifecycle_events (adjustments, rolls),
exit_reason (profit_target | stop_loss | expiry | roll),
realized_pnl, expected_pnl_at_entry, edge_realized
```

**What gets analyzed (weekly):**
- Win rate by strategy type × VRP regime bucket
- Average edge realized vs edge expected (measures entry quality)
- Which regime conditions produce the best iron condor outcomes? Best directional spread outcomes?
- Which strike selection heuristics (GEX-aligned vs delta-targeted) produce better outcomes?
- Which lifecycle decisions (50% profit target vs 21-DTE exit) perform better in which regimes?

**What gets updated:**
- Strategy selection weights (which strategy gets priority in which regime)
- VRP threshold parameters (at what VRP percentile does selling premium become attractive?)
- DTE preference by strategy type
- Roll decision triggers

This is the compound learning machine — every trade makes the next trade slightly smarter.

---

## Architecture overview

DerivAgent is a standalone application with its own data ingestion, computation engine, storage, and output streams.

### Data sources

| Source | Data | Cadence |
|--------|------|---------|
| **CBOE / OPRA** | Full options chain (strikes, expiries, bid/ask, OI, volume) | Intraday (15-min delayed free; real-time requires subscription) |
| **CBOE public** | VIX index, VIX futures term structure | Real-time (free) |
| **CBOE put/call data** | Daily aggregate put/call ratios | Daily (free) |
| **Market data feed** | Underlying prices (IndicAgent or Databento) | Real-time |

### Services

| Service | Responsibility |
|---------|----------------|
| **Options chain ingestion** | Pull and normalize full chain data. Compute mid-prices, validate for obvious errors. |
| **Surface builder** | Construct implied vol surface from chain. Apply interpolation (e.g. SVI parameterization). Store daily snapshots. |
| **GEX engine** | Compute aggregate gamma by strike. Sum across all expiries. Compute net GEX, key levels, flip level. |
| **Second-order engine** | Compute VANNA and CHARM flows from current surface and expected vol/time changes. |
| **VRP tracker** | Compute IV vs realized vol over multiple windows (10d, 20d, 30d). Track percentile vs history. |
| **PDF extractor** | Apply Breeden-Litzenberger to derive risk-neutral density. Flag bimodal distributions. |
| **Term structure monitor** | Track VIX/VX futures curve. Compute M1/M2 ratio. Detect contango/backwardation transitions. |
| **Expiry calendar** | Maintain calendar of all expiry events. Publish proximity flags. |
| **Regime publisher** | Aggregate all signals into published regime streams. |

### Output streams

| Stream | Contents |
|--------|----------|
| `deriv:regime:gamma_env` | `positive` / `negative` / `transitioning` + aggregate GEX |
| `deriv:gex:key_levels` | Pin levels, flip level, top 3 gamma concentration strikes |
| `deriv:vrp:current` | VRP value + percentile + regime label |
| `deriv:skew:current` | 25d risk-reversal + percentile + evolution flag |
| `deriv:term_structure:shape` | Contango/backwardation + M1/M2 ratio + evolution flag |
| `deriv:second_order:flow` | VANNA + CHARM flow direction and magnitude estimate |
| `deriv:pdf:current` | Implied PDF snapshot + bimodal flag + tail premium |
| `deriv:expiry:flags` | Proximity flags for weekly/monthly/quarterly expiry |

---

## How DerivAgent feeds the product family

### → IndicAgent (optional exogenous input)

IndicAgent's I4 regime layer can optionally read DerivAgent's gamma regime as a signal modifier:
- Positive gamma → upweight mean-reversion setups (VWAP deviation, session extremes, Kalman)
- Negative gamma → upweight momentum/breakout setups; widen stops on all setups
- Pre-expiry pin flag → reduce confidence on breakout setups near gamma walls

### → QualAgent (regime coordination)

DerivAgent publishes `deriv:vrp:percentile` and `deriv:term_structure:shape` which QualAgent ingests as components of its macro regime synthesis. Specifically:
- VRP compressed + term structure flat → macro fragility signal → QualScore adjustment
- Term structure moving toward backwardation → QualAgent risk-off flag → transition probability spike

### → TradeAgent (sizing and risk)

The most direct consumer. Before every signal, TradeAgent's lead agent reads:
- **Gamma regime:** Determines baseline sizing multiplier. Positive gamma = normal sizing. Negative gamma = reduce 20–40%.
- **GEX key levels:** Are entry/target/stop near a gamma wall? If target level is a major pin level, the trade has a mechanical tailwind; if stop is at a pin level, there's gravitational support.
- **Term structure:** Backwardation → reduce all sizes 30%; tighten stops; no new trend trades.
- **VANNA flow forecast:** If a VANNA-driven rally is expected today (vol crush post-event), this provides tailwind for long setups and headwind for short setups independent of IndicAgent's technical read.
- **Expiry proximity:** Near weekly OPEX → flag active pin risk; near monthly/quarterly → reduce size, widen expectations for unusual flow.

---

## Renaissance framing for derivatives intelligence

Jim Simons' team specifically used **kernel methods** and **non-linear feature mapping** to extract structure from market data. The volatility surface is exactly this: it maps linear price data into a higher-dimensional space (the full smile and term structure) that reveals non-linear market beliefs.

Key Renaissance principles applied:

| Principle | DerivAgent application |
|-----------|----------------------|
| **Data first (1)** | Vol surface data is richer than price alone — start with the surface, derive signals |
| **State-based / non-linear (8)** | GEX regime, term structure shape are market states that explain non-linear price dynamics |
| **Alternative data (9)** | The options market is an unconventional data source that reveals non-obvious structure |
| **Signal validation (5)** | VRP is one of the most statistically validated signals in finance — high prior confidence. GEX is newer; validate before full weight. |
| **Adaptive models (11)** | GEX key levels change daily; term structure evolves; the model updates continuously rather than being static |
| **Stress testing (13)** | Test how IndicAgent setups performed in backwardation regimes, negative gamma regimes, high VRP environments before relying on these as modifiers |

---

## Key ideas to research further

**Vol surface arbitrage:** Are there systematic mispricing patterns in how the surface evolves around specific event types (Fed meetings, earnings, CPI)? Can the surface be used to identify when pre-event IV is overpriced vs fairly priced for a given signal type?

**GEX flip level as target/stop:** The GEX flip level (price at which the gamma regime inverts) is often a significant level for IndicAgent's I7 setups. It can function as an institutional-grade target level (positive gamma market heading toward the flip = natural momentum) or a stop-loss reference (negative gamma environment starting at the flip).

**Cross-asset GEX:** GEX on SPX options affects ES futures directly. But GEX on NDX/QQQ options affects NQ futures. Can DerivAgent publish a GEX-derived level for each futures instrument based on the relevant equity options chain?

**Realized vol forecasting:** VRP requires a realized vol estimate. But realized vol itself can be forecast using GARCH models (already implemented in IndicAgent's I4 context layer). DerivAgent can use IndicAgent's GARCH forecast as its realized vol estimate for VRP computation — a cross-platform data dependency worth designing explicitly.

**Vol surface clustering:** Use unsupervised learning to identify recurring vol surface "shapes" (similar to IndicAgent's regime clustering). Cluster the historical surface shapes and label each with its typical subsequent price behavior. "Surface Type 4 (inverted near-term, steep skew, compressed far-term) has preceded sharp selloffs within 5 days in 70% of historical occurrences."

---

## The big picture vision — democratizing the house edge

*Integrated from the Agentic Derivatives Platform source documents. Core positioning and market vision.*

---

### The institutional advantage gap

Major trading firms and $30B+ ETFs (JEPI, JEPQ) generate consistent profits not through market prediction but through **mathematical advantages** — systematic edges in volatility pricing, time decay, and mean reversion. These edges have been monopolised by institutions because accessing them requires:

- Millions in technology infrastructure (custom quant systems, real-time risk engines, execution infrastructure)
- PhD-level quantitative analysts and professional risk managers
- Capital minimums of $10M+ for proper diversification
- Regulatory and compliance frameworks designed for institutional operators

**The proof that the market exists:** JEPI and JEPQ grew to $30B+ AUM. They are covered call ETFs — a basic options income strategy — running at institutional scale. The demand for systematic income from options is massive and proven. What retail traders and emerging fund managers lack is the intelligence layer, not the desire.

**DerivAgent's mission:** Make the same mathematical edge accessible at any scale — from a $10K individual account to a $100M fund — through AI agents that think, adapt, and execute like professional quantitative trading teams.

The framing: *"Democratizing the house edge."* Casinos are consistently profitable not because they predict outcomes but because they have systematically favorable odds across thousands of small bets. DerivAgent applies the same philosophy — a diversified portfolio of options strategies, each with a mathematical edge, deployed intelligently by regime.

---

### The four mathematical edges being unlocked

**1. Volatility risk premium harvesting**
Implied volatility consistently trades 3–5% above realized volatility across major indices. Selling options systematically captures this structural overpricing. The institutional implementation requires real-time vol surface analysis, dynamic delta hedging, multi-timeframe coordination, and portfolio-level optimization — capabilities that DerivAgent automates.

**2. Time decay monetization**
Options lose 60–80% of their time value in the final weeks before expiration. Theta accelerates in a predictable, mathematical curve. The MEIC (Multiple Entry Iron Condor) strategy exploits this systematically with layered deployments across the steepest part of the decay curve.

**3. Mean reversion exploitation**
Markets spend 70–80% of time in range-bound conditions. Range-bound regimes are precisely where premium collection strategies (iron condors, butterflies, jade lizards) have their highest expected value. Regime detection is the intelligence gate — know when the range-bound regime is active, deploy accordingly.

**4. Flow-based systematic advantages**
Institutional order flow, gamma exposure, and dealer positioning create predictable structural flows (GEX pinning, VANNA rallies, CHARM decay pressure). Understanding these flows gives a systematic edge in entry timing, strike selection, and exit points that pure chart-based trading cannot access.

---

### "Start with AI guidance, evolve to AI autonomy"

The platform's user experience philosophy. Users don't start fully autonomous — they start with AI-recommended strategies they can review and approve, learning the logic as they go. As confidence and track record build, the system takes on more autonomy.

**Three operating modes:**

| Mode | Who controls what |
|------|-----------------|
| **Regime Router** | AI analyzes regime and recommends the optimal strategy. User approves. AI executes and manages. |
| **Strategy Buffet** | User picks a strategy category (income, directional, volatility). AI optimizes all parameters, timing, and lifecycle. |
| **Integrated Portfolio** | AI autonomously manages a balanced portfolio of strategies across regimes. User sets objectives and guardrails. System runs. |

Users can operate in different modes for different accounts or strategies. A conservative account might stay in Strategy Buffet; an advanced user lets the system run Integrated Portfolio mode for their main account.

---

### Complete strategy universe — 24 strategies

The full institutional strategy arsenal, organized by the "4 Flavors of Premium Collection" framework:

#### Flavor 1 — Range-bound premium collection
*Deploy when: ADX < 25, VIX moderate, strong support/resistance, positive gamma environment*

| Strategy | Edge | Risk profile |
|----------|------|-------------|
| **Iron Condor** | VRP + range + theta | Defined risk both sides |
| **Broken Wing Butterfly** | Asymmetric risk elimination | Net credit, one side risk-free |
| **Jade Lizard** | Eliminate upside risk entirely | No upside risk, defined downside |
| **Traditional Butterfly** | High probability price pinning | Tight profit zone, max if pins ATM |
| **Short Strangle** | Wider zones than condor | Undefined risk — requires strict stops |

#### Flavor 2 — Directional premium collection
*Deploy when: IndicAgent generates directional signal, moderate IV, confirmed trend*

| Strategy | Edge | Risk profile |
|----------|------|-------------|
| **Bull Call Spread** | Directional + debit optimization | Defined risk, limited reward |
| **Bull Put Spread** | Bullish + theta collection | Defined risk credit structure |
| **Bear Call Spread** | Bearish + theta collection | Defined risk credit structure |
| **Bear Put Spread** | Directional + debit optimization | Defined risk, limited reward |
| **Covered Call** | Income on existing holding | Caps upside, income in flat market |
| **Cash-Secured Put** | Income + potential acquisition | Assignment risk at strike |
| **Protective Put** | Insurance + hedging | Cost of protection |
| **Collar** | Protection + income | Defined range, near-zero cost |

#### Flavor 3 — Time decay strategies
*Deploy when: Low IV expecting expansion, stable price, steep contango term structure*

| Strategy | Edge | Risk profile |
|----------|------|-------------|
| **Calendar Spread** | Time decay differential + vol expansion | Long vega, positive theta |
| **Diagonal Spread** | Time decay + directional bias | Mixed delta, positive theta |
| **Double Calendar** | Range-bound + vol expansion | Multiple calendar positions |
| **0DTE Time Decay** | Extreme intraday theta capture | Extreme theta, extreme gamma risk |

#### Flavor 4 — Volatility strategies
*Deploy when: VRP compressed (cheap options), bimodal PDF detected, pre-event uncertainty*

| Strategy | Edge | Risk profile |
|----------|------|-------------|
| **Long Straddle** | Big move expectation, direction unknown | Long gamma, long vega |
| **Long Strangle** | Big move, lower cost than straddle | Long gamma, long vega, wider breaks |
| **Short Straddle** | Vol contraction + theta | Short gamma, extreme risk (use strict guardrails) |
| **Ratio Spread** | Asymmetric vol expectations | Unbalanced, requires careful management |

#### Advanced / Institutional strategies

| Strategy | Complexity | When deployed |
|----------|-----------|--------------|
| **MEIC (Multiple Entry Iron Condor)** | Advanced | Institutional income: layered condor entries over 3-hour window at 18-delta, 45 DTE. The flagship systematic income strategy. |
| **Volatility Arbitrage** | Institutional | Vol surface mispricing across strikes/expiries. Requires full surface construction. |
| **Gamma Scalping** | Professional | Dynamic delta hedging around a long gamma position. Profits from realized vol > implied vol. |

**MEIC — the institutional flagship.** Multiple Entry Iron Condor is the core of systematic income generation at institutional scale. Instead of a single iron condor entry, MEIC deploys 6 entries over a 3-hour window with staggered strikes around the ATM. This achieves a better average entry price (cost averaging into the spread), captures different volatility moments during the session, and creates a smoother overall risk profile than a single large entry.

---

### Market regime classification — routing logic

The intelligence layer drives automatic strategy routing. Seven distinct regime types, each matched to optimal strategies:

| Regime | Detection criteria | Primary strategies | Key AI enhancement |
|--------|-------------------|-------------------|-------------------|
| **Low vol, range-bound** | ADX < 25, VIX < 18, RSI 30–70, positive GEX | Iron condors, butterflies, MEIC | Strike optimization, GEX-aligned levels |
| **High IV, mean-reverting** | IV rank > 70th pct, low correlation | Short strangles, volatility harvesting, VRP selling | Vol surface analysis, regime timing |
| **Strong bullish trend** | ADX > 25, RSI > 50, momentum confirmed | Bull call/put spreads, covered calls | IndicAgent signal integration |
| **Strong bearish trend** | ADX > 25, RSI < 50, breakdown confirmed | Bear put spreads, bear call spreads | IndicAgent signal integration |
| **Moderate trending** | Directional bias with consolidations | Progressive credit laddering, directional spreads | Momentum detection, entry timing |
| **High vol, unstable** | VIX > 25, negative GEX, news events | Calendar spreads, protective strategies, long premium | QualAgent event flags, event coordination |
| **Intraday volatility spike** | Elevated intraday IV, volume spikes | 0DTE strategies, multi-entry construction | Real-time gamma management |

**The routing intelligence:** The regime is not a manual label — it is computed continuously from the DerivAgent intelligence layer (vol surface, GEX regime, term structure shape) combined with QualAgent's macro regime and IndicAgent's technical regime. The three platforms collectively determine the regime; the strategy selection agent routes to the appropriate strategy bucket automatically.

---

### The LEGO agent architecture — four layers

The execution platform is built as a modular, layered multi-agent system. Each layer can operate independently or combine with others for more sophisticated operations. Like LEGO bricks — each piece works alone, but combining creates something more powerful.

```
═══════════════════════════════════════════════════════════════
LAYER 4: AUTONOMOUS TRADING SYSTEMS (Institutional)
  Fully autonomous agent clusters — minimal human intervention
  ├── High-Frequency Premium Collection System
  │   ├── 0DTE opportunity scanner
  │   ├── Rapid execution agent (sub-second decisions)
  │   ├── Gamma explosion monitor
  │   └── Emergency shutdown agent (circuit breaker)
  └── Volatility Arbitrage System
      ├── Real-time vol surface analysis agent
      ├── Arbitrage detection agent
      ├── Complex multi-leg strategy builder
      └── Advanced Greeks / correlation monitoring
═══════════════════════════════════════════════════════════════
LAYER 3: MULTI-STRATEGY ORCHESTRATORS (Professional)
  Coordination agents managing multiple specialists simultaneously
  ├── Portfolio Balance Orchestrator
  │   ├── Strategy allocation agent (which strategies to run when)
  │   ├── Greeks coordination agent (portfolio-level balance)
  │   ├── Risk distribution agent (spread risk across approaches)
  │   └── Capital efficiency agent (margin optimization)
  └── Market Regime Adapter
      ├── Strategy rotation agent (switch on regime changes)
      ├── Transition management agent (exit old, enter new)
      ├── Performance attribution agent (which strategies winning)
      └── Learning coordination agent (cross-strategy insights)
═══════════════════════════════════════════════════════════════
LAYER 2: SINGLE STRATEGY SPECIALISTS (Modular)
  Individual strategy-focused clusters — run independently
  ├── Iron Condor Specialist
  │   Strike Selection → Greeks Management → Adjustment → Exit
  ├── Calendar Spread Specialist
  │   Term Structure → Vol Expansion → Roll Orchestration → Vega
  ├── Straddle / Strangle Specialist
  │   Event Coordination → Vol Prediction → Breakout → Dynamic Exit
  ├── Directional Spread Specialist
  │   Technical Analysis → Support/Resistance → Entry Timing → R/R
  └── MEIC Specialist (institutional income)
      Multi-entry window → Layered strikes → Greeks → Roll management
═══════════════════════════════════════════════════════════════
LAYER 1: REGIME INTELLIGENCE (Foundational — always on)
  Environmental analysis that all other layers depend on
  ├── Volatility Regime Agent (IV rank, vol forecasting, VRP)
  ├── Market Structure Agent (range-bound vs trending, S/R mapping)
  ├── Risk Environment Agent (economic calendar, earnings, events)
  └── Execution Timing Agent (optimal entry/exit, liquidity analysis)
═══════════════════════════════════════════════════════════════
```

**Four coordination patterns:**

| Pattern | When used |
|---------|----------|
| **Independent** | A single specialist runs alone. Example: Iron Condor Specialist for a simple income account. |
| **Coordinated** | An orchestrator manages multiple specialists. Example: Portfolio Balance Orchestrator running condor + calendar + directional spreads simultaneously. |
| **Hierarchical** | Advanced layers can override specialist decisions. Example: Emergency Shutdown Agent overrides all specialists during a flash crash. |
| **Collaborative** | All layers share intelligence from Layer 1. Market regime updates flow simultaneously to all active agents. |

**User-facing:** An on/off panel for each agent suite. Users can activate only the layers and specialists appropriate for their account size, risk tolerance, and sophistication level:

```
☐ Market Intelligence       (always recommended — the foundation)
☐ Iron Condor Specialist    (range-bound markets)
☐ Calendar Spread Specialist (low vol environments)
☐ Straddle Specialist       (events / vol expansion plays)
☐ Bull/Bear Spread Specialist (trending markets)
☐ MEIC System               (institutional income)
☐ Portfolio Orchestrator    (multi-strategy coordination)
☐ Volatility Arbitrage      (advanced — full surface required)
☐ 0DTE System               (intraday — high skill required)
```

---

### Agent reusability matrix

Every agent is a reusable building block. The same Greeks Calculator runs inside the Iron Condor Specialist, the Calendar Specialist, and the MEIC Specialist — it is built once and shared:

| Agent | Iron Condor | Calendar | Straddle | Bull Spread | Bear Spread |
|-------|:-----------:|:--------:|:--------:|:-----------:|:-----------:|
| Market Regime | ✅ | ✅ | ✅ | ✅ | ✅ |
| Vol Surface | ✅ | ✅ | ✅ | ❌ | ❌ |
| Support/Resistance | ✅ | ❌ | ❌ | ✅ | ✅ |
| Momentum Detection | ❌ | ❌ | ❌ | ✅ | ✅ |
| Strike Selection | ✅ | ✅ | ✅ | ✅ | ✅ |
| Greeks Calculator | ✅ | ✅ | ✅ | ✅ | ✅ |
| Position Sizing | ✅ | ✅ | ✅ | ✅ | ✅ |
| Order Management | ✅ | ✅ | ✅ | ✅ | ✅ |
| Economic Calendar | ✅ | ✅ | ✅ | ✅ | ✅ |
| Performance Attribution | ✅ | ✅ | ✅ | ✅ | ✅ |

This means the development effort compounds — each new specialist reuses the shared agent library. Adding a new strategy does not require rebuilding the intelligence layer, just composing the right agents.

---

### Theta-to-Delta portfolio optimization — industry-first framework

One of the most novel concepts from the platform vision. Institutional portfolio managers balance income generation (theta) against directional exposure (delta) deliberately. No consumer options platform quantifies this relationship or helps optimize it.

**The ratio:** `Portfolio Theta / Absolute Portfolio Delta`

| Target ratio | Portfolio profile | When to use |
|-------------|-----------------|-------------|
| **5:1 to 10:1** | Income-focused | Maximum theta collection, minimal directional risk. Mostly iron condors, credit spreads, calendar spreads. |
| **2:1 to 5:1** | Balanced | Moderate income with controlled market exposure. Mix of income and directional strategies. |
| **1:1 to 2:1** | Growth-enhanced | Directional exposure with income enhancement. Heavier directional spreads. |

**Dynamic rebalancing:** The orchestrator continuously monitors the portfolio T/D ratio and makes strategy allocation decisions to keep it in the target range. If delta drifts from a trending move, add a higher-theta position to rebalance. If theta is compressed (options cheap), shift to directional strategies.

**Regime adjustments:**
- Low volatility: increase target ratio (maximize theta when premium is scarce)
- High volatility: decrease target ratio (reduce exposure during uncertain periods)
- Trending: lower ratio (capture directional moves while maintaining income)

This framework gives portfolio managers a single KPI that summarizes the risk-return balance across all active strategies — more intuitive than managing five individual Greeks.

---

### User progression model — Explorer to Institutional

Users move through competency tiers. Each tier unlocks more sophisticated agent layers, expanded strategy access, and more automation:

```
EXPLORER
  │  Single strategy, AI-guided, human approval required
  │  Strategy Buffet mode only
  │  Income-focused: iron condors, cash-secured puts, covered calls
  │
  ▼
TRADER  
  │  Multiple strategies, AI-coordinated
  │  Regime Router mode unlocked
  │  Full premium collection arsenal
  │
  ▼
PROFESSIONAL
  │  Multi-strategy portfolio orchestration
  │  Integrated Portfolio mode unlocked
  │  Advanced strategies: MEIC, calendar arbitrage, ratio spreads
  │  Team collaboration features
  │
  ▼
INSTITUTIONAL
     Multi-portfolio fund management
     Full LEGO system — all four layers active
     SMA / white-label capabilities
     Volatility arbitrage, gamma scalping, 0DTE systems
     Client reporting and compliance audit trails
```

**No platform graduation required.** A key failure of existing tools is that users outgrow them — they start on one platform, graduate to a more expensive institutional tool, losing their history and learning. DerivAgent is designed to scale from Explorer to Institutional on a single platform, retaining all trading history, all performance attribution, all learned parameters.

---

### Fund management and institutional architecture

DerivAgent scales to professional fund management operations — not as a future feature but as a core design principle:

**Multi-portfolio architecture:**
```
Fund / Firm dashboard
├── Conservative Income Portfolio ($2M allocation)
│   Iron condors, MEIC, calendar spreads only
├── Growth Strategy Portfolio ($5M allocation)
│   Directional spreads, covered calls, momentum-triggered
├── Market-Neutral Portfolio ($8M allocation)
│   Straddles, risk-reversals, vol arb, gamma scalping
├── Client SMA Templates
│   Per-client customized strategy profiles
└── Cross-portfolio coordination
    Unified risk management, consolidated reporting
```

**Team structure with role-based agent access:**

| Role | Agent access | Typical responsibility |
|------|-------------|----------------------|
| **Portfolio Manager** | Full orchestration + allocation | Strategy deployment decisions across portfolios |
| **Risk Manager** | Risk monitoring + Greeks dashboard | Continuous exposure monitoring, stop protocols |
| **Senior Trader** | Execution optimization | Position management, fill quality, order routing |
| **Research Analyst** | Performance attribution + learning | Strategy optimization, regime-performance analysis |

**Separately Managed Accounts (SMAs):**
- Create template strategies that can be customized per client risk profile
- Deploy identical intelligence across multiple client accounts with appropriate sizing
- Per-client attribution tracking while maintaining systematic consistency
- White-label interface for RIAs and regional broker-dealers

---

### Community learning with privacy preservation

As the user base grows, collective intelligence improves the system for everyone while preserving individual privacy:

- **Individual learning:** Each account's performance history improves its own agent parameters. An account that has traded iron condors for 200 sessions has precisely calibrated entry timing, stop levels, and profit targets for its specific risk profile.
- **Community patterns:** Successful patterns (anonymized) are surfaced across the user base. "Iron condor entries in the 65–80th IV rank percentile have historically outperformed 16-delta vs 18-delta shorts by 2.3% win rate across the user community."
- **Efficiency compounding:** Shared learning reduces the AI reasoning cost per trade decision over time. As the system learns which analyses lead to profitable outcomes, it routes faster — lower cost per user while improving accuracy.
- **Network effect:** Each user makes the platform more valuable for everyone. The more trading history the system accumulates, the better its regime detection, strategy selection, and parameter optimization.

This is the competitive moat that is impossible to replicate without years of live trading data. A new competitor starting from scratch cannot duplicate what the DerivAgent community has collectively learned.

---

### AI reasoning tiers — options trading requires mathematical precision

Standard AI models are insufficient for options trading. The challenge: options pricing, vol surface construction, and multi-leg strategy optimization require mathematical precision that general-purpose AI doesn't reliably deliver.

DerivAgent's AI architecture is tiered by the mathematical and speed requirements of each decision type:

| Tier | Decision type | Latency requirement | Mathematical requirement |
|------|--------------|--------------------|-----------------------|
| **Speed tier** | Real-time trading decisions, entry/exit signals | < 500ms | Moderate — regime confirmation, signal routing |
| **Cost tier** | High-volume processing, monitoring, screening | < 2s | Moderate — status checks, routine adjustments |
| **Reasoning tier** | Complex mathematical analysis, strategy optimization, vol surface modeling | < 5s acceptable | High — Greeks optimization, surface fitting, portfolio T/D optimization |

**Key principle:** Match the reasoning model to the decision complexity. Real-time execution uses fast, cost-efficient models. Complex portfolio optimization uses maximum mathematical precision, with latency tolerance because the decision is not time-critical second by second. This tiered approach delivers both speed where it matters and precision where it counts — while keeping costs viable.

**Emergency actions** always use cached, pre-computed decisions from Redis — no AI inference in the critical path. Risk circuit breakers are deterministic rules, not LLM calls.

---

### Operational procedures — market hours awareness

DerivAgent operates on a market-hours-aware cadence:

**Pre-market (8:30–9:30 AM ET):**
- System health verification: all broker connections live, data feeds flowing, Redis warm
- Portfolio Greeks review: delta, theta, vega across all active positions
- Catalyst check: read QualAgent's pre-event flags — any major events before close today?
- GEX update: pull latest gamma exposure map for the session
- Strategy review: any positions requiring early management (near DTE, near stop)?

**Market hours (9:30 AM–4:00 PM ET):**
- Continuous regime monitoring via Layer 1 agents
- Position lifecycle checks every 15 minutes (P&L vs targets, Greeks drift)
- Opportunity scanning per configured regime (is the current regime still the same as at open?)
- Event monitoring: QualAgent publishes any intraday catalyst flags
- Emergency halt: circuit breakers always active, accessible within 10 seconds

**After-hours (4:00 PM–close):**
- End-of-day reconciliation: all fills confirmed, positions matched to broker statements
- Performance attribution run: P&L broken down by strategy, time decay, vol change, delta
- Parameter update: learning agent proposes any regime-specific updates for review
- Next-session preparation: upcoming catalyst calendar, GEX reset, strategy queue for tomorrow

**Weekend maintenance:**
- Backtest runs for any new strategy proposals
- Learning agent weight updates (weekly cycle)
- Vol surface model recalibration with Friday close data

---

### Usage-based economic alignment

DerivAgent's pricing model should align platform revenue with user success — not flat subscription fees that extract value regardless of outcomes.

**The principle:** Users pay for AI intelligence consumed, not for access. Light users exploring strategies pay almost nothing. Successful traders building wealth pay proportionally to the value they receive.

**AI cost transparency:** Every analysis, every agent decision, every optimization run is tracked with an estimated cost and attributed to the outcome it drove. Users can see: "Your systematic approach generated $45K in realized gains this quarter. AI analysis for those decisions cost $180. Return on intelligence: 250x."

**Learning reduces costs:** As agents become more efficient — learning which analyses reliably predict profitable outcomes and which are redundant — the cost per decision decreases. A mature DerivAgent account costs less to operate per trade than a new one, because the system stops asking questions it already knows the answers to.

**Tier examples:**
- Explorer (learning, 1-2 strategies, small account): $20–75/month
- Trader (3-5 strategies, multiple strategies): $75–200/month
- Professional (full LEGO system, team features): $200–500/month
- Institutional / Fund Management: $1,000–5,000/month
- White-label / RIA: custom pricing

## Relationship to Existing Architecture

DerivAgent extends the existing architecture as the derivatives intelligence and execution layer:

- **Unified Data Bus compliance** — Services never call each other. DerivAgent publishes `deriv:*` events; consumers (IndicAgent, QualAgent, TradeAgent) subscribe. No coupling beyond the bus. See `docs/data/` for bus architecture.
- **DAG invariants preserved** — Options data flows one direction: chain → surface construction → regime signals → Kafka → consumers. No cycles. See `docs/concepts/dag-execution.md`.
- **APR-governed** — All thresholds, VRP filters, strategy parameters live in `config_state` under `deriv.*` namespace. See `docs/foundation/adaptive-parameter-registry.md`.
- **Shadow governance** — Every strategy enrolls in shadow. Promotion requires n ≥ 100 resolved signals and bootstrap CI > 0 at 95% confidence. See `docs/intelligence/intelligence-ai.md`.
- **Ring compliance** — Lives in Ring 2 as `services/deriv_agent.py`. See `docs/foundation/naming-system.md`.
- **Typed events via `stream_keys.py`** — All topic keys constructed centrally. See `src/core/stream_keys.py`.
- **Aegis integration** — All execution respects AegisAgent pre-trade checks and risk limits. See `docs/ideas/vision-01-aegisagent.md`.
- **Cross-product dependency** — GEX for ES futures computed from SPX/SPY options. Same for NQ vs NDX/QQQ. Deliberate architectural choice.

## Foundation Concepts Referenced

- **Principles** — `docs/foundation/principles.md`: Let the system run, earn through proof, segment relentlessly, data quality over model complexity, instrument everything
- **Naming System** — `docs/foundation/naming-system.md`: `DerivAgent` is a product name, not a code class; the Ring 2 daemon class/file is derived per the naming system when built
- **APR** — `docs/foundation/adaptive-parameter-registry.md`: Strategy parameters governed by APR
- **Documentation System** — `docs/foundation/documentation-system.md`: Idea docs live in `ideas/`, not authoritative until verified
- **Bus Architecture** — `docs/data/`: Unified event stream, typed events
- **DAG Execution** — `docs/concepts/dag-execution.md`: One-directional data flow, no cycles
- **Product Family** — See `docs/ideas/vision-04-qualagent.md` and `docs/ideas/vision-05-tradeagent.md` for peer products

---

## Open questions

1. **Data cost:** Real-time OPRA options chain data is expensive (~$1k+/month for professional feeds). 15-minute delayed CBOE data is free and may be sufficient for daily regime signals (GEX doesn't change significantly intraday for regime purposes). Which cadence is needed for which signals?

2. **Compute cost:** Constructing a full vol surface intraday from hundreds of strikes × multiple expiries is computationally intensive. Surface construction on open and close (twice daily) vs continuous intraday — what cadence is needed?

3. **Index options vs futures:** GEX for ES futures should be computed from SPX/SPY options, not ES options (ES options market is smaller). Same for NQ vs NDX/QQQ. This means DerivAgent ingests equity index options data even though IndicAgent trades futures — a deliberate cross-product dependency.

4. **VIX as a proxy:** For many purposes, VIX (the index, not futures) is a reasonable proxy for the vol regime without constructing a full surface. Phase 1 of DerivAgent might use VIX + VIX futures term structure alone, deferring full surface construction to Phase 2.

5. **Connection to QualAgent's options flow:** QualAgent ingests put/call ratios and net premium. DerivAgent ingests the full chain. There's a clean data handoff: CBOE aggregate daily stats go to QualAgent (sentiment layer); the full tick-by-tick chain goes to DerivAgent (structure layer). Same source, different processing pipelines.

6. **GEX data provider:** Computing GEX from scratch requires the full options chain. Alternatively, services like SqueezeMetrics (GEX), SpotGamma, and Market Chameleon publish GEX data directly. Phase 1 might use a GEX data provider; Phase 2 builds the computation in-house.

---

## References

- `docs/ideas/vision-04-qualagent.md` — boundary definition, product family integration, feedback loop
- `docs/ideas/vision-05-tradeagent.md` — primary consumer of DerivAgent outputs
- `docs/ideas/renaissance-01-simons-principles.md` — state-based (8), kernel methods, alternative data (9)
- [SqueezeMetrics GEX](https://squeezemetrics.com/monitor/dix) — GEX reference and data
- [SpotGamma](https://spotgamma.com/) — GEX, CHARM, VANNA flow data provider
- [Market Chameleon](https://marketchameleon.com/) — options flow, vol surface, skew data
- [VIX Central](https://vixcentral.com/) — VIX term structure monitoring
- [CBOE Data Shop](https://datashop.cboe.com/) — official options chain data
- [OPRA](https://www.opradata.com/) — Options Price Reporting Authority (full chain)
- Breeden-Litzenberger (1978) — risk-neutral probability density extraction from options prices
- [SVI parameterization](https://arxiv.org/abs/1204.0646) — Gatheral's stochastic vol inspired vol surface fit
- [Options as insurance: VRP persistence](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2543709) — academic evidence for VRP
