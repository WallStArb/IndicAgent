"""FEATURE_APR_FIELDS is the one table of FeatureFactoryConfig's APR keys (R2 item 3)."""

from __future__ import annotations

import dataclasses
import typing

import pytest

from src.intelligence.features.feature_factory_config import (
    FEATURE_APR_FIELDS,
    FeatureFactoryConfig,
)
from src.intelligence.features.kernels._hmm import HmmConfig


def _hmm_values() -> dict[str, typing.Any]:
    hints = typing.get_type_hints(HmmConfig)
    sample = {int: 3, float: 0.25, str: "diag"}
    return {f.metadata["apr_key"]: sample[hints[f.name]] for f in dataclasses.fields(HmmConfig)}


def _get(overrides: dict[str, typing.Any] | None = None):
    hmm = _hmm_values()
    overrides = overrides or {}

    def get(key: str, default: typing.Any = None) -> typing.Any:
        if key in overrides:
            return overrides[key]
        return hmm.get(key, default)

    return get


def test_the_table_names_every_apr_field_exactly_once() -> None:
    names = [name for name, _, _, _ in FEATURE_APR_FIELDS]
    keys = [key for _, key, _, _ in FEATURE_APR_FIELDS]
    assert len(set(names)) == len(names)
    assert len(set(keys)) == len(keys)
    fields = {f.name for f in dataclasses.fields(FeatureFactoryConfig)} - {"hmm"}
    assert set(names) == fields


def test_a_dataclass_default_equals_the_table_default() -> None:
    """Tests build configs directly, so a field may default on the dataclass too; the two copies
    of one default must agree."""
    by_name = {f.name: f for f in dataclasses.fields(FeatureFactoryConfig)}
    for name, key, _cast, default in FEATURE_APR_FIELDS:
        f = by_name[name]
        if f.default is not dataclasses.MISSING:
            assert f.default == default, (name, key)
        elif f.default_factory is not dataclasses.MISSING:
            assert f.default_factory() == default, (name, key)


def test_the_defaults_build_a_config_whose_fields_are_the_table_defaults() -> None:
    config = FeatureFactoryConfig.from_values(_get())
    for name, _key, cast, default in FEATURE_APR_FIELDS:
        value = getattr(config, name)
        assert value == default, name
        assert type(value) is (dict if cast is dict else cast), name
    assert config.hmm == HmmConfig.from_values(_get())


def test_every_key_is_read_with_its_table_default_and_cast() -> None:
    seen: dict[str, typing.Any] = {}
    hmm = _hmm_values()

    def get(key: str, default: typing.Any = None) -> typing.Any:
        if key in hmm:
            return hmm[key]
        seen[key] = default
        return default

    FeatureFactoryConfig.from_values(get)
    assert seen == {key: default for _, key, _, default in FEATURE_APR_FIELDS}


def test_a_live_value_overrides_and_is_cast() -> None:
    config = FeatureFactoryConfig.from_values(
        _get({"feature.momentum.window_fast": "7", "feature.sr.cluster_atr_mult": "0.9"})
    )
    assert config.momentum_window_fast == 7
    assert config.sr_cluster_atr_mult == pytest.approx(0.9)


def test_a_json_object_key_takes_a_dict_or_a_json_string_and_falls_back_otherwise() -> None:
    key = "feature.ctf.higher_tf_map"
    assert FeatureFactoryConfig.from_values(_get({key: {"5m": "1d"}})).ctf_higher_tf_map == {
        "5m": "1d"
    }
    assert FeatureFactoryConfig.from_values(_get({key: '{"5m": "1h"}'})).ctf_higher_tf_map == {
        "5m": "1h"
    }
    default = next(d for _, k, _, d in FEATURE_APR_FIELDS if k == key)
    assert FeatureFactoryConfig.from_values(_get({key: 5})).ctf_higher_tf_map == default


def test_a_missing_hmm_key_raises_and_a_none_feature_value_raises() -> None:
    with pytest.raises(KeyError):
        FeatureFactoryConfig.from_values(lambda key, default=None: default)
    with pytest.raises(TypeError):
        FeatureFactoryConfig.from_values(_get({"feature.momentum.window_fast": None}))


def test_apr_keys_lists_every_key_the_loader_reads() -> None:
    keys = FeatureFactoryConfig.apr_keys()
    assert set(keys) == {k for _, k, _, _ in FEATURE_APR_FIELDS} | set(HmmConfig.apr_keys())
    assert len(keys) == len(set(keys))
