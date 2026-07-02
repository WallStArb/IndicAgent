"""Unit test: Invariant 1 enforcement (executable_open_to_open) in ensemble_ic_engine.py source.

CLAUDE.md Invariant 1: IC measurement MUST use forward_returns.return_type =
'executable_open_to_open'. This is a grep-as-test that reads the source file as a
string and asserts the literal substring is present -- guards against a future edit
silently reverting to theoretical returns (which capture untradeable overnight gaps
and overstate IC).

No DB, no Kafka. Pure string assertion.
"""

from __future__ import annotations

from pathlib import Path

_SOURCE_PATH = Path(__file__).parent.parent.parent / "services" / "ensemble_ic_engine.py"


def _read_source() -> str:
    assert _SOURCE_PATH.exists(), f"services/ensemble_ic_engine.py not found at {_SOURCE_PATH}"
    return _SOURCE_PATH.read_text()


def test_executable_open_to_open_filter_present():
    """The forward_returns SQL string must contain the executable_open_to_open filter."""
    source = _read_source()
    assert "return_type = 'executable_open_to_open'" in source, (
        "services/ensemble_ic_engine.py must filter forward_returns on "
        "return_type = 'executable_open_to_open' (Invariant 1)"
    )


def test_no_theoretical_return_type_substring():
    """The literal 'theoretical' substring must never appear (no silent fallback)."""
    source = _read_source()
    assert "theoretical" not in source, (
        "services/ensemble_ic_engine.py must not reference the 'theoretical' "
        "return_type value -- Invariant 1 requires executable_open_to_open only"
    )
