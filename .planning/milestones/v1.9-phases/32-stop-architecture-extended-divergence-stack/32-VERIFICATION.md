---
phase: 32-stop-architecture-extended-divergence-stack
verified: 2026-03-17T12:00:00Z
status: passed
score: 9/9 must-haves verified
re_verification: false
gaps: []
---

# Phase 32: Stop Architecture + Extended Divergence Stack — Verification Report

**Phase Goal:** Centralize stop architecture with GARCH-adaptive scaling and FVG priority, extend lifecycle layer with Chandelier trailing stop and staleness-based condition_expired, and expand divergence intelligence from 2-input AND-gate to 5-input weighted convergence with 3 new I5 divergence plugins.
**Verified:** 2026-03-17T12:00:00Z
**Status:** PASSED
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | `frame_trade()` applies GARCH multiplier {0:0.8, 1:1.0, 2:1.35} to effective_atr before all stop/target calculations | VERIFIED | `GARCH_MULTIPLIERS` dict at line 86 of `trade_framer.py`; `effective_atr = atr * GARCH_MULTIPLIERS.get(garch_regime_int, 1.0)` applied in `frame_trade()` lines 722-724 |
| 2 | FVG is Priority 0 structural stop — `fvg_bottom` for longs, `fvg_top` for shorts — ahead of demand zone | VERIFIED | `_resolve_stop_long()` line 382 handles "Priority 0: FVG low"; `_resolve_stop_short()` line 433 handles "Priority 0: FVG high" |
| 3 | `stop_basis` field classifies every stop into structure_snap / garch_adaptive / atr_static with 1.5xATR proximity gate | VERIFIED | `_classify_stop_basis()` function lines 166-207; `STRUCTURE_SNAP_PROXIMITY_ATR = 1.5` line 91; populated on every TradeFrame returned |
| 4 | `LedgerEntry.to_insert_params()` returns 54 elements; `_INSERT_SQL` has $1..$54 | VERIFIED | `signal_ledger.py` docstring "54-element tuple"; `$54` at line 175; 15 new fields starting `stop_basis` at $40 |
| 5 | Chandelier trailing stop computed with `garch_sigma` or ATR-14 fallback; tightens monotonically; `condition_expired` fires after 3 consecutive bars above 0.5 staleness | VERIFIED | `compute_chandelier_stop()` and `compute_staleness_score()` in `lifecycle_tracker.py`; `chandelier_state` mutated in-place; `staleness_consecutive_bars >= 3 and staleness_score > 0.5` gate at line 243 |
| 6 | `signal_lifecycle_service.py` manages per-signal Chandelier state, staleness consecutive counter, and shadow tracking state machine | VERIFIED | `_chandelier_state`, `_staleness_consecutive`, `_shadow_signals` dicts in `__init__`; Chandelier initialized on first active bar; `compute_staleness_score` imported and called; `_reseed_chandelier_state()` on startup |
| 7 | `MACDDivergencePlugin` and `CMFDivergencePlugin` are new I5 plugins registered in TIER_I5; `VolumeDivergencePlugin` extended with `obv_div_*` outputs computed independently | VERIFIED | `macd_divergence.py` has `MACDDivergencePlugin` with outputs `{macd_div_bullish, macd_div_bearish, macd_div_strength}`; `cmf_divergence.py` has `CMFDivergencePlugin`; `volume_divergence.py` computes `obv_div_*` via independent linreg (not aliased); both new plugins in `TIER_I5` (lines 357-358 of `register_plugins.py`) |
| 8 | `DivergenceStackPlugin` uses 5-input weighted score (RSI 0.30, MACD 0.25, vol 0.20, OBV 0.15, CMF 0.10); gate: score > 0.40 AND n_agreeing >= 3; LOCKED DESIGN removed | VERIFIED | `DIVERGENCE_WEIGHTS` dict and `DIVERGENCE_SCORE_THRESHOLD = 0.40`, `DIVERGENCE_MIN_AGREEING = 3` in `divergence_stack.py`; `LOCKED DESIGN` not present in file; always-log `base_output` returned on every bar |
| 9 | `div_weighted_score` / divergence scoring and `stop_basis` fields flow to `intelligence_features.i7` JSONB on every bar via `_build_i7_payload()` | VERIFIED | `_build_i7_payload()` in `signal_generator_service.py` includes `stop_basis`, `stop_structure_type`, `structural_stop_distance_atr`, `stop_structure_age_bars`, `chandelier_vol_source` in per-signal dict (lines 395-399); `divergence_scoring` parameter populated from `div_weighted_score` in plugin_metadata (lines 859-861) and passed to payload (line 1150) |

**Score: 9/9 truths verified**

---

### Required Artifacts

| Artifact | Status | Evidence |
|----------|--------|----------|
| `production/migrations/035_stop_basis_and_divergence_stack.sql` | VERIFIED | Exists; 15 `ALTER TABLE signal_ledger ADD COLUMN IF NOT EXISTS` statements for all required columns including `chandelier_vol_source`, `trailing_stop_price JSONB`, `shadow_outcome`, etc.; partial index on `stop_basis` |
| `src/intelligence/trading/trade_framer.py` | VERIFIED | `GARCH_MULTIPLIERS`, `STRUCTURE_SNAP_PROXIMITY_ATR`, `_classify_stop_basis()`, `_stop_type_to_structure_type()`, `_get_structure_age_bars()`, FVG Priority 0 in both stop hierarchies, 4 new `TradeFrame` fields all present |
| `src/intelligence/trading/signal_ledger.py` | VERIFIED | 15 new `LedgerEntry` fields after `is_shadow`; `to_insert_params()` returns 54-element tuple; `_INSERT_SQL` has $40–$54; `stop_basis` appears 4+ times (field def, to_insert_params, _INSERT_SQL, SQL string) |
| `services/signal_generator_service.py` | VERIFIED | `TF_TTL_BARS = {"1m":20,"5m":12,"15m":8,"1h":6}`; `hmm_regime_at_fire` and `garch_sigma_at_fire` captured from features; TradeFrame stop fields copied into signal dict and LedgerEntry; `_build_i7_payload()` includes stop_basis and divergence_scoring |
| `src/intelligence/trading/lifecycle_tracker.py` | VERIFIED | `compute_chandelier_stop()` and `compute_staleness_score()` pure functions; `evaluate_signal()` extended with `chandelier_state`, `staleness_consecutive_bars`, `staleness_score` params; return type unchanged (`Transition | None`) |
| `services/signal_lifecycle_service.py` | VERIFIED | Three state dicts; Chandelier init with garch_sigma/atr_14 priority; `chandelier_vol_source` written via COALESCE guard; staleness counter per bar; shadow tracking on `condition_expired`; `_reseed_chandelier_state()` on startup; cleanup on signal resolution |
| `src/intelligence/patterns/macd_divergence.py` | VERIFIED | `MACDDivergencePlugin` with outputs `{macd_div_bullish, macd_div_bearish, macd_div_strength}`, `min_lookback=50` |
| `src/intelligence/patterns/cmf_divergence.py` | VERIFIED | `CMFDivergencePlugin` with outputs `{cmf_div_bullish, cmf_div_bearish, cmf_div_strength}`, `min_lookback=30` |
| `src/intelligence/patterns/volume_divergence.py` | VERIFIED | `obv_div_*` outputs added to frozenset; computed independently from OBV cumulative series via separate `_linreg_slope()` calls (lines 75-90); not aliased from `vol_div_*` |
| `src/intelligence/trading/divergence_stack.py` | VERIFIED | `DIVERGENCE_WEIGHTS` dict; 5-input weighted score; `div_weighted_score` and `div_n_agreeing` in `base_output` returned every bar; "LOCKED DESIGN" absent |
| `src/intelligence/schemas.py` | VERIFIED | `macd_div_bullish`, `cmf_div_bullish`, `obv_div_bullish` (and bearish/strength variants) present in `I5Patterns` |
| `src/intelligence/register_plugins.py` | VERIFIED | `macd_div_plugin` and `cmf_div_plugin` imported, instantiated, registered in `register_all_plugins()`, and appended to `TIER_I5` |
| `tests/unit/test_trade_framer.py` | VERIFIED | 21 TDD tests; 21/21 pass |
| `tests/unit/intelligence/test_lifecycle_tracker.py` | VERIFIED | 65 tests (60 existing + 5 new service integration); all pass |
| `tests/unit/test_macd_divergence.py` | VERIFIED | Tests collected and passing |
| `tests/unit/test_cmf_divergence.py` | VERIFIED | Tests collected and passing |
| `tests/unit/test_divergence_stack.py` | VERIFIED | 21 tests; pass |

---

### Key Link Verification

| From | To | Via | Status | Evidence |
|------|----|-----|--------|----------|
| `trade_framer.py` | `signal_ledger.py` | TradeFrame fields mapped to LedgerEntry | WIRED | `signal_generator_service.py` lines 342-347: `stop_basis=sig.get("stop_basis")` and related fields copied from sig dict (which comes from frame) into `LedgerEntry` |
| `signal_generator_service.py` | `signal_ledger.py` | `hmm_regime_at_fire`, `garch_sigma_at_fire` written at signal fire | WIRED | Lines 996-997: `"hmm_regime_at_fire": features.get("hmm_regime")` captured from live features at fire time |
| `signal_generator_service.py` | `feature_writer_service.py` (via i7 topic) | `_build_i7_payload()` includes stop_basis + divergence_scoring | WIRED | Lines 395-399: stop_basis fields in per-signal dict; lines 859-861 + 1150: divergence_scoring block populated and passed to payload function |
| `signal_lifecycle_service.py` | `lifecycle_tracker.py` | Chandelier/staleness state injected as parameters | WIRED | `evaluate_signal()` called with `chandelier_state=self._chandelier_state.get(sid)` and `staleness_consecutive_bars`, `staleness_score` parameters |
| `signal_lifecycle_service.py` | `signal_ledger.py` | `trailing_stop_price` JSONB, `chandelier_vol_source`, staleness written per tick | WIRED | SQL UPDATE at line 60-64 in lifecycle_service; `chandelier_vol_source` via COALESCE guard at line 588 |
| `macd_divergence.py` | `schemas.py` | I5Patterns has `macd_div_*` fields | WIRED | `schemas.py` lines 419-421: `macd_div_bullish`, `macd_div_bearish`, `macd_div_strength` declared |
| `divergence_stack.py` | `macd_divergence.py` | Reads `macd_div_bullish/bearish` from features dict | WIRED | `divergence_stack.py` line 100: `features.get("macd_div_bullish")`, `features.get("macd_div_bearish")` |
| `register_plugins.py` | `macd_divergence.py` / `cmf_divergence.py` | Plugins registered in TIER_I5 | WIRED | Lines 50-51 (imports), 133 (validate_schema_coverage call), 203-204 (register_pattern), 357-358 (TIER_I5 list) |

---

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|------------|-------------|--------|----------|
| SIG-01 | 32-01 | Structure-first stop placement; `stop_basis` field logged | SATISFIED | `_classify_stop_basis()` returns structure_snap/garch_adaptive/atr_static; `stop_basis` written to `signal_ledger` via LedgerEntry $40 |
| SIG-02 | 32-01 | All I7 plugins inherit GARCH-adaptive ATR scaling via `trade_framer.py` | SATISFIED | `GARCH_MULTIPLIERS {0:0.8, 1:1.0, 2:1.35}` applied to `effective_atr` in `frame_trade()` before calling any stop/target resolver |
| SIG-03 | 32-02 | Chandelier Exit trailing stop; tightens monotonically; `trailing_stop_price` logged | SATISFIED | `compute_chandelier_stop()` in `lifecycle_tracker.py`; tighten-only invariant in state update block; `trailing_stop_price` JSONB history appended per bar |
| SIG-04 | 32-02 | Staleness score per bar; regime-flip or vol-drift triggers `condition_expired`; fire-time snapshots in `signal_ledger` | SATISFIED | `compute_staleness_score()` computed per bar; 3-bar confirmation gate; `hmm_regime_at_fire` and `garch_sigma_at_fire` stored in `signal_ledger` |
| SIG-05 | 32-01 | Per-TF TTL constants; signals expire correctly | SATISFIED | `TF_TTL_BARS = {"1m":20, "5m":12, "15m":8, "1h":6}` in `signal_generator_service.py`; applied at line 905-907 |
| DIV-01 | 32-03 | New I5 plugin `macd_divergence.py` with `macd_div_bullish/bearish` outputs | SATISFIED | `MACDDivergencePlugin` in `src/intelligence/patterns/macd_divergence.py`; outputs `{macd_div_bullish, macd_div_bearish, macd_div_strength}` |
| DIV-02 | 32-03 | `volume_divergence.py` extended with `obv_div_*` from OBV series | SATISFIED | `obv_div_bullish/bearish/strength` outputs added; computed via independent `_linreg_slope()` on OBV cumulative series (not aliased) |
| DIV-03 | 32-03 | New I5 plugin `cmf_divergence.py` with `cmf_div_bullish/bearish` outputs | SATISFIED | `CMFDivergencePlugin` in `src/intelligence/patterns/cmf_divergence.py`; outputs `{cmf_div_bullish, cmf_div_bearish, cmf_div_strength}` |
| DIV-04 | 32-03 | `divergence_stack.py` upgraded to 5-input weighted convergence; gate score > 0.40 AND n_agreeing >= 3 | SATISFIED | `DIVERGENCE_WEIGHTS` dict; `DIVERGENCE_SCORE_THRESHOLD = 0.40`; `DIVERGENCE_MIN_AGREEING = 3`; always-log base_output on every bar |

All 9 requirements fully satisfied. No orphaned requirements.

---

### Anti-Patterns Found

No blockers or warnings found. Specific checks:

- No `TODO/FIXME/PLACEHOLDER` comments in modified files
- No stub implementations (`return {}` is the correct early-return pattern for insufficient lookback in plugins)
- `evaluate_signal()` return type is `Transition | None` — unchanged, pure function preserved
- "LOCKED DESIGN" comment confirmed absent from `divergence_stack.py`
- `obv_div_*` outputs confirmed independently computed (not aliased from `vol_div_*`)
- GARCH multiplier applied to `effective_atr` in `frame_trade()`, not to stored `atr` parameter — correctly scoped

---

### Human Verification Required

None. All goal-critical behaviors are verifiable programmatically.

---

### Test Results

| Test File | Count | Result |
|-----------|-------|--------|
| `tests/unit/test_trade_framer.py` | 21 | 21 passed |
| `tests/unit/intelligence/test_lifecycle_tracker.py` | 65 | 65 passed |
| `tests/unit/test_macd_divergence.py` | 14 | 14 passed |
| `tests/unit/test_cmf_divergence.py` | 13 | 13 passed |
| `tests/unit/test_divergence_stack.py` | 21 | 21 passed |
| Full unit suite | 2060 | 2052 passed, 8 pre-existing failures (unchanged from before phase) |

**Pre-existing failures (confirmed unrelated to phase 32):**
- `tests/unit/api/test_signals_route.py::TestGetSignals::test_get_signals_base_symbol_resolved`
- `tests/unit/config/test_settings.py::TestHelperFunctions::*` (4 tests)
- `tests/unit/service_tests/test_feature_writer_config.py::test_default_config_uses_active_contracts`
- `tests/unit/test_historical_backfill.py::TestInsertFeaturesSync::*` (2 tests)

---

### Gaps Summary

No gaps. All 9 observable truths verified, all 9 requirements satisfied, all key links wired.

---

_Verified: 2026-03-17T12:00:00Z_
_Verifier: Claude (gsd-verifier)_
