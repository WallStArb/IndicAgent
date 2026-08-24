---
phase: 173
slug: broadcast-feature-significance-correction-fix-pooled-cross-s
status: ready
nyquist_compliant: true
wave_0_complete: true
created: 2026-08-24
updated: 2026-08-24
---

# Phase 173 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest (project standard, `.venv/bin/pytest`) |
| **Config file** | `/home/bg/dev/indicagent/pytest.ini` — existing project pytest config applies |
| **Quick run command** | `.venv/bin/pytest tests/unit/test_ic_engine_compute_split.py tests/unit/test_ic_engine_fingerprint.py tests/unit/scripts/test_ops_broadcast_feature_audit.py -q` |
| **Full suite command** | `.venv/bin/pytest tests/unit/ -q` |
| **Estimated runtime** | ~5-15s quick, several minutes full suite |

Path note: the ic_engine test modules live at `tests/unit/test_ic_engine_*.py`, NOT under
`tests/unit/services/`. The detector's test module lives at
`tests/unit/scripts/test_ops_broadcast_feature_audit.py` (repo convention: `scripts/ops/*` tests go
under `tests/unit/scripts/`). An earlier draft of this file carried the wrong prefix; both are
corrected above and in every plan.

---

## Sampling Rate

- **After every task commit:** Run the quick command above
- **After every plan wave:** Run the full suite command
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 60 seconds for every automated verify EXCEPT the two long-running tasks
  listed in Manual-Only Verifications below (173-04 Task 3's live corpus smoke run, hours; 173-04
  Task 4's cross-AI review invocation, minutes). Both are terminal tasks in the final wave and both
  still carry an `<automated>` post-condition check that runs in under 60s.

---

## Per-Task Verification Map

Every task in this phase carries an `<automated>` verify. No task depends on an unwritten test
harness, so there is no Wave 0 scaffolding gap.

| Plan / Task | Automated verify | Decision covered |
|---|---|---|
| 173-01 T1 — register APR key | migration applied twice; `config_state` count == 1 | D-10 |
| 173-01 T2 — three-way verdict + `--persist` | `pytest tests/unit/scripts/test_ops_broadcast_feature_audit.py -q` + ruff | D-08, D-10 |
| 173-01 T3 — run detector, persist population | psql count of `metadata->>'broadcast'='true'` over the locked predicate >= 32 | D-02 |
| 173-02 T1 — gate, then delete CONTEXT_FEATURES path | psql `regime_label_source='context_features'` count == 0 **(pre-deletion gate, first clause)**, then `pytest -k ic_engine` + grep count == 0 | D-01 |
| 173-02 T2 — regression test + follow-up todos | `pytest tests/unit/test_ic_engine_compute_split.py -q` + both todo files exist | D-01 |
| 173-03 T1 — DB-sourced broadcast column split | `pytest tests/unit/test_ic_engine_compute_split.py -q` + `pytest -k ic_engine` | D-01, D-08 |
| 173-03 T2 — thread `bar_ts` through the fetch | `pytest tests/unit/test_ic_engine_compute_split.py -q` + `git diff --stat services/_batch_utils.py` empty | D-05 |
| 173-03 T3 — `broadcast_hash` watermark | `pytest tests/unit/test_ic_engine_fingerprint.py -q` + full suite | D-08 |
| 173-04 T1 — `_compute_one_broadcast_cell` | `pytest tests/unit/test_ic_engine_compute_split.py -q` + `pytest -k ic_engine` | D-03, D-04, D-06, D-09 |
| 173-04 T2 — wire into cross-sectional pass + BH-FDR | full suite + ruff | D-07 |
| 173-04 T3 — live smoke run | psql degenerate-CI count == 0 (post-condition, <60s; the run itself is the manual-only item below) | D-05, D-06 |
| 173-04 T4 — independent cross-AI review | full suite + SUMMARY contains the executed `codex exec` / `agy -p` command | Done-Coding SOP |

Sampling continuity: no three consecutive tasks lack an automated verify — all twelve have one.

---

## Wave 0 Requirements

All three Wave 0 blockers are resolved. None of them gates an unstarted decision any longer.

- [x] Live cross-check of the confirmed-broadcast feature population against `concept_registry`
      (research's Open Question 2 — D-02's "23" vs. the literal enumerated name-list count
      discrepancy). **Resolved:** the "23" is a counting-convention artifact (sin/cos pairs counted
      as one logical field), not a list error; all 32 enumerated names exist in `_FEATURE_NAMES`
      (173-01-PLAN.md planner_findings 1). No plan hardcodes the list — 173-01 Task 3 persists an
      empirically-measured population to `concept_registry.metadata` and 173-03 Task 1 reads it from
      the database.
- [x] Decide the `ic_cell_fingerprints` `pass_type` for the new broadcast cell (research's Open
      Question 1) before the cell's fingerprint-gated call site is wired into `main()`.
      **Resolved:** fold into the existing `pass_type='cross_sectional'` row; no new `pass_type`, no
      CHECK-constraint migration (173-03-PLAN.md planner_findings, with the three pieces of live
      evidence). Broadcast rows carry `regime_scope='cross_sectional'` so the existing
      archive/delete predicates sweep them unchanged.
- [x] Decide the BH-FDR `cluster_id` scheme for broadcast rows (research's Open Question 3,
      recommends reusing `_cluster_features`) before any row is written to `feature_ic_scores`.
      **Resolved:** `_cluster_features` on the broadcast matrix plus a mandatory
      `_BROADCAST_CLUSTER_ID_OFFSET = 10000` partition (173-03-PLAN.md planner_findings; implemented
      in 173-04 Task 1).

*Existing test infrastructure (`tests/unit/test_ic_engine_compute_split.py`,
`tests/unit/test_ic_engine_fingerprint.py`, `tests/unit/scripts/test_ops_broadcast_feature_audit.py`)
covers the surrounding machinery this phase touches — no new test framework and no new test module
needed. 173-01 Task 2 EXTENDS the pre-existing detector test module rather than adding a parallel
one, so the CI duplicate-test gate stays satisfied.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions | Discharged by |
|----------|-------------|------------|--------------------|---------------|
| No OOM regression on `_compute_cross_sectional_tf` under the new `bar_ts`-threading and boundary-scan grouping | D-05 | This function has a documented 2026-07-08 OOM incident (float32 conversion exists because of it); a unit test can't reproduce full-corpus memory pressure | Run the largest known cell (equity/5m, ~539K regime timestamps per this session's live observation) against the corpus and monitor RSS, not just correctness | 173-04 Task 3 |
| Broadcast cell rows produce real, non-degenerate CIs (not the todo-204 stale-vintage `[0,0]` signature) on a fresh corpus pass | — | Requires a live `ic_engine` run against real data, not mockable | Run `ops_canary_integrity_assert.py` (or equivalent) against a fresh `feature_ic_scores` vintage populated by the new broadcast cell | 173-04 Task 3 |
| Statistical-specification review (is one draw per `bar_ts` against an equal-weighted peer aggregate the right test?) | Done-Coding SOP | No test can validate a specification choice; needs an independent reviewer | `codex exec --model "$MODEL" --skip-git-repo-check -` on the phase diff, and/or `agy -p "<literal prompt>" --dangerously-skip-permissions` | 173-04 Task 4 |

The partial static allocation-safety property IS automatable and is not on this list:
`test_broadcast_cell_grouping_uses_no_sort_or_unique` (173-04 Task 1) enforces the sort-free grouping
contract in CI, so only the live RSS number remains manual.

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies — all twelve tasks carry one
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references — all three Wave 0 items resolved, none deferred into execution
- [x] No watch-mode flags — every verify command is a single-shot `pytest -q` / `psql -tAc` / `ruff`
- [x] Feedback latency < 60s — for every automated verify; the two long-running tasks are declared under Sampling Rate and Manual-Only Verifications rather than hidden
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** ready — validation contract complete against the final four-plan set (2026-08-24).
