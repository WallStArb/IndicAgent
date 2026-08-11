# Fast-Cadence AI Collaboration

**Version:** 1.0 (portable)
**Status:** template
**Source:** distilled from ~a year of accumulated session feedback on the IndicAgent project — not ported from an existing `docs/foundation/` doc, because this wisdom lived only in the AI assistant's private memory system, never written down anywhere project-visible until now.

## Why This Doc Exists

[Renaissance Principles](principles.md), [design-principles.md](design-principles.md), and [naming-system.md](naming-system.md) are about what to build and how to name it. This doc is about a different thing: how to keep quality from eroding when the actual work is done by a human directing an AI agent through hundreds of fast, small iterations over months. That's a distinct failure mode from bad architecture — the architecture can be sound and the naming can be precise, and you can still accumulate silent drift, rework, and false confidence purely from the *pace and shape* of AI-paired iteration.

None of this was designed in advance. Every rule below exists because a specific failure happened once, was corrected, and the correction was worth keeping. That provenance matters: don't treat this as a speculative best-practices list to apply uniformly — treat it as documented incident response, the same epistemic status as a gotchas file.

---

## 1. Verification Discipline

**A pasted status report — from a subagent, a prior session, a teammate, or your own memory of an earlier conversation — can be wrong on every detail.** Before acting on a claim of "this is done" or "this is confirmed," re-check it against live ground truth: run the query, read the file, check the actual state. This is not distrust of the reporter; cross-context reports degrade for the same reason any handoff does — details get compressed, and compression loses exactly the details that matter for correctness.

**A code fix and a data/state recompute are separate steps.** "We fixed the bug" and "the existing results now reflect the fix" are two different claims. Before trusting a "re-verified" or "re-run" claim, spot-check that the specific mechanism the fix touched is actually the one that produced the result being cited — not a superficially similar path.

**"Don't cite X as settled" propagates to everything downstream of X, not just mentions of X itself.** If a measurement, a table, or a conclusion gets invalidated, the correction isn't "avoid restating the invalidated claim" — it's "re-check every claim, doc, or decision that depended on it." Trace the caveat forward through the dependency graph, don't just patch the point of failure.

**When something needs "further validation," check whether a bounded, cheap empirical test can resolve it right now** instead of filing it as a future action item. A vague "needs more validation" note is often actually a 10-minute query away from being a settled fact — filing it as deferred work is sometimes just procrastination wearing a process costume.

---

## 2. Autonomy and Checkpoints

**Run autonomously; don't insert human checkpoints on decisions the available context can already resolve.** Every mid-task pause to ask "should I proceed?" on something you already have enough information to decide is a tax on the human's attention, paid for a decision that didn't need paying for. Reserve actual checkpoints for genuinely irreversible or high-blast-radius actions (see your CLAUDE.md's or equivalent's guidance on destructive-action confirmation), and for decisions that are genuinely the human's to make, not yours.

**Give direct recommendations; don't surface every trade-off as an open-ended question.** "Here's what I'd do and why" beats "here are three options, which do you prefer?" for the large majority of engineering decisions. Push back when a request violates a first-principles rule you're confident about — silent compliance with a bad instruction is not deference, it's a failure to add value.

---

## 3. Scope Discipline

**Concurrent work streams need explicit boundary-checking, not just good intentions.** If more than one agent (or session, or person) can be touching the same repository at the same time:
- A broad repo-wide sweep (grep-and-fix, cleanup pass, rename) can silently step into territory another stream owns. Check what else might be in flight before editing something a broad search surfaced, not just whether *your* change is correct in isolation.
- `git status --short` immediately before every stage-and-commit, not just at the start of a session — the working tree can have changed underneath you between when you last checked and when you're about to commit, especially with concurrent writers.
- Stage only the files your actual task touched. A broad `git add -A` or blind `git add .` will happily bundle someone else's in-progress work into your commit.

**A subagent or delegated task can exceed its assigned scope.** A "report only, don't edit" dispatch can still silently make edits if the agent decides that's the more helpful path. A subagent assigned to one isolated workspace (a worktree, a branch) can still land its actual output somewhere else. Verify the result landed where — and only where — intended, especially before trusting a delegated task's own "done" report (see §1).

**A cleanup or simplification pass has a scope boundary, and known-out-of-scope issues found along the way get *noted*, not fixed inline.** Discovering a second bug while fixing the first is common; expanding the current task to fix it too, without a decision to do so, is scope creep that makes the eventual diff harder to review and revert.

---

## 4. Fix-vs-Defer Discipline

**A proof-of-value gate governs new capability, not repair of a confirmed defect.** If your project's culture requires evidence before promoting something new (a feature, a strategy, a design) — that gate should never be used to justify leaving a *known, confirmed-wrong* piece of code or data unfixed pending "proof it matters." A causal bug (wrong formula, off-by-one, backwards sign) gets fixed on discovery, full stop; the evidence bar applies to whether a new thing should exist, not to whether a demonstrably broken thing should be repaired.

**Before deleting a helper, a table, or a code path because it "looks unused," grep the whole repository — not just the directory or module you're currently working in.** A file-scoped search finding zero callers is not the same evidence as a repo-wide search finding zero callers; the former has a real, not-rare failure mode of missing a genuine cross-module dependency.

**When cleaning up stale docs or code, make the call in the moment.** "This looks outdated, flag it for someone to check later" is worse than either fixing it now or leaving it alone — a flag with no owner and no deadline is a permanent fixture, not a todo.

---

## 5. Capture Discipline

**Deferred work gets captured into your tracking system the same turn it's identified, not "later."** The gap between noticing something needs doing and writing it down is exactly where good intentions evaporate under the next context switch.

**When persisting notes into any long-lived memory or knowledge system, write the current state and its rationale — not a narrative of how it got fixed.** "X was broken because Y, fixed in commit Z" belongs in git history and commit messages, which are already the system of record for that; a persistent-memory entry that duplicates resolved-incident narrative just accumulates noise that has to be read past on every future recall. Keep persistent notes to what's still true and still load-bearing.

**Closing a gated item also means updating anything that named it as a blocking condition.** If a todo, a phase, or a decision doc says "blocked pending X," resolving X means finding and updating every place that cited it as the gate — not just closing X's own tracking entry.

---

## 6. Communication Altitude

**"What's the scope / status / priority here?" is a request for a one-page compressed view, not a doc-by-doc deep dive.** When someone asks a question at PM-altitude, answer at PM-altitude first — a ranked, compressed summary — and let them ask a follow-up if they want depth on a specific item. Leading with exhaustive detail when compression was requested makes the answer harder to use, not more thorough.

---

## Adopting This in a New Project

1. Copy this file as a starting point — the six sections above are drawn from real incidents but stated generically enough to apply to any AI-paired, fast-iteration project.
2. Treat it as a living doc, the same way the source project treats its own memory system: when a real failure happens once and gets corrected, add the lesson here (or to your equivalent persistent-memory system) with enough context (the "why," not just the rule) that a future session can judge edge cases rather than blindly following a rule stripped of reasoning.
3. Don't pre-populate this with hypothetical failure modes you haven't actually hit — per §4/§6 above and the Musk 5-step mandate, an invented "best practice" nobody has needed yet is exactly the premature-abstraction anti-pattern this whole doc set otherwise guards against. Let this doc grow only from real incidents.
