# Phase 41: Intelligence Gap Fill - Context

**Gathered:** 2026-03-20
**Status:** Ready for planning

<domain>
## Phase Boundary

Fill intelligence fields that were hardcoded stubs with real computed values:
- `i6_fvg_tf_alignment` and `i6_ob_tf_alignment` in `cross_timeframe.py` (currently `0.0`)
- Volume Profile levels (POC/VAH/VAL) as T1/T2 targets in `trade_framer.py`
- Higher-TF (1h) VP + I6 context injected into I7 signal framing for short-TF bars
- VWAP/session plugin TF guards (intraday-only plugins must not fire on 1h+)
- Aggregator `active`-from-`all_ranked` assertion + plugin state write-back comments (from pending todos)

**INTEL-04 (roll premium) explicitly deferred to Phase 44** — requires back-month IBKR subscriptions and belongs alongside `ROLL_MONITOR_ENABLED=true` enablement. No new IBKR subscriptions in Phase 41.

</domain>

<decisions>
## Implementation Decisions

### FVG/OB Cross-TF Alignment Scoring

- **Formula**: `score = direction_match_fraction × proximity_decay` per TF, then TF-authority-weighted sum
  - Direction match: does `fvg_type` (or `ob_type`) on the higher TF match the current bar's direction?
  - Proximity decay: zone within 1 ATR of current price = full weight; linear decay from 1–3 ATR; beyond 3 ATR = zero weight. ATR already available in frames.
- **TF scope**: Higher TFs only. For a 1m bar: uses 5m, 15m, 1h intel frames. For a 5m bar: uses 15m, 1h. Lower TFs are too ephemeral and add noise.
- **Same formula for FVG and OB**: `order_blocks.py` already filters to unmitigated OBs before output — the data is clean by the time `cross_timeframe.py` sees it. Same direction × proximity formula applies to both; weights diverge only if Phase 46 calibration supports it.
- **Per-TF contributions logged in i6 JSONB**: fully decomposable and auditable — Renaissance standard.
- **TF authority weights**: reuse the existing `_TF_MINUTES` weight structure already in `cross_timeframe.py`.

### Volume Profile Targets in trade_framer

- **Priority override when near VA boundary**: when `distance_to_vah_atr < 0.5` or `distance_to_val_atr < 0.5`, VP candidates are elevated to the front of the candidate ranking. Implemented as a clean `_vp_regime_active(features)` predicate — not scattered special-case code.
- **Near VA boundary**: T1 = POC, T2 = VAH (long) or VAL (short)
- **Inside value area** (`price_in_value_area == 1.0`): T1 = far VA boundary (VAH for longs, VAL for shorts), no T2. Avoids targeting POC which may be behind entry.
- **TF-based VP source** via `_select_vp(features, tf)` helper (single responsibility):
  - 1m/5m → session VP (`poc_price`, `vah`, `val`) — intraday volume most relevant
  - 15m/1h → rolling VP (`poc_price_rolling`, `vah_rolling`, `val_rolling`) — structural volume more stable
  - Called from both `_collect_targets_long` and `_collect_targets_short` — zero duplication.
- All VP fields (`poc_price`, `vah`, `val`, `distance_to_vah_atr`, `distance_to_val_atr`, `price_in_value_area`) already in I4Context schema and available in features dict. No schema changes needed.

### HTF Context to trade_framer

- **Pattern**: identical to existing `_cross_asset_cache` — `signal_generator_service` maintains `_htf_intel_cache: dict[str, dict]` keyed by `"{symbol}:1h"`.
- **Injection**: for 1m/5m/15m bars, inject `frames["htf_1h"] = self._htf_intel_cache.get(f"{symbol}:1h", {})` before `compute_full()`. 1h bars need no injection.
- **Zero new subscriptions**: `signal_generator_service` already consumes `intelligence:SYMBOL:TF` for all TFs to build `bar_history`. Cache is populated from the same stream.
- **trade_framer uses htf_1h for targets only** — not stops. HTF stops would destroy RR on 1m/5m signals (stop would be 5-20× wider than native-TF structure). `_select_vp()` reads from `htf_1h` when current-TF VP is absent.
- **I7 plugins unchanged**: they pass `features` as-is. All routing logic stays in `signal_generator_service`.

### VWAP/Session Plugin TF Guards

- VWAP-based plugins (`AnchoredVWAPReversion`, `VWAPReclaim`, `POCRejection`) and session-based plugins (`ORB15`, `ORB30`, `PrevDayLevelTest`) are intraday-only.
- Add TF guard at the top of each `compute_full()`: `if timeframe not in ("1m", "5m", "15m"): return self._no_signal()`
- Timeframe is available in `frames` dict as `frames.get("timeframe")` or extracted from the bar.

### Aggregator + Plugin State Write-back (from pending todos)

- **Aggregator guard**: add `# CRITICAL: Always derive active from all_ranked, NOT raw signals` comment at the `active` derivation line + assertion in tests: `assert "adjusted_rank" in sig for sig in result["active"]`
- **Plugin state write-back**: add `# CRITICAL: Write state back AFTER compute_full()` warning comment in both `market_analysis_service.py` and `indicator_service.py` plugin computation loops.
- Both are documentation-only changes (zero behavioral impact), implemented in one plan.

### Claude's Discretion

- Exact TF authority weight values for FVG/OB cross-TF scoring (reuse `_TF_MINUTES` ratio or define explicit weights)
- Whether `_vp_regime_active()` is a module-level function or inline predicate in trade_framer
- How `timeframe` is extracted in VWAP plugins (from `frames` dict key or plugin `InputSpec`)

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Intelligence stub locations
- `src/intelligence/confluence/cross_timeframe.py:140-141` — hardcoded `i6_fvg_tf_alignment: 0.0` and `i6_ob_tf_alignment: 0.0` stubs to replace
- `src/intelligence/schemas.py:684-685` — `i6_fvg_tf_alignment` and `i6_ob_tf_alignment` field definitions

### Volume Profile
- `src/intelligence/schemas.py:369-388` — I4Context VP fields: `poc_price`, `vah`, `val`, rolling variants, `price_in_value_area`, `distance_to_vah_atr`, `distance_to_val_atr`
- `src/intelligence/trading/trade_framer.py:479-555` — `_collect_targets_long/short` candidate system to extend with VP

### HTF context injection pattern
- `services/signal_generator_service.py:599-601` — `_cross_asset_cache` pattern to replicate for `_htf_intel_cache`
- `services/signal_generator_service.py:1466-1470` — cross-asset frame injection to mirror for `htf_1h`

### FVG/OB plugin outputs
- `src/intelligence/trading/fvg_fill.py` — outputs: `fvg_type`, `fvg_top`, `fvg_bottom`
- `src/intelligence/smart_money/order_blocks.py` — outputs: `ob_type`, `ob_top`, `ob_bottom` (already filtered to unmitigated)

### Pending todos to close
- `.planning/todos/pending/2026-03-11-aggregator-active-from-all-ranked-guard.md`
- `.planning/todos/pending/2026-03-11-plugin-state-writeback-comments.md`

### Requirements
- `.planning/REQUIREMENTS.md` §INTEL — INTEL-01 through INTEL-05 (INTEL-04 deferred to Phase 44)

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `_TF_MINUTES` dict in `cross_timeframe.py` — TF authority weights already defined; reuse for FVG/OB alignment TF weighting
- `_cross_asset_cache` + frame injection pattern in `signal_generator_service.py` — exact template for `_htf_intel_cache`
- `_vp_regime_active` logic implied by `distance_to_vah_atr`/`distance_to_val_atr` fields already computed upstream — no new computation needed in trade_framer

### Established Patterns
- `cross_timeframe.py` iterates `intel_<tf>` frame keys (lines 89-92) — FVG/OB data from other TFs is already flowing through; the scoring function is the only missing piece
- `_collect_targets_long/short` candidate system sorts by distance ascending — VP candidates plug in naturally; priority override via insertion order
- `compute_full(frames)` receives full frame dict — HTF data injection is transparent to plugins

### Integration Points
- `cross_timeframe.py` `compute_full()` — add `_score_fvg_alignment()` and `_score_ob_alignment()` scoring methods
- `trade_framer.py` `_collect_targets_long/short` — add VP candidates via `_select_vp(features, tf)` helper; add `_vp_regime_active()` predicate
- `signal_generator_service.py` `__init__` — add `_htf_intel_cache`; update stream consumer to populate it; inject into frames in the bar processing loop
- VWAP/ORB plugins `compute_full()` — add 2-line TF guard at entry point

</code_context>

<specifics>
## Specific Ideas

- Renaissance principle applied throughout: every alignment score contribution is logged in i6 JSONB for full auditability — decomposable, not a black box number
- Proximity decay (1 ATR full → 3 ATR zero) prevents irrelevant historical zones from polluting scores
- Same formula for FVG/OB with separate output fields — let Phase 46 calibration diverge them if data supports it ("let the data speak first")
- HTF context follows zero-new-subscriptions constraint — cache from existing stream, inject via existing pattern

</specifics>

<deferred>
## Deferred Ideas

- **INTEL-04 (roll premium)**: `roll_premium_pct = (front_price - back_price) / back_price` — requires back-month IBKR subscriptions. Deferred to Phase 44 alongside `ROLL_MONITOR_ENABLED=true`. Back-month sub logic belongs in roll monitor, not Phase 41.
- **trade_framer ATR cap tightening**: `ATR_TARGET_MAX_MULTIPLIER=8.0` produces targets many % from price on volatile instruments. Per-TF caps (1m→3 ATR, 5m→5 ATR, 15m→7 ATR) captured as todo: `.planning/todos/pending/2026-03-20-tighten-trade-framer-atr-multiplier-caps-per-tf.md`

</deferred>

---

*Phase: 41-intelligence-gap-fill*
*Context gathered: 2026-03-20*
