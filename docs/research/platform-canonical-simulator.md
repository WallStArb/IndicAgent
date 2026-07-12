# Canonical Simulator — One Counterfactual Ledger, One Cost Kernel, One Run Identity

**Version:** 2.1
**Status:** draft — v1.0 (2026-07-01, "One Replay Engine") rewritten 2026-07-03 against the
shipped Phase 141.1/142A state and the 142B design; the engine proposal did not survive review,
the binding invariant did. v2.1 (2026-07-12) reconciles against the executed Phase 142B.
**Priority:** high (was critical) — the binding rule's main enforcement surface has now shipped:
Phase 142B (2026-07-10) built the frames ledger with provenance columns, and pre-commit Check 9
blocks new parallel claim/event/frame tables (verified live in `.git/hooks/pre-commit:403`).
This codebase has already had one real look-ahead incident (HMM full-history fit) and one
documented near-miss (rolling-correlation causality); the rule remains what stands between those
two and a third, but the remaining work is promotion + a triggered kernel build, not
infrastructure.
**Milestone:** the one build item (a cost kernel) is triggered by its second consumer, not
scheduled standalone — see below
**Last Updated:** 2026-07-12 (Fable re-review against executed Phase 142B)
**2026-07-12 note:** Phase 142B executed 2026-07-10 (SHADOW-REVIEW frozen `4fcdbca9`, migration
214 `9198be07`, review fixes `fa4208ef`, pushed `5024bb88`). Open Questions 2 and 3 are settled
— both in the direction this doc argued — and are marked so below. The seam table, cost-kernel,
and provenance sections are updated to shipped reality. One drift flagged (cost `reporting
column` landed via publisher-snapshot copy-through, not a kernel — see cost kernel section). As
of 2026-07-12 the ledger holds 11.81M frames (2.64M scored, backfill in progress). Caveat
inherited from Phase 143.1: `alpha_events` is 99.99% long-only (sign-asymmetric eligibility
gates, todo 094), so the frames ledger currently measures an effectively long-only book; any
SHADOW-REVIEW gate evaluation before todo 094 lands inherits that composition.
**Tags:** simulator, replay, point-in-time, look-ahead, validation, renaissance, cost-kernel,
alpha-frames, corpus-run

**Source:** `.planning/research/2026-07-03-canonical-simulator-fable-review.md` — Author: Fable 5
**Informed by:** Fable 5 — found the shared-replay-engine artifact was a second-system shell
(same species as intel-10 v2 and pre-rescope AnalogEngine); point-in-time correctness already
decomposes into three separately-owned seams, two shipped, one designed. Supersedes v1.0
(2026-07-01), archived at `docs/research/archive/canonical-simulator-v1-replay-engine.md`.

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
| **Frozen claim + outcome backfill** — a counterfactual result is frozen at emission time, scored only against later bars | `alpha_frames` (migrations 214+215) + `AlphaFrameWriter` + `CounterfactualTracker`: FRAME-01 freezes the claim off the emitted event; geometry fills at the T+1 bar open and the forward scan reads only bars *after* the frame opens (`services/counterfactual_tracker.py`) | **Shipped, Phase 142B (2026-07-10)** |

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
(`docs/foundation/principles.md`). It is not yet promoted to that file — the "after 142B"
precondition has now arrived, see Open Questions. It already governs in practice: the
decile-spread frame variant (`intel-15`'s Cross-Sectional Rank IC addendum) and the shadow
portfolio (`trade-construction-layer.md`) both route through `alpha_frames` as `frame_variant`s,
not a new ledger; pre-commit Check 9 enforces the no-new-tables clause mechanically; and
migration 214's provenance columns satisfy the corpus-run/weight-epoch clause on every row.

## The One Build Item: a Cost Kernel

Cost logic today lives at the emission-time hurdle in `alpha_publisher` (per-event, calibrated —
todo 030 closed in Phase 141.1). This doc's v2.0 predicted 142B's shadow-period reporting could
be the kernel's first consumer. **Drift, flagged plainly: 142B shipped the cost reporting
column without a kernel.** `alpha_frames.cost_r` is a copy-through of `alpha_events.cost_hurdle`
— the snapshot `alpha_publisher` stamps at publish time — combined in the pure function
`compute_expected_r_snapshot()` inside `services/alpha_frame_writer.py` (`net_expected_r =
gross_expected_r - cost_r`). No `src/intelligence/costs.py` exists. This is defensible, not a
violation: the copy-through means the frame consumes the *same* cost fact the publisher already
computed (one definition, frozen per-row, immune to later recalibration drift — migration 214's
`cost_r` column comment makes this explicit), rather than a second live derivation.

The kernel extraction is therefore still pending, and its trigger stands at the original count.
Remaining consumers needing a *fresh* cost computation (not a copy-through):

1. The decile-spread frame variant — cost-hurdle applied per leg.
2. Trade-construction's rebalance rule — trade only ranking changes that clear a per-trade cost
   floor.

This remains an `ic_math.py`-shaped extraction: a pure-function cost module
(`src/intelligence/costs.py` or a `statistics/` sibling), APR-fed from the calibrated
`alpha.quant.cost_hurdle.*` keys, zero I/O. **Build it when the first of these two arrives** —
not standalone, not now.

## Provenance

"Every claim ties to a CorpusManifest identity" is the Corpus Run concept (run_id threaded
through manifests and output tables), which Phase 141.1's weight-epoch fix partly delivered.
The `alpha_frames` requirement shipped: migration 214 (`9198be07`) added both `corpus_run_id`
(pinned once per `AlphaFrameWriter` invocation) and `weight_epoch` (copy-through of
`alpha_events.weight_version`), citing this doc's Open Question 3 in its header. Deliberately
no FK to `alpha_events` (review M1): the events hypertable is TRUNCATEd on every corpus
rebuild, so provenance is carried by these columns and the truncate script covers both tables.

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
biggest lever on IR (`docs/research/edge-source-thesis.md`, breadth section), but multiplying the
universe before the pipeline-to-P&L path is trusted multiplies unvalidated machinery, not
returns.

## Related Invariants Captured in Sibling Docs

- **One model, one book** — foundation invariant, `docs/foundation/principles.md`
- **Freeze the method, automate the cadence** — `docs/plans/methodology-change-ledger.md`
- **Breadth after proof** — `docs/research/edge-source-thesis.md`

## Open Questions

1. **Does the binding rule get promoted to `principles.md`?** Still open, but the v2.0 lean
   ("after 142B, once the ledger is proven") has had its precondition arrive: `alpha_frames`
   exists, is populated (11.81M frames as of 2026-07-12), and Check 9 enforces the no-new-tables
   clause mechanically. Promotion is now unblocked and should happen at the next
   `principles.md` touch; the rule is exactly what stops AnalogEngine-era backtesting ideas
   (e.g. todo 017's non-parametric hypothesis backtester) from growing their own counterfactual
   paths.
2. **SETTLED (Phase 142B, 2026-07-10) — gross, with a mandatory net reporting column.**
   `docs/plans/SHADOW-REVIEW.md` (frozen `4fcdbca9`, finalized `fa4208ef`) resolved this
   exactly as v2.0 recommended: D-01 evaluates all five gate criteria on GROSS
   `counterfactual_pnl_r` (gating on the unvalidated cost calibration would conflate "does the
   frame capture IC as P&L" with "is our cost estimate right"); D-02 mandates `net_expected_r`
   as a REPORTING-ONLY column alongside every gross metric, citing this doc's "gross reads
   optimistic" flag by name. Note the mechanism drift recorded in the cost kernel section:
   the reporting column consumes the publisher's per-event snapshot, not a new kernel.
3. **SETTLED (Phase 142B, 2026-07-10) — yes, both columns.** Migration 214 (`9198be07`) added
   `corpus_run_id` and `weight_epoch` to `alpha_frames` at the P1 migration, citing this doc's
   Open Question 3 in its deviation notes. See Provenance section for the copy-through
   semantics and the deliberate no-FK decision.

## References

- `.planning/research/2026-07-03-canonical-simulator-fable-review.md` — this rewrite's source review
- `.planning/research/2026-07-02-v3-topdown-architecture.md` §1.9 (the controlling sequencing
  call), §2.3 (kernel-not-monolith precedent)
- `.planning/research/2026-07-02-v3-bottomup-audit.md` §1.4 (OOS gap, since closed), §4.1/§5.3
  (Corpus Run), §4.6 (emission tier)
- `.planning/research/2026-07-03-intel10-11-fable-review.md` F5/F8 (frames as the one claim
  ledger; decile-spread as a frame variant), §5 R3 (one-model-one-book promotion pattern)
- `docs/research/intel-15-measurement-engine.md` — kernel-not-monolith precedent (`ic_math.py`);
  Cross-Sectional Rank IC addendum's per-leg cost need
- `docs/research/intel-13-analog-engine.md` — serialization law rule 2; analog point-in-time fully owned there
- `docs/research/trade-construction-layer.md` — shadow portfolio routed through the frames variant
- `docs/plans/2026-06-25-v30-alpha-lifecycle-schema.md` — two-instrument principle
- `.planning/todos/pending/030-cost-hurdle-apr-calibration.md` — closed, Phase 141.1; the
  calibrated inputs the cost kernel will consume
- `src/observability/corpus_manifest.py` — provenance identity
- `services/ic_engine.py` :39-44, :854, :1700 — training-window/OOS clamp as shipped (141.1)
- ROADMAP.md — Phase 142B spec (FRAME-01..04, SHADOW-REVIEW pre-commitment)
- `docs/plans/SHADOW-REVIEW.md` — frozen Phase 147 promotion criteria (D-01 gross gate, D-02
  net reporting column) — settles Open Question 2
- `production/migrations/214_alpha_frames_schema.sql` — shipped frames DDL + provenance columns
  — settles Open Question 3
- `services/alpha_frame_writer.py` / `services/counterfactual_tracker.py` — the shipped ledger
  writers (Phase 142B, commits `9198be07`/`fa4208ef`/`059d4a75`)
