# Plugin Infrastructure: Shared Code Abstraction

**Date:** 2026-05-21
**Status:** Post-review revision - incorporating cross-AI feedback
**Scope:** Reduce duplication across 132 plugins (I1-I7) through promoted shared utilities
**Sequencing:** After Phase 093 (shipped); can execute opportunistically alongside other phases

---

## Motivation

132 plugins across 7 tiers share identical structural patterns. A bug fix or pattern change currently requires editing dozens of files. Phase 093 fixed mathematical bugs in individual plugins; this work extracts the common code so future fixes touch one place, not 132.

The IncrementalPlugin ABC is **revised**. Deep analysis found 5 HIGH severity production bugs in incremental plugins that justify a targeted `IncrementalMixin` for the 31 genuine incremental plugins. Full ABC for all 132 remains rejected.

---

## Key Findings

### 1. 34 plugins claim incremental; 31 are genuine

**34 plugins** set `supports_incremental = True`. Of those, 3 delegate `compute_next` to `compute_full` (CVD, OFI, MAComposite). The remaining **98 plugins** either have `supports_incremental = False` or no `compute_next` at all. The incremental problem is a 31-plugin problem, not 132.

### 2. State shapes cluster into 7 archetypes

**Archetype 1: Wilder's Accumulator** (5 plugins)
`{smoothed_value: float, prev_close: float}` - ATR, RSI, StochRSI, Supertrend, ADX
(Note: OBV uses cumulative delta, not Wilder's. GARCH/Kalman use recursive filters with different update rules. Keltner is EMA + ATR hybrid.)

**Archetype 2: Rolling Window + Min/Max** (6 plugins)
`{high_window: deque(N), low_window: deque(N)}` - Aroon, Chandelier, Donchian, Stochastic, WilliamsR, BollingerSqueeze

**Archetype 3: Rolling Window + Running Sum** (6 plugins)
`{window: deque(N), sum: float, [sum_sq: float]}` - Bollinger, MovingAverages, AC Oscillator, CCI, CMF, MFI

**Archetype 4: EMA Chain** (4 plugins)
`{ema_a: float, ema_b: float, [ema_signal: float]}` - MACD, ROC/PPO, Keltner, MovingAverages

**Archetype 5: Deque History + Z-Score** (4 plugins)
`{history: deque(N)}` - VolumeZscore, HistoricalVolatility, CVD, OFI

**Archetype 6: Complex State Machine** (3 plugins - unique)
- PSAR: 8-key ratchet (sar, ep, af, direction, prev h/l)
- BOCPD: 6 numpy arrays length R=200 (run_length_probs, mu, kappa, alpha, beta)
- HMMRegime: forward algorithm state (alpha array, return_buffer, regime tracking)

**Archetype 7: Cumulative with Session Reset** (3 plugins)
`{cum_value: float, session_marker: date/int}` - VWAP, CVD, SessionLevels

### 3. Shared state keys are highly concentrated

| State Key | Plugin Count | Note |
|-----------|-------------|------|
| `prev_close` | **21/34** | Near-universal. Used for delta/TR/return. |
| `deque` (any window) | **24/34** | Dominant data structure. Maxlen 3-200, mode=20. |
| `*_window` (H/L deque pair) | **8/34** | Rolling min/max pattern. |
| `*_sum` (running sum) | **6/34** | Online aggregation to avoid re-summing. |
| `ema_fast`/`ema_slow` | **4/34** | EMA chain pattern. |
| `*_history` (deque/list for stats) | **8/34** | Rolling statistics windows. |

### 4. Higher tiers share almost nothing with I1

| What I1 does | What higher tiers do | Shared? |
|--------------|---------------------|---------|
| Incremental state (28/28) | Delegate to compute_full (104/104) | No |
| Pure math on OHLCV arrays | Scoring, gating, signal construction | No |
| Output: flat scalar dict | Output: nested schema with confidence | No |
| Input: `frames["main"]` only | Input: `frames["features"]`, `frames["intel_*"]`, `frames["tick_buffer"]` | Partially |

I7 already has good shared utilities (`plugin_utils.py`, `confidence_utils.py`, `gradient_utils.py`). Promoting them to I1-I6 would add indirection without reducing complexity - I1 doesn't have confidence, regime gating, or signal construction concepts.

### 5. The current Protocol + dataclass design is already optimal for the 98 non-incremental plugins

The existing `IndicatorPlugin`/`PatternPlugin` Protocol classes provide structural typing without inheritance coupling. 132 `@dataclass` instances implement them via duck typing. This is what a Renaissance engineer would build: minimal machinery, maximum measurability.

**What quant libraries chose:**
- **Zipline**: Base class with template method (homogeneous data pipeline - not our case)
- **Backtrader**: Base class with `next()` (simpler - only sees one bar)
- **vectorbt**: Function factory (vectorized - no incremental state)

None of these fit. IndicAgent plugins have heterogeneous inputs (OHLCV, features, tick buffers, intel events, cache snapshots) and heterogeneous computation shapes. A one-size-fits-all base class will always fight some subset of plugins.

---

## Full State Shape Inventory (34 plugins with `supports_incremental = True`)

| Plugin | Tier | State Shape | `_seed_state`? | `compute_next` |
|--------|------|------------|----------------|----------------|
| ATRPlugin | I1 | `atr_{p}: {prev_atr: float, prev_close: float}` | No | Wilder on TR |
| ADXPlugin | I1 | `adx_{p}: {smoothed_plus_dm, smoothed_minus_dm, smoothed_tr, adx, prev_h, prev_l, prev_close: float}` | No | Wilder on DM/TR |
| AroonPlugin | I1 | `{high_window: deque(p+1), low_window: deque(p+1)}` | No | Append H/L, argmax/argmin |
| BollingerPlugin | I1 | `bb_{p}_{s}: {window: deque(p), sum, sum_sq, std_dev: float, period: int}` | No | Sliding window online variance |
| CCIPlugin | I1 | `cci_{p}: {tp_window: deque(p)}` | Yes | Append TP, mean/MAD |
| ChandelierPlugin | I1 | `{atr: float, prev_close: float, high_window: deque(p), low_window: deque(p)}` | No | Wilder ATR + H/L window |
| CMFPlugin | I1 | `{mfv_window: deque(20), vol_window: deque(20)}` | No | Append MFV/vol, sum |
| CVDPlugin | I1 | `{cum_cvd: float, last_session_date: date, cvd_history: deque(100), delta_history: deque(100)}` | No | **Delegates to compute_full** |
| DonchianPlugin | I1 | `{high_window: deque(p), low_window: deque(p)}` | Yes | Append H/L, min/max |
| HistVolPlugin | I1 | `{prev_close: float, log_return_window: deque(20), hv_window: deque(20)}` | No | Append log return, std |
| KeltnerPlugin | I1 | `{ema: float, atr: float, prev_close: float}` | Yes | EMA + Wilder ATR |
| MACDPlugin | I1 | `macd_{f}_{s}_{sig}: {ema_fast, ema_slow, ema_signal: float}` | Yes | 3-EMA chain |
| MFIPlugin | I1 | `mfi_{p}: {prev_tp: float, pos_mf_window: deque(p), neg_mf_window: deque(p)}` | Yes | Classify pos/neg MF |
| MovingAvgPlugin | I1 | SMA: `{window: deque(p), sum: float}`, EMA: flat float | Yes | SMA sliding + EMA alpha |
| OBVPlugin | I1 | `{prev_close: float, cum_obv: float}` | No | Add/sub vol by direction |
| OFIPlugin | I1 | `{symbol}_{tf}: {ofi_history: deque(100), ret_history: deque(100), ewma5, ewma20: float}` | No | **Delegates to compute_full** |
| PSARPlugin | I1 | `{sar, ep, af, direction, prev_h, prev_l, prev_prev_h, prev_prev_l: float}` | No | SAR ratchet |
| ROC_PPOPlugin | I1 | `{roc_window: deque(p+1), ema_fast, ema_slow, ppo_signal_ema: float}` | Yes | Sliding ROC + 3-EMA |
| RSIPlugin | I1 | `rsi_{p}: {avg_gain, avg_loss, prev_close: float}` | Yes | Wilder on gain/loss |
| StochasticPlugin | I1 | `stoch_{k}_{d}: {high_window: deque(k), low_window: deque(k), k_values: deque(d)}` | Yes | H/L append, %K, SMA %D |
| StochRSIPlugin | I1 | `{avg_gain, avg_loss, prev_close: float, rsi_window: deque(p), k_window: deque(d)}` | No | Wilder RSI + Stochastic on RSI |
| SupertrendPlugin | I1 | `{prev_final_upper, prev_final_lower, prev_direction, prev_close, prev_atr: float/int}` | No | Ratchet band + flip |
| VWAPPlugin | I1 | `{cum_pv, cum_vol, cum_tp_sq_vol: float, session_date: date}` | No | Cumulate PV, session reset |
| WilliamsRPlugin | I1 | `wr_{p}: {high_window: deque(p), low_window: deque(p)}` | Yes | H/L append, min/max |
| ACOscillatorPlugin | I1 | `{mp5_window: deque(5), mp5_sum, mp34_window: deque(34), mp34_sum, ao5_window: deque(5), ao5_sum}` | Yes | 3 sliding-window SMAs |
| MarketProfilePlugin | I3 | `{tick_size, price_min: float, volume_buckets: dict, bar_count: int, session_id: str}` | No | Increment bucket TPOs |
| SessionLevelsPlugin | I3 | `{bar_count, sess_n, session_start_idx: int, 15+ session/weekly pivot keys}` | No | Session boundary detect |
| BollingerSqueezePlugin | I5 | `{squeeze_count: int, prev_squeeze: bool, bandwidth_history: deque(100), close/high/low_window: deque(20), prev_close: float}` | No | BB/KC update, squeeze detect |
| BOCPDPlugin | SMC | `{run_length_probs, mu, kappa, alpha, beta: ndarray(200), cp_prob, prev_close: float}` | No | Forward pass run-length |
| HMMRegimePlugin | SMC | `{alpha: ndarray(3), prev_close: float, return_buffer: deque(20), prev_regime, regime_duration, bars_processed: int, prob_history: deque(5)}` | No | Forward algorithm step |
| GARCHPlugin | I4 | `{prev_sigma2: float, prev_close: float, sigma_history: list(100), realized_returns: list(20)}` | No | GARCH(1,1) recursion |
| KalmanPlugin | I4 | `{x_est, P_est: float, trend_history: list(6), R: float}` | No | Predict-update step |
| MACompositePlugin | I2 | `{golden_cross_bars_ago: float}` | No | **Delegates to compute_full** |
| VolumeZscorePlugin | I7 | `{vol_history: deque(20)}` | No | Append vol, z-score |

---

## Decision: Approach D - Protocol + Promoted Helpers

**No base class. No template method.** Protocol + dataclass for the 98 non-incremental plugins. Targeted `IncrementalMixin` for the 31 genuine incremental plugins. The concrete wins are 4 promoted functions plus a mixin that enforces the state contract.

### Why the other approaches lose

| Approach | Verdict | Reason |
|----------|---------|--------|
| A. Pure functions | Reject | Would lose `@dataclass` config fields, break executor/registry, rewrite 132 plugins for zero gain |
| B. Mixin classes | Reject | OFI reads tick_buffer, HMM reads features, CVD reads tick data - too heterogeneous for mixins. "Optional" mixins that 80% of plugins opt out of are useless mixins. |
| C. Base class + template method | Reject | Architecture astronautics. Splits 50-line plugins into 4 methods. Heterogeneous inputs mean some hooks get args they don't need. The current Protocol IS the template. |
| D. Protocol + promoted helpers | **Accept** | Zero architectural changes. Each plugin adopts independently. Full backward compatibility. The `plugin_utils.py` docstring already says it: "module-level functions, NOT a BaseI7Plugin class." |

---

## Concrete Changes

### Change 1: Make `compute_next` optional in executor

**Impact: ~121 plugins can delete their `compute_next` method entirely**

The executor already checks `supports_incremental` before calling `compute_next`. If a plugin doesn't define `compute_next`, or defines it as just delegating to `compute_full`, the executor can fall back automatically.

```python
# executor.py: when plugin has no genuine compute_next
if state is None or not state:
    return plugin.compute_full(frames)
```

**Eliminates ~121 one-line delegation methods.** Plugins that need genuine incremental logic keep their `compute_next`.

### Change 2: Promote `extract_ohlcv` to shared utility

**Impact: ~35 non-I7 plugins that do raw OHLCV extraction**

Move from `trading/plugin_utils.py` to a location accessible by all tiers. Two functions:

```python
def get_main_df(frames: dict, min_bars: int) -> pd.DataFrame | None:
    """Extract and validate main DataFrame. Returns None if insufficient data."""
    df = frames.get("main")
    if df is None or len(df) < min_bars:
        return None
    return df
```

Plugins adopt incrementally: `df = get_main_df(frames, self.min_lookback); if df is None: return {}`.

### Change 3: Extract `wilders_smoothing` as pure function

**Impact: 7+ plugins (ATR, ADX, RSI, Chandelier, Keltner, StochRSI, Supertrend)**

```python
def wilders_update(prev: float, new_val: float, period: int) -> float:
    """Wilder's smoothing: (prev * (period-1) + new) / period."""
    return (prev * (period - 1) + new_val) / period
```

Currently copy-pasted as inline arithmetic. Extracting it means bug fixes (like the MFI edge case from Phase 093) touch one place.

### Change 4: Extract `update_ema` as pure function

**Impact: ~17 plugins**

```python
def update_ema(current: float, prev_ema: float, span: int) -> float:
    """EMA update: alpha * current + (1-alpha) * prev_ema, alpha=2/(span+1)."""
    alpha = 2.0 / (span + 1)
    return alpha * current + (1.0 - alpha) * prev_ema
```

Same pattern in MACD, Bollinger, Keltner, PPO, and 13 others.

---

## ABC Refinements: Incremental Plugin Contract

### Why this changed

Initial research concluded 92% of plugins delegate `compute_next` to `compute_full`, making an ABC premature. Deeper analysis of the 31 genuine incremental plugins revealed **5 HIGH severity production bugs** where incremental computation is silently broken or crashes, and **7 state archetypes** showing real shared patterns. The ABC isn't about boilerplate reduction - it's about preventing bugs the Protocol contract cannot enforce.

### Newly discovered bugs (Phase 093 missed these)

| Plugin | Bug | Severity | Impact |
|--------|-----|----------|--------|
| **RSI** | `compute_next` reads `self._state` instead of `state` parameter; never returns `_state` | HIGH | Incremental never activates. Always falls back to `compute_full`. |
| **CMF** | Same as RSI: reads `self._state`, never returns `_state` | HIGH | Incremental never activates. |
| **BOCPD** | `compute_full` does not return `_state` | HIGH | Crashes on cold start (executor validation fires). |
| **MarketProfile** | `compute_next` does not return `_state` | HIGH | Crashes in incremental mode. |
| **SessionLevels** | `compute_next` does not return `_state` | HIGH | Crashes in incremental mode. |
| CVD | Uses `self._state` per-symbol sub-dict; delegates to `compute_full` | MEDIUM | Works but fragile singleton pattern. |
| OFI | Same as CVD | MEDIUM | Works but fragile singleton pattern. |
| GARCH/Kalman | `state = {}; state.update(...)` anti-pattern | LOW | Works but unclear intent. |
| HMM | Hybrid `self._state` + return | LOW | Works but confusing dual pattern. |

**Key insight**: Only 6 of 16 "incremental" plugins are correctly migrated to the PERF-03 state-as-parameter pattern. The rest either read `self._state` (pre-migration) or forget to return `_state` (post-migration but incomplete).

### Migration status of all incremental plugins

| Status | Plugins | Count |
|--------|---------|-------|
| Correctly migrated (reads `state` param, returns `_state`) | ATR, ADX, Stochastic, WilliamsR, MFI, VolumeZscore | 6 |
| Pre-migration (reads `self._state`, ignores `state` param) | RSI, CMF | 2 |
| Missing `_state` in return | BOCPD (compute_full), MarketProfile, SessionLevels (compute_next) | 3 |
| Delegate-only (compute_next calls compute_full) | CVD, OFI, MAComposite | 3 |
| Hybrid (self._state + return) | GARCH, Kalman, HMM | 3 |
| No _seed_state method, inline seeding | 22 plugins | 22 |
| Has _seed_state method | 12 plugins | 12 |

### Refined approach: IncrementalMixin for the 31 genuine plugins

The mixin owns the two things that every bug has in common: **fallback-to-full** and **`_state` return**. Plugins implement only their domain logic.

```python
class IncrementalMixin:
    """Owns fallback-to-full and _state return contract.
    
    Plugins implement:
    - _compute_full_core(frames) -> dict          # pure outputs, no _state
    - _compute_next_core(frames, state) -> dict   # pure outputs, no _state
    - _seed_state(frames) -> dict                 # extract state from full computation
    
    The mixin provides compute_full() and compute_next() with:
    - Automatic state fallback (if not state -> compute_full)
    - Automatic _state attachment to output
    - State never None in _compute_next_core
    """
    
    def compute_full(self, frames, *, state=None):
        result = self._compute_full_core(frames)
        if not result:
            return {}
        result["_state"] = self._seed_state(frames)
        return result
    
    def compute_next(self, windows, *, state=None):
        if not state:
            return self.compute_full(windows)
        result = self._compute_next_core(windows, state)
        if isinstance(result, dict):
            result["_state"] = state
        return result
```

### What bugs the mixin prevents

| Bug | How mixin prevents it |
|-----|----------------------|
| Missing `_state` in return | Mixin ALWAYS attaches `_state`. Plugin cannot forget. |
| State parameter shadowed (`state = {}`) | Plugin never touches `state` parameter. Mixin owns it. |
| Missing fallback-to-full | Mixin owns the `if not state` check. Plugin never writes it. |
| State param ignored (reads `self._state`) | Mixin passes state to `_compute_next_core`. No `self._state` access needed. |

### Migration effort per archetype

| Archetype | Effort | Plugins | Notes |
|-----------|--------|---------|-------|
| Wilder's Accumulator | Easy | ATR, Keltner, OBV, GARCH, Kalman, RSI, StochRSI, Supertrend | `wilders_update()` covers the core. |
| Rolling Window + Min/Max | Easy | Aroon, Chandelier, Donchian, Stochastic, WilliamsR | H/L deque append + min/max. |
| Rolling Window + Running Sum | Easy | Bollinger, MovingAverages, AC, CCI, CMF, MFI | `deque_sum_update()` covers core. |
| EMA Chain | Easy | MACD, ROC/PPO, Keltner, MovingAverages | `update_ema()` chain. |
| Deque History + Z-Score | Easy | VolumeZscore, HistVol | Append + z-score. |
| Cumulative + Session Reset | Medium | VWAP, CVD, SessionLevels | Session boundary logic varies. |
| BollingerSqueeze | Medium | 1 plugin | Mixed window + squeeze state machine. |
| PSAR | Hard | 1 plugin | 8-field ratchet. Unique. |
| BOCPD | Hard | 1 plugin | 6 numpy arrays. Forward algorithm. |
| HMMRegime | Hard | 1 plugin | Forward algorithm + regime tracking. |
| CVD/OFI | Hard | 2 plugins | Per-symbol sub-state. Architectural bug. |

### Phased execution

**Phase A (fail-fast + targeted fixes, zero architectural changes):** Fix the 5 HIGH bugs directly: add `_state` returns to BOCPD/MarketProfile/SessionLevels, migrate RSI/CMF from `self._state` to `state` parameter. No executor recovery magic - fail fast on missing `_state` so bugs surface immediately. Log at error level with metric counter for tracking.

**Phase B (conformance tests):** Add tests for every `supports_incremental=True` plugin: (1) cold `compute_full()` returns `_state`, (2) warm `compute_next(state=...)` returns `_state`, (3) incremental output matches full recompute within tolerance over N bars, (4) no `self._state` writes after migration.

**Phase C (mixin, 6 easy plugins):** ATR, ADX, Stochastic, WilliamsR, MFI, VolumeZscore migrate to `IncrementalMixin`. These are the cleanest candidates. Validate with conformance tests + Phase 093 tests.

**Phase D (lint gate):** Add grep/lint gate: migrated plugins must not reference `self._state`. Enforce in CI.

**Phase E (flag correction):** Set `supports_incremental = False` on delegation plugins. They do not have incremental logic. Removes them from executor validation entirely. Consider splitting Protocol into base + `IncrementalCapable` sub-Protocol.

**Phase F (complex plugins):** GARCH, Kalman, HMM, BOCPD migrate once Phase C proves the mixin works. CVD and OFI need isolated sprint for architectural fix (per-symbol state should use the `state` parameter, not `self._state`).

**Phase G (optional future):** Typed state dataclasses (`ATRState`, `RSIState`, etc.) for IDE autocomplete and compile-time key checking. Quality-of-life, not correctness.

### Why not a full ABC with typed state (Proposal 3)

A full `IncrementalPluginBase[Generic[TState]]` with typed state dataclasses was evaluated. Verdict: too much machinery for 11 plugins. The mixin approach captures 100% of the bug prevention value with 20% of the complexity. Typed state can be added later as a non-breaking enhancement once all plugins are on the mixin.

---

## What We're NOT Doing

| Idea | Why not |
|------|---------|
| Full IncrementalPlugin ABC for all 132 | 98 plugins don't need incremental logic. The mixin targets only the 31 that do. |
| Typed state dataclasses (Generic[TState]) | Too much machinery for 31 plugins with 7 archetypes. The mixin captures 100% of bug prevention with 20% of complexity. Can add later as non-breaking enhancement. |
| Base class with template method for all tiers | Current Protocol IS the template. Adding `_extract_inputs()` / `_compute()` / `_build_output()` hooks splits simple plugins into fragments. |
| Signal construction for I1-I6 | I1 outputs flat scalar dicts. Signal schema is an I7 concept. |
| Confidence scoring promotion | I7-only concept. I1-I6 don't have confidence. |

---

## Inline Indicator Recomputation (correctness bug, not utility issue)

Three I5 plugins recompute I1 indicators instead of consuming I1 outputs:

- `rsi_divergence.py` has its own `_rsi_series()`
- `head_shoulders.py` has its own `_compute_atr()`
- `bollinger_squeeze.py` has its own `_atr_series()` and inline Bollinger Band computation

These should consume `frames["features"]["rsi_14"]` etc. instead. This is a correctness issue (drift between inline and I1 computation), not a shared-utility issue. Separate fix, low priority since results are mathematically equivalent today.

---

## Risks

- **Trivial abstraction risk**: The promoted helpers are so small (1-2 lines each) that the indirection cost may exceed the duplication cost. Mitigation: only promote functions that appear in 7+ plugins AND have been a source of bugs (Wilder's smoothing was the source of the MFI bug).
- **Performance regression**: Any shared helper that adds overhead per-bar. Mitigation: Phase 093's 10K-bar stability tests will catch regressions. These are pure functions with zero allocation overhead.
- **Adoption friction**: Plugins adopt incrementally, so old and new patterns coexist. Mitigation: document the preferred pattern in CLAUDE.md and enforce on new plugins.
- **Concurrency hazard (Codex review)**: Shared plugin instances + `self._state` + threadpool dispatch = race condition across symbols/timeframes. PERF-03 intentionally stopped assigning `plugin._state` before threadpool dispatch. Any remaining `self._state` use in `compute_full()` or `compute_next()` is a race risk. Mitigation: lint gate forbids `self._state` in migrated plugins; conformance tests verify no writes.
- **Mixin state mutation (Codex review)**: The mixin attaches `_state` by mutating the output dict. State manager must snapshot/serialize safely. No caller may mutate returned output state. Mitigation: conformance tests check state isolation.
- **Archetype precision (Codex review)**: OBV/GARCH/Kalman are not Wilder's Accumulator - they use cumulative delta and recursive filters respectively. ADX is Wilder-style but was omitted. Mitigation: tightened groupings above; migration plan targets plugins individually, not by archetype.

---

## Execution Plan

### Part 1: Shared Utilities (low risk, high leverage)

| Step | What | Plugins affected | Lines removed |
|------|------|-----------------|---------------|
| 1 | Make `compute_next` optional in executor | 121 | ~121 |
| 2 | Add `get_main_df()` to shared utils | 0 (add only) | +5 |
| 3 | Add `wilders_update()` to shared utils | 0 (add only) | +3 |
| 4 | Add `update_ema()` to shared utils | 0 (add only) | +3 |
| 5 | Migrate I1 plugins to `get_main_df()` | 28 | ~56 |
| 6 | Migrate I1 plugins to `wilders_update()` | 7 | ~7 |
| 7 | Migrate I1 plugins to `update_ema()` | 17 | ~17 |
| 8 | Delete 121 delegation `compute_next` methods | 121 | ~363 |

### Part 2: IncrementalMixin (bug fixes for 31 genuine incremental plugins)

| Step | What | Plugins affected | Risk |
|------|------|-----------------|------|
| A | Add `_state` recovery safety net to executor | 0 (executor only) | Minimal |
| B | Create `IncrementalMixin` | 0 (add only) | None |
| C | Add `wilders_update()`, `update_ema()`, `deque_sum_update()` to shared utils | 0 (add only) | None |
| D | Migrate archetype 1 (Wilder's Accumulator): ATR, Keltner, OBV, RSI, StochRSI, Supertrend | 6 | Low |
| E | Migrate archetype 2 (Rolling Window Min/Max): Aroon, Chandelier, Donchian, Stochastic, WilliamsR | 5 | Low |
| F | Migrate archetype 3 (Running Sum): Bollinger, MovingAverages, AC, CCI, CMF, MFI | 6 | Low |
| G | Migrate archetype 4 (EMA Chain): MACD, ROC/PPO | 2 | Low |
| H | Migrate archetype 5 (Z-Score): VolumeZscore, HistVol | 2 | Low |
| I | Migrate archetype 7 (Session Reset): VWAP | 1 | Medium |
| J | Fix RSI, CMF: migrate from `self._state` to mixin | 2 | Medium |
| K | Fix BOCPD, MarketProfile, SessionLevels: add `_state` returns | 3 | Medium |
| L | Migrate GARCH, Kalman to mixin | 2 | Medium |
| M | Migrate PSAR, BOCPD, HMM to mixin | 3 | High (unique state) |
| N | Fix CVD, OFI: per-symbol state architecture | 2 | High (architectural change) |
| O | Set `supports_incremental = False` on 3 delegation plugins (CVD, OFI, MAComposite) | 3 | Low |

Each step regression-testable via Phase 093's 94 correctness tests. Part 1 and Part 2 are independent - can execute in either order or in parallel.

---

## Bug Catalog

### Phase 093 findings (fixed)
- MFI `compute_full` returned 0.0 instead of 100.0 for all-positive money flow (CR-01, FIXED)
- Dead `np.partition` call in BollingerSqueeze (WR-01, FIXED)
- State parameter shadowed in WilliamsR and Stochastic (WR-02, FIXED)

### Phase 093 warnings (still open)
- Missing state initialization in 8+ `compute_full` methods (CR-01 from CODE-REVIEW.md)
- GARCH/Kalman call `state.update()` on uninitialized dict (CR-02)
- Volume z-score never returns `_state` (CR-03)
- `inputs` type annotation violates protocol on 5 files (WR-04 from REVIEW.md)

### Infrastructure analysis findings (NEW - not yet fixed)
- RSI `compute_next` reads `self._state` not `state` param; never returns `_state` (HIGH)
- CMF `compute_next` reads `self._state` not `state` param; never returns `_state` (HIGH)
- BOCPD `compute_full` does not return `_state` (HIGH - crashes on cold start)
- MarketProfile `compute_next` does not return `_state` (HIGH)
- SessionLevels `compute_next` does not return `_state` (HIGH)
- CVD/OFI use `self._state` per-symbol sub-dicts instead of `state` parameter (MEDIUM)
