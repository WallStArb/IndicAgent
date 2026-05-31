"""Tests for WorkerContext frozen dependency container."""

import dataclasses
import pathlib

import pytest

from src.core.ai.worker_context import WorkerContext


class TestWorkerContextConstruction:
    """Test construction and field defaults."""

    def test_construction_with_required_fields(self):
        """Construct with sentinel values for required fields; defaults are None."""
        sentinel_ctx = object()
        sentinel_chain = object()
        wc = WorkerContext(signal_context=sentinel_ctx, llm_chain=sentinel_chain)

        assert wc.signal_context is sentinel_ctx
        assert wc.llm_chain is sentinel_chain
        assert wc.db_pool is None
        assert wc.memory_client is None

    def test_construction_with_all_fields(self):
        """All four fields round-trip correctly when supplied."""
        sentinel_ctx = object()
        sentinel_chain = object()
        sentinel_pool = object()
        sentinel_mem = object()

        wc = WorkerContext(
            signal_context=sentinel_ctx,
            llm_chain=sentinel_chain,
            db_pool=sentinel_pool,
            memory_client=sentinel_mem,
        )

        assert wc.signal_context is sentinel_ctx
        assert wc.llm_chain is sentinel_chain
        assert wc.db_pool is sentinel_pool
        assert wc.memory_client is sentinel_mem

    def test_defaults_are_none(self):
        """db_pool and memory_client default to None."""
        wc = WorkerContext(signal_context="ctx", llm_chain="chain")
        assert wc.db_pool is None
        assert wc.memory_client is None


class TestWorkerContextImmutability:
    """Test that frozen=True prevents mutation."""

    def test_mutation_raises_frozen_instance_error(self):
        """Attempting to set any field after construction raises FrozenInstanceError."""
        wc = WorkerContext(signal_context="ctx", llm_chain="chain")
        with pytest.raises(dataclasses.FrozenInstanceError):
            wc.signal_context = "other"  # type: ignore[misc]

    def test_mutation_of_optional_field_raises(self):
        """Setting an optional field also raises FrozenInstanceError."""
        wc = WorkerContext(signal_context="ctx", llm_chain="chain")
        with pytest.raises(dataclasses.FrozenInstanceError):
            wc.db_pool = object()  # type: ignore[misc]


class TestWorkerContextIsDataclass:
    """Test dataclass structural properties."""

    def test_is_dataclass(self):
        """WorkerContext must be a dataclass."""
        assert dataclasses.is_dataclass(WorkerContext)

    def test_field_order(self):
        """Fields must be exactly: signal_context, llm_chain, db_pool, memory_client."""
        field_names = [f.name for f in dataclasses.fields(WorkerContext)]
        assert field_names == ["signal_context", "llm_chain", "db_pool", "memory_client"]

    def test_not_pydantic_model(self):
        """WorkerContext must not inherit from any Pydantic BaseModel."""
        try:
            from pydantic import BaseModel

            assert not issubclass(WorkerContext, BaseModel)
        except ImportError:
            pass  # pydantic not installed; test passes trivially


class TestWorkerContextRing0Boundary:
    """Test Ring 0 import cleanliness."""

    def test_no_runtime_signal_context_import(self):
        """Source file must not have a runtime import of SignalContext.

        SignalContext lives in Ring 1 (src.intelligence). WorkerContext is Ring 0
        and must not reference it at runtime. The field is typed Any precisely to
        avoid this coupling.
        """
        source_path = (
            pathlib.Path(__file__).parent.parent.parent.parent
            / "src"
            / "core"
            / "ai"
            / "worker_context.py"
        )
        source_text = source_path.read_text()

        # No bare import of SignalContext outside a TYPE_CHECKING block.
        # We check that 'import SignalContext' does not appear at all in the file
        # (TYPE_CHECKING guard prevents it from appearing as an import statement).
        assert (
            "import SignalContext" not in source_text
        ), "WorkerContext must not import SignalContext at all (not even under TYPE_CHECKING)"

    def test_no_base_model_in_source(self):
        """WorkerContext source must not reference BaseModel."""
        source_path = (
            pathlib.Path(__file__).parent.parent.parent.parent
            / "src"
            / "core"
            / "ai"
            / "worker_context.py"
        )
        source_text = source_path.read_text()
        assert "BaseModel" not in source_text, "WorkerContext must not use Pydantic BaseModel"
