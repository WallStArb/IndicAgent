---
phase: 186-old-ensemble-chain-retirement-and-ic-engine-re-scope
plan: 18
subsystem: features
tags: [hmm, regime, coverage-auditor, market-regimes, apr, golden-parity]
requires:
  - phase: 186-13
    provides: walk-forward HMM regime kernels, training-slice gate, regime golden and capture script
provides:
  - trend obs builder that starts after the nested vol_of_vol warmup (todo 286), golden regenerated in its own commit
  - kernel-level pin of the WR-01 duration and churn reset for both families (todo 292)
  - read-only kernel coverage sweep script and its evidence (todos 289, 341)
  - exception-aware regime coverage auditor with APR exceptions that expire (todo 341)
  - atomic per-(regime_group, tf) market_regimes replace with a shrink guard and a dry-run diff (todo 420)
  - migrations 419 and 420
affects: [186-20, 186-24, 186-25, 186-26]
tech-stack:
  added: []
  patterns:
    - "decision rule written into the todo and committed before the measurement run"
    - "diagnose a coverage gap on the kernel from stored bars, register an expiring exception, let the rebuild clear it"
key-files:
  created:
    - scripts/infrastructure/features_regime_kernel_coverage_sweep.py
    - tests/unit/scripts/test_features_regime_kernel_coverage_sweep.py
    - production/migrations/419_market_regimes_replace_guard_apr.sql
    - production/migrations/420_regime_coverage_auditor_exceptions_apr.sql
    - .planning/phases/186-old-ensemble-chain-retirement-and-ic-engine-re-scope/evidence/186-18-regime-coverage.json
    - .planning/phases/186-old-ensemble-chain-retirement-and-ic-engine-re-scope/evidence/186-18-market-regimes-dry-run.json
    - .planning/todos/pending/478-regime-volatility-1d-three-state-fit-collapses-on-250-day-windows.md
  modified:
    - src/intelligence/features/kernels/_hmm.py
    - services/regime_coverage_auditor.py
    - services/cross_sectional_regime_model.py
    - scripts/infrastructure/features_capture_regime_kernel_golden.py
    - tests/fixtures/regime_kernel/ (manifest, real_golden, synthetic_golden)
    - docs/operations/operations-infrastructure.md
    - docs/research/summary-cards/cache-feature-vectors-v1.md
key-decisions:
  - "alpha.hmm.walk_forward.refit_every_bars.1d stays 252: the pre-registered rule kept it, and the measurement shows the schedule is not the cause of sparse 1d regime_volatility (todo 478)"
  - "The five auditor symbols are registered as exceptions expiring 2026-12-29, because the kernel labels all of them (class d) and the 186-26 rebuild writes those labels"
  - "market_regimes orphan cleanup run deferred: J = 510,835 timestamps join feature_vectors and 186-20-SUMMARY.md is not on main"
patterns-established:
  - "a dry-run diff that joins feature_vectors reads the distinct bar timestamps once (a correlated EXISTS per row ran over 4 minutes)"
requirements-completed: [D-29, D-01]
duration: 4h
completed: 2026-09-30
---

# Phase 186 Plan 18: Regime bundle on the kernel (286, 289, 292, 341, 420)

The trend obs matrix no longer feeds the HMM a zero-padded vol_of_vol warmup, the 1d refit
schedule was measured and kept, the nightly coverage canary goes red only on new or expired gaps,
and `market_regimes` is replaced atomically per (group, tf). The one deferred step is the orphan
cleanup run, which waits for 186-20. No regime recompute was written into `feature_vectors`,
`regime_writer` was never run.

## Commits (branch phase-186-18, merged to main locally; not pushed)

| Task | Commit | Message |
|---|---|---|
| 1 | `f573aeab7` | fix: start trend HMM obs rows after the nested vol_of_vol warmup (todo 286) |
| 1 | `faeabc867` | test: pin WR-01 churn reset across skipped segments on both kernel families (todo 292) |
| 1 | `b42fbdd3b` | docs: record the 286 obs artifact and the 292 stored churn defect on the card |
| 1 | `d396fc17a` | test: regenerate regime golden after the todo 286 obs start fix |
| 1 | `968deff22` | docs: close todos 286 and 292 |
| 2 | `4bf3c6251` | feat: read-only regime kernel coverage sweep |
| 2 | `81c22910c` | docs: pre-register the 289 decision rule and the 341 classification rule |
| 2 | `b7f60706e` | feat: regime coverage auditor fails only on unregistered or expired gaps |
| 2 | `7ffe947b0` | docs: coverage evidence for todos 289 and 341; sweep classes n_obs at the boundary as history short |
| 2 | `67a52ac18` | chore: migration 420 seeds auditor exceptions; 1d refit schedule kept at 252 |
| 2 | `6e9c8ab73` | fix: auditor logs no_unregistered_gap_found when every gap is excepted |
| 3 | `d1d7633ea` | fix: cross_sectional_regime_model replaces each (group, tf) history atomically (todo 420); migration 419 |
| 3 | `961322cf5` | fix: dry-run feature_vectors join reads distinct bar timestamps once |
| 3 | `c902707cf` | docs: close todos 289 and 341, file 478, record the 420 dry run and deferral |

## D-01 gate

`ps -eo pid,cmd | grep -E '[i]c_engine|[r]egime_writer|[c]ross_sectional_regime|[r]ebuild|[b]ackfill_feature_factory|[i]c_measure'`
at 2026-09-30 21:2x EDT, again before the task 3 edits and before the dry run: no output. STATE.md
lists no live or resumable ic_engine corpus run or feature rebuild (its lane table has only the phase
186 build row). The todo 449 backfill lane (`infrastructure_run_historical_pipeline.py`,
`intraday_chain.sh`) was running throughout and was not touched; load stayed at 2 to 5 on 24 cores.
No file under `logs/backfill_ops` was read or written.

## Task 1: todos 286 and 292

RED (against the merged 186-13 code), `test_trend_vol_of_vol_never_reaches_the_zero_padded_realized_vol_warmup`:

```
AssertionError: first obs row is log-return row 19, but its vol_of_vol window reaches realized_vol warmup padding until row 38
assert 19 >= 38
```

Fix `f573aeab7`: trend start index `max(max(windows) - 1, vol_window + vol_of_vol_window - 2)`, short-series
threshold `len(log_returns) < start + 1`; the commit lists no file under `tests/fixtures/regime_kernel/`.
It leaves the golden-comparing tests failing until `d396fc17a` (separate commits as planned). The
fix needed fixture work the plan did not name: `make_collapsing_segment_bars` is tuned to obs row j
= bar j + 20; it is now 939 bars on seed 2 (first segment bars 639..938), chosen because at seed 7 the
training slice at the later start fails the gate (min fraction 0.04) while at seed 2 the training slice
passes and the whole-segment decode has an empty state. The kernel gate tests, the first-boundary test
and one writer wrapper test (`test_build_obs_matrix_shape`) were shifted by 19 bars; all still assert
what they asserted.

Golden regeneration `d396fc17a`, from `real_inputs.npz` and the manifest APR snapshot (no DB read), with a
pre-fix `--dump` taken from a scratch worktree at the parent commit. Rule checked before committing: every
volatility digest unchanged; five trend cases changed and nothing else. `--verify`: `VERIFY OK: 10
case/family digests match the stored golden`. The capture script now keeps earlier records in
`regeneration_history` (186-13's is the first entry); the manifest holds `186-18 todo 286` in its reason.

| Case | Rows labeled now | Rows lost label | Rows gained label | Segments flipped |
|---|---|---|---|---|
| SPY/1d trend | 4,545 | 0 | 0 | 0 |
| TLT/1d trend | 504 | 252 | 252 | 2 |
| LQD/1d trend | 252 | 0 | 252 | 1 |
| SPY/1h trend | 27,915 | 1,650 | 0 | 1 |
| synthetic trend | 2,061 | 600 | 0 | 2 |

Changed rows outside flipped segments exist in every case, expected: every trend training slice changed.

Todo 292: the WR-01 pin was not present on the kernel path (the existing writer-level tests drove the deleted
functions through a patched `_walk_forward_hmm_full`), so `test_duration_and_churn_restart_across_a_skipped_segment`
is new, parametrized over both families. It passes on first run: it pins existing behavior, it was not a RED test.
The 9.4M stored `hmm_vol_churn` rows are not recomputed in place (the only write path is `regime_writer`'s UPDATE,
refused by the todo 426 guard; 186-26 recomputes every regime column). Grep of `src/intelligence/research/`,
`scripts/research/` and `docs/research/construction-verdict-ledger.md` for `hmm_vol_churn` and `hmm_churn`: no hits.
Both defects are on the `cache-feature-vectors-v1` card (`test_summary_cards.py` green).

## Task 2: todos 341 and 289

Auditor gap list today (the same query the nightly timer runs): BIL, EMLC, ETHA, IBIT, VIXY.

### 341 classification (rule committed before the sweep; trend column, which is what the auditor reads)

Sweep: 5 names x 4 tfs x 2 families, 5 workers, 912 s, load average 2.5 at launch.

| symbol | 1d | 15m | 1h | 5m |
|---|---|---|---|---|
| BIL | d (4 segments, 1,008 rows) | e (16 degenerate, 1 not converged) | b | b |
| EMLC | d | d | d | d |
| ETHA | a (501 obs, boundary 504) | b | d | d |
| IBIT | d | d | d | b |
| VIXY | d | d | d | d |

All five have kernel labels in at least one trend cell, so the 186-26 rebuild writes labels for all five.
BIL 15m trend falls in the rule's (e) bucket only because its rejections mix degenerate occupation and one
not-converged fit; each segment was rejected by a named gate (near-flat price, todo 168 precedent), so it is not a
code defect and no global HMM parameter was touched. Sweep script fix found by the 289 run: a series with n_obs
equal to the first boundary (SDRL volatility, 504 observations) has no row to segment and was classed (e); the
rule now reads `n_obs <= boundary` for (a) and the stored cells were reclassified from their stored counts
(listed in the evidence file under `classifier_correction`). The 341 cells did not change class.

### 289 decision (rule text in todo 289, committed `81c22910c` before the run)

Metric: pooled 1d segment skip fraction per family at `hmm_refit_every_bars_1d` in {126, 252, 504}; deciding value =
larger of the two families; keep 252 if within 0.02 of the smallest, else the smallest. Sample choice stated before
launch: all 931 `compute_eligible_1d` names, estimated at most about 1.9 h from the manifest's runtimes (6 workers);
actual 3,409 s (57 min), 5,586 cells, 0 errors. Bars only, no returns read.

| schedule | trend skip | volatility skip | deciding | trend labeled fraction | volatility labeled fraction |
|---|---|---|---|---|---|
| 126 | 0.1506 | 0.9838 | 0.9838 | 0.849 | 0.016 |
| 252 | 0.1594 | 0.9821 | 0.9821 | 0.840 | 0.018 |
| 504 | 0.1799 | 0.9794 | 0.9794 | 0.819 | 0.020 |

Result: 252 is within 0.02 of 0.9794, so it is kept. Dominant skip reason in both families: degenerate occupation (no
not-converged or other-gate skips at 1d). No schedule change, so the config default, `_WALK_FORWARD_DEFAULT_PARAMS` and
`config_state` agree at 252 and no golden regeneration was needed for it. The finding behind it: 1d `regime_volatility`
is gated off for about 98% of segments at every schedule (215 of 12,012 attempted segments written at 252; 145 of 931
names labeled); the minimum state occupation of the training decode is exactly 0 in 560 of the 742 no-label cells. The
cause is the model configuration (3 states on 250-day windows), filed as todo 478 (P1, PRIORITIES row).

### Auditor and migration 420

`services/regime_coverage_auditor.py`: `parse_known_exceptions`, `evaluate_gaps(gap_symbols, exceptions, today)`,
`AuditResult`; fails only on unregistered or expired gaps, warns on stale entries, malformed list fails the job with
status `failure`. Migration 420 (applied live, committed `67a52ac18`; the highest file before it was 419, mine) seeds
`alpha.regime.coverage_auditor.known_exceptions` (json value type) with the five symbols, each reason naming the class,
expiry 2026-12-29, and one `config_history` row. Verified: `config_state` count 1, `config_history` count 1. The
auditor run from the worktree after the migration: exit 0, log `no_unregistered_gap_found` with 5 excepted. The earlier
`gap_found` and malformed-list log lines in `logs/regime_coverage_auditor.log` of the worktree are from the unit tests.

## Task 3: todo 420

D-08 grep: `_write_rows` is used only inside `cross_sectional_regime_model.py` (its own test checks it is gone); the
module has no importer outside its own test file (the plan's note that ic_engine imports it does not hold in this tree).
Code `d1d7633ea`: `_replace_group_tf` (temp stage with COPY, one FULL OUTER JOIN diff, shrink guard, DELETE + INSERT, single
commit; rollback tested with a fake connection failing on the INSERT), `--accept-orphan-delete`, `--dry-run` that stages and
diffs and writes nothing to `market_regimes`. Migration 419 (applied live, same commit) seeds
`alpha.regime.cross_sectional.max_orphan_delete_fraction` = 0.01.

EXPLAIN (SOP, before the join counts): the probe as a correlated `EXISTS` ran past 4 minutes in the dry run and was killed
(and its backend terminated); the rewrite reads `SELECT DISTINCT bar_ts FROM feature_vectors WHERE tf = %s` once (3.6 s for
5m, 396,423 timestamps; the equity 5m semi-join EXPLAIN ANALYZE 5.5 s) and joins it (`961322cf5`).

Dry run (read-only, `evidence/186-18-market-regimes-dry-run.json`), per (group, tf): stored / produced / orphaned / changed / new,
and the feature_vectors join counts:

| group | tf | stored | produced | orphaned | changed | new |
|---|---|---|---|---|---|---|
| equity | 5m | 2,084,617 | 376,494 | 1,710,775 | 186,132 | 2,652 |
| equity | 15m | 694,855 | 125,508 | 570,231 | 124,457 | 884 |
| equity | 1h | 173,605 | 29,359 | 144,500 | 29,017 | 254 |
| equity | 1d | 7,067 | 4,817 | 2,283 | 4,772 | 33 |
| rates | 5m | 935,042 | 174,050 | 763,644 | 0 | 2,652 |
| rates | 15m | 311,682 | 58,035 | 254,531 | 0 | 884 |
| rates | 1h | 80,145 | 15,629 | 64,754 | 0 | 238 |
| rates | 1d | 3,221 | 2,230 | 1,018 | 0 | 27 |
| commodity | 5m / 15m / 1h / 1d | 392,412 / 130,547 / 37,153 / 5,059 | 394,830 / 131,535 / 37,530 / 5,092 | 0 | 234 / 94,867 / 26,696 / 4,859 | 2,418 / 988 / 377 / 33 |
| fx | 5m / 15m / 1h / 1d | 344,480 / 121,544 / 28,563 / 4,798 | 346,925 / 122,424 / 28,817 / 4,829 | 0 | 0 / 0 / 354 / 0 | 2,445 / 880 / 254 / 31 |

Weekend orphans total 1,223,265 (equity 844,895, rates 378,370), exactly the todo's figure. Weekday orphans are 2,288,471,
not zero: the stored history carries rows for bars the tradeable view no longer serves. J, the orphaned, changed and new
timestamps that join a feature_vectors row, is 510,835 (all categories; feature_vectors has no weekend 1d bars, and the
weekend split is in the file). J is nonzero and `186-20-SUMMARY.md` is not on main, so the cleanup run was not executed:

186-18 cleanup run deferred to after 186-20: J=510,835 market_regimes rows that join feature_vectors would change the cells
186-20 replays; rerun `cross_sectional_regime_model.py --accept-orphan-delete` then VACUUM after 186-20's parity report is on
main and before the rebuild launch; the deferred rerun is owned by the 186-26 executor (task 1's conditional step, per todo
420's Deferred rerun owner note). Todo 420 stays pending with the numbers above.

## Deviations from Plan

1. **[Rule 3] Names that landed in 186-13 differ from the plan's.** `HmmConfig.from_values` (not
   `hmm_config_fields_from_values`), config handed to `compute_kernels` as a namespace with `.hmm`, `compute_regime_columns`
   returns `(columns, events)`. The sweep follows the merged code: overrides are `dataclasses.replace` on a `HmmConfig`.
2. **Sweep signature.** `summarize_segments(segment_status, refit_every_bars)` takes the schedule: segments cannot be counted from the
   status array alone (adjacent segments share a status). Added `--sweep field=v1,v2` for the 289 grid and a `cell["skip_events"]`
   diagnostic from `compute_regime_columns` for no-label cells.
3. **Fixture retune** (task 1): see above; the plan did not list the change.
4. **WR-01 test** was new rather than present, and is a pin not a RED test.
5. **`STATE.md` not edited** (dispatch: coordinator owns it; the plan's step 5 edit is relayed below).
6. **Branch name.** The worktree branch is `phase-186-18` as the plan and dispatch say; the executor boilerplate's
   `worktree-agent-*` namespace check was therefore not applied.
7. **`/simplify` and `/review` cannot be invoked from an executor.** I read the full diff for dead code, stale docstrings and
   mirrored logic instead (one stale paragraph in `_build_obs_matrix_volatility` and the manifest history were fixed that way); the
   coordinator runs the two gates after this lands.
8. **Estimate.** The pre-run estimate for the 289 run was 1.9 h worst case; it took 57 min.

## Verification

- Worktree `pytest tests/unit/ -q -x`: exit 0, 4 skips (listed in the log), before the merge. Merged-main run recorded under
  "Merged main" below.
- `repro_frozen`: not required; `git diff --stat main..HEAD -- src/intelligence/research src/intelligence/statistics services/regime_writer.py services/_batch_utils.py` is empty.
- ruff and black clean on every touched Python file; `vulture` adds no finding (one new finding, `conn.read_only`, was
  removed by using `set_read_only`); mypy: `src/intelligence/features/kernels/_hmm.py` is the only touched file under `src/`,
  and `mypy src/ | mypy-baseline filter` prints the same 1,436 findings on a worktree of main and on this branch (the filter
  does not match baseline paths from a worktree), so none are new.
- `--verify` of the regime golden: `VERIFY OK: 10 case/family digests match the stored golden`.
- `tools/check_plugin_invariants.sh` (all four modes) and `tools/check_duplicate_tests.py` pass; `test_todo_priorities_link_integrity.py` passes.

## Relay to the coordinator

- STATE.md line 88, the "Alarm fatigue" bullet ("`regime_coverage_auditor` fails every night on 5 known symbols (todo 341)"):
  replace it with the plain fact: the coverage auditor fails only on unregistered or expired gaps; the five
  known symbols (BIL, EMLC, ETHA, IBIT, VIXY) are exceptions in APR `alpha.regime.coverage_auditor.known_exceptions` until
  2026-12-29 and clear when the 186-26 rebuild writes labels.
- Todo 478 (P1) needs a decision before the 186-25/186-26 rebuild: 1d `regime_volatility` is labeled on about 1.7% of rows.
- The todo 420 cleanup run is owned by the 186-26 executor (see above); `market_regimes` is untouched.
- The ROADMAP tick for 186-18 is added on main after the merge.

## Known Stubs

None.

## Threat Flags

None: no new endpoint or trust-boundary file access. The sweep reads bars read-only; the dry run creates a session temp table and rolls
back; migrations 419 and 420 add one APR key each.

## Self-Check: PASSED
