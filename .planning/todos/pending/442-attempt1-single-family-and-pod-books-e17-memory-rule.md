---
status: pending
priority: P1
filed: 2026-09-26
source: adopted unified design (todo 436), sections 4.1 and 4.5; Fable review items 3 and 6
---

# Attempt 1 as single-family books plus a pod book; E17 memory rule for fitted combiners

## What

1. `spec.py` `_check_book` refuses a book whose families differ in panel, horizon or factor spec,
   so families 1 (15m, horizon 2) and 2 (session legs, horizon 1) cannot share a book. Run them as
   two single-family books, then a pod book whose series is the session-level sum of their E17 D_s
   series (its own book type and attempt).
2. The runner passes `memory_sessions = max(slot_histories)` for books, which ignores a fitted
   combiner's training reach and a partial-adjustment rate below 1. Set L = member memory +
   combiner training reach + horizon-rule reach, and add ridge and kappa cells to E17's H0 battery
   before any attempt uses them.
3. Anchor combiner refits to calendar dates rather than the panel's first row, so forward runs
   refit on the same dates.

Owned by the phase 183 session (owner of `runner.py`, `timing.py`); coordinate before editing.

## Done when

Attempts 1a, 1b and 1c are runnable and the H0 battery covers fitted combiners.
