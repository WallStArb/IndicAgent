# 297 - `src/api/routes/signals.py` coercion helpers violate the new function-naming abbreviation floor

**Filed:** 2026-08-10
**Source:** naming-system.md §4 Surface 7 authoring pass (REST API Routes / Functions / Constants gap-fill)
**Status:** pending, not blocking

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
