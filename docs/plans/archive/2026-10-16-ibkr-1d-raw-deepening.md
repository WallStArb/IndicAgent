# IBKR 1d raw deepening (scoped full-scan pass)

Original: 2026-10-16 (armed and executed via scripts/ops/bars/ops_ibkr_1d_deepening_gate.sh).
Archived 2026-10-31: executed operations pass, kept for the gap mechanics.

Kept: 1,135 of 1,529 names had unadjusted 1d raw history starting later than their own ibkr
head floor (about 3.66M missing sessions); the old deep fetch used ADJUSTED_LAST, and
smart_adjusted rows are excluded from 1d coverage by DAILY_NOT_COVERAGE_KINDS, so those names
are deepening candidates too. The limiter was cadence, not code: full depth is planned only
on --full-scan or a series' weekly gap-fill slot. The gate script self-removes from crontab
on completion. Consumer context: the damaged-basis names wait on this deepening (todo 535
item 42).

Full text in git history at docs/plans/2026-10-16-ibkr-1d-raw-deepening.md as of 708f3fe09.
