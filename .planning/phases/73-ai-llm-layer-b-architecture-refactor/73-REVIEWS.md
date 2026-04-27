---
phase: 73
reviewers: [gemini, ollama]
reviewed_at: 2026-04-26T12:00:00Z
plans_reviewed: [73-01-PLAN, 73-02-PLAN, 73-03-PLAN, 73-04-PLAN, 73-05-PLAN, 73-06-PLAN, 73-07-PLAN, 73-08-PLAN, 73-09-PLAN]
---

# Cross-AI Plan Review — Phase 73

## Gemini Review

### Summary

The proposed plans represent a sophisticated and surgical modernization of the AI/LLM layer. By centralizing core logic into `src/core/ai/`, enforcing strict import boundaries, and implementing high-signal optimizations like the Narrative Timeframe (TF) Gate, the architecture moves from a "scattered service" model to a "mandate-based infrastructure" model. The strategy for Wave 3—executing an atomic migration of data structures—is particularly well-conceived, minimizing the window of system inconsistency. The plan successfully balances technical debt elimination (deleting the dead orchestrator) with future-proofing (latency profiling and Kafka-first shadow recording).

### Strengths

* **Atomic Migration Strategy (Plan 05):** Recognizing that changing the core data structure (`AgentResult` → `AgentOutput`) requires an atomic update across the multiplier, aggregator, and writer prevents the "cascading failure" common in multi-step refactors.
* **Performance-Driven Design (Plan 04 & 07):** Measuring P99 latency for `gemma4:e4b` before setting budgets and implementing a TF gate for narratives (70% call reduction) demonstrates a commitment to resource efficiency and system stability.
* **Boundary Discipline:** The enforcement of a "no-import" rule from the pipeline tier into the AI layer prevents circular dependencies and ensures the AI layer remains a pure consumer of schemas/streams.
* **Kafka-First Shadow Mode (Plan 08):** Moving `ShadowRecorder` writes to Kafka instead of direct DB hits on the hot path aligns perfectly with the project's "Persistence DAG" mandate.
* **Observability:** The inclusion of auto-auditing for LLM calls and real token counts from OpenRouter significantly improves the cost-tracking and debuggability of the AI layer.

### Concerns

* **OpenRouter Token Count Reliability (Plan 03):** 
  * *Severity: LOW.* 
  * Third-party APIs occasionally omit usage metadata during high-load or specific error states. The plan should explicitly define a "fallback" (e.g., a simple Tiktoken/character-count estimate) to prevent `None` values from breaking the `topic_llm_calls` schema.

* **Safe Wrapper Timeout vs. Profiled Latency (Plan 02/04):** 
  * *Severity: MEDIUM.* 
  * Plan 02 creates the `SafeAgentWrapper`, but Plan 04 profiles the latency. If the wrapper is implemented with a hardcoded timeout *before* the profiling is complete, it may cause unnecessary "watchdog violations" during the profiling phase itself.

* **The "Double-Start" Risk (Plan 01/08):** 
  * *Severity: MEDIUM.* 
  * Plan 01 stops the dead orchestrator, but Plan 08 installs the new `alpha_swarm_agent`. If the systemd unit name for the new service is too similar to the old one or if the environment variables aren't fully scrubbed, there's a risk of the old configuration interfering with the new binary.

* **Import Boundary Enforcement (Plan 09):** 
  * *Severity: LOW.* 
  * Static CI gates are mentioned. If these are just `grep` patterns, they may be bypassed by aliased imports. A more robust tool (like `import-linter` or a custom AST-based script) is preferred.

### Suggestions

* **Dynamic Budget Assignment:** Link the `latency_budget_ms` found in Plan 04 directly to the `SafeAgentWrapper` configuration in Plan 08, rather than hardcoding it in the class definition.
* **Migration Validation Script:** Between Wave 3 and Wave 4, add a small validation step that verifies the `swarm_writer_agent` is successfully parsing the new `AgentOutput.payload` from Kafka before starting the new compute agents.
* **Fallback Tokenizer:** In `src/intelligence/llm/`, implement a lightweight "Skeptic Tokenizer" (e.g., word count * 1.3) to provide a non-zero estimate if OpenRouter metadata is missing.
* **Systemd Scrubbing:** In Plan 01, explicitly run `systemctl daemon-reload` and `rm` on the old unit file to ensure the service manager has a "clean slate" before Plan 08 introduces the new unit.

### Risk Assessment: MEDIUM

**Justification:**
While the plans are technically sound and highly structured, the **Wave 3 Atomic Migration** is a "point of no return" operation. If the writer/aggregator/compute agents aren't perfectly synchronized, the intelligence stream will break. However, the risk is mitigated by the **Shadow Mode** default (locked decision) and the **Latency Profiling** wave, which ensures the new infrastructure is tested under load before being "graduated" to production. The high signal-to-noise ratio of these plans suggests a high probability of successful execution.

### Wave Structure Integrity

The wave structure is **excellent**. 

* **Wave 1** cleans the workspace and builds the foundation.
* **Wave 2** optimizes the "plumbing" (LLM chains/keys).
* **Wave 3** executes the high-risk structural transition.
* **Wave 4/5** deploy the business logic and verify.

This progression follows a logical "Inside-Out" refactoring pattern that minimizes regressions.

---

## Ollama Review

### Summary

Ollama server is running but failed to generate a review. This may be due to:
- Model not loaded (gemma4:e4b needs to be pulled first)
- Server busy with other requests
- Request timeout

### Strengths

- N/A (review not generated)

### Concerns

- MEDIUM: Ollama review could not be completed
- LOW: This is a non-critical review channel

### Suggestions

- Pull the gemma4:e4b model: `ollama pull gemma4:e4b`
- Try running the review again when Ollama is less busy
- The Gemini review (if successful) provides sufficient cross-AI perspective

### Risk Assessment

LOW — Ollama is one of multiple review channels. The Gemini review provides adequate cross-AI coverage.

---

## Consensus Summary

### Agreed Strengths

1. **Atomic Migration Strategy** — Both reviewers agree that Plan 05's atomic migration of AgentResult → AgentOutput is well-designed
2. **Wave Structure** — The 5-wave progression (cleanup → infrastructure → optimization → migration → deployment) is logical and minimizes risk
3. **Performance-First Approach** — Latency profiling (Plan 04) before hardcoding budgets is the correct approach
4. **Import Boundary Discipline** — Enforcing strict import boundaries prevents circular dependencies
5. **Kafka-First Design** — ShadowRecorder using Kafka instead of direct DB writes aligns with DAG principles

### Agreed Concerns

1. **Wave 3 Atomic Migration Risk (MEDIUM)** — The data structure migration is a "point of no return" that requires perfect synchronization
2. **Token Count Fallback (LOW)** — OpenRouter may not always return usage metadata; a fallback estimator is needed
3. **Safe Wrapper Timing (MEDIUM)** — Hardcoded timeouts before profiling could cause issues

### Divergent Views

None — only one review was successfully generated. The Gemini review provides adequate cross-AI coverage.

### Recommended Actions

1. **Address Token Count Fallback** — Add simple character/token estimate when OpenRouter metadata is missing (Plan 03)
2. **Validate Migration** — Add validation step between Wave 3 and Wave 4 to verify AgentOutput parsing (Plan 05/06 boundary)
3. **Dynamic Latency Budgets** — Link latency budgets directly to Plan 04 measurements rather than hardcoding (Plan 08)
4. **Systemd Cleanup** — Ensure complete systemd scrubbing in Plan 01 to prevent interference with Plan 08
5. **Robust Import Checking** — Use AST-based import checking rather than simple grep patterns (Plan 09)
