---
phase: 185-daily-data-foundation
plan: 34
subsystem: bars / D-28 data bar gate
tags: [D-10, D-28, gap_closure, ohlcv_revision, late_names, ohlcv_venue_head, tradier]
requires: [185-28, 185-30]
provides: [source-aware D-28 conditions 1, 3 and 4, LEGACY_1D_KEYS constant, ISLAND-failed head rule behind infra.ibkr.venue_fallback.island_failed_unlisted (migration 453)]
affects: [ops_head_rerun classify_head (shared by condition 3), market_data_ohlcv boundary allow-list, ops_real_rows_swap CONSUMER_VERDICTS]
tech-stack:
  added: []
  patterns: ["a known answer is quarantined, replaced (non-IBKR stored row, IBKR ohlcv_revision row, scrub fact after the last revision) or open; judged by the stored row, not the tradeable view"]
key-files:
  created:
    - production/migrations/453_island_failed_unlisted_switch.sql
  modified:
    - scripts/ops/bars/ops_data_bar_check.py
    - scripts/ops/bars/ops_head_rerun.py
    - scripts/ops/bars/ops_real_rows_swap.py
    - tests/unit/scripts/test_data_bar_check.py
    - tests/unit/scripts/test_head_rerun.py
    - tests/unit/test_market_data_ohlcv_boundary.py
decisions:
  - "Replaced requires the 1d scrub fact to postdate every ohlcv_revision of the key (loaded_at < evaluated_at), so a bar revised after the last scrub is open until the scrub judges it."
  - "The 15 legacy keys are a module constant read from migration 381's source column (market_data_ohlcv.price_sanity_status = 'confirmed_corrupt', 15 rows on 2026-10-07)."
  - "Condition 3 counts the Tradier-owned late names it excludes and lists the ones that would be unresolved under IBKR answers; every unresolved IBKR-sourced name is listed in full, not sampled."
  - "ISLAND-failed rule: implemented with the switch seeded true. This is an orchestrator call pending owner review, not an owner decision."
metrics:
  duration: 25min
  completed: 2026-10-07
  tasks: 1
  files: 7
---

# Phase 185 plan 34: D-28 gate conditions 1, 3 and 4 made source-aware

Conditions 1 and 4 now pass on the live DB. Condition 3 still fails, on 7 IBKR-sourced late names that 185-28 left unresolved. The gate is 6/7, up from 4/7.

## D-28 gate, before and after (`.venv/bin/python -m scripts.ops.bars.ops_data_bar_check`, read-only, 2026-10-07)

| Condition | Before | After |
|---|---|---|
| scrub_pass_complete | FAIL: dry-run keys quarantined 28/72; legacy 1d keys quarantined 3 (>= 15) | PASS: dry-run keys 72: quarantined 28, replaced 44, open 0; legacy 1d keys 15: quarantined 5, replaced 10, open 0; replaced bars hidden by a stale price_sanity_status 10 |
| seam_audit_complete | PASS (0 actions) | PASS (0 actions) |
| late_name_dispositions | FAIL: 410 late names, unresolved 26 | FAIL: IBKR-sourced late names 163, unresolved 7 (BMNR, CRH, FUBO, IDR, LION, OLED, RCAT); Tradier-owned excluded 247 (unresolved under IBKR answers: ARES, CHTR, ECH, HNRG, IBP, IHF, INDA, IYZ, MARA, OCUL, ODFL) |
| no_pre_move_bars_visible | FAIL: 91,059 | PASS: IBKR-source pre-move 1d bars 0 (all 91,059 were tradier on 32 names) |
| dividend_coverage | PASS 1502/1502 | PASS 1502/1502 |
| survivorship_apr_keys | PASS 6/6 | PASS 6/6 |
| inventory_is_active | PASS 0 | PASS 0 |
| Total | 4/7, exit 1 | 6/7, exit 1 |

Condition 3 with the ISLAND switch off (computed read-only with the same code): 12 IBKR-sourced names unresolved (BMNR, CPS, CRH, FUBO, IDR, LION, OLED, QXO, RCAT, SD, SGHC, UUUU), and 14 Tradier-owned names excluded but unresolved. That matches the 185-28 residue exactly. With the switch on, 49 names are verified_empty instead of 41.

## What changed

- Condition 1. Each known-answer key gets one of three statuses:
  - quarantined: the key carries any quarantine flag. This wins over replaced, so a replaced bar that a D2a rule flags counts as quarantined.
  - replaced: three things must all hold. The stored row's source is not ibkr_named or ibkr_venue. An `ohlcv_revision` row holds an IBKR old_source for the key. The latest 1d `historical_pass_complete` fact (2026-10-03 20:59 UTC) is later than the key's last revision (the 743 Tradier loads ran 20:50 to 20:56 UTC).
  - open: anything else. A key with no revision row is open.
  The 15 legacy keys are now the constant `LEGACY_1D_KEYS`. They used to be counted from flags, and 185-30 retired 12 of those flags.
- Condition 3. Late names that are Tradier-owned (`TRADIER_OWNED_SQL`, imported) are excluded, counted and named. The condition reads the ISLAND switch and passes it to `classify_head`.
- Condition 4. `_PREMOVE_SQL` now counts only `m.source = ANY(IBKR_1D_SOURCES)`.
- ISLAND rule (`ops_head_rerun.classify_head`, keyword `island_failed_unlisted`):
  - When on, the latest ISLAND answer `failed` counts as no_data, but only on a name whose recorded primary is not Nasdaq. If no primary is recorded, the rule does not apply.
  - Only `failed` counts. Timeouts do not, and neither do other venues.
  - A missing key reads as off.
  - Migration 453 seeds the key true. It was applied live with `psql -f` after `ls` showed 446 to 453 free on disk (445 exists; 450 to 452 are reserved by 185-40, 185-43 and 189-10), and it was committed together with the code.

## Residue: the 7 unresolved IBKR-sourced late names

| Name | Why still unresolved |
|---|---|
| CRH | No SMART request window covers the head (185-28) |
| LION | SMART itself fails on the old window (185-28) |
| OLED | SMART zero-volume bars before the stored head (185-28) |
| RCAT | Same as OLED (185-28) |
| BMNR | Stays unresolved under the ISLAND rule. SMART served 4 zero-volume bars (2012-03-23 to 2012-04-11) before the stored head 2012-04-19 |
| FUBO | Same class. 263 zero-volume SMART bars (2014-10-16 to 2015-11-10) before the head 2015-11-11 |
| IDR | Same class. The 185-28 re-ask (2026-10-07) returned a SMART bar for 2011-02-23 with volume 0, the day before the head 2011-02-24. The latest SMART answer for the oldest window now starts before the head |

185-28 listed BMNR, FUBO and IDR as ISLAND-failed. That was their first blocker. Under the rule they belong with OLED and RCAT, and need the zero-volume rule that 185-33 owns. No disposition was set by hand.

## Owner-pending decision (not an owner decision)

The ISLAND-failed rule comes from an orchestrator call on 2026-10-07 and is pending owner review. Setting `infra.ibkr.venue_fallback.island_failed_unlisted` to false restores the strict 185-28 classification. Points for the review:

- The premise is "no Nasdaq listing exists to answer". Live D1 does not support it in general. ISLAND answered `bars` on 14 NYSE-primary names and `no_data` on 42, and failed on 19. A name that was once listed on Nasdaq and now has an NYSE primary would be misread as empty if ISLAND failed for it. The rule cannot detect that case from stored answers.
- The rule resolves SGHC, UUUU, CPS, QXO and SD (all IBKR-sourced), plus DAL, PARR and USL, which are already excluded as Tradier-owned. QXO was formerly SilverSun Technologies (SSNT), a Nasdaq name. Its SMART head (2017-04-19) appears to cover that listing, but this should be checked before the switch stays on.
- `reconcile_empty_history` does not apply the rule. Since 185-28 the head classification and the empty-history facts had agreed, and now they disagree for these names.

## New finding: 10 clean Tradier bars hidden by a stale `price_sanity_status`

`market_data_ohlcv_tradeable` still filters `price_sanity_status IS DISTINCT FROM 'confirmed_corrupt'`. The Tradier load replaced the 12 legacy IBKR prints but left that column set on the new rows. 185-30 retired the flags but not the column. As a result, 10 clean Tradier bars are invisible to research: DBC 2007-08-17, FXI 2007-02-27, FXY 2008-09-24, GLD 2007-09-10, IWM 2007-08-08, RSP 2007-08-01, SPY 2007-04-02, VWO 2007-05-02, VWO 2007-12-28 and XRT 2007-09-18. EFA 2008-09-29 and XRT 2008-09-19 are hidden too, but those two are quarantined by their own rules anyway.

No defect is visible because of this, so condition 1 passes and reports the count. It is still lost good data. Clearing the column, or dropping it from the view, is a canonical-table write, so it is out of this plan's scope. It needs a todo, or should go with 185-33. I did not file a todo because PRIORITIES.md is shared, so I am flagging it for the orchestrator to capture.

## Verification

- `pytest tests/unit/scripts/test_data_bar_check.py tests/unit/scripts/test_head_rerun.py`: passed. Both files use fakes only, and no test writes the live D1.
- `pytest tests/unit -k boundary`: passed.
- 185-44 guards (`test_single_writer_registry`, `test_table_and_apr_key_readers`, `test_temporary_allow_list_expiry`), plus `test_migration_number_uniqueness` and `test_ohlcv_load_revision_writer_boundary`: passed. The new APR key has a reader in `ops_head_rerun._load_apr`, so no `retire:` entry is needed.
- ruff and black are clean on the touched files.
- Full `pytest tests/unit/ -q`: exit 0. The first run failed on `test_ops_real_rows_swap::test_every_allow_listed_reader_has_a_verdict` (see deviation 2). The run after the fix was clean. The project config prints no count line.
- Acceptance: `scrub_pass_complete` and `no_pre_move_bars_visible` both print PASS (met). The one FAIL line names only residue that 185-28 recorded (met).
- Not run: `repro_frozen`, because nothing under `src/intelligence/research/` or `statistics/` was touched.

## Deviations from plan

### Auto-fixed issues

**1. [Rule 1 - Bug] Replaced legacy keys read as open through the tradeable view**
- Found during: the first live run after GREEN, which showed legacy replaced 0 and open 10.
- Issue: the stored source was read from `market_data_ohlcv_tradeable`, and that view hides the 10 replaced bars by their stale `price_sanity_status`.
- Fix: the known-answer query left-joins the raw row (source and stale status) for the 87 fixed keys and counts the replaced bars that are hidden as evidence. The script gained a `test_market_data_ohlcv_boundary` allow-list entry with its reason.
- Commits: 3b1bae8e0 (RED), 8bcab0b6a.

**2. [Rule 3 - Blocking] Real-rows swap verdict for the new raw reader**
- `test_ops_real_rows_swap` requires one `CONSUMER_VERDICTS` entry per allow-listed raw reader. Added a REAL_ROWS verdict to `scripts/ops/bars/ops_real_rows_swap.py`, a file outside the plan's list.
- Commit: 2725b0541.

**3. [Orchestrator scope] The ISLAND-failed head rule, migration 453 and the `ops_head_rerun.py` edit**
- Not in the plan's files list. Added by the orchestrator's instructions, with failing tests first (413aaef4d) and a minimal edit to `classify_head` (7709d5128).

### Plan expectations that differed from the data

- The plan expected condition 3 to be resolved for the IBKR-sourced names. Condition 3 still fails on 7 names (see residue).
- The plan expected the 185-28 ISLAND names to resolve under the rule. 5 of the 8 did. BMNR, FUBO and IDR moved to the zero-volume class.
- The plan said the legacy count follows the same rule. It does, but 10 of the 15 replaced bars are hidden by the stale column (see the new finding).

## Known stubs

None.

## Threat flags

None beyond the plan's threat model. The new raw read is a fixed set of 87 keys in a read-only script. T-185-34-01 is mitigated: replaced needs a revision row, no quarantine flag and a later scrub. T-185-34-02 is mitigated: condition 3's pass rule is unchanged, every unresolved IBKR name is listed, and the scope cut is reported on the evidence line.

## TDD gate compliance

- RED 413aaef4d, then GREEN 7709d5128 (ISLAND rule) and a6f192be0 (conditions 1, 3 and 4).
- RED 3b1bae8e0, then GREEN 8bcab0b6a (stored-row read).

## Commits

- 413aaef4d test(185-34): failing tests for source-aware D-28 conditions 1, 3, 4 and the ISLAND-failed head rule
- 7709d5128 feat(185-34): ISLAND-failed head rule behind APR switch (migration 453, applied live)
- a6f192be0 feat(185-34): source-aware D-28 conditions 1, 3 and 4
- 3b1bae8e0 test(185-34): failing tests for replaced known answers the tradeable view hides by a stale price_sanity_status
- 8bcab0b6a fix(185-34): judge known answers by the stored row; report replaced bars hidden by a stale price_sanity_status
- 2725b0541 fix(185-34): real-rows swap verdict for the D-28 gate's raw known-answer read

## Self-Check: PASSED

The migration, the SUMMARY and every modified file exist; all six commits resolve with `git cat-file -e`; the live gate output above is from the final code.
