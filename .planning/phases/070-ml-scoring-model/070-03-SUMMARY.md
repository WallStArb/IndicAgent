---
phase: 070-ml-scoring-model
plan: "03"
subsystem: ml
tags: [lightgbm, mlflow, shap, polars, training, feature-engineering, model-registry]

dependency_graph:
  requires:
    - phase: 070-01
      provides: features_snapshot JSONB column on signal_ledger populated at signal INSERT
  provides:
    - src/intelligence/ml/feature_builder.py — pure-function training matrix builder
    - src/intelligence/services/ml_training_compute_agent.py — MLTrainingComputeAgent
    - services/ml_training_agent.py — systemd oneshot entrypoint
    - ML training deps in requirements.txt (lightgbm, shap, mlflow, polars)
  affects:
    - 070-04 (Plan 04) — MLScorerMultiplierAgent imports SHADOW_FEATURE_KEYS and
      loads shap_importance.json feature_cols from MLflow for column alignment

tech-stack:
  added:
    - lightgbm>=4.0
    - shap>=0.44
    - mlflow>=2.10
    - polars>=1.0
  patterns:
    - Walk-forward 60/20/20 temporal split with no shuffling (no train_test_split)
    - Delta gate on resolved signal count (50 new signals min) before training
    - D-04 regime gate: n>=100 per segment before fitting any model
    - MLflow artifact: shap_importance.json with feature_cols list as inference contract
    - Systemd Type=oneshot service pattern mirroring ml_orchestrator_agent.py
    - Top-level exception catch in _run() → exit 0 for timer cadence preservation

key-files:
  created:
    - src/intelligence/ml/feature_builder.py
    - src/intelligence/services/ml_training_compute_agent.py
    - services/ml_training_agent.py
  modified:
    - requirements.txt

key-decisions:
  - "volume_z_score (not volume_z) is the canonical i1 JSONB key used in training SQL and Python — enforced by grep check in acceptance criteria"
  - "SHADOW_FEATURE_KEYS is exported as a public alias from feature_builder.py so Plan 04 inference agent can import the same key ordering without duplication"
  - "tod_multiplier sourced from i7 JSONB array element 0 with COALESCE 1.0 fallback — ensures train/inference feature shapes always match"
  - "polars added to requirements.txt (was already used in training_data.py but not in requirements)"
  - "SIGUSR1 sent via subprocess systemctl kill after any successful model registration to trigger in-process model reload in alpha-swarm"

patterns-established:
  - "feature_builder.py: pure-function module pattern with _MIN_SAMPLE_SIZE, module logger, no side effects"
  - "encode_features: returns (X, y, final_feature_cols) — final_feature_cols is the inference column-alignment contract"
  - "MLTrainingComputeAgent._run() swallows all exceptions and exits 0 (systemd oneshot timer preservation)"

requirements-completed: []

duration: 8min
completed: "2026-05-13"
---

# Phase 70 Plan 03: ML Training Pipeline Summary

**LightGBM nightly training pipeline with walk-forward CV, SHAP feature importance, and ModelRegistry registration via a systemd oneshot service triggered by indicagent-ml-training.timer**

## Performance

- **Duration:** ~8 min
- **Started:** 2026-05-13T14:38:00Z
- **Completed:** 2026-05-13T14:41:45Z
- **Tasks:** 2
- **Files created/modified:** 4

## Accomplishments

- `feature_builder.py`: SQL-based training matrix builder with no-lookahead enforcement (`f.ts < sl.activated_at`), features_snapshot JSONB flattening, one-hot categorical encoding, and temporal walk-forward split
- `MLTrainingComputeAgent`: full nightly training loop with delta gate (50 signals), D-04 regime gate (n>=100 per segment), 4-segment model training (global + 3 HMM regimes), SHAP, MLflow, ModelRegistry, and SIGUSR1 swarm reload
- `ml_training_agent.py`: systemd oneshot entrypoint mirroring ml_orchestrator_agent.py pattern
- ML dependencies installed and pinned in requirements.txt (lightgbm, shap, mlflow, polars)
- Dry-run verified: exits 0 with `ml_training.delta_gate_skip` when data is insufficient

## Task Commits

1. **Task 1: feature_builder.py + requirements.txt** - `a6bb511b` (feat)
2. **Task 2: MLTrainingComputeAgent + ml_training_agent.py** - `e94b6af9` (feat)

## Files Created/Modified

- `src/intelligence/ml/feature_builder.py` — 273 lines. Pure-function training matrix builder: `build_training_matrix`, `encode_features`, `split_walk_forward`, `filter_segment`, `SHADOW_FEATURE_KEYS` public alias
- `src/intelligence/services/ml_training_compute_agent.py` — 320 lines. MLTrainingComputeAgent class with delta gate, D-04 regime gate, LightGBM walk-forward training, SHAP TreeExplainer, MLflow logging, ModelRegistry.register(), SIGUSR1 swarm reload
- `services/ml_training_agent.py` — 31 lines. Systemd oneshot entrypoint invoking MLTrainingComputeAgent.start()
- `requirements.txt` — added lightgbm>=4.0, shap>=0.44, mlflow>=2.10, polars>=1.0

## Decisions Made

1. `SHADOW_FEATURE_KEYS` exported as a public alias at module level in feature_builder.py so Plan 04's inference agent can import the canonical 25-key ordering without hard-coding it.
2. `tod_multiplier` sourced from `f.i7->0->>'tod_multiplier'` with `COALESCE(..., 1.0)` — the JSONB array element 0 is the I7 trading signal payload that carries the per-signal time-of-day multiplier computed at signal fire time.
3. `polars` added to requirements.txt — it was already used in `src/core/ml/training_data.py` but was not in the pinned dependency list.
4. Python `_SHADOW_FEATURE_KEYS` tuple uses 25 distinct keys (confidence_utils.py `capture_signal_features()` sets exactly 25 keys in the snapshot dict); plan cited 27 but accepted >=25.
5. `encode_features()` aligns validation/test feature matrices to the train-derived `final_cols` ordering using an `_align_X` helper to handle cases where one-hot encoding of smaller data slices may produce different dummy column sets.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Installed missing polars, lightgbm, shap, mlflow dependencies**
- **Found during:** Task 1 (import check after creating feature_builder.py)
- **Issue:** `import polars` failed — polars not installed in the venv. lightgbm, shap, mlflow also missing.
- **Fix:** Added all four deps to requirements.txt; installed via `uv pip install` in the main project venv.
- **Files modified:** requirements.txt
- **Verification:** `python -c "import lightgbm, shap, mlflow, polars, sklearn; print('deps_ok')"` exits 0
- **Committed in:** a6bb511b (Task 1 commit, requirements.txt)

**2. [Rule 3 - Blocking] Created .venv symlink in worktree for pre-commit hook compatibility**
- **Found during:** Task 1 commit (pre-commit hook blocked)
- **Issue:** Pre-commit hook uses `${REPO_ROOT}/.venv/bin/ruff` where REPO_ROOT = worktree path. The worktree has no `.venv` directory.
- **Fix:** Created `ln -s /home/bg/dev/indicagent/.venv /home/bg/.../agent-adf8e87c63ad15b45/.venv` symlink.
- **Files modified:** `.venv` symlink (not a tracked file)
- **Verification:** Pre-commit hook passes with "PASSED: All pre-commit checks passed"
- **Committed in:** Resolved inline before Task 1 commit

---

**Total deviations:** 2 auto-fixed (both Rule 3 - Blocking)
**Impact on plan:** Both auto-fixes were infrastructure setup issues, not logic changes. No scope creep.

## Issues Encountered

None beyond the blocking auto-fixes above.

## Next Phase Readiness

- Plan 04 (MLScorerMultiplierAgent inference agent) can now import `SHADOW_FEATURE_KEYS` from `feature_builder.py` for column alignment
- MLflow artifact `shap_importance.json` will contain `feature_cols` list as the inference contract once models are trained
- MLflow server at `http://localhost:5000` must be running before training runs (Type=oneshot needs it)
- `indicagent-ml-training.service` + `.timer` systemd units (from Plan 02 or manually installed) complete the deployment

---
*Phase: 070-ml-scoring-model*
*Completed: 2026-05-13*
