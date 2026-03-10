# Phase 22: I8 Narrative Three-Tier Redesign - Context

**Gathered:** 2026-03-09
**Status:** Ready for planning
**Source:** PRD Express Path (docs/plans/2026-03-09-i8-narrative-implementation.md)

<domain>
## Phase Boundary

Replace the single thin narrative LLM call with a three-tier system:
1. **Tier 0 — Signal Bar (instant):** Deterministic `action_tag` and `action_bias` derived from signal data, no LLM wait
2. **Tier 1 — Short Narrative (~500ms):** 2-sentence Context+Execution, always visible, confidence-gated instruction
3. **Tier 2 — Deep Narrative (~5-8s):** 3-sentence confluence story, revealed on expand

Architecture: at signal time, fetch intelligence context via `XREVRANGE intelligence:SYMBOL:TF`, fire two concurrent async tasks (`narrative_short`, `narrative_deep`), each publishes independently to narratives stream.

</domain>

<decisions>
## Implementation Decisions

### Context Extraction Pure Functions (locked)
- `extract_short_context(signal, intel)` → conclusion-level fields: regime label/prob, killzone, confluence score, entry/stop/target/RR, confidence, structural label
- `extract_deep_context(signal, intel)` → superset of short + FVG bounds, OB levels, S/D zone levels, supporting factors, regime context
- `extract_deep_context` MUST be a superset of `extract_short_context` (all short keys present in deep)
- Both handle empty intel gracefully (returns None for missing intel fields)

### Prompt Builders (locked)
- `build_short_prompt(signal, ctx)` → 2-sentence prompt; confidence-gated execution instruction:
  - ≥75%: "DIRECT — act now at {entry} with stop at {stop}"
  - 50-75%: "CONDITIONAL — wait for condition before entering"
  - <50%: "MONITOR — frame as 'watch', not 'enter'"
- `build_deep_prompt(signal, ctx)` → 3-sentence prompt: Confluence / Key Levels / Guidance+Invalidation
- Both prompts start with `/no_think` prefix (qwen model instruction)

### Action Tag + Structural Label (locked)
- `build_action_tag(signal)`:
  - confidence <50%: `[MONITOR]`
  - 50-75%: `[WAIT — BULLISH]` / `[WAIT — BEARISH]`
  - ≥75%: `[BULLISH SWEEP RECLAIM]` (direction + structural label)
- `get_structural_label(setup_plugin)` → maps plugin name to short label (17-entry dict provided in plan)
- Unknown plugins: `plugin.upper()[:16]`

### Concurrent Execution Architecture (locked)
- `_process_single_message()` fires two `asyncio.create_task()` calls: `narrative_short` and `narrative_deep`
- Tasks execute concurrently without blocking each other or the main processing loop
- New method `_run_narrative_call(signal_data, symbol, timeframe, call_type, prompt, chain)` handles each call
- Both calls publish to `llm_calls:stream` and to `narratives:SYMBOL:TF` stream independently

### Narratives Stream Schema (locked)
- New field: `narrative_type`: `"short"` or `"deep"` (derived from `call_type.replace("narrative_", "")`)
- New field: `action_tag`: deterministic tag string
- New field: `signal_id`: correlates short + deep events for same signal
- Keep existing fields: `symbol`, `timeframe`, `timestamp`, `narrative`, `action_bias`, `confidence`, `model`, `latency_ms`
- `narrative_short` call also updates the `narrative:{symbol}:{timeframe}:latest` hash (backward compat)

### LLM Chain Separation (locked)
- `self.short_chain` and `self.deep_chain` — separate LLMChain instances, each independently routable
- Both start with same initial provider (z-ai/glm-4.7-flash via OpenRouter)
- `_apply_score_routing()` loop covers: `narrative_short`, `narrative_deep`, `group_synthesis`
- Keep `self.per_signal_chain = self.short_chain` as alias during transition (removed in Task 9 cleanup)
- Config JSON: add `narrative_short` and `narrative_deep` entries (same provider as `per_signal` initially)

### SYSTEM_PROMPT Voice (locked)
- Replace existing prompt with senior trading desk analyst voice
- Banned phrases: "capitalize on", "execute long orders", "protect the position", "price momentum suggests", "within the established regime", "deliver a risk-to-reward"
- No passive voice, no "suggests/indicates"
- Core instruction: explain WHY structure matters + WHAT to do

### Dashboard Types (locked)
- `NarrativeData` interface adds: `narrative_short?: string`, `narrative_deep?: string`, `action_tag: string`, `signal_id?: string`
- Keep `narrative?: string` for backward compat (aliased to `narrative_short`)
- SSE handler merges short and deep updates into same key (`{sym}:{tf}`) via `setNarratives`

### Dashboard UI (locked)
- `action_tag` badge: `text-xs font-mono text-amber-400`
- `narrative_short`: primary text, always visible, skeleton if loading
- Expand/collapse toggle: `▼ Full analysis` / `▲ Hide analysis`
- `narrative_deep`: shown on expand, skeleton if not yet arrived

### Retire Old Path (locked, Task 9)
- `build_narrative_prompt()` is retired after three-tier path is proven
- Old `per_signal` call type disappears from routing loop
- `per_signal_chain` alias removed

### Claude's Discretion
- Exact timing of cleanup (Task 9 may be before or after Task 8 verification)
- Whether to add `narrative_type` filter to narrative-panel.tsx (recommended but layout details are flexible)
- Whether `test_narrative_stream_message_has_type_field` test is fully implemented or left as pass stub (plan marks it as "implement after verifying first test passes")

</decisions>

<specifics>
## Specific Implementation Details

**Files to modify:**
- `services/ai_narrative_service.py` — primary service changes (Tasks 1, 2, 3, 6)
- `tests/unit/service_tests/test_ai_narrative_helpers.py` — new file (Task 1)
- `tests/unit/service_tests/test_ai_narrative_service.py` — extend existing (Tasks 2, 3)
- `dashboard/src/lib/types.ts` — NarrativeData type (Task 4)
- `dashboard/src/hooks/use-market-stream.ts` — SSE handler (Task 4)
- `dashboard/src/components/narrative-panel.tsx` — UI (Task 5)
- Narrative service JSON config — provider entries (Task 6)

**Key test fixtures provided in plan:**
- `_SIGNAL` dict with all signal fields
- `_INTEL` dict with regime/FVG/OB/killzone/confluence fields
- 16 unit tests for pure functions (Tasks 1-2)
- Async integration test for `_process_single_message` (Task 3)

**Stream key import:** `from src.core.stream_keys import intelligence as sk_intelligence`

**Confidence thresholds (locked):**
- ≥0.75 = high conviction, direct entry instruction
- 0.50-0.74 = conditional, wait instruction
- <0.50 = monitor only

</specifics>

<deferred>
## Deferred Ideas

- Model routing optimization per call type — architecture ready via `_apply_score_routing()`, but actual model differentiation deferred until performance data accumulates
- `test_narrative_stream_message_has_type_field` — plan marks as stub ("implement after first test passes")
- Group synthesis narrative — existing, not changed in this phase

</deferred>

---

*Phase: 22-i8-narrative-three-tier-redesign*
*Context gathered: 2026-03-09 via PRD Express Path (docs/plans/2026-03-09-i8-narrative-implementation.md)*
