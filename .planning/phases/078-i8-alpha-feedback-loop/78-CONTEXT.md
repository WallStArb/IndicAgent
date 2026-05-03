# Phase 78: I8 Alpha Feedback Loop - Context

**Gathered:** 2026-04-30
**Status:** Ready for replanning — existing 7 plans need updates per decisions below

<domain>
## Phase Boundary

Phase 78 closes the I8 feedback loop so AI agents produce **statistically validated alpha**, not LLM theater. It delivers:

1. **Bug fixes** — pool leak, segment key, volume-profile stub, lead instrument map
2. **Dead code removal** — SafeAgentWrapper, NarrativeGroupComputeAgent._setup() override, ShadowRecorder, TransformRecorder (superseded by LineageRecorder)
3. **Phase 73 lineage migration completion** — swarm migrates from dual-write (ShadowRecorder + TransformRecorder) to single LineageRecorder path. Retires alpha_multiplier_shadow and signal_transform_log as swarm write targets.
4. **AIContext architectural upgrade** — uses schemas.py types directly (zero drift, one source of truth)
5. **Graduation loop** — skeptic_v1 enrolled in shadow_registry; _graduation_loop evaluates Spearman on signal_lineage outcomes
6. **Brier score + calibration** — llm_model_scores gets proper probabilistic metrics
7. **Math plugin replacements** — VolumeZscorePlugin (I1), corr_z in CrossAssetComputeAgent replace CorrelationAgent + VolumeAgent (LLM)
8. **Narrative off hot path** — GET /api/signals/{signal_id}/narrative on-demand endpoint; Kafka consumer service retired
9. **Agent authoring codification** — CLAUDE.md + TEMPLATE_agent.py + AUTHORING.md

**Does NOT include:** Unified ShadowAuditorAgent for swarm+I7 (Phase 79+), FeatureValidationService (todo 008), Superset BI layer (todo 005), dashboard I3/I5/I6 field gaps (todo 003).

**Core principle guiding all decisions:** Design like Renaissance Technologies. Modularity, reuse, separation of concerns, microservices DAG alignment. No manual tasks — prefer automation. No dual-write debt. Balance efficiency with simplicity. Right foundation for future building, not one-off fixes.

</domain>

<decisions>
## Implementation Decisions

### Shadow Data Architecture (integrates todo 009)

- **D-01:** Complete Phase 73 lineage migration. Swarm writes via `LineageRecorder` → `topic_signal_lineage()` → `LineageWriterAgent` → `signal_lineage` hypertable. This is the ONLY write path for swarm AI predictions after Phase 78.
- **D-02:** `alpha_multiplier_shadow` table — swarm STOPS writing to it. Table kept for historical reads only (not dropped).
- **D-03:** `signal_transform_log` — swarm STOPS writing to it via TransformRecorder. Table kept for historical reads only (not dropped).
- **D-04:** `ShadowRecorder` (`src/core/ml/shadow.py`) — import removed from `services/alpha_swarm_agent.py`. Class archived (not deleted) to preserve historical reference. `TransformRecorder` (`src/core/ml/transform_recorder.py`) — same treatment.
- **D-05:** `shadow_registry` is the **graduation STATE table** for all component types — `i7_plugin` (Phase 75) and `swarm_agent` (Phase 78). `component_type` column discriminates. Same promotion/demotion state machine for both.
- **D-06:** `signal_lineage` is the **outcome/audit table** for swarm predictions. `_graduation_loop` queries `signal_lineage WHERE event_type = 'agent_prediction'` JOIN `signal_ledger` on `signal_id` for outcomes.
- **D-07:** Two auditors for Phase 78 — `ShadowAuditorAgent` handles `i7_plugin` rows; `AlphaSwarmComputeAgent._graduation_loop` handles `swarm_agent` rows. Schema (`shadow_registry`) is unified; unified auditor service is Phase 79+ work (deferred — different eval cadence and logic).
- **D-08:** `alpha_swarm_agent._setup()` creates ONE `LineageRecorder` (not ShadowRecorder + TransformRecorder). `LineageRecorder` is initialized with `self._producer` (already available) and `self.env_name`.

### AIContext Architecture (replaces Plan 05 approach)

- **D-09:** `AIContext` uses `src/intelligence/schemas.py` types **directly** for pipeline tiers. Import is permitted by D-36 (Phase 73). Zero schema drift — one source of truth.
- **D-10:** Replace sparse TierContext subclasses in `context.py` with schemas.py types:
  ```
  i1: I1Indicators | None = None      # 53 fields — was 3-field I1Context
  i2: I2Events | None = None          # 56 fields — was absent
  i3: I3Structure | None = None       # full struct — was absent
  i4: I4Context | None = None         # 112 fields — was 11-field I4Context
  i5: I5Patterns | None = None        # full struct — was absent
  i6: I6Confluence | None = None      # full struct — was 7-field I6Context
  ```
  Delete sparse subclasses `I1Context`, `I4Context`, `I6Context` from `context.py` entirely.
- **D-11:** `I7Context` stays **custom** in `context.py` — it holds signal-specific data (setup_plugin, regime_type, confidence, adjusted_rank) that is not a pipeline tier output.
- **D-12:** `BarContext` stays **custom** — OHLCV + source fields specific to the AIContext contract.
- **D-13:** `AIContextCache.build()` maps `event.i1` → `ctx.i1` directly. No field-by-field copy. All tier fields are null-safe (None if pipeline hasn't computed them); agents handle None gracefully — same convention as schemas.py.
- **D-14:** Add `Tier` enum values for `I2`, `I3`, `I5` (currently missing). Agents declare `tiers_needed = frozenset({Tier.I4, Tier.I5})` etc. to signal which tiers they consume.
- **D-15:** No `full_features: dict[str, Any]` escape hatch. If a field is needed, it is in the typed model. If the model is missing a field, the right fix is to add it to the schema — not bypass the type system.

### Skeptic Prompt v2

- **D-16:** `skeptic_v2` prompt renders the **full typed context** via `_render_full_context(ctx: AIContext) -> str`. Serializes all non-None fields across i1–i7 using model field names (same as pipeline). Registered in `PROMPT_REGISTRY` alongside v1.
- **D-17:** `ACTIVE_VERSION = "skeptic_v2"`. v1 preserved for A/B. Segment key includes prompt version for correct TransformRecorder/LineageRecorder attribution.

### Dead Code Removal

- **D-18:** `src/core/ai/safe_wrapper.py` deleted. `BaseAIAgent.compute()` already provides asyncio.wait_for + neutral fallback — no wrapper needed.
- **D-19:** `NarrativeGroupComputeAgent` does NOT override `_setup()`. Inherits `BaseGroupService._setup()` which handles empty `bar_topics` correctly.
- **D-20:** Correlation LLM agent (`correlation_agent.py`, `correlation_prompts.py`) deleted. Replaced by `corr_z` in `CrossAssetComputeAgent` (pure math, no LLM).
- **D-21:** Volume LLM agent (`volume_agent.py`, `volume_prompts.py`) deleted. Replaced by `VolumeZscorePlugin` in TIER_I1 (pure math, no LLM).
- **D-22:** After deletions, `AlphaSwarmComputeAgent._agents = [SkepticAgentComputeAgent]` only. No other swarm LLM agents.

### Graduation Loop

- **D-23:** `skeptic_v1` enrolled in `shadow_registry` as `component_type='swarm_agent'` at `_setup()` startup (idempotent: `INSERT ... ON CONFLICT DO NOTHING`).
- **D-24:** Promotion gates: N ≥ 100 resolved signals, Spearman ρ > 0, p < 0.05 (consistent with I7 statistical discipline — earn the right through proof).
- **D-25:** Demotion gates: 3 consecutive 15-min eval cycles with Spearman ρ < 0.
- **D-26:** Migration SQL (`078_alpha_swarm_shadow_enrollment.sql`) enrolls `skeptic_v1` in `shadow_registry` idempotently; does NOT enroll correlation_v1/volume_v1 (those agents are deleted by D-20/D-21).

### Calibration Metrics (Brier Score)

- **D-27:** `llm_model_scores` gains three nullable columns: `brier_score DOUBLE PRECISION`, `calibration_slope DOUBLE PRECISION`, `ece DOUBLE PRECISION` (Expected Calibration Error).
- **D-28:** `_recompute_scores` in `llm_writer_service` computes all three per group. Brier = mean squared error of `confidence` against realized win/loss outcome. Existing `win_rate`/`p_value`/`is_significant` columns preserved for backward compatibility.

### Narrative Offload

- **D-29:** `GET /api/signals/{signal_id}/narrative` — on-demand, synchronous, returns `{"narrative": str}`. 404 when signal_id not in signal_ledger.
- **D-30:** `indicagent-ai-narrative` removed from `_DAG_ORDER`, `_LAG_THRESHOLDS`, `_AGENT_ID_TO_UNIT` in `service_auditor_agent.py`. Systemd unit file removed from `production/systemd/`.
- **D-31:** `NarrativeComputeAgent` class survives at `src/intelligence/ai/narrative/narrative_agent.py` — only the Kafka consumer wrapper service is retired.

### Agent Authoring Codification

- **D-32:** Add `"Adding an AI Agent"` section to `CLAUDE.md` — 5-step pattern: class attributes, file location, tiers_needed, _compute() contract, prompt file convention.
- **D-33:** Add `src/intelligence/ai/TEMPLATE_agent.py` — commented skeleton enforcing all 5 required class attributes plus docstring explaining the contract.
- **D-34:** Add `src/intelligence/ai/AUTHORING.md` — full protocol document: what each group (alpha/narrative/risk) is for, how LineageRecorder is used, how shadow enrollment works, how to add a new group.

### Bug Fixes (from existing Plan 01 scope)

- **D-35:** Pool fix: `AlphaSwarmComputeAgent._setup()` must call `super()._setup()` ONLY — no second `asyncpg.create_pool`. One pool, from `BaseGroupService`.
- **D-36:** Segment key fix: `_record_swarm_result` builds key from hmm_regime + timeframe (numeric prefix: e.g., `"1.5m"`) — never `"unknown.*"`.
- **D-37:** Lead map fix: ES → NQ as lead instrument. `_LEAD_MAP: dict[str, str]` hardcoded in `alpha_swarm_agent.py`.
- **D-38:** `_extract_volume_profile()` is removed from the swarm service (replaced by VolumeZscorePlugin in TIER_I1 — Plan 06 work).

### Revised Plan Structure

The 7 existing plans absorb the upgraded scope without adding an 8th plan:
- **Plan 01** (was: bug fixes) → ADD LineageRecorder migration (D-01 through D-08, D-35 through D-38)
- **Plan 02** (was: SafeAgentWrapper + setup override) → ADD ShadowRecorder/TransformRecorder archive (D-04, D-18, D-19)
- **Plan 03** (graduation loop) → UPDATE: query signal_lineage not signal_transform_log (D-23 through D-26)
- **Plan 04** (Brier score) → unchanged (D-27, D-28)
- **Plan 05** (AIContext) → UPDATE: schemas.py types directly, no dict escape (D-09 through D-17) + authoring docs (D-32 through D-34)
- **Plan 06** (math plugins) → unchanged (D-20, D-21)
- **Plan 07** (narrative API) → unchanged (D-29 through D-31)

### Folded Todos

- **Todo 009 — Align shadow infrastructure across I7 plugins and swarm agents**: Folded into Phase 78. D-01 through D-08 complete the Phase 73 migration and unify the shadow write path. Notes: `signal["_shadow"]` rename was done in Phase 75 (now `features_snapshot`). `ShadowRecorder` is NOT dead code — it's active in swarm, migrated to LineageRecorder by this phase. `SHADOW_PLUGINS` in weight_updater.py and `is_shadow` in signal_ledger are I7-side concerns handled by ShadowAuditorAgent (Phase 75) — not in Phase 78 scope.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### AI Layer Architecture (Phase 73 decisions that remain locked)
- `.planning/phases/73-ai-llm-layer-b-architecture-refactor/73-CONTEXT.md` — D-01 through D-37 locked decisions from Phase 73. D-36 (import boundary), D-48 (LineageRecorder schema), D-18 through D-22 (new infrastructure). All still apply.

### Shadow Governance (Phase 75)
- `services/shadow_auditor_agent.py` — ShadowAuditorAgent: reads shadow_registry, runs statistical gates, writes transitions. Phase 78 swarm graduation must be consistent with this pattern.
- `src/intelligence/register_plugins.py` — `shadow_registry_ensure()` and `auto_enroll_all_plugins()` — the idempotent enrollment pattern Phase 78 swarm must follow.

### Signal Lineage Infrastructure
- `src/core/ai/lineage.py` — `LineageRecorder` class. Phase 78 Plan 01 migrates swarm to use this. Read the API before implementing.
- `services/lineage_writer_agent.py` — LineageWriterAgent. Already deployed; writes to `signal_lineage` table.
- `src/core/ml/shadow.py` — `ShadowRecorder` to be archived (not deleted). Read before touching.
- `src/core/ml/transform_recorder.py` — `TransformRecorder` to be archived. Read before touching.

### Schema Contracts
- `src/intelligence/schemas.py` — Canonical typed models: `I1Indicators`, `I2Events`, `I3Structure`, `I4Context`, `I5Patterns`, `I6Confluence`, `IntelligenceEvent`. Phase 78 Plan 05 uses these directly in AIContext.
- `src/core/ai/context.py` — Current AIContext: sparse TierContext subclasses to be deleted, replaced with schemas.py types.

### Plugin Registry
- `src/intelligence/register_plugins.py` — `TIER_I1` list. `VolumeZscorePlugin` must be registered here (Plan 06).

### Stream Keys
- `src/core/stream_keys.py` — `topic_signal_lineage()`, `topic_signal_lineage_dlq()`. Use these functions — never hardcode topic strings.

### Existing Agent as Canonical Example
- `src/intelligence/ai/alpha/skeptic_agent.py` — Reference implementation for new agents. `SkepticAgentComputeAgent` is the pattern all future agents follow.
- `src/intelligence/ai/alpha/skeptic_prompts.py` — Prompt registry pattern. `skeptic_v2` added here in Plan 05.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `LineageRecorder` (`src/core/ai/lineage.py`) — Kafka-first, batch-flush, Kafka producer injection. Phase 78 Plan 01 wires it into AlphaSwarmComputeAgent._setup(). Already fully implemented.
- `shadow_registry_ensure()` (`src/intelligence/register_plugins.py:620`) — Idempotent enrollment function. Phase 78 Plan 03 calls this for `skeptic_v1` with `component_type='swarm_agent'`.
- `BaseGroupService._setup()` (`src/core/ai/base_group_service.py`) — Creates one asyncpg pool. Plan 01 must call `super()._setup()` only — no second pool.
- `schemas.py` tier models — Fully typed, null-safe, Pydantic. Direct replacement for sparse TierContext subclasses.

### Established Patterns
- **Kafka-first writes**: LineageRecorder publishes to Kafka; LineageWriterAgent persists. Never write DB directly from hot path. Plan 01 must follow this.
- **Idempotent enrollment**: `INSERT ... ON CONFLICT DO NOTHING` pattern from `shadow_registry_ensure()`. Plans 03 and 01 follow this.
- **Component type discrimination**: `shadow_registry.component_type` (`i7_plugin` | `swarm_agent`) allows one table to serve multiple graduation contexts. Future component types (e.g., `risk_agent`) follow the same pattern.
- **Graduation via `bootstrap_ci_lower` (I7) vs Spearman (swarm)**: Different statistical tests per component type because I7 measures realized pnl_r (outcome), swarm measures prediction-vs-outcome correlation. Both use the SAME state table.
- **Segment key convention**: `{hmm_regime}.{timeframe}` — numeric regime prefix. `_record_swarm_result` must build keys this way.

### Integration Points
- **Plan 01 → Plan 03**: LineageRecorder migration (Plan 01) is prerequisite for graduation loop (Plan 03) because _graduation_loop queries signal_lineage which is populated by LineageWriterAgent consuming LineageRecorder output.
- **Plan 05 → Plan 03**: AIContext expansion (Plan 05) feeds skeptic_v2 prompt (Plan 05) which is consumed by graduation evaluation in Plan 03.
- **Plan 06 → Plan 01**: Correlation/Volume agent deletion (Plan 06) means _agents list in alpha_swarm is [SkepticAgentComputeAgent] only — Plan 01 must not rely on correlation_v1/volume_v1 existing.

</code_context>

<specifics>
## Specific References

- **Renaissance design principle** — every decision in this phase was made through the lens of: "What would Jim Simons demand?" Modularity, automation, no manual tasks, no dual-write debt, separation of concerns, statistical rigor (earn the right through proof).
- **No `dict[str, Any]` in critical paths** — AIContext must be fully typed. If a field is needed and missing from the typed model, add it to schemas.py — don't bypass the type system.
- **Compute cost awareness** — Replacing LLM Correlation + Volume agents with pure math (VolumeZscorePlugin, corr_z in CrossAssetComputeAgent) reduces LLM call volume while preserving the signal. Skeptic (judgment call) stays LLM; deterministic computations move to math plugins.
- **One audit trail** — signal_lineage is the immutable record. shadow_registry is the graduation state. These are two concerns; don't conflate them.

</specifics>

<deferred>
## Deferred Ideas

- **Unified ShadowAuditorAgent** — extend ShadowAuditorAgent to handle `component_type='swarm_agent'` rows. Deferred to Phase 79+. Schema is ready; different eval logic and cadence makes unification a separate scoped effort.
- **`risk` agent group** — `src/intelligence/ai/risk/__init__.py` placeholder exists. Population of the risk group with actual agents is future work.
- **FeatureValidationService** — todo 008. Automated IC/p-value gate superseding human-verify checkpoint. Out of Phase 78 scope.
- **Todo 003** — Dashboard I3/I5/I6 field gaps. UI work, separate concern.
- **Todo 005** — Apache Superset BI analytics layer. Infrastructure, separate concern.
- **Todo 006** — Re-run validate_alpha for DerivOsc/AC Osc. Data-gated (~May 10), separate concern.
- **Todo 007** — Extract swarm shared utilities. Triggered on 4th+ agent. Deferred until then.

</deferred>

---

*Phase: 78-I8 Alpha Feedback Loop*
*Context gathered: 2026-04-30*
