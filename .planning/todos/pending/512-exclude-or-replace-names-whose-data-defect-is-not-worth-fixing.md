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
