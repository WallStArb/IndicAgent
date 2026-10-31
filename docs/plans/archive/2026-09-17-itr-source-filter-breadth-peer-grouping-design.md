# Design decision: source filtering for instrument_tags in breadth and peer-grouping (todo 379)

Original: 2026-09-17 (decision landed).
Archived 2026-10-31: landed decision, kept for the reasoning.

Kept: breadth and peer-grouping consume instrument_tags filtered by tag source rather than
passes_fdr alone, because TagCalibrator's empirical tags clear significance on shared market
beta alone (with n=250+ observations, trivial beta correlation is significant). A polluted
breadth label does not just mislabel a display metric; it silently corrupts which bars are
bucketed into which regime stratum for every symbol trained under the asset class. Claims
about what an instrument is live in the tag registry, never in hardcoded symbol lists.

Live successor: docs/foundation/instrument-tag-registry.md.
Full text in git history at docs/plans/2026-09-17-itr-source-filter-breadth-peer-grouping-design.md as of 708f3fe09.
