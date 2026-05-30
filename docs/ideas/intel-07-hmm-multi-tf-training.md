# HMM Regime — Multi-Timeframe Design & Training Pipeline

**Version:** 1.0.0
**Status:** draft
**Priority:** high
**Milestone:** future (post-v2.8)
**Last Updated:** 2026-03-23
**Tags:** hmm, regime, multi-timeframe, training, em-algorithm, signal-gating, intelligence

---

## Context

The current `smc_HMMRegime` plugin has two structural gaps beyond operational bugs:

1. **Single timeframe (1m only)** — all higher-TF signals consume the wrong regime context
2. **Untrained parameters** — emission means/variances are hand-tuned priors, never fitted to data

These are separate problems with separate fixes, but they're closely related and should be
planned together.

---

## Gap 1: Wrong Regime Context for Higher Timeframes

### The Problem

`HMMRegimePlugin` hardcodes `InputSpec(symbol=".*", timeframe="1m", lookback=200)`.

- 200 × 1m bars = ~3.3 hours of market context
- A 1h signal generator consumes this same 1m HMM output
- The regime question for a 1h setup is "what has price been doing for the past several days"
  — not "what has price been doing for the past 3 hours"

| Signal TF | Current regime context | What it should be |
|-----------|----------------------|-------------------|
| 1m | 200 bars × 1m = 3.3h | Correct |
| 5m | 200 bars × 1m = 3.3h | 200 × 5m = ~16h (2 sessions) |
| 15m | 200 bars × 1m = 3.3h | 200 × 15m = ~50h (2.5 days) |
| 1h | 200 bars × 1m = 3.3h | 100 × 1h = ~10 days |

A 1h FVG fill setup being filtered by a 1m regime classifier is structurally wrong.
The 3.3h HMM might say "ranging" while the 10-day 1h structure is clearly in a trend.

### The Fix: Per-TF HMM Instances

Run one HMM per timeframe, each with a TF-appropriate lookback:

```
smc_HMMRegime_1m   — InputSpec(timeframe="1m",  lookback=200)  → ~3.3h
smc_HMMRegime_5m   — InputSpec(timeframe="5m",  lookback=200)  → ~16h
smc_HMMRegime_15m  — InputSpec(timeframe="15m", lookback=150)  → ~37h
smc_HMMRegime_1h   — InputSpec(timeframe="1h",  lookback=100)  → ~10 days
```

Output field names stay identical (`hmm_regime`, `hmm_regime_prob`, etc.) — each TF's
feature dict gets its own regime context. I7 plugins on 5m bars consume the 5m HMM output,
not the 1m HMM output.

**Implementation approach:**
- Parameterize `HMMRegimePlugin` with a `timeframe` field
- Register 4 instances in `TIER_I6` (or new `TIER_I4` placement — see below)
- Each instance's `InputSpec` targets its own TF
- Output keys could remain identical since each plugin runs in its own TF frame context

**Placement question:** Currently in I6 SMC tier. Multi-TF instances are more naturally I4
(context/regime classification), not SMC. Could move the 1m instance to I4 and add the
others alongside it. Low priority decision — either works.

---

## Gap 2: Untrained Parameters

### The Problem

`config/hmm_parameters.json` does not exist. The plugin runs on `_DEFAULT_TRANSITION`,
`_DEFAULT_MEANS`, `_DEFAULT_VARIANCES` — hand-crafted values that represent reasonable
priors about what futures regime observation vectors should look like, but have never been
validated or fitted to actual IndicAgent market data.

What this means in practice:
- Regime boundaries are approximate — the HMM may mislabel trending periods as ranging
  (or vice versa) because the emission parameters don't reflect actual ES/NQ/RTY behavior
- The 2D vs 5D fallback compounds this: the 5D parameters were designed together; the 2D
  slice has different statistical properties that were never explicitly calibrated
- `regime_entropy` and `hmm_regime_velocity` (see `regime-transition-early-detection.md`)
  become much more meaningful once the model knows what "high confidence trend" actually
  looks like in the data

### The Fix: Baum-Welch Training on `intelligence_features`

The `intelligence_features` hypertable is the training dataset. Once 30+ days of clean data
accumulates:

1. Pull historical bars with `rsi_14`, `adx_14`, `atr_14`, `macd_histogram_12_26_9`,
   `close` for each active symbol and TF
2. Build observation sequences (5D vectors) from the same `_build_observation()` logic
3. Run Baum-Welch (EM) via `hmmlearn.GaussianHMM` or equivalent to find ML parameters
4. Validate learned parameters make semantic sense (state 1 should have positive returns
   and high ADX; state 0 should have near-zero returns and low ADX)
5. Write to `config/hmm_parameters.json` — existing plugin loads it automatically
6. Per-TF instances get per-TF parameter files: `config/hmm_parameters_1m.json`, etc.

**Training cadence:** Not continuous. Retrain quarterly or when market structure changes
(volatility regime shift, correlation breakdown). This is not a realtime learning system —
it's periodic parameter updates like how Renaissance recalibrates models.

**Validation approach:**
- Hold-out set: train on first 20 days, validate on last 10
- Metric: does learned regime correlate with realized volatility clusters?
- Sanity check: do trending regimes coincide with high-conviction I7 signal outcomes?

### Dependency

Requires `intelligence_features` to be populated and stable — at minimum 30 days of clean
multi-symbol data across all active TFs. **This is why this is a v2.3 candidate**, not
something to rush. Training on 3 weeks of data produces overfit parameters.

---

## Interaction with Regime Transition Detection

See `regime-transition-early-detection.md`. The `regime_entropy` and `hmm_regime_velocity`
fields proposed there become significantly more useful once:

1. Each TF has its own HMM (so 1h entropy reflects 1h structure, not 1m noise)
2. Parameters are trained (so the entropy thresholds mean something calibrated)

The transition detection idea is worth shipping on 1m first with current parameters.
Multi-TF + training unlocks it properly for higher TFs.

---

## Implementation Scope (when ready to plan)

**Phase A — Multi-TF HMM (no training required):**
1. Parameterize `HMMRegimePlugin` with `timeframe: str` and `lookback: int`
2. Register 3 additional instances for 5m, 15m, 1h in `TIER_I6` (or I4)
3. Update `TIER_I6` tier list in `register_plugins.py`
4. Each instance uses same default parameters initially — still better than 1m-for-all
5. Test: verify 1h signal generator receives `hmm_regime` from 1h HMM, not 1m

**Phase B — Training pipeline (v2.3, after 30+ days data):**
1. Write `scripts/train_hmm_parameters.py` — reads `intelligence_features`, fits model,
   writes per-TF `config/hmm_parameters_<tf>.json`
2. Update plugin to load TF-specific parameter file if present
3. Add training run to post-milestone housekeeping checklist
4. Validate: query regime distributions before/after and confirm semantic alignment

---

## v2.1 Data Quality Caveat (Phase 54 Concern)

Phase 49.1 will begin writing `regime_type_at_fire` to `signal_ledger` for all signals.
That data will reflect the current HMM architecture: all TFs (1m, 5m, 15m, 1h) computed
from 200 × 1m bars. So when Phase 54 ML scoring segments by `(plugin, regime_type, tf)`,
the "15m trending" and "1m trending" buckets both reflect ~3.3h of 1m context, not
structurally different regime windows.

This doesn't invalidate the Phase 49.1 data collection — regime labels are still better
than NULL, and 1m-based regime is a reasonable proxy. But Phase 54 planning should note
this caveat when interpreting regime-segmented IC scores. Multi-TF HMM (Phase A above)
should ideally ship before Phase 54 to give the ML layer meaningful regime differentiation.

---

## Open Questions

1. **Should parameters differ per symbol?** ES and CL have different vol regimes.
   Per-symbol training is theoretically better but multiplies parameter files.
   Start with per-TF only; add per-symbol if regime mislabeling is measurable.

2. **3 states vs 4 states?** Adding a "transition" state explicitly is appealing
   (see `regime-transition-early-detection.md`) but changes the output schema.
   Could be trained in as a 4th state rather than derived post-hoc from entropy.
   Evaluate after Phase A ships and transition detection is validated.

3. **Lookback for higher TFs:** 200 bars for 1m is ~3.3h. What's right for 1h?
   Too short (50 bars = 2 days) and regime flips on every news event.
   Too long (500 bars = 3 weeks) and regime detection lags structural changes.
   Suggested starting points: `{1m: 200, 5m: 200, 15m: 150, 1h: 100}`.
