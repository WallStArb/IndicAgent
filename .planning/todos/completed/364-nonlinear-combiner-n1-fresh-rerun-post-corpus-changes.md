---
status: closed
priority: P2
filed: 2026-09-01
closed: 2026-09-01
source: user question "did the recompute reopen N1/nonlinear or other tested ideas?" --
  investigated live, confirmed the specific Phase 173/todo-335 fixes don't touch N1's
  data path, but ~3 weeks and several real corpus-integrity fixes have landed since N1's
  own run, making a fresh re-run cheap insurance rather than a stale citation risk
---

# Re-run N1 (nonlinear_interaction_combiner) fresh -- not reopened by Phase 173/335, but stale enough to be worth a clean re-check

## CLOSED 2026-09-01

Re-ran N1-a-capped @ 1h at both colsample_bytree values (0.10 and 0.05). **Both reproduced
their original 2026-08-25 numbers bit-identically** -- `point_diff`, `ci_lower`, `ci_upper`,
`p`, the fold-1 `gap_z` breach magnitude, total row count (6,646,123), and fold boundaries
all matched exactly. Traced to todo 366 (filed same session): live IBKR ingestion has been
down since 2026-08-12, before N1's original run, so the 1h equity corpus this test reads
from has not grown in the intervening ~3 weeks -- the exact reproduction is explained by
identical underlying data, not coincidence.

**Verdict, per this todo's own pre-registered framing: the instability persists, confirming
it is real and structural, not a data-staleness artifact.** Not resolved cleanly one way
either -- both outcomes are real, deterministic, reproducible properties of the estimator at
this corpus size, not measurement noise. No further re-run is warranted until either the
corpus genuinely grows (todo 366, not urgent per current priority) or a differently-designed
estimator fix (feature-specific `gap_z` gain cap, not another colsample sweep) is built.

New observation, not investigated further this session: peak RSS was ~15-20% higher on both
fresh runs than the original (27.19GB/27.25GB vs. 22.82GB/24.05GB) at identical row counts
and hyperparameters -- within the module's documented OOM envelope but worth a look before
running this test again at this scale.

Full numbers and analysis: `docs/research/measurement-nonlinear-interaction-combiner.md`'s
"N1-a-capped @ 1h fresh re-run, 2026-09-01" section.

## Why this, not a blind "re-run everything"

Investigated 2026-09-01 whether the post-Phase-173 corpus recompute (broadcast-feature
significance fix) or todo 335's commodity/fx regime-relabeling fix reopened any
previously DEAD/inconclusive discovery-track verdict. Checked systematically, confirmed
**none of them are affected by either fix specifically**:

- 4 DEAD discovery pilots (`jump_diffusion_decomposition`, `cointegrated_pairs_residual`,
  `retail_immediacy_provision`, `dealer_hedging_flow`) -- pure price-derived statistical
  tests, zero dependency on any broadcast column or `regime_group`.
- `regime_conditional_persistence` (T2) -- tested 2026-08-03, before the commodity regime
  group even existed (unified 2026-08-07).
- Phase 167's cross-sectional construction -- trains on exactly one feature
  (`ctf_momentum`), not on the broadcast list; already re-verified post-CTF-fix at
  authoritative tier.
- **N1 (nonlinear_interaction_combiner)** -- trains on essentially all ~248
  `feature_vectors` float columns (`EXCLUDE_COLS` in
  `scripts/analysis/_nonlinear_interaction_combiner_shared.py` only blocks 12
  identity/canary columns, so the 38 broadcast columns ARE in its training matrix), but
  it never touches `ic_engine.py`'s pooled cross-sectional significance test -- the only
  thing Phase 173 changed. It also filters `asset_class = 'equity'` only, so todo 335's
  commodity/fx fix is irrelevant too.

**But N1's own verdict is "inconclusive," not a settled DEAD/PASS** -- and it ran
2026-08-25, before several real corpus-integrity fixes landed in the ~3 weeks since
(todo 312's HMM probability underflow fix, 2026-08-14 -- already before N1's run, so not
itself a reason, but illustrative of how much churn this corpus sees; the corpus itself
also grew via the completed post-Phase-173 recompute). An inconclusive result sitting on
data from before that much churn is exactly the kind of thing worth a cheap re-check
before being cited indefinitely as "unresolved" -- unlike the DEAD verdicts above, which
don't benefit from a rerun (re-running every closed candidate "just in case" isn't
proportionate; this one specifically is not settled).

## What to do

Re-run N1's residual-form test (`docs/research/measurement-nonlinear-interaction-combiner.md`'s
design, `scripts/analysis/_nonlinear_interaction_combiner_shared.py` +
N1-a/N1-a-capped) fresh against the current corpus. If the 1h colsample-sensitivity
instability (flips between "significantly worse than linear" and "no effect" on one
parameter step) persists, that's real signal the instability itself is structural, not a
data-staleness artifact -- still don't cite pass/fail either way, but now with fresher
grounding. If it resolves cleanly one way, that's an actual answer worth having.

## References

- `docs/research/measurement-nonlinear-interaction-combiner.md` -- design doc
- `scripts/analysis/_nonlinear_interaction_combiner_shared.py` -- shared training-matrix/model code
- `project_n1_nonlinear_combiner_and_feature_phase_audit_2026_08_25` memory -- original run's result
