# Phase 185 complexity baseline (plan 185-44)

Measured: 2026-10-06T22:29Z, at git SHA 74fb3fd4b plus this plan's census script (uncommitted at
measurement; it is committed with this file). Measured before any data layer integrity plan
(185-31 onward, 189-07 onward) commits a change.

Producer: `.venv/bin/python -m scripts.ops.ops_complexity_census --markdown` (read-only: one
read-only database session, `git`, `systemctl show`, the filesystem). Plan 185-43 reruns the same
command unchanged; its exit criteria require each count below to go down or be explained.

The TEMPORARY count here is taken before the 185-44 guards existed. The single_writer registry
(`tests/unit/test_single_writer_registry.py`) adds TEMPORARY entries of its own, each with a
`retire:` clause, in the commit after this one; 185-43 explains that delta against this baseline.

## Definitions

- scripts_total / scripts_ops: `*.py` and `*.sh` files under `scripts/` (total) and under
  `scripts/ops/` (subtotal), tracked or untracked-not-ignored, excluding `__init__.py` and
  `__pycache__`.
- temporary_entries: allow-list entries whose reason contains "TEMPORARY", in
  `tests/unit/test_*boundary*.py` and `tests/unit/test_*_registry.py` (module-level dicts, nested
  dicts flattened to key paths).
- tables_public / views_public: `information_schema.tables` rows with `table_schema = 'public'`
  and `table_type = 'BASE TABLE'`, and separately `'VIEW'`.
- apr_keys_without_reader (of apr_keys_total): `config_state` keys whose literal does not appear
  in `services/`, `src/` or `scripts/` (`*.py`, `*.sh`, `*.sql`), and for which no dotted prefix
  of the key appears followed by a `{` placeholder, a `%` format or a closing quote (the
  registry's naming rule for keys built in code: `<prefix>.{tf}`, `<prefix>_{tf}`,
  `"alert.lag." + unit`). Migrations and tests are not readers.
- services_without_live_consumer: `_DAG_ORDER` units (`services/service_auditor.py`) whose
  systemd unit is failed, missing (LoadState not `loaded`), or inactive while neither
  `Type=oneshot` nor backed by a loaded `.timer` (`systemctl show -p Id,Type,ActiveState,LoadState`),
  plus the units CLAUDE.md documents as dormant (the I8 AI stack).
- todos_pending: files in `.planning/todos/pending/`.
- docs_stale_status: files under `docs/` (excluding `docs/research/`) whose Status line starts
  with proposed, draft or in progress (case-insensitive), and whose last git change is older than
  30 days, or whose Status names a plan (`185-27`) or phase (`phase 170`) whose SUMMARY files say
  it is complete (every PLAN in the phase directory has its SUMMARY). Docs with any other Status
  (implemented, superseded, archived, current, ...) are out of scope by construction.

## Counts and listings

| Measure | Count |
|---|---|
| scripts_total | 103 |
| scripts_ops | 36 |
| temporary_entries | 2 |
| tables_public | 100 |
| views_public | 14 |
| apr_keys_without_reader | 177 |
| services_without_live_consumer | 38 |
| todos_pending | 88 |
| docs_stale_status | 10 |
| apr_keys_total | 845 |

### scripts_total (103)

- scripts/debug/analysis/debug_analyze_feature_ic.py
- scripts/debug/analysis/debug_batch_agent_memory.py
- scripts/debug/analysis/debug_bic_k_selection.py
- scripts/debug/analysis/debug_memory_recall_benchmark.py
- scripts/debug/replay/debug_feature_replay.py
- scripts/debug/replay/debug_lifecycle_replay.py
- scripts/debug/replay/debug_replay_all.sh
- scripts/debug/replay/debug_replay_post.py
- scripts/debug/replay/debug_replay_prep.py
- scripts/debug/snapshot/debug_signal_corpus_snapshot.py
- scripts/debug/snapshot/debug_signal_ledger_snapshot.py
- scripts/debug/validate/debug_db_verify.sh
- scripts/debug/validate/debug_validate_alpha.py
- scripts/infrastructure/_capture_common.py
- scripts/infrastructure/_write_mode_args.py
- scripts/infrastructure/backfill/_d1_gaps.py
- scripts/infrastructure/backfill/_derivation_stage.py
- scripts/infrastructure/backfill/_empty_history.py
- scripts/infrastructure/backfill/_fetch_queue.py
- scripts/infrastructure/backfill/_fetcher_lock.py
- scripts/infrastructure/backfill/_history_fetch_item.py
- scripts/infrastructure/backfill/_intraday_persist.py
- scripts/infrastructure/backfill/ibkr_history_fetcher.py
- scripts/infrastructure/backfill/infrastructure_fetch_htf_bars.py
- scripts/infrastructure/backfill/infrastructure_ibkr_chunk_and_rate_limit_probe.py
- scripts/infrastructure/backfill/infrastructure_nightly_backfill.py
- scripts/infrastructure/backfill/infrastructure_reset_pipeline_data.py
- scripts/infrastructure/backfill/infrastructure_run_historical_pipeline.py
- scripts/infrastructure/backfill/infrastructure_run_tradier_daily.py
- scripts/infrastructure/backfill/infrastructure_truncate_derived_tables.sh
- scripts/infrastructure/classification_ibkr_sourcing.py
- scripts/infrastructure/features_capture_kernel_parity_golden.py
- scripts/infrastructure/features_capture_regime_kernel_golden.py
- scripts/infrastructure/features_regime_kernel_coverage_sweep.py
- scripts/infrastructure/instrument_compute_eligibility_audit.py
- scripts/infrastructure/kafka/infrastructure_enforce_topic_retention.py
- scripts/infrastructure/kafka/infrastructure_ensure_topics.sh
- scripts/infrastructure/kafka/infrastructure_redpanda_watchdog.sh
- scripts/infrastructure/setup/infrastructure_db_setup.sh
- scripts/infrastructure/setup/infrastructure_init_kafka_topics.py
- scripts/infrastructure/universe_expansion_fetch_iwv_holdings.py
- scripts/infrastructure/universe_expansion_holdings_draw.py
- scripts/infrastructure/universe_expansion_onboard_gap_fill_etfs.py
- scripts/infrastructure/universe_expansion_onboard_manifest.py
- scripts/infrastructure/universe_expansion_pilot_draw.py
- scripts/infrastructure/universe_expansion_promote_compute_eligible.py
- scripts/infrastructure/universe_expansion_stratified_sourcing.py
- scripts/infrastructure/universe_expansion_wave2_select.py
- scripts/ops/alpha/ops_broadcast_feature_audit.py
- scripts/ops/alpha/ops_canary_integrity_assert.py
- scripts/ops/alpha/ops_concept_registry_override.py
- scripts/ops/alpha/ops_dependence_length_diagnostic.py
- scripts/ops/bars/_campaign.py
- scripts/ops/bars/ops_d1_bootstrap.py
- scripts/ops/bars/ops_d1_dedupe.py
- scripts/ops/bars/ops_data_bar_check.py
- scripts/ops/bars/ops_export_known_answer_fixtures.py
- scripts/ops/bars/ops_grid_lane_guard.py
- scripts/ops/bars/ops_head_rerun.py
- scripts/ops/bars/ops_intraday_venue_recovery.py
- scripts/ops/bars/ops_masked_slot_baseline.py
- scripts/ops/bars/ops_measure_ohlcv_write_rates.py
- scripts/ops/bars/ops_real_rows_swap.py
- scripts/ops/bars/ops_scrub_historical_pass.py
- scripts/ops/bars/ops_seam_audit.py
- scripts/ops/bars/ops_split_detect.py
- scripts/ops/bars/ops_tradier_fetch_complete_repair.py
- scripts/ops/bars/ops_tradier_lineage_backfill.py
- scripts/ops/bars/ops_venue_study.py
- scripts/ops/corpus/ops_corpus_final_verification.py
- scripts/ops/corpus/ops_corpus_pipeline_run.sh
- scripts/ops/corpus/ops_ctf_columns_recompute_15m.py
- scripts/ops/corpus/ops_known_corrupt_print_cleanup.py
- scripts/ops/corpus/ops_oos_holdout_eval.py
- scripts/ops/corpus/ops_pipeline_monitor.sh
- scripts/ops/corpus/ops_regime_monitor.sh
- scripts/ops/corpus/ops_regime_null_out_and_verify.py
- scripts/ops/corpus/ops_stale_k3_hmm_fields_cleanup.py
- scripts/ops/db/ops_pg_settings_baseline.py
- scripts/ops/ops_complexity_census.py
- scripts/ops/pipeline/ops_pipeline_audit.py
- scripts/ops/pipeline/ops_pipeline_status.py
- scripts/ops/roll/ops_roll_batch.py
- scripts/ops/roll/ops_validate_roll_detection.py
- scripts/research/cost_hurdle.py
- scripts/research/date_panel.py
- scripts/research/determinism/config.py
- scripts/research/determinism/repro_frozen.py
- scripts/research/determinism/results.py
- scripts/research/determinism/sessions.py
- scripts/research/determinism/signals.py
- scripts/research/determinism/snapshot_io.py
- scripts/research/e17_null_battery.py
- scripts/research/family1_conviction_gating.py
- scripts/research/family1_event_study_5m.py
- scripts/research/family1_liquid_close.py
- scripts/research/family1_monthly_returns.py
- scripts/research/family1_slot_profile.py
- scripts/research/feature_matrix.py
- scripts/research/midterm_cycle_looks.py
- scripts/research/run_spec.py
- scripts/research/static_sizes.py
- scripts/research/todo445_5m_incremental_ic.py

### scripts_ops (36)

- scripts/ops/alpha/ops_broadcast_feature_audit.py
- scripts/ops/alpha/ops_canary_integrity_assert.py
- scripts/ops/alpha/ops_concept_registry_override.py
- scripts/ops/alpha/ops_dependence_length_diagnostic.py
- scripts/ops/bars/_campaign.py
- scripts/ops/bars/ops_d1_bootstrap.py
- scripts/ops/bars/ops_d1_dedupe.py
- scripts/ops/bars/ops_data_bar_check.py
- scripts/ops/bars/ops_export_known_answer_fixtures.py
- scripts/ops/bars/ops_grid_lane_guard.py
- scripts/ops/bars/ops_head_rerun.py
- scripts/ops/bars/ops_intraday_venue_recovery.py
- scripts/ops/bars/ops_masked_slot_baseline.py
- scripts/ops/bars/ops_measure_ohlcv_write_rates.py
- scripts/ops/bars/ops_real_rows_swap.py
- scripts/ops/bars/ops_scrub_historical_pass.py
- scripts/ops/bars/ops_seam_audit.py
- scripts/ops/bars/ops_split_detect.py
- scripts/ops/bars/ops_tradier_fetch_complete_repair.py
- scripts/ops/bars/ops_tradier_lineage_backfill.py
- scripts/ops/bars/ops_venue_study.py
- scripts/ops/corpus/ops_corpus_final_verification.py
- scripts/ops/corpus/ops_corpus_pipeline_run.sh
- scripts/ops/corpus/ops_ctf_columns_recompute_15m.py
- scripts/ops/corpus/ops_known_corrupt_print_cleanup.py
- scripts/ops/corpus/ops_oos_holdout_eval.py
- scripts/ops/corpus/ops_pipeline_monitor.sh
- scripts/ops/corpus/ops_regime_monitor.sh
- scripts/ops/corpus/ops_regime_null_out_and_verify.py
- scripts/ops/corpus/ops_stale_k3_hmm_fields_cleanup.py
- scripts/ops/db/ops_pg_settings_baseline.py
- scripts/ops/ops_complexity_census.py
- scripts/ops/pipeline/ops_pipeline_audit.py
- scripts/ops/pipeline/ops_pipeline_status.py
- scripts/ops/roll/ops_roll_batch.py
- scripts/ops/roll/ops_validate_roll_detection.py

### temporary_entries (2)

- tests/unit/test_ibkr_history_lease_boundary.py _ALLOW_LIST[services/backfill_feature_factory.py]: TEMPORARY: corpus feature backfill fetches 1d bars lease-free; wiring the lease through it needs its own change (tracked in the phase 185 deferred items), not a rider on plan 09.
- tests/unit/test_ibkr_history_lease_boundary.py _ALLOW_LIST[scripts/infrastructure/backfill/_history_fetch_item.py]: TEMPORARY: library invoked only by ibkr_history_fetcher.py under FetcherLock; plan 189-08 rewrites this guard around FetcherLock.

### tables_public (100)

- alpha_multiplier_shadow
- backfill_status
- bar_content_digest
- bar_derivation_batch
- bar_quality_flag
- batch_job_checkpoints
- calibration_curves
- canonical_bar_lineage
- cis_weights
- classification_node
- classification_scheme
- concept_annotation
- concept_evaluation
- concept_gate
- concept_parent
- concept_registry
- concept_transition_log
- confidence_calibration
- config_history
- config_outbox
- config_schema
- config_state
- contract_metadata
- controlled_vocabulary
- corporate_action
- dividend_date_dispute
- dividend_event_coverage
- dividend_events
- dlq_events
- drift_state
- economic_series_observation
- economic_series_observation_coverage
- factor_series_correlation
- feature_ic_scores
- feature_ic_scores_v2
- feature_vectors
- feature_vectors_v2
- gate_evaluations
- ic_cell_fingerprints
- instrument_annotations
- instrument_classification
- instrument_metadata
- instrument_tags
- instruments
- integrity_monitor
- intelligence_ai_enrichment
- intelligence_features
- intelligence_metrics
- listing_venue
- llm_calls
- llm_model_scores
- macro_features
- market_data_gaps
- market_data_ohlcv
- market_regimes
- market_regimes_override
- memory_calibration_promoted
- memory_calibration_spc
- memory_episodes_labeled
- memory_episodes_raw
- memory_regime_transitions
- memory_system_state
- ml_data_quality_runs
- ml_discovery_runs
- ml_models
- ml_signal_training
- ohlcv_coverage
- ohlcv_empty_history
- ohlcv_intraday_raw_archive
- ohlcv_load
- ohlcv_observation
- ohlcv_provider_head
- ohlcv_request
- ohlcv_revision
- parity_certification_state
- pattern_reliability
- provenance_batch
- remediation_ledger
- research_run
- roll_events
- service_health_events
- setup_performance
- shadow_registry
- shadow_transition_log
- signal_ai_enrichment
- signal_events
- signal_lineage
- signal_metrics
- signal_metrics_dq_failures
- signal_metrics_ic
- signal_transform_log
- swarm_agent_weights
- system_events
- tag_vocabulary
- tod_multipliers
- trade_executions
- trade_frames
- transform_graduation
- vocabulary_group
- vocabulary_group_member

### views_public (14)

- bar_content_digest_current
- corporate_action_current
- dividend_events_reconciled
- economic_series_observation_current
- feature_edge_by_regime
- feature_edge_by_symbol
- instrument_tags_active
- market_data_5m
- market_data_ohlcv_scrub_input
- market_data_ohlcv_tradeable
- ohlcv_venue_head
- pg_stat_statements
- pg_stat_statements_info
- signal_ledger

### apr_keys_without_reader (177)

- alpha.commodity_regime.momentum_window
- alpha.commodity_regime.primary_threshold
- alpha.concept_registry.ensemble_strategy_min_new_observations
- alpha.concept_registry.ensemble_strategy_min_observations
- alpha.concept_registry.ensemble_strategy_min_promotion_consecutive
- alpha.construction.attribution_max_static_r2
- alpha.construction.cost_hurdle_bps_round_trip
- alpha.construction.decile_fraction
- alpha.construction.null_p_threshold
- alpha.construction.null_shuffles
- alpha.equity_regime.breadth_bull
- alpha.equity_regime.ma_window
- alpha.equity_regime.realized_vol_window
- alpha.equity_regime.vix_high_pct
- alpha.equity_regime.vix_low_pct
- alpha.equity_regime.vix_z_window
- alpha.frame.atr_period
- alpha.frame.geometry_source
- alpha.frame.hold_max_bars.high_bear.15m
- alpha.frame.hold_max_bars.high_bear.1d
- alpha.frame.hold_max_bars.high_bear.1h
- alpha.frame.hold_max_bars.high_bear.5m
- alpha.frame.hold_max_bars.high_bull.15m
- alpha.frame.hold_max_bars.high_bull.1d
- alpha.frame.hold_max_bars.high_bull.1h
- alpha.frame.hold_max_bars.high_bull.5m
- alpha.frame.hold_max_bars.high_neutral.15m
- alpha.frame.hold_max_bars.high_neutral.1d
- alpha.frame.hold_max_bars.high_neutral.1h
- alpha.frame.hold_max_bars.high_neutral.5m
- alpha.frame.hold_max_bars.low_bear.15m
- alpha.frame.hold_max_bars.low_bear.1d
- alpha.frame.hold_max_bars.low_bear.1h
- alpha.frame.hold_max_bars.low_bear.5m
- alpha.frame.hold_max_bars.low_bull.15m
- alpha.frame.hold_max_bars.low_bull.1d
- alpha.frame.hold_max_bars.low_bull.1h
- alpha.frame.hold_max_bars.low_bull.5m
- alpha.frame.hold_max_bars.low_neutral.15m
- alpha.frame.hold_max_bars.low_neutral.1d
- alpha.frame.hold_max_bars.low_neutral.1h
- alpha.frame.hold_max_bars.low_neutral.5m
- alpha.frame.hold_max_bars.mid_bear.15m
- alpha.frame.hold_max_bars.mid_bear.1d
- alpha.frame.hold_max_bars.mid_bear.1h
- alpha.frame.hold_max_bars.mid_bear.5m
- alpha.frame.hold_max_bars.mid_bull.15m
- alpha.frame.hold_max_bars.mid_bull.1d
- alpha.frame.hold_max_bars.mid_bull.1h
- alpha.frame.hold_max_bars.mid_bull.5m
- alpha.frame.hold_max_bars.mid_neutral.15m
- alpha.frame.hold_max_bars.mid_neutral.1d
- alpha.frame.hold_max_bars.mid_neutral.1h
- alpha.frame.hold_max_bars.mid_neutral.5m
- alpha.frame.min_stop_price_fraction
- alpha.frame.stop_atr_mult
- alpha.frame.stop_atr_mult.high_bear.15m
- alpha.frame.stop_atr_mult.high_bear.1d
- alpha.frame.stop_atr_mult.high_bear.1h
- alpha.frame.stop_atr_mult.high_bear.5m
- alpha.frame.stop_atr_mult.high_bull.15m
- alpha.frame.stop_atr_mult.high_bull.1d
- alpha.frame.stop_atr_mult.high_bull.1h
- alpha.frame.stop_atr_mult.high_bull.5m
- alpha.frame.stop_atr_mult.high_neutral.15m
- alpha.frame.stop_atr_mult.high_neutral.1d
- alpha.frame.stop_atr_mult.high_neutral.1h
- alpha.frame.stop_atr_mult.high_neutral.5m
- alpha.frame.stop_atr_mult.low_bear.15m
- alpha.frame.stop_atr_mult.low_bear.1d
- alpha.frame.stop_atr_mult.low_bear.1h
- alpha.frame.stop_atr_mult.low_bear.5m
- alpha.frame.stop_atr_mult.low_bull.15m
- alpha.frame.stop_atr_mult.low_bull.1d
- alpha.frame.stop_atr_mult.low_bull.1h
- alpha.frame.stop_atr_mult.low_bull.5m
- alpha.frame.stop_atr_mult.low_neutral.15m
- alpha.frame.stop_atr_mult.low_neutral.1d
- alpha.frame.stop_atr_mult.low_neutral.1h
- alpha.frame.stop_atr_mult.low_neutral.5m
- alpha.frame.stop_atr_mult.mid_bear.15m
- alpha.frame.stop_atr_mult.mid_bear.1d
- alpha.frame.stop_atr_mult.mid_bear.1h
- alpha.frame.stop_atr_mult.mid_bear.5m
- alpha.frame.stop_atr_mult.mid_bull.15m
- alpha.frame.stop_atr_mult.mid_bull.1d
- alpha.frame.stop_atr_mult.mid_bull.1h
- alpha.frame.stop_atr_mult.mid_bull.5m
- alpha.frame.stop_atr_mult.mid_neutral.15m
- alpha.frame.stop_atr_mult.mid_neutral.1d
- alpha.frame.stop_atr_mult.mid_neutral.1h
- alpha.frame.stop_atr_mult.mid_neutral.5m
- alpha.frame.structure_snap_proximity_atr
- alpha.frame.target_r_multiple
- alpha.frame.target_r_multiple.high_bear.15m
- alpha.frame.target_r_multiple.high_bear.1d
- alpha.frame.target_r_multiple.high_bear.1h
- alpha.frame.target_r_multiple.high_bear.5m
- alpha.frame.target_r_multiple.high_bull.15m
- alpha.frame.target_r_multiple.high_bull.1d
- alpha.frame.target_r_multiple.high_bull.1h
- alpha.frame.target_r_multiple.high_bull.5m
- alpha.frame.target_r_multiple.high_neutral.15m
- alpha.frame.target_r_multiple.high_neutral.1d
- alpha.frame.target_r_multiple.high_neutral.1h
- alpha.frame.target_r_multiple.high_neutral.5m
- alpha.frame.target_r_multiple.low_bear.15m
- alpha.frame.target_r_multiple.low_bear.1d
- alpha.frame.target_r_multiple.low_bear.1h
- alpha.frame.target_r_multiple.low_bear.5m
- alpha.frame.target_r_multiple.low_bull.15m
- alpha.frame.target_r_multiple.low_bull.1d
- alpha.frame.target_r_multiple.low_bull.1h
- alpha.frame.target_r_multiple.low_bull.5m
- alpha.frame.target_r_multiple.low_neutral.15m
- alpha.frame.target_r_multiple.low_neutral.1d
- alpha.frame.target_r_multiple.low_neutral.1h
- alpha.frame.target_r_multiple.low_neutral.5m
- alpha.frame.target_r_multiple.mid_bear.15m
- alpha.frame.target_r_multiple.mid_bear.1d
- alpha.frame.target_r_multiple.mid_bear.1h
- alpha.frame.target_r_multiple.mid_bear.5m
- alpha.frame.target_r_multiple.mid_bull.15m
- alpha.frame.target_r_multiple.mid_bull.1d
- alpha.frame.target_r_multiple.mid_bull.1h
- alpha.frame.target_r_multiple.mid_bull.5m
- alpha.frame.target_r_multiple.mid_neutral.15m
- alpha.frame.target_r_multiple.mid_neutral.1d
- alpha.frame.target_r_multiple.mid_neutral.1h
- alpha.frame.target_r_multiple.mid_neutral.5m
- alpha.fx_regime.carry_risk_on_threshold
- alpha.fx_regime.dollar_strong_threshold
- alpha.fx_regime.momentum_window
- alpha.ic.bootstrap_early_stop.check_interval
- alpha.ic.bootstrap_early_stop.enabled
- alpha.ic.bootstrap_early_stop.min_resamples
- alpha.ic.bootstrap_early_stop.stable_checks
- alpha.ic.bootstrap_early_stop.tol
- alpha.ic.bootstrap_numba_kernel
- alpha.ic.earnings_season_conditioned
- alpha.ic.max_cell_rows
- alpha.ic.min_obs_daily_features
- alpha.ic.min_obs_per_regime
- alpha.ic.min_observations
- alpha.ic.partial_fdr_alpha
- alpha.ic.refresh_min_new_fraction
- alpha.ic.sharpe_min_windows
- alpha.ic.walk_forward_folds
- alpha.publisher.is_shadow
- alpha.rates_regime.credit_tight_threshold
- alpha.rates_regime.credit_window
- alpha.rates_regime.curve_window
- alpha.rates_regime.inverted_threshold
- alpha.rates_regime.steep_threshold
- alpha.regime.breadth_bear
- alpha.regime.breadth_bull
- alpha.regime.ma_window
- alpha.regime.vix_high_pct
- alpha.regime.vix_low_pct
- alpha.vector.v1_quant.members
- feature.zone_engine.min_stop_distance_atr.equity
- feature.zone_engine.min_stop_distance_atr.futures
- feature.zone_engine.min_stop_distance_atr.fx
- infra.alpha_publisher.chunk_size
- infra.bar_auditor.price_sanity_batch_size
- infra.cross_sectional_spread_tracker.chunk_size
- infra.cross_sectional_spread_tracker.itersize
- infra.dividend_event.lookback_years
- infra.ensemble_trainer.workers
- infra.ic.max_unrouted_symbols
- infra.interaction_primitives_pilot.fetch_flush_rows
- threshold.signal_audit.hit_rate_anti_signal_ceiling
- threshold.signal_audit.hit_rate_validated_floor
- threshold.signal_audit.ic_anti_signal_ceiling
- threshold.signal_audit.ic_validated_floor
- threshold.signal_audit.partial_population_floor
- threshold.signal_audit.verifiable_population_floor

### services_without_live_consumer (38)

- indicagent-ibkr-provider: inactive Type=simple with no timer
- indicagent-bar-replay: inactive Type=simple with no timer
- indicagent-provider-merger: inactive Type=simple with no timer
- indicagent-bar-aggregator: inactive Type=simple with no timer
- indicagent-bar-auditor: inactive Type=simple with no timer
- indicagent-bar-writer: inactive Type=simple with no timer
- indicagent-cross-asset: inactive Type=simple with no timer
- indicagent-macro-compute: inactive Type=simple with no timer
- indicagent-feature-vector-pipeline: failed
- indicagent-signal-tracker-compute: inactive Type=simple with no timer
- indicagent-signal-writer: inactive Type=simple with no timer
- indicagent-lifecycle-writer: inactive Type=simple with no timer
- indicagent-alpha-swarm: documented: dormant I8 AI stack (CLAUDE.md, src/intelligence/CLAUDE.md)
- indicagent-narrative-compute: documented: dormant I8 AI stack (CLAUDE.md, src/intelligence/CLAUDE.md)
- indicagent-llm-writer: documented: dormant I8 AI stack (CLAUDE.md, src/intelligence/CLAUDE.md)
- indicagent-swarm-ledger-writer: documented: dormant I8 AI stack (CLAUDE.md)
- indicagent-signal-metrics-compute: inactive Type=simple with no timer
- indicagent-signal-metrics-writer: inactive Type=simple with no timer
- indicagent-graduation-compute: inactive Type=simple with no timer
- indicagent-graduation-writer: inactive Type=simple with no timer
- indicagent-memory-batch: missing (not-found)
- indicagent-shadow-validator: missing (not-found)
- indicagent-feature-parity-auditor: missing (not-found)
- indicagent-confidence-calibration-monitor: missing (not-found)
- indicagent-signal-probe-auditor: missing (not-found)
- indicagent-regime-writer: missing (not-found)
- indicagent-ic-measure: missing (not-found)
- indicagent-feature-lifecycle: missing (not-found)
- indicagent-bar-derivation: missing (not-found)
- indicagent-economic-series-writer: missing (not-found)
- indicagent-signal-auditor: inactive Type=simple with no timer
- indicagent-signal-replay: inactive Type=simple with no timer
- indicagent-alerting-agent: inactive Type=simple with no timer
- indicagent-dlq-drain: inactive Type=simple with no timer
- indicagent-config-service: inactive Type=simple with no timer
- indicagent-outbox-dispatcher: inactive Type=simple with no timer
- indicagent-self-healing-agent: inactive Type=simple with no timer
- indicagent-service-auditor: inactive Type=simple with no timer

### todos_pending (88)

- .planning/todos/pending/009-service-utils-ic-engine-cleanup.md
- .planning/todos/pending/038-cross-sectional-collinearity-diagnostic.md
- .planning/todos/pending/039-tag-stratified-ic-population-check.md
- .planning/todos/pending/056-phase146-147-v2x-retirement-stale.md
- .planning/todos/pending/099-bootstrap-ci-staged-validation-gate-not-cleared-5m-residual.md
- .planning/todos/pending/108-hmm-multi-seed-restart-best-likelihood.md
- .planning/todos/pending/191-feature-scoring-beyond-ic.md
- .planning/todos/pending/223-src-intelligence-i1-i7-dead-code-153-files-30k-lines.md
- .planning/todos/pending/226-regime-writer-n-iter-convergence-headroom-check.md
- .planning/todos/pending/228-corpus-pipeline-unmeasured-steps-io-vs-cpu-triage.md
- .planning/todos/pending/272-instrument-tag-peer-group-coverage-auditor.md
- .planning/todos/pending/275-v3-north-star-precedentengine-mechanics-predate-d4-rescope.md
- .planning/todos/pending/284-gsd-review-agy-stdin-invocation-broken.md
- .planning/todos/pending/309-vulture-baseline-cleanup-backlog.md
- .planning/todos/pending/317-backfill-status-migrate-to-anti-join-checkpoint-pattern.md
- .planning/todos/pending/321-feature-factory-config-test-fixture-consolidation.md
- .planning/todos/pending/324-gradient-vocabulary-naming-check-unenforced.md
- .planning/todos/pending/331-vocabulary-drift-auditor-windowed-query-blind-spot.md
- .planning/todos/pending/360-broadcast-day-constant-empirical-classifier.md
- .planning/todos/pending/363-ib-gateway-libgtk3-fix-not-durable-across-recreation.md
- .planning/todos/pending/373-docs-tree-152-broken-internal-links-not-file-count-clutter.md
- .planning/todos/pending/376-survivorship-bias-active-only-universe-no-owner.md
- .planning/todos/pending/383-gsd-sdk-state-and-gap-checker-hardcoded-field-path-assumptions.md
- .planning/todos/pending/387-nightly-backfill-detect-gaps-cost-scaling-and-staleness-observability.md
- .planning/todos/pending/390-illiq-series-unguarded-division-by-zero-dollar-volume.md
- .planning/todos/pending/394-todo-number-uniqueness-not-ci-enforced-duplicate-389.md
- .planning/todos/pending/395-nightly-backfill-fails-3-nights-weekly-ibkr-weekly-2fa-unattended.md
- .planning/todos/pending/397-universe-dimension-views-and-instruments-boundary-test.md
- .planning/todos/pending/398-ic-engine-scratch-dir-shares-db-filesystem.md
- .planning/todos/pending/406-ic-math-1087-invalid-divide-warning-unexamined.md
- .planning/todos/pending/411-feature-vectors-and-regimes-stale-since-2026-08-10-nightly-job-refreshes-ohlcv-only.md
- .planning/todos/pending/420-market-regimes-orphan-rows-from-pre-tradeable-writer.md
- .planning/todos/pending/421-feature-vectors-partial-coverage-velocity-and-never-computed-rank-z.md
- .planning/todos/pending/423-phase181-short-term-reversal-prereg.md
- .planning/todos/pending/426-compressed-write-session-decompresses-whole-feature-vectors-exceeds-disk.md
- .planning/todos/pending/429-integration-conftest-replay-broken-since-322.md
- .planning/todos/pending/430-terminology-enforcement-curate-then-ratchet.md
- .planning/todos/pending/431-stratified-sourcing-onboarding-holds-one-transaction-across-ibkr-calls.md
- .planning/todos/pending/433-ibkr-daily-history-truncated-at-primary-listing-venue-change.md
- .planning/todos/pending/435-wire-feature-vectors-into-research-panel-all-timeframes.md
- .planning/todos/pending/437-first-cut-cost-model-commission-and-spread.md
- .planning/todos/pending/438-daily-borrow-availability-snapshot-capture.md
- .planning/todos/pending/439-forward-span-integrity-write-once-oos-start-and-ic-purge.md
- .planning/todos/pending/440-generated-family-grammar-daily-ohlcv-931-names.md
- .planning/todos/pending/441-price-only-daily-families-931-names-prereg.md
- .planning/todos/pending/442-attempt1-single-family-and-pod-books-e17-memory-rule.md
- .planning/todos/pending/443-postgres-exporter-chunk-scrape-cost-and-idle-in-transaction-timeout.md
- .planning/todos/pending/444-onboarding-tooling-classification-mapper-pair-column-orchestrator.md
- .planning/todos/pending/448-research-lane-dependencies-for-phases-186-187.md
- .planning/todos/pending/449-intraday-5m-backfill-for-the-698-names-without-it.md
- .planning/todos/pending/453-ibkr-backfill-concurrency-probe-then-pipelined-persistence.md
- .planning/todos/pending/454-ultra-thin-traded-series-treatment.md
- .planning/todos/pending/455-drop-1m-from-nightly-backfill-defaults.md
- .planning/todos/pending/456-todo445-rerun-zero-commission-and-longer-horizons.md
- .planning/todos/pending/457-family1-slot-subsets-through-the-runner.md
- .planning/todos/pending/458-family1-slot-alpha-as-execution-timing-overlay.md
- .planning/todos/pending/459-ucr-feature-composition-replaces-stale-tier-and-register-hmm-columns.md
- .planning/todos/pending/460-family1-auction-price-check-and-auction-to-auction-hold.md
- .planning/todos/pending/461-gap-z-read-the-next-bars-open.md
- .planning/todos/pending/462-stop-storing-synthetic-fill-bars-record-coverage-instead.md
- .planning/todos/pending/463-live-macro-features-fabricate-zero-when-no-cross-asset-record.md
- .planning/todos/pending/464-cross-asset-builder-does-not-track-previous-closes-before-first-record.md
- .planning/todos/pending/465-ring0-metrics-module-holds-domain-named-instruments.md
- .planning/todos/pending/466-regime-columns-lookahead-dependents-303-304-benchmark.md
- .planning/todos/pending/467-regime-kernel-raises-on-a-constant-training-slice.md
- .planning/todos/pending/470-ic-measure-unit-grain-resume-and-digest-pass-cost.md
- .planning/todos/pending/471-ic-measure-intraday-full-universe-memory-and-time.md
- .planning/todos/pending/472-ctf-source-builder-hard-coded-constants-not-apr.md
- .planning/todos/pending/473-live-ctf-path-differs-from-batch-and-runs-92-kernels-per-bar.md
- .planning/todos/pending/474-kernels-fill-neutral-values-for-undefined-instead-of-nan.md
- .planning/todos/pending/475-macro-kernels-branch-on-symbol-and-timeframe-names.md
- .planning/todos/pending/477-pivot-detection-repeated-per-row-across-structure-kernels.md
- .planning/todos/pending/479-service-timer-logs-root-owned-break-single-module-unit-tests.md
- .planning/todos/pending/481-rates-regime-curve-label-measures-rate-direction-not-slope.md
- .planning/todos/pending/483-record-2026-midterm-forward-window-result.md
- .planning/todos/pending/484-htf-lane-honor-quarantined-symbols-file.md
- .planning/todos/pending/485-rate-limiter-wait-logging-in-ibkr-py.md
- .planning/todos/pending/487-run-spec-synthetic-defaults-cannot-express-spec-gates.md
- .planning/todos/pending/488-nightly-backfill-hang-holds-priority-lease.md
- .planning/todos/pending/490-grid-stage-archive-verify-fails-on-revised-bars.md
- .planning/todos/pending/491-universe-membership-pinned-in-the-s0-snapshot.md
- .planning/todos/pending/492-tradier-vs-ibkr-vendor-reconciliation-and-production-token.md
- .planning/todos/pending/493-tradier-nightly-intraday-capture-5m-15m.md
- .planning/todos/pending/494-unit-tests-can-spawn-live-writers-ci-guard.md
- .planning/todos/pending/495-integration-baseline-regen-after-phase-185.md
- .planning/todos/pending/496-two-live-db-integration-tests-red-since-185-12-and-186-23.md
- .planning/todos/pending/497-186-27-sets-the-intraday-recovery-unlock-keys.md
- .planning/todos/pending/498-otel-collector-drops-every-job-labelled-metric.md

### docs_stale_status (10)

- docs/architecture/architecture-overview.md: names completed phase 170 (Status: draft — downgraded 2026-08-11, staleness-quarantined per `docs/foundation/documentation-system.md` §6. Predates Phase 170 (`concept_registry` replacing `feature_registry`), Phase 171/172 (`regime_volatility` redesign), and the broader v3.1 milestone. Re-verify against current code before trusting any claim here.)
- docs/plans/archive/2026-04-01-pipeline-parallelization-design.md: unchanged 94 days (Status: Draft)
- docs/plans/archive/2026-05-03-phase-79-signal-quality-fix-design.md: unchanged 94 days (Status: Draft)
- docs/plans/archive/2026-05-04-structural-zone-engine-design.md: unchanged 94 days (Status: Draft)
- docs/plans/archive/2026-05-19-cis-stf-mtf-per-bar-design.md: unchanged 94 days (Status: In progress)
- docs/plans/archive/2026-06-26-drift-detection-architecture.md: unchanged 90 days (Status: PROPOSED — not planned, awaiting prioritization)
- docs/plans/archive/2026-06-26-feature-distribution-drift-detection.md: unchanged 90 days (Status: PROPOSED — not planned, awaiting prioritization)
- docs/plans/archive/2026-06-26-feature-ic-decay-implementation.md: unchanged 90 days (Status: PROPOSED — not planned, awaiting prioritization)
- docs/plans/archive/2026-06-27-ensemble-lifecycle-implementation.md: unchanged 90 days (Status: PROPOSED — not planned, awaiting prioritization)
- docs/plans/archive/2026-06-27-health-guardian-design.md: unchanged 90 days (Status: PROPOSED — awaiting prioritization)
