---
phase: 191-unified-raw-bar-table
plan: 23
subsystem: bars
tags: [tradier-retirement, code-deletion, services, canonical-1d]
requires: [191-22]
provides: [tradier-free canonical 1d sets and bar services, 31-name digest proof]
affects: [191-25]
key-files:
  modified:
    - src/intelligence/bars/sources.py
    - src/intelligence/bars/vendor_kind.py
    - services/bar_derivation.py
    - services/bar_hold.py
    - services/bar_reconciliation_audit.py
    - services/listing_venue_writer.py
    - services/rebuild_preconditions.py
    - services/README.md
    - production/grafana/dashboards/operations.json
metrics:
  completed: 2026-10-29
---

# Phase 191 Plan 23: Tradier out of the canonical 1d sets and the bar services

The retired vendor's `("tradier", "consolidated")` pair is gone from `CANONICAL_1D_SOURCES` and the volume-basis map, the audit's agreement report, the hold ratios, the listing venue official-close read and the derivation's snapshot restore arm are deleted; canonical 1d digests for the 31 baseline names are identical.

## What changed

- `sources.py`, `vendor_kind.py`: the Tradier pair leaves `CANONICAL_1D_SOURCES` and `VOLUME_BASIS_BY_VENDOR_KIND`. `CANONICAL_1D_VENDORS` is now `(alpaca, ibkr)` and `CANONICAL_1D_KINDS` `(fallback, named, sip_rth, venue)`. `BAR_VENDORS` "tradier" and `BAR_KINDS` "consolidated" stay (CVR codes pinned by the migration contract test).
- `bar_reconciliation_audit.py`: `SOURCE_TRADIER`, `VendorYear`, `VendorAgreementAccumulator`, `_VENDOR_SYMBOLS_SQL`, `_VENDOR_PAIRS_SQL`, `_vendor_agreement`, the two `bar_reconciliation_vendor_*` gauges, the vendor facts and the printed table are deleted. The Tradier `no_data` branch of `_EMPTY_SESSIONS_SQL` is deleted too; `ohlcv_request` holds no tradier `no_data` row (6,506 bars, 7 failed), so the result is unchanged (live query returns the same 252 spans). A Tradier daily pair is now a stray source (`check_stray_sources`), which is correct: the live table holds none.
- `production/grafana/dashboards/operations.json`: the two panels (ids 45, 46) that plotted the deleted gauges are removed.
- `listing_venue_writer.py`: `VENDOR_TRADIER`, `_OFFICIAL_CLOSE_SQL` and the official-close read are deleted; the first-bar read is IBKR only. The pure scoring functions still accept an `official_close` series (tested), the loader supplies `{}`. Live behavior is unchanged because the Tradier raw rows were already deleted.
- `bar_hold.py`: the ratio read takes ibkr smart_trades via route SMART only.
- `bar_derivation.py`: the `--restore-snapshot` arm is deleted (`_execute_restore`, `_restore_symbol`, `_read_1d_snapshot`, the argument, the constructor parameter, `_RESTORE_LOAD_CALLER`); the stored-group label `tradier_only` becomes `alpaca_only`. The revision waiver SQL still honors the 3 historical `bar_derivation-restore` loads in `ohlcv_load`. Decision: delete rather than limit to IBKR-only snapshots, since the one snapshot is 6.27M Tradier rows of 7.01M and a restore would reinstate bars the rule can no longer produce; re-derive instead.
- `rebuild_preconditions.py`: its only Tradier text was a comment on the landing markers; reworded. No branch existed.
- Tests: the daily-stage fixtures move from Tradier primary to Alpaca primary (route ALPACA, stored alpaca/sip_rth); the no_provider_volume case, which an Alpaca primary never serves, now has its own IBKR-primary test; the restore tests become one test that the arm is gone; the audit fixtures, stray-source cases, hold ratios, listing venue reads, volume-basis and migration contract tests follow.

## Digest proof (T-191-48)

`digest_probe.py` run with `PYTHONPATH=/home/bg/dev/indicagent-a` against `logs/tradier_code_delete_digest_before.json`: 31 names, 0 differences on `harness_bars`, `harness_digest`, `stored_digest`, `stored_rows`. Output kept in the scratchpad as `after23.json`.

## Removed-symbol decisions

| Symbol | Decision |
|---|---|
| `SOURCE_TRADIER`, `VendorYear`, `VendorAgreementAccumulator`, vendor gauges | deleted; callers were this service and its tests only; Grafana panels removed. |
| `listing_venue_writer.VENDOR_TRADIER`, `_OFFICIAL_CLOSE_SQL` | deleted; no other caller. |
| `bar_hold.vendor_rescale_ratios` | kept (`ops_split_detect.py` calls it); returns SMART only. |
| `bar_derivation._read_1d_snapshot`, `_execute_restore`, `--restore-snapshot` | deleted; docs under `.planning/phases/185-*` keep describing them as history. |
| `daily_rule.py`, `source_admission.py`, `vendor_arbitration.py` | untouched per scope; `RAW_DAILY_SERIES` still lists the Tradier raw series, so the daily raw read's `vendor = ANY(...)` filter still names it as data (matches nothing). Callers left in `scripts/` (`ops_data_bar_check`, `ops_head_rerun`, `ops_source_policy`, `ops_tradier_residue`, `ops_d191q_arbitration`, `ops_tradier_delete`) are plan 25. |

## Deviations from plan

- [Rule 3] Touched `tests/unit/bars/test_volume_basis.py`, `tests/unit/test_bar_source_policy_migration_contract.py`, `production/grafana/dashboards/operations.json` and `services/README.md`, none in the plan's file list: each pinned or plotted a deleted symbol.
- The `listing_venue_writer` choice (keep the pure official-close scoring, drop only the Tradier source) is a judgement call; a re-run of the writer now infers by the volume rule alone, and spans written earlier with the official close would show as conflicts. No run was made. Flag for the data lane.
- The plan's done-grep `grep -rniE tradier services | grep -v comment-lines` prints only `services/README.md` before this edit and nothing after.
- The /simplify and /code-review skills are not callable from this agent; the diff was self-reviewed by hand. The data lane runs the independent review.
- Nothing was restarted or stopped. The timer services import the shared checkout, which this plan did not touch.

## Verification

- Full `tests/unit` (`-n auto`): all pass.
- Imports: every `services/*.py`, `scripts/ops/bars/*.py` and `scripts/infrastructure/backfill/*.py` imports with `PYTHONPATH=.:services`.
- Live read-only check of the 1d stage SQL with the new sets (`_SELECT_STORED_1D_SQL`, `_SELECT_DIGEST_1D_SQL`, `_FIRST_1D_BAR_SQL`, `_EMPTY_SESSIONS_SQL`): all execute (SPY: 6,873 rows both reads).
- ruff and black clean.

## 186-26 code key

`services/backfill_feature_factory.py` `unit_code_key` closure (row contract plus every kernel module) includes `src/intelligence/bars/sources.py` and `src/intelligence/bars/vendor_kind.py`, so the key moves with this plan. It excludes `bar_derivation`, `bar_hold`, `bar_reconciliation_audit`, `listing_venue_writer` and `rebuild_preconditions`. No `backfill_feature_factory` or ic run was live when edited.

## Self-check: PASSED

## Review and fix (2026-10-29)

Fresh-context review: PASS WITH FIXES. Canonical 1d is unchanged (7,084,546 rows under the old and new vendor and kind sets), the 252 empty-session spans are identical, `check_stray_sources` returns 0 on live counts, `bar_hold` ratios match, every module imports, and no changed service is in the 186-26 code key.

Fixed: `listing_venue_writer._write_symbol` now returns `unresolved` for a name whose inferred spans include a closed former-venue span while the official-close series is empty, instead of appending it. On live data a volume-only run would have inserted 21 moved names, 8 of them with a BATS span before BATS existed (2008-10-17), into the append-only `listing_venue`. Open spans from the SMART primary are unaffected. The writer has no timer. Restoring the official-close source (or a different evidence basis with its own `RULE_VERSION`) is the way to resolve those names; until then the 564 conflicts and 21 moved names stay unwritten.

Left for plans 24 and 25: `daily_rule.PRIMARY_PAIR` and `RAW_DAILY_SERIES` still map the Tradier pair, which the canonical sets no longer include; unreachable with zero Tradier rows.
