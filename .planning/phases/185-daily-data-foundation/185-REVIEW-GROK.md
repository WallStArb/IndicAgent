# Grok review — Phase 185 (fresh pass after the plan update)

**Reviewer:** Grok 4.7, four fresh-context passes (plans 01–06, 07–12, 13–18, 19–24), synthesized here
**Reviewed:** 2026-09-29
**Plans:** all 24 (`185-01` through `185-24`), current text
**Method:** gsd-review prompt (summary, strengths, concerns, suggestions, risk) against `185-CONTEXT.md` D-01..D-31, the ROADMAP phase section, and spot-checks of cited files. Prior file (2026-09-27) was not shown to the reviewers. Council: one writer, one grid, flags that cannot hide a bar by accident, failures loud.

Plans were not edited.

## What changed since 2026-09-27

The previous HIGH is closed in the text. `185-12`'s objective no longer says the expansion lanes are never stopped. It now orders the cut-over: kill the pipeline by pid, sweep orphans, terminate leftover backends, let the lane resume, then rewrite. `185-16`'s success line now says D-04 is not met until the research lane applies the hand-off.

The new defect is numbering. Phase 186 has already landed migrations `384` through `388`. Unexecuted plans 13, 15, 17, 19, and 21 still name those numbers in `files_modified`. Plans 20 and 22–24 reserve `389`–`392`, which is where a naive renumber of the earlier files would land. One remap of all nine files, then a re-check immediately before `psql -f`.

## Summary

Waves 1–2 and plans 10–11 are the right architecture and are already checked off: append-only D1, quarantine as a side table, the tradeable view as the read boundary, the session lease, and archive-with-checksum before the stored 15m/1h leave `market_data_ohlcv`. The remaining plans will deliver the phase goal if the migration filenames are renumbered before anyone creates a file, and if plan 12 names a single insert path into the intraday archive and does not call `ObservationSink.flush()` inside the transaction that is supposed to commit the request and the bars together. Everything else is a verify command, a requirements tag, or a schedule coupling. Deferred work (D8, a vendor source, an intraday raw store, todo 438) stays out.

## Strengths

- Flag, never delete, is structural. `bar_quality_flag` is a side table. Plan 10 forbids `INSERT`/`UPDATE` of `market_data_ohlcv` from the scrub path. The known-answer set is a stop.
- The lease replaced the nightly skip, and plan 09's summary records the cut-over: the todo 449 process restarted onto the lease on its next lane attempt (pid 1883343, `lease:ibkr_history_stream:bulk:historical-pipeline:46` in `pg_stat_activity`). No silent skip remains in that path.
- Plan 11 archives stored IBKR 15m/1h with a count and value checksum in the same transaction, then deletes that segment. Synthetic fills are not archived.
- Plan 12's current objective matches its task: the running pipeline is cut over before any symbol is rewritten, the nightly is checked with `systemctl is-active`, and `partial_constituents` is `quarantine=false` so a partial bar stays visible.
- Plan 17 keeps rule version and request ids on `canonical_bar_lineage`, not on the compressed hypertable. Plan 18 fences the other 1d writers. Plan 20 refuses intraday recovery until phase 186 writes the unlock keys, and it does not start that rebuild.
- Plan 21 freezes the dividend pure functions and hands disputed spanning returns to the research lane instead of editing `src/intelligence/research/dividends.py` while that lane is held.

## Concerns

- **HIGH — migrations 384–388 are already phase 186's files.** On disk: `384_market_regimes_duplicate_index_drop.sql`, `385_primary_key_inventory.sql`, `386_provenance_batch.sql`, `387_feature_lifecycle_data_quality.sql`, `388_drop_ctx_tables.sql`. Still named in plans: `384_corporate_action` (15), `385_venue_study_switches` (13), `386_canonical_bar_lineage` (17), `387_dividend_date_dispute` (21), `388_venue_fallback_store_bars_retired` (19). Each objective says "next free if taken." `files_modified` does not. An executor who creates the named path fails the migration-number uniqueness check, or, if they ignore it, writes the wrong SQL under a taken number. Plans 20, 22, 23, and 24 already claim `389`–`392`. Renumbering only 13/15/17/19/21 into that range collides again. Next free after 388 is 389. All nine files move together.

- **HIGH — `185-12` grows a second writer of `ohlcv_intraday_raw_archive` and a transaction that fights `ObservationSink.flush`.** Plan 11's derivation inserts archived IBKR 15m/1h. Plan 12 task 1a also routes pipeline fetches into that table. There is a writer-boundary test for `market_data_ohlcv` and none for the archive. Task 1b requires the `ohlcv_request` row and the archive rows in one transaction, with `SET LOCAL ROLE` in sequence. The live sink refuses `flush()` on a connection that is not idle, because an open transaction would trap `SET LOCAL ROLE`. An executor who calls `flush()` inside that transaction either aborts the write or recreates the todo 462 race: a recorded answer with no bars. One insert function, and an explicit ban on `flush()` inside the helper's transaction.

- **MEDIUM — `185-18` task 1a deletes `tests/unit/scripts/test_request_coverage.py` and the verify line still runs it.** Acceptance says `_request_coverage.py` is gone. The automated verify includes `tests/unit/scripts/test_request_coverage.py`. A correct fold-in fails its own pytest. Loud, so it will not ship silently. The verify list should name `tests/unit/bars/test_gap_plan.py` and drop the deleted module.

- **MEDIUM — `185-16` still lists D-04 in `requirements` after its success line says the labels are not on an attempt.** `STATE.md` still has the research lane held, so the plan writes `185-S0-HANDOFF.md` and leaves `snapshot.py` and `runner.py` untouched. That is the right stop. The requirements tag will let a later reader mark D-04 done. Drop D-04 from this plan's `requirements`. The data-bar check stays the gate for attempts 3, 3b, and 4, owned by whoever applies the hand-off. Plans 17 and 18 do not `depends_on` 16, so the sole 1d writer can land while the checker still exits non-zero. That is acceptable only if nothing starts those attempts on the strength of 17 or 18.

- **MEDIUM — `185-15` runs the seam audit only after the D1 bootstrap.** D-27 step 2 and D-24 say the seam audit needs a fresh TRADES fetch and does not need D1. Plan 15 bootstraps D1, then audits, and depends on plan 14. Plan 16 depends on 15, so the data bar waits on the client-47 campaign. The audit can stay a direct fetch. The bootstrap stays D1.

- **MEDIUM — ROADMAP wave 4 blocks plan 12 on plans 13 and 14. Plan 12's `depends_on` is 09, 10, and 11.** D-15 does not need the venue study or the 1d head re-run. Following the wave text holds the phase 186 precondition behind two campaigns. Following `depends_on` ignores the wave gate. Pick one sentence and put it in both places: 12 starts when 09–11 are done; 13 and 14 are parallel.

- **MEDIUM — `185-17` allows `volume: int | None` on a canonical bar without saying a venue bar stores the fetched volume.** The tradeable view filters `volume > 0` on the stored column, then projects venue volume as NULL. A derived row written with SQL NULL volume never enters the view. Venue bars that should be visible have to store the provider volume. Only the view nulls it.

- **MEDIUM — `185-19` acceptance, if the study switch is false: "no ibkr_venue rows exist."** Any row already stored under the old `store_bars` path fails that check even when this plan correctly refuses to apply venue bars. The check is: no new canonical venue apply, and the `ibkr_venue` 1d count is unchanged from the pre-task baseline.

- **LOW — `185-02` still says "seed the five APR keys" and its acceptance counts a WHERE that misses the lease keys.** Migration `380_ohlcv_observation_store.sql` seeded the four keys the interfaces list. The plan is checked off. The text is stale. A re-executor who invents a fifth key to hit the count is inventing schema. Completed plans 01, 03, and 06 also cite line numbers that have moved (`ibkr.py`, `_batch_utils.py`, `aggregate_bars_from_1m`).

- **LOW — `185-09`'s objective still says the running chain picks up the lease on its next attempt, and task 4 still says kill by pid.** The summary records that the next attempt did load the lease code, and no kill was required. The contradiction is closed in fact. Leave the summary as the record. Do not re-kill a process that already holds `lease:ibkr_history_stream`.

- **LOW — `185-21` says to change `_reconcile` on a near miss.** The rollback lives in `DividendEventWriter.execute()`. Editing the pure `reconcile()` breaks the byte-identical must-have and misses the control point.

## Suggestions

- In one edit, point plans 13, 15, 17, 19, 20, 21, 22, 23, and 24 at migrations `389`–`397` (next free after `388`), same order as the current numbers `384`–`392`. State in each: re-check `ls production/migrations` after the file exists and again immediately before `psql -f`. Add the uniqueness test to each migration task's verify.
- In `185-12`, name one function as the only `INSERT` into `ohlcv_intraday_raw_archive`, used by both the derivation's archive-from-table path and the fetch path. Add a writer-boundary test of the same shape as `test_market_data_ohlcv_writer_boundary.py`. In task 1b, forbid `ObservationSink.flush()` inside the shared transaction.
- In `185-18`'s verify, drop `tests/unit/scripts/test_request_coverage.py`.
- In `185-16`, remove `D-04` from `requirements`.
- In `185-17`, one sentence: venue canonical rows store the fetched volume; `market_data_ohlcv_tradeable` is what nulls it.
- In `185-19` task 2, replace "no ibkr_venue rows exist" with the unchanged-count baseline.
- In the ROADMAP wave 4 line, say plan 12 is not blocked on 13 or 14.

## Risk assessment

**HIGH until the nine migration filenames move, then MEDIUM.** The HIGH is a filename collision with files that are already applied. It does not change the design. Executed as the tasks are written after that remap, the phase keeps one 1d writer, one 15m/1h grid in the table readers use, and quarantine off the compressed hypertable. The archive's second insert path is the remaining way to get two owners of a raw row during the live rewrite. Fix that sentence before plan 12 runs. Do not reopen the lease, the side-table quarantine, or the lineage table.

## Cross-plan checks

- **Coverage.** D-01..D-31 each appear in some plan. D-04 is claimed by 16 and then explicitly unmet while the research lane is held. D-20 is claimed early by 02 (request log only) and actually finished in 14 and 19. D-22 is claimed by 15 (the fetch) and finished in 21. D8, stage V, the intraday observation store, and todo 438 do not appear as work.
- **Waves.** Frontmatter wave numbers match the ROADMAP. `depends_on` is narrower than the wave gates: 05 and 06 depend only on 01 while wave 2 waits on all of wave 1; 12 does not depend on 13 or 14 while wave 4 does. IDs are not execution order (12 is wave 4, 13 is wave 3).
- **Prior HIGH.** Plan 12's objective and task 2 now agree on the cut-over. The mixed-minute check still has to be repeated after the resumed lane has written one symbol on the new code, not only at the end of the rewrite.
- **186 hand-off.** Plan 12 records in STATE.md that D2b has landed. Plan 20 stores recovered intraday only behind the content-digest unlock and does not start the rebuild.
- **Research lane.** No plan edits `src/intelligence/research/` except 16, and only when STATE.md shows the lane released. Plan 21 checks `git diff` empty on `research/dividends.py`.

## Council pass

One direction of flow. A reader either sees a bar or does not, for one reason. A second clock in the table readers use is a wrong answer. A migration file that reuses an applied number is a wrong answer of the same kind: the catalog says one thing and the plan says another.

### What already matches

Raw 1d observations are append-only. Stored 15m/1h are archived with a checksum before they leave `market_data_ohlcv`. Quarantine does not update the compressed hypertable. The tradeable view is the read boundary. The nightly can no longer skip a day without a failed status. The plan 12 objective now cuts the running pipeline over before the rewrite. None of that should be redesigned.

### The defect

Nine unexecuted migrations still wear numbers phase 186 has used. The prose escape hatch ("next free if taken") is not what `files_modified` tells the executor to create. A desk that has watched two phases share a checkout does not leave both the number and the escape hatch in the plan. One number, taken at file-creation time, checked again at apply time.

Beside that, plan 12 is about to make the archive the permanent store of IBKR 15m/1h while the derivation also writes it. Two insert sites and a flush that cannot run inside a transaction will either split the raw row from its request or fail loud in the middle of the rewrite. Name one writer before that plan starts.

### What not to add

Do not put rule version or request ids on `market_data_ohlcv`. Do not delete quarantined bars. Do not store NULL volume on a venue bar so the view can null it again. Do not start a second IBKR history stream. Do not block plan 12 on the venue study. Do not re-kill the lease holder that plan 09 already cut over.

### Before the next unexecuted plan

1. Remap migrations `384`–`392` in plans 13, 15, 17, 19, 20, 21, 22, 23, and 24 onto `389`–`397`, and re-check at apply time.
2. One insert function for `ohlcv_intraday_raw_archive`, and no `ObservationSink.flush()` inside its transaction.
3. Plan 18's verify list matches the files that survive the fold-in.
4. D-04 stays unmet in the requirements list until the hand-off is applied.
