# Documentation System

**Version:** 3.0
**Status:** current
**Last Updated:** 2026-06-28

---

## Purpose

This document is the complete design specification for how documentation is structured, written, and maintained. It is a portable foundation: the taxonomy and recipe-card format travel to any new project with `docs/foundation/` unchanged.

The documentation system is not a style guide. It is a specification of what kinds of documents exist, where each kind lives, what a document must prove before it is trusted, and what happens when it decays.

**See also:** `docs/foundation/renaissance-grade-standards.md` — Documentation Is Living principle

---

## 1. Philosophy

### The Core Principle

**A wrong document is worse than no document.**

At Renaissance, dirty data does not lower model quality — it actively destroys it. A corrupted data series introduces false signal that dominates real signal. The same applies to documentation: a doc marked `current` with one wrong claim misleads every engineer who reads it. They act on the false signal. The cost is not zero — it is negative.

The documentation system exists to maximize the ratio of verified claims to total claims in the `current` corpus. Every structural decision follows from this.

### The Invariant

> **A document earns `Status: current` if and only if every factual claim in it can be traced to a specific source — a file path, a line number, a table schema, a systemd unit listing — and that source was verified at the time of writing.**

Unverified claims are noise. `Status: current` is a precision claim, not an age claim. A three-year-old doc with all claims verified is `current`. A doc written yesterday with claims from memory is `draft`.

### The Decay Model

Documentation decays at rates determined by what it describes. Different document types have different half-lives. This determines how aggressively a document must be re-verified before retaining `current` status.

| Document type | Decay rate | Re-verification trigger |
|--------------|-----------|------------------------|
| `foundation/` — principles, naming, standards | Slow — changes only on deliberate redesign | Version bump or architectural phase |
| Domain WHAT — schemas, contracts, payloads | Medium — changes on schema migrations | Any migration or schema change |
| Domain HOW — procedures, extend guides | Fast — changes when described code changes | Any PR touching described subsystem |
| `operations/` — deployment, monitoring runbooks | Fast — changes on infrastructure changes | Infrastructure or systemd changes |
| `reference/` — cheatsheets, gotchas | Medium — commands and patterns drift | Periodic, or when gotcha resolved |
| `concepts/` — architectural theory | Slow — changes only on design revision | Architectural phase changing described principle |

When a doc's described system changes, the doc's status drops to `draft` automatically until re-verified. This is a process rule, not optional.

### Bad Data Is Quarantined, Not Tolerated

At Renaissance, bad data is removed from the training set. A doc that fails verification is immediately downgraded to `draft` and flagged. It is not left as `current` with an inline caveat. Inline accuracy warnings are noise annotations on noise — they do not fix the problem.

The global caveat in `docs/README.md` applies to workspace folders only (`ideas/`, `plans/`, `specs/`). Inner-ring domain docs carry no such escape hatch.

### Shadow Mode for Documentation

A doc earns trust the same way any system component earns production status: it starts in shadow mode (`draft`), accumulates evidence (verification against code), and graduates to `current` only when the verification criterion is met. Reverting from `current` to `draft` on staleness detection is not a failure — it is the system working correctly.

---

## 2. The Domain-First Taxonomy

Every document belongs to exactly one domain folder. The folder is determined by the domain of the system being described, not the format of the document.

```
docs/
  foundation/     Immutable — principles, naming, documentation design
  data/           Data ingestion, streaming, storage, persistence architecture
  intelligence/   Compute pipeline — features, analysis, signals, AI evaluation
  signals/        Signal lifecycle — creation, activation, outcomes, graduation
  agents/         Agent framework — daemon contracts, writers, telemetry
  platform/       Infrastructure, observability, API layer
  concepts/       Architectural theory — design principles, decisions, patterns
  architecture/   Cross-cutting design — legacy, deprecating as catch-all
  operations/     Sysadmin runbooks — deployment, monitoring, disaster recovery
  development/    Developer HOW — setup, testing, profiling
  reference/      Quick lookup — cheatsheets, gotchas, standards
  ideas/          Research workspace — living, speculative, not authoritative
  plans/          Phase implementation plans — living workspace
  specs/          Design contracts for in-flight phases
```

### Inner Ring — Authoritative, Verified

`foundation/`, `data/`, `intelligence/`, `signals/`, `agents/`, `platform/`

These folders are the clean training set. Every `current` doc here has been verified against source code. Engineers can read these docs without cross-checking the codebase. If this trust is ever violated — if a verified claim turns out to be wrong — the doc is downgraded and a post-mortem is written on how the drift occurred.

### Concepts Library — Permanent, Authoritative Theory

`concepts/`

Each document explains one architectural principle: the problem it solves, the rejected alternatives, and how the system applies it. This folder is permanent — new concept docs are added when a design principle recurs across multiple domain folders and deserves a canonical explanation. A principle local to one domain belongs in that domain's WHY doc, not here.

Concepts docs decay slowly. They change when a design principle is revised, not when implementation details change. Unlike inner-ring domain docs, concepts docs do not cite file paths and line numbers — their verification criterion is coherence with the system's actual design, not correspondence to a specific implementation. They are authoritative about design intent; inner-ring docs are authoritative about implementation state.

### Outer Ring — Stable, Pre-taxonomy

`architecture/`, `operations/`, `development/`, `reference/`

These folders predate the domain-first taxonomy. Content is stable but carries implicit staleness risk. No new files are added to `architecture/`. `operations/`, `development/`, and `reference/` remain active for their respective purposes. Content migrates to the inner ring only after verification. `architecture/` is actively deprecating as a catch-all folder.

### Workspace Folders — Not Authoritative

`ideas/`, `plans/`, `specs/`

These folders are thinking space. Forward-looking content is expected and permitted. No doc in these folders is trusted without verification. The accuracy warning in `docs/README.md` is aimed here.

### The Portability Test for `foundation/`

`docs/foundation/` must pass the portability test: strip the project-specific vocabulary and the files should describe a system applicable to any quantitative platform. `principles.md` passes. `naming-system.md` passes. `documentation-system.md` passes. A doc about a specific pipeline implementation fails — it belongs in the appropriate domain folder.

---

## 3. The Four Questions

Every document answers exactly one primary question. The question determines which domain folder it lives in and which recipe-card sections it needs.

**WHY** — Design rationale. Why this design? What was rejected? An engineer reads this to understand reasoning, not state. Decays slowly.

**WHAT** — Contracts and data shapes. Schemas, topic payloads, API types, table columns. An engineer reads this before crossing a system boundary. Decays at schema-change rate.

**HOW** — Procedures. How to add a component, run a backfill, debug a stalled writer. An engineer reads this when they have a task. Decays at code-change rate.

**WHERE** — Quick lookup. Commands, cheat sheets, common gotchas. An engineer scans, not reads. Decays at medium rate.

One document can blend WHY + WHAT, or HOW + WHERE — but every section is classifiable. Sections that answer none of the four questions do not belong.

---

## 4. Document Anatomy — The Recipe Card

Every inner-ring domain doc follows the recipe card structure. The section order is fixed; omit sections that genuinely do not apply.

```markdown
# <Domain>-<Role>

**Version:** X.Y
**Status:** draft | design | current | archived
**Last Updated:** YYYY-MM-DD

---

## 1. Purpose
WHY this document exists. Who reads it.
The question it answers that no other doc answers.

## 2. Design Principles
WHY this design was chosen. What was rejected and why.
Architecture Decision Records live here, not in a separate ADR doc.
Omit for HOW-primary docs.

## 3. Architecture
ASCII diagrams. Data flows. System boundaries.
The sketch an engineer draws on a whiteboard when explaining this domain.

## 4. Data Contracts
Message payloads. DB schemas. API types. Type signatures.
Every claim cites its canonical source: file path, table name, migration number.

## 5. How To Extend
Step-by-step task procedures. Reference implementation with file:line references.
One heading per distinct task type.

## 6. Failure Modes & Operations
Named failure modes with diagnosis steps and fix commands.
Structure: **Symptom** → root cause → fix → verify.

## 7. See Also
Bidirectional cross-references to domain docs this one depends on and that depend on it.
```

### File Naming

Domain folder docs follow `<domain>-<role>.md`. Domain part matches the folder. Role part names the governing question:

| Role suffix | Primary question | Example |
|------------|-----------------|---------|
| `foundation` | WHY + WHAT | `intelligence-foundation.md` |
| `operations` | HOW (sysadmin) | `intelligence-operations.md` |
| `plugins` | HOW (developer) | `intelligence-plugins.md` |
| `lifecycle` | WHAT + HOW | `signals-lifecycle.md` |

The role suffix is not a closed list — choose the word that names what the document does. Two-word role suffixes are permitted when one word is ambiguous.

### Source Citations in `current` Docs

Every factual claim in a `current` doc must be traceable. The citation format:

```markdown
The writer batch flushes at 500ms or 1,000 records, whichever comes first.
<!-- src: services/feature_writer.py:142 -->
```

For schema claims: `<!-- src: migrations/095_signal_ledger_split.sql -->`
For service state claims: verified by `systemctl list-units` at `Last Updated` date.

Citations are in HTML comments — they do not appear in rendered output but are visible when editing. A doc with no citations is `draft` regardless of what the status header says.

---

## 5. Complete Coverage Pattern

A domain achieves complete coverage when one file answers each of the Four Questions without overlap. The test: if the same claim appears in two domain docs, one of them is wrong. Claims live in exactly one canonical location; the other doc links to it.

Example pattern (not a hard constraint on file count):
- `<domain>-foundation.md` — WHY + WHAT
- `<domain>-operations.md` — HOW (sysadmin)
- `<domain>-plugins.md` — HOW (developer)
- `<domain>-lifecycle.md` — WHAT + HOW

This is a model of how one domain achieves complete coverage with zero redundancy. New domain folders replicate this pattern.

---

## 6. Document Lifecycle

```
draft  →  design  →  current  →  archived
```

| Status | Meaning | Verification state |
|--------|---------|-------------------|
| `draft` | Work in progress or staleness-quarantined | No verification required or failed |
| `design` | Design complete, implementation may not match | Describes intent; caveated at top |
| `current` | Verified against codebase at Last Updated | All claims cited, all sources read |
| `archived` | Superseded or described system no longer exists | Not read; referenced for history only |

**`current` is a precision claim.** An uncited claim in a `current` doc is a measurement without error bars — it looks precise but is not. Downgrade to `draft` until the claim is verified and cited.

**Graduating to `current`:** Read every factual claim. Find its source in code. Add the citation. Set `Last Updated` to today. Only then change the status.

**Downgrading on staleness:** When a PR changes a subsystem described by a `current` doc, the doc status drops to `draft` on the same PR. The doc author (or PR author) schedules re-verification. A `current` doc whose source has changed and which has not been re-verified is worse than no doc — it is corrupted data.

---

## 7. Enforcement

Documentation quality is only durable if violations are visible.

### Pre-Commit Checks (advisory)

```bash
# Docs claiming `current` status with no citations
grep -l "Status: current" docs/foundation/ docs/data/ docs/intelligence/ docs/signals/ docs/agents/ docs/platform/ | \
  xargs grep -L "<!-- src:"
```

```bash
# Docs missing Last Updated
grep -rL "Last Updated" docs/foundation/ docs/data/ docs/intelligence/ docs/signals/ docs/agents/ docs/platform/
```

### Code Review Gate

Every PR that modifies a file in a path covered by an inner-ring doc must either:
1. Update the doc, re-verify affected claims, and set `Last Updated`, or
2. Explicitly downgrade the doc to `draft` in the same PR

Leaving a `current` doc unmodified when its described code changes is a review rejection — same category as leaving a broken test.

---

## 8. Stable Conventions

These do not change as part of any restructure:

- **`docs/README.md`** — navigational entry point, folder index, taxonomy overview
- **`docs/foundation/`** — trusted without code cross-checking
- **Domain folder file names** — follow `<domain>-<role>.md`
- **Plan docs** — follow `YYYY-MM-DD-<description>.md`
- **Idea docs** — carry `**Status:** draft | under-review | adopted | rejected`
- **All `current` docs** — carry `**Last Updated:** YYYY-MM-DD` and source citations
- **`concepts/`** — permanent tier; **`architecture/`** — read-only structurally

---

## See Also

- **Renaissance Standards:** `docs/foundation/renaissance-grade-standards.md` — Cleanliness, anti-patterns
- **Design Principles:** `docs/foundation/design-principles.md` — Architectural + coding principles
- **Naming System:** `docs/foundation/naming-system.md` — Vocabulary conventions
- **Glossary:** `docs/foundation/glossary.md` — Canonical terminology

---

*When a new domain folder is added, update Section 2 and `docs/README.md`. When a new governing question type is identified, update Section 3. The taxonomy grows; the principle does not.*
