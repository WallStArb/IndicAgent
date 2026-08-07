---
phase: 171
slug: hmm-walk-forward-regime-labeling-parameter-lookahead-fix
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-08-07
---

# Phase 171 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest (`.venv/bin/pytest`) |
| **Config file** | project-root `pytest.ini` / conftest (standard, unchanged by this phase) |
| **Quick run command** | `.venv/bin/pytest tests/unit/services/test_regime_writer.py -q` |
| **Full suite command** | `.venv/bin/pytest tests/unit/ -q` |
| **Estimated runtime** | ~10s quick / full-suite duration varies (avoid the ~10min hang class fixed in `1cd59327`) |

---

## Sampling Rate

- **After every task commit:** `.venv/bin/pytest tests/unit/services/test_regime_writer.py -q`
- **After every plan wave:** `.venv/bin/pytest tests/unit/ -q`
- **Before `/gsd:verify-work`:** Full suite must be green, AND the REQ-3 data-integrity spot-check
  query (below) must have been run against the actually-relabeled corpus and its result recorded
  in phase completion evidence — it cannot be expressed as a pytest assertion against production
  data.
- **Max feedback latency:** ~10s (unit suite); the full-corpus refit itself is a separate,
  multi-hour operational step gated on live background-job state, not part of the fast feedback
  loop.

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 171-01-01 | 01 | 0 | REQ-5 | — | New pilot script exercises `_hmm_seed_stability_check` against real fetched OHLCV, not just synthetic unit-test data | script run | `.venv/bin/python scripts/analysis/hmm_walk_forward_seed_stability_pilot.py` | ❌ W0 | ⬜ pending |
| 171-01-02 | 01 | 0 | REQ-3 | — | Reusable, checked-in data-integrity verification query/script for the NULL-out + relabel pass (no silent method-blending in `feature_vectors.regime`) | script run | `.venv/bin/python scripts/analysis/regime_writer_relabel_provenance_check.py` (or equivalent) | ❌ W0 | ⬜ pending |
| 171-02-01 | 02 | 1 | REQ-1 | — | tf-calibrated `refit_every_bars`/`initial_warmup_bars` APR keys present for all 4 tfs (1h/15m/5m/1d) with correct provenance tags | manual config assertion | `PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "SELECT config_key, config_value, description FROM config_state WHERE config_key LIKE 'alpha.hmm.walk_forward%'"` | N/A (config-state, not unit test) | ⬜ pending |
| 171-02-02 | 02 | 1 | REQ-2 | — | `_run_symbol_worker` dispatches to walk-forward path when `alpha.hmm.walk_forward.enabled` is true, full-history path when false | unit | `.venv/bin/pytest tests/unit/services/test_regime_writer.py -k walk_forward -x` | ✅ (function-level exists) / ❌ W0 (dispatch-level gap) | ⬜ pending |
| 171-03-01 | 03 | 2 | REQ-3 | — | Pre-relabel NULL-out executed per (symbol, tf) chunk before walk-forward relabel; no row carries mixed-method provenance post-refit | script run + spot-check | REQ-3 script above, run against pilot symbols first | ❌ W0 | ⬜ pending |
| 171-04-01 | 04 | 3 | REQ-4 | — | `ic_engine`/`feature_ic_scores` reflects post-relabel regime stratification | regression | `.venv/bin/pytest tests/unit/services/test_ic_engine*.py -q` (mechanism regression only — `--refresh` bypasses fingerprint, so freshness itself is operational, not unit-testable) | ✅ mechanism / ❌ no freshness-specific assertion (acceptable per RESEARCH.md) | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

*The planner should treat the above as a starting skeleton, not a fixed task list — expand/renumber
task IDs to match the actual PLAN.md wave structure once written.*

---

## Wave 0 Requirements

- [ ] `scripts/analysis/hmm_walk_forward_seed_stability_pilot.py` (or similar name) — new pilot
      script exercising `_hmm_seed_stability_check` against real fetched OHLCV (Requirement 5)
- [ ] Data-integrity verification query/script for the NULL-out + relabel pass (Requirement 3) —
      checked in, reusable, not an ad hoc psql command lost to shell history
- [ ] `_walk_forward_hmm_full` per-segment `iters_used`/`n_iter_cap` logging (D-04's data
      collection gap on the path that will actually run at full scale)
- [ ] `_run_symbol_worker`-level dispatch test (REQ-2 gap: existing tests exercise
      `_compute_symbol_tf_walk_forward` directly but not the flag-branch dispatch itself)
- [ ] If D-03's pilot parallel-arm comparison favors `n_restarts>1`: `n_restarts` parameter
      threading through `_walk_forward_hmm_full`/`_compute_symbol_tf_walk_forward`, with unit test
      coverage mirroring `_compute_symbol_tf`'s existing multi-restart tests (this task is
      conditional on the pilot's own verdict — do not build it unconditionally)

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|--------------------|
| Full-corpus regime recompute produces clean, single-method-provenance data | REQ-3 | Data-integrity property over live production rows, not a unit-testable code path | `SELECT count(*) FROM feature_vectors WHERE symbol=%s AND tf=%s AND bar_ts < <warmup boundary> AND regime IS NOT NULL` must return 0 post-NULL-out-and-relabel for warmup-prefix bars, per symbol/tf |
| Full 231-symbol x 4-tf rollout execution timing | REQ-3/REQ-4 | Gated on live background-job state (todo 259 client-43 backfill, todo 256 `ic_engine --refresh`, Phase 151 waves 6-7 bundling), not deterministic at plan time | Re-check `ps aux \| grep -E "ic_engine\|backfill\|regime_writer"` immediately before launching the full-corpus refit task; do not launch a redundant concurrent `ic_engine --refresh` pass |
| Seed-stability check pass/fail on real corpus data | REQ-5 | Statistical threshold judgment on live pilot output, not a fixed unit-test assertion | Run `_hmm_seed_stability_check` via the new pilot script against the D-01 staged pilot symbols; record pass/fail per symbol/tf in phase completion notes |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 10s (unit suite)
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
