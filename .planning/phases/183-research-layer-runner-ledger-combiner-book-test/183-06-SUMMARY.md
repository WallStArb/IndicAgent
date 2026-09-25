---
phase: 183
plan: 06
status: complete
requirements: [D-10, D-11, D-16, D-17, D-18, D-22]
---

# 183-06 summary: S8 book test

Executed inline by the orchestrator (subagents unavailable until the weekly limit resets).

## What was built

`book.py`: `BOOK_ARM`, `flatten_stack`, `book_returns` (unflatten, refit S7 on the given stack
against the unshifted target, R1), `book_weights`, `book_memory_rows`, `book_sharpe` (shift 0
is the observed book), `book_construction` (the picklable partial), `evaluate_book` (the
unchanged `evaluate()` with the book construction, session scoring on, embargo from the ridge
spec).

## Verification

- `test_book.py`: 10 fast tests (flattened roll equals the joint stack roll; book equals ridge
  then R1 by hand; the ridge runs 1 + K times and each null Sharpe equals an independent
  `book_sharpe` at that shift; the post-fit alternative gives a different null; whole-session
  shifts equal `session_shifts`; memory 8141 for family 1; a 160-session panel is refused on
  shift count; complete cases; pool equals serial; planted book p < 0.05, unplanted not).
- Slow `test_book_null_is_calibrated`: 100 unplanted panels, rejections at p < 0.05 inside the
  99% binomial band at the exact nominal size; 25 s.
- Full-size book shift (127,400 x 233 x 4 float32, half the rows empty): 2.04 s median of 3 at
  load average about 13-16. Under the 3 s ceiling, above the 2 s target. The power check in
  plan 08 scales linearly with this: research's 60-75 CPU-hour estimate assumed about 1 s, so
  expect roughly double unless plan 08 finds a saving.
- `repro_frozen.py`: three bit-identical lines.

## Notes

- Peer session indicagent-63 reports the whole-session shift null is anti-conservative in the
  tail for slow signals (about 1.25x size at p 0.00167 for a 40-session mean) and is
  validating a sign-flip surrogate calibration (E16). The 0.05-level calibration test here
  does not probe that tail. Plan 10's book test waits for E16.
