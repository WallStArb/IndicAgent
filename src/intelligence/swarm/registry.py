from __future__ import annotations

import importlib
import json

import structlog

from src.intelligence.swarm.interface import IAlphaContributor

logger = structlog.get_logger(__name__)


def load_contributors(config_path: str = "config/intelligence_contributors.json") -> list[IAlphaContributor]:
    """Factory to instantiate intelligence contributors from configuration.

    Returns empty list if config file does not exist (swarm is optional/shadow).
    """
    try:
        with open(config_path) as f:
            config = json.load(f)
    except FileNotFoundError:
        logger.info("swarm_contributors_config_missing", path=config_path)
        return []
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
