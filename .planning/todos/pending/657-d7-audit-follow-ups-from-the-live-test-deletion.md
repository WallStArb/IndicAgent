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

- [x] DONE 2026-11-23 (indicagent-d4, the lead ruled build): wire a `grid_recompute` verdict per 15m and 1h into `judge_name_intraday`. The pure check exists: `src/intelligence/bars/integrity_checks.py::grid_recompute_findings` (stored rows against the derivation of current 5m, identity included; unit test `test_grid_recompute_flags_a_changed_extra_or_missing_bucket`). Today nothing compares stored grid rows to the derivation: intraday `digest_fresh` recomputes from 5m and compares against the digest the grid stage wrote from its derived values, so a stored 15m/1h row that drifts after the write keeps a fresh digest. Needs a per-name read of the stored canonical 15m/1h rows over the months `digest_scope` picks, a field on `_IntradayInputs`, the aggregate `intraday_month_digests` already computes, and a new name in `CHECKS_INTRADAY`; check every reader of the verdict list (verdict gate, unit tests that pin the list, dashboards). Edit only while the audit timer is quiet, in a detached worktree. Remove the `tools/vulture_whitelist.py` entry for `grid_recompute_findings` in the same change.
- [x] DONE 2026-11-23 (indicagent-d4): after runbook Part F deletes the IBKR raw rows: drop the three IBKR pairs from `CANONICAL_1D_SOURCES` (`src/intelligence/bars/sources.py`), so `check_stray_sources` flags a stray IBKR 1d row on every name (today only `policy_conformance` would, and it judges `is_active` names only). Check every reader of the pair and the two ANY arrays first.
- [x] DONE 2026-11-23 (retired, lead ruling): `check_daily_vs_intraday` reads IBKR SMART observations and goes vacuous after Part F. Decide its successor: a vendor-neutral comparison of canonical 1d to the canonical 5m session aggregate, with a tolerance measured first (never set before the measurement), or retire the check with a recorded reason.

Gates: per item, the Done-Coding SOP (`/simplify`, `/review`, unit suite exit 0, independent review). Rollback: `git revert`.

## Progress 2026-11-23 (indicagent-d4)

IBKR pairs: dropped from `CANONICAL_1D_SOURCES`. Checked first: canonical `market_data_ohlcv` 1d holds only `massive/sip_flat_adj` (46,803,861 rows) and `alpaca/sip_rth` (369,606), from 2003-09-10 to 2026-11-20, so no stored row left the arrays; every reader (`bar_derivation` stored and digest reads, the audit's first-bar and stored reads, `ALLOWED_PAIRS`) reads `market_data_ohlcv`, never raw. An IBKR 1d row is now a stray row `check_stray_sources` flags (unit test). The module is in the research runner's import closure but in no bound battery's closure (computed with `battery_pass`), so no pass record moved; the live family 9 runs execute from a separate detached worktree.

`grid_recompute` recommendation (build, not wired): the existing `grid_parity` check compares stored 15m/1h rows with the IBKR archive and reads `n_without_archive` 1,529 of 1,529 names in the last audit (nothing compared), so no check compares stored grid rows to anything outside the digest. Evidence of what the new check would have caught: nothing today. A bounded read-only comparison of stored canonical 15m with the aggregate of canonical 5m (6 names, 2026-10-01 to 2026-10-31) found 3,432 buckets in both, 0 only derived, 0 only stored, 0 differing in any field. So it is insurance against a rogue write or partial write after the grid stage, not a fix for a seen defect. Musk order: delete the vacuous archive comparison of `grid_parity` (its input is gone), then build `grid_recompute` as its replacement, reusing the 5m derivation `intraday_month_digests` already computes per name and month, so the added cost is one stored-row read per name over the months `digest_scope` picks. Not built here; the item stays open for the lead's ruling.

Residual from the review of the IBKR pair drop (not done here): (1) `_INSERT_BAR_SQL` is a plain INSERT keyed on (timestamp, symbol, timeframe), so a stray IBKR 1d row, now invisible to the daily stage's read, would make that date classify as new and fail with a unique violation; today there is none, and the audit's stray check is the protection (loud, not silent). (2) Dead after Part F: the `VOLUME_BASIS_BY_VENDOR_KIND` entries for ibkr named, fallback and venue in `vendor_kind.py`, `SOURCE_IBKR_FALLBACK` and its two test uses, and the stale IBKR text in the `bar_derivation.py` module docstring and `docs/foundation/canonical-truth-registry.md` (line 30); deleting them touches raw-row handling (`backfill_feature_factory.py` may still read the labels), so it is a separate cleanup after the raw rows are gone. (3) `_stored_group` named an `ibkr_only` group that cannot occur and had no Massive-only group; it now reports `massive_only`.

## Landing 2026-11-23 (indicagent-d4, lead rulings)

`grid_recompute` replaces `grid_parity` in the D7 intraday report and in `verdict_gate.REQUIRED_CHECKS` (15m and 1h); the IBKR archive comparison, the dated-exceptions loader, `superseded_archive_buckets`, `rebucket_5m`, `check_daily_vs_intraday` and `aggregate_sessions` are deleted. `check_daily_vs_intraday` is retired because its IBKR SMART observations are gone; a vendor-neutral successor is decided later from a measured tolerance. The check compares the stored canonical 15m/1h rows of the scoped months with the derivation of the current 5m bars, a name with no passing `grid_recompute` record of its own is judged over every month (so an empty digest scope never passes on nothing), and stored rows outside the checked months are not compared. A read-only run on the live DB over 6 names for 2026-10 compared 572 15m and 154 1h buckets per name with 0 mismatches. The daily stage now fails a name with a stray 1d row loudly, naming the row, instead of a unique violation. The first audit after this lands has no `grid_recompute` rows, so the verdict gate and rebuild preconditions read `15m:grid_recompute missing` until one audit run writes them.

Open: retire the now-unread APR keys (`infra.grid_parity.dated_exceptions` and siblings, `threshold.bar_reconciliation.close_tolerance_bp` and `volume_tolerance_rel`) with a migration in the style of 591; not done here (an APR change).
