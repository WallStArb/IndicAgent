---
phase: 56
plan: "02"
subsystem: intelligence/narrative
tags: [narrative, llm, prompts, refactor, tdd]
dependency_graph:
  requires: ["56-01"]
  provides: ["src/intelligence/narrative"]
  affects: ["services/ai_narrative_service.py"]
tech_stack:
  added: ["src/intelligence/narrative/"]
  patterns: ["pure functions", "TYPE_CHECKING guard", "noqa E501 for prompt strings"]
key_files:
  created:
    - src/intelligence/narrative/__init__.py
    - src/intelligence/narrative/prompts.py
    - src/intelligence/narrative/parsers.py
    - src/intelligence/narrative/orchestrator.py
    - tests/unit/test_narrative_prompts.py
    - tests/unit/test_narrative_parsers.py
    - tests/unit/test_narrative_orchestrator.py
  modified: []
decisions:
  - "noqa: E501 for natural-language prompt strings — cannot split without altering LLM instructions"
  - "TYPE_CHECKING guard for BarIntelligenceRecord — avoids circular import at runtime"
  - "NarrativeOrchestrator accepts chain: object (duck-typed) — not typed to LLMProviderChain to avoid coupling"
metrics:
  duration_minutes: 18
  completed_date: "2026-04-11"
  tasks_completed: 4
  tasks_total: 4
  files_created: 7
  files_modified: 0
---

# Phase 56 Plan 02: Narrative Module Extraction Summary

**One-liner:** Pure `src/intelligence/narrative/` module extracted from ai_narrative_service.py monolith — prompt builders, field parser, and orchestrator with 10 TDD tests.

## What Was Built

Extracted reusable narrative logic from `services/ai_narrative_service.py` (1,327-line monolith) into a testable `src/intelligence/narrative/` module with three files:

- **`prompts.py`** — `build_short_prompt()` (2-sentence) and `build_deep_prompt()` (3-sentence) pure functions. Both include `/no_think` prefix for Ollama Qwen3 models, confidence-tier execution guidance, regime labels, and CTF confluence fields.
- **`parsers.py`** — `parse_bar_intelligence_record()` extracts symbol, timeframe, direction, confidence, plugin, regime, and CTF fields. Returns `None` when `direction=0` (no actionable signal).
- **`orchestrator.py`** — `NarrativeOrchestrator.generate()` wires parsers + prompts + `LLMProviderChain`. Returns `None` for direction=0 without calling the chain.

## Tasks Completed

| Task | Description | Commit |
|------|-------------|--------|
| 1 | `prompts.py` + `__init__.py` + 4 tests | `59ff30c4` |
| 2 | `parsers.py` + 4 tests | `0e469666` |
| 3 | `orchestrator.py` + 2 tests | `51d27189` |
| 4 | Lint + black formatting | `b4c9c65e` |

## Test Results

10/10 tests passing across all three modules. Pre-existing failures (37 pipeline tests) unchanged.

## Deviations from Plan

**None** — plan executed exactly as written. All files created per spec.

Minor: Black auto-reformatted files after ruff applied `noqa` suppressions — no behavioral changes.

## Known Stubs

None. All functions are fully implemented and wired. The orchestrator's `chain` dependency is injected — `services/ai_narrative_service.py` refactor (Plan 56-05) will wire `LLMProviderChain` to `NarrativeOrchestrator`.

## Self-Check: PASSED

- [x] `src/intelligence/narrative/__init__.py` exists
- [x] `src/intelligence/narrative/prompts.py` exists
- [x] `src/intelligence/narrative/parsers.py` exists
- [x] `src/intelligence/narrative/orchestrator.py` exists
- [x] All 4 test files exist
- [x] Commits `59ff30c4`, `0e469666`, `51d27189`, `b4c9c65e` verified in git log
- [x] `from src.intelligence.narrative import NarrativeOrchestrator, build_short_prompt, build_deep_prompt, parse_bar_intelligence_record` imports cleanly
