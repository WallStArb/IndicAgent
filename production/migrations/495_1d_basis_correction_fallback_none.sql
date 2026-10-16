-- 495: correct migration 494's fallback choice (todo 535 item 42).
--
-- The d2-v3 rule supports (tradier primary, ibkr fallback) and (ibkr primary, no
-- fallback); it refuses (ibkr primary, tradier fallback) ("only IBKR may fall
-- back for Tradier"). Migration 494's nine rows used fallback 'tradier', so the
-- daily stage refused every one of the seven names. The rows are closed
-- (valid_to set) and the append-only trigger forbids UPDATE, so this migration
-- corrects them under session_replication_role (superuser, trusted migration
-- path): delete the 494 rows, reinsert identical spans with fallback NULL.
-- Days without an ibkr bar are then simply not derived; coverage is >= 98% of
-- stored for all seven names, so removal stays far under the 2% contract gate.

SET session_replication_role = replica;

DELETE FROM bar_source_policy
WHERE timeframe = '1d' AND symbol IN ('AVA', 'BH', 'FTV', 'CUBI', 'FTI', 'IP', 'PFE')
  AND reason LIKE 'Basis correction 2026-10-15 (todo 535 item 42)%';

SET session_replication_role = DEFAULT;

INSERT INTO bar_source_policy (timeframe, symbol, valid_from, valid_to, ingress_mode, primary_source, fallback_source, reason, evidence)
VALUES
('1d', 'AVA', DATE '1990-01-01', DATE '2026-10-07', 'observed', 'ibkr', NULL,
 'Basis correction 2026-10-15 (todo 535 item 42; migration 495 fixed the fallback to none): tradier consolidated 1d is back-adjusted before 2023-01-03 (median -57.18% vs ibkr over 1,516 paired sessions); canonical restored to the unadjusted ibkr basis. Surfaced by the daily-stage removal refusal (D-191-O isolation).',
 '{"measured": "2026-10-15", "median_drift_pct": -57.18, "paired_pre2023_days": 1516, "n_stored": 5229, "n_ibkr_raw": 6991, "ibkr_coverage_pct": 133.7, "anchor": {"stored_non_tradier_days": 2770, "median_abs_log_dev": 0.0}}'),
('1d', 'BH', DATE '1990-01-01', DATE '2026-10-07', 'observed', 'ibkr', NULL,
 'Basis correction 2026-10-15 (todo 535 item 42; migration 495 fixed the fallback to none): tradier consolidated 1d is back-adjusted before 2023-01-03 (median -11.14% vs ibkr over 3,206 paired sessions); canonical restored to the unadjusted ibkr basis.',
 '{"measured": "2026-10-15", "median_drift_pct": -11.14, "paired_pre2023_days": 3206, "n_stored": 4155, "n_ibkr_raw": 4155, "ibkr_coverage_pct": 100.0, "anchor": {"revision_non_tradier_rows": 4146, "match_rows": 4146}}'),
('1d', 'FTV', DATE '1990-01-01', DATE '2016-06-13', 'observed', 'ibkr', NULL,
 'Basis correction 2026-10-15 (todo 535 item 42; migration 495 fixed the fallback to none): tradier consolidated 1d is back-adjusted before 2023-01-03 (median -7.77% vs ibkr over 1,636 paired sessions); canonical restored to the unadjusted ibkr basis. Split around the closed 185-47 one-day row at 2016-06-13 (same primary; no gap).',
 '{"measured": "2026-10-15", "median_drift_pct": -7.77, "paired_pre2023_days": 1636, "n_stored": 2586, "n_ibkr_raw": 2600, "ibkr_coverage_pct": 100.5, "anchor": {"revision_non_tradier_rows": 2595, "match_rows": 2595}}'),
('1d', 'FTV', DATE '2016-06-14', DATE '2026-10-07', 'observed', 'ibkr', NULL,
 'Basis correction 2026-10-15 (todo 535 item 42; migration 495 fixed the fallback to none): second span of the FTV basis correction (see the 1990-01-01 row).',
 '{"measured": "2026-10-15", "median_drift_pct": -7.77, "paired_pre2023_days": 1636, "split_around": "185-47 one-day row 2016-06-13"}'),
('1d', 'CUBI', DATE '1990-01-01', DATE '2026-10-07', 'observed', 'ibkr', NULL,
 'Basis correction 2026-10-15 (todo 535 item 42; migration 495 fixed the fallback to none): tradier consolidated 1d is back-adjusted before 2023-01-03 (median +4.82% vs ibkr over 2,425 paired sessions); canonical restored to the unadjusted ibkr basis.',
 '{"measured": "2026-10-15", "median_drift_pct": 4.82, "paired_pre2023_days": 2425, "n_stored": 3374, "n_ibkr_raw": 3374, "ibkr_coverage_pct": 100.0, "anchor": {"revision_non_tradier_rows": 3365, "match_rows": 3365}}'),
('1d', 'FTI', DATE '1990-01-01', DATE '2026-10-07', 'observed', 'ibkr', NULL,
 'Basis correction 2026-10-15 (todo 535 item 42; migration 495 fixed the fallback to none): tradier consolidated 1d is back-adjusted before 2023-01-03 (median +4.15% vs ibkr over 5,420 paired sessions); canonical restored to the unadjusted ibkr basis. Anchor is thin (3 revision + 8 stored days, all exact); recorded as such.',
 '{"measured": "2026-10-15", "median_drift_pct": 4.15, "paired_pre2023_days": 5420, "n_stored": 6370, "n_ibkr_raw": 6370, "ibkr_coverage_pct": 100.0, "anchor": {"revision_non_tradier_rows": 3, "match_rows": 3, "stored_non_tradier_days": 8}}'),
('1d', 'IP', DATE '1990-01-01', DATE '2006-10-02', 'observed', 'ibkr', NULL,
 'Basis correction 2026-10-15 (todo 535 item 42; migration 495 fixed the fallback to none): tradier consolidated 1d is back-adjusted before 2023-01-03 (median -2.37% vs ibkr over 1,675 paired sessions); canonical restored to the unadjusted ibkr basis. ibkr raw is deeper than stored (5,037 vs 2,623 days): the restore also extends depth. Split around the closed 185-47 one-day row at 2006-10-02 (same primary; no gap).',
 '{"measured": "2026-10-15", "median_drift_pct": -2.37, "paired_pre2023_days": 1675, "n_stored": 2623, "n_ibkr_raw": 5037, "ibkr_coverage_pct": 192.0, "anchor": {"revision_non_tradier_rows": 5037, "match_rows": 5037}}'),
('1d', 'IP', DATE '2006-10-03', DATE '2026-10-07', 'observed', 'ibkr', NULL,
 'Basis correction 2026-10-15 (todo 535 item 42; migration 495 fixed the fallback to none): second span of the IP basis correction (see the 1990-01-01 row).',
 '{"measured": "2026-10-15", "median_drift_pct": -2.37, "paired_pre2023_days": 1675, "split_around": "185-47 one-day row 2006-10-02"}'),
('1d', 'PFE', DATE '1990-01-01', DATE '2026-10-07', 'observed', 'ibkr', NULL,
 'Basis correction 2026-10-15 (todo 535 item 42; migration 495 fixed the fallback to none): tradier consolidated 1d is back-adjusted before 2023-01-03 (median -2.35% vs ibkr over 5,786 paired sessions); canonical restored to the unadjusted ibkr basis.',
 '{"measured": "2026-10-15", "median_drift_pct": -2.35, "paired_pre2023_days": 5786, "n_stored": 6736, "n_ibkr_raw": 6834, "ibkr_coverage_pct": 101.5, "anchor": {"revision_non_tradier_rows": 5085, "match_rows": 5085}}');
