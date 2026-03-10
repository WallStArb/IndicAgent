# I6 Confluence Expansion — Cross-Timeframe + Cross-Asset Intelligence

**Version:** 1.0.0
**Last Updated:** 2026-03-08
**Status:** Research & Design — ready for planning
**Related:** `renaissance-i7-i8-refinement.md`, `regime-adaptive-trading.md`, `intelligence-redo-brainstorm.md`

---

## Context

I6 (Confluence) currently has one plugin: `CrossTimeframeConfluencePlugin`. It answers a single question:

> **"Do higher timeframes confirm this signal?"**

This is powerful but incomplete. Renaissance principles demand segmentation across multiple orthogonal dimensions:

1. **Time-scale confluence** — Do 5m/15m/1h agree?
2. **Asset-class confluence** — Do ES/NQ/RTY agree? What does VIX say?
3. **Correlation regime** — Are correlated assets diverging? Is it stress or calm?
4. **Sector flow** — Is tech leading? Are utilities/energy lagging?

A multi-dimensional confluence system scores signals based on **orthogonal confirmation sources**, not just timeframe alignment.

---

## Current I6 Implementation

### `CrossTimeframeConfluencePlugin` — What It Does

| Component | Weight | Description |
|-----------|--------|-------------|
| Trend Alignment | 0.4 | Direction agreement across TFs (trend_direction, trend_strength) |
| Structure Alignment | 0.3 | Swing pattern agreement (swing_pattern) |
| Regime Agreement | 0.2 | Vol/momentum regime consistency (hmm_regime, vol_expansion) |
| Pattern Confirmation | 0.1 | Higher-TF pattern validation (RSI divergence, BOS confirmation) |
| I2 Events | 0.1 | MACD/RSI/Stoch/ADX event confluence |

**Current Outputs:**
- `ctf_score`: [-1, +1] normalized composite
- `ctf_trend_alignment`: [-1, +1] trend agreement
- `ctf_structure_alignment`: [-1, +1] pattern agreement
- `ctf_regime_agreement`: [0, +1] regime consistency
- `ctf_timeframes_aligned`: count of aligned TFs
- `ctf_highest_aligned_tf`: minutes of highest aligned TF
- `i6_smc_bos_alignment`: [-1, +1] BOS vs higher-TF trend
- `i6_i2_event_score`: [-1, +1] I2 event confluence
- `i6_fvg_tf_alignment`: **0.0** (TODO stub)
- `i6_ob_tf_alignment`: **0.0** (TODO stub)

**Recency Weighting:** Already implemented — stale intel contributes less:
```python
bars_since = frames.get(f"intel_{tf}_bars_since", 999)
weight = 1.0 / (bars_since + 1)
# Fresh 5m bar (1 bar ago) → 0.5
# Stale 1h bar (60 bars ago) → 0.016
```

---

## Gap 1: Cross-Timeframe TODOs (High Priority)

### 1.1 FVG Cross-TF Alignment

**Current State:** `i6_fvg_tf_alignment = 0.0` (stub)

**What It Should Do:**
Check if there's an unfilled Fair Value Gap on a higher timeframe that aligns with the current signal direction.

**Logic:**
```python
def score_fvg_overlap(
    current_fvg_top: float,
    current_fvg_bottom: float,
    higher_fvg_5m: dict,
    higher_fvg_15m: dict,
    direction: int,  # -1 bearish, +1 bullish
) -> float:
    """
    Returns: [-1, +1] where +1 = higher-TF FVG supports current direction

    A bullish FVG on 15m (gap below current price) supports a bullish signal on 1m
    when price is above that FVG. The FVG acts as a "magnet" for continuation.
    """
    if direction == 0:
        return 0.0

    score = 0.0

    # Check 5m FVG
    fvg_5m_top = higher_fvg_5m.get("fvg_top")
    fvg_5m_bottom = higher_fvg_5m.get("fvg_bottom")
    if fvg_5m_top and fvg_5m_bottom:
        if direction == 1:  # bullish signal
            # FVG is below price → support zone
            if current_fvg_top > fvg_5m_bottom:
                score += 0.5
        elif direction == -1:  # bearish signal
            # FVG is above price → resistance zone
            if current_fvg_bottom < fvg_5m_top:
                score += 0.5

    # Check 15m FVG (higher weight)
    fvg_15m_top = higher_fvg_15m.get("fvg_top")
    fvg_15m_bottom = higher_fvg_15m.get("fvg_bottom")
    if fvg_15m_top and fvg_15m_bottom:
        if direction == 1:
            if current_fvg_top > fvg_15m_bottom:
                score += 1.0  # 15m FVG is more authoritative
        elif direction == -1:
            if current_fvg_bottom < fvg_15m_top:
                score += 1.0

    return clamp(score)
```

**Why It Matters:**
- FVGs are ICT price inefficiency zones that "should be filled"
- An unfilled higher-TF FVG in signal direction = institutional intent confirmation
- This is orthogonal to BOS/structure alignment — adds dimension to confluence

### 1.2 Order Block Cross-TF Alignment

**Current State:** `i6_ob_tf_alignment = 0.0` (stub)

**What It Should Do:**
Check if current price is within a higher-TF Order Block that aligns with expected direction.

**Logic:**
```python
def score_ob_alignment(
    current_price: float,
    higher_ob_5m: dict,
    higher_ob_15m: dict,
    direction: int,
) -> float:
    """
    Returns: [-1, +1] where +1 = higher-TF OB supports current direction

    For bullish signals: price being near/above 5m bullish OB = institutional buying zone
    For bearish signals: price being near/below 5m bearish OB = institutional selling zone
    """
    if direction == 0 or not current_price:
        return 0.0

    score = 0.0

    for ob_data, tf_minutes in [
        (higher_ob_5m.get("ob_bottom"), 5),
        (higher_ob_15m.get("ob_bottom"), 15),
    ]:
        if not ob_data:
            continue

        ob_bottom = ob_data.get("ob_bottom")
        ob_top = ob_data.get("ob_top")

        if ob_bottom and ob_top:
            ob_mid = (ob_bottom + ob_top) / 2
            atr = ob_data.get("atr_at_ob") or 20.0  # fallback
            proximity = abs(current_price - ob_mid) / atr

            # Is price within OB zone?
            if proximity < 0.5:  # Within 0.5 ATR of OB
                # Determine OB direction from recent candles before OB
                ob_bullish = ob_data.get("ob_bullish", 0.5) > 0

                if direction == 1 and ob_bullish:
                    # Bullish signal + bullish OB = confirmation
                    score += tf_minutes / 15.0  # 5m = 0.33, 15m = 1.0
                elif direction == -1 and not ob_bullish:
                    # Bearish signal + bearish OB = confirmation
                    score += tf_minutes / 15.0

    return clamp(score)
```

**Why It Matters:**
- OBs are last aggressive institutional order zones
- Price trading within higher-TF OB in signal direction = continuation from institutional level
- Confirms signal is "with the market makers" not against them

### 1.3 Squeeze-Within-Expansion Divergence

**New Dimension:** Detect coiled-spring setups where 1m is compressed but higher TFs show vol expansion.

**Logic:**
```python
def score_squeeze_expansion_divergence(
    bb_squeeze_1m: float,
    vol_expansion_5m: float,
    vol_expansion_15m: float,
) -> float:
    """
    Returns: [-1, +1] where:
    +1 = 1m squeezed + 15m+ expanding → breakout imminent
    -1 = 1m expanding + 15m+ squeezed → blow-off risk
    """
    if not bb_squeeze_1m:
        return 0.0

    expansion_5m = 1.0 if vol_expansion_5m > 0 else 0.0
    expansion_15m = 1.0 if vol_expansion_15m > 0 else 0.0

    # Squeeze on 1m, expansion on 15m+ = coiled spring
    if expansion_5m and expansion_15m:
        return 1.0

    # Expansion everywhere = no squeeze
    if not expansion_5m and not expansion_15m:
        return 0.0

    # 1m expanding, higher TFs compressed = blow-off
    return -1.0
```

**New Output:** `ctf_squeeze_expansion_divergence`

**Why It Matters:**
- Squeezes are high-probability breakout setups
- Vol expansion on higher TFs confirms the market is "ready to move"
- This is a momentum regime mismatch detector

### 1.4 Multi-TF Momentum Confluence

**New Dimension:** Score when all TFs show same momentum direction.

**Logic:**
```python
def score_momentum_confluence(
    momentum_bias_1m: float,
    momentum_bias_5m: float,
    momentum_bias_15m: float,
    momentum_bias_1h: float,
) -> float:
    """
    Returns: [-1, +1] where:
    +1 = all TFs bullish
    -1 = all TFs bearish
    0 = mixed or neutral
    """
    signs = [
        _sign(momentum_bias_1m),
        _sign(momentum_bias_5m),
        _sign(momentum_bias_15m),
        _sign(momentum_bias_1h),
    ]

    # All bullish?
    if all(s == 1 for s in signs):
        return 1.0

    # All bearish?
    if all(s == -1 for s in signs):
        return -1.0

    # Mixed or neutral
    return 0.0
```

**New Output:** `ctf_momentum_confluence`

**Why It Matters:**
- Momentum alignment across all TFs is a very strong signal
- From `renaissance-i7-i8-refinement.md` §1.5: already partially implemented in MTFAlignment
- Making it explicit in I6 allows all I7 plugins to use it

---

## Gap 2: Cross-Asset Confluence (New Plugin)

### 2.1 `CrossAssetConfluencePlugin` — New Plugin

**Purpose:** Score confluence across correlated assets (ES/NQ/RTY, sector ETFs, VIX)

**Plugin Signature:**
```python
@dataclass
class CrossAssetConfluencePlugin:
    """I6 cross-asset confluence scoring.

    Reads intelligence from correlated assets to produce a composite
    cross-asset alignment score. Answers:
    - "Are related futures moving together?"
    - "What does VIX say about this signal?"
    - "Is there sector rotation?"
    """
    name: str = "i6_CrossAssetConfluence"
    outputs: set[str] = frozenset({
        "caf_score",                     # [-1, +1] composite
        "caf_equities_alignment",          # ES/NQ/RTY agreement
        "caf_vix_regime",               # VIX term structure signal
        "caf_sector_rotation",             # Tech vs Energy vs SPY
        "caf_correlation_divergence",      # Deviation from baseline
        "caf_pairs_spread_zscore",        # Cointegration spread
    })
    min_lookback: int = 1
    supports_incremental: bool = False
    inputs: list[InputSpec] = ()
```

### 2.2 Equities Index Alignment (ES/NQ/RTY)

**Logic:**
```python
def score_equities_alignment(
    es_intel: dict,  # ES intelligence from current TF
    nq_intel: dict,  # NQ intelligence from current TF
    rty_intel: dict, # RTY intelligence from current TF
    cur_trend: int,     # Current symbol's trend direction
) -> float:
    """
    Returns: [-1, +1] where:
    +1 = ES/NQ/RTY all agree with current direction
    -1 = ES/NQ/RTY disagree (divergence = weak signal)
    """
    if not all([es_intel, nq_intel, rty_intel]):
        return 0.0

    signs = [
        _extract_trend_sign(es_intel),
        _extract_trend_sign(nq_intel),
        _extract_trend_sign(rty_intel),
    ]

    # Count agreement
    agree_count = sum(1 for s in signs if s == cur_trend)
    disagree_count = sum(1 for s in signs if s == -cur_trend)

    if agree_count == 3:
        return 1.0  # All agree = strong confluence
    elif agree_count >= 2:
        return 0.5  # 2/3 agree = moderate confluence
    elif disagree_count >= 2:
        return -0.5  # 2/3 disagree = divergence
    else:
        return 0.0
```

**New Output:** `caf_equities_alignment`

**Data Requirement:** IBKR subscriptions for ES, NQ, RTY (not just current symbol)

**Why It Matters:**
- Index futures are highly correlated (β ~0.8–0.95)
- When they diverge, the move is idiosyncratic (less reliable)
- When they agree, the move is structural (more reliable)
- From `renaissance-i7-i8-refinement.md` §4.1: lead-lag architecture

### 2.3 VIX Regime Signal

**Logic:**
```python
def score_vix_regime(
    vx_intel_5m: dict,
    vx_intel_15m: dict,
    vx_intel_1h: dict,
    cur_trend: int,  # ES/NQ/RTY direction
) -> float:
    """
    Returns: [-1, +1] where:
    +1 = VIX in low vol regime (complacency) → equities can trend
    -1 = VIX in high vol regime (fear) → reduce exposure
    0 = neutral VIX

    Also checks VIX term structure:
    - VX9D < VIX = term inversion (fear subsiding) → bullish
    - VX9D > VIX = term premium (fear building) → bearish
    """
    if not vx_intel_5m:
        return 0.0

    # VIX level regime (low vol = friendly for trends)
    vix_5m = vx_intel_5m.get("vix_level", 20.0)
    if vix_5m < 16:  # Low VIX = complacency
        vix_regime_score = 0.5
    elif vix_5m > 25:  # High VIX = fear
        vix_regime_score = -0.5
    else:
        vix_regime_score = 0.0

    # VIX term structure (requires 9-day and 3-month data)
    # This would need separate VIX9D/VIX3M streams
    # For now, use VIX trend as proxy
    vix_trend = _extract_trend_sign(vx_intel_5m)

    # Combine level and trend
    if vix_trend == 1:  # VIX falling = fear subsiding
        vix_regime_score += 0.3
    elif vix_trend == -1:  # VIX rising = fear building
        vix_regime_score -= 0.3

    # VIX regime gates equity signals
    if vix_regime_score < 0 and cur_trend != 0:
        # High VIX + long signal = reduce confidence
        return vix_regime_score

    return vix_regime_score
```

**New Output:** `caf_vix_regime`

**Data Requirement:** VX (VIX futures) intelligence stream + optionally VIX9D/VIX3M for term structure

**Why It Matters:**
- VIX is the fear index — inverse correlation to equities
- High VIX = regime where mean-reversion beats trend-following
- VIX term structure (VX9D vs VIX) predicts volatility mean-reversion

### 2.4 Sector Rotation Signals

**Logic:**
```python
def score_sector_rotation(
    xlk_intel: dict,  # XLK (Tech)
    xle_intel: dict,  # XLE (Energy)
    xlf_intel: dict,  # XLF (Financials)
    spy_intel: dict,  # SPY benchmark
) -> float:
    """
    Returns: [-1, +1] where:
    +1 = Tech outperforming = risk-on regime
    -1 = Tech underperforming = risk-off regime

    Also returns sector leadership flags for I7 gating.
    """
    if not all([xlk_intel, xle_intel, xlf_intel, spy_intel]):
        return 0.0

    # Compute 5d return ratio vs SPY
    xlk_vs_spy = compute_return_ratio(xlk_intel, spy_intel, bars=5)
    xle_vs_spy = compute_return_ratio(xle_intel, spy_intel, bars=5)
    xlf_vs_spy = compute_return_ratio(xlf_intel, spy_intel, bars=5)

    # Sector leadership signal
    if xlk_vs_spy > 1.02 and xle_vs_spy < 0.98 and xlf_vs_spy > 0.98:
        # Tech leading, others lagging = risk-on
        return 1.0
    elif xlk_vs_spy < 0.98:
        # Tech lagging = risk-off
        return -1.0

    return 0.0


def compute_return_ratio(asset_intel: dict, spy_intel: dict, bars: int) -> float:
    """Compute return ratio: (asset_return / spy_return)."""
    asset_close = asset_intel.get("close")
    spy_close = spy_intel.get("close")
    asset_close_n_bars_ago = asset_intel.get(f"close_{bars}_bars_ago")
    spy_close_n_bars_ago = spy_intel.get(f"close_{bars}_bars_ago")

    if not all([asset_close, spy_close, asset_close_n_bars_ago, spy_close_n_bars_ago]):
        return 1.0

    asset_return = (asset_close - asset_close_n_bars_ago) / asset_close_n_bars_ago
    spy_return = (spy_close - spy_close_n_bars_ago) / spy_close_n_bars_ago

    if spy_return == 0:
        return 1.0

    return asset_return / spy_return
```

**New Output:** `caf_sector_rotation`

**Data Requirement:** IBKR subscriptions for XLK, XLE, XLF, SPY

**Why It Matters:**
- Sector rotation reveals institutional positioning
- Tech leadership = risk-on regime (equity bullish)
- Utilities/energy leadership = defensive/risk-off regime
- From `renaissance-i7-i8-refinement.md` §7.4

### 2.5 Correlation Breakdown Detection

**Logic:**
```python
def score_correlation_divergence(
    es_intel: dict,
    spy_intel: dict,
    # Correlation baseline from DB (pre-computed)
    corr_es_spy_baseline: float,
    corr_es_spy_window: float,
) -> float:
    """
    Returns: [-1, +1] where:
    +1 = Correlation stronger than baseline (normal)
    -1 = Correlation breaking down = stress signal = reduce exposure
    """
    if not corr_es_spy_baseline:
        return 0.0

    # Deviation from long-term baseline
    deviation = corr_es_spy_window - corr_es_spy_baseline

    # 2σ below baseline = correlation breakdown
    std_dev = 0.05  # Assumed volatility of correlation
    if deviation < -2 * std_dev:
        # Assets diverging = stress regime
        return -1.0

    return 0.0
```

**New Output:** `caf_correlation_divergence`

**Data Requirement:** Rolling correlation computation + baseline tracking

**Why It Matters:**
- When normally-correlated assets diverge, it's a stress/regime-shift signal
- Correlation breakdown precedes many market dislocations
- From `renaissance-i7-i8-refinement.md` §7.2

### 2.6 Cointegration Pairs (Optional, Lower Priority)

**Logic:**
```python
def score_pairs_spread(
    es_intel: dict,
    spy_intel: dict,
    hedge_ratio: float,  # Pre-computed from DB
    spread_mean: float,
    spread_std: float,
) -> float:
    """
    Returns: z-score of ES-SPY spread from cointegration equilibrium.

    When |z_score| > 2.0, the spread is extreme = mean-reversion opportunity.
    """
    if not all([es_intel, spy_intel, hedge_ratio]):
        return 0.0

    es_price = es_intel.get("close")
    spy_price = spy_intel.get("close")

    if not all([es_price, spy_price]):
        return 0.0

    # Current spread
    spread = es_price - hedge_ratio * spy_price

    # Z-score from equilibrium
    z_score = (spread - spread_mean) / spread_std if spread_std > 0 else 0

    # Threshold gating
    if abs(z_score) > 2.0:
        # Extreme spread = directional signal based on spread direction
        return 1.0 if z_score > 0 else -1.0

    return 0.0
```

**New Output:** `caf_pairs_spread_zscore`

**Data Requirement:** Pre-computed cointegration stats (Engle-Granger test, hedge ratio)

**Why It Matters:**
- ES/SPY are cointegrated — when they diverge, they revert
- Pairs trading was Medallion's bread-and-butter
- From `renaissance-i7-i8-refinement.md` §7.1

**Note:** This is more I7 signal material than I6 confluence, but belongs in cross-asset intelligence infrastructure.

---

## Gap 3: Multi-Dimensional Confluence Scoring

### 3.1 Unified I6 Output Structure

All I6 plugins write to `IntelligenceEvent.i6` JSONB. Proposed structure:

```python
{
    # Cross-timeframe (existing, expanded)
    "ctf_score": float,                # [-1, +1] overall TF confluence
    "ctf_trend_alignment": float,
    "ctf_structure_alignment": float,
    "ctf_regime_agreement": float,
    "ctf_timeframes_aligned": float,
    "ctf_highest_aligned_tf": float,
    "ctf_momentum_confluence": float,   # NEW
    "ctf_squeeze_expansion_divergence": float,  # NEW

    # SMC cross-TF (existing, implemented)
    "i6_smc_bos_alignment": float,
    "i6_fvg_tf_alignment": float,        # TODO → implement
    "i6_ob_tf_alignment": float,          # TODO → implement
    "i6_i2_event_score": float,

    # Cross-asset (NEW)
    "caf_score": float,                  # [-1, +1] overall cross-asset confluence
    "caf_equities_alignment": float,       # ES/NQ/RTY agreement
    "caf_vix_regime": float,            # VIX signal
    "caf_sector_rotation": float,          # Tech vs Energy
    "caf_correlation_divergence": float,   # Correlation breakdown
    "caf_pairs_spread_zscore": float,    # Pairs spread

    # Regime (NEW)
    "crf_score": float,                  # [-1, +1] overall regime confluence
    "crf_vix_term_structure": float,     # VX9D vs VIX
    "crf_correlation_stress": float,      # Correlation matrix heat
    "crf_liquidity_regime": float,       # High/low liquidity detection
}
```

### 3.2 Weighted Multi-Dimensional Composite

The I7 aggregator should read all I6 dimensions and compute a unified confluence score:

```python
def compute_unified_confluence_score(i6_data: dict) -> float:
    """
    Combines cross-TF, cross-asset, and regime confluence into a single score.

    Dimensions:
    - Cross-TF: 0–1 scale (how many TFs agree?)
    - Cross-Asset: -1–1 scale (are assets confirming?)
    - Regime: -1–1 scale (is it stress or calm?)

    Weighting adapts based on which dimensions are "loud" (non-zero).
    """
    ctf = abs(i6_data.get("ctf_score", 0.0))  # [0, 1]
    caf = abs(i6_data.get("caf_score", 0.0))   # [0, 1]
    crf = abs(i6_data.get("crf_score", 0.0))   # [0, 1]

    # How many dimensions have signal?
    dimension_count = sum([
        ctf > 0.2,  # Significant TF confluence
        caf > 0.2,  # Significant asset confluence
        crf > 0.2,  # Significant regime signal
    ])

    if dimension_count == 0:
        return 0.0

    # Weight each dimension by its strength
    raw = (
        0.35 * ctf +
        0.35 * caf +
        0.30 * crf
    )

    # Normalize by how many dimensions are active
    normalized = raw * (dimension_count / 3.0)

    return clamp(normalized)
```

---

## Implementation Roadmap

### Phase 1: Cross-Timeframe Completion (High Priority)

| Task | Plugin | Output | Complexity |
|-------|---------|---------|----------|
| Implement FVG cross-TF alignment | `CrossTimeframeConfluencePlugin` | `i6_fvg_tf_alignment` | Medium |
| Implement OB cross-TF alignment | `CrossTimeframeConfluencePlugin` | `i6_ob_tf_alignment` | Medium |
| Add squeeze-expansion divergence | `CrossTimeframeConfluencePlugin` | `ctf_squeeze_expansion_divergence` | Low |
| Add momentum confluence | `CrossTimeframeConfluencePlugin` | `ctf_momentum_confluence` | Low |

### Phase 2: Cross-Asset Plugin (Medium Priority)

| Task | Plugin | Output | Complexity | Data Requirement |
|-------|---------|---------|-----------------|
| Create `CrossAssetConfluencePlugin` | `i6_CrossAssetConfluencePlugin` | — | — |
| Implement equities alignment (ES/NQ/RTY) | New | `caf_equities_alignment` | Low | ES, NQ, RTY streams |
| Implement VIX regime signal | New | `caf_vix_regime` | Low | VX stream (+ VX9D/VIX3M) |
| Implement sector rotation | New | `caf_sector_rotation` | Medium | XLK, XLE, XLF, SPY |
| Implement correlation breakdown | New | `caf_correlation_divergence` | Medium | Rolling correlation DB |
| Add to TIER_I6 | `register_plugins.py` | — | — |

### Phase 3: Regime Confluence (Low Priority)

| Task | Plugin | Output | Complexity |
|-------|---------|---------|----------|
| Create `RegimeConfluencePlugin` | `i6_RegimeConfluencePlugin` | — | — |
| Implement VIX term structure | New | `crf_vix_term_structure` | Medium | VX9D/VIX3M data |
| Implement correlation stress | New | `crf_correlation_stress` | Medium | Correlation matrix |
| Implement liquidity regime | New | `crf_liquidity_regime` | Low | Spread/vol metrics |
| Add to TIER_I6 | `register_plugins.py` | — | — |

### Phase 4: Integration & UI

| Task | Location | Complexity |
|-------|----------|------------|
| Expand I6 schema in `schemas.py` | `I6Confluence` dataclass | Low |
| Update `intelligence_features` migration | `ALTER TABLE ... ADD COLUMN i6` | Low |
| Market analysis service wiring | `market_analysis_service.py` | Low |
| Create unified confluence dashboard panel | `dashboard/src/components/` | Medium |
| CIS scoring integration | `cis_scorer.py` | Low |

---

## Data Requirements

### New IBKR Subscriptions (Cross-Asset)

For full cross-asset confluence, the TWS daemon needs parallel subscriptions:

| Symbol | Description | Priority |
|--------|-------------|----------|
| ES | Current (already subscribed) | — |
| NQ | Nasdaq-100 futures | High |
| RTY | Russell 2000 futures | High |
| SPY | SPDR S&P 500 ETF | Medium |
| VX | VIX futures | High |
| VX9D | 9-day VIX options (optional) | Low |
| VIX3M | 3-month VIX futures (optional) | Low |
| XLK | Technology Select Sector SPDR | Medium |
| XLE | Energy Select Sector SPDR | Medium |
| XLF | Financial Select Sector SPDR | Medium |

### Database Changes

**`intelligence_features` — expand `i6` JSONB:**
- Already has `ctf_*`, `i6_smc_*`, `i6_i2_*`
- Add: `ctf_momentum_confluence`, `ctf_squeeze_expansion_divergence`
- Add: `caf_*` fields (7 new fields)
- Add: `crf_*` fields (3 new fields)

**New table — correlation tracking:**
```sql
CREATE TABLE asset_correlations (
    symbol_a VARCHAR(8),
    symbol_b VARCHAR(8),
    window_minutes INT,
    correlation FLOAT,
    ts TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (symbol_a, symbol_b, window_minutes, ts)
);
CREATE INDEX ON asset_correlations (ts DESC);
```

**New table — cointegration stats:**
```sql
CREATE TABLE cointegration_pairs (
    symbol_a VARCHAR(8),
    symbol_b VARCHAR(8),
    hedge_ratio FLOAT,
    spread_mean FLOAT,
    spread_std FLOAT,
    updated_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (symbol_a, symbol_b)
);
```

---

## Renaissance Principle Alignment

| Principle | How I6 Expansion Satisfies |
|-----------|-----------------------------|
| **Instrument everything** | Every confluence dimension is captured and measurable |
| **Let the system run** | Confluence scores feed signal aggregator without manual override |
| **Segment relentlessly** | Confluence across TF, asset, correlation, sector = 4-way segmentation |
| **Degrade gracefully** | Missing data (no VIX, no sector) → partial confluence, not zero |
| **Data quality over model complexity** | Simple, interpretable scoring beats black-box ensemble |

---

## Open Questions

1. **VIX Data Source:** Yahoo Finance or CBOE direct? Term structure requires both VIX and VX9D.
2. **Cointegration Recomputation:** Daily? Weekly? How often to retest cointegration?
3. **Correlation Baseline Window:** 252 bars (1 day) or 2016 bars (8 days)?
4. **Sector ETF Coverage:** XLK/XLE/XLF or full GICS sector universe (11 ETFs)?
5. **Real-Time Correlation:** Compute per-bar or update every N bars?
6. **Dashboard Visualization:** How to show multi-dimensional confluence? Radar chart? Heatmap? Separate panels?

---

## Related Documents

- `renaissance-i7-i8-refinement.md` — Source of many ideas
- `regime-adaptive-trading.md` — Cross-TF synchronization, regime-specific models
- `intelligence-redo-brainstorm.md` — I6 refactor design
- `src/intelligence/confluence/cross_timeframe.py` — Current implementation
- `src/intelligence/schemas.py` — IntelligenceEvent schema
- `services/market_analysis_service.py` — I6 execution
