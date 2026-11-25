"""Todo 674 (commit R1): a member's reach is the larger of the kernel's memory and the first row
its value can exist. A pass-through of an external builder declares memory 0 on purpose (D-26: the
writer feeds the builder the full source history, so the rebuild masks nothing), but its value
reaches back over the builder's window, which the kernel's `definition` states. The certificate
bound, warmup mask and E17 memory of a member read the reach, so a pass-through is no longer
admitted as memoryless."""

from __future__ import annotations

import pytest

from src.intelligence.features.contract.registry import default_registry, feature_memory_bars
from tests.unit.intelligence import kernel_parity_reference as ref

CONFIG = ref.build_config(ref.load_manifest()["synthetic_config"])

# column -> the first row its builder's value exists (rows after the first bar), written out here
# independently of the kernel modules
BUILDER_FIRST_ROW = {
    "max_daily_return": lambda c: c.max_daily_return_window,
    "max_drawdown": lambda c: c.max_drawdown_window - 1,
    "downside_deviation": lambda c: c.downside_deviation_window,
    "dividend_yield": lambda c: c.dividend_yield_window - 1,
    "market_residual_return": lambda c: c.factor_beta_window,
    "idiosyncratic_volatility": lambda c: c.factor_beta_window
    + c.idiosyncratic_volatility_window
    - 1,
    "market_residual_z": lambda c: c.factor_beta_window + c.market_residual_z_window - 1,
    "market_residual_lag1_acf": lambda c: c.factor_beta_window
    + c.market_residual_lag1_acf_window
    - 1,
    "residual_beta_stability": lambda c: c.factor_beta_window
    + c.residual_beta_stability_window
    - 1,
    "equity_beta_z": lambda c: c.factor_beta_window + c.factor_beta_zscore_window - 1,
    "rate_beta_z": lambda c: c.factor_beta_window + c.factor_beta_zscore_window - 1,
}


@pytest.mark.parametrize("column", sorted(BUILDER_FIRST_ROW))
def test_a_pass_through_member_reaches_back_over_its_builder_window(column: str) -> None:
    registry = default_registry()
    kernel = registry.by_output(column)
    assert registry.effective_memory_bars(kernel.name, CONFIG) == 0  # D-26: the rebuild masks none
    assert feature_memory_bars(column, CONFIG, registry) == BUILDER_FIRST_ROW[column](CONFIG)
    assert feature_memory_bars(column, CONFIG, registry) > 0


def test_every_other_non_path_dependent_column_keeps_its_memory_as_its_reach() -> None:
    """The reach differs from the memory only where a pass-through declares a definition: any
    other column moving would change a certificate bound or an E17 memory without a ruling."""
    registry = default_registry()
    moved = []
    for kernel in registry.kernels:
        for output in kernel.outputs:
            if output.startswith("_") or registry.is_path_dependent(output):
                continue
            memory = registry.effective_memory_bars(kernel.name, CONFIG)
            if feature_memory_bars(output, CONFIG, registry) != memory:
                moved.append(output)
    assert sorted(moved) == sorted(BUILDER_FIRST_ROW), sorted(set(moved) ^ set(BUILDER_FIRST_ROW))


def test_the_reach_never_falls_below_the_memory_and_takes_a_timeframe() -> None:
    registry = default_registry()
    for column in ("size_proxy", "momentum_z_mid", "equity_beta_z"):
        memory = registry.effective_memory_bars(registry.by_output(column).name, CONFIG)
        assert feature_memory_bars(column, CONFIG, registry, "1d") >= memory
        assert feature_memory_bars(column, CONFIG, registry) == feature_memory_bars(
            column, CONFIG, registry, "1d"
        )


# The reviewed list of pass-through outputs whose builder is path dependent (todo 674, lead ruling
# 2026-11-24): a pass-through is marked exactly when its builder grid kernel declares path_dependent.
MARKED = {
    "vix_z",
    "flight_quality",
    "yield_slope_z",
    "tip_tlt_ret_z",
    "hyg_lqd_ret_z",
    "sb_corr_fast",
    "sb_corr_slow",
    "sb_corr_z",
    "ctf_momentum",
    "ctf_vwap_align",
}
# pass-through kernel -> the grid kernel that builds its columns
BUILDER_OF = {
    "macro_pass_through": {
        **dict.fromkeys(MARKED - {"ctf_momentum", "ctf_vwap_align"}, "cross_asset_daily"),
        "equity_beta_z": "factor_beta_daily",
        "rate_beta_z": "factor_beta_daily",
    },
    "ctf_passthrough": dict.fromkeys(("ctf_momentum", "ctf_vwap_align"), "ctf_source"),
    "distribution_pass_through": dict.fromkeys(
        ("max_daily_return", "max_drawdown", "downside_deviation"), "distribution_daily"
    ),
    "market_residual_pass_through": dict.fromkeys(
        (
            "market_residual_return",
            "idiosyncratic_volatility",
            "market_residual_z",
            "market_residual_lag1_acf",
            "residual_beta_stability",
        ),
        "market_residual_daily",
    ),
    "dividend_yield_pass_through": {"dividend_yield": "dividend_yield_daily"},
}


def test_the_builder_path_dependent_marker_is_the_reviewed_list() -> None:
    registry = default_registry()
    marked = {o for k in registry.kernels for o in k.builder_path_dependent}
    assert marked == MARKED, sorted(marked ^ MARKED)
    assert all(registry.builder_path_dependent_reason(o) for o in MARKED)
    assert registry.builder_path_dependent_reason("max_daily_return") is None


def test_a_pass_through_is_marked_exactly_when_its_builder_is_path_dependent() -> None:
    registry = default_registry()
    for kernel_name, columns in BUILDER_OF.items():
        kernel = registry.by_name(kernel_name)
        assert set(columns) == set(kernel.outputs), kernel_name  # every output is accounted for
        assert not kernel.path_dependent  # D-26: the pass-through itself keeps memory 0
        for column, builder in columns.items():
            assert (column in kernel.builder_path_dependent) == registry.by_name(
                builder
            ).path_dependent, (column, builder)


def test_a_marker_naming_a_foreign_output_or_no_reason_is_refused() -> None:
    import dataclasses

    from src.intelligence.features.contract.registry import KernelRegistry, KernelRegistryError

    base = default_registry().by_name("ctf_passthrough")
    for bad in ({"not_an_output": "x"}, {"ctf_momentum": ""}):
        with pytest.raises(KernelRegistryError):
            KernelRegistry.from_kernels(
                [dataclasses.replace(base, builder_path_dependent=bad)],
                default_registry().external_inputs,
            )
    with pytest.raises(KernelRegistryError):  # a path-dependent kernel does not carry the marker
        KernelRegistry.from_kernels(
            [
                dataclasses.replace(
                    base,
                    path_dependent=True,
                    path_dependent_reason="r",
                    builder_path_dependent={"ctf_momentum": "r"},
                )
            ],
            default_registry().external_inputs,
        )
