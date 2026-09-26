# Research methods portfolio: one evidence standard, many methods

**Author:** Claude (Opus 5.5), 2026-09-26, from the backlog triage with Brandon ("we want to refine
and optimize our strategy or have multiple methods we can use").
**Status:** WORKING INPUT, not for separate adoption. Owner direction 2026-09-26: fold into the unified
research-to-production design (todo 436) as its methods section.
**Parents:** `docs/plans/2026-09-24-evidence-framework.md` (E15, adopted),
`docs/plans/2026-09-25-alpha-research-architecture.md` (adopted). Input to todo 436; the methods depend on todo 435.

## 1. The decision proposed

Keep one evidence path for everything, and let several methods compete inside it. The strategy
is refined by comparing methods on the same test, not by choosing one method in advance.

Renaissance's reported edge is many weak signals pooled in one model, with discovery driven by
data as much as by economic story. The adopted framework already has the first half (one book,
walk-forward combination, breadth). This plan adds the second: more than one way to propose
members and more than one way to combine them, all charged to the same budget.

## 2. The fixed evidence path

Unchanged from E15 and the architecture plan: the research layer (S0 to S9), the S6 ledger, the
screen budget (M = 30 per vintage, bar p < 0.00167 on vintage 1), one confirmation of a frozen
book on the forward span, capital sized net of costs after confirmation and scaled by forward
results. No method gets a softer test, so results stay comparable.

## 3. Discovery methods (how members are proposed)

| Method | What it proposes | Disclosure |
|---|---|---|
| D1 Prior-driven families | 3-8 variants of one published or reasoned mechanism (families 1-10 in the ledger) | Seen-data looks disclosed per family |
| D2 Whole corpus as one family | Every `feature_vectors` column that passes guards, no per-member prior (the ledger's reopened corpus-features row) | Corpus IC table disclosed as context |
| D3 Interaction terms | Theory-motivated pairwise terms (Interaction Factory v2, ledger section 3) | Pilot's 22.2% BH-FDR pass disclosed |
| D4 IC as proposer | ic_engine's per-feature IC selects members | Recorded as outcome-informed: the screen is optimistic, the forward confirmation is not |
| D5 Learned members (later) | ML-derived features | Declared memory and guards like any member |

D2 and D4 differ on purpose: D2 takes everything and lets the combiner weight it; D4 selects
first. Running both answers whether selection helps on this data.

## 4. Combination methods (book versions)

Equal weight (E17 default), walk-forward ridge (S7), regime-conditioned (ledger section 3, poor
prior, one variant), gradient-boosted (ledger section 3, never run). Each is a book version and
spends one screen.

## 5. The budget decides the order

30 screens per vintage and one forward span are the binding constraint. Before any method
spends a real screen:

1. Synthetic power at the pre-declared effect (the E15 refusal rule already applies).
2. Disclosed diagnostics on the vintage that do not decide admission (member IC term structure,
   turnover, cost band).
3. The owner picks which methods spend screens, in writing, before the run.

Proposed first sequence once todo 435 lands: D1 families already registered (1, 2), then D2 with
the equal-weight and ridge combiners (two screens), then D4 against D2 (one screen). That spends
about 5 of 30 and answers the three biggest open questions: do features add to price-only
families, does the combiner matter, does per-feature selection help.

## 6. What this does not change

E15's rules, E16/E17's statistic, the ledger as the single list of ideas, and the forward span's
single use.
