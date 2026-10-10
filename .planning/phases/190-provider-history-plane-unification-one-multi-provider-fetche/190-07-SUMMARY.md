# 190-07 SUMMARY

Executed 2026-10-10 by session indicagent-49 (autonomous, docs-only).

## What was done

- **Glossary** (`docs/foundation/glossary.md`, Bar data layer terms): seven entries —
  `ohlcv_history_fetcher`/`OHLCVHistoryFetcher`, `HistoryProvider`, `per-provider tier`,
  `canonical tier`, `no-data verdict`, `raw archive` (the per-supplier provenance store),
  and `source` (bar provenance)/`provider` with the ibkr_named-vs-ibkr ruling (same
  supplier, two label generations; stored labels are permanent history; derived buckets
  straddling a span boundary are blends — vendor-agreement audits compare per source,
  never inside a blended bucket). External-identity freeze noted on the fetcher entry.
- **Gotchas** (`docs/reference/gotchas.md`): the external-identity freeze list, the
  live-service migration pattern (additive-then-breaking, same-breath deploy, parity TSVs
  as the bar, post-cutover --reset-failures), the columnstore trigger-DDL refusal and its
  `session_replication_role` workaround, and the `config_state.version` NOT NULL trap.
- **Todo 526 closed** as absorbed (190-02 PK + floor seeds, 190-03 lookup, 190-06 parity
  PASS; heads verified 1,529 + 1,529 post-cutover); PRIORITIES.md row removed; the
  pending-path references left are the 190-07 plan's own instructions and 190-RESEARCH's
  historical snapshot.
- **190-ALPACA-DOWNSTREAM.md** updated for the T4 landing: the leaf and the nightly
  capture runner exist; the design rev 2 oneshot ban reconciled explicitly (the nightly
  runner is 521's T4 tail-capture shell on the shared engine, not a second campaign path);
  the six prerequisites for the unified-loop alpaca lane are listed.
- **CLAUDE.md** gained the raw-capture Key Rule (every bar stored under its supplier's
  label; nothing served is dropped; vendor onboarding cost named).

## Deviations

- The plan's Task 1 asked for five glossary entries; seven landed (the raw archive and
  source/provider entries carry the provenance ruling the owner requested the same day).
- The plan's downstream note assumed the Alpaca leaf did not exist; it does (T4, landed
  earlier the same day), so the note records reality plus the lane prerequisites.

## Verification

- Glossary pre-commit check clean on commit (baseline unchanged).
- `ohlcv_history_fetcher` present in the glossary; FETCHER_LOCK_NAME present in gotchas.
- 526 in completed/ with the closure note; PRIORITIES.md has no 526 pending row.
