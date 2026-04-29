"""Ensure project root is on sys.path for `from src.*` imports.

Every service under services/ imports this to set up the Python path
before any `from src.*` imports. This replaces the per-file boilerplate:

    project_root = Path(__file__).parent.parent
    sys.path.insert(0, str(project_root))
"""
import sys
from pathlib import Path

_project_root = str(Path(__file__).resolve().parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)
