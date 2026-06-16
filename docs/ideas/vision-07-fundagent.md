# FundAgent

**Status:** Idea
**Created:** 2025-06-16
**Context:** Fundamental analysis — earnings, macro, company fundamentals

## Core Concept

Price action tells you what the market is doing. Fundamentals tell you *why*. FundAgent consumes fundamental data — earnings, macroeconomic indicators, company financials, sector rotations — and publishes events that provide context for quantitative signals.

FundAgent is a standalone domain — parallel to Quantitative (price-based math), Flow (positioning), and Qualitative (sentiment/narrative).

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

- **Bus-compatible**: Each source publishes typed events; consumers subscribe
- **APR-governed**: Thresholds, weights, decay parameters live in APR
- **Shadow governance**: Starts in shadow; promotion requires statistical proof
- **VIL-ready**: Fundamental state embeds for historical analog retrieval
- **Regime-aware**: Macro data primarily informs I4 regime classification

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
