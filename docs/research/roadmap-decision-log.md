# ROADMAP.md decision log

**What this is:** durable reasoning behind `.planning/ROADMAP.md` that isn't obvious from current
phase status alone — non-obvious architectural rationale, decisions that could plausibly get
re-litigated or re-discovered as "bugs" later, and open falsifiers. This is not a full audit
trail: dated correction narratives, superseded verdict-by-verdict bug hunts, and closed-item
trivia were pruned 2026-07-14 rather than archived — once a correction has landed and ROADMAP.md
states the corrected fact, the story of the mistake has no forward reference value. Keep this doc
lean on the same principle: add an entry only if someone doing future work would actually need it.

---

## Process lesson

**Don't conflate readiness with value.** Being unblocked makes a phase eligible to start, not
important. A phase with zero dependencies but low scored reward doesn't outrank a blocked
high-reward phase just because it can start today — check the effort/risk/reward table
(`docs/research/intelligence-lifecycle-backlog-matrix.md`), not just the dependency graph.

**A plan doc claiming a phase number is not a registration.** Found 2026-07-18: a fully-specced,
`Priority: HIGH` plan (`docs/research/unified-orthogonalization-layer.md`, dated 2026-07-14,
self-declared "Phase 162") sat as a freestanding markdown file for 4 days — never entered in
ROADMAP.md, the backlog matrix, or PRIORITIES.md — until an unrelated audit stumbled on it by
accident. In that window its claimed number was independently reused by a real phase, and its
claimed hard blocker on Phase 144 was silently never honored (144 shipped without it). No process
caught either fact; only a broad manual sweep did. **Rule: writing a plan doc that names a
ROADMAP phase number is not the same action as registering that phase — the ROADMAP.md entry (at
minimum a stub with the doc's status) must land in the same commit as the plan doc, not "when
someone gets to it."** A plan doc without a live ROADMAP/matrix/PRIORITIES pointer is
indistinguishable from an abandoned draft — don't rely on a future audit to notice the
difference.

## v4.0: why Portfolio State is its own phase (156), not folded into sizing (157)

Portfolio Kelly, aggregate VaR, correlation-aware sizing, and a portfolio-level kill switch are
fundamentally portfolio-level, not per-security — none of it is computable from any single
symbol's `alpha_score`. Every other stateful concept in this system that multiple consumers need
(regime, feature lifecycle, config) has its own persisted, single-writer entity —
`market_regimes`, `feature_registry`, `config_state`. The portfolio's own current state (open
positions, aggregate exposure, correlation-cluster concentration, capital utilization,
drawdown-to-date) had no such home in the original single-phase design; it was about to be
computed inline inside a sizing function, which would have silently violated this project's own
"one model, one book" principle (`docs/foundation/principles.md`). Hence four phases, strictly
sequential: 156 (Portfolio State — the entity) → 157 (Position Sizing & Risk — first consumer) →
158 (execution, needs 157's position sizes) → 159 (cost calibration, needs 158's real fills).

## Phase 142A: EIC-04 gate — bug patterns found en route to a trustworthy PASS

Current state (what ROADMAP.md keeps): PASS, 54/1425 = 3.79% qualifying, as of 2026-07-10. Getting
there took 5 superseded verdicts as real measurement bugs were found and fixed. Kept here as a
checklist of bug *classes*, not a play-by-play — if a future gate looks suspiciously FAIL/PASS,
check for these patterns first:

- **Unexercised pipeline paths mistaken for data starvation.** 1h/1d timeframes had qualifying
  upstream IC but zero downstream ensemble rows — nobody had re-run the trainer for them, not an
  IC problem.
- **Unweighted cell-counting in a pass/fail gate.** Counting `POOLED` and each per-symbol row as
  one equal vote conflates "no pooled signal" with "per-symbol slices too thin to resolve
  individually."
- **Meta-FDR pooled across incompatible strata.** `GROUP BY feature_name` without `tf` let a
  feature strong at 1d but noisy at 5m get vetoed everywhere; fixed to `GROUP BY feature_name, tf`.
- **`DELETE ... RETURNING` on a 30M+-row table** forced Postgres to materialize the entire
  deleted-row set and OOM-killed the backend, crashing the whole TimescaleDB instance. Use a
  command-tag row count instead of `RETURNING` for bulk deletes.
- **Post-selection bias: measuring IC on the post-filter population instead of the pre-filter
  scored population.** Conditions the correlation test on the very confidence gate being
  validated. The gate population should always be defined before any emission/threshold filter.
- **A schema migration silently dropped 91 of 161 columns from the INSERT statement** when
  `FeatureVector` grew but the hand-maintained INSERT SQL wasn't updated — compute logic was
  correct and tested, values were computed correctly in memory, then discarded before ever
  reaching the database. 98/156 columns were 100% NULL for an entire corpus generation. Fix:
  generate the INSERT column list programmatically from `dataclasses.fields()`, plus a structural
  regression test asserting every field appears as a column — this exact failure mode cannot
  recur silently.
- **A missing walk-forward eligibility check let 36% of "qualifying" cells through** without ever
  being confirmed out-of-sample — a gate had drifted out of sync with a sibling gate that already
  required it. Fix: extract shared eligibility constants so the criterion can't drift a second
  time.

## Phase 142.5: why 89 primitives, not 91

`new_high_flag`/`new_low_flag` were found mathematically redundant with `dist_from_high`/
`dist_from_low` — same rolling-max window, same comparison,
`new_high_flag[i] == 1{dist_from_high[i] <= eps/atr[i]}` exactly, zero orthogonal information.
Removed (migration 211, full proof in its header). 89 primitives, 150 total `FeatureVector`
columns, `feature_registry` at 150 rows.

## Phase 143: why there's no `pre_shadow_weight` column

Rejected during a plan revision: `services/ensemble_trainer.py` is the sole writer of
`ensemble_weights` and recomputes every weight from scratch each run from current
`feature_ic_scores` — no warm-start/prior-weight read exists anywhere in that file — so a scalar
`pre_shadow_weight` on `feature_registry` would write to a column nothing reads. Promotion
restores weight by the status flip alone; the next `ensemble_trainer` run does the rest. If this
gets re-proposed later, it's re-solving an already-closed question.

## Phase 144: non-obvious design decisions

**Why loud-crash over silent default for unrouted symbols:** the original design silently
defaulted unmatched symbols to `"equity"`. Rejected in favor of excluding them from
regime-stratified IC with loud startup logging — "silent wrong answers are worse than loud
crashes." Pooled IC still covers them; no data lost.

**Why crypto joined the `fx` group rather than getting its own:** N=1 crypto instrument (IBIT)
doesn't justify its own regime signal module; both crypto and fx are macro-liquidity-driven,
single-symbol-per-exposure assets. Revisit only if the crypto sleeve grows past N=1.

**Why commodity/fx enablement was blocked (historical — resolved 2026-08-07, todo 224):** todo
041 (tag exposure-vs-sensitivity taxonomy audit) — OIH/XLE/XOP carry both `eq_*` and
`commodity_energy_*` tags and would raise `AmbiguousRegimeGroupError` the moment
`commodity_energy` is enabled. Resolved without todo 041 ever running as a standalone audit:
`fx` enabled 2026-08-06, the three commodity sub-groups unified and enabled 2026-08-07
(migration 306), and the collision resolved via a new `exclude_symbols` field on
`_build_symbol_regime_class` rather than a taxonomy redesign — see
`.planning/todos/completed/224-commodity-fx-regime-group-reenablement-decision-todo-041.md`.

**Why OIH/XLE staying in equity breadth despite commodity-sensitivity tags isn't a blocker:**
defensible by convention (they're equity sector funds) — revisit only if Phase 146 tag calibration
shows material contamination.

## Phase 148: why "v2.x Retirement Gate" was dropped from the title

The scoring/proof half (Gate 1 + Gate 2) reads only pure v3.0 tables and has zero dependency on
v2.x's fate. Only a legacy-comparison step (formerly SCORE-04/05) ever touched v2.x, and it was
moved out of this phase's requirements — it depended on a "v2.x gets retired" assumption that's
now an open question (todo 056), not this phase's problem to resolve.

## v3.15: why weak-separation regime groups demote to shadow rather than get a bespoke model

Renaissance "delete before you build": a regime group whose per-symbol HMM shows weak IC
separation (gap < 0.01 in the per-symbol test) demotes to shadow rather than triggering a
dedicated per-asset-class model or factor-augmented variant. This is deliberately the
conservative default — it presupposes nothing about *why* separation is weak (wrong observation
features vs. missing exogenous factors are both live hypotheses with no experiment yet
distinguishing them), and it's reversible through the same substitution test any candidate uses
to get promoted. Full reasoning and falsifiers:
`docs/research/fable-2026-07-07-phase144-conditioning-decision.md`.

**Why Phase 143.1 became a hard prerequisite:** Phase 144's evidence (regime-conditional IC
separation) needs to be re-measured against a corpus produced by a corrected measurement pipeline
— 143.1 fixes a confirmed Fisher-z CI miscalibration and a confirmed sign-symmetry bug that
directly affect the `ic_ci_lower`/`ic_ci_upper` values any regime-separation analysis reads.
