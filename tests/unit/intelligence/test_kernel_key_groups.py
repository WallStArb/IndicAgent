"""Key-group specs and declared-memory accessors of the VP/SR and SMC kernels (186-15 review)."""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from src.intelligence.features.kernels import smc, vp_sr
from src.intelligence.features.kernels._primitives import (
    KeyGroup,
    none_mask_name,
    nullable_keys,
    row_dict_columns,
    row_dict_outputs,
    window_start,
)


def test_nullable_keys_are_the_fallback_none_entries():
    assert nullable_keys({"a": 0.0, "b": None, "c": None}) == {"b", "c"}


def test_group_outputs_are_exactly_the_columns_row_dict_columns_returns():
    group = KeyGroup.from_fallback({"a": 0.0, "b": None, "c": 1.0}, {"c": "_c"})
    columns = group.columns(3, lambda i: {"a": 1.0, "b": None, "c": 2.0})
    assert set(columns) == set(group.outputs) == {"a", "b", "_c", none_mask_name("b")}
    assert group.public_keys == ("a", "b")
    assert row_dict_outputs(group.keys, group.nullable, group.names) == group.outputs
    assert set(columns) == set(
        row_dict_columns(
            3, group.keys, group.nullable, lambda i: {"a": 1.0, "b": None, "c": 2.0}, group.names
        )
    )


def test_window_start_is_the_causal_lookback_window():
    assert [window_start(i, 3) for i in range(5)] == [0, 0, 0, 1, 2]


@pytest.mark.parametrize("kernel_name", [k.name for k in smc.KERNELS if k.name != "amd_cycle"])
def test_smc_stateless_memory_reads_the_lookback_the_compute_reads(kernel_name):
    lookbacks = {
        "order_blocks": smc._OB_LOOKBACK,
        "fair_value_gaps": smc._FVG_LOOKBACK,
        "liquidity_sweeps": smc._SWEEP_LOOKBACK,
        "liquidity_pools": smc._POOL_LOOKBACK,
        "supply_demand_zones": smc._ZONE_LOOKBACK,
        "bos_choch": smc._BOS_LOOKBACK,
    }
    kernel = next(k for k in smc.KERNELS if k.name == kernel_name)
    config = SimpleNamespace(
        **{
            "smc_order_blocks_lookback": 11,
            "smc_fvg_lookback": 12,
            "smc_liquidity_sweeps_lookback": 13,
            "smc_liquidity_pools_lookback": 14,
            "smc_zones_lookback": 15,
            "smc_bos_choch_lookback": 16,
        }
    )
    assert kernel.memory(config) == lookbacks[kernel_name](config) - 1


def test_sr_memory_follows_the_default_lookback_the_compute_uses(monkeypatch):
    kernel = next(k for k in vp_sr.KERNELS if k.name == "support_resistance")
    config = SimpleNamespace(sr_lookback_by_tf={"5m": 50})
    assert vp_sr._sr_lookback(config, "5m") == 50
    assert vp_sr._sr_lookback(config, "1h") == vp_sr._SR_DEFAULT_LOOKBACK
    assert kernel.memory(config) == vp_sr._SR_DEFAULT_LOOKBACK - 1
    monkeypatch.setattr(vp_sr, "_SR_DEFAULT_LOOKBACK", 200)
    assert vp_sr._sr_lookback(config, "1h") == 200
    assert kernel.memory(config) == 199
    assert kernel.memory(SimpleNamespace(sr_lookback_by_tf={"5m": 300})) == 299


def test_none_free_groups_stay_non_nullable():
    for group in (smc.OB, smc.FVG, smc.SWEEP, smc.POOL, smc.ZONE, smc.BOS, smc.AMD, vp_sr.SR):
        assert group.nullable == frozenset()
    assert len(np.unique(vp_sr.SWING_STRUCTURE.keys)) == len(vp_sr.SWING_STRUCTURE.keys)
