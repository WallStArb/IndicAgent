---
phase: 187-research-core-recipe-book-selection-construction
plan: 09
status: complete
completed: 2026-10-28
commits: [67dce9b31, 0e3d292bb, e8dc93371]
requirements: [R-187-16, R-187-17, R-187-18]
---

# 187-09 summary: missing members, calendar-anchored refits, in-fold signs

- Task 1 (67dce9b31): `min_members` on both combiners. Equal weight keeps each member's 1/K and
  an absent member contributes nothing; the ridge predicts a partial cell with the fold's best
  linear forecast from the present members. The AGY rescale was reversed in review.
- Task 2 (0e3d292bb): `refit_anchor` puts ridge refits on the exchange-session grid through the
  anchor (the calendar S0 checks, never business days), so panels starting on different rows
  refit on the same sessions; a missing session moves a refit to the next panel session.
  `Combiner.combine` takes `row_session_dates`; `run_book` and `book_timing` pass it.
- Task 3 (e8dc93371): a sign of `in_fold` takes the sign of the member's trailing fold IC (mean
  per-row cross-sectional correlation of its z-score with the target) over
  `sign_window_sessions`, refit every `sign_refit_sessions`, with the ridge's embargo; zero or
  undefined IC, or no full window, makes the member absent. window + embargo enters
  `book_memory()`. Trailing, not expanding (owner 2026-10-27), recorded as an E17 ledger
  amendment.

Each field is optional and unset reproduces the old output and spec hash. Admission: each rule
needs its own battery cell (`<kind>_min_members_<n>`, `<kind>_refit_anchor`,
`equal_weight_in_fold_signs`), and an in-fold book is admitted only at the certificate's
`in_fold` settings. No cell exists yet; none is needed until a book uses a rule.

Deviations: Task 2 was written by indicagent-b1's executor, whose session died before it
committed; indicagent-5b verified and committed it. Task 3's review was a fresh Claude reviewer
(Codex and AGY were out of quota); its findings were fixed before commit (empty grid crash,
the window mean summed directly so a zero IC is exactly zero, the certificate pin, two
stronger tests). Verification per task: full unit suite, repro_frozen bit-identical.

Open: a book with both `refit_anchor` and in-fold signs needs two separate cells, and no cell
certifies the pair together.
