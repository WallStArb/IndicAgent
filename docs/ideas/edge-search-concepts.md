# Edge search concepts: a running map against the design

**Status:** Idea catalogue, started 2026-10-28. Unreviewed Sonnet 5.5 mapping; needs an Opus or Fable rigor pass before anything here changes the design.
**Source:** high-level concepts for a Renaissance-style edge search engine, pasted by the owner one at a time. Each entry says what the repo already does and what, if anything, is new. Alpha ideas go to the ledger (`docs/research/construction-verdict-ledger.md`); this file holds methodology concepts.

## Part 6: what happens when the market regime changes

The flowchart: alpha signal, historical test, split by regime (low and high volatility; IC, P&L and drawdown in each), stability check, structural break test (break means reassess, no break means continue), out of sample, robust alpha.

| Step | Where it stands |
|---|---|
| Per-regime IC and P&L | Covered as disclosure: design section 5.2 and UD-07 require a fixed table on every book test (share of P&L, mean, HAC t, IC, hit rate, effective observations per regime, per member and family) plus the regime-explained share; `measure/regime_disclosure.py` does it for `regime_volatility` |
| Per-regime drawdown | Not in the 5.2 table. Candidate: add drawdown (and time under water) per regime to the disclosure |
| Stability check | Covered: attribution item 6 (stability by sub-period, regime and lag; weight-sign stability across folds) |
| Structural break, then reassess | Partly covered: UD-10 and section 8 (per-member realized contribution on a control chart, leaving the band is the decay alarm; structural change becomes a challenger version with a capital ramp). No formal break test exists in current code (CUSUM, sup-F, Bai-Perron appear only in archived v2.x drift designs). Candidate: a break test on each member's contribution series as a complement to the control chart, pre-registered so it is not a free look |
| Out of sample, robust alpha | Covered: E15 to E18, one confirmation of a frozen book on the forward span |

Where the flowchart differs from the design: it lets a regime result decide (a break triggers reassessment). The design keeps regimes disclosure-only and never gating (UD-07), because 31 thin cells make one significant t a multiplicity artifact, E18 counts every look, and earlier regime-gated constructions failed (regime-conditional persistence 0/270 cells, the `bars_since_high` regime gate; ledger section 4). Conditioning enters only through continuous state variables in one pre-registered S7 variant.

Caution: stored regime columns carry the per-symbol HMM lookahead until the 186-26 rebuild (todos 248 and 466), so any per-regime IC before then reads contaminated labels.

Two candidates from this part, neither queued: drawdown per regime in the 5.2 disclosure table, and a pre-registered structural-break test on member contribution series beside the decay alarm.

## Signal validation flow: IC, ICIR, decay, stability, out of sample

The flowchart: alpha signal, future returns, IC, then ICIR and decay, stability, unseen data, survives (approved) or rejected. The caption adds: a high IC is not automatically alpha; the information must survive research, portfolio and execution.

| Step | Where it stands |
|---|---|
| IC against future returns | Covered: IC targets come from the kernel `panel.forward_returns` (executable open-to-open returns, never close-to-close), `measure/ic.py` |
| ICIR (consistency over time) | Covered: the IC-Sharpe combiner rule (design section 6 combiner table, mean IC over its time variation with peer shrinkage and cluster deflation), beside equal weight and ridge |
| Decay | Covered: IC term structure to lag 60 (`measure/term_structure.py`) and the member decay alarm (UD-10) |
| Stability, regimes | Covered: attribution item 6 and the 5.2 regime disclosure (see Part 6) |
| Unseen data, survives or rejected | Covered: E15 to E18, one confirmation of a frozen book on the forward span; the verdict is never edited |
| Costs, turnover, implementation | Covered: statistics are gross, promotion needs positive net expectation; turnover and cost share per member (attribution item 7); the cost model is todo 437. Evidence that IC alone is not alpha: all 554 BH-FDR-passing pooled 1d cells clear the personal cost hurdle (ledger section 5), while family 1's strong detection fails it on turnover |

Nothing new. The flowchart's binary approve or reject is coarser than the design: nothing promotes without positive net expectation and a counted confirmation.

## Self-revising agent harnesses ("The End of Harness Engineering")

A paper pasted by the owner (authors, affiliation, date and numbers as given in the paste; the paper itself is not verified). Its claim: a frozen solver plus a small proposer that rewrites the harness from execution reports beats hand-built harnesses; the human writes only the scoring set. Four channels: the execution report (read-only record of what failed), proposer edits (a 4B model, eight candidates per round), the scoring set (the operator's held-out questions, never shown to the proposer; only the top edit survives), and the final set (one honest test after the last round, reported, never optimized against, used once). Reported: 41 rounds, 37 revisions, held-out score 0.31 to 0.64.

| Channel | Counterpart here |
|---|---|
| Execution report | `research_run` rows and the ledger: every run recorded, never edited |
| Proposer edits | Closest: todo 440's `generated_family` (grammar, in-fold selection plus ridge) and the `ic_proposal` method; no model rewrites code or specs, and the v2.x AI stack was removed in 185-45 |
| Scoring set, never shown to the proposer | Vintage 1 is the screening set, but it is searched and counted (M = 30, E18), not hidden |
| Final set, used once | The forward span: one confirmation of a frozen book, `alpha.validation.oos_start` write-once (migration 506) |

What carries over: the structure of the evidence framework matches the paper's (screen, select, confirm once, never optimize against the confirmation). What does not: the paper's scoring set is selected on every round (8 candidates x 41 rounds), so its held-out 0.64 is a winner's-curse figure; only its final set is an honest estimate. Any agentic research loop here would have to count every candidate as a look (E18) and keep the forward span out of the proposer's reach. No such loop is planned; adopting one is an owner decision, not something this catalogue implies.
