# Phase 48: Tick Aggregation & I7 Quality

**Status:** 🚧 In Progress

**Goals:**
1. Verify and complete tick aggregation feature (5s real-time bars → 1m OHLCV)
2. I7 trading layer refactoring for code reuse, quality, and efficiency

---

## Part 1: Tick Aggregation (Already Implemented, Needs Verification)

### What Was Done (March 21-22, 2026)
- ✅ Implemented `stream_real_time_bars()` in IBKRProvider
- ✅ Replaced `poll_1m_bars()` and `_tick_loop` with `_rtb_loop` and `_emit_bar`
- ✅ 5s bars from IBKR aggregate to 1m OHLCV
- ✅ 5s close published to `market.ticks` for live dashboard pricing
- ✅ Fixes after-hours freeze; works 24/7 for crypto/FX
- ✅ 2664 tests passing

### What Remains
1. **Verification**: Run TWS daemon in production and verify:
   - No `bars_processed` freeze bug
   - After-hours data flows correctly
   - 1m bars match official IBKR 1m bars (within drift tolerance)
   - Dashboard live pricing updates work

2. **Documentation**: Update CLAUDE.md with new architecture
   - Remove references to old `poll_1m_bars`
   - Document `_rtb_loop` behavior
   - Update TWS daemon section

3. **Monitoring**: Ensure metrics expose:
   - `bars_processed` incrementing normally
   - `tick_rate_per_sec` within acceptable range
   - No error spikes in logs

---

## Part 2: I7 Trading Layer Refactoring (Simplify Review Findings)

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

#### 2.4 Fix I6 Confluence in fvg_fill.py
**Current:** Only uses `apply_exhaustion_boost`
**Missing:** `ctf_fvg_alignment`, `ctf_ob_alignment`

**Fix:** Add I6 confluence consumption (10 lines)

#### 2.5 Fix I6 Confluence in choch_reversal.py
**Current:** Only uses `hmm_regime` for alignment check
**Missing:** `ctf_structure_alignment`, `ctf_trend_alignment`, `ctf_score`

**Fix:** Add I6 confluence consumption (15 lines)

#### 2.6 Fix I6 Confluence in liquidity_sweep_reclaim.py
**Current:** Uses `ctf_score` only as binary gate (> 0.3)
**Issue:** Doesn't incorporate magnitude into confidence

**Fix:** Weight confidence by `ctf_score` magnitude, not binary (5 lines)

#### 2.7 Fix I6 Confluence in supply_demand_setup.py
**Current:** Uses `ctf_score` but likely as binary gate
**Fix:** Verify and fix if needed (5 lines)

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

### Week 3: Efficiency + Verification (Parts 1, 2.8-2.10)
1. Optimize aggregator calibration batching
2. Optimize plugin gate ordering (all 36 plugins)
3. Extract remaining shared utilities
4. Verify tick aggregation in production
5. Update documentation

---

## Success Criteria

### Part 1 (Tick Aggregation)
- [ ] TWS daemon runs without `bars_processed` freeze
- [ ] After-hours data flows correctly (verified in logs)
- [ ] 1m bar drift within tolerance (< 0.1% of ATR)
- [ ] Dashboard pricing updates live
- [ ] CLAUDE.md updated with new architecture

### Part 2 (I7 Refactoring)
- [ ] 3 new utility modules created (microstructure, state, volume_profile)
- [ ] 450-600 lines of duplicate code eliminated
- [ ] All 36 plugins consume relevant I6 ctf_* scores
- [ ] Per-bar latency reduced by 40-60% in aggregator
- [ ] All tests passing (2664+)
- [ ] No regressions in signal quality

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
