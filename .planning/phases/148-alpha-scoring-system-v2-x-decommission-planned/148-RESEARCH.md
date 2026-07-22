# Phase 148: Alpha Scoring System + v2.x Decommission - Research

**Researched:** 2026-07-22
**Domain:** Batch statistical scoring (Python/asyncpg/TimescaleDB), OOS promotion-gate governance, APR migrations
**Confidence:** HIGH

## Summary

This phase has almost no framework/library risk — every piece of statistical machinery it
needs (Fisher-z CI, BH-FDR, walk-forward stability, day-clustered bootstrap CI,
`evaluate_frame_gate`) already exists, is unit-tested, and is used in production by
`services/ensemble_ic_engine.py`, `services/ic_engine.py`, and
`services/counterfactual_tracker.py`. The real work is (1) two small, mechanical DB
migrations for tables that don't exist yet (`alpha_strategy_scores`, `gate_evaluations`)
plus a handful of never-seeded `alpha.scoring.*` APR keys the original schema doc specified
but nobody ever migrated in, and (2) three scripts/services that **compose** existing pure
functions rather than reimplement any statistics.

The single most important finding is a **methodology fork that must be resolved before
planning tasks**: `ic_engine.py`'s current CI method is a circular block bootstrap
(`circular_block_bootstrap_ic_serial`, added later, Component A/todo 091), but
`ensemble_ic_engine.py` (the thing SCORE-02 must extend) still uses the older
`_fisher_z_ci` Fisher z-transform CI. SCORE-02's OOS scorer must reuse **exactly**
`ensemble_ic_engine.py`'s current methodology (Fisher-z, not circular-block-bootstrap) so
its OOS numbers are apples-to-apples comparable with the one existing in-sample
`alpha_ensemble_ic` run (2026-07-19) that used the same code path. Mixing methodologies
between the in-sample baseline and the OOS look would itself introduce a confound the
"two independent gates" design explicitly exists to avoid.

The second key finding is that **SCORE-03's actual mechanics are already fully proven out**
by `scripts/analysis/phase143_1_08_shadow_validation.py`, which computed the exact pooled
+ regime-stratified numbers D-06/D-07 require, on the exact champion data, five days ago.
SCORE-03 is best understood as: take that script's structure, drop the challenger/A-B
comparison logic (not relevant here), retarget it at the FRAME-04 framing (D-08: SCORE-03
*is* FRAME-04, not a second run), and add persistence to a new `gate_evaluations` table plus
a promotion decision record. This is a much smaller build than a naive reading of
SCORE-03's roadmap bullet ("query `alpha_strategy_scores`...") suggests — see Architecture
Patterns below for the reconciliation between the roadmap text and the CONTEXT.md-mandated
machinery.

**Primary recommendation:** Build SCORE-01 (`AlphaScorer`) as a straightforward `BaseBatch`
subclass that generalizes `evaluate_frame_gate`'s day-clustered bootstrap (grouping by
`(symbol, tf, regime, alpha_score_decile)` instead of `(tf, regime)` or
`(direction, regime)`) rather than hand-rolling a new bootstrap CI. Build SCORE-02 as a
standalone script structurally identical to `ops_oos_holdout_eval.py` but scoring
`ensemble_alpha` (not `feature_vectors`) via `ensemble_ic_engine.py`'s exact IC helpers
(`_fisher_z_ci`, `_vectorized_ic`, `_p_values_from_ic`, `compute_walk_forward_stable`) with
`bar_ts >= oos_start`. Build SCORE-03 as a slimmed, persisting version of
`phase143_1_08_shadow_validation.py`'s champion-only evaluation. Neither SCORE-02 nor
SCORE-03 needs new statistical code — only new query/persistence glue.

<phase_requirements>
## Phase Requirements

No REQUIREMENTS.md IDs are tracked for this phase (`phase_req_ids` is null in project init
state). Use the SCORE-01 through SCORE-04 IDs from ROADMAP.md as the requirement set.

| ID | Description | Research Support |
|----|-------------|------------------|
| SCORE-01 | `AlphaScorer` (weekly oneshot, `BaseBatch`) aggregates closed primary `alpha_frames` into `alpha_strategy_scores` by (symbol, tf, regime, alpha_score_decile) | `BaseBatch` contract confirmed (`src/core/agent/base_batch.py`); `evaluate_frame_gate` generalization pattern identified as the correct reuse target for the per-cell bootstrap CI, avoiding a hand-rolled statistic |
| SCORE-02 | Standalone one-shot OOS Gate 1 (signal proof) scorer, writes verdict to `gate_evaluations` | `ops_oos_holdout_eval.py` read in full as structural template; `ensemble_ic_engine.py`'s exact IC helper functions identified; `alpha.validation.oos_start` read pattern confirmed; D-04's "run once" cadence + look-log pattern identified |
| SCORE-03 | OOS Gate 2 (execution proof) evaluation, adopts 143.1-08 champion numbers, pairs pooled + regime-stratified, writes to `gate_evaluations` as FRAME-04 | `phase143_1_08_shadow_validation.py` read in full as structural/numeric template; exact champion numbers extracted from `143.1-08-SHADOW-VALIDATION.md` §6/§7; `evaluate_frame_gate`/`frame_gate_passes` signatures confirmed |
| SCORE-04 | v2.x comparison — documentation only, not a gate | No live v2.x comparison population exists (confirmed: v2.x pipeline `failed` since 2026-07-17/06-22 per CLAUDE.md); this is a promotion-decision-record paragraph, not a code task |

</phase_requirements>

## Project Constraints (from CLAUDE.md)

- **APR mandate**: no hard-coded numeric thresholds/weights/periods in `src/`/`services/` —
  every new gate threshold this phase introduces (`alpha.scoring.min_sharpe`,
  `alpha.scoring.max_drawdown_ratio`, `alpha.scoring.min_ic_alpha_score_corr`, etc.) must be
  a `config_schema`/`config_state`/`config_history` migration triple, not a Python constant.
- **DAG Invariant 3** (compute daemon never writes its own output): `AlphaScorer` computes
  AND writes in one `BaseBatch.execute()` — this is the established exception for batch
  oneshots (same pattern as `ic_engine.py`, `ensemble_ic_engine.py`, `counterfactual_tracker.py`,
  all of which compute and write inline), not a violation. The Ring/writer-separation rule
  is about *real-time daemons*, confirmed by each of those files' own "DAG invariant note:
  this oneshot is exempt" docstring comment.
- **ProcessPoolExecutor workers are compute-only**: if SCORE-01 parallelizes per (tf, regime)
  cohort via `ProcessPoolExecutor` (as the roadmap text specifies), workers must return
  `list[dict]` rows only; the async batch INSERT happens once, serially, in the main process
  — mirrors `ensemble_ic_engine.py`'s and `counterfactual_tracker.py`'s exact pattern.
- **Never log per-row inside a corpus loop** — accumulate a counter, log once per run/cohort
  (pattern already used by every sibling batch service).
- **Exception variable name is `error`**, not `exc`.
- **All timestamps UTC** — `datetime.now(UTC)` only.
- **Executable returns only (Invariant 1)**: any query touching `forward_returns` (SCORE-02)
  MUST filter `WHERE return_type = 'executable_open_to_open'` — note `ensemble_ic_engine.py`
  reads `forward_returns.return_fast/mid/slow/extended` columns directly rather than
  filtering on `return_type` in SQL; confirm at plan time which convention the live
  `forward_returns` schema actually uses for these gradient columns (see Open Questions).
- **Service registry**: if SCORE-01 ships as a systemd-managed oneshot (matching
  `AlphaScorer`/`indicagent-alpha-scorer` naming from the schema doc), it must be added to
  `_DAG_ORDER` (priority 8, alongside `indicagent-ensemble-ic-engine`/
  `indicagent-counterfactual-tracker`) and `_AGENT_ID_TO_UNIT` in `service_auditor.py`, plus
  seed an `alert.lag.*` APR key. SCORE-02/SCORE-03, being ad-hoc governance scripts under
  `scripts/`, follow `ops_oos_holdout_eval.py`'s precedent of **not** being DAG-registered.
- **Naming**: `alpha_strategy_score` → table `alpha_strategy_scores`, class `AlphaScorer`,
  unit `indicagent-alpha-scorer` (already derived in the schema doc, confirmed consistent
  with `docs/foundation/naming-system.md`'s derivation rule).
- **Migrate-as-you-go**: any numeric literal in SCORE-01/02/03 that isn't already an APR key
  must be migrated in this phase's own migration, not deferred.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Weekly strategy-cell aggregation (SCORE-01) | Batch compute (`services/`, `BaseBatch`) | Database/Storage (`alpha_strategy_scores`) | Same tier as `ic_engine.py`/`ensemble_ic_engine.py` — a scheduled oneshot that reads a hypertable and writes an aggregate hypertable |
| OOS Gate 1 signal-proof evaluation (SCORE-02) | Batch compute (standalone script, `scripts/`) | Database/Storage (`gate_evaluations`) | Deliberately NOT a service-tier daemon (D-03) — a governance script, same tier as `ops_oos_holdout_eval.py` |
| OOS Gate 2 execution-proof evaluation (SCORE-03) | Batch compute (standalone script, `scripts/`) | Database/Storage (`gate_evaluations`) | Same tier as `phase143_1_08_shadow_validation.py`, which it directly extends |
| Promotion decision record (SCORE-04 + overall verdict) | Documentation (`docs/plans/`) | — | Not a runtime tier at all — a governance artifact, matching `SHADOW-REVIEW.md`/`OOS-EVAL-PROTOCOL.md`'s existing home |
| `alpha_strategy_scores`/`gate_evaluations` schema + APR keys | Database/Storage (migration) | — | Pure schema/config, no application-tier logic |

## Standard Stack

### Core

No new libraries. Everything is already installed and imported by sibling batch services:

| Library | Version (installed) | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `asyncpg` | already in `.venv` | Async Postgres/TimescaleDB access for `BaseBatch` pool | Used by every `BaseBatch` subclass in this codebase |
| `numpy` | already in `.venv` | Vectorized IC math, bootstrap resampling | Used by `ic_math.py`, `counterfactual_tracker.py` |
| `scipy` (`scipy.stats.bootstrap`, `rankdata`) | already in `.venv` | BCa bootstrap CI (`frame_gate_passes`), rank-IC (`_vectorized_ic`) | Already the project's bootstrap-CI implementation of record |
| `statsmodels` (`multipletests`) | already in `.venv` | BH-FDR correction | Already used by `ic_engine.py`/`ops_oos_holdout_eval.py` |
| `pandas` | already in `.venv` | Daily-mean aggregation, Sharpe calc | Used by `phase143_1_08_shadow_validation.py` |

### Supporting

| Library | Purpose | When to Use |
|---------|---------|-------------|
| `structlog` | Structured logging via `setup_service_logging()` | Every service/script in this codebase |
| `argparse` | CLI args for standalone scripts | SCORE-02/SCORE-03's entrypoints, matching `ops_oos_holdout_eval.py`/`counterfactual_tracker.py --evaluate-gate` |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `_fisher_z_ci` (Fisher z-transform CI) | `circular_block_bootstrap_ic_serial` (ic_engine.py's newer method) | Rejected for SCORE-02: would create a methodology mismatch against the existing in-sample `alpha_ensemble_ic` baseline row, which was computed with `_fisher_z_ci`. Must match, not upgrade, for this specific gate comparison. |
| Hand-rolled per-decile bootstrap in `AlphaScorer` | Reuse `evaluate_frame_gate`'s generalized `group_key`/day-cluster core | `evaluate_frame_gate` was generalized in todo 165 specifically so a second caller could reuse it without duplicating the day-clustered bootstrap; SCORE-01's per-(symbol, tf, regime, decile) cell aggregation is a natural third caller |

**Installation:** None — this phase adds zero new dependencies.

**Version verification:** Not applicable — no new packages.

## Package Legitimacy Audit

**Not applicable.** This phase installs zero new external packages; every library used is
already present in `.venv` and imported by production code today (`ic_engine.py`,
`ensemble_ic_engine.py`, `counterfactual_tracker.py`). No `pip install` step is part of any
plan for this phase.

## Architecture Patterns

### System Architecture Diagram

```
                     alpha_events (Phase 139)
                            |
                            v
   ensemble_alpha  <---  ensemble_trainer  (existing, upstream of this phase)
        |
        |  (in-sample only, bar_ts < oos_start -- EXISTING)          (OOS only, bar_ts >= oos_start -- NEW, SCORE-02)
        v                                                                    v
  EnsembleICEngine ---> alpha_ensemble_ic  <-----------------------  [standalone OOS Gate 1 script]
   (existing service)      |                                          reuses _fisher_z_ci/_vectorized_ic/
                            |                                          _p_values_from_ic/compute_walk_forward_
                            |                                          stable from ic_math.py via
                            |                                          ensemble_ic_engine.py's import pattern
                            |
                            |                              +--------> writes verdict -----+
                            |                              |                              |
   alpha_frames (existing, populated by                    |                              v
   AlphaFrameWriter + CounterfactualTracker)                |                     gate_evaluations (NEW table)
        |                                                   |                       (gate_id, result, evidence JSON)
        |  weekly aggregation (NEW, SCORE-01)                |                              ^
        v                                                   |                              |
  AlphaScorer (BaseBatch) --> alpha_strategy_scores (NEW)    |                              |
        |                        |                           |                              |
        |         (diagnostic: ic_alpha_score_corr)          |                              |
        |                        |                           +------------------------------+
        |                        v
        |               [SCORE-03 script: pooled + regime-stratified
        +-------------->  evaluate_frame_gate() on raw alpha_frames,
       (OOS rows,          reusing champion 143.1-08 numbers per D-06/D-07]
        bar_ts >= oos_start)          |
                                       v
                          docs/plans/<date>-phase148-promotion-decision.md
                          (SCORE-04's v2.x note lives here too)
```

Data flow to trace the primary use case: `ensemble_alpha` (existing) is read twice — once
by the existing in-sample `EnsembleICEngine`, once by the new SCORE-02 OOS script — both
writing distinct `alpha_ensemble_ic` rows distinguished only by which side of `oos_start`
they measured (no schema column distinguishes them, D-03; the distinction lives in
`gate_evaluations.evidence` provenance, not in `alpha_ensemble_ic` itself). Separately,
`alpha_frames` (existing, already populated) is read by the new `AlphaScorer` for the
decile-level diagnostic table and, independently, by the new SCORE-03 script for the actual
pass/fail verdict (reusing the exact machinery already run once for 143.1-08). Both gate
scripts converge on the same new `gate_evaluations` table; the promotion decision record is
the human-readable synthesis of both rows plus the SCORE-04 v2.x note.

### Recommended Project Structure

**Correction (2026-07-22):** the planner combined the DDL and APR-key seed below into a
single migration rather than splitting them — `production/migrations/248_alpha_scoring_gate_tables.sql`
is the only migration this phase adds (see `148-01-PLAN.md`). The two-file split shown below
is this research doc's original suggestion, superseded once the plan was actually written; left
in place for context, not as the executed shape. Migration numbering itself is separately
confirmed live-correct at **248** — 247 (`247_regime_groups_dual_write_symbol_hmm.sql`) landed
same day as an unrelated concurrent workstream; see `148-PATTERNS.md`'s migration-numbering
section for the full resolution.

```
production/migrations/
├── 248_alpha_scoring_gate_tables.sql   # alpha_strategy_scores + gate_evaluations DDL
└── 249_alpha_scoring_apr_keys.sql      # never-seeded alpha.scoring.* keys (see Pitfall 3)
                                          # (or combine into one migration -- planner's call;
                                          # recent precedent has both single- and split-purpose
                                          # migrations, e.g. 244 is APR-only, 236 is DDL-only)

services/
└── alpha_scorer.py                     # SCORE-01: AlphaScorer(BaseBatch)

scripts/ops/corpus/                     # OR scripts/analysis/ -- planner's discretion (CONTEXT.md)
└── ops_oos_gate1_signal_eval.py        # SCORE-02: standalone, mirrors ops_oos_holdout_eval.py

scripts/analysis/
└── score03_gate2_execution_eval.py     # SCORE-03: mirrors phase143_1_08_shadow_validation.py,
                                          # champion-only, persists to gate_evaluations

docs/plans/
└── 2026-07-22-phase148-promotion-decision.md   # promotion decision record (SCORE-04 lives here)

tests/unit/
├── test_alpha_scorer.py                # new
├── test_oos_gate1_signal_eval.py       # new
└── test_score03_gate2_execution_eval.py  # new
```

### Pattern 1: BaseBatch subclass for AlphaScorer (SCORE-01)

**What:** `AlphaScorer(BaseBatch)` with `job_name = "alpha-scorer"`, `compute_version`,
async `execute(pool)`.
**When to use:** Any new scheduled batch aggregation over corpus tables — this is the
established pattern for `ic_engine.py`, `ensemble_ic_engine.py`, `counterfactual_tracker.py`.
**Example:**
```python
# Source: src/core/agent/base_batch.py (read in full), mirrored from
# services/ensemble_ic_engine.py's EnsembleICEngine(BaseBatch) class shape.
class AlphaScorer(BaseBatch):
    job_name = "alpha-scorer"
    compute_version = "1.0.0"

    async def execute(self, pool: asyncpg.Pool) -> None:
        # 1. Read alpha.scoring.min_strategy_n / bootstrap_* APR keys
        # 2. Fetch closed primary alpha_frames rows (status != 'open', frame_variant='primary')
        # 3. Bucket alpha_score into deciles (NTILE(10) in SQL or np.percentile in Python)
        # 4. Group by (symbol, tf, regime, alpha_score_decile); reuse evaluate_frame_gate's
        #    day-clustered bootstrap core with a custom group_key rather than reimplementing
        # 5. Compute win_rate / sharpe_annualized / max_drawdown / ic_alpha_score_corr per cell
        # 6. Filter cells with sample_n < min_strategy_n
        # 7. Async batch INSERT into alpha_strategy_scores (single serial write, main process)
        ...
```

### Pattern 2: Standalone OOS Gate 1 script (SCORE-02)

**What:** A script structurally identical to `scripts/ops/corpus/ops_oos_holdout_eval.py`,
but scoring `ensemble_alpha` (not `feature_vectors`) against `forward_returns`, joined to
`market_regimes`, using **`ensemble_ic_engine.py`'s exact helper set**
(`_fisher_z_ci`, `_vectorized_ic`, `_p_values_from_ic`, `compute_walk_forward_stable`), NOT
`ic_engine.py`'s newer circular-block-bootstrap helpers.
**When to use:** SCORE-02 only — this is a one-time authoritative promotion gate, run at
most once per D-04.
**Example:**
```python
# Source: services/ensemble_ic_engine.py (imports, lines 98-104) +
# scripts/ops/corpus/ops_oos_holdout_eval.py (structural template, read in full)
from src.intelligence.statistics.ic_math import (
    _fisher_z_ci,
    _nan_to_none,
    _p_values_from_ic,
    _vectorized_ic,
)
from services.ensemble_ic_engine import compute_walk_forward_stable

# Query: same shape as ensemble_ic_engine.py's _WORKER_FETCH_SQL, but
# `ea.bar_ts >= $oos_start` instead of `ea.bar_ts < $oos_start`.
# Apply corpus-level BH-FDR once across all cells (mirrors ic_engine.py's convention).
# Write verdict (not raw IC rows -- D-03: never write into alpha_ensemble_ic) to
# gate_evaluations: {gate_id: 'SCORE-02-signal-proof', result: 'pass'|'fail', evidence: {...}}
```
Append an entry to a look-log (`.planning/oos_look_log.jsonl` or a new
`.planning/gate_look_log.jsonl`) on every run, mirroring `ops_oos_holdout_eval.py`'s
`_append_look_log` — this operationalizes D-04's "run at most once" rule as an auditable
trail rather than an unenforced convention.

### Pattern 3: Standalone OOS Gate 2 script (SCORE-03) — adopts, does not recompute

**What:** A slimmed, persistence-adding version of
`scripts/analysis/phase143_1_08_shadow_validation.py`'s `evaluate_epoch()` function, run
against `weight_epoch='143.1-08-champion'` only (no challenger comparison needed for this
gate), reporting both the pooled verdict (criteria 1/2/3/4 from SHADOW-REVIEW.md) and the
regime-stratified companion (criterion 2 via `evaluate_frame_gate`'s
`group_key=lambda row: (row["direction"], row["regime"])`, per D-07).
**When to use:** SCORE-03 only.
**Example:**
```python
# Source: scripts/analysis/phase143_1_08_shadow_validation.py (read in full, lines 87-166
# is evaluate_epoch() -- SCORE-03 is ~this function minus challenger/c6, plus a
# gate_evaluations INSERT and a max_drawdown/sharpe recompute reused verbatim, not re-derived)
from services.counterfactual_tracker import (
    _DEFAULT_BOOTSTRAP_RANDOM_STATE,
    evaluate_frame_gate,
    frame_gate_passes,
)

# D-06: cite 143.1-08-SHADOW-VALIDATION.md Section 6 (pooled) verbatim in the evidence JSON
# and the decision record -- do not re-run this on champion data pretending it's a fresh look.
# The known numbers (already computed, weight_epoch='143.1-08-champion', 69 OOS days):
#   c2_ci_lower = -0.1214896346368989   (fails > 0)
#   c3_sharpe   = 0.38512018365944       (fails > 0.5)
#   c4_max_dd   = 9.598299843093644      (fails < 0.25 ratio)
#   c1 (>=60 days) = True (69 days)      (passes)
# D-07: regime-stratified companion (same script, Section 7) -- only 2 of 8 champion cells
# clear min_clusters=20 coverage (long/mid_bull: ci_lower=-0.077, fails; short/mid_bull:
# ci_lower=-0.278, fails). The other 6 cells are coverage="insufficient", excluded from the
# verdict combination, not counted as pass or fail.
```

### Anti-Patterns to Avoid

- **Re-running `EnsembleICEngine` "just to check" after SCORE-02's first OOS look**: violates
  `OOS-EVAL-PROTOCOL.md`'s frozen cadence rule (D-04). Every additional look converts part of
  the holdout into a training set by process.
- **Treating SCORE-03 as a fresh statistical exercise**: D-06 explicitly forbids recomputing
  the champion's pooled numbers "from scratch and pretending it's a fresh look" — cite
  `143.1-08-SHADOW-VALIDATION.md` §6/§7, don't silently re-derive and risk a numeric drift
  from a config change nobody flagged as relevant.
- **Reporting Gate 2's pooled verdict alone**: D-07 is explicit that a flat pooled FAIL
  without the regime-stratified companion repeats a known, just-diagnosed blindness
  (todo 165's finding that shorts had regime-conditional edge invisible to the pooled window).
- **Writing OOS Gate 1 results into `alpha_ensemble_ic`**: D-03 — that table has no
  in-sample/OOS distinguishing column; a future consumer querying it naively would silently
  blend the two populations. Verdict + evidence goes to `gate_evaluations` only.
- **Hand-rolling a new bootstrap CI for `AlphaScorer`'s per-decile cells**: reuse
  `evaluate_frame_gate`'s generalized core (see Don't Hand-Roll below).

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Day-clustered bootstrap CI on `counterfactual_pnl_r` (any grouping) | A new `scipy.stats.bootstrap` call in `AlphaScorer` | `evaluate_frame_gate(rows, ..., group_key=lambda row: (row["symbol"], row["tf"], row["regime"], row["alpha_score_decile"]))` from `services/counterfactual_tracker.py` | Generalized in todo 165 specifically for grouping-key reuse; a third hand-rolled bootstrap risks silently drifting from the frozen `frame_gate_passes` methodology (BCa below `bootstrap_max_n` day-clusters, analytic CLT bound above) |
| Rank-IC / CI / p-value on `alpha_score` vs. forward returns (OOS side) | A new correlation + CI implementation for SCORE-02 | `_vectorized_ic`/`_fisher_z_ci`/`_p_values_from_ic` from `src/intelligence/statistics/ic_math.py`, exactly as `ensemble_ic_engine.py` already imports them | These are the SAME functions the in-sample `alpha_ensemble_ic` baseline used; using anything else breaks apples-to-apples comparability |
| BH-FDR multiple-testing correction | Custom p-value adjustment | `statsmodels.stats.multitest.multipletests(..., method="fdr_bh")` (already how `ic_engine.py`/`ops_oos_holdout_eval.py` do it) | Standard, already vetted implementation; a custom implementation is a correctness risk for zero benefit |
| Walk-forward fold-stability check | A new fold-ratio function | `compute_walk_forward_stable` from `services/ensemble_ic_engine.py` | EIC-03/D-142A-R1 already locked this as fold IC-**magnitude** ratio (not Sharpe ratio) for a specific, documented statistical-power reason; reimplementing risks silently reverting to the wrong metric |
| Annualized Sharpe / max-drawdown-ratio on a `pnl_r` series | New pandas groupby logic | `_annualized_sharpe`/`_max_drawdown` pure functions from `scripts/analysis/phase143_1_08_shadow_validation.py` (lines 44-68) | Already implements the exact WR-03 frozen edge cases (non-positive peak/Sharpe fails outright) |

**Key insight:** This phase's entire statistical surface area was built and frozen across
Phases 138-143.1. The correct scope of new code is thin composition/persistence glue, not
new statistics. Any plan task that proposes writing a new bootstrap, CI, or correlation
function should be treated as a red flag during plan review.

## Common Pitfalls

### Pitfall 1: Methodology mismatch between SCORE-02 and the existing in-sample baseline
**What goes wrong:** Using `ic_engine.py`'s newer `circular_block_bootstrap_ic_serial` (the
current state-of-the-art CI method in this codebase) for the OOS side, while the one
existing in-sample `alpha_ensemble_ic` row (2026-07-19) was computed with
`ensemble_ic_engine.py`'s older `_fisher_z_ci`.
**Why it happens:** `circular_block_bootstrap_ic_serial` is genuinely the more advanced,
recently-added method (feature-IC uses it now) — a planner skimming `ic_engine.py`'s
imports without checking which file the actual gate compares against could reasonably
default to "use the newest method."
**How to avoid:** SCORE-02 must import from `ensemble_ic_engine.py`'s import list (or
`ic_math.py` directly, selecting `_fisher_z_ci`) to match the in-sample baseline's exact
methodology. If a future phase wants to upgrade `EnsembleICEngine` to the circular-block
method, that is a separate migration that must re-run the in-sample side too before any OOS
comparison is meaningful again — out of scope here.
**Warning signs:** SCORE-02's script importing `circular_block_bootstrap_ic_serial` or
`_circular_block_bootstrap_ic`.

### Pitfall 2: Confusing `alpha_events` population with `ensemble_alpha` population
**What goes wrong:** `ensemble_ic_engine.py`'s own docstring (lines 12-26) documents a real,
previously-fixed bug: measuring IC on `alpha_events` (the post-emission-threshold subset)
instead of `ensemble_alpha` (every scored bar) is post-selection bias that collapses N and
can bias IC in either direction.
**Why it happens:** `alpha_events` is the more "obviously relevant" table name for a signal
gate; `ensemble_alpha` sounds like an intermediate/internal table.
**How to avoid:** SCORE-02 must read `ensemble_alpha` (not `alpha_events`) for Gate 1,
exactly mirroring `EnsembleICEngine`'s own measurement population, just with the OOS-side
`bar_ts` filter.
**Warning signs:** SCORE-02 querying `alpha_events` instead of `ensemble_alpha`.

### Pitfall 3: Assuming all `alpha.scoring.*` APR keys from the 2026-06-25 schema doc already exist
**What goes wrong:** The schema doc (`docs/plans/2026-06-25-v30-alpha-lifecycle-schema.md`)
lists `alpha.scoring.min_strategy_n`, `oos_ic_ci_threshold`, `v2x_comparison_ci`,
`min_sharpe`, `max_drawdown`, `min_ic_alpha_score_corr` as if all were seeded together.
**Live-verified 2026-07-22 (`SELECT config_key, config_value FROM config_state WHERE
config_key LIKE 'alpha.scoring.%'`):** only `min_strategy_n` (30), `bootstrap_max_n` (5000),
`bootstrap_batch` (1000), `bootstrap_random_state` (42) actually exist. `oos_ic_ci_threshold`,
`v2x_comparison_ci`, `min_sharpe`, `max_drawdown`, `min_ic_alpha_score_corr` were never
migrated in.
**Why it happens:** The schema doc was written in one sitting listing the full intended key
set; only the keys a since-shipped phase (143.1) actually needed got seeded along the way.
**How to avoid:** This phase's migration must seed the missing keys
(`alpha.scoring.min_sharpe=0.5`, `alpha.scoring.max_drawdown_ratio=0.25`,
`alpha.scoring.min_ic_alpha_score_corr=0.3`) if SCORE-01/03 read them as APR rather than
hardcoding SHADOW-REVIEW.md's frozen literals inline with a citation comment (either is
defensible per CLAUDE.md's APR-exempt list arguable case for "frozen, pre-registered,
not-tunable" values — see migration 244's precedent of seeding a frozen value as APR anyway
for auditability). Recommend seeding as APR with the same "PRE-REGISTERED, NOT TUNABLE
POST-HOC" provenance language migration 244 used.
**Warning signs:** A plan task assuming `cfg.get_sync("alpha.scoring.min_sharpe", ...)` will
resolve to a live DB value without a migration inserting it first.

### Pitfall 4: `alpha_frames` live schema differs from the 2026-06-25 design doc
**What goes wrong:** The design doc's `CREATE TABLE alpha_frames` (used as illustrative
reference in this research) does not match the live table. Live-verified columns (via `\d
alpha_frames`, 2026-07-22) include `frame_id text` (not `uuid`), plus `corpus_run_id`,
`weight_epoch`, `is_shadow`, `target_r_multiple` — none of which appear in the original
design doc, added by later migrations (215, 224/236, and the weight_epoch/corpus_run_id
columns from `alpha_frame_writer.py`).
**Why it happens:** The design doc is explicitly flagged stale on phase numbers by
CONTEXT.md; it is *also* stale on `alpha_frames`' exact column list, just not called out.
**How to avoid:** Any query against `alpha_frames` (SCORE-01, SCORE-03) must be written
against the live schema (`\d alpha_frames`), not copy-pasted from the design doc. The design
doc's `alpha_strategy_scores` CREATE TABLE (not yet built) is a reasonable *starting point*
for the new migration, but should follow the live `alpha_frames`/`gate_evaluations`
conventions (e.g., text IDs, not uuid, matching `frame_id`'s live type) for consistency.
**Warning signs:** A migration or query assuming `alpha_frames.frame_id` is a `uuid` type.

### Pitfall 5: OOS window may be too short for a meaningful walk-forward split (SCORE-02)
**What goes wrong:** `_run_ensemble_ic_worker`'s walk-forward loop
(`ensemble_ic_engine.py` lines 813-837) divides each cell's series into
`config.walk_forward_folds` folds, each needing `>= min_reliable_n` (currently gated per
cell) observations after an embargo. The OOS window (`bar_ts >= 2025-12-24`) is much shorter
than the full in-sample history; per-cell N inside the OOS window may be too small for
`walk_forward_stable` to be computable at all for many (symbol, tf, regime, lookahead) cells.
**Why it happens:** The walk-forward machinery was designed and tuned against in-sample N;
nobody has run it against a true OOS-only slice before (D-02: "genuinely untested").
**How to avoid:** Expect (and plan a reporting path for) a meaningful fraction of OOS cells
returning `walk_forward_stable=None`/insufficient-N rather than a clean true/false — this is
itself diagnostic information (data starvation vs. signal absence per
`OOS-EVAL-PROTOCOL.md`'s failure-rule), not a bug to "fix" by lowering `min_reliable_n`
post-hoc.
**Warning signs:** A plan task or verification step assuming every OOS cell will produce a
determinate walk-forward verdict.

## Code Examples

### `BaseBatch` minimal contract (verbatim, `src/core/agent/base_batch.py`)
```python
class AlphaScorer(BaseBatch):
    job_name = "alpha-scorer"          # matches systemd unit %n suffix, kebab-case
    compute_version = "1.0.0"

    async def execute(self, pool: asyncpg.Pool) -> None:
        ...  # all business logic; BaseBatch.run() owns pool lifecycle + D-06 emission
```

### Reading `alpha.validation.oos_start` (fail-loud pattern, `ensemble_ic_engine.py` lines 952-967)
```python
# Source: services/ensemble_ic_engine.py
try:
    oos_start = await conn.fetchval(
        "SELECT config_value::timestamptz FROM config_state "
        "WHERE config_key = 'alpha.validation.oos_start'"
    )
except Exception as error:
    raise oos_start_gate_error from error
if oos_start is None:
    raise oos_start_gate_error
```
SCORE-02/SCORE-03 must both fail loud (not default to `MAX(bar_ts)`) if this key is unset —
`OOS-EVAL-PROTOCOL.md`'s "empty/unset -> collapses to no holdout, must be loud" rule applies
equally to gate scripts, not just the corpus orchestrator.

### `evaluate_frame_gate` regime-stratified call (verbatim signature, D-07's exact requirement)
```python
# Source: services/counterfactual_tracker.py, lines 906-979
regime_cells = evaluate_frame_gate(
    rows,                      # list[dict] with keys: tf/regime (or whatever group_key needs), cluster_id, pnl_r
    min_n=1,                   # frame-count floor not meaningful per-regime; min_clusters is the real floor
    bootstrap_max_n=bootstrap_max_n,
    bootstrap_batch=bootstrap_batch,
    bootstrap_random_state=bootstrap_random_state,
    group_key=lambda row: (row["direction"], row["regime"]),
    min_clusters=regime_gate_min_clusters,   # alpha.validation.regime_gate_min_clusters, seed 20
)
```

### Migration triple pattern for a new APR key (verbatim structure, migration 244)
```sql
BEGIN;

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description)
VALUES ('alpha.scoring.min_sharpe', 'float', '0.5', 0.0, 5.0,
        '[conventional] SHADOW-REVIEW.md criterion 3 frozen threshold. PRE-REGISTERED: '
        'not tunable post-hoc.')
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES ('alpha.scoring.min_sharpe', '0.5', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
VALUES (NOW(), 'alpha.scoring.min_sharpe', 1, '0.5', 'migration_NNN',
        'Seed SHADOW-REVIEW.md frozen Sharpe gate threshold, never previously migrated')
ON CONFLICT DO NOTHING;

COMMIT;
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|---------------|--------|
| Feature-level IC CI: Fisher z-transform | Circular block bootstrap (`circular_block_bootstrap_ic_serial`) | Component A, todo 091, migrations 161/165/177/222 | `ic_engine.py` uses the new method; `ensemble_ic_engine.py` was NOT upgraded alongside it — this phase must consciously choose the OLD method for SCORE-02 to match the existing baseline (see Pitfall 1), not because it's "current" but because comparability requires it |
| Pooled-only FRAME-04 gate | Pooled + regime-stratified (`group_key`/`min_clusters`) | todo 164/165, 2026-07-21 | This phase's D-07 mandates the newer regime-stratified companion be used for Gate 2, unlike the original 2026-06-25 schema doc which only specified a pooled gate |

**Deprecated/outdated:**
- The 2026-06-25 schema doc's phase numbers ("Phase 142A/142B/144") — roadmap has since
  renumbered; this phase is 148, not 144. Schema/logic content is still current.
- `SHADOW-REVIEW.md`'s title ("Phase 147 Live Promotion Criteria") — numbering fossil per
  D-08; the document's 5 criteria are still the frozen, current gate definition.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `alpha.scoring.min_sharpe`/`max_drawdown_ratio`/`min_ic_alpha_score_corr` should be seeded as new APR keys (not hardcoded literals) for this phase's migration | Pitfall 3 / Code Examples | Low — either approach is defensible per CLAUDE.md's frozen-value precedent (migration 244); if the planner chooses hardcoded literals with a citation comment instead, that is not a correctness bug, just a stylistic deviation from this research's recommendation |
| A2 | `AlphaScorer` should be a systemd-managed, `_DAG_ORDER`-registered weekly oneshot (per the original schema doc's naming table: `indicagent-alpha-scorer`) rather than an ad-hoc script | Project Constraints | Medium — if this phase's actual near-term need is "run it once to produce the promotion decision record" rather than "stand up a recurring weekly service," full systemd/DAG registration may be premature scope; the roadmap text does call it a "weekly oneshot" explicitly, so this is likely correct, but the planner should confirm cadence is actually needed now vs. deferred |
| A3 | SCORE-01's `alpha_score_decile` binning is computed via `NTILE(10)` (SQL) or equivalent over each (symbol, tf, regime) cohort, not globally across the whole corpus | Architecture Patterns Pattern 1 | Medium — the design doc doesn't specify per-cohort vs. global decile binning; per-cohort is the only interpretation consistent with "(symbol, tf, regime, alpha_score_decile)" being the unique index grain, but this should be confirmed as an explicit plan decision, not left implicit |
| A4 | `forward_returns` gradient columns (`return_fast`/`mid`/`slow`/`extended`) used by `ensemble_ic_engine.py` are already filtered to `return_type = 'executable_open_to_open'` at the column-population level (i.e., these columns only ever hold executable returns, so no additional `WHERE return_type = ...` filter is needed in SCORE-02's query) | Project Constraints, Common Pitfalls | Medium — if `forward_returns` in fact stores multiple `return_type` variants per row and these columns are ambiguous without an explicit filter, SCORE-02 could silently read theoretical (non-executable) returns; verify `forward_returns` table schema/population logic before writing SCORE-02's query |

## Open Questions (RESOLVED)

1. **Does `forward_returns` require an explicit `WHERE return_type = 'executable_open_to_open'` filter for the gradient columns `ensemble_ic_engine.py` reads, or is that invariant enforced at write time?**
   - **(RESOLVED by plan 148-03, SCORE-02):** the executor reads `ensemble_ic_engine.py`'s full `_WORKER_FETCH_SQL`/`_POOLED_WORKER_FETCH_SQL` and copies its existing filtering convention verbatim rather than introducing a new one.
   - What we know: CLAUDE.md states this filter is mandatory for all `forward_returns` queries in `ic_engine.py`; `ensemble_ic_engine.py`'s `_WORKER_FETCH_SQL` was not fully read in this research pass (only partial context around line 530/565).
   - What's unclear: whether `ensemble_ic_engine.py`'s existing query already includes this filter (in which case SCORE-02 should copy it verbatim) or whether the `return_fast/mid/slow/extended` columns are populated exclusively with executable returns at write time by `forward_return_writer.py` (in which case no runtime filter is needed).
   - Recommendation: the planner/executor should read `ensemble_ic_engine.py`'s full `_WORKER_FETCH_SQL`/`_POOLED_WORKER_FETCH_SQL` text (around lines 500-570) before writing SCORE-02's query, and copy whatever filtering convention it already uses — do not introduce a new convention.

2. **Should SCORE-01's `AlphaScorer` be registered in `_DAG_ORDER`/systemd now, or is a plain script sufficient for this phase's actual deliverable (the OOS gate verdicts)?**
   - **(RESOLVED by plan 148-02, SCORE-01):** built as a full `BaseBatch` subclass; systemd-timer/`_DAG_ORDER` registration deferred to a follow-up (not required for this phase's gate-verdict deliverable).
   - What we know: the schema doc specifies a full service (`indicagent-alpha-scorer` systemd unit); ROADMAP.md calls it a "weekly oneshot, BaseBatch."
   - What's unclear: whether this phase needs `AlphaScorer` to run on a systemd timer immediately, or whether a `BaseBatch`-shaped script invoked manually (once, to feed SCORE-03's `ic_alpha_score_corr` diagnostic) satisfies this phase's actual scope, with the timer/DAG registration deferred.
   - Recommendation: build it as a full `BaseBatch` subclass (correct regardless), but let the planner decide whether Wave 1 includes the systemd unit file + `_DAG_ORDER` entry or defers that to a follow-up — CONTEXT.md doesn't address this explicitly.

3. **Where exactly does `gate_evaluations.evidence` schema draw its line between SCORE-02's and SCORE-03's JSON shape?**
   - **(RESOLVED by plan 148-01):** migration 247 uses a generic loose `evidence JSONB` column with no enforced sub-schema; each gate script writes whatever fields fit its own criteria.
   - What we know: CONTEXT.md leaves `gate_evaluations` schema details (beyond timestamp/gate_id/result/evidence) to planner's discretion, calling it "standard APR/migration conventions."
   - What's unclear: whether SCORE-02 and SCORE-03 should share one evidence JSON shape (e.g., `{criteria: [...], ci_lower, ci_upper, n_obs, ...}`) or have gate-specific shapes given how different Gate 1's (IC-based) and Gate 2's (P&L-based) evidence naturally are.
   - Recommendation: use a generic `evidence JSONB` column with no enforced sub-schema (matches `llm_calls`'/`integrity_monitor`'s existing loose-JSONB-evidence convention in this codebase), let each gate script write whatever fields make sense for its own criteria.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| TimescaleDB / PostgreSQL | All of SCORE-01/02/03 | ✓ (live-queried during this research, `alpha_frames` row counts confirmed) | live | — |
| Python 3.14 + `.venv` | All scripts/services | ✓ | 3.14.4 | — |
| pytest | Validation Architecture | ✓ | 9.0.3 | — |
| `numpy`/`scipy`/`statsmodels`/`pandas`/`asyncpg` | All statistics | ✓ (already imported by sibling services) | already installed | — |

No missing dependencies. This phase requires no new infrastructure.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 9.0.3 |
| Config file | (project-root `pyproject.toml`/`pytest.ini` — not read in this pass; existing `tests/unit/` convention confirmed via directory listing) |
| Quick run command | `.venv/bin/pytest tests/unit/test_alpha_scorer.py tests/unit/test_ensemble_ic_gate.py -q` |
| Full suite command | `.venv/bin/pytest tests/unit/ -q` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| SCORE-01 | `AlphaScorer` correctly buckets `alpha_frames` into (symbol, tf, regime, decile) cells and filters N < `min_strategy_n` | unit | `pytest tests/unit/test_alpha_scorer.py -x` | ❌ Wave 0 |
| SCORE-01 | `ic_alpha_score_corr` computed correctly (monotonicity diagnostic) | unit | `pytest tests/unit/test_alpha_scorer.py -x -k corr` | ❌ Wave 0 |
| SCORE-02 | OOS Gate 1 script fails loud when `alpha.validation.oos_start` unset | unit | `pytest tests/unit/test_oos_gate1_signal_eval.py -x -k oos_start` | ❌ Wave 0 |
| SCORE-02 | OOS Gate 1 script uses `_fisher_z_ci` (not circular-block-bootstrap) methodology | unit | `pytest tests/unit/test_oos_gate1_signal_eval.py -x -k methodology` | ❌ Wave 0 |
| SCORE-03 | Gate 2 script correctly cites champion 143.1-08 pooled numbers without recomputing from a different population | unit/manual | `pytest tests/unit/test_score03_gate2_execution_eval.py -x` | ❌ Wave 0 |
| SCORE-03 | Regime-stratified companion never lets a pooled FAIL stand alone without the per-cell breakdown in the same output/row | unit | `pytest tests/unit/test_score03_gate2_execution_eval.py -x -k regime_stratified` | ❌ Wave 0 |
| — | Existing `evaluate_frame_gate`/`frame_gate_passes`/`compute_walk_forward_stable` machinery this phase reuses | regression | `pytest tests/unit/test_counterfactual_tracker.py tests/unit/test_ensemble_ic_gate.py tests/unit/test_ensemble_ic_wf_stability.py -q` | ✅ (already exist) |

### Sampling Rate
- **Per task commit:** the relevant new test file, quick-run above.
- **Per wave merge:** `.venv/bin/pytest tests/unit/ -q` (full suite).
- **Phase gate:** full suite green before `/gsd:verify-work`; additionally, the actual OOS
  gate runs (SCORE-02/SCORE-03 executed for real, not just unit-tested) are themselves a
  Wave 2 deliverable per D-04's "run once" rule — these are NOT re-runnable smoke tests.

### Wave 0 Gaps
- [ ] `tests/unit/test_alpha_scorer.py` — covers SCORE-01
- [ ] `tests/unit/test_oos_gate1_signal_eval.py` — covers SCORE-02
- [ ] `tests/unit/test_score03_gate2_execution_eval.py` — covers SCORE-03
- [ ] No framework install needed — pytest already configured and green project-wide

## Security Domain

`security_enforcement` is not set in `.planning/config.json` (absent = enabled), but this
phase has essentially no attack surface: it is internal batch analytics over already-trusted,
already-computed corpus data, with no user input, no network-facing endpoint, no
authentication/session concerns, and no new secrets.

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | No | No auth surface — internal batch scripts run by an operator with existing DB credentials |
| V3 Session Management | No | Not applicable |
| V4 Access Control | No | Not applicable — same trust boundary as every other batch service in this codebase |
| V5 Input Validation | Marginal | CLI args (`argparse`) for SCORE-02/03 should validate `--symbols`/`--tf` against known values the same way `ops_oos_holdout_eval.py` already does (via `get_active_contracts(settings)`), not accept arbitrary strings interpolated into SQL |
| V6 Cryptography | No | No new secrets or crypto operations |

### Known Threat Patterns for this stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| SQL injection via CLI-supplied `--symbols`/`--tf` | Tampering | Parameterized queries throughout (already the codebase convention — `asyncpg`/`psycopg2` positional params, never string interpolation) |
| Silent OOS-boundary misconfiguration (empty/malformed `oos_start`) treated as "no holdout" | Tampering / Repudiation (of the gate's own integrity) | Fail-loud pattern already established (`ensemble_ic_engine.py`'s `oos_start_gate_error`, `ops_oos_holdout_eval.py`'s `_read_oos_start`) — SCORE-02/03 must copy this, never silently default to `MAX(bar_ts)` |

## Sources

### Primary (HIGH confidence)
- `.planning/phases/148-alpha-scoring-system-v2-x-decommission-planned/148-CONTEXT.md` — user decisions D-01 through D-08, canonical refs, reusable assets (read in full)
- `docs/plans/2026-06-25-v30-alpha-lifecycle-schema.md` — schema/APR key design (read in full)
- `docs/plans/OOS-EVAL-PROTOCOL.md` — frozen OOS holdout discipline (read in full)
- `docs/plans/SHADOW-REVIEW.md` — frozen 5 pass/fail criteria (read in full)
- `.planning/phases/143.1-measurement-and-eligibility-integrity-fisher-z-ci-bootstrap-/143.1-08-SHADOW-VALIDATION.md` §6/§7 — exact champion numbers (read in full)
- `src/core/agent/base_batch.py` — `BaseBatch` contract (read in full)
- `services/ensemble_ic_engine.py` — Gate 1 reusable IC helpers, in-sample query pattern, `compute_walk_forward_stable` (read in full: imports, config, worker function, walk-forward, row builder)
- `services/ic_engine.py` (partial) — confirms newer circular-block-bootstrap methodology, distinct from `ensemble_ic_engine.py`'s
- `src/intelligence/statistics/ic_math.py` (function inventory) — canonical home of all pure IC math helpers
- `scripts/ops/corpus/ops_oos_holdout_eval.py` — SCORE-02 structural template (read in full)
- `scripts/analysis/phase143_1_08_shadow_validation.py` — SCORE-03 structural/numeric template (read in full)
- `services/counterfactual_tracker.py` — `evaluate_frame_gate`/`frame_gate_passes` signatures and full docstrings (read in full for relevant sections)
- `production/migrations/244_regime_gate_min_clusters.sql`, `236_alpha_frames_is_shadow.sql` — migration convention templates (read in full)
- Live DB queries (2026-07-22): `\d alpha_frames`, `\d alpha_strategy_scores` (does not exist), `\d gate_evaluations` (does not exist), `config_state` for `alpha.scoring.*`/`alpha.validation.*` keys, `alpha_frames` weight_epoch distinct counts
- `services/service_auditor.py` `_DAG_ORDER` — confirmed registration convention for batch oneshots

### Secondary (MEDIUM confidence)
- `.planning/STATE.md` — project history/sequencing context (read in full)
- `.planning/ROADMAP.md` grep excerpts (lines 1327-1363) — current SCORE-01/02/03/04 text, consistent with CONTEXT.md's additional_context

### Tertiary (LOW confidence)
- None — this phase's domain is entirely internal codebase conventions, all verified against live code/DB rather than external sources.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — zero new dependencies, all reused code read and confirmed live
- Architecture: HIGH — every pattern this phase needs already has 1-2 production precedents read in full
- Pitfalls: HIGH — Pitfall 1 (methodology fork) and Pitfall 3 (unseeded APR keys) are both live-verified findings, not speculation

**Research date:** 2026-07-22
**Valid until:** 30 days (stable internal codebase conventions; re-verify `config_state` APR keys and `alpha_frames` row counts if this research is reused after a corpus rebuild)
