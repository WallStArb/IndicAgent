# 310 - Mirror glossary + counterfactual-ledger pre-commit checks into CI

**Filed:** 2026-08-14
**Source:** Same audit that surfaced the Ring 0 boundary CI gap (fixed directly this session, see
`.github/workflows/ci.yml`'s "Ring 0 boundary" step). `tools/pre-commit.hook` runs 9 checks; before
this session CI's `plugin-guards` job mirrored only 3 (plugin class naming, plugin file naming, I7
`regime_type`) despite its own header comment claiming to mirror "the bash checks in
.git/hooks/pre-commit so --no-verify can't bypass them." This session added a 4th (Ring 0 boundary)
and a 5th, in a separate `lint` job (duplicate test names). Checks 8 (glossary enforcement,
`tools/check_glossary.py`) and 9 (counterfactual-ledger enforcement, inline bash in the hook) are
still local-only — a commit with `--no-verify`, or any push that never ran the local hook (fresh
clone, CI runner, another contributor who never installed it), gets zero enforcement of either.
**Status:** pending, P2 — real gap, same shape as the Ring 0 one already fixed, not urgent (both
checks are narrow-scope: glossary only fires on banned-term usage, ledger only on new migration
files, so the exposure window per unprotected commit is small).

## Fix shape

- **Glossary (#8):** `tools/check_glossary.py` already takes a list of file paths and is
  self-contained — CI equivalent is `git diff --name-only origin/main...HEAD` (or
  `github.event.pull_request` base) filtered to `.py`/`.md`, piped into the same script. Slightly
  more involved than the Ring 0 mirror because it needs the diff base, not just a static grep over
  the whole tree.
- **Counterfactual-ledger (#9):** inline bash in the hook (`check_counterfactual_ledger`), scoped to
  staged `.sql` files under `migrations?/`. CI equivalent needs the same diff-against-base approach
  as glossary, checking new/changed migration files in the PR rather than "staged" files.

Both need a PR-diff base to mirror correctly (unlike Ring 0, which is a static whole-tree check) —
that's the main reason they weren't done in the same pass as the Ring 0 fix. `git diff
origin/${{ github.base_ref }}...HEAD` in the CI job is the standard pattern; confirm it works for
both `pull_request` and `push` trigger contexts before wiring.

## Where

- `tools/pre-commit.hook` — canonical check source (bash functions `check_glossary_terms`,
  `check_counterfactual_ledger`)
- `.github/workflows/ci.yml`'s `plugin-guards` job — where the CI mirror should land
- `tools/check_glossary.py` — the Python script check #8 already delegates to
