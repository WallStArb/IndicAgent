# Phase 142B: Frame Simulation + Counterfactual Tracking - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-07-09
**Phase:** 142B-Frame Simulation + Counterfactual Tracking
**Areas discussed:** Cost basis, State machine, Initial scale, IC cadence

---

## Cost basis (SHADOW-REVIEW.md gross vs. net-of-cost)

| Option | Description | Selected |
|--------|-------------|----------|
| Gross gate + net reporting column | Pass/fail stays on gross `counterfactual_pnl_r`; `net_expected_r` added as a mandatory reporting column alongside it | ✓ |
| Gross only | Ship SHADOW-REVIEW.md exactly as ROADMAP's drafted criteria, no cost column | |
| Net-of-cost is the actual gate | Compute Sharpe/drawdown/mean-pnl thresholds on net P&L directly | |

**User's choice:** Delegated to Claude — "design this like Renaissance would... how would a
senior engineer/quant at Renaissance think about this."
**Notes:** Claude selected "Gross gate + net reporting column" (originally the recommended
option). Rationale: gating on the not-yet-fill-validated `alpha.quant.cost_hurdle.*` estimate
would conflate frame-quality measurement with cost-calibration uncertainty — the same
non-conflation principle that motivated splitting 142A (signal) from 142B (frame). Reporting net
alongside gross closes canonical-simulator.md's flagged optimism gap without injecting that
uncertainty into a binary go/no-go decision. Captured as D-01/D-02/D-03 in CONTEXT.md.

---

## State machine (`closed_reversal` vs. `closed_ic_decay`)

| Option | Description | Selected |
|--------|-------------|----------|
| Follow ROADMAP (drop closed_reversal, add closed_ic_decay) | CHECK constraint: open, closed_stop, closed_target, closed_max_hold, closed_ic_decay | ✓ |
| Support both states | CHECK constraint allows all 5; closed_reversal reserved but never triggered | |

**User's choice:** Delegated to Claude — same Renaissance-rigor framing.
**Notes:** Claude selected "Follow ROADMAP." Rationale: shipping a CHECK constraint for a state
the code will never emit is dead schema surface that lies about what the system does — the exact
kind of latent drift this codebase's principles explicitly guard against. ROADMAP's FRAME-02/03
text (2026-07-03) is later and gives an explicit, reasoned rationale (bar-level reversal is
noise, destroys returns via turnover) that the 2026-06-25 schema doc's literal DDL does not
account for. Captured as D-04 in CONTEXT.md — the schema doc is superseded on this specific
point only, nothing else in it changes.

---

## Initial scale (12.26M existing `alpha_events`)

| Option | Description | Selected |
|--------|-------------|----------|
| Chunked backfill pass over full history | `--backfill` mode processes the full existing backlog in chunks on first run; nightly cadence takes over after | ✓ |
| Nightly-only accretion from launch | No special backfill; N accrues gradually from launch, could take weeks/months per cell | |

**User's choice:** "1 seems right" (chunked backfill), with the same Renaissance-rigor framing.
**Notes:** Directly confirmed by user, not delegated. Captured as D-05/D-06/D-07 in CONTEXT.md.

---

## IC cadence (weekly IC-decay trigger dependency)

| Option | Description | Selected |
|--------|-------------|----------|
| CounterfactualTracker reads "most recent" regardless of staleness | No new timer work in 142B; scheduling tracked separately | ✓ |
| 142B also sets up the recurring EnsembleICEngine schedule | Add a systemd timer as part of this phase | |

**User's choice:** Delegated to Claude — same Renaissance-rigor framing.
**Notes:** Claude selected "reads most recent, no timer in scope" but added an explicit
observability requirement (D-10: instrument the age of the row consumed) rather than accepting
pure silence on staleness. Rationale: bundling timer provisioning into 142B blurs the 142A/142B
measurement-instrument boundary and expands past ROADMAP's stated 2-plan scope; per the
project's "automate what's proven, instrument everything" principles, the correct middle path is
scope discipline (no timer) plus visibility (log/metric on staleness) rather than either silent
staleness or premature automation. A stale read degrades gracefully — the early exit just fires
late, frames still close correctly via stop/target/max_hold. Captured as D-08/D-09/D-10 in
CONTEXT.md, with a follow-on todo noted (not yet filed) for the recurring cadence itself.

---

## Claude's Discretion

- IC-staleness observability signal's exact metric/log field name and emission point.
- `--backfill` mode's chunk size and checkpoint/resume strategy.
- Whether `sr_support_dist`/`sr_resist_dist` are still NULL post-142.5 (verify during research,
  don't assume the 2026-06-25 schema doc's note still holds).
- Frame-id generation strategy (`content_key()` vs. `gen_random_uuid()` default).

## Deferred Ideas

None raised — discussion stayed within phase scope throughout. Todos 078 and 082 (both
explicitly post-142B by their own text) were reviewed and correctly left deferred, not folded.
