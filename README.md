# IndicAgent

A quantitative market research platform built to one standard: nothing is believed until it is measured. A person proposes what to measure, the data decides what predicts, and every result, including every refusal, is kept so the next proposal starts better.

It is a research system first. Trading is one possible output of it, and the larger aim is an intelligence layer that improves its own machinery: the measurements it takes, how often and over what windows, and how the results are combined.

The discipline is borrowed on purpose from two places. From Renaissance Technologies and Jim Simons, proof before belief: intuition proposes and measurement decides. From the five-step engineering mandate, question first, delete second, simplify third, and only then speed up and automate.

---

## Where it stands

Stated plainly, because the rigor below only means something if it is applied to this project's own claims. Figures are as of 2026-10-14 and come from the live database and `.planning/STATE.md`.

- **Feature-level evidence is real; a tradeable construction is not yet proven.** Individual measurements show statistically real, replicated predictive power. No book has yet passed confirmation net of trading costs, and none trades capital.
- **The platform is mid-rebuild.** Milestone v3.5 (Unified Research Pipeline) replaces the earlier ensemble chain with one pipeline from raw data to a frozen book. Research attempts are paused while the build lands (owner decision, 2026-09-27).
- **The data layer is large and growing.** 1,529 active instruments (1,502 eligible for daily computation). Daily history reaches back to 2000. Five-minute bars cover every eligible name, and a deep backfill of the 2006 to 2015 intraday history is running.
- **The registry governs 302 features** (295 active, 5 candidate, 2 deprecated), each with a recorded lifecycle.

Live status: [`.planning/STATE.md`](.planning/STATE.md). Every research verdict: [`docs/research/construction-verdict-ledger.md`](docs/research/construction-verdict-ledger.md).

---

## The north star

Twenty-two truths in four groups. Full text, with where each one is enforced in the code: [`docs/foundation/north-star-truths.md`](docs/foundation/north-star-truths.md).

**What counts as true**
1. Proof before belief. Intuition proposes; measurement decides.
2. The default is no edge. Every positive result carries the burden of proof.
3. Judge only what could have been traded: prices someone could actually have had, after cost.
4. Only what was knowable at the time enters a test. Nothing borrows from the future.
5. Unseen data is spent once. Searching is a screen; confirmation happens once, on data nobody has searched.
6. Every look is counted. Each pass over the data spends some credibility.
7. Tests that cannot answer the question are not run.
8. Measure outcomes, not activity.

**Where edge comes from**

9. Edge is discovered, not designed. If the answer to "who decides what matters here?" is the researcher, the design is wrong.
10. Many small edges, combined. No single measurement is the insight.
11. Every edge has a counterparty: name who is on the other side, and why they are wrong.
12. The market is taken out. A result is what is left once the tide is removed.
13. Stability counts as much as size.
14. Condition on context; never discard it.

**How the practice runs**

15. Influence is earned and can be lost, with hysteresis: recovery needs new proof.
16. What was turned down is data. Refusals are kept, and failures are studied.
17. Nothing is overwritten, and every result can be reproduced.
18. Every source clears the same bar. A new kind of data gets no exemption.
19. The vocabulary is the model. A term has one meaning.
20. Question first, delete second, simplify third. Speed and automation come last.

**How risk is held** (designed; the risk layer is not built yet)

21. Risk sits above the forecast. Limits can halt the book, and nothing in the research can override them.
22. No single bet matters. Many small positions, sized from the cautious end of the evidence.

---

## The pipeline

```
ingest -> feature -> measure -> research -> frozen book -> forward run -> capital
```

| Stage | What it does |
|---|---|
| **Ingest** | Bars from IBKR (daily primary and deep history) and Alpaca (five-minute), written through one ingress contract. Every vendor row is kept under its supplier's label; missing data stays missing. |
| **Feature** | Measurements computed on every bar, unconditionally, with no directional opinion. Point in time: universe, classification, tags and parameters as of the bar. |
| **Measure** | Information coefficient of every feature against executable forward returns (open to open), per symbol and pooled, conditioned on regime, on non-overlapping windows. |
| **Research** | Panel, residualized target, pre-registered families, mechanical guards, a walk-forward combiner that sets member weights, a construction rule, and a book test. Every run is recorded in `research_run`. |
| **Frozen book** | A book's members, combiner, construction rule and horizon rule are frozen with a spec hash in the registry. Any change makes a new book version. |
| **Forward run** | Frozen books run forward in sealed shadow on data nobody has searched (phase 188, designed). |
| **Capital** | Sized net of costs from the low end of the evidence, after confirmation (designed). |

Design of record: [`docs/plans/2026-09-26-unified-research-to-production-design.md`](docs/plans/2026-09-26-unified-research-to-production-design.md).

---

## The evidence framework

Adopted 2026-09-25 and amended 2026-09-26 ([`docs/plans/2026-09-24-evidence-framework.md`](docs/plans/2026-09-24-evidence-framework.md)):

- **The unit of test is a book**, not an idea. Ideas enter as pre-registered family members, and the book is what gets tested.
- **The searched data is a screen.** Error control comes from one confirmation of a frozen book on its own unsearched forward span.
- **Every look is counted**, and selection is corrected with Romano-Wolf StepM.
- **No underpowered test runs.** A test that cannot resolve its bar is refused before any real-data number exists.
- **Promotion needs positive net expectation.** Costs never enter a test statistic, but nothing is promoted that loses money after them.

---

## The research program

Twelve families of ideas are designed or under study, each with a stated mechanism, a named counterparty and a falsification condition. They include same-time-of-day periodicity, overnight versus intraday returns, short-term reversal, residual and industry momentum, fund-to-constituent and cross-asset lead-lag, period-end marking, window dressing and tax-loss flows, options expiry, index reconstitution, price anchoring, volume and order flow, and a governed generative grammar over price and volume primitives.

Many earlier ideas have been retired, and the reasons are kept: look-ahead found in a join, a real signal that did not survive cost, a market tilt mistaken for skill, a result that held only on the data it was fitted to, and a data fault that made a model look stronger than it was. The scorecard and every frozen verdict are in the [research ledger](docs/research/construction-verdict-ledger.md) and the [edge source thesis](docs/research/data-edge-source-thesis.md).

---

## Where it is going

The aim is for agentic workflows to drive the research inside the same gates as everything else: a population of candidate ideas generated, tested on data it has not seen, and selected with no person in the loop. The narrow first step, evolving the parameters in the Adaptive Parameter Registry, is designed in [`docs/ideas/eai-apr-parameter-evolution.md`](docs/ideas/eai-apr-parameter-evolution.md); the original design is archived in [`docs/research/archive/ai-03-evolvable-ai-agents.md`](docs/research/archive/ai-03-evolvable-ai-agents.md). None of it is built yet.

Further information domains are designed to clear the same measurement before they matter: institutional flow and positioning, derivatives, news and narrative, and fundamentals.

---

## Keeping a growing system legible

- **Naming with a falsifiable test.** A name is right if an expert who has never seen the code can predict the object's role from it. One concept name derives every layer's label. [`naming-system.md`](docs/foundation/naming-system.md)
- **One definition per term.** When code and the glossary disagree, the glossary wins. [`glossary.md`](docs/foundation/glossary.md)
- **One lifecycle for every governed concept.** The Unified Concept Registry runs `candidate -> shadow_only -> active -> deprecated`, and only its service flips a status. [`unified-concept-registry.md`](docs/foundation/unified-concept-registry.md)
- **No hard-coded numbers.** Every tunable value is a versioned row in the Adaptive Parameter Registry, with who changed it and why. [`adaptive-parameter-registry.md`](docs/foundation/adaptive-parameter-registry.md)
- **Research invariants enforced in code:** temporal integrity, determinism (bit-exact reproduction), single writer per table, no filled data, point-in-time reads, lineage, and asset-agnostic computation.

---

## History

The first generation (2026) was an event-driven, real-time pipeline: eight analytical tiers, a specialist agent swarm and a language-model narrative layer. Its flaw was not the engineering but the method: its signal plugins encoded human theories about what a good setup looks like, so it could only find edges someone already believed in. It was removed in phase 185 (archive tag `archive/v2x-ai-stack-2026-10`) in favor of measurement-first discovery. Its design remains documented in [`docs/architecture/architecture-v2-event-driven-pipeline.md`](docs/architecture/architecture-v2-event-driven-pipeline.md).

---

## Documentation

Docs in `docs/foundation/` carry a verification contract: a document marked `Status: current` has had its claims traced to code, tables or live state as of its date.

| Document | Covers |
|---|---|
| [North star truths](docs/foundation/north-star-truths.md) | The twenty-two truths and where each is enforced |
| [Principles](docs/foundation/principles.md) | The detailed principles, design frame and decision heuristics |
| [Evidence framework](docs/plans/2026-09-24-evidence-framework.md) | Book-level tests, a counted screen, one confirmation on unsearched data |
| [Unified design](docs/plans/2026-09-26-unified-research-to-production-design.md) | The one pipeline from data to capital |
| [Research ledger](docs/research/construction-verdict-ledger.md) | Every idea and where it stands |
| [Edge source thesis](docs/research/data-edge-source-thesis.md) | Who is on the other side of each proposed edge |
| [Naming system](docs/foundation/naming-system.md) and [glossary](docs/foundation/glossary.md) | The controlled vocabulary |
| [Five-step process](docs/foundation/musk-5-step-process.md) | Question, delete, simplify, accelerate, automate |
| [Rigor playbook](docs/renaissance-rigor-playbook/README.md) | A portable version of these standards for other projects |

For AI assistants: [CLAUDE.md](CLAUDE.md) holds architecture, commands and conventions.
