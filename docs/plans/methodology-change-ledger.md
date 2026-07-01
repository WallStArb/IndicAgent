# Methodology Change Ledger

**Status:** STANDING — append-only; maintained forever
**Created:** 2026-07-01
**Purpose:** Track every methodology change made *after seeing results*, so the family-wise
error of pipeline iterations is visible the same way BH-FDR makes feature-level multiplicity
visible.

---

## Why This Exists

BH-FDR controls multiplicity across features tested *within* a pipeline run. Nothing controls
multiplicity across *versions of the pipeline itself*. Each corpus rebuild has followed
methodology fixes made in response to the previous run's results. Each fix was individually
defensible; the sequence is a garden of forking paths at the pipeline level. A single-operator
system has no adversarial reviewer to catch this — this ledger is the structural substitute.

**The rule:** any change to gates, thresholds, fold construction, stratification, embargo,
clustering, or return definitions that is made after observing results from the machinery it
modifies gets an entry here, in the same commit. Entries answer three questions:
1. What result was observed before the change?
2. What changed?
3. What would the change have looked like if decided *before* seeing any data (pre-registered
   justification) — and honestly, was it?

**The consumer:** the OOS boundary is the ultimate control (`alpha.validation.oos_start` —
never touched by any iteration), but the OOS window can only be spent once per major claim.
This ledger tells us how much selection pressure the in-sample machinery has accumulated,
i.e., how skeptical to be when we finally spend it.

**The operational fix that makes this ledger shrink (2026-07-01, Simons-lens review): freeze
the method, automate the cadence.** Most result-driven methodology tweaks happen because a
rebuild/refresh is a manually-triggered event — every run is an occasion to fiddle. Once the
methodology stabilizes (post-Phase-B), ic_engine/ensemble refresh becomes a boring scheduled
job with the method frozen; changes then require a deliberate act that lands here, instead of
a temptation that accompanies every manual run. Staleness is also an error: a model running on
last month's weights is a silent methodology choice too.

---

## Retrospective Entries (reconstructed 2026-07-01)

### E1 — 2026-06-26: IC stratification switched from per-symbol HMM to cross-sectional pooling
- **Observed first:** per-symbol per-regime cells too thin (~1.5K bars at 5m); `ic_sharpe_hac`
  structurally NULL per-symbol per-regime.
- **Changed:** `ic_engine` regime source swapped to `market_regimes` join + POOLED pass
  (commit `74447369`, Phase 140.5 P4). ~58x observation density.
- **Pre-registered?** Partially — sample-size floors were a stated principle before the
  observation, and the fix follows from arithmetic, not from disappointing IC values. Low
  selection-pressure risk. But note: the change was made without first recording what the
  per-symbol-stratified results *were*, which is why todo 026's validation gate is now
  circular (labels feed IC; IC would validate labels; the per-symbol IC rows don't exist).

### E2 — 2026-06-29 → 2026-06-30: IC gate redesign after 5m/15m returned 0 qualifying features
- **Observed first:** Phase 141 gate FAIL — 5m = 0, 15m = 0 qualifying features on the
  2026-06-29 corpus.
- **Changed:** Phase A — WF fold construction, corpus-level BH-FDR, scale-specific embargo,
  direct-linkage clustering; gate replaced (`ic_ci_lower > 0 AND passes_fdr` instead of binary
  `passes_walkforward`). Result on next corpus: 5m = 37, 15m = 28 qualifying features.
- **Pre-registered?** No — this is the highest-selection-pressure entry in the ledger. The
  root-cause analysis (A1) concluded the original gate was a design bug (721 cells had
  `ic_ci_lower > 0` and were being rejected by fold-construction artifacts), which is a
  legitimate defense. But the sequence "gate fails → gate redesigned → gate passes" is exactly
  the pattern this ledger exists to flag. **Implication: the 37/28 qualifying-feature counts
  are gate-conditional in-sample results and carry accumulated selection pressure from this
  iteration. They must not be cited as evidence of edge until confirmed on the untouched OOS
  window (Phase 142A).**

### E3 — 2026-06-29 → 2026-07-01: three corpus rebuilds
- **Observed first / changed:** build 1 (2026-06-29) superseded by feature-factory changes
  (VP/SR removal, 7-feature demote/restore); build 2 (2026-06-30) superseded by Phase A
  methodology fixes; build 3 (2026-07-01) is current.
- **Pre-registered?** Mixed. Feature-set changes (build 1→2) were structural, not
  result-driven. Build 2→3 inherits E2's pressure.

### E4 — 2026-06-26: BIC K-selection (K=3 → K=5)
- **Observed first:** BIC study across SPY/TLT/GLD/EWT.
- **Changed:** `feature.hmm.n_components` 3 → 5; all regime labels re-derived.
- **Pre-registered?** Yes — model-selection criterion chosen before results, unanimous across
  symbols, provenance recorded in APR. This is the clean pattern; entries should look like
  this.

---

## Live Entries (append below; same commit as the change)

<!-- Template:
### E<n> — <date>: <one-line summary>
- **Observed first:** <the result that prompted the change>
- **Changed:** <what, where, commit>
- **Pre-registered?** <yes / partially / no — and the honest justification>
-->
