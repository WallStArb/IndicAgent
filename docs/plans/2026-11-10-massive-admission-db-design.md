# Massive admission: database-side onboarding design

Author: session indicagent-22, 2026-11-10, at the lead's assignment (indicagent-d8), for todo 600's admission
Status: ruled by the lead (indicagent-d8, 2026-11-10; section 11), after an adversarial review (Opus subagent) whose findings are folded in. This is the admission-day execution plan. Design only: no code, no DB writes, no migrations until the owner's admission verdict.
Informed by: `.planning/todos/pending/600-massive-flat-files-all-history-vendor.md`, `docs/plans/2026-11-09-massive-pilot-basis-study.md`, `docs/plans/2026-10-12-unified-raw-bar-table-design.md`, `docs/foundation/canonical-truth-registry.md`, `src/intelligence/bars/{vendor_kind,vendor_ingress,selection,daily_rule,integrity_checks}.py`, `services/{bar_load,ohlcv_ingress_contract}.py`, `scripts/ops/bars/{ops_source_policy,ops_bar_load}.py`, the downloader `scripts/infrastructure/massive/massive_download.py`, read-only schema and data queries (2026-11-10).

Applies only after the pilot verdict is "admit" or "admit with named caveats". Nothing here touches the downloader, the pilot comparison scripts or `data/massive/`.

## 1. Scope

Todo 600's admission: vendor and kind codes in `ohlcv_raw`, the reader and 5m aggregation, the adjustment basis, the ticker to entity map, the `bar_source_policy` switch, and the documents that move with it. Out of scope: offsite backup (waits on the owner's destination), the post-admission deletion list (its own doc, Opus-reviewed before anything executes), and post-2016 consolidation onto one vendor (a later measured decision).

## 2. Facts that shape the design

- Archive: `minute_aggs_v1` (86.8 GB) and `day_aggs_v1` (1.0 GB), 5,829 trading days each, 2003-09-10 to date. Columns `ticker, volume, open, close, high, low, window_start, transactions`; `window_start` in nanoseconds. About 7,700 tickers and 0.85M minute rows per 2003 day. Dotted tickers (BRK.B, HEI.A) match our stored symbols.
- `ohlcv_raw.symbol` has a foreign key to `instruments(symbol)` (1,551 rows, 1,529 active). 338 of 341 raw chunks are compressed.
- Every stored price is split-adjusted (onboarding SOP, "Price-only bars"; Alpaca kinds by definition). Massive files are unadjusted. The daily rule already rescales unadjusted series from `corporate_action_current` (`daily_rule.py` d2-v5 path), so a corporate-action input to selection has precedent for 1d; 5m selection has none.
- IBKR pre-2016 5m holds zero-volume bars (89,165 of 732,880 in a four-name sample); Massive has no row for a bucket without trades.
- Alpaca SIP is Polygon's feed, the same upstream as Massive. From 2016 Massive agreeing with Alpaca is expected, not independent evidence (flag for the pilot runbook).
- The downloader (committed 07c70a806) records key, size, sha256 and `downloaded_at` in its manifest and skips a file whose size matches. The vendor's LastModified and ETag per key are captured out of band in `data/massive/manifest/servetimes_*.jsonl`.

## 3. Vendor and kinds

CVR `bar_vendor` code `massive` (who served the bar; Alpaca-via-Polygon stays `alpaca`). CVR `bar_kind` codes:

| kind | meaning | timeframe |
|---|---|---|
| `sip_flat_agg` | Massive minute aggregates cut to the NYSE regular session and aggregated to 5m by our reader (section 4); unadjusted | 5m |
| `sip_flat` | Massive day aggregate as served; unadjusted | 1d |

Both are session-bound kinds: `sip_flat_agg` joins `SESSION_BOUND_KINDS` in `selection.py`, whose `partition_session` already drops off-grid stamps. No new session-cut mechanism. The 1d kind is confirmed by the pilot's 1d arm: if Massive day bars differ from the regular-hours aggregate of its minute bars on any of open, high, low, close or volume beyond the pilot tolerance (extended-hours trades are the likely cause), 1d is instead built from the regular-hours minute rows under kind `sip_flat_agg` at 1d, and the served day file stays archived only.

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

## 5. Adjustment basis

Raw stores Massive bars as served (unadjusted). Canonical stays split-adjusted on today's convention, so selection rescales Massive-sourced rows by the split factors in `corporate_action_current`. This extends the d2-v5 precedent from 1d to 5m.

- Pin: `corporate_action` is append-only, so the batch record stores the `recorded_at` horizon (or batch id) of the corporate-action rows the selection read. No snapshot hash. `ops_selection_gate --compare` reads the same horizon and gains the rescale, or it reports every Massive row as a difference.
- Canonical kind: canonical copies the raw (vendor, kind), and about 15 scripts join canonical back to raw on it. A canonical Massive row holds adjusted prices, so it carries canonical kind `sip_flat_adj` via `_CANONICAL_KIND_FOR_RAW`, and the raw join maps it back explicitly. The kind never says unadjusted for adjusted prices.
- Missing splits. D7 `split_continuity` checks recorded splits only. A split missing from `corporate_action` (394 rows today) would leave an unseen step in canonical. Two gates before step 5: reconcile Massive's splits endpoint against `corporate_action` for every mapped name (differences listed, recorded under a new `inferred_by` code `massive_reference`, which needs the CHECK widened), and a seam detector run over the Massive raw series for steps with no recorded split.
- Late splits. A split recorded after selection changes the factor for the whole earlier history. The split writer's commit triggers a reselect of every Massive-sourced span of that name before its next canonical read; until that runs, D7 holds the name (a new required check `split_horizon_fresh`: the selection's pinned horizon covers every split row of the name).
- Daily rule: the 1d stale-scale logic must rescale Massive 1d by every recorded split, not only `calendar_audit` rows, or it quarantines Massive 1d. This is a rule version bump with its own review.

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

Stage 1 deepens and cross-checks the history of current names. It does not remove survivorship, because the universe is still current names. The caveat lifts only at stage 2 (historical instrument rows for dead names, a point-in-time membership table, the key rule for reused tickers, an owner-approved SOP exception). The caveat wording moves in the step 7a commit and says this, citing the presence rate the pilot measured (runbook A8).

Glossary entries first: `issuer` (CIK, LEI), `security identifier` (share-class FIGI, CUSIP, ISIN, dated, append-only), `ticker_event` (dated span of a ticker string on a security). Reuse `listing_venue` and `listing_end`. Massive and IBKR reference responses are stored raw as served (vendor, endpoint, key, as-of date, body, served_at; last-wins with revision).

## 7. Definition epochs

A small append-only dated table per vendor and column recording a change of meaning: Massive volume fractional from 2026-02-23 (rounded per bucket), the 23/5 SIP session from 2026-12-06 (regular-hours cut unchanged). Read by the loader to tag rows and by feature code that must not mix definitions. Lands with admission; glossary entry first.

## 8. Switch sequence

Current defaults (2026-11-10): 5m `ibkr` [1990-01-01, 2016-01-04), `alpaca` with `ibkr` fallback from 2016-01-04; 1d the same; 15m and 1h `derived`; 1m `ibkr`; 4h closed. Append-only table, EXCLUDE on overlap among unretired rows, no vendor CHECK.

0. Preconditions: pilot verdict recorded; downloader serve-time changes in and the full archive verified against the manifest; offsite backup done; glossary entries landed; the IBKR 5m backfill timer stopped; fetcher timers quiet during canonical rewrites.
1. Migration: CVR codes, the APR key, the `inferred_by` CHECK, definition-epoch, identity and reference tables. Applied live and committed together.
2. Code, each its own plan with /simplify, /review and the unit suite: the reader; the vendor and kind maps of section 3; the session-bound kind; the canonical-kind map; the 5m rescale in selection and in `ops_selection_gate --compare`; the `split_horizon_fresh` D7 check; the mapping retract path; `--valid-to` on `ops_source_policy --reselect-only`.
3. Reference load (Massive and IBKR) and ticker spans. Gate: every instrument has a span or is on the gap list.
4. Split reconciliation and seam detection (section 5). Gate: no unexplained difference.
5. Raw load, per year, newest first, 5m then 1d. The load engine runs selection on every chunk, and while Massive is unranked every Massive-only slot reports as unselected (status UNSELECTED, not APPLIED). Gate per year: unselected equals the Massive-only on-grid slots counted from the manifest; row balance (traded minutes in, bars out, unmapped excluded and counted); `ops_selection_gate --compare` unchanged.
6. Full-scale basis gates over loaded raw: the pilot's price, scale-factor and OHLC gates per name-year for every mapped name. A name outside a gate is listed and keeps its incumbent.
7. Policy, through `ops_source_policy --plan` (it already retires and re-tiles defaults) then `--reselect-only` per year:
   a. 5m before 2016-01-04: Massive primary with no fallback. The default IBKR fallback would undo the switch: selection judges a vendor complete against every slot any ranked vendor holds, and IBKR's zero-volume bars in buckets Massive correctly lacks would make Massive incomplete and hand whole sessions to IBKR. Names and spans on the gap list keep IBKR through symbol rows. Missing is NaN.
   b. 1d before 2016-01-04: the same shape, after the daily-rule version bump. The 1d plan must name all 95 live IBKR 1d symbol rows, pin the two default ids and carry the raw fingerprint, as `--plan` requires.
   c. Re-derive the 15m and 1h grid over the changed span.
8. Docs move in the step 7a commit (section 9). After each step: `ops_selection_gate --compare` on the changed series, D7 on a sample then all names; `repro_frozen` only if research or statistics code moved (it should not).
9. The corpus rerun stays behind the data-complete gate (186-32); admission does not open it.

Raw IBKR pre-2016 rows stay permanent; only selection changes.

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
- Planning: todo 600 to completed; 534, 544 and 607 resolved per their rulings; `PRIORITIES.md` rows; `STATE.md`; the pilot runbook status.

Every reference to a moved or deleted path is repaired in the same commit (CI-enforced).

## 10. Invariant check

- `single_writer`: ingress contract writes raw, selection writes canonical, one reference loader writes the identity and reference tables.
- `lineage`: raw rows carry `load_id`; the load detail holds file key, ETag and sha256; each Massive load records its `ticker_event` id.
- `determinism`: canonical is a function of raw, policy and the pinned corporate-action horizon.
- `point_in_time`: spans, identifiers, policy and splits are dated; a row is never read outside its span.
- `no_fill`: traded minutes only; no bar for an empty bucket; no IBKR fallback filling Massive sessions.
- `temporal_integrity`: raw serve time is the vendor's LastModified, never our download time.

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
5. **Adopted into the pilot**: the 1d arm compares full OHLCV, not close only; and the 2016+
   Alpaca agreement is same-upstream corroboration (Alpaca SIP is the same Polygon feed), not
   independent evidence - the verdict weights the pre-2016 IBKR arm and the internal OHLC
   consistency accordingly. Routed to the running pilot.
6. Deferred to stage 2, as drafted.
