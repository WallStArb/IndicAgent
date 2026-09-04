<!-- generated-by: gsd-doc-writer -->
# Plugin Reference Overview

**Version:** 3.0
**Status:** current
**Last Updated:** 2026-09-04

> **ARCHIVED SYSTEM (v2.x, no live consumer since 2026-07-02).** This describes the I1-I7 plugin pipeline. It is not the compute path for the live v3.0 system — that is Feature Factory (`src/intelligence/feature_factory.py`, run by `services/feature_vector_pipeline.py`, `indicagent-feature-vector-pipeline.service`, `active running`). `register_plugins.py` (below) has no live consumer either: the only in-repo callers are `services/shadow_validator.py` (a weekly, promotion-only oneshot) and internal plugin-DAG infrastructure (`plugins/base.py`, `plugin_validator.py`, `pipeline/executor.py`) — not `feature_vector_pipeline.py`, which imports Feature Factory directly and never touches this registry. Content below is accurate as a description of the archived system's structure — kept for historical reference and in case the subsystem is ever formally reactivated or ported. Do not cite plugin counts or tier behavior here as describing what computes signals today. See `src/intelligence/CLAUDE.md` for the fuller archived-system banner and `src/intelligence/register_plugins.py` for the authoritative source.

Plugin counts and tier lists below are read directly from the `TIER_I1`…`TIER_I7` constants in `src/intelligence/register_plugins.py`, verified 2026-09-04.

---

## Plugin Protocol

Plugins implement the `PatternPlugin` protocol from `src/intelligence/plugins.py`. Register in `register_all_plugins()` and add to the matching `TIER_*` constant in `src/intelligence/register_plugins.py` (single source of truth for the archived system). `registry.validate_tier()` hard-crashes at startup on unknown names — but "startup" here means the archived `intelligence_pipeline.py`/`shadow_validator.py` code paths, not the live v3.0 daemon.

## Registration

`TIER_I1`…`TIER_I7` constants in `src/intelligence/register_plugins.py`.

## Source Code Location

Plugin source has partially moved into an `archive/` subpackage as part of the v2.x archival (verified via `register_plugins.py` imports, 2026-09-04):

| Tier | Source path |
|------|-------------|
| I1 (indicators) | `src/intelligence/features/i1_indicators/` — not under `archive/` |
| I2 (composites) | `src/intelligence/composites/` — not under `archive/` |
| I3 (structure) | `src/intelligence/features/i3_structure/` — not under `archive/` |
| I4 (context) | `src/intelligence/context/` — not under `archive/` |
| I5 (patterns) | `src/intelligence/archive/i5_patterns/` |
| I6 (confluence/CTF) | `src/intelligence/archive/confluence/` |
| SMC (smart money) | `src/intelligence/archive/smc_context/` |
| I7 (trading setups) | `src/intelligence/archive/trading_i7/` |

I1-I4 plugin source has not physically moved (it predates and is separate from the `feature_factory.py` module the live pipeline actually runs); I5-I7 and SMC have moved into `archive/` outright. Neither path is executed by the live v3.0 pipeline.

---

## Plugin Directories

Counts below are from `register_plugins.py` (`len(TIER_I*)`), verified 2026-09-04:

| Tier | Count |
|------|-------|
| I1: Technical Indicators | 28 |
| I2: Composite | 10 |
| I3: Market Structure | 8 |
| I4: Context Classification | 14 |
| I5: Pattern Detection | 16 |
| SMC: Smart Money Concepts | 16 |
| I6: Confluence | 6 |
| I7: Trading Setups | 35 |

**Total: 133 registered plugins across I1-I7 + SMC** (28+10+8+14+16+16+6+35). This is the count in the archived registry, not a count of anything computing signals live today. No per-file catalogs (e.g. `i1-indicators.md`) exist in this directory — see `docs/reference/README.md` for what's actually linkable.

The signal aggregator (`aggregator.py`) uses CISScorer (multi-bucket weighted scorer). See `src/intelligence/trading/cis_scorer.py` — this file is not part of the `archive/` tree (it postdates I5-I7 archival and belongs to the shared I7 utility layer described in `src/intelligence/CLAUDE.md`), but it is likewise not invoked by the live v3.0 pipeline.

---

**Archived-system detail:** `src/intelligence/CLAUDE.md`
**Live compute path:** `services/feature_vector_pipeline.py`, `src/intelligence/feature_factory.py`
