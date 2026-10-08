---
phase: 189-ibkr-history-fetch-consolidation-single-fetcher-coverage-led
plan: 10
scope: Task 1 only (partial; Task 1b, Task 2 and Task 3 not run, plan not landed)
subsystem: ibkr-history-backfill
tags: [two-lanes, update-lane, gap-fill-lane, overlap-escalation, todo-507, parity-sample, migration-451, CD-06, CD-07]
requires: [189-08, 185-46, 185-43]
provides:
  - "one queue, two span rules: update lane (1d due rule, 5m 3-day overlap) and gap-fill lane (one session in every 7 per series)"
  - "due 1d items rank ahead of every 5m item; tradier_owned hold removed"
  - "in-process overlap escalation: 1d splits recorded, then full-depth re-fetch, then derive (todo 507 closed)"
  - "weekly parity sample: vendor 15m/1h for 10 names a week into the archive"
  - "ingress contract waiver for a recorded corporate action (5m escalation re-fetch)"
  - "migration 451 applied live 2026-10-08 04:04:59 UTC"
affects: [189-10 Task 1b, 185-47, 189-10 Task 2, 189-10 Task 3, 189-11]
key-files:
  created:
    - production/migrations/451_fetcher_reconcile_and_parity_apr.sql
    - tests/unit/test_fetcher_reconcile_parity_migration_contract.py
  modified:
    - scripts/infrastructure/backfill/_fetch_queue.py
    - scripts/infrastructure/backfill/ibkr_history_fetcher.py
    - scripts/infrastructure/backfill/_history_fetch_item.py
    - scripts/infrastructure/backfill/_history_fetch.py
    - scripts/ops/bars/ops_split_detect.py
    - services/split_detection.py
    - services/ohlcv_ingress_contract.py
    - tests/unit/scripts/test_fetch_queue.py
    - tests/unit/scripts/test_ibkr_history_fetcher.py
    - tests/unit/scripts/test_history_fetch_item.py
    - tests/unit/services/test_ohlcv_ingress_contract.py
    - .planning/todos/PRIORITIES.md
  moved:
    - .planning/todos/pending/507-split-refetch-in-process-under-the-fetcher-lock.md -> completed/
decisions:
  - "The 1d overlap key is a rename of infra.bar_derivation.overlap_sessions (value 20 and history kept), not a second key for the same overlap"
  - "infra.backfill.ibkr_1d_reconcile_interval_days counts completed NYSE sessions: due when the latest answered SMART TRADES 1d request predates the close of the Nth latest session"
  - "A stale canonical bar queues a name only when it was not asked since the last close, so a name IBKR cannot make current is never re-asked every 15 minutes (the freshness_1d verdict names it)"
  - "Any restated close escalates 1d (measured: 1 of 5,558 repeated observations moved); 5m escalates only on the median close ratio, because IBKR restates 15 to 40 recent 5m rows a name routinely"
  - "A 5m escalation re-fetch runs only through the waived grid writer, when a corporate action recorded after the series' last applied load explains it; otherwise the breach is an integrity fact and the run is partial"
  - "The gap-fill slot is a stable hash of (symbol, timeframe) against the weekday index of the last completed session: no stored state, the work spreads evenly"
metrics:
  completed: 2026-10-08
  tasks: 1 of 4 (Task 1)
---

# Phase 189 plan 10, Task 1: one queue with two lanes, overlap escalation in-process

The fetcher now asks every active name's 1d and 5m after each close since the latest stored
bar with a verified overlap, runs the full-depth gap fill on a per-series cadence, ranks every
due 1d item ahead of the 5m drain, and re-fetches a restated or rescaled name inside the same
run under its own lock (record, re-fetch, derive). Task 1b, Task 2 and Task 3 were not run; no
IBKR request was made and the fetcher service and timer were not touched.

## Commits

| Step | Commit | What |
|---|---|---|
| RED | 08126bf98 | failing tests: due rule, escalation, 1d-before-5m, gap-fill cadence, parity, split ordering, migration contract, item overlap and refetch, ingress waiver |
| GREEN | 714683f0d | queue, item, fetcher, split detection refactor, ingress waiver, migration 451 |
| fix | (summary commit) | a failed 1d overlap judgment makes the run partial and still derives (Rule 1), todo 507 closed, this summary |

## Preconditions

- `ps -eo pid,args | grep -E '[b]ackfill_feature_factory|[i]ntraday_chain|[i]bkr_history_fetcher'`: no process, before the first edit and before each commit.
- `indicagent-ibkr-history-fetcher.timer` and `.service`: inactive, timer disabled. Unchanged.
- Migration 451 free (`ls production/migrations`: 450, 453 to 455, 458, 459 present; 451 absent).

## What Task 1 built

Queue (`_fetch_queue.py`, pure functions plus two reads):
- `daily_due_reason(latest_answered, latest_canonical, DailyRule)`: `never_asked`, `reconcile_due` (latest answered SMART TRADES 1d request before `reconcile_after`, the close of the Nth latest completed session; N = 1 is the latest close), `not_current` (canonical bar not the last completed session and not asked since that close), or None (held as current). A 1d series whose last fetch errored is never held. The reads: latest answered request per name from `ohlcv_request` (test callers excluded) and latest canonical bar from `market_data_ohlcv_tradeable` over a 14-day lookback; once per run, about 100 ms.
- Rank gains a leading element `timeframe != '1d'` after the exclusion flag: every queued 1d item precedes every other item, including an SLA-breached 5m series with the full 20-year gap (the SLA band precedes the timeframe class, so the class alone could not do it).
- `gap_fill_due(symbol, tf, session_day, N)`: one weekday session in every N per series.
- `parity_sample(eligible, day, n)` and `parity_week_start(day)`: n names per ISO week by a stable hash, held once asked that week.
- `judge_overlap(pairs, tolerance_bp, escalate_on_restated)`: median stored/fresh close ratio and restated count.
- `LaneConfig`/`load_lane_config`: the six keys, no fallbacks (a missing key raises).

Item (`_history_fetch_item.py`):
- `_needs_full_window` no longer forces the full window for a short start; the gap-fill lane does that on its cadence (the fetcher passes `full_scan`).
- `overlap_days` (5m update lane): the tail starts that many days before the latest bar's midnight and the stored slots of that window are re-asked (merged with the planned gaps into one ask); the persister reads the stored closes first and returns `overlap_pairs`.
- `refetch` (escalation): the whole depth window, stored or not (1d: every session; 5m: one window); `waived` routes 5m through `_insert_market_data_rows_waived`.

Fetcher (`ibkr_history_fetcher.py`):
- `tradier_owned` hold, the `_DAILY_SOURCE_PROBE_SQL` import and `RunPlan.tradier_owned` removed; the `ops_split_detect.py` subprocess stage removed.
- `item_lane(plan, row)`: `parity` (tail, no overlap), `gap_fill` (full depth), `backfill` (never fetched or last failed: the item plans the full depth itself), `update` (5m with the overlap days; 1d's overlap is the run-level session overlap).
- After the loop, `_escalate`: the 1d judge (`services/split_detection.overlap_pairs` and `judge_overlap_pairs`) records splits with `ops_split_detect.record_split`, reports unexplained differences as integrity facts, and adds every name whose overlap ratio is outside tolerance or whose close was restated; 5m breaches come from the loop's `overlap_pairs`. Each escalated name is re-fetched at full depth on the open connection, under the run's lock, before the daily stage. A 5m re-fetch needs a corporate action recorded after the series' last applied load (`_WAIVER_SQL`); without it the breach is reported and the run is partial. A judgment exception makes the run partial and the daily stage still runs (as when split detection was a subprocess).
- Default runs add the parity sample: eligible names hold 5m coverage and archive rows (`ohlcv_intraday_raw_archive`, 15m or 1h); explicit runs get no sample.
- Run summary gains `lanes`, `escalated` and the `escalation` stage code; the dry-run TSV gains `lane` and `due_reason` columns and prints the composition by lane, timeframe and due reason.

Other: `services/ohlcv_ingress_contract.apply_ingress_contract(..., waived=False)` (the load row's detail names the waiver; every changed row still goes to `ohlcv_revision`); `services/split_detection.py` split into `overlap_pairs` and `judge_overlap_pairs` (`detect_overlap_splits` is their composition, behavior unchanged); `ops_split_detect.py` docstring describes the by-hand path, not a refusal inside fetcher runs.

## APR keys (migration 451)

| Key | Seed | Provenance | Notes |
|---|---|---|---|
| infra.backfill.ibkr_1d_reconcile_interval_days | 1 | [user_preference] | owner decision 2026-10-07 (IBKR is the 1d primary); counts completed sessions; min 1, max 30 |
| infra.backfill.update_overlap_sessions_1d | 20 | [initial_estimate] | renamed from infra.bar_derivation.overlap_sessions (migration 406), value and history kept |
| infra.backfill.update_overlap_days_5m | 3 | [initial_estimate] | reaches the prior session across a weekend inside the one request the 150-day chunk already makes; calibrate from ohlcv_revision ages (no 5m IBKR revision row exists yet: the fetcher has been stopped since 185-39) |
| infra.backfill.gap_fill_interval_days | 7 | [initial_estimate] | weekday sessions; a holiday slot skips that cycle |
| infra.backfill.grid_parity_sample_names_per_week | 10 | [initial_estimate] | 0 queues no 15m/1h item |

Descriptions rewritten (189-08 deferred item 6): `infra.ibkr.historical_request_timeout_sec` (names the stall bound and WatchdogSec, not the deleted retry-loop watchdog) and `infra.backfill.default_scopes` (states the post-189-07 value and the parity sample, not the nightly legs, the todo 449 campaign or PAUSE_5M).

Applied live 2026-10-08 04:04:59 UTC with `lock_timeout 10s` after a ROLLBACK dry run (UPDATE 1 x3, INSERT 4, 4, 5, UPDATE 1 x2). A rerun changed nothing but the two idempotent description UPDATEs. config_state: the four new keys at their seeds with one history row each; update_overlap_sessions_1d 20 with two history rows (migration 406's, renamed, and 451's); the old key has no row left.

### How the overlap tolerance was chosen

No new key. The comparison reads `threshold.bar_integrity.fallback_basis_tolerance_bp` (10 bp, [initial_estimate], migration 446's basis tolerance), as the 185-46 amendment specifies. Measured before choosing to reuse it (2026-10-07, read-only): over 5,558 pairs of repeated IBKR SMART TRADES 1d observations of completed sessions (931 names, bar dates from 2026-08-01), 0 closes moved by more than 10 bp, 1 close moved at all, 8 rows changed any of OHLC and 150 changed volume. So the median ratio never trips on routine re-asks, a split (ratio 2, 0.5, ...) always does, and "any restated close" for 1d costs about one extra one-request re-fetch per thousands of pairs. Volume never enters the decision.

## Verification

- Plan verify: `pytest test_fetch_queue.py test_ibkr_history_fetcher.py test_fetcher_reconcile_parity_migration_contract.py test_migration_number_uniqueness.py test_ibkr_history_lock_boundary.py` passes and the `_tradier_owned|_DAILY_SOURCE_PROBE_SQL` grep on the fetcher is empty.
- Tests for the required behaviors: `test_daily_due_rule_queues_a_name_asked_before_the_close_and_holds_one_asked_after`, `test_a_split_restated_overlap_escalates_the_name`, `test_an_unchanged_overlap_does_not_escalate`, `test_a_due_1d_item_precedes_a_5m_item_with_a_larger_gap`, `test_gap_fill_cadence_is_one_session_in_every_n_per_series`, `test_a_split_is_recorded_then_re_fetched_in_process_then_derived`, the migration 451 contract file, plus parity (`..._parity_count_at_zero_...`, `..._parity_sample_adds_15m_and_1h_...`), the 5m escalation and its unwaived path, and the item overlap and refetch tests.
- Full `.venv/bin/pytest tests/unit/ -q`: exit 0, 7,315 passed, 5 skipped (the five pre-existing skips), before the GREEN commit; the touched suites again after the judgment fix.
- ruff and black clean on every touched file; pre-commit 9/9 on both commits. No `src/intelligence/research` or `statistics` edit, so repro_frozen does not apply.

## Dry run (default scopes, 2026-10-08 04:05 UTC)

`--dry-run --dry-run-out logs/189-10_task1_dryrun.tsv`. Verified in the code first: `execute()` returns after `_dry_run`, which calls only `prepare()` (config, lane keys, coverage, request and canonical reads, the parity eligibility read); the provider factory and the lock are never constructed (the unit test asserts both).

3,024 candidate series, all queued, none held (the fetcher has not run since 2026-10-04, so every series is past its last close):

| Timeframe | Queued | Composition |
|---|---|---|
| 1d | 1,502 | positions 1 to 1,502 (all ahead of 5m). Due: 473 never_asked, 1,029 reconcile_due. Lanes: 875 update, 220 gap_fill, 407 backfill |
| 5m | 1,502 | positions from 1,503. 1,262 never fetched (1,082 backfill, 180 on their gap-fill session, both full depth); 240 with 5m: 200 update (3-day overlap), 34 gap_fill, 6 backfill (last fetch not ok) |
| 15m, 1h | 10 + 10 | parity sample, ISO week 2026-W41: A, COP, ELV, ETHA, EWZ, HON, HYG, PM, VRTX, XRT |

The 473 never-asked count matches the plan's 2026-10-07 figure. SLA band: 1,501 1d series and 238 5m series breach it; the 1d figure is the 1d ledger's stale `latest_timestamp` for Tradier-loaded names (deferred item 5: e.g. ASTS shows 2020-11-12), not missing data. It does not change the order (1d already ranks first) and clears as the daily stage refreshes the bounds of the names it derives.

## Deviations from plan

1. [Rule 3 - Blocking] `_history_fetch_item.py` edited although the plan says it does not: the record planner never asks a stored slot, so the 5m overlap, the full-depth re-fetch and the waived writer cannot exist without the item planning them. `gap_days` left `fetch_item`'s signature (a short start no longer forces the full window; the gap-fill lane does); the item tests lost that argument.
2. [Rule 2 - Missing critical functionality] `services/ohlcv_ingress_contract.py` gained `waived` and `_history_fetch.py` the waived grid writer: a full-depth 5m re-fetch after a split changes every stored row, so without a waiver the contract always refuses it (ratio about 1 over at least 500 stored rows). The waiver is the one D2 already applies (a recorded corporate action) and every changed row is still recorded.
3. [Interpretation] The amendment's "any restated row escalates" applies to 1d only. For 5m, IBKR's routine restatement of 15 to 40 recent rows a name would escalate every name every night to about 49 requests; those rows are written and recorded in `ohlcv_revision` by the contract (the existing revision path), and only a median close ratio outside tolerance escalates.
4. [Interpretation] A 5m breach without a recorded corporate action is not re-fetched: the contract would refuse the rewrite, so the about 49 requests would buy nothing. It is an integrity fact (`bar_split_detection`, `unexplained_overlap_difference`), the summary records `unwaived_overlap_breach`, and the run is partial.
5. [Simplification] `infra.bar_derivation.overlap_sessions` renamed rather than a second key added (its only reader was the fetcher); the `--overlap-sessions` CLI override stays.
6. [Interpretation] The two "_days" keys count sessions: the reconcile interval completed NYSE sessions, the gap-fill interval weekday sessions. Their descriptions say so.
7. [Scope] `services/split_detection.py` split into a read and a judge so the fetcher can judge pairs and record in-process; `detect_overlap_splits` keeps its behavior (its tests pass unchanged).
8. [Scope] The weekly parity sample is built although the coordinator's Task 1 outcome list omitted it: the plan says all text other than the amendment is unchanged, and its must_haves and behavior list keep the sample.
9. [Deletion] `last_session_close` had no caller left; replaced by `completed_session_closes` and its test.
10. [Rule 1 - Bug] A failed 1d overlap judgment (for example find_seams rejecting unusable pairs) raised out of the run and skipped the daily stage for every touched name. It now logs, sets the escalation code 1 (partial) and the daily stage still runs, as when split detection was a subprocess. Test added.
11. [TDD note] The migration file was written before its contract test first ran, so the contract test's RED came only from the missing `fq.LANE_KEYS`; one test-helper bug (stripping the quote before the provenance tag) was fixed in the test, not the migration.
12. [Housekeeping] Todo 507 closed (moved to completed with a Closed section; PRIORITIES row and the Data critical-path row updated); link integrity passes. Deferred item 6 is resolved by migration 451 but the 189 `deferred-items.md` was not edited (other sessions were told never to stage it).

## For Task 1b (before the first live IBKR request)

Code facts Task 1b relies on:
- Named `--symbols` runs bypass every hold (no daily rule, no current hold), get no parity sample, and a never-asked 1d series plans its full depth (lane `backfill`): one request a name, since `infra.ibkr.chunk_days.1d` is 7300 and `infra.backfill.depth_days.1d` is 7300.
- The refresh step's split handling is in-process now (todo 507's gate is met): a split found in the overlap is recorded, re-fetched and derived in the same run.
- A default (timer) run would also queue all 473 never-asked names first, so Task 1b's names are not at risk of starvation even if the order changes.
- Not checked here: that `get_active_contracts(settings, dimension="backfill")` selects the 27 names outside compute_1d (Task 1b's own confirmation step).

What the owner needs to do or decide:
1. Gateway login: Task 1b is the first IBKR request since 2026-10-04. The `ib-gateway` container must show a completed login (`docker logs ib-gateway`); a pending 2FA prompt needs a human (todo 395). The executor can probe SPY on a spare client id once the login is complete.
2. Open decisions that Task 1b's d2-v2 apply exercises: todo 508 (stale Tradier heads; option 1 recommended and recorded) and todo 511 (ISLAND head rule; its APR switch is off). Confirm the recorded recommendation stands or say otherwise before the `--apply` step; the dry run's "changed 0 and removed 0" check gates the apply either way.
3. Not a Task 1b gate but next: todo 505 (5m pacing ceiling) must be measured before Task 2's criterion is judged; with the overlap the nightly 5m slice stays one request a name, so 505's arithmetic is unchanged.

## Known stubs

None.

## Threat flags

| Flag | File | Description |
|------|------|-------------|
| threat_flag: write-contract waiver | services/ohlcv_ingress_contract.py | `waived=True` lifts the revision refusal for a chunk. Only `_insert_market_data_rows_waived` passes it, only the fetcher's escalation re-fetch uses that writer, and only after `_WAIVER_SQL` finds a corporate action recorded after the series' last applied ingress load; every changed row still goes to ohlcv_revision and the load row names the waiver |

## Self-Check: PASSED

- FOUND: production/migrations/451_fetcher_reconcile_and_parity_apr.sql, tests/unit/test_fetcher_reconcile_parity_migration_contract.py, .planning/todos/completed/507-split-refetch-in-process-under-the-fetcher-lock.md, logs/189-10_task1_dryrun.tsv (untracked, ignored)
- FOUND commits: 08126bf98, 714683f0d
- Live: the four new keys and the renamed key in config_state; no infra.bar_derivation.overlap_sessions row
