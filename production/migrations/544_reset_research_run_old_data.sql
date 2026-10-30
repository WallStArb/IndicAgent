-- Migration 544: reset the research ledger (owner decision 2026-10-30)
--
-- Every real-data research result so far (54 research_run rows: 27 legacy verdicts, 27 vintage_1 runs
-- including 1 refused book test, with 22 research_run_series rows) was produced on incomplete bar data and
-- an unsettled universe, before the 186-26 feature rebuild. The owner voided them and restarts the testing
-- program from scratch once data and features are clean (.planning/STATE.md). The rows are backed up in
-- data/backups/reset-2026-10-30/ (research_run_and_series.dump, pg_dump -Fc; .sql, --inserts).
--
-- The ledger is append-only by design (triggers block DELETE and TRUNCATE) and there is no built reset
-- path (select_books.py refuses a second vintage), so this one-time reset disables the guard triggers inside
-- one transaction and re-enables them before commit. It is the only sanctioned exception; the sole writer
-- stays the S6 ledger.
--
-- Not touched: the concept layer (concept_registry statuses drive which features feature_factory computes;
-- resetting it is coordinated with the 186-26 rebuild), .planning/gate_look_log.jsonl (the record of looks
-- at the forward span; deleting rows does not un-see data) and the synthetic battery records. Idempotent.

BEGIN;

ALTER TABLE research_run DISABLE TRIGGER trg_research_run_guard;
ALTER TABLE research_run DISABLE TRIGGER trg_research_run_no_delete;
ALTER TABLE research_run_series DISABLE TRIGGER trg_research_run_series_guard;

DELETE FROM research_run_series;
DELETE FROM research_run;

ALTER TABLE research_run ENABLE TRIGGER trg_research_run_guard;
ALTER TABLE research_run ENABLE TRIGGER trg_research_run_no_delete;
ALTER TABLE research_run_series ENABLE TRIGGER trg_research_run_series_guard;

COMMIT;
