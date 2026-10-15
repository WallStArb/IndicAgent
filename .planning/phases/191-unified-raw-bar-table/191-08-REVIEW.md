# 191-08 review (range 40bec424c..HEAD)

Scope: daily and grid stages over ohlcv_raw, serve-time last-wins, restatement flag gating, detector v2, migration 485. Read-only; SELECT-only SQL.

## Verified sound

- Serve-time last-wins is enforced twice: Python classification (`_classify_series`, `answered_at >= stored_at` or stored NULL) and the SQL guard in `_UPSERT_TAIL`. The series advisory lock is held from preview to commit, so the preview and write counts agree (and the contract raises if they do not).
- Every replaced value goes to ohlcv_revision before the replacement; every superseded offer is logged as origin `superseded`. No other code path in `scripts/` or `services/` writes ohlcv_raw except ops_raw_backfill (DO NOTHING inserts and a `_LATER_SERVE` reconcile update that treats NULL as oldest and logs the displaced value).
- Live: no raw 1d row has NULL served_at (`observation_from_raw` raises on one), none is in the future, `ohlcv_revision` origins are load/archive_segment/raw/superseded with exactly 80 superseded, `ohlcv_restatement_flag` has 0 rows and the reviewed_at/reviewed_by pairing check holds. Migration 485 is transactional with lock_timeout, a NOT VALID then VALIDATE constraint swap, and a count assertion on the 80 relabeled rows.
- Daily SELECT keys on (vendor, kind) pairs via unnest, so listing-venue kinds and smart_adjusted cannot enter. Daily no_data coverage subtracts transport failures only (measured rationale in the docstring).

## Findings

### M1 (medium): an unchanged re-serve does not advance served_at

Stored V2 at t2, vendor re-confirms V2 at t4 (nothing written, served_at stays t2). An artifact fetched at t3 (t2 < t3 < t4) holding the older V1 then replaces V2, because t3 >= t2, although the vendor reaffirmed V2 after t3. The old V2 is logged, so it is recoverable, but raw (and the 1d changed-since probe) moves to a value the vendor no longer serves. Narrow window: needs a replay of an artifact fetched between a change and a later confirm. Fix: on an unchanged offer with `answered_at > stored served_at`, advance served_at (and request_id) without a revision; or document that replays are only safe for artifacts older than the oldest unconfirmed serve. Note the 1d probe `served_at > baseline` would then re-trigger every night, so keep a separate `confirmed_at` column instead of reusing served_at.

### M2 (medium, bounded): Alpaca answered_at is file mtime

`_alpaca_5m_answered_at` uses `st_mtime`. Any rewrite or in-place append of `{symbol}_5Min.parquet` re-stamps the whole file, so old bars in it look newly answered and beat a nightly re-serve that happened between the pull and the rewrite; a copy without preserved mtime does the same. 220,097,578 alpaca rows have NULL served_at, so for those any replay wins regardless. Mitigation already in the docstring (keep artifacts in place); add a loader check that refuses an artifact whose mtime is later than its newest bar's session plus a bound, or record the fetch time in a sidecar at pull time.

### L1 (low): ops_d1_bootstrap stamps answered_at = write time `now`

`ops_d1_bootstrap.py:133` stamps legacy corpus bars with the import time. Fine as a one-time load before any nightly; if re-run later it beats newer serves. Gate it on "no 1d raw row newer than the corpus" or stamp with the corpus request's recorded time.

### L2 (low): detector blind below signature_min_bars (5)

A basis change confined to fewer than 5 replaced bars in one chunk (a short nightly window) raises no flag, and older bars stay on the old basis. For 1d the split records in the d2 rule cover this; for 5m a 1-session overlap is 78 bars, so it is judged. No action needed before 191-10; keep todo 535 aware.

### L3 (low): resume is not mechanically gated

`ohlcv_history_fetcher` marks a run partial on `n_basis_flagged` but does not read `read_unreviewed_basis` at start; the timer keeps landing last-wins restatements on top of unreviewed flags. This matches D-191-N (nothing refused), the selection gate (exit 3) and the D7 gauge are the control. Resume discipline therefore depends on running ops_selection_gate (clean, exit 0) before re-enabling the timer.

### L4 (low): test-caller filter drops the whole raw row

`_SELECT_DAILY_RAW_SQL` excludes a row whose last serving request has caller `test-%`; raw keeps only the last value, so a fixture overwrite removes the real value from the daily input rather than falling back to the prior one (the revision log holds it). Real data has no test callers live; only matters if a test hits the live DB.

## Verdict

No HIGH findings. No path found that silently corrupts raw, skips the revision log, or bypasses the serve-time compare.

- Plan 191-10 can start.
- The fetcher can resume after 191-10 provided ops_selection_gate exits 0 first (no unreviewed basis flags, no unselected slots; it last exited 3 on 26 IBKR re-serve slots) and no Alpaca artifact is replayed from a rewritten/copied file (M2). M1 is a documented-risk item, not a blocker.
