# Phase 095 Plan 02: UPDATED for Multi-Tenant Integration

## Changes to Original Plan 02

### Updated PydanticAIAdapter with Quota Enforcement

**NEW Features Added:**
1. **Quota enforcement** before agent compute()
2. **User context propagation** to llm_calls audit trail
3. **Permission checking** for agent access control
4. **Concurrency tracking** per user

### Updated PydanticAIAdapter Constructor

**OLD (from 094-02-PLAN.md):**
```python
def __init__(
    self,
    pydantic_agent: Agent,
    llm_chain: Any,
    db_pool: Any | None = None,
    memory_client: Any | None = None,
    **kwargs: Any,
) -> None:
    super().__init__(**kwargs)
    self._pydantic_agent = pydantic_agent
    self._llm = llm_chain
    self._db_pool = db_pool
    self._memory_client = memory_client
```

**NEW (Multi-Tenant Ready):**
```python
def __init__(
    self,
    pydantic_agent: Agent,
    llm_chain: Any,
    db_pool: Any | None = None,
    memory_client: Any | None = None,
    user_context: UserContext | None = None,  # NEW
    **kwargs: Any,
) -> None:
    super().__init__(**kwargs)
    self._pydantic_agent = pydantic_agent
    self._llm = llm_chain
    self._db_pool = db_pool
    self._memory_client = memory_client
    self._user_context = user_context or UserContext.system()  # NEW: Default to system
    self._limits = AgentLimits(self._user_context)  # NEW: Quota enforcement
```

### Updated _compute() with Quota Enforcement

**OLD:**
```python
async def _compute(self, context: AIContext) -> AgentOutput:
    """Delegate to Pydantic AI agent, convert result to AgentOutput."""
    deps = self._build_deps(context)
    # ... rest of compute
```

**NEW (Multi-Tenant with Quota Enforcement):**
```python
async def _compute(self, context: AIContext) -> AgentOutput:
    """Delegate to Pydantic AI agent with quota enforcement and audit trail.

    NEW: Enforces per-user quotas before compute. Tracks user_id and tenant_id
    in llm_calls audit trail. Checks agent permissions.
    """
    # NEW: Check quota before compute
    can_execute, deny_reason = self._limits.can_execute()
    if not can_execute:
        return self._neutral(error=f"Quota exceeded: {deny_reason}", latency_ms=0.0)

    # NEW: Check agent permissions
    if not self._limits.check_permissions(self.agent_id):
        return self._neutral(
            error=f"Permission denied for agent {self.agent_id}",
            latency_ms=0.0,
        )

    # NEW: Track concurrency
    self._limits.concurrent_requests += 1

    try:
        deps = self._build_deps(context)
        user_prompt = self._build_user_prompt(context)
        system_prompt = self._build_system_prompt()

        # Call LLM through _llm_generate() with user context
        raw_response, call_id = await self._llm_generate(
            context,
            prompt=user_prompt,
            system=system_prompt,
            max_tokens=500,
            timeout=self.latency_budget_ms / 1000.0,
            # NEW: Pass user context for audit trail
            user_context=self._user_context,  # Will be added to llm_calls
        )

        if not raw_response:
            return self._neutral(error="LLM returned empty response", latency_ms=0.0)

        # Parse response
        try:
            result = self._parse_response(raw_response)
        except Exception as exc:
            await self._report_parse_failure(call_id)
            return self._neutral(error=f"Parse failed: {exc}", latency_ms=0.0)

        # Compute agent output
        output = await self._to_agent_output(result, context)

        # NEW: Record request completion with cost tracking
        estimated_cost_usd = self._estimate_llm_cost(raw_response)
        self._limits.record_completion(cost_usd=estimated_cost_usd)

        return output

    finally:
        # NEW: Always release concurrency slot
        self._limits.concurrent_requests = max(0, self._limits.concurrent_requests - 1)
```

### Updated _build_deps()

**OLD:**
```python
def _build_deps(self, context: AIContext) -> AgentDeps:
    """Build dependency container for Pydantic AI run."""
    return AgentDeps(
        signal_context=context,
        llm_chain=self._llm,
        db_pool=self._db_pool,
        memory_client=self._memory_client,
    )
```

**NEW (Multi-Tenant):**
```python
def _build_deps(self, context: AIContext) -> AgentDeps:
    """Build dependency container for Pydantic AI run.

    NEW: Includes user_context for multi-tenant awareness.
    """
    return AgentDeps(
        user_context=self._user_context,  # NEW: Multi-tenant support
        signal_context=context,
        llm_chain=self._llm,
        db_pool=self._db_pool,
        memory_client=self._memory_client,
    )
```

### New Helper Methods

**NEW: Cost estimation for quota tracking**
```python
def _estimate_llm_cost(self, response: str) -> float:
    """Estimate LLM call cost in USD for quota tracking.

    Simplified model: $0.0001 per 1K characters (adjust with actual pricing).
    In production, use token count from LLM provider.
    """
    char_count = len(response)
    return (char_count / 1000) * 0.0001
```

## Implementation Changes

### In Plan 02, Task 1:

**ADD to imports:**
```python
from src.core.ai.user_context import UserContext
from src.core.ai.agent_limits import AgentLimits
```

**UPDATE constructor:**
```python
def __init__(
    self,
    pydantic_agent: Agent,
    llm_chain: Any,
    db_pool: Any | None = None,
    memory_client: Any | None = None,
    user_context: UserContext | None = None,  # NEW
    **kwargs: Any,
) -> None:
    super().__init__(**kwargs)
    self._pydantic_agent = pydantic_agent
    self._llm = llm_chain
    self._db_pool = db_pool
    self._memory_client = memory_client
    self._user_context = user_context or UserContext.system()  # NEW
    self._limits = AgentLimits(self._user_context)  # NEW
```

**UPDATE _compute() with quota enforcement** (see full example above)

**UPDATE _build_deps()** (see full example above)

**ADD _estimate_llm_cost()** helper method

### In Plan 02, Task 3:

**UPDATE test for quota enforcement:**
```python
@pytest.mark.asyncio
async def test_compute_enforces_quotas(mock_context, mock_llm_chain):
    """FIXED: _compute() should enforce quotas before execution."""
    from src.core.ai.user_context import UserContext
    from src.core.ai.agent_limits import AgentLimits

    # Create user with low quota
    user_ctx = UserContext(
        user_id="test_user",
        request_quota=1,  # Only 1 request allowed
    )

    adapter = DummyPydanticAIAdapter(
        pydantic_agent=None,
        llm_chain=mock_llm_chain,
        user_context=user_ctx,  # NEW: Pass user context
    )

    # Mock _llm_generate to return fake response
    adapter._llm_generate = AsyncMock(return_value=('{"test": "data"}', "call_123"))

    # First request should succeed
    result1 = await adapter._compute(mock_context)
    assert isinstance(result1, AgentOutput)

    # Exceed quota
    adapter._limits.requests_today = 1

    # Second request should fail with quota error
    result2 = await adapter._compute(mock_context)
    assert "Quota exceeded" in result2.error
```

## Success Criteria Updates

**NEW:**
- PydanticAIAdapter enforces per-user quotas before compute()
- llm_calls populated with user_id and tenant_id from UserContext
- Agent permissions checked via AgentLimits.check_permissions()
- Concurrency tracked per user via AgentLimits
- Cost tracking via _estimate_llm_cost() for quota enforcement
- Backward compatibility preserved (UserContext.system() for single-tenant)

## Integration Notes

**BaseAIAgent._llm_generate() Update Required:**
The existing `_llm_generate()` method needs updating to accept `user_context` parameter:

```python
# EXISTING signature (in base_agent.py)
async def _llm_generate(
    self,
    context: AIContext,
    prompt: str,
    system: str,
    max_tokens: int,
    timeout: float,
    model: str = "default",
    extra_audit: dict | None = None,
) -> tuple[str | None, str]:

# NEEDS UPDATE to:
async def _llm_generate(
    self,
    context: AIContext,
    prompt: str,
    system: str,
    max_tokens: int,
    timeout: float,
    model: str = "default",
    extra_audit: dict | None = None,
    user_context: UserContext | None = None,  # NEW
) -> tuple[str | None, str]:
```

**audit_context update:**
```python
audit_context: dict[str, Any] = {
    "call_id": call_id,
    "called_at": format_iso_ts(datetime.now(UTC)),
    "symbol": context.symbol,
    "signal_id": str(context.signal_id) if context.signal_id else None,
    "group_name": self.group,
    "agent_id": self.agent_id,
    "prompt_version": self.prompt_version,
    "timeframe": context.timeframe,
    "prompt": prompt,
    "succeeded": True,
    "parse_success": True,
    # NEW: Multi-tenant audit fields
    "user_id": user_context.user_id if user_context else "system",
    "tenant_id": user_context.tenant_id if user_context else None,
}
```

---

**Integration Note:** This update depends on Plan 00 and Plan 01 completion.
BaseAIAgent._llm_generate() signature update is a **breaking change** that
requires updating all existing agent implementations that call _llm_generate().
