-- 584 4b-2 group 4: the SMC/VP/SR no-object columns are NULL where their object does not
-- exist (D1 rule 2), never a fabricated 0.0/0.5. Distances that already said "NULL when
-- none exists" (ob/fvg/pool/zone distances, breaker_dist_atr) now actually deliver it;
-- this migration states the contract for the strengths, ages, freshness, the friction
-- score, the bars-since counts, the VP flags and the four legacy VP/SR columns.
-- Flags, counts and direction fields keep 0.0 as a measured state (zero_is_state, 4c).

COMMENT ON COLUMN feature_vectors.poc_dist_atr IS 'abs(close - session POC) / ATR; NULL when no session profile exists (no POC object, todo 584 4b-2 group 4)';
COMMENT ON COLUMN feature_vectors.va_position IS 'position of close within the session value area, clipped [0,1]; NULL when no value area exists or its width is zero (todo 584 4b-2 group 4)';
COMMENT ON COLUMN feature_vectors.sr_resist_dist IS '(nearest resistance cluster level - close) / ATR; NULL when no qualifying resistance cluster exists in-window (todo 584 4b-2 group 4)';
COMMENT ON COLUMN feature_vectors.sr_support_dist IS '(close - nearest support cluster level) / ATR; NULL when no qualifying support cluster exists in-window (todo 584 4b-2 group 4)';
COMMENT ON COLUMN feature_vectors.resistance_strength IS 'Volume-weighted resistance cluster strength: sum of min(2.0, member_volume/mean_volume) per cluster member, capped per member, unbounded in aggregate across cluster size. Comparable scalar, not ATR-normalized (not a distance). NULL when no qualifying cluster exists. Phase 163 (D-19), todo 584 4b-2 group 4.';
COMMENT ON COLUMN feature_vectors.support_strength IS 'Volume-weighted support cluster strength, same formula as resistance_strength. NULL when no qualifying cluster exists. Phase 163 (D-19), todo 584 4b-2 group 4.';
COMMENT ON COLUMN feature_vectors.resistance_age_bars IS 'Bars since the nearest resistance cluster''s most recent touch; NULL when no qualifying cluster exists (right-censored). Phase 163 (D-19), todo 584 4b-2 group 4.';
COMMENT ON COLUMN feature_vectors.support_age_bars IS 'Bars since the nearest support cluster''s most recent touch; NULL when no qualifying cluster exists (right-censored). Phase 163 (D-19), todo 584 4b-2 group 4.';
COMMENT ON COLUMN feature_vectors.price_in_value_area IS '1.0 if VAL <= close <= VAH (session value area) else 0.0; NULL when no value area exists. Phase 163, todo 584 4b-2 group 4.';
COMMENT ON COLUMN feature_vectors.in_lvn IS '1.0 if close''s current volume bucket is at/below the LVN threshold (liquidity-void flag, distinct from price_in_value_area per D-17) else 0.0; NULL when no session histogram exists. Phase 163, todo 584 4b-2 group 4.';
COMMENT ON COLUMN feature_vectors.ob_strength IS 'Order block strength score from impulse-move volume magnitude, bounded [0,1]; NULL when no order block exists. Phase 164, todo 584 4b-2 group 4.';
COMMENT ON COLUMN feature_vectors.ob_mitigation_pct IS 'Fraction of the nearest order block''s range price has retraced, [0,1]: 0.0=fresh, 1.0=fully mitigated (void); NULL when no order block exists. Phase 164, todo 584 4b-2 group 4.';
COMMENT ON COLUMN feature_vectors.sweep_strength IS 'Bounded [0,1] strength of the most recent liquidity sweep, from wick-beyond depth relative to price (linear_ramp-clamped); NULL when no sweep has occurred in-window. Phase 164, todo 584 4b-2 group 4.';
COMMENT ON COLUMN feature_vectors.reclaim_velocity IS 'Bounded [0,1] speed of price reclaim following a liquidity sweep; NULL when no sweep has occurred in-window. Phase 164, todo 584 4b-2 group 4.';
COMMENT ON COLUMN feature_vectors.bars_since_last_sweep IS 'Bar count since the most recent liquidity sweep detection; NULL when no sweep is known inside the window (right-censored, never 0). Phase 164, todo 584 4b-2 group 4.';
COMMENT ON COLUMN feature_vectors.demand_freshness IS 'Bounded [0,1] freshness/decay score of the nearest demand zone (unretested = 1.0, decaying with retest count and age); NULL when no active demand zone exists. Phase 164, todo 584 4b-2 group 4.';
COMMENT ON COLUMN feature_vectors.supply_freshness IS 'Bounded [0,1] freshness/decay score of the nearest supply zone; NULL when no active supply zone exists. Phase 164, todo 584 4b-2 group 4.';
COMMENT ON COLUMN feature_vectors.zone_friction_score IS 'Bounded [0,1] composite: freshness * strength * (1/(1+dist_atr)) of the higher-friction nearest zone (demand or supply); NULL when neither side has an active zone. Phase 164, todo 584 4b-2 group 4.';
COMMENT ON COLUMN feature_vectors.bos_strength IS 'ATR-normalized break-of-structure magnitude: (break close - broken swing level) / ATR, clamped >= 0; NULL when no break has fired in-window. Phase 164, todo 584 4b-2 group 4.';
COMMENT ON COLUMN feature_vectors.choch_strength IS 'ATR-normalized change-of-character magnitude -- same formula as bos_strength for the opposing-trend break; NULL when no CHoCH has fired in-window. Phase 164, todo 584 4b-2 group 4.';
COMMENT ON COLUMN feature_vectors.bars_since_last_shift IS 'Bar count since the most recent BOS or CHoCH structural shift; NULL when no shift is known inside the window (right-censored, never 0). Phase 164, todo 584 4b-2 group 4.';
