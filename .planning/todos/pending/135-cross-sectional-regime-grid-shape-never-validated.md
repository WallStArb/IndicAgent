---
status: pending
priority: P2
filed: 2026-07-18
source: session comparing HMM vs. cross-sectional regime validation status, prompted by a
  question about whether the cross-sectional label counts were ever tested the way HMM K was
---

# Cross-sectional regime grid shape (9 equity cells, 6 rates cells) was never validated — unlike HMM's K=5

## Finding

The per-symbol HMM's state count has real statistical justification: Phase 140.5 P2 ran a formal
BIC study (`BIC = -2×log_likelihood + n_params×ln(n_obs)`) across SPY/TLT/GLD/EWT, K=5 won
unanimously, applied via migration 176 with APR provenance `[bic_study_2026]`.

The cross-sectional regime model has no equivalent. Its label counts are a fixed deterministic
design, never selected via any statistical criterion:
- `equity`: VIX-percentile tercile (low/mid/high) × breadth tercile (bull/neutral/bear) = 3×3 = 9
  cells, unconditionally
- `rates`: curve-shape tercile-ish × credit-spread bucket = 3×2 = 6 cells

Nobody has asked "does a 3×3 grid separate IC better than 2×2, 4×4, or an asymmetric shape" —
the grid shape itself has never been a hypothesis under test, only ever a starting design
(`services/cross_sectional_regime_model.py`, originally `equity_regime_model.py`).

This is a distinct question from todo 092 (already open): todo 092 asks whether the *cut-point
values* within the existing 3×3 tercile design are well-calibrated (they're guessed defaults,
0.33/0.67/0.40/0.60). This todo asks whether the *number of cells* — the grid shape itself — is
right at all, independent of where the cuts sit within it.

## Why this matters

Per this project's own standard (earn promotion through proof, segment by regime — not segment
arbitrarily then call it a regime): the equity/rates cross-sectional models are the primary IC
stratification key today (`alpha.regime.equity_model_enabled=true` routes essentially all live
measurement through them, per todo 026's 2026-07-09 finding — the per-symbol HMM is shadow-only
in practice). A stratification key this load-bearing having an unvalidated cell count is a bigger
open question than any of the new candidate dimensions in
`docs/research/stratification-dimension-unification.md` — it's not "should we add a 4th axis,"
it's "is the shape of the axes we already depend on even right."

## Proposed approach

Once Phase 145's substitution-test machinery exists (same gate as every other stratification
candidate — see `docs/research/stratification-dimension-unification.md`), treat grid shape as a
model-selection question with the same rigor as the HMM's BIC study: compare IC separation (or a
BIC/AIC-style information criterion trading cell count against fit) across candidate grid shapes
(e.g. 2×2, 3×3 current, asymmetric variants) on the corpus, not just accept 3×3 because it's what
shipped first. Natural sequencing: after todo 092's cut-point recalibration (calibrate within the
current shape first), before or alongside Phase 145's new-dimension work (which will be
re-litigating "how many cells" for every new candidate anyway — solve it once, generically,
rather than per-dimension).

## References

- `.planning/todos/pending/092-equity-regime-model-threshold-calibration.md` — cut-point
  calibration within the existing grid shape; distinct from this todo's grid-shape question
- `.planning/ROADMAP.md` P2 "HMM State Count K via BIC" (todo 002) — the methodology this todo
  proposes extending to the cross-sectional side
- `docs/research/stratification-dimension-unification.md` — Phase 145's substitution-test /
  orthogonality gate machinery this would run through
- `.planning/todos/deferred/026-hmm-regime-audit-optimization.md` — 2026-07-09 finding that the
  cross-sectional model is the live-path stratification key, not the per-symbol HMM
