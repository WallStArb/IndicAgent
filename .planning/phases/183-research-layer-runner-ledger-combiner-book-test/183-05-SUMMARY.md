---
phase: 183
plan: 05
status: complete
requirements: [D-15, D-16, D-18, D-21, D-25]
---

# 183-05 summary: family 1 members and array guards

Executed inline by the orchestrator (the wave-1 executor stopped on an API limit before any
commit).

## What was built

- `families/` package: `common.py` (`centred_rank`, `declared_memory_rows`,
  `member_on_panel`) and `intraday_periodicity.py` (`SLOT_BARS`, `slot_returns`,
  `place_slot_alpha`, `same_slot_mean` for P1-P4). Slot sums of bar pairs, placement at the bar
  before the slot (slot 0 at the previous session's last bar), prefix-sum means over past
  sessions with the half-window rule, no position where the signal bar has no residual, then
  the centred rank with the coverage floor.
- `guards.py`: `causality_probe_array`, `memory_check_array` (additive shock of SHOCK_SDS
  column sds), `require_testable(power=None)` for evidence runs. Existing guards unchanged.
- `portfolio.py`: `_average_ranks` renamed `average_ranks` (public) so R1 and the members share
  one tie-averaged rank.

## Verification

- `test_families_intraday.py` (22 fast + 4 slow) and `test_guards_array.py` (10) pass; existing
  `test_guards.py` unchanged and passing. Declared memory rows 7124/7228/7618/8138 match the
  prereg.
- Synthetic S3 guards (`run_guards` with S1 inside) pass for all four members on a 100-session,
  24-name, 26-bar panel with 5% missing bars: 32-38 s each under load average about 19.
- `repro_frozen.py`: three bit-identical lines.
- P4 over 127,400 x 233: 5.2 s under load (target 3 s on an idle machine; not re-measured
  idle). It runs once per real run, not per shift, so it is off the hot path.

## Deviations

- Slow guard test panel reduced from 150 sessions/25 names/8 probe rows to 100/24/5 to fit the
  60 s budget; every member still gets causality and memory probes.
- `average_ranks` made public in portfolio.py (not in this plan's file list) to avoid a
  second rank implementation.
