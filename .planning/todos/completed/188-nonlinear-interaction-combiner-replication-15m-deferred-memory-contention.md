---
status: completed
priority: P2
filed: 2026-07-27
closed: 2026-08-03
source: nonlinear_interaction_combiner's 1d independent replication, deferred the 15m follow-on due to memory contention
---

## What

`scripts/analysis/nonlinear_interaction_combiner_replication_1d.py` (2026-07-27) partially replicated
nonlinear_interaction_combiner's non-linear-combiner finding at equity/1d: the tree combiner clears its own bootstrap CI in
the cross-sectional-neutral rigor pass (`point_ic`=0.0164, `ci_lower`=0.0081), but the magnitude
collapsed ~16x from the original equity/1h finding (0.258 -> 0.0164) -- confirmed SMALL, not
confirmed LARGE. Full writeup: `docs/research/data-edge-source-thesis.md`'s nonlinear_interaction_combiner section (v1.4).

The 15m replication is the directly actionable one -- it's the timeframe Phase 167's live
`CrossSectionalSpreadTracker` construction actually trades on (`ctf_momentum` ranked at 15m).
Deliberately deferred at write time: 15m equity is ~8.1M feature_vectors/forward_returns rows
vs. 1d's ~330K, and the concurrent todo 183 `ic_engine` corpus recompute was holding ~9GB RSS
against only ~12GB available on this machine -- loading the full 15m corpus into one in-memory
pandas DataFrame (the pattern both the 1h and 1d nonlinear_interaction_combiner scripts use) risked OOM/heavy swapping.

Separately, the 1d replication surfaced an unrelated, load-bearing finding worth its own
investigation before or alongside this: `ctf_momentum` shows NEGATIVE mean IC at 1d
(`point_ic`=-0.0244, cross-sectional-neutral `ci_lower`=-0.0174, does not clear zero) -- the
opposite of its validated positive behavior at 15m (Phase 167's live Gate 1/Gate 2 both
PASSED using this exact feature at this tf). Unexplained timeframe instability
(short-horizon-momentum/long-horizon-reversal is one plausible, unconfirmed explanation).

## Next step

The original deferral reason (todo 183's concurrent recompute contending for memory) cleared
weeks ago. `scripts/analysis/nonlinear_interaction_combiner_replication_15m.py` now exists (built off the
shared `_nonlinear_interaction_combiner_shared.py` module, not a copy-pasted override of the 1h script's
globals) and has been attempted multiple times since -- each attempt hit a distinct OOM (data
fetch, then source-frame retention, then per-fold model retention). Current status and the
active fix: [234](234-nonlinear-interaction-combiner-15m-lightgbm-oom-survives-both-prior-fixes.md). This todo's remaining
scope is superseded by 234 -- close this one once 234 resolves rather than tracking the run
attempt in two places.

If the 15m result shows a magnitude closer to the 1h finding than the 1d one, that would be
meaningful evidence the effect is tf-dependent in a specific, not-yet-understood way rather than
simply an artifact that shrinks with lower-frequency data in general.

## Resolution (2026-08-03)

Todo 234 resolved the OOM (root-cause architectural fix, not a patch -- see that file). 15m
completed: tree cross-sectional-neutral `point_ic`=0.2506, much closer to 1h's 0.1822 than 1d's
0.0127. Answers this todo's own closing question directly -- yes, the effect is tf-dependent in
the specific way hypothesized: substantial at 1h and 15m (the actionable tf), small specifically
at 1d. Full detail: `docs/research/data-edge-source-thesis.md`'s nonlinear_interaction_combiner section (v1.8).
