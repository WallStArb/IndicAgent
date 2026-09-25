# Phase 182: Security classification hierarchy (todo 384) - Research

**Researched:** 2026-09-25
**Domain:** Point-in-time reference-data schema + cached read-layer service + IBKR contract-detail sourcing (Python/PostgreSQL/TimescaleDB, asyncpg, ib_async)
**Confidence:** HIGH (schema/patterns, live-verified against running DB and source tree) / MEDIUM (GICS industry-group naming, cited not licensed) / LOW (exact IBKR industry/category/subcategory coverage for the 40 pilot names as of today - last verified 2026-09-18, one week stale)

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

- **D-01 Scope is Layer 1 only.** `classification_scheme`, `classification_node`,
  `instrument_classification` exactly as the design doc specifies: point-in-time,
  append-only in effect (close `valid_to`, insert new), `ON DELETE RESTRICT`, partial unique
  index for one current row per (symbol, scheme), node-immutability guard in the seed (parent
  and level never change for a code; the seed crashes on disagreement). Layer 2's `parent_tag`
  is NOT built: the design doc's own trigger (a first hierarchical-tag consumer) has not fired.
- **D-02 First scheme: `indicagent_v1`, project-owned, four levels:** asset class > sector >
  industry group > industry. Codes embed their parent (`EQ`, `EQ.IT`, `EQ.IT.SEMI`,
  `EQ.IT.SEMI.EQUIP`), so a reparent mints a new code, as in GICS. `parent_code` is still
  stored explicitly (design doc rule).
- **D-03 Equity levels 2-4 follow the public GICS structure** (11 sectors, industry groups,
  industries) by name, but the scheme is not GICS and must not be called GICS: GICS
  assignments are licensed, and ETFs have none. `authority` = 'IndicAgent', `source_ref`
  records how each assignment was made.
- **D-04 Non-equity asset classes:** fixed income, commodity, currency, crypto, volatility,
  multi-asset, each with its own level-2 split (for example fixed income > rates / credit /
  municipal / inflation-linked / preferred; commodity > energy / precious metals / industrial
  metals / agriculture / broad). Exact node list is a plan deliverable, reviewed before seeding.
- **D-05 Assignment depth follows the instrument.** A single name goes to its industry (level
  4). An ETF goes to the deepest level its mandate pins down (SMH to the semiconductors
  industry; XLK to the IT sector; SPY to the equity asset class with a broad-market sector
  node). Assignment above the leaf is allowed by the design; consumers asking for a deeper level
  get the explicit `unclassified` stratum (D-08).
- **D-06 Sources.** Single names: IBKR `reqContractDetails` industry / category / subcategory,
  fetched through `src/providers/ibkr.py` (the only ib_async file), used as a seed candidate and
  human-reviewed into `indicagent_v1` nodes. ETFs: fund mandate (name, issuer description).
  `source_ref` distinguishes `ibkr_contract_details+review` from `fund_mandate`. The reviewed
  mapping is committed as data (a seed file or migration), never computed at runtime.
- **D-07 No history before the build date.** Every assignment's `valid_from` is the build date.
  The scheme did not exist earlier, so any earlier row would be a backfill from a current
  snapshot, which the design forbids. Research over pre-build history uses the causal
  clusters, not this table. Reclassifications from the build date on close the old row and
  insert a new one.
- **D-08 Read layer.** `ClassificationService` (`src/config/`, cached at init like
  `ConfigService` and `VocabularyService`, no hot-path DB calls): as-of lookup of a symbol's node
  at a requested level, returning the scheme-qualified `unclassified` label, never NULL, when
  the assignment does not reach that level or does not exist as of that date.
- **D-09 Coverage is enforced, not hoped for.** Every active instrument gets a current
  `indicagent_v1` assignment in this phase (273 today, including the 40 unlabeled 1d-pilot
  names). Onboarding (`src/config/instrument_onboarding.py`) requires a classification for any
  new instrument. A unit or CI test fails when an active instrument has no current assignment.
- **D-10 The flat label stops being a source of truth.** Its readers
  (`src/config/settings.py` Instrument.sector, `src/intelligence/pipeline/cache_manager.py`,
  `src/api/routes/signals.py`) move to `ClassificationService` (sector = level-2 node name).
  The JSON field stays in `contract_details` as historical data and is no longer written.
- **D-11 Migration discipline.** Schema and seed land as numbered migrations, applied live and
  committed in the same breath (CLAUDE.md rule). Next free number at plan time (363 is taken;
  verified live this session — 364 is next free).

### Claude's Discretion

Not present as a separate section in this phase's CONTEXT.md. The nearest equivalent is D-04's
"exact node list is a plan deliverable, reviewed before seeding" — the non-equity level-2 splits
are locked in shape (fixed income / commodity / currency / crypto / volatility / multi-asset,
each with its own children) but the precise child-node list is left to plan-time design, reviewed
before the seed migration lands.

### Deferred Ideas (OUT OF SCOPE)

- Layer 2 `parent_tag` and any custom soft taxonomy (D-01).
- GICS or any licensed classification feed; SIC or ICB schemes.
- Issuer identity (GOOG/GOOGL both carry rows, design doc open question 2).
- Using this table in the research residual target (S1 uses causal clusters by decision,
  2026-09-25).
- Options open-interest capture (an open owner question, separate).
</user_constraints>

<phase_requirements>
## Phase Requirements

No formal `REQUIREMENTS.md` IDs exist for this phase; CONTEXT.md's locked decisions D-01..D-11
serve as this phase's requirements and are used as the ID scheme below.

| ID | Description | Research Support |
|----|-------------|------------------|
| D-01 | Layer 1 only: 3 tables, append-only-in-effect, `ON DELETE RESTRICT`, partial unique current-row index, node-immutability guard | Pattern 3 (schema shape), Pattern 4 (migration guard idiom, live precedent migration 363), Pitfall 1 (do not copy `instrument_tags`' non-append-only PK) |
| D-02 | `indicagent_v1` scheme, 4 levels, self-nesting codes, explicit `parent_code` | Architecture Patterns, live confirmation next migration number is 364 |
| D-03 | Equity levels 2-4 named after public GICS structure, not licensed, `authority='IndicAgent'` | Code Examples (11 sectors / 25 industry groups, CITED Wikipedia), Anti-Patterns ("never call it GICS"), Assumption A1 |
| D-04 | Non-equity asset-class level-2 splits, exact list a plan deliverable | Standard Stack / Architecture note distinguishing CVR's `asset_class` namespace from the new scheme's level-1 nodes (live-verified conflict risk) |
| D-05 | Assignment depth follows the instrument (single names to level 4, ETFs to mandate depth) | Verified live counts (168 single names / 105 ETFs), Anti-Patterns (don't seed unused level-4 nodes) |
| D-06 | Sourcing: IBKR contract details (single names, human-reviewed) / fund mandate (ETFs) | `src/providers/ibkr.py` read (confirmed no industry/category/subcategory sourced today), Code Examples (where a new fetch attaches), Pitfall 4 (re-fetch, don't reuse stale 2026-09-18 data) |
| D-07 | No pre-build-date history; accumulate forward only | Pattern 3 (as-of query shape), design doc cross-check (no change needed vs. locked decision) |
| D-08 | `ClassificationService`, cached at init, no hot-path DB calls, `unclassified` fallback, never NULL | Pattern 1 (VocabularyService template, full file read), Pattern 2 (Ring 0 access wrapper), Validation Architecture (unit test template) |
| D-09 | Coverage enforced: onboarding gate + a test that fails on any active-instrument gap | Pattern 4 (seed-time RAISE guard), Pattern 5 (onboarding gate template), Pitfall 2 (CI-cannot-run-DB-tests conflict — flagged, not a decision change), Open Question 2 |
| D-10 | Flat-label readers move to `ClassificationService`; JSON field frozen as historical | Verified live reader map (`settings.py`, `cache_manager.py`, transitively `signals.py`), Pitfall 5 (`snapshot.py`/`panel.py` correctly out of scope) |
| D-11 | Numbered migration, applied live + committed together, next number confirmed | Verified live: `production/migrations/` sorted listing, 364 is next free |
</phase_requirements>

## Summary

This phase builds three new tables (`classification_scheme`, `classification_node`, `instrument_classification`), one migration-seeded scheme (`indicagent_v1`, 4 levels), one cached read-layer service (`ClassificationService`), and moves three call sites off the flat `contract_details->>'sector'` label. The design doc (`docs/research/stratification-security-classification-hierarchy.md`) is complete, twice-reviewed, and CONTEXT.md's D-01..D-11 lock every structural choice - this research verifies the doc's assumptions against the *current* live DB/codebase (some of it is 2-3 months stale) and maps every concrete file this phase must touch.

Two live-verified facts change the shape of the work versus what the design doc and todo 384 assumed: (1) `instrument_tags` already carries `valid_from`/`valid_to` columns (added by Phase 175's materiality filter, unrelated to this phase) but keeps `PRIMARY KEY (symbol, tag)` - not append-only - so it is *not* a template to copy for `instrument_classification`'s append-only PK; the actual point-in-time precedent to copy is `contract_metadata`'s roll-tracking shape plus `context_writer.py`'s `AND valid_to IS NULL` as-of-read idiom. (2) `signals.py`'s "asset_class" grouping endpoint does not read `contract_details->>'sector'` directly - it reads `Instrument.sector`, which is populated in exactly two builder functions (`settings.py::_build_instrument_from_db_row`, `cache_manager.py::_instrument_from_row`). Fixing those two functions to read from `ClassificationService` transitively fixes `signals.py` with no edit there at all. This shrinks D-10's three-reader list to two real edit sites plus one consumer that inherits the fix for free.

The one real friction point against the locked decisions: D-09 says "a unit or CI test fails when an active instrument has no current assignment." This project's actual GitHub Actions CI (`.github/workflows/ci.yml`) runs only `pytest tests/unit/` with **no live database** - confirmed by the `test` job definition and by `tests/integration/conftest.py`'s own docstring ("this suite only runs under `pytest -m integration`, never in CI"). A true DB-coverage check cannot run in GitHub CI; it must live in `tests/integration/` (matching the existing `test_instrument_registry.py` precedent) and is enforced only when someone runs it locally, or be replaced with a migration-time `DO $$ ... RAISE EXCEPTION` guard (matching migration 363's own pattern) that only checks the seed's own moment-in-time coverage, not future drift. D-09 itself is not wrong to keep, but the plan needs to pick one of these two enforcement points explicitly rather than assume "CI-enforced" means what it means in other CLAUDE.md-cited examples (`test_todo_priorities_link_integrity.py`, `test_compressed_hypertable_migration_vacuum_check.py`) - both of those are pure-filesystem checks with no DB dependency, which is exactly why they can be true GitHub CI gates and this one cannot be, in the same form.

**Primary recommendation:** Build Layer 1 exactly as CONTEXT.md and the design doc specify; source single-name industry/category/subcategory via a new one-off script calling `IBKRProvider.qualify_instrument()`'s underlying `reqContractDetailsAsync` (which does not currently request/store `industry`/`category`/`subcategory` - a new provider method is needed) against the 168 `single_name_equity`-tagged symbols; seed `indicagent_v1`'s equity levels 2-4 with GICS-derived *names* (11 sectors, 25 industry groups verified below; industries derived from the actual 168-symbol universe's IBKR categories, not a blind copy of all 74 published GICS industries); enforce coverage via a migration-time RAISE guard (seed-time) plus a `tests/integration/` DB test (drift-time, run manually, documented as not a GitHub CI gate); wire `ClassificationService` through a `src/core/classification_access.py` Ring-0 wrapper mirroring `vocabulary_access.py` byte-for-byte in shape.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Scheme/node/membership schema (3 tables) | Database / Storage | — | Reference data, migration-seeded, read-only at runtime (design doc gate check §3) |
| As-of classification lookup | API / Backend (library) | — | `ClassificationService` is an embedded library like `ConfigService`/`VocabularyService`, not a network service - runs in-process inside every daemon/API/script that needs it |
| Coverage enforcement at onboarding | API / Backend | Database / Storage | `onboard_instrument()` (`src/config/instrument_onboarding.py`) is the sole write path; the check belongs in its transaction, not a separate cron |
| Coverage drift detection (existing rows) | Database / Storage | API / Backend | Needs a live query against `instruments` + `instrument_classification`; cannot be a pure-filesystem unit test (see Summary) |
| IBKR industry/category/subcategory sourcing | API / Backend | — | `src/providers/ibkr.py` is the sole ib_async file (Ring rule); a new method there, called by a one-off onboarding-adjacent script, not a live daemon |
| Flat-label readers (`settings.py`, `cache_manager.py`) | API / Backend | — | In-process Python builder functions constructing `Instrument` objects from DB rows |
| `signals.py` sector grouping | API / Backend | — | Inherits the fix transitively via `Instrument.sector`; no direct edit needed once the builders above are fixed |

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| asyncpg | already pinned in `requirements.txt` (project-wide) | DB access for `ClassificationService`, seed migration verification | Existing project standard; `create_pool()` registers JSONB codec, matches every other `*Service` in `src/config/` |
| ib_async | already pinned (project-wide, `src/providers/ibkr.py` only) | `reqContractDetailsAsync` call to source `industry`/`category`/`subcategory` | Sole sanctioned ib_async entry point per Ring rule; no new dependency |
| structlog | already pinned | Logging in the new service and seed script | Project-wide standard (`setup_service_logging`) |

No new third-party packages are required. This phase is pure schema + Python using the exact same libraries every sibling registry (`VocabularyService`, `ConfigService`, `TagCalibrator`) already uses.

## Package Legitimacy Audit

**Not applicable.** This phase installs zero new external packages - `asyncpg`, `ib_async`, and `structlog` are already present in `requirements.txt` and used identically by `VocabularyService`/`ConfigService`/`ibkr.py`. No `pip install` step, no `npm install`, nothing for slopcheck to gate.

## Verified live-DB state (2026-09-25, `PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent`)

| Fact | Value | Source |
|------|-------|--------|
| Active instruments (`is_active=true`) | 273 | `SELECT count(*) FROM instruments WHERE is_active=true` |
| `single_name_equity`-tagged instruments | 168 | `SELECT count(*) FROM instrument_tags WHERE tag='single_name_equity'` |
| ETFs (273 - 168) | 105 | derived |
| `contract_details->>'asset_class'` values among active rows | `equity` (273), no `futures`/`fx` active today | matches root CLAUDE.md's "Live IBKR streaming still DOWN" note - futures/fx are `is_active=false` |
| Unlabeled sector (`sector IS NULL OR ''`) among active rows | Exactly the 40 symbols named in CONTEXT.md/todo 384 (ACTG, ALMS, ARRY, ATMU, AVBP, BEAM, BKE, CASY, CENT, COFS, CRI, CRUS, CRWV, CSTM, DAR, FRHC, GKOS, GRBK, INSW, JBS, KEX, MAR, MGM, MTH, PGNY, PURR, RCL, RGR, RIVN, RJF, SLM, SPNT, SSP, THRM, TXT, UNFI, UPB, VNDA, WCC, WSHP) | 40 | live query - unchanged since todo filed, confirms migration 363 did not touch these (they are single names, migration 363 scoped to ETFs only) |
| All 40 unlabeled symbols carry `single_name_equity` tag | yes | live query confirms they are a subset of the 168, not a separate cohort |
| Next free migration number | 364 | `ls production/migrations/ | sort` - 363 is `363_sector_label_fixes.sql`, confirmed taken per CONTEXT.md D-11 |
| CVR `asset_class` namespace | `equity`/`futures`/`fx` only (3 codes) | `SELECT * FROM controlled_vocabulary WHERE namespace='asset_class'` |

**Important distinction the plan must not blur:** CVR's `asset_class` namespace (equity/futures/fx - how IBKR settles the contract) is a *different concept* from `indicagent_v1`'s level-1 node "asset class" (equity/fixed_income/commodity/currency/crypto/volatility/multi_asset - what economic exposure the instrument represents, per D-04). Today's flat `sector` field already conflates these: `TLT` has `contract_details.asset_class='equity'` (it is a stock-market-traded ETF share) but should land on `indicagent_v1`'s `fixed_income` asset-class node. This is exactly the ambiguity the new hierarchy exists to resolve - name the two things differently in code/docs (`contract_asset_class` vs. `classification_node` level-1) so a reviewer never conflates CVR's namespace with the new scheme's root level.

## Architecture Patterns

### System Architecture Diagram

```
                     ┌─────────────────────────────┐
                     │  IBKR Gateway (reqContract-  │
                     │  DetailsAsync)               │
                     └──────────────┬───────────────┘
                                    │ industry/category/subcategory
                                    │ (one-off script, human-reviewed)
                                    ▼
                     ┌─────────────────────────────┐
                     │ Migration NNN_indicagent_v1_ │   (seed: scheme + nodes
                     │ classification_scheme.sql   │    + 273 instrument rows,
                     └──────────────┬───────────────┘    node-immutability guard,
                                    │ applied live + committed together   coverage RAISE)
                                    ▼
        ┌───────────────────────────────────────────────────┐
        │  classification_scheme / classification_node /     │
        │  instrument_classification  (TimescaleDB, Ring 0)  │
        └──────────────────────┬──────────────────────────────┘
                                │ prewarm() at process startup
                                ▼
        ┌───────────────────────────────────────────────────┐
        │  ClassificationService (src/config/, cached,        │
        │  zero hot-path DB calls) via                         │
        │  src/core/classification_access.py (Ring 0 wrapper)  │
        └──────┬───────────────────┬───────────────────┬─────┘
               │                   │                   │
   as-of node lookup      onboard_instrument()   settings.py /
   (research, reporting,  coverage gate           cache_manager.py
   peer baskets - out of  (D-09)                   Instrument.sector
   scope this phase)                               builders (D-10)
                                                         │
                                                         ▼
                                              signals.py sector-grouping
                                              endpoint (inherits fix,
                                              no direct edit needed)
```

### Recommended Project Structure
```
production/migrations/
└── 364_indicagent_v1_classification_scheme.sql   # tables + seed + node-immutability guard + coverage RAISE

src/config/
├── classification_service.py     # ClassificationService, mirrors vocabulary_service.py
└── instrument_onboarding.py      # add classification requirement (D-09 hook)

src/core/
└── classification_access.py      # prewarm()/set_.../codes-style Ring 0 wrapper, mirrors vocabulary_access.py

scripts/infrastructure/
└── classification_ibkr_sourcing.py   # one-off: reqContractDetailsAsync for 168 single names -> candidate CSV/JSON for human review

tests/unit/
├── test_classification_service.py          # pure-Python, no-DB (mirrors test_vocabulary_service.py)
└── _classification_fakes.py                # FakeClassificationService (mirrors _vocabulary_fakes.py)

tests/integration/
└── test_instrument_classification_coverage.py   # live-DB: every active instrument has a current row (D-09 drift check)
```

### Pattern 1: Cached read-layer service, mirroring VocabularyService exactly
**What:** Constructor takes `(database_url, pool=None)`, `initialize()` does one prewarm pass and populates plain dicts, all hot-path readers are synchronous dict lookups, no lazy DB fallback ever.
**When to use:** `ClassificationService` per D-08.
**Example:**
```python
# Source: src/config/vocabulary_service.py (verified live, this exact shape)
class ClassificationService:
    def __init__(self, database_url: str, pool: asyncpg.Pool | None = None) -> None:
        self._database_url = database_url
        self._db_pool = pool
        # (scheme, symbol) -> list of _Assignment rows sorted by valid_from, for as-of lookup
        self._assignments: dict[tuple[str, str], list[_Assignment]] = {}
        self._nodes: dict[tuple[str, str], _Node] = {}  # (scheme, code) -> node

    async def initialize(self) -> None:
        if self._db_pool is None:
            self._db_pool = await create_pool(self._database_url, pool_name="classification_service")
        await self._load_all()

    def node_at_level(self, symbol: str, scheme: str, level: int, as_of: date | None = None) -> str:
        """Returns the code at `level`, or f"{scheme}:unclassified" if the assignment
        doesn't reach that level or none exists as-of the given date (D-08 - never NULL)."""
```

### Pattern 2: Ring 0 access wrapper (avoid threading the instance through every constructor)
**What:** `src/core/classification_access.py` — `prewarm()`, `set_classification_service()`, `reset_..._for_test()`, plus thin sync read wrappers.
**When to use:** Every daemon/script/API route that needs classification lookups without re-plumbing a constructor argument through every call site (same justification `vocabulary_access.py` gives for todo 327).
**Example:**
```python
# Source: src/core/vocabulary_access.py (verified live, this exact shape - todo 327/330)
async def prewarm(database_url: str, pool: asyncpg.Pool | None) -> ClassificationService:
    svc = ClassificationService(database_url, pool=pool)
    await svc.initialize()
    set_classification_service(svc)
    return svc
```
Existing daemon call sites that already do the equivalent for `VocabularyService` (`services/bar_writer.py:253`, `services/feature_vector_pipeline.py:967`, `services/signal_auditor.py:142`) are the wiring template if/when a live daemon needs classification lookups; this phase's actual consumers (`settings.py`, `cache_manager.py`, `instrument_onboarding.py`) are simpler call sites (scripts/library code, not long-running daemons), so a direct `ClassificationService(...)` construction with the process's own pool may be simpler than the full prewarm-registration dance — the wrapper is still worth building for the API/reporting consumers and any future daemon consumer, but don't force every call site through it if a call site never had a `VocabularyService`-style multi-consumer problem to begin with.

### Pattern 3: Point-in-time schema with a partial unique "current row" index
**What:** `instrument_classification(symbol, scheme, code, valid_from, valid_to, source_ref)`, `PRIMARY KEY (symbol, scheme, valid_from)`, `UNIQUE INDEX ... WHERE valid_to IS NULL`.
**When to use:** Exactly as specified in the design doc and D-01 — do not copy `instrument_tags`' shape (see Common Pitfalls #1).
**Example:**
```sql
-- Source: docs/research/stratification-security-classification-hierarchy.md (Layer 1 schema),
-- as-of read idiom cross-checked against services/context_writer.py:53's live
-- `AND valid_to IS NULL` pattern (the one existing precedent for this exact query shape).
CREATE UNIQUE INDEX uq_instrument_classification_current
    ON instrument_classification (symbol, scheme)
    WHERE valid_to IS NULL;

-- As-of query for a historical join (never "get current for a past date"):
SELECT code FROM instrument_classification
WHERE symbol = $1 AND scheme = $2
  AND valid_from <= $3 AND (valid_to IS NULL OR valid_to > $3);
```

### Pattern 4: Migration seed with a hard-fail guard (node-immutability + coverage)
**What:** A `DO $$ ... RAISE EXCEPTION` block after the seed INSERT, checked against live data, exactly like migration 363.
**Example:**
```sql
-- Source: production/migrations/363_sector_label_fixes.sql (live, verified pattern in this repo)
DO $$
DECLARE
    bad TEXT;
BEGIN
    SELECT string_agg(symbol, ', ' ORDER BY symbol) INTO bad
    FROM instruments i
    WHERE i.is_active
      AND NOT EXISTS (
          SELECT 1 FROM instrument_classification ic
          WHERE ic.symbol = i.symbol AND ic.scheme = 'indicagent_v1' AND ic.valid_to IS NULL
      );
    IF bad IS NOT NULL THEN
        RAISE EXCEPTION 'active instruments still without a current indicagent_v1 assignment: %', bad;
    END IF;
END $$;
```
This gives D-09's coverage guarantee *at seed time* for free, using an idiom already proven in this exact codebase. It does not catch future drift (a new instrument onboarded outside `onboard_instrument()`, or a raw `UPDATE instruments SET is_active=true`) — that is `onboard_instrument()`'s job (Pattern 5) plus the `tests/integration/` drift check (see Common Pitfalls #2).

### Pattern 5: Onboarding-time coverage gate
**What:** `onboard_instrument()` (`src/config/instrument_onboarding.py`) currently requires `metadata` or an explicit `metadata_skip_reason` (D-08's precedent, same phase-174 mandate shape D-09 wants for classification). Add a parallel required argument.
**Example:**
```python
# Source: src/config/instrument_onboarding.py (live, verified — same "no silent omission"
# API shape this phase should reuse for classification, not reinvent):
if metadata is None and not metadata_skip_reason:
    raise ValueError(
        "onboard_instrument: metadata is None and metadata_skip_reason is empty -- "
        "a silent instrument_metadata omission is not permitted (D-08, todo 282)."
    )
# New, mirrored:
if classification_code is None and not classification_skip_reason:
    raise ValueError(
        "onboard_instrument: classification_code is None and classification_skip_reason "
        "is empty -- a silent instrument_classification omission is not permitted (D-09, todo 384)."
    )
```

### Anti-Patterns to Avoid
- **Copying `instrument_tags`' PK shape for `instrument_classification`:** `instrument_tags` has `PRIMARY KEY (symbol, tag)` even though it now has `valid_from`/`valid_to` columns (Phase 175) — it is not append-only, a reclassification would overwrite in place. The design doc's `PRIMARY KEY (symbol, scheme, valid_from)` is deliberately different and must be built that way, not copied from the nearest-looking existing table.
- **Treating "CI-enforced" as meaning GitHub Actions can run a live-DB coverage check:** it cannot (see Summary). Pick `tests/integration/` explicitly and document that the check runs on-demand/pre-merge locally, not on every push.
- **Calling the new scheme "GICS" anywhere in code, migrations, or docs:** D-03 is explicit — `authority='IndicAgent'`, never S&P/MSCI's trademark, because assignments are IBKR-category-derived and human-reviewed, not licensed data.
- **Seeding all 74 published GICS industries up front:** D-05 says assignment depth follows the instrument, and this project has 168 single names, not 3,000. Seed the industry-group level (25, name-verified below) fully, but only seed industry-level (level 4) nodes for industries the actual universe needs — extra unused nodes are dead rows with no consumer, the same anti-pattern CVR's own "no namespace without a concrete consumer" rule already names.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Cached read layer with hot-path-safe lookups | A bespoke dict-cache class | Mirror `VocabularyService`'s exact shape (constructor, `initialize()`, sync readers) | Two working, tested precedents already exist in this exact codebase (`ConfigService`, `VocabularyService`) — a third one-off shape is pure inconsistency risk with zero benefit |
| Cross-daemon service registration | A DI container or global singleton pattern of its own design | `src/core/classification_access.py`, mirroring `vocabulary_access.py`'s `prewarm()`/`set_...`/`reset_..._for_test()` triplet | Already the established Ring-0 idiom for exactly this problem (todo 327) |
| Point-in-time membership tracking | A generic "temporal table" library or trigger-based history table | The explicit close-old-row/insert-new-row pattern the design doc specifies, matching `config_history`/`concept_transition_log`'s existing append-only shape | Simpler, auditable, no extension dependency, and every other point-in-time table in this codebase already does it this way |
| GICS industry taxonomy | Scraping/copying a full commercial GICS code list into a migration | Public sector/industry-group *names* only (11/25, cited below), industries derived from live IBKR `category` values for the actual 168-symbol universe | D-03 explicitly forbids using licensed GICS codes; the real universe is small enough that deriving from actual data is both correct and cheaper than a blind full taxonomy import |

**Key insight:** every piece of infrastructure this phase needs (cached service, Ring-0 access wrapper, point-in-time schema, migration-guard idiom, onboarding required-field pattern) already has one-to-three live, working precedents in this exact codebase. There is no genuinely novel engineering problem here — the entire task is applying five existing patterns to one new domain.

## Runtime State Inventory

Not applicable in the rename/refactor sense (no renaming, no existing runtime state migration) — however, this phase does retire a field as a source of truth (D-10), so the relevant categories are checked:

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | `instruments.contract_details->>'sector'` — 273 active rows carry it (233 with a value, 40 blank) | No migration of the JSON field itself (D-10: "stays in `contract_details` as historical data ... no longer written"). New writes go to `instrument_classification` instead; the flat field is frozen, not deleted. |
| Live service config | None found — no external service (n8n, Datadog, etc.) references sector labels | None |
| OS-registered state | None | None |
| Secrets/env vars | None | None |
| Build artifacts | None — no compiled artifact embeds sector strings | None |

## Common Pitfalls

### Pitfall 1: Building `instrument_classification` with `instrument_tags`' non-append-only PK
**What goes wrong:** A reclassification silently overwrites history instead of closing the old row and inserting a new one, defeating the entire point-in-time justification for this system.
**Why it happens:** `instrument_tags` is the closest-looking existing table (same `symbol`, has `valid_from`/`valid_to`) and is easy to copy from without checking its actual PK.
**How to avoid:** `PRIMARY KEY (symbol, scheme, valid_from)` exactly as the design doc specifies (verified: `instrument_tags` is `PRIMARY KEY (symbol, tag)`, confirmed live via `\d instrument_tags`).
**Warning signs:** A migration or `ClassificationService` write path that does `ON CONFLICT (symbol, scheme) DO UPDATE` anywhere.

### Pitfall 2: Assuming "CI-enforced" (D-09) means GitHub Actions
**What goes wrong:** A plan writes a `tests/unit/` test that opens a live DB connection; it either fails on every GitHub Actions run (no DB available) or is silently skipped, giving false confidence that coverage is enforced.
**Why it happens:** Other CLAUDE.md-cited CI-enforced examples (`test_todo_priorities_link_integrity.py`, `test_migration_number_uniqueness.py`, `test_compressed_hypertable_migration_vacuum_check.py`) are all pure-filesystem checks that genuinely do run in GitHub CI — the pattern looks reusable but isn't, because this check's subject (live table row counts) has no filesystem representation.
**How to avoid:** Put the coverage check in `tests/integration/` (matching `test_instrument_registry.py`'s existing precedent, `pytest -m integration`, run locally/pre-merge) and rely on the migration-time RAISE guard (Pattern 4) for the one moment GitHub CI *can* verify anything relevant (the migration file's own text, via `test_migration_number_uniqueness.py`-style filesystem checks — though that only checks numbering, not the guard's logic).
**Warning signs:** A new `tests/unit/` file importing `asyncpg` or calling `get_settings().database_url`.

### Pitfall 3: Conflating `contract_details->>'asset_class'` with the new scheme's level-1 "asset class"
**What goes wrong:** Code or a migration comment implies the two are the same field, and a future reader assumes filtering on `contract_details->>'asset_class'='equity'` already gives "true equities" — it gives "instruments settled as an equity trade," which includes TLT, GLD, SMH, etc.
**Why it happens:** Both use the words "asset class"; CVR even has a same-named `asset_class` namespace with different values than D-04's level-1 node list.
**How to avoid:** Name things precisely in docstrings/comments — "contract asset class" (existing, IBKR-settlement-type) vs. "classification asset-class node" (new, economic-exposure). Never write bare "asset_class" in this phase's new code without the qualifier.
**Warning signs:** A `WHERE contract_details->>'asset_class' = ...` clause inside code that is supposed to be reading the new hierarchy.

### Pitfall 4: Re-fetching IBKR contract details without checking staleness
**What goes wrong:** Todo 384's 100%-coverage claim for 168/168 names is dated 2026-09-18 — 7 days stale as of this research, and 40 of the 168 (the 1d-only pilot cohort) were confirmed *unlabeled* in the flat field on 2026-09-25, meaning they may not have been part of that earlier 168-name IBKR probe at all (the pilot cohort was likely added or promoted after 2026-09-18's probe). The plan must not assume the earlier IBKR category data still covers 100% of today's 168 without re-running the probe.
**Why it happens:** A stale "coverage confirmed" claim from a todo file gets treated as still-current fact.
**How to avoid:** Re-run `reqContractDetailsAsync` against the live universe (all 168 current `single_name_equity` symbols) as this phase's own sourcing step, not a reuse of the earlier session's output.
**Warning signs:** A seed migration or CSV that doesn't have a fresh `fetched_at` timestamp from this phase's own run.

### Pitfall 5: Treating `snapshot.py`/`panel.py`'s sector capture as a D-10 violation
**What goes wrong:** A reviewer sees `src/intelligence/research/snapshot.py` reading `contract_details->>'sector'` (verified live, line 43) and flags it as an un-migrated reader, triggering unnecessary scope creep into the research panel format.
**Why it happens:** It is a literal read of the flat field, matching D-10's trigger pattern on the surface.
**How to avoid:** This is explicitly *not* one of D-10's three named readers, and the field is deliberately kept as historical/provenance data ("as S0 captured it," per `panel.py`'s own comment) — S1 (`factors.py`) already stopped using it for grouping (commit `a43bada3b`, 2026-09-25). D-10 only requires migrating readers that treat the field as current source-of-truth for decisions; a frozen provenance snapshot is fine to leave alone.
**Warning signs:** A plan task that edits `snapshot.py` or `panel.py` for this phase — almost certainly out of scope.

## Code Examples

### GICS sector/industry-group names (public, for D-03's name-only reuse)
```
// Source: https://en.wikipedia.org/wiki/Global_Industry_Classification_Standard
// (CITED, MEDIUM confidence — public taxonomy names only, no codes/assignments,
// per D-03's explicit "GICS assignments are licensed" constraint)

Energy
  - Energy
Materials
  - Materials
Industrials
  - Capital Goods
  - Commercial & Professional Services
  - Transportation
Consumer Discretionary
  - Automobiles & Components
  - Consumer Durables & Apparel
  - Consumer Services
  - Consumer Discretionary Distribution & Retail
Consumer Staples
  - Consumer Staples Distribution & Retail
  - Food, Beverage & Tobacco
  - Household & Personal Products
Health Care
  - Health Care Equipment & Services
  - Pharmaceuticals, Biotechnology & Life Sciences
Financials
  - Banks
  - Financial Services
  - Insurance
Information Technology
  - Software & Services
  - Technology Hardware & Equipment
  - Semiconductors & Semiconductor Equipment
Communication Services
  - Telecommunication Services
  - Media & Entertainment
Utilities
  - Utilities
Real Estate
  - Equity Real Estate Investment Trusts (REITs)
  - Real Estate Management & Development
```
11 sectors, 25 industry groups (counted and verified: 1+1+3+4+3+2+3+3+2+1+2 = 25). This is the 2023 revision (Communication Services split from IT/Consumer Discretionary in 2018, payment processors moved IT→Financials in March 2023 — both already reflected in this list, per MSCI's own methodology PDF found during this research but not fully fetched). **Not independently cross-checked against the primary MSCI PDF** — flagged as an Assumption below; recommend a 10-minute spot-check against `msci.com/documents/1296102/11185224/GICS+Methodology+2023.pdf` before the seed migration locks these 25 names in.

### `onboard_instrument()`'s existing no-silent-omission pattern (template for D-09's hook)
```python
# Source: src/config/instrument_onboarding.py (live, verified, lines ~262-268)
if metadata is None and not metadata_skip_reason:
    raise ValueError(
        "onboard_instrument: metadata is None and metadata_skip_reason is empty -- "
        "a silent instrument_metadata omission is not permitted (D-08, todo 282). "
        f"...(symbol={instrument.symbol!r}) has no metadata row."
    )
```

### IBKR contract qualification call site (where a new industry/category/subcategory fetch attaches)
```python
# Source: src/providers/ibkr.py (live, verified, lines ~1019-1027)
details = await asyncio.wait_for(
    self._ib.reqContractDetailsAsync(contract), timeout=_CONTRACT_DETAILS_TIMEOUT_SEC
)
if details:
    qualified = details[0].contract
    # `details[0]` is an ib_async ContractDetails object -- .industry/.category/
    # .subcategory live here, NOT on `.contract`. Today's code only reads
    # `details[0].contract`; a new sourcing path must read `details[0].industry`
    # etc. directly, ideally via a new IBKRProvider method (e.g.
    # `fetch_contract_classification_hints(symbol)`) rather than overloading
    # `qualify_instrument`'s existing contract, which is on the hot connect path.
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|---------------|--------|
| Flat `contract_details->>'sector'` string, one level, mixes asset class and sector | `classification_scheme`/`classification_node`/`instrument_classification`, 4-level point-in-time hierarchy | This phase (182), migration 364 | `settings.py`/`cache_manager.py` builders read from `ClassificationService` instead of raw JSON |
| S1's residual factor grouped by flat sector label | S1 groups by causal price-correlation clusters (commit `a43bada3b`, `f83609725`, 2026-09-25) | Same day CONTEXT.md was authored | This phase is explicitly *off* the research critical path — its consumers are stratification/peer-groups/reporting, not S1 |

**Deprecated/outdated:**
- `contract_details->>'sector'` as a source of truth for grouping decisions: frozen as historical/provenance data only after this phase (D-10). Still read by `snapshot.py`/`panel.py` deliberately (Pitfall 5) — not deprecated for that specific provenance-capture use.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | The 25 GICS industry-group names listed above match the current (2023-revision) official structure exactly | Code Examples (GICS names) | Low-medium: these are display names/seed data only (D-03: name-only reuse, no codes/licensing), a wrong name is a one-line UPDATE later; but worth a 10-minute cross-check against the primary MSCI PDF before the seed migration is finalized, since Wikipedia is a secondary source |
| A2 | The earlier session's "168/168 IBKR coverage confirmed" claim (todo 384, dated 2026-09-18) still holds for today's exact 168-symbol universe | Common Pitfalls #4 | Medium: if the pilot 40 weren't part of that probe, the plan needs its own fresh `reqContractDetailsAsync` sourcing pass regardless — recommended regardless of this assumption's truth, so risk is contained by the recommendation itself |
| A3 | `onboard_instrument()`'s existing `metadata`/`metadata_skip_reason` pattern is the right template to mirror for a `classification_code`/`classification_skip_reason` pair (rather than, say, a hard requirement with no skip escape hatch) | Pattern 5 | Low: D-09 says "requires a classification for any new instrument" without specifying whether a skip-reason escape hatch should exist at all; the plan should decide explicitly whether onboarding a genuinely-unclassifiable instrument (rare) needs an escape hatch or should hard-fail with no exception, unlike metadata which has a legitimate "no data available" case |

## Open Questions (RESOLVED)

1. **Does D-09's onboarding gate need a skip-reason escape hatch, or should it hard-fail unconditionally?**
   - What we know: `metadata`'s existing pattern has a skip-reason escape hatch because some legitimately have no metadata (e.g. sparse index funds).
   - What's unclear: whether any instrument onboarded going forward could legitimately have no classifiable node (e.g. a truly novel multi-asset product) or whether `unclassified` (D-08's read-layer fallback) is only for pre-existing gaps, not new onboarding.
   - RESOLVED: no escape hatch (CONTEXT D-09; 182-04).
   - Recommendation: default to **no escape hatch** at onboarding (classification is always determinable to at least the asset-class level, unlike metadata which can be genuinely absent) — plan should confirm this in the task breakdown rather than blindly copying the metadata pattern's permissiveness.

2. **Where exactly does the D-09 coverage drift test live, and does it run in any automated hook at all?**
   - What we know: GitHub Actions CI cannot run it (no DB). `tests/integration/` exists and has the exact precedent (`test_instrument_registry.py`) but that suite is documented as never running in CI.
   - What's unclear: whether the project wants this as a genuinely manual/local-only check, or whether there's appetite for a lightweight local pre-commit/pre-merge hook (like `tools/pre-commit.hook`'s existing bash guards) that queries the DB directly, bypassing pytest's `-m integration` gate entirely.
   - RESOLVED: seed-time guard, onboarding gate, nightly audit, plus a tests/integration/ check (CONTEXT D-09; 182-06, 182-07).
   - Recommendation: put it in `tests/integration/`, matching precedent; note in the phase's SUMMARY that "CI-enforced" per D-09 means "enforced by a documented, run-before-merge integration test," not a GitHub Actions gate — this is a documentation clarification, not a design change, so it does not require reopening the locked decision.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| PostgreSQL/TimescaleDB (`indicagent` DB, local) | Migration 364, `ClassificationService` | ✓ | live, verified via psql this session | — |
| IBKR Gateway (`ib-gateway` container, `127.0.0.1:7497`) | Industry/category/subcategory sourcing script | Not probed this session (no live connection test attempted — read-only DB/filesystem research only) | — | If gateway is down at execution time, the sourcing script degrades to the fund-mandate path for ETFs and blocks single-name seeding until the gateway is reachable; no other path exists per D-06 |
| Free client ID for the sourcing script | IBKR connection | `_MAX_CLIENT_ID=50` in `ibkr.py`; existing scripts use client IDs 35/40/45 (`_GATEWAY_PROBE_CLIENT_ID=45` in `universe_expansion_stratified_sourcing.py`) | — | Pick an unused ID in the 35-50 range not already claimed by a concurrently-running script; check `docker exec ib-gateway` logs or `ps aux` for concurrent sessions first (CLAUDE.md's "Multiple concurrent backfills" gotcha) |

**Missing dependencies with no fallback:** none identified — IBKR Gateway reachability should be verified at execution time, not assumed from this research session.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest, project-wide (`.venv/bin/pytest`) |
| Config file | `pytest.ini` (root) — `--strict-markers`, `integration` marker registered |
| Quick run command | `.venv/bin/pytest tests/unit/test_classification_service.py -x` |
| Full suite command | `.venv/bin/pytest tests/unit/ -q` (GitHub CI's actual gate) plus `.venv/bin/pytest tests/integration/ -m integration` (local-only, DB-required, per Pitfall 2) |

### Phase Requirements → Test Map
(CONTEXT.md's D-01..D-11 serve as this phase's requirement IDs — no formal REQUIREMENTS.md IDs exist.)

| Decision | Behavior | Test Type | Automated Command | File Exists? |
|----------|----------|-----------|-------------------|-------------|
| D-01 (schema shape, append-only, RESTRICT, partial index, node-immutability) | Migration creates 3 tables with exact constraints; seed rejects a parent/level disagreement | unit (schema-shape assertions via a throwaway test DB or `psycopg`/`asyncpg` connection in `tests/integration/`) | `pytest tests/integration/test_classification_schema.py -m integration` | ❌ Wave 0 |
| D-02/D-03/D-04 (indicagent_v1 4 levels, GICS-name equity levels, non-equity level-2 splits) | Seed inserts correct node tree; codes embed parent | unit (pure-Python: load seed SQL's VALUES, assert tree shape) or integration (query live nodes) | `pytest tests/unit/test_classification_seed_shape.py -x` (if seed data is Python-importable) or integration | ❌ Wave 0 |
| D-05 (assignment depth follows instrument) | A sampled single name lands on level 4; a sampled broad ETF lands on level 1/2 | integration (live query) | `pytest tests/integration/test_instrument_classification_coverage.py -m integration -k depth` | ❌ Wave 0 |
| D-06 (source_ref distinguishes ibkr vs fund_mandate) | Every row's `source_ref` matches one of the two allowed values | integration | same file, `-k source_ref` | ❌ Wave 0 |
| D-07 (no history before build date) | Every `valid_from` >= build date | integration | same file, `-k valid_from` | ❌ Wave 0 |
| D-08 (ClassificationService as-of lookup, unclassified fallback) | Pure-Python unit tests, mirroring `test_vocabulary_service.py`'s no-DB style | unit | `pytest tests/unit/test_classification_service.py -x` | ❌ Wave 0 |
| D-09 (coverage enforced) | Migration RAISE guard (seed-time) + integration test (drift-time) | migration guard (manual apply) + integration | `pytest tests/integration/test_instrument_classification_coverage.py -m integration` | ❌ Wave 0 |
| D-10 (flat label readers migrated) | `settings.py`/`cache_manager.py` builder functions read `ClassificationService`, not `contract_details->>'sector'` | unit (existing builder-function tests, if any, updated; new assertions) | grep-check for the old field access pattern replaced with a positive assertion | Check `tests/unit/` for existing `test_settings*`/`test_cache_manager*` coverage — none found by filename scan this session, likely Wave 0 |
| D-11 (migration numbered, applied+committed together) | Migration 364 exists, applies cleanly, is committed with the phase | filesystem (`test_migration_number_uniqueness.py` already covers uniqueness) | `pytest tests/unit/test_migration_number_uniqueness.py -x` | ✅ exists already |

### Sampling Rate
- **Per task commit:** `pytest tests/unit/test_classification_service.py tests/unit/test_migration_number_uniqueness.py -x`
- **Per wave merge:** `pytest tests/unit/ -q` (must stay CI-clean) plus a manual `pytest tests/integration/test_instrument_classification_coverage.py -m integration` run against the live DB
- **Phase gate:** Full `tests/unit/ -q` green (real GitHub CI gate) + the integration coverage test passing locally before `/gsd:verify-work` — document explicitly in the phase's verification notes that the integration piece is not GitHub-CI-enforced (Pitfall 2)

### Wave 0 Gaps
- [ ] `tests/unit/test_classification_service.py` — pure-Python, no-DB, mirrors `test_vocabulary_service.py` (D-08)
- [ ] `tests/unit/_classification_fakes.py` — `FakeClassificationService`, mirrors `_vocabulary_fakes.py` (for any daemon-style consumer's own tests)
- [ ] `tests/integration/test_instrument_classification_coverage.py` — live-DB coverage + depth + source_ref + valid_from checks (D-05, D-06, D-07, D-09)
- [ ] `tests/integration/test_classification_schema.py` (or fold into the above) — schema shape assertions (D-01)
- [ ] No framework install needed — pytest + asyncpg + the `integration` marker are all already configured

## Security Domain

`security_enforcement` not found set to `false` in `.planning/config.json` (absent workflow key defaults enabled per instructions, though this phase's own config.json shows `workflow.nyquist_validation: true` and no explicit `security_enforcement` key at all — treating as enabled per the "absent = enabled" rule).

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | No | This phase adds no auth surface — internal schema + library service only |
| V3 Session Management | No | No session state introduced |
| V4 Access Control | No | No new access-control boundary; `instrument_classification` is read by the same trust boundary (in-process services) that already reads `instruments` |
| V5 Input Validation | Marginal | The IBKR-sourced `industry`/`category`/`subcategory` strings are external input (IBKR API response) mapped by a *human reviewer* into `indicagent_v1` codes (D-06) — the human-review step is itself the validation gate; the seed migration's `code`/`parent_code` values should still be constrained by a `CHECK` or FK (already implied by the design doc's `FOREIGN KEY (scheme, parent_code) REFERENCES classification_node(scheme, code)`) so a malformed code can never enter `instrument_classification` |
| V6 Cryptography | No | No secrets, no crypto operations |

### Known Threat Patterns for this stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| SQL injection via a dynamically-built onboarding classification value | Tampering | Parameterized asyncpg queries throughout (`$1`, `$2`, ...) — same pattern already used by every other write path in `instrument_onboarding.py`; never string-interpolate a symbol or code into SQL |
| A malformed/attacker-influenced IBKR category string silently becoming a new, uncontrolled taxonomy node | Tampering / Elevation of Privilege (of a sort — data-integrity) | D-06 already mandates human review before any IBKR-sourced candidate becomes a committed `indicagent_v1` node; the FK from `instrument_classification.code` to `classification_node.code` structurally prevents an unreviewed string from ever being written as a live assignment |

## Sources

### Primary (HIGH confidence)
- Live DB (`psql -U postgres -h localhost -d indicagent`) — active instrument counts, sector-label distribution, unlabeled symbol list, CVR `asset_class` namespace, `instrument_tags`/`concept_registry`/`contract_metadata` schemas, next-free migration number. All queries run and results captured in this research session, 2026-09-25.
- `src/config/vocabulary_service.py`, `src/core/vocabulary_access.py` — full file reads, the direct structural template for `ClassificationService`/`classification_access.py`.
- `src/config/instrument_onboarding.py` — full read of the docstring and the `metadata`/`metadata_skip_reason` pattern, the direct template for D-09's onboarding hook.
- `src/providers/ibkr.py` — read of `qualify_instrument()` and the `reqContractDetailsAsync` call sites; confirmed no `industry`/`category`/`subcategory` field is currently requested/stored.
- `production/migrations/363_sector_label_fixes.sql` — full read, the direct template for the seed-guard pattern and confirmation of migration numbering.
- `.github/workflows/ci.yml` — full read, confirms GitHub Actions runs `tests/unit/` only, no DB service, no `tests/integration/` step.
- `tests/integration/conftest.py`, `tests/integration/test_instrument_registry.py` — confirms the integration-suite-never-runs-in-CI fact and the `-m integration` DB-test precedent.
- `tests/unit/test_vocabulary_service.py`, `tests/unit/_vocabulary_fakes.py` — confirms the pure-Python no-DB unit-test template to reuse for `ClassificationService`.
- `.planning/phases/182-security-classification-hierarchy-todo-384/182-CONTEXT.md`, `docs/research/stratification-security-classification-hierarchy.md`, `.planning/todos/pending/384-...md`, `.planning/STATE.md` — full reads, the design and decision source of truth this research verifies against.

### Secondary (MEDIUM confidence)
- Wikipedia, "Global Industry Classification Standard" (fetched via WebFetch this session) — 11-sector/25-industry-group name list, cross-summed to confirm the count (25) matches the officially cited total from the MSCI methodology PDF search snippet. Not independently cross-checked against the primary MSCI PDF text (see Assumption A1).

### Tertiary (LOW confidence)
- None used without at least one corroborating live-verification or official-source cross-check in this research pass.

## Metadata

**Confidence breakdown:**
- Standard stack / patterns: HIGH — every pattern has 1-3 live, verified precedents in this exact codebase
- Schema design: HIGH — CONTEXT.md and the design doc fully lock this; verified against live schema of the nearest analogous tables
- GICS naming: MEDIUM — public secondary source (Wikipedia), not the primary MSCI PDF text itself
- CI/test enforcement mechanics: HIGH — directly read `.github/workflows/ci.yml` and `tests/integration/conftest.py`'s own documented admission
- IBKR sourcing coverage for the current 168-symbol universe: LOW — last empirically verified 2026-09-18, one week stale, and the 40-pilot-name overlap with that probe is unconfirmed (Assumption A2)

**Research date:** 2026-09-25
**Valid until:** 30 days for the schema/pattern findings (stable internal codebase); 7 days for the "168/168 IBKR coverage" and "40 unlabeled symbols" live-DB facts (this project's universe changes via onboarding scripts frequently — re-verify counts at plan/execution time if more than a few days elapse)
