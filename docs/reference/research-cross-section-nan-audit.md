# Research cross-section NaN audit

Recorded 2026-11-18 (todo 609 blocker I1). A non-member cell is NaN (`no_fill`), so every cross-sectional operation must leave a masked name out of its counts, ranks, means, regressions, clusters and components. Executable form: `tests/unit/research/test_nan_columns_do_not_enter_cross_sections.py` adds all-NaN columns to a panel and requires the outputs on the real columns to be unchanged (bit-identical for rank and count operations; same finite cells and agreement to reduction-order rounding, about 1e-12 in S1, for sum and regression operations).

Result: no operation counts, weights or shifts a statistic because of a masked name. Nothing needed a fix.

| Operation | Where | How a NaN cell is handled | Test |
|---|---|---|---|
| Average rank | `portfolio.average_ranks` | NaN sorts last and keeps a NaN rank | `test_centred_rank_and_average_ranks` |
| Centred rank | `families/common.centred_rank` | n is the finite count; a row under the coverage floor is NaN | same |
| R1 weights | `portfolio.rank_vol_neutral_weights` | valid = finite alpha and positive finite vol; sides scaled over valid names | `test_rank_vol_neutral_weights` |
| Trailing vol | `portfolio.trailing_vol` | per-name time window over finite values; NaN column stays NaN | `test_trailing_vol` |
| Row correlation (member signs) | `combiner._row_correlation` | complete-case mask, count of jointly finite names | `test_row_correlation_used_by_the_combiner_signs` |
| S1 market and group means, clusters, PCs, loadings | `factors.residual_returns` | leave-one-out means over finite names; a name without enough finite rows in the window gets no loadings and NaN residuals | `test_s1_residuals_and_neutralize` |
| Score neutralization | `factors.neutralize` | regression over names with finite alpha and finite loadings | same |
| Member attribution | `contribution.attribution` | scored cell = finite target and one finite term; row mean over scored cells | `test_contribution_attribution_scores_only_finite_cells` |

Operations that do not cross names (time-series windows, session P&L, the E17 null shifts, StepM over series) read one name or one series at a time and are not affected by a masked column beyond that name's own NaN cells, which the member masks already treat as missing.

Entrants are the one place a masked name matters over time: S1 is fed prices that are NaN before a name's first membership (`membership.seen_member_mask`), so an entrant's residual history starts at first membership. The effect is measured at the membership build (`membership.cold_start_share_by_year`) and tested in `tests/unit/research/test_membership_runner.py`.
