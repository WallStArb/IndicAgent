# Market Data Intelligence Configuration

**Version:** 1.0.0  
**Last Updated:** 2026-02-13  
**Status:** Intelligence Platform Data Configuration

**Note:** Contract symbols (e.g. ESU5, NQU5) in tables are examples; front-month changes. Use `config/symbol_config.py` or IBKR auto-discovery for current contracts.

## Overview

Configuration for market data sources that feed the IndicAgent intelligence platform. Focus on high-quality, liquid instruments that provide optimal signal-to-noise ratio for intelligence extraction and pattern recognition.

---

##  **Primary Intelligence Sources**

### **Equity Index Futures (Primary Intelligence)**

IndicAgent intelligence platform configured exclusively for futures analysis with **IBKR auto-discovery** of most active contracts:

| Symbol | Description | Exchange | Intelligence Focus | Status |
|--------|-------------|----------|-------------------|--------|
| **ESU5** | E-mini S&P 500 Sep 2025 | CME | Broad market intelligence, institutional flow |  ACTIVE |
| **NQU5** | E-mini Nasdaq Sep 2025 | CME | Technology sector intelligence, growth trends |  ACTIVE |
| **RTYU5** | E-mini Russell 2000 Sep 2025 | CME | Small-cap intelligence, risk appetite |  ACTIVE |

### **Treasury Futures (Macro Intelligence)**
| Symbol | Description | Exchange | Intelligence Focus | Status |
|--------|-------------|----------|-------------------|--------|
| **ZNU5** | 10-Year Treasury Sep 2025 | CBOT | Interest rate intelligence, macro regime |  ACTIVE |
| **ZBU5** | 30-Year Treasury Sep 2025 | CBOT | Long-term macro intelligence, inflation |  ACTIVE |

---

##  **Contract Intelligence Specifications**

### **E-mini S&P 500 (ES) - Primary Market Intelligence**
- **Point Value**: $50 per point
- **Minimum Tick**: 0.25 points ($12.50)
- **Trading Hours**: Nearly 24/5 (Sunday 6:00 PM - Friday 5:00 PM ET)
- **Intelligence Value**: Broad market sentiment, institutional positioning
- **Pattern Reliability**: High - most liquid contract with institutional participation

### **E-mini Nasdaq (NQ) - Technology Intelligence**  
- **Point Value**: $20 per point
- **Minimum Tick**: 0.25 points ($5.00)
- **Trading Hours**: Nearly 24/5 (Sunday 6:00 PM - Friday 5:00 PM ET)
- **Intelligence Value**: Technology sector trends, growth vs value rotation
- **Pattern Reliability**: High - strong retail and institutional volume

### **E-mini Russell 2000 (RTY) - Small-Cap Intelligence**
- **Point Value**: $50 per point  
- **Minimum Tick**: 0.10 points ($5.00)
- **Trading Hours**: Nearly 24/5 (Sunday 6:00 PM - Friday 5:00 PM ET)
- **Intelligence Value**: Risk appetite gauge, domestic economic health
- **Pattern Reliability**: Medium-High - lower liquidity but strong signal value

---

##  **Intelligence Data Collection Configuration**

### **High-Frequency Intelligence Collection**
```yaml
# High-frequency intelligence data collection
intelligence_data_collection:
  primary_contracts:
    - ESU5  # S&P 500 E-mini - Primary market intelligence
    - NQU5  # Nasdaq E-mini - Technology intelligence  
    - RTYU5 # Russell 2000 E-mini - Small-cap intelligence
  
  collection_parameters:
    tick_collection_rate: "all_ticks"  # Maximum granularity for intelligence
    bar_building_timeframes: ["1m", "5m", "15m", "1h", "4h", "1d"]
    intelligence_processing_priority: "real_time"
    
  data_quality_requirements:
    minimum_tick_volume: 10  # Filter noise for intelligence quality
    maximum_spread_threshold: 0.50  # Reject poor quality data
    intelligence_validation_required: true
```

### **IBKR Auto-Discovery Intelligence Configuration**
```python
# scripts/production_ibkr_feed.py - Intelligence-focused data collection
class IntelligenceDataCollector:
    """IBKR data collection optimized for intelligence extraction"""
    
    def __init__(self):
        self.intelligence_symbols = ["ES", "NQ", "RTY", "ZN", "ZB"]
        self.volume_threshold = 10000  # Minimum daily volume for intelligence
        self.intelligence_quality_filters = {
            "minimum_spread": 0.25,  # Maximum acceptable spread
            "minimum_volume": 100,   # Minimum tick volume
            "data_freshness": 5      # Maximum seconds old
        }
    
    async def discover_active_intelligence_contracts(self):
        """Auto-discover most liquid contracts for intelligence analysis"""
        active_contracts = []
        
        for base_symbol in self.intelligence_symbols:
            contracts = await self.discover_contracts(base_symbol)
            # Select most liquid contract for intelligence processing
            most_liquid = max(contracts, key=lambda c: c.volume)
            if most_liquid.volume > self.volume_threshold:
                active_contracts.append(most_liquid)
                
        return active_contracts
```

---

##  **Intelligence Processing Configuration**

### **Symbol Intelligence Profiles**
```yaml
# Symbol-specific intelligence processing profiles  
intelligence_profiles:
  ES_intelligence:
    symbol: "ESU5"
    intelligence_priority: "critical"
    pattern_sensitivity: "high"
    smart_money_analysis: "enhanced"
    volatility_regime_tracking: true
    
  NQ_intelligence:
    symbol: "NQU5" 
    intelligence_priority: "critical"
    pattern_sensitivity: "high"
    sector_correlation_analysis: true
    growth_trend_tracking: true
    
  RTY_intelligence:
    symbol: "RTYU5"
    intelligence_priority: "high" 
    pattern_sensitivity: "medium"
    small_cap_sentiment_analysis: true
    risk_appetite_tracking: true
```

### **Multi-Timeframe Intelligence Configuration**
```yaml
# Multi-timeframe intelligence processing
timeframe_intelligence:
  primary_analysis_timeframes:
    - "1m"   # Micro-structure intelligence
    - "5m"   # Short-term pattern intelligence
    - "15m"  # Intraday intelligence
    - "1h"   # Daily intelligence cycles
    - "4h"   # Swing intelligence
    - "1d"   # Positional intelligence
    
  intelligence_confluence_requirements:
    minimum_timeframe_agreement: 3  # At least 3 timeframes must agree
    confidence_weighting_by_timeframe:
      "1m": 0.05   # Micro signals
      "5m": 0.15   # Short-term patterns  
      "15m": 0.20  # Intraday confluence
      "1h": 0.25   # Primary analysis
      "4h": 0.20   # Swing context
      "1d": 0.15   # Macro context
```

---

##  **Intelligence Stream Configuration**

### **Redis Streams for Intelligence Distribution**
```yaml
# Intelligence-focused stream configuration
intelligence_streams:
  # Raw market data for intelligence processing
  market_data: "market:{symbol}:{timeframe}"
  
  # Pattern intelligence streams  
  pattern_intelligence: "intelligence:patterns:{symbol}:{timeframe}"
  
  # Smart money intelligence
  smart_money_intelligence: "intelligence:smart_money:{symbol}:{timeframe}"
  
  # Market context intelligence
  market_context: "intelligence:context:{symbol}:{timeframe}"
  
  # Confluence intelligence (multi-factor)
  confluence_intelligence: "intelligence:confluence:{symbol}:{timeframe}"
  
  # AI-powered insights
  ai_intelligence: "intelligence:ai:{symbol}:{timeframe}"
```

### **Intelligence Quality Configuration**
```yaml
# Intelligence data quality and validation
intelligence_quality:
  data_validation:
    reject_gaps_larger_than: "5_minutes"
    minimum_volume_per_bar: 10
    maximum_spread_percentage: 0.1
    
  intelligence_confidence_thresholds:
    minimum_pattern_confidence: 0.70
    minimum_multi_timeframe_agreement: 0.75
    minimum_smart_money_confidence: 0.65
    
  intelligence_distribution_policies:
    only_publish_high_confidence: true
    include_confidence_metadata: true
    enable_intelligence_versioning: true
```

---

## 🔮 **Future Intelligence Sources (Expansion)**

### **Commodities Intelligence (Future Integration)**
| Symbol | Description | Exchange | Intelligence Focus |
|--------|-------------|----------|-------------------|
| **CL** | Crude Oil WTI | NYMEX | Energy sector intelligence, macro risk |
| **GC** | Gold | COMEX | Safe haven intelligence, inflation hedge |
| **NG** | Natural Gas | NYMEX | Energy infrastructure, seasonal patterns |
| **SI** | Silver | COMEX | Industrial demand, precious metals correlation |

### **Volatility Intelligence (Future Integration)**
| Symbol | Description | Exchange | Intelligence Focus |
|--------|-------------|----------|-------------------|
| **VX** | CBOE VIX Futures | CFE | Fear/greed intelligence, market volatility |

---

##  **Intelligence Configuration Management**

### **Centralized Configuration Source**
```python
# config/symbol_config.py - Single source of truth for intelligence configuration
class IntelligenceSymbolConfig:
    """Centralized intelligence symbol configuration"""
    
    PRIMARY_INTELLIGENCE_SYMBOLS = [
        {"symbol": "ES", "priority": "critical", "intelligence_focus": "broad_market"},
        {"symbol": "NQ", "priority": "critical", "intelligence_focus": "technology"},  
        {"symbol": "RTY", "priority": "high", "intelligence_focus": "risk_appetite"}
    ]
    
    INTELLIGENCE_TIMEFRAMES = ["1m", "5m", "15m", "1h", "4h", "1d"]
    
    INTELLIGENCE_PROCESSING_CONFIG = {
        "pattern_analysis_enabled": True,
        "smart_money_analysis_enabled": True,
        "multi_timeframe_confluence": True,
        "ai_intelligence_synthesis": True
    }
```

### **Dynamic Contract Discovery**
```python
# Automatic discovery of active contracts for intelligence analysis
async def discover_intelligence_contracts():
    """Discover most liquid contracts for optimal intelligence extraction"""
    
    contracts = []
    for base_config in IntelligenceSymbolConfig.PRIMARY_INTELLIGENCE_SYMBOLS:
        # Find most active contract for this symbol
        active_contract = await ibkr_client.find_most_liquid_contract(
            base_symbol=base_config["symbol"],
            min_volume=50000,  # Minimum volume for intelligence quality
            max_days_to_expiry=90  # Active contract selection
        )
        
        contracts.append({
            "symbol": active_contract.localSymbol,
            "base_symbol": base_config["symbol"],
            "intelligence_priority": base_config["priority"],
            "intelligence_focus": base_config["intelligence_focus"]
        })
    
    return contracts
```

---

##  **Intelligence Configuration Best Practices**

### **Data Quality for Intelligence**
- **High Volume Required**: Only analyze liquid contracts with sufficient volume
- **Tight Spreads**: Reject data with spreads wider than normal ranges
- **Real-Time Processing**: Minimize latency between data collection and intelligence generation
- **Multiple Timeframe Validation**: Confirm patterns across multiple timeframes

### **Intelligence Processing Optimization**
- **Symbol Prioritization**: Focus processing power on most liquid, highest-signal contracts
- **Dynamic Rebalancing**: Automatically adjust to changing market conditions and volatility
- **Quality Metrics**: Continuously monitor intelligence quality and accuracy
- **Adaptive Thresholds**: Adjust confidence thresholds based on market regime and historical performance

This configuration provides the foundation for high-quality market intelligence extraction while maintaining focus on the most liquid and informative instruments for pattern recognition and analysis.