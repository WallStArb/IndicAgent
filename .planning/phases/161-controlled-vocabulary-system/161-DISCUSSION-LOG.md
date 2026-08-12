# Phase 161: Controlled Vocabulary System - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-07-16
**Phase:** 161-Controlled Vocabulary System
**Areas discussed:** tag_vocabulary consolidation, drift-audit host daemon, vocabulary grouping/hierarchy, architecture reuse/extensibility (DAG microservice reuse)

---

## tag_vocabulary consolidation

| Option | Description | Selected |
|--------|-------------|----------|
| Keep separate, don't resolve now | tag_vocabulary is confidence-weighted many-to-many; ship CV for its 5 core namespaces only | |
| Subsume tag_vocabulary into this build now | Add instrument tags as a 6th namespace, migrate 71 rows | |
| Explicitly scope-guard as a follow-on decision | Record a concrete revisit gate instead of silent open question | |
| **Resolved via discussion, not a menu pick** | Traced live schema (`instrument_tags`: weight/source/evidence — the only weighted-assignment table in the DB) plus `stratification-security-classification-hierarchy.md`'s Layer 2 design (commits to extending `tag_vocabulary` in place with `parent_tag`) — concluded tag_vocabulary must stay fully separate, permanently, not as a deferred question | ✓ |

**User's choice:** Free-form discussion, converged on "explicitly closed, not deferred" (D-02).
**Notes:** Initial framing offered 3 menu options; user rejected the AskUserQuestion tool call
and asked to discuss in prose instead ("lets discuss"). Discussion then proceeded conversationally
for the rest of the session.

---

## Drift-audit host daemon

| Option | Description | Selected |
|--------|-------------|----------|
| `data_quality_auditor.py` | Existing periodic BaseDaemon, quality-score + alert pattern already matches the drift-check shape | ✓ (Claude's Discretion, low-stakes) |
| A new dedicated auditor daemon | Contradicts the design doc's explicit "not a new service" call | |
| Let the planner/researcher decide | Low-stakes implementation detail | |

**User's choice:** Not explicitly confirmed — carried as Claude's Discretion per the design doc's
own "ride an existing auditor, don't build a new service" instruction.
**Notes:** Never became a live discussion point; user's attention went to the bigger
architecture question below instead.

---

## Vocabulary hierarchy / grouping (regime_hmm, regime_cross_sectional)

**User's prompt:** "many of these concepts have a hierarchy" — pushing on whether the 5-label
HMM regime set and 9-label cross-sectional regime set need a parent/child structure.

**Resolution:** Distinguished exclusive single-parent hierarchy (GICS/SIC-style — wrong fit,
already ruled out by `stratification-security-classification-hierarchy.md`'s own reasoning) from
overlapping multi-dimensional facets (right fit — the existing `vocabulary_group`/
`vocabulary_group_member` many-to-many design). Concrete groups worked out and locked as D-03/D-04:
- `regime_hmm`: `trending`, `transition`, `bullish_bias`, `bearish_bias`
- `regime_cross_sectional`: `low_vol`/`mid_vol`/`high_vol` (vol-tier), `bull`/`neutral`/`bear` (direction)

**Notes:** No new schema required — this is groups to *seed*, not a design gap.

---

## Architecture: flexibility / extensibility / "DAG microservice reuse"

**User's prompt:** "we want to design this to be flexible and extensible... highly scalable and
reusable for other concepts as well - dag microservice reuse... think about this like
Renaissance and Jim Simons."

**Resolution:** Surveyed the full research corpus (`concept-governance-registries.md`,
`concept-unified-registry.md`, `stratification-governance-registries.md`,
`stratification-dimension-unification.md`, `stratification-security-classification-hierarchy.md`,
`fable-2026-07-04-concept-registry-cluster-review.md`) rather than reasoning from scratch.
Findings:
- The project already has a documented "When to Add a New Registry" 3-part test — adopted as
  the standing extensibility rule (D-06).
- `StratificationDimension`'s Protocol design already cites the archived v2.x `PatternPlugin` +
  `validate_tier()` system as validated prior art for "one interface, many pluggable providers" —
  real precedent for the DAG-reuse instinct, at the interface level, not the schema level (D-08).
- `VocabularyService` and `ConceptRegistryService` are already documented siblings in the
  Registry Taxonomy's "Full Comparison" table — same family, deliberately different tables, no
  shared base class.
- `StratificationDimension`'s contract declares `labels: list[str]  # from Vocabulary` — a real,
  already-anticipated future integration point (D-08, informational, out of scope this phase).

**Locked decisions:** D-05 (library not microservice), D-06 (extensibility test), D-07 (no
premature shared base class — extract on the second real instance, per the
`Float32ChunkAccumulator` precedent), D-08 (StratificationDimension integration noted, deferred).

---

## Claude's Discretion

- Drift-audit host daemon (`data_quality_auditor.py`) — low-stakes, not locked as a hard decision.
- Exact migration numbers, `VocabularyService` method signatures, label/description text for the
  5 namespaces, API route placement — all follow the design doc's existing full specification.

## Deferred Ideas

- `tag_vocabulary` unification — explicitly rejected (closed, not deferred).
- Security Classification Hierarchy (GICS-style) — real future work, gated on the
  individual-equities milestone, no ROADMAP phase yet.
- `StratificationDimension` integration — real future connection, sequenced after Phase 144/145,
  itself blocked on the current 143.1-07 corpus re-run.
