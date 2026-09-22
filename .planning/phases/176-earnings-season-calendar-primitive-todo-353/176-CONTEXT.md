# Phase 176: Earnings-Season Calendar Primitive (todo 353) - Context

**Gathered:** 2026-09-22
**Status:** Ready for planning

<domain>
## Phase Boundary

Ship `is_earnings_season` (binary) and `days_since_quarter_end` (continuous companion) as new
`feature_factory.py` calendar-group primitives, AND wire `is_earnings_season` into
`ic_engine.py`'s regime segmentation as a conditioning axis. Two connected workstreams, both in
scope (see D-01) — not just a standalone feature, and not just the regime integration alone.

Out of scope: no new data source (market-wide earnings season is pure calendar math off
`bar_ts`, same pattern as `_quarter_position`/`_days_to_month_end_fraction` — no per-company
earnings-date table). No trade construction or live promotion decision — this phase ends at a
real `feature_ic_scores` FDR/walk-forward gate pass, same as any other new primitive.

</domain>

<decisions>
## Implementation Decisions

### Scope (D-01)
- **D-01:** Build BOTH workstreams in this phase, not staged across two phases. User's explicit
  call, invoking a "design this like Renaissance would" lens: a council of senior
  quants/engineers wouldn't ship the weaker of two findings and leave the stronger one (the
  regime-conditioning angle) on the table as unfinished business. Accept the added risk of
  touching `ic_engine.py`'s cross-sectional regime-segmentation code (documented OOM history,
  see `docs/foundation/performance-investigation-sop.md` and the `357`/`358` todos) as the cost
  of doing this once, correctly, rather than twice.

### Field scope (D-02)
- **D-02:** Ship both `is_earnings_season` (binary) and `days_since_quarter_end` (continuous
  companion), not the binary flag alone. User's explicit call. Note for planning: unlike
  `is_earnings_season`, `days_since_quarter_end` has NO proxy-test evidence of its own yet (see
  D-04) — treat it as a companion encoding that rides along with the validated primitive, not as
  independently pre-validated. It still needs to clear its own `feature_ic_scores` gate like
  every other feature; it is not exempted by `is_earnings_season`'s evidence.

### Design principles (D-03)
- **D-03:** Renaissance-rigor lens is binding for planning and execution, not just vision-level
  framing — apply CLAUDE.md's own "Design mindset" section literally:
  - **Data integrity paramount / no hidden bias:** the corrected-window re-verification (D-04)
    is exactly this instinct in practice — don't build on top of an unverified or overstated
    effect. Carry the same skepticism into the regime-conditioning integration: verify the
    `up_vol_body_diff` IC-doubling finding's own numbers before wiring it in, don't take the
    todo's reported figures as final without re-checking (same discipline just applied to
    `is_earnings_season`'s primary effect).
  - **Ruthless simplicity / component reuse:** the binary/continuous primitives MUST reuse the
    existing calendar-group pattern (`_quarter_position`, `_days_to_month_end_fraction`,
    `_quarter_cycle_encoding` in `feature_factory.py` — see `<code_context>`), not invent a new
    shape. The regime-conditioning integration should reuse `ic_engine.py`'s existing
    regime-stratification machinery (whatever shape research finds fits best — see the open
    question in `<code_context>` Integration Points) rather than building a parallel mechanism.
  - **DAG topology / SoC:** compute (feature_factory.py) stays separate from persistence
    (FeatureVectorWriter) stays separate from the IC-measurement layer (ic_engine.py) — the
    regime-conditioning integration reads `is_earnings_season` off already-persisted
    `feature_vectors` rows, it does not create a new inter-stage coupling or have `ic_engine.py`
    compute calendar math itself.
  - **No magic numbers:** the 14/42-day window boundaries are numeric thresholds and MUST be
    APR-backed (`ConfigService.get()`, a `feature.earnings_season.*` or similar namespace key,
    not hardcoded literals in `feature_factory.py`) per CLAUDE.md's Adaptive Parameter Registry
    mandate — this is an existing, non-negotiable project rule, not a new decision, flagged here
    so planning doesn't miss it.

### Corrected evidence base (D-04)
- **D-04:** The todo's original proxy-test numbers (4.3x, p=1.2e-17, 81% of symbols) used the
  WRONG window (0-42 days post-quarter-end) and are superseded. Re-verified live 2026-09-22
  against the CORRECTED 14-42-day window: **1.90x ratio** (mean return in-season 0.000397 vs.
  off-season 0.000209), **Welch p=5.05e-05** (not 1.2e-17), **67% of symbols** higher in-season
  (155/233, not 81%). Still a real, broad, statistically significant effect — worth building —
  but planning and any write-up must cite these corrected numbers, not the todo's original ones.
  The todo's own caveat still applies on top of this correction: daily returns within a 6-week
  earnings-season block are autocorrelated, so even this corrected naive Welch t-stat overstates
  the effective N — the real test is `ic_engine.py`'s FDR/walk-forward gate, not this proxy.
- The second finding (`up_vol_body_diff`'s Spearman IC nearly doubling in-season, +0.0197 vs.
  +0.0103) was reported as already using the corrected 14-42-day window in the todo — NOT
  independently re-verified during this discussion (budget constraint). Per D-03's own
  data-integrity principle, research should re-verify this number before it drives the
  regime-conditioning integration's design, the same way D-04 re-verified the primary effect.

### Claude's Discretion
- Exact implementation shape of the `ic_engine.py` regime-conditioning integration (new
  `regime_group`-style axis vs. a stratification split within existing cross-sectional cells vs.
  something else) — this is a HOW question for research/planning, not a vision decision; see
  `<code_context>` Integration Points for the open question research should resolve.
- Whether `days_since_quarter_end` is raw days or normalized (e.g., z-scored, or
  fraction-of-quarter like the existing `quarter_position` pattern) — planning's call, informed
  by the existing calendar-group primitives' conventions.

### Folded Todos
- **353** (this phase's origin) — is_earnings_season calendar primitive, validated candidate.
  Full scope folded into this phase; todo 353 should be closed (moved to `completed/`) once this
  phase ships, referencing this phase directory.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Design principles / rigor mandate
- `CLAUDE.md` — "Design mindset" section (data integrity, DAG topology, SoC, async-first) and
  "5-Step mandate" section — the binding lens per D-03.
- `docs/foundation/principles.md` — full Renaissance/Simons principles doc.

### APR (numeric-threshold governance)
- `docs/foundation/adaptive-parameter-registry.md` — full spec; the 14/42-day window boundaries
  must be seeded here per D-03, not hardcoded.

### Concept lifecycle
- `docs/foundation/unified-concept-registry.md` — migration-time genesis-seeding exemption
  (`concept_registry` row with `status='active'` inserted directly by the schema migration,
  established practice across migrations 288/289/290/291/316) applies to this phase's new
  `FeatureVector` fields.

### Naming
- `docs/foundation/naming-system.md` §7 — gradient/calendar-scale vocabulary conventions, in
  case `days_since_quarter_end`'s naming needs a scale qualifier.

### Performance / hot-path risk
- `docs/foundation/performance-investigation-sop.md` — mandatory reading before touching
  `ic_engine.py`'s cross-sectional cell code (the regime-conditioning integration half of this
  phase) given its documented OOM history (todos 357/358/371).

### Origin
- `.planning/todos/pending/353-earnings-season-calendar-primitive-candidate.md` — the source
  todo, including the original (now-superseded, see D-04) proxy-test numbers and the second
  finding's un-reverified `up_vol_body_diff` numbers.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `_quarter_position(bar_ts)` (`src/intelligence/feature_factory.py:3303`) — the existing
  calendar-group primitive pattern: pure function, `bar_ts: datetime -> float`, computed inline
  in both `compute()` and `compute_batch()`, registered in the field-to-group dict
  (`"calendar"`, line ~190-195).
- `_days_to_month_end_fraction(bar_ts)` (line 3313) and `_quarter_cycle_encoding(bar_ts)` (line
  3320) — same pattern, including `_quarter_cycle_encoding`'s example of reusing another
  primitive's computation directly rather than recomputing (`qp = _quarter_position(bar_ts)`) —
  the reuse discipline D-03 asks for already has a precedent in this exact file.
- `_guard()` — the existing NaN/None-safety wrapper applied to every calendar primitive at
  construction time (e.g. line 6427-6430) — new fields must follow the same guard pattern.

### Established Patterns
- Calendar-group `FeatureVector` fields are registered in three places per addition: (1) the
  field-to-group dict near line 190, (2) the dataclass field list (~line 6116-6120), (3) both
  `compute()` (~line 7058) and `compute_batch()` (~line 7705) construction sites. A new
  primitive here is a 3-site-plus-migration change, not a 1-line add.
- Migration-time `concept_registry` genesis-seeding (see canonical refs) is the established
  pattern for new `FeatureVector` fields — no separate runtime promotion needed at ship time.

### Integration Points
- **Open question for research:** `ic_engine.py`'s regime segmentation currently has two live
  axes — `feature_vectors.regime` (per-symbol HMM, 5-state, confirmed a volatility partition per
  Phase 171) and `market_regimes`/`regime_group` (cross-sectional, `breadth_vol`/`curve_credit`
  pluggable signal, Phase 144). `is_earnings_season` is neither — it's a deterministic calendar
  boolean, not a fitted/HMM-derived label. Research needs to determine whether it fits as (a) a
  new `regime_group`-style pluggable signal, (b) a stratification split applied within existing
  cross-sectional cells (filter cells by earnings-season membership before the existing
  IC/FDR/walk-forward machinery runs), or (c) something else — and whether `ic_engine.py`'s
  documented OOM-sensitive cell-materialization code (todos 357/358/371) constrains the choice.

</code_context>

<specifics>
## Specific Ideas

No UI/UX specifics — this is a pure data-pipeline feature addition, no dashboard-facing
component in scope for this phase.

</specifics>

<deferred>
## Deferred Ideas

None raised beyond the phase's own two workstreams — discussion stayed within scope.

### Reviewed Todos (not folded)
None — todo 353 is the phase's sole origin and was folded in full.

</deferred>

---

*Phase: 176-earnings-season-calendar-primitive-todo-353*
*Context gathered: 2026-09-22*
