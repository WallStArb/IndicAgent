# Hybrid Intelligence Architecture: Service-Plugin Integration

**Version:** 3.2.0
**Last Updated:** 2026-02-12
**Status:** HISTORICAL REFERENCE — PI-1 completed, I1-I5 operational (22 plugins). Some file references below refer to code since deleted. See [`docs/current-status-and-priorities.md`](../current-status-and-priorities.md) for current state.

## Executive Summary

This document outlines the **Hybrid Intelligence Architecture** that resolves the conflict between existing production services and sophisticated plugin framework by integrating plugins INTO services rather than replacing them.

**Key Decision:** Preserve working production services (141x performance) while integrating plugin framework for advanced intelligence tiers (I2-I8). This provides the best of both worlds - performance AND extensibility.

**Architecture Principle:** Service-Plugin Bridge Pattern - Services coordinate both direct calculations and plugin execution based on intelligence tier requirements.

---

## Current Intelligence Infrastructure (Already Implemented)

### **Existing Plugin Framework (Operational)**

**Core Components:**
- `src/intelligence/plugins.py` - Plugin registry with `IndicatorPlugin` and `PatternPlugin` protocols (in use)
- `src/intelligence/dag.py` - DAG execution engine with topological sorting (present; plugin order is currently fixed I1→I3→I4→I5 in `intelligence_processor_service`, so DAG is not yet wired in)
- `src/intelligence/contracts.py` - Intelligence data contracts (in use by `unified_market_processor` and stream schemas)
- **Removed (Tier 2 refactor):** `executor.py`, `shadow_runner.py`, `join.py` — deleted in cleanup; plugin execution is now done directly in `intelligence_processor_service` and via LangGraph in `langgraph_event_processor.py` / `langgraph_integration.py`. No separate executor or shadow-runner modules.

**Plugin Implementation:**
- `src/intelligence/indicators/` - 12 indicator plugins (RSI, MACD, SMA, EMA, etc.)
- `src/intelligence/composites/` - Composite indicator framework
- Plugin registration system with capability tags
- Incremental computation support

**Documentation:**
- `/docs/architecture/plugin-registry-and-dag-execution.md` - Complete framework specification

### **Current Limitations**

**1. Service Integration Gap (partially addressed):**
- Plugin framework is integrated via `intelligence_processor_service.py` (I3/I4/I5). `indicators_processor_service.py` remains service-based for I1.
- Historical: two parallel approaches (service-based I1 vs plugin-based I3/I4/I5) are now coordinated.

**2. Limited Flexibility:**
- Hard-coded intelligence tier assumptions (I1-I8 linear progression)
- Static service architecture not leveraging dynamic plugin capabilities
- No runtime reconfiguration of intelligence pipelines

**3. Extensibility Constraints:**
- Plugin framework ready but not production-integrated
- Limited support for custom intelligence workflows
- No configuration-driven pipeline composition

---

## Hybrid Architecture: Service-Plugin Integration

### **Core Principle: Service-Plugin Bridge Pattern**

Instead of replacing working services, integrate plugin framework INTO existing services based on intelligence tier characteristics and performance requirements.

### **Hybrid Architecture Overview**

```
┌─────────────────────────────────────────────────────┐
│                Service Layer                         │
│  ┌─────────────────────┐  ┌─────────────────────────┐ │
│  │ Indicator Processor │  │ Pattern Detection       │ │
│  │ Service (Enhanced)  │  │ Service (NEW)           │ │
│  │ ┌─────────────────┐ │  │ ┌─────────────────────┐ │ │
│  │ │I1: Direct Calc  │ │  │ │I5-I7: Plugin Native │ │ │
│  │ │(Performance)    │ │  │ │(Flexibility)        │ │ │
│  │ └─────────────────┘ │  │ └─────────────────────┘ │ │
│  │ ┌─────────────────┐ │  │                         │ │
│  │ │I2-I4: Hybrid    │ │  │                         │ │
│  │ │Bridge Pattern   │ │  │                         │ │
│  │ └─────────────────┘ │  │                         │ │
│  └─────────────────────┘  └─────────────────────────┘ │
└─────────────────────────────────────────────────────┘
┌─────────────────────────────────────────────────────┐
│              Plugin Framework (Existing)            │
│  Plugin Registry • DAG Execution • Shadow Runner    │
│  State Management • Event Sourcing • Contracts      │
└─────────────────────────────────────────────────────┘
┌─────────────────────────────────────────────────────┐
│              Configuration Engine (NEW)             │
│  YAML Pipelines • Dynamic Composition • Routing     │
└─────────────────────────────────────────────────────┘
```

## Hybrid Implementation Strategy

### **Intelligence Tier Allocation**

**I1 Technical Indicators (Production Direct Calculation)**
- **Service:** `indicators_processor_service.py` / `indicators_enhanced_service.py` (existing)
- **Method:** Direct calculation via `IndicatorCalculations` (141x performance)  
- **Reason:** Maximum performance for real-time indicator computation
- **Examples:** RSI, MACD, SMA, EMA, Bollinger Bands, ATR

**I2-I4 Composite Intelligence (Hybrid Bridge)**
- **Service:** `intelligence_processor_service.py` (I2 composites, I3 structure, I4 context plugins)
- **Method:** Plugin integration for composite calculations
- **Reason:** Leverage plugin flexibility for composite indicators while maintaining service reliability
- **Examples:** MA crossovers, momentum combinations, market structure, regime detection

**I5-I7 Pattern Intelligence (Plugin Native)**
- **Service:** `pattern_detection_service.py` (NEW)
- **Method:** Pure plugin framework execution
- **Reason:** Patterns are inherently plugin-native and benefit from DAG execution
- **Examples:** MACD/RSI divergence, Bollinger squeeze, FVG, liquidity sweeps

**I8 AI Intelligence (Future Service)**  
- **Service:** `ai_intelligence_service.py` (future implementation)
- **Method:** LLM integration with plugin framework
- **Reason:** AI synthesis requires specialized service with cost controls

### **1. Enhanced Service-Plugin Integration**

**Bridge Pattern Implementation:**

```python
# Enhanced indicator service with plugin integration
class HybridIndicatorProcessor:
    def __init__(self):
        self.direct_calculator = IndicatorCalculations()  # I1 performance
        self.plugin_registry = PluginRegistry()           # I2-I4 flexibility
        self.config = IntelligenceConfig.load()           # YAML configuration
    
    async def process_bar(self, bar_data):
        results = {}
        
        # I1: Direct high-performance calculation
        if self.config.enable_direct_indicators:
            i1_results = self.direct_calculator.calculate_all(bar_data)
            results.update(i1_results)
        
        # I2-I4: Plugin-based composite indicators  
        if self.config.enable_composite_plugins:
            composite_plugins = self.plugin_registry.get_tier_plugins(['I2', 'I3', 'I4'])
            i2_4_results = await self.execute_plugins(composite_plugins, bar_data)
            results.update(i2_4_results)
        
        return results
```
    processing_mode: ClassVar[ProcessingMode]  # REAL_TIME, BATCH, EVENT_DRIVEN
    resource_requirements: ClassVar[ResourceRequirements]
    cost_model: ClassVar[CostModel]  # FREE, PER_CALCULATION, PER_TOKEN
    
    # Stream-native processing
    async def process_stream(self, input_streams: Dict[str, AsyncIterator]) -> AsyncIterator:
        """Stream-native processing for real-time intelligence"""
    
    # Configuration-driven processing
    def configure(self, config: Dict[str, Any]) -> None:
        """Runtime configuration of plugin behavior"""
```

**Plugin Categories (Extensible):**

```python
class PluginCategory(Enum):
    # Mathematical Intelligence (I1-I4)
    TECHNICAL_INDICATOR = "technical_indicator"    # RSI, MACD, SMA
    COMPOSITE_INDICATOR = "composite_indicator"    # MA crossovers, momentum combinations
    MARKET_STRUCTURE = "market_structure"         # Swing analysis, support/resistance
    REGIME_DETECTION = "regime_detection"         # Bull/bear classification
    
    # Pattern Intelligence (I5-I7)
    PATTERN_RECOGNITION = "pattern_recognition"   # Divergence, breakouts
    CONFLUENCE_ANALYSIS = "confluence_analysis"   # Multi-factor validation
    SMART_MONEY = "smart_money"                   # FVG, liquidity analysis
    
    # AI Intelligence (I8)
    AI_SYNTHESIS = "ai_synthesis"                 # LLM integration
    MARKET_NARRATIVE = "market_narrative"         # Human-readable insights
    
    # Extensible Categories (Future)
    SENTIMENT_ANALYSIS = "sentiment_analysis"     # News/social sentiment
    ALTERNATIVE_DATA = "alternative_data"         # Options flow, institutional data
    CROSS_ASSET = "cross_asset"                   # Multi-asset correlation
```

### **2. Configuration-Driven Intelligence Pipelines**

**Intelligence Pipeline Configuration:**

```yaml
# config/intelligence-pipelines.yaml
pipelines:
  basic_analysis:
    name: "Basic Technical Analysis"
    description: "I1-I4 mathematical intelligence for all instruments"
    enabled: true
    instruments: ["ES", "NQ", "RTY"]
    timeframes: ["1m", "5m", "15m", "1h", "4h", "1d"]
    plugins:
      # I1 Technical Indicators
      - plugin: "rsi_14"
        config: {"period": 14, "overbought": 70, "oversold": 30}
      - plugin: "macd_standard" 
        config: {"fast": 12, "slow": 26, "signal": 9}
      - plugin: "sma_20_50"
        config: {"periods": [20, 50]}
      - plugin: "bollinger_bands"
        config: {"period": 20, "std_dev": 2.0}
      
      # I2 Composite Indicators  
      - plugin: "ma_crossover"
        dependencies: ["sma_20_50"]
        config: {"fast_period": 20, "slow_period": 50}
      - plugin: "momentum_confluence"
        dependencies: ["rsi_14", "macd_standard"]
        
      # I3 Market Structure
      - plugin: "swing_detector"
        dependencies: ["bollinger_bands"]
        config: {"swing_threshold": 0.5}
        
      # I4 Regime Detection
      - plugin: "trend_regime"
        dependencies: ["ma_crossover", "swing_detector"]
    
    output_streams:
      - "features:SYMBOL:TIMEFRAME"     # I1 outputs
      - "composite:SYMBOL:TIMEFRAME"    # I2-I4 outputs

  advanced_patterns:
    name: "Advanced Pattern Recognition"
    description: "I5-I7 pattern intelligence for high-confidence setups"
    enabled: true
    instruments: ["ES", "NQ"]  # Limited to liquid instruments
    timeframes: ["5m", "15m", "1h", "4h"]
    triggers:
      - pattern: "composite:*:confidence>0.7"  # Only process high-confidence signals
      - pattern: "features:*:rsi_divergence"   # RSI divergence detected
    plugins:
      # I5 Pattern Recognition
      - plugin: "macd_divergence"
        dependencies: ["basic_analysis"]
        config: {"min_bars": 10, "max_bars": 50}
      - plugin: "smart_money_fvg"
        dependencies: ["basic_analysis"]
        config: {"min_gap_size": 0.25}
        
      # I6 Confluence Analysis
      - plugin: "multi_timeframe_confluence"
        dependencies: ["macd_divergence", "smart_money_fvg"]
        config: {"required_timeframes": 2}
        
      # I7 Intelligence Outputs
      - plugin: "setup_validator" 
        dependencies: ["multi_timeframe_confluence"]
        config: {"min_confluence_score": 0.8}
    
    output_streams:
      - "patterns:SYMBOL:TIMEFRAME"     # I5-I7 outputs

  ai_insights:
    name: "AI-Powered Market Intelligence"
    description: "I8 AI synthesis for human-readable insights"
    enabled: true
    cost_controls:
      max_monthly_cost: 50.00  # USD
      batch_size: 5
      cooldown_minutes: 15
    triggers:
      - pattern: "patterns:*:confidence>0.85"  # Only high-confidence patterns
      - schedule: "0 */4 * * *"  # Every 4 hours for market narrative
    plugins:
      # I8 AI Synthesis
      - plugin: "pattern_interpreter"
        dependencies: ["advanced_patterns"]
        config: 
          model: "deepseek/deepseek-r1:free@chutes"
          max_tokens: 200
          temperature: 0.3
      - plugin: "market_narrative"
        dependencies: ["basic_analysis", "advanced_patterns"]
        config:
          model: "qwen/qwen3-14b:free@chutes" 
          max_tokens: 500
          temperature: 0.5
    
    output_streams:
      - "insights:SYMBOL:TIMEFRAME"     # I8 outputs
      - "insights:MARKET"               # Market-wide insights
```

### **3. Stream-Native Intelligence Processing**

**Stream Transformation Framework:**

```python
class StreamTransform:
    """Pure functional stream transformation"""
    
    def __init__(self, 
                 input_patterns: List[str],
                 plugin: IntelligencePlugin,
                 output_pattern: str,
                 config: Dict[str, Any] = None):
        self.input_patterns = input_patterns
        self.plugin = plugin
        self.output_pattern = output_pattern
        self.config = config or {}
    
    async def process(self, stream_manager: RedisStreamsManager) -> None:
        """Process input streams and publish to output streams"""
        
        # Create input stream iterators
        input_streams = {}
        for pattern in self.input_patterns:
            input_streams[pattern] = stream_manager.stream_iterator(pattern)
        
        # Configure plugin
        self.plugin.configure(self.config)
        
        # Process streams
        async for output in self.plugin.process_stream(input_streams):
            output_stream = self.output_pattern.format(**output.context)
            await stream_manager.publish(output_stream, output.data)

class IntelligencePipeline:
    """Composable intelligence pipeline from configuration"""
    
    def __init__(self, config: PipelineConfig):
        self.config = config
        self.transforms = self._build_transforms()
    
    def _build_transforms(self) -> List[StreamTransform]:
        """Build stream transformations from configuration"""
        transforms = []
        
        for plugin_config in self.config.plugins:
            plugin = plugin_registry.get(plugin_config.plugin)
            
            # Determine input patterns from dependencies
            input_patterns = self._resolve_dependencies(plugin_config)
            
            # Create stream transform
            transform = StreamTransform(
                input_patterns=input_patterns,
                plugin=plugin,
                output_pattern=self._get_output_pattern(plugin),
                config=plugin_config.config
            )
            transforms.append(transform)
        
        return transforms
    
    async def start(self, stream_manager: RedisStreamsManager) -> None:
        """Start all stream transformations"""
        tasks = []
        for transform in self.transforms:
            task = asyncio.create_task(transform.process(stream_manager))
            tasks.append(task)
        
        await asyncio.gather(*tasks)
```

### **4. Multi-Modal Intelligence Support**

**Support Different Intelligence Types:**

```python
class IntelligenceMode(Enum):
    MATHEMATICAL = "mathematical"      # Deterministic calculations
    PATTERN = "pattern"               # Pattern recognition  
    AI_ENHANCED = "ai_enhanced"       # LLM-powered analysis
    SENTIMENT = "sentiment"           # News/social sentiment
    ALTERNATIVE = "alternative"       # Options flow, institutional data
    CROSS_ASSET = "cross_asset"       # Multi-asset correlation

class ProcessingStyle(Enum):
    REAL_TIME = "real_time"           # <10ms processing
    BATCH = "batch"                   # Batched processing
    EVENT_DRIVEN = "event_driven"     # Triggered by specific events
    SCHEDULED = "scheduled"           # Time-based processing

class ResourceRequirements:
    cpu_cores: float = 0.1            # CPU requirement
    memory_mb: int = 100              # Memory requirement  
    gpu_required: bool = False        # GPU requirement
    network_intensive: bool = False   # Network I/O requirement

class CostModel:
    type: str                         # FREE, PER_CALCULATION, PER_TOKEN
    cost_per_unit: float = 0.0       # Cost per calculation/token
    monthly_budget: float = 0.0       # Monthly budget limit
```

### **5. Runtime Intelligence Composition**

**Dynamic Pipeline Management:**

```python
class IntelligenceOrchestrator:
    """Runtime intelligence pipeline management"""
    
    def __init__(self, stream_manager: RedisStreamsManager):
        self.stream_manager = stream_manager
        self.active_pipelines: Dict[str, IntelligencePipeline] = {}
        self.plugin_registry = PluginRegistry()
    
    async def load_pipeline(self, config_path: str) -> None:
        """Load and start intelligence pipeline from configuration"""
        config = PipelineConfig.from_yaml(config_path)
        pipeline = IntelligencePipeline(config)
        
        self.active_pipelines[config.name] = pipeline
        await pipeline.start(self.stream_manager)
    
    async def update_pipeline(self, name: str, new_config: PipelineConfig) -> None:
        """Update running pipeline with new configuration"""
        # Stop existing pipeline
        if name in self.active_pipelines:
            await self.active_pipelines[name].stop()
        
        # Start new pipeline
        pipeline = IntelligencePipeline(new_config)
        self.active_pipelines[name] = pipeline
        await pipeline.start(self.stream_manager)
    
    async def scale_plugin(self, plugin_name: str, instances: int) -> None:
        """Scale specific plugin processing"""
        # Implementation for horizontal scaling of individual plugins
        pass
    
    def get_pipeline_metrics(self) -> Dict[str, Any]:
        """Get real-time metrics for all pipelines"""
        return {
            name: pipeline.get_metrics()
            for name, pipeline in self.active_pipelines.items()
        }
```

### **6. Intelligence Event Sourcing**

**Complete Intelligence Audit Trail:**

```python
@dataclass
class IntelligenceEvent:
    """Immutable intelligence event for complete audit trail"""
    
    event_id: str                     # Unique event identifier
    timestamp: datetime               # Event timestamp
    intelligence_tier: str            # I1, I2, I3, I4, I5, I6, I7, I8
    intelligence_type: str            # rsi, macd_divergence, etc.
    symbol: str                       # Trading symbol
    timeframe: str                    # Analysis timeframe
    
    # Intelligence data
    data: Dict[str, Any]              # Intelligence calculation results
    confidence: float                 # Intelligence confidence score
    
    # Lineage and provenance
    source_events: List[str]          # Source event IDs
    plugin_name: str                  # Plugin that generated this intelligence
    plugin_version: str               # Plugin version
    config_hash: str                  # Configuration hash
    
    # Processing metadata
    processing_latency_ms: float      # Processing time
    cost_usd: float                   # Processing cost (for AI intelligence)
    resource_usage: Dict[str, float]  # CPU/memory usage

class IntelligenceEventStore:
    """Event sourcing for intelligence processing"""
    
    async def append_event(self, event: IntelligenceEvent) -> None:
        """Append intelligence event to event store"""
        pass
    
    async def replay_from(self, timestamp: datetime) -> AsyncIterator[IntelligenceEvent]:
        """Replay intelligence events from specific timestamp"""
        pass
    
    async def get_lineage(self, event_id: str) -> List[IntelligenceEvent]:
        """Get complete lineage for intelligence event"""
        pass
    
    async def rebuild_state(self, symbol: str, timeframe: str, timestamp: datetime) -> Dict[str, Any]:
        """Rebuild intelligence state from events"""
        pass
```

---

## Implementation Strategy

### **Phase 1: Plugin Integration (Immediate - 2 weeks)**

**Integrate Existing Plugin Framework with Services:**

1. **Enhance Plugin Registry**
   - Add intelligence tier classification
   - Add processing mode and resource requirements
   - Add configuration-driven plugin loading

2. **Integrate with Current Services**
   - Modify `indicators_processor_service.py` / bridge with `intelligence_processor_service.py` for plugin framework
   - Create plugin-based I1 processing pipeline
   - Migrate existing indicator calculations to plugin format

3. **Stream-Native Processing**
   - Enhance `RedisStreamsManager` to support stream transformations
   - Implement stream iteration and publishing for plugins
   - Add plugin-based stream processing framework

### **Phase 2: Configuration Engine (Medium-term - 3 weeks)**

**Configuration-Driven Intelligence:**

1. **Pipeline Configuration System**
   - Implement YAML-based pipeline configuration
   - Add runtime pipeline loading and validation
   - Create configuration management API

2. **Dynamic Plugin Composition**
   - Implement dependency resolution for plugins
   - Add dynamic DAG generation from configuration
   - Create runtime reconfiguration capabilities

3. **Multi-Modal Intelligence Support**
   - Add support for different intelligence modes
   - Implement cost controls and resource management
   - Add scheduling and event-driven processing

### **Phase 3: Advanced Features (Long-term - 4 weeks)**

**Event Sourcing and Advanced Capabilities:**

1. **Intelligence Event Sourcing**
   - Implement complete intelligence event store
   - Add event replay and lineage tracking
   - Create time-travel debugging capabilities

2. **AI Intelligence Integration**
   - Integrate OpenRouter LLM framework with plugin system
   - Add cost-controlled AI processing
   - Implement intelligent batching and caching

3. **Advanced Orchestration**
   - Add horizontal scaling for individual plugins
   - Implement intelligent resource allocation
   - Create comprehensive monitoring and alerting

---

## Benefits of Enhanced Architecture

### **Flexibility**
- **Runtime Reconfiguration:** Change intelligence pipelines without code changes
- **Plugin Composition:** Mix and match intelligence capabilities dynamically
- **Multi-Modal Support:** Easy to add new types of intelligence processing

### **Extensibility**
- **Plugin Ecosystem:** Easy to add new intelligence capabilities
- **Configuration-Driven:** New intelligence workflows through configuration
- **Event Sourcing:** Complete audit trail and replay capabilities

### **Elegance**
- **Stream-Native:** Pure functional stream processing approach
- **Declarative Configuration:** Clear, readable intelligence pipeline definitions
- **Separation of Concerns:** Intelligence logic separate from orchestration

### **Production Benefits**
- **Scalability:** Scale individual intelligence components independently
- **Observability:** Complete intelligence lineage and performance tracking
- **Cost Control:** Intelligent resource allocation and cost management
- **Reliability:** Event sourcing enables robust error recovery

---

## Integration with Existing Refactoring Plan

**Enhanced Approach vs Original Two-Layer Plan:**

| Aspect | Original Plan | Enhanced Plan |
|--------|---------------|---------------|
| **Architecture** | Two monolithic services (L4/L5) | Plugin-native intelligence engine |
| **Flexibility** | Fixed I1-I4 / I5-I8 separation | Dynamic plugin composition |
| **Configuration** | Hard-coded intelligence logic | YAML-driven pipeline configuration |
| **Extensibility** | Add features by modifying services | Add features by creating plugins |
| **Deployment** | Service-based deployment | Plugin-based deployment |
| **Scaling** | Scale entire intelligence layers | Scale individual intelligence plugins |

**Migration Path:**
1. **Keep existing plugin framework** (already implemented and sophisticated)
2. **Integrate plugins with services** (Phase 1 - immediate benefit)
3. **Add configuration engine** (Phase 2 - major flexibility gain)
4. **Enhance with advanced features** (Phase 3 - production-grade capabilities)

This approach leverages our existing investment in the plugin framework while providing significantly more flexibility and elegance than the original two-layer service approach.

---

**The enhanced architecture provides a natural evolution path that builds on our existing plugin infrastructure while delivering the flexibility, extensibility, and elegance needed for sophisticated intelligence processing.**