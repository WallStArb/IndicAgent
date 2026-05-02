"""Architecture boundary tests for DAG and compute/persistence separation.

These tests do not prove the architecture is perfect. They prevent new agents
from quietly bypassing the documented role boundaries while legacy exceptions
are retired deliberately.
"""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SERVICES = ROOT / "services"

DB_IMPORT_PREFIXES = (
    "asyncpg",
    "psycopg",
    "psycopg2",
    "sqlalchemy",
    "src.core.database_manager",
    "src.persistence.repository",
)

DB_ALLOWED_ROLE_MARKERS = (
    "_writer_agent.py",
    "_auditor_agent.py",
    "llm_writer_service.py",
    "bar_writer_agent.py",
    "contract_metadata_writer_agent.py",
    "feature_writer_agent.py",
    "feature_snapshot_writer_agent.py",
    "graduation_writer_agent.py",
    "lifecycle_writer_agent.py",
    "lineage_writer_agent.py",
    "signal_metrics_writer_agent.py",
    "signal_writer_agent.py",
)

# Existing architecture debt. Do not add to this list without an explicit
# migration plan in docs/plans. Removing entries is encouraged.
LEGACY_DB_ACCESS_EXCEPTIONS = {
    "cross_asset_service.py": "seeds cross-asset history from DB before stream-only refactor",
    "graduation_compute_agent.py": "legacy compute reads graduation state directly",
    "intelligence_pipeline_agent.py": "legacy warmup/reliability reads before checkpoint/read-model refactor",
    "macro_compute_agent.py": "legacy compute persists macro features directly",
    "ml_data_quality_agent.py": "timer auditor/ML service reads training data quality state",
    "ml_discovery_agent.py": "timer ML service reads feature/outcome history",
    "ml_orchestrator_agent.py": "timer ML service reads model/training state",
    "signal_metrics_compute_agent.py": "legacy compute reads signal_ledger before read-model split",
    "signal_tracker_compute_agent.py": "legacy lifecycle bootstrap reads/writes before pure transition split",
}

PROTECTED_ROLE_MARKERS = (
    "_compute_agent.py",
    "_provider_agent.py",
    "_merger_agent.py",
    "_tracker_agent.py",
    "_generator_agent.py",
)


def _imports_for(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(), filename=str(path))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)
    return imports


def _has_db_import(path: Path) -> bool:
    return any(
        imported == prefix or imported.startswith(f"{prefix}.")
        for imported in _imports_for(path)
        for prefix in DB_IMPORT_PREFIXES
    )


def _is_db_allowed_role(path: Path) -> bool:
    return path.name.endswith(DB_ALLOWED_ROLE_MARKERS)


def _is_protected_role(path: Path) -> bool:
    return path.name.endswith(PROTECTED_ROLE_MARKERS)


def test_new_compute_provider_merger_tracker_agents_do_not_import_db_access() -> None:
    """Protected stream/compute roles must not add new direct DB dependencies."""
    offenders: list[str] = []
    for path in sorted(SERVICES.glob("*.py")):
        if not _is_protected_role(path):
            continue
        if path.name in LEGACY_DB_ACCESS_EXCEPTIONS:
            continue
        if _has_db_import(path):
            offenders.append(path.relative_to(ROOT).as_posix())

    assert offenders == [], (
        "Compute/provider/merger/tracker agents must stay DB-ignorant. "
        "Use a WriterAgent, ReadModelAgent, checkpoint topic, or documented legacy exception. "
        f"Offenders: {offenders}"
    )


def test_non_writer_db_imports_are_either_auditors_or_documented_legacy_exceptions() -> None:
    """Any service with DB access must be role-allowed or explicitly documented debt."""
    offenders: list[str] = []
    for path in sorted(SERVICES.glob("*.py")):
        if not _has_db_import(path):
            continue
        if _is_db_allowed_role(path):
            continue
        if path.name in LEGACY_DB_ACCESS_EXCEPTIONS:
            continue
        offenders.append(path.relative_to(ROOT).as_posix())

    assert offenders == [], (
        "Services with DB imports must be Writer/Auditor roles or documented legacy exceptions. "
        f"Offenders: {offenders}"
    )


def test_legacy_db_access_exceptions_still_exist_and_are_not_stale() -> None:
    """Keep the legacy exception list honest as files are renamed or retired."""
    missing = [
        name for name in sorted(LEGACY_DB_ACCESS_EXCEPTIONS) if not (SERVICES / name).exists()
    ]
    assert missing == []
