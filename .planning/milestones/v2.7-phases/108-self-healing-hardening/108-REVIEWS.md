---
phase: 108
reviewers: [codex]
reviewed_at: 2026-05-28T10:45:00Z
plans_reviewed:
  - 108-01-PLAN.md
  - 108-02-PLAN.md
  - 108-03-PLAN.md
  - 108-04-PLAN.md
  - 108-05-PLAN.md
  - 108-06-PLAN.md
  - 108-07-PLAN.md
notes: >
  Gemini produced execution-mode output (not a review).
  Ollama (qwen3.5:4b) timed out / not available for review.
  Codex review is the authoritative finding.
---

# Cross-AI Plan Review — Phase 108

## Codex Review

## Overall Summary

The phase plan is well-structured and mostly achieves Phase 108's stated goals: watchdog rollout, OTel health coverage, DLQ quarantine, stuck consumer visibility, CB-open observability, API health, and SOP closure. The best parts are the explicit dependency waves, clear locked decisions, avoidance of new Kafka health topics, and concrete acceptance checks. The largest risks are operational: plans assume sudo/systemd/DB access, restart live services, mutate `/etc/systemd/system`, and run live migrations without an explicit deployment guardrail or rollback strategy. There are also a few correctness issues around OTel export from short-lived oneshot jobs, DLQ quarantine semantics, FastAPI lifespan DB access, and watchdog rollout ordering.

## Plan 01 - OTel Foundation

**Strengths**
- Good Wave 1 placement. Downstream plans depend on these instruments.
- Correctly separates BaseAgent watchdog counters from shared `metrics.py` instruments.
- Acceptance criteria are concrete and import-based.
- Keeps label responsibility at call sites.

**Concerns**
- **MEDIUM:** `BaseAgent._watchdog_notify()` increments `watchdog_notify_total` after `notifier.notify()` without catching notify errors. If sd_notify raises, the task may die silently depending on task handling.
- **MEDIUM:** "No duplicate-instrument warnings" is hard to enforce with simple imports if other modules initialize OTel globally.
- **LOW:** Plan adds `JOB_COMPLETED_TOTAL` before confirming oneshot OTel flush behavior. Short-lived jobs may exit before OTLP export flushes.

**Suggestions**
- Wrap `notifier.notify("WATCHDOG=1")` in minimal error handling if current BaseAgent task policy does not already surface task exceptions.
- Add a note for oneshots to flush/shutdown the OTel provider before process exit.
- Verify existing metric naming convention allows global names like `api_health` rather than `indicagent_api_health`.

**Risk Assessment:** LOW-MEDIUM. The changes are small and foundational, but watchdog task failure behavior should be checked.

## Plan 02 - systemd WatchdogSec Rollout

**Strengths**
- Correctly excludes dashboard and oneshots.
- Adds both `WatchdogSec=60` and `NotifyAccess=main`, which is essential.
- Good post-change verification with `systemd-analyze verify`.
- Restart order is thoughtful, with lower-criticality services first.

**Concerns**
- **HIGH:** The plan assumes live sudo/systemd access and restarts 25 production services. That is operationally risky for a single execute plan.
- **HIGH:** Plan 02 is Wave 1 and independent from Plan 01, but runtime success depends on Plan 01 code being deployed and services running code that emits sd_notify. If Plan 02 lands before BaseAgent changes are deployed, watchdog visibility may be incomplete, and non-BaseAgent services may cycle.
- **MEDIUM:** `sudo cp production/systemd/indicagent-*.service /etc/systemd/system/` copies all units, not just the 25 modified ones. This could overwrite unrelated local/system-specific unit changes.
- **MEDIUM:** "Wait 70s after each restart" makes the plan long and fragile. It also does not explicitly capture a pre-task failed-unit baseline.
- **LOW:** Count mismatch appears in the context: roadmap says 27, research says 25. The plan adopts 25 but should explicitly reconcile the discrepancy.

**Suggestions**
- Split source edits from live installation/restarts, or require an explicit deployment window.
- Copy only the 25 modified unit files, not the full glob.
- Capture pre-change `systemctl list-units --failed 'indicagent-*'` before restarts.
- Make Plan 02 depend on Plan 01 deployment, not just source completion.
- Add `systemctl show ... -p NotifyAccess -p WatchdogUSec` verification for a representative sample.

**Risk Assessment:** HIGH. The file edits are low risk, but live fleet restart plus `/etc/systemd/system` overwrite is the riskiest operation in the phase.

## Plan 03 - DLQ Quarantine

**Strengths**
- Correctly honors D-22: no new Kafka topic.
- Migration is idempotent and narrowly scoped.
- Adds useful index for query/read paths.
- Quarantine metric is tied to actual quarantine events.

**Concerns**
- **HIGH:** In-memory counting does not survive DLQDrainAgent restart. Poison pills spread across restarts may never quarantine, despite `dlq_events` having persistent history.
- **MEDIUM:** "After >= 3 identical errors" vs implementation `count > 3` means the 4th message is quarantined. The text and acceptance criteria disagree.
- **MEDIUM:** Keying by `(agent, source_topic, error_type)` may quarantine unrelated payloads with the same broad error type. The requirement says poison-pill quarantine, but this groups by class of error, not message identity.
- **MEDIUM:** Live DB migration is embedded in an autonomous plan. That should have backup/transaction/rollback notes, even if HEAL-02 backup is deferred.
- **LOW:** Label uses `agent`, while the broader convention says `agent_id`. This may be intentional for DLQ domain metrics, but the plan should state why.

**Suggestions**
- Prefer DB-backed counting over pure memory: count prior rows in last 24h for the same key, or initialize the in-memory window from DB at startup.
- Decide explicitly whether quarantine starts at the 3rd or 4th occurrence. If requirement says "exceeding 3," use 4th; if "after >= 3," use 3rd.
- Consider including a stable payload hash or error fingerprint if "poison pill" means repeated same payload.
- Add migration rollback guidance: dropping index/column may not be safe, but document the forward-only recovery.

**Risk Assessment:** MEDIUM-HIGH. Implementation is simple, but semantics may not fully prevent infinite retry loops after restarts.

## Plan 04 - ServiceAuditor + Pipeline CB + E2E Latency

**Strengths**
- Good placement after Plan 01.
- Stuck-consumer counter is inserted at the right point: warning before restart.
- Avoids Kafka health events, consistent with D-01/D-19.
- Adds a single end-to-end latency metric rather than replacing stage metrics.

**Concerns**
- **MEDIUM:** Direct access to `self._executor._plugin_circuit_breakers` is brittle. The research recommended a property as the cleaner approach, but the plan chooses private access.
- **MEDIUM:** `cb.failures` may not be the actual attribute name or public state. If wrong, the CB logging block could break the whole bar loop.
- **MEDIUM:** Reusing `pipeline_latency_ms` as "bar arrival to signal enqueue" may be semantically inaccurate if the timer starts after bar receipt or ends before Kafka write/enqueue.
- **MEDIUM:** Lowering stall threshold to 120s may restart slow-but-healthy services if message rates are naturally sparse for some agents.
- **LOW:** Per-bar scan over all plugin breakers is probably fine, but it should be guarded so logging logic cannot fail bar processing.

**Suggestions**
- Add a `PluginExecutor.circuit_breakers` read-only property rather than using the private attribute.
- Wrap CB scan in a small defensive helper so an unexpected CB object shape logs but does not fail `_process_bar_compute`.
- Verify actual latency boundaries before naming the metric `bar_e2e_latency_ms`; otherwise rename to match reality.
- Review expected idle/message cadence per service before globally applying 120s stall threshold.

**Risk Assessment:** MEDIUM. The observability additions are reasonable, but private attribute access and timing semantics need tightening.

## Plan 05 - FastAPI OTel + API Health

**Strengths**
- Uses official FastAPI instrumentation rather than custom middleware.
- Correctly identifies stale gauge risk and adds background refresh.
- Updates both background task and `/health/database` endpoint.
- Verifies HTTP metric family names with fallback for version differences.

**Concerns**
- **HIGH:** The plan specifies `uv pip install ...` during execution. That mutates the environment outside source control and may diverge from deployment. Requirements update should drive install through normal deployment.
- **MEDIUM:** The described DB connection lifecycle may be wrong depending on the connection manager API. "close the connection" may break pooled connections if the local pattern expects release/context manager.
- **MEDIUM:** Background task sleeps at the end only. If DB checks hang, the loop can stall indefinitely unless the DB manager has timeouts.
- **MEDIUM:** If `FastAPIInstrumentor().instrument_app(app)` is run more than once across reload/import patterns, duplicate instrumentation can occur.
- **LOW:** Logging every failed 30s DB health check at warning can become noisy during known outages.

**Suggestions**
- Remove direct package installation from the implementation plan or mark it as deployment-only.
- Follow the repo's existing DB connection pattern exactly, preferably via a shared health-check helper used by both lifespan and endpoint.
- Add a timeout around `SELECT 1`.
- Make instrumentation idempotent if the app is imported in tests or reload mode.
- Consider rate-limited warning logs for repeated DB health failures.

**Risk Assessment:** MEDIUM. The design is sound, but environment mutation and DB connection handling are likely failure points.

## Plan 06 - Oneshot Completion Counters

**Strengths**
- Addresses a real visibility gap for timer-triggered jobs.
- Preserves existing roll-batch counters.
- Correctly uses kebab-case job labels matching unit suffixes.
- Keeps exception propagation so systemd still sees failures.

**Concerns**
- **HIGH:** Short-lived oneshot processes may exit before OTel exports the counter. Without an explicit flush/shutdown, `job_completed_total` may never reach the collector.
- **MEDIUM:** Wrapping top-level script bodies can accidentally alter cleanup ordering or double-log exceptions if existing entrypoints are complex.
- **MEDIUM:** "Before final resource teardown" is not always the right place. If teardown fails after success counter is emitted, the job may report success and exit failure.
- **LOW:** The plan covers only three oneshots, while context mentions more oneshot units. That may be intentional, but it should be explicitly justified.

**Suggestions**
- Emit success only after all critical work and required cleanup have completed.
- Add an OTel force-flush/shutdown step after adding the counter, if the project's OTel provider exposes one.
- Audit all Type=oneshot units and document why only these three get counters in Phase 108.
- Prefer minimal edits around existing `main()` return/exception boundary.

**Risk Assessment:** MEDIUM-HIGH. The biggest issue is metrics loss on process exit.

## Plan 07 - Documentation, HYGIENE-07 Audit, HEAL-02 Deferral

**Strengths**
- Good closeout plan: records SOP, audit, and explicit deferral.
- Correctly treats HYGIENE-07 as verification if research is accurate.
- HEAL-02 deferral is documented instead of silently ignored.
- Grafana SLO list is practical and tied to phase metrics.

**Concerns**
- **MEDIUM:** Version bump rule for `CLAUDE.md` may conflict with the file's actual versioning scheme.
- **MEDIUM:** The HYGIENE audit command can miss daemon scripts whose service unit name does not map cleanly to `services/*.py`.
- **LOW:** Documentation depends on all previous plans completing; if one slips, CLAUDE.md may overstate reality.

**Suggestions**
- Generate the daemon-to-script mapping from `ExecStart` in `production/systemd/*.service`, not just filename assumptions.
- In CLAUDE.md, say "new daemon services must inherit BaseAgent or implement the full equivalent health contract" to cover exceptional non-Python daemons.
- Link deferral to a backlog item or requirement status so it remains trackable.
- Only write "Phase 108 closed..." after verification summaries exist.

**Risk Assessment:** LOW-MEDIUM. Mostly documentation, but the audit should be robust enough to avoid false closure.

## Design Decision Review

Most locked decisions are sound. D-01/D-02 are especially strong: using OTel/Prometheus/Grafana as the single health plane prevents split-brain monitoring. D-08/D-09 are correct exclusions for dashboard and oneshots. D-22 is pragmatic because a dead-final Kafka topic without a re-delivery loop is mostly cosmetic.

The weaker decisions are D-20 and D-23. D-20's in-memory DLQ counter is not durable enough for a self-healing guarantee unless initialized from DB or backed by DB queries. D-23's 120s stall threshold should be validated against real service message cadence before rollout. D-06 also needs an export-flush requirement for oneshots, otherwise the metric contract may be unreliable.

---

## Consensus Summary

*Single authoritative reviewer: Codex*

### Agreed Strengths

- Wave dependency structure is well-organized (01 foundational, 02-06 parallel, 07 closeout)
- OTel-only health plane (D-01) is the right architectural decision — no split-brain monitoring
- Locked decisions are explicit and well-reasoned, especially D-22 (no dead-final Kafka topic)
- Concrete, machine-checkable acceptance criteria throughout
- DLQ quarantine and CB logging correctly honor the "no new Kafka topics" constraint

### Top Concerns (Priority Order)

1. **HIGH — Plan 06 + Plan 01 (OTel flush for oneshots):** Short-lived oneshot processes may exit before OTLP exports `job_completed_total`. An explicit `provider.force_flush()` / `provider.shutdown()` is needed after counter increment.
2. **HIGH — Plan 03 (DLQ in-memory state lost on restart):** In-memory occurrence counter resets on `DLQDrainAgent` restart. Poison pills that arrived before the restart will never quarantine. Fix: initialize count from recent `dlq_events` rows on startup.
3. **HIGH — Plan 02 (live fleet restart risk):** `sudo cp indicagent-*.service /etc/systemd/system/` overwrites all unit files, not just the 25 modified ones. Capturing pre-change failed-unit baseline and copying only modified files reduces blast radius.
4. **MEDIUM — Plan 04 (private `_plugin_circuit_breakers` access):** Accessing private attribute directly is brittle. A `PluginExecutor.circuit_breakers` read-only property is the right fix. CB scan must also be wrapped defensively so it cannot break bar processing.
5. **MEDIUM — Plan 05 (`uv pip install` during execution):** Runtime package install mutates the venv outside source control. Add to `requirements.txt` and let normal deployment handle it.

### Divergent Views

None — single reviewer. Execute with the HIGH concerns addressed via plan revisions.
