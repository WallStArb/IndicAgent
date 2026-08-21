# 311 - Build a mypy error baseline, then flip CI from report-only to blocking

## Fixed 2026-08-21

Took the recommended option 1 (`mypy-baseline` package). `.mypy-baseline.txt` generated via
`mypy src/ --ignore-missing-imports | mypy-baseline sync --sort-baseline` (803 errors, 1212
baseline lines across 158 files -- error count matches the todo's own 2026-08-14 figure closely,
minor drift expected over a week of intervening commits). CI's "Mypy" step now pipes through
`mypy-baseline filter`, `continue-on-error` removed -- a genuinely new type error now fails the
build; every pre-existing one stays silently grandfathered.

**Real bug caught before landing**: piping `mypy | mypy-baseline filter` under GitHub Actions'
default `bash -eo pipefail` shell would have failed the step on `mypy`'s own nonzero exit code
(803 pre-existing errors) regardless of what `mypy-baseline filter` reported -- defeating the
entire baseline mechanism, every run would fail unconditionally. Caught by testing the exact
pipeline locally with `pipefail` explicitly enabled before wiring it into CI. Fixed with
`set +o pipefail` immediately before the piped command, so the step's exit code is `mypy-baseline
filter`'s (0 = no new violations), not `mypy`'s.

**Verified**: (1) fresh sync against current `main` produces `new: 0` when immediately re-filtered
against itself; (2) a deliberately introduced new type error (`x: int = "not an int"` appended to
a scratch file, never committed) is correctly caught -- `filter` reports `new: 1`, exits 1, prints
"Your changes introduced new violations"; both checks re-run with `pipefail` on to match CI's
actual shell semantics. Also bumped CI's mypy install pin from the stale `>=1.14.0` to match
`requirements.txt`'s `>=1.19.0` (pre-existing drift between the two, unrelated to this fix but
directly adjacent -- a mismatched mypy version between local baselining and CI's install could
itself desync the baseline). `docs/reference/cheatsheet.md` updated with both the gated check and
the resync command. Full `tests/unit/`/ruff/black all green (no Python production code touched).

**Filed:** 2026-08-14
**Source:** Same audit pass that surfaced the vulture and Ring 0 boundary gaps. `[tool.mypy]` in
`pyproject.toml` is real, reasonably-scoped config (`disallow_untyped_defs = false` — pragmatic,
not demanding a mass-annotation retrofit) that was configured but never run anywhere — not in CI,
not in the pre-commit hook. This session added a CI step (`mypy src/ --ignore-missing-imports`)
but as `continue-on-error: true` (report-only), because `mypy src/ --ignore-missing-imports`
currently returns **795 errors across 158 files** (checked 462 source files, 2026-08-14) — blocking
on that today would fail every PR regardless of its actual diff, which trains people to ignore CI
red rather than trust it (worse than the current unwired state).
**Status:** pending, P2 — real value once a baseline mechanism exists; not urgent, the report-only
step already surfaces new obvious type errors in CI logs even unblocked.

## Approach

Same "grandfather existing, block new" shape as `[tool.ruff]`'s E501 baseline and vulture's
`tools/vulture_whitelist.py` (todo 309), but mypy has no built-in whitelist mechanism the way
vulture does. Two real options:
1. **`mypy-baseline` package** (pip, not currently a dependency) — snapshots current errors to a
   baseline file, CI step then only fails on errors not in the baseline. Closest match to the
   vulture pattern, one new dependency.
2. **Per-module `[[tool.mypy.overrides]]`** in `pyproject.toml` — set `ignore_errors = true` for the
   158 files with pre-existing errors, drop modules off the list as they're cleaned up. No new
   dependency, but coarser (silences a whole file, not just today's specific error lines — a new
   *different* error in an already-overridden file won't be caught either).

Recommend (1) — finer-grained, matches the precedent already set by vulture's whitelist approach
in the same session.

## Where

- `pyproject.toml`'s `[tool.mypy]` — existing config
- `.github/workflows/ci.yml`'s "Mypy (report-only)" step — flip `continue-on-error` to `false` once
  a baseline exists
- `docs/reference/cheatsheet.md` — already documents the bare invocation; update once gated
