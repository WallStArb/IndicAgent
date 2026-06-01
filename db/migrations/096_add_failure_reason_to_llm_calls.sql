-- Migration 096: Add failure_reason column to llm_calls
--
-- Wires through the failure_reason field emitted by LLMProviderChain.generate_structured()
-- when instructor/structured generation fails. Previously silently dropped (Phase 094 deferral).

ALTER TABLE llm_calls ADD COLUMN IF NOT EXISTS failure_reason TEXT;
