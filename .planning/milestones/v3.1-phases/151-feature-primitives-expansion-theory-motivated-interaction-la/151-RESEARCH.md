# Phase 151: Feature Primitives Expansion + Theory-Motivated Interaction Layer - Research

**Researched:** 2026-07-24
**Domain:** Quant feature engineering — Feature Factory primitive addition, IC screening (BH-FDR), Feature Registry governance, regime-conditioned collinearity clustering
**Confidence:** HIGH (mechanics/code paths — all directly grepped from live source) / MEDIUM (exact statistical treatment for sparse event flags and Wave 2's still-undesigned ~45 interaction candidates)

## Summary

Phase 151 is NOT a greenfield feature-engineering phase — it is an extension of a fully live, already-proven pipeline (Feature Factory -> `feature_vectors` -> `ic_engine.py` -> `feature_registry`) that has done this exact job three times already: migration 169 (Phase 140.5, 61 baseline features), migration ~197-216 (Phase 142.5, 91 Renaissance primitives), and migration 255 (Phase 163, 17 VP/SR structural primitives, executed 2026-07-24, same day as this research). Migration 255 is the closest, most current analog and should be the direct template for Wave 1's and Wave 2's migrations. The candidate roster itself (28 tier-0 atomics, 5 tier-1 interactions already named, ~45 more tier-1 interactions to be designed in Wave 2) is fully specified in ROADMAP.md and its four source todos (104/123/180/066) — all four have already been through an independent Fable design review. There is no remaining design-review debt on the WHAT; this research is entirely about the HOW (exact code paths, migration numbering, config wiring, and screening mechanics).

Three load-bearing facts drive the plan structure. First, `feature_registry` enforces a hard startup alignment gate (`_REGISTRY_ROW_COUNT = len(dataclasses.fields(FeatureVector))`, `feature_registry_service.py:44`) — every new column requires touching `schemas.py` (dataclass field), `feature_factory.py` (compute logic + `FEATURE_VECTOR_DOMAIN` entry + `_cold_start_vector` fallback), a migration (`ALTER TABLE feature_vectors ADD COLUMN` + `INSERT INTO feature_registry`), and (for tunable params) `config_schema`/`config_state`/`config_history` rows — all four in the same PR, or `ic_engine.py`'s registry-drift assertion at line ~4194 hard-crashes on startup. Second, IC screening already has two BH-FDR pools live: the corpus-wide atomic pool (`alpha.ic.fdr_alpha`, ~516K hypotheses, `ic_engine.py`) and a dedicated small-N interaction-primitive partial-IC pool (`alpha.ic.partial_fdr_alpha`, migration 206, todo 037, currently 8 features) — Wave 1 plugs directly into the first, Wave 3 should almost certainly extend the second rather than mint a third. Third, the ROADMAP's own Theory-Motivated Interaction Layer registration spec (`parent_features=[]`) contradicts the live schema and the existing 8-row precedent (every live `tier=1_interaction` row has exactly 2 non-empty `parent_features`, required by the partial-IC methodology) — flagged below as a correction the planner must apply, not follow verbatim.

**Primary recommendation:** Wave 1 and Wave 2 should each be a single migration following migration 255's exact template (schema comment block documenting numbering/type/note conventions, `ADD COLUMN IF NOT EXISTS`, `INSERT ... ON CONFLICT (feature_name) DO NOTHING` for feature_registry, `config_schema`/`config_state`/`config_history` triplets for every new APR key) plus corresponding `schemas.py`/`feature_factory.py`/`feature_cache.py` edits mirroring the closest live sibling pattern per feature family (see Code Examples). Do not use the `add-plugin`/`plugin-reference`/`wire-pipeline` skills — they document the archived v2.x I1-I7 plugin system with no live consumer; the correct pattern is direct Feature Factory + migration edits as demonstrated by Phases 140.5/142.5/163.

## User Constraints

No CONTEXT.md exists for this phase yet (`/gsd-discuss-phase 151` has not been run) — there are no locked decisions, discretion notes, or deferred ideas to copy verbatim. The closest thing to user constraints is ROADMAP.md's own detailed Phase 151 section, which this research treats as pre-existing scope (see Phase Requirements below) rather than CONTEXT.md-sourced constraints.

**Sequencing note (important, not this research's call to resolve):** `.planning/STATE.md` currently places Phase 151 in "Tier 6 — explicitly gated, do not start planning yet" behind Phase 148's Gate 2 FAIL / "prove edge before production infra" reasoning, and its `Current focus` section frames the real open question as whether the *existing* feature set + ensemble construction has any OOS-detectable edge at all before investing further in features. This research was dispatched anyway (explicit orchestrator request) and proceeds on its merits, but the planner and any downstream `/gsd-discuss-phase 151` should surface this sequencing tension to the user rather than silently overriding it.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Atomic primitive computation (28 new columns) | Compute (Feature Factory, `src/intelligence/feature_factory.py`) | — | Pure-function, stateless per DAG Invariant 2/3; `FeatureCache` holds only cross-bar/cross-asset state, never persists |
| Cross-asset macro spread computation (TIP/HYG/LQD, SPY/TLT beta) | Compute (`FeatureCache.update_cross_asset` extension) | Backfill/live bar-fetch (`services/backfill_feature_factory.py`, `services/feature_vector_pipeline.py`) | Needs multi-symbol OHLCV history feeding a stateful cache, same pattern as existing `vix_z`/`flight_quality`/`yield_slope_z` |
| Persistence of computed feature values | Persistence (`FeatureVectorWriter`) | — | DAG Invariant 3 — compute daemon never writes its own output |
| Feature governance / lifecycle (tier, status, parent_features) | Persistence + Config (`feature_registry` table via migrations) | Service (`feature_registry_service.py` alignment gate) | Single source of truth for tier/status; enforced at every `ic_engine`/`ensemble_trainer` startup |
| IC screening (Wave 1 atomic sweep, Wave 3 interaction sweep) | Batch/Measurement (`services/ic_engine.py`, `scripts/ops/alpha/ops_interaction_primitives_pilot.py`) | Config (APR: `alpha.ic.fdr_alpha`, `alpha.ic.partial_fdr_alpha`) | Corpus-wide BH-FDR is a `ProcessPoolExecutor`-parallel batch job, never inline in compute |
| APR key registration (new tunables) | Config (migrations to `config_schema`/`config_state`/`config_history`) | — | Adding-a-parameter lifecycle per CLAUDE.md; loaded via `ConfigService.get_sync()` at `FeatureFactoryConfig` construction time |
| Regime-conditioned collinearity clustering (Wave 4) | Batch/Measurement (`ic_engine.py::_cluster_features`, extended) | Persistence (new cluster-membership table, if the planner chooses one) | Currently ephemeral per-cell clustering; Wave 4 needs to decide whether to persist by (cross_sectional_regime, symbol_hmm_regime) jointly — see Open Questions |

## Standard Stack

### Core

This phase adds no new third-party dependencies — every mechanism it needs (Spearman IC, BH-FDR via `statsmodels.multipletests`, hierarchical clustering via `scipy.cluster.hierarchy`, circular-block bootstrap) is already live in `services/ic_engine.py` and `src/intelligence/statistics/ic_math.py`. No `## Package Legitimacy Audit` section is required — this phase installs zero new packages.

| Component | Location | Purpose | Why Standard (already proven 3x) |
|---|---|---|---|
| `FeatureFactory` (pure functions) | `src/intelligence/feature_factory.py` | Compute all `FeatureVector` primitives, stateless, zero IO | DAG Invariant 2/3; every one of the 172 live fields goes through this exact contract |
| `FeatureCache` | `src/intelligence/feature_cache.py` | Cross-bar/cross-asset stateful accumulation (vix_z, yield_slope_z, weekly VWAP, session VP) | The only sanctioned place for state that spans bars; `update_cross_asset()` is the direct template for TIP/HYG/LQD |
| `feature_registry` + `feature_registry_service.py` | `production/migrations/169_feature_registry.sql`, `src/intelligence/feature_registry_service.py` | Governance catalog; tier/status/parent_features; alignment gate | Phase 143's evidence-based promotion/demotion system, live since 2026-07 |
| `ic_engine.py` | `services/ic_engine.py` (4,878 lines) | Per-(symbol,tf,regime,scale) Spearman IC + circular-block bootstrap CI + corpus-wide BH-FDR | Already handles exactly the sweep Wave 1/Wave 3 need — no new engine required |
| `ops_interaction_primitives_pilot.py` | `scripts/ops/alpha/ops_interaction_primitives_pilot.py` | Partial-Spearman-IC screening for `tier=1_interaction` features controlling for `parent_features` | Direct precedent for Wave 3; currently scoped to the 8 already-live interaction features, needs generalizing to the new ~50 |
| `partial_spearman_ic`, `apply_bh_fdr` | `src/intelligence/statistics/ic_math.py` | Partial correlation controlling for 2 parent atomics; Benjamini-Hochberg correction | Used by both the corpus-wide pool and the todo-037 interaction pool today |
| `ConfigService` / APR pattern | `src/config/` + `config_schema`/`config_state`/`config_history` tables | All new tunables (window lengths, thresholds) | CLAUDE.md APR mandate; migration 206/255 are the exact templates |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Direct Feature Factory + migration edits (recommended) | The `add-plugin`/`plugin-reference`/`wire-pipeline` skills' I1-I7 plugin registration pattern | **Do not use** — those skills document the ARCHIVED v2.x pipeline (`indicagent-intelligence-pipeline.service` is `failed`, `ExecStart` points at a deleted file per root CLAUDE.md and `src/intelligence/CLAUDE.md`'s own archived banner). Following that pattern would build a plugin nothing consumes. |
| Extending existing `alpha.ic.partial_fdr_alpha` pool for Wave 3 (recommended) | Minting a new dedicated APR key for the ~50-feature interaction pool | A new key is defensible if the planner/user wants Wave 3's population kept statistically distinct from todo 037's original 8-feature pilot cohort (different N materially changes BH-FDR's practical power). Flagged as an Open Question, not a closed decision. |
| `scipy.cluster.hierarchy` dendrogram clustering (already live, `_cluster_features`) | A different clustering algorithm (k-means, DBSCAN) for Wave 4's regime-conditioned clusters | No reason to switch — Wave 4 is explicitly an "extension," and using a different algorithm than Phase 140 P2 would break comparability between cross-sectional-regime and HMM-regime cluster structures. |

**Installation:** none — zero new packages this phase.

## Package Legitimacy Audit

Not applicable — this phase adds no new external dependencies (Python packages, npm packages, etc.). All required statistical/ML tooling (`scipy`, `statsmodels`, `numpy`) is already installed and in active use by `ic_engine.py`.

## Architecture Patterns

### System Architecture Diagram

```
                              WAVE 1: Atomic Primitives Expansion
   ┌─────────────────────────────────────────────────────────────────────┐
   │  market_data_ohlcv_tradeable (view)                                  │
   │       │  (SPY/TLT/SHY/TIP/HYG/LQD bars for macro; own-symbol bars    │
   │       │   for calendar/recency/beta/autocorr primitives)             │
   │       ▼                                                              │
   │  services/backfill_feature_factory.py  ─────┐                        │
   │  services/feature_vector_pipeline.py (live) ─┤                       │
   │       │                                      │                       │
   │       ▼                                      ▼                       │
   │  FeatureCache.update_cross_asset()   FeatureFactory.compute()        │
   │  (extended: tip/hyg/lqd bars,        (28 new pure-function           │
   │   equity_beta_z/rate_beta_z state)    primitives added)              │
   │       │                                      │                       │
   │       └──────────────► FeatureVector (172 → 200 fields) ─────────────┤
   │                                      │                                │
   │                                      ▼                                │
   │                           FeatureVectorWriter (sole writer)           │
   │                                      │                                │
   │                                      ▼                                │
   │                              feature_vectors (TimescaleDB)            │
   └─────────────────────────────────────────────────────────────────────┘
                                       │
                                       ▼
   ┌─────────────────────────────────────────────────────────────────────┐
   │  services/ic_engine.py — per (symbol,tf,regime,scale) Spearman IC +  │
   │  circular-block bootstrap CI, corpus-wide BH-FDR (alpha.ic.fdr_alpha)│
   │  New 28 atomic columns enter this sweep automatically once           │
   │  feature_registry.status='active' and dataclass field count matches │
   └─────────────────────────────────────────────────────────────────────┘
                                       │
                                       ▼
                        feature_ic_scores → feature_registry status
                     (promote / demote per alpha.feature_registry.*)

                    WAVE 2: Theory-Motivated Interaction Layer (design-time)
   ┌─────────────────────────────────────────────────────────────────────┐
   │  Analyst designs ≤50 compound features (product/ratio/conditional,   │
   │  each with a 1-sentence hypothesis) — 5 already named (ret_div_*,    │
   │  opex_flag, quad_witching_flag), ~45 new. Registered in              │
   │  feature_registry with tier='1_interaction', parent_features=        │
   │  [atomic1, atomic2] (NOT [] — see Common Pitfalls), hypothesis text  │
   │  in formula_short. Computed in FeatureFactory alongside their        │
   │  parents (same compute() call, no separate DAG stage).               │
   └─────────────────────────────────────────────────────────────────────┘
                                       │
                                       ▼
                    WAVE 3: Interaction IC Sweep (separate BH-FDR pool)
   ┌─────────────────────────────────────────────────────────────────────┐
   │  ops_interaction_primitives_pilot.py pattern, generalized from 8 →   │
   │  ~50 features: partial_spearman_ic() controls for each interaction's │
   │  2 parent_features, writes feature_ic_scores.partial_ic/             │
   │  passes_partial_fdr (migration 206 columns), BH-FDR via              │
   │  alpha.ic.partial_fdr_alpha — SEPARATE pool from Wave 1's atomic     │
   │  alpha.ic.fdr_alpha (design rule: 50 tests, not 30K)                 │
   └─────────────────────────────────────────────────────────────────────┘
                                       │
                                       ▼
                WAVE 4: Regime-Conditioned Collinearity Clusters
   ┌─────────────────────────────────────────────────────────────────────┐
   │  ic_engine.py::_cluster_features() already runs per (symbol, tf,     │
   │  cross_sectional_regime) cell — extend to ALSO condition on          │
   │  feature_vectors.regime (per-symbol HMM state), the axis Phase 140   │
   │  P2 never added. New APR key alpha.ensemble.cluster_regime_          │
   │  conditioned=true (does not exist yet — confirmed via live           │
   │  config_schema query). Output: cluster membership varies by joint    │
   │  (cross_sectional_regime, symbol_hmm_regime), not just the former.   │
   └─────────────────────────────────────────────────────────────────────┘
```

### Recommended Migration/Plan Structure (mirrors ROADMAP's stated 4-plan, 4-wave design)

```
Wave 1 (primitives expansion IC sweep):
├── migration 259 (next free number, verify at execution time — 258 is
│   the latest as of 2026-07-24) — 28 new feature_vectors columns +
│   28 feature_registry rows (tier=0_atomic) + 5 new APR keys
│   (feature.momentum_velocity.window, VWAP delta-window key,
│   macro.sb_corr.window_fast/slow, tip_tlt/hyg_lqd z-score windows,
│   feature.bars_since_extreme_move.sigma_threshold,
│   feature.bars_since_vol_spike.threshold — count exact keys at
│   implementation, todo 123 says 3, todo 180 says 2, verify no overlap)
├── schemas.py — 28 new FeatureVector fields (dataclass)
├── feature_factory.py — 28 new pure compute functions + FEATURE_VECTOR_DOMAIN
│   entries + _cold_start_vector fallbacks
├── feature_cache.py — extend update_cross_asset() for TIP/HYG/LQD bars;
│   new cache fields for equity_beta_z/rate_beta_z/sb_corr rolling state
├── backfill_feature_factory.py / feature_vector_pipeline.py — wire new
│   symbol bar-fetches (TIP/HYG/LQD) alongside existing SPY/TLT/SHY
├── unit tests (tests/unit/intelligence/test_feature_factory_*.py pattern)
└── ic_engine.py sweep run — no code change needed, new columns enter
    automatically via dataclass/registry alignment

Wave 2 (Theory-Motivated Interaction Layer design + registration):
├── Design ≤50 compounds (5 pre-named + up to 45 new), one-sentence
│   hypothesis each — this is an analysis/design task, not pure code
├── migration N+1 — feature_registry rows (tier=1_interaction,
│   parent_features=[atomic1,atomic2] per feature, formula_short=hypothesis)
├── feature_factory.py — compound compute logic (product/ratio/conditional,
│   single operation only per design rule)
└── schemas.py — new FeatureVector fields for the interaction columns

Wave 3 (interaction IC sweep + Feature Registry integration):
├── Generalize ops_interaction_primitives_pilot.py (or a full ic_engine.py
│   sweep) from the 8-feature assumption to the new ~50-feature population
├── BH-FDR: extend alpha.ic.partial_fdr_alpha pool (recommended) or mint
│   a new dedicated key — Open Question, needs a planner/user decision
└── feature_registry status transitions per gate results

Wave 4 (regime-conditioned clusters):
├── migration N+2 — new APR key alpha.ensemble.cluster_regime_conditioned
├── ic_engine.py::_cluster_features() call sites — add symbol_hmm_regime
│   as a second stratification axis alongside cross_sectional_regime
└── New cluster-membership persistence (table or reuse cluster_id column
    with an added regime_group_2 dimension) — design decision, see Open
    Questions
```

### Pattern 1: Adding a new atomic feature (streaming `_series_full` + `_series_last`)

**What:** Every existing atomic feature that needs O(n) one-pass computation over full bar history (not just the latest bar) follows a `_<name>_series_full(...)` → `_series_last(...)` pattern: compute once per corpus pass, then either take the whole array (batch/backfill path) or just the last element (live path).

**When to use:** Any of the 28 Wave 1 atomics that need rolling-window or full-history state (`bars_since_high_fast/slow`, `abs_ret_autocorr_1`, `equity_beta_z`, momentum velocity fields). Simple per-bar stateless transforms (e.g. `minute_of_hour_sin/cos`, pure calendar coordinates) do NOT need this pattern — they compute directly from `bar_ts`/`config`, no history required (see `_in_ny_session`, `_session_time_pos` for that simpler pattern).

**Example (existing sibling to model `abs_ret_autocorr_1` on — `ret_autocorr_1` already computes signed-return autocorrelation, todo 180's abs-value version is a one-line variant):**
```python
# Source: src/intelligence/feature_factory.py:2358 (_ret_autocorr_series_full)
def _ret_autocorr_series_full(closes: np.ndarray, lag: int) -> np.ndarray:
    """result[i] == streaming _ret_autocorr at bar i. O(n) via incremental running sums."""
    # ... existing implementation computes signed log-return autocorrelation
    # abs_ret_autocorr_1 (todo 180 candidate #2) is the identical construction
    # applied to np.abs(returns) instead of raw returns — same running-sum
    # incremental algorithm, different input array.
```

**Example (existing sibling for `bars_since_high_fast/slow` — `_dist_from_high` measures magnitude; the new feature measures recency of the same rolling-extreme event):**
```python
# Source: src/intelligence/feature_factory.py:1210 (_dist_from_high) and
# :2249 (_dist_from_high_series_full) — the new bars_since_high primitive
# needs a parallel "bars since argmax" helper over the same rolling window,
# not a from-scratch design. Design flag from todo 180's Fable review:
# must stay a BOUNDED rolling-window statistic in [0, N-1], not an
# expanding lookback.
```

### Pattern 2: Cross-asset macro spread (extend `FeatureCache.update_cross_asset`)

**What:** `tip_tlt_ret_z`/`hyg_lqd_ret_z` (todo 123) need the exact same construction as the live `yield_slope_z` (TLT/SHY log-return spread, z-scored via a rolling deque) — just a different symbol pair.

**Example:**
```python
# Source: src/intelligence/feature_cache.py:345-357 (update_cross_asset,
# yield_slope_z block) — direct template for tip_tlt_ret_z/hyg_lqd_ret_z:
yzw = config.yield_curve_zscore_window
if len(tlt_bars) >= 2 and len(shy_bars) >= 2:
    n = min(len(tlt_bars), len(shy_bars))
    tlt_closes = np.array([b["close"] for b in tlt_bars[-n:]], dtype=float)
    shy_closes = np.array([b["close"] for b in shy_bars[-n:]], dtype=float)
    tlt_rets = np.diff(np.log(np.maximum(tlt_closes, 1e-10)))
    shy_rets = np.diff(np.log(np.maximum(shy_closes, 1e-10)))
    min_len = min(len(tlt_rets), len(shy_rets))
    if min_len > 0:
        ratio = float(tlt_rets[-1]) - float(shy_rets[-1])
        self._yield_ratio_history.append(ratio)
    self.yield_slope_z = _zscore_from_deque(self._yield_ratio_history, yzw)
# tip_tlt_ret_z: same shape, tip_bars/tlt_bars, new APR key for the
# z-score window (todo 123 doesn't reuse yield_curve_zscore_window --
# needs its own key per the naming-system.md gradient rule, since TIP/TLT
# is a semantically distinct spread from TLT/SHY).
```

**Wiring implication:** `update_cross_asset()`'s signature (`spy_bars, tlt_bars, shy_bars, config`) must grow to accept `tip_bars, hyg_bars, lqd_bars` — every call site (`services/backfill_feature_factory.py:784`, `services/feature_vector_pipeline.py:862`) needs the new bar fetches wired in (`_fetch_bars_from_db(db_conn, "TIP", "1d")` etc., confirmed already reads `market_data_ohlcv_tradeable`, not the raw table — CLAUDE.md's tradeable-view rule is already satisfied by the existing fetch helper).

### Pattern 3: Interaction feature registration (`tier=1_interaction`)

**What:** Every live `tier=1_interaction` row has exactly 2 populated `parent_features` and a `formula_short` describing the operation (product/subtraction/ratio/correlation) — used by `partial_spearman_ic()` to control for the parents.

**Example (live migration 169/197-216 rows, via direct DB query 2026-07-24):**
```
feature_name          | parent_features                  | formula_short
vol_body_product       | {body_ratio,volume_z}            | body_ratio * volume_z
ret_vol_product_fast   | {ret_lag_fast,volume_z}          | ret_lag_fast * volume_z
ret_vol_ratio_fast     | {ret_lag_fast,atr_z}             | ret_lag_fast / atr_z
```
Every Wave 2 interaction candidate should follow this exact shape: 2-element `parent_features` array, `formula_short` stating the single operation. See Common Pitfalls for the ROADMAP text's contradicting `parent_features=[]` spec.

### Anti-Patterns to Avoid

- **Using the `add-plugin`/`plugin-reference`/`wire-pipeline` skills:** These document `src/intelligence/indicators|structure|context|patterns|smart_money|confluence/` — the archived v2.x I1-I7 tiered plugin system. `indicagent-intelligence-pipeline.service` is `failed` with a deleted `ExecStart` target. Zero live consumer. Do not register anything through `register_plugins.py`.
- **Hardcoding any new threshold/window as a Python literal:** Every one of todo 123's 3 and todo 180's 2 flagged APR keys must go through `config_schema`/`config_state`/`config_history`, loaded via `FeatureFactoryConfig` construction (`_prewarm_threshold_config()` in the live pipeline) — CLAUDE.md's migrate-as-you-go rule is not optional here, and this phase's own source todos already called out every needed key.
- **Registering an interaction feature with `parent_features=[]`:** Breaks `ops_interaction_primitives_pilot.py`'s hard assumption of exactly-2-parent unpacking (`_load_interaction_features`) and the partial-IC methodology itself — there is nothing to control for with an empty parent list. Follow the live 8-row precedent instead (see Common Pitfalls).
- **Treating `is_opex_day`/event flags as tier-0 atomic:** Confirmed rejected by the 2026-07-13 Fable review — a binary flag selecting a point in a cycle is a hypothesis (interaction-tier), not a coordinate (atomic-tier). `opex_flag`/`quad_witching_flag` are correctly tier-1 per ROADMAP and `docs/research/signal-temporal-atomic-primitives.md`.
- **Running Spearman IC directly on sparse event flags** (`opex_flag`, ~4% sparse; `quad_witching_flag`, ~1% sparse): the temporal-primitives doc explicitly flags this as the wrong instrument — use the SHADOW-REVIEW-pattern episode-clustered BCa bootstrap of flag days vs. matched control days instead (small dedicated analysis script, not the standard `ic_engine.py` sweep).
- **Assuming a fresh `feature_ic_scores` corpus recompute is required before Wave 1 can run:** it is not architecturally required — new columns simply enter the next scheduled/triggered `ic_engine.py` run via the existing incremental/fingerprint mechanism (Phase 162). But STATE.md flags that a live corpus recompute has NOT been run recently for unrelated reasons (todo 092's regime fix) — coordinate scheduling with whoever owns the next corpus pass rather than triggering a redundant one.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|--------------|-----|
| Spearman IC + bootstrap CI + BH-FDR | A new screening script for the 28 atomics | `services/ic_engine.py`'s existing per-cell sweep | Already handles subsampling, embargo, walk-forward folds, cluster-representative BH-FDR — building a parallel path would double-maintain a 4,878-line correctness-critical file |
| Partial IC controlling for parent features | A new partial-correlation implementation for Wave 3 | `src/intelligence/statistics/ic_math.py::partial_spearman_ic` + `ops_interaction_primitives_pilot.py`'s pattern | Already proven on todo 037's pilot (192/864 cells passed BH-FDR); has the ill-conditioning guard (`alpha.ic.partial_control_condition_max`) already tuned |
| Hierarchical feature clustering | New clustering code for Wave 4 | `ic_engine.py::_cluster_features` (scipy dendrogram, distance-threshold cutoff) | Already the Phase 140 P2 mechanism; Wave 4 is explicitly framed as its extension, not a replacement |
| Feature lifecycle governance (promote/demote/deprecate) | Custom status tracking for new features | `feature_registry` + `feature_transition_log` + the cascade-deprecation trigger (`fn_cascade_parent_deprecation`) | Already auto-deprecates tier-1 children when a tier-0 parent is demoted — exactly the semantics a new interaction layer needs |

**Key insight:** Phase 151's actual net-new code surface is narrow — 28 pure compute functions plus a handful of `FeatureCache` state fields plus migration rows. Every governance, screening, and clustering mechanism already exists and has been used for this exact purpose at least twice (Phase 142.5, Phase 163).

## Common Pitfalls

### Pitfall 1: ROADMAP's `parent_features=[]` spec contradicts the live schema

**What goes wrong:** ROADMAP.md's Theory-Motivated Interaction Layer design-rules section states new interaction features should register with `parent_features=[]` (empty array). Every one of the 8 live `tier=1_interaction` rows has exactly 2 populated `parent_features` (confirmed via direct query, 2026-07-24). An empty array breaks `ops_interaction_primitives_pilot.py`'s `_load_interaction_features()`, which validates and unpacks exactly 2 parents per row before computing partial IC.

**Why it happens:** Likely a drafting slip in ROADMAP's design-rules paragraph — the surrounding text (candidate sources like "momentum_z_fast × low_vol_regime") clearly implies 2-atomic products, and migration 169's own column comment defines `1_interaction` as "deterministic combination of two tier-0 features."

**How to avoid:** Register each Wave 2 interaction with its actual 2 `parent_features`, matching the live precedent exactly. If a candidate's second "parent" is a categorical regime label rather than a numeric atomic (see Pitfall 2), that candidate needs a different registration strategy — not an empty array either.

**Warning signs:** Any plan task that literally copies `parent_features=[]` from ROADMAP text without cross-checking the live schema/precedent.

### Pitfall 2: Regime-label interactions aren't literal 2-atomic products

**What goes wrong:** ROADMAP's candidate-source list includes "momentum_z_fast × low_vol_regime" and "mean-reversion × regime label" — but `market_regimes`/`feature_vectors.regime` labels are categorical strings (e.g. `high_bull`, `trending_down`), not numeric `FeatureVector` columns. A literal product operation needs two numeric operands.

**Why it happens:** The design-rule prose was written at the hypothesis level (finance-theory framing), not the implementation level.

**How to avoid:** Wave 2 needs to resolve, per candidate, whether "× regime" means (a) using a numeric regime-proxy feature already in `FeatureVector` (e.g. `volatility_rank_z` standing in for "low_vol_regime"), or (b) a genuine stratified/conditional split computed at IC-measurement time rather than as a persisted `FeatureVector` column at all. This is a real design decision, not a coding detail — flagged in Open Questions.

**Warning signs:** A Wave 2 task that tries to multiply a float column by a string regime label without first resolving which of (a)/(b) applies.

### Pitfall 3: Migration number collision

**What goes wrong:** Migration 255's own header note documents this exact failure mode happening twice already (216 vs 221/222/223; 243 vs the plan's stated 243 assumption vs the actual free number 255) — a plan written today naming "migration 259" may find a different number is actually free by execution time if a concurrent session lands migrations first.

**Why it happens:** Multiple concurrent GSD/ad hoc sessions land migrations against the same numbering sequence; ROADMAP/CONTEXT/RESEARCH docs are written before execution, and the sequence can move between planning and execution.

**How to avoid:** Verify the actual next-free migration number (`ls production/migrations/ | sort -t_ -k1 -n | tail -5`) immediately before writing each migration file at execution time, not just at planning time. As of this research (2026-07-24), 258 is the latest; Wave 1 should provisionally target 259 but MUST re-verify at execution.

### Pitfall 4: Sparse event-flag IC methodology mismatch

**What goes wrong:** Running standard `ic_engine.py` Spearman-rank IC on `opex_flag` (~4% sparse) or `quad_witching_flag` (~1% sparse) produces a technically-computable but statistically-wrong result — Spearman rank correlation on a near-constant binary series has degenerate power characteristics documented explicitly in `docs/research/signal-temporal-atomic-primitives.md`.

**Why it happens:** The standard IC sweep is designed for continuous/near-continuous features; sparse flags are a fundamentally different statistical object (rare-event testing).

**How to avoid:** Per the temporal-primitives doc's own resolved methodology split: smooth coordinates (`quarter_cycle_sin/cos`, `tdom_sin/cos`, `minute_of_hour_sin/cos`) go through the standard `ic_engine.py` + partial-IC path; sparse flags (`opex_flag`, `quad_witching_flag`) use the SHADOW-REVIEW-pattern episode-clustered BCa bootstrap (flag days vs. matched control days) as a small dedicated analysis script, NOT the standard sweep.

**Warning signs:** A Wave 1/3 plan task that runs `opex_flag`/`quad_witching_flag` through the exact same `ic_engine.py` invocation as the other 28 atomics without branching methodology.

### Pitfall 5: Circular-block bootstrap block length vs. calendar feature cycle period

**What goes wrong:** The 143.1-01 circular-block bootstrap's block length must be >= a feature's cycle period, or the CI is invalid. A quarter-period feature (`quarter_cycle_sin/cos`) at 1d timeframe needs ~63-trading-day blocks; the engine's default block length (tuned for non-cyclical features) is shorter.

**Why it happens:** Block-bootstrap block length is itself an APR-tunable global default, not per-feature — a feature with an unusually long natural cycle period breaks the implicit assumption that the default block length exceeds any feature's autocorrelation structure.

**How to avoid:** Per the temporal-primitives doc's own pre-check: either confirm the bootstrap's block length parameter already exceeds ~63 trading days for the relevant (tf, feature) combination, or aggregate to per-episode means before computing IC for `quarter_cycle_sin/cos` specifically.

**Warning signs:** `quarter_cycle_sin/cos` IC results with implausibly tight confidence intervals (a common symptom of a bootstrap block length shorter than the true autocorrelation structure).

### Pitfall 6: Backfill worker-count OOM (unrelated bug class, same script)

**What goes wrong:** `backfill_feature_factory.py --compute-only` at its default worker count (12) has twice OOM-killed on this machine during a large recompute (documented in STATE.md's 2026-07-22 closeout) — a Wave 1 full-corpus recompute for the 28 new columns is exactly the kind of operation that triggers this.

**Why it happens:** 12 concurrent workers each computing full-history features for large symbols (390K+ bars) exceeds available RAM.

**How to avoid:** Use `--workers 4` (already a documented flag / `infra.feature_factory.workers` APR key) for any recompute touching more than a handful of symbols.

**Warning signs:** The process disappearing silently ~5-6 minutes into a `--compute-only` run with no Python traceback (check `journalctl -k` for OOM-killer entries, not the script's own logs).

## Code Examples

### Existing atomic feature (calendar coordinate, no history needed) — template for `minute_of_hour_sin/cos`

```python
# Source: src/intelligence/feature_factory.py — dow_sin/dow_cos precedent
# (exact line numbers vary; grep "dow_sin" for current location)
# minute_of_hour_sin/cos follows the identical sin/cos-of-a-bounded-cycle
# pattern already used for dow_sin/cos, month_position, quarter_position:
def _minute_of_hour_sin_cos(bar_ts: datetime) -> tuple[float, float]:
    minute = bar_ts.minute
    angle = 2 * math.pi * minute / 60.0
    return math.sin(angle), math.cos(angle)
```

### Existing velocity pattern — template for `momentum_z_velocity_fast/mid/slow`, `vwap_dev_sigma_velocity`

```python
# Source: src/intelligence/feature_factory.py:2748 (_vol_velocity_z_series_full)
def _vol_velocity_z_series_full(atr_z: np.ndarray, window: int) -> np.ndarray:
    """result[i] == streaming vol_velocity_z at bar i. Delta of the underlying
    z-score over `window` bars, then z-scored again. Direct template: apply the
    identical construction to momentum_z_fast/mid/slow (-> momentum_z_velocity_*)
    and vwap_dev_sigma (-> vwap_dev_sigma_velocity), each needing its own APR
    window key (feature.momentum_velocity.window; a new VWAP delta-window key —
    do NOT reuse vol_velocity_window, a semantically distinct family per the
    naming-system.md gradient rule)."""
```

### Existing partial-IC screening entry point — template for Wave 3

```python
# Source: scripts/ops/alpha/ops_interaction_primitives_pilot.py:115
async def _load_interaction_features(conn: asyncpg.Connection) -> list[dict]:
    """tier='1_interaction' rows from feature_registry with their parent atomics.
    Validated here, once, before any per-tf work starts: every Renaissance
    interaction primitive has exactly 2 parent atomics (the partial_spearman_ic
    call below assumes and unpacks exactly 2)."""
    # Wave 3 generalizes this from the current 8-feature cohort to ~50 --
    # the query itself (`WHERE tier = '1_interaction'`) needs no change,
    # it will simply return more rows once Wave 2's registrations land.
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|---------------|--------|
| Single global (non-regime-conditioned) collinearity clustering | Per-(symbol, tf, cross_sectional_regime) clustering, already live | Phase 140 P2 (migration 171, 2026-06-25) | Wave 4's actual gap is adding the per-symbol HMM regime axis on top of the already-live cross-sectional-regime conditioning — ROADMAP's framing of Phase 140 as "global" is imprecise; verify this nuance with the planner before scoping Wave 4 |
| `is_opex_day` as a single flag | Split into `opex_flag` (monthly) + `quad_witching_flag` (quarterly) | Todo 104 Fable review, 2026-07-13 | Splitting is itself the test design — isolates expiration mechanics from quarter-end seasonality |
| `mkt_beta_z` / unqualified "beta" naming | `equity_beta_z` / `rate_beta_z` (factor-qualified) | Todo 180 Fable review + naming-compliance audit, 2026-07-24 | Glossary bans unqualified `beta`; every beta must name its factor |
| "real yield spread" / "credit spread" (theory-laden names) | `tip_tlt_ret_z` / `hyg_lqd_ret_z` (instrument-descriptive) | Todo 123 Fable review, 2026-07-24 | Matches `yield_slope_z`'s convention — theory-free naming for a theory-free ratio computation |

**Deprecated/outdated:** `days_to_month_end` is exactly redundant with `1 - month_position` (found during todo 104's review) — removal filed separately as todo 115, not in this phase's scope but worth noting if Wave 1 touches nearby calendar code.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|----------------|
| A1 | Wave 3 should extend `alpha.ic.partial_fdr_alpha` (migration 206) rather than mint a new dedicated key for the ~50-feature interaction pool | Standard Stack (Alternatives), Architecture Patterns (Wave 3) | If the user/planner wants Wave 3's population statistically separated from todo 037's original 8-feature pilot cohort, a new key is needed instead — low-cost to change, but affects one migration's content |
| A2 | The exact count of new APR keys is 3 (todo 123) + 2 (todo 180) = 5, no overlaps | Recommended Migration Structure | If any two candidates end up sharing a window concept (e.g. if the planner decides momentum-velocity and VWAP-velocity should share one window key), the actual count could be 4; low risk, easy to verify at implementation |
| A3 | "Momentum × low_vol_regime"-style interaction candidates require resolving categorical-vs-numeric parent representation before Wave 2 registration (Pitfall 2) | Common Pitfalls | If this is left unresolved, Wave 2 could register a candidate that literally can't be computed as specified, discovered only at Wave 2 implementation time rather than planning time |
| A4 | Wave 4's "one cluster membership table per HMM state" should be read as adding `feature_vectors.regime` (per-symbol HMM axis) as a stratification dimension alongside the already-live `cross_sectional_regime` axis, not replacing it | State of the Art, Open Questions | If the ROADMAP intent was actually to replace/simplify the existing cross-sectional-regime clustering rather than add a second axis, the Wave 4 scope shrinks significantly |

## Open Questions (RESOLVED)

Questions 1-3 were resolved at planning time (2026-07-24); the resolutions are implemented in plans
151-02, 151-06, and 151-08. Question 4 is a sequencing question this research deliberately does not
answer; it was surfaced to the user and accepted before planning proceeded (see the note under Q4).
The same resolutions are recorded in ROADMAP.md's "Planning-time decisions recorded (2026-07-24)"
block; they are inlined here so this document stands alone for future readers.

1. **Does Wave 3's interaction BH-FDR pool extend migration 206's `alpha.ic.partial_fdr_alpha` or need a dedicated key?**
   - What we know: The existing key/columns were built for exactly this purpose (partial IC for `tier=1_interaction` features) and are currently scoped to 8 features.
   - What's unclear: Whether growing the population 8 -> ~50 within the same statistical family is intended, or whether the ROADMAP's "separate BH-FDR pool from atomics" language implies Wave 3 needs its own distinct pool separate even from todo 037's pilot cohort.
   - Recommendation: Default to extending the existing key (simpler, avoids a 3rd BH-FDR family) unless the user has a specific reason to keep todo 037's pilot cohort as a permanently separate population.
   - **RESOLVED (2026-07-24, implemented in plan 151-08):** Extend the existing
     `alpha.ic.partial_fdr_alpha` pool (migration 206, todo 037) rather than mint a third BH-FDR
     family. The tier-1 interaction population lands at 23 rows (8 pre-existing + 5 named + 10
     designed), inside ROADMAP's <=50 cap, and the cap becomes a machine-enforced invariant via
     `test_interaction_tier_population_within_cap` rather than a prose commitment. The pool-growth
     effect on todo 037's original 8-feature cohort is quantified in 151-08's report rather than
     left implicit.

2. **How do categorical-regime interaction candidates (Pitfall 2) get represented?**
   - What we know: Some of ROADMAP's suggested interaction sources ("momentum x low_vol regime," "mean-reversion x regime label") pair a numeric atomic with a categorical stratification axis, not another numeric atomic.
   - What's unclear: Whether Wave 2 substitutes a numeric proxy feature, computes these as regime-stratified IC cells rather than persisted compound columns, or drops these specific candidate sources in favor of purely numeric-times-numeric compounds.
   - Recommendation: Resolve explicitly during Wave 2 design (before any registration), not deferred to implementation.
   - **RESOLVED (2026-07-24, implemented in plan 151-06):** Numeric-proxy substitution.
     `market_regimes` and `feature_vectors.regime` are categorical strings, so every "x regime"
     candidate uses an existing numeric tier-0 proxy instead (`hv_ratio`, `adx`, `hurst`,
     `variance_ratio_fast`, `vix_z`, `yield_slope_z`). No compound multiplies a string, and no
     second stratification surface is opened.

3. **Wave 4 cluster persistence: new table, or extend the existing `cluster_id` column's semantics?**
   - What we know: Clustering today is ephemeral per `ic_engine.py` cell run (not a standalone persisted table); `cluster_id` is written onto `feature_ic_scores` rows per Phase 140 P2 (migration 171).
   - What's unclear: Whether "one cluster membership table per HMM state" (ROADMAP's phrasing) means a genuinely new standalone table, or just adding `feature_vectors.regime` as an additional groupby key to the existing per-cell clustering call sites (`_compute_one_regime_cell`, `_compute_cross_sectional_tf`'s helper).
   - Recommendation: The lighter-weight option (add a groupby dimension to existing call sites) fits the "extension of Phase 140 P2" framing better and avoids a new persistence surface; flag this as the recommended default but confirm with the user given ROADMAP's literal "table" wording.
   - **RESOLVED (2026-07-24, implemented in plan 151-02):** No new table. Clustering is already
     per-(symbol, tf, regime) inside `_compute_one_regime_cell`; the real gap is that the
     `symbol_hmm` pass only runs for regime groups with `dual_write_symbol_hmm=true` (live:
     `rates` only, migration 247). A new `alpha.ensemble.cluster_regime_conditioned` APR key widens
     that gate so the second stratification axis runs for every routed symbol. This also supersedes
     assumption A4 above and ROADMAP's earlier "Phase 140's clustering is global" framing, which was
     imprecise.

4. **Sequencing tension: is Phase 151 actually next, given STATE.md's Tier 6 gating?**
   - What we know: STATE.md places Phase 151 behind resolving whether the current feature set + ensemble construction has ANY OOS-detectable edge at all (the "prove edge before production infra" principle, applied here as "prove the current features are exhausted before adding more").
   - What's unclear: Whether this research/planning dispatch represents a deliberate override of that gating (e.g., the user decided to invest in features per the Tier-1 "strategic fork" framing) or should be flagged back to the user before `/gsd-execute-phase 151` runs.
   - Recommendation: Not this research's call - surface explicitly to the user at `/gsd-discuss-phase 151` or plan-review time.
   - **SURFACED AND ACCEPTED (2026-07-24):** This tension was raised to the user before planning
     proceeded, and the `/gsd-plan-phase 151` invocation is the user's explicit acceptance of the
     Tier-1 "strategic fork" reading: Phase 151 proceeds ahead of STATE.md's Tier-6 gate as a
     deliberate override, not an oversight. This remains a product/sequencing decision owned by the
     user, not a research finding - it is recorded here so a future reader does not re-litigate it
     as an unresolved gap. If the Tier-6 edge question is later answered negatively, revisit whether
     the features added by this phase are still worth carrying.

## Environment Availability

Skipped — this phase has no new external tool/service dependencies. All required infrastructure (TimescaleDB with `feature_vectors`/`feature_registry`/`config_schema` tables, `ic_engine.py`'s `ProcessPoolExecutor` batch mechanics, `market_data_ohlcv_tradeable` view, existing SPY/TLT/SHY/TIP/HYG/LQD instrument coverage) is already live in production per direct code/schema inspection this session.

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest (`.venv/bin/pytest tests/unit/ -v`) |
| Config file | `pytest.ini` (repo root) |
| Quick run command | `.venv/bin/pytest tests/unit/intelligence/test_feature_factory_batch.py -q` |
| Full suite command | `.venv/bin/pytest tests/unit/ -q` |

### Phase Requirements -> Test Map

No formal `REQUIREMENTS.md`/requirement-ID system exists in this project (confirmed: `.planning/REQUIREMENTS.md` does not exist) — ROADMAP.md's Phase 151 section is itself the authoritative requirement text. Mapping its major deliverables to test types:

| Deliverable | Behavior | Test Type | Automated Command | File Exists? |
|---|---|---|---|---|
| 28 new atomic primitives compute correctly | Each new `FeatureVector` field returns expected value/shape given synthetic OHLCV | unit | `.venv/bin/pytest tests/unit/intelligence/test_feature_factory_batch.py -x` (extend) | ✅ existing file, ❌ new test cases (Wave 0) |
| `feature_registry`/`FeatureVector` alignment holds after 28+ new columns | Registry row count == dataclass field count | unit | `.venv/bin/pytest tests/unit/intelligence/test_feature_registry_service.py -x` | ✅ existing file |
| New APR keys load correctly via `ConfigService` | `FeatureFactoryConfig` construction picks up new keys with correct defaults | unit | new test in `tests/unit/intelligence/` | ❌ Wave 0 |
| Interaction features (`tier=1_interaction`) register with correct `parent_features` shape | Migration seed rows have exactly 2 non-empty `parent_features` | unit/integration | new assertion, or extend `tests/unit/test_ic_engine_clustering.py`-style pattern | ❌ Wave 0 |
| Wave 4 regime-conditioned clustering | Cluster membership differs across `symbol_hmm_regime` values for the same `cross_sectional_regime` | unit | extend `tests/unit/test_ic_engine_clustering.py` | ✅ existing file, ❌ new test cases (Wave 0) |
| Sparse event-flag IC methodology (`opex_flag`/`quad_witching_flag`) | Episode-clustered bootstrap script, NOT standard `ic_engine.py` sweep | manual/script | new small analysis script per temporal-primitives doc | ❌ not automated by design (small one-off analysis, matches the SHADOW-REVIEW precedent) |

### Sampling Rate
- **Per task commit:** targeted `tests/unit/intelligence/` subset covering the touched feature family
- **Per wave merge:** `.venv/bin/pytest tests/unit/ -q` (full suite)
- **Phase gate:** Full suite green before `/gsd:verify-work`, plus a live IC sweep run (not unit-testable — this is a statistical measurement, not a code-correctness check) confirming the 28 new atomics + interaction candidates produce non-degenerate `feature_ic_scores` rows

### Wave 0 Gaps
- [ ] Unit tests for each of the 28 new atomic compute functions (extend `tests/unit/intelligence/test_feature_factory_batch.py` and/or `test_feature_factory_p7.py` pattern)
- [ ] Unit test confirming new APR keys load with correct defaults via `FeatureFactoryConfig`
- [ ] Unit test confirming `feature_registry` row count matches `FeatureVector` field count after each wave's migration (extends existing `test_feature_registry_service.py` alignment-gate coverage)
- [ ] Unit test confirming every new `tier=1_interaction` registry row has exactly 2 non-empty `parent_features` (guards against Pitfall 1 regressing)
- [ ] Extend `tests/unit/test_ic_engine_clustering.py` for Wave 4's regime-conditioned clustering behavior

## Security Domain

Not applicable — this is an internal feature-engineering phase with no new external inputs, authentication surfaces, or user-facing endpoints. `security_enforcement` gating in `.planning/config.json` is absent (default enabled per the skill's own instructions), but this phase's scope (pure numeric transforms on already-ingested OHLCV/macro ETF data, internal migrations, internal batch jobs) has no applicable ASVS category — no V2/V3/V4/V5/V6 controls are triggered by adding database columns and compute functions to an already-authenticated internal pipeline.

## Project Constraints (from CLAUDE.md)

- **APR mandate:** every new tunable numeric value (all 5 new todo-123/180 window/threshold keys) MUST go through `config_schema`/`config_state`/`config_history` migrations, loaded via `ConfigService.get()`/`get_sync()` — never a hardcoded literal in `feature_factory.py`.
- **Migrate-as-you-go:** any hardcoded numeric threshold encountered while touching `feature_factory.py`/`feature_cache.py` during this phase must be migrated in the same session, not deferred.
- **Naming system (`docs/foundation/naming-system.md` §7):** gradient qualifiers must come from the approved vocabulary (`fast`/`mid`/`slow`, `low`/`high`, etc.) — numbers in names only when the number IS the statistic (`abs_ret_autocorr_1`, `bars_since_52w_high`), never a tunable calibration parameter (already verified compliant for all 33 named candidates per the todos' own naming-compliance audits).
- **Ring rule:** all new code lives in `src/intelligence/` (Ring 1 domain) — `feature_factory.py`, `feature_cache.py`, `schemas.py` are all already correctly placed there.
- **`market_data_ohlcv_tradeable` rule:** all new bar reads (TIP/HYG/LQD, own-symbol history for recency/beta features) MUST go through the tradeable view, never raw `market_data_ohlcv` directly — confirmed the existing `_fetch_bars_from_db()` helper in `backfill_feature_factory.py` already does this correctly (post todo-124 fix), so extending it for new symbols inherits correctness for free.
- **DAG Invariant 3 (compute daemon never writes its own output):** all 28+ new atomics flow through the existing `FeatureVectorWriter` — no direct persistence from `FeatureFactory.compute()` or `FeatureCache`.
- **All timestamps UTC:** any new calendar-primitive code (`minute_of_hour_sin/cos`, `tdom_sin/cos`) must use `datetime.now(UTC)`/timezone-aware `bar_ts`, matching the existing `dow_sin`/`month_position` precedent.
- **File/class renames require a test sweep:** not directly triggered by this phase (no renames), but any `FeatureCache.update_cross_asset()` signature change (adding tip/hyg/lqd params) requires updating every call site and its tests.
- **Never log per-row inside a loop over the full corpus:** if Wave 1's backfill recompute touches millions of rows, follow the `ic_engine.py` accumulate-and-report-once pattern, not per-row logging.

## Sources

### Primary (HIGH confidence — direct code/schema/doc reads this session)
- `production/migrations/169_feature_registry.sql`, `206_partial_ic_interaction_primitives.sql`, `255_vp_structural_primitives.sql` — full text read
- `src/intelligence/feature_factory.py` (4,878-line sibling file `services/ic_engine.py` also fully greped) — patterns for `_velocity`, `_dist_from_high`, `_ret_autocorr`, `FEATURE_VECTOR_DOMAIN`, `_cold_start_vector`
- `src/intelligence/feature_cache.py` — `update_cross_asset()` full implementation read
- `src/intelligence/feature_registry_service.py` — `_REGISTRY_ROW_COUNT` alignment gate
- `scripts/ops/alpha/ops_interaction_primitives_pilot.py` — partial-IC screening pattern
- `services/backfill_feature_factory.py` — confirmed `market_data_ohlcv_tradeable` usage, `--workers` OOM gotcha
- Live DB queries (`feature_registry` tier counts, `tier=1_interaction` parent_features shape, `config_schema` key existence checks) via `psql`
- `.planning/ROADMAP.md` Phase 151 section (full text, lines 1668-1723) plus surrounding v3.x/v4.0 context
- `.planning/todos/pending/123-momentum-velocity-and-macro-spread-features.md`, `180-four-new-atomic-primitive-candidates-phase151.md`, `.planning/todos/deferred/066-cross-tf-divergence-primitives.md`, `.planning/todos/completed/104-quarterly-seasonality-opex-fable-review.md`
- `docs/research/signal-temporal-atomic-primitives.md` — exact formulas and methodology split for calendar primitives
- `docs/foundation/naming-system.md` §7 — gradient vocabulary rule
- Root `CLAUDE.md` and `src/intelligence/CLAUDE.md` — archived v2.x pipeline banner, APR mandate, DAG invariants
- `.planning/STATE.md` — current phase sequencing/gating context

### Secondary (MEDIUM confidence)
- `docs/research/intel-feature-interaction-factory.md` — referenced for the combinatorial-vs-curated design rationale (skimmed, not fully re-derived this session, but consistent with ROADMAP's own restatement)

### Tertiary (LOW confidence)
- None — every claim in this document traces to a direct file/DB read this session; no unverified WebSearch-only claims were needed since this is an entirely internal codebase question.

## Metadata

**Confidence breakdown:**
- Standard stack / architecture: HIGH — every mechanism (Feature Factory, feature_registry, ic_engine BH-FDR, partial IC) is live code, directly read this session, used successfully at least twice before for the identical task shape.
- Pitfalls: HIGH for the ones grounded in direct schema/code comparison (parent_features shape, migration numbering, OOM); MEDIUM for the ones requiring judgment about ROADMAP's intent (Wave 4 table-vs-axis, Wave 3 pool reuse).
- Candidate roster completeness: HIGH — the 28+5 candidates are the ROADMAP's own already-Fable-reviewed list; this research did not re-derive or second-guess the candidate selection itself, only the implementation mechanics.

**Research date:** 2026-07-24
**Valid until:** ~14 days (this codebase's migration sequence and STATE.md's phase-gating context move fast — re-verify the next-free migration number and STATE.md's current Tier ordering before executing, not just before planning)
