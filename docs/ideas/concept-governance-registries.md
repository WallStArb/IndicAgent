# Concept Governance Registries

**Status**: Partially built — four registries live, two to build
**Created**: 2026-06-28
**Informed by**: `.planning/research/2026-07-01-v3-architecture-review.md` (Fable 5) — Domains table gate-metric corrections and MVP build-trigger reassessment (2026-07-02) trace back to that review's ensemble-weighting and HMM-variant findings.
**Refreshed**: 2026-07-01 — critical re-architecture of Concept Registry; recipe-card framing, concepts-vs-facts boundary, gate-vs-annotation discipline rule; Concept Registry's full spec re-merged into this doc after a same-day split/re-unify (kept as one unified research doc, not an index + satellite file); renamed from "Metadata Governance Registry System" — "metadata" undersold what this actually is: reference (identity/knowledge) *and* lifecycle (active governance — promote, demote, prove), not passive descriptive data. **2026-07-02** — Domains table's `ensemble_strategy`/`hmm_variant` gate metrics corrected against concrete decisions made the same session (Phase 142B.1 insertion, todo 026's Decision Gate) — see §Domains footnotes; MVP build-trigger domain #2 reassessed from an assumed `alpha_pattern` default to `ensemble_strategy` as the more concrete and lower-risk near-term candidate (item 20); the IOHMM and factor-augmented HMM variants' real dependency on Phase 151's `regime_group` signal modules identified and fixed at the source doc. Also dropped this doc's own stray references to the regime-stratification doc's old, now-retired `P1`-`P8` numbering (see that doc's 2026-07-02 update — those codes looked like priority tiers but weren't, and collided with `todo 026`'s legitimate, unrelated `P4a`/`P4b` priority codes).
**Type**: Architecture pattern + design

---

## Renaissance Framing

Renaissance Technologies runs every model variant, signal idea, and methodology through a formal research pipeline. Nothing lives in a notebook nobody reads. Nothing disappears into a deleted branch. Every hypothesis either earns its way to live through accumulated statistical proof or gets formally retired with the evidence attached.

This is not bureaucracy — it is how you avoid re-discovering dead ends. When someone asks ten years from now "why don't we use diagonal covariance HMM?" the answer should be in the database: `demotion triggered 2026-09-14, held-out LL = -847.3 vs full covariance -821.1, n = 1200 bars`. Not in a Slack thread. Not in someone's memory. Queryable. Permanent.

But evidence alone is not enough. The other half of institutional knowledge is understanding — why something works, what breaks it, what we've learned since deployment, what depends on what. A concept whose thesis lives only in someone's head evaporates when they're gone. A concept whose failure modes are undocumented gets re-discovered the hard way.

The registries in this system capture both halves. The **governance layer** answers: *Is this valid? What state is it in? What happened?* The **knowledge layer** answers: *Why does it work? What breaks it? What have we learned? What depends on it?*

---

## What This Is: A Recipe Card File

Concept Registry is where the platform's actual secret sauce lives — not the infrastructure (IC engine, corpus pipeline, HMM training), which is methodology anyone could rebuild, but the specific, proven results of running that methodology: which feature interactions out of thousands of candidates actually carry IC, which HMM configuration was proven better and why, which ensemble weights survived out-of-sample. One row per recipe: what it is, whether it currently earns its keep, the formula/parameters that make it reproducible, and enough history that turning a deprecated one back on is a status flip, not archaeology.

**Concepts vs. facts — what belongs here and what doesn't.** A recipe is governed here; the output of using the recipe is not. `alpha_pattern` concepts (the strategy logic deciding when to fire) are governed rows with a lifecycle; `alpha_events` (the actual emitted signals at runtime) are a fact table with its own canonical writer (`docs/foundation/canonical-truth-registry.md`), recomputed/emitted fresh every time, never itself a lifecycle-governed row. Same for features: the *definition* of `momentum_z_fast` is a concept; a bar's actual `momentum_z_fast` value in `feature_vectors` is a fact. Concept Registry stores recipes, not their output.

**Not a secrecy mechanism today, but worth being clear about what's actually sensitive if that ever matters.** The system needs no access control right now — this is a solo project, there's no competing desk and no walkaway-employee risk. But if it's ever worth naming: the sensitive part isn't the methodology (walk-forward validation, FDR correction, HMM regime detection are all standard technique), it's the narrow, expensive-to-discover, cheap-to-copy result — which specific interactions/parameters/weights are `active` and their `thesis` annotations. `concept_registry` carries an unused, nullable `sensitivity` column for exactly this reason: free to add now, costs nothing while unused, saves a migration if a future access-control layer ever needs to filter by it.

---

## Registry Taxonomy

Three types, distinguished by what drives state changes:

**Type 1 — Parameter** (value-mutable): entries have tunable values ML can update at runtime. Gate is a validation range.
- **APR** — 348 numeric/behavioral params across 13 namespaces

**Type 2 — Lifecycle** (evidence-gated): entries move through `candidate → shadow_only → active → deprecated` based on statistical evidence.
- **Shadow Registry** — 36 components (`i7_plugin`, `swarm_agent`), EV[R] bootstrap CI gated. **Legacy** — no systemd unit runs `shadow_auditor`/`shadow_validator`/`alpha_swarm`, `last_eval_at` is NULL on all 36 rows, and it governs the v2.x I1-I7 plugin/swarm system that CLAUDE.md documents as archived under v3.0 (Feature Factory replaces I1-I4; I5-I7 archived outright). Not a migration target — there is no live plugin/swarm domain for Concept Registry to absorb it into. Revisit only if I7 plugins or swarm agents come back into active use.
- **Concept Registry** — generalized lifecycle governance for all research domains _(to build; absorbs Feature Registry only, for now)_

**Type 3 — Vocabulary** (static taxonomy): codes/labels with metadata, no lifecycle states.
- **Tag Vocabulary** — 6 categories, 301 instrument tags
- **Controlled Vocabulary** — domain enums _(to build; design at `docs/ideas/controlled-vocabulary.md`)_

---

## What Exists

Type 2/3 registries only — APR (Type 1) is the origin analogy for this whole family (see Registry Taxonomy above) but isn't comparable feature-by-feature here: it's value-mutable parameter tuning, not lifecycle governance or static vocabulary, so it was never designed to have gates, promotion states, or annotations. Full detail: `docs/foundation/adaptive-parameter-registry.md`.

| Registry | Tables | Entries | Gate | Gap |
|---|---|---|---|---|
| Feature Registry | `feature_registry`, `feature_transition_log` | 61 features | IC Sharpe + FDR | Governance only — no knowledge layer; gate params conflated in registry row; migrates to Concept Registry |
| Shadow Registry | `shadow_registry`, `shadow_transition_log` | 36 components | EV[R] bootstrap CI | Legacy — v2.x I1-I7 plugin/swarm governance, no live systemd consumer, never evaluated (`last_eval_at` NULL). Not migrating; no live domain to absorb it into |
| Tag Vocabulary | `tag_vocabulary`, `instrument_tags`, `instrument_annotations` | 301 tags | Human curation | — |

---

## Controlled Vocabulary (Type 3)

Full design at `docs/ideas/controlled-vocabulary.md`. Three tables:

```
controlled_vocabulary      — one row per valid code per namespace
vocabulary_group           — named groupings within a namespace
vocabulary_group_member    — many-to-many membership
```

`VocabularyService`: load at startup, hard crash on Python enum divergence, cached reads.

Namespaces to seed at build time: `signal_outcome` (groups: wins/losses/timeouts), `entry_type`, `signal_status`, `hmm_regime` (5 labels by emission mean), `market_regime_cross_sectional` (9 labels), `timeframe`.

Phase 134 blocker satisfied. Ready to build.

---

## Concept Registry (Type 2) — design exists, NOT a build plan

### Status check, applied honestly

This doc's own "When to Add a New Registry" rule (below) requires *external consumers that need enumeration*. Run it against what's actually true today: one live consumer (`domain='feature'`, already served by `feature_registry`), zero of the other six domains implemented, and the specific complexity added in the 2026-07-01 refinement pass (`concept_gate_template`, `concept_eval_run`, `concept_correlation`) was justified almost entirely by Interaction Factory's ~30,000-candidate scale — a system that is itself unbuilt and deferred. Two speculative designs were justifying each other's complexity. That's a real finding from applying our own stated rule, not a hypothetical concern: **do not build the ten-table version.** It stays documented below as a reference architecture — consulted if and when a domain actually reaches that scale — not as the thing to implement next.

### Purpose

Every research domain that needs evidence-gated lifecycle governance goes here. Alpha patterns, HMM architecture variants, IC methods, ensemble strategies, regime models, intelligence vector features. One system governs all of them, eventually. What gets built *first*, and why, is the Minimal Viable Version immediately below — not the full reference architecture.

Feature Registry migrates into this at build time as `domain = 'feature'` — that separation is historical, not structural. Shadow Registry does not migrate in — see Registry Taxonomy above; it's legacy v2.x plugin/swarm governance with no live v3.0 domain to attach to.

### Core discipline: the gate proves, the annotation explains — never invert

`concept_gate` and `concept_annotation` are deliberately separate tables with no dependency between them in either direction. A concept can carry a detailed, compelling `thesis` annotation and still sit at `candidate` forever if it never clears its gate — a good story is not evidence. Equally, a concept can promote to `active` with no thesis at all if the numbers clear the bar — inexplicable-but-proven is not a defect. This is the single most important invariant in the design: it's the mechanism that prevents the registry from becoming a system for justifying beliefs instead of falsifying them. Any future dashboard, UI, or workflow built on top of this schema must never let annotation content influence a gate decision, and must never require an annotation to exist before a promotion can fire.

This invariant matters more, not less, once an AI agent is proposing concepts autonomously — see "Promotion/Demotion Design for Autonomous Self-Improvement" below, which is the part of this doc actually worth building toward now.

### Minimal Viable Version — build this first, when domain #2 becomes real

Four tables, not ten. This is `feature_registry`'s current shape (identity + status + gate + last-eval cache, all on one row, which is exactly how `feature_registry` does it today) plus a knowledge layer, generalized just enough to take a second domain without a second bespoke table:

```
concept_registry       — identity, domain, status, lineage, enabled
                          status IN ('candidate', 'shadow_only', 'active', 'deprecated') — all four
                          survive from the reference architecture; shadow_only is not optional
                          scaffolding, it's the generalization of what the legacy Shadow Registry
                          did for plugins (live-observed, not yet acted on) — see invariant 6 below
concept_gate           — per-concept gate (no template layer — add one later only if a domain's
                          candidate volume actually makes per-concept configuration painful;
                          we don't know that yet because no domain has produced real candidates)
                          PLUS last-eval cache columns on the same row: last_eval_metric,
                          last_eval_n, last_eval_at, decay_ratio — mirrors feature_registry's
                          last_ic_value/last_ic_sharpe/last_ic_n/last_eval_at today. Without this,
                          a routine eval that reconfirms "still active, still above threshold"
                          writes nothing to concept_transition_log (which only logs status
                          *changes*), so "what's this concept's current measured performance"
                          would be unanswerable between transitions — a real gap caught by
                          checking this design against feature_registry's actual live schema.
                          PLUS fdr_required (bool), fdr_alpha (float) — per-concept FDR settings.
                          Note this is a different granularity than the reference architecture's
                          concept_eval_run.fdr_alpha (corpus-batch FDR for e.g. Interaction
                          Factory's 30,000-candidate sweep); feature_registry's fdr_alpha today is
                          a per-feature setting, which concept_gate is the correct home for — the
                          reference design never actually had a field for this at either
                          granularity, another gap caught by checking against the live schema.
concept_transition_log — immutable state-change audit trail, trigger_reason required
concept_annotation     — thesis / failure_mode / observation / open_question / implementation,
                          source = human | ai | empirical (this field is why the self-improvement
                          section below works — see there)
```

No `concept_gate_template` (per-concept gates are fine at low volume), no separate `concept_eval_state` table (folded into `concept_gate` above — one table doing both jobs is exactly what `feature_registry` already does, no reason to split it prematurely), no `concept_eval_run` (provenance matters once eval cadence is high enough to lose track of which corpus build backed which decision — not yet, one domain, infrequent evals), no `concept_correlation` (redundancy-by-correlation matters once there are enough concepts in one domain to actually be redundant with each other — `feature`'s 61 rows already have this need arguably, but it's a `feature`-specific analysis today, not infrastructure), no candidate staleness job (61 rows, all `active`, nothing rotting).

**Build trigger:** domain #2 gets real candidates. Originally assessed as "most likely
`alpha_pattern`, once `alpha_events` stabilizes and a self-improving agent starts proposing
patterns" — **reassessed 2026-07-02, that assumption no longer holds unchallenged.**
`alpha_pattern`'s path to real candidates depends on two things that don't exist yet:
`alpha_events` stabilizing (no defined completion point) and an autonomous proposer being
built (a significant project of its own — everything in "Promotion/Demotion Design for
Autonomous Self-Improvement" below has to be right before that proposer's output can be
trusted). `ensemble_strategy` now has a shorter, concrete path: Phase 142B.1 (inserted into
`ROADMAP.md` 2026-07-01/02) specs four human-authored weighting-strategy candidates (E1 shrunk-IC
inputs, E2 mean-variance `Σ⁻¹·IC`, E3 hierarchical partial-pooling, E4 per-feature decay
half-lives), each already has a defined eval mechanism (Phase 142A's `EnsembleICEngine`, OOS,
already planned and Renaissance-reviewed), and the only upstream dependency is Phase 142A
completing — a phase already in flight, not a speculative future capability. `ensemble_strategy`
may reach the build trigger before `alpha_pattern` does.

This changes more than timing. `ensemble_strategy`'s E1-E4 candidates are **human-authored**, not
AI-proposed — which means the six self-improvement invariants below (proposal/decision
separation, re-evaluation integrity, proposal budgets, proposer track-record, demotion symmetry,
mandatory `shadow_only` for AI-sourced concepts) mostly don't bind for this domain's first real
use. That makes `ensemble_strategy` a *safer* domain to prove the MVP against than `alpha_pattern`
would be: the schema and gate/annotation discipline get validated on a live domain without also
having to get AI-proposer trust boundaries right on the first attempt. Recommendation if/when the
MVP build trigger fires: build against `ensemble_strategy` first (validates the schema under low
risk), *then* extend to `alpha_pattern`/`confluence` once the self-improvement invariants are
also ready to be exercised for real — don't validate both classes of risk (schema correctness,
AI-proposer trust) in the same first build.

**`alpha_pattern` still has a concrete candidate spec (2026-07-01, later same day):**
`docs/ideas/intel-10-confluence-detection-persistence-layer.md` defines validated confluences as
governed statistical objects with their own lifecycle (`candidate → shadow → active → decaying →
retired`), gates, provenance, and decay governance — that is a Concept Registry domain
(`confluence`, or `alpha_pattern` if merged), specced independently the same day this doc was
refreshed. **Rule to prevent divergence:** if intel-10 reaches build stage before Concept Registry
exists, its lifecycle tables ARE the Concept Registry MVP instantiated for one domain — build them
in the four-table generalized shape (concept_registry/concept_gate/concept_transition_log/
concept_annotation), not as bespoke confluence tables that need migrating later. One mapping
question to settle at build time: intel-10 uses a `decaying` *status* (weight-consumers stop
reading, but the concept still fires and records occurrences); this registry deliberately has no
such status — decay lives in `decay_ratio` + demotion. intel-10's `decaying` is closest to
`shadow_only` re-entered from `active` (live-observed, not acted on), which suggests the enum
survives unchanged and `decaying` is a transition pattern, not a new state — but decide against
that domain's real needs, not by assertion here.

### Promotion/Demotion Design for Autonomous Self-Improvement

This is the part of the design that's actually worth thinking hard about now, because it's the part that changes shape once the proposer is an AI agent instead of a human researching by hand — everything above this section is infrastructure that can wait; this section is a set of invariants that need to be right from the first line of code, because retrofitting them after an autonomous agent has been proposing and promoting concepts for a while means auditing a history you can no longer fully trust.

**1. Proposal and decision are different roles, and the schema must make that structural, not conventional.** An AI agent may create a `concept_registry` row (`status='candidate'`), write its `thesis` annotation (`source='ai'`), even suggest a gate. It may never write to `status` directly. Only the deterministic evaluation engine — a fixed code path with no LLM in it, reading only `concept_gate` and eval results — flips `status`. This is the gate-proves/annotation-explains discipline rule from above, but stated as an access-control invariant instead of a convention: an AI that can write a persuasive `thesis` must be structurally incapable of using that same persuasiveness to promote itself. In practice: the promotion function is a plain SQL transaction or a narrowly-scoped service method: no agent, human or AI, gets a code path that both writes annotation content and flips status in the same call.

**2. Re-evaluation must consume new evidence, not re-roll the same dice.** An autonomous proposer that can resubmit the same candidate for re-evaluation indefinitely will eventually clear a p<0.05 gate by chance alone — the look-elsewhere effect, but self-inflicted by the system itself rather than by an external researcher p-hacking. The fix doesn't need `concept_eval_run`'s full provenance machinery to work at the minimal-version scale: it needs one constraint — a concept cannot be evaluated twice against the same corpus build. `concept_transition_log` already has `triggered_at`; enforcing "the corpus must have advanced since the last eval" (even just a monotonic build identifier compared against the log's last row) closes this without adding a table.

**3. Proposal volume needs a budget, even at minimal-version scale.** A human researcher self-limits by how many ideas they can physically generate; an AI agent doesn't. Before self-improvement is live, decide a cap — e.g. N new `candidate` rows per domain per day/week from `source='ai'` — enforced at the service layer, not the schema. This is cheap to add now (one config value, `alpha.concept_registry.max_ai_candidates_per_period`, APR-backed per this project's own convention) and expensive to discover the need for after an agent has flooded the registry with a thousand low-quality candidates overnight.

**4. Track the proposer's own track record — this is free, and it's the actual self-improvement signal.** `concept_annotation.source` already distinguishes `human`/`ai`/`empirical` on every thesis. That alone answers "is the AI's idea generation actually any good": `SELECT source, count(*) FILTER (WHERE status='active') / count(*)::float AS hit_rate FROM concept_registry c JOIN concept_annotation a ON a.concept_id=c.concept_id AND a.annotation_type='thesis' GROUP BY source`. If the AI proposer's hit rate is worse than the human baseline, that's a signal to retrain or constrain it, not to trust its future proposals more. No new table, no new mechanism — just a requirement that every `candidate` row gets a `thesis` annotation with an honest `source` at creation, which the minimal version already requires.

**5. Demotion must be exempt from the same self-interest problem, in reverse.** An agent that proposed a concept has no business being the one that decides to keep a failing concept alive past its gate. Demotion, like promotion, is engine-only — same invariant as #1, applied to the opposite direction. `decay_floor`-triggered demotion (in the reference architecture) or a simpler manual `demotion_threshold` check (in the minimal version) must fire automatically once gate conditions are met, with no override path that goes through the proposer.

**6. `shadow_only` is mandatory between `candidate` and `active` for domains where proof is proposer-driven or backtested-only, and non-negotiable for AI-sourced concepts specifically.** This is the generalization of what the legacy Shadow Registry did for plugins — clear the statistical gate, then run live-observed for `min_promotion_consecutive` real eval cycles with zero influence on any downstream decision (`enabled` stays effectively inert at this stage — the concept is scored but not acted on), *before* ever reaching `active`. A human proposer implicitly shadow-tests an idea through their own judgment before formally proposing it at all; an autonomous proposer has no such filter, which makes this stage more load-bearing for AI-sourced concepts, not less. Backtested/OOS proof and live-observed proof are different kinds of evidence — a concept can pass walk-forward validation on historical data and still behave differently once it's actually watching live data it wasn't fit to.

**Documented exception: `domain='feature'`.** `docs/ideas/feature-vector-lifecycle.md` explicitly designs *without* a live shadow period — "the IC gate is retrospective... this is not a gap" — and that reasoning holds: features are hand-engineered (not proposer-driven, no self-improvement risk this invariant exists to guard against), and the walk-forward IC gate already provides fold-based OOS validation that serves an equivalent evidentiary function to live observation, just through a different, already-reasoned mechanism. Earlier drafts of this invariant stated it as absolute ("for any domain, regardless of proposer") — that was an over-generalization: a rule built for one specific risk (AI proposers overfitting to backtest-only conditions) got stated as universal, contradicting an already-good design decision for a domain where that risk doesn't apply. **The corrected rule:** any domain claiming this exception must document, like `feature` does, why its gate already provides evidence live observation would add — not merely assert the exception. `feature_interaction` inherits `feature`'s exception once/if it exists, since it's the same evaluation methodology on the same gate. Domains with proposer-driven or self-improvement-adjacent concepts (`alpha_pattern` especially, once real) do not get this exception by default.

None of this requires the ten-table reference architecture. All six invariants apply directly to the four-table minimal version — they're rules about *who can write what, and in what order*, not about additional storage.

### Full Reference Architecture (do not build yet) — two layers, ten tables

```
GOVERNANCE LAYER — is this valid, what state is it in, what happened, and could we prove it again
  concept_registry       — identity, status, lineage, redundancy group
  concept_gate_template   — domain-level default gate
  concept_gate           — per-concept override of the domain template; optional
  concept_eval_run       — one row per evaluation batch/cycle; ties results to a corpus build
  concept_eval_state     — last-cycle summary only (promotion/demotion counters); NOT the history record
  concept_transition_log — immutable state-change audit trail

KNOWLEDGE LAYER — why it works, what breaks it, what we know, what depends on what, what's redundant
  concept_annotation     — versioned knowledge: thesis, assumptions, failure modes, observations
  concept_dependency     — directed dependency graph between concepts
  concept_regime_ic      — full regime-stratified IC matrix, one row per (concept, regime) per eval_run
  concept_correlation    — pairwise correlation within a domain, one row per pair per eval_run
```

Ten tables, not seven — three refinements (gate templates, eval provenance, correlation-as-evidence) each add one table. `concept_eval_state` is demoted from "the record" to "a cache of the most recent record," because a system built to prevent institutional amnesia cannot itself forget how a metric trended over time.

---

### GOVERNANCE LAYER

#### concept_registry

Identity and current state. Changes almost never. Owned by operator/migration.

```sql
CREATE TABLE concept_registry (
    concept_id        UUID    PRIMARY KEY DEFAULT gen_random_uuid(),
    domain            TEXT    NOT NULL
        CHECK (domain IN ('feature', 'alpha_pattern', 'hmm_variant', 'ic_method',
                           'ensemble_strategy', 'regime_model', 'feature_interaction')),
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

**`domain`** is enforced with a plain `CHECK` constraint, same pattern as `status` above — no dependency on Controlled Vocabulary. An earlier version of this design specced `domain` validation as a runtime dependency on `VocabularyService.codes("concept_domain")`, requiring Controlled Vocabulary (a separate, also-unbuilt, also-deferred Type 3 system) to exist before Concept Registry could. That coupling wasn't earning its cost — 7 fixed values already listed inline is exactly the same shape as `status`'s 4 values, which needs nothing beyond a `CHECK`. Correction: Concept Registry has no dependency on Controlled Vocabulary. They remain unrelated sibling designs — Concept Registry governs lifecycle, Controlled Vocabulary governs symbolic-code labels/groupings elsewhere in the platform (`signal_outcome`, `regime` labels, `timeframe`, etc.) — with no shared build gate and no reason to couple their schedules.

**`enabled`** is independent of `status`. An `active` concept can be disabled without demotion. A `candidate` can run in shadow before formal promotion. The evaluation engine skips `enabled = false` entirely.

**`parent_concept_id`** creates a research lineage tree. When an HMM variant is iterated, the revision references the prior version. History is navigable. **Cardinality caveat:** this is a single-parent FK, but `feature_registry.parent_features` is `text[]` — a compound primitive like `xf_prod_body_ratio__volume_z` (naming per `interaction-factory.md`: single underscore after the operation, double underscore between parent names) has two parents by definition. Zero live features exercise this today (checked: `array_length(parent_features, 1) > 1` returns no rows), so it's not an active migration blocker, but `concept_dependency`'s `uses_feature` edge type (in the reference architecture, not the MVP) is the correct home for multi-parent relationships once Interaction Factory produces compound features — `parent_concept_id` should stay reserved for true single-lineage iteration (HMM variant v2 replacing v1), not composition.

**`redundancy_group`** prevents silent over-fitting. Concepts in the same group compete — only one holds `active`. **Scoped to a single domain** — a `redundancy_group` spanning `alpha_pattern` and `hmm_variant` has no coherent meaning; different gate metrics, different eval methods, nothing to compare. Enforced with `CHECK` at the service layer: all members of a `redundancy_group` must share `domain`. When a new concept earns promotion, it displaces the incumbent unless `concept_correlation` (below) shows their correlation is under threshold — this is evidence looked up, not an assumption made.

---

#### concept_gate_template

Domain-level default gate. Added because the design's own first heavy user *would* break the original one-gate-per-concept assumption: if Interaction Factory (`docs/ideas/interaction-factory.md`) is ever built and reaches its full ~30,000-candidate scale, nobody hand-configures 30,000 gates. **Caveat, consistent with the "Status check" above:** Interaction Factory itself now has an explicit evidence-based build trigger (documented atomic-feature IC saturation, not just readiness) and is not scheduled — so this table's justification is conditional on a system that may never reach that scale. It's kept in the reference architecture as "what this would need if that happens," not as an active requirement.

```sql
CREATE TABLE concept_gate_template (
    domain                     TEXT  PRIMARY KEY,
    gate_metric_name           TEXT  NOT NULL,
    gate_eval_method           TEXT  NOT NULL,
        -- 'oos_holdout', 'walk_forward', 'bootstrap_ci' — in-sample never valid
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

Per-concept override of the domain template. Optional — most concepts in a high-volume domain (`feature_interaction`, eventually `alpha_pattern`) have no row here and inherit `concept_gate_template` for their domain. A row here only exists when a specific concept needs a bar different from its domain's default (e.g. a `regime_scope`-conditional gate, or a hand-tuned `decay_floor`).

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

**`min_promotion_consecutive`** — N consecutive evaluations above threshold before promotion fires. Default 3. One good evaluation proves nothing.

**`regime_scope`** — an edge that works only in trending regime is a real edge. Governing it conditionally is more honest than forcing it through an unconditional gate it cannot pass. Template-level, since it's concept-specific by nature, has no domain default. **(2026-07-01, second pass) a bare label is ambiguous under the multi-dimension stratification roadmap:** today the per-symbol HMM labels (`trending_up`...) and cross-sectional labels (`high_bear`...) happen to be disjoint strings, but `docs/plans/2026-07-01-regime-stratification-alternatives.md` adds more dimensions (volatility_regime, dispersion_regime) whose bucket names can collide. Qualify with the stratification dimension — `market_regimes:high_bear`, `hmm:trending_up`, `volatility_regime:high` — or split into `(regime_dimension, regime_label)` columns at build time.

**`decay_floor`** — when `current_metric / baseline_metric_at_promotion < decay_floor`, decay demotion fires immediately without waiting for `demotion_consecutive`. Zombie edges die fast.

---

#### concept_eval_run

One row per evaluation batch/cycle, per domain. Fixes two gaps at once:

1. **Reproducibility** — every `concept_eval_state` and `concept_transition_log` row references the `eval_run_id` that produced it, which in turn records which corpus build / `feature_ic_scores` generation it read from. Without this, "why was this demoted on 2026-08-14" is unanswerable after the next corpus rebuild overwrites the numbers that decision was based on — and this project rebuilds its corpus every few days.
2. **Portfolio-level false discovery control** — `n_candidates_in_run` records how many concepts were gate-checked in the same batch. A domain running 30,000 `feature_interaction` candidates through one eval cycle needs a corpus-level BH-FDR correction across that batch (same principle the IC engine already applies per Phase 142A) — this table is what makes that correction possible after the fact, not just at compute time.

```sql
CREATE TABLE concept_eval_run (
    eval_run_id        UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    domain              TEXT         NOT NULL,
    corpus_build_ref    TEXT         NOT NULL,   -- ties to the ic_engine/corpus rebuild that produced the inputs
                                                 -- (2026-07-01) this already has a live implementation: the
                                                 -- CorpusManifest system (.planning/corpus_manifests/*.json,
                                                 -- src/observability/corpus_manifest.py) written by ic_engine/
                                                 -- ensemble_trainer/alpha_publisher today — use the manifest
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

Cache of the most recent evaluation — **not the history**. History lives in `concept_eval_run` joined against per-run results (see below); this table exists purely so the evaluation engine and dashboard can read "current state" in one row without scanning history.

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
exactly when its measured metric is high — which is partly luck (the promotion gate selects on the
metric, so the promotion-time value is biased upward by construction). If `baseline_metric` stores
the raw promotion-time value, `decay_ratio`'s denominator is systematically inflated and decay
demotions will fire on pure regression-to-the-mean, killing healthy concepts. `baseline_metric`
must store the *shrunk* estimate (empirical-Bayes toward the domain/regime prior, weighted by
effective N — same mechanism as `docs/plans/2026-06-29-feature-scoring-beyond-ic.md` §0b) or,
minimally, the mean of the `min_promotion_consecutive` evaluations rather than the final one.
This applies equally to the MVP's `concept_gate` last-eval cache columns.

**Original design flaw, fixed by `concept_eval_run`:** this table was previously described as "overwritten each cycle — not audit data," which meant a concept sitting `active` for months with slowly eroding IC that never crosses the demotion threshold had its entire decay trajectory silently lost — visible only if a transition eventually fired. That directly contradicted the "never drop data that could contain signal" principle. Every eval cycle now writes a durable row keyed by `eval_run_id` (in `concept_regime_ic` for the regime-stratified numbers, or a lightweight `concept_eval_run` join for the scalar gate metric) — `concept_eval_state` is free to be "just the latest" because the full curve is reconstructable elsewhere.

---

#### concept_transition_log

What happened. Immutable, append-only.

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

`trigger_reason` distinguishes why a demotion fired. A decay demotion on a once-strong concept signals edge erosion. A redundancy demotion signals a better competitor emerged. A `candidate_timeout` demotion signals nobody ever evaluated the idea — a different research response than either (revisit vs. abandon vs. schedule). `eval_run_id` ties the transition back to the exact corpus build and candidate batch that triggered it.

---

### KNOWLEDGE LAYER

#### concept_annotation

Versioned, typed knowledge about a concept. Append-only — annotations accumulate over time, superseded annotations are closed with `valid_to`. Same pattern as `instrument_annotations`.

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

Every concept gets a `thesis` annotation at creation — this is the intellectual basis, not a one-liner description. The `failure_mode` annotations accumulate empirically: the evaluation engine writes one when it detects a regime or volatility condition that correlates with IC collapse. `observation` annotations capture what was learned post-promotion that was not known at creation. `open_question` annotations mark things that are unresolved — they surface in the dashboard as open research items.

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

This is richer than `regime_scope` in `concept_gate`. A concept with `regime_scope = NULL` (unconditional gate) may still show a strong regime profile here: IC Sharpe 0.8 in `trending_up`, 0.1 in `ranging`, -0.3 in `trending_down`. The ensemble uses the full matrix to apply zero weight outside the concept's strong regimes without needing to change its governance status. Regime-conditional weighting and regime-conditional promotion are separate concerns. Keying on `eval_run_id` rather than overwriting `(concept_id, regime_label)` in place is what makes this the durable eval-history table referenced above — the ensemble reads the latest `eval_run_id` per concept; research queries can read all of them.

---

#### concept_correlation

Makes redundancy an evidence-backed fact instead of an implied rule. Scoped within a domain — cross-domain correlation between, say, an `alpha_pattern` and an `hmm_variant` isn't well-defined (different gate metrics, different eval methods) and isn't computed here.

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

The redundancy-group displacement rule (`concept_registry` above) reads this table before displacing an incumbent: if the challenger's correlation to the incumbent (looked up here, most recent `eval_run_id`) is below the domain's redundancy threshold, both can coexist as `active` — they're not actually redundant even though they're in the same `redundancy_group`, they're diversifying. This is also useful independent of redundancy_group membership: it's the raw material for "what's secretly correlated with what" queries the ensemble's correlation engine would need if `feature_interaction` ever reaches meaningful scale — `interaction-factory.md`'s "Concentration Risk" section flags this as a correctly-open question, since no compounds exist yet to measure.

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

The motivating query this whole design exists to answer, and it's the same shape for every domain — `feature`, `alpha_pattern`, `hmm_variant`, whatever `domain` value is passed in:

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

Before this exists, that question is only answerable for one domain (`feature`, via `feature_registry.formula_short` — a one-line gloss, not the actual formula) and not at all for any other domain. After migration, `implementation` annotations close the formula gap too — `formula_short`'s one-liner becomes a fuller, versioned `implementation` annotation that can hold the real derivation or a code-path pointer, not just a description of it.

---

### ConceptRegistryService

Domain-scoped **lazy loading**. Active and shadow_only concepts load eagerly at daemon startup — these are in use. Candidates load lazily when the evaluation engine requests them. With hundreds (or tens of thousands, for `feature_interaction`) of candidates, loading all at startup is wasteful.

Hard crash if any domain referenced in `concept_registry` has no `concept_gate_template` row — every domain must have a resolvable default, even if every individual concept overrides it. A `concept_gate` row is optional per concept; `concept_gate_template` is not optional per domain.

A background job enforces `max_candidate_age_days` per domain: any `candidate` with no `concept_eval_run` reference older than the template's window transitions to `deprecated` with `trigger_reason = 'candidate_timeout'`.

Knowledge layer tables (annotation, dependency, regime_ic, correlation) are read on demand, not cached at startup. They are queried by the dashboard and the evaluation engine but not on the hot path.

---

### Domains

| Domain | Gate metric | Eval method | What it governs |
|---|---|---|---|
| `feature` | IC Sharpe + FDR | Walk-forward | Intelligence vector features (migrated from feature_registry) |
| `feature_interaction` | IC Sharpe + FDR | Walk-forward | Interaction feature candidates before FeatureVector column |
| `alpha_pattern` | IC Sharpe | OOS holdout | Alpha signal ideas competing for ensemble inclusion |
| `hmm_variant` | Held-out log-likelihood† | OOS holdout | HMM architecture variants (covariance structure, obs vector, K) |
| `ic_method` | Walk-forward IC stability | Walk-forward | IC calculation variants (Spearman, rank-IC, HAC methods) |
| `ensemble_strategy` | Ensemble IC (`ic_ci_lower`, stable walk-forward folds)‡ | OOS, via EnsembleICEngine | Ensemble weighting strategies |
| `regime_model` | Cross-validated accuracy | Walk-forward | Regime classification model variants |

Each row here becomes a `concept_gate_template` row at build time — this table is now literally the seed data for that table, not just documentation of intent. An eighth domain, `feature_interaction`'s eventual promoted-survivor storage from Interaction Factory (`docs/ideas/interaction-factory.md`), is already covered by the `feature_interaction` row above — no separate `compound_primitive_registry` table needed once Concept Registry exists.

**† `hmm_variant` gate note (added 2026-07-02, checked against live decisions):** held-out log-likelihood remains the right *per-candidate* eval metric once an HMM variant is actually built and compared. But it is not the *build trigger* — todo 026's Decision Gate is a regime-IC separation query on the current per-symbol HMM labels (`regime-IC gap < 0.01` escalates to justifying a variant; `> 0.05` means current labels are fine, don't build). Two different gates at two different decision points, both real: the Decision Gate decides *whether* to spend effort on a variant at all; held-out LL (or a domain-appropriate substitute) decides whether a built variant is actually better. Neither table row nor `concept_gate_template` currently has room for a build-trigger gate distinct from a promotion gate — worth a note if `hmm_variant` ever reaches the MVP build trigger, not a reason to change the MVP schema now (no live candidates in this domain yet).

**‡ `ensemble_strategy` gate note (added 2026-07-02):** this row originally guessed "Realized Sharpe" before any concrete ensemble-methodology mechanism existed. Phase 142B.1 (`ROADMAP.md`, inserted 2026-07-01/02 from `.planning/research/2026-07-01-v3-architecture-review.md` §2) now defines the actual mechanism: every weighting variant (IC-proportional, mean-variance `Σ⁻¹·IC`, hierarchical partial-pooling, per-feature decay) is a new `weight_version` in the existing `ensemble_weights` PK, A/B'd by Phase 142A's `EnsembleICEngine` on OOS data — an IC-based gate, consistent with every other domain in this table and with Invariant 1 (executable-return IC is the platform's standard evidentiary currency), not a Sharpe-based one. Corrected to match. This is informal practice today (142B.1 doesn't use `concept_registry` — Concept Registry has no live consumer in this domain), but if/when `ensemble_strategy` reaches its MVP build trigger, this is the gate to seed `concept_gate_template` with.

---

### Feature Registry migration

`feature_registry` migrates into `concept_registry` at build time as `domain = 'feature'`. The separation is historical, not structural:

- **Dataclass alignment gate** — implemented per domain in ConceptRegistryService
- **Parent-cascade trigger** — application-layer logic for `domain = 'feature'`
- **SQL columns vs JSONB** — `formula_short`, `normalization`, `linear_ready`, `tier`, `group_name` etc. move to `metadata JSONB`; actual consumers (ic_engine, ensemble_trainer) load into Python at startup, no SQL-level consumers exist
- **Decay tracking** — `feature_registry`/`feature_ic_scores`'s existing `is_decaying`/`decay_detected_at`/`recovery_eligible_at` columns (currently unwired — see `.planning/todos/deferred/015-feature-vector-lifecycle.md`, a near-term priority fix independent of this migration) map onto `concept_eval_state.decay_ratio` + `concept_gate.decay_floor` at migration time. Same relationship as `feature_registry` itself: todo 015 wires up decay detection for the domain that exists *today*; Concept Registry's `decay_floor` is the same mechanism generalized to every domain, for whenever this migration actually happens. Building 015 first is not wasted work — it's the live version of exactly this column pair.

`FeatureRegistryService` becomes `ConceptRegistryService` loading `domain = 'feature'`. Migration proves the design with a live domain on day one.

Feature ideas and interaction candidates enter as `domain = 'feature_interaction'` at `candidate` status, earn IC promotion, then graduate to `domain = 'feature'` when they get a FeatureVector column. Only candidates that survive Interaction Factory's raw screening (`compound_ic_scores`, outside Concept Registry's scope) enter `concept_registry` at all — the ~30,000 raw pairs never get a `concept_registry` row, only the hundreds that clear the initial IC bar do.

Shadow Registry (`shadow_registry`) is **not** migrated — see Registry Taxonomy above.

---

### Build sequence (reference architecture, for when it's warranted)

1. Governance layer (concept_registry, concept_gate_template, concept_gate, concept_eval_run, concept_eval_state, concept_transition_log)
2. Migrate feature_registry → `domain = 'feature'`; seed `thesis` and `failure_mode` annotations for all 61 features
3. `concept_regime_ic` and `concept_correlation` — evaluation engine writes from day one, keyed by `eval_run_id`; feeds ensemble immediately
4. `concept_annotation` — human knowledge layer live; AI and empirical annotations accumulate
5. `concept_dependency` — populated at concept creation; gate checks dependencies before promotion
6. Candidate staleness job — enforces `max_candidate_age_days` per domain from day one, so candidate rot never accumulates in the first place
7. Dashboard: single concept view shows all ten tables — governance status, annotation history, regime IC trend, correlation matrix, dependency graph

---

### Refinements vs. original 2026-06-28 design (critical review, 2026-07-01)

1. **Eval history was being destroyed.** `concept_eval_state` was "overwritten each cycle — not audit data" — a concept decaying slowly toward (but never crossing) its demotion threshold had its entire trajectory silently lost. Fixed: `concept_eval_run` + `eval_run_id`-keyed `concept_regime_ic` rows preserve full history; `concept_eval_state` is now explicitly just a cache.
2. **No corpus-build provenance.** Corpus rebuilds happen every few days in this project; nothing tied a promotion/demotion decision to which rebuild produced the numbers behind it. Fixed: `concept_eval_run.corpus_build_ref`.
3. **No portfolio-level FDR control.** Interaction Factory alone plans ~30,000 candidates; each gate check was an independent p<0.05 test with no batch-level false-discovery correction, the same look-elsewhere-effect problem the IC engine already solved at the corpus level (Phase 142A) but that could creep back in here. Fixed: `concept_eval_run.n_candidates_in_run` + `fdr_alpha`.
4. **Redundancy was asserted, not computed**, and implicitly cross-domain (incoherent — an `alpha_pattern` and an `hmm_variant` have no comparable correlation). Fixed: `concept_correlation` table, within-domain only.
5. **Schema couldn't survive its own first customer.** One gate row per concept doesn't scale to 30,000 auto-generated `feature_interaction` candidates. Fixed: `concept_gate_template` (domain default) + optional `concept_gate` (per-concept override), resolved via `COALESCE`.
6. **Unbounded candidate accumulation.** Nothing aged out a `candidate` created and never evaluated — same "notebook nobody reads" failure the whole system exists to prevent, just relocated into a DB row. Fixed: `max_candidate_age_days` auto-demotion with `trigger_reason='candidate_timeout'`.
7. **Shadow Registry's exclusion was initially flagged as an oversight, then confirmed correct.** First pass proposed migrating it in as `domain='plugin'` since its gate (`n>=100`, `bootstrap_ci_lower(pnl_r)>0`) maps directly onto `concept_gate_template`'s `bootstrap_ci` method. Checked against live state: no systemd unit runs `shadow_auditor`/`shadow_validator`/`alpha_swarm`, `last_eval_at` is NULL on all 36 rows, and it governs the v2.x I1-I7 plugin/swarm system CLAUDE.md documents as archived (Feature Factory replaces I1-I4; I5-I7 archived). There is no live `plugin` or `swarm_agent` domain in v3.0 to migrate it into. Correction: Shadow Registry stays separate and legacy; revisit only if I7 plugins or swarm agents return to active use.
8. **Applied "when to add a registry" rule against the design itself and it failed.** One live consumer, six of seven domains unbuilt, and the complexity in items 1-6 above was justified by a second unbuilt system's imagined scale. Nine-table design demoted to reference-only; four-table Minimal Viable Version defined as the actual build target, deferred until a second domain has real candidates.
9. **Promotion/demotion needed to account for autonomous self-improvement, not just human research.** Added six invariants (see "Promotion/Demotion Design for Autonomous Self-Improvement" above) governing proposal/decision separation, re-evaluation integrity, proposal budgets, proposer track-record measurement, demotion symmetry, and mandatory `shadow_only`.
10. **This doc itself was briefly split** into an index (this file) + a satellite spec (`concept-registry.md`) to avoid duplicating the schema in two places, then re-unified same day — the split solved a real problem (drift between the todo and this doc) but recreated it in a different shape once a separate satellite file existed. Re-merged: this doc is the single, unified home for Concept Registry; Feature Registry, Controlled Vocabulary, and Interaction Factory remain separate sibling docs (own history, own build gate), referenced here with a summary and a link, not duplicated.
11. **APR (Type 1) was appearing as a peer row in "What Exists" and "Full Comparison," and `concept_registry.domain` had an unnecessary runtime dependency on Controlled Vocabulary.** Both trimmed: APR reduced to its origin-analogy mention in Registry Taxonomy (it was never designed to have gates or lifecycle states, so a feature-by-feature comparison was comparing incompatible things); `domain` now uses a plain `CHECK` constraint like `status` does, no dependency on a separate unbuilt system to validate 7 fixed values.
12. **Interaction Factory's own design was unclear about what it actually was and whether it was justified**, which fed two circular-reasoning references in this doc (`concept_gate_template` and `concept_correlation`'s rationale, both citing IF's 30K-candidate scale to justify reference-architecture tables while IF itself was unbuilt and its need unproven). Rewrote `interaction-factory.md`: reframed from "a service" to "a candidate-generation strategy" that reuses the existing IC engine + Concept Registry pipeline rather than duplicating it; added an evidence-based build trigger (documented atomic-feature IC saturation, not just readiness); fixed a real statistical gap (no explicit batch-level FDR correction in the stated promotion rule — naive `p<0.05` across 30K candidates produces ~1,000-1,500 false discoveries by chance alone) and an unstated look-ahead risk (rolling correlation window must be explicitly causal). This doc's two circular references now note explicitly that they describe conditional, not-currently-justified reference material.

What was already right and left unchanged: `trigger_reason` in `concept_transition_log` (not `status`) is the correct place to distinguish "demoted after decay" from "never promoted" — resisted the urge to add complexity to the status enum.

### Second review pass (2026-07-01, later same day — findings from cross-checking against work done since the morning refresh)

13. **intel-10 is domain #2 arriving.** The confluence detection/persistence layer
    (`docs/ideas/intel-10-confluence-detection-persistence-layer.md`, written the same day)
    independently specced a full lifecycle-governed object — exactly what this registry
    generalizes. Anti-divergence rule and status-enum mapping added at the MVP build trigger
    above. Without this cross-reference, the two designs would have produced the bespoke
    per-domain duplication this registry exists to prevent.
14. **`baseline_metric` had a winner's-curse flaw.** Raw promotion-time metric as the decay
    denominator fires false demotions on regression-to-the-mean. Fixed inline at
    `concept_eval_state`: store the shrunk estimate (feature-scoring-beyond-ic §0b machinery).
15. **The evaluation engine is load-bearing and unspecified.** All six self-improvement
    invariants delegate to "the deterministic evaluation engine" — no doc names the service,
    its cadence, its Ring placement, or oneshot-vs-daemon shape. The ten tables are storage;
    the engine is the system. This is an acknowledged open gap, to be specced when the MVP
    build trigger fires — likely a `BaseBatch` oneshot per this project's conventions, but
    that's a guess, not a decision.
16. **`corpus_build_ref` doesn't need inventing** — the live CorpusManifest system is the
    identifier. Noted inline at `concept_eval_run`.
17. **`regime_scope` needs a dimension qualifier** before additional stratification dimensions
    land (`volatility_regime` etc.) — bare labels are only unambiguous today by accident.
    Noted inline at `concept_gate`.
18. **Pipeline-level methodology changes are invisible to this schema by design — and that's
    fine, but only because a sibling doc now covers them.** `concept_transition_log` audits
    per-concept state changes; a change to a `concept_gate_template` (or to the eval
    methodology itself) affects every concept in a domain and shows up in no per-concept log.
    That grain is covered by `docs/plans/methodology-change-ledger.md` (created the same day):
    gate-template changes and eval-methodology changes get ledger entries there. The two are
    complementary grains of the same audit discipline, not alternatives.
19. **Naming inconsistency with interaction-factory.md fixed** — this doc wrote
    `xf_prod__body_ratio__volume_z` (double underscore after operation); the convention is
    `xf_prod_body_ratio__volume_z` (single after operation, double between parents).

### Third review pass (2026-07-02 — findings from the day's ensemble/regime architecture review and roadmap surgery)

20. **The "domain #2 = `alpha_pattern`" assumption was checked against a same-session roadmap
    change and didn't hold up.** Phase 142B.1 (Ensemble Weighting Methodology, inserted into
    `ROADMAP.md` this session) gives `ensemble_strategy` four concrete, human-authored candidates
    (E1-E4) with an already-planned eval mechanism (Phase 142A's `EnsembleICEngine`), a shorter
    dependency chain than `alpha_pattern`'s (which needs `alpha_events` to stabilize and an
    unbuilt autonomous proposer), and — because the candidates are human-authored — a chance to
    validate the MVP schema without simultaneously having to get the six self-improvement
    invariants right for an AI proposer. Reassessed in "Minimal Viable Version" above:
    `ensemble_strategy` may be domain #2 in practice, and building against it first is lower-risk
    than building against `alpha_pattern` first regardless of which arrives sooner.
21. **`ensemble_strategy` and `hmm_variant` Domains-table gate metrics were stale guesses,
    corrected against concrete decisions made this session** — see Domains table footnotes (†, ‡).
    `ensemble_strategy` was "Realized Sharpe" (guessed before any mechanism existed); actual
    mechanism is IC-based (`ic_ci_lower` via `EnsembleICEngine`), consistent with every other
    domain's IC-based gate. `hmm_variant`'s "held-out log-likelihood" is still right for comparing
    a *built* variant, but todo 026's Decision Gate (regime-IC-separation query) is a distinct,
    earlier build-trigger gate the original row didn't distinguish.
22. **The IOHMM and factor-augmented HMM variants (`docs/plans/2026-07-01-regime-stratification-alternatives.md`) turned out to
    have a real structural dependency on `regime_group` (Phase 151) that neither doc had stated.**
    IOHMM's exogenous inputs (VIX, breadth, yield spread) are literally Phase 151's signal-module
    outputs (`breadth_vol.compute()`, `curve_credit.compute()`); the factor-augmented variant's
    "cross-sectional factor returns" reuses Phase 151's peer-resolution mechanism
    (`_resolve_group_symbols`) rather than needing a bespoke factor definition. Captured in that doc's HMM Variants section, not just here — this
    is a content fix to the source doc, not a pointer to it.

### Dependency

Defer until a second domain has real candidates ready to govern — no longer assumed to be `alpha_pattern` by default; see item 20 above. `ensemble_strategy` (Phase 142B.1) is the more concrete near-term candidate and the lower-risk one to build the MVP against first. Build the Minimal Viable Version informed by whichever domain actually gets there first.

---

## When to Add a New Registry

A registry earns its cost when all three are true:

1. **Mutable membership** — the set can grow, shrink, or change state over time
2. **External consumers need enumeration** — dashboard, SQL, or ML pipelines discover members without importing Python
3. **Metadata enrichment has actual consumers** — labels, descriptions, groupings, or gates are read by something concrete

Not worth it for: mathematical constants, schema identifiers, internal codes no consumer enumerates, fixed sets that never change.

---

## Full Comparison

Type 2/3 registries only, for the same reason as "What Exists" above — APR isn't a peer on this axis. For APR's own gate/audit/service model, see `docs/foundation/adaptive-parameter-registry.md`.

| | Shadow Registry (legacy, not migrating) | Controlled Vocabulary | Concept Registry |
|---|---|---|---|
| Identity table | `shadow_registry` | `controlled_vocabulary` | `concept_registry` |
| Gate params | in registry row | — | `concept_gate_template` (domain default) + `concept_gate` (per-concept override) |
| Eval provenance / batch FDR | — | — | `concept_eval_run` — ties results to corpus build, tracks batch size for FDR |
| Eval state | in registry row | — | `concept_eval_state` (latest-cycle cache only, not history) |
| State audit log | `shadow_transition_log` | — | `concept_transition_log` (includes `candidate_timeout`) |
| Knowledge — thesis/failure modes | — | — | `concept_annotation` |
| Knowledge — dependency graph | — | — | `concept_dependency` |
| Knowledge — regime IC history | — | — | `concept_regime_ic` — new row per `eval_run_id`, full trend preserved |
| Knowledge — redundancy evidence | — | — | `concept_correlation` — within-domain pairwise correlation, not asserted |
| OOS enforcement | No | — | Yes — `gate_eval_method` required |
| Regime-conditional gate | No | — | Yes — `regime_scope` |
| Sustained promotion | No | — | Yes — `min_promotion_consecutive` |
| Decay tracking | No | — | Yes — `decay_ratio` vs `baseline_metric`, full history via `concept_regime_ic` |
| Candidate staleness | No | — | Yes — `max_candidate_age_days` auto-demotes unevaluated candidates |
| Lineage | No | — | Yes — `parent_concept_id` |
| Redundancy | No | — | Yes — `redundancy_group`, scoped within-domain, displacement gated on `concept_correlation` evidence |
| Scales to 10K+ candidates | No (36 hand-registered, legacy) | N/A | Yes — `concept_gate_template` means most candidates need zero manual gate config |
| Enable/disable | `is_shadow` bool | — | `enabled` independent of `status` |
| Service | Shadow auditor | `VocabularyService` | `ConceptRegistryService` |
| Loading | Eager | Eager | Active/shadow eager; candidates lazy |
| Dashboard | — | `/api/vocabulary/{ns}` | `/api/concepts/{domain}` |
