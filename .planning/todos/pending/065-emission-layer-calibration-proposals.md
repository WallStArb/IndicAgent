# 065 — Emission layer (Stage 4) calibration proposals

Source: `docs/research/measurement-alpha-emission.md` (Fable review, 2026-07-08).

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

Separately, cheap and unblocked: the architecture doc's Stage 4 summary has drifted from
`alpha_publisher.py` — documents `threshold[symbol][tf][regime]` + `ci_lower > 0`, actual code
is per-TF-only threshold (`alpha.quant.threshold.{tf}`) plus a four-gate stack (effective_n ≥ 3,
abs threshold, direction-aware CI + cost hurdle, non-empty top_features). Fix independently of
the rest of this todo — no data dependency.
