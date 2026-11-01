---
status: done
priority: P1
filed: 2026-10-03
source: interactive session (universe wave 2 review)
---

# Universe membership: a stored entry date and cohort per name, with the symbol set hashed into the S0 snapshot

## What

The research spec's `universe` field names a dimension (`compute_eligible_1d`), not a snapshot, and
`instruments` has only `created_at`. Promoting wave 2 (597 names) changes the S0 panel under any
future `repro_frozen` comparison or counted look without leaving a trace. A name onboarded in 2026
enters the panel for its whole 2006 history, so a size or momentum test cannot tell which names were
selectable at t.

Two selection biases need to be visible to research, not only to the README:
- Wave 2 and batch 1 picked names by today's market-cap rank (Russell 3000 holdings, current
  members). Today's rank reflects past returns, so it is an outcome-conditioned selector.
- The README's cohort labels sit in manifests only; the database does not know a name came from
  `r3k_501_1000` or `spx`.

## Fix

1. Store per name: `universe_entry_date` (onboarding date) and the batch/cohort label (tag or column,
   one writer, set by the onboarding script).
2. Hash the promoted symbol set into the S0 snapshot key and record it on `research_run`, so a
   changed universe changes the run's identity (E18 counting, `determinism`, `point_in_time`).
   Not called a vintage: the glossary defines `vintage` as a dated data span counted for the
   selection test, and this is membership.
3. Add the cap-rank bias to the SOP's "Known biases" list (done with this todo's filing), and
   put the membership rule in the unified design's S0 section when this lands.

## Gate

Before the first counted research run after 185/186. Edits under `src/intelligence/research/` need
`repro_frozen` bit-identical; new optional spec fields go in `_OPTIONAL_*_FIELDS`.

## Status

Landed 2026-10-31 (migration 551, applied live and committed in the same breath).

- **Shape.** Plain columns on `instruments` (`universe_entry_date date`, `universe_cohort text`),
  not ITR tags: membership is universe governance, a sibling of migration 337's eligibility
  columns, not a claim about what the instrument is (ITR's own rule); one writer,
  `onboard_instrument()`, called by the manifest onboarder with the row's cohort. Hash: a separate
  nullable `research_run.universe_hash` column (sha256 over the S0 snapshot's symbol list,
  computed in `runner._load_panel` and written by `finish_run` beside `snapshot_hash`,
  NULL-to-value once per the migration 551 guard), not a snapshot-hash composition change: the
  symbol set is already inside the snapshot's content hash via meta.json, so the column adds the
  explicit, queryable identity with no mechanism and no recorded run moves.
- **Backfill counts.** 1,551 instruments, all 1,551 got `universe_entry_date`
  (`created_at::date`; verified equal to the manifest batch date for every one of the 1,256
  manifest-named names, zero mismatches, so nothing is invented), 1,256 got a cohort from the
  five committed manifests (25 cohorts), 295 pre-SOP names (2026-05-15 to 2026-09-16) have cohort
  NULL. XWEB, manifest-named but IBKR-rejected, has no row and got nothing.
- SOP "Known biases" cap-rank entry: verified present at filing; reworded to the landed columns.
  Membership rule added to the unified design section 3.1 and a `universe membership` glossary
  entry.
