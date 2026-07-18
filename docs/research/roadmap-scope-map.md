# Roadmap Scope & Impact Map

**Status:** current
**Last Updated:** 2026-07-05 (re-ranked against `PROJECT.md`'s confirmed endgame: personal live trading capital)
**Purpose:** one page, high level — what's weak or missing in each major area of the system,
what's being proposed to address it, and roughly how much it matters. Built for product-management
scanning (scope and breadth), not implementation detail. For depth: `idea-catalog.md` is the full
navigation index across every doc; `intelligence-lifecycle-backlog-matrix.md` is the
effort/risk/reward sequencing within the Core Alpha Pipeline area below.
**Keep current:** when a new idea/plan meaningfully changes an area's weak points or proposals,
update that area's bullets here in the same commit. This doc stays a paragraph or two per area —
if an area's bullets are growing long, that's a signal the detail belongs in the catalog/matrix
instead, not a reason to expand this doc.

---

## Impact ranking, across all areas

**Ranked against the endgame confirmed 2026-07-05 (`PROJECT.md` Core Value): personal live
trading capital, not a commercial product or pure research exercise. "Impact" below means
distance-to-placing-a-real-trade-with-real-money, not general engineering value.**

1. **Core Alpha Pipeline** — highest. Nothing sizes a live trade until this proves out-of-sample edge — the hard gate everything else waits behind.
2. **Signal / Trade Construction Layer (incl. minimum risk management)** — promoted. This is the literal next step after edge is proven: turning an alpha_event into a sized position you'd actually place. Minimum risk controls (position limits, drawdown circuit breakers) belong here now, not filed under long-horizon product vision — see area 3.
3. **Platform / Infrastructure** — promoted from background risk. Real capital raises the cost of a silent bug or crash from "embarrassing" to "lost money" — reliability work matters more now than it did as a pure research system.
4. **Governance / Concept Lifecycle** — still foundational and cheap now, but less urgent than 2-3 under this lens.
5. **AI / Agentic Layer** — low, by design. Restraint is the correct call right now, not investment.
6. **Product Vision — Adjacent Platforms** — demoted, with one exception. AegisAgent's risk-overlay ideas and TradeAgent's execution-vehicle framing partially overlap with area 2 and are worth a second read specifically for that overlap. DerivAgent, PrimeAgent, QualAgent, FlowAgent, FundAgent, and the commercialization path describe a *different* endgame (building a product for others) and are correctly parked — zero urgency unless the endgame changes.
7. **Ops / Misc** — low, mostly small adopted items.
8. **Renaissance Philosophy / Research** — reference only, no open work.

---

## 1. Core Alpha Pipeline (Stages 0-4: Feature Factory → Stratification → Edge Measurement → Ensemble → Emission)

**Weak / open:**
- Two regime systems (per-symbol HMM, cross-sectional VIX×breadth) still unreconciled — no single stratification contract.
- No proof the intelligence vectors (Quant/Macro/Flow/Qual) are actually statistically independent — orthogonality is asserted, not measured.
- No vector orthogonalization/whitening step exists anywhere — correlated features go into the ensemble as-is.
- Edge measurement is Spearman-IC only — blind to real-but-nonmonotonic relationships.

**Proposed:**
- `intel-12` StratificationDimension — unifies the two regime systems behind one contract (v3.15, Phases 144/145).
- Phase 142B.1 — four candidate ensemble-weighting mechanisms (E1-E4) being A/B judged.
- AnalogEngine (`intel-13`) — non-parametric K-NN retrieval as an alternative predictor family, gated on the current pipeline's OOS proof holding up.
- Mutual-information as a secondary edge-measurement statistic — flagged as a real open question, not yet scoped as a todo.

## 2. Governance / Concept Lifecycle

**Weak:** features, regimes, tags, and confluence patterns have each grown their own ad hoc lifecycle — no shared promotion/demotion discipline across concept types.

**Proposed:** Concept Governance Registries (4-table MVP: registry/gate/transition_log/annotation); Feature Registry (shipped); Instrument Tag Calibrator; Controlled Vocabulary.

## 3. Signal / Trade Construction Layer (the live-trading on-ramp)

**Weak:** no forecast-to-position translation yet (sizing, trade framing); no minimum risk management exists anywhere in the codebase today (no position limits, no drawdown circuit breaker); signal/trade separation architecture proposed but not fully realized; known SR/zone-engine accuracy gaps.

**Proposed:** Trade Construction Layer (v4.0, gated on IC proof — this is the actual on-ramp to personal live trading, not a generic feature); Canonical Simulator (binding rule shipped — one shared counterfactual ledger, no engine built yet); zone-engine refinements. Worth reading AegisAgent's risk-overlay design (area 6) and TradeAgent's execution-vehicle design specifically for reusable pieces before building this from scratch.

## 4. Platform / Infrastructure

**Weak:** known architectural weak points — pipeline god class (~1,820 lines), settings god object, persistence fragility, service-resilience patterns only partially shipped (circuit breaker done, rest pending).

**Proposed:** incremental hardening per the platform docs — no big-bang rewrite proposed anywhere.

## 5. AI / Agentic Layer

**Weak:** some AI foundations shipped but unused (LineageRecorder, graduation logic); no evidence the current single-LLM-agent approach is actually insufficient.

**Proposed:** mostly held at low priority on purpose — the Occam's Razor Evaluator idea exists specifically to gate future orchestration/swarm complexity behind evidence of need. Correct posture here is restraint, not building more agents.

## 6. Product Vision — Adjacent Platforms (mostly a different endgame, not on roadmap)

Seven vision docs for standalone products: **AegisAgent** (risk overlay), **DerivAgent** (options/derivatives intelligence), **PrimeAgent** (portfolio management), **QualAgent** (fundamental/qualitative intelligence), **TradeAgent** (autonomous trading app), **FlowAgent** and **FundAgent** (scope unclear, titles only), plus a retail SaaS **commercialization** path.

Most of these describe building a product for other people — a different endgame than personal live trading (`PROJECT.md` Core Value) — and stay correctly parked, zero urgency. Two exceptions worth a second read specifically through the live-trading lens, not as commercial products: **AegisAgent**'s risk-overlay design (position sizing, portfolio-level constraints) is close to what area 3's "minimum risk management" needs; **TradeAgent**'s execution-vehicle design may already describe the shape of the personal live-trading front end, minus the multi-tenant/commercial framing.

## 7. Renaissance Philosophy / Research

Reference material underlying `docs/foundation/principles.md`. No open work items — settled, not a work area.

## 8. Ops / Misc

Small adopted items (BI/Superset analytics layer, futures-roll simplification) plus one open item: latency & persistence audit.
