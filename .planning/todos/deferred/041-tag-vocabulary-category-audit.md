**Tracked under:** [112 — Stratification & Classification index](../pending/112-stratification-classification-index.md)

# Audit the 6-category tag_vocabulary taxonomy before building the calibrator against it

**Status (updated 2026-07-12):** Phase 144 was planned and executed (`144-CONTEXT.md` D-04) and
explicitly did NOT fold this in -- confirmed not blocking, since Phase 144's commodity/fx
`regime_group`s ship `enabled: false` regardless, so the `eq_*`/`commodity_energy_*` collision
this todo addresses (OIH/XLE) cannot fire yet. Still unscheduled: no phase or todo currently
owns "enable the commodity/fx regime_group entries," and this todo is the gate for that action
whenever it happens -- flipping `enabled: true` on either group without resolving this first
will raise `AmbiguousRegimeGroupError` at the next `ic_engine` run. Revive when commodity/fx
enablement is actually proposed, not on any fixed schedule.


**Found:** 2026-07-01, while walking through `regime_group`/`instrument_tags` design in
conversation. `docs/foundation/glossary.md` already defines all 6 `tag_vocabulary.category`
values (`exposure`, `sensitivity`, `factor_regime`, `cycle_position`, `signal_role`,
`macro_driver`) precisely and consistently — but glossary consistency doesn't mean the
taxonomy is right. Applying real scrutiny rather than accepting it as settled canon surfaced
three concrete problems, not just naming confusion.

## Findings

**`signal_role` is a relational fact miscast as a unary attribute.** Example already live in
the data: `SDOG` tagged `spread_leg` with evidence "VYM/SDOG broad vs sector-equal-weight yield
spread." That tag only means anything in relation to `VYM` — it's not a property of `SDOG`
alone. Storing it as a flat instrument-level tag discards the other half of the relationship
(spread_leg of *what*?). This likely doesn't belong in `instrument_tags` at all — it wants
either its own table describing instrument *pairs*/comparisons, or shouldn't be a persisted
classification at all and should just be a parameter on whatever specific analysis needs the
spread.

**`cycle_position` admits its own provisional status in its own glossary definition.** Quote:
"static institutional priors... never empirically validated by the TagAuditor; superseded by
HMM regime conditioning in Phase 2." A hand-asserted `early_cycle`/`late_cycle` tag directly
contradicts this project's own stated principles (segment by regime, empirical over
theoretical) — it's a hardcoded belief standing in for a measurement that regime-awareness is
explicitly supposed to replace, yet it's marked `Status: active` as if it's a stable peer of
the empirically-measured categories.

**`macro_driver` may be redundant with `sensitivity`, not independent.** The glossary's own
text for `macro_driver` says it's "empirically measured via beta against a canonical macro
proxy" — the exact same measurement procedure as `sensitivity`'s "empirically measured via beta
regression." The glossary tries to draw a philosophical line (causal force vs. magnitude of
response) but that distinction may not survive contact with how these actually get computed.
Needs verification that `oil_price` (`macro_driver`) and `oil_beta` (`sensitivity`) aren't just
the same regression wearing two different tag names.

**Two categories are solid and don't need re-litigating:** `exposure` and `sensitivity` map
cleanly onto standard factor-model practice (loadings vs. measured betas) and hold up under
scrutiny.

**Sector granularity does not exist today (verified 2026-07-12, live DB).** Of 80 active
`asset_class='equity'` instruments, exactly one sector-adjacent tag exists in
`instrument_tags`: `sector_rotation`, assigned to 11 symbols — a flat "this is a sector-rotation
ETF" flag, not a `sector_tech`/`sector_energy`/... taxonomy. Any future ask for finer-than-
equity/rates `regime_group`s (e.g. GICS-sector-level cross-sectional regimes) is blocked on this
audit producing real sector tags first, not just on todo 041's existing OIH/XLE collision fix —
worth noting alongside `signal_role`/`cycle_position`/`macro_driver` as a fourth concrete
scoping question for whoever picks this up: does the audit's action list also need "seed a real
sector taxonomy," or does that stay a separate follow-on?

## Why this matters now, not later

Todo 040 (Instrument Tag Calibrator, promoted to Phase 148) is about to build empirical
validation machinery *against* this 6-category taxonomy. If `signal_role` shouldn't be a tag at
all, or `macro_driver` turns out to be a relabeling of `sensitivity`, building the calibrator
first bakes the confusion into a real system rather than resolving it before the fact. This
audit should happen before or alongside Phase 148 planning, not after.

## Action

1. For `macro_driver`: pull the actual (or planned) measurement procedure for a `macro_driver`
   tag and a `sensitivity` tag on the same instrument/factor pair (e.g. `oil_price` vs
   `oil_beta` on an energy ETF) and check whether they're computationally distinct or the same
   regression under two names. If identical, collapse to one category.
2. For `cycle_position`: decide explicitly — either commit to it as a permanent category (and
   update the glossary to stop calling it provisional), or deprecate it now in favor of actual
   regime-conditioned analysis (per its own stated "superseded by HMM regime conditioning in
   Phase 2" — check whether that condition has already been met by the existing HMM/regime_group
   work and this category is simply stale).
3. For `signal_role`: evaluate whether it should be extracted into a separate relational
   structure (instrument pairs / spread definitions) rather than `instrument_tags`. If kept as
   a tag, its "evidence" should be required to name the counterpart instrument, not optional.
4. Update `docs/foundation/glossary.md` with whatever this audit concludes — glossary is not
   immutable; a category that fails scrutiny should be corrected there, not preserved because
   it's already documented.

**Blocked on:** nothing — this is a review/reasoning task, not gated on any other phase. Should
be sequenced before Phase 145 (renumbered from 148; Empirical Instrument Tag Calibrator)
commits engineering effort to validating all 6 categories as if they're equally well-formed,
and before commodity/fx `regime_group` entries are ever flipped `enabled: true` in Phase 144's
`alpha.regime.groups` (see updated Status note above).
