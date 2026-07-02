---
**Created:** 2026-07-01
**Area:** intelligence / ensemble
**Type:** hardening
**Priority:** P3
**Effort:** trivial (migrate-as-you-go)
**Risk:** low
**Gate:** none
---

# 043 — APR-backed ensemble stale-weight cliff

`services/ensemble_trainer.py:509` hardcodes the equal-weight staleness fallback inline:

```python
if days_since > 90:
    # Equal-weight fallback: IC scores are too stale to trust the weight ordering.
    aged_quality_weights = np.full(len(quality_weights), 1.0 / max(1, len(quality_weights)))
```

Its sibling `weight_half_life_days` (used two lines below for the exponential decay itself) is
already APR-backed. The `90` cliff is not — an architecture violation per CLAUDE.md's
migrate-as-you-go mandate (any hardcoded threshold in `src/`/`services/` must be migrated in
the same session it's encountered; capturing as a todo here since this was found during the
2026-07-01 v3 architecture review, not during active work on this file).

## Fix

Add `alpha.ensemble.weight_stale_max_days` (int, default 90, `[conventional]`) to
`config_schema`/`config_state` in a migration; read via `cfg.get_sync(...)` at the point of use
alongside the existing `weight_half_life_days` load. No behavior change at default value.

## Reference

Found by the Fable-5 architecture review agent, `.planning/research/2026-07-01-v3-architecture-review.md` §1/§6 — batch into the first commit of whichever phase touches `ensemble_trainer.py` next (the planned "Ensemble Weighting Methodology" phase, if the user approves it, is the natural landing spot).
