---
**Created:** 2026-07-06
**Completed:** 2026-07-12
**Area:** planning
**Type:** doc_sync
**Priority:** P3
**Effort:** 15 min
**Benefit:** ROADMAP Phase 154 ALTDATA-01 stops specifying a schema shape its source doc has since rejected
**Risk:** low
---

## Resolution (2026-07-12)

ALTDATA-01 rewritten to the two-shape design (bar-cadence sibling tables joined by `ic_engine`
on the bar key; sub-bar-cadence sources extending the `context_features` long/narrow pattern),
plus the per-source APR gate keys and "N counts update events, not rows" principle from the
source doc's Key Risk section. Also updated ALTDATA-04 (fundamentals) in the same pass — it
still described the now-rejected "longer accumulation period" framing right next to this fix,
which the source doc's 2026-07-06 revision replaced with "measured cross-sectionally only, never
per-symbol time-series" (20 years of quarters is ~80 independent per-symbol observations, which
no gate calibration fixes). Left uncorrected in the original scope, but fixing it in the same
pass avoided leaving an internal contradiction in the same ROADMAP section.

# 063 — Update ROADMAP Phase 154 ALTDATA-01 to the two-shape alt-data design

Found 2026-07-06 during the Fable 5 review of `docs/research/data-alt-data-sources.md`.
ROADMAP's ALTDATA-01 requirement ("`alt_feature_vectors` table keyed on
`(symbol, ts, data_source)`; IC engine joins both") was inherited from that doc's original
2026-06-23 text. The review rejected the single grab-bag table and replaced it with a
two-shape design (see the rewritten "Architectural Implication" section of the idea doc):

1. Bar-cadence sources (flows): dense sibling table per source family, keyed
   `(symbol, tf, bar_ts)`, dedicated `BaseWriter`, joined by `ic_engine` on the bar key.
2. Sub-bar-cadence sources (fundamentals, Kalshi snapshots, materialized qualitative
   scores): extend the live `context_features` pattern (long/narrow, `source` check
   constraint, effective-date contract at materialization; raw immutable event table
   upstream for event-driven sources).

Also fold in: per-source N gates count update events not rows
(`alpha.ic.min_obs.<source>` APR keys per the `min_obs_daily_features` precedent), and
fundamentals are cross-sectional-only measurement.

Not applied 2026-07-06 because ROADMAP.md carried uncommitted edits from a concurrent
session (142.5 work). Apply when Phase 154 is next touched or ROADMAP is quiet - it is a
surgical edit to the ALTDATA-01 block only.
