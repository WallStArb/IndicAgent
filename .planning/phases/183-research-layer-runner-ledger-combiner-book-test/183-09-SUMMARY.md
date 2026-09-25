---
phase: 183
plan: 09
status: complete
requirements: [D-04, D-08, D-09, D-11, D-16, D-17, D-18, D-21]
---

# 183-09 summary: runner book mode and book version 1

Executed inline. Book mode, `book_v1.yaml`, CLI book mode and the power-mask fix
(replicates planted on the real residual availability, not the close mask) landed on main.
The book statistic was then replaced by E16 in plan 183-11, which rewrote the S8 and power
paths; see 183-11-SUMMARY.md.

## Full-size synthetic dry run (old shift-null path)

4,900 sessions x 233 names x 26 bars, 4 workers, load average about 20: S1 2 h 05 min (two
residualizations), S3 guards 1 h 20 min, plant calibration 19 min (plant 0.0141, IC 0.00193
against 0.002). Stopped during the power replicates once E16 made that path obsolete. Plan 10
should budget roughly 3.5 hours for S1 and guards at that load (much less idle), plus E16 power
(about 40 s per replicate).

## Deviations

- The dry run used 4 workers, not 8 (about 3 GB per worker, 14 GB available).
- CI hygiene in the same push: research excluded from the plugin suffix rule, dead code
  deleted, vulture false positives whitelisted; S0 stopped capturing the flat sector label.
