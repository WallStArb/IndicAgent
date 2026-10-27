"""The response shape every dashboard read route returns (dashboard v3.5 design decision 4).

`source` names the table, view or system the rows came from and `as_of` the newest timestamp in
them (the lineage the page shows beside each figure); route-specific extras go in `meta`, never
as new top-level keys, so the dashboard reads one shape.
"""

import asyncio
from collections.abc import Awaitable, Mapping
from datetime import datetime
from typing import Any, TypedDict

import structlog

logger = structlog.get_logger(__name__)


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


def all_ok(sections: Mapping[str, Envelope]) -> bool:
    """No section failed: a page with a failed section is not cached, so the next poll retries."""
    return not any("error" in env["meta"] for env in sections.values())


async def gather_sections(sections: Mapping[str, Awaitable[Envelope]]) -> dict[str, Envelope]:
    """Run a page's section queries together; a section whose query raises becomes an empty
    envelope with `meta.error` (logged), so one failure cannot take down the page. Cancellation
    is never swallowed."""
    results = await asyncio.gather(*sections.values(), return_exceptions=True)
    out: dict[str, Envelope] = {}
    for name, result in zip(sections, results, strict=True):
        if isinstance(result, asyncio.CancelledError):
            raise result
        if isinstance(result, BaseException):
            logger.warning("api.section_failed", section=name, error=repr(result))
            out[name] = envelope(None, [], None, error=type(result).__name__)
        else:
            out[name] = result
    return out
