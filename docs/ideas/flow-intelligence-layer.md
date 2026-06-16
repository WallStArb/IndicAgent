# Flow Intelligence Layer

**Status:** Idea
**Created:** 2025-06-16
**Context:** Derivatives domain enhancement to quantitative intelligence

## Core Concept

Price-derived SMC zones are historical patterns. Flow measures are *where real money must act*. A Flow Intelligence Layer would consume cross-sectional derivatives data and publish augment events that strengthen or weaken structural zones based on obligate order flow.

Three data sources form the foundation:

| Source | What it measures | Frequency | Access |
|--------|-----------------|-----------|--------|
| **COT** | Positioning of commercials vs speculators | Weekly (Fridays 3:30pm ET) | CFTC public |
| **Prime Brokerage** | Actual fund positions, flows | Proprietary | Dealer access |
| **Dealer Gamma** | Options dealer hedging obligation | Intraday | Options analytics |

**The thesis:** Zones confirmed by flow data have higher probability of holding. Zones contradicted by flow may be false structures or about to break.

## Integration Architecture

### Data Flow

```
COT snapshot          → deriv:cot_positioning   (weekly)
PB position changes   → deriv:pb_positions      (daily/intraday)
GEX flip updates      → deriv:gex_flip          (intraday)
                           ↓
                   Flow Intelligence Layer
                           ↓
              flow:structural_augment (zone confidence adjustment)
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

### Hypotheses

1. **GEX flip zones overlapping SMC support/resistance** — Higher probability of holding; dealer hedging creates actual order flow at the level

2. **Extreme COT positioning** — When commercials and large speculators are at historical extremes, the trade is crowded; regime filter or signal suppression

3. **PB data divergence from price** — If funds are positioning opposite to price structure, potential regime transition or false breakout

4. **Confluence of multiple flow sources** — GEX + COT + PB all agreeing on a zone = highest conviction structural level

## Open Questions

### Data Access

- **COT**: Free, public, weekly. Lagged but authoritative.
- **GEX**: Options analytics providers (SPY, stocks). Cost? API access?
- **PB**: Proprietary. Do we have access? If not, can we proxy with 13F/Futures position data?

### Temporal Alignment

- COT is weekly; GEX is intraday. How to join?
- Does a weekly COT signal have value for intraday setups?
- Should flow be a regime filter (binary) or continuous score?

### Validation

- How to measure if flow-augmented zones outperform pure SMC zones?
- Counterfactual tracking: signals that would have fired with flow but were suppressed without it

### Scope

- Start with COT only (free, immediate access)?
- Or go straight for GEX (more actionable, intraday)?
- PB data as stretch goal if access emerges

## Relationship to Existing Architecture

- **Fits Derivatives domain**: Already designed, just needs implementation
- **Bus-compatible**: Each data source publishes typed events; consumers subscribe
- **APR-governed**: Thresholds, weights, decay parameters live in APR
- **Shadow governance**: Flow augment starts in shadow; promotion requires statistical proof
- **VIL-ready**: Flow state embeds alongside bar state for historical analog retrieval

## Next Steps

1. **Research phase**: COT data structure, API options for GEX, PB access exploration
2. **Prototype**: COT consumer → weekly `deriv:cot_positioning` event → simple regime filter
3. **Measure**: Does COT-regime-filtered signals outperform unfiltered?
4. **Expand**: Add GEX once COT validates the approach
5. **Integrate**: Flow bucket in CIS or I6 confluence input

## References

- CFTC COT reports: https://www.cftc.gov/MarketReports/CommitmentsofTraders/index.htm
- GEX concept: Dealer gamma exposure, flip zones, options hedging flows
- Prime brokerage: Fund positioning data (proprietary)
