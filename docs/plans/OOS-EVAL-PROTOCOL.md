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

## Enforcement points

The corpus orchestrator (`scripts/ops/corpus/ops_corpus_pipeline_run.sh`)
clamps `TRAINING_WINDOW_END` to `min(MAX(bar_ts), oos_start)` before passing
it to `forward_return_writer` (step 3) and `ic_engine` (step 4). This is the
sole *computation* point for the clamp.

`forward_return_writer.py` and `ic_engine.py` are the second enforcement
layer: both files' `--training-window-end` CLI argument is `required=True`
(argparse). Neither file has a bare-`MAX(bar_ts)` default fallback — an
invocation missing the flag crash-loudly refuses to run instead of silently
consuming the OOS holdout window. This closes the gap where either file is
directly invokable outside the orchestrator (both files' own docstrings
document ad-hoc single-symbol/TF usage).

**Any script that reverts to a bare `MAX(bar_ts)` query, or makes
`--training-window-end` optional with a `MAX(bar_ts)` default, is a protocol
violation.** The clamp SQL and its empty-corpus / malformed-input fail-loud
behavior are documented inline in the orchestrator script.

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

### Construction-level scorer (Phase 167+, folded in 2026-08-04)

`services/cross_sectional_spread_tracker.py --evaluate-gate`/`--evaluate-attribution`
is a third, authoritative-tier OOS scorer, one level below `EnsembleICEngine`:
it evaluates a single named construction's realized spread (Gate 1: net-of-cost
Sharpe via day-clustered bootstrap + shuffled-ranking null; Gate 2: attribution
honesty via a static-tilt regression) over `bar_ts >= alpha.validation.oos_start`,
rather than the whole ensemble. It reads `return_fast`/`return_slow` from
`forward_returns` (unlike the interim scorer above, which computes returns
on the fly) — an authoritative run therefore requires `forward_returns` to
already have real, corroborated rows in the OOS window (todo 253's fix
design covers how to get them there; this is NOT automatic from the normal
corpus pipeline, which deliberately never writes past `oos_start` — see
Enforcement points above).

This scorer was NOT folded into this protocol when Phase 167 built it
(2026-07-27), and ran its first evaluation without the run-once discipline
below — a gap closed 2026-08-04 (todo 253): `_run_evaluate_gate`/
`_run_evaluate_attribution` now write one row per construction to
`gate_evaluations` (`gate_id` = `gate{1,2}_{construction_name}`) and append
to `.planning/gate_look_log.jsonl`, atomically refusing a second write for
the same `gate_id` — the same D-04 mechanism `ops_oos_gate1_signal_eval.py`
(Phase 148) and Phase 166's gates already use, not a fourth parallel
convention. `--dry-run` runs the full computation without consuming the
one-shot gate, for dev-time verification.

## Cadence

The authoritative OOS scorers (`EnsembleICEngine` in OOS mode, and each
named construction's Gate 1/Gate 2 above) are each run **at most once per
milestone gate, per construction**. Re-running one to "check if it passes
now" after a tweak is forbidden — every additional look at the holdout
converts part of it into a training set by process, even if no code path
writes to it. `gate_evaluations`/`gate_look_log.jsonl` is the system of
record for whether a given `gate_id` has already had its one look — check
there before assuming a construction is eligible for a first look, don't
infer it from whether a result "feels" already-known. A change to the
*construction's own inputs* (e.g. a corrected feature computation feeding
the same `gate_id`) does not automatically earn a fresh look under the
existing `gate_id` — that is a real judgment call (does the corrected
input make this a legitimately new first look, or does the protocol's
spirit still treat it as the same gate), not something to resolve by
picking a new `gate_id` to route around the guard. The interim diagnostic
scorer may be run more freely since it is never a gate, but its output must
not be used to tune any in-sample parameter.

**Corrected-input re-look (added 2026-08-05, todo 243)**: `cross_sectional_spread_tracker.py`'s
`--evaluate-gate`/`--evaluate-attribution` support a `--gate-id-suffix` (paired mandatorily with
`--gate-id-suffix-reason`) for exactly the judgment call named above, once it has actually been
made — not a way to avoid making it. The suffixed run gets its own `gate_evaluations` row; the
original run stays in place as the historical record of what the pre-fix data showed. Use this
only when ALL of the following hold, and state which apply in the required reason string:

1. The input correction was discovered independently of this gate's result (via code review,
   a different investigation, a test failure) — never because this gate's result was
   disappointing and someone went looking for a reason to discount it.
2. The correction was already shipped (code fix committed, tested, merged) *before* the
   consumed `gate_id`'s recorded run — i.e. the corpus/data was simply lagging an
   already-known-correct fix, not modified in reaction to the gate's answer.
3. The prior recorded run measured a demonstrably different (buggy) computation, not a
   parameter or methodology tweak to the same well-defined construction — this is "our
   instrument was miscalibrated," not "we didn't like the reading so we adjusted the scale."

If any of these doesn't hold, the corrected data does not earn a fresh look under this
mechanism — the existing verdict stands, full stop, regardless of whether the corrected data is
believed to change the answer. This escape hatch is intentionally narrow; do not extend its use
by analogy without updating this section first.

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
