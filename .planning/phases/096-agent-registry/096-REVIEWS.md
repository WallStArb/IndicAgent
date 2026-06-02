---
phase: 096
reviewers: [gemini, codex]
reviewed_at: 2026-06-02T00:00:00Z
plans_reviewed: [096-01-PLAN.md, 096-02-PLAN.md, 096-03-PLAN.md]
---

# Cross-AI Plan Review — Phase 096

## Gemini Review

### Summary

The plan provides a robust, well-architected approach to decoupling agent construction from swarm logic. By leveraging `__init_subclass__` for self-registration and introducing `SwarmDeps` for dependency injection, the design effectively adheres to the Ring 0/Ring 1 boundary constraints. The migration strategy is structured in logical waves, minimizing disruption while ensuring the `AgentRegistry` becomes the authoritative constructor. The overall design successfully addresses the requirements for "fail-fast" YAML validation and strict DB-based production promotion.

### Strengths

- **Boundary Integrity:** Strict use of `TYPE_CHECKING` and lazy imports effectively preserves the Ring 0/Ring 1 isolation.
- **Fail-Fast Design:** The plan explicitly calls for validation before `_run()` and forbids unauthorized `shadow_only: false` overrides in YAML.
- **Template Method Pattern:** Utilizing `AgentRegistry.build` within the swarm lifecycle ensures consistent behavior across different coordinator types.
- **Dependency Injection:** Moving from loose kwargs to `SwarmDeps` simplifies constructor signatures and improves type safety.
- **Migration Safety:** The waves-based approach allows for verification at each stage, particularly crucial for the constructor signature changes in Plan 02.

### Concerns

- **MEDIUM:** While Python module-level imports are thread-safe, ensure that `AgentRegistry.build` and `_REGISTRY` registration are handled safely if swarm coordinators are ever instantiated in parallel.
- **MEDIUM:** The plan notes keeping `MLEvaluator` imports in `AlphaSwarm` for `isinstance` checks. Ensure that the registry logic doesn't inadvertently trigger instantiation of heavy objects if not required for the specific swarm.
- **LOW:** D-05 states `is_shadow=TRUE` in DB is authoritative. Ensure `BaseSwarmCoordinator` explicitly merges the class default (`shadow_only=False`) with DB state, so the agent doesn't enter an inconsistent state.
- **LOW:** The manual `AGENT_MODULES` list is a potential source of drift. As new agents are added, developers must remember to update this file.

### Suggestions

- Add a test case that verifies `AgentRegistry` contains exactly the expected set of agents after `_import_all()` is called.
- Ensure `RegistryConfigError` includes the `agent_id` that caused failure and if possible the source file location.
- Consider using `typing.Protocol` for `SwarmDeps` components to further decouple Ring 0 from specific implementations.
- Explicitly verify in `AgentRegistry.build` that an empty list for a group (e.g. `risk: []`) is treated as valid and inert rather than a misconfiguration.

### Risk Assessment

**LOW.** The plan is highly disciplined. The most significant risk — breaking the constructors of six existing agents — is mitigated by the wave-based approach and unit test coverage. The strict enforcement of DB-authority over YAML effectively neutralizes shadow-mode promotion risks.

---

## Codex Review

### Summary

The plans are directionally solid and mostly satisfy the registry phase goals: explicit module registration, YAML-driven startup construction, fail-closed YAML semantics for `shadow_only`, and a `SwarmDeps` boundary are good choices. The main risks are around runtime authority of `shadow_registry`, migration completeness, and setup ordering. In particular, `NarrativeSynthesizer.shadow_only = False` is not safe unless startup reads DB state and applies it to the instance before any compute. Also, constructor migration is broader than Plan 02 states because `NarrativeSynthesizer` is instantiated in `src/api/routes/narrative.py` as well as the swarm.

### Plan 01: SwarmDeps + Registry Core

**Strengths**

- Uses explicit `AGENT_MODULES` registration instead of filesystem scanning — safer and easier to audit.
- `yaml.safe_load` plus Pydantic `extra="forbid"` is the right security and correctness posture.
- Rejecting `shadow_only: false` in YAML directly supports the "YAML cannot promote" rule.
- Keeping `SwarmDeps` in Ring 0 with `TYPE_CHECKING` imports avoids runtime Ring 0 -> Ring 1 coupling.

**Concerns**

- **HIGH:** `AgentRegistry.build(group, deps)` should validate that each resolved class actually belongs to the requested `group`. Otherwise `narrative_v1` could appear under `alpha:` and be constructed.
- **HIGH:** Duplicate `agent_id`s inside a YAML group are not called out. That could instantiate the same agent twice.
- **MEDIUM:** If `alpha:` is accidentally empty or missing, the service may start with zero agents. Empty active groups should not be silently treated as inert.
- **MEDIUM:** The registry should distinguish config errors clearly: missing YAML file, malformed YAML, missing group, non-list group, missing `agent_id`, unknown `agent_id`.
- **MEDIUM:** Tests using temporary subclasses need careful cleanup and unique IDs due to the global `_REGISTRY`.
- **LOW:** Module-level `_REGISTRY` is mutable global state. Parallel test class creation or dynamic plugins could race.

**Suggestions**

- Add validation for: duplicate YAML `agent_id`s per group; class `group` matching requested group; group value must be a list; non-empty active groups.
- Consider `MappingProxyType` or accessor to avoid external mutation of `_REGISTRY`.
- Make `_load_specs` path resolution deterministic from repo root, not CWD.
- Include known IDs grouped by `class.group` in unknown-agent errors.

**Risk Assessment: MEDIUM.** Good design, but missing group/class validation could produce incorrect runtime behavior.

### Plan 02: Migrate All Six Agent Constructors

**Strengths**

- `SwarmDeps` is a cleaner construction contract than loose kwargs.
- Keyword-only `deps` makes registry construction uniform.
- Keeping `deps` optional at `BaseAIWorker` level reduces test friction.

**Concerns**

- **HIGH:** Migration scope is incomplete. Direct constructor call sites include `src/api/routes/narrative.py` in addition to the swarm services.
- **HIGH:** `tests/unit/api/test_narrative_route.py` likely also needs updates.
- **MEDIUM:** The plan says "4 unit test files," but `tests/unit/core/test_core_ai_base_agent.py` and API route tests may also be affected.
- **MEDIUM:** If `deps` is optional but concrete agents require `deps.llm_chain` or `deps.pool`, constructors should fail with a descriptive error when required dep is missing.
- **LOW:** `SwarmDeps(settings=None)` in tests conflicts with the proposed non-optional `settings: "Settings"` type.

**Suggestions**

- Run a full constructor call-site search before implementation: `rg "(SkepticEvaluator|CorrelationAnalyzer|RegimeCoherenceAnalyzer|CounterfactualEvaluator|MLEvaluator|NarrativeSynthesizer)\\("`.
- Either update the API narrative route to use `SwarmDeps`, or explicitly preserve backwards compatibility for `NarrativeSynthesizer(llm_chain=...)`.
- Add constructor guards: LLM agents require `deps.llm_chain is not None`; `MLEvaluator` requires `deps.pool is not None`.
- Consider `settings: Settings | None` in `SwarmDeps` to match test reality.

**Risk Assessment: MEDIUM-HIGH.** The change is mechanical but broad. The missed API route constructor makes breakage likely.

### Plan 03: Wire Registry End-to-End

**Strengths**

- Moving construction into `BaseSwarmCoordinator._setup()` is the right architectural direction.
- Building before the lineage loop fixes the issue where base setup assigns lineage before subclass agents exist.
- Explicit `register_agents.py` is aligned with D-01 and avoids import-by-string from YAML.
- Removing hardcoded startup construction directly supports AGENT-REG-02.

**Concerns**

- **HIGH:** `shadow_registry` is not actually authoritative unless DB state is read and applied to agent instances before compute. `_shadow_registry_ensure_agents()` only inserts missing rows; it does not update `agent.shadow_only`.
- **HIGH:** `NarrativeSynthesizer.shadow_only = False` is unsafe unless DB overlay happens immediately after enrollment — narrative outputs can be production in memory while DB says shadow.
- **HIGH:** The API route still constructs `NarrativeSynthesizer` outside the registry. If AGENT-REG-02 means all construction, the API route violates it.
- **MEDIUM:** Registry validation/build currently happens after Kafka/DB/LLM setup — it is before `_run()`, but not truly early preflight.
- **MEDIUM:** `NarrativeSwarm` may still need `NarrativeSynthesizer` for `_NARRATIVE_TFS` unless that gate moves to instance or shared constant.
- **MEDIUM:** `AgentRegistry.build()` should be followed by DB shadow-state overlay before config propagation or compute.
- **LOW:** `isinstance(MLEvaluator)` in AlphaSwarm still carries a hardcoded agent import.

**Suggestions**

- Add a base method after enrollment: fetch `shadow_registry` rows; set `agent.shadow_only = row.is_shadow`; fail closed if row missing.
- Do registry preflight before external I/O: import agents → load YAML → validate → then start Kafka/DB/LLM.
- Add tests proving `shadow_only: false` in YAML fails and that class default `False` is overridden by DB `is_shadow=TRUE`.
- Update `NarrativeSwarm` to hard-fail if not exactly one narrative agent exists after base setup.

**Risk Assessment: HIGH.** Biggest correctness gap: DB authority is asserted in design but not enforced on runtime instances.

---

## Consensus Summary

### Agreed Strengths

- **Ring 0/Ring 1 boundary** — Both reviewers agree that `TYPE_CHECKING` guards and lazy imports correctly preserve Ring 0 isolation. No runtime domain imports in `src/core/ai/`.
- **Fail-fast YAML semantics** — `extra="forbid"` + `shadow_only: false` rejection is solid and both reviewers praise it.
- **Wave-based migration strategy** — Wave ordering (foundation → constructors → wiring) is logically sound and allows per-wave verification.
- **Template method pattern** — Moving `AgentRegistry.build` into `BaseSwarmCoordinator._setup()` is the right architectural direction.

### Agreed Concerns (Highest Priority)

1. **DB shadow authority is stated but not enforced** (Codex: HIGH, Gemini: LOW) — `_shadow_registry_ensure_agents()` inserts rows but does NOT read back DB `is_shadow` and apply it to agent instances. `NarrativeSynthesizer.shadow_only = False` (class default) will be the runtime value unless a DB overlay step is added after enrollment. **This is the most important gap to address before execution.**

2. **Constructor migration scope is incomplete** (Codex: HIGH, Gemini: implicit) — `src/api/routes/narrative.py` constructs `NarrativeSynthesizer(llm_chain=...)` directly. Plan 02 doesn't include this file. Either migrate it or explicitly document the exception to AGENT-REG-02.

3. **No duplicate YAML agent_id validation** (Codex: HIGH) — Two entries with the same `agent_id` in the same group would instantiate the agent twice. `_load_specs` should deduplicate or error.

4. **No class.group / YAML group cross-check** (Codex: HIGH) — An agent registered under the wrong YAML group will be built and could cause subtle runtime issues. `AgentRegistry.build` should validate that `cls.group == requested_group`.

### Divergent Views

- **Overall risk level** — Gemini rates Phase 096 LOW risk; Codex rates Plan 03 HIGH risk. The divergence is explained by Codex's focus on the DB shadow enforcement gap (which Gemini noted as LOW). Since the Narrative agent has `shadow_only=False` as its class default and the DB overlay is missing, Codex's concern is well-founded and should be treated as the higher-confidence signal (memory note: weight Codex findings over Gemini when they diverge on correctness issues).

- **Empty group handling** — Gemini wants explicit inert-group testing; Codex distinguishes between empty scaffolded groups (risk: []) vs accidentally empty active groups (alpha:). Both are valid — the fix is to test both cases.

---

*To incorporate this feedback: `/gsd-plan-phase 096 --reviews`*
