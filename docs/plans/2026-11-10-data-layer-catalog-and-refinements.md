# Data layer catalog and refinements (Massive era)

Author: session indicagent-22, 2026-11-10, at the owner's request
Status: draft for review, revised once after an adversarial review (Opus subagent, 2026-11-10; 1 blocker and 8 material findings, all folded in). Design only: no code, no DB writes, no migrations.
Informed by: live read-only schema and row-count queries (2026-11-10), `docs/plans/2026-11-10-massive-admission-db-design.md`, `.planning/todos/pending/600-massive-flat-files-all-history-vendor.md`, `docs/reference/data-adjacency-register.md`, `docs/foundation/glossary.md` (`availability time`), the Massive REST docs (overview, all tickers, custom bars, trades, short interest pages read 2026-11-10), a read-only listing of the Massive flat-file bucket.

## 1. Purpose

One catalog of what the data layers hold today, what Massive adds (the files already downloaded, the REST API our plan covers, the other flat-file datasets), and which refinements are worth making. The plan lapses about 2026-12-10, so anything wanted from Massive must be captured raw before then. Test for every item: does it shorten the path to a counted test or protect its integrity (root CLAUDE.md goal). Items that fail are listed as skipped.

## 2. What we hold today

Counts are from the live database, 2026-11-10 (hypertable counts are estimates).

| Layer | Tables | State |
|---|---|---|
| Raw bars | `ohlcv_raw` (about 650M rows; vendors ibkr, alpaca, tradier; 1m to 1d), `ohlcv_revision` (28M), `ohlcv_restatement_flag` (576) | one table, last-wins, revision log; single writer (ingress contract) |
| Canonical bars | `market_data_ohlcv` (a hypertable of about 596M rows, a selection written from raw, not a view), `bar_source_policy` (1,901), `bar_session_choice` (1.2M), `bar_content_digest` (3.1M), `bar_quality_flag` (12.9M), `bar_hold`, `market_data_gaps`; views `canonical_bar_lineage`, `bar_content_digest_current`, `market_data_5m`, `ohlcv_venue_head`, `ohlcv_ask_current` | selection is a function of raw plus policy; flags never delete |
| Fetch and load ledgers | `ohlcv_request` (296k; ibkr 98.7k, alpaca 190.4k, tradier 6.5k; written today), `ohlcv_load` (372k), `ohlcv_coverage` (ibkr 5,039, alpaca 3,058, tradier 1,529 stale), `ohlcv_provider_head` (3,060, ibkr only), `ohlcv_empty_history` (673, ibkr only), `bar_derivation_batch`, `provenance_batch` | lineage and completeness |
| Corporate actions | `corporate_action` (405 rows, 400 non-void, 394 current, 281 names; append-only with supersedes; four of five `inferred_by` codes in use, `seam_audit` unused), `dividend_events` (148k: yahoo 102.8k and `ibkr_adjusted_last_ratio` 45.9k, the latter inferred from adjusted prices; columns `ex_date`, `amount`, `prev_close`, `source`, `compute_version`, `derived_at`), `dividend_event_coverage`, `dividend_date_dispute`; view `dividend_events_reconciled` | splits are thin: AAPL's 2014 and 2020 and NVDA's 2006, 2007, 2021 and 2024 are missing |
| Instrument identity | `instruments` (1,551; 1,529 active), `instrument_metadata` (166 rows; `listing_date`, free-text `issuer` on 163), `contract_details` JSON, `listing_venue` (974 point-in-time spans), `listing_end` (5 rows: acquired 3, merged 1, taken_private 1; `delisted` allowed and unused; written only by migrations 518 and 546, no code writer) | no CIK, FIGI, CUSIP or ISIN in any column, `contract_details` key or `provider_meta` |
| Classification and tags | `classification_*` (scheme indicagent_v1, 118 nodes), `instrument_classification` (1,551), `tag_vocabulary` (72), `instrument_tags` (4,867), `instrument_annotations` (2,753: 2,695 TagCalibrator, 58 human theses) | point in time, append-only; the annotations are the ITR evidence trail and never a deletion candidate |
| Economic series | `economic_series_observation` (235k; fred, nyfed, yahoo) with `observation_date`, `available_at`, `availability_basis`, `fetched_at`; view `economic_series_observation_current` | 235,198 of 235,212 rows are `assumed_lag` (todo 482): the convention exists, the true release times mostly do not |
| Other reference | `borrow_availability_snapshots` (symbol, as_of, vendor, shortable_shares), `roll_events`, `contract_metadata`, `macro_features` (empty), `factor_series_correlation` | small |
| Not data layers (one line each) | `corpus_run*`, `research_run*`, `integrity_monitor`, `config_schema`, `config_state`, `config_history`, `config_outbox`, `concept_*`, `vocabulary_group*`, `controlled_vocabulary`, `classification_scheme`, `shadow_registry`, `market_regimes` (5.4M, derived), `market_regimes_override`, `feature_vectors`, IC tables, event and DLQ logs | out of scope |

## 3. What Massive adds

### 3.1 Already on disk

`data/massive/files/` (82 GiB, verified): `minute_aggs_v1` and `day_aggs_v1`, 5,829 trading days each, 2003-09-10 to 2026-11-09, all tickers, extended hours included, unadjusted. Columns: ticker, volume, open, close, high, low, window_start (ns), transactions. Serve times (LastModified, ETag) per key in `data/massive/manifest/servetimes_*.jsonl`.

### 3.2 The REST API (covered by the plan; read 2026-11-10)

Groups: tickers (all tickers with a point-in-time `date` parameter and `active=false` plus `delisted_utc` for delisted names; ticker overview with identifiers; related tickers); aggregate bars; snapshots; trades and quotes (tick level, to 2003-09-10 on our tier); technical indicators; market operations (exchanges, condition codes, holidays that only look forward); corporate actions (splits, dividends with declaration, record and pay dates and `historical_adjustment_factor`, IPOs from 2008, ticker events marked experimental); fundamentals (balance sheet, cash flow, income, ratios, short interest from 2017-12-29 every two weeks, short volume, float); filings and disclosures (EDGAR index, 10-K sections, 8-K text, Form 3 and 4, 13F, insider data); news with sentiment. History depth and point-in-time behaviour are stated only for the pages named above; every other claim is unverified until a capture reads it.

### 3.3 Other flat-file datasets in the bucket

Entitlement checked 2026-11-10 with a small ranged GET on one 2024-06 file per dataset. Readable (206): `us_stocks_sip/trades_v1` (4.1 TB) and `us_stocks_sip/quotes_v1` (15 TB). Not entitled (403, separate subscriptions): every `us_options_opra` dataset, `us_indices`, `us_futures_*`, `global_forex` and `global_crypto`.

Tick data is out of scope (owner 2026-11-10: 1m bars are ample for the timeframes we target). A reduce-and-discard capture was considered and rejected the same day: features and compute will change, and a reduced copy could never be recomputed, which breaks the keep-raw rule. If a tick-level hypothesis ever appears, trades and quotes need a fresh purchase and storage decision at that time.

## 4. Refinements

Ordered by value to the goal.

R1. Capture reference responses to disk now, as served; a database table waits for a consumer. Following the flat-file ruling (the files as delivered are the keep-everything artifact), responses go to `data/massive/reference/` with a manifest recording endpoint, normalized parameters, page index, the response Date header and sha256. The API key is stripped from any stored URL. A typed projection table is built only when a base feature or the admission design reads it, with its own registered writer and a parser `compute_version`; the generic JSONB landing table in the admission design (section 6, reference table) stays the target shape for that step and is not built before then. Capture grain: tickers listing monthly and at change points plus `active=false` once (a per-date answer over 5,829 dates would be about 60M records and adds nothing the day files do not already show); ticker overview per ticker with `date` set inside each of its spans, so a reused ticker returns its own entity; splits, dividends, IPOs and ticker events once per ticker or in bulk as the API allows.

R2. Time convention for reference tables: follow the glossary `availability time` entry, do not coin a new one. A reference row carries its domain date (`ex_date`, `settlement_date`, `observation_date`), `available_at` with `availability_basis` (`release_record`, `declared_rule` or `fetch`), and `served_at` (the vendor's response time, as in `ohlcv_raw`; for flat files, LastModified). Short interest is the live temporal-integrity case (keyed by settlement date, published later). The missing dividend declaration, record and pay dates limit features rather than integrity (an ex-date amount is knowable before the ex-date), so adding them is a feature decision, made when a base feature needs them.

R3. Identity in three levels, the point-in-time ticker map and the ticker-reuse failure: already designed, see admission design section 6 and todo 600 refinement item 1. No change here.

R4. Point-in-time membership from the tickers endpoint: capture only (R1). `listing_end`, `corporate_action`, `dividend_events` and `ohlcv_raw` all have a foreign key to `instruments`, so a dead name has nowhere to go until stage 2 onboards it through `onboard_instrument()`. Membership means "listed per the endpoint on date d", never "has bars in the files" (onboarding SOP rule 1 bans selecting on data availability); it is a population, not a selection rule, and a stage-2 universe rule needs a point-in-time size measure and an owner-approved SOP exception.

R5. Massive splits and dividends as a witness. Capture raw (R1), reconcile against `corporate_action` (admission design section 5), fix the calendar gap from it. `corporate_action` writers are segmented by `inferred_by` (single-writer registry test), so `massive_reference` needs its own registered writer segment. Massive splits used to rescale Massive bars are not independent evidence of the split dates: the third-witness rule (admission design section 8a) applies before the capture fills the calendar alone.

R6. Dropped. Condition codes matter only if ticks are loaded (the vendor already applied them in the aggregates), and the CVR holds codes our own code validates. The raw capture of conditions and exchanges stays in section 6 as a small static file.

R7. Already planned, see todo 600 refinement items 2 to 4 and admission design section 7: `trade_count` (Massive `transactions`, Alpaca `n`) and Alpaca `vw` as nullable raw columns kept out of compute until a consumer exists; definition epochs; session calendar as data. Calendar check: the 5,829 day files match the code calendar exactly, so the files are a standing witness for historical sessions (Massive's holiday endpoint is forward-only).

R8. Reference features, decided per field after R1 lands and only when a base feature would read it (data adjacency register discipline): short interest, short volume, float, IPOs, parsed 8-K and Form 4 text. Each needs its availability time read from a real response before any feature uses it. Fundamentals: the register rejects income statements only (`filing_date` is the latest filing, not the original); balance sheet, cash flow, ratios and float are unverified, not rejected, and float is likely current-only.

R9. Dropped (owner 2026-11-10): tick data is not pivotal and 1m bars are ample for the targeted timeframes; reduce-and-discard is rejected (section 3.3).

Skipped, with reason: technical indicators (derivable from bars), snapshots and last-trade calls (live-only), REST bars (the flat files are the as-served archive), market holidays (forward-only), news sizing (no consumer exists), options, futures, crypto and forex flat files (outside the equity scope).

## 5. Simplifications this enables

Facts verified 2026-11-10:
- `ohlcv_request` stays: it is the lineage spine (`ohlcv_raw.request_id`, `corporate_action.evidence_request_ids` and `canonical_bar_lineage` refer to it) with about 30 code readers.
- `ohlcv_coverage` stays (read by the API routes and `instrument_onboarding.py`); its 1,529 Tradier rows are residue.
- `ohlcv_provider_head` (read by `vendor_arbitration.py` and the fetch queue) and `ohlcv_empty_history` (read by `gap_plan.py`, `integrity_checks.py`, `corpus_rerun_data_gate.py`, `rebuild_preconditions.py`) are IBKR-specific; they go with the IBKR pre-2016 leg in the post-admission deletion list (todo 600, open item 4, Opus-reviewed before anything runs).
- `instrument_annotations` is not a candidate (R1 table above).

## 6. Before the plan lapses

| Item | Action | Cost | By |
|---|---|---|---|
| Reference set: tickers (monthly, change points, `active=false`), ticker overview per span, ticker events, splits, dividends (with `historical_adjustment_factor`), IPOs, related tickers | capture to disk, as served (R1) | small | well before 2026-12-10 |
| Short interest, short volume, float, exchanges, condition codes | capture to disk | small | before lapse |
| Filings (EDGAR index, 8-K, Form 4) | size one month, then decide (EDGAR direct stays the clean source for original dates) | unknown | decision by 2026-12-01 |
| Offsite copy of the flat files | owner's second machine, pending setup | 82 GiB | before lapse |

## 7. Open questions

1. R1: confirm disk capture now and the typed projection later, against building the JSONB landing table before a consumer exists.
2. R4: is stage 2 (dead names in the universe) wanted before the first counted test, or capture-only for now.
3. R8: which reference features (short interest, float, filings) justify more than a raw capture, given no consumer exists yet.
