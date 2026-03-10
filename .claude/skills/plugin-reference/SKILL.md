---
name: plugin-reference
description: Use when implementing a new intelligence plugin, needing the plugin protocol interface, or checking tier directory conventions and registration patterns
---

# IndicAgent Plugin Reference

## Plugin Protocol

Both `IndicatorPlugin` and `PatternPlugin` share the same interface (defined in `src/intelligence/plugins.py`):

```python
@dataclass
class MyPlugin:
    name: str = "tier_PluginName"           # prefix: struct_, ctx_, smc_, i6_, or bare for I1/I5
    outputs: set[str] = frozenset({...})    # output field names
    min_lookback: int = 60                  # minimum bars needed
    supports_incremental: bool = False      # True only for I1 indicators
    capability_tags: set[str] = frozenset({"smart_money"})  # tier tag
    inputs: list[InputSpec] = (InputSpec(symbol=".*", timeframe="1m", lookback=120),)

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        df = frames.get("main")  # OHLCV DataFrame
        if df is None or len(df) < self.min_lookback:
            return {}
        # ... compute and return dict of output fields
        return {"field_name": value, ...}

    def compute_next(self, windows: dict[str, Any]) -> dict[str, Any]:
        return {}  # Only implement for incremental plugins

plugin = MyPlugin()  # Module-level instance required
```

## Tier Map

| Tier | Directory | Plugin List | capability_tags | Name Prefix | Registration |
|------|-----------|-------------|-----------------|-------------|-------------|
| I1 | `src/intelligence/indicators/` | `INDICATOR_PLUGINS` | `{"indicator"}` | bare | `register_indicator()` |
| I3 | `src/intelligence/structure/` | `I3_PLUGINS` | `{"structure"}` | `struct_` | `register_pattern()` |
| I4 | `src/intelligence/context/` | `I4_PLUGINS` | `{"context"}` | `ctx_` | `register_pattern()` |
| I5 | `src/intelligence/patterns/` | `I5_PLUGINS` | `{"pattern"}` | bare | `register_pattern()` |
| SMC | `src/intelligence/smart_money/` | `SMC_PLUGINS` | `{"smart_money"}` | `smc_` | `register_pattern()` |
| I6 | `src/intelligence/confluence/` | `I6_PLUGINS` | `{"confluence"}` | `i6_` | `register_pattern()` |

## `frames` Dict Structure

Plugins receive `frames` with these keys:
- `"main"` — OHLCV DataFrame (columns: open, high, low, close, volume, timestamp)
- `"features"` — dict of I1 indicator outputs (available to I4+ plugins that need it)
- `"tf_1m"`, `"tf_5m"`, etc. — cross-timeframe OHLCV DataFrames (I6 only)
- `"intel_1m"`, `"intel_5m"`, etc. — cached intelligence dicts from other timeframes (I6 only)

## Registration

In `src/intelligence/register_plugins.py`:
```python
from .smart_money.my_plugin import plugin as my_plugin
# ... in register_all_plugins():
registry.register_pattern(my_plugin)  # or register_indicator() for I1
```

## Test Convention

- File: `tests/unit/intelligence/test_<tier>_plugins.py` (or add to existing tier test file)
- Generate realistic test data with enough bars (min_lookback + buffer)
- Test: returns expected keys, handles insufficient data, edge cases
- Run: `python -m pytest tests/unit/intelligence/test_<file>.py -v`

## Pipeline Order

`I1 → I3 → I4 → I5 → SMC → I6 → Redis → SSE → Dashboard`
