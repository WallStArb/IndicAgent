# Phase 126: Signal Universe Hardening — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the four mechanical defects that make the clean replay (Phase 127) meaningless as ML training data: (1) 47.6% of signals stop at entry due to sub-ATR zone widths and stops calculated from zone edge rather than entry, (2) 8 signal-generation plugins are exempt from confluence annotation, (3) trad_FVGFill has a catastrophic 8.93% equity win rate from a structural entry-timing defect, and (4) several plugins have broken gate conditions (MeanReversion mutual-exclusion, zero-signal time-specific plugins). Also validates USDJPY data integrity before the replay consumes it as training data. This phase produces a corrected signal universe before any replay is run.

**Workstream position:** Phase 126 is the final data-quality gate in Workstream A (Phases 123-127). It runs after APR full migration (125) and before Clean Replay (127). No code in Workstreams B (128-130) depends on Phase 126 internals.

**Tech Stack:** Python/asyncpg, PostgreSQL/TimescaleDB, pytest, APR (config_schema/config_state), structlog/OTel.

---

## Factual Baseline (verified 2026-06-14)

`signal_ledger` contains 1,446,479 signals across 30 distinct plugins. TIER_I7 registers 36 plugins. Six registered plugins have never fired:

| Plugin | Status | Root cause |
|--------|--------|-----------|
| `trad_RegimeTransition` | In `_I7_I6_EXEMPT` | I6 integration missing; fixed by Wave 2 |
| `trad_PrevDayLevelTest` | In `_I7_I6_EXEMPT` | I6 integration missing; fixed by Wave 2 |
| `trad_CrossAssetDivergence` | In `_I7_I6_EXEMPT` | I6 integration missing; fixed by Wave 2 |
| `trad_SessionExtremesSetup` | NOT in exempt set | Session-specific (Asian→London transition); may be rarely-triggered, not broken |
| `trad_ORB15` | NOT in exempt set | Opening range breakout; fires only at RTH open |
| `trad_ORB30` | NOT in exempt set | Opening range breakout; fires only at RTH open |

The "13 zero-signal plugins" mentioned in earlier analysis docs (BreakoutPullback, ChiAdapted, etc.) do not exist in TIER_I7 or the trading directory — those names are phantom. The actual zero-signal set is 6, and 3 are fixed by Wave 2.

**Phase 124 onset-guard status (confirmed):** All 5 onset-guard offenders fixed and verified by fire-rate report. Fire rates: 0.12%-3.08% (target: single-digit). No onset-guard work needed in Phase 126.

---

## Root Crime Analysis

### Root Crime 1 — Universal Zone Width Bypass (47.6% stopped_at_entry)

**The problem is systemic, not confined to three fast paths.** Signal_ledger analysis (verified 2026-06-14) shows narrow zones across all zone source types:

| Plugin | N signals | Zone < $0.005 | Zone < $0.025 | Zone source |
|--------|-----------|--------------|--------------|-------------|
| trad_CVDDivergence | 112,579 | 65.9% | 80.3% | structural zone engine |
| trad_GapAnalysisSetup | 255,480 | 47.3% | 62.7% | structural zone engine |
| trad_AnchoredVWAPReversion | 142,979 | 46.5% | 71.9% | structural zone engine |
| trad_FVGFill | 61,816 | 31.8% | 60.7% | fvg fast path |
| trad_SupplyDemandSetup | 16,661 | (none) | 37.9% | supply/demand fast path |

`zone_engine.py` has `MIN_ZONE_WIDTH_ATR = 0.25` but it is not enforced on its output — the constant is used only in zone construction, not as a post-construction gate. The three fast paths in `_resolve_zone_bounds()` (supply/demand, fvg, ob) bypass it entirely. Plugins using `resolve_structural_zone()` also produce sub-ATR zones, confirmed by the CVDDivergence data above.

**Why this produces stopped_at_entry:** Lifecycle tracker activates a signal when `low <= zone_high AND high >= zone_low`. A zone $0.02 wide on QQQ (ATR $0.75) activates on any bar that ticks into it; a 1m bar with range > $0.02 simultaneously activates AND overshoots the zone in the same bar.

**The noise band argument — zone width determines total stop distance from entry:**

For zone-based trades (the majority of I7 signals), the stop architecture is:
```
entry = zone_high          ← proximal edge (zone_proximal entry type)
stop  = zone_low - buffer  ← small ATR fraction below structural level (0.20-0.30×ATR)
total stop distance from entry = zone_width + buffer
```

The `0.25×ATR` buffer is NOT the stop distance — it is padding below the structural level. The total stop distance from entry is `zone_width + 0.25×ATR`.

ATR is the average true range of a single bar. For a stop to be outside intrabar noise, the total stop distance must be a multiple of ATR (convention: 2-3×ATR for entry-based stops). Applying this to zone trades:

```
zone_width + buffer ≥ 2.0×ATR    →    zone_width ≥ 1.75×ATR
```

This means **the zone width gate IS the stop distance gate for zone trades.** A separate fractional stop distance floor is redundant — the zone width threshold directly controls how much room the trade has from entry to stop.

**Zone width distribution (equity, verified 2026-06-14) with noise-band assessment:**
- p05 = $0.003 (0.003-0.006×ATR) — tick noise; stop ≈ 0.25×ATR from entry → coin flip
- p25 = $0.020 (0.02-0.04×ATR) — quote noise; stop ≈ 0.27×ATR from entry → coin flip
- p50 = $0.080 (0.08-0.16×ATR) — marginal; stop ≈ 0.33×ATR from entry → inside noise band
- p75 = $0.560 (0.56-1.12×ATR) — approaching noise floor; stop ≈ 0.81×ATR from entry → marginal
- **For stop outside noise: zone_width ≥ 1.75×ATR → stop ≈ 2.0×ATR from entry**

The existing `MIN_ZONE_WIDTH_ATR = 0.25` constant in zone_engine.py and the initial plan estimate of `0.5×ATR` are both far too loose. They filter only the most catastrophic cases (tick noise), not the systematic noise-band problem. The threshold for meaningful structure is approximately **1.5-2.0×ATR**, not 0.25-0.5×ATR.

**Initial APR seed estimates (to be confirmed by Step 1 diagnostic):**
- Equity ETF: `min_zone_width_atr = 1.5` (stop ≈ 1.75×ATR from entry)
- Forex: `min_zone_width_atr = 1.0` (forex zones structurally larger relative to ATR)
- Futures: `min_zone_width_atr = 1.5` (same reasoning as equity)

**ATR-derived zones are self-exempt:** Sweep band (`entry ± 0.5×ATR` = 1.0×ATR wide), ATR fallback zone (`entry - 1.0×ATR` to `entry + 0.5×ATR` = 1.5×ATR wide). These pass the gate trivially. Pure ATR-based stops from entry (fallback: `entry - 2.0×ATR`) correctly use multiples, not fractions — no zone width gate applies.

**Root Crime 1b — Stop distance contamination in historical data (NOT an active code bug):**

Signal_ledger shows median equity stop distance = $0.31, with 70%+ of CVDDivergence signals having stop < $0.25. This is historical contamination from before `MIN_STOP_ATR_MULTIPLIER = 1.0` was added to `_resolve_stop_long/short`.

Current code is correct: every stop path returns `min(structural_stop, min_stop)` where `min_stop = entry - ATR × _adaptive_buffer(1.0)`. The adaptive buffer floor is 0.742 (worst case: GARCH vol=0.70, trend + max Hurst tightening), giving minimum stop_distance of **0.742×ATR from entry**. Combined with the zone width gate at 0.5×ATR, the structural minimum is ~0.686×ATR, with `min(stop, min_stop)` pushing to 0.742×ATR. A 0.5×ATR gate cannot fire under current code. The plan's prior description "stop = zone_low - 1×ATR when no structural stop is found" was wrong -- the actual ATR fallback is `entry - ATR×2.0`; stops are always anchored to entry, not zone edge.

**Disposition:** The zone width gate (Step 3) is the primary control for stop distance on zone trades. The separate `min_stop_distance_atr` gate (Step 2 below) covers the non-zone ATR-fallback path only — where there is no zone and the stop must be a multiple of ATR from entry. For zone trades, enforcing `zone_width ≥ 1.5×ATR` guarantees total stop distance from entry ≈ 1.75×ATR, which is near the noise floor. Both gates are needed for completeness but the zone width gate carries the load.

**Asset-class reality:**

| Asset | Typical 1m ATR | Zone p50 | Zone p50/ATR | Assessment |
|-------|---------------|---------|-------------|------------|
| Equity ETF (QQQ/SPY) | $0.50-$1.00 | $0.08 | 0.08-0.16× | Noise — any touching bar overshoots |
| Forex (EURUSD/USDCHF) | 0.0003-0.0008 | $0.00073 | ~1-2× | Structurally meaningful |
| Futures (ES/NQ) | 1.0-3.0 pts | (no data yet) | TBD | Requires replay data |

**Why widening is wrong:** A $0.02 ETF zone is not supply/demand — it is a tick-spread artifact. Widening it invents structure. The correct response is `_reject_frame("zone_too_narrow")`.

### Root Crime 2 — Confluence Annotation Bypass (8 signal-generation plugins)

Eight signal-generation plugins carry `requires_i6_confluence = False` via the `_I7_I6_EXEMPT` frozenset in `register_plugins.py`. The exemption was granted during Phase 118-119 as a temporary carve-out while those plugins were being migrated. As of Phase 123, all ECL vectors are annotations on emitted signals — there is no longer any architectural reason for exemption.

The 8 exempt plugins (from `register_plugins.py`): `regime_transition`, `prev_day_level_test`, `anchored_vwap_reversion`, `poc_rejection`, `hvn_rejection`, `cross_asset_divergence`, `mean_revert`, `squeeze_exp`.

Consequences:
- `validate_tier()` silently passes exempt plugins even when they lack `capture_signal_features()` calls
- Confluence context (`ctf_score`, `ctf_confirmed`, `zone_friction_score`) is absent from their signal payloads
- The ECL annotation contract is violated: these signals arrive at `signal_processor.py` missing fields that `context_features` persistence depends on

### Root Crime 3 — trad_FVGFill Catastrophic Failure (8.93% equity win rate)

trad_FVGFill has an 8.93% equity win rate and -0.647 avg pnl_r. This is not explained by zone width:

- FVG zones are **structurally defined by the gap itself** (distance between bar N's close and bar N+2's open). They don't appear as 2-cent zones — their width is determined by actual gap size.
- 8.93% win rate with -0.647 pnl_r means the signal is actively wrong, not just noisy.
- Forex performance is also worst-in-class (28.48% win rate), suggesting the issue is not asset-class-specific.

Hypothesis: FVG **entry timing** defect. Entering when the candle approaches the gap (anticipatory entry) vs. when the gap is actually being filled (reaction entry). An anticipatory entry means the fill may reverse immediately, creating a structural stopped_at_entry pattern independent of zone width.

Secondary hypothesis: FVG zones are being identified on bars where the "gap" is actually a normal spread/rollover artifact, not a genuine market gap.

### Root Crime 4 — Broken Gate Conditions (MeanReversion + zero-signal time-specific plugins)

**trad_MeanReversion dual-gate mutual exclusion:**
- Gate A: `abs(trend_regime) >= 0.4` — requires a ranging market
- Gate B: `abs(kalman_price_position) < 1.0` — requires price displaced > 1 stddev from fair value

When the market is ranging (Gate A satisfied), price stays near fair value by definition — Gate B rarely satisfies. When price is displaced (Gate B satisfied), the market is usually trending — Gate A rarely satisfies. Result: 39 signals in 1.44M signal history.

**Zero-signal time-specific plugins (SessionExtremesSetup, ORB15, ORB30):**
These are NOT in `_I7_I6_EXEMPT`. Their zero-signal status may reflect legitimate rarity (ORB fires once per RTH session; SessionExtremesSetup fires at specific session transitions) or broken gate conditions. Must be diagnosed before the clean replay, not assumed to be correct.

---

## What "Detection Correctness" Means

Per Renaissance principles: a plugin's claim to detect a pattern is credible only if the claimed detection condition is mechanically verifiable from OHLCV + features present at signal time. Textbook backing is not the standard.

A plugin that claims "detects demand zone bounce" is correct if `nearest_demand_low`, `nearest_demand_high`, and `close > nearest_demand_low` are present in features. It is not verifiable if the plugin uses a moving average crossover to infer demand without a zone feature.

**Statistical correctness** is a layer above logic correctness: even if the condition is mechanically verifiable, the plugin must show evidence of predictive power. For Phase 126, this means computing IC (Information Coefficient = correlation between `raw_confidence` and realized outcome) per plugin on existing signal_ledger data. Plugins that are logically correct but statistically noise are demoted to `shadow_only=True` — they stay in `TIER_I7` and accumulate training data for future evaluation.

All dispositions in this phase: `shadow_only=True` with documented rationale. Removal from `TIER_I7` is never valid — every firing is training data.

---

## Wave Structure

### Wave 0 — Data Integrity Prerequisites (runs before all code changes)

**P126-00: USDJPY anomaly diagnosis**

The replay revealed: EURUSD 63.60% win rate (+0.267), USDCHF 64.42% win rate (+0.237), USDJPY 14.39% win rate (-0.380). USDJPY performs like equity ETFs despite being a forex pair. This must be understood before the clean replay consumes USDJPY data as training data. Running a multi-day replay on potentially corrupted instrument data is unacceptable.

Files: SQL analysis only; no code changes unless data quality issue is found.

- [ ] Run bar completeness diagnostic for USDJPY vs EURUSD/USDCHF:
  ```sql
  SELECT symbol,
    count(*) AS total_bars,
    count(*) FILTER (WHERE close IS NOT NULL AND high > low) AS valid_bars,
    avg(high - low) AS avg_range,
    min(timestamp) AS earliest,
    max(timestamp) AS latest,
    count(DISTINCT DATE(timestamp)) AS trading_days
  FROM market_data_ohlcv
  WHERE timestamp > now() - interval '60 days'
    AND symbol IN ('USDJPY', 'EURUSD', 'USDCHF')
  GROUP BY symbol;
  ```
- [ ] Compare zone/ATR ratios for USDJPY signals vs EURUSD signals in signal_ledger:
  ```sql
  SELECT sl.symbol,
    avg((sl.entry_zone_high - sl.entry_zone_low) / NULLIF(
      (SELECT avg(i1->>'atr') FROM intelligence_features if2
       WHERE if2.symbol = sl.symbol AND if2.ts = sl.fired_at LIMIT 1)::float, 0
    )) AS avg_zone_atr_ratio,
    count(*) AS n,
    avg(sl.pnl_r) AS avg_pnl_r
  FROM signal_ledger sl
  WHERE sl.symbol IN ('USDJPY', 'EURUSD', 'USDCHF')
    AND sl.pnl_r IS NOT NULL
  GROUP BY sl.symbol;
  ```
- [ ] Analyze USDJPY by time-of-day (Asian session vs London/NY):
  ```sql
  SELECT sl.symbol,
    extract(hour FROM sl.fired_at AT TIME ZONE 'UTC') AS hour_utc,
    count(*) AS n,
    avg(sl.pnl_r) AS avg_pnl_r
  FROM signal_ledger sl
  WHERE sl.symbol = 'USDJPY' AND sl.pnl_r IS NOT NULL
  GROUP BY sl.symbol, hour_utc
  ORDER BY hour_utc;
  ```
- [ ] Verdict: document findings in plan comments. If data quality issue found → fix data pipeline in this wave. If zone/ATR ratio issue → confirmed addressed by Wave 1. If structural (time-of-day, carry dynamics) → document as ML training segment note; add `usdjpy` regime tag to affected signals.
- [ ] Findings must be written to `docs/plans/2026-06-14-phase-126-usdjpy-diagnostic.md` before Wave 1 begins.

---

### Wave 1 — Zone Geometry Enforcement (blocks replay; after Wave 0)

**P126-01: Universal zone width gate in `frame_trade()` + data-derived APR seeds**

Files: `src/intelligence/trading/trade_framer.py`, `src/intelligence/trading/zone_engine.py`, new migration file

**Architectural decision (non-negotiable):**

The gate does NOT go in `_resolve_zone_bounds()`. That function's contract is to return `(zone_low, zone_high, zone_source)` — it resolves geometry, it does not make viability decisions. `frame_trade()` is already the sole location for all signal viability gates (`zero_risk`, `rr_below_1.5`, `pullback_entry_price_past_t1`, `no_targets_found`). The zone width gate belongs there, applied universally after `_resolve_zone_bounds()` returns, regardless of which zone source path was taken.

This is the only location that catches ALL zone source paths uniformly — confirmed necessary because the narrow zone problem is systemic across structural engine zones (CVDDivergence, GapAnalysis, AnchoredVWAPReversion) not just the three feature-coordinate fast paths.

`validate_stop_against_zone()` is preserved as-is: it corrects stops inside zones. With the zone width gate upstream, it operates only on zones that are geometrically valid. No change needed.

**Step 1 — Pre-implementation diagnostics (run before writing any code):**

Signal_ledger has no outcomes (shadow_outcome all null). Zone width distribution and stop distance distribution are already known from the factual baseline above. One query remains before thresholds can be set — zone_width/ATR ratio by plugin and asset class, which requires joining to intelligence_features for ATR:

- [ ] Run zone_width/ATR ratio distribution query:
  ```sql
  SELECT
    sl.setup_plugin,
    CASE WHEN sl.symbol IN ('EURUSD','USDCHF','USDJPY') THEN 'forex'
         WHEN sl.symbol IN ('ES','NQ','RTY','YM') THEN 'futures'
         ELSE 'equity_etf' END AS asset_class,
    count(*) AS n,
    round(percentile_cont(0.10) WITHIN GROUP (
      ORDER BY (sl.entry_zone_high - sl.entry_zone_low) /
               NULLIF((if1.i1->>'atr')::float, 0)
    )::numeric, 4) AS p10_zone_atr_ratio,
    round(percentile_cont(0.25) WITHIN GROUP (
      ORDER BY (sl.entry_zone_high - sl.entry_zone_low) /
               NULLIF((if1.i1->>'atr')::float, 0)
    )::numeric, 4) AS p25_zone_atr_ratio,
    round(percentile_cont(0.50) WITHIN GROUP (
      ORDER BY (sl.entry_zone_high - sl.entry_zone_low) /
               NULLIF((if1.i1->>'atr')::float, 0)
    )::numeric, 4) AS p50_zone_atr_ratio
  FROM signal_ledger sl
  JOIN intelligence_features if1 ON if1.symbol = sl.symbol
    AND if1.ts = sl.timestamp AND if1.timeframe = sl.timeframe
  WHERE sl.entry_zone_high IS NOT NULL AND sl.entry_zone_high > sl.entry_zone_low
    AND (if1.i1->>'atr')::float > 0
  GROUP BY 1, 2
  HAVING count(*) >= 100
  ORDER BY 2, p50_zone_atr_ratio ASC;
  ```
- [ ] Document results in plan comments. Thresholds must be set from this data, not assumed. The prior plan proposed 0.5/0.25/0.35 — these are starting hypotheses, not final values.
- [ ] Determine threshold for each asset class. Theory says target ≈ 1.5-2.0×ATR (so total stop distance from entry = zone_width + buffer ≈ 2.0×ATR, outside intrabar noise). Use Step 1 data to verify where the empirical inflection sits. Key questions:
  - At what zone_width/ATR ratio does stopped_at_entry probability drop below 10%? (proxy: at what ratio does zone_width + 0.25 ≥ 2.0×ATR → zone_width ≥ 1.75×ATR)
  - Are there asset-class differences? Forex zones tend to be structurally larger relative to ATR — may tolerate 1.0×ATR minimum.
  - The existing `MIN_ZONE_WIDTH_ATR = 0.25` in zone_engine.py is ~7× too low by this analysis; initial estimates are now 1.5 (equity), 1.0 (forex), 1.5 (futures)

**Step 2 — Stop distance (Root Crime 1b): invariant proof + named assertion:**

**Finding (verified 2026-06-14 by code trace):** The stop distance gate as described in prior plan drafts would never trigger under current code. Proof:

`_resolve_stop_long/short` computes `min_stop = entry - atr * _adaptive_buffer(features, MIN_STOP_ATR_MULTIPLIER=1.0, ...)` and returns `min(structural_stop, min_stop)` — always anchored to **entry**, not zone edge. The `_adaptive_buffer` floor (worst case: GARCH vol_ratio=0.70, trend regime, hurst=1.0) yields multiplier = 0.80 × 0.928 = **0.742**. Minimum stop_distance from entry = 0.742×ATR.

Combined with the zone width gate (0.5×ATR minimum): in the structural worst case (entry at zone_high, zone_width=0.5×ATR, demand_stop = zone_low - ATR×0.186), structural stop_distance = 0.686×ATR; `min(stop, min_stop)` enforces 0.742×ATR. Combined minimum = **0.742×ATR**, well above any 0.5×ATR gate.

Historical corpus contamination (median equity stop $0.31, 70%+ of CVD stops < $0.25 in signal_ledger) is from before `MIN_STOP_ATR_MULTIPLIER` was added. The clean replay (Phase 127) regenerates signals through current code.

The plan's description "stop = zone_low - 1×ATR when no structural stop is found" was also a misread — the actual ATR fallback is `entry - ATR×2.0`, not zone-edge relative.

**What to implement:** A real, independent floor gate in `frame_trade()`. This is NOT derived from the adaptive buffer math. `MIN_STOP_ATR_MULTIPLIER` is the primary control; this APR-backed gate is the absolute floor. These are two independent semantic controls: one that sets intent, one that enforces the minimum. Once `MIN_STOP_ATR_MULTIPLIER` migrates to APR and becomes an ML learning target, this gate becomes the hard boundary that ML cannot breach.

- [ ] Add floor gate after `validate_stop_against_zone` call in `frame_trade()`:
  ```python
  _stop_distance = abs(resolved_entry - stop)
  _min_stop_dist = atr * _cfg("feature.zone_engine.min_stop_distance_atr", 0.5)
  if _stop_distance < _min_stop_dist:
      return _reject_frame(
          f"stop_too_close:{stop_type}",
          resolved_entry, entry_type, stop, stop_type, zone_low, zone_high,
      )
  ```
- [ ] APR seeds (initial estimates; ML learning targets once sufficient counterfactual_pnl_r data exists):
  - `feature.zone_engine.min_stop_distance_atr` = 0.5 (default)
  - `feature.zone_engine.min_stop_distance_atr.equity_etf` = 0.5
  - `feature.zone_engine.min_stop_distance_atr.forex` = 0.3
  - `feature.zone_engine.min_stop_distance_atr.futures` = 0.4
  - Description in config_schema: `[initial_estimate] Absolute floor on stop distance from entry as ATR multiple. Independent of MIN_STOP_ATR_MULTIPLIER — ML may tune that parameter but cannot breach this floor without an operator override.`

**Deferred: Full APR migration of trade_framer.py constants (separate todo, not Phase 126):**

Every numeric constant in `trade_framer.py` is a CLAUDE.md architecture violation. ML discovery cannot tune what is hardcoded. These need APR keys and initial estimates documented with provenance:
- `ATR_STOP_DEMAND_MULTIPLIER = 0.25` → `feature.trade_framer.stop_demand_buffer_atr`
- `ATR_STOP_SWEEP_MULTIPLIER = 0.30` → `feature.trade_framer.stop_sweep_buffer_atr`
- `ATR_STOP_OB_MULTIPLIER = 0.20` → `feature.trade_framer.stop_ob_buffer_atr`
- `ATR_STOP_SWING_MULTIPLIER = 0.25` → `feature.trade_framer.stop_swing_buffer_atr`
- `ATR_STOP_SR_MULTIPLIER = 0.50` → `feature.trade_framer.stop_sr_buffer_atr`
- `ATR_STOP_FALLBACK_MULTIPLIER = 2.0` → `feature.trade_framer.stop_fallback_atr`
- `MIN_STOP_ATR_MULTIPLIER = 1.0` → `feature.trade_framer.min_stop_atr`
- `MIN_RR_T1 = 1.5` → `threshold.trade_framer.min_rr_t1`
- `ADAPTIVE_BUFFER_HARD_CAP = 1.40` → `feature.trade_framer.adaptive_buffer_hard_cap`
- `STRUCTURE_SNAP_PROXIMITY_ATR = 1.5` → `feature.trade_framer.structure_snap_proximity_atr`
Tracked in `.planning/todos/pending/` as a separate phase task.

**Step 3 — Implement the zone width gate in `frame_trade()`:**

- [ ] Read `frame_trade()` in full to confirm exact insertion point (after line ~1013 where `_resolve_zone_bounds()` is called, before `validate_stop_against_zone`)
- [ ] Confirm `atr` is available at insertion point (it is — `atr` is a parameter of `frame_trade()`)
- [ ] Add APR-backed configuration loader at top of trade_framer.py (consistent with zone_engine.py pattern):
  ```python
  def _min_zone_width_atr(asset_class: str | None) -> float:
      key = f"feature.zone_engine.min_zone_width_atr.{asset_class}" if asset_class else None
      default = _cfg("feature.zone_engine.min_zone_width_atr", MIN_ZONE_WIDTH_ATR)
      if key and _config_service is not None:
          return _cfg(key, default)
      return default
  ```
- [ ] Insert zone width gate in `frame_trade()` immediately after `features["zone_source"] = zone_source`:
  ```python
  zone_width = zone_high - zone_low
  _asset_class = features.get("asset_class")  # populated by SignalContext
  _min_width = atr * _min_zone_width_atr(_asset_class)
  if zone_width < _min_width:
      return _reject_frame(
          f"zone_too_narrow:{zone_source}",
          resolved_entry, entry_type, stop, stop_type, zone_low, zone_high,
      )
  ```
  Note: `_reject_frame()` not `no_signal()` — this is inside `frame_trade()` which returns a `TradeFrame`, not a signal dict. Plugins call `frame_trade()` and check `trade_frame.viable` before emitting.
- [ ] Confirm `asset_class` is in the features dict at frame time — verify via `SignalContext` or add to `build_flat_features()` if absent
- [ ] Add `set_config_service()` wiring in `trade_framer.py` matching the pattern in `zone_engine.py` (trade_framer currently has no config service; add it)
- [ ] Wire config service into `trade_framer` at `IntelligencePipeline` startup (same location where `zone_engine.set_config_service()` is called)

**Step 4 — APR seeds (data-derived values from Step 1):**

- [ ] Create migration `migrations/NNN_phase126_apr_seeds.sql` with seeds based on Step 1 results.
  Initial estimates from noise-band analysis (total stop distance from entry = zone_width + buffer must be ≥ 2.0×ATR → zone_width ≥ 1.75×ATR; rounded to 1.5 as practical starting point):
  - `feature.zone_engine.min_zone_width_atr` (default) = 1.5
  - `feature.zone_engine.min_zone_width_atr.equity_etf` = 1.5
  - `feature.zone_engine.min_zone_width_atr.forex` = 1.0  (forex zones structurally larger vs. ATR; verify with Step 1)
  - `feature.zone_engine.min_zone_width_atr.futures` = 1.5
  - `feature.zone_engine.min_stop_distance_atr` = 0.5 (non-zone ATR-fallback path only; zone-based stop distance controlled by zone width above)
  - Note: existing `MIN_ZONE_WIDTH_ATR = 0.25` constant in zone_engine.py becomes the fallback default only until APR is loaded — replace with APR key at init.
- [ ] Descriptions in `config_schema` must note provenance: `[initial_estimate — noise band analysis: zone_width + buffer ≥ 2.0×ATR → zone_width ≥ 1.75×ATR; rounded to 1.5. ML learning target post Phase 127 replay.]`

**Step 5 — Proxy before/after impact measurement:**

Signal_ledger has no outcomes (shadow_outcome all null — lifecycle replay not yet populated). The 47.6% stopped_at_entry stat came from lifecycle_replay output, not this table. Proxy measurement:

- [ ] After implementing gate, count signals that WOULD be rejected by zone width threshold on historical corpus, by plugin and asset class:
  ```sql
  -- Run after Step 1 produces confirmed ATR-ratio threshold T
  SELECT
    setup_plugin,
    CASE WHEN symbol IN ('EURUSD','USDCHF','USDJPY') THEN 'forex' ELSE 'equity_etf' END AS ac,
    count(*) AS total,
    count(*) FILTER (
      WHERE (entry_zone_high - entry_zone_low) < T * (i1_atr_from_join)
    ) AS would_reject,
    round(100.0 * count(*) FILTER (
      WHERE (entry_zone_high - entry_zone_low) < T * (i1_atr_from_join)
    ) / count(*)::numeric, 1) AS pct_rejected
  FROM signal_ledger sl
  JOIN intelligence_features ... -- as in Step 1
  GROUP BY 1, 2 ORDER BY pct_rejected DESC;
  ```
- [ ] Document: N signals in replay corpus will be rejected per plugin. Success criterion is not "stopped_at_entry < 25%" (can't measure without replay) but "zone_width/ATR >= threshold for all emitted signals" (verifiable by unit test + logging)

**Step 6 — Unit tests:**

- [ ] supply/demand zone $0.02 on equity (ATR $0.75) → `trade_frame.viable == False`, `rejection_reason == "zone_too_narrow:setup:supply_demand_zone"`
- [ ] FVG zone $0.03 on equity (ATR $0.75) → `viable == False`, `rejection_reason == "zone_too_narrow:setup:fvg_zone"`
- [ ] Structural engine zone 0.0020 on USDJPY (ATR 0.0004) → valid (zone_width 5×ATR)
- [ ] Sweep band zone (always `entry ± 0.5×ATR` = 1.0×ATR wide) → always valid, gate never triggers
- [ ] ATR fallback zone (always `entry ± [1.0, 0.5]×ATR` = 1.5×ATR wide) → always valid, gate never triggers
- [ ] Verify rejection is logged at WARNING level with `zone_width`, `min_width`, `atr`, `zone_source`, `setup_type`, `symbol`
- [ ] `pytest tests/unit/ -q` green

---

### Wave 2 — Signal-Generation Plugin Completeness (parallel with Wave 1, after Wave 0)

**P126-02: Delete `_I7_I6_EXEMPT`, bring 8 plugins to confluence compliance, diagnose 3 time-specific zero-signal plugins**

Files: `src/intelligence/register_plugins.py`, 8 exempt plugin files, `src/intelligence/trading/trade_framer.py` (validate_tier)

**I6 integration for 8 exempt plugins:**

- [ ] List the 8 plugins in `_I7_I6_EXEMPT` explicitly (confirmed from register_plugins.py):
  `regime_transition`, `prev_day_level_test`, `anchored_vwap_reversion`, `poc_rejection`, `hvn_rejection`, `cross_asset_divergence`, `mean_revert`, `squeeze_exp`
- [ ] For each of the 8 exempt plugins:
  - [ ] Set `requires_i6_confluence = True`
  - [ ] Add `capture_signal_features()` call in `compute_full()` (or confirm it already exists and is being called)
  - [ ] Confirm `ctf_score`, `ctf_confirmed`, `zone_friction_score` are populated in signal payload after the fix
- [ ] Delete `_I7_I6_EXEMPT` frozenset from `register_plugins.py`
- [ ] Rename any remaining references `_I7_I6_EXEMPT` → delete entirely (grep sweep: `grep -r "_I7_I6_EXEMPT" src/ tests/`)
- [ ] Confirm `validate_tier()` now catches any plugin missing confluence compliance with no carve-out path

**Diagnose 3 time-specific zero-signal plugins (Jim Simons would not accept "probably rarely triggered" as a verdict):**

- [ ] `trad_SessionExtremesSetup`: Read `compute_full()`. Identify exact gate conditions. Run SQL to find how many bars in signal_ledger window match the session transition condition. Expected: fires at Asian→London crossover. If gate logic is correct but instrument coverage doesn't include Asian session instruments → `shadow_only=True` with note "instrument universe lacks Asian session coverage; set shadow_only=False when instruments added."
- [ ] `trad_ORB15` / `trad_ORB30`: Read `compute_full()`. Opening range breakout fires only at RTH open (9:30 ET) for equity instruments. Verify: (a) are equity instruments with RTH data in the replay window? (b) does the first-15-min / first-30-min range calculation work correctly? (c) does the breakout detection trigger correctly in test? Write one targeted unit test with a synthetic bar sequence simulating RTH open. If logic is correct → document as working-but-rare. If logic is broken → fix gate condition.
- [ ] For each of the 3: document findings in plugin docstring. Outcome must be one of: (a) CORRECT-RARE (documented, no code change), (b) BROKEN (gate condition fixed), (c) SCOPE-MISMATCH (`shadow_only=True` with note).
- [ ] `pytest tests/unit/ -q` green

**P126-03: Fix `trad_MeanReversion` dual-gate conflict**

Files: `src/intelligence/trading/mean_reversion.py`

- [ ] Read current gate logic for `trad_MeanReversion`; document exact conditions and threshold values
- [ ] Confirm mutual-exclusivity with SQL probe:
  ```sql
  SELECT
    count(*) FILTER (WHERE (if1->>'trend_regime')::float BETWEEN -0.4 AND 0.4) AS gate_a_ok,
    count(*) FILTER (WHERE abs((if3->>'kalman_price_position')::float) > 1.0) AS gate_b_ok,
    count(*) FILTER (WHERE
      (if1->>'trend_regime')::float BETWEEN -0.4 AND 0.4
      AND abs((if3->>'kalman_price_position')::float) > 1.0
    ) AS both_gates_ok,
    count(*) AS total_bars
  FROM intelligence_features
  WHERE ts > now() - interval '30 days';
  ```
- [ ] Decision based on data:
  - If `both_gates_ok / total_bars < 0.01`: gates are mutually exclusive — lower Gate A threshold to 0.2 (relaxing trend requirement); APR key `threshold.mean_reversion.trend_regime_max` = 0.2
  - If `both_gates_ok / total_bars >= 0.01`: gates are not mutually exclusive; diagnose why only 39 signals fired — wrong threshold values or wrong feature keys
  - Either way: APR key for threshold so it's tunable without code change
- [ ] If trad_MeanReversion cannot be made to fire reliably in 30-day window after gate fix: `shadow_only=True` with documented "dual-gate mutual exclusion diagnosed; relaxed to [threshold] but insufficient activation — parked for redesign"
- [ ] `pytest tests/unit/ -q` green

**P126-04: trad_FVGFill structural audit**

Files: `src/intelligence/trading/fvg_fill.py`, possibly `src/intelligence/trading/trade_framer.py`

This is a diagnostic-first task. Do not change code until the root cause is confirmed.

- [ ] Read `compute_full()` in fvg_fill.py in full. Document:
  - What defines an "FVG" in the code (which feature fields, what calculation)
  - What triggers entry — price proximity to gap (`close near fvg_bottom`) vs confirmed penetration (`low < fvg_bottom AND close > fvg_bottom`)
  - How the zone coordinates map to `zone_low`/`zone_high` (does zone_width depend on bar gap size?)
- [ ] Run SQL to compare FVGFill zone widths to other plugins:
  ```sql
  SELECT
    setup_plugin,
    avg(entry_zone_high - entry_zone_low) AS avg_zone_width,
    percentile_cont(0.5) WITHIN GROUP (ORDER BY entry_zone_high - entry_zone_low) AS median_zone_width,
    count(*) AS n
  FROM signal_ledger
  WHERE setup_plugin IN ('trad_FVGFill', 'trad_SupplyDemandSetup', 'trad_LiquiditySweepReclaim', 'trad_CHoCHReversal')
  GROUP BY setup_plugin;
  ```
- [ ] Check: does FVGFill entry_type = `at_close` (aggressive) or `at_limit` (at gap fill price)? If `at_close`, the signal fires on the APPROACH bar before the fill happens — entries that are immediately reversed on the next bar explain the failure rate.
- [ ] Check: is the FVG computed from SMC tier features (`fvg_bottom`, `fvg_top`) or recomputed in the plugin? If recomputed: could produce stale zones that don't match current market structure.
- [ ] Verdict: if entry timing defect confirmed (entry on approach, not on fill confirmation) → fix to require penetration + close inside gap before triggering; APR key for confirmation threshold. If zone quality issue → cross-validate FVG coordinates with SMC tier output. If no clear defect found → document findings; `shadow_only=True` with "catastrophic equity performance, mechanism unknown, parked for redesign."
- [ ] After any fix: run SQL probe to confirm equity win rate improves on existing data (before/after signal comparison on signal_ledger)
- [ ] `pytest tests/unit/ -q` green

---

### Wave 3 — Pipeline-Layer Signal Annotation (parallel with Wave 2, after Wave 0)

**Full plan:** `docs/plans/2026-06-14-phase-126-pipeline-annotation-layer.md`

Annotation of extrinsic context (CTF scores, macro regime, exhaustion, zone friction) is pipeline infrastructure responsibility, not plugin responsibility. The current design puts `capture_signal_features()` in plugin bodies — a category error that produces a biased, heterogeneous training corpus. This wave moves annotation to `signal_processor.process()`, applied uniformly to every signal regardless of which plugin fired.

**Why this blocks Phase 127:** A clean replay on a corpus where `context_features` is populated by 22 of 30 plugins and null for the rest produces ML training data with a plugin-identity confound in the feature matrix. That corpus is not fit for `context_features`-dependent training.

Summary of tasks (see full plan for implementation details):
- [ ] **P126-06a:** Audit what is/isn't in `flat_features` — establishes ground truth before any code changes
- [ ] **P126-06b:** Formalize `zone_friction_score` in a tier plugin — currently produced by one plugin body only, not in IntelligenceEvent schema
- [ ] **P126-06c:** Implement `_annotate_signal()` in `signal_processor.py` — single annotation point, full `flat_features` as `context_features`
- [ ] **P126-06d:** Strip `capture_signal_features()` from all 30 plugin bodies — mechanical sweep
- [ ] **P126-06e:** Clean `make_signal_from_frame()` — remove ECL kwargs (`ctf_score=`, `context_features=`, etc.)
- [ ] **P126-06f:** Delete `_I7_I6_EXEMPT` and `requires_i6_confluence` enforcement
- [ ] **P126-06g:** Deprecate `capture_signal_features()` in `confidence_utils.py`
- [ ] **P126-06h:** Bump `SIGNAL_SCHEMA_VERSION` with changelog comment
- [ ] **P126-06i:** Unit tests — annotation uniformity, extensibility contract, zero plugin annotation code

---

### Wave 4 — Statistical & Detection Correctness Audit (after Wave 2)

**P126-05: Per-plugin IC validation + detection condition verification**

Files: new audit script `production/scripts/signal_quality_audit.py`, output `docs/plans/2026-06-14-phase-126-signal-quality-audit-results.md`

This replaces the narrower "detection correctness audit" (P126-04 in prior plan) with a two-layer audit: statistical validity first, then logic correctness for survivors.

**Layer 1 — Statistical IC table (existing signal_ledger data):**

- [ ] Write `signal_quality_audit.py` Part 1:
  ```python
  # For each plugin with >= 30 outcomes in signal_ledger:
  # - hit_rate = pnl_r > 0 rate
  # - IC = corr(raw_confidence, pnl_r)  [uses signal_transform_log or signal_ledger.pre_quality_confidence]
  # - bootstrap 95% CI on hit_rate (10,000 resample)
  # - t-stat for IC vs 0
  # - segment by symbol (equity vs forex)
  ```
- [ ] Query:
  ```sql
  SELECT
    setup_plugin,
    count(*) FILTER (WHERE pnl_r IS NOT NULL) AS n_outcomes,
    avg(CASE WHEN pnl_r > 0 THEN 1.0 ELSE 0.0 END)
      FILTER (WHERE pnl_r IS NOT NULL) AS hit_rate,
    corr(pre_quality_confidence, pnl_r) AS ic,
    avg(pnl_r) AS avg_pnl_r,
    -- segment
    count(*) FILTER (WHERE symbol IN ('EURUSD', 'USDCHF', 'USDJPY') AND pnl_r IS NOT NULL) AS n_forex,
    count(*) FILTER (WHERE symbol NOT IN ('EURUSD', 'USDCHF', 'USDJPY') AND pnl_r IS NOT NULL) AS n_equity,
    avg(pnl_r) FILTER (WHERE symbol IN ('EURUSD', 'USDCHF', 'USDJPY')) AS avg_pnl_forex,
    avg(pnl_r) FILTER (WHERE symbol NOT IN ('EURUSD', 'USDCHF', 'USDJPY')) AS avg_pnl_equity
  FROM signal_ledger
  GROUP BY setup_plugin
  HAVING count(*) FILTER (WHERE pnl_r IS NOT NULL) >= 30
  ORDER BY ic DESC;
  ```
- [ ] Compute bootstrap CI for each plugin's hit_rate (Python scipy or manual resampling)
- [ ] Verdict logic per plugin:
  - `IC > 0.02` AND `hit_rate CI lower > 0.45`: VALIDATED — proceed to Layer 2 logic audit
  - `IC between -0.02 and 0.02` OR `hit_rate CI includes 0.5`: NOISE CANDIDATE — Layer 2 for logic audit, results noted, no immediate action
  - `IC < -0.02` OR `hit_rate CI upper < 0.45`: ANTI-SIGNAL — `shadow_only=True` with "statistically anti-predictive on existing data; redesign required" note

**Layer 2 — Detection condition verification (for VALIDATED and NOISE CANDIDATE plugins):**

- [ ] Write `signal_quality_audit.py` Part 2:
  - Pull 50 signals per plugin from signal_ledger (join to intelligence_features on `fired_at`, `symbol`)
  - For each plugin, read its `compute_full()` to identify the primary detection condition
  - For each sampled signal: query intelligence_features to check if the detection condition fields are populated and non-null at signal time
  - Output: plugin name, samples, fields_populated_rate, verdict (VERIFIABLE / PARTIAL / UNVERIFIABLE)
- [ ] For each UNVERIFIABLE plugin: `shadow_only=True` with "detection condition relies on feature fields absent at signal time — signal is firing on stale or missing data"
- [ ] Run audit; produce `docs/plans/2026-06-14-phase-126-signal-quality-audit-results.md` with both layers:
  - IC league table (all plugins with >= 30 outcomes)
  - Detection verifiability table (all plugins)
  - Summary: N validated, N noise candidates, N anti-signals, N unverifiable
- [ ] `pytest tests/unit/ -q` green

---

## Success Criteria

| # | Criterion | Measurable condition |
|---|-----------|---------------------|
| 0 | USDJPY diagnostic complete | `docs/plans/2026-06-14-phase-126-usdjpy-diagnostic.md` exists with verdict: data quality, zone geometry, or structural |
| 1 | Zone width gate location correct | Gate is in `frame_trade()` after `_resolve_zone_bounds()`, not inside `_resolve_zone_bounds()`. Returns `_reject_frame("zone_too_narrow:...")` with zone_source in reason. |
| 2 | Gate is universal | All zone sources (supply_demand, fvg, ob, structural engine, ATR fallback) pass through the same gate. ATR-derived zones pass trivially by construction — no special-case code. |
| 3 | APR seeds data-derived | `feature.zone_engine.min_zone_width_atr` per-asset-class seeds set from Step 1 zone_width/ATR ratio analysis, not assumed. Provenance documented in config_schema description. |
| 4 | Stop distance verified | Step 2 query run; result documented. If p05 stop_atr >= 0.8 on recent signals, no additional gate added. If gap found, gate added with APR key. |
| 4a | Impact measured | Proxy rejection count query run: N signals per plugin per asset class would be rejected by the gate on historical corpus. Numbers documented. |
| 5 | Time-specific plugin verdict documented | SessionExtremesSetup, ORB15, ORB30 each have documented verdict (CORRECT-RARE / BROKEN / SCOPE-MISMATCH) in plugin docstring |
| 6 | trad_MeanReversion resolved | > 100 fires in 30-day replay simulation OR `shadow_only=True` with rationale; stays in `TIER_I7` |
| 7 | trad_FVGFill root cause identified | Entry timing defect confirmed/refuted; code fix applied OR `shadow_only=True` with redesign doc |
| 8 | Annotation uniform across all signals | `grep -rn "capture_signal_features" src/intelligence/trading/` returns empty; every signal from `signal_processor.process()` has non-empty `context_features` |
| 9 | Surfaced ECL fields always populated | `ctf_score`, `ctf_confirmed`, `zone_friction_score` present on every signal (null only when source genuinely absent, never missing due to plugin omission) |
| 10 | `zone_friction_score` formalized | Field added to IntelligenceEvent schema; computed by tier plugin; present in `flat_features` |
| 11 | Exempt category deleted | `grep -r "_I7_I6_EXEMPT\|requires_i6_confluence" src/` returns empty |
| 12 | Signal schema version bumped | `SIGNAL_SCHEMA_VERSION` incremented with changelog comment |
| 13 | Signal quality audit complete | `docs/plans/2026-06-14-phase-126-signal-quality-audit-results.md` with IC table + detection verifiability table |
| 14 | Anti-signal plugins demoted | All plugins with IC < -0.02 or hit_rate CI upper < 0.45 set to `shadow_only=True` |
| 15 | Tests green | `pytest tests/unit/ -q` passes |

---

## Dependencies

| Dependency | On phase | Reason |
|-----------|----------|--------|
| `feature.zone_engine.min_zone_width_atr` is a Tier C APR key | Phase 125 (APR migration) | P126-01 reads from APR; if 125 not complete, hard-code with TODO comment |
| `atr` in feature vector at framing time | Phase 122 (I2 tier persistence) | Confirmed available; use `atr_utils.get_atr()` |
| `requires_i6_confluence` enforcement in `validate_tier()` | Phase 118 | Already in place; P126-02 removes the carve-out |
| `pre_quality_confidence` in signal_ledger | Phase 57 | Available; IC calculation queries this field |

---

## What This Does Not Fix

| Issue | Deferred to | Reason |
|-------|-------------|--------|
| Asset-class-specific detection logic redesign | v2.11 | The zone geometry fix addresses the mechanical failure mode; detection logic redesign (equity-specific setup variants) requires replay data first |
| Calibration curves trained on pre-fix corpus | Phase 127 | Replay must complete first |
| 3-table signal architecture | Phases 128-130 | Structural; not data-quality |
| CounterfactualTracker (populates `counterfactual_pnl_r`) | Phase 130 | Requires trade_frames table |
| Full ML parameter discovery | v2.11 | Requires 30-90 days of counterfactual_pnl_r |
| `capture_signal_features()` deletion | Phase 128 | Deprecated in Phase 126; retained one release cycle to confirm no external callers before full removal |

---

## Probe Queries

```sql
-- Zone width distribution by asset class (signal_ledger, pre-fix baseline)
SELECT
  CASE WHEN symbol IN ('EURUSD', 'USDCHF', 'USDJPY') THEN 'forex'
       WHEN symbol IN ('ES', 'NQ', 'RTY', 'YM') THEN 'futures'
       ELSE 'equity_etf' END AS asset_class,
  percentile_cont(ARRAY[0.05, 0.25, 0.5, 0.75, 0.95]) WITHIN GROUP (
    ORDER BY entry_zone_high - entry_zone_low
  ) AS zone_width_pctiles,
  count(*) AS n
FROM signal_ledger
WHERE pnl_r IS NOT NULL
GROUP BY 1;

-- stopped_at_entry rate by asset class and plugin
SELECT
  setup_plugin,
  CASE WHEN symbol IN ('EURUSD', 'USDCHF', 'USDJPY') THEN 'forex' ELSE 'equity' END AS asset_class,
  count(*) FILTER (WHERE outcome = 'stopped_at_entry') AS stopped,
  count(*) AS total,
  round(100.0 * count(*) FILTER (WHERE outcome = 'stopped_at_entry') / count(*), 1) AS pct
FROM signal_ledger
WHERE pnl_r IS NOT NULL
GROUP BY 1, 2
ORDER BY pct DESC;

-- IC league table (quick version, without bootstrap CI)
SELECT
  setup_plugin,
  count(*) FILTER (WHERE pnl_r IS NOT NULL) AS n,
  round(avg(pnl_r)::numeric, 4) AS avg_pnl_r,
  round(corr(pre_quality_confidence, pnl_r)::numeric, 4) AS ic,
  round(avg(CASE WHEN pnl_r > 0 THEN 1.0 ELSE 0.0 END)
    FILTER (WHERE pnl_r IS NOT NULL)::numeric, 4) AS hit_rate
FROM signal_ledger
GROUP BY setup_plugin
HAVING count(*) FILTER (WHERE pnl_r IS NOT NULL) >= 30
ORDER BY ic DESC NULLS LAST;
```

---

*Plan created: 2026-06-14*
*Revised: 2026-06-14 — added Root Crimes 1b (stop distance), 3 (FVGFill), 4 (time-specific plugins); added Wave 0 (USDJPY diagnostic); added statistical IC validation to Wave 3; corrected zero-signal plugin count from phantom 13 to actual 6; updated success criteria*
*Revised: 2026-06-14 (P126-01 noise band analysis) — Zone width threshold corrected from 0.5×ATR to 1.5×ATR initial estimate. Reasoning: for zone trades, total stop distance from entry = zone_width + buffer (0.25×ATR); to be outside intrabar noise band (≥ 2.0×ATR from entry), zone_width ≥ 1.75×ATR. The zone width gate IS the stop distance gate for zone trades — the separate min_stop_distance_atr gate applies only to non-zone ATR-fallback path. ATR-based stops from entry must be multiples (2-3×ATR), fractional stops are coin flips. min_stop_distance_atr = 0.5 retained only as safety gate for the non-zone path where entry-based ATR-multiple stops are used.*
*Revised: 2026-06-14 (P126-01 Renaissance audit) — Root Crime 1 analysis corrected: zone width problem is systemic across ALL zone sources (structural engine + fast paths), not confined to 3 fast paths; confirmed by signal_ledger data (80% of CVDDivergence zones < $0.025, affects 112k signals). P126-01 implementation location corrected: gate belongs in `frame_trade()` not `_resolve_zone_bounds()` — consistent with all other viability gates; `_resolve_zone_bounds()` contract is geometry resolution only. APR seed values changed from assumed to data-derived (Step 1 diagnostic query added). Stop distance gate made conditional on Step 2 verification (MIN_STOP_ATR_MULTIPLIER=1.0 may already handle this for new signals). Baseline measurement corrected: signal_ledger has no outcomes; proxy impact count replaces stopped_at_entry SQL. Config service wiring requirement added for trade_framer. Sweep/ATR-derived zone exemption documented (trivially exempt, no code needed).*
*Implements: SIGNAL-QUALITY-01, SIGNAL-QUALITY-02 (REQUIREMENTS.md)*
*Workstream A gate: must complete before Phase 127 (Clean Replay)*
