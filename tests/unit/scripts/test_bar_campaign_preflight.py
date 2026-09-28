"""Unit tests for the phase 185 campaign preflight (scripts/ops/bars/_campaign.py, D-30).

Pure function tests: the APR mapping arrives as a plain dict exactly as a caller
that has already loaded config_state would pass it. The one rule: a campaign
client id outside infra.bar_campaign.client_ids refuses to start, and anything
that prevents the check from being evaluated (missing key, malformed value)
refuses too -- never falls back to "probably fine", because 46 and 40 belong to
the todo 449 chain and 45 to the nightly, and a collision there costs the stream.
"""

from __future__ import annotations

import pytest
from scripts.ops.bars._campaign import CampaignRefused, preflight

_APR = {"infra.bar_campaign.client_ids": "[47, 48, 49]"}


@pytest.mark.parametrize("client_id", [47, 48, 49])
def test_campaign_lanes_pass(client_id: int) -> None:
    preflight(client_id=client_id, apr=_APR)


@pytest.mark.parametrize("client_id", [46, 45, 40, 44, 50, 51])
def test_non_campaign_lanes_are_refused(client_id: int) -> None:
    with pytest.raises(CampaignRefused) as excinfo:
        preflight(client_id=client_id, apr=_APR)
    # The refusal names the reserved owners so the operator can see the collision.
    assert "449" in str(excinfo.value) or "nightly" in str(excinfo.value)


def test_missing_apr_key_refuses() -> None:
    with pytest.raises(CampaignRefused):
        preflight(client_id=47, apr={})


def test_malformed_apr_value_refuses() -> None:
    with pytest.raises(CampaignRefused):
        preflight(client_id=47, apr={"infra.bar_campaign.client_ids": "not json{"})


def test_already_parsed_list_is_accepted() -> None:
    apr = {"infra.bar_campaign.client_ids": [47, 48, 49]}
    preflight(client_id=48, apr=apr)
    with pytest.raises(CampaignRefused):
        preflight(client_id=46, apr=apr)
