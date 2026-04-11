---
phase: 56
plan: "03"
subsystem: swarm-protocol
tags: [swarm, schemas, feature-vector, protocol, archival]
dependency_graph:
  requires: [56-01]
  provides: [SwarmContext, SwarmContextCache, FeatureVector, IAlphaContributor-protocol]
  affects: [src/intelligence/schemas.py, src/intelligence/swarm/, src/core/agents/, src/core/ml/]
tech_stack:
  added: [src/core/ml/, src/core/agents/]
  patterns: [frozen-pydantic-models, protocol-re-export, archival-pattern]
key_files:
  created:
    - src/intelligence/swarm/context.py
    - src/core/ml/features.py
    - src/core/ml/__init__.py
    - src/core/agents/alpha_contributor.py
    - src/core/agents/__init__.py
    - tests/unit/test_swarm_protocol.py
    - src/intelligence/swarm/agents/_archived_contagion_agent.py
    - src/intelligence/swarm/agents/_archived_narrative_agent.py
    - src/intelligence/swarm/agents/_archived_sweep_hunter.py
    - src/intelligence/swarm/agents/_archived_trend_vol.py
  modified:
    - src/intelligence/schemas.py
    - src/intelligence/swarm/interface.py
    - config/intelligence_contributors.json
decisions:
  - AgentResult gains `path`, `shadow_only`, `latency_ms`, `error` fields — required by IAlphaContributor.compute() contract
  - AlphaMultiplier gains `symbol`, `timeframe`, `path_a_multiplier`, `path_b_multiplier`, `production_multiplier`, `shadow_only` — is_production_ready now reads `not self.shadow_only` (was `self.path == "deterministic"`)
  - IAlphaContributor canonical home is src/core/agents/ — swarm/interface.py is a re-export shim for backward compat
  - SwarmContext uses `ts: Any` (not datetime) to avoid circular import through TYPE_CHECKING
  - FeatureVector uses `ts: str` (ISO-8601) — polars DataFrame rows carry strings; inference path converts before constructing
  - All 4 old stubs archived (not deleted) — contain working get_multiplier signature for reference
  - intelligence_contributors.json emptied — no live contributors until Phase 66 (SkepticAgent)
metrics:
  duration_seconds: 478
  completed_date: "2026-04-10"
  tasks_completed: 4
  files_created: 10
  files_modified: 3
---

# Phase 56 Plan 03: Swarm Protocol + Schema Fixes + FeatureVector Summary

**One-liner:** Swarm protocol fixed with typed `SwarmContext/Cache`, `IAlphaContributor.compute(SwarmContext) -> AgentResult` contract, `FeatureVector` frozen schema as no-skew training/inference bridge, and all 4 old stub agents archived.

## Tasks Completed

| Task | Description | Commit | Files |
|------|-------------|--------|-------|
| 1 | SwarmContext/Cache + AgentResult/AlphaMultiplier schema extension | 75ece9c1 | context.py, schemas.py, test_swarm_protocol.py |
| 2 | FeatureVector schema in src/core/ml/ | be4c3b41 | features.py, __init__.py |
| 3 | IAlphaContributor protocol fix + archive old stubs | 0230d8cd | alpha_contributor.py, interface.py, 4 archived agents, intelligence_contributors.json |
| 4 | Lint and formatting | be6f0906 | 13 files reformatted |

## What Was Built

### SwarmContext + SwarmContextCache (`src/intelligence/swarm/context.py`)
- `SwarmContext`: frozen Pydantic model with 30 fields covering I1/I4/I6 intel + winner signal + OHLCV
- `SwarmContextCache`: asyncio-safe in-memory cache keyed by `(symbol, tf)`, 5-minute TTL
- `update(event)` called by bar loop; `build(symbol, tf, signal, signal_id)` called by signal loop
- Returns `None` on miss or stale — callers skip swarm computation gracefully

### AgentResult + AlphaMultiplier (extended in `src/intelligence/schemas.py`)
- `AgentResult` now has `path: Literal["deterministic", "llm_swarm"]`, `shadow_only: bool = True`, `latency_ms: float = 0.0`, `error: str | None = None`
- `AlphaMultiplier` now has `symbol`, `timeframe`, `path_a_multiplier`, `path_b_multiplier`, `path_b_discount`, `production_multiplier`, `shadow_only`
- `is_production_ready` now returns `not self.shadow_only` (all shadow until proven)

### FeatureVector (`src/core/ml/features.py`)
- 55-field frozen Pydantic model covering I1-I7 feature tiers
- All fields Optional — no imputation at this layer
- `ts: str` (ISO-8601) for polars DataFrame compatibility at training time
- Single source of truth: add a field once here, extractor + training query follow

### IAlphaContributor protocol (`src/core/agents/alpha_contributor.py`)
- Canonical location moved from `src/intelligence/swarm/interface.py`
- New contract: `async compute(context: SwarmContext) -> AgentResult`
- Added: `warm_up() -> None`, `health_check() -> dict[str, Any]`
- `src/intelligence/swarm/interface.py` is now a backward-compat re-export shim

### Archival
- 4 old stub agents archived with deprecation headers (wrong `get_multiplier(sid, dict)` contract)
- `config/intelligence_contributors.json` emptied — no active contributors until Phase 66

## Test Results

8 tests written and passing in `tests/unit/test_swarm_protocol.py`:
- `test_context_cache_build_returns_swarm_context`
- `test_context_cache_returns_none_for_unknown_symbol`
- `test_context_is_immutable`
- `test_agent_result_has_path_field`
- `test_agent_result_rejects_out_of_bounds_multiplier`
- `test_alpha_multiplier_has_symbol_and_timeframe`
- `test_feature_vector_is_frozen`
- `test_feature_vector_defaults_to_none_for_optional_fields`

Pre-existing failures: 37 (unchanged before/after — confirmed by stash baseline test).

## Decisions Made

1. `AgentResult` gets `path` field — required for `IAlphaContributor.compute()` to return a self-describing result without the caller knowing which path produced it.
2. `AlphaMultiplier.is_production_ready` reads `not self.shadow_only` — semantically correct (shadow flag is the truth, not the path label).
3. `IAlphaContributor` moved to `src/core/agents/` — protocol belongs in core (reusable by any service), not in intelligence layer.
4. `SwarmContext.ts: Any` to avoid circular import — `context.py` imports `IntelligenceEvent` only under `TYPE_CHECKING`.
5. `FeatureVector.ts: str` — polars returns strings from CSV/parquet; forcing datetime here would require conversion at every training call site.
6. Old stub agents archived, not deleted — CLAUDE.md archival pattern; deprecation headers explain why and what replaces them.

## Deviations from Plan

None — plan executed exactly as written.

## Known Stubs

None. `intelligence_contributors.json` is intentionally empty (documented: Phase 66 will add SkepticAgent).

## Threat Flags

None. No new network endpoints, auth paths, file access patterns, or schema changes at trust boundaries introduced.

## Self-Check: PASSED

All files present and all commits found:
- src/intelligence/swarm/context.py — FOUND
- src/core/ml/features.py — FOUND
- src/core/ml/__init__.py — FOUND
- src/core/agents/alpha_contributor.py — FOUND
- tests/unit/test_swarm_protocol.py — FOUND
- config/intelligence_contributors.json — FOUND
- Commit 75ece9c1 — FOUND
- Commit be4c3b41 — FOUND
- Commit 0230d8cd — FOUND
- Commit be6f0906 — FOUND
