# intel-10 / intel-11 Review — Confluence Persistence and the Dual-Track Framing

**Date:** 2026-07-03 · **Author:** Fable 5 (dispatched via Claude Code Agent tool) · **Type:** research/review, read-only
**Scope:** `docs/ideas/intel-10-confluence-detection-persistence-layer.md` (v2.0, 2026-07-01) and `docs/ideas/intel-11-dual-system-discrete-vs-portfolio.md` (v1.0, 2026-07-01), assessed against the 2026-07-02 topdown/bottomup reviews and the intel-12/13/14/15 docs that came out of them. Both target docs predate that review cycle by one day and were never run through it; this closes the gap.
**Verdict up front:** the statistical hygiene in both docs is real and survives scrutiny untouched. The *architecture* around it does not: intel-10 was written one day before the predictor abstraction (D1) and the AnalogEngine rescope (D4/intel-13) landed, and it rebuilds — at confluence grain — four layers the target architecture now owns generically. intel-11's best content ("One Model, One Book") logically dissolves its own dual-track frame. Both docs warrant rewrite, and the concrete replacement shapes are sketched in §5.

---

## 1. Findings — intel-10 (DiscreteTrack / Confluence Persistence)

### F1. The "terminal deliverable of the v3.0 pipeline" claim is superseded — a confluence is a predictor, not a new terminal layer. [HIGH]

Under the post-2026-07-02 architecture (topdown §2.2-2.3, intel-15), everything that claims to forecast forward returns is a **predictor**: a per-bar value measured by one Measurement Engine, weighted by one ensemble, emitted through one emission layer, validated by one frame simulator. A confluence fits this contract exactly: it is a nonlinear function of `feature_vectors` columns (or an analog neighborhood) producing a per-bar conditional expectation, NULL where the condition is absent — precisely the definedness semantics intel-13 already specified for analog predictors ("NULL, never zero"; sparsity handled by the existing min-obs gates; conditionality stated, never hidden).

Read that way, intel-10 duplicates, at confluence grain:

| intel-10 builds | Architecture already owns it as |
|---|---|
| Its own gate machinery (gates 2, 3, 6 — FDR, walk-forward, OOS) | Measurement Engine kernel — identical hygiene, one estimator (D1, intel-15) |
| Its own lifecycle (`candidate → shadow → active → decaying → retired`) | Concept Registry (intel-10 already concedes this — see F4, the one place it self-corrected) |
| A live daemon + `confluence_events` occurrence table | The emission layer (L6, `alpha_publisher`/`alpha_events`) — bottomup §4.6's emission-tier-vs-research-tier concept, solved once, not per-system |
| Occurrence rows opened-then-backfilled with realized returns | Phase 142B's `alpha_frames` — frozen claim at emission, outcome backfilled, pre-committed criteria. Topdown §1.9: one simulator concept |
| A calibrated E[R] estimate in return units | `2026-06-29-feature-scoring-beyond-ic.md` §0c — the calibration layer intel-11 itself identifies as shared and track-independent |

This is the same diagnosis intel-13 applied to AnalogEngine one day later: a well-designed parallel stack whose alpha content survives entirely as predictors + gate extensions inside the existing pipeline, and whose parallel infrastructure should be deleted. intel-10 simply predates that pattern. Nothing in it needs the "second, independently persisted event system" shape it currently has.

**What is genuinely novel in intel-10 and must be kept** (this is the doc's real content, and it is good):

1. **Gate 1 — marginal lift over the additive null** (partial IC / incremental OOS R² conditioned on the linear combination of the confluence's own constituents). This is the single most important idea in the doc and exists nowhere else in the built system. It belongs in the measurement kernel (`src/intelligence/measurement/`) as a gate mode, where Phase 147's interaction candidates use the identical function — one implementation, two consumers.
2. **Mandatory winner's-curse shrinkage on the persisted estimate.** Correct, and already echoed in the Concept Registry doc's `baseline_metric` shrinkage note — same mechanism, keep them explicitly unified (feature-scoring §0b's estimator, one implementation).
3. **Effective-N via temporal clustering correction** for occurrence counts. Correct; same HAC/subsampling discipline the kernel already has, applied to a new count.
4. **Per-concept calibration monitoring** (rolling reliability/Brier drift, CUSUM) driving registry transitions, plus `out_of_scope` occurrence tracking as free OOS evidence for scope expansion. Both correct; both are evaluation-engine behaviors writing Concept Registry state (D3: lifecycle out of measurement tables), not properties of a bespoke event system.

### F2. The ANALOG-08 Score Object convergence claim is stale — the convergence already happened, in the other direction. [HIGH]

intel-10 (Dependencies): "ANALOG-08's Score Object (E[R] distribution, direction, OOD flag, analog count) is a direct precursor of this doc's calibrated-estimate concept and should converge with it, not duplicate it." intel-13 (2026-07-02) **deleted the Score Object outright**: "What does not survive: the bespoke Score Object, the `score_cache` table, and the composite z-score's own weighting/orthogonalization machinery." What survives in intel-13 is the **return-distribution primitive** (full empirical distribution per horizon per query — percentiles, moments, shape label) plus analog predictor columns and the conviction envelope.

So intel-10's `calibrated_outcome_distribution` should be specified as *the same return-distribution primitive intel-13 preserves*, shrunk per F1.2 — not as a convergence target with an object that no longer exists in the design. This is a one-paragraph fix but it matters: as written, intel-10 directs a future implementer toward ANALOG-08's `score_cache`, which intel-13 killed.

**Related roadmap staleness (out of these docs' scope but found here):** ROADMAP.md Phases 145-146 still spec the *pre-rescope* AnalogEngine — `feature_ic_stats`, `similarity_pairs`, `score_cache`, Score Objects, `analog-enricher`, `embedding_feature_registry` — all of which intel-13/D4 deleted. Phase 146's closing note even instructs revisiting intel-10 "once this phase produces validated analog-based confluences" via the Score Object path. If 145-146 are planned from the ROADMAP text rather than intel-13, the D4 rescope silently un-happens. The ROADMAP v3.2 section needs rewriting against intel-13 before any 145-147 planning starts. (Filed here as a direct consequence of verifying intel-10's dependency claims.)

### F3. Silent-wrong-answer risk: gate 1's null model must be the *calibrated, shrunk* additive baseline — which makes feature-scoring §0b/0c a hard prerequisite neither doc states. [HIGH]

intel-11 itself admits the current combiner's weakness: "`alpha_score` = IC-weighted linear sum of z-scores — no units, no interaction capture, weights from raw selected ICs." If gate 1 tests incremental lift against *that* null, the gate is soft: a candidate confluence can clear it merely by recovering information a properly shrunk/calibrated linear combiner would have captured anyway. The system would then persist "validated confluences" whose entire edge is an artifact of a weak baseline — a silent wrong answer at the exact point the doc calls "the single most important gate."

intel-11 gets within one sentence of this ("a fancier combiner before calibration is polishing an instrument with no units") but never applies it to gate 1. The corrected dependency: **feature-scoring-beyond-ic §0b (shrunk weights) and §0c (calibrated return-unit output) are prerequisites of intel-10's gate 1**, not merely a shared upgrade path. The null model is the calibrated linear combination of the confluence's constituents, in return units — then "incremental lift" means what it claims to mean, and the cost-hurdle gate (gate 5) can compare like units to like.

### F4. The Concept Registry deferral is verified consistent — keep it exactly as written. [CONFIRMED SOLID]

intel-10's governance note (implement lifecycle in the registry's four-table MVP shape, `decaying` as a transition pattern `active → shadow_only`, not a new status) matches `concept-governance-registries.md`'s own cross-reference and mapping rule verbatim, and matches how the topdown review scoped the registry (D9: MVP at 142B.1 against `ensemble_strategy` first, `confluence`/`alpha_pattern` later once the AI-proposer invariants are exercised). No drift. This is the one part of intel-10 that was updated in step with the rest of the doc ecosystem, and it should survive the rewrite unchanged.

One sharpening: under F1, the lifecycle domain is a predictor domain. A confluence concept row is a `concept_registry` row whose gate stack is gates 1-6; there is no separate "confluence governance" — it is Concept Registry governance with a stricter gate template. That also resolves intel-10's open question 4 (calibration sample floor) as a `concept_gate` field, not a new mechanism.

### F5. Open question 2 (new `confluence_events` table) should resolve to **no new event table**. [MEDIUM]

The doc leans toward a new table on grain grounds ("sparse discrete fires vs per-bar scores"). But sparse-fires-above-a-calibrated-threshold *is* the emission tier — the exact distinction bottomup §4.6 named (`alpha_events` conflating research-grade per-bar scores with action-grade events). The right resolution is one emission concept with a source/predictor discriminator and a frames row per emitted claim (the frozen-claim + outcome-backfill semantics intel-10 wants are 142B's `alpha_frames` semantics, already designed with pre-committed review criteria). Building `confluence_events` alongside `alpha_events` + `alpha_frames` creates the third parallel claim-ledger in a system whose companion doc's headline invariant is "one book."

Similarly, the "live daemon" prerequisite is real but not confluence-specific — it is the same live-scoring/emission daemon the whole v3 stack lacks (bottomup §1.2: the live leg publishes into the void). Scope it once, at the emission layer, when *anything* is worth firing live; do not let intel-10 own it.

### F6. Everything else in intel-10 survives scrutiny. [CONFIRMED SOLID]

The 5-step application is honest (especially step 4: "do not build live infrastructure before one confluence has survived validation — there is nothing to detect yet"). The silent-failure-modes section is exactly right, including analog-index point-in-time discipline (independently re-derived in intel-13's substrate law) and threshold-drift-through-APR-only. Decay-as-steady-state with symmetric re-promotion matches 149B semantics. The supersession of intel-04 is correct. Open questions 1 and 3 are genuinely open and correctly deferred to data; open question 3's default ("combine conservatively, never sum") is the right pre-commitment.

---

## 2. Findings — intel-11 (DiscreteTrack vs PortfolioTrack)

### F7. "One Model, One Book" is correct — and it dissolves the doc's own dual-track frame. [HIGH]

The invariant says: one forecast per (symbol, tf, bar) is the end state; AnalogEngine scores, confluence events, ensemble scores are all *inputs* to one combined forecast, never parallel forecasts with separate consumers; one P&L. Taken seriously, there are no tracks. What the doc calls DiscreteTrack and PortfolioTrack are **two read surfaces of the same forecast**:

- **Sparse surface:** the emission tier — thresholded, provenance-carrying, auditable claims (already `alpha_events`; with intel-10's gates, some of those claims are confluence-sourced and carry calibrated distributions).
- **Dense surface:** the full forecast vector per bar, consumed by a portfolio constructor (v4.0's layer, currently and correctly unbuilt).

The doc's own coordination rule ("DiscreteTrack events can be a feature of PortfolioTrack but never the reverse") is a symptom of the frame, not a solution: once confluences are predictors inside the single ensemble (F1), the dependency question evaporates — there is nothing to coordinate because there is one model. "Two products on one validation substrate" is the earlier-generation-shop architecture the doc's own institutional review warned about, kept alive one section after the Simons-lens review refuted it. The doc records both positions without noticing they conflict; the Simons position wins.

### F8. The T3 argument is the doc's strongest content, and it does not require a "track" — it requires a measurement mode. [HIGH]

The asymmetry argument is genuinely load-bearing: per-symbol directional trading is the hardest way to monetize small IC; cross-sectional long-short cancels idiosyncratic noise and hedges beta; if T3 (`edge-source-thesis.md`) is where the edge lives, a directional-only system concludes "no edge" while a spread portfolio on the same features pays. Correct, and worth acting on *earlier and cheaper* than the doc proposes.

The minimal falsification instrument for T3 is not a portfolio constructor. It is:

1. **Cross-sectional rank IC as a Measurement Engine mode** — per-bar Spearman of `alpha_score` (or any predictor) against forward returns *across the 58-symbol universe*, aggregated over bars, with the cross-sectional effective-N correction that edge-source-thesis §P6 already flags as missing (58 correlated symbols on one bar are not 58 observations). This is a kernel extension, weeks not quarters, and it directly measures T3's premise.
2. **A counterfactual decile-spread simulation** in the 142B frame machinery — long top decile, short bottom decile, dollar-neutral, at the executable-return definition, cost-hurdle applied per leg. This is `alpha_frames` with a portfolio-shaped frame variant, not a new system.

If (1) shows cross-sectional IC materially exceeding time-series IC and (2) shows the spread paying net of the cost floor, *then* a portfolio-constructor design doc is warranted — with evidence in hand rather than institutional analogy. If not, T3 dies cheaply. This converts intel-11's "unscoped future System 2" into one concrete near-term measurement deliverable and one frame variant, which is the Renaissance-correct order: measure first, construct later.

### F9. Scoping PortfolioTrack as a named parallel track is premature architecture — the doc half-knows this. [MEDIUM]

"Prerequisite honesty" already says don't scope before 142A's gate, and "the first concrete deliverable is a design doc, not code." Good instincts. But naming a zero-code future system as a *track* — with its own consumer, its own definition of working, its own sequencing section — is exactly the parallel-system proliferation the One-Book invariant exists to block, applied to the doc's own proposal. At this account size and stage, the portfolio constructor (netting, risk model, turnover optimization) remains a v4.0 concern gated on the F8 evidence; it needs a paragraph in the roadmap, not a track identity. The useful residue of the PortfolioTrack section is: (a) the T3 testability argument (→ F8 deliverables), (b) the combiner upgrade sequencing 0b→0c→learned-only-if-it-beats-calibrated-linear-OOS (already canonical in feature-scoring-beyond-ic; intel-11 adds nothing beyond a correct restatement), (c) the observation that netting/risk-allocation/turnover live only at the portfolio layer (true; belongs in the v4.0 gate description).

### F10. Trigger-state staleness: the doc's own scoping trigger has (mechanically) fired. [LOW]

intel-11: "PortfolioTrack gets scoped only after Phase 142A proves ensemble OOS IC." Phase 142A completed 2026-07-02 — the `EnsembleICEngine`, EIC-04 gate script, and hold_max_bars calibration all shipped. Completion of the *machinery* is not the same as the EIC-04 gate *passing on OOS data*; the doc's trigger should be restated as "EIC-04 verdict = PASS on the OOS window" (and per intel-15, note the engine shipped as the standalone service D2 argued against — the measurement-unification question is now intel-15's problem, not this doc's). Either way, a doc whose trigger condition is ambiguous the day after it fires needs its trigger pinned to the gate verdict, not the phase status.

---

## 3. What's Solid (do not touch in any rewrite)

- **intel-10's gate stack as a *gate template***: marginal-lift null (with F3's calibrated-baseline fix), search-level BH-FDR, walk-forward stability, calibration (reliability/Brier), cost hurdle at executable returns, OOS confirmation, shadow-mode promotion at `n >= 100 AND bootstrap_ci_lower > 0`. As intel-11 correctly says, this stack is track-independent validation discipline at or above institutional standard.
- **Shrinkage-mandatory, effective-N, frozen-at-fire-time claims, out_of_scope tracking, symmetric decay/re-promotion, never-delete-retired.** All correct, all consistent with the Phase 142B SHADOW-REVIEW pre-commitment pattern and the 149B semantics.
- **intel-10's Concept Registry deferral** (F4) — verified consistent both directions.
- **intel-11's One Model, One Book invariant** — correct; too important to live in a draft idea doc (see R3).
- **intel-11's T3 asymmetry argument** — the strongest single reason cross-sectional measurement must exist.
- **Both docs' refusal to grow execution/sizing semantics** — Kelly/portfolio/execution stay v4.0; capacity/crowding stays out of scope. Right at this scale.

## 4. Direct Corrections

1. intel-10 header: "names the actual terminal deliverable of the v3.0 pipeline" — false under D1; the terminal artifacts remain emission (`alpha_events`) + frames (`alpha_frames`); confluences are predictors feeding both (F1).
2. intel-10 Dependencies: "ANALOG-08's Score Object … should converge with it" — the Score Object was deleted by intel-13; converge with intel-13's return-distribution primitive instead (F2).
3. intel-10 gate 1: null model must be the calibrated (§0c) shrunk (§0b) additive baseline; feature-scoring-beyond-ic §0b/0c become named prerequisites (F3).
4. intel-10 open question 2: resolve to no new `confluence_events` table — emission tier + `alpha_frames` (F5).
5. intel-10 "live daemon … scope it inside this phase" — scope it at the emission layer, once, system-wide (F5).
6. intel-11 §How the Two Tracks Relate: "two products with different consumers" contradicts the One-Book section three paragraphs later; the invariant wins (F7).
7. intel-11 sequencing trigger: pin to "EIC-04 PASS on OOS," not "Phase 142A complete" (F10).
8. ROADMAP.md Phases 145-146 text still specs the pre-intel-13 AnalogEngine (Score Object, `score_cache`, `feature_ic_stats`, `similarity_pairs`, enricher) — must be rewritten against intel-13 before v3.2 planning, or D4 silently reverts (F2).

## 5. Recommended Restructure (concrete, ready to execute)

The split does **not** earn its keep in current form. Replace the pair with:

**R1 — Rewrite intel-10 as "intel-10: Confluence — a Governed Predictor Family" (the intel-13 treatment).** Structure:
- *The core idea, stated once:* a confluence is an empirically validated joint condition, persisted as a governed predictor whose per-bar value is a shrunk, calibrated conditional-return distribution (intel-13's return-distribution primitive), NULL where the condition is absent (intel-13's definedness rules, inherited verbatim).
- *What gets deleted as separate systems:* bespoke lifecycle tables (→ Concept Registry MVP, keep F4's mapping note verbatim), `confluence_events` + bespoke live daemon (→ emission tier + `alpha_frames`), bespoke calibration estimate (→ feature-scoring §0b/0c, now named prerequisites).
- *What is genuinely new and where it lands:* gate 1 (marginal-lift-over-calibrated-additive-null) as a measurement-kernel gate mode shared with Phase 147; occurrence effective-N correction; per-concept calibration monitoring (reliability/Brier/CUSUM) as evaluation-engine behavior writing registry state; `out_of_scope` occurrence tracking; the conservative-combination default for simultaneous confluences.
- *Sequencing:* after Phase 147 supplies interaction candidates and intel-13's analog predictors supply neighborhood candidates; gated on §0b/0c landing; nothing built until one candidate survives gates 1-5 (its own step-4 discipline, kept).
- Keep open questions 1 and 3; retire 2 (resolved per F5); convert 4 into a `concept_gate` field.

**R2 — Retire intel-11 as a standalone doc**, extracting three survivors:
- The **T3 falsification deliverables** (cross-sectional rank IC measurement mode + decile-spread frame variant, F8) → a short new idea doc (or an intel-15 addendum, since it is a Measurement Engine mode) with the effective-N correction named as part of the spec.
- The **combiner upgrade sequencing** → already canonical in `2026-06-29-feature-scoring-beyond-ic.md`; add a cross-reference, delete the restatement.
- The **institutional-review record** (why discrete-named-patterns is a deliberate departure) → one paragraph of context in rewritten intel-10.

**R3 — Promote "One Model, One Book" out of the idea tier.** It is an architecture invariant with the same standing as the DAG invariants and Invariant 1 (executable returns): *every new forecasting proposal must state at creation how it feeds the single forecast and the single P&L; nothing ships as a second book; research tracks shadow-measure only.* It should live in `docs/foundation/principles.md` (or the DAG-invariants list), where it binds future proposals — including this review's own R1/R2 — rather than in a draft doc that half-contradicts it. This is the one piece of intel-11 that is load-bearing forever.

Net effect: one rewritten idea doc (confluence-as-predictor), one short measurement-mode doc, one new foundation invariant, one ROADMAP v3.2 correction, zero parallel tracks. All of intel-10's statistical content survives; all of intel-11's evidence survives; the two parallel-system shells are deleted — which is what the 5-step mandate says should happen to them.

## 6. Open Questions (for the operator)

1. **Does R3's invariant get foundation status now, or after 142B proves the single book is worth protecting?** My call: now — it is a constraint on *proposals*, and proposals (145-147, intel-10 successor) are being written this month.
2. **Cross-sectional rank IC (F8.1): kernel mode in the eventual MeasurementEngine, or a bolt-on to `ensemble_ic_engine.py` as it stands?** Depends on intel-15's unresolved unification decision; F8 should not wait on it — a bolt-on measured against `alpha_events ⋈ forward_returns` is acceptable if the kernel decision drags.
3. **Should the confluence gate template (gates 1-6) be seeded into Concept Registry's domain table now** (as documentation-that-becomes-seed-data, per that doc's pattern), or only when a `confluence` domain has real candidates? Leaning: add the row to the doc's Domains table now, build nothing.
4. **EIC-04's actual OOS verdict** — completion status says the machinery shipped; the gate verdict on the OOS window is the number that triggers everything downstream (F10, and intel-11's original trigger). If it hasn't been run against post-141.1 OOS-enforced data, that run precedes any of this.

## References

- `docs/ideas/intel-10-confluence-detection-persistence-layer.md`, `docs/ideas/intel-11-dual-system-discrete-vs-portfolio.md` — subjects
- `.planning/research/2026-07-02-v3-topdown-architecture.md` (D1-D4, D9, §2.2-2.5), `.planning/research/2026-07-02-v3-bottomup-audit.md` (§4.6 emission tier, §1.2 void-publishing live leg)
- `docs/ideas/intel-13-analog-engine.md` (Score Object deletion; return-distribution primitive; definedness rules), `docs/ideas/intel-15-measurement-engine.md` (unification status post-142A), `docs/ideas/intel-12-stratification-dimension.md`
- `docs/ideas/concept-governance-registries.md` (four-table MVP; intel-10 mapping rule; baseline shrinkage)
- `docs/ideas/edge-source-thesis.md` (T3, §P6 cross-sectional effective N)
- `docs/plans/2026-06-29-feature-scoring-beyond-ic.md` (§0b/0c — now gate-1 prerequisites)
- ROADMAP.md — Phase 142A status (complete 2026-07-02), Phases 145-147 (stale pre-intel-13 spec), 142B/SHADOW-REVIEW pattern
