"""Walk-forward HMM regime kernels (186-13, D-29, R-10).

Four kernels over bars only: a heavy walk-forward fit-and-decode per family (trend and
volatility) and a label kernel per family that turns the numeric label code into the text label.
The math is in `_hmm.py`. The heavy kernels are path dependent: each segment's model is fit on
every observation from the series start, and refit boundaries count from the first valid
observation, so no finite memory reproduces a row (`feature_memory_bars` raises for all 16
columns and the rebuild computes them from the series start).

Input rules: `tf` must be one known timeframe repeated on every row. Rows are computed on the
finite prefix; a non-finite close or volume that runs to the end of the series yields NaN (None
for the label) from its first row, and a non-finite value followed by a finite row raises,
because real bars never contain one and hiding it would be a silent wrong answer.

Pure: no database, no ConfigService.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np

from src.intelligence.features.contract.registry import Alignment, ExternalInput, Kernel
from src.intelligence.features.feature_vector_persistence import (
    REGIME_VOLATILITY_WRITER_OWNED_COLUMN_NAMES,
    REGIME_WRITER_OWNED_COLUMN_NAMES,
)
from src.intelligence.features.kernels import _hmm
from src.intelligence.features.kernels._hmm import (
    FAMILY_TREND,
    FAMILY_VOLATILITY,
    N_NUMERIC_COLUMNS,
    TREND_LABELS,
    VOLATILITY_LABELS,
    hmm_config_fields_from_values,
)

if TYPE_CHECKING:
    from src.intelligence.feature_factory import FeatureFactoryConfig

__all__ = [
    "EXTERNAL_INPUTS",
    "FAMILY_KERNELS",
    "KERNELS",
    "RegimeFamilySpec",
    "hmm_config_fields_from_values",
]

EXTERNAL_INPUTS = (ExternalInput("tf", np.dtype(object), Alignment.CONSTANT_PER_SERIES),)

_HEAVY_REASON = (
    "expanding-window walk-forward HMM: every segment's model is fit on all observations from "
    "the series start and refit boundaries count from the first valid observation"
)
_LABEL_REASON = "reads a path-dependent upstream code"


@dataclass(frozen=True)
class RegimeFamilySpec:
    """Names of one family's kernel outputs (the capture script and the writer read these)."""

    family: str
    label_output: str
    code_output: str
    status_output: str
    numeric_outputs: tuple[str, ...]
    labels: tuple[str, ...]


FAMILY_KERNELS: dict[str, RegimeFamilySpec] = {
    FAMILY_TREND: RegimeFamilySpec(
        family=FAMILY_TREND,
        label_output=REGIME_WRITER_OWNED_COLUMN_NAMES[0],
        code_output="_hmm_trend_code",
        status_output="_hmm_trend_segment_status",
        numeric_outputs=tuple(REGIME_WRITER_OWNED_COLUMN_NAMES[1:]),
        labels=TREND_LABELS,
    ),
    FAMILY_VOLATILITY: RegimeFamilySpec(
        family=FAMILY_VOLATILITY,
        label_output=REGIME_VOLATILITY_WRITER_OWNED_COLUMN_NAMES[0],
        code_output="_hmm_volatility_code",
        status_output="_hmm_volatility_segment_status",
        numeric_outputs=tuple(REGIME_VOLATILITY_WRITER_OWNED_COLUMN_NAMES[1:]),
        labels=VOLATILITY_LABELS,
    ),
}
assert all(len(f.numeric_outputs) == N_NUMERIC_COLUMNS for f in FAMILY_KERNELS.values())


def _known_tf(tf_values: np.ndarray) -> str:
    """The one timeframe of a series; ValueError for an empty, mixed or unknown value."""
    values = np.asarray(tf_values, dtype=object)
    if len(values) == 0:
        raise ValueError("regime kernels need a tf on every row; got no rows")
    first = values[0]
    if not all(v == first for v in values):
        raise ValueError("regime kernels need one tf per series; the tf input changes across rows")
    if first not in _hmm.WALK_FORWARD_TIMEFRAMES:
        raise ValueError(
            f"regime kernels know timeframes {_hmm.WALK_FORWARD_TIMEFRAMES}, got {first!r}"
        )
    return str(first)


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


def _compute_family(inputs: Mapping[str, np.ndarray], config: FeatureFactoryConfig, family: str):
    close = np.asarray(inputs["close"], dtype=float)
    n = len(close)
    tf = _known_tf(inputs["tf"])
    if family == FAMILY_TREND:
        volume = np.asarray(inputs["volume"], dtype=float)
        prefix = _finite_prefix_rows(close, volume)
    else:
        prefix = _finite_prefix_rows(close)
    rows = list(range(prefix))
    if family == FAMILY_TREND:
        obs, valid_rows = _hmm._build_obs_matrix(
            rows,
            close[:prefix],
            volume[:prefix],
            vol_window=config.hmm_vol_window,
            momentum_window=config.hmm_momentum_window,
            vol_of_vol_window=config.hmm_vol_of_vol_window,
            block_rows=config.hmm_rolling_block_rows,
        )
    else:
        obs, valid_rows = _hmm._build_obs_matrix_volatility(
            rows,
            close[:prefix],
            vol_window=config.hmm_volatility_vol_window,
            vol_of_vol_window=config.hmm_volatility_vol_of_vol_window,
            block_rows=config.hmm_rolling_block_rows,
        )
    if not valid_rows:
        return _hmm.FamilyResult(
            np.full(n, np.nan),
            np.full(n, _hmm.STATUS_NO_MODEL),
            np.full((N_NUMERIC_COLUMNS, n), np.nan),
        )
    return _hmm.walk_forward_family_arrays(obs, valid_rows[0], n, config, tf, family)


def _heavy_compute(family: str):
    spec = FAMILY_KERNELS[family]

    def compute(inputs, config):
        arrays = _compute_family(inputs, config, family)
        out = {spec.code_output: arrays.code, spec.status_output: arrays.status}
        out.update(zip(spec.numeric_outputs, arrays.numeric, strict=True))
        return out

    compute.__name__ = f"_compute_{family}_walk_forward"
    return compute


def _label_compute(family: str):
    spec = FAMILY_KERNELS[family]
    table = np.empty(len(spec.labels) + 1, dtype=object)
    table[: len(spec.labels)] = spec.labels
    table[len(spec.labels)] = None

    def compute(inputs, config):
        code = np.asarray(inputs[spec.code_output], dtype=float)
        index = np.where(np.isnan(code), len(spec.labels), code).astype(int)
        return {spec.label_output: table[index]}

    compute.__name__ = f"_compute_{family}_label"
    return compute


def _kernels_for(family: str) -> tuple[Kernel, Kernel]:
    spec = FAMILY_KERNELS[family]
    heavy_inputs = ("close", "volume", "tf") if family == FAMILY_TREND else ("close", "tf")
    heavy = Kernel(
        name=f"hmm_{family}_walk_forward",
        outputs=(spec.code_output, spec.status_output, *spec.numeric_outputs),
        inputs=heavy_inputs,
        memory=lambda config: 0,
        compute=_heavy_compute(family),
        path_dependent=True,
        path_dependent_reason=_HEAVY_REASON,
    )
    label = Kernel(
        name=f"hmm_{family}_label",
        outputs=(spec.label_output,),
        inputs=(spec.code_output,),
        memory=lambda config: 0,
        compute=_label_compute(family),
        dtype=np.dtype(object),
        path_dependent=True,
        path_dependent_reason=_LABEL_REASON,
    )
    return heavy, label


KERNELS = (*_kernels_for(FAMILY_TREND), *_kernels_for(FAMILY_VOLATILITY))
