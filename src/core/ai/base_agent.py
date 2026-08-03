"""BaseAIWorker — universal base class for all AI agents."""

from __future__ import annotations

import asyncio
import time
from abc import ABC, abstractmethod
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, ClassVar, Protocol, runtime_checkable
from uuid import UUID, uuid4

import structlog
from opentelemetry.trace import StatusCode
from pydantic import BaseModel

from src.core.agent.base import BaseDaemon
from src.core.ai.output import AgentOutput
from src.core.service_utils import format_iso_ts
from src.observability.metrics import (
    AI_AGENT_DURATION_MS,
    AI_AGENT_ERRORS_TOTAL,
    AI_AGENT_INVOCATIONS_TOTAL,
    LLM_EMPTY_RESPONSES,
    LLM_PARSE_FAILURES,
)
from src.observability.spans import ATTR_AGENT_ID, ATTR_SYMBOL, ATTR_TF, observed_span

if TYPE_CHECKING:
    from src.core.ai.agent_dependencies import AgentDependencies
    from src.core.ai.lineage import LineageRecorder
    from src.core.llm.chain import LLMProviderChain
    from src.core.memory.client import MemoryClient  # ring0-ok: TYPE_CHECKING only, not at runtime
    from src.intelligence.ai.context import (  # ring0-ok: TYPE_CHECKING only, not at runtime
        SignalContext,
        Tier,
    )

logger = structlog.get_logger(__name__)


@runtime_checkable
class IAIAgent(Protocol):
    """Protocol for AI agents — enables isinstance() checks and type hints.

    All AI agents must implement this interface. BaseAIWorker provides
    the default implementation; subclasses only override _compute().
    """

    agent_id: str
    group: str
    tiers_needed: frozenset[Tier]
    shadow_only: bool
    latency_budget_ms: float

    async def compute(self, context: SignalContext) -> AgentOutput: ...
    async def _compute(self, context: SignalContext) -> AgentOutput: ...


class BaseAIWorker(BaseDaemon, ABC):
    """Abstract base for all AI agents.

    Provides:
    - Wall-clock timing capture in compute() wrapper
    - asyncio.wait_for timeout enforcement (configurable via latency_budget_ms)
    - Exception handling with neutral AgentOutput fallback
    - Extension hooks (_on_error, _on_guardrail_violation, _audit_payload)

    Subclasses must implement:
    - _compute(context: SignalContext) -> AgentOutput

    Inherits from BaseDaemon for full lifecycle:
    - SIGTERM/SIGINT handling
    - Structured logging (self.logger)
    - OTel tracing (self.tracer)

    D-51: Latency budgets configurable via latency_budget_ms class attribute.
    Default 5000ms ceiling; tuned per agent (alpha: 3000ms, narrative: 60000ms).
    """

    agent_id: str = ""  # override in subclass
    group: str = ""  # "alpha", "narrative", "risk"
    tiers_needed: frozenset[Tier] = frozenset()
    shadow_only: bool = True  # D-37: always True, graduation_loop flips it
    latency_budget_ms: float = 5000.0  # D-51: default ceiling, tuned per agent
    prompt_version: str = ""  # override in subclass, e.g. "skeptic_v2"

    # D-10: Universal typed-output opt-in. Subclasses set result_type to a
    # pydantic BaseModel subclass to enable _run_typed(). None = opted out.
    # TODO: narrow _run_typed() to a TypedOutputMixin so the None guard is enforced
    # by the type system instead of at call time, and non-typed agents don't inherit it.
    result_type: ClassVar[type[BaseModel] | None] = None

    # D-12: Conservative token ceiling used when _run_typed() caller passes
    # max_tokens=None. Matches compute-cost discipline from CONTEXT.md.
    _default_max_tokens: ClassVar[int] = 2048

    def __init__(
        self,
        *,
        dependencies: AgentDependencies | None = None,
        name: str | None = None,
        memory_client: MemoryClient | None = None,
        **kwargs: Any,
    ) -> None:
        # If name not provided, use class name or agent_id
        if name is None:
            name = self.__class__.__name__
        super().__init__(name=name, **kwargs)
        self._timeout_s = self.latency_budget_ms / 1000.0
        self._lineage: LineageRecorder | None = None
        self._llm: LLMProviderChain | None = None
        self._memory_client: MemoryClient | None = memory_client
        self._agent_labels: dict[str, str] = {"agent_id": self.agent_id, "group": self.group}

    def set_memory_client(self, memory_client: MemoryClient | None) -> None:
        """Inject or replace the MemoryClient after construction.

        Called by the group coordinator (e.g. AlphaSwarm) after building its
        MemoryClient so that agents receive the live client without requiring
        every agent constructor signature to accept it. Setting None is valid
        and corresponds to AGENT_MEMORY_ENABLED=False.
        """
        self._memory_client = memory_client

    def __init_subclass__(cls, **kwargs: Any) -> None:
        """Validate result_type and self-register agent in _REGISTRY.

        - result_type validation: Fails immediately when a subclass sets result_type
          to a non-BaseModel value (REVIEWS LOW item 10).
        - Self-registration: Registers agents by agent_id in _REGISTRY at class-
          definition time. BaseAIWorker (agent_id="") and Evaluator are skipped.
          Duplicate agent_ids raise RegistryError.
        """
        super().__init_subclass__(**kwargs)

        # result_type validation (existing)
        if cls.result_type is not None and not (
            isinstance(cls.result_type, type) and issubclass(cls.result_type, BaseModel)
        ):
            raise TypeError(
                f"{cls.__name__}.result_type must be a pydantic BaseModel subclass or None,"
                f" got {cls.result_type!r}"
            )

        # Self-registration in _REGISTRY (Phase 096)
        if cls.agent_id:
            # Lazy import avoids circular import at module load
            from src.core.ai.registry import _REGISTRY, RegistryError

            if cls.agent_id in _REGISTRY and _REGISTRY[cls.agent_id] is not cls:
                raise RegistryError(
                    f"Duplicate agent_id '{cls.agent_id}': "
                    f"{_REGISTRY[cls.agent_id].__name__} vs {cls.__name__}"
                )
            _REGISTRY[cls.agent_id] = cls

    async def compute(self, context: SignalContext) -> AgentOutput:
        """Run _compute() with timing capture + exception safety.

        Returns AgentOutput with latency_ms populated.
        Returns neutral AgentOutput on timeout or exception.
        """
        with self.tracer.start_as_current_span(
            "agent.compute",
            attributes={
                ATTR_AGENT_ID: self.agent_id,
                "group": self.group,
                ATTR_SYMBOL: context.symbol,
                ATTR_TF: context.timeframe,
            },
        ) as span:
            t0 = time.monotonic()
            try:
                result = await asyncio.wait_for(
                    self._compute(context),
                    timeout=self._timeout_s,
                )
                latency_ms = (time.monotonic() - t0) * 1000
                self._record_metrics("success", latency_ms)
                span.set_attribute("status", "success")
                span.set_attribute("latency_ms", round(latency_ms, 1))
                return result.model_copy(update={"latency_ms": latency_ms})

            except TimeoutError as error:
                latency_ms = (time.monotonic() - t0) * 1000
                self._record_metrics("timeout", latency_ms)
                span.set_status(StatusCode.ERROR, str(error))
                span.record_exception(error)
                span.set_attribute("status", "timeout")
                span.set_attribute("latency_ms", round(latency_ms, 1))
                # Base-class infra events use the "ai_worker." role prefix (not a per-service agent_id) — intentional exception to the {derived_agent_id}.action convention.
                logger.warning(
                    "ai_worker.timeout",
                    agent_id=self.agent_id,
                    timeout_s=self._timeout_s,
                    latency_ms=round(latency_ms, 1),
                )
                await self._on_error(TimeoutError(f"timeout after {self._timeout_s:.1f}s"))
                return self._neutral(
                    error=f"timeout after {self._timeout_s:.1f}s", latency_ms=latency_ms
                )

            except Exception as error:
                latency_ms = (time.monotonic() - t0) * 1000
                self._record_metrics("error", latency_ms)
                span.set_status(StatusCode.ERROR, str(error))
                span.record_exception(error)
                span.set_attribute("status", "error")
                span.set_attribute("error", str(error)[:200])
                logger.exception(
                    "ai_worker.exception",
                    agent_id=self.agent_id,
                    error=str(error),
                )
                await self._on_error(error)
                return self._neutral(error=str(error), latency_ms=latency_ms)

    async def _run(self) -> None:
        """BaseAIWorker subclasses are compute objects driven by BaseGroupCoordinator.

        They must not be started as standalone agents. This satisfies BaseDaemon's
        abstract requirement while failing loudly if misused.
        """
        raise RuntimeError(
            f"{self.__class__.__name__} is a compute agent and cannot be run standalone. "
            "Use within a BaseGroupCoordinator."
        )

    @abstractmethod
    async def _compute(self, context: SignalContext) -> AgentOutput:
        """Implement the agent's core computation logic.

        Subclasses must override this method. Returns AgentOutput with
        payload dict containing agent-specific results.
        """
        ...

    def _record_metrics(self, status: str, latency_ms: float) -> None:
        AI_AGENT_INVOCATIONS_TOTAL.add(1, {**self._agent_labels, "status": status})
        AI_AGENT_DURATION_MS.record(latency_ms, self._agent_labels)

    def _neutral(self, error: str, latency_ms: float) -> AgentOutput:
        """Return neutral AgentOutput for error/timeout cases."""
        return AgentOutput(
            agent_id=self.agent_id,
            group=self.group,
            output_type="neutral",
            payload={},
            shadow_only=self.shadow_only,
            latency_ms=latency_ms,
            error=error,
        )

    def _require_llm(self) -> None:
        if self._llm is None:
            raise RuntimeError(
                f"{self.__class__.__name__} ({self.agent_id}): _llm is None — "
                "agent must be constructed inside _setup() after super()._setup()"
            )

    def _require_prompt_version(self) -> None:
        """Fail loudly if prompt_version is unset (CLAUDE.md: every BaseAIWorker
        subclass must set it from ACTIVE_VERSION). Checked in _build_audit_context(),
        not __init_subclass__, so non-LLM Evaluator subclasses (e.g. MLEvaluator)
        that never build an audit context have no obligation to set it."""
        if not self.prompt_version:
            raise RuntimeError(
                f"{self.__class__.__name__} ({self.agent_id}): prompt_version is empty — "
                "set the class attribute from your agent's ACTIVE_VERSION constant "
                "before calling _llm_generate()/_llm_generate_structured()"
            )

    def _agent_span(self, name: str, context: SignalContext, **extra):
        """Return an observed_span pre-populated with standard agent attributes."""
        return observed_span(
            name,
            tracer=self.tracer,
            agent_id=self.agent_id,
            symbol=context.symbol,
            tf=context.timeframe,
            **extra,
        )

    def _build_audit_context(
        self, context: SignalContext, prompt: str, call_id: str, *, include_called_at: bool = True
    ) -> dict[str, Any]:
        """Build the base audit_context dict for an LLM call.

        Single choke point for all three LLM-invoking methods (_llm_generate,
        _llm_generate_structured, _run_typed) -- _require_prompt_version() is
        enforced here rather than at each call site so no current or future
        caller of this method can bypass it.
        """
        self._require_prompt_version()
        audit_context: dict[str, Any] = {
            "call_id": call_id,
            "symbol": context.symbol,
            "signal_id": str(context.signal_id) if context.signal_id else None,
            "group_name": self.group,
            "agent_id": self.agent_id,
            "prompt_version": self.prompt_version,
            "timeframe": context.timeframe,
            "prompt": prompt,
            "succeeded": True,
            "parse_success": True,
        }
        if include_called_at:
            audit_context["called_at"] = format_iso_ts(datetime.now(UTC))
        if context.smc is not None:
            regime = getattr(context.smc, "hmm_regime", None)
            if regime is not None:
                audit_context["regime"] = str(int(regime))
        return audit_context

    async def _llm_generate(
        self,
        context: SignalContext,
        prompt: str,
        system: str,
        max_tokens: int,
        timeout: float,
        model: str = "default",
        extra_audit: dict | None = None,
    ) -> tuple[str | None, str]:
        """Generate LLM response with automatic audit trail.

        Wraps self._llm.generate() with auto-injected audit_context so every
        LLM call is captured for model scoring. Agents MUST use this instead of
        calling self._llm.generate() directly — instrumentation should be
        impossible to forget.

        Returns (response, call_id). call_id is used by agents to publish
        corrective parse_success=False updates via _report_parse_failure().
        """
        self._require_llm()
        async with self._agent_span("agent.llm_generate", context, model=model) as span:
            call_id = str(uuid4())
            audit_context = self._build_audit_context(context, prompt, call_id)

            if extra_audit:
                audit_context.update(extra_audit)

            result = await self._llm.generate(
                prompt=prompt,
                system=system,
                max_tokens=max_tokens,
                timeout=timeout,
                model=model,
                audit_context=audit_context,
            )
            if result is None:
                span.set_attribute("llm.empty_response", True)
                LLM_EMPTY_RESPONSES.add(1, self._agent_labels)
            return result, call_id

    async def _llm_generate_structured(
        self,
        context: SignalContext,
        prompt: str,
        system: str,
        response_model: type[BaseModel],
        max_tokens: int,
        timeout: float,
        extra_audit: dict | None = None,
    ) -> tuple[BaseModel | None, str]:
        """Generate structured output via instructor with automatic audit trail.

        Mirrors _llm_generate() -- same audit context, same span setup, same call_id
        returned for _report_parse_failure(). Supports extra_audit kwarg for additional
        audit fields, same as _llm_generate() (M4).

        Returns (result, call_id). result is None when instructor exhausts retries.
        Caller must invoke _report_parse_failure(call_id) on None result.
        """
        self._require_llm()
        async with self._agent_span("agent.llm_generate_structured", context) as span:
            call_id = str(uuid4())
            audit_context = self._build_audit_context(context, prompt, call_id)

            # Do NOT pre-merge extra_audit here (WR-04): chain.generate_structured
            # already merges extra_audit into the audit row. Pre-merging here and then
            # passing extra_audit again would apply the fields twice. Let the chain
            # handle merging via its extra_audit parameter.

            result = await self._llm.generate_structured(
                prompt=prompt,
                system=system,
                response_model=response_model,
                max_tokens=max_tokens,
                timeout=timeout,
                audit_context=audit_context,
                extra_audit=extra_audit,
            )
            if result is None:
                span.set_attribute("llm.empty_response", True)
                LLM_EMPTY_RESPONSES.add(1, self._agent_labels)
            return result, call_id

    async def _run_typed(
        self,
        context: SignalContext,
        prompt: str,
        system: str,
        max_tokens: int | None = None,
    ) -> BaseModel:
        """Execute a typed LLM call, returning a validated result_type instance.

        Universal opt-in path for agents that declare result_type (D-10 through D-13).
        Constructs a single-use WorkerContext + LLMAdapter per call, runs a
        pydantic_ai.Agent with output_type=result_type, and returns the validated
        result_type instance. Caller is responsible for converting to AgentOutput.

        Timeout is always derived from self._timeout_s (computed from latency_budget_ms)
        so the latency budget is impossible to forget (D-11).

        max_tokens=None is resolved to self._default_max_tokens before the adapter is
        built so chain.generate() always receives an int (REVIEWS MEDIUM fix).

        Raises RuntimeError immediately if result_type is None — subclass must declare
        result_type: ClassVar = YourModel to use this method (D-13).
        """
        if self.result_type is None:
            raise RuntimeError(
                f"{self.__class__.__name__}.result_type is None - "
                "set result_type: ClassVar = YourModel to use _run_typed()"
            )

        # Lazy imports: avoid module-load cost and circular import chains.
        from pydantic_ai import Agent  # noqa: PLC0415

        from src.core.ai.llm_adapter import make_llm_adapter  # noqa: PLC0415
        from src.core.ai.worker_context import WorkerContext  # noqa: PLC0415

        # Resolve max_tokens before adapter construction — chain.generate() requires int.
        _max_tokens = max_tokens if max_tokens is not None else self._default_max_tokens

        # Build audit base with placeholder call_id. The LLMAdapter stamps a fresh
        # call_id per physical request, so retries produce distinct llm_calls rows.
        # called_at excluded — llm_adapter._request() stamps it per request.
        audit_context = self._build_audit_context(
            context, prompt, call_id="", include_called_at=False
        )

        worker_ctx = WorkerContext(
            signal_context=context, llm_chain=self._llm, memory_client=self._memory_client
        )
        adapter = make_llm_adapter(
            worker_context=worker_ctx,
            system=system,
            max_tokens=_max_tokens,
            timeout=self._timeout_s,  # D-11: always from self._timeout_s
            audit_context=audit_context,
        )

        async with self._agent_span("agent.run_typed", context):
            # output_type= is the pydantic-ai 1.0 kwarg (Pitfall 2: not result_type=).
            # Single-use agent per call (Pitfall 3: adapter closures fresh audit base).
            agent: Agent[None, BaseModel] = Agent(
                adapter,
                output_type=self.result_type,
                retries=1,
            )
            result = await agent.run(prompt)
            return result.output  # Pitfall 5: .output not .data

    async def _report_parse_failure(self, call_id: str) -> None:
        """Publish a corrective parse_success=False update for the given call_id.

        Called by agents after _llm_generate succeeds (got a response) but
        JSON parsing of that response fails. Routes through the LLM chain's
        producer so the writer can UPDATE the llm_calls row.
        """
        LLM_PARSE_FAILURES.add(1, self._agent_labels)
        try:
            await self._llm._publish_parse_failure(call_id)
        except Exception as error:
            logger.warning("agent.parse_failure_report_failed", call_id=call_id, error=str(error))

    # -----------------------------------------------------------------------
    # Extension hooks (D-42, D-43, D-44) — future phases wire these to OTel,
    # guardrails, and data classification. Default implementations are no-ops.
    # -----------------------------------------------------------------------

    async def _on_error(self, error: Exception) -> None:
        """Hook: called when _compute() raises exception.

        Emits AI_AGENT_ERRORS_TOTAL counter with agent_id and error_type labels.
        Publishes an agent_prediction lineage event when self._lineage is set.
        """
        AI_AGENT_ERRORS_TOTAL.add(
            1,
            {**self._agent_labels, "error_type": type(error).__name__},
        )
        if self._lineage is not None:
            self._lineage.record(
                signal_id=UUID(int=0),
                event_type="agent_prediction",
                source=self.agent_id,
                metadata={"error": str(error), "error_type": type(error).__name__},
            )

    async def _on_guardrail_violation(self, output: AgentOutput) -> None:
        """Hook: called when guardrails detect policy violation.

        Future phase: wire to content filtering.
        """
        pass

    @property
    def _audit_payload(self) -> dict:
        """Hook: returns audit metadata for data classification.

        Future phase: use for data governance tracking.
        """
        return {}
