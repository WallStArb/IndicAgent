---
phase: 24
slug: second-derivative-acceleration
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-03-10
---

# Phase 24 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 7.x |
| **Config file** | `pytest.ini` (project root) |
| **Quick run command** | `.venv/bin/pytest tests/unit/intelligence/ -v -k "momentum_accel or exhaustion or accel_regime or swing_momentum or hma"` |
| **Full suite command** | `.venv/bin/pytest tests/unit/ -v` |
| **Estimated runtime** | ~30 seconds (quick) / ~120 seconds (full) |

---

## Sampling Rate

- **After every task commit:** Run `.venv/bin/pytest tests/unit/intelligence/ -v -k "momentum_accel or exhaustion or accel_regime or swing_momentum or hma"`
- **After every plan wave:** Run `.venv/bin/pytest tests/unit/ -v`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 30 seconds

---

## Per-Task Verification Map

| Task ID | Component | Wave | Behavior | Test Type | Automated Command | File Exists | Status |
|---------|-----------|------|----------|-----------|-------------------|-------------|--------|
| HMA | HMA (I1) | 1 | `hma_20` computed correctly from WMA formula | unit | `.venv/bin/pytest tests/unit/intelligence/ -v -k "hma"` | ❌ W0 | ⬜ pending |
| MomAccel-extend | MomentumAcceleration | 1 | `rsi_curvature` = second derivative of RSI; 0.0 on first bar | unit | `.venv/bin/pytest tests/unit/intelligence/composites/test_momentum_accel.py -v -k "curvature"` | ✅ (extend) | ⬜ pending |
| MomAccel-extend | MomentumAcceleration | 1 | `macd_hist_slope` reads `macd_histogram_12_26_9` not `macd_12_26_9` | unit | `.venv/bin/pytest tests/unit/intelligence/composites/test_momentum_accel.py -v -k "hist_slope"` | ✅ (extend) | ⬜ pending |
| MomAccel-extend | MomentumAcceleration | 1 | `price_accel` = ATR-normalized 2nd derivative; 0.0 when ATR missing | unit | `.venv/bin/pytest tests/unit/intelligence/composites/test_momentum_accel.py -v -k "price_accel"` | ✅ (extend) | ⬜ pending |
| MomAccel-extend | MomentumAcceleration | 1 | `hma_slope` and `hma_accel` computed from `hma_20` feature | unit | `.venv/bin/pytest tests/unit/intelligence/composites/test_momentum_accel.py -v -k "hma_slope or hma_accel"` | ❌ W0 | ⬜ pending |
| ExhaustionScore | ExhaustionScore (I2) | 2 | Score = 1.0 all 3 conditions; 0.6 for 2/3; 0.2 for 1/3 | unit | `.venv/bin/pytest tests/unit/intelligence/composites/ -v -k "exhaustion"` | ❌ W0 | ⬜ pending |
| ExhaustionScore | ExhaustionScore (I2) | 2 | `exhaustion_bars` counter increments each bar, resets to 0 | unit | `.venv/bin/pytest tests/unit/intelligence/composites/ -v -k "exhaustion_bars"` | ❌ W0 | ⬜ pending |
| ExhaustionScore | ExhaustionScore (I2) | 2 | `exhaustion_side` = "bull"/"bear"/"none" for each case | unit | `.venv/bin/pytest tests/unit/intelligence/composites/ -v -k "exhaustion_side"` | ❌ W0 | ⬜ pending |
| AccelRegime | AccelerationRegime (I2) | 2 | `accel_regime == "peak"` fires exactly on crossing bar | unit | `.venv/bin/pytest tests/unit/intelligence/composites/ -v -k "accel_regime or peak"` | ❌ W0 | ⬜ pending |
| AccelRegime | AccelerationRegime (I2) | 2 | `accel_agreement` = fraction in agreement (0.0–1.0) | unit | `.venv/bin/pytest tests/unit/intelligence/composites/ -v -k "accel_agreement"` | ❌ W0 | ⬜ pending |
| SwingMomentum | SwingMomentum (I3) | 3 | Returns `{}` when fewer than 3 complete swings confirmed | unit | `.venv/bin/pytest tests/unit/intelligence/ -v -k "swing_momentum"` | ❌ W0 | ⬜ pending |
| SwingMomentum | SwingMomentum (I3) | 3 | `struct_energy` formula: amplitude_ratio × speed_factor / 3.0, clamped 0.0–1.0 | unit | `.venv/bin/pytest tests/unit/intelligence/ -v -k "struct_energy"` | ❌ W0 | ⬜ pending |
| SwingMomentum | SwingMomentum (I3) | 3 | `swing_amplitude_expanding = 1` only with 3 monotonically increasing amplitudes | unit | `.venv/bin/pytest tests/unit/intelligence/ -v -k "amplitude_expanding"` | ❌ W0 | ⬜ pending |
| I7-wiring | LiquiditySweepReclaim (I7) | 4 | `exhaustion_score > 0.6` in sweep dir → confidence += 0.1 + "exhaustion_sweep_boost" tag | unit | `.venv/bin/pytest tests/unit/intelligence/ -v -k "sweep_reclaim and exhaustion"` | ❌ W0 | ⬜ pending |
| I7-wiring | LiquidityHunt (I7) | 4 | Same boost pattern as LiquiditySweepReclaim | unit | `.venv/bin/pytest tests/unit/intelligence/ -v -k "liquidity_hunt and exhaustion"` | ❌ W0 | ⬜ pending |
| I7-wiring | MomentumBreakout (I7) | 4 | `exhaustion_score > 0.7` AND `exhaustion_bars >= 3` → confidence -= 0.15 + "exhaustion_guard_penalty" | unit | `.venv/bin/pytest tests/unit/intelligence/ -v -k "momentum_breakout and exhaustion"` | ❌ W0 | ⬜ pending |
| I7-wiring | TrendFollowing (I7) | 4 | Same guard; if confidence < threshold → `_no_signal()` returned | unit | `.venv/bin/pytest tests/unit/intelligence/ -v -k "trend_follow and exhaustion"` | ❌ W0 | ⬜ pending |
| Registration | All new plugins | 1 | `cmp_ExhaustionScore`, `cmp_AccelerationRegime` in TIER_I2; `struct_SwingMomentum` in TIER_I3 | unit | `.venv/bin/pytest tests/unit/intelligence/ -v -k "tier_i2 or tier_i3 or registration"` | ✅ | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/unit/intelligence/composites/test_exhaustion_score.py` — covers ExhaustionScore all conditions (score tiers, side, bars counter)
- [ ] `tests/unit/intelligence/composites/test_acceleration_regime.py` — covers AccelerationRegime regime transitions (peak/trough/building/waning/neutral)
- [ ] `tests/unit/intelligence/test_swing_momentum.py` — covers SwingMomentum warmup gate + struct_energy formula
- [ ] `tests/unit/intelligence/test_hma.py` — covers HMA WMA formula correctness (or extend `test_moving_averages.py`)
- [ ] `tests/unit/intelligence/test_i7_exhaustion_wiring.py` — covers all 4 I7 exhaustion boost/guard wires
- [ ] Extend `tests/unit/intelligence/composites/test_momentum_accel.py` — add test functions for `rsi_curvature`, `macd_hist_slope`, `price_accel`, `hma_slope`, `hma_accel`

---

## Key Edge Cases

1. **rsi_curvature state ordering:** Call plugin twice; verify bar 2 curvature = accel[bar2] − accel[bar1] (reads OLD prev_rsi_accel before write)
2. **macd_hist_slope uses state not prev_features:** Mock frames with different values in `prev_features["macd_histogram_12_26_9"]` vs `_state["prev_macd_histogram"]` — plugin must use state value
3. **price_accel with exactly 3 close values:** `len(df) == 3` is the minimum; verify it works
4. **ExhaustionScore partial exhaustion:** RSI > 70 + rsi_curvature < 0 but macd_hist_slope >= 0 → score = 0.6, side = "bull"
5. **AccelerationRegime trough:** `prev_accel_score < -0.3` AND `accel_score >= -0.3` → regime = "trough"; following bar re-classifies
6. **SwingMomentum with exactly 5 extremes:** Must return `{}` (needs 6 for 3 complete swings)
7. **SwingMomentum ATR=0 fallback:** Use raw price amplitude for ratio without ATR normalization
8. **I7 boost cap:** Total confidence cannot exceed 0.95 after all boosts applied
9. **I7 suppression threshold:** MomentumBreakout/TrendFollowing must check actual fire threshold after penalty — not hardcoded 0.0

---

## Manual-Only Verifications

| Behavior | Why Manual | Test Instructions |
|----------|------------|-------------------|
| 17 new features appear in `intelligence_features` live stream | Requires live pipeline | Restart market_analysis_service; check Redis stream payload for new keys |
| I7 signals adjust correctly under exhaustion conditions | Requires live market data | Monitor signal_ledger for confidence adjustments with exhaustion_score present |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 30s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
