# Phase 121: Lifecycle Replay & Validation - Research

**Researched:** 2026-06-10
**Domain:** Signal lifecycle infrastructure, batch replay, schema alignment, validation reporting
**Confidence:** HIGH

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**D-01: Wave 1 Scope — Renaissance-Grade Clean Replay**
Signal ledger must reflect corrected reality. 4.46M noise signals from broken plugin code (22 shadow setups) are deleted and regenerated. Wave 1 execution sequence is strict:
1. Complete backfill integrity plan
2. Redesign lifecycle_replay.py for current schema
3. Capture before-snapshot
4. Run historical_backfill.py --replay-only --clean scoped to 22 setups
5. Run redesigned lifecycle_replay.py on all pending signals
6. Integrity gate

**D-02: lifecycle_replay.py Redesign Requirements**
- Remove hardcoded cutoff/date constraints: `datetime(2026, 6, 2)`, `'2026-05-21'` window, `--reset-before` default, `--reset-after` default
- Add new signal_outcomes columns to SELECT/UPDATE: `trailing_stop_price`, `staleness_score`, `staleness_trigger_reason`, `chandelier_vol_source`, `shadow_tracking_start_ts`, `shadow_mae`, `shadow_mfe`, `shadow_outcome`, `effective_ts`
- Add new signal_ledger columns to SELECT: `stop_basis`, `stop_type_col`, `structural_stop_distance_atr`, `adaptive_buffer_mult`, `plugin_regime_type`
- `_verify_replay` currently filters `is_shadow = false` — must be updated for shadow signal handling
- Default behavior: process ALL pending signals (no date window). `--after`/`--before` as optional overrides

**D-03: Delete+Regenerate Scope — Exactly 22 Shadow Setups**
Scoped to `_SHADOW_VALIDATION_SETUPS` frozenset in `services/shadow_validator.py`. The 8 GOOD setups (trad_TrendFollowing, trad_MeanReversion, trad_LiquiditySweepReclaim, trad_CHoCHReversal, trad_SqueezeExpansion, trad_SupplyDemandSetup, trad_AnchoredVWAPReversion, trad_VWAPDeviation) are NOT touched.

**D-04: Before-Snapshot — Atomic Capture Before Any Destructive Operation**
Script captures per-setup metrics before DELETE, writes `docs/plans/phase-121-before-snapshot.json`. Query documented in CONTEXT.md. Uses signal_ledger JOIN signal_outcomes.

**D-05: Comparison Report — All 30 Setups, 5 Metrics**
Script: `production/scripts/phase_121_report.py`. Output: `docs/plans/phase-121-validation-report.md`. Mandatory metrics: signal count, selection rate, SNR, calibration correlation, stopped_at_entry count. Cluster rollup: GOOD/MODERATE/NEEDS_REFACTOR.

**D-06: Integrity Gate Before Wave 2**
Hard-fail on: stale signals without outcome, stopped_at_entry in shadow signals, signal_id without signal_outcomes row. Extends `_verify_replay()`.

### Claude's Discretion

None — all decisions are locked.

### Deferred Ideas (OUT OF SCOPE)

- 3-table schema migration (signal_events + trade_framing + trade_execution) — v2.10 Phases 123-125
- Extrinsic composite confidence layer — Phase 4.1
- Shadow promotion — handled by shadow_validator.timer weekly (Phase 120)
- New plugin modifications
</user_constraints>

---

## Summary

Phase 121 has a tightly defined scope: redesign lifecycle_replay.py to match the current schema, execute a plugin-scoped delete+regenerate for 22 shadow setups, run lifecycle replay on 1.54M pending non-shadow signals, then generate a before/after comparison report. The required groundwork (backfill integrity plan Tasks 1-5) is already fully implemented in the codebase — `_load_calibration_curves`, `_load_perf_weights`, and `_assert_backfill_integrity` are all present and wired. Task 6 (the actual clean+replay execution) has NOT yet run.

The critical architectural gap in lifecycle_replay.py is threefold: hardcoded date constraints that prevent full-history replay, a missing plugin-scoped clean mode (--clean in historical_backfill.py deletes by symbol, not by setup_plugin), and a SELECT query that is missing 14 columns added in migrations 112/119. The before-snapshot and report scripts do not exist yet and must be created from scratch using asyncpg (consistent with lifecycle_replay.py driver choice).

**Primary recommendation:** Add a `--setups` filter to historical_backfill.py's `--clean` path, update lifecycle_replay.py's column lists and date constraints, create before-snapshot script, run the operations in strict D-01 sequence, then create phase_121_report.py.

---

## Standard Stack

### Core (verified against codebase)
| Component | Version/Pattern | Purpose | Source |
|-----------|----------------|---------|--------|
| asyncpg | existing in codebase | lifecycle_replay.py and new scripts DB driver | CLAUDE.md |
| psycopg2 | existing in codebase | historical_backfill.py DB driver — do NOT mix | CLAUDE.md |
| `DatabaseManager` | `src/core/database_manager.py` | asyncpg connection pool | codebase |
| `flush_and_shutdown_metrics` | `src/observability/metrics.py` | mandatory oneshot exit pattern | CLAUDE.md D-06 |
| `JOB_COMPLETED_TOTAL` | `src/observability/metrics.py` | oneshot job telemetry | CLAUDE.md D-06 |
| `init_otel_providers` | `src/observability/otel.py` | OTel init with graceful error | codebase |

### Key Constants and Lock Values (must not change)
| Constant | Value | Location |
|----------|-------|----------|
| `_REPLAY_LOCK_ID` | 20260602 | lifecycle_replay.py — changing allows concurrent replays with old ID |
| `ZONE_CHUNK` | 1500 | lifecycle_replay.py `_flush_writes` — 14 params/row; max 21K params |
| `MARKET_CHUNK` | 2000 | lifecycle_replay.py `_flush_writes` — 11 params/row; max 22K params |
| `ACTIVATION_CHUNK` | 4000 | lifecycle_replay.py `_flush_writes` — 6 params/row; max 24K params |
| `SET timescaledb.max_tuples_decompressed_per_dml_transaction = 0` | per-connection | Required before DML on TimescaleDB compressed chunks |

---

## Architecture Patterns

### Verified: Backfill Integrity Plan Status

All 5 code-change tasks (Tasks 1-5) are COMPLETE in historical_backfill.py:
- `_load_calibration_curves(conn, symbol)` — present at line 908
- `_load_perf_weights(conn)` — present at line 941
- Both threaded through `run_i7_and_persist` → `replay_symbol` → `_replay_worker` and single-worker path
- `_assert_backfill_integrity(conn, symbols)` — present at line 1618, wired at line 2159
- Task 6 (the actual clean+replay run) has NOT executed — operational step still pending

**Confidence:** HIGH — verified by grep.

### Critical Gap: --clean Has No Plugin Filter

`historical_backfill.py --clean` deletes by symbol only (lines 2067-2116). The delete SQL is:
```sql
DELETE FROM signal_ledger WHERE symbol = ANY(%s)
```
This would delete ALL plugins for the given symbols, including the 8 GOOD control setups. D-03 requires deletion scoped to the 22 shadow setups only.

**Solution:** Add `--setups` (or `--setup-filter`) flag to historical_backfill.py's `--clean` path. When provided, the delete becomes:
```sql
DELETE FROM signal_ledger 
WHERE symbol = ANY(%s) 
  AND setup_plugin = ANY(%s)
```
The intelligence_features delete CANNOT be scoped by setup_plugin (that table has no such column), so intelligence_features rows should NOT be deleted in the plugin-scoped clean — only signal_ledger and signal_outcomes rows. This is a behavioral change from the full-clean path.

**Alternative:** Run a manual SQL DELETE scoped to the 22 setups before `--replay-only`. Either approach works; adding `--setups` is cleaner and makes the operation reproducible.

### Verified: lifecycle_replay.py v1.2 Schema Drift

**SELECT query missing columns (lines 397-417):**

Current SELECT fetches from signal_ledger:
- Missing: `stop_basis`, `stop_type_col`, `structural_stop_distance_atr`, `adaptive_buffer_mult`, `plugin_regime_type` (added in migration 119)

Current SELECT fetches from signal_outcomes:
- Missing: `trailing_stop_price`, `staleness_score`, `staleness_trigger_reason`, `chandelier_vol_source`, `shadow_tracking_start_ts`, `shadow_mae`, `shadow_mfe`, `shadow_outcome`, `effective_ts` (present in schema, confirmed via information_schema query)

Note: `trailing_stop_price` is `jsonb` type in signal_outcomes — asyncpg returns JSONB as dict automatically (no json.loads needed, per CLAUDE.md).

**Hardcoded date constraints (confirmed by grep):**
- Line 122 (in `_seed_orphan_outcomes`): `AND sl.timestamp >= '2026-05-21'` — hardcoded, must be removed
- Line 1199 (in `main_async`): `cutoff = datetime(2026, 6, 2, 0, 0, 0, tzinfo=UTC)` — hardcoded, must be parameterized
- Lines 1143/1149: `--reset-before` default `2026-06-02T00:00:00Z`, `--reset-after` default `2026-05-21T00:00:00Z` — defaults must become `None`

**`_verify_replay` shadow filter (line 1074):**
Current filter: `AND sl.is_shadow = false`
After regeneration, 22 setups will have shadow signals. The verify check needs to cover shadow signals too, OR be explicitly designed to skip them with documented rationale. D-06 requires a `stopped_at_entry` check on shadow signals specifically — this means shadow signals must be included in verify, not excluded.

### Verified: `_seed_orphan_outcomes` Redesign

Current signature: `_seed_orphan_outcomes(conn, symbols, timeframes, cutoff)` — uses `cutoff` as upper bound and hardcodes `'2026-05-21'` as lower bound. The redesigned version should seed ALL orphans (no date window):

```python
async def _seed_orphan_outcomes(conn, symbols, timeframes) -> int:
    result = await conn.execute(
        """INSERT INTO signal_outcomes (signal_id, status)
           SELECT sl.signal_id, 'pending'
           FROM signal_ledger sl
           LEFT JOIN signal_outcomes so ON sl.signal_id = so.signal_id
           WHERE so.signal_id IS NULL
             AND sl.symbol = ANY($1)
             AND sl.timeframe = ANY($2)
           ON CONFLICT (signal_id) DO NOTHING""",
        symbols,
        timeframes,
    )
    return int(result.split()[-1])
```

### Verified: Data State as of 2026-06-10

From live DB queries:
- Total signals: 7,443,348 (7.44M)
- Non-shadow pending: 1,541,462 (~1.54M)
- Shadow signals: 16,657 (tiny — live accumulation since Phase 120 deployment)
- Non-shadow signals using 22 shadow setup names: 5,170,783 — these are the old noise signals to delete+regenerate
- Active work queue for lifecycle_replay: 286 (symbol, timeframe) pairs across 79 symbols

The 22 setups' non-shadow rows total ~5.17M — not 4.46M as mentioned in CONTEXT.md. The delta is recent accumulation from live pipeline. The before-snapshot captures the actual numbers.

setup_performance: 0 rows (TRUNCATED — no ml-training run yet)
swarm_agent_weights: 8 rows (stale from before last truncate)

### Inconsistency: trad_VWAPDeviation in Both "GOOD" and "Shadow 22"

D-03 lists trad_VWAPDeviation as one of the 8 GOOD setups NOT to touch. However, `_SHADOW_VALIDATION_SETUPS` in `shadow_validator.py` includes `trad_VWAPDeviation` (confirmed at line 72). And `_PHASE_119_PLUGINS` in `register_plugins.py` includes `vwap_deviation_plugin.name` at line 682.

**Resolution:** `_SHADOW_VALIDATION_SETUPS` is the authoritative list per CONTEXT.md canonical refs. D-03 is inconsistent with the frozenset. The planner must note this: trad_VWAPDeviation IS in the 22 shadow setups and WILL be deleted+regenerated. The 8 GOOD setups listed in D-03 appear to be the 8 setups that were always GOOD (never in NEEDS_REFACTOR) and are NOT in shadow mode — trad_VWAPDeviation was explicitly refactored in Phase 119 and placed in shadow. D-03's "8 GOOD setups" list contains an error. Use `_SHADOW_VALIDATION_SETUPS` (len == 22) as the ground truth for the delete scope.

### Replay Resource and Timing

**Work queue magnitude:** 286 (symbol, timeframe) pairs, 1.54M pending signals for lifecycle replay. The largest single pairs are 65-95K pending signals (USDJPY/1m, NQM6/1m, etc.). At --workers 8, pairs run concurrently. Each pair streams bars from market_data_ohlcv using client-side LIMIT/OFFSET batching (BATCH_SIZE=1000), evaluating every pending signal against every bar since min(signal.timestamp).

**Estimated duration:** No prior run log exists. The 7.44M total signals with 1.54M pending across 286 pairs and 79 symbols is a substantial job. With --workers 8 and asyncio.gather concurrency, expect 30-90 minutes depending on bar depth per symbol. Incremental commits every 1000 resolved signals make the job resumable.

**setup_performance and swarm_agent_weights:** These are ALREADY empty/stale (confirmed). The `_reset_corrupt_data` in lifecycle_replay.py TRUNCATEs them when `--reset` is passed. They repopulate on: setup_performance — nightly ml-training (11pm); swarm_agent_weights — weekly ml-orchestrator (Monday). The lifecycle replay doc header comment already documents this (lines 38-42).

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Signal outcome evaluation | Custom stop/target logic | `evaluate_signal()`, `evaluate_market_entry()` from `lifecycle_tracker.py` | Already handles all 8 outcome types, chandelier state, staleness, TTL |
| Stop outcome classification | Custom if/else | `_classify_stop_outcome(mfe, bars)` | `OUTCOME_THRESHOLD_QUICK_STOP_BARS = 2` calibration baked in |
| DB write batching | Custom chunking | Existing `_flush_writes` with ZONE_CHUNK/MARKET_CHUNK/ACTIVATION_CHUNK | PostgreSQL 32767 param limit already solved |
| Calibration loading | Custom query | `_load_calibration_curves(conn, symbol)` — already in historical_backfill.py | Handles global vs symbol-specific resolution |
| Perf weight loading | Custom query | `_load_perf_weights(conn)` — already in historical_backfill.py | Uses same `_compute_perf_multipliers` as live pipeline |
| Incremental commit | Custom approach | Existing `commit_every` pattern in `_process_symbol_tf` | Already handles resumability correctly |

---

## Common Pitfalls

### Pitfall 1: --clean Deletes ALL Setups for a Symbol
**What goes wrong:** Running `historical_backfill.py --replay-only --clean` without a setup filter wipes all 30 setups' signals for every active symbol. The 8 GOOD control setups' data is destroyed.
**Why it happens:** `--clean` was designed for full wipes, not plugin-scoped wipes.
**How to avoid:** Must add `--setups` filter to the `--clean` path before running. Alternatively: run a manual SQL delete scoped to the 22 setup names, then run `--replay-only` (without `--clean`).

### Pitfall 2: intelligence_features Cannot Be Setup-Scoped
**What goes wrong:** If `--clean` logic tries to scope the `intelligence_features` delete to the 22 setups, it will fail — `intelligence_features` has no `setup_plugin` column.
**Why it happens:** intelligence_features stores per-bar feature vectors, not per-setup. Multiple setups share the same feature row.
**How to avoid:** In the plugin-scoped clean, delete only from `signal_outcomes` and `signal_ledger` WHERE `setup_plugin = ANY(shadow_22)`. Do NOT delete `intelligence_features` in a plugin-scoped clean — bars must remain for the replay to re-evaluate.

### Pitfall 3: lifecycle_replay.py _verify_replay Excludes Shadow Signals
**What goes wrong:** The current `_verify_replay` has `AND sl.is_shadow = false`. After regeneration, shadow signals will exist as pending and won't be checked. D-06 requires a `stopped_at_entry` check specifically on shadow signals.
**Why it happens:** v1.2 was written before shadow signals existed in volume.
**How to avoid:** Update `_verify_replay` to either (a) run two passes — one for non-shadow, one for shadow — or (b) remove the is_shadow filter and adjust the stale-unresolved check to account for shadow signals' lifecycle.

### Pitfall 4: Missing asyncpg Column Coercion for trailing_stop_price
**What goes wrong:** `trailing_stop_price` is `jsonb` in signal_outcomes. asyncpg returns JSONB as Python dict natively. If the replay code tries to do json.loads() on it, it will fail with TypeError.
**Why it happens:** New column type differs from float/int columns.
**How to avoid:** Use the dict directly. Per CLAUDE.md: "JSONB → dict (no json.loads()/json.dumps())."

### Pitfall 5: Hardcoded Advisory Lock Release in Error Path
**What goes wrong:** The advisory lock acquired at `_acquire_replay_lock` in the preflight must be released in the `finally` block. The current code does this (line 1206), but any new code path must also release.
**Why it happens:** pg_try_advisory_lock is session-scoped; if the connection is returned to the pool without unlocking, the lock is held until that connection closes.
**How to avoid:** Preserve the try/finally pattern around all advisory lock usage.

### Pitfall 6: Before-Snapshot Must Use Signal_Ledger JOIN Signal_Outcomes
**What goes wrong:** If snapshot query uses signal_ledger alone and misses signal_outcomes JOIN, `pnl_r` and calibration_corr will always be NULL.
**Why it happens:** Phase 104 split — lifecycle fields live in signal_outcomes.
**How to avoid:** Always JOIN on `sl.signal_id = so.signal_id` (LEFT JOIN to include signals without outcomes).

### Pitfall 7: D-03 GOOD Setups List Inconsistency
**What goes wrong:** D-03 lists trad_VWAPDeviation as a GOOD setup NOT to touch. But `_SHADOW_VALIDATION_SETUPS` includes it (confirmed). Using D-03's list as-is would leave VWAPDeviation's broken signals intact.
**Why it happens:** D-03 text contains an error — the "8 GOOD" list was written from memory, not from code.
**How to avoid:** Use `_SHADOW_VALIDATION_SETUPS` frozenset (len == 22, assert verified) as the authoritative delete scope. Do not use the D-03 text as the list source.

---

## Code Examples

### Verified: Full Column List for lifecycle_replay.py SELECT (after D-02 update)

```python
# signal_ledger columns (add stop_basis group from migration 119):
# sl.stop_basis, sl.stop_type_col, sl.structural_stop_distance_atr,
# sl.adaptive_buffer_mult, sl.plugin_regime_type

# signal_outcomes columns (add shadow/staleness group from migration 112):
# so.trailing_stop_price, so.staleness_score, so.staleness_trigger_reason,
# so.chandelier_vol_source, so.shadow_tracking_start_ts,
# so.shadow_mae, so.shadow_mfe, so.shadow_outcome, so.effective_ts
```

Source: `production/migrations/112_update_signal_ledger_full_view.sql` and `119_framing_audit_trail.sql` — confirmed authoritative via direct file read.

### Verified: _seed_orphan_outcomes Redesign Pattern

```python
async def _seed_orphan_outcomes(
    conn, symbols: list[str], timeframes: list[str]
) -> int:
    """Seed ALL missing signal_outcomes rows — no date window."""
    result = await conn.execute(
        """INSERT INTO signal_outcomes (signal_id, status)
           SELECT sl.signal_id, 'pending'
           FROM signal_ledger sl
           LEFT JOIN signal_outcomes so ON sl.signal_id = so.signal_id
           WHERE so.signal_id IS NULL
             AND sl.symbol = ANY($1)
             AND sl.timeframe = ANY($2)
           ON CONFLICT (signal_id) DO NOTHING""",
        symbols,
        timeframes,
    )
    return int(result.split()[-1])
```

### Verified: Plugin-Scoped Delete Pattern (for --setups filter)

```python
# historical_backfill.py --clean path with --setups filter
# Delete outcomes first (no FK cascade), then ledger entries
setup_values = list(_SHADOW_VALIDATION_SETUPS)  # 22 names

cur.execute(
    """DELETE FROM signal_outcomes
       WHERE signal_id IN (
           SELECT signal_id FROM signal_ledger 
           WHERE symbol = ANY(%s) AND setup_plugin = ANY(%s)
       )""",
    (symbol_values, setup_values),
)
cur.execute(
    """DELETE FROM signal_ledger
       WHERE symbol = ANY(%s) AND setup_plugin = ANY(%s)""",
    (symbol_values, setup_values),
)
# Note: do NOT delete intelligence_features — no setup_plugin column
```

### Verified: Before-Snapshot Query

```sql
SELECT
    sl.setup_plugin,
    sl.is_shadow,
    COUNT(*) as total_signals,
    COUNT(CASE WHEN sl.was_selected THEN 1 END) as selected,
    COUNT(CASE WHEN sl.was_selected THEN 1 END)::float / NULLIF(COUNT(*), 0) as selection_rate,
    AVG(CASE WHEN so.pnl_r IS NOT NULL THEN so.pnl_r END) as avg_pnl_r,
    CORR(sl.cis_score, (so.pnl_r > 0)::int) FILTER (WHERE so.pnl_r IS NOT NULL) as calibration_corr
FROM signal_ledger sl
LEFT JOIN signal_outcomes so ON sl.signal_id = so.signal_id
GROUP BY sl.setup_plugin, sl.is_shadow
ORDER BY total_signals DESC
```

Source: CONTEXT.md D-04 — exact SQL specified by user.

### Verified: Integrity Gate Extensions (D-06)

```python
# In _verify_replay, additional checks to add for shadow signals:
"""
SELECT
    COUNT(CASE WHEN so.outcome = 'stopped_at_entry'
               AND sl.is_shadow = true
               AND sl.setup_plugin = ANY($3)  -- 22 shadow setups
          THEN 1 END) as shadow_stopped_at_entry,
    COUNT(CASE WHEN sl.signal_id IS NOT NULL
               AND so.signal_id IS NULL
          THEN 1 END) as orphan_ledger_rows
FROM signal_ledger sl
LEFT JOIN signal_outcomes so ON sl.signal_id = so.signal_id
WHERE sl.symbol = ANY($1) AND sl.timeframe = ANY($2)
"""
# Hard-fail conditions (raise RuntimeError):
# 1. shadow_stopped_at_entry > 0 (Phase 117 fix must eliminate all stopped_at_entry for shadow setups)
# 2. orphan_ledger_rows > 0 (Phase 104 invariant)
# 3. Existing: stale_unresolved > 0 (signals older than 2 days with NULL outcome)
```

### Verified: JOB_COMPLETED_TOTAL Pattern

```python
# At script exit — mandatory per CLAUDE.md D-06
from src.observability.metrics import JOB_COMPLETED_TOTAL, flush_and_shutdown_metrics

JOB_COMPLETED_TOTAL.add(1, {"job": "lifecycle-replay", "status": "success"})
flush_and_shutdown_metrics()
# job label MUST match systemd unit %n suffix exactly (kebab-case)
```

---

## State of the Art

| Area | Current State | Required Change | Confidence |
|------|--------------|-----------------|------------|
| Backfill integrity plan (Tasks 1-5) | DONE — all 3 functions present and wired | Task 6 (operational run) still pending | HIGH |
| lifecycle_replay.py SELECT columns | Missing 14 columns from migrations 112/119 | Add to both SELECT and UPDATE paths | HIGH |
| lifecycle_replay.py date constraints | 3 hardcoded dates prevent full-history replay | Remove/parameterize all 3 | HIGH |
| --clean plugin scoping | Deletes by symbol only | Add --setups filter for plugin-scoped clean | HIGH |
| _verify_replay shadow coverage | Excludes is_shadow=true entirely | Include shadow signals in integrity checks | HIGH |
| before-snapshot script | Does not exist | Create production/scripts/phase_121_before_snapshot.py | HIGH |
| phase_121_report.py | Does not exist | Create from scratch | HIGH |
| setup_performance | 0 rows (empty) | Will repopulate nightly after lifecycle data fills | HIGH |
| swarm_agent_weights | 8 stale rows | Will be truncated by --reset, repopulate weekly | HIGH |

---

## Open Questions

1. **Does lifecycle_replay.py need to SELECT the new signal_outcomes columns to pass them to evaluate_signal()?**
   - What we know: `evaluate_signal()` accepts `chandelier_state`, `staleness_consecutive_bars`, `staleness_score` as kwargs. The new columns (`staleness_score`, `chandelier_vol_source`, etc.) are OUTPUTS of the live signal_tracker, not inputs to the evaluator. The replay re-evaluates from scratch using bar data — it does not pass pre-existing staleness scores into the evaluator.
   - What's unclear: Whether D-02 intends "add to SELECT" so we can log/preserve them during partial resets, or just to avoid SELECT * breakage.
   - Recommendation: Add them to SELECT for schema-completeness (prevents future breakage), but don't thread them into evaluate_signal(). The evaluator will compute fresh staleness state from bar data.

2. **`--reset` flag behavior with plugin-scoped clean**
   - What we know: `--reset` in lifecycle_replay.py resets signal_outcomes (not deletes signal_ledger). `--clean` in historical_backfill.py deletes signal_ledger rows. These are different operations.
   - What's unclear: After the plugin-scoped clean, should lifecycle_replay.py's `--reset` still be offered? The remaining non-shadow signals have pre-existing outcomes and may not need reset.
   - Recommendation: Don't use `--reset` in lifecycle_replay.py for this phase. The non-shadow signals already have correct outcomes for resolved signals. Only PENDING signals need replay.

3. **intelligence_features deletion in plugin-scoped clean**
   - What we know: `intelligence_features` has no `setup_plugin` column. Deleting it by symbol would also delete features used by the 8 GOOD setups.
   - What's unclear: Whether re-running backfill for the 22 shadow setups requires re-generating intelligence_features, or whether the existing feature rows are reusable.
   - Recommendation: Do NOT delete intelligence_features in the plugin-scoped clean. The historical bars are stored in market_data_ohlcv; the backfill `--replay-only` will re-use existing bars and generate new signals by re-running I1-I7 pipeline. Intelligence_features rows represent per-bar feature vectors — they do not need to be regenerated if the underlying bars are unchanged.

---

## Sources

### Primary (HIGH confidence)
- Direct file reads: `production/scripts/lifecycle_replay.py` v1.2 — full codebase analysis
- Direct file reads: `production/scripts/historical_backfill.py` v1.4 — full --clean and --replay-only paths
- Direct file reads: `production/migrations/112_update_signal_ledger_full_view.sql` — exact signal_ledger_full column list
- Direct file reads: `production/migrations/119_framing_audit_trail.sql` — 5 new signal_ledger columns
- Direct file reads: `production/migrations/121_signal_ledger_shadow_view.sql` — shadow view definition
- Direct file reads: `services/shadow_validator.py` — `_SHADOW_VALIDATION_SETUPS` frozenset (22 setups, verified)
- Direct file reads: `src/intelligence/register_plugins.py` — `_PHASE_119_PLUGINS` (17 setups) + Phase 118 (5 setups)
- Live DB queries — signal counts, setup breakdown, pending counts, signal_outcomes column schema
- `.planning/phases/121-lifecycle-replay-validation/121-CONTEXT.md` — locked decisions

### Secondary (MEDIUM confidence)
- `.planning/STATE.md` — Phase 121 status context
- `docs/plans/2026-06-06-backfill-signal-integrity-plan.md` — Tasks 1-5 completion status inferred from grep

---

## Metadata

**Confidence breakdown:**
- Backfill integrity plan status: HIGH — functions confirmed present via grep
- lifecycle_replay.py schema drift: HIGH — verified against actual migration SQL and information_schema
- --clean plugin scoping gap: HIGH — code verified; no --setups or setup_plugin filter exists
- Data counts: HIGH — live DB queries as of 2026-06-10
- Timing estimates: LOW — no prior replay log, estimated from pair count and signal volume
- VWAPDeviation inconsistency: HIGH — both frozenset and D-03 text verified

**Research date:** 2026-06-10
**Valid until:** 2026-06-17 (data counts change daily; schema stable)
