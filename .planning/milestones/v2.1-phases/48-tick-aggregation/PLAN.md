# Phase 48: Tick Aggregation & I7 Quality

**Status:** 🚧 Part 1 ✅ Complete | Part 2 🚧 In Progress

**Progress:**
- ✅ **Part 1:** Tick Aggregation (5s→1m bars) - SHIPPED March 22, 2026
- 🚧 **Part 2:** I7 Trading Layer Refactoring - 4/10 subtasks complete (I6 violations fixed)

**Goals:**
1. ✅ ~~Verify and complete tick aggregation feature (5s real-time bars → 1m OHLCV)~~
2. I7 trading layer refactoring for code reuse, quality, and efficiency

**Current Focus:** Part 2 - I7 Trading Layer Refactoring (I6 Confluence ✅ Complete, Code Reuse next)

---

## Part 1: Tick Aggregation ✅ COMPLETE

### What Was Done (March 21-22, 2026)
- ✅ Implemented `stream_real_time_bars()` in IBKRProvider
- ✅ Replaced `poll_1m_bars()` and `_tick_loop` with `_rtb_loop` and `_emit_bar`
- ✅ 5s bars from IBKR aggregate to 1m OHLCV
- ✅ 5s close published to `market.ticks` for live dashboard pricing
- ✅ Fixes after-hours freeze; works 24/7 for crypto/FX
- ✅ 2664 tests passing

### ✅ Completed (March 21-22, 2026)
- ✅ Implemented `stream_real_time_bars()` in IBKRProvider
- ✅ Replaced `poll_1m_bars()` and `_tick_loop` with `_rtb_loop` and `_emit_bar`
- ✅ 5s bars from IBKR aggregate to 1m OHLCV
- ✅ 5s close published to `market.ticks` for live dashboard pricing
- ✅ Fixes after-hours freeze; works 24/7 for crypto/FX
- ✅ TWS daemon runs without `bars_processed` freeze
- ✅ After-hours data flows correctly (verified in logs)
- ✅ Dashboard live pricing updates work
- ✅ CLAUDE.md updated with new architecture
- ✅ All tests passing (2664+)

---

## Part 2: I7 Trading Layer Refactoring (Simplify Review Findings) 🚧

**Quick Status:**
- Code Reuse (2.1-2.3): ⬜ Not Started (~550 line savings potential)
- I6 Confluence (2.4-2.7): ✅ COMPLETE (4 plugins fixed, 4 commits)
- Efficiency (2.8-2.10): ⬜ Not Started (performance improvements)

---

### HIGH Priority - Code Reuse (450-600 line savings)

#### 2.1 Extract Microstructure Spike Detector
**Files affected:**
- `src/intelligence/trading/ofi_spike.py` (115 lines)
- `src/intelligence/trading/cvd_spike.py` (118 lines)

**Action:** Create `microstructure_utils.py` with shared `detect_spike_signal()` function

**Impact:** ~180 lines saved, 2 plugins improved

#### 2.2 Extract Divergence Confirmation Counter
**Files affected:**
- `src/intelligence/trading/cvd_divergence.py` (lines 86-98)
- `src/intelligence/trading/dual_divergence.py` (lines 102-113)
- `src/intelligence/trading/ofi_continuation.py` (lines 78-87)

**Action:** Create `state_utils.py` with `track_consecutive_state()` function

**Impact:** ~90 lines saved, 3 plugins improved

#### 2.3 Extract Volume Profile Rejection Pattern
**Files affected:**
- `src/intelligence/trading/poc_rejection.py` (199 lines)
- `src/intelligence/trading/hvn_rejection.py` (219 lines)

**Action:** Create `volume_profile_utils.py` with `detect_vp_rejection()` function

**Impact:** ~280 lines saved, 2 plugins improved

---

### HIGH Priority - I6 Confluence Violations (Renaissance Principle)

**Issue:** 4 SMC/FVG plugins NOT consuming I6 `ctf_*` scores in confidence calculations

#### 2.4 Fix I6 Confluence in fvg_fill.py ✅ COMPLETE
**Commit:** bb76b2a - "fix(i7): consume I6 ctf_* scores in fvg_fill"

**Fixed:** Added `ctf_fvg_alignment` (0.08 weight) and `ctf_ob_alignment` (0.06 weight)

#### 2.5 Fix I6 Confluence in choch_reversal.py ✅ COMPLETE
**Commit:** 8a01c3c - "fix(i7): consume I6 ctf_* scores in choch_reversal"

**Fixed:** Added `ctf_structure_alignment` (0.08), `ctf_trend_alignment` (0.06), `ctf_score` (0.05)

#### 2.6 Fix I6 Confluence in liquidity_sweep_reclaim.py ✅ COMPLETE
**Commit:** 6d1c3ec - "fix(i7): magnitude-weight I6 ctf_score in liquidity_sweep_reclaim"

**Fixed:** Changed binary gate to magnitude-weighted boost (0.05 * abs(ctf) / 0.5, max 2.0x)

#### 2.7 Fix I6 Confluence in supply_demand_setup.py ✅ COMPLETE
**Commit:** 24bb7a8 - "fix(i7): magnitude-weight I6 ctf_score in supply_demand_setup"

**Fixed:** Changed binary gate to magnitude-weighted boost (0.05 * abs(ctf) / 0.5, max 2.0x)

---

### MEDIUM Priority - Additional Efficiency Improvements

#### 2.8 Batch Calibration Interpolation in aggregator
**File:** `src/intelligence/trading/aggregator.py` (lines 456-469)

**Current:** `np.interp()` called per-signal in loop
**Fix:** Group by plugin_name, batch interpolate per plugin

**Impact:** Reduces np.interp calls from 36 to ~6 per bar

#### 2.9 Optimize Plugin Gate Ordering
**Files:** All 36 I7 plugins

**Current:** `extract_ohlcv()` called before cheap regime gate
**Fix:** Check regime gate first, only extract OHLCV if gate passes

**Impact:** Skips ~144 numpy conversions per bar (80% early exit rate)

#### 2.10 Extract Additional Shared Utilities
- VWAP position calculator (vwap_utils.py, 60 lines saved)
- S/R proximity score (plugin_utils.py, 30 lines saved)
- Zone stop loss calculator (atr_utils.py, 40 lines saved)

---

## Execution Order

### Week 1: Code Reuse (Part 2.1-2.3)
1. Create `microstructure_utils.py`
2. Create `state_utils.py`
3. Create `volume_profile_utils.py`
4. Refactor OFI/CVD spike plugins
5. Refactor divergence plugins
6. Refactor VP rejection plugins

### Week 2: I6 Confluence (Part 2.4-2.7)
1. Fix fvg_fill.py I6 confluence
2. Fix choch_reversal.py I6 confluence
3. Fix liquidity_sweep_reclaim.py I6 confluence
4. Fix supply_demand_setup.py I6 confluence
5. Verify all 36 plugins consume relevant I6 scores

### Week 3: Efficiency + Verification (Part 2.8-2.10)
1. Optimize aggregator calibration batching
2. Optimize plugin gate ordering (all 36 plugins)
3. Extract remaining shared utilities
4. Run full test suite to verify no regressions

---

## Success Criteria

### Part 1 (Tick Aggregation) ✅ COMPLETE
- [x] TWS daemon runs without `bars_processed` freeze
- [x] After-hours data flows correctly (verified in logs)
- [x] 1m bar drift within tolerance (< 0.1% of ATR)
- [x] Dashboard pricing updates live
- [x] CLAUDE.md updated with new architecture

### Part 2 (I7 Refactoring) 🚧 IN PROGRESS
- [ ] 2.1: Extract microstructure spike detector (~180 lines saved)
- [ ] 2.2: Extract divergence confirmation counter (~90 lines saved)
- [ ] 2.3: Extract volume profile rejection pattern (~280 lines saved)
- [ ] 2.4: Fix fvg_fill.py I6 confluence
- [ ] 2.5: Fix choch_reversal.py I6 confluence
- [ ] 2.6: Fix liquidity_sweep_reclaim.py I6 confluence
- [ ] 2.7: Fix supply_demand_setup.py I6 confluence
- [ ] 2.8: Optimize aggregator calibration batching
- [ ] 2.9: Optimize plugin gate ordering (36 plugins)
- [ ] 2.10: Extract additional shared utilities (~130 lines saved)

**Expected Impact:**
- 550-730 lines of duplicate code eliminated
- 4 I6 confluence violations fixed (Renaissance principle)
- Per-bar latency reduced by 40-60%
- All 36 plugins consuming relevant I6 ctf_* scores

---

## Dependencies

**Requires:**
- None (standalone refactor)

**Blocks:**
- Phase 49 (DB Performance) — should complete before DB optimization work
- Phase 54-55 (ML Foundation) — clean I7 layer required for ML training data

---

## Notes

- **Renaissance Principle:** Never merge OFI/CVD/VWAP/liquidity signal identities. Extract computation utilities while preserving separate ML feature columns.
- **Backward Compatibility:** All refactors must maintain existing signal outputs. No breaking changes to signal_ledger schema.
- **Testing:** Run full test suite after each utility extraction. Verify shadow capture data unchanged.
