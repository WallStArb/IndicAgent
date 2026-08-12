---
phase: 142B-frame-simulation-counterfactual-tracking
verified: 2026-07-10T08:15:00Z
status: passed
score: 9/9 must-haves verified
overrides_applied: 0
---

# Phase 142B: Frame Simulation + Counterfactual Tracking Verification Report

**Phase Goal:** Prove that a reasonable execution rule (stop/target/hold) can capture the
signal IC proven in Phase 142A as positive counterfactual P&L is a binary question this phase
does NOT answer yet — this phase builds the two services (`AlphaFrameWriter`,
`CounterfactualTracker`) and the frozen `SHADOW-REVIEW.md` pre-commitment document. Actually
running them against the historical corpus to answer the binary question is explicitly out of
scope for the plans in this phase (Phase 147 territory / a follow-on ops run).

**Verified:** 2026-07-10T08:15:00Z
**Status:** passed
**Re-verification:** No — initial verification

## Goal Achievement

The phase goal, correctly scoped, is: ship a schema + two services + a frozen pre-commitment
document that are each individually correct and ready to be run against the corpus in a later
phase — not to produce the binary IC-capture verdict itself (explicitly deferred to Phase
147/ops per CONTEXT.md and both plans' `<post_execution>` notes). Verified against that scope.

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | `alpha_frames` hypertable exists with D-04 lifecycle CHECK (`closed_ic_decay` in, `closed_reversal` out), composite PK `(frame_id, bar_ts)`, no FK to `alpha_events`, provenance columns | ✓ VERIFIED | Live DB: `timescaledb_information.hypertables` returns `alpha_frames`; `\d alpha_frames` shows `alpha_frames_pkey PRIMARY KEY, btree (frame_id, bar_ts)`; migration 214 SQL contains the corrected CHECK constraint and no `REFERENCES alpha_events`; `corpus_run_id`/`weight_epoch` columns present |
| 2 | Every `alpha_events` row maps to at most one primary `alpha_frames` row via idempotent `content_key`-derived `frame_id`; `ON CONFLICT` target is `uq_alpha_frames_variant` | ✓ VERIFIED | `services/alpha_frame_writer.py:181` `ON CONFLICT (event_id, bar_ts, frame_variant) DO NOTHING`; `frame_id = BaseBatch.content_key(event_id, str(bar_ts), 'primary')` (line 331); idempotency proven by `tests/unit/test_alpha_frame_writer.py` |
| 3 | `AlphaFrameWriter --backfill` processes the alpha_events backlog per-(symbol,tf) partition in chunks, no single long-running write transaction; geometry columns NULL at write time, ATR is caller-supplied (never read from `feature_vectors`) | ✓ VERIFIED | `_process_partition` per-(symbol,tf) with `chunk_size` flush (`alpha_frame_writer.py:275-370`); `grep -c feature_vectors services/alpha_frame_writer.py` = 0; `compute_frame_geometry` takes `atr` as a parameter, never queries a table |
| 4 | Nine (plus one from migration 215 = ten) APR keys seeded under correct names (`target_r_multiple` not `target_r_fallback`) | ✓ VERIFIED | Live `config_state`: all 10 keys present with correct values (`alpha.frame.stop_atr_mult=1.5`, `alpha.frame.target_r_multiple=2.0`, `alpha.frame.atr_period=14`, `alpha.scoring.min_strategy_n=30`, `alpha.scoring.bootstrap_max_n=5000`, `alpha.scoring.bootstrap_batch=1000`, `alpha.scoring.bootstrap_random_state=42`, `infra.alpha_frame_writer.chunk_size=50000`, `infra.counterfactual_tracker.itersize=5000`, `infra.counterfactual_tracker.workers=12`); `grep target_r_fallback` migration 214 = 0 |
| 5 | D-03 `gross_expected_r`/`cost_r`/`net_expected_r` diagnostic snapshots populated non-NULL on every frame, documented column-comment units | ✓ VERIFIED | `compute_expected_r_snapshot` unit-tested (`test_alpha_frame_writer.py`: `(0.4, 2.0, 0.05)` → `(0.8, 0.75)`, direction-agnostic); migration 214 has `COMMENT ON COLUMN` for all three; INSERT SQL includes all three columns |
| 6 | `SHADOW-REVIEW.md` exists, frozen, with five numerically-evaluable gross-pnl gate criteria, `net_expected_r` mandatory reporting column, day-clustered block-bootstrap method + residual-correlation caveat | ✓ VERIFIED | `docs/plans/SHADOW-REVIEW.md` read in full: all 5 criteria present with explicit numeric bases; criteria 4/5 have the WR-03 "fails outright on non-positive denominator" clauses; GROSS gate + net_expected_r reporting-only stated explicitly; day-clustered caveat documented |
| 7 | `determine_exit` is direction-aware (H3): short stop above entry, short target below, pnl sign flips; long-only would falsely close every short frame | ✓ VERIFIED | `services/counterfactual_tracker.py:98-145` implements direction branch exactly per spec; mandatory short-frame test cases present in `test_counterfactual_tracker_exit_priority.py`; all pass |
| 8 | ATR + T+1 entry + geometry + outcome computed in ONE named-server-side-cursor sweep per (symbol,tf) cell; no plain `conn.cursor()`; workers write-free (list[dict] only); per-symbol incremental flush, never one aggregate write | ✓ VERIFIED | `_scan_symbol_tf` uses `conn.cursor(name=cursor_name, ...)` (line 395); `grep -c "conn.cursor()"` = 0; `_run_counterfactual_worker` has no `pool.acquire`/`asyncpg`; `_flush_worker_results` flushes per-symbol-batch, proven by mock test (3 batches → 3 executemany calls) |
| 9 | FRAME-04 gate is day-clustered block bootstrap, GROSS pnl only, respects `min_strategy_n`; IC-decay row age instrumented (D-10), never freshness-gated (D-08); D-09 cadence deferred to todo 089 | ✓ VERIFIED | `frame_gate_passes` aggregates to per-day cluster means before resampling, BCa below `bootstrap_max_n` else analytic CLT (`counterfactual_tracker.py:165-228`); `evaluate_frame_gate` helper has no `cost` substring (grep-enforced test); `COUNTERFACTUAL_TRACKER_IC_ROW_AGE_SECONDS` gauge set in `_instrument_ic_staleness`; `.planning/todos/pending/089-ensemble-ic-engine-recurring-cadence.md` exists, references D-08/D-09/D-10 and the gauge |

**Score:** 9/9 truths verified

### Code-Review Blocker Remediation (142B-REVIEW.md → commit fa4208ef)

The phase's own code review (`142B-REVIEW.md`) found 2 BLOCKER-severity defects (CR-01, CR-02)
plus 3 warnings (WR-01/02/03) and 2 info findings (IN-01/02). All 7 were independently verified
present in the current code, not merely claimed fixed:

| Finding | Fix Verified | Evidence |
|---------|-------------|----------|
| CR-01 (ZeroDivisionError on zero ATR/stop_atr_mult poisons whole cell scan) | ✓ VERIFIED | `compute_frame_geometry` (`alpha_frame_writer.py:83-87`) raises `ValueError` on `atr <= 0 or stop_atr_mult <= 0`; `_scan_symbol_tf` (`counterfactual_tracker.py:428-447`) catches `ValueError`, logs a warning, and `continue`s (skips just that frame, not the cell); dedicated regression tests `test_zero_atr_raises_value_error_not_zero_division_error` / `test_zero_stop_atr_mult_raises_value_error` pass |
| CR-02 (`target_r_multiple` not snapshotted, silent historical drift on recalibration) | ✓ VERIFIED | Migration 215 adds `alpha_frames.target_r_multiple` column (confirmed live in `\d alpha_frames`); `AlphaFrameWriter._INSERT_SQL` writes it (col 17, `frame_config.target_r_multiple`); `_OPEN_FRAMES_SQL` selects it; `_scan_symbol_tf` reads `frame["target_r_multiple"]` per-frame with the live-APR value only as a fallback for legacy NULL rows (lines 423-427); `tests/unit/test_alpha_frames_target_r_multiple_migration.py` (4 tests) passes |
| WR-01 (bootstrap CI non-reproducible, undermines "no post-hoc renegotiation") | ✓ VERIFIED | `frame_gate_passes` takes `bootstrap_random_state` param, threaded into `scipy.stats.bootstrap(..., random_state=np.random.default_rng(bootstrap_random_state))` (line 215); seeded from new `alpha.scoring.bootstrap_random_state` APR key = 42, confirmed live; `test_bootstrap_random_state_makes_ci_lower_reproducible` passes |
| WR-02/IN-01 (silent APR/data fallbacks) | ✓ VERIFIED | `hold_max_bars_key_missing` warning log (`alpha_frame_writer.py:317-328`); `cost_hurdle_missing` warning log (lines 299-309) |
| WR-03 (SHADOW-REVIEW ratio criteria undefined for non-positive denominators) | ✓ VERIFIED | Criteria 4 and 5 both have explicit "fails outright" clauses for non-positive denominators, read in full in `docs/plans/SHADOW-REVIEW.md` |
| IN-02 (unclosed connection-liveness probe cursor) | ✓ VERIFIED | `with conn.cursor(...) as probe_cur:` (`counterfactual_tracker.py:523`) |

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `production/migrations/214_alpha_frames_schema.sql` | alpha_frames hypertable + 9 APR seeds | ✓ VERIFIED | Applied live; hypertable confirmed in `timescaledb_information.hypertables`; all 9 keys in `config_state` |
| `production/migrations/215_alpha_frames_target_r_multiple.sql` | target_r_multiple column + bootstrap seed | ✓ VERIFIED | Applied live; column present; APR key `alpha.scoring.bootstrap_random_state=42` present |
| `services/alpha_frame_writer.py` | `AlphaFrameWriter(BaseBatch)` FRAME-01 | ✓ VERIFIED | 399 lines; exports `AlphaFrameWriter`, `compute_frame_geometry`, `compute_expected_r_snapshot`; no Kafka; no `feature_vectors` read |
| `services/counterfactual_tracker.py` | `CounterfactualTracker(BaseBatch)` FRAME-02/03/04 | ✓ VERIFIED | 886 lines; exports `CounterfactualTracker`, `determine_exit`, `compute_frame_pnl_r`, `frame_gate_passes`, `evaluate_frame_gate`; imports `compute_frame_geometry` from Plan 01 |
| `docs/plans/SHADOW-REVIEW.md` | Frozen Phase 147 promotion criteria | ✓ VERIFIED | 137 lines; frozen, 5 numeric criteria, GROSS gate, net_expected_r reporting column, day-clustered bootstrap caveat, WR-03 edge-case clauses |
| `src/observability/metrics.py` | IC-staleness gauge | ✓ VERIFIED | `COUNTERFACTUAL_TRACKER_IC_ROW_AGE_SECONDS` present, set via `.set(age_seconds, {...})` |
| `.planning/todos/pending/089-ensemble-ic-engine-recurring-cadence.md` | D-10 follow-on todo | ✓ VERIFIED | Exists; references D-08/D-09/D-10 and the gauge |

### Key Link Verification

| From | To | Via | Status | Details |
|------|-----|-----|--------|---------|
| `alpha_frame_writer.py` | `alpha_events`/`alpha_frames` | anti-join per-(symbol,tf) chunked write | ✓ WIRED | `_PENDING_SQL` LEFT JOIN anti-join, per-partition, chunked `executemany` flush |
| `migration 214` | `config_schema`/`config_state` | APR seed triad | ✓ WIRED | All 9 (+1 from 215) keys present live |
| `counterfactual_tracker.py` | `market_data_ohlcv` | named server-side cursor, one sweep per cell | ✓ WIRED | `conn.cursor(name=cursor_name, ...)`, verified no plain cursor exists |
| `counterfactual_tracker.py` | `alpha.scoring.min_strategy_n`/`bootstrap_max_n` | `frame_gate_passes` reads APR | ✓ WIRED | `_run_evaluate_gate` loads `alpha.scoring.%` from `config_state`, passes to `evaluate_frame_gate` |
| `counterfactual_tracker.py` | `alpha_ensemble_ic` | most-recent-row read, age instrumented | ✓ WIRED | `_IC_CI_LOWER_SQL` reads regardless of age (D-08); `_instrument_ic_staleness` sets the gauge (D-10) |
| `counterfactual_tracker.py` | `alpha_frame_writer.py` | imports `compute_frame_geometry` | ✓ WIRED | `from services.alpha_frame_writer import compute_frame_geometry` (line 69), used at line 429 |
| `services/service_auditor.py` | both new services | `_DAG_ORDER` + `_ONESHOT_UNITS` registration | ✓ WIRED | Both `indicagent-alpha-frame-writer` and `indicagent-counterfactual-tracker` present in both dicts (lines 114-115, 209-210) |
| `infrastructure_truncate_derived_tables.sh` | `alpha_frames` | corpus-rebuild truncation | ✓ WIRED | `TRUNCATE alpha_frames;` present, plus pre/post count-report SELECTs |

### Data-Flow Trace (Level 4)

Not applicable in the traditional sense (no UI/dashboard rendering) — this phase's "data flow"
is DB read → pure-fn compute → DB write, already covered by Key Link Verification above. The
one relevant trace: `alpha_frames` currently has 0 rows, which is the CORRECT and EXPECTED
state per the phase's explicit scope boundary — `AlphaFrameWriter --backfill` and
`CounterfactualTracker --backfill`/`--evaluate-gate` have not been run against the live corpus,
and running them is explicitly deferred to Phase 147 / a follow-on ops run per both plans'
`<post_execution>` sections and CONTEXT.md's Phase Boundary. This is not a gap — it is the
correctly-scoped deliverable boundary for this phase.

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Migration 214 creates a valid hypertable | `SELECT * FROM timescaledb_information.hypertables WHERE hypertable_name='alpha_frames'` | 1 row returned | ✓ PASS |
| Migration 215 adds the CR-02 column | `\d alpha_frames` shows `target_r_multiple` | column present, `double precision` | ✓ PASS |
| All 10 APR keys resolve live | `SELECT config_key, config_value FROM config_state WHERE config_key IN (...)` | 10/10 rows returned with expected values | ✓ PASS |
| `compute_frame_geometry` raises ValueError (not ZeroDivisionError) on zero ATR | `test_zero_atr_raises_value_error_not_zero_division_error` | passed | ✓ PASS |
| `frame_gate_passes` bootstrap is reproducible with a fixed seed | `test_bootstrap_random_state_makes_ci_lower_reproducible` | passed | ✓ PASS |
| Both services registered as oneshots, not lag-monitored daemons | `grep -c "indicagent-alpha-frame-writer\|indicagent-counterfactual-tracker" services/service_auditor.py` | 4 occurrences (2 services × `_DAG_ORDER` + `_ONESHOT_UNITS`) | ✓ PASS |

### Probe Execution

No `scripts/*/tests/probe-*.sh` probes declared or referenced by this phase's PLAN/SUMMARY —
skipped (this phase's verification surface is unit tests + live-DB schema/APR checks, not a
probe-script convention).

### Full Unit Suite (independently re-run by the verifier, not taken from SUMMARY claims)

Ran directly by this verifier (not trusting the SUMMARY's self-reported numbers):

```
.venv/bin/pytest tests/unit/ -q
```

Result: **1 failed, 5652 passed, 42 skipped, 366 warnings in 684.72s (0:11:24)**

The single failure is `tests/unit/test_feature_factory.py::TestRegimePrimitives::test_no_smooth_or_backward_in_factory`.
Confirmed via `.planning/todos/pending/086-hmm-test-coverage-gaps.md` (finding #2) that this is
a pre-existing, already-tracked false positive in a blunt grep-based look-ahead-bias check that
trips on the English word "smoothed" in a confirmed-causal volatility estimator's variable
names — unrelated to Phase 142B's changes, not introduced by this phase. The phase-specific
test files (6 files, 80 tests: `test_alpha_frames_schema.py`,
`test_alpha_frame_writer_geometry.py`, `test_alpha_frame_writer.py`,
`test_alpha_frames_target_r_multiple_migration.py`, `test_counterfactual_tracker_exit_priority.py`,
`test_frame_gate.py`, `test_counterfactual_tracker.py`) all pass with zero failures.

This exactly matches the SUMMARY's claimed final state (5652 passed, 42 skipped, 1 pre-existing
unrelated failure) — independently reproduced, not merely trusted.

### Requirements Coverage

This project uses `.planning/ROADMAP.md`'s inline FRAME-01..04 requirement IDs plus
`142B-CONTEXT.md`'s D-01..D-10 decisions as the requirements source for this phase — there is
no `.planning/REQUIREMENTS.md` file (confirmed absent). Requirement IDs are declared in each
plan's frontmatter (`142B-01-PLAN.md`: `[FRAME-01, FRAME-03]`; `142B-02-PLAN.md`: `[FRAME-02,
FRAME-03, FRAME-04]`).

| Requirement | Source Plan | Description | Status | Evidence |
|--------------|------------|-------------|--------|----------|
| FRAME-01 | 142B-01 | AlphaFrameWriter writes one hypothetical frame per alpha_events row | ✓ SATISFIED | `AlphaFrameWriter` implemented, tested, idempotent |
| FRAME-02 | 142B-02 | CounterfactualTracker nightly oneshot scoring frame outcomes | ✓ SATISFIED | `CounterfactualTracker` implemented, tested, registered |
| FRAME-03 | 142B-01, 142B-02 | Frame lifecycle state machine (schema + exit logic) | ✓ SATISFIED | D-04 CHECK constraint + direction-aware `determine_exit` both implemented and tested |
| FRAME-04 | 142B-02 | Phase 142B exit gate (day-clustered bootstrap) | ✓ SATISFIED | `frame_gate_passes`/`evaluate_frame_gate`/`--evaluate-gate` CLI mode implemented and tested |

All 10 D-01..D-10 decisions from CONTEXT.md were checked against code/docs during this
verification (D-01 gross gate, D-02 net_expected_r reporting, D-03 diagnostic snapshot, D-04
lifecycle CHECK, D-05 backfill mode, D-06 nightly cadence via BaseBatch, D-07 unfiltered
population, D-08 no freshness gate, D-09 cadence out of scope, D-10 age instrumented) — all
confirmed implemented as specified. No orphaned requirements found.

### Anti-Patterns Found

None. Scanned `services/alpha_frame_writer.py`, `services/counterfactual_tracker.py`,
`production/migrations/214_alpha_frames_schema.sql`,
`production/migrations/215_alpha_frames_target_r_multiple.sql`, and `docs/plans/SHADOW-REVIEW.md`
for `TBD|FIXME|XXX|TODO|HACK|PLACEHOLDER` (zero matches), stub-language
(`not yet implemented`/`coming soon`/`will be here` — zero matches), and hollow returns
(`return null|return {}|return []` — the one `return []` match in `counterfactual_tracker.py:369`
is a legitimate early-return for an empty open-frames query result, not a stub). No debt
markers found in any file this phase touched.

### Human Verification Required

None. All must-haves are verifiable via code/schema/APR inspection and the automated test
suite; nothing in this phase's scope depends on visual rendering, real-time behavior, or
external-service integration that can't be checked programmatically.

### Gaps Summary

No gaps. This phase's scope is deliberately narrow (schema + two services + a frozen document,
not a corpus run), and every item within that scope — including all 7 code-review findings from
`142B-REVIEW.md` — is verified present and correctly implemented in the current codebase, not
merely claimed in SUMMARY.md. `alpha_frames` having 0 rows is the expected state given the
phase's explicit boundary (running the services against the 12.2M-row corpus and evaluating the
FRAME-04 gate is Phase 147/ops-run territory, documented as such in both plans'
`<post_execution>` sections).

---

_Verified: 2026-07-10T08:15:00Z_
_Verifier: Claude (gsd-verifier)_
