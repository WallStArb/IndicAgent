# 297 - `src/api/routes/signals.py` coercion helpers violate the new function-naming abbreviation floor

**Filed:** 2026-08-10
**Source:** naming-system.md §4 Surface 7 authoring pass (REST API Routes / Functions / Constants gap-fill)
**Status:** RESOLVED 2026-08-11 -- renamed `_f`/`_s`/`_i`/`_ts` to `_to_float`/`_to_str`/`_to_int`/
`_to_timestamp` (word-boundary sed, all ~60 call sites), verified zero dangling old-name
references repo-wide, `/simplify` 4-agent pass clean (nothing to fix), `/code-review` found no
correctness issues. Full `tests/unit/` suite green. Altitude agent's repo-wide grep during this
pass found a same-shape violation outside scope -- filed as
[299](299-reset-pipeline-data-ts-single-letter-helper.md).

## What

`src/api/routes/signals.py` defines four module-private helpers named `_f`, `_s`, `_i`, `_ts`
(float/str/int/timestamp coercion). `docs/foundation/naming-system.md` §4 Surface 7 now states
explicitly that single/double-letter function names are prohibited outside the Surface 5
mathematical-variable exception — a coercion helper must be named by what it does
(`_to_float`/`_to_str`/`_to_int`/`_to_timestamp` or similar), never a bare letter. These four
predate that rule being written down but were real violations even under the pre-existing
Tier 3 Abbreviation Policy in spirit (§6) — just never caught because that policy's grep checks
target specific banned strings (`ctx`, `cfg`, etc.), not the general single-letter-name pattern.

## Why not fixed inline

Renaming these is a real code change (call-site updates throughout `signals.py`), not a doc
edit — deliberately out of scope for the naming-doc authoring pass that found it.

## Fix

Rename `_f`→`_to_float`, `_s`→`_to_str`, `_i`→`_to_int`, `_ts`→`_to_timestamp` (or equally
descriptive alternatives) in `src/api/routes/signals.py`; update all call sites in the same file.
Low risk, single-file, mechanical — good candidate for `/simplify` or a quick standalone pass.
