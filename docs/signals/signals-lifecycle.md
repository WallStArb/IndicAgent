# Signals Lifecycle — State machine, transitions, and outcome classification

**Version:** 2.8.0 | **Status:** stale (v2.x, see banner) | **Last Updated:** 2026-06-05

---

> **Staleness note (2026-08-01):** This doc describes the `SignalTracker`/`LifecycleWriter`
> state machine and `signal_outcomes`/`signal_ledger` outcome taxonomy — the ARCHIVED v2.x
> signal lifecycle, with no live consumer as of 2026-07-02 per CLAUDE.md. Not yet rewritten for
> v3.0 -- tracked for a future doc pass, not fixed here.

## Purpose

This document covers the full lifecycle of a signal from I7 emission to final outcome. A signal is not a point-in-time event — it is a lifecycle. Understanding the state machine, activation conditions, exit triggers, and outcome taxonomy is required before debugging or modifying any lifecycle service.

**Who reads this doc:** Engineers debugging why a signal did or did not activate, building new exit conditions, or understanding what each outcome label means in the ML training dataset.

---

## Design Principles

### Compute/writer split

The lifecycle pipeline follows the DB-ignorant compute pattern:

- **`SignalTracker`** — pure compute. Reads bar data from Kafka. Maintains all active signal state in memory. Calls `evaluate_signal()` for every bar. Never writes to DB. Publishes `LifecycleTransition` events to the `lifecycle.transitions` Kafka topic.
- **`LifecycleWriter`** — pure persistence. Consumes `lifecycle.transitions`. Batch-writes all state changes to `signal_outcomes` in `signal_ledger`. Deduplicates via `WHERE exit_at IS NULL` guards on exit writes.

This split exists because DB writes are I/O-bound and cannot sit in the hot bar-processing loop.

### Two-path safety contract

Every signal has two potential resolution paths:

1. **Live tracker** — `SignalTracker` processes bars in real time and resolves most signals as they happen.
2. **Replay auditor** — `SignalReplayAuditor` runs every 5 minutes, finds signals whose `expires_at` has elapsed and `exit_at IS NULL`, and replays them bar-by-bar against `market_data_ohlcv` using the same `evaluate_signal()` logic.

Both paths publish `LifecycleTransition(type=EXIT)` events. `LifecycleWriter` uses `WHERE exit_at IS NULL` on all exit writes — the second writer is always a safe no-op. First writer wins.

### Temporal guard (D-01)

A signal can never activate on a bar from before the signal was fired. `_check_zone_activation()` in `lifecycle_tracker.py` enforces `bar_time >= signal_timestamp`. This prevents stale bars from spuriously activating newly-ingested signals.

---

## Signal State Machine

```
                  I7 fires
                      |
                      v
              status = 'pending'
                      |
        bar_time >= signal_timestamp
        price overlaps entry zone
                      |
                      v
              status = 'active'
                 activated_at set
                      |
             (per-bar evaluation)
            /           |          \
     stop hit      target hit    TTL/staleness
           \           |          /
            v          v         v
              status = 'expired'
              exit_at, outcome set
```

`regime_suppressed` is a separate path:

```
Signal fails regime gate (set by signal_processor.py at emission)
          |
          v
status = 'regime_suppressed'  (seeded into signal_outcomes at INSERT time, never transitions)
  -- shadow lifecycle tracking proceeds:
  -- shadow_mae, shadow_mfe, shadow_outcome recorded in signal_outcomes
  -- written via TransitionType.SHADOW_OUTCOME event to lifecycle.transitions
  -- status stays 'regime_suppressed' throughout (counterfactual data only)
  -- never enters the zone-track activation path
```

Note: `regime_suppressed` is stamped at signal emission, not via a lifecycle transition. The `SHADOW_OUTCOME` transition type carries the post-tracking counterfactual outcome fields (`shadow_mae`, `shadow_mfe`, `shadow_outcome`) and is consumed by `LifecycleWriter` which writes them to `signal_outcomes` without changing `status`.

Status values are **raw strings**: `"pending"`, `"active"`, `"regime_suppressed"`, `"expired"`. No enum in the database — `SignalStatus(str, Enum)` in `signal_ledger_repository.py` extends `str` for zero-migration compatibility.

### State semantics

| Status | Meaning |
|--------|---------|
| `"pending"` | Signal fired; waiting for price to enter the entry zone. May expire via TTL without ever activating. |
| `"active"` | Price entered the entry zone; trade is being tracked. |
| `"regime_suppressed"` | Signal fired but the I7 aggregator's regime gate rejected it. Tracked as a shadow counterfactual — `status` stays `"regime_suppressed"` forever. The outcome is recorded for gate calibration. |
| `"expired"` | Trade exited via stop loss, target hit, TTL expiry, chandelier stop, or condition expiry. Terminal — no further transitions. |

---

## Signal Origin: Fields Written at Emission

When `SignalWriter` inserts a signal into `signal_ledger`, these fields are populated:

| Field | Value at emission |
|-------|------------------|
| `status` | `'pending'` (seeded in `signal_outcomes`) |
| `timestamp` | Bar timestamp at I7 computation |
| `direction` | `1` (long) or `-1` (short) |
| `entry_price` | Resolved from TradeFramer zone geometry |
| `stop_loss` | Structural stop level |
| `targets` | JSONB list of profit target prices |
| `entry_zone_low` | Lower zone bound. NULL routes to DLQ — signal never tracked |
| `entry_zone_high` | Upper zone bound. NULL routes to DLQ — signal never tracked |
| `ttl_bars` | Default 10 for most timeframes; varies by TF via `TF_TTL_BARS` |
| `expires_at` | `signal_ts + ttl_bars * tf_seconds` — pre-computed at write time |
| `signal_schema_version` | `SIGNAL_SCHEMA_VERSION` constant (currently `'v1'`) |
| `hmm_regime_at_fire` | HMM regime at time of fire — used for staleness scoring |
| `garch_sigma_at_fire` | GARCH sigma at fire — used for staleness scoring |

**NULL at emission (filled progressively):** `activated_at`, `activation_price`, `exit_at`, `exit_price`, `exit_reason`, `outcome`, `pnl_r`, `mae`, `mfe`, `bars_in_trade`.

---

## Activation: Pending to Active

For every pending signal, each new bar checks whether price entered the entry zone:

```python
# lifecycle_tracker._check_zone_activation()
bar_overlaps_zone = low <= zone_high and high >= zone_low

if bar_overlaps_zone and bar_time >= signal_timestamp:  # D-01 temporal guard
    if direction == 1:  # Long
        activation_price = min(high, zone_high)  # First touch of zone_high
        zone_entry_pct = (zone_high - activation_price) / zone_span  # 0=proximal
    else:  # Short
        activation_price = max(low, zone_low)   # First touch of zone_low
        zone_entry_pct = (activation_price - zone_low) / zone_span   # 0=proximal
```

On activation, `LifecycleWriter` writes:
- `status = 'active'`
- `activated_at = bar_time`
- `activation_price` (capped at zone boundary — not necessarily bar.high/low)
- `zone_entry_pct` (0.0 = entered at proximal edge, 1.0 = entered at distal edge)
- `bars_to_activation` (active bars elapsed since signal fire — excludes empty overnight bars)

---

## Tracker Update Loop

`SignalTracker._evaluate_bar()` runs for every bar on every (symbol, timeframe) that has active signals. For each signal:

1. Count active bars (`high != low` — empty overnight gaps excluded).
2. For active signals: compute chandelier trailing stop state and staleness score.
3. Call `evaluate_signal()` — returns `Transition | None`.
4. If `None`: update in-memory MAE/MFE and continue.
5. If transition to `ACTIVE`: update in-memory state, publish `ACTIVATION` event.
6. If transition with `exit_reason`: enrich with `bars_in_trade`, publish `EXIT` event, remove from active index.

The in-memory `SignalState` per signal:
```python
@dataclass
class SignalState:
    mae: float = 0.0           # Maximum adverse excursion (pnl_r units)
    mfe: float = 0.0           # Maximum favorable excursion (pnl_r units)
    market_mae: float = 0.0    # Parallel market-entry track MAE
    market_mfe: float = 0.0    # Parallel market-entry track MFE
    chandelier_state: dict     # Trailing stop state (initialized on first active bar).
                               # Keys: trailing_stop, highest_high, lowest_low, vol, be_floor.
                               # be_floor advances at T1/T2 to clamp the chandelier floor.
    staleness_consecutive: int # Consecutive bars with staleness_score > 0.5
    activated_at: datetime     # For bars_in_trade computation
    active_bars_elapsed: int   # Total active bars since signal fire (TTL countdown)
    bars_since_activation: int # Active bars since activation (bars_in_trade baseline)
```

MAE/MFE are maintained in-memory and written to `signal_outcomes` on exit (not per-bar, to avoid write amplification).

---

## Exit Conditions (Priority Order)

`evaluate_signal()` checks exits in this strict order for active signals:

1. **Stop loss** — `bar.low <= stop_loss` (long) or `bar.high >= stop_loss` (short). Conservative: stop checked before target on the same bar.
2. **Target hits** — checks highest target first for maximum credit. A bar that both touches stop and target is classified as a stop (conservative). **T1 does not exit** — it advances the chandelier floor (see below). Only T2 and T3 produce target-based exits.
3. **Chandelier trailing stop with breakeven floor** — ATR-based trailing stop (3x multiplier, updates each bar to preserve gains). Initialized on first active bar using `garch_sigma_at_fire` (preferred) or `atr_14` (fallback). After T1 is hit, the chandelier stop is clamped so it can never trail below entry price (`be_floor = entry`). After T2 is hit, clamped to never trail below T1 price (`be_floor = target_1`). The clamp applies before the exit check — the chandelier remains the sole exit mechanism; `be_floor` is a floor constraint on its level, not a parallel path. Exit log payload includes `be_floor_active: bool` for analytics.
4. **Staleness condition_expired** — 3 consecutive bars with composite staleness score > 0.5. Staleness = `0.6 * hmm_regime_drift + 0.4 * garch_sigma_ratio`. Fires when the market regime has fundamentally shifted from when the signal fired.
5. **TTL expiry** — `bar_time >= expires_at`. Always last, only after all price-based checks. Uses pre-computed `expires_at` for deterministic replay — never `datetime.now()`.

### Chandelier floor state

`chandelier_state` carries one additional field after the T1/T2 floor design:

```python
"be_floor": float | None  # None → entry_price (after T1) → target_1_price (after T2)
```

Floor advancement runs before the chandelier exit check each bar:
- T1 hit and `be_floor is None` → set `be_floor = entry_price`
- T2 hit and `be_floor is not None` → advance `be_floor = target_1_price`

The clamp in the chandelier exit check:
```python
if be_floor is not None:
    trailing_stop = max(trailing_stop, be_floor)  # long
    trailing_stop = min(trailing_stop, be_floor)  # short
```

`stop_loss` is never modified — it remains the signal's permanent risk anchor. `be_floor` is transient state in `chandelier_state`; it is not persisted to `signal_outcomes`.

### NULL expires_at handling (D-17)

If `expires_at IS NULL` (data integrity bug), the TTL check is skipped and the OTel counter `signal_lifecycle_null_expires_at_total` is incremented. The signal stays in its current state — price-based exits still apply. Do NOT fall back to bar-count TTL.

---

## MAE / MFE / pnl_r / bars_in_trade — What Each Means

These fields are computed per-bar for active signals and written to `signal_outcomes` at exit:

| Field | Units | Meaning |
|-------|-------|---------|
| `pnl_r` | Risk units (R) | Final P&L = `(exit_price - entry_price) * direction / risk`. 1R = 1x the initial stop distance. +1.0 means the trade moved 1 stop-distance in your favor. |
| `mae` | Risk units (R) | Maximum adverse excursion — the worst intrabar close-based drawdown against the trade. Always <= 0 for a profitable trade. Computed as `min(close-based pnl_r across all active bars)`. |
| `mfe` | Risk units (R) | Maximum favorable excursion — the best close-based peak in favor of the trade. Always >= 0. Computed as `max(close-based pnl_r across all active bars)`. |
| `bars_in_trade` | Count | Active bars from activation to exit. Excludes empty overnight gaps (`high == low`). Used to classify stop outcomes (see below). |

MAE and MFE use close-based pnl_r for the cross-bar tracking, but the exit check uses the actual bar high/low to determine if stop or target was hit. This means the final MAE on a stop-loss exit may be slightly less negative than the actual stop pnl_r (the exit uses the stop price, not the bar close).

---

## 8-Class Outcome Taxonomy

Every closed signal receives exactly one outcome:

| Outcome | Trigger | pnl_r sign |
|---------|---------|------------|
| `never_activated` | TTL expired, price never entered the entry zone | 0 |
| `stopped_at_entry` | Hit stop within 2 bars of activation OR `mfe <= 0.05R` — likely entry slippage or false breakout | negative |
| `stopped_in_trade` | Hit stop after trade moved (bar 3+ since activation AND `mfe > 0.05R`) | negative |
| `target_1` | Price reached first target but not second | positive |
| `target_1_2` | Price reached first and second target but not full | positive |
| `target_full` | Price reached all targets | positive |
| `ttl_expired_ahead` | TTL expired while trade was in positive territory (`mfe > 0`) | varies |
| `ttl_expired_behind` | TTL expired while trade was in negative territory | varies |

The stop outcome distinction (`stopped_at_entry` vs `stopped_in_trade`) is resolved by `_classify_stop_outcome(mfe, bars_in_trade)` in `lifecycle_tracker.py`. The raw stop exit only knows a stop was hit — the service layer enriches it with `bars_in_trade` context.

Chandelier stop exits and `condition_expired` exits both resolve to `stopped_in_trade` — they only fire after the trade has been active long enough for the chandelier to build.

**Effect of the chandelier floor on outcomes:** T1 is no longer a terminal exit. A trade that reaches T1 and subsequently exits via chandelier produces `stopped_in_trade` with `pnl_r >= 0` — the floor guarantees the exit price never falls below entry, but `exit_price` is the actual `trailing_stop` value at the moment price breaches it (recorded exactly, not approximated). If the chandelier has risen above entry before price reverses, `pnl_r > 0`; if it exits exactly at the floor, `pnl_r = 0`. The `target_1` outcome label is only reachable if a future change re-introduces a T1-terminal path. Profitable target-hit outcomes now effectively start at `target_1_2` (T2 reached) or `target_full` (all targets reached). Downstream ML training queries should be aware that `outcome = 'target_1'` will not appear in data generated post-deployment of this design.

---

## Fields Written at Each Lifecycle Stage

| Stage | Fields populated |
|-------|-----------------|
| **Emission** | All `signal_ledger` columns, `status='pending'` in `signal_outcomes` |
| **Activation** | `status='active'`, `activated_at`, `activation_price`, `zone_entry_pct`, `bars_to_activation` |
| **Exit** | `status='expired'`, `exit_at`, `exit_price`, `exit_reason`, `outcome`, `pnl_r`, `mae`, `mfe`, `bars_in_trade` |
| **Per-bar (active)** | `mae`/`mfe` updated in memory; written only at exit to minimize DB writes |

---

## LifecycleTransition Types

`src/intelligence/trading/lifecycle_transitions.py` defines the Kafka event schema:

| TransitionType | When published | Data payload |
|---------------|----------------|-------------|
| `ACTIVATION` | Pending → Active | `activated_at`, `activation_price`, `zone_entry_pct`, `bars_to_activation` |
| `EXIT` | Any → Expired | `status`, `exit_at`, `exit_price`, `exit_reason`, `pnl_r`, `mae`, `mfe`, `bars_in_trade`, `outcome` |
| `MAE_MFE_UPDATE` | Active, no transition this bar | `signal_id` (payload is minimal — not currently used for writes) |
| `CHANDELIER_UPDATE` | Active, chandelier state changed | Trailing stop history |
| `SHADOW_OUTCOME` | Shadow signal resolved | `shadow_mae`, `shadow_mfe`, `shadow_outcome` |
| `MARKET_RESOLUTION` | Parallel market-entry track exits | `market_entry_*` fields |

---

## Schema Versioning

| Version | Meaning |
|---------|---------|
| `v0` | Pre-Phase-79. Entry zones were zero-width or had incorrect geometry. Phase 83 migration truncated all v0 data via `TRUNCATE TABLE signal_ledger`. **Exclude from ML training.** |
| `v1` | Current. Proper zone geometry, resolved `entry_price`, correct `entry_zone_low`/`high`, `expires_at` TTL column. |

If a new version is needed:
1. Change `SIGNAL_SCHEMA_VERSION` in `signal_schema.py`.
2. Write a migration for existing rows.
3. Grep for all `signal_schema_version` usages — the replay auditor, metrics compute, and training queries all gate on this.

---

## Signal Generator Warmup

After a service restart, `IntelligencePipeline` needs approximately 50 live 1-minute bars (about 50 minutes) for plugin state to warm up before I7 setups fire. The consumer group is not rewound on restart. No signals will fire during warmup — this is expected behavior, not a bug.

---

## See Also

- `docs/signals/signals-foundation.md` — why signal_ledger exists, full schema reference
- `docs/signals/signals-operations.md` — operating the three lifecycle services, diagnostic queries
- `docs/data/data-streaming.md` — Signal Kafka topics — see Data Streaming
- `src/intelligence/trading/lifecycle_tracker.py` — `evaluate_signal()`, `Transition` dataclass, all exit logic
- `src/intelligence/trading/lifecycle_transitions.py` — `LifecycleTransition`, `TransitionType`
- `services/signal_tracker_compute_agent.py` — live tracker service
- `services/signal_replay_auditor_agent.py` — replay auditor service
- `services/lifecycle_writer_agent.py` — persistence writer
