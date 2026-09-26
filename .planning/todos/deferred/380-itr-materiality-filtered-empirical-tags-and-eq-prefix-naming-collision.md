---
status: pending
priority: P2
filed: 2026-09-17
source: deferred option (b) from todo 379, plus a root-cause finding from AGY's review of
  the todo 379 design doc that neither Codex nor Fable's parallel reviews surfaced
---

# ITR follow-up: materiality-filtered empirical tags for breadth/peer-grouping, and the eq_* naming collision

## What

Todo 379 shipped the `source='human'`-only stopgap for `equity_regime_model.py` and
`cross_sectional_regime_model.py`'s breadth/peer-grouping reads of `instrument_tags`. All
three independent reviewers (Codex, Fable, AGY) agreed the stopgap should land first, but
flagged it as a bigger hammer than the underlying question calls for -- it discards
empirical sensitivity data that may have genuine value once properly filtered. Two related
pieces of follow-up design work, not urgent (nothing is actively wrong today):

### 1. Materiality filter for empirical tags in sensitivity/behavioral-similarity contexts

Breadth/peer-grouping questions ("does this instrument trade like an equity/rates/fx peer")
are legitimately about behavioral similarity, not categorical identity -- unlike
`ic_engine.py`'s routing question. A well-designed empirical-tag filter could admit real
signal the human-only stopgap now excludes. All three reviewers converged on the same shape
of fix and independently rejected loading-magnitude-alone or `passes_fdr`-alone (both
reproduce the ic_engine.py bug's own finding -- significance and materiality are different
questions at n=250+):

- **Codex**: orthogonalize the target group factor against a control set (broad equity,
  rates curve/credit, dollar, commodity broad/sector) first, then gate on the *incremental*
  partial coefficient/partial-R² of the residualized loading -- not the raw bivariate
  loading. Proposed concrete gate: `sample_n >= 756`, BH-FDR on the partial coefficient,
  `abs(partial_beta) >= 0.35`, incremental `partial_R2 >= 0.05`, sign-stable in >= 3 of 4
  rolling 252-day windows, lower-CI bound on `abs(partial_beta) > 0.20`. Should also respect
  the ITR's own already-documented-but-unenforced `discovery_oos_days` pending-OOS state
  (`docs/foundation/instrument-tag-registry.md` Known Gaps) before a newly-discovered
  empirical tag affects a regime label.
- **Fable**: same shape (regress `symbol_return ~ market_return + factor_series_return`,
  gate on the incremental factor coefficient after controlling for market beta), plus a
  peer-relative check (is the candidate's loading inside the distribution already exhibited
  by symbols carrying the human tag, not merely nonzero). Must clear a null-arm
  (scrambled-data) control before trusting it, per this project's standing HMM-regime-
  candidate rule -- that discipline generalizes to any auto-classifier gating a regime label.
- **AGY**: same orthogonalization math, `|beta| >= 0.30` + `ΔR² >= 0.05`, plus an
  asset-class prior constraint (candidate must already be inside `tag_vocabulary.category
  = 'exposure'`'s broad asset-class family) to bar cross-asset leakage.

Whichever design is built, all three agree: reuse one filter implementation across both
consumers, but calibrate the threshold per consumer -- `equity_regime_model.py`'s (or its
replacement's) breadth fraction is a single aggregate multiplying error across the whole
downstream stack and warrants a near-definitional confidence bar; `cross_sectional_regime_
model.py`'s peer pools are smaller and group-scoped and can tolerate a somewhat lower one.

### 2. `eq_*` naming collision -- RE-VERIFIED 2026-09-17, downgraded to a documentation note, NOT an active fix needed

AGY's original framing (below, kept for record) proposed renaming `eq_low_vol`/
`eq_momentum`/`eq_quality` out of the `eq_*` prefix family. **Checked against live data
before implementing, and the premise doesn't hold**: `tag_vocabulary`'s current
descriptions (not visible to AGY's review, which only read migration 343) show these three
tags were deliberately designed in Phase 174 D-06 to nest under `eq_factor` as refinements
("`eq_factor` is retained as the parent-level label; this tag refines, not replaces, it") --
renaming them would reverse a real, recent, deliberate architectural decision, not fix an
accident.

More importantly: verified live that `MTUM`/`QUAL`/`USMV` (the three factor-proxy ETFs
themselves) each carry their OWN `source='human'` row for `eq_momentum`/`eq_quality`/
`eq_low_vol` respectively -- meaning **todo 379's `source='human'` stopgap already fully
resolves this for real data today**: the human filter correctly keeps the three legitimate
identity refinements (MTUM/QUAL/USMV stay routed as equity-family members) while excluding
every other instrument's spurious empirical loading on the same tag names (confirmed:
before the 379 fix, AAPL/FXA/GLD/etc. all carried `source='empirical'` rows for these same
three tags; after it, only the 3 human rows remain visible to identity-based consumers).

**Residual risk, now correctly scoped as hypothetical, not live**: a FUTURE human manually
asserting `eq_momentum`/`eq_quality`/`eq_low_vol` on a genuinely non-equity instrument would
still slip through the source filter (since it would be `source='human'`) -- this requires
a human tagging error, not a system bug, and is a much weaker risk than the "future
non-equity human tag" framing originally suggested. Not worth a schema change today. If this
ever becomes a real concern, option (ii) (also requiring `measurement_type='definitional'`)
is the safer fix of the two originally proposed -- it doesn't touch a live, intentional
design decision the way renaming would.

<details>
<summary>Original framing (AGY's proposal, superseded by the re-verification above)</summary>

Migration 343 deliberately made `eq_low_vol`/`eq_momentum`/`eq_quality` (all
`tag_vocabulary.category='exposure'`) empirically measurable against USMV/MTUM/QUAL,
calling them "genuine falsifiable exposure claims" (migration comment, line 21) -- a
defensible decision on its own terms (style-factor exposure is a real, measurable thing).
The bug is that these three tags share the `eq_*` textual prefix with true equity-identity
tags (`eq_broad`, `eq_sector`, `eq_factor`, ...), and every identity-based consumer in this
codebase resolves group membership via a raw `tag LIKE 'eq_%'`/prefix-match, with no way to
distinguish "IS equity" from "exhibits an equity-style factor." The `source='human'` filter
in todo 379 fixes today's contamination (all offending rows happen to be empirical), but a
future human-curated `eq_momentum` assignment for a genuinely non-equity instrument would
still slip through undetected by that filter alone.

Fix options to weigh: (i) rename the three style-factor tags out of the `eq_*` prefix
family entirely (e.g. `factor_low_vol`/`factor_momentum`/`factor_quality`, or move them to
`category='sensitivity'` alongside `equity_beta`, which is already correctly categorized
this way) so no identity-based prefix match can ever catch them regardless of source; or
(ii) make every identity-based consumer join `tag_vocabulary` and require
`measurement_type='definitional'` in addition to (or instead of) `source='human'`. Check
`docs/foundation/instrument-tag-registry.md`'s banned-alias rule (two tags must never share
a `factor_series`) for any interaction before renaming.

</details>

## Cross-refs

- Todo 379 (completed) -- the stopgap this follow-up extends.
- `docs/plans/2026-09-17-itr-source-filter-breadth-peer-grouping-design.md` -- full design
  doc + all three reviewers' complete findings.
- `docs/foundation/instrument-tag-registry.md` -- ITR spec; Known Gaps section already
  flags `discovery_oos_days` as unenforced and `sensitivity`/`macro_driver` tags as
  unconsumed -- this todo is the first concrete consumer design for those tags.
- `production/migrations/343_itr_measurement_gap_fixes.sql` -- the migration that made
  eq_low_vol/eq_momentum/eq_quality measurable.

## Status update 2026-09-18

Part 1 (materiality filter) is now **Phase 175**
(`.planning/phases/175-itr-materiality-filtered-empirical-tags-for-breadth-peer-gro/`) --
context gathered, researched, pattern-mapped, planned (5 plans in 4 waves), and plan-checked
through 2 revision rounds. **D-07's cross-AI review (Fable + Codex/AGY) is now complete and
the gate is cleared** -- see the update immediately below. Not yet executed; the Wave 1
`checkpoint:human-action` gate in plan 01 (P175-08) can now be answered "done" truthfully.
This todo stays `pending` -- the work has a home and is unblocked, but execution hasn't run.

**Update 2026-09-18 (Fable's D-07 pass on the finished plan set, after Codex/AGY's):** clears
the gate, with one precondition recorded here for whoever eventually scopes the deferred
consumer-cutover phase this todo's Part 1 explicitly defers to. `instrument_tags` has no
point-in-time history -- every column, including Phase 175's new Pass 4 evidence, reflects
"as of the most recent `TagCalibrator` run," overwritten in place. Because Pass 4 measures
against a symbol's full available history (R-07) rather than a fixed lookback, a
`passes_materiality=true` flag can rest on 3+ years of accumulated data. **Any future consumer
that uses `instrument_tags` to reconstruct historical group membership must not treat today's
flag as if it held throughout that full measurement window** -- doing so would bake
lookahead/survivorship bias directly into peer-group membership (a symbol only becomes
"eligible" retroactively once enough history has accumulated to prove it, backwards for a
backtest). This does not block Phase 175 itself (shadow-mode, no live consumer reads this
evidence yet) but must be resolved before the cutover phase lets any consumer use this
evidence for anything beyond the live "current membership" diagnostic Phase 175 ships. See
`docs/ideas/itr-extension-opportunities.md` #1 (point-in-time history) for the candidate fix.

Part 2 (`eq_*` naming collision) stays resolved as a documentation note, unchanged from the
re-verification above -- not folded into Phase 175, no action needed.

Also produced along this path, not part of Phase 175's scope: `docs/ideas/signal-
sensitivity-regime-interaction-primitives.md` (a downstream consumer-use idea for the
sensitivity/macro_driver tags this todo's materiality filter would admit -- Fable-reviewed
2026-09-18, revision-required, not yet promoted) and `docs/ideas/itr-extension-opportunities
.md` (a broader survey of ITR concept extensions, including one -- cross-tag collinearity
auditing -- that generalizes this todo's own orthogonalize-against-a-control-set approach
from tag-vs-proxy to tag-vs-tag). Neither blocks or is blocked by this todo; noted for
whoever picks either up next.

## Phase 175 status (2026-09-18)

Phase 175 executed 2026-09-23 and shipped Part 1 as shadow-mode measurement only. What
shipped: `TagCalibrator`'s Pass 4 materiality filter (`services/tag_calibrator.py`,
`decide_materiality()`/`is_materiality_eligible()`), migration 346 (eleven `instrument_tags`
evidence columns, the `instrument_tags_active` view, the `discovery_state` CHECK
constraint), all eleven `alpha.tag_calibrator.materiality.*` APR keys, and
`scripts/analysis/itr_materiality_shadow_diagnostic.py` (the D-03 shadow report, run once
against the live corpus: 2170 empirical pairs measured, 222 passing the statistical gate, 0
symbols currently admitted to any of the four enabled regime groups). Todos 125 and 126 are
both closed, folded into this phase as planned.

What did NOT ship: any consumer query change. `breadth_vol.py` (via
`cross_sectional_regime_model.py`'s group resolution) and that module's own
`_load_tags_by_symbol` still filter `source = 'human'` only, exactly as the todo 379
stopgap left them. This todo's remaining open item is the consumer-cutover decision --
gated on the shadow report above plus the D-07 cross-AI review and the user's own review,
not yet scheduled.

Part 2 (`eq_*` naming collision) is unaffected by this phase and remains a documentation
note requiring no fix, per the re-verification above.

## Triage 2026-09-26 (backlog review with the owner)

Deferred (per-feature regime stratification in ic_engine/lifecycle). Gate: reactivate if regime-stratified per-feature IC becomes part of a method in the research methods plan (todo 436). Thin regime x tf cells are the Phase 148 failure shape, so this does not restart by default.
