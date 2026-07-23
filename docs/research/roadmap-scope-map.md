# Roadmap Scope & Impact Map

**Status:** current
**Last Updated:** 2026-07-23 (Phase 148's OOS verdict landed — see area 1 and the ranking note below; re-ranked against `PROJECT.md`'s confirmed endgame: personal live trading capital)
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

**Update 2026-07-23:** Phase 148 ran the two OOS proof gates this whole ranking's #1 item existed
to produce. Result is a split verdict, not a clean pass: Gate 1 (signal proof) **PASS** —
`alpha_score` genuinely predicts forward returns out-of-sample (21.875% of 5m/15m cells qualify,
>10x the 2% floor). Gate 2 (execution proof) **FAIL**, decisively — 3 of 5 SHADOW-REVIEW criteria
fail, including a ~960% max drawdown against a 0.25 ceiling. Decision: do not promote to live
capital. This moves the hard gate from "does edge exist" (area 1, now partially answered) to
"can the current frame/execution rules capture it" (area 2's territory) — ROADMAP Phase 166
(Frame/Execution Recalibration, registered 2026-07-23, not yet planned) is now the literal
next step, not a generic area-2 backlog item. See area 1's bullets below for detail.

1. **Core Alpha Pipeline** — highest, though its central open question (does OOS edge exist) is now half-answered: signal proof passed, execution proof failed. The hard gate has shifted from "prove edge exists" to "can it be captured" — see the 2026-07-23 update above and area 3 below.
2. **Signal / Trade Construction Layer (incl. minimum risk management)** — promoted, and now carries the actual next-step item: Phase 166 diagnosing Gate 2's failure and recalibrating stop/target/hold against the IC decay curve. Minimum risk controls (position limits, drawdown circuit breakers) belong here too, not filed under long-horizon product vision — see area 3.
3. **Platform / Infrastructure** — promoted from background risk. Real capital raises the cost of a silent bug or crash from "embarrassing" to "lost money" — reliability work matters more now than it did as a pure research system.
4. **Governance / Concept Lifecycle** — still foundational and cheap now, but less urgent than 2-3 under this lens.
5. **AI / Agentic Layer** — low, by design. Restraint is the correct call right now, not investment.
6. **Product Vision — Adjacent Platforms** — demoted, with one exception. AegisAgent's risk-overlay ideas and TradeAgent's execution-vehicle framing partially overlap with area 2 and are worth a second read specifically for that overlap. DerivAgent, PrimeAgent, QualAgent, FlowAgent, FundAgent, and the commercialization path describe a *different* endgame (building a product for others) and are correctly parked — zero urgency unless the endgame changes.
7. **Ops / Misc** — low, mostly small adopted items.
8. **Renaissance Philosophy / Research** — reference only, no open work.

---

## 1. Core Alpha Pipeline (Stages 0-4: Feature Factory → Stratification → Edge Measurement → Ensemble → Emission)

**Weak / open:**
- **Phase 148's OOS gates landed a split verdict (2026-07-23), the central fact for this whole area now:** Gate 1 (signal proof) PASS — `alpha_score` genuinely predicts forward returns OOS (21.875% of 5m/15m cells qualify). Gate 2 (execution proof) FAIL, decisively — 3 of 5 SHADOW-REVIEW criteria fail (~960% max drawdown vs a 0.25 ceiling). Do not promote to live capital. The pipeline's signal-generation side is proven; its frame/execution side is not. See `docs/plans/2026-07-22-phase148-promotion-decision.md` for full evidence.
- Two regime systems (per-symbol HMM, cross-sectional VIX×breadth) still unreconciled — no single stratification contract.
- No proof the intelligence vectors (Quant/Macro/Flow/Qual) are actually statistically independent — orthogonality is asserted, not measured.
- No single unified orthogonalization/marginal-value gate exists — but the underlying discipline is real and distributed, not simply absent (corrected 2026-07-18, see `unified-orthogonalization-layer.md`'s superseded-note): feature-grain redundancy is already handled by `ensemble_trainer`'s live Ledoit-Wolf cluster deflation (decision D4); regime-grain substitution testing is specced in Phase 145; portfolio-grain effective-N/Kelly is specced in Phase 157 (not yet planned). The real gap is Phase 145 hasn't shipped and Phase 157 hasn't been planned, not that orthogonalization is unaddressed.
- Edge measurement is Spearman-IC only — blind to real-but-nonmonotonic relationships.

**Proposed:**
- **Phase 166 (Frame/Execution Recalibration, registered 2026-07-23, not yet planned)** — diagnose Gate 2's failure and recalibrate stop/target/hold against the IC decay curve; the pre-registered playbook for exactly this split verdict. This is now the highest-impact concrete next step in this area — everything below is either already gated on a different question or unaffected by Gate 2's result.
- `intel-12` StratificationDimension — unifies the two regime systems behind one contract (v3.15, Phases 144/145).
- Phase 142B.1 — four candidate ensemble-weighting mechanisms (E1-E4) being A/B judged.
- PrecedentEngine (`intel-precedent-engine.md`, renamed from AnalogEngine 2026-07-09 — corrected 2026-07-18) — non-parametric K-NN retrieval as an alternative predictor family, gated on the current pipeline's OOS proof holding up. Its gate is signal-level (Gate 1, which passed) — Gate 2's execution failure doesn't block this, since PrecedentEngine proposes an alternative predictor, not an alternative frame. Registered as ROADMAP Phase 150.
- Mutual-information as a secondary edge-measurement statistic — flagged as a real open question, not yet scoped as a todo.
- Phase 162 (ic_engine Corpus Pipeline Throughput) shipped 2026-07-23 — whole-cell fingerprinting turns a full-corpus re-run into a minutes-not-hours no-op skip; the precondition for ever running this pipeline on a cadence. Platform/infra value (area 4), not signal value — noted here since it's the same file.

## 2. Governance / Concept Lifecycle

**Weak:** features, regimes, tags, and confluence patterns have each grown their own ad hoc lifecycle — no shared promotion/demotion discipline across concept types.

**Proposed:** Concept Governance Registries (4-table MVP: registry/gate/transition_log/annotation); Feature Registry (shipped); Instrument Tag Calibrator; Controlled Vocabulary.

## 3. Signal / Trade Construction Layer (the live-trading on-ramp)

**Weak:** no forecast-to-position translation yet (sizing, trade framing); no minimum risk management exists anywhere in the codebase today (no position limits, no drawdown circuit breaker); signal/trade separation architecture proposed but not fully realized; known SR/zone-engine accuracy gaps. **Phase 148 (2026-07-23) sharpened this: the existing frame simulation (stop/target/hold) fails execution proof decisively (Gate 2, 3/5 SHADOW-REVIEW criteria) even though the underlying signal is real (Gate 1 PASS) — this area's current frame design is now a demonstrated, not just suspected, weak point.**

**Proposed:** **Phase 166 (Frame/Execution Recalibration) is the immediate next step here**, not the longer-horizon Trade Construction Layer below — it diagnoses whether the *existing* frame can be recalibrated (stop/target/hold against the IC decay curve) before any v4.0 redesign is warranted. Trade Construction Layer (v4.0, gated on IC proof — signal-side proof cleared 2026-07-23, execution-side proof did not; this is the actual on-ramp to personal live trading, not a generic feature) should wait on Phase 166's finding, since building a new construction layer on top of a frame design already shown not to work would repeat the same gap. Canonical Simulator (binding rule shipped — one shared counterfactual ledger, no engine built yet); zone-engine refinements. Worth reading AegisAgent's risk-overlay design (area 6) and TradeAgent's execution-vehicle design specifically for reusable pieces before building this from scratch.

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
