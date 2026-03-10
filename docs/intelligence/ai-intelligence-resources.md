# AI Intelligence Resources & Implementation Guide

**Version:** 2.2.0  
**Last Updated:** 2026-02-12  
**Status:** Implementation resources — I1-I5 operational; resources support I6-I8 and hybrid architecture

## Purpose

Comprehensive resource collection for implementing AI intelligence capabilities in IndicAgent. Includes runnable examples, external references, research concepts, and practical implementation patterns focused on market intelligence extraction.

---

##  Intelligence Service Architecture

### **Docker Compose Intelligence Services**
```bash
# Add AI intelligence services to existing docker-compose.yml
services:
  ai-intelligence-runtime:
    build: ./src/intelligence/ai
    environment:
      - DATABASE_URL=postgresql://postgres:postgres@timescaledb:5432/indicagent
      - REDIS_URL=redis://dragonfly:6379/0
      - OPENROUTER_API_KEY=${OPENROUTER_API_KEY}
      - INDICAGENT_ENV=${INDICAGENT_ENV:-development}
    volumes:
      - ./config/intelligence:/app/config
    depends_on:
      - timescaledb
      - dragonfly
    ports:
      - "9111:9111"  # Health endpoint for AI intelligence service
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:9111/health"]
      interval: 30s
      timeout: 10s
      retries: 3
    restart: unless-stopped
    
  intelligence-pattern-analyzer:
    build: ./src/intelligence/pattern_analyzer  
    environment:
      - DATABASE_URL=postgresql://postgres:postgres@timescaledb:5432/indicagent
      - REDIS_URL=redis://dragonfly:6379/0
      - INDICAGENT_ENV=${INDICAGENT_ENV:-development}
    depends_on:
      - ai-intelligence-runtime
    ports:
      - "9112:9112"  # Health endpoint for pattern analyzer service  
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:9112/health"]
      interval: 30s
      timeout: 10s
      retries: 3
    restart: unless-stopped
```

---

##  Intelligence Agent Implementation Examples
### Reference Payloads (Contracts)

These examples support the ideas doc; use canonical streams and build keys with `src/core/stream_keys.py` (env prefix from `INDICAGENT_ENV`).

#### insight.v1 (pattern explanation)
```json
{
  "type": "insight.v1",
  "schema_version": "1.0.0",
  "symbol": "ES",
  "timeframe": "15m",
  "timestamp": "2025-08-10T14:30:00Z",
  "intelligence_tier": "I8",
  "insight_type": "pattern_explanation",
  "summary": "Bullish MACD divergence with volume confirmation",
  "narrative": "MACD formed higher lows while price made lower lows; volume increased on confirmation bar.",
  "key_factors": ["macd_divergence", "volume_above_avg", "support_touch"],
  "confidence": 0.82,
  "evidence_sources": ["I5_macd_divergence", "I2_volume_composite"],
  "actionable_intelligence": {"invalidates_below": 4501.0, "targets": [4515.0, 4525.0]},
  "source": "ai_pattern_narrative_v1"
}
```

#### composite.v1 (multi-factor confluence)
```json
{
  "type": "composite.v1",
  "schema_version": "1.0.0",
  "symbol": "ES",
  "timeframe": "15m",
  "timestamp": "2025-08-10T14:30:00Z",
  "intelligence_tier": "I6",
  "composite_type": "multi_factor_confluence",
  "values": {"confluence_score": 0.76, "factors": ["macd_divergence", "rsi_regime", "volume_trend"]},
  "rationale": "Agreement across MACD, RSI trend, and volume confirmation",
  "source": "ai_confluence_ranker_v1"
}
```

#### insight.v1 (counterfactual requirements)
```json
{
  "type": "insight.v1",
  "schema_version": "1.0.0",
  "symbol": "ES",
  "timeframe": "1h",
  "intelligence_tier": "I8",
  "insight_type": "counterfactual_requirements",
  "summary": "Requirements to validate bullish setup",
  "required_changes": [
    {"metric": "rsi_14", "delta": "+3.5", "target": ">= 55"},
    {"metric": "volume_sma_20", "delta": "+10%", "target": "> avg"}
  ],
  "monitoring_triggers": ["close_above_4512", "rsi_slope_positive"]
}
```


### **Pattern Intelligence Agent**
```python
# src/intelligence/agents/pattern_intelligence_agent.py
class PatternIntelligenceAgent:
    """Core pattern recognition intelligence agent"""
    
    def __init__(self, config: IntelligenceConfig):
        self.config = config
        self.db_manager = DatabaseManager()
        self.redis_streams = RedisStreamsManager()
        self.llm_client = OpenRouterClient()
        
    async def analyze_pattern(self, symbol: str, timeframe: str, 
                             market_data: Dict) -> PatternIntelligence:
        """Generate pattern intelligence from market data"""
        
        # Extract technical patterns
        technical_patterns = await self._identify_technical_patterns(
            symbol, timeframe, market_data
        )
        
        # Generate AI intelligence analysis
        intelligence_analysis = await self._generate_pattern_intelligence(
            technical_patterns, market_data
        )
        
        # Validate and score confidence
        confidence_score = await self._calculate_pattern_confidence(
            technical_patterns, intelligence_analysis
        )
        
        return PatternIntelligence(
            symbol=symbol,
            timeframe=timeframe,
            patterns=technical_patterns,
            intelligence=intelligence_analysis,
            confidence=confidence_score,
            timestamp=datetime.utcnow()
        )
    
    async def _generate_pattern_intelligence(self, patterns: Dict, 
                                           market_data: Dict) -> str:
        """Use AI to interpret technical patterns"""
        
        prompt = self._build_pattern_analysis_prompt(patterns, market_data)
        
        response = await self.llm_client.generate(
            prompt=prompt,
            temperature=0.3,
            max_tokens=500,
            model_preference="analysis"  # Use analytical model
        )
        
        return self._parse_intelligence_response(response)
    
    def _build_pattern_analysis_prompt(self, patterns: Dict, 
                                     market_data: Dict) -> str:
        """Build specialized prompt for pattern intelligence"""
        return f"""
        Analyze the following technical patterns for market intelligence:
        
        Symbol: {market_data['symbol']}
        Timeframe: {market_data['timeframe']}
        Current Price: ${market_data['close']:.2f}
        
        Technical Patterns Detected:
        {json.dumps(patterns, indent=2)}
        
        Market Context:
        - Volume: {market_data.get('volume', 'N/A')}
        - ATR: {market_data.get('atr', 'N/A')}
        - Trend: {market_data.get('trend', 'N/A')}
        
        Provide concise market intelligence analysis focusing on:
        1. Pattern strength and reliability
        2. Multi-timeframe implications
        3. Volume confirmation or divergence
        4. Risk considerations
        5. Key levels to monitor
        
        Respond with structured intelligence in JSON format.
        """
```

### **Smart Money Intelligence Agent**
```python
# src/intelligence/agents/smart_money_intelligence_agent.py
class SmartMoneyIntelligenceAgent:
    """Institutional flow and liquidity intelligence analysis"""
    
    async def analyze_institutional_flow(self, symbol: str, 
                                       timeframe: str) -> SmartMoneyIntelligence:
        """Analyze institutional trading patterns"""
        
        # Volume profile analysis
        volume_intelligence = await self._analyze_volume_profile(symbol, timeframe)
        
        # Liquidity analysis
        liquidity_intelligence = await self._analyze_liquidity_patterns(
            symbol, timeframe
        )
        
        # Order flow analysis
        order_flow_intelligence = await self._analyze_order_flow(symbol, timeframe)
        
        # Generate AI interpretation
        ai_analysis = await self._generate_smart_money_intelligence(
            volume_intelligence, liquidity_intelligence, order_flow_intelligence
        )
        
        return SmartMoneyIntelligence(
            symbol=symbol,
            timeframe=timeframe,
            volume_intelligence=volume_intelligence,
            liquidity_analysis=liquidity_intelligence,
            order_flow_analysis=order_flow_intelligence,
            ai_interpretation=ai_analysis,
            confidence=self._calculate_smart_money_confidence(
                volume_intelligence, liquidity_intelligence
            )
        )
    
    def _build_smart_money_prompt(self, volume_data: Dict, 
                                 liquidity_data: Dict) -> str:
        """Build prompt for institutional flow analysis"""
        return f"""
        Analyze the following institutional flow patterns:
        
        Volume Profile Intelligence:
        {json.dumps(volume_data, indent=2)}
        
        Liquidity Analysis:  
        {json.dumps(liquidity_data, indent=2)}
        
        Provide market intelligence focusing on:
        1. Institutional accumulation/distribution signals
        2. Large player positioning and bias
        3. Liquidity sweep and fair value gap implications
        4. Market maker behavior patterns
        5. Smart money directional bias
        
        Respond with actionable intelligence in structured format.
        """
```

---

##  Intelligence Orchestration Patterns

### **Multi-Agent Intelligence Coordinator**
```python
# src/intelligence/orchestration/intelligence_coordinator.py
class IntelligenceCoordinator:
    """Coordinates multiple intelligence agents for comprehensive analysis"""
    
    def __init__(self):
        self.pattern_agent = PatternIntelligenceAgent()
        self.smart_money_agent = SmartMoneyIntelligenceAgent()
        self.market_context_agent = MarketContextIntelligenceAgent()
        self.confluence_agent = ConfluenceIntelligenceAgent()
        
    async def generate_comprehensive_intelligence(self, symbol: str, 
                                                timeframe: str) -> ComprehensiveIntelligence:
        """Generate multi-factor market intelligence"""
        
        # Run intelligence agents in parallel
        tasks = [
            self.pattern_agent.analyze_pattern(symbol, timeframe),
            self.smart_money_agent.analyze_institutional_flow(symbol, timeframe),
            self.market_context_agent.analyze_market_context(symbol, timeframe)
        ]
        
        pattern_intel, smart_money_intel, context_intel = await asyncio.gather(*tasks)
        
        # Synthesize intelligence through confluence agent
        confluence_intel = await self.confluence_agent.synthesize_intelligence(
            pattern_intelligence=pattern_intel,
            smart_money_intelligence=smart_money_intel,
            market_context=context_intel
        )
        
        return ComprehensiveIntelligence(
            symbol=symbol,
            timeframe=timeframe,
            pattern_intelligence=pattern_intel,
            smart_money_intelligence=smart_money_intel,
            market_context_intelligence=context_intel,
            confluence_intelligence=confluence_intel,
            overall_confidence=confluence_intel.confidence,
            timestamp=datetime.utcnow()
        )
```

### **Intelligence Stream Distribution**
```python
# src/intelligence/distribution/intelligence_publisher.py
class IntelligencePublisher:
    """Publish intelligence to Redis streams for real-time distribution"""
    
    async def publish_intelligence(self, intelligence: ComprehensiveIntelligence):
        """Publish intelligence to appropriate streams"""
        
        # Use stream key helpers instead of manual construction
        from src.core.stream_keys import patterns as sk_patterns, smart_money as sk_smart_money, confluence as sk_confluence
        
        streams_to_publish = [
            (sk_patterns(self.env_prefix, intelligence.symbol, intelligence.timeframe),
             intelligence.pattern_intelligence.to_dict()),
            
            (sk_smart_money(self.env_prefix, intelligence.symbol, intelligence.timeframe),
             intelligence.smart_money_intelligence.to_dict()),
             
            (sk_confluence(self.env_prefix, intelligence.symbol, intelligence.timeframe),
             intelligence.confluence_intelligence.to_dict())
        ]
        
        # Publish to all streams concurrently
        await asyncio.gather(*[
            self.redis_streams.publish_to_stream(stream, data)
            for stream, data in streams_to_publish
        ])
```

---

##  External Intelligence Resources
## Data Storage References

### insight_memory (pgvector) schema
```sql
CREATE TABLE insight_memory (
  id UUID PRIMARY KEY,
  timestamp TIMESTAMPTZ NOT NULL,
  symbol TEXT NOT NULL,
  timeframe TEXT NOT NULL,
  tier TEXT NOT NULL,            -- I4/I5/I6/I8
  insight_type TEXT NOT NULL,    -- pattern_explanation, counterfactual_requirements, daily_intelligence_brief, etc.
  summary TEXT NOT NULL,
  narrative TEXT,
  metadata JSONB,
  embedding VECTOR(1536)
);
CREATE INDEX ON insight_memory USING ivfflat (embedding vector_cosine_ops);
```


### **AI & Machine Learning References**
- **LangGraph:** https://github.com/langchain-ai/langgraph - Multi-agent workflow orchestration
- **LiteLLM:** https://github.com/BerriAI/litellm - Unified LLM interface  
- **OpenRouter:** https://openrouter.ai/docs - Multi-model LLM API
- **Mixture of Agents:** https://arxiv.org/abs/2406.04692 - Multi-agent synthesis patterns

### **Market Intelligence Resources**
- **Order Flow Analysis:** Institutional trading pattern recognition
- **Volume Profile Intelligence:** Large player positioning analysis
- **Market Microstructure:** Liquidity and market maker behavior
- **Technical Pattern Recognition:** Advanced pattern validation techniques

### **Implementation Patterns**
- **Agentic Workflows:** Orchestrator-worker, parallel processing, intelligent routing
- **MCP Integration:** Model Context Protocol for tool integration
- **Circuit Breaker Patterns:** Resilient AI service architecture
- **Confidence Calibration:** Intelligence quality scoring and validation

---

##  Research & Innovation Concepts

### **Advanced Intelligence Concepts**
- **Pattern Evolution Intelligence:** Tracking how patterns change over market cycles
- **Cross-Asset Intelligence:** Multi-market correlation and flow analysis
- **Sentiment Intelligence Integration:** Social sentiment and positioning data
- **Predictive Intelligence:** Uncertainty quantification and probability modeling

### **Experimental Intelligence Features**
- **Market Narrative Generation:** AI-powered market story and context
- **Intelligence Explanation:** Why certain patterns are significant now
- **Dynamic Model Selection:** Choosing optimal models based on market conditions
- **Intelligence Personalization:** Tailored analysis based on user preferences

### **Future Intelligence Capabilities**
- **Real-time Intelligence Adaptation:** Dynamic strategy adjustment
- **Meta-Intelligence Learning:** Learning how to learn from market data
- **Intelligence Quality Evolution:** Continuous improvement of analysis quality
- **Collaborative Intelligence:** Human-AI collaborative analysis workflows

---

##  Implementation Best Practices

### **Intelligence Quality Assurance**
- Always validate intelligence with confidence scoring
- Implement multi-timeframe consistency checks
- Track historical performance of intelligence outputs
- Use circuit breakers for model failures and degradation

### **Performance Optimization**
- Cache frequently analyzed patterns and contexts
- Use model pooling for concurrent intelligence generation
- Implement intelligent batching for multiple timeframe analysis
- Monitor and optimize intelligence generation latency

### **Intelligence Distribution**
- Use Redis streams for real-time intelligence broadcasting
- Implement intelligence versioning for model updates
- Provide fallback intelligence for model failures
- Maintain intelligence audit trails for quality tracking

This resource guide provides the foundation for implementing sophisticated AI intelligence capabilities while maintaining focus on market analysis and insights generation.