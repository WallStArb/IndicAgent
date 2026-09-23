"""Postgres `real` (IEEE 754 float4) column range clamping.

Ring 0 (portable infrastructure, no domain vocab) so it can be imported by both a Ring 2
batch service (services/_batch_utils.py) and a Ring 1 domain module
(src/intelligence/features/feature_vector_persistence.py) without violating the Ring import
rule (Ring 1 must not import services/).

Root-caused live 2026-08-14 (todo 312): regime_writer.py's HMM posterior probabilities
occasionally produce a residual state probability (or entropy value) smaller in magnitude than
float4 can represent at all -- e.g. 1e-50 for a highly confident state assignment. Postgres
rejects such a value outright ("value out of range: underflow") rather than rounding it to
zero, even though every consumer of these columns already truncates to float32 precision on
read (migration 201/312's own rationale) -- so a near-zero residual is scientifically
indistinguishable from exactly 0.0 at any precision that survives the round trip anyway.
Clamping the underflow tail to 0.0 is the mathematically correct value at this precision, not
an approximation being papered over. The overflow tail is symmetric defensive coverage.

2026-09-22 (underflow-7symbol-real-column debug session): promoted out of
services/_batch_utils.py, where it originally lived as a private helper used only by
bulk_update_by_key. feature_vector_persistence.py's feature_vector_to_insert_params() -- the
single shared row-serializer for both the live asyncpg write path (feature_vector_writer.py)
and the batch psycopg write path (backfill_feature_factory.py) -- hit the identical Postgres
error class on a different write primitive (raw INSERT, not bulk_update_by_key's COPY+UPDATE)
that never got todo 312's fix. Shared here instead of duplicated so the two implementations
can't drift.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

# Confirmed live 2026-08-14 (`SELECT 1e-45::real` parses, `1e-46::real` raises "value out of
# range: underflow"; `SELECT 1e50::real` raises "out of range" the other tail) that Postgres's
# own boundary matches IEEE754 float32 exactly, including the subnormal range down to
# smallest_subnormal -- not just the "normal" range.
REAL_MIN_MAGNITUDE = float(np.finfo(np.float32).smallest_subnormal)
REAL_MAX_MAGNITUDE = float(np.finfo(np.float32).max)


def clamp_to_real_range(value: Any) -> Any:
    """Clamp a Python float (typically computed in float64) to what Postgres's `real`
    column type can actually store, before it reaches a write targeting one.

    NaN/Infinity are valid IEEE754 float4 values Postgres accepts natively -- left
    untouched, not this function's concern. `None` (SQL NULL) and non-float values
    (bool, int, str, datetime, UUID, ...) pass through unchanged.
    """
    if value is None or not isinstance(value, float) or not math.isfinite(value):
        return value
    magnitude = abs(value)
    if magnitude == 0.0 or REAL_MIN_MAGNITUDE <= magnitude <= REAL_MAX_MAGNITUDE:
        return value
    if magnitude < REAL_MIN_MAGNITUDE:
        return 0.0
    return math.copysign(REAL_MAX_MAGNITUDE, value)
