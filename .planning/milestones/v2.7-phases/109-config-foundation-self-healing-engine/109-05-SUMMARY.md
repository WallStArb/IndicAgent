---
phase: 109-config-foundation-self-healing-engine
plan: "05"
subsystem: self-healing
tags: [self-healing, webhook, fastapi, runtime-defaults, config-shim, lag-thresholds, shadow-mode, hot-reload, d07-precedence]
dependency_graph:
  requires:
    - SelfHealingEngine  # 109-04: engine.py, pool_manager.py
    - ManagedPool        # 109-04: owns pool lifecycle
    - ConfigConsumerMixin  # 109-03: _on_config_message_received hook, get_config()
    - config_schema/config_state tables  # 109-01
    - webhook_metrics    # 109-02: WEBHOOK_RECEIVED_TOTAL etc
  provides:
    - SelfHealingAgent   # FastAPI service port 9002 / metrics port 9007
    - runtime_defaults   # src/config/runtime_defaults.py: 15 typed _DEFAULT_* constants
    - get_config_value   # Settings.get_config_value() shim with typed fallback
    - lag_thresholds_from_config  # ServiceAuditorAgent loads alert.lag.* from DB
    - shadow_mode_from_config     # 4 AI agents: shadow_only driven by config, not hardcoded
    - AlphaSwarm_config_delivery  # _on_config_message_received + _apply_shadow_mode_config
  affects:
    - services/self_healing_agent.py (created)
    - production/systemd/indicagent-self-healing-agent.service (created)
    - src/config/runtime_defaults.py (created)
    - src/config/settings.py (get_config_value shim added)
    - services/service_auditor_agent.py (_LAG_THRESHOLDS removed)
    - services/alpha_swarm_agent.py (config delivery wired)
    - src/intelligence/ai/alpha/correlation_agent.py (shadow_only annotated + hook)
    - src/intelligence/ai/alpha/counterfactual_agent.py (shadow_only annotated + hook)
    - src/intelligence/ai/alpha/regime_coherence_agent.py (shadow_only annotated + hook)
    - src/intelligence/ai/alpha/ml_scorer_agent.py (shadow_only annotated + hook)
    - production/migrations/109_config_foundation.sql (15 OPS + 21 lag + 4 shadow rows)
tech_stack:
  added: []
  patterns:
    - FastAPI webhook with defense-in-depth auth (HTTP layer + engine layer)
    - ManagedPool ownership: caller passes database_url string, not raw pool
    - Typed fallback module (runtime_defaults.py) prevents None returns for numeric thresholds
    - Config DB over hardcoded constants (fail-closed on miss = keep code default)
    - Per-agent config cache propagation: AlphaSwarm pushes ai.agent.* keys to each agent
    - D-07 precedence: config DB wins over shadow_registry in _refresh_shadow_state_from_registry
key_files:
  created:
    - services/self_healing_agent.py
    - production/systemd/indicagent-self-healing-agent.service
    - src/config/runtime_defaults.py
  modified:
    - src/config/settings.py
    - services/service_auditor_agent.py
    - services/alpha_swarm_agent.py
    - src/intelligence/ai/alpha/correlation_agent.py
    - src/intelligence/ai/alpha/counterfactual_agent.py
    - src/intelligence/ai/alpha/regime_coherence_agent.py
    - src/intelligence/ai/alpha/ml_scorer_agent.py
    - production/migrations/109_config_foundation.sql
    - tests/unit/services/test_service_auditor_agent.py
decisions:
  - "SelfHealingAgent HTTP auth on both HTTP layer (fastapi) and engine layer (defense-in-depth)"
  - "ManagedPool constructed with settings.database_url string per Plan 04 contract; no raw pool pre-created"
  - "Settings fields SWARM_*/REGIME_*/ROLL_*/CROSS_ASSET_*/MACRO_* RETAINED; removal deferred to Phase 110"
  - "get_config_value emits DeprecationWarning to guide call-site migration to BaseAgent.get_config()"
  - "_config_prefixes=(alert.lag.,) on ServiceAuditorAgent to restrict Kafka reload storm"
  - "AlphaSwarm propagates ai.agent.* cache entries to each individual agent before _apply_shadow_mode_config()"
  - "D-07: config DB takes precedence in _refresh_shadow_state_from_registry; registry used only as fallback"
  - "skeptic_agent.py untouched (shadow_only=False; already live)"
  - "volume_agent.py not created (does not exist; checked was in error)"
metrics:
  duration_minutes: 10
  completed_date: "2026-05-29"
  tasks_completed: 4
  files_created: 3
  files_modified: 9
---

# Phase 109 Plan 05: SelfHealingAgent + Runtime Defaults + Config Cleanup Summary

**One-liner:** SelfHealingAgent HTTP service (port 9002 / OTel 9007) with defense-in-depth auth, typed runtime_defaults fallback preventing None returns, _LAG_THRESHOLDS replaced by config-backed loader, and 4 AI agent shadow_only flags driven by config DB with D-07 precedence in AlphaSwarmComputeAgent.

## What Was Built

### Task 1: SelfHealingAgent HTTP Service (6121e427)

**`services/self_healing_agent.py`:**

| Concern | Implementation |
|---------|----------------|
| HTTP port | 9002 (uvicorn) |
| OTel metrics port | 9007 (METRICS_PORT env in systemd unit) |
| Endpoint | POST /webhook/alertmanager |
| Auth | HTTP-layer: validates CONFIG_WEBHOOK_SHARED_SECRET (X-Webhook-Secret header OR payload field) |
| Auth design | Defense-in-depth: HTTP layer + engine layer both verify (engine.py is secondary gate) |
| Pool | ManagedPool(settings.database_url, pool_name="self_healing") - Plan 04 contract honored |
| No raw pool | grep for create_pool returns 0 matches - ManagedPool owns pool lifecycle |
| On 503 | Returns 503 if engine not initialized (startup in progress) |
| On 401 | Returns 401 if CONFIG_WEBHOOK_SHARED_SECRET set and secret wrong |
| On 200 | Returns {remediation_id, status, error} JSON body |

**`production/systemd/indicagent-self-healing-agent.service`:**
- Description explicitly names both port 9002 (HTTP API) and port 9007 (OTel metrics)
- `METRICS_PORT=9007` in Environment block
- WatchdogSec=60, Requires=indicagent-infrastructure.target
- systemd-analyze verify: PASS (no warnings)

Port mapping confirmation:
- 9001 = config-service HTTP API
- 9005 = config-service OTel metrics
- 9002 = self-healing HTTP API (this plan)
- 9007 = self-healing OTel metrics (this plan)

ManagedPool construction proof:
```python
managed_pool = ManagedPool(settings.database_url, pool_name="self_healing")
# grep -q "create_pool" services/self_healing_agent.py -> NOT FOUND (correct)
# grep -qE "ManagedPool\(settings\.database_url" -> FOUND (correct)
```

Auth test (manual verification):
- POST without CONFIG_WEBHOOK_SHARED_SECRET set: passes to engine (no HTTP-layer auth)
- POST with CONFIG_WEBHOOK_SHARED_SECRET set + no secret: 401
- POST with CONFIG_WEBHOOK_SHARED_SECRET set + wrong secret: 401
- POST with correct secret + valid payload: 200 with remediation_id/status/error keys

### Task 2: runtime_defaults.py + Settings.get_config_value() Shim (f4767ad5)

**`src/config/runtime_defaults.py`:** 15 typed _DEFAULT_* constants + RUNTIME_DEFAULTS dict.

```python
RUNTIME_DEFAULTS = {
    "regime.prob_min": 0.30,      # float
    "regime.dur_min": 1,           # int
    "swarm.min_confidence": 0.60,  # float
    "swarm.min_tf_minutes": 5,     # int
    "swarm.weight_min_samples": 30, # int
    "swarm.weight_floor": 0.05,    # float
    "swarm.max_concurrent_calls": 8, # int
    "roll.monitor_window_size": 100, # int
    "roll.threshold_default": 1.2,  # float
    "roll.postroll_bars": 10,        # int
    "roll.cooldown_min": 30,         # int
    "roll.confirmation_bars": 3,     # int
    "roll.time_of_day_gated": True,  # bool
    "cross_asset.window_bars": 20,   # int
    "macro.window_bars": 10,         # int
}
```

All 6 historically divergent keys verified to match settings.py defaults:
- swarm.min_confidence = SWARM_MIN_CONFIDENCE = 0.6 OK
- swarm.weight_min_samples = SWARM_WEIGHT_MIN_SAMPLES = 30 OK
- swarm.max_concurrent_calls = SWARM_MAX_CONCURRENT_CALLS = 8 OK
- roll.monitor_window_size = roll_monitor_window_size = 100 OK
- cross_asset.window_bars = cross_asset_window_bars = 20 OK
- macro.window_bars = macro_window_bars = 10 OK

**`Settings.get_config_value()` behavior:**
```python
Settings.get_config_value('regime.prob_min')    # -> 0.30 (float, NOT None)
Settings.get_config_value('unknown.key', 'x')  # -> 'x' (caller default)
Settings.get_config_value('unknown.key')         # -> None
get_settings().SWARM_MIN_CONFIDENCE              # -> 0.6 (back-compat preserved)
```

SWARM_*/REGIME_*/ROLL_*/CROSS_ASSET_*/MACRO_* fields RETAINED (deferred to Phase 110):
```
grep -E "^\\s*(REGIME_PROB_MIN|SWARM_MIN_CONFIDENCE|ROLL_MONITOR_WINDOW_SIZE|CROSS_ASSET_WINDOW_BARS|MACRO_WINDOW_BARS)" src/config/settings.py -> FOUND (correct)
```

alpha_swarm_agent.py SWARM_* references unchanged: grep -c "self.settings.SWARM_" = 5 (same count).

DB assertion: 15 config_schema + 15 config_state rows verified.

### Task 3: Replace _LAG_THRESHOLDS with Config-Backed Loader (c87e310c)

_LAG_THRESHOLDS removed: `grep -c "_LAG_THRESHOLDS" services/service_auditor_agent.py` = 0

Changes to `ServiceAuditorAgent`:
- `_config_prefixes = ("alert.lag.",)` - restricts Kafka reload to relevant keys (no storm)
- `_lag_thresholds: dict[str, int] = {}` - instance attribute
- `_load_lag_thresholds()` - reads from `_config_cache` (populated by Plan 03's _pre_setup_config_load); non-fatal
- Called at end of `_setup()` after config snapshot is loaded
- `_on_config_message_received()` override - calls `_load_lag_thresholds()` on alert.lag.* updates
- Both `_LAG_THRESHOLDS.get(unit, 0)` usages replaced with `self._lag_thresholds.get(unit, 0)`

Migration seeded 21 alert.lag.* rows (same count as original dict):
- DB: `SELECT COUNT(*) FROM config_schema WHERE config_key LIKE 'alert.lag.%'` = 21
- DB: `SELECT COUNT(*) FROM config_state WHERE config_key LIKE 'alert.lag.%'` = 21

Hot-reload behavior: after publishing alert.lag.feature-writer Kafka update, `_on_config_message_received` fires, calls `_load_lag_thresholds()`, and `self._lag_thresholds['indicagent-feature-writer']` reflects the new value WITHOUT restart.

### Task 4: AI Agent Shadow Mode + AlphaSwarm Kafka Delivery (0b9a42ca)

Four AI agents (correlation_v1, counterfactual_v1, regime_coherence_v1, ml_scorer_v1):

```python
# Before: shadow_only = True  (literal, no type annotation)
# After:  shadow_only: bool = True  (annotated, FAIL-CLOSED)
#         def _apply_shadow_mode_config(self) -> None:
#             override = self.get_config(f"ai.agent.{self.agent_id}.shadow_mode", None)
#             if override is None: return  # fail-closed
#             if isinstance(override, bool): self.shadow_only = override
#             elif isinstance(override, str): self.shadow_only = override.strip().lower() in ("true","1","yes")
```

skeptic_agent.py UNCHANGED: shadow_only = False (live agent - confirmed).
volume_agent.py NOT created (verified does not exist in codebase).

**AlphaSwarmComputeAgent changes:**
- `_config_prefixes = ("ai.agent.",)` - limits reload to ai.agent.* keys
- `_on_config_message_received()` override: propagates key to each agent's `_config_cache`, then calls `_apply_shadow_mode_config()` (Kafka hot-reload path)
- `_setup()`: propagates all ai.agent.* keys from AlphaSwarm's cache to each agent's cache BEFORE `_shadow_registry_ensure_agents` (initial load)
- `_refresh_shadow_state_from_registry()`: D-07 precedence - calls `self.get_config(f"ai.agent.{agent.agent_id}.shadow_mode")` FIRST; if not None, delegates to `agent._apply_shadow_mode_config()`; only falls back to shadow_registry if no config entry

D-07 precedence proof (manual verification):
- With empty config cache: shadow_only stays True (fail-closed)
- With config_cache['ai.agent.correlation_v1.shadow_mode'] = 'false': shadow_only flips to False
- With shadow_registry(correlation, False) AND config DB(correlation, True): shadow_only = True (config wins)

DB assertion: 4 ai.agent.*.shadow_mode rows with default 'true' seeded.

Publishing `ai.agent.correlation_v1.shadow_mode=false` via Kafka:
1. AlphaSwarm's `_reload_config_loop` receives the message
2. `_config_cache['ai.agent.correlation_v1.shadow_mode'] = False` updated by mixin
3. `_on_config_message_received` called
4. Each agent's `_config_cache` updated with new value
5. `_apply_shadow_mode_config()` called on CorrelationComputeAgent
6. `CorrelationComputeAgent.shadow_only = False` (within one poll cycle, no restart)

Migration seeds: 4 rows (config_schema + config_state), default 'true' (fail-closed).

## Acceptance Criteria Verification

```
# Task 1
grep -q "port=9002" services/self_healing_agent.py                   => FOUND
grep -q "9007" services/self_healing_agent.py                         => FOUND
grep -qE "ManagedPool\(settings\.database_url" self_healing_agent.py => FOUND
grep -q "create_pool" services/self_healing_agent.py                  => NOT FOUND (correct)
systemd-analyze verify indicagent-self-healing-agent.service          => EXIT 0

# Task 2
len(RUNTIME_DEFAULTS) == 15                                            => TRUE
RUNTIME_DEFAULTS['regime.prob_min'] == 0.30 (float)                   => TRUE
Settings.get_config_value('regime.prob_min') == 0.30                  => TRUE (NOT None)
Settings.get_config_value('unknown.key', 'x') == 'x'                 => TRUE
Settings.get_config_value('unknown.key') is None                       => TRUE
get_settings().SWARM_MIN_CONFIDENCE == 0.6                            => TRUE (back-compat)
SELECT COUNT(*) FROM config_schema WHERE config_key IN (15 keys) = 15 => TRUE
grep -c "self.settings.SWARM_" alpha_swarm_agent.py == 5              => TRUE (unchanged)

# Task 3
grep -c "_LAG_THRESHOLDS" service_auditor_agent.py == 0               => TRUE
grep -q "_config_prefixes" service_auditor_agent.py                   => FOUND
grep -q "_load_lag_thresholds" service_auditor_agent.py               => FOUND
grep -q "async def _on_config_message_received" service_auditor_agent => FOUND
SELECT COUNT(*) FROM config_schema WHERE config_key LIKE 'alert.lag.%' = 21 => TRUE

# Task 4
shadow_only: bool = True in all 4 agent files                          => TRUE
_apply_shadow_mode_config in all 4 agent files                         => TRUE
skeptic_agent.py shadow_only = False                                   => UNCHANGED
volume_agent.py does NOT exist                                         => TRUE
_on_config_message_received in alpha_swarm_agent.py                   => FOUND
_apply_shadow_mode_config called in alpha_swarm _setup()               => FOUND (before shadow_registry sync)
get_config("ai.agent.{agent.agent_id}.shadow_mode") in _refresh...    => FOUND (D-07)
_config_prefixes = ("ai.agent.",) in AlphaSwarmComputeAgent           => FOUND
SELECT COUNT(*) FROM config_schema WHERE config_key LIKE 'ai.agent.%.shadow_mode' = 4 => TRUE
```

## Unit Tests

```
pytest tests/unit/ -q: 4052 passed, 31 skipped (zero failures)
```

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Stale test_lag_thresholds_cover_consumers imported removed _LAG_THRESHOLDS**
- **Found during:** Post-task-3 pytest run
- **Issue:** `tests/unit/services/test_service_auditor_agent.py::test_lag_thresholds_cover_consumers` imported `_LAG_THRESHOLDS` which no longer exists after Task 3
- **Fix:** Updated test to verify alert.lag.* entries in migration SQL file (equivalent coverage)
- **Files modified:** `tests/unit/services/test_service_auditor_agent.py`
- **Commit:** ca31ad00

**2. [Rule 2 - Design] Agent config cache propagation for _apply_shadow_mode_config**
- **Found during:** Task 4 implementation
- **Issue:** Individual AI agents (correlation, etc.) have their own `_config_cache` (always empty) since they don't run as standalone services. `_apply_shadow_mode_config()` calls `self.get_config()` which reads from the agent's own empty cache, not from AlphaSwarm's cache.
- **Fix:** Before calling `_apply_shadow_mode_config()` on each agent, explicitly propagate `ai.agent.*` keys from AlphaSwarm's `_config_cache` to each agent's `_config_cache`. Done in both `_setup()` (initial load) and `_on_config_message_received()` (hot-reload). No architectural change - this is the correct propagation pattern for host/guest cache relationships.
- **Files modified:** `services/alpha_swarm_agent.py`
- **Commit:** 0b9a42ca

## Rollout Order

Recommended order per Codex MEDIUM finding:
1. Run migration: `PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -f production/migrations/109_config_foundation.sql`
2. Restart config-service (if running) to load new config_schema rows
3. Restart service-auditor to pick up alert.lag.* thresholds from DB
4. Restart alpha-swarm to pick up ai.agent.* shadow_mode from DB
5. Start self-healing-agent (new service): `sudo systemctl enable --now indicagent-self-healing-agent`

## Phase 110 Prerequisites (SWARM_* Migration)

The following work is explicitly deferred to Phase 110:
1. Migrate `services/alpha_swarm_agent.py` SWARM_* call sites (5 locations):
   - Line 173: `self.settings.SWARM_MAX_CONCURRENT_CALLS`
   - Line 281: `self.settings.SWARM_WEIGHT_MIN_SAMPLES`
   - Line 282: `self.settings.SWARM_WEIGHT_FLOOR`
   - Line 446: `self.settings.SWARM_MIN_TF_MINUTES`
   - Line 453: `self.settings.SWARM_MIN_CONFIDENCE`
2. Migrate remaining SWARM_*/REGIME_*/ROLL_*/CROSS_ASSET_*/MACRO_* call sites across the codebase
3. Remove corresponding fields from `src/config/settings.py`
4. Remove `src/config/runtime_defaults.py` (all callers will use BaseAgent.get_config() with explicit defaults)

## User Setup (Alertmanager Integration)

To enable webhook-triggered self-healing:

1. Generate a shared secret:
   ```bash
   openssl rand -hex 32
   ```

2. Set in `/etc/indicagent/self-healing.env` (create file):
   ```
   CONFIG_WEBHOOK_SHARED_SECRET=<your-generated-secret>
   PROMETHEUS_URL=http://localhost:9090
   ```

3. Add to systemd override:
   ```bash
   sudo systemctl edit indicagent-self-healing-agent
   # Add: [Service]
   # EnvironmentFile=/etc/indicagent/self-healing.env
   ```

4. Configure Alertmanager webhook:
   ```yaml
   receivers:
     - name: 'self-healing'
       webhook_configs:
         - url: 'http://localhost:9002/webhook/alertmanager'
           http_config:
             headers:
               X-Webhook-Secret: '<same-secret-as-CONFIG_WEBHOOK_SHARED_SECRET>'
   ```

5. Start service: `sudo systemctl enable --now indicagent-self-healing-agent`

## Self-Check: PASSED

Files verified:
- `services/self_healing_agent.py` - FOUND
- `production/systemd/indicagent-self-healing-agent.service` - FOUND
- `src/config/runtime_defaults.py` - FOUND
- `src/config/settings.py` (get_config_value added) - FOUND

Commits verified:
- `6121e427` (SelfHealingAgent service) - FOUND
- `f4767ad5` (runtime_defaults + shim) - FOUND
- `c87e310c` (_LAG_THRESHOLDS cleanup) - FOUND
- `0b9a42ca` (shadow_only cleanup) - FOUND
- `ca31ad00` (test fix) - FOUND
