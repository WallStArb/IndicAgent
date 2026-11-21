---
status: pending
priority: P0
filed: 2026-11-21
source: lead, 2026-11-21 (total-return panels cover only the 1,509 active members; recon and Phase A below)
owner: lead
---

# Massive as a dividend source: the reader, the load and the disclosure (phase B)

## What

A total-return panel prices a symbol only inside its dividend coverage; Yahoo covers the 1,509 active members and none of the 11,348 inactive ones, so the first counted daily test would run on survivors. Massive's 2026-11-10 dividend capture (733,810 events) covers dead names: it adds 36,339 dead member-years (61,747 against 24,642 member-years in all). Phase A is on main (`806c06f20`: migration 608 written and not applied, the writer `--sources massive`, the pure rule `src/intelligence/bars/massive_dividends.py`, the measurement `docs/plans/2026-11-21-massive-dividend-coverage-rule.md`). The writer refuses a live load while `MASSIVE_READERS_READY` is False.

## Scope (phase B)

1. Fix the two readers that do not filter `dividend_events` by source and flip the flag: `services/backfill_feature_factory.py` `_DIVIDEND_AMOUNTS_SQL` (fingerprinted; edit only when no corpus run is live or resumable) and `services/bar_reconciliation_audit.py` `_EXPLAINED_DATES_SQL`.
2. The research reader (`src/intelligence/research/dividends.py`, `snapshot.py`): covered means inside the coverage span and outside every `dividend_event_coverage_gap` row for that source; Massive amounts are raw units (use amount over the stored prior close); a Massive-only span needs its own guard against large unexplained drops (Massive has no spin-offs and no return of capital); `declared_on` on or before the as-of when set. Design so the E17 battery code key does not move, or rerun the affected batteries on their seeds (check `battery_pass.battery_code_key` first); `repro_frozen` bit-identical; record the source set in the snapshot manifest.
3. Apply migration 608, run the load (single writer, after step 1), and record the coverage claim and the disclosed residual (about 5,900 dead members with no events stay uncovered: dead non-payers drop out of a total-return panel) in the methodology ledger before the first counted run.

## Done when

The first counted daily test builds its snapshot over the Massive-extended coverage with the member-year gain measured on the real panel, the disclosure is in the ledger, battery records are current, and the dividend writer's three sources reconcile without a crash.

## Not blocking

The Yahoo nightly path is unchanged and keeps running.
