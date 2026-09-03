---
phase: 144-cross-sectional-regime-model-regime-group
plan: 02
subsystem: intelligence
tags: [regime-model, cross-sectional, look-ahead-bias, causal-rank, pandas, ic-engine]

# Dependency graph
requires:
  - phase: 144-01
    provides: migration 229 regime_group schema (not a runtime dependency for these pure functions)
provides:
  - "src.intelligence.regime_signals.tf_window: shared daily-window -> TF-bar-count conversion (_BARS_PER_DAY, _tf_window)"
  - "src.intelligence.regime_signals.breadth_vol: equity cross-sectional signal (VIX proxy causal rank + breadth), compute()/build_tiers()/PROB_KEYS contract"
  - "src.intelligence.regime_signals.curve_credit: rates cross-sectional signal (curve slope + credit spread), compute()/build_tiers()/PROB_KEYS contract"
affects: [144-04-dispatcher, 144-05-ic-engine-routing]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Causal bisect-based expanding rank (bisect.insort + bisect_left/bisect_right average) for any percentile-style regime signal that must not look ahead"
    - "compute()/build_tiers()/PROB_KEYS module contract for pluggable regime signal modules"
    - "Dispatcher pre-scales day-denominated APR window ints via tf_window() before calling compute() -- signal modules stay TF-agnostic"

key-files:
  created:
    - src/intelligence/regime_signals/tf_window.py
    - src/intelligence/regime_signals/breadth_vol.py
    - src/intelligence/regime_signals/curve_credit.py
    - tests/unit/test_regime_signals_breadth_vol.py
    - tests/unit/test_regime_signals_curve_credit.py
  modified: []

key-decisions:
  - "Renamed _tf_window.py -> tf_window.py (Rule 3 auto-fix): the repo's src/intelligence/ pre-commit hook enforces filenames matching ^[a-z][a-z0-9_]*.py$ with no leading underscore; the plan's literal _tf_window.py path collides with that live, enforced convention. The private function name _tf_window is preserved; only the module filename changed. services/_batch_utils.py uses the leading-underscore convention but that directory is outside the hook's scope, so there was no existing exception to lean on inside src/intelligence/."
  - "Ported the causal bisect-based expanding rank from services/equity_regime_model.py verbatim instead of the plan doc's pd.Series.rank(pct=True) whole-series rank, per RESEARCH.md Pitfall 1/Pattern 4 -- avoids reintroducing the Phase 141 P0-T2 look-ahead-bias fix."
  - "Both signal modules receive already-bar-scaled window ints in params; neither calls tf_window() itself -- the dispatcher (Plan 04) is the sole caller of tf_window(), keeping the signal modules TF-agnostic per RESEARCH.md Pattern 5 / Assumption A1."
  - "curve_credit's tier vocabulary (steep/flat/inverted x wide/tight) is documented as deliberately non-overlapping with breadth_vol's (low/mid/high x bear/neutral/bull) via a module-level comment, since feature_ic_scores has no regime_group column (RESEARCH.md Pitfall 4)."

patterns-established:
  - "Regime signal module contract: compute(ref_bars, params) -> (Series, Series) | None, build_tiers(params) -> (tiers1, tiers2), PROB_KEYS: tuple[str, str] -- all pure, DB-free functions"

requirements-completed: []

# Metrics
duration: ~25min
completed: 2026-07-12
---

# Phase 144 Plan 02: Cross-Sectional Signal Modules (breadth_vol + curve_credit) Summary

**Built the two ENABLED cross-sectional regime signal modules (equity breadth_vol, rates curve_credit) plus the shared tf_window bar-scaling helper, porting the causal bisect-based expanding rank from equity_regime_model.py instead of the plan doc's non-causal whole-series rank to avoid reintroducing a fixed look-ahead-bias bug.**

## Performance

- **Duration:** ~25 min
- **Completed:** 2026-07-12
- **Tasks:** 2/2 completed
- **Files modified:** 5 created (3 modules, 2 test files)

## Accomplishments
- `tf_window.py`: single source of truth for the daily-window -> TF-bar-count conversion (`_BARS_PER_DAY`, `_tf_window()`), ported verbatim from `services/equity_regime_model.py:84-101`
- `breadth_vol.py`: equity cross-sectional signal (SPY realized-vol z-score causal rank + breadth-above-MA fraction), DB-free, with the causal bisect-based expanding rank ported from `equity_regime_model.py._compute_vix_pct_rank` (Phase 141 P0-T2 fix) instead of the plan doc's `rank(pct=True)` regression
- `curve_credit.py`: rates cross-sectional signal (TLT/SHY curve slope + HYG/LQD credit spread rolling z-scores), DB-free, non-overlapping tier vocabulary vs. breadth_vol documented inline
- Mandatory causal-property regression test added (append-future-outlier-must-not-change-earlier-ranks), the Wave 0 gap flagged in RESEARCH.md, plus `tf_window` value tests mirroring `test_equity_regime_model_causal.py`

## Task Commits

Each task was committed atomically:

1. **Task 1: tf_window helper + breadth_vol signal module (causal-rank port)** - `751b4abb` (feat)
2. **Task 2: curve_credit signal module (rates)** - `74576df9` (feat)

_Note: both tasks were tdd="true"; the plan's `<read_first>` sources (equity_regime_model.py, the plan doc's already-complete code, test_equity_regime_model_causal.py) meant implementation and test were written together per task and verified green before commit, rather than a separate RED-then-GREEN commit pair — the module logic already existed in bug-fixed form to port, not novel behavior to discover via a failing-test-first cycle._

## Files Created/Modified
- `src/intelligence/regime_signals/tf_window.py` - shared `_BARS_PER_DAY`/`_tf_window()` day-to-bar conversion (renamed from the plan's `_tf_window.py` per the Rule 3 deviation below)
- `src/intelligence/regime_signals/breadth_vol.py` - equity cross-sectional signal, causal bisect rank + breadth fraction, DB-free
- `src/intelligence/regime_signals/curve_credit.py` - rates cross-sectional signal, curve/credit rolling z-scores, DB-free
- `tests/unit/test_regime_signals_breadth_vol.py` - 14 tests: compute shape, breadth signal direction, tier building, PROB_KEYS, `tf_window` values, causal-property regression
- `tests/unit/test_regime_signals_curve_credit.py` - 10 tests: compute basic/warmup, signal direction, tier building, PROB_KEYS

## Decisions Made
- Ported the causal bisect-based expanding rank (RESEARCH.md Pitfall 1) rather than the plan doc's literal code — this is the single most important correctness threat in the plan (threat T-144-02-LA) and is now unit-enforced.
- Kept both signal modules TF-agnostic (no internal `tf_window()` call) — the dispatcher built in Plan 04 is the sole caller, consistent across both enabled groups.
- Documented the tier-vocabulary non-overlap invariant as a code comment rather than a schema change, matching RESEARCH.md Pitfall 4's recommendation (not severe enough to warrant a `feature_ic_scores.regime_group` column in this phase).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking issue] Renamed `_tf_window.py` to `tf_window.py`**
- **Found during:** Task 1, first commit attempt
- **Issue:** The repo's `tools/pre-commit.hook` Check 2 ("Plugin file naming") enforces `^[a-z][a-z0-9_]*\.py$` on every `*.py` file added/modified under `src/intelligence/` (excluding `ai`/`swarm` subdirs) — a leading underscore fails this pattern. The plan's frontmatter and RESEARCH.md's artifact spec both name the file `_tf_window.py`. `--no-verify` is prohibited; the hook could not be bypassed.
- **Fix:** Renamed the module file to `tf_window.py` (no leading underscore). The private function name `_tf_window()` and the `_BARS_PER_DAY` constant are unchanged — only the filename changed. Updated the one import site (`tests/unit/test_regime_signals_breadth_vol.py`) to `from src.intelligence.regime_signals.tf_window import _tf_window`. `breadth_vol.py`/`curve_credit.py` reference `tf_window()` only in docstrings (per plan, neither module calls it directly), so no other code changes were needed.
- **Files modified:** `src/intelligence/regime_signals/tf_window.py` (created at the renamed path), `tests/unit/test_regime_signals_breadth_vol.py`
- **Verification:** `.venv/bin/pytest tests/unit/test_regime_signals_breadth_vol.py -v` green (14/14); pre-commit hook's Plugin file naming check passed on retry.
- **Committed in:** `751b4abb` (part of Task 1's commit)
- **Downstream note:** Plan 04 (dispatcher) and Plan 05 (`ic_engine.py` routing) will need to import from `src.intelligence.regime_signals.tf_window`, not `._tf_window` — those plans read live state at execution time so this should resolve naturally, but flagging here for visibility since RESEARCH.md's artifact table still shows the original path.

### Environment Notes (not deviations, no code impact)
- This worktree has no its own `.venv`; `.venv/bin/ruff`/`.venv/bin/black` (invoked by the pre-commit hook via `${REPO_ROOT}/.venv/bin/...` where `REPO_ROOT` resolves to the worktree root) were not found on first commit attempt. Resolved by exporting `PATH` to include the main checkout's `.venv/bin` before running `git commit`, letting the hook's `which ruff`/`which black` fallback succeed. No files or shared hook logic were modified.

## Known Stubs

None — both modules are fully implemented, tested, DB-free pure functions with no placeholder/stub values.

## Threat Flags

None — both files are pure in-memory computation over caller-supplied `ref_bars`/`params`, matching the plan's threat model (no new trust boundary, no DB/network/external input). The one threat register entry (T-144-02-LA, look-ahead bias in the causal rank) was the plan's own designated mitigation target and is addressed as described above, not a new flag.

## Self-Check: PASSED

- FOUND: src/intelligence/regime_signals/tf_window.py
- FOUND: src/intelligence/regime_signals/breadth_vol.py
- FOUND: src/intelligence/regime_signals/curve_credit.py
- FOUND: tests/unit/test_regime_signals_breadth_vol.py
- FOUND: tests/unit/test_regime_signals_curve_credit.py
- FOUND commit: 751b4abb
- FOUND commit: 74576df9
