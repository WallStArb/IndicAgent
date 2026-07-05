# I6 Confluence Pattern Exploration

**Version:** 1.0
**Status:** SUPERSEDED by `docs/ideas/intel-10-confluence-detection-persistence-layer.md` (v3.0 successor: confluence as an IC-validated statistical object, not a plugin score). This doc describes the v2.x I6 plugin approach — I5-I7 archived in v3.0.
**Priority:** medium
**Milestone:** future (post-v2.8)
**Last Updated:** 2026-05-02
**Tags:** confluence, i6, cross-timeframe, patterns, renaissance, algorithm, intelligence

## Problem Statement

Current I6 Confluence tier has only 1 plugin: `CrossTimeframeConfluence` — multi-timeframe alignment scoring.

**Open questions:**
- What other confluence patterns matter?
- How do we discover them algorithmically vs. manually?
- Renaissance perspective: let data reveal patterns, don't pre-invent them

## Current State Analysis

### Existing `CrossTimeframeConfluencePlugin`
Location: `src/intelligence/confluence/cross_timeframe.py`

**What it does:**
- Reads cached intelligence from other timeframes (`intel_*`)
- Computes weighted confluence score across 5 alignment dimensions:
  - Trend alignment (recency-weighted)
  - Structure alignment (recency-weighted)
  - Regime agreement (recency-weighted)
  - Pattern confirmation (current TF patterns confirmed by higher TFs)
  - SMC BOS alignment (recency-weighted)
  - I2 event score (MACD/RSI/Stochastic event summation)
- Outputs 10 fields to `IntelligenceEvent.i6`

**Output fields:**
```python
{
    "ctf_score",              # Weighted confluence score [-1.0, 1.0]
    "ctf_trend_alignment",   # Recency-weighted trend agreement across TFs
    "ctf_structure_alignment", # Recency-weighted swing pattern agreement
    "ctf_regime_agreement",  # Recency-weighted regime/momentum/vol agreement
    "ctf_timeframes_aligned",  # Count of TFs aligned with current direction
    "ctf_highest_aligned_tf",  # Minutes of highest-TF that agreed
    "i6_smc_bos_alignment",  # SMC BOS alignment vs higher-TF trends
    "i6_fvg_tf_alignment",   # TODO: FVG overlap across TFs
    "i6_ob_tf_alignment",     # TODO: OB confluence across TFs
    "i6_i2_event_score",      # I2 composite event summation
}
```

**Weights (recency-based):**
```python
W_TREND = 0.4
W_STRUCTURE = 0.3
W_REGIME = 0.2
W_PATTERN = 0.1
W_I2 = 0.1
```

## Renaissance-Aligned Framework Approach

### Core Principle

**"Let system run. Don't override data with intuition."**

We don't pre-specify which confluence patterns matter. We:
1. Enumerate ALL concurrent signals (I5 × I6 × I7 × assets)
2. Track which combinations occur together over time
3. Measure performance of each combination
4. Surface statistically significant patterns to human analysts
5. Humans label meaningful patterns with domain expertise
6. System uses labeled patterns as filters for I7 setups

### Why This Beats Pre-Specified Confluence Plugins

**Pre-specified plugins (original Option 1 approach):**
```
MultiPatternConfluencePlugin   — Hard-coded: "squeeze + divergence + BOS"
MultiTierAgreementPlugin     — Hard-coded: "I5 + I6 + I7 all fire"
LevelClusterConfluencePlugin    — Hard-coded: "Fibonacci + session + swing in zone"
MultiAssetCorrelationPlugin    — Hard-coded: "ES + NQ + RTY all bullish"
```

**Problems:**
- We're inventing hypotheses about what confluence matters
- Renaissance would ask: "Where's the evidence squeeze+divergence+BOS is better than FVG+OB+AMD?"
- If a combination underperforms, we can't know why — correlation vs causation
- When market regime shifts, pre-coded patterns may stop working but we don't detect it

**Renaissance framework (unsupervised discovery):**
- System discovers patterns, humans interpret them
- Every confluence signature is measured independently
- If `squeeze+divergence+BOS` stops working in trending regime, we see `occurrence_count` drop, `win_rate` degrade
- Renaissance can surface: "Hey, `squeeze+divergence+BOS` only works in ranging regime (HMM=0). Try `squeeze+FVG` in trending."

### 5-Phase Renaissance Discovery Cycle

#### **Phase 1: Enumeration (Automated)**
Framework plugin tracks ALL concurrent I5/I6/I7 signals per bar:

```python
class ConfluenceExplorationPlugin:
    """Enumerate concurrent signals to discover confluence patterns."""

    def compute_full(self, frames: dict) -> dict:
        # Collect all signals that fired on current bar
        concurrent_signals = {
            # I5 patterns
            "rsi_divergence": features.get("rsi_div_bullish", 0),
            "bollinger_squeeze": features.get("bollinger_squeeze", 0),
            "volume_divergence": features.get("volume_divergence_bullish", 0),
            # I6 SMC
            "bos": features.get("bos_direction", 0),
            "fvg": features.get("fvg_type", 0),
            "order_block": features.get("ob_type", 0),
            "liquidity_sweep": features.get("sweep_type", 0),
            "amd_phase": features.get("amd_phase", 0),
            "killzone_active": features.get("ict_killzone", 0),
            # I7 setups
            "trend_following": features.get("setup_trend_following_conf", 0),
            "mean_reversion": features.get("setup_mean_reversion_conf", 0),
            "liquidity_sweep_reclaim": features.get("setup_liquidity_sweep_reclaim_conf", 0),
            "squeeze_expansion": features.get("setup_squeeze_expansion_conf", 0),
            # ... all 17 I7 setup confidences
        }

        # Filter to only signals that actually fired (>0)
        active = {k: v for k, v in concurrent_signals.items() if v > 0}

        # Compute confluence signature (what fired together)
        signature_hash = hash(tuple(sorted(active.keys())))

        return {
            "confluence_signature": signature_hash,
            "confluence_active_count": len(active),
            "confluence_signals": active,
        }
```

**Output fields:**
- `confluence_signature`: Integer hash representing unique combination
- `confluence_active_count`: How many signals fired (3, 5, 7?)
- `confluence_signals`: Dict of active signal names

#### **Phase 2: Accumulation (Automated)**
Track confluence signatures over time in TimescaleDB:

```sql
CREATE TABLE confluence_patterns (
    signature_hash BIGINT PRIMARY KEY,
    signature TEXT NOT NULL,              -- Human-readable: "squeeze_divergence_bos_amd_accumulation"
    signature_signals JSONB,              -- What fired together
    occurrence_count BIGINT DEFAULT 0,
    win_count BIGINT DEFAULT 0,
    loss_count BIGINT DEFAULT 0,
    win_rate DECIMAL(5,4),
    sample_size BIGINT DEFAULT 0,

    -- Segmentation: Renaissance principle
    regime_hmm INT,                         -- HMM regime this pattern occurred in
    regime_amd_phase TEXT,                   -- AMD cycle phase
    timeframe VARCHAR(10),                   -- Which TF

    last_seen_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_confluence_performance ON confluence_patterns(win_rate, sample_size);
CREATE INDEX idx_confluence_regime ON confluence_patterns(regime_hmm, timeframe);
```

**Writer logic:** `confluence_explorer_writer.py` — consumes `intelligence:SYMBOL:TF` stream, upserts to `confluence_patterns` table on every signal outcome.

#### **Phase 3: Surface Candidates (Automated)**
Query for statistically significant patterns:

```sql
-- Renaissance thresholds: sufficient N, statistically significant p-value
SELECT
    signature,
    signature_signals,
    occurrence_count,
    win_rate,
    sample_size,
    regime_hmm,
    timeframe
FROM confluence_patterns
WHERE sample_size >= 100                      -- Minimum sample size
  AND occurrence_count >= 30                 -- Pattern occurs often enough
  AND win_rate > 0.60                         -- Above random (60% for directional)
ORDER BY win_rate DESC, sample_size DESC
LIMIT 50;
```

**Output to dashboard/research UI:**
- Top 50 confluence patterns ranked by `win_rate`
- With `occurrence_count` and `sample_size`
- Segmented by `regime_hmm` and `timeframe`

#### **Phase 4: Human Labeling (Manual)**
You or Renaissance analysts review top candidates:

**Human tasks:**
1. Review pattern combinations that statistically outperform
2. Interpret market logic behind why they work together
3. Give meaningful names to patterns

**Examples of human labels:**
- `"squeeze + divergence + BOS in AMD accumulation"` → `"Momentum Squeeze Confluence"`
- `"TrendFollowing + CHoCH + Premium zone"` → `"Trend Continuation Confluence"`
- `"MeanReversion + liquidity sweep + FVG"` → `"Liquidity Flip Confluence"`

**Labeling workflow:**
```sql
UPDATE confluence_patterns
SET name = 'Momentum Squeeze Confluence',
    human_validated = TRUE,
    notes = 'Combination of squeeze, divergence, and BOS during AMD accumulation. Works best in HMM regime 1/2.'
WHERE signature_hash = 123456789;
```

#### **Phase 5: Integration (Automated)**
I7 setup plugins consume labeled confluence patterns:

```python
# In I7 setup plugin compute_full()
confluence_signature = features.get("confluence_signature")
confluence_name = features.get("confluence_name")  # From human label

if confluence_name == "Momentum Squeeze Confluence":
    confidence_multiplier = 1.4  # Boost this setup
elif confluence_name == "Liquidity Flip Confluence":
    confidence_multiplier = 1.3
else:
    confidence_multiplier = 1.0
```

**Setup can also filter:**
```python
if not confluence_name:
    # Only fire setup if a named confluence pattern is active
    return {}
```

## Open Questions for Further Research

### Confluence Detection Mechanisms
1. **Multi-bar confirmation**: Should we detect confluence across N bars (3-5 bars) instead of single bar?
   - Tradeoff: More confirmation vs. latency
   - Renaissance would test both and measure performance

2. **Sequential vs. simultaneous**: Does order matter?
   - "Divergence → squeeze → BOS" (sequential pattern) vs. all 3 on same bar
   - Track sequence signatures: `divergence|squeeze|bos`

3. **Cross-asset confluence timing**: When ES and NQ both show same pattern, which leads?
   - If ES fires confluence 5m before NQ, NQ is predictable
   - Track lead/lag relationships

4. **Regime-specific patterns**: Which confluence patterns work in trending vs. ranging regimes?
   - `confluence_patterns.regime_hmm` segmentation answers this
   - Renaissance would enable/disable patterns by regime

### Performance Measurement
1. **Time decay**: Do confluence patterns degrade over time (market adaptation)?
   - Track rolling 30d vs. 90d vs. 180d win rates
   - Renaissance monitors for signal decay

2. **Correlation vs. causation**: Is `squeeze + divergence + BOS` causally linked, or just correlated?
   - Granger causality testing
   - Renaissance cares: if causally linked, robust; if correlated, fragile

3. **Sample bias**: Some confluence patterns may only fire in specific market conditions
   - `occurrence_count / total_bars` = pattern frequency
   - Rare patterns (0.1% occurrence) need higher win rates to justify activation

## Advantages of Renaissance Framework

1. **No hand-coded hypotheses** — We're not guessing what confluence matters
2. **Statistical rigor** — Every pattern measured independently via p-values
3. **Granular control** — Enable/disable individual patterns if they degrade
4. **Segmentation** — Patterns tracked per regime/timeframe for Renaissance principle
5. **Self-correcting** — System detects when patterns stop working (low occurrence, degraded win rate)
6. **Human-in-the-loop** — Renaissance analysts interpret, system executes

## Comparison: Renaissance vs. Pre-Specified

| Aspect | Renaissance Framework | Pre-Specified Plugins |
|--------|---------------------|----------------------|
| Pattern discovery | Unsupervised enumeration, human labeling | Hard-coded hypotheses |
| Performance tracking | Per-signature win rate, sample size, p-value | Aggregate only |
| Regime adaptation | Automatic detection via segmentation | Manual regime filters |
| Failure mode | Pattern stops occurring = system knows | Plugin still fires, loses money |
| Renaissance alignment | ✅ Let data reveal what matters | ❌ Override data with intuition |

## Implementation Considerations

### Plugin: `ConfluenceExplorationPlugin`
- **Tier:** I6 Confluence
- **Inputs:** All I5/I6/I7 signals via `features` dict
- **Outputs:** `confluence_signature`, `confluence_active_count`, `confluence_signals`
- **Consumer:** New service: `confluence_explorer_service.py`
- **DB writer:** `confluence_explorer_writer.py`
- **Dashboard:** New panel "Confluence Explorer" showing top 50 patterns

### Integration with Existing System
- `ConfluenceExplorationPlugin` outputs to `IntelligenceEvent.i6` (like `CrossTimeframeConfluence`)
- I7 setup plugins consume `confluence_signature` from `intelligence_features.i6`
- `confluence_patterns` table joins to `signal_ledger` for win rate computation
- Human labeling workflow: SQL updates + dashboard UI

## Next Steps

1. **Build Phase 1-3**: `ConfluenceExplorationPlugin`, DB schema, writer service, surface query
2. **Collect baseline data**: Run for 30 days to accumulate occurrences
3. **Human review session**: You review top 20 candidates, assign names
4. **Integration phase**: Wire labeled patterns into I7 setup plugins
5. **Iterate**: Repeat discovery cycle every 90 days as market conditions evolve

## Related Concepts

- **Renaissance framing**: `docs/ideas/renaissance-framing.md`
- **MLAgent learning machine**: `docs/ideas/ml-learning-machine.md` — similar "Discovery → Scoring → Feedback" loop
- **Intelligence tiers**: `docs/concepts/intelligence-tiers.md`
- **Plugin architecture**: `docs/architecture/plugin-registry-and-dag-execution.md`

---

**Status:** Research complete, ready for design spec when approved.
