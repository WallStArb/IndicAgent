"""Kernel registry contract (186-08)."""

from __future__ import annotations

import dataclasses
import sys
import textwrap
from types import SimpleNamespace

import numpy as np
import pytest

from src.intelligence.features.registry import (
    Kernel,
    KernelRegistry,
    KernelRegistryError,
    discover_kernels,
    feature_memory_bars,
)

# Memory callables only read named attributes; a stand-in avoids the 113-field config.
CFG = SimpleNamespace(window=20)


def _k(name, outputs=None, inputs=("close",), memory=3, **kw):
    outs = outputs or (name,)
    return Kernel(
        name=name,
        outputs=tuple(outs),
        inputs=tuple(inputs),
        memory=(lambda c, m=memory: m),
        compute=lambda x, c, outs=outs: {o: x["close"].astype(np.float32) for o in outs},
        **kw,
    )


def test_registers_and_answers_memory():
    reg = KernelRegistry.from_kernels([_k("a", memory=5)])
    assert feature_memory_bars("a", CFG, reg) == 5


def test_effective_memory_adds_upstream_and_orders():
    reg = KernelRegistry.from_kernels(
        [_k("b", inputs=("a",), memory=4), _k("a", memory=6), _k("c", inputs=("b",), memory=1)]
    )
    assert feature_memory_bars("b", CFG, reg) == 10
    assert feature_memory_bars("c", CFG, reg) == 11
    assert [k.name for k in reg.topological_order()] == ["a", "b", "c"]


def test_duplicate_name_raises():
    with pytest.raises(KernelRegistryError, match="duplicate kernel name"):
        KernelRegistry.from_kernels([_k("a"), _k("a", outputs=("z",))])


def test_duplicate_output_raises():
    with pytest.raises(KernelRegistryError, match="duplicate output"):
        KernelRegistry.from_kernels([_k("a", outputs=("x",)), _k("b", outputs=("x",))])


def test_unresolved_input_raises():
    with pytest.raises(KernelRegistryError, match="nope"):
        KernelRegistry.from_kernels([_k("a", inputs=("nope",))])


def test_cycle_raises():
    with pytest.raises(KernelRegistryError, match="cycle"):
        KernelRegistry.from_kernels([_k("a", inputs=("b",)), _k("b", inputs=("a",))])


@pytest.mark.parametrize("bad", [-1, 2.5, "3"])
def test_invalid_memory_raises(bad):
    reg = KernelRegistry.from_kernels([_k("a", memory=bad)])
    with pytest.raises(KernelRegistryError, match="memory"):
        feature_memory_bars("a", CFG, reg)


def test_multi_output_kernel():
    reg = KernelRegistry.from_kernels([_k("smc", outputs=("x", "y"), memory=2)])
    assert feature_memory_bars("y", CFG, reg) == 2
    assert reg.outputs() == ("x", "y")


def test_kernel_is_frozen():
    with pytest.raises(dataclasses.FrozenInstanceError):
        _k("a").name = "b"  # type: ignore[misc]


def test_default_package_is_empty():
    assert discover_kernels().kernels == ()


_KERNEL_SRC = textwrap.dedent("""
    import numpy as np
    from src.intelligence.features.registry import Kernel
    KERNELS = (
        Kernel(name="{n}", outputs=("{n}",), inputs=("close",),
               memory=lambda c: 1, compute=lambda x, c: {{"{n}": x["close"]}}),
    )
    """)


def _make_pkg(tmp_path, monkeypatch, name, files):
    pkg = tmp_path / name
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    for fname, src in files.items():
        (pkg / f"{fname}.py").write_text(src)
    monkeypatch.syspath_prepend(str(tmp_path))
    return name


def _cleanup(name):
    for key in [k for k in sys.modules if k == name or k.startswith(name + ".")]:
        del sys.modules[key]


def test_discovery_finds_modules_and_ignores_others(tmp_path, monkeypatch):
    name = _make_pkg(
        tmp_path,
        monkeypatch,
        "tmp_kernels_ok",
        {"one": _KERNEL_SRC.format(n="k1"), "two": _KERNEL_SRC.format(n="k2"), "none": "X = 1\n"},
    )
    try:
        reg = discover_kernels(name)
    finally:
        _cleanup(name)
    assert [k.name for k in reg.kernels] == ["k1", "k2"]
    assert [k.origin for k in reg.kernels] == ["one", "two"]
    assert reg.kernels[0].module == f"{name}.one"


def test_discovery_rejects_non_kernel(tmp_path, monkeypatch):
    name = _make_pkg(tmp_path, monkeypatch, "tmp_kernels_bad", {"bad": "KERNELS = (1,)\n"})
    try:
        with pytest.raises(KernelRegistryError, match="tuple of Kernel"):
            discover_kernels(name)
    finally:
        _cleanup(name)
