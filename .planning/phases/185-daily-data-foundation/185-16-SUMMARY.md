# Plan 185-16 Summary: D-28 data bar check, D0 read helper, S0 hand-off

Status: complete. Task 1 committed test-first (RED 3663e2aaf, GREEN 372de8ca0), the live
check ran with evidence below, and task 2 wrote the hand-off (00cefad7a) without touching
`src/intelligence/research/` (research lane held by the phase 183 session; coordination
pending). D-03, D-07 and D-27 step 2 are met by this plan; D-28 is checkable and currently
FAILs on one condition, the phase's open blocker in front of daily attempts 3, 3b and 4.
D-04 is NOT met by this plan (by design): it is met when the lane owner applies
`185-S0-HANDOFF.md`.

## What landed

- `src/intelligence/bars/label_inputs.py`: `LabelInputs` + `async load_label_inputs(conn,
  *, symbols, tf, start, end)` (D-07). Read-only asyncpg, one parameterized query per input
  (moved names and dates from `ohlcv_venue_head`, quarantine keys as (symbol, ts_seconds)
  from `bar_quality_flag`, latest `ohlcv_request.primary_exchange` per name, D2 rule
  version from the latest completed `bar_derivation_batch` stage `daily`, Yahoo
  `dividend_event_coverage` windows), jsonb codecs registered for bare and pooled
  connections. No import from `src/intelligence/research/` (acceptance grep clean).
- `scripts/ops/bars/ops_data_bar_check.py`: the D-28 gate. Seven conditions, each a pure
  predicate over stored evidence (T-185-16-01), one PASS/FAIL line with counts, exit 1 on
  any FAIL. Late-name dispositions are recomputed from stored D1 answers via plan 14's
  `classify_head` imported from `ops_head_rerun` (no re-fetch, no new facts).
- `.planning/phases/185-daily-data-foundation/185-S0-HANDOFF.md`: exact patch description
  for the research lane owner (manifest keys `d2_rule_version` and `bar_content_digests`,
  evidence key `data_quality`, the functions to call, the tests to add, ledger sole-writer
  and determinism constraints).
- Tests: `tests/unit/bars/test_label_inputs.py` (SQL shape, array parameters, row mapping,
  codec registration, d2 None before the first daily batch, no research imports) and
  `tests/unit/scripts/test_data_bar_check.py` (every predicate's pass and fail sides,
  fixture parsing, CLI one-line-per-condition and exit codes over a fake connection).
  15 new tests; `tests/unit/bars` + `tests/unit/scripts` suites green (two pre-existing
  skips in test_research_cost_hurdle.py, unrelated).

## Live D-28 run (2026-10-02, read-only)

Command: `PYTHONPATH=. .venv/bin/python scripts/ops/bars/ops_data_bar_check.py`

```
PASS scrub_pass_complete: fact=True; dry-run keys quarantined 72/72; legacy 1d keys quarantined 15 (>= 15)
PASS seam_audit_complete: fact=True; seam_audit actions 0; without pre-seam split_seam flags 0
FAIL late_name_dispositions: late names 382; unresolved 42 (e.g. AMPH, ANET, APPS, ARES, BCML, BLBD, CHTR, COFS, CPS, CRH)
PASS no_pre_move_bars_visible: pre-move 1d bars in tradeable view 0; venue_bars_1d=false
PASS dividend_coverage: yahoo coverage 931/931 (100.0%, needs >= 99%); total_return importable=True
PASS survivorship_apr_keys: present 6/6
PASS inventory_is_active: inventory names with is_active false: 0
6/7 conditions pass
```

Exit 1. The single FAIL is the open blocker: 42 of 382 late names remain unresolved
(the ISLAND-never-answers set). The fix belongs to plan 14's re-ask lane (rerun
`ops_head_rerun.py` when the venue answers, or a disposition policy decision by the
owner); `ops_data_bar_check.py` is the gate that flips to exit 0 when they resolve. D-28
is deliberately not hidden: daily attempts 3, 3b and 4 stay blocked behind this FAIL.

Measured side facts: the 72 dry-run keys carry 75 quarantine flag rows (three keys carry
two rules each; the flag PK includes rule), all 72 distinct keys are quarantined; 0
seam-audit corporate actions exist (185-15 inferred 0 splits), so condition 2 holds
vacuously today; `bar_derivation_batch` has no stage='daily' rows, so `d2_rule_version`
is None everywhere (correct per contract until 185-17's first run).

## Deviations from plan

**1. [Rule 1 - bug] fixture-key quarantine count double-counted flag rows**
- Found during the live run: the first version printed `75/72` and FAILed
  `scrub_pass_complete`. The join counted flag rows, but the flag PK is
  (symbol, timeframe, timestamp, rule) and three of the 72 keys carry two quarantine
  rules.
- Fix: `COUNT(DISTINCT (b.symbol, b."timestamp"))`; live output now 72/72 PASS.
- File: `scripts/ops/bars/ops_data_bar_check.py`; commit 372de8ca0 (fixed inside the same
  task before the GREEN commit).

**2. RED-phase test corrections (normal TDD iteration, before GREEN)**
- The dry-run parser had an off-by-one (cells[1:4] instead of cells[0:3] after
  strip("|")); one assertion used the truthiness of the `CheckResult` dataclass instead
  of `.ok`; the fake connection's per-table replies became per-marker queues once the
  implementation settled on two config_state reads (venue flag, survivorship keys).
- Files: `tests/unit/scripts/test_data_bar_check.py`; commits 3663e2aaf and 372de8ca0.

**3. Coordination pending on task 2 (expected branch of the plan)**
- STATE.md's lanes table holds `src/intelligence/research/` with the phase 183 session
  (the 2026-10-01 release covered only the 186-29 import switch), so task 2 wrote
  `185-S0-HANDOFF.md` and left `snapshot.py` and `runner.py` untouched
  (`git diff --quiet src/intelligence/research/` holds; `tests/unit/research/` green,
  77 tests).

## Notes for 185-17 and 185-21

- 185-17's first completed stage='daily' batch is what makes `d2_rule_version` non-None;
  `load_label_inputs` and the hand-off both report None until then, never a guess. Its
  daily rows should also give `bar_content_digest_current` 1d coverage, which the
  hand-off's `bar_content_digests` manifest key reads.
- 185-21 (IBKR dividend route) does not interact with the gate's dividend condition:
  the condition reads `dividend_event_coverage` source='yahoo' (931/931 today) and only
  checks `dividends.total_return` imports.
- Anyone gating daily attempts: the gate command is the one above; exit 0 required, and
  the current FAIL is plan 14's 42 unresolved names, not a new regression.

## Commits

- 3663e2aaf test(185-16): failing tests for label inputs and D-28 data bar check (RED)
- 372de8ca0 feat(185-16): D0 label inputs read helper and D-28 data bar check (GREEN)
- 00cefad7a docs(185-16): S0/S6 data-quality hook hand-off to the research lane owner
