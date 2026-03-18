# Phase 37: Cross-Asset Intelligence Service — Research

**Researched:** 2026-03-18
**Status:** Complete — ready for planning

## RESEARCH COMPLETE

---

## 1. Service Architecture Pattern

**Template:** `services/signal_generator_service.py`

### Canonical Service Structure
```python
class CrossAssetService:
    def __init__(self):
        self.running = False
        self.shutdown_requested = False
        settings = Settings()
        self.env_name = settings.env_name or ""
        # ... metrics, logging, signal handlers
        setup_service_logging("logs/cross_asset_service.log")
        start_metrics_server(port=settings.cross_asset_metrics_port)  # 9118

    def _signal_handler(self, signum, frame):
        self.shutdown_requested = True

    async def start(self):
        try:
            await self._kafka_producer.start()
            await self._kafka_consumer.start()
            tasks = [asyncio.create_task(self._process_loop()), ...]
            await asyncio.gather(*tasks, return_exceptions=True)
        finally:
            await self.stop()

    async def stop(self):
        self.running = False
        await self._kafka_consumer.stop()
        await self._kafka_producer.stop()
```

### Kafka Consumer Pattern
```python
self._kafka_consumer = KafkaConsumerClient(
    topic_intelligence(env_name),
    bootstrap_servers=settings.kafka_bootstrap_servers,
    group_id="cross_asset_group",   # separate group — gets own copy
    auto_offset_reset="latest"
)
```

### Message Loop Pattern
```python
async for topic, key, payload in self._kafka_consumer.messages():
    if self.shutdown_requested:
        break
    if topic == _intel_topic:
        # process
    elif topic == _cross_asset_topic:
        # handle
```

### Feature Flag Guard (Phase 38 roll monitor pattern)
```python
if self._roll_monitor_enabled:
    topics.append(topic_system_events(self.env_name))
```
→ For cross_asset: `if self._cross_asset_enabled: topics.append(topic_cross_asset(self.env_name))`

---

## 2. Stream Keys

**File:** `src/core/stream_keys.py`

### Existing Pattern
```python
def topic_intelligence(env_name: str) -> str:
    return f"{env_prefix(env_name)}intelligence"

def topic_system_events(env_name: str) -> str:
    return f"{env_prefix(env_name)}system.events"
```

### New Function to Add
```python
def topic_cross_asset(env_name: str) -> str:
    """Kafka topic for cross-asset spread features (group-level)."""
    return f"{env_prefix(env_name)}cross_asset"
```

### Message Key Format
Group-based key: `"EQ_INDEX:1m"` — not symbol-based. Used for both publishing (cross_asset_service) and consuming (signal_generator_service cache lookup).

---

## 3. Settings Pattern

**File:** `src/config/settings.py` — `Settings(BaseSettings)` class

### Fields to Add
```python
# Cross-asset intelligence
cross_asset_enabled: bool = Field(default=False, validation_alias="CROSS_ASSET_ENABLED")
cross_asset_window_bars: int = Field(default=20, validation_alias="CROSS_ASSET_WINDOW_BARS")
cross_asset_metrics_port: int = Field(default=9118, validation_alias="CROSS_ASSET_METRICS_PORT")
```

### Active Instrument Groups (for group membership)
Settings defines instruments with `sector` field. EQ_INDEX group = instruments where `sector == "equity_index"` AND `asset_class == FUTURES`:
- ES (ESM6), NQ (NQM6), RTY (RTYM6), YM (YMM6)

Sector ETFs available for future groups: XLK, XLE, XLF, XLV, XLI, XLU, XLC, XLY (sector="technology" etc, asset_class=EQUITY)

---

## 4. Frames Dict Construction

**File:** `services/signal_generator_service.py` lines 1448-1458

### Current Frames Dict
```python
frames = {
    "main": self._get_df(key),      # pandas DataFrame of bar history
    "features": features,            # flat dict from _build_features_from_event()
}
```

### After Phase 37 — Inject Cross-Asset
```python
frames = {
    "main": self._get_df(key),
    "features": features,
    # NEW — only for equity_index symbols when cross_asset_enabled:
    "cross_asset": self._cross_asset_cache.get(timeframe, {"ready": False}),
    "cross_asset_5m": self._cross_asset_cache.get("5m", {"ready": False}),
}
```

### How I7 Plugins Receive Frames
`_run_setup_plugins(frames)` at line 986 iterates `I7_PLUGINS` and calls `plugin.compute_full(frames)` for each. Plugins read directly from `frames` keys.

---

## 5. I7 Plugin Pattern

**Reference:** `src/intelligence/trading/failed_breakout.py`

### Canonical Structure
```python
@dataclass
class FailedBreakoutPlugin:
    name: str = "trad_FailedBreakout"
    regime_type: str = "mean_reversion"   # MANDATORY
    outputs: frozenset[str] = frozenset({"signal_type", "direction", ...})
    inputs: tuple[InputSpec, ...] = (InputSpec(...),)
    min_lookback: int = 20
    supports_incremental: bool = False
    capability_tags: frozenset[str] = frozenset({"trading", "reversal"})
    # NO _state dict for stateless plugins

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        ...

    def compute_next(self, windows: dict[str, Any]) -> dict[str, Any]:
        return self.compute_full(windows)

    @staticmethod
    def _no_signal() -> dict[str, Any]:
        return {"signal_type": "none", "direction": 0, "confidence": 0.0}

plugin = FailedBreakoutPlugin()  # module-level export
```

### Stop Framing
All I7 plugins use `frame_trade()` from `trade_framer.py` for entry/stop/targets. Pass `setup_type`, `direction`, and the bar DataFrame.

### Registration
In `src/intelligence/register_plugins.py`:
1. Import: `from .trading.cross_asset_divergence import plugin as cross_asset_div_plugin`
2. Register: `registry.register_pattern(cross_asset_div_plugin)` in `register_all_plugins()`
3. Tier: append `cross_asset_div_plugin.name` to `TIER_I7` list

**Count assertions in `tests/unit/intelligence/test_i7_registration.py`:**
- Current (post-Phase 36): TIER_I7 = 30, total plugins = 113
- After Phase 37: TIER_I7 = 31, total plugins = 114
- Verify actual counts before updating (Phase 36 may still be in flight when 37 executes)

---

## 6. Intelligence Event Parsing

### Parsing Intelligence Topic Payload
```python
from src.intelligence.schemas import IntelligenceEvent

event = IntelligenceEvent.model_validate_json(payload.get("event"))
close_price = event.bar.c
volume = event.bar.v
symbol = event.symbol
timeframe = event.timeframe
ts = event.ts
base_symbol = event.symbol.rstrip("0123456789FGHJKMNQUVXZ")  # strip expiry
```

### Extracting Base Symbol (strip expiry code)
`"ESM6".rstrip("0123456789FGHJKMNQUVXZ")` → `"ES"`
`"RTYM6".rstrip("0123456789FGHJKMNQUVXZ")` → `"RTY"`

---

## 7. Cross-Asset Feature Computation

### Spread Z-Score Algorithm
```python
from collections import deque

_EQ_INDEX_BASES = frozenset({"ES", "NQ", "RTY", "YM"})
_SHORT_WINDOW = 5    # bars for return computation
_Z_SCORE_WINDOW = 20  # bars for z-score baseline

def compute_eq_index_features(
    close_windows: dict[str, deque],  # keyed by base symbol
    vol_windows: dict[str, deque],    # keyed by base symbol
    tf: str,
    ts: datetime,
    window_bars: int = 20,
) -> dict[str, Any]:
    # 1. Check all 4 symbols have >= window_bars
    for sym in _EQ_INDEX_BASES:
        if len(close_windows[sym]) < window_bars:
            return {"ready": False}

    # 2. Compute 5-bar log returns per symbol
    # 3. Compute spread = return_ES - return_NQ (and ES - RTY)
    # 4. z-score over last window_bars spreads
    # 5. Compute 5-bar and 20-bar pairwise correlations
    # 6. eq_corr_break = abs(short_corr - long_corr)
    # 7. Compute eq_vol_imbalance = (ES_vol / ES_avg_vol) / (NQ_vol / NQ_avg_vol)
    # 8. Determine active_pair, pairs_confirming

    return {
        "ready": True,
        "ts": ts.isoformat(),
        "tf": tf,
        "group": "EQ_INDEX",
        "es_nq_spread_z": float(es_nq_z),
        "es_rty_spread_z": float(es_rty_z),
        "eq_corr_break": float(corr_break),
        "eq_vol_imbalance": float(vol_imbalance),
        "active_pair": "ES_NQ" if abs(es_nq_z) >= abs(es_rty_z) else "ES_RTY",
        "pairs_confirming": int(sum([abs(es_nq_z) > 2.0, abs(es_rty_z) > 2.0])),
        "data_quality_score": float(data_quality),
        "low_vol_flag": bool(low_vol),
    }
```

**Critical:** All output values must be `float(x)` / `int(x)` — not `np.float64`. JSON serialization over Kafka requires plain Python types.

### Timing Alignment
4 symbol messages arrive near-simultaneously for the same bar. Track `_last_published_ts: dict[str, datetime]` per tf. Only publish once per unique `(tf, ts)` combination.

### DB Seed on Startup
```python
# Pseudo-code for startup seeding
async def _seed_from_db(self, symbol: str, tf: str):
    rows = await self.db_manager.fetch_all(
        "SELECT close, volume, computed_at FROM intelligence_features "
        "WHERE symbol=$1 AND timeframe=$2 ORDER BY computed_at DESC LIMIT $3",
        symbol, tf, self._window_bars
    )
    for row in reversed(rows):  # chronological order
        self._close_windows[f"{symbol}:{tf}"].append(row["close"])
        self._vol_windows[f"{symbol}:{tf}"].append(row["volume"])
```

---

## 8. Feature Persistence (feature_writer_service)

**File:** `services/feature_writer_service.py`

### Pattern for Adding New Topic Subscription
1. Add `topic_cross_asset(env_name)` to topics list when `cross_asset_enabled`
2. In message dispatch loop, add `elif topic == _cross_asset_topic:` branch
3. Parse payload, write to `intelligence_features` with tier `"cross_asset"` in JSONB

### intelligence_features Persistence
The cross_asset features persist as a new tier in the `intelligence_features` JSONB. Use the `"cross_asset"` key under the existing JSONB column structure.

---

## 9. Systemd Unit

**File:** `production/systemd/indicagent-cross-asset.service`

```ini
[Unit]
Description=IndicAgent Cross-Asset Intelligence Service
After=network-online.target indicagent-market-analysis.service
Wants=indicagent-market-analysis.service
StartLimitIntervalSec=300
StartLimitBurst=5

[Service]
Type=simple
User=bg
WorkingDirectory=/home/bg/dev/indicagent
Environment=PYTHONPATH=/home/bg/dev/indicagent
Environment=PYTHONUNBUFFERED=1
ExecStart=/home/bg/dev/indicagent/.venv/bin/python services/cross_asset_service.py
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal
SyslogIdentifier=indicagent-cross-asset
LimitNOFILE=65536

[Install]
WantedBy=multi-user.target
```

---

## 10. Metrics Port Allocation

Current assignments:
- indicator_service: :9109
- signal_generator: :9112
- ai_narrative: :9113
- market_analysis: :9114
- signal_lifecycle: :9115
- feature_writer: :9116
- llm_writer: :9117
- **cross_asset: :9118** (next available)

---

## 11. Redpanda Topic Setup

After service deployment:
```bash
docker exec redpanda rpk topic create development.cross_asset
docker exec redpanda rpk topic alter-config development.cross_asset --set retention.ms=604800000
```

---

## 12. Test Patterns

### Service Tests (bypass __init__ with __new__)
```python
svc = CrossAssetService.__new__(CrossAssetService)
svc._close_windows = defaultdict(lambda: deque(maxlen=20))
svc._vol_windows = defaultdict(lambda: deque(maxlen=20))
svc._last_published_ts = {}
svc.env_name = ""
svc._window_bars = 20
svc._cross_asset_enabled = True
```

### Plugin Tests (pure function, no infra)
```python
from src.intelligence.trading.cross_asset_divergence import CrossAssetDivergencePlugin
plugin = CrossAssetDivergencePlugin()
result = plugin.compute_full({"cross_asset": {...}, "features": {...}})
assert result["direction"] == -1
```

---

## 13. CLAUDE.md Updates Required

After implementation, update CLAUDE.md:
1. Add `cross_asset_service` row to services table with metrics port :9118
2. Add `indicagent-cross-asset` to systemd unit inventory
3. Update plugin counts in Key Facts section

---

## Validation Architecture

### Verification Commands
```bash
# Confirm service publishes
docker exec redpanda rpk topic consume development.cross_asset --num 1

# Confirm features appear in payload
docker exec redpanda rpk topic consume development.cross_asset --num 1 | python3 -c "import sys,json; d=json.loads(sys.stdin.read()); print(list(d.keys()))"

# Confirm plugin fires in replay
.venv/bin/python production/scripts/historical_backfill.py --replay-only --symbols ESM6 --days 2

# Confirm registration
.venv/bin/python -c "from src.intelligence.register_plugins import TIER_I7; print('trad_CrossAssetDivergence' in TIER_I7)"

# Run unit tests
.venv/bin/pytest tests/unit/test_cross_asset_features.py tests/unit/test_cross_asset_divergence_plugin.py -v
```

### Success Criteria (from ROADMAP.md)
1. `indicagent-cross-asset` service starts and publishes to `development.cross_asset` topic
2. `es_nq_spread_z`, `es_rty_spread_z`, `eq_corr_break` visible in consumed messages
3. `trad_CrossAssetDivergence` fires in replay with injected spread event; direction reflects regime bias
4. Service registered in CLAUDE.md services table with :9118 port

---

*Research complete — planner may proceed directly to PLAN.md creation.*
*Key files: services/signal_generator_service.py, src/core/stream_keys.py, src/intelligence/trading/failed_breakout.py, src/intelligence/register_plugins.py, services/feature_writer_service.py*
