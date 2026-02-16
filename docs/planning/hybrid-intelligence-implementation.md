# Hybrid Intelligence Implementation Specification

**Version:** 1.1.0
**Last Updated:** 2026-02-13
**Status:** HISTORICAL REFERENCE — PI-1 completed. I1-I5 operational with 22 plugins. See [`docs/current-status-and-priorities.md`](../current-status-and-priorities.md) for current state. In practice I3/I4/I5 run in `intelligence_processor_service.py` (no separate `pattern_detection_service`).

## Executive Summary

This document provides the detailed implementation specification for the Hybrid Intelligence Architecture that integrates the existing plugin framework INTO current production services rather than replacing them.

**Core Strategy:** Service-Plugin Bridge Pattern maintains 141x performance while adding plugin-based extensibility for advanced intelligence tiers.

---

## Architecture Decisions

### **Intelligence Tier Implementation Strategy**

| Tier | Service | Method | Rationale |
|------|---------|--------|-----------|  
| **I1** | `indicators_processor_service.py` / `indicators_enhanced_service.py` | Direct calculation | Maximum performance (141x boost) |
| **I2-I4** | `intelligence_processor_service.py` (I3/I4 plugins) | Hybrid bridge | Composites benefit from plugin flexibility |
| **I5-I7** | `pattern_detection_service.py` (NEW) | Plugin native | Patterns require DAG execution |
| **I8** | `ai_intelligence_service.py` (future) | LLM + plugins | AI needs specialized service |

### **Implementation Phases**

## Phase 1: Service-Plugin Bridge (Immediate - 2 weeks)

### **1.1 Enhanced Indicator Processor Service**

**Objective:** Add plugin capability to existing service without breaking performance

**Implementation:**
```python
# services/indicators_enhanced_service.py
class HybridIndicatorProcessor:
    def __init__(self, config_path: str):
        # Preserve existing performance components
        self.direct_calculator = IndicatorCalculations()
        self.incremental_manager = IncrementalManager()
        
        # Add plugin integration components
        self.plugin_registry = PluginRegistry()
        self.plugin_executor = PluginExecutor()
        self.config = IntelligenceConfig.load(config_path)
        
        # Bridge coordination
        self.tier_coordinator = TierCoordinator()
    
    async def process_ohlcv_bar(self, symbol: str, timeframe: str, bar_data: dict):
        results = {}
        
        # I1: High-performance direct calculation (existing)
        if self.config.intelligence_tiers.I1.enabled:
            i1_results = await self._process_i1_direct(symbol, timeframe, bar_data)
            results.update(i1_results)
            
        # I2-I4: Plugin-based composites (NEW)
        if self.config.intelligence_tiers.I2_I4.enabled:
            composite_results = await self._process_i2_i4_plugins(symbol, timeframe, bar_data, i1_results)
            results.update(composite_results)
            
        return results
    
    async def _process_i1_direct(self, symbol: str, timeframe: str, bar_data: dict):
        """Existing high-performance I1 indicator calculation"""
        return self.direct_calculator.calculate_all(bar_data)
    
    async def _process_i2_i4_plugins(self, symbol: str, timeframe: str, bar_data: dict, i1_data: dict):
        """NEW: Plugin-based composite indicator calculation"""
        composite_plugins = self.plugin_registry.get_tier_plugins(['I2', 'I3', 'I4'])
        
        # Combine bar data with I1 results for composite calculations
        plugin_input = {
            'bars': bar_data,
            'indicators': i1_data,
            'symbol': symbol,
            'timeframe': timeframe
        }
        
        return await self.plugin_executor.execute_dag(composite_plugins, plugin_input)
```

### **1.2 Pattern Detection Service**

**Objective:** Create new service specifically for I5-I7 pattern detection using pure plugin architecture

**Implementation:**
```python
# services/pattern_detection_service.py
class PatternDetectionService:
    def __init__(self, config_path: str):
        self.plugin_registry = PluginRegistry()
        self.plugin_executor = PluginExecutor()
        self.pattern_config = PatternConfig.load(config_path)
        self.redis_client = redis.Redis()
        self.db_manager = DatabaseManager()
    
    async def start(self):
        """Start pattern detection service"""
        # Subscribe to indicator streams (I1-I4 outputs)
        await self._setup_stream_consumers()
        
        # Load pattern detection plugins
        pattern_plugins = self.plugin_registry.get_tier_plugins(['I5', 'I6', 'I7'])
        
        # Start pattern detection loop
        await self._run_pattern_detection_loop(pattern_plugins)
    
    async def _run_pattern_detection_loop(self, pattern_plugins):
        """Main pattern detection processing loop"""
        while True:
            # Read from indicator streams
            indicator_data = await self._consume_indicator_streams()
            
            # Execute pattern detection plugins
            for symbol_timeframe, data in indicator_data:
                pattern_results = await self.plugin_executor.execute_dag(
                    pattern_plugins, data
                )
                
                # Publish pattern results
                await self._publish_pattern_results(symbol_timeframe, pattern_results)
```

### **1.3 Configuration Engine**

**Objective:** YAML-based configuration system for dynamic intelligence pipeline composition

**Configuration Structure:**
```yaml
# config/intelligence_pipeline.yaml
intelligence_tiers:
  I1:
    enabled: true
    method: "direct_calculation"
    indicators:
      - "rsi_14"
      - "macd_12_26_9" 
      - "sma_20"
      - "ema_21"
      - "bb_20_2"
      - "atr_14"
    
  I2_I4:
    enabled: true
    method: "plugin_execution"
    plugins:
      - name: "ma_crossover_composite"
        tier: "I2"
        inputs: ["sma_20", "ema_21"]
      - name: "momentum_confluence"
        tier: "I2" 
        inputs: ["rsi_14", "macd_12_26_9"]
      - name: "market_structure_analyzer"
        tier: "I3"
        inputs: ["bars", "sma_20", "atr_14"]
      - name: "regime_detector"
        tier: "I4"
        inputs: ["bars", "bb_20_2", "atr_14"]

  I5_I7:
    enabled: true
    method: "pattern_service"
    plugins:
      - name: "rsi_divergence_engine"
        tier: "I5"
        inputs: ["bars", "rsi_14"]
      - name: "bollinger_squeeze_engine" 
        tier: "I5"
        inputs: ["bars", "bb_20_2", "atr_14"]
      - name: "multi_indicator_confluence"
        tier: "I6"
        inputs: ["rsi_14", "macd_12_26_9", "bb_20_2"]

stream_routing:
  I1_outputs: "features:{symbol}:{timeframe}"
  I2_I4_outputs: "composite:{symbol}:{timeframe}"  
  I5_I7_outputs: "patterns:{symbol}:{timeframe}"

performance_settings:
  max_concurrent_plugins: 5
  plugin_timeout_ms: 1000
  enable_incremental_calculation: true
  enable_shadow_validation: false
```

## Phase 2: Plugin Framework Enhancement (3-4 weeks)

### **2.1 Enhanced Plugin Protocols**

**Objective:** Extend existing plugin framework to support intelligence tier classification

```python
# src/intelligence/enhanced_plugins.py
from typing import Protocol, ClassVar, List, Set, Dict, Any
from enum import Enum

class IntelligenceTier(Enum):
    I1 = "I1"  # Technical Indicators
    I2 = "I2"  # Composite Indicators  
    I3 = "I3"  # Market Structure
    I4 = "I4"  # Market Context
    I5 = "I5"  # Pattern Recognition
    I6 = "I6"  # Confluence Analysis
    I7 = "I7"  # Intelligence Outputs
    I8 = "I8"  # AI Synthesis

class ProcessingMode(Enum):
    REAL_TIME = "real_time"      # Process every bar
    EVENT_DRIVEN = "event_driven"  # Process on pattern/condition
    BATCH = "batch"              # Process in batches

class EnhancedIntelligencePlugin(Protocol):
    # Existing plugin fields (preserve compatibility)
    name: ClassVar[str]
    outputs: ClassVar[Set[str]]
    min_lookback: ClassVar[int]
    supports_incremental: ClassVar[bool]
    capability_tags: ClassVar[Set[str]]
    inputs: ClassVar[List[InputSpec]]
    
    # Enhanced fields for hybrid architecture
    intelligence_tier: ClassVar[IntelligenceTier]
    processing_mode: ClassVar[ProcessingMode]
    execution_priority: ClassVar[int]  # 1-10, higher = more important
    resource_cost: ClassVar[str]       # "low", "medium", "high"
    
    def compute_full(self, frames: Dict[str, Any]) -> Dict[str, Any]: ...
    def compute_next(self, windows: Dict[str, Any]) -> Dict[str, Any]: ...
```

### **2.2 Stream Schema Implementation**

**Objective:** Implement missing stream models for intelligence routing

```python
# src/core/stream_models_v2.py
from enum import Enum
from dataclasses import dataclass
from typing import Optional, Dict, Any, Union
from datetime import datetime

class StreamCategory(Enum):
    TICKS = "ticks"           # Live tick data
    BARS = "bars"             # OHLCV bars  
    FEATURES = "features"     # I1 technical indicators
    COMPOSITE = "composite"   # I2-I4 composite intelligence
    PATTERNS = "patterns"     # I5-I7 pattern intelligence
    INSIGHTS = "insights"     # I8 AI synthesis
    REGIME = "regime"         # Market regime data

@dataclass
class StreamKey:
    category: StreamCategory
    symbol: str
    timeframe: str
    subcategory: Optional[str] = None
    
    def to_redis_key(self, env_prefix: str = "") -> str:
        """Generate Redis stream key"""
        if env_prefix:
            base = f"{env_prefix}:{self.category.value}:{self.symbol}:{self.timeframe}"
        else:
            base = f"{self.category.value}:{self.symbol}:{self.timeframe}"
            
        return f"{base}:{self.subcategory}" if self.subcategory else base

@dataclass
class IntelligenceMessage:
    stream_key: StreamKey
    timestamp: datetime
    intelligence_tier: str
    data: Dict[str, Any]
    metadata: Dict[str, Any]
    source_plugin: Optional[str] = None
    confidence_score: Optional[float] = None
```

## Phase 3: Configuration-Driven Processing (4-5 weeks)

### **3.1 Dynamic Pipeline Composition**

**Objective:** Runtime reconfiguration of intelligence pipelines without service restart

**Implementation:**
```python
# src/config/intelligence_pipeline_manager.py
class IntelligencePipelineManager:
    def __init__(self):
        self.config_watcher = ConfigFileWatcher()
        self.active_pipelines = {}
        self.plugin_registry = PluginRegistry()
    
    async def start(self):
        """Start pipeline manager with hot reloading"""
        await self._load_initial_config()
        self.config_watcher.on_change(self._reload_pipeline_config)
    
    async def _reload_pipeline_config(self, config_path: str):
        """Hot reload pipeline configuration"""
        new_config = IntelligenceConfig.load(config_path)
        
        # Compare with current config
        changes = self._detect_config_changes(new_config)
        
        # Apply changes without service restart
        for change in changes:
            await self._apply_pipeline_change(change)
    
    async def get_active_plugins(self, symbol: str, timeframe: str, tier: str) -> List[Plugin]:
        """Get currently active plugins for symbol/timeframe/tier"""
        pipeline_key = f"{symbol}:{timeframe}:{tier}"
        return self.active_pipelines.get(pipeline_key, [])
```

## Implementation Benefits

### **Immediate Benefits**
-  **Preserve 141x Performance:** I1 indicators keep direct calculation speed
-  **Add Plugin Flexibility:** I2-I4 composites use plugin framework  
-  **Enable Pattern Detection:** I5-I7 patterns use native plugin execution
-  **Zero Downtime:** Additive changes, no service disruption
-  **Gradual Migration:** Can migrate indicators to plugins incrementally

### **Long-term Benefits**
-  **Configuration-Driven:** YAML pipeline composition
-  **Hot Reloading:** Change intelligence pipelines without restart
-  **Plugin Extensibility:** Easy addition of new indicators/patterns
-  **Performance Optimization:** Right tool for each intelligence tier
-  **AI Integration Ready:** Clear path to I8 AI synthesis

## Success Criteria

### **Phase 1 Success Metrics**
-  Enhanced indicator service processes I1 + I2-I4 hybrid
-  Pattern detection service operational for I5-I7
-  YAML configuration system working
-  No performance degradation in I1 indicators
-  Plugin framework integration successful

### **Phase 2 Success Metrics**  
-  Enhanced plugin protocols implemented
-  Stream models operational with intelligence routing
-  Multi-tier plugin execution working
-  Shadow validation system operational

### **Phase 3 Success Metrics**
-  Hot configuration reloading working
-  Dynamic pipeline composition operational
-  Performance monitoring and optimization complete
-  Ready for I8 AI intelligence integration

---

**This hybrid implementation preserves the best of both worlds: production performance AND plugin framework extensibility, creating the foundation for advanced pattern detection and AI intelligence capabilities.**