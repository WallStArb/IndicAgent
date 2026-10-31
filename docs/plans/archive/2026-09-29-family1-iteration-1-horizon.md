# Family 1 iteration 1: does the same-slot alpha persist beyond its slot?

Original: 2026-09-29 (exploration, in-sample before oos_start; ran through the runner).
Archived 2026-10-31: voided-era exploration, results voided by the owner's 2026-10-30 reset; superseded by the 2026-10-27 daily residual family prereg.

Kept finding: the same-slot edge is slot-local. Edge per unit traded falls from 0.07 to 0.10
bp at a 2-slot hold to about a fifth of that by the session close, so a longer hold dilutes
rather than accumulates; turnover is about 26 units per session at every horizon. Run groups
h2/h4/h8/h26 recorded through the runner (48b7a104, 3492bf3f, c962934b, 684a5aa7).

Full text in git history at docs/plans/2026-09-29-family1-iteration-1-horizon.md as of 708f3fe09.
