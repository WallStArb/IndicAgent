# Grok review — Phase 185 (owner-run external)

**Reviewer:** Grok (Cursor session on `\\192.168.68.60\dev\indicagent`)
**Reviewed:** 2026-09-27
**Plans:** all 24 (`185-01` through `185-24`)
**Method:** same two passes as `186-REVIEW-GROK.md`. Consistency: `185-CONTEXT.md` (D-01..D-31, deferred list), the ROADMAP phase section, every plan's wave / `depends_on` / `requirements`, and the task text of the load-bearing plans (`04`, `09`, `10`, `11`, `12`, `16`, `17`, `18`, `19`). Council: one writer, one grid, flags that cannot hide a bar by accident, failures loud.

Plans and `185` research docs were not edited.

## Summary

The 24 plans will deliver the phase goal if the task text is followed: raw IBKR answers land in an append-only store, one derivation writes canonical 1d bars, quarantine is a side table the tradeable view anti-joins, and the 15m/1h grid readers see is computed from 5m. Every locked decision D-01 through D-31 appears in at least one plan's `requirements`. Deferred work (D8, a vendor source, an intraday raw store, todo 438) is not pulled in. The dependency graph is acyclic and every wave number is one past the latest dependency wave. One instruction contradicts its own task and can leave two 1h grids in the table readers use. That is the defect to fix before execution. The rest is schedule coupling and a label that does not land on the attempt until another lane applies a hand-off.

## Strengths

- Flag, never delete, is structural. `bar_quality_flag` is an uncompressed side table. `185-10` forbids `INSERT`/`UPDATE` of `market_data_ohlcv` from the scrub path. The known-answer set (45 unflagged corrupt bars, 27 Flash Crash clears, 15 legacy rows, 1,864 edge bars that must stay) is a stop, not a report.
- Venue volume is already the right predicate. Migration 374 filters `WHERE volume > 0` on the stored column, then projects `volume` as NULL when `source = 'ibkr_venue'`. Recovered bars stay in the tradeable view. Their volume cannot be summed as SMART volume. `185-19` checks that.
- Lineage does not widen the compressed hypertable. `185-17` states that no provenance column is added to `market_data_ohlcv`. `canonical_bar_lineage` holds rule version and request ids. `185-18` makes the derivation the only 1d writer and fences the other writers in CI.
- The grid switch keeps the raw bars. `185-11` archives stored IBKR 15m/1h, checks count and value checksum inside the same transaction, then deletes that segment and writes `derived_5m`. Synthetic fills are not archived. Readers of the canonical table see one grid per symbol.
- The lease replaces a silent skip. `185-09` deletes the nightly `pgrep` path. A leg that cannot get the stream fails with `failed_lease_timeout` and an integrity fact. The lock is session-level, so a dead process cannot hold it.
- D-11 is a known answer, not a comment. Cross-symbol corroboration must not clear a print past the magnitude threshold. The Flash Crash date is in the fixture the historical pass must quarantine.

## Concerns

- **HIGH — `185-12` tells the executor two opposite things about the running pipeline.** The objective says the 1h/15m expansion lanes are never stopped; their names are excluded from the rewrite. Task 2 says to kill the pipeline process, the same way `185-09` task 4 does, before the rewrite, so no process is still running the pre-plan-12 code. That second cut-over is the one that matters. Plan 09 restarts the chain onto the lease. Plan 12 then changes the same file so 15m/1h writes go to the archive. A process restarted at plan 09 still has the old store path. If it keeps running, it inserts IBKR 15m/1h into `market_data_ohlcv` after derived rows exist. The live check looks for both `:00` and `:30` in one session. A writer that starts after the check, or a symbol the lane guard excluded and then finishes on old code, puts the second grid back. Readers of the tradeable view then mix session-anchored derived bars with IBKR's own clock. Phase 186's rebuild consumes that table. Follow task 2. Delete the objective sentence.
- **MEDIUM — D-04 is a hand-off, and the phase can close without it.** `185-16` writes `load_label_inputs` and a data-bar check. The S0 manifest and runner evidence (rule version, digests, the data-quality block) are edited only if STATE.md shows the research lane released. Otherwise the plan writes `185-S0-HANDOFF.md` and stops. Attempts are paused until 185 and 186 land, so nothing is mislabeled today. The decision says every attempt carries the labels. A markdown file does not. The data-bar check should stay a hard gate in front of the next attempt, owned by whoever applies the hand-off, and `185-16`'s success line should say the labels are not on the runner until that happens.
- **MEDIUM — migration numbers 380–392 collide with phase 186 wave 1.** This phase names `380_ohlcv_observation_store` through `392_listing_venue`. `186-05`, `186-06`, and `186-09` still describe 380 as the next free number after 379, with a re-check at write time. Parallel worktrees can take the same number between the check and `psql -f`. Same note as the 186 review. The rule is already "next free." It has to be re-checked immediately before apply, on both phases.
- **MEDIUM — `market_data_ohlcv_scrub_input` shows quarantined bars and has no reader fence.** The view is for the scrub and seam stages, and the comment says so. It is granted to `bar_derivation_writer` and is not added to the raw-table allow-list, because it is not the raw table. A later script that selects from it treats flagged bars as eligible. The tradeable view is the boundary that makes D-09 true. This view is a hole beside it. A CI grep, the same shape as the raw-table boundary, limited to the scrub and seam modules, closes it.
- **LOW — dropping a scrub rule does not clear its flags.** `write_flags` deletes and reinserts only the rules that run evaluated. A full pass replaces those. A later run that stops evaluating a rule leaves that rule's quarantine rows in place, and the view keeps hiding the bars. Raw rows are safe. The hide is not. A full pass should delete flags for rules no longer in the evaluated set, for the span it covers, and log the count.

## Suggestions

- In `185-12`, replace the objective sentence "lanes are never stopped" with the task-2 cut-over: kill the pipeline by pid, sweep orphans, terminate leftover backends, let the lane loop resume on the new code, then rewrite. The lane guard still excludes symbols a new process is writing.
- In `185-16`, state that D-04 is unmet until the research lane applies the hand-off, and name the data-bar check as the gate that attempts 3, 3b, and 4 must pass.
- In `185-02` (first migration) and `186-05`/`186-06`/`186-09`, one shared sentence: the other phase may have consumed the number; re-check after the file exists and again immediately before `psql -f`.
- Add `market_data_ohlcv_scrub_input` to a reader allow-list: scrub, seam, and their tests only.

## Risk assessment

**MEDIUM, one HIGH.** The HIGH is an instruction conflict on the only step that keeps a single 15m/1h grid. Executed as task 2 is written, the phase does not write a silent second grid. Executed as the objective is written, it does, and phase 186 will rebuild features on it. The quarantine design, the venue-volume projection, the lineage side table, and the lease are the right architecture and should not be reopened.

## Cross-plan checks

- **Coverage.** D-01..D-31 each appear in some plan's `requirements`. D8, stage V, the intraday observation store, and todo 438 do not.
- **Waves.** `depends_on` matches the ROADMAP. Wave number is `max(dependency wave) + 1` for all 24. Plan 12 is wave 4 and plan 13 is wave 3; IDs are not execution order.
- **D-27 order.** The 1d re-run (`185-14`), the venue study (`185-13`), and the scrub pass (`185-10`) do not wait on a full D1 bootstrap. They wait on the lease (`185-09`) where they fetch, which is D-29, not a hidden dependency on D1 contents. The seam audit (`185-15`) waits on a fresh TRADES fetch in D1. That is a data dependency, not a violation of "the audit can be computed without the derivation."
- **Single 1d writer.** `185-17` dry-runs. `185-18` moves the backfill to D1-only and fences `backfill_feature_factory`, `bar_writer`, `bar_auditor`, and the cleanup script. `185-19` re-derives moved names through that stage only when the study switch is on.
- **186 hand-off.** `185-12` records in STATE.md that D2b has landed and how many symbols still lack 5m. `185-20` stores recovered intraday only behind the content-digest gate and does not start the 186 rebuild.
- **Research lane.** No plan edits `src/intelligence/research/` except `185-16`, and only when the lane has released. `185-21` checks `git diff` empty on `research/dividends.py` and leaves the dispute-window reader change as a hand-off.

## Council pass (one grid, one writer, flags that fail loud)

Same standard as the 186 council pass. One direction of flow. A reader either sees a bar or does not, for one reason. A second clock in the table readers use is a wrong answer, not a scheduling note.

### What already matches

Raw observations are permanent: D1 is append-only, and stored 15m/1h are archived with a checksum before they leave `market_data_ohlcv`. Canonical 1d has one writer. Quarantine does not update the compressed hypertable. The tradeable view is the read boundary, and venue volume is nulled in the projection after a real `volume > 0` filter, so recovered history is visible and its volume is not usable. The nightly can no longer skip a day without a failed status. None of that should be redesigned.

### The defect

`185-12` is about to make derived 15m/1h the only bars in the table phase 186 rebuilds from. The running todo 449 process is the other writer of those rows. Excluding its symbols from one rewrite does not change the code that process has loaded. When it next stores a 15m or 1h bar, it uses the binary it started with. After plan 12 is merged, that binary is the wrong writer.

The task already specifies the cut-over. The objective forbids it. A desk that has watched a stale process keep writing after a code change does not leave both sentences in the plan. One writer means one process image.

The check that fails the plan if any session has both `:00` and `:30` 1h bars is the right alarm. It has to be rerun after the lane has resumed and written at least one symbol on the new code, not only at the end of the rewrite. Otherwise the alarm fires before the old process has had a chance to prove it is gone.

### What not to add

Do not put rule version or request ids on `market_data_ohlcv`. The side table is the lineage. Do not delete quarantined bars. Do not start a second IBKR history stream to "go faster"; the lease is the measurement. Do not block the scrub pass on D1. The known-answer flags are a property of the bars already stored.

### Before execution

1. One sentence in `185-12`: the running pipeline is cut over onto the archive path before any symbol is rewritten, and the mixed-minute check is repeated after that process has written.
2. D-04's success condition is the hand-off applied, not the hand-off written.
3. `market_data_ohlcv_scrub_input` grows a reader allow-list before anyone imports it out of habit.
