---
status: completed
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

## Closure 2026-11-24

Not a new stored column: the thirteen HMM numeric columns (seven trend, six volatility) are declared object dependent, with presence = the walk-forward segment is written (status 1), through their `_<column>_is_none` masks in `kernels/regime.py`. The rebuild already counts, per unit, the rows where an object-dependent column is present and the NaN rows among them (provenance `unit_stats`), and `object_share_gate` judges that share, so a NaN HMM column is judged only where a segment is written, with the counts stored beside every unit. No migration, no schema change, no new feature column (a stored status would have entered `feature_columns()`, the IC allow-list and the screen). No stored value changes: every numeric column is already NaN where no segment is written (tested for both families, including a skipped degenerate segment). The rebuild code key moves (e84d55a7e591 to 09708ae249f2 at this change). The screen now fails an HMM column only when entirely NULL; the share test moves to `object_share_gate`, which judges NaN among the rows where a segment is written. The skipped-segment diagnostics (`EVENT_SEGMENT_SKIPPED`) are unchanged.

