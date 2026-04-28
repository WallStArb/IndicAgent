# Phase 73: AI LLM Layer B+ Architecture Refactor - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-04-28
**Phase:** 73-ai-llm-layer-b-architecture-refactor
**Areas discussed:** ShadowRecorder vs TransformRecorder overlap, Phase 73 vs 75 execution order, LLM chain fixes verification, Plan consolidation 9→6, Extension hooks scope

---

## ShadowRecorder vs TransformRecorder Overlap

| Option | Description | Selected |
|--------|-------------|----------|
| Unified lineage (institutional) | Merge both tables into one signal_lineage. Single recorder, Kafka-first, event-sourced. | ✓ |
| Keep both, Kafka ShadowRecorder | Keep both tables. Move ShadowRecorder to Kafka (DAG-correct). | |
| No recorder changes | Keep everything as-is (direct DB for both). | |

**User's choice:** Unified lineage (institutional)
**Notes:** User asked "what would be the most institutional and future proof? what would Robinhood build or Renaissance or other professional firms?" — drove the decision toward event-sourced unified audit trail. ShadowRecorder captures agent predictions (3 rows/signal), TransformRecorder captures pipeline transforms (9 rows/signal) — they capture different data but belong in one immutable lineage table.

---

## Phase 73 vs 75 Execution Order

| Option | Description | Selected |
|--------|-------------|----------|
| 73 first, then 75 | Phase 73 reorganizes infrastructure first. Phase 75 builds governance on top. | ✓ |
| Merge into single run | Run both as one combined execution. | |
| 75 first, then 73 | Phase 75 patches current structure, then Phase 73 reorganizes. | |

**User's choice:** 73 first, then 75
**Notes:** User confirmed "I would think 73 first then 75." Phase 75 references file paths and class names that Phase 73 moves/renames — running 75 first would require rework. Phase 75 needs minor adjustments after 73 (signal_transform_log → signal_lineage, updated file paths).

---

## LLM Chain Fixes After OllamaCloud Addition

| Fix Target | Current State | Still Needed |
|-----------|---------------|--------------|
| Cache key `[:200]` | `semantic_cache.py:23` still truncates | Yes |
| Rate limiter pre-acquire | No `await acquire()` before dispatch | Yes |
| Guardrails dead branch | `chain.py:140` conditional check | Yes |
| Auto-audit to Kafka | Not implemented | Yes |
| Real token counts | No usage metadata extraction | Yes |
| WatchdogSec in systemd | Present in swarm-orchestrator unit | Yes |

**User's choice:** Confirmed all 6 fixes still apply
**Notes:** OllamaCloud addition (April 27) only extended `_build_providers()` with 3 cloud models. None of the fix targets affected. Rate limiter now covers 3 provider types (OpenRouter, OllamaCloud, OllamaLocal) — same fix pattern applies.

---

## Plan Consolidation: 9 → 6 Coverage Check

**Finding:** Reviews file references 73-01 through 73-09 but only 73-01 through 73-06 exist. Mapping:

| Original Plan | Current Plan | Status |
|--------------|-------------|--------|
| 01 (delete orchestrator) | 73-01 | Direct mapping |
| 02 (SafeAgentWrapper) | Absorbed into 73-03 | Infrastructure |
| 03 (token counts) | Absorbed into 73-02 | LLM chain fixes |
| 04 (latency profiling) | Absorbed into 73-06 | Cleanup |
| 05 (atomic migration) | 73-05 | Direct mapping |
| 06 | Absorbed | — |
| 07 (performance design) | Absorbed into 73-03/04 | Infrastructure |
| 08 (Kafka shadow) | Absorbed into 73-04/05 | Rename + migration |
| 09 (import boundaries) | 73-06 | Direct mapping |

**User's choice:** Confirmed, replan needed
**Notes:** Plans 73-03 and 73-05 reference `topic_shadow_recordings` and `ShadowRecorder` — need updating to `topic_signal_lineage` and `LineageRecorder` per unified lineage decision.

---

## Extension Hooks Scope

| Option | Description | Selected |
|--------|-------------|----------|
| Hooks now, implementations later | Add _on_error, _on_guardrail_violation, _audit_payload to base classes (~60-80 lines). Full implementations in future phases. | ✓ |
| Everything later | Phase 73 does structure only. Future phase adds everything together. Simpler now but more rework later. | |

**User's choice:** Hooks now, implementations later
**Notes:** User asked "would it be easier to wire up and add in this now to base classes or just wait?" — wiring hooks during base class creation avoids retroactive patching. Full OTel spans, prompt injection detection, content filtering, and quality scoring are future phases.

---

## Claude's Discretion

- DB migration number for signal_lineage table
- Whether to keep GraduationWriterAgent as-is or absorb into LineageWriterAgent
- Exact schema of JSONB metadata field per event_type
- Whether to update CLAUDE.md service table with renamed services
- Systemd unit file name for renamed alpha swarm agent

## Deferred Ideas

- AI Agent full observability (OTel spans per agent, quality dashboards, cost tracking) — future phase
- Advanced guardrails (prompt injection detection, content filtering, jailbreak resistance) — future phase
- Security & data protection (input sanitization, access control, data classification) — future phase
- Evaluation QA (automated quality scoring of individual agent outputs) — future phase
- Governance (model versioning, rollback, policy enforcement) — broader than Phase 75's shadow governance
