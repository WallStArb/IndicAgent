---
phase: 112
reviewers: [codex]
reviewed_at: 2026-05-31T01:30:00Z
plans_reviewed: [112-01-PLAN.md, 112-02-PLAN.md, 112-03-PLAN.md]
---

# Cross-AI Plan Review — Phase 112: Plugin Correlation Analysis & Automated Pruning

## Codex Review

### Summary

The phase is well decomposed: Plan 01 lays schema/metrics groundwork, Plan 02 builds the weekly analytical batch, and Plan 03 wires suppression into live I7 execution. The biggest risks are in Plan 02: the self-expiry model is only partially correct unless stale pair rows are deleted or recomputed as absent, the 90-day `signal_ledger` scan likely needs a purpose-built index, and the effective-N correlation matrix is statistically awkward because `directional_r` is agreement-only and never negative. Plan 03 is directionally right and targets the correct executor path, but it should be tightened around typing, test construction, and the "all consumers use `shadow_registry_active`" rule.

### Strengths

- Clear dependency ordering: schema and metric handles first, then batch and executor integration in parallel wave 2.
- Corrects the important `shadow_registry` semantic issue: live/promoted means `NOT is_shadow`, not a nonexistent `promoted` column.
- Good canonical-pair design: `(plugin_a, plugin_b)` PK plus `CHECK (plugin_a < plugin_b)` prevents duplicate pair rows.
- Batch design uses pure functions, making the correlation logic testable outside async DB code.
- The I7 skip gate is planned in the right place: before `self._plugin_cache.get(...)` and before `run_in_executor(...)`, so suppressed plugins do not compute.
- D-06 oneshot handling is included: `JOB_COMPLETED_TOTAL` on success/failure and `flush_and_shutdown_metrics()` in `main()`.
- Plan 03 correctly keeps suppression separate from shadow stamping.

### Concerns

- **[HIGH] Self-expiry is incomplete unless stale `plugin_correlation_pairs` rows are deleted.**  
  The batch UPSERTs qualifying pairs but does not delete rows absent from the current 90-day window. Since `plugin_correlation_pairs` is latest-snapshot UPSERT only, an old row can remain forever with `co_fire_count >= 30` and high `directional_r`. Suppression selection uses in-memory `pairs`, so runtime behavior may be correct, but the persisted table will contain stale rows that downstream consumers (Grafana, diagnostics) will misread.

- **[HIGH] `create_db_pool` must be awaited.**  
  Existing `roll_batch.py` uses `pool = await create_db_pool(...)`. Plan 02 must use the same awaited pattern. If implemented without `await`, `pool.acquire()` will raise a coroutine error at runtime.

- **[HIGH] Effective-N calculation is not a true correlation matrix.**  
  `directional_r = agree_count / co_fire_count` ranges `[0, 1]`, not `[-1, 1]`. Treating it as a correlation matrix loses anti-correlation signal and can inflate independence score. Codex suggests: use agreement-rate `directional_r = agree/co_fire` for redundancy suppression (as designed), but use `signed_r = (agree - disagree) / co_fire` for effective-N eigenvalue computation.

- **[MEDIUM] No deletion strategy for stale pair rows.**  
  The batch specification does not include a step to delete `plugin_correlation_pairs` rows whose `(plugin_a, plugin_b)` are absent from the current 90-day qualifying set. This undermines "latest snapshot only" semantics.

- **[MEDIUM] 90-day scan likely needs a dedicated index.**  
  The existing `idx_signal_ledger_symbol_tf` index is ordered `(symbol, timeframe, timestamp DESC)`. The batch filters by `timestamp`, `direction != 0`, and `signal_schema_version`; this index is not ideal for that access pattern. Plan 02 mentions `EXPLAIN ANALYZE` post-implementation — consider adding a partial index in migration if EXPLAIN confirms a full scan.

- **[MEDIUM] Unused `bootstrap_ci_lower` import will trigger ruff F401.**  
  The suppression decision correctly uses `shadow_registry.last_eval_ci_lower`. If `bootstrap_ci_lower` is imported anywhere in the batch, it must be removed or used.

- **[MEDIUM] `select_suppressions()` EV fallback needs explicit signature.**  
  Plan 02 mentions a fallback from CI to EV when both plugins have `-inf` last_eval_ci_lower. The function signature and dict structure for this fallback should be specified explicitly in the plan; otherwise implementers may silently skip valid suppressions.

- **[MEDIUM] Suppression clear should restrict to `component_type = 'i7_plugin'`.**  
  `UPDATE shadow_registry SET correlation_suppressed=false WHERE correlation_suppressed=true AND component_name != ALL($1)` should add `AND component_type = 'i7_plugin'` to avoid affecting future non-I7 components.

- **[MEDIUM] Empty array `!= ALL($1)` needs explicit cast.**  
  asyncpg type inference may require `$1::text[]` for empty arrays in `component_name != ALL($1)` and `component_name = ANY($1)`.

- **[MEDIUM] `shadow_registry_active` rule ambiguity.**  
  Project rule says "all consumers use `shadow_registry_active` VIEW, never base table." Plan 03 reads base `shadow_registry` for `shadow_cache` and suppressed plugins — which is the correct implementation (cache/governance components need raw state). This deliberate exception should be documented in the plan.

- **[LOW] `CREATE OR REPLACE VIEW ... SELECT *` is brittle.**  
  Future table columns will not automatically appear in the view without recreating it. Acceptable given current use, but weakens the "single interface for future suppression types" claim.

- **[LOW] Metrics naming: `_total` suffix on point gauges is misleading.**  
  `plugin_correlation_redundant_pairs_total` and `plugin_correlation_suppressed_total` use `_total` (implies monotonic counter) but are point gauges. This is per-spec, but is semantically confusing.

- **[LOW] Plan 03 test should assert compute call count, not only task absence.**  
  The acceptance criterion checks that the suppressed plugin is absent from the executor task list. The stronger assertion is: the suppressed plugin's `_compute()` method is never called (zero invocations), confirmed via mock/spy.

### Suggestions

- Add `delete_stale_pairs(conn, current_qualifying_pairs, dry_run)` step after UPSERT: delete `plugin_correlation_pairs` rows whose `(plugin_a, plugin_b)` are not in the current qualifying set.
- Use `signed_r = (agree - disagree) / co_fire` for the effective-N correlation matrix; keep `directional_r = agree / co_fire` for the suppression gate (>= 0.80).
- Restrict suppression SQL to `AND component_type = 'i7_plugin'`.
- Add `::text[]` cast in asyncpg array parameters.
- In Plan 03, type `suppressed_plugins` as `set[str]`, and pass `set(cache_snapshot.suppressed_plugins)` defensively.
- Document the `shadow_registry_active` exception explicitly: "cache loaders and governance tools read the base table; active-plugin consumers use the view."
- Add unit tests for Plan 02 pure functions: canonical ordering, min co-fire filtering, EV fallback, stale clear selection.

### Risk Assessment

**Overall risk: MEDIUM-HIGH.**

Plan 02 has two correctness risks (stale rows not deleted, effective-N using agreement rate not signed correlation) and several medium-severity operational gaps. Plan 03 is lower risk. Plan 01 is low risk. All three HIGH findings should be addressed in the plans before execution.

---

## Consensus Summary

Only one reviewer (Codex) participated in this review (Gemini excluded by -gemini flag; Claude excluded for independence).

### Strengths (Codex)

- Correct two-table schema separation (latest-snapshot vs history)
- VIEW predicate correctly uses `NOT is_shadow` (not nonexistent `promoted` column)
- Skip gate wired before `_compute()`, not after
- D-06 oneshot contract included
- Pure-function batch design enables unit testing

### Agreed Concerns (Codex HIGH)

1. **Stale pair rows not deleted** — batch UPSERTs but does not delete absent pairs from `plugin_correlation_pairs`. Table will accumulate stale rows.
2. **`create_db_pool` must be awaited** — plan text implies synchronous call; must match `roll_batch.py` awaited pattern.
3. **Effective-N uses [0,1] agreement rate instead of [-1,1] signed correlation** — inflates effective independence; fix: use `signed_r = (agree - disagree) / co_fire` for eigenvalue computation.

### Divergent Views

N/A — single reviewer.
