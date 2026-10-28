---
phase: 184-multi-timeframe-research-inputs
plan: 01
subsystem: research
tags: [multi-timeframe, clock, align, causality, nyse-calendar]
requires: []
provides:
  - "clock.closes_at: calendar-exact availability time per grid row"
  - "align.align_index / gather / align: the one cross-clock alignment implementation"
  - "align.check_alignment: S3 proof over every scored row"
  - "align.align_causality_probe: unit-level cross-clock probe"
  - "tests/unit/research/mtf_fixtures.py: real-calendar 5m/15m/1h/1d grids"
affects: [184-07, 184-08, 184-10]
tech-stack:
  added: []
  patterns: ["searchsorted side=right over non-NaT availabilities mapped back to source-grid rows", "np.maximum.accumulate index of latest finite row (index, never value copy)"]
key-files:
  created:
    - src/intelligence/research/clock.py
    - src/intelligence/research/align.py
    - tests/unit/research/mtf_fixtures.py
    - tests/unit/research/test_clock.py
    - tests/unit/research/test_align.py
  modified: []
decisions:
  - "align_causality_probe takes an optional fn (the composition under test); without it the probe aligns with the same src_avail it treats as truth and cannot see a falsely early availability"
  - "align_index without n_symbols on a [ns, 1] source returns one column; broadcasting happens only when n_symbols is passed"
  - "closes_at refuses only traded rows outside their session; untraded rows (half-day slots after 13:00 ET) are NaT"
metrics:
  duration: "about 8h wall clock, most of it the compare-all replay"
  completed: 2026-10-28
  tasks: 2
  files: 5
---

# Phase 184 Plan 01: clock and align summary

`closes_at` gives each grid row the earlier of its slot end and its NYSE session close (NaT where untraded). `align` reads, per destination row and symbol, the latest finite source value available at or before the destination close and at most `max_age_rows` source-grid rows old. It is a gather over the one `align_index`, and `check_alignment` is the S3 proof over that index.

## Tasks

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Shared MTF fixtures and clock.closes_at (B1b) | 9c50cea45 | mtf_fixtures.py, clock.py, test_clock.py |
| 2 | align node with D7 guards 1 and 2 (B3a-c) | ad53f40fe | align.py, test_align.py (+ clock.py mypy fix) |

Tests: 15 in test_clock.py and 22 in test_align.py, 37 passing. `-k leak` (3), `-k daily_on_intraday` (6), `-k age_grid_rows` (1) and `-k index` (3) each select passing tests. Full unit suite: `6884 passed, 1 skipped`. One earlier run showed `1 failed, 6883 passed`, which did not reproduce in two reruns and was never identified. The shared checkout had concurrent sessions editing research files at the time.

## B7 trio (verbatim)

repro_frozen (`.venv/bin/python -m scripts.research.determinism.repro_frozen <scratch> --logs /home/bg/dev/indicagent/logs`), run after commit ad53f40fe:

```
phase 179 S3: bit-identical [ 0.21612308 -0.14601638 -0.10558864]
phase 181 S2 (signal from Panel): bit-identical
phase 181 S3: bit-identical [0.19424572]
```

test_spec_hashes_pinned: `8 passed`.

`backfill_attempt_series.py --compare-all` exited 0 but did not report all equal. Log: `logs/research/series_backfill_2026-10-28T05:32:19.554747Z.json`.

```
replaying research/specs/family1_h8.yaml (4 runs)
{... "member": "same_slot_lag1", "outcome": "equal", "n_sessions": 3767}
{... "member": "same_slot_mean20", "outcome": "equal", "n_sessions": 3767}
{... "member": "same_slot_mean40", "outcome": "equal", "n_sessions": 3767}
{... "member": "same_slot_mean5", "outcome": "equal", "n_sessions": 3767}
replaying research/specs/family1_intraday_periodicity.yaml (4 runs)
{"run_id": "a72b6e93-be8e-4911-9bab-548b65a19ddf", ..., "member": "same_slot_lag1", "outcome": "series_unavailable", "reason": "replay differs", "diff": {"t": [13.526067140122194, 13.324889754694329], "p": [4.835653997660866e-41, 6.456605117520537e-40], "se": [1.3678695054491772e-05, 1.3594487228620882e-05], "mean_session_pnl": [0.00018501894769631312, 0.0001811450435929733], "memory_sessions": [null, 1]}}
{"run_id": "48913529-daff-4edf-be51-bd9ca3c43c54", ..., "member": "same_slot_mean20", "outcome": "series_unavailable", "reason": "replay differs", "diff": {"t": [18.563224900405054, 18.73965474554066], "p": [5.628952481330773e-74, 2.744232816272809e-75], "se": [1.3603588285948037e-05, 1.3463018888104202e-05], "mean_session_pnl": [0.0002525264688045691, 0.0002522923257957654], "memory_sessions": [null, 20]}}
{"run_id": "37ee0e70-7464-4810-9ec2-afa63224c549", ..., "member": "same_slot_mean40", "outcome": "series_unavailable", "reason": "replay differs", "diff": {"t": [18.410614072064696, 18.2277537574046], "p": [7.534008817939731e-73, 1.6472790803103315e-71], "se": [1.2004348025198277e-05, 1.2094183106053243e-05], "mean_session_pnl": [0.00022100741867867745, 0.00022044979155410124], "memory_sessions": [null, 40]}}
{"run_id": "c6c340d7-1e0b-4ebd-b1ab-6118921a5b6f", ..., "member": "same_slot_mean5", "outcome": "series_unavailable", "reason": "replay differs", "diff": {"t": [18.317370977616626, 18.18463435843605], "p": [3.643905039570921e-72, 3.3967587416952033e-71], "se": [1.4382200878482263e-05, 1.4248644041020091e-05], "mean_session_pnl": [0.0002634441089657634, 0.00025910638198945905], "memory_sessions": [null, 5]}}
```

Outcome tally: 4 equal (family1_h8) and 4 `series_unavailable` / "replay differs" (family1_intraday_periodicity). This is a failed gate item. Per the execution rules I did not adjust anything; it needs a decision.

Caveats:
- WIP import: the compare-all forkserver started about 00:22Z on 2026-10-28, after another session's uncommitted 187-09 Task 2 edits to `combiner.py` and `runner.py` were written (22:57Z). Its workers may have imported that work in progress. The working tree at the end of the run also held uncommitted edits to `book.py`, `certificate.py`, `power.py` and `spec.py`. 187-09 Task 2 is a no-op for every existing spec (the field is unset), so a clean pass would also have covered its parity. A failed pass cannot be attributed to it or cleared of it.
- This plan cannot be the cause: `clock.py` and `align.py` are new files that no module under `src/`, `services/` or `scripts/` imports (grep returns nothing), and repro_frozen is bit-identical.
- Possibly pre-existing: per 187-03-SUMMARY, `family1_intraday_periodicity.yaml` had never been replayed (the 187-03 dry run stopped after h2, h26 and h4, and 187-07 left the compare-all baseline unrun). This may be the first replay of these four runs. Recorded `memory_sessions` is null in all four, so they predate memory recording. The t statistics move by about 1 to 1.5 percent, which is too large for float noise.
- Suggested next step: rerun `--specs research/specs/family1_intraday_periodicity.yaml` on a clean tree (a detached-HEAD scratch worktree at a commit before the WIP) to separate a pre-existing replay mismatch from WIP contamination.

## Deviations from plan

1. [Rule 2 - correctness] `align_causality_probe` gained an optional `fn` keyword. As specified, the probe aligns with the same `src_avail` it treats as truth, so a source availability shifted one row early is invisible to it (the 184-REVIEWS row 1 concern). The planned test "raises when the source availability is shifted one row early" could only be expressed by probing a function that uses the leaky availability against the true `src_avail`. `fn` defaults to plain `align`. Covered by `test_leak_cross_clock_align_causality_probe`.
2. Commits: the plan named one commit for both tasks; the orchestrator asked for per-task commits, so there are two.
3. Acceptance grep: `grep -c "def align"` returns 3, because `align_index` and `align_causality_probe` share the prefix the plan itself mandates. `grep -c "def align("` returns 1, and `searchsorted` appears once (in `_candidates`, shared by `align_index` and `check_alignment`).
4. Simplify/review gate: these are slash-command skills the executor cannot invoke. I did a self-review pass and ran mypy on the two new modules: one `no-any-return` in `clock._as_date` was fixed, and the missing pandas stubs are environment-wide.
5. TDD: the tests and implementation were written in the same task step rather than as separate RED commits; there is no RED commit.

## Known stubs

None.

## Self-Check: PASSED

- FOUND: src/intelligence/research/clock.py, src/intelligence/research/align.py, tests/unit/research/mtf_fixtures.py, tests/unit/research/test_clock.py, tests/unit/research/test_align.py
- FOUND commits: 9c50cea45, ad53f40fe
- Shared research files: no edit from this plan (the `git diff -- src/intelligence/research/` md5 was unchanged from baseline through both task commits)
