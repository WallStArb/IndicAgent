---
status: pending
priority: P3
filed: 2026-07-12
source: Phase 144 execution session — user request to unify related stratification/
  classification/governance idea docs under a consistent topic-clustered naming scheme
---

# Rename `docs/research/*.md` to topic-clustered prefixes, unify cross-references

## Decision made (2026-07-12)

User chose **topic-clustered prefixes** over the alternatives (keep existing organic
platform-/intel-/data-/fable- prefixes as-is; or skip renaming, only fix cross-refs). Group by
subject area regardless of authorship, so related docs sort together — e.g.
`stratification-regime-multi-regime-layer.md`, `stratification-security-classification-hierarchy.md`,
`governance-unified-concept-registry.md`.

No existing spec governs `docs/research/*.md` filenames — `docs/foundation/naming-system.md`
only covers code surfaces (Python classes, Kafka topics, DB tables, source file names), not
research-doc filenames. This todo defines the scheme from scratch.

## Proposed cluster map (29 live files, 2026-07-12 census)

**`stratification-*`** (regime/classification providers — what state is the market/instrument in):
- `regime-multi-regime-layer.md` → `stratification-dimension-unification.md` (doc's own title is
  "StratificationDimension — A Unified Conditioning Layer")
- `platform-security-classification-hierarchy.md` → `stratification-security-classification-hierarchy.md`

**`governance-*`** (Concept Registry lifecycle family):
- `platform-unified-concept-registry.md` → `governance-unified-concept-registry.md`
- `concept-governance-registries.md` → `governance-registries-index.md` (it IS the umbrella
  index, name should say so)
- `measurement-governance-monitor.md` → `governance-drift-monitor.md` (currently under
  `measurement-`, but it's IntegrityMonitor/decay governance, not an IC measurement doc — real
  mismatch worth fixing)

**`tags-*`** (instrument tag data — JUDGMENT CALL, see Open Questions #1):
- `data-instrument-tag-calibrator.md` → `tags-instrument-calibrator.md`
- `platform-controlled-vocabulary.md` → stays `platform-controlled-vocabulary.md` or becomes
  `tags-controlled-vocabulary.md`? (see Open Questions #1 — it's explicitly platform-wide, NOT
  instrument-scoped, so may not belong in a tags- cluster at all)

**`predictor-*`** (CaseSubstrate/confluence/interaction family, currently `intel-*`):
- `intel-case-substrate.md` → `predictor-case-substrate.md`
- `intel-confluence-detection-persistence-layer.md` → `predictor-confluence-detection.md`
- `intel-feature-interaction-factory.md` → `predictor-feature-interaction-factory.md`

**`measurement-*`** (already correctly clustered, no rename):
- `measurement-ic-engine.md`, `measurement-alpha-emission.md` — unchanged

**`platform-*`** (infra, already correctly clustered, no rename):
- `platform-canonical-simulator.md` — unchanged

**`data-*`** (sourcing, already correctly clustered, no rename):
- `data-alt-data-sources.md`, `data-edge-source-thesis.md` — unchanged

**`signal-*`** (already correctly clustered, no rename):
- `signal-renaissance-primitives-ohlcv.md` — unchanged

**`execution-*`** (v4.0 forward-looking, currently unprefixed):
- `trade-construction-layer.md` → `execution-trade-construction-layer.md`?  (only one file in
  this cluster today — judgment call whether a 1-file cluster is worth a prefix, see Open
  Questions #2)

**`fable-YYYY-MM-DD-*`** (point-in-time review narratives — JUDGMENT CALL, see Open Questions #3):
- 12 files: `fable-2026-07-01-v3-architecture-review.md`,
  `fable-2026-07-02-v3-bottomup-audit.md`, `fable-2026-07-02-v3-topdown-architecture.md`,
  `fable-2026-07-03-canonical-simulator-review.md`, `fable-2026-07-03-intel10-11-review.md`,
  `fable-2026-07-03-roadmap-reconciliation.md`, `fable-2026-07-04-concept-registry-cluster-review.md`,
  `fable-2026-07-06-end-to-end-architecture-review.md`, `fable-2026-07-07-phase144-conditioning-decision.md`,
  `fable-2026-07-07-renaissance-layer-refinements.md`, `fable-2026-07-09-ensemble-winners-curse-peer-group.md`
  — recommend LEAVING AS-IS, not topic-clustering (see Open Questions #3).

**Meta/index docs (no rename):**
- `catalog.md`, `roadmap-scope-map.md`, `2026-07-08-intelligence-lifecycle-backlog-matrix.md`

## Open Questions (resolve before executing, not silently)

1. **`platform-controlled-vocabulary.md`** — its own text is explicit that it has "deliberately
   zero relationship to instruments," i.e. it is NOT instrument-tag data despite living next to
   `tags-instrument-calibrator.md` topically. Putting it in a `tags-` cluster would misrepresent
   its own stated scope. Recommend leaving it `platform-*` (matches its self-description) rather
   than forcing it into the tags cluster for surface-level topical adjacency.
2. **`trade-construction-layer.md`** — only file that would populate an `execution-*` cluster
   today. A 1-file cluster prefix adds churn (one rename, all its inbound cross-refs) for no
   sorting benefit yet. Recommend deferring this one rename until v4.0 phases add siblings.
3. **Fable review docs (12 files)** — these are narrative point-in-time audits ("what did Fable
   find on this date"), not standing topic references; their own value is chronological
   (`fable-2026-07-0N-*` already sorts by review date, which is how they get referenced — e.g.
   "the 2026-07-04 cluster review"). Recommend NOT topic-clustering these; keep the
   `fable-YYYY-MM-DD-*` scheme as its own, deliberately different, non-topical namespace.

## Scope of the actual sweep

For every renamed file: `git mv`, then grep the WHOLE repo (not just `docs/`) for the old
filename — `.planning/`, `CLAUDE.md`, test files, and other `docs/research/*.md` files all
contain live cross-references (verified this session: `platform-security-classification-hierarchy.md`
alone is referenced by ≥4 sibling docs plus ROADMAP.md). This is the same blast-radius pattern
todo 057 (doc-crossref-phase-renumbering-sweep) already exercises — consider running this as a
follow-on to 057 or reusing its verification method (grep old filename, confirm zero hits,
commit).

**Blocked on:** nothing technical — pure documentation reorganization, no code/schema
dependency. Sequenced as P3 (housekeeping) since it doesn't block any live work; do when doing
another doc-crossref pass anyway rather than as a dedicated session.

## References

- This session's discussion (2026-07-12) — traced ~10 cross-doc references while investigating
  Concept Registry / Security Classification Hierarchy / StratificationDimension relationships;
  the cluster map above reflects that actual traced structure, not a guess.
- `.planning/todos/pending/057-doc-crossref-phase-renumbering-sweep.md` — sibling mechanism/
  precedent for the cross-reference-correction half of this work.
