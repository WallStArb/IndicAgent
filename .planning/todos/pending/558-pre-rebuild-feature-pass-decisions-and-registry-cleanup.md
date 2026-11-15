---
status: pending
priority: P1
filed: 2026-10-28
source: owner question 2026-10-28 (new features, factors and signals; missing atomic features; cleanup)
---

# Decide the pre-rebuild stored-column additions and clean the feature registry

## Status (2026-11-15)

Landed: the eight-row add-list is stored (kernels `residual.py`, `dividend.py`; todo 584 item 8,
2026-11-03) and the three `*_rank_z` columns are retired (session indicagent-c6, lane L1): gone from
`UNOWNED_COLUMNS`, the `FeatureVector` (288 to 285 fields), the factory domain map and constructor
calls, and the legacy insert tuple; the kernel parity goldens were regenerated with the three
columns removed and every other column's digest unchanged. `feature_vectors` never carried them
(migration 425), so no migration. What is left is item 3 below.

## What

The `ret_acf1_z` against `ret_autocorr_1` duplicate is an unmeasured inference (todo 421 and a
kernel grep); nothing is dropped on a duplicate finding alone.

After the corpus rerun: measure the `ret_acf1_z` against `ret_autocorr_1` correlation, then fill
`redundancy_group` (empty for all registry features) from measured correlations.

## Done when

`redundancy_group` is filled from measured correlations.
