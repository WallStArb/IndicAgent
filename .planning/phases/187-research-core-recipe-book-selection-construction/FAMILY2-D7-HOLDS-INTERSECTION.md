# Family 2: D7 holds in the members universe (2026-10-29)

Author: indicagent research lane (session B)
Informed by: `.planning/phases/191-unified-raw-bar-table/191-20-D7-HOLDS.tsv`, `FAMILY2-RUN-READINESS.md`

The members universe (compute_eligible and EQ without intl_* tags) is 187 names. 17 of them are
among the 229 plan 191-20 D7 holds (list and failing checks in `FAMILY2-D7-HOLDS-INTERSECTION.tsv`):
16 hold on `session_coverage` (one finding each), one each on `canonical_recompute`,
`freshness_1d`, `lineage_missing`, `policy_conformance`, `unexplained_seam` (some names carry two).

The spec is pre-registered, so the run keeps all 187 names; dropping the 17 would be a new spec
hash. The held names are disclosed here and the verdict gate already keeps them out of promotion.
No with/without-17 sensitivity is planned (decision 2026-10-30). A first plan to derive it from the recorded
series was wrong: the recorded D_s is the book's cross-sectional total, so names cannot be subtracted from
it, and a real answer needs a new exploration-mode run on 170 names. It could not change a decision: no
member is significant in the preregistered direction, nothing is promoted from this run, and the verdict
gate already keeps held names out of promotion.
