# Handoff — Simplify Review Pending Fixes

**Handoff date:** 2026-03-02

---

## Current Position

**Phase:** Intelligence Palette Expansion
**Branch:** main (all Phase 2 work committed, 871 tests passing)
**Immediate task:** Apply fixes identified by /simplify review agents

---

## Pending Fixes (from /simplify review — NOT YET APPLIED)

### Fix 1: ma_composites.py — remove duplicate `_is_num`, import from common.py
- Remove `_is_num` static method (line 159–161)
- Add `from .common import is_num, crossover_detect` import
- Replace all `self._is_num(x)` calls with `is_num(x)`
- Replace inline crossover logic (lines 73–75, 109–111) with `crossover_detect()`
  - Line 73: `crossed_up = pe9 <= pe21 and e9 > e21` + `crossed_down = ...`
    → `crossed_up, crossed_down = crossover_detect(pe9, e9, pe21, e21)`
  - Line 109: same pattern for sma_20_cross_50
  - Line 97: cross_occurred for golden cross — use crossover_detect where applicable

### Fix 2: stochastic_events.py line 53 — remove `# noqa: E501` suppression
- Reformat to multi-line like lines 54–56 already do:
  ```python
  out["stoch_both_oversold"] = (
      1 if k < self._STOCH_OVERSOLD and d < self._STOCH_OVERSOLD else 0
  )
  ```

### Fix 3: volume_events.py line 37 — falsy zero bug
- Current: `bb_mid = features.get("bb_20_2_mid") or features.get("bb_mid")`
- Fix: `bb_mid = features.get("bb_20_2_mid"); bb_mid = features.get("bb_mid") if bb_mid is None else bb_mid`
- Or: explicit None check pattern

---

## Work Remaining After Fixes

Phase 3: I3 Structure Additions (register_plugins.py was already updated by simplifier — check TIER_I3 includes market_profile, session_levels, anchored_vwap, fib_zones)

---

## Next Action

1. Apply the 3 fixes above
2. Run tests: `.venv/bin/pytest tests/unit/ -q`
3. Run ruff: `.venv/bin/ruff check .`
4. Commit: `git commit -m "refactor(i2): consolidate is_num/crossover_detect into common.py"`
5. Then proceed to Phase 3 (Task 3.1 MarketProfile is already registered per system reminder)
