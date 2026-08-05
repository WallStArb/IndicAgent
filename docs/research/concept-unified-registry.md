# Unified Concept Registry

**Status**: MVP BUILT 2026-07-13 (todo 058, migrations 231/232): `concept_registry`/`concept_gate`/`concept_transition_log`/`concept_annotation` live, `domain='ensemble_strategy'` seeded (5 concepts), `ConceptRegistryService` (`src/intelligence/concept_registry_service.py`) wired as invariant-1 status-flipper from `ops_ensemble_weight_compare.py`. `domain='feature'` NOT yet migrated (todo 118, promoted to ROADMAP Phase 170 2026-08-04); reference-architecture tables remain unbuilt by design. What is live are the sibling/precursor registries, each still a separate system: APR (425 params), `feature_registry` (**249 rows** as of 2026-08-04, up from the 61-row Phase 140.5 seed — the count in this line rots, verify live before citing), tag vocabulary (71 tags / 410 assignments). `shadow_registry` (36 rows) exists but is legacy and was never evaluated - not "live" in any operational sense, and a prior version of this line counted it as such. **Retirement direction confirmed 2026-08-04**: `feature_registry` is to be migrated ASAP once the real remaining gate clears (see 2026-08-04 entry below) — not a someday-maybe, a decided target.

**Scope**: Cross-tier lifecycle governance system that unifies the feature tier (Feature Registry) and intelligence tier (alpha patterns, HMM variants, ensemble strategies, regime models) under one schema, one service (`ConceptRegistryService`), and a single promotion/demotion discipline.
**Created**: 2026-06-28
**Informed by**: `docs/research/fable-2026-07-01-v3-architecture-review.md` (Fable 5) — Domains table gate-metric corrections and MVP build-trigger reassessment (2026-07-02) trace back to that review's ensemble-weighting and HMM-variant findings.
**Type**: Architecture pattern + design

**Revision history** (append-only, oldest first; see each entry for what changed and why, never rewritten, only appended to):

- **2026-06-28 (original design).**
- **2026-07-01 (critical re-architecture).** Recipe-card framing, concepts-vs-facts boundary, gate-vs-annotation discipline rule. Full spec re-merged into this doc after a same-day split/re-unify (kept as one unified research doc, not an index + satellite file). Renamed from "Metadata Governance Registry System" — "metadata" undersold what this actually is: reference (identity/knowledge) *and* lifecycle (active governance — promote, demote, prove), not passive descriptive data.
- **2026-07-02.** Domains table's `ensemble_strategy`/`hmm_variant` gate metrics corrected against concrete decisions made the same session (Phase 142B.1 insertion, todo 026's Decision Gate) — see §Domains footnotes. MVP build-trigger domain #2 reassessed from an assumed `alpha_pattern` default to `ensemble_strategy` as the more concrete and lower-risk near-term candidate (item 20). The IOHMM and factor-augmented HMM variants' real dependency on Phase 144's `regime_group` signal modules identified and fixed at the source doc. Also dropped this doc's own stray references to the regime-stratification doc's old, now-retired `P1`-`P8` numbering (see that doc's 2026-07-02 update — those codes looked like priority tiers but weren't, and collided with `todo 026`'s legitimate, unrelated `P4a`/`P4b` priority codes).
- **2026-07-06 (rigor pass, Fable 5).** Added Renaissance-mandate safeguards: Invariant 7 (initial promotion minimum observation floors, p-value alone is insufficient), per-domain minimum observation floors in Domains table, "What Jim Simons Would Demand" section making eight non-negotiable requirements explicit. Verification-and-rigor pass against live code/DB and the five sibling registry docs: status line corrected (no `concept_*` tables exist; the prior "four registries live" counted separate sibling systems and treated the never-evaluated `shadow_registry` as live); Invariant 2's APR key corrected to the real `alpha.decay.recovery_min_observations`; Invariant 8 (implementation-version binding of evidence) and Invariant 9 (compare-and-swap status transitions; the live `FeatureRegistryService` fails this today) added; `domain` CHECK cut to domains with real candidates at build time, applying the doc's own confluence rule uniformly; Domains-table floors given provenance tags and an effective-N-under-autocorrelation requirement; `regime_scope` pre-registration rule added (per-stratum promotion without multiplicity correction is selection bias); gate-shape heterogeneity note added (confluence and ensemble_strategy gates are not scalar); tag-calibrator boundary stated (measured tag assignments are facts, not a Concept Registry domain); stale todo-015 reference updated (superseded into IntegrityMonitor / Phase 143); ten file references repointed after the docs/ideas renaming sweep; APR live count refreshed (348 to 425).
- **2026-07-06 (domain-vetting pass, Fable 5).** Scope correction per user pushback: the rigor pass conflated "should this domain be seeded into the live `domain` CHECK" (correctly cut to `feature`/`ensemble_strategy` only, unchanged) with "should this domain's gate shape be fully vetted so there's zero design lag at build time" (the user wants yes for four more domains). Added a Domain Vetting section fully specifying `hmm_variant`, `ic_method`, `regime_model`, and `confluence` — real trigger status (verified against `services/ic_engine.py`, todo 026, and the two source docs, not assumed), gate shape, effective-N floor, and schema fit for each, none seeded into the CHECK; found `ic_method` has no real candidate today (its founding description conflated Spearman and rank-IC as two methods when they are the same computation, and misfiled HAC's variance-correction as a competing correlation method) and said so rather than inventing one. Added `concept_gate_stack` (Governance Layer, optional per-domain extension) resolving the "one schema, really?" question properly: shared discipline (status enum, transition log, invariants), not forced identical gate columns — `confluence`'s six-gate ordered stack and `regime_model`'s three-stage cascade both use it, `feature`/`hmm_variant`/`ensemble_strategy` never touch it. Fully specced both `regime_model` row-grain options (per-dimension vs. per-(dimension, regime_group)) per the user's explicit ask, recommending but not forcing the v3.15 decision. Retired `alpha_pattern` outright (not "reserved") — its scope was already fully absorbed by `feature_interaction`/`confluence`/`feature`-grain analog predictors with zero residual, the same unearned-scaffolding pattern this pass cut elsewhere; resolved "the alpha decay thought" by generalizing decay/demotion (`decay_ratio`/`decay_floor`, CUSUM via IntegrityMonitor) as a property every domain's lifecycle already carries, not a reason to invent a domain whose purpose was "things that decay."
- **2026-07-06 (adversarial stress-test, Fable 5).** Stress-test against the user's restated problem ("catalog multiple intelligence layers, activate/deactivate, promotion/demotion/decay, plus metadata about the logic/computational parameters"), explicitly trying to break the design rather than defend it. Audited the full codebase with a strict liveness bar (row count plus recency, systemd service state, explicit ARCHIVED markers, not code/table existence) after an earlier draft of this audit wrongly treated two dead v2.x mechanisms (`llm_model_scores`, `setup_performance`) as live; corrected against actual data (0 rows, disabled services) once checked properly. Found the live-domain count unchanged from the prior pass (`feature`, `ensemble_strategy` live; `hmm_variant`/`regime_model`/`confluence`/`ic_method` vetted, not yet real) but surfaced three real precedents worth learning from: `src/core/ml/registry.py`'s dead `ModelRegistry` (parameters referenced via MLflow, never duplicated into the lifecycle row, adopted as `metadata.apr_namespace`, refining Invariant 8 with a concrete trigger via `config_history` version-watching); `signal_lineage` + `_graduation_loop` (a live-infrastructure, zero-current-activity event ledger, architecturally consistent with APR's own `config_state`/`config_history` hybrid, adopted the lesson that append-only evidence tables should be TimescaleDB hypertables, declared this for `concept_transition_log`, without abolishing the materialized status column); and the abandoned v2.x I1-I7 tier's twelve-plus bespoke tables with no shared schema or discipline, wiped rather than migrated forward per `docs/operations/operations-database.md`, direct evidence against the "fully separate per-tier storage, protocol only" alternative, since that is what this codebase already tried and already abandoned. Evaluated and rejected: full event-sourcing (departs from APR's own proven hybrid precedent), a graph database engine (unjustified new infrastructure; Postgres recursive CTEs over the existing edge tables already serve the graph-shaped knowledge layer), full per-tier separation (the v2.x sprawl is the cautionary tale), and merging Concept Registry into APR (different questions: APR governs which value is best for a setting whose existence is settled, Concept Registry governs whether a candidate deserves to exist at all). Verdict: the core design (`concept_registry`/`concept_gate`/`concept_gate_stack`) survives the stress-test; two concrete refinements adopted, no wholesale rearchitecture, and nothing added to the live `domain` CHECK or Domains table since no newly-inventoried mechanism has real candidates.
- **2026-07-07 (structural pass, Claude).** No content changes - reformatted the giant single-paragraph revision history above into this dated list and renamed the ambiguous "second/third/fourth pass" labels to descriptive ones (rigor / domain-vetting / adversarial-stress-test) matching the entries above. Also added a table of contents; removed same-day per user feedback - this is a working research doc consumed by grep and targeted reads, not a reference manual read linearly, and a TOC's anchors go stale every time a header changes, which is often here. Not worth the upkeep for this doc's actual use.
- **2026-07-07 (rewrite pass, Fable 5).** Genuine content rewrite per explicit user request ("apply the knowledge... it should have been rewritten") - not another append, a consolidation separating the live spec from the discovery narrative that four passes had interleaved into it. No facts, dates, or conclusions changed. Rewrote all nine promotion/demotion invariants as clean single-paragraph rules (each previously carried an inline "originally X, corrected on date Y because Z" narrative arc; that provenance is preserved here in this revision history and in the pre-existing changelog entries above, not lost, just no longer interleaved into the live rule text); consolidated the `alpha_pattern` retirement argument to one canonical explanation (§Concept Registry Type 2) with short pointers from the Domains table, Cross-Tier Unification, Registry Taxonomy, and Invariant 5, removing three near-duplicate restatements; consolidated the `metadata.apr_namespace` convention to one canonical explanation (§concept_registry) with pointers from Invariant 8 and the Architecture Stress-Test, removing one duplicate; trimmed the Domains table's `hmm_variant`/`ensemble_strategy` footnotes to short pointers into Domain Vetting and the Minimal Viable Version section respectively, which already carried the same argument in full; moved Architecture Stress-Test from directly after the intro (where it referenced tables and invariants not yet introduced) to after the full design and Domain Vetting are presented, and compressed its narrative (the specific "an earlier draft wrongly treated two mechanisms as live" correction anecdote is preserved in the 2026-07-06 adversarial-stress-test entry above, not repeated in the live section) while keeping its liveness inventory and all five architecture alternatives with verdicts intact.
- **2026-08-04 (architecture review + retirement confirmation, Claude).** User confirmed `feature_registry` is to be retired into this system ASAP, framed explicitly through Musk's 5-step mandate (question the requirement → delete → simplify → accelerate → automate). Corrected a mid-session error: todo 118 (this migration) was believed gated behind "todo 117," but 117 is a different, already-completed thing (`feature_registry`'s own operator-override CLI actuator, closed 2026-07-19, unrelated to this migration's own proof requirement) — re-checking live state found the real remaining gate is that `ConceptRegistryService.record_comparison_outcome` (the CAS write path this migration would route `ic_engine`/`ensemble_trainer` through) has **never executed against real data**: `alpha_ensemble_ic` has 0 rows as of this date, still pending the in-flight corpus rebuild (H-1/M-B notes, todo 118). Applying Musk's ordering: delete (retire `feature_registry`, no further investment in it — its dead, never-written `last_ic_value`/`last_ic_sharpe`/`last_ic_n`/`last_eval_at` rollup columns don't get fixed in place, they disappear with the table) and simplify (close two concrete gaps as part of one migration pass, not as separate follow-on phases) come before accelerate/automate (don't route the live feature-lifecycle path through unrehearsed machinery that has already caught two undetected bugs — a migration-drift bug and a runtime crash — in review). Two gaps found and added to todo 118 as L-5/L-6: `concept_gate` has no equivalent of `feature_registry.consecutive_shadow_passes`/`observations_since_demotion` (Phase 143's LIFECYCLE-01 shadow-recovery mechanics would silently regress on migration without a schema addition first); `ConceptRegistryService` documents FDR enforcement as the caller's responsibility rather than enforcing `fdr_required` itself (safe with one caller today, becomes a real risk once this migration makes `ic_engine` and `ensemble_trainer` both callers of `record_comparison_outcome`). Separately found, independent of this registry question but sharing its design lesson: `services/ic_engine.py`'s fingerprint invalidation (`_FINGERPRINT_INVALIDATE_DELETE_SQL`) hard-deletes `feature_ic_scores` rows with no archive whenever `code_content_key`/`apr_snapshot_key`/`upstream_watermark` changes for an already-computed `training_window_end` — filed as todo 252. Recommended reusing that same fingerprint tuple as the provenance/version key for `concept_transition_log` rows this migration writes, rather than inventing two independently-versioned schemes for the same underlying "what changed" question. Migration formalized as **ROADMAP Phase 170** (stub, `Plans: 0`, same `alpha_ensemble_ic` dependency, closes the narrative arc this doc's own history left open since Phase 160 deliberately scoped `domain='feature'` out of the MVP). Todo 118 raised P2→P1 in `PRIORITIES.md` — "ASAP" reframed as "execute the moment the data dependency clears," not "skip the rehearsal": untested-in-anger machinery deciding what's live in 249 real features' governance is exactly the silent-wrong-answer risk this project's own principles rank above a loud crash.

---

## Renaissance Framing

Renaissance Technologies runs every model variant, signal idea, and methodology through a formal research pipeline. Nothing lives in a notebook nobody reads. Nothing disappears into a deleted branch. Every hypothesis either earns its way to live through accumulated statistical proof or gets formally retired with the evidence attached.

This is not bureaucracy - it is how you avoid re-discovering dead ends. When someone asks ten years from now "why don't we use diagonal covariance HMM?" the answer should be in the database: `demotion triggered 2026-09-14, held-out LL = -847.3 vs full covariance -821.1, n = 1200 bars`. Not in a Slack thread. Not in someone's memory. Queryable. Permanent.

But evidence alone is not enough. The other half of institutional knowledge is understanding - why something works, what breaks it, what we've learned since deployment, what depends on what. A concept whose thesis lives only in someone's head evaporates when they're gone. A concept whose failure modes are undocumented gets re-discovered the hard way.

The registries in this system capture both halves. The **governance layer** answers: *Is this valid? What state is it in? What happened?* The **knowledge layer** answers: *Why does it work? What breaks it? What have we learned? What depends on it?*

### What Jim Simons Would Demand

Renaissance principles demand specific safeguards against the most common failure modes in quantitative research. This system implements eight non-negotiable requirements:

| Requirement | Implementation | Status |
|---|---|---|
| **No fluke promotions** | Minimum observation floors per domain (Invariant 7); p<0.05 alone is insufficient | ✅ Added |
| **Every decision queryable** | Full audit trail in `concept_transition_log`; queryable 10 years later | ✅ Covered |
| **No silent decay** | CUSUM change detection (`measurement-governance-monitor.md`); continuous re-evaluation | ✅ Covered |
| **Shadow mode before live** | Mandatory shadow period for AI-sourced concepts (Invariant 6) | ✅ Covered |
| **Regime-aware evaluation** | `concept_regime_ic` table; regime-specific IC profiles; conditional weighting | ✅ Covered |
| **False discovery control** | FDR correction for multi-candidate domains (`feature`, `feature_interaction`); `confluence`'s gate 2 applies the same batch-level BH-FDR at its own grain | ✅ Covered |
| **Redundancy as evidence** | `concept_correlation` table; correlation-based diversity guards; `redundancy_group` displacement | ✅ Covered |
| **Concepts vs facts boundary** | Recipes governed in `concept_registry`; outputs recomputed in fact tables | ✅ Covered |

**The Renaissance question this answers:** "When someone asks ten years from now 'why don't we use this feature/strategy/model anymore?' the answer is in the database: demotion triggered 2026-XX-XX, held-out LL = -847.3, p < 0.01, n = 1200 bars. Not in Slack. Not in memory. Queryable."

---

## What This Is: A Recipe Card File

Concept Registry is where the platform's actual secret sauce lives - not the infrastructure (IC engine, corpus pipeline, HMM training), which is methodology anyone could rebuild, but the specific, proven results of running that methodology: which feature interactions out of thousands of candidates actually carry IC, which HMM configuration was proven better and why, which ensemble weights survived out-of-sample. One row per recipe: what it is, whether it currently earns its keep, the formula/parameters that make it reproducible, and enough history that turning a deprecated one back on is a status flip, not archaeology.

**Concepts vs. facts - what belongs here and what doesn't.** A recipe is governed here; the output of using the recipe is not. `confluence` concepts (the joint-condition logic deciding when to fire) are governed rows with a lifecycle; `alpha_events` (the actual emitted signals at runtime) are a fact table with its own canonical writer (`docs/foundation/canonical-truth-registry.md`), recomputed/emitted fresh every time, never itself a lifecycle-governed row. Same for features: the *definition* of `momentum_z_fast` is a concept; a bar's actual `momentum_z_fast` value in `feature_vectors` is a fact. Concept Registry stores recipes, not their output.

**Not a secrecy mechanism today, but worth being clear about what's actually sensitive if that ever matters.** The system needs no access control right now - this is a solo project, there's no competing desk and no walkaway-employee risk. But if it's ever worth naming: the sensitive part isn't the methodology (walk-forward validation, FDR correction, HMM regime detection are all standard technique), it's the narrow, expensive-to-discover, cheap-to-copy result - which specific interactions/parameters/weights are `active` and their `thesis` annotations. `concept_registry` carries an unused, nullable `sensitivity` column for exactly this reason: free to add now, costs nothing while unused, saves a migration if a future access-control layer ever needs to filter by it.

---

## Cross-Tier Unification

**What makes Unified Concept Registry unique:** it generalizes lifecycle governance across BOTH the feature tier and the intelligence tier - one system, instead of separate bespoke registries for each tier.

### Before: Separate tier-specific governance

| Tier | Existing Registry | What it governed | Status |
|------|-------------------|------------------|--------|
| **Feature tier** | `feature_registry` | 61 intelligence vector features, IC Sharpe + FDR gate | Live, will migrate into Unified Concept Registry as `domain='feature'` |
| **Intelligence tier** | Shadow Registry | 36 I1-I7 plugins/swarm agents, EV[R] bootstrap CI gate | Legacy, archived v2.x system; not migrating - no live v3.0 domain |

### After: One unified system

```
Unified Concept Registry
├── feature tier domain
│   └── domain='feature' - 61 current features, eventually feature_interaction survivors
│   └── Gate: IC Sharpe + FDR, walk-forward, 20,000-bar floor
│
└── intelligence tier domains
    ├── domain='ensemble_strategy' - weighting method variants (E1-E4)
    ├── domain='hmm_variant' - HMM architecture variants (covariance, obs vector, K)
    ├── domain='ic_method' - competing computations of the same predictive edge (no real candidate yet, see Domain Vetting)
    ├── domain='regime_model' - stratification-dimension variants (per-symbol HMM, cross-sectional, percentile-rank, and future axes)
    └── domain='confluence' - validated joint conditions over primitives/analog neighborhoods
```

Of these, only `feature` (61 live rows to migrate) and `ensemble_strategy` (E1-E4, todo 058) have real candidates as of 2026-07-06 - that stays the seeding bar for the live `domain` CHECK below. `hmm_variant`, `ic_method`, `regime_model`, and `confluence` are fully vetted (gate shape, eval method, effective-N floor, schema fit) in the Domain Vetting section below, so there is zero design lag whenever each earns real candidates - vetting a domain's design and seeding it into the live schema are separate questions; the first happens as soon as a domain is worth designing, the second only when it has rows to hold. `alpha_pattern` is retired, not merely deferred - see the retirement note under Domains.

**Cross-tier discipline:** same tables, same service, same promotion/demotion engine, same audit trail - whether you're governing a momentum feature or an HMM variant. The tier doesn't matter; the evidence discipline does.

### Why this matters

Without unification, every new research domain needs a new bespoke table:
- `feature_registry` for features
- `hmm_variant_registry` for HMM architectures (would need to be built)
- `ensemble_strategy_registry` for weighting methods (would need to be built)
- ...one per domain forever

With unification, every new domain is just another `domain` value in the same schema:
- Seed the domain row in the `Domains` table (this doc §Domains)
- Define its gate metric and eval method
- Start promoting candidates

The architecture scales; the governance discipline stays consistent.

---

## Registry Taxonomy

**"Unified Concept Registry" is the specific system this document describes** - a cross-tier lifecycle governance system that unifies feature and intelligence tiers under one schema. The broader governance *family* (APR, vocabularies, legacy registries) is context; Unified Concept Registry is the subject.

```
Unified Concept Registry (this doc)
├── Type 1: APR (Adaptive Parameter Registry) - context, separate infrastructure
│   └── Tables: config_state, config_history, config_schema
│   └── Purpose: value-mutable runtime tuning, no lifecycle states
│   └── Full spec: docs/foundation/adaptive-parameter-registry.md
│
├── Type 2: Lifecycle registries - the unified piece
│   ├── Shadow Registry (legacy, separate tables: shadow_registry, shadow_transition_log)
│   │   └── Governs: archived v2.x I1-I7 plugin/swarm system; no live systemd consumer
│   │   └── Status: legacy, not migrating - no v3.0 domain to absorb into
│   │
│   └── Unified Concept Registry (the subject of this doc)
│       └── Tables: concept_registry, concept_gate, concept_transition_log, concept_annotation...
│       └── Purpose: evidence-gated lifecycle governance for ALL research domains
│       └── Key: ONE schema, ONE service (ConceptRegistryService), MANY domains (partitioned by `domain` column)
│       └── Domains: feature, ensemble_strategy, hmm_variant, ic_method, regime_model, confluence (alpha_pattern retired - merged, no residual scope, see Domains)
│       └── Status: design complete; MVP build trigger fired 2026-07-04 (todo 058), build not started
│
└── Type 3: Vocabulary registries (static taxonomy) - context, separate infrastructure
    ├── Tag Vocabulary (live, tables: tag_vocabulary, instrument_tags, instrument_annotations)
    ├── Controlled Vocabulary (to build, design at docs/research/concept-controlled-vocabulary.md)
    └── Security Classification (future, design at docs/research/stratification-security-classification-hierarchy.md)
```

**What's actually unified:** Unified Concept Registry (Type 2) is the single-schema system that governs multiple research domains across BOTH feature and intelligence tiers. APR and the vocabularies are related by governance philosophy only - they have separate tables, separate services, and separate purposes.

**Three types, distinguished by what drives state changes:**

**Type 1 - Parameter** (value-mutable): entries have tunable values ML can update at runtime. Gate is a validation range.
- **APR** - 425 numeric/behavioral params across 13 namespaces (live count 2026-07-06; a prior "348" here had gone stale). Separate infrastructure (`config_state`, `config_history`, `config_schema`). Full spec: `docs/foundation/adaptive-parameter-registry.md`.

**Type 2 - Lifecycle** (evidence-gated): entries move through `candidate → shadow_only → active → deprecated` based on statistical evidence.
- **Shadow Registry** - 36 components (`i7_plugin`, `swarm_agent`), EV[R] bootstrap CI gated. **Legacy** - no systemd unit runs `shadow_auditor`/`shadow_validator`/`alpha_swarm`, `last_eval_at` is NULL on all 36 rows, and it governs the v2.x I1-I7 plugin/swarm system that CLAUDE.md documents as archived under v3.0 (Feature Factory replaces I1-I4; I5-I7 archived outright). Separate tables (`shadow_registry`, `shadow_transition_log`). Not a migration target - there is no live plugin/swarm domain for Concept Registry to absorb it into. Revisit only if I7 plugins or swarm agents come back into active use.
- **Concept Registry** - generalized lifecycle governance for all research domains _(to build; absorbs Feature Registry only, for now)_. **This is the unified piece** - one schema, one service (`ConceptRegistryService`), many domains partitioned by the `domain` column.

**Type 3 - Vocabulary** (static taxonomy): codes/labels with metadata, no lifecycle states. Separate infrastructure per registry.
- **Tag Vocabulary** - 6 categories, 71 tags, 410 instrument assignments (live-verified 2026-07-04; the "301 tags" figure previously stated here matched neither table). Tables: `tag_vocabulary`, `instrument_tags`, `instrument_annotations`. **Boundary with the calibrator (2026-07-06):** `docs/research/stratification-instrument-tag-calibrator.md` makes tag *assignments* evidence-gated (p-value, sample_n, expiry, half-life decay), which superficially looks like Type 2 lifecycle. It is not: per the concepts-vs-facts boundary above, a measured `(symbol, tag)` beta is a fact, recomputed each calibration run - the same resolution as `ensemble_strategy`'s per-stratum champions (F2). The *measurement contracts* on `tag_vocabulary` (`factor_series`, `measurement_type`, thresholds) are the recipe half and stay Type 3 vocabulary rows. Tags do not become a Concept Registry domain; the two designs share discipline, not tables.
- **Controlled Vocabulary** - domain enums _(to build; design at `docs/research/concept-controlled-vocabulary.md`)_
- **Security Classification** - hierarchical instrument classification: strict external schemes (GICS) as new effective-dated tables, soft custom taxonomies via `tag_vocabulary.parent_tag` _(future, unscheduled, gated on individual-equities onboarding; design at `docs/research/stratification-security-classification-hierarchy.md` - a Type 3 sibling by taxonomy, deliberately not a shared implementation with the other two)_

---

## What Exists

Type 2/3 registries only - APR (Type 1) is the origin analogy for this whole family (see Registry Taxonomy above) but isn't comparable feature-by-feature here: it's value-mutable parameter tuning, not lifecycle governance or static vocabulary, so it was never designed to have gates, promotion states, or annotations. Full detail: `docs/foundation/adaptive-parameter-registry.md`.

| Registry | Tables | Entries | Gate | Gap |
|---|---|---|---|---|
| Feature Registry | `feature_registry`, `feature_transition_log` | 61 features | IC Sharpe + FDR | Governance only - no knowledge layer; gate params conflated in registry row; migrates to Concept Registry |
| Shadow Registry | `shadow_registry`, `shadow_transition_log` | 36 components | EV[R] bootstrap CI | Legacy, not migrating - see Registry Taxonomy above |
| Tag Vocabulary | `tag_vocabulary`, `instrument_tags`, `instrument_annotations` | 71 tags / 410 assignments | Human curation (falsification engine designed but unbuilt: `stratification-instrument-tag-calibrator.md`) | Stays Type 3 - see Registry Taxonomy boundary note |

---

## Controlled Vocabulary (Type 3)

Full design at `docs/research/concept-controlled-vocabulary.md`. Three tables:

```
controlled_vocabulary      - one row per valid code per namespace
vocabulary_group           - named groupings within a namespace
vocabulary_group_member    - many-to-many membership
```

`VocabularyService`: load at startup, hard crash on Python enum divergence, cached reads.

Namespaces to seed at build time: `signal_outcome` (groups: wins/losses/timeouts), `entry_type`, `signal_status`, `hmm_regime` (5 labels by emission mean), `market_regime_cross_sectional` (9 labels), `timeframe`.

Phase 134 blocker satisfied. Ready to build.

---

## Concept Registry (Type 2) - design exists, NOT a build plan

### Status check, applied honestly

This doc's own "When to Add a New Registry" rule (below) requires *external consumers that need enumeration*. Run it against what's actually true today: one live consumer (`domain='feature'`, already served by `feature_registry`), zero of the other six domains implemented, and the specific complexity added in the 2026-07-01 refinement pass (`concept_gate_template`, `concept_eval_run`, `concept_correlation`) was justified almost entirely by Interaction Factory's ~30,000-candidate scale - a system that is itself unbuilt and deferred. Two speculative designs were justifying each other's complexity. That's a real finding from applying our own stated rule, not a hypothetical concern: **do not build the ten-table version.** It stays documented below as a reference architecture - consulted if and when a domain actually reaches that scale - not as the thing to implement next.

### Purpose

Every research domain that needs evidence-gated lifecycle governance goes here. Alpha patterns, HMM architecture variants, IC methods, ensemble strategies, regime models, intelligence vector features. One system governs all of them, eventually. What gets built *first*, and why, is the Minimal Viable Version immediately below - not the full reference architecture.

Feature Registry migrates into this at build time as `domain = 'feature'` - that separation is historical, not structural. Shadow Registry does not migrate in - see Registry Taxonomy above; it's legacy v2.x plugin/swarm governance with no live v3.0 domain to attach to.

### Core discipline: the gate proves, the annotation explains - never invert

`concept_gate` and `concept_annotation` are deliberately separate tables with no dependency between them in either direction. A concept can carry a detailed, compelling `thesis` annotation and still sit at `candidate` forever if it never clears its gate - a good story is not evidence. Equally, a concept can promote to `active` with no thesis at all if the numbers clear the bar - inexplicable-but-proven is not a defect. This is the single most important invariant in the design: it's the mechanism that prevents the registry from becoming a system for justifying beliefs instead of falsifying them. Any future dashboard, UI, or workflow built on top of this schema must never let annotation content influence a gate decision, and must never require an annotation to exist before a promotion can fire.

This invariant matters more, not less, once an AI agent is proposing concepts autonomously - see "Promotion/Demotion Design for Autonomous Self-Improvement" below, which is the part of this doc actually worth building toward now.

### Minimal Viable Version - build this first, when domain #2 becomes real

Four tables, not ten. This is `feature_registry`'s current shape (identity + status + gate + last-eval cache, all on one row, which is exactly how `feature_registry` does it today) plus a knowledge layer, generalized just enough to take a second domain without a second bespoke table:

```
concept_registry       - identity, domain, status, lineage, enabled
                          status IN ('candidate', 'shadow_only', 'active', 'deprecated') - all four
                          survive from the reference architecture; shadow_only is not optional
                          scaffolding, it's the generalization of what the legacy Shadow Registry
                          did for plugins (live-observed, not yet acted on) - see invariant 6 below
concept_gate           - per-concept gate (no template layer - add one later only if a domain's
                          candidate volume actually makes per-concept configuration painful;
                          we don't know that yet because no domain has produced real candidates)
                          PLUS last-eval cache columns on the same row: last_eval_metric,
                          last_eval_n, last_eval_at, decay_ratio - mirrors feature_registry's
                          last_ic_value/last_ic_sharpe/last_ic_n/last_eval_at today. Without this,
                          a routine eval that reconfirms "still active, still above threshold"
                          writes nothing to concept_transition_log (which only logs status
                          *changes*), so "what's this concept's current measured performance"
                          would be unanswerable between transitions - a real gap caught by
                          checking this design against feature_registry's actual live schema.
                          PLUS fdr_required (bool), fdr_alpha (float) - per-concept FDR settings.
                          Note this is a different granularity than the reference architecture's
                          concept_eval_run.fdr_alpha (corpus-batch FDR for e.g. Interaction
                          Factory's 30,000-candidate sweep); feature_registry's fdr_alpha today is
                          a per-feature setting, which concept_gate is the correct home for - the
                          reference design never actually had a field for this at either
                          granularity, another gap caught by checking against the live schema.
concept_transition_log - immutable state-change audit trail, trigger_reason required
concept_annotation     - thesis / failure_mode / observation / open_question / implementation,
                          source = human | ai | empirical (this field is why the self-improvement
                          section below works - see there)
```

No `concept_gate_template` (per-concept gates are fine at low volume), no separate `concept_eval_state` table (folded into `concept_gate` above - one table doing both jobs is exactly what `feature_registry` already does, no reason to split it prematurely), no `concept_eval_run` (provenance matters once eval cadence is high enough to lose track of which corpus build backed which decision - not yet, one domain, infrequent evals), no `concept_correlation` (redundancy-by-correlation matters once there are enough concepts in one domain to actually be redundant with each other - `feature`'s 61 rows already have this need arguably, but it's a `feature`-specific analysis today, not infrastructure), no candidate staleness job (61 rows, all `active`, nothing rotting).

Both live domains (`feature`, `ensemble_strategy`) have scalar gates and need nothing beyond these four tables. `concept_gate_stack` (Governance Layer, defined below) is a fifth table added only when a domain whose gate is an ordered sequence rather than a scalar actually gets seeded - `confluence` and `regime_model` are vetted against it in Domain Vetting below, but neither is live yet, so it is not part of the baseline build.

**Build trigger:** domain #2 gets real candidates. Originally assessed as "most likely
`alpha_pattern`, once `alpha_events` stabilizes and a self-improving agent starts proposing
patterns" - **reassessed 2026-07-02, that assumption no longer holds unchallenged.**
`alpha_pattern`'s path to real candidates depends on two things that don't exist yet:
`alpha_events` stabilizing (no defined completion point) and an autonomous proposer being
built (a significant project of its own - everything in "Promotion/Demotion Design for
Autonomous Self-Improvement" below has to be right before that proposer's output can be
trusted). `ensemble_strategy` now has a shorter, concrete path: Phase 142B.1 (inserted into
`ROADMAP.md` 2026-07-01/02) specs four human-authored weighting-strategy candidates (E1 shrunk-IC
inputs, E2 mean-variance `Σ⁻¹·IC`, E3 hierarchical partial-pooling, E4 per-feature decay
half-lives), each already has a defined eval mechanism (Phase 142A's `EnsembleICEngine`, OOS,
already planned and Renaissance-reviewed), and the only upstream dependency is Phase 142A
completing - a phase already in flight, not a speculative future capability. `ensemble_strategy`
may reach the build trigger before `alpha_pattern` does.

**Trigger fired (2026-07-04):** Phase 142B.1 is complete. Originally tracked at todo 058, now at
`.planning/todos/pending/112-concept-registry.md` (058 closed 2026-07-13 as a duplicate, kept as
frozen historical record) - do not let this drift; the 2026-07-04 cluster review (F1) found the
trigger had fired with no work item tracking it, which is exactly the "notebook nobody reads"
failure mode this registry exists to prevent, now happening to the registry itself.
`ensemble_weights` holds only `weight_version='v1'` as of
this date - E1/E2 shipped as code paths (`shrinkage.py`, `mean_variance_weights()`), not as rows;
E3/E4 have theses but no eval mechanism yet (F7). Seeding also surfaced two open design questions
that must be resolved before the first migration, not after (F2, F3 below).

**Per-stratum status (F2, 2026-07-04):** the MVP's single global `status` column cannot represent
`ensemble_strategy`'s reality - `ops_ensemble_weight_compare.py` (142B.1-05) selects a champion
weighting method *per (tf, regime) stratum*, so two variants can be simultaneously legitimate.
`regime_model` (intel-12) has the identical need at (dimension, regime_group) grain. Resolution
adopted for `ensemble_strategy`: `status` governs recipe validity (has this weighting method ever
earned a win anywhere); per-stratum champion stays a *fact*, living in `ensemble_weights` as
today, not in `concept_registry`; `redundancy_group`'s "only one holds active" displacement rule
is disabled for this domain (competing weighting strategies are the normal state here, resolved
per stratum by the A/B judge, not by registry displacement). `regime_model` is provisionally
expected to need the opposite resolution - one `concept_registry` row per (dimension,
regime_group), preserving single-status semantics - decide for real at v3.15 planning.

This changes more than timing. `ensemble_strategy`'s E1-E4 candidates are **human-authored**, not
AI-proposed - which means the six self-improvement invariants below (proposal/decision
separation, re-evaluation integrity, proposal budgets, proposer track-record, demotion symmetry,
mandatory `shadow_only` for AI-sourced concepts) mostly don't bind for this domain's first real
use. That makes `ensemble_strategy` a *safer* domain to prove the MVP against than `alpha_pattern`
would be: the schema and gate/annotation discipline get validated on a live domain without also
having to get AI-proposer trust boundaries right on the first attempt. Recommendation if/when the
MVP build trigger fires: build against `ensemble_strategy` first (validates the schema under low
risk), *then* extend to `alpha_pattern`/`confluence` once the self-improvement invariants are
also ready to be exercised for real - don't validate both classes of risk (schema correctness,
AI-proposer trust) in the same first build.

**`alpha_pattern` retired, merged into `confluence` (resolved 2026-07-06):** `docs/research/intel-confluence-detection-persistence-layer.md`
(v3.0, 2026-07-03) defines validated confluences as governed statistical objects with their own
lifecycle (`candidate → shadow → active → decaying → retired`), gates, provenance, and decay
governance - this is the same domain `alpha_pattern` was reserved for, not a sibling. That doc's
own history shows why: `alpha_pattern`'s original scope ("alpha signal ideas competing for
ensemble inclusion") drifted into a vestigial superset once concrete predictor families got their
own crisper homes - dense deterministic transforms went to `feature_interaction`, sparse
conditional predictors carrying a calibrated return distribution went to `confluence`,
retrieval-derived columns went to the analog-predictor design at `feature` grain. Nothing was left
for `alpha_pattern` to govern that one of those three doesn't already cover. Keeping it "reserved,
pending definition" past that point was the same unearned-scaffolding pattern this doc's own
Musk-step-1 pass cut everywhere else - a domain with a name, a slot in three lists, and zero
distinct residual scope. **`alpha_pattern` is retired, not deferred.** If a genuinely new
predictor shape ever emerges that doesn't fit `feature`, `feature_interaction`, or `confluence`,
it earns a new domain name at that time, argued from its own real candidates - it does not revive
`alpha_pattern`.

`confluence`'s lifecycle tables ARE the Concept Registry MVP instantiated for one domain - build
them in the four-table generalized shape (concept_registry/concept_gate/concept_transition_log/
concept_annotation, plus `concept_gate_stack` for its ordered six-gate sequence - see the
Governance Layer section and Domain Vetting below), not as bespoke confluence tables that need
migrating later. **Status mapping settled (2026-07-04, per intel-10 v3 / 2026-07-03 Fable review
F4):** intel-10 uses a `decaying` *status* (weight-consumers stop reading, but the concept still
fires and records occurrences); this registry has no such status - decay lives in `decay_ratio` +
demotion. `decaying` maps onto `shadow_only` re-entered from `active` (live-observed, not acted
on) - a transition pattern, not a new enum value; `retired` maps onto `deprecated`. The enum
survives unchanged as `candidate/shadow_only/active/deprecated`.

### Promotion/Demotion Design for Autonomous Self-Improvement

This is the part of the design that's actually worth thinking hard about now, because it's the part that changes shape once the proposer is an AI agent instead of a human researching by hand - everything above this section is infrastructure that can wait; this section is a set of invariants that need to be right from the first line of code, because retrofitting them after an autonomous agent has been proposing and promoting concepts for a while means auditing a history you can no longer fully trust.

**1. Proposal and decision are different roles, structurally, not conventionally.** An AI agent may create a `concept_registry` row (`status='candidate'`), write its `thesis` annotation (`source='ai'`), even suggest a gate. It may never write to `status` directly. Only the deterministic evaluation engine - a fixed code path with no LLM in it, reading only `concept_gate`/`concept_gate_stack` and eval results - flips `status`. This is the gate-proves/annotation-explains discipline stated as an access-control rule: an AI that can write a persuasive `thesis` must be structurally incapable of using that same persuasiveness to promote itself. In practice: the promotion function is a plain SQL transaction or a narrowly-scoped service method - no agent, human or AI, gets a code path that both writes annotation content and flips status in the same call.

**2. Re-evaluation consumes new evidence, never re-rolls the same dice.** An autonomous proposer that can resubmit the same candidate for re-evaluation indefinitely will eventually clear a p<0.05 gate by chance alone - the look-elsewhere effect, self-inflicted. Corpus-advance alone ("the corpus has moved since the last eval") is a necessary but insufficient guard: this project's corpus rebuilds run every few days on mostly-overlapping windows, so two passes can double-count the same fluke. Re-evaluation is permitted only once ≥ N new independent observations have accrued since the concept's last evaluation - a per-domain `concept_gate` field, APR-keyed, in the same family as `alpha.decay.recovery_min_observations` (the identical standard Phase 143 already applies to feature-recovery evidence). `concept_transition_log.corpus_build_ref` (the live CorpusManifest identity - `.planning/corpus_manifests/*.json`, `src/observability/corpus_manifest.py`) is what "the corpus has advanced" checks against; it is a cheap necessary precondition, not the whole guard.

**3. Proposal volume has a budget, even at minimal-version scale.** A human researcher self-limits by how many ideas they can physically generate; an AI agent doesn't. `alpha.concept_registry.max_ai_candidates_per_period` (APR-backed) caps new `candidate` rows per domain per period from `source='ai'`, enforced at the service layer, not the schema.

**4. The proposer's own track record is tracked, for free.** `concept_annotation.source` already distinguishes `human`/`ai`/`empirical` on every thesis, which alone answers "is the AI's idea generation actually any good": `SELECT source, count(*) FILTER (WHERE status='active') / count(*)::float AS hit_rate FROM concept_registry c JOIN concept_annotation a ON a.concept_id=c.concept_id AND a.annotation_type='thesis' GROUP BY source`. A worse-than-human hit rate is a signal to retrain or constrain the proposer, not to trust its future proposals more. No new table - just the requirement, already in the minimal version, that every `candidate` row gets a `thesis` annotation with an honest `source` at creation.

**5. Demotion is exempt from the same self-interest problem, in reverse.** An agent that proposed a concept has no business deciding to keep a failing concept alive past its gate. Demotion, like promotion, is engine-only - same rule as Invariant 1, opposite direction. `decay_floor`-triggered demotion (reference architecture) or `demotion_threshold` (minimal version) fires automatically once gate conditions are met, with no override path through the proposer. Decay itself is domain-agnostic infrastructure, not a domain of its own: `decay_ratio` measured against a shrunk `baseline_metric` (§concept_eval_state below) generalizes to every domain, and the platform-level continuous-monitoring half (CUSUM change-detection, rolling-metric drift) is `docs/research/measurement-governance-monitor.md`'s IntegrityMonitor design, feeding transitions through `feature_registry` today and `concept_registry` once built. This is why decay never justified a bespoke `alpha_pattern`-shaped domain - see its retirement note under "Concept Registry (Type 2)" above.

**6. `shadow_only` is mandatory between `candidate` and `active` for proposer-driven or backtested-only domains, non-negotiable for AI-sourced concepts.** This generalizes what the legacy Shadow Registry did for plugins: clear the statistical gate, then run live-observed for `min_promotion_consecutive` real eval cycles with zero downstream influence (`enabled` stays inert), before ever reaching `active`. A human proposer implicitly shadow-tests an idea through their own judgment before formally proposing it; an autonomous proposer has no such filter, making this stage more load-bearing for AI-sourced concepts. Backtested/OOS proof and live-observed proof are different evidence kinds - a concept can pass walk-forward validation and still behave differently once watching live data it wasn't fit to. **Documented exception: `domain='feature'`** - features are hand-engineered, not proposer-driven, and the walk-forward IC gate's fold-based OOS validation already serves an equivalent evidentiary function to live observation (per `docs/research/archive/feature-vector-lifecycle.md`: "the IC gate is retrospective... this is not a gap"). `feature_interaction` inherits the same exception, same evaluation methodology. Any domain claiming this exception must document why its gate already provides the evidence live observation would add, not merely assert it; proposer-driven domains (`confluence` especially, once real) do not get it by default.

**Documented exception: `domain='ensemble_strategy'` (recorded 2026-07-13, todo 058 build).** E1-E4 candidates are human-authored, not proposer-driven, so mandatory `shadow_only` does not bind here the way it would for an AI-sourced concept. The evidentiary substitute for a live shadow period is the OOS A/B judged by `EnsembleICEngine` over live corpus runs: per-stratum non-overlapping-CI win rule (challenger `ic_ci_lower` > champion `ic_ci_upper`), `walk_forward_stable` veto, and BH-FDR correction across strata, executed by `ops_ensemble_weight_compare.py` and recorded through `ConceptRegistryService.record_comparison_outcome()` - which is also this domain's invariant-1 deterministic status-flipper. Promotion therefore runs `candidate -> active` directly for this domain; every promotion transition's `notes` cites this exception.

**7. Initial promotion requires an effective-N minimum observation floor, regardless of statistical significance.** A concept clearing p<0.05 on 50 bars is not proven, it's a fluke. Every domain specifies a `min_observation_floor` in its gate (APR-backed, per-domain: `alpha.concept_registry.feature_min_observations`, `alpha.concept_registry.ensemble_strategy_min_observations`, etc.), and no promotion fires until it is met even if the gate metric clears. The floor is stated against the *effective* count, not raw bars: overlapping forward returns are autocorrelated by construction, so 20,000 overlapping bars can carry the information of a few hundred independent observations. Applying this uses the same independence discipline the live IC engine already applies (stride subsampling via `alpha.ic.subsample_min_stride`; effective-N gating in the family of `alpha.ensemble.effective_n_gate`) - a floor met only by raw overlapping bars is not met. This invariant governs first promotion only; re-evaluation uses Invariant 2's N-new-observations rule.

**8. Evidence is bound to the implementation version that produced it.** A promotion proves a specific recipe as computed by a specific code path. If the computation silently changes after promotion (a formula edit, a normalization fix, a window change), the accumulated evidence no longer describes what is running, and `active` becomes a stale claim. Every concept carries an implementation-version identity - for `domain='feature'` this is `pipeline_version` on `feature_vectors`; for a concept parameterized via `metadata.apr_namespace` (§concept_registry below), the version identity is the `config_history` version of every key under that namespace, snapshotted at promotion time - and every evaluation and transition records the version it measured. A version change resets promotion evidence (counters zero, the concept re-enters evaluation, `trigger_reason='implementation_change'`); otherwise Invariant 2's new-evidence rule is enforced against the wrong denominator, with old-version evidence quietly counting toward a new-version promotion.

**9. Status transitions are compare-and-swap, in one transaction.** The promotion/demotion write is `UPDATE concept_registry SET status = :to WHERE concept_id = :id AND status = :from`; zero rows updated aborts the whole transaction, including the `concept_transition_log` insert. Without the `AND status = :from` guard, two racing evaluators (or one evaluator holding a stale in-memory cache) can log a transition whose `from_status` never matched the row, corrupting the exact audit trail this system exists to keep trustworthy. (The live `FeatureRegistryService._write_transition_record()` does not do this today - unconditional `UPDATE ... SET status`, scheduled fire-and-forget, failure reduced to a log line the caller never sees - a migration-time fix, not a pattern to generalize.)

None of this requires the ten-table reference architecture. All nine invariants apply directly to the four-table minimal version - they govern who can write what, in what order, and under what identity, not additional storage: Invariant 8 costs one metadata field plus a version column on the log; Invariant 9 costs a WHERE clause.

### Full Reference Architecture (do not build yet) - two layers, ten tables

```
GOVERNANCE LAYER - is this valid, what state is it in, what happened, and could we prove it again
  concept_registry       - identity, status, lineage, redundancy group
  concept_gate_template   - domain-level default gate
  concept_gate           - per-concept override of the domain template; optional
  concept_eval_run       - one row per evaluation batch/cycle; ties results to a corpus build
  concept_eval_state     - last-cycle summary only (promotion/demotion counters); NOT the history record
  concept_transition_log - immutable state-change audit trail

KNOWLEDGE LAYER - why it works, what breaks it, what we know, what depends on what, what's redundant
  concept_annotation     - versioned knowledge: thesis, assumptions, failure modes, observations
  concept_dependency     - directed dependency graph between concepts
  concept_regime_ic      - full regime-stratified IC matrix, one row per (concept, regime) per eval_run
  concept_correlation    - pairwise correlation within a domain, one row per pair per eval_run
```

Ten tables, not seven - three refinements (gate templates, eval provenance, correlation-as-evidence) each add one table. `concept_eval_state` is demoted from "the record" to "a cache of the most recent record," because a system built to prevent institutional amnesia cannot itself forget how a metric trended over time.

---

### GOVERNANCE LAYER

#### concept_registry

Identity and current state. Changes almost never. Owned by operator/migration.

```sql
CREATE TABLE concept_registry (
    concept_id        UUID    PRIMARY KEY DEFAULT gen_random_uuid(),
    domain            TEXT    NOT NULL
        -- Seed ONLY domains with real candidates at build time. As of 2026-07-06 that is two:
        -- 'feature' (61 live rows to migrate) and 'ensemble_strategy' (E1-E4, todo 058).
        -- Every other domain in the Domains table below ('feature_interaction', 'hmm_variant',
        -- 'ic_method', 'regime_model', 'confluence', embedding recipes) is added by a one-line
        -- migration when it has real candidates. A prior version of this CHECK pre-seeded seven
        -- values, five of them with zero candidates, while holding only 'confluence' to the
        -- real-candidates bar - the rule is now applied uniformly. ('alpha_pattern' is not in
        -- this list because it is retired, not pending - see Domains below.)
        -- 'regime_model' in particular must NOT be added before its row-grain question (one
        -- row per dimension vs. per (dimension, regime_group) - see
        -- docs/research/stratification-dimension-unification.md) is decided at v3.15 planning; adding it
        -- earlier bakes in a grain that may be wrong.
        CHECK (domain IN ('feature', 'ensemble_strategy')),
    name              TEXT    NOT NULL,
    description       TEXT    NOT NULL,
    status            TEXT    NOT NULL DEFAULT 'candidate'
        CHECK (status IN ('candidate', 'shadow_only', 'active', 'deprecated')),
    enabled           BOOLEAN NOT NULL DEFAULT false,
    parent_concept_id UUID    REFERENCES concept_registry(concept_id),
    redundancy_group  TEXT,
    metadata          JSONB,
    added_phase       TEXT,
    sensitivity       TEXT,   -- NULL today, unused; forward-looking hook, see "What This Is" above
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (domain, name)
);
```

**`domain`** is enforced with a plain `CHECK` constraint, same pattern as `status` above - no dependency on Controlled Vocabulary. An earlier version of this design specced `domain` validation as a runtime dependency on `VocabularyService.codes("concept_domain")`, requiring Controlled Vocabulary (a separate, also-unbuilt, also-deferred Type 3 system) to exist before Concept Registry could. That coupling wasn't earning its cost - 7 fixed values already listed inline is exactly the same shape as `status`'s 4 values, which needs nothing beyond a `CHECK`. Correction: Concept Registry has no dependency on Controlled Vocabulary. They remain unrelated sibling designs - Concept Registry governs lifecycle, Controlled Vocabulary governs symbolic-code labels/groupings elsewhere in the platform (`signal_outcome`, `regime` labels, `timeframe`, etc.) - with no shared build gate and no reason to couple their schedules.

**`enabled`** is independent of `status`. An `active` concept can be disabled without demotion. A `candidate` can run in shadow before formal promotion. The evaluation engine skips `enabled = false` entirely.

**`parent_concept_id`** creates a research lineage tree. When an HMM variant is iterated, the revision references the prior version. History is navigable. **Cardinality caveat:** this is a single-parent FK, but `feature_registry.parent_features` is `text[]` - a compound primitive like `xf_prod_body_ratio__volume_z` (naming per `intel-feature-interaction-factory.md`: single underscore after the operation, double underscore between parent names) has two parents by definition. Zero live features exercise this today (checked: `array_length(parent_features, 1) > 1` returns no rows), so it's not an active migration blocker, but `concept_dependency`'s `uses_feature` edge type (in the reference architecture, not the MVP) is the correct home for multi-parent relationships once Interaction Factory produces compound features - `parent_concept_id` should stay reserved for true single-lineage iteration (HMM variant v2 replacing v1), not composition.

**`redundancy_group`** prevents silent over-fitting. Concepts in the same group compete - only one holds `active`. **Scoped to a single domain** - a `redundancy_group` spanning `confluence` and `hmm_variant` has no coherent meaning; different gate metrics, different eval methods, nothing to compare. Enforced with `CHECK` at the service layer: all members of a `redundancy_group` must share `domain`. When a new concept earns promotion, it displaces the incumbent unless `concept_correlation` (below) shows their correlation is under threshold - this is evidence looked up, not an assumption made.

**`metadata` carries a pointer to the concept's computational definition, never the definition itself (convention added 2026-07-06, per the Architecture Stress-Test's Alternative 5).** The clean precedent for this, found by auditing `src/core/ml/registry.py`'s `ModelRegistry` (dead today, but the pattern is sound): a lifecycle row holds identity plus a *reference* to wherever its actual parameters/artifact live (`mlflow_run_id`, `artifact_path`), never a copy of them. `concept_registry.metadata` follows the same rule. For a concept whose computation is parameterized by APR-tunable numbers, `metadata->>'apr_namespace'` names the APR namespace prefix that fully parameterizes it (e.g. an `hmm_variant` row `factor_augmented_v1` sets `metadata.apr_namespace = 'alpha.hmm_variant.factor_augmented_v1'`; `ConfigService` reads every key under that prefix). For a concept whose definition is code (a feature formula, an agent prompt), `metadata` points at the code path or, for `domain='feature'`, the `implementation` annotation already carries this. Never store parameter *values* in `metadata` - only where to find them; APR (or the code, or MLflow if ML models are ever revived) stays the single source of truth for the value itself, so there is never a second copy that can drift.

---

#### concept_gate_template

Domain-level default gate. Added because the design's own first heavy user *would* break the original one-gate-per-concept assumption: if Interaction Factory (`docs/research/intel-feature-interaction-factory.md`) is ever built and reaches its full ~30,000-candidate scale, nobody hand-configures 30,000 gates. **Caveat, consistent with the "Status check" above:** Interaction Factory itself now has an explicit evidence-based build trigger (documented atomic-feature IC saturation, not just readiness) and is not scheduled - so this table's justification is conditional on a system that may never reach that scale. It's kept in the reference architecture as "what this would need if that happens," not as an active requirement.

```sql
CREATE TABLE concept_gate_template (
    domain                     TEXT  PRIMARY KEY,
    gate_metric_name           TEXT  NOT NULL,
    gate_eval_method           TEXT  NOT NULL,
        -- 'oos_holdout', 'walk_forward', 'bootstrap_ci' - in-sample never valid
    min_gate_metric            FLOAT   NOT NULL,
    min_gate_n                 INTEGER NOT NULL DEFAULT 100,
    min_promotion_consecutive  INTEGER NOT NULL DEFAULT 3,
    demotion_threshold         FLOAT,
    demotion_lookback_days     INTEGER,
    demotion_consecutive       INTEGER,
    decay_floor                FLOAT,
    max_candidate_age_days     INTEGER NOT NULL DEFAULT 90,
    updated_at                 TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

**`max_candidate_age_days`** fixes candidate rot: a `candidate` with no `concept_eval_run` referencing it within this window auto-transitions to `deprecated` with `trigger_reason = 'candidate_timeout'` (see `concept_transition_log`). An unevaluated candidate sitting in the registry forever is the "notebook nobody reads" failure mode wearing a different UUID. Retention still holds: the row and its annotations are never deleted, just moved out of the active consideration set.

---

#### concept_gate

Per-concept override of the domain template. Optional - most concepts in a high-volume domain (`feature_interaction`, eventually `confluence`) have no row here and inherit `concept_gate_template` for their domain. A row here only exists when a specific concept needs a bar different from its domain's default (e.g. a `regime_scope`-conditional gate, or a hand-tuned `decay_floor`).

```sql
CREATE TABLE concept_gate (
    concept_id                UUID  PRIMARY KEY REFERENCES concept_registry(concept_id),
    gate_metric_name          TEXT,   -- NULL = inherit from concept_gate_template
    gate_eval_method          TEXT,   -- NULL = inherit
    min_gate_metric           FLOAT,  -- NULL = inherit
    min_gate_n                INTEGER,
    min_promotion_consecutive INTEGER,
    demotion_threshold        FLOAT,
    demotion_lookback_days    INTEGER,
    demotion_consecutive      INTEGER,
    decay_floor               FLOAT,
    regime_scope              TEXT,   -- NULL = unconditional; regime label = conditional gate
    updated_at                TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

**`gate_eval_method`** is non-negotiable, at either the template or override level. In-sample IC causes false promotions. The evaluation engine resolves `COALESCE(concept_gate.field, concept_gate_template.field)` per concept and enforces whatever resolves.

**`min_promotion_consecutive`** - N consecutive evaluations above threshold before promotion fires. Default 3. One good evaluation proves nothing.

**`regime_scope`** - an edge that works only in trending regime is a real edge. Governing it conditionally is more honest than forcing it through an unconditional gate it cannot pass. Template-level, since it's concept-specific by nature, has no domain default. **(2026-07-01, second pass) a bare label is ambiguous under the multi-dimension stratification roadmap:** today the per-symbol HMM labels (`trending_up`...) and cross-sectional labels (`high_bear`...) happen to be disjoint strings, but `docs/plans/archive/2026-07-01-regime-stratification-alternatives.md` adds more dimensions (volatility_regime, dispersion_regime) whose bucket names can collide. Qualify with the stratification dimension - `market_regimes:high_bear`, `hmm:trending_up`, `volatility_regime:high` - or split into `(regime_dimension, regime_label)` columns at build time. **Pre-registration rule (2026-07-06):** `regime_scope` is declared before the concept's evaluation begins, never chosen after seeing per-stratum results. A concept evaluated across R strata and promoted on the best one is R hypotheses tested with one reported - selection bias that the batch-level FDR machinery (`concept_eval_run.n_candidates_in_run`) never sees, because it counts candidates, not strata per candidate. Either the scope is pre-declared (one hypothesis), or every stratum tested enters the multiplicity correction as its own entry.

**`decay_floor`** - when `current_metric / baseline_metric_at_promotion < decay_floor`, decay demotion fires immediately without waiting for `demotion_consecutive`. Zombie edges die fast.

---

#### concept_gate_stack (optional extension - added per-domain, not part of the baseline four/ten tables)

**Added 2026-07-06** to resolve the "one schema, really?" question the design had previously
narrowed but not answered. `concept_gate` and `concept_gate_template` assume a gate is one scalar
metric cleared once (`gate_metric_name`, `min_gate_metric`). Two domains vetted below  - 
`confluence` (a mandatory *ordered sequence* of six qualitatively different gates: marginal lift,
FDR, walk-forward stability, calibration, cost hurdle, OOS) and `regime_model` (a three-stage
cascade: structural pre-filter, orthogonality study, substitution test) - do not reduce to that
shape, and forcing them to would be exactly the "ill-fitting shared table" failure mode this
doc's own review lens warns against. Per the user's framing that domains "don't have to share
identical tables": the shared discipline is the state machine (`concept_registry.status`), the
audit trail (`concept_transition_log`), and the nine promotion/demotion invariants - not
necessarily one physical gate-row shape. A domain whose gate is a sequence adds this one
extension table; a domain whose gate is a scalar (`feature`, `hmm_variant`, `ensemble_strategy`,
and - if it ever gets a real candidate - `ic_method`) never touches it.

```sql
CREATE TABLE concept_gate_stack (
    concept_id       UUID    NOT NULL REFERENCES concept_registry(concept_id),
    gate_order       INTEGER NOT NULL,   -- 1..N, evaluated in order; a failed gate stops the sequence
    gate_name        TEXT    NOT NULL,   -- e.g. 'marginal_lift', 'fdr', 'walk_forward_stability',
                                         -- 'calibration', 'cost_hurdle', 'oos_confirmation' (confluence);
                                         -- 'structural_redundancy', 'orthogonality', 'substitution_test' (regime_model)
    gate_eval_method TEXT    NOT NULL,   -- same vocabulary as concept_gate.gate_eval_method
    threshold        FLOAT,              -- NULL for gates that are boolean pass/fail (e.g. structural pre-filter)
    passed           BOOLEAN,
    evaluated_value  FLOAT,
    evaluated_n      INTEGER,
    evaluated_at     TIMESTAMPTZ,
    PRIMARY KEY (concept_id, gate_order)
);
```

`concept_gate` still exists for a stack-governed concept, but its scalar columns stay NULL  - 
`concept_gate.decay_floor` and `concept_gate.regime_scope` are still meaningful post-promotion
fields that belong on the concept, not on any one gate in the stack. `concept_transition_log`
fires once, on the full stack clearing (or on the first gate failing, ending candidacy) - the
stack is the promotion decision's internal detail, not a source of six separate transitions. In
the reference architecture, `concept_gate_stack.eval_run_id` would reference `concept_eval_run`
the same way `concept_transition_log` does; the MVP shape above uses `evaluated_at` only, matching
how the rest of the MVP omits `concept_eval_run` until eval cadence is high enough to need it.

---

#### concept_eval_run

One row per evaluation batch/cycle, per domain. Fixes two gaps at once:

1. **Reproducibility** - every `concept_eval_state` and `concept_transition_log` row references the `eval_run_id` that produced it, which in turn records which corpus build / `feature_ic_scores` generation it read from. Without this, "why was this demoted on 2026-08-14" is unanswerable after the next corpus rebuild overwrites the numbers that decision was based on - and this project rebuilds its corpus every few days.
2. **Portfolio-level false discovery control** - `n_candidates_in_run` records how many concepts were gate-checked in the same batch. A domain running 30,000 `feature_interaction` candidates through one eval cycle needs a corpus-level BH-FDR correction across that batch (same principle the IC engine already applies per Phase 142A) - this table is what makes that correction possible after the fact, not just at compute time.

```sql
CREATE TABLE concept_eval_run (
    eval_run_id        UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    domain              TEXT         NOT NULL,
    corpus_build_ref    TEXT         NOT NULL,   -- ties to the ic_engine/corpus rebuild that produced the inputs
                                                 -- (2026-07-01) this already has a live implementation: the
                                                 -- CorpusManifest system (.planning/corpus_manifests/*.json,
                                                 -- src/observability/corpus_manifest.py) written by ic_engine/
                                                 -- ensemble_trainer/alpha_publisher today - use the manifest
                                                 -- identity/timestamp, don't invent a parallel identifier.
                                                 -- Invariant 2's "corpus must have advanced" check compares this.
    n_candidates_in_run INTEGER      NOT NULL,
    fdr_alpha           FLOAT        NOT NULL DEFAULT 0.05,
    started_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    completed_at        TIMESTAMPTZ
);
```

---

#### concept_eval_state

Cache of the most recent evaluation - **not the history**. History lives in `concept_eval_run` joined against per-run results (see below); this table exists purely so the evaluation engine and dashboard can read "current state" in one row without scanning history.

```sql
CREATE TABLE concept_eval_state (
    concept_id             UUID  PRIMARY KEY REFERENCES concept_registry(concept_id),
    last_eval_run_id       UUID  REFERENCES concept_eval_run(eval_run_id),
    last_eval_metric       FLOAT,
    last_eval_n            INTEGER,
    last_eval_ci_lower     FLOAT,
    baseline_metric        FLOAT,   -- metric at promotion; NULL if never promoted
    decay_ratio            FLOAT,   -- last_eval_metric / baseline_metric
    promotion_consecutive  INTEGER  NOT NULL DEFAULT 0,
    demotion_consecutive   INTEGER  NOT NULL DEFAULT 0,
    last_eval_at           TIMESTAMPTZ,
    last_eval_regime       TEXT
);
```

**`baseline_metric`** is written once at promotion and never updated. `decay_ratio` is derived from it every cycle. When `decay_ratio < decay_floor`, the engine fires a decay demotion immediately.

**Winner's-curse correction on the baseline (added 2026-07-01, second pass):** a concept promotes
exactly when its measured metric is high - which is partly luck (the promotion gate selects on the
metric, so the promotion-time value is biased upward by construction). If `baseline_metric` stores
the raw promotion-time value, `decay_ratio`'s denominator is systematically inflated and decay
demotions will fire on pure regression-to-the-mean, killing healthy concepts. `baseline_metric`
must store the *shrunk* estimate (empirical-Bayes toward the domain/regime prior, weighted by
effective N - same mechanism as `docs/plans/archive/2026-06-29-feature-scoring-beyond-ic.md` §0b) or,
minimally, the mean of the `min_promotion_consecutive` evaluations rather than the final one.
This applies equally to the MVP's `concept_gate` last-eval cache columns.

**Original design flaw, fixed by `concept_eval_run`:** this table was previously described as "overwritten each cycle - not audit data," which meant a concept sitting `active` for months with slowly eroding IC that never crosses the demotion threshold had its entire decay trajectory silently lost - visible only if a transition eventually fired. That directly contradicted the "never drop data that could contain signal" principle. Every eval cycle now writes a durable row keyed by `eval_run_id` (in `concept_regime_ic` for the regime-stratified numbers, or a lightweight `concept_eval_run` join for the scalar gate metric) - `concept_eval_state` is free to be "just the latest" because the full curve is reconstructable elsewhere.

---

#### concept_transition_log

What happened. Immutable, append-only. **Declared as a TimescaleDB hypertable at build time
(2026-07-06, per the Architecture Stress-Test's Alternative 2)** - partitioned on `triggered_at`,
matching `config_history`, `llm_calls`, and `signal_lineage`, this project's three other
immutable-audit-trail tables. This is the concrete, low-cost lesson taken from seriously
evaluating full event-sourcing as a replacement for the mutable `status` column: don't replace the
column (APR's own `config_state`/`config_history` split, which this design already mirrors, is the
stronger precedent), but do give the append-only side of that split the same storage engine this
project already gives every other append-only side.

```sql
CREATE TABLE concept_transition_log (
    id             BIGSERIAL    PRIMARY KEY,
    concept_id     UUID         NOT NULL REFERENCES concept_registry(concept_id),
    domain         TEXT         NOT NULL,
    name           TEXT         NOT NULL,
    from_status    TEXT         NOT NULL,
    to_status      TEXT         NOT NULL,
    trigger_reason TEXT         NOT NULL,
        -- 'promotion', 'demotion_performance', 'demotion_decay',
        -- 'demotion_redundancy', 'operator_override', 'parent_cascade',
        -- 'candidate_timeout'
    eval_run_id    UUID         REFERENCES concept_eval_run(eval_run_id),
    gate_metric    FLOAT,
    gate_n         INTEGER,
    ci_lower       FLOAT,
    decay_ratio    FLOAT,
    regime_scope   TEXT,
    triggered_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    notes          TEXT
);
```

`trigger_reason` distinguishes why a demotion fired. A decay demotion on a once-strong concept signals edge erosion. A redundancy demotion signals a better competitor emerged. A `candidate_timeout` demotion signals nobody ever evaluated the idea - a different research response than either (revisit vs. abandon vs. schedule). `eval_run_id` ties the transition back to the exact corpus build and candidate batch that triggered it.

---

### KNOWLEDGE LAYER

#### concept_annotation

Versioned, typed knowledge about a concept. Append-only - annotations accumulate over time, superseded annotations are closed with `valid_to`. Same pattern as `instrument_annotations`.

```sql
CREATE TABLE concept_annotation (
    annotation_id   UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    concept_id      UUID         NOT NULL REFERENCES concept_registry(concept_id),
    annotation_type TEXT         NOT NULL CHECK (annotation_type IN (
        'thesis',           -- why this works: market microstructure or behavioral basis
        'assumption',       -- what must be true for it to hold
        'failure_mode',     -- when and how it breaks
        'observation',      -- empirical finding since deployment
        'open_question',    -- what we still do not understand
        'implementation',   -- how it is computed, which code path
        'reference'         -- paper, doc, or prior concept that inspired this
    )),
    content         TEXT         NOT NULL,
    source          TEXT         NOT NULL CHECK (source IN ('human', 'ai', 'empirical')),
        -- 'empirical' = derived from evaluation data by the evaluation engine
    confidence      FLOAT        CHECK (confidence BETWEEN 0 AND 1),
    valid_from      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    valid_to        TIMESTAMPTZ, -- NULL = still holds; set when superseded
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);
```

Every concept gets a `thesis` annotation at creation - this is the intellectual basis, not a one-liner description. The `failure_mode` annotations accumulate empirically: the evaluation engine writes one when it detects a regime or volatility condition that correlates with IC collapse. `observation` annotations capture what was learned post-promotion that was not known at creation. `open_question` annotations mark things that are unresolved - they surface in the dashboard as open research items.

`source = 'empirical'` means the evaluation engine wrote it, not a human. Example: "IC correlation with alpha_pattern_momentum_exhaustion = 0.71, evaluated 2026-09-14, n = 1200 bars." This turns the evaluation engine into a self-documenting research system.

---

#### concept_dependency

Directed dependency graph between concepts.

```sql
CREATE TABLE concept_dependency (
    concept_id       UUID NOT NULL REFERENCES concept_registry(concept_id),
    depends_on_id    UUID NOT NULL REFERENCES concept_registry(concept_id),
    dependency_type  TEXT NOT NULL CHECK (dependency_type IN (
        'uses_feature',     -- alpha pattern uses this feature
        'extends',          -- this is a refinement of that concept
        'competes_with',    -- explicit competition outside redundancy_group
        'requires_method'   -- this concept requires a specific ic_method or regime_model
    )),
    PRIMARY KEY (concept_id, depends_on_id)
);
```

Enables impact analysis: "what breaks if `momentum_z_fast` is deprecated?" → query `WHERE depends_on_id = X AND dependency_type = 'uses_feature'`. The gate check at promotion time can block a concept from promoting if any of its `uses_feature` dependencies are still `candidate`.

---

#### concept_regime_ic

Full regime-stratified IC matrix. The evaluation engine writes this every cycle for every active/shadow concept. The ensemble reads it to weight concepts by current regime.

```sql
CREATE TABLE concept_regime_ic (
    concept_id   UUID         NOT NULL REFERENCES concept_registry(concept_id),
    regime_label TEXT         NOT NULL,
    eval_run_id  UUID         NOT NULL REFERENCES concept_eval_run(eval_run_id),
    ic_sharpe    FLOAT,
    ic_n         INTEGER,
    ci_lower     FLOAT,
    updated_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    PRIMARY KEY (concept_id, regime_label, eval_run_id)
);
```

This is richer than `regime_scope` in `concept_gate`. A concept with `regime_scope = NULL` (unconditional gate) may still show a strong regime profile here: IC Sharpe 0.8 in `trending_up`, 0.1 in `ranging`, -0.3 in `trending_down`. The ensemble uses the full matrix to apply zero weight outside the concept's strong regimes without needing to change its governance status. Regime-conditional weighting and regime-conditional promotion are separate concerns. Keying on `eval_run_id` rather than overwriting `(concept_id, regime_label)` in place is what makes this the durable eval-history table referenced above - the ensemble reads the latest `eval_run_id` per concept; research queries can read all of them.

---

#### concept_correlation

Makes redundancy an evidence-backed fact instead of an implied rule. Scoped within a domain - cross-domain correlation between, say, a `confluence` and an `hmm_variant` isn't well-defined (different gate metrics, different eval methods) and isn't computed here.

```sql
CREATE TABLE concept_correlation (
    concept_id_a  UUID         NOT NULL REFERENCES concept_registry(concept_id),
    concept_id_b  UUID         NOT NULL REFERENCES concept_registry(concept_id),
    domain        TEXT         NOT NULL,
    eval_run_id   UUID         NOT NULL REFERENCES concept_eval_run(eval_run_id),
    correlation   FLOAT        NOT NULL,
    computed_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    PRIMARY KEY (concept_id_a, concept_id_b, eval_run_id),
    CHECK (concept_id_a < concept_id_b)   -- one row per unordered pair
);
```

The redundancy-group displacement rule (`concept_registry` above) reads this table before displacing an incumbent: if the challenger's correlation to the incumbent (looked up here, most recent `eval_run_id`) is below the domain's redundancy threshold, both can coexist as `active` - they're not actually redundant even though they're in the same `redundancy_group`, they're diversifying. This is also useful independent of redundancy_group membership: it's the raw material for "what's secretly correlated with what" queries the ensemble's correlation engine would need if `feature_interaction` ever reaches meaningful scale - `intel-feature-interaction-factory.md`'s "Concentration Risk" section flags this as a correctly-open question, since no compounds exist yet to measure.

---

### Separation of concerns

| Table | Layer | Owner | Changes when | Query purpose |
|---|---|---|---|---|
| `concept_registry` | Governance | Operator / migration | Concept added, iterated, or deprecated | What exists and what state is it in? |
| `concept_gate_template` | Governance | Operator | Domain-wide bar tuned | What does this domain need to prove by default? |
| `concept_gate` | Governance | Operator | Exception to the domain default | What does this specific concept need to prove instead? |
| `concept_eval_run` | Governance | Evaluation engine | Every eval batch | Which corpus build produced these results, how many candidates ran together? |
| `concept_eval_state` | Governance | Evaluation engine | Every eval cycle | What did we last observe (cache only)? |
| `concept_transition_log` | Governance | Evaluation engine | Every state change | What happened and why, tied to which eval run? |
| `concept_annotation` | Knowledge | Human / AI / engine | New understanding gained | Why does it work? What breaks it? What's open? |
| `concept_dependency` | Knowledge | Operator / migration | Concept created or relationship identified | What does this depend on? What does it affect? |
| `concept_regime_ic` | Knowledge | Evaluation engine | Every eval cycle (new row per run, not overwritten) | What is the IC profile by regime, and how has it trended? |
| `concept_correlation` | Knowledge | Evaluation engine | Every eval cycle, within-domain pairs | What's actually redundant vs. merely co-located in a group? |

---

### Worked example: "what are all the active X, explain them, show the math"

The motivating query this whole design exists to answer, and it's the same shape for every domain - `feature`, `confluence`, `hmm_variant`, whatever `domain` value is passed in:

```sql
SELECT c.name, c.status, c.enabled,
       thesis.content AS why_it_works,
       impl.content   AS formula_or_code_path,
       fm.content     AS known_failure_modes
FROM concept_registry c
LEFT JOIN concept_annotation thesis ON thesis.concept_id = c.concept_id
       AND thesis.annotation_type = 'thesis' AND thesis.valid_to IS NULL
LEFT JOIN concept_annotation impl   ON impl.concept_id = c.concept_id
       AND impl.annotation_type = 'implementation' AND impl.valid_to IS NULL
LEFT JOIN concept_annotation fm     ON fm.concept_id = c.concept_id
       AND fm.annotation_type = 'failure_mode' AND fm.valid_to IS NULL
WHERE c.domain = :domain AND c.status = 'active'
ORDER BY c.name;
```

Before this exists, that question is only answerable for one domain (`feature`, via `feature_registry.formula_short` - a one-line gloss, not the actual formula) and not at all for any other domain. After migration, `implementation` annotations close the formula gap too - `formula_short`'s one-liner becomes a fuller, versioned `implementation` annotation that can hold the real derivation or a code-path pointer, not just a description of it.

---

### ConceptRegistryService

Domain-scoped **lazy loading**. Active and shadow_only concepts load eagerly at daemon startup - these are in use. Candidates load lazily when the evaluation engine requests them. With hundreds (or tens of thousands, for `feature_interaction`) of candidates, loading all at startup is wasteful.

Hard crash if any domain referenced in `concept_registry` has no `concept_gate_template` row - every domain must have a resolvable default, even if every individual concept overrides it. A `concept_gate` row is optional per concept; `concept_gate_template` is not optional per domain.

A background job enforces `max_candidate_age_days` per domain: any `candidate` with no `concept_eval_run` reference older than the template's window transitions to `deprecated` with `trigger_reason = 'candidate_timeout'`.

Knowledge layer tables (annotation, dependency, regime_ic, correlation) are read on demand, not cached at startup. They are queried by the dashboard and the evaluation engine but not on the hot path.

---

### Domains

| Domain | Gate metric | Eval method | Min observation floor | What it governs |
|---|---|---|---|---|
| `feature` | IC Sharpe + FDR | Walk-forward | 20,000 bars | Intelligence vector features (migrated from feature_registry; IC Sharpe gate requires this minimum) |
| `feature_interaction` | IC Sharpe + FDR | Walk-forward | 2,000 bars | Interaction feature candidates before FeatureVector column (interaction-specific minimum) |
| `hmm_variant` | Held-out log-likelihood† | OOS holdout (train/test time split) | 5,000 bars raw - see Domain Vetting for the effective-N caveat | HMM architecture variants (covariance structure, obs vector, K). Trigger not yet cleared - see † |
| `ic_method` | Undefined - no real candidate exists; see Domain Vetting | Speculative: walk-forward substitution test vs. incumbent | Undefined | No governable scope identified as of 2026-07-06 - see Domain Vetting before routing anything here |
| `ensemble_strategy` | Ensemble IC (`ic_ci_lower`, stable walk-forward folds)‡ | OOS, via EnsembleICEngine | 1,000 bars | Ensemble weighting strategies (per-TF fold minimum) |
| `regime_model` | Three-stage cascade - structural pre-filter, orthogonality study, substitution test (see Domain Vetting) | Substitution test: Partial IC, causal comparison against corpus | Substitution test: N > 20,000 bars in the joint cell, raw - see Domain Vetting for the effective-N caveat | Stratification-dimension variants (per-symbol HMM, cross-sectional, percentile-rank, future axes). Row-grain (per-dimension vs. per-(dimension, regime_group)) is an open design choice, both fully specced - see Domain Vetting |
| `confluence` (anticipated, not in CHECK yet) | Six-gate ordered stack (marginal lift, BH-FDR, walk-forward, calibration, cost hurdle, OOS) via `concept_gate_stack` - see Domain Vetting | Mixed per gate (walk-forward, bootstrap, OOS) | 100 events (bootstrap CI requirement, gate 6) | Empirically validated joint conditions over primitives/analog neighborhoods - `docs/research/intel-confluence-detection-persistence-layer.md`. Added to CHECK once Phase 150/analog predictors produce real candidates (per that doc's Governance section), not before |

**Floor provenance (2026-07-06):** only two floors above trace to existing decisions - `feature`'s
20,000 bars (the live IC Sharpe gate) and `confluence`'s 100 events (that doc's bootstrap-CI gate).
The others (2,000 / 5,000 / 10,000 / 1,000) are `[initial_estimate]` round numbers with no
statistical-power derivation behind them. Seed each as an APR key carrying that provenance tag
(Invariant 7 names the keys) and recalibrate from power analysis - effective N under
autocorrelation, per Invariant 7's qualifier - when the domain gets real candidates. Do not let a
placeholder harden into a gate by repetition.

**`alpha_pattern` is retired, not listed as a row here** - see the retirement note under "Concept
Registry (Type 2)" above for the full reasoning. It does not get a Domains-table row because there
is nothing left for it to govern - a deletion, per Musk step 1, not a "reserved" placeholder.

**Anticipated seventh domain - embedding/analog-substrate recipes:** `docs/research/intel-analog-engine.md`
and todo 055 (Phase 148's `embedding_feature_registry`) both expect a `concept_registry` row per
embedding recipe (feature set, normalization, ordering). This does not fit any of the six domains
above. Name it at v3.2 (AnalogEngine) planning - `embedding_spec` or a widened `feature` reading  - 
and add it here before either consumer builds against an undefined domain (2026-07-04, F5.3).

Each row here becomes a `concept_gate_template` row at build time in the reference architecture, or
per-concept `concept_gate` (plus `concept_gate_stack` for `confluence`/`regime_model`) rows under
the MVP (the ten-table `concept_gate_template` itself is deliberately not part of the four-table
MVP - see "Minimal Viable Version" above; do not seed that table from this one until the MVP
graduates to the reference architecture). `feature_interaction`'s eventual promoted-survivor
storage from Interaction Factory (`docs/research/intel-feature-interaction-factory.md`) is already
covered by the `feature_interaction` row above - no separate `compound_primitive_registry` table
needed once Concept Registry exists.

**† `hmm_variant`:** held-out log-likelihood is the promotion gate once a variant exists; todo 026's Decision Gate is a separate, earlier build-trigger gate deciding whether a `candidate` row gets created at all - see Domain Vetting below for the full argument.

**‡ `ensemble_strategy`:** IC-based gate (`ic_ci_lower` via `EnsembleICEngine`), judged per-stratum by `ops_ensemble_weight_compare.py` - see "Per-stratum status (F2)" under Minimal Viable Version above for the full per-stratum-status resolution and current seeding status (todo 058).

---

### Domain Vetting - hmm_variant, ic_method, regime_model, confluence (2026-07-06, domain-vetting pass)

**Why this section exists.** The rule governing the live `domain` CHECK - seed only domains with
real candidates - answers one question: is this domain ready to hold rows today? It does not
answer a second, separate question the earlier pass conflated with it: is this domain's gate
shape, eval method, and schema fit fully designed, so there is zero design lag whenever it does
get real candidates? These four domains are vetted fully here without being seeded into the live
schema - the same separation `confluence` and `ensemble_strategy` already modeled (both fully
speced before either had a row). Invariants 7 (effective-N), 8 (implementation-version binding),
and 9 (compare-and-swap transitions) apply to all four exactly as they apply to `feature` and
`ensemble_strategy` - nothing below lowers that bar.

#### hmm_variant

**Trigger:** todo 026's Decision Gate (regime-IC separation query), not yet cleared to a build
decision. Step 1 already ran (2026-07-02) with real, asset-class-dependent findings this doc
already cites: SPY gap +0.024 (ambiguous zone), TLT gap −0.003 (deficient, inverted sign - the
HMM's trend labels carry no separation for TLT at all). The root-cause hypothesis for TLT points
at a factor-augmented HMM or `regime_group`-conditional variant as a competing explanation to
rolling refit (todo 026, 2026-07-04 update) - but building either is still gated on Steps 2-4 of
that decision gate, none of which have cleared. No `hmm_variant` candidate exists today.

**Gate shape:** scalar - fits `concept_gate` as designed, no extension needed. Held-out
log-likelihood, evaluated on a genuine time-based train/test split (not walk-forward - HMM
parameters are *fit*, not measured per-bar, so the eval method is a holdout comparison of two
fitted models' out-of-sample likelihood, not a rolling-fold stability check).

**Effective-N:** the existing 5,000-bar floor is raw and, per Invariant 7's qualifier, materially
overstates independent evidence for this domain specifically. HMM regime states are
autocorrelated by construction and additionally smoothed (`min_hold_bars`, live in
`regime_writer.py`) - consecutive bars in the same state are close to the *opposite* of
independent observations. No power analysis exists for this domain in any current doc (checked
todo 026 and `docs/research/stratification-dimension-unification.md`). At build time, recalibrate the floor from
the number of regime *transitions* observed in the held-out window (a proxy for independent
state-visits), not raw bar count - this is new statistical work, not a doc fix.

**Schema fit:** standard four-table MVP shape, unchanged. Implementation-version identity
(Invariant 8) for this domain is the HMM's `covariance_type`/observation-vector/`K` combination
plus `alpha.hmm.random_state` - already effectively versioned in `regime_writer.py`'s config, just
not yet stamped onto a `concept_registry.metadata` field, since no candidate row exists yet.

#### ic_method

**Real-candidate check (2026-07-06):** grepped `services/ic_engine.py` for a competing
correlation-calculation method - none exists. The live engine computes Spearman IC by ranking
both the feature and forward-return series (`rankdata`, `services/ic_engine.py:84` — verified 2026-08-01, was cited at `:70` — and every
call site keyed off it) and correlating the ranks. This matters for the domain's own founding
description, which listed "Spearman, rank-IC, HAC methods" as three candidates: **two of those
three names are the same computation.** Spearman correlation *is* Pearson-on-ranks - "rank-IC" is
not a distinct method from "Spearman," it is the same method under a second name. **HAC
(Newey-West) is also already live** (`alpha.ic.hac_max_lag`, migration 177), but as a
variance-correction on the IC-Sharpe standard error, not a competing way to compute the IC point
estimate itself - it corrects the *Sharpe estimator's* autocorrelation, it does not offer an
alternative to Spearman for the correlation itself. So the domain's original three-name
description was one live method, described twice, plus one live correction misfiled as a
competing method.

The one plausible near-term document reference - cross-sectional rank IC
(`docs/research/measurement-ic-engine.md`, "Addendum: Cross-Sectional Rank IC," 2026-07-03) - is not
an `ic_method` candidate either: it measures a genuinely different question (cross-sectional
relative-value edge across the 58-symbol universe on one bar, vs. this domain's time-series edge
for one symbol across bars), so it would run *alongside* the incumbent method, never promote or
demote against it. It answers "does a spread pay," not "is this a better way to compute the same
edge."

**Conclusion: no real `ic_method` candidate exists in this codebase's docs as of 2026-07-06.** Say
so plainly rather than inventing one to fill the row. The domain stays named in the schema comment
and Domains table as a placeholder for a genuine future case - a method that competes to replace
the incumbent computation for the *same* measurement question - but its gate metric, eval method,
and floor are explicitly speculative, not the confident "Walk-forward IC stability / 10,000 bars"
the row previously asserted as settled design. If a real candidate appears: the natural gate is a
substitution test against the incumbent (same shape as `regime_model`'s gate 2 below) - walk-
forward, OOS holdout, with an effective-N floor derived from that candidate's own autocorrelation
structure at that time, not carried over from this placeholder.

**Schema fit:** scalar, no heterogeneity to resolve - because there is nothing to resolve it
against yet.

#### regime_model

**Seeding sequence (folded in from todo 105, 2026-07-13):** this domain is seeded *after* the
Concept Registry MVP itself ships (`ensemble_strategy` is domain #1) - `alpha.regime.groups[].enabled`
today is an ungoverned flat APR boolean where this domain would instead carry a status enum with
an evidence-backed transition log, and Phase 144's own D-05 acceptance gate produces exactly the
promotion/demotion evidence `concept_transition_log` exists to store permanently and queryably
(as shipped, that verdict lands only in a SUMMARY.md and a todo file). Not urgent - no live
consumer reads `regime_model` lifecycle state today; this is a governance/auditability upgrade,
not a correctness fix.

**Trigger:** blocked on two things, both already flagged elsewhere in this doc and not resolved
here - Phase 144 shipping `regime_group` (needed for TLT's own clean cross-sectional comparison
and for any non-equity asset class's substitution test), and the v3.15 row-grain decision (below).
Unlike `ic_method`, this domain's gate mechanism is *not* speculative - `docs/research/stratification-dimension-unification.md`
already fully specs a three-stage cascade, live in that doc's "Governance" section, ported here:

1. **Structural redundancy pre-filter** (free - no query). If a candidate dimension already
   substantially overlaps an incumbent's existing observation dimensions, reject without running
   anything. Precedent already applied: Hurst/mean-reversion and autocorrelation-sign rejected
   against the incumbent HMM's `momentum`/`vol_of_vol` observation dimensions.
2. **Orthogonality study.** Correlation (Pearson on continuous score, or MI on discretized labels)
   between the candidate and every dimension already in production. Gate:
   `alpha.regime_stratification.max_correlation` - no default asserted yet; that doc correctly
   defers the number to the first real study rather than guessing.
3. **Substitution test (Partial IC).** `IC_partial = Corr(X_bar, Y_forward | S_candidate)`,
   computed on 3-5 symbols first, never a full-corpus run on an unvalidated candidate. Pass
   criterion: IC Sharpe increases more than 10% in at least one joint cell, with **N > 20,000 bars
   in that cell** - stated as raw bars in the source doc. **Effective-N correction (2026-07-06,
   applying Invariant 7 uniformly):** restate this as effective N, not raw bars, before it is
   actually used as a gate - a joint (existing-dimension, candidate) cell inherits the same
   autocorrelation the incumbent HMM already has, so 20,000 raw bars in a joint cell is a smaller
   number of independent state-visits than it looks. This is the same correction `hmm_variant`
   needs above, applied to a cell instead of a whole-corpus floor.

This is a genuine ordered gate sequence, not a scalar - the first stage is a free structural
check, the second is a correlation threshold, the third is the actual promotion evidence. It fits
`concept_gate_stack` (defined in the Governance Layer above), the same extension `confluence`
uses below, not `concept_gate`'s scalar columns. This is the second real domain that needs the
gate-stack shape - exactly the "wait until the pattern is proven twice" bar this project's own
reuse principle sets before extracting a shared mechanism, now met.

**Row-grain - both candidate shapes, fully specced, decision deferred to v3.15:**
`docs/research/stratification-dimension-unification.md` already found the concrete problem this creates: todo
026's Step 1 showed the incumbent HMM dimension is live-quality for equities and deficient for
rates - the *same* dimension needs a different status for different asset classes
simultaneously, which a single `concept_registry` row per dimension cannot represent. Two options,
both viable, neither chosen here:

- **Option A - one row per dimension.** `concept_registry` row: `domain='regime_model'`,
  `name='hmm_price_vol'`, one global `status`. Simple, matches every other domain's grain. **Loses
  the exact information todo 026 already found essential** - "active for equities, shadow for
  rates" cannot be represented in one status column; a global status would have to average across
  asset classes the same way todo 026's original pooled SPY+TLT query wrongly averaged away a real
  effect (this doc's own Step 1 finding). Would need a satellite fact table (analogous to how
  `ensemble_strategy` keeps its per-stratum champion in `ensemble_weights`, not `concept_registry`)
  to carry per-`regime_group` legitimacy outside the audit trail - but per that same
  `stratification-dimension-unification.md` doc's own reasoning, a dimension's per-asset-class legitimacy is
  itself worth an immutable transition log, not just an operational fact, which is a weaker fit for
  the ensemble_strategy resolution's pattern.
- **Option B - one row per (dimension, regime_group).** No new column needed - encode the grain in
  `name` itself (`hmm_price_vol__equity`, `hmm_price_vol__rates`), reusing the existing
  `UNIQUE (domain, name)` constraint. Each cell gets its own full lifecycle: independent `status`,
  independent `concept_gate_stack` rows, independent `concept_transition_log` entries. Directly
  represents todo 026's actual finding (HMM legitimate for equities, demotable to shadow for
  rates) with a real audit trail per cell - "why did we stop trusting the HMM for rates" becomes a
  queryable transition, not an inference from a fact table. Costs more rows as more
  `regime_group`s and dimensions multiply, but row count is cheap; audit-trail granularity is the
  scarce thing this whole system exists to provide.

**Recommendation, not a decision:** Option B fits this domain's actual empirical shape better  - 
`stratification-dimension-unification.md`'s own provisional lean agrees - but per the user's explicit
instruction, this is left for real ratification at v3.15 planning, not settled by assertion here.
Whichever is picked, the schema is a known quantity: Option A needs a new satellite fact table
(not yet designed, since it is not the recommended path); Option B needs zero new columns, only
the `name`-encoding convention stated above.

**Effective-N caveat:** applies at both the orthogonality-study and substitution-test stages, per
the correction above - carry it forward into whichever grain option is chosen.

#### confluence

**Trigger:** Phase 150 (Interaction Primitives) or the analog-predictor design surviving their own
gates first - `docs/research/intel-confluence-detection-persistence-layer.md`'s own Governance
section already states this; not re-derived here. No real candidate today, same as `ic_method`,
but unlike `ic_method` the gate mechanism is already fully designed in that source doc (v3.0,
2026-07-03) and simply needs porting into this schema, which is what follows.

**Gate shape:** the six-gate ordered stack from that doc, mandatory, in order - marginal lift over
the calibrated additive null, BH-FDR across the discovery batch, walk-forward stability,
calibration (reliability curve / Brier vs. base rate), cost hurdle (executable-return definition,
Invariant 1), OOS confirmation. This is the same `concept_gate_stack` shape `regime_model` needs
above - gate 1 is that source doc's own most load-bearing finding (a weak, uncalibrated additive
baseline would make every later gate's "lift" spurious), so the sequence is order-dependent, not a
set of independent scalar checks; `concept_gate_stack.gate_order` exists specifically to preserve
that.

**Effective-N:** that source doc already specifies its own correction - "effective-N via
temporal-clustering correction" on occurrence counts, because confluence occurrences cluster in
time (a condition true at bar T is usually still true at T+1). This is the same HAC/subsampling
discipline `ic_engine` already applies, applied to a count instead of a return series. The
100-event floor (gate 6, bootstrap CI) is stated against this corrected count, not raw
occurrences - already effective-N-aware by design, unlike the other three domains above, because
that source doc reasoned through this explicitly rather than inheriting a raw-bar floor.

**Decay:** confluence's decay mechanism (CUSUM or rolling-Brier-drift-triggered `active →
shadow_only` re-entry, symmetric re-promotion on recovery) is not confluence-specific - see the
domain-agnostic decay note under Invariant 5, and the retirement note above for why this replaces
any notion of an `alpha_pattern` domain built around "things that decay."

**Schema fit:** needs `concept_gate_stack`, same table `regime_model` needs - confirmed as the
second real consumer of that extension, alongside `regime_model`, and the one whose gate stack was
already fully designed before this doc's domain-vetting pass.

---

### Architecture Stress-Test

Restating the problem from scratch - catalog multiple intelligence layers, activate/deactivate
them, gate promotion/demotion/decay on evidence, and carry metadata about the logic/computational
parameters that make each reproducible - and auditing the codebase against it before trusting the
design above, rather than defending it. (An earlier draft of this audit misjudged two mechanisms
as live before checking properly; see the Revision Log for that correction - the method below is
the corrected one.)

#### Method

A table existing, a service file compiling, or a doc describing a mechanism does not make it
live. Liveness requires three checks, all required: row count and most recent timestamp in the
actual table; `systemctl status <unit>` for the producing/consuming service (disabled and not
loaded counts as not live, even with the unit file installed); and explicit
`ARCHIVED`/`v2.x`/`no live consumer` markers in root `CLAUDE.md` or `src/intelligence/CLAUDE.md`,
which this codebase maintains unusually well.

#### Inventory

**Live today** (fresh evidence within this project's few-days rebuild cadence):

| Domain | Evidence |
|---|---|
| `feature` | `feature_ic_scores`: 256,566 rows, last computed 2026-07-01. `feature_registry`: 61 rows, all `active`. `indicagent-feature-vector-pipeline` running for compute; `ic_engine` is oneshot/batch - freshness verified via output recency, matching how this project treats `ml-training`/`roll-batch` |
| `ensemble_strategy` | `alpha_ensemble_ic`: 572 rows, last scored 2026-07-04. `ensemble_weights`: 103 rows, last computed 2026-07-01. Todo 058's MVP-seed trigger fired 2026-07-04 |

**Fully designed, no real candidates yet:** `hmm_variant`, `regime_model`, `confluence`,
`ic_method` (see Domain Vetting above).

**Infrastructure present, zero current activity:** `signal_lineage` + `shadow_registry`'s
`_graduation_loop` (`src/intelligence/ai/AUTHORING.md`) - an append-only event ledger
(TimescaleDB hypertable) that a periodic loop reads, joined against outcomes, to compute Spearman
rho + p-value and write a promotion/demotion decision into `shadow_registry` (promotion: N >= 100,
rho > 0, p < 0.05; demotion: 3 consecutive 15-min cycles with rho < 0). `indicagent-lineage-writer`
is genuinely running, but `signal_lineage` has 0 rows because the producer
(`indicagent-alpha-swarm`) is disabled - the consumer is live, nothing feeds it. Not a live
domain, but the most instructive precedent found (used in Alternative 2 below).

**Confirmed dead** (0 rows or stale far beyond normal cadence, producing/consuming services
disabled and not loaded, all part of the archived v2.x I1-I7/alpha-swarm tier `CLAUDE.md` already
documents): `llm_model_scores`, `llm_calls` (stale), `setup_performance`, `ml_models`
(+`ModelRegistry`, `src/core/ml/registry.py`), `cis_weights`, `confidence_calibration`,
`pattern_reliability`, `swarm_agent_weights`, `signal_metrics`, `signal_metrics_ic`,
`calibration_curves`, `tod_multipliers`, `drift_monitor`, `drift_state`, `transform_graduation`,
`memory_calibration_spc`/`memory_calibration_promoted`, `memory_regime_transitions`,
`alpha_multiplier_shadow` (explicitly superseded by `signal_lineage`, dead and replaced),
`ml_discovery_runs`, `ml_data_quality_runs`. `shadow_registry` itself: 36 rows, all
`last_eval_at IS NULL` - never evaluated, reconfirming its exclusion.

**What this means for scope:** the live-plus-vetted domain count is unchanged from Domain Vetting
above - two live, four fully vetted. This audit's value is different: this codebase has solved
"catalog it, activate/deactivate it, gate promotion/demotion on evidence, track decay" at least
three times before - the v2.x I1-I7 aggregator's sprawl of a dozen-plus bespoke tables with no
shared schema or discipline, then the alpha-swarm/`shadow_registry`/`signal_lineage` redesign,
then `feature_registry` for v3.0. All three are real precedent for what to do and what not to,
used directly below.

#### Alternatives, evaluated against this evidence

**1. Current design** - one `concept_registry` table, `domain`-partitioned, `concept_gate_stack`
satellite for ordered-sequence gates.

**2. Event-sourced ledger, no materialized status column.** The strongest version of this
alternative already exists in this codebase, for exactly this problem: `signal_lineage` +
`_graduation_loop` - nothing updated in place, a periodic job derives a decision from the
immutable log and writes it into `shadow_registry`'s status columns. But APR's own `config_state`
(mutable cache) + `config_history` (immutable hypertable) split - architecturally identical in
shape to `concept_registry.status` + `concept_transition_log` as already designed - is the
stronger precedent this project actually follows, and it is a hybrid, not pure event-sourcing:
`ConfigService.set()`'s `SELECT config_state FOR UPDATE` plus optimistic-version check is exactly
Invariant 9's compare-and-swap already in production, not a novel patch. Abolishing the
materialized status column entirely would depart from this project's own dominant, proven pattern
in exchange for a guarantee (status can never drift from the log) that APR's version-checked write
already provides in practice, with no observed drift bugs anywhere in this codebase.

**Verdict: keep the materialized status column and CAS write. Adopt the narrower real lesson -
declare `concept_transition_log` (and any future per-cycle evidence table) as a TimescaleDB
hypertable**, matching `config_history`/`llm_calls`/`signal_lineage`'s established pattern
(applied at §concept_transition_log below).

**3. Graph model**, for `concept_dependency`/`concept_correlation`/`concept_regime_ic`, already
node-and-typed-edge shaped. This project has no live graph database anywhere in `src/`/`services/`
- the only graph tooling is `gsd-graphify`'s planning-document graph, an unrelated system.
Postgres already answers every query this data shape needs (`WITH RECURSIVE` over
`concept_dependency` handles "what breaks if X is deprecated" natively) at a scale (tens to low
hundreds of concepts, low thousands even at Interaction Factory's hypothetical future scale) far
below where a dedicated graph engine earns its keep.

**Verdict: reject the engine, adopt the model conceptually** - keep the edge tables relational,
query with recursive CTEs, do not add a graph database.

**4. Fully separate per-tier storage, unified only by a shared protocol, no shared tables.** Not
hypothetical - this is what the v2.x I1-I7 tier actually was: a dozen-plus bespoke tables, each
hand-shaped for one narrow scoring need, no shared schema or discipline. Per
`docs/operations/operations-database.md`'s truncation script, that entire tier was wiped, not
migrated forward. Sprawl without shared discipline is the documented, checkable outcome the last
time this codebase actually tried this.

**Verdict: reject.** The "one schema, shared discipline" ambition is the corrective response to a
failure mode this codebase has already lived through, not unearned complexity.

**5. Merge Concept Registry into APR, or vice versa**, given parameters are arguably part of a
concept's identity. APR's lifecycle (seed → operator → ml_learned → user_override) superficially
resembles `candidate → shadow_only → active → deprecated`, and its schema/state/history split
already exists. But APR governs *which value is currently best for a setting whose existence is
already settled* (an RSI period always exists as a tunable; the question is only its number);
Concept Registry governs *whether a candidate deserves to exist as something the system trusts at
all*. Forcing 425 mostly-scalar APR parameters through a p-value/FDR/OOS gate 99% of them don't
need would be the same ill-fitting-shared-table smell this doc's review lens exists to catch, in
the opposite direction. The one genuinely useful precedent found in the dead-mechanism inventory:
`src/core/ml/registry.py`'s `ModelRegistry` already answers "where do a concept's computational
parameters live" cleanly - a thin identity+status row pointing at MLflow, which holds the actual
parameters/metrics/artifact, never duplicating them.

**Verdict: reject merging as one schema. Adopt the reference-not-duplicate pattern the
`ModelRegistry` precedent demonstrates**, implemented as `metadata.apr_namespace` (§concept_registry
above) and Invariant 8.

#### What this did not change

No domain was added to the live `domain` CHECK or the Domains table - every newly-inventoried
mechanism above is confirmed dead or inactive end-to-end, and none has real candidates. If any
comes back to life (a producer service re-enabled, real rows accruing), re-run this liveness check
before deciding whether it earns a domain.

---

### Feature Registry migration

`feature_registry` migrates into `concept_registry` at build time as `domain = 'feature'`. The separation is historical, not structural:

- **Dataclass alignment gate** - implemented per domain in ConceptRegistryService
- **Parent-cascade trigger** - application-layer logic for `domain = 'feature'`
- **SQL columns vs JSONB** - `formula_short`, `normalization`, `linear_ready`, `tier`, `group_name` etc. move to `metadata JSONB`; actual consumers (ic_engine, ensemble_trainer) load into Python at startup, no SQL-level consumers exist
- **Decay tracking** - `feature_registry`/`feature_ic_scores`'s existing `is_decaying`/`decay_detected_at`/`recovery_eligible_at` columns map onto `concept_eval_state.decay_ratio` + `concept_gate.decay_floor` at migration time. Wiring them is owned by the IntegrityMonitor design (`docs/research/measurement-governance-monitor.md`, ROADMAP Phase 143); todo 015, which previously owned this, was superseded and absorbed there 2026-07-04 (`.planning/todos/completed/015-feature-vector-lifecycle.md` - a prior version of this bullet pointed at the todo as pending/deferred). Phase 143 wires decay detection for the domain that exists *today*; Concept Registry's `decay_floor` is the same mechanism generalized to every domain, for whenever this migration actually happens.

`FeatureRegistryService` becomes `ConceptRegistryService` loading `domain = 'feature'`. Migration proves the design with a live domain on day one.

Feature ideas and interaction candidates enter as `domain = 'feature_interaction'` at `candidate` status, earn IC promotion, then graduate to `domain = 'feature'` when they get a FeatureVector column. Only candidates that survive Interaction Factory's raw screening (`compound_ic_scores`, outside Concept Registry's scope) enter `concept_registry` at all - the ~30,000 raw pairs never get a `concept_registry` row, only the hundreds that clear the initial IC bar do.

Shadow Registry (`shadow_registry`) is **not** migrated - see Registry Taxonomy above.

---

### Build sequence (reference architecture, for when it's warranted)

1. Governance layer (concept_registry, concept_gate_template, concept_gate, concept_eval_run, concept_eval_state, concept_transition_log)
2. Migrate feature_registry → `domain = 'feature'`; seed `thesis` and `failure_mode` annotations for all 61 features
3. `concept_regime_ic` and `concept_correlation` - evaluation engine writes from day one, keyed by `eval_run_id`; feeds ensemble immediately
4. `concept_annotation` - human knowledge layer live; AI and empirical annotations accumulate
5. `concept_dependency` - populated at concept creation; gate checks dependencies before promotion
6. Candidate staleness job - enforces `max_candidate_age_days` per domain from day one, so candidate rot never accumulates in the first place
7. Dashboard: single concept view shows all ten tables - governance status, annotation history, regime IC trend, correlation matrix, dependency graph

---

### Revision Log (2026-07-01 / 2026-07-02)

Purely historical - the pre-2026-07-06 design-review passes, kept as changelog. Nothing in the
live spec above depends on reading this; it exists so a later reader can see how the design
arrived where it is, not to restate current rules.

#### Refinements vs. original 2026-06-28 design (critical review, 2026-07-01)

1. **Eval history was being destroyed.** `concept_eval_state` was "overwritten each cycle - not audit data" - a concept decaying slowly toward (but never crossing) its demotion threshold had its entire trajectory silently lost. Fixed: `concept_eval_run` + `eval_run_id`-keyed `concept_regime_ic` rows preserve full history; `concept_eval_state` is now explicitly just a cache.
2. **No corpus-build provenance.** Corpus rebuilds happen every few days in this project; nothing tied a promotion/demotion decision to which rebuild produced the numbers behind it. Fixed: `concept_eval_run.corpus_build_ref`.
3. **No portfolio-level FDR control.** Interaction Factory alone plans ~30,000 candidates; each gate check was an independent p<0.05 test with no batch-level false-discovery correction, the same look-elsewhere-effect problem the IC engine already solved at the corpus level (Phase 142A) but that could creep back in here. Fixed: `concept_eval_run.n_candidates_in_run` + `fdr_alpha`.
4. **Redundancy was asserted, not computed**, and implicitly cross-domain (incoherent - an `alpha_pattern` and an `hmm_variant` have no comparable correlation). Fixed: `concept_correlation` table, within-domain only.
5. **Schema couldn't survive its own first customer.** One gate row per concept doesn't scale to 30,000 auto-generated `feature_interaction` candidates. Fixed: `concept_gate_template` (domain default) + optional `concept_gate` (per-concept override), resolved via `COALESCE`.
6. **Unbounded candidate accumulation.** Nothing aged out a `candidate` created and never evaluated - same "notebook nobody reads" failure the whole system exists to prevent, just relocated into a DB row. Fixed: `max_candidate_age_days` auto-demotion with `trigger_reason='candidate_timeout'`.
7. **Shadow Registry's exclusion was initially flagged as an oversight, then confirmed correct.** First pass proposed migrating it in as `domain='plugin'` since its gate (`n>=100`, `bootstrap_ci_lower(pnl_r)>0`) maps directly onto `concept_gate_template`'s `bootstrap_ci` method. Checked against live state: no systemd unit runs `shadow_auditor`/`shadow_validator`/`alpha_swarm`, `last_eval_at` is NULL on all 36 rows, and it governs the v2.x I1-I7 plugin/swarm system CLAUDE.md documents as archived (Feature Factory replaces I1-I4; I5-I7 archived). There is no live `plugin` or `swarm_agent` domain in v3.0 to migrate it into. Correction: Shadow Registry stays separate and legacy; revisit only if I7 plugins or swarm agents return to active use.
8. **Applied "when to add a registry" rule against the design itself and it failed.** One live consumer, six of seven domains unbuilt, and the complexity in items 1-6 above was justified by a second unbuilt system's imagined scale. Nine-table design demoted to reference-only; four-table Minimal Viable Version defined as the actual build target, deferred until a second domain has real candidates.
9. **Promotion/demotion needed to account for autonomous self-improvement, not just human research.** Added six invariants (see "Promotion/Demotion Design for Autonomous Self-Improvement" above) governing proposal/decision separation, re-evaluation integrity, proposal budgets, proposer track-record measurement, demotion symmetry, and mandatory `shadow_only`.
10. **This doc itself was briefly split** into an index (this file) + a satellite spec (`concept-registry.md`) to avoid duplicating the schema in two places, then re-unified same day - the split solved a real problem (drift between the todo and this doc) but recreated it in a different shape once a separate satellite file existed. Re-merged: this doc is the single, unified home for Concept Registry; Feature Registry, Controlled Vocabulary, and Interaction Factory remain separate sibling docs (own history, own build gate), referenced here with a summary and a link, not duplicated.
11. **APR (Type 1) was appearing as a peer row in "What Exists" and "Full Comparison," and `concept_registry.domain` had an unnecessary runtime dependency on Controlled Vocabulary.** Both trimmed: APR reduced to its origin-analogy mention in Registry Taxonomy (it was never designed to have gates or lifecycle states, so a feature-by-feature comparison was comparing incompatible things); `domain` now uses a plain `CHECK` constraint like `status` does, no dependency on a separate unbuilt system to validate 7 fixed values.
12. **Interaction Factory's own design was unclear about what it actually was and whether it was justified**, which fed two circular-reasoning references in this doc (`concept_gate_template` and `concept_correlation`'s rationale, both citing IF's 30K-candidate scale to justify reference-architecture tables while IF itself was unbuilt and its need unproven). Rewrote `intel-feature-interaction-factory.md`: reframed from "a service" to "a candidate-generation strategy" that reuses the existing IC engine + Concept Registry pipeline rather than duplicating it; added an evidence-based build trigger (documented atomic-feature IC saturation, not just readiness); fixed a real statistical gap (no explicit batch-level FDR correction in the stated promotion rule - naive `p<0.05` across 30K candidates produces ~1,000-1,500 false discoveries by chance alone) and an unstated look-ahead risk (rolling correlation window must be explicitly causal). This doc's two circular references now note explicitly that they describe conditional, not-currently-justified reference material.

What was already right and left unchanged: `trigger_reason` in `concept_transition_log` (not `status`) is the correct place to distinguish "demoted after decay" from "never promoted" - resisted the urge to add complexity to the status enum.

#### Second review pass (2026-07-01, later same day - findings from cross-checking against work done since the morning refresh)

13. **intel-10 is domain #2 arriving.** The confluence detection/persistence layer
    (`docs/research/intel-confluence-detection-persistence-layer.md`, written the same day)
    independently specced a full lifecycle-governed object - exactly what this registry
    generalizes. Anti-divergence rule and status-enum mapping added at the MVP build trigger
    above. Without this cross-reference, the two designs would have produced the bespoke
    per-domain duplication this registry exists to prevent.
14. **`baseline_metric` had a winner's-curse flaw.** Raw promotion-time metric as the decay
    denominator fires false demotions on regression-to-the-mean. Fixed inline at
    `concept_eval_state`: store the shrunk estimate (feature-scoring-beyond-ic §0b machinery).
15. **The evaluation engine is load-bearing and unspecified.** All six self-improvement
    invariants delegate to "the deterministic evaluation engine" - no doc names the service,
    its cadence, its Ring placement, or oneshot-vs-daemon shape. The ten tables are storage;
    the engine is the system. **Two-thirds resolved (2026-07-04, cluster review F5.1):** intel-14
    has since decided this for `domain='feature'` - no daemon, no module; the transition writer is
    a post-run hook inside `ic_engine` calling a narrowly-scoped registry service method,
    explicitly reasoned from this doc's invariant 1 (status changes can only happen through a
    deterministic code path with no LLM in it) and adopted into ROADMAP Phase 143 2026-07-03. For
    `ensemble_strategy`, the engine already shipped in practice: `ops_ensemble_weight_compare.py`'s
    win-decision gate is the deterministic code path invariant 1 requires. The original "likely a
    `BaseBatch` oneshot" guess is superseded - status changes belong at the end of the measurement
    run that produces new evidence, not on an independent timer. Still open: whether every future
    domain's engine takes this same end-of-run-hook shape, or whether some domain's eval cadence
    genuinely needs its own scheduled scan.
16. **`corpus_build_ref` doesn't need inventing** - the live CorpusManifest system is the
    identifier. Noted inline at `concept_eval_run`.
17. **`regime_scope` needs a dimension qualifier** before additional stratification dimensions
    land (`volatility_regime` etc.) - bare labels are only unambiguous today by accident.
    Noted inline at `concept_gate`.
18. **Pipeline-level methodology changes are invisible to this schema by design - and that's
    fine, but only because a sibling doc now covers them.** `concept_transition_log` audits
    per-concept state changes; a change to a `concept_gate_template` (or to the eval
    methodology itself) affects every concept in a domain and shows up in no per-concept log.
    That grain is covered by `docs/plans/methodology-change-ledger.md` (created the same day):
    gate-template changes and eval-methodology changes get ledger entries there. The two are
    complementary grains of the same audit discipline, not alternatives.
19. **Naming inconsistency with intel-feature-interaction-factory.md fixed** - this doc wrote
    `xf_prod__body_ratio__volume_z` (double underscore after operation); the convention is
    `xf_prod_body_ratio__volume_z` (single after operation, double between parents).

#### Third review pass (2026-07-02 - findings from the day's ensemble/regime architecture review and roadmap surgery)

20. **The "domain #2 = `alpha_pattern`" assumption was checked against a same-session roadmap
    change and didn't hold up.** Phase 142B.1 (Ensemble Weighting Methodology, inserted into
    `ROADMAP.md` this session) gives `ensemble_strategy` four concrete, human-authored candidates
    (E1-E4) with an already-planned eval mechanism (Phase 142A's `EnsembleICEngine`), a shorter
    dependency chain than `alpha_pattern`'s (which needs `alpha_events` to stabilize and an
    unbuilt autonomous proposer), and - because the candidates are human-authored - a chance to
    validate the MVP schema without simultaneously having to get the six self-improvement
    invariants right for an AI proposer. Reassessed in "Minimal Viable Version" above:
    `ensemble_strategy` may be domain #2 in practice, and building against it first is lower-risk
    than building against `alpha_pattern` first regardless of which arrives sooner.
21. **`ensemble_strategy` and `hmm_variant` Domains-table gate metrics were stale guesses,
    corrected against concrete decisions made this session** - see Domains table footnotes (†, ‡).
    `ensemble_strategy` was "Realized Sharpe" (guessed before any mechanism existed); actual
    mechanism is IC-based (`ic_ci_lower` via `EnsembleICEngine`), consistent with every other
    domain's IC-based gate. `hmm_variant`'s "held-out log-likelihood" is still right for comparing
    a *built* variant, but todo 026's Decision Gate (regime-IC-separation query) is a distinct,
    earlier build-trigger gate the original row didn't distinguish.
22. **The IOHMM and factor-augmented HMM variants (`docs/plans/archive/2026-07-01-regime-stratification-alternatives.md`) turned out to
    have a real structural dependency on `regime_group` (Phase 144, renumbered 2026-07-04  - 
    originally 151) that neither doc had stated.**
    IOHMM's exogenous inputs (VIX, breadth, yield spread) are literally Phase 144's signal-module
    outputs (`breadth_vol.compute()`, `curve_credit.compute()`); the factor-augmented variant's
    "cross-sectional factor returns" reuses Phase 144's peer-resolution mechanism
    (`_resolve_group_symbols`) rather than needing a bespoke factor definition. Captured in that doc's HMM Variants section, not just here - this
    is a content fix to the source doc, not a pointer to it.

#### Dependency

Defer until a second domain has real candidates ready to govern - no longer assumed to be `alpha_pattern` by default; see item 20 above. `ensemble_strategy` (Phase 142B.1) is the more concrete near-term candidate and the lower-risk one to build the MVP against first. Build the Minimal Viable Version informed by whichever domain actually gets there first.

**Status update (2026-07-04):** Phase 142B.1 is complete - the build trigger has fired. Originally
tracked at todo 058, now at `.planning/todos/pending/112-concept-registry.md` (058 closed
2026-07-13 as a duplicate, kept as frozen historical record); do not let this defer
indefinitely (2026-07-04 cluster review, F1).

---

## When to Add a New Registry

A registry earns its cost when all three are true:

1. **Mutable membership** - the set can grow, shrink, or change state over time
2. **External consumers need enumeration** - dashboard, SQL, or ML pipelines discover members without importing Python
3. **Metadata enrichment has actual consumers** - labels, descriptions, groupings, or gates are read by something concrete

Not worth it for: mathematical constants, schema identifiers, internal codes no consumer enumerates, fixed sets that never change.

---

## Full Comparison

Type 2/3 registries only, for the same reason as "What Exists" above - APR isn't a peer on this axis. For APR's own gate/audit/service model, see `docs/foundation/adaptive-parameter-registry.md`.

| | Shadow Registry (legacy, not migrating) | Controlled Vocabulary | Concept Registry |
|---|---|---|---|
| Identity table | `shadow_registry` | `controlled_vocabulary` | `concept_registry` |
| Gate params | in registry row | - | `concept_gate_template` (domain default) + `concept_gate` (per-concept override) |
| Eval provenance / batch FDR | - | - | `concept_eval_run` - ties results to corpus build, tracks batch size for FDR |
| Eval state | in registry row | - | `concept_eval_state` (latest-cycle cache only, not history) |
| State audit log | `shadow_transition_log` | - | `concept_transition_log` (includes `candidate_timeout`) |
| Knowledge - thesis/failure modes | - | - | `concept_annotation` |
| Knowledge - dependency graph | - | - | `concept_dependency` |
| Knowledge - regime IC history | - | - | `concept_regime_ic` - new row per `eval_run_id`, full trend preserved |
| Knowledge - redundancy evidence | - | - | `concept_correlation` - within-domain pairwise correlation, not asserted |
| OOS enforcement | No | - | Yes - `gate_eval_method` required |
| Regime-conditional gate | No | - | Yes - `regime_scope` |
| Sustained promotion | No | - | Yes - `min_promotion_consecutive` |
| Decay tracking | No | - | Yes - `decay_ratio` vs `baseline_metric`, full history via `concept_regime_ic` |
| Candidate staleness | No | - | Yes - `max_candidate_age_days` auto-demotes unevaluated candidates |
| Lineage | No | - | Yes - `parent_concept_id` |
| Redundancy | No | - | Yes - `redundancy_group`, scoped within-domain, displacement gated on `concept_correlation` evidence |
| Scales to 10K+ candidates | No (36 hand-registered, legacy) | N/A | Yes - `concept_gate_template` means most candidates need zero manual gate config |
| Enable/disable | `is_shadow` bool | - | `enabled` independent of `status` |
| Service | Shadow auditor | `VocabularyService` | `ConceptRegistryService` |
| Loading | Eager | Eager | Active/shadow eager; candidates lazy |
| Dashboard | - | `/api/vocabulary/{ns}` | `/api/concepts/{domain}` |
