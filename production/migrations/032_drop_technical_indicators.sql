-- Drop legacy EAV indicator table — never written to by any active service.
-- All indicator data lives in intelligence_features JSONB. See migration 022 comment.
DROP TABLE IF EXISTS technical_indicators CASCADE;
