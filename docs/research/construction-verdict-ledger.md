# Construction & Hypothesis Verdict Ledger

**Status:** current, filename-stable (edited in place, not re-dated on rewrite per
`docs/research/` convention).
**Purpose:** one place to answer "have we tried this, and what happened" for every
predictive-signal construction/hypothesis this project has run to a definitive verdict.
Distinct from `methodology-change-ledger.md` (tracks changes to test *machinery* made after
seeing results) and `docs/research/catalog.md` (tracks idea *docs* and their status, not
individual construction test outcomes).

**Sources, not duplicated here beyond a one-line summary:**
- `concept_registry` (`domain='construction'`, Postgres) — the canonical, structured record
  for constructions tested since the pre-registration discipline formalized (2026-09-02
  onward). Query directly for the authoritative current text; this doc's entries for that era
  are a snapshot, not a live mirror.
- Individual pre-registration/measurement docs (`docs/research/measurement-*.md`,
  `docs/plans/*-prereg*.md`) — full methodology and numbers.
- Session memory (`project_*` files) — process history, informal until a verdict lands here
  or in `concept_registry`.

**Scope:** predictive-signal hypothesis tests only (does construction X have real, tradeable
IC/edge) — not infrastructure phases, architecture decisions, or regime-labeling mechanics
unless they were themselves the thing under test.

**Maintenance:** append a row when a construction reaches a definitive verdict (DEAD / FAIL /
PASS / KILLED-ON-PAPER / structurally inconclusive). Don't relitigate a closed row here — if a
successor construction is tried, it gets its own row with a pointer back.

---

## Verdicted constructions, chronological

| Construction | Date | Verdict | Why |
|---|---|---|---|
| `jump_diffusion_decomposition` | 2026-08-07 | **DEAD** | Bipower-variation jump_ratio adds no partial IC beyond `garch_ratio`+`hurst`; CI crosses zero pooled and in all 5 regimes. `docs/research/measurement-jump-diffusion-decomposition.md`. |
| `cointegrated_pairs_residual` | 2026-08-07 | **DEAD** | `docs/research/measurement-cointegrated-pairs-residual.md`. |
| `retail_immediacy_provision` (levered-sleeve sharpening) | 2026-08-07 | **DEAD (falsified by its own pre-registered rule)** | Both the levered group AND the no-sleeve control group passed the bootstrap gate — the effect is ordinary intraday momentum present everywhere, not a levered-issuer close-rebalance flow. `docs/research/data-edge-source-thesis.md` (Retail Immediacy Provision section). |
| `dealer_hedging_flow` (options-expiry calendar screen) | 2026-08-07/08 | **DEAD, confirmed across two window specs** | Heavily-optioned group failed its bootstrap gate under both the original and a corrected (expiry-Friday-excluded) window; re-run moved closer to zero, consistent with dilution, still didn't clear. `docs/research/data-edge-source-thesis.md` (Dealer Hedging Flow section). |
| `statistical_factor_residual` (K-selection) | 2026-09-01 | **DEAD** | Residualizing didn't improve IC on any axis tested. Memory: `project_statistical_factor_residual_k_selection_2026_08_11.md`. |
| Todo 303 — per-symbol trend regime candidate | 2026-09-01 | **DEAD, closed** | Failed the standing null-arm (scrambled-data) control this project requires of every regime candidate. |
| Todo 304 — per-symbol percentile-rank regimes (volume/skew/volatility) | 2026-09-01 | **DEAD, closed** | Same null-arm standard; none sharpen IC beyond the already-live `regime_volatility`. |
| Todo 281 — systematic-dominance / volume-price-confirmation statistics | 2026-08-08 | **Rejected as HMM regime axes, NOT dead as features** | Both carry real signal fraction (0.375-0.401 at best window) but HMM identifiability moves the *opposite* direction from signal quality as the window strengthens — wrong shape for a regime, not wrong as a continuous feature. Recommended as `feature_vectors` columns instead, IC-separation-across-buckets test still pending. Findings doc: `171-CANDIDATE-REGIME-AXES-FINDINGS.md` §5.3/§6.1/§6.4. |
| `nonlinear_interaction_combiner` residual form (N1) | 2026-08-25, reconfirmed 2026-09-01 | **Structurally inconclusive — not a pass or a fail, confirmed not staleness** | Composite-vs-linear result flipped sign of significance between two adjacent `colsample_bytree` values at 1h, the strongest-evidenced timeframe. A bit-identical re-run 6 days later reproduced the same instability exactly, ruling out data drift as the cause. Do not cite as confirming or denying the thesis either way. `docs/research/measurement-nonlinear-interaction-combiner.md`. |
| `range_pct_fast_xs_ls_h5` (cross-sectional long-short) | 2026-09-02 | **DEAD (market-beta tilt, not a personal-scale edge)** | Real signal (shuffled-null p=0.0010) but OLS beta +1.14/R²=0.75 against the equal-weighted universe mean — a beta bet, not market-neutral alpha. Net-negative at all 9 personal-cost combinations tested. `concept_registry` (`domain='construction'`, `range_pct_fast_xs_ls_h5`); memory `project_range_pct_fast_prereg_verdict_dead.md`. |
| Phase 148 `alpha_score_directional` | 2026-09-02 | **Killed on paper** | Gate 1 passed (140/640 OOS cells) but fails the personal cost hurdle on every cell under the worst-case band, and — decisive, band-independent — Gate 2's realized OOS frame P&L is negative *gross* of any costs (mean -0.1215R). A lower cost hurdle can't rescue a negative gross edge. `concept_registry` (`phase148_alpha_score_directional`); todo 367. |
| `alpha_score_residual_single_security_15m` | 2026-09-03 | **FAIL** | Family stat 0.00277 clears the effect-size floor and both bootstrap/null conditions pass, but 0/231 symbols individually qualify BY-FDR positive (floor 10%) — a uniformly dilute common effect, not concentrated per-name alpha. Raw (non-residualized) arm was ~3.8x stronger, confirming the predictivity is dominated by the common/market component the demeaning strips. `concept_registry` (`alpha_score_residual_single_security_15m`); workstream 2 of the personal-scale edge program. |

## Supporting measurements (not standalone construction verdicts, but load-bearing context)

- **Effective breadth ~8.4 vs. raw feature count ~230** (measured alongside the discovery-track
  pilots, 2026-08-07/08) — the corpus has far fewer genuinely independent bets than its column
  count suggests. Relevant whenever a new candidate's "how much room is left" question comes up.
- **Personal-scale cost hurdle is not the binding constraint at this account size** (0b,
  2026-09-02) — worst-case `IC_min` ~0.003-0.004 at H=5-10 vs. measured signal mass 0.03-0.055;
  the institutional Gate 2 that killed Phase 148 was calibrated to a different (larger) trader.
  This is why several of the DEAD verdicts above are about *signal not existing at the
  personal-name level* (alpha_score_residual) or being *a disguised factor bet*
  (range_pct_fast), not about costs — costs stopped being the limiting factor from 0b onward.
- **Phase-family feature-quality audit** (2026-08-25, live `feature_ic_scores`): SMC (order
  blocks, FVG, sweeps) 66.7% gate-clear rate, best family in the corpus; classical
  swing/Fibonacci structure 27%, with several columns (including `swing_volume_confirmation`
  — the same column round 1 of the 2026-09-06 volume-divergence pre-registration found
  measures the wrong thing for that construction) showing literally zero gate-clears anywhere.
  Corroborating, not conclusive on its own.

## Currently in flight (not yet verdicted)

- **H-A / H-B (extreme-volume divergence / confirmation)** — both constructions finalized and
  twice-reviewed (H-B: three attempts, from-scratch redesign) as of 2026-09-09, neither has
  run. `docs/plans/2026-09-06-extreme-volume-divergence-confirmed-reversal-prereg.md`.
