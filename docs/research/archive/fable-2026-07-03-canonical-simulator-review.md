# canonical-simulator Review — The Invariant Is Right, the Engine Is a Shell

**Date:** 2026-07-03 · **Author:** Fable 5 (dispatched via Claude Code Agent tool) · **Type:** research/review, read-only
**Scope:** `docs/research/canonical-simulator.md` (v1.0, 2026-07-01), assessed against the 2026-07-02 topdown/bottomup reviews, the intel-13/15 docs, the intel-10/11 review, Phase 141.1/142A as shipped, and the actual 142B spec in ROADMAP.md. The target doc predates the whole review cycle and was written one day before the topdown review answered its central question in one line.
**Verdict up front:** the doc's *invariants* (one executable-return + cost definition, provenance on every counterfactual claim, look-ahead discipline enforced structurally) are correct and worth binding. Its *artifact* — one shared point-in-time replay engine with a state-reconstruction API that every validation client calls — is a second-system shell of the same species as intel-10's parallel event system and pre-rescope AnalogEngine's parallel measurement stack. Nothing in the current system iterates bar-by-bar needing "what was knowable at T" reconstructed generically; point-in-time correctness lives at three specific seams, two of which are already enforced in shipped code and the third of which is 142B's existing design. The topdown review (§1.9) already made the sequencing call the doc's own incremental path contradicts: "Phase 142B is the seed of the canonical simulator — name it that and let it grow, but **don't generalize early**. Keep 142B as planned." The doc should be rewritten as a short binding invariant ("one counterfactual ledger, one cost kernel, one run identity — no client builds its own replay path") rather than an engine proposal; sketch in §5.

---

## 1. Findings

### F1. The premise "each client re-implements replay history without cheating" mischaracterizes what the clients actually do — none of them is a replay engine, and none needs a state-reconstruction API. [HIGH]

The system's validation machinery is not bar-by-bar event-driven replay anywhere. It is batch corpus runs over immutable facts, and point-in-time correctness decomposes into exactly three seams, each with a specific owner:

| Seam | What enforces it | Status |
|---|---|---|
| **Causal construction** — features, labels, embeddings computed only from data ≤ T | Per-producer laws: feature factory's causal transforms; `_causal_decode` forward-filter in `regime_writer`; causal expanding rank in `equity_regime_model` (fixed per todo 026 P1a); intel-13's embedding serialization law rule 2 ("point-in-time only, provably") | Enforced per producer; a generic engine cannot enforce this — causality is a property of how each fact is *computed*, not of how it is *read back* |
| **Frozen evaluation window** — IC/weights/events computed only through a pre-committed boundary | `training_window_end` threaded through every `ic_engine.py` query (verified: `fv.bar_ts <= %(training_window_end)s` at :854, :1175, PK component at :171-205), now clamped by `LEAST(MAX(bar_ts), alpha.validation.oos_start)` (ic_engine.py:39-44, :1700 — Phase 141.1 closed the bottomup audit's #1 rigor gap) | **Shipped, 141.1** |
| **Frozen claim + outcome backfill** — a counterfactual result is a claim frozen at emission time, scored against only-later bars | 142B's `alpha_frames` design: FRAME-01 freezes geometry off the emitted event, FRAME-02's forward scan reads only bars *after* the frame opens — structurally incapable of look-ahead in the direction that matters | Planned (142B), design correct as specced |

The doc's API sketch — "at simulated bar T a client can see bars ≤ T, features from data ≤ T, regime labels from causal decode ≤ T, weights from the last refresh before T" — describes a read surface no planned client consumes. `ic_engine` runs set-based windowed queries, not a bar cursor. FRAME-02 needs only *future* bars relative to an already-frozen claim. The shadow portfolio (trade-construction-layer.md) says of itself: "shadow measurement is queries and a batch service, not new infrastructure." The "weights from the last refresh before T" clause is real but already fixed at the fact layer: 141.1's weight-epoch fix plus the Corpus Run identity give weights a vintage; consumers join on it. Building an engine to *mediate reads* cannot prevent the actual historical look-ahead bugs cited (HMM full-history fit, rolling-correlation causality) — both were construction-time bugs in how a fact was computed, upstream of any conceivable replay API.

### F2. The doc's factual claims, re-verified: mostly accurate, two now stale. [MEDIUM]

- **"ic_engine's training-window-end discipline"** — accurate, and *more* true now than when written: at authorship (07-01) the OOS clamp did not exist (bottomup §1.4: `alpha.validation.oos_start` had zero readers); 141.1 (07-02) implemented it. The doc got lucky — its claim describes the post-141.1 state.
- **"Phase 142B will build frame simulation"** — still accurate; 142B is 📋 PLANNED, not built. But the in-flight phase is 142B.**1** (ensemble weighting, inserted, explicitly independent of frames). "Incremental path starts inside Phase 142B" remains temporally valid but the instruction "scope the core when 142B is planned, as part of it" directly contradicts topdown §1.9's keep-142B-as-planned / don't-generalize-early, which postdates it and was made with the 142B spec in view. Injecting a "small shared replay core" into 142B planning is exactly the early generalization §1.9 forbids.
- **"todo 030's calibration" as future cost-model input** — stale: todo 030 closed in 141.1 (cost-hurdle calibration done; `alpha.quant.cost_hurdle.*` no longer 0.0 no-ops). The cost inputs exist now; what doesn't exist is a shared consumer (see F4).
- **"the trade-construction doc proposes its own shadow portfolio measurement"** — was true on 07-01; partially cured since. trade-construction-layer.md now (07-03 note) gates itself on intel-15's cross-sectional falsification addendum, whose deliverable #2 is explicitly "`alpha_frames` with a portfolio-shaped frame variant, **not a new system**" (intel-11 review F8.2). The drift the doc feared is being resolved doc-by-doc in the direction of frames-as-the-one-ledger — i.e., toward the invariant, without the engine.
- **"AnalogEngine needs point-in-time retrieval"** — true, and intel-13 already owns it fully: serialization law rule 2, the versioned embedding contract, definedness rules, and forward-return joins to the canonical table. Nothing is left for a shared engine to supply; retrieval-for-measurement rides `ic_engine.py` at feature grain (intel-15's grain analysis). intel-13 does not cite canonical-simulator.md and needs nothing from it.

### F3. This is the second-system-shell pattern, with the same resolution as intel-10/13 — and the shell already has a live counterexample proving the alternative works. [HIGH]

The intel-15 story is the controlling precedent: D1 proposed one unified MeasurementEngine; what actually shipped was a shared *kernel* (`ic_math.py`) extracted organically during cleanup, consumed by three callers, with tables and services left separate under named revisit triggers — and intel-15 concluded that fallback captured most of D1's value. The simulator question has the identical shape. The durable shared assets here are: the executable-return definition (already sole return type in `forward_returns`, verified 10.08M rows), the frozen-window clamp (one place, the corpus orchestrator + ic_engine), the frames ledger (one table, extensible by `frame_variant`), and — the one genuinely unbuilt piece — a cost function. "One engine everything calls" adds an ownership layer, a client-migration program (`ic_engine` migrating "last, if ever" is the doc conceding the flagship client never needs it), and an API whose contract ("nothing else, enforced by the engine's API") it cannot actually honor per F1. Musk step 2 applies: delete the engine, keep the contract.

### F4. The genuinely missing shared piece is a cost kernel, not a simulator — and it has a concrete near-term forcing function. [MEDIUM]

Cost logic today: the emission-time hurdle in `alpha_publisher` (per-event, now calibrated). Coming consumers with *different* application shapes: 142B frames (ROADMAP explicitly defers a cost model to v4.0 — defensible for the binary FRAME-04 gate, but SHADOW-REVIEW's Sharpe/drawdown criteria on gross P&L are optimistic by construction), the decile-spread frame variant ("cost-hurdle applied per leg" — intel-15 addendum), and trade-construction's rebalance rule ("trade only ranking changes that clear a per-trade cost floor"). Three consumers, one definition of "what does a round trip cost at this tf/spread regime." That is precisely an `ic_math.py`-shaped extraction: a pure-function cost module (`src/intelligence/costs.py` or a `statistics/` sibling), APR-fed from the todo-030-calibrated keys, zero I/O — built when the *second* consumer arrives (the decile-spread variant or 142B's shadow-period reporting, whichever lands first). This is the doc's "cost model applied uniformly" bullet, correctly scoped; it survives the rewrite as the only new code the doc actually implies.

### F5. Provenance is already an owned concept — the doc's bullet should point at it, not restate it. [LOW]

"Every simulation run ties to a CorpusManifest identity" is the Corpus Run concept (bottomup §4.1/§5.3): run_id threaded through manifests and output tables. 141.1's weight-epoch fix delivered part of it; the rest is tracked there. The rewrite keeps one sentence: counterfactual results (frames rows, gate verdicts) must carry the corpus-run/weight-epoch identity of the machinery that produced them — which is a column-and-join requirement on `alpha_frames`, worth stating as a 142B planning note, not an engine property.

### F6. The Renaissance framing itself deserves one honest correction. [LOW]

Renaissance's simulator arbitrated *portfolio-level* claims for a firm running live execution across thousands of instruments — order-book effects, capacity, market impact. At this project's scale and stage (no fills, 58 ETFs, pre-Gate-1), the doc itself concedes the right scope: "a disciplined data-access layer plus a cost model." Taken at its own word, that is not an engine; it is (a) the fact-layer discipline that exists, (b) the frames ledger that is planned, (c) the cost kernel of F4. The "What It Is Not" section was more right than the "What It Is" section; the rewrite should let it win.

---

## 2. What's Solid (keep verbatim in any rewrite)

- **The core insight paragraph** — one arbiter, a look-ahead bug fixed once is fixed everywhere, results comparable because same code path. True; the rewrite re-grounds it in the kernel/ledger decomposition rather than an engine.
- **The incident evidence** (HMM full-history fit; rolling-correlation near-miss) — real, and the correct justification for *structural* enforcement over per-client discipline. The structural enforcement just lives at construction seams (F1), not a read API.
- **"Extract, don't invent" and "second client tests the abstraction"** — exactly right method; already vindicated by `ic_math.py`. Apply it to frames (second client = decile-spread variant) and costs (second consumer triggers extraction).
- **"ic_engine migrates last, if ever"** — correct instinct that undercuts the engine framing; keep it as evidence for the rewrite's conclusion.
- **The sequencing decision record** (end-to-end system → breadth only after proof) — operator decision, orthogonal to the engine question, preserve as-is.
- **The sibling-invariant cross-references** (one-model-one-book now in principles.md; methodology-change-ledger; breadth-after-proof) — all still correct.

## 3. Direct Corrections

1. "Phase 142B's frame simulator is the natural first client built on a small shared replay core... scope the core when 142B is planned, as part of it" → contradicts topdown §1.9 (keep 142B as planned, don't generalize early); 142B builds `alpha_frames` exactly as specced, and the "core" is whatever survives contact with the second frame variant (F3).
2. "spread/slippage from todo 030's calibration" → todo 030 is closed (141.1); the calibrated `alpha.quant.cost_hurdle.*` keys exist; the missing piece is the shared cost function, not the calibration (F4).
3. "the trade-construction doc proposes its own shadow portfolio measurement" → superseded by that doc's 07-03 note and intel-15's addendum: the shadow portfolio is an `alpha_frames` variant + queries, already routed through the one ledger (F2).
4. "AnalogEngine needs point-in-time retrieval" as an unowned requirement → intel-13 owns it in full (serialization law, versioned contract, canonical forward_returns join); no residual demand on this doc (F2).
5. "ic_engine's training-window-end discipline" → cite 141.1's OOS clamp explicitly; the discipline is now code-enforced, not orchestration convention (F2).
6. "Phase 152 (deferred beneficiary)" in References → verify against current ROADMAP numbering when rewritten; the v3.2+ phase text is already known-stale in other respects (intel-10/11 review F2).

## 4. Assessment Against the Task's Direct Questions

- **Is "one shared replay engine" still the right frame post-142A/intel-13/15?** No. The frame decomposes into: causal-construction laws (per producer, existing), the frozen-window clamp (shipped, 141.1), one counterfactual ledger with variants (142B + F8.2), one cost kernel (F4, unbuilt, triggered), one run identity (Corpus Run). Each piece is separately owned; the engine adds no enforcement any piece lacks.
- **Does it overlap/conflict with intel-15 or the emission/frames architecture?** It overlaps in method (kernel-not-monolith is intel-15's whole conclusion) and conflicts in sequencing (its 142B instruction vs topdown §1.9). It does not conflict with intel-14 (whose E2B consumes `alpha_frames` — a fourth reason the frames ledger, not a new engine, is the convergence point).
- **Is the incremental build path still accurate?** Direction yes (142B first), mechanism no (no "replay core" gets scoped into 142B; 142B ships as planned and the shared surface emerges via extraction).
- **Real gap or redundant?** One real gap (cost kernel, F4) and one real invariant worth binding (F1's client rule). The rest is redundant with shipped or designed machinery.

## 5. Recommended Rewrite (concrete, single round-trip)

Replace `docs/research/canonical-simulator.md` with a short doc (~half current length), retitled **"canonical-simulator: One Counterfactual Ledger, One Cost Kernel, One Run Identity"** (keep the filename for link stability; add a supersession note). Structure:

- **The insight, kept:** Renaissance's simulator lesson = every claim about the past through one arbiter. At this system's scale the arbiter is not an engine; it is three shared facts plus one binding rule.
- **The binding rule (the doc's real payload, stated as an invariant in the one-model-one-book style):** *No validation client builds its own replay or counterfactual path. Counterfactual P&L claims are `alpha_frames` rows (new shapes are `frame_variant`s, never new tables/services); return definitions are Invariant 1; costs come from the shared cost kernel once it exists; every claim carries corpus-run/weight-epoch provenance. Point-in-time correctness is enforced where facts are constructed (causal laws) and where windows are frozen (the 141.1 clamp), never re-derived per client.* Candidate for `docs/foundation/principles.md` promotion after 142B proves the ledger with two variants — same staging as one-model-one-book.
- **The map (one table):** the three seams of F1 with their owners and status — so a future proposer can see the discipline is already placed and where a new client plugs in.
- **The one build item:** the cost kernel (F4) — pure functions, APR-fed from the calibrated `alpha.quant.cost_hurdle.*` inputs, extraction triggered by the second consumer (decile-spread variant or 142B shadow-period net reporting). Explicitly *not* scheduled standalone.
- **What is deleted from v1.0:** the point-in-time state-reconstruction API, the client-migration program, "scope the core inside 142B." One paragraph recording why (F1/F3, topdown §1.9), so the idea doesn't get re-proposed cold.
- **Kept verbatim:** the incident evidence, the operator sequencing decision (breadth after proof), the sibling-invariant references.

## 6. Open Questions (operator)

1. **Does the binding rule go to `principles.md` now or after 142B?** Leaning after: unlike one-model-one-book (which constrains proposals being written this month), the frames ledger doesn't exist yet; binding clients to an unbuilt table is weaker than binding them to a proven one. But if 145-147 planning starts before 142B executes, promote early — the rule is what stops AnalogEngine-era backtesting ideas (e.g. todo 017's non-parametric hypothesis backtester) from growing their own counterfactual paths.
2. **142B shadow-period reporting: gross or net?** SHADOW-REVIEW's Sharpe/drawdown criteria on gross counterfactual P&L will read optimistic given 98.3% of events sit in the band todo 030 found cost-marginal. The cost keys are calibrated now; applying them as a *reporting column* (not a gate change — the pre-commitment stands) during 142B is cheap and would make the F4 kernel's first consumer arrive inside 142B itself. Needs a call before SHADOW-REVIEW.md is committed, since criteria are frozen at launch.
3. **Does `alpha_frames` get a `corpus_run_id`/`weight_epoch` column at 142B P1 migration time?** F5 says yes; costs one column now vs a provenance hole forever. Should be raised at 142B planning.

## References

- `docs/research/canonical-simulator.md` — subject
- `.planning/research/2026-07-02-v3-topdown-architecture.md` §1.9 (the controlling sequencing call), §2.3 (kernel precedent)
- `.planning/research/2026-07-02-v3-bottomup-audit.md` §1.4 (OOS gap, since closed), §4.1/§5.3 (Corpus Run), §4.6 (emission tier)
- `.planning/research/2026-07-03-intel10-11-fable-review.md` F5/F8 (frames as the one claim ledger; decile-spread as a frame variant), §5 R3 (one-model-one-book promotion pattern)
- `docs/research/intel-15-measurement-engine.md` — the kernel-not-monolith precedent (`ic_math.py`) and the cross-sectional addendum's per-leg cost need
- `docs/research/intel-13-analog-engine.md` — serialization law rule 2; canonical forward_returns join (analog point-in-time fully owned there)
- `docs/research/trade-construction-layer.md` — 07-03 note routing the shadow portfolio through the frames variant
- `services/ic_engine.py` :39-44, :854, :1700 — training-window/OOS clamp as shipped (141.1)
- `.planning/ROADMAP.md` — Phase 142B spec (FRAME-01..04, SHADOW-REVIEW pre-commitment, no-cost-model note); Phase 141.1 completion (OOS enforcement, weight-epoch, cost-hurdle calibration / todo 030 closed)
