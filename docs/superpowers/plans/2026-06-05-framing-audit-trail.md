# Framing Audit Trail Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Capture the full stop/target framing decision audit trail — adaptive buffer multiplier, stop basis, structural distance, and plugin regime type — in `TradeFrame`, signal dict, and `signal_ledger`, while wiring `regime_type` to all 26 `frame_trade()` call sites so Hurst tightening is live.

**Architecture:** Five sequential changes form a clean data pipeline: (1) `TradeFrame` gains two new fields (`adaptive_buffer_mult`, `plugin_regime_type`) captured once in `frame_trade()`; (2) `make_signal_from_frame()` propagates all four framing audit fields into the signal dict; (3) all 26 call sites — 25 direct frame_trade() locations plus cvd_spike/ofi_spike routing through `microstructure_utils.detect_spike_signal()` — pass `regime_type=self.regime_type`; (4) migration 119 adds five typed columns to `signal_ledger` and recreates `signal_ledger_full` to expose them; (5) an OTel histogram in `metrics.py` records the buffer multiplier per `{regime_type, stop_type}` for operational alerting on vol regime drift, plus structured debug logging in `frame_trade()` when Hurst fires.

**Canonical audit field contract** (one name, used everywhere — TradeFrame field, signal dict key, DB column):

| Field | Type | Meaning |
|-------|------|---------|
| `stop_basis` | `str \| None` | Already on TradeFrame; not yet in signal dict. `"structure_snap" \| "garch_adaptive" \| "atr_static"` |
| `stop_type` | `str` | Already on TradeFrame; already in signal dict (line 276); not in DB yet. `"swing_low" \| "ob_bottom" \| ...` |
| `structural_stop_distance_atr` | `float \| None` | Already on TradeFrame; not yet in signal dict or DB. Distance of structural stop from ATR fallback in ATR units. |
| `adaptive_buffer_mult` | `float` | **New** to TradeFrame. Value is `_adaptive_buffer(features, 1.0, regime_type)` — the regime-adjusted multiplier at unit base, not stop-type-specific. Default 1.0. |
| `plugin_regime_type` | `str \| None` | **New** to TradeFrame. The plugin's declared `regime_type` passed to `frame_trade()`. `"trend" \| "mean_reversion" \| "any" \| None`. |

DB columns use these exact names. No aliasing. `stop_type` is not a PostgreSQL reserved word — no renaming needed.

**Tech Stack:** Python 3.11, pytest, asyncpg, structlog, OpenTelemetry SDK. No new dependencies.

---

## File Map

| File | Change |
|------|--------|
| `src/intelligence/trading/trade_framer.py` | Tasks 1 + 5: add `adaptive_buffer_mult` + `plugin_regime_type` to `TradeFrame`; extract multiplier variable; add structlog debug; record OTel histogram |
| `src/intelligence/trading/signal_schema.py` | Task 2: propagate 4 audit fields from `TradeFrame` into signal dict |
| `src/intelligence/trading/cross_asset_divergence.py` | Task 2: remove manual `signal["stop_basis"]` injection (construction invariant violation) |
| `src/intelligence/trading/microstructure_utils.py` | Task 3: add `regime_type: str = "any"` param to `detect_spike_signal()` |
| `src/intelligence/trading/cvd_spike.py` | Task 3: pass `regime_type=self.regime_type` to `detect_spike_signal()` |
| `src/intelligence/trading/ofi_spike.py` | Task 3: pass `regime_type=self.regime_type` to `detect_spike_signal()` |
| 25 direct plugin files (listed in Task 3) | Task 3: pass `regime_type=self.regime_type` to `frame_trade()` |
| `production/migrations/119_framing_audit_trail.sql` | Task 4: add 5 columns to `signal_ledger`; recreate `signal_ledger_full` view |
| `src/persistence/repository/signal_ledger_repository.py` | Task 4: update `LedgerEntry` + `_INSERT_SQL` + `_to_row()` |
| `services/signal_writer.py` | Task 4: populate 5 new fields from signal dict in `_payload_to_ledger_entries()` |
| `src/observability/metrics.py` | Task 5: add `STOP_BUFFER_MULT_DISTRIBUTION` histogram |
| `tests/unit/intelligence/test_trade_framer.py` | Tasks 1 + 5 |
| `tests/unit/intelligence/test_signal_schema.py` | Task 2 |
| `tests/unit/services/test_signal_writer.py` | Task 4 |

---

## Task 1: Extend TradeFrame with adaptive_buffer_mult and plugin_regime_type

**Files:**
- Modify: `src/intelligence/trading/trade_framer.py`
- Modify: `tests/unit/intelligence/test_trade_framer.py`

- [ ] **Step 1.1: Write failing tests**

Add to `tests/unit/intelligence/test_trade_framer.py` (add `frame_trade` to the import if not already present):

```python
class TestFrameTradeAuditFields:
    def test_adaptive_buffer_mult_captured_normal_regime(self):
        f = {"garch_vol_ratio": 1.0, "timeframe": "5m"}
        tf = frame_trade("trend_long", 1, 5000.0, f, atr=10.0, regime_type="trend")
        assert tf.adaptive_buffer_mult == pytest.approx(1.0, rel=1e-4)

    def test_adaptive_buffer_mult_captured_high_vol(self):
        f = {"garch_vol_ratio": 1.5, "timeframe": "5m"}
        tf = frame_trade("trend_long", 1, 5000.0, f, atr=10.0, regime_type="trend")
        assert tf.adaptive_buffer_mult == pytest.approx(1.35, rel=1e-4)

    def test_adaptive_buffer_mult_hurst_tightening(self):
        # H=0.75 trend → tighten by (0.75-0.55)*0.16 = 0.032; mult = 1.0 * (1 - 0.032) = 0.968
        f = {"garch_vol_ratio": 1.0, "hurst_exponent": 0.75, "timeframe": "5m"}
        tf = frame_trade("trend_long", 1, 5000.0, f, atr=10.0, regime_type="trend")
        assert tf.adaptive_buffer_mult == pytest.approx(1.0 * (1.0 - 0.032), rel=1e-4)

    def test_adaptive_buffer_mult_always_positive(self):
        # Invariant: never negative regardless of feature values
        f = {"garch_vol_ratio": 0.1, "hurst_exponent": 0.99, "timeframe": "5m"}
        tf = frame_trade("trend_long", 1, 5000.0, f, atr=10.0, regime_type="trend")
        assert tf.adaptive_buffer_mult > 0

    def test_plugin_regime_type_stored(self):
        f = {"timeframe": "5m"}
        tf = frame_trade("trend_long", 1, 5000.0, f, atr=10.0, regime_type="mean_reversion")
        assert tf.plugin_regime_type == "mean_reversion"

    def test_plugin_regime_type_none_when_not_passed(self):
        f = {"timeframe": "5m"}
        tf = frame_trade("trend_long", 1, 5000.0, f, atr=10.0)
        assert tf.plugin_regime_type is None
```

Run: `.venv/bin/pytest tests/unit/intelligence/test_trade_framer.py::TestFrameTradeAuditFields -v`
Expected: `AttributeError` — `TradeFrame` has no `adaptive_buffer_mult`.

- [ ] **Step 1.2: Add fields to TradeFrame dataclass**

In `src/intelligence/trading/trade_framer.py`, after line 164 (`structural_stop_distance_atr: float | None = None`), add:

```python
    adaptive_buffer_mult: float = 1.0    # _adaptive_buffer(features, 1.0, regime_type) at fire time
    plugin_regime_type: str | None = None  # plugin's self.regime_type passed to frame_trade

    def __post_init__(self) -> None:
        if self.adaptive_buffer_mult <= 0:
            raise ValueError(f"adaptive_buffer_mult must be > 0, got {self.adaptive_buffer_mult}")
```

- [ ] **Step 1.3: Extract multiplier variable and populate TradeFrame**

In `frame_trade()`, locate the `_classify_stop_basis` call (currently near line 1051). Before it, add:

```python
    # Compute once at unit base for audit trail; stop resolution uses same multiplier
    adaptive_buffer_mult = _adaptive_buffer(features, 1.0, regime_type)
    stop_basis, stop_structure_type, structural_stop_distance_atr = _classify_stop_basis(
        stop_type,
        stop,
        resolved_entry,
        atr * adaptive_buffer_mult,
        direction,
    )
    stop_structure_age_bars = _get_structure_age_bars(stop_type, features)
```

Then in the `return TradeFrame(...)`, add the two new fields:

```python
    return TradeFrame(
        entry=resolved_entry,
        entry_type=entry_type,
        stop=round(stop, 2),
        stop_type=stop_type,
        targets=targets,
        rr_t1=rr_t1,
        rr_t2=rr_t2,
        rr_t3=rr_t3,
        method=method,
        viable=True,
        rejection_reason=None,
        zone_low=zone_low,
        zone_high=zone_high,
        stop_basis=stop_basis,
        stop_structure_type=stop_structure_type,
        stop_structure_age_bars=stop_structure_age_bars,
        structural_stop_distance_atr=structural_stop_distance_atr,
        adaptive_buffer_mult=adaptive_buffer_mult,
        plugin_regime_type=regime_type,
    )
```

- [ ] **Step 1.4: Run tests**

```bash
.venv/bin/pytest tests/unit/intelligence/test_trade_framer.py -v -q
```
Expected: all PASS including `TestFrameTradeAuditFields`.

- [ ] **Step 1.5: Commit**

```bash
git add src/intelligence/trading/trade_framer.py tests/unit/intelligence/test_trade_framer.py
git commit -m "feat(trade_framer): capture adaptive_buffer_mult and plugin_regime_type in TradeFrame"
```

---

## Task 2: Propagate framing audit fields through make_signal_from_frame()

**Files:**
- Modify: `src/intelligence/trading/signal_schema.py`
- Modify: `src/intelligence/trading/cross_asset_divergence.py`
- Modify: `tests/unit/intelligence/test_signal_schema.py`

**What's already in the signal dict:** `stop_type` (line 276 of signal_schema.py). No change needed.
**What needs to be added:** `stop_basis`, `structural_stop_distance_atr`, `adaptive_buffer_mult`, `plugin_regime_type`.

- [ ] **Step 2.1: Write failing tests**

Add to `tests/unit/intelligence/test_signal_schema.py`. The existing `_viable_frame()` fixture doesn't set the new fields; build an augmented fixture:

```python
def _frame_with_audit() -> TradeFrame:
    return TradeFrame(
        entry=4500.0,
        entry_type="at_close",
        stop=4480.0,
        stop_type="swing_low",
        targets=[
            TradeTarget(price=4530.0, label="S/R 4530", level_type="sr", rr=1.5),
        ],
        rr_t1=1.5,
        method="structural",
        viable=True,
        rejection_reason=None,
        zone_low=4495.0,
        zone_high=4505.0,
        stop_basis="structure_snap",
        structural_stop_distance_atr=0.8,
        adaptive_buffer_mult=0.968,
        plugin_regime_type="trend",
    )


class TestFramingAuditPropagation:
    def test_stop_basis_in_signal(self):
        sig = make_signal_from_frame(_frame_with_audit(), **_frame_kwargs())
        assert sig["stop_basis"] == "structure_snap"

    def test_structural_stop_distance_atr_in_signal(self):
        sig = make_signal_from_frame(_frame_with_audit(), **_frame_kwargs())
        assert sig["structural_stop_distance_atr"] == pytest.approx(0.8)

    def test_adaptive_buffer_mult_in_signal(self):
        sig = make_signal_from_frame(_frame_with_audit(), **_frame_kwargs())
        assert sig["adaptive_buffer_mult"] == pytest.approx(0.968)

    def test_plugin_regime_type_in_signal(self):
        sig = make_signal_from_frame(_frame_with_audit(), **_frame_kwargs())
        assert sig["plugin_regime_type"] == "trend"

    def test_none_fields_present_when_not_set(self):
        # TradeFrame without audit fields set → fields present at defaults
        tf = _viable_frame()  # existing fixture; no audit fields explicitly set
        sig = make_signal_from_frame(tf, **_frame_kwargs())
        assert "stop_basis" in sig
        assert "adaptive_buffer_mult" in sig
        assert sig["stop_basis"] is None
        assert sig["adaptive_buffer_mult"] == pytest.approx(1.0)
```

Run: `.venv/bin/pytest tests/unit/intelligence/test_signal_schema.py::TestFramingAuditPropagation -v`
Expected: `KeyError` on `stop_basis`.

- [ ] **Step 2.2: Propagate fields in make_signal_from_frame()**

In `src/intelligence/trading/signal_schema.py`, in `make_signal_from_frame()`, after `sig["zone_source"] = ...` (or the last existing sig[] assignment before return), add:

```python
    sig["stop_basis"] = tf.stop_basis
    sig["structural_stop_distance_atr"] = tf.structural_stop_distance_atr
    sig["adaptive_buffer_mult"] = tf.adaptive_buffer_mult
    sig["plugin_regime_type"] = tf.plugin_regime_type
```

Note: `stop_type` is already propagated (line ~276). No change needed there.

- [ ] **Step 2.3: Remove manual stop_basis injection in cross_asset_divergence.py**

In `src/intelligence/trading/cross_asset_divergence.py`, find and delete line ~234:

```python
signal["stop_basis"] = tf.stop_basis
```

`make_signal_from_frame()` is now the sole authority for this field. Verify no other manual injection exists for `structural_stop_distance_atr`, `adaptive_buffer_mult`, or `plugin_regime_type`.

- [ ] **Step 2.4: Run tests**

```bash
.venv/bin/pytest tests/unit/intelligence/test_signal_schema.py tests/unit/intelligence/test_trade_framer.py -q
```
Expected: all PASS.

- [ ] **Step 2.5: Commit**

```bash
git add src/intelligence/trading/signal_schema.py src/intelligence/trading/cross_asset_divergence.py tests/unit/intelligence/test_signal_schema.py
git commit -m "feat(signal_schema): propagate framing audit trail (stop_basis, structural_dist, buffer_mult, plugin_regime_type) through make_signal_from_frame"
```

---

## Task 3: Wire regime_type to all 26 frame_trade() call sites

**Files:**
- Modify: `src/intelligence/trading/microstructure_utils.py`
- Modify: `src/intelligence/trading/cvd_spike.py`
- Modify: `src/intelligence/trading/ofi_spike.py`
- Modify: 25 direct plugin files (listed below)

**Authoritative call site count** (from grep of repo — do not trust the original plan's list):

```bash
grep -rn "frame_trade(" src/intelligence/trading/ --include="*.py" \
  | grep -v "def frame_trade\|test_\|#" | sort
```

This must return exactly 26 lines (25 plugin/utility files + trade_framer.py internal references excluded). The 25 direct frame_trade() call sites, by regime categorization from each plugin's class attribute:

**Trend (8 files):**
- `src/intelligence/trading/lvn_breakout.py` (~line 124)
- `src/intelligence/trading/mtf_alignment.py` (~line 83)
- `src/intelligence/trading/ofi_continuation.py` (~line 106)
- `src/intelligence/trading/orb15.py` (~line 226)
- `src/intelligence/trading/orb30.py` (~line 227)
- `src/intelligence/trading/second_leg_continuation.py` (~line 153)
- `src/intelligence/trading/trend_following.py` (~line 92)
- `src/intelligence/trading/vcp.py` (~line 188)

**Mean-reversion (9 files):**
- `src/intelligence/trading/anchored_vwap_reversion.py` (~line 119)
- `src/intelligence/trading/cvd_divergence.py` (~line 135)
- `src/intelligence/trading/delta_exhaustion.py` (~line 115)
- `src/intelligence/trading/dual_divergence.py` (~line 125)
- `src/intelligence/trading/failed_breakout.py` (~line 161)
- `src/intelligence/trading/fvg_fill.py` (~line 85)
- `src/intelligence/trading/hvn_rejection.py` (~line 152)
- `src/intelligence/trading/mean_reversion.py` (~line 109)
- `src/intelligence/trading/poc_rejection.py` (~line 128)

**Any (8 files — Hurst adjustment suppressed, `regime_type` still recorded for audit):**
- `src/intelligence/trading/choch_reversal.py` (~line 87)
- `src/intelligence/trading/cross_asset_divergence.py` (~line 193)
- `src/intelligence/trading/divergence_stack.py` (~line 222)
- `src/intelligence/trading/ofi_divergence.py` (~line 163)
- `src/intelligence/trading/pattern_completion.py` (~line 108)
- `src/intelligence/trading/prev_day_level_test.py` (~line 222)
- `src/intelligence/trading/regime_transition.py` (~line 91)
- `src/intelligence/trading/vwap_reclaim.py` (~line 169)

**Via utility (+1 call site, 2 callers):**
- `src/intelligence/trading/microstructure_utils.py` (~line 79) — called by cvd_spike + ofi_spike

> **Note:** `momentum_breakout`, `squeeze_expansion`, `liquidity_hunt`, `liquidity_sweep_reclaim`, `session_extremes_setup`, `vwap_deviation`, `candlestick_pattern_setup`, `gap_analysis_setup`, `supply_demand_setup` all declare `regime_type` class attributes but do NOT call `frame_trade()` directly. Do not modify them in this task.

- [ ] **Step 3.1: Write a contract test**

Add to `tests/unit/intelligence/test_trade_framer.py`:

```python
class TestRegimeTypeWired:
    def test_hurst_tightening_fires_for_trend_regime_type(self):
        from src.intelligence.trading.trade_framer import _adaptive_buffer
        f = {"garch_vol_ratio": 1.0, "hurst_exponent": 0.75}
        mult = _adaptive_buffer(f, 1.0, regime_type="trend")
        assert mult < 1.0, "Hurst tightening did not fire for trend regime_type"

    def test_no_hurst_tightening_when_regime_type_none(self):
        from src.intelligence.trading.trade_framer import _adaptive_buffer
        f = {"garch_vol_ratio": 1.0, "hurst_exponent": 0.75}
        mult = _adaptive_buffer(f, 1.0, regime_type=None)
        assert mult == pytest.approx(1.0)
```

Run: `.venv/bin/pytest tests/unit/intelligence/test_trade_framer.py::TestRegimeTypeWired -v`
Expected: both PASS (these test the existing `_adaptive_buffer` contract, not new code).

- [ ] **Step 3.2: Add regime_type param to detect_spike_signal()**

In `src/intelligence/trading/microstructure_utils.py`, update the function signature:

```python
def detect_spike_signal(
    frames: dict[str, Any],
    spike_feature_key: str,
    signal_name_prefix: str,
    min_lookback: int = 20,
    setup_plugin: str = "",
    regime_type: str = "any",
) -> dict[str, Any]:
```

And update the `frame_trade` call within it (~line 79):

```python
    tf = frame_trade(sig_type, direction, entry, features, atr, regime_type=regime_type)
```

- [ ] **Step 3.3: Update cvd_spike.py and ofi_spike.py**

In `src/intelligence/trading/cvd_spike.py`, find the `detect_spike_signal(...)` call and add `regime_type=self.regime_type`:

```python
        return detect_spike_signal(
            frames,
            "cvd_spike_z",
            "cvd_spike",
            setup_plugin=self.name,
            regime_type=self.regime_type,
        )
```

Apply the same change to `src/intelligence/trading/ofi_spike.py`:

```python
        return detect_spike_signal(
            frames,
            "ofi_spike_z",
            "ofi_spike",
            setup_plugin=self.name,
            regime_type=self.regime_type,
        )
```

- [ ] **Step 3.4: Wire all 25 direct plugin call sites**

The pattern is identical for every plugin: find the `frame_trade(...)` call and add `regime_type=self.regime_type` as the final keyword argument. Each plugin already declares the correct `self.regime_type` class attribute — no value needs to be changed, only threaded through.

After editing all 25 files, run the acceptance check — this must return zero results:

```bash
grep -rn "frame_trade(" src/intelligence/trading/ --include="*.py" \
  | grep -v "def frame_trade\|regime_type=\|microstructure_utils\|test_\|trade_framer.py"
# → must return 0 results
```

- [ ] **Step 3.5: Run full unit suite**

```bash
.venv/bin/pytest tests/unit/ -q --tb=short 2>&1 | tail -5
```
Expected: all PASS.

- [ ] **Step 3.6: Commit**

```bash
git add \
  src/intelligence/trading/microstructure_utils.py \
  src/intelligence/trading/cvd_spike.py \
  src/intelligence/trading/ofi_spike.py \
  src/intelligence/trading/anchored_vwap_reversion.py \
  src/intelligence/trading/choch_reversal.py \
  src/intelligence/trading/cross_asset_divergence.py \
  src/intelligence/trading/cvd_divergence.py \
  src/intelligence/trading/delta_exhaustion.py \
  src/intelligence/trading/divergence_stack.py \
  src/intelligence/trading/dual_divergence.py \
  src/intelligence/trading/failed_breakout.py \
  src/intelligence/trading/fvg_fill.py \
  src/intelligence/trading/hvn_rejection.py \
  src/intelligence/trading/lvn_breakout.py \
  src/intelligence/trading/mean_reversion.py \
  src/intelligence/trading/mtf_alignment.py \
  src/intelligence/trading/ofi_continuation.py \
  src/intelligence/trading/ofi_divergence.py \
  src/intelligence/trading/orb15.py \
  src/intelligence/trading/orb30.py \
  src/intelligence/trading/pattern_completion.py \
  src/intelligence/trading/poc_rejection.py \
  src/intelligence/trading/prev_day_level_test.py \
  src/intelligence/trading/regime_transition.py \
  src/intelligence/trading/second_leg_continuation.py \
  src/intelligence/trading/trend_following.py \
  src/intelligence/trading/vcp.py \
  src/intelligence/trading/vwap_reclaim.py
git commit -m "feat(i7-plugins): wire regime_type to all frame_trade() call sites — activates Hurst tightening"
```

---

## Task 4: DB migration + signal_ledger persistence

**Files:**
- Create: `production/migrations/119_framing_audit_trail.sql`
- Modify: `src/persistence/repository/signal_ledger_repository.py`
- Modify: `services/signal_writer.py`
- Modify: `tests/unit/services/test_signal_writer.py`

- [ ] **Step 4.1: Verify migration numbering**

```bash
ls production/migrations/ | sort | tail -3
# → confirm latest is 118_*.sql, so next is 119
```

- [ ] **Step 4.2: Write failing test for signal_writer enrichment**

Add to `tests/unit/services/test_signal_writer.py`:

```python
class TestFramingAuditFieldsInLedgerEntry:
    def _minimal_payload(self) -> dict:
        return {
            "symbol": "ES",
            "tf": "5m",
            "bar_ts": "2026-01-01T10:00:00Z",
            "computed_at": "2026-01-01T10:00:01Z",
            "signals": [
                {
                    "signal_id": "00000000-0000-0000-0000-000000000001",
                    "signal_type": "trend_long",
                    "setup_plugin": "TrendFollowingPlugin",
                    "direction": 1,
                    "was_selected": True,
                    "entry_price": 5000.0,
                    "stop_loss": 4980.0,
                    "targets": [5030.0],
                    "zone_low": 4995.0,
                    "zone_high": 5005.0,
                    "ttl_bars": 10,
                    "stop_basis": "structure_snap",
                    "stop_type": "swing_low",
                    "structural_stop_distance_atr": 0.7,
                    "adaptive_buffer_mult": 0.968,
                    "plugin_regime_type": "trend",
                }
            ],
        }

    def test_stop_basis_extracted(self):
        from services.signal_writer import _payload_to_ledger_entries
        entries = _payload_to_ledger_entries(self._minimal_payload())
        assert entries[0].stop_basis == "structure_snap"

    def test_stop_type_extracted(self):
        from services.signal_writer import _payload_to_ledger_entries
        entries = _payload_to_ledger_entries(self._minimal_payload())
        assert entries[0].stop_type == "swing_low"

    def test_structural_stop_distance_extracted(self):
        from services.signal_writer import _payload_to_ledger_entries
        entries = _payload_to_ledger_entries(self._minimal_payload())
        assert entries[0].structural_stop_distance_atr == pytest.approx(0.7)

    def test_adaptive_buffer_mult_extracted(self):
        from services.signal_writer import _payload_to_ledger_entries
        entries = _payload_to_ledger_entries(self._minimal_payload())
        assert entries[0].adaptive_buffer_mult == pytest.approx(0.968)

    def test_plugin_regime_type_extracted(self):
        from services.signal_writer import _payload_to_ledger_entries
        entries = _payload_to_ledger_entries(self._minimal_payload())
        assert entries[0].plugin_regime_type == "trend"

    def test_missing_fields_default_to_none(self):
        from services.signal_writer import _payload_to_ledger_entries
        payload = self._minimal_payload()
        del payload["signals"][0]["stop_basis"]
        del payload["signals"][0]["adaptive_buffer_mult"]
        entries = _payload_to_ledger_entries(payload)
        assert entries[0].stop_basis is None
        assert entries[0].adaptive_buffer_mult is None
```

Run: `.venv/bin/pytest tests/unit/services/test_signal_writer.py::TestFramingAuditFieldsInLedgerEntry -v`
Expected: `AttributeError` — `LedgerEntry` has no `stop_basis`.

- [ ] **Step 4.3: Create migration 119**

Create `production/migrations/119_framing_audit_trail.sql`:

```sql
-- Migration 119: framing audit trail columns on signal_ledger + view refresh
-- Captures stop/target decision metadata at fire time for outcome segmentation.
-- All new columns nullable: historical rows predate this feature.

ALTER TABLE signal_ledger
    ADD COLUMN IF NOT EXISTS stop_basis                  text,
    ADD COLUMN IF NOT EXISTS stop_type                   text,
    ADD COLUMN IF NOT EXISTS structural_stop_distance_atr double precision,
    ADD COLUMN IF NOT EXISTS adaptive_buffer_mult        double precision,
    ADD COLUMN IF NOT EXISTS plugin_regime_type          text;

COMMENT ON COLUMN signal_ledger.stop_basis IS '"structure_snap"|"garch_adaptive"|"atr_static"';
COMMENT ON COLUMN signal_ledger.stop_type IS 'structural level that anchored the stop (swing_low, ob_bottom, etc.)';
COMMENT ON COLUMN signal_ledger.structural_stop_distance_atr IS 'distance of structural stop from ATR fallback in ATR units';
COMMENT ON COLUMN signal_ledger.adaptive_buffer_mult IS '_adaptive_buffer(features, 1.0, regime_type) at fire time; 1.0 = no adjustment';
COMMENT ON COLUMN signal_ledger.plugin_regime_type IS '"trend"|"mean_reversion"|"any"|null';

-- Recreate view to expose new fire-time columns.
-- signal_ledger_full uses explicit column selection; new sl.* columns are invisible
-- to existing consumers until this view is recreated.
CREATE OR REPLACE VIEW signal_ledger_full AS
SELECT
    sl.signal_id,
    sl."timestamp",
    sl.symbol,
    sl.timeframe,
    sl.setup_plugin,
    sl.signal_type,
    sl.direction,
    sl.was_selected,
    sl.is_shadow,
    sl.is_backfill,
    sl.signal_schema_version,
    sl.feature_schema_version,
    sl.signal_computed_at,
    sl.feature_ts,
    sl.feature_tf,
    sl.hmm_regime_at_fire,
    sl.garch_sigma_at_fire,
    sl.ttl_bars,
    sl.expires_at,
    sl.entry_price,
    sl.stop_loss,
    sl.targets,
    sl.entry_zone_low,
    sl.entry_zone_high,
    sl.market_entry_price,
    sl.cis_score,
    sl.bucket_scores,
    sl.weights_version,
    sl.pipeline_lag_ms,
    sl.stop_basis,
    sl.stop_type,
    sl.structural_stop_distance_atr,
    sl.adaptive_buffer_mult,
    sl.plugin_regime_type,
    so.status,
    so.activated_at,
    so.activation_price,
    so.zone_entry_pct,
    so.bars_to_activation,
    so.exit_at,
    so.exit_price,
    so.exit_reason,
    so.pnl_ticks,
    so.pnl_r,
    so.pnl_dollars,
    so.signal_quality,
    so.mae,
    so.mfe,
    so.bars_in_trade,
    so.outcome,
    so.market_entry_at,
    so.market_entry_exit_price,
    so.market_entry_exit_at,
    so.market_entry_outcome,
    so.market_entry_pnl_r,
    so.market_entry_mae,
    so.market_entry_mfe,
    so.market_entry_bars_in_trade,
    so.market_entry_gap_bars,
    so.trailing_stop_price,
    so.trailing_stop_tightening_rate,
    so.staleness_score,
    so.staleness_trigger_reason,
    so.chandelier_vol_source,
    so.shadow_tracking_start_ts,
    so.shadow_mae,
    so.shadow_mfe,
    so.shadow_outcome,
    so.effective_ts
FROM signal_ledger sl
LEFT JOIN signal_outcomes so ON sl.signal_id = so.signal_id;
```

- [ ] **Step 4.4: Update LedgerEntry dataclass**

In `src/persistence/repository/signal_ledger_repository.py`, add five new optional fields to `LedgerEntry` after `feature_schema_version` (before the `status` field):

```python
    feature_schema_version: int | None = None
    stop_basis: str | None = None
    stop_type: str | None = None
    structural_stop_distance_atr: float | None = None
    adaptive_buffer_mult: float | None = None
    plugin_regime_type: str | None = None
    # Initial status for signal_outcomes seeding — NOT stored in signal_ledger
    status: SignalStatus = SignalStatus.PENDING
```

- [ ] **Step 4.5: Update _INSERT_SQL**

Replace the existing `_INSERT_SQL` with (current $28 → $33 after adding 5 fields):

```python
_INSERT_SQL = """
INSERT INTO signal_ledger (
    signal_id, timestamp, symbol, timeframe,
    setup_plugin, signal_type, direction,
    was_selected, is_shadow, is_backfill,
    signal_computed_at,
    feature_ts, feature_tf,
    hmm_regime_at_fire, garch_sigma_at_fire,
    ttl_bars,
    entry_price, stop_loss, targets, entry_zone_low, entry_zone_high,
    market_entry_price,
    cis_score, bucket_scores, weights_version,
    pipeline_lag_ms, expires_at,
    feature_schema_version,
    stop_basis, stop_type, structural_stop_distance_atr,
    adaptive_buffer_mult, plugin_regime_type
) VALUES (
    $1::uuid, $2, $3, $4,
    $5, $6, $7,
    $8, $9, $10,
    $11,
    $12, $13,
    $14, $15,
    $16,
    $17, $18, $19::jsonb, $20, $21,
    $22,
    $23, $24::jsonb, $25,
    $26, $27,
    $28,
    $29, $30, $31,
    $32, $33
)
ON CONFLICT (signal_id, timestamp) DO NOTHING
"""
```

- [ ] **Step 4.6: Update _to_row()**

In `LedgerEntry._to_row()`, extend the tuple to match the 33-parameter INSERT:

```python
    def _to_row(self) -> tuple:
        return (
            self.signal_id,                      # $1
            self.timestamp,                      # $2
            self.symbol,                         # $3
            self.timeframe,                      # $4
            self.setup_plugin,                   # $5
            self.signal_type,                    # $6
            self.direction,                      # $7
            self.was_selected,                   # $8
            self.is_shadow,                      # $9
            self.is_backfill,                    # $10
            self.signal_computed_at,             # $11
            self.feature_ts,                     # $12
            self.feature_tf,                     # $13
            self.hmm_regime_at_fire,             # $14
            self.garch_sigma_at_fire,            # $15
            self.ttl_bars,                       # $16
            self.entry_price,                    # $17
            self.stop_loss,                      # $18
            self.targets,                        # $19 list → asyncpg JSONB
            self.entry_zone_low,                 # $20
            self.entry_zone_high,                # $21
            self.market_entry_price,             # $22
            self.cis_score,                      # $23
            self.bucket_scores,                  # $24 dict → asyncpg JSONB
            self.weights_version,                # $25
            self.pipeline_lag_ms,                # $26
            self.expires_at,                     # $27
            self.feature_schema_version,         # $28
            self.stop_basis,                     # $29
            self.stop_type,                      # $30
            self.structural_stop_distance_atr,   # $31
            self.adaptive_buffer_mult,           # $32
            self.plugin_regime_type,             # $33
        )
```

- [ ] **Step 4.7: Update signal_writer.py**

In `services/signal_writer.py`, in `_payload_to_ledger_entries()`, add the five new fields to the `LedgerEntry(...)` constructor call after `feature_schema_version=FEATURE_SCHEMA_VERSION`:

```python
                feature_schema_version=FEATURE_SCHEMA_VERSION,
                stop_basis=sig.get("stop_basis"),
                stop_type=sig.get("stop_type"),
                structural_stop_distance_atr=sig.get("structural_stop_distance_atr"),
                adaptive_buffer_mult=sig.get("adaptive_buffer_mult"),
                plugin_regime_type=sig.get("plugin_regime_type"),
```

- [ ] **Step 4.8: Run tests**

```bash
.venv/bin/pytest tests/unit/services/test_signal_writer.py -q
.venv/bin/pytest tests/unit/ -q --tb=short 2>&1 | tail -5
```
Expected: all PASS.

- [ ] **Step 4.9: Apply migration to local DB**

```bash
PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -f production/migrations/119_framing_audit_trail.sql
# → ALTER TABLE ... CREATE OR REPLACE VIEW
```

Verify view includes new columns:

```bash
PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c \
  "SELECT column_name FROM information_schema.columns WHERE table_name='signal_ledger_full' AND column_name IN ('stop_basis','stop_type','adaptive_buffer_mult','plugin_regime_type');"
# → must return 4 rows
```

- [ ] **Step 4.10: Commit**

```bash
git add production/migrations/119_framing_audit_trail.sql \
        src/persistence/repository/signal_ledger_repository.py \
        services/signal_writer.py \
        tests/unit/services/test_signal_writer.py
git commit -m "feat(signal_ledger): add framing audit trail columns + recreate signal_ledger_full view"
```

---

## Task 5: OTel histogram + structlog debug

**Files:**
- Modify: `src/observability/metrics.py`
- Modify: `src/intelligence/trading/trade_framer.py`
- Modify: `tests/unit/intelligence/test_trade_framer.py`

- [ ] **Step 5.1: Write failing test**

Add to `tests/unit/intelligence/test_trade_framer.py`:

```python
class TestFrameTradeObservability:
    def test_structlog_debug_emitted_when_hurst_fires(self, caplog):
        import logging
        with caplog.at_level(logging.DEBUG, logger="src.intelligence.trading.trade_framer"):
            f = {"garch_vol_ratio": 1.0, "hurst_exponent": 0.75, "timeframe": "5m"}
            frame_trade("trend_long", 1, 5000.0, f, atr=10.0, regime_type="trend")
        messages = " ".join(r.message for r in caplog.records)
        assert "adaptive_buffer_applied" in messages

    def test_no_debug_when_buffer_neutral(self, caplog):
        import logging
        with caplog.at_level(logging.DEBUG, logger="src.intelligence.trading.trade_framer"):
            f = {"garch_vol_ratio": 1.0, "timeframe": "5m"}
            frame_trade("trend_long", 1, 5000.0, f, atr=10.0)
        messages = " ".join(r.message for r in caplog.records)
        assert "adaptive_buffer_applied" not in messages
```

Run: `.venv/bin/pytest tests/unit/intelligence/test_trade_framer.py::TestFrameTradeObservability -v`
Expected: FAIL.

- [ ] **Step 5.2: Add histogram to metrics.py**

In `src/observability/metrics.py`, after the `SIGNAL_MFE_DISTRIBUTION` block:

```python
STOP_BUFFER_MULT_DISTRIBUTION = _meter.create_histogram(
    "stop_buffer_mult_distribution",
    description="Adaptive buffer multiplier at frame time by regime_type and stop_type — alerts on vol regime drift",
    unit="1",
)
```

`stop_type` is bounded (swing_low, ob_bottom, demand_zone, etc.) — cardinality is safe.

- [ ] **Step 5.3: Add import and observability block to frame_trade()**

Check for existing structlog import:

```bash
grep -n "import structlog\|_logger" src/intelligence/trading/trade_framer.py | head -5
```

If not present, add at the top:

```python
import structlog as _structlog
_logger = _structlog.get_logger(__name__)
```

Add the metrics import:

```python
from src.observability.metrics import STOP_BUFFER_MULT_DISTRIBUTION
```

After the `adaptive_buffer_mult = _adaptive_buffer(features, 1.0, regime_type)` line (Task 1 Step 1.3), after `stop_type` is resolved:

```python
    STOP_BUFFER_MULT_DISTRIBUTION.record(
        adaptive_buffer_mult,
        {"regime_type": regime_type or "any", "stop_type": stop_type},
    )
    if adaptive_buffer_mult != 1.0 and regime_type in ("trend", "mean_reversion"):
        _logger.debug(
            "adaptive_buffer_applied",
            regime_type=regime_type,
            vol_ratio=features.get("garch_vol_ratio"),
            hurst=features.get("hurst_exponent"),
            buffer_mult=round(adaptive_buffer_mult, 4),
            stop_type=stop_type,
        )
```

- [ ] **Step 5.4: Run all tests**

```bash
.venv/bin/pytest tests/unit/ -q --tb=short 2>&1 | tail -5
```
Expected: all PASS.

- [ ] **Step 5.5: Run verification greps**

```bash
# No unwired frame_trade() callers
grep -rn "frame_trade(" src/intelligence/trading/ --include="*.py" \
  | grep -v "def frame_trade\|regime_type=\|microstructure_utils\|test_\|trade_framer.py"
# → 0 results

# TradeFrame audit fields present
grep -n "adaptive_buffer_mult\|plugin_regime_type" src/intelligence/trading/trade_framer.py

# Signal dict carries audit fields
grep -n "adaptive_buffer_mult\|plugin_regime_type\|stop_basis\|structural_stop" \
  src/intelligence/trading/signal_schema.py

# LedgerEntry + INSERT carry all 5 fields
grep -n "stop_basis\|stop_type\|adaptive_buffer_mult\|plugin_regime_type\|structural_stop" \
  src/persistence/repository/signal_ledger_repository.py

# View exposes new columns (live check)
PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c \
  "SELECT stop_basis, stop_type, adaptive_buffer_mult, plugin_regime_type FROM signal_ledger_full LIMIT 0;"
# → must not error
```

- [ ] **Step 5.6: Commit**

```bash
git add src/observability/metrics.py src/intelligence/trading/trade_framer.py tests/unit/intelligence/test_trade_framer.py
git commit -m "feat(observability): stop_buffer_mult OTel histogram + structlog debug in frame_trade"
```

---

## Done-Coding SOP

After all tasks are committed:

```bash
# 1. code-simplifier agent (invoke automatically)
# 2. /review
# 3. pytest tests/unit/ -q   # must be green
# 4. git checkout main && git merge --ff-only <branch>
# 5. git branch -d <branch>
# 6. git worktree prune
# 7. git push origin main
```

---

## Research Queries Unlocked After Deployment

```sql
-- Which stop_type produces the best outcomes?
SELECT stop_type, AVG(o.pnl_r) AS avg_pnl_r, COUNT(*) AS n
FROM signal_ledger sl
JOIN signal_outcomes o USING (signal_id)
WHERE sl.stop_basis = 'structure_snap'
  AND o.outcome NOT IN ('ttl_expired_ahead', 'ttl_expired_behind', 'never_activated')
GROUP BY stop_type
ORDER BY avg_pnl_r DESC;

-- Does Hurst tightening (buffer_mult < 1.0) improve outcomes for trend plugins?
SELECT
    adaptive_buffer_mult < 1.0 AS hurst_tightened,
    AVG(o.pnl_r)               AS avg_pnl_r,
    AVG(o.mae)                 AS avg_mae,
    COUNT(*)                   AS n
FROM signal_ledger sl
JOIN signal_outcomes o USING (signal_id)
WHERE plugin_regime_type = 'trend'
  AND adaptive_buffer_mult IS NOT NULL
GROUP BY hurst_tightened;

-- How does structural_stop_distance_atr correlate with MAE?
SELECT
    ROUND(structural_stop_distance_atr::numeric, 1) AS dist_bucket,
    AVG(o.mae) AS avg_mae,
    COUNT(*)   AS n
FROM signal_ledger sl
JOIN signal_outcomes o USING (signal_id)
WHERE structural_stop_distance_atr IS NOT NULL
GROUP BY dist_bucket
ORDER BY dist_bucket;
```
