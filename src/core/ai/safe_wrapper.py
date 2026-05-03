"""Stub: SafeAgentWrapper deleted in Phase 78 (D-18).

BaseAIAgent.compute() already provides asyncio.wait_for + neutral fallback.
Importing this module raises ImportError to surface any orphaned references loudly.
"""

raise ImportError(
    "SafeAgentWrapper was deleted in Phase 78 (D-18). "
    "Use BaseAIAgent directly — it provides asyncio.wait_for + neutral fallback."
)
