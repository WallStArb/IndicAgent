---
phase: 174-universe-expansion-single-name-breadth-scaling-targeted-etf
plan: 04
subsystem: infra
tags: [data-sourcing, russell-3000, iwv, universe-expansion, ibkr, survivorship-bias]

# Dependency graph
requires: []
provides:
  - "scripts/infrastructure/universe_expansion_fetch_iwv_holdings.py: fetch_holdings()/parse_holdings() for Plan 08's stratified sampling script to import directly"
  - "Confirmed real IWV holdings file schema (header index 9, verbatim column list, filler/rejection counts) as recorded fact, not assumption"
  - "Market-cap decision for Plan 08: use `Market Value` column directly, no AUM derivation needed"
  - "Delisted-constituent feasibility verdict (UNRESOLVED) for todo 376, with a concrete next step"
affects: [174-08-stratified-sampling, 174-12-backfill-execution]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Defensive external-file fetch: status + content-type + body-plausibility + <html body-sniff validation before anything is written to disk"
    - "Header-schema-drift fails loud (ValueError naming expected vs actual) rather than silently half-parsing an untrusted external file"
    - "Counts (n_rows_raw/n_filler_dropped/n_rejected/n_accepted) attached via df.attrs + logged once, never per-row"

key-files:
  created:
    - scripts/infrastructure/universe_expansion_fetch_iwv_holdings.py
    - tests/unit/scripts/test_universe_expansion_fetch_iwv_holdings.py
    - docs/research/russell3000-sourcing-and-delisted-feasibility.md
  modified:
    - .planning/todos/pending/376-survivorship-bias-active-only-universe-no-owner.md

key-decisions:
  - "Real IWV download endpoint is /latest-holdings.csv, not the plausible-looking .ajax?fileType=csv endpoint (which serves an HTML bot-mitigation shell at HTTP 200 with a misleading text/csv Content-Type)"
  - "Market Value column used directly as the stratification variable -- no AUM-based derivation needed, since it is linearly proportional to true market cap for a cap-weighted index"
  - "Delisted-constituent feasibility verdict: UNRESOLVED (not NOT OBTAINABLE) -- free sources confirmed absent, IBKR untested per plan's explicit gateway-down instruction, paid vendors exist but untested"

patterns-established:
  - "Content-Type header is not trustworthy for discriminating a real file from a bot-mitigation challenge page on this endpoint class -- body content sniffing is the authoritative check"

requirements-completed: [D-02, D-03]

# Metrics
duration: 45min
completed: 2026-09-15
---

# Phase 174 Plan 04: Russell 3000 Sourcing Schema + Delisted-Data Feasibility Summary

**Built a working iShares IWV holdings fetch/parse module (real endpoint found live, not the guessed one), confirmed the real file's schema and market-cap column choice, and returned an UNRESOLVED (not blocking) verdict on delisted-constituent data feasibility.**

## Performance

- **Duration:** ~45 min
- **Completed:** 2026-09-15T12:45:36Z
- **Tasks:** 3/3 completed
- **Files modified:** 4 (3 created, 1 modified)

## Accomplishments

- `fetch_holdings()`/`parse_holdings()` in `scripts/infrastructure/universe_expansion_fetch_iwv_holdings.py` — downloads and defensively parses the real iShares IWV Russell 3000 holdings export, returning a validated `symbol`/`name`/`market_cap` frame
- Found and fixed a real-world data-sourcing problem live: the plausible-looking `.ajax?fileType=csv` endpoint serves an HTML bot-mitigation shell (not the real file) even at HTTP 200 with a `text/csv` Content-Type; the actual working endpoint (`/latest-holdings.csv`) was found by inspecting the real product page's download link
- 10 unit tests covering preamble skipping, header-drift failure, filler-row dropping, SQL-metacharacter ticker rejection, malformed/negative/NaN market cap rejection, thousands-separator/`$` handling, the 3-column contract, and ticker-format edge cases — all pass against inline fixtures, plus independently verified against the real 2,564-row downloaded file
- Delisted-constituent data feasibility (todo 376 action item 1) empirically investigated: Yahoo Finance's free chart API confirmed structurally absent for 3 named delisted tickers (SIVB, TWTR, ATVI — explicit "symbol may be delisted" 404 for all 3); stooq.com blocked by a JS proof-of-work challenge; live IBKR deliberately not tested (`ib-gateway` down, not this task's restart to make). Verdict: UNRESOLVED, with a named concrete next step, and an explicit statement that this does not change Phase 174's active-only pilot scope (D-03)

## Task Commits

Each task was committed atomically:

1. **Task 1: Fetch the real IWV holdings export and record its actual column schema** - `1dea4d2ea` (feat)
2. **Task 2: Defensive parser with per-row schema and type validation** - `265be244f` (test)
3. **Task 3: Delisted-constituent data feasibility verdict (todo 376 action item 1)** - `2f9c44061` (docs)

_Note: Task 1's commit includes a fully-implemented `parse_holdings()` (not a stub) since building it was required to gather the real file's schema facts for this plan's own deliverables; Task 2 added the test suite against it. No separate refactor commit was needed._

## Files Created/Modified

- `scripts/infrastructure/universe_expansion_fetch_iwv_holdings.py` — `fetch_holdings()` (defensive download with status/content-type/body-plausibility/`<html`-sniff validation), `parse_holdings()` (header-schema-drift-checked, filler-dropping, ticker/market-cap-validating parser), `main()` (argparse entry point, `JOB_COMPLETED_TOTAL`/`flush_and_shutdown_metrics` oneshot contract)
- `tests/unit/scripts/test_universe_expansion_fetch_iwv_holdings.py` — 10 unit tests against inline `tmp_path` fixtures reproducing the real file's exact preamble/header shape
- `docs/research/russell3000-sourcing-and-delisted-feasibility.md` — records both this plan's data-sourcing decision (Market Value as the market-cap column, no derivation) and the delisted-data feasibility verdict
- `.planning/todos/pending/376-survivorship-bias-active-only-universe-no-owner.md` — updated with action item 1's UNRESOLVED verdict and a link to the new research doc

## Decisions Made

- **Real download endpoint is `/latest-holdings.csv`, not the guessed `.ajax` endpoint.** Found by fetching the live product page and grepping its own download-link `href`, after the guessed endpoint was confirmed (live, this session) to serve an HTML SPA shell despite a 200 status and a `text/csv` Content-Type — Content-Type alone is not a reliable signal for this endpoint class; the `<html` body-sniff check is what actually catches it.
- **`Market Value` used directly as the market-cap proxy, no AUM derivation.** It is the fund's dollar position in each holding, not the company's literal market cap — but for a cap-weighted index like IWV this is linearly proportional to true market cap by a single constant scalar across every row, which is sufficient for Plan 08's relative-decile stratification. Documented as a caveat for any future consumer that needs absolute company-level market cap instead.
- **Delisted-data verdict: UNRESOLVED, not NOT OBTAINABLE.** The free/convenience path is confirmed dead (Yahoo's own API says so explicitly); the two real candidate paths (IBKR once `ib-gateway` is back, or a paid survivorship-bias-free vendor) were not tested — testing IBKR required restarting a container explicitly out of this task's scope per the plan.

## Deviations from Plan

None — plan executed exactly as written. The plan's Task 1 action anticipated exactly the failure mode found (a bot-mitigation-served challenge page) and specified the defensive validation checks (status/content-type/size/`<html` sniff) that caught it live; no improvisation was needed beyond following those checks as written.

## Issues Encountered

- **Worktree had no `.venv`.** Symlinked `.venv -> /home/bg/dev/indicagent/.venv` (the main repo's existing venv) at the start of this session — a known GSD-worktree gap (venvs are not tracked in git, so a fresh worktree checkout doesn't have one). Not a plan deviation; environment setup only.
- **Guessed IWV download endpoint didn't work.** Resolved by fetching the live product page and finding the real download link directly (see Decisions above) — this was expected investigative work under Task 1's action ("Run the script against the live issuer endpoint and record... the following concrete facts about the real file"), not a blocker requiring a deviation rule.
- **Both fallback sources named in the plan's `<interfaces>` block (Barchart, StockAnalysis.com) were checked and found to be JS-rendered SPA shells, not raw file endpoints, when probed directly.** Not pursued further since the primary iShares source worked once the correct endpoint was found — recorded here for anyone revisiting the fallback path later.

## User Setup Required

None — no external service configuration required. (No API keys or accounts were created for the delisted-data feasibility investigation; that investigation deliberately used only already-public, unauthenticated endpoints.)

## Next Phase Readiness

- Plan 08 (stratified sampling) can import `fetch_holdings()`/`parse_holdings()` directly and has a confirmed, evidence-backed market-cap column decision — no schema guesswork remains.
- Plan 10 (backfill execution, which owns the `ib-gateway` restart) should include the delisted-data IBKR test named in this plan's research doc as a cheap follow-on check once the gateway is back up, if todo 376 is picked up again.
- No blockers for Plan 08 or Plan 12 from this plan's work.

---
*Phase: 174-universe-expansion-single-name-breadth-scaling-targeted-etf*
*Completed: 2026-09-15*

## Self-Check: PASSED

- FOUND: scripts/infrastructure/universe_expansion_fetch_iwv_holdings.py
- FOUND: tests/unit/scripts/test_universe_expansion_fetch_iwv_holdings.py
- FOUND: docs/research/russell3000-sourcing-and-delisted-feasibility.md
- FOUND commit: 1dea4d2ea
- FOUND commit: 265be244f
- FOUND commit: 2f9c44061
