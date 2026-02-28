# Phase 7: Composite Intelligence Score (CIS) - Context

**Gathered:** 2026-02-27
**Status:** Ready for planning
**Source:** PRD Express Path (docs/plans/2026-02-27-composite-intelligence-score-design.md)

<domain>
## Phase Boundary

Replace the current winner-pick I7 aggregator with a principled Composite Intelligence Score (CIS) that:
- Aggregates ALL intelligence tiers (I1–I6) into 6 decorrelated factor buckets
- Produces a single directional probability score per bar (CIS ∈ [-1.0, +1.0])
- Self-improves via logistic regression trained on live signal outcomes
- Starts with designed weights, transitions to learned weights automatically
- Adds 5 new evidence-contributor I7 plugins (bringing total to 14)
- Improves entry type precision for 4 existing setups

This phase is self-contained: all existing 9 I7 plugins remain unchanged; stream keys, signal format, and trade_framer structural logic are unchanged.

</domain>

<decisions>
## Implementation Decisions

### 5 New I7 Plugins (Phase A — evidence contributors only, not standalone signals)

All 5 follow standard PatternPlugin protocol and are registered in TIER_I7:

- `trad_CHoCHReversal` — early trend flip signal; inputs: `choch_detected`, `choch_direction`, `hmm_regime`; bucket: Structure + Regime
- `trad_FVGFill` — FVG magnetism; inputs: `fvg_type`, `fvg_open_count`, `fvg_top`, `fvg_bottom`; bucket: Institutional
- `trad_PatternCompletion` — confirmed I5 patterns; inputs: `dt_db_*`, `hs_*`, `tri_*` from I5; bucket: Pattern
- `trad_DivergenceStack` — dual divergence (RSI + volume must both agree); inputs: `rsi_div_*`, `vol_div_*`; bucket: Momentum + Pattern
- `trad_RegimeTransition` — regime flip bet; inputs: `cp_probability`, `choch_detected`, `hmm_regime` flip; bucket: Regime + Structure

### 6 Factor Buckets (Phase B)

Each bucket produces a [-1.0, +1.0] directional score. Positive = bullish, negative = bearish, near-zero = no edge:

| Bucket | Bootstrap Weight | Key Inputs |
|--------|-----------------|------------|
| Trend | 0.20 | trend_regime, kalman_slope, smc_trend_direction, ctf_trend_alignment, trend_confluence_score |
| Momentum | 0.20 | roc_14, macd_histogram, rsi_14 vs 50, momentum_context, stoch_k, DivergenceStack output |
| Structure | 0.15 | swing_pattern, bos_detected+direction, choch_detected+direction, trend_strength, CHoCHReversal output |
| Pattern | 0.05 | dt_db_confidence+direction, hs_confidence, tri_confidence+breakout_bias, PatternCompletion output |
| Institutional | 0.25 | ob_type+strength, fvg_type, in_demand/supply_zone, sweep_type, premium_position, bsl/ssl_significance, FVGFill output, SupplyDemand output |
| Regime | 0.15 | hmm_prob_trending_up/down/ranging, cp_probability, garch_vol_state, vol_regime, ctf_regime_agreement, RegimeTransition output |

### CIS Fire Conditions (Phase B)

```
CIS = sum(weights[i] * bucket_scores[i] for i in range(6))
fires = abs(CIS) > 0.35 AND buckets_agreeing >= 3
```

Signal type label derived from two highest-weighted agreeing buckets.

### signal_ledger Schema Additions (Phase B)

Four new columns:
- `cis_score FLOAT` — CIS value at signal firing time
- `bucket_scores JSONB` — {"trend": 0.4, "momentum": 0.3, ...} at firing time
- `weights_version INTEGER` — FK to cis_weights version used
- `signal_quality FLOAT` — populated when outcome resolves: (rr_achieved × confidence) / vol_regime

### cis_weights Table (Phase C)

```sql
CREATE TABLE cis_weights (
    id SERIAL PRIMARY KEY,
    version INTEGER NOT NULL,
    weights_type TEXT NOT NULL,  -- 'designed' | 'learned'
    symbol TEXT DEFAULT 'global',
    timeframe TEXT DEFAULT 'global',
    trend_w FLOAT NOT NULL,
    momentum_w FLOAT NOT NULL,
    structure_w FLOAT NOT NULL,
    pattern_w FLOAT NOT NULL,
    institutional_w FLOAT NOT NULL,
    regime_w FLOAT NOT NULL,
    threshold FLOAT NOT NULL DEFAULT 0.35,
    n_training_samples INTEGER,
    signal_quality_mean FLOAT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

Active weights = MAX(version) WHERE symbol = 'global'. Global weights first; per-symbol rows deferred until ≥100 resolved signals per symbol.

### Adaptive Weight Learning (Phase C)

Bootstrap transition rules:
- n_resolved < 50: use 'designed' weights, no retraining
- 50 ≤ n < 100: train but keep 70% designed / 30% learned blend
- n ≥ 100: full learned weights, nightly retraining

Outcome metric: `signal_quality = (rr_achieved × confidence_at_fire) / vol_regime_at_fire`

`weight_updater.py` triggers nightly or when 20 new outcomes accumulate:
1. Load resolved signals with bucket_scores + signal_quality from signal_ledger
2. Train LogisticRegression (sklearn, C=1.0, max_iter=500) on bucket scores → binary quality above mean
3. Normalize coefficients via softmax, enforce min_w=0.05 per bucket
4. Write new version row to cis_weights

### Entry Type Improvements (Phase D)

Four setups upgraded from `at_close` to limit/pullback entries:
- `momentum_breakout_*` → `at_limit` at `swing_high/low` (broken structure level)
- `squeeze_expansion_*` → `at_limit` at `bb_middle` (squeeze centre)
- `trend_long/short` → `at_pullback` at `nearest_support/resistance` or key MA
- `mtf_alignment_*` → `at_pullback` at `ctf` confluence level

Implementation: `_resolve_entry()` in `trade_framer.py` gains two new entry type cases.

### Unchanged Components

- All 9 existing I7 plugins — unchanged, still registered in TIER_I7
- PatternPlugin protocol — unchanged
- Stream keys (`signals:SYMBOL:TF:aggregated`) — unchanged
- Signal format (entry/stop/targets/confidence/signal_type) — unchanged
- trade_framer.py structural stop/target logic — unchanged
- Dashboard field names — unchanged (signal_type label changes but field names stay)

### Claude's Discretion

- Exact bucket scorer implementation structure (separate class vs inline in aggregator)
- Test organization within plans (unit tests per plugin vs consolidated test file)
- Whether weight_updater.py is a standalone script or importable module
- sklearn dependency handling (already in project or needs adding)
- Specific logistic regression feature engineering details not covered by PRD

</decisions>

<specifics>
## Specific Ideas

### Implementation Order (from PRD "Implementation Phases" section)

The PRD defines 4 sequential phases (A→B→C→D) that map 1:1 to the 4 plans:
- **07-01** = Phase A: New I7 Plugins (5 plugins, standard protocol, full TDD)
- **07-02** = Phase B: CIS Scorer + Aggregator Replacement (bucket scorer, aggregator swap, schema migration)
- **07-03** = Phase C: Weight Updater + Adaptive Learning (cis_weights table, weight_updater.py, bootstrap logic)
- **07-04** = Phase D: Entry Type Improvements (at_limit, at_pullback in trade_framer.py)

### Key Architecture File

`src/intelligence/register_plugins.py` — TIER_I7 constant must list all 14 plugins. `registry.validate_tier()` hard-crashes at startup on any missing name. New plugins go in `src/intelligence/trading/`.

### Existing Signal Aggregator

Current aggregator in `signal_generator_service.py` picks winner by confidence + regime tiebreak. Phase B replaces this with CIS aggregator. The new aggregator should be a drop-in (same output format, same stream key).

### Feature Fields Available in IntelligenceEvent

CIS bucket scorers read from the existing IntelligenceEvent tiered JSONB fields (i3, i4, i5, smc, i6). All required inputs (choch_detected, fvg_open_count, hmm_prob_*, cp_probability, etc.) are already published by existing plugins.

</specifics>

<deferred>
## Deferred Ideas

- Per-symbol cis_weights rows — deferred until ≥100 resolved signals per symbol (23 symbols × 100 = deferred)
- i7/i8 columns in intelligence_features (backlog item — separate from this phase)
- ML scoring model (backlog — XGBoost/LightGBM, needs 90 days history)
- Dashboard visualization of CIS score and bucket breakdown (not in this phase — field names unchanged so existing panels still work)

</deferred>

---

*Phase: 07-composite-intelligence-score*
*Context gathered: 2026-02-27 via PRD Express Path*
