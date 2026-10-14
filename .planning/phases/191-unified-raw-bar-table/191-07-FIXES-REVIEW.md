# Review of the plan 191-07 review fixes, read-only

Scope: c238769e9 eeb0fb7c6 aadd48ae6 378dc8a3c 091706c88 1b14e4b79 79d251135 ac700791c c86059c3d 658755619 (gate, chunk edge, raw repair, policy reselect, unselected counting, re-serve lane, D-191-M). No tracked file, service or DB row was changed and nothing contacted IBKR. Every SQL read ran SELECT-only (read-only transactions); the gate re-run used `PGOPTIONS=-c default_transaction_read_only=on` with `--out` in the session scratchpad. Targeted unit suites pass (chunk edge, repair, gate, source policy, raw writer, ingress contract, fetch item, fetcher).

## Ranked findings

### 1. HIGH: 88 "re-served" restores rest on a date-level coverage test; the vendor never served those slots again, so the latest vendor answer is neither raw nor pending

- Code: `ops_raw_repair.plan_series` (lines 193-199) calls `evidence.later().find(ts, vendor, refused_at)`. `LoadFact.covers` compares UTC dates only (`ops_selection_gate.py:160`). Any applied load whose first-to-last bar dates include the slot's date counts as a re-serve, even when its request ended or started hours away from the slot.
- Evidence: 3,735 restores carry the reason "re-served by applied load". 3,647 rest on GE load 2e726390, whose 11,856 bars were all unchanged, so that evidence is sound. The other 88 are all on 2026-10-12, and their excusing loads' requests do not hold the slot:
  - ADM f40ff724, AEP 6c823d09, AMT 39565f04, AMZN b38ae254, ASML 8312736c, BA 2e368a80: each request window is 2026-10-12 20:10 to 2026-10-13 00:05 (48 after-hours bars, `n_new 48`). The excused slots run 16:00 to 19:55 UTC. That is 80 slots, confirmed.
  - HON 2d2a6b4c: the request window is 15:25 to 20:11, but the excused slot is 15:10. Confirmed.
  - SHY 9b6686c7, TLT ab871f0b, TMUS 5ea5e8c4: 10 or 11 bars from a request that ended at 2026-10-13 08:47. Probable, not proven.
- Worst case, ADM 2026-10-12 19:55 (the review's own example of an in-progress bar):
  - Raw and canonical now both hold volume 380,459, the earlier, incomplete serve.
  - The vendor's later, after-close answer (380,759, refused load 898c4a50 at 23:23) survives only as a raw-repair-191 `origin raw` revision. It is not pending and not on the reserve list.
  - Across all restores, 3 slots ended with raw volume below the replaced refused value and no pending row.
- The gate cannot see this. Raw equals canonical and no pending row exists, so all 48 "clean" series include these slots.
- `held()` (gate line 288) uses the same date-level test. Today it excuses only 20 keys (GE 2021-11-05 x19 and VIXY x1), and I checked that both excusing loads really served those slots. The mechanism is still unsound.
- The test `test_a_refused_value_the_vendor_answered_again_is_restored_without_a_hold` locks in date-level evidence: its later load covers 2007-01-01..2026-12-31.
- Fix:
  - Make a re-serve exact-key evidence. Use the later load's request window (`ohlcv_request.window_start..window_end` via `request_id` on new-path rows, or the request answered within seconds of the load for legacy loads), or an archive or revision row of that load at the key.
  - With only date-level evidence, default to `restore_pending`.
  - Remediate the 88 now: `hold_legacy_refusal` under each original refused load, with the refused value from the raw-repair revision. It is idempotent.
  - Add the 3 lower-volume slots (ADM 19:55 among them) to the reserve list.
  - Apply the same exactness to `LaterServes` in `held()` and `refused_serve_map`.
  - Replace the test with one where the later load covers the date but not the slot.

### 2. MEDIUM: D-191-M splits a load-level refusal per key, and the result matches neither outcome of the per-source contract

- `apply_raw_contract` judges a whole chunk series against the vendor's own stored rows. Accepted means every bar lands last-wins. Refused means every offered row that differs is held pending, new rows included (`held_stamps = changed_old | new_timestamps`).
- The repair instead accepts the new keys of a legacy refused load (2,895 catch-up) and holds its changed keys (2,400 pending). Every catch-up load also has holds: ADM 14, EEM 57, EWZ 80, FXI 82, and so on.
- Own-value restatement share per load, from the repair report (lower bound, because "stored" includes Alpaca canonical rows):
  - Over 2%, so the per-source contract would also refuse:
    - ADM: 27 / 1,125 = 2.4%.
    - AEP: 39 / 1,125 = 3.5%.
    - AMT: 32 / 1,127 = 2.8%.
    - ASML: 26 / 1,128 = 2.3%.
    - BA: 31 / 1,129 = 2.7%.
    - These five loads supplied about 370 catch-up slots that the contract would hold pending.
  - About 0.3 to 0.7%, so the per-source contract would apply: EEM, EFA, EPD, EQIX, ETR, EWG, EWJ, EWT, EWY, EWZ, EZU, F, FCX, FDX, GDX, GE 2b653430, IWM, IYT, KRE and others. Their 1,000+ pending holds are holds the contract would not make; the restatement would land last-wins.
- Fix: re-judge each legacy refused load once with `should_refuse` against the vendor's own pre-refusal values (they are reconstructable from the raw-backfill revisions and the archive). Then apply one outcome per load:
  - Accepted: the offered values become raw, no pending.
  - Refused: hold everything, new keys included.
  - Record the decision in D-191-M with the per-load table, and get the owner's acknowledgement before plans 08 and 10 rely on it.

### 3. MEDIUM: the catch-up spliced IBKR afternoons onto Alpaca mornings in 52 of 57 sessions on 2026-10-09

- Canonical 5m on 2026-10-09 is mixed-vendor for 52 of the 57 series. Examples:
  - ADM: Alpaca 13:30-16:10, then IBKR 16:15-19:55.
  - ECL: Alpaca to 17:10.
  - EEM: Alpaca to 17:15.
- The span 2026-10-01..10-10 ranks Alpaca first. Alpaca raw stops mid-session, and the 2,619 only_selected catch-up slots filled the rest from the IBKR fallback. Before the fix those slots had no canonical row, an honest NaN.
- Alpaca SIP volume runs about 1.1 to 2x IBKR's on the same bar (ADM 16:05: 17,244 against 10,607). Every volume feature and the 15m/1h derivation therefore see a step at the splice.
- The gate does not detect this because it is policy-correct.
- Other mixed sessions in the 57 series in 2026: 6 on 09-16, 1 to 3 per day on 10-01..10-08, and 2 on 07-07.
- Fix:
  - Make fallback session-level for direct timeframes: when the primary's session is incomplete, take the whole session from the fallback or leave it, and record the choice.
  - Alternatively, count mixed-vendor sessions in the gate as a reported class.
  - Separately, find out why Alpaca's 2026-10-09 serve ends mid-session (loads at 2026-10-10 15:19-16:12; the last Alpaca bar may itself be partial, and the Alpaca leaf has no forming-bar rule, see finding 5).

### 4. MEDIUM: 9 held refused values stay current in raw

- The 9 reserve refused serves are HD, HON, IGV, ISRG and ITA 2026-05-15 15:25; RLAY 2026-10-09 14:10; and SHY, TLT and TMUS 2026-10-09 19:05.
- Raw holds the refused whole bar as the current row, which is exactly the state D-191-I forbids.
- Any `select_and_write` window over those slots promotes them, before the re-serve and without a decision. The window can come from any vendor's ingress chunk, a policy `--reselect`, or the repair. The 2026-10-09 slots are recent enough for a routine update-lane overlap or an Alpaca load to touch.
- The gate would then report `refused_value_in_canonical` and exit 1, so the failure is loud, but only after canonical has changed.
- Fix: before anything resumes, run the reserve lane first, as FIXES says. Better, make `select_and_write` exclude keys that `refused_serve_map` marks as held. The rule then lives in the writer instead of the order of operations.

### 5. MEDIUM: the forming and straddling bar rule sits in the IBKR leaf, drops the bar's values with no record, and Alpaca has no equivalent

- `src/providers/CLAUDE.md`: "policy never enters a leaf". The 1d analogue (D-191-J) lives in `_ChunkPersister`, where the request row is kept.
- `complete_intraday_bars` discards the bar inside `_walk_history`. The `RequestRecord` still says `n_bars=len(ib_bars)`, but only the first five stamps reach a structlog warning, and the values are lost. That contradicts "nothing a vendor serves is dropped", and any balance check of served against stored bars will see an unexplained shortfall.
- The forming test uses `datetime.now(UTC)` at parse time, not the answer time. A bar answered at 19:59:50 and parsed after 20:00:00 is kept.
- The last bar of a session (15:55-16:00 ET) is still revised after the close by the closing cross. ADM 19:55 moved from 380,459 to 380,759. The intraday rule treats it as complete the moment its block ends.
- Fix:
  - Return the partial bars from the leaf, or pass them through `on_observation`, and drop them in the persister (vendor-agnostic, so Alpaca gets it too). Record them in the archive or a pending-style row.
  - Judge the bar against `answered_at`.
  - Add an APR settle delay for the session's last bar.

### 6. LOW

- FIXES and D-191-M say canonical was "never copied into raw at an edge". In fact all 6,163 restores, including the 6 edge restores (HD, HON, IGV, IHF, ISRG and ITA 2026-10-12 15:25), write `a.canonical` into raw.
  - 6,142 of those values were logged before as the same vendor key's old values, mostly in raw-backfill-191 revisions.
  - The 21 VIXY 2026-09-23 restores are evidenced only by the later canonical load's revision of the old value.
  - Fix: read the restore value from the ledger (revision or archive row of the same vendor and kind) and assert that it equals canonical, rather than taking canonical as the source.
- Repair raw rows get `served_at = now()` at repair time (`_UPSERT_TAIL`). The load caller `raw-repair-191` disambiguates, but `served_at` no longer means "the vendor served it then". Keep the original serve instant, or document the field as a write time.
- `count_unmapped` counts labels outside `LABEL_TO_VENDOR_KIND`, but `read_canonical` also skips the `derived_5m` label. A derived-labelled row in a direct timeframe is neither compared nor counted. There are 0 such rows today. Fix: count non-vendor labels as unmapped for direct timeframes.
- `--reselect` writes the policy row without taking `bar_selection|symbol|timeframe` before the policy INSERT. A concurrent ingress chunk holding cached `policy_rows` can re-select its window with the old policy after the commit. The fetcher is held today. Fix: take the series selection lock before the policy write, and have ingress re-read policy under the lock.
- `ops_selection_gate --apply-spans` still writes through `insert_row` with no backdated guard. That is acknowledged, but a stale spans file would rewrite canonical silently. Fix: refuse unless the spans file's compare run is newer than the series' last load.
- The 4h rule drops the complete winter 20:00-21:00 UTC bar whenever the run end sits between 21:00 and 24:00 UTC, because the block end of 24:00 is used as an upper bound. The planner re-asks the slot, so nothing is lost, but every such run wastes one bar.
- The `--reserve-keys` window is America/New_York midnight to midnight, a 1-day delta, so the request uses duration "2 D" and re-serves the prior session as well. Any 1-cent late revisions there count toward the restatement share and can refuse the re-serve. Fix: ask with an end at the session close and a duration of 1 D.

## Verified sound

- FIXES numbers reproduce exactly:
  - The gate `--compare` re-run over the 57 series exits 3, with refused_self_restatement 9, restated_after_copy 17, cross-vendor 0, real 0, refused_value_selected 9, refused_value_in_canonical 0, pending 2,400, canonical = selected = 21,687,556, and 48 series clean.
  - Raw 5m rows of the 57: 36,554,783.
  - raw-backfill-191 origin raw revisions: 6,151 across 46 loads, all intact.
  - raw-repair-191 revisions: 6,163 across 45 loads, equal to 3,763 restore plus 2,400 restore_pending.
  - Catch-up: 2,895 (2,619 only_selected plus 276 vendor-kind). Canonical new 2,580 + 39 = 2,619; replaced 304 + 99 = 403.
- Pending rows: all 2,400 sit under refused loads of the same symbol, timeframe and vendor, whose dates cover the slot. Each equals the old value of the raw-repair revision at that key and exists in `ohlcv_intraday_raw_archive`. None has a later applied load covering its date, so no pending row is spurious. No raw or revision row was deleted.
- Repair write path:
  - It takes the raw series advisory locks with the writer's own key format, then `bar_selection|symbol|timeframe`, the same order as ingress, and re-plans under the lock.
  - Raw is written only by `write_raw(repair=True)`, which logs the old value before the upsert.
  - The selection count is checked against the plan, and a mismatch rolls back the series.
  - The repair is idempotent: repaired rows carry the repair `load_id`, so they are no longer refused serves, and `hold_legacy_refusal` skips keys already held. The rerun dry run plans only the 26 reserve keys.
- Chunk-edge alignment:
  - IBKR stamps every intraday bar on the UTC grid of its size, so floor alignment is right. Checked in raw: 15m and 1h on :00/:15/:30/:45 with the 13:30 or 14:30 opening partial; 4h at 13:30/16:00 in summer and 14:30/16:00/20:00 in winter.
  - ET offsets are whole hours, so DST and half days do not break the 5m, 15m or 1h grids.
  - Every inner chunk end steps back by whole days and stays aligned.
- No permanent loss at inner chunk edges. IBKR's "N D" counts sessions, so chunks overlap by about 60 calendar days. KRE's 2007-06-26..11-22 request returned 11,655 bars, while raw holds 8,030 RTH bars (104 sessions) in that nominal window: about 150 sessions served. The bar starting at a chunk's end is therefore served whole by the later chunk.
- At the run's end, `plan_gaps` caps windows at `run_end`, and `AnsweredWindows.covers` needs `slot + interval <= window_end`. A dropped straddler or forming bar therefore stays a gap and is asked again. The reserve-lane windows sit on the grid, and no trading day falls on a DST transition date.
- Fingerprints: no `code_content_key` or `kernel_code_key` closure reaches `src/providers/ibkr.py`. `backfill_feature_factory` imports it, but that module is hashed as an `own` file without following its imports, and no file under `src/intelligence` or `src/core` changed.
- Gate:
  - Exit codes are 0 only on exact equality; 1 for real differences, a refused value in canonical or unmapped labels; 3 for residue.
  - `check_shards` and `merge_reports` refuse incomplete, mixed or duplicate shards.
  - `refused_serve_map` uses `load_id` first, so the `served_at` match applies only to NULL-`load_id` backfill copies.
  - Same-vendor, different-kind differences are now REAL.
- The unselected and NULL-volume counting is correct: `store_bars` raises, the run is partial, and the ingress contract adds `skipped_null_volume`.
- `--reselect` re-selects exactly the session-date window `[valid_from, valid_to)`, from America/New_York midnight, in the same psycopg transaction as the policy write, then gates the series.

## Could not verify

- That the SHY, TLT and TMUS excusing loads (10 or 11 bars, requests ending 2026-10-13 08:47) did not serve the 19:05, 19:10-19:55 and 19:30 slots. Load to request is matched by time only, and the legacy rows carry no `request_id`.
- Which serve produced ADM canonical 19:55 = 380,459. No `ohlcv_request` row for ADM ends on 2026-10-12 before the 23:23 refused request, so `at_edge` could not mark it either.
- Why Alpaca's 5m serve of 2026-10-09 ends mid-session for most names, and whether its last bar is partial.
- Whether IBKR answers a seconds-duration request that ends in pre-market with the prior session's bars. GE load 043784e0 records 2021-11-05 bars from a request window of 2021-11-08 09:00-10:30, so request windows are not the served range. That weakens any request-window evidence used for the finding 1 fix, which should therefore prefer per-row `request_id` where it exists.
- The re-serve lane end to end (fetcher held).
