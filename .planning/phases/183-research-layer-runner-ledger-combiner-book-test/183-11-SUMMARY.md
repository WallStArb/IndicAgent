---
phase: 183
plan: 11
status: complete
requirements: [D-26, D-27, D-28, D-29]
---

# 183-11 summary: E16 adopted and built

Owner adopted methodology-change-ledger E16 on 2026-09-25 and asked for it to be built in this
phase. Executed inline (subagents unavailable until the weekly limit resets).

## What was built

- `statistics/hac.py`: the unfloored Newey-West mean t E16's simulations used (lag rule, Student
  t df n - 1), tested against the simulation script's `nw_t` to 1e-12.
- `research/timing.py`: the timing P&L series and test, static tilt per (bar-of-session,
  symbol), returns causally demeaned.
- `research/book.py`: `book_timing` (ridge once, R1, timing test) and `book_memory_rows` for the
  diagnostic shift set; the refit-per-shift construction deleted.
- `research/power.py`: replicates scored by `book_timing` at the bar, exact fixed-R curtailment,
  pool cancels queued work once decided; `b_max`, `replicate_passes` and the stop flag deleted.
- Runner: one measurement path for members and books (timing decision, shift-null diagnostic,
  evidence v2); only a book's power refuses; `PowerSpec.stop_check_every` removed.
- Docs: E16 marked ADOPTED with the two refinements and their numbers; evidence framework
  sections 5, 6, 7 and architecture S8 updated; CONTEXT D-26 to D-29.

## The refinements and the evidence for them

`scripts/analysis/e16_null_size/slot_tilt_size.py`, 4,000 H0 simulations per cell (slot fixed
effects, one factor, t4 noise, volatility clustering, persistent predictor aligned with the
fixed effects), rejection at the 0.00167 bar:

| Tested series | fe 0.03, tau 40 / 200 | fe 0.3, tau 40 / 200 |
|---|---|---|
| adopted: per slot, returns demeaned | 0.00075 / 0.00175 | 0.00075 / 0.00250 |
| pinned: per slot, raw returns | 0.0010 / 0.0040 | 0.042 / 0.152 |
| per-symbol tilt | 0.00275 / 0.0060 | 1.0 / 1.0 |

The adopted series held size at 0.05 (0.047 to 0.054) and 0.01 (0.0085 to 0.011) as well.

## Verification

- `pytest tests/unit/research tests/unit/test_hac.py`: all pass, slow tests included.
- `repro_frozen.py`: three bit-identical lines. Vulture clean for the research package.
- Live `research_run`: 0 rows.
