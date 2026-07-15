# 065 — Emission layer (Stage 4) calibration proposals

Source: `docs/research/measurement-alpha-emission.md` (Fable review, 2026-07-08).

**Update 2026-07-14:** still blocked on the *same class* of dependency as 2026-07-08 —
now Phase 143.1-07 (in progress at time of writing), which is correcting the exact
inputs EM-CAL reads (`ic_sharpe` stride bias, eligibility sign asymmetry, Fisher-z CI
miscalibration). Calibrating against the live (pre-fix) `feature_ic_scores`/
`alpha_ensemble_ic` today would mean redoing it once the rebuild lands — the same
p-hacking-adjacent mistake this todo already caught itself making once.

What DID land today, with zero data dependency:
- **EM-CAL harness built**: `scripts/ops/alpha/ops_emission_threshold_sweep.py` +
  `tests/unit/test_emission_threshold_sweep.py` (23 tests, all pure-function coverage —
  `ensemble_alpha` is empty mid-rebuild, so no live dry-run was possible; the harness is
  validated against synthetic data instead). `--commit-to-apr` is intentionally
  unimplemented (refuses with an explanatory message) — this script is report-only until
  re-run against the corrected corpus.
- **Real methodology bug caught and fixed**: `measurement-alpha-emission.md`'s EM-CAL
  section said to calibrate on the OOS holdout window ("OOS window only, per
  OOS-EVAL-PROTOCOL") — backwards. `docs/plans/OOS-EVAL-PROTOCOL.md` explicitly lists
  "Threshold tuning" among the uses the holdout must NEVER serve. Corrected in both the
  doc and the harness (`bar_ts < alpha.validation.oos_start`, enforced as a hard filter,
  not an option).
- **Doc-drift fix** (the todo's own "separately, cheap and unblocked" item below): all 4
  stale `threshold[symbol][tf][regime] AND ci_lower > 0` mentions in
  `docs/foundation/glossary.md` corrected to describe the actual live four-gate stack.

**Next action once 143.1-07 (and the E1/E2 A/B re-run it unblocks) completes:** run
`ops_emission_threshold_sweep.py --weight-version <epoch>` for real, per
`measurement-alpha-emission.md`'s own sequencing note — after the weight-method winner is
promoted, so thresholds calibrate against the surviving `weight_method`, not a superseded
one.

**Update 2026-07-08 (later same day):** deliberately NOT actioned this session — see
ROADMAP.md's EIC-04 Verdict Log. Building EM-CAL to manufacture more `alpha_events` volume
specifically to satisfy EIC-04's sample-size floor would have been p-hacking (tuning an
execution-policy threshold to pass a signal-validation gate). Separately, a much bigger issue
surfaced same day: 60% of `feature_vectors` columns were silently NULL (persistence bug in
`feature_vector_persistence.py`, now fixed and regression-guarded — see project memory's
"Corpus pipeline state" for full detail), so every number this todo's "blocked on" section
references is stale pending a full corpus rebuild. Re-evaluate this todo only after that
rebuild completes and EIC-04 is re-measured on complete data.

Blocked on: current corpus rebuild (started 2026-07-07 17:00, step 4/7 as of writing) finishing,
then the E1/E2 A/B judgment + EIC-04 re-run that unblocks Phase 142B. `alpha_events` is 0 rows
mid-rebuild — EM-STAMP/EM-HYST need real event flow to mean anything; EM-CAL needs the fresh
`feature_ic_scores`/`alpha_ensemble_ic` this rebuild produces, not the data it's replacing.

Proposals, ranked by the review:
- **EM-CAL** (build first) — empirical threshold calibration; current `alpha.quant.threshold.{tf}`
  seeds (1.5/1.2/1.0/0.8) are admitted guesses, not calibrated.
- **EM-STAMP** (cheap, do opportunistically) — `weight_computed_at` on `alpha_events` for
  decay-awareness; stamp now, only gate on it once a decay curve is actually measured.
- **EM-RANK** (gated) — cross-sectional rank gate; depends on a separate T3/Cross-Sectional Rank
  IC verdict landing first. Has an honest boundary note vs. Trade Construction Layer — don't
  duplicate that scope.
- **EM-HYST** (likely skip) — hysteresis for flap reduction. Review recommends a pre-registered
  flap-rate measurement with a pre-committed kill bar before building, not building outright.

Rejected by the review (don't resurrect without new evidence): continuous emission (already
~90% present via `ensemble_alpha`), cross-TF confirmation gates (reintroduces I6 confluence
epistemology), per-symbol thresholds (~1,900-cell overfitting surface).

~~Separately, cheap and unblocked: the architecture doc's Stage 4 summary has drifted from
`alpha_publisher.py`~~ — **done 2026-07-14**, see update above.
