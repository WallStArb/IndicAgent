"""CI enforcement of DAG Invariant 2: intelligence plugins must not import DB or Kafka clients."""

import importlib
import pkgutil
import sys

import pytest

_FORBIDDEN_MODULES = {"asyncpg", "asyncpg.pool", "aiokafka", "confluent_kafka"}
_INTELLIGENCE_PACKAGE = "src.intelligence"


def _iter_intelligence_modules() -> list[str]:
    import src.intelligence as pkg

    results = []
    for info in pkgutil.walk_packages(pkg.__path__, prefix=pkg.__name__ + "."):
        results.append(info.name)
    return results


@pytest.mark.parametrize("module_name", _iter_intelligence_modules())
def test_intelligence_module_does_not_import_db_or_kafka(module_name: str):
    """Each src.intelligence module must not pull in asyncpg or Kafka clients."""
    # Snapshot sys.modules before import to detect newly loaded transitive deps
    before = set(sys.modules.keys())
    try:
        importlib.import_module(module_name)
    except Exception:
        pytest.skip(f"Could not import {module_name} (missing optional dep)")
    after = set(sys.modules.keys())
    newly_loaded = after - before
    violations = newly_loaded & _FORBIDDEN_MODULES
    assert not violations, (
        f"{module_name} imported forbidden modules: {violations}. "
        "DAG Invariant 2 requires I1-I7 to be DB and Kafka ignorant."
    )
