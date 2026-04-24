---
phase: 066-skeptic-agent
reviewed: 2026-04-24T18:30:00Z
depth: quick
files_reviewed: 16
files_reviewed_list:
  - scripts/compute_skeptic_baseline.py
  - scripts/validate_skeptic.py
  - services/indicagent-swarm-dispatch.service
  - services/swarm_dispatch_service.py
  - src/intelligence/swarm/agents/correlation_agent.py
  - src/intelligence/swarm/agents/correlation_prompts.py
  - src/intelligence/swarm/agents/skeptic_agent.py
  - src/intelligence/swarm/agents/skeptic_prompts.py
  - src/intelligence/swarm/agents/volume_agent.py
  - src/intelligence/swarm/agents/volume_prompts.py
  - src/intelligence/swarm/context.py
  - tests/unit/test_correlation_agent.py
  - tests/unit/test_skeptic_agent.py
  - tests/unit/test_swarm_dispatch.py
  - tests/unit/test_swarm_dispatch_integration.py
  - tests/unit/test_volume_agent.py
findings:
  critical: 0
  warning: 1
  info: 3
  total: 4
status: issues_found
---

# Phase 066: Code Review Report

**Reviewed:** 2026-04-24T18:30:00Z
**Depth:** quick
**Files Reviewed:** 16
**Status:** issues_found

## Summary

Reviewed 16 files implementing the SkepticAgent, CorrelationAgent, VolumeAgent, and SwarmDispatchService. The code is well-structured: agents are pure compute classes with no infrastructure coupling, prompts are versioned, JSON parsing has robust fallback handling, and SwarmContext is an immutable Pydantic model. No hardcoded secrets, no dangerous function calls, no debug artifacts, no empty catch blocks. The codebase follows project conventions (structlog, asyncpg, stream_keys via import, UTC timestamps in tests).

One Warning-level issue found: duplicated `_LEAD_INDEX_MAP` dict between `swarm_dispatch_service.py` and `correlation_prompts.py` with a comment acknowledging the duplication. If one copy is updated without the other, lead index resolution will silently diverge.

## Warnings

### WR-01: Duplicated _LEAD_INDEX_MAP across two files

**File:** `src/intelligence/swarm/agents/correlation_prompts.py:78` and `services/swarm_dispatch_service.py:46`
**Issue:** The `_LEAD_INDEX_MAP` dictionary is defined identically in two files. The comment in `correlation_prompts.py` (line 77) says "must match _LEAD_INDEX_MAP in swarm_dispatch_service.py", but there is no enforcement. If a new asset class is added to one copy and not the other, `get_lead_index()` in `correlation_prompts.py` will return a different result than `_find_lead_context()` in `swarm_dispatch_service.py`, causing the prompt to reference a stale or missing lead index while the enrichment layer uses the correct one.
**Fix:** Define `_LEAD_INDEX_MAP` in a single canonical location (e.g., `src/intelligence/swarm/context.py` or a new `src/intelligence/swarm/constants.py`) and import it in both files.

## Info

### IN-01: Duplicated _DIRECTION_LABELS and _fmt helper across three prompt files

**File:** `src/intelligence/swarm/agents/skeptic_prompts.py:63-70`, `src/intelligence/swarm/agents/correlation_prompts.py:75-91`, `src/intelligence/swarm/agents/volume_prompts.py:79-86`
**Issue:** `_DIRECTION_LABELS = {1: "LONG", -1: "SHORT", 0: "FLAT"}` and `def _fmt(val, spec)` are copy-pasted identically into all three `*_prompts.py` files. Low risk today but creates maintenance burden as the agent count grows.
**Fix:** Extract to a shared module (e.g., `src/intelligence/swarm/agents/prompt_utils.py`) and import.

### IN-02: Duplicated _validate_*_fields functions across three agent files

**File:** `src/intelligence/swarm/agents/skeptic_agent.py:123-150`, `src/intelligence/swarm/agents/correlation_agent.py:122-149`, `src/intelligence/swarm/agents/volume_agent.py:122-149`
**Issue:** `_validate_skeptic_fields`, `_validate_correlation_fields`, and `_validate_volume_fields` are functionally identical -- they all validate `failure_probability`, `confidence`, `risk_factors`, and `reasoning` with the same clamping and type coercion logic. Same for `_parse_*_response`. A base class method or shared utility would eliminate ~30 lines of duplication per agent.
**Fix:** Extract a shared `parse_llm_json_response(raw: str) -> dict | None` into a utility module (e.g., `src/intelligence/swarm/agents/response_parser.py`) since all three agents have identical response schemas.

### IN-03: price_divergence_pct computes trend_regime difference, not price divergence

**File:** `src/intelligence/swarm/agents/correlation_prompts.py:131`
**Issue:** The variable `price_divergence_pct` is computed as `ctx.trend_regime - lc.trend_regime` -- a difference of trend regime scores, not actual price divergence. The prompt template (line 50) labels it "Lead index price vs signal price divergence" which is semantically misleading. The LLM receives a trend-regime delta labeled as price divergence. This is not a bug (the prompt instructs the LLM to assess correlation broadly) but the naming is confusing for future maintainers.
**Fix:** Rename the field to `trend_regime_divergence` in both the prompt template and the code, or compute actual price divergence `(ctx.price - lc.price) / lc.price`.

---

_Reviewed: 2026-04-24T18:30:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: quick_
