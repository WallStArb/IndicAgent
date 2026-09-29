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

    @classmethod
    def from_kernels(cls, kernels: tuple[Kernel, ...] | list[Kernel]) -> KernelRegistry:
        kernels = tuple(kernels)
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
        for kernel in kernels:
            for name in kernel.inputs:
                if name not in BAR_FIELDS and name not in by_output:
                    raise KernelRegistryError(
                        f"kernel {_where(kernel)} input {name!r} is neither a bar field "
                        "nor another kernel's output"
                    )
        registry = cls(kernels=kernels)
        registry._check_acyclic()
        return registry

    def _upstream(self, kernel: Kernel) -> list[Kernel]:
        seen: dict[str, Kernel] = {}
        for name in kernel.inputs:
            if name not in BAR_FIELDS:
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

    def effective_memory_bars(self, name: str, config: FeatureFactoryConfig) -> int:
        kernel = self.by_name(name)
        own = _check_memory(kernel, config)
        upstream = [self.effective_memory_bars(up.name, config) for up in self._upstream(kernel)]
        return own + (max(upstream) if upstream else 0)

    def outputs(self) -> tuple[str, ...]:
        return tuple(sorted(o for kernel in self.kernels for o in kernel.outputs))


def discover_kernels(package: str = _DEFAULT_PACKAGE) -> KernelRegistry:
    """Import every non-underscore module in `package` and collect its `KERNELS` tuple."""
    pkg = importlib.import_module(package)
    found: list[Kernel] = []
    for info in sorted(pkgutil.iter_modules(pkg.__path__), key=lambda i: i.name):
        if info.name.startswith("_"):
            continue
        module_path = f"{package}.{info.name}"
        module = importlib.import_module(module_path)
        kernels = getattr(module, "KERNELS", None)
        if kernels is None:
            continue
        if not isinstance(kernels, tuple) or not all(isinstance(k, Kernel) for k in kernels):
            raise KernelRegistryError(f"{module_path}.KERNELS must be a tuple of Kernel")
        found.extend(dataclasses.replace(k, origin=info.name, module=module_path) for k in kernels)
    return KernelRegistry.from_kernels(found)


@functools.lru_cache(maxsize=1)
def default_registry() -> KernelRegistry:
    return discover_kernels()


def feature_memory_bars(
    output: str, config: FeatureFactoryConfig, registry: KernelRegistry | None = None
) -> int:
    """Declared memory in bars of the kernel producing `output` (D-26, the one source)."""
    reg = registry if registry is not None else default_registry()
    return reg.effective_memory_bars(reg.by_output(output).name, config)
