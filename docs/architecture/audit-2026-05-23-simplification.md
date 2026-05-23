# Simplification Audit — 2026-05-23

**Framing:** Renaissance / load-bearing simplification. A bigger machine built on tangled
foundations breaks in unexpected ways. Each item below either reclaims code that is never
executed, removes indirection that will grow friction with v2.8, or identifies a scaling cliff
that doubles in severity when symbol count doubles.

---

## Section 1: Delete/Merge Candidates

---

**Item:** `src/core/ml/shadow.py` (ShadowRecorder) and `src/core/ml/transform_recorder.py`
(TransformRecorder) — archived stubs with deprecation warnings
**Lines reclaimed:** ~200 (94 + 110)
**Risk:** Low
**Verification needed:** Both modules emit `DeprecationWarning` at import time. However,
`services/intelligence_pipeline_agent.py:250` and five pipeline stage files
(`calibrator.py`, `regime_gate.py`, `quality_gate.py`, `ranker.py`, `tod_adjuster.py`) still
import `TransformRecorder` at runtime via local `TYPE_CHECKING`-guarded imports. The pipeline
instantiates `TransformRecorder` in `_setup()` and passes it live to `SignalProcessor`, which
routes it through all five pipeline stages. So TransformRecorder is not truly dead — data still
flows into `signal_transform_log` via the deprecated path. Confirm with a live query:
`PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "SELECT COUNT(*) FROM signal_transform_log WHERE ts > NOW() - INTERVAL '1 day'"`.
`GraduationComputeAgent` (`services/graduation_compute_agent.py:45`) reads `signal_transform_log`
directly. If the table is still receiving writes and graduation still reads it, the "archived"
label is misleading — the migration from TransformRecorder to LineageRecorder is incomplete.
**Full delete requires:** either migrating graduation to use `signal_lineage` instead, or
confirming `signal_transform_log` is intentionally kept as a parallel write path.

---

**Item:** `src/core/ml/shadow.py` (ShadowRecorder only) — zero production instantiations confirmed
**Lines reclaimed:** ~94
**Risk:** None
**Verification needed:** `grep -rn "ShadowRecorder(" /home/bg/dev/indicagent/src/ /home/bg/dev/indicagent/services/` returns zero hits outside the archived file. Safe to delete. `signal_transform_log` and `alpha_multiplier_shadow` are separate tables; `ShadowRecorder` wrote only to `alpha_multiplier_shadow`. Confirm `alpha_multiplier_shadow` is not queried anywhere after deletion.

---

**Item:** `src/core/ai/safe_wrapper.py` — deliberately poisoned `ImportError` stub
**Lines reclaimed:** 10
**Risk:** None
**Verification needed:** File raises `ImportError` on import. It exists only to surface stale
references loudly. Confirm no remaining import in codebase (`grep -rn "safe_wrapper" /home/bg/dev/indicagent/src/ /home/bg/dev/indicagent/services/` returns zero hits outside the file itself). Delete the file once you've confirmed nothing imports it.

---

**Item:** `_on_guardrail_violation` and `_audit_payload` hooks in `src/core/ai/base_agent.py`
**Lines reclaimed:** ~10
**Risk:** Low
**Verification needed:** `_on_guardrail_violation` is a no-op (`pass`). `_audit_payload` returns
`{}`. Neither is overridden in any subclass. Neither is wired to any caller that acts on the
return value. Both are labelled "future phase" with no v2.8 designs referencing them by name.
`_on_error` is NOT dead — it emits `AI_AGENT_ERRORS_TOTAL` and publishes a lineage event; keep
it. `_on_guardrail_violation` and `_audit_payload` are the deletable pair.

---

**Item:** `has_graduation` class attribute on `NarrativeGroupComputeService`
(`services/narrative_group_compute_agent.py:46`)
**Lines reclaimed:** 1 line + associated test churn
**Risk:** None
**Verification needed:** `BaseGroupService._run()` checks `hasattr(type(self), "_graduation_loop")`,
not `has_graduation`. The attribute is never read. The existing unit test at
`tests/unit/core/test_base_group_service.py:49` already asserts that `has_graduation` must NOT
exist on `BaseGroupService`. NarrativeGroupComputeService sets it to `False` as a guard, but
since the check uses `hasattr(..., "_graduation_loop")` and narrative does not define that method,
the guard is redundant.

---

**Item:** `SWARM_QUEUE_TIMEOUT_MS` setting in `src/config/settings.py:179`
**Lines reclaimed:** 5 lines + env-var documentation
**Risk:** None
**Verification needed:** The setting docstring says "Deprecated — semaphore timeout removed (D-07)".
`grep -rn "SWARM_QUEUE_TIMEOUT_MS" /home/bg/dev/indicagent/src/ /home/bg/dev/indicagent/services/`
returns zero hits outside `settings.py`. Safe to delete. No env-var migration needed; the field
is ignored by all callers.

---

**Item:** `LLM_RATE_LIMIT_RPM` and `LLM_RATE_LIMIT_TPM` settings — orphaned fields
**Lines reclaimed:** ~6 lines
**Risk:** None
**Verification needed:** `LLMProviderChain._make_rate_limiters()` consults `settings.LLM_RATE_LIMITS`
(a dict, not defined in Settings), never `LLM_RATE_LIMIT_RPM` or `LLM_RATE_LIMIT_TPM`. The two
scalar fields exist in `Settings` but are not read by any runtime code. They can be deleted once
confirmed no external tooling or .env relies on them.

---

**Item:** `SHADOW_CORRELATION_THRESHOLD` and `SHADOW_MIN_SAMPLES` settings
**Lines reclaimed:** ~6 lines
**Risk:** None
**Verification needed:** `grep -rn "SHADOW_CORRELATION_THRESHOLD\|SHADOW_MIN_SAMPLES" /home/bg/dev/indicagent/src/ /home/bg/dev/indicagent/services/` returns zero hits outside `settings.py`. Neither
field is read by `shadow_auditor_agent.py`, which uses its own hardcoded thresholds or
`getattr` calls for different names. Safe to delete.

---

**Item:** `LANGFUSE_HOST` setting in `src/config/settings.py:242`
**Lines reclaimed:** 1 line
**Risk:** None
**Verification needed:** Zero production uses. The field was added for a LangFuse integration that
was never implemented. `grep -rn "LANGFUSE\|langfuse" /home/bg/dev/indicagent/src/ /home/bg/dev/indicagent/services/` returns only this one line. Safe to delete.

---

**Item:** `MLFLOW_TRACKING_URI` setting in `src/config/settings.py:239`
**Lines reclaimed:** 1 line
**Risk:** None
**Verification needed:** `src/intelligence/services/ml_training_compute_agent.py:63` declares its
own `_MLFLOW_TRACKING_URI = "http://localhost:5000"` and calls `mlflow.set_tracking_uri()`
directly, bypassing the Settings field entirely. The setting exists but is never read. Safe to
delete the Settings field (not the local constant in the training agent).

---

**Item:** `IntelligenceJournal` and `ProvenanceChain` schema in
`src/core/schemas/intelligence_journal.py` — never instantiated
**Lines reclaimed:** ~26 lines
**Risk:** Low
**Verification needed:** `grep -rn "IntelligenceJournal(" /home/bg/dev/indicagent/src/ /home/bg/dev/indicagent/services/` returns zero hits. The class is re-exported from `src/intelligence/schemas.py` as
`# noqa: F401` (suppressed unused import), confirming it is present for future use, not current
use. The `topic_intelligence_journal()` topic function IS used — the pipeline publishes full
`IntelligenceEvent` serialized JSON to that topic; `IntelligenceJournal` the model was a planned
structured wrapper never wired to a producer. Can be removed from re-export in `schemas.py` and
archived if the v2.8 AI platform will use a different audit schema.

---

**Item:** `GuardrailsValidator` registry in `src/core/llm/guardrails.py` — zero schemas registered
**Lines reclaimed:** 53 lines (full file)
**Risk:** Low — v2.8 plans to add Guardrails AI as a replacement
**Verification needed:** `_guardrails.register()` is never called anywhere in the codebase.
`_guardrails.has_schema()` in `chain.py:194` always returns `False` — the branch is never taken.
The guardrails call in `_generate_inner` is dead code. The class is safe to delete. v2.8 is
expected to bring Guardrails AI as the replacement; the current stub adds maintenance overhead
without providing any actual validation.

---

**Item:** `SemanticCache` max_size is hardcoded to 500 in `src/core/llm/chain.py:35`, ignoring
`Settings.LLM_SEMANTIC_CACHE_SIZE`
**Lines reclaimed:** 0 (this is a bug/inconsistency, not dead code)
**Risk:** Low
**Verification needed:** `_cache = SemanticCache(max_size=500)` is module-level. `Settings.LLM_SEMANTIC_CACHE_SIZE` exists but is never passed to the constructor. When symbol count doubles, prompts increase proportionally — the cache should be sized from Settings. Fix: change to
`SemanticCache(max_size=get_settings().LLM_SEMANTIC_CACHE_SIZE)` or pass via `LLMProviderChain.__init__`. This is also a friction point for v2.8 LiteLLM integration (see Section 2).

---

**Item:** `TokenBudget` in `src/core/llm/chain.py` — observability-only, never gates execution
**Lines reclaimed:** 60 lines (`token_budget.py`)
**Risk:** Low
**Verification needed:** The budget warning in `chain.py:220-226` logs but does not change provider
routing or stop execution. The comment at `chain.py:218` explicitly says "budget is
observability-only — never gates execution". The `LLM_SEMANTIC_CACHE_SIZE` / daily budget fields
in Settings also read 0 cost (cost_per_1k=0.001 but only for Ollama estimation). If v2.8 LiteLLM
is taking over provider management, `TokenBudget` should be deleted to avoid duplication. If
budget enforcement is wanted, it should be a real gate — not a logging-only side effect.

---

**Item:** `src/intelligence/ai/TEMPLATE_agent.py` calls `self._llm.generate()` directly
(bypasses audit trail)
**Lines reclaimed:** 0 (code change, not deletion)
**Risk:** Low
**Verification needed:** Line 78 calls `await self._llm.generate(...)` instead of
`await self._llm_generate(...)`. The CLAUDE.md rule is explicit: "Agents MUST use
`self._llm_generate()` — never call `self._llm.generate()` directly." Every production agent
(skeptic, correlation, regime_coherence, counterfactual, narrative) already uses `_llm_generate`.
The TEMPLATE is the one outlier. Since TEMPLATE is copied to create new agents, leaving this bug
in it means every future agent author will copy the violation unless caught in code review.

---

**Item:** `GraduationComputeAgent` + `GraduationWriterAgent` + `src/intelligence/swarm/graduation.py`
— reads from `signal_transform_log`, which is populated by the deprecated `TransformRecorder`
**Lines reclaimed:** 334 + 120 + 350 = ~800 lines if fully removed; or 0 if kept as-is
**Risk:** Medium
**Verification needed:** This is not dead code — `graduation_compute_agent` runs as a live service.
The concern is architectural: `signal_transform_log` is being written by `TransformRecorder`
(labelled "ARCHIVED") and read by `graduation_compute_agent`. Meanwhile `signal_lineage`
(written by `LineageRecorder`) duplicates the multiplier data and `alpha_swarm_agent._graduation_loop`
runs its own Spearman weight learning directly. There are now TWO graduation mechanisms:
(1) `graduation_compute_agent` evaluating `transform_graduation` table, and (2)
`alpha_swarm_agent._graduation_loop` updating `swarm_agent_weights` table. Clarify which
graduation path is canonical before v2.8 adds more agents. The `transform_graduation` + graduation
pipeline appears to be the older, plugin-level graduation; the swarm loop is the newer agent-level
graduation. If they serve different purposes, document it. If one is superseded, delete it.

---

## Section 2: v2.8 Friction Points

---

**Friction point:** Per-bar state scan is O(N plugins × symbols × timeframes) on every bar
**Files affected:**
- `src/intelligence/pipeline/state_manager.py` — `get_all_states_for()` iterates all
  `_plugin_states` entries to filter by `(symbol, tf)`
- `src/intelligence/pipeline/feature_pipeline_executor.py:200` — calls per bar
**When it hurts:** Immediately at 116 symbols. At 58 symbols with ~4 TFs = 232 (symbol, tf) pairs
and 132 plugins, `_plugin_states` holds ~30,624 keys. `get_all_states_for()` scans all of them
per bar to find ~132 matching entries. At 116 symbols this doubles to ~61,248 keys per scan.
With multiple active bars arriving concurrently, this scan runs thousands of times per minute.
**Recommended action:** Do before v2.8. Index `_plugin_states` with a secondary lookup:
`dict[(symbol, tf), dict[str, dict]]` instead of a flat `dict[tuple[plugin,sym,tf], dict]`. The
`get_all_states_for` method becomes an O(1) lookup. `update()` and `update_batch()` must update
both. Checkpoint serialization stays the same. The refactor is ~30 lines and eliminates a
quadratic scan that becomes the dominant hot-path cost at scale.

---

**Friction point:** Checkpoint file grows proportionally with symbols; 5-minute write becomes
blocking JSON serialization of O(symbols × tiers × plugins) state
**Files affected:**
- `src/intelligence/pipeline/state_manager.py:141` — `write_checkpoint()` serializes entire
  `_plugin_states` via `_tag_value()` to a JSON file
- `src/intelligence/pipeline/state_manager.py:37` — hardcoded path `cache/pipeline_checkpoint.json`
**When it hurts:** At 116 symbols, the checkpoint payload doubles. The `_tag_value()` serializer
walks every plugin state dict recursively. For GARCH/Kalman states (numpy arrays), this involves
array-to-list conversion. At 58 symbols this is tolerable; at 116+ with complex plugin states
(e.g. HMM maintains model parameters), the 5-minute checkpoint write can block the asyncio loop
if the underlying `Path.write_text()` call is slow.
**Recommended action:** Do before v2.8. Wrap `write_checkpoint()` in `asyncio.to_thread()` to
prevent loop blocking. Additionally, consider partitioning the checkpoint by symbol to enable
incremental writes. Hardcoded path `cache/pipeline_checkpoint.json` should become a Settings field
for multi-shard deployments (`PIPELINE_CHECKPOINT_PATH`).

---

**Friction point:** `PluginStateManager._plugin_states` is a single in-process dict; no sharding
path for the intelligence pipeline beyond the `symbol_filter` mechanism
**Files affected:**
- `src/intelligence/pipeline/state_manager.py`
- `src/intelligence/pipeline/per_key_worker_manager.py`
- `services/intelligence_pipeline_agent.py:256-257`
**When it hurts:** The `symbol_filter` env var enables basic sharding by running two pipeline
instances each handling a subset of symbols. However, `BarHistory`, `PluginStateManager`, and
`CacheManager` all hold global state. Doubling symbols also doubles all three simultaneously. The
GIL cap is 12 thread-pool workers — adding symbols does not add parallelism, only queue depth.
**Recommended action:** Safe to defer to v2.8, but document the sharding contract explicitly:
at 116 symbols, plan for two pipeline instances with `INTELLIGENCE_PIPELINE_SYMBOL_FILTER`
splitting the symbol set. The mechanisms exist; operator runbooks need updating. The thread pool
auto-sizing (`max(4, cpu_count // 2)`) should scale up for higher symbol counts.

---

**Friction point:** LLM provider coupling — all AI agents receive `LLMProviderChain` at
construction time; adding LiteLLM requires touching every agent constructor
**Files affected:**
- `src/intelligence/ai/alpha/skeptic_agent.py:57`
- `src/intelligence/ai/alpha/correlation_agent.py:73`
- `src/intelligence/ai/alpha/counterfactual_agent.py:47`
- `src/intelligence/ai/alpha/regime_coherence_agent.py:81`
- `src/intelligence/ai/narrative/narrative_agent.py:49`
- `src/core/ai/base_group_service.py:130` — instantiates `LLMProviderChain`
- `services/alpha_swarm_agent.py:162-167` — passes chain to all agents
**When it hurts:** At v2.8 phase 1 (LiteLLM integration). Every agent constructor signature
hardcodes `llm_chain: LLMProviderChain`. Replacing with LiteLLM means touching 5 agent files
plus the group service constructor, the chain wiring in `_setup()`, and any tests mocking
`LLMProviderChain`.
**Recommended action:** Do before v2.8. The fix is one layer of indirection: move `_llm` from
agent constructor injection to a late-binding accessor on `BaseAIAgent`. E.g., agents call
`self._get_llm()` which returns the chain from `self._group_service._llm_chain`. This way
swapping `LLMProviderChain` for a LiteLLM adapter only requires changing one place:
`BaseGroupService._setup()`. Agent constructors become `def __init__(self, **kwargs)` with no
LLM dependency. The v2.8 TEMPLATE should reflect this pattern.

---

**Friction point:** Adding a new AI agent requires touching 3 files minimum (agent file, swarm
agent `_agents` list, shadow registry); with evolvable agents this should be 1 file or 0
**Files affected:**
- `services/alpha_swarm_agent.py:162-170` — hardcoded `self._agents` list with specific imports
- `src/core/ai/base_group_service.py` — no discovery mechanism
- Everywhere a shadow_registry row must be manually seeded
**When it hurts:** At v2.8 evolvable agent registry phase. Currently adding an agent requires:
(1) creating the agent file, (2) registering in `alpha_swarm_agent._setup()`, (3) running a
migration or `shadow_registry_ensure()`. "Evolvable" means the agent set changes without code
deploys. The hardcoded `self._agents` list in `alpha_swarm_agent.py` is the primary obstacle.
**Recommended action:** Do during v2.8 evolvable agents phase. Design: agents declare themselves
via a `@register_agent` decorator or entry-point discovery. `BaseGroupService` loads registered
agents dynamically, not from a hardcoded list. `shadow_registry_ensure()` already handles
idempotent DB enrollment — the missing piece is the Python-level registry. Model after
`register_plugins.py` which already has a declarative `TIER_I*` list pattern.

---

**Friction point:** `src/core/llm/` stack conflicts with LiteLLM's design surface; several
components overlap
**Files affected:**
- `src/core/llm/providers.py` — `OllamaProvider`, `OpenRouterProvider`, `LLMChain` (replaced by
  LiteLLM provider abstraction)
- `src/core/llm/semantic_cache.py` — LiteLLM has built-in caching via `litellm.cache`
- `src/core/llm/rate_limiter.py` — LiteLLM has built-in rate limiting
- `src/core/llm/chain.py` — the `LLMProviderChain` facade would become a thin wrapper or be
  replaced
- `src/core/llm/token_budget.py` — LiteLLM tracks tokens natively
**When it hurts:** At v2.8 LiteLLM integration. The current stack is custom-built (~450 lines
across these 5 files). LiteLLM replicates most of this. The audit trail via `_publish_audit()`
is the only piece LiteLLM does not natively provide — that logic must be preserved.
**Recommended action:** Do during v2.8. Plan: replace `providers.py` + `chain.py` with a
LiteLLM-backed implementation. Keep `_publish_audit()` logic as a callback/hook. Retire
`semantic_cache.py`, `rate_limiter.py`, and `token_budget.py` in favour of LiteLLM's equivalents.
The `GuardrailsValidator` stub can be replaced by Guardrails AI. Net line reduction: ~400 lines.
The one load-bearing piece to port is the Kafka audit trail wiring in `_publish_audit()`.

---

**Friction point:** `BaseAIAgent._llm` is set by agent constructors but validated nowhere;
`_llm_generate()` calls `self._llm.generate()` which will `AttributeError` if `_llm` is never set
**Files affected:**
- `src/core/ai/base_agent.py` — `_llm` is not declared in `__init__`
- All five production agents set `self._llm = llm_chain` in their own `__init__`
- `src/intelligence/ai/TEMPLATE_agent.py:55` — template sets it
**When it hurts:** At v2.8 when dynamically registered agents that forget `self._llm = ...` will
produce silent `AttributeError` at call time. The error only surfaces when `_compute()` runs.
**Recommended action:** Do before v2.8. Add `self._llm: LLMProviderChain | None = None` to
`BaseAIAgent.__init__`, and add a check in `_llm_generate()`:
`if self._llm is None: raise RuntimeError(f"{self.agent_id}: _llm not wired")`. This surfaces
mis-wired agents at agent construction time, not at first LLM call.

---

**Friction point:** Prompt version is a class attribute on each agent but is also manually
injected into `audit_context` in `_llm_generate()` — DSPy optimizer will want to modify prompts
at runtime without changing class attributes
**Files affected:**
- `src/core/ai/base_agent.py:228` — `audit_context["prompt_version"] = self.prompt_version`
- `src/intelligence/ai/alpha/skeptic_agent.py:51` — `prompt_version = ACTIVE_VERSION`
- Every agent's `_compute()` calls `_build_multiplier_output(prompt_version=ACTIVE_VERSION)`
**When it hurts:** At v2.8 DSPy integration phase. DSPy optimizes prompts by evaluating variants.
The current design assumes a static `ACTIVE_VERSION` string. DSPy needs to run agents with
different prompt versions simultaneously without restarting services. The class-level constant
makes this impossible without either subclassing (expensive) or instance-level override (not
currently supported).
**Recommended action:** Do during v2.8 DSPy phase. Move `prompt_version` from class attribute
to an instance attribute that can be set at construction time, defaulting to `ACTIVE_VERSION`.
This allows `BaseGroupService` to inject version tags per-agent, and DSPy to create variant
instances with different versions.

---

**Friction point:** Zep memory integration has no hook point in `BaseAIAgent` or `AIContext`
**Files affected:**
- `src/core/ai/base_agent.py` — no `_memory` attribute
- `src/core/ai/context.py` — `AIContext` is purely market data; no session/agent memory slot
- `src/core/ai/base_group_service.py` — no memory wiring in `_setup()`
**When it hurts:** At v2.8 Zep memory integration phase. Zep provides persistent agent memory
across sessions (conversation history, learned preferences). The current `AIContext` is stateless
by design — it is rebuilt per-signal from the Kafka cache. Injecting Zep memory will require
adding a memory retrieval step between context cache lookup and agent dispatch.
**Recommended action:** Do during v2.8. Add `memory: dict | None = None` to `AIContext` as an
optional field. Add `_memory_client: Any | None = None` to `BaseGroupService.__init__()`. The
`_enrich_context()` method in `alpha_swarm_agent.py` is the natural injection point for Zep
retrieval before agent dispatch. This is a clean seam — no existing logic needs to change,
memory is additive.

---

**Friction point:** `get_all_states_for()` in `PluginStateManager` is called once per bar per
(symbol, tf) and does a full dict comprehension over all plugin states — O(132 plugins ×
all symbols × all tfs) per call
**Files affected:**
- `src/intelligence/pipeline/state_manager.py:91-102`
- `src/intelligence/pipeline/feature_pipeline_executor.py:200`
**When it hurts:** Listed above in Section 1, repeated here for v2.8 framing: at 116 symbols
with 6 TFs (1m/5m/15m/1h/4h/1d) this is 696 × 132 = ~91,872 dict entries scanned per bar.
The pipeline processes bars for all symbols concurrently via per-key workers. Under load at
double symbol count, this becomes the dominant CPU cost in the Python hot path.
**Recommended action:** See Section 1 item above — index by `(symbol, tf)` before v2.8.

---

## Prioritized Top-10: Highest Complexity-Reduction / Implementation-Risk Ratio

| Rank | Change | Complexity Reduction | Risk | Effort |
|------|--------|---------------------|------|--------|
| 1 | Index `PluginStateManager._plugin_states` by `(symbol, tf)` to eliminate O(N) scan per bar | Eliminates quadratic scaling cliff; bars per second stays flat as symbols double | Low — mechanical dict refactor | 1-2 hours |
| 2 | Delete `GuardrailsValidator` stub (53 lines, zero schemas registered, dead branch in chain.py) | Removes dead branch on every LLM call; cleans up pre-v2.8 for Guardrails AI | None — confirmed zero schemas registered | 30 min |
| 3 | Delete `ShadowRecorder` archived file and confirm `alpha_multiplier_shadow` table is inactive | Removes source of confusion about "archived" vs "active" write paths | Low — confirm table is empty first | 30 min |
| 4 | Fix TEMPLATE_agent.py to use `_llm_generate()` not `_llm.generate()` | Every future agent copying this template will have correct audit trail wiring | None — one-line change | 5 min |
| 5 | Delete dead Settings fields: `SWARM_QUEUE_TIMEOUT_MS`, `LLM_RATE_LIMIT_RPM/TPM`, `SHADOW_CORRELATION_THRESHOLD`, `SHADOW_MIN_SAMPLES`, `LANGFUSE_HOST`, `MLFLOW_TRACKING_URI` | Shrinks Settings god object; reduces cognitive load when reading configuration | None — confirmed zero runtime uses | 20 min |
| 6 | Move `_llm` wiring from agent constructors to `BaseGroupService` late-binding | Makes LiteLLM swap a 1-file change instead of 5+; removes per-agent constructor coupling | Low — straightforward refactor, tests need updating | 2-3 hours |
| 7 | Clarify graduation architecture (dual graduation paths: `signal_transform_log` vs `signal_lineage`) | Eliminates architectural ambiguity before v2.8 adds more agents; prevents third graduation mechanism | Medium — requires confirming production data flow | 1 day |
| 8 | Add `self._llm: LLMProviderChain | None = None` to `BaseAIAgent.__init__` with guard in `_llm_generate()` | Surfaces mis-wired agents at construction time; essential for safe dynamic agent registration | None — additive change | 30 min |
| 9 | Delete `_on_guardrail_violation` and `_audit_payload` no-op hooks from `BaseAIAgent` | Removes forward-looking stubs that conflict with Guardrails AI's design; avoids name collision | Low — confirm no subclass override | 15 min |
| 10 | Move `prompt_version` from class attribute to instance attribute in `BaseAIAgent` | Prerequisite for DSPy A/B testing multiple prompt versions without service restart | Low — backward-compatible if defaulted from class constant | 1 hour |

---

*Audit date: 2026-05-23*
*Auditor: codebase-mapper (concerns focus)*
*Scope: `services/`, `src/`, `src/core/`, `src/intelligence/`, `src/config/`*
