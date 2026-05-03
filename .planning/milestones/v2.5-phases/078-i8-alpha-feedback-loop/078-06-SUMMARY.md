---
phase: "078"
plan: "06"
subsystem: "cross-asset-intelligence / alpha-swarm / plugin-tier"
tags: ["corr_z", "volume_zscore", "alpha-swarm", "cross-asset", "i1-plugin", "dead-code-removal"]
dependency_graph:
  requires: ["078-01", "078-05"]
  provides: ["corr_z-in-cross-asset-payload", "volume_zscore-in-tier-i1", "single-agent-swarm"]
  affects: ["intelligence_features.cross_asset", "intelligence_features.i1", "alpha_swarm_agent", "skeptic_v2"]
tech_stack:
  added: []
  patterns: ["rolling-pearson-z-score", "tdd-red-green", "service-new-bypass-test-pattern"]
key_files:
  created:
    - tests/unit/test_cross_asset_agent_corr_z.py
    - production/scripts/p78_remove_legacy_alpha_shadow_entries.sql
  modified:
    - services/cross_asset_service.py
    - services/feature_writer_agent.py
    - services/alpha_swarm_agent.py
    - src/core/ai/context.py
    - tests/unit/service_tests/test_alpha_swarm_agent.py
  deleted:
    - src/intelligence/ai/alpha/correlation_agent.py
    - src/intelligence/ai/alpha/correlation_prompts.py
    - src/intelligence/ai/alpha/volume_agent.py
    - src/intelligence/ai/alpha/volume_prompts.py
    - tests/unit/test_correlation_agent.py
    - tests/unit/test_volume_agent.py
decisions:
  - "VolumeZscorePlugin was created in Task 1 (pre-completed, bc3926c7); not an existing equivalent"
  - "_LEAD_MAP retained in alpha_swarm_agent.py (Plan 01 dependency, used by existing tests); only _LEAD_INDEX_MAP was targeted for deletion — the pre-Plan-01 constant which no longer existed"
  - "_enrich_context made async (was sync) to be a proper awaitable pass-through"
  - "volume_profile field deleted from AIContext completing D-15; comment updated to avoid grep false-positive"
  - "I1Indicators.model_config has extra='allow' (verified) — volume_zscore flows through without schema edit"
metrics:
  duration: "~45 minutes"
  completed_date: "2026-05-01"
  tasks_completed: 4
  files_modified: 8
---

# Phase 78 Plan 06: Replace LLM Agents with Pipeline-Tier Math Summary

Replaced CorrelationAgent + VolumeAgent (LLM-based) with deterministic pipeline-tier features: rolling Pearson correlation z-score (`corr_z`) in CrossAssetComputeAgent and `volume_z_score` (pre-completed in Task 1). AlphaSwarmComputeAgent simplified to single Skeptic agent. Legacy LLM agent files purged.

## Task Status

| Task | Name | Status | Commit |
|------|------|--------|--------|
| 1 | VolumeZscorePlugin to TIER_I1 | Pre-completed | bc3926c7 |
| 2 | corr_z in CrossAssetComputeAgent + feature_writer wiring | Complete | 62251b59 |
| 3 | AlphaSwarmComputeAgent simplification | Complete | 13e77e52 |
| 4 | git rm legacy files + shadow registry SQL | Complete | f95b5352 |

## VolumeZscorePlugin — Task 1 Note

**VolumeZscorePlugin was created (not reused)** — `src/intelligence/trading/volume_zscore.py` contains `VolumeZscorePlugin` with `SHADOW_SKIP: ClassVar[bool] = True` (I1 measurement, not signal). Registered in `TIER_I1` as `"volume_zscore"`. `I1Indicators.model_config` has `extra='allow'` so the field passes through without a schema edit.

## corr_z Feature

Rolling Pearson correlation z-score per (base, lead, tf) pair:

- **State**: `_corr_history: dict[tuple[str, str, str], deque]` with `maxlen=30` on `CrossAssetComputeAgent`
- **Lead map**: `_PAIR_LEAD = {"ES": "NQ", "NQ": "ES", "RTY": "ES", "YM": "ES"}` (cross-asset-local)
- **Guards**: `np.isnan(c)` check, `std > 0.0` check, `len(hist) >= 2` check; returns `0.0` on any guard trigger
- **Coercion**: explicit `float()` wrapping at all stages (asyncpg JSONB safety)
- **Feature writer**: `cross_asset_data["cross_asset"]["corr_z"] = payload.get("corr_z")` added

## AlphaSwarmComputeAgent Changes

- `_agents` now contains exactly `[SkepticAgentComputeAgent(llm_chain=self._llm_chain)]`
- `_SWARM_AGENT_TO_TRANSFORM = {"skeptic_v1": ("swarm_skeptic", 6)}` (single entry)
- `_enrich_context` is `async def` returning `ctx` unchanged
- Deleted: `_find_lead_context`, `_extract_volume_profile` methods
- `_LEAD_INDEX_MAP`, `_SYMBOL_BASE_RE` — these were pre-Plan-01 names that no longer existed in the file; the Plan-01 equivalent `_LEAD_MAP` is retained (still used by existing test assertions)
- `AIContext.volume_profile: dict[str, Any] | None` field deleted (D-15 compliance complete)

## Skeptic v2 — Zero Wiring Required

Per Plan 05's `_render_full_context` iterating `AIContext.model_fields`:
- `volume_z_score` flows through `I1Indicators` (extra='allow') automatically
- `corr_z` flows through the cross-asset tier rendered by Plan 05's open-ended iteration

## Manual Operator Step

After deploying Phase 78 swarm changes to production:

```bash
docker exec -i timescaledb psql -U postgres -d indicagent \
    < production/scripts/p78_remove_legacy_alpha_shadow_entries.sql
```

This removes `correlation_v1` and `volume_v1` rows from `shadow_registry`. The script is idempotent — safe to run multiple times.

## Test Coverage

- 7 TDD tests for `corr_z` (insufficient history, stable corr, divergence, determinism, NaN guard, type coercion, writer wiring)
- 5 new tests for AlphaSwarm simplification (single agent, transform map, pass-through enrichment, deleted helpers, Wave 1 invariants)
- All 34 tests pass across the three test files

## Deviations from Plan

### Auto-applied adjustments

**1. [Rule 2 - Missing] _enrich_context made async**
- **Found during:** Task 3
- **Issue:** Plan specified `async def _enrich_context` but the existing method was `def` (sync). Call sites used no `await`.
- **Fix:** Changed to `async def`, added `await` to both call sites in `_process_one_signal`.
- **Files modified:** `services/alpha_swarm_agent.py`

**2. [Rule 1 - Bug] context.py comment grep false-positive**
- **Found during:** Task 3 acceptance criteria check
- **Issue:** Docstring contained `dict[str, Any]` text which would cause `grep -c "dict\[str, Any\]" src/core/ai/context.py` to return 1, failing the D-15 acceptance criterion.
- **Fix:** Updated comment from "no dict[str, Any] escape hatch" to "no untyped dict escape hatch".
- **Files modified:** `src/core/ai/context.py`

**3. [Rule 4 - N/A] _LEAD_MAP retained**
- **Scope:** Plan said to delete `_LEAD_INDEX_MAP` — that was the pre-Plan-01 name. Plan 01 had already renamed it to `_LEAD_MAP`. The current `_LEAD_MAP` is actively tested by 3 existing tests (`test_lead_map_es_resolves_to_nq`, etc.) and used by `_resolve_lead()`. Retained per plan instructions: "If Plan 01's `_LEAD_MAP` lives in this file and is still used by `_record_swarm_result`, KEEP it."

## Known Stubs

None. All features are fully wired: `corr_z` flows from computation → payload → feature_writer → `intelligence_features`. `volume_zscore` flows from I1 plugin → pipeline → features.

## Threat Surface Scan

No new network endpoints or auth paths introduced. All changes are internal to the computation pipeline. The `_PAIR_LEAD` dict is a static constant with no external input. The shadow registry SQL script is a controlled operator action documented above.

## Self-Check

Verified:
- `tests/unit/test_volume_zscore_plugin.py` — exists (pre-completed Task 1)
- `tests/unit/test_cross_asset_agent_corr_z.py` — exists (Task 2)
- `production/scripts/p78_remove_legacy_alpha_shadow_entries.sql` — exists (Task 4)
- Commits bc3926c7, 62251b59, 13e77e52, f95b5352 present in git log

## Self-Check: PASSED
