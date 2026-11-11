# Massive admission: database-side onboarding design

Author: session indicagent-22, 2026-11-10, at the lead's assignment (indicagent-d8), for todo 600's admission
Status: ruled by the lead (indicagent-d8, 2026-11-10; section 11), after an adversarial review (Opus subagent) and the refinement review (`docs/plans/2026-11-10-massive-admission-refinement-review.md`, d386cac3a), both folded in as dated amendment notes. This is the admission-day execution plan. Design only: no code, no DB writes, no migrations until the owner's admission verdict.
Informed by: `docs/plans/2026-11-10-massive-admission-refinement-review.md`, `.planning/todos/pending/600-massive-flat-files-all-history-vendor.md`, `docs/plans/2026-10-12-unified-raw-bar-table-design.md`, `docs/foundation/canonical-truth-registry.md`, `src/intelligence/bars/{vendor_kind,vendor_ingress,selection,daily_rule,integrity_checks}.py`, `services/{bar_load,ohlcv_ingress_contract}.py`, `scripts/ops/bars/{ops_source_policy,ops_bar_load}.py`, the downloader `scripts/infrastructure/massive/massive_download.py`, read-only schema and data queries (2026-11-10).

Runs on the owner's admission call (bundled with the law 528 amendment, section 11). Nothing here touches the downloader or `data/massive/`.

## 1. Scope

Todo 600's admission: vendor and kind codes in `ohlcv_raw`, the reader and 5m aggregation, the adjustment basis, the ticker to entity map, the `bar_source_policy` switch, and the documents that move with it. Out of scope: offsite backup (waits on the owner's destination), the post-admission deletion list (its own doc, Opus-reviewed before anything executes), and post-2016 consolidation onto one vendor (pulled forward, see the section 8 amendment of 2026-11-11).

## 2. Facts that shape the design

- Archive: `minute_aggs_v1` (86.8 GB) and `day_aggs_v1` (1.0 GB), 5,829 trading days each, 2003-09-10 to date. Columns `ticker, volume, open, close, high, low, window_start, transactions`; `window_start` in nanoseconds. About 7,700 tickers and 0.85M minute rows per 2003 day. Dotted tickers (BRK.B, HEI.A) match our stored symbols.
- `ohlcv_raw.symbol` has a foreign key to `instruments(symbol)` (1,551 rows, 1,529 active). 338 of 341 raw chunks are compressed.
- Every stored price is split-adjusted (onboarding SOP, "Price-only bars"; Alpaca kinds by definition). Massive files are unadjusted. The daily rule already rescales unadjusted series from `corporate_action_current` (`daily_rule.py` d2-v5 path), so a corporate-action input to selection has precedent for 1d; 5m selection has none.
- IBKR pre-2016 5m holds zero-volume bars (89,165 of 732,880 in a four-name sample); Massive has no row for a bucket without trades.
- Alpaca SIP is Polygon's feed, the same upstream as Massive. From 2016 Massive agreeing with Alpaca is expected, not independent evidence (section 8a).
- The downloader (committed 07c70a806) records key, size, sha256 and `downloaded_at` in its manifest and skips a file whose size matches. The vendor's LastModified and ETag per key are captured out of band in `data/massive/manifest/servetimes_*.jsonl`.

## 3. Vendor and kinds

CVR `bar_vendor` code `massive` (who served the bar; Alpaca-via-Polygon stays `alpaca`). CVR `bar_kind` codes:

| kind | meaning | timeframe |
|---|---|---|
| `sip_flat_agg` | Massive minute aggregates cut to the NYSE regular session and aggregated to 5m by our reader (section 4); unadjusted | 5m |
| `sip_flat` | Massive day aggregate as served; unadjusted | 1d |

Both are session-bound kinds: `sip_flat_agg` joins `SESSION_BOUND_KINDS` in `selection.py`, whose `partition_session` already drops off-grid stamps. No new session-cut mechanism. The 1d kind is settled by the day-against-minute check (section 8a): if Massive day bars differ from the regular-hours aggregate of its minute bars on close on more than 1 percent of names in any era (extended-hours trades are the likely cause), 1d is instead built from the regular-hours minute rows under kind `sip_flat_agg` at 1d, and the served day file stays archived only.

The `_agg` kind amends the unified design's "raw holds what the vendor served only": a reader may store an aggregate of a finer served timeframe under a kind that says so. Todo 600's storage ruling already decided this (5m aggregated by us, 1m loaded only on demand); the amendment text goes into the unified design in the same commit.

Code that must name the new vendor and kinds before any load (each read raises on an unmapped pair today): `LABEL_TO_VENDOR_KIND`, `VENDOR_SERVED_KINDS`, `BAR_KINDS` (`vendor_kind.py`); the source label and route (`sources.py`); `VOLUME_BASIS_BY_VENDOR_KIND`; `RAW_DAILY_SERIES` and `RAW_DAILY_SESSION_ZONE` (daily rule); the canonical-kind map (section 5).

APR: one key, `infra.massive.artifact_max_answer_lag_days` (section 4). The rounding rule, the one-traded-minute bucket rule and the session cut are definitions, not tunables, so they are code constants with a test, not APR keys (a switch on any of them would change canonical without a reselect). Chunk size reuses `bar_load.CHUNK_ROWS`.

## 4. Reader, aggregation and serve time

No `history_leaf("massive")`: the fetch stage is the downloader plus its manifest, which is also the completeness proof. A pure Ring 1 reader (`src/intelligence/bars/massive_flat.py`) turns one day file into per-ticker 5m frames:

1. Cut minutes to the NYSE regular session first (open inclusive, close exclusive, early closes from `nyse_sessions`, including the irregular 15:56 close of 2005-06-01). Cutting before aggregation keeps an after-close minute out of the last bucket.
2. Bucket by the 5-minute floor of `window_start` in UTC; whole-hour ET offsets align the buckets with 09:30 and the 13:00 early closes (checked on all 52 such sessions).
3. Per bucket from traded minutes only: first open, max high, min low, last close, summed volume. A bucket with no traded minute has no bar (no fill).
4. Volume: sum the minute volumes (fractional in files from 2026-02-23), then round half to even once per bucket, in the reader. `frame_to_raw_rows` does `int(v)`, which truncates, so the reader hands it integers. The column stays bigint; changing it would be a compressed-hypertable migration for at most half a share per bucket. The fractional values stay in the archived file, and the change is recorded as a definition epoch (section 7).
5. `transactions` is not loaded now.

`VendorIngress`: the Massive row's `read_artifacts(dir, symbols)` reads a day range and filters to mapped symbols. One ingress call loads one day file group, so `answered_at` is per file, not per symbol.

Serve time and restatement. Raw is last-wins by serve time, so every row needs the vendor's serve time, not our download time. LastModified and ETag per key are in `data/massive/manifest/servetimes_*.jsonl`; `answered_at` is LastModified from there. Still open in the downloader: re-fetch when the ETag changes, not only when the size changes, and keep the superseded file beside the new one (archive as delivered). `ops_bar_load` checks `answered_at` against the Alpaca lag key, which a years-old file fails; the Massive row uses `infra.massive.artifact_max_answer_lag_days` instead, and the check becomes "LastModified is after the file's trading day", since a historical file is legitimately served years later.

Lineage: each `ohlcv_load` row records the file key, ETag and sha256 in its detail, so a bar traces to the exact file bytes.

Amendment 2026-11-10 (refinement review d386cac3a): the load path joins the downloader manifest to `servetimes_*.jsonl` on ETag and fails loudly on mismatch; a mismatched key means the recorded LastModified is not the serve time of the file on disk, and `answered_at` (temporal integrity, section 10) would be silently wrong. The downloader's ETag-based re-fetch (still open above) is load-bearing for the nightly-update decision too: it stays a step 0 precondition, and the size-skip path must not fire on an ETag change with equal size.

## 5. Adjustment basis

Raw stores Massive bars as served (unadjusted). Canonical stays split-adjusted on today's convention, so selection rescales Massive-sourced rows by the split factors in `corporate_action_current`. This extends the d2-v5 precedent from 1d to 5m.

- Pin: `corporate_action` is append-only, so the batch record stores the `recorded_at` horizon (or batch id) of the corporate-action rows the selection read. No snapshot hash. `ops_selection_gate --compare` reads the same horizon and gains the rescale, or it reports every Massive row as a difference.
- Canonical kind: canonical copies the raw (vendor, kind), and about 15 scripts join canonical back to raw on it. A canonical Massive row holds adjusted prices, so it carries canonical kind `sip_flat_adj` via `_CANONICAL_KIND_FOR_RAW`, and the raw join maps it back explicitly. The kind never says unadjusted for adjusted prices.
- Missing splits. D7 `split_continuity` checks recorded splits only. A split missing from `corporate_action` (394 rows today) would leave an unseen step in canonical. Two gates before step 5: reconcile Massive's splits endpoint against `corporate_action` for every mapped name (differences listed, recorded under a new `inferred_by` code `massive_reference`, which needs the CHECK widened), and a seam detector run over the Massive raw series for steps with no recorded split.
- Rescale rule (owner-lead ruling 2026-11-10). Selection applies every `corporate_action_current` row with action_type `split` or `reverse_split`, effective_date on or after the bar's session date, `recorded_at` at or before a pinned horizon, and effective_date not after the horizon's New York date (a split not yet executed must not rescale history: real prices at the horizon are still pre-split). The horizon is an explicit `horizon` parameter of `select_and_write` and `--horizon` of `ops_selection_gate --compare`, resolved once at call start, returned in the result and recorded in the run detail; no migration. Limitation: the data carries no declaration date, so a rebuild is an as-of-horizon snapshot, and `recorded_at <= horizon` is the only point-in-time control. A Massive winner with no split row passes through unscaled but carries `sip_flat_adj`: the unreconciled-split hazard is closed by ordering (step 4 reconciliation applied and its gate passed before the step 7 policy switch), not by a marker in code.
- Late splits. A split recorded after selection changes the factor for the whole earlier history. The split writer's commit triggers a reselect of every Massive-sourced span of that name before its next canonical read; until that runs, D7 holds the name (a new required check `split_horizon_fresh`: the selection's pinned horizon covers every split row of the name).
- Daily rule: the 1d stale-scale logic must rescale Massive 1d by every recorded split, not only `calendar_audit` rows, or it quarantines Massive 1d. This is a rule version bump with its own review.

Amendment 2026-11-10 (refinement review d386cac3a): future-dated corporate actions exist in the captures, splits to execution date 2027-01-13 and dividends to ex-date 2030-12-13, so this section carries an announcement-time gate explicitly. Every reference-derived corporate-action row (`inferred_by = massive_reference`) carries `recorded_at` = capture time, and selection never joins a reference-derived row by effective or ex date alone; it gates on the recorded announcement time. The gate lives in the reference-derived subset, not in canonical's stored convention (adjusted on today's knowledge), which is exactly why the subset needs it.

## 6. Ticker to entity map

The risk: a ticker string is reused (AKTS, CART, EXE, DOW). Massive `EXE` in 2010 is a different company from our `EXE`. Loading it under `EXE` is a silent wrong answer, and raw is permanent.

Todo 600 says raw holds Massive keyed by ticker as of the date and the entity map joins at selection, never inside raw. `ohlcv_raw` cannot do that today: its symbol is a foreign key to `instruments`, and selection reads raw by symbol. Two ways, my recommendation first:

A. (Recommended) The archived files are the as-served, ticker-keyed record, permanent under the storage ruling. `ohlcv_raw` holds the mapped projection, loaded only inside an evidenced ticker span, and every Massive load records the `ticker_event` id it used. A wrongly mapped span is then retractable by load id: a retract path (the parked supersede tool, scoped to mapping-scoped Massive loads, logged to `ohlcv_revision` with origin `mapping_retract`) is a precondition of the first raw load. This is a written amendment to law 528 for one case (a load whose identity premise was wrong), owner-approved.

B. Drop the foreign key for vendor `massive` by storing the served ticker in raw and joining the map inside selection. Faithful to todo 600's wording, but it changes every raw-by-symbol reader and selection's key. More mechanism for the same outcome.

Mapping evidence (stage 1, current names only):

1. Anchor today's identity outside Massive: IBKR contract details give ISIN for every held instrument (free, not captured today). Massive ticker details give share-class FIGI and CIK. Match on share-class FIGI, cross-checked through ISIN. CIK alone maps the wrong share class (BRK.B, BF.B, HEI.A, MOG.A, UHAL.B are held), so it never decides.
2. Walk Massive ticker events backwards through renames, so a name's history under an earlier ticker is found, and cut where the same string changes FIGI.
3. Check price continuity against incumbent bars at each span edge, by level over the span, not by the junction step (the 592 rule).
4. A span without that evidence is a gap: the name keeps the incumbent for the span and goes on a list for the owner. Rows outside spans, and tickers with no instrument, stay in the archive only; the manifest counts them per day.

Amendment 2026-11-10 (refinement review d386cac3a): measured limits of the walk-back. Delisted rows in the tickers universe carry no identifiers (no cik, no composite_figi, no share_class_figi), and per-ticker events answer only for active tickers: 23,040 of 36,869 events responses are NOT_FOUND and all of them are delisted-format queries; all 13,829 OK responses are active queries. The 15,448 events are every one of type `ticker_change` with no from/to, so the response body's `composite_figi` is the only join key across a chain (verified: A, Agilent, BBG000C2V3D6, listing AWD to 2005-11-23 then A from 2003-09-10). The mechanism is therefore FIGI-grouping of the per-ticker events responses, not a per-ticker walk of dead tickers. The step 3 gate records the measured NOT_FOUND rate, and the loader parses body status, not HTTP status: NOT_FOUND arrives as HTTP 200 with a NOT_FOUND body. Stage 2's dead-name identifiers must come from outside Massive (SEC, hand-lists); Massive's endpoints do not answer for dead tickers.

Stage 1 deepens and cross-checks the history of current names. It does not remove survivorship, because the universe is still current names. The caveat lifts only at stage 2 (historical instrument rows for dead names, a point-in-time membership table, the key rule for reused tickers, an owner-approved SOP exception). The caveat wording moves in the step 7a commit and says this, citing the presence rate measured under section 8a. It also states the residual (refinement review d386cac3a): pre-2016 adjustment correctness rests on Massive alone plus the load checks, since there is no independent vendor comparison for the pre-2016 span.

Glossary entries first: `issuer` (CIK, LEI), `security identifier` (share-class FIGI, CUSIP, ISIN, dated, append-only), `ticker_event` (dated span of a ticker string on a security). Reuse `listing_venue` and `listing_end`. Massive and IBKR reference responses are stored raw as served (vendor, endpoint, key, as-of date, body, served_at; last-wins with revision).

Amendment 2026-11-10 (refinement review d386cac3a): the dated directory + `manifest/YYYYMMDD.jsonl` reference layout is canonical for any future capture (the undated `capture_log.jsonl` + `pageNNNN.json` layout collides on a second run). The loader ingests both manifests once, records which layout each row came from, and carries the manifest line's sha256 into the reference row's lineage (section 10). Splits and dividends exist in both captured families; both stay, as the two witnesses they already proved to be (the families agree on the AAPL and NVDA rows).

## 7. Definition epochs

A small append-only dated table per vendor and column recording a change of meaning: Massive volume fractional from 2026-02-23 (rounded per bucket), the 23/5 SIP session from 2026-12-06 (regular-hours cut unchanged). Read by the loader to tag rows and by feature code that must not mix definitions. Lands with admission; glossary entry first.

## 8. Switch sequence

Current defaults (2026-11-10): 5m `ibkr` [1990-01-01, 2016-01-04), `alpaca` with `ibkr` fallback from 2016-01-04; 1d the same; 15m and 1h `derived`; 1m `ibkr`; 4h closed. Append-only table, EXCLUDE on overlap among unretired rows, no vendor CHECK.

0. Preconditions: the owner's admission call recorded; downloader serve-time changes in and the full archive verified against the manifest; offsite backup done; glossary entries landed; the IBKR 5m backfill timer stopped; fetcher timers quiet during canonical rewrites.

   Amendment 2026-11-10 (refinement review d386cac3a): the offsite backup is DONE for the reference tree: `data/backups/massive-reference-2026-11-10/reference.tar.gz`, 530 MB, 2026-11-10, tarred so the offsite copy is one file (332k inodes would crawl a naive rsync). Serve-time currency is proven for the capture day: all 11,658 keys were re-statted on 2026-11-10 and the ETag and size diff against `servetimes_*.jsonl` was empty (`data/massive/manifest/etag_drift_2026-11-10.json`). The re-stat stays a pre-execution step: repeat it immediately before the first raw load and re-download any drift; after the plan lapses a restatement can never be repaired. The quiet rule enumerates the writers to quiesce: D7 bar audits, split detection, the dividend writer, any corpus or rerun service, and the selection gate itself; the Alpaca nightly writes raw only and may run.
1. Migration: CVR codes, the APR key, the `inferred_by` CHECK, definition-epoch, identity and reference tables. Applied live and committed together.
2. Code, each its own plan with /simplify, /review and the unit suite: the reader; the vendor and kind maps of section 3; the session-bound kind; the canonical-kind map; the 5m rescale in selection and in `ops_selection_gate --compare`; the `split_horizon_fresh` D7 check; the mapping retract path; `--valid-to` on `ops_source_policy --reselect-only`.
3. Reference load (Massive and IBKR) and ticker spans. Gate: every instrument has a span or is on the gap list. Amendment 2026-11-10 (refinement review d386cac3a): the gate records the measured events NOT_FOUND rate (section 6), and the reference load filters the bulk dividends family by venue or currency (it includes non-US tickers and currencies, sample: ticker `6866`, JPY). Neither dividend family carries a declaration date or a historical adjustment factor; float and ratios are snapshot-only, one row per ticker with no served history, so a panel can only be built by recapture cadence (measured facts in `docs/reference/massive-plan-entitlements.md`).
4. Split reconciliation and seam detection (section 5). Gate: no unexplained difference.
5. Raw load, per year, newest first, 5m then 1d. The load engine runs selection on every chunk, and while Massive is unranked every Massive-only slot reports as unselected (status UNSELECTED, not APPLIED). Gate per year: unselected equals the Massive-only on-grid slots counted from the manifest; row balance (traded minutes in, bars out, unmapped excluded and counted); `ops_selection_gate --compare` unchanged.
6. Load checks over loaded raw (section 8a), for every mapped name. A name outside a check is listed and keeps its incumbent for that span; a systemic failure stops the switch.
7. Canonical rebuild (owner 2026-11-10: start the compute bars fresh at admission, not before). Canonical `market_data_ohlcv` is a pure function of raw plus policy, so it is a rebuildable cache; `ohlcv_raw` is never touched. A drop and one-pass rebuild replaces per-year incremental reselects, because the derived 15m and 1h bars were built from IBKR's zero-volume constituents and a partial rebuild would leave a mix of old and new derivations. Nothing is dropped before admission: the D7 bar audits, split detection and the dividend writer read canonical bars, and clearing early saves nothing until Massive is loaded. Sequence:
   - Summary card first (derived data is dropped only after its card exists): row counts and content digests per timeframe and vendor, plus the derived-bar rows to be dropped. The scrub flags and the regime tables go on the deletion list; that list gets an Opus review before anything runs, since deletions are the irreversible kind.
   - Policy, through `ops_source_policy --plan` (it already retires and re-tiles defaults), applied once for all spans below.
   - Drop the derived canonical rows and rebuild every timeframe from raw in one pass. Mechanics (checked 2026-11-10: 114 chunks of 90 days, 113 compressed, 2 indexes): when every timeframe is rebuilt, `TRUNCATE` the hypertable (instant, no WAL churn, no bloat, no VACUUM). A row-level `DELETE` would decompress chunks and leave bloat. TRUNCATE takes an exclusive lock, so the step 0 quiet rule covers D7, split detection and the dividend writer. Load span-major in chunk-aligned windows through the load engine, compress each chunk as it completes, `ANALYZE` at the end.

     Amendment 2026-11-10 (refinement review d386cac3a): the 1m condition is a hard abort precondition re-run immediately before TRUNCATE, not an in-run branch. Chunks are 90-day time ranges mixing all timeframes, so keeping 1m while rebuilding the rest cannot be expressed by chunk-aligned loads; a row-level DELETE decompresses and bloats, exactly the incident class the compressed-hypertable migration rule exists for. The named fallback when the precondition fails: build the rebuilt timeframes into a new table and swap names; no improvised delete path mid-run. Also verified before TRUNCATE: no foreign key references `market_data_ohlcv` (TRUNCATE fails on referenced tables without CASCADE), and the chunk compression settings (`segment_by`, `orderby`) carry over to the rebuilt chunks, so the storage shape does not drift by accident. Measured 2026-11-10: the 1m source exists, `ohlcv_raw` vendor `ibkr` holds 9,775,958 1m rows (233 symbols, 2026-03-23 to 2026-10-01), matching canonical's 9,775,958.
   - Checks: from 2016-01-04 raw is unchanged, so the rebuild must reproduce the old canonical bars exactly (`ops_selection_gate --compare`); that tests the whole rebuild path before it is trusted. Pre-2016 changes by design. D7 on a sample, then all names.

     Amendment 2026-11-10 (refinement review d386cac3a): the byte-exact reproduction proves mechanics only. Every 2016+ span reads unchanged Alpaca/IBKR raw, so `ops_selection_gate --compare` exercises chunk alignment, the load engine, compression and the derived 15m/1h pass; it cannot see a broken 5m rescale, a broken daily-rule version bump or a misrouted Massive kind (those fire only on pre-2016 Massive rows, where Massive is primary with no fallback), and it would pass with the rescale code deleted. Three additions close that gap: (a) a seam-continuity witness at 2016-01-04, Massive 2015 into Alpaca 2016, judged by adjusted-close level continuity against the reference over the span, not by the junction step (the 592 rule): split-free names must be continuous, split-era offsets must reconcile to the corporate-action factor; (b) a unit-level rescale canary run before the data rebuild: the factor algebra on a known split (NVDA 2024-06-07 10:1) asserted against a hand-computed expected series, so the code path has a test that does not depend on data state; (c) the caveat text (section 6) states the residual explicitly: pre-2016 adjustment correctness rests on Massive alone plus the load checks, that is `corporate_action` quality and the internal witnesses (day-vs-minute, split-step detector, seam), because there is no independent vendor comparison for it.

   The policy content, per span:
   a. 5m before 2016-01-04: Massive primary with no fallback. The default IBKR fallback would undo the switch: selection judges a vendor complete against every slot any ranked vendor holds, and IBKR's zero-volume bars in buckets Massive correctly lacks would make Massive incomplete and hand whole sessions to IBKR. Names and spans on the gap list keep IBKR through symbol rows. Missing is NaN.
   b. 1d before 2016-01-04: the same shape, after the daily-rule version bump. The 1d plan must name all 95 live IBKR 1d symbol rows, pin the two default ids and carry the raw fingerprint, as `--plan` requires.
   c. 15m and 1h: derived from the rebuilt 5m in the same pass.
8. Docs move in the step 7a commit (section 9). After each step: `ops_selection_gate --compare` on the changed series, D7 on a sample then all names; `repro_frozen` only if research or statistics code moved (it should not).
9. The corpus rerun stays behind the data-complete gate (186-32); admission does not open it.

Raw IBKR pre-2016 rows stay permanent; only selection changes.

## 8b. Amendment 2026-11-11 (lead indicagent-32): Massive as the single source for the whole archive span

Decision: Massive becomes primary for 5m and 1d over the entire archive span (2003-09-10 to the archive end, 2026-11-09), not only before 2016-01-04. Reasons: one adjustment path (raw is as served and unadjusted, and our corporate-action rescale is the only adjuster, while Alpaca is adjusted as served at capture time and can carry capture-epoch seams inside one span); no IBKR zero-volume bars or cent-rounded prices; and Alpaca SIP is the same Polygon tape, so it adds no independent evidence. The plan is one month, so the archive ends at the lapse: Alpaca's nightly capture stays primary for days after the archive end, and the Massive-to-Alpaca seam sits at that date, not at 2016.

Two policy stages, in this order, so the byte-exact check keeps testing the rebuild mechanics:
1. Stage 1 is step 7 exactly as written: Massive primary before 2016-01-04, post-2016 canonical reproduced byte for byte from unchanged Alpaca and IBKR raw.
2. Stage 2 is its own `ops_source_policy --plan` after the 2016 to 2025 loads and their section 8a load checks pass: Massive primary from 2016-01-04 to the archive end, Alpaca after it and as fallback only for gap-list names, IBKR retired from selection. It gets a reselect and a `--compare` report per year (expected differences are the Alpaca capture-epoch seams and rounding, classified under 8a), and the seam at the archive end is witnessed by level continuity like the 2016 seam.

## 8a. Load checks

Owner 2026-11-10: Massive is used regardless, so there is no separate pilot and no admit or
refuse verdict. The checks below replace the pilot basis study (archived, `docs/plans/archive/2026-11-09-massive-pilot-basis-study.md`). They decide how each name and span is loaded, never whether Massive is used. Massive is the yardstick: a disagreement with IBKR or Alpaca is an incumbent defect when a third witness agrees (Massive's own continuity across eras, an exchange-official close, a filing-dated split), and unresolved otherwise. From 2016-01-04 Alpaca agreement carries no weight on units, session or scale (same upstream); IBKR is the independent arm. Survivorship is measured and disclosed (presence by era, the names missing), never a gate.

Two outcomes, nothing in between: a name or span outside a check keeps its incumbent through a symbol row and goes on the gap list; a systemic failure (units, session offset, internal consistency) stops step 7 until fixed.

| Check | Rule | Outside it |
|---|---|---|
| Identity | Ticker-as-of map for the compared names, evidence not from price (FIGI, ticker events, IBKR contract details, filings), frozen and hashed before comparison. Known corrections: MTCH is `IACI` in Massive's 2010 files, RSPF is `RYF`, QQQ is `QQQQ`. A pair with daily return correlation under 0.9 over the era is identity-unresolved, never a scale finding. | gap list |
| Adjustment factor | Never fitted from the compared series. Source: the corporate-action list frozen and hashed before comparison (Massive's splits endpoint, captured under todo 600 and reconciled per section 5, labelled non-independent). Name-eras pre-classified: no action, splits only, non-split adjustment. Price and scale checks apply to the first two; the third (IBKR `smart_trades` carries non-split adjustments no split table reproduces, 103 of 286 factor-off names in the 2010-03 probe) is a convention difference. | listed |
| Price agreement (5m and 1d) | A bar agrees when abs(Massive / factor - incumbent) is at most half the incumbent's stored price increment plus 1 bp (IBKR stores adjusted prices at cent precision: NVDA's 2010 close of 0.46 carries about 108 bp of rounding). At least 99 percent of matched bars agree per name-era and 99.5 percent vendor-wide. Disagreements classified: rounding, last-print eligibility, scale, time shift, other (above 0.5 percent vendor-wide: investigate before any switch). | name: gap list; vendor-wide: stop |
| Scale factor (the 587 class) | Per name-year, median log close ratio within 10 bp of 0 after the factor. | listed with factor and actions in window |
| 5m comparison | Window start, after the RTH cut, traded buckets only (incumbent volume above 0). Zero-volume incumbent bars and incumbent traded buckets Massive lacks are counted and listed, never assumed no-trade. | listed |
| Day file against minute file | Per era, day O, H, L, C, V against the RTH and the all-hours aggregate of the same day's minutes (2003-09-10: close differs from the RTH aggregate on 1,976 of 7,716 names, volume on 4,273). If close mismatches on more than 1 percent of names in any era, 1d is built from RTH minutes (section 3) and the served day file stays archived only. | systemic: decides the 1d kind |
| 1d census | Every held name, every session, all of O, H, L, C against incumbent 1d (the day files are about 1 GB), plus the ten sessions either side of each todo 592 disputed date (592 names and OKE). | gap list |
| Volume bands | Per era and per listing exchange, median IBKR/Massive ratio in 0.8 to 1.25 (measured p50 0.943, p1 0.537, p99 1.572); at most 2 percent of names outside 0.5 to 2.0. Name-level basis differences inside the bands stay labelled data (todo 518). | systemic: stop (units) |
| Record sanity | High at or above max(open, close) and low at or below min(open, close) on 99.9 percent of bars; price strictly positive, volume at or above zero, (ticker, window_start) unique, on minute and day files. | systemic: stop |
| Session | No systematic offset against the NYSE grid, early closes and the post-DST days included (a seeded draw of days, seed recorded, at least one early close and one post-DST day per era). | systemic: stop |
| Publish lag, manifest | Time each of the last 20 sessions' files first appeared (LastModified in `data/massive/manifest/servetimes_*.jsonl`) as lag after the 16:00 ET close; every NYSE session in the archive range has both files, parsing, with row count and sha256 (5,829 of 5,829 per dataset on 2026-11-10). | informational (feeds the nightly-update decision) |
| Survivorship | Delisted names (from `listing_end` and a hand-list): bars run through the last exchange session with a last price consistent with the delisting event; OTC afterlife is out of coverage. Presence by era and the missing names recorded. | disclosed in the caveat text |

The pilot had computed (not finalised) result tables before it was stopped: `logs/massive_pilot/` (price, scale, volume, survivorship and witness files). They are inputs a check run may reuse after confirming they were computed under the rules above; they are not a verdict.

Amendment 2026-11-10 (refinement review d386cac3a):

- Disagreement ledger. The third-witness tie-break is a record, not a convention. Each unresolved case gets a ledger row: name, span, the claimed incumbent defect, witness citations, verdict, deciding session id. The ledger states its precedence order explicitly; the recorded order: a filing-dated corporate action first, then the exchange-official close, then Massive's own continuity across eras; the 2016+ Alpaca arm corroborates and never outranks. One witness is re-anchored: Massive's own day close is an exchange-official close but it is Massive, not a third party. The independent exchange-official-close witness pre-2016 is the IBKR 1d row, which would be circular inside a Massive-internal check, so it witnesses only Massive-vs-IBKR disputes; the Massive-internal day-vs-minute check rests on Massive's own official-close status, recorded as such.
- Universe closure. The check runner emits a complete partition of the mapped universe: every mapped name carries (name, era, outcome in {pass, gap list, stop}); the per-bucket counts must sum to the mapped total; a partial run reports as partial, never as a result table.
- Alpaca capture-epoch seams. Alpaca raw is adjusted as served at capture time, so history fetched at different epochs can carry different adjustment bases inside one 2016+ span. The name-era pre-classification names this class: an Alpaca capture-epoch seam, the Alpaca sibling of the 587 IBKR `smart_trades` incumbent defect. A Massive-vs-Alpaca scale disagreement classified as an epoch seam routes through the third witness and stays out of the vendor-wide stop bucket.

## 9. Documents that move with step 7a

- `docs/foundation/canonical-truth-registry.md`: the Bar source policy row, the Roles paragraph, the provider count, the provider matrix (Massive 5m and 1d rows; IBKR loses "primary before 2016"), the canonical 1d row, the corporate-actions row (new input and `inferred_by` code).
- `docs/foundation/controlled-vocabulary-registry.md`: `bar_vendor`, `bar_kind`.
- `docs/foundation/glossary.md`: `ohlcv_raw`, `bar_vendor`, `bar_kind`, and the new terms; a survivorship entry that separates depth from universe.
- `docs/plans/2026-10-12-unified-raw-bar-table-design.md`: the `_agg` amendment. `docs/plans/2026-09-26-unified-research-to-production-design.md` (protected canonical design): its survivorship row near line 618, by an appended dated note, not an edit of frozen text.
- `docs/foundation/instrument-onboarding-sop.md`: Survivorship, Venue truncation, Price-only bars.
- `docs/foundation/adaptive-parameter-registry.md` or its backlog: the APR key.
- `docs/operations/operations-database.md`, `docs/reference/cheatsheet.md`, `docs/reference/data-adjacency-register.md`, `docs/reference/alpaca-api.md`, `docs/reference/gotchas.md` (backfill sections, since 534 stops), `docs/operations/corpus-rerun-runbook.md`, `docs/plans/2026-11-03-path-to-first-counted-test.md` (task 7, split recovery), `docs/research/correlation-regime-and-single-name-breadth-design.md`, `docs/foundation/business-requirements.md`.
- The survivorship strings in `services/corpus_rerun_data_gate.py` and `services/corpus_rerun.py`, with `tests/unit/services/test_corpus_rerun.py`.
- Root `CLAUDE.md` (pipeline line and raw-capture bullet), `src/providers/CLAUDE.md`.
- `dashboard/src/lib/copy/landing.ts` line 692 and any test that pins it.
- `indicagent-ibkr-history-fetcher.timer` disabled, with its unit docs.
- Planning: todo 600 to completed; 534, 544 and 607 resolved per their rulings; `PRIORITIES.md` rows; `STATE.md`.

Every reference to a moved or deleted path is repaired in the same commit (CI-enforced).

## 10. Invariant check

- `single_writer`: ingress contract writes raw, selection writes canonical, one reference loader writes the identity and reference tables.
- `lineage`: raw rows carry `load_id`; the load detail holds file key, ETag and sha256; each Massive load records its `ticker_event` id.
- `determinism`: canonical is a function of raw, policy and the pinned corporate-action horizon.
- `point_in_time`: spans, identifiers, policy and splits are dated; a row is never read outside its span.
- `no_fill`: traded minutes only; no bar for an empty bucket; no IBKR fallback filling Massive sessions.
- `temporal_integrity`: raw serve time is the vendor's LastModified, never our download time.

Amendment 2026-11-10 (refinement review d386cac3a): `lineage` additionally carries the reference-row manifest sha256 and the serve-time manifest-to-servetimes ETag join (section 4). `point_in_time` additionally carries the announcement-time `recorded_at` gate on reference-derived corporate actions (section 5).

## 11. Open questions - RULED by the lead (indicagent-d8, 2026-11-10)

1. Mapping: **option A** (projection with a retract path; the archive files are the as-served
   record). Same outcome as B with less mechanism; a wrong identity premise must be retractable,
   not permanent. The dated law 528 amendment (a load whose identity premise was wrong is
   retractable by load id, logged) is an owner ruling - the lead bundles it with the admission
   verdict.
2. **Confirmed**: 5m pre-2016 Massive primary with NO default fallback; IBKR serves only through
   gap-list symbol rows. Completeness is judged per vendor on real slots; a union-of-vendors
   slot set punishes the vendor that correctly has no bar (the zero-volume-bar analysis stands).
3. **Confirmed**: the 5m rescale in selection, with the late-split reselect trigger and the
   `split_horizon_fresh` D7 check. It is the largest contract change and keeps its per-plan
   review discipline; the alternative (adjusting at load) would violate raw-as-served.
4. **Done out of band**: LastModified and ETag for all 11,658 keys are captured in
   data/massive/manifest/servetimes_*.jsonl (2026-11-10, while the plan is live); the
   downloader integration (inventory fields, ETag-based re-fetch) is in flight with the builder.
5. **Adopted** (now in section 8a): the 1d arm compares full OHLCV, not close only; and the 2016+
   Alpaca agreement is same-upstream corroboration (Alpaca SIP is the same Polygon feed), not
   independent evidence - the verdict weights the pre-2016 IBKR arm and the internal OHLC
   consistency accordingly.
6. Deferred to stage 2, as drafted.

### Amendment 2026-11-10 (owner): offsite backup deferred

The step-0 precondition "offsite backup done" is DEFERRED by the owner (2026-11-10: "we aren't
backing up data yet"). The current protection state: the full 82 GB archive and the 530 MB
reference tar live locally; serve times and ETags are captured with zero drift; and the vendor
re-serves during the plan month. Offsite copy lands when the owner names a destination; it is
not a blocker for admission execution. The local reference tar
(data/backups/massive-reference-2026-11-10/reference.tar.gz) stands as captured.
