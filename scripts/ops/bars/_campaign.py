"""Phase 185 campaign preflight (D-30).

Every phase 185 campaign (plans 13-24) funnels through this check before it
touches IBKR: the campaign owns client ids 47-49 and nothing else, because 46
and 40 belong to the todo 449 intraday chain and 45 to the nightly. Two
processes on one client id force an IBKR re-login race; worse, a campaign
silently riding the chain's id makes the chain's own reconnects kill it.

This module holds only the refusal. Windowing schemes and request-counting
machinery were considered and deleted from the design (2026-09-27): the lease
(plan 09) already serializes the stream, and request rates are the provider's
own pre-emptive limiter's business.

Usage from a campaign script that has loaded APR into a mapping::

    apr = {...}  # config_state rows, e.g. via load_apr_dict_async
    preflight(client_id=args.client_id, apr=apr)
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any


class CampaignRefused(RuntimeError):
    """A campaign precondition failed; the script must not start."""


_CLIENT_IDS_KEY = "infra.bar_campaign.client_ids"


def preflight(*, client_id: int, apr: Mapping[str, Any]) -> None:
    """Refuse to run on a client id outside infra.bar_campaign.client_ids.

    Fails closed: a missing key or a malformed value also refuses (the one
    thing this check must never do is guess that an id is probably fine).
    """
    raw = apr.get(_CLIENT_IDS_KEY)
    if raw is None:
        raise CampaignRefused(
            f"{_CLIENT_IDS_KEY} absent from APR; refusing to start a campaign "
            "without the reserved-lane list (D-30)"
        )
    try:
        allowed = json.loads(raw) if isinstance(raw, str) else list(raw)
    except (TypeError, ValueError) as error:
        raise CampaignRefused(
            f"{_CLIENT_IDS_KEY} is malformed ({raw!r}); refusing to start (D-30)"
        ) from error
    if client_id not in allowed:
        raise CampaignRefused(
            f"client id {client_id} is outside {_CLIENT_IDS_KEY}={allowed}; "
            "46 and 40 belong to the todo 449 intraday chain, 45 to the nightly "
            "(D-30)"
        )
