-- Migration 138: Revoke write access to signal_ledger (read-only transition)
--
-- Phase 129 data migration complete. signal_ledger is retained read-only
-- for the 48-hour transition window per Phase 129 ROADMAP success criteria.
-- Phase 130 will DROP TABLE after all writers are verified using signal_events.

REVOKE INSERT, UPDATE, DELETE ON signal_ledger FROM PUBLIC;
-- NOTE: postgres is a superuser and bypasses all privilege checks. The REVOKE below
-- has no practical effect but is kept for documentation and non-superuser role coverage.
REVOKE INSERT, UPDATE, DELETE ON signal_ledger FROM postgres;
