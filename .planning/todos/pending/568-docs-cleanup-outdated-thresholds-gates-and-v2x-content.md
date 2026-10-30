---
status: pending
priority: P2
filed: 2026-10-30
source: owner 2026-10-30 ("clean up old docs with old outdate thresholds, gates etc - high level summaries only")
---

# Docs cleanup: drop outdated thresholds, gates and v2.x content

Rule (memory, owner 2026-10-28): keep each doc to status, the decision, the key numbers a disclosure
requires and a pointer; confirm a linked doc holds the detail before cutting (grep a key number);
frozen sections stay verbatim, with the pre-condense commit named in the header.

## Done 2026-10-30

- `docs/operations/operations-database.md`: v2.x table list, key columns, matview and freshness queries
  replaced by a high-level current table list (605 to 574 lines; status now current).
- `docs/operations/operations-promotion-protocol.md`: the swarm Path B to kernel rule with a rho > 0.4
  gate rewritten as a 10-line summary of the real promotion rule (unified design 7.3).

## Candidates, not yet touched (check each for unique content first)

| Doc | Lines | Why | Check before cutting |
|---|---|---|---|
| `docs/plans/2026-09-24-edge-proof-program.md` | 260 | superseded 2026-09-26; ROADMAP line 158 says some phase rationale lives only here | move the phase 177 to 183 rationale into ROADMAP, then reduce to a status page |
| `docs/plans/2026-09-24-feature-lifecycle-evidence-ledger-design.md` | 159 | decision rules superseded by design 11 (186-09) | keep the concept_evaluation ledger mechanics paragraph |
| `docs/plans/2026-09-02-personal-scale-edge-determination-plan.md` | 1,090 | "active program" of 2026-09-02, replaced by the unified design; `scripts/research/cost_hurdle.py` cites it | reduce to a summary; keep what cost_hurdle cites |
| `docs/foundation/v3-north-star.md` | 621 | 37 mentions of deleted components (ensemble, AlphaEngine, I8) | restate the north star against the v3.5 pipeline |
| `docs/plans/2026-08-02-regime-label-transition-quality-measurement-design.md` | 823 | v2.x regime measurement; 14 mentions of deleted chain | confirm superseded by 248 and 186-13 |
| `docs/foundation/glossary.md` | 2,474 | 73 mentions of retired terms, many deliberate as `**Banned:**`/history | only prune entries for deleted components with no ban role; `tools/check_glossary.py` must pass |

Do not touch: `docs/plans/methodology-change-ledger.md` (append-only), `docs/plans/2026-09-24-phase179-
sleeve-walk-forward-prereg.md` (FROZEN), `docs/plans/SHADOW-REVIEW.md` (FROZEN),
`docs/plans/OOS-EVAL-PROTOCOL.md` (committed before any OOS number), and ledger sections 2 and 4 of
`docs/research/construction-verdict-ledger.md`.

Also sweep todo files in `.planning/todos/pending/` whose diagnostics are older than their decision
(547, 560 and 564 carry multi-round logs; reduce to status, decision and numbers a disclosure needs).
