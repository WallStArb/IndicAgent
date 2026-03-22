# Phase 47: Shadow Mode Graduation - Research

**Researched:** 2026-03-22
**Domain:** Shadow mode promotion, feature flag graduation, roll detection algorithm fix, regime gate settings migration
**Confidence:** HIGH (all findings from direct codebase inspection + existing test infrastructure)

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Area A — HMM Regime Thresholds**
- D-01: Move `_REGIME_PROB_MIN` and `_REGIME_DUR_MIN` from `src/intelligence/trading/aggregator.py` to `Settings` fields with env var aliases `REGIME_PROB_MIN` and `REGIME_DUR_MIN`.
- D-02: Default values are safety floors only — lower than current (e.g., 0.30 / 1). Not quality filters.
- D-03: No threshold optimization in Phase 47. Phase 49 ML model takes `hmm_regime_prob` and `hmm_regime_duration` as raw features.
- D-04: Lower to safety floor to maximize labeled training data for Phase 49.
- D-05: `regime_gate.py` reads from the new Settings fields — no other changes to gate logic.

**Area B — DualDivergence Shadow Promotion**
- D-06: Extend `weight_updater.py` with `compute_shadow_plugin_stats()` function on existing 30-min cadence.
- D-07: Promotion gate: N >= 100 resolved shadow signals (excludes `never_activated`); 95% CI lower bound on E[PnL_R] > 0 via bootstrap on resolved sample. Win/loss/neutral definitions specified.
- D-08: Emit Prometheus metrics per cycle via `src/observability/metrics.py`: `shadow_n_resolved{plugin}`, `shadow_win_rate{plugin}`, `shadow_ev_r{plugin}`, `shadow_ev_ci_lower{plugin}`, `shadow_days_to_gate{plugin}`, `shadow_promotion_ready{plugin}`.
- D-09: Emit WARNING log when `shadow_promotion_ready` flips to 1. Human makes `IS_SHADOW = False` change manually.
- D-10: `shadow_days_to_gate` > 180 is informational signal that plugin fires too rarely.

**Area C — Cross-Asset Graduation**
- D-11: Pre-enable validation: confirm Phase 46 cross-asset fields non-null in `intelligence_features` for EQ_INDEX symbols within past 7 days.
- D-12: Enable `CROSS_ASSET_ENABLED=true` in `.env`, restart affected services. 5-trading-day rollback window.
- D-13: Operational validation via existing Prometheus metrics on feature-pipeline (:9125) and signal-generator (:9112).
- D-14: Graduate (after 5 clean days): remove `cross_asset_enabled` from `Settings`, remove all conditional branches from `cross_asset_service.py`, `feature_pipeline_service.py`, `signal_generator_service.py`, `feature_writer_service.py`. Atomic cleanup commit.
- D-15: Graduation bar is operational only: no errors, latency within bounds.

**Area C — Roll Monitor Graduation**
- D-16: `update_volume(symbol, vol, vol)` bug at line 569 of `tws_daemon.py` confirmed — identical values produce ratio=1.0 always.
- D-17: Fix: replace ratio-based detection with calendar-driven + volume anomaly confirmation. Primary: deterministic roll date lookup. Confirmation: front-month volume z-score drops below -2.0 SD from rolling window mean during calendar roll window.
- D-18: Extend `src/config/contracts.py` in-place: add `get_expiry_date()`, `get_roll_window()`, extend `derive_roll_chain()` with `expiry_date` field. No new module.
- D-19: `RollMonitor.update_volume()` signature changes to remove `next_vol` parameter. `PAPER_SKIP_CONTRACTS` guard may be unnecessary with calendar approach.
- D-20: `_on_roll_confirmed` fixed: call `derive_roll_chain(base_symbol)` from `contracts.py`, read `chain[0]["roll_to"]` for `new_symbol`.
- D-21: Offline validation against `market_data_5m` view for known historical roll dates. Accuracy gate: >= 90% detection, < 10% false positives.
- D-22: Enable: `ROLL_MONITOR_ENABLED=true` in `.env`, restart 5 services.
- D-23: Graduate: remove `roll_monitor_enabled` from `Settings`, remove all conditional scaffolding. Atomic cleanup commit.

**Graduation Order:** (1) Fix roll detection bug, (2) offline validation, (3) enable roll monitor, (4) enable cross-asset, (5) 5-day soak, (6) remove roll monitor scaffolding, (7) remove cross-asset scaffolding. Sequential.

### Claude's Discretion
- Bootstrap implementation for 95% CI on E[PnL_R]: sample size and iteration count
- Specific safety floor values for `REGIME_PROB_MIN` / `REGIME_DUR_MIN` defaults (must be a floor, not a filter)
- Roll calendar exact offsets for energy/metals monthly rolls
- Whether cross-asset and roll monitor graduate in the same Phase 47 execution or sequentially

### Deferred Ideas (OUT OF SCOPE)
- Threshold optimization (segment by TF, asset cluster, sensitivity sweep) — Phase 49 ML
- Automated shadow promotion (DB flag flip without human code change) — Phase 49 scope
- Dynamic IBKR subscription management for next-month contracts during roll week
- Roll monitor consuming 5m bars directly for live detection
- Cross-asset lift measurement — Phase 49 feature weight assignment
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| SHADOW-01 | `hmm_regime` gating thresholds empirically validated, adjusted if supported | D-01 through D-05: move to Settings as safety floors; regime_gate.py accepts as parameters |
| SHADOW-02 | `CROSS_ASSET_ENABLED=true` after shadow monitoring confirms quality | D-11 through D-15: validation query + enable + 5-day soak + structural cleanup |
| SHADOW-03 | `ROLL_MONITOR_ENABLED=true` after paper account validation | D-16 through D-23: fix bug first, offline validation, then enable + graduate |
| SHADOW-04 | `trad_DualDivergence` promoted from shadow to live after statistical gate | D-06 through D-10: `compute_shadow_plugin_stats()` in weight_updater.py |
| INTEL-04 | `roll_premium_pct` populated in `intelligence_features` for futures near roll dates | No DB column exists yet; must add column to schema + populate during roll window from tws_daemon data |
</phase_requirements>

---

## Summary

Phase 47 graduates three shadow-mode systems to production and fixes a confirmed detection bug. The work is primarily operational (config changes, scaffolding removal) with two code-change workstreams: (1) the roll detection algorithm replacement, and (2) the shadow stats monitoring extension to `weight_updater.py`.

The **critical pre-work** is the roll detection bug fix (D-16): `tws_daemon.py` line 569 calls `update_volume(symbol, vol, vol)` — passing the same `current_vol` for both parameters. The `check_roll()` method computes `ratio = next_vol / current_vol`, which always equals 1.0. The volume ratio condition (`ratio >= threshold`) can never fire for any threshold > 1.0. The calendar + volume anomaly replacement algorithm requires changes only in `contracts.py` (add `get_expiry_date()`, `get_roll_window()`) and `tws_daemon.py` (`RollMonitor` methods).

The **signal_ledger is currently empty** (confirmed by DB query — 0 rows total). This means `trad_DualDivergence` has 0 resolved shadow signals. The `compute_shadow_plugin_stats()` function will report `shadow_n_resolved=0` and `shadow_promotion_ready=0` on first execution, which is the correct and expected behavior. Promotion will not happen in Phase 47 — the monitoring infrastructure is built and will track progress toward the gate over time.

The **roll_premium_pct field (INTEL-04)** does not exist anywhere in the codebase yet — no column in `intelligence_features`, no field in `I4Context` schema, no computation logic. This is a greenfield addition that requires: (1) a DB migration adding the nullable column to `intelligence_features`, (2) a new field in `I4Context` or written directly to the i7/i4 JSONB, (3) computation logic in `tws_daemon.py` or a new I4 plugin during roll windows.

**Primary recommendation:** Fix roll detection bug and build monitoring infrastructure in parallel, then enable features sequentially per the graduation order specified in D-17 and the specifics section.

---

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `statsmodels` | (installed) | `proportions_ztest` for significance tests | Already used in `weight_updater.py` — do NOT use scipy (1.17+ removed proportions_ztest) |
| `numpy` | (installed) | Bootstrap CI computation | Already used throughout intelligence layer |
| `prometheus_client` | (installed) | Metrics emission | Existing pattern in `src/observability/metrics.py` |
| `pydantic-settings` | (installed) | Settings fields for new env vars | Established pattern: `Field(default=X, validation_alias="ENV_VAR")` |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `zoneinfo` | stdlib | ET timezone conversion in roll calendar | Already used in `tws_daemon.py` `_apply_tod_adjustment()` |
| `datetime.date` | stdlib | Roll window boundary arithmetic | `get_roll_window()` returns `tuple[date, date]` |

### Installation
No new packages required. All dependencies already installed.

---

## Architecture Patterns

### Settings Field Pattern (verified from `settings.py`)
```python
# In class Settings(BaseSettings):
regime_prob_min: float = Field(default=0.30, validation_alias="REGIME_PROB_MIN")
regime_dur_min: int = Field(default=1, validation_alias="REGIME_DUR_MIN")
```
Then `regime_gate.py` accepts them as parameters instead of importing module-level constants from `aggregator.py`.

### Metrics Registration Pattern (verified from `src/observability/metrics.py`)
```python
# In src/observability/metrics.py — add at module level:
# New shadow monitoring metrics
SHADOW_N_RESOLVED = Gauge("shadow_n_resolved", "Resolved shadow signals", ["plugin"])
SHADOW_WIN_RATE = Gauge("shadow_win_rate", "Shadow plugin win rate", ["plugin"])
SHADOW_EV_R = Gauge("shadow_ev_r", "Shadow plugin E[PnL_R]", ["plugin"])
SHADOW_EV_CI_LOWER = Gauge("shadow_ev_ci_lower", "Shadow 95% CI lower bound", ["plugin"])
SHADOW_DAYS_TO_GATE = Gauge("shadow_days_to_gate", "Estimated days to N=100", ["plugin"])
SHADOW_PROMOTION_READY = Gauge("shadow_promotion_ready", "1 when gate conditions met", ["plugin"])
```

### `run_weight_update()` Extension Pattern (verified from `weight_updater.py`)
`run_weight_update()` already calls calibration and pattern reliability in independent try/except blocks at the end. The shadow stats function follows the same pattern:
```python
# In run_weight_update(), after pattern calibration block:
try:
    await compute_shadow_plugin_stats(db_manager)
except Exception:
    logger.error("Shadow plugin stats update failed", exc_info=True)
```

### Bootstrap CI Pattern (Claude's discretion — recommended implementation)
```python
import numpy as np

def _bootstrap_ci_lower(pnl_r_values: list[float], n_boot: int = 2000, alpha: float = 0.05) -> float:
    """95% CI lower bound on E[PnL_R] via bootstrap resampling."""
    arr = np.array(pnl_r_values)
    boot_means = np.array([
        np.random.choice(arr, size=len(arr), replace=True).mean()
        for _ in range(n_boot)
    ])
    # Lower bound: alpha/2 percentile of bootstrap distribution
    return float(np.percentile(boot_means, alpha / 2 * 100))
```
2000 iterations is sufficient for 95% CI at N=100 (standard in finance research). Faster than statsmodels bootstrap for this simple case.

### Calendar Roll Window Pattern (new `contracts.py` functions)
```python
from datetime import date, timedelta
import calendar

def get_expiry_date(base_symbol: str, expiry_month: int, expiry_year: int) -> date:
    """Approximate expiry date per contract family.
    - Quarterly (equity index, rates, VIX): third Friday of expiry month
    - Monthly energy/metals: last business day of month PRIOR to expiry month
    - Monthly grain: Friday closest to 15th of expiry month (approximation)
    """
    ...

def get_roll_window(base_symbol: str, ref_date: date) -> tuple[date, date] | None:
    """Return (roll_start, roll_end) if a roll is upcoming within 14 days, else None.
    Roll window: starts 10 trading days before expiry, ends 2 trading days before.
    Returns None when no upcoming roll.
    """
    ...
```

### Calendar-Driven Roll Detection (replaces ratio approach in `RollMonitor`)
The new algorithm in `check_roll()`:
1. Call `get_roll_window(base_symbol, date.today())` — if None, return False immediately (no roll window active)
2. If in roll window: compute z-score of `current_vol` against rolling window mean/std
3. If `z_score < -2.0` (volume drop below 2 SD): increment confirmation counter
4. After 3 consecutive confirming bars: fire roll confirmed
5. No `next_vol` needed at all — drop from `update_volume()` signature

The z-score direction is **negative** here: we look for volume DROPPING (front-month volume shrinks as traders move to back month), not rising. This is the inverse of the broken ratio logic (which looked for next-month volume RISING).

### `_on_roll_confirmed()` Fix Pattern
```python
async def _on_roll_confirmed(self, base_symbol: str, old_symbol: str, ...):
    # Derive new_symbol from roll chain — contracts.py already has this
    from src.config.contracts import derive_roll_chain
    chain = derive_roll_chain(base_symbol)
    new_symbol = chain[0]["roll_to"]  # next contract in chain
    # roll_gap: price data unavailable at detection time → set to 0.0
    # roll_direction: "unknown" until price comparison available
```

### Cross-Asset Conditional Branch Removal Pattern
Four files have conditional branches to remove after graduation:
1. `services/cross_asset_service.py` line 386-387: `if not self._cross_asset_enabled:` exit path
2. `services/feature_pipeline_service.py` line 227, 654, 1002, 1014, 1134: `self._cross_asset_enabled` conditionals
3. `services/signal_generator_service.py` line 489, 767, 1453, 1498, 1506: `self._cross_asset_enabled` conditionals
4. Remove `cross_asset_enabled` from `Settings` after branch removal

Remove `self._cross_asset_enabled = ...` assignments from all service `__init__` methods.

### Roll Monitor Conditional Branch Removal Pattern
Five files have conditional branches to remove after graduation:
1. `services/tws_daemon.py` line 566: `if self._roll_monitor.is_enabled:` block
2. `services/indicator_service.py` line 689-695: conditional `system_events` subscription
3. `services/market_analysis_service.py` line 768: `roll_monitor_enabled` conditional
4. `services/signal_generator_service.py` line 438: `self._roll_monitor_enabled`
5. `services/feature_writer_service.py` line 269: `self._roll_monitor_enabled`
Remove `roll_monitor_enabled` and related fields from `Settings`.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Bootstrap confidence intervals | Custom CI code from scratch | `numpy` percentile on resampled means (2000 iterations) | Simpler than statsmodels bootstrap for this specific case; already dependency |
| Proportion significance test | Custom z-test | `statsmodels.stats.proportion.proportions_ztest` | Already imported in `weight_updater.py`; scipy removed this in 1.17 |
| Metrics duplicate registration | Direct `Gauge()` / `Counter()` calls | `src/observability/metrics.py` module-level registration | Prevents `ValueError: Duplicated timeseries` on service restart |
| Roll date computation for unknown symbols | Complex lookup table | Conservative default: last 5 trading days of contract month | Consistent with context.md specifics |
| New service for shadow stats | Separate cadence/infrastructure | Extend `weight_updater.py` `run_weight_update()` | Same 30-min cycle, same DB connection, independent failure domain |

---

## Runtime State Inventory

> Roll detection and cross-asset graduation involve runtime state changes.

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | `signal_ledger` has 0 rows (DB cleared recently); `contract_metadata` table has roll state (is_front_month, roll_detected_at) from migration 038 | No migration needed for graduation; `intelligence_features` needs `roll_premium_pct` column (INTEL-04, new migration required) |
| Live service config | `CROSS_ASSET_ENABLED=false` in `.env` (confirmed); `ROLL_MONITOR_ENABLED=false` in `.env` (confirmed from Settings defaults); `REGIME_PROB_MIN` / `REGIME_DUR_MIN` not yet in `.env` (computed from hardcoded constants) | Update `.env` as part of each graduation step |
| OS-registered state | `indicagent-cross-asset.service` systemd unit exists and is managed; `indicagent-weight-updater.service` exists | Restart services after `.env` changes; no re-registration needed |
| Secrets/env vars | `CROSS_ASSET_ENABLED`, `ROLL_MONITOR_ENABLED` — existing env var names are correct, just need value change to `true`; `REGIME_PROB_MIN` / `REGIME_DUR_MIN` are new env vars to add | Add new vars to `.env` with floor defaults before starting services that read them |
| Build artifacts | None — all Python source, no compiled binaries | None |

**`intelligence_features.roll_premium_pct` column does not exist:** Verified via `information_schema.columns` query — no roll-related columns in `intelligence_features`. INTEL-04 requires a migration (e.g., `049_roll_premium_pct.sql`) adding `roll_premium_pct DOUBLE PRECISION` nullable column.

---

## Common Pitfalls

### Pitfall 1: `regime_gate.py` imports constants directly from `aggregator.py`
**What goes wrong:** After moving `_REGIME_PROB_MIN` and `_REGIME_DUR_MIN` to Settings, `regime_gate.py` still imports them as module-level constants — the gate silently uses old hardcoded values.
**Why it happens:** `regime_gate.py` line 9-13 does `from src.intelligence.trading.aggregator import _REGIME_PROB_MIN, _REGIME_MAP, _REGIME_PROB_MIN` — direct module-level import.
**How to avoid:** Change `apply_regime_gate()` signature to accept `prob_min: float` and `dur_min: int` as parameters. Update all callers (signal_generator_service passes regime data to the gate).
**Warning signs:** Regime gate still suppresses signals at 0.55 probability after the env var is lowered.

### Pitfall 2: Bootstrap returns CI lower bound above zero for empty / sparse data
**What goes wrong:** With 0 or very few resolved shadow signals, bootstrap of an empty array crashes or returns NaN; `shadow_ev_ci_lower` emits infinity.
**Why it happens:** `np.random.choice([], size=0)` is valid but `np.percentile([], ...)` raises ValueError.
**How to avoid:** Guard with `if len(pnl_r_values) < 10: return float('-inf')`. Emit `shadow_promotion_ready=0` and `shadow_days_to_gate` based on firing rate.

### Pitfall 3: Service `__new__` pattern — removed Settings fields break tests
**What goes wrong:** Tests for affected services use `ServiceClass.__new__(ServiceClass)` and manually set attributes. Removing `self._cross_asset_enabled` or `self._roll_monitor_enabled` from `__init__` but leaving the attribute set in test setup causes tests to use the removed flag even after code removal.
**Why it happens:** Service test pattern in `tests/unit/service_tests/` sets instance attributes manually — stale test setup silently tests the wrong code path.
**How to avoid:** For each service: remove the attribute from `__init__`, remove it from test setup, remove conditional branches together in the same commit. Verify with `grep -n "_cross_asset_enabled\|_roll_monitor_enabled" services/*.py` returns 0 lines.

### Pitfall 4: `update_volume()` signature change breaks `tws_daemon.py` call site
**What goes wrong:** After removing `next_vol` from `update_volume(base_symbol, current_vol, next_vol)`, the call at line 569 still passes two volume args.
**Why it happens:** The call site and the method change must be updated together.
**How to avoid:** Change method signature AND call site in the same task. The new call is `self._roll_monitor.update_volume(symbol, float(state["volume"]))`.

### Pitfall 5: `trad_DualDivergence` fires 0 signals on empty `signal_ledger`
**What goes wrong:** `compute_shadow_plugin_stats()` queries `signal_ledger WHERE is_shadow=TRUE AND setup_plugin='trad_DualDivergence'` and gets 0 rows. `shadow_n_resolved` is 0, `shadow_promotion_ready` is 0. This is CORRECT behavior but looks like a bug.
**Why it happens:** The `signal_ledger` was cleared (confirmed 0 rows). Shadow signals accumulate over time as the live system runs.
**How to avoid:** Log explicitly: `"DualDivergence: 0 resolved shadow signals — normal on empty ledger; tracking will populate over time"`. Do not treat 0 rows as an error.

### Pitfall 6: `INTEL-04` `roll_premium_pct` — no back-month price available in calendar approach
**What goes wrong:** Computing `roll_premium_pct = front_price - back_price` requires knowing the back-month price. The new calendar approach avoids subscribing to the back-month contract. Front-only subscription means `back_price` is unavailable.
**Why it happens:** D-17 explicitly chose calendar + z-score to avoid IBKR subscription limits. But INTEL-04 needs both prices.
**How to avoid:** `roll_premium_pct` is only populated during roll windows when the signal arrives from a cross-asset or external source. During a real roll with IBKR: the new front-month contract (previously the back month) provides its price at roll time. Delta between old close and new contract's first bar is a reasonable proxy. Alternatively, store `roll_premium_pct = NULL` and populate from the `roll_gap` value already computed in `_on_roll_confirmed()`.

### Pitfall 7: Cross-asset graduation validation query returns false negative
**What goes wrong:** D-11 pre-enable check queries `intelligence_features` for non-null cross-asset fields. If no Phase 46 data has been written (e.g., due to service restart or EQ_INDEX symbols not active), the query returns 0 rows and graduation appears blocked even though the pipeline is healthy.
**Why it happens:** `ctf_vix_level`, `ctf_vix_z` etc. are Phase 46 I6 fields stored in the i6 JSONB sub-object. Direct column access may not work if they are inside JSONB.
**How to avoid:** Check the actual column structure of `intelligence_features` — these fields may be in `i6` JSONB, not top-level columns. The validation query should use `WHERE i6->>'ctf_vix_level' IS NOT NULL` if stored as JSONB.

---

## Code Examples

Verified patterns from codebase inspection:

### Adding Settings Fields (verified `settings.py` pattern)
```python
# In class Settings(BaseSettings) after roll_monitor block:
regime_prob_min: float = Field(default=0.30, validation_alias="REGIME_PROB_MIN")
regime_dur_min: int = Field(default=1, validation_alias="REGIME_DUR_MIN")
```

### Updating `apply_regime_gate()` to Accept Parameters (current implementation at `regime_gate.py`)
```python
# Before (current):
from src.intelligence.trading.aggregator import _REGIME_DUR_MIN, _REGIME_MAP, _REGIME_PROB_MIN

def apply_regime_gate(signals, regime_data):
    ...
    if hmm_regime_prob < _REGIME_PROB_MIN:  # uses module constant

# After:
from src.intelligence.trading.aggregator import _REGIME_MAP  # keep _REGIME_MAP only

def apply_regime_gate(signals, regime_data, *, prob_min: float = 0.30, dur_min: int = 1):
    ...
    if hmm_regime_prob < prob_min:  # uses parameter
```

### `compute_shadow_plugin_stats()` Structure (new function in `weight_updater.py`)
```python
async def compute_shadow_plugin_stats(db_manager: Any) -> None:
    """Compute and emit Prometheus metrics for shadow-mode plugins."""
    from src.observability import metrics as m
    from src.intelligence.trading.signal_ledger import WIN_OUTCOMES, NEUTRAL_OUTCOMES

    SHADOW_PLUGINS = ["trad_DualDivergence"]

    rows = await db_manager.execute_query("""
        SELECT setup_plugin, outcome, calibrated_confidence,
               -- pnl_r proxy from signal_performance_segmented if available
               NULL::float AS pnl_r
        FROM signal_ledger
        WHERE is_shadow = TRUE
          AND outcome IS NOT NULL
          AND outcome NOT IN ('never_activated', 'ttl_expired_behind')
        ORDER BY signal_computed_at DESC
        LIMIT 10000
    """)

    for plugin_name in SHADOW_PLUGINS:
        plugin_rows = [r for r in rows if r["setup_plugin"] == plugin_name]
        n_resolved = len(plugin_rows)
        # ... compute win_rate, ev_r, ci_lower, days_to_gate
        # ... set Prometheus gauges
```

### Bootstrap CI Lower Bound (Claude's discretion)
```python
def _bootstrap_ci_lower(
    pnl_r_values: list[float],
    n_boot: int = 2000,
    alpha: float = 0.05,
) -> float:
    """95% CI lower bound on E[PnL_R]. Returns -inf if insufficient data."""
    if len(pnl_r_values) < 10:
        return float("-inf")
    arr = np.array(pnl_r_values, dtype=float)
    rng = np.random.default_rng(seed=42)
    boot_means = np.array([
        rng.choice(arr, size=len(arr), replace=True).mean()
        for _ in range(n_boot)
    ])
    return float(np.percentile(boot_means, alpha / 2 * 100))
```

### Expiry Date Computation for Quarterly Contracts (third Friday logic)
```python
import calendar
from datetime import date

def _third_friday(year: int, month: int) -> date:
    """Return the third Friday of the given month."""
    # Find first Friday
    first_day = date(year, month, 1)
    # weekday(): Monday=0, Friday=4
    days_to_friday = (4 - first_day.weekday()) % 7
    first_friday = first_day + timedelta(days=days_to_friday)
    return first_friday + timedelta(weeks=2)
```

### Roll Window Definition (Claude's discretion — recommended defaults)
```python
# Roll window: 10 trading days before expiry to 2 trading days before
# For calendar purposes, approximate as 14 calendar days before to 3 calendar days before
ROLL_WINDOW_DAYS_BEFORE: dict[str, tuple[int, int]] = {
    "quarterly": (14, 3),   # ES, NQ, RTY, YM, ZN, ZF, ZB, ZT, VIX
    "monthly": (7, 2),      # CL, GC, SI, HG — monthly rolls, shorter window
    "grain": (10, 3),       # ZC, ZS, ZW
}
```

### Volume Z-Score Drop Detection (new `check_roll()` core logic)
```python
def check_roll(self, base_symbol: str, utc_now: datetime) -> bool:
    # 1. Calendar gate first — fast path, no stats needed
    from src.config.contracts import get_roll_window
    roll_win = get_roll_window(base_symbol, utc_now.date())
    if roll_win is None:
        self._confirmation_count[base_symbol] = 0
        return False

    window = self._volume_windows.get(base_symbol)
    if window is None or len(window) < _ROLL_MIN_WINDOW:
        return False

    # 2. Volume z-score: looking for a DROP (negative z)
    vols = list(window)  # window now stores single float per bar
    mean_vol = sum(vols) / len(vols)
    std_vol = (sum((v - mean_vol)**2 for v in vols) / len(vols)) ** 0.5
    latest_vol = vols[-1]
    z_score = (latest_vol - mean_vol) / std_vol if std_vol > 0 else 0.0

    # Fire on volume drop below -2.0 SD (roll approaching, front-month volume drying up)
    candidate = z_score < -2.0

    # ... 3-bar confirmation logic unchanged
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Ratio-based roll detection (next_vol / current_vol) | Calendar + volume z-score drop | Phase 47 | Fixes confirmed bug (ratio always 1.0) |
| Hardcoded `_REGIME_PROB_MIN=0.55` / `_REGIME_DUR_MIN=3` in `aggregator.py` | Settings fields with floor defaults (0.30 / 1) | Phase 47 | Maximizes training data for Phase 49 ML |
| `CROSS_ASSET_ENABLED=false` conditional code path | Always-on (after graduation) | Phase 47 | Removes maintenance liability, DAG principle |
| `IS_SHADOW=True` in `dual_divergence.py` | Human removes flag after statistical gate passes | Phase 47+ | Plugin participates in live aggregation |
| `roll_premium_pct` untracked | Populated in `intelligence_features` during roll windows | Phase 47 | INTEL-04 ML feature for futures seasonality |

**Deprecated/outdated:**
- `_REGIME_PROB_MIN` and `_REGIME_DUR_MIN` module-level constants in `aggregator.py`: replaced by Settings fields; constants should be removed after migration (or kept as legacy default values only if imported elsewhere).
- `test_roll_detection_algorithm.py` existing tests: all test the broken ratio logic — full rewrite needed for calendar + z-score approach.

---

## Open Questions

1. **PnL_R proxy for DualDivergence shadow stats**
   - What we know: `signal_ledger` stores `outcome` (8-class) but not raw pnl_r values directly; `signal_performance_segmented` has `avg_pnl_r` but is aggregated per plugin/tf
   - What's unclear: For the bootstrap CI on E[PnL_R], we need per-signal pnl_r. The 8-class outcome maps to: target_1 → +1R, target_1_2 → +1.5R, target_full → +2R, stopped_at_entry → -0.5R, stopped_in_trade → -1R, ttl_expired_ahead → -0.5R as reasonable proxies
   - Recommendation: Map outcome strings to R-multiples using a constant dict in `compute_shadow_plugin_stats()`. This is an approximation but sufficient for the gate condition.

2. **`ctf_vix_level` etc. storage location in `intelligence_features`**
   - What we know: Phase 46 added `ctf_vix_level`, `ctf_vix_z`, `ctf_eq_spread_z`, `ctf_eq_pairs_confirming` to `I6Confluence` schema; `intelligence_features` has an `i6` JSONB column
   - What's unclear: Are these fields stored as top-level columns or inside the `i6` JSONB? The D-11 validation query must target the correct path.
   - Recommendation: Before writing the validation query, run `SELECT i6 FROM intelligence_features WHERE symbol='ESM6' LIMIT 1` to inspect actual storage format.

3. **`roll_premium_pct` computation source**
   - What we know: INTEL-04 requires `front_price - back_price` during roll windows; calendar approach avoids back-month subscription
   - What's unclear: Where does `back_price` come from if no back-month IBKR subscription?
   - Recommendation: At roll confirmation time, `_on_roll_confirmed()` already has both old and new contract symbols. The new symbol's first bar price vs. old symbol's last bar price gives the roll gap. Store `roll_gap` (already computed in `_on_roll_confirmed`) as `roll_premium_pct` in `intelligence_features` via a targeted UPDATE on the row for the roll timestamp. Mark `NULL` for all non-roll bars.

---

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest (`.venv/bin/pytest`) |
| Config file | `pytest.ini` or `setup.cfg` in project root |
| Quick run command | `.venv/bin/pytest tests/unit/test_roll_detection_algorithm.py -x -v` |
| Full suite command | `.venv/bin/pytest tests/unit/ -v` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| SHADOW-01 | `apply_regime_gate()` uses Settings `prob_min`/`dur_min` params, not hardcoded constants | unit | `.venv/bin/pytest tests/unit/test_regime_gate.py -x` | ❌ Wave 0 |
| SHADOW-02 | Cross-asset branch removal — service initializes without `_cross_asset_enabled` attribute | unit | `.venv/bin/pytest tests/unit/service_tests/ -x -k cross_asset` | ❌ Wave 0 |
| SHADOW-03 | New `check_roll()` fires only inside calendar roll window, volume z-score drop < -2.0 | unit | `.venv/bin/pytest tests/unit/test_roll_detection_algorithm.py -x -v` | ✅ (rewrite) |
| SHADOW-03 | `update_volume()` accepts single volume arg (removed next_vol) | unit | `.venv/bin/pytest tests/unit/test_roll_detection_algorithm.py -x` | ✅ (rewrite) |
| SHADOW-04 | `compute_shadow_plugin_stats()` emits correct Prometheus gauges for 0/partial/full resolved | unit | `.venv/bin/pytest tests/unit/intelligence/test_weight_updater.py -x -k shadow` | ❌ Wave 0 |
| INTEL-04 | `roll_premium_pct` column present in `intelligence_features` schema | migration | Manual DB check | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** `.venv/bin/pytest tests/unit/ -x -q`
- **Per wave merge:** `.venv/bin/pytest tests/unit/ -v`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `tests/unit/test_regime_gate.py` — covers SHADOW-01: parametric regime gate
- [ ] `tests/unit/intelligence/test_shadow_stats.py` — covers SHADOW-04: bootstrap CI, metrics emission, 0-row guard
- [ ] `tests/unit/test_roll_detection_algorithm.py` — **full rewrite** (existing file tests broken ratio logic)
- [ ] `production/migrations/049_roll_premium_pct.sql` — INTEL-04 column addition

---

## Sources

### Primary (HIGH confidence)
- Direct codebase inspection: `services/tws_daemon.py`, `src/intelligence/trading/aggregator.py`, `src/intelligence/pipeline/regime_gate.py`, `src/config/settings.py`, `src/config/contracts.py`, `src/intelligence/weight_updater.py`, `src/observability/metrics.py`, `src/intelligence/trading/dual_divergence.py`, `src/intelligence/schemas.py`
- DB query confirming: `signal_ledger` has 0 rows; `intelligence_features.roll_premium_pct` column does not exist
- CONTEXT.md locked decisions (all decisions D-01 through D-23)

### Secondary (MEDIUM confidence)
- State inference: `services/cross_asset_service.py` line 386-387 confirmed exit path location; `services/signal_generator_service.py` line 489, 767 confirmed conditional locations
- Test file inspection: `tests/unit/test_roll_detection_algorithm.py` confirmed tests broken ratio logic (VOLUME_THRESHOLDS, ratio >= threshold pattern)

### Tertiary (LOW confidence)
- Roll calendar date offsets (third Friday for quarterly, last business day for monthly energy): standard CME/CBOT contract specs, not verified against official exchange docs. Approximate is intentional per D-17 (volume z-score is the precision layer).

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — no new packages; all confirmed installed
- Architecture patterns: HIGH — verified directly from source files
- Roll detection fix: HIGH — bug confirmed at line 569 `tws_daemon.py`
- Shadow stats: HIGH — `weight_updater.py` structure verified; bootstrap CI pattern is standard
- INTEL-04: MEDIUM — column doesn't exist; computation approach (from `roll_gap` in `_on_roll_confirmed`) is inferred, not confirmed from explicit spec
- Pitfalls: HIGH — each verified against actual code (import path, line numbers)

**Research date:** 2026-03-22
**Valid until:** 2026-04-22 (stable codebase, no fast-moving dependencies)
