# Phase 095 Plan 01: UPDATED for Multi-Tenant Integration

## Changes to Original Plan 01

### Updated AgentDeps Definition

**OLD (from 094-01-PLAN.md):**
```python
@dataclass(frozen=True)
class AgentDeps:
    signal_context: AIContext
    llm_chain: LLMProviderChain
    db_pool: Any | None = None
    memory_client: Any | None = None
```

**NEW (Multi-Tenant Ready):**
```python
@dataclass(frozen=True)
class AgentDeps:
    user_context: UserContext  # NEW: Multi-tenant awareness
    signal_context: AIContext
    llm_chain: LLMProviderChain
    db_pool: Any | None = None
    memory_client: Any | None = None
```

### Updated Unit Tests

**OLD:**
```python
def test_agent_deps_instantiation(mock_context, mock_llm_chain):
    deps = AgentDeps(
        signal_context=mock_context,
        llm_chain=mock_llm_chain,
    )
```

**NEW (Multi-Tenant):**
```python
def test_agent_deps_instantiation(mock_context, mock_llm_chain):
    user_ctx = UserContext.system()  # Single-tenant mode
    deps = AgentDeps(
        user_context=user_ctx,  # NEW: Required parameter
        signal_context=mock_context,
        llm_chain=mock_llm_chain,
    )
```

### Backward Compatibility

**Single-Tenant Mode (ENABLE_MULTI_TENANT=false):**
- Uses `UserContext.system()` automatically
- All agents run as "system" user
- No behavioral changes to existing code

**Multi-Tenant Mode (ENABLE_MULTI_TENANT=true):**
- Requires `user_context` parameter
- Per-user quotas enforced
- llm_calls populated with user_id

## Implementation Changes

### In Plan 01, Task 1:

**ADD to imports:**
```python
from src.core.ai.user_context import UserContext
```

**UPDATE AgentDeps class:**
```python
@dataclass(frozen=True)
class AgentDeps:
    """Dependency container for Pydantic AI agents.

    Threaded through RunContext[AgentDeps] to provide access to user
    context, signal context, LLM chain, database pool, and optional memory client.

    Immutable (frozen=True) to prevent accidental modification by agents.

    NEW: user_context provides multi-tenant awareness for per-user quotas,
    permissions, and cost tracking.
    """
    user_context: UserContext  # NEW: Multi-tenant support
    signal_context: AIContext
    llm_chain: LLMProviderChain
    db_pool: Any | None = None
    memory_client: Any | None = None
```

### In Plan 01, Task 3:

**UPDATE test fixture:**
```python
@pytest.fixture
def mock_user_context():
    """Create UserContext for testing."""
    from src.core.ai.user_context import UserContext
    return UserContext.system()  # Single-tenant mode

def test_agent_deps_instantiation(mock_context, mock_llm_chain, mock_user_context):
    """AgentDeps should construct with required fields including user_context."""
    deps = AgentDeps(
        user_context=mock_user_context,  # NEW: Required parameter
        signal_context=mock_context,
        llm_chain=mock_llm_chain,
    )
    assert deps.user_context is mock_user_context
    assert deps.signal_context is mock_context
    assert deps.llm_chain is mock_llm_chain
```

## Success Criteria Updates

**NEW:**
- AgentDeps includes user_context parameter with UserContext.system() default
- Unit tests verify user_context propagation through AgentDeps
- Backward compatibility preserved (single-tenant mode works unchanged)
- Multi-tenant foundation ready for Plan 02 integration

---

**Integration Note:** This update depends on Plan 00 completion. Plan 01 should
execute after Plan 00 to ensure UserContext is available.
