"""Unit tests: EnsembleICConfig.from_apr binding + pickle safety.

No DB, no Kafka. Pure Python / dataclasses.
"""

from __future__ import annotations

import dataclasses
import pickle
import sys
from pathlib import Path

_project_root = Path(__file__).parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from services.ensemble_ic_engine import EnsembleICConfig

_FULL_CFG_DICT = {
    # Shared ICEngineConfig-style keys
    "alpha.ic.fdr_alpha": "0.05",
    "alpha.ic.walk_forward_folds": "3",
    "alpha.ic.sharpe_window_size": "2000",
    "alpha.ic.sharpe_window_size_subsampled": "100",
    "alpha.ic.sharpe_min_windows": "30",
    "alpha.ic.subsample_min_stride": "5",
    "alpha.ic.min_reliable_n": "100",
    "alpha.ic.hac_max_lag": "3",
    # Todo 146: per-tf lookahead grid (replaces the old flat alpha.ic.lookahead.{scale} keys)
    "alpha.ic.lookahead.5m.fast": "1",
    "alpha.ic.lookahead.5m.mid": "6",
    "alpha.ic.lookahead.5m.slow": "12",
    "alpha.ic.lookahead.5m.extended": "39",
    "alpha.ic.lookahead.15m.fast": "1",
    "alpha.ic.lookahead.15m.mid": "2",
    "alpha.ic.lookahead.15m.slow": "5",
    "alpha.ic.lookahead.15m.extended": "10",
    "alpha.ic.lookahead.1h.fast": "1",
    "alpha.ic.lookahead.1h.mid": "2",
    "alpha.ic.lookahead.1h.slow": "20",
    "alpha.ic.lookahead.1h.extended": "60",
    "alpha.ic.lookahead.1d.fast": "1",
    "alpha.ic.lookahead.1d.mid": "2",
    "alpha.ic.lookahead.1d.slow": "5",
    "alpha.ic.lookahead.1d.extended": "10",
    "infra.ensemble_ic_engine.workers": "12",
    # EnsembleIC-specific keys (migration 195)
    "alpha.ensemble_ic.decay_threshold": "0.1",
    "alpha.ensemble_ic.min_qualifying_fraction": "0.60",
    "alpha.ensemble_ic.wf_stability_ratio": "3.0",
    "alpha.ensemble_ic.gate_lookahead": "fast",
    "alpha.ensemble_ic.wf_stability_metric": "ic_ratio",
    "alpha.ensemble_ic.min_obs_per_regime": "3000",
}


def test_from_apr_binds_all_keys():
    """EnsembleICConfig.from_apr binds every alpha.ensemble_ic.* and shared key."""
    cfg = EnsembleICConfig.from_apr(_FULL_CFG_DICT)

    assert cfg.decay_threshold == 0.1
    assert cfg.min_qualifying_fraction == 0.60
    assert cfg.wf_stability_ratio == 3.0
    assert cfg.gate_lookahead == "fast"
    assert cfg.wf_stability_metric == "ic_ratio"
    assert cfg.min_obs_per_regime == 3000
    assert cfg.n_workers == 12
    assert cfg.fdr_alpha == 0.05
    assert cfg.walk_forward_folds == 3
    assert cfg.sharpe_window_size == 2000
    assert cfg.sharpe_window_size_subsampled == 100
    assert cfg.sharpe_min_windows == 30
    assert cfg.subsample_min_stride == 5
    assert cfg.min_reliable_n == 100
    assert cfg.hac_max_lag == 3
    assert cfg.lookahead_fast == {"5m": 1, "15m": 1, "1h": 1, "1d": 1}
    assert cfg.lookahead_mid == {"5m": 6, "15m": 2, "1h": 2, "1d": 2}
    assert cfg.lookahead_slow == {"5m": 12, "15m": 5, "1h": 20, "1d": 5}
    assert cfg.lookahead_extended == {"5m": 39, "15m": 10, "1h": 60, "1d": 10}
    assert cfg.lookaheads_for("5m") == {"fast": 1, "mid": 6, "slow": 12, "extended": 39}
    assert cfg.active_scales_for("5m") == ("fast", "mid", "slow", "extended")
    assert cfg.active_scales_for("1h") == ("fast", "mid", "slow", "extended")


def test_from_apr_applies_defaults_when_keys_missing():
    """Missing keys fall back to documented APR defaults, not a KeyError."""
    cfg = EnsembleICConfig.from_apr({})

    assert cfg.decay_threshold == 0.05  # todo 096: rescaled 0.1 -> 0.05, migration 230
    assert cfg.min_qualifying_fraction == 0.60
    assert cfg.wf_stability_ratio == 3.0
    assert cfg.gate_lookahead == "fast"
    assert cfg.wf_stability_metric == "ic_ratio"
    assert cfg.sharpe_window_size_subsampled == 100
    assert cfg.active_scales_for("1h") == ("fast", "mid", "slow", "extended")
    assert cfg.active_scales_for("5m") == ("fast", "mid", "slow", "extended")


def test_ensemble_ic_config_active_scales_for_returns_canonical_tuple():
    """Todo (2026-07-30 per-tf active-scale-set design): active_scales_for resolves
    the per-tf active-scale tuple from APR fallback defaults when unset -- mirrors
    ICEngineConfig.active_scales_for's identical semantics on the independent
    EnsembleICConfig frozen dataclass. All four tfs currently resolve to all four
    scales (migration 272 reverted 1h's exclusion once its cause -- the same-session
    completeness gate -- was removed); this test asserts the resolver mechanism
    works, not that any tf is currently restricted."""
    cfg = EnsembleICConfig.from_apr({})
    assert cfg.active_scales_for("1h") == ("fast", "mid", "slow", "extended")
    assert cfg.active_scales_for("5m") == ("fast", "mid", "slow", "extended")


def test_config_is_frozen_dataclass():
    """EnsembleICConfig must be a frozen dataclass (required for worker pickling safety)."""
    assert dataclasses.is_dataclass(EnsembleICConfig)
    assert EnsembleICConfig.__dataclass_params__.frozen is True

    cfg = EnsembleICConfig.from_apr(_FULL_CFG_DICT)
    try:
        cfg.decay_threshold = 0.99  # type: ignore[misc]
        raised = False
    except dataclasses.FrozenInstanceError:
        raised = True
    assert raised, "EnsembleICConfig must reject attribute mutation (frozen=True)"


def test_config_is_pickle_safe():
    """EnsembleICConfig must round-trip through pickle (ProcessPoolExecutor requirement)."""
    cfg = EnsembleICConfig.from_apr(_FULL_CFG_DICT)
    restored = pickle.loads(pickle.dumps(cfg))
    assert restored == cfg
