# Family 1 iteration 4: where inside the opening and closing slots does the P&L accrue?

Author: Claude (Opus 5.5), with Brandon. Informed by: iteration 3
(`docs/plans/2026-09-29-family1-iteration-3-open-close-slots.md`).

Status: exploration. Outside the runner, no `research_run` rows, no verdict. The rules below are
set before any number from this iteration exists.

## Question

Iteration 3 found the opening and closing slots carry about 78% of the family's gross P&L, and
that neither clears measured cost as a standalone book. The cost sits on one leg per slot: the
opening slot enters at the auction and pays the continuous half-spread at its 10:00 exit (3.9 bp
median on the 233 names); the closing slot pays it at its 15:30 entry (1.7 bp) and exits at the
auction. Spreads fall steeply after the open (4.8 bp at 09:45, 3.0 at 10:30). If the opening
slot's P&L holds after 10:00, a later exit pays less; if the closing slot's P&L arrives late, a
later entry pays less and holds less risk. The signal, the names and the trade count do not
change: 5m bars move only the timestamp of the continuous-market leg.

## Method

`scripts/research/family1_event_study_5m.py`. The runner's weights (15m panel, 233 names,
members `same_slot_mean5` and `same_slot_mean20`, keep 0.5 and 0.1, signal rows 25 and 23) are
applied to 5m price paths: the opening slot's cumulative log return from the 09:30 open to each
5m bar open through 11:00, the closing slot's from the 15:00 open through the close. Each point
is the E17 timing statistic (bp per session, E per unit traded at the slot's turnover, HAC t).
Raw 5m returns, since S1 has no 5m residual; the book is dollar neutral. In-sample, scored span
2010-01-04 to 2025-12-23. The 15:00 to 15:30 segment is before the runner's entry and is
descriptive only.

A 5m spread sample runs alongside: IBKR BID and ASK 5m RTH bars, last 30 sessions, the same 39
names as the 15m sample, half-spread at each bar's open.

## Checks and rules, set before any result

- Reconciliation first: the 5m path at 10:00 (opening) and from 15:30 to the close (closing)
  must match the raw 15m panel return on the same rows to within 5% of its bp value. Otherwise
  stop and find the misalignment.
- Opening exit, one rule: exit time t is chosen from {10:00, 10:15, 10:30, 11:00} as the one that
  maximizes E(t) minus half the median 5m half-spread at t, computed on keep 0.1, averaged over
  the two members. Other keeps and members are reported, not used to choose.
- Closing entry, one rule: entry time t from {15:30, 15:40, 15:45, 15:50}, E from t to the close
  minus half the median 5m half-spread at t, same averaging.
- Front-loading, reported: the share of the 09:30 to 10:00 P&L reached by 09:35. Above one half
  means the opening edge depends on getting the auction print, which is unverified (the 09:30 5m
  open equals the daily open on 99.95% of name-days in 2024 to 2025, consistent with an auction
  print but not proof).
- Standalone test of the chosen timing: net E per unit above zero at the median spread. Positive
  net E makes the rule the next book candidate; it still needs confirmation on the replication
  names once their 5m history lands (todo 449's 5m lane), then the forward span once. Negative
  net E ends the standalone slot book at any timing and leaves todo 458 (overlay) as the route.
- Counted as one look on the 233-name set. No other timing grid is read.

## Result

Pending.
