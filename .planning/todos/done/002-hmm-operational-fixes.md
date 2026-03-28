---
created: 2026-03-23T00:00:00.000Z
updated: 2026-03-28T00:00:00.000Z
title: HMM operational fixes — observability, fallback logging, warm-up
area: intelligence
priority: 2
tier: immediate
files:
  - src/intelligence/smart_money/hmm_regime.py
---

## Architecture Context

**How the HMM gates signals (read this first):**

`smc_HMMRegime` is the sole binary gate for all I7 signals. The path is:

```
HMMRegimePlugin (I6) → IntelligenceEvent.smc.hmm_regime
  → signal_generator_agent._regime_cache[symbol][tf]
  → aggregate(regime_data=_regime_cache[symbol][authority_tf])
  → _regime_gate_signals() → regime_eligible=True/False
```

`_REGIME_AUTHORITY_TF` in `services/signal_generator_agent.py` maps each signal TF to a
higher TF's regime: `{1m→5m, 5m→15m, 15m→1h, 1h→4h}`. The intent is slow-clock
gating — 1m signals are gated by the 5m HMM regime, not the noisy 1m regime.

**Critical gap:** The HMM declares `InputSpec(symbol=".*", timeframe="1m", lookback=200)`.
This means when the feature pipeline runs the HMM for a 5m or 15m bar, it fetches
200 bars of **1m** history regardless of which TF event triggered it. So the "5m
regime" and "15m regime" stored in `_regime_cache` are both computed from the same
200 × 1m bars (~3.3h of context). The slow-clock temporal separation is real (5m
cache is older than 1m cache) but the structural separation is not — a 1h signal
being gated by "1h regime" is still just 3.3h of 1m data. This is a separate issue
tracked in `docs/ideas/hmm-multi-tf-and-training.md` (multi-TF HMM instances).

**Untrained parameters:** `config/hmm_parameters.json` does not exist. The plugin
runs on hardcoded defaults never fitted to actual market data. All regime labels
are approximate. This is also tracked in `docs/ideas/hmm-multi-tf-and-training.md`.

---

## Problem

Three operational bugs in `HMMRegimePlugin` that are fixable without training or
multi-TF changes:

**1. Silent 2D fallback**
`_resolve_dims()` silently drops to 2D (log_return + realized_vol only) when any of
`rsi_14`, `adx_14`, `atr_14`, `macd_histogram_12_26_9` is missing from the features dict.
The 2D observation uses sliced columns of a 5D-designed parameter matrix — not independently
calibrated for 2D. There is no log, metric, or indicator that this fallback is active.
When running in 2D mode the gate may fire on significantly weaker regime signal.

**2. No observability on which mode is running**
No metric or log field records `n_dims` per bar. You cannot tell from `intelligence_features`
or service logs whether the HMM ran in 2D or 5D mode on a given bar. Without this, you
cannot know how much of the gating history is based on degraded input.

**3. compute_full cold-start warm-up noise**
`compute_full` resets to a uniform prior via `_reset_state()`. The first ~20 bars post-reset
(service restart, symbol switch) produce prior-convergence noise that downstream plugins treat
as real regime signal. `regime_gate` suppresses signals when `hmm_regime_prob < 0.30` — but
during warm-up, all three state probabilities are near 0.33 and `hmm_regime_prob ≈ 0.33`,
which passes the 0.30 floor, meaning warm-up noise propagates through the gate unchecked.

## Solution

1. Add `structlog` warning when `_resolve_dims` returns 2 — log which field(s) were missing
2. Add `hmm_n_dims` to plugin output (value: 2 or 5) so `intelligence_features` records
   which mode ran — enables downstream filtering and audit queries
3. Add `hmm_warmed_up: bool` output field — False for first N bars after `_reset_state()`,
   True once `regime_duration >= min_lookback`. Downstream consumers can gate on this.
4. During warm-up (`hmm_warmed_up=False`), emit `hmm_regime_prob = 0.0` so the 0.30
   floor in `regime_gate` correctly suppresses signals rather than passing warm-up noise
