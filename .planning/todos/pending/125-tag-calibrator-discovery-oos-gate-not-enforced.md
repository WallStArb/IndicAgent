# TagCalibrator's discovery_oos_days OOS-confirmation gate is computed but never enforced

**Found:** 2026-07-17, Phase 146 code review (CR-02, `146-REVIEW.md`).

`alpha.tag_calibrator.discovery_oos_days` (migration 238) is documented as "days required
before a newly discovered (gap-annotated) empirical tag is promoted to a live
`instrument_tags` row," and 146-04-PLAN.md's pass-3 spec says the same: "keep+no row ->
INSERT pending-OOS until `discovery_oos_days` of disjoint data confirm." The live
implementation (`services/tag_calibrator.py`, `_apply_decision`'s `insert_discovery`
branch) does not honor this: a first-pass discovery writes a fully live
`source='empirical'` row via `_UPSERT_EMPIRICAL_SQL` immediately, identical in every
queryable column (`weight`, `loading`, `p_value`) to a tag that has survived
`discovery_oos_days` of confirmation.

`_next_evidence` does compute a `discovery_state` field (`"pending_oos"` vs
`"confirmed"`) and stashes it in the `evidence` JSONB, but nothing anywhere in the
codebase reads that field to gate weight, gate downstream consumption, or otherwise treat
a `pending_oos` row differently — confirmed via `grep -rn "discovery_state" src/
services/` returning only the write site in `tag_calibrator.py` itself.

**Why not fixed inline during Phase 146 execution:** the two straightforward fixes both
require a design decision beyond a code-quality tweak:
- (a) Don't write the `instrument_tags` row until `elapsed_days >= discovery_oos_days` —
  but the current `first_measured_at` tracking mechanism lives in the *row's own*
  `evidence` JSONB, so withholding the row loses the only persistent state needed to
  track elapsed days across runs. Tracking `first_measured_at` via
  `instrument_annotations` instead (which is already written unconditionally on
  discovery) would work but needs its own query/parsing path added to `existing_by_pair`.
- (b) Write the row but add a `pending` boolean (or repurpose `weight`) that current/future
  consumers can filter on — requires a new `instrument_tags` column, i.e. a new migration.

Both are real schema/architecture changes, not a `/simplify`-scope fix. **Practical
urgency is currently zero**: WR-02 (companion finding, same review) confirms none of the
three live `instrument_tags` readers (`ic_engine.py`, `equity_regime_model.py`,
`cross_sectional_regime_model.py`) touch the `sensitivity`/`macro_driver` tags
TagCalibrator measures at all — they key off `eq_*`/`intl_*`/`fi_*`/`fx_*` exposure-tag
prefixes, all `measurement_type='definitional'`, untouched by this loop.

**Fix when picked up:** resolve WR-02 first (see companion todo) since the answer there
(canonical `instrument_tags_active` view, or per-call-site comment obligation) likely
shapes which of options (a)/(b) above is cheaper. Add a test asserting a fresh discovery
does NOT reach the same state as a `discovery_oos_days`-confirmed one until elapsed days
actually clear the gate — none of the existing `test_tag_calibrator.py` tests cover this
path.

**Addendum (2026-07-17, `/simplify` altitude pass):** the same underlying gap shows up as
a schema-depth issue, not just a missing-enforcement one. Migration 238 gives the *expiry*
half of the lifecycle (`consecutive_fails`, `valid_from`, `valid_to`, `passes_fdr`) real
typed columns with CHECK-able semantics, but the *discovery* half (`first_measured_at`,
`discovery_state: pending_oos|confirmed`) is packed into the `evidence` JSONB blob instead
(`_next_evidence`, `services/tag_calibrator.py`) — the code's own docstring says why ("no
dedicated schema column for discovery state exists; JSONB carries it"), an acknowledged
workaround, not an oversight. Whichever fix direction is chosen above, prefer promoting
`first_measured_at timestamptz` and `discovery_state text CHECK (discovery_state IN
('pending_oos','confirmed'))` to real `instrument_tags` columns in the same migration,
rather than leaving the same state machine split across a typed-column half and an
untyped-JSONB half — a future consumer needing `WHERE discovery_state = 'confirmed'`
currently has no index or schema guarantee, only a JSONB string-match with no constraint
stopping an invalid state from being written.
