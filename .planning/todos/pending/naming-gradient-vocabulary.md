---
type: todo
priority: medium
created: 2026-06-23
---

# Gradient Scale Vocabulary — Naming System Taxonomy

The naming system uses gradient scale identifiers (fast/mid/slow, low/mid/high, etc.) but has
no formal vocabulary list. Add a canonical approved-terms table to `docs/foundation/naming-system.md`.

## Proposed taxonomy

| Concept | Approved terms | Notes |
|---------|---------------|-------|
| Speed/horizon (2-level) | `fast`, `slow` | RSI fast/slow, Aroon fast/slow |
| Speed/horizon (3-level) | `fast`, `mid`, `slow` | RSI fast/mid/slow, CCI, momentum_z |
| Speed/horizon (4-level) | `fast`, `mid`, `slow`, `extended` | IC lookahead horizons |
| Magnitude/intensity | `low`, `mid`, `high` | threshold tiers, confidence bands |
| Rank/quality | `primary`, `secondary` | signal tiers, confirmation layers |

## Rule

Only terms from this table may appear as scale qualifiers in column names, APR keys, and
variable names. Adding a new gradient term requires updating this table first (naming-system.md
is the single source of truth). Numbers in names are valid ONLY for statistical concept
definitions (e.g., `momentum_z_5` where 5 bars IS the concept).

## Files to update

- `docs/foundation/naming-system.md` — add Gradient Vocabulary section
- `CLAUDE.md` — cross-reference the table (brief mention under Naming section)
