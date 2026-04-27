# Phase 66: SkepticAgent - Pattern Map

**Mapped:** 2026-04-24
**Files analyzed:** 8
**Analogs found:** 8 / 8

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `src/intelligence/swarm/agents/skeptic_agent.py` | swarm-agent | event-driven | `services/swarm_orchestrator_agent.py` | exact |
| `src/intelligence/swarm/agents/skeptic_prompts.py` | utility | transform | `src/intelligence/narrative/prompts.py` | exact |
| `services/skeptic_agent_service.py` | service | request-response | `services/swarm_orchestrator_agent.py` | exact |
| `services/indicagent-skeptic-agent.service` | config | systemd-unit | `services/indicagent-ai-narrative.service` | exact |
| `scripts/validate_skeptic.py` | utility | batch | `production/scripts/validate_alpha.py` | role-match |
| `scripts/compute_skeptic_baseline.py` | utility | batch | `production/scripts/validate_alpha.py` | role-match |
| `tests/unit/test_skeptic_agent.py` | test | unit | `tests/unit/service_tests/test_swarm_orchestrator_agent.py` | exact |
| `tests/unit/test_skeptic_validation.py` | test | unit | `tests/unit/test_swarm_protocol.py` | role-match |

## Pattern Assignments

### `src/intelligence/swarm/agents/skeptic_agent.py` (swarm-agent, event-driven)

**Analog:** `services/swarm_orchestrator_agent.py`

**Service entry point pattern** (lines 236-243):
```python
def main() -> None:
    settings = Settings()
    agent = SwarmOrchestratorComputeAgent(settings, contributors=[])
    asyncio.run(agent.start())

if __name__ == "__main__":
    main()
```

**SwarmBaseAgent subclass pattern** (lines 41-53):
```python
from src.core.agent.base import BaseAgent
from src.intelligence.swarm.context import SwarmContextCache
from src.intelligence.swarm.safety import SafeSwarmWrapper

class SwarmOrchestratorComputeAgent(BaseAgent):
    def __init__(self, settings: Settings, contributors: list | None = None) -> None:
        super().__init__(name="SwarmOrchestratorComputeAgent", max_idle_seconds=300)
        self.settings = settings
        self._context_cache = SwarmContextCache()
        self._contributors = [SafeSwarmWrapper(c) for c in (contributors or [])]
```

**Kafka consumer setup pattern** (lines 54-77):
```python
async def _setup(self) -> None:
    env = self.settings.env_name
    self._bar_consumer = KafkaConsumerClient(
        topic_market_bars(env),
        topic_market_bars_htf(env),
        bootstrap_servers=self.settings.kafka_bootstrap_servers,
        group_id="swarm_orchestrator_bar_consumer",
        auto_offset_reset="latest",
    )
    await self._bar_consumer.start()

    self._signal_consumer = KafkaConsumerClient(
        topic_intelligence_i7_signals(env),
        bootstrap_servers=self.settings.kafka_bootstrap_servers,
        group_id="swarm_orchestrator_signal_consumer",
        auto_offset_reset="latest",
    )
    await self._signal_consumer.start()

    self._producer = KafkaProducerClient(
        bootstrap_servers=self.settings.kafka_bootstrap_servers,
    )
    await self._producer.start()
```

**Context cache seeding pattern** (lines 209-234):
```python
async def _seed_context_cache(self, pool: asyncpg.Pool) -> None:
    """Seed SwarmContextCache from last row per (symbol, tf) in intelligence_features."""
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT DISTINCT ON (symbol, tf)
                    symbol, tf, ts, bar, i1, i4, i6
                FROM intelligence_features
                WHERE ts > NOW() - INTERVAL '7 days'
                  AND i1 IS NOT NULL
                  AND i4 IS NOT NULL
                ORDER BY symbol, tf, ts DESC
            """)
        loaded = 0
        for row in rows:
            self._context_cache.seed_from_db_row(dict(row))
            loaded += 1
        self.logger.info("swarm_orchestrator.cache_seeded", rows=loaded)
    except Exception as exc:
        self.logger.warning("swarm_orchestrator.cache_seed_failed", error=str(exc))
```

**Signal loop pattern** (lines 117-129):
```python
async def _signal_loop(self) -> None:
    assert self._signal_consumer is not None
    async for _topic, _key, payload in self._signal_consumer.messages():
        if not self.running:
            break
        self._record_message_consumed()
        symbol = (
            payload.get("symbol")
            if isinstance(payload, dict)
            else getattr(payload, "symbol", None)
        )
        tf = payload.get("tf") if isinstance(payload, dict) else getattr(payload, "tf", None)
        await self._handle_signal(payload, symbol=symbol, tf=tf)
```

**SwarmContext build pattern** (lines 142-153):
```python
signal_id = uuid4()
ctx = self._context_cache.build(
    symbol=symbol or "",
    tf=tf or "",
    signal=signal,
    signal_id=signal_id,
)
if ctx is None:
    await self._producer.publish(
        topic_swarm_orchestrator_dlq(self.settings.env_name),
        {"error": "no_context", "symbol": symbol, "tf": tf},
    )
    return
```

---

### `src/intelligence/swarm/agents/skeptic_prompts.py` (utility, transform)

**Analog:** `src/intelligence/narrative/prompts.py`

**Prompt registry pattern** (lines 14-32):
```python
_STRUCTURAL_LABELS: dict[str, str] = {
    "LiquiditySweepReclaim": "SWEEP RECLAIM",
    "LiquidityHunt": "LIQUIDITY HUNT",
    "FVGFill": "FVG FILL",
    # ... more mappings
}

_REGIME_LABELS = {0: "Ranging", 1: "Trending Up", 2: "Trending Down"}
```

**Pure prompt building function pattern** (lines 46-92):
```python
def build_short_prompt(record: BarIntelligenceRecord) -> str:
    """Two-sentence prompt. confidence >= 0.75 → direct; 0.50-0.74 → conditional; < 0.50 → monitor."""
    intel = record.intelligence
    symbol = intel.symbol
    tf = intel.tf
    direction = record.winner_direction or 0
    confidence = record.winner_confidence or 0.0
    plugin = record.winner_plugin or ""
    close = intel.bar.c
    atr = getattr(intel.i1, "atr_14", None) or 1.0
    regime = getattr(intel.i4, "hmm_regime", None)
    regime_prob = getattr(intel.i4, "hmm_regime_prob", None)
    ctf = getattr(intel.i6, "ctf_trend_alignment", None)

    stop = round(close - atr * 1.5, 2) if direction > 0 else round(close + atr * 1.5, 2)
    entry = close

    if confidence >= 0.75:
        exec_line = (
            f"Sentence 2 (Execution — DIRECT): State entry at {entry} with stop at {stop}. "
            f"High conviction — instruct PM to act now."
        )
    elif confidence >= 0.50:
        exec_line = (
            f"Sentence 2 (Execution — CONDITIONAL): Name the exact condition before entering. "
            f"Entry {entry}, stop {stop}."
        )
    else:
        exec_line = "Sentence 2 (Monitor): Name what level confirms this setup. Frame as 'watch' not 'enter'."

    regime_line = ""
    if regime is not None and regime_prob is not None:
        regime_line = f"Regime: {_REGIME_LABELS.get(regime, str(regime))} (prob {float(regime_prob):.0%})\n"

    ctf_line = f"CTF Alignment: {ctf:.2f}\n" if ctf is not None else ""

    return (
        f"/no_think\n\n"
        f"Symbol: {symbol} {tf} — {_direction_label(direction)} (confidence {confidence:.0%})\n"
        f"Structure: {_structural_label(plugin)}\n"
        f"{regime_line}"
        f"{ctf_line}"
        f"Entry: {entry} | Stop: {stop}\n\n"
        f"Write exactly 2 sentences:\n"
        f"Sentence 1 (Context — STRUCTURAL): What is the market doing and why does this level matter?\n"
        f"{exec_line}"
    )
```

**Versioned prompt registry pattern** (from RESEARCH.md Pattern 2):
```python
PROMPT_REGISTRY = {
    "skeptic_v1": """You are a skeptical trading analyst reviewing a signal.

Signal details:
- Symbol: {symbol}
- Timeframe: {timeframe}
- Setup: {winner_plugin} ({direction} {confidence:.0%})
- Regime: hmm_regime={hmm_regime} (0=ranging, 1=trending_up, 2=trending_down)
- ATR: {atr:.2f}
- RSI: {rsi:.1f}
- ADX: {adx:.1f}
- Price: {price:.2f}
- Volume: {volume:.0f}

Cross-timeframe confluence:
- CTF trend alignment: {ctf_trend_alignment}
- CTF regime agreement: {ctf_regime_agreement}
- CTF FVG alignment: {ctf_fvg_alignment}
- CTF OB alignment: {ctf_ob_alignment}

Context classification:
- Trend regime: {trend_regime}
- Vol regime: {vol_regime}
- VWAP: {vwap:.2f}
- POC: {poc_price:.2f}
- POC rolling: {poc_price_rolling:.2f}

TASK: Identify what's WRONG with this signal. Respond with JSON ONLY:
{{
    "failure_probability": <float 0.0-1.0>,
    "confidence": <float 0.0-1.0>,
    "risk_factors": ["<factor1>", "<factor2>", ...],
    "reasoning": "<1-2 sentence explanation>"
}}

Rules:
- failure_probability=0.0 means "nothing wrong, this is a great signal"
- failure_probability=1.0 means "this will definitely fail"
- Be contrarian — look for hidden risks, regime mismatches, weak confluence
- confidence reflects how certain you are in your failure probability
""",
}
```

---

### `services/skeptic_agent_service.py` (service, request-response)

**Analog:** `services/ai_narrative_agent.py`

**Thin Kafka wrapper pattern** (lines 24-35):
```python
class AINarrativeComputeAgent(BaseAgent):
    """Thin agent: consume BarIntelligenceRecord → generate narrative → publish."""

    def __init__(self, settings: Settings) -> None:
        super().__init__("AINarrativeComputeAgent")
        self.settings = settings
        chain = LLMProviderChain(call_type="narrative", settings=settings)
        self._orchestrator = NarrativeOrchestrator(chain=chain, max_tokens=200, timeout=30.0)
        # Kafka clients created in _setup() — AIOKafkaConsumer requires a running event loop.
        self._consumer: KafkaConsumerClient | None = None
        self._producer: KafkaProducerClient | None = None
```

**Async consumer setup pattern** (lines 36-48):
```python
async def _setup(self) -> None:
    self._consumer = KafkaConsumerClient(
        topic_intelligence_journal(self.settings.env_name),
        bootstrap_servers=self.settings.kafka_bootstrap_servers,
        group_id="ai_narrative_consumer",
    )
    self._producer = KafkaProducerClient(
        bootstrap_servers=self.settings.kafka_bootstrap_servers,
    )
    await self._consumer.start()
    await self._consumer.skip_lag_if_needed(max_lag=100)
    await self._producer.start()
```

**Main consume loop pattern** (lines 56-68):
```python
async def _run(self) -> None:
    """Main loop: consume records, generate narratives, publish."""
    self.logger.info("ai_narrative_agent.starting")
    assert self._consumer is not None, "_run called before _setup"
    # lag_task created by BaseAgent.start() at line 155
    async for _topic, _key, payload in self._consumer.messages():
        if self._stop_event.is_set():
            break
        try:
            await self._process_bar(payload)
        except Exception as exc:
            self.logger.exception("ai_narrative_agent.consume_error", error=str(exc))
```

---

### `services/indicagent-skeptic-agent.service` (config, systemd-unit)

**Analog:** `services/indicagent-ai-narrative.service`

**Systemd unit pattern** (full file):
```ini
[Unit]
Description=IndicAgent AI Narrative Service — I8 narratives
After=network-online.target indicant-market-analysis.service
Wants=indicant-market-analysis.service
StartLimitIntervalSec=300
StartLimitBurst=5

[Service]
Type=simple
User=bg
WorkingDirectory=/home/bg/dev/indicant
Environment=PYTHONPATH=/home/bg/dev/indicant
Environment=PYTHONUNBUFFERED=1
ExecStart=/home/bg/dev/indicant/.venv/bin/python services/ai_narrative_service.py
Restart=always
RestartSec=10
TimeoutStopSec=75
StandardOutput=journal
StandardError=journal
SyslogIdentifier=indicant-ai-narrative

[Install]
WantedBy=multi-user.target
```

**Key systemd conventions:**
- `After=network-online.target` — wait for network
- `Environment=PYTHONUNBUFFERED=1` — critical for Python logging
- `Restart=always` + `RestartSec=10` — auto-restart on failure
- `SyslogIdentifier` — matches service name for log aggregation

---

### `scripts/validate_skeptic.py` (utility, batch)

**Analog:** `production/scripts/validate_alpha.py`

**Script entry point pattern** (lines 820-863):
```python
def main() -> None:
    parser = argparse.ArgumentParser(
        description="Statistical validation gate for new alpha sources.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--plugin",
        required=True,
        help="Plugin name to validate.",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=90,
        help="Number of days of historical data to query (default: 90)",
    )
    parser.add_argument(
        "--symbol-filter",
        type=str,
        default=None,
        help="Comma-separated symbol filter, e.g. ESH6,NQH6",
    )
    parser.add_argument(
        "--promote",
        action="store_true",
        default=False,
        help="Patch register_plugins.py if gates pass (hard-blocked on failure)",
    )

    args = parser.parse_args()

    symbol_filter: list[str] | None = None
    if args.symbol_filter:
        symbol_filter = [s.strip() for s in args.symbol_filter.split(",") if s.strip()]

    result = asyncio.run(run_validation(
        plugin=args.plugin,
        days=args.days,
        symbol_filter=symbol_filter,
        promote=args.promote,
        field=args.field,
        report_dir=report_dir,
    ))

    # Exit code: 0 = PASS, 1 = FAIL
    if result["verdict"] != "PASS":
        sys.exit(1)
```

**Pearson correlation validation pattern** (lines 302-310):
```python
# Pearson correlation (the gate)
try:
    pearson_r_val, pearson_p_val = pearsonr(all_signals.values, all_returns.values)
    pearson_r = float(pearson_r_val)
    pearson_p = float(pearson_p_val)
except Exception:
    pearson_r = float("nan")
    pearson_p = float("nan")
```

**SQL query pattern for JOIN** (from RESEARCH.md Pattern 3):
```python
query = """
SELECT
    s.predicted_multiplier,
    s.confidence,
    s.features->>'failure_probability' as failure_prob,
    l.outcome,
    l.pnl_r
FROM alpha_multiplier_shadow s
JOIN signal_ledger l ON s.signal_id = l.signal_id
WHERE s.agent_id = 'skeptic_v1'
  AND l.exit_at IS NOT NULL
  AND s.symbol = $1
  AND s.tf = $2
  AND s.hmm_regime = $3
"""
```

---

### `scripts/compute_skeptic_baseline.py` (utility, batch)

**Analog:** `production/scripts/validate_alpha.py`

**DB data fetching pattern** (lines 339-381):
```python
async def _count_qualifying_rows(
    db: DatabaseManager,
    column: str,
    field: str,
    days: int,
    symbol_filter: list[str] | None,
) -> int:
    """Return count of rows where the plugin field is present and non-null."""
    async with db.get_connection() as conn:
        base_sql = f"""
            SELECT COUNT(*)
            FROM intelligence_features
            WHERE ts >= NOW() - INTERVAL '{days} days'
            AND {column} ? $1
            AND ({column}->>$2) IS NOT NULL
            AND ($3::text[] IS NULL OR symbol = ANY($3))
        """
        params: list[Any] = [field, field, symbol_filter]

        return await conn.fetchval(base_sql, *params)


async def _fetch_rows(
    db: DatabaseManager,
    column: str,
    field: str,
    days: int,
    symbol_filter: list[str] | None,
) -> list[tuple[Any, ...]]:
    """Fetch (symbol, tf, ts, close, column_jsonb) rows."""
    async with db.get_connection() as conn:
        base_sql = f"""
            SELECT symbol, tf, ts, (bar->>'close')::float, {column}
            FROM intelligence_features
            WHERE ts >= NOW() - INTERVAL '{days} days'
            AND {column} ? $1
            AND ($2::text[] IS NULL OR symbol = ANY($2))
            ORDER BY symbol, tf, ts
        """
        params: list[Any] = [field, symbol_filter]

        rows = await conn.fetch(base_sql, *params)
        return [tuple(row) for row in rows]
```

**Per-segment aggregation pattern** (lines 232-262):
```python
for (_symbol, tf), group in df.groupby(["symbol", "tf"]):
    group = group.sort_values("ts").reset_index(drop=True)
    n_bars = _n_bars_for_tf(tf, n_bars_by_tf)

    # Forward return: close[t+N]/close[t] - 1, aligned to bar t via shift(-N)
    fwd_return = group["close"].pct_change(n_bars).shift(-n_bars)

    # Signal direction extraction
    field_vals = group[field]

    if signal_type == "binary":
        direction = field_vals.apply(lambda v: 1.0 if v > 0 else 0.0)
    elif signal_type == "zero_cross":
        direction = field_vals.apply(lambda v: 1.0 if v > 0 else (-1.0 if v < 0 else 0.0))

    # Valid mask: forward return is available (include ALL bars, not just signal bars)
    valid_mask = fwd_return.notna() & direction.notna()
    signal_parts.append(direction[valid_mask])
    return_parts.append(fwd_return[valid_mask])
```

---

### `tests/unit/test_skeptic_agent.py` (test, unit)

**Analog:** `tests/unit/service_tests/test_swarm_orchestrator_agent.py`

**`__new__` pattern for service tests** (lines 11-24):
```python
def _make_agent():
    from services.swarm_orchestrator_agent import SwarmOrchestratorComputeAgent
    from src.intelligence.swarm.aggregator import SwarmAggregator
    from src.intelligence.swarm.context import SwarmContextCache

    agent = SwarmOrchestratorComputeAgent.__new__(SwarmOrchestratorComputeAgent)
    agent._context_cache = SwarmContextCache()
    agent._contributors = []
    agent._aggregator = SwarmAggregator()
    agent._producer = MagicMock()
    agent._producer.publish = AsyncMock()
    agent.settings = MagicMock(env_name="test")
    agent.logger = MagicMock()
    return agent
```

**Async test pattern** (lines 27-53):
```python
@pytest.mark.asyncio
async def test_bar_loop_updates_context_cache():
    agent = _make_agent()
    from src.intelligence.schemas import IntelligenceEvent

    event = MagicMock(spec=IntelligenceEvent)
    event.symbol = "ESM6"
    event.tf = "1m"
    event.ts = datetime.now(UTC)
    event.bar = MagicMock()
    event.i1 = MagicMock()
    event.i4 = MagicMock()
    event.i6 = MagicMock()

    await agent._handle_bar(event)

    # Cache should now have an entry for (ESM6, 1m)
    from src.intelligence.schemas import RankedSignal

    sig = MagicMock(spec=RankedSignal)
    sig.plugin = "TrendFollowing"
    sig.direction = 1
    sig.calibrated_confidence = 0.8
    ctx = agent._context_cache.build("ESM6", "1m", sig, uuid4())
    assert ctx is not None
```

**Mock safety pattern** (from CLAUDE.md):
```python
# Always use isinstance checks for mock values
if isinstance(val, (int, float)):
    # safe to use val as number
else:
    # handle MagicMock case
```

---

### `tests/unit/test_skeptic_validation.py` (test, unit)

**Analog:** `tests/unit/test_swarm_protocol.py`

**Validation test pattern** (lines 200-331 from validate_alpha.py):
```python
def _compute_stats(
    df: pd.DataFrame,
    field: str,
    signal_type: str,
    n_bars_by_tf: dict[str, int],
) -> dict[str, Any]:
    """
    Compute all statistics for the validation gate.

    Parameters
    ----------
    df : DataFrame with columns [symbol, timeframe, feature_ts, close, field_value]
    field : The plugin output field name (signal column name in df)
    signal_type : 'binary', 'zero_cross', or 'directional'
    n_bars_by_tf : TF-to-N-bars mapping for forward return window

    Returns
    -------
    dict with all stat fields needed for the report and gates
    """
    # Build signal direction series per (symbol, timeframe) group
    signal_parts = []
    return_parts = []

    for (_symbol, tf), group in df.groupby(["symbol", "tf"]):
        group = group.sort_values("ts").reset_index(drop=True)
        n_bars = _n_bars_for_tf(tf, n_bars_by_tf)

        # Forward return computation
        fwd_return = group["close"].pct_change(n_bars).shift(-n_bars)

        # Signal direction extraction
        field_vals = group[field]

        if signal_type == "binary":
            direction = field_vals.apply(lambda v: 1.0 if v > 0 else 0.0)

        # Valid mask
        valid_mask = fwd_return.notna() & direction.notna()
        signal_parts.append(direction[valid_mask])
        return_parts.append(fwd_return[valid_mask])

    # Compute Pearson correlation
    all_signals = pd.concat(signal_parts)
    all_returns = pd.concat(return_parts)

    try:
        pearson_r_val, pearson_p_val = pearsonr(all_signals.values, all_returns.values)
        pearson_r = float(pearson_r_val)
        pearson_p = float(pearson_p_val)
    except Exception:
        pearson_r = float("nan")
        pearson_p = float("nan")

    return {
        "pearson_r": pearson_r,
        "pearson_pvalue": pearson_p,
        # ... other fields
    }
```

---

## Shared Patterns

### SwarmBaseAgent Subclass Pattern
**Source:** `src/core/swarm/base_agent.py`
**Apply to:** All swarm agents (SkepticAgent)

```python
from src.core.swarm.base_agent import SwarmBaseAgent
from src.intelligence.schemas import AgentResult
from src.intelligence.swarm.context import SwarmContext

class SkepticAgentComputeAgent(SwarmBaseAgent):
    agent_id = "skeptic_v1"
    path = "llm_swarm"
    shadow_only = True
    latency_budget_ms = 5000.0

    def __init__(self, settings, llm_chain: LLMProviderChain):
        super().__init__(name="SkepticAgentComputeAgent")
        self.settings = settings
        self._llm = llm_chain

    async def _compute(self, context: SwarmContext) -> AgentResult:
        # Core computation logic
        # Return AgentResult with multiplier, confidence, shadow_only=True
        pass

    def _neutral(self, error: str, latency_ms: float) -> AgentResult:
        # Already provided by SwarmBaseAgent
        return super()._neutral(error, latency_ms)
```

### LLM Provider Chain Pattern
**Source:** `src/core/llm/chain.py`
**Apply to:** All LLM-powered agents

```python
from src.core.llm.chain import LLMProviderChain
from src.config.settings import Settings

settings = Settings()
llm = LLMProviderChain(
    call_type="skeptic",
    settings=settings,
    cache_ttl=300.0,  # 5 minutes
)

response = await llm.generate(
    prompt="What's wrong with this signal?",
    system="You are a risk analyst. Always respond with valid JSON.",
    max_tokens=500,
    timeout=5.0,
)
```

### ShadowRecorder Batch Write Pattern
**Source:** `src/core/ml/shadow.py`
**Apply to:** All swarm agents recording predictions

```python
from src.core.ml.shadow import ShadowRecorder
import asyncpg

# In agent _setup():
pool = await asyncpg.create_pool(settings.database_url, min_size=1, max_size=5)
self._recorder = ShadowRecorder(pool, batch_size=100, flush_interval_s=2.0)

# In _compute() after building AgentResult:
await self._recorder.record(
    signal_id=context.signal_id,
    agent_id=self.agent_id,
    multiplier=result.multiplier,
    confidence=result.confidence,
    symbol=context.symbol,
    tf=context.timeframe,
    regime=context.hmm_regime,
    path=self.path,
    features=result.metadata,  # Stores prompt_version, risk_factors, etc.
)

# In _teardown():
await self._recorder.flush()
```

### SafeSwarmWrapper Timeout Pattern
**Source:** `src/intelligence/swarm/safety.py`
**Apply to:** All swarm agents that need timeout protection

```python
from src.intelligence.swarm.safety import SafeSwarmWrapper

# Wrap contributors in SafeSwarmWrapper
self._contributors = [SafeSwarmWrapper(c) for c in contributors]

# Run with timeout + exception isolation
result = await wrapper.run(context)  # Returns neutral on timeout/exception
```

### Kafka Consumer Loop Pattern
**Source:** `services/swarm_orchestrator_agent.py`
**Apply to:** All Kafka consumer services

```python
async def _run(self) -> None:
    self.logger.info("service.starting")
    assert self._consumer is not None, "_run called before _setup"
    async for _topic, _key, payload in self._consumer.messages():
        if self._stop_event.is_set():
            break
        try:
            await self._process_payload(payload)
        except Exception as exc:
            self.logger.exception("service.process_error", error=str(exc))
```

### Systemd Unit Pattern
**Source:** `services/indicagent-ai-narrative.service`
**Apply to:** All systemd service units

```ini
[Unit]
Description=IndicAgent Service Name
After=network-online.target
StartLimitIntervalSec=300
StartLimitBurst=5

[Service]
Type=simple
User=bg
WorkingDirectory=/home/bg/dev/indicant
Environment=PYTHONPATH=/home/bg/dev/indicant
Environment=PYTHONUNBUFFERED=1
ExecStart=/home/bg/dev/indicant/.venv/bin/python services/service_name.py
Restart=always
RestartSec=10
TimeoutStopSec=75
StandardOutput=journal
StandardError=journal
SyslogIdentifier=indicant-service-name

[Install]
WantedBy=multi-user.target
```

### Test `__new__` Pattern
**Source:** `tests/unit/service_tests/test_swarm_orchestrator_agent.py`
**Apply to:** All service tests

```python
def _make_agent():
    from services.service_name import ServiceClass

    agent = ServiceClass.__new__(ServiceClass)
    agent._attribute1 = MagicMock()
    agent._attribute2 = AsyncMock()
    agent.settings = MagicMock(env_name="test")
    agent.logger = MagicMock()
    return agent
```

## No Analog Found

Files with no close match in the codebase (planner should use RESEARCH.md patterns instead):

| File | Role | Data Flow | Reason |
|------|------|-----------|--------|
| None | — | — | All files have strong analogs in existing codebase |

## Metadata

**Analog search scope:** services/, src/intelligence/swarm/, src/intelligence/narrative/, production/scripts/, tests/unit/
**Files scanned:** 12
**Pattern extraction date:** 2026-04-24

## Key Architectural Insights

1. **SwarmOrchestratorComputeAgent** is the perfect analog for SkepticAgent — both consume from `intelligence.i7.signals`, both use SwarmContextCache, both publish results.
2. **AINarrativeComputeAgent** shows the thin Kafka wrapper pattern for LLM-powered services.
3. **validate_alpha.py** provides the complete statistical validation pattern (Pearson correlation, N≥30 gates, per-segment analysis).
4. **SwarmBaseAgent** (from Phase 56) provides timeout, exception safety, OTel spans, and neutral fallback — no need to re-implement.
5. **Prompt versioning** should follow the narrative prompts.py pattern — module-level registry with version IDs.
