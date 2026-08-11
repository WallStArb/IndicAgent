# 299 - Two more single-letter `_ts()` helper violations outside todo 297's scope

**Filed:** 2026-08-11
**Source:** `/simplify` altitude-agent pass on todo 297 (signals.py `_f`/`_s`/`_i`/`_ts` rename) --
a repo-wide grep run to confirm todo 297's scope was correctly bounded turned up this
unrelated hit outside `src/api/`.
**Status:** pending, not blocking

## What

`scripts/infrastructure/backfill/infrastructure_reset_pipeline_data.py:286` defines
`def _ts() -> str:` (a timestamp formatter). `docs/foundation/naming-system.md` §4 Surface 7
prohibits single/double-letter function names outside the Surface 5 mathematical-variable
exception; this wasn't caught by naming-system.md's original authoring pass because that pass
scoped its known-violations list to `src/api/routes/signals.py` only, not a full repo sweep.

A second instance of the same pattern surfaced during a later altitude-review pass (2026-08-11,
`/simplify` on todo 297's completion): `tests/unit/intelligence/test_smc_amd_cycle.py:168`
defines `def _ts(day: date, hour: int) -> datetime:`. Test-only helper, no production-code
impact, but same shape -- worth including in this todo's scope rather than filing separately.

## Fix

Rename both `_ts` helpers to something descriptive (`_format_timestamp`/`_to_datetime` or
similar) and update call sites in each file. Low risk, mechanical, two files.

## References

- [297](297-signals-route-single-letter-coercion-helpers.md) (or `../completed/` once closed) --
  the sibling fix this todo mirrors.
- `docs/foundation/naming-system.md` §4 Surface 7 -- the rule both violations fall under.
