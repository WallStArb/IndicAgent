# Phase 160: Concept Registry MVP - Context

**Gathered:** 2026-07-14
**Status:** Ready for planning

<domain>
## Phase Boundary

Build the four-table Concept Registry MVP (`concept_registry` / `concept_gate` /
`concept_transition_log` / `concept_annotation`) and seed exactly one domain,
`domain='ensemble_strategy'`, from Phase 142B.1's verified live ensemble-weighting state:
`ic_proportional` as the `active` incumbent (genesis transition row), `e1_shrunk_ic`/
`e2_mean_variance`/E3/E4 as `candidate` rows (E3/E4 thesis-only, no code exists yet). Wires
`ops_ensemble_weight_compare.py`'s win-decision gate as the domain's sole deterministic
status-flipper (invariant 1). Backend-only — no dashboard/UI component in this MVP.

This phase's design is fully decided going in: 4 review passes on the canonical doc, a complete
7-task implementation plan with zero open questions in the plan doc itself. Discussion for this
phase surfaced one genuine scope question (below) rather than open implementation gray areas —
the rest of the design (schema shape, promotion mechanics, gate semantics) is locked and should
not be re-litigated.

</domain>

<decisions>
## Implementation Decisions

### Scope: exactly one domain, not two
- **D-01:** Ship `domain='ensemble_strategy'` only. Do **not** migrate `feature_registry`'s 61
  live rows (`domain='feature'`) into Concept Registry in this phase, even though the schema's
  `domain` CHECK already includes `'feature'` per the canonical doc's MVP sketch. This was
  already the plan doc's stated scope guard (todo 058 item 7); this discussion re-examined it
  under Renaissance rigor and reaffirms it for a stronger reason than the plan doc's own
  ("zero feature rows are seeded" is a scope observation, not a risk justification):
  - `feature_registry` is a live, hot write path — `ic_engine.py`'s post-run lifecycle hook
    (Phase 143, LIFECYCLE-00/03/04/05) writes to it directly on every corpus epoch
    (evidence-based promotion/demotion, materiality-gated demotion, regime-shift guard). A
    corpus rerun is actively writing to this table as of this discussion (143.1-07).
  - `ensemble_strategy` is near-static (a handful of weighting-recipe candidates, no automated
    hot-path writer) — the correct domain to prove `ConceptRegistryService`'s CAS-based
    transactional apply logic on for the first time, before trusting it with a domain under
    live automated write pressure. Same "earn promotion through proof" pattern already applied
    to todo 080 (test one weighting candidate before building scaffolding for the rest).
  - Migrating `feature` now would also require rewiring the already-shipped, already-working
    LIFECYCLE hook to write through the new service instead of its current direct UPDATE — a
    second live-pipeline integration point in the same phase, doubling blast radius against a
    pipeline this project has spent significant effort protecting this session.
  - No forcing incident exists for `feature` (unlike the 058/112 duplicate-tracker case, which
    did force a fix). `feature_registry` works correctly today; this is a valid future
    consolidation, not an urgent one.
- **D-02:** The `domain='feature'` migration remains a separate follow-on phase/todo, sequenced
  only after `ensemble_strategy`'s governance has run live through at least one real A/B
  promotion/demotion cycle (proof the mechanism works under its first real load), and scoped to
  include rewiring `ic_engine.py`'s lifecycle hook as part of that follow-on's task list, not
  assumed to be a trivial add-on.

### Stale reference correction
- **D-03 [informational, correct at plan-phase time]:** The plan doc's Task 6 says the
  `domain='feature'` follow-on "files it as todo 109." That number is now taken — `109` is
  `completed/109-fisher-z-ci-bracket-clamp-belongs-in-ic-math.md`, an unrelated, already-closed
  item. Whoever executes Task 6 must file the follow-on under the next free todo number, not 109.

### Out of scope, correctly deferred elsewhere (not re-opened here)
- **D-04 [informational]:** `domain='regime_model'`'s row-grain question (one row per dimension
  vs. per (dimension, regime_group)) was flagged in Phase 144's own CONTEXT.md as something to
  revisit "when concept_registry MVP work is scheduled." Checked against the canonical design
  doc (`concept-unified-registry.md`, Domain Vetting section): this question is already fully
  specced with a recommendation (Option B — encode grain in `metadata`, no new column) but
  explicitly left as "a recommendation, not a decision," correctly deferred until `regime_model`
  has a real candidate to seed (it has zero rows today, same as `feature` had before Phase 142.5
  and today's ensemble work gave `ensemble_strategy` its first real candidates). Nothing about
  this phase's `ensemble_strategy`-only scope requires resolving it now, and doing so would be
  scope creep — a design decision belonging to whichever phase first seeds `regime_model` for
  real (not yet scheduled).

### Claude's Discretion
- Exact migration numbers (232/233 in the plan doc were current as of 2026-07-13; verify against
  live migration tip before applying — the project has hit duplicate-migration-number collisions
  before, see todo 101).
- Everything else task-by-task per the existing plan doc — schema DDL, service method
  signatures, gate default values, test coverage — is already fully specified there and should
  be followed as-is unless research surfaces a reason not to.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Implementation plan (primary source — read first)
- `docs/plans/archive/2026-07-13-concept-registry-mvp-implementation-plan.md` — the full 7-task
  implementation plan (migration SQL, `ConceptRegistryService` code, wiring, tests). Treat as
  authoritative for HOW; this CONTEXT.md only adds/corrects the scope decisions above. Note:
  Task 6's "todo 109" citation is stale (see D-03) — verify migration numbers 232/233 against
  the live tip before applying (see Claude's Discretion).

### Design doc (background, already survived 4 review passes)
- `docs/research/concept-unified-registry.md` — canonical design: 4-table schema, 9
  promotion/demotion invariants, Domain Vetting section (covers `feature`, `ensemble_strategy`,
  `hmm_variant`, `ic_method`, `regime_model`, `confluence` — only the first two are live-seeded
  anywhere, the rest are vetted-but-unseeded per D-04 above).

### Roadmap and prioritization context
- `.planning/ROADMAP.md` — "Phase 160: Concept Registry MVP" section for the live phase entry
  (Goal/Depends-on/Design pointers).
- `.planning/todos/pending/112-concept-registry.md` — this phase's source todo; kept as
  prioritization context.
- `.planning/todos/completed/058-concept-registry-mvp-seed-ensemble-strategy.md` — frozen
  historical record, superseded by 112 as the live tracker (duplicate-tracking incident, see
  D-01's forcing-incident comparison).

### Related, explicitly out of scope for this phase
- `.planning/phases/144-cross-sectional-regime-model-regime-group/144-CONTEXT.md` — is
  the source of the `regime_model` row-grain question addressed (and re-deferred) in D-04.
- `src/intelligence/feature_registry_service.py` — the live sibling system for `domain='feature'`
  (61 rows); reference implementation for the same lifecycle pattern, but not touched by this
  phase (see D-01/D-02).

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `src/intelligence/feature_registry_service.py` — 566-line reference implementation of the
  same `candidate → active → shadow_only → deprecated` lifecycle pattern for `domain='feature'`.
  Not extended or touched by this phase, but the pattern this phase's `ConceptRegistryService`
  generalizes — worth reading for established conventions (CAS-style status flips, transition
  logging) before writing the new service.
- `services/ic_engine.py`'s post-run lifecycle hook (Phase 143, LIFECYCLE-00/03/04/05) —
  confirmed live and actively writing to `feature_registry` during a corpus rerun as of this
  discussion. Not modified by this phase (see D-01) but is the concrete evidence for why
  `feature` domain migration is deferred.

### Established Patterns
- `metadata.apr_namespace` convention (from the canonical doc's Architecture Stress-Test,
  2026-07-06 pass) — how Concept Registry rows reference APR config keys without duplicating
  parameter values into the lifecycle row itself.
- Append-only evidence tables as TimescaleDB hypertables (`concept_transition_log`) — same
  precedent as `signal_lineage`, adopted explicitly in the canonical doc.

### Integration Points
- `ops_ensemble_weight_compare.py` — Task 5's wiring target; becomes the sole deterministic
  status-flipper for `domain='ensemble_strategy'` (invariant 1).
- `concept_registry` schema's `domain` CHECK constraint as shipped in migration 232 is only
  `('feature','ensemble_strategy')` — NOT the fuller `'hmm_variant'` / `'ic_method'` /
  `'regime_model'` / `'confluence'` set the canonical doc's MVP sketch enumerates. Each of those
  future domains will need its own CHECK-constraint migration before it can be seeded. This
  phase seeds only `'ensemble_strategy'`; the `'feature'` value is permitted by the CHECK but
  zero feature rows are seeded here. Confirmed live at discussion time: zero `concept_*` tables
  existed yet (checked via `\dt`).

</code_context>

<specifics>
## Specific Ideas

User's steering input was to apply Renaissance/Simons-style rigor (data integrity paramount,
prove-before-build, minimal complexity, guard against hidden bias, SoC/DAG discipline, automate
what's proven) to the one open scope question (domain='feature' bundling) rather than a specific
UI/UX preference — this phase has no UI surface. Applied directly to D-01/D-02 above.

</specifics>

<deferred>
## Deferred Ideas

- **`domain='feature'` migration** (D-02) — real future work, not lost, sequenced after
  `ensemble_strategy`'s governance has proven itself live through at least one real promotion/
  demotion cycle. Needs its own todo (109 is taken, see D-03) and its own scope covering the
  `ic_engine.py` lifecycle-hook rewiring, not a trivial add-on to a future phase.
- **`domain='regime_model'` row-grain decision** (D-04) — already fully specced with a
  recommendation in the canonical design doc; correctly stays deferred until `regime_model` has
  a real candidate to seed. Not this phase's or this discussion's call to make.

### Reviewed Todos (not folded)
- **gsd-sdk's `todo.match-phase 160` query** returned 42 low-signal matches, nearly all scoring
  the same generic 0.6 on keyword overlap ("2026", "status pending") rather than real
  phase-relevance. Reviewed and judged noise, not folded — none had a substantive connection to
  Concept Registry beyond generic todo-file boilerplate.

</deferred>

---

*Phase: 160-Concept Registry MVP*
*Context gathered: 2026-07-14*
