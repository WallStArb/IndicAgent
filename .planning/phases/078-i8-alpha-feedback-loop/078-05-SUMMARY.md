---
phase: 078-i8-alpha-feedback-loop
plan: "05"
subsystem: ai-context
tags: [typed-bus, schema-unification, llm-prompts, authoring-protocol]
dependency_graph:
  requires: [078-01, 078-02]
  provides: [typed-aicontext, skeptic-v2-prompt, agent-authoring-protocol]
  affects: [services/alpha_swarm_agent.py, src/core/ai/context.py, src/intelligence/ai/alpha/]
tech_stack:
  added: []
  patterns: [pydantic-direct-pass-through, open-ended-model-fields-iteration]
key_files:
  created:
    - src/intelligence/ai/TEMPLATE_agent.py
    - src/intelligence/ai/AUTHORING.md
    - tests/unit/test_core_ai_context_typed_tiers.py
    - tests/unit/test_skeptic_prompts_v2.py
  modified:
    - src/core/ai/context.py
    - src/intelligence/ai/alpha/skeptic_prompts.py
    - src/intelligence/ai/alpha/skeptic_agent.py
    - services/alpha_swarm_agent.py
    - CLAUDE.md
decisions:
  - "hmm_regime sourced from SMCContext not I4Context — schemas.I4Context has no hmm_regime field"
  - "Tier.SMC added to enum; AIContext gains smc field for direct SMC tier pass-through"
  - "skeptic_v2 renders via open-ended model_fields iteration — future tiers auto-appear"
  - "ACTIVE_VERSION = skeptic_v2 — renders full typed AIContext; v1 preserved for rollback"
metrics:
  duration: "~25 minutes"
  completed: "2026-04-30"
  tasks_completed: 3
  tasks_total: 3
  files_modified: 9
---

# Phase 78 Plan 05: AIContext Typed-Tier Rewrite + skeptic_v2 + Authoring Protocol Summary

AIContext rewritten to use schemas.py types directly for all six pipeline tiers (i1-i6, smc); sparse subclasses deleted; skeptic_v2 registered as ACTIVE_VERSION with open-ended `_render_full_context`; agent authoring docs codified.

## What Was Built

### Task 1: AIContext typed-tier rewrite (TDD)

`src/core/ai/context.py` rewritten end-to-end:

- **Deleted**: `I1Context(TierContext)`, `I4Context(TierContext)`, `I6Context(TierContext)` sparse subclasses (D-10)
- **Kept**: `I7Context(TierContext)` (signal-specific), `BarContext(TierContext)` (custom OHLCV shape)
- **Added**: `i2: I2Events`, `i3: I3Structure`, `i5: I5Patterns`, `smc: SMCContext` fields on `AIContext`
- **Tier enum**: Added `I2`, `I3`, `I5`, `SMC` members (D-14)
- **build()**: Direct `event.iN` → `ctx.iN` pass-through, no field-by-field copy (D-13)
- **seed_from_db_row()**: Constructs typed models via `model_validate` (no SimpleNamespace for tier data)
- **Zero escape hatch**: No `full_features` or `dict[str, Any]` on pipeline tier fields (D-15)

21 unit tests in `tests/unit/test_core_ai_context_typed_tiers.py` — all pass.

### Task 2: skeptic_v2 prompt registration (TDD)

`src/intelligence/ai/alpha/skeptic_prompts.py`:

- `_render_full_context(ctx: AIContext) -> str` — iterates `ctx.__class__.model_fields` (open-ended per D-16); any future tier added to `AIContext` automatically appears in the LLM prompt
- `skeptic_v2` registered in `PROMPT_REGISTRY`; `ACTIVE_VERSION = "skeptic_v2"` (D-17)
- `skeptic_v1` preserved verbatim for one-line rollback via `ACTIVE_VERSION`
- `build_skeptic_prompt` updated: v2 path accepts typed `AIContext`; v1 dict path preserved

`src/intelligence/ai/alpha/skeptic_agent.py`:
- `_compute` branches on `ACTIVE_VERSION` to pass `AIContext` directly (v2) or `_context_to_dict(context)` (v1)
- `tiers_needed` updated to include `Tier.SMC` (needed for hmm_regime via smc tier)
- `_context_to_dict` field names corrected: `atr_14`, `rsi_14`, `adx_14` (schemas.I1Indicators field names); `hmm_regime` sourced from `smc_ctx.hmm_regime`

14 unit tests in `tests/unit/test_skeptic_prompts_v2.py` — all pass.

### Task 3: Agent authoring protocol codified

- `src/intelligence/ai/TEMPLATE_agent.py`: copy-me skeleton with all five required class attributes, `_compute` contract, doc-string steps
- `src/intelligence/ai/AUTHORING.md`: full protocol covering groups, file layout, LineageRecorder, shadow enrollment/graduation, `_compute()` contract, adding a new group
- `CLAUDE.md`: "Adding an AI Agent" section cross-referencing AUTHORING.md and TEMPLATE_agent.py

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] hmm_regime lives on SMCContext, not I4Context**

- **Found during**: Task 1 — when rewriting AIContext to use schemas.I4Context directly, the sparse local `I4Context.hmm_regime` field had no equivalent on `schemas.I4Context` (confirmed: `schemas.I4Context` has no `hmm_regime`; it lives on `SMCContext` line 646)
- **Issue**: `alpha_swarm_agent.py` read `enriched.i4.hmm_regime`; `_context_to_dict` read `i4_ctx.hmm_regime`. After the rewrite, both would fail at runtime (AttributeError on the Pydantic model)
- **Fix**:
  - Added `Tier.SMC` to the `Tier` enum
  - Added `smc: SMCContext | None` field to `AIContext`
  - Updated `alpha_swarm_agent.py` line 249: `hmm_regime = enriched.smc.hmm_regime if enriched.smc is not None else None`
  - Updated `alpha_swarm_agent.py` initial build tiers: `frozenset({Tier.SMC})`
  - Added `Tier` import to `alpha_swarm_agent.py`
  - Updated `_context_to_dict` to use `smc_ctx.hmm_regime`
  - Updated `skeptic_agent.tiers_needed` to include `Tier.SMC`
- **Files modified**: `src/core/ai/context.py`, `services/alpha_swarm_agent.py`, `src/intelligence/ai/alpha/skeptic_agent.py`
- **Plan note acknowledged**: The plan explicitly said to surface this in SUMMARY.md if `ctx.i4.hmm_regime` doesn't resolve — it doesn't, because `schemas.I4Context` has no `hmm_regime`. The correct source is `ctx.smc.hmm_regime`.

**2. [Rule 1 - Bug] _context_to_dict field name corrections**

- **Found during**: Task 2 — `_context_to_dict` used `i1_ctx.atr`, `i1_ctx.rsi`, `i1_ctx.adx` (sparse subclass field names). `schemas.I1Indicators` uses `atr_14`, `rsi_14`, `adx_14`.
- **Fix**: Corrected to `i1_ctx.atr_14`, `i1_ctx.rsi_14`, `i1_ctx.adx_14`
- **Files modified**: `src/intelligence/ai/alpha/skeptic_agent.py`

## TDD Gate Compliance

- Task 1: RED commit `c320214c`, GREEN commit `1515d609` — gates satisfied
- Task 2: RED commit `29f803b8`, GREEN commit `a12e83f7` — gates satisfied

## Known Stubs

None — all pipeline tier types are wired directly from schemas.py; no placeholder data.

## Threat Flags

None — no new network endpoints, auth paths, or file access patterns introduced. The LLM prompt now sends a larger context payload (T-78-05-02/T-78-05-03 accepted in plan threat model).

## Self-Check

Verifying created files and commits:

- FOUND: src/core/ai/context.py
- FOUND: src/intelligence/ai/alpha/skeptic_prompts.py
- FOUND: src/intelligence/ai/TEMPLATE_agent.py
- FOUND: src/intelligence/ai/AUTHORING.md
- FOUND: tests/unit/test_core_ai_context_typed_tiers.py
- FOUND: tests/unit/test_skeptic_prompts_v2.py
- FOUND: commit c320214c (RED: typed AIContext tests)
- FOUND: commit 1515d609 (GREEN: AIContext rewrite)
- FOUND: commit 29f803b8 (RED: skeptic_v2 tests)
- FOUND: commit a12e83f7 (GREEN: skeptic_v2 implementation)
- FOUND: commit 2b36bccc (docs: authoring protocol)

## Self-Check: PASSED
