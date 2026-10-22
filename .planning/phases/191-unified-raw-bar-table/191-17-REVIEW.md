# Plan 191-17 Review: close (gates, drop the old canonical, delete one-shots, retire keys, docs)

Status: complete
Date: 2026-10-22
Reviewer: fresh-context Claude reviewer (read-only; live DB read via psql)

Verdict: PASS, with one P2 finding to correct in the planning record before plan 18 closes.

## Findings

### P2-1: the plan 16 P3-6 rider is answered with a false factual premise; todo 539 inherits it

`191-17-SUMMARY.md:95-102` and `.planning/todos/pending/539-parity-lane-rank-starved-behind-deep-backfill.md`
claim: zero 15m/1h parity `ohlcv_request` rows since 2026-10-10 except plan 16's explicit URA run, no
parity destination rows in `ohlcv_load` for week 42, and therefore the week-42 draw did not execute.

The live database contradicts all three statements. All nine week-42 names (EPD, FXC, ARRY, FSLR, GEV,
PM, RSG, THRM, BMY) were fetched and applied end to end on 2026-10-18, the same day as the cited dry run:

- `ohlcv_request`: 19 rows (15m and 1h per name, plus one PM 15m retry), `requested_at`
  2026-10-18 19:49:35Z to 19:52:36Z, source ibkr, outcome bars.
- `ohlcv_load`: the same 19 rows, `destination='raw'`, `caller='ibkr-history-fetch'`, outcome applied,
  with parity-sized windows (~4-5 days of bars: 286-416 15m bars, 77-112 1h bars), not deep-backfill
  volumes. The ARRY 15m load even raised a live restatement flag (`detail`: "restatement flagged:
  changed 35 / stored 126").
- With URA (2026-10-17 06:14Z) that is exactly the 21 raw-destination 15m/1h loads since 2026-10-16.

So the rank starvation measured at the 07:45Z dry run (positions 177-194 of 3025, budget exhausted at
the 06:00Z run) was real but transient: the fetcher worked the queue down and served the parity lane
about 12 hours later, same day. The D7 grid_parity 1683/3058 number was measured at 06:12Z, before the
draw executed, so it was correct at measurement time; nothing in the gate chain or the drop decision is
affected. But the recorded answer to plan 16 P3-6 ("NOT confirmed") is wrong, and todo 539 is filed at
P2 priority on the premise that the weekly cadence "silently stops", with a fix direction ("estimate
weeks-to-execution") that follows from the false premise. The structural concern (an unbounded lane can
delay a weekly lane by many hours) survives on the corrected evidence; the todo's What/Why sections need
rewriting from "never executes" to "executed ~12h late on 2026-10-18" and its evidence line corrected.

Concrete failure scenario if uncorrected: plan 18 or the fetcher owner reads todo 539, believes week 42
never ran, and either re-triggers the draw (duplicate vendor fetches, avoidable restatement-flag noise)
or over-waits before measuring the lane again; future readers of the SUMMARY take "week 42 did not
execute" as history.

### P3-1: ETHA split effective date differs between the citation and the corporate_action row

The permanent review citation (all five `ohlcv_restatement_flag.review_note` rows) and SUMMARY line 46
say "effective 2026-10-06"; `corporate_action` row ce003ee6-e78f-47f0-98cf-5648dca9a286 records
`effective_date = 2026-10-05` (action_type reverse_split, factor 0.3333, inferred_by operator,
recorded_at 2026-10-08). Both dates may be defensible in different frames (payable date versus
first-adjusted-session date), but the citation of record should state the date the registry row carries.
One-day discrepancy in an otherwise verified chain; no decision hinged on it.

### P3-2: STATE.md completed_plans decreased while a plan completed

`.planning/STATE.md:11` went from `completed_plans: 123` to `completed_plans: 122` in the same commit
that marks plan 17 done, with no note of a recount. Presumably a correction of a prior overcount, but
the commit (855a73a28) does not say so; a future audit of the counter will see an unexplained decrease.

## Priority 1: migrations 501/502 applied live, correctness

Confirmed, no findings.

- 501 (`production/migrations/501_drop_market_data_ohlcv_old.sql`): one transaction;
  `SET LOCAL lock_timeout = '30s'`; the pg_depend guard admits exactly the table family (the table, its
  chunks via pg_inherits, constraints on the family, non-internal triggers on the family) and raises on
  any other normal dependent, with the offender named in the error. Inbound FKs and views on the table
  land outside the family and abort the migration. No CASCADE anywhere; `DROP TABLE` is deliberately
  plain so a rerun fails loudly. `remove_compression_policy(..., if_exists => true)` runs before the
  drop, with an explicit loud failure if the function is unavailable (the bgw_job is not covered by the
  pg_depend guard, which is why the explicit removal matters).
- CI VACUUM check (`tests/unit/test_compressed_hypertable_migration_vacuum_check.py`) triggers only on
  decompress_chunk plus compress_chunk in one migration; 501 contains neither, so no in-file VACUUM is
  owed. The post-apply bare `VACUUM market_data_ohlcv;` was run as a separate statement per the commit
  message (disk 246G to 230G used), which is the only form VACUUM can take anyway.
- Applied state verified live: `to_regclass('market_data_ohlcv_old')` is NULL.
- 502 (`production/migrations/502_retire_phase_191_apr_keys.sql`): three DELETEs in the order history,
  state, schema, literal five-key lists, one transaction. Verified live: 0 rows matching
  `infra.canonical_swap.%` in each of `config_history`, `config_state`, `config_schema`.
  `infra.raw_backfill.statement_timeout_s` staying out (already retired by 499) and
  `infra.old_store_backup.disk_margin` staying (reader lives until 2026-11-12, retire 191-18) are both
  correct.

## Priority 2: deletion safety

Confirmed, no findings.

- Repo-wide grep over `src/ services/ scripts/ tests/` for `market_data_ohlcv_old`,
  `ops_canonical_vendor_kind_swap`, `ops_d2_raw_equivalence`, `ops_legacy_restamp` returns five hits,
  all deliberate: the `_DROPPED_TABLES` entry in `tests/unit/test_backfill_status_retirement_migration_contract.py:27`
  (the spent `_REUSED_BY_191_14` exemption, now a must-not-exist name), the history comment in
  `tests/unit/test_table_and_apr_key_readers.py:149-151`, and the three assertions in
  `tests/unit/test_vendor_kind_swap_migration_contract.py:127,167` (127 pins historical migration 497's
  text; 167 asserts `market_data_ohlcv_old not in tables`, the new state).
- `scripts/ops/bars/` no longer contains the three scripts; `ops_selection_gate.py` and
  `ops_restatement_review.py` (both still load-bearing) remain.
- Docs mention the deleted scripts as history only (`docs/reference/gotchas.md` raw-layer section names
  them and states they were deleted at phase close), which is the allowed form.
- Rider greps: `_API_START_TIMEOUT_S`, `prove_blockers`, `run_rollback` return zero hits across
  src, services, scripts, tests. The plan 14 riders are resolved by deletion; confirmed.

## Priority 3: ETHA basis-flag review legitimacy

Confirmed with the P3-1 date nit.

- Five `ohlcv_restatement_flag` rows, all ETHA 5m ibkr/named, ratio exactly 3, flagged 2026-10-17
  23:01:42Z to 23:07:51Z (the deep 5m backfill re-serve window).
- All five reviewed 2026-10-18 07:42:54Z by "operator (plan 191-17 close session)", review_note citing
  corporate_action ce003ee6, Nasdaq ECA2026-713, operator-verified 2026-10-08; the row exists live with
  reverse_split, factor 0.3333333333333333 (1-for-3), operator, recorded 2026-10-08 21:59Z.
- Ratio 3.0 on price with ~0.3333 volume is precisely a 1-for-3 reverse split signature; the
  disposition is legitimate.
- Sequencing holds: review at 07:42:54Z precedes the clean gate re-run started 07:43:09Z.
- `logs/selection_gate_20261018T062807Z.json` (first run) shows `unreviewed_basis_flags: 5`;
  `logs/selection_gate_20261018T074309Z.json` (re-run) shows 0 real differences, 1762/1762 series
  clean, `unreviewed_basis_flags: 0`. Deviation 2's account is exactly what the logs show.

## Priority 4: CLAUDE.md and doc updates

Confirmed, no findings.

- CLAUDE.md 5.63.0 raw-capture/1d rows state the (vendor, kind) layout with `source` retired by
  migration 497 and the selection gate as standing proof; live schema agrees: `market_data_ohlcv`
  carries `vendor` and `kind`, no `source`; `ohlcv_raw` exists and is populated.
- The grid row's cited key `infra.backfill.grid_parity_sample_names_per_week` exists in `config_state`.
- Glossary `source` entry now records the retired-column status; canonical-truth-registry rows match
  the vendor/kind values; both design docs moved to landed; gotchas' new raw-layer section matches the
  live writer script names.

## Priority 5: test flips in 320339a96

Confirmed, no findings.

- `test_vendor_kind_swap_migration_contract.py:167` flipped from `in tables` to a real
  `not in tables` assertion with an explanatory comment: asserts the new state, not a deleted check.
- `test_table_and_apr_key_readers.py` removed the `market_data_ohlcv_old` pending-retirement entry in
  320339a96 and the five `infra.canonical_swap.*` entries in a6f7f465c, leaving only
  `infra.old_store_backup.disk_margin` (retire: 191-18), matching the SUMMARY.
- Boundary, no-synthetic-fill and single-writer edits are pure removals of exemptions for deleted code
  (both swap-era script allow-list rows, the restamp TEMPORARY writer with its `retire: 191-17` clause,
  the empty-writer `market_data_ohlcv_old` entry).
- Touched tests run green on the final tree: 34 passed across the seven affected files.

## Priority 6: riders and todo 539

- Plan 14 riders: resolved by deletion, grep-verified (see priority 2). Confirmed.
- Plan 16 P3-6: the rider conversion into todo 539 is where P2-1 lives. The starvation evidence at the
  07:45Z dry run is real and the file itself is well-formed (PRIORITIES row present, scope guard
  limiting the fix to queue ranking), but its premise is refuted by the DB: the week-42 draw executed
  end to end the same evening. Correct the todo's What/Why and the SUMMARY rider before plan 18.

## Deviations

1. ops_legacy_restamp.py deletion beyond the plan's named list: confirmed legitimate. Its single-writer
   entry carried `retire: 191-17`, and the expiry guard (`test_temporary_allow_list_expiry.py`,
   referenced from `test_single_writer_registry.py:17-18`) fails any TEMPORARY entry whose named plan's
   SUMMARY exists; same-commit removal was contractually required. The one-shot was spent
   (`logs/legacy_restamp_20261015T174031Z.json` exists).
2. Selection gate first run exit 3 then clean re-run: confirmed by both logs (5 unreviewed flags, then
   0 with 1762/1762 clean).
3. Session interruption and resume: process claims; nothing in the repo or DB contradicts them, commit
   timestamps are internally consistent (deletions and docs committed 19:23-19:24, migrations applied
   in the same breath), and all gate evidence is from the 2026-10-18 qualifying cycle as stated. Accepted.
4. The parity rider "answered in the negative": refuted as to the negative answer itself (P2-1); it was
   answered in the affirmative by the system, ~12 hours after the measurement.

## Evidence list

- `git diff 65f0622fd..HEAD` (six commits), each file read in the range.
- Live DB (read-only): `to_regclass('market_data_ohlcv_old')` NULL; 0 `infra.canonical_swap.%` rows in
  config_state/config_schema/config_history; `corporate_action` ce003ee6 row;
  `ohlcv_restatement_flag` ETHA rows with review records; `ohlcv_request`/`ohlcv_load` rows for the
  week-42 names (2026-10-18 19:49:35Z-19:52:36Z, destination raw, applied);
  `market_data_ohlcv` columns (vendor, kind; no source); `ohlcv_raw` present;
  `infra.backfill.grid_parity_sample_names_per_week` present.
- Files: `production/migrations/501_drop_market_data_ohlcv_old.sql`,
  `production/migrations/502_retire_phase_191_apr_keys.sql`,
  `tests/unit/test_compressed_hypertable_migration_vacuum_check.py` (guard scope),
  `tests/unit/test_backfill_status_retirement_migration_contract.py`,
  `tests/unit/test_table_and_apr_key_readers.py` (both states across 320339a96/a6f7f465c),
  `tests/unit/test_single_writer_registry.py`, `.planning/todos/pending/539-*.md`,
  `.planning/STATE.md`, `docs/reference/gotchas.md`.
- Logs: `logs/selection_gate_20261018T062807Z.json` (5 unreviewed),
  `logs/selection_gate_20261018T074309Z.json` (0 unreviewed, 1762/1762 clean),
  `logs/ibkr_history_fetcher_dryrun_20261018T074520.tsv` (exists),
  `logs/legacy_restamp_20261015T174031Z.json` (exists).
- Tests: `.venv/bin/pytest` on the seven touched files, 34 passed.
