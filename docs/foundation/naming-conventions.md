# Naming Conventions

**Version:** 2.8
**Status:** current
**Last Updated:** 2026-05-10
**Principle:** A service's *concept name* (`snake_case`, no suffix) determines all its derived names across every layer. Given `feature_pipeline`, every layer's name is mechanically derivable — no lookup needed.

## Cross-Layer Transformation Rules

| Layer | Pattern | Example (`alpha_signal`) |
|-------|---------|------------------------------|
| Python file (Service) | `<concept>_service.py` | `alpha_signal_service.py` |
| Python file (Agent) | `<concept>_agent.py` | `alpha_signal_agent.py` |
| Python file (Plugin) | `src/intelligence/trading/<concept>.py` | `alpha_signal.py` |
| Python class (Service) | `PascalCase` + `Service` | `AlphaSignalService` |
| Python class (Agent) | `PascalCase` + agent role suffix | `AlphaSignalComputeAgent` |
| Python class (Plugin) | `PascalCase` + `Plugin` | `AlphaSignalPlugin` |
| Systemd unit | `indicagent-<concept-kebab>.service` | `indicagent-alpha-signal.service` |
| Kafka topic fn | `topic_<concept>()` in `stream_keys.py` | `topic_alpha_signal()` |
| Kafka topic string | `<env>.<domain>[.<sublayer>]` (dots only) | `dev.alpha_signal` |
| DB table | `snake_case` plural noun | `alpha_signals` |
| DB columns | `snake_case` | `ts`, `symbol`, `tf`, `i7` |

## Agent Role Suffixes

- `ProviderAgent` — external source→Kafka, no compute/DB
- `ComputeAgent` — math/stats transform, DB-ignorant
- `GeneratorAgent` — signal/trade fire
- `WriterAgent` — DB persistence
- `TrackerAgent` — business object lifecycle
- `AuditorAgent` — data integrity validation + self-healing

## Per-Layer Rules

**Python**
- Plugins: `snake_case.py` file (short name) / `PascalCasePlugin` class — `adx.py` → `ADXPlugin`
- Aggregators/results: `PascalCase` no suffix — `CISScorer`, `AggregatedResult`
- Functions/methods: `snake_case`. Constants: `UPPER_SNAKE_CASE`. Private attrs: `_snake_case`.

**Kafka topics** (always via `src/core/stream_keys.py`, never hardcoded)
- Functions: `topic_<output_domain>()` — singular noun describing what flows in the topic
- Strings: `<env>.<domain>` or `<env>.<domain>.<sublayer>` — **dots only, never colons**
- Consumer groups: `<concept>_consumer` (idempotent on restart)

**Database**
- Tables: `snake_case` plural nouns. Columns: `snake_case` — timestamp is `ts` (not `feature_ts`); always `symbol`, `tf`
- Views: `<source_table>_<timeframe>` — `ohlcv_15m`, `market_data_5m`. Migrations: `NNN_description.sql`.

**Systemd / Infrastructure**
- Units: installed in `/etc/systemd/system/`; source files in `services/`. `production/systemd/` is a reference dir — do not treat as authoritative.
- Logs: `logs/<python_service_filename>.log` — read directly for structured output (journald shows only `print()`)

**Tests / TypeScript / Docs**
- Tests: `tests/unit/test_<module>.py`; functions `test_<what>_<condition>`
- TypeScript: components `PascalCase.tsx`, hooks `use-kebab-case.ts`, utils `kebab-case.ts`
- Docs: `kebab-case.md`; plan docs `YYYY-MM-DD-<topic>.md`; uppercase `README.md`/`CLAUDE.md`/`CHANGELOG.md`

---

## Intelligence Tier Naming System

Tiers have both a code (`I1`–`I8`) and a functional name. Both are valid in documentation and code; use whichever aids clarity.

### Tier Mapping

| Code | Functional Name | `snake_case` | Usage |
|------|----------------|--------------|-------|
| I1 | Technical Indicators | `technical_indicators` | Plugin tier key, log tags |
| I2 | Composite Events | `composite_events` | |
| I3 | Market Structure | `market_structure` | |
| I4 | Market Context | `market_context` | Regime detection, volatility, session |
| I5 | Pattern Intelligence | `pattern_intelligence` | |
| I6 | Confluence Synthesis | `confluence_synthesis` | Also: `smc` shorthand in event keys |
| I7 | Trading Signals | `trading_signals` | |
| I8 | AI Narrative | `ai_narrative` | |

### Usage Guidelines

- **In code:** Use tier codes (`I1`–`I8`) for constants and tier keys; functional names as dict keys and topic suffixes
- **In docs:** Tier codes for brevity; functional names when clarity matters
- **In logs:** Tier codes preferred for width constraints
- **In metrics:** Dual label `I1:technical_indicators` via `format_tier_label()`
- **In DB columns:** Functional names only (Phase 104 schema)
- **In APIs:** Functional names for external consumers

### Conversion API

`src/intelligence/tier_aliases.py` provides programmatic conversion:

```python
from src.intelligence.tier_aliases import (
    tier_to_functional,   # "I1" → "technical_indicators"
    functional_to_tier,   # "trading_signals" → "I7"
    format_tier_label,    # "I1" → "I1:technical_indicators" (for metrics)
)
```

See `src/intelligence/register_plugins.py` `TIER_I1`..`TIER_I7` for the canonical tier lists.
