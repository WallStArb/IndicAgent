# Symbol Configuration Alignment - IndicAgent Platform

Version: 1.0.1
Last Updated: 2025-08-09
Status: Centralized Configuration 

## **Single Source of Truth Implementation**

The IndicAgent platform now uses a centralized symbol configuration system to ensure consistency across all components.

### **Base Symbols (Single Source of Truth)**

| Symbol | Name | Exchange | Point Value | Tick Size | Status |
|--------|------|----------|-------------|-----------|--------|
| **ES** | E-mini S&P 500 | CME | $50 | 0.25 |  ACTIVE |
| **NQ** | E-mini Nasdaq | CME | $20 | 0.25 |  ACTIVE |
| **RTY** | E-mini Russell 2000 | CME | $50 | 0.10 |  ACTIVE |
| **CL** | Crude Oil WTI | NYMEX | $1,000 | 0.01 |  ACTIVE |
| **NG** | Natural Gas | NYMEX | $10,000 | 0.001 |  ACTIVE |
| **GC** | Gold | COMEX | $100 | 0.10 |  ACTIVE |
| **SI** | Silver | COMEX | $5,000 | 0.005 |  ACTIVE |
| **PL** | Platinum | NYMEX | $50 | 0.10 |  ACTIVE |
| **HG** | Copper | COMEX | $25,000 | 0.0005 |  ACTIVE |
| **VX** | CBOE VIX Futures | CFE | $1,000 | 0.05 |  ACTIVE |

### **Active Contracts (Dynamically Generated)**

The system automatically generates active contracts for each base symbol:

- **ESU5, ESZ5** - S&P 500 E-mini contracts
- **NQU5, NQZ5** - Nasdaq E-mini contracts  
- **RTYU5, RTYZ5** - Russell E-mini contracts
- **CLU5, CLZ5** - Crude Oil contracts
- **NGU25, NGZ25** - Natural Gas contracts
- **GCV5, GCZ5** - Gold contracts
- **SIV5, SIZ5** - Silver contracts
- **PLV5, PLZ5** - Platinum contracts
- **HGV5, HGZ5** - Copper contracts
- **VXU5, VXZ5** - VIX contracts

## **Configuration Files Updated**

### **1. `config/symbol_config.py`**
- **Centralized base symbols** with complete metadata
- **Dynamic contract generation** based on current date
- **Unified access methods** for all components

### **2. `config/settings.py`**
- **Removed hardcoded symbols**
- **Uses centralized configuration** via properties
- **Dynamic symbol loading** from symbol_config

### **3. Service Components Updated**
- **`services/indicator_processor_service.py`** - Uses `get_active_contracts()`
- **`services/timeframe_builder_service.py`** - Uses `get_active_contracts()`
- **`src/core/unified_market_processor.py`** - Uses `get_active_contracts()`
- **`src/core/bar_completion_engine.py`** - Uses `get_all_symbols()`
- **`production/daemons/high_frequency_tws_daemon.py`** - Uses centralized config

## **API Methods Available**

### **Base Symbol Access**
```python
from config.symbol_config import get_base_symbols, get_base_symbol_info

# Get all base symbols
symbols = get_base_symbols()  # ['ES', 'NQ', 'RTY', 'CL', 'NG', 'GC', 'SI', 'PL', 'HG', 'VX']

# Get symbol information
info = get_base_symbol_info('ES')  # {'name': 'E-mini S&P 500', 'exchange': 'CME', ...}
```

### **Active Contract Access**
```python
from config.symbol_config import get_active_contracts, get_all_symbols

# Get active contracts only
contracts = get_active_contracts()  # ['ESU5', 'ESZ5', 'NQU5', ...]

# Get all symbols (base + contracts)
all_symbols = get_all_symbols()  # ['ES', 'NQ', 'RTY', ..., 'ESU5', 'ESZ5', ...]
```

### **Symbol Information**
```python
from config.symbol_config import get_symbol_display_name, get_exchange, get_point_value, get_tick_size

# Get symbol details
display_name = get_symbol_display_name('ES')  # 'E-mini S&P 500'
exchange = get_exchange('ES')  # 'CME'
point_value = get_point_value('ES')  # 50
tick_size = get_tick_size('ES')  # 0.25
```

## **Benefits of Centralized Configuration**

### **1. Consistency**
- **Single source of truth** for all symbol definitions
- **No more misaligned configurations** across services
- **Automatic updates** when base symbols change

### **2. Maintainability**
- **Easy symbol additions** in one location
- **Centralized metadata** (exchange, point value, tick size)
- **Dynamic contract generation** based on current date

### **3. Flexibility**
- **Profile-based symbol selection** for different use cases
- **Easy rollover management** for futures contracts
- **Extensible for new symbol types**

### **4. Performance**
- **Reduced configuration overhead** across services
- **Optimized symbol lookups** with cached information
- **Consistent data structures** across components

## **Migration Status**

| Component | Status | Updated |
|-----------|--------|---------|
| `config/symbol_config.py` |  Complete | Centralized base symbols |
| `config/settings.py` |  Complete | Uses centralized config |
| `services/indicator_processor_service.py` |  Complete | Uses `get_active_contracts()` |
| `services/timeframe_builder_service.py` |  Complete | Uses `get_active_contracts()` |
| `src/core/unified_market_processor.py` |  Complete | Uses `get_active_contracts()` |
| `src/core/bar_completion_engine.py` |  Complete | Uses `get_all_symbols()` |
| `production/daemons/high_frequency_tws_daemon.py` |  Complete | Uses centralized config |

## **Next Steps**

1. **Test all services** with new configuration
2. **Verify data collection** for all symbols
3. **Monitor performance** with expanded symbol set
4. **Implement rollover logic** for automatic contract updates
5. **Add symbol validation** for new additions

**Version:** 1.0.0, **Last Updated:** 2025-01-27, **Status:** Centralized Configuration  