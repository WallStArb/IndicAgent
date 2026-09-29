"""Causality probe and memory check over the pure kernel entry point (D-27).

The probe is truncation: for each probed row t, cut every declared input to rows [: t + 1]
along axis 0, recompute, and require rows 0..t of the truncated output to equal the full
output's rows 0..t in the kernel's dtype (float32 by default). Comparing all t + 1 rows, not
only row t, is what catches full-sample normalization. For cross-sectional kernels the
`[row, symbol]` arrays are cut on axis 0, which truncates every symbol at once.

This does not wrap `research/guards.causality_probe_array`: that function replaces future
rows with NaN or rescaled values instead of truncating, so it misses kernels that depend on
series length or on how many rows exist, and importing the research package would put
research-lane files into the rebuild's import closure, where the no-edit rule would then
bind the research lane. The research S3 guard adopts this probe in the research lane (D-27),
not here.

Pure: no database, no randomness; rows are a caller-stated array.
"""

from __future__ import annotations

from collections.abc import Mapping

import numpy as np

from src.intelligence.features.registry import Kernel, KernelRegistry


class CausalityViolation(AssertionError):
    """A kernel's output at a past row changed when future rows were removed."""


class MemoryViolation(AssertionError):
    """A kernel's output at row t needs more history than its declared memory."""


def _run(kernel: Kernel, inputs: Mapping[str, np.ndarray], config: object, lo: int, hi: int):
    cut = {name: np.asarray(inputs[name])[lo:hi] for name in kernel.inputs}
    out = kernel.compute(cut, config)  # type: ignore[arg-type]
    missing = [o for o in kernel.outputs if o not in out]
    if missing:
        raise CausalityViolation(f"kernel {kernel.name!r} did not return outputs {missing}")
    result = {}
    for name in kernel.outputs:
        arr = np.asarray(out[name]).astype(kernel.dtype)
        if arr.shape[0] != hi - lo:
            raise CausalityViolation(
                f"kernel {kernel.name!r} output {name!r} has {arr.shape[0]} rows for "
                f"{hi - lo} input rows"
            )
        result[name] = arr
    return result


def _first_difference(a: np.ndarray, b: np.ndarray, ulp: int) -> tuple[int, object, object] | None:
    """First differing row (axis 0) between equal-shaped arrays, or None."""
    nan_a, nan_b = np.isnan(a), np.isnan(b)
    bad = nan_a != nan_b
    both = ~nan_a & ~nan_b
    if ulp == 0:
        bad |= both & (a != b)
    else:
        a64, b64 = a.astype(np.float64), b.astype(np.float64)
        with np.errstate(invalid="ignore"):
            unit = np.spacing(np.maximum(np.abs(a), np.abs(b)).astype(np.float32)).astype(
                np.float64
            )
            close = np.abs(a64 - b64) <= ulp * unit
        bad |= both & ~close & (a != b)
    if not bad.any():
        return None
    idx = np.argwhere(bad)[0]
    return int(idx[0]), a[tuple(idx)], b[tuple(idx)]


def causality_probe(
    kernel: Kernel,
    inputs: Mapping[str, np.ndarray],
    config: object,
    rows: np.ndarray,
    *,
    ulp: int = 0,
) -> None:
    n = len(np.asarray(inputs[kernel.inputs[0]])) if kernel.inputs else 0
    full = _run(kernel, inputs, config, 0, n)
    for t in (int(r) for r in np.sort(np.asarray(rows))):
        truncated = _run(kernel, inputs, config, 0, t + 1)
        for name in kernel.outputs:
            diff = _first_difference(full[name][: t + 1], truncated[name], ulp)
            if diff is not None:
                row, full_value, cut_value = diff
                raise CausalityViolation(
                    f"kernel {kernel.name!r} output {name!r}: truncating at row {t} changed "
                    f"row {row} (full={full_value!r}, truncated={cut_value!r}, ulp={ulp})"
                )


def memory_check(
    kernel: Kernel,
    inputs: Mapping[str, np.ndarray],
    config: object,
    rows: np.ndarray,
    *,
    ulp: int = 0,
) -> int:
    memory = int(kernel.memory(config))  # type: ignore[arg-type]
    n = len(np.asarray(inputs[kernel.inputs[0]])) if kernel.inputs else 0
    full = _run(kernel, inputs, config, 0, n)
    for t in (int(r) for r in np.sort(np.asarray(rows))):
        if t < memory:
            continue
        window = _run(kernel, inputs, config, t - memory, t + 1)
        for name in kernel.outputs:
            diff = _first_difference(full[name][t : t + 1], window[name][-1:], ulp)
            if diff is not None:
                raise MemoryViolation(
                    f"kernel {kernel.name!r} output {name!r} at row {t} needs more than the "
                    f"declared memory {memory} (full={diff[1]!r}, windowed={diff[2]!r}, "
                    f"ulp={ulp})"
                )
    return memory


def probe_registry(
    registry: KernelRegistry,
    inputs: Mapping[str, np.ndarray],
    config: object,
    rows: np.ndarray,
    *,
    ulp: int = 0,
) -> dict[str, int]:
    """Run both checks over every kernel in topological order; return name -> memory."""
    available = dict(inputs)
    checked: dict[str, int] = {}
    for kernel in registry.topological_order():
        causality_probe(kernel, available, config, rows, ulp=ulp)
        checked[kernel.name] = memory_check(kernel, available, config, rows, ulp=ulp)
        n = len(np.asarray(available[kernel.inputs[0]])) if kernel.inputs else 0
        available.update(_run(kernel, available, config, 0, n))
    return checked
