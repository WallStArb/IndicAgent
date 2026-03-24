from __future__ import annotations

import importlib
import json
import logging

from src.intelligence.swarm.interface import IAlphaContributor

logger = logging.getLogger(__name__)


def load_contributors(config_path: str = "config/intelligence_contributors.json") -> list[IAlphaContributor]:
    """Factory to instantiate intelligence contributors from configuration."""
    try:
        with open(config_path) as f:
            config = json.load(f)
    except FileNotFoundError:
        raise FileNotFoundError(f"Contributors config not found: {config_path}")
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON in contributors config: {e}")

    contributors = []
    for entry in config.get("contributors", []):
        module_name = entry.get("module")
        class_name = entry.get("class")
        if not module_name or not class_name:
            logger.warning("Skipping contributor entry missing 'module' or 'class': %s", entry)
            continue
        try:
            module = importlib.import_module(module_name)
            contributor_class = getattr(module, class_name)
            contributors.append(contributor_class())
        except (ModuleNotFoundError, AttributeError, Exception) as e:
            logger.warning("Failed to load contributor %s.%s: %s", module_name, class_name, e)
            continue

    return contributors
