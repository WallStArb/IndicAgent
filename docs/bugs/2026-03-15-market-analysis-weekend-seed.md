# Bug: market_analysis_service active_symbols=0 on weekends after restart

**Status:** Root cause confirmed. Workaround known. Permanent fix not yet implemented.
**Severity:** High — dashboard shows no intelligence data on weekends after any service restart.
**Affected service:** `services/market_analysis_service.py`

---

## Symptom

After restarting `indicagent-market-analysis` on a weekend, the service logs show `active_symbols: 0` continuously. The dashboard shows `-` for all non-crypto instruments. Only ~43 intelligence events publish on startup (from `intelligence_features` DB seed), and no new ones arrive.

---

## Root Cause (confirmed)

Two compounding issues:

### 1. Stale consumer offset (`line 733`)

```python
self._kafka_consumer = KafkaConsumerClient(
    topic_indicators(self.env_name),
    group_id="market_analysis",
    auto_offset_reset="latest",   # ← the problem
)
```

`group_id="market_analysis"` is persistent — Redpanda remembers the committed offset across restarts. When `indicator_service` publishes 249 seeded I1 events on startup, those messages land *before* `market_analysis_service`'s committed offset. `auto_offset_reset="latest"` means it will never replay them. On weekdays, live IBKR bars arrive constantly so this is masked. On weekends, no live bars → nothing new → `active_symbols: 0` forever.

### 2. Fallback seed has no I1 data (`_fallback_one`, line 615)

`_fallback_one()` seeds `bar_history` from `market_data_ohlcv` (OHLCV bars only). But computing I2-I6 requires `i1_features` from an I1 event (line 331):

```python
frames["features"] = dict(i1_features)  # must come from indicator_service
```

So even after the fallback seed, symbols have bars in memory but cannot compute intelligence. The service is stuck waiting for I1 events that will never arrive.

---

## Workaround (immediate, no code change)

Restart `indicator_service`. It re-publishes 249 fresh seeded I1 events as **new** Redpanda messages (after `market_analysis`'s committed offset), which `market_analysis_service` will consume:

```bash
sudo systemctl restart indicagent-indicator
```

Wait ~2 minutes for seeding to complete, then confirm in logs:

```bash
journalctl -u indicagent-market-analysis -f
# look for: active_symbols: N (where N > 0)
```

---

## Permanent Fix Needed

`market_analysis_service` should seek to beginning of `development.indicators` on startup, fast-forward through all historical messages, and deduplicate to the most recent per `symbol:TF` key — exactly like the SSE broadcaster pattern in `src/api/main.py:81-86`.

### SSE broadcaster reference pattern (`src/api/main.py:81-86`):
```python
group_id="sse_broadcaster",
auto_offset_reset="earliest",
...
await _sse_consumer.seek_to_beginning()  # replay history to repopulate _latest on restart
```

`KafkaConsumerClient.seek_to_beginning()` exists at `src/core/kafka_utils.py:79` — it's already supported.

### Proposed approach for `market_analysis_service`:

1. Change `auto_offset_reset="latest"` → `"earliest"` on the existing consumer **OR** create a separate short-lived consumer just for startup replay (avoids changing the main consumer's group behaviour).
2. On startup, before entering the main `_process_market_data()` loop, call `seek_to_beginning()` and fast-forward through `development.indicators`, collecting only the **latest message per `symbol:TF`** key.
3. Process those deduplicated I1 messages through the normal pipeline to warm up `bar_history` and compute + publish I2-I6 intelligence.
4. Then hand off to the normal consume loop as today.

### Tradeoffs to consider:
- **Separate startup consumer** (preferred): cleaner separation; main group offset stays correct; startup consumer can be a throwaway group ID like `f"market_analysis_seed_{uuid.uuid4().hex[:8]}"` with `auto_offset_reset="earliest"` so it always replays from the start and leaves no committed offsets.
- **Shared consumer with seek**: simpler, but `seek_to_beginning()` on a group with committed offsets may not behave as expected for subsequent restarts — test carefully.

---

## Files to Modify

| File | What |
|------|------|
| `services/market_analysis_service.py` | Add startup I1 replay before main consume loop |
| `services/market_analysis_service.py:733` | Consider `auto_offset_reset` change depending on approach |

## Related

- SSE broadcaster seek pattern: `src/api/main.py:81-86`
- `KafkaConsumerClient.seek_to_beginning()`: `src/core/kafka_utils.py:79`
- `_fallback_one()` (bar-only seed, no I1): `services/market_analysis_service.py:615`
- Memory note: `memory/project_market_analysis_weekend_bug.md`
