"""PluginStateManager — owns plugin state dicts, per-(symbol,tf) locks, and checkpoint file.

Key responsibilities:
- Single owner of _plugin_states dict keyed by (plugin_name, symbol, tf)
- Single owner of per-(symbol, tf) threading.Lock dict for bar serialisation
- Single writer of plugin_states in the checkpoint payload (HIGH finding 5)
- Background checkpoint loop with per-iteration error resilience (MEDIUM finding)
- write_checkpoint raises on I/O failure (Phase 086 contract D-15)
"""

from __future__ import annotations

import ast
import asyncio
import json
import threading
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import structlog

from src.core.state_serializer import (
    _ensure_default_models_registered,
    _tag_value,
    _untag_value,
)
from src.observability.metrics import counter

# ---------------------------------------------------------------------------
# Module-level constants (previously in intelligence_pipeline_agent.py)
# ---------------------------------------------------------------------------

_AGENT_VERSION = "v1"

_CHECKPOINT_PATH = Path("cache/pipeline_checkpoint.json")

_CHECKPOINT_FIELDS: tuple[str, ...] = (
    "plugin_states",
    "kalman_state",
    "tod_priors",
    "last_bar_offset",
    "setup_last_fire",
)


def _restore_tuple_key(k: Any) -> Any:
    """Convert stringified tuple keys back to tuples for state restoration."""
    if isinstance(k, str):
        try:
            parsed = ast.literal_eval(k)
            if isinstance(parsed, tuple):
                return parsed
        except (ValueError, SyntaxError):
            pass
    return k


class PluginStateManager:
    """Owns plugin state dicts (keyed by (plugin_name, symbol, tf)), per-(symbol,tf)
    threading locks, and the checkpoint file.

    This class is the SINGLE writer of plugin_states in the checkpoint payload.
    Callers pass cross-owned fields via extra_state; plugin_states must NOT appear there.
    """

    def __init__(self, checkpoint_path: Path) -> None:
        self._checkpoint_path = checkpoint_path
        # (plugin_name, symbol, tf) -> dict
        self._plugin_states: dict[tuple, dict] = {}
        # (symbol, tf) -> threading.Lock  — NOT per-plugin; one lock per bar-slot
        self._locks: dict[tuple, threading.Lock] = {}
        self._logger = structlog.get_logger(__name__)
        self._checkpoint_failures = counter(
            "intelligence_pipeline_checkpoint_failures_total",
            "Checkpoint loop iteration failures",
        )

    # ------------------------------------------------------------------
    # Read API
    # ------------------------------------------------------------------

    def get_state(self, key: tuple) -> dict:
        """Return state for a single (plugin_name, symbol, tf) key.

        Returns empty dict if the key is not found.
        """
        return self._plugin_states.get(key, {})

    def get_all_states_for(self, symbol: str, tf: str) -> dict[str, dict]:
        """Return mapping of plugin_name -> state for all plugins matching (symbol, tf).

        This is the per-bar read API consumed by the plugin executor (HIGH finding 1).
        Preserves full (plugin_name, symbol, tf) keying internally while exposing a
        plugin-name-keyed view to the caller.
        """
        return {
            plugin_name: state
            for (plugin_name, s, t), state in self._plugin_states.items()
            if s == symbol and t == tf
        }

    def get_lock(self, key: tuple) -> threading.Lock:
        """Lazy-init and return the threading.Lock for a (symbol, tf) bar-slot.

        Lock keying is (symbol, tf) — one lock per bar-slot, NOT per-plugin.
        This matches the original god class _get_state_lock behaviour.
        """
        if key not in self._locks:
            self._locks[key] = threading.Lock()
        return self._locks[key]

    def get_all_states(self) -> dict:
        """Return a snapshot of the full _plugin_states dict.

        Used internally by write_checkpoint and in tests.
        """
        return dict(self._plugin_states)

    # ------------------------------------------------------------------
    # Write API
    # ------------------------------------------------------------------

    def update(self, key: tuple, state: dict) -> None:
        """Set state for a single (plugin_name, symbol, tf) key."""
        self._plugin_states[key] = state

    def update_batch(self, state_updates: dict) -> None:
        """Merge a batch of state updates keyed by (plugin_name, symbol, tf).

        Required for Plan 04 (PluginExecutor returns a full batch after tier execution).
        The updates dict uses the same keying as _collect_plugin_results output.
        """
        self._plugin_states.update(state_updates)

    # ------------------------------------------------------------------
    # Checkpoint write
    # ------------------------------------------------------------------

    def write_checkpoint(self, extra_state: dict) -> None:
        """Write the checkpoint file atomically via .tmp + rename.

        SINGLE WRITER CONTRACT (HIGH finding 5): plugin_states is always written
        from self._plugin_states. Callers MUST NOT include a 'plugin_states' key
        in extra_state — doing so raises ValueError immediately.

        Phase 086 contract D-15: raises on I/O failure. The internal background loop
        wrapper catches the raise so the task stays alive; direct callers (teardown)
        get the exception propagated.
        """
        if "plugin_states" in extra_state:
            raise ValueError(
                "extra_state must not contain 'plugin_states' — "
                "PluginStateManager is the single writer"
            )
        payload: dict[str, Any] = {
            "version": _AGENT_VERSION,
            "ts": datetime.now(UTC).isoformat(),
            "plugin_states": _tag_value(self._plugin_states),
        }
        for k, v in extra_state.items():
            payload[k] = _tag_value(v)
        tmp = self._checkpoint_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload))
        tmp.rename(self._checkpoint_path)
        self._logger.info("state.checkpoint_written", path=str(self._checkpoint_path))

    # ------------------------------------------------------------------
    # Checkpoint read
    # ------------------------------------------------------------------

    async def read_checkpoint(self) -> dict | None:
        """Restore plugin_states from the checkpoint file and return cross-owned fields.

        Restores self._plugin_states internally (tuple-key restoration via
        _restore_tuple_key).  Returns a dict containing the remaining
        _CHECKPOINT_FIELDS (excluding 'plugin_states') for the orchestrator to
        distribute to its own attributes:
            {"kalman_state": ..., "tod_priors": ..., "last_bar_offset": ...,
             "setup_last_fire": ...}

        Returns None on file-miss or version mismatch.
        """
        try:
            raw_text = self._checkpoint_path.read_text()
        except FileNotFoundError:
            self._logger.info("state.checkpoint_miss", note="starting fresh")
            return None

        try:
            _ensure_default_models_registered()
            raw = json.loads(raw_text)
            if raw.get("version") != _AGENT_VERSION:
                self._logger.warning("state.checkpoint_version_mismatch", found=raw.get("version"))
                return None

            # Restore plugin_states internally — tuple-key restoration
            restored_states: dict[tuple, dict] = {}
            for k, v in _untag_value(raw.get("plugin_states", {})).items():
                restored_states[_restore_tuple_key(k)] = v
            self._plugin_states = restored_states

            extra_fields: dict[str, Any] = {}
            for field in _CHECKPOINT_FIELDS:
                if field == "plugin_states":
                    continue
                raw_field = _untag_value(raw.get(field, {}))
                if isinstance(raw_field, dict):
                    raw_field = {_restore_tuple_key(k): v for k, v in raw_field.items()}
                extra_fields[field] = raw_field

            self._logger.info(
                "state.checkpoint_restored",
                ts=raw.get("ts"),
                path=str(self._checkpoint_path),
            )
            return extra_fields

        except Exception as exc:
            self._logger.warning("state.checkpoint_read_failed", error=str(exc))
            return None

    # ------------------------------------------------------------------
    # Background checkpoint loop
    # ------------------------------------------------------------------

    def start_checkpoint_loop(
        self, interval_sec: int, get_extra_fn: Callable[[], dict]
    ) -> asyncio.Task:
        """Create and return an asyncio.Task running the background checkpoint loop.

        The loop catches per-iteration exceptions and logs+counts them (MEDIUM finding:
        a single transient I/O failure must not silently kill all future checkpoints).
        asyncio.CancelledError is re-raised so cancellation propagates correctly.

        write_checkpoint itself still raises on failure (D-15 contract preserved for
        direct callers); the loop wrapper here catches that raise so the task lives.

        Args:
            interval_sec: Seconds between checkpoint attempts.
            get_extra_fn: Zero-argument callable returning the cross-owned extra_state
                dict (must not contain 'plugin_states').
        """

        async def _loop() -> None:
            while True:
                try:
                    await asyncio.sleep(interval_sec)
                    extra = get_extra_fn()
                    self.write_checkpoint(extra)
                except asyncio.CancelledError:
                    raise  # propagate cancellation — do not swallow
                except Exception as exc:
                    self._checkpoint_failures.add(1)
                    self._logger.exception("checkpoint_loop.iteration_failed", error=str(exc))
                    # continue — do not let one transient error kill the loop forever

        return asyncio.create_task(_loop())
