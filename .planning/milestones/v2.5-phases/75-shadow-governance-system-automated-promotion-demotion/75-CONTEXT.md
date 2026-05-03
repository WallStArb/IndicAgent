# Phase 75: Shadow Governance System — Context

**Gathered:** 2026-04-28
**Status:** Ready for planning
**Source:** PRD Express Path (docs/plans/2026-04-28-shadow-governance-design.md)

<domain>
## Phase Boundary

Replace three conflated "shadow" concepts with a clean, automated self-governing system. Deliver automated promotion and demotion of I7 plugins and swarm agents based on statistical gates, with DB as single source of truth, unified enrollment protocol, and renamed ML capture key.

This phase does NOT change signal routing logic, confidence computation, or any live trading behavior. It is purely a governance and naming cleanup phase.

</domain>

<decisions>
## Implementation Decisions

### D-01: Opt-out enrollment (not opt-in)
All TIER_I7 plugins and SwarmBaseAgent subclasses auto-enroll in shadow evaluation at pipeline startup unless they declare `SHADOW_SKIP: ClassVar[bool] = True`. Absence of any flag = enrolled. Rationale: "earn the right through proof" — a new plugin that omits a flag should never go live unproven by omission.

### D-02: shadow_registry as DB source of truth
New `shadow_registry` table holds: `component_name (PK)`, `component_type` (i7_plugin | swarm_agent), `is_shadow BOOLEAN DEFAULT TRUE`, `enrolled_at`, `promoted_at`, `demoted_at`, per-component gate params (`min_n INTEGER DEFAULT 100`, `min_ev_r FLOAT DEFAULT 0.0`, `ci_alpha FLOAT DEFAULT 0.05`, `demotion_lookback_days INTEGER DEFAULT 30`, `demotion_threshold_ev_r FLOAT DEFAULT -0.05`, `demotion_min_evaluations INTEGER DEFAULT 3`), `demotion_consecutive_count INTEGER DEFAULT 0`, and last-eval stats (`last_eval_n`, `last_eval_ev_r`, `last_eval_ci_lower`, `last_eval_win_rate`, `last_eval_at`).

### D-03: shadow_transition_log as immutable audit trail
New `shadow_transition_log` table: `id BIGSERIAL PK`, `component_name`, `component_type`, `from_state` (shadow|live), `to_state` (shadow|live), `triggered_at`, `trigger_reason` (promotion_gate_cleared | demotion_ev_r_degraded), `n`, `ev_r`, `ci_lower`, `win_rate`. Append-only. Index on `(component_name, triggered_at DESC)`.

### D-04: ShadowAuditorAgent timer pattern
New `services/shadow_auditor_agent.py` following the existing `indicagent-ml-data-quality` timer pattern (not a streaming agent). Systemd units: `indicagent-shadow-auditor.service` + `indicagent-shadow-auditor.timer`. Runs every 30 minutes. Reads shadow_registry + signal_ledger, makes promotion/demotion decisions, writes shadow_registry + shadow_transition_log, publishes ShadowTransitionEvent to Kafka.

### D-05: Promotion gate per component
For components with `is_shadow = TRUE`: query signal_ledger WHERE `setup_plugin = component_name AND outcome IS NOT NULL AND outcome NOT IN ('never_activated', 'ttl_expired_behind')`. Promote when: `n >= min_n` AND `bootstrap_ci_lower(pnl_r_values, ci_alpha) > min_ev_r`. On promotion: set `is_shadow = FALSE`, `promoted_at = NOW()`, reset `demotion_consecutive_count = 0`, log to `shadow_transition_log`, publish event.

### D-06: Demotion gate with consecutive-count guard
For components with `is_shadow = FALSE`: compute rolling EV[R] over last `demotion_lookback_days` days. If rolling EV[R] < `demotion_threshold_ev_r`: increment `demotion_consecutive_count`. If count reaches `demotion_min_evaluations`: demote (set `is_shadow = TRUE`, `demoted_at = NOW()`, reset counter), log to `shadow_transition_log`, publish event. If rolling EV[R] passes: reset `demotion_consecutive_count = 0`. Prevents noise-driven demotions from a single bad evaluation.

### D-07: bootstrap_ci_lower in src/core/stats_utils.py
Extract `_bootstrap_ci_lower()` from `weight_updater.py` to new `src/core/stats_utils.py`. Signature: `bootstrap_ci_lower(pnl_r_values: list[float], alpha: float = 0.05, n_boot: int = 1000) -> float`. Returns `-inf` on empty input. Both `ShadowAuditorAgent` and `weight_updater.py` import from this module.

### D-08: ShadowTransitionEvent on Kafka topic intelligence.shadow.transitions
New dataclass `ShadowTransitionEvent` in `src/intelligence/schemas.py`. New `topic_shadow_transitions(env_name: str)` function in `src/core/stream_keys.py`. Published by ShadowAuditorAgent on any promotion or demotion.

### D-09: _is_shadow() pipeline cache
IntelligencePipelineAgent loads `_shadow_cache: dict[str, bool]` from `shadow_registry` at startup (SELECT component_name, is_shadow FROM shadow_registry). Background task refreshes every 5 minutes. Replaces `getattr(plugin_inst, "IS_SHADOW", False)` at signal emit time with `_is_shadow(plugin_name)` cache lookup (no DB hit on hot path). Same cache loaded by SwarmOrchestratorAgent for swarm agent shadow state.

### D-10: Rename signal["_shadow"] → signal["features_snapshot"]
Mechanical find-replace across all 37 I7 plugin files in `src/intelligence/trading/`. The key in `confidence_utils.capture_signal_features()` return dict does not change (it returns a plain dict — the caller assigns it). Only the assignment `signal["_shadow"] = ...` → `signal["features_snapshot"] = ...` changes in each plugin. Update `confidence_utils.py` docstring. No leading underscore — this data flows to DB and is not transient.

### D-11: Remove IS_SHADOW ClassVar from dual_divergence.py
`dual_divergence.py` currently has `IS_SHADOW: ClassVar[bool] = False`. This plugin is live (not shadow) — it should simply not declare any shadow attribute. Remove the `IS_SHADOW` declaration entirely. The plugin auto-enrolls via the default enrollment protocol (D-01) unless `SHADOW_SKIP = True` is added.

### D-12: Remove shadow_only instance attribute from SwarmBaseAgent subclasses
Three swarm agents (`correlation_agent.py`, `volume_agent.py`, `skeptic_agent.py`) have `shadow_only = True`. Remove these instance attributes. `AgentResult.shadow_only` field is populated from `_shadow_cache` via `_is_shadow()` rather than from the class attribute. SwarmBaseAgent auto-enrolls all subclasses at startup (D-01 pattern).

### D-13: Remove SHADOW_PLUGINS tuple and compute_shadow_plugin_stats() from weight_updater.py
`SHADOW_PLUGINS: tuple[str, ...] = ()` is hardcoded and empty — delete it. `compute_shadow_plugin_stats()` function moves to `shadow_auditor_agent.py`. Remove its call from `run_weight_update()`. Import `bootstrap_ci_lower` from `src/core/stats_utils.py` for weight_updater's own CI computations.

### D-14: shadow_registry_ensure() is idempotent
`INSERT INTO shadow_registry (component_name, component_type) VALUES ($1, $2) ON CONFLICT (component_name) DO NOTHING`. Never overwrites existing rows — custom gate parameters tuned in DB are preserved across restarts. A plugin that has been promoted (`is_shadow = FALSE`) keeps that state on restart.

### D-15: Migration 076
File: `production/migrations/076_shadow_governance.sql`. Creates `shadow_registry` and `shadow_transition_log`. No data migration needed — registry starts empty and is populated by auto-enrollment on next pipeline startup.

### D-16: Update CLAUDE.md
Remove stale: "Shadow modes: CROSS_ASSET active; ROLL_MONITOR disabled; trad_DualDivergence IS_SHADOW=True". Add shadow governance section covering `shadow_registry` as source of truth, `SHADOW_SKIP` opt-out, `ShadowAuditorAgent` cadence, and `features_snapshot` key name.

### Claude's Discretion
- Prometheus metric labels: use existing `SHADOW_*` gauge names/labels unchanged (only move their emit location from weight_updater to shadow_auditor_agent)
- Timer interval: 30 minutes (same as weight update cadence — consistent with existing timer pattern)
- Kafka topic retention: use existing `_BUFFER_MS` (1 day) — transition events are low volume
- Thread safety of `_shadow_cache` refresh: use `asyncio.Lock` on the refresh task to prevent race on cache dict swap
- `n_boot=1000` for bootstrap CI: consistent with existing weight_updater implementation

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Design Spec (primary source)
- `docs/plans/2026-04-28-shadow-governance-design.md` — Full approved design with data model, architecture, and component list

### Existing Shadow Code to Modify/Remove
- `src/intelligence/weight_updater.py` — `compute_shadow_plugin_stats()`, `_bootstrap_ci_lower()`, `SHADOW_PLUGINS` to remove
- `src/intelligence/trading/dual_divergence.py` — `IS_SHADOW: ClassVar[bool] = False` to remove
- `src/core/swarm/base_agent.py` — `shadow_only: bool = True` to restructure
- `src/intelligence/swarm/agents/correlation_agent.py`, `volume_agent.py`, `skeptic_agent.py` — `shadow_only = True` instance attrs to remove
- `src/intelligence/trading/confidence_utils.py` — docstring update (`_shadow` → `features_snapshot`)

### Existing Patterns to Follow
- `src/core/ml/shadow.py` — ShadowRecorder batch writer pattern (timer + DB write)
- `production/systemd/indicagent-ml-data-quality.service` — timer service unit pattern
- `production/systemd/indicagent-ml-data-quality.timer` — timer unit pattern
- `src/core/stream_keys.py` — topic function naming convention
- `src/intelligence/schemas.py` — IntelligenceEvent/ShadowTransitionEvent dataclass location
- `src/intelligence/register_plugins.py` — TIER_I7 list, register_all_plugins() hook point
- `production/migrations/075_macro_features.sql` — SQL migration file format

### Signal Ledger Query Reference
- `src/persistence/repository/signal_ledger_repository.py` — field names: `setup_plugin`, `outcome`, `pnl_r`, `signal_computed_at`, `is_shadow`
- `src/observability/metrics.py` — `SHADOW_N_RESOLVED`, `SHADOW_WIN_RATE`, `SHADOW_EV_R`, `SHADOW_EV_CI_LOWER`, `SHADOW_DAYS_TO_GATE`, `SHADOW_PROMOTION_READY` gauges

</canonical_refs>

<specifics>
## Specific Values

- Migration number: `076_shadow_governance.sql`
- New files: `src/core/stats_utils.py`, `services/shadow_auditor_agent.py`, `production/systemd/indicagent-shadow-auditor.service`, `production/systemd/indicagent-shadow-auditor.timer`, `production/migrations/076_shadow_governance.sql`
- New topic function: `topic_shadow_transitions(env_name: str)` in `stream_keys.py` → returns `f"{env_prefix(env_name)}intelligence.shadow.transitions"`
- I7 plugin files requiring `signal["_shadow"]` → `signal["features_snapshot"]` rename: all files in `src/intelligence/trading/` that contain `signal["_shadow"]` (~35 files per grep)
- Timer cadence: 30 minutes (OnCalendar=*:0/30 in systemd timer)
- Cache refresh interval: 5 minutes
- Default gate: min_n=100, min_ev_r=0.0, ci_alpha=0.05
- Default demotion: demotion_lookback_days=30, demotion_threshold_ev_r=-0.05, demotion_min_evaluations=3

</specifics>

<deferred>
## Deferred Ideas

- Dashboard subscription to `intelligence.shadow.transitions` Kafka topic for live promotion/demotion feed — out of scope for Phase 75, natural follow-on
- Per-plugin gate parameter tuning UI — deferred, DB direct edit is sufficient for now
- Cross-asset shadow mode (whole-pipeline parallel shadow via `topic_intelligence_shadow`) — separate concern, not addressed here

</deferred>

---

*Phase: 75-shadow-governance-system-automated-promotion-demotion*
*Context gathered: 2026-04-28 via PRD Express Path (design spec)*
