# 303 - Per-symbol trend regime candidate — cheap, null-arm-tested probe (not a build yet)

**Filed:** 2026-08-12
**Source:** Interactive session, user question chain: "what other regimes should we look at /
a real trend?" -> "do we need a replacement regime?" -> "so are you suggesting scrapping the
HMM?" -> "how would Renaissance/Jim Simons think about this?" -> "save this as a todo with a
plan." Full reasoning trail lives in that conversation; this file is the durable, actionable
distillation.
**Status:** pending, not urgent. **Stage 1 (mechanism build + validation) run 2026-08-12,
PASSED** — see Result section below. Explicitly **not a build task overall** — full Stage 2/3
falsification still gated on a data-availability check below. **Update 2026-08-13: the corpus
pipeline run this was gated on FAILED at step 2** (768GB disk-full incident, migration 312
missing VACUUM — see `project_disk_full_incident_2026_08_13` memory). `regime` and
`regime_volatility` are both still 0-populated across all 69.9M `feature_vectors` rows as of this
writing (not "not yet reached," actually failed and not recovered). **No Stage 2/3 work has
happened — this candidate regime has never been built past Stage 1.** Do not assume the gate
below has cleared without re-querying.

**Pre-registered design doc written 2026-08-12** (this todo's own Step 1 requirement, satisfied
retroactively): `docs/research/measurement-per-symbol-trend-regime.md` — full Stage 2/3 design,
including the mandatory null-arm control (per-symbol IID time-permutation, 200 replicates, null
p < 0.05), written before either stage runs. Read that doc for the actual falsification protocol
instead of re-deriving it from this file.

## What this is NOT

Not a proposal to touch the live per-symbol HMM. `regime_writer.py`'s HMM mechanism is fine —
it's what currently computes `regime_volatility` (K=3, calm/elevated/turbulent), which is the
live, `ic_engine.py`-gating (`sys.exit` on all-NULL), null-arm-validated stratification axis.
**`ic_engine` already groups single-symbol IC by regime today.** Nothing here proposes
replacing that.

## What this actually is

A real, unfilled gap: **no validated per-symbol trend axis exists.** The old `feature_vectors.regime`
(K=5) was labeled trending_up/ranging/trending_down but Phase 171/172's null-arm control found
it was empirically a volatility partition, not a trend signal — the label was wrong, not just
imprecise. Nobody has since asked, with fresh eyes and a real adversarial test, whether a
per-symbol trend axis would sharpen IC beyond what `regime_volatility` alone already provides.
That's a genuinely open, cheap-to-test hypothesis — not a known deficiency, not urgent, but
real.

**Two prior candidates for exactly this (Hurst exponent, autocorrelation-sign) already exist**
in `docs/research/stratification-dimension-unification.md`'s candidate table, rejected at
Gate 0 (structural redundancy) on the reasoning that the incumbent HMM's `momentum` observation
dimension already captured trend. **That reasoning's premise is now disproven** (the HMM never
actually separated on trend). The Gate 0 rejection should be re-run against current evidence,
not left standing on a premise this project's own later work falsified.

## The plan (sequenced, Renaissance-rigor discipline, same pattern as the other discovery-track
## candidates this session — `statistical_factor_residual`, `cointegrated_pairs_residual`,
## `jump_diffusion_decomposition`)

**Step 0 — Data-availability gate (check before anything else).** As of 2026-08-12:
**a full corpus pipeline run (features -> ensemble) is active in a separate session**
(`scripts/ops/corpus/ops_corpus_pipeline_run.sh`, PID visible via `ps aux | grep
ops_corpus_pipeline_run`) -- `feature_vectors` is growing live (6.8M -> 7.09M rows observed
within minutes). `regime_volatility` is still 0-populated as of this writing, meaning that run
hasn't reached its regime-writer step yet (same fix from `3b0a520a2` landed same-day, not yet
exercised by a live run). **Do not launch anything that touches `ic_engine`, `regime_writer`,
`ensemble_trainer`, or any other corpus-pipeline-adjacent process while that run is in
flight** -- concurrent writers on the same tables is exactly the failure shape this project's
own gotchas doc warns about. Re-check `ps` and the `regime_volatility` count once this session's
work resumes; the concurrent run may hand this todo a populated `regime_volatility` column for
free, or may not reach that step at all depending on its own scope.

**Step 1 — Write the pre-registered design doc FIRST**, before any query runs. Follow
`docs/research/measurement-statistical-factor-residual.md`'s exact structure (Status/Author/
Origin/Companion header, core point, staged design, reuse plan, promotion boundary). The
falsification design must include, non-negotiably:

1. **The trend proxy** — start with the cheapest options already in the candidate backlog:
   Hurst exponent (rolling, per symbol) or trailing-window OLS slope sign. Not a new HMM.
   Per the stratification doc's own stated default: "percentile-rank first, full HMM only once
   percentile-rank proves insufficient."
2. **The null-arm control, written into the design BEFORE running anything** — the exact
   discipline Phase 171/172's postmortem made a standing rule for future HMM-family regime
   candidates, extended here to any trend candidate regardless of mechanism: compute the same
   IC-separation statistic on a symbol-shuffled or time-shuffled null version of the same data.
   **No separation number gets cited as real evidence unless it clears this control** — this is
   the load-bearing lesson from the last two times this exact failure shape hit the project
   (this regime, and `ctf_momentum`'s lookahead leak, todo 243).
3. **Falsification bar** — same shape as every other discovery-track candidate: day-clustered
   bootstrap CI on the trend-stratified IC vs. unstratified, BH-FDR across cells, real N
   threshold (>20,000 bars per cell, matching the stratification doc's own substitution-test
   pass criterion).

**Step 2 — Run the diagnostic.** Zero schema change, throwaway script, same pattern as
`effective_breadth_diagnostic.py`/`statistical_factor_residual_k_selection_pilot.py`. If it
doesn't clear the null-arm control by a real margin, it's dead in one script — no production
code, no schema touched, exactly how the two already-dead discovery-track candidates correctly
died cheap this month.

**Step 3 — Only on a real pass:** scope what a production per-symbol trend provider would look
like (same `regime_writer.py` host, new observation vector, own BIC-selected K per the
stratification doc's own caveat that "K=5" is a naive placeholder for any new fitted dimension,
not a settled count) — a separate, later decision, not bundled into this todo.

## Sequencing relative to other open work

`statistical_factor_residual` is already mid-flight (Stage 1/K-selection done, see
`docs/research/measurement-statistical-factor-residual.md` and
[[project_statistical_factor_residual_k_selection_2026_08_11]] memory). This candidate is
disjoint (different data shape — per-symbol trend vs. cross-sectional PCA — no resource
contention) and can run in parallel, but Step 1 (the pre-registered design doc) should exist
before Step 2 runs, same discipline either way. Don't let this become a third open thread that
never finishes — if picked up, finish Steps 1-2 before starting anything else new.

## Result — Stage 1 (mechanism build + validation), run 2026-08-12

**Clean pass. Script: `scripts/analysis/per_symbol_trend_candidates_stage1_pilot.py`.** Same 5
representative symbols as todo 304's sibling run (SPY/AAPL/XOM/JPM/TLT), 2 candidates each = 10
checks:

- **Causality: 10/10 PASS**, `0.00e+00` truncated-vs-full diff on every candidate/symbol pair.
- **Distribution: non-degenerate on all 10** — rank `std` 0.285-0.298, matching the uniform[0,1]
  theoretical value (0.289) as tightly as todo 304's results.
- **Side observation, not a finding** (no IC touched, don't over-read this): raw Hurst averaged
  0.51-0.52 across all 5 symbols (barely above the random-walk midpoint of 0.5 — very mild
  persistence at this window/scale, nothing dramatic); raw lag-1 autocorrelation averaged
  slightly negative (-0.03 to -0.09) across all 5, consistent with the well-known short-horizon
  mean-reversion microstructure effect (bid-ask bounce and similar) rather than strong trending.
  Interesting context for Stage 3, not evidence of anything yet.

**No IC comparison happened.** Stage 2 (re-examine the Gate 0 redundancy rejection against
`regime_volatility`) and Stage 3 (falsification bar + mandatory null-arm control) remain gated
on the concurrent corpus pipeline finishing.

## Where

- `docs/research/stratification-dimension-unification.md` — existing candidate table, Gate 0
  rejection of Hurst/autocorrelation-sign to re-examine, governance/substitution-test protocol
- `docs/research/measurement-statistical-factor-residual.md` — structural template for the new
  design doc
- `services/regime_writer.py` — the per-symbol HMM host, future production home if Step 3 is
  ever reached
- Standing null-arm rule: project memory `project_hmm_regime_volatility_only_redesign_2026_08_08`
  ("any future HMM regime candidate must clear a null-arm control before its numbers are
  trusted") — this todo extends that rule to non-HMM trend mechanisms too, same lesson
