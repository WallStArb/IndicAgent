"""kernel_source: registry and research kernels on an S0 panel at spec-pinned windows (184 B2b).

Design D5 (revision 3): research computes a kernel only for a (statistic, window) the stored
feature table does not carry; a member at a stored window reads the stored column (184-REVIEWS
row 10). Memory comes from the registry (`effective_memory_bars`, D-26, the one source). A
path-dependent (expanding) output has no finite memory and is refused (design D7 guard 5).

Per symbol, the kernels run on that symbol's present rows only (valid grid row with a finite
close), so a gap never enters a window as a value. The first `memory` present rows are NaN, and
a present row whose trailing `memory + 1` present rows span more than `memory + max_gap_rows`
grid rows is NaN (the gap rule). Output is float32 `[n, m]` on the panel grid, NaN where the
symbol did not trade.

The config is the FeatureFactoryConfig built from the source tf's verified provenance
(184-04 `feature_inputs.feature_config`): the config that computed any stored output a research
kernel consumes, and the one holding the stored windows the D5 rule checks against. This module
never builds a default config and never reads APR. `None` is accepted only when every kernel in
the requested outputs' upstream closure is config free and no requested output has a stored
equivalent whose window would need the config to check.

Pure: no database, no services, no `measure` import.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING

import numpy as np

from src.intelligence.features.contract.registry import (
    BAR_FIELDS,
    KernelRegistry,
    KernelRegistryError,
    compute_kernels,
    default_registry,
)
from src.intelligence.features.research_kernels.rolling import (
    CONFIG_FREE_KERNELS,
    FACTORIES,
    STORED_EQUIVALENTS,
    STORED_WINDOW_FIELD,
    family_of,
    window_of,
)
from src.intelligence.research.panel import Panel

if TYPE_CHECKING:
    from src.intelligence.feature_factory import FeatureFactoryConfig


class KernelSourceRefused(ValueError):
    """kernel_source will not compute this request (unknown, expanding, stored-window, config)."""


@dataclasses.dataclass(frozen=True)
class KernelSourceResult:
    values: dict[str, np.ndarray]  # output -> float32 [n, m]
    memory_bars: dict[str, int]  # output -> declared memory (registry)
    gap_masked: dict[str, int]  # output -> rows NaN by the gap rule, all symbols
    warmup_masked: dict[str, int]  # output -> rows NaN by the warmup rule, all symbols


def kernel_registry(
    windows: Mapping[str, int], config: FeatureFactoryConfig | None
) -> KernelRegistry:
    """The default registry plus one research kernel per (family, pinned window), so a research
    kernel may consume a stored output. `windows` maps a research family to its window; windows
    never come from the config. `config` is unused here and kept for one calling convention."""
    del config
    research = []
    for family, window in sorted(windows.items()):
        factory = FACTORIES.get(family)
        if factory is None:
            raise KernelSourceRefused(f"unknown research kernel family {family!r}")
        research.append(factory(window))
    default = default_registry()
    return KernelRegistry.from_kernels(default.kernels + tuple(research), default.external_inputs)


def _closure_needs_config(registry: KernelRegistry, outputs: Sequence[str]) -> list[str]:
    """Kernels in the upstream closure of `outputs` that read the config."""
    return [
        kernel.name
        for kernel in registry.topological_order(tuple(outputs))
        if family_of(kernel.name) not in CONFIG_FREE_KERNELS
    ]


def _resolve(
    registry: KernelRegistry, outputs: Sequence[str], config: FeatureFactoryConfig | None
) -> None:
    for output in outputs:
        try:
            path_dependent = registry.is_path_dependent(output)
        except KernelRegistryError as error:
            raise KernelSourceRefused(str(error)) from None
        if path_dependent:
            raise KernelSourceRefused(
                f"{output!r} is path dependent (expanding): no finite memory, refused by design "
                "D7 guard 5"
            )
    if config is None:
        needs = _closure_needs_config(registry, outputs)
        if needs:
            raise KernelSourceRefused(
                f"kernel_source needs the provenance config (B1f): {needs} read it"
            )


def _check_stored_window(output: str, config: FeatureFactoryConfig | None) -> None:
    """184-REVIEWS row 10: a research kernel only at a window no stored column carries."""
    family = family_of(output)
    if family is None or not STORED_EQUIVALENTS[family]:
        return
    if config is None:
        raise KernelSourceRefused(
            f"{output!r}: checking it against the stored windows of {STORED_EQUIVALENTS[family]} "
            "needs the provenance config (B1f, 184-REVIEWS row 10)"
        )
    window = window_of(output)
    for column in STORED_EQUIVALENTS[family]:
        stored = int(getattr(config, STORED_WINDOW_FIELD[column]))
        if window == stored:
            raise KernelSourceRefused(
                f"{output!r} duplicates stored column {column!r} (window {stored}); read the "
                "stored column (184-REVIEWS row 10)"
            )


def kernel_member_memory_bars(
    output: str, windows: Mapping[str, int], config: FeatureFactoryConfig | None
) -> int:
    """Declared memory in bars of `output` on the combined registry (D-26)."""
    registry = kernel_registry(windows, config)
    _resolve(registry, (output,), config)
    return registry.effective_memory_bars(registry.by_output(output).name, config)  # type: ignore[arg-type]


def _gap_mask(grid_index: np.ndarray, memory: int, max_gap_rows: int) -> np.ndarray:
    """True at present row k (k >= memory) whose trailing memory + 1 present rows span more than
    memory + max_gap_rows grid rows."""
    mask = np.zeros(len(grid_index), dtype=bool)
    if memory == 0 or len(grid_index) <= memory:
        return mask
    span = grid_index[memory:] - grid_index[:-memory]
    mask[memory:] = span > memory + max_gap_rows
    return mask


def kernel_source(
    panel: Panel,
    outputs: Sequence[str],
    windows: Mapping[str, int],
    config: FeatureFactoryConfig | None,
    *,
    max_gap_rows: int,
    high: np.ndarray | None = None,
    low: np.ndarray | None = None,
    volume_basis: np.ndarray | None = None,
) -> KernelSourceResult:
    """Run `outputs` per symbol over its present rows; float32 [n, m] per output on the grid."""
    if isinstance(max_gap_rows, bool) or not isinstance(max_gap_rows, (int, np.integer)):
        raise KernelSourceRefused(f"max_gap_rows must be an int, got {max_gap_rows!r}")
    if max_gap_rows < 0:
        raise KernelSourceRefused(f"max_gap_rows must be >= 0, got {max_gap_rows}")
    outputs = tuple(outputs)
    if not outputs or len(set(outputs)) != len(outputs):
        raise KernelSourceRefused(f"outputs must be non-empty and distinct, got {outputs!r}")
    registry = kernel_registry(windows, config)
    _resolve(registry, outputs, config)
    for output in outputs:
        _check_stored_window(output, config)
    memory = {
        o: registry.effective_memory_bars(registry.by_output(o).name, config)  # type: ignore[arg-type]
        for o in outputs
    }

    n, m = panel.close.shape
    fields: dict[str, np.ndarray | None] = {
        "open": panel.open,
        "high": high,
        "low": low,
        "close": panel.close,
        "volume": panel.volume,
        # The panel carries no vendor provenance (todo 555), so a kernel that needs the volume
        # basis is refused unless the caller supplies it: a constant would hide the seam.
        "volume_basis": volume_basis,
    }
    for name in ("high", "low", "volume_basis"):
        if fields[name] is not None and np.shape(fields[name]) != (n, m):
            raise KernelSourceRefused(
                f"{name} has shape {np.shape(fields[name])}, expected {(n, m)}"
            )
    needed = {
        name
        for kernel in registry.topological_order(outputs)
        for name in kernel.inputs
        if name in BAR_FIELDS
    }
    missing = sorted(name for name in needed if fields.get(name, ...) is None)
    if missing:
        raise KernelSourceRefused(f"{outputs!r} need bar fields {missing}, which were not supplied")

    ts = np.asarray(panel.timestamps).astype("datetime64[ns]").astype(np.int64)
    values = {o: np.full((n, m), np.nan, dtype=np.float32) for o in outputs}
    gap_masked = dict.fromkeys(outputs, 0)
    warmup_masked = dict.fromkeys(outputs, 0)
    close = np.asarray(panel.close, dtype=float)
    valid = np.asarray(panel.valid, dtype=bool)
    for j in range(m):
        rows = np.flatnonzero(valid & np.isfinite(close[:, j]))
        if rows.size == 0:
            continue
        inputs = {"ts": ts[rows]}
        for name, array in fields.items():
            if array is not None:
                inputs[name] = np.asarray(array, dtype=float)[rows, j]
        try:
            computed = compute_kernels(registry, inputs, config, outputs=outputs)  # type: ignore[arg-type]
        except KernelRegistryError as error:
            raise KernelSourceRefused(str(error)) from None
        for output in outputs:
            column = np.asarray(computed[output]).astype(np.float32)
            warm = min(memory[output], rows.size)
            column[:warm] = np.nan
            warmup_masked[output] += warm
            gap = _gap_mask(rows, memory[output], int(max_gap_rows))
            column[gap] = np.nan
            gap_masked[output] += int(gap.sum())
            values[output][rows, j] = column
    return KernelSourceResult(
        values=values, memory_bars=memory, gap_masked=gap_masked, warmup_masked=warmup_masked
    )
