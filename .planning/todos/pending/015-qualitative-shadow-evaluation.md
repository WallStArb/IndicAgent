---
created: 2026-05-03T19:00:00.000Z
title: "Qualitative Shadow Evaluation Gate (P-CTX-04)"
area: qualitative
priority: 14
resolves_phase: 89
tier: validation
files:
  - docs/ideas/qualitative-intelligence-layer.md
  - docs/plans/2026-05-02-unified-intelligence-design.md
---

# Qualitative Shadow Evaluation Gate (P-CTX-04)

**Filed:** 2026-05-03
**Priority:** Medium
**Prerequisite:** P-CTX-03a or P-CTX-03b (todos 013 or 014)

## Problem

Qualitative context (earnings, macro) must NOT affect I7 signal confidence or sizing until it has passed shadow-mode evaluation against realized outcomes. Renaissance principle: "Earn the right through proof."

## Solution

Shadow evaluation of qualitative context impact:

1. **Log qualitative context with every signal** — `ctx` JSONB already in intelligence_features
2. **Measure whether ctx improves realized outcomes** — compare signal performance with ctx available vs without
3. **Statistical gate** — only promote to live influence when:
   - N >= 100 signals with ctx context
   - Sharpe improvement with ctx > without ctx, p < 0.05
   - No regime-specific degradation
4. **Automatic promotion** — when gate passes, allow ctx to influence I7 confidence multipliers
5. **Graceful degradation** — if ctx is missing or stale, signals fire exactly as before

### Key constraint from architecture doc

> "Do not allow qualitative context to affect I7 signal confidence or sizing until it has passed shadow-mode evaluation against realized outcomes."

This mirrors the existing I7 shadow governance pattern (Phase 75/77) — same statistical gates, same auto-promotion logic.

## Context

Architecture: `docs/ideas/qualitative-intelligence-layer.md` (Refinement Notes)
Implementation plan: `docs/plans/2026-05-02-unified-intelligence-design.md` (P-CTX-04)
