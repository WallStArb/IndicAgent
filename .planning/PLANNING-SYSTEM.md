# Planning System Guide

How ideas, todos, roadmap, and phases relate and flow into each other.

---

## Objectives (above the backlog)

**File:** `.planning/OBJECTIVES.md` (owner ruling 2026-11-27)

The owner gives the system objectives; the lead turns each into todos and phases and assigns or spawns the workers.

- The owner writes OBJECTIVES.md: each objective has an id (`O1`, `O2`, ...), an outcome, a measurable done-criterion, constraints and vetoes, a priority, a status and its source. The lead proposes a new or changed objective in a commit for the owner to confirm; it never invents one.
- Every todo names the objective it serves: `objective: O<n>` as a top-level key of its line-1 frontmatter. Required on every todo numbered above 687 (the highest number when the layer landed, `OBJECTIVE_REQUIRED_AFTER` in `tools/todo_claims.py`), optional on older ones, and checked wherever it is set. A todo that serves no objective is a question for the owner, not a todo.
- Enforced by `tests/unit/test_todo_priorities_link_integrity.py` through `tools/todo_claims.py`: ids unique in OBJECTIVES.md, one `objective:` line per todo, its value an id of the table.

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

**Numbering:** Sequential (`018-topic.md`). Don't renumber when todos complete — move to `completed/`.

**When to create a todo:** When an idea has a clear problem statement and solution scope,
and you intend to execute it within the next 1-3 milestones.

**Key distinction from idea docs:** A todo has a defined problem + solution. An idea doc
may just be exploration or vision without a clear "do this" action.

---

### Claiming a todo (idle workers)

An idle worker session claims light work itself instead of waiting for the lead.

- Who marks work claimable: only the lead, by adding `claimable: true` to a todo's frontmatter. It fits a todo that is light, outside every pin closure (no module a live or resumable run imports), needs no heavy job and no owner ruling. Heavy, pinned or owner-ruled work stays lead-assigned.
- A claimed todo is unavailable: a todo carries at most one `claimed_by` line, and a claim commit only adds the two fields to an unclaimed todo; it never edits or replaces someone else's claim (only its holder or the lead changes it; this is procedure, since one valid line after an overwrite looks like any other claim).
- How to claim: `git fetch`, check that the todo on `origin/main` has no `claimed_by`, then in a detached worktree off `origin/main` (never on the shared checkout's main) add `claimed_by: <your ListAgents name>` and `claimed_at: <UTC ISO time, e.g. 2026-11-27T08:00:00+00:00>` as top-level keys of the frontmatter block that starts on line 1 (a claim field anywhere else is no claim), commit only that file and `git push origin HEAD:main`. If the push is rejected, drop your commit and start again from the fetch; never rebase or merge a claim, since resolving that conflict is how two names end up on one todo.
- How to renew or release: a holder still on the work after three days rewrites `claimed_at`; a release removes both fields (finished work closes the todo instead, and a todo in `completed/` or `deferred/` carries no claim). A claim whose `claimed_at` is more than three days old is stale and is released by its holder or the lead.
- Landing: every claimed landing still passes the Done-Coding SOP, is reviewed by an independent reviewer session and is reported to the lead with its sha and that reviewer's session name. Timer-run code is still edited only in a detached worktree off `origin/main`.
- Enforced by `tests/unit/test_todo_priorities_link_integrity.py` through `tools/todo_claims.py`: claim fields only as top-level keys of the line-1 frontmatter, one of each, only on a pending `claimable: true` todo, `claimed_by` a session name (`indicagent-<id>`), `claimed_at` in UTC and not in the future. Staleness is not tested, so an abandoned claim never turns an unrelated worker's suite red: `.venv/bin/python tools/todo_claims.py` lists every claim with its age and exits 1 on a stale or broken one, and the lead runs it in the orient step (1) of every lead-loop cycle and releases or reassigns what it flags.

### Spawning workers (lead)

The lead starts its own headless worker sessions with `scripts/ops/spawn_worker.sh` instead of waiting for the owner to open one.

- Which path: a lead-assigned lane that needs a session of its own and no idle session can take it: spawn. Light work marked `claimable: true`: an idle session claims it. A bounded read, search or review inside the lead's own task: a subagent.
- How: `scripts/ops/spawn_worker.sh --name <name> --todo <N> --brief <file> --model <model> --permission-mode <mode>`. It creates a detached worktree off `origin/main` (`../indicagent-wt-<name>`), runs `claude -p` with the brief on stdin, detached with `setsid`, logging to `logs/agents/<name>.log`, and appends the worker to `logs/agents/workers.jsonl` (append-only). `--list` shows every worker not yet reaped; `--reap` removes the worktree (and its local branch, when merged) of a finished worker once no process runs in it, it is clean (ignored files count, bar tool caches), unlocked and every commit on it has landed on `origin/main`. The registry lives in the primary checkout; one lock serialises spawn and reap.
- Capacity gate: it refuses when the brief lacks one of the seven parts, the todo is not pending on `origin/main`, is claimed or already has a live worker, the name is taken, the live workers reach `infra.spawn_worker.max_workers`, or MemAvailable is under `infra.spawn_worker.mem_margin_gib` plus, while a heavy job is live, the largest `infra.run_guarded.mem_floor_gib.*` floor. A missing APR key refuses (migration 625).
- Permission mode: there is no default. A headless worker cannot answer a prompt, so what it may run is set by the mode and the settings the owner chooses; no session picks a wider mode for itself or a peer (harness SOP guards).
- A spawned worker's landing is reviewed independently like any other (Done-Coding SOP, suite exit code), and the lead reaps it after the landing.

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
5. Todo moves from `pending/` to `completed/`

**STATE.md** tracks the current active phase and overall milestone progress.

**Archiving rule (added 2026-08-11, after the gap it closes let 8 completed phase dirs and 6
completed `docs/plans/` docs drift unarchived for weeks):**
- **Phase directories** (`.planning/phases/NNN-slug/`) are created with a `-planned` suffix
  while unstarted. The moment ROADMAP.md marks the phase ✅ COMPLETE, rename the directory to
  drop the `-planned` suffix in the same session — `git mv`, then fix any internal
  self-references (frontmatter `phase:` fields, `@`-includes, "create X when done" pointers)
  that cite the old path. Do not defer this to a later cleanup pass; it accumulates silently
  because nothing else forces it.
- **`docs/plans/` root files** move to `docs/plans/archive/` once the plan's own stated
  verdict/decision is final and the phase(s) it fed are ROADMAP.md-complete. A plan doc with
  unresolved checkboxes, an explicit "not yet implemented" status line, or no stated verdict at
  all stays at root even if it's old — age alone is not a completion signal. `git mv`, then fix
  any cross-references to the old (non-archive) path the same way as phase directories above.

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
