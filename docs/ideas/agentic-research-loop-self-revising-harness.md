# Agentic research loop: self-revising harnesses

**Status:** Idea, 2026-10-28. Unreviewed Sonnet 5.5 mapping; needs an Opus or Fable rigor pass. Nothing is planned: adopting an agentic research loop is an owner decision, and the v2.x AI stack was removed in phase 185-45.
**Source:** a paper pasted by the owner and two arXiv papers the owner linked, mapped against the evidence framework. Running catalogue of other methodology concepts: `docs/ideas/edge-search-concepts.md`.

## The pasted paper ("The End of Harness Engineering")

A paper pasted by the owner (authors, affiliation, date and numbers as given in the paste; the paper itself is not verified, and it is neither of the two papers below). Its claim: a frozen solver plus a small proposer that rewrites the harness from execution reports beats hand-built harnesses; the human writes only the scoring set. Four channels: the execution report (read-only record of what failed), proposer edits (a 4B model, eight candidates per round), the scoring set (the operator's held-out questions, never shown to the proposer; only the top edit survives), and the final set (one honest test after the last round, reported, never optimized against, used once). Reported: 41 rounds, 37 revisions, held-out score 0.31 to 0.64.

| Channel | Counterpart here |
|---|---|
| Execution report | `research_run` rows and the ledger: every run recorded, never edited |
| Proposer edits | Closest: todo 440's `generated_family` (grammar, in-fold selection plus ridge) and the `ic_proposal` method; no model rewrites code or specs, and the v2.x AI stack was removed in 185-45 |
| Scoring set, never shown to the proposer | Vintage 1 is the screening set, but it is searched and counted (M = 30, E18), not hidden |
| Final set, used once | The forward span: one confirmation of a frozen book, `alpha.validation.oos_start` write-once (migration 506) |

What carries over: the structure of the evidence framework matches the paper's (screen, select, confirm once, never optimize against the confirmation). What does not: the paper's scoring set is selected on every round (8 candidates x 41 rounds), so its held-out 0.64 is a winner's-curse figure; only its final set is an honest estimate. Any agentic research loop here would have to count every candidate as a look (E18) and keep the forward span out of the proposer's reach. No such loop is planned; adopting one is an owner decision, not something this catalogue implies.

Sources the owner linked afterwards, read 2026-10-28:

| Source | What it is |
|---|---|
| arXiv 2604.21003, "The Last Harness You'll Ever Build" (Sylph.AI, 22 Apr 2026) | Conceptual: a worker, an evaluator and an evolution agent edit a harness, with an outer loop that tunes the evolution protocol. Reports no results; the authors say empirical results will follow |
| arXiv 2606.09498, "Self-Harness: Harnesses That Improve Themselves" (Shanghai AI Laboratory, 8 Jun 2026) | Empirical: a fixed model mines its own failures, proposes minimal edits, and an edit is promoted only if it degrades neither the held-in nor the held-out split and improves at least one. On Terminal-Bench-2.0 (64 of 89 tasks) held-out pass rates rose 40.5 to 61.9, 23.8 to 38.1 and 42.9 to 57.1 across three models. Stated limits: bounded edits on fixed benchmarks, accepted edits may encode benchmark-specific patterns, results depend on verifier quality, and higher-stakes changes need stronger gates than non-regression. Its appendix baselines differ from the main table and are not reconciled |
| Medium article "Harness engineering: the last guide you need" | Not read (HTTP 403) |

Relevance, neither paper being about finance: Self-Harness's promotion rule is a held-out non-regression gate, which is weaker than E15 to E18 (it counts no looks, applies no multiplicity correction and spends the held-out split repeatedly), and its own caveat is the overfitting worry the evidence framework exists for. Both describe the same execute, evaluate, modify loop as an agentic research pipeline; neither supports adopting one here.
