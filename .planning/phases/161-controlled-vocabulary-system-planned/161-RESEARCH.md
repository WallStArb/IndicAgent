# Phase 161: Controlled Vocabulary System - Research

**Researched:** 2026-07-16
**Domain:** Static taxonomy / vocabulary registry (Type 3 governance registry), PostgreSQL schema + Python service + FastAPI endpoint
**Confidence:** MEDIUM-HIGH — schema/service/API conventions are HIGH confidence (verified against live sibling code); seed-data accuracy is the weak spot: three of five namespaces have live-DB discrepancies against the design doc / CONTEXT.md that must be resolved before the seed migration is written (see Summary and Open Questions).

## Summary

This phase is mechanically well-specified — `docs/research/concept-controlled-vocabulary.md` is a
mature, Fable-reviewed design and `161-CONTEXT.md` locks scope tightly (3 tables, 5 namespaces,
`VocabularyService`, one drift audit, one API route). The main research value-add here is NOT
"what pattern to follow" (that's settled: mirror `ConfigService`/APR exactly) — it's **verifying
the live data the design doc's seed decisions were built on, since three separate discrepancies
surfaced against the current database**, and one structural finding about the CONTEXT.md-suggested
drift-audit host.

**Critical finding 1 (blocks D-04 as literally written):** `market_regimes.regime_label` carries
**14-15 distinct live labels**, not the 9 the design doc and CONTEXT.md's D-04 describe. Root
cause: the same TEXT column is shared by two independent `regime_group` signal modules —
`equity` (breadth_vol: 9 labels, `{low,mid,high}_{bull,neutral,bear}` — matches the design doc)
and `rates` (curve_credit: 6 labels, `{flat,steep,inverted}_{tight,wide}` — an entirely different
taxonomy shape). Seeding only 9 codes per D-04 will cause the column-backed drift audit to
data-superset-alert on every `rates` row the moment it goes live. This must be resolved by the
user/planner before the seed migration is written — see Open Questions.

**Critical finding 2:** `feature_registry.tier` has **3 live values today** (`0_atomic`: 135,
`1_interaction`: 8, `2_theory`: 12), not the 2 CONTEXT.md's code_context section states. The
`1_interaction` tier was populated by the Interaction Primitives Pilot (todo 037, completed
2026-07-10) after CONTEXT.md's snapshot. Seed all 3.

**Finding 3 (implementation detail, not a scope conflict):** `feature_vectors.regime` carries an
empty string `''` (not NULL) for ~31% of rows even in the last 30 days — bars where the HMM
regime hasn't been computed yet, not a 6th taxonomy code. The column-backed drift audit's
`SELECT DISTINCT` query must filter `WHERE regime <> ''` or it will permanently false-positive on
day one.

**Structural finding:** CONTEXT.md's Claude's Discretion section names `data_quality_auditor.py`
as the natural drift-audit host. On inspection this is a weaker fit than it looks: it's a
`oneshot`, timer-triggered daemon whose 4 existing checks all query `intelligence_features` and
`signal_ledger` — both tables CLAUDE.md's Architecture section marks ARCHIVED (v2.x, no live
consumer as of 2026-07-02) — and the file hasn't been touched since 2026-06-16, predating that
archiving. Its systemd timer's live/enabled state cannot be verified from this environment and
CLAUDE.md explicitly warns "all systemd timers are confirmed disabled as of 2026-07-02." See
Open Questions for the recommended resolution.

**Primary recommendation:** Build the schema/service/API exactly as designed (`concept-controlled-vocabulary.md` is authoritative for HOW), but resolve the two data discrepancies above before writing the seed migration, and re-verify `data_quality_auditor.py`'s timer state (or pick `bar_auditor.py`, the only continuously-running live auditor in the DAG) before wiring the drift audit into it.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| `controlled_vocabulary`/`vocabulary_group`/`vocabulary_group_member` schema | Database / Storage | — | Migration-time, read-only-at-runtime metadata tables, same tier as `config_state`/`config_history` |
| `VocabularyService` (cache, lookup API) | API / Backend (library, embedded) | — | Not a network service (D-05) — a library any process embeds locally, same tier as `ConfigService` |
| Three-way ENUM divergence check | API / Backend | Database / Storage | Startup-time reconciliation of registry rows + Python enum + `pg_enum` catalog; runs once per process boot |
| Column-backed drift audit | API / Backend (batch/auditor daemon) | Database / Storage | Periodic `SELECT DISTINCT` against a declared source column; hosted by an existing `BaseDaemon` auditor, not a new service |
| `/api/vocabulary/{namespace}` endpoint | API / Backend | — | Plain FastAPI router under `src/api/routes/`, same tier as `drift.py`/`features.py` |
| Dashboard regime-label consumer | Browser / Client | API / Backend | Reads the new endpoint instead of a hardcoded label list; out of this phase's build (design doc lists it as "first consumer," CONTEXT.md doesn't lock a dashboard task) |

## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-01:** Seed only `regime_hmm`, `regime_cross_sectional`, `timeframe`, `asset_class`, `tier` in this build. `signal_outcome`/`entry_type`/`signal_status`/`session_type` stay "on demand later."
- **D-02:** `tag_vocabulary`/`instrument_tags` are permanently out of scope — closed decision, not deferred. Different epistemic shape (authoritative/flat vs. weighted/falsifiable-hypothesis rows); folding them in would make the schema "lie about what kind of row this is."
- **D-03:** `regime_hmm`'s 5 labels seed two independent, overlapping `vocabulary_group` groupings: `trending`={trending_down,trending_up}, `transition`={transition_down,transition_up}, `bullish_bias`={transition_up,trending_up}, `bearish_bias`={transition_down,trending_down}. `ranging` stays ungrouped.
- **D-04:** `regime_cross_sectional`'s labels are two crossed facets seeded as independent groups — vol-tier (`low_vol`/`mid_vol`/`high_vol`) and direction (`bull`/`neutral`/`bear`). **Research finding: this decision's premise (9 total labels) does not match the live column, which carries 14-15 labels across two `regime_group` values (`equity`, `rates`) with different taxonomy shapes — see Open Questions. D-04 as written covers only the `equity` subset.**
- **D-05:** `VocabularyService` is a library any daemon embeds locally (same pattern as `ConfigService`/APR) — cached at startup, zero DB calls on the hot path. Not a new DAG node or network service.
- **D-06:** Standing rule for adding future namespaces (from `concept-governance-registries.md`'s "When to Add a New Registry"): a namespace earns its place when (1) membership is mutable, (2) external consumers need enumeration without importing Python, and (3) metadata enrichment has real, concrete consumers.
- **D-07:** Do NOT build a shared abstract base class generalizing `VocabularyService` and `ConceptRegistryService`. Extract shared code only the second time a shape is proven needed (per the `Float32ChunkAccumulator`/todo 087 precedent — confirmed live at `services/_batch_utils.py:147`).
- **D-08 [informational, not in scope]:** `StratificationDimension` Protocol anticipates Controlled Vocabulary as its future label-set authority. No code in this phase should build toward that integration.

### Claude's Discretion
- **Drift-audit host daemon:** CONTEXT.md suggests `data_quality_auditor.py` as the natural fit, "use it unless research surfaces a reason not to." **Research surfaced a reason — see Structural Finding above and Open Questions.**
- Everything else — exact migration numbers, `VocabularyService` method signatures, exact label/description text for the 5 namespaces, API route placement — follows the design doc's own fully-specified schema and staging section as-is.

### Deferred Ideas (OUT OF SCOPE)
- **`tag_vocabulary` unification** — considered and explicitly rejected, not deferred (D-02). Closed.
- **Security Classification Hierarchy** (GICS-style) — real future work, gated on the individual-equities milestone, no ROADMAP phase yet.
- **`StratificationDimension`/Controlled-Vocabulary integration** (D-08) — sequenced after Phase 144/145's conditioning-layer work, itself blocked on the current 143.1 corpus re-run.

## Phase Requirements

No `REQUIREMENTS.md` entries reference Phase 161 by ID (confirmed: `.planning/REQUIREMENTS.md` does not exist in this repo). This phase's scope is defined entirely by `161-CONTEXT.md`'s locked decisions above, not by tracked requirement IDs.

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| asyncpg | (already pinned project-wide) | DB access for `VocabularyService` and the drift audit | Same driver as `ConfigService`, `ConceptRegistryService`, every `BaseDaemon` subclass |
| structlog | (already pinned) | Logging via `setup_service_logging()` | Project-wide convention, CLAUDE.md mandate |
| FastAPI | (already pinned, see `src/api/main.py`) | `/api/vocabulary/{namespace}` route | Existing API app; no new framework |

No new third-party packages are needed for this phase — it is pure Python/SQL against already-installed dependencies (`asyncpg`, `structlog`, `fastapi`). **Package Legitimacy Audit is not applicable** (no new packages to install).

### Supporting
None beyond the above — this is an internal registry pattern, not an integration with an external service.

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `vocabulary_group`/`vocabulary_group_member` as separate tables | `groups TEXT[]`/JSONB column on `controlled_vocabulary` | Design doc already steelmanned and rejected this (concept-controlled-vocabulary.md, "Is three tables the minimal shape?") — loses group metadata (labels/tooltips/sort order) and forces `ANY()` array predicates instead of a clean join for the ML/SQL derivation consumer. Not revisited here; CONTEXT.md treats the 3-table shape as locked. |
| Hosting drift audit in `data_quality_auditor.py` | Hosting in `bar_auditor.py` (the only live, continuously-running auditor in the DAG) | See Open Questions — this is the one place research diverges from CONTEXT.md's discretion suggestion. |

## Package Legitimacy Audit

Not applicable — this phase installs no new external packages (pure internal Python/SQL using already-vendored `asyncpg`/`structlog`/`fastapi`).

## Architecture Patterns

### System Architecture Diagram

```
Migration (write-once, reviewed)
   │
   ▼
controlled_vocabulary ──┐
vocabulary_group        │  (3 tables, PK/FK-linked, read-only at runtime)
vocabulary_group_member ┘
   │
   │  cached in full at process startup (one SELECT per table)
   ▼
VocabularyService (in-process library, embedded by any consumer)
   ├── .codes(namespace)          -> list[str]           (zero DB calls, hot path)
   ├── .label(namespace, code)    -> str
   ├── .group_codes(namespace,g)  -> frozenset[str]
   └── .namespace(namespace)      -> list[VocabEntry]
   │
   ├──> consumed by: dashboard filter panels, ML feature derivation (future),
   │                  any service wanting a label/group lookup
   │
   ├──> /api/vocabulary/{namespace}  (FastAPI route, src/api/routes/vocabulary.py)
   │        reads VocabularyService (or DB directly, matching drift.py's
   │        try/except-on-DB-error pattern) -> JSON response
   │
   └──> divergence detection (never gates writes, always read-side):
        ├── ENUM-backed namespaces: three-way startup check
        │     registry rows  <-->  Python enum members  <-->  pg_enum catalog
        │     any pairwise mismatch -> hard crash at process boot
        │
        └── column-backed namespaces (regime_hmm, regime_cross_sectional,
            tier, asset_class, timeframe): periodic drift audit
              SELECT DISTINCT <col> FROM <table>
                WHERE <time_col> > now() - <window>   (bounded scan, NOT full-table)
              compare against registry codes
              data-superset (live code registry never heard of) -> LOUD alert
                (OTel counter .add(1) + logger.error + optionally an
                 integrity_monitor fact row, see Code Examples)
              registry-superset (registered code no longer observed) -> informational
                (this is what is_deprecated is for)
```

### Recommended Project Structure
```
production/migrations/
├── 237_controlled_vocabulary_schema.sql        # 3-table DDL, indexes, FKs
├── 238_controlled_vocabulary_seed_namespaces.sql  # seed rows for the 5 live namespaces + groups

src/config/
└── vocabulary_service.py     # VocabularyService — mirrors config_service.py exactly

src/api/routes/
└── vocabulary.py             # APIRouter(), included in src/api/main.py under /api/vocabulary

services/
└── data_quality_auditor.py   # OR bar_auditor.py — drift-audit method added here (see Open Questions)
```

### Pattern 1: Library-embedded registry service (VocabularyService follows ConfigService exactly)
**What:** A plain class with `__init__(database_url, pool=None)`, an in-memory `_cache: dict`,
async `initialize()`/`close()`, a synchronous `get_sync()` for hot-path reads (asserts the cache
was pre-warmed), and an async `get()` that fills the cache on miss.
**When to use:** Any process that needs namespace/code/label/group lookups without a network
call per lookup — i.e., every consumer of `VocabularyService`.
**Example (the actual live pattern, verified):**
```python
# Source: src/config/config_service.py (live code, verified via Read)
class ConfigService:
    def __init__(self, database_url: str, pool: asyncpg.Pool | None = None) -> None:
        self._database_url = database_url
        self._db_pool: asyncpg.Pool | None = pool
        self._cache: dict[str, Any] = {}

    async def initialize(self) -> None:
        if self._db_pool is None:
            self._db_pool = await create_pool(self._database_url, pool_name="config_service")

    def get_sync(self, key: str, default: Any = None) -> Any:
        """Return a cached config value synchronously — no DB I/O.
        MUST be called only after the cache has been pre-warmed via get().
        """
        return self._cache.get(key, default)

    async def get(self, key: str, default: Any = None) -> Any:
        if key in self._cache:
            return self._cache[key]
        assert self._db_pool is not None, "ConfigService.initialize() not called"
        # ... DB fetch, cache fill ...
```
`VocabularyService` should mirror this shape 1:1 (`initialize()`/`close()`/in-memory cache/
`get_sync`-style hot path), living at `src/config/vocabulary_service.py` — the same directory as
`ConfigService`, not `src/core/` or `src/intelligence/`. This is the strongest evidence-based
placement: `ConfigService` itself is domain-agnostic code that serves domain-specific keys
(`regime.*`, `alpha.*`) without embedding domain vocabulary in the class itself — exactly the
same relationship `VocabularyService` has to `regime_hmm`/`tier`/etc. `src/config/` is the
established third location (alongside Ring 0 `src/core/` and Ring 1 `src/intelligence/`) for this
exact kind of cross-cutting, domain-agnostic-code/domain-specific-data registry.

### Pattern 2: FastAPI router convention (for `/api/vocabulary/{namespace}`)
**What:** A bare `APIRouter()` in its own file under `src/api/routes/`, included in
`src/api/main.py` with a URL prefix, DB access wrapped in try/except with a `logger.warning` on
failure (never crashes the endpoint on a transient DB error).
**Example:**
```python
# Source: src/api/routes/drift.py (live code, verified via Read) — 65-line file, the
# closest existing precedent to a small metadata-read endpoint
router = APIRouter()

@router.get("")
async def get_drift_state() -> dict[str, Any]:
    from src.core.database_manager import get_connection
    try:
        async with get_connection() as conn:
            rows = await conn.fetch("SELECT ... FROM drift_state ...")
    except Exception as error:
        logger.warning("drift endpoint: DB query error", error=str(error))
    return {...}
```
```python
# src/api/main.py — registration convention
app.include_router(drift.router, prefix="/api/drift", tags=["drift"])
# vocabulary.py should register the same way:
app.include_router(vocabulary.router, prefix="/api/vocabulary", tags=["vocabulary"])
```
No existing Concept Registry (Phase 160) API route was found in `src/api/routes/` — Phase 160
shipped `ConceptRegistryService` + a dashboard integration, not a REST endpoint — so `drift.py` is
the closest sibling precedent for a small read-only metadata route, not a Concept Registry
equivalent.

### Pattern 3: Reusing `integrity_monitor` as the drift audit's persistence layer
**What:** `integrity_monitor` (created Phase 143, migration 218) is a generic
`(monitor_type, subject, metric_name, metric_value, threshold_value, passed, evaluated_at)` fact
table, already used by `ic_engine.py` for an identically-shaped "run a check, compare to
threshold, log pass/fail" pattern, with an idempotent `ON CONFLICT ... DO NOTHING` insert.
**When to use:** The design doc only mandates "OTel counter + log at error" for the drift audit's
loud alert — it does not specify persistence. `integrity_monitor` is currently empty of any
`monitor_type` rows (verified via psql), so adding `monitor_type='vocabulary_drift'` costs nothing
schema-wise and gives the drift audit a queryable history (`SELECT * FROM integrity_monitor WHERE
monitor_type='vocabulary_drift' AND passed=false`) instead of only a transient metric + log line.
**Example:**
```sql
-- Source: services/ic_engine.py:2637 (live code, verified via Read) — the pattern to replicate
INSERT INTO integrity_monitor
    (monitor_type, subject, metric_name, metric_value, threshold_value, passed, training_window_end)
VALUES ('ic_lifecycle', NULL, 'regime_shift_fraction', %s, %s, false, %s)
ON CONFLICT (monitor_type, training_window_end, metric_name, COALESCE(subject, ''), evaluated_at)
DO NOTHING
```
For vocabulary drift: `monitor_type='vocabulary_drift'`, `subject=<namespace>`,
`metric_name='unregistered_code_count'`, `metric_value=<count>`, `threshold_value=0`,
`passed=(count == 0)`, `training_window_end=NULL` (this monitor type has no training-window
concept — the audit's own audit-run timestamp via `evaluated_at DEFAULT now()` is sufficient).

### Anti-Patterns to Avoid
- **Treating empty-string as a taxonomy code:** `feature_vectors.regime = ''` is a "not yet
  computed" placeholder for ~31% of rows even in the last 30 days, not a 6th `regime_hmm` label.
  The drift audit's `SELECT DISTINCT` query MUST add `WHERE regime <> ''` or it alerts every run.
- **Assuming `market_regimes.regime_label` is one flat 9-value taxonomy:** it is two independent
  taxonomies sharing one column, distinguished only by `regime_group` (`equity`/`rates`). A drift
  audit query that doesn't scope by `regime_group` will conflate them.
- **Making `VocabularyService` a runtime write gate:** the design doc explicitly rejects this — it
  would put a DB lookup on hot write paths and invert the DAG (a compute daemon consulting a
  registry service to validate its own output). Read-only projection only.
- **Building a shared `RegistryService` base class with `ConceptRegistryService`:** explicitly
  rejected by D-07. Two purpose-built classes, no shared base, same house style as APR/Concept
  Registry/Tag Vocabulary already independently confirm.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Metadata projection over an enum/taxonomy | A new bespoke table + ad-hoc Python dict per namespace | The existing `controlled_vocabulary`/`vocabulary_group`/`vocabulary_group_member` schema, already fully designed | This is precisely the "one registry, any module registers, any consumer reads" pattern APR already proved for numeric params — a fourth bespoke vocabulary table per domain is the exact sprawl this phase exists to prevent |
| Cached, hot-path-safe config/metadata reads | A custom caching layer, TTL logic, or a Redis cache | `ConfigService`'s exact in-memory-dict + `initialize()`/`get_sync()` shape | Already proven at 425-parameter scale; `VocabularyService`'s ~100-row scale is far smaller |
| "Is this drift real" persistence/audit trail | A new `vocabulary_drift_log` table | `integrity_monitor` (already live, already generic, already has the identical INSERT+ON CONFLICT pattern in `ic_engine.py`) | Same schema shape already solves "run a check, compare to a threshold, record pass/fail," no new migration needed for this part |

**Key insight:** Every piece of this phase already has a proven, live sibling to copy — `ConfigService` for the service shape, `drift.py` for the API route shape, `integrity_monitor` for the audit-persistence shape, `ic_engine.py`'s regime-shift-hold code for the "loud alert" logging shape. There is no genuinely novel infrastructure decision left in this phase; the remaining risk is entirely in the seed-data accuracy (see Critical Findings) and the drift-audit host choice.

## Common Pitfalls

### Pitfall 1: Seeding `regime_cross_sectional` from CONTEXT.md's D-04 count without re-verifying against the live column
**What goes wrong:** The seed migration ships with 9 codes; the very first drift-audit run
data-superset-alerts on all 6 `rates`-regime_group rows, on day one, in perpetuity, because
nobody reads alerts that fire constantly.
**Why it happens:** D-04's premise (9 labels) was accurate for the design doc's original scope
(equity breadth_vol only) but the live column now also carries `curve_credit`/rates labels added
by a different regime_group module.
**How to avoid:** Resolve the Open Question below before writing the seed migration — either
seed all 15 codes (extending D-04's grouping pattern to a third dimension for `rates`) or scope
the namespace/drift-audit query to `regime_group = 'equity'` explicitly, documented in the
migration comment.
**Warning signs:** Any drift-audit alert firing immediately and every run, rather than only on
genuine future drift (e.g., a BIC K-selection change).

### Pitfall 2: Treating `feature_vectors.regime = ''` as a data-superset violation
**What goes wrong:** Same failure mode as Pitfall 1 — permanent, meaningless alerts.
**Why it happens:** `''` is not NULL; a naive `SELECT DISTINCT regime FROM feature_vectors WHERE
bar_ts > window` returns it as if it were a valid observed code.
**How to avoid:** `WHERE regime <> ''` in the drift audit's bounded-scan query.
**Warning signs:** Drift audit's very first run reports an "unregistered code: ''" alert.

### Pitfall 3: Wiring the drift audit into a daemon whose timer never fires
**What goes wrong:** The drift audit is built, tested, code-reviewed, and then silently never
runs in production because `indicagent-ml-data-quality.timer` is disabled (per CLAUDE.md's
explicit warning that "all systemd timers are confirmed disabled as of 2026-07-02").
**Why it happens:** `data_quality_auditor.py`'s existing 4 checks reference archived v2.x tables
and the file hasn't been touched since before the SLA archiving — a sign this daemon's own timer
health was never re-verified after the archiving either.
**How to avoid:** Before finalizing the host choice, explicitly verify (on the actual production
host, not this dev sandbox) whether `indicagent-ml-data-quality.timer` is enabled and active. If
not, either re-enable it as part of this phase's plan, or choose `bar_auditor.py` (confirmed live,
continuously-running, priority-3 in `_DAG_ORDER`, not timer-gated) as the host instead.
**Warning signs:** `systemctl is-enabled indicagent-ml-data-quality.timer` returns `disabled` or
`systemctl list-timers` doesn't show it in the NEXT column.

## Code Examples

### VocabularyService skeleton (following ConfigService's exact shape)
```python
# Pattern source: src/config/config_service.py (live, verified)
from __future__ import annotations
from dataclasses import dataclass
from typing import Any
import asyncpg
import structlog

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class VocabEntry:
    code: str
    label: str
    description: str | None
    sort_order: int
    is_deprecated: bool


class VocabularyService:
    """Read-only cached projection over controlled_vocabulary/vocabulary_group(_member).

    Cached at startup, zero DB calls on the hot path (mirrors ConfigService).
    Never becomes a runtime write gate.
    """

    def __init__(self, database_url: str, pool: asyncpg.Pool | None = None) -> None:
        self._database_url = database_url
        self._db_pool: asyncpg.Pool | None = pool
        self._entries: dict[str, dict[str, VocabEntry]] = {}   # namespace -> code -> entry
        self._groups: dict[tuple[str, str], frozenset[str]] = {}  # (namespace, group) -> codes

    async def initialize(self) -> None:
        # ... create pool if needed, then load_all() to prewarm cache ...
        ...

    def codes(self, namespace: str) -> list[str]:
        return list(self._entries.get(namespace, {}).keys())

    def label(self, namespace: str, code: str) -> str:
        entry = self._entries.get(namespace, {}).get(code)
        return entry.label if entry else code

    def group_codes(self, namespace: str, group_name: str) -> frozenset[str]:
        return self._groups.get((namespace, group_name), frozenset())
```

### Three-way ENUM divergence check (startup, hard crash)
```sql
-- Source: docs/research/concept-controlled-vocabulary.md's "Source of truth" section
-- (design spec, not yet implemented) — the live catalog query to run at process boot
SELECT enumlabel FROM pg_enum
JOIN pg_type ON pg_enum.enumtypid = pg_type.oid
WHERE typname = %s;
-- Compare against: registry rows (controlled_vocabulary WHERE namespace=%s)
--                  AND Python enum members
-- Any pairwise mismatch among the three -> raise at startup (not applicable to this
-- phase's 5 seeded namespaces, which are all TEXT-backed — kept here because a future
-- namespace addition (e.g., reviving signal_outcome) will need it).
```

### Bounded column-backed drift audit query
```sql
-- Pattern for regime_hmm — note the '' filter (Finding 3) and the recent-window bound
-- (never a full-hypertable distinct-scan)
SELECT DISTINCT regime
FROM feature_vectors
WHERE bar_ts > now() - interval '30 days'
  AND regime <> '';

-- Pattern for regime_cross_sectional — MUST decide regime_group scoping first (Open Question)
SELECT DISTINCT regime_label
FROM market_regimes
WHERE ts > now() - interval '30 days'
  AND regime_group = 'equity';   -- or omit this filter if seeding all 15 codes
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Design doc's original staging (seed archived SLA ENUMs first) | Seed live TEXT-backed namespaces first | 2026-07-06 Fable review (inverted after 2026-07-02 SLA archiving) | Already reflected in CONTEXT.md's D-01; no action needed, noted for context only |
| Two-way ENUM divergence check (registry vs. Python enum) | Three-way check (+ live `pg_enum` catalog) | 2026-07-06 Fable review | Not exercised by this phase's 5 TEXT-backed namespaces, but must be implemented correctly for future ENUM namespace additions |
| "TEXT columns can't be drift-checked" | Declared source-column + periodic bounded drift audit | 2026-07-06 Fable review | Directly implemented by this phase |

**Deprecated/outdated:** None specific to this phase's scope — the design doc itself is current (last touched 2026-07-06, ten days before this research).

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `indicagent-ml-data-quality.timer` is currently disabled in production, per CLAUDE.md's general "all systemd timers are confirmed disabled as of 2026-07-02" statement | Structural Finding / Pitfall 3 | If actually enabled and running weekly, the drift audit could safely live there after all — but CLAUDE.md's own text is the only source for this claim (this dev sandbox has no indicagent systemd units to check directly), so it is flagged `[ASSUMED]` pending a direct `systemctl is-enabled` check on the production host (192.168.68.53) |
| A2 | `bar_auditor.py` is a suitable secondary host if `data_quality_auditor.py`'s timer is confirmed dead | Open Questions | Adding an unrelated vocabulary-drift check to a bar-gap-detection daemon is a SoC stretch; if the timer turns out to be fine, this alternative is unnecessary |

## Open Questions

1. **Does `regime_cross_sectional` seed 9 codes (equity only) or all 14-15 (equity + rates)?**
   - What we know: The live column has verifiably 14-15 distinct labels across two `regime_group`
     values (`equity`: 9, `rates`: 6). D-04 was written assuming a single 9-label taxonomy.
   - What's unclear: Whether the user wants `regime_cross_sectional` to cover both regime_groups
     (extending D-04's crossed-facet grouping pattern with a third dimension for `rates`'
     curve-shape × width facets) or to scope this namespace/drift-audit strictly to `equity` and
     treat `rates` as a future addition (namespace `regime_cross_sectional_rates`, or a
     `regime_group`-qualified query filter).
   - Recommendation: Surface this to the user before the seed migration is written — it's a
     genuine scope question the design doc didn't anticipate (it predates full awareness of the
     `rates` regime_group module), not something research should silently resolve either way.

2. **Should the drift audit live in `data_quality_auditor.py` (per CONTEXT.md's discretion) or `bar_auditor.py` (the only confirmed continuously-running, non-timer-gated auditor)?**
   - What we know: `data_quality_auditor.py` is oneshot/timer-triggered with all-archived existing
     checks; `bar_auditor.py` runs continuously (every 5 min during market hours), is priority-3
     in the live DAG, and reads a genuinely live table (`market_data_ohlcv`).
   - What's unclear: `data_quality_auditor.py`'s actual timer enablement state in production
     (cannot be verified from this dev environment).
   - Recommendation: Verify `systemctl is-enabled indicagent-ml-data-quality.timer` on the
     production host as the first task of implementation. If disabled, either re-enable it
     (small, in-scope fix) or default to `bar_auditor.py` instead.

## Environment Availability

Skipped — this phase has no external tool/service dependencies beyond the already-running
PostgreSQL/TimescaleDB instance and the already-deployed FastAPI app, both confirmed live via the
psql queries and file reads performed during this research.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest (see `pytest.ini`) |
| Config file | `/home/bg/dev/indicagent/pytest.ini` |
| Quick run command | `.venv/bin/pytest tests/unit/test_vocabulary_service.py -x -q` |
| Full suite command | `.venv/bin/pytest tests/unit/ -q` |

### Phase Requirements -> Test Map
No tracked requirement IDs exist for this phase (see Phase Requirements section). Behavior-level
test mapping instead:

| Behavior | Test Type | Automated Command | File Exists? |
|----------|-----------|-------------------|-------------|
| `VocabularyService.codes()`/`.label()`/`.group_codes()` return correct values for all 5 seeded namespaces | unit | `pytest tests/unit/test_vocabulary_service.py -x` | ❌ Wave 0 |
| `VocabularyService` cache is populated at `initialize()` and `get_sync()`-equivalent reads never touch the DB after that | unit | `pytest tests/unit/test_vocabulary_service.py::test_no_db_calls_after_init -x` | ❌ Wave 0 |
| Column-backed drift audit correctly filters `''`/empty placeholder values and correctly scopes `regime_group` | unit | `pytest tests/unit/test_vocabulary_drift_audit.py -x` | ❌ Wave 0 |
| Three-way ENUM divergence check (even if not exercised by any of the 5 live namespaces, the mechanism itself should be unit-tested against a fixture ENUM) | unit | `pytest tests/unit/test_vocabulary_service.py::test_enum_divergence_check -x` | ❌ Wave 0 |
| `/api/vocabulary/{namespace}` returns 5 seeded namespaces correctly, 404/empty for unknown namespace | integration (requires_db) | `pytest tests/integration/test_vocabulary_api.py -x -m requires_db` | ❌ Wave 0 |

The closest live precedent for unit-test style is `tests/unit/test_concept_registry_service.py`
(pure-Python, no-DB tests of the invariant-enforcement core, dataclass-fixture builder pattern via
a `_state(**overrides)` helper) — model `VocabularyService`'s pure-logic tests (cache lookups,
drift-comparison logic) the same way: no DB, no Kafka, dataclass fixtures.

### Sampling Rate
- **Per task commit:** `.venv/bin/pytest tests/unit/test_vocabulary_service.py -x -q`
- **Per wave merge:** `.venv/bin/pytest tests/unit/ -q`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `tests/unit/test_vocabulary_service.py` — covers cache behavior, `codes()`/`label()`/`group_codes()`, ENUM divergence logic
- [ ] `tests/unit/test_vocabulary_drift_audit.py` — covers the `''`-filter and `regime_group`-scoping logic in isolation from the DB
- [ ] `tests/integration/test_vocabulary_api.py` — covers the `/api/vocabulary/{namespace}` route against a real (test) DB
- [ ] No new pytest markers or framework install needed — `requires_db` marker already exists in `pytest.ini`

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | This is an internal, solo-project read-only metadata endpoint; no auth layer exists anywhere else in `src/api/routes/` either (confirmed: `drift.py`, `features.py` etc. have no auth dependency) |
| V3 Session Management | no | No sessions in this API |
| V4 Access Control | no | Same as V2 — no access-control layer exists in this codebase's API today |
| V5 Input Validation | yes | `namespace` path parameter must be validated against the known set of seeded namespaces (return an empty/404 response for unknown namespaces, not a raw SQL error) — same defensive style as `drift.py`'s try/except-on-DB-error |
| V6 Cryptography | no | No secrets or crypto in this phase's scope |

### Known Threat Patterns for this stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| SQL injection via `namespace` path param | Tampering | Parameterized query (`WHERE namespace = $1` via asyncpg, never string interpolation) — same pattern already used everywhere in this codebase (`asyncpg.Pool.fetch(query, param)`) |
| Unbounded `SELECT DISTINCT` full-hypertable scan (drift audit) | Denial of Service (self-inflicted, resource exhaustion) | Design doc already mandates a bounded, recent-window scan (`WHERE <time_col> > now() - <window>`), not a full-table distinct — carried through in this research's Code Examples |

## Sources

### Primary (HIGH confidence)
- `docs/research/concept-controlled-vocabulary.md` — full design doc, read in entirety
- `docs/research/concept-governance-registries.md` — registry family framework
- `docs/research/concept-unified-registry.md` (partial, lines 1-411) — `ConceptRegistryService` sibling pattern, "When to Add a New Registry" rule
- `src/config/config_service.py` — live `ConfigService` code, read in full header + method list
- `services/data_quality_auditor.py` — live code, read in full
- `services/service_auditor.py` — live `_DAG_ORDER` registry, read in full for auditor liveness classification
- `src/api/main.py`, `src/api/routes/drift.py` — live FastAPI app + router precedent, read in full
- `src/observability/metrics.py` — live counter/gauge helper conventions
- `services/ic_engine.py` (lines 2500-2650) — live `integrity_monitor` write pattern
- Direct psql queries against the live `indicagent` database (`feature_vectors.regime`,
  `market_regimes.regime_label`+`regime_group`, `feature_registry.tier`,
  `instruments.contract_details->>'asset_class'`, `market_data_ohlcv.timeframe`) — the source of
  all three Critical/Finding discrepancies above
- `production/migrations/` directory listing — migration numbering (highest existing: 236;
  next free: 237)
- `.planning/todos/pending/101-*.md` — confirms the 13 pre-existing duplicate-migration-number
  groups, cross-checked against a direct `ls`+grep of the migrations directory

### Secondary (MEDIUM confidence)
- CLAUDE.md's "all systemd timers are confirmed disabled as of 2026-07-02" statement — stated in
  the context of `roll-batch` specifically but phrased as a blanket claim; treated as MEDIUM
  confidence pending direct production-host verification (see Assumptions Log A1)

### Tertiary (LOW confidence)
None — every claim in this document is either read directly from live source code, queried
directly against the live database, or explicitly flagged in the Assumptions Log.

## Metadata

**Confidence breakdown:**
- Standard stack / schema / service pattern: HIGH — directly copied from live, working sibling code (`ConfigService`, `drift.py`, `ic_engine.py`'s `integrity_monitor` usage)
- Seed data accuracy: MEDIUM — 2 of 5 namespaces (`regime_cross_sectional`, `tier`) have confirmed live-DB discrepancies against the design doc/CONTEXT.md that need a decision before migration; 3 of 5 (`regime_hmm`, `asset_class`, `timeframe`) verified clean
- Drift-audit host: MEDIUM — the CONTEXT.md-suggested host has a real, evidenced structural weakness (dead checks, possibly-dead timer); the fallback (`bar_auditor.py`) is a valid but not perfectly-scoped alternative

**Research date:** 2026-07-16
**Valid until:** 2026-08-15 (30 days — stable internal architecture pattern; live-data snapshots (regime label counts, tier counts) should be re-verified at planning/implementation time if more than a few days pass, since the corpus is actively re-running per `.planning/STATE.md`)
