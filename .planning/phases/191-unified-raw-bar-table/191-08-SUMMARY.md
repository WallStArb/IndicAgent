---
phase: 191-unified-raw-bar-table
plan: 08
subsystem: database
tags: [ohlcv_raw, bar_derivation, daily-rule, d2-v3, gap-planner, equivalence]

requires:
  - phase: 191-07
    provides: last-wins raw (D-191-N), selection gate, session choices
provides:
  - daily stage (d2-v3) and grid stage read ohlcv_raw; no ohlcv_observation or archive read or write
  - shared raw 1d input read (read_daily_inputs) used by the daily stage, D7, ops_source_policy and two research scripts
  - per-symbol equivalence check of the daily rule over raw against stored canonical 1d, with a reviewed allow-list
  - todo 535 items 6, 10, 15 and 26 closed
affects: [191-09, 191-10, 191-16, 191-17, fetcher resume]

tech-stack:
  added: []
  patterns:
    - "Raw-to-rule boundary: daily_rule.observation_from_raw maps one current raw row to the rule's Observation (fetched_at = served_at, legacy from the request route); the rule is unchanged"
    - "A canonical row the stage did not write fails it loud (vendor 15m/1h row in canonical)"

key-files:
  created:
    - scripts/ops/bars/ops_d2_raw_equivalence.py
    - tests/unit/scripts/test_ops_d2_raw_equivalence.py
    - .planning/phases/191-unified-raw-bar-table/191-D2-EQUIVALENCE-EXPLAINED.json
  modified:
    - services/bar_derivation.py
    - src/intelligence/bars/daily_rule.py
    - services/bar_reconciliation_audit.py
    - scripts/infrastructure/backfill/_d1_gaps.py
    - scripts/ops/bars/ops_source_policy.py
    - scripts/research/vendor_basis_study.py
    - scripts/research/swap_1d_primary_measure.py
    - tests/unit/test_market_data_ohlcv_boundary.py
    - tests/unit/test_ohlcv_intraday_raw_archive_writer_boundary.py
  deleted:
    - services/intraday_raw_archive.py
    - tests/unit/services/test_intraday_raw_archive.py

key-decisions:
  - "Daily rule reads raw (tradier consolidated, ibkr smart_trades); venue kinds stay out as d2-v3 has always excluded venue routes; the rule itself is unchanged"
  - "D-191-D pairing is not part of d2-v3: the rule reads TRADES only, so no TRADES/ADJUSTED_LAST pair exists here; the pairing function and its tests belong to plans 09 and 10"
  - "--changed-only keys on raw served_at, which moves only when a value changes; an unchanged re-serve no longer re-derives a name"
  - "1d gap coverage is withdrawn only by a transport failure (timeout or failure with error text), not by every failure and not by requiring every route: measured 346,491 and 101,615 spurious gap sessions for the stricter rules, 2,467 (KNSL, the real hole) for this one"
  - "Intraday planner drops slots whose bar has not ended by now; the leaf's forming-bar drop alone did not close todo 535 item 10"
  - "bar_derivation units are not resumed here (hard rule of this run); bar-derivation.service had resume_action none at window open"

requirements-completed: [R-191-06]

duration: about 3h
completed: 2026-10-15
---

# Phase 191 Plan 08: daily stage over raw summary

**The d2-v3 daily stage and the 15m/1h grid read `ohlcv_raw`; the rule over raw reproduces canonical 1d digest-for-digest on 1,460 of 1,502 names, and the 42 others derive identically from raw and from the old observation read (canonical is behind serves after 2026-10-11, not a cutover effect).**

## Performance

- Started: 2026-10-15 about 10:20 UTC (resumed after a usage-limit stop with no work lost)
- Completed: 2026-10-15 about 13:30 UTC
- Tasks: 2 of 2, plus todo 535 items 6, 10, 15 and 26
- Files: 3 created, 2 deleted, about 20 modified

## Accomplishments

- Daily stage: `_SELECT_DAILY_RAW_SQL` reads the current raw 1d rows of `daily_rule.RAW_DAILY_SERIES` (tradier consolidated, ibkr smart_trades); test callers are excluded through `request_id` to `ohlcv_request.caller`, and a NULL `request_id` is no test row; `legacy` comes from the request route `LEGACY_IMPORT`. `observation_from_raw` is the one mapping; a raw row without `served_at` raises.
- `read_daily_inputs` and `read_daily_params` are shared: D7 (`bar_reconciliation_audit`), `ops_source_policy` and the research scripts `vendor_basis_study` and `swap_1d_primary_measure` read the same inputs the stage derives from. Without this they would have broken on import; D7 stays held until plan 09.
- Grid stage: the archive INSERT, archive_segment revisions, vendor verify and delete are gone. There are zero vendor 15m/1h rows in canonical (checked live), and one now fails the symbol loud. `services/intraday_raw_archive.py` is deleted, and the archive writer allow-list is empty (the table is read-only until 191-16).
- Item 26: the grid's answered-window read corroborates `bars` answers on the answering vendor's raw rows and excludes windows whose load was refused, the gap planner's rule. `infra.selection_gate.request_load_match_s` is required from APR.
- Known cases: all five d2v2 fixture cases (RJF, REX, DAL, ETHA, INDA, splits included) derive identically from raw-shaped inputs built as the 1d backfill built raw.

## D2 raw equivalence result

`ops_d2_raw_equivalence.py --all --allowlist 191-D2-EQUIVALENCE-EXPLAINED.json` exits 0.

| Class | Names | Dates | Explanation |
|---|---|---|---|
| equal over the whole series | 4 | | |
| equal over the stored span (digest) | 1,460 | | canonical holds exactly the rule over raw |
| rule_only_after_stored_end | 1,498 | 1,518 | sessions after the name's last stored canonical date; canonical 1d stops at the cutover (last daily run 2026-10-11 06:15 UTC), raw holds IBKR through 2026-10-12 |
| rule_only (in span) | 40 | 25,945 | IBKR head and history served after the name's last applied daily load |
| value | 2 | 1,980 | CTVA (held, bar_hold: never rewritten) and GYRE (250 values re-served after the load) |
| stored_only | 1 | 5 | UNIT: IBKR re-served 2,853 values from 2015-04-27 on another scale (45.63 against Tradier 27.61) on 2026-10-12 22:48; the seam test now refuses the five ibkr_fallback head dates 2015-04-20..24 |
| rule errors | 0 | | |

All 42 in-span differing names were re-derived from `ohlcv_observation` as well: 0 dates differ between the rule over observations and the rule over raw. Every rule-only date was served after the name's last applied daily load. No difference comes from the cutover. Per-symbol reasons are in the allow-list.

The stage's own dry run (`python -m services.bar_derivation --stage daily`, its default mode) over AAPL, MSFT, SPY, RJF and UNIT gives 0 changed and 0 removed on the four matching names, with only the post-cutover sessions new. UNIT has 5 removed (the explained head) at revision ratio 0.0017. `count(*)` of 1d canonical is 7,109,230 before and after.

## Task commits

1. Task 1, daily and grid stages over raw: `03ab0a4a6`
2. Task 2, equivalence check and allow-list: `4279340f9`; integration tests: `a8c5a7689`
3. Todo 535 items 6, 10, 15: `85dd6537b`, item 6 rule replaced on measurement: `cbbc7386b`

## Todo 535 items

- Item 6 (any single route's no_data covers a 1d session): the recommended fix was all routes no_data in one run, the empty-history rule. Measured over the 518 names with an IBKR 1d no_data answer, it added 346,491 gap sessions, nearly all pre-listing heads: venues are rarely asked about a head, and ISLAND fails structurally for non-NASDAQ names. Withdrawing coverage on any failure added 101,615 sessions on 64 names; those failures carry no error text and recur on every ask (ISLAND unlisted, SMART pre-listing windows such as ELE and CHRD). The final rule withdraws coverage only for a transport failure (timeout, or a failure with error text) its route has not answered later. Live effect: 2,467 sessions on KNSL, whose ISLAND, AMEX and BATS walks over 2006-10-09..2016-07-28 were lost to `ConnectionError: Not connected` under SMART and ARCA no_data. That is exactly the hole item 6 describes, and it is asked once on resume.
- Items 10 and 15: the IBKR leaf's forming-bar drop (eeb0fb7c6) did not close item 10. An ask whose window ran past `now` still recorded the dropped slot as answered, and 15m/1h never re-ask it. `detect_gaps_from_record` now drops slots whose bar has not ended by `now`.
- Item 26: closed (above). The grid does not port `live_partials`: a slot served partial only affects a `partial_constituents` flag.

## Deviations from plan

### D-191-N adaptations (the plan predates last-wins)

1. **Pairing (D-191-D) not built here.** The plan asks for the served_at-ordering and same-run pairing, with unit tests, in the daily rule. d2-v3 reads TRADES only; ADJUSTED_LAST is no rule input and has no current-scale role (scale is judged by `corporate_action_current.recorded_at` and `evidence_request_ids`). Adding a pair would be a rule change that moves recorded verdicts. Plans 09 (D7) and 10 (dividend writer) carry the same pairing behavior and tests, so the function is built where it has a caller.
2. **No pending/held raw values exist.** Raw is the current value per key. The daily read takes it, with nothing to exclude or release.
3. **Revision-ratio refusal of the daily stage stays** (`should_refuse` remains only in the derivation stage, per D-191-N).

### Other deviations

4. **[Rule 3] Callers of the deleted observation SQL.** D7, `ops_source_policy`, `vendor_basis_study` and `swap_1d_primary_measure` imported `_SELECT_DAILY_OBSERVATIONS_SQL`/`_D2V2_ROUTES` from `bar_derivation`. They now use `read_daily_inputs`; the `TRADIER`+`SMART` callers filter out the corpus import as before. D7's 1d input read therefore moves to raw in this plan; its other reads stay for plan 09. `ops_source_policy._FIRST_OBSERVATION_SQL` still reads `ohlcv_observation` and is left for the "rest" step.
5. **Venue kinds not read.** The plan lists venue among the daily candidates. d2-v3 has never read venue routes (D-17), so reading them would change the rule.
6. **The grid stage reads no parity rows.** The plan says the grid reads vendor 15m/1h parity rows from raw. The grid stage never read parity; it only archived and deleted vendor rows from canonical. With 0 such rows live, the step is deleted and a vendor row fails loud.
7. **The d2v2 fixture is not rewritten.** The rule's input type is unchanged, so the fixture stays an observation extract. A new parametrized test collapses each case into raw rows exactly as the backfill did and requires identical output: bars, flags, refused interior, head, restated and stale-only.
8. **Units not resumed.** The plan's last step resumes the bar_derivation units; this run's hard rule forbids resuming held units. `indicagent-bar-derivation.service` had `resume_action: none` at window open. The 5-name check used the stage's default dry run, not `--apply`.
9. **Integration tests run with `--noconftest`.** The session fixture replays every migration into `indicagent_test`. The concurrent executor's migration 485 asserts on live data ("expected exactly the 80 superseded release offers") and fails there, which is not this plan's file. `indicagent_test` already had `ohlcv_raw` from an earlier replay.
10. **[Rule 1] Two stale live assertions fixed** in `test_d2_single_writer_live` (owned by this plan). The lineage rule version is `d2-v3` since 185-52, and `ibkr_named` bars are judged against the resolved policy row (default IBKR primary from 2026-10-07, migration 456), not only symbol rows.
11. **Grid live volume check scoped to IBKR-5m sessions.** Its thresholds were measured when canonical 5m was IBKR. Alpaca sessions are another volume basis (D-191-N item 6), and over all sessions only 36% were within 1%. On IBKR sessions the aggregate rates pass. The per-name median still fails on CTVA (held), ETHA (ratio exactly 3.000 over 557 sessions, a share-basis mismatch) and MDGL. Recorded as todo 535 item 30; the test stays strict.

## Verification

- Plan verify set: `test_bar_derivation_daily`, `_policy_change_sql`, `_grid`, `test_bar_write_no_first_write_wins`, `test_ohlcv_intraday_raw_archive_writer_boundary` all pass, plus `tests/unit/bars/`, `tests/unit/scripts/` and the boundary and registry tests.
- `grep -nE "(FROM|JOIN|INTO|COPY)\s+(ohlcv_observation|ohlcv_intraday_raw_archive)" services/bar_derivation.py src/intelligence/bars/daily_rule.py` is empty.
- `git diff --stat -- src/intelligence/research src/intelligence/statistics` is empty (no repro_frozen needed). No fingerprinted batch writer was live or resumable (only `compression_auditor` and `feature_vector_writer` were running).
- Integration (live): `test_d2_single_writer_live` and `test_d2_excludes_test_caller_observations` pass; `test_derived_grid_live` passes except the item 30 per-name volume check.
- Full unit suite: see the self-check.

## Held units remaining

All ten units in `logs/raw_cutover_window.json` stay held: the fetcher, reconciliation audit and dividend writer timers and services, plus the bar aggregator, auditor, derivation and writer. None was resumed.

## Owner attention

- UNIT: IBKR re-served its 1d history from 2015-04-27 on a scale about 1.65 times Tradier's on 2026-10-12. The next daily apply removes the five 2015-04-20..24 fallback bars (ratio under the refusal limit). It looks like a corporate action IBKR applied, and the restatement detector should show it.
- ETHA: the 1d to 5m volume share basis differs by exactly 3 (todo 535 item 30).
- Canonical 1d is behind on 42 names until the daily stage applies again (held with the window).

## Known stubs

None.

## Self-check: PASSED

- Files: the equivalence script, its tests, the allow-list and this summary exist; `services/intraday_raw_archive.py` is deleted.
- Commits: `03ab0a4a6`, `4279340f9`, `85dd6537b`, `cbbc7386b`, `a8c5a7689` exist.
- Full unit suite on the final state: one failure, `tests/unit/scripts/test_ohlcv_history_fetcher.py::test_the_1d_judge_reads_the_split_rule_keys_and_acts_through_ops_split_detect`. That test and `ohlcv_history_fetcher.py` were uncommitted work of the concurrent 191-07 review-fix executor at the time; the test passes when rerun alone. Not this plan's files.
