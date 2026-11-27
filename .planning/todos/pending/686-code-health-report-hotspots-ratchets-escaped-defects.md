---
status: pending
priority: P2
filed: 2026-11-27
source: owner ruling 2026-11-27 (constant refinement of the code is north star), docs/foundation/harness-improvement-sop.md "The code loop"
---

# Code health report: hotspots, ratchets and escaped defects

## What

The code loop needs its signals in one place. Today the ratchets exist piecemeal (`.mypy-baseline.txt`, `tools/vulture_whitelist.py`, `tools/glossary_baseline.json`, `tools/duplicate_test_allowlist.txt`, `scripts/ops/ops_complexity_census.py`), some without a no-growth check. Hotspots and escaped defects are not measured at all.

## Scope

1. `tools/code_health.py`, read-only, with no database:
   - Hotspots: per file under `src/`, `services/`, `scripts/` and `tools/`, from `git log` over N days, report churn, escaped defects (commits whose body says `fixes <sha>`, attributed to the files that sha touched) and lines. Ranked.
   - Ratchets: the current size of each baseline above, plus skipped-test count and unit-suite wall time (read from the last gate run if recorded, else omitted).
   - Escaped defects: a list of `fixes <sha>` pairs with days-to-escape.
   - Output is a table, plus `--jsonl` to append to `logs/harness/` beside todo 685's signals.
2. A no-growth check for each ratchet that lacks one: a unit test comparing the current size with a committed number, where a reduction updates the number in the same commit.
3. The lead turns the top three hotspots into refactor todos, claimable where outside every pin closure, each with its prediction.

## Gates

/simplify and /review. Unit tests run on a planted git repo (churn, `fixes <sha>` attribution) and planted baselines. The report never writes outside `logs/harness/`.

## Not blocking

Nothing on the counted-test path waits on this.
