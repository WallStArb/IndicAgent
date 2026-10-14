# Review of plan 191-07 (selection gate), read-only

Scope: b2ffcaec4 12b80c126 349cdc825 f035d3bed 49d21f9a5 5f759b70e 089f95426. No repo file, service or DB state was changed. Every DB read was symbol-bounded, with LIMIT and statement_timeout, in a rolled-back read-only transaction.

Scripts in this scratchpad: `verify_classes.py` (seeded sample, seed 19107, 25 slots per class, full evidence in `classes.json`), `verify_value_classes.py` (every explained slot characterised, `value_classes.json`), `tod.py` / `tod2.py` (time of day, volume and chronology crosstabs). Recomputing over the 57 series gives exactly the report's totals: refused_self_restatement 6,168, refused_cross_vendor 2,895, restated_after_copy 148.

## Ranked findings

### 1. HIGH: the gate verdict treats 9,211 slots as clean, against the plan amendment, and the D-191-I check counts nothing
- Code: scripts/ops/bars/ops_selection_gate.py:159-171 (classify), 323-330 (refused-value check), 600-607 (verdict).
- Amendment 2026-10-13 to plan 07 keeps `refused_self_restatement` "only as a report line" and says "Any non-zero difference on a refused series is a real difference". The code does the opposite. It exempts three classes from the verdict (two of them added during execution), and `--compare` exits 0 while canonical differs from f(raw, policy) on 9,211 slots. The idempotence probe confirms it: running the writer over 7 of the 57 series inserts 436 rows and replaces 320.
- `refused_value_selected` reads only `origin = 'pending'` revision rows. There are none, so the check passes without testing anything. Meanwhile 6,151 current raw rows on the explained slots were served by a refused `ohlcv_load`: raw.served_at equals the refused load's loaded_at; the raw-backfill-191 copy took them from the archive. Selection would promote exactly those values. That is the D-191-I violation the check exists to catch.
- Failing scenario: plan 08 or 10 reads "gate exit 0" as permission and resumes the fetcher. The first IBKR chunk over GE 2021-09-01..2022-04-05 runs select_and_write over its span, and canonical takes the refused 2-decimal serve (64.73 for 64.7305 on 2021-09-01 16:55).
- Fix: count every selected raw row whose served_at or load_id maps to a refused load as `refused_value_selected`. Return a non-zero code, for example 3 "explained residue", whenever explained VALUE or refused-served slots exist. Keep the classes as diagnostics only.

### 2. HIGH: repair step (a) writes chunk-edge truncated bars into raw; a fetcher edge defect is the cause
- Evidence:
  - 128 of the 148 restated_after_copy slots sit at 14:00 UTC.
  - On 127 of them canonical volume is lower than raw volume.
  - Where an Alpaca twin exists, the raw IBKR volume is closer to Alpaca in 70 of 72 cases.
- KRE 2007-06-25 14:00: canonical is 45.61/45.61/45.61/45.61 with volume 0. Raw holds 45.65 ... 45.65 with volume 9,500. Load 2006-11-16..2007-06-25 (loaded 2026-10-13 16:34:50, n_changed=1) restated exactly that bar; it is the last bar of a request ending that day.
- The same pattern appears in the self-restatement class: TMUS 19:05 bars, the 2026-05-15 15:25 bars of HD, HON, IGV and ISRG (ISRG canonical volume 712 against raw 15,235), and ADM 2026-10-12 19:55 (an in-progress bar).
- Cause (partly traced): src/providers/ibkr.py:1132 and 1340. `chunk_end = end`, then `chunk_end = chunk_start - 1 day`, so every chunk keeps the clock time of `end`; `fetch_end = gap_end` comes from _history_fetch_item.py:813. Each request edge cuts a bar mid-session. Under last-wins with a 2% share the partial bar is accepted as a restatement.
- Impact: summary Unresolved 1(a), "refresh raw for the 148 stale keys from canonical", would make the truncated bar current raw on about 128 keys. The full bar would survive only as a revision row. The same defect would recur on every chunk boundary once the fetcher resumes (task 3).
- Fix: do not refresh edge keys from canonical. Fix the leaf first. Either align endDateTime to the session close or the day boundary, or drop the bar that straddles chunk_end and any forming bar (the 5m analogue of D-191-J). Then re-serve the affected keys and let last-wins land a complete bar. Refreshing from canonical is fine for the remaining 20 non-edge keys, under a dedicated repair load with origin raw.

### 3. MEDIUM: refused_self_restatement mislabels 17 to 22 slots, and a unit test locks in the error
- Code: ops_selection_gate.py:159-165. The class only checks that canonical's value is among the logged old values. It never checks the order of serves, and it never checks that a refused load exists.
- 17 slots (TMUS) have raw.served_at NULL, no refused load covering the day, and only applied-load revisions. The chain is: full bar V1, then a 2026-10-09 load replaced it with truncated V2, raw copied V2, then a 2026-10-13 load restored V1. Raw is stale and canonical is the latest accepted serve, so the correct class is restated_after_copy.
- 5 more slots have both values logged, and canonical is the truncated edge bar (HD, HON, IGV, ISRG at 2026-05-15 15:25).
- tests/unit/scripts/test_ops_selection_gate.py:99-100 asserts that when both values are logged the class is SELF_RESTATEMENT. That is the wrong precedence.
- Effect on repair (b): it would invent `pending` holds for a superseded truncated bar.
- Fix:
  - Require that the raw row's served_at or load_id belongs to a refused load of the same vendor.
  - When both values are logged, decide by the latest revision's loaded_at.
  - Replace the test.

### 4. MEDIUM: repair step (b) is mostly right, but its stated premise is wrong for 61% of slots and it keeps incomplete bars
- 3,747 of the 6,151 refused-served slots have an applied IBKR canonical load covering the same day that ran after the refused serve, with no revision logged, so it re-served the canonical value. The refused value is the earlier serve, not "the later serve". GE is an example: refused at 12:14:31, applied at 12:15:17. Holding those as `pending` asks a question the vendor has already answered.
- 59 slots have canonical volume below raw volume (incomplete or truncated bars), for example ADM 2026-10-12 19:55 (380,459 against 380,759) and HD 2026-05-15 15:25 (11,238 against 24,428). Under strict D-191-I, (b) keeps those bars and holds the complete one as pending. That is acceptable only if the pending list flags them for an explicit release.
- What (b) can destroy:
  - Rewriting raw in place loses the fact that raw-backfill-191 made the refused value current, unless that is logged.
  - Deleting the raw-backfill-191 `origin='raw'` revision rows loses the only record of the canonical value on 6,146 keys.
- Safest implementation:
  1. Fetcher held.
  2. One transaction per series, through the raw single writer, under the bar_selection advisory lock.
  3. For each key: raw ← canonical value, with a new ohlcv_load (caller raw-repair-191, outcome applied, destination raw) and an origin raw revision whose old value is the refused value.
  4. A `pending` row with the refused value under the ORIGINAL refused load_id (it exists: its loaded_at equals raw.served_at), only where no later applied serve covers the day. Elsewhere, origin raw history only.
  5. Never delete existing revision rows.
  6. Then select over each touched series and re-run the gate.
- Verification:
  - Explained VALUE classes reach 0.
  - refused_value_selected = 0 under the fixed definition from finding 1.
  - The pending count equals the planned count.
  - Idempotence over all 57 series shows 0/0.
  - Raw row count unchanged.

### 5. MEDIUM: refused_cross_vendor is honest today but too generous to serve as a standing gate (plans 12 to 14)
- Code: ops_selection_gate.py:166-170, 627-630, 684-686.
- Windows are whole refused request ranges: 171 of the 276 vendor differences and 1,909 of the 2,619 raw-only rows fall under windows of 180 days or more, for example EMR 2026-03-09..2026-10-09.
- VENDOR_KIND is explained without checking that canonical's own (vendor, kind) raw row equals canonical.
- A same-vendor, different-kind difference is explained by vendor-keyed windows.
- ONLY_SELECTED is explained without tying the raw row to the refused load.
- Re-verified today:
  - 276/276: canonical's vendor row in raw equals canonical, and canonical holds both vendors on that session date.
  - 2,619/2,619: the raw row was served by the refused load, and canonical has no row of any label there.
- Latent scenario: an Alpaca raw row drifts from Alpaca canonical inside an IBKR-refused window where the span ranks IBKR first. The slot shows as VENDOR_KIND and is explained, so the Alpaca divergence is hidden.
- Fix: require the selected row's served_at or load_id to be the refused load, and canonical's own raw row to be equal.

### 6. MEDIUM: a backdated span changes historical canonical piecemeal and silently
- Code: scripts/ops/bars/ops_source_policy.py insert_row (no valid_from guard); services/bar_selection.py and services/ohlcv_ingress_contract.py:404-416 re-select only the loaded window. Canonical replacements are not logged by design.
- Scenario: a span is added (or closed and re-inserted) with valid_from 2026-03-10. The next nightly re-selects only its own window. A later fetcher chunk over 2026-05 flips that chunk only. Canonical becomes a mix of the old and new policy until someone re-runs the gate.
- Fix: a span write re-selects [valid_from, valid_to) of that series in the same transaction and runs the per-series gate. Alternatively, refuse valid_from earlier than today unless `--reselect` is given.

### 7. LOW
- The fetcher ignores IngressResult.n_unselected: _intraday_persist.py:124-140, ohlcv_history_fetcher.py:1075-1082 and _history_fetch.py:895-899. Coverage is still credited and the status can be "success". It cannot happen today, because every 5m, 1m and 4h ranking includes ibkr; it becomes possible once a span excludes it.
- NULL-volume winner (bar_selection.py:147-149): the writer skips it and leaves the previous canonical row in place (possibly another vendor's), with no fallback to the next ranked vendor. skipped_null_volume is not propagated to IngressResult. The count is 0 today.
- Span evidence (ops_selection_gate.py:524-544): every span of a series carries the whole series' canonical_rows, first_bar and last_bar. For example, all 5 ECL spans say 2006-06-30..2026-10-09, and the forward tail claims rows it never covered.
- Refused windows are UTC dates (ohlcv_ingress_contract._utc_date into requested_start and requested_end), but classify compares session dates. After-hours stamps after 00:00 UTC widen a window by one day.
- merge_reports (548-597) drops meta and does not check shard completeness or duplicates. I checked by hand: 12 shards, 1,551 symbols = count of instruments.
- read_canonical (667-673) silently skips source labels outside the vendor map, NULL included. Today there are 0 such rows in the 57 series and in SPY, AAPL, KRE and VIXY.
- Off-grid is not a failure signal. A calendar defect would drop a whole day of sip_rth. The only odd session from 2006 to 2026 is 2006-12-27 (09:32 open), before Alpaca's history begins.
- Tests: test_bar_selection.py `test_rth_grid_is_open_inclusive...` ends with a vacuous `assert day.date() == date(2026,10,12)`. The precedence test is covered in finding 3.

## Verified sound
- No shard gaps: 0/12..11/12; n_symbols sums to 1,551 = instruments, active and inactive. Raw and load have an FK to instruments.
- Compare is not canonical against itself: canonical comes from the target, selection from ohlcv_raw with the live pure function. The month digest packs float64 over double columns, so there is no precision loss, and a mismatching month gets an exact tuple diff.
- The sip_rth session filter cannot hide a divergence. Any canonical row without a selected twin is ONLY_CANONICAL (REAL, never explained), and REAL is 0. All 31.8M dropped candidates are slots where canonical never held Alpaca.
- Spans: 1,641 rows; 0 gaps and 0 open-ended rows mid-sequence per symbol. Session-date matching is the same in derivation and selection. DST and half days are handled through America/New_York dates. The EXCLUDE constraint prevents overlap. For ECL, ELV and EMR the 5 spans follow canonical exactly (alpaca first 03-10..07-31 and 10-01..10-10, the IBKR-refused span).
- Lock:
  - Callers take the advisory lock in sorted (symbol, timeframe) order: ingress sorts its spans, the gate locks one symbol per call. There is no cross-order path.
  - Under READ COMMITTED, a writer that writes raw before taking the lock still converges, because the selection re-reads raw after acquiring it.
  - The 64-bit hashtextextended key makes collisions negligible, and a collision would only serialize writers.
  - The lock is held only for the chunk transaction; no network IO happens under it.
- ON CONFLICT overwrites whatever row holds the slot with the deterministic winner. That is intended, and selection reads canonical after taking the lock.
- Shuffle determinism: slots are sorted, there is a kind tie-break, and the raw primary key rules out duplicates. No wall clock enters selection.
- ops_bar_load and ops_bar_nightly: held → HELD, unselected → UNSELECTED, exit 1 on either; tested.

## Could not verify
- That today's fetcher path still produces mid-session chunk edges on every chunk. The data shows the pattern up to 2026-10-13; I traced the mechanism in _walk_history but not the exact gap_end alignment.
- ADM refused load b0a0f500 (2026-10-10, 1,092 bars, n_archived 0) has no archive rows, so that refused offer's evidence appears lost (domain of plans 04/05). A later refused serve covers the same range.
- Whether price_sanity_status and base go stale when the upsert replaces a row (the upsert does not reset them).
