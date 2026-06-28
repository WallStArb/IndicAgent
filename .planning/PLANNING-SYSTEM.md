# Planning System Guide

How ideas, todos, roadmap, and phases relate and flow into each other.

---

## The Five Layers

```
Observation / Inspiration
        │
        ▼
  .planning/IDEAS.md          ← quick capture, no commitment, no structure
        │
        │  (when worth fleshing out)
        ▼
  docs/ideas/<topic>.md       ← strategy, vision, research — NOT a todo
        │
        │  (when ready to execute: clear problem + solution)
        ▼
  docs/plans/<topic>-plan.md  ← implementation specs, dated, task breakdown
        │
        │  (when actionable and prioritized)
        ▼
  .planning/todos/pending/    ← scoped, actionable, will become a phase
        │
        │  (when prioritized into a milestone)
        ▼
  .planning/ROADMAP.md        ← milestone-ordered list of committed phases
        │
        │  (when ready to execute)
        ▼
  .planning/phases/phase-NNN/ ← PLAN.md files, execution, SUMMARY.md, VERIFICATION.md
```

---

## Layer 1 — IDEAS.md (Inbox)

**File:** `.planning/IDEAS.md`

A bullet-point inbox. No structure required. No commitment to act.
Capture anything: observations, half-formed thoughts, references to docs.

**Rules:**
- One bullet per idea, with a link to `docs/ideas/` if a doc exists
- No frontmatter, no priority, no deadline
- Ideas can live here indefinitely — not everything needs to become a todo

**When to add here:** Any time you have an idea worth not losing.

---

## Layer 2 — docs/ideas/ (Strategy & Vision)

**Directory:** `docs/ideas/`

Narrative docs for ideas worth thinking through. Not todos — some of these
are pure vision (TradeAgent, AegisAgent), some are research (renaissance principles,
regime-adaptive trading), some are architectural analysis (weakness assessment).

An idea doc does NOT mean the work is planned or committed.

**When to create a doc:** When an idea is complex enough that bullet notes won't capture it,
or when you want to think through design, tradeoffs, and priorities in writing.

**Contents:** Problem background, proposed approach, priorities, open questions, files affected.
Use Status frontmatter: `Idea`, `Research`, `Approved`, `Deferred`.

**Relationship to todos:** A todo may reference an idea doc (`files:` field), but an idea doc
does not imply a todo exists. Many idea docs will never become todos — they're strategy
reference or vision that may never ship.

---

## Layer 3 — docs/plans/ (Implementation Specs)

**Directory:** `docs/plans/`

Implementation specs with task breakdowns, migration strategies, and execution plans.
When `docs/ideas/` research has a clear implementation path, write it here as a dated plan.

**When to create docs/plans/:**
- When `docs/ideas/` research has a clear implementation path
- Before creating a phase — write the plan first
- When you need to sequence tasks and estimate effort

**Contents:** Task breakdown, migration strategy, testing approach, rollback plan.
Dated format: `2026-MM-DD-<topic>-plan.md` (e.g., `2026-05-04-structural-zone-engine-plan.md`)

**Relationship:**
```
docs/ideas/<topic>.md (research) → docs/plans/2026-MM-DD-<topic>-plan.md (spec) → .planning/todos/NNN-<topic>.md (actionable)
```

**Key distinction from `docs/ideas/`:**
- `docs/ideas/` = Research, vision, exploration (may never ship)
- `docs/plans/` = Implementation specs, task breakdowns, ready to execute

---

## Layer 4 — .planning/todos/pending/ (Actionable Backlog)

**Directory:** `.planning/todos/pending/`

Scoped, actionable items. A todo means: we know the problem, we know the solution,
and this will eventually become a phase. It is a commitment to act — just not yet.

**Format (Renaissance-grade frontmatter):**
```markdown
---
**Created:** YYYY-MM-DD
**Area:** intelligence | infra | ml | data | operations | ui | tooling
**Type:** bug_fix | improvement | optimization | new_feature | refactor | tech_debt
**Priority:** P0 | P1 | P2 | P3 | P4
**Effort:** ~4 hours | 1-2 days
**Benefit:** What value this delivers (one-line)
**Risk:** low | medium | high (with brief context)
**Gate:** After XXX complete | None
---

# NNN — <title>

## Problem
<What's broken or missing — specific and observable>

## Solution / Fix / What / Why
<Implementation details — specific enough to become a plan>
```

**Frontmatter fields explained:**
- **Created** — Age tracking. A 6-month-old P2 deserves scrutiny.
- **Area** — Domain filtering. "Show me all intelligence todos."
- **Type** — What kind of work. Determines code review focus.
- **Priority** — P0 bugs before P3 features. P0/P1 = blockers; P2 = next milestone; P3/P4 = backlog.
- **Effort** — Expected cost. Know before you start.
- **Benefit** — Payoff. Why do this at all.
- **Risk** — Danger level. Affects review rigor and rollback planning.
- **Gate** — Dependencies. What must complete first.

**Numbering:** Sequential (`018-topic.md`). Don't renumber when todos complete — move to `done/`.

**When to create a todo:** When an idea has a clear problem statement and solution scope,
and you intend to execute it within the next 1-3 milestones.

**Key distinction from idea docs:** A todo has a defined problem + solution. An idea doc
may just be exploration or vision without a clear "do this" action.

---

## Layer 5 — ROADMAP.md + phases/ (Committed Execution)

**Files:** `.planning/ROADMAP.md`, `.planning/phases/phase-NNN/`

The roadmap organizes committed phases into milestones. A phase on the roadmap means
it is planned for a specific milestone and will be executed.

**Flow from todo → roadmap:**
1. Todo is prioritized during milestone planning
2. It gets a phase number and added to the relevant milestone in ROADMAP.md
3. `/gsd-plan-phase` creates the `phases/phase-NNN/` directory with PLAN.md files
4. Execution produces SUMMARY.md per plan and VERIFICATION.md for the phase
5. Todo moves from `pending/` to `done/`

**STATE.md** tracks the current active phase and overall milestone progress.

---

## Decision Guide

| Situation | Action |
|-----------|--------|
| Flash of insight, half-formed thought | Add bullet to `IDEAS.md` |
| Interesting pattern or technique worth remembering | Create `docs/ideas/` doc |
| Architectural vision not on roadmap yet | Create `docs/ideas/` doc, add bullet to `IDEAS.md` |
| Clear problem + solution, will build eventually | Create `todos/pending/` entry, reference idea doc |
| Research ready to execute as implementation plan | Create dated plan in `docs/plans/` |
| Todo is ready to schedule this milestone | Add to `ROADMAP.md`, assign phase number |
| Phase is planned and ready to execute | Run `/gsd-plan-phase` |

---

## What Doesn't Belong

- **todos/pending/** is not a wishlist. If there's no clear solution or no intention to build
  within 2-3 milestones, it belongs in `docs/ideas/` or `IDEAS.md` instead.
- **docs/ideas/** is not a phase plan. No PLAN.md-style task breakdowns go here.
- **IDEAS.md** is not a structured backlog. Keep it loose — that's the point.
- **ROADMAP.md** is not a speculative list. Only committed phases with known milestone targets
  belong here. "Maybe someday" goes in the todo or idea layers.
