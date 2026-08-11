# Renaissance Rigor Playbook

A portable extraction of IndicAgent's institutional-rigor foundation docs — the accumulated naming, documentation, and governance discipline built up over about a year on this project — stripped of trading/IndicAgent specifics so it can seed a sister project from day one instead of drifting into rigor by accident.

**What "portable" means here:** every doc below keeps the *mechanism* (a table schema, a lifecycle, a governing test, a decision frame) and replaces the *content* (IndicAgent's actual class names, table names, trading examples) with placeholders or illustrative examples. None of these are meant to be used as-is without filling in your own project's real vocabulary — each doc ends with an "Adopting This in a New Project" section that says exactly what to keep verbatim and what to rebuild.

## Start Here

Copy [`CLAUDE.md.template`](CLAUDE.md.template) into your new project's repo root as `CLAUDE.md`, and copy this whole `renaissance-rigor-playbook/` directory into the new project's `docs/`. Fill in the template's placeholders as you go — it's the dense index; these docs are the depth it points into, the same relationship IndicAgent's own `CLAUDE.md` has to its `docs/foundation/`.

## The Docs

**Near-generic as-is** (copy with only light edits):

| Doc | What it governs |
|---|---|
| [principles.md](principles.md) | The Renaissance/Simons philosophy — instrument everything, earn promotion through proof, one model one book, adversarial review cadence |
| [musk-5-step-process.md](musk-5-step-process.md) | Order of operations before touching code: requirements → delete → simplify → accelerate → automate |
| [renaissance-grade-standards.md](renaissance-grade-standards.md) | Workspace/code/data/architecture hygiene standards, anti-patterns, enforcement |
| [ship-or-sink-rules.md](ship-or-sink-rules.md) | Session-level workflow discipline for working with AI coding agents |
| [model-selection-principle.md](model-selection-principle.md) | Occam's razor as a formal promotion gate — reject unjustified complexity |
| [documentation-system.md](documentation-system.md) | Doc taxonomy, the recipe-card format, staleness/decay model, citation discipline |

**Genericized pattern docs** (structure is portable, every concrete example needs rebuilding from your own codebase):

| Doc | What it governs |
|---|---|
| [adaptive-parameter-registry.md](adaptive-parameter-registry.md) | APR — every tunable number lives in a migration-governed table with a lifecycle (seed → learned → override), never a hardcoded constant |
| [controlled-vocabulary-registry.md](controlled-vocabulary-registry.md) | CVR — symbolic taxonomies (valid codes per namespace) as a definitional, non-falsifiable registry, kept structurally separate from classification claims |
| [unified-concept-registry.md](unified-concept-registry.md) | UCR — evidence-gated lifecycle governance for research artifacts (`candidate → shadow_only → active → deprecated`), with nine invariants protecting against self-promotion |
| [naming-system.md](naming-system.md) | The full naming method: governing tests, ring/layer architecture, taxonomy construction, surface-derivation table, gradient vocabulary, abbreviation policy, operational-file rules |

**Deliberately excluded from this set** (too project-specific to genericize usefully — build your own from scratch using the *method* in the docs above, don't try to port the content):
- A glossary — 100% project vocabulary, no portable content
- An Instrument Tag Registry-style falsifiable-classification system — the *pattern* is described inline in the CVR/UCR docs' sibling-registry sections, but a standalone doc would be almost entirely trading-domain example content

## Why This Exists

Prompted by: "do we have generic versions of these docs... something we could use to help build a sister project if we wanted to use the same renaissance rigor and reuse many of the ideas we have been solidifying over a year here." Nothing like this existed before this pass — it was built fresh from IndicAgent's `docs/foundation/` on 2026-08-11.

## Keeping This Set in Sync

This is a snapshot, not a live mirror. When IndicAgent's own foundation docs evolve (a new invariant added to UCR, a new naming surface, a revised principle), this playbook does **not** update automatically. If you want it to track the source project, that has to be a deliberate periodic pass — diff the two doc sets and decide what's a genuine mechanism improvement worth porting versus IndicAgent-specific drift that should stay out.
