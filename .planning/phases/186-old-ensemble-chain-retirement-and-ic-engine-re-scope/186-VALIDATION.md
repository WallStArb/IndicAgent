---
phase: 186
slug: old-ensemble-chain-retirement-and-ic-engine-re-scope
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-09-27
---

# Phase 186 - Validation strategy

> Per-phase validation contract for feedback sampling during execution. Source:
> `186-RESEARCH.md` "Validation architecture".

## Test infrastructure

| Property | Value |
|---|---|
| Framework | pytest 9.0.3 |
| Config file | `pytest.ini` |
| Quick run command | `.venv/bin/pytest tests/unit/<file> -x -q` plus `.venv/bin/pytest tests/unit -q --co` (dead imports fail at collection) |
| Full suite command | `.venv/bin/pytest tests/unit/ -q` |
| Estimated runtime | about 10 minutes full suite; under 60 s per quick run |

## Sampling rate

- After every task commit: the touched test files plus the collection-only run.
- After every plan wave: full `tests/unit`.
- Before `/gsd-verify-work`: full suite green, `repro_frozen` bit-identical, parity report committed.
- Max feedback latency: 60 s for quick runs.

## Per-decision verification map

| Decisions | Behavior | Test type | Automated command | File exists | Status |
|---|---|---|---|---|---|
| D-04..D-06 | card front matter valid; every dropped table covered by a card | unit | `pytest tests/unit/test_summary_cards.py -x` | W0 | pending |
| D-07..D-10, R-01, R-04 | no import of deleted modules anywhere | collection + full | `pytest tests/unit -q --co` then full suite | yes | pending |
| D-11, R-05 | promoted `repro_frozen` bit-identical; unpickler remaps old class path on a real frozen pickle | unit + run | promoted `repro_frozen` test; tool run on a frozen book | W0 | pending |
| D-14, D-16 | drop migrations; compressed-hypertable VACUUM rule | unit | `pytest tests/unit/test_compressed_hypertable_migration_vacuum_check.py` | yes | pending |
| D-17..D-20 | proposer, term structure, monitoring pure on synthetic panels; scope in unique key | unit | `pytest tests/unit/measure/ -x` | W0 | pending |
| D-19 | no written IC row has target end at or after `oos_start` | unit + SQL | fixture test; post-write count query recorded in summary | W0 | pending |
| D-21, R-06 | harness reproduces stored `ic_value` with table targets; kernel diffs attributed to gap rows | unit + script | `pytest tests/unit/measure/test_parity_harness.py`; committed parity report | W0 | pending |
| D-24 | COPY in chunk order, per-chunk compress, idempotent rerun is a no-op, float32 clamp | unit (fakes) + integration | `pytest tests/unit/test_bulk_load.py tests/integration/test_bulk_load.py` | W0 | pending |
| D-25 | byte-identical float32 before and after the split | unit | `pytest tests/unit/intelligence/test_kernel_registry_parity.py` and existing batch parity test | W0 | pending |
| D-27 | causality probe fails an injected lookahead kernel, passes real kernels | unit | `pytest tests/unit/intelligence/test_causality_probe.py` | W0 | pending |
| D-28 | todo 339 bounded worker payload | unit | backfill_feature_factory tests (extended) | yes | pending |
| D-29, R-10 | walk-forward only; regime as a rebuild kernel | unit | `pytest tests/unit -k regime_writer` (extended) | yes | pending |
| D-30, R-03 | lifecycle decides from data quality only; no ensemble reads | unit | `pytest tests/unit/test_feature_lifecycle.py` (rewritten) | yes | pending |
| D-32, D-32a, R-09 | precondition checker refuses on each missing gate; resume skips completed units | unit + pilot | `pytest tests/unit/test_rebuild_preconditions.py`; pilot log | W0 | pending |
| D-36..D-38, R-12 | index and PK state; settings applied | SQL, recorded in summaries | psql queries from RESEARCH.md | manual | pending |

CI boundary tests that change with this phase: `test_market_data_ohlcv_boundary.py`,
`test_compressed_hypertable_write_boundary.py`, `test_compressed_hypertable_migration_vacuum_check.py`,
`test_todo_priorities_link_integrity.py`, `test_span_coverage_compliance.py`,
`test_ic_engine_active_scales_boundary.py` and `test_ic_engine_worker_otel_boundary.py` (deleted
with the old engine), `tests/unit/_source_grep_helpers.py`.

## Wave 0 requirements

- [ ] `tests/unit/test_summary_cards.py`
- [ ] `tests/unit/test_bulk_load.py`, `tests/integration/test_bulk_load.py`
- [ ] `tests/unit/measure/` (proposer, term structure, monitoring, parity harness)
- [ ] `tests/unit/intelligence/test_kernel_registry_parity.py`, `test_causality_probe.py`
- [ ] `tests/unit/test_rebuild_preconditions.py`
- [ ] promoted `repro_frozen` test with a fixture pickle carrying the old class path

## Manual-only verifications

| Behavior | Decisions | Why manual | Instructions |
|---|---|---|---|
| Postgres restart with new `shared_buffers`/`work_mem` | D-38, R-12 | host restart, needs no batch job running | before/after measurements per the performance-investigation SOP, recorded in the plan summary |
| Rebuild pilot timing and full run | D-32a | multiday run on live data | pilot chunk first, stated expected duration, resume tested by kill-and-restart |

## Validation sign-off

- [ ] All tasks have an automated verify or a Wave 0 dependency
- [ ] No 3 consecutive tasks without an automated verify
- [ ] Wave 0 covers every missing reference
- [ ] No watch-mode flags
- [ ] Feedback latency under 60 s
- [ ] `nyquist_compliant: true` set in front matter

**Approval:** pending
