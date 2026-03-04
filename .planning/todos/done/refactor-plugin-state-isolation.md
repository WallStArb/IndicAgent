# Refactor Plugin State Isolation

**Created:** 2026-02-28
**Area:** Intelligence Plugins (I1-I7)
**Priority:** High — becomes critical if `compute_next()` incremental path is enabled

## Problem

All indicator, pattern, and trading plugins are instantiated once as module-level singletons with a shared `_state` dict. Each plugin's `_state` accumulates data for a single symbol/timeframe combination.

**Example failure scenario:**
1. Service calls `plugin.compute_full(frames)` for ES 1m → `_state` seeded with ES data
2. Service then calls `plugin.compute_full(frames)` for NQ 1m → `_state` is **overwritten** with NQ data
3. If `compute_next()` is ever called later, NQ data is corrupted but ES service continues

**Root cause:** Plugins use `dataclass field(default_factory=dict)` for `_state` but the registry creates one instance per plugin name at import time. When multiple symbols/timeframes are processed sequentially through the same instance, state is shared and clobbered.

## Files Affected

- All 23 I1 indicators: `src/intelligence/indicators/*.py`
- All 6 I4 context plugins: `src/intelligence/context/*.py`
- All 8 I5 pattern plugins: `src/intelligence/patterns/*.py`
- All 6 SMC plugins: `src/intelligence/smart_money/*.py`
- All 9 I7 trading plugins: `src/intelligence/trading/*.py`

## Solution Options

**Option A (Recommended): Key `_state` by `(symbol, timeframe)` — Rewrite each plugin to accept `(symbol: str, timeframe: str)` as parameter and use this for state storage
- **Complexity:** High — requires touching 62 plugin files, changes to plugin protocol (`compute_full` signature)
- **Pros:** Correctness, isolation guaranteed, minimal refactoring of consumer code
- **Cons:** Breaking change to plugin protocol and downstream consumers

**Option B:** Instantiate one plugin per (symbol, timeframe) pair — Create plugin registry that manages lifecycle
- **Complexity:** High — Need registry infrastructure, state cleanup on bar completion
- **Pros:** Correctness, isolation guaranteed, no plugin protocol changes

**Option C:** Hybrid — Accept shared state but add guard to ensure `compute_next` path is never used
- **Complexity:** Medium — Add explicit `if self._supports_incremental` check before calling `compute_next()`
- **Pros:** Minimal changes to current code

## Recommendation

**Implement Option A or Option C:**
- Option A is cleaner long-term but requires touching every plugin
- Option C is pragmatic short-term fix with guard

Do not enable `compute_next()` anywhere in codebase until this is properly architected.

**Testing:**
- Verify state isolation by running service and checking `_state` values across successive bars
- Add test case where two symbols processed sequentially

**Related:** H1 I1-I4 layer — all plugins share same singleton pattern

**Estimated Effort:** 3-4 hours for Option A, 1-2 hours for Option C, 0.5 hours for guard-only Option C
