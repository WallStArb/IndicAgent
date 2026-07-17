# Phase 161: Controlled Vocabulary System - Context

**Gathered:** 2026-07-16
**Status:** Ready for planning

<domain>
## Phase Boundary

Build the three-table Controlled Vocabulary core infrastructure (`controlled_vocabulary` /
`vocabulary_group` / `vocabulary_group_member`) and `VocabularyService`, seeding **six live
namespaces** (revised from five — see D-01/D-04, `regime_cross_sectional` splits into two):
`regime_hmm`, `regime_cross_sectional_equity`, `regime_cross_sectional_rates`, `timeframe`,
`asset_class`, `tier`. Ship the column-backed drift audit as an importable module + oneshot CLI
(revised from "an existing auditor daemon" — see D-09, every candidate auditor is verifiably
dead) and a `/api/vocabulary/{namespace}` endpoint. Archived-SLA namespaces (`signal_outcome`,
`entry_type`, `signal_status`, `session_type`) are explicitly deferred per the design doc's own
"on demand later" staging — not part of this build.

This phase's design is fully decided going in: a 2026-07-06 Fable 5 review pass already
inverted the staging order, redesigned the divergence check, and ran the doc through CLAUDE.md's
four design-gate questions with a "build-ready" verdict. Discussion for this phase surfaced two
scope questions the design doc leaves genuinely open (tag_vocabulary's relationship to this
system, and the drift-audit's host daemon), a substantial architecture discussion about
reuse/extensibility, and — during the plan-phase research pass — two further open questions a
second Fable review resolved (`docs/research/fable-2026-07-16-controlled-vocabulary-open-questions-review.md`,
findings V1-V5): the live `regime_cross_sectional` column actually carries two distinct taxonomies
sharing one column (equity + rates), and no auditor-family systemd unit is currently running on
this host, so the drift audit ships as a module + oneshot rather than riding a "live" daemon that
turned out not to be live. None of this reopens the schema shape or staging order, which stay
locked as designed.

</domain>

<decisions>
## Implementation Decisions

### Scope: exactly the 6 live core namespaces, nothing archived
- **D-01 (revised 2026-07-16 per Fable review V1):** Seed `regime_hmm`,
  `regime_cross_sectional_equity`, `regime_cross_sectional_rates`, `timeframe`, `asset_class`,
  `tier` — six namespaces, not five. `regime_cross_sectional` splits into two: live verification
  found `market_regimes.regime_label` actually carries 15 distinct values across two independent
  `regime_group` taxonomies (`equity`: 9 labels, `rates`: 6 labels, a completely different
  curve-shape × width shape) sharing one column. One 15-code namespace would violate this
  project's Label Identity Invariant (a label is only meaningful paired with its dimension —
  `stratification-dimension-unification.md`) and recreate the exact pre-141.1
  `feature_ic_scores.regime` mixing bug inside the registry meant to prevent it. Prefer explicit
  `_equity`/`_rates` suffixes over an implicit bare `regime_cross_sectional` = equity — renaming
  is free today (zero consumers exist), expensive later. `signal_outcome`/`entry_type`/
  `signal_status` (archived SLA-adjacent PG ENUMs) and `session_type` (no live column) stay "on
  demand later" — seeding archived vocabularies before a live consumer exists is inventory nobody
  consumes.

### tag_vocabulary: explicitly OUT of scope, decided not deferred
- **D-02:** Do **not** fold `tag_vocabulary`/`instrument_tags` (live, 71 tags, migrations
  227/228) into `controlled_vocabulary` in this phase or any future one. This is a closed
  decision, not an open question left for later — the canonical CV doc itself flags this as
  unresolved, but cross-referencing the wider research answers it:
  - `tag_vocabulary` (tag, category, description) and `controlled_vocabulary` (namespace, code,
    label, description) ARE the same vocabulary-definition shape — but `instrument_tags`
    (symbol, tag, weight, source, evidence, assigned_at) is a fundamentally different relationship:
    confidence-weighted, falsifiable-hypothesis, multi-valued entity assignment. It's the only
    table of that shape in the entire schema (verified live, `\dt` scan) — generalizing an
    assignment mechanism for a population of one would be the same "don't build infrastructure
    for unproven ideas" mistake already avoided on todo 080's E-candidate queue.
  - `docs/research/stratification-security-classification-hierarchy.md`'s Layer 2 design
    (already Fable-reviewed, build-ready pending the individual-equities milestone) commits to
    extending `tag_vocabulary` **in place** — a single `parent_tag ADD COLUMN` — explicitly
    because `instrument_tags` "already IS the soft-membership system; building a second one
    would fork provenance and calibration machinery for zero new capability." Folding
    `tag_vocabulary`'s definition rows into `controlled_vocabulary` now would have to be
    half-undone (or complicate the FK target) when that Layer 2 work lands.
  - The 2026-07-04 Fable cluster review (F11) already confirmed Controlled Vocabulary's
    decoupling from its sibling systems is "verified clean, both directions" — this phase
    reaffirms the same boundary against `tag_vocabulary` specifically, for the epistemic reason
    above (authoritative/flat vocabulary vs. weighted/falsifiable hypothesis are different kinds
    of rows; forcing both through one table makes the schema "lie about what kind of row this
    is" — a direct data-integrity violation, not a style preference).

### Vocabulary groupings to seed (the "hierarchy" that already fits the 3-table shape)
- **D-03:** `regime_hmm`'s 5 labels are not a single ordered scale — seed two independent,
  overlapping `vocabulary_group` groupings so a label can belong to both simultaneously:
  - `trending` = {trending_down, trending_up}, `transition` = {transition_down, transition_up}
  - `bullish_bias` = {transition_up, trending_up}, `bearish_bias` = {transition_down, trending_down}
  - `ranging` stays ungrouped (a group of one adds no query value)
- **D-04 (re-scoped 2026-07-16 to `regime_cross_sectional_equity` per D-01/Fable review V1):**
  This namespace's 9 labels (`{low,mid,high}_{bull,neutral,bear}`) are two crossed facets, not a
  tree — seed both dimensions as independent groups so every label belongs to exactly one
  vol-tier group AND one direction group:
  - Vol-tier: `low_vol`/`mid_vol`/`high_vol` (3 members each)
  - Direction: `bull`/`neutral`/`bear` (3 members each)
  - This is precisely the multi-membership case the design doc's "Is three tables the minimal
    shape?" section defends — collapsing to a single `parent_code` or `groups TEXT[]` column
    cannot represent a label belonging to two independent groupings at once.
- **D-04b (new, `regime_cross_sectional_rates`):** This namespace's 6 labels
  (`{flat,steep,inverted}_{tight,wide}`) apply the same crossed-facet pattern to a different
  taxonomy shape — curve-shape groups `flat`/`steep`/`inverted` (2 members each) and width groups
  `tight`/`wide` (3 members each). Verified live: 618k-19k rows per label, written through
  2026-07-07 (batch-stale, consistent with the in-flight 143.1 corpus re-run, not a fault).
- **D-09 (drift-audit host, revised from "existing auditor daemon"):** Ship the column-backed
  drift audit as an importable module (`src/config/vocabulary_drift.py`, beside
  `vocabulary_service.py`) plus a thin D-06 oneshot CLI entrypoint, persisting to
  `integrity_monitor` (`monitor_type='vocabulary_drift'`) — not wired into any existing auditor
  daemon. Verified live via `systemctl` on this host: every auditor-family unit
  (`bar-auditor`, `ml-data-quality`+timer, `service-auditor`, `shadow-auditor`+timer,
  `signal-auditor`) is `disabled`/`inactive dead`; only `ctx-writer`, `feature-vector-pipeline`,
  and `lineage-writer` are `active running`. `data_quality_auditor.py`'s own 4 checks query
  archived v2.x tables (dead subject matter on top of a dead unit); `bar_auditor.py`'s domain
  (OHLCV gap detection) and `service_auditor.py`'s domain (service liveness, never table content)
  are both SoC mismatches even setting liveness aside. Chain the oneshot into
  `scripts/ops/corpus/ops_corpus_pipeline_run.sh` — the operator-invoked event that actually
  produces new regime labels — and run it once at phase end as the seed migration's own
  verification. This adds zero DAG nodes/daemons/units, preserving the design doc's "not a new
  service" intent without pretending a dead daemon is a live host. Also add a `SELECT DISTINCT
  regime_group` guard in the same audit, comparing against the namespace suffixes the registry
  knows, so a future third `regime_group` (e.g. `credit`) can't drift past both D-04/D-04b queries
  silently.
- **Operator decision, explicitly NOT bundled into this phase's build (per Fable review V3c/V5):**
  making the drift audit run on a schedule (rather than only when the corpus pipeline happens to
  run) requires enabling a systemd unit/timer on this production host — every auditor unit and
  all 10 timers are currently disabled. That is a production-operations sign-off for the project
  owner, separate from this phase's code, and is not decided here. Separately flagged, also not
  this phase's problem: `service_auditor` itself being dark means nothing currently watches the
  three services that are running.

### Architecture: extensibility and reuse — interface-level, not schema-level
- **D-05:** `VocabularyService` is a library any daemon embeds locally (same pattern as
  `ConfigService`/APR) — cached at startup, zero DB calls on the hot path. It does **not**
  become a new DAG node or network service. This is not a new call; it's the design doc's own
  DAG-gate-check conclusion ("no compute daemon consults it to validate its own output"),
  restated here because the discussion specifically probed "DAG microservice reuse."
- **D-06:** The standing rule for adding future namespaces (already established in
  `docs/research/concept-governance-registries.md`'s "When to Add a New Registry" section,
  applies identically here): a namespace earns its place when (1) membership is mutable, (2)
  external consumers need enumeration without importing Python, and (3) metadata enrichment
  (labels/descriptions/groups) has real, concrete consumers. Not worth it for fixed sets no
  consumer enumerates. Document this test explicitly alongside `VocabularyService` so the next
  candidate vocabulary gets checked against a rule, not a vibe.
- **D-07:** Do NOT build a shared abstract base class ("RegistryService") generalizing
  `VocabularyService` and `ConceptRegistryService`. This codebase's own precedent
  (`Float32ChunkAccumulator`, generalized into `_batch_utils.py` only after a second real
  consumer needed it — todo 087) is the rule to follow: extract shared code the second time a
  shape is proven needed, not preemptively. Right now there is exactly one `VocabularyService`
  instance. `docs/research/concept-unified-registry.md`'s "Full Comparison" table already lists
  `VocabularyService` and `ConceptRegistryService` as siblings sharing a family resemblance
  (named thing, looked up by any consumer, governed writes) without sharing a schema or base
  class — that's the house style, confirmed independently across two canonical docs.
- **D-08 [informational, not in scope]:** `docs/research/stratification-dimension-unification.md`'s
  `StratificationDimension` `Protocol` declares `labels: list[str]  # from Vocabulary` — meaning
  Controlled Vocabulary is the anticipated label-set authority for future stratification-dimension
  providers (Phase 144/145 territory, itself gated on the current corpus re-run). No code in this
  phase should build toward that integration; noted here so a future implementer doesn't have to
  rediscover the connection. Same doc independently validates the "one interface, many pluggable
  providers, evidence-promoted" pattern this discussion converged on, citing the archived v2.x
  `PatternPlugin` + `validate_tier()` system as prior art — real precedent, not a novel proposal.

### Claude's Discretion
- **Drift-audit host daemon:** the design doc says the periodic column-backed drift check should
  "ride an existing auditor daemon, not a new service" but doesn't name one. `data_quality_auditor.py`
  is the natural structural fit (already a periodic `BaseDaemon` computing quality scores and
  firing alerts via the same `_check_outliers`/`_maybe_publish_alert` shape the drift check
  needs) — use it unless research surfaces a reason not to. Low-stakes, not worth a locked
  decision.
- Everything else — exact migration numbers, `VocabularyService` method signatures, exact
  label/description text for the 5 namespaces, API route placement — follows the design doc's
  own fully-specified schema and staging section as-is.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Design doc (primary source — read first)
- `docs/research/concept-controlled-vocabulary.md` — the full design: 3-table schema,
  `VocabularyService` interface, three-way ENUM divergence check, column-backed drift audit,
  staging (core build vs. on-demand-later), APR analogy, design gate check (build-ready verdict).
  Treat as authoritative for HOW; this CONTEXT.md only adds/corrects the scope decisions above.

### Registry family — extensibility/reuse rules cited in D-05/D-06/D-07
- `docs/research/concept-governance-registries.md` — umbrella framework; "When to Add a New
  Registry" (the 3-part test, D-06); Registry Taxonomy and "Full Comparison" table (confirms
  `VocabularyService` is already a documented peer alongside `ConceptRegistryService`, D-07);
  F11 of the linked cluster review confirms CV/Concept-Registry decoupling verified clean.
- `docs/research/concept-unified-registry.md` — "When to Add a New Registry" (§1271), "Registry
  Taxonomy" (§110), "Renaissance Framing" / "What Jim Simons Would Demand" (§23-49) — the
  evidentiary/audit-trail discipline this discussion's "flexible and scalable" framing resolved
  against.
- `docs/research/fable-2026-07-04-concept-registry-cluster-review.md` — F11: Controlled
  Vocabulary/Concept Registry decoupling "verified clean, both directions," cited in D-02.

### tag_vocabulary / instrument_tags separation — cited in D-02
- `docs/research/stratification-security-classification-hierarchy.md` — Layer 2 design
  (§"Layer 2 - custom soft taxonomies: one column on the live tag system"), the taxonomy-vs-
  membership and authoritative-vs-hypothesized separations that justify keeping `tag_vocabulary`
  and `controlled_vocabulary` permanently distinct.
- `docs/research/stratification-governance-registries.md` — sibling umbrella (stratification/
  classification cluster), explicitly kept thin by design; confirms Tag Calibrator and
  Classification Hierarchy are separate, unbuilt, gated systems, not part of this phase.
- `.planning/todos/pending/110-controlled-vocabulary.md` — this phase's source todo; the "open
  question, not resolved here" it flags is resolved by D-02 above.

### Future integration point — informational only, cited in D-08
- `docs/research/stratification-dimension-unification.md` — `StratificationDimension` Protocol
  (`labels: list[str]  # from Vocabulary`); "Prior art note" citing archived v2.x `PatternPlugin`
  + `validate_tier()` as validated precedent for the interface-level reuse pattern in D-05/D-08.

### Roadmap and prioritization context
- `.planning/ROADMAP.md` — "Phase 161: Controlled Vocabulary System" section (Goal/Depends-on/
  Design pointers); notes it supersedes orphaned Phase 135.
- `docs/foundation/principles.md` — Renaissance/Jim Simons principles cited throughout this
  discussion (data integrity paramount, don't build infrastructure for unproven ideas, earn
  promotion through proof).

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `src/config/settings.py` / `ConfigService` (APR) — the direct structural analog for
  `VocabularyService`: cached-at-startup, zero-hot-path-DB-calls, library-not-microservice
  pattern (D-05). Read for the established calling convention before writing the new service.
- `services/data_quality_auditor.py` — `DataQualityAuditor(BaseDaemon)`, existing periodic
  quality-check + alert pattern (`_check_outliers`, `_maybe_publish_alert`); the natural host
  for the column-backed drift audit (Claude's Discretion above).
- `services/_batch_utils.py`'s `Float32ChunkAccumulator` — cited as the project's own precedent
  for "generalize the second time a shape is needed, not before" (D-07).

### Established Patterns
- Registry family convention (D-06/D-07): named thing, migration/evidence-gated writes, cached
  reads, looked up by any consumer via a single service class — shared by APR (`ConfigService`),
  Concept Registry (`ConceptRegistryService`, Phase 160), and now Controlled Vocabulary
  (`VocabularyService`). Each purpose-built to its own table; no shared base class.
- `feature_registry.tier` (2 live values: `0_atomic`, `2_theory`) and `contract_details->>'asset_class'`
  are the live TEXT columns the `tier`/`asset_class` namespaces back.

### Integration Points
- `feature_vectors.regime` (5 HMM labels) and `market_regimes.regime_label` (9 cross-sectional
  labels, written by Phase 144's `cross_sectional_regime_model.py`) are the two live columns
  the drift audit's declared-source-column mechanism watches for `regime_hmm`/`regime_cross_sectional`.
- `tf`/`timeframe` columns split across ~40 tables under two different column names — the
  namespace-keyed design handles this cleanly since it's keyed by vocabulary, not column name.

</code_context>

<specifics>
## Specific Ideas

User's steering input was architectural: start from "one unified system managing multiple
relationships" and "DAG microservice reuse," then converge — through direct evidence from the
project's own research corpus — on interface-level reuse (a shared registry *convention*, not a
shared schema), with three purpose-built tables (Controlled Vocabulary / Concept Registry /
Classification Hierarchy / Tag+Membership) each honest about what its rows actually are. The
"hierarchy" instinct for regime_hmm/regime_cross_sectional resolved into `vocabulary_group`
seeds (D-03/D-04) rather than new schema, since these are overlapping facets, not an exclusive
tree — the same reasoning the classification-hierarchy doc used to reject a single `parent_code`
column for GICS-vs-custom-taxonomy.

</specifics>

<deferred>
## Deferred Ideas

- **`tag_vocabulary` unification** — considered and explicitly rejected, not deferred (D-02).
  Not future work; closed.
- **Security Classification Hierarchy (GICS-style, `stratification-security-classification-hierarchy.md`)**
  — real future work, but gated on the individual-equities milestone (no ROADMAP phase exists
  yet). Fully designed and build-ready when that milestone starts.
- **`StratificationDimension`/Controlled-Vocabulary integration** (D-08) — real future
  connection, sequenced after Phase 144/145's conditioning-layer work, itself blocked on the
  current 143.1-07 corpus re-run. Not this phase's concern.

### Reviewed Todos (not folded)
- **`gsd-sdk`'s `todo.match-phase 161` query** returned 45 matches, nearly all generic 0.6
  keyword-overlap noise (same pattern Phase 160's discussion already flagged for this tool).
  Reviewed and judged noise — none had a substantive connection to Controlled Vocabulary beyond
  generic todo-file boilerplate, except todo 110 itself (this phase's source todo, already
  cited in canonical_refs, not a "fold" candidate).

</deferred>

---

*Phase: 161-Controlled Vocabulary System*
*Context gathered: 2026-07-16*
