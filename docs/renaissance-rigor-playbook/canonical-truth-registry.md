# Canonical Truth Registry

**Version:** 1.0 (portable)
**Status:** template — pattern only, the ownership table must be built fresh for your project
**Source:** genericized from IndicAgent `docs/foundation/canonical-truth-registry.md` v3.0

## What It Is

A registry defining which stream/table owns each durable business fact in your system. Any new table, stream, read model, or cache must either appear in this registry or explicitly declare that it is a derived projection.

This is the documentation-level enforcement of [design-principles.md](design-principles.md) §8's Single Writer Rule — a place where "which component actually owns this fact" is a checkable table, not tribal knowledge someone has to already know.

**Core rule: one canonical writer per durable fact.** Read models may duplicate data for query speed, but they must never become a second source of truth.

## Ownership Table (Template)

Build your own version of this table as your system grows. Columns to keep:

| Entity | Canonical stream | Canonical table | Canonical writer | Notes |
|---|---|---|---|---|
| `<business fact 1>` | `<topic/queue, if any>` | `<table name, or None if stream-only>` | `<exactly one writer component>` | `<anything a reader needs to know before trusting this row>` |
| `<business fact 2>` | ... | ... | ... | ... |

A few shape notes from the source project's table, illustrating what a filled-in row looks like:

- A **raw ingestion fact** ("raw provider bars") had no canonical table at all — the stream itself was the canonical record, because the payload was an immutable protocol translation with nothing to persist beyond replay.
- A **derived/computed fact** ("higher-timeframe bars") named its canonical writer as the same writer as the fact it was computed from, with a Notes entry explaining the derivation ("HTF bars are computed from canonical 1m bars") — so a reader doesn't mistake it for an independent source.
- A **read-surface/join view** ("signal ledger full") had `None` for canonical writer, because a join view is never itself a source of truth — its Notes entry pointed at which underlying tables it joins and flagged that a legacy monolith table it replaced was read-only pending drop.
- A **file-based artifact** ("IC discovery report") had `None` for canonical stream and a filesystem path instead of a table — the pattern doesn't assume every canonical fact lives in a database.

## Projection Rules

- A projection must name its canonical source stream/table.
- A projection may lag or fail without blocking the canonical writer.
- A projection must be rebuildable from canonical sources.
- A projection must not mutate canonical source tables.
- Consumers must tolerate missing projections with graceful degradation.

## Adding a New Canonical Fact

Before adding a new durable fact, document:

| Question | Required answer |
|---|---|
| What is the fact? | Business-level description, not implementation detail. |
| Which stream is canonical? | Topic/queue name from your central key-registry module. |
| Which table is canonical? | Table name, or `None` if stream-only. |
| Which component writes it? | Exactly one writer/owner. |
| Is it replay-safe? | Explain offset-0/backfill behavior. |
| Is it event-time valid? | Include `valid_from` / `valid_to` if applicable. |
| What are projections? | Caches/read models and their rebuild path. |

This checklist is the actual enforcement mechanism — a PR that adds a new table without being able to answer these six questions is adding an undocumented second source of truth, which is exactly what this registry exists to prevent.

## See Also

- [Design Principles](design-principles.md) §8 — the Single Writer Rule this registry enforces
- [Documentation System](documentation-system.md) — this registry's own doc should be a WHAT-type doc (schemas, contracts) with source citations, and its decay rate tracks schema migrations

---

## Adopting This in a New Project

1. Copy the Projection Rules and the "Adding a New Canonical Fact" checklist verbatim — both are fully domain-agnostic.
2. Start the Ownership Table with just your first few genuinely canonical facts — don't pre-populate placeholder rows for facts that don't exist yet. Grow it the same way a schema grows: one row added in the same PR/migration that introduces the fact.
3. Treat a missing or wrong row the same way [documentation-system.md](documentation-system.md) treats a stale `current` doc — a wrong ownership claim is worse than no registry at all, because it actively misleads whoever reads it next about who's allowed to write to a table.
