"""Regression test: SafeAgentWrapper deleted in Phase 78 (D-18).

Asserts that importing src.core.ai.safe_wrapper raises ImportError
so that any orphaned reference is caught immediately in CI.
"""

import pytest


def test_safe_wrapper_import_raises_import_error() -> None:
    """Importing safe_wrapper must raise ImportError with Phase 78 message."""
    with pytest.raises(ImportError, match="deleted in Phase 78"):
        import src.core.ai.safe_wrapper  # noqa: F401
