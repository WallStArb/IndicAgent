---
phase: 036-microstructure-plugins
verified: 2026-03-18T07:30:00Z
status: passed
score: 8/8 must-haves verified
re_verification: false
---

# Phase 036: Microstructure Plugins Verification Report

**Phase Goal:** Add OFI and CVD as I1 microstructure indicator plugins, then create 7 I7 trading plugins that consume these features.
**Verified:** 2026-03-18T07:30:00Z
**Status:** passed
**Re-verification:** No — initial verification

---

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | OFI features (ofi_ewma_5, ofi_ewma_20, ofi_divergence, ofi_spike_z, ofi_variant) appear in I1 output on every bar | VERIFIED | `src/intelligence/indicators/ofi.py` returns all 5 fields; wired into indicator_service via `_tick_buffers.pop(symbol, [])` at bar close |
| 2 | CVD features (cvd, cvd_slope_5bar, cvd_divergence, cvd_spike_z) appear in I1 output on every bar | VERIFIED | `src/intelligence/indicators/cvd.py` returns all 4 fields; same tick_buffer injection path |
| 3 | When tick_buffer is empty, OFI falls back to bar-level proxy and sets ofi_variant='proxy' | VERIFIED | `ofi.py` line 48-51: `if tick_buf: ... variant="tick"` else `... variant="proxy"` |
| 4 | When tick_buffer is populated, OFI uses tick rule and sets ofi_variant='tick' | VERIFIED | `_compute_tick_ofi()` method uses sequential price comparison to classify buy/sell volume |
| 5 | CVD resets to 0 at session open (09:30 ET) | VERIFIED | `cvd.py` lines 58-64: `et_hour==9 and et_minute>=30 and et_date != last_session_date` → resets `cum_cvd=0.0` using `ZoneInfo("America/New_York")` |
| 6 | indicator_service buffers ticks from market.ticks topic and injects them into I1 plugin frames | VERIFIED | `indicator_service.py` has `self._tick_buffers: dict[str, list[dict]] = defaultdict(list)`, `_process_tick_data()` consumer loop, `group_id="indicator_service_ticks"`, and `tick_buf = self._tick_buffers.pop(symbol, [])` in `_process_single_bar` |
| 7 | All 7 I7 OFI/CVD plugins appear in TIER_I7 and validate_tier() passes | VERIFIED | Runtime confirms TIER_I7=35; all 7 names in TIER_I7: trad_OFIContinuation, trad_OFIDivergence, trad_OFISpike, trad_CVDDivergence, trad_CVDSpike, trad_DeltaExhaustion, trad_DualDivergence |
| 8 | trad_DualDivergence starts in shadow mode and signal_generator_service marks its entries is_shadow=True | VERIFIED | `dual_divergence.py` line 47: `IS_SHADOW: bool = True`; `signal_generator_service.py` lines 1259-1264: IS_SHADOW attribute check marks all matching entries `entry.is_shadow = True` |

**Score:** 8/8 truths verified

---

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `src/intelligence/indicators/ofi.py` | OFIPlugin I1 feature computation | VERIFIED | 132 lines; `class OFIPlugin`, `name="ind_OFI"`, `_compute_tick_ofi()`, `_compute_proxy_ofi()`, `plugin = OFIPlugin()` at module level |
| `src/intelligence/indicators/cvd.py` | CVDPlugin I1 feature computation | VERIFIED | 167 lines; `class CVDPlugin`, `name="ind_CVD"`, ET session reset, `plugin = CVDPlugin()` at module level |
| `services/indicator_service.py` | Tick consumer + buffer injection | VERIFIED | Contains `_tick_buffers`, `topic_market_ticks` import, `group_id="indicator_service_ticks"`, `_process_tick_data()`, seed path uses `tick_buffer=[]` |
| `src/intelligence/trading/ofi_continuation.py` | trad_OFIContinuation I7 plugin | VERIFIED | `name="trad_OFIContinuation"`, `regime_type="trend"`, 5-bar consecutive gate, `_no_signal()`, `plugin = OFIContinuationPlugin()` |
| `src/intelligence/trading/ofi_divergence.py` | trad_OFIDivergence I7 plugin | VERIFIED | `name="trad_OFIDivergence"`, `regime_type="mean_reversion"`, `abs(ofi_divergence) >= 1.5` gate, `plugin = OFIDivergencePlugin()` |
| `src/intelligence/trading/ofi_spike.py` | trad_OFISpike I7 plugin | VERIFIED | `name="trad_OFISpike"`, `regime_type="any"`, stateless, `abs(ofi_spike_z) > 2.0` gate, `plugin = OFISpikePlugin()` |
| `src/intelligence/trading/cvd_divergence.py` | trad_CVDDivergence I7 plugin | VERIFIED | `name="trad_CVDDivergence"`, `regime_type="mean_reversion"`, `dual_divergence` flag in outputs and computed/logged, N=3 confirmation |
| `src/intelligence/trading/cvd_spike.py` | trad_CVDSpike I7 plugin | VERIFIED | `name="trad_CVDSpike"`, `regime_type="any"`, `abs(cvd_spike_z) > 2.0` gate |
| `src/intelligence/trading/delta_exhaustion.py` | trad_DeltaExhaustion I7 plugin | VERIFIED | `name="trad_DeltaExhaustion"`, `regime_type="mean_reversion"`, `abs(cvd_spike_z) > 1.5 AND price_change < 0.3*ATR` gate |
| `src/intelligence/trading/dual_divergence.py` | trad_DualDivergence I7 shadow plugin | VERIFIED | `name="trad_DualDivergence"`, `IS_SHADOW: bool = True`, `regime_type="mean_reversion"`, dual gate (both OFI AND CVD), N=3 confirmation |
| `tests/unit/intelligence/indicators/test_ofi.py` | OFI unit tests | VERIFIED | 9 tests covering proxy/tick paths, EWMA convergence, divergence, spike z-score, min_lookback guard |
| `tests/unit/intelligence/indicators/test_cvd.py` | CVD unit tests | VERIFIED | 10 tests covering accumulation, session reset, slope, divergence, spike z-score, proxy fallback |
| `tests/unit/intelligence/trading/test_ofi_plugins.py` | OFI I7 plugin tests | VERIFIED | 27 tests covering OFIContinuation, OFIDivergence, OFISpike — fire conditions and no-signal conditions |
| `tests/unit/intelligence/trading/test_cvd_plugins.py` | CVD I7 plugin tests | VERIFIED | 27 tests covering CVDDivergence, CVDSpike, DeltaExhaustion |
| `tests/unit/intelligence/trading/test_dual_divergence.py` | DualDivergence shadow plugin tests | VERIFIED | 10 tests including IS_SHADOW=True assertion, dual-gate requirement |

---

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `services/indicator_service.py` | `src/intelligence/indicators/ofi.py` | `frames['tick_buffer']` injection in `_process_single_bar` | WIRED | `tick_buf = self._tick_buffers.pop(symbol, [])` then `frames = {"main": ..., "tick_buffer": tick_buf}` at line ~394-395 |
| `services/indicator_service.py` | `src/intelligence/indicators/cvd.py` | `frames['tick_buffer']` injection in `_process_single_bar` | WIRED | Same injection path — both OFI and CVD receive `tick_buffer` from the same `frames` dict |
| `src/intelligence/indicators/ofi.py` | I1Indicators (schemas.py) | `extra='allow'` passes ofi_* fields through typed bus | WIRED | `ofi_ewma_20` and other fields flow through as extra fields; no schema change required |
| `src/intelligence/trading/ofi_spike.py` | I1 features | `frames.get('features').get('ofi_spike_z')` | WIRED | Line 57: `ofi_spike_z = features.get("ofi_spike_z")` |
| `src/intelligence/trading/cvd_divergence.py` | I1 features | `frames.get('features').get('cvd_divergence')` | WIRED | Lines 68-69: reads `cvd_divergence` and `cvd_slope_5bar` from features |
| `src/intelligence/trading/dual_divergence.py` | I1 features | `frames.get('features').get('ofi_divergence') and get('cvd_divergence')` | WIRED | Lines 75-77: reads both `ofi_divergence` and `cvd_divergence` from features dict |
| `src/intelligence/register_plugins.py` | all 7 I7 plugins | TIER_I7 list + register_pattern() calls | WIRED | All 7 imports present (lines 93-110), all 7 `register_pattern()` calls (lines 300-306), all 7 names in TIER_I7 (lines 452-458) |
| `src/intelligence/trading/aggregator.py` | trad_OFIContinuation | TREND_SETUPS set | WIRED | Line 57: `"trad_OFIContinuation"` added to TREND_SETUPS frozenset |
| `services/signal_generator_service.py` | trad_DualDivergence | IS_SHADOW class attribute check | WIRED | Lines 1259-1264: `getattr(plugin_instance, "IS_SHADOW", False)` → `entry.is_shadow = True` |

---

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|------------|-------------|--------|----------|
| OFI-01 | 036-01 | Tick data availability audited; bar-level OFI proxy implemented as fallback; ofi_variant documented | SATISFIED | `ofi.py` implements both tick path (primary) and `(close-low)/(high-low+ε)*volume` proxy; `ofi_variant` field returned on every bar |
| OFI-02 | 036-01 | `ofi_ewma_20` and `ofi_divergence` computed as I1 features; EWMA spans 5-bar and 20-bar | SATISFIED | `ofi_ewma_5` and `ofi_ewma_20` both computed via EWMA state; divergence = OFI direction vs price direction |
| OFI-03 | 036-02 | New I7 plugin with three variants: continuation, divergence, spike; registered in TIER_I7 | SATISFIED (naming deviation) | All three variant behaviors exist as separate plugins: `trad_OFIContinuation`, `trad_OFIDivergence`, `trad_OFISpike`. REQUIREMENTS.md named the single plugin `trad_OrderFlowImbalance` but the plan and implementation chose three separate plugins — all three are in TIER_I7. The intent (three variants in TIER_I7) is fully met; the name `trad_OrderFlowImbalance` does not exist. REQUIREMENTS.md is already marked [x] complete. |
| CVD-01 | 036-01 | CVD computed as I1 feature; outputs `cvd`, `cvd_slope_5bar`, `cvd_divergence` | SATISFIED | `cvd.py` computes all three outputs plus `cvd_spike_z`; cumulative delta via tick rule or proxy |
| CVD-02 | 036-02 | `trad_CVDDivergence` I7 plugin; CVD direction diverges from price; dual OFI+CVD convergence logged | SATISFIED | `cvd_divergence.py` implements name=`trad_CVDDivergence` with N=3 confirmation and `dual_divergence` flag always logged on fire; registered in TIER_I7 |

**Note on OFI-03 naming:** REQUIREMENTS.md specified a single `trad_OrderFlowImbalance` plugin with three variants. The implementation chose three independent plugins (`trad_OFIContinuation`, `trad_OFIDivergence`, `trad_OFISpike`). The behavioral intent — three variant setups registered in TIER_I7 — is fully satisfied. This is an improvement over the spec (separate plugins are cleaner, independently testable, and have correct `regime_type` per variant). The REQUIREMENTS.md entry is already marked complete.

---

### Anti-Patterns Found

No anti-patterns found in any phase 036 files:
- No TODO/FIXME/PLACEHOLDER comments
- No stub return values (`return null`, `return {}`, `return []`)
- No empty handlers
- All plugins have substantive gate logic, compute real values, and return structured output dicts

---

### Test Suite Results

All 89 phase-related tests pass:

- `tests/unit/intelligence/indicators/test_ofi.py` — 9 tests
- `tests/unit/intelligence/indicators/test_cvd.py` — 10 tests
- `tests/unit/intelligence/trading/test_ofi_plugins.py` — 27 tests
- `tests/unit/intelligence/trading/test_cvd_plugins.py` — 27 tests
- `tests/unit/intelligence/trading/test_dual_divergence.py` — 10 tests
- `tests/unit/intelligence/test_i7_registration.py` — updated: TIER_I7=35, total=120
- `tests/unit/intelligence/test_plugin_registry.py` — updated: TIER_I1=27, TIER_I7=35

**89 passed, 0 failed, 1 warning (unrelated pytest mark)**

---

### Human Verification Required

None. All critical behaviors are verifiable programmatically:
- Plugin file contents (read and verified)
- TIER counts (runtime confirmed: I1=27, I7=35)
- Key link patterns (grep confirmed injection, registration, IS_SHADOW wiring)
- Test suite (all 89 pass)

The tick path vs proxy path behavior has 19 unit tests covering both paths explicitly, making human verification of live tick buffering unnecessary for this phase gate.

---

## Summary

Phase 036 goal is fully achieved. All 9 artifacts exist, are substantive (no stubs), and are wired. All 89 tests pass. The 5 requirement IDs (OFI-01, OFI-02, OFI-03, CVD-01, CVD-02) are satisfied, with a minor naming deviation on OFI-03 (three separate plugins instead of one named `trad_OrderFlowImbalance`) that represents a better design choice and is already accepted in REQUIREMENTS.md.

---

_Verified: 2026-03-18T07:30:00Z_
_Verifier: Claude (gsd-verifier)_
