"""Inputs derived from the bar fields once per call by the registry layer, not by each kernel.

A kernel that declares a derived input name (`ts_dt`) reads it from `inputs` like any other
array, so kernels stay pure functions of their arguments with no cross-call state. A derived
input is row-aligned (axis 0 has one entry per bar) and row-local: entry i depends only on
bar-field row i, so truncating it with the bar fields (the causality probe) is exact.

Pure: no database, no global state.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta

import numpy as np

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)

TS_DATETIME = "ts_dt"


def ts_ns_to_datetimes(ts: np.ndarray) -> list[datetime]:
    """int64 UTC nanoseconds to aware datetimes by integer arithmetic (never float seconds)."""
    return [_EPOCH + timedelta(microseconds=int(ns) // 1000) for ns in ts]


def _ts_datetimes(inputs: Mapping[str, np.ndarray]) -> np.ndarray:
    """Object array of the UTC datetime of every row's `ts`.

    Each distinct timestamp is converted once (ts_ns_to_datetimes) and scattered, so rows that
    share a timestamp share one datetime object.
    """
    unique, inverse = np.unique(inputs["ts"], return_inverse=True)
    converted = np.empty(len(unique), dtype=object)
    converted[:] = ts_ns_to_datetimes(unique)
    return converted[inverse.reshape(-1)]


# name -> (bar fields it is built from, builder)
DERIVED_INPUTS: dict[
    str, tuple[tuple[str, ...], Callable[[Mapping[str, np.ndarray]], np.ndarray]]
] = {
    TS_DATETIME: (("ts",), _ts_datetimes),
}


def build_derived_inputs(
    names: set[str] | frozenset[str], inputs: Mapping[str, np.ndarray]
) -> dict[str, np.ndarray]:
    """Build each requested derived input from `inputs`."""
    return {name: DERIVED_INPUTS[name][1](inputs) for name in sorted(names)}


def with_derived_inputs(inputs: Mapping[str, np.ndarray]) -> dict[str, np.ndarray]:
    """`inputs` plus every derived input whose bar fields are all present (a caller that runs
    kernels directly, such as the causality probe, uses this instead of naming them)."""
    extra = {
        name: builder(inputs)
        for name, (needs, builder) in DERIVED_INPUTS.items()
        if all(field in inputs for field in needs)
    }
    return {**inputs, **extra}
