---
status: closed
priority: P3
filed: 2026-08-03
closed: 2026-08-21
source: code-reviewer subagent review of todo 241's live-path fix, finding #6
---

# `ctf_vwap_align`/`ctf_regime_align` sit at their dataclass default (0.0) in live serving
# forever -- same bug class as todo 241, but for two already-rejected features

## What

`_CTF_HIGHER_TF`'s batch computation (`_build_ctf_series` in `backfill_feature_factory.py`)
produces three values per HTF bar: `ctf_momentum`, `ctf_vwap_align` (sign of close vs.
cumulative VWAP), `ctf_regime_align` (an HMM forward-pass regime label). Todo 241 fixed
`ctf_momentum`'s live computation. The other two are never assigned anywhere in the live
path -- grepped `src/` and `services/`, the only writer of `cache.ctf_vwap_align`/
`cache.ctf_regime_align` is `_build_ctf_series` (batch). `FeatureCache`'s dataclass default
(`0.0` for both, `feature_cache.py:65-66`) is what live emits into every `feature_vectors`
row, permanently.

The docstring line removed by todo 241 ("other fields hold prior cached values") was never
true for these two -- they were never assigned a "prior" value to hold in the first place,
live-side.

## Why this is P3, not P0/P1 (unlike todo 241/243)

Both features are already-rejected, dead-for-decision-making candidates:
[todo 189](../completed/189-ctf-momentum-1d-self-referential-htf-not-cross-timeframe.md)'s
closing note records both were independently tested through the same
`cross_sectional_relative_value` falsification methodology as `ctf_momentum`
(`scripts/analysis/t3_ctf_family_check.py`, deleted 2026-07-28) and **rejected**:
`ctf_vwap_align` clears its statistical bar but dies on turnover cost; `ctf_regime_align`
doesn't clear its own CI at any scale tested. Nothing downstream reads either field as a
decision input today -- zero current blast radius, unlike `ctf_momentum` (Phase 167's live
ranking signal) or the batch join bug (todo 243).

## Fix

If either feature is ever resurrected for a new construction, wire live computation the same
way todo 241 did for `ctf_momentum` (extend `_update_ctf_cache_from_htf_bar` to also compute
and propagate `ctf_vwap_align`/`ctf_regime_align`, reusing `_build_ctf_series`'s existing
VWAP-sign and HMM-forward-pass logic). Not worth doing speculatively for two features with a
documented negative result and no live consumer -- CLAUDE.md's "don't accelerate work steps
1-3 haven't justified" mandate applies directly.

## Cross-refs

- [todo 241](241-ctf-momentum-live-batch-compute-divergence.md) -- the sibling fix for
  `ctf_momentum`, same bug class
- [todo 189](../completed/189-ctf-momentum-1d-self-referential-htf-not-cross-timeframe.md) --
  records both features as rejected, closing note

## Resolution (2026-08-21): re-verified, decision confirmed unchanged, closed

Re-ran the grep this todo's own claim depends on before trusting it, per this project's
"verify then delete, don't flag" discipline -- 6+ weeks had passed since filing, long
enough for the ensemble-eligibility or concept-registry landscape to have shifted.

`grep -rn "ctf_vwap_align\|ctf_regime_align" src/ services/ scripts/` (excluding tests):
every hit is either (a) plumbing -- `feature_factory.py`/`feature_cache.py`/`schemas.py`/
`feature_vector_persistence.py`/`backfill_feature_factory.py`, the dataclass/column
definition and pass-through, no decision logic -- or (b) a diagnostic/analysis script
(`nonlinear_interaction_combiner_ctf_leak_diagnostic_{5m,15m,1h}.py`,
`ops_ctf_columns_recompute_15m.py`) that explicitly *excludes* both columns from its
training matrix, the opposite of treating them as a live signal. **Zero references in
`services/ensemble_trainer.py` or `src/intelligence/concept_registry_service.py`** --
confirmed directly, not inferred. No live consumer exists today, same as 2026-08-03.

Decision stands: not worth wiring live computation speculatively for two features with a
documented negative result (todo 189) and no live consumer. Closing as a confirmed
no-action decision, not deferred work -- if either feature is ever resurrected for a new
construction, the fix shape this file already describes (extend
`_update_ctf_cache_from_htf_bar`, reuse `_build_ctf_series`'s existing logic) is still the
right one to reach for.
