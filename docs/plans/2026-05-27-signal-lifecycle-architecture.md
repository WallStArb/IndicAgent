# Signal Lifecycle Architecture Fix

**Version:** 1.0
**Last Updated:** 2026-05-27
**Date:** 2026-05-27
**Status:** Research complete, implementation pending
**Context:** Emerged from AI swarm performance analysis — 96% of signals were permanently pending, masking real performance data.

---

## What We Found

### The Band-Aid (shipped, commit e4615a3e)

Fixed two bugs in `signal_replay_auditor_agent.py`:
1. LATERAL JOIN to `intelligence_features` crashed on NULL `stop_loss` — fixed by reading `stop_loss`/`targets` from `signal_ledger_full` directly
2. PENDING signals that never activated were never expired — fixed by synthesizing `never_activated` exit when `_evaluate_zone_track` returns None for a PENDING signal

This cleared the 914k backlog. But it's a band-aid. The replay auditor should process near-zero signals in steady state. If it's doing bulk work, something upstream is broken.

---

## Root Causes (Three Design Flaws)

### 1. Incomplete signal records — entry_zone_low/high are NULL

`signal_ledger.entry_zone_low` and `signal_ledger.entry_zone_high` are NULL for all 958k signals. These values exist only in `intelligence_features.trading_signals` JSONB (the `zone_low`/`zone_high` fields per signal entry).

**Impact:** A signal's lifecycle cannot be evaluated from its own record. The replay auditor needs a fragile LATERAL JOIN to reconstruct what the signal said. Any future system that needs to evaluate signals (ML training, backtesting, audit) has the same dependency.

**File where zone fields must be emitted:** wherever `make_signal()` or `make_signal_from_frame()` is called in I7 plugins — `src/intelligence/trading/signal_schema.py` constructs the signal dict; zone values come from `frame_trade()` return in `src/intelligence/trading/trade_framer.py` (fields: `TradeFrame.zone_low`, `TradeFrame.zone_high`).

**Fix:** Write `entry_zone_low`/`entry_zone_high` into `signal_ledger` at signal creation. The `signal_writer_service` or wherever signals are persisted must include these fields. Then the LATERAL JOIN in the replay auditor can be removed entirely.

### 2. TTL ambiguity — bar-count vs wall-clock

Two TTL models coexist and produce different outcomes for the same signal:

| Code path | Model | Implementation |
|-----------|-------|----------------|
| `lifecycle_tracker.py` | Bar-count | `bars_elapsed >= ttl_bars` (active bars only, excludes gaps) |
| `_replay_signal` | Wall-clock | `elapsed = (now - signal_ts).total_seconds()` |
| `_ingest_signal` backfill fast-path | Wall-clock | `bars_elapsed = int(elapsed / tf_secs)` |

Non-deterministic: the same signal evaluated at the same wall-clock time produces different outcomes depending on code path. This corrupts performance attribution.

**Fix:** Choose one model. Recommendation: wall-clock, stored as `expires_at = timestamp + ttl_bars * tf_seconds` in `signal_ledger` at emission. Any evaluator checks `bar_ts >= expires_at`. Simpler, cheaper, unambiguous.

**Downstream check needed:** Does `ttl_bars` as a bar-count appear in any ML features or graduation logic? If so, those consumers need migration too.

### 3. Live tracker has ephemeral state — root cause of the backlog

`signal_tracker_compute_agent` holds pending signals in memory. On restart (systemd, crash, deploy), it reloads from DB via `_load_pending_signals()`. But those signals' bar windows have passed — Kafka has discarded those bars (minimal retention). The tracker holds them in memory waiting for bars that never come.

The `_ingest_signal` backfill fast-path exists (`_publish_ttl_expired_transition_sync`) but only fires when `canonical["is_backfill"] == True`. Real-time signals loaded at startup after a restart get no fast-path and accumulate indefinitely.

**Fix:** Remove the `is_backfill` guard. Any signal loaded at startup where `elapsed >= ttl_bars * tf_secs` should immediately fire `_publish_ttl_expired_transition_sync`. One conditional change in `_ingest_signal`.

```python
# Current (wrong):
if canonical["is_backfill"] and bars_elapsed >= canonical["ttl_bars"]:
    self._publish_ttl_expired_transition_sync(canonical, bars_elapsed)

# Fixed:
if bars_elapsed >= canonical["ttl_bars"]:
    self._publish_ttl_expired_transition_sync(canonical, bars_elapsed)
```

---

## The Four Fixes (Priority Order)

| # | Fix | File(s) | Risk | Impact |
|---|-----|---------|------|--------|
| 1 | Remove `is_backfill` guard from startup fast-path | `services/signal_tracker_compute_agent.py` | Low — one conditional | Eliminates backlog accumulation on restart |
| 2 | Emit `entry_zone_low/high` at signal creation | `signal_writer_service` + `signal_ledger` schema | Medium — migration + writer change | Makes signal records self-contained |
| 3 | Store `expires_at` in `signal_ledger`, unify TTL model | `signal_ledger` migration + `lifecycle_tracker.py` + `signal_tracker_compute_agent.py` | Medium — touches evaluation logic | Deterministic lifecycle, removes dual model |
| 4 | Demote replay auditor to true canary | `signal_replay_auditor_agent.py` | Low — remove LATERAL JOIN after fix 2 | Simplifies service, reduces compute |

---

## Design Principles (Renaissance framing)

1. **Self-contained signal records.** Every field needed to evaluate a signal's lifecycle lives in the signal row. No external lookups, no JSONB reconstruction.

2. **One evaluation function, two call sites.** `evaluate(signal_record, bars) → outcome` in `lifecycle_tracker.py` is the single implementation. Live tracker and replay auditor call the same function with the same inputs. Currently subtly different — must unify.

3. **Deterministic outcomes.** Same signal + same bars = same outcome, regardless of when or which service does the evaluation. Requires unifying TTL model.

4. **No compensating services doing bulk work.** The replay auditor in steady state should process near-zero signals. If its gauge is non-zero for >5 minutes, that's an alert, not normal operation.

5. **Stateless evaluation.** Lifecycle outcome is derivable from signal record + market_data_ohlcv at any time. No dependency on in-memory tracker state.

---

## Current State (post band-aid)

- Replay auditor: running, processing ~130 signals/cycle (steady-state backlog), zero errors
- `_BATCH_SIZE` = 2000, `REPLAY_INTERVAL_SECONDS` = 30 (temporary — can revert once live tracker fix is in)
- 914k historical signals resolved as `never_activated` (some mislabeled — were ACTIVE signals with bar gaps, but acceptable for triage)
- New signals resolving correctly going forward

---

## Open Questions for GSD Discuss Phase

1. Does any ML feature use `ttl_bars` as a bar-count input? If yes, switching to wall-clock `expires_at` needs those consumers updated.
2. Where exactly does `signal_writer_service` persist `entry_zone_low/high`? Is it the signal_schema dict fields already named that way, or are they named `zone_low`/`zone_high` in the TradeFrame and renamed somewhere?
3. Should we backfill `entry_zone_low/high` for the 958k historical signals from `intelligence_features` JSONB, or accept NULLs for the historical set?
4. What's the safest rollout order so the live tracker doesn't see partial state during the migration?
