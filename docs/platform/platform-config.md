# Platform Config — APR Namespace Registry

**Version:** 1.0
**Status:** current
**Last Updated:** 2026-06-16

---

## Purpose

This document is the IndicAgent-specific companion to `docs/foundation/adaptive-parameter-registry.md`. It contains the live namespace registry: every APR prefix in use, its natural writer, ML target status, OPS_PREFIXES membership, and current key count.

The foundation doc explains the concept and the patterns. This doc tells you what actually exists in `config_state` and what is still missing.

---

## Namespace Registry

All keys follow `<domain>.<concept>.<param>`. The prefix determines which OPS category the parameter belongs to. `ConfigService.OPS_PREFIXES` (line 39 of `src/config/config_service.py`) is the authoritative allowlist — a prefix absent from this tuple will reject runtime `ConfigService.set()` calls with `ConfigValidationError`.
<!-- src: src/config/config_service.py:39 — OPS_PREFIXES tuple -->

Verified against `config_state` 2026-06-16.
<!-- src: PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "SELECT left(config_key, position('.' in config_key)) as prefix, count(*) FROM config_state GROUP BY 1 ORDER BY 1;" -->

| Prefix | Domain | Natural writer | ML target? | OPS_PREFIXES? | Live keys | Notes |
|--------|--------|---------------|------------|---------------|-----------|-------|
| `threshold.*` | Plugin detection gates | ML discovery (Level 3) | Yes | Yes | 58 | Phase 125 complete — gates across all I7 plugins |
| `weights.*` | Confidence composite weights | ML discovery | Yes | **No** | 48 | Phase 125 complete; OPS_PREFIXES gap blocks runtime writes (v2.10) |
| `feature.*` | Indicator parameters (periods, windows) | User / ML discovery | Yes | Yes | 21 | Phase 125 complete — indicator periods, zone geometry |
| `regime.*` | Regime classification gates | Operator | Possibly | Yes | 2 | Seeded Phase 109 |
| `shadow.*` | Shadow governance thresholds | Operator | No | **No** | 0 | Not yet seeded; OPS_PREFIXES entry required before use |
| `signal.*` | Signal lifecycle (TTL, activation) | Operator | No | **No** | 0 | Not yet seeded; OPS_PREFIXES entry required before use |
| `swarm.*` | AI swarm agent parameters | Operator | Possibly | Yes | 5 | Seeded Phase 109 |
| `roll.*` | Futures roll detection | Operator | No | Yes | 6 | Seeded Phase 109 |
| `cross_asset.*` | Cross-asset correlation windows | ML discovery | Yes | Yes | 1 | Seeded (correlation windows) |
| `macro.*` | Macro context windows | Operator | Possibly | Yes | 1 | Seeded (macro windows) |
| `alert.*` | Alert thresholds and rate limits | Operator | No | Yes | 21 | Seeded (alert thresholds) |
| `ai.*` | AI agent parameters | Operator | Possibly | Yes | 4 | Seeded (AI agent params) |
| `ui.*` | Dashboard display preferences | User | No | **No** | 0 | Not yet seeded; `"ui."` must be added to OPS_PREFIXES first |

---

## OPS_PREFIXES Gaps

Four valid namespaces are absent from `ConfigService.OPS_PREFIXES`:

**`weights.*`** — 48 live keys exist in `config_state` (seeded via migration) but `ConfigService.set()` will raise `ConfigValidationError` for any weights key. ML discovery cannot write learned weight values at runtime until this is fixed. Tracked in the v2.10 refactor plan.
<!-- src: docs/plans/2026-06-14-v2.10-signal-architecture-refactor.md -->

**`shadow.*`** — No keys seeded yet. Governance thresholds (`shadow.promotion.min_samples`, `shadow.promotion.ci_lower_floor`) should be migrated out of hard-coded constants in `GraduationAnalyzer` when this namespace is activated.

**`signal.*`** — No keys seeded yet. Signal lifecycle parameters (TTL bars, activation windows) currently live as hard-coded constants.

**`ui.*`** — No keys seeded yet. The dashboard `/config/parameters` uses a special OPS path — add `"ui."` to `OPS_PREFIXES` before seeding any `ui.*` keys.

**To activate any unregistered namespace:** (1) add the prefix string to the `OPS_PREFIXES` tuple in `src/config/config_service.py:39`; (2) seed keys in a migration with INSERT into `config_schema` + `config_state`; (3) load via `ConfigService.get()` at service init.
<!-- src: src/config/config_service.py:39 -->

---

## Key Naming Examples

Representative examples across the active namespaces:

```
threshold.trend_following.regime_min          # float, gate in TrendFollowingPlugin
threshold.ofi_continuation.min_bars           # int, streak gate in OFIContinuationPlugin
threshold.ofi_continuation.magnitude_floors   # json, per-instrument dict
feature.sma.periods                           # json, list e.g. [20, 50, 100, 200]
feature.rsi.period                            # int, default 14
feature.atr.period                            # int, default 14
shadow.promotion.min_samples                  # int, n >= 100 gate (not yet seeded)
shadow.promotion.ci_lower_floor               # float, bootstrap_ci_lower > 0.0 (not yet seeded)
ui.signals.default_timeframe                  # str, e.g. "15m" (not yet seeded)
ui.signals.max_active_displayed               # int, e.g. 50 (not yet seeded)
ui.alerts.confidence_highlight_threshold      # float, e.g. 0.75 (not yet seeded)
```

---

## See Also

- `docs/foundation/adaptive-parameter-registry.md` — concept, lifecycle, adding a parameter, what doesn't belong
- `src/config/config_service.py` — `OPS_PREFIXES`, `ConfigService.get()`, `ConfigService.set()`
- `src/config/settings.py` — `Settings`, instrument and contract definitions (distinct from APR)
