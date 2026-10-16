# 191-12 review (fresh-context, read-only)

Reviewer: independent Claude session, 2026-10-16. Scope: commits 98274e851..976c6bdd1
(migration 496, ops_canonical_vendor_kind_swap.py, contract test, four guard-test edits).
Method: live read-only psql queries, log and report file reads, code read of the script, the
migration, the window script and the tests, plus my own independent digest spot check.
No code, DB or service state was modified.

## Verdict

PASS with one MEDIUM records defect. All three claims verified against the live database and
the artifacts. The plan's must-haves hold: v2 exists, equals the live table row for row (my own
queries plus the prove's digest method re-derived independently), the plan 07 gate passes
against v2 with totals identical to the live baseline, window two is open with all ten held
units inactive, and nothing is swapped.

## Findings

### MEDIUM

**M1. The committed evidence file quotes a stale source breakdown that does not reconcile with
the table total it sits beside.**
- Where: `.planning/phases/191-unified-raw-bar-table/191-12-WINDOW-EVIDENCE.json`
  (`preflight.sources`: ibkr_named 99,140,486, ibkr_fallback 194,470) versus its own
  `row_counts` (461,198,119). The five quoted sources sum to 461,195,455, 2,664 short.
- Root cause: those two numbers are from the pre-window dry-run preflight (the run that found
  deviation 1, while fetcher run a4428e8b was still writing). The final preflight
  (`logs/vendor_kind_preflight_191_12.json`, measured_at 2026-10-16T01:32:27Z, after the
  fetcher exited at 01:30:01Z) reads ibkr_named 99,142,349 and ibkr_fallback 195,271; five
  labels summing exactly to 461,198,119. The delta (1,863 named + 801 fallback) is the tail the
  fetcher wrote between the dry run and 01:30. The evidence file cites the clean preflight log
  as its source while carrying the dry run's numbers, so it is internally inconsistent.
- Failure scenario: a later reader recomputes the sum, finds 2,664 rows unaccounted, and either
  suspects a mapping gap that does not exist or loses trust in the evidence chain.
- Minimal fix: correct the two numbers in the evidence JSON to the final preflight values, or
  record both runs with their measured_at stamps. The gates themselves are sound (see checks a
  and d below); this is a records defect only.

### LOW

**L1. The deleted stale window-one record has no preserved evidence beyond summary prose.**
Check (e). `logs/` is gitignored (`.gitignore` line 205) and `git log --all --
logs/raw_cutover_window.json` is empty, so the 2026-10-13 record deleted per deviation 3
survives only as the deviation text in 191-12-SUMMARY.md. The deleted record held `units: []`
and no state key, so nothing substantive is lost, but `ops_raw_cutover_window.py` has no
`abort`/`discard` verb, so manual file deletion is the only exit from a dead record. Fix (if
worth it before the 191 close deletes the script): add an `abort` subcommand; otherwise accept.

**L2. Two held units sit in `failed` state.**
`systemctl is-active` now reports `failed` for `indicagent-ibkr-history-fetcher.service` (the
documented gateway-loss exit) and `indicagent-dividend-event-writer@yahoo.service`. The swap
script's gates treat only active/activating as blockers, which is correct, but plan 14's close
should confirm the failed states clear (timer `start` resets them) rather than accumulate.
Fix: at window close, verify both units come back via their timers; `systemctl reset-failed` if
they do not.

**L3. One migration landed where the plan text expected two.**
The plan's standing rules say "two files here: take two consecutive free numbers"; the executor
merged the APR seeds and the table into migration 496 alone. The contract test finds the file
by stem so nothing breaks, and one file is simpler, but the deviation is undocumented in the
SUMMARY's deviation list. Fix: none needed for code; note it if the SUMMARY is revised.

**L4. Resume-by-count-equality can skip a same-count wrong-values window (no exposure here).**
Check (c). In `copy_windows` (ops_canonical_vendor_kind_swap.py:947-962) a window whose v2
count equals the old count is marked done without a value check. A hypothetical earlier build
that wrote wrong values with correct counts would be skipped on resume. Backstops: compression
is applied only after an in-run verified copy, so compressed chunks are safe by construction;
both crashes in this plan (deviations 2 and the dry-run fix) aborted before any row landed; and
`--prove` compares full row digests, so any such window is caught before done. Carry one
obligation into plan 14: `--swap` must require a fresh `--prove` in the same state, since
nothing in code today enforces prove-before-swap.

### NONE

No HIGH findings. Checks b and d are clean (details below).

## Answers to the specific checks

**a. The 2,664-row arithmetic gap.** Resolved: not a mapping gap, no sixth label. Live
`GROUP BY source` returns exactly five labels: alpaca 220,108,375; derived_5m 135,090,402;
ibkr_named 99,142,349; tradier 6,661,722; ibkr_fallback 195,271; sum exactly 461,198,119.
All five are keys of `LABEL_TO_VENDOR_KIND` (vendor_kind.py:45-55, which also maps four
currently unused ibkr labels). The gap exists only inside the evidence JSON, which quotes the
pre-window dry run; see M1. The script has no totals gate asserting sum(sources) equals the
row total, but the build re-measures sources through `write_gates` -> `preflight` ->
`count_sources` at copy time, and an unmapped label is a hard blocker, so a real mapping gap
cannot pass.

**b. Digest coverage.** `DIGEST_COLUMNS` (script lines 138-149) carries timestamp, open, high,
low, close, volume, vendor, kind, base, price_sanity_status; symbol is the per-symbol WHERE,
timeframe the GROUP BY. That is every column of v2 and, via `_LIVE_COLUMNS` (line 152), the
preflight proves the live table has exactly those columns plus `source` (its report shows the
11 live columns), so no column can escape the proof. `ROW(...)::text` distinguishes NULL from
empty string and renders floats shortest-exact; `string_agg ... ORDER BY "timestamp"` is
deterministic because (timestamp, symbol, timeframe) is the primary key. The old side maps
source through the same rendered CASE the copy used. No skip paths: the digest loop has no
try/except, one-side-only series are mismatches (`compare_digests`), and a statement timeout
crashes loudly. I re-derived one symbol's four series independently (hand-written CASE, same
md5 formula): old and v2 counts and digests identical.

**c. Resume interaction.** See L4. Standalone `--prove` against a partially built table is
safe: it requires no build state and fails loudly (exit 3, digest/count differences) rather
than passing.

**d. Guard integrity.** The swap script never stops units and never edits the window record;
its only systemctl use is `is-active` (no sudo). `SUDO_PASS` lives in the window script
(`_real_systemctl`, ops_raw_cutover_window.py:353-368): `sudo -S` with the password on stdin,
not argv. The script writes only to market_data_ohlcv_v2 (INSERT/DELETE/compress/VACUUM on v2
chunks; the preflight mode sets `default_transaction_read_only = on`). The temporary registry
entries (single-writer v2 with the script as sole writer, raw-read allow-list row, pending
retirement naming 191-17) all carry retire clauses enforced by
test_temporary_allow_list_expiry.py, so nothing outlives the window. Preflight proved the
186-26 rebuild idle via pg_stat_activity, host processes and STATE.md lines.

## Verification (checks actually run)

1. `select source, count(*) from market_data_ohlcv group by source`: five labels, sum exactly
   461,198,119 (values above). `count(*)` both tables: 461,198,119 = 461,198,119.
2. `select timeframe, count(*) from market_data_ohlcv_v2 group by timeframe`: 15m 105,952,774;
   1d 7,159,561; 1h 29,137,628; 1m 9,775,958; 5m 309,172,198, identical to the old table's
   counts (preflight report and build log agree).
3. `select vendor, kind, count(*) from market_data_ohlcv_v2 group by 1,2`: exactly the five
   mapped pairs (alpaca/sip_rth, derived/5m_grid, ibkr/named, tradier/consolidated,
   ibkr/fallback) with counts matching their source labels.
4. Independent one-symbol digest spot check (hand-written CASE, same md5 formula): 4 series,
   counts and digests identical old vs v2.
5. Gate reports compared: `logs/selection_gate_20261016T013456Z.json` (target
   market_data_ohlcv, target_mode source) and `logs/selection_gate_20261016T034317Z.json`
   (target market_data_ohlcv_v2, target_mode vendor): exit 0 both, totals identical
   (n_canonical = n_selected = 318,948,156, real_differences 0, 1762/1762 series clean, all
   secondary counters equal). Claim 2 verified.
6. `logs/raw_cutover_window.json`: state open, opened_at 2026-10-16T01:16:51Z, ten units.
   `systemctl is-active` on all ten: inactive (two `failed`, see L2). Claim 3 verified.
7. Preflight log read: measured_at 01:32:27Z, verdict ready, blockers empty, disk 622.49 GiB
   free vs 68.58 required, shape_differences empty. Its sources contradict the evidence JSON
   (M1).
8. Fetcher log (`logs/ibkr_history_fetcher.log.1`): run a4428e8b, 198/200 ok, gateway_lost
   ibkr/ARE/1d, run_summary at 2026-10-16T01:30:01Z, exited on its own. Matches the operational
   note; the window did not kill it.
9. Code read: migration 496, the full swap script, ops_raw_cutover_window.py, vendor_kind.py,
   the contract test, and the diffs of the four guard-test files. Diffstat 98274e851~1..976c6bdd1:
   exactly the seven expected files, no attribution lines in commit bodies, gate --target was
   not touched in this range (the plan-07 implementation is the single one; its introspection
   reads v2 on (vendor, kind) directly, confirmed by target_mode "vendor" in the v2 report).
10. Tests: `.venv/bin/pytest` on the five touched files: 24 passed.
11. Live APR: five `infra.canonical_swap.*` keys present in config_state with the seeded
    values; 5 config_history rows with changed_by migration_496.
12. `git log --all -- logs/raw_cutover_window.json`: empty; the file was never tracked (L1).
