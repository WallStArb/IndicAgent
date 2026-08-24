# Phase 173: Broadcast Feature Significance Correction - Research

**Researched:** 2026-08-24
**Domain:** Statistical significance testing correctness in `services/ic_engine.py` (Renaissance-style IC measurement pipeline). No external library/framework surface — this is entirely internal codebase archaeology.
**Confidence:** HIGH (every claim below is grounded in direct code reads and one live DB query against production `concept_registry`, not training-data recall)

## Summary

This phase's CONTEXT.md (D-01 through D-10) already locks the architecture. What was missing for planning was ground-truth on the CURRENT code this phase touches — exact line numbers, function signatures, the fingerprint/skip-gate mechanism CONTEXT.md never mentions, and a pre-existing script that already implements most of D-10's detector logic. All of that is now verified against live `services/ic_engine.py` (5,877 lines) and a live query against production `concept_registry`.

The single most important finding for planning: **`scripts/ops/alpha/ops_broadcast_feature_audit.py` already exists and already implements an empirical broadcast classifier** (per-`bar_ts` max-min-within-epsilon check across symbols) — it is explicitly read-only today, with a docstring stating persistence was deferred as YAGNI until "whoever builds a broadcast-aware significance test" arrives. That's this phase. D-10's "lightweight variance-based detector" should extend/adapt this script (or its `_classify_broadcast` logic) to also WRITE `concept_registry.metadata`, not be built from scratch. Its existing epsilon-based classifier (`max - min <= epsilon` per `bar_ts` group) is arguably simpler and more robust for this exact purpose than a variance threshold — the planner should treat D-10's "variance ≈ 0" framing and this script's already-built max-min-epsilon check as two valid mechanics for the same job and pick one, not necessarily invent a third.

Second key finding: `concept_registry.group_name` (TEXT column, NOT `metadata`) already tags `vix_z`/`yield_slope_z`/`flight_quality`/all 5 cross-asset fields as `group_name='macro'`, and calendar/session fields as `group_name='calendar'`/`group_name='session'` — live-verified. But `group_name` is **over-inclusive**: `calendar`=30 rows, `session`=62 rows, `macro`=12 rows in production today, versus the 23-feature confirmed-broadcast population (15 calendar/session + 3 macro-context + 5 cross-asset — note `macro`'s 12 already exceeds the 8 CONTEXT_FEATURES+cross-asset features, meaning some `macro`-grouped features are NOT in the confirmed-broadcast list). `group_name` is a topical peer-group taxonomy, not a correctness classification — this independently confirms why D-08 correctly rejected reusing it and locked `metadata` (JSONB) as the new flag's home instead. Do not let a plan task shortcut to `WHERE group_name IN ('macro','calendar','session')` — it would over-select.

Third: the fingerprint/incremental-skip mechanism (`ic_cell_fingerprints`, `pass_type` column, values today are `'pooled'`/`'symbol_hmm'`/`'cross_sectional'`) is NOT mentioned anywhere in CONTEXT.md or todo 270, but is a hard architectural dependency of `_compute_cross_sectional_tf`'s single call site in `main()` (line 5658) — every cross-sectional cell computed there is gated by a fingerprint-valid skip check and, on recompute, UPSERTs one `ic_cell_fingerprints` row keyed `(cs_symbol_key, tf, "cross_sectional", training_window_end)`. A new, separately-computed broadcast cell needs its own answer to "how does it participate in this skip/recompute gate" — this is a real open design question the planner must resolve, not an implementation detail CONTEXT.md already settled.

**Primary recommendation:** Treat this as three sequenced units of work: (1) delete `_compute_symbol_tf`'s `CONTEXT_FEATURES` daily-cadence block + the `CONTEXT_FEATURES` frozenset (self-contained, no dependencies); (2) exclude the 23 broadcast columns from `_compute_one_cross_sectional_cell`'s input matrix and thread `bar_ts` through `_compute_cross_sectional_tf`'s chunked fetch (touches the OOM-history code, needs care per D-05); (3) build the new `_compute_one_broadcast_cell` + wire it into `main()`'s cross-sectional loop with its own fingerprint/skip-gate answer, and build/extend the variance detector to persist `concept_registry.metadata`. Units 1 and 3's detector piece can proceed in parallel; unit 2 and unit 3's cell-compute piece are sequentially dependent (unit 3 needs bar_ts-tagged returns_mat from unit 2's plumbing).

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Broadcast-feature classification (is this feature symbol-invariant?) | Batch/Compute (`ic_engine.py` or a new oneshot script) | Database (`concept_registry.metadata`, persisted classification) | Classification is a one-time-per-corpus-epoch empirical computation over `feature_vectors`; the answer is read at measurement time by the compute tier, not recomputed inline every run |
| Per-symbol pooled cross-sectional significance test | Batch/Compute (`_compute_one_cross_sectional_cell`) | Database (`feature_ic_scores` write via `_write_cross_sectional_results`) | Existing, unchanged pattern — DAG invariant: compute never writes its own output, a dedicated write function does |
| Broadcast significance test (new) | Batch/Compute (new `_compute_one_broadcast_cell`, reusing `_subsample_and_rank`) | Database (same `feature_ic_scores` write path) | D-07 locks this into the SAME table/writer, not a new system |
| Aggregate market-return construction (equal-weighted mean across peer symbols) | Batch/Compute (inside `_compute_cross_sectional_tf`'s fetch phase) | — | D-04/D-05: built from `returns_mat` already fetched for the cell; no new data source |
| Incremental skip/recompute gating for the new broadcast cell | Batch/Compute (`ic_cell_fingerprints` read/write in `main()`) | Database (`ic_cell_fingerprints` table) | Not addressed by CONTEXT.md — see Open Questions. Existing per-symbol/cross-sectional cells already follow this pattern; the new cell must adopt or deliberately opt out of it |

## Phase Requirements

No `REQUIREMENTS.md` exists in `.planning/` (repo-wide grep confirms it — this project does not currently maintain that file at all, not merely for this phase). This phase predates `/gsd-discuss-phase`'s requirement-ID convention; `173-CONTEXT.md`'s `<decisions>` block (D-01 through D-10) is the authoritative locked-decision source. Per the phase brief's own instruction, this is not a gap to fill — the table below maps CONTEXT.md decisions to research support instead of REQ-IDs.

| Decision | Description | Research Support |
|----------|-------------|-------------------|
| D-01 | Delete `CONTEXT_FEATURES` bespoke per-symbol daily-cadence block | Exact block located: `services/ic_engine.py:2801-3163` (comment header at 2801, loop `for cf_idx, cf_name in enumerate(sorted(CONTEXT_FEATURES))` at 2842, `all_results.append(...)` closing the per-feature/per-scale loop ends ~3163 where `_compute_one_cross_sectional_cell` begins at 3164). `CONTEXT_FEATURES` frozenset itself at line 228. |
| D-02 | 23-feature broadcast population is authoritative starting set | Live-queried `concept_registry`: all 11 sampled features (3 CONTEXT_FEATURES + 5 cross-asset + 3 calendar/session) confirmed present with `status='active'`; no evidence of a missed Phase 151+ addition in the sample checked. Full row-by-row cross-check against all 23 names still needed by planner/implementer (script below can do it in one query) — this research spot-checked, did not exhaustively re-verify all 23. |
| D-03 | Broadcast cell computed per existing `(regime_group, tf, regime_label)` boundary | Confirmed: `_compute_cross_sectional_tf` is called once per cell from `main()`'s `cs_cell_plan` loop (line 5621), already scoped to exactly this granularity. |
| D-04 | Equal-weighted mean aggregate return, no cap-weighting infra | Confirmed no market-cap data anywhere in schema via grep (no results for cap/weight columns on `instruments`). `returns_mat` is already fetched pooled-by-symbol in `_compute_cross_sectional_tf` (line 3652 `returns_mat = np.vstack(ret_chunks)`) — the exact array D-04 says to reuse. |
| D-05 | New cell never touches `Float32ChunkAccumulator`; `bar_ts` must be threaded through the chunked fetch | Confirmed: `chunk_sql` (line 3580) selects `fv.bar_ts` as column 0 of every row, but the accumulation loop at line 3632 (`X_acc.append_chunk([[r[i + 1] for i in range(n_features)] for r in batch])`) and the return/complete matrix loop (lines 3633-3641, indices `1 + n_features + j`) both explicitly skip index 0 — `bar_ts` is fetched and immediately discarded today, exactly as todo 270 finding #5 states. No array anywhere currently threads it further. See Code Examples section for the exact skip points. |
| D-06 | Thin cells skip via existing `min_reliable_n` gate | Confirmed: `_compute_one_cross_sectional_cell` already applies this gate identically at lines 3250 and 3259 (`if n_independent < min_reliable_n` / `if n_valid < min_reliable_n`) — same gate, same constant, reusable as-is for the new cell function. |
| D-07 | Same `feature_ic_scores` table, same BH-FDR family via `cf_cluster_id` | Confirmed: `_compute_one_cross_sectional_cell` already writes `cluster_id` per row (line 3393, from `_cluster_features`); the corpus-level BH-FDR pass groups by cluster representative (lines 3681-3688 `cluster_groups` dict) inside `_compute_cross_sectional_tf` itself, before rows return to the caller for writing. A new broadcast cell function needs an equivalent cluster-ID assignment (could reuse `_cluster_features` on the smaller broadcast matrix, or assign each broadcast feature its own singleton cluster like the deleted `CONTEXT_FEATURES` block did with `cf_cluster_id = 10000 + cf_idx` at line 2880 — that ID-space convention is now available for reuse since its origin block is deleted). |
| D-08 | Classification lives in `concept_registry.metadata` (JSONB), not `concept_annotation` or `group_name` | Confirmed via live query: `metadata` already carries structured keys (`tier`, `apr_namespace`, `formula_short`, `normalization`, `migrated_from`, `migrated_by`) for every sampled row — a new `broadcast` (or similarly named) key fits this existing convention. `group_name` independently confirmed NOT to be a reliable 1:1 broadcast flag (see Summary) — reinforces D-08's correctness, not just its stated rationale. |
| D-09 | Reuse `_CROSS_SECTIONAL_SYMBOL`/`'POOLED'`, `is_pooled=True`, `regime=regime_label` row shape | Confirmed: exact same convention at line 3367 (`"symbol": _CROSS_SECTIONAL_SYMBOL`) in the existing per-symbol pooled cell; trivially reusable for broadcast rows. |
| D-10 | New variance-based detector writes `concept_registry.metadata`, new APR key `alpha.ic.broadcast_variance_threshold` | `scripts/ops/alpha/ops_broadcast_feature_audit.py` already implements the read-only half of this (see Summary/Don't Hand-Roll). APR key does not yet exist anywhere in the codebase (grepped, zero hits) — needs a new migration; migration 298 is the exact copy-paste template (see Code Examples). |

## Standard Stack

No new external dependencies. This phase is pure modification of existing internal code (`services/ic_engine.py`, one new/extended internal script, one migration). numpy/scipy/psycopg/asyncpg are already project dependencies and already imported in every file this phase touches.

**Package Legitimacy Audit:** N/A — no new packages installed by this phase.

## Architecture Patterns

### System Architecture Diagram

```
                    feature_vectors (per-symbol rows, incl. 23 broadcast columns)
                              |
                              v
        _compute_cross_sectional_tf(regime_group, tf, regime_label)
        [single call site: main(), line 5658, once per cs_cell_plan entry]
                              |
              +---------------+----------------+
              |                                |
     [fetch phase, per bar_ts chunk]   (NEW, D-05) capture bar_ts
     symbol x feature matrix (X_raw)   alongside existing fetch --
     via Float32ChunkAccumulator       no new query, same chunk_sql
     -- UNCHANGED for per-symbol            |
     (non-broadcast) columns                v
              |                    collapse to one row per bar_ts
              v                    (broadcast feature values, identical
   _compute_one_cross_sectional_cell   across symbols by construction)
   [23 broadcast columns EXCLUDED    + equal-weighted mean(returns_mat)
    from X_nd going forward, D-01]   across symbol_list peers (D-04)
              |                                |
              v                                v
     existing per-symbol POOLED       (NEW) _compute_one_broadcast_cell
     significance rows                [reuses _subsample_and_rank,
     (symbol='POOLED', is_pooled=T)    D-05: never touches
              |                        Float32ChunkAccumulator]
              |                                |
              +---------------+----------------+
                              v
                  feature_ic_scores (SAME table, D-07)
                  [cluster_id -> corpus-level BH-FDR, unchanged mechanism]
                              |
                              v
              ensemble_trainer.py eligibility gate (unmodified, D-07/D-09)

  SEPARATE, upstream/offline path (not in the hot compute loop):
  feature_vectors (empirical sample) --> variance/epsilon-based detector
  (extend ops_broadcast_feature_audit.py, D-10) --> writes
  concept_registry.metadata->>'broadcast' (or similar key)
  [read by _compute_cross_sectional_tf at cell-fetch time to decide the
   column split -- this is the join D-08 specifies]
```

### Recommended Project Structure

No new top-level files/directories needed beyond:
```
services/ic_engine.py                          # modified: delete CONTEXT_FEATURES block,
                                                # thread bar_ts, add _compute_one_broadcast_cell,
                                                # wire into main()'s cs_cell_plan loop
scripts/ops/alpha/ops_broadcast_feature_audit.py  # extended: add --persist flag or a sibling
                                                   # oneshot that writes concept_registry.metadata
                                                   # (Claude's discretion per CONTEXT.md, but this
                                                   # file is the natural extension point, not a
                                                   # new file from scratch)
production/migrations/3NN_ic_broadcast_variance_threshold.sql  # new APR key
tests/unit/test_ic_engine_compute_split.py     # extend existing test file (this phase's
                                                # natural home — already tests both cell functions)
tests/unit/test_ic_engine_fingerprint.py       # extend if a new pass_type is introduced
                                                # (see Open Questions)
```

### Pattern 1: `_subsample_and_rank` kernel reuse (locked by D-05/todo 270)

**What:** The shared rank→IC→bootstrap-CI→walk-forward-fold pipeline, generic over `[n_sub, n_features]` + a matching `returns_scale` vector.
**When to use:** Any new significance-test cell in this codebase — confirmed row/column-agnostic, zero modification needed.
**Example (actual current call site, `_compute_one_cross_sectional_cell`, `services/ic_engine.py:3280`):**
```python
# Source: services/ic_engine.py:3271-3297 (live code, not illustrative)
(
    X_raw_scale,
    ranks_X_scale,
    ranks_Y,
    ic_vector_nd,
    p_vector_nd,
    ci_lower_nd,
    ci_upper_nd,
    fold_ics_list,
) = _subsample_and_rank(
    X_sub_nd,
    valid_mask,
    returns_scale,
    walk_forward_folds=walk_forward_folds,
    embargo_bars=embargo_bars,
    min_reliable_n=min_reliable_n,
    bootstrap_block_size=config.bootstrap_block_size[tf],
    bootstrap_resamples=config.bootstrap_resamples,
    rng=rng,
    max_workers=config.cross_sectional_bootstrap_threads[tf],
    feature_block_columns=config.feature_block_columns,
    bootstrap_early_stop_enabled=config.bootstrap_early_stop_enabled,
    bootstrap_early_stop_check_interval=config.bootstrap_early_stop_check_interval,
    bootstrap_early_stop_tol=config.bootstrap_early_stop_tol,
    bootstrap_early_stop_min_resamples=config.bootstrap_early_stop_min_resamples,
    bootstrap_early_stop_stable_checks=config.bootstrap_early_stop_stable_checks,
)
```
The new `_compute_one_broadcast_cell` calls this identically, just with a much smaller `X_sub_nd` (one row per `bar_ts`, ~23 or fewer columns after excluding degenerate features) and `returns_scale` = the new equal-weighted aggregate-return column instead of a per-symbol `returns_mat` column.

### Pattern 2: `bar_ts` is fetched but discarded — the exact D-05 plumbing gap

**What:** `chunk_sql` already SELECTs `fv.bar_ts` as the first column of every row; every downstream consumer of `batch` skips it.
**Example (current code, the exact three skip points):**
```python
# Source: services/ic_engine.py:3580-3641 (live code)
chunk_sql = f"""
    SELECT fv.bar_ts, {feature_cols}, {return_cols}, {complete_cols}
    FROM feature_vectors fv
    INNER JOIN forward_returns fr ...
"""
...
for chunk_start in range(0, len(regime_timestamps), cs_chunk_ts):
    ...
    batch = chunk_cur.fetchall()
    ...
    # bar_ts is batch[i][0] -- NEVER READ. Feature columns start at index 1:
    X_acc.append_chunk([[r[i + 1] for i in range(n_features)] for r in batch])
    ret_chunk = np.full((n_batch, n_scales), np.nan)
    cmp_chunk = np.zeros((n_batch, n_scales), dtype=bool)
    for i, row in enumerate(batch):
        for j in range(n_scales):
            val = row[1 + n_features + j]            # bar_ts offset (+1) baked into every index
            ret_chunk[i, j] = val if val is not None else np.nan
            cmp_chunk[i, j] = bool(row[1 + n_features + n_scales + j])
```
To satisfy D-05, a plan task needs a fourth accumulator (a plain list of `bar_ts` arrays per chunk, concatenated once via `np.concatenate` — same shape idiom as `ret_chunks`/`cmp_chunks`, NOT routed through `Float32ChunkAccumulator` since `bar_ts` is a timestamp, not a float32-safe numeric). This new array is parallel-indexed to `X_raw`/`returns_mat`/`complete_mat` (same row order, since it's built from the same `batch` iteration) — a plan task can then `np.unique(bar_ts_arr, return_index=True)` (or a pandas groupby) to collapse to one representative row per distinct `bar_ts` for the broadcast feature-value matrix, and use `bar_ts_arr` to group `returns_mat` rows for the equal-weighted-mean aggregate return (D-04).

### Pattern 3: `concept_registry.metadata` read (join pattern for D-08)

**What:** Read a classification flag from `metadata` JSONB at compute time.
**Example (existing project convention, `_watermark_concept_registry`, `services/ic_engine.py:1036-1044`):**
```python
# Source: services/ic_engine.py:1036-1044 (live code — plain psycopg cursor, no ORM)
with conn.cursor() as cur:
    cur.execute(
        "SELECT md5(COALESCE(string_agg("
        "cr.name || '=' || cr.status, '' ORDER BY cr.name), '')) "
        "FROM concept_registry cr JOIN concept_gate cg USING (concept_id) "
        "WHERE cr.domain = 'feature'"
    )
    (status_hash,) = cur.fetchone()
```
The new broadcast-column-split read follows the identical shape: `SELECT name FROM concept_registry WHERE domain='feature' AND metadata->>'broadcast' = 'true'` (or whatever key D-10's detector writes), executed once per `ic_engine.py` invocation (matching the existing "compute once, pass into every cell" convention `_watermark_concept_registry`'s own docstring establishes) rather than once per cell.

### Pattern 4: `concept_registry.metadata` write (migration-time JSONB merge — the pattern for a NON-migration write)

**Example (existing project convention, migration 310, `production/migrations/310_concept_registry_feature_provenance_backfill.sql:33-40`):**
```sql
-- Source: production/migrations/310_concept_registry_feature_provenance_backfill.sql
UPDATE concept_registry cr
SET metadata = cr.metadata || jsonb_build_object(
    'migrated_from', 'feature_registry',
    'migrated_by', 'migration_310_provenance_backfill'
)
WHERE cr.domain = 'feature'
  AND (cr.metadata->>'migrated_from' IS NULL OR cr.metadata->>'migrated_from' = '')
  AND EXISTS (SELECT 1 FROM feature_registry fr WHERE fr.feature_name = cr.name);
```
This is a ONE-TIME migration write. D-10's detector, by contrast, is a repeatable oneshot script (not a migration) — it should use the same `metadata || jsonb_build_object(...)` merge idiom via `asyncpg`/`psycopg`, not `INSERT`/full-row `UPDATE`, so it never clobbers the existing `tier`/`apr_namespace`/etc. keys already on every row (confirmed live — every sampled row already carries 6 metadata keys).

### Pattern 5: New APR key registration (migration template)

`production/migrations/298_ic_engine_bootstrap_early_stop.sql` (full text read; see Code Examples) is the exact copy-paste template: `INSERT INTO config_schema` (with `[initial_estimate]`-tagged description per CLAUDE.md's provenance convention) + `INSERT INTO config_state` (seed value) + `INSERT INTO config_history` (audit trail, `changed_by='migration_3NN'`), all `ON CONFLICT DO NOTHING`, wrapped in `BEGIN; ... COMMIT;`. `alpha.ic.broadcast_variance_threshold` follows this exactly — one key, `value_type='float'`, a conservative starting threshold (the migration should document it as `[initial_estimate]`, not benchmarked, same honesty pattern 298 used for its own five keys).

### Anti-Patterns to Avoid

- **Filtering broadcast features by `group_name`:** Live-verified over-inclusive (`calendar`=30, `session`=62, `macro`=12 rows vs. 23 confirmed-broadcast features). Do not let a plan task use `group_name` as a shortcut for the broadcast set — D-08 already settled this, but it's worth a hard warning since `group_name` LOOKS like exactly the right column at first glance (and IS what `ops_broadcast_feature_audit.py`'s existing report cross-references against, for a different, softer purpose: flagging surprises, not gating).
- **Extending `Float32ChunkAccumulator` to also carry `bar_ts`:** D-05 explicitly rejects this ("never touching the OOM-prone accumulator for its own construction"). `bar_ts` is a timestamp, not float32-safe numeric data anyway — use a plain `list[np.ndarray]` + one `np.concatenate` at the end, mirroring `ret_chunks`/`cmp_chunks`'s own un-accumulator-ed pattern (they're not routed through `Float32ChunkAccumulator` either — only `X_acc` is).
- **Reviving the deleted `CONTEXT_FEATURES` daily-cadence pattern for the new broadcast cell:** That block queried a SEPARATE table (`context_features`, daily cadence, `DISTINCT ON (DATE(bar_ts))`) — a fundamentally different data source from `feature_vectors`. The new broadcast cell reads the SAME `feature_vectors`/`forward_returns` join every other cross-sectional cell reads (at intraday cadence, same `bar_ts` grid), just row-collapsed. Do not accidentally resurrect a query against `context_features` when building the replacement.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Rank→IC→bootstrap-CI→walk-forward pipeline for the broadcast cell | A parallel/simplified statistical kernel | `_subsample_and_rank` (unmodified) | Confirmed fully row/column-agnostic; a second implementation would be an unjustified parallel-system risk in a codebase that already retired one parallel system (`feature_registry`/`concept_registry`, Phase 170) |
| Broadcast-feature detection from scratch | A brand-new detector script | Extend `scripts/ops/alpha/ops_broadcast_feature_audit.py` | It already implements the empirical classification logic (per-`bar_ts` cross-symbol max-min-within-epsilon check) that D-10 calls for; its docstring explicitly anticipated this exact phase and deferred only the persistence step |
| Cluster-ID assignment for the new broadcast rows' BH-FDR participation | A new clustering scheme | `_cluster_features` (already used by `_compute_one_cross_sectional_cell`) on the smaller broadcast matrix, OR the `10000 + idx` singleton-cluster convention the deleted `CONTEXT_FEATURES` block used | Both conventions already exist in this file; reuse whichever fits — do not invent a third `cluster_id` numbering scheme |
| APR key registration boilerplate | Ad hoc `INSERT` statements | Migration 298's exact three-block template (`config_schema`/`config_state`/`config_history`, all `ON CONFLICT DO NOTHING`) | Matches CLAUDE.md's "migrate-as-you-go" + provenance-tag mandate precisely; deviating risks missing the audit-trail requirement |

**Key insight:** This phase's entire "don't hand-roll" surface is internal reuse, not external libraries — the codebase already contains 90% of the primitives this phase needs; the design work is composition (which existing function calls which, in what order), not new algorithms.

## Common Pitfalls

### Pitfall 1: Forgetting the fingerprint/skip-gate mechanism entirely

**What goes wrong:** A plan implements `_compute_one_broadcast_cell` and wires it into `main()`, but the corpus-level incremental-skip mechanism (`ic_cell_fingerprints`, gated by `pass_type`) never learns about it — either the broadcast cell recomputes on every single run regardless of whether anything changed (wasteful, multi-hour corpus runs), or worse, gets silently skipped forever because it accidentally collides with the existing `'cross_sectional'` `pass_type` key and a stale fingerprint from the per-symbol path marks it "already done."
**Why it happens:** CONTEXT.md's `<decisions>` block never mentions `ic_cell_fingerprints` at all — it was out of scope for the 2026-08-21 discussion, which focused entirely on the statistical design, not the incremental-recompute infrastructure this file has accumulated since Phase 162.
**How to avoid:** Plan explicitly for one of: (a) a NEW `pass_type` value (e.g. `'cross_sectional_broadcast'`) with its own fingerprint row per `(cs_symbol_key, tf, training_window_end)`, computed/invalidated alongside the existing `'cross_sectional'` row in the same loop iteration; or (b) fold broadcast computation into the SAME fingerprint row as the per-symbol cross-sectional cell (simpler, but means any future broadcast-only code change forces a needless full per-symbol cross-sectional recompute too, and vice versa). Option (a) is more correct given `_fingerprint_computational_key`'s existing design (the code-content-key component is meant to detect exactly this kind of "this cell's compute logic changed" case). This is a genuine open design call — see Open Questions.
**Warning signs:** A corpus re-run after this phase ships either takes dramatically longer than expected (broadcast cell never skips) or a `passes_fdr` value for a broadcast feature never updates across multiple runs (silently perma-skipped).

### Pitfall 2: `cs_symbol_key` identity for the broadcast cell's fingerprint row

**What goes wrong:** `_upsert_cell_fingerprints` keys per-cell fingerprint rows by `cs_symbol_key` (line 5676), which today is the SAME value used for the per-symbol pooled cross-sectional cell. If the broadcast cell reuses this exact key with a different `pass_type`, that's fine; if a plan task accidentally reuses BOTH the same key AND the same `pass_type`, the two cells' fingerprints collide (one INSERT/UPDATE silently overwrites the other's row on `ON CONFLICT (symbol, tf, pass_type, training_window_end)`).
**Why it happens:** Easy to miss when copy-pasting the existing `_fp_row(cs_symbol_key, tf, "cross_sectional", training_window_end, fp)` call site (line 5676) for the new cell without changing the `pass_type` literal.
**How to avoid:** If going with Pitfall 1's option (a), the new call must use a distinct `pass_type` string, verified against the fingerprint table's actual `ON CONFLICT` columns (`symbol, tf, pass_type, training_window_end` — confirmed at line 1533).
**Warning signs:** A code review or test asserting the two `_fp_row` calls in the modified `main()` use different `pass_type` literals.

### Pitfall 3: Silently changing an existing gate's cardinality via `min_reliable_n`

**What goes wrong:** D-06 explicitly expects "more skips" for broadcast cells since collapsing to one-row-per-`bar_ts` divides N by roughly `n_symbols_in_group` — but this is easy to under-provision for at plan time if the planner doesn't realize `min_reliable_n` (APR default 100, line 725/3204) is a SHARED constant with the per-symbol path, which has no such division.
**Why it happens:** The exact same `config.min_reliable_n` value gates both cell types; a value calibrated for a ~10K-row per-symbol-pooled cell may make almost every broadcast cell (now ~10K / `n_symbols` rows) get skipped, especially for regime-group/`tf` combinations with many peer symbols.
**How to avoid:** D-06 already blesses this as correct behavior for thin slices — the planner should NOT add a separate, lower `min_reliable_n` for broadcast cells without user sign-off (that would be a new locked decision, not implied by CONTEXT.md). Flag this explicitly as an expected outcome in verification criteria ("most/all broadcast cells for high-`n_symbols` regime groups are expected to skip on `min_reliable_n`, this is correct") rather than treating a high skip rate as a bug during phase verification.
**Warning signs:** A verification pass that flags "broadcast feature X has zero `feature_ic_scores` rows" as a regression without checking whether `min_reliable_n` was the (correct) cause.

### Pitfall 4: Breaking `test_ic_engine_compute_split.py`'s reflection-based assertions

**What goes wrong:** Several existing tests in `tests/unit/test_ic_engine_compute_split.py` use `inspect.getsource()`/`inspect.signature()` string/AST assertions against `_compute_cross_sectional_tf` and `_compute_one_cross_sectional_cell` (e.g. `test_compute_cross_sectional_tf_closes_connection_before_clustering` checks that `_compute_one_cross_sectional_cell(` appears textually after the `with` block closes, at a specific indentation). Restructuring these functions for D-05's `bar_ts` threading or D-01's column exclusion can break these tests even if behavior is otherwise correct, because they pin SOURCE SHAPE, not just outputs.
**Why it happens:** This codebase has a documented pattern (162 simplify-pass, todo 125's connection-scoping fix) of using source-introspection tests to pin structural invariants (e.g., "the DB connection must be closed before the multi-hour compute phase begins") that a pure behavioral test can't easily catch.
**How to avoid:** Read `tests/unit/test_ic_engine_compute_split.py` in full before touching either function's structure (696 lines; the relevant assertions are at lines 135-262 per this research's earlier read). Any plan task modifying these two functions' control flow should explicitly check these tests still pass, not just add new tests.
**Warning signs:** `test_compute_cross_sectional_tf_closes_connection_before_clustering` or `test_both_cell_functions_call_subsample_and_rank` failing after a refactor that "looks" behavior-preserving.

## Code Examples

### The exact block to delete (D-01)

```python
# Source: services/ic_engine.py:2801-2811 (block header) through ~3163 (block end,
# immediately before `def _compute_one_cross_sectional_cell` at 3164). Full block
# not reproduced here (362 lines) -- read directly before implementing; this citation
# gives the implementer the exact boundary so no manual re-search is needed.
# ------------------------------------------------------------------
# Context features: daily-cadence features in context_features table.
# vix_z, flight_quality, yield_slope_z are daily-cadence features stored in context_features.
# ...
for cf_idx, cf_name in enumerate(sorted(CONTEXT_FEATURES)):  # deterministic order
    ...
```
Also delete the frozenset itself:
```python
# Source: services/ic_engine.py:217-228
CONTEXT_FEATURES: frozenset[str] = frozenset(["flight_quality", "vix_z", "yield_slope_z"])
```
`grep -rn CONTEXT_FEATURES` (repo-wide, this research session) confirms it is referenced ONLY at lines 228 (definition), 2842 (the loop being deleted), and 3431 (a docstring comment in `_compute_cross_sectional_tf` that should be updated to reflect the new mechanism, not deleted verbatim). No test file references `CONTEXT_FEATURES` by name (`grep -rln CONTEXT_FEATURES tests/` returns zero results) — the test sweep CLAUDE.md's "File/class renames require test sweep" rule calls for is a no-op for this specific symbol, though the surrounding functions' tests (Pitfall 4) still need checking.

### Migration 298 template (full text read; use as literal copy-paste base for the new APR key)

See Pattern 5 above for structure. Full file: `production/migrations/298_ic_engine_bootstrap_early_stop.sql` (132 lines) — read in full during this research session, reproduced in relevant part in Pattern 5.

### The 23-feature confirmed broadcast population (D-02, verbatim from CONTEXT.md, cross-checked live for the sampled subset)

```
dow_sin, dow_cos, month_position, quarter_position, days_to_month_end,
quarter_cycle_sin, quarter_cycle_cos, tdom_sin, tdom_cos,
minute_of_hour_sin, minute_of_hour_cos, hour_of_day_sin, hour_of_day_cos,
week_of_month_sin, week_of_month_cos, day_of_month_sin, day_of_month_cos,
week_of_year_sin, week_of_year_cos, in_ny_session, in_london_kz, in_overlap,
power_hour, opening_range,
vix_z, yield_slope_z, flight_quality,
tip_tlt_ret_z, hyg_lqd_ret_z, sb_corr_fast, sb_corr_slow, sb_corr_z
```
(Counting: 19 calendar/session sin/cos+flag fields — CONTEXT.md's D-02 prose says "15 calendar/session fields" but lists what appears to be 19 distinct field names when `_sin`/`_cos` pairs are counted individually, plus `in_ny_session`/`in_london_kz`/`in_overlap`/`power_hour`/`opening_range` = 5 session-window flags, for 24 total non-macro/non-cross-asset names, +3 macro +5 cross-asset = 32, not 23. **This is a real discrepancy the planner must resolve before writing tasks** — either D-02's "15" was counting sin/cos pairs as one logical field each (19 names → but paired sin/cos might be "10 logical fields" if `dow`, `quarter_cycle`, `tdom`, `minute_of_hour`, `hour_of_day`, `week_of_month`, `day_of_month`, `week_of_year` = 8 pairs = 16 columns, + `month_position`/`quarter_position`/`days_to_month_end` = 3 more = 19 calendar-cycle columns, + 5 session-window flags = 24 total non-macro), or the "23" total in CONTEXT.md/todo 270 is counting differently than the literal name list enumerates. **Do not silently pick a resolution — re-run the row-by-row `concept_registry` cross-check D-02 itself calls for ("verify it's still current... with a row-by-row cross-check against concept_registry") as an early plan task, and let the actual column list drive the count, not the other way around.** This research flags the arithmetic mismatch; it does not resolve it.)

## State of the Art

Not applicable in the usual "library version drift" sense — this is a closed, single-codebase measurement-methodology fix. The relevant "state of the art" is the project's OWN prior architecture decisions, already fully captured in D-01 through D-10 and the Architecture Patterns section above.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | The 23-feature count in D-02/todo 270 is internally consistent (this research found an apparent arithmetic mismatch between "15 calendar/session fields" and the literal list, which enumerates closer to 19-24 names depending on how sin/cos pairs are counted) | Code Examples, "23-feature confirmed broadcast population" | If the planner writes tasks against a miscounted list, some genuinely-broadcast features stay in the per-symbol pooled cell (bug persists) or some genuinely-idiosyncratic features get wrongly excluded (loses real signal measurement). Low probability of being wrong in SUBSTANCE (the underlying feature names are all independently confirmed broadcast via feature_factory.py source reads in todo 270) — the risk is purely in the COUNT/framing, resolvable by one query before implementation. |
| A2 | `ops_broadcast_feature_audit.py`'s existing epsilon-based classifier (`max-min <= 1e-9` per `bar_ts` group) is an acceptable basis for D-10's detector, interchangeable with a "variance ≈ 0" framing | Summary, Don't Hand-Roll | Low risk — both are mathematically equivalent classification criteria for "is this feature identical across symbols at a bar_ts"; the choice between them is Claude's discretion per CONTEXT.md anyway. Flagged only because CONTEXT.md's D-10 text specifically says "variance-based" and the existing script uses max-min, not `np.var` — worth a one-line note in the plan so this isn't read as a discrepancy from D-10, it's an implementation-detail equivalence. |
| A3 | No `REQUIREMENTS.md` file existing in `.planning/` is expected/correct for this phase, not a gap | Phase Requirements | None — explicitly confirmed by the phase brief itself ("this phase predates /gsd-discuss-phase... Do not treat missing requirement IDs as a gap to fill") and independently verified by this research (file genuinely does not exist anywhere under `.planning/`). |

**If this table is empty:** N/A — see above.

## Open Questions

1. **How does the new broadcast cell participate in the `ic_cell_fingerprints` incremental-skip mechanism?**
   - What we know: The existing per-symbol and per-symbol-cross-sectional cells are gated by `pass_type IN ('pooled', 'symbol_hmm', 'cross_sectional')`, keyed `(symbol, tf, pass_type, training_window_end)`. `_compute_cross_sectional_tf`'s single call site (line 5658) already does the fingerprint-check/archive/delete/recompute/UPSERT dance for `pass_type='cross_sectional'`.
   - What's unclear: Whether the new broadcast cell gets its own `pass_type` (e.g. `'cross_sectional_broadcast'`) with an independent fingerprint row, or is folded into the existing `'cross_sectional'` fingerprint (meaning any change to broadcast-cell code forces the per-symbol cross-sectional cell to also recompute, and vice versa — likely wasteful given multi-hour cell compute times).
   - Recommendation: Plan a new `pass_type` value. This needs its own explicit plan task (schema/enum update if `pass_type` is constrained anywhere, e.g. a CHECK constraint — verify before assuming free-text) and its own `_fp_row(...)` call alongside line 5676's existing one. Flag as a design decision for the planner to make explicitly (not silently assumed), since CONTEXT.md's Claude's Discretion section doesn't mention it either.

2. **Does the 23-feature list's literal enumeration match its stated count of 23?**
   - What we know: See Assumptions Log A1 — the literal names in D-02 appear to total more than 23 depending on how sin/cos pairs are counted.
   - What's unclear: Whether this is a benign counting-convention difference or an actual list error (e.g., a feature name accidentally included/excluded).
   - Recommendation: First plan task should be a live `concept_registry`/`_FEATURE_NAMES` cross-check script run (this research's live query pattern, extended to all names in D-02) producing an authoritative, exactly-enumerated column list before any code touches `_compute_one_cross_sectional_cell`'s matrix-splitting logic.

3. **Cluster-ID scheme for the new broadcast rows' BH-FDR participation.**
   - What we know: D-07 requires broadcast rows to enter the SAME BH-FDR family via `cf_cluster_id`, and two existing conventions are available for reuse (`_cluster_features` correlation-based clustering, or the deleted block's `10000 + idx` singleton-ID convention).
   - What's unclear: CONTEXT.md doesn't specify which. Given the broadcast matrix is small (~23-32 columns, one row per `bar_ts`), running `_cluster_features` on it is cheap and gives genuine correlation-aware clustering (e.g. `dow_sin`/`dow_cos` might cluster together) rather than treating every broadcast feature as its own singleton cluster (which the deleted block did, but that block never actually ran BH-FDR at all — `bh_adjusted_p`/`passes_fdr` were hardcoded `None` at lines 3005-3006, a detail worth noting: the OLD per-symbol daily-cadence path never even participated in real FDR correction, so its removal doesn't regress an existing FDR guarantee for these 3 features — it only fixes a DIFFERENT bug, the correlated-multiple-testing one todo 270 names).
   - Recommendation: Reuse `_cluster_features` on the broadcast matrix — matches the per-symbol pooled cell's own approach (D-09's "natural fit, not a special case" framing extends naturally to this too), and is a genuine correctness improvement over the deleted block's never-actually-FDR-corrected behavior.

## Environment Availability

Skipped — this phase has no new external dependencies; all required tooling (Python, numpy/scipy, psycopg/asyncpg, PostgreSQL/TimescaleDB) is already live and in continuous use by `services/ic_engine.py` itself.

## Validation Architecture

`workflow.nyquist_validation` is `true` in `.planning/config.json` (absent-as-enabled would also apply) — section included.

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest (`pytest.ini` + `pyproject.toml` present at repo root) |
| Config file | `/home/bg/dev/indicagent/pytest.ini` |
| Quick run command | `.venv/bin/pytest tests/unit/test_ic_engine_compute_split.py tests/unit/test_ic_engine_fingerprint.py tests/unit/test_ic_engine_incremental_write.py -v` |
| Full suite command | `.venv/bin/pytest tests/unit/ -q` |

### Phase Requirements → Test Map
| Decision | Behavior | Test Type | Automated Command | File Exists? |
|----------|----------|-----------|-------------------|-------------|
| D-01 | `CONTEXT_FEATURES` block/frozenset fully removed | unit (grep-based/static) | `grep -c CONTEXT_FEATURES services/ic_engine.py` (expect 0) | N/A — a shell assertion, not a pytest file; planner should add a pytest wrapper if this needs CI enforcement |
| D-01/D-05 | Existing structural tests on `_compute_cross_sectional_tf`/`_compute_one_cross_sectional_cell` still pass | unit | `.venv/bin/pytest tests/unit/test_ic_engine_compute_split.py -v` | ✅ exists |
| D-05 | `bar_ts` correctly threaded and row-collapse produces exactly one row per distinct `bar_ts` | unit (new) | `.venv/bin/pytest tests/unit/test_ic_engine_compute_split.py::test_broadcast_bar_ts_collapse_one_row_per_timestamp -x` | ❌ Wave 0 — new test, exact function/fixture TBD by planner |
| D-04 | Equal-weighted aggregate return matches manual `returns_mat.mean(axis=1)` for a known peer-symbol fixture | unit (new) | `.venv/bin/pytest tests/unit/test_ic_engine_compute_split.py::test_broadcast_aggregate_return_equal_weighted -x` | ❌ Wave 0 |
| D-06 | Thin broadcast cells correctly skip via `min_reliable_n` | unit (new, or extend existing gate test pattern already used for per-symbol cells) | `.venv/bin/pytest tests/unit/test_ic_engine_compute_split.py -k broadcast_min_reliable -x` | ❌ Wave 0 |
| D-07/D-09 | Broadcast rows use `symbol='POOLED'`, `is_pooled=True`, correct `cluster_id` | unit (new) | `.venv/bin/pytest tests/unit/test_ic_engine_compute_split.py -k broadcast_row_shape -x` | ❌ Wave 0 |
| D-08 | Detector correctly writes/reads `concept_registry.metadata` broadcast flag without clobbering existing keys | integration (needs a real/test DB with `concept_registry`) | `.venv/bin/pytest tests/integration/ -k broadcast_metadata -x` | ❌ Wave 0 — check whether `tests/integration/` has a suitable fixture DB pattern to extend (e.g. `tests/integration/test_concept_parent_lineage.py` is the closest existing precedent, uses a real/test connection) |
| Open Question 1 (fingerprint `pass_type`) | New `pass_type` participates correctly in fingerprint valid/invalid/skip logic | unit | Extend `tests/unit/test_ic_engine_fingerprint.py`'s existing `test_fingerprint_*` pattern with the new `pass_type` value | ❌ Wave 0 |
| D-01 | `_compute_symbol_tf`'s daily-cadence removal doesn't break its OTHER (non-CONTEXT_FEATURES) responsibilities | unit | `.venv/bin/pytest tests/unit/test_ic_engine_compute_split.py::test_compute_symbol_tf_return_keys -x` (existing) | ✅ exists — re-run after deletion, don't just trust it wasn't touched |

### Sampling Rate
- **Per task commit:** Quick run command above (3 targeted files, ~seconds)
- **Per wave merge:** Full suite command (`tests/unit/ -q`)
- **Phase gate:** Full suite green before `/gsd:verify-work`; additionally, per this project's CLAUDE.md Done-Coding SOP, `/simplify` then peer review (`codex`/`agy`) before merge to main — this phase's blast radius (production significance gate, corpus-wide per todo 270) makes the SOP non-optional, not just a suggestion.

### Wave 0 Gaps
- [ ] New unit tests for `_compute_one_broadcast_cell` (row-collapse correctness, aggregate-return correctness, row-shape/cluster-ID correctness, `min_reliable_n` gating) — natural home: extend `tests/unit/test_ic_engine_compute_split.py`, mirroring its existing `_compute_one_cross_sectional_cell` test patterns (e.g. `test_cross_sectional_per_scale_subsample_uses_slice_not_fancy_index`'s source-introspection style, `test_cell_too_large_error_raised_by_both_cell_functions`'s shared-behavior style).
- [ ] New unit tests for the fingerprint `pass_type` extension — extend `tests/unit/test_ic_engine_fingerprint.py` (1,032 lines, already exhaustively covers `pass_type IN ('pooled','symbol_hmm','cross_sectional')` scoping logic at lines 326-398; a fourth value needs equivalent coverage).
- [ ] Integration test (or a documented manual verification step, if no fixture DB is practical) for the `concept_registry.metadata` detector write path — precedent: `tests/integration/test_concept_parent_lineage.py`.
- [ ] Migration test/assertion for the new `alpha.ic.broadcast_variance_threshold` APR key — this project's migrations self-assert via `DO $$ ... RAISE EXCEPTION ... END $$;` blocks (see migration 310's pattern) rather than separate pytest files for data-integrity checks; migration 298 has no such block (pure seed, no assertion) — planner's discretion on whether this key needs one.

## Security Domain

`security_enforcement` not present in `.planning/config.json` → treated as enabled per instructions, but this phase has essentially no attack surface: no new user input, no new network-facing endpoint, no new auth/session/crypto surface. It is a pure internal batch-compute statistical-methodology fix reading/writing existing tables via existing connection patterns.

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | No | No new auth surface |
| V3 Session Management | No | No new session surface |
| V4 Access Control | No | No new access-control surface — same DB role/connection pattern as existing `ic_engine.py` code |
| V5 Input Validation | Marginal | All SQL in this phase follows the existing parameterized-query convention (`%(name)s` psycopg placeholders, `$1`/`$2` asyncpg placeholders) already used throughout `ic_engine.py` — no raw string interpolation of user/external input. `feature_cols`/`return_cols` etc. ARE built via f-string interpolation today (e.g. line 3532 `feature_cols = ", ".join(f'"fv"."{f}"' for f in _FEATURE_NAMES)`), but the interpolated values are hardcoded internal column names from `_FEATURE_NAMES` (derived from `dataclasses.fields(FeatureVector)`), never external input — this is the existing, accepted pattern in this codebase, not a new risk introduced by this phase. |
| V6 Cryptography | No | No new crypto surface |

### Known Threat Patterns for this stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| SQL injection via column-name interpolation | Tampering | Already mitigated by construction — interpolated names are drawn exclusively from `_FEATURE_NAMES` (a fixed, code-defined list from `FeatureVector`'s dataclass fields), never from request/user input. The new broadcast-column-exclusion logic must preserve this invariant: the "which columns are broadcast" list comes from a DB query (`concept_registry.metadata`) that returns FEATURE NAMES, which then get used the same way `_FEATURE_NAMES` already is — verify this list is filtered/intersected against the known-safe `_FEATURE_NAMES` set before being used in any f-string SQL construction, not used directly from the DB read. |

## Sources

### Primary (HIGH confidence — direct code reads this session)
- `services/ic_engine.py` (5,877 lines) — full read of lines 169-260 (constants), 1933-2110 (`_subsample_and_rank`), 2513-2560 (function header context), 2770-3020 (`CONTEXT_FEATURES` daily-cadence block), 3164-3410 (`_compute_one_cross_sectional_cell`), 3409-3690 (`_compute_cross_sectional_tf`), 5600-5700 (`main()`'s cross-sectional dispatch loop), plus targeted greps for `ic_cell_fingerprints`/`pass_type`/`Float32ChunkAccumulator`/`BaseBatch` across the whole file.
- `scripts/ops/alpha/ops_broadcast_feature_audit.py` (225 lines, full read) — pre-existing empirical broadcast-classification script.
- `production/migrations/298_ic_engine_bootstrap_early_stop.sql` (full read) — APR key registration template.
- `production/migrations/310_concept_registry_feature_provenance_backfill.sql` (full read) — `metadata` JSONB write pattern.
- `production/migrations/283_concept_registry_feature_domain_schema.sql` (targeted grep) — confirms `group_name` is a real, separate, unconstrained TEXT column, distinct from `metadata`.
- Live PostgreSQL query against production `concept_registry` (`PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent`) — confirmed `group_name`/`metadata` contents for 11 sampled features, confirmed `group_name` distribution counts (`calendar`=30, `session`=62, `macro`=12).
- `tests/unit/test_ic_engine_compute_split.py` (grepped for test names/structure, 696 lines total).
- `tests/unit/test_ic_engine_fingerprint.py` (grepped for test names/structure, 1,032 lines total).
- `.planning/phases/173-.../173-CONTEXT.md` (full read) — authoritative locked-decision source (D-01 through D-10).
- `.planning/todos/pending/270-broadcast-feature-significance-overstates-effective-n.md` (full read) — problem history, 2026-08-05/07/11/21 investigation timeline.
- `.planning/STATE.md`, `.planning/config.json` (read for project status/nyquist_validation flag).
- `CLAUDE.md` (project root) — read for APR/DAG-invariant/testing conventions.

### Secondary (MEDIUM confidence)
- None — this research required no external web search; the entire domain is internal codebase archaeology with tool-verifiable ground truth.

### Tertiary (LOW confidence)
- None.

## Metadata

**Confidence breakdown:**
- Standard stack: N/A (no external dependencies)
- Architecture: HIGH — every claim traced to a specific line number in live code, cross-checked against a live DB query
- Pitfalls: HIGH — all four pitfalls derived from reading the actual fingerprint/test-suite mechanisms, not speculation
- Open questions: correctly flagged as genuinely unresolved (fingerprint `pass_type` design, the 23-count arithmetic mismatch) rather than papered over

**Research date:** 2026-08-24
**Valid until:** 14 days (this touches a file — `services/ic_engine.py` — under very active development per recent commit history; re-verify line numbers before implementation if more than ~2 weeks elapse or if any other phase touching `ic_engine.py` lands first)
