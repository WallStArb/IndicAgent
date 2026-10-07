# Canonical Truth Registry

**Version:** 3.2
**Status:** current
**Last Updated:** 2026-10-07
**Tags:** data-ownership, canonical-source, streams, persistence, writer-agents, kafka

**Archival note:** Rows describing the I1-I7 plugin tier, the typed intelligence bus
(`intelligence_features`, `FeatureWriter`), and the Signal Ledger Architecture (`signal_events`
/ `trade_frames`/`trade_executions`/`signal_ledger`) describe the **v2.x pipeline — archived, no
live consumer as of 2026-07-02** (see `CLAUDE.md` Architecture section). They are retained below
for historical ownership record, not as live behavior. The v3.0 pipeline
(`feature_vectors` → kernel forward returns → `feature_ic_scores_v2` via `ic_measure`;
the old `forward_returns` table was dropped by migration 430, phase 186 plan 23)
is the live canonical set.

This registry defines which stream/table owns each durable business fact. Any new table, stream, read model, or cache must either appear here or explicitly declare that it is a derived projection.

Core rule: **one canonical writer per durable fact**. Read models may duplicate data for query speed, but they must never become a second source of truth.

## Ownership Table

| Entity | Canonical stream | Canonical table | Canonical writer | Notes |
|---|---|---|---|---|
| Raw provider bars | `{env}.market.bars.raw.{provider}` | None | Provider-specific `Provider` | Provider payloads are immutable protocol translations. |
| Streaming 1m/5m bars | `{env}.market.bars` | `market_data_ohlcv` | `BarWriter` | `ProviderMerger` selects the authoritative stream event; writer persists. Limited to 1m and 5m, and dormant while the IBKR live feed is down. Never writes 1d, 15m or 1h (phase 185). |
| Historical 1m/5m bars | None (batch) | `market_data_ohlcv` | `infrastructure_run_historical_pipeline.py` (`backfill_feature_factory.py --fetch-only` for the rebuild) | Provider bars as fetched, real rows only (no synthetic fill since 185-18; table rebuilt from real rows by 185-25). |
| Daily observations (D1) | None (batch) | `ohlcv_request`, `ohlcv_observation` | `services/ohlcv_observation_writer.py` under role `ohlcv_observation_writer`, called by the fetch paths (IBKR historical pipeline, Tradier loader) | Every provider answer, per route and what_to_show; requests log no_data/timeout/failed too. Mutable since migration 438. Test callers (`test-...`) are provenance-excluded by every reader. |
| Canonical 1d bars | None (batch) | `market_data_ohlcv` (timeframe 1d) | `bar_derivation` (`services/bar_derivation.py --stage daily`, rule `d2-v2`), the only 1d writer since plan 185-38; the Tradier loader lands D1 and chains it | Source per date from `bar_source_policy` (Tradier primary by default; IBKR-primary exception rows on evidence, `ops_source_policy.py`). Lineage is the `canonical_bar_lineage` view (migration 447): the latest equal observation of the bar's source route, derived on read. Loads in `ohlcv_load`, replaced values in `ohlcv_revision`. |
| Canonical 15m/1h bars (derived grid) | None (batch) | `market_data_ohlcv` (source `derived_5m`) | `bar_derivation` (`--stage grid`) | Rebuilt from tradeable 5m bars on session edges; the IBKR 15m/1h answers go to `ohlcv_intraday_raw_archive` (same writer). Single-writer CI fence: `tests/unit/test_market_data_ohlcv_writer_boundary.py`. |
| Bar scrub flags and quarantine | None (batch) | `bar_quality_flag` | `services/bar_scrub.py` (run by bar_derivation's daily stage and the historical pass) and bar_derivation (constituent and split flags) | Flag, never delete (D-09): quarantine rules hide a bar from `market_data_ohlcv_tradeable`; the bar is never edited. |
| Corporate actions (splits) | None (batch) | `corporate_action` (read `corporate_action_current`) | `ops_seam_audit.py`, `ops_split_detect.py` (nightly overlap), Tradier loader (refetch split) | Append-only; one fact type with three inference paths, each tagged by `inferred_by`, corrections supersede. All write under `bar_derivation_writer`. |
| Listing venue (D6) | None (batch) | `listing_venue` | `services/listing_venue_writer.py` | Point-in-time `[valid_from, valid_to)` spans, no overlap; reconstructed history, the only update closes an open span (migration 408). |
| Bar content digest | None (batch) | `bar_content_digest` (read `bar_content_digest_current`) | `bar_derivation` | Per (symbol, timeframe, month) checksum with the rule version; append-only. |
| Derivation provenance | None (batch) | `bar_derivation_batch` | `services/bar_derivation_batch.py` (`open_batch`/`close_batch`, called by every derivation-side writer) | One row per run: stage, rule version, code commit, APR snapshot. |
| Roll events | `{env}.market.events.roll` | `contract_metadata` | `roll-batch` nightly timer (`scripts/ops/roll/ops_roll_batch.py`) | Calendar-based roll detection; promotes front-month contract; broadcasts Kafka update events. |
| Full I1-I7 feature record *(v2.x, archived)* | `{env}.intelligence.journal` | `intelligence_features` | `FeatureWriter` | Canonical per-bar feature persistence unit. No live consumer as of 2026-07-02. |
| Signal detection (SLA) *(v2.x, archived)* | `{env}.intelligence.i7.signals` | `signal_events` | `SignalWriter` | Detection layer: one row per I7 plugin fire. Fields: `raw_confidence`, `factor_scores`, `context_features`, `ctf_score`, `ctf_confirmed`, `zone_friction_score`, `status`. |
| Trade hypotheses (SLA) *(v2.x, archived)* | `{env}.intelligence.i7.signals` | `trade_frames` | `SignalWriter` | Hypothesis layer: one row per `entry_type` per signal. Fields: `entry_type`, `entry_price`, `stop_price`, `target_price`, `counterfactual_pnl_r`, `was_selected`. |
| Trade executions (SLA) *(v2.x, archived)* | execution event from `stream_keys.py` | `trade_executions` | `ExecutionWriter` | Execution layer: one row per live trade. Fields: `actual_pnl_r`, `actual_fill_price`, `exit_reason`. |
| Signal lifecycle transitions *(v2.x, archived)* | lifecycle transition topic from `stream_keys.py` | `signal_events.status` | `LifecycleWriter` | Tracker computes transitions; writer updates status on `signal_events`. Valid transitions: `pending` → `active`, `pending` → `regime_suppressed`, `active` → `expired`. |
| SLA query surface *(v2.x, archived)* | None | `signal_ledger` (view) | — | Join view across all three SLA tables (renamed from `signal_ledger_full` in Phase 130). Legacy monolith and `signal_outcomes` were dropped in Phase 130 — no separate read-only table remains. |
| Signal-affecting lineage *(v2.x, archived)* | `topic_signal_lineage()` | `signal_lineage` | `LineageWriter` | Canonical audit trail for transforms and swarm `agent_prediction` events. |
| Signal performance metrics *(v2.x, archived)* | signal metrics topic from `stream_keys.py` | `signal_metrics` tables | `SignalMetricsWriter` | Metrics compute may read canonical outcomes; writer persists metrics. |
| Quant-facing context cache | None | `intelligence_features.ctx` | `FeatureWriter` or optional bridge job | Denormalized projection only; not canonical truth. |
| LLM call audit | `{env}.llm.calls` | `llm_calls` | `LLMWriter` | Every call, including failures, is training/audit data. |
| LLM outcomes | `{env}.llm.outcomes` | `llm_calls` outcome columns | `LLMWriter` | Outcome backfill annotates historical call records. |
| Narratives | `{env}.narratives` | `llm_calls` / narrative projection | `LLMWriter` | Narrative text is explanatory, not a production signal unless promoted separately. |
| Shadow transitions | `{env}.intelligence.shadow.transitions` | shadow governance tables | shadow writer/auditor agents | Shadow state is audit/promotion metadata. |
| v3.0 feature vectors (per-bar) | `{env}.intelligence.feature_vectors` | `feature_vectors` | `FeatureWriter` | 54-scalar typed feature primitives per bar. No JSONB — all columns. IC Engine reads this; never writes to it. |
| v3.0 regime labels (per bar) | None (batch UPDATE) | `feature_vectors.regime` | `RegimeWriter` | HMM Viterbi per-(symbol,tf) sequence; UPDATEs `feature_vectors.regime` and `regime_label_source`. Single canonical writer — IC Engine reads but never writes regime. |
| v3.0 outcome labels (forward returns) | None (kernel compute) | *(none — `forward_returns` dropped by migration 430, 186-23)* | `panel.forward_returns` kernel via `ICMeasure` | Causal log returns `ln(open[T+N+1]/open[T+1])` at 1/5/20/60 bar horizons. The old `ForwardReturnWriter`/table were deleted in phase 186 plan 23; targets are computed with the kernel, never stored as a label table. |
| v3.0 IC scores (per feature×symbol×tf×regime×lookahead) | None (batch INSERT) | `feature_ic_scores` (frozen; fresh rows to `feature_ic_scores_v2`) | `ICEngine` (deleted 186-23; `ICMeasure` writes v2) | Spearman IC + bootstrap CI + BH-FDR + walk-forward results. Legacy table frozen, dropped whole by 186-28. |
| v3.0 IC discovery report | None (file write) | `docs/analysis/ic-discovery-report-{date}.md` | `ICEngine` | Markdown report of features passing FDR + walk-forward gates by regime and TF. Written at end of each IC Engine run. Not a DB table — filesystem artifact. |

<!-- src: signal_events table, trade_frames table, trade_executions table, signal_ledger view (renamed from signal_ledger_full, Phase 130) — verified 2026-09-04 -->
<!-- alpha_ensemble_ic, ensemble_alpha, alpha_events: rows removed; tables dropped by migration 426 (186-22) -->
<!-- forward_returns row repointed at the kernel; table dropped by migration 430 (186-23) -->
<!-- bar rows rewritten 2026-10-06 (phase 185 plan 24): BarWriter limited to streaming 1m/5m; bar_derivation owns 1d, 15m, 1h -->
<!-- v3.0 rows added 2026-06-21: feature_vectors, regime labels, forward_returns, feature_ic_scores, IC discovery report -->

## Provider matrix

Two price providers (IBKR, Tradier) and one reference-data provider (Yahoo). Each row is one (provider, timeframe): the request route and stored source values, the tables it writes and the writer. Plan 185-32, 2026-10-07; 185-43 rewrites it for d2-v2.

| Provider, timeframe | Route and source | D1 (`ohlcv_request`, `ohlcv_observation`) | `ohlcv_load`, `ohlcv_revision` | `market_data_ohlcv` | `ohlcv_intraday_raw_archive` | Writer |
|---|---|---|---|---|---|---|
| IBKR 1d | Routes `SMART`, the former listing venues (`NYSE`, `ARCA`, `ISLAND`, `AMEX`, `BATS`) and `LEGACY_IMPORT`; what_to_show `TRADES` and `ADJUSTED_LAST`; observation source `ibkr` | Every answer, through `services/ohlcv_observation_writer.py` | Not yet: bar_derivation's daily stage records a load from 185-38 | Canonical source `ibkr_named` (or `ibkr_venue` for a pre-venue-move span) for names Tradier does not own; lineage rule `d2-v1` | No | Fetch: the IBKR history fetcher (phase 189; stopped and disabled, owner decision). Bars: `bar_derivation --stage daily` |
| Tradier 1d | Route `TRADIER`, what_to_show `TRADES`; source `tradier` | Changed bars only (185-27 elision), through the observation writer | One `ohlcv_load` row per load (destination `d1`); refetch splits in `corporate_action` | The policy's primary 1d vendor; the daily stage derives canonical bars from it | No | `infrastructure_run_tradier_daily.py` |
| IBKR 5m | `SMART` `TRADES`; source `ibkr_named` | Request record only (`ohlcv_request`, answered windows) | No | Real provider bars only, stored as fetched (no fill) | No | The IBKR history fetcher (paused, todo 462); `backfill_feature_factory.py --fetch-only` for the rebuild (raw bars, 5m and 1m only) |
| IBKR 1m | `SMART` `TRADES`; source `ibkr_named` | Request record only | No | Real provider bars only | No | Same as 5m; dormant (not in the fetcher's default scopes) |
| IBKR 15m and 1h | `SMART` `TRADES`; vendor observations | Request record only | Differing observations of an archived bar in `ohlcv_revision`, origin `archive_segment` (185-31) | Readers see source `derived_5m` from `bar_derivation --stage grid`; vendor `ibkr_named` rows remain only for names the grid stage has not yet replaced, and leave the table after a value match against the archive | Every vendor answer, through `services/intraday_raw_archive.py` | No longer fetched (migration 445: default scopes stop vendor 15m and 1h); the archive is frozen as the parity reference |
| IBKR 4h | `SMART` `TRADES`; source `ibkr_named` | No | No | Real provider bars only since 185-32 (2,184 legacy rows); the design derives 4h from 5m | No | No default scope fetches it |
| Yahoo | Dividends only, never a price | No | No | No | No | `dividend_events` (read through `dividend_events_reconciled`) |

**No synthetic_fill exists.** The store holds real rows only since the 185-25 swap (zero synthetic_fill rows). Two fences keep it so: migration 444's CHECK constraint `market_data_ohlcv_no_synthetic_fill` refuses an insert or update with that source (NOT VALID in the catalog, because TimescaleDB refuses VALIDATE on a columnstore hypertable; the ADD checked every chunk), and `tests/unit/test_market_data_ohlcv_no_synthetic_fill.py` fails CI on any synthetic_fill row build. The fill path itself (`normalize_bars`) is deleted: plan 189-08 removed its last caller and plan 185-42 the function.

**Placeholder-coverage gap readers.** Three readers once counted stored placeholders as coverage; they now see real rows only, so a slot with no real bar reads as a gap (185-25 accepted the one-time re-asks). None needs a code change today; phase 189's `ohlcv_coverage` ledger replaces gap planning (todo 499):

| Reader | Timeframe | State |
|---|---|---|
| `scripts/infrastructure/backfill/_d1_gaps.py` (`detect_gaps_from_record`) | 5m (also 15m, 1h) | Paused with the 5m fetch (todo 462); answered windows stop a definitive no_data span from being re-asked |
| `infrastructure_run_historical_pipeline.py` `detect_gaps` (legacy grid difference) | 1m | Dormant: 1m is not in any default scope |
| `services/bar_auditor.py` | 1m | Unit disabled |

## Signal Ledger Architecture (SLA) Note *(v2.x — archived, no live consumer as of 2026-07-02)*

The SLA replaced the legacy `signal_ledger` monolith beginning Phase 128. The three-table design separates concerns that the monolith conflated:

- **`signal_events`** — detection layer: did the pattern fire?
- **`trade_frames`** — hypothesis layer: what trade was proposed? (ML training target via `counterfactual_pnl_r`)
- **`trade_executions`** — execution layer: what was actually traded?

**Query surface:** `signal_ledger` is the join view across all three SLA tables (renamed from `signal_ledger_full` in Phase 130). The original legacy monolith and `signal_outcomes` were dropped in Phase 130 — there is no separate deprecated table still pending removal.

**See also:** `docs/foundation/glossary.md` — SLA, ECL, ICC entries.

## Projection Rules

- A projection must name its canonical source stream/table.
- A projection may lag or fail without blocking the canonical writer.
- A projection must be rebuildable from canonical sources.
- A projection must not mutate canonical source tables.
- Consumers must tolerate missing projections with graceful degradation.

## Adding A New Canonical Fact

Before adding a new durable fact, document:

| Question | Required answer |
|---|---|
| What is the fact? | Business-level description, not implementation detail. |
| Which stream is canonical? | Topic function from `src/core/stream_keys.py`. |
| Which table is canonical? | Table name, or `None` if stream-only. |
| Which agent writes it? | Exactly one writer/owner. |
| Is it replay-safe? | Explain offset-0/backfill behavior. |
| Is it event-time valid? | Include `valid_from` / `valid_to` if applicable. |
| What are projections? | Caches/read models and their rebuild path. |
