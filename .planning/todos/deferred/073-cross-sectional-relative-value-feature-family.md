# 073 — Cross-sectional relative-value feature family (finish the ghost columns properly)

**Status (moved to deferred/, 2026-07-10):** New FeatureFactory feature-family build meant for the v3.15 corpus-rerun batch / Phase 150's remit, not a standalone build -- the source doc explicitly warns against running these piecemeal. Revive alongside that batch or Phase 150 planning.


**Merged 2026-07-08:** this exact finding was independently discovered twice — first as todo
013 (2026-06-28; the completed-todo file itself was deleted 2026-07-09 as doc bloat once merged
here), then again via this Fable review. Todo 013's "Option A" sketch (standalone batch script, e.g.
`compute_cross_sectional_ranks.py`, run as a new step in `corpus_pipeline_run.sh` right after
`backfill_feature_factory`) is a concrete implementation shape worth reusing when this is built.

**Source:** `docs/research/fable-2026-07-07-renaissance-layer-refinements.md` §3 (L1-1, L1-3),
executive summary item 1 — the single highest-conviction finding in the doc.
**Priority:** HIGHEST — the system trains its ensemble exclusively on cross-sectional POOLED
strata (`ensemble_trainer.py:317,430-431,469,540`) yet has zero cross-sectional features. T3
(cross-sectional relative mispricing) is the lowest-IC-bar edge thesis on record
(`data-edge-source-thesis.md`) and currently has no features that directly serve it.
**Gate:** needs a new cross-sectional batch step in the corpus DAG (after
`backfill_feature_factory`, before `forward_return_writer`) — real build, batch into the v3.15
corpus rerun window per topdown D5, not a quick patch.

## Verified finding (confirmed live in this session, 2026-07-08)

`momentum_rank_z`, `volume_rank_z`, `volatility_rank_z` are declared in `FeatureVector`
(`schemas.py:1453`) and the persistence SQL (`feature_vector_persistence.py:91,296` — comment
says "None until Phase 139 enrichment"). Verified via direct query: **all 36,719,598
`feature_vectors` rows have `momentum_rank_z` NULL, zero writers exist anywhere (grep-confirmed).**
The corpus audit script normalized this away as "100% NaN rate ... expected." The family was
designed, scaffolded into schema and 36.7M DB rows, and silently never built.

## Proposal

Build the cross-sectional enrichment stage and widen the family:

- Per-bar universe percentile rank (causal, current bar across 80 symbols) of: `ret_lag_1`,
  `ret_lag_fast/mid/slow`, `volume_z`, `overnight_gap`, `atr_z` — against the full equity universe
  and, once Phase 144 ships `regime_group`, within-group too.
- Peer-relative return: symbol return minus regime_group mean return at the same lags (raw
  material for sector-relative momentum/reversal).
- Cross-sectional dispersion contribution: symbol's `|return|` rank within the bar's
  cross-sectional return distribution.
- **L1-3 rides the same infrastructure** (lead-lag/peer-influence, primitive-grade, no state
  machinery): `leader_ret_lag_1/2/3` (SPY's lagged returns as a feature on every non-SPY symbol),
  `group_ret_lag_1/2/3` + `group_ret_div` (regime_group mean return at lags 1-3, Phase 144
  dependency). Let IC discover lead-lag structure rather than encoding a hypothesis about which
  pairs lead — this deliberately supersedes the archived `cross-group-lead-lag-ic.md`'s
  Granger-style group-state approach with something smaller and primitive-grade, per the 142.5
  philosophy.

## Mechanics

Cannot live in `FeatureFactory` (correctly per-symbol single-pass). New batch service shaped like
`equity_regime_model.py` (cross-sectional reader, one writer, one fact). Grain note: a
per-(symbol, tf, bar_ts) value — can legally UPDATE the reserved `feature_vectors` columns that
were always meant to own it, or land in a sibling table if the one-writer-per-table reading of
the DAG invariant is preferred. Decide at planning.

**Pairs with:** the still-unbuilt cross-sectional rank IC mode (`measurement-ic-engine.md`
Addendum) — build both in the same phase; it's T3's honest falsification instrument and this
family's honest measurement, each validates the other.

## Filter check

Falsifiable (standard `ic_engine` measurement + the rank-IC addendum). Overfitting: ~15-20 new
columns in the standard corpus-level FDR pool, ranks are bounded, no new normalization freedom.
Weak-signal diversification: textbook Renaissance move — many small relative-value signals across
a correlated universe rather than one directional conviction. Cost: pure derivation from data
already in `feature_vectors`; one new batch service + one corpus rerun.
