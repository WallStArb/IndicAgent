# Todo 368 — range_pct_fast successor pre-registration decision

**Filed:** 2026-09-02, after pre-registration 1 returned DEAD
(`de7c33bb2`, full numbers in
`docs/plans/2026-09-02-personal-scale-edge-determination-plan.md` § "Pre-registration
1 run").

## Problem

`range_pct_fast_xs_ls_h5` is DEAD: real signal (shuffled-null p=0.0010) but a
market-beta tilt (beta +1.14, R² 0.75 vs EW-universe mean), net-negative at all 9
personal cost combos (turnover 0.45/rebalance, 2.8-3.2bp/side commissions at $100k),
2/3 subperiods net-negative. Attribution: 52/231 symbols pass per-symbol BH-FDR.

Per the pre-registration, no successor is auto-promoted. Whether to design one at all,
and its shape, is an open decision the user owns.

## Scope

- Decide: pursue a successor construction (built around the 52/231 per-symbol
  survivors and/or beta-neutral per-name framing) vs. deprioritize this program branch.
- Any successor needs its own pre-registration that answers why the leader failed:
  market-beta loading plus personal-scale costs on a 0.45-churn quintile construction.
- No re-running or re-parameterizing the DEAD construction (N1 lesson).
- If pursued: pre-registration 1's script never received cross-AI review (AGY backend
  down, Codex out of quota until 2026-09-13; synthetic controls were the validation). A
  successor script reusing its harness gets reviewed before its run, and the pre-reg-1
  script gets a retro review before its verdict numbers are cited as decision input.
  Relevant input to this decision: todo 367's Phase 148 placement (0b's ruler says the
  institutional Gate 2 measured the wrong trader; if Phase 148's construction clears
  the personal hurdle, deprioritizing this branch costs less).

## Verification note

Before treating "todo 278's 15m diagnostic" as the remaining queue item (as the program
doc's workstream 2 claims), verify 278's actual status: `PRIORITIES.md` records
277/278 as verified in `completed/`, conflicting with the program doc's "runs unchanged
and in parallel" framing written the same day. One of the two is stale.

**Resolved 2026-09-02: neither is stale.** Todo 278 is a decision todo, filed and
resolved 2026-08-08 — its resolution makes a properly-powered 15m residual diagnostic
(day-clustered bootstrap CI, shuffled-ranking null, BH-FDR) a prerequisite before any
new gate_id run. The diagnostic was never itself a todo; the program doc's workstream 2
is that diagnostic, correctly described in its body ("per todo 278's closed design") and
loosely attributed in its title, now reworded. The diagnostic remains live queue work.

## Success criteria

A user decision recorded in the program doc (pursue/deprioritize), and if pursued, a
new pre-registration section under the program's approval discipline.
