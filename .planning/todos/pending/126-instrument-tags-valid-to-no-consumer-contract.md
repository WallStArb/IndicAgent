# No downstream consumer of instrument_tags filters on valid_to — expiry has no observable effect yet

**Found:** 2026-07-17, Phase 146 code review (WR-02, `146-REVIEW.md`).

Migration 238 introduces `valid_to` as the expiry marker for empirical `instrument_tags`
rows (written by `services/tag_calibrator.py`'s expire path). Every existing live reader
of `instrument_tags` selects the full table with no expiry filter:
- `services/ic_engine.py:2884` (`_build_symbol_regime_class`)
- `services/equity_regime_model.py:289` (breadth-universe query)
- `services/cross_sectional_regime_model.py:261` (`_load_tags_by_symbol`)

**Currently harmless:** none of these three readers key off the `sensitivity`/
`macro_driver` tags TagCalibrator actually measures (`rate_sensitive`, `credit_risk`,
`equity_beta`, etc.) — they use `eq_*`/`intl_*`/`fi_*`/`fx_*` exposure-tag prefixes, which
stay `measurement_type='definitional'` and are never touched by TagCalibrator's expire
path. So today, an expired empirical tag silently sitting in `instrument_tags` with a
non-NULL `valid_to` produces no wrong output anywhere.

**The gap:** nothing (view, helper function, or code comment at any of the three call
sites) establishes the obligation that a *future* consumer of the empirically calibrated
tags must add `AND valid_to IS NULL`. This is exactly the kind of contract that's easy to
violate silently once someone builds a new tag-membership query against
`rate_sensitive`/`credit_risk`/etc.

**Fix when picked up:** add a canonical `instrument_tags_active` view
(`SELECT ... FROM instrument_tags WHERE valid_to IS NULL`) and make it the required read
path for any future tag-membership query, or at minimum add a comment at each of the
three existing call sites noting the obligation. Resolving this likely informs the fix
direction for [[125-tag-calibrator-discovery-oos-gate-not-enforced]] (option (b) there —
a `pending` boolean — would naturally live behind the same view/contract this todo
establishes).
