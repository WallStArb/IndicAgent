<!-- generated-by: gsd-doc-writer -->
# Plugin Reference Overview

**Version:** 2.8
**Status:** current
**Last Updated:** 2026-05-27

Plugin system reference. Authoritative plugin counts and tier lists are in `TIER_I1`…`TIER_I7` constants in `src/intelligence/register_plugins.py`.

---

## Plugin Protocol

Plugins implement the `PatternPlugin` protocol from `src/intelligence/plugins.py`. Register in `register_all_plugins()` and add to the matching `TIER_*` constant in `src/intelligence/register_plugins.py` (single source of truth). `registry.validate_tier()` hard-crashes at startup on unknown names.

## Registration

`TIER_I1`…`TIER_I7` constants in `src/intelligence/register_plugins.py`. Services import them — never define local string lists.

---

## Plugin Directories

Counts below are from `register_plugins.py` as of 2026-05-27:

| Tier | File | Count |
|------|------|-------|
| I1: Technical Indicators | [i1-indicators.md](i1-indicators.md) | 29 |
| I2: Composite | — | 11 |
| I3: Market Structure | [i3-structure.md](i3-structure.md) | 9 |
| I4: Context Classification | [i4-context.md](i4-context.md) | 13 |
| I5: Pattern Detection | [i5-patterns.md](i5-patterns.md) | 16 |
| I6: Smart Money Concepts | [i6-smart-money.md](i6-smart-money.md) | 7 |
| I7: Trading Setups | [i7-trading.md](i7-trading.md) | 37 |

**Total: 122 registered plugins** across I1-I7 (CLAUDE.md cites 132 including 2 aggregation components and additional registered plugins — use `register_plugins.py` as the authoritative count).

The signal aggregator (`aggregator.py`) uses CISScorer (6-bucket weighted scorer) replacing winner-pick logic. See `src/intelligence/trading/cis_scorer.py`.

---

**Guide:** [Adding Plugins](../../guides/adding-plugins.md)
**Concepts:** [Plugin Architecture](../../concepts/plugin-architecture.md)
