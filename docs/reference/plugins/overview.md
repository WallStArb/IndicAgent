# Plugin Reference Overview

All 57 registered plugins.

---

## Plugin Protocol

Plugins implement the `PatternPlugin` protocol from `src/intelligence/plugins.py`. Register in `register_all_plugins()` and add to the matching `TIER_*` constant in `src/intelligence/register_plugins.py` (single source of truth). `registry.validate_tier()` hard-crashes at startup on unknown names.

## Registration

`TIER_I1`…`TIER_I7` constants in `src/intelligence/register_plugins.py`. Services import them — never define local string lists.

---

## Plugin Directories

- [I1: Technical Indicators](i1-indicators.md) — 23 plugins
- [I3: Market Structure](i3-structure.md) — 3 plugins
- [I4: Context Classification](i4-context.md) — 5 plugins
- [I5: Pattern Detection](i5-patterns.md) — 8 plugins
- [I6: Smart Money Concepts](i6-smart-money.md) — 6 plugins
- [I6: Cross-TF Confluence](i6-confluence.md) — 1 plugin
- [I7: Trading Setups](i7-trading.md) — 9 plugins
- [I7: Signal Aggregation](i7-aggregation.md) — 4 components (aggregator, ledger, lifecycle, sizer)

**Total:** 57 plugins + 4 aggregation components

See [STATUS.md](../../STATUS.md) for current counts.

---

**Guide:** [Adding Plugins](../../guides/adding-plugins.md)
**Concepts:** [Plugin Architecture](../../concepts/plugin-architecture.md)
