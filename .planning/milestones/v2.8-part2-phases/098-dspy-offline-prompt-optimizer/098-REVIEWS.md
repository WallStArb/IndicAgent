---
phase: 98
reviewers: [gemini, codex]
reviewed_at: 2026-06-03T00:00:00Z
plans_reviewed:
  - 098-01-PLAN.md
  - 098-02-PLAN.md
  - 098-03-PLAN.md
  - 098-04-PLAN.md
  - 098-05-PLAN.md
---

# Cross-AI Plan Review — Phase 098

## Gemini Review

### Phase 098 Plan Review

#### 1. Summary

The plan set is well-structured, adheres to core IndicAgent invariants (DB-ignorant pipeline, batch-job ML services), and provides a clear, incremental path for deploying DSPy optimization. The design correctly isolates the optimization path from inference, uses a robust A/B testing mechanism via status flags, and respects the batch processing mandate. The dependencies between plans are logical, and the deferral of Plan 05 is a prudent architectural guardrail.

#### 2. Strengths

- **Architecture Alignment:** Strict adherence to the `BaseDaemon` batch-pattern and keeping DB operations inside dedicated `Writer/Auditor` or `Optimizer` logic preserves the `IntelligencePipeline` integrity.
- **Safety & Gatekeeping:** The `COUNT(*) >= 500` and regime balance checks are vital for preventing noise-driven prompt changes.
- **Versioning Strategy:** The `prompt_versions` table schema and the status-based routing (candidate -> active -> retired) enable safe, verifiable A/B testing and rollbacks.
- **Operational Clarity:** The explicit use of `_path_bootstrap` and systemd `Type=oneshot` ensures consistency with existing services like `ml_training_agent`.

#### 3. Concerns

- **MEDIUM — Metric Definition:** In Plan 02, the `parse_success_metric` evaluates the *predicted* output. While this is standard for DSPy, ensure the metric function is strictly deterministic and doesn't implicitly rely on the ground-truth outcome of the training set. If the optimizer optimizes for parsing but not for *intelligence quality* (e.g., faithfulness to market data), the models might become more concise but less accurate.
- **MEDIUM — DSPy Serialization:** Serializing complex `dspy.Predict` objects into `JSONB` via `compiled.save()` can be brittle if the underlying DSPy version updates or if the signature structure changes significantly. Ensure `compiled.load()` is tested for cross-version compatibility or that the migration/load logic gracefully handles `JSONB` corruption/mismatch.
- **LOW — Regime Data Integrity:** Plan 04 requires regime balance. If the `llm_calls` table doesn't have an indexed, reliable `regime` column, the query in `_fetch_ab_stats` could become slow as the dataset grows. Verify the `llm_calls` table indexing supports these filter operations efficiently.

#### 4. Suggestions

- **Validation Loop:** Enhance Plan 02's `parse_success_metric` to include a lightweight "sanity check" that ensures the `Predict` output contains the required keys for the `IntelligenceEvent`. A model that parses *successfully* into an empty dict shouldn't be promoted.
- **Auditability:** In Plan 04, ensure the `logs/dspy_optimizer_report_{date}.json` includes the specific `n` counts for each regime, not just the final result. This facilitates manual debugging when promotions fail to trigger.
- **Constraint Enforcement:** Explicitly mandate that the `prompt_versions.compiled_prompt` must be validated against a schema before being set to `status='active'`.

#### 5. Risk Assessment

**Risk Level: LOW**

**Justification:** The plans are heavily constrained by existing system invariants and rely on established patterns (batch training, idempotent migrations, systemd-timer management). The most significant risk — inference-time degradation — is mitigated by the 7-day A/B window and strict promotion criteria. The deferred reliance on Phase 096 is handled appropriately.

---

## Codex Review

### Summary

The phase direction is sound, but the current plan set has two major design gaps: `BootstrapFewShot` optimizes few-shot demonstrations, not prompt instructions, and the stored DSPy compiled program is not clearly consumable by the existing live agents. DSPy's docs show `dspy.Predict`, `BootstrapFewShot.compile(...)`, and `program.save(...)` are valid APIs, but they also distinguish demo bootstrapping from instruction optimization, which is handled by optimizers like MIPRO/GEPA. With D-01 locked to `BootstrapFewShot`, this phase can produce compiled demo-augmented DSPy programs, not rewritten prompt templates. The plans also under-specify how `parse_success` becomes a meaningful DSPy metric and how A/B routing happens before Phase 096 startup injection exists.

---

### Plan 01 — Migration + DSPy Pin

#### Strengths

- Table shape matches locked D-05 closely.
- `CREATE TABLE IF NOT EXISTS` and `CREATE INDEX IF NOT EXISTS` are appropriate for migration re-runs.
- `dspy` package name is correct for current DSPy installs.

#### Concerns

- **MEDIUM:** `version_tag TEXT UNIQUE` is globally unique, but promotion and lookup are per-agent. That is acceptable, but it makes collisions more painful than needed. A safer schema is unique `(agent_id, version_tag)`.
- **MEDIUM:** No constraint prevents more than one `active` version per `agent_id`. Plan 04 retires prior active rows transactionally, but direct/manual flips could violate D-06 routing assumptions.
- **LOW:** `created_at DEFAULT NOW()` is Postgres-side local semantics. It stores `TIMESTAMPTZ`, but the project invariant prefers explicit UTC timestamps in application code where possible.
- **LOW:** `compiled_prompt JSONB NOT NULL` may be a poor name if the value is actually a serialized DSPy program state with demos, not a prompt.

#### Suggestions

- Add a partial unique index: `CREATE UNIQUE INDEX ... ON prompt_versions(agent_id) WHERE status = 'active'`.
- Consider `UNIQUE (agent_id, version_tag)` unless global tags are intentionally desired.
- Rename or document `compiled_prompt` as "DSPy compiled program JSON/state" to avoid confusing it with a plain prompt template.

#### Risk Assessment

**LOW to MEDIUM.** The migration is mostly solid, but missing active-version uniqueness can create ambiguous startup behavior.

---

### Plan 02 — DSPyOptimizer Core Class

#### Strengths

- Per-agent isolation is correct and matches D-03.
- Data gate uses `outcome IS NOT NULL` with a 500-row threshold, matching D-07.
- 90-day bounded reads and limit 2000 are reasonable for batch cost control.
- `dspy.Predict(signature_cls)`, `BootstrapFewShot(...).compile(student, trainset=...)`, and `.save(path)` align with DSPy docs.

#### Concerns

- **HIGH:** `BootstrapFewShot` does not rewrite prompt instructions. DSPy docs describe it as synthesizing/selecting few-shot examples; instruction proposal is associated with MIPRO/GEPA. With D-01 locked, success criteria should say "compile few-shot variants," not "optimized prompts," unless the live path will execute DSPy programs.
- **HIGH:** The metric is underspecified and likely wrong. A metric that only evaluates the predicted output for parseability does not optimize against historical `parse_success`; it just rewards any schema-valid output. The trainset examples need labels or validation targets that make failed vs successful parsing meaningful.
- **HIGH:** The plan says import each agent's `PROMPT_REGISTRY` and use `ACTIVE_VERSION` as the Signature base, but the tasks only define new Signature classes. Existing prompt text is not actually embedded into the DSPy program unless explicitly added as the Signature docstring/instructions or as data.
- **HIGH:** `AGENT_SIGNATURES` uses `skeptic_v2`, but the local agent ID is `skeptic` while its prompt version is `skeptic_v2`. Queries using `agent_id = 'skeptic_v2'` will miss rows.
- **MEDIUM:** A `BaseDaemon` subclass doing direct asyncpg reads/writes may violate the stated DB-operation invariant unless this batch optimizer is explicitly classified as an allowed DB batch service or implemented through a `BaseAuditor`/writer-style boundary.
- **MEDIUM:** `version_tag = f"...{datetime.now(UTC)}..."` calls `datetime.now(UTC)` twice; it can cross an hour boundary. Use one timestamp variable.
- **MEDIUM:** `ON CONFLICT DO NOTHING` needs a defined return path. If the insert conflicts, `_store_candidate` cannot pretend it stored a new candidate.
- **MEDIUM:** No mention of `dspy.configure(lm=...)` or passing LM settings around. Creating `dspy.LM(...)` alone is not enough unless the compiled module receives/configures it.
- **LOW:** `dspy.LM(model=f"ollama_chat/{settings.ollama_model}", ...)` should be verified in CI with the pinned DSPy version because LiteLLM/Ollama provider names can shift.

#### Suggestions

- Reframe D-01 output as "compiled few-shot DSPy program state," or adjust success criteria since D-01 is locked.
- Build trainset examples with expected parsed fields and/or an explicit `parse_success` label, then define a deterministic metric that compares `pred` against expected schema.
- Map optimizer keys separately: `agent_id` for `llm_calls` queries and `prompt_version`/`ACTIVE_VERSION` for prompt registry lookup.
- Add a small spike/test that compiles one local signature, saves JSON, loads it back, and proves the stored object can be executed or transformed into live-agent prompt material.
- Use one captured timestamp for version tags and include minutes/seconds or a UUID suffix.

#### Risk Assessment

**HIGH.** This is the highest-risk plan. The DSPy API usage is broadly recognizable, but the optimization objective and downstream consumability are not yet coherent.

---

### Plan 03 — Oneshot Entrypoint + Systemd

#### Strengths

- Timer-triggered `Type=oneshot` is aligned with OPT-03 and the project invariant that batch jobs are inactive between runs.
- `_path_bootstrap` first import matches local entrypoint patterns.
- Metrics flush in `finally` follows existing batch job patterns.

#### Concerns

- **MEDIUM:** "Monday 02:00 ET" is not always 07:00 UTC. During daylight saving time (which applies in June 2026), 02:00 ET is 06:00 UTC, not 07:00 UTC.
- **MEDIUM:** `skipped_data_gate` emitted inside `DSPyOptimizer._run()` plus `success` emitted by `main()` can double-count job completion statuses unless the metric model expects both.
- **MEDIUM:** Registering only `_DAG_ORDER` may be incomplete; timer-triggered services may also belong in `_ONESHOT_UNITS` to prevent inactive state from being treated as failures.
- **LOW:** The plan references D-06 for counters, but D-06 is the prompt loading decision; D-11 is the counter requirement.

#### Suggestions

- Use `OnCalendar=Mon *-*-* 02:00:00 America/New_York` if systemd version supports time zones, or fix UTC offset accounting for DST.
- Add `indicagent-dspy-optimizer` to `_ONESHOT_UNITS` per the service auditor pattern for oneshots.
- Make job completion status single-source: either `main()` emits terminal status after optimizer returns a status enum, or optimizer emits all terminal statuses and `main()` only flushes.

#### Risk Assessment

**MEDIUM.** The entrypoint shape is right, but scheduler semantics and service auditor registration need tightening.

---

### Plan 04 — A/B Promotion Runner + Unit Tests

#### Strengths

- Promotion separated into pure decision logic plus transactional DB mutation — correct for unit-testability.
- The regime guard correctly uses stored regime strings `'0'`, `'1'`, `'2'`.
- Running promotion even when compile is data-gated is a good catch.
- Unit tests focus on core promotion boundary cases.

#### Concerns

- **HIGH:** There is no A/B assignment/routing plan before Plan 05, and Plan 05 is deferred. Without live traffic assigned to candidate `prompt_version`, `_fetch_ab_stats` will have no candidate calls. Promotion can never trigger.
- **HIGH:** Auto-promotion based only on `parse_success` can promote prompts that parse better but degrade signal quality. This matches D-02/D-09, but conflicts with the success criterion asking for win-rate and calibrated-confidence deltas before promotion.
- **MEDIUM:** Candidate and baseline comparison may be biased if traffic assignment is not balanced by agent/regime/time.
- **MEDIUM:** `baseline_tag` may be absent if no active version exists. The plan needs a fallback to file `ACTIVE_VERSION` rows or a seeded active baseline.
- **MEDIUM:** Strict boundary "parse delta > 0.02" should be documented as intentional; reviewers may expect `>=`.
- **LOW:** Atomic report writing should specify same-filesystem temp file plus `os.replace`.

#### Suggestions

- Add a prerequisite: seed an `active` baseline row for each agent, and document that no candidate evaluation is possible until routing traffic exists.
- Report parse delta, win-rate delta, and calibrated-confidence delta in the report file for observability, even if promotion gates only on D-09 parse criteria.
- Add tests for missing baseline, missing candidate stats, exactly-one-regime-short, and transaction rollback.
- Include `called_at >= window_start`, `agent_id`, `prompt_version IN (...)`, and `outcome IS NOT NULL` explicitly in stats queries.

#### Risk Assessment

**MEDIUM to HIGH.** The promotion mechanics are reasonable, but A/B data generation is missing until deferred live-path work lands.

---

### Plan 05 — Startup Prompt Injection

#### Strengths

- Correctly deferred on Phase 096 — `AgentDependencies` does not exist yet.
- Startup-only DB load respects D-06 and avoids DB reads in live inference calls.
- Active-absent fallback behavior is appropriate.
- Mock-pool tests are the right level for this integration.

#### Concerns

- **HIGH:** Existing agents build string prompts and call `_llm_generate`; a DSPy compiled JSON program cannot be injected as a plain replacement prompt without a defined adapter. The live-consumption contract is unspecified.
- **HIGH:** The plan names `BaseGroupCoordinator._setup()` in some places but `BaseSwarmCoordinator` in others. Naming is inconsistent throughout.
- **MEDIUM:** Loading per `AGENT_SIGNATURES` entry can miss agents if the map uses prompt-version keys rather than actual agent IDs.
- **LOW:** A single `WHERE status='active' AND agent_id = ANY($1)` query would be simpler than one query per agent.

#### Suggestions

- Define the live-consumption contract before implementation: either agents execute loaded DSPy modules, or compiled demos/instructions are converted into a prompt template format the current agents can render.
- Use consistent naming throughout: `BaseSwarmCoordinator`.
- Add tests proving the injected candidate changes the actual `prompt_version` emitted into `llm_calls`.

#### Risk Assessment

**HIGH while deferred.** Deferral is correct, but the consumption adapter is not yet designed.

---

## Ollama Review

*Ollama (qwen3.5:4b) returned empty output — review omitted.*

---

## Consensus Summary

### Agreed Strengths

1. **Per-agent independence** — Both reviewers confirm D-03 per-agent isolation is correctly designed; one ineligible agent never blocks others.
2. **Status-based routing** — `candidate → active → retired` table schema is well-liked; enables safe A/B and rollback.
3. **Batch job pattern alignment** — `Type=oneshot`, `_path_bootstrap` first, `JOB_COMPLETED_TOTAL` flush in `finally` all match existing `ml_training_agent.py` conventions.
4. **Plan 05 deferral** — Both reviewers agree the explicit gate on Phase 096 is prudent; attempting Plan 05 without `AgentDependencies` would fail at import time.
5. **Promotion as pure function** — `_promotion_decision` with no I/O, unit-testable, separated from transactional mutation is correct design.

### Agreed Concerns

1. **`parse_success_metric` is underspecified (HIGH/MEDIUM)** — Both reviewers flag that the metric function as described rewards any parseable output, not historical parse failures. The trainset needs labels/expected fields to make the metric meaningful for `BootstrapFewShot`.
2. **DSPy serialization / consumption gap** — Both reviewers note that what is stored in `compiled_prompt JSONB` is a DSPy program state (few-shot demos), not a prompt string. How the live inference agents consume this is not specified. The adapter is missing.
3. **Missing active baseline row** — Both note that if no `active` prompt_version row exists for an agent, `_fetch_active_version_tag` returns None and the A/B baseline is undefined. A seed or fallback strategy is needed.
4. **MEDIUM agent_id key confusion (Codex HIGH)** — `AGENT_SIGNATURES` uses prompt-version strings like `skeptic_v2` as keys, but `llm_calls.agent_id` stores the actual class-level `agent_id` (e.g., `skeptic`). Querying with the wrong key will silently return 0 rows and bypass the data gate.

### Divergent Views

1. **Overall risk level** — Gemini rates the phase LOW risk overall; Codex rates it HIGH. Gemini takes the architectural invariants at face value; Codex digs into DSPy API semantics and the agent_id mapping gap. Codex's concerns are better grounded: the agent_id mismatch and consumption adapter gap are genuine implementation blockers, not style issues.
2. **BootstrapFewShot framing** — Codex explicitly flags that BootstrapFewShot produces few-shot demos, not rewritten instructions, and says the success criteria language should reflect this. Gemini accepts the framing without challenge. Codex is correct on the DSPy semantics.
3. **DST handling for the Monday timer** — Codex flags that June 2026 is EDT (UTC-4), making 02:00 ET = 06:00 UTC, not 07:00 UTC. Gemini does not flag this. Codex is correct.
4. **active-version uniqueness** — Codex recommends a partial unique index `ON prompt_versions(agent_id) WHERE status = 'active'` to prevent multiple active rows per agent. Gemini does not flag this. Worth adding.

### Top 3 Shared Concerns for Planning Action

1. **Specify the `parse_success_metric` precisely** — The metric must evaluate whether the predicted output matches the expected parsed schema for that agent (not just "is it JSON"). Build trainset examples with ground-truth expected fields; define the metric as: does `pred.coherence_score` exist and is it a float in [0,1]? etc. This is the core of what BootstrapFewShot optimizes.
2. **Clarify the agent_id key** — `AGENT_SIGNATURES` keys must match the `agent_id` column in `llm_calls` exactly. If `llm_calls` stores `skeptic` (class-level attribute), the registry must use `skeptic` not `skeptic_v2`. Verify each mapping before Plan 02 execution.
3. **Define the live-consumption adapter before Plan 05** — Either: (a) at inference time, agents load their `compiled_prompt` JSON via `program.load()` and execute `dspy.Predict`, or (b) the compiled few-shot demos are extracted from the JSON and injected as few-shot examples into the existing PROMPT_REGISTRY template. This contract must be settled before Plan 05 is unblocked.
