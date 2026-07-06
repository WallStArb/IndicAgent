# Canonical Simulator — One Counterfactual Ledger, One Cost Kernel, One Run Identity

**Version:** 2.0
**Status:** draft — v1.0 (2026-07-01, "One Replay Engine") rewritten 2026-07-03 against the
shipped Phase 141.1/142A state and the 142B design; the engine proposal did not survive review,
the binding invariant did
**Priority:** critical — this is still the highest-leverage infrastructure investment in the
tree; the rewrite changed the mechanism, not the stakes. This codebase has already had one real
look-ahead incident (HMM full-history fit) and one documented near-miss (rolling-correlation
causality). The binding rule below is what stands between those two and a third — now with
automated enforcement (pre-commit Check 9 blocks new parallel claim/event/frame tables), which
makes it cheaper to hold the line than v1's engine would have been, not less urgent to hold.
**Milestone:** the one build item (a cost kernel) is triggered by its second consumer, not
scheduled standalone — see below
**Last Updated:** 2026-07-03
**Tags:** simulator, replay, point-in-time, look-ahead, validation, renaissance, cost-kernel,
alpha-frames, corpus-run

**Source:** `.planning/research/2026-07-03-canonical-simulator-fable-review.md` — Author: Fable 5
**Informed by:** Fable 5 — found the shared-replay-engine artifact was a second-system shell
(same species as intel-10 v2 and pre-rescope AnalogEngine); point-in-time correctness already
decomposes into three separately-owned seams, two shipped, one designed. Supersedes v1.0
(2026-07-01), archived at `docs/ideas/archive/canonical-simulator-v1-replay-engine.md`.

---

## The Insight, Kept

Renaissance's simulator lesson: every claim the firm made about the past went through one
arbiter, so a look-ahead bug fixed once was fixed everywhere, and results were always comparable
because they came from the same code path. That lesson is correct and worth binding into this
codebase. What changed in this rewrite is the mechanism — at this system's scale, the arbiter is
not an engine. It is three shared facts plus one binding rule.

## The Map: Point-in-Time Correctness Already Has Three Owners

| Seam | What enforces it | Status |
|---|---|---|
| **Causal construction** — features, labels, embeddings computed only from data ≤ T | Per-producer laws: Feature Factory's causal transforms; `_causal_decode` forward-filter in `regime_writer`; causal expanding rank in `equity_regime_model`; `intel-13`'s embedding serialization law (point-in-time only, provably) | Enforced per producer — this is a property of how a fact is *computed*, and a generic read API cannot substitute for it |
| **Frozen evaluation window** — IC/weights/events computed only through a pre-committed boundary | `training_window_end` threaded through every `ic_engine.py` query, now clamped by `LEAST(MAX(bar_ts), alpha.validation.oos_start)` (`ic_engine.py:39-44, :1700`) | **Shipped, Phase 141.1** |
| **Frozen claim + outcome backfill** — a counterfactual result is frozen at emission time, scored only against later bars | Phase 142B's `alpha_frames` design: FRAME-01 freezes geometry off the emitted event; FRAME-02's forward scan reads only bars *after* the frame opens | Planned (142B), design already correct |

No client in the system iterates bar-by-bar needing "what was knowable at T" reconstructed
generically. `ic_engine` runs set-based windowed queries. FRAME-02 needs only future bars
relative to an already-frozen claim. The two look-ahead incidents that motivate this doc (HMM
full-history fit; rolling-correlation near-miss) were both construction-time bugs in how a fact
was computed — upstream of any conceivable replay API, and not preventable by one.

## The Binding Rule

*No validation client builds its own replay or counterfactual path. Counterfactual P&L claims
are `alpha_frames` rows — new shapes are `frame_variant`s, never new tables or services. Return
definitions are Invariant 1 (`executable_open_to_open`), never theoretical. Costs come from the
shared cost kernel once it exists (below). Every claim carries corpus-run/weight-epoch
provenance. Point-in-time correctness is enforced where facts are constructed (causal laws) and
where windows are frozen (the 141.1 clamp) — never re-derived per client.*

This is this doc's real payload, in the same style as `one model, one book`
(`docs/foundation/principles.md`). It is not yet promoted to that file — see Open Questions for
when. It already governs how new proposals should be read: the decile-spread frame variant
(`intel-15`'s Cross-Sectional Rank IC addendum) and the shadow portfolio
(`trade-construction-layer.md`) both route through `alpha_frames`, not a new ledger — this is the
rule already working, not a future aspiration.

## The One Build Item: a Cost Kernel

Cost logic today lives at the emission-time hurdle in `alpha_publisher` (per-event, calibrated —
todo 030 closed in Phase 141.1). Three coming consumers need the *same* definition of "what does
a round trip cost at this tf/spread regime," applied differently:

1. Phase 142B's frames (currently no cost model — a defensible gap for the binary FRAME-04 gate,
   but SHADOW-REVIEW's Sharpe/drawdown criteria on gross P&L will read optimistic; see Open
   Questions).
2. The decile-spread frame variant — cost-hurdle applied per leg.
3. Trade-construction's rebalance rule — trade only ranking changes that clear a per-trade cost
   floor.

This is an `ic_math.py`-shaped extraction: a pure-function cost module (`src/intelligence/costs.py`
or a `statistics/` sibling), APR-fed from the calibrated `alpha.quant.cost_hurdle.*` keys, zero
I/O. **Build it when the second consumer arrives** (the decile-spread variant or 142B's
shadow-period reporting, whichever lands first) — not standalone, not now.

## Provenance

"Every claim ties to a CorpusManifest identity" is the Corpus Run concept (run_id threaded
through manifests and output tables), which Phase 141.1's weight-epoch fix partly delivered. The
remaining requirement: `alpha_frames` should carry a `corpus_run_id`/`weight_epoch` column at its
142B P1 migration — cheap now, a provenance hole forever if skipped (see Open Questions).

## What Is Deleted From v1.0, and Why

v1.0 proposed a point-in-time state-reconstruction API, a client-migration program (ic_engine
migrating "last, if ever" — itself the tell that the flagship client never needed it), and
scoping a "shared replay core" inside Phase 142B planning. That last instruction directly
contradicted the 2026-07-02 topdown architecture review's explicit sequencing call: keep 142B as
planned, don't generalize early. All three are deleted. The engine added an ownership layer and
an API contract it could not actually honor (F1 of the source review); the binding rule above
captures everything the engine was trying to guarantee, without building it.

## Sequencing Decision (operator, 2026-07-01, unchanged)

End-to-end system first → the ledger/kernel/identity above grow inside that build (142B onward)
→ **universe expansion (breadth) only after the end-to-end system is proven.** Breadth is the
biggest lever on IR (`docs/ideas/edge-source-thesis.md`, breadth section), but multiplying the
universe before the pipeline-to-P&L path is trusted multiplies unvalidated machinery, not
returns.

## Related Invariants Captured in Sibling Docs

- **One model, one book** — foundation invariant, `docs/foundation/principles.md`
- **Freeze the method, automate the cadence** — `docs/plans/methodology-change-ledger.md`
- **Breadth after proof** — `docs/ideas/edge-source-thesis.md`

## Open Questions

1. **Does the binding rule get promoted to `principles.md` now, or after 142B?** Leaning after:
   unlike one-model-one-book (which constrains proposals being written this month), the frames
   ledger doesn't exist yet — binding clients to an unbuilt table is weaker than binding them to
   a proven one. Promote early instead if Phase 145-147 planning starts before 142B executes; the
   rule is exactly what stops AnalogEngine-era backtesting ideas (e.g. todo 017's non-parametric
   hypothesis backtester) from growing their own counterfactual paths.
2. **142B shadow-period reporting: gross or net of cost?** SHADOW-REVIEW's Sharpe/drawdown
   criteria on gross counterfactual P&L will read optimistic given most events sit in the
   cost-marginal band todo 030's calibration found. Applying the calibrated cost keys as a
   *reporting column* (not a gate change — the pre-commitment stands) during 142B is cheap and
   would make the cost kernel's first consumer arrive inside 142B itself. Needs a call before
   SHADOW-REVIEW.md is committed, since criteria are frozen at launch.
3. **Does `alpha_frames` get a `corpus_run_id`/`weight_epoch` column at 142B's P1 migration?**
   Costs one column now vs. a provenance hole forever. Should be raised at 142B planning.

## References

- `.planning/research/2026-07-03-canonical-simulator-fable-review.md` — this rewrite's source review
- `.planning/research/2026-07-02-v3-topdown-architecture.md` §1.9 (the controlling sequencing
  call), §2.3 (kernel-not-monolith precedent)
- `.planning/research/2026-07-02-v3-bottomup-audit.md` §1.4 (OOS gap, since closed), §4.1/§5.3
  (Corpus Run), §4.6 (emission tier)
- `.planning/research/2026-07-03-intel10-11-fable-review.md` F5/F8 (frames as the one claim
  ledger; decile-spread as a frame variant), §5 R3 (one-model-one-book promotion pattern)
- `docs/ideas/intel-15-measurement-engine.md` — kernel-not-monolith precedent (`ic_math.py`);
  Cross-Sectional Rank IC addendum's per-leg cost need
- `docs/ideas/intel-13-analog-engine.md` — serialization law rule 2; analog point-in-time fully owned there
- `docs/ideas/trade-construction-layer.md` — shadow portfolio routed through the frames variant
- `docs/plans/2026-06-25-v30-alpha-lifecycle-schema.md` — two-instrument principle
- `.planning/todos/pending/030-cost-hurdle-apr-calibration.md` — closed, Phase 141.1; the
  calibrated inputs the cost kernel will consume
- `src/observability/corpus_manifest.py` — provenance identity
- `services/ic_engine.py` :39-44, :854, :1700 — training-window/OOS clamp as shipped (141.1)
- ROADMAP.md — Phase 142B spec (FRAME-01..04, SHADOW-REVIEW pre-commitment)
