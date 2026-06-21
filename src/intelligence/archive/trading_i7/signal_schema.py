"""Redirect: signal_schema lives in src/intelligence/trading/ (not archived)."""

from src.intelligence.trading.signal_schema import *  # noqa: F401, F403
from src.intelligence.trading.signal_schema import (  # noqa: F401
    REQUIRED_PIPELINE_FIELDS,
    REQUIRED_SIGNAL_FIELDS,
    SIGNAL_SCHEMA_VERSION,
    make_signal_from_frame,
    make_signal_id,
    validate_signal,
)
