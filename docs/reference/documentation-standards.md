<!-- generated-by: gsd-doc-writer -->
# Documentation Standards

**Version:** 1.0
**Status:** current
**Last Updated:** 2026-05-27

Formatting conventions for documentation files. For code naming on all surfaces (Python, Kafka, DB, systemd, TypeScript), see `docs/reference/naming-conventions.md`. For the documentation system design — taxonomy, verification lifecycle, the `current` status contract — see `docs/foundation/documentation-system.md`.

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
