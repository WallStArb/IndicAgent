# Data layer integrity design

Author: Claude (Opus 5.5), 2026-10-06, at Brandon's request ("build the data layer right from the
start, as Renaissance would")
Status: implemented (plans 185-31, 185-33, 185-35 to 185-45, 189-07, 189-08; 189-09 to 189-11 pull the new data)
Informed by: `docs/plans/2026-09-26-unified-research-to-production-design.md` (section 12),
`docs/plans/2026-09-26-daily-data-foundation.md` (D0-D7),
`docs/plans/2026-09-29-intraday-bar-store-redesign.md`,
`docs/plans/2026-10-02-ibkr-history-fetch-consolidation-design.md` (phase 189),
`.planning/phases/185-daily-data-foundation/185-VERIFICATION.md` and plans 185-27 to 185-35,
`docs/foundation/instrument-onboarding-sop.md`, live read-only queries on 2026-10-06.

## Problem

Every defect found in the last two weeks has the same shape: a second path, a side table or a
bookkeeping flag that could disagree with the bars and did. The nightly Tradier refetch appended
10.97M identical D1 rows. Lineage and digests, written beside the bars, described IBKR values on
743 names after Tradier overwrote them. 74% of rows were synthetic fill. The promote gate read
`backfill_status.fetch_complete`, which nothing set for Tradier names, and held 517 names with real
data. A week of IBKR stream time fetched vendor 15m and 1h that are a function of 5m.

The fix is not more checks on more paths. It is fewer paths, each a pure function of stored raw
answers, with every side record either derived on read or verified against the data it describes.

## Measured state (2026-10-06, read-only)

| Fact | Value |
|---|---|
| Universe | 1,529 active equities; 1,502 `compute_eligible_1d`; 233 `compute_eligible`; 27 held |
| 1d canonical | Tradier 6,271,834 rows; IBKR 737,081 rows |
| 1d source mix | 1,006 Tradier only; 260 Tradier plus IBKR (821 IBKR bars: 35 heads on 16 names, 786 inside the Tradier span on 249 names, 177 of them on 2025-03-06 and 176 on 2026-03-19); 236 IBKR only, every one a Tradier `short_history` refusal |
| Vendor agreement on 1d close (3.91M overlapping name-dates) | 83.5% within 1 bp, 91.8% within 10 bp, 94.5% within 1%; 216,057 name-dates on 821 names differ by more than 1% |
| Vendor volume ratio IBKR SMART / Tradier | median 0.80 (p10 0.46, p90 0.97) |
| Intraday | 5m 81.8M rows on 240 names; 15m 26.1M derived plus 31.7M vendor; 1h 7.2M derived plus 8.5M vendor; 1m 9.8M; 4h 2,184 |
| Zero-volume provider bars | 5m 4.40M (5.4%), 15m 0.90M, 1d 17,666 |
| Promoted names without 5m | 1,262 |
| Request ledger | `ohlcv_request` 32,738 rows, all timeframes (22,360 intraday); `ohlcv_observation` is 1d only (CHECK), 15.8M rows, 3.4 GB heap plus 3.5 GB index |
| Lineage and digests | `canonical_bar_lineage` 7.05M rows (1.2 GB, 1d only); `bar_content_digest` 825k rows; repaired by 185-30 |
| Intraday bar write | `ON CONFLICT DO NOTHING` (`_intraday_persist.py`): a later differing answer is dropped silently |
| Storage | `market_data_ohlcv` 6.6 GB (109 of 110 chunks compressed); archive 3.1 GB; database 121 GB; 567 GB free |

Correction to the brief: intraday requests are recorded in `ohlcv_request` (since 185-09); only
intraday observations are absent. `ohlcv_coverage` is a rollup of that ledger, not a second one.

Finding not previously recorded: the two vendors disagree on adjustment basis for long runs. RJF
before its 2021-09-22 3:2 split: Tradier 85.90 then 86.92 (continuous), IBKR SMART 57.27 then 86.92
(a +52% step in IBKR's own series). REX in September 2025: Tradier steps 15.42 to 30.51, IBKR is
continuous. IBM, BDX and LEN show IBKR/Tradier ratios of 1.01 to 1.08 ending at spin-off dates.
Each vendor is wrong on different names. The canonical series checked (RJF Tradier, REX IBKR) are
continuous, but nothing reports these runs, and a cross-vendor splice inside a run creates two
false returns. Of the 786 inside IBKR bars, 96% sit where the vendors agree within 10 bp; the rest
are false-return generators today.

## 1. Invariants

| Invariant | Statement | Enforced by |
|---|---|---|
| One canonical value | Each (symbol, timeframe, bar) has one stored value, from the source the policy names for that date | Source policy table; conformance check (zero tolerance) |
| Pure derivation | Canonical = f(raw answers, rule version, source policy, corporate actions); rebuild is bit-exact | Nightly recompute-and-compare for 1d; digest compare for grids |
| Idempotent writes | Writing the same answer twice changes nothing; a changed answer writes exactly the changed rows and records the old values | Write contract (section 4); CI tests |
| No fabrication | No placeholder, no scaled volume, no forward fill; missing is NaN | 185-32 fence; `no_fill` |
| Ground-truth gates | Promotion and the 186 rebuild read the computed integrity verdicts, never a bookkeeping flag | Section 6 |
| Lineage cannot drift | Provenance is derived from the data on read, or verified against it nightly | Section 4 |
| Point in time | Policy rows, corporate actions and listing venues carry valid-from dates and are append-only; snapshots pin their symbol list and the verdicts they read | Existing triggers; snapshot manifest |
| Every layer earns its place | A table exists only if a measured problem needs it | Section 10 deletions |

## 2. Source policy

One table, `bar_source_policy`: `timeframe`, `symbol` (NULL for the timeframe default),
`valid_from`, `valid_to`, `ingress_mode`, `primary_source`, `fallback_source`, `reason`,
`evidence` (jsonb), `recorded_at`. Append-only, superseded by closing `valid_to`, the
`listing_venue` pattern. It is the only place a source choice lives.

Decisions:

- 1d: primary Tradier for every name, fallback IBKR SMART TRADES. One vendor for the whole
  cross-section, because cross-sectional volume and turnover ranks across 1,266 consolidated-volume
  names and 236 SMART-volume names would carry a 20% basis split that no feature can see.
- Fallback admission is a deterministic rule inside the derivation:
  - Head (before Tradier's first bar): admitted, with a seam row in `evidence` stating the
    overlap ratio over the first `threshold.bar_integrity.fallback_basis_window_sessions` common
    sessions.
  - Interior hole: re-asked from Tradier first. If still absent, admitted only when the median
    IBKR/Tradier close ratio over the nearest window of common sessions is within
    `threshold.bar_integrity.fallback_basis_tolerance_bp`. Otherwise the bar is NaN.
  - Every admitted fallback bar has volume NULL in the tradeable view (the `ibkr_venue`
    precedent). The 0.80 volume ratio is never spliced and never rescaled.
- Per-name exception rows only on evidence: a name whose Tradier series has a seam IBKR does not
  (REX) gets `primary_source = ibkr` for the affected range, with the basis run as evidence.
- Consequences. The 236 IBKR-only names become Tradier primary with IBKR heads, NULL volume on
  those heads, and their revisions recorded. Of the 260 mixed names, the 35 heads stay as recorded
  seams. About 96% of the 786 interior bars pass admission; the rest become NaN. This keeps
  migration 438's rule that a name's volume comes from one source, and adds an explicit, measured
  price seam where the old rule refused the whole name.
- 5m: primary IBKR, no fallback. 15m, 1h, 4h: derived from 5m, no vendor source.

## 3. Ingress modes

`ingress_mode` per timeframe, one of three:

| Mode | Timeframes | Raw record | Canonical |
|---|---|---|---|
| `observed` | 1d | `ohlcv_request` plus `ohlcv_observation` (changes only) | Derived by the daily stage |
| `direct` | 5m, 1m | `ohlcv_request` with per-request content digest; the stored row is the raw answer | The stored row; restatements recorded in `ohlcv_revision` |
| `derived` | 15m, 1h, 4h | none; vendor bars only in the frozen archive and the parity sample | Session-anchored aggregation of 5m |

1d needs `observed` because it has two vendors, ADJUSTED_LAST (the D5 dividend input), venue routes
(D3) and whole-history restatement on splits (ETHA rescaled 552 bars on 2026-10-02). Those are
inputs to computations, so the raw answers must persist apart from the choice.

5m is `direct` because it has one vendor and no second view to reconcile. An observation copy would
add about 17 GB at full scale and buy nothing. "Immutable" is the wrong word: IBKR restates recent
intraday bars (185-31 found 15 to 40 differing rows per name inside its revision window). The rule
is that the latest answer wins, and the replaced values go to `ohlcv_revision`.

`ohlcv_request` is the one request ledger for every timeframe. `ohlcv_coverage` stays as the
fetcher's ranking cache. It is declared derived and rebuilt by `--rebuild-coverage` (189-06), and
the integrity report fails on any drift from its rebuild. `ohlcv_load` widens from Tradier 1d to
the write record of every canonical writer (`batch_id`, `n_new`, `n_changed`, `n_unchanged`).
`ohlcv_revision` then has one parent for all timeframes, gains an `origin` column (`load`,
`archive_segment`), and is the one revision table.

## 4. Canonical derivation, lineage and the write contract

One 1d rule and one 1d writer. `derive_daily` (d2-v1) and the Tradier loader's inline rule
(tradier-v1) merge into one pure function, rule `d2-v2`: (D1 observations, policy rows, current
corporate actions, scrub rule version) in, canonical bars and flags out. The Tradier loader keeps
its fetch, D1 elision and refusal logic, writes only D1 and `ohlcv_load`, then chains the daily
stage for the names it changed. This reverses the owner-accepted override that allowed a second
1d writer. It does not reopen Tradier as primary. The override was an implementation consequence,
and it is where gap A came from. The fallback rule also needs both vendors' observations in one
function.

Lineage becomes derived. `canonical_bar_lineage` the table is dropped and replaced by a view of the
same name. For each canonical 1d bar, the view returns the latest observation of the policy source
with equal open, high, low, close and volume (`IS NOT DISTINCT FROM`). By construction it cannot
point at different values. A canonical bar with no match returns NULL, and the report counts it as
`lineage_missing` (zero tolerance on visible bars). For `direct` timeframes, provenance is the latest
`bars` request whose window contains the timestamp. Under the write contract below, that is the
answer the row holds. No per-row provenance column goes on a compressed hypertable (unified design
12.1, the 768 GB class).

Digests stay a table, because the 186 rebuild and `ic_measure` read them as idempotency keys and
recomputing sha256 over 5m slices on every read is wasteful. The writer of each timeframe updates
the digests of every month it changed, in the same transaction as the bar change. The integrity
report recomputes all 1d digests nightly, plus every intraday month written since the last report
and a full intraday sweep weekly. A mismatch fails the name.

Write contract, for every writer of `market_data_ohlcv`, `ohlcv_observation` and the archive:

1. Read the stored rows for the incoming keys.
2. Classify each incoming row as new, changed or unchanged by exact value comparison.
3. Write new and changed rows only. Write old values of changed rows to `ohlcv_revision`. Write one
   `ohlcv_load` row with the three counts. Do all of this in one transaction with the request
   rows and digests.
4. Refuse the load when `n_changed / n_stored` exceeds `threshold.bar_integrity.max_revision_ratio`
   (generalizing `infra.tradier.max_changed_bar_ratio`), unless the load carries a recorded
   corporate action. A refused load is a finding.

This replaces `ON CONFLICT DO NOTHING` in the intraday path and delete-and-rewrite of unchanged
segments in the grid stage. D1 identical-answer elision (185-27) becomes the IBKR rule too.

## 5. Derived timeframes and the 5m fetch

15m, 1h and 4h come only from 5m, through `aggregate_session_grid` on NYSE session-anchored edges
(the existing D2b rule, `grid-v1`, regular session only). A derived bar over a constituent slot
in an unanswered window carries `partial_constituents` and is NaN to research. Zero-volume provider
bars count as answered no-trade slots, never as prices.

Vendor 15m and 1h stop being fetched today. Set `infra.backfill.default_scopes` to
`{"compute_1d": ["1d", "5m"]}` and `infra.backfill.priority_tf_order` to `["5m"]`. The archive (75.1M
15m and 20.4M 1h vendor rows on about 695 names, 3.1 GB) is frozen as the parity reference and kept,
because raw market data is permanent and it is the independent measurement that catches a bad 5m
fetch. Ongoing parity is a weekly vendor refetch of
`infra.backfill.grid_parity_sample_names_per_week` (10) names into the archive, compared bucket by
bucket. 15m must match exactly. 1h is compared on matching buckets only, because the vendor's 1h
grid lacks the 09:30 half-hour on 39 of 231 measured names.

Per name, after its 5m lands, the grid stage derives 15m and 1h, records parity against the archive,
and moves the vendor rows out of `market_data_ohlcv` into the archive. That covers 31.7M plus 8.5M
rows (about 1.6 GB), plus 185-31's seven names.

5m fetch for the 1,262 promoted names without it:
- 150-day chunks (`infra.ibkr.chunk_days.5m`), so at most 49 requests per name over the 20-year
  depth. That is at most about 61,800 requests.
- Two bounds, each about 8,400 requests a day: pacing (58 per 10 minutes) and latency (median 10.2
  s per measured 5m request). Corrected 2026-10-06 from 1,012 measured 5m requests (mean 14.0 s, p90 34 s): floor about 10.6
  days; expect 12 to 18 days at the fetcher's 240-minute
  budget with a 15-minute gap, plus gateway outages.
- Pilot of 20 names spanning wave 1 and wave 2 first. Measure requests per hour, rows per name,
  revisions and parity. Extrapolate before the full run (performance SOP).
- The single stream is the bound, so no parallelism. Shorten the floor only by a 5m rate probe if
  latency proves not to bind.
- Storage, estimated from 341k rows per name today: at most about 430M 5m rows (about 17 GB) and
  about 180M derived rows (about 7 GB).

The feature scope does not widen. 5m features remain the todo 445 decision. At today's 69% share,
5m features for all names would be about 390 GB, and this design does not authorize that.

## 6. Ground-truth gates

One computed report: D7 (`services/bar_reconciliation_audit.py`) is extended as its single writer.
It writes one verdict row per (symbol, timeframe, check) into the existing `integrity_monitor`
(`monitor_type = 'bar_integrity'`, `subject = '<symbol>|<tf>'`, `passed`, `metric_value`,
`threshold_value`). Prometheus keeps check-only labels.

| Check | Rule | Threshold |
|---|---|---|
| `session_coverage` (1d) | Bars plus answered-empty sessions over NYSE sessions since first bar | `threshold.bar_integrity.session_coverage_min_1d` 0.999 |
| `slot_coverage` (intraday, per year) | Real plus answered-empty RTH slots over expected | `threshold.bar_integrity.slot_coverage_min_intraday` 0.995 (measured 2007-2023 level 0.996) |
| `policy_conformance` | Every visible row's source matches the policy, or is an admitted fallback | zero |
| `lineage_missing` | Visible 1d bars with no lineage match | zero |
| `canonical_recompute` | Recomputed 1d canonical equals stored, bit-exact | zero |
| `digest_fresh` | Recomputed digest equals stored for checked ranges | zero |
| `coverage_cache` | `ohlcv_coverage` equals its rebuild | zero |
| `unexplained_seam` | Canonical close-to-close jump with no corporate action (existing D7 rule) | existing D7 keys |
| `vendor_basis_run` | Run of at least `threshold.bar_integrity.vendor_ratio_run_min_sessions` (5) where the vendor ratio leaves the tolerance, classified by which vendor is continuous | reported; blocks only when the canonical side is the discontinuous one |
| `grid_parity` | Derived vs archived vendor buckets | exact for 15m |
| `stray_vendor_rows` | Vendor 15m/1h rows in `market_data_ohlcv` | zero (gates 186 only) |
| `report_age` | Verdict newer than the latest `ohlcv_load` for the series | `threshold.bar_integrity.report_max_age_hours` 30 |

Zero-tolerance checks are definitions, not APR values. Every other value is a new APR key, seeded
`[initial_estimate]` except the slot coverage floor (`[rca_analysis]`). None are ML learning
targets.

The promote script requires every 1d check to pass and be fresh for `compute_1d`, and the same for
5m, 15m and 1h for `compute`. `rebuild_preconditions.check_d2_landed` and `check_bar_coverage` read
the same rows. `backfill_status.fetch_complete` stops being a gate today and the table is deleted
once its readers move (section 9).

## 7. Hidden-bias and silent-failure register

| Risk | Treatment | Caught by |
|---|---|---|
| Survivorship | Disclosed, carried (todo 376, descoped 2026-09-26) | D0 survivorship label |
| Current-holdings universe | The universe is today's names; snapshots pin the symbol list | Snapshot manifest; D0 label |
| Vendor restatement | Latest answer wins; old values kept | `ohlcv_revision`; revision-ratio refusal |
| Adjustment basis (splits, spin-offs) | Both vendors deliver split-adjusted history as of fetch. Spin-off treatment differs and is unverified; prices are never spliced across a basis run | `vendor_basis_run`; `unexplained_seam`; `corporate_action` |
| Dividends | Price-only bars; total return via `dividend_events_reconciled` (todo 428) | D7 dividend freshness |
| Session calendar | NYSE mcal with half days and DST (`src/intelligence/bars/sessions.py`) | Grid tests; `slot_coverage` |
| Late listing, venue moves | IBKR 5m starts at the last venue move, so 5m may start years after 1d | D7 `late_heads`; D0 venue label |
| Volume definitions | 1d is consolidated (Tradier); intraday is IBKR SMART. Cross-timeframe volume ratios mix bases. The daily-vs-intraday volume identity is tested against IBKR 1d observations, never canonical 1d | Policy `ingress_mode` and source; D7 |
| Timestamps | UTC, stamped at bar start; availability is bar end (1d: session close) | `temporal_integrity` audit |
| Complete-case selection | Answered-empty slots are not holes, so thin names are not dropped | Coverage definition |
| Silent first-write-wins | Removed | Write-contract tests |

To keep the fallback and basis checks fed, IBKR 1d SMART is fetched for every name every
`infra.backfill.ibkr_1d_reconcile_interval_days` (7) into D1, never canonical for Tradier names.
That is about 75 minutes of stream time a week at the 1d rate.

## 8. Failure modes and tests

What fails loud:
- A refused load (exit non-zero, `ohlcv_load.outcome = 'failed'`).
- A missing policy row (the derivation raises).
- A verdict that fails or goes stale, which blocks promotion and the rebuild.
- The fetcher's `sla_breached`.

Tests:
- CI boundary: the existing `market_data_ohlcv` writer boundary, extended so that no ingress path
  writes a `derived` timeframe and only the daily stage writes 1d.
- A new CI scan that fails on `ON CONFLICT DO NOTHING` against bar tables.
- Pure unit tests:
  - The unified rule on fixtures: RJF, REX, the DAL head, an interior hole on each side of the
    basis tolerance, the ETHA reverse split.
  - The write contract: the same answer twice gives zero writes; one changed bar gives one row and
    one revision.
- Integration tests on `indicagent_test` under the real roles, never the live database (todo 494).
- Bit-exact repro: the nightly `canonical_recompute` and digest checks. `repro_frozen` applies to
  any edit under `src/intelligence/research/` or `statistics/`.

Alarms: the D7 Grafana panel exists. Add alert rules for any failing `bar_integrity` verdict,
`report_age` breach, fetcher `sla_breached`, Tradier refusals above zero, and any revision-ratio
refusal.

## 9. Migration path

Ordered; each step ships alone.

| Step | Work | Owner | Rollback | Storage |
|---|---|---|---|---|
| 1 | Stop vendor 15m/1h fetches (two APR writes) | ops, recorded in 189-07 | restore APR values | stops archive growth |
| 2 | 185-28, 185-32, 185-34 as planned; 185-31 amended | 185 | per plan | none |
| 3 | Unified 1d rule `d2-v2`, `bar_source_policy`, single 1d writer, lineage view, widened `ohlcv_load`/`ohlcv_revision`; re-derive all 1,502 names (the 236 move to Tradier) | new 185-36 | dump `canonical_bar_lineage` before drop (kept 30 days); canonical values restore from `ohlcv_revision` by load | -1.2 GB lineage |
| 4 | Integrity report verdicts, promote gate switch, `fetch_complete` retired as a gate | 185-33 amended | gate code revert; verdict rows are additive | small |
| 5 | Vendor basis study on known answers (RJF, REX, IBM, BDX, LEN, ETHA) and exception policy rows | new 185-37 | close policy rows | none |
| 6 | Verify the first fired runs of the 189 timers instead of restarting the nightly | 185-35 replaced | none | none |
| 7 | Write contract in the fetcher (compare-and-write, request digests); deletions; `backfill_status` dropped after readers move | 189-07, 189-08 amended | dump `backfill_status` before drop | none |
| 8 | 5m pilot, then the full fetch; per-name grid derivation, parity, vendor rows out | new 189-10 | per-name re-derive; archive keeps vendor rows | +17 GB 5m, +7 GB derived, -1.6 GB vendor |
| 9 | `VACUUM FULL ohlcv_observation` after the dedupe | in 185-36 | none needed | reclaim measured first |
| 10 | 186-26 gate reads verdicts for all promoted names; runs once, after step 8 | 186-26 amended | per plan | per plan |
| 11 | Docs: CLAUDE.md, onboarding SOP promote gate, glossary terms | 189-09 amended | revert | none |

Plans replaced or amended:
- 185-27: done. Its D1 elision and changes-only writes stay; its loader lineage writes and
  tradier-v1 are superseded in step 3.
- 185-30: applied. Its digest repair and legacy-flag retirement stand; its lineage rows are
  superseded by the view.
- 185-31: amended to record differing archive observations in `ohlcv_revision`
  (`origin = 'archive_segment'`) instead of creating `ohlcv_intraday_raw_revision`.
- 185-33: amended. `lineage_value_mismatch` becomes `lineage_missing`, and the scope grows to the
  full verdict report in section 6.
- 185-35: replaced. The nightly timer stays disabled, because 189-06 cut over to the fetcher,
  Tradier and D7 timers. ETHA's split is already recorded (`tradier_refetch`, 2026-10-06).
- 185-28, 185-29, 185-32, 185-34: unchanged. 185-29's labels record the policy and verdict
  as-of.
- 186-26: amended gate and timing. 186-27 and 186-28: unchanged.
- 189-07, 189-08, 189-09: amended as above.
- New plans: 185-36, 185-37, 189-10.

Research stays paused until step 10's gate passes. The 186 rebuild runs once, on final bars, not
before and after the 5m backfill.

## 10. Deletions and non-goals

Deleted:
- The `canonical_bar_lineage` table (a view replaces it).
- The Tradier loader's canonical write and rule tradier-v1.
- Vendor 15m/1h fetching outside the parity sample.
- `ON CONFLICT DO NOTHING` bar writes and grid rewrites of unchanged segments.
- `backfill_status` and the `fetch_complete` gate.
- The planned `ohlcv_intraday_raw_revision` table.
- The nightly timer restart.
- The second-writer allow-list entry for the Tradier loader.

Non-goals:
- Delisting capture.
- Futures.
- New vendors (Stage V).
- 5m features for all names (todo 445).
- Per-row provenance columns on hypertables.
- Bitemporal storage of each bar.
- The streaming path.
- 1m and extended-hours research grids. 1m (9.8M rows) and 4h (2,184 rows) are kept and not
  fetched.

## Open risks

- Vendor adjustment semantics are inferred from ratios, not documented. Tradier's spin-off
  handling especially may move many names to exception rows in step 5.
- The 5m fetch duration depends on gateway stability. 2FA hangs (todo 395) have stalled it for
  hours before.
- Step 3 revises the 1d history of the 236 names and the interior bars. It must land before 186-26
  or the rebuild pays twice.
- IBKR's intraday revision window is unmeasured beyond 185-31's sample. A trailing refetch window
  may be needed to capture final values.

## Verification status of claims

Verified live or in code: every number in the measured-state table; the RJF and REX values; the
schemas and constraints named; the write semantics of `_intraday_persist.py`; the 189-06 timer
state; ETHA's `corporate_action` row.

Unverified:
- Which vendor is correct for the IBM, BDX and LEN runs.
- Whether D2's daily stage already skips unchanged rows.
- The grid stage's rewrite cost per name (taken from the redesign doc).
- The 5m duration and the storage projections (estimates from the stated rates).
- The lineage view's query cost.
- The bloat `VACUUM FULL` would reclaim.

Verified by plans 185-46 to 185-48 (2026-10-07 and 2026-10-08): the last Tradier 1d observation
is 2026-10-06 on all 1,529 names; the Tradier live API answers HTTP 401 (orchestrator check,
2026-10-08); after the
swap no source writes a Tradier row (7,161,155 TRADIER observations, 6,689,979 canonical tradier
1d bars, counted equal before and after 185-48's deletions); d2-v2 and D7 still read the TRADIER
route through `src/intelligence/bars/sources.py`.

## Amendment 2026-10-07

Author: Claude (Opus 5.5), 2026-10-08, recording the owner's decision of 2026-10-07
Status: owner decision, implemented by plans 185-46 to 185-48

The Tradier account is unfunded and will not be funded. Section 2's decision "1d: primary
Tradier for every name, fallback IBKR SMART TRADES" is superseded by shape F, forward from D
(`docs/research/1d-primary-swap-evidence.md`, rule R1):

- D = 2026-10-07, the first NYSE session after the last Tradier bar (2026-10-06). The default 1d
  row (primary Tradier, fallback IBKR) is closed at D and a new default (primary IBKR SMART
  TRADES, no fallback) opens at D (migration 456, live 2026-10-08 16:03:53 UTC).
- History before D is unchanged: Tradier's bars stay canonical before D, read by d2-v2 through
  the TRADIER route, and keep full standing in the verdict gate and in rebuilds.
- Per-name rows only where the evidence decides. Class B (the vendors disagree recently) got no
  new row: all 8 already held a 185-38 IBKR row, and Task 1b's refresh made them class A. Class C
  (too little common history): MOD and QRVO get hold rows that keep Tradier primary with IBKR
  fallback; EU already held an IBKR row.
- The counts that decided it (185-47 rerun after the IBKR 1d fetch for the names without SMART
  history): class A 1,526, B 0, C 3. Criteria C1 to C8 held on every name except CTVA, which is
  held (todos 515 and 516).
- Volume basis. IBKR SMART counts less volume than Tradier. Over the last 250 common sessions,
  per name, the median IBKR/Tradier ratio has p10 0.409, p50 0.528 and p90 0.807 (1,528 names);
  the yearly median fell from about 0.95 (2006 to 2013) to about 0.54 (2025, 2026). Canonical 1d
  volume therefore steps at D for every name at once, to about half its Tradier level, by a
  different factor per name. The ratio is recorded in the new default row's evidence and is
  never rescaled or spliced.

Residual risks, each with a todo:
- Tradier history after a split. d2-v2 serves a stale-scale primary observation with the
  `pre_split_unrefetched` flag and never falls back to the restated IBKR answer. No Tradier
  re-ask exists, so the first split of a name with Tradier bars before D quarantines that whole
  history (todo 517).
- The volume basis change at D: research volume features and the S0 data-quality labels must
  treat D as a basis change (todo 518; the gate rides with todo 501).
- Frozen names: PSKY, WBD and QRVO fail IBKR contract qualification and MOD's IBKR fallback is
  not admitted, so each stops at its last Tradier bar; PSKY, WBD and QRVO fail `freshness_1d`
  today and MOD will once more than two sessions pass (todo 519).

The Tradier loader, its units, its provider module, its Settings fields, D7's `tradier_refused`
check and its alert, and the `infra.tradier.*` APR keys (migration 457) are deleted. A second or
replacement 1d vendor is the deferred Stage V item of D-01 and is not added.
