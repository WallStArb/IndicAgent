# FundAgent

**Status:** draft
**Version:** 0.1
**Created:** 2026-06-16
**Last Updated:** 2026-06-17
**Context:** Fundamental analysis — earnings, macro, company fundamentals
**Priority:** low
**Milestone:** future (post-v2.8)
**Tags:** fundagent, fundamentals, earnings, macro, regime, platform, vision

## Core Concept

Price action tells you what the market is doing. Fundamentals tell you *why*. FundAgent consumes fundamental data — earnings, macroeconomic indicators, company financials, sector rotations — and publishes events that provide context for quantitative signals.

FundAgent is a standalone domain — parallel to Quantitative (I1-I8), Flow (positioning), and Qualitative (sentiment/narrative).

### Renaissance Frame

FundAgent embodies Renaissance principles:

- **Instrument everything:** Every fundamental event is captured — earnings releases, macro data, Fed decisions. No fundamental signal is dropped.
- **Let the system run:** Fundamental context is not a manual overlay. It's event-driven regime input that the pipeline consumes automatically.
- **Earn the right through proof:** Every fundamental source starts in shadow mode. Promotion requires statistical proof that fundamental-augmented signals outperform pure price signals (p < 0.05, n ≥ 100).
- **Segment relentlessly:** Fundamental signals are regime-aware. Yield curve inversion matters differently in expansion vs. recession regimes. Earnings surprises are filtered by volatility regime.

### Architectural Positioning

FundAgent fits the shared spine architecture:

- **Ring 2 daemon** — Would live under `services/` when implemented; class and file names derive from the naming system at build time (the `_agent` suffix is retired)
- **Event publisher** — Publishes to `fundamental:*` topics via `stream_keys.py`
- **Bus consumer** — No direct calls to/from other services
- **DAG-compliant** — Data flows one direction: external source → fundamental analysis → Kafka → consumers
- **APR-governed** — All thresholds, weights, and regime parameters live in `config_state`, not code
- **Shadow-governed** — Every fundamental source enrolls in shadow; promotion requires bootstrap CI > 0

## Fundamental Data Sources

| Source | What it measures | Frequency | Access | Signal Type |
|--------|-----------------|-----------|--------|-------------|
| **Earnings** | Company earnings, guidance, surprises | Quarterly | Public | Equity-specific |
| **Macroeconomic** | GDP, inflation, employment, rates | Monthly/Daily | Public | Regime context |
| **Sector Rotation** | Capital flow between sectors | Daily | Price/ETF data | Regime shifts |
| **Valuation Metrics** | P/E, P/B, multiples vs. history | Daily/Quarterly | Public | Value signals |
| **Corporate Actions** | Buybacks, dividends, M&A | Ad-hoc | Public | Corporate intent |
| **Economic Surprise** | Data vs. expectations | Daily | Public | Regime surprise |
| **Interest Rates** | Fed policy, yield curve | Daily | Public | Regime driver |
| **Commodity Supply** | Production, inventories, demand | Monthly | Public | Supply/demand |
| **Cross-Asset Spreads** | Yield curves, basis, term structures | Daily | Market data | Regime signals |

## Architecture: Event-Publishing Sources

Like FlowAgent, FundAgent has parallel sources that publish independent events:

```
┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐
│ Earnings │  │  Macro   │  │  Sector  │  │   Fed    │
│          │  │          │  │ Rotation │  │  Policy  │
└────┬─────┘  └────┬─────┘  └────┬─────┘  └────┬─────┘
     │             │             │             │
     └─────────────┴─────────────┴─────────────┘
                         │
                  FundAgent
                         │
              fundamental:context event
                         │
                   Augments I4/I6
```

## Integration with Quantitative Pipeline

### Data Flow

```
Earnings release         → fundamental:earnings_surprise     (ad-hoc)
Macro data release       → fundamental:macro_data            (daily)
Fed policy decision      → fundamental:fed_policy            (ad-hoc)
Sector rotation signal   → fundamental:sector_rotation       (daily)
Yield curve change       → fundamental:yield_curve           (daily)
                             ↓
                          FundAgent
                             ↓
                fundamental:regime_context event
                             ↓
                      I4 Regime / I6 Confluence
```

### Integration Points

**Option A: I4 Regime Input**
- Macro data feeds regime classification (HMM, BOCPD)
- Economic surprises trigger regime reassessment
- Yield curve slope informs recession/expansion regime

**Option B: I6 Confluence Context**
- Earnings surprises boost/suppress individual equity signals
- Sector rotation weights confluence buckets
- Valuation extremes as regime filter

**Option C: CIS Bucket**
- Add "Fundamental" as evidence bucket
- Weight lower than price-based signals (0.05-0.10)
- Useful for longer-term regime context

## Hypotheses

**Earnings & Corporate Fundamentals**
1. Earnings surprise + price momentum = continuation — Positive surprise with strong price trend = higher conviction
2. Earnings miss + structural support = reversal setup — Bad earnings at key support can be bullish (everyone in)
3. Guidance changes > earnings beat/miss — Forward-looking matters more than backward-looking
4. Buyback announcements = floor at current price — Corporate buying creates support

**Macroeconomic Regime**
5. Yield curve inversion = recession regime — Flatten/inversion signals regime shift to defensive positioning
6. Fed policy surprise = regime transition — Unexpected policy changes trigger regime reassessment
7. Economic data surprise = short-term regime bias — Data beating/missing expectations creates directional bias
8. Volatility regime (VIX term structure) = risk-on/off — VIX contango = normal, backwardation = panic regime

**Sector Rotation & Cross-Asset**
9. Capital flowing into defensive sectors = risk-off — Rotation into utilities, staples, bonds suggests regime change
10. Sector relative strength = regime proxy — Leading sectors indicate current regime theme
11. Commodity supercycles = multi-year regime — Structural supply/demand changes create long-term regimes
12. Cross-asset basis divergences = regime transition — Futures curves, ETF premiums/discounts signaling regime shift

**Valuation & Mean Reversion**
13. Extreme valuation multiples = regime filter — P/E at historical extremes signals regime vulnerability
14. Value factor regime = mean reversion — High value stocks outperform in certain regimes
15. Quality factor regime = momentum — High quality stocks outperform in expansion regimes

## Implementation Phases

### Phase 1: Public Macro Data (Immediate)

1. **Yield Curve**
   - Treasury curve data (2y, 5y, 10y, 30y)
   - Compute slope, inversion signals
   - Publish `fundamental:yield_curve` event
   - Regime context for I4

2. **Fed Policy**
   - FOMC decisions, minutes, dot plot
   - Policy surprise detection
   - Publish `fundamental:fed_policy` event
   - Regime transition trigger

3. **Key Economic Data**
   - CPI, PPI, employment, GDP, retail sales
   - Surprise vs. expectations
   - Publish `fundamental:macro_surprise` event
   - Regime bias adjustment

### Phase 2: Earnings & Corporate Actions

4. **Earnings Data**
   - Parse earnings releases, estimates
   - Compute surprise (actual vs. expected)
   - Publish `fundamental:earnings_surprise` event
   - Equity-specific signal adjustment

5. **Corporate Actions**
   - Buybacks, dividends, M&A announcements
   - Publish `fundamental:corporate_action` event
   - Support/resistance context

### Phase 3: Sector & Cross-Asset

6. **Sector Rotation**
   - Relative strength by sector
   - Capital flow detection
   - Publish `fundamental:sector_rotation` event
   - Regime proxy

7. **Cross-Asset Spreads**
   - Futures basis, calendar spreads
   - ETF premiums/discounts
   - Publish `fundamental:cross_asset_spread` event
   - Regime transition signal

### Phase 4: Valuation & Quality

8. **Valuation Metrics**
   - P/E, P/B, EV/EBITDA by sector
   - Historical percentile ranks
   - Publish `fundamental:valuation` event
   - Regime filter for extreme valuations

## Data Access & Costs

| Tier | Sources | Cost | Access Path |
|------|---------|------|-------------|
| **Free** | Treasury yields, Fed data, economic releases | $0 | FRED, Fed websites, Treasury |
| **Low** | Earnings estimates, surprise data | ~$50-150/m | Estimize, Refinitiv (basic) |
| **Medium** | Sector rotation, cross-asset analytics | ~$200-400/m | Bloomberg, Refinitiv |
| **High** | Full valuation data, global macro | ~$1000+/m | Professional terminals |

### Temporal Alignment

- **Real-time**: Treasury yields, Fed announcements
- **Daily**: Economic releases, sector rotation, cross-asset spreads
- **Weekly**: Summarized macro context
- **Quarterly**: Earnings season (bulk)

Strategy: Start with free macro data (treasury yields, Fed policy), validate regime signals, then expand to earnings and sector rotation.

## Validation & Governance

For each fundamental source:
1. **Shadow mode first** — Publish events without acting on them
2. **Regime correlation** — Does fundamental signal correlate with regime transitions?
3. **Signal enhancement** — Do fundamental-augmented signals outperform pure price signals?
4. **Promotion gate** — Bootstrap CI > 0 at 95% confidence, n ≥ 100
5. **Demotion** — EV[R] < -0.05 for 3 consecutive cycles

## Relationship to Existing Architecture

FundAgent extends the existing architecture without violating invariants:

- **Unified Data Bus compliance** — Services never call each other. FundAgent publishes `fundamental:*` events; consumers subscribe. No coupling beyond the bus. See `docs/data/` for bus architecture.
- **DAG invariants preserved** — Fundamental data flows one direction: source → analysis → Kafka → consumers. No cycles. No service touches the database except Writers/Trackers. See `docs/concepts/dag-execution.md`.
- **APR-governed** — All fundamental thresholds, weights, and regime parameters live in `config_state` under `fundamental.*` namespace. No hardcoded values. See `docs/foundation/adaptive-parameter-registry.md`.
- **Shadow governance** — Every fundamental source enrolls in shadow. Promotion requires n ≥ 100 resolved signals and bootstrap CI > 0 at 95% confidence. See `docs/intelligence/intelligence-ai.md`.
- **VIL-ready** — Fundamental state embeds alongside bar state for historical analog retrieval. See `docs/ideas/vil-01-vector-intelligence-layer.md`.
- **Ring compliance** — Would live in Ring 2 as `services/fund_agent.py`. See `docs/foundation/naming-system.md`.
- **Typed events via `stream_keys.py`** — All topic keys constructed centrally. No hardcoded strings. See `src/core/stream_keys.py`.
- **I4 regime integration** — Macro data primarily informs regime classification (HMM, BOCPD, Kalman). See `docs/intelligence/intelligence-foundation.md`.

## Foundation Concepts Referenced

- **Principles** — `docs/foundation/principles.md`: Instrument everything, earn through proof, segment relentlessly
- **Naming System** — `docs/foundation/naming-system.md`: `FundAgent` is a product name, not a code class; the Ring 2 daemon class/file is derived per the naming system when built
- **APR** — `docs/foundation/adaptive-parameter-registry.md`: Parameter lifecycle, governance
- **Documentation System** — `docs/foundation/documentation-system.md`: Idea docs live in `ideas/`, not authoritative until verified
- **Intelligence Architecture** — `docs/intelligence/intelligence-foundation.md`: I4 regime classification, I6 confluence

## References

### Macro & Fed Data
- [FRED Economic Data](https://fred.stlouisfed.org/) — Treasury yields, economic releases
- [Federal Reserve Board](https://www.federalreserve.gov/) — Monetary policy, FOMC decisions
- [Bureau of Labor Statistics](https://www.bls.gov/) — Employment, inflation data
- [BEA GDP Data](https://www.bea.gov/) — GDP, personal income

### Earnings Data
- [Estimize](https://estimize.com/) — Crowdsourced earnings estimates
- [Zacks Earnings Surprise](https://www.zacks.com/) — Earnings data, surprise estimates
- [YCharts Earnings Calendar](https://ycharts.com/) — Earnings releases, historical data

### Sector & Cross-Asset
- [FRED Sector Data](https://fred.stlouisfed.org/categories/) — Sector-level economic data
- [S&P Sector Performance](https://www.spglobal.com/) — Sector relative strength
- [State Street ETF Flows](https://www.ssga.com/) — Sector ETF creation/redemption

### Yield Curve & Rates
- [Treasury.gov Yield Curve](https://www.treasury.gov/) — Official treasury yields
- [FRED Yield Curve](https://fred.stlouisfed.org/categories/32291) — Historical yield curve data

### Valuation
- [Multpl.com](https://www.multpl.com/) — Historical valuation multiples
- [Damodaran Online](https://pages.stern.nyu.edu/~adamodar/) — Valuation data, models
