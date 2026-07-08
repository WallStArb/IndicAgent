# Renaissance Principles Gap Analysis

**Last Updated:** 2026-05-02

**Created:** 2026-03-08
**Status:** Phase 29 shipped — T0-B, T1-A–E, T2-A, T2-B, T3-A, T3-B all live as of 2026-03-13
**Related:** `docs/research/renaissance-i7-i8-refinement.md` (105 ideas, 48 sections)

## Overview

IndicAgent has excellent infrastructure (data pipeline, DAG execution, event bus) but is missing two things:
1. **Signal quality improvements** — the I7 layer fires signals, but doesn't gate them on alpha decay, freshness, volume confirmation, or market quality
2. **Systematic discovery loop** — outcomes are collected but not exploited to ask "under what conditions does X work best?" or to detect when the system is degrading

This document consolidates the actionable gaps from both the analytical infrastructure view and the signal refinement research backlog into a prioritized implementation plan.

## Core Principle Assessment

| Renaissance Principle | What It Means | IndicAgent Status | Gap Priority |
|---------------------|-----------------|-------------------|----------------|
| **Instrument everything** | Every data point is measurable; no decisions without evidence | ✅ Full feature vectors, LLM audit trail, lifecycle outcomes | — |
| **Let the system run** | Build automation, trust it; no manual overrides | ✅ systemd-managed services, autonomous pipeline | — |
| **Earn the right through proof** | p < 0.05, sufficient N before promotion | ⚠️ `setup_performance` requires N≥30, but **no p-value test** | Deferred (needs outcome volume) |
| **Segment relentlessly** | Rules must specify conditions where they hold | ⚠️ HMM regimes exist, but fine-grained "when does X work?" is missing | Deferred (needs outcome volume) |
| **Degrade gracefully, adapt automatically** | Feedback loops self-correct without tuning | ⚠️ CIS weights are static; **no drift detection** on features or signal performance | **HIGH — buildable now** |
| **Data quality over model complexity** | Clean data beats smart models on dirty data | ✅ TimescaleDB constraints, schema validation | — |
| **Never drop training data** | Every outcome is a labeled sample | ✅ `signal_ledger` retained forever, LLM outcomes backfilled | — |

---

## Implementation Plan

### Tier 0 — Bug Fixes (no design needed)

These are things that are supposed to work but don't.

**T0-A: Fix CIS scoring in `historical_backfill.py`**
- `aggregate()` is not receiving `features=` argument → CIS fields are NULL in `intelligence_features` cold storage
- Fix: pass the feature dict when calling the CIS aggregator during backfill replay
- Impact: fixes the entire ML training dataset for CIS analysis

**T0-B: Populate `constituent_contributions` in `cis_scorer.py`** ✅ SHIPPED (Phase 29-01)
- `cis_scorer.py:158` initializes `constituent_contributions: {b: {} for b in BUCKET_NAMES}` — always empty, never populated
- Each bucket scorer runs and produces per-setup scores but discards them before writing to `CISResult`
- Fix: capture per-setup score contributions during bucket scoring and write them to the JSONB field
- Impact: enables future counterfactual analysis — which setups pushed which buckets, on every bar
- Note: `constituent_contributions` is already a column in `signal_ledger` JSONB; this is purely a data population gap

---

### Tier 1 — Signal Quality Improvements (wire-ins, no new plugins)

These use data that already exists in the pipeline and wire it into CIS scoring or signal gating logic. Buildable now.

**T1-A: Alpha Decay Rate** ✅ SHIPPED (Phase 29-03)
- Renaissance principle: the 5th consecutive same-direction signal has less alpha than the 1st
- Add `alpha_decay_rate` to I4 feature output: `1.0 - (bars_since_last_signal / alpha_half_life)`
- Wire decay factor into `_build_all_ranked()` in `signal_generator_service.py` as a CIS score multiplier
- Vol-of-vol variant: `vol_adjusted_half_life = base_half_life / (1 + vol_of_vol)` — decay accelerates in unstable regimes

**T1-B: Time-Weighted Signal Freshness** ✅ SHIPPED (Phase 29-03)
- Distinct from alpha decay: this is about how stale the *signal instance* is from the moment it fired, not setup clustering
- Exponential decay: `freshness = exp(-lambda * bars_since_fire)` applied to CIS confidence on each downstream bar
- Prevents signals fired 20 bars ago from competing with fresh signals at equal confidence
- Wire into `signal_lifecycle_service.py` when evaluating active signals

**T1-C: Signal Recycling Window** ✅ SHIPPED (Phase 29-02)
- Prevent same setup from firing multiple times within N bars in the same direction
- Add per-symbol per-TF per-setup cooldown window in `signal_generator_service.py`
- Configurable: `_SIGNAL_COOLDOWN_BARS` (suggested: 3 bars for 1m, 2 bars for 5m+)
- Reduces noise from setup clustering in strong trends without killing legitimate re-entries

**T1-D: Volume-Weighted Confidence** ✅ SHIPPED (Phase 29-02)
- `rel_volume` is already computed in I1 (relative volume vs rolling average)
- Not currently wired into CIS bucket scoring
- Wire as a momentum/institutional bucket multiplier: `rel_volume > 1.5` → confidence boost; `rel_volume < 0.5` → suppress
- Prevents signals firing on dead-volume bars where breakouts are likely false

**T1-E: Killzone Acceleration** ✅ SHIPPED (Phase 29-02)
- Killzones (Asian/London/NY open) are already tracked in the intelligence bus
- Currently used for context display only — not as a signal gate or boost
- Wire as a time-of-day gate in CIS: boost signal confidence in killzone opens, reduce during dead sessions
- Particularly relevant for mean-reversion setups which underperform in off-hours low-liquidity

---

### Tier 2 — New I4 Plugins (require plugin implementation)

These require new computations but use existing data (rolling returns, price stream). No external data dependencies.

**T2-A: Hurst Exponent Regime Detection** ✅ SHIPPED (Phase 29-04/05)
- Measures fractal dimension of price series: H > 0.5 = trending, H < 0.5 = mean-reverting, H ≈ 0.5 = random
- Complements HMM regime (which classifies direction) with a *type* classification
- Hard gate: mean-reversion setups suppressed when H > 0.65; trend setups suppressed when H < 0.45
- Requires rolling 64–256 bar window of returns (already available)

**T2-B: Shannon Entropy Market Quality Gate** ✅ SHIPPED (Phase 29)
- Measures information entropy of the return distribution: low entropy = structured/predictable, high entropy = noise
- Universal signal confidence gate: `entropy > threshold` → all signal confidence reduced by 30–50%
- Particularly valuable for filtering out choppy, non-directional periods where all setups underperform
- Requires rolling return distribution (already available)

**T2-C: Momentum Exhaustion Entry**
- RSI acceleration (second derivative of RSI or rate-of-change of RSI)
- Detects when momentum is peaking/reversing before price confirms
- Wire as a new I7 plugin or as an I4 feature → CIS momentum bucket contribution
- Complements existing RSI-based plugins with timing precision

---

### Tier 3 — Monitoring & Drift Detection (new infrastructure, buildable now)

These detect system degradation before it becomes a crisis. No signal dependencies; uses existing data.

**T3-A: KS Distribution Drift Detection** ✅ SHIPPED (Phase 29-06)
- Kolmogorov-Smirnov test on I1/I4 feature distributions vs a baseline reference window
- Detects when market microstructure has changed enough to invalidate model assumptions
- Alert: `KS p-value < 0.05` on key features (RSI, vol regime, HMM state distribution) triggers monitoring flag
- Reference window: establish from first 30 days of `intelligence_features` data
- Implementation: periodic background job (every 4h), writes drift flags to a monitoring table

**T3-B: CUSUM Performance Drift Detection** ✅ SHIPPED (Phase 29-07)
- Cumulative sum control chart on rolling `pnl_r` from `signal_ledger` outcomes
- Detects when signal performance is statistically degrading vs expected baseline
- Alert triggers: CUSUM statistic exceeds control limit → flag in observability dashboard
- Per-setup tracking: each I7 plugin gets its own CUSUM monitor, not just aggregate
- Implementation: background job reading `signal_ledger` outcome stream

---

### Deferred — Needs Outcome Volume (3–6 months of live signals)

These are correct approaches but meaningless without sufficient `signal_ledger` outcome data. Don't build them yet — build them when N ≥ 200 outcomes per setup.

**D1: Statistical Significance Framework (p-values)**
- Wilson score interval / t-test on per-setup win rates vs null hypothesis
- Gating requirement before any CIS weight changes
- Deferred: current signal volume too low for meaningful p-values

**D2: Segmentation Analysis Matrix**
- `setup_plugin × vol_regime × time_of_day × hmm_regime` performance breakdown
- Start 2D: `vol_regime × session` — expand dimensions as data grows
- Deferred: segment cells will be too sparse with current volume

**D3: Regime Suppression Validation**
- Track virtual outcomes for `status='regime_suppressed'` signals via `signal_lifecycle_service`
- Validates whether `_REGIME_PROB_MIN=0.60` and `_REGIME_DUR_MIN=5` thresholds are correctly calibrated
- Add `outcome_virtual` column to `signal_ledger`
- Deferred: need 200+ suppressed signals with resolved outcomes to draw conclusions

**D4: A/B Testing Infrastructure**
- `experiment_version` column in `signal_ledger`; split traffic between CIS variant and baseline
- Deferred: no point testing weight changes until we have statistical significance infrastructure (D1)

**D5: Bayesian Online Weight Updates**
- Beta posterior per setup (win/loss → posterior update) replaces static `BOOTSTRAP_WEIGHTS`
- Thompson sampling for explore/exploit across setup selection
- Deferred: needs outcome stream volume and KS drift detection first (to know when to reset posteriors)

---

## Relationship to `renaissance-i7-i8-refinement.md`

The 105 ideas in the refinement doc map to this plan as follows:

| Refinement Ref | This Plan |
|---|---|
| #3 Alpha Decay | T1-A |
| #8 Signal Freshness | T1-B |
| #4 Signal Recycling | T1-C |
| #6 Volume-Weighted Confidence | T1-D |
| #5 Killzone Acceleration | T1-E |
| #2 Hurst Exponent | T2-A |
| #1 Shannon Entropy | T2-B |
| #7 Momentum Exhaustion | T2-C |
| #9 KS Drift Detection | T3-A |
| #10 CUSUM Performance Drift | T3-B |
| #20 Counterfactual Logging | T0-B |
| #11–22 (Bayesian/Causal) | Deferred (D5) |
| #33–42 (Agentic/Self-Improving) | Deferred |

---

## What Renaissance Would Demand

These are the five structural gaps in how we measure, validate, and evolve the system. All five are **deferred** until we have sufficient outcome volume — but they define the target state.

### Gap 1: Statistical Significance Before Any Weight Change → D1

Current: `setup_performance` gates `perf_multiplier` when N ≥ 30. No p-value test exists.

Renaissance demand: before `trad_TrendFollowing` gets weight 1.2 (up from 1.0), prove it:

```sql
SELECT
    setup_plugin,
    COUNT(*) as n,
    AVG(CASE WHEN outcome IN ('target_1', 'target_1_2', 'target_full') THEN 1 ELSE 0 END) as win_rate,
    AVG(pnl_r) as avg_return,
    STDDEV(pnl_r) as return_vol
    -- Wilson score interval for p-value calculation
FROM signal_ledger
WHERE outcome IS NOT NULL
GROUP BY setup_plugin
HAVING COUNT(*) >= 50  -- Renaissance wouldn't accept N=30
```

Only setups with **p < 0.05** get weight bumps. A setup with N=20, win_rate=55% stays at weight=1.0 — you don't promote it to 1.3 on 10 trades, even if they all won.

Implementation notes:
- Wilson score interval is more accurate than normal approximation for small N
- Threshold should be configurable per setup (some fire less frequently)
- Gate enforcement: automated check in `setup_performance` refresh job before writing `perf_multiplier`

### Gap 2: Segmentation Analysis, Not Just Regime Tags → D2

Current: HMM gives `trending_up / trending_down / ranging`. No quantified breakdown by conditions.

Renaissance demand: "trad_MeanReversion works best when..." with measured proof:

```sql
SELECT
    setup_plugin,
    vol_regime,             -- low/medium/high from I4
    hmm_regime_state,       -- 0/1/2 from HMM
    trend_regime,           -- I3 trend classification
    time_of_day,            -- Asian/London/NY/Overnight (derived from timestamp)
    weekday,                -- Mon/Tue/Wed/Thu/Fri
    days_from_earnings,     -- pre/post earnings (needs external calendar data)
    COUNT(*) as n,
    AVG(CASE WHEN outcome IN ('target_1', 'target_1_2', 'target_full') THEN 1 ELSE 0 END) as win_rate,
    AVG(pnl_r) as avg_return,
    STDDEV(pnl_r) as return_vol
FROM signal_ledger
WHERE outcome IS NOT NULL
GROUP BY 1,2,3,4,5,6,7
HAVING COUNT(*) >= 30
```

Example discovery: *"MeanReversion wins 4.3% in high-vol London session, loses 2.1% in low-vol Asian session"* — this gets encoded as a **hard rule**, not a soft confidence adjustment.

Implementation notes:
- Start with 2D segments: `vol_regime × time_of_day` (no external data needed)
- Add dimensions incrementally as data volume grows (segment explosion → sparse cells)
- `days_from_earnings` requires external calendar API (Forex Factory, etc.) — add last

### Gap 3: Counterfactual Tracking — What Didn't Fire → T0-B

Current: `cis_scorer.py:158` initializes `constituent_contributions: {b: {} for b in BUCKET_NAMES}` — always empty, never populated.

Renaissance demand: when 6 buckets say LONG and `trad_TrendFollowing` is selected as winner, record every setup's contribution:

```python
# CISResult.constituent_contributions (currently always {}):
{
    "trend": {
        "trad_TrendFollowing": +0.20,   # pushed trend +0.20
        "trad_MeanReversion": +0.05,    # pushed trend +0.05 (weaker)
    },
    "momentum": {
        "trad_DivergenceStack": +0.10,  # fired, contributed +0.10
        "trad_TrendFollowing": 0.0,     # fired but didn't push momentum
    },
    "structure": {
        "trad_CHoCHReversal": 0.0,      # didn't fire — 0 contribution
    },
    # etc. for pattern, institutional, regime buckets...
}
```

Why this matters: when `trad_TrendFollowing` wins 4.3% but `trad_CHoCHReversal` (which didn't fire) would have won 5.2% in this regime, you've discovered a regime where CHoCH signals are undervalued. That's alpha to exploit.

This is a **bug fix** — the infrastructure already exists, the data is just never written.

### Gap 4: Regime Suppression Granularity → D3

Current: `regime_suppressed` status exists, `suppression_reason` is tracked. No virtual outcome measurement.

Renaissance demand: measure whether the gate is calibrated correctly:

```sql
SELECT
    setup_plugin,
    suppression_reason,       -- regime_prob / regime_duration / regime_type
    outcome_virtual,          -- simulated outcome if we had activated
    COUNT(*) as n,
    AVG(CASE WHEN outcome_virtual IN ('target_1', 'target_1_2', 'target_full') THEN 1 ELSE 0 END) as win_rate_virtual
FROM signal_ledger
WHERE status = 'regime_suppressed'
GROUP BY 1,2
```

Example finding: *"MeanReversion suppressed in regime_prob < 0.60 has virtual win rate of 62%"* → gate is too tight, missing alpha.

Requires: `outcome_virtual` column in `signal_ledger` + `signal_lifecycle_service` mode that simulates suppressed signals through the MAE/MFE/exit lifecycle without activating them.

### Gap 5: A/B Testing Protocol → D4

Current: No shadow mode. Any CIS weight or threshold change goes live immediately without comparison.

Renaissance demand: never deploy without shadow comparison:

```python
# For 30 days:
# 50% of signals: CIS scoring (candidate version)
# 50% of signals: Priority-based selection (baseline control)

# Promotion gate — all three must pass:
win_rate_diff        # must be statistically significant (p < 0.05)
sharpe_ratio_diff    # must improve vs baseline
max_drawdown_diff    # must not worsen
```

Only if CIS variant outperforms baseline with p < 0.05 does it become the new default.

Requires: `experiment_version` column in `signal_ledger` + experiment coordinator (CLI flag or service config).

---

## Summary

| Area | Renaissance | Us | Gap |
|---|---|---|---|
| **Proof** | p-value < 0.05 before weight change | N ≥ 30 gate | No p-value test |
| **Segmentation** | Quantified "when X works best" | HMM regimes | Missing session/vol/time breakdown |
| **Counterfactuals** | Track what didn't fire | `all_ranked` exists | `constituent_contributions` always empty |
| **Regime gates** | Measure if too tight/loose | `regime_suppressed` exists | No virtual outcome tracking |
| **A/B testing** | Shadow mode before promotion | N/A | No A/B infrastructure |

Jim Simons would say: *You've built an excellent data pipeline, but you're not exploiting the data you collect. You know what happened, but you're not systematically discovering why or under what conditions.*

The Renaissance edge wasn't better math — it was relentless measurement and experimentation. We have the measurement infrastructure; we're missing the systematic discovery loop.

---

## Related Documents

- [Renaissance I7/I8 Refinement Ideas](./renaissance-i7-i8-refinement.md) — full 105-idea research backlog
- [CIS Scoring Concepts](../concepts/cis-scoring.md)
- [Signal Ledger Schema](../reference/schemas/stream-schemas.md)
- [Renaissance Framing](./renaissance-framing.md)
