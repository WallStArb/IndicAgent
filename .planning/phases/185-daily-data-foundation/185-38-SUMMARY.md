---
phase: 185-daily-data-foundation
plan: 38
subsystem: bars / the d2-v2 cutover (one 1d writer, lineage on read, every name re-derived)
tags: [D-06, D-07, D-12, d2-v2, bar_source_policy, lineage-view, cutover, migration-447, migration-454, gap_closure]
requires: [185-36]
provides:
  - "canonical_bar_lineage is a view derived on read (migration 447, live); the 7,010,160-row table is dumped to data/backups/185-38/"
  - "market_data_ohlcv_tradeable filters on the quarantine flag only (todo 500)"
  - "every 1d bar re-derived under d2-v2 by the single 1d writer; every 1d month digest at d2-v2"
  - "Tradier admitted as primary only on evidence: 74 IBKR-primary exception rows, the policy CLI ops_source_policy.py"
  - "d2-v2 head gate: a fallback head is admitted only within the basis tolerance"
  - "the Tradier loader writes D1 and ohlcv_load only and chains the daily stage"
  - "the daily stage's --restore-snapshot and --rewrite-digests paths"
  - "ohlcv_observation VACUUM FULLed: 6.80 GiB to 3.41 GiB"
affects: [185-33, 185-37, 185-41, 185-42, 185-43, 189-10]
tech-stack:
  added: []
  patterns: ["source admission on cross-vendor evidence before any apply", "a one-off per-name review gate the first-load waiver cannot bypass", "lineage as a view over stored values: it cannot point at values the table no longer holds"]
key-files:
  created:
    - production/migrations/447_canonical_bar_lineage_view.sql
    - production/migrations/454_cutover_admission_apr.sql
    - src/intelligence/bars/source_admission.py
    - scripts/ops/bars/ops_source_policy.py
    - scripts/ops/bars/ops_cutover_review.py
    - tests/unit/bars/test_source_admission.py
    - tests/unit/scripts/test_ops_source_policy.py
    - tests/unit/scripts/test_ops_cutover_review.py
    - tests/unit/scripts/test_tradier_daily_run.py
    - tests/unit/test_cutover_admission_apr_migration_contract.py
    - tests/unit/test_canonical_bar_lineage_view_migration_contract.py
    - tests/unit/test_tradeable_view_quarantine_only_contract.py
  modified:
    - src/intelligence/bars/daily_rule.py
    - services/bar_derivation.py
    - scripts/infrastructure/backfill/infrastructure_run_tradier_daily.py
    - scripts/ops/bars/ops_real_rows_swap.py
    - tests/unit/bars/test_daily_rule.py
    - tests/unit/services/test_bar_derivation_daily.py
    - tests/unit/scripts/test_tradier_daily_plan.py
    - tests/unit/scripts/test_data_bar_check.py
    - tests/unit/test_market_data_ohlcv_writer_boundary.py
    - tests/unit/test_market_data_ohlcv_boundary.py
    - tests/unit/test_canonical_lineage_digest_writer_boundary.py
    - tests/unit/test_ohlcv_load_revision_writer_boundary.py
    - tests/unit/test_single_writer_registry.py
    - tests/unit/test_table_and_apr_key_readers.py
    - docs/foundation/canonical-truth-registry.md
    - docs/operations/operations-database.md
  deleted:
    - scripts/ops/bars/ops_tradier_lineage_backfill.py
    - tests/unit/scripts/test_ops_tradier_lineage_backfill.py
    - tests/unit/scripts/test_tradier_daily_lineage.py
decisions:
  - "Exception rows are primary ibkr with no fallback (the plan said fallback tradier, which d2-v2 refuses, and a Tradier fill would put the rejected series back into the holes)"
  - "A Tradier incumbent with fewer than min_overlap common sessions keeps Tradier with no row (keep_no_overlap): no evidence either way; 475 names, most with no IBKR SMART 1d answer in D1"
  - "Orchestrator decision at the review gate: removed and value-changed shares gate; refused-interior and refused-head shares are reported for names that remove nothing stored (SIL, BNO); thresholds unchanged"
  - "Orchestrator decision: BRBR and SEZL get IBKR-primary rows (admitted, but their IBKR history would otherwise be removed); VMRK's row closed and routed to 185-37 (dividend-basis question)"
  - "todo 500's ten confirmed_corrupt keys without a quarantine flag are the ten clean Tradier bars; they are not quarantined, the predicate is dropped and they are visible"
  - "The lineage view ranks LEGACY_IMPORT below SMART for IBKR bars, as d2-v2 does"
  - "A snapshot restore waives the next daily re-derivation; only the daily stage's own loads are the waiver baseline"
  - "TRADIER_OWNED_SQL lives in services/bar_derivation.py (the loader re-exports it) and reads the open 1d policy row plus a Tradier observation"
metrics:
  duration: 2h10m
  completed: 2026-10-07
  tasks: 4
  files: 37
---

# Phase 185 plan 38: the d2-v2 cutover Summary

Every 1d bar is now derived by one writer under d2-v2. Tradier is primary only where its closes agree with IBKR, lineage is a view that cannot drift from the values, and the pre-cutover state can be restored per symbol from a tested snapshot until 185-43 deletes it. After the apply the recompute of all 1,502 names equals the stored bars (0 new, changed or removed), 0 visible bars lack lineage, and every 1d month digest is at d2-v2.

## Commits

| Task | Commit | What |
|---|---|---|
| 0 RED | d71089e43 | admission, head gate, CLI, review, migration 454 tests |
| 0 GREEN | 9c030bfce | migration 454 (applied), head gate, source_admission.py, ops_source_policy.py, ops_cutover_review.py, refused_head column |
| 0 fix | 29887882b | incumbents without enough IBKR overlap keep Tradier (Rule 1) |
| 0 fix | 3941a3535 | boundary allow-list and real-rows verdict for the sweep's incumbent probe (Rule 3) |
| 2 RED | 694a7fd8c | 447 contract, quarantine-only tradeable view, digest rewrite, restore tests |
| 2 GREEN | cb1914d7c | migration 447, --rewrite-digests, --restore-snapshot |
| 0 gate RED | 5de9a3fac | review gated on stored data lost or altered; sweep never rewrites a decided name |
| 0 gate GREEN | 4e93b0dd6 | the same (orchestrator decision) |
| 1 RED | 77b90308e | raw-only loader tests |
| 1 GREEN | fa1550f85 | loader writes D1 and ohlcv_load only and chains the daily stage; boundaries |
| 3 RED | 24b92d479 | restore waives the next re-derivation |
| 3 fix | cbfe63289 | the same (Rule 1, found in the canary restore proof) |

Tasks ran in the order 0, 2, 1, 3. Task 1 was held until the review gate passed: a committed raw-only loader would have chained an apply into the lineage guard if the Tradier timer had been restarted before the cutover.

## Task 0: source admission, head gate, policy CLI, review gate

### Migration 454
`ls production/migrations` before applying showed 446, 453 and nothing else in 447 to 454. Applied with `psql -f` under `lock_timeout 10s` at about 10:59 UTC: four keys (`tradier_admission_min_overlap_sessions` 60, `tradier_admission_min_agree_share` 0.9, `cutover_max_removed_share` 0.005, `cutover_max_refused_share` 0.005), all `[initial_estimate]`, not ML targets, one `migration_454` history row each.

### Head gate
d2-v2 admits a fallback head only when its seam is within `fallback_basis_tolerance_bp`. The seam is the median IBKR/Tradier close ratio over the first `fallback_basis_window_sessions` common sessions from Tradier's head, and having no common session refuses the head. A refused head date has no bar and is listed in `DailyV2Result.refused_head` and in the TSV's new `refused_head` column. DAL's seam measures 0.0 bp, so its five heads stay admitted. The 185-36 seam test used an 80 bp seam; it now uses 8 bp.

### todo 500 check (read-only, before the sweep)
`price_sanity_status = 'confirmed_corrupt'` with no quarantine flag on the same key: **10**. They are exactly todo 500's ten clean Tradier bars: DBC 2007-08-17, FXI 2007-02-27, FXY 2008-09-24, GLD 2007-09-10, IWM 2007-08-08, RSP 2007-08-01, SPY 2007-04-02, VWO 2007-05-02 and 2007-12-28, XRT 2007-09-18. Each is continuous with its neighbors (FXI's -9.9% is the 2007-02-27 Shanghai drop). Every other confirmed_corrupt row (5 on 1d, 20 on 5m) carries a quarantine flag. No flag was written (deviation 3).

### Admission sweep (`logs/185-38_admission_sweep.tsv`, 1,502 rows, 48 s)

| Action | Names | Row |
|---|---|---|
| admit (Tradier agrees) | 841 | none |
| write (IBKR-primary exception) | 73 | written |
| route_185_37 (incumbent, fails only over history) | 113 | none |
| keep_no_overlap (incumbent, under 60 common sessions) | 475 | none |

Exception rows written by the sweep (`--apply`, 0 refused), primary ibkr, no fallback, open-ended from the name's first observation, evidence = the sweep's numbers:

- IBKR-only, no common session (5): CART, CC, CUBE, FLUT, LEA
- IBKR-only, fewer than 60 common sessions (22): AAOI, AVTR, CFR, CNH, DKNG, EU, FLNG, FROG, G, LGND, NE, RNG, S, SAIC, SARO, SITM, SN, SNEX, TGTX, TRU, TW, VSEC
- IBKR-only, agree share under 0.9 (45): AIG, ARGT, ASML, AUGO, CBC, COR, CTVA, ELS, FBIZ, FTV, FUBO, GRBK, GYRE, HLT, HPE, HPQ, HWM, IP, IPO, KDP, LION, MSI, MTCH, NEXN, NOC, PATK, POST, RCAT, REX, RGEN, RSG, RSPF, SAFE, STE, TMUS, TPL, UAMY, VATE, W, WEX, WSBF, XAR, XHS, XLY, XSW
- Tradier incumbent failing on the recent window too (1): VMRK, later closed (see the review gate)

Routed to 185-37 with no row (113): A, AAON, ABT, ADP, APH, APO, ATRO, BAX, BDX, BF.B, BH, BHP, BIL, BNO, BNTX, BNY, BWX, BX, BZH, CAH, CBRE, CENT, CF, CHD, CMG, COP, COPX, CPAY, CPRT, CUBI, CXW, DHC, DNTH, DOV, DRI, DXCM, EBAY, EQT, EWI, EWJ, EWM, EWS, EWT, EWU, EXPE, FLO, FTI, FTNT, GDXJ, GL, GLNG, GOOGL, HON, HSIC, HST, IBB, IBM, ICLN, IJR, IRM, JCI, KIE, KMB, LEN, LHX, LXP, MAS, MGM, MSTR, NFLX, NI, NVDA, O, OKE, ONIT, ORLY, OXY, PAR, PARR, PFE, PPL, RJF, ROST, RTX, SIL, SPG, SSP, THC, TSCO, TSLA, TSM, TT, UDR, UNG, URA, VCIT, VCLT, VCSH, VLO, VTR, VZ, WBD, WELL, WY, XBI, XHE, XLF, XPH, XRT, XSD, XTN, YUM, and VMRK after its close. The 475 keep_no_overlap names are in the sweep TSV (action column).

### Review gate
The first review on the after-admission dry run failed on four names: BRBR (removed 0.340, refused_head 1.0), SEZL (removed and refused_interior 0.0996), SIL (refused_head 1.0, nothing removed) and BNO (refused_interior 0.0069, nothing removed). I stopped and reported. The orchestrator decided:

1. BRBR and SEZL: IBKR-primary rows through `--add`, with the admission and removal evidence. Under the Tradier default, d2-v2 would remove 594 and 78 stored IBKR bars respectively; IBKR agrees with Tradier on their common sessions, so one IBKR source loses nothing.
2. VMRK: its row closed through `--close` and routed to 185-37. Its disagreement is a dividend-adjustment basis: median ratio 1.062, and the vendors are equal from 2026-08-24. Flipping a Tradier incumbent on a basis disagreement would drop 1,701 pre-2006 bars that IBKR never answered. The table forbids `valid_to = valid_from`, so the closed row still covers 2000-01-03. VMRK's 2000-01-03 bar was therefore removed by the apply; its old values are in ohlcv_revision, and 185-37 can restore it.
3. Review rule (orchestrator decision, recorded here): the gate is the removed share and the value-changed share (changed minus source-only) on a Tradier or mixed series. Refused-interior and refused-head shares are reported as informational. An IBKR-only name moving to Tradier is not gated on changes, because the admission sweep's evidence is the review of that switch. The thresholds were not changed. A sweep now never rewrites a name that already has a symbol row, open or closed.

Open IBKR-primary symbol rows: **74** (73 from the sweep, minus VMRK, plus BRBR and SEZL).

The rerun dry run (`logs/185-38_d2v2_dryrun_after_admission.tsv`) showed:
- 0 new, changed and removed bars on all 74 exception names (REX, W, CTVA, WEX, RGEN, MTCH, XLY, CART, BRBR, SEZL among them);
- refused heads only on SIL (276), with nothing stored removed.

The review exited 0, with BNO and SIL reported as informational.

## Task 2: lineage view, todo 500, restore path

- Migration 447 drops the table and creates the view. It reuses the old column names. Each bar resolves to the latest non-test TRADES observation of its source route with equal OHLCV (`IS NOT DISTINCT FROM`). Routes: tradier reads TRADIER; ibkr_named and ibkr_fallback read SMART, then LEGACY_IMPORT. Any other source gets NULL. rule_version, batch_id and derived_at come from the bar's month digest. SELECT is granted to bar_derivation_writer, the only role that read the table. No index was added; `idx_ohlcv_observation_symbol_date` is used (EXPLAIN below).
- The tradeable view drops `price_sanity_status IS DISTINCT FROM 'confirmed_corrupt'`; the quarantine flag is the one visibility rule.
- `--rewrite-digests` writes a month when its content or its rule version differs.
- `--restore-snapshot <gz csv> --symbols X --apply` rewrites the symbols through the write contract. Each symbol gets one load row, caller `bar_derivation-restore`, waiver `restore`. Every stored key is in the removal scope. The run then scrubs and digests. Flags are left as they are; a following re-derivation rewrites the stage's own.

## Task 1: one 1d writer

- The loader lands D1 only (185-27 elision) and writes one `ohlcv_load` row per load (destination `d1`).
- Deleted: canonical upsert, lineage upsert and unmatched check, `LineageGapError`, the scrub and digest step, `--raw-only`, the tradier stage batch, and the short_history refusal.
- Refusal is now on the raw record: an answer revising more than `threshold.bar_integrity.max_revision_ratio` of the latest Tradier observations lands nothing (outcome `gated`, request row only). Exceptions are `--rebase`, or a back-adjusted split, whose corporate_action row is written in the load row's transaction under bar_derivation_writer.
- A short answer lands, with `short_history` in its detail.
- After the loop, one `services.bar_derivation --stage daily --symbols <changed> --apply` subprocess runs; a non-zero exit fails the run. fetch_complete is marked after it.
- `TRADIER_OWNED_SQL` is the policy predicate: the open 1d policy row names Tradier, and a TRADIER observation exists. The fetcher's `tradier_owned` probe column keeps its name and now reads it. The nightly selects 1,455 names, and the missing-name query finds 27.
- Boundaries:
  - the loader is off the market_data_ohlcv writer and read allow-lists;
  - every other writer references `DERIVATION_OWNED_TIMEFRAMES` or carries a fence exemption with its reason;
  - canonical_bar_lineage has no writer (INSERT, UPDATE, DELETE and COPY all fail the scan);
  - the loader is off the ohlcv_revision list;
  - `infra.tradier.max_changed_bar_ratio` is in `_PENDING_RETIREMENT` (retire: 185-43).
- `grep -c "INSERT INTO market_data_ohlcv\|canonical_bar_lineage"` on the loader prints 0. `scripts/ops/bars/ops_tradier_lineage_backfill.py` no longer exists.

## Task 3: live cutover (all times UTC, 2026-10-07)

Preconditions: Tasks 0 to 2 committed and the review passing. The Tradier timer and service, and the fetcher service and timer, were inactive (the fetcher is also disabled). The run fell inside the allowed window. Free disk was 571 GB against ohlcv_observation's 6.96 GB total. No other session was active on the tables.

1. **Timer:** `indicagent-tradier-daily.timer` was inactive throughout (stopped by the orchestrator).
2. **Dump and snapshot** (11:28):
   - `data/backups/185-38/canonical_bar_lineage_2026-10-07.dump`: 22.7 MB, 3.4 s. `pg_restore -l` lists the table, its data, pk, FK and ACL. The data section holds **7,010,160** rows, equal to the live count at that moment.
   - `data/backups/185-38/market_data_ohlcv_1d_pre_d2v2.csv.gz`: 125 MB, **7,010,186** rows plus a header, equal to the live 1d count.
   - `bar_quality_flag_1d_pre_d2v2.csv.gz`: 22,425 rows, kept as evidence.
   - A restore dry run of SPY, W and XLY from the snapshot classified 14,338 unchanged, 0 changed: the CSV round-trips exactly.
3. **Migration 447** applied at 11:28:53 under `lock_timeout 30s`; relkind is now `v`. View cost:
   - `SELECT count(*) ... WHERE symbol = 'SPY'`: 97.7 ms, using idx_ohlcv_observation_symbol_date. That index was also used in the earlier temp-view probe; the full plan is in the logs.
   - Full-corpus NULL request_ids over visible 1d bars: 42.4 s (`logs/185-38_lineage_view_full_explain.txt`). This is far under the 10-minute bound, so 185-33's lineage_missing check can read the view.
   - Pre-apply count: 0 visible NULLs, and 1 NULL among all 7.01M rows (INDA 2012-08-03, hidden by volume 0).
4. **Before the canary:**
   - The ten todo 500 bars are visible in market_data_ohlcv_tradeable (10 of 10).
   - D-28 (`python -m scripts.ops.bars.ops_data_bar_check`): 6/7 pass. Condition 1's evidence line still prints "replaced bars hidden by a stale price_sanity_status 10", because that count reads the column, not the view.
   - Condition 3 FAILs on FUBO, LION and RCAT: unresolved IBKR late names, now IBKR-primary exception names. The same check lists 23 Tradier-owned names it excludes.
   - Pre-canary dry run `logs/185-38_d2v2_dryrun_precanary.tsv`: identical to the after-admission run. Review exit 0.
5. **Canary** (11:34, 3.1 s wall, scrub and digests included): SPY, RJF, REX, DAL, INDA, ETHA, XLY, W, AA, SD, HON, XHE. Coverage:
   - SPY, RJF and ETHA are Tradier-only;
   - XLY, W and REX are exception names;
   - AA and SD are IBKR-only names admitted to Tradier;
   - DAL, INDA, HON and XHE are mixed.

   Checks:
   - every ohlcv_load and revision count equals the pre-canary dry run (0 differences across 12 names);
   - 0 NULL lineage over 52,976 visible bars;
   - the re-run dry run shows 0 new, changed and removed;
   - digests are current (0 content changes).

   The write rate (about 7,300 bar writes in 2.3 s of batch time) needed no decompress fallback, so no VACUUM of market_data_ohlcv was required.

   **Restore proof:** SPY, HON and AA were restored from the snapshot.
   - The restore wrote AA 2,501 changed and 2 removed, and HON 2 new.
   - The restored rows equal the snapshot exactly (15,961 of 15,961).
   - The re-derivation reapplied HON's 2 removals and AA's 2,501 changes and 2 new bars; a dry run afterwards showed 0 changes.

   The old waiver would have refused AA's re-derivation: its query returned false, because the restore load counted as the last daily load. This was fixed first (cbfe63289).
6. **Full apply** (11:35:39 to 11:39:47, 4 min 8 s): 1,502 names derived, 0 refused, 0 failed. 150 names breached the revision ratio, all waived as the first apply; the review gate was the control.

   Cutover totals (canary plus full run; the restore/re-derive cycle excluded), by group before the run:

   | Group | Names | Stored | Canonical | New | Changed (source only) | Unchanged | Removed | Head | Refused head | Admitted interior | Refused interior |
   |---|---|---|---|---|---|---|---|---|---|---|---|
   | Tradier only | 1,006 | 4,939,968 | 4,944,427 | 4,459 | 0 (0) | 4,939,968 | 0 | 4,407 | 276 | 52 | 32 |
   | Mixed | 260 | 1,333,950 | 1,333,921 | 0 | 793 (792) | 1,333,128 | 29 | 35 | 0 | 758 | 28 |
   | IBKR only, admitted | 162 | 560,676 | 654,586 | 93,910 | 560,676 (131,581) | 0 | 0 | 114,060 | 0 | 9,473 | 0 |
   | IBKR only, exception row | 74 | 175,592 | 175,592 | 0 | 0 (0) | 175,592 | 0 | 0 | 0 | 0 | 0 |
   | Total | 1,502 | 7,010,186 | 7,108,526 | 98,369 | 561,469 (132,373) | 6,448,688 | 29 | 118,502 | 276 | 10,283 | 60 |

   Against 185-36:
   - the 74 exception names avoid 15,025 interior removals and 167,139 head relabels;
   - the 162 admitted IBKR-only names remove nothing;
   - the Tradier-only group is unchanged except SIL's 276 refused heads (nothing stored);
   - mixed is unchanged, except that VMRK's 2000-01-03 bar is the 29th removal (the dry run lists it without a refused date, because it is the closed row's one day).

   Removed bars per name: XHE 14, MUX 4, BIL 2, HON 2, EWM 1, EWS 1, EWU 1, PARR 1, WELL 1, XTN 1, VMRK 1. Refused interior per name: BNO 28, XHE 14, MUX 4, COPX 3, BIL 2, HON 2, EWM 1, EWS 1, EWU 1, PARR 1, SIL 1, WELL 1, XTN 1. Refused heads: SIL 276.

   `tests/integration/test_d2_single_writer_live.py` (read-only, live DB) has 3 failing tests: CRBG has no derived bars under its d2-v1 recompute; a 1d source outside `{ibkr_named, ibkr_venue, synthetic_fill}`; unlinked bars. All three are d2-v1 assumptions; 185-41 Task 2 rewrites the test, and red is expected here.

   5b. **Digest rewrite** (11:39:56, 37 s): 316,179 month digests written at d2-v2. `bar_content_digest_current` for 1d: d2-v2 344,424, no other rule.
7. **Checks after the apply:**
   - visible 1d bars with NULL request_ids: **0**; all lineage rows NULL: 0; rows not d2-v2: 0, of 7,108,526;
   - full dry run (`logs/185-38_d2v2_dryrun_post_apply.tsv`): 0 new, 0 changed, 0 removed, every name derived;
   - per-source 1d counts: tradier 6,804,149, ibkr_named 175,592, ibkr_fallback 128,785; other sources 0.
8. **Loader by hand** (`systemctl start indicagent-tradier-daily.service`, 11:50:53, **128 s**):
   - loaded 1,455 names, destination d1, 324 new and 8 changed D1 bars;
   - the chained daily stage ran over 166 names, exit 0 (316 new, 16 changed, 0 removed, 0 refused);
   - no canonical row was written by the loader;
   - 0 visible NULL lineage and 0 non-d2-v2 digests after it.

   128 s is far under TimeoutStartSec=3600, so the unit file is unchanged.
9. **VACUUM FULL** (11:54:06). Before running:
   - no session was active on ohlcv_observation and no lock was held;
   - estimated reclaim: 15.85M live rows at about 95 bytes average width plus 28 bytes overhead is about 1.95 GB of heap against 3.63 GB, plus index bloat.

   `SET lock_timeout = '30s'; VACUUM FULL ohlcv_observation; ANALYZE` ran in 15.5 s, which is the time the exclusive lock was held.

   | | Heap | Indexes | Total |
   |---|---|---|---|
   | Before | 3,628,777,472 | 3,670,605,824 | 7,300,415,488 (6.80 GiB) |
   | After | 2,155,339,776 | 1,505,689,600 | 3,661,037,568 (3.41 GiB) |

   Reclaimed 3,639,377,920 bytes (3.39 GiB); the row count is unchanged at 15,848,895.
10. **Timer:** not started. The orchestrator restarts `indicagent-tradier-daily.timer` (its decision for this run; plan step 9 named this executor).

## Verification

- Touched-area tests, the boundary family and the three 185-44 guards pass. The guards are test_single_writer_registry, test_table_and_apr_key_readers and test_temporary_allow_list_expiry, rerun after this SUMMARY exists.
- Full `.venv/bin/pytest tests/unit/ -q`: exit 0. The 5 skips predate this plan.
- ruff and black are clean on every touched file. `ruff check .` reports only the pre-existing unsorted import in `tests/unit/research_tools/test_repro_frozen.py` (deferred since 185-44).
- Not run: repro_frozen, because nothing under research/ or statistics/ changed.
- Unit tests use fakes only.

## Deviations from plan

### Auto-fixed issues

1. **[Rule 1] Exception rows have no fallback.** The plan said fallback tradier, but `_check_policy` refuses (ibkr, tradier), and REX's tested row has no fallback. Commit 9c030bfce.
2. **[Rule 1] keep_no_overlap.** As written, the first sweep would have given 474 Tradier-only names IBKR rows because they had no common session. ZWS, for example, has only TRADIER observations, so the apply would have removed its whole series. An incumbent now gets a row only on a full recent window that fails. Commit 29887882b.
3. **[Rule 1] todo 500 keys not quarantined.** The plan's fallback (quarantine any confirmed_corrupt key without a flag) would have hidden the ten bars todo 500 exists to reveal. The check found exactly those ten, verified clean.
4. **[Rule 1] LEGACY_IMPORT in the lineage view**, ranked below SMART. Without it, the ibkr heads served from the stored corpus (DAL 2007) would read as lineage_missing.
5. **[Rule 3] Two files outside the plan.** ops_real_rows_swap.py gets a consumer verdict for ops_source_policy.py and drops the loader and lineage-backfill verdicts. test_data_bar_check.py's fake routes the policy-based Tradier-owned query. Commits 3941a3535 and fa1550f85.
6. **[Rule 1] The restore waives the next re-derivation.** Found in the canary restore proof: the old waiver query returned false for AA after its restore. Commit cbfe63289.
7. **[Rule 3] Surviving loader run tests moved to the new file test_tradier_daily_run.py**; test_tradier_daily_lineage.py is deleted.
8. **TRADIER_OWNED_SQL moved to services/bar_derivation.py.** The probe needs it, and a service must not import a script. The loader re-exports it, so ops_data_bar_check and ops_tradier_fetch_complete_repair are unchanged.

### Orchestrator decisions (not deviations)

- The review gate's rule change, the BRBR/SEZL rows and the VMRK close are covered in the review gate section above.
- The timer is restarted by the orchestrator, not by this plan.

## Known stubs

None.

## Threat flags

None beyond the register. T-185-38-01 to 05 are mitigated as planned: no lineage writer exists (CI); dump, snapshot and a tested restore path were in place before the apply; the timer stayed stopped; VACUUM FULL ran with no writer active; tradier_owned is redefined from the policy.

## Remaining for later plans

- 185-37: the 113 routed names, VMRK (including its 2000-01-03 bar), and SIL's 276 refused heads.
- 185-41: rewrite `test_d2_single_writer_live.py`.
- 185-43: delete the dump and snapshots after 30 days (about 2026-11-06); retire `infra.tradier.max_changed_bar_ratio` (migration 452) and the two cutover keys; drop price_sanity_status.
- 185-42: delete ops_cutover_review.py.
- 189-10: replace the fetcher's tradier_owned skip with the weekly IBKR 1d reconcile. This also supplies evidence for the 475 keep_no_overlap names.
- D-28: condition 3 fails on FUBO, LION and RCAT.

## TDD gate compliance

RED before GREEN for every code change: d71089e43 then 9c030bfce; 694a7fd8c then cb1914d7c; 5de9a3fac then 4e93b0dd6; 77b90308e then fa1550f85; 24b92d479 then cbfe63289. Each RED test failed before its implementation.

## Self-Check: PASSED

- Files exist: migrations 447 and 454, source_admission.py, ops_source_policy.py, ops_cutover_review.py, the new tests, the dump and the snapshots; ops_tradier_lineage_backfill.py does not exist.
- All commits listed above resolve. The deletions in fa1550f85 are intended (the lineage backfill, its test, test_tradier_daily_lineage.py).
- Acceptance query (visible 1d bars joined to the view with NULL request_ids) prints 0. relkind is `v`. The snapshot is non-empty.
