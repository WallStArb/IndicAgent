---
status: pending
priority: P2
filed: 2026-11-18
source: B-H review (todo 609): the H-C seasonality members need the panel's session dates; the book and power paths do not bind them
---

# Bind session dates for calendar members in the book and power-calibration paths

## What

`runner._member_fn` binds `session_dates` for a member marked `needs_session_dates` (the H-C members in
`families/seasonality.py`). Two other paths build members as `(resolve_member(m.signal), params)` and never pass the
dates: `synthetic._member_stack` (power calibration) and the book run in `runner.py` (`run_book`). A book that holds an H-C
member raises a TypeError (missing keyword-only argument) at the power calibration step. The failure is loud and no book
holds such a member today.

## Done when

- One helper builds a member's callable for any path (the family run, the power check, the book run) and binds the dates from the
  path's own panel.
- A unit test builds a book with an H-C member on a synthetic dated panel and runs the power calibration to completion.
- `repro_frozen` bit-identical.

## Not before

Any book registration that contains an H-C member. Until then it is a known loud failure.
