# Plan 191-17 Summary: close (gates, drop the old canonical, delete one-shots, retire keys, docs)

Status: complete
Date: 2026-10-22 (gates and drop evidence 2026-10-18)
Author: gsd executor session (plan 191-17)

## Task 1: the close gates and the drop

Timing: the plan 14 swap completed 2026-10-17T00:25:12Z; the qualifying nightly is the
2026-10-18 06:00 UTC run (audit 06:12:04Z, grid done 06:21:55Z, 1,529 symbols, 0 refused /
0 failed, 1,811 new, 2,348 changed). More than 24 hours and four further nightly cycles
separated it from the drop. The IBKR gateway has been 2FA-wedged since 2026-10-18 23:59Z
(awaiting the owner's phone approval), so fetcher freshness after 2026-10-17 close is stalled
for reasons outside this plan; nothing here chases it.

Gate results, all five plan conditions:

1. R6 `ops_capture_completeness --gate`: exit 0, unexplained 0 in every (source, timeframe)
   group (2026-10-18 run).
2. D7, 2026-10-18 06:00Z versus the pre-phase baseline (2026-10-15 23:04Z). Same known
   failures or better on every condition; every changed condition:
   - freshness_1d 851 -> 8 (IBKR 1d deepening + nightly filled the gaps)
   - session_coverage 400 -> 181, slot_coverage 0/1529 -> 45 passing names
   - unexplained_seam 4 -> 3 names (CCI, GLIBA, TMUS cleared; CZR, EIDO new one-bar singles;
     BMBL unchanged)
   - canonical_recompute 4 -> 9 names (AVA 2768, GYRE 250, IDA 51 cleared; CTVA ~unchanged
     1858 -> 1860, held name; new singles CARG 2, CLH 2, CPRT 3, CYRX 2, CDE 53, CRUS 74,
     URA 8 and FLUT 649, all from deepening re-serves)
   - lineage_missing 2 -> 4 names but fewer bars (1,978 -> 1,854): GYRE 130 cleared, CTVA
     1848 unchanged, new CDE 1, CRUS 1 (the documented off-by-one re-serve churn class) and
     URA 4 (plan 16's explicit parity run)
   - vendor_basis_run 16 -> 20 names (AVA cleared; EMR, OII, PEN, RYN, SO newly without a
     14-day basis run; every value 1)
   - grid_parity 1693 -> 1683 of 3058 (unchanged class: the weekly parity lane, see the
     rider below)
   - coverage_cache (656) and digest_full_sweep are gone as conditions (retired with the
     plan 16 drops)
   - digest_fresh, policy_conformance, refused_head_1d, report_age, stray_vendor_rows,
     held_1d: unchanged.
3. Selection gate `ops_selection_gate --compare --timeframes 1m 5m 4h`: the first full run
   (started 06:28:07Z) reported 0 real differences, 1762/1762 series clean, but exit 3
   (EXIT_RESIDUE): five unreviewed basis-change restatement flags, all ETHA 5m ibkr/named,
   price ratio exactly 3.000000, volume ratio 0.3333, raised 2026-10-17 23:01-23:07Z when
   the deep 5m backfill re-served ETHA on its post-split scale. The split is independently
   recorded: ETHA 1-for-3 reverse split effective 2026-10-06, corporate_action row
   ce003ee6 (operator-verified 2026-10-08, Nasdaq ECA2026-713). The five flags were marked
   reviewed with that citation (`ops_restatement_review --mark ... --apply`); the re-run
   (started 07:43:09Z) exited 0: 0 real differences, 1762/1762 clean, 0 unreviewed flags
   (`logs/selection_gate_20261018T074309Z.json`). This is the first basis-flag review since
   the queue landed; the gate did exactly what it is designed to do.
4. `git diff` under src/intelligence/research|statistics since before plan 01: empty; and
   `repro_frozen` was run once regardless: BIT-IDENTICAL for phase 179 S3 and phase 181
   S2/S3 (scratch `/tmp/repro_frozen_191_17`, exit 0).
5. lineage_missing: see the D7 row above; same known failures in substance.

Drop: migration 501 applied live 2026-10-22 (`psql -v ON_ERROR_STOP=1 -f`), one transaction,
lock_timeout 30s, pg_depend guard (only the table family passes; inbound FKs or views abort),
remove_compression_policy then a plain `DROP TABLE market_data_ohlcv_old` (deliberately no IF
EXISTS: a rerun fails loudly). 461,198,119 rows, 15.7 GB hypertable. `to_regclass` empty after.
Bare `VACUUM market_data_ohlcv;` then. Disk 246G -> 230G used (16 GB freed). No reader existed
(any query naming the table: zero rows in pg_stat_activity).

## Task 2: deletions, retirement, docs

- Deleted `scripts/ops/bars/ops_canonical_vendor_kind_swap.py`,
  `ops_d2_raw_equivalence.py`, and `ops_legacy_restamp.py` (see deviation 1) with their
  tests (`tests/unit/scripts/test_canonical_vendor_kind_swap.py`,
  `test_ops_d2_raw_equivalence.py`; the restamp script had no test).
- Guard edits: boundary and no-synthetic-fill allow-list rows removed for both swap-era
  scripts; single-writer registry lost the restamp TEMPORARY writer and the
  `market_data_ohlcv_old: ()` entry; `_REUSED_BY_191_14` exemption spent (the name is dead
  again once 501 parses); vendor-kind contract test flipped to `market_data_ohlcv_old not in
  tables`; `_PENDING_RETIREMENT` now holds only `infra.old_store_backup.disk_margin`
  (retire: 191-18).
- Migration 502 retired the five `infra.canonical_swap.*` keys (disk_margin,
  statement_timeout_s, copy_statement_timeout_s, lock_timeout_s, stats_flush_wait_s):
  history then state then schema, 5 rows each, zero remaining in config_state.
  `infra.raw_backfill.statement_timeout_s` was already retired by 499.
- Docs: CLAUDE.md raw-capture bullet rewritten to the (vendor, kind) layout with the
  selection gate as the standing proof, Version 5.63.0; canonical-truth-registry rows to
  vendor/kind values; glossary `source` entry to its retired-column status; both design docs
  to landed status; gotchas gains the raw-layer section and the one-shot deletion note.
- Commit plan (each green, migrations applied in the same breath): 2f43c5435 deletions,
  fc9339e19 docs, 320339a96 migration 501, a6f7f465c migration 502, plus d3fff6dc7 (todo 539)
  and the bookkeeping commit.

## Riders

- Plan 14 P3s (rollback path test coverage, run_rollback api-state check, prove_blockers
  shape leniency, `_API_START_TIMEOUT_S` APR note): all four lived in
  ops_canonical_vendor_kind_swap.py. The script is deleted and the pre-swap copy is dropped,
  so rollback is structurally impossible and there is nothing to test or configure; grep
  confirms zero remaining references to any of the four in src/, services/, scripts/ or
  tests/. Resolved by deletion.
- Plan 16 P3-6 (confirm the week-42 parity draw executed end to end): NOT confirmed, and the
  cause is measured. Zero 15m/1h parity `ohlcv_request` rows since 2026-10-10 except plan
  16's explicit URA run, so `ohlcv_load` has no parity destination rows for week 42. The
  lane is eligible, not held: the nine week-42 names sat at queue positions 177-194 of 3025
  in the 2026-10-18T07:45Z dry run (`logs/ibkr_history_fetcher_dryrun_20261018T074520.tsv`)
  while the nightly budget went to deep 5m backfill (06:00Z run: 12 items, budget
  exhausted). Captured as todo 539 (per-run item floor or priority ranking while the
  ISO-week window is open; queue ranking only).

## Deviations

1. `ops_legacy_restamp.py` was deleted here although the plan's Task 2 named only the swap
   and d2 scripts: its single-writer entry carried `retire: 191-17`, and
   test_temporary_allow_list_expiry fails any entry whose named plan's SUMMARY exists, so
   the same-commit removal was contractually required. The script was a spent one-shot
   (applied 2026-10-15, `logs/legacy_restamp_20261015T174031Z.json`, 0 value flips).
2. The selection gate's first run exited 3, not 0; the residue was the ETHA split review
   above, resolved by the intended review mechanism, and the gate then exited 0. Recorded
   here because the plan named exit 0 without anticipating the first real basis flag.
3. Execution was interrupted (session died 2026-10-18 with nothing committed; resumed
   2026-10-22 per the coordinator's sequencing: docs and deletions committed before the
   migrations were applied). No evidence was invalidated by the gap: every gate cited above
   is from the 2026-10-18 qualifying cycle, the drop preconditions were re-verified live
   immediately before applying 501, and the disk numbers are from 2026-10-22.
4. The parity rider (above) is answered in the negative with a todo, which is a finding, not
   a plan change.

## Full unit suite

Run 2026-10-22 on the final tree (after every commit above): exit 0, zero failures, the two
known intentional skips only (test_pipeline_annotation.py confidence.py capture, and the HMM
degenerate Viterbi skip in test_causal_hmm_decoding.py).

## Corrections (2026-10-22, from the plan 17 review)

- The plan 16 P3-6 rider answer above ("NOT confirmed") is wrong, and deviation 4's "answered
  in the negative" with it. The week-42 parity draw executed end to end 2026-10-18 19:49:35Z
  to 19:52:36Z: `ohlcv_request` and `ohlcv_load` each hold the 19 rows (15m and 1h for EPD,
  FXC, ARRY, FSLR, GEV, PM, RSG, THRM, BMY plus one PM 15m retry; destination raw, applied;
  the ARRY 15m load raised a restatement flag). The starvation measured at the 07:45Z dry run
  was real but transient; the fetcher served the parity lane about 12 hours later, same day.
  DB-verified by the 191-17 review (P2-1). Todo 539 is corrected and closed on this evidence
  (`.planning/todos/completed/539-parity-lane-rank-starved-behind-deep-backfill.md`).

