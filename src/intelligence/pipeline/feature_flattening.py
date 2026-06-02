"""feature_flattening — neutral module for flat feature dict construction.

Extracted from signal_processor.py (_I1_ALIAS_MAP, _build_features_from_event) and
renamed to build_flat_features() in Plan 05 (Phase 112). This is a neutral module:
it has no lateral imports from signal_processor.py or feature_pipeline_executor.py,
preventing the circular dependency that would result from importing these symbols
directly between those two modules.

Why neutral:
    feature_pipeline_executor.py needs build_flat_features() to precompute
    flat_features once per bar (3-E). signal_processor.py also uses the same function.
    If feature_pipeline_executor imported from signal_processor, it would create a
    circular dep (feature_pipeline_executor -> signal_processor -> executor ->
    feature_pipeline_executor). This module is the shared neutral ground.

Usage::

    from src.intelligence.pipeline.feature_flattening import _I1_ALIAS_MAP, build_flat_features

    flat = build_flat_features(event)  # -> dict with all tier fields flattened
"""

from __future__ import annotations

from typing import Any

from src.intelligence.schemas import I1Indicators, IntelligenceEvent

# ---------------------------------------------------------------------------
# I1 alias map (1-C): maps feature dict keys used in build_flat_features
# to their canonical I1Indicators.model_fields names. Validated at import time
# so any schema drift is caught immediately rather than silently at runtime.
#
# Moved from signal_processor.py (Plan 05) to prevent circular import.
# signal_processor.py and feature_pipeline_executor.py both import from here.
# ---------------------------------------------------------------------------

_I1_ALIAS_MAP: dict[str, str] = {
    # Bollinger Band aliases used in CIS scorer / downstream consumers
    "bb_middle": "bb_20_2_mid",
    "bb_upper": "bb_20_2_upper",
    "bb_lower": "bb_20_2_lower",
}

# Import-time assertion: every VALUE must exist in I1Indicators.model_fields
_I1_FIELDS = set(I1Indicators.model_fields.keys())
for _alias_key, _canonical in _I1_ALIAS_MAP.items():
    if _canonical not in _I1_FIELDS:
        raise ImportError(
            f"_I1_ALIAS_MAP validation failed: alias '{_alias_key}' -> '{_canonical}' "
            f"is not in I1Indicators.model_fields. Known fields: {sorted(_I1_FIELDS)}"
        )
del _alias_key, _canonical  # clean up loop variable from module scope

# HMM regime integer -> semantic label (used in build_flat_features)
_HMM_REGIME_LABEL: dict[int, str] = {0: "ranging", 1: "trending", 2: "trending"}


def build_flat_features(event: IntelligenceEvent) -> dict[str, Any]:
    """Build a flat features dict from a typed IntelligenceEvent for I7 plugins.

    Iterates event.i1 fields (applying _I1_ALIAS_MAP for BB aliases) then all tier
    sub-models (i2, i3, i4, i5, smc, i6), filtering None values.

    This function was previously private (_build_features_from_event) in
    signal_processor.py. It is now public and lives here so both
    feature_pipeline_executor.py (which precomputes flat_features once per bar)
    and signal_processor.py (which consumes it) can import from this neutral module
    without circular dependency.

    Args:
        event: Typed IntelligenceEvent with all tier sub-models populated.

    Returns:
        Flat dict with all non-None indicator + tier fields, plus aliases and
        hmm_regime_label derived from hmm_regime integer.
    """
    f: dict[str, Any] = {}
    for k, v in event.i1.model_dump().items():
        if v is not None:
            f[k] = v
    # Apply I1 aliases (BB field names used by CIS scorer and downstream I7 plugins).
    # Guard against None so aliases do not bypass the None filter applied to other fields.
    if event.i1.bb_20_2_mid is not None:
        f["bb_middle"] = event.i1.bb_20_2_mid
    if event.i1.bb_20_2_upper is not None:
        f["bb_upper"] = event.i1.bb_20_2_upper
    if event.i1.bb_20_2_lower is not None:
        f["bb_lower"] = event.i1.bb_20_2_lower
    for tier_key in ("i2", "i3", "i4", "i5", "smc", "i6"):
        sub = getattr(event, tier_key, None)
        if sub is not None:
            for k, v in sub.model_dump().items():
                if v is not None:
                    f[k] = v
    f["vix"] = getattr(event, "vix", None)
    hmm_val = f.get("hmm_regime")
    hmm_int = int(hmm_val) if hmm_val is not None else None
    f["hmm_regime_label"] = (
        _HMM_REGIME_LABEL.get(hmm_int, "unknown") if hmm_int is not None else None
    )
    return f
