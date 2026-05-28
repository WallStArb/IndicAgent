# Project Cleanup and Restructure Implementation Plan

**Version:** 1.0
**Status:** archived
**Last Updated:** 2026-05-27
> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Clean up dead code, reorganize test directories to eliminate confusion, split oversized test files, and trim CLAUDE.md to reduce navigation friction.

**Architecture:** Five independent sections executed in order. Each section produces a self-contained commit. No production code changes except removing dead modules.

**Tech Stack:** pytest, bash, git

---

## File Structure

### Deleted
- `src/indicators/` (empty directory)
- `tests/unit/indicators/` (empty directory)
- `tests/unit/intelligence/ml/` (empty directory)
- `tests/unit/intelligence/monitoring/` (empty directory)
- `tests/unit/pipeline_tests/` (merged into `tests/unit/pipeline/`)
- `tests/unit/service_tests/` (merged into `tests/unit/services/`)

### Created
- `tests/unit/pipeline/test_output_queue_integration.py` (renamed from pipeline_tests)
- `tests/unit/intelligence/trading/test_trend_following.py`
- `tests/unit/intelligence/trading/test_mean_reversion.py`
- `tests/unit/intelligence/trading/test_liquidity_sweep_reclaim.py`
- `tests/unit/intelligence/trading/test_multi_timeframe_alignment.py`
- `tests/unit/intelligence/trading/test_squeeze_expansion.py`
- `tests/unit/intelligence/trading/test_liquidity_hunt.py`
- `tests/unit/intelligence/trading/test_supply_demand_setup.py`
- `tests/unit/intelligence/trading/test_zone_enhancements.py`
- `tests/unit/intelligence/trading/test_candlestick_tier1_setups.py`
- `tests/unit/intelligence/trading/test_hmm_gradient_continuity.py`

### Modified
- `CLAUDE.md` (trim completed-phase gotchas)
- `docs/gotchas.md` (absorb historical gotchas from CLAUDE.md)
- Various test files moved between directories

---

## Task 1: Remove dead directories and purge cache

**Files:**
- Delete: `src/indicators/` (entire directory)
- Delete: `tests/unit/indicators/` (empty)
- Delete: `tests/unit/intelligence/ml/` (empty)
- Delete: `tests/unit/intelligence/monitoring/` (empty)

- [ ] **Step 1: Delete empty source directories**

```bash
rm -rf src/indicators/
rm -rf tests/unit/indicators/
rm -rf tests/unit/intelligence/ml/
rm -rf tests/unit/intelligence/monitoring/
```

- [ ] **Step 2: Purge all __pycache__ directories outside .venv**

```bash
find . -name "__pycache__" -type d -not -path "./.venv/*" -not -path "./.git/*" -not -path "./dashboard/*" -exec rm -rf {} + 2>/dev/null
echo "done"
```

- [ ] **Step 3: Verify no imports reference src/indicators**

```bash
grep -r "from src\.indicators\|import src\.indicators" --include="*.py" . 2>/dev/null | grep -v __pycache__ | grep -v .venv
```

Expected: no output (no references found).

- [ ] **Step 4: Run tests to confirm nothing broke**

```bash
.venv/bin/pytest tests/unit/ -q --tb=no 2>&1 | tail -5
```

Expected: 4049 tests collected, same 3 pre-existing collection errors.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "chore: remove empty src/indicators/ and dead test directories, purge __pycache__"
```

---

## Task 2: Merge tests/unit/pipeline_tests/ into tests/unit/pipeline/

`tests/unit/pipeline_tests/` has 8 files testing pipeline internals. `tests/unit/pipeline/` has 4 files. Both test the same subsystem. Merge them into `tests/unit/pipeline/`.

**Files:**
- Move: `tests/unit/pipeline_tests/*.py` → `tests/unit/pipeline/`
- Rename: `tests/unit/pipeline_tests/test_output_queue.py` → `tests/unit/pipeline/test_output_queue_integration.py` (avoid collision)
- Delete: `tests/unit/pipeline_tests/` after move

- [ ] **Step 1: List files to move and check for name collisions**

```bash
ls tests/unit/pipeline_tests/*.py
echo "---"
ls tests/unit/pipeline/*.py
```

Expected collision: `test_output_queue.py` exists in both directories.

- [ ] **Step 2: Move files, renaming the colliding one**

```bash
# Move non-colliding files
for f in tests/unit/pipeline_tests/test_cache_manager.py tests/unit/pipeline_tests/test_executor.py tests/unit/pipeline_tests/test_executor_state_threading.py tests/unit/pipeline_tests/test_orchestrator_checkpoint_assembly.py tests/unit/pipeline_tests/test_orchestrator_integration.py tests/unit/pipeline_tests/test_signal_processor.py tests/unit/pipeline_tests/test_state_manager.py; do
  mv "$f" tests/unit/pipeline/
done

# Rename colliding file
mv tests/unit/pipeline_tests/test_output_queue.py tests/unit/pipeline/test_output_queue_integration.py
```

- [ ] **Step 3: Remove empty directory**

```bash
rm -rf tests/unit/pipeline_tests/
```

- [ ] **Step 4: Run pipeline tests to verify**

```bash
.venv/bin/pytest tests/unit/pipeline/ -q --tb=short 2>&1 | tail -10
```

Expected: all pipeline tests pass.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "chore: merge pipeline_tests/ into pipeline/ test directory"
```

---

## Task 3: Merge tests/unit/service_tests/ into tests/unit/services/

`tests/unit/service_tests/` has 39 files testing individual service agents. `tests/unit/services/` has 8 files. Both test the same layer. Merge into `tests/unit/services/`.

**Files:**
- Move: `tests/unit/service_tests/*.py` → `tests/unit/services/`
- Delete: `tests/unit/service_tests/` after move

- [ ] **Step 1: Check for name collisions**

```bash
comm -12 <(ls tests/unit/service_tests/*.py | xargs -I{} basename {}) <(ls tests/unit/services/*.py | xargs -I{} basename {})
```

Expected: no output (no collisions).

- [ ] **Step 2: Move all files**

```bash
mv tests/unit/service_tests/*.py tests/unit/services/
```

- [ ] **Step 3: Remove empty directory**

```bash
rm -rf tests/unit/service_tests/
```

- [ ] **Step 4: Run service tests to verify**

```bash
.venv/bin/pytest tests/unit/services/ -q --tb=short 2>&1 | tail -10
```

Expected: all service tests pass.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "chore: merge service_tests/ into services/ test directory"
```

---

## Task 4: Relocate stray top-level test files

64 test files sit directly in `tests/unit/` (not in a subdirectory). Move them to appropriate subdirectories based on the module they test.

**Files:**
- Move files matching `tests/unit/test_<module>*.py` to their corresponding test subdirectory

The mapping (determined by import inspection):

| File | Target Directory | Reason |
|------|-----------------|--------|
| `test_base_agent.py` | `tests/unit/core/` | Tests `src.core.agent.base` |
| `test_base_group_service.py` | `tests/unit/core/` | Tests `src.core.ai` |
| `test_base_writer_agent.py` | `tests/unit/core/` | Tests `src.core.agent.base` (writer contract) |
| `test_core_ai_*.py` (4 files) | `tests/unit/core/` | Tests `src.core.ai.*` |
| `test_bar_accumulator_*.py` (2 files) | `tests/unit/core/` | Tests `src.core.bar_accumulator` |
| `test_bar_normalizer.py` | `tests/unit/core/` | Tests `src.core.bar_normalizer` |
| `test_stream_keys*.py` (4 files) | `tests/unit/core/` | Tests `src.core.stream_keys` |
| `test_state_checkpoint_serde.py` | `tests/unit/core/` | Tests state serialization |
| `test_process_manifest.py` | `tests/unit/core/` | Tests process topology |
| `test_settings*.py` (2 files) | `tests/unit/config/` | Tests `src.config.settings` |
| `test_metrics.py` | `tests/unit/observability/` | Tests `src.observability.metrics` |
| `test_plugin_validator.py` | `tests/unit/intelligence/` | Tests plugin validation |
| `test_pipeline_*.py` (5 files) | `tests/unit/pipeline/` | Tests pipeline behavior |
| `test_candlestick_patterns.py` | `tests/unit/intelligence/indicators/` | Tests candlestick patterns |
| `test_cross_timeframe_confluence.py` | `tests/unit/intelligence/` | Tests confluence |
| `test_cross_tier_validation.py` | `tests/unit/intelligence/` | Tests tier validation |
| `test_signal_*.py` (4 files) | `tests/unit/intelligence/trading/` | Tests signal/trading logic |
| `test_winner_selector.py` | `tests/unit/intelligence/trading/` | Tests winner selection |
| `test_capture_signal_features.py` | `tests/unit/intelligence/trading/` | Tests confidence utils |
| `test_lifecycle_transitions.py` | `tests/unit/intelligence/trading/` | Tests lifecycle |
| `test_skeptic*.py` (2 files) | `tests/unit/services/` | Tests skeptic agent (service) |
| `test_graduation*.py` (2 files) | `tests/unit/services/` | Tests graduation service |
| `test_hmm_*.py` (2 files) | `tests/unit/intelligence/` | Tests HMM |
| `test_swarm_settings_metrics.py` | `tests/unit/services/` | Tests swarm settings |
| `test_shadow_auditor_agent.py` | `tests/unit/services/` | Tests shadow auditor |
| `test_signal_auditor_agent.py` | `tests/unit/services/` | Tests signal auditor |
| `test_ctx_writer_agent.py` | `tests/unit/services/` | Tests ctx writer |
| `test_feature_validation_compute_agent.py` | `tests/unit/services/` | Tests feature validation |
| `test_regime_gate_soft.py` | `tests/unit/intelligence/` | Tests regime gate |
| `test_signals_api_*.py` (5 files) | `tests/unit/api/` | Tests API routes |
| `test_transform_recorder.py` | `tests/unit/intelligence/` | Tests transform recorder |
| `test_dlq_payload.py` | `tests/unit/core/` | Tests DLQ schema |
| `test_market_events_schema.py` | `tests/unit/core/` | Tests market event schemas |
| `test_roll_chain_derivation.py` | `tests/unit/core/` | Tests roll chain logic |
| `test_service_contract_resolution.py` | `tests/unit/services/` | Tests contract resolution |
| `test_warmup_provider.py` | `tests/unit/persistence/` | Tests warmup provider |
| `test_validation_engine.py` | `tests/unit/intelligence/` | Tests validation engine |
| `test_reference_implementations.py` | `tests/unit/intelligence/` | Tests reference impls |
| `test_vix_context.py` | `tests/unit/intelligence/` | Tests VIX context |
| `test_prompt_utils.py` | `tests/unit/core/` | Tests prompt utils |
| `test_stats_utils.py` | `tests/unit/core/` | Tests stats utils |
| `test_signal_quality_hardening.py` | `tests/unit/intelligence/trading/` | Tests signal quality |
| `test_multiplier_agent.py` | `tests/unit/core/` | Tests multiplier agent |
| `test_signal_ledger_repository.py` | `tests/unit/persistence/` | Tests signal ledger repo |
| `test_pipeline_attribution.py` | `tests/unit/pipeline/` | Tests pipeline attribution |

- [ ] **Step 1: Create any missing target directories**

```bash
mkdir -p tests/unit/core tests/unit/config tests/unit/observability tests/unit/pipeline tests/unit/intelligence/indicators tests/unit/intelligence/trading tests/unit/services tests/unit/api tests/unit/persistence
```

- [ ] **Step 2: Move core tests**

```bash
for f in test_base_agent.py test_base_group_service.py test_base_writer_agent.py test_core_ai_base_agent.py test_core_ai_context.py test_core_ai_context_typed_tiers.py test_core_ai_output.py test_bar_accumulator_session_boundary.py test_bar_accumulator_validation.py test_bar_normalizer.py test_stream_keys.py test_stream_keys_ctx.py test_stream_keys_dlq.py test_stream_keys_lifecycle.py test_stream_keys_signals.py test_stream_keys_htf.py test_stream_keys_aggregated.py test_state_checkpoint_serde.py test_process_manifest.py test_dlq_payload.py test_market_events_schema.py test_roll_chain_derivation.py test_prompt_utils.py test_stats_utils.py test_multiplier_agent.py; do
  mv "tests/unit/$f" tests/unit/core/ 2>/dev/null
done
```

- [ ] **Step 3: Move config tests**

```bash
mv tests/unit/test_settings.py tests/unit/test_settings_thread_safety.py tests/unit/config/ 2>/dev/null
```

- [ ] **Step 4: Move observability tests**

```bash
mv tests/unit/test_metrics.py tests/unit/observability/ 2>/dev/null
```

- [ ] **Step 5: Move pipeline tests**

```bash
for f in test_pipeline_determinism.py test_pipeline_exception_isolation.py test_pipeline_parallelization.py test_pipeline_recorder_wiring.py test_pipeline_attribution.py; do
  mv "tests/unit/$f" tests/unit/pipeline/ 2>/dev/null
done
```

- [ ] **Step 6: Move API tests**

```bash
for f in test_signals_api_attribution.py test_signals_api_detail.py test_signals_api_stats.py test_signals_api_tier.py test_signals_api_timeframe_filter.py; do
  mv "tests/unit/$f" tests/unit/api/ 2>/dev/null
done
```

- [ ] **Step 7: Move intelligence tests**

```bash
# Intelligence root
for f in test_cross_timeframe_confluence.py test_cross_tier_validation.py test_plugin_validator.py test_hmm_regime_multitf.py test_regime_gate_soft.py test_transform_recorder.py test_validation_engine.py test_reference_implementations.py test_vix_context.py; do
  mv "tests/unit/$f" tests/unit/intelligence/ 2>/dev/null
done

# Intelligence indicators
mv tests/unit/test_candlestick_patterns.py tests/unit/intelligence/indicators/ 2>/dev/null

# Intelligence trading
for f in test_signal_ledger_repository.py test_signal_quality_hardening.py test_winner_selector.py test_capture_signal_features.py test_lifecycle_transitions.py; do
  mv "tests/unit/$f" tests/unit/intelligence/trading/ 2>/dev/null
done
```

- [ ] **Step 8: Move service tests**

```bash
for f in test_skeptic_agent.py test_skeptic_prompts_v2.py test_graduation.py test_graduation_compute_agent.py test_swarm_settings_metrics.py test_shadow_auditor_agent.py test_signal_auditor_agent.py test_ctx_writer_agent.py test_feature_validation_compute_agent.py test_service_contract_resolution.py; do
  mv "tests/unit/$f" tests/unit/services/ 2>/dev/null
done
```

- [ ] **Step 9: Move persistence tests**

```bash
mv tests/unit/test_warmup_provider.py tests/unit/test_signal_ledger_repository.py tests/unit/persistence/ 2>/dev/null
```

- [ ] **Step 10: Verify no stray test files remain in tests/unit/ root**

```bash
ls tests/unit/test_*.py 2>/dev/null
```

Expected: no output (all moved). If any remain, move them to the appropriate directory based on their imports.

- [ ] **Step 11: Run full test suite**

```bash
.venv/bin/pytest tests/unit/ -q --tb=no 2>&1 | tail -5
```

Expected: 4049 tests collected, same or fewer collection errors.

- [ ] **Step 12: Commit**

```bash
git add -A
git commit -m "chore: relocate stray test files to proper subdirectories"
```

---

## Task 5: Split test_trading_setups.py into per-plugin files

`tests/unit/intelligence/test_trading_setups.py` is 1420 lines with 10 test classes, one per I7 setup plugin. Split into individual files for navigability.

**Files:**
- Split: `tests/unit/intelligence/test_trading_setups.py` → 10 files in `tests/unit/intelligence/trading/`
- Delete: `tests/unit/intelligence/test_trading_setups.py` after split

- [ ] **Step 1: Identify class boundaries in the source file**

```bash
grep -n "^class " tests/unit/intelligence/test_trading_setups.py
```

Expected output (line numbers approximate):
```
14:class TestTrendFollowing:
XX:class TestMeanReversion:
XX:class TestLiquiditySweepReclaim:
XX:class TestMultiTimeframeAlignment:
XX:class TestSqueezeExpansion:
XX:class TestLiquidityHunt:
XX:class TestSupplyDemandSetup:
XX:class TestZoneEnhancements:
XX:class TestCandlestickTier1Patterns:
XX:class TestHMMGradientContinuity:
```

- [ ] **Step 2: Read the shared imports and helper from the file header**

```bash
head -13 tests/unit/intelligence/test_trading_setups.py
```

The header contains shared imports (`numpy`, `make_ohlcv` helper). Each split file needs these imports.

- [ ] **Step 3: Split each class into its own file**

For each class, create `tests/unit/intelligence/trading/test_<snake_case_name>.py` with:
1. The shared imports from the header
2. The class and all its methods

Target files:
- `test_trend_following.py` ← `TestTrendFollowing`
- `test_mean_reversion.py` ← `TestMeanReversion`
- `test_liquidity_sweep_reclaim.py` ← `TestLiquiditySweepReclaim`
- `test_multi_timeframe_alignment.py` ← `TestMultiTimeframeAlignment`
- `test_squeeze_expansion.py` ← `TestSqueezeExpansion`
- `test_liquidity_hunt.py` ← `TestLiquidityHunt`
- `test_supply_demand_setup.py` ← `TestSupplyDemandSetup`
- `test_zone_enhancements.py` ← `TestZoneEnhancements`
- `test_candlestick_tier1_setups.py` ← `TestCandlestickTier1Patterns`
- `test_hmm_gradient_continuity.py` ← `TestHMMGradientContinuity`

- [ ] **Step 4: Delete the original monolithic file**

```bash
rm tests/unit/intelligence/test_trading_setups.py
```

- [ ] **Step 5: Run the split tests to verify**

```bash
.venv/bin/pytest tests/unit/intelligence/trading/ -q --tb=short 2>&1 | tail -10
```

Expected: all trading tests pass, same test count as before split.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "chore: split test_trading_setups.py into per-plugin test files"
```

---

## Task 6: Trim CLAUDE.md and archive stale docs

**Files:**
- Modify: `CLAUDE.md`
- Modify: `docs/gotchas.md` (if exists) or create it
- Move: completed-phase plans from `docs/plans/` to `docs/plans/archive/`

- [ ] **Step 1: Identify CLAUDE.md entries that reference completed phases**

Read CLAUDE.md and find entries marked "FIXED", "COMPLETE", or referencing completed phases (084-092, 100). These should move to `docs/gotchas.md` as historical reference.

Entries to move:
- `lifecycle-writer crash (FIXED)` → gotchas
- `Memory + OTel bugs (FIXED)` → gotchas
- `Signal quality hardening (COMPLETE 2026-05-14)` → gotchas
- `CIS weights column mismatch (FIXED in 091)` → gotchas
- `1d backfill + lifecycle replay` → gotchas
- `Sunday service audit` → gotchas

- [ ] **Step 2: Move historical entries to docs/gotchas.md**

Create or append to `docs/gotchas.md` with the historical entries, organized under a "Resolved Issues" section with dates.

- [ ] **Step 3: Remove moved entries from CLAUDE.md**

Remove the entries identified in Step 1 from CLAUDE.md. Keep only actively-relevant gotchas and rules.

- [ ] **Step 4: Verify CLAUDE.md is under 160 lines**

```bash
wc -l CLAUDE.md
```

Target: under 160 lines.

- [ ] **Step 5: Move completed-phase plans to archive**

```bash
# Move plans for completed phases (088-093, 100) to archive
for f in docs/plans/*088* docs/plans/*089* docs/plans/*090* docs/plans/*091* docs/plans/*092* docs/plans/*093* docs/plans/*100*; do
  if [ -f "$f" ]; then
    mv "$f" docs/plans/archive/
  fi
done
```

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "docs: trim CLAUDE.md, archive completed-phase plans and gotchas"
```

---

## Task 7: Final verification

- [ ] **Step 1: Run full test suite**

```bash
.venv/bin/pytest tests/unit/ -q --tb=short 2>&1 | tail -15
```

Expected: 4049 tests collected, same or fewer errors than baseline.

- [ ] **Step 2: Run lint and format**

```bash
.venv/bin/ruff check . --fix && .venv/bin/black .
```

Expected: no errors.

- [ ] **Step 3: Verify test directory structure is clean**

```bash
find tests/unit -type d | sort
```

Expected: no empty directories, no duplicate-named directories.

- [ ] **Step 4: Verify no dead imports**

```bash
grep -r "from src\.indicators" --include="*.py" . 2>/dev/null | grep -v __pycache__ | grep -v .venv
```

Expected: no output.
