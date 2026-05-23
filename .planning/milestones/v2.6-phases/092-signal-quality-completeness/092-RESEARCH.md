# Phase 092: Signal Quality Completeness - Research

**Researched:** 2026-05-20
**Domain:** Signal metrics computation, DB schema migration, shadow governance gate
**Confidence:** HIGH

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**New Metrics (D-01 through D-03):**
- Six new columns: `skewness`, `kurtosis`, `min_r`, `p5_r`, `recovery_factor`, `cvar_5`
- All are `float` / nullable. NULL thresholds: skewness/kurtosis n<3, min_r/recovery_factor n<30, p5_r/cvar_5 n<20
- `SignalMetricsResult` gains six new optional fields with `None` defaults
- Extract `_distribution_shape(pnl_rs, avg_mfe)` as a standalone pure function returning `DistributionShape` dataclass

**DB Schema Migration (D-04 through D-06):**
- `entry_type text NOT NULL DEFAULT '*'` added to `signal_metrics` table AND to PK
- PK drop+recreate guarded by `information_schema.key_column_usage` check
- Migration is idempotent: all steps use `ADD COLUMN IF NOT EXISTS`
- `signal_metrics` writer upsert ON CONFLICT clause must include `entry_type`

**Per-Symbol and Per-Entry-Type Segmentation (D-07 through D-10):**
- Three accumulation dicts: `by_group`, `by_symbol`, `by_entry_type`
- Per-symbol × per-entry_type cross product deferred to 092.1
- Signal ledger query gains `entry_type` column in SELECT
- NULL entry_type rows in signal_ledger fold into global only (not per-entry_type)

**Compute Logic (D-11 through D-12):**
- `_distribution_shape()` is pure with `DistributionShape` dataclass return
- `scipy.stats.skew` and `scipy.stats.kurtosis` imported as `_scipy_skew`, `_scipy_kurtosis`

**Shadow Governance Tail Gate (D-13 through D-17):**
- Gate fires in existing `_check_promotion()` BEFORE the promotion check
- Queries signal_metrics WHERE `symbol='*' AND entry_type='*' AND track='market'`
- Thresholds: `TAIL_GATE_MIN_SKEWNESS = -2.0`, `TAIL_GATE_MIN_RECOVERY = 0.5`
- NULL values skip gate (don't block)
- Pure function: `_tail_risk_blocks_promotion(skewness, recovery_factor, min_skewness, min_recovery) -> bool`
- OTel: `SHADOW_TAIL_RISK_BLOCKED` counter, labels `{"plugin": name, "reason": "skewness"|"recovery_factor"}`

**Plan Structure (D-18):**
- Plan 01: DB migration + SignalMetricsResult + writer upsert + `_distribution_shape()` + unit tests
- Plan 02: Per-symbol + per-entry_type grouping in compute agent + integration test
- Plan 03: Tail gate in shadow_auditor + pure function + OTel counter + unit tests

### Claude's Discretion
None specified.

### Deferred Ideas (OUT OF SCOPE)
- Per-symbol x per-entry_type cross product (revisit in 092.1)
- Maximum drawdown series (full drawdown curve)
- IC decay curve
- Benchmark-relative metrics (alpha vs SPY)
- Per-plugin tail gate thresholds in shadow_registry
</user_constraints>

---

## Summary

Phase 092 adds six distribution-shape metrics to `signal_metrics`, extends compute to run per-symbol and per-entry_type in addition to the global '*' aggregate, and wires tail-risk thresholds into the shadow governance promotion gate. The implementation is a pure extension of existing infrastructure with no new services or timers.

The existing code is well-structured for this extension. `_build_metrics_result()` is a clean pure function that needs only a new `entry_type` parameter and six new return fields. The accumulation loop in `compute_signal_metrics()` already handles per-symbol grouping and requires straightforward extension to per-entry_type. The shadow auditor's gate functions are already pure and tested in isolation.

The key structural constraint: `signal_metrics` PK currently has six columns (confirmed from DB). Adding `entry_type` requires a PK rebuild, which must be guarded by an idempotent check. The `MetricsComputedEvent` Pydantic schema in `schemas.py` has `extra="forbid"` so it must also receive new fields or they must be optional-defaulted to avoid runtime rejection.

**Primary recommendation:** Implement in the locked three-plan sequence. Plan 01 establishes all schema and compute primitives; Plan 02 adds grouping; Plan 03 wires governance. Each plan is independently testable.

---

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| scipy | >=1.15.0 | `skew()`, `kurtosis()` | Already in requirements.txt; already imported in compute.py |
| numpy | (transitive) | `percentile()` for p5_r | Already used in stats_utils.py |
| asyncpg | (project standard) | DB pool + schema migration | Project-wide DB standard |

**Installation:** No new dependencies. scipy already in requirements.txt line: `scipy>=1.15.0`.

---

## Architecture Patterns

### Current File Map

```
src/intelligence/metrics/
  compute.py              — pure compute functions; _build_metrics_result(), SignalMetricsResult
services/
  signal_metrics_compute_agent.py   — timer agent, accumulation loop, Kafka publish
  signal_metrics_writer_agent.py    — consumes topic, upserts signal_metrics table
  shadow_auditor_agent.py           — pure gate functions, _check_promotion()
src/intelligence/schemas.py         — MetricsComputedEvent, SignalMetricsEvent union
src/observability/metrics.py        — OTel counter registry
src/core/stats_utils.py             — bootstrap_ci_lower() as pattern for gate functions
tests/unit/intelligence/test_metrics_compute.py
tests/unit/service_tests/test_signal_metrics_writer_agent.py
tests/unit/test_shadow_auditor_agent.py
```

### Pattern 1: Pure Compute Functions (reference: compute.py)

All new metrics derive from `pnl_rs` and `mfes` only. No new accumulator fields. The accumulator dict structure is:
```python
{
    "pnl_rs": list[float],
    "maes": list[float],
    "mfes": list[float],
    "win_flags": list[bool],
    "n_never_activated": int,
    "n_total": int,
    "n_outliers": int,
}
```
`_distribution_shape()` receives `pnl_rs` and `avg_mfe` (computed inline in `_build_metrics_result()`).

### Pattern 2: ensure_schema() Self-Managing Migration

`feature_validation_compute_agent.py` does NOT use `ensure_schema()` — it runs schema migration at startup via direct asyncpg pool calls. The pattern for this phase is:
- Add a `_ensure_schema(conn)` async function called at agent `_setup()` time
- Each `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` is idempotent
- PK rebuild wrapped in a `DO $$ ... $$` block that checks `information_schema.key_column_usage` before dropping

### Pattern 3: Pure Gate Functions (reference: shadow_auditor_agent.py)

The existing gate functions are module-level pure functions tested directly:
```python
def _should_promote(n, ci_lower, min_n, min_ev_r) -> bool: ...
def _should_demote(new_count, min_evaluations) -> bool: ...
def _ev_r_below_threshold(ev_r, threshold) -> bool: ...
```
`_tail_risk_blocks_promotion()` follows this exact pattern.

### Pattern 4: OTel Counter Registration (reference: metrics.py)

```python
SHADOW_TAIL_RISK_BLOCKED = _meter.create_counter(
    "shadow_tail_risk_blocked_total",
    description="Shadow promotions blocked by tail-risk gate (skewness or recovery_factor)",
)
```
Import in `shadow_auditor_agent.py` alongside existing shadow metrics. Call: `SHADOW_TAIL_RISK_BLOCKED.add(1, {"plugin": name, "reason": "skewness"})`.

### Anti-Patterns to Avoid

- **Rebuilding PK without guard**: DROP CONSTRAINT then ADD CONSTRAINT without checking if entry_type already in PK will crash on second startup.
- **Adding new fields to MetricsComputedEvent without defaults**: The Pydantic model uses `extra="forbid"`. New fields added to the compute agent's publish dict must have matching optional fields in MetricsComputedEvent or the writer will DLQ every event.
- **Computing `_distribution_shape()` outside `_build_metrics_result()`**: Keep it called from within `_build_metrics_result()` so all three grouping passes (global, per-symbol, per-entry_type) get distribution shape automatically.
- **Querying signal_metrics in shadow_auditor with wrong entry_type filter**: Must specify `AND entry_type='*'` or promotion gate reads per-entry_type rows, getting wrong n.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Fisher-Pearson skewness | Custom formula | `scipy.stats.skew(pnl_rs, bias=False)` | Bias correction is non-trivial; scipy handles degrees-of-freedom correction |
| Excess kurtosis | Custom formula | `scipy.stats.kurtosis(pnl_rs, fisher=True, bias=False)` | Fisher=True gives excess kurtosis (0=normal); bias=False corrects for small sample |
| 5th percentile | Manual sort+index | `np.percentile(pnl_rs, 5)` | Edge cases with small N, interpolation behavior |
| Idempotent PK migration | Custom check | `information_schema.key_column_usage` + `DO $$ ... $$` | Standard PostgreSQL pattern; `ADD CONSTRAINT IF NOT EXISTS` not available pre-PG15 |

**Key insight:** scipy is already imported in compute.py (`from scipy.stats import t as _scipy_t`). Adding skew and kurtosis is two more names in the same import line. Zero dependency overhead.

---

## Common Pitfalls

### Pitfall 1: MetricsComputedEvent extra="forbid" rejection
**What goes wrong:** Compute agent publishes `skewness`, `kurtosis` etc. in the event dict. Writer agent validates via `SignalMetricsEvent` discriminated union. `MetricsComputedEvent` has `extra="forbid"`. Pydantic rejects the event and DLQs it.
**Why it happens:** The Pydantic schema gates every inbound Kafka message in `BaseWriterAgent._parse_payload()`.
**How to avoid:** Plan 01 must update `MetricsComputedEvent` in `schemas.py` to add six optional fields with `None` defaults: `skewness: float | None = None`, etc. Also add `entry_type: str = "*"`.
**Warning signs:** Writer log shows `signal_metrics_writer.unknown_event_type` or DLQ depth growing after Plan 01 deploy.

### Pitfall 2: ON CONFLICT clause missing entry_type after PK migration
**What goes wrong:** Writer upsert uses old `ON CONFLICT (track, setup_plugin, tf, regime_type, window_days, symbol)`. After PK migration, PostgreSQL will reject the upsert with "there is no unique or exclusion constraint matching the ON CONFLICT specification".
**Why it happens:** The ON CONFLICT clause must exactly match the new PK.
**How to avoid:** Plan 01 updates `_handle_metrics_computed()` in `signal_metrics_writer_agent.py` to include `entry_type` in both the INSERT column list and ON CONFLICT clause. The event dict must supply `entry_type` (default `'*'`).

### Pitfall 3: Kafka message key missing entry_type (duplicate key collisions)
**What goes wrong:** Compute agent publishes with key `metrics:{track}:{plugin}:{tf}:{regime}:{window}:{symbol}`. Two rows with different `entry_type` get the same Kafka key, causing one to overwrite the other in the consumer.
**Why it happens:** Kafka key is used for partition routing, not dedup — but if the consumer processes messages in order and the writer upserts by PK, there's no functional collision. However, keys should still be unique per PK tuple for debuggability.
**How to avoid:** Add `entry_type` to the Kafka message key in Plan 02: `metrics:{track}:{plugin}:{tf}:{regime}:{window}:{symbol}:{entry_type}`.

### Pitfall 4: signal_ledger idx_ledger_metrics_compute missing entry_type
**What goes wrong:** The `_QUERY` in `signal_metrics_compute_agent.py` does not include `entry_type`. The existing index `idx_ledger_metrics_compute` INCLUDEs `outcome, was_selected, signal_id, direction, entry_price, stop_loss, pnl_r, hmm_regime_at_fire, symbol` but NOT `entry_type`. Fetching `entry_type` will not be covered by this index and requires a heap fetch.
**Why it happens:** The covering index was built before entry_type segmentation was planned.
**How to avoid:** This is acceptable for now — the query fetches ~1.27M rows regardless and is already a full index scan. Adding `entry_type` to the SELECT causes one additional heap fetch per row but doesn't change the query plan materially. Document this as a potential optimization for 092.1.

### Pitfall 5: PK rebuild race on concurrent startups
**What goes wrong:** Two instances of signal_metrics_writer_agent start simultaneously. Both check information_schema, see entry_type not in PK, both try to DROP CONSTRAINT. Second DROP fails on "constraint does not exist".
**Why it happens:** Non-atomic check-then-act in the migration DO block.
**How to avoid:** Wrap entire PK migration in `BEGIN; LOCK TABLE signal_metrics IN ACCESS EXCLUSIVE MODE; ... COMMIT;` or use advisory locks. Or accept the failure mode (second startup will see entry_type already in PK and skip). The `IF NOT EXISTS` pattern on `ADD COLUMN` handles columns; for constraints, use `DROP CONSTRAINT IF EXISTS`.

### Pitfall 6: scipy.stats.kurtosis default is NOT excess kurtosis
**What goes wrong:** `scipy.stats.kurtosis(data)` with default args returns excess kurtosis (Fisher=True is the default). However, `bias=True` is also the default which applies small-sample bias. With small N, biased kurtosis can differ substantially from unbiased.
**Why it happens:** Default `bias=True` applies bias correction only when `fisher=True`. Actually: default is `fisher=True, bias=True`. The locked decision specifies `fisher=True, bias=False` — verify this is called correctly.
**How to avoid:** Always call `scipy.stats.kurtosis(pnl_rs, fisher=True, bias=False)`. Write a unit test with a known distribution (e.g., 30 normally distributed values) to verify the return value matches expected excess kurtosis.

---

## Code Examples

### _distribution_shape() Helper (locked design from D-11)

```python
# Source: CONTEXT.md D-11; scipy confirmed in requirements.txt >=1.15.0
from scipy.stats import skew as _scipy_skew, kurtosis as _scipy_kurtosis
import numpy as np

@dataclass
class DistributionShape:
    skewness: float | None
    kurtosis: float | None
    min_r: float | None
    p5_r: float | None
    recovery_factor: float | None
    cvar_5: float | None


def _distribution_shape(pnl_rs: list[float], avg_mfe: float) -> DistributionShape:
    n = len(pnl_rs)
    skewness = float(_scipy_skew(pnl_rs, bias=False)) if n >= 3 else None
    kurt = float(_scipy_kurtosis(pnl_rs, fisher=True, bias=False)) if n >= 3 else None
    min_r = float(min(pnl_rs)) if n >= 30 else None
    if n >= 20:
        p5 = float(np.percentile(pnl_rs, 5))
        tail = [r for r in pnl_rs if r < p5]
        cvar = float(sum(tail) / len(tail)) if tail else None
        recov = round(avg_mfe / abs(p5), 4) if p5 < -1e-9 else None
    else:
        p5 = None
        cvar = None
        recov = None
    return DistributionShape(
        skewness=round(skewness, 4) if skewness is not None else None,
        kurtosis=round(kurt, 4) if kurt is not None else None,
        min_r=round(min_r, 4) if min_r is not None else None,
        p5_r=round(p5, 4) if p5 is not None else None,
        recovery_factor=recov,
        cvar_5=round(cvar, 4) if cvar is not None else None,
    )
```

### _build_metrics_result() signature extension

```python
# Gains entry_type parameter; passes avg_mfe to _distribution_shape()
def _build_metrics_result(
    acc: dict,
    track: str,
    setup_plugin: str,
    tf: str,
    regime_type: str,
    window_days: int,
    symbol: str = "*",
    entry_type: str = "*",
) -> SignalMetricsResult:
    ...
    shape = _distribution_shape(pnl_rs, avg_mfe or 0.0)
    return SignalMetricsResult(
        ...existing fields...,
        entry_type=entry_type,
        skewness=shape.skewness,
        kurtosis=shape.kurtosis,
        min_r=shape.min_r,
        p5_r=shape.p5_r,
        recovery_factor=shape.recovery_factor,
        cvar_5=shape.cvar_5,
    )
```

### DB Migration (idempotent DO block for PK)

```sql
-- Step 1: add entry_type column
ALTER TABLE signal_metrics
    ADD COLUMN IF NOT EXISTS entry_type text NOT NULL DEFAULT '*';

-- Step 2: add six metric columns
ALTER TABLE signal_metrics ADD COLUMN IF NOT EXISTS skewness float;
ALTER TABLE signal_metrics ADD COLUMN IF NOT EXISTS kurtosis float;
ALTER TABLE signal_metrics ADD COLUMN IF NOT EXISTS min_r float;
ALTER TABLE signal_metrics ADD COLUMN IF NOT EXISTS p5_r float;
ALTER TABLE signal_metrics ADD COLUMN IF NOT EXISTS recovery_factor float;
ALTER TABLE signal_metrics ADD COLUMN IF NOT EXISTS cvar_5 float;

-- Step 3: rebuild PK only if entry_type not already in it
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.key_column_usage
        WHERE table_name = 'signal_metrics'
          AND constraint_name = 'signal_metrics_pkey'
          AND column_name = 'entry_type'
    ) THEN
        ALTER TABLE signal_metrics DROP CONSTRAINT signal_metrics_pkey;
        ALTER TABLE signal_metrics ADD PRIMARY KEY
            (track, setup_plugin, tf, regime_type, window_days, symbol, entry_type);
    END IF;
END $$;
```

### _tail_risk_blocks_promotion() pure gate function

```python
# Source: CONTEXT.md D-15; consistent with _should_promote/_should_demote pattern
TAIL_GATE_MIN_SKEWNESS: float = -2.0
TAIL_GATE_MIN_RECOVERY: float = 0.5

def _tail_risk_blocks_promotion(
    skewness: float | None,
    recovery_factor: float | None,
    min_skewness: float,
    min_recovery: float,
) -> bool:
    if skewness is not None and skewness < min_skewness:
        return True
    if recovery_factor is not None and recovery_factor < min_recovery:
        return True
    return False
```

### Tail gate integration in _check_promotion()

```python
# Inserted BEFORE the _should_promote() check block, inside the existing pool.acquire
metrics_row = await conn.fetchrow(
    """
    SELECT skewness, recovery_factor
    FROM signal_metrics
    WHERE setup_plugin = $1
      AND symbol = '*'
      AND entry_type = '*'
      AND track = 'market'
    ORDER BY computed_at DESC LIMIT 1
    """,
    name,
)
if metrics_row is not None:
    skewness_val = metrics_row["skewness"]
    recovery_val = metrics_row["recovery_factor"]
    if _tail_risk_blocks_promotion(skewness_val, recovery_val,
                                   TAIL_GATE_MIN_SKEWNESS, TAIL_GATE_MIN_RECOVERY):
        reason = "skewness" if (skewness_val is not None
                                and skewness_val < TAIL_GATE_MIN_SKEWNESS) else "recovery_factor"
        SHADOW_TAIL_RISK_BLOCKED.add(1, {"plugin": name, "reason": reason})
        logger.info(
            "shadow_audit.tail_risk_blocked",
            plugin=name,
            skewness=skewness_val,
            recovery_factor=recovery_val,
        )
        return  # block promotion
```

### Per-entry_type accumulation extension in compute_signal_metrics()

```python
# Three accumulation dicts (by_group is the existing regime_accs + all_accs)
# by_entry_type keyed (plugin, tf_val, regime_label, entry_type_val)
by_entry_type: dict[tuple, dict] = defaultdict(_empty_acc)

for row in rows:
    ...
    entry_type_raw = row.get("entry_type")
    entry_type_val = entry_type_raw if entry_type_raw else None  # None folds to global only

    # Existing accumulation (unchanged)
    regime_accs[regime_key]["pnl_rs"].append(...)
    all_accs[all_key]["pnl_rs"].append(...)

    # New per-entry_type accumulation (skip if entry_type is None/missing)
    if entry_type_val is not None:
        et_key = (plugin, tf_val, regime_label, entry_type_val)
        by_entry_type[et_key]["pnl_rs"].append(...)
```

---

## Verified Findings by Research Question

### Q1: Exact signal_metrics schema — does entry_type exist?
**Confirmed from DB:**
```
Column       | Type    | Nullable | Default
-------------|---------|----------|--------
track        | text    | not null |
setup_plugin | text    | not null |
tf           | text    | not null |
regime_type  | text    | not null |
window_days  | integer | not null |
n            | integer | not null |
n_outliers   | integer | not null | 0
never_activated_pct | float |     |
win_rate     | float   |          |
avg_r        | float   |          |
std_r        | float   |          |
sharpe       | float   |          |
p_value      | float   |          |
avg_mae      | float   |          |
avg_mfe      | float   |          |
computed_at  | timestamptz | not null | now()
symbol       | text    | not null | '*'
```
PK: `(track, setup_plugin, tf, regime_type, window_days, symbol)`
**entry_type does NOT exist** — must be added by Plan 01.
**Confidence: HIGH** (verified from live DB)

### Q2: Exact ON CONFLICT clause in signal_metrics_writer_agent.py
```sql
ON CONFLICT (track, setup_plugin, tf, regime_type, window_days, symbol)
```
**Confirmed at line 51** of `services/signal_metrics_writer_agent.py`. Plan 01 must add `entry_type` to this clause after PK migration.
**Confidence: HIGH** (verified from source)

### Q3: What does _build_metrics_result() return today? SignalMetricsResult fields?
Current `SignalMetricsResult` dataclass fields: `track, setup_plugin, tf, regime_type, window_days, symbol, n, n_outliers, never_activated_pct, win_rate, avg_r, std_r, sharpe, p_value, avg_mae, avg_mfe, computed_at`.
Missing: `entry_type, skewness, kurtosis, min_r, p5_r, recovery_factor, cvar_5`. All seven must be added in Plan 01.
**Confidence: HIGH** (verified from source at lines 41-63)

### Q4: How does feature_validation_compute_agent.py implement ensure_schema()?
It does NOT implement `ensure_schema()`. It manages its own asyncpg pool via `create_pool()` and calls `_setup()` at startup. The reference pattern for this phase is to add an `_ensure_schema(conn)` coroutine called during `_setup()` of `signal_metrics_writer_agent.py` (or a standalone migration script). The writer agent's `_setup()` already acquires a DB connection — the migration can run there.
**Confidence: HIGH** (verified from source)

### Q5: Exact accumulation loop in signal_metrics_compute_agent.py
The compute agent calls `compute_signal_metrics()` from `src/intelligence/metrics/compute.py` — it does NOT implement its own accumulation loop. The accumulation is inside `compute_signal_metrics()`. The per-entry_type grouping must be added to `compute_signal_metrics()` itself, not to the compute agent directly.

The compute agent loop: fetch all rows → DQ publish → for each window → filter to window → call `compute_signal_metrics()` → publish each result row. Plan 02 changes `compute_signal_metrics()` to also accumulate `by_entry_type`.
**Confidence: HIGH** (verified from source)

### Q6: Gate functions in shadow_auditor_agent.py — exact signature of _check_promotion()
```python
async def _check_promotion(pool: asyncpg.Pool, env_name: str, row: dict[str, Any]) -> None:
```
Pure gate functions at module level: `_should_promote()`, `_should_demote()`, `_ev_r_below_threshold()`. The tail gate query + `_tail_risk_blocks_promotion()` call inserts before line 155 (`if _should_promote(...)`).
**Confidence: HIGH** (verified from source)

### Q7: Existing tests for compute.py and shadow_auditor_agent.py
- `tests/unit/intelligence/test_metrics_compute.py` — tests `compute_signal_metrics()`, `compute_ic_metrics()`, symbol grouping (318 lines)
- `tests/unit/test_shadow_auditor_agent.py` — tests pure gate functions (`_should_promote`, `_should_demote`, `_ev_r_below_threshold`) directly (68 lines)
- `tests/unit/service_tests/test_signal_metrics_writer_agent.py` — tests `_handle_metrics_computed()`, `_handle_ic_computed()`, `_handle_dq_failure()` with AsyncMock

Tests follow the project pattern: pure functions tested with direct calls; DB functions tested with `AsyncMock` for the connection object. Plan 01 and Plan 03 unit tests follow these exact patterns.
**Confidence: HIGH** (verified from source)

### Q8: scipy.stats.skew / kurtosis in requirements.txt?
`scipy>=1.15.0` in `requirements.txt`. `scipy.stats.t` already imported in `compute.py` as `_scipy_t`. Adding skew and kurtosis requires adding two names to the existing import: `from scipy.stats import t as _scipy_t, skew as _scipy_skew, kurtosis as _scipy_kurtosis`. No new dependency.
**Confidence: HIGH** (verified from source and requirements.txt)

### Q9: Downstream consumers of signal_metrics — will adding entry_type break anything?
Three consumers identified:
1. `src/intelligence/pipeline/cache_manager.py` — queries `SELECT setup_plugin, tf, symbol, sharpe FROM signal_metrics WHERE track='market' AND regime_type=... AND window_days=30 AND n>=30`. Does NOT filter on entry_type. After migration, existing rows get `entry_type='*'` (from DEFAULT). This query will now return both global rows (`entry_type='*'`) AND per-entry_type rows for the same (plugin, tf, symbol). This will produce DUPLICATE rows in the result, inflating perf_weights.
2. `src/api/routes/signals.py` — similar explicit-column queries, same duplication risk.
3. `src/intelligence/setup_performance_updater.py` — reads from signal_metrics for shim.

**CRITICAL FINDING:** All consumers that do NOT filter `AND entry_type='*'` will get duplicate rows once per-entry_type rows are written. This must be addressed in Plan 02 either by:
- Adding `AND entry_type='*'` to all existing consumer queries, OR
- Ensuring per-entry_type rows are only written when they differ from global (not a clean solution), OR
- Accepting the duplication and documenting the consumer query fix as part of Plan 02's scope.

The recommended approach: Plan 02 adds `AND entry_type='*'` to `cache_manager.py`, `signals.py`, and `setup_performance_updater.py`. This is a one-line addition to each WHERE clause.
**Confidence: HIGH** (verified from source)

### Q10: OTel metrics in shadow_auditor_agent — label structure
Current shadow metrics all use `{"plugin": name}` label. `SHADOW_TAIL_RISK_BLOCKED` adds a second label key `"reason"`. Existing metrics imported: `SHADOW_DAYS_TO_GATE, SHADOW_EV_CI_LOWER, SHADOW_EV_R, SHADOW_N_RESOLVED, SHADOW_PROMOTION_READY, SHADOW_WIN_RATE`. All use `.add()` (up_down_counter pattern). The new `SHADOW_TAIL_RISK_BLOCKED` is a `create_counter` (increments only), consistent with other `_TOTAL` counters.
**Confidence: HIGH** (verified from source)

---

## State of the Art

| Old Approach | Current Approach | Impact |
|--------------|------------------|--------|
| No tail shape metrics | skewness + kurtosis + min_r + p5_r + recovery_factor + cvar_5 | Promotion gate blind to left-tail blowup risk |
| Global '*' aggregate only | + per-symbol + per-entry_type | Reveals cross-instrument masking and entry-type risk profiles |
| Promotion gate: n AND ci_lower | + tail risk gate (skewness AND recovery_factor) | Measurement becomes action |

---

## Open Questions

1. **Consumer query deduplication scope in Plan 02**
   - What we know: `cache_manager.py` (lines 483-533), `signals.py` (lines 553-620), `setup_performance_updater.py` (line 126) all query `signal_metrics` without filtering `entry_type='*'`
   - What's unclear: Whether `setup_performance_updater.py` is still active or is a dead code path
   - Recommendation: Plan 02 explicitly adds `AND entry_type = '*'` to all three consumers. Verify `setup_performance_updater.py` is still called before patching.

2. **signal_ledger idx_ledger_metrics_compute coverage of entry_type**
   - What we know: The covering index does not include `entry_type` in its INCLUDE list
   - What's unclear: Whether adding `entry_type` to the SELECT causes a significant heap fetch cost for 1.27M rows
   - Recommendation: Add `entry_type` to the index INCLUDE list in the migration (step 4 in ensure_schema). This is one additional column in the existing index with minimal cost.

3. **shadow_auditor_agent uses direct asyncpg pool, not DatabaseManager**
   - What we know: `shadow_auditor_agent.py` uses `create_pool` directly and `pool.acquire()` for each operation
   - What's unclear: Whether adding a second `pool.acquire()` in `_check_promotion()` for the tail gate query causes contention (pool is min_size=2, max_size=5)
   - Recommendation: Reuse the existing `pool.acquire()` context already present in `_check_promotion()` rather than opening a second connection. The tail gate query can run inside the same `async with pool.acquire() as conn:` block where shadow_registry is read.

---

## Sources

### Primary (HIGH confidence)
- Live DB schema query: `\d signal_metrics` — confirmed 17 columns, PK of 6 columns, no entry_type
- `services/signal_metrics_writer_agent.py` — ON CONFLICT clause at line 51
- `src/intelligence/metrics/compute.py` — `SignalMetricsResult` dataclass, `_build_metrics_result()`, `_empty_acc()`
- `services/signal_metrics_compute_agent.py` — `_QUERY`, timer loop, compute delegation
- `services/shadow_auditor_agent.py` — gate function signatures, `_check_promotion()` structure
- `src/intelligence/schemas.py:991-1062` — `MetricsComputedEvent` with `extra="forbid"`
- `src/observability/metrics.py` — all existing shadow metrics, OTel creation pattern
- `src/core/stats_utils.py` — `bootstrap_ci_lower()` as gate function pattern
- `requirements.txt` — `scipy>=1.15.0` confirmed

### Secondary (MEDIUM confidence)
- `tests/unit/intelligence/test_metrics_compute.py` — test patterns for compute functions
- `tests/unit/test_shadow_auditor_agent.py` — test patterns for gate functions
- `src/intelligence/pipeline/cache_manager.py:469-533` — consumer queries without entry_type filter
- `src/api/routes/signals.py:540-620` — consumer queries without entry_type filter

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — scipy confirmed in requirements.txt, all imports verified in source
- Architecture: HIGH — all files read directly, patterns verified from existing code
- Pitfalls: HIGH for most; MEDIUM for index coverage (no query plan run)
- Consumer impact (Q9): HIGH — confirmed by reading all three consumer files

**Research date:** 2026-05-20
**Valid until:** 60 days (stable codebase, no external dependencies)
