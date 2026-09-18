# Phase 175: ITR materiality-filtered empirical tags for breadth/peer-grouping - Research

**Researched:** 2026-09-18
**Domain:** Statistical filtering of `instrument_tags` empirical rows (multi-factor orthogonalization, partial correlation, null-arm validation) feeding two `market_regimes` consumers
**Confidence:** HIGH (architecture, reuse targets, migration/APR conventions) / MEDIUM (exact threshold numbers, which control-factor set is complete) / LOW (rolling-window sign-stability construction — no existing helper found)

## Summary

This phase adds a 4th measurement pass to `services/tag_calibrator.py` that computes an
orthogonalized (partial) factor loading for every `source='empirical'` `sensitivity`/
`macro_driver` row, persists it as new `instrument_tags` evidence columns, and writes a
shadow-mode diagnostic comparing today's `source='human'`-only breadth/peer-pool membership
against what membership would look like if materiality-eligible empirical rows were also
admitted. No consumer query changes ship in this phase (D-03).

The core statistical primitive already exists in this codebase and does not need to be
built from scratch: `src.intelligence.statistics.ic_math.partial_spearman_ic(x, y, controls,
condition_max)` implements exactly the "residualize target and candidate against a control
design matrix, correlate residuals" pattern all three cross-AI reviewers (Codex/Fable/AGY)
independently proposed for orthogonalizing a candidate instrument's return against a control
set before measuring its incremental loading on the target factor. It is rank-based
(Spearman) where `TagCalibrator`'s existing Pass 1 (`standardized_loading`) is a raw
(Pearson) standardized beta — Pass 4 needs a decision (below) on which convention to match,
since `loading_threshold`/`weight` semantics on the existing empirical rows are Pearson-based.
The control-factor set Codex/AGY describe (broad equity, rates, credit, dollar, commodity)
already exists as live, working `tag_vocabulary.factor_series` proxies — `SPY` (`equity_beta`),
`TLT` (`rate_sensitive`), `HYG-IEF` (`credit_risk`), `UUP` (`dollar_strength`) — with one gap:
no existing `factor_series` row represents "commodity broad" (`commodity_broad` is a
definitional/identity tag with no proxy); DBC is available in the corpus
(`compute_eligible=true`, confirmed active in Phase 174's cross-asset basket) and is the
natural candidate if a commodity control leg is needed.

The BH-FDR correction (`apply_bh_fdr`), the HAC p-value math (`loading_hac_pvalue`'s
inflation-factor approach), the ill-conditioning gate (`check_condition_number`), and the
existing `discovery_state`/hysteresis/expiry machinery in `_next_evidence`/`decide_outcome`
are all directly reusable — this phase extends, not replaces, `TagCalibrator`'s 3-pass
engine. The null-arm circular-shift primitive (`ic_math._circular_shift_null`) is already
used for exactly this shape of validation in `scripts/analysis/tsmom_per_symbol_ic_screen.py`
and reuses cleanly for D-06's factor-proxy-only shift.

The two folded todos (125 discovery-OOS enforcement, 126 `valid_to` filtering) are both small,
well-scoped additions once the new evidence columns exist — 125 needs a `discovery_state`
column (promoted out of the `evidence` JSONB per the todo's own addendum) gating a materiality
read, and 126 needs a canonical `instrument_tags_active` view (proposed by the todo, never
built) that both this phase's diagnostic and any future consumer cutover should use.

**Primary recommendation:** Extend `TagCalibrator` with a Pass 4 that reuses
`partial_spearman_ic` (or a Pearson-loading sibling matching Pass 1's convention — planner
must pick one explicitly, see Open Questions) against the existing SPY/TLT/HYG-IEF/UUP control
proxies, persist evidence columns + a promoted `discovery_state` column via one migration,
seed `alpha.tag_calibrator.materiality.*` APR keys at Codex's numbers (most conservative of
the three), build a read-only shadow diagnostic script (not a consumer query change), and
gate the whole Pass 4 write path behind the existing `discovery_oos_days`/hysteresis
machinery already in `_apply_decision`.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Orthogonalized/partial loading computation | Database/Storage-adjacent batch compute (`TagCalibrator`, a `BaseBatch` oneshot) | — | Matches D-01: one measurement engine, not per-consumer duplication; same tier as existing Pass 1-3 |
| Evidence persistence (new columns) | Database/Storage (`instrument_tags` schema via migration) | — | Same table, same lifecycle machinery (hysteresis, `valid_to`) as existing empirical rows |
| Materiality threshold application | API/Backend batch consumers (`breadth_vol.py`, `cross_sectional_regime_model.py`) — but shadow-mode diagnostic only this phase | Database/Storage (read-time `WHERE` clause) | D-02: consumers apply their own cutoff at read time against the persisted statistic; no live query change ships this phase |
| Null-arm validation | **OVERRIDDEN, see note below.** As researched: Analysis/offline (`scripts/analysis/`, not a live daemon) | — | Matches `tsmom_per_symbol_ic_screen.py`'s existing placement — a one-off validation script, not part of the production DAG |
| APR threshold storage | Database/Storage (`config_schema`/`config_state`) | — | Standard APR pattern; `ConfigService` is the sole read path |
| Shadow-mode diagnostic | Analysis/offline (new script under `scripts/analysis/`) | — | Read-only, reports what-would-change; explicitly not a consumer, not a writer |

> **R-02 override (plan 03, 175-03-PLAN.md):** the planner overrode the null-arm row above. The D-06 circular-shift null arm runs **inline inside `TagCalibrator.execute()`** as part of Pass 4, not as an offline `scripts/analysis/` step. Rationale and the cost argument that makes it affordable across the whole corpus are in plan 03's R-02 resolution; plan 02's vectorized partial-loading primitive is what brings the Monte-Carlo draw cost into range. `null_arm_p_value` is therefore written on every `TagCalibrator` run rather than refreshed periodically. Treat this row as historical research framing, not as the shipped tier assignment.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

- **D-01:** Extend `TagCalibrator` (`services/tag_calibrator.py`) with a 4th pass computing
  an orthogonalized/incremental factor loading, persisted as new evidence columns on
  `instrument_tags` for every `source='empirical'` row (unconditionally — this is a
  measurement, not an admission decision). Rejected building this inside
  `breadth_vol.py`/`cross_sectional_regime_model.py` directly.
  **AMENDED 2026-09-18 by D-01a (see CONTEXT.md):** the D-07 cross-AI review found this
  wording wider than what plan 03 actually implements ("kept" rows only, i.e. rows clearing
  Pass 1-3's `passes_fdr AND abs(loading) >= loading_threshold` gate) -- CONTEXT.md's D-01a
  amendment narrows this decision's text to match the plan, rather than widening the plan to
  match this original wording. This entry is a frozen research-time snapshot; CONTEXT.md is
  the current, authoritative decision record.
- **D-02:** Each consumer applies its *own* admission threshold as a `WHERE` clause at read
  time against the persisted statistic. Do not build N copies of the orthogonalization math.
  New evidence columns needed on `instrument_tags`: the orthogonalized/partial factor loading,
  its incremental R², a sign-stability measure across rolling windows, and a boolean/threshold
  outcome per the seeded APR bar. Migration required. Exact names/types are a
  research/planning decision, not locked.
- **D-03:** Shadow mode first, non-negotiable. TagCalibrator writes the new evidence columns
  for every empirical row informationally in this phase. A diagnostic script (new, this
  phase) reports what breadth-universe/peer-pool membership *would* change if the two
  consumers switched from human-only to human-OR-passes-materiality — reviewed (by the user,
  and via cross-AI review) before either consumer's live query actually changes. Cutting over
  the two consumers' queries themselves may be a **separate, later phase** — do not assume
  cutover is in this phase's scope without re-confirming after the shadow-mode diagnostic
  lands.
- **D-04:** Do not average or arbitrarily pick between Codex's (`abs(partial_beta) >= 0.35`,
  `sample_n >= 756`, sign-stable 3/4 windows), Fable's (peer-relative distribution check), or
  AGY's (`|beta| >= 0.30`, asset-class prior constraint) proposed numbers as if reconciling
  them produced a validated answer.
- **D-05:** Seed the more conservative of the three reviewers' thresholds as new
  `alpha.tag_calibrator.materiality.*` APR keys, each description explicitly marked
  `[initial_estimate]`/uncalibrated. Empirical re-calibration is real follow-up work, not
  required to ship this phase's shadow-mode measurement.
- **D-06:** Null-arm control = circular time-shift of the `factor_series` proxy's own return
  series — NOT a symbol-shuffle, NOT a candidate-return shift. Reuses the circular-shift null
  pattern already established in `scripts/analysis/tsmom_per_symbol_ic_screen.py`. Must clear
  this null-arm control before any candidate's materiality flag is trusted.
- **D-07:** Get Fable involved in reviewing the eventual PLAN.md/design before implementation,
  paired with Codex and/or AGY.
- **Todo 125 folded in:** `discovery_oos_days` gate becomes load-bearing — a newly-discovered
  empirical tag must not be materiality-eligible until `discovery_oos_days` of confirmation
  have elapsed.
- **Todo 126 folded in:** both consumers' new materiality-aware queries (and the shadow-mode
  diagnostic) must filter `valid_to IS NULL`.

### Claude's Discretion

- Exact column names/types for the new `instrument_tags` evidence fields.
- Whether the live cutover of the two consumers' queries becomes this phase's own scope or a
  separate follow-on phase — left open pending the shadow-mode diagnostic's findings.

### Deferred Ideas (OUT OF SCOPE)

- Todo 272 (`instrument-tag-peer-group-coverage-auditor`) — different capability, stays its
  own future todo.
- Live cutover of `breadth_vol.py`/`cross_sectional_regime_model.py` queries — may become its
  own phase, gated on this phase's shadow-mode diagnostic findings.
</user_constraints>

<phase_requirements>
## Phase Requirements

No formal `.planning/REQUIREMENTS.md` exists in this project (confirmed absent — this project
tracks phase scope via `.planning/ROADMAP.md` phase entries and phase CONTEXT.md, not a
separate requirements register). The phase's requirement set is fully specified by
CONTEXT.md's Decisions (D-01 through D-07) plus the two folded todos, reproduced above.
Requirement IDs below are synthesized from those decisions for planner traceability.

| ID | Description | Research Support |
|----|-------------|------------------|
| P175-01 | Pass 4 lives in `TagCalibrator`, computes orthogonalized/partial loading per empirical `(symbol, tag)` pair | `partial_spearman_ic` reuse target identified; existing Pass 1-3 structure documented below |
| P175-02 | New evidence columns on `instrument_tags` via migration; consumers read, never recompute | Migration pattern (238/343) documented; column list proposed below |
| P175-03 | Shadow-mode diagnostic script, no live consumer query change this phase | `breadth_vol.py`/`cross_sectional_regime_model.py` current read paths documented; diagnostic script skeleton proposed below |
| P175-04 | APR keys seeded at conservative (Codex) numbers, `[initial_estimate]` tagged | `alpha.tag_calibrator.*` namespace and migration 342's APR-seeding pattern documented |
| P175-05 | Null-arm: circular time-shift of factor_series proxy only | `ic_math._circular_shift_null` and its existing call site documented below |
| P175-06 | Todo 125: `discovery_oos_days` becomes enforced/load-bearing for materiality eligibility | `_next_evidence`'s existing `discovery_state` computation and its "computed but never read" gap documented |
| P175-07 | Todo 126: `valid_to IS NULL` filtering contract for any new materiality-aware query | `instrument_tags_active` view proposal (never built) documented; confirmed absent in codebase |
| P175-08 | Cross-AI review (Fable + Codex/AGY) of the PLAN.md before implementation | Process requirement, not a code dependency — flag for the planner to schedule as a review gate |
</phase_requirements>

## Standard Stack

### Core (all already in-project — no new packages)

| Library | Version (installed) | Purpose | Why Standard |
|---------|---------|---------|--------------|
| numpy | (project pinned) | `lstsq`-based partial regression, circular shift | Already the sole linear-algebra dependency in `ic_math.py`/`factor_math.py` |
| pandas | (project pinned) | Series alignment, rolling windows | Already used throughout `tag_calibrator.py` |
| statsmodels | (project pinned) | `multipletests` (BH-FDR) — reused via `apply_bh_fdr`, not re-imported directly | Already imported in `ic_math.py`; do not add a second direct `statsmodels` import to `tag_calibrator.py` — go through `ic_math`/`factor_math`'s existing wrappers |
| asyncpg | (project pinned) | DB writes | `TagCalibrator` already uses it |

### Package Legitimacy Audit

**Not applicable — this phase installs zero new external packages.** Every function needed
(partial regression, BH-FDR, HAC p-values, circular-shift null) is either already implemented
in `src/intelligence/statistics/ic_math.py` / `factor_math.py`, or is a straightforward
extension of those using only numpy/pandas/statsmodels, all already project dependencies. The
Package Legitimacy Gate protocol is skipped for this reason — no `slopcheck`/registry
verification is needed since nothing new is being installed.

## Architecture Patterns

### System Architecture Diagram

```
tag_vocabulary (sensitivity/macro_driver rows, factor_series set)
        │
        ▼
┌─────────────────────────── TagCalibrator (services/tag_calibrator.py) ───────────────────────────┐
│                                                                                                    │
│  Pass 1 (existing) ── measure raw standardized loading per (symbol, tag)                          │
│  Pass 2 (existing) ── one BH-FDR correction over the full p-vector                                │
│  Pass 3 (existing) ── decide keep/expire/discover, write instrument_tags (loading, p_value, ...)  │
│                                                                                                    │
│  Pass 4 (NEW, this phase) ── for every KEPT empirical row:                                        │
│      1. build control-factor return matrix (SPY, TLT, HYG-IEF, UUP [, DBC])                       │
│      2. residualize candidate return + target factor_series return against controls               │
│         (reuse/extend ic_math.partial_spearman_ic's residual-then-correlate shape)                 │
│      3. compute incremental/partial loading + incremental R² from residuals                       │
│      4. sign-stability check across N rolling windows (NEW helper — no existing precedent)         │
│      5. write evidence columns unconditionally (measurement, not gating) + discovery_state         │
│                                                                                                    │
└───────────────────────────────────────┬────────────────────────────────────────────────────────┘
                                          │ writes new instrument_tags columns
                                          ▼
                              instrument_tags (extended schema)
                                          │
                    ┌─────────────────────┴─────────────────────┐
                    │                                            │
                    ▼ (read-only, THIS PHASE)                    ▼ (deferred — separate phase)
     scripts/analysis/<new>_materiality_shadow_diagnostic.py     breadth_vol.py /
     — reports membership DELTA (human-only vs.                  cross_sectional_regime_model.py
       human-OR-materiality-eligible) per group, no writes          live query cutover
                                          │
                                          ▼
                              null-arm validation (offline, same script or sibling):
                              circular-shift factor_series proxy N=1000x,
                              reuse ic_math._circular_shift_null
```

### Recommended Project Structure

```
services/tag_calibrator.py                          # Pass 4 added here (not a new file — D-01)
src/intelligence/statistics/factor_math.py           # candidate home for a new
                                                       # `partial_loading()`/`incremental_r2()`
                                                       # kernel, if Pass 4 needs a
                                                       # Pearson-convention sibling to
                                                       # ic_math.partial_spearman_ic
production/migrations/346_itr_materiality_evidence_columns.sql   # new evidence columns +
                                                                   # discovery_state promotion
                                                                   # (next available number
                                                                   # after 345 — verify at
                                                                   # plan time)
scripts/analysis/itr_materiality_shadow_diagnostic.py   # NEW — shadow-mode membership diff
                                                          # + null-arm validation report
tests/unit/test_tag_calibrator.py                    # extend with Pass 4 unit tests
                                                       # (pure functions, no DB — matches
                                                       # existing test file's style)
```

### Pattern 1: Reuse `partial_spearman_ic`'s residualize-then-correlate shape

**What:** `ic_math.partial_spearman_ic(x, y, controls, condition_max)` already regresses
rank-transformed `x` and `y` on rank-transformed `controls` via one shared `np.linalg.lstsq`
call, then correlates the two residual vectors — literally "orthogonalize against a control
set, then measure the incremental relationship," which is what all three reviewers (Codex/
Fable/AGY) described independently for Pass 4.

**When to use:** As the direct implementation, or as the template to copy if Pass 4 needs a
Pearson/standardized-loading convention instead of Spearman (see Open Questions — Pass 1's
existing `loading_threshold`/`weight` semantics are Pearson-based, so a straight
`partial_spearman_ic` call would introduce a second, incompatible loading convention onto the
same `instrument_tags` row unless the new evidence columns are named/typed distinctly, e.g.
`partial_loading` vs. the existing `loading`).

**Example:**
```python
# Source: src/intelligence/statistics/ic_math.py:703-762 (existing, read in full during research)
def partial_spearman_ic(
    x: np.ndarray, y: np.ndarray, controls: np.ndarray, condition_max: float,
) -> tuple[float, float, int]:
    # ranks_x, ranks_y, ranks_controls = rankdata(...) each
    # center all three
    # check_condition_number(ranks_controls_c, condition_max) -- reuse this gate verbatim
    # coefs, *_ = np.linalg.lstsq(ranks_controls_c, np.column_stack([ranks_x_c, ranks_y_c]))
    # residual_x = ranks_x_c - ranks_controls_c @ coefs[:, 0]
    # residual_y = ranks_y_c - ranks_controls_c @ coefs[:, 1]
    # partial_ic = _vectorized_ic(residual_x, residual_y)  (Pearson corr of residuals)
    ...
```
A Pearson-convention sibling (if chosen) would be nearly identical but skip the `rankdata()`
calls — center and residualize raw standardized returns instead of ranks, matching
`standardized_loading`'s existing convention (`cov(x,y)/(std_x*std_y)`, clipped to [-1,1]).

### Pattern 2: Control-factor set — reuse existing `factor_series` proxies, don't invent new ones

**What:** Every control-factor Codex/AGY named already has a live, working, currently-
measured `tag_vocabulary.factor_series` proxy in this corpus:

| Control concept | Existing tag | `factor_series` | Construction |
|---|---|---|---|
| Broad equity/market beta | `equity_beta` | `SPY` | single-symbol log-return |
| Rates | `rate_sensitive` | `TLT` | single-symbol log-return |
| Credit | `credit_risk` | `HYG-IEF` | long-short spread return (`long_short_daily_returns`) |
| Dollar | `dollar_strength` | `UUP` | single-symbol log-return |
| Commodity broad | **none exists** | — | `commodity_broad` is `measurement_type='definitional'`, no `factor_series` set; `DBC` (compute_eligible, live in Phase 174's cross-asset basket per `.planning/STATE.md`) is the natural unwired proxy if a commodity control leg proves necessary |

**When to use:** Build the control-factor return matrix for Pass 4 by reusing
`build_factor_series_cache()` (already generic over any `factor_series` string — single
symbol, hyphenated long-short spread, or the vol sentinel) rather than writing a second,
parallel factor-series constructor. This is the same "don't re-derive, reuse the existing
single-source-of-truth construction" discipline the module's own docstring calls out for
`compute_factor_correlations()`.

**Anti-pattern to avoid:** Hardcoding `SPY`/`TLT`/`HYG-IEF`/`UUP` as raw price fetches inside
the new Pass 4 code, bypassing `_build_factor_return_series`/`build_factor_series_cache`. This
would duplicate factor-series construction logic and risk drift (the exact E12-class bug this
module's docstrings already warn about).

### Pattern 3: Reuse `_circular_shift_null` for D-06, matching `tsmom_per_symbol_ic_screen.py` exactly

**What:** `ic_math._circular_shift_null(Y, rng)` shifts a series by a random offset in
`[1, len(Y)-1]`, preserving `Y`'s own autocorrelation while destroying alignment with any
paired `X`. `tsmom_per_symbol_ic_screen.py` already uses this pattern for its own per-symbol
null (N=1000 draws, `rng = np.random.default_rng(hash_key_to_int(...))` for a deterministic
seed, BH-FDR applied per symbol family).

**When to use:** For D-06, shift the `factor_series` proxy's OWN return series (never the
candidate instrument's return, never a symbol-shuffle) N times, recompute the partial loading
against each shifted draw, and derive a null p-value the same way
`tsmom_per_symbol_ic_screen.py` does: `p = (1 + sum(null_draws >= observed)) / (N + 1)`.

**Example:**
```python
# Source: scripts/analysis/tsmom_per_symbol_ic_screen.py:58-88 (existing, read in full)
from src.core.rng import hash_key_to_int
from src.intelligence.statistics.ic_math import _circular_shift_null, apply_bh_fdr

rng = np.random.default_rng(hash_key_to_int(f"{_SCREEN_NAME}_null"))
null_draws = np.empty(_N_NULL)
for i in range(_N_NULL):
    y_shift = _circular_shift_null(factor_ret, rng)   # shift the FACTOR proxy (D-06), not
                                                        # the candidate's own return series
    null_draws[i] = <recompute partial loading with y_shift in place of factor_ret>
p = (1 + int((null_draws >= observed).sum())) / (len(null_draws) + 1)
```

### Pattern 4: New evidence columns via a `weight`-shaped migration, following migration 230's precedent

**What:** Migration 230 (`230_tag_calibrator_measurement_contract.sql`) added
`loading`/`p_value`/`bh_adjusted_p`/`passes_fdr`/`consecutive_fails`/`sample_n`/`estimated_at`/
`valid_from`/`valid_to` to `instrument_tags` via one `ALTER TABLE ... ADD COLUMN IF NOT
EXISTS` block, idempotent, wrapped in `BEGIN`/`COMMIT`.

**When to use:** Follow the identical shape for the new Pass 4 columns. Proposed column set
(names/types are Claude's discretion per CONTEXT.md — this is a starting proposal for the
planner, not a lock):

| Column | Type | Purpose |
|---|---|---|
| `partial_loading` | `float` | The orthogonalized/incremental loading (distinct from existing raw `loading`) |
| `incremental_r2` | `float` | Partial R² attributable to the target factor after controlling for the control set |
| `sign_stable_windows` | `int` | Count of rolling windows (out of N) where `partial_loading`'s sign matched the full-sample sign |
| `sign_stable_windows_total` | `int` | N — the denominator, so the ratio is self-documenting without a second APR lookup |
| `null_arm_p_value` | `float` | p-value from the D-06 circular-shift null (NULL until the null-arm script has run for this pair — see Open Questions on whether Pass 4 runs the null arm inline or as a separate offline step) |
| `passes_materiality` | `boolean` | The boolean/threshold outcome column D-01/D-02 call for — computed from `partial_loading`/`incremental_r2`/`sign_stable_windows`/`null_arm_p_value` against the seeded APR bar |
| `discovery_state` | `text CHECK (discovery_state IN ('pending_oos','confirmed'))` | **Todo 125 fold-in**: promotes the existing JSONB-only `evidence.discovery_state` to a real, constrained column — matches todo 125's own addendum recommendation ("prefer promoting ... to real `instrument_tags` columns ... rather than leaving the same state machine split across a typed-column half and an untyped-JSONB half") |
| `first_measured_at` | `timestamptz` | **Todo 125 fold-in**: promotes `evidence.first_measured_at` alongside `discovery_state`, same rationale |

Follow-up write-path change: `_next_evidence`/`_apply_decision` must write these two promoted
columns directly (not just inside the JSONB `evidence` blob) — keep the JSONB write too for
backward read compatibility unless a full sweep confirms nothing else reads
`evidence.discovery_state`/`evidence.first_measured_at` (confirmed via `grep -rn
"discovery_state" src/ services/` in the original todo — only the write site existed at time
of filing; re-verify at plan time since this phase adds new code that will also touch it).

### Pattern 5: `instrument_tags_active` view — todo 126 fold-in

**What:** Todo 126 proposed (never built — confirmed via `grep -rn instrument_tags_active`
returning zero hits) a canonical `SELECT ... FROM instrument_tags WHERE valid_to IS NULL`
view as the required read path for any tag-membership query.

**When to use:** This phase is the first concrete consumer of empirical
`sensitivity`/`macro_driver` tags in a load-bearing way (per CONTEXT.md's own framing), so
build this view now rather than deferring again. The shadow-mode diagnostic (P175-03) should
read through it, establishing the pattern before any future consumer cutover phase needs it.

```sql
-- Proposed, following migration 230's idempotent style
CREATE OR REPLACE VIEW instrument_tags_active AS
SELECT * FROM instrument_tags WHERE valid_to IS NULL;
```

### Anti-Patterns to Avoid

- **Computing the orthogonalization inside `breadth_vol.py` or `cross_sectional_regime_model.py`:** explicitly rejected by D-01 — breaks the consumer-is-a-dumb-reader-of-decided-state pattern every other governance registry (APR, ITR's own existing tags, ConceptRegistry, VocabularyService) in this codebase follows.
- **Using `passes_fdr` alone, or raw (non-orthogonalized) `loading` magnitude alone, as the materiality gate:** this is precisely the failure mode the `ic_engine.py` routing bug already proved insufficient at n=250+ (common-beta noise clears significance trivially) — the whole point of Pass 4 is the orthogonalization step, not a stricter version of the same test.
- **Symbol-shuffle or candidate-return-shift as the null arm:** explicitly rejected by D-06 — either destroys the exact relationship (market-beta control) the filter needs to preserve while breaking the temporal candidate-to-factor link.
- **Writing a second, parallel factor-series constructor for the control set:** reuse `build_factor_series_cache`/`_build_factor_return_series` — this module's own docstrings already flag the E12-class drift risk of a sibling script re-deriving the same spreads independently.
- **Changing either consumer's live `_load_tags_by_symbol`/breadth query in this phase:** explicitly deferred by D-03 — this phase writes evidence and a diagnostic only.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Orthogonalize candidate against a control-factor design matrix | A fresh multi-factor `statsmodels.OLS` or manual normal-equations solve | `ic_math.partial_spearman_ic`'s residualize-via-shared-`lstsq`-then-correlate shape (adapt to Pearson convention if needed) | Already handles centering, the shared-design-matrix `lstsq` optimization, the `check_condition_number` ill-conditioning gate, and the reduced-df p-value — re-deriving any of these risks a silent numerical-stability regression |
| BH-FDR correction over the Pass 4 p-vector | A second `multipletests` call site | `ic_math.apply_bh_fdr` (already imported in `tag_calibrator.py`) | Run-level-once discipline (F1) already enforced there; a second independent correction call risks running FDR per-hypothesis by accident, which CLAUDE.md-adjacent module docstrings explicitly warn against |
| Circular-shift null-arm mechanics | A new random-offset roll implementation | `ic_math._circular_shift_null` | Already used for the identical purpose in `tsmom_per_symbol_ic_screen.py`; reimplementing risks a subtly different offset range or wrap behavior |
| Ill-conditioning guard on the control design matrix | A new condition-number check | `ic_math.check_condition_number` | Shared gate used by both `mean_variance_weights()` and `partial_spearman_ic()` already — same class of estimated-matrix risk |
| Factor-series (control leg) price/return construction | Direct `market_data_ohlcv_tradeable` queries inside Pass 4 | `build_factor_series_cache()` / `_build_factor_return_series()` | Already handles single-symbol, long-short-spread, and vol-sentinel construction uniformly; a second constructor risks drift (E12-class bug precedent) |

**Key insight:** This phase's statistical core (orthogonalize, correct once, gate, null-arm
validate) is not new territory for this codebase — every primitive it needs already exists
somewhere in `ic_math.py`/`factor_math.py`/`tag_calibrator.py` or as an established script
pattern. The actual new work is (1) wiring these primitives together as Pass 4, (2) the
sign-stability-across-rolling-windows check (genuinely new, no precedent found), and
(3) the schema/migration/APR/diagnostic-script plumbing around them.

## Common Pitfalls

### Pitfall 1: Pearson vs. Spearman convention mismatch
**What goes wrong:** `partial_spearman_ic` is rank-based; `TagCalibrator`'s existing Pass 1
(`standardized_loading`, `loading_hac_pvalue`) is Pearson-based on raw (not ranked) returns.
If Pass 4 uses `partial_spearman_ic` directly and writes its result into a column presented
alongside `loading` without clear naming/documentation, a future reader could compare two
loadings computed under different statistical conventions as if they were the same quantity.
**Why it happens:** Both are called "loading"/"correlation" informally; the underlying
transform (rank vs. raw) is easy to lose track of once the numbers are just floats in a table.
**How to avoid:** Name the new column distinctly (`partial_loading`, not `loading_partial` or
anything that reads as a variant of the existing `loading`), and decide explicitly (this is an
Open Question below) whether Pass 4 should instead build a Pearson-convention partial-loading
sibling function to match Pass 1's existing semantics, given `loading_threshold`'s existing
values (0.2 across every measured tag) were calibrated informally against Pearson-style
correlations.
**Warning signs:** A unit test comparing `partial_loading` to `loading` for the same pair
without accounting for the rank transform; a threshold seeded from Codex's `abs(partial_beta)
>= 0.35` (Pearson-flavored language: "beta") applied to a Spearman rank correlation without
adjustment.

### Pitfall 2: Reusing `partial_spearman_ic`'s df-adjustment without checking `k` (control count)
**What goes wrong:** `partial_spearman_ic` reduces degrees of freedom by `k` (control count)
and requires `n >= k + 4`. With 4-5 control factors (SPY, TLT, HYG-IEF, UUP, maybe DBC) plus
this phase's likely-longer lookback for stability checking, `min_sample_n` (currently 60 for
Pass 1) may be too low for a well-conditioned Pass 4 with `k=4` or `5` controls — Codex's own
proposed gate (`sample_n >= 756`) implies awareness of this, roughly 3 years of daily data
rather than the ~60-observation floor Pass 1 tolerates.
**Why it happens:** Pass 1 measures a single bivariate relationship (`k=0` controls); Pass 4
measures a partial relationship with `k=4-5` controls, a structurally different sample-size
requirement.
**How to avoid:** Do not reuse `alpha.tag_calibrator.min_sample_n` (60) for Pass 4's own gate
— seed a distinct `alpha.tag_calibrator.materiality.min_sample_n` APR key at Codex's `756` (or
close to it), per D-05's "seed the conservative number" instruction.
**Warning signs:** Pass 4 measurements passing with `sample_n` in the 60-200 range, which
would be a k=4-5-control partial regression running on barely more observations than
parameters being estimated — the `check_condition_number` gate may catch some of this, but a
sample-size floor is the more direct, interpretable guard.

### Pitfall 3: Sign-stability-across-rolling-windows has no existing implementation to reuse
**What goes wrong:** Codex's proposed gate ("sign-stable in >= 3 of 4 rolling 252-day
windows") requires re-running the partial-loading computation on 4 distinct historical
windows and checking sign agreement — a genuinely new capability, not found anywhere in
`ic_math.py`, `factor_math.py`, or any `scripts/analysis/*.py` rolling-window pattern searched
during this research.
**Why it happens:** Every existing rolling-window-shaped computation in this codebase
(`regime_writer.py`'s per-bar HMM smoothing, `breadth_vol.py`'s causal expanding rank) is a
per-bar streaming computation, not a "split history into N disjoint or overlapping windows,
recompute a summary statistic per window" pattern.
**How to avoid:** Budget real implementation time for this — it is not a reuse, it is new
code. A straightforward approach: split the available history into N (Codex: 4) windows of
`W` (Codex: 252) trading days each (either disjoint tail-anchored windows or a rolling stride),
recompute `partial_loading` on each window's data independently, and count sign agreement with
the full-sample sign.
**Warning signs:** A plan that treats this as "just call an existing function N times" without
accounting for how windows are defined (disjoint vs. overlapping vs. anchored-to-present) or
what happens when a window has insufficient data for the `k+4`/`min_sample_n` floor (a partial
window near the start of a shorter-history instrument's data).

### Pitfall 4: `discovery_oos_days` enforcement interacting with the materiality gate's own timing
**What goes wrong:** Todo 125's fold-in requires a newly-discovered empirical tag to not be
materiality-eligible until `discovery_oos_days` (63) have elapsed. But Pass 4's own
`partial_loading` measurement needs its own sample-size floor (Pitfall 2, likely ~3 years of
data) to be well-conditioned in the first place — these are two independent gates
(data-sufficiency for the partial regression vs. OOS-confirmation of the discovery itself)
that could be conflated into one check by mistake.
**Why it happens:** Both gates ultimately produce a boolean "is this row trustworthy yet,"
inviting a shortcut of merging them.
**How to avoid:** Keep `passes_materiality` (statistical gate: does the partial loading clear
the threshold with sufficient sample/stability/null-arm evidence) and `discovery_state`
(temporal gate: has this specific row survived `discovery_oos_days` since first measured)
as two independent, AND-ed conditions at read time — never fold OOS-day counting into the
statistical threshold itself.
**Warning signs:** A `passes_materiality` boolean that changes value purely because
`discovery_oos_days` elapsed, with no new measurement having run — this would indicate the two
gates got merged.

### Pitfall 5: `valid_to` filtering omitted from the new diagnostic (todo 126 fold-in)
**What goes wrong:** The shadow-mode diagnostic script reads `instrument_tags` without
`WHERE valid_to IS NULL`, silently counting expired empirical rows toward the "what would
change" membership delta — producing a diagnostic result the eventual cutover phase can't
trust.
**Why it happens:** None of the three existing live readers (`ic_engine.py`,
`breadth_vol.py`'s predecessor, `cross_sectional_regime_model.py`) currently filter on
`valid_to` either — there's no existing call site to copy the filter from by example; it has
to be added deliberately.
**How to avoid:** Route the diagnostic (and any future consumer cutover) through the new
`instrument_tags_active` view (Pattern 5) rather than querying `instrument_tags` directly.
**Warning signs:** A diagnostic query with a bare `FROM instrument_tags` and no
`valid_to`/`instrument_tags_active` reference anywhere in the file.

## Runtime State Inventory

> Not applicable — this phase is not a rename/refactor/migration phase. It adds new schema
> (additive migration, `ADD COLUMN IF NOT EXISTS`) and new code; it does not rename or move any
> existing runtime state. Skipped per the trigger condition in the research protocol.

## Code Examples

### Existing Pass 1-3 structure to extend (read in full before planning)

```python
# Source: services/tag_calibrator.py:432-500 (measure_matrix, Pass 1)
def measure_matrix(
    active_symbols: list[str],
    measurable_rows: list[dict[str, Any]],
    price_cache: dict[str, pd.Series],
    config: TagCalibratorConfig,
    condition_max: float,
    realized_vol_window: int,
    vix_z_window: int,
) -> tuple[list[dict[str, Any]], int, int]:
    # ... builds factor_series_cache once per unique factor_series (reuse target)
    # ... builds instrument_ret_cache once per (symbol, lookback_days)
    # ... calls _measure_pair(instrument_ret, factor_ret, ...) per (symbol, tag)
```

A Pass 4 function would follow the identical shape: iterate `measured` (the output of Pass 1,
already filtered to `keep=True` empirical pairs in the `execute()` loop), build a control
return matrix once (reusing `build_factor_series_cache` with the 4-5 control tags' own
`factor_series` values), and compute the partial loading per pair.

### Existing APR-seeding migration pattern (copy this shape exactly)

```sql
-- Source: production/migrations/342_universe_pilot_sample_size_apr_key.sql (existing, full text read)
INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description) VALUES
(
    'alpha.tag_calibrator.materiality.min_partial_loading',
    'float',
    '0.35',
    0.0, 1.0,
    '[initial_estimate] Phase 175 D-05: most conservative of three reviewers'' proposed '
    'materiality gates (Codex: 0.35, AGY: 0.30) -- not empirically re-derived against this '
    'corpus''s actual partial-loading distribution. See docs/foundation/apr-calibration-backlog.md.'
)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version) VALUES
('alpha.tag_calibrator.materiality.min_partial_loading', '0.35', 1)
ON CONFLICT (config_key) DO NOTHING;
```

Repeat this pattern for each new APR key: `min_sample_n` (756), `min_incremental_r2` (0.05),
`min_sign_stable_windows` (3 of 4), `min_null_arm_significance` (project's standing
`fdr_alpha`=0.05, unless a dedicated key is preferred for clarity).

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|---------------|--------|
| `source='human'`-only filter for `breadth_vol.py`/`cross_sectional_regime_model.py` (todo 379 stopgap) | Materiality-filtered `source='empirical'` rows admitted alongside `source='human'` (this phase, shadow-mode first) | Todo 379 shipped 2026-09-17 (commit `d1ce8d6bb`); this phase designs the successor | Re-admits real empirical sensitivity signal the stopgap currently discards entirely — but only in shadow mode this phase, not live |
| `passes_fdr`-alone significance gate | Orthogonalized/partial loading vs. a control-factor set | This phase (new Pass 4) | Addresses the `ic_engine.py` routing bug's own finding: raw significance does not separate signal from common-beta noise at n=250+ |
| `discovery_state` computed but never enforced (todo 125) | `discovery_state` promoted to a real column, AND-ed into `passes_materiality` eligibility | This phase (todo 125 fold-in) | First load-bearing consumer of the OOS-pending state |
| No `valid_to` filtering contract anywhere (todo 126) | `instrument_tags_active` view established as the required read path | This phase (todo 126 fold-in) | First enforcement point; sets the pattern for future consumers |

**Deprecated/outdated:** None — this is additive work on a live, current system (`TagCalibrator`
has been the empirical measurement engine since Phase 146, 2026-07-17; no predecessor to
retire).

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `partial_spearman_ic` is the right reuse target rather than writing a fresh multi-factor Pearson OLS from scratch | Pattern 1, Don't Hand-Roll | If the planner decides Pearson convention must match Pass 1 exactly, a new sibling function is needed (still reusing `check_condition_number`/`lstsq` shape) — moderate rework, not a wrong direction, but changes the specific function signature the plan should target |
| A2 | DBC is an adequate/available commodity-broad control proxy if one is needed | Pattern 2 | If DBC's data history or liquidity profile doesn't suit a control leg, the control set may need to ship without a commodity leg, or use a different proxy — low risk, this is presented as "if needed," not required |
| A3 | Codex's proposed numbers (`sample_n>=756`, `|partial_beta|>=0.35`, `incremental R2>=0.05`, sign-stable 3/4 windows, `abs(partial_beta) lower-CI > 0.20`) are in fact the most conservative of the three reviewers' proposals, as D-05 instructs seeding | Code Examples, Pitfall 2 | This claim is taken from CONTEXT.md/todo 380's own framing, not independently re-derived in this research session — if a planner or reviewer disagrees on which set is "most conservative" per-parameter (e.g. AGY's asset-class-prior constraint might be stricter on a different axis), the seeded defaults should be revisited before migration authoring |
| A4 | No existing rolling-window sign-stability helper exists anywhere in this codebase | Pitfall 3 | Based on a targeted grep/read of `ic_math.py`, `factor_math.py`, and `scripts/analysis/` during this session, not an exhaustive repo-wide audit — if a planner finds a precedent this research missed, prefer reusing it |
| A5 | The next available migration number is 346 (current highest is 345) | Recommended Project Structure | Migration numbering could advance between research and plan-time if another phase lands first — planner must re-check `ls production/migrations/ | tail -1` before authoring the migration file, not trust this number |

**If this table is empty:** N/A — see rows above.

## Open Questions (RESOLVED)

All three were resolved during planning. Each carries an inline `RESOLVED:` pointer to the plan and resolution ID that closed it. The resolutions themselves are subject to the P175-08 / D-07 cross-AI review gate documented in 175-05-PLAN.md, which must clear before Wave 1 executes.

1. **Pearson vs. Spearman convention for the new `partial_loading` column**
   - RESOLVED: Pearson, on centered raw returns, via a new `factor_math.py` sibling to `partial_spearman_ic` rather than reuse of the rank-based function. See plan 02 (175-02-PLAN.md) resolution R-01.
   - What we know: `partial_spearman_ic` (rank-based) exists and directly implements the
     orthogonalize-then-correlate shape; Pass 1's existing `standardized_loading` (raw/Pearson)
     is what `loading_threshold=0.2` was informally calibrated against for every currently-live
     measured tag.
   - What's unclear: Whether Codex's `abs(partial_beta) >= 0.35` number was conceived as a
     Pearson-style standardized beta or a rank correlation — the todo's language ("partial
     coefficient," "partial-R²") reads more naturally as an OLS beta (Pearson-flavored) than a
     Spearman rank correlation.
   - Recommendation: Planner should have the eventual PLAN.md explicitly pick one convention
     and, if Pearson is chosen, scope a small new `factor_math.py` function (Pearson-flavored
     sibling to `partial_spearman_ic`, reusing `check_condition_number`/the shared-`lstsq`
     trick but operating on centered raw returns instead of ranks) rather than silently reusing
     the rank-based function under a name that implies Pearson semantics. This is exactly the
     kind of ambiguous, hard statistical-design question D-07 flags for Fable's review.

2. **Does Pass 4 run inline in `TagCalibrator.execute()` or as an offline follow-up pass?**
   - RESOLVED: inline. The whole of Pass 4, null arm included, runs inside `TagCalibrator.execute()`; this recommendation was overridden. See plan 03 (175-03-PLAN.md) resolution R-02, and the override note on the Architectural Responsibility Map above.
   - What we know: D-01 says "4th pass" inside `TagCalibrator` — implying inline, same run.
     But the sign-stability check (Pitfall 3) needs N re-computations per pair on historical
     windows, and the null-arm check (D-06) needs N=1000 circular-shift draws per pair — both
     potentially expensive if run for every one of the corpus's empirical rows on every
     `TagCalibrator` run (which has no systemd timer, run manually/via ops batch cadence per
     the ITR doc).
   - What's unclear: Whether the null-arm validation specifically should run inline (writing
     `null_arm_p_value` every run) or as a separate, less-frequent offline validation script
     (matching where `tsmom_per_symbol_ic_screen.py`'s own null-arm lives — a read-only
     `scripts/analysis/` script, not inside a production batch job).
   - Recommendation: Given `tsmom_per_symbol_ic_screen.py`'s own null-arm is offline/read-only
     (not baked into a production writer), and the shadow-mode diagnostic (P175-03) is already
     scoped as a separate offline script, the planner should consider putting the null-arm
     validation there too rather than inside `TagCalibrator.execute()` itself — keeping the
     inline Pass 4 cheap (partial loading + incremental R² + sign-stability, all deterministic
     closed-form-ish computations) and the null-arm's Monte-Carlo cost in the offline
     diagnostic/validation script, written back to `null_arm_p_value` as a periodic refresh
     rather than every run. This needs explicit resolution in the plan, not left implicit.

3. **How many control factors, and does the commodity leg matter in practice?**
   - RESOLVED: four legs only (SPY, TLT, HYG-IEF, UUP), no DBC, stored as the `control_factor_series` APR JSON behavioral list so a fifth leg is an APR edit rather than a code change. See plan 01 (175-01-PLAN.md) resolution R-03.
   - What we know: SPY/TLT/HYG-IEF/UUP are wired and available; commodity broad has no
     `factor_series` proxy today.
   - What's unclear: Whether omitting a commodity control leg materially changes results for
     the specific empirical tags this phase cares about (equity breadth and peer-group
     resolution for equity/rates/commodity/fx groups) — commodity-tagged symbols specifically
     might need the commodity control leg to avoid false-positive equity/rates/fx materiality
     from shared commodity-cycle co-movement.
   - Recommendation: Start with the 4 wired proxies (SPY/TLT/HYG-IEF/UUP); if the shadow-mode
     diagnostic surfaces commodity-tagged symbols being materiality-flagged for a non-commodity
     group in a way that looks like commodity-cycle confounding rather than genuine signal, add
     DBC as a 5th control leg before trusting that specific result — this is exactly the kind
     of finding the shadow-mode-first discipline (D-03) exists to catch before cutover.

## Environment Availability

> Skipped — this phase has no external tool/service dependencies beyond the already-running
> PostgreSQL/TimescaleDB instance and the project's existing Python environment (numpy, pandas,
> statsmodels, asyncpg — all already installed and in active use by `tag_calibrator.py` and its
> imports, confirmed via direct `grep`/read of the live file during this research session).

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 9.1.1 (confirmed via `pytest.ini`) |
| Config file | `pytest.ini` (project root) |
| Quick run command | `.venv/bin/pytest tests/unit/test_tag_calibrator.py -x -q` |
| Full suite command | `.venv/bin/pytest tests/unit/ -q` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| P175-01 | Pass 4 computes a partial loading for a known synthetic (candidate, controls) pair matching a hand-derivable value | unit | `pytest tests/unit/test_tag_calibrator.py::test_partial_loading_known_value -x` | ❌ Wave 0 (new test, pattern matches existing `test_compute_factor_correlations_known_correlation_value`) |
| P175-01 | Self-regression / degenerate-control guards (reuse `check_condition_number`) return NaN, never crash | unit | `pytest tests/unit/test_tag_calibrator.py::test_pass4_ill_conditioned_controls_returns_nan -x` | ❌ Wave 0 |
| P175-02 | Migration adds new columns idempotently (`ADD COLUMN IF NOT EXISTS`), safe to re-run | integration (requires_db) | Manual `psql -f production/migrations/<N>_....sql` re-run twice, assert no error — matches existing project convention (no automated migration test harness found for prior migrations) | N/A — no existing migration test pattern in this codebase to extend |
| P175-04 | New APR keys resolve via `ConfigService.get_sync`/`get` at their seeded `[initial_estimate]` defaults | unit | `pytest tests/unit/test_config_service.py -k materiality -x` (or add a targeted assertion in `test_tag_calibrator.py`'s existing `TagCalibratorConfig.from_apr` coverage) | ❌ Wave 0 (extend existing `from_apr` test pattern, no dedicated file found for APR-key-presence tests) |
| P175-05 | Circular-shift null-arm p-value computed correctly on a known synthetic series (matches `tsmom_per_symbol_ic_screen.py`'s own validation shape) | unit | `pytest tests/unit/test_tag_calibrator.py::test_null_arm_p_value -x` (or a new `tests/unit/test_itr_materiality_shadow_diagnostic.py` if the null-arm logic lives in the diagnostic script per Open Question 2) | ❌ Wave 0 |
| P175-06 | A freshly-discovered empirical row is NOT `passes_materiality`-eligible until `discovery_oos_days` elapsed, independent of its statistical gate passing | unit | `pytest tests/unit/test_tag_calibrator.py::test_discovery_oos_gate_blocks_fresh_discovery -x` | ❌ Wave 0 — this is the exact test the original todo 125 said was missing ("Add a test asserting a fresh discovery does NOT reach the same state ... until elapsed days actually clear the gate — none of the existing test_tag_calibrator.py tests cover this path") |
| P175-07 | Shadow diagnostic excludes `valid_to IS NOT NULL` rows from its membership delta | unit/integration | New test against `instrument_tags_active` view or the diagnostic's own query-building function | ❌ Wave 0 |
| P175-03 | Shadow diagnostic is read-only — no `INSERT`/`UPDATE`/`DELETE` against `market_regimes` or any consumer table | integration (requires_db) or a static grep-based check | Manual review / `grep -n "INSERT\|UPDATE\|DELETE" scripts/analysis/itr_materiality_shadow_diagnostic.py` asserting zero matches outside a comment | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** `.venv/bin/pytest tests/unit/test_tag_calibrator.py -x -q`
- **Per wave merge:** `.venv/bin/pytest tests/unit/ -q`
- **Phase gate:** Full suite green before `/gsd:verify-work`; additionally, the shadow-mode
  diagnostic's actual output (run against live/corpus data, not just unit-tested) must be
  reviewed by the user + cross-AI (D-03, D-07) before this phase is considered complete — this
  is a human/cross-AI review gate, not an automatable test.

### Wave 0 Gaps
- [ ] `tests/unit/test_tag_calibrator.py` — extend with Pass 4 unit tests (partial loading,
      ill-conditioning guard, discovery-OOS gate enforcement) — file exists, needs new test
      functions, not a new file.
- [ ] `tests/unit/test_itr_materiality_shadow_diagnostic.py` — new file if the diagnostic
      script's logic (membership delta, null-arm) is substantial enough to warrant its own
      pure-function unit tests separate from `test_tag_calibrator.py` (recommended, matching
      this project's convention of one test file per production module).
- [ ] No dedicated migration-test harness exists in this codebase for any prior migration
      (230, 342, 343 all reviewed — none have an accompanying automated test) — this phase
      should not invent one; manual idempotency verification (re-run twice) matches existing
      project practice.

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | No | Internal batch job, no auth surface |
| V3 Session Management | No | N/A |
| V4 Access Control | No | N/A — no new API endpoint or user-facing surface this phase |
| V5 Input Validation | Yes (narrow) | APR-key values are read via `ConfigService`'s existing typed schema (`config_schema.value_type`/`min_value`/`max_value` CHECK constraints) — no free-form user input enters this phase's code path; the only "input" is corpus price data already validated by the existing `market_data_ohlcv_tradeable` view contract |
| V6 Cryptography | No | N/A |

### Known Threat Patterns for this stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Malformed/out-of-range APR value silently degrading a statistical gate (e.g. a negative `min_sample_n`) | Tampering (of config, not of code) | `config_schema`'s existing `min_value`/`max_value` CHECK constraints, set at migration time for every new key (see Code Examples' migration template) |
| A migration applied live via `psql -f` without being committed to git (CLAUDE.md's own standing warning: "A migration applied live via psql -f has no forcing function to get committed") | Repudiation (of the actual live schema state vs. what git shows) | Commit the migration file in the same breath as applying it — explicit CLAUDE.md directive, not a new finding for this phase but directly applicable given this phase requires a real migration |

This phase is internal statistical/batch tooling with no external attack surface — the
security domain is narrow by nature (no auth, no network-facing endpoint, no user input).
The one concrete, applicable risk is config/migration integrity, already covered by this
project's existing APR and migration-commit conventions.

## Sources

### Primary (HIGH confidence — direct code read, this session)
- `services/tag_calibrator.py` (full file, 895 lines) — existing Pass 1-3 structure, APR
  config binding, `_apply_decision`/`_next_evidence`/`decide_outcome` machinery.
- `src/intelligence/statistics/factor_math.py` (full file) — `standardized_loading`,
  `loading_hac_pvalue`, `long_short_daily_returns`, `spy_realized_vol_factor`.
- `src/intelligence/statistics/ic_math.py` (targeted reads: `partial_spearman_ic` lines
  703-762+, `apply_bh_fdr` lines 545-560, `check_condition_number` lines 682-696,
  `_circular_shift_null` lines 180-199) — existing reusable statistical primitives.
- `src/intelligence/regime_signals/breadth_vol.py` (full file) — equity breadth consumer,
  causal-rank pattern.
- `services/cross_sectional_regime_model.py` (full file) — peer-group dispatcher,
  `_load_tags_by_symbol` (the todo-379 stopgap's exact filter), `_resolve_group_symbols`.
- `scripts/analysis/tsmom_per_symbol_ic_screen.py` (targeted reads: lines 33-88, 164) —
  existing circular-shift null-arm usage pattern.
- `docs/foundation/instrument-tag-registry.md` (full file) — ITR canonical spec, full
  `instrument_tags`/`tag_vocabulary` schema, Known Gaps section (both folded todos).
- `production/migrations/230_tag_calibrator_measurement_contract.sql`,
  `342_universe_pilot_sample_size_apr_key.sql`, `343_itr_measurement_gap_fixes.sql` — migration
  conventions (idempotent `ADD COLUMN IF NOT EXISTS`, APR-key-seeding
  `config_schema`/`config_state` INSERT pattern).
- `docs/foundation/apr-calibration-backlog.md` (partial read) — confirms
  `alpha.tag_calibrator.*` keys are already flagged `[initial_estimate]`, establishing the
  provenance-tagging convention this phase's new keys must follow.
- `.planning/todos/pending/380-itr-materiality-filtered-empirical-tags-and-eq-prefix-naming-collision.md`,
  `.planning/todos/pending/125-...md`, `.planning/todos/pending/126-...md`,
  `docs/plans/2026-09-17-itr-source-filter-breadth-peer-grouping-design.md` — full design
  record, all three reviewers' original proposals.
- Live DB query (`tag_vocabulary`, full 78-row table) — confirmed exact current
  `factor_series` wiring for every measurable tag, including the four control-factor
  candidates (SPY/TLT/HYG-IEF/UUP) and the commodity-broad gap.
- `tests/unit/test_tag_calibrator.py` (function-name listing only) — existing test coverage
  shape (pure-function unit tests, no DB, matching module's own `measure_matrix`/
  `decide_outcome`/`apply_run_level_fdr` structure).
- `pytest.ini` — test framework/config confirmation.
- `.planning/config.json` — `nyquist_validation: true` (Validation Architecture section
  required), no `security_enforcement: false` override (Security Domain section required).

### Secondary (MEDIUM confidence)
- None — this research relied entirely on direct codebase reads (primary sources); no
  WebSearch/Context7 lookups were needed since every relevant primitive is internal to this
  project, not a third-party library capability.

### Tertiary (LOW confidence)
- None.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — zero new packages, every dependency already pinned and in active use.
- Architecture (reuse targets, migration/APR conventions): HIGH — directly read from live
  source files and live migrations in this session.
- Threshold numbers (D-05's seeded APR values): MEDIUM — sourced from CONTEXT.md/todo 380's
  own framing of "Codex is most conservative," not independently re-derived from the corpus's
  actual partial-loading distribution (D-05 itself acknowledges this is expected — real
  calibration is explicit follow-up work).
- Sign-stability-across-rolling-windows construction: LOW — no existing precedent found in
  this codebase; this is genuinely new implementation work, not a reuse-and-adapt situation.
- Pitfalls: HIGH for the Pearson/Spearman and sample-size pitfalls (directly derived from
  reading the actual function signatures/docstrings); MEDIUM for the discovery/materiality
  gate-interaction pitfall (reasoned from CONTEXT.md's fold-in language, not tested against
  code that doesn't exist yet).

**Research date:** 2026-09-18
**Valid until:** 2026-10-18 (30 days — stable internal codebase, no fast-moving external
dependency; re-verify migration numbering and `tag_vocabulary` state if this research is
reused after other phases land in the interim, since both are live/mutable).
