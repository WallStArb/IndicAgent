# Family 2: D7 holds in the members universe (2026-10-29)

Author: indicagent research lane (session B)
Informed by: `.planning/phases/191-unified-raw-bar-table/191-20-D7-HOLDS.tsv`, `FAMILY2-RUN-READINESS.md`

The members universe (compute_eligible and EQ without intl_* tags) is 187 names. 17 of them are
among the 229 plan 191-20 D7 holds (list and failing checks in `FAMILY2-D7-HOLDS-INTERSECTION.tsv`):
16 hold on `session_coverage` (one finding each), one each on `canonical_recompute`,
`freshness_1d`, `lineage_missing`, `policy_conformance`, `unexplained_seam` (some names carry two).

The spec is pre-registered, so the run keeps all 187 names; dropping the 17 would be a new spec
hash. The held names are disclosed here and the verdict gate already keeps them out of promotion.
After the run, report the headline with and without the 17 as a descriptive sensitivity (not a
second look: it is a subset of the same recorded D_s series).
