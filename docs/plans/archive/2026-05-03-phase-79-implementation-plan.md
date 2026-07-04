# Phase 79: Signal Quality Fix — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix zero-width activation zone propagation and wrong entry_price bugs that cause 99.7% signal never-activated rate and negative PnL on target hits.

**Architecture:** Add `make_signal_from_frame()` helper to `signal_schema.py` that auto-extracts all TradeFrame fields (zones, resolved entry, framing metadata). Migrate all 28 I7 plugins to use it. Wire signal_writer to map new fields to existing LedgerEntry columns. Add Prometheus metrics for signal quality monitoring. Add co-fire tracking in aggregator.

**Tech Stack:** Python 3.11+, asyncpg, prometheus_client/OTel, TimescaleDB

---

## Task 1: `make_signal_from_frame()` helper + tests

**Files:**
- Modify: `src/intelligence/trading/signal_schema.py`
- Test: `tests/unit/intelligence/test_signal_schema.py`

- [ ] **Step 1: Write tests for `make_signal_from_frame()`**

Create `tests/unit/intelligence/test_signal_schema.py`:

```python
"""Tests for make_signal_from_frame() — Phase 79 signal quality fix."""
import pytest
from src.intelligence.trading.signal_schema import make_signal_from_frame, validate_signal
from src.intelligence.trading.trade_framer import TradeFrame, TradeTarget


def _viable_frame(**overrides) -> TradeFrame:
    defaults = dict(
        entry=4500.0, entry_type="at_close", stop=4480.0, stop_type="atr",
        targets=[
            TradeTarget(price=4530.0, label="S/R 4530", level_type="sr", rr=2.5),
            TradeTarget(price=4550.0, label="VWAP+1σ 4550", level_type="vwap_1sigma", rr=3.5),
        ],
        rr_t1=2.5, rr_t2=3.5, rr_t3=0.0, method="structural",
        viable=True, rejection_reason=None,
        zone_low=4490.0, zone_high=4505.0,
    )
    defaults.update(overrides)
    return TradeFrame(**defaults)


def test_make_signal_from_frame_propagates_zones():
    tf = _viable_frame()
    sig = make_signal_from_frame(
        tf, symbol="ESM6", timeframe="1m", timestamp="2026-05-05T10:00:00Z",
        setup_plugin="trad_FVGFill", direction=1, confidence=0.75,
        regime_context="bullish", confluence_score=0.6,
        supporting_factors=["fvg_fill"], invalidation_conditions=["fvg_close"],
    )
    assert sig["zone_low"] == 4490.0
    assert sig["zone_high"] == 4505.0
    assert sig["entry_type"] == "at_close"


def test_make_signal_from_frame_uses_resolved_entry():
    tf = _viable_frame(entry=4520.0, entry_type="at_pullback")
    sig = make_signal_from_frame(
        tf, symbol="ESM6", timeframe="15m", timestamp="2026-05-05T10:00:00Z",
        setup_plugin="trad_MTFAlignment", direction=-1, confidence=0.8,
        regime_context="bearish", confluence_score=0.7,
        supporting_factors=["3_timeframes_aligned"], invalidation_conditions=["ctf_break"],
    )
    assert sig["entry_price"] == 4520.0  # tf.entry, NOT raw close
    assert sig["entry_type"] == "at_pullback"


def test_make_signal_from_frame_schema_version():
    tf = _viable_frame()
    sig = make_signal_from_frame(
        tf, symbol="ESM6", timeframe="1m", timestamp="2026-05-05T10:00:00Z",
        setup_plugin="trad_FVGFill", direction=1, confidence=0.75,
        regime_context="bullish", confluence_score=0.6,
        supporting_factors=["test"], invalidation_conditions=["test"],
    )
    assert sig["signal_schema_version"] == "v1"


def test_make_signal_from_frame_propagates_stop_type_and_targets():
    tf = _viable_frame()
    sig = make_signal_from_frame(
        tf, symbol="ESM6", timeframe="1m", timestamp="2026-05-05T10:00:00Z",
        setup_plugin="trad_FVGFill", direction=1, confidence=0.75,
        regime_context="bullish", confluence_score=0.6,
        supporting_factors=["test"], invalidation_conditions=["test"],
    )
    assert sig["stop_type"] == "atr"
    assert sig["targets"] == [4530.0, 4550.0]
    assert sig["target_labels"] == ["S/R 4530", "VWAP+1σ 4550"]
    assert sig["target_types"] == ["sr", "vwap_1sigma"]
    assert sig["rr_t1"] == 2.5
    assert sig["rr_t2"] == 3.5


def test_make_signal_from_frame_rejects_nonviable():
    tf = _viable_frame(viable=False, rejection_reason="no_targets_found")
    with pytest.raises(ValueError, match="non-viable TradeFrame"):
        make_signal_from_frame(
            tf, symbol="ESM6", timeframe="1m", timestamp="2026-05-05T10:00:00Z",
            setup_plugin="trad_FVGFill", direction=1, confidence=0.75,
            regime_context="bullish", confluence_score=0.6,
            supporting_factors=["test"], invalidation_conditions=["test"],
        )


def test_make_signal_from_frame_validates_as_signal_v1():
    tf = _viable_frame()
    sig = make_signal_from_frame(
        tf, symbol="ESM6", timeframe="1m", timestamp="2026-05-05T10:00:00Z",
        setup_plugin="trad_FVGFill", direction=1, confidence=0.75,
        regime_context="bullish", confluence_score=0.6,
        supporting_factors=["test"], invalidation_conditions=["test"],
    )
    assert validate_signal(sig) is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/unit/intelligence/test_signal_schema.py -v`
Expected: FAIL — `make_signal_from_frame` not defined

- [ ] **Step 3: Implement `make_signal_from_frame()` in `signal_schema.py`**

Add to end of `src/intelligence/trading/signal_schema.py` (after the existing `make_signal` function):

```python
from __future__ annotations — already at top of file

# Add import at top of file:
from src.intelligence.trading.trade_framer import TradeFrame


def make_signal_from_frame(
    tf: "TradeFrame",
    *,
    symbol: str,
    timeframe: str,
    timestamp: str,
    setup_plugin: str,
    direction: int,
    confidence: float,
    regime_context: str,
    confluence_score: float,
    supporting_factors: list[str],
    invalidation_conditions: list[str],
    ttl_bars: int = 10,
    features_snapshot: dict | None = None,
) -> dict:
    """Construct a validated signal.v1 dict from a TradeFrame.

    Auto-extracts entry_price, stop_loss, targets, zones, and all framing
    metadata from the TradeFrame. Use this instead of manual dict construction
    to ensure zone fields and resolved entry propagate correctly.
    """
    if not tf.viable:
        raise ValueError(
            f"Cannot build signal from non-viable TradeFrame: {tf.rejection_reason}"
        )
    sig = make_signal(
        symbol=symbol,
        timeframe=timeframe,
        timestamp=timestamp,
        signal_type=f"{setup_plugin}_{('long' if direction == 1 else 'short')}",
        setup_plugin=setup_plugin,
        direction=direction,
        entry_price=tf.entry,
        stop_loss=tf.stop,
        targets=[t.price for t in tf.targets],
        confidence=confidence,
        regime_context=regime_context,
        confluence_score=confluence_score,
        supporting_factors=supporting_factors,
        invalidation_conditions=invalidation_conditions,
        ttl_bars=ttl_bars,
        entry_type=tf.entry_type,
        stop_type=tf.stop_type,
        target_labels=[t.label for t in tf.targets],
        target_types=[t.level_type for t in tf.targets],
        rr_t1=tf.rr_t1,
        rr_t2=tf.rr_t2,
        rr_t3=tf.rr_t3,
        framing_method=tf.method,
    )
    sig["zone_low"] = tf.zone_low
    sig["zone_high"] = tf.zone_high
    sig["signal_schema_version"] = "v1"
    if features_snapshot is not None:
        sig["features_snapshot"] = features_snapshot
    return sig
```

Note: `make_signal` already computes `signal_type` internally from `signal_type` parameter, but plugins set their own `signal_type` using `signal_type_for_direction()`. The `make_signal` parameter `signal_type` is used directly. Verify this doesn't double-prefix — check that `signal_type_for_direction("fvg_fill", 1)` returns `"fvg_fill_long"` and `make_signal` stores it as-is. If plugins previously set signal_type manually, the helper should accept it as a parameter. Let me correct:

Actually looking at `make_signal()`, the `signal_type` parameter is stored directly. Plugins call `signal_type_for_direction("mtf_alignment", 1)` which returns `"mtf_alignment_long"`. So the helper should take `signal_type` as a parameter, not derive it. Updated signature:

```python
def make_signal_from_frame(
    tf: "TradeFrame",
    *,
    symbol: str,
    timeframe: str,
    timestamp: str,
    signal_type: str,  # from signal_type_for_direction()
    setup_plugin: str,
    direction: int,
    confidence: float,
    regime_context: str,
    confluence_score: float,
    supporting_factors: list[str],
    invalidation_conditions: list[str],
    ttl_bars: int = 10,
    features_snapshot: dict | None = None,
) -> dict:
```

And pass `signal_type=signal_type` to `make_signal()` instead of deriving it.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/unit/intelligence/test_signal_schema.py -v`
Expected: All 7 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/intelligence/trading/signal_schema.py tests/unit/intelligence/test_signal_schema.py
git commit -m "feat(079-01): add make_signal_from_frame() helper with zone propagation"
```

---

## Task 2: Wire signal_writer zone mapping

**Files:**
- Modify: `services/signal_writer_agent.py:136-179`

- [ ] **Step 1: Add zone/version/co-fire field mapping to `_payload_to_ledger_entries()`**

In `services/signal_writer_agent.py`, inside `_payload_to_ledger_entries()`, add these fields to the `LedgerEntry(` constructor after the existing `weights_version=sig.get("weights_version"),` line:

```python
                entry_zone_low=sig.get("zone_low"),
                entry_zone_high=sig.get("zone_high"),
                signal_schema_version=sig.get("signal_schema_version", "v0"),
                entry_type=sig.get("entry_type", "at_close"),
                co_fire_count=sig.get("co_fire_count", 1),
                co_fire_partners=sig.get("co_fire_partners", []),
```

Note: `entry_zone_low` and `entry_zone_high` already exist on `LedgerEntry` (line 93-94). The new fields (`signal_schema_version`, `entry_type`, `co_fire_count`, `co_fire_partners`) need to be added to `LedgerEntry` in Task 3.

- [ ] **Step 2: Commit**

```bash
git add services/signal_writer_agent.py
git commit -m "feat(079-02): wire zone/version/co-fire fields in signal_writer"
```

---

## Task 3: Extend LedgerEntry + DB migration

**Files:**
- Modify: `src/persistence/repository/signal_ledger_repository.py`
- Create: `production/migrations/079_signal_quality_zones.sql`

- [ ] **Step 1: Add new fields to `LedgerEntry` dataclass**

In `src/persistence/repository/signal_ledger_repository.py`, add after the `pre_calibration_confidence` field (around line 140):

```python
    # Phase 79: Signal quality fix — zone propagation + lineage + co-fire
    signal_schema_version: str = "v0"
    entry_type: str | None = None  # "at_close"|"at_pullback"|"at_limit"|"at_reclaim"|"zone_proximal"
    co_fire_count: int = 1
    co_fire_partners: list = field(default_factory=list)
```

Update `to_insert_params()` to include these new fields in the tuple. Find the current last element and append:

```python
            self.signal_schema_version,
            self.entry_type,
            self.co_fire_count,
            self.co_fire_partners,
```

Update the INSERT SQL string in `insert_signals()` to match the new column count. Add columns `signal_schema_version, entry_type, co_fire_count, co_fire_partners` and corresponding `$N` placeholders.

Update `to_update_dict()` and any SELECT queries that reconstruct `LedgerEntry` from rows to include these columns.

- [ ] **Step 2: Create DB migration**

Create `production/migrations/079_signal_quality_zones.sql`:

```sql
-- Phase 79: Signal quality fix — add schema version, entry_type, co-fire tracking
ALTER TABLE signal_ledger ADD COLUMN IF NOT EXISTS signal_schema_version text DEFAULT 'v0';
ALTER TABLE signal_ledger ADD COLUMN IF NOT EXISTS entry_type text DEFAULT 'at_close';
ALTER TABLE signal_ledger ADD COLUMN IF NOT EXISTS co_fire_count int DEFAULT 1;
ALTER TABLE signal_ledger ADD COLUMN IF NOT EXISTS co_fire_partners text[] DEFAULT '{}';

-- Verify zone columns exist (they should from Phase 1 institutional fields)
-- entry_zone_low and entry_zone_high should already exist; this is a safety check
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'signal_ledger' AND column_name = 'entry_zone_low') THEN
        ALTER TABLE signal_ledger ADD COLUMN entry_zone_low float;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'signal_ledger' AND column_name = 'entry_zone_high') THEN
        ALTER TABLE signal_ledger ADD COLUMN entry_zone_high float;
    END IF;
END $$;

-- Index for ML training data filtering by schema version
CREATE INDEX IF NOT EXISTS idx_ledger_schema_version ON signal_ledger (signal_schema_version) WHERE signal_schema_version = 'v1';
```

- [ ] **Step 3: Run existing tests to verify no regressions**

Run: `.venv/bin/pytest tests/unit/ -v --timeout=60`
Expected: All existing tests pass

- [ ] **Step 4: Commit**

```bash
git add src/persistence/repository/signal_ledger_repository.py production/migrations/079_signal_quality_zones.sql
git commit -m "feat(079-03): extend LedgerEntry with schema_version, entry_type, co_fire fields + migration"
```

---

## Task 4: Migrate I7 plugins to `make_signal_from_frame()` (batch 1)

**Files:**
- Modify: `src/intelligence/trading/fvg_fill.py`
- Modify: `src/intelligence/trading/trend_following.py`
- Modify: `src/intelligence/trading/mtf_alignment.py`
- Modify: `src/intelligence/trading/mean_reversion.py`
- Modify: `src/intelligence/trading/choch_reversal.py`
- Modify: `src/intelligence/trading/anchored_vwap_reversion.py`

For **each plugin**, the migration pattern is identical:

1. Add import: `from .signal_schema import make_signal_from_frame`
2. Remove unused variables: `stop = tf.stop` and `targets = [round(t.price, 2) for t in tf.targets]`
3. Replace the manual signal dict with `make_signal_from_frame()` call
4. Keep the `features_snapshot` line after the call

**Example migration for `mtf_alignment.py` (lines 74-118):**

Before:
```python
        tf = frame_trade(signal_type, direction, entry, features, atr)
        if not tf.viable:
            return no_signal()
        stop = tf.stop
        targets = [round(t.price, 2) for t in tf.targets]
        # ... confidence computation ...
        signal = {
            "signal_type": signal_type,
            "direction": direction,
            "entry_price": round(entry, 2),  # BUG
            "stop_loss": round(stop, 2),
            "targets": targets,
            "confidence": confidence,
            "regime_context": regime_ctx,
            "supporting_factors": supporting,
        }
        signal["features_snapshot"] = capture_signal_features(...)
        return signal
```

After:
```python
        tf = frame_trade(signal_type, direction, entry, features, atr)
        if not tf.viable:
            return no_signal()
        # ... confidence computation unchanged ...
        signal = make_signal_from_frame(
            tf,
            symbol=frames.get("symbol", ""),
            timeframe=features.get("timeframe", ""),
            timestamp=features.get("timestamp", ""),
            signal_type=signal_type,
            setup_plugin=self.name,
            direction=direction,
            confidence=confidence,
            regime_context=regime_ctx,
            confluence_score=features.get("ctf_score", 0.0),
            supporting_factors=supporting,
            invalidation_conditions=[f"ctf_score_below_{self.ctf_score_threshold}"],
        )
        signal["features_snapshot"] = capture_signal_features(
            features, direction, "trend", signal["confidence"]
        )
        return signal
```

**Each plugin's specific differences:**
- `confluence_score` varies — some use 0.0, others compute it
- `invalidation_conditions` varies — some have specific conditions
- Extra fields after signal dict (e.g., `dual_divergence`, `div_weighted_score`) must be added back after the `make_signal_from_frame()` call

- [ ] **Step 1: Migrate all 6 plugins in batch 1**

- [ ] **Step 2: Run tests**

Run: `.venv/bin/pytest tests/unit/ -v --timeout=60`
Expected: All tests pass

- [ ] **Step 3: Commit**

```bash
git add src/intelligence/trading/fvg_fill.py src/intelligence/trading/trend_following.py src/intelligence/trading/mtf_alignment.py src/intelligence/trading/mean_reversion.py src/intelligence/trading/choch_reversal.py src/intelligence/trading/anchored_vwap_reversion.py
git commit -m "fix(079-04): migrate batch 1 plugins to make_signal_from_frame"
```

---

## Task 5: Migrate I7 plugins (batch 2)

**Files:**
- Modify: `src/intelligence/trading/poc_rejection.py`
- Modify: `src/intelligence/trading/hvn_rejection.py`
- Modify: `src/intelligence/trading/candlestick_pattern_setup.py`
- Modify: `src/intelligence/trading/cvd_divergence.py`
- Modify: `src/intelligence/trading/momentum_breakout.py`
- Modify: `src/intelligence/trading/cross_asset_divergence.py`

Same migration pattern as Task 4.

- [ ] **Step 1: Migrate all 6 plugins**

- [ ] **Step 2: Run tests**

Run: `.venv/bin/pytest tests/unit/ -v --timeout=60`

- [ ] **Step 3: Commit**

```bash
git add src/intelligence/trading/poc_rejection.py src/intelligence/trading/hvn_rejection.py src/intelligence/trading/candlestick_pattern_setup.py src/intelligence/trading/cvd_divergence.py src/intelligence/trading/momentum_breakout.py src/intelligence/trading/cross_asset_divergence.py
git commit -m "fix(079-05): migrate batch 2 plugins to make_signal_from_frame"
```

---

## Task 6: Migrate I7 plugins (batch 3) + microstructure_utils

**Files:**
- Modify: `src/intelligence/trading/delta_exhaustion.py`
- Modify: `src/intelligence/trading/divergence_stack.py`
- Modify: `src/intelligence/trading/vwap_deviation.py`
- Modify: `src/intelligence/trading/liquidity_hunt.py`
- Modify: `src/intelligence/trading/liquidity_sweep_reclaim.py`
- Modify: `src/intelligence/trading/dual_divergence.py`
- Modify: `src/intelligence/trading/microstructure_utils.py`

`microstructure_utils.py` has `detect_spike_signal()` which builds signal dicts. It also uses `round(entry, 2)`. The function needs to accept a `TradeFrame` and delegate to `make_signal_from_frame()`, or the callers (cvd_spike.py, ofi_spike.py) should be modified to call `make_signal_from_frame()` directly. Check which is cleaner.

`divergence_stack.py` adds many extra fields (`div_weighted_score`, `rsi_div_score`, etc.). These must be added back to the signal dict after the `make_signal_from_frame()` call.

- [ ] **Step 1: Migrate all 7 files**

- [ ] **Step 2: Run tests**

Run: `.venv/bin/pytest tests/unit/ -v --timeout=60`

- [ ] **Step 3: Commit**

```bash
git add src/intelligence/trading/delta_exhaustion.py src/intelligence/trading/divergence_stack.py src/intelligence/trading/vwap_deviation.py src/intelligence/trading/liquidity_hunt.py src/intelligence/trading/liquidity_sweep_reclaim.py src/intelligence/trading/dual_divergence.py src/intelligence/trading/microstructure_utils.py
git commit -m "fix(079-06): migrate batch 3 plugins + microstructure_utils to make_signal_from_frame"
```

---

## Task 7: Migrate remaining I7 plugins (batch 4)

**Files:**
- Modify: `src/intelligence/trading/gap_analysis_setup.py`
- Modify: `src/intelligence/trading/orb_setup.py` (if it uses frame_trade)
- Modify: `src/intelligence/trading/session_extremes_setup.py`
- Modify: `src/intelligence/trading/failed_breakout.py`
- Modify: `src/intelligence/trading/second_leg_continuation.py`
- Modify: `src/intelligence/trading/supply_demand_setup.py`
- Modify: `src/intelligence/trading/vcp_setup.py`
- Modify: `src/intelligence/trading/lvn_breakout.py`
- Modify: `src/intelligence/trading/squeeze_expansion.py`
- Modify: `src/intelligence/trading/cvd_spike.py`
- Modify: `src/intelligence/trading/ofi_spike.py`

Note: Some of these may already set `entry_type` manually (gap_analysis, session_extremes). With `make_signal_from_frame()`, the entry_type comes from `tf.entry_type` automatically — verify these match.

- [ ] **Step 1: Audit and migrate all remaining plugins**

- [ ] **Step 2: Run full test suite**

Run: `.venv/bin/pytest tests/unit/ -v --timeout=60`
Expected: All tests pass

- [ ] **Step 3: Commit**

```bash
git add src/intelligence/trading/
git commit -m "fix(079-07): migrate remaining I7 plugins to make_signal_from_frame"
```

---

## Task 8: Prometheus signal quality metrics

**Files:**
- Modify: `src/observability/metrics.py`
- Modify: `src/intelligence/trading/lifecycle_tracker.py`

- [ ] **Step 1: Add metrics to `metrics.py`**

Add after the existing `REGIME_GATE_SUPPRESSIONS_TOTAL` section:

```python
# ---------------------------------------------------------------------------
# Signal quality metrics (Phase 79)
# ---------------------------------------------------------------------------

SIGNAL_OUTCOME_TOTAL = OTelCounter(
    "signal_outcome_total",
    "Signal outcomes by plugin and result",
    labelnames=["setup_plugin", "outcome"],
)

SIGNAL_ACTIVATION_RATE = OTelGauge(
    "signal_activation_rate",
    "Activation rate per plugin (rolling 1h)",
    labelnames=["setup_plugin"],
)

SIGNAL_HIT_RATE = OTelGauge(
    "signal_hit_rate",
    "Target hit rate per plugin (rolling 1h)",
    labelnames=["setup_plugin"],
)
```

- [ ] **Step 2: Wire metrics in `lifecycle_tracker.py`**

At the top of `lifecycle_tracker.py`, add import:
```python
from src.observability.metrics import SIGNAL_OUTCOME_TOTAL
```

In `evaluate_signal()`, after every `return Transition(...)` that includes an `outcome`, add:
```python
    SIGNAL_OUTCOME_TOTAL.labels(
        setup_plugin=signal.get("setup_plugin", "unknown"),
        outcome=outcome.value,
    ).inc()
```

This requires threading the outcome recording through each return path in `evaluate_signal()`. Add a helper function to avoid duplication:

```python
def _record_outcome(signal: dict, outcome: "SignalOutcome") -> None:
    SIGNAL_OUTCOME_TOTAL.labels(
        setup_plugin=signal.get("setup_plugin", "unknown"),
        outcome=outcome.value,
    ).inc()
```

Call `_record_outcome(signal, outcome)` before each `return Transition(...)` in `evaluate_signal()`.

- [ ] **Step 3: Run tests**

Run: `.venv/bin/pytest tests/unit/ -v --timeout=60`

- [ ] **Step 4: Commit**

```bash
git add src/observability/metrics.py src/intelligence/trading/lifecycle_tracker.py
git commit -m "feat(079-08): add Prometheus signal quality metrics + lifecycle wiring"
```

---

## Task 9: Co-fire tracking in aggregator

**Files:**
- Modify: `src/intelligence/intelligence_pipeline_agent.py`

- [ ] **Step 1: Add co-fire detection after `_build_all_ranked()`**

Find the method that produces `all_ranked` (likely `_build_all_ranked()` or `_aggregate_signals()`). After it returns, add co-fire detection:

```python
def _tag_co_fires(all_ranked: list[dict]) -> None:
    """Tag signals that fire on the same bar with identical entry/stop/targets."""
    from collections import defaultdict
    groups = defaultdict(list)
    for sig in all_ranked:
        if sig.get("regime_eligible", True):
            key = (
                sig.get("symbol", ""),
                sig.get("feature_ts"),
                sig.get("feature_tf", ""),
                round(sig.get("entry_price", 0.0), 4),
                round(sig.get("stop_loss", 0.0), 4),
                tuple(round(t, 4) for t in (sig.get("targets") or [])),
            )
            groups[key].append(sig)
    for group in groups.values():
        if len(group) > 1:
            partners = [s.get("setup_plugin", "") for s in group]
            for sig in group:
                sig["co_fire_count"] = len(group)
                others = [p for p in partners if p != sig.get("setup_plugin", "")]
                sig["co_fire_partners"] = others
```

Call `_tag_co_fires(all_ranked)` after `all_ranked` is built and before publishing.

- [ ] **Step 2: Run tests**

Run: `.venv/bin/pytest tests/unit/ -v --timeout=60`

- [ ] **Step 3: Commit**

```bash
git add src/intelligence/intelligence_pipeline_agent.py
git commit -m "feat(079-09): add co-fire tracking in signal aggregator"
```

---

## Task 10: Run migration + lint + full verification

**Files:**
- None (operational)

- [ ] **Step 1: Apply DB migration**

Run: `docker exec timescaledb psql -U postgres -d indicagent -f /path/to/079_signal_quality_zones.sql`

Or copy the SQL and run inline:
```bash
docker exec timescaledb psql -U postgres -d indicagent -c "
ALTER TABLE signal_ledger ADD COLUMN IF NOT EXISTS signal_schema_version text DEFAULT 'v0';
ALTER TABLE signal_ledger ADD COLUMN IF NOT EXISTS entry_type text DEFAULT 'at_close';
ALTER TABLE signal_ledger ADD COLUMN IF NOT EXISTS co_fire_count int DEFAULT 1;
ALTER TABLE signal_ledger ADD COLUMN IF NOT EXISTS co_fire_partners text[] DEFAULT '{}';
CREATE INDEX IF NOT EXISTS idx_ledger_schema_version ON signal_ledger (signal_schema_version) WHERE signal_schema_version = 'v1';
"
```

- [ ] **Step 2: Run lint + format**

Run: `.venv/bin/ruff check . --fix && .venv/bin/black .`

- [ ] **Step 3: Run full test suite**

Run: `.venv/bin/pytest tests/unit/ -v --timeout=60`
Expected: All tests pass, 3395+

- [ ] **Step 4: Restart pipeline service**

Run: `sudo systemctl restart indicagent-intelligence-pipeline indicagent-signal-writer`

- [ ] **Step 5: Verify new signals have zones (live check after market open)**

```bash
docker exec timescaledb psql -U postgres -d indicagent -c "SELECT signal_schema_version, entry_zone_low, entry_zone_high, entry_type FROM signal_ledger WHERE signal_schema_version = 'v1' LIMIT 5;"
```

Expected: Non-NULL zone values, entry_type populated, schema_version = 'v1'

- [ ] **Step 6: Commit any lint/format fixes**

```bash
git add -A && git commit -m "chore(079-10): lint, format, migration applied"
```

---

## Task 12: Historical replay validation script (optional, post-deploy)

**Files:**
- Create: `scripts/replay_signal_validation.py`

- [ ] **Step 1: Create replay script**

A standalone async script that:
1. Loads last 7 days of `market_data_ohlcv` from TimescaleDB
2. Runs I7 pipeline on each bar (using fixed code)
3. Counts signals fired, activation count, target hits, PnL distribution
4. Queries historical `signal_ledger` for same period (v0 signals)
5. Prints comparison table: activation rate v0 vs v1, hit rate, per-plugin breakdown
6. Runs chi-squared test on activation counts

This script validates the fix against historical data without waiting for live trading.

- [ ] **Step 2: Commit**

```bash
git add scripts/replay_signal_validation.py
git commit -m "feat(079-12): add historical replay validation script"
```

---

## Task 11: Update CLAUDE.md with Phase 79 notes

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Add Phase 79 notes to relevant sections**

In the **signal_ledger** section, add:
- `signal_schema_version` column: `'v0'` = pre-fix (zero-width zones, potentially wrong entry_price), `'v1'` = post-fix. ML training queries MUST filter `WHERE signal_schema_version = 'v1'`.
- `entry_type` column: populated by `make_signal_from_frame()`. Values: `at_close`, `at_pullback`, `at_limit`, `at_reclaim`, `zone_proximal`.
- `co_fire_count`/`co_fire_partners`: co-firing signal metadata. Count > 1 means multiple plugins fired with identical entry/stop/target levels.

In the **Plugin System** section, add:
- **I7 signal construction**: All I7 plugins MUST use `make_signal_from_frame()` from `signal_schema.py`. Never build signal dicts manually — manual construction skips zone propagation and may use wrong entry_price. The helper auto-extracts all TradeFrame fields.

- [ ] **Step 2: Commit**

```bash
git add CLAUDE.md
git commit -m "docs(079-11): update CLAUDE.md with Phase 79 signal quality notes"
```
