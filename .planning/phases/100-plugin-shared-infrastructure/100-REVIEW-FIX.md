---
phase: 100-plugin-shared-infrastructure
fixed_at: 2026-05-21T19:45:00Z
review_path: .planning/phases/100-plugin-shared-infrastructure/100-REVIEW.md
iteration: 1
findings_in_scope: 9
fixed: 9
skipped: 0
status: all_fixed
---

# Phase 100: Code Review Fix Report

**Fixed at:** 2026-05-21T19:45:00Z
**Source review:** .planning/phases/100-plugin-shared-infrastructure/100-REVIEW.md
**Iteration:** 1

**Summary:**
- Findings in scope: 9 (CR-01, CR-02, CR-03, WR-01 through WR-06)
- Fixed: 9
- Skipped: 0

Note: WR-06 (misleading CVD comment) was resolved in the same commit as CR-03
since both touch `cvd.py`. The comment was updated to describe the corrected
per-symbol keyed architecture and cross-reference OFI as the correct pattern.

## Fixed Issues

### CR-01: MACompositePlugin writes undeclared output key

**Files modified:** `src/intelligence/composites/ma_composites.py`
**Commit:** ae3d9378
**Applied fix:** Changed `"price_above_sma_50"` to `"price_above_sma200"` in the outputs frozenset. The computation block uses `s200` (SMA200 distance), so the declaration was wrong. The written key `out["price_above_sma200"]` is now declared.

---

### CR-02: SessionLevelsPlugin.compute_next sets prior_session_close to wrong bar

**Files modified:** `src/intelligence/features/i3_structure/session_levels.py`
**Commit:** 18bff297
**Applied fix:** Added `session_close_running` tracking. On every non-rollover bar in `compute_next`, `state["session_close_running"] = bar_close` is updated. On rollover, `state["prior_session_close"] = state.get("session_close_running")` is used instead of the current `bar_close` (which is the first bar of the new session, not the last bar of the old session). Seeded in `compute_full` from `session["close"].iloc[-1]`.
**Commit status:** fixed: requires human verification (logic change to session boundary handling)

---

### CR-03: CVDPlugin._state is not keyed per symbol

**Files modified:** `src/intelligence/features/i1_indicators/cvd.py`
**Commit:** 1ca1fb21
**Applied fix:** Added `symbol = frames.get("__symbol__", "_")` and `tf = frames.get("__timeframe__", "_")` extraction in `compute_full`. All state reads/writes now use `state = self._state.setdefault(state_key, {})` where `state_key = f"{symbol}_{tf}"`, following OFI's pattern. Also addressed WR-06 in this commit: updated the misleading "per-symbol self._state architecture" comment to describe the corrected implementation.

---

### WR-01: ROCPPOPlugin and ACOscillatorPlugin do not return `_state`

**Files modified:** `src/intelligence/features/i1_indicators/roc_ppo.py`, `src/intelligence/features/i1_indicators/ac_oscillator.py`
**Commit:** ee2011fc
**Applied fix:** Added `out["_state"] = self._state` before `return out` in `roc_ppo.py`. Changed the return in `ac_oscillator.py` from `{"ao": float(ao), "ac": float(ac)}` to include `"_state": self._state`. Executor state threading is now correctly maintained.

---

### WR-02: RSI, MACD, Bollinger, CCI, CMF, MovingAverages use `if not state`

**Files modified:** `src/intelligence/features/i1_indicators/rsi.py`, `macd.py`, `bollinger.py`, `cci.py`, `cmf.py`, `moving_averages.py`
**Commit:** ff65e6ff
**Applied fix:** Changed `if not state:` to `if state is None:` in each plugin's `compute_next`. An empty dict `{}` is a valid seeded state and must not trigger fallback to `compute_full`.

---

### WR-03: BOCPD shallow copy doesn't protect numpy arrays

**Files modified:** `src/intelligence/features/smc_context/bocpd_changepoint.py`
**Commit:** 0a4ca5b7
**Applied fix:** Added `import copy` and changed `"_state": dict(self._state)` to `"_state": copy.deepcopy(self._state)`. The shallow `dict()` copy left numpy arrays (run_length_probs, mu, kappa, alpha, beta) shared between the returned state and the instance, allowing callers to corrupt instance state.

---

### WR-04: MovingAveragesPlugin compute_full aliases self._state into output

**Files modified:** `src/intelligence/features/i1_indicators/moving_averages.py`
**Commit:** d65d3fef
**Applied fix:** Changed `compute_full` to build a `new_state = {}` dict, pass it to `_seed_state(frames, new_state)` (added `state` parameter to `_seed_state`), then set `self._state = new_state` and `out["_state"] = new_state`. The returned dict is now independent from the instance dict. All writes in `_seed_state` now target the passed `state` parameter rather than `self._state`.

---

### WR-05: Dataclass fields typed `list[int] = None` instead of `field(default=None)`

**Files modified:** `rsi.py`, `atr.py`, `adx.py`, `macd.py`, `bollinger.py`, `stochastic.py`, `williams_r.py`, `mfi.py`
**Commit:** bc336989
**Applied fix:** Changed all `periods: list[int] = None` and `configs: list[tuple] = None` fields to use `list[int] | None = field(default=None)` (or the appropriate tuple variant). Added `field` to `from dataclasses import` in the six files that only imported `dataclass`.

---

### WR-06: CVDPlugin comment claims per-symbol architecture that did not exist

**Files modified:** `src/intelligence/features/i1_indicators/cvd.py`
**Commit:** 1ca1fb21 (combined with CR-03)
**Applied fix:** Updated the misleading docstring comment from "per-symbol self._state architecture" to accurately describe the corrected per-(symbol, timeframe) keyed state implementation, with a cross-reference to OFI as the canonical pattern.

---

_Fixed: 2026-05-21T19:45:00Z_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 1_
