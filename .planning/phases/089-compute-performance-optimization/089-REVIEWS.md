---
phase: 089
reviewers: [gemini, ollama]
reviewed_at: 2026-05-19T00:00:00Z
plans_reviewed:
  - 089-01-PLAN.md
  - 089-02-PLAN.md
  - 089-03-PLAN.md
  - 089-04-PLAN.md
  - 089-05-PLAN.md
  - 089-06-PLAN.md
notes:
  - codex skipped (rate limit — resets 2026-05-20 11:15 AM)
  - claude skipped (self — running inside Claude Code)
  - ollama used gemma4:e4b; only reviewed Plan 01 meaningfully (context window confusion on plan numbering)
---

# Cross-AI Plan Review — Phase 089: Compute Performance Optimization

## Gemini Review

## Review of Phase 089: Compute Performance Optimization

### 1. Summary
Phase 089 is a high-impact architectural refactor that systematically moves the platform from a monolithic, synchronous, and allocation-heavy pipeline to an efficient, concurrent, and incremental DAG-based architecture. The plan is well-phased, respects existing system constraints (like the thread pool and existing Prometheus infrastructure), and correctly identifies the prerequisite chains required for per-key concurrency. The decomposition of the God Class into specialized executors (`FeaturePipelineExecutor`, `PerKeyWorkerManager`) is the correct architectural direction, provided that the state-threading migration (Wave 2) is handled with extreme rigor.

### 2. Strengths
- **Logical Phasing:** The wave-based approach minimizes risk by ensuring foundational cleanup (Wave 0) and allocation optimizations (Wave 1) occur before the complex state-threading (Wave 2) and concurrency (Wave 3) refactors.
- **Incremental Concurrency:** Moving from per-bar synchronous compute to per-key asyncio workers is the optimal solution for both throughput and resource isolation.
- **Regression-Oriented:** The inclusion of parity tests for incremental compute (D-22/Wave 2) and concurrency regression tests (Plan 04) demonstrates a high level of operational maturity.
- **Observability First:** Incorporating OTel metrics for gating and lifecycle events ensures that performance improvements (or regressions) can be immediately identified post-deployment.

### 3. Concerns
- **[HIGH] Wave 2 State Isolation:** The transition from `plugin._state` to explicit parameter threading is the highest-risk activity. If a plugin still maintains hidden state or if the dictionary deep-copy/reference-passing logic is flawed, concurrent bar processing (Wave 3) will introduce non-deterministic state corruption across symbols.
- **[MEDIUM] Queue Backpressure Management:** In Plan 06, `asyncio.Queue` backpressure is mentioned, but the interaction with the global pipeline ingest loop needs clarification. If a specific symbol/TF worker is slow (e.g., due to O(N) spike or network delay), it could block the global producer for that key.
- **[MEDIUM] Dual-Write Removal:** Plan 02's requirement to audit and remove flat features dual-write is sound, but there's a risk of breaking downstream consumers that are not yet instrumented or registered in the code repository.
- **[LOW] State Threading Protocol Completeness:** The Plugin protocol updates (Plan 04) require 100% adherence from all 132+ plugins. The plan assumes this can be done as a refactor; ensuring type-safety or static analysis coverage (e.g., mypy) during this transition is critical.

### 4. Suggestions
- **State Isolation Validation:** During Plan 04 (Wave 2), implement a `StateProxy` decorator that wraps the state dictionary passed to plugins. In test mode, this proxy should be immutable or detect unauthorized writes to prevent plugins from inadvertently mutating state that belongs to a different thread/worker.
- **Global Producer Resiliency:** For Plan 06, ensure the `PerKeyWorkerManager` incorporates a "drop-and-log" or "slow-consumer-warn" mechanism for queues exceeding a certain depth before fully blocking the global ingest loop, to prevent a single stalled instrument from freezing the entire system.
- **Automated Audit for Dual-Write:** Rather than just manual auditing for Plan 02, write a quick static analysis script to check for any imports or usage of the "flat features" keys across the whole `src/` and `services/` trees.
- **Documentation of "Incremental" Contracts:** Formalize the contract of `compute_next` in `src/intelligence/plugins.py`. If a plugin claims to be incremental, it must document its storage requirement (e.g., "requires X state keys").

### 5. Risk Assessment
**Overall Risk: MEDIUM**

*Justification:* The scope of changes is massive (affecting the entire intelligence core). While the plan is robust, the complexity of migrating 132+ plugins to explicit state threading and moving to per-key concurrency provides many opportunities for subtle bugs. The rigorous testing and parity-check requirements are appropriate mitigations, but the state-threading migration must be monitored with extreme vigilance during the integration testing phase.

---

## Ollama Review (gemma4:e4b)

*Note: Model context window confusion caused it to only meaningfully review Plan 01. Relevant excerpts below.*

### Plan 01 Summary
Plan 01 is the essential setup phase, reorganizing the codebase foundationally. It is necessary to establish ownership (e.g., FeaturePipelineExecutor owning I1-I6) and implement core observability features like the 5 OTel counters. This phase primarily reduces structural dependencies and improves modularity, which is crucial before tackling the deep performance fixes.

### Plan 01 Strengths
- **Strong Decomposition:** Extracting the FeaturePipelineExecutor is a crucial win, forcing the separation of concerns and isolating the bulk of the I1-I6 compute logic.
- **Observability First:** Adding the 5 specific OTel counters (e.g., `gate_rejections`, `cis_null`) allows the team to immediately measure the impact and success rate of later performance optimizations.
- **Clear Ownership Model:** Explicitly requiring the orchestrator to stop accessing internal executor state (`_plugin_cache`, `sig_proc._setup_last_fire`) ensures clean class boundaries.

### Plan 01 Concerns
- **[MEDIUM] Scope Creep Risk:** The requirement to "cleanup dead code" and "delete deferred imports" could creep into extensive, time-sink refactoring if not strictly scoped to functional removal.
- **[MEDIUM] Cache Transition Complexity:** Migrating stream caches to `CacheManager` (adding `update_cross_asset/update_macro/update_htf_intel` methods) could introduce subtle race conditions if synchronization primitives are not perfectly maintained during the transition.
- **[LOW] I7 Consolidation:** While consolidating the I7 setup block is good, ensuring the new `state` object passed to the updated function signature maintains parity with the old object structure is a significant point of failure risk.

### Plan 01 Recommendations
- Verify the contract for all functions passed to the updated I7 function signature.
- Treat the state management in the I7 updates as the highest priority unit testing area before merging.

---

## Consensus Summary

Two reviewers (Gemini, Ollama/gemma4:e4b) were successfully invoked. Codex was rate-limited.

### Agreed Strengths (2+ reviewers)
- **Wave-based dependency ordering** is correct and risk-mitigating — foundational cleanup before the state-threading and concurrency work.
- **FeaturePipelineExecutor extraction** is the right architectural direction; both reviewers praised it as a clean separation of concerns.
- **Observability-first** approach (5 OTel counters in Plan 01) is strong — performance improvements must be measurable before and after.
- **The Plan 04 -> Plan 06 dependency** (PERF-03 state threading before PERF-07 per-key concurrency) is correctly sequenced and essential.

### Agreed Concerns (2+ reviewers)
- **[HIGH] Plugin state isolation is the #1 risk.** Both reviewers flag the transition from `plugin._state` to explicit state threading as the highest-risk activity in this phase. Hidden plugin state, improper dict reference semantics, or any plugin that bypasses the protocol could cause non-deterministic signal corruption when concurrent dispatch is enabled in Wave 3. Mitigation: the Plan 04 concurrency regression test is the right approach; consider adding a mypy/Protocol enforcement pass to ensure all 132 plugins comply.
- **[MEDIUM] CacheManager stream cache migration** could introduce async race conditions during the Wave 0 transition. Mitigation: the migration is additive (new methods only), but the lockless dict access pattern must be verified; the `_cross_asset_cache`, `_macro_cache`, and `_htf_intel_cache` are currently written from the consume loop and read inside `_run_i1_to_i6` — if these are still accessed concurrently post-migration, CacheManager needs an asyncio.Lock per cache.
- **[MEDIUM] Flat features dual-write audit** must be exhaustive. Removing the dual-write path without a complete consumer audit risks silent data loss in an active plugin.

### Divergent Views
- **Queue back-pressure in Plan 06:** Gemini raised the concern that a slow per-key worker blocks the global producer for that key. The plans address this with `asyncio.Queue(maxsize=100)` and blocking `put()` — this is intentional (back-pressure is the correct behavior; a stalling key should slow only itself). No divergence on solution, but worth confirming the queue maxsize is tunable and not hardcoded.
- **Scope of Plan 01 cleanup:** Ollama flagged scope creep risk on dead-code removal. The plans scope cleanup to specific named items (D-24: _df_cache, deferred imports, orchestrator _plugin_cache) — not open-ended refactoring. Risk is low given the explicit enumeration.

### Priority Actions for Implementor
1. Before Wave 3 (Plan 06), run `grep -rn "plugin\._state\|self\._state" src/intelligence/features/` to confirm zero hidden state assignments in plugin files post-Plan 04.
2. Add `asyncio.Lock` protection to CacheManager's three new stream cache update methods if the consume loop and FPE can access them concurrently.
3. For Plan 02 PERF-02: run the consumer audit script (`grep -rn 'frames\["features"\]' src/intelligence/`) before removing the dual-write path.
4. Document the queue maxsize (100) as a Settings parameter to allow tuning without code change.
