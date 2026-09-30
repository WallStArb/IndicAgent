"""Tunables for the measure package, passed in by the caller (the 186-14 writer).

No defaults: every value is read from APR by the writer and handed over, so no numeric literal
lives in this package (APR mandate). Field to APR key mapping is recorded in the 186-10 summary.

Every field is classified, as ic_engine classifies its config fields
(services/ic_engine.py `_COMPUTATIONAL_CONFIG_FIELDS` / `_OPERATIONAL_CONFIG_FIELDS`):

- computational: a change moves stored values, so it belongs in a unit's identity;
- operational: throughput or memory only, bit-identical output for any value, so it must never
  re-key a unit (tuning a memory knob would otherwise recompute everything).

A field declared without a kind raises on the first construction, and the writer's partition test
fails, so a new field cannot skip classification.
"""

from __future__ import annotations

import dataclasses
import typing

KIND = "kind"
COMPUTATIONAL = "computational"
OPERATIONAL = "operational"
_SIGNED = "signed"


def _field(kind: str, *, signed: bool = False) -> typing.Any:
    return dataclasses.field(metadata={KIND: kind, _SIGNED: signed})


@dataclasses.dataclass(frozen=True)
class MeasureParams:
    min_stride: int = _field(COMPUTATIONAL)  # alpha.ic.subsample_min_stride
    bootstrap_block_size: int = _field(COMPUTATIONAL)  # alpha.ic.bootstrap_block_size.{tf}
    bootstrap_resamples: int = _field(COMPUTATIONAL)  # alpha.ic.bootstrap_resamples
    rng_seed: int = _field(COMPUTATIONAL, signed=True)  # alpha.ic.bootstrap_seed
    fdr_alpha: float = _field(COMPUTATIONAL)  # alpha.ic.fdr_alpha (BH-FDR level)
    min_obs: int = _field(
        COMPUTATIONAL
    )  # alpha.ic.min_reliable_n (finite pairs for a reliable cell)
    # Size of the symbol chunks the S0 panels are built in. Targets of chunks stacked on the union
    # grid equal the targets of one panel exactly (targets.py), so it never enters a value.
    symbol_chunk_size: int = _field(OPERATIONAL)  # infra.ic_measure.symbol_chunk_size
    monitor_window_sessions: int = _field(COMPUTATIONAL)  # alpha.ic_measure.monitor_window_sessions
    hac_max_lag: int = _field(COMPUTATIONAL)  # alpha.ic.hac_max_lag
    degenerate_std: float = _field(COMPUTATIONAL)  # alpha.ic_measure.degenerate_std (1e-8)
    # Std floor below which the spread of a member's window ICs is degenerate, so its IC Sharpe
    # is 0.0 rather than a ratio to a near-zero denominator (monitoring.py). A different quantity
    # from `degenerate_std`, which floors a feature column's std.
    monitor_degenerate_std: float = _field(COMPUTATIONAL)  # alpha.ic_measure.monitor_degenerate_std

    def __post_init__(self) -> None:
        hints = typing.get_type_hints(type(self))
        for field in dataclasses.fields(self):
            value = getattr(self, field.name)
            if field.metadata.get(KIND) not in (COMPUTATIONAL, OPERATIONAL):
                raise TypeError(f"MeasureParams.{field.name} is not classified")
            if hints[field.name] is int:
                if not isinstance(value, int) or isinstance(value, bool):
                    raise ValueError(f"{field.name} must be an int, got {value!r}")
                if not field.metadata[_SIGNED] and value <= 0:
                    raise ValueError(f"{field.name} must be a positive int, got {value!r}")
            elif field.name == "fdr_alpha":
                if not 0.0 < value < 1.0:
                    raise ValueError(f"fdr_alpha must be in (0, 1), got {value!r}")
            elif not value > 0.0:
                raise ValueError(f"{field.name} must be positive, got {value!r}")


def field_type(name: str) -> type:
    """The declared type (int or float) of a MeasureParams field."""
    hint = typing.get_type_hints(MeasureParams)[name]
    if hint not in (int, float):
        raise TypeError(f"MeasureParams.{name} is declared {hint!r}, not int or float")
    return hint


def fields_of_kind(kind: str) -> tuple[str, ...]:
    """Names of the MeasureParams fields classified `kind`, in declaration order."""
    return tuple(f.name for f in dataclasses.fields(MeasureParams) if f.metadata.get(KIND) == kind)
