"""The write contract's pure core: compare incoming bars with stored bars (plan 185-31).

Data layer integrity design (docs/plans/2026-10-06-data-layer-integrity-design.md) section 4:
every writer of a bar table reads the stored rows for its keys, classifies each incoming row as
new, changed or unchanged by exact value, writes only new and changed rows, records the old value
of every changed or removed row in ohlcv_revision, and refuses a write that revises more than
threshold.bar_integrity.max_revision_ratio of what is stored (a finding to look at, not to
auto-apply), unless the caller waives it for a recorded corporate action.

Pure functions, no I/O and no APR reads: callers pass the thresholds. One rule replaces each
writer's ad hoc compare (the grid stage first; 185-36, 185-38 and 185-39 follow).

Exact equality, on purpose: the same answer written twice must compare equal and any drift must
surface as a change, never be rounded away. Missing is None and None equals None; NaN never
reaches the contract (no_fill), and one that does raises, because NaN != NaN would report an
unchanged row as changed on every run.
"""

from __future__ import annotations

import math
from collections.abc import Collection, Hashable, Mapping
from dataclasses import dataclass, field

# (open, high, low, close, volume, source)
BarValues = tuple[float | None, float | None, float | None, float | None, int | None, str]


@dataclass(frozen=True)
class WriteDelta[K: Hashable]:
    """Incoming rows against stored rows: what a write must do and what it replaces."""

    new: dict[K, BarValues] = field(default_factory=dict)
    # key -> (new values, old values)
    changed: dict[K, tuple[BarValues, BarValues]] = field(default_factory=dict)
    unchanged: int = 0
    removed: dict[K, BarValues] = field(default_factory=dict)


def _has_nan(values: BarValues) -> bool:
    return any(isinstance(v, float) and math.isnan(v) for v in values)


def classify[K: Hashable](
    incoming: Mapping[K, BarValues],
    stored: Mapping[K, BarValues],
    *,
    removal_scope: Collection[K] | None = None,
) -> WriteDelta[K]:
    """Classify incoming rows against stored rows by exact value.

    `removed` holds the stored rows inside `removal_scope` that incoming no longer has. A
    derivation passes the keys of its whole output range (a slot it no longer derives is
    stale); an ingress chunk passes None, because a bar missing from an answer is not a
    deletion. Raises ValueError on a NaN in a compared row.
    """
    new: dict[K, BarValues] = {}
    changed: dict[K, tuple[BarValues, BarValues]] = {}
    unchanged = 0
    for key, values in incoming.items():
        old = stored.get(key)
        if old is None:
            if _has_nan(values):
                raise ValueError(f"NaN in incoming row {key!r}: missing is None, never NaN")
            new[key] = values
        elif values == old:
            unchanged += 1
        else:
            if _has_nan(values) or _has_nan(old):
                raise ValueError(f"NaN in compared row {key!r}: missing is None, never NaN")
            changed[key] = (values, old)
    removed: dict[K, BarValues] = {}
    if removal_scope is not None:
        scope = set(removal_scope)
        removed = {
            key: values for key, values in stored.items() if key in scope and key not in incoming
        }
    return WriteDelta(new=new, changed=changed, unchanged=unchanged, removed=removed)


def revision_ratio(delta: WriteDelta, n_stored: int) -> float:
    """(changed + removed) / stored; 0.0 when nothing is stored."""
    if n_stored <= 0:
        return 0.0
    return (len(delta.changed) + len(delta.removed)) / n_stored


def should_refuse(
    delta: WriteDelta, n_stored: int, max_ratio: float, *, min_stored: int, waived: bool
) -> bool:
    """True when the write revises more than `max_ratio` of at least `min_stored` stored rows.

    Below `min_stored` every restatement is written and recorded (a fetcher tail window holds
    about 78 5m bars and IBKR restates recent bars); `waived` is a recorded corporate action.
    """
    if waived or n_stored < min_stored:
        return False
    return revision_ratio(delta, n_stored) > max_ratio
