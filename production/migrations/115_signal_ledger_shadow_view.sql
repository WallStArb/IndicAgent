-- Migration 115: signal_ledger_shadow view
--
-- Provides a clean, nameable interface for shadow-specific queries.
-- Base is signal_ledger_full (Phase 095), which JOINs signal_ledger +
-- signal_outcomes and surfaces is_shadow, was_selected, cis_score, pnl_r.
--
-- Used by: shadow_validator.py (Phase 120), Grafana dashboards, future analytics.

CREATE VIEW signal_ledger_shadow AS
  SELECT *
  FROM signal_ledger_full
  WHERE is_shadow = true;
