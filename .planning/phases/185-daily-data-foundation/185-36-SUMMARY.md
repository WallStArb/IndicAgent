---
phase: 185-daily-data-foundation
plan: 36
subsystem: bars / 1d source policy and the unified daily rule
tags: [D-06, D-07, D-09, D-18, D-21, bar_source_policy, d2-v2, write-contract, gap_closure, migration-446]
requires: [185-28, 185-31]
provides:
  - "bar_source_policy (migration 446, live): append-only source decisions, seeded with the real state of every timeframe"
  - "threshold.bar_integrity.fallback_basis_window_sessions 20 and fallback_basis_tolerance_bp 10"
  - "market_data_ohlcv_tradeable NULLs volume for ibkr_venue and ibkr_fallback"
  - "src/intelligence/bars/daily_rule.py: RULE_VERSION d2-v2, PolicyRow, resolve_policy, derive_daily_v2"
  - "daily stage on d2-v2: per-name TSV dry run, write-contract apply path that refuses while canonical_bar_lineage is a table"
  - "logs/185-36_d2v2_dryrun.tsv: d2-v2 measured over all 1,502 compute_1d names"
affects: [185-37, 185-38, 185-33, 185-42, 185-43, 189-10]
tech-stack:
  added: []
  patterns: ["source choice as append-only policy rows resolved per date; a missing row raises", "fallback admission by the median vendor close ratio over the nearest common sessions"]
key-files:
  created:
    - production/migrations/446_bar_source_policy.sql
    - src/intelligence/bars/daily_rule.py
    - tests/unit/test_bar_source_policy_migration_contract.py
    - tests/unit/bars/test_daily_rule.py
    - tests/fixtures/bars/d2v2_known_cases.json
  modified:
    - src/intelligence/bars/sources.py
    - src/intelligence/bars/derivation.py
    - services/bar_derivation.py
    - tests/unit/services/test_bar_derivation_daily.py
    - tests/unit/test_single_writer_registry.py
    - tests/unit/test_canonical_lineage_digest_writer_boundary.py
    - tests/fixtures/bars/README.md
    - tests/integration/test_d2_single_writer_live.py
    - tests/integration/test_d2_excludes_test_caller_observations.py
decisions:
  - "LEGACY_IMPORT observations are IBKR's lowest-ranked fallback (below SMART, always stale under a split), not ignored: DAL's 2007-04-27 to 05-02 IBKR answers exist only as LEGACY_IMPORT, and the plan's DAL truth needs them"
  - "A split's evidence request counts as current scale: ETHA's post-split Tradier refetch was fetched 25 ms before the split's recorded_at"
  - "A primary vendor with only stale-scale answers serves the latest one flagged pre_split_unrefetched before the fallback is considered; a stale fallback is never admitted"
  - "Head seam recorded as a non-quarantine bar_quality_flag (rule fallback_seam) on the first Tradier bar, not in bar_source_policy.evidence (named deviation from spec section 2)"
  - "Removal scope = stored 1d keys between the name's first and last observed date (TRADIER, SMART, LEGACY_IMPORT)"
  - "Revision waiver reads corporate_action and the symbol's or the default 1d policy rows recorded after the last applied daily load; no applied load waives"
  - "todo 500 (10 clean Tradier bars hidden by a stale price_sanity_status) belongs to 185-38, not this plan"
metrics:
  duration: 35min
  completed: 2026-10-07
  tasks: 3
  files: 14
---

# Phase 185 plan 36: bar_source_policy and the unified daily rule d2-v2 Summary

The source policy now lives in one append-only table (migration 446, applied live), one pure rule (d2-v2) replaces d2-v1 and the loader's tradier-v1, and the daily stage runs it for every compute_1d name. The dry run over all 1,502 names changed no stored bar. It reproduces the spec's measured state exactly on the mixed names, leaves every Tradier-only name unchanged, and shows that the 236 IBKR-only names cannot be cut over until per-name exception rows exist (see "For 185-37 and 185-38").

## Commits

| Task | Commit | What |
|---|---|---|
| 1 RED | 96e36f050 | migration 446 contract test |
| 1 GREEN | 21adbc226 | migration 446 (applied live), SOURCE_IBKR_FALLBACK, registry entry |
| 2 RED | 7408cf145 | d2-v2 tests, read-only D1 extracts of the five known cases, README row |
| 2 GREEN | 11c86ab28 | daily_rule.py; SplitRecord gains optional evidence_request_ids |
| 3 RED | 518579cbd | daily-stage tests for dry run, apply path, refusal, lineage guard |
| 3 GREEN | 9c44b1add | daily stage on d2-v2, TSV report, write-contract apply path |
| fix | b15c25f28 | a non-positive Tradier close measures no basis (Rule 1) |

## Task 1: migration 446

`ls production/migrations` right before applying showed 445 and 453, no 446. Applied with `psql -f` under `lock_timeout 10s`, then committed with the code.

- `bar_source_policy`: `policy_id`, `timeframe`, `symbol` (NULL = default), `valid_from`, `valid_to`, `ingress_mode`, `primary_source`, `fallback_source`, `reason`, `evidence`, `recorded_at`. CHECKs on each vocabulary, `fallback_source IS DISTINCT FROM primary_source`, and derived ingress if and only if a derived primary. An exclusion constraint on `(timeframe, coalesce(symbol, ''), daterange(valid_from, valid_to))` stops two rows covering one date of one series.
- The listing_venue triggers: the only UPDATE closes an open row; DELETE and TRUNCATE raise. Probed live inside rolled-back transactions: a non-closing update, a DELETE, a TRUNCATE and an overlapping INSERT all raised; close-then-insert of a REX row worked; `bar_derivation_writer` can read but not insert.
- Grants: SELECT to `bar_derivation_writer`; INSERT, UPDATE, DELETE and TRUNCATE revoked from PUBLIC. The D7 audit connects as the database owner (Settings DSN), so it needs no grant.
- Acceptance: open rows are 15m derived/derived, 1d observed/tradier, 1h derived/derived, 1m direct/ibkr, 4h direct/ibkr, 5m direct/ibkr. `grep -c ibkr_fallback` on the view definition prints 1.
- APR: both keys seeded `[initial_estimate]`, not ML targets, with a `migration_446` config_history row each.
- Registry: `bar_source_policy: ()` (no module may write it; 185-37 registers its CLI).

## Task 2: d2-v2

`derive_daily_v2(observations, policy_rows, splits, *, symbol, basis_window_sessions, basis_tolerance_bp) -> DailyV2Result(bars, flags, refused_interior, head, admitted_interior, stale_only)`. It is pure: thresholds are parameters.

Known cases, on read-only extracts (one SELECT-only transaction, 387 observations plus ETHA's split; sha256 in the README):

| Case | Result |
|---|---|
| RJF | Untouched: every bar is Tradier, equal to Tradier's latest answer. With a Tradier hole made at 2021-08-16 or 2021-09-21, IBKR's pre-split bar (57.27 against 85.90) is refused and listed |
| REX | Under a symbol row `primary ibkr` to 2025-09-09: every bar in range is IBKR SMART, source `ibkr_named`, none from Tradier; no step across the range boundary. Without the row d2-v2 serves Tradier's 15.50 for 2025-09-08 (the seam) |
| DAL | 2007-04-26 (SMART 22.79) and 04-27 to 05-02 (LEGACY_IMPORT) are `ibkr_fallback` heads; 05-03 onward Tradier; one `fallback_seam` on 05-03, 20 common sessions, median ratio within 1% |
| ETHA | Every bar Tradier with no flag; every date before 2026-10-02 comes from the split's evidence request (closes above 50); SMART and LEGACY_IMPORT answers are all stale and never chosen |
| INDA | The 12 interior IBKR dates in the window are admitted (vendors agree), source `ibkr_fallback`, volume 0, so the tradeable view hides them |

Synthetic cases: a 5 bp interior hole is admitted and a 15 bp hole is refused; a nearest-window tie goes to the earlier session; a missing policy row raises; a non-TRADES observation raises; shuffled input gives identical output.

## Task 3: daily stage on d2-v2

- Every name runs d2-v2. The Tradier-owned early return, the d2-v1 call path and `_UPSERT_LINEAGE_SQL` are gone (grep counts: `derive_daily_v2` 2, `_UPSERT_LINEAGE_SQL` 0).
- Stored 1d rows of every canonical source are classified by `write_contract.classify`.
- Apply path, tested on fakes only:
  - one transaction per symbol, under `SET LOCAL ROLE bar_derivation_writer`;
  - one `ohlcv_load` row (source derived, timeframe 1d, caller `bar_derivation-daily`, destination market_data_ohlcv, the four counts, outcome applied or refused);
  - old values of changed and removed rows go to `ohlcv_revision` (origin load) before any bar change;
  - removed rows are deleted by key, new rows inserted, changed rows written through `_UPSERT_1D_SQL` (the changed set only);
  - flags go through `write_flags`;
  - then the scrub and `write_1d_digests` at d2-v2.
- No compressed-hypertable allow-list entry was needed.
- `_SELECT_DAILY_CHANGED_SINCE_SQL` keeps its name and `tradier_owned`, and gains `policy_since`.
- The batch APR snapshot now holds `infra.bar_derivation.*`, `threshold.bar_integrity.*` and `threshold.bar_scrub.*` (closes 185-27's provenance note).
- Apply raises before opening a batch while `canonical_bar_lineage` has relkind `r`, with a message naming 185-38.

### Live dry run (2026-10-07 04:48:57 UTC, no `--apply`)

`.venv/bin/python -m services.bar_derivation --stage daily --report logs/185-36_d2v2_dryrun.tsv`. Exit 0 in 73 s wall (222 MB peak). 1,502 names derived, 0 failed, 0 stale-only dates, 0 stored rows outside a name's span. The TSV has one row per name.

Bars by group (group = the name's stored 1d sources before the run):

| Group | Names | Stored | Canonical | New | Changed (source only) | Unchanged | Removed | Head | Admitted interior | Refused interior |
|---|---|---|---|---|---|---|---|---|---|---|
| Tradier only | 1,006 | 4,939,968 | 4,944,703 | 4,735 | 0 (0) | 4,939,968 | 0 | 4,683 | 52 | 32 |
| Mixed | 260 | 1,333,950 | 1,333,922 | 0 | 793 (792) | 1,333,129 | 28 | 35 | 758 | 28 |
| IBKR only | 236 | 736,268 | 944,929 | 223,686 | 721,243 (167,139) | 0 | 15,025 | 146,587 | 12,272 | 15,025 |
| Total | 1,502 | 7,010,186 | 7,223,554 | 228,421 | 722,036 (167,931) | 6,273,097 | 15,053 | 151,305 | 13,082 | 15,085 |

Names with a non-zero count:

| Group | New | Changed | Removed | Head | Admitted interior | Refused interior | Would refuse (unwaived) |
|---|---|---|---|---|---|---|---|
| Tradier only | 25 | 0 | 0 | 9 | 20 | 3 | 0 (0) |
| Mixed | 0 | 255 | 10 | 16 | 244 | 10 | 0 (0) |
| IBKR only | 232 | 231 | 42 | 128 | 124 | 42 | 202 (0) |

Readings:

- **Tradier-only names:** d2-v2 equals every stored Tradier bar on all 1,006 names (0 changed, 0 removed). The 4,735 new bars are IBKR answers Tradier lacks:
  - 4,683 heads on 9 names: LIT 1,552, TEAM 1,369, INSM 1,127, SIL 276, SPOT 222, FBIN 95, GREK 35, RKLB 5, QSR 2;
  - 52 admitted interior bars on 20 names.
  - 32 interior dates are refused on BNO (28), COPX (3) and SIL (1). Nothing is stored there, so nothing would be removed.
- **Mixed names:** these match the spec's measurement exactly.
  - The 35 heads sit on 16 names.
  - Of the 786 interior IBKR bars, 758 (96.4%) are admitted on 244 names and 28 refused on 10 names: XHE 14, MUX 4, BIL 2, HON 2 (2025-03-06 and 2026-03-19), EWM, EWS, EWU, PARR, WELL and XTN 1 each.
  - The 792 source-only changes relabel stored `ibkr_named` bars to `ibkr_fallback` with equal values.
  - The one value change is INDA 2012-08-03: IBKR's latest SMART answer has high 21.68 where the stored bar has 21.69 (185-30 recorded this).
- **IBKR-only names:**
  - 554,104 value changes (IBKR to Tradier) and 167,139 relabels of heads.
  - 223,686 new Tradier bars.
  - 15,025 refused interior IBKR bars on 42 names would be removed: W 2,315, RGEN 1,562, AUGO 1,164, GYRE 1,069, CBC 1,045, FROG 946, AIG 922, FUBO 795, NEXN 637, MTCH 624, and others.
  - 202 names would breach the revision ratio (about 1.0). All 202 are waived, because no applied d2-v2 load exists yet, so the refusal gives no protection at the first apply.

## For 185-37 and 185-38 (the cutover)

1. **IBKR-only names have bad Tradier data.** The "Tradier primary for every name" decision is not safe for the IBKR-only names as they stand. This is a read-only follow-up over the 236: the IBKR/Tradier close ratio on common sessions, with the share within 10 bp.

   | Agreement on common sessions | Names | Examples |
   |---|---|---|
   | at least 90% within 10 bp | 179 | |
   | 50 to 90% within 10 bp | 24 | |
   | under 50% within 10 bp | 28 | median ratio CTVA 6.7, ELS 205, MTCH about 98,920, WEX 37, RGEN 40, TPL 9.0, KDP 6.2, GYRE 10.1, AUGO 15.0, REX 2.0, RSG 1.64 |
   | no common session | 5 | CART, CC, CUBE, FLUT, LEA |

   - Tradier's `W` is a different series, not Wayfair: from 2007-12-24, ratios 0.53 to 0.75 drifting day to day.
   - For these names the `short_history` refusal kept bad data out. d2-v2 under the default row would make that data canonical and remove the correct IBKR interior bars.
   - 185-37 must write exception rows, or 185-38 must exclude these names, before any apply.
   - REX is in this set: without its exception row, d2-v2 serves the September 2025 Tradier seam.
2. **Heads with large seams.** Head admission is unconditional, as the spec says, but 31 of the 153 head names have a seam beyond the 10 bp tolerance: 30 IBKR-only and SIL.
   - Largest: MTCH, ELS, AUGO, NOC 88,616 bp, CTVA, KDP, RGEN, SIL 20,004 bp, SAFE, HPQ, SNEX, COR.
   - XLY, XAR, XHS and XSW sit at about 5,000 bp, a 2:1 basis.
   - Each would be a false return at the seam, recorded only by the `fallback_seam` flag.
   - Recommendation: gate head admission by the same tolerance (refuse the head when the seam's median ratio is outside it). That is a spec change for the owner. 185-37's basis study can supply the evidence.
3. **The refusal is waived on every first load.** The revision-ratio refusal is waived for all 202 IBKR-only breaches on the first apply (no prior applied daily load). 185-38 should review the per-name TSV, not rely on the refusal.
4. **The historical pipeline's daily stage now fails until 185-38.** `infrastructure_run_historical_pipeline.py` (used by `ops_head_rerun.py`) chains `--stage daily --apply`, as does the fetcher's daily stage. The fetcher is stopped and disabled.
5. **todo 500 belongs to 185-38.** The write contract compares OHLCV and source only, so the 10 clean Tradier bars with a stale `price_sanity_status` classify unchanged and d2-v2 never touches the column. 185-38 should, inside the cutover:
   - either clear the column on those rows under the daily writer's role;
   - or drop the predicate from the view, after confirming that every `confirmed_corrupt` row also carries a quarantine flag.
6. **The ISLAND switch does not affect d2-v2.** `infra.ibkr.venue_fallback.island_failed_unlisted` is off; d2-v2 reads no venue route and no head classification.
7. **Adjustment basis.** d2-v2 serves Tradier's basis unless a policy row says otherwise. The 5.5% of name-dates on 821 names where the vendors disagree go to 185-37's study; RJF (IBKR wrong) and REX (Tradier wrong) are in the fixture.
8. **Volume on the 236 names.** After cutover, fallback heads read NULL volume in the tradeable view: 146,587 head bars on 128 IBKR-only names.

## Verification

- Task gates:
  - Task 1 verify: contract, migration number uniqueness, `tests/unit/bars/`.
  - Task 2 verify: daily_rule, derivation, fixtures present.
  - Task 3 verify: daily, batch, grid, market_data_ohlcv writer boundary, lineage/digest boundary, load/revision boundary.
  - All passed, as did `test_compressed_hypertable_write_boundary`, `test_market_data_ohlcv_boundary` and the three 185-44 guards (single_writer, readers, expiry).
- ruff and black are clean on every touched file; pre-commit passed on every commit.
- Full `.venv/bin/pytest tests/unit/ -q`: see Self-Check.
- Not run:
  - `repro_frozen` (nothing under research/ or statistics/ was touched);
  - the two edited integration tests (signature change only).
- Unit tests use fakes only. No test writes D1 or runs derivation against production.

## Deviations from plan

### Auto-fixed issues

**1. [Rule 1] LEGACY_IMPORT is IBKR's lowest-ranked fallback, not ignored.**
- The plan's interface says d2-v2 ignores LEGACY_IMPORT. Its DAL truth needs 2007-04-27 to 05-02 as heads, and those IBKR answers exist in D1 only as LEGACY_IMPORT.
- Ignoring them would delete real IBKR answers.
- They rank below SMART and are always stale for a split-affected date, as in d2-v1. The fixture includes the route.
- Commit 11c86ab28.

**2. [Rule 1] SplitRecord gains optional `evidence_request_ids` (derivation.py, outside the files list).**
- The Tradier refetch that records a split is fetched before the split's `recorded_at` (ETHA: 25 ms), so a fetched_at-only staleness rule marks the only current-scale answer stale.
- d2-v1 ignores the field. The daily stage's split read selects it.
- Commit 11c86ab28.

**3. [Rule 3] The lineage/digest boundary test drops bar_derivation as a canonical_bar_lineage writer.** Removing the d2-v1 path made its PERMANENT entry stale. Commit 9c44b1add.

**4. [Rule 3] Two integration tests pass the route list** to `_SELECT_DAILY_OBSERVATIONS_SQL`, which now takes `$2`. This is a signature change only. Commit 9c44b1add.

**5. [Rule 2] `policy_since` in the changed-since probe.** Without it, a new exception row would never make a name due under `--changed-only`. Commit 9c44b1add.

**6. [Rule 1] Zero Tradier close.** A non-positive close raised ZeroDivisionError in the ratio and would fail the whole name; it is now left out of the common sessions. The dry run had 0 failures, so its results are unaffected. Commit b15c25f28.

**7. [Rule 1] Idempotent history insert in migration 446.**
- My verification re-run of the migration added a second pair of `config_history` rows: the 443 pattern's `ON CONFLICT DO NOTHING` never conflicts, because timestamps differ.
- The insert is now guarded by `NOT EXISTS`. I deleted the two duplicate rows I had created (timestamp 04:37:39); the original pair stays.
- A second re-run inserted nothing.

### Named deviation from the spec text (plan revision)

The head seam is a non-quarantine `bar_quality_flag` row (rule `fallback_seam`) on the first Tradier bar after the head. Its detail holds the overlap median ratio, its deviation in bp, the window, the common-session count and the head span. It is not stored in `bar_source_policy.evidence`. The policy table holds decisions and has one writer; a seam is a measurement the derivation recomputes on every run, and writing it there would make the daily stage a second writer of the policy table. The registry gives `bar_derivation.py`'s bar_quality_flag segment the three d2-v2 rules.

### Discretion choices

- `--report` is now a TSV, as the plan asks. The d2-v1 markdown report is gone.
- Group is assigned by the stored sources before the run: none, tradier_only, mixed or ibkr_only.
- The waiver also counts the default 1d policy row, because a default change legitimately revises every name.
- 4h's policy row records the real state, per the plan check.
- No orphaned APR key, so no `_PENDING_RETIREMENT` entry. `infra.bar_derivation.venue_bars_1d` keeps its readers (`ops_data_bar_check.py`, D7).

## Known stubs

None.

## Threat flags

None beyond the plan's register.
- T-185-36-01 is mitigated: the median-ratio test refuses 15,085 interior dates.
- T-185-36-02 is mitigated: the view NULLs `ibkr_fallback` volume.
- T-185-36-03 is mitigated: append-only rows, the exclusion constraint, and a missing row raises.
- T-185-36-04 is mitigated: apply refuses on relkind `r`.

The new finding (wrong Tradier series and large head seams on the IBKR-only names) is a data risk for 185-38, not a new surface.

## TDD gate compliance

RED then GREEN for each task: 96e36f050 then 21adbc226; 7408cf145 then 11c86ab28; 518579cbd then 9c44b1add. Each RED failed before its implementation existed.

## Self-Check: PASSED

- Full `.venv/bin/pytest tests/unit/ -q`: exit 0, no failures (the project config prints no count line; 5 skip lines, all pre-existing). It ran after 9c44b1add; the b15c25f28 guard and its test were run with `tests/unit/bars/` afterwards.
- Files exist: migration 446, daily_rule.py, the contract and rule tests, the fixture, logs/185-36_d2v2_dryrun.tsv (1,502 rows plus header, equal to the live compute_1d count) and this SUMMARY.
- Commits resolve: 96e36f050, 21adbc226, 7408cf145, 11c86ab28, 518579cbd, 9c44b1add, b15c25f28. No commit in the range deletes a tracked file.
- No stored change: 0 bar_derivation_batch, ohlcv_load or ohlcv_revision rows since the plan began; 1d rows still tradier 6,273,097 and ibkr_named 737,089.
