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

## Done 2026-10-31

Disposition per the owner's mid-flight corrections: reduce, then archive as a stub (title, kept
ideas, verdict pointer, git-history commit) unless the detail is itself the value; final text in
git history at each doc's named commit.

- `docs/plans/2026-09-24-edge-proof-program.md` (260 to stub): phase 177-183 rationale moved into
  `.planning/ROADMAP.md` ("v3.4 rationale"); archived as a stub.
- `docs/plans/2026-09-24-feature-lifecycle-evidence-ledger-design.md` (159 to 57): kept in full in
  `docs/plans/archive/` (the `concept_evaluation` ledger mechanics are the value); decision rules
  superseded by unified design 11 / 186-09, pointer updated in the UCR doc.
- `docs/plans/2026-09-02-personal-scale-edge-determination-plan.md` (1,090 to stub): the
  pre-registered hurdle constants live in `scripts/research/cost_hurdle.py` (which still cites the
  old path; not edited, code untouched); verdicts in the ledger and summary cards; archived as a stub.
- `docs/foundation/v3-north-star.md` (621 to 81): north star blockquote and the seven invariants
  restated against the v3.5 pipeline; AlphaEngine/PrecedentEngine/I7/ECL mechanics dropped (they
  stay in the glossary's ban records); eight-vector table stays in business-requirements.md.
- `docs/plans/2026-08-02-regime-label-transition-quality-measurement-design.md` (823 to stub):
  supersession confirmed (todo 005's 2026-08-27 source fix, todo 248, plan 186-13); the
  joinable-population census idea kept in the stub and the backlog matrix.
- `docs/foundation/glossary.md` (2,479 to 2,339): entries for deleted components pruned to
  Legacy/ban/status lines and replacements (`alpha_events`, `ensemble alpha` status, `alpha decay`,
  `alpha_events`, `IC Sharpe`, `Shadow Governance`, `counterfactual_pnl_r`, `CounterfactualTracker`,
  `cross-sectional spread construction`, `signal`, the AlphaEngine stages, the ensemble slots,
  I1-I4 code surfaces); every `**Banned:**` line untouched; `tools/check_glossary.py` passes on the
  file (the pre-existing full-tree baseline failures are unchanged, verified on a stashed tree).
- Todo sweep: 547 (214 to 64), 560 (96 to 62), 564 (114 to 60): status, decision and every verdict
  number kept; round-by-round diagnostic narration cut.
- Not touched: the reset follow-ups (owner owns the frozen-ledger lift), `methodology-change-ledger.md`,
  the FROZEN preregs, `SHADOW-REVIEW.md`, `OOS-EVAL-PROTOCOL.md`, ledger sections 2 and 4,
  `STATE.md`, `PRIORITIES.md`. Historical mentions of the four paths in completed todos, phase dirs,
  milestone snapshots, summary cards and the frozen ledger were left as history; live pointers were
  repointed to the archive stubs. `tools/glossary_baseline.json` holds counts now above actual (7
  entries); lowering it needs a `--all --update-baseline` run, deferred because the full-tree check
  has 136 pre-existing held violations.

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

## Reset follow-ups (2026-10-30)

After migration 544 emptied the ledger, these still describe voided results: `docs/research/construction-verdict-ledger.md`
(frozen sections 2 and 4; owner lifts the freeze or marks them void in one header line), `docs/research/summary-cards/`,
`FAMILY2-*` files in phase 187, the `research_run` row counts in `tests/unit/research/test_spec_hashes_pinned.py`'s
docstring. Reduce each to a status line plus a pointer to `data/backups/reset-2026-10-30/`. The concept layer reset
(306 active statuses, 590 evaluations) is a separate item for the data lane with the 186-26 rebuild.
