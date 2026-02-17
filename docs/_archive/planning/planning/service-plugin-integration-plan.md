# Service-Plugin Integration Implementation Plan

**Version:** 1.0.0
**Created:** 2025-08-17
**Last Updated:** 2026-02-13
**Status:** HISTORICAL REFERENCE — Integration completed. 22 plugins operational with I1-I5 tiers. See [`docs/current-status-and-priorities.md`](../current-status-and-priorities.md) for current state.  

## Executive Summary

This plan outlines the integration of our existing plugin framework with production services using a Service-Plugin Bridge Pattern. The approach maintains our 141x performance gains from direct calculations while enabling plugin-based intelligence expansion.

## Architecture Overview

### Current State (as of 2026-02)
-  **Production Services:** Enhanced indicator processing with 141x performance boost
-  **Plugin Framework:** 22 plugins (12 I1, 3 I3, 3 I4, 4 I5), DAG execution
-  **Integration:** Complete — `intelligence_processor_service.py` runs I3/I4/I5; bridge implemented

### Target State
- **Hybrid Architecture:** Direct calculations + Plugin alternatives with seamless fallback
- **Configuration-Driven:** YAML-based pipeline composition with hot reloading
- **Intelligence-Aware:** Streaming with I1-I8 tier classification and metadata
- **Production-Ready:** Comprehensive monitoring, circuit breakers, and state management

## Implementation Phases

---

##  Phase A: Monitoring & Safety Infrastructure (Week 1: Days 1-2)

**Objective:** Enhance existing monitoring and add safety mechanisms before integration  
**Duration:** 4-5 hours  
**Dependencies:** None - leverages existing Prometheus/OpenTelemetry

### A1: Connect Enhanced Services to Prometheus (30 minutes)
**File:** `services/indicators_enhanced_service.py:services/indicators_enhanced_service.py:771-809`

**Current Problem:** Service uses internal JSON metrics instead of Prometheus

**Implementation:**
```python
# Add to service initialization
from src.observability.metrics import counter, gauge, start_metrics_server

# Replace EnhancedIndicatorMetrics with Prometheus metrics
self.indicators_calculated_total = counter(
    "enhanced_indicators_calculated_total", 
    "Total enhanced indicators calculated"
)
self.incremental_calculations_total = counter(
    "enhanced_incremental_calculations_total", 
    "Total incremental calculations performed"
)
self.calculation_duration_ms = gauge(
    "enhanced_calculation_duration_ms", 
    "Average calculation time in milliseconds"
)
self.memory_usage_mb = gauge(
    "enhanced_memory_usage_mb", 
    "Memory usage in megabytes"
)

# Start metrics server
start_metrics_server(port=9109)
```

**Deliverable:** Enhanced service exposing Prometheus metrics at `:9109/metrics`

### A2: Add Plugin-Specific Metrics (1 hour)
**File:** `src/observability/metrics.py:src/observability/metrics.py:32-64`

**Implementation:**
```python
# Plugin execution metrics
PLUGIN_EXECUTION_TOTAL = Counter(
    "plugin_executions_total", 
    "Total plugin executions", 
    ["plugin_name", "symbol", "timeframe", "status"]
)
PLUGIN_EXECUTION_TIME = Histogram(
    "plugin_execution_seconds", 
    "Plugin execution time", 
    ["plugin_name", "intelligence_tier"]
)
PLUGIN_FALLBACK_TOTAL = Counter(
    "plugin_fallbacks_total", 
    "Plugin fallbacks to direct calculation", 
    ["plugin_name", "reason"]
)
PLUGIN_ACCURACY_GAUGE = Gauge(
    "plugin_accuracy_percentage", 
    "Plugin vs direct calculation accuracy", 
    ["plugin_name", "symbol", "timeframe"]
)
PLUGIN_STATE_SIZE_GAUGE = Gauge(
    "plugin_state_size_bytes", 
    "Plugin state size in bytes", 
    ["plugin_name", "symbol", "timeframe"]
)

# Hybrid processing metrics
HYBRID_MODE_GAUGE = Gauge(
    "hybrid_processing_active", 
    "Whether hybrid mode is active", 
    ["service", "symbol", "timeframe"]
)
CIRCUIT_BREAKER_STATE = Gauge(
    "plugin_circuit_breaker_state", 
    "Circuit breaker state (0=closed, 1=open, 2=half-open)", 
    ["plugin_name"]
)
```

**Deliverable:** Plugin-specific metrics available in Prometheus

### A3: Plugin State Management (2 hours)
**File:** `src/core/plugin_state_manager.py` (new)

**Implementation:**
```python
import json
import asyncio
from typing import Dict, Any, Optional
from collections import defaultdict
import redis.asyncio as redis
import structlog

logger = structlog.get_logger(__name__)

class PluginStateManager:
    """Manages plugin state persistence using Redis."""
    
    def __init__(self, redis_client: redis.Redis, env_prefix: str):
        self.redis = redis_client
        self.env_prefix = env_prefix
        self.state_cache = defaultdict(dict)  # In-memory cache for performance
        
    async def save_plugin_state(self, plugin_name: str, symbol: str, 
                               timeframe: str, state: Dict[str, Any]) -> bool:
        """Save plugin state to Redis with TTL."""
        try:
            key = self._get_state_key(plugin_name, symbol, timeframe)
            
            # Serialize state
            serialized_state = {
                k: json.dumps(v, default=str) for k, v in state.items()
            }
            
            # Save to Redis with 24-hour TTL
            await self.redis.hset(key, mapping=serialized_state)
            await self.redis.expire(key, 86400)
            
            # Update cache
            self.state_cache[f"{plugin_name}:{symbol}:{timeframe}"] = state
            
            # Update metrics
            from src.observability.metrics import PLUGIN_STATE_SIZE_GAUGE
            state_size = len(json.dumps(state))
            PLUGIN_STATE_SIZE_GAUGE.labels(
                plugin_name=plugin_name, 
                symbol=symbol, 
                timeframe=timeframe
            ).set(state_size)
            
            return True
            
        except Exception as e:
            logger.error("Failed to save plugin state", 
                        plugin=plugin_name, symbol=symbol, timeframe=timeframe, error=str(e))
            return False
    
    async def restore_plugin_state(self, plugin_name: str, symbol: str, 
                                  timeframe: str) -> Optional[Dict[str, Any]]:
        """Restore plugin state from Redis."""
        try:
            cache_key = f"{plugin_name}:{symbol}:{timeframe}"
            
            # Check cache first
            if cache_key in self.state_cache:
                return self.state_cache[cache_key]
            
            # Load from Redis
            key = self._get_state_key(plugin_name, symbol, timeframe)
            data = await self.redis.hgetall(key)
            
            if not data:
                return None
                
            # Deserialize state
            state = {}
            for k, v in data.items():
                try:
                    state[k.decode()] = json.loads(v.decode())
                except (json.JSONDecodeError, UnicodeDecodeError):
                    logger.warning("Failed to deserialize state field", 
                                 plugin=plugin_name, field=k)
                    
            # Update cache
            self.state_cache[cache_key] = state
            
            return state
            
        except Exception as e:
            logger.error("Failed to restore plugin state", 
                        plugin=plugin_name, symbol=symbol, timeframe=timeframe, error=str(e))
            return None
    
    async def clear_plugin_state(self, plugin_name: str, symbol: str, timeframe: str) -> bool:
        """Clear plugin state from Redis and cache."""
        try:
            key = self._get_state_key(plugin_name, symbol, timeframe)
            await self.redis.delete(key)
            
            cache_key = f"{plugin_name}:{symbol}:{timeframe}"
            self.state_cache.pop(cache_key, None)
            
            return True
            
        except Exception as e:
            logger.error("Failed to clear plugin state", 
                        plugin=plugin_name, symbol=symbol, timeframe=timeframe, error=str(e))
            return False
    
    def _get_state_key(self, plugin_name: str, symbol: str, timeframe: str) -> str:
        """Generate Redis key for plugin state."""
        return f"{self.env_prefix}plugin_state:{plugin_name}:{symbol}:{timeframe}"
    
    async def get_state_summary(self) -> Dict[str, Any]:
        """Get summary of all plugin states for monitoring."""
        summary = {
            "total_cached_states": len(self.state_cache),
            "plugins": defaultdict(int),
            "symbols": defaultdict(int),
            "timeframes": defaultdict(int)
        }
        
        for cache_key in self.state_cache.keys():
            parts = cache_key.split(":")
            if len(parts) == 3:
                plugin, symbol, timeframe = parts
                summary["plugins"][plugin] += 1
                summary["symbols"][symbol] += 1
                summary["timeframes"][timeframe] += 1
                
        return dict(summary)
```

**Deliverable:** Redis-based plugin state persistence with caching

### A4: Circuit Breaker Implementation (1 hour)
**File:** `src/core/plugin_circuit_breaker.py` (new)

**Implementation:**
```python
import time
import asyncio
from typing import Dict, Callable, Any, Union
from collections import defaultdict
from enum import Enum
import structlog

logger = structlog.get_logger(__name__)

class CircuitState(Enum):
    CLOSED = 0      # Normal operation
    OPEN = 1        # Failing, use fallback
    HALF_OPEN = 2   # Testing recovery

class PluginCircuitBreaker:
    """Circuit breaker for plugin failure handling."""
    
    def __init__(self, failure_threshold: int = 3, recovery_timeout: int = 300):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        
        # Per-plugin state tracking
        self.plugin_states: Dict[str, CircuitState] = defaultdict(lambda: CircuitState.CLOSED)
        self.failure_counts: Dict[str, int] = defaultdict(int)
        self.last_failure_time: Dict[str, float] = defaultdict(float)
        self.success_counts: Dict[str, int] = defaultdict(int)
        
    async def execute_with_fallback(self, 
                                   plugin_name: str,
                                   plugin_fn: Callable,
                                   fallback_fn: Callable,
                                   *args, **kwargs) -> Any:
        """Execute plugin with automatic fallback on failure."""
        
        # Check circuit state
        if self._should_use_fallback(plugin_name):
            logger.debug("Using fallback due to circuit breaker", plugin=plugin_name)
            
            # Update metrics
            from src.observability.metrics import PLUGIN_FALLBACK_TOTAL
            PLUGIN_FALLBACK_TOTAL.labels(
                plugin_name=plugin_name, 
                reason="circuit_breaker"
            ).inc()
            
            return await self._execute_fallback(fallback_fn, *args, **kwargs)
        
        # Try plugin execution
        try:
            start_time = time.time()
            result = await plugin_fn(*args, **kwargs)
            execution_time = time.time() - start_time
            
            # Record success
            self._record_success(plugin_name)
            
            # Update metrics
            from src.observability.metrics import PLUGIN_EXECUTION_TOTAL, PLUGIN_EXECUTION_TIME
            PLUGIN_EXECUTION_TOTAL.labels(
                plugin_name=plugin_name,
                symbol=kwargs.get('symbol', 'unknown'),
                timeframe=kwargs.get('timeframe', 'unknown'),
                status="success"
            ).inc()
            
            return result
            
        except Exception as e:
            logger.warning("Plugin execution failed, using fallback", 
                          plugin=plugin_name, error=str(e))
            
            # Record failure
            self._record_failure(plugin_name)
            
            # Update metrics
            from src.observability.metrics import PLUGIN_EXECUTION_TOTAL, PLUGIN_FALLBACK_TOTAL
            PLUGIN_EXECUTION_TOTAL.labels(
                plugin_name=plugin_name,
                symbol=kwargs.get('symbol', 'unknown'),
                timeframe=kwargs.get('timeframe', 'unknown'),
                status="failure"
            ).inc()
            
            PLUGIN_FALLBACK_TOTAL.labels(
                plugin_name=plugin_name, 
                reason="execution_failure"
            ).inc()
            
            return await self._execute_fallback(fallback_fn, *args, **kwargs)
    
    def _should_use_fallback(self, plugin_name: str) -> bool:
        """Determine if fallback should be used."""
        state = self.plugin_states[plugin_name]
        
        if state == CircuitState.CLOSED:
            return False
        elif state == CircuitState.OPEN:
            # Check if recovery timeout has passed
            if time.time() - self.last_failure_time[plugin_name] > self.recovery_timeout:
                self.plugin_states[plugin_name] = CircuitState.HALF_OPEN
                logger.info("Circuit breaker moving to half-open", plugin=plugin_name)
                return False
            return True
        elif state == CircuitState.HALF_OPEN:
            # Allow limited testing
            return False
        
        return True
    
    def _record_success(self, plugin_name: str):
        """Record successful plugin execution."""
        self.failure_counts[plugin_name] = 0
        self.success_counts[plugin_name] += 1
        
        # If we were in half-open, close the circuit
        if self.plugin_states[plugin_name] == CircuitState.HALF_OPEN:
            self.plugin_states[plugin_name] = CircuitState.CLOSED
            logger.info("Circuit breaker closed after successful recovery", plugin=plugin_name)
        
        # Update metrics
        from src.observability.metrics import CIRCUIT_BREAKER_STATE
        CIRCUIT_BREAKER_STATE.labels(plugin_name=plugin_name).set(
            self.plugin_states[plugin_name].value
        )
    
    def _record_failure(self, plugin_name: str):
        """Record failed plugin execution."""
        self.failure_counts[plugin_name] += 1
        self.last_failure_time[plugin_name] = time.time()
        
        # Open circuit if threshold exceeded
        if self.failure_counts[plugin_name] >= self.failure_threshold:
            self.plugin_states[plugin_name] = CircuitState.OPEN
            logger.warning("Circuit breaker opened due to failures", 
                          plugin=plugin_name, 
                          failure_count=self.failure_counts[plugin_name])
        
        # Update metrics
        from src.observability.metrics import CIRCUIT_BREAKER_STATE
        CIRCUIT_BREAKER_STATE.labels(plugin_name=plugin_name).set(
            self.plugin_states[plugin_name].value
        )
    
    async def _execute_fallback(self, fallback_fn: Callable, *args, **kwargs) -> Any:
        """Execute fallback function."""
        try:
            if asyncio.iscoroutinefunction(fallback_fn):
                return await fallback_fn(*args, **kwargs)
            else:
                return fallback_fn(*args, **kwargs)
        except Exception as e:
            logger.error("Fallback execution also failed", error=str(e))
            raise
    
    def get_plugin_stats(self) -> Dict[str, Any]:
        """Get circuit breaker statistics."""
        return {
            "plugin_states": {k: v.name for k, v in self.plugin_states.items()},
            "failure_counts": dict(self.failure_counts),
            "success_counts": dict(self.success_counts),
            "configuration": {
                "failure_threshold": self.failure_threshold,
                "recovery_timeout": self.recovery_timeout
            }
        }
```

**Deliverable:** Circuit breaker with automatic fallback to direct calculations

### A5: Testing & Validation (30 minutes)
**Files:** `tests/unit/test_monitoring_improvements.py` (new)

**Test Coverage:**
- Prometheus metrics integration
- Plugin state persistence
- Circuit breaker functionality
- Performance baseline validation

---

##  Phase B: Service-Plugin Bridge Implementation (Week 1-2: Days 3-10)

**Objective:** Integrate plugin framework with enhanced indicator service  
**Duration:** 5-7 days  
**Dependencies:** Phase A completion  

### B1: Hybrid Calculator Implementation (2 days)
**File:** `src/core/hybrid_indicator_calculator.py` (new)

**Implementation:**
```python
from typing import Dict, Any, Optional, Union
import asyncio
import structlog
from src.intelligence.plugins import registry
from src.indicators.calculations import IndicatorCalculations
from src.core.plugin_circuit_breaker import PluginCircuitBreaker
from src.core.plugin_state_manager import PluginStateManager

logger = structlog.get_logger(__name__)

class HybridIndicatorCalculator:
    """Hybrid calculator supporting both direct and plugin-based calculations."""
    
    def __init__(self, redis_client, env_prefix: str):
        self.direct_calculator = IndicatorCalculations()
        self.plugin_registry = registry
        self.circuit_breaker = PluginCircuitBreaker()
        self.state_manager = PluginStateManager(redis_client, env_prefix)
        
        # Configuration
        self.plugin_enabled_indicators = {
            "RSI": True,
            "SMA_20": True, 
            "SMA_50": True,
            "EMA_12": True,
            "EMA_26": True,
            "MACD": True,
            "ATR": True,
            "BB_UPPER": True,
            "BB_MIDDLE": True,
            "BB_LOWER": True,
            "STOCH_K": True,
            "STOCH_D": True
        }
        
    async def calculate_indicator(self, 
                                symbol: str, 
                                timeframe: str, 
                                indicator_name: str,
                                bar_data: Dict[str, Any],
                                historical_data: Optional[Any] = None) -> Optional[Union[float, Dict[str, float]]]:
        """Calculate indicator using hybrid approach."""
        
        # Check if plugin is available and enabled
        if (indicator_name in self.plugin_enabled_indicators and 
            self.plugin_enabled_indicators[indicator_name]):
            
            # Try plugin calculation with fallback
            return await self.circuit_breaker.execute_with_fallback(
                plugin_name=indicator_name,
                plugin_fn=self._calculate_with_plugin,
                fallback_fn=self._calculate_direct,
                symbol=symbol,
                timeframe=timeframe,
                indicator_name=indicator_name,
                bar_data=bar_data,
                historical_data=historical_data
            )
        else:
            # Use direct calculation
            return await self._calculate_direct(
                symbol, timeframe, indicator_name, bar_data, historical_data
            )
    
    async def _calculate_with_plugin(self, 
                                   symbol: str, 
                                   timeframe: str, 
                                   indicator_name: str,
                                   bar_data: Dict[str, Any],
                                   historical_data: Optional[Any] = None) -> Optional[Union[float, Dict[str, float]]]:
        """Calculate using plugin framework."""
        
        # Get plugin
        plugin = self._get_plugin_for_indicator(indicator_name)
        if not plugin:
            raise ValueError(f"No plugin found for indicator: {indicator_name}")
        
        # Restore plugin state
        plugin_state = await self.state_manager.restore_plugin_state(
            plugin.name, symbol, timeframe
        )
        
        # Prepare data frame
        frames = self._prepare_plugin_data(historical_data, bar_data)
        
        # Calculate using plugin
        if plugin.supports_incremental and plugin_state:
            # Incremental calculation
            result = plugin.compute_next(frames)
        else:
            # Full calculation
            result = plugin.compute_full(frames)
        
        # Save plugin state
        if hasattr(plugin, 'get_state'):
            new_state = plugin.get_state()
            await self.state_manager.save_plugin_state(
                plugin.name, symbol, timeframe, new_state
            )
        
        # Extract specific indicator value
        return self._extract_indicator_value(result, indicator_name)
    
    async def _calculate_direct(self, 
                              symbol: str, 
                              timeframe: str, 
                              indicator_name: str,
                              bar_data: Dict[str, Any],
                              historical_data: Optional[Any] = None) -> Optional[Union[float, Dict[str, float]]]:
        """Calculate using direct methods (fallback)."""
        
        # Use existing direct calculation logic
        # (Implementation matches current enhanced service logic)
        
        if indicator_name == "RSI":
            return self.direct_calculator.calculate_rsi(historical_data, period=14)
        elif indicator_name.startswith("SMA_"):
            period = int(indicator_name.split("_")[1])
            result = self.direct_calculator.calculate_moving_averages(historical_data, periods=[period])
            return result.get(f"sma_{period}")
        # ... etc for other indicators
        
        return None
    
    def _get_plugin_for_indicator(self, indicator_name: str):
        """Get plugin for specific indicator."""
        # Map indicator names to plugins
        plugin_mapping = {
            "RSI": "RSI",
            "SMA_20": "MovingAverages", 
            "SMA_50": "MovingAverages",
            "EMA_12": "MovingAverages",
            "EMA_26": "MovingAverages", 
            "MACD": "MACD",
            "ATR": "ATR",
            "BB_UPPER": "BollingerBands",
            "BB_MIDDLE": "BollingerBands", 
            "BB_LOWER": "BollingerBands",
            "STOCH_K": "Stochastic",
            "STOCH_D": "Stochastic"
        }
        
        plugin_name = plugin_mapping.get(indicator_name)
        if plugin_name:
            return self.plugin_registry.get_indicator(plugin_name)
        return None
    
    def _prepare_plugin_data(self, historical_data, current_bar):
        """Prepare data frame for plugin consumption."""
        # Convert data to plugin-expected format
        # Implementation depends on plugin interface
        pass
    
    def _extract_indicator_value(self, plugin_result: Dict[str, Any], indicator_name: str):
        """Extract specific indicator value from plugin result."""
        # Map plugin outputs to indicator names
        # Implementation depends on plugin output format
        pass
```

**Deliverable:** Hybrid calculator with plugin + direct calculation support

### B2: Enhanced Service Integration (1-2 days)
**File:** `services/indicators_enhanced_service.py:services/indicators_enhanced_service.py:458-515` (modify)

**Key Changes:**
1. Replace direct calculation calls with hybrid calculator
2. Add plugin configuration loading
3. Integrate circuit breaker and state management
4. Add plugin-specific metrics

### B3: Intelligence Stream Models Integration (1 day)
**File:** `src/core/stream_models.py` integration into services

**Implementation:**
- Upgrade Redis publishing to use `IntelligenceStreamMessage`
- Add I1-I8 tier classification to stream messages
- Include plugin metadata in published messages

### B4: Configuration Integration (1 day)
**Files:** 
- Connect `config/pipelines/default_intelligence.yaml:config/pipelines/default_intelligence.yaml:14-96` to service
- Add runtime configuration reloading

### B5: Shadow Mode Implementation (1-2 days)
**File:** `src/core/shadow_mode_runner.py` (new)

**Purpose:** Run plugins in parallel with direct calculations for validation

---

##  Phase C: Testing & Validation (Week 3: Days 11-15)

**Objective:** Comprehensive testing of hybrid architecture  
**Duration:** 3-5 days  

### C1: Unit Testing (1-2 days)
- Plugin state management tests
- Circuit breaker functionality tests  
- Hybrid calculator tests
- Configuration loading tests

### C2: Integration Testing (1-2 days)
- End-to-end pipeline tests
- Performance comparison tests
- Fallback mechanism tests
- Shadow mode validation tests

### C3: Performance Validation (1 day)
- Benchmark plugin vs direct calculations
- Validate 141x performance is maintained
- Memory usage analysis
- Latency impact assessment

---

##  Success Metrics

### Performance Targets
- **Plugin Execution Time:** <5ms per indicator (vs <1ms direct)
- **Fallback Time:** <100ms when circuit breaker triggers
- **Memory Overhead:** <50MB additional for plugin state
- **Accuracy:** >99.9% match between plugin and direct calculations

### Monitoring KPIs  
- **Plugin Success Rate:** >95% successful executions
- **Circuit Breaker Triggers:** <1% of total executions
- **State Persistence:** >99.9% successful state saves/restores
- **Configuration Reloads:** 100% successful without restart

### Observability Goals
- All plugin executions tracked in Prometheus
- Circuit breaker state visible in monitoring
- Plugin performance comparison dashboards
- Alert on plugin failure thresholds

---

##  Deployment Strategy

### Phase A Deployment
- Deploy monitoring improvements to development environment
- Validate metrics collection 
- Test circuit breaker with simulated failures

### Phase B Deployment  
- Deploy hybrid calculator to staging environment
- Run shadow mode validation for 24 hours
- Compare plugin vs direct calculation accuracy
- Performance testing under load

### Phase C Deployment
- Production rollout with feature flags
- Gradual enablement of plugin calculations
- Monitoring and rollback plan ready

---

## Risk Mitigation

### Technical Risks
- **Plugin Performance:** Circuit breaker provides automatic fallback
- **State Corruption:** Redis TTL and cache invalidation prevent persistence issues  
- **Configuration Errors:** YAML validation prevents invalid configurations
- **Memory Leaks:** State cache with TTL and size limits

### Operational Risks
- **Service Downtime:** Backward compatibility maintained throughout
- **Data Loss:** Dual processing ensures no calculation gaps
- **Monitoring Gaps:** Comprehensive metrics added before integration

---

## Timeline Summary

| Phase | Duration | Key Deliverables |
|-------|----------|------------------|
| **A: Monitoring** | 2 days | Prometheus integration, circuit breaker, state management |
| **B: Integration** | 7 days | Hybrid calculator, service integration, configuration |
| **C: Testing** | 5 days | Comprehensive testing, performance validation |
| **Total** | **14 days** | **Production-ready hybrid architecture** |

---

## Next Steps

1. **Immediate (Today):** Begin Phase A implementation
2. **Week 1:** Complete monitoring improvements and start service integration  
3. **Week 2:** Finish hybrid calculator and configuration integration
4. **Week 3:** Comprehensive testing and validation
5. **Week 4:** Production deployment with monitoring

---

This plan provides a systematic approach to integrating our plugin framework while maintaining performance and reliability. Each phase builds upon the previous with clear deliverables and validation steps.