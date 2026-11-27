---
status: pending
priority: P2
filed: 2026-11-27
source: todo 677 side finding (indicagent-03), lead ruling 2026-11-27
---

# The stationary prior of an absorbing fitted chain puts zero mass on the first regime, so bar 0 decodes wrong

## What

`src/intelligence/features/kernels/_hmm.py` seeds the causal forward filter with `_stationary_distribution(model.transmat_)` on the first segment of a series, after a failed fit (`prior_label is None`), and for the gate's decode of the training slice. When the training data holds one regime switch, the fitted chain is absorbing (the later regime never leaves), its stationary distribution is all mass on that regime, and the filter decodes bar 0 as the absorbing regime even when bar 0's emission strongly favours the other one. The filter recovers within a bar or two once emissions dominate the near-zero transition, so the defect is the first bars of a segment, not the whole span.

## Reproduction (tests only, no database)

```python
from hmmlearn.hmm import GaussianHMM
from src.intelligence.features.kernels._hmm import _log_emit_diag, _stationary_distribution
from tests.unit._hmm_decode_helpers import decode
from tests.unit.test_causal_hmm_decoding import _make_regime_switch_obs  # percent units since todo 677

obs = _make_regime_switch_obs(200, 150)  # up for 150 bars, then down: one switch
m = GaussianHMM(2, covariance_type="diag", n_iter=100, random_state=42).fit(obs)
cv = m.covars_[:, [0, 1], [0, 1]]
_stationary_distribution(m.transmat_)       # [0., 1.]: state 1 absorbing
_log_emit_diag(obs[:1], m.means_, cv)        # [[2.70, -90.3]]: bar 0 is clearly state 0
decode(obs, m.means_, cv, m.transmat_, 2)[0][:3]  # [1, 0, 0]: bar 0 decodes as state 1
```

With a second switch back to the first regime the chain is not absorbing and bar 0 decodes correctly (the todo 677 fixture).

## Measure before fixing (light reads only, and only while nothing heavy is live)

`market_regimes` keeps labels, not the fitted transition matrices, so measure the symptom:

1. Per series (`regime_group`, `tf`), compare the label at its first `ts` with the label at its second; count series where they differ and the share of all series. Do the same at every segment start (the first bar after each refit boundary of the walk-forward fit), where `prior_label` is None only after a failed fit.
2. For a sample of those series, refit the first training slice read-only in a scratch process and check whether its transition matrix is reducible (a row with self-transition within 1e-6 of 1 and a stationary component under 1e-12).
3. Report the count, the share and the bars affected per series. If only bar 0 of each series moves, the effect on any counted test is one observation per series and is disclosed rather than fixed urgently (CLAUDE.md data gates by materiality).

## Candidate fixes

- When the fitted chain is reducible (a stationary component at or near zero), seed the filter with a uniform prior or with the empirical state frequencies of the training decode instead of the stationary distribution; keep the stationary prior when the chain is irreducible, so the fix changes nothing elsewhere.
- Or use hmmlearn's fitted `startprob_` for the first segment only. It is fitted to the training slice's own first bar, which is not the segment's, so it is the weaker choice.

## Constraint

`_hmm.py` is in the rebuild pin (the feature rebuild's import closure), so any fix changes `rebuild_code_key` and lands only at the next re-pin, with `repro_frozen` and a regime-column rebuild in the plan. Do not change the kernel while a pinned run is live or resumable.

## Done when

The measurement is recorded here; then either a disclosure line (if only one bar per series moves) or the fix with a unit test built on the reproduction above, landed at the next re-pin.
