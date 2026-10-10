---
status: completed
priority: P1
filed: 2026-10-08
closed: 2026-10-10
source: owner instruction in the 185 session, 2026-10-08: survivorship bias is not an issue; delete all references
---

# Retire the survivorship bound: D0 label arithmetic, D-28 gate condition, APR keys, docs

## What

Owner, 2026-10-08: survivorship bias is not an issue. Remove it from the live system and its documentation. Scope (live surface, found by grep on 2026-10-08):

- Code: `src/intelligence/bars/labels.py` (`SurvivorshipRule`, `SurvivorshipBound`, `survivorship_bound`, the survivorship field of the D0 label and its serialisation) and `tests/unit/bars/test_labels.py`; `scripts/ops/bars/ops_data_bar_check.py` condition 6 `survivorship_apr_keys` (renumber nothing silently: record that the gate has six conditions fewer-one) and `tests/unit/scripts/test_data_bar_check.py`; `scripts/infrastructure/universe_expansion_holdings_draw.py` mention.
- APR: the six `alpha.survivorship.*` keys, retired by a new migration in the order config_history, config_state, config_schema (pattern of migration 459). Migration 382 stays as applied history.
- Docs and planning: `docs/foundation/glossary.md` survivorship entries (signal corpus layer entry and the cross-references), `docs/foundation/instrument-onboarding-sop.md` lines 44 and 61, `docs/concepts/extrinsic-confidence-layer.md` and `signal-ledger-architecture.md` survivorship sections and tags, `config/universe/README.md`, `.planning/STATE.md` line 160, `.planning/ROADMAP.md` phase 185 text, the open todos 376 (close it with the owner statement), 423, 438, 441, 501 (501: the D0 label keeps its other fields; remove the survivorship field from the S0 handoff), and the 185 design docs under `docs/plans/` that state it as a requirement (replace the statement, do not stack).
- Research side (indicagent-6a lane): `docs/research/*`, `.planning/IDEAS.md` and the ledger references, and any pre-registration wording that requires a survivorship label on every attempt.
- Memory: remove survivorship statements from the project memory files.

Left as history (frozen records, not live references; the owner may say to scrub them too): applied migration files (382, 334, the fixture seed 2026-10-02), `.planning/milestones/*` archives, and past phase PLAN and SUMMARY files that record what was true when written.

## Cautions

- The D0 label feeds the research snapshot path (501). If the label payload changes, check whether any recorded spec hash or snapshot hash includes it; run `repro_frozen` (must report bit-identical) if anything under `src/intelligence/research/` or `statistics/` is edited. `labels.py` is under `bars/`, so verify by grep whether the runner or snapshot imports it before assuming it is outside the frozen path.
- The D-28 gate loses a condition: update the 185 closing-check text so the count of conditions in docs matches.
- The pre-commit glossary check fails on retired terms in new text; after removal add survivorship to no list (it is simply gone).

## Done when

`grep -rIil survivorship` over live paths (excluding the named history) is empty; the full unit suite and the 185-44 guards are green; the APR keys are gone from config tables; todo 376 is in completed/ with the owner statement; repro_frozen is bit-identical if the research path was touched.

## Closed 2026-10-10

Landed in two commits: 8e5c214cc (code + migration 467 (applied live as 466; renumbered after a collision with 466_alpaca_source_check): labels.py drops the bound to three D0
labels, the D-28 gate drops condition 6 with the numbering gap recorded, the six
alpha.survivorship.* keys retired history-then-state-then-schema, applied live and verified 0
remaining; no production consumer existed outside the label module and the gate, nothing under
research/ or statistics/ imports labels.py, so no frozen-path re-verification) and the docs sweep
commit (ROADMAP phase 185 text, onboarding SOP rule 6's rationale, universe README bias list, the
Oct 6 design verdict row, ledger rows 6/9/11, todos 441 and 501 requirement clauses; the
signal-corpus survivorship-bias glossary entry and concept docs are a different concept and stay).
Todo 376 was already completed; 438's mention is accurate descope history.
