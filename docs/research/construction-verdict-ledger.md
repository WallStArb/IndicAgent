# Research ledger: every alpha idea and where it stands

**Status:** current, filename-stable (edited in place). Last full reconciliation 2026-09-25.
**Purpose:** the one list of alpha research. Section 1 is what is queued or running, section 2
what is reopened, section 3 what was never tested, section 4 the frozen verdict record. It
replaces the idea rows of the deleted `docs/research/catalog.md` and the alpha bullets of
`.planning/IDEAS.md`. Designs live in the linked docs; status lives here only.

**How status works under E15** (`docs/plans/2026-09-24-evidence-framework.md`, adopted
2026-09-25): the unit of test is a book version, not an idea. Ideas enter as pre-registered
family members; the ridge combiner sets their weights walk-forward; each book version tested on
vintage 1 (data before `alpha.validation.oos_start`, 2025-12-24) spends one screen test from a
budget of M = 30, count restarted at 0 on adoption (bar p < 0.00167). Confirmation is one test
of a frozen book on the forward span. A frozen verdict below is never edited; revisiting an idea
means a new pre-registered family member ("reopened as family X"), which enters a counted book
version. The 18 pre-E15 verdicts count toward nothing now, but every family built on seen data
discloses that look.

**Maintenance:** change a row's status in the same commit as the work that changes it. Add a
section 4 row when a pre-E15-style standalone verdict is recorded (none are expected now).

## 1. Active queue

Family designs are in `docs/plans/2026-09-25-alpha-research-architecture.md` section 4. No
family has a real-data number yet: the first run waits for phase 183 (spec runner, ledger
writer, combiner, book test), so no number exists outside a recorded run.

| # | Family | Status | Blocked on |
|---|---|---|---|
| 1 | Intraday same-slot periodicity (Heston, Korajczyk, Sadka 2010), members P1-P4 | **REGISTERED** 2026-09-25, `docs/plans/2026-09-25-family1-intraday-periodicity-prereg.md` | Phase 183; family 1 build items R1 (dollar-neutral construction) and R2 (session-aggregated scoring). R3 (per-slot market beta) shipped c73cb8307 |
| 1b | Residual first-half-hour to last-half-hour (split out of family 1 as P5) | Design in section 4 of the architecture doc | Pre-registration. Must disclose `retail_immediacy_provision`'s 2026-08-07 finding (intraday momentum present in every group), which was seen on this data; and the corpus `power_hour` pooled IC (section 5), a pending member |
| 2 | Overnight versus intraday return decomposition (Lou, Polk, Skouras 2019; Berkman et al. 2012 for the same-day gap) | Registered 2026-09-25: `docs/plans/2026-09-25-family2-overnight-intraday-prereg.md`. Six members on one signal row (09:45, first 15m bar's close) targeting the rest of the session: intraday persistence 20/60, overnight-to-intraday 20/60, gap fade, scaled gap fade. Members' universe US-session equities (187 names). Gap members disclosed as seen-data re-specifications (section 5 look); low-liquidity gap fade kept as a diagnostic, not a member. Overnight persistence (overnight target) not tested here | Build B1 (session-legs panel, per-leg S1), B2 (family 2 power plant), B3 (universe filter); then the book run (one of M = 30) |
| 3 | ETF-to-constituent and cross-asset lead-lag, 5m to 1h | Design only; same idea as the Edge Source Thesis's never-run `cross_asset_lead_lag` | Pre-registration |
| 4 | Short-term reversal (todo 423) | Design only. In-sample panel is seen data (2026-09-13 screen); daily form runs only on symbols added since or phase 180 onboarding, never the forward span | Pre-registration with disclosure and one-bar skip variants |
| 5 | Period-end marking (Carhart, Kaniel, Musto, Reed 2002) | Design only (owner-proposed) | Power check, then pre-registration |
| 6 | Period-end disclosure and liquidation flows (window dressing, tax-loss selling) | Design only (owner-proposed) | Power check; survivorship (todo 376) if marginal |
| 7 | Index reconstitution | **Held** | A point-in-time event history (no source) |
| 8 | Options expiry flows (pinning and release, quarterly dose-response) | Design only | A split history (stored prices are split-adjusted); no open-interest capture (owner decision 2026-09-25) |
| 9 | Price anchoring and slow reversal (George and Hwang 2004 for the 52-week-high anchor, which predicts continuation, the opposite sign to the raw corpus result; the pre-registration states the expected sign). Pending members: `vwap_dev_sigma`, `high_52w_dist`, `rsi_slow`, `aroon_slow`, `price_percentile_slow`, `stoch_k_slow`, `dist_from_high_slow` | Design only, proposed 2026-09-25. Daily clock, one-session target; persistence enters as declared smoothing or lag members, and the run reports each member's IC term structure to lag 60 (`docs/plans/2026-09-25-multi-timeframe-horizon-design.md`; section 5: predictability had not decayed by the longest horizon measured). Before confirmation: survivorship bound (todo 376) and dividend adjustment (todo 428, price-only prices can manufacture this signal on high-yield names). Screenable only if its alpha's autocorrelation time passes the proposed effective-draw refusal (design D6), or under a within-cluster permutation null. Must declare how it relates to family 4 so the same reversal edge is not counted twice | Pre-registration; E15 step 0 residual n_eff at 1d, which sets whether h 20 and 60 have power |
| 10 | Volume and order flow. Pending members: `up_vol_ratio_fast`, `ofi_z`, `obv_z`, `mfi_slow`, and the todo 281 systematic-dominance and volume-price-confirmation statistics (rejected as HMM axes, not as features) | Design only, proposed 2026-09-25. Weak per-feature support (about 8-9 of 232 names FDR-pass each), the many-weak-members shape ridge pools | Pre-registration; step 0 residual n_eff at 5m and 15m |

## 2. Reopened as new family members (pre-registration pending)

Owner decision 2026-09-25. Reopened because the old verdict came from a gate E15 removed, from a
failure the new architecture fixes, or from an underpowered vehicle; not because code changed.
Each is disclosed as seen data. The section 4 rows stay frozen.

| Idea | Frozen verdict | Why reopened | Enters as |
|---|---|---|---|
| `alpha_score_residual_single_security_15m` | FAIL 2026-09-03: family statistic and both nulls passed, 0/231 names qualified individually | The per-name concentration gate is removed under E15; a weak effect spread across many names is the target shape. S1 now removes the common component that dominated the raw arm | A 15m single-name family on S1 residual targets |
| `range_pct_fast_xs_ls_h5` (both forms) | DEAD 2026-09-02 / 2026-09-13: real signal (shuffled p 0.001), beta tilt; single-name form failed 3/3 stability | S1 residualizes the target, which is the failure mechanism; the 3/3 stability gate is removed | A cross-sectional family on S1 residual targets |
| Corpus features through the ensemble (phase 179) | FAIL 2026-09-25 on the 13-ETF sleeve | Wrong vehicle: 13 names, arms with 0% power on slow edges (V3b). Wrong gating: production selects features by BH-FDR on thin regime x tf cells, which drops weak real features and inflates survivors (the Phase 148 failure). The ~290-column corpus has never been tested as a book on the 233-name residual panel | Feature families (SMC structure, volatility state, ...) admitted on prior, corpus IC table disclosed. Every member of an admitted family enters; no per-feature IC gate, walk-forward ridge weights instead |
| TSMOM on the sleeve | FAIL 2026-09-24, p 0.22, positive in 3/3 sub-periods | Underpowered on 13 names | New construction: residual momentum, 12-1 month on S1 residual returns (Blitz, Huij, Martens 2011) |

## 3. Open, never tested

Candidates with no verdict. None is queued; each needs a family spec to enter a book.

| Idea | Where | Note |
|---|---|---|
| Overnight futures path to ETF open | `docs/research/data-edge-source-thesis.md` | Falsification pre-registered in that doc, never run |
| `ctf_momentum` combined with the other untested `_build_ctf_series()` siblings | same | "Both proven independently, combination untested" |
| Adaptive combiner weights (regime-aware ensemble weights) | `docs/research/measurement-adaptive-combiner-weights.md` | Gated-open since 2026-08-07; overlaps S7's walk-forward ridge, decide there |
| Volume-price confirmation and systematic-dominance statistics as features (todo 281) | `.planning/milestones/v3.1-phases/171-hmm-walk-forward-regime-labeling-parameter-lookahead-fix/171-CANDIDATE-REGIME-AXES-FINDINGS.md` §6 | Rejected as regime axes, never tested as features |
| Cross-sectional relative-value feature family (`momentum_rank_z`, `volatility_rank_z`, `volume_rank_z`, never computed) | `.planning/todos/completed/073-cross-sectional-relative-value-feature-family.md` | Moved from todo 073 in the 2026-09-26 triage. The three columns overlap todo 421 step 2 (implement or deprecate). Includes the 5m-vs-15m timeframe choice from closed todo 235 |
| OHLCV microstructure proxies (Corwin-Schultz and Roll spreads, Amihud, spread regime) | `.planning/todos/completed/074-microstructure-proxy-feature-family.md` | Moved from todo 074, 2026-09-26. Dual use: a measured per-symbol spread for the cost band diagnostics |
| Small additions: permutation entropy, dollar-bar clock pilot, sub-bar path summaries | `.planning/todos/completed/075-small-feature-additions-entropy-dollar-bars-subbar.md` | Moved from todo 075, 2026-09-26. Dollar bars are a sampling change, not a member; would be its own book version |
| Rolling volume profile at 1d (`poc_rolling_dist_atr`, `poc_session_rolling_divergence_atr`, suppressed for 1d with session VP) | `.planning/todos/completed/213-rolling-vp-suppressed-for-1d-never-independently-reviewed.md` | Moved from todo 213, 2026-09-26. Needs the 1d columns computed before any family can use them |
| Outcome-target refinements (beta-hedged residual, overnight/intraday decomposition) | `.planning/todos/completed/077-outcome-target-refinements-vol-normalized-residual-overnight.md` | Moved from todo 077, 2026-09-26. Mostly covered by S1's residualized target and family 2; remaining piece is the overnight leg as a separate target |
| Confluence as a governed predictor family | `docs/research/intel-confluence-detection-persistence-layer.md` | Draft |
| PrecedentEngine (k-NN retrieval of similar states) | `docs/research/intel-precedent-engine.md` | Draft; glossary gates it on the ensemble showing IC > 0 |
| Curated interaction layer (Interaction Factory v2) | `docs/research/intel-feature-interaction-factory.md`, `docs/research/2026-09-11-strategic-plans-features-ensemble-construction.md` | Pilot (todo 037) cleared 22.2% of terms at BH-FDR; never run at full scale. Highest-value ensemble candidate: enters as a family of 20-30 theory-motivated pairwise terms |
| Gradient-boosted (LightGBM) scoring or ensemble pilot | `docs/research/archive/2026-03-19-ml-scoring-research.md` | Designed, never run; would enter as a combiner variant, a new book version |
| Nonlinear combiner (N1) redesign | `docs/research/measurement-nonlinear-interaction-combiner.md` | Inconclusive (hyperparameter-unstable, reproduced exactly); only worth a new design with a per-feature gain cap, as a combiner variant (a new book version) |
| Regime-conditioned combiner (regime labels as S7 interaction inputs) | section 4 rows: regime-conditional persistence (0/270 cells), `bars_since_high` regime gate | Poor prior; admissible only as a pre-registered combiner variant |
| Participation-state combiner variant (RSP/SPY concentration trend as the S7 regime input, members enter as `s` and `s x z_t`) | `docs/ideas/signal-participation-state-style-spreads.md` part A | Owner idea 2026-09-25. The concrete first case of the row above: one variant, continuous trailing-rank state, no threshold sweep. Needs S7 and a base book; costs one screen test |
| Factor momentum on style spreads (RSP/SPY, IWM/SPY, VTV/VUG; SPHB/USMV, MTUM/SPY, QUAL/SPY from 2011-2013) | same, part B | Raw-return time-series book (S1 removes style returns, so not a residual family). Synthetic power check first: 80% power needs annual Sharpe about 0.9 (3 spreads) to 1.1 (6 spreads); expected to be refused on vintage 1 |
| OHLCV primitive expansion | `docs/research/signal-renaissance-primitives-ohlcv.md` | Idea |
| Candlestick pattern expansion | `docs/research/archive/candlestick-pattern-expansion-research.md` | Untested as v3 features (the feature factory carries only body/range ratios); weak prior |
| Intelligence palette brainstorm (I2-I6, SMC additions) | `docs/research/archive/intelligence-redo-brainstorm.md` | Shipped in v2.x; SMC and OFI features are in the v3 feature factory, BOCPD and Kalman (next rows) are not |
| BOCPD change-point features | `docs/plans/archive/2026-02-14-bocpd-changepoint-design.md` | v2.x plugin design; not a v3 feature-factory column |
| Kalman trend features | `docs/plans/archive/2026-02-19-kalman-trend-design.md` | v2.x plugin design; not a v3 feature-factory column |
| I7 quant audit, "10 structural gaps" | `docs/research/archive/i7-quant-audit-2026-03-16.md` | Written for the v2.x I7 layer; OFI is now a v3 feature; recheck the other gaps (divergence stack, CIS learning loop) against the E15 book |
| Renaissance refinement ideas (105 across 48 sections) | `docs/research/archive/signal-06-renaissance-refinements.md`, `docs/plans/archive/2026-03-07-i7-i8-renaissance-refinement-design.md` | Written against the v2.x I7/I8 tiers; not yet read at v3 altitude, so unsorted |
| Sensitivity x regime interaction primitives | `docs/ideas/signal-sensitivity-regime-interaction-primitives.md` | Revision required after its 2026-09-18 review |
| Quarterly seasonality / OPEX risk-off | `docs/ideas/signal-quarterly-seasonality-opex-risk-off.md` | Overlaps families 5 and 8 |
| Political / policy regime | `docs/ideas/signal-political-policy-regime.md` | Idea |
| Event catalog and impact measurement | `docs/ideas/from-ssfi/signal-event-catalog-and-impact-system.md` | Idea |
| Factor sensitivity, cross-asset regime levels | `docs/ideas/from-ssfi/signal-factor-sensitivity-cross-asset.md` | Idea |
| Convolutional raw-window representation | `docs/ideas/signal-convolutional-raw-window-representation.md` | Idea, skeptical on arrival |
| Implied borrow cost from listed derivatives | `docs/ideas/signal-implied-borrow-cost-from-listed-derivatives.md` | Needs options data |
| Orderflow setups (delta divergence, imbalance, absorption) | `.planning/IDEAS.md` | Needs tick-level bid/ask data |
| News sentiment, alternative data | `.planning/IDEAS.md`, `docs/research/data-alt-data-sources.md` | Needs a data source |

## 4. Verdict record (frozen, chronological)

| Construction | Date | Verdict | Why |
|---|---|---|---|
| `jump_diffusion_decomposition` | 2026-08-07 | **DEAD** | Bipower-variation jump_ratio adds no partial IC beyond `garch_ratio`+`hurst`; CI crosses zero pooled and in all 5 regimes. `docs/research/measurement-jump-diffusion-decomposition.md`. |
| `cointegrated_pairs_residual` | 2026-08-07 | **DEAD — closed for good, both ETF and single-name forms exhausted** | `docs/research/measurement-cointegrated-pairs-residual.md`. Original: 0/6 broad sector/asset-class ETF pairs cointegrate (Stage 1). **Reconsidered 2026-09-11, same-sector single-equity screen run**: `scripts/analysis/cointegrated_pairs_residual_same_sector_screen.py` tested 471 economically-motivated same-sector single-name pairs (ITR `single_name_equity` tag × `instruments.contract_details->>'sector'`, 20 sectors, sub-sector granularity kept for tight linkage) — Stage 1 Engle-Granger (identical methodology/split-date to the original pilot, reused via import) with BY-FDR correction across all 471, then Stage 2 OOS split-sample reconfirmation for corrected survivors. **0/471 pairs qualify** (0 even survive corrected Stage 1 alone) — a far stronger, better-powered result than the original 0/6. Per the pre-registered fast-kill rule, this is decisive: cointegration is genuinely rare in this corpus/era regardless of granularity. Construction type closed for good — do not narrow further (e.g. sub-industry) or re-litigate. |
| `retail_immediacy_provision` (levered-sleeve sharpening) | 2026-08-07 | **DEAD (falsified by its own pre-registered rule)** | Both the levered group AND the no-sleeve control group passed the bootstrap gate — the effect is ordinary intraday momentum present everywhere, not a levered-issuer close-rebalance flow. `docs/research/data-edge-source-thesis.md` (Retail Immediacy Provision section). |
| `dealer_hedging_flow` (options-expiry calendar screen) | 2026-08-07/08 | **DEAD, confirmed across two window specs** | Heavily-optioned group failed its bootstrap gate under both the original and a corrected (expiry-Friday-excluded) window; re-run moved closer to zero, consistent with dilution, still didn't clear. `docs/research/data-edge-source-thesis.md` (Dealer Hedging Flow section). |
| `statistical_factor_residual` (K-selection) | 2026-09-01 | **DEAD** | Residualizing didn't improve IC on any axis tested. Memory: `project_statistical_factor_residual_k_selection_2026_08_11.md`. |
| Todo 303 — per-symbol trend regime candidate | 2026-09-01 | **DEAD, closed** | Failed the standing null-arm (scrambled-data) control this project requires of every regime candidate. |
| Todo 304 — per-symbol percentile-rank regimes (volume/skew/volatility) | 2026-09-01 | **DEAD, closed** | Same null-arm standard; none sharpen IC beyond the already-live `regime_volatility`. |
| Todo 281 — systematic-dominance / volume-price-confirmation statistics | 2026-08-08 | **Rejected as HMM regime axes, NOT dead as features** | Both carry real signal fraction (0.375-0.401 at best window) but HMM identifiability moves the *opposite* direction from signal quality as the window strengthens — wrong shape for a regime, not wrong as a continuous feature. Recommended as `feature_vectors` columns instead, IC-separation-across-buckets test still pending. Findings doc: `171-CANDIDATE-REGIME-AXES-FINDINGS.md` §5.3/§6.1/§6.4. |
| `nonlinear_interaction_combiner` residual form (N1) | 2026-08-25, reconfirmed 2026-09-01 | **Structurally inconclusive — not a pass or a fail, confirmed not staleness** | Composite-vs-linear result flipped sign of significance between two adjacent `colsample_bytree` values at 1h, the strongest-evidenced timeframe. A bit-identical re-run 6 days later reproduced the same instability exactly, ruling out data drift as the cause. Do not cite as confirming or denying the thesis either way. `docs/research/measurement-nonlinear-interaction-combiner.md`. |
| `range_pct_fast_xs_ls_h5` (cross-sectional long-short) | 2026-09-02, numbers corrected 2026-09-13 | **DEAD (market-beta tilt, not a personal-scale edge) — verdict unchanged after correcting a real 10x cost-model bug** | Real signal (shuffled-null p=0.0010) but OLS beta +1.14/R²=0.75 against the equal-weighted universe mean — a beta bet, not market-neutral alpha. **2026-09-13: found the falsification script's spread constant carried a 10x transcription bug (0.0014=14bp instead of 0.00014=1.4bp — the same bug `personal_edge_paper_screen.py` had already caught and fixed in itself, never propagated here), undetected 11 days through an AGY design review and the 2026-09-11 graveyard reconsideration.** Re-ran the full falsification at the corrected anchor: verdict unchanged, still DEAD — all 9 cost combos still fail CI>0 (corrected cheapest-corner CI [−5.0, +8.6]bp, mean +1.85bp, vs the originally-recorded [−7.9, +5.8]bp), stability still fails on the same 2-of-3-subperiods-negative shape (corrected: −3.9/−6.4/+14.2bp vs originally-recorded −9.7/−12.1/+8.7bp). Point estimates shifted meaningfully favorable throughout; the qualitative conclusion did not. `concept_registry` (`domain='construction'`, `range_pct_fast_xs_ls_h5`, migrations 329+335); memory `project_range_pct_fast_prereg_verdict_dead.md`. **Reconsidered 2026-09-11 — confirmed settled**: the beta-neutralized residual *was* the actual test performed; no untried refinement of the same idea plausibly overturns a net-negative result at every one of 9 cost assumptions including the cheapest — this conclusion is re-verified, not undermined, by the 2026-09-13 correction. |
| Phase 148 `alpha_score_directional` | 2026-09-02 | **Killed on paper** | Gate 1 passed (140/640 OOS cells) but fails the personal cost hurdle on every cell under the worst-case band, and — decisive, band-independent — Gate 2's realized OOS frame P&L is negative *gross* of any costs (mean -0.1215R). A lower cost hurdle can't rescue a negative gross edge. `concept_registry` (`phase148_alpha_score_directional`); todo 367. **Reconsidered 2026-09-11 — confirmed settled**: the 140-cell "pass" is selection-inflated (chosen from 640 by the same FDR procedure claiming significance; unbiased all-cell mean rank-IC is 0.000-0.050); 100% sign co-firing across cells means there was never independent breadth to refine. |
| `bars_since_high_fast_xs_ls_h5` (cross-sectional long-short) | 2026-09-11 | **DEAD (unconditional net-negative; regime-gate refinement also fails on decomposition)** | Unconditional full-history spread check: negative gross return (mean -0.0004/rebalance) despite positive pooled regime-averaged IC of 0.1118; low beta (0.19/R²=0.085) rules out beta-contamination. The apparent "0.11 avg IC, 46-symbol support" (`scripts/analysis/personal_edge_paper_screen.py`, H=5) decomposes into 5 FDR-passing `feature_ic_scores` cells drawn from FOUR STRUCTURALLY DIFFERENT regime taxonomies (`market_regimes.regime_group`: equity trend×vol, commodity contango/backwardation, rates curve-shape, fx dollar risk) — not one coherent "hold in regime X" signal. The standout cell, commodity `down_primary_backwardation` (IC=0.299, p=2e-5, FDR-pass), occurred on only 52 total days across 16 years (2008-2024) — a handful of macro-shock episodes (2008 crash, 2014-15 oil collapse, 2020 COVID, 2022 bear), not 52 independent bets; passing a mechanical FDR/CI gate doesn't rescue episode-clustered thinness this severe. Stripping it out, the only broad/robust cells are two equity ones (`mid_neutral` IC=0.043, `high_bear` IC=0.040, n_independent 24k/24k) — barely above the already-failed unconditional pooled IC, not enough to plausibly flip the spread result. No untried regime-gate construction survives this decomposition; graveyard reconsideration item #2 closed on this basis, not merely unreproduced. Structurally-motivated successor (SR-level-support divergence via `_compute_sr_dist_atr`) also tested, also flat (51-58% sign consistency). `docs/research/2026-09-11-strategic-plans-features-ensemble-construction.md` (graveyard #4); `project_strategic_plans_2026_09_11` memory. |
| `alpha_score_residual_single_security_15m` | 2026-09-03 | **FAIL, bucketed retest also FAIL — closed** | Family stat 0.00277 clears the effect-size floor and both bootstrap/null conditions pass, but 0/231 symbols individually qualify BY-FDR positive (floor 10%) — a uniformly dilute common effect, not concentrated per-name alpha. Raw (non-residualized) arm was ~3.8x stronger, confirming the predictivity is dominated by the common/market component the demeaning strips. `concept_registry` (`alpha_score_residual_single_security_15m`); workstream 2 of the personal-scale edge program. **Reconsidered 2026-09-11, bucketed retest run same day — FAST-KILL**: pre-registered 8-bucket sector split (`instruments.contract_details->>'sector'`, fixed mapping, 24 NULL-sector symbols ex-ante excluded) re-ran condition (d) as BY-FDR across 8 bucket-level null p-values instead of 231 per-symbol ones. 0/8 qualify — every raw bucket null_p was already >= 0.15 (range 0.15-0.80), well short of 0.05 before correction even applied. Per the pre-registered fast-kill rule (<=1 of ~8 clearing → abandon), this closes the construction: both per-symbol and bucketed forms of condition (d) have now failed. `scripts/analysis/alpha_score_residual_bucketed_retest_15m.py`. |
| `range_pct_fast_xs_ls_h5_single_name_only` (successor, Pre-registration 3) | 2026-09-13 | **DEAD (stability criterion fails)** | Successor to the pooled `range_pct_fast_xs_ls_h5` verdict above, restricted to the 128-symbol single-name-equity subset after a diagnostic found the pooled verdict's beta contamination was disproportionately an ETF-subset property (single-name β=0.91/R²=0.44 vs. ETF-only β=1.31/R²=0.82). Full pre-registration written, AGY-reviewed before running (raised valid meta-FDR/cost-realism/null-validity/survivorship objections, recorded but not resolved — moot for this verdict) and specifically flagged that the stability criterion (net > 0 in 3/3 subperiods) fails. AGY's own specific subperiod numbers were independently verified and found WRONG, but the qualitative call held: true numbers +17.87bp / **-1.14bp** / +4.87bp (subperiod 2, 2013-10-02..2019-11-06, at anchor cost) — criterion (c) requires strict positivity in all three, fails on subperiod 2 alone. Per the pre-registration's own no-post-hoc-loosening clause, this is DEAD on criterion (c) without needing the full bootstrap CI/shuffled-null machinery (all three criteria are required; (c) already fails). The preliminary diagnostic's headline 10.17bp (primary-phase-only) masked this — excess return concentrated in the 2007-2013 crisis era, not uniform. `concept_registry` (`range_pct_fast_xs_ls_h5_single_name_only`, migration 334); `docs/plans/2026-09-02-personal-scale-edge-determination-plan.md` (Pre-registration 3); todo 375 (completed). |

| H-A `extreme_volume_divergence` (15m, within-symbol) | 2026-09-24 | **FAIL (all five gated criteria), weak effect in the reverse direction** | Pre-registered Track 1, 233 symbols, B=2000, N=1000, panel-synchronous whole-date shift null (todo 372's reviewed fix). Gated 1-bar: family IC -0.0022, CI [-0.0051, +0.0005], null p 0.92 for the predicted direction, negative in all 3 thirds, 0.9% of symbols BY-qualify. 2-bar (reported): IC -0.0033, CI [-0.0067, -0.0002] entirely negative, 8 symbols significant the wrong way. Light volume at a fresh extreme leans very slightly toward continuation (capitulation read), not the predicted reversal; afternoon more negative than morning, so not the open's volume smile. The reverse direction was not pre-registered and is at the effect floor: not claimable from this run. `logs/extreme_volume/h_a_h_b_track1_20260924T201208Z.json` (commit f461bdc54); `scripts/analysis/extreme_volume_divergence_track1.py`; pre-reg `docs/plans/2026-09-06-extreme-volume-divergence-confirmed-reversal-prereg.md`. |
| H-B `confirmed_reversal` K=3 (15m, within-symbol) | 2026-09-24 | **FAIL (all five gated criteria), no detectable signal** | Same run and machinery. Gated 1-bar: family IC +0.0007, CI [-0.0030, +0.0046], null p 0.37, sub-thirds +0.0029/+0.0017/-0.0022, 0/233 symbols qualify. 2-bar (reported) +0.0029, CI through zero, positive in all thirds but 0 qualifiers. Ungated K robustness: K=1 +0.0006, K=2 +0.0004, K=5 +0.0042 (positive in all thirds) -- choosing K=5 after seeing it is the forking path the pre-registration forbids; not a lead without a fresh pre-registration and its own N_tested increment. |
| `tsmom_sleeve` classic time-series momentum, 13-symbol cross-asset sleeve (1d, fixed sign) | 2026-09-24 | **FAIL (p 0.22), weak positive excess in all sub-periods** | Pre-registered (`docs/plans/2026-09-24-phase181-tsmom-sleeve-prereg.md`, frozen 0c33a2596; V2 2.0%, V3 54% at excess 0.50). 12-month trailing log return, sign/vol book, phase 179 evaluator with memory-aware whole-panel shift null (K=3,389). Observed Sharpe 0.47 gross vs null median 0.27: excess +0.19, bootstrap CI [-0.32, +0.73], permutation p 0.22; sub-period excess positive 3/3. Most of the book's return is drift a shifted copy also earns; the timing part is below detection at 13 years. Closes classic TSMOM and its variants (unsigned, 12-1, other lookbacks) on this sleeve. First test of the paradigm here (the 2026-09-13 screen measured a daily RSI). N_tested 18. |
| Phase 179 cross-asset sleeve walk-forward: production ensemble weights (equity-group pooled 1d IC, yearly refits 2011-2025), calibrated arms `ic_proportional`/`vol_normalized`/`mean_variance` on the 13-symbol sleeve | 2026-09-25 | **FAIL (no arm qualifies; best adj p 0.36)** | Pre-registered (`docs/plans/2026-09-24-phase179-sleeve-walk-forward-prereg.md`, frozen da0548a96; rerun under methodology-change-ledger E14 after the frozen run ended FIDELITY BROKEN on a calibration-coverage defect, no performance number read in between). Point-in-time walk-forward, 2013-2025, whole-panel shift null (2,885 shifts, memory 758), Westfall-Young across 3 arms. Excess Sharpe: ic_proportional +0.22 (CI -0.33 to +0.68, adj p 0.36, sub-periods -/+/+), vol_normalized -0.15 (p 0.88), mean_variance -0.11 (p 0.85). The in-sample Sharpe ~1.19 portfolio diagnostic (2026-09-22) does not survive point-in-time weights. Scope: V3b showed these calibrated arms have 0% power on slow return-built edges, so this FAIL says nothing about those; V3 power on the planted fast edge was 83% at excess 0.85. N_tested 18. |

## 5. Supporting measurements (not verdicts, but load-bearing context)

- **Corpus feature IC by timeframe and horizon, 2026-09-25 (disclosure for families 1b, 9, 10).**
  Read from `feature_ic_scores` (`regime_scope = 'pooled'`, raw IC, vintage 1) while scoping feature
  families. The largest pooled ICs are one mechanism: price position within its recent range, 1d
  h 10 (`vwap_dev_sigma` -0.061, `high_52w_dist` -0.058, `rsi_slow` -0.052, `price_percentile_slow`
  -0.046), with 0 or 1 of 227 names FDR-passing (overlapping 10-day windows, few independent
  observations). The IC depends on calendar horizon, not timeframe: the same features at 1h reach
  -0.03 at h 20 (about 3 sessions) and -0.036 to -0.056 at h 60 (about 9 sessions), matching 1d at
  h 5 to 10, and are about 0 at every 5m and 15m horizon (all within one session). IC over the square
  root of horizon is roughly flat from 1 to 10 days, so the predictability had not decayed by the
  longest horizon measured (`alpha.ic.lookahead.1d.extended` = 10); 20 to 60 days was never
  measured. Broad support is rare: `power_hour` 57/232 at 5m (+0.011), `gap_z` 95/232 (a bar-to-bar
  artifact, see the next note); everything else is at most about 9/232. `canary_acausal_placebo`
  at 0.654 on 229/229 confirms the lookahead canary works.
- **Corpus gap features, pooled IC look, 2026-09-25 (disclosure for family 2).** Gap fade was never
  tested as a construction or book; it existed only as five corpus features scored per feature by
  `ic_engine`. Read from `feature_ic_scores` (`regime_scope = 'pooled'`, raw IC, not residualized,
  vintage 1) while scoping family 2: `opening_gap_pct` (session open vs prior close) is about 0 at 1d
  (0/229 FDR passes) and slightly positive intraday (+0.004 to +0.006, continuation, not reversion;
  magnitude-conditional IC +0.008 to +0.011 intraday, about -0.014 at 1d h 5-10); `overnight_gap_z`
  and `gap_filled` are about 0 at every timeframe. `gap_z` is strongly negative intraday (-0.023 at
  5m and 15m, 95/232 and 69/233 names FDR-pass) but is misnamed: it is `open[i] - close[i-1]` over
  ATR on every bar (`feature_factory.py::_gap_z_series_full`), so intraday it measures the
  bar-to-bar open discontinuity, most likely bid-ask bounce or open-print noise, not the overnight
  gap (unverified; `overnight_gap_z`, the same raw input on a gap-history scale, is flat). Family 2's
  gap members are specified on seen data and must say so; the `gap_z` effect is a separate
  microstructure idea, not evidence for gap fade.
- **TSMOM per-symbol (time-series/absolute momentum) screen — NEGATIVE, 2026-09-13.**
  Council review of the fired decision gate found this construction TYPE (per-symbol,
  no cross-sectional ranking — structurally distinct from every construction actually
  falsified in this program) had been proposed
  (`docs/research/2026-09-11-strategic-plans-features-ensemble-construction.md`) but
  never executed. Ran the "near-free" screen that doc specified: per-symbol Spearman IC
  of `ctf_momentum` vs. `forward_returns.return_mid` (H=5, IS window), circular-shift
  null, BH-FDR per symbol family (`scripts/analysis/tsmom_per_symbol_ic_screen.py`).
  **Mean IC negative across every split** — pooled -0.0261, single-name-only -0.0280,
  ETF-only -0.0239; 0/231, 0/128, 0/103 qualify BY-FDR positive at any split. A screen,
  not a falsification (per 0c's own convention — shortlists, doesn't verdict), but a
  clean negative closes this thread: the one genuinely untried construction paradigm
  flagged before the gate fired has now been tried and doesn't clear even the screening
  bar. Does not itself get a ledger row (no construction was ever pre-registered off it
  — nothing to verdict), recorded here so the gap doesn't get re-flagged as untested.
  **Corrected 2026-09-24: this screen did not test time-series momentum, and TSMOM is still
  untested.** At 1d, `ctf_momentum` is a same-timeframe 14-period Wilder RSI scaled to
  [-1, +1] (`feature_factory.py`'s `ctf_higher_tf_map` comment, todo 189;
  `services/backfill_feature_factory.py::_build_ctf_series`), and 1d `return_mid` is 2
  sessions (`alpha.ic.lookahead.1d.mid`, per-tf keys since todo 146), not the H=5 the script's
  docstring states. So the screen measured a two-week oscillator against a two-day forward
  return, which is short-term reversal territory. Classic TSMOM (Moskowitz, Ooi and Pedersen
  2012: 12-month lookback, monthly holding, volatility-scaled positions) was never run. The
  consistent negative IC is itself a short-term reversal hint (same sign in every split), seen
  in-sample, so any reversal pre-registration must disclose it and exclude this screen's
  symbols and window from its evidence. Both are queued in phase 181
  (`docs/plans/2026-09-24-edge-proof-program.md`, "Phase 181 queue").
- **`range_pct_fast_xs_ls_h5` beta-by-universe-composition diagnostic — led to a real
  pre-registered successor test, now CLOSED DEAD, 2026-09-13.** The diagnostic itself
  (single-name-only β=0.91/R²=0.44 vs. pooled β=1.14/R²=0.75, neutralized intercept
  10.17bp vs. 4.87bp) was real but explicitly preliminary/non-load-bearing. Followed up
  same day with a full pre-registration (Pre-registration 3) and AGY review — see the
  `range_pct_fast_xs_ls_h5_single_name_only` row above for the verdict. Superseded; kept
  here only as the provenance trail from diagnostic → pre-registration → verdict.
- **Personal-cost-hurdle tautology check — RESOLVED, hurdle confirmed non-tautological,
  2026-09-13.** Same review questioned whether 0c's 218/218 (100%) hurdle-clear rate
  meant the hurdle was a rubber stamp rather than doing real discriminating work. Checked
  live: across the full population of 554 BH-FDR-passing pooled 1d cells in
  `feature_ic_scores` (not just the curated 218-cell shortlist), the minimum |IC| is
  0.0228 — roughly 5-7x above the hurdle's worst-case floor (~0.003-0.004). Nothing in
  this corpus's FDR-passing population sits anywhere near the hurdle boundary, so the
  100% pass rate is a real gap between statistical detectability and the personal cost
  floor, not a tautology artifact of feeding a pre-filtered population into an
  always-true test. Closes this objection; don't re-raise it.
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
