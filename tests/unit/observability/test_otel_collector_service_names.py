"""Each service.name the collector config matches is one a process passes to init_otel_providers.

A condition naming a service no process reports is a silent no-op: the stable-series transform
for the split feed auditor named "indicagent-split-feed-auditor" while the auditor reports
"split-feed-auditor", so its per-run series churn went on unnoticed (todo 683 review). Names are
read from the code by AST: a string literal, a module-level string constant, or an f-string over
such constants."""

from __future__ import annotations

import ast
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
CONFIG = REPO / "production" / "otel-collector-config.yaml"
_MATCHED = re.compile(r'resource\.attributes\["service\.name"\] == "([^"]+)"')


def _constants(tree: ast.Module) -> dict[str, str]:
    out = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant):
            if isinstance(node.value.value, str):
                out.update(
                    {t.id: node.value.value for t in node.targets if isinstance(t, ast.Name)}
                )
    return out


def _resolve(node: ast.expr, constants: dict[str, str]) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name):
        return constants.get(node.id)
    if isinstance(node, ast.JoinedStr):
        parts = []
        for value in node.values:
            part = _resolve(
                value.value if isinstance(value, ast.FormattedValue) else value, constants
            )
            if part is None:
                return None
            parts.append(part)
        return "".join(parts)
    return None


def _reported_service_names() -> set[str]:
    names = set()
    for path in [
        *REPO.glob("services/**/*.py"),
        *REPO.glob("scripts/**/*.py"),
        *REPO.glob("src/**/*.py"),
    ]:
        text = path.read_text()
        if "init_otel_providers(" not in text:
            continue
        tree = ast.parse(text)
        constants = _constants(tree)
        for node in ast.walk(tree):
            if not (
                isinstance(node, ast.Call)
                and getattr(node.func, "id", None) == "init_otel_providers"
            ):
                continue
            args = [*node.args, *(k.value for k in node.keywords if k.arg == "service_name")]
            names.update(n for a in args if (n := _resolve(a, constants)) is not None)
    return names


def test_the_resolver_finds_the_known_reporters() -> None:
    names = _reported_service_names()
    assert {"split-feed-auditor", "indicagent-alpaca-nightly"} <= names


def test_every_matched_service_name_is_reported_by_some_process() -> None:
    matched = set(_MATCHED.findall(CONFIG.read_text()))
    assert matched, "no service.name condition in the collector config"
    unknown = sorted(matched - _reported_service_names())
    assert not unknown, f"collector conditions on service names no process reports: {unknown}"
