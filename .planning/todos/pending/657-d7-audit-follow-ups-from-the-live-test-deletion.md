---
status: pending
priority: P2
filed: 2026-11-22
source: todo 656 task 1 closure note (the six live-reading integration tests deleted, their assertions mapped to the D7 audit), 2026-11-22
---

# D7 audit follow-ups from the live-test deletion: the grid recompute verdict, the IBKR 1d pairs, a vendor-neutral daily vs intraday check

## Why

Todo 656 task 1 deleted the integration tests that read production and mapped each assertion to a D7 audit check (`services/bar_reconciliation_audit.py`, daily 06:00 UTC). Three things the deleted tests or the mapping exposed are not monitored today.

## Scope

- [ ] Wire a `grid_recompute` verdict per 15m and 1h into `judge_name_intraday`. The pure check exists: `src/intelligence/bars/integrity_checks.py::grid_recompute_findings` (stored rows against the derivation of current 5m, identity included; unit test `test_grid_recompute_flags_a_changed_extra_or_missing_bucket`). Today nothing compares stored grid rows to the derivation: intraday `digest_fresh` recomputes from 5m and compares against the digest the grid stage wrote from its derived values, so a stored 15m/1h row that drifts after the write keeps a fresh digest. Needs a per-name read of the stored canonical 15m/1h rows over the months `digest_scope` picks, a field on `_IntradayInputs`, the aggregate `intraday_month_digests` already computes, and a new name in `CHECKS_INTRADAY`; check every reader of the verdict list (verdict gate, unit tests that pin the list, dashboards). Edit only while the audit timer is quiet, in a detached worktree. Remove the `tools/vulture_whitelist.py` entry for `grid_recompute_findings` in the same change.
- [ ] After runbook Part F deletes the IBKR raw rows: drop the three IBKR pairs from `CANONICAL_1D_SOURCES` (`src/intelligence/bars/sources.py`), so `check_stray_sources` flags a stray IBKR 1d row on every name (today only `policy_conformance` would, and it judges `is_active` names only). Check every reader of the pair and the two ANY arrays first.
- [ ] `check_daily_vs_intraday` reads IBKR SMART observations and goes vacuous after Part F. Decide its successor: a vendor-neutral comparison of canonical 1d to the canonical 5m session aggregate, with a tolerance measured first (never set before the measurement), or retire the check with a recorded reason.

Gates: per item, the Done-Coding SOP (`/simplify`, `/review`, unit suite exit 0, independent review). Rollback: `git revert`.
