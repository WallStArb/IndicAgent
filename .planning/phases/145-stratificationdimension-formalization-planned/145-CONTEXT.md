# Phase 145: StratificationDimension Formalization - Context

**Gathered:** 2026-08-06
**Status:** Ready for planning

<domain>
## Phase Boundary

Formalize governance for the conditioning layer that stratifies IC measurement and
(eventually) AnalogEngine retrieval by regime. Concretely: write the
`StratificationDimension` `Protocol`/ABC as real code, ratify the `concept_registry`
row-grain decision for the `regime_model` domain, add the two statistical/causal
safeguards this discussion identified as missing from the existing design docs, and
run exactly one candidate dimension (`volatility_pct`) through the full corrected gate
stack as proof the machinery works end to end. Does not seed `concept_registry`'s
schema for real (sequenced after Phase 170) and does not attempt to resolve todo 167
(equity-side HMM-vs-cross-sectional falsifier) as part of this phase's own work.

</domain>

<decisions>
## Implementation Decisions

### Row-grain (ratified, not deferred to planner)
- **D-01:** `concept_registry` uses **Option B** — one row per `(dimension,
  regime_group)`, encoded in `name` (e.g. `hmm_price_vol__equity`,
  `hmm_price_vol__rates`), reusing the existing `UNIQUE(domain, name)` constraint. No
  new columns. Each `(dimension, regime_group)` cell gets its own independent
  `status` and its own `concept_transition_log` history.
- **Rationale:** forced by data already in hand, not a style preference — the
  incumbent HMM is simultaneously live-quality for `equity` and deficient for `rates`
  (Phase 144's D-05 verdict). A single global-status row (Option A) cannot represent
  "verified-and-passing for one segment, unverified/failing for another"
  simultaneously without a bolt-on satellite fact table that doesn't exist and isn't
  designed. Option B represents this for free.
- **Consequence for todo 167:** the contract must be written regime_group-agnostic —
  it must not hard-code an assumption that only `rates` needs a fallback/shadow
  state. Equity's `(hmm_price_vol, equity)` cell simply sits in whatever status
  todo 167's eventual result implies (currently: never falsifier-tested, so
  effectively unverified) — same shape as any other cell, no special-casing.

### Todo 167 sequencing (ratified)
- **D-02:** Phase 145 does **not** block on todo 167, and does **not** fold todo
  167's execution into its own scope. Todo 167 (run the equity-scoped
  `ic_engine.py` pass + `equity_regime_separation_gate.py`) remains an independent,
  already-filed piece of work, queued behind the in-flight corpus rebuild — folding
  it in would conflate "build the governance contract" with "close an unrelated
  empirical question on someone else's timeline."
- **Rationale:** Option B's per-`(dimension, regime_group)` state already absorbs
  whatever todo 167 finds later with zero rework to the contract. Blocking Phase 145
  entirely on it wastes a legitimate parallel-work opportunity (design/discussion
  work has no compute or file-level collision with the in-flight OHLCV backfill,
  the CTF/Phase 167 gate re-verification, or Phase 170's concurrent
  `concept_registry` migration).

### Statistical safeguard added to scope: multiple-testing correction across the candidate pool
- **D-03:** The substitution test's promotion decision must be corrected for
  multiple comparisons across the cumulative set of candidate-dimension tests run
  for a given `regime_group`, not evaluated as an isolated per-candidate
  significance check. Every test (pass or fail) is logged to
  `concept_transition_log`; a "pass" on the raw substitution-test criterion (IC
  Sharpe +>10% in a joint cell, N > effective-N floor) becomes eligible for
  promotion to `active` only after BH-FDR correction across that `regime_group`'s
  test history. New APR key: `alpha.regime_stratification.fdr_alpha`.
- **Rationale:** the candidate list has 15+ named dimensions
  (`volatility_pct`/`dispersion`/`factor_regime`/`term_structure`/E1-E4/deferred
  HMM variants). Testing that many candidates over the system's lifetime with no
  family-wise error control produces exactly the failure pattern this project has
  already lived through three times (CTF momentum join leak, HMM parameter
  lookahead, `nonlinear_interaction_combiner`'s inflated headline number — all
  confirmed 44-91% leak-driven per STATE.md's 2026-08-05 strategic-plan note). The
  `confluence` domain in `concept-unified-registry.md` already specs BH-FDR across
  its discovery batch as gate 2 of its six-gate stack; `regime_model`'s three-stage
  cascade as currently specced has no analogous step — this closes that asymmetry
  rather than let `regime_model` inherit the weaker discipline by omission.
- **Scope note:** this is new scope beyond the roadmap's current Phase 145
  description — an explicit addition, not a re-derivation of something already
  written down.

### Statistical safeguard added to scope: effective-N floor, not raw bar count
- **D-04:** Before any real substitution test runs, derive the effective-N floor
  for the gate from the number of regime *transitions* observed in the relevant
  window (a proxy for independent state-visits), not the raw bar count the design
  doc currently states ("N > 20,000 bars"). HMM/percentile-rank regime states are
  autocorrelated by construction (and additionally smoothed via `min_hold_bars`) —
  consecutive bars in the same state are close to duplicate observations, not
  independent draws. This is the same correction already flagged (but not yet
  derived) for `hmm_variant`'s effective-N floor in `concept-unified-registry.md`'s
  Domain Vetting section; `regime_model` inherits the identical gap and needs the
  identical fix before its gate is trustworthy.
- **Consequence:** deriving this floor is a real deliverable of this phase (new
  statistical work), not a caveat to note and defer indefinitely.

### Causal safeguard added to scope: enforce `causality_basis`, don't just declare it
- **D-05:** No provider may enter gate 0 (structural redundancy pre-filter) without
  first passing an automated acausal-placebo test that verifies its `compute()`
  produces no informative labels on a shuffled/future-blind version of its input.
  This generalizes the existing `canary_acausal_placebo` mechanism
  (`scripts/ops/alpha/ops_canary_integrity_assert.py`,
  `.planning/todos/completed/204-canary-acausal-placebo-pooled-not-detected.md`)
  from a single planted-leak feature check into a mandatory registration
  precondition for every `StratificationDimension` implementation.
- **Rationale:** the contract as originally sketched adds a `causality_basis` field
  (`deterministic`/`expanding_window`/`fitted`) that a provider self-declares, with
  nothing checking it. This project has hit exactly this failure shape three times
  already (CTF momentum batch-join lookahead — todo 243; HMM parameter lookahead —
  todo 248; the still-partially-diagnosed `canary_acausal_placebo` POOLED-gate
  anomaly — todo 204). A self-reported, unverified causality field is the same
  silent-wrong-answer pattern that let those three ship. "Silent wrong answers are
  worse than loud crashes" (project principle) means `causality_basis` must be a
  gate, not a comment.
- **Scope note:** also new scope beyond the roadmap's current description, alongside
  D-03.

### Pilot-only candidate scope (ratified)
- **D-06:** This phase runs exactly **one** candidate dimension —
  `volatility_pct` — through the full corrected gate stack (structural pre-filter →
  orthogonality study → effective-N-corrected, FDR-corrected substitution test).
  Every other entry in the candidate table
  (`dispersion`/`factor_regime`/`term_structure`/E1-E4/deferred HMM variants/
  non-HMM stamped scalars) stays backlog — explicitly not built or tested in this
  phase.
- **Rationale:** `volatility_pct` is already identified in
  `stratification-dimension-unification.md` as the cheapest, zero-schema-change
  first probe, exempt from the orthogonality gate. Running one candidate all the way
  through validates the new FDR-correction and effective-N mechanisms themselves
  against a single, well-understood case before opening the pool to more
  candidates — fewer tests run also means less FDR burden to spend while the
  correction mechanism is itself unproven. This also forces
  `alpha.regime_stratification.max_correlation` (currently "no default asserted")
  to get a real empirically-derived value rather than remaining open-ended config.

### `concept_registry` schema sequencing (ratified, unchanged from roadmap)
- **D-07:** Design work (the Protocol/ABC, the row-grain ratification, the FDR and
  effective-N mechanism design) proceeds now. The actual `concept_registry` schema
  write — seeding the `regime_model` domain, adding
  `alpha.regime_stratification.fdr_alpha` and related APR keys via migration —
  sequences **after** Phase 170 (`feature_registry`→`concept_registry` migration,
  running concurrently in a separate session as of 2026-08-04) lands, per the
  roadmap's existing note. No file-level collision with Phase 170 during design/
  discussion; only the schema-write step needs to wait.

### Known, accepted limitation — not fixed this phase
- Candidate-dimension *generation* is theory-first (human backlogs, a session
  comparing against standard hedge-fund regime taxonomy), while candidate
  *validation* is empirical (the three-gate cascade). The system's "empirical over
  theoretical" framing currently only applies to validation. Not worth fixing here —
  a data-driven candidate-generation step would multiply the FDR burden before the
  correction mechanism above even exists — but state this plainly in the design doc
  rather than implying the process is empirical end to end.

### Claude's Discretion
- Exact shape of the `alpha.regime_stratification.fdr_alpha` APR key naming and its
  interaction with existing `alpha.decay.*` keys.
- Exact implementation of the acausal-placebo registration check (test harness
  location, whether it's a pytest fixture, a standalone script mirroring
  `ops_canary_integrity_assert.py`, or a decorator-enforced runtime check) — left to
  the planner/researcher to scope against existing test infrastructure.
- Whether the effective-N floor derivation is a one-time empirical study written up
  in a doc, or a runtime-computed value per gate invocation — planner's call, guided
  by whichever is cheaper without compromising rigor.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Design and governance (primary)
- `docs/research/stratification-dimension-unification.md` — canonical design doc:
  the `StratificationDimension` `Protocol` sketch, the three-gate cascade (§
  Governance), the full candidate-dimension table, Open Questions 1-4, and the
  `volatility_pct` pilot recommendation
- `docs/research/concept-unified-registry.md` § Domain Vetting (`regime_model`
  subsection, lines ~896-975) — the row-grain Option A/B specification this phase
  ratifies (Option B), the three-stage gate cascade ported into `concept_registry`
  terms, and the effective-N caveat already flagged for both `hmm_variant` and
  `regime_model`
- `docs/research/concept-unified-registry.md` § Domain Vetting (`confluence`
  subsection, lines ~976-1009) — the BH-FDR precedent this phase's D-03 generalizes
  to `regime_model`
- `docs/research/concept-governance-registries.md` — the three-registry taxonomy
  `regime_model` (as a Concept Registry domain) fits into

### Empirical state this phase's decisions are grounded in
- `.planning/ROADMAP.md` § Phase 144 (`### Phase 144: Cross-Sectional Regime Model`)
  — the D-05 verdict this phase's row-grain decision is forced by (HMM live for
  `equity`, deficient/demoted for `rates`)
- `.planning/ROADMAP.md` § Phase 145 — current roadmap entry, including the
  2026-08-06 currency re-check (todo 167 still open, `fx` group live, Phase 170
  concurrent)
- `.planning/todos/pending/167-equity-cross-sectional-vs-symbol-hmm-never-falsifier-tested.md`
  — the open equity-side falsifier question this phase's contract must stay
  agnostic to (D-02)
- `.planning/todos/completed/111-stratification-classification.md` — closed
  2026-08-03, superseded by the ROADMAP Phase 145 entry; read for the original
  Option A/B framing

### Causality safeguard precedent
- `.planning/todos/completed/204-canary-acausal-placebo-pooled-not-detected.md` —
  the existing `canary_acausal_placebo` mechanism D-05 generalizes into a
  per-provider registration gate
- `.planning/todos/pending/243-ctf-momentum-batch-join-lookahead-bias.md` — one of
  the three prior lookahead incidents motivating D-05
- `.planning/todos/pending/248-hmm-full-history-fit-regime-label-instability-gate4-pilot.md`
  — the second prior lookahead incident motivating D-05

### Statistical-integrity context
- `.planning/STATE.md` § Strategic Plan (2026-08-05 revision) — the "every large
  number collapsed 44-91% once a leak was corrected" pattern D-03's FDR correction
  is designed to prevent recurring in this subsystem

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `scripts/ops/alpha/ops_canary_integrity_assert.py` — existing acausal-placebo
  check machinery; D-05's per-provider registration gate should follow this
  pattern rather than invent a new one
- `concept_transition_log` (schema already exists per `concept-unified-registry.md`)
  — the table D-03's FDR correction logs every candidate test to; no new table
  needed, only a new query/decision step reading from it before promotion
- `regime_writer.py`'s `min_hold_bars` smoothing — the existing mechanism that
  makes regime states autocorrelated, cited as the reason D-04's effective-N floor
  can't use raw bar counts

### Established Patterns
- `confluence` domain's six-gate ordered stack (`concept-unified-registry.md`) —
  the pattern D-03 generalizes from; already uses `concept_gate_stack` for ordered,
  non-scalar gates, which `regime_model` also needs per the existing Domain Vetting
  section (unchanged by this discussion)
- Migration 247 (`rates.dual_write_symbol_hmm`) / migration 262
  (`equity.dual_write_symbol_hmm`) — precedent for scoping a per-`regime_group` APR
  change as a one-line config edit with zero code change; the pattern D-01's row-
  grain decision extends into `concept_registry` proper

### Integration Points
- `services/ic_engine.py` — current hand-wired regime routing
  (`_resolve_regime_scope()`, the `mr_dict` join) this contract eventually replaces
  for consumers; out of scope for this phase's actual code (Protocol/ABC + one
  pilot only), but the researcher should confirm the Protocol shape is compatible
  with `ic_engine.py`'s existing call sites before planning the pilot's wiring

</code_context>

<specifics>
## Specific Ideas

No UI/behavioral specifics — this is a backend governance/contract phase. The
concrete artifacts this discussion pinned down: (1) the `Protocol`/ABC signature
from the design doc, unmodified except for the row-grain implication; (2) the
`alpha.regime_stratification.fdr_alpha` APR key; (3) an effective-N derivation
method based on regime-transition counts; (4) an acausal-placebo registration test
modeled on `ops_canary_integrity_assert.py`.

</specifics>

<deferred>
## Deferred Ideas

- **Data-driven candidate-dimension generation** (as opposed to human-curated
  backlogs) — named explicitly as a known limitation in D-03's discretion note, not
  scoped into any phase yet. Would need its own FDR budget considered before
  building, given D-03's correction is sized for the current ~15-candidate
  human-curated list.
- **Running todo 167 itself** (the equity falsifier gate) — explicitly kept as
  independent work, not folded into this phase (D-02).
- **The other 14+ candidate dimensions** beyond `volatility_pct` (`dispersion`,
  `factor_regime`, `term_structure`, E1-E4, deferred HMM variants, non-HMM stamped
  scalars) — stay in the candidate table as backlog, each still gated on todo 167's
  eventual conclusion, the orthogonality study, and the corrected substitution test
  this phase builds (D-06).

### Reviewed Todos (not folded)
- Todo 167 — reviewed extensively (it's the primary empirical grounding for D-01
  and D-02) but explicitly not folded into this phase's execution scope; see D-02.

</deferred>

---

*Phase: 145-StratificationDimension Formalization*
*Context gathered: 2026-08-06*
