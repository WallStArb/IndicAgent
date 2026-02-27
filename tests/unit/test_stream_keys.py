"""Tests for stream key helpers."""
from src.core.stream_keys import narratives_group


def test_narratives_group_no_prefix():
    key = narratives_group("", "equity")
    assert key == "narratives:group:equity"


def test_narratives_group_with_env_prefix():
    key = narratives_group("development:", "metals")
    assert key == "development:narratives:group:metals"


def test_narratives_group_all_groups():
    groups = ["equity", "energy", "metals", "rates", "fx_crypto", "ag"]
    for g in groups:
        key = narratives_group("", g)
        assert key == f"narratives:group:{g}"
