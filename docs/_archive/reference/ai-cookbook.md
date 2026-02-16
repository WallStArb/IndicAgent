# AI Cookbook — Runnable Examples

Version: 1.0.0  
Last Updated: 2025-08-10  
Status: Current 

## Purpose

Central home for runnable/reference code snippets mentioned in planning docs. Keeps the roadmap focused on contracts while preserving working examples.

---

## Service Architecture Setup

```bash
# Add AI service to existing docker-compose.yml
services:
  ai-agent-runtime:
    build: ./src/ai
    environment:
      - DATABASE_URL=postgresql://postgres:postgres@timescaledb:5432/indicagent
      - REDIS_URL=redis://dragonfly:6379/0
      - OPENROUTER_API_KEY=${OPENROUTER_API_KEY}
    volumes:
      - ./config/ai:/app/config
    depends_on:
      - timescaledb
      - dragonfly
    restart: unless-stopped
```

---

## Core Components Implementation

```python
# src/ai/agent_runtime_service.py
class AIAgentRuntimeService:
    """Core AI agent runtime service following IndicAgent patterns"""
    
    def __init__(self):
        self.config = self.load_config("config/ai/agent_runtime_service.json")
        self.db_manager = DatabaseManager()  # Existing IndicAgent component
        self.redis_streams = RedisStreamsManager()  # Existing component
        self.agents = {}
        
    async def start(self):
        """Start AI agent runtime service"""
        await self.initialize_database_schema()
        await self.register_agents()
        await self.start_stream_consumers()
        await self.start_health_monitoring()
        
    async def register_agents(self):
        """Register available AI agents"""
        self.agents = {
            "pattern_analysis": PatternAnalysisAgent(self.config["agents"]["pattern_analysis"]),
            "market_context": MarketContextAgent(self.config["agents"]["market_context"]),
            "risk_assessment": RiskAssessmentAgent(self.config["agents"]["risk_assessment"])
        }
```

---

## Database Schema Extension

```sql
-- AI Analysis Results (hypertable for time-series data)
CREATE TABLE ai_analysis_results (
    id SERIAL PRIMARY KEY,
    timestamp TIMESTAMPTZ NOT NULL,
    symbol TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    agent_type TEXT NOT NULL,
    analysis_type TEXT NOT NULL,
    confidence DECIMAL(5,4) NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
    reasoning JSONB NOT NULL,
    metadata JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

SELECT create_hypertable('ai_analysis_results', 'timestamp');

-- Agent Performance Tracking
CREATE TABLE agent_performance (
    id SERIAL PRIMARY KEY,
    timestamp TIMESTAMPTZ NOT NULL,
    agent_id TEXT NOT NULL,
    performance_metrics JSONB NOT NULL,
    resource_usage JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

SELECT create_hypertable('agent_performance', 'timestamp');
```

---

## Redis Streams Integration

```python
class AIStreamProcessor:
    """Process existing IndicAgent streams and publish AI intelligence"""
    
    async def start_stream_processing(self):
        """Start consuming existing streams and publishing AI results"""
        
        # Consume existing streams
        stream_consumers = [
            self.consume_market_data_stream(),
            self.consume_indicators_stream(),
            self.consume_patterns_stream()
        ]
        
        await asyncio.gather(*stream_consumers)
    
    async def consume_market_data_stream(self):
        """Consume market:SYMBOL:TIMEFRAME streams"""
        async for message in self.redis_streams.read_stream("market:*:*"):
            symbol = message["symbol"]
            timeframe = message["timeframe"] 
            market_data = message["data"]
            
            # Process with AI agents
            ai_analysis = await self.process_with_agents(symbol, timeframe, market_data)
            
            # Publish to AI intelligence stream
            await self.redis_streams.publish_stream(
                f"intelligence:{symbol}:{timeframe}",
                ai_analysis
            )
```

---

## Prometheus Metrics Integration

```python
from prometheus_client import Counter, Histogram, Gauge

# AI-specific metrics extending existing IndicAgent metrics
ai_requests_total = Counter(
    'ai_requests_total',
    'Total AI analysis requests',
    ['agent_type', 'symbol', 'timeframe']
)

ai_request_duration = Histogram(
    'ai_request_duration_seconds', 
    'Time spent processing AI requests',
    ['agent_type', 'analysis_type']
)

ai_confidence_score = Gauge(
    'ai_confidence_score',
    'AI analysis confidence scores', 
    ['agent_type', 'symbol', 'timeframe']
)
```

---

## Health Monitoring

```python
class AIHealthMonitor:
    """Health monitoring for AI services"""
    
    async def health_check(self) -> Dict[str, Any]:
        """Comprehensive health check"""
        health_status = {
            "service": "ai-agent-runtime",
            "status": "healthy",
            "timestamp": datetime.utcnow().isoformat(),
            "components": {}
        }
        # DB & Redis checks omitted for brevity
        return health_status
```

---

## LangGraph Workflow Skeleton

```python
from langgraph import StateGraph
from typing import TypedDict

class TradingIntelligenceState(TypedDict):
    symbol: str
    timeframe: str
    market_data: Dict
    agent_analyses: Dict[str, Any]
    confluence_score: float
    final_signal: Optional[TradingSignal]

async def create_trading_intelligence_workflow():
    workflow = StateGraph(TradingIntelligenceState)
    workflow.add_node("pattern_analysis", process_pattern_analysis)
    workflow.add_node("market_context", process_market_context)
    workflow.add_node("risk_assessment", process_risk_assessment)
    workflow.add_node("confluence_synthesis", synthesize_confluence)
    workflow.add_node("signal_generation", generate_final_signal)
    return workflow.compile(parallel_execution=True)
```

---

## Real-Time Workflow Processing (Excerpt)

```python
class WorkflowProcessor:
    async def process_market_event(self, event: MarketEvent):
        initial_state = TradingIntelligenceState(
            symbol=event.symbol,
            timeframe=event.timeframe,
            market_data=event.data,
            agent_analyses={},
            confluence_score=0.0,
            final_signal=None,
        )
        result = await asyncio.wait_for(self.workflow.ainvoke(initial_state), timeout=25.0)
        await self.publish_intelligence_result(result)
        return result
```

---

Notes
- Replace raw stream names with helpers from `src/core/stream_keys.py` in production.
- Use `src/config/Settings` for configuration values.
- Emit Prometheus/OTel metrics around each node and external call.

