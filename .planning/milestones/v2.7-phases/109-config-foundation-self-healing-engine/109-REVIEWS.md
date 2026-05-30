---
phase: 109
reviewers: [gemini, codex]
reviewed_at: 2026-05-29T00:00:00Z
plans_reviewed: [109-01-PLAN.md, 109-02-PLAN.md, 109-03-PLAN.md, 109-04-PLAN.md, 109-05-PLAN.md]
prior_review: 2026-05-28 (NEEDS_REVISION — security, category invariant, non-fatal startup)
prior_issues_resolved: true
---

# Cross-AI Plan Review — Phase 109 (Revised Plans)

> These plans were previously reviewed on 2026-05-28 and flagged NEEDS_REVISION due to security gaps, category column in config_schema, and fatal config startup failures. Plans were revised in commits c4ebd880 and b0975f65. This is the post-revision review.

---

## Gemini Review

### Summary
The revised plans for Phase 109 demonstrate a significant improvement in addressing prior feedback, particularly regarding transactional safety, auditability, and defense-in-depth security. The separation of concerns between config management, outbox dispatching, and self-healing is clean. The overall design correctly follows the platform's "Shadow Mode" and "Fail-Closed" defaults. However, the performance implications of the decentralized config-reload architecture on the 23+ agents and the operational complexity of managing the remediation strategies (specifically the Prometheus dependency) require careful validation.

### Strengths
- **Transactional Integrity:** Using `SELECT ... FOR UPDATE` and a formal outbox pattern ensures configuration consistency across the DB and Kafka bus.
- **Fail-Closed/Non-Fatal Design:** The "NON-FATAL" config loading with last-known-good caching is an excellent safety pattern for a high-frequency environment.
- **Security:** Defense-in-depth approach (auth at API and Webhook/Engine layers) and explicit redaction of secret logs align well with production-grade security.
- **Clean Separation:** Separating INFRA, STRUCT, and OPS layers prevents accidental runtime corruption of critical service definitions.
- **Auditability:** The `remediation_ledger` and `config_history` hypertables provide essential diagnostic data for post-mortems.

### Concerns
- **MEDIUM: Prometheus Dependency** — The self-healing engine queries `localhost:9090` to measure state. If Prometheus is slow or unreachable, the remediation logic could trigger incorrectly or fail silently.
- **MEDIUM: Config Reload Storms** — With 23+ agents subscribing to a compacted `config.updates` topic, a bulk update (e.g., changing a global threshold) could trigger a concurrent reload storm. While non-fatal, this could cause transient CPU spikes or log spam.
- **MEDIUM: Migration Safety** — Removing 15 params from `settings.py` while services are live is high-risk. The plan mentions a deprecation warning, but does not explicitly detail a "hybrid-read" period where agents fall back to `settings.py` if the config DB is unreachable or empty.
- **LOW: Remediation Idempotency** — Using an in-memory set for idempotency resets on restart. If an agent flaps, it could repeatedly trigger the same remediation action.
- **LOW: No-Op Strategies** — The `_flush_db_pools` strategy is `pass`. This needs to be explicitly documented as "Unimplemented" to prevent confusion during debugging.

### Suggestions
- Introduce a `ConfigFallbackLoader` that explicitly checks `settings.py` as a "level 2" fallback before falling back to hardcoded defaults, explicitly removed in a subsequent phase.
- Add a `CONFIG_RELOAD_LATENCY` metric to track if agents are falling behind the update stream.
- Consider adding a `last_remediation_timestamp` column or dedicated state table to persist rate limiting history across service restarts.
- Ensure `CONFIG_WEBHOOK_SHARED_SECRET` can be rotated without restarting the system.

### Risk Assessment
**MEDIUM** — The core architecture is sound. The primary risk is in the operational transition: the decentralized reload mechanism, if not carefully implemented, could stress downstream consumers during large config changes. The settings migration is a high-touch task requiring rigorous verification.

**Prior feedback resolved?** Yes. Transactional outbox correctly implemented; auth explicitly handled; fail-closed defaults maintained.
**Plan completeness?** Yes, the 5-wave structure covers all success criteria.
**Dependency order?** Logical and correct.

---

## Codex Review

### Summary
The revised plans are materially stronger and appear to address most of the prior architectural concerns: OPS-only config schema, transactional outbox, optimistic concurrency, fail-closed shadow mode, non-fatal config startup, and disabled-by-default remediation are all aligned with the stated principles. The phase is still moderately risky because it spans DB schema, HTTP APIs, Kafka propagation, BaseAgent lifecycle changes, runtime parameter migration, and self-healing automation in one phase. The largest remaining concerns are operational correctness around config reload semantics, migration safety while removing settings, self-healing idempotency/rate limiting durability, and the unclear Prometheus/localhost dependency.

### Strengths
- The three-layer config model is now much cleaner: `config_schema` is OPS-only and rejects INFRA/STRUCT keys early.
- Transactional outbox is the right pattern for config propagation and avoids treating Kafka as source of truth.
- Optimistic concurrency with `expected_version` is appropriate for operator-facing config changes.
- Non-fatal config startup is correctly aligned with platform resilience.
- Fail-closed `shadow_only=True` default for AI agents is the right safety posture.
- Outbox claiming with `FOR UPDATE SKIP LOCKED` is a solid design for horizontal dispatcher safety.
- Remediation strategies `enabled=False` by default prevents accidental automation.
- `REFRESH CONCURRENTLY` plus unique index for materialized view is explicitly planned.
- Input validation for remediation actions (mountpoint allowlist, systemd unit prefix) is a good security boundary.
- Replacing `_LAG_THRESHOLDS` with config-backed thresholds directly addresses a stated success criterion.

### Concerns
- **HIGH: BaseAgent lifecycle ordering may be wrong** — Wave 3 says startup order is `await self._setup()` then config snapshot. If service `_setup()` needs OPS config to initialize thresholds, feature flags, or clients, this defeats config-at-startup. Consider loading snapshot before service-specific setup, while still making it non-fatal.
- **HIGH: Removing 15 settings values may break services before config DB is populated** — Config startup is non-fatal but defaults must still exist somewhere in code, or every migrated setting needs a config-backed accessor with a local fallback. The plan's deprecation warning path returns `default` (None) which is not a safe fallback for numeric thresholds.
- **HIGH: Self-healing idempotency and rate limiting are only in-memory** — A restart can replay the same Alertmanager alert and reset hourly limits. Since `remediation_ledger` exists, it should participate in dedupe and rate limiting.
- **HIGH: `_flush_db_pools` as a no-op is not acceptable if advertised as a success criterion** — If pool flush is listed as criterion 6, `pass` means the plan does not fully meet it. Either implement it, explicitly stub behind `enabled=False` with a tracked TODO, or remove from claimed scope.
- **MEDIUM: ConfigService port mismatch** — Success criteria say port `9001`; Wave 3 systemd units use `9005` for config-service. API vs metrics port convention needs to be explicit and consistent.
- **MEDIUM: 100ms outbox polling is unnecessarily aggressive** — Consider `LISTEN/NOTIFY` plus polling fallback, or adaptive backoff when no rows are pending.
- **MEDIUM: 23+ agents subscribing to config topic — reload filtering matters** — Every agent should ignore irrelevant keys cheaply and avoid expensive reload work on every config update.
- **MEDIUM: Kafka compacted topic behavior needs operational details** — Topic creation/config, cleanup policy, tombstone handling, replay behavior for new consumers.
- **MEDIUM: Prometheus measurement via `localhost:9090` is brittle** — Architecture uses OTel SDK. Should be config-driven and fail-safe if unavailable.
- **MEDIUM: Double webhook auth needs clarity** — If engine can be called independently, defense-in-depth is valid. Otherwise document why both layers exist.
- **MEDIUM: Config validation type coercion underspecified** — JSON handling, boolean parsing, numeric precision, nullability need explicit treatment.
- **LOW: `depends_on` column semantics are unclear** — If not enforced, avoid the column to prevent operator confusion.
- **LOW: Materialized view refresh cadence is unclear** — When does `refresh_success_rates()` run and can it lag decisions?
- **LOW: Alertmanager payload handling underspecified** — Grouped alerts, resolved alerts, repeated notifications, fingerprints.

### Suggestions
- Load config snapshot before service-specific `_setup()` where feasible, or add a two-phase hook: base config load → service setup → Kafka subscription.
- Keep migrated runtime defaults as code-level fallback constants during the migration window. Do not remove old settings until all callers are migrated.
- Use `remediation_ledger` for durable idempotency and rate limiting.
- Either implement DB pool flush through a real service endpoint or mark the strategy as explicitly unsupported in Phase 109.
- Make ports explicit: Config API `9001`, Self-healing API `9002`, metrics ports `9005`/`9007` (document as metrics-only).
- Replace 100ms outbox polling with adaptive polling: 100ms while backlog exists, back off to 1-5s when idle.
- Define config update event contract explicitly (key, value, version, timestamp, actor, operation, schema version).
- Make Prometheus URL a config key or env var, not hardcoded `localhost:9090`. Fail closed if unavailable.
- Add migration rollout order: apply DB migration first → deploy config service/outbox → deploy BaseAgent reload → migrate consumers away from settings.

### Risk Assessment
**MEDIUM-HIGH** — Design direction is sound and most previous issues appear resolved, but the phase touches several foundational paths at once. Highest-risk areas: service startup ordering, safe migration away from `settings.py`, and remediation correctness. With staged rollout, compatibility fallbacks, and durable remediation controls, reducible to **MEDIUM**.

---

## Consensus Summary

Both reviewers confirm the prior NEEDS_REVISION issues are resolved. The revised plans are solid enough to execute.

### Agreed Strengths
- Transactional outbox with `SELECT ... FOR UPDATE` is the right consistency model
- OPS-only config schema (no category column) is correct
- Non-fatal config startup (fail-closed defaults) is production-safe
- `shadow_only=True` class default with explicit config promotion is the right safety posture
- Remediation strategies `enabled=False` by default prevents accidental automation
- Defense-in-depth auth (API Bearer + webhook shared secret)

### Agreed Concerns (Highest Priority)

**MEDIUM-HIGH: Migration safety for removed settings.py params**
Both reviewers flag this. The deprecation path in `Settings.get_config_value()` returns `None` as default — numeric thresholds like `REGIME_PROB_MIN=0.30` need real fallback constants, not `None`. The config DB must be populated before settings are removed.
→ **Action:** Keep all removed settings as module-level constants (prefixed `_DEFAULT_*`) during the migration window. `get_config_value()` falls back to these constants, not `None`. Constants removed in Phase 110.

**MEDIUM: Prometheus hardcoded at localhost:9090**
Both reviewers flag this as brittle. Should be an OPS config key or env var, and self-healing should fail-closed (record measurement failure) if unavailable.
→ **Action:** Read Prometheus URL from env (`PROMETHEUS_URL`, default `http://localhost:9090`). On connection failure, return 0.0 and log warning — do not trigger remediation on measurement failure.

**MEDIUM: In-memory idempotency and rate limiting reset on restart**
Both reviewers flag this. The `remediation_ledger` already exists — use it.
→ **Action:** On startup, `SelfHealingEngine` loads `_processed_alerts` from `remediation_ledger` for the last 24 hours. Rate limiting queries `remediation_ledger` for count in last hour per strategy.

**MEDIUM: BaseAgent startup ordering (Codex HIGH)**
If `_setup()` needs OPS config values (e.g., threshold flags), loading config snapshot after `_setup()` defeats the purpose.
→ **Action:** Split `start()` into: `_pre_setup_config_load()` (non-fatal snapshot) → `await self._setup()` → `_setup_config_consumer()`. This way OPS config is available during service setup.

### Agreed LOW Concerns
- `_flush_db_pools` as `pass` — should be explicitly marked in code with a `# TODO Phase 110` comment and `enabled=False` in the registry
- Config reload filtering: agents should check if a Kafka key is in their relevant prefix set before doing any reload work

### Divergent Views
- **Port confusion:** Codex caught a mismatch between success criteria (port 9001) and Wave 3 systemd units (port 9005). Gemini did not flag this. Resolution: 9001 = Config API HTTP, 9005 = Config Service OTel metrics. Plans should make this explicit.
- **Outbox polling frequency:** Codex recommends adaptive backoff; Gemini did not flag. 100ms is fine for initial implementation given low config change frequency — add backoff only if DB load becomes measurable.
