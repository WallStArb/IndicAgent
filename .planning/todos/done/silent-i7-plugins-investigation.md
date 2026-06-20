# Silent I7 Plugins Investigation

**Date:** 2026-06-19
**Status:** ECL gate removal DONE — backfill re-run needed; 2 remaining items

## What Was Done

HMM regime gates removed from all 16 I7 plugin detection paths (commits 3cf105e6 + ac93a2f3, pushed).
Root cause confirmed: backfill data shows 96.2% ranging (`hmm_prob_ranging=0.962`), so
`hmm_trending_weight=0.025 < 0.30` blocked essentially all bars for 12+ plugins.

Plugins fixed: microstructure_utils (OFISpike/CVDSpike), momentum_breakout, lvn_breakout,
vwap_reclaim, failed_breakout, ofi_divergence, candlestick_pattern_setup, orb15, orb30,
liquidity_hunt, delta_exhaustion, dual_divergence, session_extremes_setup, vwap_deviation,
second_leg_continuation, vcp.

4 unit tests skipped (were validating the removed gate behavior).
All 4876 unit tests pass.

## Remaining Items — RESOLVED (2026-06-19)

### 1. trad_RegimeTransition — CLOSED (threshold correct)

`cp_probability` p50=0.009, max=0.853. The 0.5 threshold correctly selects only the
highest-conviction changepoints (2 fires in 474K bars is proportionally correct).
The 2 observed fires had cp_probability 0.575-0.601 — confirmed genuine events.
No change needed.

### 2. trad_AnchoredVWAPReversion — FIXED (commit bb4e57f8)

Root cause was NOT sigma_min threshold. Premature state clearing in all no_signal()
paths meant departure_sigma wiped before VWAP cross happened on subsequent bar.
Fix: departure state persists until episode resolves. Also removed HMM gate (ECL).
sigma_min lowered 1.5→1.0 (APR updated) to match observed p50=1.04 distribution.

## Verify After Backfill Re-run

Plugins expected to now fire (were previously silent):
- trad_MomentumBreakout, trad_LVNBreakout, trad_VWAPReclaim, trad_FailedBreakout
- trad_SecondLegContinuation, trad_CandlestickPatternSetup, trad_VCP
- trad_OFISpike, trad_CVDSpike, trad_OFIDivergence, trad_DualDivergence
- trad_LiquidityHunt, trad_DeltaExhaustion, trad_SessionExtremesSetup, trad_VWAPDeviation

Plugins expected to remain zero/rare (architecture, not bugs):
- trad_ORB15 / trad_ORB30: session-only (RTH 09:30-11:30 ET) — CORRECT-RARE
- trad_CrossAssetDivergence: requires live cross-asset service state — architectural

## Re-run Command

```bash
nohup .venv/bin/python -u production/scripts/run_historical_pipeline.py \
  --replay-only --overwrite-features --include-rolled --workers 8 \
  > /tmp/backfill_clean.log 2>&1 &
```

Check signal counts after:
```sql
SELECT setup_plugin, COUNT(*) as fires
FROM signal_events
GROUP BY setup_plugin
ORDER BY fires DESC;
```
