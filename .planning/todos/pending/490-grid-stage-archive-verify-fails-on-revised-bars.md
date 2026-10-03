---
status: pending
priority: P1
filed: 2026-10-03
source: interactive session (185 session), found while verifying 185-18 Task 0
---

# Grid stage fails every night: archive verify refuses 7 symbols whose recent bars were observed twice

## What

`services/bar_derivation.py` `--stage grid --apply` fails for A, AAP, ABBV, ACRS, ACVA, ADBE and ADP
on every run (`bar_derivation_batch`: `failed: 7, unchanged: 233`, repeating, status `failed`), so the
nightly's grid stage exits nonzero and the nightly reports `failed` until this is resolved. The
verify (`_ARCHIVE_VERIFY_SQL`) is doing its job: it refuses to DELETE a stored 15m/1h segment when an
archive row under the same key has different values, and the whole symbol transaction rolls back
(nothing is lost; `n_archive_rows` stays 0).

Diagnosis (live DB, 2026-10-03): across the 7 symbols 15 to 40 bars each differ (15m and 1h,
source `ibkr_named` on both sides), all dated 2026-09-28 to 2026-10-01. Differences are one-cent
price moves and volume changes of a few hundred to a few thousand shares, in both directions. That
is two observations of the same bar taken at different times inside IBKR's revision window (late
prints, adjusted volume), not corruption. The archive keeps the first write per
`(symbol, timeframe, timestamp)` (`ON CONFLICT DO NOTHING`), so a later or earlier second
observation can neither be added nor be allowed to vanish, and the verify correctly stops the
delete.

## Why it matters

Raw observations are permanent (principles: never drop data that could contain signal). Today the
archive has no way to hold both observations of one bar, so any bar fetched by two paths inside the
revision window blocks its symbol's grid derivation forever. Other symbols are exposed the same way
whenever a re-fetch overlaps a stored segment.

## Fix (decision needed before building)

Recommended: make the archive an observation history, key `(symbol, timeframe, timestamp,
observed_at)` or an equivalent revision column, so the second observation is appended rather than
dropped, and have the verify compare the latest archived observation per key against the stored row.
Alternatives, weaker: (a) `DO UPDATE` to the later observation (loses the first, breaks the
permanence rule); (b) hold derivation for bars younger than a settle window (APR
`infra.bar_derivation.revision_settle_days`) and verify only settled bars, which leaves a window of
unverified deletes but never discards an observation. The intraday redesign
(`docs/plans/2026-09-29-intraday-bar-store-redesign.md`) and phase 189's single fetcher own the write
path, so this should land with or before 189-04.

Until fixed, the 7 symbols keep their stored 15m/1h rows (nothing deleted) and the grid stage's exit
code is the loud signal; do not special-case the failure away.

## Also found

`tests/unit/scripts/test_nightly_lease.py` patched only the daily stage, so every full unit run
spawned a real `bar_derivation.py --stage grid --apply` against the live database (nine runs
2026-10-03 04:01 to 04:58 UTC, the first derived 74 symbols and 7.7M rows through the normal
idempotent changed-only path). Fixed in the 185-18 follow-up commit; a CI guard that no unit test
spawns `bar_derivation.py` would close the class (not built).
