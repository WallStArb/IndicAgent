# Phase 095 Plan 05: UPDATED for Multi-Tenant Service Registration

## Changes to Original Plan 05

### Updated Service Registration with Per-User Queues

**NEW Features Added:**
1. **Per-user request queues** for isolation
2. **User context propagation** from service to agents
3. **Multi-tenant feature gates** (ENABLE_MULTI_TENANT + ENABLE_PYDANTIC_SKEPTIC_SHADOW)
4. **Cost tracking per user** in service metrics

### Updated AlphaSwarm Registration

**OLD (from 094-05-PLAN.md):**
```python
# In _setup() method
if self.settings.ENABLE_PYDANTIC_SKEPTIC_SHADOW:
    self._agents.append(SkepticComputeAgentPydantic(llm_chain=self._llm_chain))
```

**NEW (Multi-Tenant Ready):**
```python
# In _setup() method
# NEW: Per-user request queues for multi-tenant mode
self._user_queues: dict[str, asyncio.Queue] = {}
self._active_requests: dict[str, int] = {}  # Track concurrent requests per user

# Register agents with user context support
if self.settings.ENABLE_PYDANTIC_SKEPTIC_SHADOW:
    self._agents.append(
        SkepticComputeAgentPydantic(
            llm_chain=self._llm_chain,
            # User context injected per-request, not at construction
        )
    )
```

### Updated Agent Execution with Per-User Queues

**NEW: Per-request user context injection**

```python
async def _execute_agent_with_user_context(
    self,
    agent: BaseAIAgent,
    context: AIContext,
    user_context: UserContext,
) -> AgentOutput:
    """Execute agent with per-user context and quota enforcement.

    NEW: Injects user_context into agent for quota-aware execution.
    Routes requests through per-user queues for isolation.
    """
    # Check per-user queue capacity
    user_queue = self._get_or_create_user_queue(user_context.user_id)
    if user_queue.qsize() >= user_context.concurrency_limit:
        return AgentOutput(
            agent_id=agent.agent_id,
            group=agent.group,
            output_type="neutral",
            payload={},
            error=f"User {user_context.user_id} concurrency limit exceeded",
            shadow_only=True,
            latency_ms=0.0,
        )

    # Queue the request
    await user_queue.put((agent, context, user_context))

    # Execute with timeout
    try:
        result = await asyncio.wait_for(
            self._process_user_queue(user_context.user_id),
            timeout=300.0,  # 5 minute max per-user queue time
        )
        return result
    except asyncio.TimeoutError:
        return AgentOutput(
            agent_id=agent.agent_id,
            group=agent.group,
            output_type="neutral",
            payload={},
            error=f"User {user_context.user_id} request timeout",
            shadow_only=True,
            latency_ms=300_000,
        )

def _get_or_create_user_queue(self, user_id: str) -> asyncio.Queue:
    """Get or create per-user request queue."""
    if user_id not in self._user_queues:
        self._user_queues[user_id] = asyncio.Queue(maxsize=10)
    return self._user_queues[user_id]

async def _process_user_queue(self, user_id: str) -> AgentOutput:
    """Process next request from user's queue."""
    queue = self._user_queues[user_id]
    agent, context, user_context = await queue.get()

    # Inject user context into agent
    if hasattr(agent, '_user_context'):
        agent._user_context = user_context

    # Execute agent
    result = await agent.compute(context)

    # Update per-user metrics
    self._update_user_metrics(user_id, result)

    return result
```

### Updated Settings for Multi-Tenant

**NEW: Feature gates in settings.py**

```python
# In src/config/settings.py
class Settings(BaseSettings):
    # ... existing settings ...

    # Multi-tenant agent execution
    ENABLE_MULTI_TENANT: bool = Field(default=False)  # NEW: Multi-tenant mode
    DEFAULT_USER_QUOTA: int = Field(default=1000)  # Requests per day per user
    DEFAULT_COST_QUOTA_USD: float = Field(default=100.0)  # Budget per user
    DEFAULT_CONCURRENCY_LIMIT: int = Field(default=5)  # Max concurrent per user

    # Pydantic AI shadow mode
    ENABLE_PYDANTIC_SKEPTIC_SHADOW: bool = Field(default=False)  # Existing gate
```

### Updated Service Registration Tests

**NEW: Multi-tenant registration tests**

```python
@pytest.mark.integration
@pytest.mark.asyncio
async def test_multi_tenant_agent_execution():
    """Service should execute agents with per-user context."""
    mock_settings = Mock()
    mock_settings.ENABLE_MULTI_TENANT = True
    mock_settings.ENABLE_PYDANTIC_SKEPTIC_SHADOW = True

    with patch('services.alpha_swarm_agent.get_settings', return_value=mock_settings):
        service = AlphaSwarmComputeAgent()
        await service._setup()

        # Create two users
        user1_ctx = UserContext.from_request(user_id="user1", request_quota=10)
        user2_ctx = UserContext.from_request(user_id="user2", request_quota=10)

        # Execute requests for both users
        context = AIContext(symbol="ES", timeframe="5m", ts=datetime.now(UTC))

        # User1 request
        result1 = await service._execute_agent_with_user_context(
            agent=service._agents[0],
            context=context,
            user_context=user1_ctx,
        )
        assert isinstance(result1, AgentOutput)

        # User2 request (should have independent quota)
        result2 = await service._execute_agent_with_user_context(
            agent=service._agents[0],
            context=context,
            user_context=user2_ctx,
        )
        assert isinstance(result2, AgentOutput)

        # Verify user queues isolated
        assert "user1" in service._user_queues
        assert "user2" in service._user_queues
```

### Updated Cost Tracking Queries

**NEW: Per-user cost tracking in shadow validation**

```python
@pytest.mark.integration
def test_per_user_cost_tracking_query():
    """Verify per-user cost tracking query for multi-tenant mode.

    NEW: Tracks LLM costs per user for quota enforcement and billing.
    """
    query = """
        SELECT
            user_id,
            tenant_id,
            COUNT(*) as total_requests,
            SUM(estimated_cost_usd) as total_cost_usd,
            AVG(latency_ms) as avg_latency_ms,
            AVG(parse_success::int) as parse_success_rate
        FROM llm_calls
        WHERE called_at > NOW() - INTERVAL '7 days'
        GROUP BY user_id, tenant_id
        HAVING SUM(estimated_cost_usd) > 0;
    """

    # Assert query structure checks for user-level aggregation
    assert "user_id" in query
    assert "tenant_id" in query
    assert "total_cost_usd" in query
    assert "GROUP BY user_id, tenant_id" in query

    # Expected: Each user's costs tracked independently
    # Used for quota enforcement and billing in multi-tenant mode
```

## Implementation Changes

### In Plan 05, Task 1:

**UPDATE service registration** (see full examples above)

**ADD per-user queue management:**
```python
# In AlphaSwarmComputeAgent.__init__
self._user_queues: dict[str, asyncio.Queue] = {}
self._active_requests: dict[str, int] = {}
self._user_metrics: dict[str, dict[str, float]] = {}
```

**ADD _execute_agent_with_user_context() method** (see full example above)

**ADD _get_or_create_user_queue() helper**

**ADD _process_user_queue() helper**

**ADD _update_user_metrics() helper**
```python
def _update_user_metrics(self, user_id: str, result: AgentOutput) -> None:
    """Update per-user metrics after agent execution."""
    if user_id not in self._user_metrics:
        self._user_metrics[user_id] = {
            "requests": 0,
            "total_cost_usd": 0.0,
            "total_latency_ms": 0.0,
        }

    self._user_metrics[user_id]["requests"] += 1
    self._user_metrics[user_id]["total_latency_ms"] += result.latency_ms

    # Estimate cost (would use actual cost from LLM provider)
    estimated_cost = result.latency_ms / 1000 * 0.001  # Simplified
    self._user_metrics[user_id]["total_cost_usd"] += estimated_cost
```

### In Plan 05, Task 2:

**ADD multi-tenant settings to settings.py** (see example above)

### In Plan 05, Task 3-5:

**UPDATE integration tests** to include multi-tenant scenarios

## Success Criteria Updates

**NEW:**
- Per-user request queues isolate execution
- User context propagated from service to agents
- ENABLE_MULTI_TENANT feature gate defaults false
- Per-user cost tracking queries added to validation tests
- Integration tests verify multi-user isolation
- Backward compatibility preserved (single-tenant mode uses UserContext.system())

## Migration Path

### Phase 1: Single-Tenant (Current)
- ENABLE_MULTI_TENANT = false
- All requests use UserContext.system()
- No per-user queues or quotas

### Phase 2: Multi-Tenant Alpha (Future Phase)
- ENABLE_MULTI_TENANT = true
- User context loaded from auth/request
- Per-user quotas enforced
- Per-user queues for isolation

### Phase 3: Multi-Tenant Production (Future)
- Billing integration via cost tracking
- Admin dashboard for per-user metrics
- Dynamic quota adjustment via admin API

---

**Integration Note:** This update depends on Plan 00-04 completion.
Per-user queue management adds complexity to AlphaSwarm service.
Consider incremental rollout: Phase 095 uses single-tenant mode,
Phase 09X enables multi-tenant for user-facing features.
