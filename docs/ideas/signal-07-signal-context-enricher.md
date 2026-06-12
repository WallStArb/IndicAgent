# Signal-ContextEnricher

**Version:** 1.2
**Status:** draft
**Last Updated:** 2026-06-12

---

## 1. Purpose

Defines the design for `SignalContextEnricher` and its position as Phase 1 of a planned collapse
of the confidence transform chain into a single unified `SignalRanker` model.

The immediate goal: recover the relationship between extrinsic context features and signal quality
that was stripped from I7 confidence formulas during the v2.9 Signal Quality Renaissance — without
re-contaminating `raw_confidence`. The enricher builds the feature infrastructure and
`context_multipliers` table that the eventual `SignalRanker` will consume.

The end state: replace the entire transform chain (calibrator + enricher + `perf_multiplier` +
ToD adjuster) with one end-to-end trained ranking model. Every current component in the chain is
approximating a piece of the same function — `P(pnl_r > 0 | raw_confidence, setup_plugin, tf,
symbol, context_features)` — using separate methods, trained on the same target, applied
sequentially. Sequential layers with correlated inputs trained independently introduce compounding
error and opacity. One model trained on all inputs simultaneously is strictly better.

`SignalContextEnricher` is the scaffold, not the destination.

Prerequisite: the v2.9 pass must be complete and all 29 non-exempt I7 plugins must follow the
6 GOOD patterns (`docs/architecture/i7-setup-confidence-patterns.md`). The enricher is meaningless
if `raw_confidence` is still contaminated by extrinsic factors. The 8 plugins in `_I7_I6_EXEMPT`
(`src/intelligence/register_plugins.py`) must complete their Phase 122 strip before their signals
can contribute meaningful training data to either the enricher or the eventual `SignalRanker`.

---

## 2. Design Principles

### The core separation

`raw_confidence` answers one question: **how strong is this pattern in the price/volume/microstructure
data right now?** It is immutable after I7 fires and must never carry regime state, I6 confluence
scores, exhaustion indicators, or zone context. Those are extrinsic — computed by separate plugins
running in parallel, not derivable from the pattern's own detection logic.

The test: if the feature is emitted by a different plugin, it is extrinsic. If it is derived from
the same raw market data the plugin's detection logic directly consumes, it is intrinsic.

The v2.9 audit found four categories of extrinsic leakage hard-coded into confidence formulas
across 21 plugins:

1. **HMM regime weights** — `hmm_regime_weight()` as additive trim or composite component
2. **I6 CTF scores** — `ctf_score`, `ctf_structure_alignment`, `ctf_trend_alignment`
3. **Exhaustion state** — `apply_exhaustion_boost` / `apply_exhaustion_guard` from I4
4. **Zone context** — supply/demand zone membership and strength

All four were stripped in v2.9. The data is preserved — it travels with every signal via
`capture_signal_features()`. What was intentionally removed is the *assumed* relationship between
these features and signal quality. That relationship should be learned from outcomes, not encoded
as priors.

### Why priors are wrong

Hard-coded modifiers assume the relationship is stationary, direction-fixed, and setup-agnostic.
None of these holds. Exhaustion may help reversal setups and harm continuation setups. CTF alignment
may matter in trending regimes and be irrelevant in ranging regimes. The enricher discovers these
interactions empirically with bootstrap confidence intervals.

### `raw_confidence` is immutable — the enricher produces a ranking score, not a replacement

`SignalContextEnricher` writes `adjusted_confidence` — a separate column. `raw_confidence` is
never modified after I7 fires. It is the plugin's first-class intrinsic assessment, a signal fed
*into* the learned model, not overwritten by it. All ML training, shadow governance promotion, and
plugin-level diagnostics use `raw_confidence`. The enricher's output is a ranking instrument, not
a redefinition of pattern quality.

### Multipliers are gated by evidence — threshold aligned with shadow governance

No multiplier is active until `n >= 100` observations in its bucket and
`bootstrap_ci_lower(multiplier) > 1.0` (or `< 1.0` for penalty multipliers). This matches the
shadow governance promotion gate for plugin graduation (`src/intelligence/register_plugins.py`,
`_I7_I6_EXEMPT` docstring). Using a lower threshold without a statistical power justification is
a silent bias risk — context buckets accumulate sample at a different rate than plugins, but the
evidence bar is the same. Cold-start: all multipliers = 1.0, `adjusted_confidence = raw_confidence`.
The enricher is a no-op until evidence earns it the right to act.

Multiplier caps are derived from the empirical distribution of effects at first training, not set
by prior. Initial implementation may use `[0.5, 1.5]` as a conservative starting bound, but this
should be revisited after the first 1000 bucket-observations and tightened or widened to match
the data.

### The transform chain collapses into one model

The current chain applies four sequential learned adjustments to produce a ranking score:

```
raw_confidence
  → calibrator        (isotonic regression per plugin+tf+symbol)
  → enricher          (context multipliers per plugin+feature+bucket)
  → perf_multiplier   (Sharpe rank from setup_performance)
  → ToD adjuster      (time-of-day multiplier)
  → adjusted_rank     (used by aggregator)
```

Each stage was trained independently, ignoring the others, on the same target variable (`pnl_r`).
This is statistically equivalent to fitting correlated factors in a model you pretend are orthogonal.
The compounding error is not bounded.

The correct formulation is one model:

```
P(pnl_r > 0) = SignalRanker(raw_confidence, setup_plugin, tf, symbol,
                              hmm_state, ctf_score, exhaustion_state,
                              zone_context, time_of_day, ...)
```

`SignalContextEnricher` builds the feature infrastructure — the `context_multipliers` table,
the feature extraction path, the governance machinery — that `SignalRanker` will consume directly.
Once `SignalRanker` is trained and shadow-validated, the four-table chain is deprecated. The phase
plan for `SignalRanker` is deferred; the enricher is its precondition.

**`perf_multiplier` compounding while both exist:** until `SignalRanker` is built, the enricher
and the `perf_multiplier` will coexist. They must not both be active on the same signal. When the
enricher's first bucket reaches promotion, disable the `perf_multiplier` pass in the ranker for
that plugin. The ranker's `perf_multiplier` path remains active only for plugins with no promoted
enricher buckets. This is tracked per-plugin via a flag in `setup_performance` or `context_multipliers`.

---

## 3. Architecture

```
I7 plugins → raw_confidence (intrinsic, immutable after this point)
    │
    ▼
SignalContextEnricher  (in-process, post-I7, pre-calibrator)
    reads:    signal.setup_plugin + full feature vector
    looks up: context_multipliers (DB-loaded, refreshed every 30 min via CacheManager
              — same cadence as calibration_curves; nightly ml-training writes the table)
    writes:   adjusted_confidence = raw_confidence * product(active_multipliers)
    │
    ▼
Calibrator  (isotonic regression; operates on adjusted_confidence, not raw_confidence)
    writes:   calibrated_confidence
    │
    ▼
Aggregator  (CISScorer + perf_multiplier + ToD + regime gate)
    ranks on: calibrated_confidence
    writes:   was_selected, composite_rank, perf_multiplier, cis_score
    │
    ▼
signal_ledger
    stores:   raw_confidence, adjusted_confidence, calibrated_confidence
              (all signals written — not just winner; was_selected=True on winner only)

Future: SignalRanker replaces calibrator + enricher + perf_multiplier + ToD adjuster entirely.
        raw_confidence remains; ranking_score replaces calibrated_confidence at that point.
```

`SignalContextEnricher` is an in-process wave inside `IntelligencePipeline` — no new service,
no new Kafka topic. It slots between the I7 compute pass and the calibrator call inside
`SignalProcessor.process` (`src/intelligence/pipeline/signal_processor.py`).

**Pipeline position is load-bearing:** the calibrator must operate on `adjusted_confidence`, not
`raw_confidence`. A calibrator trained on `raw_confidence` learns a curve that ignores context;
when context multipliers shift `adjusted_confidence`, the calibrated output is wrong. Calibration
curves must be re-fit against `adjusted_confidence` after the enricher is active — the existing
curves become stale and must be reset at enricher activation.

---

## 4. Data Contracts

### `context_multipliers` table (new — migration required)

| Column | Type | Description |
|---|---|---|
| `setup_plugin` | `text` | Plugin name matching `signal_ledger.setup_plugin` |
| `context_feature` | `text` | Feature key from `capture_signal_features()` output |
| `bucket` | `text` | Bucket label, e.g. `LOW`, `MED`, `HIGH` or decile `D1`–`D10` |
| `multiplier` | `float8` | Capped to `[0.5, 1.5]`; 1.0 = no effect |
| `pnl_r_mean` | `float8` | Mean pnl_r for signals in this bucket |
| `n` | `int4` | Observation count |
| `bootstrap_ci_lower` | `float8` | 95% CI lower bound on multiplier |
| `bootstrap_ci_upper` | `float8` | 95% CI upper bound on multiplier |
| `active` | `bool` | True when promotion gate passed |
| `updated_at` | `timestamptz` | Last nightly update |

### `signal_ledger` changes (migration required)

New column `adjusted_confidence float8` — populated by `SignalContextEnricher` at pipeline
time. Null when enricher is not yet active (pre-build). `raw_confidence` and
`calibrated_confidence` columns are unchanged (`\d signal_ledger` as of migration 095).

### Candidate context features

These are the exact extrinsic features stripped from I7 confidence formulas during v2.9. Each is
a candidate multiplier input. The enricher learns empirically which matter per setup type.

**HMM regime probability**

| Feature key | Candidate for | Prior max distortion |
|---|---|---|
| `hmm_prob_trending_up` | `ofi_continuation`, `gap_analysis`, `cvd_divergence`, `momentum_breakout`, `squeeze_expansion`, `orb15`, `orb30`, `choch_reversal`, `liquidity_hunt`, `prev_day_level_test` | ±0.20 |
| `hmm_prob_trending_down` | same (short direction) | ±0.20 |
| `hmm_prob_ranging` | `failed_breakout`, `supply_demand_setup`, `liquidity_sweep_reclaim`, `ofi_divergence`, `prev_day_level_test` | ±0.20 |

**I6 CTF confluence scores**

| Feature key | Plugin | Prior formula | Prior max effect |
|---|---|---|---|
| `ctf_score` | `ofi_continuation`, `cvd_divergence` | `+0.15 * min(1.0, ctf/0.7)` if `\|ctf\| > 0.3` | +0.15 |
| `ctf_score` | `liquidity_sweep_reclaim`, `supply_demand_setup` | `+0.05 * min(2.0, ctf/0.5)` if `\|ctf\| > 0.3` | +0.10 |
| `ctf_structure_alignment` | `choch_reversal` | `+0.08 * min(1.0, ctf_struct/0.7)` if `> 0.3` | +0.08 |
| `ctf_trend_alignment` | `choch_reversal` | `+0.06 * min(1.0, ctf_trend/0.7)` if `> 0.3` | +0.06 |
| `ctf_score` | `trend_following` | `0.20 * min(1.0, \|ctf\|)` in composite | 20% of raw_conf |
| `ctf_score` | `liquidity_hunt` | `+0.05` if `\|ctf\| > 0.3` and directionally aligned | +0.05 |

Note: `choch_reversal` stacked all three CTF components — prior combined distortion up to +0.19 on
a single signal. `trend_following` was the structural worst case: CTF was 20% of the composite
formula, not an additive trim.

**Exhaustion state**

| Feature key | Plugin | Variant | Prior effect |
|---|---|---|---|
| `exhaustion_score`, `exhaustion_side` | `supply_demand_setup`, `liquidity_sweep_reclaim`, `liquidity_hunt`, `prev_day_level_test` | boost (reversal direction confirms) | +0.10 |
| `exhaustion_score`, `exhaustion_bars` | `momentum_breakout`, `squeeze_expansion`, `trend_following` | guard (`exhaustion_score > 0.7` and `exhaustion_bars >= 3`) | -0.15 |

**Zone context**

| Feature key | Plugin | Condition | Prior effect |
|---|---|---|---|
| `supply_strength` | `momentum_breakout`, `trend_following` | long into supply zone | up to -0.12 |
| `demand_strength` | `momentum_breakout`, `trend_following` | short into demand zone | up to -0.12 |
| `supply_strength`, `demand_strength` | `liquidity_hunt` | directionally aligned / opposing | +0.05 / -0.10 |

**SMC layer outputs (found only in `liquidity_hunt`)**

A fifth category — I5/SMC event flags used as confidence boosts. Same tier boundary violation as
CTF, one layer lower. Combined prior maximum distortion on a single `liquidity_hunt` signal: +0.35
from SMC alone.

| Feature key | Condition | Prior effect |
|---|---|---|
| `fvg_type` | equals signal direction | +0.08 |
| `ob_type` | equals signal direction | +0.06 |
| `choch_detected` | `== 1.0` | +0.10 |
| `bos_detected`, `bos_direction` | detected and directionally aligned | +0.05 |
| `price_in_premium` | discount-aligned long or premium-aligned short | +0.06 |

---

## 5. Build Scope

1. Resolve the `perf_multiplier` compounding decision (ADR in phase CONTEXT.md).
2. Migration: add `adjusted_confidence float8` to `signal_ledger`.
3. Migration: create `context_multipliers` table.
4. Implement `SignalContextEnricher` in `src/intelligence/pipeline/context_enricher.py`.
5. Wire into `IntelligencePipeline` between I7 compute and `SignalProcessor.process`.
6. Write `adjusted_confidence` on all signals in `all_ranked` (not winner only).
7. Add `adjusted_confidence` to `_INSERT_SYNC_TEMPLATE` in `run_historical_pipeline.py`.
8. Add nightly `context_multipliers` update pass to `ml-training` batch job.
9. Shadow governance: promote first multipliers once `n >= 100` per bucket (aligned with plugin shadow governance gate).
10. Reset calibration curves at enricher activation — existing curves were fit on `raw_confidence` and become stale once the calibrator operates on `adjusted_confidence`.
11. Once enricher is stable and `SignalRanker` design is ready, plan deprecation of calibrator + `perf_multiplier` + ToD adjuster chain.

---

## 6. Structural Defects Fixed in v2.9 (context for enricher design)

Two plugins had problems deeper than additive extrinsic modifiers that required special handling
during the v2.9 strip. These are not enricher candidates — they were structural bugs.

**`trend_following` — 55% of raw_conf was extrinsic**

`trend_regime` (I4 classifier output, 35% weight) and `ctf_score` (I6 output, 20% weight) made
the confidence value primarily a market-context score. Fixed in Phase 118: confidence redesigned
around `trend_strength` (Kalman trend magnitude), `trend_conf` (Kalman filter quality), and
`swing_pattern` (structural confirmation).

**`choch_reversal` — HMM boost was directionally inverted**

CHoCH is a structural reversal signal. The prior formula rewarded `hmm_prob_trending_up` for a
bullish CHoCH — inflating confidence when the market was already trending up, where the CHoCH is
*least* significant (minimal character change). This is not extrinsic leakage; it is a wrong prior.
Fixed in Phase 118: HMM boost removed entirely. The enricher will learn the correct HMM
relationship from outcomes without any directional prior encoded — if `hmm_prob_trending_up`
negatively predicts CHoCH pnl_r, the learned multiplier will reflect that without being told.

---

## 7. See Also

- `docs/architecture/i7-setup-confidence-patterns.md` — 6 GOOD patterns; prerequisite for enricher
- `src/intelligence/pipeline/signal_processor.py` — pipeline orchestration; enricher slots pre-calibrator
- `src/intelligence/pipeline/calibrator.py` — calibration curve pipeline; must be re-fit after enricher activation
- `src/intelligence/pipeline/ranker.py` — `perf_multiplier`; disabled per-plugin as enricher buckets promote
- `src/intelligence/pipeline/cache_manager.py` — `_load_calibration_curves` (30 min cadence); enricher uses same
- `src/intelligence/trading/aggregator.py` — `all_ranked` population; all signals written to ledger
- `src/intelligence/register_plugins.py` — `_I7_I6_EXEMPT` (8 plugins); must complete Phase 122 strip first
- `signal_ledger_full` view (migration 095) — join of `signal_ledger` + `signal_outcomes`
