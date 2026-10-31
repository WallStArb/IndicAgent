# Simplify findings: 185/189 load-bearing code (wave 2)

Original: 2026-10-10 (findings only, none applied; filed as the post-backfill cleanup
backlog, todo 527).
Archived 2026-10-31: findings record; the open items live on as todo 527 and deferral D-191-H.

Kept: the answered-window SQL existed in five copies (plan 191-06 consolidated one copy); the
5m load-and-shape logic was copy-pasted between writer and auditor, where recipe drift is
self-masking, with tripled per-row timestamp conversion (order 10^8 conversions per night);
the month-digest recipe (the D-07 identity contract) existed three times; the audit re-ran
route-disagreement checks only to log a count. Items 3 to 9 remain open, deferred as D-191-H
(owner acknowledgement pending).

Full text in git history at docs/plans/2026-10-10-simplify-findings-185-189.md as of 708f3fe09.
