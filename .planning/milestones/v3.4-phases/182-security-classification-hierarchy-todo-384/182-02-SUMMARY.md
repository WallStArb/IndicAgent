---
phase: 182-security-classification-hierarchy-todo-384
plan: 02
subsystem: providers
tags: [ibkr, ib_async, classification, sourcing, data-quality]

# Dependency graph
requires: []
provides:
  - "IBKRProvider.fetch_contract_classification (src/providers/ibkr.py)"
  - "config/classification/ibkr_classification_candidates.csv -- fresh, committed IBKR sourcing data for all 168 single_name_equity symbols"
affects: [182-03]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "New ib_async read path added next to qualify_instrument, not inside it -- keeps the hot connect path untouched"
    - "One-off sourcing script writes an atomic (temp+os.replace) candidate CSV, never a live-computed classification (D-06's 'committed as data' rule)"

key-files:
  created:
    - tests/unit/providers/test_ibkr_contract_classification.py
    - scripts/infrastructure/classification_ibkr_sourcing.py
    - config/classification/ibkr_classification_candidates.csv
  modified:
    - src/providers/ibkr.py

key-decisions:
  - "fetch_contract_classification raises ValueError naming the symbol on disagreeing multi-listing triples, rather than silently picking the first -- ambiguity must be loud (plan's explicit behavior spec)."
  - "No skip-reason escape hatch or fallback path anywhere in the sourcing script's per-symbol handling; every failure mode (no_details/ambiguous/timeout/error) is recorded as a CSV row status, and the script exits 2 (not 0) if any row is non-ok, so a silent partial run can never look like full coverage."

requirements-completed: [D-06]

# Metrics
duration: 8min
completed: 2026-09-25
---

# Phase 182 Plan 02: IBKR classification candidate sourcing (D-06) Summary

**New `IBKRProvider.fetch_contract_classification` method plus a one-off sourcing script that fetched fresh industry/category/subcategory/longName for all 168 single_name_equity symbols in a single live run -- 168/168 ok, zero failures, committed as `config/classification/ibkr_classification_candidates.csv`.**

## Performance

- **Duration:** ~8 min (test-first RED at 08:47:24, GREEN at 08:48:20, live sourcing run + CSV commit at 08:52:30)
- **Tasks:** 2 (Task 1 split RED/GREEN per its `tdd="true"` flag)
- **Files modified:** 3 created, 1 modified (plus the CSV, effectively a 4th created file)

## Accomplishments
- `ContractClassification` frozen dataclass + `IBKRProvider.fetch_contract_classification(symbol)` in `src/providers/ibkr.py`, reusing `qualify_instrument`'s exact `Stock(SMART, USD)` construction and `asyncio.wait_for(..., timeout=_CONTRACT_DETAILS_TIMEOUT_SEC)` wrapper (F4 rationale). 8 passing unit tests covering: single-listing success, contract shape, empty details -> None, agreeing multi-listing dedup, disagreeing multi-listing -> loud `ValueError` naming the symbol, missing-attribute default to `""`, pre-connect `RuntimeError`, and timeout propagation (uncaught).
- `scripts/infrastructure/classification_ibkr_sourcing.py`: queries `instrument_tags` for every `single_name_equity` symbol (168, DB-verified before the run), connects via `IBKRProvider` on a dedicated client ID (47, free -- no collision with the concurrently-running nightly backfill on client ID 45), fetches classification for each symbol sequentially without aborting the loop on any single failure, and writes an atomic (temp-file + `os.replace`) CSV.
- **Live run result: 168/168 `ok`, 0 `empty`/`no_details`/`ambiguous`/`timeout`/`error`.** Exit code 0. All 40 pilot-cohort symbols (ACTG...WSHP) present and `ok`.
- CSV columns exactly `symbol,industry,category,subcategory,long_name,status,detail,fetched_at` per the plan's automated verify command; every row's `fetched_at` is from this run (2026-09-25, not a reuse of the stale 2026-09-18 probe, RESEARCH.md Pitfall 4).
- `IBKRProvider`/`ibkr.py` existing unit test suites (`test_ibkr_equity.py`, `test_ibkr_provider.py`) still green after the addition.

## Task Commits

1. **Task 1a: Failing tests for fetch_contract_classification (RED)** - `126f68319` (test)
2. **Task 1b: Implement ContractClassification + fetch_contract_classification (GREEN)** - `3ca4c583f` (feat)
3. **Task 2: Sourcing script + live run + committed candidates CSV** - `522109808` (feat)

## Files Created/Modified
- `tests/unit/providers/test_ibkr_contract_classification.py` - 8 pure-unit tests, mocked `_ib`, no live connection
- `src/providers/ibkr.py` - `ContractClassification` dataclass + `fetch_contract_classification` method, added next to `qualify_instrument`
- `scripts/infrastructure/classification_ibkr_sourcing.py` - one-off sourcing script (argparse `--out`/`--client-id`, DB query, per-symbol fetch loop, atomic CSV write, `job_completed_total` OTel emission)
- `config/classification/ibkr_classification_candidates.csv` - 168 rows, all `status=ok`, committed as reviewable data

## Decisions Made
- Client ID 47 chosen and verified free at run time (`ps aux | grep client-id` showed only the nightly backfill on 45; no collision).
- The script emits `job_completed_total{job="classification-ibkr-sourcing", status=...}` via OTel, matching the sibling `universe_expansion_stratified_sourcing.py`'s one-off-script pattern (D-06 of the OTel Health Contract), even though this script is not a systemd unit.
- Exit code 2 is reserved for "wrote a file but some rows are non-ok" (did not fire this run -- all 168 were ok); exit 3 for a zero-row DB query; exit 4 for a gateway connection failure, both of which skip the CSV write entirely.

## Deviations from Plan
None - plan executed exactly as written. The gateway was up and logged in on the first attempt (no rerun needed), so the "rerun once on exit 2" contingency in the plan's Task 2 action did not need to be exercised.

## Issues Encountered
None.

## User Setup Required
None - no external service configuration required. The `ib-gateway` Docker container was already running and logged in.

## Next Phase Readiness
- Plan 03 can now read `config/classification/ibkr_classification_candidates.csv` directly -- full 168/168 coverage, no gateway blocker, no non-ok rows to special-case.
- `IBKRProvider.fetch_contract_classification` is available for any future re-sourcing run (e.g. if the universe grows) with the same client-ID-47 convention.

---
*Phase: 182-security-classification-hierarchy-todo-384*
*Plan: 02*
*Completed: 2026-09-25*

## Self-Check: PASSED

All created files verified present (`tests/unit/providers/test_ibkr_contract_classification.py`,
`scripts/infrastructure/classification_ibkr_sourcing.py`,
`config/classification/ibkr_classification_candidates.csv`, this SUMMARY.md). All commit hashes
(`126f68319`, `3ca4c583f`, `522109808`) verified present in `git log --oneline --all`. Full
`.venv/bin/pytest tests/unit/ -q` suite re-run green (2 pre-existing, unrelated skips only,
matching Plan 01's summary).
