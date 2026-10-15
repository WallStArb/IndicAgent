# Plan 191-07, third fix round: fresh-context review

Reviewer: fresh-context Claude (read-only), 2026-10-15
Scope: commits b8990554e..d9246c7a9 (`git log --oneline 6e7052b61..d9246c7a9`), D-191-N in
`docs/plans/2026-10-12-unified-raw-bar-table-design.md`, `191-07-FIXES.md` (third round),
`191-07-FIXES2-REVIEW.md`, todo 535. SQL ran read-only (`default_transaction_read_only=on`).

Status: complete.

## Findings (ranked)

### 1. HIGH: "latest" is write order, not serve time; an artifact replay reverts newer answers and stamps them as fresh

Evidence:
- `services/ohlcv_raw_writer.py` `_UPSERT_TAIL` replaces unconditionally (`ON CONFLICT ... DO UPDATE SET ... served_at = EXCLUDED.served_at`) and `_RAW_ROW` sets `served_at = now()` for every live write. No path compares the offer's serve time with the stored row's `served_at`.
- `scripts/ops/bars/ops_bar_load.py` -> `services/bar_load.load_frame` replays parquet artifacts from disk (`src/intelligence/bars/vendor_ingress.py`, default dir `data/scratch/alpaca-pilot/depth`, fetched days or weeks earlier) through `persist_chunk_atomically` -> `apply_raw_contract`. Its docstring says "Rerunning is idempotent". Under D-191-N that is only true while nothing newer was served: once the Alpaca nightly (`ops_bar_nightly`) re-serves a key with a corrected value, a rerun of the campaign loader writes the older artifact value back over it, logs the newer value as the "old" revision, and stamps `served_at = now()`, so raw now claims the stale value is the freshest answer.
- Before D-191-N the refusal caught a large reversion (share > 2% over 500 stored). Now the only signal is the detector's share flag, which nothing reads (finding 3), and a small reversion (a handful of corrected bars) is invisible.
- The one-time release (`ops_pending_release.py`) did decide by serve time, and `ops_raw_backfill.py` guards with `s.served_at > r.served_at`, so the code base already knows the right rule; the live writer does not apply it.
- Today no conflict exists in the data (the nightly has not run since the cutover; no vendor load reached raw in the last 30 days except the one-time tools), so this is latent, not realized.

Fix: give `write_raw` an explicit per-row `answered_at` (the request's answer time for the fetcher and nightly; the artifact's recorded fetch time, never `now()`, for `ops_bar_load`) and make the replacement conditional: `... DO UPDATE ... WHERE ohlcv_raw.served_at IS NULL OR EXCLUDED.served_at >= ohlcv_raw.served_at`. An offer older than the stored row goes to `ohlcv_revision` as a superseded answer (exactly what the release did for its 80), and the preview counts it as such. Until then, refuse `ops_bar_load --apply` for a series whose raw rows carry a `served_at` later than the artifact's mtime. Pin with a unit test: an older answer offered after a newer one leaves raw unchanged and logs the older value.

### 2. MEDIUM: the restatement detector is write-only; nothing reads `ohlcv_restatement_flag`

Evidence: repo-wide grep finds the table only in its migration (481), its writer (`services/ohlcv_ingress_contract.py`) and the single-writer test. The selection gate, the fetcher completion status (`ohlcv_history_fetcher.py`: `failed` no longer includes flags; `n_flagged_series` is only a counter), `ops_bar_nightly.exit_code` and `ops_bar_load` all treat a flag as success. `reviewed_at`/`review_note` exist but nothing lists unreviewed rows. Alerting is deliberately unwired, and the old Grafana rule `revision_refused` (`production/grafana/provisioning/alerting/alert-rules.yml`, `ohlcv_load_refused_24h{source=~'ibkr|derived'}`) can no longer fire for ibkr. D-191-N replaced a hard stop with "detected and reported loudly"; as built, a split-adjusted re-serve lands, gets one row nobody reads, and selection mixes bases.

Fix: a basis signature (`price_ratio`, `time_shift`) makes the run partial (fetcher completion status and nightly exit 1, like `unselected`), and the selection gate (or R6/D7) fails while any flag with a basis signature has `reviewed_at IS NULL`. Share-only flags can stay informational. Retarget or remove the `revision_refused` rule for ibkr.

### 3. MEDIUM: the detector can miss real basis changes

Evidence (`src/intelligence/bars/restatement.py`, APR seeds in migration 481):
- No volume signature. A volume-unit change (lots of 100 versus shares, a known IBKR API behaviour change) leaves prices equal, so `price_ratio` cannot fire (`abs(median - 1) > tol` fails), and `time_shift` cannot fire. Only the share flag catches it, and that needs at least 500 stored overlapping rows (`restatement_flag_min_stored`); the nightly 5m overlap of one session (about 78 bars) never qualifies.
- `price_ratio` uses `max` relative spread with tolerance 0.0005 (5 bp). A split re-serve rounded to cents breaks it for low-priced names (a 0.005 rounding on a 5 dollar post-split price is 10 bp), and a single genuinely corrected bar in the same re-serve also breaks it. Combined with the 500-row floor on the share signature, a split re-serve of one session on a low-priced name is not flagged at all.
- Flood risk is low: in the 30 days before the cutover only 3 of 156 IBKR 5m loads and 3 of 834 1d loads would have tripped the share flag (`ohlcv_load`, share > 0.02 over >= 500 stored). Live false-positive rate could not be measured (no vendor load has reached raw since the cutover).

Fix: add a `volume_ratio` signature (same shape as price, on volume); make `price_ratio` robust (the share of changed bars whose four prices sit within `max(tol, tick / price)` of the median ratio is at least an APR share, instead of the max spread); let any signature fire regardless of `flag_min_stored` once `signature_min_bars` is met (it already does) but lower `signature_min_bars` for 5m so a one-session overlap (78 bars) is enough. Unit tests: a 2:1 split on a 4 dollar name with cent rounding and one corrected bar flags; a volume x100 restatement flags.

### 4. MEDIUM: the only DB-level test of the ingress contract is broken and still pins the retired behaviour

Evidence: `tests/integration/test_ingress_write_contract.py` still calls `apply_raw_contract(..., waived=waived)` (the parameter is gone, so every test there raises `TypeError`), asserts `result.refused`, `n_held == 600`, and counts `origin = 'pending'` revisions (the value migration 482 forbids). Last touched in 191-06. The unit tests use fake connections, so nothing exercises against Postgres that a re-serve logs the old value and replaces raw in one transaction, that the upsert targets the right key, or that a failure rolls both back.

Fix: rewrite the file for D-191-N: first serve inserts; second serve with changed values replaces raw, writes exactly the changed rows to `ohlcv_revision` (origin raw, under the new load, old request_id), and a forced failure after `_write_revisions` leaves neither. Add the finding 1 test there too.


### 5. LOW: 2006-12-27 sessions are recorded as zero-grid "absence" choices although IBKR held them whole

Evidence: 160 `bar_session_choice` rows on 2006-12-27 have `vendor = ranking[1] = 'ibkr'`, 74 to 81 IBKR slots, `n_vendor_grid_slots = 0`, `n_primary_grid_slots = 0` (166 such rows in all with 2010-08-04 and 2011-01-28). IBKR opened 14:30 UTC where the calendar says 14:32 (D-191-L rule 1), so no IBKR stamp is on the calendar grid; `judged = session_slots & grid` is empty and completeness is vacuous (every vendor is "complete"). A feature conditioning on `n_primary_grid_slots = 0` reads these as fallback by absence. No canonical data is affected today (no Alpaca data in 2006).

Fix: when the chosen vendor holds slots but none on the grid, judge completeness on `session_slots` and record the calendar mismatch (for example `n_grid_slots` NULL with a reason), or snap the grid to the vendor's session open for named kinds.

### 6. LOW: the one-time release and the GE precision restatement left no detector record

Evidence: `ops_pending_release.py` writes through `write_raw` directly, so the 1,014 GE 2021-11 bars that moved from four-decimal to two-decimal prices (a precision basis change the share signature would flag: 100% of 1,014 stored) have no `ohlcv_restatement_flag` row; the table is empty. Todo 535 item 24 records it, so this is bookkeeping only.

Fix: insert one flag row for the GE release load (share signature, detail pointing at item 24) when the table gets its first reader (finding 2), so the review queue starts complete.

### 7. LOW: `bar_session_choice` writes row by row and cannot clear an all-off-grid session

Evidence: `record_session_choices` issues one `INSERT ... ON CONFLICT` per choice. The table is 677 MB for 3,081,879 rows (about 220 bytes a row, `ranking` and `dropped` arrays); at 10x the sessions it is about 7 GB in a plain heap, which is acceptable, but a full reselect of the universe would be tens of millions of single-row statements. `outcome.sessions` holds only sessions with on-grid candidates, so a session whose candidates all became off-grid keeps a stale row (unlikely, raw rows are never deleted).

Fix: one multi-row upsert per call (the raw writer's batching pattern). Optional: drop `ranking` per row in favour of the policy as of the session date.

### 8. LOW: dead one-time code and stale references

- `scripts/ops/bars/ops_pending_release.py` reads `origin = 'pending'` (five SQL strings); after migration 482 it can only find nothing. Delete it (the run is in `logs/pending_release_191_apply.json` and git history), or make it exit loud.
- `_history_fetch_item.py` and `ohlcv_history_fetcher.py` still thread `waived` (todo 535 item 25 already records it).
- Grafana `revision_refused` (see finding 2).

## Answers to the review questions

1. Revision before overwrite, same transaction: yes. `write_raw` writes `_write_revisions` before the raw inserts and upserts on the caller's cursor, under the series advisory lock taken in `preview_series` and held to commit; `store_bars` and `persist_chunk_atomically` wrap it in `conn.transaction()`. The unit test pins the order. The only raw writers are `write_raw` and the one-time `ops_raw_backfill.py`. Latest by serve time: no for live writes (finding 1).
2. The release: verified at every one of the 4,652 decisions in `logs/pending_release_191_apply.json` (scratch script `verify_release.py`): all 4,572 released keys hold the offered value in raw now; all 1,110 that displaced a value have that value as a revision under the release load; all 80 superseded offers exist as origin raw revisions under their own refused load, and for each the raw value's serve time is later than the offer's; no `pending` row remains; nothing served is lost. Note that all 1,110 displacements were decided because the raw value's serve time was unknown (backfill copies, `served_at` NULL, no covering serve); that is correct here because the refusal had judged against that very value, so it predates the offer.
3. The detector runs on every live path (fetcher chunks and the reserve lane via `persist_chunk_atomically`, `store_bars`, the Alpaca campaign and nightly via `load_frame`), not on the one-time release. Gaps: findings 2 and 3. Thresholds are APR (migration 481).
4. No live reader of the retired origin or removed helpers in `src/`, `services/`, `scripts/` (except the dead release tool) or the dashboard; the integration test is stale (finding 4); one Grafana rule is stale for ibkr. Migration 482 is safe: it raises if any pending row exists, and the swap validates against the table.
5. `bar_session_choice` has one writer (`record_session_choices` inside `select_and_write`, same lock and transaction; the single-writer registry pins it). Fallback by absence versus shortfall is defined by `n_primary_grid_slots` 0 versus more, correct except finding 5. "Short of calendar" never drops data: completeness is judged against the union of the ranked vendors' slots, not the calendar, and only the 42 sessions with no complete vendor drop slots (87 slots, all recorded in `dropped`). Scale: finding 7.
6. The refused-window exclusion in `_d1_gaps.py` is coherent: no vendor load is refused any more, but 75 historical refused 5m loads remain, so it is not dead. Matching is by the latest request within 5 s (`infra.selection_gate.request_load_match_s`); on the refused loads checked (GE, IWM), each refused load matches its own chunk's request. Windows of the six 2026-10-12 loads and GE whose offers were later released stay "unanswered" and are re-asked only for slots still missing from raw, which is harmless.
7. `logs/reserve_keys_191_07.json`: 4,569 keys, 103 sessions, 38 series, every timestamp tz-aware. 4,524 keys are 58 whole sessions (78 each) on the nine series, all missing from IBKR raw today (canonical holds Alpaca at 4,226 and nothing at 298). 22 truncated 2026-10-09 bars and 17 TMUS verifications are in raw (as expected for a verify re-serve). 6 partial-only keys are missing from raw and canonical. Sane.
8. The new unit tests would fail on the old code (for example `test_a_restatement_beyond_the_old_threshold_lands_last_wins_and_is_flagged`, `test_changed_row_replaced_and_old_values_logged` with the order assertion, the gap planner refused-window tests). Gaps: no test of serve-time ordering (finding 1), the ratio test uses exact unrounded prices (finding 3), no DB-level test (finding 4). The targeted suites pass (restatement, ingress contract, raw writer, d1 gaps, bar selection, ledger evidence, selection gate).

## Verified sound

- Revision log before overwrite, same transaction, series advisory lock (question 1).
- The pending release: every decision checked against the database; nothing lost (question 2).
- Migration 482 guard and constraint swap; no `pending` rows remain.
- `bar_session_choice` single writer and clear-then-upsert semantics on the selection transaction.
- Re-serve list composition and coverage (question 7).
- Contradicting duplicates in one chunk still raise before any SQL; preview and write counts are cross-checked (`apply_raw_contract` raises on disagreement).


## Could not verify

- The live false-positive rate of the detector: no vendor load has reached raw since the cutover.
- The selection gate and idempotence figures in `191-07-FIXES.md` (exit 0, 21,687,536 rows): not re-run, because the gate opens a write-capable connection.
- How often the whole-session rule will switch thin IBKR-first names to Alpaca once the deep IBKR 5m backfill lands (today 340 fallback-by-shortfall sessions on 209 names); worth measuring after 191-10.

## Verdict

- Plan 191-10: proceed. It rewires `ops_bar_nightly` and `split_detection`, which is where finding 1 (serve-time ordering, so the nightly and the campaign loader cannot clobber each other) and the split side of finding 3 belong; fold them in. Do not run `ops_bar_load --apply` against existing series until finding 1 lands.
- Fetcher resume: proceed after finding 2 (a basis signature makes the run partial and is listed until reviewed), which is a small change. The IBKR fetcher itself is not exposed to finding 1 (answers are written as they arrive, under `FetcherLock` and the series lock), but the deep backfill re-asks history and will produce restatements, and today a flagged split re-serve would land unread. Finding 4 should land in the same change set. Then the re-serve of `logs/reserve_keys_191_07.json`, the gate and the idempotence check as planned.
