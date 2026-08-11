# 299 - `scripts/infrastructure/backfill/infrastructure_reset_pipeline_data.py` has the same single-letter helper violation as todo 297

**Filed:** 2026-08-11
**Source:** `/simplify` altitude-agent pass on todo 297 (signals.py `_f`/`_s`/`_i`/`_ts` rename) --
a repo-wide grep run to confirm todo 297's scope was correctly bounded turned up this
unrelated hit outside `src/api/`.
**Status:** pending, not blocking

## What

`scripts/infrastructure/backfill/infrastructure_reset_pipeline_data.py:286` defines
`def _ts() -> str:` (a timestamp formatter) -- same shape as the `_f`/`_s`/`_i`/`_ts`
violations todo 297 just fixed in `src/api/routes/signals.py`. `docs/foundation/naming-system.md`
§4 Surface 7 prohibits single/double-letter function names outside the Surface 5
mathematical-variable exception; this wasn't caught by naming-system.md's original authoring
pass because that pass scoped its known-violations list to `src/api/routes/signals.py` only,
not a full repo sweep.

## Fix

Rename `_ts` to something descriptive (`_format_timestamp` or similar) in
`infrastructure_reset_pipeline_data.py`; update call sites in the same file. Same shape as
297's fix -- low risk, single-file, mechanical.

## References

- [297](297-signals-route-single-letter-coercion-helpers.md) (or `../completed/` once closed) --
  the sibling fix this todo mirrors.
- `docs/foundation/naming-system.md` §4 Surface 7 -- the rule both violations fall under.
