# OOS Evaluation Protocol

Status: committed 2026-07-02, before any out-of-sample number has been examined.
Phase: 141.1 (Measurement and Decision Integrity Foundation).

This document is a pre-commitment. The numbers and rules below are fixed now,
before anyone looks at OOS data, mirroring the discipline `docs/plans/SHADOW-REVIEW.md`
will use for Phase 142B live promotion. Renegotiating any of this after seeing an
OOS result defeats the purpose of holding a set aside at all.

## Why this exists

`alpha.validation.oos_start` has been seeded in `config_state`
(`2025-12-24T05:15:00Z`) since Phase 141, but had zero readers anywhere in
`src/`/`services/`/`scripts/` — the corpus orchestrator derived
`TRAINING_WINDOW_END` as a bare `SELECT MAX(bar_ts) FROM feature_vectors`.
Every training, IC, and ensemble computation saw the full history, including
the supposedly-reserved holdout window. Proving "ensemble IC > 0" (Phase
142A) on data that already saw the holdout would be a hollow gate — the
project's stated core epistemology (empirical proof before promotion)
requires a real, enforced holdout. See
`.planning/research/2026-07-02-v3-bottomup-audit.md` §5.4.

## Holdout window definition

All bars with `bar_ts >= alpha.validation.oos_start` (currently
`2025-12-24T05:15:00Z`) constitute the holdout window. This window must
NEVER be used for:

- Feature selection
- IC gate calibration
- Ensemble weighting
- Threshold tuning
- Hold-horizon calibration

Any process that reads OOS bars for one of the purposes above converts the
holdout into a training set and invalidates every downstream gate that
depended on it being unseen.

## Enforcement point

The corpus orchestrator (`scripts/ops/corpus/ops_corpus_pipeline_run.sh`)
clamps `TRAINING_WINDOW_END` to `min(MAX(bar_ts), oos_start)` before passing
it to `forward_return_writer` (step 3) and `ic_engine` (step 4). This is the
single enforcement point in the pipeline.

**Any script that reverts to a bare `MAX(bar_ts)` query without the clamp is
a protocol violation.** The clamp SQL and its empty-corpus / malformed-input
fail-loud behavior are documented inline in the orchestrator script.

Degradation rules:

- `oos_start` empty/unset → clamp collapses to `MAX(bar_ts)` (no holdout).
  The orchestrator logs an explicit WARNING when this happens — the absence
  of a holdout must be loud, not silent.
- `oos_start` malformed (non-empty, unparseable) → the `::timestamptz` cast
  raises, and the pipeline aborts under `set -euo pipefail` — loud failure,
  never a silent mis-clamp.
- `feature_vectors` empty (`MAX(bar_ts)` is NULL) → the orchestrator exits 1
  before deriving `TRAINING_WINDOW_END` at all.

## Scorers

### Interim scorer (available today)

`scripts/ops/corpus/ops_oos_holdout_eval.py` — a strictly READ-ONLY
feature-IC scorer over the holdout window. It composes the existing
`ic_engine.py` pure IC helpers (`_vectorized_ic`, `_fisher_z_ci`,
`_p_values_from_ic`, `_nan_to_none`) and reuses the canonical
`forward_log_return` executable-return helper from
`forward_return_writer.py` (Invariant 1: `ln(open[T+N+1] / open[T+1])`) —
it does not reimplement the return formula. It reports in-sample-vs-OOS
qualifying-feature counts per timeframe.

This scorer is **diagnostic only**. It is never a promotion gate and its
output does not feed any downstream decision by itself.

### Authoritative scorer (Phase 144)

`EnsembleICEngine` (built in Phase 142A) run in OOS mode is the primary OOS
gate. Pass criterion is inherited from EIC-04:

`ic_ci_lower > 0` at 95% CI in at least `alpha.ensemble_ic.min_qualifying_fraction`
of (symbol, tf, regime) cells, plus the walk-forward stability gate (EIC-03:
IC Sharpe max/min fold ratio < 3x across folds).

## Cadence

The authoritative OOS scoring (`EnsembleICEngine` in OOS mode) is run **at
most once per milestone gate**. Re-running it to "check if it passes now"
after a tweak is forbidden — every additional look at the holdout converts
part of it into a training set by process, even if no code path writes to
it. The interim diagnostic scorer may be run more freely since it is never a
gate, but its output must not be used to tune any in-sample parameter.

## Failure rule

If an OOS gate fails, diagnose using the EIC-05 structure (data starvation
vs. signal absence vs. frame geometry) before making any change. Do NOT
renegotiate the threshold after seeing it fail. A failed gate is information
about the corpus or the methodology, not license to lower the bar.

## Cross-references

- `.planning/research/2026-07-02-v3-bottomup-audit.md` §5.4 — the audit
  finding this protocol closes.
- `.planning/ROADMAP.md` Phase 142A (EIC-01 through EIC-05) — the
  authoritative OOS scorer and its gate/diagnosis machinery.
- `.planning/ROADMAP.md` Phase 144 — where the authoritative OOS gate is run
  against the ensemble.
- `docs/plans/SHADOW-REVIEW.md` (Phase 142B, not yet written) — the sibling
  pre-commitment document for live-promotion criteria; same discipline
  applied one layer up the stack.
