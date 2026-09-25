---
spec: 2026-05-21-plugin-infrastructure-design
reviewers: [gemini, codex]
reviewed_at: 2026-05-21
---

# Cross-AI Design Review - Plugin Infrastructure

## Gemini Review

**Risk: LOW**

### Summary
The design spec is excellent - highly grounded, pragmatic, and well-aligned with the system's constraints. By rejecting heavy-handed inheritance in favor of "Protocol + Promoted Helpers + Targeted Mixin," the design avoids architecture astronautics while directly addressing the identified high-severity production bugs. The analysis of the 132 plugins is thorough.

### Strengths
- Architectural pragmatism: Protocol/Duck Typing preserves performance and decoupling
- Targeted solution: treats incremental as specific sub-domain, not universal requirement
- Bug-driven design: mixin addresses specific state management flaws
- Correct incremental fallback: central mixin eliminates repetitive error-prone logic
- Regression path: explicit mapping of every bug to mixin functionality

### Concerns
- **MEDIUM:** State param ownership - mixin should validate state before passing to plugins
- **HIGH:** CVD/OFI architecture - treat as isolated migration sprint due to data path role
- **LOW:** Implicit `_state` attachment hides side effects

### Suggestions
- Execute Phase A (executor safety net) immediately
- Add "cold start" integration test for BOCPD/MarketProfile/SessionLevels
- Make `_compute_full_core`/`_compute_next_core` strict signatures for future type safety

---

## Codex Review

**Risk: MEDIUM-HIGH**

### Summary
Direction is mostly right, but spec is not yet execution-ready. Has count inconsistencies, archetype overreach, and a risky executor "recovery" phase that can hide state bugs or persist cross-symbol stale state. The IncrementalMixin is useful as migration pattern but does not actually prevent all listed bugs unless paired with tests, linting, and removal of `self._state` writes.

### Strengths
- Correctly rejects universal base class
- Correctly identifies PERF-03 failure mode (self._state vs parameter)
- Executor already validates `_state` - good correctness guard
- Pure math helpers are low-risk if adoption stays opportunistic
- Correctly separates inline recomputation from shared utility work

### Concerns
- **HIGH:** Archetype analysis too loose - OBV/GARCH/Kalman aren't "Wilder's Accumulator". ADX omitted from that group despite being Wilder-style. Keltner/MovingAverages appear in multiple archetypes.
- **HIGH:** IncrementalMixin doesn't prevent `self._state` bugs - plugins can still read/write `self._state` inside `_compute_next_core()`. Enforcement requires tests or static checks.
- **HIGH:** Phase A `_state` recovery is dangerous - can persist stale/cross-symbol state if plugin instances are shared across threaded executions. Masks bugs instead of fixing them.
- **HIGH:** Shared plugin instances + `self._state` is the real HFT/concurrency hazard. PERF-03 intentionally stopped assigning `plugin._state` before threadpool dispatch. Remaining `self._state` use is a race risk.
- **MEDIUM:** Spec internally inconsistent - says "No mixin" under Approach D, then proposes IncrementalMixin. Says "31" then "11".
- **MEDIUM:** "121 plugins delete compute_next" may conflict with Protocol if it declares `compute_next`.
- **MEDIUM:** Mixin state attachment mutates and returns same dict object - state manager must snapshot safely.

### Suggestions
- Fix inventory first: machine-checked table from registered plugin instances
- Drop or narrow Phase A - prefer fail-fast with targeted fixes. If kept, make temporary, logged at error level, metric-counted, never recover from `self._state` unless allowlisted.
- Split Protocol: base Protocol + separate `IncrementalCapable` Protocol, or runtime `hasattr` check
- Make mixin contract stricter: `_compute_next_core(frames, state) -> tuple[outputs, new_state]` to avoid in-place mutation
- Add conformance tests for every `supports_incremental=True` plugin (cold start returns `_state`, warm returns `_state`, incremental matches full within tolerance, no `self._state` writes)
- Lint/grep gate for migrated plugins: no `self._state` references
- Reorder execution: fix bugs first, then helpers, then delete delegation methods
- Benchmark p50/p95/p99 per plugin after migration

---

## Consensus Summary

### Agreed Strengths
- Protocol + dataclass design is correct for the non-incremental majority
- Bug-driven design approach is sound
- Pure math helpers (wilders_update, update_ema) are low-risk wins

### Agreed Concerns (both reviewers flagged)
1. **Phase A recovery is risky** - Gemini says proceed immediately; Codex says drop or narrow it. Both agree it can mask bugs. Codex's suggestion (fail-fast, temporary, logged) is more conservative and safer.
2. **CVD/OFI need isolated treatment** - high-risk architectural change requiring dedicated sprint
3. **Mixin needs enforcement** - both reviewers note the mixin encourages correct patterns but doesn't prevent `self._state` access. Codex's conformance tests + lint gate suggestion addresses this.

### Divergent Views
- **Overall risk**: Gemini says LOW, Codex says MEDIUM-HIGH. The gap is driven by Codex identifying the concurrency hazard (shared plugin instances + `self._state` in threadpool dispatch) which Gemini did not flag.
- **Archetype quality**: Codex challenges the grouping (OBV/GARCH/Kalman aren't Wilder's Accumulator; ADX is missing). This needs fixing before phased migration.
- **Protocol revision**: Codex explicitly suggests splitting the Protocol; Gemini doesn't mention it.

### Action Items for Spec Revision
1. Fix internal inconsistencies (31 vs 11, "No mixin" vs IncrementalMixin)
2. Tighten archetype groupings - remove OBV/GARCH/Kalman from "Wilder's Accumulator", add ADX
3. Replace Phase A recovery with fail-fast + targeted bug fixes
4. Add conformance tests for all `supports_incremental=True` plugins
5. Add lint/grep gate: no `self._state` after migration
6. Consider splitting Protocol into base + IncrementalCapable
7. Benchmark per-plugin latency after migration
