-- Migration 426: drop the nine old-chain tables (phase 186 plan 22, D-14, D-06, D-08)
--
-- Tables: ensemble_weights, ensemble_alpha, alpha_ensemble_ic, alpha_events, alpha_frames,
-- alpha_strategy_scores, context_features, feature_ic_scores_history, construction_spreads.
-- forward_returns, feature_vectors and feature_ic_scores are NOT dropped here (186-23, 186-27, 186-28).
--
-- PRECONDITIONS ASSERTED BEFORE THIS MIGRATION WAS WRITTEN (recorded for the audit trail):
--   1. D-06 card gate: tests/unit/test_summary_cards.py green with git checks active; covering cards
--      docs/research/summary-cards/{cache-context-features, cache-feature-ic-scores-history,
--      legacy-ensemble-champion, legacy-phase142a-ensemble-ic, legacy-phase142b-frames-frame04,
--      legacy-phase148-score-01-03, legacy-ctf-momentum-decile-ls}.md.
--   2. D-08 greps: no surviving src, services, scripts, tests (outside schema fixtures), tools or
--      dashboard file reads a dropped table. The readers 186-19 and 186-21 left behind were deleted
--      in the preceding commit of 186-22 (ops_corpus_progress, ops_cost_hurdle_calibration,
--      watch_todo335_recompute, the context_features writer, the truncate-script blocks).
--      Remaining: comments, the v2.x context_features payload key, and services/ic_engine.py's
--      feature_ic_scores_history INSERT (deliberate: old ic_engine is non-runnable until 186-23).
--   3. No pg_stat_activity session was reading any of the nine tables at gate time.
--   4. Dependencies landed: 186-09 (feature_lifecycle clean), 186-16, 186-19, 186-21.
--
-- Row-count baseline (card record, measured 2026-10-01): ensemble_weights 358, ensemble_alpha
-- 106690090, alpha_ensemble_ic 0, alpha_events 65622721, alpha_frames 0, alpha_strategy_scores 120,
-- context_features 8985, feature_ic_scores_history 49568124, construction_spreads 130625.
-- The guard refuses when a table GREW past its baseline (new data the cards never saw); a smaller
-- or empty table (the integration database) passes.
--
-- Compression jobs 1067, 1068, 1069, 1070 (policy_compression) and 1072, 1073 (compression and
-- retention on feature_ic_scores_history) go with their hypertables. Job 1071 belongs to
-- feature_ic_scores and stays. A plain DROP decompresses nothing, so no VACUUM follows.

BEGIN;

DO $$
DECLARE
    v_pid INT;
    v_job INT;
    v_table TEXT;
    v_baseline BIGINT;
    v_count BIGINT;
    v_names TEXT[] := ARRAY[
        'ensemble_weights', 'ensemble_alpha', 'alpha_ensemble_ic', 'alpha_events', 'alpha_frames',
        'alpha_strategy_scores', 'context_features', 'feature_ic_scores_history',
        'construction_spreads'
    ];
    v_baselines BIGINT[] := ARRAY[
        358, 106690090, 0, 65622721, 0, 120, 8985, 49568124, 130625
    ];
    i INT;
BEGIN
    SELECT pid INTO v_pid FROM pg_stat_activity
    WHERE pid <> pg_backend_pid()
      AND state <> 'idle'
      AND (query ILIKE '%ensemble_weights%' OR query ILIKE '%ensemble_alpha%'
           OR query ILIKE '%alpha_ensemble_ic%' OR query ILIKE '%alpha_events%'
           OR query ILIKE '%alpha_frames%' OR query ILIKE '%alpha_strategy_scores%'
           OR query ILIKE '%context_features%' OR query ILIKE '%feature_ic_scores_history%'
           OR query ILIKE '%construction_spreads%')
    LIMIT 1;
    IF v_pid IS NOT NULL THEN
        RAISE EXCEPTION 'refusing to drop: another session is reading the old-chain tables (pid %)', v_pid;
    END IF;

    FOR i IN 1 .. array_length(v_names, 1) LOOP
        v_table := v_names[i];
        v_baseline := v_baselines[i];
        EXECUTE format('SELECT count(*) FROM %I', v_table) INTO v_count;
        IF v_count > v_baseline THEN
            RAISE EXCEPTION 'refusing to drop: % row count moved since the card was written (% vs %)',
                v_table, v_count, v_baseline;
        END IF;
    END LOOP;

    SELECT js.job_id INTO v_job
    FROM timescaledb_information.job_stats js
    WHERE js.hypertable_name IN ('ensemble_alpha', 'alpha_events', 'alpha_frames',
                                 'construction_spreads', 'feature_ic_scores_history',
                                 'alpha_ensemble_ic')
      AND js.job_status = 'Running'
    LIMIT 1;
    IF v_job IS NOT NULL THEN
        RAISE EXCEPTION 'refusing to drop: job % is running against an old-chain hypertable', v_job;
    END IF;
END
$$;

DROP TABLE ensemble_weights;
DROP TABLE ensemble_alpha;
DROP TABLE alpha_ensemble_ic;
DROP TABLE alpha_events;
DROP TABLE alpha_frames;
DROP TABLE alpha_strategy_scores;
DROP TABLE context_features;
DROP TABLE feature_ic_scores_history;
DROP TABLE construction_spreads;

COMMIT;
