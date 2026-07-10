# 083 — Analog substrate refinements: ensemble-of-metrics retrieval, conformal coverage

**Status (moved to deferred/, 2026-07-10):** Hard-blocked on Phase 148 (AnalogEngine embedding substrate) shipping, per the todo's own gate. Revive once Phase 148 ships.


**Source:** `docs/research/fable-2026-07-07-renaissance-layer-refinements.md` §4 (L1a-2, L1a-3).
`intel-analog-engine.md` already covers retrieval design, definedness rules, OOD monitoring, and
correctly defers IC-weighted re-ranking — these are additions on top, not replacements.
**Priority:** medium; genuinely additive but only relevant once the substrate exists.
**Gate:** hard-blocked on Phase 148 (AnalogEngine embedding substrate) shipping. See also todo
154 (family-balanced embedding geometry), which must land first since it changes the substrate
these ideas build on.

## L1a-2 — Ensemble-of-metrics retrieval as parallel predictor variants

Rather than one monolithic distance, compute analog predictors from *family sub-vector*
retrievals too: `analog_expected_r_vol` (neighbors by volatility-state similarity only),
`analog_expected_r_momentum`, etc. Each sub-metric answers a different question, and each is just
another predictor column measured by the standard machinery. The weak-signal-diversification
answer to metric learning: instead of learning one optimal metric (large, overfittable), measure
several cheap fixed metrics and let the ensemble weight them. 3-4 extra predictor columns, same
FDR pool; pgvector supports multiple indexes/expressions — pilot can run sub-vector retrieval
brute-force on a 6-month window before committing indexes.

## L1a-3 — Conformal coverage as the analog family's calibration test

The K-neighbor forward-return distribution is a free nonparametric prediction interval. Persist
per-bar analog quantiles (q10/q90) alongside `analog_expected_r`, then measure empirical coverage
OOS: the realized forward return should fall inside the 80% interval 80% of the time. This is
layer 0c (calibration, unbuilt, unscheduled per `measurement-ic-engine.md`) arriving for free for
one predictor family — and a coverage failure is an OOD/regime-break signal with a cleaner
statistical interpretation than the raw null-rate monitor. Coverage vs nominal is a single scalar
per (symbol, tf, regime); binomial test, no new math. Two extra columns in the planned nightly
analog batch plus one audit query.
