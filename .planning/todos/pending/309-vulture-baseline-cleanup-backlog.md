# 309 - Triage the vulture dead-code baseline (1136 whitelisted findings)

**Filed:** 2026-08-14
**Source:** Wiring vulture into CI (`pyproject.toml`'s `[tool.vulture]`, `.github/workflows/ci.yml`'s
"Vulture (dead code)" step). Vulture was in `requirements.txt` since before this session but had
zero config, zero CI/pre-commit wiring — pure dead weight. Fixed this session: config + CI gate
added, but the entire pre-existing findings set (1136 items) was frozen into
`tools/vulture_whitelist.py` via `vulture --make-whitelist` rather than triaged by hand — same
"grandfather existing, block new" pattern this project already uses for `[tool.ruff]`'s E501
baseline. CI now blocks any *new* dead code but is silent on the existing backlog.
**Status:** pending, P2 — real value (some fraction of 1136 is genuine dead code, not false
positive), not urgent (CI gate on new code is the load-bearing protection now).

## What's in the backlog

833 unused variable / 117 unused method / 104 unused function / 52 unused attribute / 25 unused
class / 4 unused property / 1 unused import, all at vulture's default 60% confidence except 8
items at 90-100%. Spot-checking during this session found the "unused variable" bucket dominated
by a known vulture false-positive pattern: dataclass/Pydantic field declarations (e.g.
`src/intelligence/schemas.py`'s `model_config`, `rsi_bars_in_extreme`, `prior_session_low`) that
vulture can't distinguish from real unused locals because it doesn't understand attribute access
through `model_validate`/dynamic dispatch. Real dead code is almost certainly mixed in among the
false positives — not yet separated.

## Approach

Work through `tools/vulture_whitelist.py` in batches (by file or by directory), for each entry
either: (a) delete the entry + the dead code it names, or (b) confirm real via dynamic dispatch
(dataclass field, plugin registry lookup, `getattr`, pytest fixture, etc.) and leave it whitelisted
with a comment noting why. `--min-confidence 90` first pass is the highest-signal subset (currently
only 7 items — check those first, they're likeliest to be real). One already fixed this session as
a freebie found while wiring the tool: `src/intelligence/ai/context.py`'s `if False else` dead
ternary branch (100% confidence — genuinely unreachable code, not a false positive).

## Where

- `tools/vulture_whitelist.py` — the frozen baseline
- `pyproject.toml`'s `[tool.vulture]` — config (paths, exclude, min_confidence)
- `.github/workflows/ci.yml`'s "Vulture (dead code)" step — the gate itself
