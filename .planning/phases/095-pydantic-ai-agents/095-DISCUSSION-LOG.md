# Phase 095: Pydantic AI Execution Layer - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-05-31
**Phase:** 095-pydantic-ai-agents
**Areas discussed:** WorkerContext Ring boundary, LLMAdapter bridge design, _run_typed placement, SkepticEvaluator structure

---

## WorkerContext Ring boundary

| Option | Description | Selected |
|--------|-------------|----------|
| `signal_context: Any` in Ring 0 | Container doesn't know its contents — mirrors AgentOutput.payload pattern | ✓ |
| Move WorkerContext to Ring 1 | SignalContext is native in Ring 1, but creates circular dep with BaseAIWorker | |
| `from __future__ import annotations` | Lazy string annotations — fragile, depends on pydantic-ai internals | |

**User's choice:** `signal_context: Any` — Ring 0 is infrastructure, not a validator.
**Notes:** User consistently applied Simons framing: correctness of invariants is non-negotiable; simplest correct solution wins.

| Option | Description | Selected |
|--------|-------------|----------|
| 4 fields: signal_context, llm_chain, db_pool, memory_client | Forward-compatible; Phase 097 Zep memory needs db_pool/memory_client | ✓ |
| 2 fields only | YAGNI but requires call-site changes in Phase 097 | |

**User's choice:** 4 fields — design the container once, correctly.

| Option | Description | Selected |
|--------|-------------|----------|
| `@dataclass(frozen=True)` | Lightweight, no serialization overhead, correct immutability | ✓ |
| `Pydantic BaseModel frozen` | Validation on construction, but WorkerContext is never serialized | |

**User's choice:** `@dataclass(frozen=True)` — compute costs matter, no unnecessary overhead.

---

## LLMAdapter bridge design

| Option | Description | Selected |
|--------|-------------|----------|
| LLMAdapter wraps LLMProviderChain | Preserves circuit breaking, routing, audit trail | ✓ |
| LLMAdapter wraps LiteLLMModel directly | Native structured output but bypasses llm_calls audit trail | |

**User's choice:** Route through LLMProviderChain — instrument everything. The audit trail IS the experiment.
**Notes:** User explicitly cited Renaissance principle: never create a blind spot in the data.

| Option | Description | Selected |
|--------|-------------|----------|
| LLMAdapter.request() injects audit_context | Structural instrumentation from WorkerContext | ✓ |
| _run_typed() injects before construction | More explicit but requires every caller to know about audit | |

**User's choice:** LLMAdapter.request() injects — same pattern as _llm_generate(), impossible to forget.

| Option | Description | Selected |
|--------|-------------|----------|
| Inherit pydantic-ai retry defaults | Thin bridge, pydantic-ai owns validation retry | ✓ |
| Derive retries from latency_budget_ms | Dynamic but complex interaction with circuit breaker | |

**User's choice:** Inherit defaults — use as much of pydantic-ai as possible. Don't rebuild what the framework already does correctly.

---

## _run_typed placement

| Option | Description | Selected |
|--------|-------------|----------|
| On BaseAIWorker (universal) | All AI agents opt in via result_type ClassVar; narrative/risk get it for free | ✓ |
| On Evaluator only | Restricts to multiplier agents; requires base class change for other agent types | |

**User's choice:** BaseAIWorker — reuse over restriction; general capability belongs at the right level of abstraction.

| Option | Description | Selected |
|--------|-------------|----------|
| Explicit max_tokens + timeout params (mirrors _llm_generate) | Consistent but requires each caller to compute timeout correctly | |
| Derive timeout from self, max_tokens optional | Latency budget always enforced; less boilerplate | ✓ |

**User's choice:** Derive from self — automate what should always be true. The budget is declared once as a ClassVar; don't require callers to repeat it.

| Option | Description | Selected |
|--------|-------------|----------|
| Returns result_type instance | _run_typed does one thing; caller builds AgentOutput | ✓ |
| Returns AgentOutput wrapping result | Double-wrapping; defeats the purpose of typed output | |

**User's choice:** Returns result_type instance — separation of concerns.

---

## SkepticEvaluator structure

| Option | Description | Selected |
|--------|-------------|----------|
| Separate SkepticPydanticEvaluator in skeptic_pydantic.py | A/B comparison in shadow system | |
| SkepticEvaluator uses _run_typed internally, feature-gated | One class, two code paths | |
| Straight replacement — migrate SkepticEvaluator to _run_typed, no parallel class | Commit to the better approach | ✓ |

**User's choice:** Straight replacement — when you have the better approach, run it. Don't hedge. No parallel experiment, no double Ollama load.
**Notes:** User challenged the parallel-class approach: "why not just use pydantic, toss the old one — do it right." This is the correct Simons answer.

| Option | Description | Selected |
|--------|-------------|----------|
| `agent_id = "skeptic_v1"` unchanged | Preserve audit trail continuity | |
| `agent_id = "skeptic"` | Correct per Phase 110/111 naming conventions; "v1" is a version suffix | ✓ |

**User's choice:** `agent_id = "skeptic"` — "why do we need V1 in anything?" Orphaned shadow_registry row for "skeptic_v1" decays (shadow-only, no production history).

---

## Claude's Discretion

- Specific structure of `LLMAdapter.request()` implementation (pydantic-ai Model protocol details) — user delegated to Claude
- `_default_max_tokens` ClassVar value (set to 2048 as conservative default)
- Exact ring0-ok annotation comment style for WorkerContext

## Deferred Ideas

- Narrative/risk agent migration to `_run_typed` — available via BaseAIWorker, not Phase 095 scope
- Zep memory wiring into `memory_client` field — Phase 097
- DSPy prompt optimization reading from `llm_calls` — Phase 098
- Qualitative pipeline todos (P-CTX-03a, P-CTX-03b, P-CTX-04) — out of scope, reviewed and deferred
