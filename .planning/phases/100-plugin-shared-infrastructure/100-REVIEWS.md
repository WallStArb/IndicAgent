---
phase: 100
reviewers: [gemini, codex]
reviewed_at: "2026-05-21T16:30:00Z"
plans_reviewed: [100-01-PLAN.md, 100-02-PLAN.md, 100-03-PLAN.md, 100-04-PLAN.md, 100-05-PLAN.md, 100-06-PLAN.md]
---

# Cross-AI Plan Review — Phase 100

## Gemini Review

### Summary

Phase 100 is coherent and well-scoped: it targets real duplication, separates shared pure utilities from incremental-state architecture, and avoids forcing a mixin onto the 98 plugins that do not need it. The wave ordering is mostly sound, especially putting shared utilities and HIGH bug fixes before broader migrations. The main risk is that `IncrementalMixin` may encode too narrow a state contract for the seven observed incremental archetypes, especially plugins that need immutable state updates, per-symbol state, rolling buffers, seeded warmup metadata, or state replacement rather than in-place mutation. The plans can achieve the phase goals, but only if parity testing includes full-vs-incremental equivalence across warmup boundaries and performance benchmarks on the hot path.

### Strengths

- The phase goal is specific: reduce duplication without changing the Protocol + dataclass architecture for all plugins.
- The plan correctly distinguishes genuine incremental plugins from delegation plugins.
- Wave sequencing is mostly appropriate: shared helpers first, then mixin reference implementation, then bug fixes and migrations.
- The HIGH bug list is concrete and tied to known state contract violations.
- Golden-file parity is an excellent success criterion for avoiding behavioral drift.
- Limiting `IncrementalMixin` to 31 genuine incremental plugins avoids unnecessary abstraction across the whole plugin fleet.
- ATR as a reference migration is a good choice if it exercises Wilder-style smoothing and warmup state.
- Correcting `supports_incremental` flags is important for executor behavior and latency predictability.

### Concerns

- **HIGH: `IncrementalMixin.compute_next()` mutates/returns the same `state` object unconditionally.**
  The sketch attaches `result["_state"] = state` after `_compute_next_core(windows, state)`. This assumes `_compute_next_core` mutates state in place. Some archetypes may need to return a new state object, replace deques, trim rolling windows, or update nested state atomically. The mixin should not force in-place mutation unless that is an explicit architecture decision.

- **HIGH: The mixin contract may not cover all seven state archetypes.**
  Wilder accumulators, rolling windows, deque history, EMA chains, and per-symbol states have different update semantics. A single `_compute_next_core(windows, state) -> dict` interface may be enough, but only if state ownership, mutation, replacement, and validation rules are defined precisely.

- **HIGH: Fallback behavior may hide broken incremental implementations.**
  `if not state: return self.compute_full(windows)` treats `{}`, `0`, or otherwise falsy states as missing. That can mask bugs and may invoke expensive full-window computation in the hot path. Use `state is None` unless empty dict is explicitly invalid.

- **HIGH: `compute_next()` fallback to `compute_full(windows)` may be semantically wrong.**
  If `windows` in incremental execution is not the full historical frame, then full recomputation from `windows` may seed incomplete or incorrect state. The executor/window contract must be verified.

- **HIGH: Plan 100-03 may be incomplete for RSI/CMF if they have both full and next state paths.**
  Replacing `self._state` reads and adding `_state` return is necessary, but the fix also needs to verify seed state shape, warmup behavior, and whether stale instance fields remain.

- **MEDIUM: `get_main_df()` risks over-standardizing plugin-specific validation.**
  Different plugins may require different minimum bars, columns, volume presence, sorted index, or non-null constraints. A shared helper is useful, but it should stay small and not erase plugin-specific guards.

- **MEDIUM: NaN handling in `wilders_update()` and `update_ema()` needs exact parity rules.**
  "Handles edge cases" is underspecified. Existing plugins may differ on whether NaN propagates, skips, resets, or preserves previous values. Normalizing behavior could change outputs.

- **MEDIUM: Golden-file parity alone may not prove incremental correctness.**
  You need parity between `compute_full()` and repeated `compute_next()` over the same bars, including state handoff at every step.

- **MEDIUM: Performance criterion lacks a measurement plan.**
  "Zero increase in per-bar latency" needs a benchmark threshold, dataset size, number of instruments, number of bars, worker count, and comparison method.

- **MEDIUM: Plan 100-04 may be too broad for one wave if each plugin has unique state.**
  ADX, MFI, Keltner, and VolumeZscore may exercise different rolling and smoothing semantics. Six migrations after only ATR may reveal mixin contract issues late.

- **LOW: File naming may become misleading.**
  `mixins.py` containing pure functions plus `IncrementalMixin` is acceptable but a little muddy.

- **LOW: Security risk is minimal.**

### Suggestions

- Change the mixin contract so `_compute_next_core()` can return both output and next state: `result, next_state = self._compute_next_core(windows, state); result["_state"] = next_state`
- Use `state is None` instead of `if not state`.
- Define the state contract explicitly: mutable vs immutable, may plugins replace state, must `_state` be JSON-safe, are deques allowed, who owns trimming rolling buffers, what happens on malformed state.
- Add conformance tests for the mixin itself before ATR migration.
- Add full-vs-incremental replay tests for every migrated plugin.
- Add performance benchmarks before migrations.
- Keep `wilders_update()` and `update_ema()` behavior mathematically minimal.
- Consider splitting files: `utils.py` for functions, `incremental.py` for IncrementalMixin.
- Stage Plan 100-04 migrations in smaller commits or checkpoints.

### Per-Plan Risk

- 100-01: **MEDIUM** (shared helpers can silently change many plugin outputs)
- 100-02: **HIGH** (state contract must be made explicit)
- 100-03: **MEDIUM** (state bugs are easy to under-fix)
- 100-04: **MEDIUM-HIGH** (breadth and hot-path impact)
- 100-05: **MEDIUM** (mechanical cleanup can still alter edge behavior)
- 100-06: **LOW-MEDIUM** (conceptually simple, but may affect latency)

### Overall Risk Assessment

**MEDIUM-HIGH**. The phase is directionally strong, but the `IncrementalMixin` is the critical risk. If its state contract is too narrow, later migrations will either contort plugin logic or silently break incremental correctness. Harden the mixin API before broad adoption, add full-vs-incremental replay tests, and define a concrete latency benchmark.

---

## Codex Review

### Summary

The plan provides a structured, incremental approach to technical debt reduction and state management standardization across the IndicAgent plugin ecosystem. By decoupling logic from state threading through a mixin and establishing shared utility functions, it directly addresses the identified inconsistencies and bug patterns. The wave-based migration strategy, prioritizing bug fixes and a reference implementation before broad adoption, is sound and minimizes the risk of introducing systemic regressions in the hot path.

### Strengths

- **Logical Sequencing:** Wave-based execution (Fixes -> Reference -> Migration -> Cleanup) is ideal for ensuring stability in a performance-critical system.
- **Separation of Concerns:** `IncrementalMixin` effectively abstracts the boilerplate of state threading, ensuring `compute_next` signatures are consistent.
- **Performance-First Design:** Using pure functions for `wilders_update` and `update_ema` minimizes overhead compared to object-oriented state management or method calls.
- **Proactive Conformance:** Plan 100-06's explicit conformance testing for `supports_incremental` flags is a crucial safeguard against silent performance degradation.

### Concerns

- **HIGH: State Shape Complexity.** The assumption that one `IncrementalMixin` handles all 7 state archetypes (e.g., deque history vs. EMA scalars) might be overly optimistic. A single base class may require too many protected method overrides (the "Template Method" anti-pattern).
- **MEDIUM: `get_main_df` Guard Rails.** If `get_main_df` returns `None` or an empty frame, does the plugin handle this gracefully without crashing the pipeline? The plan needs explicit failure-mode handling for "not enough data" scenarios.
- **MEDIUM: Type Safety and State Contracts.** The `state` parameter is currently loosely typed. Without a formal `Protocol` or `TypedDict` for the state returned by `_seed_state`, we risk runtime `KeyError` exceptions when plugins expect different keys in the `state` dict.
- **LOW: Test Parity Verification.** The plan should explicitly mandate performance regression testing (using a small benchmark of the 31 incremental plugins) to ensure the mixin overhead is truly negligible.

### Suggestions

- **State Typing:** Introduce a `typing.Protocol` for state objects (e.g., `PluginState`) that plugins must adhere to, providing a contract for `_seed_state` and `_compute_next_core`.
- **Explicit State Archetypes:** Instead of one monolithic `IncrementalMixin`, consider a few specialized mixins for common archetypes (e.g., `EMAMixin`, `RollingWindowMixin`). This prevents the base class from becoming a "God Object."
- **Failure Handling:** Update `get_main_df` to raise a specific custom exception (e.g., `InsufficientDataError`) that the executor can catch and log as a standard "warmup period" event rather than a system failure.
- **Verification Benchmark:** Include a micro-benchmark script in Wave 3/4 to measure `compute_next` execution time for the 31 plugins before and after migration.

### Overall Risk Assessment

**MEDIUM**. While the technical approach is sound, the risk stems from the sheer scale of the change (132 plugins). If the state contract is not strictly enforced, the transition to `IncrementalMixin` could lead to subtle state corruption across the pipeline. The structured approach to migration and the inclusion of conformance testing in the final wave significantly mitigate this risk.

---

## Consensus Summary

### Agreed Strengths

1. **Wave-based sequencing is correct** — both reviewers praise the dependency ordering (shared utils -> bug fixes -> mixin -> migrations -> cleanup)
2. **Performance-first pure function design** — `wilders_update` and `update_ema` as module-level functions is the right call for hot-path code
3. **Conformance testing in Plan 100-06** — both reviewers highlight the importance of structural + behavioral conformance tests
4. **Limiting mixin scope to 31 genuine incremental plugins** — avoids unnecessary abstraction on 98 non-incremental plugins
5. **Golden-file parity as success criterion** — both agree this is essential

### Agreed Concerns (highest priority)

1. **IncrementalMixin state mutation contract is underspecified** (Gemini: HIGH, Codex: HIGH)
   Both reviewers flag that `_compute_next_core` mutating state in place may not work for all archetypes. Gemini suggests returning `(result, next_state)` explicitly; Codex suggests specialized per-archetype mixins. The current design needs the state ownership model documented explicitly.

2. **`if not state` fallback is dangerous** (Gemini: HIGH)
   The falsy check on state treats `{}` as missing, which can mask bugs. Both reviewers implicitly agree the fallback logic needs tightening — use `state is None` instead.

3. **Fallback-to-full with incremental windows may be semantically wrong** (Gemini: HIGH)
   If the executor passes a single-bar window to `compute_next`, but `compute_next` falls back to `compute_full`, the full computation may produce incorrect results from insufficient data. This executor contract needs verification.

4. **NaN handling normalization could break parity** (Gemini: MEDIUM, Codex implicitly via type safety)
   If `wilders_update` or `update_ema` change how NaN propagates compared to existing inline code, outputs will drift silently.

5. **Performance regression testing is missing** (Gemini: MEDIUM, Codex: LOW)
   "Zero increase in per-bar latency" has no concrete benchmark plan.

### Divergent Views

1. **Specialized mixins vs. single mixin** — Codex recommends per-archetype mixins (`EMAMixin`, `RollingWindowMixin`), while the plan uses a single `IncrementalMixin`. Gemini focuses on fixing the single mixin's state contract instead. The plan's single mixin is correct if the state ownership model is explicit — per-archetype mixins would be premature abstraction for 31 plugins.

2. **Typed state Protocol** — Codex recommends `Protocol` or `TypedDict` for state objects. Gemini does not mention typing. The research doc already evaluated and rejected typed state dataclasses as "too much machinery for 31 plugins" — deferring is correct.

3. **`InsufficientDataError` exception** — Codex suggests raising a custom exception from `get_main_df`. The current design returns `None`, which is consistent with the existing pattern. Changing to exceptions would require executor changes beyond scope.

### Actionable Items for Plan Revision

1. **Fix `if not state` to `state is None`** in IncrementalMixin (Plan 100-02)
2. **Document state ownership model** — state is mutable, plugins mutate in place, `_compute_next_core` must not return a new state dict (Plan 100-02)
3. **Verify executor window contract** — confirm `compute_full(windows)` fallback receives full historical frames, not incremental windows (Plan 100-02)
4. **Add full-vs-incremental replay test** — for each migrated plugin, verify `compute_full(N bars) == seed + compute_next x N` (Plans 100-02, 100-04)
5. **Define NaN propagation rules** for `wilders_update` and `update_ema` — must match existing inline behavior exactly (Plan 100-01)
6. **Add per-plugin latency benchmark** — measure before/after migration on representative data (Plan 100-04)
