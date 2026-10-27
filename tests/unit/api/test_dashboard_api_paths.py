"""Every /api path the dashboard fetches is a GET route the API registers.

The 509 cleanup found the old UI still polling routes deleted months earlier (it showed error
text forever). This scans dashboard/src with comments stripped (so a doc comment may name a
route) for "/api/..." literals, treats each `${...}` template
hole and each `{param}` route segment as one path segment, ignores query strings, and requires a
match. Paths served by the dashboard's own Next.js route handlers (dashboard/src/app/api/) are
excluded: they are not the FastAPI app's.
"""

import re
from pathlib import Path

from src.api.main import app

REPO = Path(__file__).resolve().parents[3]
DASHBOARD_SRC = REPO / "dashboard" / "src"
# Block comments, and line comments whose `//` is not a URL scheme's (`http://`).
_COMMENT = re.compile(r"/\*.*?\*/|(?<!:)//[^\n]*", re.DOTALL)
# "/api/..." after a quote or a template hole (`${base}/api/...`); `${...}` stays in the path.
_PATH = re.compile(r"(/api/(?:[A-Za-z0-9_\-./]|\$\{[^}]*\})*)")


def _next_route_prefixes() -> set[str]:
    api_dir = DASHBOARD_SRC / "app" / "api"
    return {"/api/" + p.parent.relative_to(api_dir).as_posix() for p in api_dir.rglob("route.ts")}


def _dashboard_paths() -> dict[str, set[str]]:
    found: dict[str, set[str]] = {}
    for path in DASHBOARD_SRC.rglob("*.ts*"):
        if "/app/api/" in path.as_posix():
            continue
        for match in _PATH.findall(_COMMENT.sub("", path.read_text())):
            normalized = re.sub(r"\$\{[^}]*\}", "{}", match).rstrip("/")
            found.setdefault(normalized, set()).add(path.relative_to(REPO).as_posix())
    return found


def _route_patterns() -> list[re.Pattern[str]]:
    """GET paths from the OpenAPI schema: it carries every include prefix, whatever wrapper the
    installed FastAPI uses for included routers (app.routes hides them behind _IncludedRouter)."""
    patterns = []
    for path, methods in app.openapi()["paths"].items():
        if "get" in methods:
            template = re.escape(path.rstrip("/"))
            patterns.append(re.compile(re.sub(r"\\\{[^}]*\\\}", r"[^/]+", template)))
    return patterns


def test_every_dashboard_api_path_is_a_registered_get_route():
    patterns = _route_patterns()
    next_routes = _next_route_prefixes()
    missing = {
        path: files
        for path, files in _dashboard_paths().items()
        if path not in next_routes
        and not any(p.fullmatch(path.replace("{}", "x")) for p in patterns)
    }
    assert not missing, "dashboard calls API paths no route serves:\n" + "\n".join(
        f"  {path}: {', '.join(sorted(files))}" for path, files in sorted(missing.items())
    )
