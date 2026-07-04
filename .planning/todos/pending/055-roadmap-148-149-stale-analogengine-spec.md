# ROADMAP.md Phases 148-149 (AnalogEngine) still spec the pre-rescope design — will silently revert D4 if planned as written

**Renumbered 2026-07-04:** phases 143-152 were renumbered into logical dependency order (nothing
past Phase 142B.1 had execution artifacts, so this was a safe textual pass). What this todo
originally called "Phase 145/146" is now **Phase 148/149**; "Phase 147" (Feature Primitives) is
now **Phase 150**. Body below updated to match; original finding and scope unchanged.

**Found:** 2026-07-03, via Fable review of intel-10/intel-11 (`.planning/research/2026-07-03-intel10-11-fable-review.md`, finding F2).

`ROADMAP.md` Phase 148 (AnalogEngine — Embedding Substrate + Retrieval) and Phase 149 (AnalogEngine
— IC Factory + Scoring Engine + Enrichment) still specify `feature_ic_stats`, `similarity_pairs`,
`score_cache`, Score Objects, `analog-enricher`, `embedding_feature_registry` — all of which
`docs/ideas/intel-13-analog-engine.md` (2026-07-02, the topdown-architecture rescope, decision D4)
deleted in favor of analog predictors + a return-distribution primitive living in the shared
Measurement Engine, not a bespoke parallel scoring stack.

Phase 149's closing note explicitly tells a future planner to revisit
`intel-10-confluence-detection-persistence-layer.md` "once this phase produces validated
analog-based confluences" via the Score Object path — a path intel-13 already closed and the
2026-07-03 intel-10 rewrite removes the reference to entirely.

**Risk:** if Phase 148/149 are planned from the ROADMAP text as it stands today (rather than from
intel-13), the D4 rescope silently un-happens — the team rebuilds the exact parallel-system shape
intel-13 spent a full review deleting.

**Action:** rewrite ROADMAP.md Phases 148-149 requirements against `intel-13-analog-engine.md`
before either phase is planned. Also update Phase 149's stale closing note and Phase 150's note
(both currently point at the old intel-10, which the 2026-07-03 rewrite retitles/restructures).

**Blocked on:** nothing structurally, but do it as its own focused pass — it requires reconciling
the full ANALOG-01..09 requirement list against intel-13's substrate-first structure, not a
find-replace. Do before Phase 148 is planned; no urgency before then.

**Progress (2026-07-03, ROADMAP reconciliation pass — `.planning/research/2026-07-03-roadmap-reconciliation.md`):**
- ✅ Done: Phase 149/150's dead pointers to the old intel-10 fixed. v3.2 milestone-goal paragraph
  rewritten against intel-13 (was "independent System 2," violated one-model-one-book). Phase 148's
  Depends-on now encodes the v3.15 conditioning prerequisite (F1) and the current EIC-04 FAIL status.
- ⏳ Still open (this todo's original scope, unchanged): Phase 148 ANALOG-01..05 and Phase 149
  ANALOG-06..09's full requirement bodies still spec `feature_ic_stats`/`similarity_pairs`/
  `score_cache`/Score Objects/`embedding_feature_registry` — none of these rewritten yet. Also:
  Phase 148's ANALOG-02 `embedding_feature_registry` table should become a `concept_registry` row
  per `embedding_version` (D9/intel-13), and ANALOG-01's "why not IC-weighted at index time"
  paragraph should point at a deferred capability (intel-13 Open Q5 — IC-weighted re-ranking
  waits until plain-cosine predictors demonstrate IC), not a sibling requirement.
