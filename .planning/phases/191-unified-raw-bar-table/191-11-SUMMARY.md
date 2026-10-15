---
phase: 191-unified-raw-bar-table
plan: 11
subsystem: data-layer
tags: [ohlcv_raw, r6, ops-scripts, cutover-window]
requires: [191-10]
provides: [R6 over the raw plane, scripts off the two old stores, inventory for plan 16]
affects: [191-09, 191-16]
tech-stack:
  added: []
  patterns: [per-symbol counts driven from the small ledger, repeatable-read snapshot against a live writer]
key-files:
  created:
    - production/migrations/490_retire_bar_campaign_bootstrap_years_apr.sql
    - tests/unit/test_retire_bar_campaign_bootstrap_years_migration_contract.py
    - .planning/phases/191-unified-raw-bar-table/191-11-WINDOW-EVIDENCE.json
  modified:
    - scripts/ops/bars/ops_capture_completeness.py
    - scripts/ops/bars/ops_head_rerun.py
    - scripts/ops/bars/ops_source_policy.py
    - services/README.md
  deleted:
    - scripts/ops/bars/ops_d1_bootstrap.py
    - scripts/ops/bars/ops_venue_study.py
    - scripts/research/swap_1d_primary_measure.py
    - scripts/research/vendor_basis_study.py
decisions:
  - "R6 judges only the raw plane (ohlcv_load destination raw): ledger identity, revision coverage, lost new rows, unledgered rows; the 191-07 re-judge restamp is the one explained class"
  - "Four old-store scripts with no live caller are deleted, not converted; the D7 and bar-auditor units stay held for plan 191-09, which owns those modules"
  - "ops_raw_backfill and ops_selection_gate.locate_groups keep reading the old stores until plan 16's last balance check (todo 535 item 41)"
metrics:
  completed: 2026-10-15
---

# Phase 191 Plan 11: scripts leave the old stores, R6 over raw

R6 now balances every served bar against ohlcv_raw and the revision log and exits 0 live; four
old-store scripts with no caller are deleted, two are converted to raw, and the window is closed
for the units whose modules no longer touch the old stores.

## 1d catch-up (handoff first step)

At 20:52 UTC canonical `market_data_ohlcv` 1d still ended 2026-10-12 (1,492 names). The fetcher
run started 18:41 UTC was still active: raw IBKR smart_trades held 2026-10-13 and 2026-10-14 for
356 names at 20:52 and 381 at the end of this plan. The daily stage runs after the fetcher run; the
check stays open in HANDOFF (not blocked on).

## Script decisions (no-caller greps over scripts services src tests docs/foundation docs/reference docs/operations systemd production .github)

| Script | Callers found | Decision |
|---|---|---|
| ops_d1_bootstrap | _fetcher_lock comment, ops_legacy_restamp docstring, three guard allow-lists, gotchas | deleted: phase 185 one-shot, both halves ran 2026-09-30, history in raw since plan 03; no SOP calls it |
| ops_venue_study | _fetcher_lock comment, bar_reconciliation_audit comment, guard lists, gotchas, migration 401 | deleted: D3 study, verdict applied by migration 401; the last ObservationSink caller |
| swap_1d_primary_measure | its test, migration 457 comment | deleted: Tradier to SMART swap evidence (185-46/47), Tradier retired; reproduction stays at commit 8c7ce4760 |
| vendor_basis_study | its test | deleted: Tradier vs SMART basis study (185-37); same reason |
| ops_bar_load | ops_restatement_review, onboarding SOP | already on the plan 05 entry points; `--help` smoke ok, no change |
| ops_alpaca_raw_archive_backfill | none | already deleted by 7b8e13808 (plan 05) |
| ops_intraday_venue_recovery | guard lists, gotchas | no old-store reference; unchanged |
| ops_head_rerun | ops_data_bar_check imports it | converted (below) |
| ops_source_policy | selection gate, fetch-queue comment | converted (below) |

## Conversions

- ops_capture_completeness (R6): four terms per (source, timeframe) over `ohlcv_load` rows of
  destination raw: ledger_gap (served minus new, changed, unchanged, removed, superseded,
  refused), revision_gap (changed plus removed minus `ohlcv_revision` origin raw rows), lost_new
  (new minus removed minus current) and unledgered (current minus new minus changed). `current`
  is counted per symbol from the ledger in one repeatable-read snapshot, every raw read naming
  symbol, timeframe and vendor (12 s). Live result: unexplained 0 on all four rows (ibkr 1d, 4h,
  5m; tradier 1d). The first run found 340,682 unledgered ibkr 5m rows: all are rows the 191-07
  re-judge (caller refusal-rejudge-191) restamped (served_at and load_id only; `write_raw`
  restamp raises on a changed value, ac4f598e0). They are reported as `restamped` (352,975 at the
  final run) and their changed values are still checked by revision_gap.
- ops_head_rerun: a request's first bar is the earliest bar its id names in `ohlcv_raw` or
  `ohlcv_revision`; moved-name detail reads the `venue_<route>` raw kinds. Baseline before and
  after over 1,440 late names (logs/head_rerun_191_11_{before,after}.json): moved set 90/90 equal;
  two dispositions changed, BNO and BSY unresolved to verified_empty, because their latest SMART
  request was answered after the cutover and had no observation rows (the old read gave None).
  Per-request first bars: 359 post-cutover requests None to a date, 42 older requests None to a
  date, 819 recent and 3 older requests later (last-wins moved a re-served bar's request id), 222
  repeated venue requests date to None (an identical later request now owns the bars). None of
  these touches a moved name or a head re-ask's oldest window.
- ops_source_policy: valid_from's first TRADES date comes from the same raw read (`read_daily_inputs`),
  one query fewer; new unit test.

## Inventory (repo-wide grep, final)

`grep -rnE "ohlcv_observation|ohlcv_intraday_raw_archive|ObservationSink|insert_fetched_archive_rows|ARCHIVE_FROM_TABLE_SQL" src services scripts tests`, classified:

| Hit | Class |
|---|---|
| services/ohlcv_observation_writer.py, tests/unit/services/test_ohlcv_observation_writer.py, tests/integration/test_ohlcv_observation_store.py | module plan 16 deletes (no importer left) |
| services/bar_reconciliation_audit.py (9 SQL reads), services/bar_auditor.py (15m/1h map) | executable, owned by plan 191-09 (not yet executed) |
| scripts/ops/bars/ops_raw_backfill.py (14), ops_selection_gate.locate_groups (2) | executable old-store migration tooling; plan 16 runs its last balance with them, then deletes (todo 535 item 41) |
| `ohlcv_observation_writer` role name in _intraday_persist.py, ohlcv_request_writer.py and their tests; APR key `infra.ohlcv_observation.copy_batch_rows` in _history_fetch, ohlcv_raw_writer, ohlcv_ingress_contract | role and key names, not table reads |
| vendor_kind.observation_kind docstring; services/README.md | text |
| tests/unit/*_migration_contract.py, test_single_writer_registry, test_*_boundary, tests/integration/fixtures | historical-migration contract strings and registries |

Executable references outside the two retiring modules: bar_reconciliation_audit and bar_auditor
(plan 09) and the two migration tools (plan 16). No script imports ObservationSink.

## Window

aggregator and writer cleared with evidence `191-11-WINDOW-EVIDENCE.json` and resumed (both were
inactive and disabled before the window; resume_action none). The D7 timer and service and
bar-auditor stay held: their modules still read the old stores and plan 09 clears them after its
D7 baseline diff. The fetcher timer is active.

## Deviations from Plan

1. [Rule 4 scope, decided] Window not fully closed: plan 09 (owner of D7 and bar_auditor) has not
   run, so three units stay held; closing them now would resume D7 on the old stores.
2. [Rule 2] Deleted instead of converted: ops_d1_bootstrap, ops_venue_study (both ObservationSink
   writers) and the two research scripts; the plan allowed deletion after a no-caller check.
3. [Rule 3] Migration 490 retires `infra.bar_campaign.bootstrap_years`, orphaned by the
   ops_d1_bootstrap deletion (reader test failed); rows backed up to data/backups/191-11/.
4. [Rule 2] R6 counts the 191-07 restamp as an explained class (metadata only, verified in code).
5. The `_fetcher_lock.py` comment still names the deleted scripts: the live fetcher imports the
   module, so the edit waits (todo 535 item 41).
6. No /simplify or /review run here; the independent review of 11 is next.

## Verification

- `.venv/bin/pytest tests/unit/ -q`: passes.
- `.venv/bin/python -m scripts.ops.bars.ops_capture_completeness --gate`: exit 0.
- `grep -rln "ohlcv_observation_writer\|ObservationSink\|archive_frame_to_tuples\|split_series" scripts src services tests/unit`:
  only the writer module, its test, role or registry strings, and guard tests that assert absence.

## Self-Check: PASSED

Commits 3b23c8c5b, 0add3a02d, e10b7015d, b5d15b92a, f1f4dcaa4, 6ea305434 exist; migration 490 applied live.
