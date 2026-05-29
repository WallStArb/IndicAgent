<!-- generated-by: gsd-doc-writer -->
# Documentation Standards

**Version:** 1.0
**Status:** current
**Last Updated:** 2026-05-27

Personal reference for consistent doc and code naming across the project.

---

## File & Directory Naming

| Context | Convention | Example |
|---------|-----------|---------|
| Docs | kebab-case | `layered-architecture.md`, `data-streaming.md` |
| Standard root files | UPPERCASE | `README.md`, `CHANGELOG.md`, `CLAUDE.md` |
| Directories | lowercase, hyphens | `docs/architecture/`, `docs/getting-started/` |
| Plan docs | date-prefixed kebab | `2026-03-15-signal-lifecycle-redesign.md` |

> **Note:** `docs/architecture/` files were historically UPPERCASE (`CURRENT_STATE.md`, etc.) — all renamed to kebab-case on 2026-04-21. If you encounter any stale UPPERCASE references in archived plan docs or `.planning/` context files, they can be ignored.

---

## Document Headers

All docs should open with:

```markdown
# Title

**Version:** X.Y
**Status:** draft | design | current | archived
**Priority:** high | medium | low | future   (ideas docs only)
**Last Updated:** YYYY-MM-DD
```

Version: document revision number (start at 1.0, increment on meaningful changes). For docs tracking project state, use the project milestone version (e.g. 2.8).

Status values: `draft` -> `design` -> `current` -> `archived`

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

See also: `CLAUDE.md` Naming section and `docs/naming-conventions.md`.

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
{env}.market.bars                  # canonical 1m bars
{env}.market.bars.htf              # HTF bars (5m-1d)
{env}.intelligence.journal         # BarIntelligenceRecord (atomic per-bar output)
{env}.intelligence.i7.signals      # all ranked I7 signals per bar
{env}.lifecycle.transitions        # signal lifecycle state changes
{env}.llm.calls                    # LLM audit log
{env}.system.health.events         # service health transitions
{env}.<domain>.<agent>.dlq         # dead letter queue per agent
```

Always built via `src/core/stream_keys.py` — never construct topic strings manually with f-strings. Full topic list: see `topic_*` functions in `stream_keys.py`.

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

Examples: `indicagent-intelligence-pipeline.service`, `indicagent-signal-writer.service`

Check authoritative live state: `systemctl list-units --all | grep indicagent`

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

---

## Observability Conventions

Metrics use the OTel SDK directly (`src/observability/metrics.py`) — `prometheus_client` is fully removed.

| Metric type | Call pattern | Example |
|-------------|-------------|---------|
| Counter | `.add(1, {"label": val})` | `PLUGIN_EXEC_COUNTER.add(1, {"tier": "I1"})` |
| Histogram | `.record(value, {"label": val})` | `PLUGIN_DURATION_MS.record(42.5, {"plugin": "rsi"})` |
| UpDownCounter (gauge) | `.add(delta, {"label": val})` | `QUEUE_DEPTH.add(1, {"queue": "output"})` |
| PointGauge | `.set(value, {"label": val})` | `PIPELINE_LATENCY.set(8.5, {"symbol": "ES"})` |

Never import `prometheus_client` — it is fully removed.

---

## Accuracy Warning

Docs in `docs/` may contain forward-looking specs that were never implemented. Always verify claims against source code before acting on them. When in doubt, read the code.
