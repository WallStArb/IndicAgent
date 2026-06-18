# Controlled Vocabulary System

**Date:** 2026-06-18
**Status:** Planned — pending Phase 134 completion
**Phase target:** 135

---

## Problem

The codebase has 10+ domain enums (`SignalOutcome`, `EntryType`, `SignalStatus`, `MarketRegime`, `SignalGrade`, `Timeframe`, `AssetClass`, `Tier`, `TransitionType`, `SessionType`) with zero discoverable metadata. Taxonomy groupings (`WIN_OUTCOMES`, `STOP_OUTCOMES`, `TTL_OUTCOMES`) are Python frozensets invisible to SQL. Every dashboard filter and API consumer must hardcode vocabulary independently — a distributed maintenance problem that compounds as the analyst-facing surface grows.

APR solved the same problem for numeric parameters: one registry, any module registers into it, any consumer reads from it. Controlled vocabulary is the same pattern for symbolic codes.

---

## Design

### Three tables, written at migration time, read-only at runtime

```sql
-- Atomic vocabulary: one row per valid code per namespace
CREATE TABLE controlled_vocabulary (
    namespace     TEXT    NOT NULL,   -- 'signal_outcome', 'entry_type', 'market_regime'
    code          TEXT    NOT NULL,   -- exact value: 'stopped_at_entry'
    label         TEXT    NOT NULL,   -- "Stopped at Entry"
    description   TEXT,              -- tooltip: "Price stopped within 2 bars without favorable move"
    sort_order    INT     DEFAULT 0,  -- display order within namespace
    is_deprecated BOOLEAN DEFAULT FALSE,
    PRIMARY KEY (namespace, code)
);

-- Taxonomy: named groupings of codes within a namespace
CREATE TABLE vocabulary_group (
    namespace    TEXT NOT NULL,
    group_name   TEXT NOT NULL,   -- 'wins', 'losses', 'timeouts'
    label        TEXT NOT NULL,   -- "Winning Outcomes"
    description  TEXT,
    sort_order   INT  DEFAULT 0,
    PRIMARY KEY (namespace, group_name)
);

-- Many-to-many membership (a code can belong to multiple groups)
CREATE TABLE vocabulary_group_member (
    namespace   TEXT NOT NULL,
    group_name  TEXT NOT NULL,
    code        TEXT NOT NULL,
    PRIMARY KEY (namespace, group_name, code),
    FOREIGN KEY (namespace, code)       REFERENCES controlled_vocabulary(namespace, code),
    FOREIGN KEY (namespace, group_name) REFERENCES vocabulary_group(namespace, group_name)
);
```

### VocabularyService — the APR equivalent

```python
VocabularyService.codes("signal_outcome")             # -> list[str]
VocabularyService.label("signal_outcome", "target_1") # -> "Target 1"
VocabularyService.group_codes("signal_outcome", "wins") # -> frozenset[str]
VocabularyService.namespace("signal_outcome")          # -> list[VocabEntry]
```

Single interface. Any module calls it. No knowledge of other namespaces. Cached at startup — zero DB calls at runtime on the hot path.

### Python enum stays as source of truth

Python enum = compile-time contract. PostgreSQL ENUM type = write-time enforcement. `controlled_vocabulary` = metadata projection. The registry describes vocabulary; it does not enforce it.

At startup, `VocabularyService` compares each registered namespace against its Python enum members. Any divergence (code in Python enum missing from DB, or code in DB not in Python enum) is a hard crash — not a warning, not a log line.

---

## What Goes In

**In** — domain vocabulary that appears in dashboards, APIs, or analyst queries:

| Namespace | Source | Groups |
|---|---|---|
| `signal_outcome` | `SignalOutcome` | `wins`, `losses`, `timeouts` |
| `entry_type` | `EntryType` | (none yet) |
| `signal_status` | `SignalStatus` | `live`, `terminal` |
| `market_regime` | `MarketRegime` | `trending`, `mean_reverting` |
| `signal_grade` | `SignalGrade` | (none yet) |
| `timeframe` | `Timeframe` | (for display labels) |

**Out** — internal infrastructure codes users never see: `CircuitState`, `DataSource`, `TransitionType`, `SessionType`.

---

## What This Replaces / Extends

The `WIN_OUTCOMES`, `STOP_OUTCOMES`, `TTL_OUTCOMES` frozensets in `signal_outcome.py` become seeded rows in `vocabulary_group_member`. They stay in Python for in-process use (fast, no DB call) but the DB projection makes them:

- Queryable from SQL: `SELECT code FROM vocabulary_group_member WHERE namespace='signal_outcome' AND group_name='wins'`
- Reachable from dashboard filter panels without hardcoding
- Usable in ML feature derivation (`is_winning_outcome` as a clean derived column)
- Self-documenting in API responses

---

## Staging

**Phase 135 — core infrastructure:**
- Migration: create 3 tables
- Seed: `signal_outcome`, `entry_type`, `signal_status` namespaces with labels/descriptions
- Seed: taxonomy groups (`wins`, `losses`, `timeouts` for `signal_outcome`)
- `VocabularyService` with startup divergence check
- `/api/vocabulary/{namespace}` endpoint
- Replace first dashboard consumer (signal filter dropdowns)

**Subsequent phases — expand on demand:**
- Add `market_regime`, `signal_grade`, `timeframe` namespaces when a consumer needs them
- Add taxonomy groups when the first SQL query needs `WHERE group_name = ...`
- ML feature derivation: join `vocabulary_group_member` for `is_winning_outcome` etc.

Do not seed a namespace until there is a concrete consumer. The infrastructure is built once; namespaces are added reactively.

---

## APR Analogy

| APR | Controlled Vocabulary |
|---|---|
| `config_state` table | `controlled_vocabulary` table |
| `threshold.*`, `weights.*` namespaces | `signal_outcome`, `market_regime` namespaces |
| `ConfigService.get("threshold.x", 1.0)` | `VocabularyService.group_codes("signal_outcome", "wins")` |
| ML can update values at runtime | Metadata updated only via migration |
| Any module registers a parameter | Any module seeds a namespace |
| Startup schema divergence = hard error | Startup enum divergence = hard error |

---

## Dependency

Phase 134 must complete first. Plan 03 of Phase 134 converts `signal_outcome`, `entry_type`, and `signal_status` columns to PostgreSQL ENUM types — the `controlled_vocabulary` seeding must reference values that the DB already enforces. Building the vocabulary table before the ENUM types exist would let `controlled_vocabulary` describe values that the DB does not yet enforce.
