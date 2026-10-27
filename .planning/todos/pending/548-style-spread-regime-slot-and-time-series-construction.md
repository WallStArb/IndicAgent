---
status: pending
priority: P2
filed: 2026-10-27
source: docs/ideas/signal-participation-state-style-spreads.md (revision 2026-10-27)
---

# Style spreads: an S7 regime input slot and a time-series spread construction

## What

The owner's participation-state idea (RSP/SPY and the other style spreads) has two parts, and
neither can run through the research runner today:

1. Part A conditions a base book's members on a continuous regime variable (`s` and `s x z_t`).
   S7 has no regime input slot, and no phase 187 plan carries one. The slot must add the
   state's reach (314 sessions for the declared RSP/SPY state) to `book_memory()` (design 4.5),
   or E17 is coupled again.
2. Part B is a time-series book on spread returns (long or short a spread's two legs). The
   runner runs only R1 (`_require_r1` in `runner.py`), a cross-sectional rank construction.

## Plan

1. Slot: a causal `[T]` float series, computed from the panel S0 already loads, entering S7 as
   interaction members; its reach joins the member term of L; the S3 causality probe covers the
   state function. Built for this one consumer (design doc section 5); generalize only when a
   second state (for example a market-level volatility z) arrives.
2. Construction: a time-series rule for a fixed set of two-leg spreads, gross statistics through
   E17 like every book; a horizon above one session waits for todo 547.
3. Part B's synthetic power check against StepM runs first and needs neither; if it refuses,
   step 2 is not built.

## Done when

Part A's pre-registered variant and Part B's book (if its power check passes) each run as one
counted attempt through the runner, after plan 191-20's 1d re-derive.
