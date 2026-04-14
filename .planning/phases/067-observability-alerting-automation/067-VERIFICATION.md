---
phase: 067-observability-alerting-automation
verified: 2026-04-13T22:30:00Z
status: gaps_found
score: 45/60 must-haves verified
overrides_applied: 0
gaps:
  - truth: "DLQ routing publishes bad payloads to Kafka topics"
    status: failed
    reason: "BaseAgent._send_to_dlq() calls producer.produce() but KafkaProducerClient only has publish() method - all DLQ messages fail with AttributeError and are silently discarded"
    artifacts:
      - path: "src/core/agent/base.py"
        issue: "Lines 322, 334 call producer.produce() instead of producer.publish()"
    missing:
      - "Fix producer.produce() → producer.publish() calls in BaseAgent._send_to_dlq()"

  - truth: "BaseAgent alert publishing works for all agents"
    status: failed
    reason: "BaseAgent._send_alert() references self._settings.env_name but BaseAgent.__init__() never sets self._settings - will fail with AttributeError for agents that don't set _settings before super().__init__()"
    artifacts:
      - path: "src/core/agent/base.py"
        issue: "Line 389 references self._settings.env_name without safe fallback"
    missing:
      - "Add safe fallback for self._settings in _send_alert() or ensure _settings is set in BaseAgent.__init__()"

  - truth: "LLMWriterService has Renaissance-style observability"
    status: failed
    reason: "LLMWriterService does not inherit from BaseAgent or BaseWriterAgent - lacks crash metrics, stall detection, and standard lifecycle"
    artifacts:
      - path: "services/llm_writer_service.py"
        issue: "Service manages its own lifecycle without BaseAgent inheritance"
    missing:
      - "Migrate LLMWriterService to BaseWriterAgent or at minimum BaseAgent for observability coverage"

  - truth: "Signal tracker bootstrap has retry logic with exponential backoff"
    status: failed
    reason: "Tests were written but implementation was deferred due to Read tool cache issues - signal_tracker_compute_agent.py still lacks the retry loop"
    artifacts:
      - path: "services/signal_tracker_compute_agent.py"
        issue: "Bootstrap retry implementation not completed"
      - path: "tests/unit/service_tests/test_signal_tracker_bootstrap.py"
        issue: "Tests exist but 2/5 fail due to missing implementation"
    missing:
      - "Implement bootstrap retry loop with exponential backoff in signal_tracker_compute_agent.py"

  - truth: "Grafana alert for signal buffer drops fires when messages are dropped"
    status: failed
    reason: "Alert rule references signal_writer_buffer_dropped_total metric which doesn't exist - actual metric is signal_writer_agent_buffer_overflow_total"
    artifacts:
      - path: "production/grafana/provisioning/alerting/alert-rules.yml"
        issue: "Line 93 queries non-existent metric signal_writer_buffer_dropped_total"
    missing:
      - "Fix alert rule to use signal_writer_agent_buffer_overflow_total metric"

  - truth: "LifecycleWriterAgent and SignalAuditorAgent have unique metrics ports"
    status: failed
    reason: "Both agents bind to port 9128 - whichever starts second will fail to bind"
    artifacts:
      - path: "services/lifecycle_writer_agent.py"
        issue: "Uses metrics_port=9128"
      - path: "services/signal_auditor_agent.py"
        issue: "Uses metrics_port=9128"
    missing:
      - "Assign unique metrics port to one agent (e.g., change SignalAuditorAgent to 9134)"

  - truth: "All DLQ topics defined in stream_keys.py are provisioned"
    status: partial
    reason: "provision_dlq_topics.sh creates 11 topics but stream_keys.py defines 15 DLQ topics - roll_dlq, health_events_dlq, ml_orchestrator_dlq, market_data_quality_dlq missing from provisioning script"
    artifacts:
      - path: "production/scripts/provision_dlq_topics.sh"
        issue: "Missing 4 DLQ topics"
      - path: "src/core/stream_keys.py"
        issue: "Defines 15 DLQ topic functions, topic_swarm_writer_dlq duplicated at lines 322-324 and 393-395"
    missing:
      - "Add missing 4 DLQ topics to provisioning script, remove duplicate topic_swarm_writer_dlq definition"

  - truth: "BarAuditorAgent doesn't publish duplicate gap requests when gap is resolved"
    status: partial
    reason: "When completeness >= 1.0, code calls _resolve_market_data_gap() AND publishes a new BarGapRequest - contradictory behavior"
    artifacts:
      - path: "services/bar_auditor_agent.py"
        issue: "Lines 341-373 run gap request append block in both resolved and unresolved branches"
    missing:
      - "Remove gap request append logic from the completeness >= 1.0 branch"

  - truth: "All agents emit consumer lag metrics"
    status: partial
    reason: "Plan 067-06 Task 2 (consumer lag reporting) was not implemented - agents don't override _report_consumer_lag() or emit PERSISTENCE_CONSUMER_LAG"
    artifacts:
      - path: "Multiple agent files"
        issue: "Missing _report_consumer_lag() overrides"
    missing:
      - "Implement _report_consumer_lag() overrides in consumer agents to emit PERSISTENCE_CONSUMER_LAG metric"

  - truth: "Grafana dashboards have consumer lag panels"
    status: partial
    reason: "Plan 067-06 Task 3 (Grafana dashboard panels for consumer lag) was not implemented"
    artifacts:
      - path: "production/grafana/dashboards/"
        issue: "No consumer lag panels added to dashboards"
    missing:
      - "Add consumer lag panels to operations.json and pipeline-health.json"

  - truth: "ParityAuditorAgent metrics are exposed on consistent port"
    status: partial
    reason: "ParityAuditorAgent calls start_metrics_server() in main() before BaseAgent.start() - metrics split across two ports"
    artifacts:
      - path: "services/parity_auditor_agent.py"
        issue: "Line 361 starts metrics server before agent.start(), BaseAgent stall detection uses different port"
    missing:
      - "Pass metrics_port=METRICS_PORT to super().__init__() and remove standalone start_metrics_server() call"

  - truth: "CrossAssetComputeAgent backward compatibility shim removed"
    status: partial
    reason: "CrossAssetService = CrossAssetComputeAgent alias preserves backward compatibility but tests should use new name"
    artifacts:
      - path: "services/cross_asset_service.py"
        issue: "Line 466 has CrossAssetService = CrossAssetComputeAgent shim"
    missing:
      - "Update tests to import CrossAssetComputeAgent directly and remove alias"
deferred: []
---

# Phase 067: Observability, Alerting & Automation Verification Report

**Phase Goal:** Add comprehensive observability, alerting, and automation to the IndicAgent pipeline — crash metrics, stall detection, DLQ routing, consumer lag reporting, Grafana dashboards, and alerting.
**Verified:** 2026-04-13T22:30:00Z
**Status:** gaps_found
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| #   | Truth   | Status     | Evidence       |
| --- | ------- | ---------- | -------------- |
| 1   | BaseAgent provides crash/setup metrics + alert publishing | ✓ VERIFIED | src/core/agent/base.py has AGENT_CRASH_TOTAL, AGENT_SETUP_SUCCESS_TOTAL, AGENT_SETUP_FAILURE_TOTAL, AGENT_SETUP_LATENCY_SECONDS, _send_alert() method |
| 2   | All agents inherit crash metrics from BaseAgent | ⚠️ PARTIAL | 11/12 consumer agents inherit from BaseAgent (LLMWriterService exception) |
| 3   | DLQ routing captures bad payloads instead of dropping | ✗ FAILED | CR-01: producer.produce() method doesn't exist - all DLQ messages fail |
| 4   | Alert publishing routes to Kafka topic | ✗ FAILED | CR-02: self._settings.env_name will fail with AttributeError |
| 5   | Grafana alert rules provisioned | ✓ VERIFIED | production/grafana/provisioning/alerting/alert-rules.yml has 10 rules |
| 6   | Contact points configured | ✓ VERIFIED | contact-points.example.yml committed, contact-points.yml gitignored |
| 7   | Roll automation triggers ibkr-provider restart | ✓ VERIFIED | service_auditor_agent.py has _roll_consumer_loop, _handle_roll_event, _restart_ibkr_provider |
| 8   | market_data_gaps table exists | ✓ VERIFIED | production/migrations/062_market_data_gaps.sql creates table |
| 9   | BarAuditorAgent writes to market_data_gaps | ✓ VERIFIED | bar_auditor_agent.py has _upsert_market_data_gap, _resolve_market_data_gap |
| 10  | Bootstrap retry in signal_tracker_compute_agent | ✗ FAILED | Tests written but implementation deferred |
| 11  | SwarmOrchestratorAgent cache seeding from DB | ✓ VERIFIED | swarm_orchestrator_agent.py has _seed_context_cache, context.py has seed_from_db_row |
| 12  | Webhook dispatcher in ServiceAuditorAgent | ✓ VERIFIED | service_auditor_agent.py has _notify_telegram, _notify_discord, _dispatch_webhook |
| 13  | Three Grafana dashboards rebuilt | ✓ VERIFIED | operations.json, pipeline-health.json, signals-i8.json all rebuilt |
| 14  | Dashboards reference current service names | ✓ VERIFIED | No archived service names in dashboards (verified by smoke tests) |
| 15  | CrossAssetService migrated to BaseAgent | ✓ VERIFIED | cross_asset_service.py renamed to CrossAssetComputeAgent, inherits from BaseAgent |
| 16  | LLMWriterService migrated to BaseAgent | ✗ FAILED | Migration deferred due to architectural incompatibility |
| 17  | Stall detection enabled on all consumer agents | ✓ VERIFIED | 11/11 consumer agents have max_idle_seconds and _record_message_consumed() |
| 18  | DLQ topics provisioned in Redpanda | ⚠️ PARTIAL | 11/15 DLQ topics created - 4 missing |
| 19  | DLQ metrics emitted when routing | ⚠️ PARTIAL | Metrics defined but routing broken (CR-01) |
| 20  | Consumer lag metrics emitted | ✗ FAILED | Plan 067-06 Task 2 not implemented |

**Score:** 12/20 truths verified (60%), 4 partial (20%), 4 failed (20%)

### Deferred Items

None.

### Required Artifacts

| Artifact | Expected | Status | Details |
| -------- | -------- | ------ | ------- |
| src/core/agent/base.py | BaseAgent with crash/setup metrics, alert publishing, stall detection, DLQ routing | ⚠️ PARTIAL | Has metrics and stall detection, but DLQ routing broken (CR-01), alert publishing broken (CR-02) |
| src/core/agent/base_writer.py | BaseWriterAgent with DLQ routing pattern | ✓ VERIFIED | Has _maybe_route_to_dlq() helper |
| src/core/schemas/dlq_payload.py | DLQPayload schema | ✓ VERIFIED | Defined with all required fields |
| src/core/stream_keys.py | DLQ topic functions | ⚠️ PARTIAL | Has 15 DLQ functions but topic_swarm_writer_dlq duplicated |
| src/config/settings.py | Webhook credential fields | ✓ VERIFIED | telegram_bot_token, telegram_chat_id, discord_webhook_url |
| src/observability/metrics.py | DLQ metrics, service restarts counter, gap fill DLQ depth | ✓ VERIFIED | DLQ_DEPTH, DLQ_MESSAGES_TOTAL, SERVICE_AUDITOR_SERVICE_RESTARTS_TOTAL, BAR_AUDITOR_GAP_FILL_DLQ_DEPTH |
| production/grafana/provisioning/alerting/contact-points.example.yml | Contact points template | ✓ VERIFIED | Template with placeholder values |
| production/grafana/provisioning/alerting/contact-points.yml | Gitignored local file | ✓ VERIFIED | Exists in .gitignore |
| production/grafana/provisioning/alerting/alert-rules.yml | 10 alert rules | ⚠️ PARTIAL | Has 10 rules but one references non-existent metric (WR-07) |
| production/grafana/dashboards/operations.json | Operations dashboard | ✓ VERIFIED | 21 panels with Golden Signals structure |
| production/grafana/dashboards/pipeline-health.json | Pipeline health dashboard | ✓ VERIFIED | 13 panels with latency/throughput/health rows |
| production/grafana/dashboards/signals-i8.json | Signals + I8 dashboard | ✓ VERIFIED | 12 panels with signal funnel/routing/narrative rows |
| production/migrations/062_market_data_gaps.sql | market_data_gaps table | ✓ VERIFIED | Creates table with unique constraint |
| production/scripts/provision_dlq_topics.sh | DLQ topic provisioning script | ⚠️ PARTIAL | Creates 11/15 topics - 4 missing |
| services/service_auditor_agent.py | Roll event consumer, webhook dispatcher | ✓ VERIFIED | Has _roll_consumer_loop, _handle_roll_event, _restart_ibkr_provider, _dispatch_webhook |
| services/bar_auditor_agent.py | market_data_gaps write path, gap resolution | ⚠️ PARTIAL | Has _upsert_market_data_gap, _resolve_market_data_gap but duplicate gap request bug (WR-02) |
| services/cross_asset_service.py | Migrated to CrossAssetComputeAgent | ✓ VERIFIED | Inherits from BaseAgent, has backward compatibility shim |
| services/swarm_orchestrator_agent.py | Cache seeding from DB | ✓ VERIFIED | Has _seed_context_cache method |
| src/intelligence/swarm/context.py | seed_from_db_row method | ✓ VERIFIED | Has seed_from_db_row method |
| tests/unit/service_tests/test_signal_tracker_bootstrap.py | Bootstrap retry tests | ⚠️ PARTIAL | 5 tests written but 2 fail due to missing implementation |
| tests/unit/service_tests/test_swarm_orchestrator_seeding.py | Cache seeding tests | ✓ VERIFIED | 6 tests verify seeding behavior |

### Key Link Verification

| From | To | Via | Status | Details |
| ---- | -- | --- | ------ | ------- |
| BaseAgent._send_alert | Kafka topic alert.requests | _producer.publish() | ✗ FAILED | CR-02: self._settings.env_name will fail |
| BaseAgent._send_to_dlq | DLQ topics | _producer.produce() | ✗ FAILED | CR-01: producer.produce() doesn't exist, should be publish() |
| ServiceAuditorAgent._dispatch_webhook | Telegram/Discord | aiohttp POST | ✓ VERIFIED | _notify_telegram, _notify_discord implemented |
| ServiceAuditorAgent._handle_roll_event | ibkr-provider restart | subprocess systemctl | ✓ VERIFIED | _restart_ibkr_provider calls systemctl |
| BarAuditorAgent._detect_gaps | market_data_gaps table | asyncpg execute | ✓ VERIFIED | _upsert_market_data_gap, _resolve_market_data_gap |
| SwarmOrchestratorAgent._seed_context_cache | intelligence_features table | asyncpg fetch | ✓ VERIFIED | Queries last row per (symbol, tf) |

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
| -------- | ------------- | ------ | ------------------ | ------ |
| operations.json dashboard | Prometheus metrics | Prometheus | ✓ FLOWING | Dashboard queries Prometheus for agent_crash_total, service_auditor_service_restarts_total, etc. |
| pipeline-health.json dashboard | PromQL histograms | Prometheus | ✓ FLOWING | Latency histograms emit from agents |
| signals-i8.json dashboard | Signal metrics | Prometheus | ✓ FLOWING | signal_tracker_compute_active_signals metric exists |
| DLQ topics | DLQPayload | BaseAgent._send_to_dlq | ✗ DISCONNECTED | CR-01: produce() method doesn't exist - no messages reach topics |
| alert.requests topic | Alert payloads | BaseAgent._send_alert | ✗ DISCONNECTED | CR-02: self._settings.env_name fails - no alerts published |
| market_data_gaps table | Gap rows | BarAuditorAgent | ✓ FLOWING | _upsert_market_data_gap writes to DB |
| roll_events topic | RollEvent payloads | RollComputeAgent | ✓ FLOWING | ServiceAuditorAgent consumes and triggers restart |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
| -------- | ------- | ------ | ------ |
| Step 7b: SKIPPED (no runnable entry points) | - | - | ? SKIP |

**Reason:** Phase 067 is infrastructure-only (observability, alerting, automation). No runnable entry points to test without starting full services. Requires human verification for:
- Visual verification of Grafana dashboards loading
- Manual test of Telegram/Discord webhooks (requires real credentials)
- Manual test of roll automation (requires futures roll event)
- Manual test of DLQ routing (after CR-01 fix)

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
| ----------- | ----------- | ----------- | ------ | -------- |
| OBS-GRAFANA-ALERTS | 067-03 | Grafana alert rules for CRITICAL/HIGH/MEDIUM | ⚠️ PARTIAL | 10 rules exist but one references non-existent metric (WR-07) |
| OBS-CONTACT-POINTS | 067-03 | Contact points for Telegram/Discord | ✓ VERIFIED | Example file committed, gitignored local file exists |
| OBS-GAP-TABLE | 067-01 | market_data_gaps table for ML exclusion | ✓ VERIFIED | Migration 062 creates table |
| OBS-BAR-AUDITOR | 067-03 | BarAuditorAgent writes to market_data_gaps | ⚠️ PARTIAL | Has write path but duplicate gap request bug (WR-02) |
| OBS-ROLL-AUTO | 067-03 | Roll automation triggers ibkr-provider restart | ✓ VERIFIED | service_auditor_agent implements roll consumer |
| OBS-WEBHOOK-DISPATCHER | 067-01 | Webhook dispatcher in ServiceAuditorAgent | ✓ VERIFIED | _notify_telegram, _notify_discord, _dispatch_webhook |
| OBS-BOOTSTRAP-RETRY | 067-02 | Bootstrap retry in signal_tracker_compute_agent | ✗ FAILED | Tests written but implementation deferred |
| OBS-SWARM-SEED | 067-02 | SwarmOrchestratorAgent cache seeding | ✓ VERIFIED | _seed_context_cache, seed_from_db_row implemented |
| OBS-DASHBOARDS | 067-04 | Three Grafana dashboards rebuilt | ✓ VERIFIED | operations.json, pipeline-health.json, signals-i8.json |

**Coverage:** 5/9 requirements fully verified, 3/9 partial, 1/9 failed

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
| ---- | ---- | ------- | -------- | ------ |
| src/core/agent/base.py | 322, 334 | producer.produce() method doesn't exist | 🛑 Blocker | All DLQ routing fails |
| src/core/agent/base.py | 389 | References self._settings without safe fallback | 🛑 Blocker | Alert publishing fails for agents without _settings |
| production/grafana/provisioning/alerting/alert-rules.yml | 93 | References non-existent metric signal_writer_buffer_dropped_total | 🛑 Blocker | Alert will never fire |
| services/lifecycle_writer_agent.py | 80 | metrics_port=9128 collides with SignalAuditorAgent | 🛑 Blocker | Port binding conflict when both services run |
| services/signal_auditor_agent.py | 119 | metrics_port=9128 collides with LifecycleWriterAgent | 🛑 Blocker | Port binding conflict when both services run |
| services/bar_auditor_agent.py | 341-373 | Duplicate gap request logic in resolved branch | ⚠️ Warning | Publishes gap requests for resolved gaps |
| services/llm_writer_service.py | 1 | Does not inherit from BaseAgent | ⚠️ Warning | No crash metrics or stall detection |
| src/core/stream_keys.py | 322-324, 393-395 | Duplicate topic_swarm_writer_dlq definition | ℹ️ Info | Confusing but no functional impact |
| services/parity_auditor_agent.py | 361 | start_metrics_server() before BaseAgent.start() | ℹ️ Info | Metrics split across two ports |
| services/cross_asset_service.py | 466 | Backward compatibility shim | ℹ️ Info | Should update tests to use new name |

### Human Verification Required

1. **Grafana Dashboards Load Correctly**
   - **Test:** Load Grafana UI, navigate to Dashboards, open "IndicAgent Operations", "IndicAgent Pipeline Health", "IndicAgent Signals + I8"
   - **Expected:** All three dashboards load without errors, panels display data from Prometheus/TimescaleDB
   - **Why human:** Cannot verify dashboard rendering and data flow programmatically

2. **Telegram Webhook Delivers Critical Alerts**
   - **Test:** Configure real telegram_bot_token and telegram_chat_id in contact-points.yml, trigger a CRITICAL alert (e.g., stop indicagent-ibkr-provider, wait 5 minutes for provider_dead alert)
   - **Expected:** Telegram message received in configured chat with alert details
   - **Why human:** Requires real Telegram credentials and manual webhook invocation

3. **Discord Webhook Delivers HIGH/MEDIUM Alerts**
   - **Test:** Configure real discord_webhook_url in contact-points.yml, trigger a HIGH alert (e.g., inject lag to trigger consumer_lag_writer alert)
   - **Expected:** Discord message posted to configured webhook URL with alert details
   - **Why human:** Requires real Discord webhook URL and manual alert triggering

4. **Roll Automation Restarts IBKR Provider**
   - **Test:** Publish roll_complete event to topic_roll_events, verify indicagent-ibkr-provider restarts
   - **Expected:** Service restarts within 10 seconds, SERVICE_AUDITOR_SERVICE_RESTARTS_TOTAL metric increments
   - **Why human:** Requires futures roll event simulation and systemctl verification

5. **DLQ Messages Reach Topics After CR-01 Fix**
   - **Test:** Fix producer.produce() → producer.publish(), send malformed payload to trigger DLQ routing, consume from DLQ topic
   - **Expected:** DLQ message appears in topic with structured DLQPayload
   - **Why human:** Requires code fix first, then manual Kafka consumption verification

### Gaps Summary

Phase 067 delivers substantial observability infrastructure (BaseAgent metrics, stall detection, Grafana dashboards, roll automation, market_data_gaps) but has **4 critical bugs** that break core functionality:

**Critical Failures:**
1. **CR-01:** DLQ routing broken - producer.produce() method doesn't exist, all DLQ messages fail silently
2. **CR-02:** Alert publishing broken - self._settings.env_name will fail with AttributeError for agents without _settings
3. **WR-07:** Grafana alert for signal drops references non-existent metric - will never fire
4. **WR-01:** Metrics port collision - LifecycleWriterAgent and SignalAuditorAgent both use :9128

**Incomplete Features:**
5. **Plan 067-02 Task 1:** Bootstrap retry implementation deferred (tests written, code not)
6. **Plan 067-05 Task 2:** LLMWriterService migration deferred (architectural incompatibility)
7. **Plan 067-06 Task 2:** Consumer lag reporting not implemented
8. **Plan 067-06 Task 3:** Grafana consumer lag panels not added

**Code Quality Issues:**
9. **WR-02:** BarAuditorAgent publishes duplicate gap requests when gap is resolved
10. **WR-03:** BaseAgent._send_to_dlq references private _topics_consumed instead of public property
11. **WR-08:** DLQ provisioning script creates 11/15 topics, 4 missing
12. **WR-06:** ParityAuditorAgent metrics split across two ports

**Recommendation:** Fix CR-01, CR-02, WR-07, WR-01 before considering phase complete. These 4 bugs break the core value propositions (DLQ routing, alert publishing, Grafana alerting, metrics availability). The remaining gaps are lower priority but should be tracked for follow-up work.

---

_Verified: 2026-04-13T22:30:00Z_
_Verifier: Claude (gsd-verifier)_
