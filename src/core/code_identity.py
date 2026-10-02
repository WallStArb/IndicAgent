"""Content identity of code: AST-normalized source and the first-party import closure.

Ring 0 (portable infrastructure, stdlib only, no domain vocabulary): a batch writer hashes the
modules that compute a result into its provenance key, so a logic edit re-keys the result and a
comment edit does not.

`normalized_source_for_hash` drops comments (never part of the AST), formatting, and module,
class and function docstrings. `import_closure` names the modules a set of entry modules can
reach through `import` statements, found with `ast` (imports inside functions and `try` blocks
included; imports under `if TYPE_CHECKING:` never run and are skipped; stdlib and third-party
excluded). A package's `__init__` is part of the closure as its own file because it runs on
import. Its imports are followed only for a name an importer takes from it: `from pkg import
Name` resolves to the module that defines `Name` by reading the `__init__`'s own imports
(through aliases and further packages), so a re-export is tracked without pulling in every
other module the hub imports. `import pkg` and `from pkg import *` take no specific name and
follow nothing. Dynamic imports (`importlib.import_module(name)`) and attribute access on a
package are invisible to it, and a module that uses one must list its target as an entry.

I/O-boundary modules (`IO_BOUNDARY_MODULES`): a reviewed, named list of infrastructure modules
(connection pooling, telemetry) that cannot influence a computed value. Each registers in the
closure by name, so importing one still moves a key, but only its name is hashed, not its source,
and its own imports are not followed: an infrastructure edit must not recompute every result.

The old services/ic_engine.py kept a verbatim copy of `normalized_source_for_hash` (its
`_normalized_source_for_hash`) because editing ic_engine would move its own
`code_content_key`; that copy was deleted with ic_engine in phase 186 plan 23.
"""

from __future__ import annotations

import ast
import hashlib
import importlib.util
from collections.abc import Collection, Iterable
from pathlib import Path

FIRST_PARTY_PACKAGES: tuple[str, ...] = ("src", "services")

# Reviewed 2026-09-30 (plan 186-14 review fix F4), by reading each module and what the measure
# path does with it. Add a module only with the same evidence: it must be pure I/O or telemetry.
IO_BOUNDARY_MODULES: dict[str, str] = {
    "src.core.database_manager": (
        "asyncpg pool creation, pool-size gauges and jsonb codec registration; the research "
        "snapshot reads bars as numeric and timestamp columns and config_state as text, so no "
        "value passes through a jsonb decode"
    ),
    "src.observability.metrics": (
        "OpenTelemetry instrument definitions; counters and gauges record values and never "
        "return or alter one (its lazy tier_aliases import only names metric labels)"
    ),
}


def normalized_source_for_hash(source: bytes) -> bytes:
    """AST-normalized source bytes for content hashing.

    Comments and formatting are not part of the AST; module, class and function docstrings are
    blanked, so a comment or docstring reword does not move a key while any logic edit does.
    Falls back to the raw bytes on a parse failure, which only makes the hash more
    change-sensitive for that file.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return source
    docstring_holders = (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
    for node in ast.walk(tree):
        if not isinstance(node, docstring_holders) or not node.body:
            continue
        first = node.body[0]
        if (
            isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)
        ):
            first.value.value = ""
    return ast.dump(tree).encode()


def _spec(name: str) -> importlib.machinery.ModuleSpec | None:
    try:
        return importlib.util.find_spec(name)
    except (ModuleNotFoundError, ValueError):
        return None


def source_path(name: str) -> Path:
    """The source file of a dotted module; a name with no source file raises."""
    spec = _spec(name)
    if spec is None or spec.origin is None or not spec.origin.endswith(".py"):
        raise ModuleNotFoundError(f"no source file for module {name!r}")
    return Path(spec.origin)


def _is_package(name: str) -> bool:
    spec = _spec(name)
    return spec is not None and spec.submodule_search_locations is not None


def _is_namespace_package(name: str) -> bool:
    """A package with no __init__.py: it runs no code and has no file to hash."""
    spec = _spec(name)
    return spec is not None and spec.submodule_search_locations is not None and spec.origin is None


def _is_type_checking(test: ast.expr) -> bool:
    """`TYPE_CHECKING` or `<module>.TYPE_CHECKING`: a condition that is False at run time."""
    return (isinstance(test, ast.Name) and test.id == "TYPE_CHECKING") or (
        isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING"
    )


def _runtime_nodes(tree: ast.AST) -> Iterable[ast.AST]:
    """Every node that can execute: an `if TYPE_CHECKING:` body is skipped, its `else` is not."""
    stack = [tree]
    while stack:
        node = stack.pop()
        yield node
        if isinstance(node, ast.If) and _is_type_checking(node.test):
            stack.extend(node.orelse)
        else:
            stack.extend(ast.iter_child_nodes(node))


def _absolute_base(node: ast.ImportFrom, module: str, own_package: str) -> str:
    if not node.level:
        return node.module or ""
    parts = own_package.split(".")
    if node.level - 1 >= len(parts):
        raise ImportError(f"{module}: relative import beyond the top-level package")
    base_parts = parts[: len(parts) - (node.level - 1)]
    return ".".join([*base_parts, *([node.module] if node.module else [])])


def _reexport_sources(package: str, name: str, packages: Collection[str]) -> Iterable[str]:
    """The modules a package's `__init__` takes `name` from (`from x import name [as y]`, the
    name the importer asks for being the bound one), followed through further packages."""
    try:
        tree = ast.parse(source_path(package).read_bytes())
    except ModuleNotFoundError:
        return
    for node in _runtime_nodes(tree):
        if not isinstance(node, ast.ImportFrom):
            continue
        base = _absolute_base(node, package, package)
        if base.partition(".")[0] not in packages:
            continue
        for alias in node.names:
            if (alias.asname or alias.name) != name:
                continue
            yield base
            candidate = f"{base}.{alias.name}"
            if _is_package(base) and _spec(candidate) is not None:
                yield candidate
            elif _is_package(base):
                yield from _reexport_sources(base, alias.name, packages)


def _imported_modules(tree: ast.AST, module: str, packages: Collection[str]) -> Iterable[str]:
    """First-party modules one module's source imports at run time, anywhere in its body."""
    own_package = module if _is_package(module) else module.rpartition(".")[0]
    for node in _runtime_nodes(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.partition(".")[0] in packages:
                    yield alias.name
        elif isinstance(node, ast.ImportFrom):
            base = _absolute_base(node, module, own_package)
            if base.partition(".")[0] not in packages:
                continue
            yield base
            if _is_package(base):
                for alias in node.names:
                    if alias.name == "*":
                        continue
                    candidate = f"{base}.{alias.name}"
                    if _spec(candidate) is not None:
                        yield candidate  # `from pkg import submodule`
                    else:
                        yield from _reexport_sources(base, alias.name, packages)


def _ancestors(name: str, packages: Collection[str]) -> Iterable[str]:
    parts = name.split(".")
    for end in range(1, len(parts)):
        ancestor = ".".join(parts[:end])
        if ancestor.partition(".")[0] in packages:
            yield ancestor


def import_closure(
    entries: Iterable[str],
    own: Iterable[str] = (),
    packages: Collection[str] = FIRST_PARTY_PACKAGES,
    io_boundary: Collection[str] = tuple(IO_BOUNDARY_MODULES),
) -> tuple[str, ...]:
    """Sorted dotted names of the entry modules, every first-party module they import
    (transitively), the `__init__` of every package on those paths, and the `own` modules, which
    are hashed as files without following their imports (a writer's orchestration module whose
    imports are infrastructure, not computation). `io_boundary` modules are included by name and
    not walked. An entry or an import that names no module raises ModuleNotFoundError."""
    seen: set[str] = set()
    pending = list(entries)
    while pending:
        name = pending.pop()
        if name in seen:
            continue
        seen.add(name)
        if _is_package(name) or name in io_boundary:
            continue  # a package is hashed as its __init__ file; an I/O boundary by name
        tree = ast.parse(source_path(name).read_bytes())
        pending.extend(m for m in _imported_modules(tree, name, packages) if m not in seen)
    leaves = set(own)
    for name in leaves:
        source_path(name)
    reached = seen | leaves
    for name in list(reached):
        reached.update(_ancestors(name, packages))
    return tuple(sorted(n for n in reached if not _is_namespace_package(n)))


def code_key(
    modules: Iterable[str], io_boundary: Collection[str] = tuple(IO_BOUNDARY_MODULES)
) -> str:
    """sha256 (64 lowercase hex) over the normalized source of exactly the named modules; an
    `io_boundary` module contributes its name only."""
    digest = hashlib.sha256()
    for name in sorted(set(modules)):
        body = (
            b""
            if name in io_boundary
            else normalized_source_for_hash(source_path(name).read_bytes())
        )
        digest.update(name.encode() + b"\x00" + body)
        digest.update(b"\x01")
    return digest.hexdigest()
