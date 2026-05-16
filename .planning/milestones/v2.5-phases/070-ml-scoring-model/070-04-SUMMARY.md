---
phase: 070-ml-scoring-model
plan: "04"
subsystem: ml
tags: [lightgbm, inference, multiplier-agent, sigusr1, systemd, model-registry, swarm]

dependency_graph:
  requires:
    - phase: 070-01
      provides: signal_ai_enrichment table, features_snapshot on signal_ledger
    - phase: 070-03
      provides: MLTrainingComputeAgent, feature_builder.SHADOW_FEATURE_KEYS, MLflow shap_importance.json artifact
  provides:
    - src/intelligence/ai/alpha/ml_scorer_agent.py — MLScorerMultiplierAgent
    - services/alpha_swarm_agent.py updated with ML agent + SIGUSR1 hot-reload
    - production/systemd/indicagent-ml-training.service + .timer (installed)
  affects:
    - AlphaSwarm aggregate multiplier (shadow_only=True — no live trade impact until promotion)
    - src/core/ml/registry.py (minimal extension: get_latest_run_id)

tech-stack:
  added: []
  patterns:
    - BaseMultiplierAgent subclass pattern (no LLM — direct LightGBM inference)
    - asyncio.get_running_loop() + add_signal_handler SIGUSR1 hot-reload pattern
    - Systemd Type=oneshot with nightly timer

key-files:
  created:
    - src/intelligence/ai/alpha/ml_scorer_agent.py (314 lines)
    - production/systemd/indicagent-ml-training.service
    - production/systemd/indicagent-ml-training.timer
  modified:
    - services/alpha_swarm_agent.py (MLScorerMultiplierAgent + SIGUSR1 handler)
    - services/service_auditor_agent.py (_DAG_ORDER L8 entry)
    - src/core/ml/registry.py (get_latest_run_id minimal extension)

decisions:
  - "MLScorerMultiplierAgent does not inline load_latest calls — uses _SEGMENTS list for clean iteration over all 4 segments (global + 3 HMM regimes); same semantic coverage as inline calls"
  - "ModelRegistry extended minimally with get_latest_run_id() to expose run_id for MLflow artifact loading without changing load_latest() return signature"
  - "SIGUSR1 handler uses asyncio.get_running_loop() (not get_event_loop()) per Pitfall 5 in RESEARCH.md; captured inside async _setup() so the running loop is guaranteed correct"

key-decisions:
  - "get_latest_run_id added to ModelRegistry rather than changing load_latest() return type — zero impact on Plan 03's training code which only calls register()"
  - "MLScorerMultiplierAgent._extract_features reads from context.i1/i4/i6/smc at inference time (features_snapshot not available on AIContext); column projection onto self._feature_cols ensures train/inference shape alignment"
  - "Auditor cross-check: no swarm_multiplier or adjusted_confidence references found in signal_auditor_agent.py or parity_auditor_agent.py — both safe post-AI-SEP-01 migration (no follow-up TODO needed)"

metrics:
  duration_minutes: 12
  completed_date: "2026-05-13"
  tasks_completed: 3
  files_changed: 6
---

# Phase 70 Plan 04: ML Inference Agent + Swarm Integration Summary

**LightGBM inference closed-loop: MLScorerMultiplierAgent loads promoted models via ModelRegistry, runs shadow-only inference in the alpha swarm aggregate, with nightly SIGUSR1 hot-reload triggered by the ml-training timer.**

## Performance

- **Duration:** ~12 min
- **Started:** 2026-05-13T14:50:00Z
- **Completed:** 2026-05-13T14:52:35Z
- **Tasks:** 3
- **Files created/modified:** 6

## Accomplishments

### Task 1 — MLScorerMultiplierAgent

`src/intelligence/ai/alpha/ml_scorer_agent.py` (314 lines):

- `MLScorerMultiplierAgent` extends `BaseMultiplierAgent` — no LLM dependency
- Five mandatory attributes: `agent_id="ml_scorer_v1"`, `group="alpha"`, `tiers_needed=frozenset()`, `latency_budget_ms=50.0`, `shadow_only=True`
- `_setup_models()`: iterates 4 segments via `_SEGMENTS` list, calls `ModelRegistry.load_latest()` + `get_latest_run_id()` to load the MLflow `shap_importance.json` artifact; populates `self._feature_cols` (training/inference column-alignment contract from Plan 03)
- `_select_model()`: selects `regime_{N}` model when `context.smc.hmm_regime` is set, falls back to `global`; returns `(None, "none")` when no models loaded
- `_extract_features()`: reads from `context.i1/i4/i6/smc/i7`; one-hot encodes categoricals; projects onto `self._feature_cols` order (zero-fill for missing columns)
- `_compute()`: returns `_neutral(error="no_promoted_model")` when `self._models` is empty (first-launch state); runs `model.predict(features)`, clamps `ml_score * 2.0` to `[0.0, 2.0]`
- `ModelRegistry.get_latest_run_id()` added as minimal extension (returns `mlflow_run_id` for latest production model per segment)

### Task 2 — Swarm Integration + SIGUSR1 Hot-reload

`services/alpha_swarm_agent.py`:

- Added `import signal as _signal` at top
- Added `from src.intelligence.ai.alpha.ml_scorer_agent import MLScorerMultiplierAgent`
- Added `"ml_scorer_v1": ("swarm_ml_scorer", 6)` to `_SWARM_AGENT_TO_TRANSFORM`
- `_setup()`: appends `MLScorerMultiplierAgent(pool=self._pool)` after the LLM-agent list; awaits `_agents[-1]._setup_models()`
- Registers SIGUSR1 handler via `asyncio.get_running_loop()` + `loop.add_signal_handler(_signal.SIGUSR1, self._on_sigusr1)`
- `_on_sigusr1()`: sync handler — logs `"alpha_swarm.sigusr1_received"`, schedules `create_task(_reload_ml_models())`
- `_reload_ml_models()`: iterates agents with `_setup_models`, wraps each in try/except; logs `"alpha_swarm.ml_models_reloaded_sigusr1"`

### Task 3 — Service Auditor DAG + Systemd Units

`services/service_auditor_agent.py`:
- Added `"indicagent-ml-training": 8` to `_DAG_ORDER` (L8 analytics tier)
- No `_LAG_THRESHOLDS` or `_AGENT_ID_TO_UNIT` entries (Type=oneshot, no Kafka consumer)

`production/systemd/indicagent-ml-training.service`:
- `Type=oneshot`, `User=bg`, `WorkingDirectory=/home/bg/dev/indicagent`
- `ExecStart=.../.venv/bin/python services/ml_training_agent.py`
- `TimeoutStartSec=7200`

`production/systemd/indicagent-ml-training.timer`:
- `OnCalendar=*-*-* 03:00:00 UTC`, `Persistent=true`

**Installed + enabled:** Both units copied to `/etc/systemd/system/`, daemon-reloaded, timer enabled and active.

## Verification Results

| Check | Result |
|-------|--------|
| ruff check ml_scorer_agent.py | PASS |
| AST parse ml_scorer_agent.py | PASS |
| `MLScorerMultiplierAgent.agent_id/group/shadow_only` | `ml_scorer_v1 alpha True` |
| class inherits BaseMultiplierAgent | CONFIRMED |
| `_setup_models`, `_compute`, `_select_model`, `_extract_features` methods | ALL PRESENT |
| `from src.intelligence.ml.feature_builder import SHADOW_FEATURE_KEYS` | PRESENT |
| `shap_importance.json` literal | PRESENT (8 occurrences) |
| `self._feature_cols` count | 14 occurrences |
| `_neutral(error="no_promoted_model"` | PRESENT |
| `_neutral(error="feature_extraction_failed"` | PRESENT |
| `clamp(ml_score * 2.0, 0.0, 2.0)` | PRESENT |
| `volume_z_score` (not bare `volume_z`) | CONFIRMED |
| No LLM imports | CONFIRMED |
| No `event=` kwargs | CONFIRMED |
| ruff check alpha_swarm_agent.py | PASS |
| `MLScorerMultiplierAgent` in swarm (import + construction) | CONFIRMED |
| `asyncio.get_running_loop()` used | CONFIRMED (line 191) |
| `add_signal_handler(_signal.SIGUSR1, self._on_sigusr1)` | CONFIRMED |
| `_on_sigusr1` + `_reload_ml_models` methods | PRESENT |
| `ml_scorer_v1` in _SWARM_AGENT_TO_TRANSFORM | CONFIRMED |
| `"indicagent-ml-training": 8` in _DAG_ORDER | CONFIRMED |
| No _LAG_THRESHOLDS / _AGENT_ID_TO_UNIT entries | CONFIRMED |
| `Type=oneshot` in .service | CONFIRMED |
| `OnCalendar=*-*-* 03:00:00 UTC` in .timer | CONFIRMED |
| `systemctl is-active indicagent-ml-training.timer` | active |
| Manual `systemctl start indicagent-ml-training.service` | status=0/SUCCESS, 4.2s wall time |
| Timer next fire | 2026-05-13 23:00 EDT (= 2026-05-14 03:00 UTC) |

## Auditor Cross-check Results

Command: `grep -nE "swarm_multiplier|adjusted_confidence" services/signal_auditor_agent.py services/parity_auditor_agent.py`

**Result: 0 matches in both files.**

Classification: Neither `signal_auditor_agent.py` nor `parity_auditor_agent.py` reference `swarm_multiplier` or `adjusted_confidence` — both auditors are unaffected by the AI-SEP-01 migration that moved these fields from `signal_ledger` to `signal_ai_enrichment`. No follow-up TODO required.

## Startup State

- **Models loaded at startup:** 0 (no promoted models yet — expected first-launch state at Phase 70 ship)
- **self._feature_cols length:** 0 (populated only when models are promoted and shap_importance.json artifact exists)
- **Swarm behavior:** MLScorerMultiplierAgent returns `_neutral(error="no_promoted_model")` on every signal; aggregate ignores zero-valid agents gracefully

## SIGUSR1 Smoke Test

Not run in worktree (alpha-swarm service not running in this environment). The handler is correctly wired via `asyncio.get_running_loop()` + `add_signal_handler`. When the service runs in production: `sudo systemctl kill -s SIGUSR1 indicagent-alpha-swarm` will emit `"alpha_swarm.sigusr1_received"` + `"alpha_swarm.ml_models_reloaded_sigusr1"` in `logs/alpha_swarm_compute_agent.log`.

## Task Commits

| Task | Commit | Description |
|------|--------|-------------|
| Task 1 | b2fbb7b4 | feat(070-04): add MLScorerMultiplierAgent + ModelRegistry.get_latest_run_id |
| Task 2 | bd455db8 | feat(070-04): integrate MLScorerMultiplierAgent into AlphaSwarm + SIGUSR1 hot-reload |
| Task 3 | 3ec61e01 | feat(070-04): register ml-training in DAG, add systemd unit + timer |

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Created .venv symlink in worktree for pre-commit hook compatibility**
- **Found during:** Pre-task setup
- **Issue:** Pre-commit hook uses `${REPO_ROOT}/.venv/bin/ruff` where REPO_ROOT = worktree path. No `.venv` in worktree.
- **Fix:** `ln -s /home/bg/dev/indicagent/.venv .venv` symlink created.
- **Committed in:** Resolved inline (not a tracked file)

**2. [Rule 2 - Missing critical functionality] Added `ModelRegistry.get_latest_run_id()` method**
- **Found during:** Task 1 — reading registry.py
- **Issue:** `ModelRegistry.load_latest()` returns only the pyfunc model object, not the `mlflow_run_id`. The plan requires loading `shap_importance.json` from `runs:/{run_id}/...` — impossible without the run_id.
- **Fix:** Added minimal `get_latest_run_id(segment)` method to `src/core/ml/registry.py` that queries `mlflow_run_id` from `ml_models` table for the latest production model of a segment. Zero impact on existing callers.
- **Files modified:** src/core/ml/registry.py
- **Committed in:** b2fbb7b4 (Task 1 commit)

**Total deviations:** 2 auto-fixed
