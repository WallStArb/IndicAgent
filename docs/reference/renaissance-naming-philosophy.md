# Renaissance Naming System — Extended Rationale

**Version:** 2.1
**Date:** 2026-08-10
**Status:** Reference — extended reasoning only. **Not the canonical spec.**
**Canonical spec (current live conventions, all surfaces):** `docs/foundation/naming-system.md`
**Quick lookup:** `docs/reference/naming-conventions.md`

---

## Purpose

This document exists for one thing `naming-system.md` deliberately keeps terse: **the reasoning
behind the three governing tests and the model-evolution protocol** — worked examples and the
"why," for a reader deciding a genuinely hard naming case, not just checking a table.

**This document is never re-derived from the live codebase and must never be read as a source of
current naming fact.** Where anything here conflicts with `naming-system.md`, `naming-system.md`
wins — always. Prior to this rewrite (v1.2, 2026-05-30), this file duplicated the Ring
Architecture, Taxonomy, Five Surfaces, Ring 0 Portability Contract, CI Enforcement, and Stable
Conventions sections of `naming-system.md` in full. That duplication had already drifted by
2026-08-10: it named `BaseSwarmCoordinator` as the live Ring 0 base class when the codebase had
actually kept `BaseGroupCoordinator` (Ring 1, not Ring 0 — see `naming-system.md` §3's YAML block
and its accompanying note on why), and it still called itself "Five Surfaces" after
`naming-system.md` grew to eight. Those sections are removed, replaced with pointers — one
source of truth, not two documents that can silently disagree.

This version also removed the prior v2.0's "Historical: 2026-05/06 Vocabulary Rename Phase"
section (~90 lines of old-name → new-name tables for an already-complete, already-verified
rename). Per this same document's own Renaissance Deletion Principle (`naming-system.md` §11: "a
file with no permanent operational use is deleted the day its job is complete... git history is
the archive"), a completed rename checklist carries no forward-looking value once every name in it
is confirmed live — keeping it was the section-level version of the `archive/`-directory anti-
pattern the project explicitly rejects elsewhere. If a stray `*ComputeAgent`/`BaseAgent` reference
ever turns up in truly old commit messages or branches, `git log`/`git blame` already has the full
mapping; this file doesn't need a second copy of it.

---

## 1. Philosophy and Governing Tests — Extended Discussion

*(Current, terse version: `naming-system.md` §1. This section adds worked reasoning.)*

### The Core Principle

**The vocabulary IS the model. The model IS the vocabulary.**

The mathematical model and the codebase are not two things connected by documentation — they are
one thing. The names prove it. When a senior quant reads a list of class names, they are reading
the mathematical architecture: what the system evaluates, what it synthesizes, what it writes,
what it monitors. When names describe mechanism instead of role, the code has drifted from the
model. Naming cleanup is not cosmetic — it restores the identity between model and code.

### The Invariant

Every naming decision reduces to one falsifiable test:

> **A name is correct if and only if a domain expert who has never seen the implementation can
> correctly predict the object's mathematical role, its inputs, and its output contract from the
> name alone — without reading any code.**

This is the single criterion. The three governing tests are tools for applying it. When they
conflict or leave a case unresolved, return to the invariant. If you cannot state what inputs and
outputs a reader would predict from the name, the name is wrong.

The invariant is also why naming enforcement belongs in code review, not just CI. Automated checks
catch mechanical violations. The invariant requires domain judgment.

### Three Governing Tests, Worked

**The Whiteboard Test**
Write the name on a whiteboard in a mathematics seminar. Would a quant immediately understand
what the object IS — its role in the mathematical model? `SkepticEvaluator` passes. `context`
passes. `ctx` fails — not because it's short, but because a reader outside this codebase has to
decode it before they know what it is.

**The Survival Test**
If you replaced the implementation tomorrow — swap the LLM for a neural net, swap asyncio for
threads, swap Kafka for a message queue — would the name still be correct? If yes, it names the
role. If no, it names the mechanism. `BarAggregator` survives any implementation change; a
hypothetical `BarAggregatorComputeAgent` does not, because `Compute` describes mechanism, not role.

**The Portability Test** *(Ring 0 only)*
Could this name be extracted into a shared library and used unchanged in a credit risk system, an
options pricing engine, or a macro research platform? `BaseDaemon` passes — it names the daemon
base in any system. `AIContext` fails — it names a trading-intelligence construct, which is why it
belongs in Ring 1, not Ring 0.

### What Fails All Three Tests

- **Mechanism words:** `Compute`, `Process`, `Handle`, `Manage`, `Execute` — all software does
  these things. They describe how, not what.
- **Unearned role words:** `Agent` on a component that is called, not autonomous. `Service` on a
  class that is not a service.
- **The `Base*` pattern on domain objects:** implies a non-base sibling exists when none does.
- **Code abbreviations:** `ctx`, `cfg`, `msg`, `sig` — shortcuts that fail the whiteboard test in
  every field, not just this one.
- **Three unrelated semantic units:** three related words in a compound (`RegimeCoherenceAnalyzer`,
  `SignalMetricsWriter`) are fine — the smell is *unrelated* concepts, not word count. Four or
  more independent PascalCase segments is the concrete heuristic naming-system.md's CI check uses.

---

## 2. Model Identity and Evolution — Extended Discussion

*(Current, terse version: `naming-system.md` §5. This section adds the full case-by-case
reasoning.)*

This governs how names behave when the mathematical model changes — the most important section
for long-term vocabulary integrity, because it's the one place drift creeps in gradually rather
than all at once.

### Names Encode Role, Not Version

A class name is a claim about mathematical role. It is not a version identifier, a prompt
identifier, or an implementation identifier. The corollary: when an evaluator's internal model
changes but its mathematical role is unchanged, the name does not change.

`SkepticEvaluator` evaluates a trading signal from an adversarial skeptic perspective and produces
a confidence multiplier. That role is stable across LLM provider changes, prompt rewrites, and
architectural improvements. The internal evolution is tracked by `prompt_version` (LLM iteration)
and equivalent `model_version` attributes. The class name is the invariant.

### The Model Evolution Protocol, Worked

**Case 1 — Implementation changes, role unchanged.**
Prompt rewrite, LLM provider swap, algorithm improvement. The evaluator still does the same thing
mathematically. → Increment `prompt_version` or equivalent. Class name unchanged. No shadow period
required unless the change is substantial enough to warrant one.

**Case 2 — New mathematical approach to the same role.**
A different analytical technique for the same question (e.g., Bayesian skeptic evaluation
replacing heuristic scoring). The role is the same; the math is fundamentally different. → New
class starts in shadow mode (`shadow_only = True`). Old class runs in parallel. When graduation
criteria are met, the new class is promoted and the old one deprecated, then deleted in the next
cleanup phase.

**Case 3 — New mathematical role.**
A genuinely different evaluation perspective producing a different analytical function — not a
better version of the same thing, a different thing. → New class with a new name derived from its
new role. The old class continues independently under its original name. These are not versions of
each other.

**Version numbers in class names are prohibited in all three cases.** `SkepticEvaluatorV2` implies
`V1` exists simultaneously — either they serve different roles (different names) or one is in
shadow mode (`shadow_only`, not a version suffix).

### Shadow Mode Is Runtime State, Not Mathematical Identity

`shadow_only = True` does not create a different type of evaluator. A `SkepticEvaluator` in shadow
mode and one in production are the same mathematical object in different operational states. Two
consequences: no shadow-suffixed class names (never `SkepticEvaluatorShadow`), and promotion
requires zero renaming — the `shadow_only` attribute flips, nothing else changes.

The research/production boundary in this system is entirely runtime-governed, not name-governed,
by design: the mathematical claim encoded in the name is the same in research and production.
Encoding environment in the name would imply the math changes between environments. It does not.

---

## 3. Abbreviation Policy — Why, Not What

*(Current permitted/banned lists: `naming-system.md` §6 — that table is the single source of
truth and changes independently of this reasoning. Do not duplicate the lists here; they will
drift, exactly as this document's old Ring Architecture / Taxonomy / Surfaces sections already
did once.)*

An abbreviation is permitted when it is the canonical term in a rigorous field and passes the
whiteboard test *in that field*. `PnL` on a finance whiteboard is not abbreviating "profit and
loss" — it IS the term. `API` in a CS context is not shorthand — it IS the term. Field codes carry
no information loss because every practitioner reads them without decoding.

Code shortcuts fail the whiteboard test in every field. `ctx`, `cfg`, `msg` are laziness dressed
as convention — no field of practice treats them as its own vocabulary the way finance treats
`PnL` or CS treats `API`.

**The test:** would a practitioner write this on a whiteboard in a mathematics, finance, or
computer science seminar and have every peer read it without decoding? If yes — field code,
permitted. If no — shortcut, not permitted.

---

*Canonical current state lives in `docs/foundation/naming-system.md`. This document adds
reasoning; it does not compete with it.*
