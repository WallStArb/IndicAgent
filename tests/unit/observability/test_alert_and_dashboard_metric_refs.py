"""Every metric an alert rule or a Grafana dashboard queries is declared in code.

A rule or panel on a metric nothing emits never fires and never draws, silently: todo 509 found
six Prometheus rules, two Grafana rules and three dashboards still watching the deleted v2.x
path, and a gap-fill DLQ panel and rule querying a counter without the `_total` the exporter
adds. Prometheus is no witness (it keeps a dead series until retention drops it), so the code
is: a metric counts as declared when src/, services/ or scripts/ creates it, by literal name or
f-string template, and the query uses the series name the exporter publishes for its kind (a
counter's `_total`, a histogram's `_bucket`/`_sum`/`_count`, a gauge's bare name). Exporter
metrics (node_exporter, postgres_exporter, Prometheus itself) are allowed by prefix.
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[3]
RULE_FILES = (
    REPO / "production/alertmanager-rules.yml",
    *sorted((REPO / "production/grafana/provisioning/alerting").glob("*.yml")),
)
# Python that sends PromQL to Prometheus: (file, function called with the query string).
PYTHON_QUERIES = (
    (REPO / "services/service_auditor.py", "_query_prometheus"),
    (REPO / "src/api/routes/health.py", "_query"),
)
_FACTORIES = {
    "create_counter": "counter",
    "create_up_down_counter": "gauge",
    "create_gauge": "gauge",
    "create_observable_gauge": "gauge",
    "create_histogram": "histogram",
    "point_gauge": "gauge",
    "counter": "counter",
    "gauge": "gauge",
    "histogram": "histogram",
    "_get_or_create_counter": "counter",
    "_get_or_create_gauge": "gauge",
    "_get_or_create_histogram": "histogram",
}
DASHBOARDS = sorted((REPO / "production/grafana/dashboards").glob("*.json"))
EXPORTER_PREFIXES = (
    "node_",
    "pg_",
    "process_",
    "go_",
    "prometheus_",
    "redpanda_",
    "container_",
    "otelcol_",
    "timescaledb_",
)
EXPORTER_NAMES = {"up", "target_info", "scrape_duration_seconds", "scrape_samples_scraped"}
_PROMQL_WORDS = {
    "sum", "min", "max", "avg", "count", "stddev", "stdvar", "topk", "bottomk", "quantile",
    "count_values", "group", "by", "without", "on", "ignoring", "group_left", "group_right",
    "and", "or", "unless", "bool", "offset", "rate", "irate", "increase", "delta", "idelta",
    "deriv", "predict_linear", "histogram_quantile", "abs", "absent", "absent_over_time",
    "ceil", "floor", "round", "clamp", "clamp_min", "clamp_max", "changes", "resets", "scalar",
    "vector", "sort", "sort_desc", "time", "timestamp", "label_replace", "label_join", "inf",
    "nan", "day_of_week", "hour", "minute", "month", "year",
}  # fmt: skip
_SUFFIXES_BY_KIND = {
    "counter": ("_total",),
    "histogram": ("_bucket", "_sum", "_count"),
    "gauge": ("",),
}


def _exprs_in(node: object) -> list[str]:
    """Every PromQL string at any depth: `expr` keys in rule YAML and dashboard targets, and a
    dashboard template variable's `query`/`definition` (label_values(metric, label) and the
    like)."""
    if isinstance(node, dict):
        found = [v for k, v in node.items() if k == "expr" and isinstance(v, str)]
        if "templating" in node:
            for var in node["templating"].get("list", []):
                for key in ("query", "definition"):
                    value = var.get(key)
                    if isinstance(value, str):
                        found.append(value)
                    elif isinstance(value, dict) and isinstance(value.get("query"), str):
                        found.append(value["query"])
        return found + [e for v in node.values() for e in _exprs_in(v)]
    if isinstance(node, list):
        return [e for v in node for e in _exprs_in(v)]
    return []


def _metric_names(expr: str) -> set[str]:
    # Grafana variable functions name a metric and then a label: keep only the metric.
    expr = re.sub(r"\blabel_values\(\s*([^,)]*)(?:,[^)]*)?\)", r"\1", expr)
    expr = re.sub(r"\b(?:query_result|metrics|label_names)\(", "(", expr)
    expr = re.sub(r'"(?:[^"\\]|\\.)*"', "", expr)
    expr = re.sub(r"\{[^}]*\}|\[[^\]]*\]", "", expr)
    expr = re.sub(r"\b(?:by|without|on|ignoring|group_left|group_right)\s*\([^)]*\)", "", expr)
    tokens = set(re.findall(r"\b[a-zA-Z_:][a-zA-Z0-9_:]*\b", expr))
    names = {t for t in tokens if t not in _PROMQL_WORDS and not t.endswith("_over_time")}
    return {t for t in names if "_" in t} | ({"up"} & tokens)


def _writer_snakes() -> list[str]:
    """agent_snake of every BaseWriter subclass in services/ (BaseDaemon names a daemon by its
    snake-cased class name), so base_writer.py's f-string metric names expand to real writers
    only, never to a wildcard that would also accept a deleted one."""
    from src.core.agent.base import _to_snake_case

    bases: dict[str, set[str]] = {}
    for path in (REPO / "services").rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.ClassDef):
                bases[node.name] = {getattr(b, "id", getattr(b, "attr", "")) for b in node.bases}

    def is_writer(cls: str, seen: frozenset[str] = frozenset()) -> bool:
        parents = bases.get(cls, set())
        return "BaseWriter" in parents or any(
            p not in seen and is_writer(p, seen | {cls}) for p in parents
        )

    return sorted(_to_snake_case(c) for c in bases if is_writer(c))


def _exported_patterns() -> list[re.Pattern[str]]:
    """One pattern per exported series of every metric-factory call in src, services, scripts."""
    writers = "(?:" + "|".join(map(re.escape, _writer_snakes())) + ")"
    patterns: list[re.Pattern[str]] = []
    for root in ("src", "services", "scripts"):
        for path in (REPO / root).rglob("*.py"):
            for node in ast.walk(ast.parse(path.read_text())):
                if not (isinstance(node, ast.Call) and node.args):
                    continue
                func = node.func
                kind = _FACTORIES.get(
                    func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
                )
                first = node.args[0]
                if kind is None:
                    continue
                if isinstance(first, ast.Constant) and isinstance(first.value, str):
                    stem = re.escape(first.value)
                elif isinstance(first, ast.JoinedStr):
                    stem = "".join(
                        re.escape(v.value) if isinstance(v, ast.Constant) else writers
                        for v in first.values
                    )
                else:
                    continue
                if kind == "counter":
                    stem = re.sub(r"_total$", "", stem)
                patterns += [re.compile(stem + re.escape(s)) for s in _SUFFIXES_BY_KIND[kind]]
    return patterns


def _python_queries() -> list[str]:
    queries = []
    for path, func_name in PYTHON_QUERIES:
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Call):
                name = getattr(node.func, "attr", getattr(node.func, "id", ""))
                for arg in node.args:
                    if (
                        name == func_name
                        and isinstance(arg, ast.Constant)
                        and isinstance(arg.value, str)
                    ):
                        queries.append((path, arg.value))
    return queries


def test_every_queried_metric_is_declared_in_code():
    patterns = _exported_patterns()
    queried: dict[str, set[str]] = {}
    sources = [(p, yaml.safe_load(p.read_text())) for p in RULE_FILES]
    sources += [(p, json.loads(p.read_text())) for p in DASHBOARDS]
    exprs = [(path, e) for path, doc in sources for e in _exprs_in(doc)] + _python_queries()
    for path, expr in exprs:
        for metric in _metric_names(expr):
            queried.setdefault(metric, set()).add(path.name)

    def declared(metric: str) -> bool:
        if metric in EXPORTER_NAMES or metric.startswith(EXPORTER_PREFIXES):
            return True
        return any(p.fullmatch(metric) for p in patterns)

    undeclared = {m: sorted(files) for m, files in queried.items() if not declared(m)}
    assert not undeclared, "metrics queried but declared nowhere in code:\n" + "\n".join(
        f"  {m}: {', '.join(files)}" for m, files in sorted(undeclared.items())
    )
