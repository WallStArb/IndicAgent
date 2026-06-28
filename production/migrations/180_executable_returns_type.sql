-- Migration 180: Executable Returns Type Column (Invariant 1)
--
-- Adds return_type column to forward_returns to distinguish between executable
-- and theoretical return computations. IC engine MUST filter for 'executable_open_to_open'
-- to satisfy Renaissance Invariant 1.
--
-- The existing rows in forward_returns were computed using ln(open[T+N+1] / open[T+1])
-- which is the executable formula (market-on-open entry, market-on-open exit).
-- We mark them as 'executable_open_to_open' to reflect this.
--
-- All statements idempotent: ALTER TABLE IF NOT EXISTS pattern equivalent.

-- Section 1: Add return_type column with CHECK constraint
DO $$
BEGIN
    -- Add column if not exists
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'forward_returns' AND column_name = 'return_type'
    ) THEN
        ALTER TABLE forward_returns
            ADD COLUMN return_type text
            NOT NULL DEFAULT 'executable_open_to_open';

        -- Add check constraint
        ALTER TABLE forward_returns
            ADD CONSTRAINT forward_returns_return_type_check
            CHECK (return_type IN ('executable_open_to_open', 'theoretical'));
    END IF;
END $$;

-- Section 2: Set existing rows to executable_open_to_open
-- (This is a no-op if the DEFAULT was applied, but ensures consistency)
UPDATE forward_returns
SET return_type = 'executable_open_to_open'
WHERE return_type IS NULL OR return_type != 'executable_open_to_open';

-- Section 3: Add index for return_type filter (IC engine queries)
CREATE INDEX IF NOT EXISTS forward_returns_return_type_idx
    ON forward_returns (return_type, symbol, tf, bar_ts);

-- Section 4: Comment the column
COMMENT ON COLUMN forward_returns.return_type IS
    'Return computation type: executable_open_to_open (ln(open[T+N+1]/open[T+1])) or theoretical (ln(close[T+N]/close[T])). IC engine MUST filter for executable_open_to_open.';
