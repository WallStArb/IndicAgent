# Idea Catalog — Full-Tree Index

**Version:** 1.3
**Status:** current
**Last Updated:** 2026-07-12 (see audit note below; earlier audit notes follow for history)
**2026-07-12 audit:** housekeeping/consolidation pass. Archived 4 docs (see Archived section) and
corrected the `docs/plans/` table's HMM/GARCH/Kalman migration row (status was blank, work is
actually complete). Separately, ROADMAP.md turned out to have 6 dead-path citations across 3
docs still using pre-2026-07-07-rename `.planning/research/...` paths, plus 5 more using other
stale filenames (`canonical-simulator.md`, `controlled-vocabulary.md`, `intel-10-...`,
`intel-14-integrity-monitor.md`, `i6-confluence-expansion.md`) — all fixed in ROADMAP.md directly;
none of those required touching this catalog. First pass over-archived two docs
(`fable-2026-07-01-v3-architecture-review.md`, `fable-2026-07-03-roadmap-reconciliation.md`) as
apparently-orphaned before discovering ROADMAP.md's dead-path citations to them — restored, see
Archived section note for the full account.
**2026-07-07 audit:** catalog had drifted from the real `docs/ideas/` directory
since 2026-07-03 — two independent rename waves, 930cdebd and fc067a2b, left ~9 links pointing at
pre-rename filenames, and ~50 rows pointed at docs already physically archived with no catalog
update. Both classes fixed this pass; see the Archived section below for what was removed and why.
Also found and deleted a genuine zombie duplicate — `docs/ideas/ensemble-alpha-lifecycle.md` was a
stale pre-correction copy of content already deliberately archived 2026-07-02 (`db2c0812`) and
already restored into `measurement-governance-monitor.md`; it reappeared wholesale in a later,
unrelated commit (`917b40e1`) and was carried forward by the rename sweep without anyone noticing
it was dead weight.)

**2026-07-11 audit:** caught the catalog drifting again, four days after the last pass. Fixed:
(1) the AnalogEngine row still linked `intel-analog-engine.md`, deleted when that doc was renamed
to PrecedentEngine (`1d41f1da`) — link and title corrected; (2) the Interaction Factory row still
said "blocked on pilot test (037)" — the doc itself was rewritten 2026-07-10 when the pilot
cleared, row brought into sync; (3) five `docs/plans/` docs created 2026-07-09 through 2026-07-11
were never added to the plans table; (4) ETF Universe Expansion and the AlphaEngine V1 Execution
Plan rows both described stale in-progress states for work that finished weeks ago; (5) the
References footer still pointed at pre-2026-07-07 `.planning/research/` paths and was missing
the 2026-07-09 winner's-curse peer-group review.

**2026-07-07:** `docs/ideas/` renamed to `docs/research/` (all live docs already Fable-reviewed,
moved to a persistent location outside GSD's periodic `.planning/` cleanup cycle); the 9
`.planning/research/fable-*.md` architecture-review docs were consolidated in alongside them for
the same reason. `docs/ideas/` remains the landing spot for new, not-yet-reviewed ideas.
**Purpose:** single point of navigation across every live idea/plan doc in `docs/research/` and
`docs/plans/`. Supersedes `docs/research/ai-index.md` (narrower scope, broken links after files were
renamed — archived, see note at bottom).
**Maintenance rule:** when a doc is created, retitled, retired, or superseded, update its row here
in the same commit. Archived docs are not listed individually below — see `docs/research/archive/`
and `docs/plans/archive/` directly; a doc's row here should be deleted, not left dangling, once
archived.
**Fable-reviewed** column: ✅ = carries `Author: Fable 5` / `Informed by: Fable 5` provenance from
an actual review pass; blank = never reviewed. Don't confuse "draft" status with "unreviewed" —
they're independent axes.

**For a high-level, low-detail view** — what's weak in each major area and what's being proposed,
across the whole system (not just Cluster 1) — see `roadmap-scope-map.md`. This catalog is full
navigation depth; that doc is the one-page product-management view.

---

## Cluster 1 — v3.0 Intelligence Lifecycle (the active build surface)

**Master priority doc for this whole cluster:**
[Intelligence Lifecycle Backlog Matrix](intelligence-lifecycle-backlog-matrix.md)
— HIGH/MEDIUM/LOW triage across everything below, refreshed against real code/DB state (not
assertion), last rewritten 2026-07-08. Read this first for "what's next," not this catalog.

| Doc | Status / Priority | Fable-reviewed | One-line |
|---|---|---|---|
| [Confluence — a Governed Predictor Family](intel-confluence-detection-persistence-layer.md) | draft, high | ✅ (v3, 2026-07-12) | Confluences as governed predictors, not a second system; gates 1-6, mandatory shrinkage; re-verified against Phase 143's executed lifecycle mechanics (promotion bar, sign-symmetry, decay gates corrected) |
| [StratificationDimension — Multi-Regime Layer](stratification-dimension-unification.md) | draft, high | ✅ (2026-07-06) | Unifies per-symbol HMM + cross-sectional regime systems; core proposal confirmed, updated against Phase 143's LIFECYCLE-00 hardening |
| [PrecedentEngine](intel-precedent-engine.md) (renamed from AnalogEngine, `1d41f1da`) | draft, high | ✅ | Non-parametric K-NN retrieval as a predictor family; Score Object deleted, return-distribution primitive kept |
| [IntegrityMonitor — Drift, Decay, Ensemble Health](measurement-governance-monitor.md) | draft, high | ✅ (2026-07-06) | Reconciled cluster doc; 7 stale passages found/fixed against executed Phase 143 (pre_shadow_weight was dead, registry amendments, staleness design, schema) |
| [MeasurementEngine — IC Kernel Unification](measurement-ic-engine.md) | answered | ✅ (2026-07-06) | Kernel-unification question resolved by existing `ic_math.py`; unfixed config drift between `ic_engine.py`/`ensemble_ic_engine.py` flagged |
| [AlphaEmitter — Stage 4 Emission Mechanisms](measurement-alpha-emission.md) | idea, not planned | ✅ (2026-07-07) | Threshold-crossing is structurally fine; real gaps are uncalibrated thresholds (EM-CAL), stratum-constant CI gate, weight-staleness blindness; gate stack as the swappable unit, three rejections recorded |
| [Unified Concept Registry](concept-unified-registry.md) | design complete, not built | ✅ (4 passes, 2026-07-06) | Cross-tier lifecycle governance unifying feature + intelligence tiers; adversarial stress-test survived (event-sourcing/graph-DB/full-separation alternatives rejected); MVP build trigger fired (todo 058), zero `concept_*` tables exist yet |
| [Governance & Registries](concept-governance-registries.md) | — | ✅ (2026-07-06) | Umbrella framework for three registry types: Parameter (APR), Lifecycle (Concept Registry), Vocabulary (Tag + Controlled); links to canonical docs |
| [Stratification & Classification Registries](stratification-governance-registries.md) | — | | Sibling umbrella to Governance & Registries, scoped to "what state/kind an instrument or market is in": StratificationDimension, Security Classification Hierarchy, Instrument Tag Calibrator |
| [Edge Source Thesis](data-edge-source-thesis.md) | draft, high | | T1-T4 falsifiable theses on where edge comes from; standing doc, revisit per thesis |
| [Canonical Simulator](platform-canonical-simulator.md) | draft, high | ✅ (v2.1, 2026-07-12) | One counterfactual ledger + cost kernel + run identity, not a replay engine; enforced via pre-commit Check 9; both open questions settled against shipped Phase 142B, priority downgraded critical→high |
| [Trade Construction Layer](trade-construction-layer.md) | draft, high | | Forecast → position; v4.0 concern, gated on the T3 falsification result |
| [Instrument Tag Calibrator](stratification-instrument-tag-calibrator.md) | draft, high | ✅ (2026-07-06) | Todo 040/Phase 145 (renumbered 2026-07-04); found and fixed a missing FDR correction (~1,600 simultaneous tests/run) and a worked example violating the live weight CHECK |
| [Interaction Factory](intel-feature-interaction-factory.md) | historical/reference — superseded as an active spec | | Todo 037's pilot (2026-07-10, PASS 22.2%) cleared this doc's evidence trigger, but Phase 150 independently rejected the combinatorial mechanism on BH-FDR power grounds and built a curated theory-motivated layer instead; kept for context, not an implementation target |
| [Controlled Vocabulary](concept-controlled-vocabulary.md) | idea, unscheduled | ✅ (2026-07-06) | Ready to build whenever prioritized; staging order was inverted (would've built against archived tables first) — fixed |

---

## Cluster 2 — Pre-v3.0 Intelligence Backlog (I1-I9 era) — ⚠️ process conflict, unresolved

**Audit finding (2026-07-07), not yet resolved — needs a human call, not a mechanical catalog fix.**
All five docs previously listed here (`intel-01-momentum-acceleration.md`,
`intel-02-second-derivative-indicators.md`, `intel-03-future-indicators.md`,
`intel-06-regime-transition-detection.md`, `intel-08-macro-cross-asset.md`) are already sitting in
`docs/research/archive/`. But `.planning/todos/pending/060-...md`, created 2026-07-05, explicitly asked
for these five to be individually reviewed against the live Feature Factory before any archive
decision — "these five are genuinely unresolved, not just stale-and-unreviewed... check before
assuming dead." They were bulk-archived anyway the next day (`53871ec3`, 2026-07-06 10:30am) with a
one-line blanket justification ("superseded by intel-10+") that shows no evidence the per-doc review
todo 060 called for actually happened. Todo 060 is now stale in premise (it assumes these docs are
still live and awaiting review) but its underlying question — was real, still-relevant content
thrown away without the review that was explicitly requested — has not actually been answered either
way. Left as an open flag rather than silently closing todo 060 or asserting the archival was fine.

---

## Cluster 3 — Cross-Cutting / Standalone

**Consolidated 2026-07-07** from the old Clusters 3-8 after an audit found nearly all of their rows
already pointed at docs physically archived — see the Archived section below for the full account
of what was removed and why. These three are what's actually still live.

| Doc | Status / Priority | Fable-reviewed | One-line |
|---|---|---|---|
| [Security Classification Hierarchy](stratification-security-classification-hierarchy.md) | draft, medium (build gated on individual-equities onboarding) | ✅ (2026-07-06) | GICS-style strict layer (3 new effective-dated tables) + custom soft taxonomies as `tag_vocabulary.parent_tag`; two epistemic models, deliberately not one tree; redesigned consumer item 6, fixed a silent point-in-time corruption risk |
| [Renaissance Primitives — OHLCV Expansion](signal-renaissance-primitives-ohlcv.md) | idea, not planned | | OHLCV-derived primitives for Signal Processing Layer (499+ raw signals approach); its Temporal Coordinate Primitives section now points to the doc below |
| [Calendar Primitives](signal-temporal-atomic-primitives.md) | adopted into Phase 151 | ✅ (2026-07-13) | Calendar-primitive doctrine (coordinates-vs-flags tier placement), 22→21-primitive inventory, 3 new atomic candidates (`quarter_cycle`, `tdom`, `minute_of_hour`), `opex_flag`/`quad_witching_flag` tier-1 split, OPEX/quarterly-seasonality test design; closes todo 104 |
| [AlphaEngine — Alternative Data Extension](data-alt-data-sources.md) | adopted as Phase 154 | ✅ (2026-07-06) | Extending AlphaEngine to alt-data sources; original table architecture rejected and redesigned around the live `context_features` precedent |

---

## docs/plans/ — Approved / Active Plans (distinct from `docs/research/` — these carry more commitment)

| Doc | Status | One-line |
|---|---|---|
| [2026-06-20: v3.0 Ground-Up Architecture](../plans/2026-06-20-alphaengine-architecture.md) | Approved design | The v3.0 rebuild's foundational architecture doc |
| [2026-06-25: v3.0 Alpha Lifecycle Schema](../plans/2026-06-25-v30-alpha-lifecycle-schema.md) | APPROVED | Referenced by Phases 142A/142B/147 (renumbered 2026-07-04) |
| [2026-06-19: HMM/GARCH/Kalman APR Migration](../plans/2026-06-19-hmm-garch-kalman-apr-migration.md) | Complete — migration 153 live; `feature.hmm.*` keys read in `src/intelligence/services/hmm_trainer.py` | APR migration plan for HMM/GARCH/Kalman params (2026-07-12: status corrected, was blank; doc's own checklist was never updated but the work shipped) |
| [2026-06-26: Salvageable AI & Intelligence Concepts from v2.x](../plans/2026-06-26-salvageable-ai-concepts.md) | EXTRACTED | What survived the v2.x → v3.0 transition |
| [2026-06-27: ETF Universe Expansion](../plans/2026-06-27-etf-universe-expansion.md) | Complete — applied 2026-07-01 | 58→80 instruments live (migrations 188/190); DB-verified 80 active instruments |
| [2026-06-28: HMM Regime Audit & Optimization](../plans/2026-06-28-hmm-regime-audit-optimization.md) | — | Companion to todo 026 |
| [2026-06-28: Renaissance Obstacle Map v3.1+](../plans/2026-06-28-renaissance-obstacle-map.md) | Planned, unblocked after V1 corpus rerun | Obstacle map for the v3.1+ path |
| [2026-06-30: AlphaEngine V1 — Methodology Hypotheses](../plans/2026-06-30-alphaengine-methodology-hypotheses.md) | Active | Three hypotheses requiring empirical validation |
| [2026-06-30: AlphaEngine V1 — Execution Plan](../plans/2026-06-30-alphaengine-v1-execution-plan.md) | Phase A/B COMPLETE; superseded by later phases | Tracked Phase A/B execution only; Phase 142A/142B/143/143.1 have since shipped — see ROADMAP.md for current state |
| [2026-07-01: Cross-Sectional Regime Model Implementation](../plans/2026-07-01-cross-sectional-regime-model.md) | — | Implementation plan for the `market_regimes` cross-sectional system |
| [2026-07-11: IC Quality & Sign-Symmetry Strategy](../plans/2026-07-11-ic-quality-and-sign-symmetry-strategy.md) | Strategy — sequencing agreed, fixes not yet implemented | Synthesizes todos 091/093/094/096/088 sequencing; full design for Phase 143.1 |
| [SHADOW-REVIEW: Phase 147 Live Promotion Criteria](../plans/SHADOW-REVIEW.md) | FROZEN | Numerically-evaluable live-promotion gate criteria, committed before any shadow data exists |
| [Methodology Change Ledger](../plans/methodology-change-ledger.md) | STANDING, append-only | Every methodology change, forever — read before trusting any historical IC number |
| [OOS Evaluation Protocol](../plans/OOS-EVAL-PROTOCOL.md) | — | Pre-commit OOS evaluation protocol |

---

## Archived (pointer only — do not list rows here, browse directly)

- **Archived 2026-07-12** (housekeeping pass, verified against this catalog's own status
  columns before moving — not just an inference pass): `docs/plans/archive/2026-06-26-renaissance-optimization-roadmap.md`
  (already self-labeled SUPERSEDED) · `docs/plans/archive/2026-07-09-ic-null-calibration-design.md`
  + `2026-07-09-ic-null-calibration-plan.md` (diagnostic executed, closed via
  `.planning/todos/completed/071-measurement-diagnostics-null-calibration-ic-decomposition.md`,
  follow-up now lives as todo 091) · `docs/plans/archive/2026-07-09-interaction-primitives-partial-ic-pilot-plan.md`
  (already labeled Executed/PASS in this table). Explicitly evaluated and **kept live, not
  archived**, despite looking superficially similar: `2026-06-20-alphaengine-architecture.md`
  (still the cited foundational architecture doc, not superseded), `fable-2026-07-03-canonical-simulator-review.md` /
  `fable-2026-07-03-intel10-11-review.md` / `fable-2026-07-04-concept-registry-cluster-review.md`
  (this catalog's References section deliberately keeps all 9 dated Fable reviews live as a
  citable audit trail — archiving any of the 9 individually would break that), `data-alt-data-sources.md`
  (adopted-and-kept status, same pattern as `ETF Universe Expansion` above), and
  `fable-2026-07-01-v3-architecture-review.md` / `fable-2026-07-03-roadmap-reconciliation.md`
  (a first pass nearly archived these two as orphaned — absent from this catalog's own
  References list — but ROADMAP.md turned out to cite both substantively, 5 times total, via
  dead pre-2026-07-07-rename paths that a plain filename grep for the *current* name doesn't
  catch; restored, and ROADMAP.md's paths fixed instead, in the same session), and
  `stratification-security-classification-hierarchy.md` (legitimate future idea gated on
  individual-equities onboarding, not dead).
- `docs/research/archive/` — superseded idea docs, including `intel-10-v2-confluence-persistence.md`,
  `intel-11-dual-system-discrete-vs-portfolio.md`, and the pre-consolidation AnalogEngine/
  IntegrityMonitor/StratificationDimension doc sets that fed intel-12/13/14.
- **Archived 2026-07-05** (self-flagged stale, no further review needed): `intel-04-confluence-patterns.md`
  (superseded by intel-10) · `intel-05-i6-confluence-architecture.md` (v2.x-era, I1-I7 tier archived
  2026-07-02) · `intel-07-hmm-multi-tf-training.md` (superseded by the shipped HMM improvement plan) ·
  `intel-09-stack-latency.md` (latency work for the now-archived I1-I7 stack) · `platform-04-kubernetes.md`
  (contradicts CLAUDE.md's explicit no-Kubernetes-HPA rule). At the time, Cluster 2's remaining
  pre-v3.0 docs (intel-01/02/03/06/08) were deliberately left alone pending individual review
  (todo 060) — **superseded by the 2026-07-07 finding in Cluster 2 above: they were bulk-archived
  the very next day anyway, without that review happening.** Left there, not restated here.
- **Audited 2026-07-07 — catalog rows removed for docs already physically archived (~50 rows, old
  Clusters 3/4/5/6/7/8). Each confirmed absent from `docs/research/` root and present under the same
  filename in `docs/research/archive/` before its row was removed — none of these are renames (the
  renamed-but-still-live docs from the same two rename commits were fixed in place above, not
  removed):**
  - **AI / ML / Agentic** (old Cluster 3, all 13 rows): `ai-01` through `ai-11`, `ai-occam-razor.md`,
    `ai-swarm-performance-analysis-2026-05-27.md`, `ml-ai-palette.md`.
  - **Platform / Infrastructure** (old Cluster 4, 7 of 8 rows — Security Classification Hierarchy
    survives into Cluster 3 above): `platform-01` through `platform-03`, `platform-05` through
    `platform-08`.
  - **Signal / Trade Layer** (old Cluster 5, all 9 rows): `2026-06-08-signal-trade-separation-architecture.md`,
    `signal-01` through `signal-07`, `sr-zone-engine-improvements.md`. `signal-08-intelligence-refactor.md`
    is the one exception — it did NOT archive, it **graduated**: promoted to
    `docs/foundation/v3-north-star.md` (the canonical v3.0 origin document) in the same 2026-07-06
    reorg commit that renamed everything else, exactly matching the 2026-07-01 backlog matrix's flag
    that this was "possibly the actual v3.0 Feature Factory precursor."
  - **Product Vision** (old Cluster 6, all 8 rows): `vision-01` through `vision-07`,
    `commercialization-retail-saas.md`.
  - **Renaissance Philosophy** (old Cluster 7, 3 of 4 rows — the OHLCV primitives doc survives into
    Cluster 3 above, renamed to `signal-renaissance-primitives-ohlcv.md`): `renaissance-01` through
    `renaissance-03`.
  - **Ops / Misc** (old Cluster 8, 5 of 6 rows — the alt-data doc survives into Cluster 3 above):
    `bi-analytics-layer-design.md`, `futures-roll-simplification.md`,
    `latency-and-persistence-audit-design.md`, `phase142-redesign-musk5step-audit.md`,
    `eai-phase-recommendations.md`.
  - **Cluster 1 (2 rows, no caveat attached — unlike Cluster 2 below, nothing in the archive
    commit or elsewhere flagged these as needing review first):** `cross-group-lead-lag-ic.md`,
    `comomentum-crowding-metric.md`.
  - **Genuine duplicate deleted outright (not archived, since a corrected archived copy already
    existed):** `docs/ideas/ensemble-alpha-lifecycle.md` — a stale pre-correction snapshot of
    content deliberately archived 2026-07-02 (`db2c0812`, with its cascade-scenario reasoning
    restored into what is now `measurement-governance-monitor.md`), accidentally resurrected
    wholesale in an unrelated commit (`917b40e1`) and carried forward by the later rename sweep
    without anyone checking it was dead weight. `docs/research/archive/alpha-ensemble-lifecycle.md`
    remains the one authoritative (corrected) historical copy.
- `docs/plans/archive/` — superseded plan docs, including the pre-142A IC-engine-improvements and
  feature-scoring-beyond-ic plans (content now carried in `measurement-ic-engine.md`).
- `docs/research/ai-index.md` — **archived by this catalog 2026-07-03.** Its own links were stale
  (referenced `qualagent-vision.md`-style filenames that no longer match the current
  `vision-0N-*.md` naming). The old Cluster 3 (now removed, see above) replaced it; that content
  has since also been fully archived.

## References

- `docs/research/fable-2026-07-02-v3-topdown-architecture.md`, `fable-2026-07-02-v3-bottomup-audit.md`,
  `fable-2026-07-03-intel10-11-review.md`, `fable-2026-07-03-canonical-simulator-review.md`,
  `fable-2026-07-04-concept-registry-cluster-review.md`, `fable-2026-07-06-end-to-end-architecture-review.md`,
  `fable-2026-07-07-phase144-conditioning-decision.md`, `fable-2026-07-07-renaissance-layer-refinements.md`,
  `fable-2026-07-09-ensemble-winners-curse-peer-group.md` — the Fable review passes this catalog's
  "Fable-reviewed" column tracks (paths corrected 2026-07-11: these moved from `.planning/research/`
  into `docs/research/` on 2026-07-07 and this section still pointed at the old location)
- `docs/research/intelligence-lifecycle-backlog-matrix.md` — the priority triage for
  Cluster 1; this catalog is navigation, that doc is sequencing
