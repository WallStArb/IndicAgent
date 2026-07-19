-- Remove NOT NULL constraint. Application code stops writing this field.
-- The column stays for historical rows; DROP COLUMN in a future cleanup migration
-- once all v1/v2 rows have aged out of query windows.
ALTER TABLE signal_ledger
    ALTER COLUMN signal_schema_version DROP NOT NULL;

ALTER TABLE signal_ledger
    ALTER COLUMN signal_schema_version SET DEFAULT NULL;
