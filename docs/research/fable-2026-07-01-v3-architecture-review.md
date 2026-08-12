# v3 Architecture Review — Regimes, HMM Granularity, Ensemble Combination, Cross-Asset Gap

**Date:** 2026-07-01 · **Author:** Fable 5 (dispatched via Claude Code Agent tool) · **Type:** research/recommendations, read-only · **Scope:** feature_vectors → regime labeling → ic_engine → ensemble_trainer → alpha_events

---

## 1. Executive Summary

- **The cross-asset regime gap is live today, not a future landmine.** 15 of 58 corpus symbols (TLT, AGG, IEF, SHY, BIL, LQD, HYG, EMB, MUB, TIP, PFF, GLD, SLV, VNQ, IBIT) are deliberately *excluded* from the equity breadth universe by `equity_regime_model.py`'s own tag filter — yet `ic_engine.py` stratifies their IC and `ensemble_trainer.py` scores their alpha under the SPY-vol × equity-breadth label. The system already "knows" they aren't equity; it just doesn't act on it downstream. Verified by direct DB query.
- **Phase 151 (`regime_group`, migration 189) is the fix vehicle and is execution-ready** (`docs/plans/archive/2026-07-01-cross-sectional-regime-model.md`, 0/9 tasks started). It cleanly fixes the 11 `fi_*` symbols via the rates group. Two residual gaps found (§4): GLD/SLV/VNQ/IBIT still silently default to equity post-151, and `AmbiguousRegimeGroupError` will hard-block enabling commodity groups while OIH/XLE/XOP carry dual `eq_*` + `commodity_*` tags.
- **"New regime categories" is already designed** — `docs/plans/2026-07-01-regime-stratification-alternatives.md` enumerates eight candidate stratification dimensions (volatility, dispersion, factor, three HMM variants, microstructure, volume, session, skew/tail) with an implementation order and an orthogonality gate. Its stated prerequisite (Numba JIT, todo 026's JIT item) has shipped (Phase 141 P2; `regime_writer.py:58`). The real unbudgeted cost is ic_engine multi-axis stratification (a `feature_ic_scores` schema change) which no plan doc covers yet (§3).
- **Ensemble combination is the genuinely open topic.** Current method is capped IC-proportional weighting on `quality_weight = ic_ci_lower × max(floor, ic_sharpe_hac)`. The Ledoit-Wolf covariance is computed but **never inverted** — it's only used as a binary clustering heuristic. Recommended path: (i) todo 029's IC shrinkage first, (ii) a Grinold-Kahn `Σ⁻¹·IC` weight variant A/B'd via Phase 142A's ensemble-IC machinery, (iii) hierarchical partial pooling for sparse regime strata (§2).
- **"HMM (security and model_group)" conflates two complementary axes**: `regime_group` (peer set for computing a cross-sectional signal) and per-symbol HMM (`feature_vectors.regime`). The literal "pooled HMM fit" idea exists as the factor-augmented HMM variant and is correctly gated on empirical proof of per-symbol HMM deficiency (todo 026's Decision Gate) (§5).
- **Sequencing:** batch all label-invalidating regime changes (Phase 151 + todo 026 P1-P3) into one ic_engine re-run after the current Phase B rebuild; ensemble weighting experiments are cheap (no corpus re-run) and slot in after 142A provides the measuring stick.
- Minor APR violation found: `ensemble_trainer.py:509` hardcodes the 90-day stale-weight cliff inline (`if days_since > 90:`) while its sibling `weight_half_life_days` is APR-backed. Needs `alpha.ensemble.weight_stale_max_days` — capture as todo.

---

## 2. Ensemble — Better Ways to Combine IC Results (open research topic)

### Current state (verified)

- **Eligibility:** cross-sectional rows only (`symbol='POOLED'`, `ic_ci_lower > 0`, `passes_fdr`, `reliable`, `feature_status_at_eval='active'`) — `ensemble_trainer.py:396-409`; meta-FDR gate requires BH-FDR pass in ≥50% of cells (`:294-307`, APR `alpha.ensemble.meta_fdr_min_fraction`).
- **Raw weight:** `quality_weight = ic_ci_lower × max(sharpe_floor, ic_sharpe_hac)` — `src/intelligence/ensemble/feature_selector.py:28-34`.
- **Normalization:** proportional-to-weight with a 0.20 per-feature cap and iterative excess redistribution — `weights.py:23-76`.
- **Decorrelation:** LW shrinkage covariance (`covariance.py:25`) → correlation matrix → union-find clusters at corr > 0.80 → cluster weight capped at 0.40 — `ensemble_trainer.py:518-529`. **The Σ estimate is used only for clustering; it is never inverted.**
- **Staleness:** exponential decay of weights (half-life 30d APR); hard equal-weight fallback beyond 90d (hardcoded, `:509`).
- **Score:** `alpha = X @ (weights × ic_sign)`, per (tf, regime) stratum, universe-level weights.

This is a defensible v1: transparent, capped, sign-safe. Its two structural weaknesses: (a) it ignores the covariance information it already computes (two 0.79-correlated features that escape the 0.80 cluster cutoff both get full weight), and (b) raw per-cell IC estimates carry winner's-curse selection bias (already diagnosed in todo 029 as its top item).

### Options (all validatable with existing bootstrap/BH-FDR gates)

**E1 — Shrunk-IC inputs (James-Stein / empirical Bayes).** Already designed as todo 029 item 0b (`ic_shrunk` + `shrinkage_weight` columns). Precedent: James-Stein (1961); Harvey & Liu haircut Sharpe. Change `_process_stratum` to consume `ic_shrunk` instead of raw `ic_sharpe_hac`. **Do this first** — it corrects decisions being made today and every other variant should be compared on de-noised inputs. Effort: rides on 029; ensemble side is a one-line query change + APR toggle.

**E2 — Mean-variance combination (Grinold-Kahn / Qian-Hua-Sorensen).** `w ∝ Σ⁻¹ · IC` where Σ is the already-computed LW-shrunk feature covariance. This is the textbook optimal combination of correlated signals (Grinold & Kahn, *Active Portfolio Management*; Qian et al., *Quantitative Equity Portfolio Management* ch. 5) and replaces the binary cluster-deflation heuristic with continuous decorrelation. LW shrinkage already regularizes the inverse; keep the per-feature cap and ic_sign logic unchanged. Implementation cost is small (everything needed is in scope inside `_process_stratum`). Risks: ill-conditioning on near-duplicate features (gate on condition number, APR `alpha.ensemble.mv_condition_max`); weight instability across reruns (measure weight turnover as a diagnostic).

**E3 — Hierarchical regime shrinkage (partial pooling).** Per-(tf, regime) IC estimates shrink toward the pooled (`is_pooled=true`) estimate with strength inversely proportional to cell N (empirical-Bayes τ). Directly addresses the documented sparsity problem (per-symbol per-regime 5m cells ~1.5K bars, `ensemble_trainer.py:9-13` docstring) and will matter more post-151 when strata multiply (6 rates labels + 9 equity labels). Precedent: Gelman-style partial pooling. **Note:** this repurposes pooled rows from "diagnostic only" (STATE.md key decision) to a shrinkage prior — needs an explicit user decision (§7 Q2).

**E4 — Per-feature decay half-lives.** Replace the single global `weight_half_life_days=30` with per-feature half-lives from todo 029's IC decay-curve profiles (`feature_decay_profiles`). Additive, low risk; sequence after 029's decay-curve item ships.

**Rejected: ML stacking / boosting over features.** Non-transparent weights can't be validated by the existing CI/FDR gates on inputs, and it violates the freeze-method-automate-cadence rule. The linear IC-weighted frame is the right complexity level until 142A proves the ensemble output has IC at all.

### Recommendation

Sequence E1 → E2 → E3 → E4. Every variant is a new `weight_version` (already in `ensemble_weights` PK — zero schema change for A/B) judged by **Phase 142A's EnsembleICEngine on OOS data**: the variant whose `alpha_score` shows higher `ic_ci_lower` with stable walk-forward folds wins. Ensemble re-runs are minutes, not a corpus rebuild — this is the cheapest experimentation surface in the whole pipeline. APR: `alpha.ensemble.weight_method` (`ic_proportional` | `mean_variance`), `alpha.ensemble.ic_input` (`raw` | `shrunk`), `alpha.ensemble.regime_shrinkage_tau`. Migration needed only for 029's `ic_shrunk` columns (covered by 029's own plan).

---

## 3. Regime Stratification Expansion (eight candidate dimensions) — readiness verification

`docs/plans/2026-07-01-regime-stratification-alternatives.md` already answers "add 5 or so new regime categories." Verified against code state:

- **JIT gate: satisfied.** Doc requires todo 026's Numba JIT item before multi-dimensional IC; shipped in Phase 141 P2 (`src/intelligence/hmm_jit.py`, wired at `regime_writer.py:490`).
- **Sequencing bindings hold:** session regime downgraded per the 2026-07-01 backlog matrix; percentile-rank-first rule; storage split decided (per-symbol dimensions — volatility, volume, session, skew/tail — → `feature_vectors` columns; cross-sectional dimensions — dispersion, factor — → `market_regimes` rows under `regime_group` — so **dispersion and factor regimes are gated on Phase 151's migration 189**).
- **Stale reference:** the doc's footer cites `Todo: 030-regime-stratification-alternatives.md`, which doesn't exist (pending 030 is cost-hurdle calibration). Cosmetic; fix when next edited.
- **Concept note:** storing dispersion regime as a `market_regimes` row under `regime_group='dispersion'` overloads regime_group (a *dimension*, not a *peer group*). Name it deliberately in the glossary when it ships, or Phase 151's `AmbiguousRegimeGroupError` semantics get confusing.

**The real gap: ic_engine multi-axis stratification has no plan.** Volatility regime's implementation section says "IC engine reads `volatility_regime` as a secondary stratification axis" in one line, but that is a `feature_ic_scores` schema change (new stratification column(s) in the conflict key), an ensemble-reader change (which axis/combination do weights key on?), and a multiplicative compute/N-budget cost the doc itself quantifies (~750K cells for HMM×vol). Before volatility regime is sequenced, decide: **substitution test first** (run ic_engine once stratified by `volatility_regime` *instead of* the cross-sectional label, compare IC separation per todo 026's baseline-separation query) vs. building the multi-axis join. The substitution test needs zero schema change and directly measures whether the new axis earns its cells — recommend it as volatility regime's gate, consistent with the doc's own orthogonality-gate philosophy.

**Verdict:** ready to sequence as-is *after* Phase B and Phase 151, with one added deliverable: a short plan for the ic_engine stratification-axis mechanics (schema + APR `alpha.regime_stratification.max_correlation` seeding) before volatility regime ships.

---

## 4. Cross-Asset Regime Gap — Phase 151 readiness + residual gaps

### Confirmed current-state facts (DB-verified 2026-07-01)

1. `equity_regime_model.py:269-289` builds the breadth universe as symbols with any `eq_*`/`intl_*` tag: **43/58 corpus symbols**. The docstring (`:262-267`) *deliberately* excludes `fi_*`, commodity metals, real estate, preferred, crypto — TLT, GLD, SLV, HYG, AGG, IEF, SHY, BIL, LQD, EMB, MUB, TIP, PFF, VNQ, IBIT (15 symbols) are out.
2. Yet `ic_engine.py:2057-2065` loads one `mr_dict` (`asset_class='equity'`) and `:771-778` applies it to **every** symbol's regime-stratified IC; `ensemble_trainer.py:469-480` joins `mr.asset_class = 'equity'` for all symbols' alpha scoring. So ~26% of the corpus — including a bitcoin ETF — has its IC conditioned on, and its alpha scored within, the equity market's state. A 2022-style rates selloff under calm equity vol labels TLT `low_bull` while it crashes. The cross-sectional POOLED IC pass also ranks bonds/gold/bitcoin against equities inside equity-regime strata.
3. Breadth-side contamination (OIH, XLE, XOP, AMLP, GDX included via `eq_sector`/`eq_sub_sector` tags despite `commodity_*`/`oil_price` tags) is **real but second-order**: these are equity funds holding stocks, and standard breadth measures include energy/miner sectors. AMLP (MLPs, `rate_sensitive` + `oil_price`) is the only genuinely marginal member. `instrument_tags.weight` is **vestigial in this path** — the breadth SQL uses `EXISTS` only, and the backlog matrix independently confirms nothing consumes calibrated weight today.

### Phase 151 assessment

The plan (`2026-07-01-cross-sectional-regime-model.md`) is execution-ready and correct in architecture: pluggable signal modules, APR-defined groups, `market_regimes.asset_class → regime_group`, ic_engine routing via `_build_symbol_regime_class` with fail-loud `AmbiguousRegimeGroupError`, corpus-pipeline step added (closing the latent gap that `equity_regime_model.py` isn't in `ops_corpus_pipeline_run.sh` today). Shipping it with the rates group enabled immediately fixes **11 of the 15** mislabeled symbols (all `fi_*`: TLT, AGG, IEF, SHY, BIL, LQD, HYG, EMB, MUB, TIP, PFF).

**Residual gap A — silent default-to-equity.** The plan's routing test explicitly asserts `GLD → "equity"` and `crypto → "equity"` (plan `:1618-1622`) because commodity/fx groups ship disabled. Post-151, **GLD, SLV, VNQ, IBIT remain silently equity-labeled** — the exact "silent wrong answer" the design mindset forbids, now encoded as a passing test. Recommend changing the unmatched-symbol policy to *exclude* (no `mr_dict` entry → bar drops out of regime-stratified IC, exactly the existing behavior at `ic_engine.py:770` for missing timestamps; pooled IC still covers them) with a loud startup log of unrouted symbols. That is a ~5-line delta to the plan, decidable before execution (§7 Q1).

**Residual gap B — dual-tag hybrids hard-block commodity enablement.** OIH/XLE/XOP carry both `eq_*` and `commodity_energy_*` tags. Today (equity+rates enabled) they route to equity — fine. The moment `commodity_energy` is enabled, `_build_symbol_regime_class` raises `AmbiguousRegimeGroupError` and ic_engine crashes at startup. Fail-loud is correct, but it means enabling commodity groups is blocked on resolving the tag taxonomy (todo 041's exposure-vs-sensitivity category audit is precisely the fix layer: `eq_sub_sector` is a *wrapper/exposure* fact, `commodity_energy_crude` is a *sensitivity* fact — routing should filter on exposure-category tags only). The plan's scope note (`:18-33`) defers multi-sensitivity for job-2 fidelity but doesn't flag this job-2 *availability* blocker. Capture as a note on Phase 151 + a dependency edge from "enable commodity groups" to todo 041/040.

**Job-1 peer-set purity (per coordinator question):** yes, OIH/XLE stay in the equity breadth peer set post-151 — and that is defensible by convention (they are equity sector funds; the % -above-200MA convention includes them). Not worth new mechanism now. If tag calibration (Phase 148) later shows their equity beta is low, weighted breadth contribution via `instrument_tags.weight` is the natural existing hook — no new schema needed. Todo-level note, not phase scope.

**Recompute cost:** migration 189 + label rebuild touches only `market_regimes` (cheap) but changes the regime stratification key → full ic_engine + ensemble + publisher re-run required. `feature_vectors`, `forward_returns`, HMM labels untouched. HMM_RANDOM_STATE unaffected.

---

## 5. HMM: "security vs model_group" — clarification (short)

Two different axes, not substitutes:

- **`regime_group`** = which *peer set* computes a shared cross-sectional regime signal (Phase 151). It never changes how the per-symbol HMM is fit.
- **Per-symbol HMM** (`regime_writer.py:12`: one independent GaussianHMM per (symbol, tf), 5D obs vector `[log_return, realized_vol, momentum, vol_of_vol, rel_volume]` at `:142-152`, K=5 BIC-selected) = the symbol's own trend state.

The literal "fit at group level instead of per security" idea is the **factor-augmented HMM variant** in the stratification doc, and the bias/variance tradeoff is real: pooling buys statistical power (a K=5 full-cov 5D HMM has ~124 free params; a 1d series has only ~5K bars) at the cost of assuming shared regime dynamics. Evidence mildly favors feasibility (BIC chose K=5 unanimously across SPY/TLT/GLD/EWT; obs are per-series StandardScaler-normalized, so pooling scaled obs is coherent) — but the doc's gate is correct: **no HMM variant until todo 026's Decision Gate baseline-separation query proves the current per-symbol labels are deficient** (regime-IC gap < 0.01 escalates; > 0.05 means labels are fine). Run that query when the current rebuild's `feature_ic_scores` lands; don't redesign ahead of the evidence.

---

## 6. Roadmap Integration

| Recommendation | Vehicle | Sequencing |
|---|---|---|
| E1 shrunk-IC inputs | todo 029 (near-term 0b, already scoped) + 1-line ensemble consumer change | After current Phase B rebuild; before any weight-method A/B |
| E2 mean-variance weights, E3 partial pooling, E4 per-feature decay | **New small phase: "Ensemble Weighting Methodology"** (2 waves: E2 A/B; E3+E4) | Gated on Phase 142A complete — 142A's `alpha_ensemble_ic` is the judge. Don't fold into 142A (it's planned/reviewed; keep measurement separate from method change) |
| APR fix: 90-day stale cliff (`ensemble_trainer.py:509`) | New todo (migrate-as-you-go) | Batch into the ensemble phase's first commit |
| Phase 151 execution + Gap A policy change + Gap B dependency note | Phase 151 (exists) | **Elevate**: schedule immediately after Phase B rebuild + todo 026's ungated items, batched into a single ic_engine re-run. Decide §7 Q5 (before/after 142A baseline) first |
| Commodity/fx group enablement | Blocked on todo 041 (tag category audit) → todo 040/Phase 148 (calibrator); Phase 152 universe expansion stays last per operator decision | Post-151, evidence-gated |
| Volatility regime (+ substitution-test gate), dispersion regime | New phase after 151 (dispersion regime's storage depends on `regime_group`); requires a short ic_engine multi-axis plan first (missing today) | After 151 re-run; run volatility-regime substitution test on that corpus |
| Factor-augmented HMM (pooled/factor HMM) | Stays gated (todo 026's Decision Gate) | Run baseline-separation query when current rebuild's IC lands |
| Regime-model integrity monitor | todo 036 (already scoped, gated on Phase 149A) | Unchanged |

**Master sequence:** Phase B rebuild finishes → 026 Step-1 baseline query → 142A (ensemble IC baseline) → Phase 151 + todo 026's ungated items (one ic_engine re-run) → Ensemble Weighting phase (shrunk-IC pre-work can overlap) → volatility/dispersion regime stratification phase.

---

## 7. Open Questions for the User

1. **Unrouted symbols post-151** (GLD, SLV, VNQ, IBIT): (a) keep plan's silent default-to-equity, (b) exclude from regime-stratified IC with loud logging *(recommended)*, or (c) enable `commodity_metals` now with GLD/SLV/GDX?
2. **Partial pooling (E3)** requires using pooled IC rows as a shrinkage prior — OK to amend the "pooled IC is diagnostic only" load-bearing decision?
3. **Ensemble methodology work**: new standalone phase after 142A *(recommended)*, or a third wave appended to 142A?
4. **Phase 151 timing vs 142A baseline**: land 151 *before* 142A's first ensemble-IC baseline (cleaner strata from day 1, but no pre/post comparison) or *after* (recommended: baseline first, then one batched re-run)?
5. **Volatility regime rollout**: substitution test only (no schema change) as the gate *(recommended)*, or commit to multi-axis `feature_ic_scores` schema up front?
6. **AMLP in equity breadth**: leave (convention) *(recommended)* or drop via tag edit now?
