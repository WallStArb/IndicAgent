---
status: pending
priority: P1
filed: 2026-09-26
source: 2026-09-26 backlog triage, owner direction
---

# Unified research-to-production design: one pipeline from features to a frozen book

## What

Two ensemble layers now overlap with no stated relation:

| | Old layer (v3.0) | New layer (phase 183) |
|---|---|---|
| Input | `feature_vectors` + `feature_ic_scores` | OHLCV only (todo 435 adds features) |
| Combiner | `ensemble_trainer` (IC-weighted, FDR-gated) -> `alpha_ensemble_ic` | S7 walk-forward ridge / equal weight |
| Test | ic_engine per-feature gates, phase 179 sleeve harness | S8 book test (E16/E17), ledger, M = 30 |
| Output | `alpha_publisher` -> `alpha_events` | frozen book, forward confirmation (S9) |

Two combiners, two definitions of the model and two routes toward capital break the DAG
principle. Settle it in one design doc for owner adoption, before todo 435 is planned, so 435
does not harden the split.

## Owner direction (2026-09-26)

- Structure the doc as the Musk 5-step process in order (requirement, delete, simplify,
  accelerate, automate), with the Renaissance principles (`docs/foundation/principles.md`) as
  acceptance checks.
- Several methods compete under one evidence standard. The draft
  `docs/plans/2026-09-26-research-methods-portfolio.md` is an input to one section of this doc,
  not a separate plan for adoption.
- Not reopened: E15/E17 evidence rules, M = 30, the ledger, the forward-span discipline.

## Questions the doc settles

1. One pipeline end to end: `feature_vectors` + OHLCV -> Panel -> families -> one combiner ->
   book test -> frozen book -> production. Likely: `ensemble_trainer`'s weighting becomes an S7
   variant or is deleted; `alpha_publisher` becomes the node that runs a frozen book forward
   (S9 shadow, then capital).
2. Where regimes belong: features (members), one pre-registered combiner-conditioning variant,
   disclosure. Never an admission gate (the Phase 148 failure).
3. ic_engine's role: disclosure plus IC as proposer; whether the regime x tf grid shrinks.
4. The methods portfolio (discovery D1-D5, combiners) inside that one pipeline, charged to M = 30.
5. Deletions: whatever has no consumer after 1-4 (candidates: the IC-weighted combiner, the
   phase 179 sleeve harness, parts of the ic_engine grid, `context_writer`).

## How

Brainstorm with the owner, then a draft in `docs/plans/` marked PROPOSED, then adoption
(methodology-change-ledger entry only if an E15 rule changes). No code. Held todos serving the
IC-as-proposer method: 191, 038, 166, 099, 039, 115.
