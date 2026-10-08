---
status: pending
priority: P2
filed: 2026-10-08
source: owner policy relayed by the research-ledger session (indicagent-6a) on 2026-10-08; owner confirmation in the 185 session pending
---

# Policy: names whose data defect is not worth fixing leave the compute set; the owner allows a better replacement

## What

If a name's data defect is not worth the effort to fix, it is excluded; the owner also allows replacing it with a better name. Guardrails (all consistent with CLAUDE.md):

1. Exclude, never erase. Set `compute_eligible_1d` false with a recorded reason code and date (a D0 label). Keep every raw D1 and IBKR observation (raw market data is permanent). No DROP, no hand-written `instruments` rows, no deactivation. "Delete" means leaves the compute set.
2. The test is data quality only, by a rule written and dated before it is applied: unrecoverable vendor basis (todo 508 names where option 1 cannot give a clean series), zero-volume rule failures (FUBO, LION, RCAT), listing history that cannot be resolved (the ISLAND 8, CLBK). Never exclude on returns, Sharpe or how a name behaved in any screen.
3. Effort rule: a fix that is a rule already built (508 option 1 head rows, the zero-volume rule) is applied, not skipped. Exclude only names that need per-name hand work.
4. Dead or delisted names with a clean series stay in; removing them is survivorship bias. Every excluded name is counted in D0's survivorship bound with its reason code, and the disclosure notes that exclusions correlate with corporate-action-heavy names.
5. A replacement goes through `docs/foundation/instrument-onboarding-sop.md` with a rule fixed beforehand (next name by liquidity rank in the same SCH classification node), never hand-picked, and enters with no look at its history or returns.

## Orchestrator notes

- Sequencing: this does not delay 189-10 Task 1b. Apply the rule after Task 1b and 185-47 have produced the measured answers (the ISLAND 8 are re-asked in Task 1b, todo 511), because "not worth fixing" must be decided on measured outcomes, not guesses.
- Promotion state moves through the integrity verdict gate (185-41) and UCR/SCH registries, not by hand edits to `instruments`; the plan that implements this must name the single writer and write the rule into an evidence doc before it runs.
- Replacements change the universe after the vintage was looked at; the plan must state how replaced names are counted in the D0 survivorship bound and keep them out of any look-count that already used the old name.

## Done when

A dated rule document exists; each excluded name carries a reason code in D0; the excluded and replacement lists are logged in the 185 summary; the survivorship disclosure is written.

## Proposed amendment 2026-10-08 (relayed by indicagent-6a; NOT accepted, needs the owner's explicit confirmation in the 185 session)

The relayed amendment replaces guardrail 1 (exclude, keep raw data) with archive-then-delete: per excluded name, dump every row from every table that holds it to data/backups/<plan>/ with row count and content hash, restore-prove one name per batch, delete from the hot tables in one transaction per name, and keep a tombstone instruments row (is_active false, reason code, date, plan id, archive path) written through the existing instrument path. Delete only after the rule is applied and the batch list is final, with the dry-run list (name, reason code, row counts per table) printed in the plan summary before the delete step. Names fixable by an existing rule (508 stale heads) stay.

Conflicts to resolve before any of it runs:
- CLAUDE.md states raw market data is permanent ("derived data is cache, raw is permanent") and the instrument SOP says never deactivate a dead name. Deleting raw D1 and IBKR observations contradicts both; the owner must amend those rules in CLAUDE.md first (or state a scoped exception), otherwise the pre-commit and review gates will treat the delete as a violation.
- The tombstone needs `is_active false`, which the SOP forbids for dead names; the exception must be written into the SOP with its reason-code vocabulary (CVR namespace, not free text).
- Point-in-time and lineage queries: a deleted name's rows leave the PIT universe snapshots only if snapshots were built from hot tables; snapshots already taken (research looks counted at the vintage) keep their hash, so a delete after a counted look changes reproducibility (determinism invariant: bit-exact from snapshot hash). Names that any recorded research run used must not be deleted, only excluded.
- Reversibility: the archive restore proof must precede the first delete, and the delete step must be a single writer with a dry run, like ops_source_policy.py.
- Recommendation: start with exclude-only (guardrail 1 as first sent). Revisit deletion only if exclusion measurably costs disk or confuses a gate; the data volume (a few hundred names at most) does not justify breaking the raw-permanence rule.
