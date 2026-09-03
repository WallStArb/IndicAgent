-- 330: register the Pre-registration 2 verdict (program doc
-- docs/plans/2026-09-02-personal-scale-edge-determination-plan.md, "Pre-registration
-- 2 run — 2026-09-03: FAIL"). Todo 278's mandated diagnostic: per-bar
-- cross-sectionally demeaned alpha_score residual vs its OWN symbol's 15m forward
-- return, full IS panel. Verdict FAIL on condition 4 (0/231 symbols qualify BY-FDR
-- positive vs the 10% floor); conditions 1-3 pass (family signal real, thin, at the
-- 0b best-case floor). No new gate_id for any residual-stripping construction.
-- Not a compressed hypertable; no VACUUM step applies.

INSERT INTO concept_registry (domain, name, description, status, enabled, metadata)
VALUES (
  'construction',
  'alpha_score_residual_single_security_15m',
  'Falsified FAIL 2026-09-03 by the pre-registered IS run (scripts/analysis/alpha_score_residual_single_security_15m.py, design + Amendment 1 committed dc4288d0f before the run). 14,750,919 rows / 231 symbols / 3,469 dates, completion-blind per-bar demeaning, family stat = mean per-symbol Spearman IC. Conditions 1-3 PASS: stat 0.00277 (floor 0.0027), date-block bootstrap CI [0.00080, 0.00466], panel-synchronous date-shift null p=0.0020. Condition 4 FAIL flatly: 0/231 symbols qualify BY-FDR positive (floor 10%; BH also 0; 30/231 ci_lower>0). The residual signal is a uniformly dilute common effect — real, stable across temporal thirds (0.00281/0.00172/0.00301), but not concentrated per-name alpha and below the 0b worst-case economic floor (0.0164); sole BH-passing regime low_neutral 0.00398 is still 4x short. RAW comparison arm: 0.01054 [0.00607, 0.01505] p=0.0010 — alpha_score single-security predictivity is dominated by the common/market component the demeaning strips. Consequence: todo 278 answered; no new gate_id for residual-stripping constructions.',
  'deprecated',
  false,
  jsonb_build_object(
    'verdict', 'FAIL',
    'run_date', '2026-09-03',
    'script', 'scripts/analysis/alpha_score_residual_single_security_15m.py',
    'design_commit', 'dc4288d0f',
    'panel_rows', 14750919,
    'panel_symbols', 231,
    'panel_dates', 3469,
    'window', 'IS bar_ts < 2025-12-24',
    'family_stat', 0.00277,
    'family_ci', to_jsonb(ARRAY[0.00080, 0.00466]),
    'family_sync_shift_null_p', 0.0020,
    'floor', 0.0027,
    'qualifying_by_fdr', '0/231',
    'qualifying_floor', '10%',
    'raw_arm_stat', 0.01054,
    'raw_arm_ci', to_jsonb(ARRAY[0.00607, 0.01505]),
    'raw_arm_null_p', 0.0010,
    'pooled_spearman_sidecar', 0.00288,
    'pooled_pearson_sidecar', 0.00174,
    'regime_bh_passing', 'low_neutral',
    'regime_low_neutral_stat', 0.00398,
    'temporal_thirds', to_jsonb(ARRAY[0.00281, 0.00172, 0.00301])
  )
)
ON CONFLICT (domain, name) DO NOTHING;
