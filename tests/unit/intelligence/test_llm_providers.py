"""Unit tests for LLM provider correctness.

OllamaProvider, OpenRouterProvider, LLMChain, and _call_llm_with_circuit_breaker
have been removed in Phase 094-02. Tests covering those classes have been deleted.

Remaining tests cover production code invariants that are still enforced:
- Alpha agent system messages must not use /no_think prefix (use think=False in payload).
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# TestAlphaAgentSystemMessages — verify /no_think prefix removed
# ---------------------------------------------------------------------------


class TestAlphaAgentSystemMessages:
    """Verify that alpha agent system messages do NOT contain /no_think prefix.

    Ollama only interprets /no_think at the start of user-turn messages,
    not system messages. OllamaProvider uses think=False in the payload
    for the correct mechanism, so the system message prefix is dead weight.
    """

    def test_skeptic_no_think_prefix(self):
        """SkepticComputeAgent._SYSTEM_MESSAGE must not start with /no_think."""
        from src.intelligence.ai.alpha.skeptic_agent import _SYSTEM_MESSAGE

        assert not _SYSTEM_MESSAGE.startswith(
            "/no_think"
        ), "System message should not have /no_think prefix; use think=False in payload instead"
        assert "JSON" in _SYSTEM_MESSAGE, "System message must instruct JSON-only output"

    def test_correlation_no_think_prefix(self):
        """CorrelationComputeAgent._SYSTEM_MESSAGE must not start with /no_think."""
        from src.intelligence.ai.alpha.correlation_agent import _SYSTEM_MESSAGE

        assert not _SYSTEM_MESSAGE.startswith(
            "/no_think"
        ), "System message should not have /no_think prefix; use think=False in payload instead"
        assert "JSON" in _SYSTEM_MESSAGE, "System message must instruct JSON-only output"

    def test_regime_coherence_no_think_prefix(self):
        """RegimeCoherenceComputeAgent._SYSTEM_MESSAGE must not start with /no_think."""
        from src.intelligence.ai.alpha.regime_coherence_agent import _SYSTEM_MESSAGE

        assert not _SYSTEM_MESSAGE.startswith(
            "/no_think"
        ), "System message should not have /no_think prefix; use think=False in payload instead"
        assert "JSON" in _SYSTEM_MESSAGE, "System message must instruct JSON-only output"

    def test_counterfactual_no_think_prefix(self):
        """CounterfactualComputeAgent._SYSTEM_MESSAGE must not start with /no_think."""
        from src.intelligence.ai.alpha.counterfactual_agent import _SYSTEM_MESSAGE

        assert not _SYSTEM_MESSAGE.startswith(
            "/no_think"
        ), "System message should not have /no_think prefix; use think=False in payload instead"
        assert "JSON" in _SYSTEM_MESSAGE, "System message must instruct JSON-only output"
