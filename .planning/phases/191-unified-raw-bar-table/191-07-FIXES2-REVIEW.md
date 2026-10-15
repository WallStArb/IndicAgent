# Review of the plan 191-07 second review fixes, read-only

Scope: 414526070, 8a2bd25f4, 66d6b0caf, ac4f598e0, 85a3831d7, 1199ed05e, 95a6463b0, de129f40b, 9eeb0907f, 08ec37d67, checked against `191-07-FIXES-REVIEW.md`, the "Second review fixes" section of `191-07-FIXES.md`, the D-191-M amendment, todo 535 items 16 to 23, and the reports `logs/refusal_rejudge_191_apply.json`, `logs/selection_gate_191-07-fix2_after.json` and `logs/reserve_keys_191_07.json`.

Nothing tracked, no service and no DB row was changed, and nothing contacted IBKR. Every SQL statement ran with `default_transaction_read_only=on`. One gate `--compare` ran read-only on 12 series outside the 57, with its output in the session scratchpad. The targeted unit suites pass: bar selection, complete bars, refusal rejudge, selection gate, raw repair, gap plan, fetch item, raw writer, request writer and d1 gaps.

## Ranked findings

### 1. HIGH: the re-judgment counted values that arrived after the refusal as "stored at the refusal", and missed the later serve that wrote them; the D-191-M table and the ADM 19:55 story are wrong for six loads

The six held loads from 2026-10-12 23:23 are ADM 898c4a50, AEP 04f17062, AMT 59097ead, AMZN 86c21967, ASML 49aa4190 and BA 4e945cfd. Each was judged against 48 IBKR values at 2026-10-12 16:00 to 19:55. None of those values existed at 23:23.

- They were first written by a later applied load of each series: ADM f40ff724 (2026-10-13 04:27), AEP 6c823d09 (04:37), AMT 39565f04 (05:10), AMZN b38ae254 (05:01), ASML 8312736c (05:11) and BA 2e368a80 (05:31).
- Each of those loads has `n_new 48`, with first and last bar on 2026-10-12.
- Canonical ADM on 2026-10-12 holds exactly 48 `ibkr_named` rows, 16:00 to 19:55. Raw holds no IBKR row after 20:00.
- No other ADM 5m load or request touches 2026-10-12 before 23:23. Only the refused 898c4a50 does, and it wrote nothing.

There are two root causes in `scripts/ops/bars/ops_refusal_rejudge.py`.

1. `canon_at`. When no revision row was logged after `t`, it returns the canonical row as it was before the first repair. It never checks whether that row existed at `t`. A key that a later load inserted, which logs no revision, therefore reads as "stored at the refusal".
2. The `covered` test, which is exact-key evidence by request window. It trusts `window_start`, but `window_start` is wall-clock end minus duration. An IBKR RTH request with a seconds duration counts trading seconds instead. Request af8b35f1 persisted the window 2026-10-12 20:10 to 2026-10-13 00:05, yet its 48 bars are 16:00 to 19:55. The serve is therefore never recognised. The previous review made the same misreading: its finding 1 called these 80 slots "not served", and that was wrong.

Consequences:

- **Ratios.** The judged numbers are inflated. Without the 48 slots, the corrected ratios are:

  | Series | Changed | Stored | Ratio |
  |---|---:|---:|---:|
  | ADM | 14 | 623 | 2.25% |
  | AEP | 19 | 623 | 3.05% |
  | AMT | 18 | 623 | 2.89% |
  | AMZN | 15 | 623 | 2.41% |
  | ASML | 14 | 623 | 2.25% |
  | BA | 16 | 623 | 2.57% |

  All six still refuse, so the outcomes stand. The D-191-M per-load table still shows 671 stored and 27, 39, 32, 21, 26 and 31 changed, and the owner is asked to acknowledge that table.
- **80 pending rows should be released.** ADM 13, AEP 20, AMT 14, AMZN 6, ASML 12 and BA 15 are pending under the 23:23 loads, but the vendor answered those keys again 5 to 6 hours later. Raw holds that later answer, which by luck is the right state.
- **The ADM 19:55 story is inverted.** The volume went from 380,759 (served 2026-10-12 23:23) to 380,459 (served 2026-10-13 04:27). It did not go from 380,459 to 380,759 after the close. Both serves came hours after the close, and raw holds the later one.
- **Wrong text that follows from it:**
  - The reserve reason "raw holds less volume than the held offer (incomplete bar)" is wrong for the 2026-10-12 keys (ADM 19:55, AMZN 17:05).
  - The FIXES finding 1 paragraph is wrong for the same reason.
  - The `complete_bars.py` docstring cites ADM as its only evidence for the settle delay.
  - Test `test_a_held_offer_with_more_volume_than_raw_is_listed_for_a_re_serve` pins the inverted story.

Fix:

- In `canon_at`, treat a key as unstored at `t` unless a value is on record at or before `t`: a revision written at or before `t`, or an archive or raw row whose load predates `t`.
- For window evidence, persist the served range on `ohlcv_request` (first and last bar stamp) and match on that, never on `window_start`. For legacy loads, accept a load whose `n_new` slots fall on one date, with first_bar = last_bar = the key's date, only when its bar count equals the run of new keys.
- Rerun the decision dry. Release the 80 holds and drop or relabel the 2026-10-12 reserve keys.
- Correct the per-load table, FIXES and the docstring, and replace the test, before the owner acknowledges D-191-M.

### 2. MEDIUM: a hold is durable only above `revision_ratio_min_stored`; the one-session re-serve asks always accept, so the re-serve lane overrides refusals instead of verifying them

`should_refuse` returns False whenever `n_stored < min_stored` (500). The `--reserve-keys` asks now cover one session each (95a6463b0), so each holds at most 78 stored rows. Every re-serve is therefore accepted last-wins whatever it carries, and `answered_again` (9eeb0907f) then releases the hold.

For the 3,462 withdrawn keys of the six held loads, the end state after the re-serve is the per-key split that finding 2 of the previous review rejected. The new keys land and the restated keys stay held. The same path lets any small gap or tail fetch over a held span land the refused values. For example, a one-session ask on GE 2021-11 would land the two-decimal serve that d2adcf51 was refused for at 40%. That contradicts D-191-I ("however often the same values are offered again").

Fix: when an offer overlaps keys held under a refused load, judge it with that load's context. Either count the vendor's own stored values over the refused load's span, or route held keys to an explicit decision. Make the re-serve lane report per key whether the vendor re-served the held offer, re-served the stored value or served something new, and do not auto-release.

### 3. MEDIUM: refused request windows count as answered in the gap planner, so lost or withdrawn IBKR slots are never asked again

`_ANSWERED_WINDOWS_SQL` (in `_d1_gaps.py`) counts a `bars` request whenever the vendor holds any raw row in its window. It does not distinguish a refused request. The 15 unjudgeable loads lost their offers before this round, which is defensible to leave. However, 9 of their series have no later held load, so nothing owes them a re-serve:

- BAC, BKNG, CAT and CCJ have 0 IBKR sessions from 2026-10-01 to 2026-10-09.
- AGG, AVGO, CRWD, EDV and EMLC have 1 such session each.
- That is about 60 IBKR sessions in all.

Their refused windows (2026-09-27 to 2026-10-10) contain IBKR rows on 09-28 to 09-30, so `AnsweredWindows.covers` is true for those slots. Canonical holds Alpaca there, so nothing is NaN. But IBKR raw keeps a permanent silent hole, which contradicts "fetch per source, agnostic to other sources".

The same mechanism hides the 3,462 withdrawn keys; only the hand-made reserve list compensates. Fix:

- Exclude windows whose request matched a refused load, or mark refused requests on `ohlcv_request`.
- Add the 9 series' missing sessions to the re-serve list.

### 4. MEDIUM: the whole-session fallback moves the vendor step from intraday to day level, and a single missing primary bar flips the day

The IBKR to Alpaca volume ratio is far from 1, so every flip is a day-level volume step in rolling volume features:

- BKNG: about 0.38 in 2023 to 2025.
- MSFT: 0.62 to 0.95.
- SPY: 0.78 to 0.97.

Example: MSFT 2026-08-06 went whole to Alpaca because IBKR lacked a single bar, 16:55 UTC, where Alpaca has volume 163,185. That is a real IBKR hole that a re-fetch would fill, after which the session flips back.

Counts:

- The gate reports 558 fallback sessions in the 57 series.
- My sample of 12 other series has 15.

The choices exist only as structlog lines (`bar_selection.session_choice`). The reselect report has counts only; it has no vendor and no dropped stamps. Canonical replacements and the new routine deletions of dropped slots are logged nowhere else.

Completeness is measured against the union of vendors, not the calendar. A single-vendor partial session is therefore "complete" and invisible to the gate (ADM 2026-10-12: 48 of 78 IBKR slots).

Fix:

- Persist session choices in a table that features can condition on.
- Report sessions with fewer slots than the calendar grid as their own class.
- Ask the primary again (the gap planner) before a fallback session becomes durable.

### 5. LOW

- The apply report itemizes neither the 1,290 released pending rows nor the 438,346 restamps. The restamps' previous `served_at`, `load_id` and `request_id` are overwritten without a log. I reconstructed the released set from the first-repair reports: all 1,290 are in the archive under their refused load, and raw equals the offer. Fix: write release and restamp lists, with the old lineage, into the report.
- The TMUS regression class recurs on any reselect wherever raw holds a truncated bar that canonical masked. BLK and XTL 2026-10-09 14:10 already carry the truncated IBKR bar in canonical. The universe-wide count is still unknown (todo 535 item 19). Run that scan before plan 10 resumes the fetcher, using the IBKR to Alpaca volume ratio per bar against the session median at request ends.
- The `retract_unselected_slots` docstring says "the routine selection never deletes", but `select_and_write` now deletes dropped slots on the ingress path.
- `AnsweredWindows.partial` is never cleared. Raw presence wins, so this is harmless today, but a slot recorded as partial for which the vendor later serves no bar would be re-asked forever.
- IBKR 5m raw holds after-close bars (SPY 16:00 to 16:10 ET, 2006 to 2010; VIXY 2,942 and GE 70 off-hours rows). Under the union rule, any such slot after 2016 would make Alpaca incomplete for its session. No case was found in the sample, but no test covers it.

## Verified sound

- **Logging of re-judgment writes.** All 1,299 raw changes and 3,469 withdrawals are logged under the re-judge load with the exact old value. Raw now equals the target and the withdrawn rows are gone.
  - 3,462 withdrawn values are also pending, with equal values.
  - The other 7 are partial bars: HON 2026-03-09 15:26:34 off-grid, plus KRE, LEN, LLY, LMT, LQD and MCD 2026-10-13 14:00. All 7 are in the archive, and the 6 on-grid ones are on the reserve list.
  - 446 withdrawn keys have no canonical row, matching "retracted 446". 3,023 are canonical Alpaca.
  - Nothing a vendor served is lost; it is in raw, revisions or the archive.
- **Unjudgeable loads.** The 15 unjudgeable loads have no linked raw rows, revisions or archive rows. Their offers were lost before this round. Leaving them is defensible, apart from finding 3.
- **TMUS repair.** All 17 slots now hold the whole bar in raw and canonical. 17 revision rows under 31f313ab log the truncated values.
- **Session rule outside the 57.** The read-only gate on EWL, OII, IDA, RLI, WEAT, MDGL, AAPL, MSFT, SPY, BLK, XTL and CACI exits 0, with 0 mixed sessions, 15 fallback sessions, 6 incomplete sessions and 12 dropped slots. Canonical matches the session-level selection there.
- **Half days.** Alpaca `sip_rth` stamps after an early close are off-grid, so IBKR's 42-slot half days stay complete. Checked on the day after Thanksgiving, July 3 and December 24 from 2016 to 2025.
- **Complete-bar rule.**
  - It is judged against `answered_at`, and the missed-bar path uses the time asked as a lower bound.
  - The early close comes from the calendar, and the winter 4h bar ends at the close.
  - A missing settle delay refuses to persist.
  - Partial bars are noted on the buffered request row.
  - The IBKR leaf no longer applies policy.
  - The planner never covers a recorded partial slot.
- **Fingerprints.** No `ic_measure` job closure, no feature or research module closure, and no feature writer key reaches any edited module.
- **Locks.** `--reselect` takes the selection lock before the policy write. Ingress reads the policy under the lock. The re-judge takes the raw lock, then the selection lock, in the same order as ingress.
- **Tests.** The new tests for session selection, held keys, answered-again, 4h close, early close and answer time would fail on the old code. The gaps are listed in findings 1 and 5.

## Could not verify

- Where the stored IBKR values from before 2026-10-10 came from (for example ADM 2026-09-23 14:00 = 82.40); no request row exists for them.
- Whether IBKR closing bars really settle within 1,800 s. The only cited example is inverted (finding 1).
- The re-serve lane and live `partial_bars` recording end to end, because the fetcher is held.
- The universe-wide count of truncated IBKR bars, and whole-table session-rule equivalence beyond the 57 plus 12 sampled series.
