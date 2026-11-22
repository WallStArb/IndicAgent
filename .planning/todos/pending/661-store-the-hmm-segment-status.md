---
status: pending
priority: P2
filed: 2026-11-22
source: indicagent-f6, todo 652 HMM recompute
owner: lead
---

# Store the HMM segment status so a NaN hmm column is verifiable

## What

The AADR recompute (read-only, writer-style series start) showed trend segment status 2 (degenerate occupation) on 1,512 of 2,524 rows and hmm_churn NaN on exactly those rows; AACG 756 of 1,758 the same. Verified only by recompute because the status is not stored.

## Done when

The segment status of both HMM families is a stored column (or a provenance statistic), and the pilot screen judges the HMM columns only where a segment is written, with counts disclosed.
