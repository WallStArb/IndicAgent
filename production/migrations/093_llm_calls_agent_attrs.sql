-- Migration 093: LLM call agent attribution columns
--
-- Adds agent_id, prompt_version, parse_success to llm_calls for per-agent
-- scoring and prompt A/B testing. Drives improvement feedback loops.

ALTER TABLE llm_calls ADD COLUMN IF NOT EXISTS agent_id TEXT;
ALTER TABLE llm_calls ADD COLUMN IF NOT EXISTS prompt_version TEXT;
ALTER TABLE llm_calls ADD COLUMN IF NOT EXISTS parse_success BOOLEAN DEFAULT TRUE;

-- Per-agent scoring (replaces call_type-only segmentation)
CREATE INDEX IF NOT EXISTS idx_llm_calls_agent_scoring
    ON llm_calls (agent_id, model, regime, win, pnl_r)
    WHERE outcome IS NOT NULL;
