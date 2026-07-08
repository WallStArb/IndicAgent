> **ARCHIVED 2026-07-03.** Superseded by `docs/research/canonical-simulator.md` v2.0, rewritten per
> `.planning/research/2026-07-03-canonical-simulator-fable-review.md`. Kept for historical
> reference only — do not build against this version. The doc's core insight (one arbiter for
> every claim about the past) survived into v2; what didn't survive is the artifact — a shared
> point-in-time state-reconstruction engine no planned client actually needs. Point-in-time
> correctness decomposes into three seams already separately owned (causal-construction laws,
> the 141.1 OOS clamp, and 142B's `alpha_frames` frozen-claim design); the review found this is
> the same second-system-shell pattern as intel-10 v2 and pre-rescope AnalogEngine.

# Canonical Simulator — One Replay Engine, Everything Else a Client

**Version:** 1.0
**Status:** draft — captured from 2026-07-01 Simons-lens review; named the highest-leverage
infrastructure investment in the tree
**Priority:** high — this is what the end-to-end system build feeds (operator decision
2026-07-01: universe expansion deferred until the end-to-end system works, and the end-to-end
system's validation spine is this)
**Milestone:** future — incremental path starts inside Phase 142B rather than as a separate build
**Last Updated:** 2026-07-01
**Tags:** simulator, replay, point-in-time, look-ahead, validation, renaissance, infrastructure

---

## The Insight

Renaissance's most guarded asset was reportedly not a signal — it was the simulator: one
point-in-time-correct, cost-aware replay engine that arbitrated *every* claim the firm made
about the past. Features, weights, execution rules, portfolios — all validated through the same
code path, so a look-ahead bug fixed once was fixed everywhere, and two results were always
comparable because they came from the same arbiter.

This project is drifting toward the opposite: validation logic scattered across independent
implementations — `ic_engine` replays history for feature IC, Phase 142B will build frame
simulation, the trade-construction doc proposes its own shadow portfolio measurement, AnalogEngine
needs point-in-time retrieval. Each is a separate re-implementation of the same hard problem:
**"replay history without cheating."** Each is an independent chance for a look-ahead bug — and
this codebase has already had one real look-ahead incident (HMM full-history fit) plus one
documented near-miss (rolling correlation causality, caught in interaction-factory review).

## What It Is

One engine with one contract:

- **Point-in-time state reconstruction:** at simulated bar T, a client can see exactly what was
  knowable at T — bars ≤ T, features computed from data ≤ T, regime labels from causal decode
  ≤ T, IC/weights from the last refresh *before* T, analog neighbors whose outcomes resolved
  before T. Nothing else, enforced by the engine's API rather than by every client's discipline.
- **Cost model applied uniformly:** executable-returns definition (Invariant 1), spread/slippage
  from todo 030's calibration, applied identically whether the client is measuring a feature,
  a frame, or a portfolio.
- **Clients, not forks:** ic_engine's forward-return join, 142B's frame simulation, the
  portfolio shadow book, AnalogEngine's retrieval validation — all call the engine; none
  re-implement replay.
- **Provenance built in:** every simulation run ties to a CorpusManifest identity, same as
  `concept_eval_run.corpus_build_ref` — a result is reproducible or it doesn't count.

## What It Is Not

Not an event-driven backtester with order-book emulation, not a GUI product, not a rewrite of
the live pipeline. At this project's scale it is a disciplined data-access layer plus a cost
model — the value is the single enforced contract, not simulation sophistication.

## Incremental Path (do not build big-bang)

1. **Extract, don't invent:** the point-in-time access patterns already exist in fragments —
   ic_engine's training-window-end discipline, forward_returns' executable definition, the
   OOS boundary. Phase 142B's frame simulator is the natural first *client built on* a small
   shared replay core, rather than another standalone implementation. Scope the core when 142B
   is planned, as part of it.
2. **Second client migrates in:** the trade-construction shadow portfolio (PortfolioTrack v1)
   uses the same core — this is the test that the abstraction is right (two clients with
   different grain: per-frame vs per-book).
3. **ic_engine migrates last, if ever:** it works today; migration is justified only when a
   shared-core change would otherwise have to be duplicated into it.

## Sequencing Decision (operator, 2026-07-01)

End-to-end system first → this simulator grows inside that build (142B onward) → **universe
expansion (breadth) only after the end-to-end system is proven.** Breadth is the biggest lever
on IR (see `docs/research/edge-source-thesis.md`, breadth section), but multiplying the universe
before the pipeline-to-P&L path is trusted multiplies unvalidated machinery, not returns. The
simulator is what makes "proven" meaningful: one arbiter, every claim through it.

## Related Invariants Captured in Sibling Docs

- **One model, one book** — now a foundation invariant, `docs/foundation/principles.md`
  (promoted 2026-07-03 from `docs/research/archive/intel-11-dual-system-discrete-vs-portfolio.md`)
- **Freeze the method, automate the cadence** — `docs/plans/methodology-change-ledger.md`
- **Breadth after proof** — `docs/research/edge-source-thesis.md`

## References

- ROADMAP.md Phase 142B (first client), Phase 152 (deferred beneficiary)
- `docs/plans/2026-06-25-v30-alpha-lifecycle-schema.md` — two-instrument principle this engine
  physically enforces (one replay, two measurements)
- `.planning/todos/pending/030-cost-hurdle-apr-calibration.md` — cost model inputs
- `src/observability/corpus_manifest.py` — provenance identity
