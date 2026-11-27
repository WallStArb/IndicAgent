---
status: pending
priority: P1
filed: 2026-11-21
source: Alpaca nightly 2026-11-20 exited 1 (PARTIAL, one basis-change restatement flag, SNDK 5m); second case in two days after VIXM (todo 641)
owner: lead
---

# Splits after the Massive seam are found by a failed nightly, not by a detector

## What

SNDK split 8:1 (Yahoo ex-date 2026-11-20). Alpaca restated 576 stored 5m bars (price ratio 0.125, volume ratio 8) and the nightly exited 1 on the basis-change flag, load 6449933f. Canonical takes Massive to the 2026-11-16 seam (old scale, 1d close 885.01 on 2026-11-13) and Alpaca after (new scale, 101.14 on 2026-11-16), so canonical steps 8x at the seam. The A3 sweep cannot judge a series switch at the junction (no measured level on the Massive side), so the row is written by hand. Row file: `config/corporate_actions/split_rescale_rows_2026_11_21_sndk.csv` (factor 8, last old-scale session 2026-11-13, route massive/sip_flat), same procedure as VIXM.

## Why a class, not a name

The archive ends at the seam and the plan lapses about 2026-12-10, so every split from now on is in this class: Alpaca serves history already adjusted, stored Massive bars stay old scale, and the only alarm is the nightly's restatement flag (loud, but a human reads it, finds the witness and writes the row). Two in two days. Measure the base rate before building (splits and reverse splits per month across the active names, from the Alpaca corporate-actions feed or the Yahoo calendar), then decide.

## Done when

1. SNDK row applied, SNDK reselected, `split_horizon_fresh` reads clean for `SNDK|5m`, the 6449933f flag marked reviewed (`ops_restatement_review`).
2. The base rate is measured and recorded here. If it is more than about one a month, a nightly step proposes the row file from the Alpaca corporate-actions feed for the flagged name (proposal only; the apply and the review stay manual, the same rule as `calendar_market`). If it is lower, close this todo with the number and keep the manual procedure in `docs/reference/gotchas.md`.

## Progress 2026-11-21

Row recorded (`calendar_market`, 2026-11-13, factor 8, commit 407494a70, independent review ok). SNDK-only `services.bar_derivation --stage daily --apply` rescaled canonical 1d (2026-11-13 now 110.63). No CLI reselects one name's 5m after a split row (the reselect trigger on a split write is "not built", step 7 runbook), so the 5m reselect ran `select_and_write` for SNDK 5m from 2025-02-01 in one transaction (33,822 Massive rows rescaled, 390 unchanged, 376 old-scale Alpaca rows unselected); 5m reads continuous across the seam (2026-11-13 closes 106 to 115, 2026-11-16 closes 100 to 104). `ops_selection_gate --compare --symbols SNDK --timeframes 5m` exit 0, 0 unreviewed flags, flag 6449933f marked reviewed. Open: `split_horizon_fresh` for `SNDK|5m` in the next 06:00Z audit, then item 1 closes. Item 2 should also decide the missing single-name 5m reselect CLI (the script used is a copy of `ops_source_policy.write_and_reselect` without the policy write).

## Not blocking

No corpus compute runs before the data gate; the stage 2 chain does not touch SNDK's recent bars.

## Base rate measured 2026-11-23 (indicagent-d4, read-only)

Sources: Alpaca corporate-actions feed (`data.alpaca.markets/v1/corporate-actions`, forward and reverse splits, ex-dates 2026-11-16 to 2026-11-23), `ohlcv_restatement_flag`, `corporate_action`, `instruments`.

- Post-seam splits in the feed: 63 (ex-dates 2026-11-16 to 2026-11-23, 8 days; the 14 on 2026-11-23 are not yet through a nightly). 60 of the 63 symbols are in `instruments`, and only 2 are active (SNDK, VIXM). The other 58 are inactive: no Alpaca capture, last bars are the archive's, so no post-seam canonical exposure.
- Active names: 2 splits in the first 8 days, about 1.75 a week. Both were caught as restatement flags on the first nightly that saw them (`signatures` share, price_ratio, volume_ratio; ratios 2.0 and 0.125; 136 and 576 5m bars) and both rows were recorded the day after the flag. The flag table holds 4 other post-seam flags (SO once, NVDA three times, share-only, no ratio, not splits).
- Latency, ex-date to recorded row: VIXM ex 2026-11-19, flag in the 2026-11-19 UTC load, row 2026-11-20; SNDK ex 2026-11-20, flag in the 2026-11-21 UTC load, row 2026-11-21. One to one and a half days each, by hand. Each touched 1 name; neither touched another symbol.
- Longer base rate, active names, `corporate_action` rows by effective date over the last 12 months (non-void, not superseded): 36, about 3 a month, 0.7 a week; the 2 post-seam events are above that mean on a sample of 8 days. Most of those 36 came from `massive_reference`, which stops when the Massive plan lapses about 2026-12-10, so after the lapse every active-name split reaches `corporate_action` only through the nightly flag and a manual row.
- Misses: none seen (every active split in the feed had a flag). The flag path depends on Alpaca restating stored 5m bars, so a split where Alpaca serves no stored overlap on 5m would not flag; unmeasured at n = 2.

Recommendation: build. The rate (about 3 a month, above the 1 a month threshold in Done-when 2) and the loss of `massive_reference` justify a nightly step, and the feed already returns the ex-date, ratio and symbol, so the detector does not depend on the flag.

Proposal (proposal only, not built): after the Alpaca nightly capture, one call to the corporate-actions feed for forward and reverse splits with `start` at the last processed ex-date and `end` 14 days ahead; keep the symbols that are active in `instruments`; for each, write a candidate row file under `config/corporate_actions/` in the `split_rescale_rows` format (factor from `old_rate` and `new_rate`, `calendar_market` route, last old-scale session from the canonical 1d series) and log a loud warning with the count. Apply, the Yahoo witness and the review stay manual, as for `calendar_market`. Also surface a feed split with no matching flag and no row after the ex-date as a failing check, which closes the unmeasured miss case. Open for review: the file format and the single-name 5m reselect CLI named in the 2026-11-21 progress note.

Status: Done-when 2 is decided (build, proposal above); item 1 still needs the `split_horizon_fresh` read for `SNDK|5m`. The todo stays pending until the detector is built or declined.

## Progress 2026-11-23 (detector built)

Item 1 closed: `split_horizon_fresh` for `SNDK|5m` was a correct read. The 2026-11-22 full sweep (bar_reconciliation_audit log, 13:34Z) reports it passing for 1,529 of 1,529 names with no failing entry, after the 2026-11-21 reselect.

Item 2 built as `services/split_feed_auditor.py` (oneshot, unit and timer in `production/systemd/`, APR keys in migration 612, tests in `tests/unit/services/test_split_feed_auditor.py`). It judges each active-name feed split as recorded, candidate, unseen or overdue as the proposal above describes, writes candidates to `logs/split_candidates/`, and never writes `corporate_action`. Run live read-only on 2026-11-23: 86 feed splits since 2026-11-09, 84 inactive ignored, SNDK and VIXM recorded, exit 0. The timer is not installed; enabling it needs sudo and is the lead's decision. Open: the single-name 5m reselect CLI (the 2026-11-21 note); close this todo when the timer runs once clean.

## Verdict refresh needs an owner of record (2026-11-24, indicagent-fb)

The pin gate (`d2_landed`) refuses member 1d verdicts older than `threshold.bar_integrity.report_max_age_hours` (30 h). The 06:00Z bar-reconciliation audit refreshes active names only; dead members' verdicts come from `scripts/ops/bars/ops_member_verdicts_1d.py --apply` (about 1.8 h measured 2026-11-25), which has no timer and no owner, so the pilot 7c5612f0 pin gate refused 11,350 of 12,857 members at 61.4 h. Ruling (lead, 2026-11-24): the refresh is launcher-run, not a timer. The operator of a pilot or stage launch runs the refresh command the launcher preflight prints (a timer would join the quiesce set, and the verdicts only matter right before a pin). Recorded in `docs/operations/guarded-run-runbook.md`. Not part of the split detector; recorded here because the refusal arrived with it.

## Timer check and mechanical closing criteria (2026-11-27, indicagent-a1, read-only)

Checked: `indicagent-split-feed-auditor.timer` is enabled and loaded, next fire 07:45 UTC (the unit reads `OnCalendar=*-*-* 07:45:00 UTC`, `Persistent=true`). The service is a oneshot with no `[Install]`, so `disabled` on the service is correct. One run so far, 2026-11-26 08:30:06Z (a catch-up fire), exit 0 in 0.36 s: feed read 74 splits since 2026-11-16, 72 inactive ignored, 2 recorded (SNDK, VIXM), 0 candidates, 0 unseen, 0 overdue. Metric visible: `job_completed_total{job_name="split-feed-auditor",status="success"}` is in Prometheus (`:9090`; `job_name` is the oneshot name, `job` is `otel-collector`). Query it with a range (`[2d]` or `max_over_time(...[26h])`), because an instant query returns nothing a few minutes after the push.

Gaps found (no code edited):
- The defect-class counts exist only in the log line `split_feed_auditor.judged`, not as metrics. Only the run status is a metric. Closed by todo 683 (2026-11-27): the gauge `split_feed_auditor_splits{class}` holds them (a base rate over a range is `max_over_time(split_feed_auditor_splits{class="unseen"}[30d])`), with a panel on the operations dashboard.
- `NightlyCaptureMissed`-style alerts exist for the alpaca nightly only. The generic oneshot alert fires on `status="failure"`; a `gap_found` or `candidates` run exits 1 or writes a file but sets a different status, so nothing alerts. A missed fire of this timer is also unalerted. Add both with the next alert-rules batch (todo 681 owns the rules file).
- No Grafana panel reads `job_completed_total` (the oneshot panel on the operations dashboard now does, panel 71).

Base-rate query (defect classes per run, read from the log; run from the repo root, any time):

```
grep -h '"split_feed_auditor.judged"' logs/split_feed_auditor.log | jq -s '{runs:length, runs_with_candidates:(map(select(.n_candidates>0))|length), runs_unseen:(map(select(.n_unseen>0))|length), runs_overdue:(map(select(.n_overdue>0))|length), max_recorded:(map(.n_recorded)|max)}'
```

Splits per month on active names are the growth of `corporate_action` rows with `effective_date` in the window for active instruments (read-only SQL, the 2026-11-23 method above); compare with `runs_with_candidates`.

Close this todo, with no further judgment, when all hold on one read:
1. At least 28 `split_feed_auditor.complete` lines with status `success` or `candidates`, on at least 28 distinct UTC dates (earliest possible 2026-12-25).
2. Zero `split_feed_auditor.run_failed` lines in the log, and `max_over_time(job_completed_total{job_name="split-feed-auditor",status="failure"}[30d])` is empty.
3. `runs_unseen` and `runs_overdue` are 0 on the last 7 runs; every candidate file in `logs/split_candidates/` is applied (a `corporate_action` row exists for its symbol and ex-date) or noted as declined in this todo.
4. The base-rate output and the monthly active-name split count are pasted here, and the alerts `SplitFeedAuditorMissed` and `SplitFeedAuditorFinding` are in `production/alertmanager-rules.yml` and the oneshot panel is on the operations dashboard (the alert gaps above); defect counts as metrics are todo 683.
Then move the todo to `completed/` in the same commit as the PRIORITIES row removal. If the Massive lapse (about 2026-12-10) leaves candidates unreviewed, criterion 3 stays open.
