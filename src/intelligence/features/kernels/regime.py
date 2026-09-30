"""Walk-forward HMM regime kernels (186-13, D-29, R-10).

Four kernels over bars only: a heavy walk-forward fit-and-decode per family (trend and
volatility) and a label kernel per family that turns the numeric label code into the text label.
The math and the per-family specs are in `_hmm.py`. The heavy kernels are path dependent: each
segment's model is fit on every observation from the series start, and refit boundaries count
from the first valid observation, so no finite memory reproduces a row (`feature_memory_bars`
raises for all 16 columns and the rebuild computes them from the series start).

`compute_regime_columns` is the one entry point that turns bars into a family's columns; the
registry kernels below, the regime writer and the rebuild all go through it, so their outputs
cannot diverge.

Input rules: `tf` must be one known timeframe repeated on every row. Rows are computed on the
finite prefix; a non-finite close or volume that runs to the end of the series yields NaN (None
for the label) from its first row, and a non-finite value followed by a finite row raises,
because real bars never contain one and hiding it would be a silent wrong answer.

Pure: no database, no ConfigService.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING

import numpy as np

from src.intelligence.features.contract.registry import Alignment, ExternalInput, Kernel
from src.intelligence.features.kernels import _hmm
from src.intelligence.features.kernels._hmm import (
    DEFAULT_ROLLING_BLOCK_ROWS,
    FAMILY_SPECS,
    FAMILY_TREND,
    FAMILY_VOLATILITY,
    N_NUMERIC_COLUMNS,
    HmmConfig,
    RegimeFamilySpec,
)

if TYPE_CHECKING:
    from src.intelligence.feature_factory import FeatureFactoryConfig

__all__ = [
    "EXTERNAL_INPUTS",
    "KERNELS",
    "compute_regime_columns",
]

EXTERNAL_INPUTS = (ExternalInput("tf", np.dtype(object), Alignment.CONSTANT_PER_SERIES),)

_HEAVY_REASON = (
    "expanding-window walk-forward HMM: every segment's model is fit on all observations from "
    "the series start and refit boundaries count from the first valid observation"
)
_LABEL_REASON = "reads a path-dependent upstream code"


def _known_tf(tf_values: np.ndarray) -> str:
    """The one timeframe of a series; ValueError for an empty, mixed or unknown value."""
    values = np.asarray(tf_values, dtype=object)
    if len(values) == 0:
        raise ValueError("regime kernels need a tf on every row; got no rows")
    first = values[0]
    if not all(v == first for v in values):
        raise ValueError("regime kernels need one tf per series; the tf input changes across rows")
    return _check_tf(first)


def _check_tf(tf: object) -> str:
    if tf not in _hmm.WALK_FORWARD_TIMEFRAMES:
        raise ValueError(
            f"regime kernels know timeframes {_hmm.WALK_FORWARD_TIMEFRAMES}, got {tf!r}"
        )
    return str(tf)


def _finite_prefix_rows(*arrays: np.ndarray) -> int:
    """Length of the leading run of rows where every array is finite."""
    bad = ~np.logical_and.reduce([np.isfinite(a) for a in arrays])
    if not bad.any():
        return len(bad)
    first = int(np.argmax(bad))
    if not bad[first:].all():
        raise ValueError(
            f"non-finite input at row {first} is followed by finite rows; regime kernels accept "
            "a non-finite tail only"
        )
    return first


def _compute_family(
    close: np.ndarray,
    volume: np.ndarray | None,
    params: HmmConfig,
    tf: str,
    spec: RegimeFamilySpec,
    block_rows: int | None,
) -> _hmm.FamilyResult:
    """The family's row-aligned walk-forward arrays over a series of bars (`volume` is read only
    by a family whose spec declares it as an input)."""
    close = np.asarray(close, dtype=float)
    n = len(close)
    if spec.needs_volume:
        volume = np.asarray(volume, dtype=float)
        prefix = _finite_prefix_rows(close, volume)
        volume = volume[:prefix]
    else:
        prefix = _finite_prefix_rows(close)
    obs, valid_start = spec.build_observations(close[:prefix], volume, params, block_rows)
    if len(obs) == 0:
        return _hmm.FamilyResult(
            np.full(n, np.nan),
            np.full(n, _hmm.STATUS_NO_MODEL),
            np.full((N_NUMERIC_COLUMNS, n), np.nan),
        )
    # obs row j is log-return row valid_start + j, which is bar row valid_start + j + 1
    return _hmm.walk_forward_family_arrays(obs, valid_start + 1, n, params, tf, spec)


def _label_table(spec: RegimeFamilySpec) -> np.ndarray:
    """Object array indexed by label code, with None at the extra last slot (unlabeled)."""
    table = np.empty(len(spec.labels) + 1, dtype=object)
    table[: len(spec.labels)] = spec.labels
    table[len(spec.labels)] = None
    return table


def _label_column(spec: RegimeFamilySpec, code: np.ndarray) -> np.ndarray:
    index = np.where(np.isnan(code), len(spec.labels), code).astype(int)
    return np.asarray(_label_table(spec)[index])


def _heavy_columns(spec: RegimeFamilySpec, result: _hmm.FamilyResult) -> dict[str, np.ndarray]:
    out = {spec.code_output: result.code, spec.status_output: result.status}
    out.update(zip(spec.numeric_outputs, result.numeric, strict=True))
    return out


def compute_regime_columns(
    close: np.ndarray,
    volume: np.ndarray | None,
    params: HmmConfig,
    tf: str,
    family: RegimeFamilySpec,
    block_rows: int | None = DEFAULT_ROLLING_BLOCK_ROWS,
) -> dict[str, np.ndarray]:
    """Every output column of `family` over one (symbol, tf) series of bars: the code, the
    segment status, the numeric columns and the text label column (None where unlabeled), keyed
    by name and identical to what the registry kernels compute for the same bars.

    `params` is the loaded `HmmConfig` (`HmmConfig.from_values(cfg.get_sync)`); `block_rows` is
    the caller's `infra.hmm.rolling_block_rows` and bounds memory without changing output.
    """
    result = _compute_family(close, volume, params, _check_tf(tf), family, block_rows)
    out = _heavy_columns(family, result)
    out[family.regime_column] = _label_column(family, result.code)
    return out


def _heavy_compute(spec: RegimeFamilySpec):
    def compute(inputs, config):
        volume = inputs["volume"] if spec.needs_volume else None
        result = _compute_family(
            inputs["close"],
            volume,
            HmmConfig.from_config(config),
            _known_tf(inputs["tf"]),
            spec,
            DEFAULT_ROLLING_BLOCK_ROWS,
        )
        return _heavy_columns(spec, result)

    compute.__name__ = f"_compute_{spec.family}_walk_forward"
    return compute


def _label_compute(spec: RegimeFamilySpec):
    def compute(inputs: Mapping[str, np.ndarray], config: FeatureFactoryConfig):
        code = np.asarray(inputs[spec.code_output], dtype=float)
        return {spec.regime_column: _label_column(spec, code)}

    compute.__name__ = f"_compute_{spec.family}_label"
    return compute


def _kernels_for(family: str) -> tuple[Kernel, Kernel]:
    spec = FAMILY_SPECS[family]
    heavy = Kernel(
        name=f"hmm_{family}_walk_forward",
        outputs=(spec.code_output, spec.status_output, *spec.numeric_outputs),
        inputs=spec.inputs,
        memory=lambda config: 0,
        compute=_heavy_compute(spec),
        path_dependent=True,
        path_dependent_reason=_HEAVY_REASON,
    )
    label = Kernel(
        name=f"hmm_{family}_label",
        outputs=(spec.regime_column,),
        inputs=(spec.code_output,),
        memory=lambda config: 0,
        compute=_label_compute(spec),
        dtype=np.dtype(object),
        path_dependent=True,
        path_dependent_reason=_LABEL_REASON,
    )
    return heavy, label


KERNELS = (*_kernels_for(FAMILY_TREND), *_kernels_for(FAMILY_VOLATILITY))
