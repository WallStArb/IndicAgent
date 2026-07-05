---
**Created:** 2026-07-05
**Area:** intelligence
**Type:** tech_debt
**Priority:** P3
**Effort:** ~2-3 hours
**Benefit:** Either salvage real content into v3.0's Feature Factory / Phase 150, or clear dead weight from docs/ideas/
**Risk:** low
**Gate:** None
---

# 060 — Review Cluster 2 legacy intelligence backlog for archive vs. salvage

## Problem

`docs/ideas/idea-catalog.md` Cluster 2 ("Pre-v3.0 Intelligence Backlog, I1-I9 era") holds five docs
of unresolved status: `intel-01-momentum-acceleration.md`, `intel-02-second-derivative-indicators.md`,
`intel-03-future-indicators.md`, `intel-06-regime-transition-detection.md`,
`intel-08-macro-cross-asset.md`. The catalog's own note says "some content may still be salvageable
into v3.0's Feature Factory / Phase 150 — check before assuming dead," but nobody has actually done
that check. Five sibling docs in the same cluster (`intel-04/05/07/09`, plus `platform-04`) were
archived 2026-07-05 because they were already self-flagged as superseded/stale with no ambiguity;
these five are genuinely unresolved, not just stale-and-unreviewed.

## Solution / Fix / What / Why

Read each of the five against the current Feature Factory (`src/intelligence/feature_factory.py`,
~61 functions) and Phase 150's interaction-primitives scope. For each: either (a) extract any
still-missing primitive into a Feature Factory candidate and archive the doc, or (b) archive outright
as fully superseded, or (c) leave as-is with a one-line reason if genuinely still open. Update
`idea-catalog.md` rows accordingly. Not urgent — these are ideas, not blockers — but cheap to resolve
in one sitting rather than five separate context-loads later.
