---
phase: 82-ml-intelligence-quality-qualitative-foundation
plan: "02"
subsystem: hmm-regime-multitf
tags: [hmm, regime, multi-tf, entropy, velocity, sigusr1, hot-reload, smc-tier]
dependency_graph:
  requires: [82-01]
  provides: [HMM-multi-tf-instances, hmm_regime_entropy, hmm_regime_velocity, SIGUSR1-hot-reload]
  affects: [TIER_SMC, SMCContext, intelligence_pipeline_agent, regime-soft-gate-plan04]
tech_stack:
  added: []
  patterns: [parameterized-dataclass, TF-adaptive-window, SIGUSR1-hot-reload, shannon-entropy]
key_files:
  created:
    - tests/unit/test_hmm_regime_multitf.py
  modified:
    - src/intelligence/features/smc_context/hmm_regime.py
    - src/intelligence/schemas.py
    - src/intelligence/register_plugins.py
    - services/intelligence_pipeline_agent.py
decisions:
  - "HMM instances kept in TIER_SMC (not TIER_I4) — minimizes schema churn; fields remain in SMCContext"
  - "VELOCITY_WINDOW_BY_TF: {1m:5, 5m:5, 15m:4, 1h:3} — TF-adaptive deque maxlen"
  - "hmm_plugin backward-compat alias = hmm_1m_plugin; no external importers confirmed"
  - "entropy/velocity are None when warmed_up=False — prevents garbage during convergence window"
metrics:
  duration_minutes: 7
  completed_date: "2026-05-13"
  tasks_completed: 3
  tasks_total: 3
  files_changed: 4
---

# Phase 82 Plan 02: HMM Multi-TF Parameterization + Entropy/Velocity Outputs Summary

**One-liner:** Four per-TF HMMRegimePlugin instances (1m/5m/15m/1h) with TF-appropriate lookbacks registered in TIER_SMC, Shannon entropy and velocity outputs added, SIGUSR1 hot-reload wired into intelligence_pipeline_agent, and full unit test coverage.

---

## Objective

Parameterize `HMMRegimePlugin` for multi-TF deployment, add `hmm_regime_entropy` and `hmm_regime_velocity` fields to every HMM output bar, register four named instances in TIER_SMC, extend `SMCContext`, and wire SIGUSR1 hot-reload into the intelligence pipeline agent.

---

## Task 1: Parameterize HMMRegimePlugin + Extend SMCContext

**Files modified:** `src/intelligence/features/smc_context/hmm_regime.py`, `src/intelligence/schemas.py`

**Changes:**
- Added `timeframe: str = "1m"` and `lookback: int = 200` as init params to `HMMRegimePlugin`
- Moved `name`, `outputs`, `inputs` to `field(init=False)` — set in `__post_init__`
- `__post_init__` sets `self.name = f"smc_HMMRegime_{self.timeframe}"` and `self.inputs` from TF/lookback
- Added `VELOCITY_WINDOW_BY_TF: dict[str, int] = {1m:5, 5m:5, 15m:4, 1h:3}` module constant
- Extended `_reset_state()` to initialize `prob_history` deque with TF-adaptive maxlen
- Extended `_build_output()` to compute and return:
  - `hmm_regime_entropy`: Shannon entropy `-sum(p * log2(p + 1e-10))` across 3 state probs
  - `hmm_regime_velocity`: rate-of-change of dominant state prob over history window
  - Both fields are `None` when `warmed_up=False` to prevent garbage during convergence
- Added `_load_tf_parameters()` private method: loads `config/hmm_parameters_{tf}.json` if present, falls back to base file
- Added `reload_parameters()` public method: hot-reloads params without resetting forward state
- Backward-compat: module-level `plugin = HMMRegimePlugin(timeframe="1m", lookback=200)`
- `SMCContext`: added `hmm_regime_entropy: float | None = None` and `hmm_regime_velocity: float | None = None` grouped with existing HMM fields

**Verification:**
```
HMMRegimePlugin(timeframe="5m", lookback=200).name == "smc_HMMRegime_5m" ✓
"hmm_regime_entropy" in HMMRegimePlugin().outputs ✓
SMCContext().hmm_regime_entropy exists ✓
```

---

## Task 2: Register Four HMM Instances in TIER_SMC

**Files modified:** `src/intelligence/register_plugins.py`

**Changes:**
- Replaced `from src.intelligence.features.smc_context.hmm_regime import plugin as hmm_plugin` with `HMMRegimePlugin` class import
- Added four instances after all imports:
  - `hmm_1m_plugin = HMMRegimePlugin(timeframe="1m", lookback=200)`
  - `hmm_5m_plugin = HMMRegimePlugin(timeframe="5m", lookback=200)`
  - `hmm_15m_plugin = HMMRegimePlugin(timeframe="15m", lookback=150)`
  - `hmm_1h_plugin = HMMRegimePlugin(timeframe="1h", lookback=100)`
  - `hmm_plugin = hmm_1m_plugin` (backward-compat alias)
- Updated `TIER_SMC` list to include all four instances (replacing single `hmm_plugin.name`)
- Updated `SMC_WAVE_A` list to include all four instances
- Updated `validate_schema_coverage()` SMC section to include all four instances
- Updated `registry.register_pattern()` calls to register all four instances

**Lookbacks (matching CONTEXT.md D-02 table):**

| TF  | Lookback | Duration    |
|-----|----------|-------------|
| 1m  | 200      | ~3.3h       |
| 5m  | 200      | ~16h        |
| 15m | 150      | ~37h        |
| 1h  | 100      | ~10 days    |

**Verification:**
```
sum(1 for p in TIER_SMC if p.startswith("smc_HMMRegime_")) == 4 ✓
smc_HMMRegime_1m/5m/15m/1h all in TIER_SMC ✓
```

---

## Task 3: SIGUSR1 Handler + Unit Tests

**Files modified:** `services/intelligence_pipeline_agent.py`
**Files created:** `tests/unit/test_hmm_regime_multitf.py`

**intelligence_pipeline_agent.py changes:**
- Added `import signal as _signal`
- Added `from src.intelligence.features.smc_context.hmm_regime import HMMRegimePlugin`
- Added `self._background_tasks: set = set()` in `__init__`
- In `_setup()`: registered `loop.add_signal_handler(_signal.SIGUSR1, self._on_hmm_sigusr1)` after shadow governance setup
- Added `_on_hmm_sigusr1()`: sync handler, schedules async task via `asyncio.create_task`, stores in `_background_tasks`
- Added `_reload_hmm_parameters()`: async method — iterates TIER_SMC, filters `HMMRegimePlugin` instances by `isinstance`, calls `plugin.reload_parameters()` per TF, logs `hmm_reload=True` with `reloaded_tfs` list; per-TF errors caught and logged, pipeline does not crash

**Unit tests (10 tests, all passing):**
- `test_hmm_regime_plugin_name_per_tf` (parametrized x4): name, TF, lookback correct
- `test_hmm_regime_outputs_include_entropy_and_velocity`: both fields in `.outputs`
- `test_hmm_regime_entropy_math`: uniform → log2(3) ≈ 1.585; peaked → ~0
- `test_hmm_regime_velocity_window_by_tf`: module constant maps correctly
- `test_hmm_regime_reload_parameters_idempotent`: two calls, no exception, K preserved
- `test_hmm_regime_reload_parameters_with_tf_file`: loads TF-suffixed file via tmp_path
- `test_register_plugins_exposes_four_hmm_instances`: all four in TIER_SMC

---

## Tier Placement Decision

**Kept in TIER_SMC** (not moved to TIER_I4). Rationale:
- Moving to TIER_I4 would require moving all HMM fields from `SMCContext` to `I4Context`, which has `extra="forbid"` — larger schema churn with no behavioral benefit
- `SMCContext` does not have `extra="forbid"` so new fields added there without errors
- Intent to move to TIER_I4 documented for Phase 83

---

## Deviations from Plan

None — plan executed exactly as written. The `validate_schema_coverage()` function in `register_plugins.py` also needed updating (it also listed `hmm_plugin` in the SMC check list), which was done as part of Task 2 (required for correctness, not an out-of-plan addition).

---

## Self-Check: PASSED

- `src/intelligence/features/smc_context/hmm_regime.py` modified: YES
- `src/intelligence/register_plugins.py` modified: YES (4 instances, TIER_SMC, SMC_WAVE_A, validate_schema_coverage, register_pattern)
- `src/intelligence/schemas.py` modified: YES (hmm_regime_entropy, hmm_regime_velocity in SMCContext)
- `services/intelligence_pipeline_agent.py` modified: YES (SIGUSR1 handler + _on_hmm_sigusr1 + _reload_hmm_parameters)
- `tests/unit/test_hmm_regime_multitf.py` created: YES
- All 10 unit tests pass: YES
- TIER_SMC contains exactly 4 HMM instances: YES
- ruff check exits 0 on all modified files: YES
- Commits: f83623e6, 3b135368, 8275ae58
