# Phase 092: Signal Quality Completeness - Pattern Map

**Mapped:** 2026-05-20
**Files analyzed:** 8 new/modified files across 3 plans
**Analogs found:** 8 / 8

---

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|---|---|---|---|---|
| `src/intelligence/metrics/compute.py` | utility (pure compute) | transform | itself (extend) | exact |
| `src/intelligence/schemas.py` | model (Pydantic schema) | request-response | itself (extend) | exact |
| `services/signal_metrics_writer_agent.py` | service (writer) | CRUD | itself (extend) | exact |
| `services/signal_metrics_compute_agent.py` | service (timer-triggered) | batch | itself (extend) | exact |
| `services/shadow_auditor_agent.py` | service (gate logic) | batch | itself (extend) | exact |
| `src/observability/metrics.py` | utility (OTel registry) | event-driven | itself (extend) | exact |
| `tests/unit/intelligence/test_metrics_compute.py` | test | transform | itself (extend) | exact |
| `tests/unit/test_shadow_auditor_agent.py` | test | event-driven | itself (extend) | exact |

All phase 092 files extend existing files in-place. No new files are created (except possibly a consumer-query fix in `src/intelligence/pipeline/cache_manager.py` and `src/api/routes/signals.py` in Plan 02).

---

## Pattern Assignments

### `src/intelligence/metrics/compute.py` (pure compute utility, transform)

**Analog:** itself — extend in-place

**Imports to add** (current line 15 — append to existing scipy import):
```python
# Current line 15:
from scipy.stats import t as _scipy_t
# Replace with:
from scipy.stats import kurtosis as _scipy_kurtosis, skew as _scipy_skew, t as _scipy_t
import numpy as np
```

**Existing dataclass pattern** (lines 41-63) — follow for new `DistributionShape` dataclass:
```python
@dataclass
class SignalMetricsResult:
    track: str
    setup_plugin: str
    tf: str
    regime_type: str
    window_days: int
    symbol: str  # '*' = global sentinel (cross-instrument aggregate)
    n: int
    n_outliers: int
    never_activated_pct: float | None
    win_rate: float | None
    avg_r: float | None
    std_r: float | None
    sharpe: float | None
    p_value: float | None
    avg_mae: float | None
    avg_mfe: float | None
    computed_at: datetime
```

New `DistributionShape` dataclass follows exact same `@dataclass` + nullable fields pattern. New fields on `SignalMetricsResult` are appended after `avg_mfe`, before `computed_at`:
```python
# Seven new fields appended to SignalMetricsResult (after avg_mfe, before computed_at):
entry_type: str  # '*' = global sentinel; actual value for per-entry_type rows
skewness: float | None
kurtosis: float | None
min_r: float | None
p5_r: float | None
recovery_factor: float | None
cvar_5: float | None
computed_at: datetime
```

**Core pure function pattern** (lines 83-161) — `_build_metrics_result()` as master template for `_distribution_shape()`:
```python
def _p_value(avg_r: float, std_r: float, n: int) -> float | None:
    """Two-sided one-sample t-test: H0 = avg_r == 0."""
    if n < 2 or std_r < 1e-9 or math.isnan(std_r):
        return None
    t_stat = avg_r / (std_r / math.sqrt(n))
    return float(_scipy_t.sf(abs(t_stat), df=n - 1) * 2)


def _build_metrics_result(
    acc: dict,
    track: str,
    setup_plugin: str,
    tf: str,
    regime_type: str,
    window_days: int,
    symbol: str = "*",
) -> SignalMetricsResult:
    """Compute statistics from an accumulated group dict and return a SignalMetricsResult."""
    pnl_rs = acc["pnl_rs"]
    ...
    avg_mfe = sum(mfes) / len(mfes) if mfes else None
    # Call _distribution_shape here; pass avg_mfe (already computed)
    return SignalMetricsResult(
        ...
        avg_mfe=round(avg_mfe, 4) if avg_mfe is not None else None,
        computed_at=now,
    )
```

**New `entry_type` parameter**: `_build_metrics_result()` gains `entry_type: str = "*"` as the last positional parameter before the closing `)`. Pass through to `SignalMetricsResult(entry_type=entry_type, ...)`.

**Accumulator pattern** (lines 164-173) — `_empty_acc()` is unchanged (no new acc fields needed for distribution shape):
```python
def _empty_acc() -> dict:
    return {
        "pnl_rs": [],
        "maes": [],
        "mfes": [],
        "win_flags": [],
        "n_never_activated": 0,
        "n_total": 0,
        "n_outliers": 0,
    }
```

**Accumulation loop pattern** (lines 197-257) — used as template for extending with `by_entry_type` dict. Key change: extract `entry_type_val = row.get("entry_type")` after `symbol_val = row.get("symbol") or "*"`:
```python
# Per-regime accumulators keyed by (plugin, tf, regime_label, symbol)
regime_accs: dict[tuple, dict] = defaultdict(_empty_acc)
# Rollup accumulators keyed by (plugin, tf, symbol)
all_accs: dict[tuple, dict] = defaultdict(_empty_acc)
# NEW: Per-entry_type accumulators keyed by (plugin, tf, regime_label, entry_type)
# entry_type_accs: dict[tuple, dict] = defaultdict(_empty_acc)

for row in rows:
    plugin = row.get("setup_plugin")
    tf_val = row.get("tf") or row.get("timeframe")
    hmm = row.get("hmm_regime_at_fire")
    if not plugin or not tf_val:
        continue
    symbol_val = row.get("symbol") or "*"
    ...
    regime_key = (plugin, tf_val, regime_label, symbol_val)
    all_key = (plugin, tf_val, symbol_val)
    ...
    for acc in (regime_accs[regime_key], all_accs[all_key]):
        acc["pnl_rs"].append(float(pnl_r))
```

**Result-building loop pattern** (lines 259-289) — template for per-entry_type result loop:
```python
for (plugin, tf_val, regime_label, sym), acc in regime_accs.items():
    if len(acc["pnl_rs"]) < MIN_SAMPLE_SIZE:
        continue
    result.append(
        _build_metrics_result(
            acc, track, plugin, tf_val, regime_label, window_days, symbol=sym,
        )
    )
```
Per-entry_type loop follows identical structure with `entry_type=et_val` kwarg added to `_build_metrics_result()` call.

---

### `src/intelligence/schemas.py` (Pydantic model, request-response)

**Analog:** itself — extend `MetricsComputedEvent` in-place

**Existing MetricsComputedEvent pattern** (lines 991-1016) — fields to add immediately after `symbol: str = "*"` and before `n: int`:
```python
class MetricsComputedEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_type: Literal["metrics_computed"]
    track: str
    setup_plugin: str
    tf: str
    regime_type: str
    window_days: int
    symbol: str = "*"
    # ADD AFTER symbol:
    entry_type: str = "*"
    n: int
    n_outliers: int
    never_activated_pct: float | None = None
    win_rate: float | None = None
    avg_r: float | None = None
    std_r: float | None = None
    sharpe: float | None = None
    p_value: float | None = None
    avg_mae: float | None = None
    avg_mfe: float | None = None
    # ADD BEFORE computed_at:
    skewness: float | None = None
    kurtosis: float | None = None
    min_r: float | None = None
    p5_r: float | None = None
    recovery_factor: float | None = None
    cvar_5: float | None = None
    computed_at: str
```

**Critical constraint:** `extra="forbid"` means any field in the Kafka publish dict that is NOT listed here causes Pydantic to reject the event and DLQ it. All seven new fields (entry_type + 6 distribution fields) must be added here before Plan 01 is deployed.

**Optional-with-default pattern:** Follow existing pattern — nullable floats use `float | None = None`, strings with sentinel use `str = "*"`.

---

### `services/signal_metrics_writer_agent.py` (writer service, CRUD)

**Analog:** itself — extend `_handle_metrics_computed()` in-place

**Existing ON CONFLICT pattern** (lines 43-82) — must update conflict target and column list:
```python
await conn.execute(
    """
    INSERT INTO signal_metrics
        (track, setup_plugin, tf, regime_type, window_days, symbol,
         n, n_outliers, never_activated_pct,
         win_rate, avg_r, std_r, sharpe, p_value,
         avg_mae, avg_mfe, computed_at)
    VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17)
    ON CONFLICT (track, setup_plugin, tf, regime_type, window_days, symbol)
    DO UPDATE SET
        n                   = EXCLUDED.n,
        ...
        computed_at         = EXCLUDED.computed_at
    """,
    event["track"],
    event["setup_plugin"],
    ...
    computed_at,
)
```

Plan 01 changes: (a) add `entry_type` to INSERT column list (position 7, after `symbol`), (b) add `$18` positional param, (c) update ON CONFLICT to include `entry_type`, (d) add six new metric columns to INSERT + DO UPDATE, (e) add `event.get("entry_type", "*")` as positional arg.

**Schema migration pattern** — add `_ensure_schema(conn)` called from `_setup()`. See `feature_validation_compute_agent.py` for the pattern of calling asyncpg DDL statements at startup. The migration runs inside `_setup()` after the DB pool is initialized:
```python
async def _setup(self) -> None:
    self._db = DatabaseManager(self.settings.database_url)
    await self._db.initialize()
    # ADD: run idempotent schema migration
    async with self._db.get_connection() as conn:
        await _ensure_schema(conn)
    ...
```

**asyncpg DDL pattern** — each `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` is a separate `conn.execute()` call. The PK rebuild uses a `DO $$ ... $$` block with `information_schema.key_column_usage` guard passed as a single string to `conn.execute()`.

---

### `services/signal_metrics_compute_agent.py` (timer-triggered agent, batch)

**Analog:** itself — extend `_QUERY` and `_run_compute_cycle()` publish block in-place

**Existing `_QUERY` pattern** (lines 75-102) — add `entry_type` to SELECT:
```python
_QUERY = """
    SELECT
        signal_id::text,
        setup_plugin,
        timeframe              AS tf,
        symbol,
        hmm_regime_at_fire,
        direction,
        entry_price,
        stop_loss,
        pnl_r,
        mae,
        mfe,
        outcome,
        confidence,
        exit_at,
        market_entry_pnl_r,
        market_entry_mae,
        market_entry_mfe,
        market_entry_outcome
        -- ADD: entry_type
    FROM signal_ledger
    WHERE outcome IS NOT NULL
      AND exit_at > NOW() - INTERVAL '90 days'
      AND timestamp > NOW() - INTERVAL '100 days'
      AND setup_plugin IS NOT NULL
      AND was_selected = true
    ORDER BY exit_at
"""
```

**Existing publish dict pattern** (lines 296-320) — template for adding new fields and updating Kafka key:
```python
await self._producer.publish(
    topic,
    msg={
        "event_type": "metrics_computed",
        "track": mr.track,
        "setup_plugin": mr.setup_plugin,
        "tf": mr.tf,
        "regime_type": mr.regime_type,
        "window_days": mr.window_days,
        "symbol": mr.symbol,
        # ADD: "entry_type": mr.entry_type,
        "n": mr.n,
        ...
        "avg_mfe": mr.avg_mfe,
        # ADD six distribution fields:
        # "skewness": mr.skewness,
        # "kurtosis": mr.kurtosis,
        # "min_r": mr.min_r,
        # "p5_r": mr.p5_r,
        # "recovery_factor": mr.recovery_factor,
        # "cvar_5": mr.cvar_5,
        "computed_at": mr.computed_at.isoformat(),
    },
    key=f"metrics:{track}:{mr.setup_plugin}:{mr.tf}:{mr.regime_type}:{window_days}:{mr.symbol}",
    # UPDATE key to: f"metrics:{track}:{mr.setup_plugin}:{mr.tf}:{mr.regime_type}:{window_days}:{mr.symbol}:{mr.entry_type}",
)
```

**Timer loop pattern** (lines 185-202) — unchanged; compute cycle structure intact.

---

### `services/shadow_auditor_agent.py` (gate logic service, batch)

**Analog:** itself — extend `_check_promotion()` and add module-level constants + pure function

**Existing imports pattern** (lines 1-33) — add `SHADOW_TAIL_RISK_BLOCKED` to imports from `src.observability.metrics`:
```python
from src.observability.metrics import (
    SHADOW_DAYS_TO_GATE,
    SHADOW_EV_CI_LOWER,
    SHADOW_EV_R,
    SHADOW_N_RESOLVED,
    SHADOW_PROMOTION_READY,
    SHADOW_WIN_RATE,
    # ADD:
    # SHADOW_TAIL_RISK_BLOCKED,
)
```

**Existing pure gate function pattern** (lines 44-54) — template for `_tail_risk_blocks_promotion()`:
```python
def _should_promote(n: int, ci_lower: float, min_n: int, min_ev_r: float) -> bool:
    return n >= min_n and ci_lower > min_ev_r


def _should_demote(new_count: int, min_evaluations: int) -> bool:
    return new_count >= min_evaluations


def _ev_r_below_threshold(ev_r: float, threshold: float) -> bool:
    return ev_r < threshold
```

New constants and gate function go in the same section (after line 37, before `_run_audit`):
```python
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

**Existing `_check_promotion()` DB query pattern** (lines 91-101) — tail gate query reuses the same `pool.acquire()` context:
```python
async def _check_promotion(pool, env_name, row):
    name = row["component_name"]
    ...
    async with pool.acquire() as conn:
        signal_rows = await conn.fetch(
            """
            SELECT outcome, pnl_r, signal_computed_at
            FROM signal_ledger
            WHERE setup_plugin = $1
              AND outcome IS NOT NULL
              AND outcome NOT IN ('never_activated', 'ttl_expired_behind')
            """,
            name,
        )
    # Tail gate query runs in its own pool.acquire() AFTER the signal_ledger read,
    # BEFORE the _should_promote() check at line 155.
```

**Gate check insertion point** — insert between line 153 (end of OTel metric recording) and line 155 (`if _should_promote(...)`):
```python
    # Tail gate: check signal_metrics for distribution-shape risk (D-13)
    async with pool.acquire() as conn:
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
        if _tail_risk_blocks_promotion(
            metrics_row["skewness"], metrics_row["recovery_factor"],
            TAIL_GATE_MIN_SKEWNESS, TAIL_GATE_MIN_RECOVERY,
        ):
            reason = (
                "skewness"
                if metrics_row["skewness"] is not None
                and metrics_row["skewness"] < TAIL_GATE_MIN_SKEWNESS
                else "recovery_factor"
            )
            SHADOW_TAIL_RISK_BLOCKED.add(1, {"plugin": name, "reason": reason})
            logger.info(
                "shadow_audit.tail_risk_blocked",
                plugin=name,
                skewness=metrics_row["skewness"],
                recovery_factor=metrics_row["recovery_factor"],
            )
            return  # block promotion

    if _should_promote(n, ci_lower, row["min_n"], row["min_ev_r"]):
        ...
```

---

### `src/observability/metrics.py` (OTel registry utility)

**Analog:** itself — append new counter after `SHADOW_PROMOTION_READY` (line 193)

**Existing shadow counter pattern** (lines 170-193) — the SHADOW_* metrics use `create_up_down_counter`. The new `SHADOW_TAIL_RISK_BLOCKED` is an increment-only event counter, so use `create_counter` (same as `PLUGIN_FALLBACK_TOTAL`, `PLUGIN_ERRORS_TOTAL` etc.):
```python
# Existing up_down_counter for shadow metrics:
SHADOW_PROMOTION_READY = _meter.create_up_down_counter(
    "shadow_promotion_ready",
    description="1 when all gate conditions met",
)

# ADD after line 193 — create_counter (not up_down_counter) because it only increments:
SHADOW_TAIL_RISK_BLOCKED = _meter.create_counter(
    "shadow_tail_risk_blocked_total",
    description="Shadow promotions blocked by tail-risk gate (skewness or recovery_factor)",
)
```

Call pattern (in shadow_auditor_agent.py): `SHADOW_TAIL_RISK_BLOCKED.add(1, {"plugin": name, "reason": "skewness"})` — consistent with all counter `.add()` calls across the codebase.

---

### `tests/unit/intelligence/test_metrics_compute.py` (unit test, transform)

**Analog:** itself — add new test classes following existing class structure

**Row factory pattern** (lines 15-57) — `_make_row()` factory to extend with `entry_type` kwarg:
```python
def _make_row(
    setup_plugin="trad_TrendFollowing",
    tf="5m",
    hmm_regime=1,
    ...
    symbol="ES",
    # ADD:
    entry_type="at_close",
) -> dict:
    ...
    return {
        ...
        "symbol": symbol,
        # ADD:
        "entry_type": entry_type,
    }
```

**Existing test class pattern** (lines 71-143) — `TestComputeSignalMetrics` as template. New `TestDistributionShape` and `TestEntryTypeGrouping` classes follow same structure:
```python
class TestComputeSignalMetrics:
    def _make_n_rows(self, n, pnl_r=1.0, outcome="target_1", hmm_regime=1):
        return [_make_row(pnl_r=pnl_r, outcome=outcome, hmm_regime=hmm_regime) for _ in range(n)]

    def test_returns_empty_when_insufficient_n(self):
        rows = self._make_n_rows(MIN_SAMPLE_SIZE - 1)
        result = compute_signal_metrics(rows, track="zone", window_days=30)
        assert result == []
```

**Assertion pattern** — use `pytest.approx(value, abs=tolerance)` for float comparisons:
```python
assert all_row.win_rate == pytest.approx(1.0, abs=0.001)
```

**Direct pure function test pattern** — call `_distribution_shape()` directly (it's a module-level function), same as `_should_promote()` / `_ev_r_below_threshold()` in shadow auditor tests. Import directly from the module:
```python
from src.intelligence.metrics.compute import _distribution_shape
```

---

### `tests/unit/test_shadow_auditor_agent.py` (unit test, event-driven)

**Analog:** itself — append new pure function tests following existing pattern

**Existing pure function test pattern** (lines 16-47) — no mocks, direct calls to module-level functions:
```python
def test_promotion_gate_passes_when_n_and_ci_met():
    assert _should_promote(n=150, ci_lower=0.02, min_n=100, min_ev_r=0.0) is True

def test_promotion_gate_fails_when_n_insufficient():
    assert _should_promote(n=50, ci_lower=0.05, min_n=100, min_ev_r=0.0) is False
```

**Import pattern** (lines 7-11) — add `_tail_risk_blocks_promotion` to existing import:
```python
from services.shadow_auditor_agent import (
    _ev_r_below_threshold,
    _should_demote,
    _should_promote,
    # ADD:
    # _tail_risk_blocks_promotion,
)
```

**New tests follow exact boolean assertion pattern:**
```python
def test_tail_risk_blocks_when_skewness_too_negative():
    assert _tail_risk_blocks_promotion(-2.5, 0.8, -2.0, 0.5) is True

def test_tail_risk_blocks_when_recovery_too_low():
    assert _tail_risk_blocks_promotion(-1.0, 0.3, -2.0, 0.5) is True

def test_tail_risk_passes_when_both_none():
    assert _tail_risk_blocks_promotion(None, None, -2.0, 0.5) is False

def test_tail_risk_passes_when_metrics_acceptable():
    assert _tail_risk_blocks_promotion(-1.5, 0.7, -2.0, 0.5) is False
```

---

## Shared Patterns

### asyncpg DB Access
**Source:** `services/shadow_auditor_agent.py` lines 62-78 and `services/signal_metrics_writer_agent.py` lines 191-212
**Apply to:** Plan 01 `_ensure_schema()` migration, Plan 03 tail gate query
```python
# Pattern A — pool.acquire() (shadow auditor style, raw asyncpg pool):
async with pool.acquire() as conn:
    rows = await conn.fetch("SELECT ...", param1)
    await conn.execute("UPDATE ...", val1, val2, name)

# Pattern B — DatabaseManager.get_connection() (writer agent style):
async with self._db.get_connection() as conn:
    await conn.execute("INSERT ...", *params)
```
Plan 01 migration uses Pattern B (writer agent already uses `DatabaseManager`). Plan 03 tail gate query uses Pattern A (shadow auditor uses raw asyncpg pool).

### structlog Logging
**Source:** `services/shadow_auditor_agent.py` lines 128-181
**Apply to:** Plan 03 tail gate block
```python
logger.info("shadow_audit.tail_risk_blocked", plugin=name, skewness=val, recovery_factor=val)
```
Never use `event=` kwarg — use domain-specific kwarg names (`plugin=`, `skewness=`, `recovery_factor=`).

### NULL-safe float handling
**Source:** `src/intelligence/metrics/compute.py` lines 111, 136-141
**Apply to:** `_distribution_shape()` helper, all six new metric calculations
```python
avg_mfe = sum(mfes) / len(mfes) if mfes else None
sharpe = round(avg_r / std_r, 4) if std_r > 1e-9 else None
```
All new metrics gate on `n >= threshold` before computing, return `None` otherwise. Round to 4dp with `round(val, 4)`.

### OTel Counter Usage
**Source:** `services/signal_metrics_compute_agent.py` lines 49-69
**Apply to:** `SHADOW_TAIL_RISK_BLOCKED.add()` call in Plan 03
```python
# Counter: .add(1, {"label_key": label_val})
_COMPUTE_CYCLES.add(1, _attrs)
_DQ_FAILURES.add(1, {"agent": _AGENT_NAME, "reason_code": vr.reason_code})
```

### Consumer query deduplication guard (Plan 02)
**Source:** `src/intelligence/pipeline/cache_manager.py` lines 483-533
**Apply to:** All four existing `signal_metrics` WHERE clauses in `cache_manager.py` and `src/api/routes/signals.py`
```python
# Current query (will get duplicate rows after per-entry_type rows are written):
SELECT setup_plugin, tf, symbol, sharpe
FROM signal_metrics
WHERE track = 'market'
  AND regime_type = $1
  AND window_days = 30
  AND n >= 30
# Add this line to every signal_metrics query that does not already filter entry_type:
  AND entry_type = '*'
```

---

## No Analog Found

None. All files to be modified have exact analogs (themselves, pre-extension).

---

## Metadata

**Analog search scope:** `services/`, `src/intelligence/metrics/`, `src/intelligence/schemas.py`, `src/observability/metrics.py`, `tests/unit/`
**Files scanned:** 8 primary + 4 consumer files
**Pattern extraction date:** 2026-05-20

### Critical Warnings for Planner

1. **`MetricsComputedEvent` fields must be added before any deploy** — `extra="forbid"` means Pydantic rejects events with unknown fields. Plan 01 must update `schemas.py` before the compute agent publishes new fields.

2. **ON CONFLICT clause must match new PK exactly** — after `signal_metrics` PK migration adds `entry_type`, the writer's `ON CONFLICT (track, setup_plugin, tf, regime_type, window_days, symbol)` becomes invalid. Plan 01 updates both together (migration + upsert clause).

3. **Consumer query deduplication is Plan 02 scope** — `cache_manager.py` (4 queries, lines 483-533) and `src/api/routes/signals.py` (lines 566-620) must add `AND entry_type = '*'` before per-entry_type rows are written. Without this fix, perf_weights get inflated by duplicate rows.

4. **Tail gate query uses `entry_type = '*'`** — Plan 03 must filter `AND entry_type = '*'` in the signal_metrics query inside `_check_promotion()` or it will pick up per-entry_type rows with different n values.

5. **`_distribution_shape()` is called from within `_build_metrics_result()`** — not from the accumulation loop. All three grouping passes (global, per-symbol, per-entry_type) automatically get distribution shape computed by the single call site.
