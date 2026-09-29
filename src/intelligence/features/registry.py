"""Kernel registry: declared inputs, declared memory and dtype over pure compute functions.

D-25: a kernel module dropped into `kernels/` and exporting a `KERNELS` tuple is found by
`discover_kernels()`; nothing in this file is edited to register it.

D-26: `feature_memory_bars()` is the single source of feature-member memory. `book_memory()`
(phase 187) and the rebuild warmup (186-25) read this function and nothing else.

Pure: no database, no ConfigService, no import-time registration side effects.
"""

from __future__ import annotations

import dataclasses
import functools
import importlib
import pkgutil
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from src.intelligence.feature_factory import FeatureFactoryConfig

# Raw inputs every kernel may declare. Timestamps enter as int64 UTC nanoseconds.
BAR_FIELDS: tuple[str, ...] = ("ts", "open", "high", "low", "close", "volume")

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
    cross_sectional: bool = False
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


@dataclass(frozen=True)
class ExternalInput:
    """A caller-supplied per-row input on the row grid (a symbol string, daily macro values).

    `alignment` states in prose when the value is available relative to the row; it is part of
    the causality contract, because the probe cannot see how the caller aligned the value.
    """

    name: str
    dtype: np.dtype
    alignment: str


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
                if name not in BAR_FIELDS and name not in by_output and name not in external_names:
                    raise KernelRegistryError(
                        f"kernel {_where(kernel)} input {name!r} is not a bar field, a declared "
                        "external input or another kernel's output"
                    )
        registry = cls(kernels=kernels, external_inputs=external_inputs)
        registry._check_acyclic()
        return registry

    def _external_names(self) -> frozenset[str]:
        return frozenset(external.name for external in self.external_inputs)

    def _upstream(self, kernel: Kernel) -> list[Kernel]:
        seen: dict[str, Kernel] = {}
        external = self._external_names()
        for name in kernel.inputs:
            if name not in BAR_FIELDS and name not in external:
                producer = self.by_output(name)
                seen[producer.name] = producer
        return [seen[key] for key in sorted(seen)]

    def _check_acyclic(self) -> None:
        state: dict[str, int] = {}  # 1 = visiting, 2 = done

        def visit(kernel: Kernel, path: tuple[str, ...]) -> None:
            if state.get(kernel.name) == 2:
                return
            if state.get(kernel.name) == 1:
                raise KernelRegistryError("input cycle: " + " -> ".join((*path, kernel.name)))
            state[kernel.name] = 1
            for up in self._upstream(kernel):
                visit(up, (*path, kernel.name))
            state[kernel.name] = 2

        for kernel in sorted(self.kernels, key=lambda k: k.name):
            visit(kernel, ())

    def by_name(self, name: str) -> Kernel:
        for kernel in self.kernels:
            if kernel.name == name:
                return kernel
        raise KernelRegistryError(f"unknown kernel {name!r}")

    def by_output(self, output: str) -> Kernel:
        for kernel in self.kernels:
            if output in kernel.outputs:
                return kernel
        raise KernelRegistryError(f"unknown feature output {output!r}")

    def topological_order(self) -> tuple[Kernel, ...]:
        done: dict[str, Kernel] = {}

        def visit(kernel: Kernel) -> None:
            if kernel.name in done:
                return
            for up in self._upstream(kernel):
                visit(up)
            done[kernel.name] = kernel

        for kernel in sorted(self.kernels, key=lambda k: k.name):
            visit(kernel)
        return tuple(done.values())

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

    def _closure(self, outputs: list[str] | tuple[str, ...]) -> set[str]:
        needed: set[str] = set()

        def visit(kernel: Kernel) -> None:
            if kernel.name in needed:
                return
            needed.add(kernel.name)
            for up in self._upstream(kernel):
                visit(up)

        for output in outputs:
            visit(self.by_output(output))
        return needed


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


def feature_memory_bars(
    output: str, config: FeatureFactoryConfig, registry: KernelRegistry | None = None
) -> int:
    """Declared memory in bars of the kernel producing `output` (D-26, the one source)."""
    reg = registry if registry is not None else default_registry()
    return reg.effective_memory_bars(reg.by_output(output).name, config)


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
    if outputs is None:
        selected = {kernel.name for kernel in registry.kernels}
    else:
        selected = registry._closure(outputs)
    order = [kernel for kernel in registry.topological_order() if kernel.name in selected]
    external = registry._external_names()
    produced = {o for kernel in order for o in kernel.outputs}
    for kernel in order:
        for name in kernel.inputs:
            if name not in produced and name not in inputs:
                kind = "external input" if name in external else "bar field"
                raise KernelRegistryError(
                    f"kernel {_where(kernel)} needs {kind} {name!r}, which the caller did not supply"
                )
    n = next((len(inputs[f]) for f in BAR_FIELDS if f in inputs), None)
    if n is None:
        raise KernelRegistryError("compute_kernels needs at least one bar field in inputs")
    values: dict[str, np.ndarray] = dict(inputs)
    result: dict[str, np.ndarray] = {}
    for kernel in order:
        cut = {name: values[name] for name in kernel.inputs}
        out = kernel.compute(cut, config)
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
