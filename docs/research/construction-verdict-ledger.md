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
| `cointegrated_pairs_residual` | 2026-08-07 | **DEAD (as tested — 6 ETF pairs only)** | `docs/research/measurement-cointegrated-pairs-residual.md`. **Reconsidered 2026-09-11**: verdict stands for the tested instance (0/6 broad sector/asset-class ETF pairs cointegrate); the 182-equity universe was never screened at any scale — genuinely untried, not re-litigated. See `docs/research/2026-09-11-strategic-plans-features-ensemble-construction.md`. |
| `retail_immediacy_provision` (levered-sleeve sharpening) | 2026-08-07 | **DEAD (falsified by its own pre-registered rule)** | Both the levered group AND the no-sleeve control group passed the bootstrap gate — the effect is ordinary intraday momentum present everywhere, not a levered-issuer close-rebalance flow. `docs/research/data-edge-source-thesis.md` (Retail Immediacy Provision section). |
| `dealer_hedging_flow` (options-expiry calendar screen) | 2026-08-07/08 | **DEAD, confirmed across two window specs** | Heavily-optioned group failed its bootstrap gate under both the original and a corrected (expiry-Friday-excluded) window; re-run moved closer to zero, consistent with dilution, still didn't clear. `docs/research/data-edge-source-thesis.md` (Dealer Hedging Flow section). |
| `statistical_factor_residual` (K-selection) | 2026-09-01 | **DEAD** | Residualizing didn't improve IC on any axis tested. Memory: `project_statistical_factor_residual_k_selection_2026_08_11.md`. |
| Todo 303 — per-symbol trend regime candidate | 2026-09-01 | **DEAD, closed** | Failed the standing null-arm (scrambled-data) control this project requires of every regime candidate. |
| Todo 304 — per-symbol percentile-rank regimes (volume/skew/volatility) | 2026-09-01 | **DEAD, closed** | Same null-arm standard; none sharpen IC beyond the already-live `regime_volatility`. |
| Todo 281 — systematic-dominance / volume-price-confirmation statistics | 2026-08-08 | **Rejected as HMM regime axes, NOT dead as features** | Both carry real signal fraction (0.375-0.401 at best window) but HMM identifiability moves the *opposite* direction from signal quality as the window strengthens — wrong shape for a regime, not wrong as a continuous feature. Recommended as `feature_vectors` columns instead, IC-separation-across-buckets test still pending. Findings doc: `171-CANDIDATE-REGIME-AXES-FINDINGS.md` §5.3/§6.1/§6.4. |
| `nonlinear_interaction_combiner` residual form (N1) | 2026-08-25, reconfirmed 2026-09-01 | **Structurally inconclusive — not a pass or a fail, confirmed not staleness** | Composite-vs-linear result flipped sign of significance between two adjacent `colsample_bytree` values at 1h, the strongest-evidenced timeframe. A bit-identical re-run 6 days later reproduced the same instability exactly, ruling out data drift as the cause. Do not cite as confirming or denying the thesis either way. `docs/research/measurement-nonlinear-interaction-combiner.md`. |
| `range_pct_fast_xs_ls_h5` (cross-sectional long-short) | 2026-09-02 | **DEAD (market-beta tilt, not a personal-scale edge)** | Real signal (shuffled-null p=0.0010) but OLS beta +1.14/R²=0.75 against the equal-weighted universe mean — a beta bet, not market-neutral alpha. Net-negative at all 9 personal-cost combinations tested. `concept_registry` (`domain='construction'`, `range_pct_fast_xs_ls_h5`); memory `project_range_pct_fast_prereg_verdict_dead.md`. **Reconsidered 2026-09-11 — confirmed settled**: the beta-neutralized residual *was* the actual test performed; no untried refinement of the same idea plausibly overturns a net-negative result at every one of 9 cost assumptions including the cheapest. |
| Phase 148 `alpha_score_directional` | 2026-09-02 | **Killed on paper** | Gate 1 passed (140/640 OOS cells) but fails the personal cost hurdle on every cell under the worst-case band, and — decisive, band-independent — Gate 2's realized OOS frame P&L is negative *gross* of any costs (mean -0.1215R). A lower cost hurdle can't rescue a negative gross edge. `concept_registry` (`phase148_alpha_score_directional`); todo 367. **Reconsidered 2026-09-11 — confirmed settled**: the 140-cell "pass" is selection-inflated (chosen from 640 by the same FDR procedure claiming significance; unbiased all-cell mean rank-IC is 0.000-0.050); 100% sign co-firing across cells means there was never independent breadth to refine. |
| `bars_since_high_fast_xs_ls_h5` (cross-sectional long-short) | 2026-09-11 | **DEAD (unconditional net-negative; regime-gate refinement also fails on decomposition)** | Unconditional full-history spread check: negative gross return (mean -0.0004/rebalance) despite positive pooled regime-averaged IC of 0.1118; low beta (0.19/R²=0.085) rules out beta-contamination. The apparent "0.11 avg IC, 46-symbol support" (`scripts/analysis/personal_edge_paper_screen.py`, H=5) decomposes into 5 FDR-passing `feature_ic_scores` cells drawn from FOUR STRUCTURALLY DIFFERENT regime taxonomies (`market_regimes.regime_group`: equity trend×vol, commodity contango/backwardation, rates curve-shape, fx dollar risk) — not one coherent "hold in regime X" signal. The standout cell, commodity `down_primary_backwardation` (IC=0.299, p=2e-5, FDR-pass), occurred on only 52 total days across 16 years (2008-2024) — a handful of macro-shock episodes (2008 crash, 2014-15 oil collapse, 2020 COVID, 2022 bear), not 52 independent bets; passing a mechanical FDR/CI gate doesn't rescue episode-clustered thinness this severe. Stripping it out, the only broad/robust cells are two equity ones (`mid_neutral` IC=0.043, `high_bear` IC=0.040, n_independent 24k/24k) — barely above the already-failed unconditional pooled IC, not enough to plausibly flip the spread result. No untried regime-gate construction survives this decomposition; graveyard reconsideration item #2 closed on this basis, not merely unreproduced. Structurally-motivated successor (SR-level-support divergence via `_compute_sr_dist_atr`) also tested, also flat (51-58% sign consistency). `docs/research/2026-09-11-strategic-plans-features-ensemble-construction.md` (graveyard #4); `project_strategic_plans_2026_09_11` memory. |
| `alpha_score_residual_single_security_15m` | 2026-09-03 | **FAIL, bucketed retest also FAIL — closed** | Family stat 0.00277 clears the effect-size floor and both bootstrap/null conditions pass, but 0/231 symbols individually qualify BY-FDR positive (floor 10%) — a uniformly dilute common effect, not concentrated per-name alpha. Raw (non-residualized) arm was ~3.8x stronger, confirming the predictivity is dominated by the common/market component the demeaning strips. `concept_registry` (`alpha_score_residual_single_security_15m`); workstream 2 of the personal-scale edge program. **Reconsidered 2026-09-11, bucketed retest run same day — FAST-KILL**: pre-registered 8-bucket sector split (`instruments.contract_details->>'sector'`, fixed mapping, 24 NULL-sector symbols ex-ante excluded) re-ran condition (d) as BY-FDR across 8 bucket-level null p-values instead of 231 per-symbol ones. 0/8 qualify — every raw bucket null_p was already >= 0.15 (range 0.15-0.80), well short of 0.05 before correction even applied. Per the pre-registered fast-kill rule (<=1 of ~8 clearing → abandon), this closes the construction: both per-symbol and bucketed forms of condition (d) have now failed. `scripts/analysis/alpha_score_residual_bucketed_retest_15m.py`. |

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
- **Reconsidered graveyard refinements, 2026-09-11** — a deliberately neutral-framed Fable
  pass re-examined all 4 DEAD/settled constructions below (excluding the already-final
  `range_pct_fast`/Phase 148 verdicts) for whether the failure mechanism was fundamental or a
  measurement artifact. Item #1 (`alpha_score_residual` bucketed retest) FAST-KILLED (0/8
  buckets) — closed same day. Item #2 (`bars_since_high_fast` regime-gate) also CLOSED same
  day, on stronger grounds than "unreproduced": the cited premise decomposed into an average
  across 4 incompatible regime taxonomies dominated by a 52-day event-clustered commodity
  cell — see its own ledger row above. Items #3-4 remain queued:
  `cointegrated_pairs_residual`'s 0/6 was ETF pairs only, never a same-sector single-equity
  screen; `cross_sectional_relative_value`'s dead `ctf_momentum` ranking doesn't retire the
  construction TYPE, whose production gate-evaluation infra
  (`cross_sectional_spread_tracker.py`) has never been tried with a different feature. Each
  has a specific refinement + fast-kill criteria, not open-ended re-litigation. Full detail:
  `docs/research/2026-09-11-strategic-plans-features-ensemble-construction.md`.
