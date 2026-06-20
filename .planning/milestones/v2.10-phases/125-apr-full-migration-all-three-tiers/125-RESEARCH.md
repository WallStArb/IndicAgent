# Phase 125: APR Full Migration — All Three Tiers - Research

**Researched:** 2026-06-14
**Domain:** Adaptive Parameter Registry (APR) — config_state seeding, ConfigService wiring, weight sum invariant
**Confidence:** HIGH

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**D-01: Wire 3 gate constants to APR; load bootstrap weights from cis_weights table.**

Three detection gate constants belong in APR (they are Tier A gates identical in kind to all other threshold.* keys):
- `threshold.cis.fire_threshold` = 0.35
- `threshold.cis.bucket_agree_min` = 3
- `threshold.cis.bucket_noise_floor` = 0.1

`CISScorer.__init__` must be updated to load bootstrap weights from `cis_weights` table (MAX(version) WHERE symbol='global') instead of the hardcoded `BOOTSTRAP_WEIGHTS` dict. The existing `update_weights()` hot-swap method is preserved; the service layer calls it at startup with DB-loaded weights. The `BOOTSTRAP_WEIGHTS` dict is removed (or kept as a DB-unavailable fallback only).

**Rationale:** `BOOTSTRAP_WEIGHTS` must NOT go into `config_state`. The `cis_weights` table (migration 012) is the correct and already-designed home - it's a versioned weight store with bootstrap version=1. Adding the same values to APR would create two sources of truth for weights, an architecture violation.

**D-02: Add 4 new float keys in migration 132. Do not modify the existing min_width_atr key.**

New keys to seed:
- `feature.zone_engine.min_zone_width_atr` = 1.5 (float, default/fallback)
- `feature.zone_engine.min_zone_width_atr.equity_etf` = 1.5
- `feature.zone_engine.min_zone_width_atr.forex` = 1.0
- `feature.zone_engine.min_zone_width_atr.futures` = 1.5

These are **distinct** from `feature.zone_engine.min_width_atr` = 0.25 (the zone expansion minimum in `_expand_to_min_width()` - already seeded in migration 129, already wired, leave untouched). Phase 126 wires the consumption code for the new `min_zone_width_atr` keys; Phase 125 only seeds the DB. Zero behavior change.

**D-03: Shared `_validate_weights_sum()` utility in `confidence_utils.py`, called at Tier B plugin prewarm/init.**

Signature: `_validate_weights_sum(weights: dict[str, float], plugin: str, tol: float = 1e-6) -> None`

Raises `ValueError` (NOT `AssertionError` - asserts are disabled by `-O`) with message: `f"{plugin} weights sum to {total:.6f}, expected 1.0"`. Called in each Tier B plugin immediately after loading weights from ConfigService at prewarm/init time.

**Naming rationale:** `_validate_weights_sum` names the mathematical role. The roadmap uses `_assert_weights_sum` but the CONTEXT.md supersedes it on naming.

**D-04: Fix `cfg` parameter name in `confidence_utils.py` when touching the file.**

`set_config_service(cfg: Any)` - `cfg` is a Tier 3 banned abbreviation. Rename parameter to `config` when adding `_validate_weights_sum()`.

**D-05: Capture two cleanup TODOs - do NOT fix in Phase 125.**

- `confidence_utils.py` file name: `Utils` is a retired word. Should be renamed to `confidence.py`. 39 import sites - out of scope.
- `_cfg()` in `zone_engine.py`: `cfg` abbreviation in function name. Should be `_read_config()`. Phase 125 does not touch `zone_engine.py` code.

### Claude's Discretion

- Exact migration number (current max is 131; next is 132 - researcher confirms no intervening migrations)
- Whether any Tier A/B constants identified in TODO 025 still need DB seeding (researcher verifies against migrations 128/129 to find gaps)
- `config_history` provenance string for new min_zone_width_atr keys: `'rca_analysis'` with reason citing Phase 126 noise-band analysis
- Whether `CISScorer` loads from `cis_weights` directly (asyncpg query) or via an injected loader; service layer wiring is researcher/planner scope
- Tolerance on `_assert_weights_sum`: 1e-6 default (float representation of 0.40+0.35+0.25 may not be exactly 1.0)

### Deferred Ideas (OUT OF SCOPE)

- **trade_framer.py constants** - 16 hardcoded ATR multipliers and RR thresholds. Deferred to after Phase 127 (requires counterfactual_pnl_r data for ML tuning). See `.planning/todos/pending/2026-06-14-trade-framer-apr-migration.md`.
- **cis_weights learned-weight ML loop** - Phase B architecture (ML-trained weights replacing bootstrap). Requires 100+ resolved signals per segment. v2.11+.
- **min_stop_distance_atr per-asset-class keys** - Phase 126 scope (needed when wiring the zone-width gate).
</user_constraints>

---

## Summary

Migrations 128, 129, and 131 have already seeded nearly all TODO 025 constants into `config_state`. Verified against live DB: 37 threshold keys, 24 weight keys, and 5 feature keys are already seeded. The active-vs-gap analysis reveals exactly 10 new keys needed in migration 132, split across three clusters: 3 CIS detection gate constants, 4 new zone-width ATR keys for Phase 126's zone entry gate, and 3 `anchored_vwap_reversion` confidence weights that were inadvertently omitted from migration 129.

CIS bucket weights (trend/momentum/structure/pattern/institutional/regime) are a fully separate concern from the 3 CIS gate constants. The `cis_weights` table loading via `CacheManager._load_cis_weights()` is already implemented and operational - the live table has 5 learned weight versions. `CISScorer.sync_cis_weights()` is called on every bar via `SignalProcessor.sync_cis_weights()`. No new CIS weight infrastructure is needed; Phase 125 only needs to wire the 3 gate constants (fire threshold, bucket agreement minimum, noise floor) to APR and remove/demote `BOOTSTRAP_WEIGHTS` to fallback-only status.

All 8 Tier B plugins except `anchored_vwap_reversion` are fully wired - they read weights from `ConfigService.get_sync()` in their `compute_full()` methods. The `_validate_weights_sum()` utility does not yet exist; it needs to be added to `confidence_utils.py`. The function applies to the 6 plugins with true weighted sums (gap_analysis, mean_reversion, momentum_breakout, squeeze_expansion, vwap_reclaim, anchored_vwap_reversion); it does NOT apply to liquidity_sweep_reclaim and supply_demand_setup which use base+scale formulas rather than weighted sums.

**Primary recommendation:** Write migration 132 with exactly 10 keys (3 CIS gate + 4 zone-width + 3 vwap_reversion weights), add `_validate_weights_sum()` to `confidence_utils.py`, wire `anchored_vwap_reversion.py` weight reads from config, add module-level `set_config_service()` to `cis_scorer.py` for the 3 gate constants, and extend `_THRESHOLD_KEYS` + `_prewarm_threshold_config()` in `intelligence_pipeline.py`.

---

## Standard Stack

### Core Tools in Use

| Component | File | Version | Status |
|-----------|------|---------|--------|
| ConfigService | `src/config/config_service.py` | Phase 109 | Production |
| `get_sync()` | `src/config/config_service.py` | Phase 109 | Pattern established |
| Migration format | `production/migrations/129_plugin_param_store.sql` | Migration 129 | Canonical reference |
| `cis_weights` table | `production/migrations/012_cis_weights_table.sql` | Migration 012 | Operational with 5 learned versions |
| `confidence_utils.py` | `src/intelligence/trading/confidence_utils.py` | Current | Home for `_validate_weights_sum()` |

### Migration 132 Canonical Format

Follow `production/migrations/129_plugin_param_store.sql` exactly. Triple-insert pattern per key:
1. `config_schema` INSERT with `ON CONFLICT (config_key) DO NOTHING`
2. `config_state` INSERT with `ON CONFLICT (config_key) DO NOTHING`
3. `config_history` INSERT with `changed_by` and `reason`

---

## Architecture Patterns

### What Is Already Done (Verified Against Live DB and Source Code)

**Migration 129 seeded and wired (do not touch):**

All 24 Tier A detection gate keys and 24 Tier B weight keys listed in TODO 025 are in `config_state` - EXCEPT the 3 CIS gate constants and the 3 `anchored_vwap_reversion` weights. All 6 Tier C zone engine geometry keys are seeded and wired.

All plugins in scope (except `anchored_vwap_reversion` and `cis_scorer`) have `_config_service: Any = field(default=None, compare=False, repr=False)` and read from `ConfigService.get_sync()` in `compute_full()`.

The `_prewarm_threshold_config()` in `intelligence_pipeline.py` already:
- Iterates `_THRESHOLD_KEYS` and calls `await self._config_service.get(key, default)` on all of them
- Calls `confidence_utils.set_config_service(self._config_service)`
- Calls `volume_profile_utils.set_config_service(self._config_service)`
- Calls `zone_engine.set_config_service(self._config_service)`
- Calls `aggregator.set_config_service(self._config_service)`
- Injects `_config_service` into all plugins that have the field via `if hasattr(p, "_config_service")`

**CIS weight loading already fully operational:**

`CacheManager._load_cis_weights()` queries `cis_weights` WHERE `asset_cluster = 'global' AND timeframe = 'global'` ORDER BY version DESC LIMIT 1. This runs at `load_initial()` startup and every 30 minutes. `SignalProcessor.sync_cis_weights()` is called at the start of every bar and calls `CISScorer.update_weights()` when version changes. Live `cis_weights` table has 5 rows, all `weights_type = 'learned'` (no `designed` bootstrap row).

### What Phase 125 Must Add

**Pattern 1: Module-level Config Singleton (for CISScorer gate constants)**

Add to `src/intelligence/trading/cis_scorer.py`:

```python
# Module-level config service singleton - same pattern as confidence_utils.py
_config_service: Any | None = None


def set_config_service(config: Any) -> None:
    global _config_service
    _config_service = config
```

In `CISScorer.score()`, replace hardcoded constant reads:

```python
# Replace:
if abs(cis_score) > CIS_FIRE_THRESHOLD:
# With:
fire_threshold = (
    _config_service.get_sync("threshold.cis.fire_threshold", CIS_FIRE_THRESHOLD)
    if _config_service is not None
    else CIS_FIRE_THRESHOLD
)
if abs(cis_score) > fire_threshold:
```

Same pattern for `BUCKET_AGREE_MIN` and `BUCKET_NOISE_FLOOR`.

**Pattern 2: _validate_weights_sum utility (in confidence_utils.py)**

```python
def _validate_weights_sum(weights: dict[str, float], plugin: str, tol: float = 1e-6) -> None:
    """Validate that confidence weights sum to 1.0 within floating-point tolerance.

    Raises ValueError (not AssertionError - asserts disabled by -O) if the
    invariant is violated. Called at prewarm/init time so bad DB seeds or
    bad operator writes fail fast at daemon startup, before any signal fires.

    Args:
        weights: Dict of weight name -> value (e.g. {'roc': 0.40, 'vol': 0.35, ...}).
        plugin:  Human-readable plugin name for error messages.
        tol:     Floating-point tolerance. Default 1e-6 handles float repr of 0.40+0.35+0.25.
    """
    total = sum(weights.values())
    if abs(total - 1.0) > tol:
        raise ValueError(f"{plugin} weights sum to {total:.6f}, expected 1.0")
```

**Pattern 3: anchored_vwap_reversion weight reads (code wiring)**

In `src/intelligence/trading/anchored_vwap_reversion.py`, inside `compute_full()` where thresholds are loaded (lines 103-110), add:

```python
w_sigma = cfg.get_sync("weights.vwap_reversion.sigma_magnitude", 0.40) if cfg else 0.40
w_hurst = cfg.get_sync("weights.vwap_reversion.hurst_quality", 0.35) if cfg else 0.35
w_vol_s = cfg.get_sync("weights.vwap_reversion.vol_stability", 0.25) if cfg else 0.25
```

Replace hardcoded line 253:
```python
# Replace:
raw_conf = 0.40 * sigma_magnitude + 0.35 * hurst_quality + 0.25 * vol_stability
# With:
raw_conf = w_sigma * sigma_magnitude + w_hurst * hurst_quality + w_vol_s * vol_stability
```

**Pattern 4: _THRESHOLD_KEYS extension**

Add to `_THRESHOLD_KEYS` tuple in `intelligence_pipeline.py`:

```python
# --- migration 132: Phase 125 CIS gate constants ---
("threshold.cis.fire_threshold", 0.35),
("threshold.cis.bucket_agree_min", 3),
("threshold.cis.bucket_noise_floor", 0.1),
# --- migration 132: Phase 125 zone entry width gate (consumed by Phase 126) ---
("feature.zone_engine.min_zone_width_atr", 1.5),
("feature.zone_engine.min_zone_width_atr.equity_etf", 1.5),
("feature.zone_engine.min_zone_width_atr.forex", 1.0),
("feature.zone_engine.min_zone_width_atr.futures", 1.5),
# --- migration 132: Phase 125 anchored_vwap_reversion Tier B weights ---
("weights.vwap_reversion.sigma_magnitude", 0.40),
("weights.vwap_reversion.hurst_quality", 0.35),
("weights.vwap_reversion.vol_stability", 0.25),
```

**Pattern 5: _prewarm_threshold_config extension**

After the existing `set_config_service()` injections, add:

```python
from src.intelligence.trading import cis_scorer  # noqa: PLC0415
cis_scorer.set_config_service(self._config_service)
```

### _validate_weights_sum Call Sites (at prewarm time in intelligence_pipeline.py)

The planner must decide WHERE to call `_validate_weights_sum` for each applicable plugin. Two options:

**Option A - In `_prewarm_threshold_config()` directly:** Load all weights for each plugin and call `_validate_weights_sum`. Clean but adds logic to pipeline prewarm.

**Option B - In each plugin's `compute_full()` guard:** After loading weights from cfg, call `_validate_weights_sum`. Only called once per (plugin, bar) cycle, not at prewarm.

The CONTEXT.md says "called in each Tier B plugin immediately after loading weights from ConfigService at prewarm/init time" - this points to Option A or a pattern where the plugin itself calls the validator in `compute_full()` on every call (acceptable since it's microseconds and raises only on sum violation).

**Plugins where `_validate_weights_sum` applies (true weighted sum, sums to 1.0):**

| Plugin | Weights | Expected Sum |
|--------|---------|--------------|
| `gap_analysis_setup` | geo(0.40) + vol(0.25) + timing(0.20) + type(0.15) | 1.00 |
| `mean_reversion` | rsi_extreme(0.30) + div_score(0.30) + vol_stability(0.20) + sr_proximity(0.20) | 1.00 |
| `momentum_breakout` | roc(0.40) + vol(0.35) + break_margin(0.25) | 1.00 |
| `squeeze_expansion` | squeeze_bars(0.35) + vol_expansion(0.35) + momentum(0.30) | 1.00 |
| `vwap_reclaim` | vol(0.30) + duration(0.30) + trend_align(0.20) + sr_proximity(0.20) | 1.00 |
| `anchored_vwap_reversion` | sigma_magnitude(0.40) + hurst_quality(0.35) + vol_stability(0.25) | 1.00 |

**Plugins where `_validate_weights_sum` does NOT apply (base + scale * ramp formulas):**

| Plugin | Formula | Why Not |
|--------|---------|---------|
| `liquidity_sweep_reclaim` | `base_conf + depth_scale * linear_ramp(...)` | Not a weighted sum to 1.0 |
| `supply_demand_setup` | `base_conf + freshness_scale * linear_ramp(...)` | Not a weighted sum to 1.0 |

### Migration 132 Key Inventory

**10 new keys total:**

```
threshold.cis.fire_threshold        float  0.35   [initial_estimate]  CIS fire gate. ML learning target.
threshold.cis.bucket_agree_min      int    3      [initial_estimate]  Min agreeing buckets for CIS fire. ML learning target.
threshold.cis.bucket_noise_floor    float  0.1    [initial_estimate]  Min |bucket_score| to count as agreeing. ML learning target.
feature.zone_engine.min_zone_width_atr              float  1.5    [rca_analysis]  Phase 126 zone entry gate (default/fallback). Noise-band analysis.
feature.zone_engine.min_zone_width_atr.equity_etf   float  1.5    [rca_analysis]  Phase 126 zone entry gate for equity/ETF. Noise-band analysis.
feature.zone_engine.min_zone_width_atr.forex        float  1.0    [rca_analysis]  Phase 126 zone entry gate for forex. Tighter noise band.
feature.zone_engine.min_zone_width_atr.futures      float  1.5    [rca_analysis]  Phase 126 zone entry gate for futures. Noise-band analysis.
weights.vwap_reversion.sigma_magnitude  float  0.40   [initial_estimate]  Sigma magnitude weight in AnchoredVWAPReversionPlugin. ML learning target.
weights.vwap_reversion.hurst_quality    float  0.35   [initial_estimate]  Hurst quality weight in AnchoredVWAPReversionPlugin. ML learning target.
weights.vwap_reversion.vol_stability    float  0.25   [initial_estimate]  Vol stability weight in AnchoredVWAPReversionPlugin. ML learning target.
```

**Existing keys to NOT touch** (already seeded and wired):
- `feature.zone_engine.min_width_atr` = 0.25 (zone expansion minimum in `_expand_to_min_width()`, migration 129)
- All 37 threshold.* keys in config_state
- All 24 weights.* keys in config_state (excluding the 3 new vwap_reversion keys)
- All 5 feature.* keys in config_state (excluding the 4 new min_zone_width_atr keys)

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Weight sum validation | Custom per-plugin assert in each plugin | `_validate_weights_sum()` in confidence_utils.py | Centralizes invariant; all 6 plugins share one code path |
| CIS gate config reads | New singleton infrastructure | Same module-level `_config_service` + `set_config_service()` pattern as confidence_utils.py | Pattern already established across 4 modules |
| CIS weight loading | New DB query in CISScorer.__init__ | cache_manager._load_cis_weights() already handles this; CISScorer.update_weights() receives weights via SignalProcessor.sync_cis_weights() | Architecture already correct - adding a second DB query would violate SoC |
| Migration | Custom script | SQL triple-insert following migration 129 format exactly | ON CONFLICT DO NOTHING is idempotent and safe |

---

## Common Pitfalls

### Pitfall 1: CIS Bucket Weights vs. CIS Gate Constants (Different Systems)

**What goes wrong:** Planner conflates BOOTSTRAP_WEIGHTS (6 bucket weights) with the 3 gate constants (fire_threshold, bucket_agree_min, bucket_noise_floor). Tries to put BOOTSTRAP_WEIGHTS into config_state.

**Why it happens:** Both live in cis_scorer.py. They look similar.

**How to avoid:** BOOTSTRAP_WEIGHTS go into `cis_weights` table (already done - table has 5 learned versions). Gate constants go into `config_state` as `threshold.cis.*`. Never add weights.cis.* to config_state.

**Warning signs:** Any PR touching config_state with a `weights.cis.*` key is wrong.

### Pitfall 2: min_zone_width_atr vs. min_width_atr Collision

**What goes wrong:** Editor or reviewer confuses the new `min_zone_width_atr` key with the existing `min_width_atr` key (already seeded in migration 129 at 0.25). Modifies the wrong key.

**Why it happens:** Very similar names. Both are zone engine ATR keys.

**How to avoid:** The existing `feature.zone_engine.min_width_atr` = 0.25 controls zone EXPANSION (`_expand_to_min_width()`). The new `feature.zone_engine.min_zone_width_atr` = 1.5 controls zone ENTRY width gate. They serve different purposes. Do NOT modify the existing key.

**Warning signs:** Any migration that UPDATEs rather than INSERTs an existing zone_engine key is suspect.

### Pitfall 3: _validate_weights_sum on Non-Weighted-Sum Plugins

**What goes wrong:** Calling `_validate_weights_sum` on `liquidity_sweep_reclaim` or `supply_demand_setup`. These use `base + scale * ramp()` formulas - the parameters don't sum to 1.0 and shouldn't.

**Why it happens:** They're in the Tier B list and have "weights.*" config keys.

**How to avoid:** Only call `_validate_weights_sum` on plugins with true `w1*f1 + w2*f2 + ... = raw_conf` where the weights sum to 1.0 by design. See the table in Architecture Patterns above.

### Pitfall 4: anchored_vwap_reversion Weight Keys Wrong Namespace

**What goes wrong:** Using `weights.anchored_vwap.*` instead of `weights.vwap_reversion.*` as specified in TODO 025.

**Why it happens:** Natural instinct is to name after the file (`anchored_vwap_reversion.py`).

**How to avoid:** TODO 025 specifies `weights.vwap_reversion.*` as the namespace. Use exactly: `weights.vwap_reversion.sigma_magnitude`, `weights.vwap_reversion.hurst_quality`, `weights.vwap_reversion.vol_stability`.

### Pitfall 5: ValueError vs AssertionError in _validate_weights_sum

**What goes wrong:** Using `assert total == 1.0, ...` instead of `raise ValueError`.

**Why it happens:** Natural instinct for invariant checking.

**How to avoid:** Python `-O` flag disables `assert` statements in production. `ValueError` always fires. Per CONTEXT.md D-03: always `ValueError`, never `AssertionError`.

### Pitfall 6: set_config_service Parameter Name

**What goes wrong:** Adding `_validate_weights_sum` to confidence_utils.py without fixing the `cfg` parameter in `set_config_service(cfg: Any)`.

**Why it happens:** Tunnel vision on the new function.

**How to avoid:** CONTEXT.md D-04 explicitly requires: when touching confidence_utils.py, rename `set_config_service(cfg: Any)` to `set_config_service(config: Any)`. Both changes go in the same commit. Also update the test file `tests/unit/intelligence/test_param_store_migration.py` which calls `teardown_function` using `cu.set_config_service(None)` - this still works, just the internal parameter name changes.

### Pitfall 7: Pre-existing Test Failures

**What goes wrong:** Attempting to make ALL 4781 tests pass and breaking Phase 125's schedule.

**Why it happens:** CONTEXT.md says "pytest tests/unit/ -q green."

**How to avoid:** At the time of research, 42 tests in 12 files have pre-existing failures unrelated to Phase 125 (signal_replay_auditor, api routes, settings_equity, lifecycle_tracker, pattern_completion, signal_ledger, trade_framer, vwap_deviation, capture_signal_features, pipeline_reset, run_historical_pipeline). Phase 125 must not introduce NEW failures and new Phase 125 tests must pass. Do not fix pre-existing failures.

---

## Code Examples

### Migration 132 Triple-Insert Pattern (from migration 129)

```sql
-- Schema entry
INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description) VALUES
('threshold.cis.fire_threshold', 'float', '0.35', 0.0, 1.0,
 '[initial_estimate] Minimum abs(CIS score) for CIS to fire a direction. ML learning target.')
ON CONFLICT (config_key) DO NOTHING;

-- Live state
INSERT INTO config_state (config_key, config_value, version) VALUES
('threshold.cis.fire_threshold', '0.35', 1)
ON CONFLICT (config_key) DO NOTHING;

-- History
INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason) VALUES
(NOW(), 'threshold.cis.fire_threshold', 1, '0.35', 'initial_estimate', 'Migration 132 seed - Phase 125 CIS gate constants')
```

### _prewarm_threshold_config Extension (intelligence_pipeline.py)

```python
async def _prewarm_threshold_config(self) -> None:
    """Pre-warm config cache and inject ConfigService into all configurable plugins."""
    assert self._config_service is not None
    for key, default in self._THRESHOLD_KEYS:
        await self._config_service.get(key, default)

    from src.intelligence.trading import (  # noqa: PLC0415
        aggregator,
        cis_scorer,          # ADD THIS
        confidence_utils,
        volume_profile_utils,
        zone_engine,
    )

    confidence_utils.set_config_service(self._config_service)
    volume_profile_utils.set_config_service(self._config_service)
    zone_engine.set_config_service(self._config_service)
    aggregator.set_config_service(self._config_service)
    cis_scorer.set_config_service(self._config_service)   # ADD THIS

    # existing plugin injection via hasattr(_config_service) ...
```

### test_param_store_migration.py Pattern (for new CIS gate tests)

```python
# Source: tests/unit/intelligence/test_param_store_migration.py (existing pattern)
import src.intelligence.trading.cis_scorer as cs

def teardown_function():
    cs.set_config_service(None)
    # ... existing teardowns

def test_cis_fire_threshold_returns_config_value():
    cs.set_config_service(_make_cfg(0.42))
    scorer = cs.CISScorer()
    # fire_threshold read inside score() - test via calling score() with boundary values

def test_cis_fire_threshold_returns_constant_when_no_config():
    assert cs.CIS_FIRE_THRESHOLD == 0.35
```

### _validate_weights_sum Unit Test Pattern

```python
import pytest
from src.intelligence.trading.confidence_utils import _validate_weights_sum

def test_validate_weights_sum_passes_on_exact():
    _validate_weights_sum({"a": 0.40, "b": 0.35, "c": 0.25}, "TestPlugin")

def test_validate_weights_sum_passes_within_tolerance():
    # Python float repr of 0.40+0.35+0.25 may not be exactly 1.0
    _validate_weights_sum({"a": 0.4, "b": 0.3, "c": 0.3}, "TestPlugin")

def test_validate_weights_sum_raises_on_bad_seed():
    with pytest.raises(ValueError, match="TestPlugin weights sum to"):
        _validate_weights_sum({"a": 0.40, "b": 0.40, "c": 0.25}, "TestPlugin")
```

---

## State of the Art (What Changed Before This Phase)

| Migration | Keys Seeded | Coverage |
|-----------|-------------|----------|
| 128 | 7 keys | Tier A Phase 118 detection gates (trend_following, ofi_continuation, pattern_completion, vwap_reversion thresholds) |
| 129 | 50 keys | Bulk seed: 24 Tier A, 22 Tier B (8 plugins), all 6 Tier C zone_engine |
| 131 | 14 keys | Phase 124 plugin parameters (trend_following expanded, ofi_continuation expanded) |
| **132** | **10 keys** | **Phase 125: CIS gate constants, min_zone_width_atr (4 keys), anchored_vwap_reversion weights** |

**What TODO 025 listed vs. what was actually done:**

- TODO 025 listed `threshold.hvn_rejection.div_threshold` and `threshold.poc_rejection.div_threshold` as separate keys. These are served by `threshold.volume_profile.div_min` (already seeded), which is read via `get_div_threshold()` in `volume_profile_utils.py` by both plugins. NOT a gap.
- TODO 025 listed CIS bucket weights as "weights.cis.*" targeting config_state. This was correctly re-routed to `cis_weights` table architecture (migration 012, operational with 5 learned versions). NOT a config_state gap.
- The ONLY missed Tier B plugin is `anchored_vwap_reversion` - its 3 weights (0.40/0.35/0.25) are hardcoded at line 253 and were not included in migration 129.

---

## Open Questions

1. **Where exactly should `_validate_weights_sum` be invoked?**
   - What we know: CONTEXT.md says "at prewarm/init time" but plugins currently load weights inline in `compute_full()` on every call.
   - What's unclear: Should it be called from `_prewarm_threshold_config()` (one-time at startup), or from inside each plugin's `compute_full()` (every call), or via a new dedicated prewarm method on each plugin?
   - Recommendation: Call from each plugin's `compute_full()` on the first weight-load path (when `cfg` is not None). This is consistent with where weights are already loaded and provides protection against hot-reload writes. The overhead is negligible (dict sum + compare). The planner should document this choice.

2. **BOOTSTRAP_WEIGHTS dict: remove or keep as fallback?**
   - What we know: CONTEXT.md says "removed (or kept as a DB-unavailable fallback only)". The `cis_weights` table has 5 learned rows; no designed row exists. If `_load_cis_weights()` fails at startup, `CISScorer` would have an empty weights dict.
   - What's unclear: Should `BOOTSTRAP_WEIGHTS` survive as a last-resort fallback in `CISScorer.__init__` when cache has not yet loaded? Or is the startup failure mode acceptable?
   - Recommendation: Keep `BOOTSTRAP_WEIGHTS` as a `_CONFIG_UNAVAILABLE_FALLBACK` constant (renamed to be explicit). This provides safe fallback if DB is unavailable at startup. Remove it as the primary default (replace with None, and use it only if cache has no weights yet).

3. **min_zone_width_atr keys: should they prewarm to avoid cold-start?**
   - What we know: Phase 126 wires the consumption code. Phase 125 only seeds them.
   - What's unclear: Should the 4 new keys be added to `_THRESHOLD_KEYS` in Phase 125 (for cache prewarm) even though no code reads them yet?
   - Recommendation: YES - add them to `_THRESHOLD_KEYS`. The prewarm loop just pre-loads cache; it causes no harm if no code reads the key yet. And it ensures the cache is warm when Phase 126 wires the consumption code.

---

## Sources

### Primary (HIGH confidence)

All findings verified against live code and DB.

- Live DB state: `config_state` table - 37 threshold, 24 weights, 5 feature keys (queried 2026-06-14)
- `src/intelligence/trading/cis_scorer.py` - BOOTSTRAP_WEIGHTS, CIS_FIRE_THRESHOLD, BUCKET_AGREE_MIN, BUCKET_NOISE_FLOOR, update_weights(), score()
- `src/intelligence/trading/confidence_utils.py` - set_config_service(cfg), get_min_regime_weight(), get_min_ctf_score()
- `src/intelligence/trading/anchored_vwap_reversion.py` - line 253 hardcoded weights, _config_service field
- `src/intelligence/pipeline/cache_manager.py` - _load_cis_weights(), load_initial(), seed_cis_weights()
- `src/intelligence/pipeline/signal_processor.py` - sync_cis_weights(), line 245 per-bar call
- `services/intelligence_pipeline.py` - _THRESHOLD_KEYS, _prewarm_threshold_config(), CISScorer() construction
- `production/migrations/128_threshold_config_params.sql` - 7 keys
- `production/migrations/129_plugin_param_store.sql` - 50 keys, canonical format reference
- `production/migrations/131_phase124_param_store.sql` - 14 keys
- `production/migrations/012_cis_weights_table.sql` - cis_weights table schema
- `tests/unit/intelligence/test_param_store_migration.py` - test pattern reference

### Secondary (MEDIUM confidence)

- `src/intelligence/trading/delta_exhaustion.py` line 37 - module-level assert pattern (reference for why `_validate_weights_sum` uses ValueError instead)
- `.planning/todos/pending/025-parameter-store-full-plugin-migration.md` - authoritative Tier A/B/C list (some entries since superseded by migration 129)

---

## Metadata

**Confidence breakdown:**
- Migration 132 key inventory: HIGH - directly queried live DB to find gaps
- CIS architecture (weight loading vs gate constants): HIGH - traced full call chain in source
- anchored_vwap_reversion gap: HIGH - confirmed hardcoded line 253, confirmed missing from migration 129
- _validate_weights_sum applicability: HIGH - checked actual formulas in liquidity_sweep and supply_demand
- Pre-existing test failures: HIGH - ran pytest, 42 failures in 12 files pre-Phase 125
- TODO 025 vs migration 129 cross-check: HIGH - compared TODO list vs live config_state query

**Research date:** 2026-06-14
**Valid until:** 2026-07-14 (stable domain; no external dependencies)
