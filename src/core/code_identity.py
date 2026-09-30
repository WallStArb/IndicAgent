"""Content identity of code: AST-normalized source and the first-party import closure.

Ring 0 (portable infrastructure, stdlib only, no domain vocabulary): a batch writer hashes the
modules that compute a result into its provenance key, so a logic edit re-keys the result and a
comment edit does not.

`normalized_source_for_hash` drops comments (never part of the AST), formatting, and module,
class and function docstrings. `import_closure` names the modules a set of entry modules can
reach through `import` statements, found with `ast` (imports inside functions, `try` and
`TYPE_CHECKING` blocks included; stdlib and third-party excluded). A package's `__init__` is part
of the closure as its own file: it runs on import, but its own imports are not followed, so a
re-export hub does not pull the whole tree in. Dynamic imports (`importlib.import_module(name)`)
are invisible to it, and a module that uses one must list its target as an entry.

services/ic_engine.py keeps a verbatim copy of `normalized_source_for_hash` (its
`_normalized_source_for_hash`) because editing ic_engine would move its own
`code_content_key`; that copy is deleted with ic_engine in phase 186 plan 23.
"""

from __future__ import annotations

import ast
import hashlib
import importlib.util
from collections.abc import Collection, Iterable
from pathlib import Path

FIRST_PARTY_PACKAGES: tuple[str, ...] = ("src", "services")


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


def _imported_modules(tree: ast.AST, module: str, packages: Collection[str]) -> Iterable[str]:
    """First-party modules one module's source imports, anywhere in its body."""
    own_package = module if _is_package(module) else module.rpartition(".")[0]
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.partition(".")[0] in packages:
                    yield alias.name
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                parts = own_package.split(".")
                if node.level - 1 >= len(parts):
                    raise ImportError(f"{module}: relative import beyond the top-level package")
                base_parts = parts[: len(parts) - (node.level - 1)]
                base = ".".join([*base_parts, *([node.module] if node.module else [])])
            else:
                base = node.module or ""
            if base.partition(".")[0] not in packages:
                continue
            yield base
            if _is_package(base):
                for alias in node.names:
                    candidate = f"{base}.{alias.name}"
                    if alias.name != "*" and _spec(candidate) is not None:
                        yield candidate  # `from pkg import submodule`


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
) -> tuple[str, ...]:
    """Sorted dotted names of the entry modules, every first-party module they import
    (transitively), the `__init__` of every package on those paths, and the `own` modules, which
    are hashed as files without following their imports (a writer's orchestration module whose
    imports are infrastructure, not computation). An entry or an import that names no module
    raises ModuleNotFoundError."""
    seen: set[str] = set()
    pending = list(entries)
    while pending:
        name = pending.pop()
        if name in seen:
            continue
        seen.add(name)
        if _is_package(name):
            continue  # a package is hashed as its __init__ file and not walked
        tree = ast.parse(source_path(name).read_bytes())
        pending.extend(m for m in _imported_modules(tree, name, packages) if m not in seen)
    leaves = set(own)
    for name in leaves:
        source_path(name)
    reached = seen | leaves
    for name in list(reached):
        reached.update(_ancestors(name, packages))
    return tuple(sorted(n for n in reached if not _is_namespace_package(n)))


def code_key(modules: Iterable[str]) -> str:
    """sha256 (64 lowercase hex) over the normalized source of exactly the named modules."""
    digest = hashlib.sha256()
    for name in sorted(set(modules)):
        digest.update(
            name.encode() + b"\x00" + normalized_source_for_hash(source_path(name).read_bytes())
        )
        digest.update(b"\x01")
    return digest.hexdigest()
