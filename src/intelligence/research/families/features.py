"""The feature family module: members that read a declared stored feature column or a research
kernel output, aligned to the book clock and optionally smoothed (phase 184 B6).

| Member | statistic | window | Sign |
|---|---|---|---|
| any feature or kernel member | the member's declared input, a stored feature column or a kernel
output aligned to the book clock (align.py) and optionally smoothed (smoothing.py) | the spec's
input block | pinned in the member's params |

The member contract differs from the other family modules in one respect: the first argument is
the member's declared input (an aligned, optionally smoothed [n, m] array), not S1 residual bar
returns; the runner hands it over once plan 184-10 wires input members. The member adds no
history of its own over that input, so its slot history is the input's memory
(member_memory.feature_member_memory).

The battery behind this module (`NULL_BATTERY`) certifies a member only for a configuration it
tested (null_battery_persistent.admit).
"""

from __future__ import annotations

import numpy as np

from src.intelligence.research.families.common import centred_rank

NULL_BATTERY = "src.intelligence.research.null_battery_persistent"


def centred(
    x: np.ndarray, *, bars_per_session: int, coverage_floor: int, sign: int = 1
) -> np.ndarray:
    """sign * the centred cross-sectional rank of the member's input; NaN on a row with fewer
    than `coverage_floor` finite values. `bars_per_session` is part of the member contract and
    unused: the rank is per row."""
    if not isinstance(sign, int) or isinstance(sign, bool) or sign not in (-1, 1):
        raise ValueError(f"sign must be +1 or -1, got {sign!r}")
    del bars_per_session
    return sign * centred_rank(x, coverage_floor=coverage_floor)
