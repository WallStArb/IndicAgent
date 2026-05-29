# Phase 109: Config Foundation & Self-Healing Engine - Peer Reviews

**Review Date:** 2026-05-28
**Reviewers:** Gemini CLI, Codex CLI, Claude CLI
**Status:** NEEDS_REVISION

---

## Executive Summary

All three reviewers identified **CRITICAL security gaps** in the self-healing webhook implementation and **MEDIUM-HIGH operational safety concerns** around config startup failures and outbox retry semantics.

The consensus: **Do not execute as written**. Fix security hardening, make config startup non-fatal, and resolve schema/category contradictions before implementation.

---

## Review by Gemini CLI

### Overall Assessment
**NEEDS_REVISION** — The architectural vision is sound and aligns well with Renaissance principles, but plans violate the "three-layer invariant" by including `category` in `config_schema`. There are gaps in systemd integration and configuration loading order.

### Plan-Specific Feedback

#### Plan 01: Config Foundation
- **Severity:** CRITICAL
- **Issues:** Schema includes `category` column in `config_schema`. Per project context, INFRA/STRUCT config must be in `.env` or deployment. Allowing `category` in the table makes it possible to programmatically insert and attempt to hot-reload INFRA keys via `ConfigService`.
- **Suggestions:**
  1. Remove `category` column from database schema entirely
  2. Enforce domain in `ConfigService._validate_key_domain()` by checking against hardcoded whitelist of allowed OPS prefixes

#### Plan 02: Config Service API
- **Severity:** HIGH
- **Issues:** API relies on single `config_service` instance without explicitly handling DatabaseManager pool lifecycle. Auth (Bearer token) is optional — should be mandatory for production.
- **Suggestions:** Ensure FastAPI startup/shutdown cleanly manage pool. Make auth mandatory.

#### Plan 03: BaseAgent Config Reload
- **Severity:** MEDIUM
- **Issues:** `ConfigConsumerMixin._load_config_snapshot()` called in `start()`. If database not ready or service restarts rapidly, could cause crash loop.
- **Suggestions:** Implement retry/exponential backoff in initial config load. Document behavior if initial load fails.

#### Plan 04: SelfHealingEngine
- **Severity:** MEDIUM
- **Issues:** `_execute_action` uses `subprocess.run` with potentially untrusted labels from `alert.labels`.
- **Suggestions:** Add strict input validation/allowlisting to `mountpoint` in `_delete_old_logs` and `unit` in `_restart_service`.

#### Plan 05: SelfHealingAgent
- **Severity:** LOW
- **Issues:** Plan mentions removing technical debt from `settings.py` but doesn't document migration path for existing services.
- **Suggestions:** Create `DeprecationWarning` path for legacy consumers.

### Cross-Cutting Concerns
- **Architecture:** Three-layer invariant needs code enforcement (prefix matching) not schema configuration
- **Security:** Remediation agent with systemd restart must be heavily restricted. Webhook should be localhost-only
- **Operations:** Add "force-reload" or "drain" signal for agents

### Recommendations
1. Remove `category` column from DB migration
2. Hard-code OPS key prefixes in `ConfigService` domain validation
3. Add strict input validation to `SelfHealingEngine` action executors

---

## Review by Codex CLI

### Overall Assessment
**BLOCKED** — The config foundation direction is good (OPS-only DB, INFRA in env, STRUCT in code, DB-plus-outbox pattern). However, **I would not execute these plans as written**. Fix schema/key contradictions, make config startup non-fatal, harden outbox semantics, and redesign self-healing security before implementation.

### Critical Findings

**1. CRITICAL: Self-healing webhook and actions are unsafe by default.**
- **109-04-PLAN.md:386** allows `find <mountpoint> -name *.log -mtime +7 -delete` using webhook label
- **109-04-PLAN.md:390** restarts arbitrary service from label
- **109-05-PLAN.md:122** exposes webhook without shared-secret auth promised in CONTEXT.md:50
- **Recommendation:** Require HMAC/shared-secret auth, strict allowlists for mountpoints and systemd units, dry-run mode first, non-blocking subprocess execution, bounded deletion paths, and explicit per-strategy enable config.

**2. CRITICAL: AI `shadow_only` migration can accidentally promote agents.**
- **109-05-PLAN.md:286** changes class defaults to `False`, while current base default is deliberately `True` in base_agent.py:77
- Swarm already treats `shadow_registry` as source of truth in alpha_swarm_agent.py:190
- If config load fails or unavailable, this is fail-open for live decisions
- **Recommendation:** Keep fail-closed `shadow_only=True`, migrate through existing `shadow_registry` or make config read secondary override only after successful load.

**3. HIGH: Schema/category model is internally contradictory.**
- Context says `config_schema` includes `category` for INFRA/STRUCT/OPS (CONTEXT.md:23)
- Plan 01 removes `category` for OPS-only (109-01-PLAN.md:80)
- Plan 05 inserts `category: 'OPS'` into that same table (109-05-PLAN.md:208)
- **Recommendation:** Pick one invariant. Prefer OPS-only DB with no category, then remove all category references and API category params.

**4. HIGH: Key-domain validation rejects planned migrated keys.**
- Plan 01 allows only `regime.`, `swarm.`, `alert.`, `ai.`, `feature.`, `threshold.` (109-01-PLAN.md:167)
- Plan 05 migrates `roll.`, `cross_asset.`, and `macro.` keys (109-05-PLAN.md:191)
- **Recommendation:** Validate against registered `config_schema` rows plus explicit `hot_reloadable=true` invariant, or add all planned OPS prefixes.

**5. HIGH: Optimistic concurrency is not actually safe as specified.**
- Plan 01 says fetch current state for version check before starting transaction, then later start transaction (109-01-PLAN.md:190)
- A `FOR UPDATE` lock outside a transaction is ineffective after statement completes
- **Recommendation:** Perform schema read, current-state `SELECT ... FOR UPDATE`, version check, history insert, state upsert, and outbox insert inside one transaction.

**6. HIGH: Outbox dispatcher violates retry and ordering guarantees.**
- Plan 02 selects pending rows with `FOR UPDATE SKIP LOCKED` but does not define DB transaction or pool setup (109-02-PLAN.md:202)
- Marks publish failures as terminal `failed` (109-02-PLAN.md:217), conflicting with retry guarantees in CONTEXT.md:40
- **Recommendation:** Claim rows transactionally with `pending -> publishing`, include retry count/next_attempt/error, retry with backoff, and preserve `changed_by`, `reason`, `redacted`, `correlation_id` from original change.

**7. HIGH: BaseAgent integration can take down all services when config infra is unhealthy.**
- Plan 03 adds DB snapshot and Kafka config consumer to every BaseAgent startup (109-03-PLAN.md:151)
- Current startup treats setup failure as fatal (base.py:228), conflicts with "last-known-good" and fail-open tuning behavior in CONTEXT.md:80
- **Recommendation:** Make config consumption opt-in or non-fatal, use service-local defaults/LKG cache, and emit stale metrics when unavailable.

**8. HIGH: Self-healing strategy lookup and enablement are broken.**
- Strategies keyed as `disk_usage_high`, etc. (109-04-PLAN.md:166)
- Execution looks up `REMEDIATION_STRATEGIES.get(alert.state_variable)` (109-04-PLAN.md:349)
- For `disk_usage` alert, no strategy is found
- No plan to enable strategies from config
- **Recommendation:** Map Alertmanager alert name or state variable consistently, store `strategy.enabled.*` in OPS config, and load it fail-closed.

**9. MEDIUM: Materialized success-rate view will be stale.**
- Plan 04 queries `remediation_success_rates` (109-04-PLAN.md:264) but never refreshes it
- Auto-disable can act on stale or empty data
- **Recommendation:** Use live aggregate query for decisions, or refresh concurrently on schedule; require minimum sample count before disabling.

**10. MEDIUM: Planned settings migration is too broad and will break call sites.**
- Existing settings fields actively used (settings.py:146 through settings.py:194)
- `Settings.get_config_value()` classmethod cannot access per-agent hot-reload cache as written (109-05-PLAN.md:200)
- **Recommendation:** Migrate consumers incrementally to `BaseAgent.get_config()` with typed defaults, leaving `settings.py` compatibility fields until each call site is converted and tested.

**11. MEDIUM: Kafka compacted topic is asserted, not provisioned.**
- Plans require compacted `topic_config_updates` (CONTEXT.md:69) but only add topic-name function (109-02-PLAN.md:167)
- **Recommendation:** Add explicit topic creation/provisioning with `cleanup.policy=compact`, appropriate partitions, replication, and ACLs.

**12. LOW: Verification steps contain false positives.**
- Plan 01 tests `set('regime.test_key')` as valid (109-01-PLAN.md:212) but validation requires `config_schema` row
- Plan 05 webhook test omits required fields while expecting 200 (109-05-PLAN.md:166)
- **Recommendation:** Align tests with schema validation and include negative tests.

---

## Review by Claude CLI

### Overall Assessment
**NEEDS_REVISION** — Plans are well-structured and follow Renaissance design principles, but have security and operational safety gaps. Three-layer config invariant is mostly enforced but has one inconsistency.

### Plan-Specific Feedback

| Plan | Severity | Key Issues |
|------|----------|------------|
| 109-01 | LOW | Seed data transaction handling, PK timestamp precision |
| 109-02 | HIGH | Bearer token optional, webhook secret not verified |
| 109-03 | HIGH | Idempotency cache not persistent, no stale config detection |
| 109-04 | HIGH | No webhook auth, systemd restart authorization, Prometheus query failure handling |
| 109-05 | LOW | Settings.get_config_value circular dependency risk |

### Cross-Cutting Concerns

**Security (HIGH - gaps found):**
- Config API auth: ⚠️ WEAK — Bearer token optional
- Webhook auth: ❌ MISSING — No shared secret verification
- Secret redaction: ✓ GOOD
- SQL injection: ✓ GOOD
- Audit trail: ✓ GOOD

**Operational Safety (HIGH - gaps found):**
- Idempotency: ⚠️ PARTIAL — In-memory only, lost on restart
- Failure modes: ⚠️ PARTIAL — DB pool exhaustion not handled
- Circuit breaker: ✓ GOOD
- Rate limiting: ✓ GOOD
- Auto-disable: ✓ GOOD
- Rollback: ✓ GOOD

**Renaissance Three-Layer Invariant (MINOR):**
- INFRA: ✓ GOOD
- STRUCT: ✓ GOOD
- OPS: ⚠️ INCONSISTENT — API has ignored `category` param

**Technical Correctness (GOOD):**
- DB schema: ✓ CORRECT
- Kafka: ✓ CORRECT
- systemd: ✓ CORRECT
- API: ✓ CORRECT
- Metrics: ✓ CORRECT

### Top 3 Recommendations

**1. Add Webhook Authentication (CRITICAL)**
```python
async def handle_webhook(self, payload: dict[str, Any]) -> RemediationResult:
    expected = os.getenv("CONFIG_WEBHOOK_SHARED_SECRET")
    if expected and payload.get("webhook_secret") != expected:
        WEBHOOK_VALIDATION_FAILED_TOTAL.add(1, {"reason": "auth_failed"})
        raise HTTPException(status_code=401, detail="Invalid webhook secret")
```

**2. Fix Config API Auth or Document Optional-Only-For-Dev (HIGH)**
```python
# Change from "Bearer token auth: Optional header"
# To: "Bearer token auth: MANDATORY if CONFIG_API_TOKEN set, reject 401 if missing"
```

**3. Document Idempotency Limitation (MODERATE)**
```python
# Idempotency: alert_id tracking is in-memory only
# - Duplicate alerts within same session are ignored
# - After restart, duplicate alert_id may be re-processed
# - Remediation actions are designed to be safe on re-execution
```

---

## Consensus Findings

All three reviewers agree on these issues:

| Issue | Severity | Found By |
|-------|----------|----------|
| Webhook auth missing | CRITICAL | All 3 |
| Config API auth too weak | HIGH | All 3 |
| Schema/category contradiction | HIGH | Gemini, Codex |
| Strategy lookup broken | HIGH | Codex, Claude |
| Idempotency session-only | MEDIUM | Claude |
| BaseAgent startup fatal on config failure | HIGH | Codex, Claude |

---

## Required Actions Before Execution

1. **CRITICAL — Add webhook shared secret authentication** to Plan 04 Task 4
2. **HIGH — Make Config API auth mandatory** or bind to localhost-only in Plan 02
3. **HIGH — Fix strategy lookup bug** in Plan 04 (map state_variable to strategy keys)
4. **HIGH — Resolve schema/category contradiction** (remove category or make consistent)
5. **HIGH — Make BaseAgent config startup non-fatal** with last-known-good fallback
6. **MEDIUM — Add all planned OPS prefixes** to key-domain validation (roll., cross_asset., macro.)
7. **MEDIUM — Add materialized view refresh** for remediation_success_rates

---

## Review Metadata

- **Gemini CLI:** Version 0.42.0, model gemini-3.1-flash-lite-preview (rate-limited)
- **Codex CLI:** Version 0.128.0, model gpt-5.5 (research preview)
- **Claude CLI:** Version not specified, Opus 4.7 equivalent

---

*Reviews generated: 2026-05-28*
*Next action: Address CRITICAL and HIGH findings before /gsd-plan-phase convergence loop*
