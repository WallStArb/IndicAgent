"""Boundary test: after the 2026-07-30 per-tf active-scale-set design landed, no
bare `_SCALES` module-constant reference should survive in ic_engine.py's compute
functions -- every call site must resolve the active set per-tf via
config.active_scales_for(tf) instead. Mirrors test_market_data_ohlcv_boundary.py's
allow-list pattern."""

from __future__ import annotations

import re
from pathlib import Path

_IC_ENGINE_PATH = Path(__file__).parent.parent.parent / "services" / "ic_engine.py"

# Lines allowed to reference the bare _SCALES name: its own definition, and any
# future explicitly-reviewed exception added here with a comment explaining why.
_ALLOWED_LINE_PATTERNS = (
    r"^_SCALES:\s*tuple\[str, \.\.\.\]\s*=",  # the definition itself
    # ACTIVE_SCALES_FALLBACKS_BY_TF (Task 2, services/_batch_utils.py) contains the
    # substring "_SCALES" but is a distinct identifier -- the per-tf fallback dict
    # consumed by ICEngineConfig.from_apr, not the module-level _SCALES tuple this
    # boundary test is guarding against. Import and single from_apr usage site only.
    r".*ACTIVE_SCALES_FALLBACKS_BY_TF.*",
)


def test_no_bare_scales_reference_outside_allow_list():
    lines = _IC_ENGINE_PATH.read_text().splitlines()
    violations = []
    for i, line in enumerate(lines, start=1):
        if "_SCALES" not in line:
            continue
        if any(re.match(pat, line.strip()) for pat in _ALLOWED_LINE_PATTERNS):
            continue
        violations.append((i, line.strip()))
    assert not violations, (
        "Bare _SCALES reference(s) found outside the allow-list -- use "
        f"config.active_scales_for(tf) instead: {violations}"
    )
