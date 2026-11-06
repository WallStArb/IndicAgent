-- Migration 581: a paginated vendor answer records the window asked and whether it completed
-- (todo 596, lead rulings 2026-11-05).
--
-- A paginated leaf (Alpaca) answers one asked window in pages. Before this migration each page
-- row claimed [its resume point, the asked end], no page said whether it was the last, and a
-- failed page wrote no row, so a deadline stop after page 1 left page 1 claiming the rest of the
-- window. Measured 2026-11-05: 913,862 Alpaca-era 5m sessions with missing slots on 1,263 names
-- read as covered through ledger rows that never proved the window was answered.
--
-- Every page of one asked window now carries:
--   ask_id     the asked window's id, shared by all its pages;
--   page_index 0, 1, 2, ... in the order the pages were asked (page 0's window_start is the
--              asked start; window_end is the asked end on every page);
--   terminal   true when the vendor said the window has no further page (no next-page token),
--              false otherwise (a failed or timed-out page is never terminal).
-- The three are set together or not at all. NULL (every row written before this migration, and
-- every unpaginated IBKR request) is not an ask and never proves a complete answer.
--
-- ohlcv_ask_current is one row per ask. An ask is complete iff it has a terminal page, its page
-- count equals max(page_index) + 1 (no page missing), and no page failed or timed out. The leaf
-- commits each page's row with that page's bars in one transaction (services/bar_load.py,
-- persist_chunk_atomically), so a page row is also the proof its bars were stored. Pages run
-- 0..max with no gap: the unique (ask_id, page_index) index makes count = max + 1 exactly that.
-- A bar the answer served incomplete (a forming bar, a close before the settle delay) is held
-- back onto its page's partial_bars and is not stored: a complete ask answers every slot of
-- [ask_start, ask_end) except those, which readers exclude (gap_plan.live_partials).
--
-- Adding nullable columns without defaults rewrites nothing, so no VACUUM clause is owed.

BEGIN;

ALTER TABLE ohlcv_request
    ADD COLUMN IF NOT EXISTS ask_id uuid,
    ADD COLUMN IF NOT EXISTS page_index smallint,
    ADD COLUMN IF NOT EXISTS terminal boolean;

ALTER TABLE ohlcv_request DROP CONSTRAINT IF EXISTS ohlcv_request_ask_check;
ALTER TABLE ohlcv_request ADD CONSTRAINT ohlcv_request_ask_check CHECK (
    (ask_id IS NULL AND page_index IS NULL AND terminal IS NULL)
    OR (ask_id IS NOT NULL AND page_index IS NOT NULL AND page_index >= 0 AND terminal IS NOT NULL
        AND (NOT terminal OR outcome IN ('bars', 'no_data')))
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_ohlcv_request_ask_page
    ON ohlcv_request (ask_id, page_index) WHERE ask_id IS NOT NULL;

CREATE OR REPLACE VIEW ohlcv_ask_current AS
SELECT
    r.ask_id,
    r.fetch_run_id,
    r.symbol,
    r.timeframe,
    r.source,
    r.route,
    r.what_to_show,
    min(r.window_start) FILTER (WHERE r.page_index = 0) AS ask_start,
    max(r.window_end) AS ask_end,
    count(*)::int AS n_pages,
    sum(r.n_bars)::int AS n_bars,
    min(r.requested_at) AS requested_at,
    max(r.answered_at) AS answered_at,
    bool_or(r.outcome = 'bars') AS served_bars,
    bool_or(r.partial_bars IS NOT NULL AND r.partial_bars <> '[]'::jsonb) AS has_partial,
    (
        bool_or(r.terminal)
        AND count(*) = max(r.page_index) + 1
        AND bool_and(r.outcome IN ('bars', 'no_data'))
    ) AS complete
FROM ohlcv_request r
WHERE r.ask_id IS NOT NULL
-- Every column here is constant within an ask; grouping by them (not min()) lets a reader's
-- symbol/timeframe/source filter reach the base table's index instead of aggregating every ask.
-- An ask whose pages disagreed on one would split into groups whose page counts cannot match,
-- so it reads incomplete: fails closed.
GROUP BY r.ask_id, r.fetch_run_id, r.symbol, r.timeframe, r.source, r.route, r.what_to_show;

COMMENT ON VIEW ohlcv_ask_current IS
    'One row per asked window of a paginated vendor (migration 581, todo 596). complete iff a '
    'terminal page exists, page count = max(page_index) + 1 and no page failed or timed out. '
    'Rows without ask_id (legacy, IBKR) never appear and never prove completion.';

GRANT SELECT ON ohlcv_ask_current TO ohlcv_observation_writer, bar_derivation_writer;

COMMIT;
