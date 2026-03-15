# Documentation Standards

**Last Updated:** 2026-03-15
**Status:** Current

Personal reference for consistent doc and code naming across the project.

---

## File & Directory Naming

| Context | Convention | Example |
|---------|-----------|---------|
| Docs | kebab-case | `ai-intelligence-architecture.md` |
| Standard root files | UPPERCASE | `README.md`, `CHANGELOG.md`, `CLAUDE.md` |
| Directories | lowercase, hyphens | `docs/architecture/`, `docs/getting-started/` |
| Plan docs | date-prefixed kebab | `2026-03-15-signal-lifecycle-redesign.md` |

---

## Document Headers

All docs should open with:

```markdown
# Title

**Status:** draft | design | current | archived
**Priority:** high | medium | low | future   (ideas docs only)
**Last Updated:** YYYY-MM-DD
```

Status values: `draft` → `design` → `current` → `archived`

---

## Section Order

**Architecture / technical docs:**
1. What this is / current state
2. How it works (design / data flow)
3. Integration points / code examples
4. Gotchas / known issues
5. Next steps (if applicable)

**Ideas docs:**
1. Context (what gap this fills)
2. The idea (what it does)
3. Why it matters (what's different from what exists)
4. Implementation sketch
5. Open questions / trigger conditions

---

## Cross-References

Use relative paths — never absolute:

```markdown
[Architecture](../architecture/layered-architecture.md)   ✓
[Architecture](/docs/architecture/layered-architecture.md) ✗
```

---

## Header Hierarchy

```markdown
# Document Title
## Major Section
### Subsection
#### Detail (use sparingly)
```

---

## Code Naming Conventions

See also: `CLAUDE.md → Development Standards → Naming Conventions`

### Python

| Thing | Convention | Example |
|-------|-----------|---------|
| Plugin classes | `PascalCase` + `Plugin` suffix | `MACDPlugin`, `BollingerPlugin` |
| Aggregator/utility classes | `PascalCase`, no suffix required | `CISScorer`, `TradeFramer` |
| Result/data classes | `PascalCase` + `Result` or descriptive | `CISResult`, `AggregatedResult` |
| Service files | `snake_case_service.py` | `signal_generator_service.py` |
| Core modules | `snake_case.py` | `stream_keys.py`, `database_manager.py` |
| Plugin files | `snake_case.py`, short and descriptive | `adx.py`, `bollinger.py`, `choch_reversal.py` |
| Functions | `snake_case` | `compute_next()`, `get_active_contracts()` |
| Constants | `UPPER_SNAKE_CASE` | `TIER_I1`, `PLUGIN_METRICS_SAMPLE_RATE` |
| Private attrs | `_snake_case` leading underscore | `_regime_cache`, `_plugin_states` |
| Topic builders | `topic_<thing>` | `topic_indicators()`, `topic_signals_aggregated()` |

### Redpanda Topics

Topics use **dots**, not colons (colons are invalid Kafka topic names):

```
{env}.market.bars
{env}.indicators
{env}.intelligence
{env}.intelligence.i7
{env}.signals.aggregated
```

Always built via `src/core/stream_keys.py` — never construct topic strings manually with f-strings.

### Database

| Thing | Convention | Example |
|-------|-----------|---------|
| Tables | `snake_case` | `intelligence_features`, `signal_ledger` |
| Columns | `snake_case` | `feature_ts`, `pnl_r`, `bar_close` |
| Indexes | implicit (TimescaleDB) or `idx_<table>_<cols>` | `idx_signal_ledger_symbol_ts` |
| Migrations | `NNN_description.sql` (zero-padded) | `030_drift_state.sql` |
| Views / caggs | `<source>_<tf>` | `ohlcv_15m`, `market_data_5m` |

### Systemd Services

```
indicagent-<name>.service
```

Examples: `indicagent-indicator.service`, `indicagent-signal-lifecycle.service`

### Tests

```
tests/unit/test_<module>.py
tests/unit/<domain>_tests/test_<thing>.py
tests/integration/test_<thing>.py
```

Test functions: `test_<what>_<condition>` — `test_compute_next_returns_macd_when_warmed_up`

### TypeScript / Dashboard

| Thing | Convention | Example |
|-------|-----------|---------|
| Components | `PascalCase.tsx` | `SignalCard.tsx`, `SkeletonCard.tsx` |
| Hooks | `use-kebab-case.ts` | `use-market-stream.ts` |
| Utilities | `kebab-case.ts` | `format.ts`, `symbol-config.ts` |
| CSS variables | `--kebab-case` | `--amber`, `--signal-green` |
