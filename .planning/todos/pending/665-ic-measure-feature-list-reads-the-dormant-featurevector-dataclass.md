---
status: pending
priority: P3
filed: 2026-11-24
source: indicagent-3d, readiness check of ic_measure against the rebuilt feature_vectors (lead item C)
---

# ic_measure picks its feature columns from the dormant FeatureVector dataclass

## What

`services/ic_measure.py` (`feature_names`, about line 318) builds the measured column list from `dataclasses.fields(FeatureVector)` that the table holds as numeric, then appends every other numeric table column ("beyond FeatureVector", logged at info). `FeatureVector` is the dormant streaming contract and `KERNEL_ONLY_COLUMNS` (`registry.py`) lists the stored columns it does not carry (roll_spread, the item-8 add-list, dividend_yield). Today the result is right because the extras fall through, but a FeatureVector field the table does not store is only a warning count, and the stored-column truth lives in `feature_vectors_numeric_columns()`.

## Done when

The measured list is `feature_vectors_numeric_columns()` intersected with the table's numeric columns, with a refusal (not a warning) for a registry column the table lacks, and a test that the HMM, add-list and `roll_spread` columns are all measured. No change to any stored value or IC definition; the result set must be identical on the 1d pilot rows.
