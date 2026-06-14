---
phase: 123
plan: "03"
subsystem: architecture-docs
tags: [ecl, setup-confidence-patterns, architecture-doc, ctf-annotation, phase-119]
dependency_graph:
  requires: [123-01]
  provides: [ecl-doc-consistent]
  affects: [docs/architecture/setup-confidence-patterns.md, src/intelligence/CLAUDE.md]
tech_stack:
  added: []
  patterns: [ecl-boundary-invariant, annotation-not-gate]
key_files:
  created: []
  modified:
    - docs/architecture/setup-confidence-patterns.md
    - src/intelligence/CLAUDE.md
decisions:
  - "Phase 119 section preserved as historical inventory but reframed: dual HMM+CTF gate dissolved in Phase 123; all plugins now uniform (single regime gate + ECL annotation)"
  - "ECL boundary invariant extended with explicit Only-the-HMM-gate phrasing"
  - "'dual gate structure' reference in src/intelligence/CLAUDE.md corrected to single regime gate"
metrics:
  duration_minutes: 8
  tasks_completed: 2
  files_changed: 2
  completed_date: "2026-06-14"
---

# Phase 123 Plan 03: Architecture Doc ECL Reconciliation Summary

**One-liner:** Reconciled setup-confidence-patterns.md with Phase 123 ECL boundary - Phase 119 dual-gate category dissolved, explicit HMM-only-suppression invariant added, stale cross-references corrected.

## What Was Done

### Task 1: Reconcile Section 7 + Pattern 5 with dissolved Phase 119 category (769f5a80)

Sections requiring edits:

**Pattern 5 (Section 2):** "ctf_score float comparison" appeared in the list of early gate checks, implying CTF is still a gate. Fixed: removed from gate list, added explicit note that post-Phase-123 ctf_score comparison only computes the `ctf_confirmed` ECL annotation.

**Section 7 Phase 119 intro:** Added statement that Phase 119 plugins "originally had a dual HMM+CTF gate" and that "Phase 123 dissolved that category" - they now follow the uniform pattern (single regime gate + ECL annotation). No structural difference remains between Phase 118 and Phase 119 plugins.

**Section 7 _I7_I6_EXEMPT subsection:** "dual gate" replaced with "single regime gate + I6 CTF ECL annotation" to reflect post-123 terminology.

**Section 5 ECL boundary invariant:** Extended with explicit phrasing: "Only the HMM regime gate may suppress emission; all extrinsic confidence vectors (CTF, zone_friction, exhaustion) are annotations on the emitted signal, never gates."

Sections already ECL-consistent (no changes needed):
- Section 3 Gate Thresholds: _MIN_CTF_SCORE correctly framed as annotation threshold, not gate
- Section 4 Vocabulary: EXTRINSIC CONFIDENCE VECTOR correctly defined as "Never a gate"
- Section 5 ECL body: regime gate exception, counterfactual rationale already correct
- Section 9 Anti-patterns: CTF gate already presented as WRONG pattern
- factor_scores: already described as universal in Pattern 3 code block and Section 4 table

### Task 2: Cross-reference cleanliness for old filename

`grep -rln "i7-setup-confidence-patterns" docs/ src/ tests/` returns only:
- `docs/plans/2026-06-14-v2.10-signal-architecture-refactor.md` - historical spec narrative describing the rename event (acceptable, not a live navigation ref)

Additionally fixed: `src/intelligence/CLAUDE.md` line 44 referenced "dual gate structure (HMM regime + I6 ctf_score before OHLCV)" - corrected to "single HMM regime gate before OHLCV (I6 ctf_score is an ECL annotation, not a gate)". This file already uses the correct new filename.

Live cross-references in `docs/foundation/glossary.md` correctly point to `setup-confidence-patterns.md`.

No `git mv` performed - file already at correct path.

## Deviations from Plan

None - plan executed exactly as written.

## Verification Results

| Check | Result |
|-------|--------|
| `_PHASE_119_PLUGINS` in doc | PASS - zero hits |
| `dual HMM+CTF gate` in doc | PASS - only in Phase 119 historical context paragraph (clearly marked dissolved) |
| `i7-setup-confidence-patterns` in docs/ src/ tests/ | PASS - only historical v2.10 spec narrative |
| `ECL boundary invariant` + `Only the HMM regime gate` | PASS - present in Section 5 |
| `factor_scores` present and universal | PASS - Pattern 3, Section 4, Section 6, Section 10 |
| CTF gating as WRONG pattern | PASS - Section 9 Anti-pattern 1 |
| `_I7_I6_EXEMPT` subsection preserved | PASS - intact with 8 plugins listed |

## Self-Check: PASSED

Files verified present:
- FOUND: docs/architecture/setup-confidence-patterns.md
- FOUND: src/intelligence/CLAUDE.md

Commit verified in git log:
- FOUND: 769f5a80 - docs(123-03): reconcile setup-confidence-patterns.md with Phase 123 ECL boundary
