-- 470: ohlcv_load.n_archived (todo 528 refused-chunk archive routing)
--
-- A revision-refused chunk's served rows are captured by the raw archive
-- (services.intraday_raw_archive.archive_refusal_rows, written in the same
-- second transaction as the refusal record). The count rides the refusal
-- row so the completeness check (R6) folds it in: an archived refusal is
-- neither loss nor refusal remainder. 0 on every applied load row.

ALTER TABLE ohlcv_load
    ADD COLUMN n_archived integer NOT NULL DEFAULT 0;

COMMENT ON COLUMN ohlcv_load.n_archived IS
    'refused chunk: served rows routed to ohlcv_intraday_raw_archive in the '
    'refusal transaction (todo 528); 0 otherwise';
