"""The response shape every dashboard read route returns (dashboard v3.5 design decision 4).

`source` names the table, view or system the rows came from and `as_of` the newest timestamp in
them (the lineage the page shows beside each figure); route-specific extras go in `meta`, never
as new top-level keys, so the dashboard reads one shape.
"""

from datetime import datetime
from typing import Any, TypedDict


class Envelope(TypedDict):
    source: str | None
    as_of: datetime | None
    rows: list[dict[str, Any]]
    meta: dict[str, Any]


def newest(rows: list[dict[str, Any]], key: str) -> datetime | None:
    """The latest non-null `key` across rows, or None when there is none."""
    return max((r[key] for r in rows if r.get(key) is not None), default=None)


def envelope(
    source: str | None,
    rows: list[dict[str, Any]],
    as_of: datetime | None,
    **meta: Any,
) -> Envelope:
    return {"source": source, "as_of": as_of, "rows": rows, "meta": meta}
