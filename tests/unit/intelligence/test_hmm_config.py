"""The one declaration of the HMM parameters (186-13 review, D2, D3 and R1).

`HmmConfig` (kernels/_hmm.py) declares every APR key the regime kernels read, with its field
name and no default. These tests hold what must agree with it: the APR schema (a mistyped key
would be a key no migration seeds) and the live seeded values.
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


def test_block_rows_is_an_argument_not_a_config_field():
    assert "hmm_rolling_block_rows" not in {f.name for f in dataclasses.fields(HmmConfig)}
    assert "hmm" in {f.name for f in dataclasses.fields(FeatureFactoryConfig)}
    assert _hmm.load_rolling_block_rows(lambda key, default: default) == 16384
    assert _hmm.load_rolling_block_rows({"infra.hmm.rolling_block_rows": "64"}.get) == 64


def test_loader_casts_values():
    params = HmmConfig.from_values({**SMALL_HMM_APR, "feature.hmm.n_components": "5"}.get)
    assert params.hmm_n_components == 5 and isinstance(params.hmm_n_components, int)
    assert isinstance(params.hmm_min_state_occupation, float)
    assert isinstance(params.hmm_covariance_type, str)


@pytest.mark.parametrize("key", HmmConfig.apr_keys())
def test_loader_raises_naming_any_missing_key(key):
    """No HMM key has a default: each changes stored labels, so a missing one is a loud error
    that names it (RED before R1: the loader took a fallback and ran a different model)."""
    values = {k: v for k, v in SMALL_HMM_APR.items() if k != key}
    with pytest.raises(KeyError, match=re.escape(key)):
        HmmConfig.from_values(values.get)


def test_the_kernels_raise_when_the_config_is_not_wired():
    from src.intelligence.features.kernels.regime import _hmm_config

    with pytest.raises(ValueError, match="FeatureFactoryConfig.hmm is None"):
        _hmm_config(SimpleNamespace(hmm=None))


def test_small_test_config_is_a_complete_snapshot():
    """SMALL_HMM_APR names exactly the keys the loader reads: a mistyped key would otherwise
    leave its value unset (now an error) and a stale one would linger unread."""
    assert set(SMALL_HMM_APR) == set(HmmConfig.apr_keys())


def test_schedule_lookup():
    params = HmmConfig.from_values(SMALL_HMM_APR.get)
    assert params.walk_forward_schedule("1d") == (300, 600)
    with pytest.raises(ValueError, match="walk-forward HMM schedule"):
        params.walk_forward_schedule("1m")


# The keys and values migrations seed, which a fresh database starts from and live APR holds
# (verified against config_state 2026-09-30). The kernels' stored labels depend on them.
_SEEDED_LIVE_VALUES = {
    "feature.hmm.n_components": 5,
    "feature.hmm.vol_window": 20,
    "feature.hmm.obs_momentum_window": 20,
    "feature.hmm.obs_vol_of_vol_window": 20,
    "feature.hmm.n_iter": 200,
    "alpha.hmm.random_state": 42,
    "feature.hmm.covariance_type": "full",
    "feature.hmm.min_hold_bars": 3,
    "feature.hmm.full_cov_min_obs": 500,
    "feature.hmm.min_state_occupation": 0.05,
    "feature.hmm.churn_window": 10,
    "feature.hmm.min_obs_factor": 50,
    "alpha.hmm.covariance_ridge": 1e-6,
    "alpha.hmm.momentum_vol_floor": 1e-8,
    "alpha.hmm_volatility.n_components": 3,
    "alpha.hmm_volatility.vol_window": 250,
    "alpha.hmm_volatility.vol_of_vol_window": 250,
    "alpha.hmm_volatility.covariance_type": "full",
    "alpha.hmm.walk_forward.refit_every_bars.5m": 19800,
    "alpha.hmm.walk_forward.initial_warmup_bars.5m": 39600,
    "alpha.hmm.walk_forward.refit_every_bars.15m": 6600,
    "alpha.hmm.walk_forward.initial_warmup_bars.15m": 13200,
    "alpha.hmm.walk_forward.refit_every_bars.1h": 1650,
    "alpha.hmm.walk_forward.initial_warmup_bars.1h": 3300,
    "alpha.hmm.walk_forward.refit_every_bars.1d": 252,
    "alpha.hmm.walk_forward.initial_warmup_bars.1d": 504,
}


def test_the_loader_returns_the_live_seeded_values():
    """The seed list covers every key, and the loader returns those values unchanged (live
    n_components is 5 and the volatility windows are 250/250, not the old defaults 3 and 20/60)."""
    assert set(_SEEDED_LIVE_VALUES) == set(HmmConfig.apr_keys())
    params = HmmConfig.from_values(_SEEDED_LIVE_VALUES.get)
    assert params.hmm_n_components == 5
    assert (params.hmm_volatility_vol_window, params.hmm_volatility_vol_of_vol_window) == (250, 250)
    assert dataclasses.asdict(params) == {
        f.name: _SEEDED_LIVE_VALUES[f.metadata["apr_key"]] for f in dataclasses.fields(HmmConfig)
    }


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


def test_ridge_and_vol_floor_seeds_are_the_literals_the_legacy_helpers_default_to():
    params = HmmConfig.from_values(SMALL_HMM_APR.get)
    assert params.hmm_covariance_ridge == _hmm._DEFAULT_COVARIANCE_RIDGE == 1e-6
    assert params.hmm_momentum_vol_floor == _hmm._DEFAULT_MOMENTUM_VOL_FLOOR == 1e-8
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
        return compute_regime_columns(bars["close"], bars["volume"], params, "1d", spec).columns

    want, got = run(base), run(dataclasses.replace(base, **change))
    assert any(
        not np.array_equal(want[name], got[name], equal_nan=True) for name in spec.numeric_outputs
    )
