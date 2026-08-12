---
status: fixed
priority: P2
filed: 2026-08-01
fixed: 2026-08-07
source: session review of commodity/fx regime-group disablement while discussing symbol-universe
  scope with user. Revised same day: fx confirmed collision-free and ready to enable; commodity
  sub-groups' thinness identified as a separate, near-term-fixable axis (unify into one
  `commodity` group) distinct from the equity-collision axis originally handed to todo 225.
---

# Commodity/FX regime-group re-enablement (todo 041's original taxonomy question, refreshed)

## Problem

`alpha.regime.groups` (migration 222) ships 4 of 6 groups disabled: `commodity_energy`,
`commodity_metals`, `commodity_agri`, `fx`. Both `commodity_momentum_ts.py` and
`fx_dollar_carry.py` are fully implemented, not stubs -- they've shipped `enabled: false`
since inception, gated on "todo 041" (tag exposure-vs-sensitivity taxonomy audit), referenced
across `ROADMAP.md`/`roadmap-decision-log.md`/Phase 144 docs but never filed as its own
standalone pending todo until this session.

This turned out to bundle two genuinely separate problems, now split apart:

**1. `fx` has no problem at all.** Verified (2026-08-01): `UUP`/`FXA`/`FXE`/`IBIT` carry zero
tag collisions with any other enabled group, on either Job 1 (`cross_sectional_regime_model.py`'s
peer-averaging) or Job 2 (`ic_engine.py`'s `_build_symbol_regime_class` routing). It can be
enabled today with zero code changes and zero crash risk. The only reason it hasn't happened is
sequencing -- see Fix.

**2. Commodity groups have two independent problems, not one.**
- **Equity-tag collision (Job 2, single-membership routing):** `OIH`/`XLE`/`XOP`/`AMLP`
  (energy) and `GDX` (metals) all carry both an `eq_*` tag (matching the enabled `equity`
  group) and a `commodity_*` tag simultaneously. `ic_engine.py`'s router requires exactly one
  group per symbol and raises `AmbiguousRegimeGroupError` on multi-match by design (never
  silently picks one). These 5 symbols are *already* routed to `equity` today (since `equity`
  is enabled and they match it); enabling any commodity sub-group makes them double-eligible
  with no resolution rule. Originally handed to
  [225](225-multi-vector-systematic-regime-join-hybrid-sensitivity-symbols.md) -- **resolved
  differently, see Resolution below.**
- **Group thinness (Job 1, peer-set size):** independent of the collision question above, the
  three commodity sub-groups are each too small on their own to compute a reliable
  cross-sectional signal. `commodity_energy` had 4 members (all 4 collide with equity anyway),
  `commodity_metals` had 5 (only `GDX` collides), `commodity_agri` had exactly 1 (`DBA` --
  unusable alone). `commodity_momentum_ts.py`'s own docstring targets 4-8 instrument peer
  groups; `commodity_agri` didn't clear that bar at all.

Bonus finding while checking group membership: `DBC` (Invesco DB Commodity Index -- the
cleanest possible commodity holder, GSCI-weighted, zero equity-tag collision) carried a
`commodity_broad` tag that wasn't matched by *any* group's `tag_filter`. Routed to nothing, a
pure oversight independent of both problems above.

## Resolution (2026-08-07)

**Migration 306** shipped all of this in one pass, live and confirmed:

1. **`fx`**: closed 2026-08-06 (see below) -- restated here for completeness.
2. **Unified `commodity_energy`/`commodity_metals`/`commodity_agri` into one `commodity`
   group.** Re-checking membership at execution time (not the 2026-08-01 snapshot below --
   the universe expansion 111->231 instruments grew this materially) found **27 members, not
   the ~11 originally estimated** -- the universe expansion between filing and execution added
   several new single-name commodity-producer equities (`COP`, `CVX`, `BHP`, `ADM`, `CTVA`,
   etc.) that now carry `commodity_*` categorical tags too.
3. **`DBC`'s routing gap fixed** -- `commodity_broad` added to the unified group's `tag_filter`.
4. **Equity-tag collision resolved WITHOUT todo 225.** Rather than wait on 225's
   gradient-conditional partial-IC mechanism (which ran its own pilot 2026-08-01 and came back
   negative -- no evidence justified building it), `ic_engine.py`'s
   `_build_symbol_regime_class` gained a new, explicit, tested `exclude_symbols` field: a
   small, named, auditable carve-out (NOT a silent precedence rule -- `AmbiguousRegimeGroupError`
   still fires for any other, undocumented collision). `AMLP`/`GDX`/`OIH`/`XLE`/`XOP` are named
   in the `commodity` group's `exclude_symbols`, so they keep routing to `equity` for Job 2's
   single-label regime-stratified IC -- unchanged from today's live behavior, zero regression.
   Job 1 (`cross_sectional_regime_model.py`'s peer-averaging) has no single-membership
   constraint and was NOT given this exclusion -- all 5 symbols remain full peers in both the
   equity breadth calc and the commodity momentum calc, no data dropped there. This closes step
   5/6 below on different terms than originally scoped; 225 is no longer a blocker for anything
   (see its own file for the resulting note).
5. **Group enabled and confirmed populated**, not just config-flipped -- lesson from the fx
   near-miss below applied directly: `cross_sectional_regime_model.py` was re-run in the same
   session immediately after the config flip. Live confirmed via `market_regimes`:
   `commodity` now has 564,439 rows across 5m/15m/1h/1d, 27 symbols, real labels
   (`up_primary_contango`, `down_secondary_neutral`, etc. -- 4 momentum x 2 term-structure
   states observed).

**Bug found and fixed as a side effect of actually enabling the group for the first time
ever:** `commodity_momentum_ts.py` shipped `enabled: false` since inception and had literally
never run against real peer data before this session. Its `compute()` force-relabeled the
cross-sectional median onto one arbitrary peer's raw timestamp index via `.set_axis()`, which
requires an *exact* length match -- silently fine (or silently wrong, never distinguished)
when peers happened to share identical backfill depth, loud-crash the first time real peers
didn't (the 27-member group spans very different tenures). Fixed by deleting the relabel and
letting `pd.concat(...).median(axis=1)`'s natural union-aligned index carry through -- this
exactly mirrors `breadth_vol.py`'s already-correct `_compute_breadth` pattern, so the two
sibling regime-signal modules are now consistent instead of one carrying a latent bug.
Regression test added: `test_peers_with_different_history_lengths_does_not_raise`. Full detail:
commit `d6623b31`.

**Item 4 from the original Fix list (re-split `commodity` back into energy/metals/agri once
each sub-group independently clears the 4-8 instrument floor) stays open as forward-looking
guidance, not a blocker** -- track against the long-term universe-scaling direction, no fixed
date. Not worth its own todo until the universe grows enough to make it concrete.

### fx closure (2026-08-06, restated for the historical record)

**DONE 2026-08-01** (migration 280): `fx` flipped to `enabled: true` in `alpha.regime.groups`,
plus `dual_write_symbol_hmm: true`. **FULLY CLOSED 2026-08-06**: the config flip sat unfollowed
for 4 days -- nobody ran `cross_sectional_regime_model.py`, so `market_regimes` had zero `fx`
rows at any tf, which meant `ic_engine.py`'s startup gate (`_assert_prerequisites`) crash-loud-
failed for EVERY invocation project-wide since 2026-08-02, not just fx-routed ones -- discovered
while unblocking todo 243's CTF refresh. Ran `cross_sectional_regime_model.py` for real: `fx`
now has 498,302 rows across 5m/15m/1h/1d. **This is exactly the failure mode this todo's
commodity-enablement step guarded against by re-running the model in the same session as the
2026-08-07 config flip, not deferring it.**

## Why this matters

- Symbols tagged `commodity_*` (27 as of 2026-08-07, up from the original ~11-symbol estimate)
  now get real regime-stratified IC instead of pooled-only -- closes a real measurement gap
  relative to equity/rates/fx.
- The interim `exclude_symbols` carve-out is a general, reusable router primitive now, not a
  one-off hack -- any future symbol with genuine dual-categorical membership can use the same
  documented mechanism instead of forcing a choice between deleting real tag data or building
  a large multi-membership redesign.
- The `commodity_momentum_ts.py` bug would have hit ANY future attempt to enable this group at
  meaningful scale, regardless of which session did it -- worth having surfaced now, via a
  real run, rather than assumed safe from the old 11-symbol read.

## References

- `production/migrations/222_regime_group.sql` -- original schema/APR seed, groups shipped
  disabled by design
- `production/migrations/280_fx_regime_group_enablement.sql` -- fx enablement
- `production/migrations/306_commodity_regime_group_unification.sql` -- this todo's resolution
- `src/intelligence/regime_signals/commodity_momentum_ts.py`,
  `src/intelligence/regime_signals/fx_dollar_carry.py` -- signal modules
- `services/ic_engine.py` (`_build_symbol_regime_class`, `AmbiguousRegimeGroupError`) --
  router; `exclude_symbols` field added here
- `tests/unit/test_ic_engine_routing.py`, `tests/unit/test_regime_signals_commodity_momentum_ts.py`
  -- new/updated coverage
- `docs/research/roadmap-decision-log.md` -- "Why commodity/fx enablement is blocked" + "Why
  OIH/XLE staying in equity breadth ... isn't a blocker" decision notes (now historical)
- `.planning/phases/146-empirical-instrument-tag-calibrator/146-CONTEXT.md` --
  confirms todo 041 was folded into the canonical design doc, not resolved as its own decision
- `.planning/todos/pending/225-multi-vector-systematic-regime-join-hybrid-sensitivity-symbols.md`
  -- no longer blocking anything from this todo; still open as an independent, currently
  deprioritized (P3) measurement-layer idea
- Live verification queries used: `instrument_tags`/`market_regimes` row counts, both cited
  inline above; commit `d6623b31`
