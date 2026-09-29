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

## Result (2026-09-29)

Reconciliation passed: the 5m path matches the raw 15m return on the same rows in every cell
(opening, mean5 keep 0.5: 1.176 against 1.183 bp per session; closing 15:30 to close: 0.584
against 0.591), and the residual-target rows reproduce iteration 3 (opening keep 0.5 mean5 1.44
bp, E 0.72). Raw returns run slightly below the residual target at the open (1.18 against 1.44
bp). Output: the script's JSON (git-ignored scratch); 5m spreads: 39 names, 30 sessions to
2026-09-29, `docs/research/family1-spread-sample-5m-2026-09-29.csv`.

Where the P&L accrues (E17, bp per session and E per unit traded):

- Opening slot: all of it by 09:35. The 09:35 value is 101% to 109% of the 10:00 value in every
  member and keep; the path is flat to 10:00 and gives back about a fifth just after 10:00. At
  keep 0.1 (mean of the two members) E is 1.42 at 10:00, 1.17 at 10:15, 1.09 at 10:30, 1.01 at
  11:00.
- Closing slot: 59% to 69% of the 15:30-to-close P&L arrives after 15:50, and about 38% in the last
  bar including the closing print.

Rules as set:

| Opening exit | E | half of median half-spread | net |
|---|---|---|---|
| 10:00 | 1.42 | 1.93 | -0.51 |
| 10:15 | 1.17 | 1.51 | -0.35 |
| 10:30 | 1.09 | 1.51 | -0.42 |
| 11:00 | 1.01 | 1.21 | **-0.20** (chosen) |

| Closing entry | E to close | half of median half-spread | net |
|---|---|---|---|
| 15:30 | 0.61 | 0.87 | -0.26 |
| 15:40 | 0.52 | 0.74 | **-0.22** (chosen) |
| 15:45 | 0.48 | 0.73 | -0.25 |
| 15:50 | 0.39 | 0.82 | -0.43 |

- Front-loading is above one half at the open (about 100%), so the opening edge depends on the
  backtest's 09:30 price being a price one can trade at, which is unverified.
- Net E is negative at the chosen timing in both slots, so by the rule set in advance the
  standalone slot book ends at any timing on this grid, and todo 458 (overlay) stays the route.

Reading (not a rule outcome): the edge sits at the two auction prints, a move away from the
opening print and a move into the closing print, consistent with recurring per-name auction
imbalances. An auction fill crosses no spread, and the opening slot's E is still about 1.0 at
11:00, so an opening-auction-to-closing-auction hold would pay no half-spread on either leg. That
is a new question outside this grid; it needs its own criteria before its curve is read, and a
check that the stored open and close are the official auction prices.

## Reporting: gross monthly returns, 2020 to 2025 (not a test)

Requested for an outside description of the strategy. `scripts/research/family1_monthly_returns.py`,
201 non-`compute_eligible` names (the slots were chosen on the 233, not these), open plus close
slots, `same_slot_mean20`, one-slot hold, entry and exit at the runner's prices, gross of all cost,
in-sample. Percent of capital deployed per slot, summed over sessions.

| Year | keep 0.1 | keep 0.05 |
|---|---|---|
| 2020 | 30.5% | 29.7% |
| 2021 | 22.1% | 29.8% |
| 2022 | 12.4% | 14.2% |
| 2023 | 13.7% | 19.6% |
| 2024 | 10.3% | 11.3% |
| 2025 | 27.4% | 47.2% |

Average month 1.62% (keep 0.1) and 2.11% (0.05); up months 59 and 60 of 72; worst month -1.55% and
-4.13%; gross Sharpe 3.9 and 3.4. March 2020 is 13.4% (0.1) and 13.6% (0.05), April 2025 5.6% and
9.7%: the book earns most when volatility spikes. On the 233 names over 2024 to 2025, keep 0.05 was
worse than keep 0.1 on both return and Sharpe (4.0 against 4.6 bp per session, Sharpe 2.5 against
4.5), so the ordering of the two keeps is not stable across name sets. At the measured half-spreads
every year is negative net (iteration 3 and the table above). The 233-name months for 2024 to 2025
were computed with the 15m runner prices and are in the script's JSON output (git-ignored scratch).
