# FlowAgent

**Status:** draft
**Version:** 0.1
**Created:** 2026-06-16
**Last Updated:** 2026-06-17
**Context:** Cross-asset positioning intelligence — where real money is committed
**Priority:** low
**Milestone:** future (post-v2.8)
**Tags:** flowagent, positioning, cot, order-flow, dark-pools, gex, platform, vision

## Core Concept

Price-derived zones (I3 market structure) are historical patterns. Flow measures are *where real money must act*. FlowAgent consumes cross-sectional positioning data and publishes augment events that strengthen or weaken structural zones based on obligate order flow.

FlowAgent is a standalone domain — parallel to Quantitative (I1-I8), Fundamental (earnings/macro), and Qualitative (sentiment/narrative). It applies across all asset classes: equities, futures, options, FX, crypto.

### Renaissance Frame

FlowAgent embodies Renaissance principles:

- **Instrument everything:** Every positioning event is captured — COT snapshots, dark pool prints, options sweeps. No data is dropped. If money moved, it's measurable.
- **Let the system run:** Flow signals are not manual overrides. They're event-driven context that the quantitative pipeline consumes automatically.
- **Earn the right through proof:** Every flow source starts in shadow mode. Promotion to production requires statistical proof (p < 0.05, n ≥ 100). No flow source acts on live signals without demonstrated edge.
- **Segment relentlessly:** Flow signals are regime-aware. COT extremes matter in trending regimes; dark pool prints matter differently in high-volatility regimes. Every hypothesis is conditioned on regime context.

### Architectural Positioning

FlowAgent fits the shared spine architecture:

- **Ring 2 daemon** — Would live under `services/` when implemented; class and file names derive from the naming system at build time (the `_agent` suffix is retired)
- **Event publisher** — Publishes to `flow:*` topics via `stream_keys.py`
- **Bus consumer** — No direct calls to/from other services
- **DAG-compliant** — Data flows one direction: external source → flow analysis → Kafka → consumers
- **APR-governed** — All thresholds, weights, and decay parameters live in `config_state`, not code
- **Shadow-governed** — Every flow source enrolls in shadow on startup; promotion requires bootstrap CI > 0

## Flow Data Sources

| Source | What it measures | Frequency | Access | Signal Type | Asset Class |
|--------|-----------------|-----------|--------|-------------|-------------|
| **COT** | Positioning of commercials vs speculators | Weekly (Fridays 3:30pm ET) | CFTC public | Regime/crowding filter | Futures, FX |
| **Dealer Gamma** | Options dealer hedging obligation | Intraday | Options analytics | Structural support/resistance | Options |
| **Options Flow** | Unusual activity, large sweeps, blocks | Intraday | Options analytics | Institutional intent | Options |
| **Dark Pool Prints** | Off-exchange institutional executions | Intraday | Exchange data | Hidden order flow | Equities, ETFs |
| **Short Interest** | Real-time short positioning, squeeze risk | Daily | Securities lending | Contrarian/flow risk | Equities |
| **Order Book Imbalance** | Bid/ask pressure at key levels | Sub-second | Exchange feeds | Microstructure pressure | All liquid |
| **ETF Creation/Redemption** | Institutional ETF unit flows | Daily | ETF providers | Sentiment/flow direction | ETFs |
| **Insider Trading** | Form 4 filings, insider positions | Lagged (days) | SEC | Corporate intent | Equities |
| **Delivery Notices** | Commercial standing vs speculative rolls | Daily | Exchange reports | Physical value signal | Futures (commodities) |
| **Warehouse Stocks** | Physical supply/demand for commodities | Daily | LME, COMEX | Supply constraints | Metals |

**The thesis:** Zones confirmed by flow data have higher probability of holding. Zones contradicted by flow may be false structures or about to break.

## Architecture: Parallel Sources, Not Sequential Tiers

FlowAgent differs from IntelligencePipeline (I1-I8) in structure:

```
IntelligencePipeline (Sequential Tiers):
I1 → I2 → I3 → I4 → I5 → SMC → I6 → I7 → I8

FlowAgent (Parallel Sources):
┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐
│   COT   │  │   GEX   │  │Options  │  │ Short   │
│         │  │         │  │  Flow   │  │Interest │
└────┬────┘  └────┬────┘  └────┬────┘  └────┬────┘
     │            │            │            │
     └────────────┴────────────┴────────────┘
                    │
            Flow Confluence
                    │
          flow:confidence event
                    │
              Augments I6/I7
```

Each flow source is independent. No sequence. Just parallel witnesses to where real money is positioned.

## Integration with Quantitative Pipeline

### Data Flow

```
COT snapshot          → flow:cot_positioning       (weekly)
Options flow          → flow:options_uoa           (intraday)
GEX flip updates      → flow:gex_flip              (intraday)
Dark pool prints      → flow:darkpool_print        (intraday)
Short interest        → flow:short_interest        (daily)
Delivery notices      → flow:delivery_notices      (daily)
                           ↓
                      FlowAgent
                           ↓
                 flow:confidence event
                           ↓
                   I6 Confluence / I7 Setups
```

### Integration Points

**Option A: New CIS bucket**
- Add "Flow" as 7th evidence bucket alongside Trend, Momentum, Structure, Pattern, Institutional, Regime
- Weight: 0.10-0.15 (flow is obligate, not discretionary)

**Option B: I6 confluence input**
- Existing buckets consume flow events as contextual adjustment
- Structural zones boosted/lowered based on flow alignment

**Option C: Separate composite score**
- `FlowConfidenceScore` computed independently
- Combined with CIS at signal selection time

## Hypotheses

**Structural Confluence (COT, GEX, Dark Pools, Delivery)**
1. GEX flip zones overlapping SMC support/resistance — Higher probability of holding; dealer hedging creates actual order flow at the level
2. Extreme COT positioning — When commercials and large speculators are at historical extremes, the trade is crowded; regime filter or signal suppression
3. Dark pool prints at key levels — Large off-exchange executions at SMC zones confirm institutional agreement; price may penetrate displayed liquidity but respect hidden levels
4. Commercial standing for delivery — Physical commodities: commercials taking delivery at a price level = real value signal

**Options Flow Intelligence**
5. Unusual options activity (UOA) — Sweeps, block trades, volume > 2x OI — institutional positioning often precedes price movement; lead indicator for direction
6. Put/call skew extremes — Extreme skew can signal regime turning points (excessive bearishness = bounce setup, excessive bullishness = risk)
7. IV percentile vs HV — Options-implied volatility diverging from realized can signal regime transition or mean-reversion setup

**Short Interest / Securities Lending**
8. High short interest + price strength = squeeze risk — Signal suppression or target extension when shorts are underwater
9. Short interest changes rapidly — Increasing SI at new highs shows conviction; decreasing SI at lows shows covering (potential bottom)
10. Securities lending rates — Spiking borrowing costs can signal short squeeze imminent or institutional conviction

**Microstructure Pressure (OBI, Order Flow)**
11. Order book imbalance at key levels — Bid volume > ask volume at support = absorbing zone likely to hold; reverse for resistance
12. Large orders sweeping the book — Aggressive buyers/sellers consuming multiple levels = directional conviction
13. Iceberg / hidden order detection — Large visible orders hiding true size; breakout when exhausted

**ETF Flows**
14. Creation unit activity — Net creation = institutional bullishness; net redemption = bearishness or rotation
15. ETF premium/discount to NAV — Extreme premiums signal euphoria; discounts signal fear; contrarian regime filter
16. Sector rotation via ETF flows — Capital moving between sector ETFs shows institutional preference shift

**Insider Activity**
17. Cluster insider buying — Multiple insiders buying within short window = high conviction signal (insiders know best)
18. Insider selling — Less predictive (diversification), but extreme selling at highs can signal regime top

**Multi-Source Confluence**
19. Flow consensus across sources — COT + GEX + Options flow + Dark pools all aligned = highest conviction structural level
20. Flow divergence as reversal signal — Price making highs but flow data (shorts, options, ETFs) showing bearish positioning = potential regime top

## Implementation Phases

### Phase 1: Free Public Data (Immediate)

1. **COT Data**
   - Parse CFTC weekly reports
   - Compute positioning extremes (z-scores by percentile)
   - Publish `flow:cot_positioning` event
   - Integrate as regime filter in I4 or I6

2. **Short Interest**
   - Public short interest data (exchange reporting)
   - Compute SI % float, changes
   - Publish `flow:short_interest` event
   - Suppress signals in high-SI squeeze zones

3. **Insider Trading**
   - Parse SEC Form 4 filings
   - Detect cluster buying patterns
   - Publish `flow:insider_activity` event
   - Use as confluence boost in I6

4. **Futures Delivery Notices**
   - Parse CME daily delivery reports
   - Detect commercial standing vs. speculative rolls
   - Publish `flow:delivery_notices` event
   - Physical value signal for commodities

### Phase 2: Options Analytics (Paid Access)

5. **Options Flow / UOA**
   - Integrate with options analytics provider
   - Detect sweeps, blocks, unusual volume
   - Publish `flow:options_uoa` event
   - Lead indicator for directional bias

6. **Dealer Gamma**
   - GEX flip zones, total gamma exposure
   - Publish `flow:gex_flip` event
   - Augment SMC zones with obligate flow levels

7. **IV/HV Skew**
   - Implied vs realized volatility divergence
   - Publish `flow:vol_regime` event
   - Regime filter for mean-reversion vs trend

### Phase 3: Microstructure (Real-Time)

8. **Order Book Imbalance**
   - Consume exchange order book feeds
   - Compute OBI at key levels
   - Publish `flow:obi_pressure` event
   - Real-time confirmation/rejection of zones

9. **Dark Pool Prints**
   - Trade reporting feeds (TRF, FINRA)
   - Detect large off-exchange executions
   - Publish `flow:darkpool_print` event
   - Hidden order flow at structural levels

### Phase 4: Enhanced Futures Data

10. **Warehouse Stocks**
    - LME, COMEX warehouse reports
    - Physical supply/demand for metals
    - Publish `flow:warehouse_stocks` event

11. **ETF Creation/Redemption**
    - Daily ETF unit flows
    - Capital rotation detection
    - Publish `flow:etf_flows` event

## Data Access & Costs

| Tier | Sources | Cost | Access Path |
|------|---------|------|-------------|
| **Free** | COT, Public SI, Form 4, Delivery notices, Warehouse stocks | $0 | Public APIs, exchange reports |
| **Low** | Options flow basics | ~$100-300/m | Unusual Whales, InsiderFinance |
| **Medium** | GEX, IV analytics | ~$300-500/m | Cboe, options providers |
| **High** | OBI feeds, Dark pools | ~$1000+/m | Exchange data, proprietary |
| **Institutional** | Prime brokerage, ETF flows | $$$ | Industry relationships |

### Temporal Alignment

- **Weekly**: COT (lagged but authoritative)
- **Daily**: Short interest, ETF flows, insider filings, delivery notices, warehouse stocks
- **Intraday**: Options flow, GEX, dark pools
- **Sub-second**: Order book imbalance

Strategy: Start with weekly/daily (cheap, immediate), validate hypotheses, then invest in higher-frequency data.

## Validation & Governance

For each flow source:
1. **Shadow mode first** — Consume and publish, but don't act on signals
2. **Correlation analysis** — Does flow at a level correlate with zone holds/breaks?
3. **Counterfactual tracking** — Signals that would have fired with flow vs without
4. **Promotion gate** — Bootstrap CI > 0 at 95% confidence, n ≥ 100
5. **Demotion** — EV[R] < -0.05 for 3 consecutive cycles

## Relationship to Existing Architecture

FlowAgent extends the existing architecture without violating invariants:

- **Unified Data Bus compliance** — Services never call each other. FlowAgent publishes `flow:*` events; consumers subscribe. No coupling beyond the bus. See `docs/data/` for bus architecture.
- **DAG invariants preserved** — Flow data flows one direction: source → analysis → Kafka → consumers. No cycles. No service touches the database except Writers/Trackers. See `docs/concepts/dag-execution.md`.
- **APR-governed** — All flow thresholds, weights, and decay parameters live in `config_state` under `flow.*` namespace. No hardcoded values. See `docs/foundation/adaptive-parameter-registry.md`.
- **Shadow governance** — Every flow source enrolls in shadow on startup. Promotion requires n ≥ 100 resolved signals and bootstrap CI > 0 at 95% confidence. See `docs/intelligence/intelligence-ai.md`.
- **VIL-ready** — Flow state embeds alongside bar state for historical analog retrieval via Vector Intelligence Layer. See `docs/ideas/vil-01-vector-intelligence-layer.md`.
- **Ring compliance** — Would live in Ring 2 as `services/flow_agent.py`. See `docs/foundation/naming-system.md`.
- **Typed events via `stream_keys.py`** — All topic keys constructed centrally. No hardcoded strings. See `src/core/stream_keys.py`.

## Foundation Concepts Referenced

- **Principles** — `docs/foundation/principles.md`: Instrument everything, earn through proof, segment relentlessly
- **Naming System** — `docs/foundation/naming-system.md`: `FlowAgent` is a product name, not a code class; the Ring 2 daemon class/file is derived per the naming system when built
- **APR** — `docs/foundation/adaptive-parameter-registry.md`: Parameter lifecycle, governance
- **Documentation System** — `docs/foundation/documentation-system.md`: Idea docs live in `ideas/`, not authoritative until verified

## References

### COT & Positioning
- [CFTC COT reports](https://www.cftc.gov/MarketReports/CommitmentsofTraders/index.htm)
- [CFTC Disaggregated COT](https://www.cftc.gov/dea/futures/deacmesf.htm)

### Options Flow
- [InsiderFinance Options Flow](https://www.insiderfinance.io/flow)
- [Unusual Whales](https://unusualwhales.com/)
- [Barchart Unusual Activity](https://www.barchart.com/options/unusual-activity)
- [Nasdaq: Understanding Unusual Options Activity](https://www.nasdaq.com/articles/understanding-unusual-options-activity)

### Short Interest & Securities Lending
- [DataLend: Securities Lending and Market Sentiment](https://datalend.com/short-meets-long-when-securities-lending-data-illuminates-market-sentiment/)
- [S&P Short Interest Data](https://www.marketplace.spglobal.com/en/datasets/securities-finance-short-interest-data-(1704372663))
- [NeuData: Short Interest Guide](https://www.neudata.co/blog/understanding-short-interest-and-securities-lending-data-a-guide-for-investors)
- [IBKR Securities Lending Dashboard](https://www.interactivebrokers.com.hk/en/trading/securities-lending-dashboard.php)

### Order Book Microstructure
- [QuestDB: Order Book Imbalance](https://questdb.com/glossary/order-book-imbalance/)
- [HftBacktest: Order Book Imbalance Tutorial](https://hftbacktest.readthedocs.io/en/latest/tutorials/Market%2520Making%2520with%2520Alpha%2520-%2520Order%2520Book%2520Imbalance.html)
- [Market Microstructure: Order Books & Execution Mechanics](https://mbrenndoerfer.com/writing/market-microstructure-order-book-mechanics)
- [Emergent Mind: Order Flow Imbalance](https://www.emergentmind.com/topics/order-flow-imbalance)

### Futures Delivery & Warehouse
- [CME Delivery Notices & Stocks](https://www.cmegroup.com/solutions/clearing/operations-and-deliveries/nymex-delivery-notices.html)
- [CME Volume & Open Interest](https://www.cmegroup.com/market-data/volume-open-interest.html)
- [LME Warehouse & Stock Reports](https://www.lme.com/market-data/reports-and-data/warehouse-and-stocks-reports)
- [MetalCharts: COMEX Inventory](https://metalcharts.org/comex)

### ETF Flows
- [State Street: ETF Creation and Redemption](https://www.ssga.com/us/en/intermediary/resources/education/how-etfs-are-created-and-redeemed)
