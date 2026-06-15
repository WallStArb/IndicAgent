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

### Root Crime 1 — Zone Width Bypass in `_resolve_zone_bounds()` (47.6% stopped_at_entry)

`_resolve_zone_bounds()` in `trade_framer.py` reads raw feature-level zone coordinates without applying any ATR-relative minimum:

```python
# Current code — no width gate
if zone_source == "supply_demand":
    zone_low = features["nearest_demand_low"]
    zone_high = features["nearest_demand_high"]
elif zone_source == "fvg":
    zone_low = features["fvg_bottom"]
    zone_high = features["fvg_top"]
elif zone_source == "ob":
    zone_low = features["ob_bottom"]
    zone_high = features["ob_top"]
```

`zone_engine.py` has `MIN_ZONE_WIDTH_ATR = 0.25` but it applies only to zones computed inside `zone_engine.py` itself. The feature-level fast paths that bypass `zone_engine` carry no such guard.

**Root Crime 1b — Stop calculated from zone edge, not entry:**

Even with a valid zone, stop distance from entry can be negligible:

```
XLE zone [57.46, 57.47], entry 57.49, stop 57.46 → stop_distance = 0.03 on ATR $0.60
QQQ zone [723.14, 723.16], entry 723.09, stop 723.24 → stop placed ABOVE entry (inverted)
```

Stop = `zone_low - 1×ATR` when no structural stop is found. When entry drifts to zone edge, the resulting R:R is degenerate regardless of zone width. The fix: require `abs(entry_price - stop_price) >= min_stop_distance_atr × ATR` as an emission gate.

**Asset-class reality:**

| Asset | 1m ATR | Typical feature zone | Zone/ATR ratio | Effect |
|-------|--------|---------------------|----------------|--------|
| QQQ / SPY | $0.50-$1.00 | $0.01-$0.06 | 0.02-0.08x | Stop sits below a $0.02 zone; any touching bar overshoots; stopped_at_entry guaranteed |
| USDJPY | 0.0003-0.0008 | 0.0010-0.0050 (2-10 pip) | 3-15x | Zone is structurally meaningful; trade has room to breathe |
| ES / NQ | 1.0-3.0 pts | 0.5-2.0 pts | 0.3-1.5x | Marginal; some zones valid, some are noise |

**Why widening is wrong:** A $0.02 ETF zone is not supply/demand — it is a single-tick reading artifact. Widening it to $0.50 invents structure that does not exist in price. The correct response is `no_signal()`.

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

**P126-01: Zone width guard + stop distance gate in `_resolve_zone_bounds()` + APR seeds**

Files: `src/intelligence/trading/trade_framer.py`, `src/intelligence/trading/zone_engine.py`, new migration file

**Zone width guard:**

- [ ] Read `_resolve_zone_bounds()` in full; map all zone-source branches (supply_demand, fvg, ob, structural, fallback)
- [ ] Confirm `features["atr"]` is available in the feature dict at framing time (check `IntelligenceEvent` schema via `atr_utils.get_atr()`)
- [ ] Add width guard after zone bounds are resolved, before `TradeFrame` construction:
  ```python
  zone_width = zone_high - zone_low
  min_width = atr * _cfg("feature.zone_engine.min_zone_width_atr", MIN_ZONE_WIDTH_ATR)
  if zone_width < min_width:
      return no_signal(reason="zone_too_narrow", zone_width=zone_width, atr=atr)
  ```
- [ ] Add per-asset-class APR seeds (new migration file `migrations/NNN_phase126_apr_seeds.sql`):
  - `feature.zone_engine.min_zone_width_atr.equity_etf` = 0.5
  - `feature.zone_engine.min_zone_width_atr.forex` = 0.25
  - `feature.zone_engine.min_zone_width_atr.futures` = 0.35
  - `feature.zone_engine.min_zone_width_atr` (default fallback) = 0.25
- [ ] Load the correct seed based on `Instrument.asset_class` from `get_active_contracts(settings)`; instrument type available in `SignalContext`
- [ ] Confirm `MIN_ZONE_WIDTH_ATR` constant in `zone_engine.py` is now the APR default; inline constant removed after APR key exists

**Stop distance gate (new — Root Crime 1b):**

- [ ] After zone width validation, add minimum stop distance gate before TradeFrame construction:
  ```python
  stop_distance = abs(entry_price - stop_price)
  min_stop = atr * _cfg("feature.zone_engine.min_stop_distance_atr", 0.5)
  if stop_distance < min_stop:
      return no_signal(reason="stop_too_close", stop_distance=stop_distance, atr=atr)
  ```
- [ ] Add per-asset-class APR seeds:
  - `feature.zone_engine.min_stop_distance_atr.equity_etf` = 0.5
  - `feature.zone_engine.min_stop_distance_atr.forex` = 0.3
  - `feature.zone_engine.min_stop_distance_atr.futures` = 0.4
  - `feature.zone_engine.min_stop_distance_atr` (default) = 0.5
- [ ] Write unit tests covering both gates:
  - supply_demand zone $0.02 on QQQ (ATR $0.75) → `no_signal(reason="zone_too_narrow")`
  - fvg zone $0.03 on QQQ, entry at zone_high, stop = zone_low - ATR → entry-stop distance < 0.5×ATR → `no_signal(reason="stop_too_close")`
  - fvg zone 0.0020 on USDJPY (ATR 0.0004) → valid (zone_width 5×ATR)
  - structural zone on ES 1.5pts (ATR 1.2pts), stop 1.0 pts from entry → valid (stop > 0.4×ATR)
- [ ] Run SQL probe on existing signal_ledger to establish before-fix baseline:
  ```sql
  SELECT
    count(*) FILTER (WHERE outcome = 'stopped_at_entry') AS stopped,
    count(*) AS total,
    round(100.0 * count(*) FILTER (WHERE outcome = 'stopped_at_entry') / count(*), 1) AS pct,
    symbol
  FROM signal_ledger
  WHERE pnl_r IS NOT NULL
  GROUP BY symbol
  ORDER BY pct DESC;
  ```
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

### Wave 3 — Statistical & Detection Correctness Audit (after Wave 2)

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
| 1 | Zone width guard enforced | `_resolve_zone_bounds()` returns `no_signal(reason="zone_too_narrow")` when `zone_width < min_zone_width_atr × ATR` for ALL zone source types |
| 2 | Stop distance gate enforced | `_resolve_zone_bounds()` returns `no_signal(reason="stop_too_close")` when `abs(entry - stop) < min_stop_distance_atr × ATR` |
| 3 | APR seeds deployed | `feature.zone_engine.min_zone_width_atr` AND `feature.zone_engine.min_stop_distance_atr` in `config_state` with per-asset-class seeds |
| 4 | stopped_at_entry rate reduced | SQL on existing signal_ledger confirms equity stopped_at_entry < 25%, overall < 20% after retrospective simulation of new gates |
| 5 | Confluence-exempt frozenset deleted | `grep -r "_I7_I6_EXEMPT" src/ tests/` returns empty |
| 6 | All 8 formerly-exempt plugins compliant | `requires_i6_confluence = True` + `capture_signal_features()` verified in each plugin |
| 7 | Time-specific plugin verdict documented | SessionExtremesSetup, ORB15, ORB30 each have documented verdict (CORRECT-RARE / BROKEN / SCOPE-MISMATCH) in plugin docstring |
| 8 | trad_MeanReversion resolved | > 100 fires in 30-day replay simulation OR `shadow_only=True` with rationale; stays in `TIER_I7` |
| 9 | trad_FVGFill root cause identified | Entry timing defect confirmed/refuted; code fix applied OR `shadow_only=True` with redesign doc |
| 10 | Signal quality audit complete | `docs/plans/2026-06-14-phase-126-signal-quality-audit-results.md` with IC table + detection verifiability table |
| 11 | Anti-signal plugins demoted | All plugins with IC < -0.02 or hit_rate CI upper < 0.45 set to `shadow_only=True` |
| 12 | Tests green | `pytest tests/unit/ -q` passes |

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
| I6 integration of any future plugins | Future phase | Only the 8 currently-exempt plugins are in scope |

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
*Implements: SIGNAL-QUALITY-01, SIGNAL-QUALITY-02 (REQUIREMENTS.md)*
*Workstream A gate: must complete before Phase 127 (Clean Replay)*
