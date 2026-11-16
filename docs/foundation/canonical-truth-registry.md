# Canonical Truth Registry

**Version:** 3.5
**Status:** current
**Last Updated:** 2026-10-27
**Tags:** data-ownership, canonical-source, streams, persistence, writer-agents, kafka

**Archival note:** Rows describing the I1-I7 plugin tier, the typed intelligence bus
(`intelligence_features`, `FeatureWriter`), and the Signal Ledger Architecture (`signal_events`
/ `trade_frames`/`trade_executions`/`signal_ledger`) describe the **v2.x pipeline — archived, no
live consumer as of 2026-07-02** (see `CLAUDE.md` Architecture section). They are retained below
for historical ownership record, not as live behavior. The v3.0 pipeline
(`feature_vectors` → kernel forward returns → `feature_ic_scores` via `ic_measure`;
the old `forward_returns` table was dropped by migration 430, phase 186 plan 23)
is the live canonical set.

This registry defines which stream/table owns each durable business fact. Any new table, stream, read model, or cache must either appear here or explicitly declare that it is a derived projection.

Core rule: **one canonical writer per durable fact**. Read models may duplicate data for query speed, but they must never become a second source of truth.

## Ownership Table

| Entity | Canonical stream | Canonical table | Canonical writer | Notes |
|---|---|---|---|---|
| Raw provider bars | `{env}.market.bars.raw.{provider}` | None | Provider-specific `Provider` | Provider payloads are immutable protocol translations. |
| Raw vendor answers (every timeframe) | None (batch) | `ohlcv_raw` | `services/ohlcv_raw_writer.py`, the one writer, reached only through the ingress write contract (`services/ohlcv_ingress_contract.py`, `apply_raw_contract`); callers: the IBKR history fetcher (`scripts/infrastructure/backfill/ohlcv_history_fetcher.py`, helpers in `_history_fetch.py`) and the load engine (`services/bar_load.py`, run by `scripts/ops/bars/ops_bar_nightly.py` and `ops_bar_load.py`) | Every bar a vendor served, keyed (symbol, timeframe, `vendor`, `kind`, timestamp), last-wins by serve time: a vendor's own newer answer replaces its row and the old values go to `ohlcv_revision` (origin `raw`; an offer older than the stored answer is logged as `superseded` and raw keeps the newer one). Nothing is refused or held (D-191-N). A different vendor at the same slot is a separate row, a disagreement for selection, never a revision. The phase 185 stores `ohlcv_observation` and `ohlcv_intraday_raw_archive` (migration 499) and `market_data_ohlcv_old` (migration 501) were dropped in phase 191; their rows live in `ohlcv_raw`. |
| Fetch ledger | None (batch) | `ohlcv_request` | `services/ohlcv_request_writer.py` (role `ohlcv_observation_writer`, a name kept from phase 185), called by the fetch paths | Every request and its outcome (`bars`, `no_data`, `timeout`, `failed`), per route and what_to_show, with a content digest. Permanent lineage: Tradier-route rows stay after plan 191-20. Test callers (`test-...`) are provenance-excluded by every reader. |
| Bar source policy | None (batch) | `bar_source_policy` (read `bar_source_policy_current`) | `scripts/ops/bars/ops_source_policy.py` | Per timeframe, and per symbol for exceptions, over dated `[valid_from, valid_to)` spans: `ingress_mode` (`observed`, `direct`, `derived`), `primary_source`, `fallback_source`, reason and evidence. A row is closed once or retired (migration 520; `--retire`), never edited; readers read the current view, where a symbol row beats the timeframe default. 5m and 1d (d2-v6, in force since the step 7 rebuild, 2026-11-16): Massive primary from 1990-01-01 (so from its first file, 2003-09-10) to the archive end, 2026-11-16, then Alpaca primary, no fallback; no policy row names IBKR (`SELECT count(*) FROM bar_source_policy_current WHERE 'ibkr' IN (primary_source, coalesce(fallback_source, ''))` returns 0). Earlier rules (D-191-P, D-191-Q) are in git. 15m and 1h: `derived`. 1m and 4h: Massive only, which holds no such bar, so neither is canonical. The Tradier-era rows are closed history; no symbol row selects Tradier. |
| Canonical 5m, 1m and 4h bars (ingress mode `direct`) | None (batch) | `market_data_ohlcv` | `services/bar_selection.py` (`select_and_write`), run by the ingress contract after each raw write and by `ops_source_policy.py` and `ops_selection_gate.py` | A selection from `ohlcv_raw` by `src/intelligence/bars/selection.py`, a pure function of raw rows and the policy: each NYSE session is taken whole from the highest-ranked vendor that holds it, and every non-trivial choice (a fallback session, a session no vendor holds completely) is recorded in `bar_session_choice` (migration 480, same writer). `sip_rth` is a candidate only on the regular-hours grid; `iex_rth` and `smart_adjusted` are never selected. A replaced canonical row is not logged: raw holds both vendors' values. |
| Canonical 1d bars | None (batch) | `market_data_ohlcv` (timeframe 1d) | `bar_derivation` (`services/bar_derivation.py --stage daily`), the one 1d rule and the one 1d writer since plan 185-38 | A selection from `ohlcv_raw` per date under `bar_source_policy` by the daily rule (`src/intelligence/bars/daily_rule.py`), stored under `vendor` and `kind` (`source` retired by migration 497): `massive`/`sip_flat_adj` from 2003-09-10 to the archive end (2026-11-16), `alpaca`/`sip_rth` after it; a zero-volume bar never serves, from either vendor. The rule is d2-v6 (d2-v5 added split rescale; todo 600 added the Massive route), in force since the step 7 rebuild (2026-11-16); the daily-rule arbitration logic and the IBKR fallback (`ibkr`/`fallback`, `ibkr`/`named`) no longer select anything and remain only as vendor-label logic. The D-191-Q exceptions (spin-off-adjusted history, ticker reuse) were per-name policy rows during the 2026-10 rerun and are superseded by the one-pass rebuild. Lineage is the `canonical_bar_lineage` view (migration 447): the raw row the canonical bar equals, derived on read, never stored. |
| Write record of every bar writer | None (batch) | `ohlcv_load`, `ohlcv_revision` | The ingress write contract (migration 448, 185-39; raw-first since phase 191), called by every bar writer (`bar_derivation` daily and grid stages; the fetch paths) | One `ohlcv_load` row per series written (`caller`, `destination` `raw` or `market_data_ohlcv`; `d1` and `archive` on rows before phase 191, `batch_id`, `n_new`, `n_changed`, `n_unchanged`, `n_removed`, `n_superseded`); a changed bar's old values in `ohlcv_revision` (`origin` `raw` or `superseded` since phase 191; `load` and `archive_segment` on older rows). `ohlcv_load` rows are permanent lineage. No first-write-wins insert remains (CI: `test_bar_write_no_first_write_wins.py`). |
| Bar integrity verdicts (D7) | None (batch) | `integrity_monitor` (`monitor_type = 'bar_integrity'`, subject `SYM\|tf`, one row per check) | `services/bar_reconciliation_audit.py` (nightly timer) | The gate: promotion and the 186 rebuild read these through `src/intelligence/bars/verdict_gate.py` (185-41); a missing, failed or stale verdict holds the name. Required 1d checks: session_coverage, policy_conformance, lineage_missing, canonical_recompute, digest_fresh, unexplained_seam, alpaca_basis_run, split_continuity (todo 587: a recorded split still stepping by its ratio, or adjusted twice, fails the name) (freshness_1d gates the rebuild only; the Tradier vendor_basis_run check was retired in 191-22). |
| Canonical 15m/1h bars (derived grid) | None (batch) | `market_data_ohlcv` (vendor `derived`, kind `5m_grid`) | `bar_derivation` (`--stage grid`) | Rebuilt from tradeable 5m bars on session edges; the IBKR 15m/1h answers land in `ohlcv_raw` (the weekly parity sample samples them, `infra.backfill.grid_parity_sample_names_per_week`). Single-writer CI fence: `tests/unit/test_market_data_ohlcv_writer_boundary.py`. |
| Bar scrub flags and quarantine | None (batch) | `bar_quality_flag` | `services/bar_scrub.py` (run by bar_derivation's daily stage and the historical pass) and bar_derivation (constituent and split flags) | Flag, never delete (D-09): quarantine rules hide a bar from `market_data_ohlcv_tradeable`; the bar is never edited. |
| Corporate actions (splits) | None (batch) | `corporate_action` (read `corporate_action_current`) | `ops_split_detect.py` (nightly overlap and the sanctioned corrections of 185-51); `tradier_refetch` rows are history from the Tradier loader (deleted in 185-48), and `seam_audit` rows are history from the one-off phase 185 plan 15 audit (script deleted in 185-42; D7's unexplained_seam check replaces it); `ops_split_calendar_audit.py --apply` writes `calendar_audit` rows (migration 567, todo 587) from a committed, reviewed audit CSV, and has written none yet: the rows land only together with the daily rule that rescales them (not live; under the current rule a split row would make the pre-split span stale) | Append-only; one fact type with four inference paths, each tagged by `inferred_by`, corrections supersede. All write under `bar_derivation_writer`. |
| Listing venue (D6) | None (batch) | `listing_venue` | `services/listing_venue_writer.py` | Point-in-time `[valid_from, valid_to)` spans, no overlap; reconstructed history, the only update closes an open span (migration 408). |
| Bar content digest | None (batch) | `bar_content_digest` (read `bar_content_digest_current`) | `bar_derivation` | Per (symbol, timeframe, month) checksum with the rule version; append-only. |
| Derivation provenance | None (batch) | `bar_derivation_batch` | `services/bar_derivation_batch.py` (`open_batch`/`close_batch`, called by every derivation-side writer) | One row per run: stage, rule version, code commit, APR snapshot. |
| Full I1-I7 feature record *(v2.x, archived)* | `{env}.intelligence.journal` | `intelligence_features` | `FeatureWriter` | Canonical per-bar feature persistence unit. No live consumer as of 2026-07-02. |
| Signal detection (SLA) *(v2.x, archived)* | `{env}.intelligence.i7.signals` | `signal_events` | `SignalWriter` | Detection layer: one row per I7 plugin fire. Fields: `raw_confidence`, `factor_scores`, `context_features`, `ctf_score`, `ctf_confirmed`, `zone_friction_score`, `status`. |
| Trade hypotheses (SLA) *(v2.x, archived)* | `{env}.intelligence.i7.signals` | `trade_frames` | `SignalWriter` | Hypothesis layer: one row per `entry_type` per signal. Fields: `entry_type`, `entry_price`, `stop_price`, `target_price`, `counterfactual_pnl_r`, `was_selected`. |
| Trade executions (SLA) *(v2.x, archived)* | execution event from `stream_keys.py` | `trade_executions` | `ExecutionWriter` | Execution layer: one row per live trade. Fields: `actual_pnl_r`, `actual_fill_price`, `exit_reason`. |
| Signal lifecycle transitions *(v2.x, archived)* | lifecycle transition topic from `stream_keys.py` | `signal_events.status` | `LifecycleWriter` | Tracker computes transitions; writer updates status on `signal_events`. Valid transitions: `pending` → `active`, `pending` → `regime_suppressed`, `active` → `expired`. |
| SLA query surface *(v2.x, archived)* | None | `signal_ledger` (view) | — | Join view across all three SLA tables (renamed from `signal_ledger_full` in Phase 130). Legacy monolith and `signal_outcomes` were dropped in Phase 130 — no separate read-only table remains. |
| Signal-affecting lineage *(v2.x, archived)* | `topic_signal_lineage()` | `signal_lineage` | `LineageWriter` | Canonical audit trail for transforms and swarm `agent_prediction` events. |
| Signal performance metrics *(v2.x, archived)* | signal metrics topic from `stream_keys.py` | `signal_metrics` tables | `SignalMetricsWriter` | Metrics compute may read canonical outcomes; writer persists metrics. |
| Quant-facing context cache | None | `intelligence_features.ctx` | `FeatureWriter` or optional bridge job | Denormalized projection only; not canonical truth. |
| LLM call audit *(v2.x, dropped by migration 458)* | `{env}.llm.calls` | `llm_calls` | `LLMWriter` | Every call, including failures, is training/audit data. |
| LLM outcomes *(v2.x, dropped by migration 458)* | `{env}.llm.outcomes` | `llm_calls` outcome columns | `LLMWriter` | Outcome backfill annotates historical call records. |
| Narratives *(v2.x, dropped by migration 458)* | `{env}.narratives` | `llm_calls` / narrative projection | `LLMWriter` | Narrative text is explanatory, not a production signal unless promoted separately. |
| Shadow transitions *(v2.x, dropped by migration 458)* | `{env}.intelligence.shadow.transitions` | shadow governance tables | shadow writer/auditor agents | Shadow state is audit/promotion metadata. |
| v3.0 feature vectors (per-bar) | `{env}.intelligence.feature_vectors` | `feature_vectors` | rebuild writer (`bulk_load`) | 310 typed columns per bar (`feature_vectors_columns()` in `src/intelligence/features/feature_vector_persistence.py` derives the list; CI-checked by `tests/unit/test_doc_schema_numbers.py`). No JSONB — all columns. |
| v3.0 regime labels (per bar) | None (batch upsert) | `feature_vectors.regime`, `regime_label_source`, `regime_prob_vector` | `services/cross_sectional_regime_model.py` (upsert) | HMM walk-forward fit and assignment per regime model; upserts the three regime columns (`SET regime_label = EXCLUDED.regime_label, ...`). The former `RegimeWriter` class is deleted; this service is the single regime writer — IC measure reads but never writes regime. |
| v3.0 outcome labels (forward returns) | None (kernel compute) | *(none — `forward_returns` dropped by migration 430, 186-23)* | `panel.forward_returns` kernel via `ICMeasure` | Causal log returns `ln(open[T+N+1]/open[T+1])` at 1/5/20/60 bar horizons. The old `ForwardReturnWriter`/table were deleted in phase 186 plan 23; targets are computed with the kernel, never stored as a label table. |
| v3.0 IC scores (per feature×symbol×tf×regime×lookahead) | None (batch INSERT) | `feature_ic_scores` (migration 413 schema since migration 575) | `ICMeasure` (`ICEngine` deleted 186-23) | Spearman IC + bootstrap CI + BH-FDR per scope. The ic_engine-era table was dropped by migration 575. |
| v3.0 IC discovery report *(v2.x-era, deleted 186-23)* | None (file write) | `docs/analysis/ic-discovery-report-{date}.md` | `ICEngine` (deleted 186-23; nothing writes this report today) | Markdown report of features passing FDR + walk-forward gates by regime and TF. Written at end of each IC Engine run. Not a DB table — filesystem artifact. |
| Instrument metadata | None (onboarding) | `instruments` | onboarding services (`src/config/instrument_onboarding.py`, `src/core/database_manager.py` insert path); never hand-written rows | Base instrument rows and metadata; the onboarding SOP (`docs/foundation/instrument-onboarding-sop.md`) owns how a name enters; dead names are never deactivated by hand. |
| Tags and tag vocabulary | None (calibration) | `tag_vocabulary`, `instrument_tags` | `TagCalibrator` for machine rows; human rows are never expired or overwritten | ITR (`docs/foundation/instrument-tag-registry.md`); materiality gates through `is_materiality_eligible()`, never `passes_materiality` alone. |
| Config state and history | None (config writes) | `config_state`, `config_history`, `config_schema` | `ConfigService` (`src/config/config_service.py`) | APR (`docs/foundation/adaptive-parameter-registry.md`); every write records `changed_by` and `reason` in `config_history`. |
| Research run ledger | None (runner) | `research_run` | the S6 ledger (`src/intelligence/research/ledger.py`) | Sole writer of research_run (unified design E15-E18); every counted backtest is a row here. |

<!-- src: signal_events table, trade_frames table, trade_executions table, signal_ledger view (renamed from signal_ledger_full, Phase 130) — verified 2026-09-04 -->
<!-- alpha_ensemble_ic, ensemble_alpha, alpha_events: rows removed; tables dropped by migration 426 (186-22) -->
<!-- forward_returns row repointed at the kernel; table dropped by migration 430 (186-23) -->
<!-- bar rows rewritten 2026-10-06 (phase 185 plan 24): BarWriter limited to streaming 1m/5m; bar_derivation owns 1d, 15m, 1h; BarWriter deleted 2026-11-14, todo 614 row 7 -->
<!-- v3.0 rows added 2026-06-21: feature_vectors, regime labels, forward_returns, feature_ic_scores, IC discovery report -->

## Provider matrix

**Step 7 done, 2026-11-16 (transition annotation of 2026-11-13, owner rulings; runbook `docs/operations/massive-step7-runbook.md`):**
canonical `market_data_ohlcv` was dropped and rebuilt from raw in one pass under the d2-v6 policy: Massive from 2003-09-10 to the archive end (2026-11-16), Alpaca after it, no fallback and no IBKR. D1 `--verify` exited 0 (rows after: 5m 452,992,974, 1d 6,308,315, 15m 158,174,558, 1h 43,631,204; 1m and 4h hold none by construction), the 5m selection gate met the B3 criteria (exit 3: no residue other than 290 unreviewed basis flags), the archive-end seam witness left no name unexplained (1d and 5m: 0 of 1,403 names, all one_sided), and D4 passed (`split_horizon_fresh` 1,529 pass, 0 fail). IBKR raw rows remain until Part F deletes those at or after 2003-09-10 (the 672,245 earlier 1d rows stay in raw only, never canonical; ledger E22). Tradier was removed with migration 589 (2026-11-12; code at tag `archive/tradier-2026-11`). The IBKR rows below describe raw, not canonical.

Two price providers in force (Massive, Alpaca), IBKR as raw only until Part F, and one reference-data provider (Yahoo); Tradier is removed. Each row is one (provider, timeframe): the route and the raw `(vendor, kind)` it is stored under, what canonical takes from it, and the writer. Rewritten for phase 191 (2026-10-27): every answer lands in `ohlcv_raw`, every write leaves an `ohlcv_load` row and a request leaves an `ohlcv_request` row, so those columns are dropped. Canonical takes from raw by `bar_source_policy`; the selection rule is the same for every vendor, so a source change is a policy row, not code.

Roles. Massive (Polygon.io's consolidated SIP feed, renamed Massive.com 2025-10-30) is the canonical historical vendor: its flat files serve 1d and 5m from 2003-09-10 to the archive end, 2026-11-16, and every slot in that span is selected from them (`(massive, sip_flat_adj)`); it holds no 1m or 4h bar, so those timeframes are not canonical. Alpaca SIP (history floor 2016, the same consolidated basis) serves 5m and 1d after the archive end, and its nightly capture is raw-only until then. There is no fallback vendor: a slot Massive or Alpaca does not hold is a gap, never a placeholder. Massive is the yardstick: an incumbent-defect call needs a third witness (owner rulings of 2026-11-13). IBKR (raw `(ibkr, *)` kinds) is retained as raw only until Part F, which deletes its rows at or after 2003-09-10; the 672,245 earlier 1d rows stay in raw as the only history before Massive's first file and are never selected. Tradier answered nothing after 2026-10-06 and its rows were deleted by plan 191-20 and migration 589. Extended-hours bars are raw only. History of the earlier roles (D-191-P, D-191-Q, the Tradier-era arbitration) is in git and in `docs/plans/2026-10-12-unified-raw-bar-table-design.md`.

| Provider, timeframe | Route and raw `(vendor, kind)` | Canonical `market_data_ohlcv` | Writer |
|---|---|---|---|
| Massive 1d | Flat day aggregates as served (unadjusted) as `(massive, sip_flat)`; reference captures in `reference_raw` | `(massive, sip_flat_adj)` for every slot from 2003-09-10 to the archive end (2026-11-16), split-rescaled by the daily rule (d2-v5 onward) | Capture: `scripts/ops/bars/ops_massive_load.py` through the ingress contract (`MASSIVE_1D`); the nightly leaf `ops_massive_nightly` stays off until the plan renewal call. Canonical: `bar_derivation --stage daily` |
| Massive 5m | Minute files cut to the regular session as `(massive, sip_flat_agg)`; extended-hours bars stay raw | Every slot from 2003-09-10 to the archive end, canonical kind `massive`/`sip_flat_adj` (D1 card: 426,346,945 rows; `alpaca`/`sip_rth` 26,646,029 rows after the archive end) | Capture: `ops_massive_load.py` (`MASSIVE_5M`). Canonical: `services/bar_selection.py` from the policy, written by the 2026-11 rebuild |
| Alpaca 1d | `ALPACA`, SIP, split-adjusted, as `(alpaca, sip_rth)` | Every slot after the archive end; raw only before it | Capture: `ops_bar_nightly.py` (unit `indicagent-alpaca-nightly`, 04:40 UTC), raw only; the load engine refuses a 1d policy write. Canonical: `bar_derivation --stage daily` |
| Alpaca 5m | `ALPACA` SIP as `(alpaca, sip_rth)` (regular hours selected; extended-hours stamps kept in raw); feed=iex as `(alpaca, iex_rth)`, raw only, never selected | Every slot after the archive end; raw only before it | `ops_bar_nightly.py` (unit `indicagent-alpaca-nightly`, 04:40 UTC; the window ends `infra.alpaca.sip_recent_lag_minutes` (20) before now because the free plan refuses recent SIP; APR `infra.alpaca.*`); deep history through the same script with a wide `--days` window (`ops_bar_load.py --vendor alpaca` replays a saved parquet artifact). Canonical by `bar_selection` in the same transaction |
| IBKR, all timeframes | `SMART` `TRADES` and the other IBKR kinds as `(ibkr, *)`, raw only; the fetcher, gateway and units are deleted | None. Canonical does not select IBKR (`bar_source_policy_current` names no IBKR source). Part F deletes the raw rows at or after 2003-09-10; the 672,245 earlier 1d rows stay in raw | None (code deleted 2026-11-13) |
| Derived 15m and 1h | None; computed from tradeable 5m | `(derived, 5m_grid)`, the derived grid | `bar_derivation --stage grid` (unit `indicagent-bar-derivation-grid`, 05:45 UTC, after the Alpaca nightly) |
| Yahoo | Dividends only, never a price | No | `dividend_events` (read through `dividend_events_reconciled`) |

**No synthetic_fill exists.** The store holds real rows only since the 185-25 swap (zero synthetic_fill rows). Two fences keep it so: migration 444's CHECK constraint `market_data_ohlcv_no_synthetic_fill` refuses an insert or update with that source (NOT VALID in the catalog, because TimescaleDB refuses VALIDATE on a columnstore hypertable; the ADD checked every chunk), and `tests/unit/test_market_data_ohlcv_no_synthetic_fill.py` fails CI on any synthetic_fill row build. The fill path itself (`normalize_bars`) is deleted: plan 189-08 removed its last caller and plan 185-42 the function.

**Placeholder-coverage gap readers.** Three readers once counted stored placeholders as coverage; they now see real rows only, so a slot with no real bar reads as a gap (185-25 accepted the one-time re-asks). None needs a code change today; phase 189's `ohlcv_coverage` ledger replaces gap planning (todo 499):

| Reader | Timeframe | State |
|---|---|---|
| `scripts/infrastructure/backfill/_d1_gaps.py` (`detect_gaps_from_record`) | 5m (also 15m, 1h) | Paused with the 5m fetch (todo 462); answered windows stop a definitive no_data span from being re-asked |
| `_history_fetch.py` `detect_gaps` (legacy grid difference) | 1m | Dormant: 1m is not in any default scope |
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
