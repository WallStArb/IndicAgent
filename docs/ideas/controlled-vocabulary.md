# Controlled Vocabulary

**Created:** 2026-06-18
**Refreshed:** 2026-07-01
**Status:** Idea / Design — unscheduled (Phase 135 deferred indefinitely; original prerequisite now satisfied, ready to build whenever prioritized)
**Type:** Architecture pattern + design, Type 3 (static taxonomy) in the [Concept Governance Registries](concept-governance-registries.md) family

---

## Problem

The codebase has 10+ domain vocabularies with zero discoverable metadata. Two tiers exist today:

- **PG-ENUM-enforced** (shipped in Phase 134, migration `151_phase134_pg_enum_types.sql`): `signal_events.status` (`signal_status_type`), `trade_frames.entry_type` (`entry_type_type`), `signal_outcome` (`signal_outcome_type`). The DB enforces valid values at write time, but there is still no labels/descriptions/groupings layer — `WIN_OUTCOMES`, `STOP_OUTCOMES`, `TTL_OUTCOMES` remain Python frozensets, invisible to SQL and dashboard consumers.
- **Plain TEXT, unenforced** (confirmed live 2026-07-01 via `information_schema.columns`): `regime`/`tf`/`timeframe`/`tier`/`session_type`/`asset_class` appear as free-text columns across 50+ tables (`feature_vectors.regime`, `market_regimes.regime`, `feature_registry.tier`, `contract_metadata.asset_class`, `intelligence_features.session_type`, etc.). This is broader than the original 2026-06-18 problem statement — v3.0's Feature Factory / AlphaEngine tables added many more untyped vocabulary columns than existed at Phase 134 time. Notably `regime` alone spans two independent systems (per-symbol HMM: 5 labels; cross-sectional: 9 labels — see MEMORY.md "Dual Regime System") with no registry distinguishing which table uses which taxonomy.

Every dashboard filter and API consumer must hardcode vocabulary independently — a distributed maintenance problem that compounds as the analyst-facing surface grows.

APR solved the same problem for numeric parameters: one registry, any module registers into it, any consumer reads from it. Controlled vocabulary is the same pattern for symbolic codes.

---

## Design

### Three tables, written at migration time, read-only at runtime

```sql
-- Atomic vocabulary: one row per valid code per namespace
CREATE TABLE controlled_vocabulary (
    namespace     TEXT    NOT NULL,   -- 'signal_outcome', 'entry_type', 'regime_hmm', 'regime_cross_sectional'
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

### Source of truth stays per-namespace

For PG-ENUM-backed namespaces (`signal_outcome`, `entry_type`, `signal_status`), the Python enum is the compile-time contract and the PostgreSQL ENUM type is write-time enforcement; `controlled_vocabulary` is a metadata projection on top — it describes vocabulary, it does not enforce it. At startup, `VocabularyService` compares each registered namespace against its Python enum members; any divergence is a hard crash, not a warning.

For TEXT-backed namespaces (`regime_hmm`, `regime_cross_sectional`, `timeframe`, `tier`, `session_type`, `asset_class`) there is no Python enum and no DB constraint today — `controlled_vocabulary` would be the *first* source of enforceable structure for these. Whether to also add PG ENUM types for these columns is a separate decision (each is a live hypertable column with production data; converting TEXT → ENUM on tables like `feature_vectors` and `market_regimes` is a migration project of its own, out of scope here). This doc's registry can exist purely as a metadata/labels layer without requiring that conversion first.

---

## What Goes In

**In** — domain vocabulary that appears in dashboards, APIs, or analyst queries:

| Namespace | Backing | Groups |
|---|---|---|
| `signal_outcome` | `signal_outcome_type` (PG ENUM) | `wins`, `losses`, `timeouts` |
| `entry_type` | `entry_type_type` (PG ENUM) | (none yet) |
| `signal_status` | `signal_status_type` (PG ENUM) | `pending`/`active` (live), `expired`/`regime_suppressed` (terminal) |
| `regime_hmm` | TEXT, `feature_vectors.regime` | 5 labels sorted by emission mean (per MEMORY.md dual regime system) |
| `regime_cross_sectional` | TEXT, `market_regimes.regime` | 9 labels: `{low/mid/high}_{bull/neutral/bear}` |
| `tier` | TEXT, `feature_registry.tier` | (for dashboard grouping) |
| `timeframe` | TEXT, `feature_vectors.tf` and 40+ other tables | (for display labels) |
| `asset_class` | TEXT, `contract_metadata.asset_class` | `equity`, `futures`, `fx` |
| `session_type` | TEXT, `intelligence_features.session_type` | (for display labels) |

**Out** — internal infrastructure codes users never see: `CircuitState`, `DataSource`, `TransitionType`.

Concept Registry's `domain` column is deliberately **not** a namespace here — it's a fixed 7-value set enforced with a plain `CHECK` constraint on `concept_registry.domain` itself, same pattern as its `status` column. An earlier draft specced a `concept_domain` namespace + runtime `VocabularyService` dependency for this; retracted after review found it coupled two independently-deferred systems to solve a problem a `CHECK` constraint already solves (see `docs/ideas/concept-governance-registries.md`). Concept Registry and Controlled Vocabulary are unrelated sibling designs with no shared build gate.

---

## What This Replaces / Extends

The `WIN_OUTCOMES`, `STOP_OUTCOMES`, `TTL_OUTCOMES` frozensets in `signal_outcome.py` become seeded rows in `vocabulary_group_member`. They stay in Python for in-process use (fast, no DB call) but the DB projection makes them:

- Queryable from SQL: `SELECT code FROM vocabulary_group_member WHERE namespace='signal_outcome' AND group_name='wins'`
- Reachable from dashboard filter panels without hardcoding
- Usable in ML feature derivation (`is_winning_outcome` as a clean derived column)
- Self-documenting in API responses

For `regime_hmm` vs `regime_cross_sectional`, the registry also solves a real correctness risk: today nothing prevents a consumer from reading `feature_vectors.regime` (5 HMM labels) and treating it as if it were a `market_regimes.regime` value (9 cross-sectional labels) — the columns share a name but not a taxonomy. A `namespace` column makes the distinction explicit and queryable.

---

## Staging

**Core infrastructure (no longer phase-134-gated — that prerequisite shipped 2026-06-18):**
- Migration: create 3 tables
- Seed: `signal_outcome`, `entry_type`, `signal_status` namespaces with labels/descriptions (PG-ENUM-backed, lowest risk — DB already enforces these values)
- Seed: taxonomy groups (`wins`, `losses`, `timeouts` for `signal_outcome`)
- `VocabularyService` with startup divergence check (PG-ENUM namespaces only)
- `/api/vocabulary/{namespace}` endpoint
- Replace first dashboard consumer (signal filter dropdowns)

**Subsequent phases — expand on demand:**
- Add `regime_hmm`, `regime_cross_sectional`, `tier`, `timeframe`, `asset_class`, `session_type` namespaces (TEXT-backed, no divergence check possible until/unless PG ENUM conversion happens separately)
- Add taxonomy groups when the first SQL query needs `WHERE group_name = ...`
- ML feature derivation: join `vocabulary_group_member` for `is_winning_outcome` etc.

Do not seed a namespace until there is a concrete consumer. The infrastructure is built once; namespaces are added reactively.

---

## APR Analogy

| APR | Controlled Vocabulary |
|---|---|
| `config_state` table | `controlled_vocabulary` table |
| `threshold.*`, `weights.*` namespaces | `signal_outcome`, `regime_hmm` namespaces |
| `ConfigService.get("threshold.x", 1.0)` | `VocabularyService.group_codes("signal_outcome", "wins")` |
| ML can update values at runtime | Metadata updated only via migration |
| Any module registers a parameter | Any module seeds a namespace |
| Startup schema divergence = hard error (all namespaces) | Startup enum divergence = hard error (PG-ENUM namespaces only) |

---

## Dependency

Originally gated on Phase 134 (converts `signal_outcome`, `entry_type`, `signal_status` columns to PostgreSQL ENUM types) — **that shipped 2026-06-18**, so the PG-ENUM-backed namespaces are unblocked today. The TEXT-backed namespaces added by v3.0 (`regime_hmm`, `regime_cross_sectional`, `tier`, etc.) have no such prerequisite; they can be seeded as soon as this system is built, with the caveat that they get metadata/labels but not DB-level enforcement unless a separate TEXT→ENUM migration is done for those columns.
