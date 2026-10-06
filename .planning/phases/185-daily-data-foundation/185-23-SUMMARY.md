---
phase: 185-daily-data-foundation
plan: 23
subsystem: bars / data integrity
tags: [D7, reconciliation, integrity_monitor, otel, grafana, todo-462, tradier]
requires: [185-12, 185-19, 185-20, 185-21, 185-22]
provides: [bar-reconciliation-audit oneshot, nightly status file, D7 Grafana panels]
affects: [infrastructure_nightly_backfill, service_auditor registry, operations dashboard]
tech-stack:
  added: []
  patterns: [pure checks + BaseBatch IO split, metrics labeled by check only, all-or-nothing fact emission keyed by session date]
key-files:
  created:
    - production/migrations/407_bar_reconciliation_apr.sql
    - production/systemd/indicagent-bar-reconciliation-audit.service
    - tests/unit/scripts/conftest.py
  modified:
    - services/bar_reconciliation_audit.py
    - tests/unit/services/test_bar_reconciliation_audit.py
    - services/service_auditor.py
    - scripts/infrastructure/backfill/infrastructure_nightly_backfill.py
    - tests/unit/scripts/test_infrastructure_nightly_backfill.py
    - tests/unit/test_market_data_ohlcv_boundary.py
    - production/grafana/dashboards/operations.json
    - tests/unit/scripts/test_grid_lane_guard.py
decisions:
  - "D7 masked-slot check treats a partial_constituents bar as not masked (it carries the real volume of the constituents it has) and reports those slots separately as partial_with_volume_by_tf"
  - "The nightly runs the D7 audit from main()'s finally, so a crash still audits and the status file still says 'started'"
metrics:
  completed: 2026-10-06
  tasks: 2
  files: 11
---

# Phase 185 Plan 23: D7 nightly reconciliation audit summary

One read-only oneshot, `services/bar_reconciliation_audit.py`, chained as the last step of every
nightly backfill run, reconciles IBKR's views of a bar against each other and against Tradier, and
reports per check to `integrity_monitor` and through OTel (labeled by check, timeframe or year,
never symbol) to Prometheus and four panels on the operations dashboard.

## Takeover note

The plan was abandoned mid-execution on 2026-10-03 by a session that no longer exists. Task 1
landed as 56f4e1731 (pure checks, migration 407, skeleton). The remaining WIP (IO layer, unit file,
registry, nightly chaining, Grafana, tests) was reviewed against the plan before commit: every
behavior in Task 1 has a test (55 tests in the audit file), the nightly chaining covers success,
lease timeout, nothing-to-do and a crash, and script tests cannot touch the production status file
or spawn a live audit (`tests/unit/scripts/conftest.py` autouse fixture; verified the live status
file was absent after the test run).

## Tasks

| Task | Name | Commit |
|------|------|--------|
| 1 | Pure checks and migration 407 | 56f4e1731 (prior session) |
| 2 | IO, unit file, registry, nightly chaining, Grafana panels, live run (plus Task 1 check refinements) | 34ffb1fe0 |

Migration 407 is the only 407 on disk, committed in 56f4e1731 and applied live (all 11
`threshold.bar_reconciliation.*` keys present in `config_state`). The plan named 6 keys; the
migration seeds 11 (adds seam_scale_sessions, volume_tolerance_rel, completeness_min_share,
completeness_years, nightly_max_age_hours).

## Live run (2026-10-06 06:00 UTC, 63 s, exit 0)

Last session 2026-10-05; judged sessions 2026-09-29, 09-30, 10-01, 10-02, 10-05; completeness
window from 2026-01-01. 769 `integrity_monitor` rows written for training_window_end 2026-10-05
(767 more exist for 2026-10-02 from the prior session's run).

| check | findings | judged | reading |
|-------|---------:|-------:|---------|
| route_disagreement | 0 | 36 | listing venue agrees with SMART |
| adjusted_vs_trades | 0 | 1,860 | |
| daily_vs_intraday | 5 | 409 | close only: LLY, MARA, TDOC 09-30; VIXY 09-29 and 09-30 |
| unexplained_seams | 2 | 3,331 | FICO 09-29, LQDA 09-30 |
| late_heads | 15 | 81 | moved names without recovery (PEP, CSX, RIOT, MATX, ...), the known plan 14 residue |
| unconfirmed_empty | 6 | 111 | 1d rows from 2006-10 (CYRX, IBEX, KURA, MARA, ODFL, POWI) |
| partial_daily | 85 | 2,159 | D1 SMART 09-30 bars fetched about 19:05 UTC, before the close, never re-fetched |
| dividend_freshness | 0 | 931 | |
| nightly_skipped | 1 | 1 | `no_status`: the status file does not exist until the first nightly on this code |
| stray_sources | 27,317 | 62,412 | 15m ibkr_named 21,486 rows on 302 names, 1h 5,831 on 303 |
| switches | 0 | 2 | |
| completeness | 699 | 699 | every (symbol, tf, 2026) cell below 0.996 |
| masked_slots | 0 | 233 | |

Masked slots (todo 462): zero masked 15m and 1h slots on every derived symbol (`masked_derived_by_tf
= {15m: 0, 1h: 0}`) and zero overall over 2026. The 185-12 SUMMARY baseline it is compared against:
155,022 masked 15m slots pre-rewrite (2007 to 2026, measured 2026-09-29; 2025 alone 84,032 slots on
13 names), 13,033 after the rewrite and all of those ACRS 2020-2022 (outside this run's 2026 window,
not derived). Acceptance met. Slots with a partial_constituents bar and 5m volume, reported apart
from masking: 15m 12,118, 1h 5,811.

Reading the large counts:

- stray_sources: none of the 302 names has a derived_5m 15m row; they are the not-yet-derived names
  whose 15m/1h still comes straight from IBKR, and the newest stray row is 2026-10-01 18:45 UTC,
  before 185-12's cutover. With a 5-session window the count should fall to zero once 10-01 rolls
  out (after the 10-07 session); any ibkr_named 15m/1h row after that is a real stray writer.
- completeness: pooled shares 5m 0.954, 15m 0.949, 1h 0.954, each name about 1.6% short in 2026.
  Latest tradeable 5m bars are 09-29 to 10-01 (SPY 09-29, AAPL 09-30, AA 10-01): the 5m lane is
  paused (PAUSE_5M, todo 462), so the most recent sessions are unanswered holes. This is a true
  finding about the feed, not a check defect.

Vendor agreement (Tradier vs IBKR SMART TRADES, 3,909,785 overlapping days, 15 bp tolerance):
7.5% of closes differ pooled (2006 24.7%, falling to 2026 1.1%); median IBKR/Tradier volume ratio
0.957 in 2006 to 0.550 in 2026. Against the 2026-10-03 baseline (6.5%; 18.6% in 2006 to 1.0% in
2026; ratio 0.96 to 0.55): the volume ratios and the 2026 share reproduce, while the early-year
close shares run higher. The baseline's close tolerance is not recorded in 185-CONTEXT, so the gap
is most likely a definition difference (tolerance), not drift; todo 492 owns the vendor question.

## Verification

- `pytest tests/unit/services/test_bar_reconciliation_audit.py tests/unit/services/test_service_auditor_registry_integrity.py tests/unit/test_market_data_ohlcv_boundary.py tests/unit/scripts/ tests/unit/test_migration_number_uniqueness.py --ignore=tests/unit/scripts/test_history_fetch_item.py`: 603 passed, 2 skipped. The ignored file fails collection against phase 189's uncommitted `_history_fetch_item.py` draft, not this plan.
- ruff and black clean on all touched files; pre-commit 9/9 passed.
- `grep -n "symbol" services/bar_reconciliation_audit.py | grep -i "add(\|\.set("`: empty.
- Dashboard JSON contains `bar_reconciliation_findings_total`; panel ids unique.
- `select count(*) from integrity_monitor where monitor_type='bar_reconciliation'`: 1,536.

## Deviations from plan

1. [Rule 3 - Blocking] `test_market_data_ohlcv_boundary.py` failed on HEAD: the Tradier daily
   loader (b3c164a76) reads the raw table without an allow-list entry. Added a PERMANENT entry
   with its reason (it diffs existing rows of every real source to record revisions). Commit 34ffb1fe0.
2. [Rule 3 - Lint] `test_grid_lane_guard.py` import block failed ruff I001 on HEAD; the one-line
   WIP fix was kept. Commit 34ffb1fe0.
3. Masked slots: the plan's truth counts a partial_constituents slot as masked; the behavior list
   and the implementation do not (a partial bar carries real constituent volume, so it hides
   nothing). Those slots are reported separately (`partial_with_volume_by_tf`) so nothing is lost.
4. Additions beyond the plan's check list, all from live data during the prior session:
   `partial_daily` (D1 bars fetched before the close), listing-venue-only route judging (D3
   criterion b), and the vendor-agreement metrics as gauges labeled by year.
5. Grafana: three panels beyond the one the plan names (completeness by timeframe, vendor close
   disagreement and volume ratio by year).

## Follow-ups (not filed as todos by this executor)

- partial_daily's 85 findings mean D1's latest view of 09-30 is partial for those names; the next
  1d fetch with overlap should heal them, and the check confirms it.
- stray_sources: confirm the count reaches zero after the 10-07 session rolls 10-01 out of the window.

## Self-Check: PASSED

- production/systemd/indicagent-bar-reconciliation-audit.service, tests/unit/scripts/conftest.py, production/migrations/407_bar_reconciliation_apr.sql: present.
- Commits 56f4e1731 and 34ffb1fe0: present in `git log`.
