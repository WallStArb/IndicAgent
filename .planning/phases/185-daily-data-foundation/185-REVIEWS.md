---
phase: 185
reviewers: [grok-4.7-g1, grok-4.7-g2, grok-4.7-g3, grok-4.7-g4]
reviewed_at: 2026-09-29T21:00:00Z
plans_reviewed: [185-01-PLAN.md, 185-02-PLAN.md, 185-03-PLAN.md, 185-04-PLAN.md, 185-05-PLAN.md, 185-06-PLAN.md, 185-07-PLAN.md, 185-08-PLAN.md, 185-09-PLAN.md, 185-10-PLAN.md, 185-11-PLAN.md, 185-12-PLAN.md, 185-13-PLAN.md, 185-14-PLAN.md, 185-15-PLAN.md, 185-16-PLAN.md, 185-17-PLAN.md, 185-18-PLAN.md, 185-19-PLAN.md, 185-20-PLAN.md, 185-21-PLAN.md, 185-22-PLAN.md, 185-23-PLAN.md, 185-24-PLAN.md]
external_reviewers: gsd-review has no Grok CLI. This session is Grok inside Cursor, which the workflow skips as SELF_CLI=cursor. Substitute: four fresh-context Grok 4.7 passes, one plan group each, shared gsd-review prompt. Synthesis: 185-REVIEW-GROK.md.
---

# Cross-AI Plan Review — Phase 185

Fresh pass on 2026-09-29 after the plan update. The 2026-09-27 review's HIGH (plan 12's objective forbade the pipeline cut-over) is closed in the current objective. Reviewers were not shown that file.

Groups:

- G1: 185-01 through 185-06
- G2: 185-07 through 185-12
- G3: 185-13 through 185-18
- G4: 185-19 through 185-24

The parent session confirmed the migration collision against `production/migrations/` (`384`–`388` exist as phase 186 files) and the plan-09 / plan-18 quotes before writing the synthesis.

## G1 Review — Grok (plans 01–06)

### Summary

Plans 185-01 through 185-06 form a coherent Wave 1–2 foundation: known-answer fixtures and write-rate measurements, an append-only 1d observation store with COPY writer and roles, provider request/observation callbacks, a quarantine side table wired into `market_data_ohlcv_tradeable`, pure D2a scrub rules with a D-11 corroboration ceiling, and session-anchored 15m/1h aggregation plus a bar content digest. They respect the project bar (no OHLCV UPDATEs for quarantine, tradeable read boundary, APR for scrub thresholds, IBKR-only prices, intraday raw store deferred). The main defects are an internal inconsistency in 185-02’s APR seed count/acceptance SQL, stale file line citations that would mislead a re-executor, a wrong anti-join EXPLAIN proxy cardinality in 185-04, and `depends_on` that understates the ROADMAP wave gate.

### Strengths

- Quarantine is a side table + view anti-join, never an UPDATE of `market_data_ohlcv`; 185-04 explicitly forbids `decompress_chunk` and notes VACUUM is N/A when no decompress happens.
- D1 is append-only with triggers, COPY-only writer, `SET LOCAL ROLE`, and an integration test that refuses cross-role INSERT and proves UPDATE/DELETE/TRUNCATE raise.
- Intraday bars are rejected from `ohlcv_observation` (`ValueError`); request outcomes may be logged for any tf — matches D-02 / deferred intraday raw store.
- D-01 preserved: `source CHECK (source IN ('ibkr'))` with vendor as a future CHECK change, not a new price path.
- D-11 is concrete: `corroboration_max_clearable_ratio` below `magnitude_threshold`; `apply_cross_symbol_downgrade` in `price_sanity.py` ignores magnitude, so the ceiling in a new module is the right fix.
- D-13/D-14: reuse `classify_candidate_bar` unchanged; port return/gap flags as pure rules with parity tests; loud failures (callback re-raise, no silent fixture skips).
- D-15 tests cover half-day, DST, consecutive sessions, and fixture volume equality; digest includes quarantine state and excludes rule version deliberately.
- Deferred scope held: no D8, no vendor stage, no todo 438, no intraday observation store.

### Concerns

- **HIGH (185-02):** APR seed count and acceptance SQL disagree with the interfaces list. Interfaces name four keys (`infra.bar_campaign.client_ids`, `infra.ibkr_history_lease.nightly_wait_minutes`, `infra.ibkr_history_lease.priority_wait_minutes`, `infra.ohlcv_observation.copy_batch_rows`), but Task 1 says “Seed the five APR keys” and acceptance requires a count of 5 on a WHERE that excludes both lease keys. (Live `380_ohlcv_observation_store.sql` seeds exactly those four.) Parent note: plan 02 is checked off; this is stale plan text, not an open migration.
- **MEDIUM (185-04):** EXPLAIN proxy uses “567 status keys.” The view only hides `quarantine=true` rows (~67), not all 567 non-null statuses.
- **MEDIUM (185-01, 185-02, 185-03, 185-06):** Stale line citations vs the current tree (`_batch_utils.py`, `ibkr.py`, `aggregate_bars_from_1m`).
- **MEDIUM (185-05 / 185-06 vs ROADMAP):** Frontmatter `depends_on: ["185-01"]` only, while ROADMAP Wave 2 is blocked on Wave 1 completion.
- **MEDIUM (185-01 ↔ 185-04):** 185-01 says to export before plan 04’s migration. Wave-1 parallel start can invert that order. The export still works after 381.
- **LOW:** requirements tags overclaim D-12 (01, 04), D-20 (02), and D-15/D-24 (01 fixtures only).

### Risk Assessment

**MEDIUM** for a re-executor of completed plans. Architecture matches the bar. Parent disposition: treat the APR count as closed by migration 380.

## G2 Review — Grok (plans 07–12)

### Summary

Plans 07–12 are mostly coherent with CONTEXT for this slice: pure D0/D3/D5 helpers (07–08), session-level IBKR history lease replacing the nightly skip (09), quarantine-only scrub with no `market_data_ohlcv` DML (10), archive-checksum-before-delete D2b writer without live rewrite (11), and live grid cut-over with `systemctl is-active` (12, D-31). Spot-checks of named modules, migrations 380–383, `classify_candidate_bar`, and measured scrub counts hold. The load-bearing open issues are plan 12’s second archive writer and the `ObservationSink.flush` transaction trap. Plan 09’s objective/task split is closed in fact by `185-09-SUMMARY.md` (the lane’s next attempt loaded the lease; no kill was required).

### Strengths

- **09** encodes D-29/D-30: session advisory lock, fetch-process acquires, bulk/priority yield, nightly `failed_lease_timeout`, CI lease boundary.
- **10** keeps quarantine on `bar_quality_flag` only; known-answer counts match D-10.
- **11** archives with count/value checksum before `DELETE`, dry-run default, single-writer CI on `market_data_ohlcv`.
- **12** uses `systemctl is-active`, lane guard, cut-over before rewrite, `partial_constituents` with `quarantine=false`, masked-slot baseline before rewrite.
- **07–08** stay pure; migration 382 seeds the six `alpha.survivorship.*` keys.

### Concerns

- **HIGH (185-09):** Objective says the running process picks up the lease on its next attempt; task 4 says kill by pid. Parent disposition: LOW. The summary records the next attempt did load the lease (`lease:ibkr_history_stream:bulk:historical-pipeline:46`). Do not re-kill that holder.
- **HIGH (185-12):** Plan 11 and plan 12 task 1a both insert into `ohlcv_intraday_raw_archive`. No writer-boundary test for the archive.
- **HIGH (185-12):** Task 1b wants request rows and archive rows in one transaction. Live `ObservationSink.flush` requires an idle connection; an open transaction traps `SET LOCAL ROLE`. Calling `flush()` inside that transaction aborts the write or recreates the todo 462 race.
- **MEDIUM:** ROADMAP wave 4 blocks 12 on unfinished 13 and 14. Plan 12 `depends_on` is 09, 10, 11 only.
- **MEDIUM (185-10):** Task 1 creates `test_market_data_ohlcv_scrub_input_boundary.py` but the verify line does not run it.
- **MEDIUM (185-12):** The `partial_constituents` must-have can be read as “a flagged bar never enters the digest.” Later acceptance says the digest of a flagged bar equals the unflagged bar. The must-have should say the digest hashes OHLC and volume only.
- **LOW:** Stale line anchors in 09 and 12. `files_modified` on 09 omits the operations doc and STATE.md that task 4 edited (already committed via the summary).

### Risk Assessment

**HIGH** on plan 12’s archive writer and flush rule. The rest of 07–11 is checked off and holds.

## G3 Review — Grok (plans 13–18)

### Summary

Plans 13–18 correctly sequence the D3 study and head re-run, D1 bootstrap plus seam audit, the D-28 check, the D2 dry run, and the sole-writer cutover. They respect flag-never-delete, IBKR-only prices, research-lane gating, and lineage off the compressed hypertable. The hard defect is migrations 384, 385, and 386, already on disk from phase 186. Plan 16 builds a real D-28 checker and, while the research lane is held, only a hand-off for D-04. Plan 18’s verify still runs a test module the task deletes.

### Strengths

- Plan 13 mechanizes D-17 (pre-registration refusal, per-timeframe verdict, APR switches).
- Plan 14 dispositions match D-20; client 49 and the priority lease match D-29/D-30.
- Plan 15 keeps scrub reads on `market_data_ohlcv_scrub_input` and uses append-only `corporate_action`.
- Plan 16’s `ops_data_bar_check.py` is a loud D-28 gate; success text admits D-04 is incomplete until the hand-off lands.
- Plan 17 puts lineage in `canonical_bar_lineage`, dry-run before `--apply`.
- Plan 18’s writer fences, nightly `--changed-only` daily stage, and D-31 nightly-active check align with D-06/D-31.

### Concerns

- **HIGH (185-13, 185-15, 185-17):** `384_corporate_action.sql`, `385_venue_study_switches.sql`, `386_canonical_bar_lineage.sql` collide with live `384_market_regimes_duplicate_index_drop.sql`, `385_primary_key_inventory.sql`, `386_provenance_batch.sql`. Confirmed on disk by the parent session.
- **HIGH (185-16 / D-04):** With the research lane held, this plan does not put labels on attempts. Parent disposition: MEDIUM. The success line already says so. The `requirements` tag still lists D-04.
- **HIGH (185-18):** Task 1a deletes `test_request_coverage.py`; the verify line still runs it. Confirmed in the plan. Parent disposition: MEDIUM, because the failure is a red pytest, not a silent write.
- **MEDIUM (185-15):** Seam audit waits on D1 bootstrap, against D-27 step 2 / D-24.
- **MEDIUM (185-15):** Task 1 verify runs `test_market_data_ohlcv_boundary.py` instead of `test_market_data_ohlcv_scrub_input_boundary.py`. `requirements` lists D-22, which is plan 21’s writer.
- **MEDIUM (185-16):** Plans 17 and 18 do not `depends_on` 16. The sole writer can land while the data-bar check exits non-zero.
- **MEDIUM (185-17):** `volume: int | None` on `CanonicalBar` can write SQL NULL and drop a venue bar out of `market_data_ohlcv_tradeable` (`WHERE volume > 0` on the stored column).
- **LOW:** CONTEXT’s “384 late-starting names” vs plan 14’s measured 381. The plan is the one that recounts at run time.

### Risk Assessment

**HIGH** until 384–386 are renumbered with the rest of the block. D2 design (dry run, side-table lineage, sole-writer fences) is otherwise sound.

## G4 Review — Grok (plans 19–24)

### Summary

Plans 19–24 encode the late gates: D3 rebased onto D1, D4 as every-route `no_data`, intraday recovery refused until 186 unlocks it, D5 as an I/O-only dividend swap, nightly split overlap, D7 into `integrity_monitor`, and D6 close-out. Migrations `387` and `388` already belong to phase 186. Plans 20/22/23/24 reserve `389`–`392`, so renumbering only the collisions recreates them.

### Strengths

- Plan 19 retires the venue-fallback store return and derives empty history from recorded answers.
- Venue volume NULL-after-`volume > 0` matches migrations 374 and 381.
- Plan 20’s refusal matches 186-27’s unlock keys; `--check` must refuse today.
- Plan 21 freezes the dividend pure functions and `DisputeRule`, with `git diff --quiet` on `research/dividends.py`.
- Plan 22 chains split detect, re-fetch, and `--stage daily` inside the nightly with the priority lease.
- Plan 23 covers D-26’s checks without failing the job on findings.
- Plan 24’s `listing_venue` reuses the SCH-style guards and keeps todo 433 pending for gated intraday.

### Concerns

- **HIGH (19, 21):** `387_dividend_date_dispute.sql` and `388_venue_fallback_store_bars_retired.sql` collide with `387_feature_lifecycle_data_quality.sql` and `388_drop_ctx_tables.sql`. Confirmed on disk.
- **HIGH (cascade):** Upstream plans still claim 384–386. Next free is 389, already reserved by 20/22/23/24. One remap of all nine files.
- **HIGH (19):** “if false, no ibkr_venue rows exist” fails if any historical `store_bars=true` row remains. Parent disposition: MEDIUM. Use an unchanged-count baseline.
- **MEDIUM (21):** Near-miss rollback is in `execute()`, not `_reconcile`.
- **MEDIUM (20):** `depends_on` omits 12, but `--apply` calls `--stage grid`. Wave order usually covers it.
- **MEDIUM (23):** The masked-slot count 155,022 is a planning-day measurement. Gate on `185-12-SUMMARY`’s recorded baseline after the rewrite.
- **LOW (19):** `requirements` omits D-18 even though the tradeable volume check implements it.

### Risk Assessment

**HIGH** until 387–392 are remapped with 384–386 as one sequence past 388.

## Consensus Summary

Synthesis the parent session will hand to a replan: `185-REVIEW-GROK.md`.

### Agreed Strengths

- Quarantine is a side table. The tradeable view is the read boundary. Raw 1d observations are append-only. (G1, G2, G3)
- The lease replaced the nightly skip, and the running chain is already on it. (G2, confirmed in `185-09-SUMMARY.md`)
- Lineage stays off `market_data_ohlcv`. One 1d writer is fenced in plan 18. Intraday recovery does not start the phase 186 rebuild. (G3, G4)
- D-04’s success text is honest: labels are not on an attempt until the hand-off is applied. (G3; this closes the 2026-09-27 MEDIUM’s wording half)
- Plan 12’s objective now orders the cut-over. (G2; this closes the 2026-09-27 HIGH)

### Agreed Concerns

1. **HIGH — migration numbers 384–392.** G3 and G4 both found it. Parent confirmed `384`–`388` on disk as phase 186 files, and plans 13, 15, 17, 19, 20, 21, 22, 23, 24 still name `384`–`392`. Remap all nine onto `389`–`397` in one edit. Re-check immediately before `psql -f`.
2. **HIGH — plan 12 archive ownership.** G2 only (the other groups did not read plan 12’s tasks). Two insert paths into `ohlcv_intraday_raw_archive`, and `ObservationSink.flush()` cannot run inside the transaction that must commit the request with the bars. Name one insert function and ban `flush()` inside it before plan 12 executes.
3. **MEDIUM — plan 18 verify runs a file the task deletes.** G3. Confirmed in the plan text.
4. **MEDIUM — D-04 requirements tag vs the hand-off stop.** G3. Drop D-04 from plan 16’s `requirements`.
5. **MEDIUM — seam audit waits on D1.** G3, against D-27 step 2.
6. **MEDIUM — wave 4 blocks plan 12 on plans 13 and 14.** G2. D-15 does not need them.
7. **MEDIUM — NULL volume on a venue canonical bar drops it from the tradeable view.** G3. **MEDIUM — “no ibkr_venue rows exist” is too strict.** G4.

### Divergent Views

- G2 rated plan 09’s objective-vs-kill as HIGH. The parent read `185-09-SUMMARY.md`: the chain restarted onto the lease on its next attempt and the kill was not needed. Disposition: closed in fact, LOW as leftover wording. Do not re-kill the holder.
- G1 rated plan 02’s “five APR keys” as HIGH. Migration 380 seeded the four listed keys and the plan is checked off. Disposition: stale text on a completed plan.
- G3 rated plan 16’s hand-off and plan 18’s verify as HIGH. Parent disposition: MEDIUM. Both fail loud or are already stated in the success line. They do not write a wrong bar.

### Before the next unexecuted plan

1. Remap the nine migration filenames.
2. One writer function for the intraday archive, and no `flush()` inside its transaction.
3. Plan 18’s verify list matches the files that survive.
4. Remove D-04 from plan 16’s `requirements`.

To fold this into the plans: `/gsd:plan-phase 185 --reviews`
