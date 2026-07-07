# Controlled Vocabulary

**Created:** 2026-06-18
**Refreshed:** 2026-07-01
**Last Updated:** 2026-07-06 (Fable 5 design review pass - staging order inverted, divergence check redesigned, schema shape confirmed)
**Status:** Idea / Design — unscheduled (Phase 135 deferred indefinitely; original prerequisite now satisfied, ready to build whenever prioritized)
**Type:** Architecture pattern + design, Type 3 (static taxonomy) in the [Concept Governance Registries](concept-governance-registries.md) framework

**Review pass (2026-07-06, Fable 5)** - full design review against live schema (psql), CLAUDE.md
architecture state, and today's revisions of the two sibling docs this doc cross-references.
Core verdict: the problem is real, the 3-table shape is right, and the APR analogy holds - but
two things postdating the 2026-07-01 refresh invalidated the staging plan and one claimed
limitation in the enforcement design was simply wrong. Changes in this pass:

1. **Staging order inverted.** The entire Signal Ledger Architecture (signal_events,
   trade_frames, signal_outcome) was archived 2026-07-02 - one day after this doc's refresh.
   The old core build seeded the three now-dead SLA namespaces first and made "signal filter
   dropdowns" (a dashboard over an archived table) the first consumer, while deferring the
   live v3.0 namespaces that carry this doc's own headline correctness win (the dual-regime
   taxonomy collision). See revised Staging section.
2. **Divergence check redesigned.** The old design's "no divergence check possible for
   TEXT-backed namespaces" was false, and its ENUM check was two-way when the drift surface
   is three-way. See revised Source-of-truth section.
3. **Column-name correction:** the cross-sectional regime column is
   `market_regimes.regime_label`, not `market_regimes.regime` (verified via psql 2026-07-06;
   9 labels live, matching this doc's list). Fixed in place everywhere it appeared.
4. **Stale cross-reference fixed:** `platform-09-security-classification-hierarchy.md` does
   not exist; the live file is `platform-security-classification-hierarchy.md` (verified via
   `ls docs/ideas/` 2026-07-06). The `-09-` was a numbering scheme that never landed.
5. **`session_type` demoted:** it appears only in archived v2.x tables
   (`intelligence_features`, `ml_signal_training` - checked via information_schema
   2026-07-06). No live v3.0 column carries it; it has no seedable consumer today.
6. **Both prior retractions re-confirmed** (`parent_code` hierarchy, `concept_domain`
   namespace) - see the dated notes at each; neither needed reopening.

---

## Problem

The codebase has 10+ domain vocabularies with zero discoverable metadata. Two tiers exist today:

- **PG-ENUM-enforced** (shipped in Phase 134, migration `151_phase134_pg_enum_types.sql`): `signal_events.status` (`signal_status_type`), `trade_frames.entry_type` (`entry_type_type`), `signal_outcome` (`signal_outcome_type`). The DB enforces valid values at write time, but there is still no labels/descriptions/groupings layer — `WIN_OUTCOMES`, `STOP_OUTCOMES`, `TTL_OUTCOMES` remain Python frozensets, invisible to SQL and dashboard consumers. *(Status note added 2026-07-06, Fable 5: the SLA tables these ENUMs back were archived 2026-07-02 with no live consumer - the ENUM types and frozensets still exist, but these namespaces no longer motivate the build. See revised Staging.)*
- **Plain TEXT, unenforced** (confirmed live 2026-07-01 via `information_schema.columns`; re-verified 2026-07-06): `regime`/`tf`/`timeframe`/`tier`/`asset_class` appear as free-text columns across 50+ tables (`feature_vectors.regime`, `market_regimes.regime_label`, `feature_registry.tier`, `contract_metadata.asset_class`, etc.). This is broader than the original 2026-06-18 problem statement — v3.0's Feature Factory / AlphaEngine tables added many more untyped vocabulary columns than existed at Phase 134 time. Notably the regime vocabulary spans two independent systems (per-symbol HMM: 5 labels in `feature_vectors.regime`; cross-sectional: 9 labels in `market_regimes.regime_label` — see MEMORY.md "Dual Regime System") with no registry distinguishing which table uses which taxonomy. The same underlying timeframe vocabulary is also split across two column *names* (`tf` on ~26 tables, `timeframe` on ~14 - a namespace-keyed registry handles this cleanly precisely because it is keyed by vocabulary, not by column).

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

### Is three tables the minimal shape? (examined 2026-07-06, Fable 5 - yes, kept)

The obvious simplification is collapsing groups into a `groups TEXT[]` (or JSONB) column on
`controlled_vocabulary` itself. Steelmanned honestly: total data volume is ~100 rows across
all namespaces, written only in reviewed migrations, so the FK-integrity argument alone is
weak - a bad membership row would be caught in migration review either way. The array shape
would serve `codes()`/`label()`/`group_codes()` fine, and `WHERE 'wins' = ANY(groups)` works
in SQL.

It still loses on two of the doc's own stated consumers, so three tables stay:

1. **Groups carry their own metadata.** Dashboard filter panels render "Winning Outcomes"
   (group label, sort order, tooltip), not the raw token `wins`. An array of bare strings has
   nowhere to put that; the moment you move group metadata into a side structure you have
   reinvented `vocabulary_group`, just without integrity.
2. **The ML/SQL derivation consumer is a join.** `is_winning_outcome` as a derived column is
   one clean equi-join against `vocabulary_group_member`; against a `TEXT[]` it becomes
   `ANY()` array predicates that planner-hostile SQL generators (and analysts) get subtly
   wrong.

One thing deliberately *not* added to the schema: a `backing`/`source_column` column for the
drift check. The authority binding (which pg_enum type or which table.column a namespace
mirrors) is code-level registration in `VocabularyService`, same as APR keys are registered
in code - putting it in the table would imply the table governs its own verification, which
inverts the projection relationship.

### Source of truth stays per-namespace

*(Section rewritten 2026-07-06, Fable 5. The original text had two flaws: the ENUM divergence
check was two-way when the drift surface is three-way, and it claimed no divergence check is
possible for TEXT-backed namespaces - which is exactly backwards, since the TEXT namespaces
are where undetected drift silently biases consumers.)*

The boundary itself is right and is kept: enforcement authority stays per-namespace (PG ENUM
at write time, Python enum at compile time, or - for TEXT columns - the writing service's own
logic), and `controlled_vocabulary` is a read-only metadata projection. The registry never
becomes a runtime write gate; making it one would put a DB lookup on hot write paths and
invert the DAG (compute daemons consulting a registry service to validate output). A
projection that can drift is acceptable *only* because drift is made loud. Two mechanisms,
declared per namespace at registration time in `VocabularyService`, not in the schema:

- **ENUM-backed namespaces - three-way startup check, hard crash.** The original design
  compared registry rows against Python enum members only. That misses the third leg: a
  migration can `ALTER TYPE ... ADD VALUE` on the PG ENUM while the Python enum lags (or vice
  versa), and a registry-vs-Python check passes while the DB accepts values the registry has
  never heard of. The startup check must reconcile all three: registry rows, Python enum
  members, and the live catalog (`SELECT enumlabel FROM pg_enum JOIN pg_type ON ... WHERE
  typname = %s`). Any pairwise divergence is a hard crash at startup. Cost: one catalog query
  per namespace, once.

- **Column-backed namespaces - declared source column + periodic drift audit, loud alert.**
  Each TEXT-backed namespace registers its authoritative column (e.g. `regime_hmm` →
  `feature_vectors.regime`). A periodic check - housed in an existing auditor daemon, not a
  new service - runs `SELECT DISTINCT <col> FROM <table> WHERE <time_col> > now() - <window>`
  (bounded to recent chunks; distinct-scan over a full hypertable is not acceptable) and
  compares against registry codes. **The dangerous drift direction is data-superset:** a live
  value the registry doesn't know means every consumer filtering or grouping by registry
  codes silently drops those rows - the exact "never drop data that could contain signal"
  violation, and not hypothetical: a BIC re-run changing HMM K from 5 would change the
  `regime_hmm` label set overnight. Data-superset fires a loud alert (OTel counter + log at
  error). Registry-superset (a registered code no longer observed) is informational - that is
  what `is_deprecated` is for. This is deliberately an alert, not a crash: the defect lives
  in the *writer* or in a stale registry migration, and crashing read-side consumers of an
  otherwise-healthy pipeline punishes the wrong node.

Whether to also add PG ENUM types for the TEXT columns remains a separate decision (each is a
live hypertable column with production data; converting TEXT → ENUM on tables like
`feature_vectors` and `market_regimes` is a migration project of its own, out of scope here).
With the drift audit above, that conversion buys write-time rejection but is no longer needed
for drift *detection* - the registry is useful and honest without it.

---

## What Goes In

**In** — domain vocabulary that appears in dashboards, APIs, or analyst queries:

*(Table re-annotated 2026-07-06, Fable 5: added liveness column - the SLA archiving of
2026-07-02 moved three namespaces from "seed first" to "seed if revived", and `session_type`
turned out to have no live column at all.)*

| Namespace | Backing | Liveness (2026-07-06) | Groups |
|---|---|---|---|
| `regime_hmm` | TEXT, `feature_vectors.regime` | **live** (v3.0 corpus) | 5 labels sorted by emission mean (per MEMORY.md dual regime system) |
| `regime_cross_sectional` | TEXT, `market_regimes.regime_label` | **live** (v3.0, ic_engine stratification) | 9 labels: `{low/mid/high}_{bull/neutral/bear}` |
| `tier` | TEXT, `feature_registry.tier` | **live** (2 values today: `0_atomic`, `2_theory`) | (for dashboard grouping) |
| `timeframe` | TEXT, `feature_vectors.tf` and ~40 other tables (as `tf` or `timeframe`) | **live** | (for display labels) |
| `asset_class` | TEXT, `contract_metadata.asset_class` | **live** | `equity`, `futures`, `fx` |
| `signal_outcome` | `signal_outcome_type` (PG ENUM) | archived (SLA, 2026-07-02) | `wins`, `losses`, `timeouts` |
| `entry_type` | `entry_type_type` (PG ENUM) | archived; plausibly revived by Phase 142B frame simulation | (none yet) |
| `signal_status` | `signal_status_type` (PG ENUM) | archived (SLA, 2026-07-02) | `pending`/`active` (live), `expired`/`regime_suppressed` (terminal) |
| `session_type` | none live - only archived v2.x tables (`intelligence_features`, `ml_signal_training`) carry it | archived | (do not seed; `normalize_session_type()` in `service_utils.py` is the only live vocabulary holder) |

**Out** — internal infrastructure codes users never see: `CircuitState`, `DataSource`, `TransitionType`.

Concept Registry's `domain` column is deliberately **not** a namespace here — it's the `CHECK` list on `concept_registry.domain`, enforced with a plain `CHECK` constraint, same pattern as its `status` column. An earlier draft specced a `concept_domain` namespace + runtime `VocabularyService` dependency for this; retracted after review found it coupled two independently-deferred systems to solve a problem a `CHECK` constraint already solves (see [Concept Registry](platform-unified-concept-registry.md)). Concept Registry and Controlled Vocabulary are unrelated sibling designs with no shared build gate. *(Retraction re-confirmed 2026-07-06, Fable 5: the Concept Registry doc went through four review passes today and kept the plain-CHECK approach - its live `domain` CHECK was actually cut down to two values (`feature`, `ensemble_strategy`), making a runtime vocabulary service for it even less warranted than when the retraction was written. The stale "7 values today" count in this paragraph was dropped rather than updated; that doc owns its own count.)*

---

## What This Replaces / Extends

The `WIN_OUTCOMES`, `STOP_OUTCOMES`, `TTL_OUTCOMES` frozensets in `signal_outcome.py` become seeded rows in `vocabulary_group_member` *(2026-07-06, Fable 5: now conditional on SLA revival - see Staging; the pattern is unchanged, the timing moved)*. They stay in Python for in-process use (fast, no DB call) but the DB projection makes them:

- Queryable from SQL: `SELECT code FROM vocabulary_group_member WHERE namespace='signal_outcome' AND group_name='wins'`
- Reachable from dashboard filter panels without hardcoding
- Usable in ML feature derivation (`is_winning_outcome` as a clean derived column)
- Self-documenting in API responses

For `regime_hmm` vs `regime_cross_sectional`, the registry also solves a real correctness risk: today nothing prevents a consumer from reading `feature_vectors.regime` (5 HMM labels) and treating it as if it were a `market_regimes.regime_label` value (9 cross-sectional labels) — two independent taxonomies with no machine-readable marker distinguishing them. A `namespace` column makes the distinction explicit and queryable. *(2026-07-06, Fable 5: this is the build's primary correctness win, which is why the revised Staging seeds these namespaces in the core build rather than deferring them.)*

---

## Staging

*(Rewritten 2026-07-06, Fable 5. The previous staging seeded the three PG-ENUM SLA namespaces
first - "lowest risk, DB already enforces these values" - with signal filter dropdowns as the
first consumer. The SLA was archived 2026-07-02: those tables have no live consumer, so that
plan's core build would have seeded three dead vocabularies and shipped a dropdown over an
archived table, while deferring the live namespaces that carry the doc's stated correctness
win. "Lowest risk" was optimizing for enforcement comfort over consumer reality. Inverted.)*

**Core infrastructure (one build):**
- Migration: create 3 tables
- Seed the **live** namespaces: `regime_hmm`, `regime_cross_sectional`, `timeframe`,
  `asset_class`, `tier` - labels, descriptions, sort order
- `VocabularyService` with the two divergence mechanisms from the Source-of-truth section:
  three-way startup check for any ENUM-backed namespace, declared-column drift audit for
  column-backed ones
- Wire the drift audit into an existing auditor daemon; alert on data-superset divergence
- `/api/vocabulary/{namespace}` endpoint
- First dashboard consumer: regime filter/labeling on any live regime-consuming panel
  (replaces hardcoded label lists and, critically, makes the 5-vs-9 taxonomy distinction
  machine-readable for the first time)

**On demand later:**
- `signal_outcome`, `entry_type`, `signal_status` - when/if an SLA-adjacent surface revives
  (Phase 142B frame simulation is the plausible path for `entry_type`); seeding archived
  vocabularies before then is inventory nobody consumes
- Taxonomy groups beyond the seeds - when the first SQL query needs `WHERE group_name = ...`
- ML feature derivation: join `vocabulary_group_member` for `is_winning_outcome` etc.
- `session_type` - only if a live v3.0 column ever carries it

**On the "do not seed until there is a concrete consumer" rule** *(clarified 2026-07-06,
Fable 5)*: the rule stays, but "consumer" must not be read as "dashboard widget." The drift
audit is itself a first-class consumer - a namespace whose live label set is being verified
against the registry is doing correctness work from day one, dashboard or not. Under the old
reading, the TEXT-backed namespaces that most need the registry (the dual-regime collision)
could have waited indefinitely behind UI priorities. The infrastructure is built once;
namespaces are added reactively - but "a live column whose taxonomy can silently drift or be
confused with a sibling" already is the concrete consumer.

---

## APR Analogy

| APR | Controlled Vocabulary |
|---|---|
| `config_state` table | `controlled_vocabulary` table |
| `threshold.*`, `weights.*` namespaces | `signal_outcome`, `regime_hmm` namespaces |
| `ConfigService.get("threshold.x", 1.0)` | `VocabularyService.group_codes("signal_outcome", "wins")` |
| ML can update values at runtime | Metadata updated only via migration |
| Any module registers a parameter | Any module seeds a namespace |
| Startup schema divergence = hard error (all namespaces) | ENUM namespaces: three-way startup check, hard error. Column-backed namespaces: periodic drift audit, loud alert *(row updated 2026-07-06, Fable 5 - was "PG-ENUM namespaces only")* |

---

## Out of Scope: Hierarchical Instrument Classification

**(2026-07-04)** An earlier revision of this doc proposed adding a self-referencing
`parent_code` here to support GICS-style individual-equity classification. Retracted after a
full design pass: classification is instrument-scoped reference data whose load-bearing half
is *membership* (effective-dated, exclusive-per-scheme assignment of securities to nodes), a
concern this platform-wide, migration-seeded, instrument-agnostic metadata registry is the
wrong shape for. Design lives at
`docs/ideas/platform-security-classification-hierarchy.md` *(filename corrected 2026-07-06,
Fable 5 - the previous `platform-09-` prefix never existed on disk; that doc was itself
reviewed and revised 2026-07-06 and the decoupling conclusion still holds)*; the two systems
remain fully decoupled, with no shared build gate.

---

## Dependency

Originally gated on Phase 134 (converts `signal_outcome`, `entry_type`, `signal_status` columns to PostgreSQL ENUM types) — **that shipped 2026-06-18**. *(2026-07-06, Fable 5: with the SLA archived 2026-07-02 and the staging inverted, Phase 134 is no longer on the critical path at all - the core build's namespaces are all TEXT-backed live v3.0 columns with zero prerequisites. This design has no build dependency today; it is gated purely on prioritization.)* The TEXT-backed namespaces get metadata/labels plus the drift audit, but not DB-level write enforcement unless a separate TEXT→ENUM migration is done for those columns.

---

## Design gate check (2026-07-06, Fable 5)

CLAUDE.md's four questions, applied to the revised design:

1. **Survives 10x volume?** Trivially. ~100 rows, migration-time writes only, cached at
   startup, zero hot-path DB calls. The only volume-sensitive piece is the drift audit's
   distinct-scan, which is bounded to recent hypertable chunks by design.
2. **What fails silently or introduces hidden bias?** Pre-revision: two things - registry
   drift on TEXT namespaces (the original design declared checking impossible) and the
   ENUM check's blind third leg (pg_enum vs Python enum skew). Both now have named,
   direction-aware detection with the dangerous direction (data-superset: consumers silently
   dropping rows carrying unregistered codes) called out explicitly. Residual accepted risk:
   the drift audit is periodic, so a new label can exist for up to one audit interval before
   alerting - acceptable because the registry never gates writes, so no data is lost in the
   window, only unlabeled.
3. **Does the DAG still hold?** Yes. Read-only projection, no new writers, no new service
   (drift audit rides an existing auditor), no compute daemon consults it to validate its own
   output, and the retracted `concept_domain` coupling stays retracted. The one DAG trap -
   making the registry a runtime write gate - is now explicitly named and rejected in the
   Source-of-truth section.
4. **What manual step does this eliminate?** Every dashboard/API consumer hand-maintaining
   vocabulary lists; every analyst manually remembering which of two regime taxonomies a
   `regime`-shaped column carries; manual eyeballing for label drift after model re-runs
   (BIC K changes) - the audit automates that check.

Verdict: build-ready as revised. The design earns its place; nothing further to cut - the
one candidate for deletion (`vocabulary_group` as a separate table) was steelmanned and kept
on consumer-driven grounds, and the two previously retracted extensions remain out.
