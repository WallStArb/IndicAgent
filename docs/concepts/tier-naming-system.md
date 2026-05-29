# Intelligence Tier Naming System

> **Domain:** Intelligence — deep-dive companion to [`intelligence-foundation.md`](../intelligence/intelligence-foundation.md)

**Version:** 2.8
**Last Updated:** 2026-05-25
**Status:** Hybrid system - Internal tier codes + External functional names

## Overview

IndicAgent uses a **dual naming system** for intelligence tiers:

1. **Internal Tier Codes (I1-I8)**: Used in code for brevity and architectural clarity
2. **External Functional Names**: Used in APIs, metrics, documentation, and user-facing content

This approach maintains clean, concise code while providing self-documenting names for external consumers.

## Tier Mapping

| Tier | Functional Name | Description |
|------|----------------|-------------|
| **I1** | `technical_indicators` | Mathematical features from OHLCV data (RSI, MACD, ATR, etc.) |
| **I2** | `composite_events` | Discrete market events and crossovers |
| **I3** | `market_structure` | Swing patterns, support/resistance, market geometry |
| **I4** | `market_context` | Regime detection, volatility classification, session context |
| **I5** | `pattern_intelligence` | Classic chart patterns and formations |
| **I6** | `confluence_synthesis` | Cross-timeframe and multi-tier confluence analysis |
| **I7** | `trading_signals` | Trading setup detection and signal generation |
| **I8** | `ai_narrative` | LLM-powered market narrative and analysis |

**Documentation Format:** Use `I{N}: {Functional Name} ({functional_name})`
- Example: "I1: Technical Indicators (technical_indicators)"
- Example: "I7: Trading Signals (trading_signals)"

## Usage Guidelines

### Documentation

**Use both tier codes and functional names** together for maximum clarity:

```markdown
## I1: Technical Indicators (technical_indicators)

The I1 tier extracts mathematical features from OHLCV data...

## I7: Trading Signals (trading_signals)

I7 setup plugins generate trading signals...
```

**Format:** `I{N}: {Functional Name} ({functional_name})`

### Internal Code (Python)

**Use tier codes** for constants, variables, and function names:

```python
# ✅ Good - Internal code uses tier codes
from src.intelligence.register_plugins import TIER_I1, TIER_I7

def process_i1_features():
    pass

class I7Plugin:
    tier = "I7"
```

### External APIs (REST/SSE)

**Use functional names** for API responses and user-facing content:

```python
# ✅ Good - API responses use functional names
{
    "feature_type": "technical_indicators",
    "signals": [...],
    "analysis_layer": "trading_signals"
}
```

### Metrics and Observability

**Use dual labels** for metrics - both code and functional name:

```python
# ✅ Good - Metrics use dual labels
from src.observability.metrics import format_tier_label

PLUGIN_DURATION_MS.record(42.5, {
    "plugin": "rsi",
    "tier": format_tier_label("I1")  # "I1:technical_indicators"
})
```

### Database Columns

**Functional names only** - database schema uses semantic column names:

```sql
-- ✅ Database uses functional names
CREATE TABLE intelligence_features (
    technical_indicators JSONB,  -- NOT i1
    trading_signals JSONB,       -- NOT i7
    pattern_detections JSONB,    -- NOT i3
    ...
);
```

## Conversion API

```python
from src.intelligence.tier_aliases import (
    tier_to_functional,      # I1 → technical_indicators
    functional_to_tier,      # trading_signals → I7
    get_tier_description,    # I1 → "Technical Indicators - Mathematical features..."
    all_tier_codes,          # {"I1", "I2", ..., "I8"}
    all_functional_names,    # {"technical_indicators", "trading_signals", ...}
)

# Convert tier code to functional name
tier_to_functional("I7")  # → "trading_signals"

# Convert functional name to tier code
functional_to_tier("market_context")  # → "I4"

# Get human-readable description
get_tier_description("I6")
# → "Confluence Synthesis - Cross-timeframe and multi-tier synthesis"
```

## Rationale

### Why Keep Tier Codes (I1-I8)?

1. **Architectural Clarity**: Tier boundaries are meaningful - they represent computational phases
2. **Concise Notation**: `I7` is cleaner than `trading_signals` in code
3. **Proven System**: 132 plugins organized into coherent computational groups
4. **Low Refactor Risk**: 2,000+ references across codebase

### Why Add Functional Names?

1. **Self-Documenting**: New developers understand `trading_signals` immediately
2. **API Clarity**: External consumers see descriptive names, not codes
3. **Consistent with DB**: Database columns use functional names (Phase 104)
4. **Better Metrics**: Grafana dashboards show readable tier labels

## Migration Status

- ✅ **Database**: Functional names (Phase 104, completed)
- ✅ **Conversion API**: `tier_aliases.py` module created
- ✅ **Metrics**: `format_tier_label()` function available
- ⏳ **API Routes**: Pending update for next API version
- ⏳ **Documentation**: Partially updated, ongoing

## Examples

### Metric Labels (Prometheus/Grafana)
```
intelligence_pipeline_plugin_duration_ms{plugin="rsi", tier="I1:technical_indicators"} 42.5
intelligence_pipeline_signals_emitted_total{tier="I7:trading_signals", direction="long"} 156
```

### API Responses
```json
{
    "data": {
        "technical_indicators": {"rsi_14": 65.2, "macd": {...}},
        "market_context": {"volatility_regime": "normal", "trend_regime": "uptrend"},
        "trading_signals": [...]
    }
}
```

### Code Comments
```python
# I1: Technical Indicators (technical_indicators) - Extract mathematical features from OHLCV
# I7: Trading Signals (trading_signals) - Generate trading setup signals
```

### Documentation Examples

**Section Headers:**
```markdown
## I1: Technical Indicators (technical_indicators)

## I7: Trading Signals (trading_signals)
```

**Inline References:**
```markdown
The I1: Technical Indicators (technical_indicators) tier extracts mathematical features...
I7: Trading Signals (trading_signals) plugins generate trading setup signals...
```

**Table Format:**
| Tier | Name | Plugin Count |
|------|------|--------------|
| I1: Technical Indicators | technical_indicators | 28 |
| I7: Trading Signals | trading_signals | 36 |

## See Also

- [Intelligence Tiers Detail](intelligence-tiers.md) - Full tier documentation
- [Plugin Architecture](plugin-architecture.md) - Plugin registration and tiers
- [Phase 104 Schema Changes](../planning/phases/phase-104/) - Database column renaming