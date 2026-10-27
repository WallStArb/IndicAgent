---
phase: 187-research-core-recipe-book-selection-construction
plan: 03
status: code-complete; backfill run pending
completed: 2026-10-27
commits: [f837a124f, 78acea146]
requirements: [R-187-05]
---

# 187-03 summary: backfill of the pre-515 series

- `spec.load_spec_from_blob` parses a family spec from a recorded spec_blob; `run_family`
  results carry each member's `AttemptSeries`; `ledger.backfill_series` writes only
  `research_run_series` for an already terminal run (S6 stays the sole writer).
- `scripts/research/backfill_attempt_series.py` replays each completed evidence run from its
  stored snapshot with its exact spec blob through the synthetic path and accepts it only when
  the decision block equals the recorded one exactly; anything else is `series_unavailable`,
  never loosened. Dry run by default, `--apply` writes, `--specs` resumes per spec; plan 07
  added `--compare-all` (the E17 parity gate).

Run state: the dry run replayed 12 of the 20 family 1 runs (h2, h26, h4) exactly equal before
the session's memory reaper stopped it. Remaining: a dry run of `--specs
research/specs/family1_h8.yaml research/specs/family1_intraday_periodicity.yaml`, then
`--apply` over all 20 once every replay is equal. Both wait on the owner's restart go-ahead.
Until then `select_books.py` refuses (a missing series is not a result) and only
`--diagnostic` prints a set, marked `"result": false`.
