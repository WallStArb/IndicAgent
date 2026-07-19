-- Migration 104: add feature_schema_version column to intelligence_features
--
-- Adds a nullable INTEGER column feature_schema_version with NO default.
-- Pre-fix rows must remain NULL (per D-01 contamination boundary contract).
-- Post-deploy rows written by feature_writer will carry FEATURE_SCHEMA_VERSION = 2.
--
-- DO NOT touch the existing schema_version TEXT column — that is a different
-- version field (text '1.0'); this new INTEGER column is named feature_schema_version.

BEGIN;

ALTER TABLE intelligence_features
    ADD COLUMN IF NOT EXISTS feature_schema_version INTEGER;

COMMIT;
