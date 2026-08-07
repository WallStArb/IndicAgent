# Phase 171: HMM Walk-Forward Regime Labeling (Parameter-Lookahead Fix) - Research

**Researched:** 2026-08-07
**Domain:** Internal batch-compute correctness fix (HMM regime labeling, TimescaleDB corpus mutation, staged rollout) — not a library-integration phase, no external packages
**Confidence:** HIGH (all claims below verified directly against live code, live DB state, and migration history — no training-data guesses required)

## Summary

This phase is much closer to done than its own ROADMAP description implies, and has one
undocumented, load-bearing data-integrity gap that the plan MUST address before Requirement 3
can run safely. Direct code inspection (not assumption) found:

- **Requirement 1 (tf-calibrated APR keys) is ALREADY SHIPPED.** Migration 292
  (`production/migrations/292_hmm_walk_forward_apr.sql`, commit `1300ec8d`, 2026-08-05) already
  seeds all 4 tfs' `refit_every_bars`/`initial_warmup_bars` with exactly the values the phase's
  own requirement note specifies (1h: 1650/3300 `[rca_analysis]`, 15m: 6600/13200
  `[rca_analysis]`, 5m: 19800/39600 `[initial_estimate]`, 1d: 252/504 `[initial_estimate]`).
  Nothing to build here.
- **Requirement 2 (wire into live path) is ALREADY SHIPPED.** `main()` reads
  `alpha.hmm.walk_forward.enabled` (default `false`) and `_run_symbol_worker` already branches
  between `_compute_symbol_tf_walk_forward` and `_compute_symbol_tf` on that flag (commit
  `1300ec8d`, todo 229's convergence fix on top in `ba8a74ef`). Flipping the flag is a config
  change (`config_state` UPDATE), not a code change.
- **Requirement 5 (seed-stability check) is genuinely NOT wired anywhere.** `_hmm_seed_stability_check`
  is exercised only by two synthetic unit tests
  (`test_hmm_seed_stability_check_shape_and_ranges`, `test_hmm_seed_stability_check_is_deterministic`).
  Zero call sites in `main()`, `_run_symbol_worker`, or any `scripts/analysis/*.py` pilot script.
  This genuinely needs a new pilot-stage script.
- **The critical, previously-undocumented gap: running `regime_writer.py --refit` with the flag
  flipped against the CURRENT corpus will silently corrupt data**, not cleanly relabel it. See
  "Critical Finding" below — this is the single most important thing the planner must account for.
- **D-03's multi-seed-restart parallel arm cannot run today without new code.**
  `_walk_forward_hmm_full`/`_compute_symbol_tf_walk_forward` take no `n_restarts` parameter at
  all — todo 108's multi-seed logic lives exclusively in the single-fit `_compute_symbol_tf`
  path. D-03 as written requires extending the walk-forward path first.
- **D-04's `iters_used` logging does not exist on the walk-forward path.** Todo 226's
  instrumentation (`regime_writer.hmm_convergence_iters` log event) is only emitted inside
  `_compute_symbol_tf` (line 1262). `_walk_forward_hmm_full` never logs it. Since the phase's
  actual full-corpus rollout runs through the walk-forward path, D-04's "collect the data as a
  side effect of this phase's refit" will not happen unless this logging is added to
  `_walk_forward_hmm_full` too.

**Primary recommendation:** Plan this phase as (1) a data-integrity-safe NULL-out + relabel
procedure (new finding, below), (2) a small amount of genuinely new code (seed-stability
wiring, n_restarts support in the walk-forward path, iters_used logging parity), (3) a
staged pilot using the existing bootstrap-CI/pairwise-agreement machinery already proven in
the Gate 4 pilot script, then (4) the gated full-corpus rollout + `ic_engine` re-run, bundled
with Phase 151 waves 6-7 per CONTEXT.md's sequencing decision.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Walk-forward HMM fit/decode mechanics | Compute (batch daemon, `regime_writer.py` in-process) | — | Already implemented; pure numpy/hmmlearn compute, no DB writes inside worker |
| APR flag/param dispatch | Compute daemon `main()` | Database (`config_state`) | Existing `ConfigService.get_sync()` pattern, no new mechanism needed |
| `feature_vectors.regime` + 7 sibling columns write | Persistence (`_write_regime_results`/`_bulk_update_by_key`, main process only) | Database (TimescaleDB hypertable) | DAG Invariant 3: compute daemon never writes its own output; already correctly separated |
| Regime-label NULL-out pre-step (new) | Database (targeted SQL, run from main process, chunked) | — | Must precede the walk-forward `--refit` pass; not a compute-daemon responsibility |
| Seed-stability check execution (new) | Analysis script (`scripts/analysis/`, ad hoc, not a daemon) | — | Diagnostic-only, run-once-per-pilot, matches existing Gate-4-pilot-script precedent, not part of the production hot path |
| Pilot go/no-go statistics | Analysis script, reusing `_nonlinear_interaction_combiner_shared.py` | — | Bootstrap CI / paired-difference machinery already built and proven; no new statistical primitive needed |
| Downstream `feature_ic_scores` recompute | Batch daemon (`ic_engine.py --refresh`) | Database | Existing, unmodified consumer; regime is an input column it stratifies on |
| Full-corpus rollout gating (backfill/Phase 151 coordination) | Orchestration (shell/human judgment) | — | Not a code capability — a sequencing/checkpoint decision the plan must encode as a gate task |

## Standard Stack

Not applicable in the traditional "pick a library" sense — no new external dependency is
being introduced. This phase wires already-implemented internal functions
(`hmmlearn.GaussianHMM`, already a project dependency since Phase 138/144, `sklearn.StandardScaler`,
already used throughout `regime_writer.py`) into a new dispatch path. Skip standard Package
Legitimacy Audit — **no new packages are installed by this phase.**

### Alternatives Considered
None — the mechanism (`_walk_forward_hmm_labels`/`_walk_forward_hmm_full`) is a locked decision
per CONTEXT.md (already built + tested, this phase wires it in, does not rebuild it).

## Critical Finding: The Corpus Is NOT NULL — A Bare `--refit` Will Silently Blend Two Methods

This is the single highest-value finding of this research pass. Verified against live DB state
2026-08-07:

```
feature_vectors total rows:        36,854,099
regime IS NOT NULL (already labeled by the OLD full-history-fit method):  26,791,341
regime IS NULL:                                                          10,062,758
```

Three independently-verified code facts combine into a real data-integrity trap:

1. **`_discover_symbols()` (used whenever `--symbols` is omitted) only returns symbols with
   at least one `regime IS NULL` row** (`services/regime_writer.py:1448-1457`, docstring:
   "Skips symbols where every row already has a regime, so restarts are safe"). Since most of
   the corpus is already fully labeled, a bare `regime_writer.py --refit` invocation with no
   `--symbols` would silently process **zero** already-labeled symbols — not an error, a
   quiet no-op for exactly the symbols this phase needs to relabel.

2. **Even when `--symbols` is passed explicitly, `_bulk_update_by_key` (`services/_batch_utils.py:78`)
   is a pure keyed UPDATE** — `UPDATE feature_vectors AS t SET ... FROM <temp> AS v WHERE
   t.symbol=v.symbol AND t.tf=v.tf AND t.bar_ts=v.bar_ts`. Rows **not present** in
   `update_rows` are left completely untouched — old values persist unchanged.

3. **The walk-forward path's `update_rows` deliberately excludes two classes of bars**
   (`_compute_symbol_tf_walk_forward`, `services/regime_writer.py:807-975`): (a) every bar
   before `initial_warmup_bars` (no walk-forward label is even computed for them — by design,
   so a freshly-NULL corpus correctly stays NULL there), and (b) every bar belonging to a
   degenerate/non-converged segment (skipped at segment granularity, again by design for a
   NULL corpus).

Combine these three facts against a corpus that is **already fully labeled by the retired
full-history method**: running the walk-forward pass will overwrite the bars it *does* cover
with clean new labels, but the warmup-prefix bars and any degenerate-segment bars will keep
their **stale full-history-fit values indefinitely** — exactly the "two different computation
methods silently blended under one column" failure mode `_compute_symbol_tf_walk_forward`'s own
docstring explicitly warns against as its unenforced precondition:

> "this must only run against rows that do not already carry a DIFFERENT method's regime
> value... e.g. right after a fresh `backfill_feature_factory.py --recompute` pass, which
> leaves `regime` NULL for every row."

**This project has already been burned by this exact failure class twice** — see todo 205
(completed 2026-07-30): a `--refresh` upsert silently nulled `feature_vectors.regime` corpus-wide
because a generic UPDATE touched a column it didn't own; and the "K3-vs-K5 HMM column collision"
finding in the same incident (11% of SPY/1d rows silently mixed two different models' output in
the same column before detection). The mechanism is different this time (stale-old-method
persistence, not accidental nulling) but the shape — a partial-coverage write leaving
mixed-provenance data in a column nobody is watching — is identical, and CLAUDE.md's own
"silent wrong answers are worse than loud crashes" principle applies directly.

**Required plan task (not optional, not Claude's discretion):** before any walk-forward
`--refit` run (pilot or full), the plan must include an explicit step that **NULLs out
`feature_vectors.regime` and all 7 sibling columns** (`REGIME_WRITER_OWNED_COLUMN_NAMES`,
`src/intelligence/features/feature_vector_persistence.py:467-476`: `regime`,
`hmm_prob_trending_up`, `hmm_prob_ranging`, `hmm_prob_trending_down`, `hmm_regime_prob`,
`hmm_entropy`, `hmm_duration`, `hmm_churn`) for the exact `(symbol, tf)` scope about to be
relabeled — scoped to the pilot's 5-10 symbols first, then to the full 231×4tf rollout — so
`_discover_symbols()` finds the rows again and every bar in scope gets a clean, single-method
label (walk-forward's own NULL-for-warmup-prefix convention then does the right thing).

**Performance implication for the same task:** `feature_vectors` is a compressed TimescaleDB
hypertable — verified 2026-08-07: **83 chunks, 80 already compressed (~96%)**. Per
`docs/foundation/performance-investigation-sop.md` (cited directly in root `CLAUDE.md`), a bulk
UPDATE against compressed chunks decompresses-then-recompresses and has caused two prior
multi-hour incidents in this exact codebase (todos 149, 161) on unrelated tables. The NULL-out
step should be scoped per-(symbol, tf) (matching the pilot's own small scope, then the full
rollout's natural symbol-by-symbol iteration) rather than issued as one corpus-wide `UPDATE ...
WHERE tf = ANY(...)` statement, and should check chunk compression status for the specific
chunks in scope before running, not assume — this is exactly the class of write the SOP was
written to prevent.

## Second Finding: D-03's Multi-Seed Parallel Arm Requires New Code, Not a Flag Flip

CONTEXT.md's D-03 asks to run `n_restarts=1` and `n_restarts>1` as two parallel comparison arms
during the pilot, reusing Phase 168 D-02's "parallel-construction-never-mutate-baseline"
pattern. Two things the planner needs to know before scoping this as "just configure it":

1. **`alpha.hmm.n_restarts` is read and used ONLY by `_compute_symbol_tf`** (the single
   full-history-fit path, `services/regime_writer.py:1139,1147,1193-1257`) via a loop that fits
   `n_restarts` seeds and keeps the best converged log-likelihood. **`_walk_forward_hmm_full`
   and `_compute_symbol_tf_walk_forward` accept no `n_restarts` parameter at all** — every
   per-segment refit inside the walk-forward path fits exactly one seed
   (`hmm_random_state`, no loop). `_run_symbol_worker`'s dispatch to
   `_compute_symbol_tf_walk_forward` does not pass `n_restarts` even though it's already
   available in the worker's arg tuple.
2. **Phase 168's `construction_spreads` pattern doesn't transfer cleanly**: that table has a
   `construction_name` partition column, so two methodologies can coexist as two named rows in
   the same table without ever touching each other. `feature_vectors.regime` has no such
   discriminator — it is one column keyed by `(symbol, tf, bar_ts)`. **There is no schema-level
   way to dual-write two regime methodologies into the same column without recreating the exact
   mixed-provenance bug documented above.**

**Implication for the plan:** D-03's parallel-arm comparison must happen at the
**analysis-script level, out of band from `feature_vectors`** — mirroring the existing
`hmm_walk_forward_gate4_ic_pilot_spy_1h.py` pattern (compute both label sequences in memory,
compare via `_hmm_seed_stability_check` and/or `paired_bootstrap_ic_difference`, print a
verdict) — not as two live writes to the same table. If the pilot's go/no-go concludes
`n_restarts>1` should be the production default, that requires: (a) extending
`_walk_forward_hmm_full`'s signature to accept and loop over `n_restarts` per segment (small,
well-precedented change — same shape as `_compute_symbol_tf`'s existing loop, lines
1193-1257), (b) threading it through `_compute_symbol_tf_walk_forward`, `_run_symbol_worker`,
and `main()`'s already-existing `n_restarts` config load. This is real, scoped implementation
work the plan must size as a task, not assume already exists.

## Third Finding: D-04's `iters_used` Data Won't Materialize on the Walk-Forward Path Without New Logging

Todo 226's cap-headroom instrumentation (`_logger.info("regime_writer.hmm_convergence_iters",
..., iters_used=int(model.monitor_.iter), n_iter_cap=..., converged=...)`) exists **only** at
`services/regime_writer.py:1262-1269`, inside `_compute_symbol_tf`. `_walk_forward_hmm_full`
(the function that will actually run at full-corpus scale once the flag is flipped, per
Requirement 2 already being live) has no equivalent log line per segment. D-04 explicitly says
"this full-corpus rerun IS the real full-corpus measurement... collect the data as a side
effect of this phase's refit" — that will not happen unless the plan adds a per-segment
`iters_used`/`n_iter_cap`/`converged` log line inside `_walk_forward_hmm_full`'s per-segment
loop (`services/regime_writer.py:725-804`), analogous to the single-fit path's existing line.
Small, well-scoped addition; flag it as an explicit task rather than assuming the existing
instrumentation already covers the new dispatch path.

## Architecture Patterns

### Data flow (current, already live)

```
main() reads config_state:
  alpha.hmm.walk_forward.enabled -----------------------------\
  alpha.hmm.walk_forward.{refit_every_bars,initial_warmup_bars}.<tf> --\
                                                                         v
_run_symbol_worker (ProcessPoolExecutor, N workers, compute-only) --> branch:
  enabled=false -> _compute_symbol_tf            (single full-history fit, LOOKAHEAD BUG)
  enabled=true  -> _compute_symbol_tf_walk_forward -> _walk_forward_hmm_full
                       (per-segment refit, causal parameter estimation)
                                                                         |
                                                          (symbol, tf) -> update_rows
                                                                         v
main() (single serial connection) -> _write_regime_results -> _bulk_update_by_key
                                                                         v
                                                        feature_vectors (TimescaleDB, compressed)
                                                                         v
                                              services/ic_engine.py --refresh (regime is a
                                              stratification key for feature_ic_scores)
```

### Recommended sequencing for this phase's execution (not code structure — operational DAG)

```
1. Wiring gaps (small code, this phase's real remaining implementation work):
   a. Add per-segment iters_used/n_iter_cap/converged logging to _walk_forward_hmm_full
   b. Extend _walk_forward_hmm_full / _compute_symbol_tf_walk_forward to accept n_restarts
      (only if D-03's pilot verdict says it's needed — see below)
   c. Write a pilot-stage script that calls _hmm_seed_stability_check against REAL fetched
      obs matrices for the pilot symbols (new; no existing script does this)
2. Pilot (D-01), 5-10 symbols spanning bar-density buckets:
   a. NULL-out regime + 7 sibling columns for JUST the pilot (symbol, tf) cells
   b. Flip alpha.hmm.walk_forward.enabled=true (or pass a --walk-forward-override the pilot
      script controls directly, bypassing config_state, so production stays untouched)
   c. Run regime_writer.py --refit --symbols <pilot symbols> --tf <scoped>
   d. Run the seed-stability check against the pilot's real obs matrices
   e. Run the n_restarts=1 vs n_restarts>1 comparison out-of-band (analysis script, not two
      live writes -- see Second Finding above)
   f. Go/no-go gate: reuse bootstrap_ic_stats / paired_bootstrap_ic_difference from
      _nonlinear_interaction_combiner_shared.py, calibrate thresholds at planning time
3. Full rollout gate (Requirement 3), 231 symbols x 4 tfs:
   a. BLOCKS on: todo 259's client-43 backfill confirmed complete (ps aux / backfill_status)
   b. BLOCKS on: coordination with Phase 151 waves 6-7's bundled recompute (not a redundant
      third ic_engine pass)
   c. NULL-out regime + 7 sibling columns for the full scope (chunked per symbol/tf, check
      compression status first)
   d. Flip alpha.hmm.walk_forward.enabled=true in config_state (real production flip)
   e. regime_writer.py --refit (full symbol/tf sweep)
4. Downstream re-run (Requirement 4):
   a. services/ic_engine.py --refresh --tf <tfs> --training-window-end <ISO8601 per
      OOS-EVAL-PROTOCOL.md>, bundled with whatever Phase 151 waves 6-7 already needs
   b. cross_sectional_regime_model.py is UNAFFECTED (different table, market_regimes) --
      does not need to re-run for this phase alone
5. Folded-todo housekeeping (not gated on 1-4):
   a. Move todo 229 to completed/, correct PRIORITIES.md's stale "deliberately deferred" note
   b. Verify todo 167's equity falsifier gate against the fresh feature_ic_scores before
      assuming a second scoped run is needed
```

### Anti-Patterns to Avoid
- **Do not run `regime_writer.py --refit` (walk-forward enabled) against the current corpus
  without the NULL-out pre-step.** Silently produces mixed-methodology data in a column no
  existing test checks for provenance mixing (see Critical Finding).
- **Do not attempt to dual-write `n_restarts=1` and `n_restarts>1` arms into `feature_vectors`
  as two "rows."** The table has no discriminator column for this; do the comparison in an
  analysis script instead (see Second Finding).
- **Do not issue one corpus-wide `UPDATE feature_vectors SET regime = NULL ...` statement.**
  83 chunks, 96% compressed — chunk it per (symbol, tf), same operational discipline as
  `backfill_feature_factory.py`'s existing `--recompute` manifest-driven per-partition pattern
  (`.planning/phases/151-.../151-07-PLAN.md`).
- **Do not assume `regime_writer.py --refit` with no `--symbols` will pick up already-labeled
  symbols.** `_discover_symbols()` explicitly skips them; always pass `--symbols` explicitly
  for this phase's runs.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Walk-forward HMM fit/decode | A new causal-refit mechanism | `_walk_forward_hmm_labels`/`_walk_forward_hmm_full` (already built, TDD-tested, todo 248) | Locked decision, CONTEXT.md D-00: "component reuse over duplication" |
| Bootstrap CI / significance testing for the pilot gate | A new statistical test | `bootstrap_ic_stats`/`paired_bootstrap_ic_difference`/`per_symbol_ic_ci` (`scripts/analysis/_nonlinear_interaction_combiner_shared.py`) | Already proven correct (circular-block bootstrap, paired-not-marginal CI) across multiple prior gates in this corpus; CONTEXT.md explicitly names this as the reusable machinery |
| Seed-stability diagnostics | A new multi-seed comparison routine | `_hmm_seed_stability_check` (already built, todo 026's bundled ask) | Exists, tested on synthetic data — needs wiring against real data, not rebuilding |
| Chunked corpus mutation over a compressed hypertable | An ad hoc single-statement UPDATE | Per-(symbol, tf) scoped UPDATE, same discipline as `backfill_feature_factory.py --recompute`'s manifest-driven partitioning | Compression-aware batch mutation is a solved, precedented pattern in this codebase (Phase 151-07); reinventing it risks the same class of incident as todos 149/161 |

**Key insight:** almost nothing in this phase needs new algorithmic code. The real work is
(a) a correctness-critical data-migration step the phase description doesn't mention at all,
(b) two small logging/parameter-threading gaps between the single-fit and walk-forward code
paths, and (c) operational sequencing/gating against two live, multi-day background jobs.

## Common Pitfalls

### Pitfall 1: Trusting `--refit`'s docstring framing as "always fits from scratch, no precondition"
**What goes wrong:** `main()`'s `--refit` flag help text says "Semantic documentation flag —
regime_writer always fits GaussianHMM from scratch" — read in isolation this sounds like it's
always safe to re-run. It is NOT safe against an already-labeled corpus with the walk-forward
flag on, per the Critical Finding above.
**Why it happens:** the flag's own docstring is about *fitting* behavior (always fits, never
loads a saved model), not about *write* behavior (which rows get touched).
**How to avoid:** treat the NULL-out pre-step as mandatory, not optional, for every symbol/tf
this phase relabels.
**Warning signs:** after a `--refit` run, spot-check a symbol's early bars (before
`initial_warmup_bars`) — if they still show a `regime` value but the run's own logs show that
symbol's segments starting only after the warmup boundary, those early rows are stale.

### Pitfall 2: Assuming `ic_engine.py`'s fingerprint mechanism will "just notice" the regime change
**What goes wrong:** `ic_engine.py`'s Phase 162 whole-cell fingerprint mechanism skips
recompute for fingerprint-valid cells unless `--refresh` is passed. A regime relabel changes
`feature_vectors.regime` in place; whether the fingerprint watermark
(`_watermark_forward_returns_feature_vectors`) picks that up organically was not independently
re-verified in this research pass.
**How to avoid:** use `--refresh` explicitly for Requirement 4's re-run (matches the pattern
already live in the currently-running `ic_engine.py --refresh --tf 15m` process, confirmed via
`ps aux` 2026-08-07) rather than relying on fingerprint auto-invalidation.

### Pitfall 3: Treating walk-forward compute cost as comparable to the current single-fit baseline
**What goes wrong:** each tf's `refit_every_bars`/`initial_warmup_bars` were deliberately
scaled so every tf gets roughly the same NUMBER of refit segments (~20, by the "1yr refit / 2yr
warmup" schedule applied at each tf's own bar density) over ~20 years of history. That means
the walk-forward path runs roughly 20 independent `GaussianHMM.fit()` calls per (symbol, tf)
cell where the current single-fit path runs 1 — an order-of-magnitude compute cost increase per
cell, not a like-for-like swap.
**How to avoid:** size the pilot's runtime expectations accordingly (small symbol count is
even more justified given this multiplier), and do not assume the full 231×4tf rollout's
runtime will resemble any previously-observed `regime_writer.py` full-corpus runtime.

### Pitfall 4: Launching a redundant third `ic_engine` pass
**What goes wrong:** as of 2026-08-07, TWO long-running background jobs are live on this box
(confirmed via `ps aux`, not assumed): `infrastructure_run_historical_pipeline.py --client-id
43` (todo 259's backfill, started 2026-08-06, still running) and `services/ic_engine.py
--refresh --tf 15m --symbols <80 symbols> --training-window-end 2025-12-24T05:15:00Z` (todo
256's ensemble-eligibility re-check, started 2026-08-06, still running, uses a
`ProcessPoolExecutor` forkserver pool). Launching Requirement 4's `ic_engine` re-run
concurrently with either would contend for the same DB/CPU resources this project's own
CLAUDE.md gotcha explicitly warns about ("check real CPU/RAM contention before launching a
second heavy job alongside a live one"), and would be a genuinely redundant third full pass if
not coordinated with Phase 151 waves 6-7's own bundled recompute need.
**How to avoid:** the plan's full-rollout task (step 3 in Recommended Sequencing above) must
be an explicit checkpoint task that verifies, at execution time (not planning time — these
jobs may finish before execution starts): (a) `ps aux | grep -E
'historical_pipeline|ic_engine'` shows neither job running, (b) `backfill_status` shows
client-43's target symbols as `fetch_complete=true`, (c) `.planning/phases/151-*` shows waves
6-7 either already scheduled to run together with this phase's recompute or explicitly not
conflicting.

## Runtime State Inventory

> This phase mutates `feature_vectors.regime` and 7 sibling columns for the entire 231×4tf
> corpus — the exact blast-radius class CLAUDE.md's Key Decisions section already documents
> for `HMM_RANDOM_STATE` changes. Runtime-state audit below, per the trigger condition for
> rename/refactor/migration-class phases (this is a methodology migration, not a rename, but
> the same "what still holds the old computation's output" question applies).

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | `feature_vectors.regime` + 7 sibling columns, 26,791,341 rows currently carrying the OLD full-history-fit method's output (verified via direct query 2026-08-07) | Explicit NULL-out per (symbol, tf) before relabeling — see Critical Finding. Data migration, not a code edit. |
| Live service config | `config_state` row `alpha.hmm.walk_forward.enabled` (currently `false`, migration 292) is the production on/off switch — flipping it is itself a state mutation tracked in `config_history`, not a code deploy | Flip via `ConfigService`/APR mechanism (not a raw SQL UPDATE) so `config_history.changed_by`/`reason` are recorded, matching this project's APR provenance discipline |
| OS-registered state | None — `regime_writer.py` is not a systemd-scheduled daemon; it's invoked manually/via the corpus pipeline shell script (`ops_corpus_pipeline_run.sh`) | None |
| Secrets/env vars | None — no secret or env-var name changes involved | None |
| Build artifacts / installed packages | None — no package/dependency changes; `hmmlearn`/`scikit-learn` already installed and used by both code paths | None |
| Downstream derived state | `feature_ic_scores` (via `ic_engine.py`), `alpha_ensemble_ic`/`ensemble_trainer` inputs, `market_regimes`-independent (that table is untouched — cross-sectional regime is a separate mechanism) | Full `ic_engine --refresh` re-run required (Requirement 4); `ensemble_trainer`/`alpha_publisher` re-run is NOT explicitly in this phase's scope per the 5 locked requirements — confirm at planning time whether it's implied or deliberately deferred |

**Canonical question answered:** after the NULL-out + walk-forward relabel pass runs, the only
remaining "old value" surface is `feature_ic_scores` rows computed against the pre-fix
`feature_vectors.regime` values — cleared entirely by the `ic_engine --refresh` re-run
(Requirement 4). No other table, service config, or OS-level registration carries the old
regime methodology's fingerprint.

## Code Examples

### Existing pilot-script pattern to model the new seed-stability pilot script on
```python
# Source: scripts/analysis/hmm_walk_forward_gate4_ic_pilot_spy_1h.py (live in repo)
# This exact shape -- fetch OHLCV via market_data_ohlcv_tradeable, build obs matrix via
# _build_obs_matrix, call the walk-forward primitive directly (bypassing regime_writer.py's
# CLI/DB-write path entirely), then run the shared bootstrap-CI helpers -- is the established
# pattern for a diagnostic-only pilot script in this codebase. The new seed-stability pilot
# script should follow the same shape, substituting _hmm_seed_stability_check for
# _walk_forward_hmm_labels as the primitive under test.
from scripts.analysis._nonlinear_interaction_combiner_shared import (
    bootstrap_ic_stats,
    paired_bootstrap_ic_difference,
)
from services.regime_writer import _build_obs_matrix, _hmm_seed_stability_check

# ... fetch real OHLCV for a pilot symbol/tf, build obs_matrix via _build_obs_matrix ...
result = _hmm_seed_stability_check(
    obs_matrix,
    n_components=5,
    covariance_type="full",
    n_iter=200,
    seeds=[42, 43, 44],  # hmm_random_state + i, matching todo 108's deterministic derivation
    full_cov_min_obs=500,
)
# result["min_pairwise_agreement"] is the pass/fail signal the pilot's go/no-go should read
```

### Existing DAG-invariant-compliant NULL-out pattern to model the required pre-step on
```sql
-- Not yet written anywhere in the repo -- new task for this phase's plan. Must be scoped
-- per (symbol, tf), issued from the SAME single serial write connection main() already uses
-- (never from a ProcessPoolExecutor worker -- DAG Invariant/gotcha: workers are compute-only).
UPDATE feature_vectors
SET regime = NULL, hmm_prob_trending_up = NULL, hmm_prob_ranging = NULL,
    hmm_prob_trending_down = NULL, hmm_regime_prob = NULL, hmm_entropy = NULL,
    hmm_duration = NULL, hmm_churn = NULL
WHERE symbol = %s AND tf = %s;
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|---------------|--------|
| `_compute_symbol_tf`: single GaussianHMM fit on entire (symbol, tf) history, causal decode only | `_compute_symbol_tf_walk_forward`: periodic refit on training-slice prefix only, causal decode, belief continuity via `_seed_prior_from_label` | Code shipped 2026-08-05 (`1300ec8d`), NOT YET flipped on in production (`alpha.hmm.walk_forward.enabled=false`) | Eliminates parameter-level lookahead; empirically confirmed 24.9-56.8% label agreement between the two methods depending on symbol/tf — this is not a marginal refinement |
| `monitor_.converged` (hmmlearn 0.3.3, unconditionally `True` post-fit) | `model.monitor_.iter < model.monitor_.n_iter` | Fixed 2026-08-05 (`ba8a74ef`, todo 229) | Already live in BOTH code paths; any new HMM code in this phase must use the corrected check, never the old one |
| `_compute_symbol_tf`'s single-seed fit | `n_restarts`-seed loop, keep best converged log-likelihood | Migration 277 (todo 108), default `n_restarts=1` (byte-identical to old behavior) | Live only on the single-fit path; NOT yet extended to walk-forward (Second Finding above) |

**Deprecated/outdated:** the full-history-fit method itself is the thing being deprecated by
this phase — but it is NOT being deleted. `_compute_symbol_tf` remains the code path when
`alpha.hmm.walk_forward.enabled=false`; this phase's rollout is a config flip + data migration,
not a code removal.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `ic_engine.py`'s fingerprint watermark would NOT automatically detect a `feature_vectors.regime` mutation without `--refresh` (this research did not independently trace `_watermark_forward_returns_feature_vectors`'s exact SQL to confirm regime is/isn't part of the watermark hash) | Common Pitfall 2 | Low — the plan already recommends `--refresh` explicitly regardless, matching the live precedent process (`ps aux` confirms `--refresh` is the pattern already in production use for a different re-check), so this assumption doesn't change the recommended action even if wrong |
| A2 | `ensemble_trainer`/`alpha_publisher` re-run is NOT part of this phase's 5 locked requirements (only `ic_engine`/`feature_ic_scores` re-run, Requirement 4, is explicitly named) | Runtime State Inventory | Medium — if the planner assumes ensemble/publisher re-run is implied, scope grows significantly; if the planner assumes it's out of scope and it's actually needed for the regime fix to have any downstream effect, the phase's value is diminished. Recommend confirming with the user at plan-check time, since Phase 148's Gate 2 FAIL / "do not promote to live capital" verdict already means no live capital consumes `alpha_publisher`'s output regardless — likely genuinely out of scope, but worth an explicit one-line confirmation in the plan rather than silent omission |

## Open Questions

1. **Does `ic_engine.py`'s `--refresh` scope for Requirement 4 need to be the full 231-symbol
   universe, or can it stay matched to whatever Phase 151 waves 6-7 scopes their own recompute
   to?**
   - What we know: CONTEXT.md's Sequencing section says this phase's recompute rides in the
     SAME pass as Phase 151 waves 6-7, explicitly to avoid "two overlapping corpus-recompute-scale
     efforts."
   - What's unclear: whether Phase 151 waves 6-7's own scope (not yet planned as of this
     research pass — `151-07-PLAN.md`/`151-08-PLAN.md` exist but have no `-SUMMARY.md`,
     confirming they have not executed) already covers the full 231-symbol universe or a
     narrower one.
   - Recommendation: the planner should re-check `.planning/phases/151-*` status at plan-check
     time (this research pass found it un-executed but did not re-derive its exact intended
     scope) and make Requirement 4's task explicitly say "same scope as whatever Phase 151
     waves 6-7 ends up running," not a hardcoded symbol list.

2. **Is a dedicated `--n-restarts-comparison` CLI mode worth building into `regime_writer.py`
   itself, or is an ad hoc analysis script (matching the existing Gate 4 pilot precedent)
   sufficient for D-03's one-time pilot comparison?**
   - What we know: the existing precedent (Gate 4 pilot) is always a standalone
     `scripts/analysis/*.py` script, never a CLI flag on the production service.
     Renaissance-style discipline in this codebase (D-00) favors reuse over new surface area.
   - What's unclear: whether the pilot's own execution will be a one-off (favoring a script) or
     something the project wants to re-run periodically (favoring a CLI flag).
   - Recommendation: default to a one-off analysis script, consistent with every prior pilot in
     this codebase; only add a CLI flag if the pilot's own findings suggest ongoing monitoring
     is warranted.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| PostgreSQL/TimescaleDB | All requirements | ✓ | live, `feature_vectors` confirmed 36.85M rows, 83 chunks/80 compressed | — |
| `hmmlearn` (GaussianHMM) | Req 2/3 | ✓ | already imported and used throughout `regime_writer.py`, no version change needed | — |
| `scikit-learn` (StandardScaler) | Req 2/3 | ✓ | already imported | — |
| ProcessPoolExecutor worker pool (`_make_worker_pool`) | Req 3 | ✓ | already used by `regime_writer.py`'s existing single-fit path; walk-forward dispatch reuses the same pool mechanism | — |
| `client-43` backfill (todo 259) completion | Req 3/4 gating | **✗ as of 2026-08-07 (still running, PID 3159680, started Aug06)** — re-check at execution time via `ps aux` and `backfill_status`, this WILL change before the plan executes | Gate task, not a fallback — the full rollout simply waits |
| Concurrent `ic_engine.py --refresh --tf 15m` (todo 256) | Req 4 resource contention | **✗ still running as of 2026-08-07 (PID 3268544 + forkserver pool)** — must confirm exited before launching a second `ic_engine` pass | Gate task; do not launch concurrently |
| Phase 151 waves 6-7 execution status | Req 3/4 sequencing | Not yet planned/executed (`151-07-PLAN.md`/`151-08-PLAN.md` have no `-SUMMARY.md`) | Re-check at execution time | Coordinate rather than duplicate |

**Missing dependencies with no fallback:**
- None — both in-flight background jobs are expected to finish on their own; the plan's gating
  task is a checkpoint, not a blocked dependency requiring a workaround.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest (`.venv/bin/pytest`) |
| Config file | `pytest.ini` / project root conftest (standard project setup, unchanged by this phase) |
| Quick run command | `.venv/bin/pytest tests/unit/services/test_regime_writer.py -q` (923 lines existing, all 40 tests confirmed passing 2026-08-07) |
| Full suite command | `.venv/bin/pytest tests/unit/ -q` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| REQ-1 | tf-calibrated APR keys present and correct | Already covered by migration 292's own values; no dedicated test found | Manual `SELECT config_value FROM config_state WHERE config_key LIKE 'alpha.hmm.walk_forward%'` | N/A — config-state assertion, not a unit test; ✅ Wave 0 candidate: add a migration-content assertion test if the plan wants automated coverage |
| REQ-2 | Walk-forward dispatch wired into live path | `test_compute_symbol_tf_walk_forward_returns_tuple_structure` and siblings (lines 1201-1406) exercise the function directly; no existing test exercises `_run_symbol_worker`'s branch-on-flag behavior end-to-end | `.venv/bin/pytest tests/unit/services/test_regime_writer.py -k walk_forward -x` | ✅ (function-level) / ❌ Wave 0 gap: an `_run_symbol_worker`-level dispatch test |
| REQ-3 | Full regime recompute produces clean, single-method-provenance data | No existing test — this is an operational/data-integrity property, not a unit-testable one | Manual: spot-check `SELECT count(*) FROM feature_vectors WHERE symbol=%s AND tf=%s AND bar_ts < <warmup boundary> AND regime IS NOT NULL` should be 0 post-NULL-out-and-relabel for warmup-prefix bars | ❌ Wave 0: needs a verification script/query, not necessarily a pytest test |
| REQ-4 | `ic_engine`/`feature_ic_scores` re-run reflects new regime labels | Existing `ic_engine.py` test suite (unaffected by this phase) covers the mechanism; no test asserts regime-label-freshness specifically | `.venv/bin/pytest tests/unit/services/test_ic_engine*.py -q` (regression only) | ✅ mechanism / ❌ no freshness-specific assertion, likely acceptable given `--refresh` bypasses the fingerprint entirely |
| REQ-5 | Seed-stability check exercised against real corpus data | `test_hmm_seed_stability_check_shape_and_ranges`/`test_hmm_seed_stability_check_is_deterministic` cover the function on synthetic data only | New pilot script (see Code Examples) — not a pytest test, an analysis-script run whose output gets recorded in phase completion notes | ❌ Wave 0: needs the new pilot script itself |

### Sampling Rate
- **Per task commit:** `.venv/bin/pytest tests/unit/services/test_regime_writer.py -q`
- **Per wave merge:** `.venv/bin/pytest tests/unit/ -q`
- **Phase gate:** Full suite green before `/gsd:verify-work`; additionally, the data-integrity
  spot-check query above (REQ-3) must be run and recorded as part of the phase's own completion
  evidence, since it cannot be expressed as a pytest assertion against production data.

### Wave 0 Gaps
- [ ] `scripts/analysis/hmm_walk_forward_seed_stability_pilot.py` (or similar name) — new
      pilot script exercising `_hmm_seed_stability_check` against real fetched OHLCV, closing
      Requirement 5's "never yet exercised against real corpus data" gap
- [ ] Data-integrity verification query/script for the NULL-out + relabel pass (REQ-3) — not
      strictly a pytest test, but should be a checked-in, reusable script, not an ad hoc psql
      command lost to shell history
- [ ] `_walk_forward_hmm_full` per-segment `iters_used`/`n_iter_cap` logging (closes D-04's data
      collection gap on the path that will actually run at full scale)
- [ ] If D-03's pilot verdict favors `n_restarts>1`: `n_restarts` parameter threading through
      `_walk_forward_hmm_full`/`_compute_symbol_tf_walk_forward`, with unit test coverage
      mirroring `_compute_symbol_tf`'s existing multi-restart tests

## Security Domain

Not applicable in the ASVS sense — this is an internal batch-compute correctness fix with no
network-facing surface, no authentication/session/access-control boundary, and no user input.
The only "security-adjacent" concern is data-integrity, already covered exhaustively above
(Critical Finding, Runtime State Inventory) as a correctness/provenance issue rather than a
confidentiality/authorization one. No ASVS category applies; no threat-pattern table is
meaningful for this phase.

## Sources

### Primary (HIGH confidence — direct code/DB inspection, this session)
- `services/regime_writer.py` (1888 lines, read in full across multiple passes) — dispatch
  flow, `_walk_forward_hmm_labels`/`_walk_forward_hmm_full`/`_compute_symbol_tf_walk_forward`/
  `_hmm_seed_stability_check`/`_seed_prior_from_label`/`_compute_symbol_tf`/`_run_symbol_worker`/
  `main()` all read directly, line numbers cited throughout
- `production/migrations/292_hmm_walk_forward_apr.sql` and `277_hmm_multi_seed_restart.sql` —
  read in full, confirms Requirement 1's APR keys already shipped with exact values
- `src/intelligence/features/feature_vector_persistence.py` (lines 460-523) —
  `REGIME_WRITER_OWNED_COLUMN_NAMES`, the todo-205 incident's fix, directly informs the
  Critical Finding
- `services/_batch_utils.py` (`bulk_update_by_key`, lines 78-119) — confirms the keyed-UPDATE
  semantics underlying the Critical Finding
- `tests/unit/services/test_regime_writer.py` (1407 lines, 40 tests, confirmed green
  2026-08-07 via `.venv/bin/pytest`) — confirms seed-stability-check coverage is synthetic-only
- `scripts/analysis/hmm_walk_forward_gate4_ic_pilot_spy_1h.py` — the existing pilot-script
  pattern to model new scripts on
- `scripts/analysis/_nonlinear_interaction_combiner_shared.py` (lines 627-728) —
  `bootstrap_ic_stats`/`paired_bootstrap_ic_difference`/`per_symbol_ic_ci` read directly,
  confirmed reusable
- `services/ic_engine.py` (argparse section, fingerprint mechanism sections) — `--refresh`
  semantics confirmed
- `scripts/ops/corpus/ops_corpus_pipeline_run.sh` (lines 300-370) — confirms the standard
  full-pipeline step ordering and CLI invocations for `regime_writer.py`/`ic_engine.py`
- Live DB queries (2026-08-07): `feature_vectors` row/chunk/compression counts, regime
  NULL/NOT-NULL split
- `ps aux` (2026-08-07): confirmed both background jobs (client-43 backfill, todo 256's
  `ic_engine --refresh`) still running
- `.planning/todos/completed/205-refresh-upsert-clobbers-regime-writer-owned-columns.md` — the
  directly-analogous prior incident informing the Critical Finding's severity assessment
- `git log` on `services/regime_writer.py` and migration 292 — commit hashes/dates cited

### Secondary (MEDIUM confidence)
- `.planning/phases/151-feature-primitives-expansion-theory-motivated-interaction-la/151-07-PLAN.md`
  — read partially (first ~80 lines); confirms `--recompute` per-partition pattern exists as
  precedent, but this research did not re-verify wave 6-7's exact intended symbol/tf scope
- `.planning/todos/pending/259-single-name-equity-backfill-135-symbols-missing.md` — read in
  full; confirms current backfill queue and sequencing intent, but the queue is explicitly
  self-described as shifting ("re-verify the zero-row set immediately before launching, don't
  trust this snapshot")

### Tertiary (LOW confidence)
- None — every claim in this document traces to a direct code read, DB query, or file read
  performed in this research session.

## Metadata

**Confidence breakdown:**
- Standard stack: N/A (no new packages) — HIGH by default, nothing to verify
- Architecture/current implementation state: HIGH — every claim verified against live code with
  line numbers, not inferred from CONTEXT.md's summary
- Critical Finding (NULL-out requirement): HIGH — derived from direct inspection of
  `_discover_symbols`, `_bulk_update_by_key`, and `_compute_symbol_tf_walk_forward`'s own
  docstring precondition, cross-confirmed against a structurally identical prior incident
  (todo 205)
- Pitfalls: HIGH for Pitfalls 1/3/4 (directly verified); MEDIUM for Pitfall 2 (fingerprint
  watermark's exact regime-sensitivity was not independently traced end-to-end — flagged as A1
  in Assumptions Log)
- Environment availability: HIGH but TIME-SENSITIVE — both background jobs' running status is
  a live fact as of 2026-08-07 and will very likely have changed by plan execution time; the
  plan must re-check, not cite this document's snapshot as current

**Research date:** 2026-08-07
**Valid until:** Re-verify the Environment Availability table's two live-process rows and the
`.planning/phases/151-*` execution status immediately before planning/execution — everything
else (code structure, migration content, DAG semantics) is stable and does not need re-checking
within a normal 30-day window.
