-- 494: scoped 1d basis-correction policy rows (todo 535 item 42, D-191-O era).
--
-- Measured 2026-10-15: tradier consolidated 1d history is on a back-adjusted basis
-- before 2023-01-03 for a subset of names (median close drift vs ibkr smart_trades
-- over >= 60 paired pre-2023 sessions; every name below also >= 1%). The 185-17/18
-- full-history apply authored those spans into canonical under the global
-- tradier-primary row, so canonical 1d sits on the adjusted basis for the span.
-- Anchor check per name: non-tradier stored values and non-tradier ohlcv_revision
-- old values equal today's ibkr smart_trades exactly (median |log| 0.000), so the
-- ibkr series is the stable unadjusted basis and canonical restores to it
-- (executable-returns principle; splits live in corporate actions, not prices).
--
-- Inclusion: |median drift| >= 1% over >= 60 paired pre-2023 days AND ibkr raw
-- coverage >= 98% of stored days (the write contract would refuse below that).
-- UNIT is excluded: ibkr re-served its own 1d history on another scale
-- (2026-10-12, plan 08 finding; todo 512 track owns it). Thin-coverage damaged
-- names (ELE 93.9%, IJR 77.2%, IBM, RTX, O, WELL, EWS, EWT, RJF, MGM, STAG, ...)
-- get the same rows in a follow-up pass once the fetcher deepens their ibkr raw.
--
-- Row shape mirrors MOD/QRVO (symbol scope overrides the global; covers() is
-- half-open so [1990-01-01, 2026-10-07) hands off to the global ibkr-primary row).
-- The 185-47 seam pass left closed one-day ibkr-primary rows for FTV (2016-06-13)
-- and IP (2006-10-02); the table is append-only and closed rows are immutable, so
-- those names get split rows around the one-day row (same primary, no gap).

INSERT INTO bar_source_policy (timeframe, symbol, valid_from, valid_to, ingress_mode, primary_source, fallback_source, reason, evidence)
VALUES
('1d', 'AVA', DATE '1990-01-01', DATE '2026-10-07', 'observed', 'ibkr', 'tradier',
 'Basis correction 2026-10-15 (todo 535 item 42): tradier consolidated 1d is back-adjusted before 2023-01-03 (median -57.18% vs ibkr over 1,516 paired sessions); canonical restored to the unadjusted ibkr basis. Surfaced by the daily-stage removal refusal (D-191-O isolation).',
 '{"measured": "2026-10-15", "median_drift_pct": -57.18, "paired_pre2023_days": 1516, "n_stored": 5229, "n_ibkr_raw": 6991, "ibkr_coverage_pct": 133.7, "anchor": {"stored_non_tradier_days": 2770, "median_abs_log_dev": 0.0}}'),
('1d', 'BH', DATE '1990-01-01', DATE '2026-10-07', 'observed', 'ibkr', 'tradier',
 'Basis correction 2026-10-15 (todo 535 item 42): tradier consolidated 1d is back-adjusted before 2023-01-03 (median -11.14% vs ibkr over 3,206 paired sessions); canonical restored to the unadjusted ibkr basis.',
 '{"measured": "2026-10-15", "median_drift_pct": -11.14, "paired_pre2023_days": 3206, "n_stored": 4155, "n_ibkr_raw": 4155, "ibkr_coverage_pct": 100.0, "anchor": {"revision_non_tradier_rows": 4146, "match_rows": 4146}}'),
('1d', 'FTV', DATE '1990-01-01', DATE '2016-06-13', 'observed', 'ibkr', 'tradier',
 'Basis correction 2026-10-15 (todo 535 item 42): tradier consolidated 1d is back-adjusted before 2023-01-03 (median -7.77% vs ibkr over 1,636 paired sessions); canonical restored to the unadjusted ibkr basis. Split around the closed 185-47 one-day row at 2016-06-13 (same primary; no gap).',
 '{"measured": "2026-10-15", "median_drift_pct": -7.77, "paired_pre2023_days": 1636, "n_stored": 2586, "n_ibkr_raw": 2600, "ibkr_coverage_pct": 100.5, "anchor": {"revision_non_tradier_rows": 2595, "match_rows": 2595}}'),
('1d', 'FTV', DATE '2016-06-14', DATE '2026-10-07', 'observed', 'ibkr', 'tradier',
 'Basis correction 2026-10-15 (todo 535 item 42): second span of the FTV basis correction (see the 1990-01-01 row).',
 '{"measured": "2026-10-15", "median_drift_pct": -7.77, "paired_pre2023_days": 1636, "split_around": "185-47 one-day row 2016-06-13"}'),
('1d', 'CUBI', DATE '1990-01-01', DATE '2026-10-07', 'observed', 'ibkr', 'tradier',
 'Basis correction 2026-10-15 (todo 535 item 42): tradier consolidated 1d is back-adjusted before 2023-01-03 (median +4.82% vs ibkr over 2,425 paired sessions); canonical restored to the unadjusted ibkr basis.',
 '{"measured": "2026-10-15", "median_drift_pct": 4.82, "paired_pre2023_days": 2425, "n_stored": 3374, "n_ibkr_raw": 3374, "ibkr_coverage_pct": 100.0, "anchor": {"revision_non_tradier_rows": 3365, "match_rows": 3365}}'),
('1d', 'FTI', DATE '1990-01-01', DATE '2026-10-07', 'observed', 'ibkr', 'tradier',
 'Basis correction 2026-10-15 (todo 535 item 42): tradier consolidated 1d is back-adjusted before 2023-01-03 (median +4.15% vs ibkr over 5,420 paired sessions); canonical restored to the unadjusted ibkr basis. Anchor is thin (3 revision + 8 stored days, all exact); recorded as such.',
 '{"measured": "2026-10-15", "median_drift_pct": 4.15, "paired_pre2023_days": 5420, "n_stored": 6370, "n_ibkr_raw": 6370, "ibkr_coverage_pct": 100.0, "anchor": {"revision_non_tradier_rows": 3, "match_rows": 3, "stored_non_tradier_days": 8}}'),
('1d', 'IP', DATE '1990-01-01', DATE '2006-10-02', 'observed', 'ibkr', 'tradier',
 'Basis correction 2026-10-15 (todo 535 item 42): tradier consolidated 1d is back-adjusted before 2023-01-03 (median -2.37% vs ibkr over 1,675 paired sessions); canonical restored to the unadjusted ibkr basis. ibkr raw is deeper than stored (5,037 vs 2,623 days): the restore also extends depth. Split around the closed 185-47 one-day row at 2006-10-02 (same primary; no gap).',
 '{"measured": "2026-10-15", "median_drift_pct": -2.37, "paired_pre2023_days": 1675, "n_stored": 2623, "n_ibkr_raw": 5037, "ibkr_coverage_pct": 192.0, "anchor": {"revision_non_tradier_rows": 5037, "match_rows": 5037}}'),
('1d', 'IP', DATE '2006-10-03', DATE '2026-10-07', 'observed', 'ibkr', 'tradier',
 'Basis correction 2026-10-15 (todo 535 item 42): second span of the IP basis correction (see the 1990-01-01 row).',
 '{"measured": "2026-10-15", "median_drift_pct": -2.37, "paired_pre2023_days": 1675, "split_around": "185-47 one-day row 2006-10-02"}'),
('1d', 'PFE', DATE '1990-01-01', DATE '2026-10-07', 'observed', 'ibkr', 'tradier',
 'Basis correction 2026-10-15 (todo 535 item 42): tradier consolidated 1d is back-adjusted before 2023-01-03 (median -2.35% vs ibkr over 5,786 paired sessions); canonical restored to the unadjusted ibkr basis.',
 '{"measured": "2026-10-15", "median_drift_pct": -2.35, "paired_pre2023_days": 5786, "n_stored": 6736, "n_ibkr_raw": 6834, "ibkr_coverage_pct": 101.5, "anchor": {"revision_non_tradier_rows": 5085, "match_rows": 5085}}');
