# Phase 175: ITR materiality-filtered empirical tags for breadth/peer-grouping - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-09-18
**Phase:** 175-itr-materiality-filtered-empirical-tags-for-breadth-peer-gro
**Areas discussed:** Where the filter logic lives, Rollout strategy, Threshold-selection philosophy, Null-arm control construction

---

## Todo fold decision (cross_reference_todos)

The automated keyword matcher returned 106 low-relevance matches (score 0.4-0.6, mostly
one-off keyword collisions with no real topical connection). Filtered manually to the three
with genuine relevance and presented those instead of the full noisy list.

| Todo | Fold decision |
|---|---|
| 125 — discovery_oos_days gate not enforced | Folded in |
| 126 — instrument_tags.valid_to never filtered | Folded in |
| 272 — instrument-tag peer-group coverage auditor | Kept separate (different capability) |

**User's choice:** Fold 125 and 126; keep 272 separate.

---

## Where the filter logic lives

First AskUserQuestion presented a concrete choice (extend TagCalibrator / separate
consumer-side calculation / you decide). User redirected: rather than picking from the
menu, explicitly instructed Claude to reason through the decision as "a council of senior
engineers" applying Renaissance/Jim Simons-grade rigor (data integrity paramount, SoC, DAG
cleanliness, ruthless elimination of unnecessary complexity) and commit to an answer.

**Claude's reasoning (see CONTEXT.md D-01/D-02 for the full writeup):** extend
`TagCalibrator` with the computation as a 4th pass, persisted as new evidence columns;
each consumer applies its own threshold at read time. Rejected consumer-side computation
as a real SoC violation with guaranteed drift risk between two independently-maintained
copies of the same math.

**User's response:** No pushback — decision stands as reasoned.

---

## Rollout strategy

Reasoned through under the same directive (no separate menu asked, given the user's
standing instruction to reason-and-present for all four areas once given for the first).

**Claude's reasoning (see CONTEXT.md D-03):** shadow-mode-first, non-negotiable — a
standing CLAUDE.md principle, not a phase-specific choice, given this filter changes what
feeds `ensemble_trainer`/`ic_engine`'s live measurement pipelines once cut over.

**User's response:** No pushback — decision stands.

---

## Threshold-selection philosophy

**Claude's reasoning (see CONTEXT.md D-04/D-05):** don't average or arbitrarily pick
between Codex/Fable/AGY's differing proposed numbers as if reconciling them validates the
result — none were derived from this corpus's actual distribution. Seed the more
conservative reviewer's numbers as explicitly-uncalibrated APR keys, matching this
project's own APR-calibration-backlog convention.

**User's response:** No pushback — decision stands.

---

## Null-arm control construction

**Claude's reasoning (see CONTEXT.md D-06):** circular time-shift of the `factor_series`
proxy's own return series, not a symbol-shuffle or candidate-return shift — reuses the
existing circular-shift null pattern in `tsmom_per_symbol_ic_screen.py` rather than
inventing a new methodology, and is the only construction of the three considered that
isolates the incremental-loading question without contaminating the market-beta control.

**User's response:** No pushback — decision stands. User also authorized using Fable for
review of this phase's eventual plan ("feel free to use fable"), captured as D-07.

---

## Claude's Discretion

- Exact column names/types for the new `instrument_tags` evidence fields — left to
  research/planning (CONTEXT.md notes this explicitly).
- Whether the live cutover of the two consumers' queries becomes this phase's own scope
  or a separate follow-on phase — left open pending the shadow-mode diagnostic's findings.

## Deferred Ideas

- Todo 272 (peer-group coverage auditor) — different capability, stays its own future todo.
- Live cutover of `breadth_vol.py`/`cross_sectional_regime_model.py` queries — may become
  its own phase, gated on this phase's shadow-mode diagnostic.
