---
phase: 82-ml-intelligence-quality-qualitative-foundation
plan: "03"
subsystem: hmm-training
tags: [hmm, training, baum-welch, hmmlearn, GaussianHMM, systemd-oneshot, timer, sigusr1, hot-reload]
dependency_graph:
  requires:
    - phase: 82-02
      provides: HMM multi-TF instances with reload_parameters() public method
  provides:
    - HMMTrainingComputeAgent (offline Baum-Welch training, per-TF pooled models)
    - config/hmm_parameters_{1m,5m,15m,1h}.json (atomic parameter file output)
    - indicagent-hmm-training systemd oneshot service + monthly timer
    - SIGUSR1 emit to indicagent-intelligence-pipeline.service on training completion
  affects: [hmm-regime-inference, intelligence-pipeline-agent, regime-soft-gate-plan04]
tech_stack:
  added: [hmmlearn>=0.3.0]
  patterns:
    - oneshot-timer pattern (mirrors ml_training_agent.py)
    - write-tmp-then-rename atomic file update
    - per-TF observation matrix construction replicating _build_observation()
    - 5D/2D fallback based on indicator data availability (>= 50% rows threshold)
key_files:
  created:
    - src/intelligence/services/hmm_training_compute_agent.py
    - services/hmm_training_agent.py
    - production/systemd/indicagent-hmm-training.service
    - production/systemd/indicagent-hmm-training.timer
    - tests/unit/test_hmm_training_compute_agent.py
  modified:
    - requirements.txt
key_decisions:
  - "Per-TF pooled models (4 files not per-symbol) — Phase 82 scope; per-(symbol,tf) deferred to Phase 83+ when 90+ days data available"
  - "5D/2D observation dimension decided at runtime based on indicator availability (>= 50% rows with all 4 indicators = 5D, else 2D)"
  - "Minimum 500 rows threshold per TF before training; TFs below threshold logged and skipped without crashing the run"
  - "Lookback days: 1m=30d, 5m=60d, 15m=90d, 1h=180d — balances recency vs sample size"
  - "SIGUSR1 emitted only if at least one TF file was written; skipped entirely if all TFs fail/skip"
  - "DatabaseManager passed via dependency injection — entrypoint creates pool, agent receives it"
requirements-completed:
  - P82-HMM-TRAINING
duration: 5min
completed: "2026-05-13"
---

# Phase 82 Plan 03: HMM Training Pipeline Summary

**Offline Baum-Welch training agent using hmmlearn.GaussianHMM writes four atomic per-TF parameter files (config/hmm_parameters_{tf}.json) and emits SIGUSR1 to intelligence-pipeline for live hot-reload, with monthly systemd timer and full unit test coverage.**

---

## Performance

- **Duration:** 5 min
- **Started:** 2026-05-13T19:47:26Z
- **Completed:** 2026-05-13T19:52:00Z
- **Tasks:** 3
- **Files modified:** 6 (1 modified requirements.txt + 5 created)

---

## Accomplishments

- `HMMTrainingComputeAgent` trains per-TF GaussianHMM (n_components=3, diag covariance, n_iter=50) from `intelligence_features`, excluding backfill rows via `is_backfill IS NOT TRUE` filter
- Atomic parameter writes via `.tmp` + `os.rename`; JSON keys (`transition_matrix`, `emission_means`, `emission_variances`) match `HMMRegimePlugin._load_parameters()` contract exactly
- SIGUSR1 emitted to `indicagent-intelligence-pipeline.service` after successful writes; live HMMRegimePlugin instances call `reload_parameters()` without restart
- Systemd `Type=oneshot` service + `OnCalendar=monthly` timer reference files created (installation is an ops step)
- 6 unit tests cover: backfill filter (source-inspection + runtime capture), per-TF file writes, JSON schema, SIGUSR1 invocation, and skip-on-insufficient-rows behavior

---

## Task Commits

1. **Task 1: Add hmmlearn dependency and implement HMMTrainingComputeAgent** - `6bf582cf` (feat)
2. **Task 2: Add oneshot entrypoint and systemd unit+timer** - `9f2e330b` (feat)
3. **Task 3: Unit tests for training data query and parameter file write** - `3defad61` (test)

---

## Files Created/Modified

- `requirements.txt` — Added `hmmlearn>=0.3.0` (hmmlearn 0.3.3 installed)
- `src/intelligence/services/hmm_training_compute_agent.py` — HMMTrainingComputeAgent: `run()`, `_query_features()`, `_build_obs_matrix()`, `_fit_hmm()`, `_write_params()`, `emit_sigusr1()`, `start()`
- `services/hmm_training_agent.py` — Oneshot entrypoint mirroring ml_training_agent.py: DatabaseManager pool creation, asyncio.run(agent.start())
- `production/systemd/indicagent-hmm-training.service` — Type=oneshot, Restart=no, matches ml-training.service pattern
- `production/systemd/indicagent-hmm-training.timer` — OnCalendar=monthly, Persistent=true
- `tests/unit/test_hmm_training_compute_agent.py` — 6 tests, all passing, no live DB required

---

## Decisions Made

- **Per-TF row threshold 500:** Prevents training on sparse data that would produce unstable/degenerate HMM parameters. Monthly timer means data accumulates between runs.
- **5D vs 2D observation dimension decided at runtime:** If >= 50% of rows have all four indicator columns (rsi_14, adx_14, atr_14, macd_histogram_12_26_9), use 5D observation matching `HMMRegimePlugin._build_observation()` 5D path. Otherwise fall back to 2D (log_return, realized_vol). This handles the case where early data lacks computed indicators.
- **Lookback windows:** 1m=30d, 5m=60d, 15m=90d, 1h=180d — higher TFs need more calendar time to accumulate enough bars.
- **DatabaseManager dependency injection:** Entrypoint creates pool; agent receives `db_manager`. Same as `MLTrainingComputeAgent` pattern.
- **SIGUSR1 only on success:** If all TFs are skipped/errored, SIGUSR1 is not sent (no valid params to reload). Prevents live instances from loading stale/deleted files.

---

## Installation Instructions (Ops Step)

After merging this PR, install the systemd units on the server:

```bash
sudo cp production/systemd/indicagent-hmm-training.service /etc/systemd/system/
sudo cp production/systemd/indicagent-hmm-training.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable indicagent-hmm-training.timer
sudo systemctl start indicagent-hmm-training.timer

# To run training immediately (one-shot):
sudo systemctl start indicagent-hmm-training.service

# Verify timer is active:
systemctl status indicagent-hmm-training.timer
```

---

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Cherry-picked 82-02 commits into worktree**

- **Found during:** Pre-execution setup
- **Issue:** Worktree branch was created before 82-02 commits landed on feat/phase80-swarm-observability-ux. HMMRegimePlugin.reload_parameters() (required for SIGUSR1 contract verification) was not present.
- **Fix:** Cherry-picked da932c97, 5eed8813, 1017b2c3, e89ef0a4, c93254a7, dafbf2e6 from the parent branch — all source-only commits (no STATE.md/ROADMAP.md).
- **Files modified:** Multiple 82-02 source files now present in worktree
- **Verification:** `HMMRegimePlugin.reload_parameters()` present; TIER_SMC has 4 HMM instances; test_hmm_regime_multitf.py present
- **Committed in:** Separate cherry-pick commits (pre-execution prep)

---

**Total deviations:** 1 auto-fixed (blocking — missing base from prior wave)
**Impact on plan:** Required to have the correct foundation. No scope creep.

---

## Issues Encountered

- `hmmlearn` was not installed in the venv. Installed via `uv pip install "hmmlearn>=0.3.0"` (version 0.3.3 installed). The `pytest.importorskip("hmmlearn")` gate in tests correctly skips the module when library is absent.

---

## Next Phase Readiness

- HMM training pipeline complete. Four per-TF parameter files can now be generated monthly.
- Live HMMRegimePlugin instances will reload on SIGUSR1 after training completes.
- Plan 04 (regime soft gate + entropy/velocity soft multiplier) can proceed — it consumes `hmm_regime_entropy` and `hmm_regime_velocity` from the HMM plugins already wired in Plan 02.
- Parameter files start as default values until first training run completes with sufficient data.

---

## Self-Check

Verifying claims before finalizing:

- `src/intelligence/services/hmm_training_compute_agent.py` exists: YES
- `services/hmm_training_agent.py` exists: YES
- `production/systemd/indicagent-hmm-training.service` contains `Type=oneshot`: YES
- `production/systemd/indicagent-hmm-training.timer` contains `OnCalendar=monthly`: YES
- `tests/unit/test_hmm_training_compute_agent.py` exists with 6 tests: YES
- All 6 tests pass: YES
- `requirements.txt` contains `hmmlearn>=0.3.0`: YES
- `is_backfill IS NOT TRUE` in query source: YES
- Atomic write via `.tmp` + `os.rename`: YES
- SIGUSR1 targets `indicagent-intelligence-pipeline.service`: YES
- JSON keys `transition_matrix`, `emission_means`, `emission_variances`: YES
- Task commits: 6bf582cf, 9f2e330b, 3defad61

## Self-Check: PASSED

---

*Phase: 82-ml-intelligence-quality-qualitative-foundation*
*Completed: 2026-05-13*
