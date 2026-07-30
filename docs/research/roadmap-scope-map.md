# Roadmap Scope & Impact Map

**Status:** current
**Last Updated:** 2026-07-30 (a cluster of measurement-integrity bugs surfaced in the
Core Alpha Pipeline this week — canary cross-sectional pseudo-replication, a regime-wipe upsert
bug, a provisional per-tf lookahead grid — see area 1's new bullet; doesn't change the ranking
below, these are execution-quality fixes to an already-#1-ranked area, not a new area)
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

**Update 2026-07-27:** Phase 148 ran the two OOS proof gates this whole ranking's #1 item existed
to produce. Result was a split verdict: Gate 1 (signal proof) **PASS** —
`alpha_score` genuinely predicts forward returns out-of-sample (21.875% of 5m/15m cells qualify,
>10x the 2% floor). Gate 2 (execution proof) **FAIL**, decisively — 3 of 5 SHADOW-REVIEW criteria
fail, including a ~960% max drawdown against a 0.25 ceiling. Do not promote that construction to
live capital. **Phase 166 (2026-07-23) diagnosed why, decisively:** neither the baseline nor a
retuned scalar stop/target candidate cleared gate166's drawdown ceiling; the direct follow-on
(todo 179) found the real cause is a market-data fact, not an execution-frame defect —
`mid_bull`'s raw, un-barriered forward return is negative at every horizon, which no
stop/target/hold tuning fixes. That closed "recalibrate the existing construction" and opened a
fork: more features, a different construction over the *existing* features, or accept no edge.
**Phase 167 (Cross-Sectional Trade Construction, T3) resolved it 2026-07-27 — COMPLETE, both
live Validation Gates PASSED** (`gate1_passes=true`, `gate2_passes_overall=true`) against the
real OOS population, the first construction in this project to clear both. This is the new
central fact: the pipeline's signal-generation side is proven both ways (per-symbol Gate 1 and
now a cross-sectional construction clearing Gate 2 too). Phase 156-159's stated precondition
(a proven, attribution-honest signal) is now met — **but the user redirected priority
2026-07-27 toward validating the features/regimes/IC/ensemble signal-generation stack further
before investing in execution/sizing**, so 156-159 is not the literal next step despite being
unblocked. See area 1's bullets below for detail.

1. **Core Alpha Pipeline** — highest. Its central open question (does OOS edge exist, and is there a construction that captures it) is now answered for one construction: Phase 167's cross-sectional spread passed both gates. Current open thread is validating that signal-generation stack further (regime labels, ensemble combiner) before building on top of it — see the 2026-07-27 update above.
2. **Signal / Trade Construction Layer (incl. minimum risk management)** — Phase 167 shipped a construction that clears both gates; Phase 156-159 (size/execute it) is unblocked but deliberately not started yet, pending further signal-stack validation. Minimum risk controls (position limits, drawdown circuit breakers) belong here too, not filed under long-horizon product vision — see area 3.
3. **Platform / Infrastructure** — promoted from background risk. Real capital raises the cost of a silent bug or crash from "embarrassing" to "lost money" — reliability work matters more now than it did as a pure research system.
4. **Governance / Concept Lifecycle** — still foundational and cheap now, but less urgent than 2-3 under this lens.
5. **AI / Agentic Layer** — low, by design. Restraint is the correct call right now, not investment.
6. **Product Vision — Adjacent Platforms** — demoted, with one exception. AegisAgent's risk-overlay ideas and TradeAgent's execution-vehicle framing partially overlap with area 2 and are worth a second read specifically for that overlap. DerivAgent, PrimeAgent, QualAgent, FlowAgent, FundAgent, and the commercialization path describe a *different* endgame (building a product for others) and are correctly parked — zero urgency unless the endgame changes.
7. **Ops / Misc** — low, mostly small adopted items.
8. **Renaissance Philosophy / Research** — reference only, no open work.

---

## 1. Core Alpha Pipeline (Stages 0-4: Feature Factory → Stratification → Edge Measurement → Ensemble → Emission)

**Weak / open:**
- **Phase 148's OOS gates found the per-symbol directional construction's signal was real but its execution frame wasn't (2026-07-22/23):** Gate 1 PASS, Gate 2 FAIL (~960% max drawdown vs a 0.25 ceiling). Phase 166 (2026-07-23) confirmed the frame couldn't be recalibrated to fix it — the real cause (todo 179) is `mid_bull`'s raw forward return being negative at every horizon, a market-data fact. **Phase 167 (2026-07-27) then found a construction that works: cross-sectional long-short decile spreads over `ctf_momentum` passed both live Validation Gates against the real OOS population** — the first construction here to clear Gate 2. See `docs/research/trade-construction-layer.md` and `docs/research/data-edge-source-thesis.md` for full evidence.
- T5 (non-linear ensemble combiner) is a live open question, not yet a settled finding: cleared its canary-leakage check, but 2026-07-27's equity/1d replication confirmed the effect is small (~16x smaller than the original 1h magnitude), not the large effect first reported. 15m replication (the tf Phase 167 actually trades) is deferred on memory contention — todo 188.
- Two regime systems (per-symbol HMM, cross-sectional VIX×breadth) still unreconciled — no single stratification contract.
- No proof the intelligence vectors (Quant/Macro/Flow/Qual) are actually statistically independent — orthogonality is asserted, not measured.
- No single unified orthogonalization/marginal-value gate exists — but the underlying discipline is real and distributed, not simply absent (corrected 2026-07-18, see `unified-orthogonalization-layer.md`'s superseded-note): feature-grain redundancy is already handled by `ensemble_trainer`'s live Ledoit-Wolf cluster deflation (decision D4); regime-grain substitution testing is specced in Phase 145; portfolio-grain effective-N/Kelly is specced in Phase 157 (not yet planned). The real gap is Phase 145 hasn't shipped and Phase 157 hasn't been planned, not that orthogonalization is unaddressed.
- Edge measurement is Spearman-IC only — blind to real-but-nonmonotonic relationships.
- **New 2026-07-30: a cluster of measurement-integrity bugs, mostly fixed same-week, one still open.** Canary negative controls (and by extension every broadcast/market-wide feature — `vix_z`, session/calendar features) were pseudo-replicated cross-sectionally, sharing one RNG draw across all symbols at a given timestamp instead of drawing independently per symbol — fixed (todo 203), but the general broadcast-aware significance test this implies is still an open design question. Separately, the Phase 164/165 `--refresh` recompute's upsert clobbered `feature_vectors.regime` for all 36.8M rows (todo 205, fixed, repair pipeline running as of this update — see `.planning/STATE.md`). And todo 146's per-tf IC lookahead grid, though already shipped to production APR, is now disputed for 5m/15m/1h by todo 208's live completeness numbers (1h `mid` only 53.5%) — treat that grid as provisional, not settled, until 208's empirical check runs. None of these change Phase 167's own T3 result (no dependency on regime labels or the disputed grid tiers), but they matter for trusting *other* measurements taken from the same corpus in this window.

**Proposed:**
- ~~Todo 183's corpus recompute, then re-run todo 179's regime sweep~~ — **DONE 2026-07-27.** T2's "dead" verdict is now confirmed on live corrected regime labels (270 cells, zero pass), no longer provisional. Doesn't affect T3/Phase 167's own result (no regime dependency).
- Phase 156-159 (Portfolio State/Sizing/Execution/Cost) — unblocked by Phase 167 clearing its stated precondition, but deliberately not started; user wants the signal-generation stack (features/regimes/IC/ensemble) validated further first.
- `intel-12` StratificationDimension — unifies the two regime systems behind one contract (v3.15, Phases 144/145).
- Phase 142B.1 — four candidate ensemble-weighting mechanisms (E1-E4) being A/B judged.
- PrecedentEngine (`intel-precedent-engine.md`, renamed from AnalogEngine 2026-07-09 — corrected 2026-07-18) — non-parametric K-NN retrieval as an alternative predictor family, gated on the current pipeline's OOS proof holding up. Its gate is signal-level (Gate 1, which passed) — Gate 2's execution failure doesn't block this, since PrecedentEngine proposes an alternative predictor, not an alternative frame. Registered as ROADMAP Phase 150.
- Mutual-information as a secondary edge-measurement statistic — flagged as a real open question, not yet scoped as a todo.
- Phase 162 (ic_engine Corpus Pipeline Throughput) shipped 2026-07-23 — whole-cell fingerprinting turns a full-corpus re-run into a minutes-not-hours no-op skip; the precondition for ever running this pipeline on a cadence. Platform/infra value (area 4), not signal value — noted here since it's the same file.

## 2. Governance / Concept Lifecycle

**Weak:** features, regimes, tags, and confluence patterns have each grown their own ad hoc lifecycle — no shared promotion/demotion discipline across concept types.

**Proposed:** Concept Governance Registries (4-table MVP: registry/gate/transition_log/annotation); Feature Registry (shipped); Instrument Tag Calibrator; Controlled Vocabulary.

## 3. Signal / Trade Construction Layer (the live-trading on-ramp)

**Weak:** no forecast-to-position translation yet (sizing, trade framing) for the newly-proven Phase 167 construction; no minimum risk management exists anywhere in the codebase today (no position limits, no drawdown circuit breaker); known SR/zone-engine accuracy gaps. **The per-symbol directional construction's frame (Phase 148/166) is a demonstrated dead end — not a data problem, a construction-choice problem, resolved by switching to cross-sectional (Phase 167), not by further stop/target tuning.**

**Proposed:** **Phase 156-159 (Portfolio State/Sizing/Execution/Cost) is the on-ramp to personal live trading now that Phase 167 has a construction proven through both gates** — its stated precondition (a proven, attribution-honest signal) is met. **Deliberately not started as of 2026-07-27**, per explicit user redirect: validate the features/regimes/IC/ensemble signal-generation stack further first (see area 1). Canonical Simulator (binding rule shipped — one shared counterfactual ledger, no engine built yet); zone-engine refinements. Worth reading AegisAgent's risk-overlay design (area 6) and TradeAgent's execution-vehicle design specifically for reusable pieces before building this from scratch.

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
