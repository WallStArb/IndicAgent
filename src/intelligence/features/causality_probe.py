"""Causality probe and memory check over the pure kernel entry point (D-27).

The probe is truncation: for each probed row t, cut every declared input to rows [: t + 1]
along axis 0, recompute, and require rows 0..t of the truncated output to equal the full
output's rows 0..t in the kernel's dtype (float32 by default). Comparing all t + 1 rows, not
only row t, is what catches full-sample normalization. Arrays are cut on axis 0, so a
`[row, symbol]` array truncates every symbol at once.

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


def _n_rows(kernel: Kernel, inputs: Mapping[str, np.ndarray]) -> int:
    return len(np.asarray(inputs[kernel.inputs[0]])) if kernel.inputs else 0


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


def _first_difference(
    a: np.ndarray, b: np.ndarray, ulp: int, atol: float = 0.0
) -> tuple[int, object, object] | None:
    """First differing row (axis 0) between equal-shaped arrays, or None.

    `atol` is an absolute tolerance (memory_check only; the causality probe stays exact).
    """
    nan_a, nan_b = np.isnan(a), np.isnan(b)
    bad = nan_a != nan_b
    both = ~nan_a & ~nan_b
    if atol > 0.0:
        with np.errstate(invalid="ignore"):
            bad |= both & ~(np.abs(a.astype(np.float64) - b.astype(np.float64)) <= atol)
    elif ulp == 0:
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
    n = _n_rows(kernel, inputs)
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
    atol = float(kernel.memory_atol)
    n = _n_rows(kernel, inputs)
    full = _run(kernel, inputs, config, 0, n)
    for t in (int(r) for r in np.sort(np.asarray(rows))):
        if t < memory:
            continue
        window = _run(kernel, inputs, config, t - memory, t + 1)
        for name in kernel.outputs:
            diff = _first_difference(full[name][t : t + 1], window[name][-1:], ulp, atol)
            if diff is not None:
                raise MemoryViolation(
                    f"kernel {kernel.name!r} output {name!r} at row {t} needs more than the "
                    f"declared memory {memory} (full={diff[1]!r}, windowed={diff[2]!r}, "
                    f"ulp={ulp}, atol={atol})"
                )
    return memory


STATUS_OK = "ok"
STATUS_PATH_DEPENDENT = "path_dependent_skipped_memory"
STATUS_ACAUSAL_CONTROL = "acausal_control_detected"


def probe_registry(
    registry: KernelRegistry,
    inputs: Mapping[str, np.ndarray],
    config: object,
    rows: np.ndarray,
    *,
    ulp: int = 0,
) -> dict[str, str]:
    """Run the checks over every kernel in topological order; return name -> status.

    `inputs` carries the bar fields and every external input the registry declares. A causal
    kernel gets the causality probe and the memory check (`ok`). A path-dependent kernel gets
    the causality probe only (`path_dependent_skipped_memory`): no finite memory reproduces it.
    An acausal control must fail the causality probe (`acausal_control_detected`); a control
    the probe does not catch raises CausalityViolation, because that means the probe is blind.
    Downstream kernels read upstream outputs at the dtype they were computed in.
    """
    available = dict(inputs)
    statuses: dict[str, str] = {}
    for kernel in registry.topological_order():
        if kernel.acausal_control:
            try:
                causality_probe(kernel, available, config, rows, ulp=ulp)
            except CausalityViolation:
                statuses[kernel.name] = STATUS_ACAUSAL_CONTROL
            else:
                raise CausalityViolation(
                    f"acausal control {kernel.name!r} passed the causality probe: the probe "
                    "cannot detect lookahead"
                )
        else:
            causality_probe(kernel, available, config, rows, ulp=ulp)
            if kernel.path_dependent:
                statuses[kernel.name] = STATUS_PATH_DEPENDENT
            else:
                memory_check(kernel, available, config, rows, ulp=ulp)
                statuses[kernel.name] = STATUS_OK
        native = kernel.compute({name: available[name] for name in kernel.inputs}, config)  # type: ignore[arg-type]
        available.update({name: np.asarray(native[name]) for name in kernel.outputs})
    return statuses
