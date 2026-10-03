---
status: pending
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
