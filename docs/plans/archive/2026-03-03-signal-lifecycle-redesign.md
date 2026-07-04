# Signal Lifecycle Redesign — Institutional-Grade Outcome Tracking

**Date:** 2026-03-03
**Status:** Shipped — fully implemented
**Shipped:** ~2026-03-10 (migration 015, not 014 — pipeline timing migration inserted first)
**Author:** Design session with user

**Implementation notes (diverged from design):**
- Migration landed as `015_signal_lifecycle_fields.sql` (not 014)
- `shadow_mae`, `shadow_mfe`, `shadow_outcome` added post-design with shadow mode work
- `LedgerEntry` grew to 54 fields at time of shipping (not 42) — continued additions in subsequent phases; Phase 35 will extend to 58
- `signal_tracker_service` retired as planned; `indicagent-signal-lifecycle` running at :9115

---

## Problem

The current signal tracking system has several accuracy gaps that prevent using signal outcomes for ML training or institutional-quality analysis:

1. **Timestamp imprecision** — `timestamp` is the bar close time (e.g., 14:35:00). The signal is actually *determined* ~2 minutes later (e.g., 14:37:15) after the pipeline processes the bar. The market has moved.
2. **No live quote capture** — `entry_price` is the plugin's structural level (e.g., demand zone at 448.50). The actual offer/bid at determination time is never recorded.
3. **No entry zones** — Activation checks `price >= entry_price` (single point touch). Real entries happen within a zone (proximal edge to distal edge). Zone quality is not tracked.
4. **TTL is silently broken** — `bars_elapsed` defaults to 0 every bar (never persisted). Signals never expire via TTL.
5. **No MAE/MFE** — Maximum Adverse/Favorable Excursion are the foundational stop/target calibration metrics. Not tracked.
6. **No categorical outcome** — Only continuous `pnl_r`. No ML-ready classification of how the signal resolved.
7. **`signal_tracker_service`** retires in favor of a richer `signal_lifecycle_service`.

---

## Infrastructure Discovery

**`price:{symbol}:latest`** — already maintained by `AsyncTickPublisher` (`src/core/async_tick_publisher.py:110-120`) with fields `{bid, ask, price, timestamp}` and a 120s TTL. No new data collection needed — just one `hgetall` call at signal determination time.

---

## Design

### New DB Fields — Migration 014

**At signal fire time** (written by `signal_generator_service`):

| Column | Type | Notes |
|--------|------|-------|
| `determined_at` | TIMESTAMPTZ | App-layer wall-clock timestamp — not DB NOW() |
| `ask_at_signal` | FLOAT | Live ask at determination |
| `bid_at_signal` | FLOAT | Live bid at determination |
| `market_price_at_signal` | FLOAT | Relevant side: ask for long, bid for short |
| `entry_zone_low` | FLOAT | Plugin-defined lower bound of entry zone |
| `entry_zone_high` | FLOAT | Plugin-defined upper bound of entry zone |
| `zone_valid_at_signal` | BOOLEAN | Market price still reachable at determination time |

**At activation** (written by `signal_lifecycle_service`):

| Column | Type | Notes |
|--------|------|-------|
| `activation_price` | FLOAT | Actual price when signal activated (where in zone) |
| `zone_entry_pct` | FLOAT | 0.0 = proximal (ideal), 1.0 = distal (risky) |
| `bars_to_activation` | INT | Bars from signal fire to activation |

**During trade** (updated per bar):

| Column | Type | Notes |
|--------|------|-------|
| `mae` | FLOAT | Max Adverse Excursion — worst pnl_r seen during trade |
| `mfe` | FLOAT | Max Favorable Excursion — best pnl_r seen during trade |

**At exit** (written by `signal_lifecycle_service`):

| Column | Type | Notes |
|--------|------|-------|
| `bars_in_trade` | INT | Bars from activation to exit |
| `outcome` | TEXT | 8-class categorical (see below) |

### 8-Class Outcome Taxonomy

| Outcome | Meaning |
|---------|---------|
| `never_activated` | Signal expired without price ever entering zone |
| `stopped_at_entry` | Activated then stopped within 1–2 bars (false entry) |
| `stopped_in_trade` | Activated, moved in favor, then reversed and stopped |
| `target_1` | Hit first target only |
| `target_1_2` | Hit targets 1 and 2 |
| `target_full` | All targets hit |
| `ttl_expired_ahead` | TTL expired while trade was profitable (MFE > 0) |
| `ttl_expired_behind` | TTL expired while trade was losing (MFE <= 0) |

### I7 Plugin Interface Addition

Each I7 plugin output dict gains two optional keys:

```python
{
    "entry_zone_low": float,   # lower bound of entry zone
    "entry_zone_high": float,  # upper bound of entry zone
    # ... existing fields
}
```

**Default (in `trade_framer.py`):** If plugin does not set zone bounds, fallback to `entry_price ± 1×ATR`. This prevents any plugin from breaking.

Most plugins already compute the relevant data:
- `FVGFill` → FVG high/low
- `SupplyDemandSetup` → demand_zone_proximal / demand_zone_distal
- `CHoCHReversal` → order block bounds
- Others → ATR-based fallback

### Component Changes

#### `signal_generator_service.py`
- Before DB insert: `hgetall(f"{env_prefix}price:{symbol}:latest")` → get live bid/ask
- Set `determined_at = datetime.now(UTC)` (app-layer)
- Compute `market_price_at_signal` = ask (long) or bid (short)
- Compute `zone_valid_at_signal`: for long, `market_price_at_signal <= entry_zone_high`; for short, `market_price_at_signal >= entry_zone_low`
- Extract `entry_zone_low` / `entry_zone_high` from plugin output (with ATR fallback)

#### `src/intelligence/trading/lifecycle_tracker.py`
- Extended `Transition` dataclass: add `mae`, `mfe`, `activation_price`, `zone_entry_pct`, `bars_to_activation`, `bars_in_trade`, `outcome`
- Zone-aware activation: bar range overlaps zone (`low <= entry_zone_high AND high >= entry_zone_low`)
- `bars_elapsed` computed from timestamps: `(current_bar_time - signal_timestamp) / tf_seconds` — **fixes TTL bug**
- MAE/MFE tracked per evaluation call (caller passes current mae/mfe, function returns updated values)
- 8-class outcome determined at exit based on `exit_reason`, `bars_in_trade`, `mfe`

#### `src/intelligence/trading/signal_ledger.py`
- `LedgerEntry` dataclass: add all 14 new fields (all nullable for backward compat)
- Updated `_INSERT_SQL`: 28 → 42 params
- New `update_signal_excursions(db, signal_id, mae, mfe)` — lightweight per-bar UPDATE
- Updated `_UPDATE_STATUS_SQL`: add `activation_price`, `zone_entry_pct`, `bars_to_activation`, `bars_in_trade`, `outcome`

#### `services/signal_lifecycle_service.py` (new — replaces `signal_tracker_service.py`)
- Subscribes to `market:SYMBOL:1m` streams (same pattern as signal_tracker)
- Consumer group: `"signal_lifecycle"` (new — old group `"signal_tracker"` will age out)
- Per bar: evaluate all pending/active signals
  - Pending: zone-aware activation check
  - Active: MAE/MFE update + stop/target/TTL exit check
- On activation: write `activation_price`, `zone_entry_pct`, `bars_to_activation`
- On exit: write full exit fields + `outcome`
- Metrics port: 9115

#### Systemd
- New: `indicagent-signal-lifecycle.service`
- Retired: `indicagent-signal-tracker.service` (stop + disable)

---

## Files to Create/Modify

| File | Action |
|------|--------|
| `production/migrations/014_signal_lifecycle_fields.sql` | CREATE — 14 new columns |
| `services/signal_lifecycle_service.py` | CREATE — new service |
| `src/intelligence/trading/lifecycle_tracker.py` | MODIFY — zone-aware, MAE/MFE, 8-class outcome |
| `src/intelligence/trading/signal_ledger.py` | MODIFY — new fields, new SQL |
| `services/signal_generator_service.py` | MODIFY — bid/ask capture, zone fields, determined_at |
| `src/core/stream_keys.py` | MODIFY — add `quote_latest(prefix, symbol)` helper |
| `src/intelligence/trading/setup_plugins/*.py` | MODIFY — 15 plugins add zone bounds |
| `src/intelligence/trading/trade_framer.py` | MODIFY — ATR fallback for zone bounds |
| `production/system/indicagent-signal-lifecycle.service` | CREATE — systemd unit |
| `tests/unit/intelligence/trading/test_lifecycle_tracker.py` | MODIFY — new test cases |
| `tests/unit/intelligence/trading/test_signal_ledger.py` | MODIFY — new field coverage |

---

## Key Reuse

- `src/core/async_tick_publisher.py:110` — `price:{symbol}:latest` hash pattern (read from this in generator)
- `src/core/stream_keys.py` — all stream key construction (add `quote_latest` helper)
- `src/core/stream_utils.py:ensure_consumer_group_with_reset` — consumer group setup
- `src/core/database_manager.py` — `execute_command`, `execute_batch`, `execute_query`
- Existing `evaluate_signal()` pure function pattern — extend, don't replace
- Systemd service template from any existing `production/system/*.service` file

---

## Verification

```bash
# 1. Run migration
psql $DATABASE_URL -f production/migrations/014_signal_lifecycle_fields.sql

# 2. Unit tests
.venv/bin/pytest tests/unit/intelligence/trading/ -v

# 3. Start lifecycle service (after stopping signal_tracker)
sudo systemctl stop indicagent-signal-tracker
.venv/bin/python services/signal_lifecycle_service.py

# 4. Verify new fields populated
psql $DATABASE_URL -c "
  SELECT signal_id, determined_at, ask_at_signal, entry_zone_low, entry_zone_high,
         zone_valid_at_signal, mae, mfe, outcome
  FROM signal_ledger ORDER BY created_at DESC LIMIT 5;
"

# 5. Check MAE/MFE updating on active signals
psql $DATABASE_URL -c "
  SELECT signal_id, status, mae, mfe, bars_to_activation
  FROM signal_ledger WHERE status = 'active' LIMIT 10;
"

# 6. Full test suite
.venv/bin/pytest tests/unit/ -v
.venv/bin/ruff check .
```
