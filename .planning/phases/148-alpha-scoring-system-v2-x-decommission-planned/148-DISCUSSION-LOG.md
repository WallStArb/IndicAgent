# Phase 148: Alpha Scoring System + v2.x Decommission - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-07-22
**Phase:** 148-Alpha Scoring System + v2.x Decommission
**Areas discussed:** Phase 147 dependency validity, OOS holdout integrity for Gate 2, Gate 1
scorer build approach, Gate 2 reporting method

---

## Phase 147 dependency validity

Not a formal gray area presented via AskUserQuestion — surfaced organically at the start of
this discussion when the user asked "Is this v2 work? We were supposed to be building v3,"
challenging the earlier `/gsd-discuss-phase 147` session's premise that Phase 147 gated this
phase.

**Investigation:** Re-read Phase 148's SCORE-01/02/03 requirements against what tables they
actually query (`alpha_frames`, `alpha_ensemble_ic`, `alpha_strategy_scores` — all pure v3.0,
zero I7 lineage). Confirmed SCORE-04 (the only place Phase 147/I7 ever connected to this
phase) was already downgraded to "documentation only, not a gate" by the 2026-07-19 rewrite.

**Conclusion:** The "Depends on: Phase 147" line in ROADMAP.md was stale narrative sequencing,
not a real technical dependency — the same pattern this project's 2026-07-01 roadmap
dependency audit previously caught and fixed elsewhere. Corrected in ROADMAP.md, the backlog
matrix, and STATE.md (commit `4ef1b71a`). Phase 148 confirmed unblocked, independent of
Phase 147.

---

## OOS holdout integrity for Gate 2

| Option | Description | Selected |
|--------|-------------|----------|
| Disclose, don't block | Document prior looks (143.1-08, todo 165) and the no-tuning-occurred argument plainly in the promotion decision record | ✓ |
| Treat Gate 2 as compromised | Need a genuinely fresh OOS window (extend `oos_start` forward) before evaluating cleanly | |
| Something else / discuss further | | |

**User's choice:** User declined to pick from the menu and instead directed Claude to apply
the "council of senior Renaissance engineers / Jim Simons" lens directly and commit to a
decision autonomously, rather than presenting more options.

**Claude's reasoning (autonomous decision per user's direction):** The champion ensemble's
actual Gate-2-equivalent numbers already exist, computed, in `143.1-08-SHADOW-VALIDATION.md`
(section 6) — not merely "the window was peeked at" in the abstract, but the literal
pass/fail numbers are already sitting in a committed doc. Re-running an equivalent
computation to appear "fresh" would be theater, not rigor. Shifting the OOS window forward
specifically because the currently-visible result is unfavorable would itself be the
post-hoc renegotiation `SHADOW-REVIEW.md` explicitly forbids, just applied to the window
boundary instead of a numeric threshold. Decision: **disclose and proceed** — adopt the
existing numbers formally, cite provenance, state the no-tuning-occurred argument, don't
pretend not to know what's already known.

**Notes:** On follow-up ("What would Jim Simons demand"), Claude refined this further: the
pooled verdict must never stand alone — it must be paired with a regime-stratified breakdown
using todo 165's already-built `evaluate_frame_gate` machinery, because reporting a flat
pooled FAIL without it would repeat the exact single-fixed-window blindness todo 165 just
diagnosed and fixed for the same underlying data, one phase later. Captured as D-07 in
CONTEXT.md.

---

## Gate 1 scorer build approach

| Option | Description | Selected |
|--------|-------------|----------|
| Standalone one-shot script (recommended) | Reuse `EnsembleICEngine`'s pure IC helpers, same pattern as the existing interim diagnostic scorer, doesn't touch the shared `alpha_ensemble_ic` table | ✓ |
| Add OOS-mode flag to `EnsembleICEngine` itself | Extend the existing service with an `--oos` flag writing real `alpha_ensemble_ic` rows for the OOS window | |

**User's choice:** Same as above — user directed Claude to decide autonomously via the
Renaissance/Simons lens rather than picking from the menu.

**Claude's reasoning:** Checked `alpha_ensemble_ic`'s live schema — no column distinguishes
in-sample vs. OOS-scored rows. Writing OOS results into the shared table would create two
indistinguishable row populations, a real silent-ambiguity risk for future consumers of that
table. Standalone script keeps `alpha_ensemble_ic` single-purpose (SoC), reuses existing pure
functions (no reimplementation), and writes its verdict to `gate_evaluations` (already
specified by SCORE-02) instead.

**Notes:** Follow-up decision (unprompted by a specific question, surfaced during the
"what would Simons demand" synthesis): Gate 1 should be built and run **before** Gate 2's
formal evaluation, since it's the genuinely untested, foundational question ("is there real
signal at all") and conflating it with Gate 2's already-complicated picture risks losing the
independent-diagnosis discipline the two-gate design exists to enforce. Captured as D-02 in
CONTEXT.md.

---

## Claude's Discretion

- Exact location/format of the promotion decision record document.
- Whether Gate 1's standalone script lives under `scripts/ops/corpus/` or
  `scripts/analysis/`.
- `gate_evaluations` table schema details beyond what SCORE-02/03 already specify.

## Deferred Ideas

- Phase 147 (I7 CORPUS-07 evaluation) — confirmed pure due diligence on a dead system, not a
  gate on this phase. Whenever convenient.
- v2.x physical decommission (todo 056) — explicitly out of this phase's scope per the
  2026-07-19 operator call.
- Diagnosing and fixing a HOLD verdict on Gate 2 (if it comes back that way) — this phase
  produces the verdict and diagnostic evidence, not a fix.
