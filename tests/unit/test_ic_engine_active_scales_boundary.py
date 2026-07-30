"""Boundary test: after the 2026-07-30 per-tf active-scale-set design landed, the
module-level `_SCALES` constant was deleted from ic_engine.py -- every call site
resolves the active set per-tf via config.active_scales_for(tf) instead. Guards
against reintroduction. Mirrors test_market_data_ohlcv_boundary.py's allow-list
pattern."""

from __future__ import annotations

from pathlib import Path

_IC_ENGINE_PATH = Path(__file__).parent.parent.parent / "services" / "ic_engine.py"

# ACTIVE_SCALES_FALLBACKS_BY_TF (Task 2, services/_batch_utils.py) contains the
# substring "_SCALES" but is a distinct identifier -- the per-tf fallback dict
# consumed by ICEngineConfig.from_apr, not the module-level _SCALES tuple this
# boundary test is guarding against. Stripped out of each line before checking
# for a bare _SCALES token, so a line combining a legitimate reference to this
# identifier with an unrelated bare _SCALES use is still caught.
_ALLOWED_SUBSTRING = "ACTIVE_SCALES_FALLBACKS_BY_TF"


def test_no_bare_scales_reference():
    lines = _IC_ENGINE_PATH.read_text().splitlines()
    violations = []
    for i, line in enumerate(lines, start=1):
        remainder = line.replace(_ALLOWED_SUBSTRING, "")
        if "_SCALES" not in remainder:
            continue
        violations.append((i, line.strip()))
    assert not violations, (
        "Bare _SCALES reference(s) found -- use config.active_scales_for(tf) "
        f"instead: {violations}"
    )
