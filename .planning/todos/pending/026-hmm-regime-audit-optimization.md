---
**Created:** 2026-06-28
**Updated:** 2026-06-29
**Area:** intelligence
**Type:** optimization
**Priority:** P0-P3 actionable; P4a/P4b gated (see below)
**Effort:** 3-5 days (P0-P3) + 8-12h compute (P4, if validated)
**Risk:** low
**Gate:** P0-P3 have no gate; P4a/P4b require empirical IC proof first
---

# 026 — HMM Regime Audit & Optimization

**Plan:** `docs/plans/2026-06-28-hmm-regime-audit-optimization.md`

Consolidates and supersedes:
- 007-numba-jit-hmm-inference.md
- 023-hmm-parameter-lookahead-bias.md
- 999-hmm-parameter-lookahead-validation.md

## Findings

10 gaps across per-symbol HMM (`regime_writer.py`) and cross-sectional model (`equity_regime_model.py`):

| Priority | Finding | File | Status (verified 2026-07-04) |
|---|---|---|---|
| P0 | Numba JIT forward-filter — 20+ hr → ~30 min | `regime_writer.py:234`, new `hmm_jit.py` | **DONE** — `alpha_pass_jit` imported and live in hot path (commits `269ad5f3`, `c4ab422f`) |
| P1a | Expanding rank for cross-sectional VIX proxy (look-ahead bug) | `equity_regime_model.py:175` | **DONE** — bisect-based causal expanding rank shipped (commit `7c759bdb`) |
| P1b | TF-normalized windows for VIX z-score and 200MA | `equity_regime_model.py:75-76` | **NOT DONE** — `vix_z_window`/`ma_window_days` are single global APR values, no per-TF variant found |
| P2a | Multiple HMM restarts, pick max log-likelihood | `regime_writer.py:377` | **NOT DONE** — what exists instead is narrower: on EM non-convergence, one retry, same seed, doubled iterations (`regime_writer.py:428-462`), not multi-seed-restart-and-keep-best. Same gap the P4a section below already flags re: no seed-stability check |
| P2b | Degenerate model detection (occupation fraction gate) | `regime_writer.py:439` | **NOT DONE** — zero references anywhere in codebase |
| P2c | Regime churn feature (`hmm_churn` column) | `regime_writer.py` + migration | **NOT DONE** — zero references anywhere in codebase |
| P3 | Empirical threshold calibration for vix/breadth cuts | `equity_regime_model.py` APR | **PARTIAL** — thresholds moved into APR (migration 182: `alpha.regime.vix_low_pct`/`vix_high_pct`/`breadth_bear`/`breadth_bull`), made tunable, but still sitting at original guessed defaults (0.33/0.67/0.40/0.60) — no empirical recalibration has actually happened |
| P4a | Rolling HMM refit (parameter look-ahead bias) | `regime_writer.py` — **GATED** | Decision gate not yet cleared (see below) — correctly not started. A pilot scaffold existed briefly (commit `45621857`) but was deleted 2026-06-29 before writing to production |
| P4b | Expanding StandardScaler | `regime_writer.py:375` — **GATED on P4a** | Not started (gated) |

See plan doc for full implementation notes and APR keys.

---

## P4a/P4b — Rolling Refit & Expanding Scaler (GATED)

**Merged with todo 034 (2026-07-01):** an independent audit found the same root cause (full-history HMM fit → non-causal parameters feeding an otherwise-causal decode) and initially proposed treating it as an unconditional P0 blocker. Corrected to route through this todo's decision gate instead — see todo 034 for the corrected framing. One genuinely new item from that audit, folded in here: **no seed-stability check exists** on HMM fits (`regime_writer.py:822`, fixed seed via APR `alpha.hmm.random_state`) — the retry-on-non-convergence path reuses the same seed rather than testing whether regime labels/log-likelihood are stable across different random inits. Add a cheap seed-stability check (fit with 3-5 seeds, compare log-likelihood spread and label agreement) as part of whatever P4a work eventually happens, same file, same validation harness.

**Status:** DEFERRED — no empirical evidence that current labels are broken.

**Background:** HMM is fit on full history (2014-2024), causally decoded via forward-filter. Forward-filter is causal (no future information in the decode step), but emission parameters and transition matrix are learned from the full window including future data. The question is whether this materially harms IC predictive power.

**2026-06-29 finding:** A rolling refit pilot was built and then killed before writing to production. When we went to measure whether improvement was needed, `feature_ic_scores` was empty (truncate script had cleared it). No baseline = no proof of a problem.

**Renaissance mandate:** Do not optimize what should be deleted. Measure first.

### Decision Gate — ALL must be true before any P4 work

1. `feature_ic_scores` is populated (IC engine has run)
2. Current regime labels show poor IC separation — e.g. trending_up IC ≈ trending_down IC (gap < 0.01)
3. Root cause analysis confirms parameter look-ahead bias is the driver (not regime irrelevance)
4. Rolling refit pilot shows ≥10% IC improvement (shadow mode, p < 0.05)

**If any gate fails → drop P4a and P4b entirely.**

### How to validate (when IC data exists)

**Blocking fact (found 2026-07-01, RESOLVED 2026-07-02):** the note below claimed the Step 1
query couldn't run because zero rows carried per-symbol HMM labels. That's now stale — the
current corpus (ic_engine run completed 2026-07-01 23:41:44) does carry all 5 per-symbol HMM
labels alongside the 9 cross-sectional ones in the same `feature_ic_scores.regime` column,
same run, same timestamp. Whatever caused the original gap (likely an `equity_model_enabled`
toggle state at an earlier run) is no longer blocking. Step 1 is runnable and was run — see
below. Original two workarounds ((a) scoped run with `equity_model_enabled=false`, (b) direct
diagnostic join) are no longer needed.

**Step 1 — RUN 2026-07-02. Result: pooled query is misleading — methodology flaw found, fix
before reusing this query.**

Pooled SPY+TLT result: `trending_up` mean_ic=0.0147, `trending_down` mean_ic=0.0063, gap=0.0084
(< 0.01 → naively triggers Step 2). **But this pooled number is an artifact.** Broken out per
symbol:

| Symbol | trending_up IC | trending_down IC | Gap | Reading |
|---|---|---|---|---|
| SPY | 0.0256 | 0.0020 | **+0.024** | Ambiguous zone (between 0.01 and 0.05) — not clearly deficient |
| TLT | 0.0064 | 0.0097 | **−0.003** | Deficient, and *inverted sign* — HMM trend labels carry no separation for TLT at all |

**The query as originally written pools dissimilar symbols (SPY=equity, TLT=bonds) and averages
away a real, asset-class-dependent effect.** SPY's per-symbol HMM labels work reasonably; TLT's
don't separate IC at all. This is a materially different finding than "labels are borderline
deficient in general" — it's "label quality is asset-class-dependent." **Fix the query before
reusing it: run per-symbol, never pre-pooled across symbols with potentially different regime
dynamics, and widen past SPY+TLT to at least one member of every `regime_group` (once Phase 151
ships) before generalizing.**

**Root-cause implication:** TLT's failure mode doesn't obviously look like parameter
look-ahead bias (rolling refit's target). A single generic 5-state trend HMM may simply not fit
bond regime dynamics — rates markets grind and mean-revert around curve shape more than they
trend the way equities do. That points at the factor-augmented HMM / `regime_group`-conditional
direction (`docs/plans/archive/2026-07-01-regime-stratification-alternatives.md`, HMM Variants
section — archived 2026-07-02, decision-relevant content consolidated into
`docs/ideas/intel-12-stratification-dimension.md`; this citation is for the implementation-level
formula detail specifically kept in the archived copy, not decision framing)
as a competing explanation to rolling refit, not a confirming one. Don't assume rolling refit is
the universal fix before Step 2 distinguishes these two hypotheses per-symbol.

**Step 2 — Root cause analysis (1 hour). Partially run 2026-07-02, on SPY only (TLT excluded
from this specific comparison — its cross-sectional label is itself contaminated, see
`docs/plans/2026-07-01-cross-sectional-regime-model.md` and the 2026-07-01 architecture review
§4 — comparing TLT's per-symbol HMM against a cross-sectional label that was never computed
with TLT's own regime in mind is not a fair test):**
Compare IC separation across: (a) current labels (full-history fit) — done, see Step 1 table;
(b) time-truncated labels (fit 2019-2022 only, decode 2023) — **not done, requires an actual
truncated-window HMM fit, real work, still open**; (c) cross-sectional regimes (`market_regimes`
table) — done for SPY only: cross-sectional range (0.0457) vs per-symbol HMM range (0.0327) on
the same SPY/5m/1h slice, a 1.4x wider separation for cross-sectional, not the 2.2x an earlier
same-day pooled-and-TLT-contaminated comparison suggested. Directionally consistent with (but
not proof of) parameter bias mattering for SPY specifically; TLT needs its own clean
same-symbol-only comparison once Phase 151 gives it a valid cross-sectional group (`rates`) to
compare against — comparing TLT's HMM to the *equity* cross-sectional label would repeat the
same contamination error found above.

**Step 3 — Rolling refit pilot (shadow mode):**
- Scope: SPY + TLT, 5m + 1h only
- Method: 3-year rolling window, annual step
- Write to `feature_vectors.regime_rolling` (migration 184 already applied — column exists)
- Compare IC scores `regime` vs `regime_rolling`
- Success: ≥10% IC improvement, p < 0.05, label disagreement ≥20%

**Step 4 — Full corpus rollout (ONLY if pilot succeeds):**
- 58 symbols × 4 TFs = ~3,480 HMM fits; 8-12h compute
- APR keys: `alpha.hmm.rolling_window_bars`, `alpha.hmm.rolling_step_bars`
- Shadow mode toggle in `regime_writer.py`; monitor 3 months before promoting to production

### Infrastructure already done
- Migration 184: `feature_vectors.regime_rolling` column exists
- `docs/experiments/2024-06-29-hmm-rolling-refit-pilot.md` — experiment doc
- Pilot code was deleted (2026-06-29) — rebuild from scratch if gates pass

---

**Resolved 2026-07-07 (fallback decision):** the operator decision the v3.15 build trigger
required is made - option (b) pre-committed (demote per-symbol HMM to shadow per weak
regime_group; cross-sectional + volatility_pct stratification), (c) factor-augmented variant
pre-registered as the rates challenger with a defined build trigger. See
`.planning/research/fable-2026-07-07-phase144-conditioning-decision.md` for reasoning and
falsifiers. Caveat carried forward from that doc: the Step 1/Step 2 magnitudes above are stale
(synthetic-bar filter fix `26efb75b`, 142.5's 91 new primitives, full-depth backfill) - the
widened per-regime_group Step 1 must re-run on the fresh corpus before any demotion executes.
