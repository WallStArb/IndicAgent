---
status: completed
priority: P3
filed: 2026-11-22
source: indicagent-22, independent review of c6a9f2db5 by the lead
owner: lead
---

# The feature screen's G2 and G6 compare stored rows with warmup declared in bars

## What

`ops_feature_column_screen.py` measures a column's first finite row as a row number within the name's stored rows (`first_rn`, the window over the stored primary-key rows), but the column's declared warmup `mem` is `stored_first_row`, counted in bars from the series start. The rebuild stores rows only from `first_row` (`feature.momentum.zscore_window`, 252), so stored row k is bar k + 252.

- G2: `first_rn - 1 - mem > warmup_gap_bars` (screen line about 246) is lenient by 252 bars: a column that starts 252 bars late passes.
- G6 and the "judged on this column" test: `n <= mem` and `n - mem` post-warmup rows compare a stored-row count with a bars quantity, so a column's post-warmup rows are overcounted by 252 per name and a column is judged on a name whose stored rows are below its memory in bars.

Found while sizing the pilot sample (ledger 2026-11-22d); the sample rule itself converts bars to stored rows with `min_stored_rows` and is not affected.

## Done when

The gate is converted (add `first_row` to the stored-row side, or subtract it from `mem`) under its own methodology-change ledger entry, with a test that a column starting 252 bars late fails G2; the effect on the recorded verdicts of a4f6ad40 is stated. The gate is not changed before that entry (pre-registered thresholds: warmup_gap_bars 5, max_null_fraction 0.05 stay).

## Closure 2026-11-24 (ledger 2026-11-24c)

`declared_memory` returns the declared warmup in stored rows (`max(0, stored_first_row - momentum_zscore_window)`), so G2, G6, the post-warmup SQL filter and the not-judged list share one unit with the screen's row counts. Thresholds unchanged. Tests: a column declared at bar 311 passes at stored row 60 and fails 252 bars later; the real-registry not-judged list is still exactly `hma_slope_z` (7,308 stored rows). The effect on the recorded a4f6ad40 verdict (still failed; G2 stricter) and the count of newly failing columns are measured by the first pilot of the next run.
