# Phase 54: Provider Abstraction Layer — Broker-Agnostic Data Foundation

## Naming Audit (strictly enforced per CLAUDE.md)

| Layer | Name | Convention | Compliant? |
|-------|------|-----------|------------|
| Protocol | `DataProviderAdapter` | `PascalCase` | ✓ |
| Base class | `BaseProviderAgent` | `PascalCase` (mirrors `BaseAgent`) | ✓ |
| Adapter class | `IBKRAdapter` | `PascalCase` | ✓ |
| Agent class | `IBKRProviderAgent` | `PascalCase` + role suffix | ✓ |
| Agent class | `ProviderMergerAgent` | `PascalCase` + `Agent` suffix | ✓ |
| Agent file | `ibkr_provider_agent.py` | `<concept>_agent.py` | ✓ |
| Agent file | `provider_merger_agent.py` | `<concept>_agent.py` | ✓ |
| Base class file | `base_provider_agent.py` | `<concept>_agent.py` | ✓ |
| Adapter file | `ibkr_adapter.py` | `<concept>_adapter.py` | ✓ |
| Systemd unit | `indicagent-ibkr-provider.service` | `indicagent-<concept-kebab>.service` | ✓ |
| Systemd unit | `indicagent-provider-merger.service` | `indicagent-<concept-kebab>.service` | ✓ |
| Log file | `logs/ibkr_provider_agent.log` | `logs/<python_filename>.log` | ✓ |
| Log file | `logs/provider_merger_agent.log` | `logs/<python_filename>.log` | ✓ |
| Topic fn | `topic_market_bars_raw(env, provider)` | `topic_<content>()` | ✓ |
| Topic fn | `topic_market_data_quality(env)` | `topic_<content>()` | ✓ (distinct from existing `topic_data_quality` → `pipeline.data_quality`) |
| Topic string | `{env}.market.bars.raw.{provider}` | `<env>.<domain>.<sublayer>` dots only | ✓ |
| Topic string | `{env}.market.data.quality` | `<env>.<domain>.<sublayer>` dots only | ✓ |
| Source const | `SOURCE_IBKR_GENERIC` (existing, `"ibkr"`) | `UPPER_SNAKE_CASE` | ✓ — already covers RTB bars; do NOT add a new SOURCE_IBKR_RTB constant |
| Metrics prefix | `provider_*` | `<concept>_<metric>_total` | ✓ |
| Metrics prefix | `merger_*` | `<concept>_<metric>_total` | ✓ |
| Consumer group | `ibkr_provider_gap_consumer` | `<concept>_consumer` | ✓ |
| Consumer group | `provider_merger_consumer` | `<concept>_consumer` | ✓ |

**Key constraint:** `provider_meta` nested key MUST match `adapter.provider_name` exactly (`"ibkr"`, `"alpaca"`, etc.) so adapters can look up their own config with `instrument.provider_meta.get(self.provider_name, {})` — zero hardcoded strings.

## Context

Phase 53.x delivered a clean data DAG (DataProviderAgent → BarAggregatorComputeAgent → BarWriterAgent/BarAuditorAgent → FeatureComputeAgent). What remains is the broker abstraction: `DataProviderAgent` is still hard-wired to IBKR. Adding a second provider today requires surgery.

Renaissance framing: **the adapter is commodity, the agent infrastructure is the moat.** One `BaseProviderAgent` class handles lifecycle/metrics/reconnect/gap-fill for every provider. The adapter is pure wire-protocol translation. Swapping IBKR for TastyTrade = one new file + one systemd unit. Everything downstream is untouched.

The `ProviderMergerAgent` runs even in single-provider mode — it is the single canonical author of `market.bars`, collects per-bar latency as a quality signal, and auto-promotes a secondary on silence. No human intervention required.

## Architecture

```
IBKRProviderAgent ──► market.bars.raw.ibkr ──┐
                                               ├──► ProviderMergerAgent ──► market.bars ──► (8 consumers, unchanged)
AlpacaProviderAgent ──► market.bars.raw.alpaca─┘         │
(stub only)                                               ▼
                                               market.data.quality (ProviderQualityEvent)
```

All 8 current consumers of `market.bars` are untouched. The merger is transparent.

## Critical Files

**Existing:**
- `services/data_provider_agent.py` — monolith to be replaced; deleted post-cutover (in git history; check backfill script imports before deleting)
- `src/providers/base.py` — has old `DataProvider` Protocol + `OHLCVBar`/`Tick` types (kept)
- `src/providers/ibkr.py` — IBKRProvider, kept unchanged; IBKRAdapter wraps it
- `src/core/agent/base.py` — BaseAgent lifecycle to inherit from
- `src/core/kafka_utils.py` — KafkaProducerClient/KafkaConsumerClient (takes `*topics`)
- `src/core/stream_keys.py` — all topic functions
- `src/core/schemas/bar_message.py` — BarMessage, source Literal
- `src/observability/metrics.py` — metrics registration
- `src/config/settings.py` — Instrument model, provider_meta (only VXJ6 uses it: `{"trading_class": "VX"}`)
- `src/core/plugin_circuit_breaker.py` — PluginCircuitBreaker, fully reusable

**New files:**
- `src/providers/base_provider_agent.py` — BaseProviderAgent(BaseAgent)
- `src/providers/ibkr_adapter.py` — IBKRAdapter implementing DataProviderAdapter Protocol
- `src/core/schemas/provider_quality.py` — ProviderQualityEvent schema
- `services/ibkr_provider_agent.py` — IBKRProviderAgent(BaseProviderAgent)
- `services/provider_merger_agent.py` — ProviderMergerAgent(BaseAgent)
- `services/indicagent-ibkr-provider.service` — port :9129
- `services/indicagent-provider-merger.service` — port :9130

## Plan Breakdown

---

### Plan 54-01: Foundation — Contracts, Schemas, Stream Keys

**Goal:** Pure additions, zero behavioral change. Establishes the typed contracts everything else builds on.

**Files modified:**
- `src/providers/base.py` — add `DataProviderAdapter` Protocol alongside existing `DataProvider` (do not remove old one):
  ```python
  @runtime_checkable
  class DataProviderAdapter(Protocol):
      provider_name: str  # "ibkr", "alpaca", etc.
      async def connect(self) -> bool: ...
      async def disconnect(self) -> None: ...
      def is_connected(self) -> bool: ...
      async def stream_bars(self, instruments: list[Instrument]) -> AsyncIterator[BarMessage]: ...
      async def fetch_historical(self, symbol: str, tf: str, start: datetime, end: datetime) -> list[BarMessage]: ...
      async def qualify_instrument(self, instrument: Instrument) -> Instrument: ...
  ```
- `src/core/schemas/provider_quality.py` — NEW:
  ```python
  class ProviderQualityEvent(BaseModel):
      ts: datetime           # UTC-aware
      symbol: str
      tf: str
      provider: str          # "ibkr", "alpaca"
      event_type: Literal["bar_received", "gap_detected", "failover", "recovery"]
      publish_ts: datetime   # when provider published to raw topic
      consume_ts: datetime   # when merger received it
      latency_ms: float      # stored, not computed (consumers filter on it)
      promoted_provider: str | None = None
  ```
- `src/core/stream_keys.py` — add (note: existing `topic_data_quality` maps to `pipeline.data_quality` — this is a distinct topic for the provider/market layer):
  ```python
  def topic_market_bars_raw(env_name: str, provider: str) -> str:
      """Raw bars from a single provider before merger routing."""
      return f"{env_prefix(env_name)}market.bars.raw.{provider}"

  def topic_market_data_quality(env_name: str) -> str:
      """ProviderQualityEvent side-channel: provider latency, gaps, failovers."""
      return f"{env_prefix(env_name)}market.data.quality"
  ```
- `src/core/schemas/bar_message.py` — **no new source constant needed.** `SOURCE_IBKR_GENERIC = "ibkr"` already exists in `bar_normalizer.py` for RTB/fallback bars. RTB-derived 1m bars use this existing constant. Expand the `source` Literal only if `SOURCE_IBKR_GENERIC` is not already in it — check first.
- `src/observability/metrics.py` — add provider + merger Golden Signal metrics. Use `provider` AND `agent` labels (provider = "ibkr"/"alpaca", agent = agent instance name). Pre-cache labeled children in `__init__` per established pattern:
  ```python
  # Provider agent metrics (shared across all ProviderAgent subclasses)
  PROVIDER_BARS_PRODUCED_TOTAL = Counter(
      "provider_bars_produced_total", "Bars published to market.bars.raw.<provider>", ["provider", "agent"])
  PROVIDER_RECONNECTS_TOTAL = Counter(
      "provider_reconnects_total", "Provider reconnection attempts", ["provider", "agent"])
  PROVIDER_CONNECTED = Gauge(
      "provider_connected", "1 when provider TCP/WebSocket is connected", ["provider", "agent"])
  PROVIDER_GAPS_FILLED_TOTAL = Counter(
      "provider_gaps_filled_total", "Gap fill requests handled", ["provider", "agent"])
  # Merger metrics
  MERGER_BARS_ROUTED_TOTAL = Counter(
      "merger_bars_routed_total", "Bars forwarded to market.bars", ["provider"])
  MERGER_BARS_DROPPED_TOTAL = Counter(
      "merger_bars_dropped_total", "Bars from non-authoritative provider (not forwarded)", ["provider"])
  MERGER_FAILOVERS_TOTAL = Counter(
      "merger_failovers_total", "Auto-promotions of secondary provider", ["from_provider", "to_provider"])
  MERGER_BAR_LATENCY_SECONDS = Histogram(
      "merger_bar_latency_seconds", "Publish-to-consume latency per provider", ["provider"],
      buckets=[0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0])
  ```
- Export `DataProviderAdapter` from `src/providers/__init__.py`

**Tests (write first):**
- `tests/unit/providers/test_adapter_protocol.py` — Protocol shape, `ProviderQualityEvent` fields/types/UTC, stream key formats
- Extend `tests/unit/test_stream_keys.py` with new topic assertions

**Verification:** `pytest tests/unit/providers/test_adapter_protocol.py tests/unit/test_stream_keys.py -v` all pass; `ruff check` clean; no existing tests broken.

**Dependencies:** None.

---

### Plan 54-02: IBKRAdapter + provider_meta Migration

**Goal:** `IBKRAdapter` wraps `IBKRProvider` and produces `BarMessage` directly. Migrate `provider_meta` to nested-by-broker format.

**Files modified:**
- `src/providers/ibkr_adapter.py` — NEW: `IBKRAdapter` implementing `DataProviderAdapter`.
  - `provider_name: str = "ibkr"` — this string is the key used in `provider_meta` lookups. Adapters must use `instrument.provider_meta.get(self.provider_name, {})` — never hardcode the string at the call site.
  - `stream_bars()`: runs `provider.stream_real_time_bars()` internally; the RTB aggregation state machine (currently 200 lines in `DataProviderAgent._rtb_loop()`) **moves here** — this is IBKR-specific (5s bars are an IBKR concept). Yields completed 1m `BarMessage` with `source=SOURCE_IBKR_GENERIC`, UTC-aware ts, `session_type` via `normalize_session_type()`. Also subscribes to `stream_official_bars()` in background for `is_reconciled`/`drift_detected` enrichment.
  - `fetch_historical()`: calls `provider.fetch_historical_bars()`, converts `OHLCVBar` → `BarMessage` with `source=SOURCE_IBKR_NAMED`
  - `qualify_instrument()`: reads `instrument.provider_meta.get("ibkr", {})` for symbol overrides
- `src/config/settings.py` — migrate VXJ6: `provider_meta={"trading_class": "VX"}` → `provider_meta={"ibkr": {"trading_class": "VX"}}`
- `src/providers/ibkr.py` line ~417 — update `qualify_instrument` to read `instrument.provider_meta.get("ibkr", {}).get("trading_class", "")`. No fallback to flat key — the migration in `settings.py` is the single source of truth. Remove any remaining flat `provider_meta.get("trading_class")` access.

**Tests (write first):**
- `tests/unit/providers/test_ibkr_adapter.py`:
  - Satisfies `DataProviderAdapter` Protocol
  - `provider_name == "ibkr"`
  - `stream_bars` yields `BarMessage` with correct source, UTC ts, symbol
  - `fetch_historical` returns `list[BarMessage]`
  - `qualify_instrument` reads nested `provider_meta["ibkr"]`
  - VXJ6 settings round-trips `provider_meta == {"ibkr": {"trading_class": "VX"}}`

**Verification:** `pytest tests/unit/providers/ -v` all pass; `pytest tests/unit/test_settings.py -v` no regressions.

**Dependencies:** Plan 54-01 (needs `DataProviderAdapter`, `SOURCE_IBKR_GENERIC`).

---

### Plan 54-03: BaseProviderAgent + IBKRProviderAgent

**Goal:** Create the shared agent base class. `IBKRProviderAgent` inherits it and publishes to `market.bars.raw.ibkr`. The existing `DataProviderAgent` keeps running during this plan — no cutover yet.

**Files created:**
- `src/providers/base_provider_agent.py` — `BaseProviderAgent(BaseAgent)`:
  - **Constructor (config-before-super pattern, per BarAggregatorComputeAgent):**
    - `self._settings = Settings()` before `super().__init__(name=..., metrics_port=...)`
    - Abstract properties: `_agent_name()`, `_agent_metrics_port()`, `_provider_name_str()`
    - Abstract method: `_create_adapter() -> DataProviderAdapter`
    - Pre-cache labeled metric children (avoid per-bar dict lookups)
    - `PluginCircuitBreaker` instance with config (not IBKR-specific, reused from `src/core/plugin_circuit_breaker.py`)
  - **`_setup()`**: start KafkaProducerClient; call `self._adapter = self._create_adapter()`; connect adapter
  - **`_run()`**: launch `_stream_loop()` + `_gap_requests_loop()` as asyncio tasks; `await self._stop_event.wait()`; cancel/await both on shutdown
  - **`_stream_loop()`**: `async for bar in self._adapter.stream_bars(instruments)` → `_publish_bar(bar)`. On disconnect: `_reconnect()`.
  - **`_reconnect()`**: exponential backoff (base 2s, max 60s), circuit breaker respected, increments `_m_reconnects`
  - **`_gap_requests_loop()`**: extract verbatim from `DataProviderAgent._gap_requests_loop()`; replace `self.provider.fetch_historical_bars()` with `self._adapter.fetch_historical()`; publish to `topic_market_bars_raw(env, provider_name)`. Consumer group: `ibkr_provider_gap_consumer` (different from old `data_provider_consumer` to avoid offset conflict during parallel running)
  - **`_teardown()`**: drain producer; disconnect adapter
  - **`_publish_bar(bar)`**: publish to `topic_market_bars_raw(env, provider_name)`; increment `_m_bars_raw`; update `_g_connected`

- `services/ibkr_provider_agent.py` — thin subclass:
  ```python
  class IBKRProviderAgent(BaseProviderAgent):
      def _agent_name(self) -> str: return "ibkr_provider_agent"
      def _agent_metrics_port(self) -> int: return 9129
      def _provider_name_str(self) -> str: return "ibkr"
      def _create_adapter(self) -> DataProviderAdapter:
          return IBKRAdapter(host=..., port=..., client_id=...)
  ```
  Plus `if __name__ == "__main__"` with `init_tracing("ibkr_provider_agent")` + `asyncio.run(agent.start())`.

- `services/indicagent-ibkr-provider.service` — systemd unit (same pattern as existing agents, `PYTHONUNBUFFERED=1` required)

**Tests (write first, using `__new__` bypass pattern):**
- `tests/unit/service_tests/test_base_provider_agent.py`:
  - Inherits BaseAgent
  - `_create_adapter()` is abstract
  - Reconnect uses exponential backoff, capped at 60s
  - Gap loop calls `adapter.fetch_historical()` on `BarGapRequest`
  - Gap fills published to raw topic (not `market.bars`)
  - Metrics have `provider` label
- `tests/unit/service_tests/test_ibkr_provider_agent.py`:
  - Inherits BaseProviderAgent
  - `_create_adapter()` returns IBKRAdapter
  - `topics_produced` includes `market.bars.raw.ibkr`

**Verification:** `pytest tests/unit/service_tests/test_base_provider_agent.py tests/unit/service_tests/test_ibkr_provider_agent.py -v`; import check `python -c "from services.ibkr_provider_agent import IBKRProviderAgent"`; systemd unit syntax check.

**Dependencies:** Plans 54-01, 54-02.

---

### Plan 54-04: ProviderMergerAgent + Zero-Downtime Cutover

**Goal:** Build the canonical gateway. Execute cutover from `DataProviderAgent` to the new two-service stack. Update docs.

**Files created/modified:**
- `src/config/settings.py` — add merger config fields:
  ```python
  provider_raw_topics: list[str] = Field(default_factory=lambda: ["ibkr"])
  provider_routing_config: dict[str, str] = Field(
      default_factory=lambda: {"futures": "ibkr", "equity": "ibkr", "crypto": "ibkr", "fx": "ibkr"}
  )
  provider_silence_bars_threshold: int = Field(default=5)
  ```

- `services/provider_merger_agent.py` — `ProviderMergerAgent(BaseAgent)`:
  - Subscribes to ALL configured raw topics via single `KafkaConsumerClient(*raw_topics, ...)` — works because KafkaConsumerClient takes `*topics`
  - Consumer group: `provider_merger_consumer`
  - **Routing**: extract `provider` from topic suffix (`dev.market.bars.raw.ibkr` → `"ibkr"`). Look up active instrument for symbol → `asset_class`. Check `_promoted` dict first, then `settings.provider_routing_config[asset_class]`.
  - **On authoritative bar**: publish to `market.bars` (BarMessage unchanged, source preserved); publish `ProviderQualityEvent(event_type="bar_received", latency_ms=...)` to `market.data.quality`; update `_last_bar_ts[provider][symbol]`
  - **On non-authoritative bar**: update secondary tracking only; check `_check_failover(symbol)`
  - **`_check_failover(symbol)`**: if primary has been silent ≥ `silence_bars_threshold` bar-intervals on this symbol and secondary has recent data → set `_promoted[symbol] = secondary`; publish `ProviderQualityEvent(event_type="failover", promoted_provider=secondary)`
  - **Recovery**: when primary resumes after failover → publish `ProviderQualityEvent(event_type="recovery")`; remove from `_promoted`
  - **Metrics**: `m_bars_routed`, `m_bars_dropped`, `m_failovers`, `m_recoveries` (labeled by `provider`)
  - Silence is bar-count-based, measured via `_last_bar_ts` timestamps vs current time / expected bar interval

- `services/indicagent-provider-merger.service` — port :9130

- **Zero-downtime cutover procedure:**
  ```
  1. sudo cp services/indicagent-{ibkr-provider,provider-merger}.service /etc/systemd/system/
     sudo systemctl daemon-reload

  2. sudo systemctl start indicagent-ibkr-provider indicagent-provider-merger
     # Both old and new stack running simultaneously — observe for 2-3 minutes
     # Verify market.bars has double bars (expected: old + new both publishing)

  3. Check new stack health:
     sudo journalctl -u indicagent-ibkr-provider -f
     sudo journalctl -u indicagent-provider-merger -f
     # Look for "bar_routed" log lines from merger

  4. sudo systemctl stop indicagent-data-provider
     sudo systemctl disable indicagent-data-provider
     # market.bars now served exclusively by new stack

  5. sudo systemctl enable indicagent-ibkr-provider indicagent-provider-merger

  6. docker exec redpanda rpk group describe feature_pipeline -t
     # Consumer lag on market.bars should be 0 within 60s

  ROLLBACK (if step 4 reveals issues):
     sudo systemctl stop indicagent-ibkr-provider indicagent-provider-merger
     sudo systemctl start indicagent-data-provider
  ```

- **Remove old service file** `services/data_provider_agent.py` after cutover is verified stable. It is in git history. Check whether any backfill scripts import from it first — update those imports before deletion.

- **CLAUDE.md updates:**
  - Active Services table: replace `Data Provider | indicagent-data-provider` with:
    - `IBKR Provider | indicagent-ibkr-provider | IBKR dual streams: 5s RTB → 1m aggregation + official reconciliation; publishes to market.bars.raw.ibkr | :9129`
    - `Provider Merger | indicagent-provider-merger | Routes market.bars.raw.<provider> → market.bars; auto-failover on primary silence; ProviderQualityEvent quality side-channel | :9130`
  - Add `topic_market_bars_raw(env, provider)` and `topic_market_data_quality(env)` to the stream keys doc section
  - Update "New contracts" procedure to reference `IBKRProviderAgent` restart instead of `indicagent-data-provider`

**Tests (write first):**
- `tests/unit/service_tests/test_provider_merger_agent.py`:
  - Routes authoritative provider bar → `market.bars`
  - Drops non-authoritative provider bar from `market.bars`
  - Preserves `BarMessage.source` unchanged
  - Publishes `ProviderQualityEvent` on every routed bar
  - `latency_ms > 0`
  - Detects primary silence and promotes secondary
  - Emits recovery event when primary resumes
  - Subscribes to all configured raw topics via single consumer

**Full verification:**
- `pytest tests/unit/ -v --tb=short` — full suite clean
- `ruff check services/provider_merger_agent.py services/ibkr_provider_agent.py src/providers/`
- `black --check services/ src/providers/`
- Cutover executed; consumer lag = 0 within 60s on all downstream groups
- `indicagent-data-provider` disabled; new services enabled and surviving reboot test

**Dependencies:** Plans 54-01, 54-02, 54-03.

---

## Patterns to Reuse

| Pattern | Location |
|---------|----------|
| Config-before-super constructor | `services/bar_aggregator_agent.py:__init__` |
| `__new__` service test bypass | `tests/unit/service_tests/test_bar_aggregator_agent.py` |
| Pre-cached labeled metric children | `services/bar_aggregator_agent.py:64–91` |
| `PluginCircuitBreaker` config | `src/providers/ibkr.py` (module-level singleton) |
| Gap-fill request loop | `services/data_provider_agent.py:_gap_requests_loop()` |
| OTel `init_tracing()` in `__main__` | `services/bar_aggregator_agent.py` |
| Systemd unit with `PYTHONUNBUFFERED=1` | `services/indicagent-bar-aggregator-compute.service` |

## What is NOT built in Phase 54
- Actual Alpaca/TastyTrade adapters (Protocol only — stub when needed)
- `ProviderAuditorAgent` (per-provider quality scoring, ML features)
- Divergence detection between two live active providers
- `market.data.quality` consumer (topic exists; no reader yet — that's Phase 55+)
