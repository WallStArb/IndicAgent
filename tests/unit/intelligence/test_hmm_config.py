"""The one declaration of the HMM parameters (186-13 review, D2 and D3).

`HmmConfig` (kernels/_hmm.py) declares every APR key the regime kernels read, with its field
name and default. These tests hold the other places that must agree with it: the
`FeatureFactoryConfig` hmm_* fields (the registry hands kernels that config), and the APR
schema (a mistyped key would silently take its fallback).
"""

from __future__ import annotations

import dataclasses
import re
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from src.intelligence.feature_factory import FeatureFactoryConfig
from src.intelligence.features.kernels import _hmm
from src.intelligence.features.kernels._hmm import FAMILY_SPECS, HmmConfig
from src.intelligence.features.kernels.regime import compute_regime_columns
from tests.unit.intelligence.regime_kernel_fixtures import SMALL_HMM_APR, make_synthetic_regime_bars

MIGRATIONS = Path(__file__).resolve().parents[3] / "production" / "migrations"


def _factory_config_hmm_defaults() -> dict[str, object]:
    return {
        f.name: f.default
        for f in dataclasses.fields(FeatureFactoryConfig)
        if f.name.startswith("hmm_")
    }


def test_feature_factory_config_hmm_fields_and_defaults_equal_hmm_params():
    """The loader with every key at its fallback gives the FeatureFactoryConfig defaults, field
    for field: a value or a field added in one place and not the other fails here."""
    from_loader = _hmm.hmm_config_fields_from_values(lambda key, default: default)
    assert from_loader == _factory_config_hmm_defaults()
    assert from_loader == dataclasses.asdict(HmmConfig())


def test_block_rows_is_an_argument_not_a_config_field():
    assert "hmm_rolling_block_rows" not in _factory_config_hmm_defaults()
    assert _hmm.load_rolling_block_rows(lambda key, default: default) == 16384
    assert _hmm.load_rolling_block_rows({"infra.hmm.rolling_block_rows": "64"}.get) == 64


def test_loader_casts_values_and_takes_the_fallback_for_a_missing_key():
    params = HmmConfig.from_values(
        {"feature.hmm.n_components": "5", "feature.hmm.min_state_occupation": 1}.get
    )
    assert params.hmm_n_components == 5 and isinstance(params.hmm_n_components, int)
    assert params.hmm_min_state_occupation == 1.0
    assert isinstance(params.hmm_min_state_occupation, float)
    assert params.hmm_random_state == 42  # the mapping has no such key


def test_from_config_reads_every_field_and_raises_on_a_missing_one():
    fields = dataclasses.asdict(HmmConfig(hmm_n_components=5))
    assert HmmConfig.from_config(SimpleNamespace(**fields)) == HmmConfig(hmm_n_components=5)
    del fields["hmm_churn_window"]
    with pytest.raises(AttributeError, match="hmm_churn_window"):
        HmmConfig.from_config(SimpleNamespace(**fields))
    params = HmmConfig()
    assert HmmConfig.from_config(params) is params


def test_small_test_config_only_names_keys_the_loader_reads():
    """A mistyped key in the shared test fixture would silently leave its default in force."""
    assert set(SMALL_HMM_APR) <= set(HmmConfig.apr_keys())


def test_schedule_defaults_are_derived_from_the_declaration():
    assert _hmm._WALK_FORWARD_DEFAULT_PARAMS == {
        "5m": (19800, 39600),
        "15m": (6600, 13200),
        "1h": (1650, 3300),
        "1d": (252, 504),
    }
    assert HmmConfig().walk_forward_schedule("1h") == (1650, 3300)
    with pytest.raises(ValueError, match="walk-forward HMM schedule"):
        HmmConfig().walk_forward_schedule("1m")
    assert _hmm._MIN_OBS_FACTOR_DEFAULT == 50


# ---------------------------------------------------------------------------
# Every key the loader reads exists in config_schema
# ---------------------------------------------------------------------------


def _schema_keys_after_migrations() -> set[str]:
    """config_schema keys the migrations leave in place, applied in number order: every quoted
    first column of an `INSERT INTO config_schema` VALUES list, minus the keys a later
    `DELETE FROM config_schema` names."""
    keys: set[str] = set()
    for path in sorted(MIGRATIONS.glob("*.sql"), key=lambda p: int(p.name.split("_")[0])):
        sql = path.read_text()
        for statement in re.split(r";\s*\n", sql):
            if re.search(r"INSERT\s+INTO\s+config_schema\b", statement):
                keys.update(re.findall(r"\(\s*'([\w.]+)'\s*,", statement))
            elif re.search(r"DELETE\s+FROM\s+config_schema\b", statement):
                keys.difference_update(re.findall(r"'([\w.]+)'", statement))
    return keys


def test_every_apr_key_the_loader_reads_is_in_config_schema():
    schema = _schema_keys_after_migrations()
    assert "alpha.hmm.random_state" in schema  # the parser sees real inserts
    assert "alpha.hmm.walk_forward.enabled" not in schema  # ... and the migration 410 delete
    wanted = {*HmmConfig.apr_keys(), _hmm.ROLLING_BLOCK_ROWS_KEY}
    assert sorted(wanted - schema) == []


# ---------------------------------------------------------------------------
# The two label-affecting numerics reach the output (D3)
# ---------------------------------------------------------------------------


def test_ridge_and_vol_floor_defaults_are_the_literals_they_replaced():
    params = HmmConfig()
    assert params.hmm_covariance_ridge == 1e-6
    assert params.hmm_momentum_vol_floor == 1e-8
    means = np.zeros((2, 3))
    covars = np.stack([np.eye(3) * 0.5, np.eye(3) * 2.0])
    obs = np.random.default_rng(3).normal(size=(50, 3))
    default = _hmm._log_emit_full(obs, means, covars)
    explicit = _hmm._log_emit_full(obs, means, covars, 1e-6)
    assert np.array_equal(default.view(np.uint64), explicit.view(np.uint64))
    assert not np.array_equal(default, _hmm._log_emit_full(obs, means, covars, 1e-2))


def test_momentum_vol_floor_changes_the_momentum_column_only_where_vol_is_below_it():
    bars = make_synthetic_regime_bars(200, 5)
    rows = list(range(200))
    kwargs = dict(vol_window=20, momentum_window=20, vol_of_vol_window=20)
    default, _ = _hmm._build_obs_matrix(rows, bars["close"], bars["volume"], **kwargs)
    explicit, _ = _hmm._build_obs_matrix(
        rows, bars["close"], bars["volume"], momentum_vol_floor=1e-8, **kwargs
    )
    assert np.array_equal(default.view(np.uint64), explicit.view(np.uint64))
    floored, _ = _hmm._build_obs_matrix(
        rows, bars["close"], bars["volume"], momentum_vol_floor=1.0, **kwargs
    )
    assert not np.array_equal(default[:, 2], floored[:, 2])
    assert np.array_equal(default[:, [0, 1, 3, 4]], floored[:, [0, 1, 3, 4]])


@pytest.mark.parametrize(
    "change", [{"hmm_covariance_ridge": 1e-2}, {"hmm_momentum_vol_floor": 1.0}], ids=str
)
def test_the_two_params_reach_the_kernel_output(change):
    bars = make_synthetic_regime_bars(1500, 42)
    base = HmmConfig.from_values(SMALL_HMM_APR.get)
    spec = FAMILY_SPECS["trend"]

    def run(params):
        return compute_regime_columns(bars["close"], bars["volume"], params, "1d", spec)

    want, got = run(base), run(dataclasses.replace(base, **change))
    assert any(
        not np.array_equal(want[name], got[name], equal_nan=True) for name in spec.numeric_outputs
    )
