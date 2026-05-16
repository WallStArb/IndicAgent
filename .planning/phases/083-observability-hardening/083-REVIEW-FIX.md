---
phase: 083-observability-hardening
fixed_at: 2026-05-15T21:48:00Z
review_path: .planning/phases/083-observability-hardening/083-REVIEW.md
iteration: 1
findings_in_scope: 8
fixed: 8
skipped: 0
status: all_fixed
---

# Phase 083: Code Review Fix Report

**Fixed at:** 2026-05-15T21:48:00Z
**Source review:** .planning/phases/083-observability-hardening/083-REVIEW.md
**Iteration:** 1

**Summary:**
- Findings in scope: 8 (3 critical + 5 warning; info excluded)
- Fixed: 8
- Skipped: 0

## Fixed Issues

### CR-01: SwarmCapacitySkipRateHigh alert references a label value that is never emitted

**Files modified:** `production/alertmanager-rules.yml`
**Commit:** 12d67080
**Applied fix:** Changed the alert expression from `status="capacity_skip"` to `status="error"`, which is one of the three label values (`ok`, `error`, `all_failed`) actually emitted by `alpha_swarm_agent.py`. Updated the summary annotation accordingly.

---

### CR-02: CIRCUIT_BREAKER_STATE, PERSISTENCE_CONSUMER_LAG, and AGENT_LAST_MESSAGE_TIMESTAMP_SECONDS misused as accumulating counters

**Files modified:** `src/observability/metrics.py`, `src/core/plugin_circuit_breaker.py`, `src/core/agent/base.py`, `src/core/agent/base_writer.py`
**Commit:** a4bbbaad
**Applied fix:** Replaced all three `create_up_down_counter` declarations with `create_gauge` in `metrics.py`. Updated all 6 `CIRCUIT_BREAKER_STATE.add(...)` call sites in `plugin_circuit_breaker.py` to `.set(...)`. Updated `AGENT_LAST_MESSAGE_TIMESTAMP_SECONDS.add(...)` in `base.py` to `.set(...)`. Updated `PERSISTENCE_CONSUMER_LAG.add(...)` in `base_writer.py` to `.set(...)`. This resolves the accumulation bug where state-tracking metrics grew permanently incorrect over state transitions.

Note: WR-05 (OPEN->HALF_OPEN accumulation) is fully resolved by this fix — `.set()` overwrites the previous value rather than accumulating.

---

### CR-03: LLMProviderChain._publish_parse_failure() dereferences self._settings without a None guard

**Files modified:** `src/core/llm/chain.py`
**Commit:** 0349602a
**Applied fix:** Added `or self._settings is None` guard to both `_publish_parse_failure()` (the reported crash path) and `_publish_audit()` (the same pattern on an adjacent path). Both methods now return early when settings is None, preventing AttributeError on `self._settings.env_name`.

---

### WR-01: dlq_events dedup index silently drops burst errors; id lacks PRIMARY KEY

**Files modified:** `production/migrations/088_dlq_events.sql`
**Commit:** 3786ce6f
**Applied fix:** Added `PRIMARY KEY (id, routed_at)` to the table DDL (TimescaleDB requires the partition column in the primary key). Removed the `CREATE UNIQUE INDEX dlq_events_dedup_idx` on `(agent, source_topic, routed_at)` — the dedup index violated the table's stated purpose as a loss-of-information audit log by silently dropping burst errors sharing the same microsecond timestamp.

---

### WR-02: plugin_circuit_breaker.py uses naive datetime.now() throughout

**Files modified:** `src/core/plugin_circuit_breaker.py`
**Commit:** 6cee71dd
**Applied fix:** Added `UTC` to the `from datetime import` statement. Replaced all 6 `datetime.now()` calls with `datetime.now(UTC)`. Persisted state via `_serialize_plugin_state()` now produces timezone-aware ISO strings (`+00:00` suffix), preventing incorrect recovery timeout calculations across DST boundaries or non-UTC locales.

---

### WR-03: ensure_topics.sh alter-config step can abort mid-loop without clear error

**Files modified:** `production/scripts/ensure_topics.sh`
**Commit:** f2e3b726
**Applied fix:** Added a Redpanda connectivity check (`docker exec redpanda rpk cluster info`) before the topic loop. If Redpanda is unreachable, the script exits immediately with a clear error message rather than silently swallowing the create error and then failing mid-loop on `alter-config`. The `|| true` on `rpk topic create` now correctly handles only the "topic already exists" case (confirmed reachable), while `alter-config` failures remain loud.

---

### WR-04: BaseAgent._report_consumer_lag() emits no-op PERSISTENCE_CONSUMER_LAG.add(0) every 15s

**Files modified:** `src/core/agent/base.py`
**Commit:** 786dfc22
**Applied fix:** Removed the `PERSISTENCE_CONSUMER_LAG.set(0, ...)` call from the base class loop. Stream processors have no buffer lag to report. The loop now sleeps for 60 seconds between stop-event checks (vs 15s before) to reduce wake-up overhead while still supporting clean shutdown. Removed the now-unused `PERSISTENCE_CONSUMER_LAG` import from `base.py` — `base_writer.py` imports it directly.

---

### WR-05: CIRCUIT_BREAKER_STATE metric accumulates permanently incorrect state on OPEN->HALF_OPEN

**Files modified:** (resolved as part of CR-02)
**Commit:** a4bbbaad (same as CR-02)
**Applied fix:** Resolved entirely by the CR-02 gauge conversion. `.set()` overwrites the current exported value on every state transition rather than accumulating additions. After OPEN->HALF_OPEN, the metric correctly exports `2` (HALF_OPEN), not `1+2=3`.

---

_Fixed: 2026-05-15T21:48:00Z_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 1_
