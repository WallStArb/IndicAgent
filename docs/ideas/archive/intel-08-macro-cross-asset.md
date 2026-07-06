# Macro & Cross-Asset Intelligence — Improvement Backlog

**Version:** 1.0.0
**Status:** draft
**Priority:** medium
**Milestone:** future (post-v2.10)
**Last Updated:** 2026-06-14
**Tags:** macro, cross-asset, ftq, yield-curve, feature-store, i4-context, intelligence

---

## Implementation Status (2026-06-14 Audit)

**Overall: ~40% complete**

| Priority | Item | Status | Notes |
|----------|------|--------|-------|
| **P1a** | Join macro fields into `intelligence_features` | ❌ Blocked | `feature_writer.py` doesn't subscribe to `topic_macro_signals`. Fields flow to I7 but never reach DB. |
| **P1b** | Add thin I4 plugins | ✅ Complete | `MacroContextPlugin` live, registered, outputs all 5 fields to I4Context. |
| **P2a** | `setup_performance` regime slicing | ❌ Not started | Awaiting P1a. |
| **P2b** | I7 gating by macro regime | ❌ Not started | Awaiting P1a+P2a. Shadow-only required. |
| **P3a** | Stock-bond correlation service | ❌ Not started | Awaiting P1+P2 signal validation. |
| **P3b** | VX term structure service | ❌ Not started | Data availability verification required. |

**Data path working:** `topic_macro_signals` → `IntelligencePipeline` → `frames["cross_asset"]` → `MacroContextPlugin` → `I4Context` → I7 plugins + ML shadow capture

**Missing link:** `feature_writer.py` needs `topic_macro_signals` subscription to persist macro fields to `intelligence_features.market_context` for historical analysis.

---

## Background

Macro compute and cross-asset are standalone enrichment services (separate systemd units), not
I-tier plugins. This is architecturally correct: both require simultaneous multi-symbol windows
(ES + NQ + RTY + YM; ZT + ZB; SPY + TLT), which a per-symbol per-bar plugin cannot provide.

The current gap is not computation — the signals are already being computed and persisted to
`macro_features`. The gap is downstream consumption:

- `ftq_score`, `yield_curve_slope`, `yield_curve_regime`, `ftq_regime`, `corr_z` all land in
  `frames["cross_asset"]` via `CacheManager.update_macro()` but no plugin reads them
- They are not in `I4Context` — no slots, no schema fields
- They are not joined into `intelligence_features` — cannot be used in ML training
- They cannot be retrospectively analyzed against signal PnL in `signal_ledger`

Renaissance framing: the data exists but is not labeled against outcomes. Every bar is a wasted
training sample.

---

## Priority 1 — Wire Existing Signals (Narrow, ~2-3 days)

The highest-leverage fix. No new services, no new computation.

### 1a. Join macro fields into `intelligence_features`

`feature_writer_service` writes `intelligence_features` per bar. Currently it ignores
`macro_data` from `CacheManager`. Add `ftq_score`, `ftq_regime`, `yield_curve_slope`,
`yield_curve_regime`, and `corr_z` (from cross-asset) as JSONB sub-fields or top-level
nullable columns in the `intelligence_features` row for each bar.

This immediately labels every bar with its macro context. Retrospective analysis and ML
training become possible.

### 1b. Add thin I4 plugins for macro fields

Two new plugins that read pre-computed values from `frames["cross_asset"]` (already injected
by `FeaturePipelineExecutor` at line 195) and surface them into `I4Context`. No computation
in the plugin — the services do the work.

**`FTQContext` plugin (I4):**
- Reads: `frames["cross_asset"].get("ftq_score")`, `frames["cross_asset"].get("ftq_regime")`
- Outputs: `ftq_score: float | None`, `ftq_regime: str | None`
- Returns `{}` when `ftq_score` is None (service warming up)
- Pattern: identical to `CrossAssetContext` (which reads `eq_spread_z`)

**`YieldCurveContext` plugin (I4):**
- Reads: `frames["cross_asset"].get("yield_curve_slope")`, `.get("yield_curve_regime")`
- Outputs: `yield_curve_slope: float | None`, `yield_curve_regime: str | None`
- Returns `{}` when slope is None

**`CorrZContext` plugin (I4):**
- Reads: `frames["cross_asset"].get("corr_z")`
- Outputs: `corr_z: float | None`
- Already computed by cross-asset service per (base, tf) — pick current instrument's value

**`I4Context` schema additions:**
```python
# FTQContext
ftq_score: float | None = None
ftq_regime: str | None = None

# YieldCurveContext
yield_curve_slope: float | None = None
yield_curve_regime: str | None = None

# CorrZContext
corr_z: float | None = None
```

Register all three in `register_plugins.py` `TIER_I4` list and `TIER_I4_NAMES`.

---

## Priority 2 — Regime Segmentation (~1 day)

Once macro fields are in `I4Context` and flowing through `IntelligenceEvent` → `signal_ledger`,
segment signal performance by macro regime.

### 2a. `setup_performance` regime slicing

The `setup_performance` table already tracks per-setup rolling 30d stats. Add a
`macro_regime` composite column (or query filter) combining `yield_curve_regime` and
`ftq_regime` so win rates are computed per regime bucket:

```
(steepening, risk_on)  → aggressive setups viable
(inverted, risk_off)   → suppress longs, favour short or flat
(normal, neutral)      → baseline stats
```

### 2b. I7 signal gating by macro regime

In signal quality scoring (I6 CTF confluence), inject macro regime as a weight modifier:

- `ftq_regime == "risk_off"` → reduce long signal confidence by configurable factor
- `yield_curve_regime == "inverted"` → increase regime suppression probability
- Do not hardcode thresholds — expose as settings, shadow-validate before promoting

Renaissance principle: earn the right through proof. Run shadow-only for ≥100 signals before
any live gating.

---

## Priority 3 — New Enrichment Services (Broad, ~3-4 days)

### 3a. Stock-Bond Correlation Service

**Why:** Rolling ES vs ZB correlation is among the most reliable macro regime signals.
Correlation breaks (historically stable relationship flipping sign) are regime transition
events. Currently ES and ZB are tracked in separate services; their correlation is never
computed.

**Architecture:** New standalone service (`stock_bond_correlation_agent`) following
`cross_asset_service.py` pattern:
- Subscribe to `topic_intelligence`
- Maintain rolling 30-bar, 60-bar, 90-bar close windows for ES (base) and ZB
- Compute Pearson correlation per window
- Compute rolling mean/std of correlation history → z-score of current correlation
- Detect sign flips: correlation crossing zero is a regime event → publish alert
- Publish to new topic `topic_stock_bond_correlation`
- `CacheManager` picks up and injects into `frames["cross_asset"]`

**Output fields:**
```python
sb_corr_30: float       # 30-bar rolling Pearson r (ES vs ZB close)
sb_corr_60: float       # 60-bar
sb_corr_z: float        # z-score vs trailing 90-bar history
sb_corr_regime: str     # "positive", "negative", "breaking" (z > 2.0 sign change)
```

**New I4 plugin:** `StockBondCorrContext` reading `frames["cross_asset"]` for these fields.

### 3b. VX Term Structure Service

**Why:** VIX futures contango/backwardation is a distinct signal from VIX level. Contango
(front < back) = complacency. Backwardation (front > back) = fear/demand for near-term
protection. Transitions are higher-signal than level.

**Requires:** VX front-month and VX back-month both subscribed via IBKR. Currently VX is in
`MACRO_ACTIVE_SYMBOLS` but only as a single contract. Need to track two contract months
simultaneously.

**Architecture:** Extend `macro_compute_agent` or new service:
- Track rolling windows for VX_FRONT and VX_BACK separately
- Compute `term_slope = VX_BACK_close - VX_FRONT_close` (positive = contango)
- Compute rolling z-score of slope
- Detect transitions: contango → backwardation crossings

**Output fields:**
```python
vx_term_slope: float     # back - front price spread
vx_term_z: float         # z-score vs trailing history
vx_term_regime: str      # "contango", "backwardation", "transitioning"
```

**Note:** Implementation depends on IBKR providing both contract months with sufficient
liquidity. Verify data availability before committing to this.

---

## Priority 4 — Deferred / Research Quality

These are lower confidence or require external data not currently subscribed.

- **Real yields** — TIP ETF vs TLT spread. Requires TIP subscription.
- **Credit spread** — HYG vs LQD. Requires both subscriptions. High signal quality but
  ETF liquidity on 1m bars may be thin.
- **Macro-implied fair value** — regression of ES price ~ yield_curve_slope + ftq_score +
  vix_level → residual as "overvalued vs macro" signal. Non-stationary relationship; must
  be walk-forward validated before use. High complexity, moderate expected signal.
- **Intra-index dispersion** — cross-sectional realized vol of ES/NQ/RTY/YM. Data already
  exists in cross-asset service windows; just not computed. Add to `compute_eq_index_features`.
- **USD strength** — already stubbed in `MACRO_FX_PAIRS` constants, deferred since Phase 64.
  FX bars via IBKR have liquidity concerns on 1m bars.

---

## Implementation Order

When this work is scheduled as a phase:

1. Priority 1a (intelligence_features join) — unlocks retrospective analysis immediately
2. Priority 1b (I4 plugins) — unlocks I6/I7 consumption and LLM prompt enrichment
3. Priority 2a (setup_performance segmentation) — data-driven regime validation
4. Priority 2b (I7 gating, shadow-only) — earn the right through proof
5. Priority 3a (stock-bond correlation service) — after 1+2 prove macro fields have signal
6. Priority 3b (VX term structure) — verify data availability first

Shadow governance applies to all new gating logic: `n >= 100` signals before promotion,
`bootstrap_ci_lower(pnl_r) > 0.0` threshold unchanged.

---

## Files Affected (when implemented)

| File | Change |
|------|--------|
| `src/intelligence/schemas.py` | Add 5 fields to `I4Context` |
| `src/intelligence/context/ftq_context.py` | New plugin |
| `src/intelligence/context/yield_curve_context.py` | New plugin |
| `src/intelligence/context/corr_z_context.py` | New plugin |
| `src/intelligence/register_plugins.py` | Register 3 new plugins in TIER_I4 |
| `services/feature_writer_agent.py` | Join macro fields into intelligence_features |
| `src/intelligence/pipeline/cache_manager.py` | Expose macro fields in CacheSnapshot |
| `services/stock_bond_correlation_agent.py` | New service (Priority 3a) |
| `src/core/stream_keys.py` | New topic: `topic_stock_bond_correlation` |
| `production/systemd/` | New unit file for stock-bond service |
