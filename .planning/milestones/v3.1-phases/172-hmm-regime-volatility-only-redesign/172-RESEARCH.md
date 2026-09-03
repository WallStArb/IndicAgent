# Phase 172: HMM Regime — Volatility-Only Redesign - Research

**Researched:** 2026-08-08
**Domain:** HMM regime labeling (per-symbol, causal), APR/CVR schema migration, downstream IC/ensemble re-wiring
**Confidence:** HIGH (all findings verified against live source in this repo; no external library research needed — this phase touches only project-internal code and schema)

## Summary

Phase 172 has no CONTEXT.md — `171-FINAL-VERDICT.md` (sections 5 and 7) is the locked design
source instead, and its recommendation is unambiguous: ship a new `regime_volatility` label
built from `realized_vol` + `vol_of_vol` only, GaussianHMM K=2 or K=3, honest
`calm`/`elevated`/`turbulent` vocabulary, reusing the already-built-and-tested walk-forward
fitting fix unchanged in its causal logic. ROADMAP.md's Phase 172 entry says
`**Requirements**: TBD` — no requirement IDs exist yet; this research does not fabricate any.

The core finding from reading `services/regime_writer.py` line-by-line: **the walk-forward
fitting mechanics generalize almost for free, but every piece of code downstream of the fit is
hardcoded to a 5-column, trend-vocabulary world.** `_build_obs_matrix` always returns a
`(n, 5)` array; `_build_label_map`/`_state_groups` hardcode the string constants
`trending_up`/`trending_down`/`ranging`/`transition_up`/`transition_down` and the
`_BULLISH_LABELS`/`_BEARISH_LABELS` sets; `_write_regime_results` hardcodes the 8-column
`REGIME_WRITER_OWNED_COLUMN_NAMES` tuple (`regime`, `hmm_prob_trending_up`, `hmm_prob_ranging`,
`hmm_prob_trending_down`, `hmm_regime_prob`, `hmm_entropy`, `hmm_duration`, `hmm_churn`). None
of this is a defect — it is simply built for one column family. Phase 172 needs a **parallel,
not merged**, code path: a new 2-column observation-matrix builder, a label-vocabulary
parameter threaded through `_build_label_map`/`_state_groups` (the underlying rank-by-column-0
logic is directly reusable — low `realized_vol` naturally sorts to `calm`, high to
`turbulent`), and a new output column family (`regime_volatility` + volatility-flavored prob
columns) written by a new `_write_regime_volatility_results`-shaped function.

The bigger risk is not `regime_writer.py` itself — it is the downstream chain that treats
`feature_vectors.regime` as *the* stratification key: `ic_engine.py` (hard startup gate on
`regime IS NOT NULL`, `alpha.regime.groups` routing, `feature_ic_scores.regime` column),
`ensemble_trainer.py` (`ensemble_weights` keyed by `(tf, regime)`, the `regime != '_pooled'`
eligibility filter from CLAUDE.md's Key Decisions), `alpha_publisher.py` (`alpha_events`/
`ensemble_alpha` carry `regime` forward), and `regime_coverage_auditor.py` (gap-detection on
`feature_vectors.regime`). None of these pattern-match specific label *strings* — they treat
`regime` as an opaque GROUP BY key — so swapping in `calm`/`elevated`/`turbulent` values does
not break string-matching logic anywhere found in this codebase (confirmed via grep: the only
files that hardcode trend-label strings outside `regime_writer.py`/its tests are the archived
v2.x `schemas.py` and a dead comment in `feature_vector_pipeline.py`). But the phase still has
to decide, and plan explicitly, whether `regime_volatility` **replaces** what `ic_engine.py`
reads as `feature_vectors.regime`, or becomes an **additional** stratification axis alongside
the existing `regime`/`market_regimes` two-system design documented in `docs/foundation/
glossary.md`'s `regime` entry. FINAL-VERDICT says "retire the composite `regime` column ...
entirely" — that is a rename/cutover of the primary per-symbol regime key, not an additive
column, and it has real blast radius across every file above plus `docs/foundation/
glossary.md`'s `regime` entry (which explicitly documents the 5-label composite as the current
idiosyncratic-regime mechanism and will go stale the moment this ships).

**Primary recommendation:** Build `regime_volatility` as a new, generalized-but-separate code
path inside `regime_writer.py` (parametrized label map + a dedicated 2-column obs-matrix
builder + a dedicated output-column family), skip the legacy full-history `_compute_symbol_tf`
path entirely for this new column (walk-forward is the only method the new column ever needs —
no dual-write blend risk since it is a brand-new column, not an in-place migration of a live
one), run the null-arm validation script (`scripts/analysis/
hmm_production_regime_axes_null_arm_validation.py`, already parametrized by `--symbols`/`--tf`,
no code change needed) at 15m/5m and a larger symbol sample before any corpus write, then treat
the `ic_engine.py`/`ensemble_trainer.py`/`alpha_publisher.py` cutover as its own explicit wave
with its own precondition doc (171-06/07's withdrawn plans are a ready-made template for this
shape of full-corpus rollout).

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Volatility HMM fit + causal decode | Batch/Ring 2 (`services/regime_writer.py`, oneshot) | — | Same as existing `regime` — CPU-bound, ProcessPoolExecutor worker, no async pipeline, DAG-exempt like `backfill_feature_factory.py` |
| APR keys for new obs-matrix window/K/label config | Database / Storage (`config_schema`/`config_state`) | Batch (`ConfigService.get_sync()` reads at `regime_writer.py` startup) | Follows existing APR mandate; no new mechanism needed |
| Controlled vocabulary for `calm`/`elevated`/`turbulent` | Database / Storage (`controlled_vocabulary`/`vocabulary_group`) | API (`VocabularyService`, `/api/vocabulary/{namespace}`) | New namespace, not a repoint of `regime_hmm` (different taxonomy entirely) |
| `feature_vectors.regime_volatility` persistence | Database / Storage (new hypertable columns) | Batch (`_write_regime_volatility_results`, Ring 1 ownership list in `feature_vector_persistence.py`) | Mirrors existing `regime`/`REGIME_WRITER_OWNED_COLUMN_NAMES` pattern exactly |
| IC stratification on the new label | API/Backend (`ic_engine.py`) | Database (`feature_ic_scores.regime` column, `alpha.regime.groups` APR) | Existing stratification machinery is column-agnostic (GROUP BY key), but the *decision* of which column feeds it is a backend/config change, not a DB change |
| Ensemble weight strata | API/Backend (`ensemble_trainer.py`) | Database (`ensemble_weights` keyed `(tf, regime)`) | Downstream of ic_engine's cutover decision — inherits whatever `ic_engine.py` treats as `regime` |
| Null-arm reliability validation | Offline/analysis (`scripts/analysis/*.py`) | — | Pure investigation tooling, no service, no DAG membership — run manually before any corpus write |
| Glossary/doc currency | Docs (`docs/foundation/glossary.md`) | — | Not code, but load-bearing per CLAUDE.md's canonical-docs-standalone rule; must be updated in the same phase, not deferred |

## User Constraints

No CONTEXT.md exists for Phase 172 (`/gsd:discuss-phase` was skipped). The design is locked by
`171-FINAL-VERDICT.md` §5–7 instead, reproduced here as the constraint set the planner must
honor:

### Locked Decisions (from 171-FINAL-VERDICT.md §5)
- Ship `regime_volatility` as a standalone regime built from `realized_vol` + `vol_of_vol`
  **only**. Retire the composite `regime` column and its trend-flavored label vocabulary
  entirely — not a compromise, not deferred.
- Model: GaussianHMM, 2 observation dimensions, `covariance_type=full`, K=2 or K=3 (both
  independently validated by the null-arm control; K=3 recommended to preserve the
  calm/elevated/turbulent framing, unless a wider-scope check finds K=2 meaningfully more
  robust).
- Fitting procedure: reuse `_walk_forward_hmm_full`/`_seed_prior_from_label`/
  `_hmm_seed_stability_check` **unchanged in causal-correctness logic** — point them at a
  2-column observation slice instead of the 5-column composite. Nothing about the fitting
  mechanics was implicated by the investigation.
- Label vocabulary: new, honest naming (e.g. `calm`/`elevated`/`turbulent`) — not a renamed
  trend vocabulary. Needs a controlled-vocabulary entry before shipping (CLAUDE.md Glossary
  discipline).
- Trend (`log_return`, `momentum`) and volume (`rel_volume`): **no regime column at all.** Dead
  on direct null-arm evidence, not deferred to a later phase.
- New candidates found along the way (idiosyncratic-vs-market co-movement, volume-price
  confirmation) land as plain `feature_vectors` columns (todo 281, already filed) — **not**
  regime labels, and **not** in scope for Phase 172.
- K-selection policy going forward (permanent, not phase-scoped): every future HMM regime
  candidate must clear the null-arm block-reliability check before its agreement/kappa numbers
  are trusted at all.

### Claude's Discretion
- Whether `regime_volatility`'s internals are implemented as a fully separate function set or
  as a parametrized generalization of the existing `_build_obs_matrix`/`_build_label_map`/
  `_state_groups` functions (see Architecture Patterns below for the recommendation and why).
- Exact new APR key names/namespace for the volatility observation window and K, and whether
  `vol_window`/`vol_of_vol_window` get dedicated new keys or repoint the existing
  `feature.hmm.vol_window`/`feature.hmm.obs_vol_of_vol_window` keys (see Common Pitfalls —
  window-dependence finding below argues for a fresh, independently-calibrated key rather than
  inheriting the composite model's `vol_window=20` default unexamined).
- Whether `ic_engine.py`/`ensemble_trainer.py`/`alpha_publisher.py` get rewired to read
  `regime_volatility` as their `regime` stratification key in this phase, or whether that
  cutover is sequenced as its own explicit wave/plan with its own precondition gate (171-06/07
  are withdrawn but are a ready template for this).
- Whether the legacy `regime` column and `regime_hmm` CVR namespace get physically dropped, or
  left in place (read-only, historical) once `regime_volatility` is live — FINAL-VERDICT says
  "retire ... entirely" but does not specify DROP COLUMN vs. stop-writing.

### Deferred Ideas (OUT OF SCOPE)
- Idiosyncratic-vs-market co-movement and volume-price confirmation as regime labels — these
  are real, null-arm-validated *signals* per FINAL-VERDICT §3/§4, but explicitly ship as
  `feature_vectors` columns (todo 281) with regime-conversion deferred pending actual IC
  evidence. Do not scope this into Phase 172.
- Any redesign of trend/direction as a regime dimension using a longer-horizon or
  volatility-regime-conditioned measure (FINAL-VERDICT §6: "trend is dead for now, not
  forever... a future attempt should design for this from the start"). Explicitly a future
  phase, not this one.
- Todo 280 (single-name equities silently excluded from `alpha.regime.groups` filters) —
  discovered during the Phase 171 investigation, explicitly unrelated and non-blocking.

## Standard Stack

No new third-party libraries. `GaussianHMM` (`hmmlearn`), `numpy`, `sklearn.preprocessing.StandardScaler`, `psycopg`, `structlog`, `opentelemetry` are all already project dependencies used identically by the existing `regime_writer.py`. No Package Legitimacy Audit is required — this phase installs nothing.

### Alternatives Considered
None — the model family, fitting procedure, and library set are already locked by
FINAL-VERDICT §5 and by what `regime_writer.py` already uses. No alternative HMM libraries or
observation-window strategies were part of this research's scope; they were already
investigated and settled across the four superseded Phase 171 findings docs.

## Architecture Patterns

### System Architecture Diagram

```
market_data_ohlcv_tradeable (realized_vol, vol_of_vol built from close/volume)
        │
        ▼
_fetch_obs_matrix_volatility()  (NEW — 2-column variant of _fetch_obs_matrix)
        │  builds (n, 2) matrix: [realized_vol, vol_of_vol]
        ▼
_walk_forward_hmm_full()  (REUSED UNCHANGED — causal-correctness logic untouched)
        │  per-segment refit on expanding window, seeded by prior segment's LABEL
        ▼
_build_label_map(means, label_vocab=VOLATILITY_VOCAB)  (GENERALIZED — vocab param)
        │  sorts by column 0 = realized_vol ascending: calm → elevated → turbulent
        ▼
_state_groups() / _alpha_history_to_regime_probs()  (GENERALIZED — vocab-driven bucket names)
        │  p_calm / p_elevated / p_turbulent per bar
        ▼
_write_regime_volatility_results()  (NEW — writes regime_volatility + hmm_vol_* columns)
        │
        ▼
feature_vectors.regime_volatility  (NEW hypertable columns, migration TBD)
        │
        ├──▶ ic_engine.py  (cutover decision: does this become the `regime` it stratifies on?)
        │        │
        │        ▼
        │    feature_ic_scores.regime  ──▶ ensemble_trainer.py (ensemble_weights keyed (tf,regime))
        │                                          │
        │                                          ▼
        │                                  alpha_publisher.py (alpha_events/ensemble_alpha)
        │
        └──▶ regime_coverage_auditor.py (gap-detection needs a regime_volatility variant)
```

### Recommended Project Structure
No new files are structurally required — this is a same-file extension of
`services/regime_writer.py`, mirroring how `_compute_symbol_tf_walk_forward` was added
alongside `_compute_symbol_tf` in Phase 171 (todo 248) rather than as a new file. Recommended
new symbols, all in `services/regime_writer.py`:

```
services/regime_writer.py
├── _VOLATILITY_LABEL_VOCAB          # dict or small typed structure: K=2/K=3 → ordered labels
├── _build_obs_matrix_volatility()   # NEW: builds (n,2) [realized_vol, vol_of_vol] only
├── _fetch_obs_matrix_volatility()   # NEW: thin wrapper mirroring _fetch_obs_matrix
├── _build_label_map()               # GENERALIZE: accept a vocab param, default = trend vocab (back-compat)
├── _state_groups()                  # GENERALIZE: accept the vocab's bucket-name mapping
├── _walk_forward_hmm_full()         # REUSE UNCHANGED (already vocab-agnostic — see below)
├── _compute_symbol_tf_volatility_walk_forward()  # NEW: mirrors _compute_symbol_tf_walk_forward
├── _write_regime_volatility_results()            # NEW: mirrors _write_regime_results, new column list
└── main()                            # ADD: --volatility-regime dispatch branch or a second CLI entrypoint
```

```
production/migrations/
└── 307_regime_volatility_apr_and_schema.sql   # next free migration number (307 confirmed free
                                                 # as of this research; re-check at execution time)
```

### Pattern 1: Vocabulary-parametrized label mapping (why `_build_label_map` generalizes almost for free)
**What:** `_build_label_map(means)` currently hardcodes `_LABEL_TRENDING_DOWN`/
`_LABEL_TRENDING_UP`/`_LABEL_RANGING`/`_LABEL_TRANSITION_DOWN`/`_LABEL_TRANSITION_UP` and always
sorts by `means[:, 0]`. For the volatility observation matrix, column 0 should be
`realized_vol` (put it first in the 2-column matrix, matching the existing convention that
column 0 drives label ordering) — ascending sort then naturally gives `calm` (lowest vol) →
`elevated` (middle, K=3 only) → `turbulent` (highest vol), exactly analogous to the existing
`trending_down`→`ranging`→`trending_up` ordering by `log_return`.
**When to use:** This is the shape every future non-trend regime axis will need (FINAL-VERDICT
§5's "K-selection policy going forward" implies more regime axes may come later) — parametrize
now rather than hand-rolling a parallel copy of `_build_label_map`.
**Example (recommended shape, not yet in the codebase):**
```python
# Source: services/regime_writer.py:497 (_build_label_map), generalized
_TREND_VOCAB_K3 = {"low": "trending_down", "mid": "ranging", "high": "trending_up"}
_VOLATILITY_VOCAB_K3 = {"low": "calm", "mid": "elevated", "high": "turbulent"}
_VOLATILITY_VOCAB_K2 = {"low": "calm", "high": "turbulent"}

def _build_label_map(means: np.ndarray, vocab: dict[str, str] | None = None) -> dict[int, str]:
    vocab = vocab or _TREND_VOCAB_K5_DEFAULT  # preserves exact existing behavior when omitted
    ...
```
Existing callers (`_compute_symbol_tf`, `_walk_forward_hmm_full`, `_hmm_seed_stability_check`)
need **zero changes** if the parameter defaults to today's trend vocabulary — this is a
backward-compatible signature extension, not a breaking change.

### Pattern 2: New 2-column observation matrix, not a slice of the 5-column one
**What:** Do not compute the full 5-column `_build_obs_matrix` and then slice columns
`[1, 3]` (realized_vol, vol_of_vol) at the caller. Build a dedicated `(n, 2)` matrix directly —
this avoids the wasted compute of `momentum`/`rel_volume`/`log_return` (rel_volume alone
requires a separate rolling-mean-of-log-volume pass) and, more importantly, avoids ever having
column-index confusion between the two matrices' different semantics.
**When to use:** Always for the volatility path — do not special-case a shared builder.
**Example:**
```python
# Source: services/regime_writer.py:175 (_build_obs_matrix), pattern to follow for the new function
def _build_obs_matrix_volatility(
    timestamps: list, closes: list[float],
    vol_window: int, vol_of_vol_window: int,
) -> tuple[np.ndarray, list]:
    """(n, 2) observation matrix: [realized_vol, vol_of_vol]. Column 0 = realized_vol
    (drives _build_label_map's ascending sort: calm -> elevated -> turbulent)."""
    ...
```

### Pattern 3: Walk-forward-only for the new column — skip the legacy single-fit path entirely
**What:** `_compute_symbol_tf` (the pre-Phase-171 full-history fit) exists for `regime` because
that column already had a live corpus and needed an APR-flagged, reversible rollout
(`alpha.hmm.walk_forward.enabled`, default false). `regime_volatility` is a brand-new column
with no existing corpus to preserve compatibility with — there is no "must not itself change
any existing label" constraint (migration 292's stated reason for defaulting the flag false).
**When to use:** `regime_volatility` should call the walk-forward path unconditionally, with no
config-gated legacy fallback. This removes an entire class of risk (dual-write blending
between two computation methods under one column, which `_compute_symbol_tf_walk_forward`'s own
docstring flags as the reason its precondition must hold).
**Anti-pattern to avoid:** Building a `_compute_symbol_tf_volatility` (full-history, non-causal)
"for symmetry" with the trend path. There is no reason to reintroduce the exact lookahead bug
Phase 171 exists to fix, in a brand-new column that has no legacy behavior to match.

### Anti-Patterns to Avoid
- **Reusing `_BULLISH_LABELS`/`_BEARISH_LABELS` frozensets for volatility bucketing.** These
  names are trend-semantic. `_state_groups()`'s underlying mechanism (map 3 buckets: low-tail
  state(s), middle state(s), high-tail state(s)) is exactly what `p_calm`/`p_elevated`/
  `p_turbulent` needs, but the constant names and the `_alpha_history_to_regime_probs()`
  parameter names (`bullish_states`, `bearish_states`) should not leak trend vocabulary into a
  volatility-only code path — generalize the parameter names too (e.g. `low_states`/
  `mid_states`/`high_states`), not just their values.
- **Writing `regime_volatility` into the existing `feature_vectors.regime` column.** The two
  are different vocabularies and (per FINAL-VERDICT) different validated content — conflating
  them defeats the entire point of the redesign and would corrupt `ic_engine.py`'s existing
  `WHERE regime IS NOT NULL` startup gate semantics mid-migration.
- **Slicing the 5-column obs matrix instead of building a dedicated 2-column one.** See Pattern
  2 — wastes compute and risks column-index bugs.
- **Repointing `feature.hmm.vol_window`/`feature.hmm.obs_vol_of_vol_window` without
  re-examining the value.** FINAL-VERDICT §6 explicitly flags `vol_of_vol`'s margin as
  window-dependent (thin at 20, solid from 60+) — inheriting `vol_window=20` unexamined because
  it's "the existing HMM window" repeats the exact mistake the investigation is correcting for
  (assuming a composite-model default transfers to a differently-validated axis).

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Causal walk-forward HMM refit | A new refit loop for the volatility column | `_walk_forward_hmm_full` (reused unchanged, pointed at the new 2-col matrix) | Already TDD-tested (Phase 171/todo 248), causal-correctness explicitly validated, FINAL-VERDICT explicitly says this logic was never implicated |
| Seed-stability / identifiability check | A new stability check | `_hmm_seed_stability_check` (already generic — takes any `obs_matrix`, `n_components`, `covariance_type`) | Already exists, already used for the K=5→K=3 finding this whole phase is built on |
| Regime-null-arm reliability control | A new scrambled-data validator | `scripts/analysis/hmm_production_regime_axes_null_arm_validation.py` (already parametrized by `--symbols`/`--tf`, already has a `volatility` axis configuration built in) | This exact script produced FINAL-VERDICT's governing table — re-running it at wider scope is a CLI invocation, not new code |
| Controlled-vocabulary registration | A new registry / ad hoc lookup table | `controlled_vocabulary`/`vocabulary_group`/`vocabulary_group_member` via `VocabularyService`, same pattern as migration 233's `regime_hmm` seed | CVR already exists precisely for this: "a symbolic taxonomy needs one namespace, not a hardcoded list" |
| APR key provisioning | Hardcoded window/K constants in `regime_writer.py` | `config_schema`/`config_state` INSERT, same shape as migration 292 | APR mandate; migration 292 is a directly analogous precedent (same file, same phase family, same "not an ML learning target" provenance framing) |

**Key insight:** Every piece of infrastructure this phase needs already exists in this
codebase, built specifically for the trend-vocabulary regime or for the Phase 171
investigation. The actual work is disciplined generalization (thread a vocab parameter) plus
new schema/config rows — not new mechanisms.

## Common Pitfalls

### Pitfall 1: Treating `feature.hmm.vol_window=20` as validated for the volatility-only fit
**What goes wrong:** Shipping `regime_volatility` with the composite model's inherited
`vol_window=20` default, because it's already an APR key and "the volatility axis already
passed" under that window.
**Why it happens:** The null-arm validation that passed used `vol_of_vol_window=20` as its
headline number, but FINAL-VERDICT §6 explicitly notes this margin is thin at 20 and solid from
60+ — the headline PASS was at the weakest tested window, not the strongest.
**How to avoid:** Either (a) run the wider-scope null-arm check (already required by FINAL-VERDICT
§7 for 15m/5m before touching the corpus) with the window as a swept parameter and pick the
value that clears with margin, or (b) explicitly default to a wider window (60+) as the shipped
value and cite the sensitivity finding as the reason, not an unexamined inheritance.
**Warning signs:** A migration that copies `feature.hmm.obs_vol_of_vol_window`'s value (20)
into a new key without a comment referencing this finding.

### Pitfall 2: Assuming `ic_engine.py`'s regime plumbing is a single switch
**What goes wrong:** Planning "swap `regime` for `regime_volatility`" as a one-line column
rename and discovering mid-execution that `alpha.regime.groups` (JSON APR, per-group
`dual_write_symbol_hmm` field), `equity_model_enabled` (cross-sectional `market_regimes`
fallback), `_POOLED_REGIME_SENTINEL`, and the hard `WHERE regime IS NOT NULL` startup gate are
four semi-independent pieces of machinery, not one.
**Why it happens:** `ic_engine.py` is ~6,000 lines with `regime` threaded through it as both a
per-symbol HMM source AND (via `market_regimes`) a cross-sectional source, unified under one
column name in `feature_ic_scores`.
**How to avoid:** Scope the ic_engine cutover as its own explicit plan/wave with its own read
of the relevant ~200-line slice (lines 580–900, 2500–2750, 4600–5050 in the current file were
the sections this research found most load-bearing) before writing any code, not as a
same-plan afterthought to the regime_writer.py change.
**Warning signs:** A plan that lists "update ic_engine.py to use regime_volatility" as a single
task with no sub-breakdown.

### Pitfall 3: Losing the `regime` glossary entry to staleness
**What goes wrong:** `docs/foundation/glossary.md`'s `regime` entry (lines ~75–111) explicitly
documents the 5-label composite as *the* idiosyncratic-regime mechanism today, complete with
"Stored in `feature_vectors.regime`" and the label list. If Phase 172 ships without updating
this doc, it becomes actively wrong (not just stale) the moment `regime_volatility` becomes the
real per-symbol stratification signal.
**Why it happens:** Glossary updates are easy to treat as optional polish rather than a
phase deliverable, especially on a batch/data-engineering phase with no user-facing surface.
**How to avoid:** Add a glossary-update task explicitly to the plan. Per CLAUDE.md's canonical-
docs-standalone rule, this doc must state what/why/alternatives on its own, not point at
`171-FINAL-VERDICT.md`.
**Warning signs:** Phase closes with `git log docs/foundation/glossary.md` showing no touch.

### Pitfall 4: `_hmm_seed_stability_check`/`_walk_forward_hmm_full`'s `label_map`-based grouping breaking silently at K=2
**What goes wrong:** `_build_label_map`'s current logic special-cases `n_components >= 4` for
transition labels and falls through to "extremes get X, everything else is ranging" — at K=2 it
assigns exactly `order[0]` and `order[-1]` (both extremes, no middle). This already works
correctly for K=2 today (verified by reading the function), but a generalized vocab-parametrized
version must preserve this K=2 behavior exactly (`calm`/`turbulent`, no `elevated` state) or
K=2 configurations will crash on a missing vocab key.
**Why it happens:** Refactoring for vocab-parametrization is exactly the kind of change that can
silently drop an edge case that wasn't obviously connected to the refactor's main goal.
**How to avoid:** Extend `test_build_label_map_*` tests (already 5 tests covering K=2/K=3/K=5
edge cases per the current test file) to run against both vocabularies before merging the
generalized function.
**Warning signs:** A K=2 volatility run producing a `KeyError` or unlabeled bars.

## Code Examples

### Existing `_build_label_map` (the function to generalize)
```python
# Source: services/regime_writer.py:497-541
def _build_label_map(means: np.ndarray) -> dict[int, str]:
    n_components = means.shape[0]
    means_ret = means[:, 0]  # log-return dimension
    order = np.argsort(means_ret)  # ascending: [most_neg, ..., most_pos]
    label_map: dict[int, str] = {}
    label_map[int(order[0])] = _LABEL_TRENDING_DOWN
    label_map[int(order[-1])] = _LABEL_TRENDING_UP
    if n_components >= 4:
        label_map[int(order[1])] = _LABEL_TRANSITION_DOWN
        label_map[int(order[-2])] = _LABEL_TRANSITION_UP
    for i in range(n_components):
        if i not in label_map:
            label_map[i] = _LABEL_RANGING
    return label_map
```
For K=2/K=3 (the only two configurations FINAL-VERDICT validates for volatility), the
`n_components >= 4` branch never fires — meaning the generalized function only needs a
2-entry (K=2) or 3-entry (K=3) vocab mapping, no "transition" concept at all. This meaningfully
simplifies the volatility vocab compared to the trend vocab it's modeled on.

### Existing APR-load pattern to extend (migration 292 precedent)
```sql
-- Source: production/migrations/292_hmm_walk_forward_apr.sql (verbatim shape to follow)
INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description) VALUES
(
    'alpha.hmm_volatility.n_components', 'int', '3', 2, 3,
    '[rca_analysis] Phase 172: K for the volatility-only regime HMM (realized_vol, vol_of_vol). '
    'Both K=2 and K=3 cleared the null-arm block-reliability control per 171-FINAL-VERDICT.md '
    'section 3; K=3 preserves the calm/elevated/turbulent framing. Not an ML learning target.'
)
ON CONFLICT (config_key) DO NOTHING;
```

### Existing CVR seed pattern to extend (migration 233 precedent)
```sql
-- Source: production/migrations/233_controlled_vocabulary_seed_namespaces.sql (verbatim shape)
INSERT INTO controlled_vocabulary (namespace, code, label, description, sort_order) VALUES
('regime_volatility', 'calm',      'Calm',      'Lowest realized-vol / vol-of-vol HMM state', 1),
('regime_volatility', 'elevated',  'Elevated',  'Middle realized-vol / vol-of-vol HMM state (K=3 only)', 2),
('regime_volatility', 'turbulent', 'Turbulent', 'Highest realized-vol / vol-of-vol HMM state', 3)
ON CONFLICT (namespace, code) DO NOTHING;
```
Must be a **new namespace**, not a repoint of the existing `regime_hmm` namespace (migration
233) — the codes are entirely different and `regime_hmm`'s existing rows describe the
composite/trend label set that FINAL-VERDICT retires.

### Existing `_write_regime_results` write pattern to mirror
```python
# Source: services/regime_writer.py:1380-1462 — same shape needed for
# _write_regime_volatility_results, new col_types dict, new REGIME_WRITER_OWNED_COLUMN_NAMES-
# style tuple (recommend: REGIME_VOLATILITY_WRITER_OWNED_COLUMN_NAMES in
# feature_vector_persistence.py, Ring 1, same single-source-of-truth pattern the existing
# tuple's own docstring calls out as fixing a prior hand-typed-list-drift incident).
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|---------------|--------|
| `feature_vectors.regime` = 5-column composite (log_return, realized_vol, momentum, vol_of_vol, rel_volume), K=5, trend-flavored labels | `feature_vectors.regime_volatility` = 2-column (realized_vol, vol_of_vol), K=2/K=3, honest vol-tier labels | Phase 171 verdict, 2026-08-08 | Production's `regime` has been a volatility partition wearing trend names since before Phase 171 started — this is a correctness fix, not a new capability |
| Full-history HMM fit (`_compute_symbol_tf`), parameter-level lookahead | Walk-forward expanding-window refit (`_walk_forward_hmm_full`), causal at both parameter-fit and decode level | todo 248 built 2026-08-04, validated as correct-but-not-yet-deployed for `regime`; Phase 172 deploys it fresh for `regime_volatility` | Eliminates the lookahead channel the original `regime` column always had |
| Agreement/kappa identifiability battery alone | Agreement/kappa **plus** null-arm (scrambled-data) block-reliability margin | Discovered mid-Phase-171, 2026-08-08 | Agreement/kappa alone cannot distinguish real regime structure from a 2-state model's tendency to split any smooth series in half — permanent addition to how this project validates any future HMM regime |

**Deprecated/outdated:**
- Trend (`log_return`/`momentum`) and volume (`rel_volume`) as regime dimensions: dead per
  direct null-arm evidence, not deferred. Do not resurrect without a differently-constructed
  feature per FINAL-VERDICT §6's own caveat.
- `171-06-PLAN.md`/`171-07-PLAN.md` (the composite-label full-corpus rollout): formally
  withdrawn (`status: withdrawn` in their own frontmatter) — do not resume as written, but their
  *shape* (precondition doc → NULL-out → refit → `ic_engine --refresh` → verifier →
  todo-reconciliation) is a directly reusable template for Phase 172's own corpus-rollout wave.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Migration 307 is the next free migration number | Recommended Project Structure | Low — trivially re-checked at execution time with `ls production/migrations \| sort -n \| tail -1`; not a design risk |
| A2 | New CVR namespace should be named `regime_volatility` (not e.g. `regime_hmm_volatility`) | Code Examples, Don't Hand-Roll | Low — purely a naming choice, easy to change before the migration ships; does not affect correctness |
| A3 | Column 0 of the new 2-column obs matrix should be `realized_vol` (not `vol_of_vol`) so the existing ascending-sort-by-column-0 convention in `_build_label_map` produces calm→turbulent without inversion | Architecture Patterns, Pattern 1 | Medium — if built with `vol_of_vol` as column 0 instead, the label ordering would still work (it's still a monotonic proxy for "regime intensity") but would silently diverge from this research's stated convention; a code reviewer should confirm which column drives the sort before merging |

**Everything else in this document is `[VERIFIED: codebase]`** — read directly from
`services/regime_writer.py`, `src/intelligence/features/feature_vector_persistence.py`,
`production/migrations/*.sql`, `src/config/vocabulary_drift.py`, `services/ic_engine.py`,
`services/ensemble_trainer.py`, `services/alpha_publisher.py`,
`services/regime_coverage_auditor.py`, `services/service_auditor.py`,
`scripts/analysis/hmm_production_regime_axes_null_arm_validation.py`,
`tests/unit/services/test_regime_writer.py`, and `docs/foundation/glossary.md` in this session —
not training-data knowledge, since this is entirely project-internal code with no external
library surface.

## Open Questions

1. **Does `regime_volatility` replace or supplement `feature_vectors.regime` as the key
   `ic_engine.py` stratifies on?**
   - What we know: FINAL-VERDICT says "retire the composite `regime` column ... entirely."
     `ic_engine.py` has a hard startup gate requiring `feature_vectors.regime IS NOT NULL`
     (line ~1664) that would need updating regardless.
   - What's unclear: Whether "retire" means physically `DROP COLUMN regime` (breaking every
     downstream reader unless they're all updated in the same phase) or means "stop writing
     meaningful values, keep the column for historical/rollback safety." The Roadmap's own
     "Rough shape" step 5 ("downstream re-verification ... any prior analysis citing `regime`
     as a conditioning variable") implies existing analyses need re-pointing, but doesn't say
     whether the old column is dropped.
   - Recommendation: Plan for a phased cutover — keep `regime` column readable (do not drop)
     through at least one full corpus cycle after `regime_volatility` ships, with `ic_engine.py`
     explicitly repointed to read `regime_volatility` as its primary stratification source. Drop
     `regime` (and the `regime_hmm` CVR namespace) as a follow-up cleanup phase once the cutover
     is confirmed stable, not in the same phase that ships the new column. This is exactly the
     "prove edge before production infra" pattern this project already applies elsewhere.

2. **What K does the wider-scope (15m/5m, larger symbol sample) null-arm check actually
   recommend?**
   - What we know: K=2 and K=3 both cleared at the 8–17-symbol, 1d/1h scope tested so far.
     FINAL-VERDICT explicitly flags this as untested at 15m/5m and wider symbol scope — the one
     gate the investigation says not to skip.
   - What's unclear: The actual result. This has to be measured, not assumed, before any
     corpus write — it is Phase 172's own first real work item, not something this research can
     answer in advance.
   - Recommendation: Sequence this as the first execution wave (`--tf 15m 5m --symbols
     <full-or-large-sample>` against `hmm_production_regime_axes_null_arm_validation.py`),
     gating every subsequent wave on its result, exactly as ROADMAP's "Rough shape" already
     specifies.

3. **What is the correctly-calibrated `vol_of_vol_window`?**
   - What we know: FINAL-VERDICT §6 says thin margin at 20, solid from 60+; no specific
     recommended value is given.
   - What's unclear: The exact value to ship, and whether it should vary by timeframe (the way
     `refit_every_bars`/`initial_warmup_bars` already do per-tf in migration 292).
   - Recommendation: Sweep window as part of the wider-scope null-arm check (item 2 above) and
     pick a value with real margin, rather than treating it as a separate, later decision.

## Environment Availability

Skipped — this phase has no external tool/service dependencies beyond what's already running in
this environment (PostgreSQL/TimescaleDB, the existing Python venv with `hmmlearn`/`numpy`/
`sklearn` already installed and used by the live `regime_writer.py`). No new dependency is
introduced.

## Validation Architecture

`workflow.nyquist_validation` is `true` in `.planning/config.json` (absent-defaults-to-enabled
would also apply) — section included per protocol.

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest (`pytest.ini` at repo root, `testpaths = tests`) |
| Config file | `/home/bg/dev/indicagent/pytest.ini` |
| Quick run command | `.venv/bin/pytest tests/unit/services/test_regime_writer.py -q` |
| Full suite command | `.venv/bin/pytest tests/unit/ -v` |

### Phase Requirements → Test Map

No requirement IDs exist yet for Phase 172 (ROADMAP.md states `**Requirements**: TBD`) — this
table maps the ROADMAP's "Rough shape" work items instead, for the planner to convert into real
REQ IDs:

| Work item (ROADMAP "Rough shape") | Behavior | Test Type | Automated Command | File Exists? |
|---|---|---|---|---|
| (1) APR migration + CVR entry | New `config_schema`/`config_state`/`controlled_vocabulary` rows present, `VocabularyDriftAuditor` recognizes the new namespace | unit | `.venv/bin/pytest tests/unit/test_vocabulary_drift.py -q` (verify this file exists; if not, Wave 0 gap) | ❌ Wave 0 — check `tests/unit/` for an existing `vocabulary_drift` test file before assuming |
| (2) Wire walk-forward against 2-col slice | `_build_obs_matrix_volatility` shape, `_build_label_map` vocab-param behavior at K=2/K=3, `_walk_forward_hmm_full` unaffected by the new column count | unit | `.venv/bin/pytest tests/unit/services/test_regime_writer.py -q` | ✅ existing file, needs new tests added (extends 1525-line file's existing 40 tests) |
| (3) Null-arm check at wider scope | Wider-scope reliability margins on real vs. permuted data | manual-only (analysis script, not a pytest-covered behavior — this is empirical research, not a unit-testable code contract) | `python scripts/analysis/hmm_production_regime_axes_null_arm_validation.py --tf 15m 5m --symbols <list>` | N/A — script already exists |
| (4) Full-corpus relabel | `regime_volatility` populated corpus-wide, no NULL gaps beyond expected warmup-prefix bars | integration/manual (matches how `171-06-PLAN.md`'s withdrawn truths were framed — a provenance-verification tool, not a pytest assertion) | Reuse the resumable NULL-out/provenance tool built in `171-03-PLAN.md` if it generalizes, or its pattern | Check `171-03-PLAN.md`'s artifact path before rebuilding |
| (5) Downstream re-verification | `ic_engine.py`/`ensemble_trainer.py` behavior unchanged in kind (still produces `feature_ic_scores`/`ensemble_weights` rows), just keyed on the new label set | integration | `.venv/bin/pytest tests/unit/ -k "ic_engine or ensemble_trainer" -q` plus a real `ic_engine.py --refresh` scoped run | ✅ existing tests exist for both modules; extend, don't replace |

### Sampling Rate
- **Per task commit:** `.venv/bin/pytest tests/unit/services/test_regime_writer.py -q`
- **Per wave merge:** `.venv/bin/pytest tests/unit/ -v`
- **Phase gate:** Full suite green before `/gsd:verify-work`, **plus** the null-arm wider-scope
  check must show a real-vs-null margin before any corpus-write wave is allowed to proceed —
  this is a domain-specific gate this phase's own investigation established, not a generic
  pytest concern, and must not be skipped even though it isn't expressible as a unit test.

### Wave 0 Gaps
- [ ] Confirm whether `tests/unit/test_vocabulary_drift.py` (or equivalent) exists and covers
  namespace-registration; if not, add coverage for the new `regime_volatility` namespace as
  part of the CVR migration task, not as an afterthought.
- [ ] No new pytest fixtures should be needed — `test_regime_writer.py` already has extensive
  synthetic-obs-matrix fixtures (`test_build_obs_matrix_shape` etc.) that generalize directly to
  a 2-column case.

## Security Domain

`security_enforcement` is not referenced in `.planning/config.json` — per protocol, absent
means enabled, so this section is included. However, this phase has **no attack surface**:
it is a batch/oneshot internal labeling job with no external input, no user-facing endpoint, no
authentication/session/access-control surface, and no cryptographic material. All "input" is
internally-generated OHLCV data already flowing through existing, already-audited pipelines.

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | No | No new endpoint or auth surface |
| V3 Session Management | No | N/A |
| V4 Access Control | No | N/A — internal batch job, same trust boundary as existing `regime_writer.py` |
| V5 Input Validation | Marginal | Existing `_check_occupation_gate`/convergence-retry logic already guards against degenerate fits; no new external input class introduced |
| V6 Cryptography | No | N/A |

### Known Threat Patterns for this stack
None applicable — this phase touches no network-facing surface, no secrets, no user input. The
only "correctness" risk (parameter-lookahead bias) is a statistical/methodological concern
already addressed by reusing the walk-forward fix, not a security concern in the ASVS sense.

## Sources

### Primary (HIGH confidence — direct source read this session)
- `services/regime_writer.py` (1945 lines, read in full) — every function signature, docstring,
  and constant cited above
- `src/intelligence/features/feature_vector_persistence.py` (lines 1-750 read) — schema column
  ownership, `REGIME_WRITER_OWNED_COLUMN_NAMES`, insert-column order
- `production/migrations/292_hmm_walk_forward_apr.sql` — APR migration template
- `production/migrations/158_hmm_probability_vector.sql` — earlier `feature_vectors` regime
  column-addition template
- `production/migrations/233_controlled_vocabulary_seed_namespaces.sql` — CVR seed template,
  including the existing `regime_hmm` namespace this phase must NOT repoint
- `src/config/vocabulary_drift.py` (lines 1-260 read) — `VocabularyDriftAuditor`'s hardcoded
  namespace-query dicts that need a new `regime_volatility` entry
- `services/ic_engine.py` (targeted reads: lines 40-90, 590-730, 1655-1680) — startup gate,
  `alpha.regime.groups` config loading, regime-source fallback logic
- `services/ensemble_trainer.py`, `services/alpha_publisher.py`, `services/
  regime_coverage_auditor.py`, `services/cross_sectional_spread_tracker.py` (grep + targeted
  reads) — downstream `regime` consumer inventory
- `services/service_auditor.py` — `regime-writer` DAG registration (oneshot, lag threshold N/A)
- `scripts/analysis/hmm_production_regime_axes_null_arm_validation.py` (docstring + CLI args
  read in full) — the null-arm reusability finding
- `tests/unit/services/test_regime_writer.py` (test names enumerated, ~1525 lines, 40 tests)
- `docs/foundation/glossary.md` (regime entry, lines 75-148 read) — the doc that goes stale
- `.planning/milestones/v3.1-phases/171-.../171-FINAL-VERDICT.md` (read in full) — the locked design source
- `.planning/milestones/v3.1-phases/171-.../171-06-PLAN.md`, `171-07-PLAN.md` frontmatter (withdrawn rollout
  templates)
- `.planning/ROADMAP.md` Phase 171/172 entries, `.planning/STATE.md` (Roadmap Evolution +
  Strategic Plan sections)
- `.planning/config.json` — `nyquist_validation: true` confirmed

### Secondary (MEDIUM confidence)
None — no web/external sources were needed for this phase; it is entirely project-internal.

### Tertiary (LOW confidence)
None.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — no new libraries, everything already in production use
- Architecture: HIGH — read every relevant function directly, verified generalization points
  against actual code (not inferred)
- Pitfalls: HIGH for the code-generalization pitfalls (verified against source); MEDIUM for the
  `ic_engine.py` cutover-scope pitfall (verified the complexity exists, did not fully map every
  line of a 6,000-line file — flagged as its own plan-scoping recommendation rather than fully
  resolved here)

**Research date:** 2026-08-08
**Valid until:** Short shelf life recommended — 7 days. This phase depends on a same-day
investigation verdict (`171-FINAL-VERDICT.md`, dated 2026-08-08) and on this repo's current
migration-number/schema state (migration 307 next-free, confirmed live at research time); both
are exactly the kind of fast-moving, single-repo state that can shift if other concurrent phases
(e.g. Phase 170, explicitly noted as running concurrently per STATE.md) land migrations first.
