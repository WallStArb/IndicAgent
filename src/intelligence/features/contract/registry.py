"""Kernel registry: declared inputs, declared memory and dtype over pure compute functions.

D-25: a kernel module dropped into `kernels/` and exporting a `KERNELS` tuple is found by
`discover_kernels()`; nothing in this file is edited to register it.

D-26: `feature_memory_bars()` is the single source of feature-member memory. `book_memory()`
(phase 187) and the rebuild warmup (186-25) read this function and nothing else.

Pure: no database, no ConfigService, no import-time registration side effects.
"""

from __future__ import annotations

import dataclasses
import enum
import functools
import importlib
import pkgutil
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import timedelta
from typing import TYPE_CHECKING

import numpy as np

from src.core.bar_accumulator import _ET, _RTH_OPEN_ET
from src.intelligence.bars.vendor_kind import VOLUME_BASIS_CONSOLIDATED
from src.intelligence.features.contract.derived_inputs import DERIVED_INPUTS, build_derived_inputs
from src.intelligence.features.contract.dropped_volume import (
    MAX_DROPPED_FRACTION,
    dropped_share_mask,
)

if TYPE_CHECKING:
    from src.intelligence.feature_factory import FeatureFactoryConfig

# Raw inputs every kernel may declare. Timestamps enter as int64 UTC nanoseconds. `volume_basis`
# (todo 555) is one small integer per bar saying what that bar's `volume` counts; a rolling
# volume statistic never spans a change of it.
BAR_FIELDS: tuple[str, ...] = ("ts", "open", "high", "low", "close", "volume", "volume_basis")

# `volume_basis` codes (none 0, consolidated 1, smart 2, mixed 3) and their (vendor, kind) mapping
# live in bars/vendor_kind.py, the one source.


def volume_basis_segment_starts(basis: np.ndarray) -> np.ndarray:
    """Row index where each row's volume-basis segment starts (todo 555).

    A segment is a run of rows on one volume basis. A bar with no volume (code 0) carries no
    basis, so it neither starts nor ends a segment: the basis it follows is the last nonzero one
    before it. A row starts a new segment when its nonzero code differs from the previous
    nonzero code, wherever that change falls in the series (per name and timeframe; never a
    date).
    """
    codes = np.asarray(basis, dtype=np.int64)
    n = len(codes)
    rows = np.arange(n)
    last_coded = np.maximum.accumulate(np.where(codes != 0, rows, -1))
    previous = np.concatenate([[-1], last_coded[:-1]])
    has_previous = previous >= 0
    changed = (codes != 0) & has_previous & (codes != codes[np.maximum(previous, 0)])
    return np.maximum.accumulate(np.where(changed, rows, 0))


def constant_volume_basis(n: int) -> np.ndarray:
    """A `volume_basis` array for a single-vendor input (the live stream, the probe fixtures, a
    research panel): every bar consolidated, so no segment boundary exists."""
    return np.full(n, VOLUME_BASIS_CONSOLIDATED, dtype=np.int64)


_DEFAULT_PACKAGE = "src.intelligence.features.kernels"


class KernelRegistryError(Exception):
    """The kernel set violates the registry contract."""


@dataclass(frozen=True)
class Kernel:
    """A pure feature computation.

    `compute(inputs, config)` returns one array per declared output, each the length of the
    input; output row i depends only on input rows 0..i. `origin` and `module` are stamped by
    `discover_kernels` (186-14 hashes `module` for the per-kernel code key, D-23).
    """

    name: str
    outputs: tuple[str, ...]
    inputs: tuple[str, ...]
    memory: Callable[[FeatureFactoryConfig], int]
    compute: Callable[[Mapping[str, np.ndarray], FeatureFactoryConfig], Mapping[str, np.ndarray]]
    dtype: np.dtype = dataclasses.field(default_factory=lambda: np.dtype(np.float32))
    origin: str = ""
    module: str = ""
    # The output at row t depends on where the series starts (a refresh cadence counted from
    # row 0, an anchor at the first close), so no finite memory reproduces it. The rebuild
    # computes such a kernel from the series start (D-26: a wrong warmup is a silent wrong
    # answer, so `feature_memory_bars` raises for it).
    path_dependent: bool = False
    path_dependent_reason: str = ""
    # Absolute float32 tolerance at which the declared memory holds. 0.0 means exact. A non-zero
    # value needs a comment in the kernel module giving the source of the last-bit difference
    # (cumsum-based rolling statistics, Wilder recursions).
    memory_atol: float = 0.0
    # A deliberate lookahead positive control: the causality probe must fail it.
    acausal_control: bool = False
    # The kernel handles NaN `volume` (a NULL-volume bar) and a volume-basis change itself.
    # Most volume kernels do not: one NaN poisons a cumulative sum or a rolling std and every
    # later row reads 0.0 or garbage. `compute_kernels` runs those per basis segment with NaN
    # volume as 0.0 and masks the affected rows (`_compute_basis_guarded`, todo 560).
    nan_volume_safe: bool = False
    # A path-dependent volume kernel whose accumulator resets on a calendar anchor: "week" (ISO
    # week of the bar timestamp) or "session" (the ET session day). A dropped bar (NULL volume,
    # entered as 0.0) corrupts the accumulator until that reset, so the guard masks those rows.
    # None: no reset, a dropped bar's own row is masked and the residual error is the accepted
    # tolerance recorded in todo 560 (one missing weight among the accumulated bars).
    volume_reset: str | None = None
    # Without a reset anchor: a row is masked while dropped bars exceed this share of the bars
    # accumulated so far (the dropped bars' weight is missing from the cumulative statistic, so
    # the error grows with their share; at 5% it stays below about 0.1 sigma on the probe series).
    # [initial_estimate] a declared property of the kernel definition, as `memory_atol` is.
    max_dropped_fraction: float = MAX_DROPPED_FRACTION


class Alignment(enum.Enum):
    """When a caller-supplied value is available relative to the row it is aligned to.

    Part of the causality contract: the probe truncates inputs it is given, so it cannot see
    how the caller aligned an external. Each member needs a builder in feature_factory
    (`_BUILT_ALIGNMENTS`) and a raw-input truncation runner in tests/unit/intelligence/
    test_macro_alignment.py.
    """

    # One value for the whole series, known before the first row (the symbol).
    CONSTANT_PER_SERIES = "constant_per_series"
    # A daily record available from the 16:00 ET close of its date, aligned with
    # kernels.macro.daily_asof_indices: a row reads only records closed by its bar end.
    DAILY_ASOF_CLOSE = "daily_asof_close"
    # A daily close on a daily reference grid (one row per date, the union of the symbols' 1d
    # dates, NaN where a symbol has no bar): value final at that date's 16:00 ET close. Only the
    # daily-grid kernels (cross_asset_daily, factor_beta_daily) read it; it is never aligned to
    # intraday rows, which read the kernels' records through DAILY_ASOF_CLOSE.
    DAILY_REFERENCE_GRID = "daily_reference_grid"
    # A higher-timeframe value keyed by its bar's close time (the next HTF bar's start) and read
    # with kernels.cross_tf.ctf_row_inputs: a row reads only HTF bars closed by its bar start.
    HTF_ASOF_CLOSE = "htf_asof_close"
    # A lower-timeframe value (the last 1m log return) taken from 1m bars stamped at or before
    # the row's bar start (kernels.cross_tf._build_ltf_return_series).
    LTF_ASOF_BAR_START = "ltf_asof_bar_start"


@dataclass(frozen=True)
class ExternalInput:
    """A caller-supplied per-row input on the row grid (a symbol string, daily macro values).

    `alignment` is part of the causality contract; the registry refuses one that is not an
    `Alignment` member.
    """

    name: str
    dtype: np.dtype
    alignment: Alignment


def _where(kernel: Kernel) -> str:
    return f"{kernel.name!r} ({kernel.module or 'unstamped'})"


def _check_memory(kernel: Kernel, config: FeatureFactoryConfig) -> int:
    value = kernel.memory(config)
    if isinstance(value, bool) or not isinstance(value, (int, np.integer)) or value < 0:
        raise KernelRegistryError(
            f"kernel {_where(kernel)} declares invalid memory {value!r}; need a non-negative int"
        )
    return int(value)


@dataclass(frozen=True)
class KernelRegistry:
    kernels: tuple[Kernel, ...]
    external_inputs: tuple[ExternalInput, ...] = ()
    # Lookup and plan caches, filled by `from_kernels` (the registry is immutable afterwards).
    _by_name: dict[str, Kernel] = field(init=False, repr=False, compare=False, default_factory=dict)
    _by_output: dict[str, Kernel] = field(
        init=False, repr=False, compare=False, default_factory=dict
    )
    _upstream_cache: dict[str, list[Kernel]] = field(
        init=False, repr=False, compare=False, default_factory=dict
    )
    _plans: dict[tuple[str, ...] | None, tuple[Kernel, ...]] = field(
        init=False, repr=False, compare=False, default_factory=dict
    )

    @classmethod
    def from_kernels(
        cls,
        kernels: tuple[Kernel, ...] | list[Kernel],
        external_inputs: tuple[ExternalInput, ...] | list[ExternalInput] = (),
    ) -> KernelRegistry:
        kernels = tuple(kernels)
        external_inputs = tuple(external_inputs)
        external_names: set[str] = set()
        for external in external_inputs:
            if external.name in external_names:
                raise KernelRegistryError(f"duplicate external input {external.name!r}")
            if external.name in BAR_FIELDS:
                raise KernelRegistryError(
                    f"external input {external.name!r} collides with a bar field"
                )
            if not isinstance(external.alignment, Alignment):
                raise KernelRegistryError(
                    f"external input {external.name!r} alignment {external.alignment!r} is not "
                    "an Alignment member"
                )
            external_names.add(external.name)
        by_name: dict[str, Kernel] = {}
        by_output: dict[str, Kernel] = {}
        for kernel in kernels:
            if kernel.name in by_name:
                raise KernelRegistryError(
                    f"duplicate kernel name {kernel.name!r}: {_where(by_name[kernel.name])} "
                    f"and {_where(kernel)}"
                )
            by_name[kernel.name] = kernel
            for output in kernel.outputs:
                if output in by_output:
                    raise KernelRegistryError(
                        f"duplicate output {output!r}: {_where(by_output[output])} "
                        f"and {_where(kernel)}"
                    )
                by_output[output] = kernel
        for name in sorted(external_names & set(by_output)):
            raise KernelRegistryError(
                f"external input {name!r} equals the output of {_where(by_output[name])}"
            )
        for kernel in kernels:
            if kernel.path_dependent and not kernel.path_dependent_reason.strip():
                raise KernelRegistryError(
                    f"kernel {_where(kernel)} is path_dependent without a path_dependent_reason"
                )
            for name in kernel.inputs:
                if (
                    name not in BAR_FIELDS
                    and name not in DERIVED_INPUTS
                    and name not in by_output
                    and name not in external_names
                ):
                    raise KernelRegistryError(
                        f"kernel {_where(kernel)} input {name!r} is not a bar field, a declared "
                        "external input or another kernel's output"
                    )
        registry = cls(kernels=kernels, external_inputs=external_inputs)
        registry._by_name.update(by_name)
        registry._by_output.update(by_output)
        registry.topological_order()  # raises on an input cycle and caches the full order
        return registry

    def _external_names(self) -> frozenset[str]:
        return frozenset(external.name for external in self.external_inputs)

    def _upstream(self, kernel: Kernel) -> list[Kernel]:
        cached = self._upstream_cache.get(kernel.name)
        if cached is None:
            seen: dict[str, Kernel] = {}
            external = self._external_names()
            for name in kernel.inputs:
                if name not in BAR_FIELDS and name not in DERIVED_INPUTS and name not in external:
                    producer = self.by_output(name)
                    seen[producer.name] = producer
            cached = self._upstream_cache[kernel.name] = [seen[key] for key in sorted(seen)]
        return cached

    def by_name(self, name: str) -> Kernel:
        try:
            return self._by_name[name]
        except KeyError:
            raise KernelRegistryError(f"unknown kernel {name!r}") from None

    def by_output(self, output: str) -> Kernel:
        try:
            return self._by_output[output]
        except KeyError:
            raise KernelRegistryError(f"unknown feature output {output!r}") from None

    def _walk(self, roots: list[Kernel]) -> dict[str, Kernel]:
        """Depth-first post-order from `roots`: each kernel after its upstream. Raises on a cycle."""
        done: dict[str, Kernel] = {}
        visiting: set[str] = set()

        def visit(kernel: Kernel, path: tuple[str, ...]) -> None:
            if kernel.name in done:
                return
            if kernel.name in visiting:
                raise KernelRegistryError("input cycle: " + " -> ".join((*path, kernel.name)))
            visiting.add(kernel.name)
            for up in self._upstream(kernel):
                visit(up, (*path, kernel.name))
            visiting.discard(kernel.name)
            done[kernel.name] = kernel

        for root in roots:
            visit(root, ())
        return done

    def topological_order(
        self, outputs: list[str] | tuple[str, ...] | None = None
    ) -> tuple[Kernel, ...]:
        """Kernels upstream first, ties by name. With `outputs`, only the kernels producing them
        and their upstream, in the same relative order. Memoized per `tuple(outputs)`."""
        key = None if outputs is None else tuple(outputs)
        plan = self._plans.get(key)
        if plan is not None:
            return plan
        full = self._plans.get(None)
        if full is None:
            full = tuple(self._walk(sorted(self.kernels, key=lambda k: k.name)).values())
            self._plans[None] = full
        if key is None:
            return full
        needed = self._walk([self.by_output(output) for output in key])
        plan = self._plans[key] = tuple(k for k in full if k.name in needed)
        return plan

    def _path_dependent_source(self, kernel: Kernel) -> Kernel | None:
        """The kernel (itself or the first upstream) declared path dependent, else None."""
        if kernel.path_dependent:
            return kernel
        for up in self._upstream(kernel):
            source = self._path_dependent_source(up)
            if source is not None:
                return source
        return None

    def is_path_dependent(self, output: str) -> bool:
        return self._path_dependent_source(self.by_output(output)) is not None

    def effective_memory_bars(self, name: str, config: FeatureFactoryConfig) -> int:
        kernel = self.by_name(name)
        source = self._path_dependent_source(kernel)
        if source is not None:
            raise KernelRegistryError(
                f"kernel {_where(kernel)} has no finite memory: {_where(source)} is path "
                f"dependent ({source.path_dependent_reason}); compute it from the series start"
            )
        own = _check_memory(kernel, config)
        upstream = [self.effective_memory_bars(up.name, config) for up in self._upstream(kernel)]
        return own + (max(upstream) if upstream else 0)

    def outputs(self) -> tuple[str, ...]:
        return tuple(sorted(o for kernel in self.kernels for o in kernel.outputs))

    def feature_columns(self) -> tuple[str, ...]:
        """Outputs that are feature columns; a leading underscore marks an intermediate."""
        return tuple(o for o in self.outputs() if not o.startswith("_"))


def discover_kernels(package: str = _DEFAULT_PACKAGE) -> KernelRegistry:
    """Import every non-underscore module in `package` and collect its `KERNELS` tuple."""
    pkg = importlib.import_module(package)
    found: list[Kernel] = []
    externals: list[ExternalInput] = []
    for info in sorted(pkgutil.iter_modules(pkg.__path__), key=lambda i: i.name):
        if info.name.startswith("_"):
            continue
        module_path = f"{package}.{info.name}"
        module = importlib.import_module(module_path)
        module_externals = getattr(module, "EXTERNAL_INPUTS", ())
        if not isinstance(module_externals, tuple) or not all(
            isinstance(e, ExternalInput) for e in module_externals
        ):
            raise KernelRegistryError(
                f"{module_path}.EXTERNAL_INPUTS must be a tuple of ExternalInput"
            )
        externals.extend(module_externals)
        kernels = getattr(module, "KERNELS", None)
        if kernels is None:
            continue
        if not isinstance(kernels, tuple) or not all(isinstance(k, Kernel) for k in kernels):
            raise KernelRegistryError(f"{module_path}.KERNELS must be a tuple of Kernel")
        found.extend(dataclasses.replace(k, origin=info.name, module=module_path) for k in kernels)
    return KernelRegistry.from_kernels(found, externals)


@functools.lru_cache(maxsize=1)
def default_registry() -> KernelRegistry:
    return discover_kernels()


# Numeric FeatureVector columns no kernel owns, each with the reason. The pipeline refuses to
# start when a numeric column is neither a registry feature column nor listed here, and a test
# holds `feature_columns() + UNOWNED_COLUMNS` equal to the numeric schema, so a dropped or
# forgotten column is loud (D-28, T-186-15-07).
UNOWNED_COLUMNS: Mapping[str, str] = {
    "momentum_rank_z": (
        "todo 421: hard-coded None in feature_factory; a cross-sectional rank needs the whole "
        "universe per bar, so it cannot be a per-series kernel; 186-24 drops the column"
    ),
    "volatility_rank_z": (
        "todo 421: hard-coded None in feature_factory; a cross-sectional rank needs the whole "
        "universe per bar, so it cannot be a per-series kernel; 186-24 drops the column"
    ),
    "volume_rank_z": (
        "todo 421: hard-coded None in feature_factory; a cross-sectional rank needs the whole "
        "universe per bar, so it cannot be a per-series kernel; 186-24 drops the column"
    ),
}


# Registry feature columns the legacy FeatureVector (and the old feature_vectors table) does not
# carry, each with the reason: they are stored only in feature_vectors_v2, which the 186-26
# rebuild writes. The legacy chain retires at the 186-27 swap and is not extended, so a test that
# holds the registry against FeatureVector subtracts exactly these.
V2_ONLY_COLUMNS: Mapping[str, str] = {
    "high_low_spread": "todo 553: added after 186-24 (migration 526); feature_vectors_v2 only",
    "roll_spread": "todo 553: added after 186-24 (migration 526); feature_vectors_v2 only",
}


def registry_column_gaps(
    numeric_columns: Iterable[str], registry: KernelRegistry | None = None
) -> list[str]:
    """Numeric columns that are neither a registry feature column nor in `UNOWNED_COLUMNS`."""
    owned = set((registry if registry is not None else default_registry()).feature_columns())
    return sorted(c for c in numeric_columns if c not in owned and c not in UNOWNED_COLUMNS)


def feature_memory_bars(
    output: str, config: FeatureFactoryConfig, registry: KernelRegistry | None = None
) -> int:
    """Declared memory in bars of the kernel producing `output` (D-26, the one source)."""
    reg = registry if registry is not None else default_registry()
    return reg.effective_memory_bars(reg.by_output(output).name, config)


def _is_none_mask(name: str) -> bool:
    return name.startswith("_") and name.endswith("_is_none")


def _masked_until_reset(
    kernel: Kernel, cut: Mapping[str, np.ndarray], dropped: np.ndarray
) -> np.ndarray:
    """Rows a dropped bar corrupts in a path-dependent kernel: from the bar to its next reset.

    A kernel without a `volume_reset` anchor masks the dropped bar's own row, and every row
    while the dropped bars exceed `max_dropped_fraction` of the bars accumulated so far.
    """
    if not dropped.any():
        return dropped
    if kernel.volume_reset is None:
        return dropped_share_mask(dropped, kernel.max_dropped_fraction)
    ids = [_reset_id(ts, kernel.volume_reset) for ts in cut["ts_dt"]]
    n = len(ids)
    new_id = np.array([True, *(ids[i] != ids[i - 1] for i in range(1, n))])
    starts = np.flatnonzero(new_id)
    start_of_row = starts[np.searchsorted(starts, np.arange(n), side="right") - 1]
    counts = np.cumsum(dropped)
    before = np.where(start_of_row > 0, counts[np.maximum(start_of_row - 1, 0)], 0)
    masked = counts - before > 0
    if kernel.volume_reset == "week":
        # The weekly flag reads its state before the same bar is added (row i holds bars < i), so
        # the first row of the next week still carries the corrupted week.
        masked[1:] |= masked[:-1].copy()
    return masked


def _reset_id(ts: object, anchor: str) -> tuple[int, ...] | object:
    """The accumulator reset bucket of a bar: ISO (year, week), or the ET session day."""
    if anchor == "week":
        iso = ts.isocalendar()  # type: ignore[attr-defined]
        return (iso.year, iso.week)
    if anchor == "session":
        et = ts.astimezone(_ET)  # type: ignore[attr-defined]
        return et.date() if et.time() >= _RTH_OPEN_ET else et.date() - timedelta(days=1)
    raise KernelRegistryError(f"unknown volume_reset anchor {anchor!r}")


def _compute_basis_guarded(
    kernel: Kernel, cut: Mapping[str, np.ndarray], basis: np.ndarray, config: object
) -> Mapping[str, np.ndarray]:
    """The outputs of `_guard_volume` (the masked rows are `compute_kernels`' business)."""
    return _guard_volume(kernel, cut, basis, config)[0]


def _guard_volume(
    kernel: Kernel, cut: Mapping[str, np.ndarray], basis: np.ndarray, config: object
) -> tuple[Mapping[str, np.ndarray], np.ndarray]:
    """Run a volume-reading kernel that is not NaN-safe per volume-basis segment (todo 555/560).

    A NaN volume (a NULL-volume bar) would turn a cumulative sum or a rolling std into 0.0 or
    garbage on every later row, and a window spanning a basis change carries a level shift. So
    the kernel runs on each basis segment alone, NaN volume enters as 0.0 (no volume traded,
    finite), and an output row is NaN (a none-mask row is 1) when its trailing `memory + 1`
    bars hold a dropped bar or span a segment boundary: the declared memory then still holds,
    and the gap is loud (tests/unit/intelligence/test_basis_guard_invariant.py proves both ways). A path-dependent kernel has no finite memory and weights by volume, so it
    runs through the whole series; a dropped bar masks its rows until the kernel's next reset anchor.
    """
    volume = np.asarray(cut["volume"], dtype=float)
    dropped = ~np.isfinite(volume)
    starts = volume_basis_segment_starts(basis)
    n = len(volume)
    if not dropped.any() and not starts.any():
        return kernel.compute(cut, config), np.zeros(n, dtype=bool)  # type: ignore[arg-type]
    clean = np.where(dropped, 0.0, volume)
    if kernel.path_dependent:
        # These kernels weight by volume (VWAP, volume profile) rather than read its level, so a
        # basis change shifts weights by the basis ratio (at most about 5% of a sigma on the
        # synthetic seam probe), while a restart at the seam lost the accumulated state and erred
        # by up to 3 sigma. Run through, mask only the dropped bar's own row.
        out = {
            name: np.array(column)
            for name, column in kernel.compute({**cut, "volume": clean}, config).items()  # type: ignore[arg-type]
        }
        masked = _masked_until_reset(kernel, cut, dropped)
        for name, column in out.items():
            if column.dtype.kind != "f":
                raise KernelRegistryError(
                    f"kernel {_where(kernel)} output {name!r} has dtype {column.dtype}; the "
                    "volume basis guard can only mask float outputs"
                )
            column[masked] = 1.0 if _is_none_mask(name) else np.nan
        return out, masked
    bounds = np.unique(starts)
    out: dict[str, np.ndarray] = {}
    for lo, hi in zip(bounds, [*bounds[1:], n], strict=True):
        part = {
            k: (
                (clean if k == "volume" else v)[lo:hi]
                if getattr(v, "ndim", 0) >= 1 and len(v) == n
                else v
            )
            for k, v in cut.items()
        }
        for name, column in kernel.compute(part, config).items():  # type: ignore[arg-type]
            column = np.asarray(column)
            if name not in out:
                out[name] = (
                    np.full(n, np.nan) if column.dtype.kind == "f" else np.empty(n, column.dtype)
                )
            out[name][lo:hi] = column
    memory = int(kernel.memory(config))  # type: ignore[arg-type]
    rows = np.arange(n)
    hits = _trailing_hits

    # A dropped bar d sits in the windows of rows d .. d + memory. A segment start s splits
    # the windows that hold both s - 1 and s: rows s .. s + memory - 1.
    masked = hits(dropped, memory) | hits((starts == rows) & (rows > 0), memory - 1)
    for name, column in out.items():
        if column.dtype.kind != "f":
            raise KernelRegistryError(
                f"kernel {_where(kernel)} output {name!r} has dtype {column.dtype}; the volume "
                "basis guard can only mask float outputs"
            )
        if _is_none_mask(name):
            # a segment's own row 0 is NaN in a none-mask column; the writer reads NaN as neither
            # present nor missing, so it reads as missing (1)
            column[np.isnan(column)] = 1.0
        column[masked] = 1.0 if _is_none_mask(name) else np.nan
    return out, masked


def _trailing_hits(event: np.ndarray, reach: int) -> np.ndarray:
    """Rows whose trailing `reach + 1` bars hold an event row."""
    rows = np.arange(len(event))
    counts = np.cumsum(event)
    before = np.where(rows - reach - 1 >= 0, counts[np.maximum(rows - reach - 1, 0)], 0)
    return counts - before > 0


def _guard_downstream(
    kernel: Kernel,
    cut: Mapping[str, np.ndarray],
    dirty: Mapping[str, np.ndarray],
    config: object,
) -> tuple[Mapping[str, np.ndarray], np.ndarray]:
    """Run a kernel that reads a guarded kernel's masked output (todo 560, transitive).

    The guard's masked rows arrive as NaN, and a cumulative or cumsum-based statistic downstream
    turns one NaN into 0.0 on every later row, or reads NaN as "no event". So a masked input row
    enters as 0.0 and an output row is masked (NaN, 1 for a none-mask column) when its trailing
    `memory + 1` input rows hold a masked row. The output's own masked rows feed the next kernel.
    """
    if kernel.path_dependent:
        raise KernelRegistryError(
            f"kernel {_where(kernel)} is path dependent and reads a volume-guarded output; the "
            "guard has no reset anchor for it"
        )
    event = np.logical_or.reduce([dirty[name] for name in kernel.inputs if name in dirty])
    clean = {
        name: (
            np.where(dirty[name], 0.0, np.asarray(column, dtype=float)) if name in dirty else column
        )
        for name, column in cut.items()
    }
    out = {name: np.array(column) for name, column in kernel.compute(clean, config).items()}  # type: ignore[arg-type]
    masked = _trailing_hits(event, int(kernel.memory(config)))  # type: ignore[arg-type]
    for name, column in out.items():
        if column.dtype.kind != "f":
            raise KernelRegistryError(
                f"kernel {_where(kernel)} output {name!r} has dtype {column.dtype}; the volume "
                "basis guard can only mask float outputs"
            )
        column[masked] = 1.0 if _is_none_mask(name) else np.nan
    return out, masked


def compute_kernels(
    registry: KernelRegistry,
    inputs: Mapping[str, np.ndarray],
    config: FeatureFactoryConfig,
    outputs: list[str] | tuple[str, ...] | None = None,
) -> dict[str, np.ndarray]:
    """Run kernels in topological order and return one array per output, each of length n.

    With `outputs`, only the kernels producing them and their upstream run. Arrays keep the
    dtype the kernel computed in (float64 for the moved feature_factory kernels); the kernel's
    declared `dtype` is the persistence dtype, applied by the writer and by the probe.
    """
    order = registry.topological_order(outputs)
    external = registry._external_names()
    produced = {o for kernel in order for o in kernel.outputs}
    derived = {name for kernel in order for name in kernel.inputs if name in DERIVED_INPUTS}
    for kernel in order:
        for name in kernel.inputs:
            if name not in produced and name not in inputs and name not in derived:
                kind = "external input" if name in external else "bar field"
                raise KernelRegistryError(
                    f"kernel {_where(kernel)} needs {kind} {name!r}, which the caller did not supply"
                )
    guarded = [k for k in order if "volume" in k.inputs and not k.nan_volume_safe]
    if guarded and "volume_basis" not in inputs:
        raise KernelRegistryError(
            f"kernels {sorted(k.name for k in guarded)} read volume and need the bar field "
            "'volume_basis', which the caller did not supply"
        )
    n = next((len(inputs[f]) for f in BAR_FIELDS if f in inputs), None)
    if n is None:
        raise KernelRegistryError("compute_kernels needs at least one bar field in inputs")
    values: dict[str, np.ndarray] = dict(inputs)
    for name in derived:
        for needed in DERIVED_INPUTS[name][0]:
            if needed not in inputs:
                raise KernelRegistryError(
                    f"derived input {name!r} needs bar field {needed!r}, which the caller did not supply"
                )
    values.update(build_derived_inputs(derived, inputs))
    result: dict[str, np.ndarray] = {}
    dirty: dict[str, np.ndarray] = {}  # output -> rows the volume guard masked
    for kernel in order:
        cut = {name: values[name] for name in kernel.inputs}
        if "volume" in kernel.inputs and not kernel.nan_volume_safe:
            out, masked = _guard_volume(kernel, cut, values["volume_basis"], config)
        elif any(name in dirty for name in kernel.inputs):
            out, masked = _guard_downstream(kernel, cut, dirty, config)
        else:
            out, masked = kernel.compute(cut, config), None
        if masked is not None and masked.any():
            dirty.update({name: masked for name in kernel.outputs})
        for name in kernel.outputs:
            if name not in out:
                raise KernelRegistryError(f"kernel {_where(kernel)} did not return output {name!r}")
            arr = np.asarray(out[name])
            if arr.shape[0] != n:
                raise KernelRegistryError(
                    f"kernel {_where(kernel)} output {name!r} has {arr.shape[0]} rows for {n} "
                    "input rows"
                )
            values[name] = arr
            result[name] = arr
    return result
