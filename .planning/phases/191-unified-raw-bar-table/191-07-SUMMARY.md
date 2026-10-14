WINDOW STILL OPEN, fetcher stopped and NOT resumed (task 3 not run, by instruction: the fetcher stays held until plans 08 and 10). Held units (all inactive or failed, none cleared, none resumed): indicagent-bar-reconciliation-audit.timer, indicagent-dividend-event-writer-yahoo.timer, indicagent-ibkr-history-fetcher.timer, indicagent-bar-aggregator.service, indicagent-bar-auditor.service, indicagent-bar-derivation.service, indicagent-bar-reconciliation-audit.service, indicagent-bar-writer.service, indicagent-dividend-event-writer@yahoo.service (failed), indicagent-ibkr-history-fetcher.service (failed). Record: `logs/raw_cutover_window.json` (opened 2026-10-13T19:00:40Z); `ops_raw_cutover_window status` at the end of this plan shows `cleared_by=None` for all ten.

---
phase: 191-unified-raw-bar-table
plan: 07
subsystem: bar data layer
tags: [selection-gate, bar-source-policy, alpaca-spans, session-rule, advisory-lock, ops_selection_gate]
status: TASKS 1 AND 2 COMPLETE; TASK 3 (fetcher resume) NOT RUN
requires: [191-06]
provides:
  - scripts/ops/bars/ops_selection_gate.py (--compare, --emit-spans, --apply-spans, --idempotence, --locate-unsourced, --merge; --target, --shard, --with-spans)
  - 1,641 explicit 5m bar_source_policy rows (1,529 series), written through ops_source_policy.insert_row only
  - selection session rule, session-date span matching, per-series advisory lock, unselected counts (D-191-L)
  - ops_source_policy --timeframe and CVR-driven vendor choices
affects: [191-08, 191-10, 191-11, 191-12, 191-13, 191-14]
key-decisions:
  - the session rule is by kind (sip_rth only), not a calendar filter on every vendor
  - a span's ranking is the least surprising one that reproduces canonical; a row only raw holds never narrows it; the last span of every series is open-ended (ibkr, then alpaca)
  - differences a recorded refusal explains are counted beside the zero in named classes, never folded into it
metrics:
  tasks: 2 of 3
  completed: 2026-10-14
---

# Phase 191 Plan 07: the selection gate Summary

Canonical selected from raw by policy equals today's canonical, row for row, for all 318,947,024 direct-timeframe vendor rows (5m 309,168,882; 1m 9,775,958; 4h 2,184), with zero unexplained differences. 1,641 seeded 5m policy spans reproduce the Alpaca and IBKR canonical rows; nine thousand slots on 57 series differ only in ways a recorded refusal explains and are counted below. Nothing in canonical, the ranking rules or the gate was changed to make it pass. The fetcher was not resumed.

## What was done

Commits (all on main, not pushed): `b2ffcaec4` (gate, policy writer, selection rules, loader reporting), `12b80c126` (rewrite-after-copy class, closest-ranking spans, locate mode, design D-191-L, todo 535), `349cdc825` (a row only raw holds never narrows a span), `f035d3bed` (forward tail span, `--with-spans`, scoped policy rows), `49d21f9a5` (locate in the database), `5f759b70e` (idempotence name spread). This file follows in its own commit.

### Review amendments (a) to (d) of plan 191-07

(a) Alpaca spans, held and unselected reporting. The 5m policy ranked IBKR alone; now every 5m series that has raw rows has a span ranking ibkr then alpaca (or alpaca first where canonical is Alpaca over held IBKR rows). `select_and_write` counts slots that reached raw with no ranked vendor (`unselected`); `IngressResult.n_unselected`, `LoadResult.n_unselected` and `load_status(..., unselected=)` carry it, `ops_bar_load` and `ops_bar_nightly` print `UNSELECTED` instead of `APPLIED` and exit non-zero. Coverage credit was already limited to rows new in raw and withheld for a refused chunk (06 fixes); unchanged. The gate's final compare shows `unselected_slots` 0.
(b) Session rule. Kind `sip_rth` is a candidate only on the regular-hours 5m grid (open inclusive, close exclusive, early closes from the NYSE calendar); 31,821,355 extended-hours Alpaca candidates are dropped before ranking and stay in raw. The rule is by kind, not a calendar filter on every vendor: IBKR's own session is not the calendar's (a 14:30 UTC open on 2006-12-27 where the calendar says 14:32, bars to 16:00 ET on early-close days; 150 canonical CMCSA rows alone), so a vendor-blind filter dropped real canonical rows in the first trial and was replaced.
(c) Lock and upsert. `pg_advisory_xact_lock(hashtextextended('bar_selection|symbol|timeframe'))` in sorted symbol order before the read; every insert carries the upsert tail.
(d) Session-date spans. `session_date(ts)` (America/New_York date) replaces the UTC date; policy rows are scoped per (symbol, timeframe) once per call.

### Task 1: the gate and the policy writer

- `ops_selection_gate.py`: per (symbol, timeframe) it reads canonical vendor rows (`--target` introspected once: a `vendor` column is read on (vendor, kind), a `source` column through `LABEL_TO_VENDOR_KIND`; the same code runs against v2 and the swapped table), reads `ohlcv_raw`, and selects with `select_slots`, the pure function the writer uses. Month digests (blake2b over timestamp, vendor, kind and values) localize; only a differing month gets a row-level diff, which is exact dict equality, so a collision cannot hide a difference. Totals are reported both ways (months digest-mismatched, rows differing).
- `ops_source_policy.py`: `--timeframe`, `--primary`/`--fallback` validated at run time against the CVR `bar_vendor` codes (unknown vendor refused with the list), an overlap check (`daterange &&`) instead of the open-row check, ingress mode by timeframe. `--add` still refuses an empty `--evidence` object; the plan's example dry run with `--evidence '{}'` therefore stops there (deviation below).
- Named classes (each needs ledger evidence for the exact key; anything else is a real difference): `refused_self_restatement` (same vendor and kind, an `ohlcv_revision` row holds the canonical value), `restated_after_copy` (same key, a revision holds the raw value: the retired fetcher restated canonical after the raw copy was taken), `refused_cross_vendor` (the vendor differs or raw holds a row canonical lacks, on a session date covered by a refused `ohlcv_load` of the series whose source is the selected vendor).
- D-191-I checks: `refused_value_in_canonical` and `refused_value_selected` are in the report and in the verdict; both are 0 (there are 0 `pending` revision rows today, so the check passes trivially; it is unit tested with a pending hold).
- Boundary allow-list row added for the gate (`PERMANENT`).

### Task 2: spans, the loop, idempotence

Before any span (first compare): 1m and 4h already equal (9,775,958 and 2,184 rows, 0 differences). 5m: 220,042,741 canonical Alpaca rows with no winner (the default ranked IBKR alone), 54,825 vendor differences and 2,619 raw-only rows inside refused windows (together 57,444, exactly the IBKR raw rows that have no IBKR canonical twin), 6,168 value differences with a revision holding the canonical value, 148 with a revision holding the raw value.

`--emit-spans` (12 shards, no single-connection scan) derived the minimal date-contiguous ranking runs per series. The first emit left 43 open-ended `alpaca` only tails; that ranking would have ignored IBKR for ever, so two corrections were made before anything was written: a row only raw holds never narrows a span, and every series ends with an open-ended ibkr-then-alpaca tail starting the day after its last data date. The final plan: 1,641 rows, 0 blockers, 0 conflicts.

| | rows |
|---|---|
| ibkr then alpaca | 1,585 (1,529 open-ended) |
| alpaca then ibkr | 56 (all bounded) |
| series with spans | 1,529 (every 5m series) |
| spans per series | 1: 1,476 names; 3: 50; 5: 3 (ECL, ELV, EMR) |

The plan was tested before it was written (`--compare --with-spans`: 0 real differences), then applied through `insert_row` (written 1,641, refused 0), then the gate was run again against the table (below). `select count(*) from bar_source_policy where primary_source = 'alpaca'` returns 56 (the alpaca-first spans); the 1,585 ibkr-first rows name alpaca as fallback, so the plan's equality "alpaca primary count equals the span count" holds for the alpaca-first rows only. No migration was needed: the CHECKs on `primary_source` and `fallback_source` were already dropped (the schema migration, 472).

Final compare against the table (12 shards, `logs/selection_gate_191-07_merged_db_state.json` plus the shard files):

| | |
|---|---|
| series compared | 1,764 (5m 1,529; 1m 233; 4h 2) |
| canonical rows / selected rows | 318,947,024 / 318,949,643 (the 2,619 extra are the raw-only rows below) |
| real (unexplained) differences | 0 |
| months, digest-mismatched | 203,898, 292 (all of them on the 57 series below) |
| refused_value_in_canonical / refused_value_selected / pending rows | 0 / 0 / 0 |
| unselected slots, NULL-volume winners | 0, 0 |
| extended-hours candidates dropped | 31,821,355 |
| explained: refused_cross_vendor | 2,895 (2,619 rows only raw holds, 276 vendor differences) |
| explained: refused_self_restatement | 6,168 |
| explained: restated_after_copy | 148 |

The 57 series carrying explained slots: ADM AEP AMT AMZN ASML BA ECL EEM EFA ELV EMR EPD EQIX ETR EWG EWJ EWT EWY EWZ EXEL EZU F FCX FDX FXE FXI GDX GE GILD GLD GOOGL GS HD HON IGV IHF ISRG ITA ITB IWM IYT IYZ JBHT JNJ JPM KO KRE LEN LLY LMT LQD MCD RLAY SHY TLT TMUS VIXY (per series counts and samples in the report).

Idempotence: `--idempotence` over 25 names that already match (13 Alpaca-canonical, 12 IBKR-canonical dominant), inside a transaction that is always rolled back: inserted 0, replaced 0, unchanged 6,163,503, unselected 0. A probe over seven of the 57 series (rolled back, nothing persisted): ADM, LMT, KRE, TMUS, ECL, RLAY, VIXY would insert 436 and replace 320 rows; that is the size of the explained residue, see Unresolved.

Row counts: `market_data_ohlcv_tradeable` 455,591,952 before and after; `market_data_ohlcv` 461,144,895 before and after (the gate and its idempotence probes never commit).

### The 12 unlocated raw rows

`--locate-unsourced` (counts in the database, 4 shards) found them: PLD 5m alpaca 2026-08-06 16:55 (1 row) and VIXY 5m alpaca 2026-09-23 18:10 and 2026-10-09 19:10 through 19:55 (11 rows). All are real Alpaca serves of the `alpaca-5m-load` (applied loads on 2026-10-10) that the retired fetcher later replaced in canonical with IBKR's row for the slot (canonical there is `ibkr_named`); the Alpaca copy existed in canonical at backfill time, so raw has it, and neither canonical nor the archive holds an Alpaca twin any more. Raw is correct and complete; nothing to repair. (Plan 04's note: immaterial against table size; now located.)

## Deviations from plan

1. [Rule 2] Files beyond the plan's list, all inside the amendments: `src/intelligence/bars/selection.py`, `services/bar_selection.py`, `services/ohlcv_ingress_contract.py`, `services/bar_load.py`, `scripts/ops/bars/ops_bar_load.py`, `scripts/ops/bars/ops_bar_nightly.py`, their tests, `tests/unit/test_bar_load_reporting.py`, the design doc (D-191-L), todo 535 (status block).
2. [Rule 1] Spans are the plan's "maximal date ranges whose canonical vendor differs" refined to the fewest runs that reproduce canonical, because a date-granular policy cannot express a day on which canonical switches vendor; the derivation tries four rankings and takes the least surprising one that is exact, then the one with the fewest explained changes.
3. [Rule 1] The plan's done criterion `--add ... --evidence '{}'` cannot print a would-write line: the standing rule (185-37) refuses an empty evidence object. Verified with a non-empty object instead (test and CLI path); the rule was not weakened.
4. The plan's `refused_self_restatement` class was kept as named; two classes were added (`restated_after_copy`, `refused_cross_vendor`) because the real data holds three distinct causes, each with its own ledger evidence. Per amendment 2026-10-13 the pending-hold class counts zero; it does, and the gate shows it as the `refused_value_*` lines.
5. Task 3 was not run (orchestrator constraint). The plan's truths "the fetcher resumes only after the gate is clean" and "its first runs write raw" are therefore still owed to the plan that clears plans 08 and 10. `ops_bar_nightly` and `ops_bar_load` were not run against live data.
6. `/simplify` and `/review` are not invocable from this executor; the diff was reviewed by hand (first trial of the session rule against canonical found the vendor-blind filter wrong and the first emit found the single-vendor tail, both fixed before anything was written).

## Unresolved

1. The 9,211 explained slots are not equal; they are recorded. If the selection writer runs over them it changes canonical: raw current holds a different value than canonical on 6,168 slots (the later IBKR serve the retired path refused and canonical never took) and 148 (canonical restated after the copy, raw stale); 276 slots have canonical Alpaca where IBKR raw also holds the slot on a day when canonical switches vendor (a date-granular span cannot reproduce that); 2,619 IBKR raw rows have no canonical row (a refused chunk's new slots). Probe: 436 inserts and 320 replacements over seven series, rolled back. Nothing runs the writer over them while the fetcher is held, but plans 08 and 10 must not resume it first. Recommended, in order: (a) refresh raw for the 148 stale keys from canonical (their displaced values are already revisions); (b) for the 6,168, put raw back to the canonical (accepted) value and hold the later serve as a `pending` revision under a refused load (the D-191-I form); (c) then accept the 2,619 additions and 276 vendor differences as the one-time catch-up of selection or hold them with explicit decisions. This is a raw write (plan 04's domain), not done here.
2. Forward tails mean any future Alpaca-only slot of a name is selected; a name onboarded after today has no span and its first Alpaca load reports `UNSELECTED` (loud by design). Onboarding must add the span through `ops_source_policy.py` (or the SOP step that calls it).
3. Todo 535 item 3 (reconstructed revision loads carry reconstruction time) is untouched; the gate's evidence reads revision values and keys, never `loaded_at`.

## Known stubs

None.

## Self-Check: PASSED

`scripts/ops/bars/ops_selection_gate.py`, `tests/unit/scripts/test_ops_selection_gate.py` and this file exist; commits b2ffcaec4, 12b80c126, 349cdc825, f035d3bed, 49d21f9a5, 5f759b70e are in `git log`; `logs/selection_gate_191-07_*.json` hold the reports; `bar_source_policy` holds 1,641 5m symbol rows; the ten units show `cleared_by=None` and none is active. Verification: touched-area suites (selection, gate, policy writer, loader reporting, ingress contract, boundary and single-writer registry) pass; full `tests/unit` passes (two pre-existing skips); `tests/integration/test_ingress_write_contract.py` and `test_ohlcv_coverage_atomic_write.py` pass (one skip: no compressible chunk on the test database). No file under `src/intelligence/research` or `statistics` changed, so `repro_frozen` was not required.
