# IndicAgent

A quantitative market research platform built to one standard: nothing is believed until it is measured. A person proposes what to measure, the data decides what predicts, and every result, including every refusal, is kept so the next proposal starts better.

It is a research system first. Trading is one possible output of it, and the larger aim is an intelligence layer that improves its own machinery: the measurements it takes, how often and over what windows, and how the results are combined.

The discipline is borrowed on purpose from two places. From Renaissance Technologies and Jim Simons, proof before belief: intuition proposes and measurement decides. From Elon Musk's five-step process, question first, delete second, simplify third, and only then speed up and automate.

## Cloud native, AI native, API first

- **API first.** Everything the platform knows is served over a FastAPI service: REST for queries, and Server-Sent Events for live streams. Market data, health, drift, validation and the controlled vocabulary each have their own routes, configuration has its own HTTP API, and a Next.js dashboard is just another client. Nothing is reachable only from inside a script.
- **Cloud native, self-hosted.** It is built the way cloud systems are: containerized infrastructure, a durable and replayable event bus (Redpanda, Kafka-compatible) so any service can fail and resume from its offset, a dependency graph that orders restarts, health checks and watchdogs on every service, scaling driven by measured consumer lag, and full observability (OpenTelemetry, Prometheus, Grafana, Loki, Tempo, Alertmanager). It runs on one self-hosted server today and moves to a cloud without a redesign.
- **AI native.** It is designed, built, reviewed and operated with AI agents working under the same rules as the code: planning and execution workflows, independent cross-model reviews before a design is adopted, and documentation written to be read by agents as well as people. The research direction is agentic too (see Where it is going), inside the same evidence gates.

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

Many earlier ideas have been retired, and the reasons are kept: look-ahead found in a join, a real signal that did not survive cost, a market tilt mistaken for skill, a result that held only on the data it was fitted to, and a data fault that made a model look stronger than it was. The first family studied shows how the bar works: its timing effect is statistically strong, but the edge sits at the opening and closing auction prints and no variant tried is net positive at measured spreads, so its book was refused. The scorecard and every frozen verdict are in the [research ledger](docs/research/construction-verdict-ledger.md) and the [edge source thesis](docs/research/data-edge-source-thesis.md).

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

## The stack

Python (async), PostgreSQL with TimescaleDB, and Redpanda as a durable, replayable event bus. Services run under systemd with dependency order derived from a declared DAG. Observability through OpenTelemetry, Prometheus and Grafana. Market data from Interactive Brokers (`ib_async`) and Alpaca. Every tunable value lives in the Adaptive Parameter Registry, not in code.

---

## The first generation: built, now archived

The first generation was built and run in production in early 2026, then archived in October 2026 (phase 185, plan 45) when the work moved to measurement-first discovery. The code is preserved at the git tag `archive/v2x-ai-stack-2026-10`, and its design is documented in [`docs/architecture/archive/architecture-v2-event-driven-pipeline.md`](docs/architecture/archive/architecture-v2-event-driven-pipeline.md). Figures below describe it as it ran at the time.

**An event-driven, real-time pipeline.** Eight analytical tiers ran end to end in under 10 ms per bar, live across 60 instruments spanning futures, ETFs, FX and crypto, computing about 729 data points per bar, per symbol, per timeframe, every one persisted and streamed.

| Tier | What it did |
|---|---|
| **I1** Raw indicators | 28 plugins, about 50 data points (RSI, MACD, Bollinger, ATR, VWAP, OFI, CVD), computed incrementally per bar |
| **I2** Composite events | Second-derivative measures: momentum inflection and trend exhaustion, scored before they complete |
| **I3** Market structure | Swings, support and resistance zones, market profile (POC and value area), anchored VWAP, session levels |
| **I4** Regime classification | Six independent models: GARCH, a Kalman filter, an HMM, BOCPD changepoints, the Hurst exponent and Shannon entropy |
| **I5** Pattern detection | Divergences, volatility squeezes, classical chart patterns |
| **I6** Smart money and confluence | An institutional order-flow model across six timeframes: breaks of structure, fair value gaps, order blocks, liquidity pools |
| **I7** Trading setups | 36 setups, each a full trade thesis with entry, stop and target, scored by a six-bucket confluence model requiring cross-tier agreement |
| **I8** AI narrative | Structured language-model analysis of every high-confidence setup, plus scheduled cross-asset synthesis |

Every setup passed a deterministic ten-stage quality pipeline before it was emitted: confidence clamping, decay for repeated fires, confluence scoring, structural and regime gates, time-of-day adjustment, isotonic calibration against real outcomes, ranking by rolling Sharpe, review by the specialist agents, and a final completeness check.

**The specialist agent swarm: a council, not an oracle.** Five independent agents each assessed one dimension of a setup: cross-asset correlation, regime coherence, the counterfactual bear case, historical analogs, and a mandatory adversarial skeptic that challenged every other agent's conclusion. Their outputs composed into a calibrated multiplier, so no single agent moved the result alone. The language-model layer was multi-provider (a local model on GPU with a cloud fallback and per-provider circuit breakers), so no single vendor was a dependency either.

**Empirical memory.** A pgvector store embedded market and setup context as vectors and retrieved the most similar historical episodes at decision time, grounding agent judgments in precedent the way a trader draws on experience. It included a Markov regime-transition prior and drift monitoring, and trusted nothing before 30 resolved observations.

**The learning agent council.** The same council pattern applied to model training: a LightGBM pipeline with a walk-forward 60/20/20 temporal split, per-regime segments gated at 100 observations, retraining only when enough new data had arrived, every model versioned in MLflow, and data validation and feature discovery as their own stages, orchestrated with LangGraph.

**Designed, never built: the head trader.** A synthesis agent to take the swarm's view, the portfolio and the regime, and make the final call, the way a desk's portfolio manager synthesizes a technician, a risk manager and a flow trader. The risk agent's halt authority sat above it by design: the head trader could decide whether to trade, never whether risk limits applied.

**Why it was archived.** The engineering held up; the method did not. Its setup plugins encoded human theories of what a good trade looks like, so it could only find edges someone already believed in, and it observed outcomes only where a hand-made filter fired. The current generation keeps the lessons (the council pattern, adversarial review, calibration against outcomes, shadow governance) and replaces the method with measurement on every bar. The agentic direction above is where those ideas return, inside the current evidence gates.

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
