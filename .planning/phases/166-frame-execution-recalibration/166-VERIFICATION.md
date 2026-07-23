---
phase: 166-frame-execution-recalibration
verified: 2026-07-23T15:30:00Z
status: passed
score: 27/27 must-haves verified
overrides_applied: 0
---

# Phase 166: Frame/Execution Recalibration Verification Report

**Phase Goal:** Diagnose why Phase 148's Gate 2 (execution proof) failed and determine whether
stop/target/hold recalibration against the IC decay curve can turn the OOS-proven signal (Gate 1
PASS) into profitable OOS P&L — the pre-registered "frame problem" playbook.

**Verified:** 2026-07-23T15:30:00Z
**Status:** passed
**Re-verification:** No — initial verification

**Verifier's note on the empirical outcome:** the phase's own conclusion is that neither the
baseline nor the scalar candidate clears the frozen five criteria, and the structural candidate
correctly halted because Phase 163 has not executed. This is NOT treated as a phase failure —
the goal was to *determine* whether recalibration could help, and the phase produced a rigorous,
reproducible, live-DB-verified answer (no, for the two testable candidates; not yet evaluable for
the third). Verification below checks that this diagnostic work was done rigorously, not that a
specific P&L outcome was achieved.

## Goal Achievement

### Observable Truths (merged from all 6 plans' `must_haves.truths` + CONTEXT.md D-01–D-06)

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Phase 163 VP/SR liveness verified before structural runtime attempted (166-01 Task 0) | VERIFIED | `SELECT count(*) FROM feature_vectors WHERE sr_support_dist IS NOT NULL` re-run live during this verification returns `0`; 166-01-SUMMARY.md records the same `NULL_PENDING_163` result from Task 0 |
| 2 | A Phase-163-not-live status is a valid, non-failing phase outcome gating only the structural arm | VERIFIED | 166-06 Task 2 halted the structural arm exactly as designed; baseline + scalar arms scored regardless; verdict doc frames this explicitly as a "2-of-3-arm valid complete outcome" |
| 3 | Diagnosis empirically confirms D-02: hold_max_bars calibrated, stop_atr_mult/target_r_multiple are not | VERIFIED | `diagnose166_frame_calibration.py` read-only, live-run output cited in 166-01-SUMMARY.md; independently confirmed the script contains zero write statements (`grep` for INSERT/UPDATE/DELETE/config_service.set returns nothing) |
| 4 | Read-only diagnosis compares current global scalars vs. empirical uncensored MAE/MFE percentiles per (regime,tf) | VERIFIED | `_summarize_excursions`/`_compare_to_current` present in `scripts/analysis/diagnose166_frame_calibration.py`; `tests/unit/test_diagnose166_frame_calibration.py` passes |
| 5 | Diagnosis discloses folded caveats 088/096/172/173 | VERIFIED | All four todo numbers present in the module docstring/comments (`grep -n "088\|096\|172\|173"` confirms) |
| 6 | Migration 253 seeds fresh alpha.frame.* keys without reusing archived feature.trade_framer.*/feature.zone_engine.* | VERIFIED | `grep -E "feature\.trade_framer|feature\.zone_engine"` on migration 253 returns nothing; live `config_schema` has 36 `stop_atr_mult.*` + 36 `target_r_multiple.*` keys |
| 7 | `_calibrate_stop_target()` writes per-(regime,tf) median across qualifying symbols | VERIFIED | Function present in `services/ensemble_ic_engine.py`; live `config_state`/`config_history` show 7 cells written by `ensemble-ic-engine`, values matching the verdict doc exactly (e.g. `low_bull.5m` = 0.4954464219337281 ≈ verdict's 0.495) |
| 8 | Calibration fires only for champion weight_version (CR-02) | VERIFIED | Dispatch wired inside the same `if weight_version == champion_weight_version:` block as `_calibrate_hold_max_bars` (read directly, lines ~1207) |
| 9 | Zero-qualifying cells are skipped, no fallback write | VERIFIED | Unit-tested (`test_ensemble_ic_stop_target_calibration.py`); confirmed live only 7 of 36 cells were ever written, rest remain at seed default `1.5`/`2.0` |
| 10 | Stop uses closed_target MAE, target uses closed_max_hold MFE (censoring-safe) | VERIFIED | `_select_stop_target_from_excursions` implements exactly this; unit tests assert `closed_stop`-only cells return `None` for stop |
| 11 | Structural module ports zone_engine's 3-tier resolution generically over ZoneCandidate | VERIFIED | `src/intelligence/trading/structural_confluence.py` (402 lines) contains `ZoneCandidate`, `_find_clusters`, `_score_cluster`, `_pick_single_best`, `_resolve_zone`; 11 unit tests pass |
| 12 | Candidate spec table populated ONLY with Phase-163-live field names, zero archived-tier imports | VERIFIED | `grep -E "from src\.intelligence\.(archive\|features)"` and `grep -E "feature\.zone_engine\|feature\.trade_framer\|weights\.zone_engine"` both return nothing against the module |
| 13 | Module reads thresholds from fresh alpha.frame.* keys only | VERIFIED | `set_config_service`/`_read_config` reference only the 6-7 migration-253-seeded keys (cross-checked against `alpha_frame_writer.py`'s `_build_structural_config_service`) |
| 14 | Extension-point comment marks Part 2 (SMC/swing/fib/anchored-VWAP) deferral | VERIFIED | `grep -n "EXTENSION POINT"` returns line 234, citing todo 175 (the actual filed number) |
| 15 | New gate script scores OOS population, writes one row per candidate under a NEW gate_id (never gate2_execution) | VERIFIED | Live `gate_evaluations` query returns exactly `gate166_baseline` (fail) and `gate166_scalar` (fail); `_GATE_IDS` dict + structural `ValueError` guard confirmed in script; `gate2_execution` appears only in comments, never as a write target |
| 16 | Gate reuses frame_gate_passes/evaluate_frame_gate + SHADOW-REVIEW's frozen five, no new thresholds | VERIFIED | Script imports these from `counterfactual_tracker`; live evidence JSON for `gate166_baseline` shows the same c1-c5 shape and near-identical c4 value to Phase 148's `gate2_execution` (9.596266492204737 vs. 9.596266492204732 — float-noise-level match), confirming genuine reuse not re-derivation |
| 17 | Every evaluation includes regime-stratified companion + discloses mid_bull-only/5m-15m-only coverage | VERIFIED | Live evidence JSON for both scored gate_ids contains `disclosure.tf_5m_15m_only: true` and a `regime_companion` structure; verdict doc reproduces these numbers |
| 18 | Evidence reports population footprint (frame_count, eligible-cell count, per-cell counts) | VERIFIED | Live evidence JSON contains `population.frame_count`/`population.cell_frame_counts`, matching verdict doc's 33,892 (baseline) / 28,100 (scalar) |
| 19 | Same-bar_ts frames aggregated before cumulative stats (172 guard) | VERIFIED | `_aggregate_pnl_by_bar_ts` ported and unit-tested with a 20+-tied-bar_ts fixture |
| 20 | Dry-run computes+prints with zero writes; real run atomically re-checks no prior row | VERIFIED | Unit-tested (`test_dry_run_performs_zero_writes`, rewritten post-review to invoke real `main()`); live sentinel file (`.gate166_dryrun_sentinel.json`) records exactly one dry-run timestamp per scored gate_id, matching the one-shot discipline |
| 21 | Per-gate_id dry-run sentinel refuses a second dry-run without --force | VERIFIED | `_check_and_record_dryrun` present and unit-tested; live sentinel shows exactly 2 entries (baseline, scalar), each once |
| 22 | AlphaFrameWriter dispatches geometry_source: global/per_cell_scalar/structural | VERIFIED | `FrameConfig.geometry_source` field + `_resolve_row_geometry` dispatch present in `services/alpha_frame_writer.py`; live `config_state.alpha.frame.geometry_source = 'global'` (correctly reverted post-run) |
| 23 | per_cell_scalar falls back to global scalar when per-cell key absent (backward-compatible) | VERIFIED | `_resolve_scalar_geometry` mirrors the existing `hold_key` pattern; unit-tested (Test 2/3 in `test_alpha_frame_writer_candidate_geometry.py`) |
| 24 | structural mode calls resolve_structural_zone, falls back to ATR geometry on tier="atr" | VERIFIED | `_resolve_structural_geometry` present; unit-tested; live-confirmed in 166-06 that with Phase 163 still NULL, every row degrades to scalar-seed fallback (documented, not hidden) |
| 25 | Selected stop/target snapshotted onto alpha_frames row at scan time (no live join) | VERIFIED | `_process_partition` resolves geometry per row and inserts the resolved values into the same `_INSERT_SQL` used before; no second write path (grep confirms single batch-flush write) |
| 26 | Missing per-cell keys logged once per partition, never per row | VERIFIED | `missing_stop_keys`/`missing_target_keys` accumulator sets, warned once after the per-row loop (mirrors pre-existing `missing_hold_keys` pattern) |
| 27 | Verdict doc + consolidated Part 2 todo + extension-point citation + closed superseded todo 163 | VERIFIED | `docs/plans/2026-07-23-phase166-frame-recalibration-verdict.md` exists (all 3 arms, population deltas, explicit Part 2 deferral sentence, clear recommendation); `todos/pending/175-*.md` exists; `todos/completed/163-*.md` exists (moved from `deferred/`, which no longer contains it) |

**Score:** 27/27 truths verified

### D-01 through D-06 (CONTEXT.md decisions) — explicit cross-check

| Decision | Status | Evidence |
|---|---|---|
| D-01(a-d): diagnose + implement + re-validate, new gate_id | VERIFIED | 166-01 (diagnose), 166-02/03 (implement both candidates), 166-04/06 (fresh gate, run once) |
| D-02: baseline facts (hold_max_bars calibrated, stop/target not) | VERIFIED | Diagnosis output + migration 253/205 cross-check |
| D-03: empirical comparison, not a priori choice; keep neither is valid | VERIFIED | Both candidates built, scored, and both correctly rejected (FAIL) — no candidate adopted by inspection |
| D-04: Gate 2 not re-run; new gate_id; run-once discipline | VERIFIED | `gate166_baseline`/`gate166_scalar` are new gate_ids in `gate_evaluations`; dry-run sentinel enforces one-shot |
| D-05: regime-window coverage disclosed, not gated | VERIFIED | `disclosure`/`regime_companion` blocks present in evidence JSON and verdict doc; mid_bull-only limitation stated, not used to block or inflate the verdict |
| D-06: structural candidate two-part split, Phase 163 as runtime-checked prerequisite, Part 2 deferred | VERIFIED | Part 1 (`structural_confluence.py`) built against Phase-163-only fields; Phase 163 checked live at Task 0 and Task 2 (both correctly found not-live); Part 2 deferred via todo 175 with extension-point citation |

### Required Artifacts

| Artifact | Expected | Status | Details |
|---|---|---|---|
| `production/migrations/253_alpha_frame_stop_target_calibration.sql` | APR keys for both candidates | VERIFIED | Applied live; 72 per-cell + 10 other keys confirmed in `config_schema` |
| `production/migrations/254_frame_structure_snap_key_correction.sql` | Code-review WR-01 fix | VERIFIED | Applied live; `config_schema.description` for `structure_snap_proximity_atr` shows the corrected `[reserved, unused]` text |
| `scripts/analysis/diagnose166_frame_calibration.py` | Read-only diagnosis | VERIFIED | 341 lines, zero writes, 4/4 caveats disclosed, unit-tested |
| `services/ensemble_ic_engine.py` (`_calibrate_stop_target`) | Scalar candidate calibration | VERIFIED | Present, champion-gated, live-run confirmed (7 cells written) |
| `src/intelligence/trading/structural_confluence.py` | Structural candidate Part 1 | VERIFIED | 402 lines, 11 unit tests, zero archived imports |
| `scripts/analysis/gate166_frame_recalibration_eval.py` | Fresh validation gate | VERIFIED | 646 lines, 13 unit tests, live-run confirmed (2 real gate_evaluations rows) |
| `services/alpha_frame_writer.py` (geometry_source dispatch) | Wiring for both candidates | VERIFIED | Dispatch present, 22 new unit tests, live-run confirmed |
| `docs/plans/2026-07-23-phase166-frame-recalibration-verdict.md` | Empirical verdict | VERIFIED | Exists, matches live DB evidence exactly (cross-checked numerically) |
| `.planning/todos/pending/175-*.md` | Part 2 deferral | VERIFIED | Exists, names all 3 dependencies (Phase 164, 165, anchored-VWAP) |

### Key Link Verification

| From | To | Via | Status | Details |
|---|---|---|---|---|
| `diagnose166_frame_calibration.py` | `alpha_frames.counterfactual_mfe/mae` | in-sample SELECT | WIRED | Read-only; confirmed no writes |
| `ensemble_ic_engine.py::_calibrate_stop_target` | `config_state` | `ConfigService.set` under champion gate | WIRED | Live `config_history` shows 7 real writes attributed to `ensemble-ic-engine` |
| `structural_confluence.py::resolve_structural_zone` | Phase-163 `feature_vectors` columns | spec table + price reconstruction | WIRED (data-starved) | Code path correct; currently degrades to `tier="atr"` for 100% of rows because Phase 163 has not executed — disclosed, not hidden |
| `gate166_frame_recalibration_eval.py` | `gate_evaluations` (new gate_id) | atomic re-check-then-insert | WIRED | Live: 2 rows present, each gate_id written exactly once |
| `alpha_frame_writer.py::_process_partition` | `alpha.frame.stop_atr_mult.<regime>.<tf>` / `structural_confluence` | `geometry_source` dispatch | WIRED | Live-run produced 33,898-row `per_cell_scalar` population with 7 distinct calibrated `(stop_atr_mult, target_r_multiple)` pairs matching the calibration exactly |

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|---|---|---|---|---|
| `gate166_baseline`/`gate166_scalar` evidence | `pooled.c2_ci_lower`/`c3_sharpe`/`c4_max_dd` | live `alpha_frames` OOS population, bootstrap-resampled | Yes — independently queried and matches verdict doc to the digit | FLOWING |
| `config_state.alpha.frame.stop_atr_mult.*` | 7 calibrated cells | `EnsembleICEngine._calibrate_stop_target` live run against 20.79M-row corpus | Yes | FLOWING |
| structural candidate frames | `stop_atr_mult` effective ratio | `structural_confluence.resolve_structural_zone` | No (100% ATR fallback, Phase 163 data-starved) | STATIC (disclosed as such, not a hidden defect) |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|---|---|---|---|
| `gate166_frame_recalibration_eval.py --help` exits 0 | `python scripts/analysis/gate166_frame_recalibration_eval.py --help` | Prints usage with `--candidate {baseline,scalar,structural}`, `--dry-run`, `--force` | PASS |
| Full phase-166 unit test set green | `pytest tests/unit/test_diagnose166_frame_calibration.py tests/unit/test_ensemble_ic_stop_target_calibration.py tests/unit/test_structural_confluence.py tests/unit/test_gate166_frame_recalibration_eval.py tests/unit/test_alpha_frame_writer_candidate_geometry.py tests/unit/test_alpha_frame_writer.py -q` | All pass | PASS |
| Full repo unit suite green | `pytest tests/unit/ -q` | All pass (3 pre-existing unrelated skips) | PASS |
| `gate_evaluations` contains exactly the claimed rows | `SELECT gate_id, result FROM gate_evaluations WHERE gate_id LIKE 'gate166%'` | `gate166_baseline: fail`, `gate166_scalar: fail` | PASS |
| Calibrated APR values match verdict doc digit-for-digit | `SELECT config_key, config_value FROM config_state WHERE config_key LIKE 'alpha.frame.stop_atr_mult.%' AND config_value != '1.5'` | 7 rows, values match verdict doc's table exactly | PASS |
| `geometry_source` correctly reverted to safe default post-run | `SELECT config_value FROM config_state WHERE config_key='alpha.frame.geometry_source'` | `global` | PASS |
| Phase 163 still correctly not-live (structural halt justified) | `SELECT count(*) FROM feature_vectors WHERE sr_support_dist IS NOT NULL` | `0` | PASS |

### Code Review Fix Verification (166-REVIEW.md's 4 findings)

| Finding | Fix Claimed | Independently Verified |
|---|---|---|
| WR-01 (dead APR key, misleading description) | Migration 254 corrects description | VERIFIED — migration 254 exists, applied live, description now reads `[reserved, unused] ... Reserved for todo 175` |
| WR-02 (coarser eligibility scoping than claimed) | `_calibrate_stop_target` narrowed to exact (symbol,tf) pairs | VERIFIED — `frame_rows = [r for r in frame_rows if (r["symbol"], r["tf"]) in eligible_symbol_tf_pairs]` present; comment corrected |
| WR-03 (counter over-counting) | Move `missing_cost_hurdle_count` increment after geometry skip-continue | VERIFIED — `continue` for `degenerate_geometry_skip_count` occurs before the `cost_hurdle` null-check in `_process_partition` |
| IN-01 (test doesn't exercise real code path) | Rewrite to invoke real `main()` | VERIFIED — `test_dry_run_performs_zero_writes` now patches `sys.argv`/`asyncpg.create_pool` and calls `await main()` |

### Requirements Coverage

No formal REQ-IDs / REQUIREMENTS.md for this project. Phase requirement IDs are CONTEXT.md
decisions D-01(a-d) through D-06 — see the D-01–D-06 cross-check table above. All satisfied.

### Anti-Patterns Found

None. Grep across all phase-166-modified files for `TBD|FIXME|XXX|HACK|PLACEHOLDER` and
"not yet implemented"-style phrases returns zero hits within phase-166 code (one pre-existing,
unrelated "not yet implemented" string in `ensemble_ic_engine.py` predates this phase, from Phase
142A — confirmed via `git log -S`).

### Human Verification Required

None. This phase's deliverables are fully machine-verifiable: DB queries, unit tests, and a
one-shot gate script with auditable evidence JSON. No UI, visual, or subjective-judgment
component. The phase's own "keep neither candidate" recommendation is an empirical, disclosed
conclusion already reached autonomously per this project's no-human-checkpoints convention, not
an open question needing human sign-off.

### Gaps Summary

No blocking gaps. One informational note, not a phase-goal gap:

- **STATE.md is stale relative to Phase 166's actual execution** — as of this verification,
  `.planning/STATE.md` still describes Phase 166 as "PLANNED... Next action: execute Phase 163,
  then `/gsd-execute-phase 166`," even though Phase 166 has fully executed (6/6 plans, verdict
  doc written, gate rows live) and Phase 163 was correctly *not* forced (per the phase's own
  design). This is a documentation-sync task for the orchestrator/next session, not a gap in any
  of Phase 166's own must-haves (STATE.md updates were never one of CONTEXT.md's D-01–D-06
  decisions or any plan's must_haves). Flagged here for completeness; does not affect phase
  status.

All 27 must-haves across the 6 plans, and all 6 CONTEXT.md decisions (D-01 through D-06), were
independently verified against live code, live DB state, and a green unit-test suite — not
inferred from SUMMARY.md prose. The 4 code-review findings (166-REVIEW.md) were independently
re-verified as fixed. The phase's empirical conclusion (both baseline and scalar candidates FAIL
gate166; structural candidate correctly not evaluable pending Phase 163) is a real, reproducible,
disclosed result, not a claimed one.

---

_Verified: 2026-07-23T15:30:00Z_
_Verifier: Claude (gsd-verifier)_
