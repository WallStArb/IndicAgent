# Phase 5: Zep Episodic Memory Implementation Plan

**Version:** 1.0
**Status:** archived
**Last Updated:** 2026-05-20
> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add episodic trading memory backed by a self-hosted Zep instance — past signal outcomes are recalled at agent prompt time, closing the feedback loop between signal outcomes and future LLM reasoning.

**Architecture:** `EpisodicMemoryStore` wraps Zep's HTTP API. `AgentDeps` gains a `memory` field (optional — `None` when Zep is not configured, falling back silently). A `@pydantic_agent.system_prompt` hook in `_build_generic_agent` and the 4 factory functions enriches each agent's prompt with recalled episodes. `llm_writer_service` calls `memory_store.record()` when a signal outcome arrives on the `llm.outcomes` topic, writing the outcome back to Zep.

**Phase dependencies:** Phase 3 (Pydantic AI) + Phase 4 (Agent Registry) must be merged first — this phase adds a `memory` field to `AgentDeps` and hooks into `_build_generic_agent`.

**Spec:** `docs/plans/2026-05-20-agent-platform-redesign.md` — Layer 4 (Zep Memory)

---

## File Map

| Action | Path | Responsibility |
|---|---|---|
| Create | `src/core/ai/memory.py` | `Episode`, `EpisodicMemoryStore`, `NullMemoryStore` |
| Modify | `src/core/ai/pydantic_agent.py` | Add `memory: EpisodicMemoryStore \| None = None` to `AgentDeps` |
| Modify | `src/core/ai/agent_registry.py` | Pass `memory_store` into `_build_generic_agent`; add `@agent.system_prompt` hook |
| Modify | `src/intelligence/ai/alpha/pydantic_agents.py` | Add `@agent.system_prompt` hooks to all 4 factory functions |
| Modify | `services/llm_writer_service.py` | Instantiate `EpisodicMemoryStore`; call `record()` on outcome |
| Modify | `production/docker-compose.yml` | Add `zep` and `zep-db` services |
| Modify | `requirements.txt` | Add `zep-python` |
| Create | `tests/unit/ai_agent_tests/test_memory.py` | Unit tests for `EpisodicMemoryStore` |

---

## Task 1: Add Zep to docker-compose

**Files:**
- Modify: `production/docker-compose.yml`

Zep self-hosted requires PostgreSQL. We add a dedicated `zep-db` postgres container and the `zep` server.

- [ ] **Step 1: Read the bottom of docker-compose.yml to find the right insertion point**

```bash
tail -30 production/docker-compose.yml
```

- [ ] **Step 2: Add Zep services to production/docker-compose.yml**

Add these two services before the final closing of the file (after the last existing service):

```yaml
  zep-db:
    image: postgres:16-alpine
    container_name: indicagent-zep-db
    restart: unless-stopped
    environment:
      POSTGRES_USER: zep
      POSTGRES_PASSWORD: zep
      POSTGRES_DB: zep
    volumes:
      - zep_postgres_data:/var/lib/postgresql/data
    networks:
      - indicagent

  zep:
    image: ghcr.io/getzep/zep:latest
    container_name: indicagent-zep
    restart: unless-stopped
    ports:
      - "8000:8000"
    environment:
      ZEP_STORE_TYPE: postgres
      ZEP_STORE_POSTGRES_DSN: "postgres://zep:zep@zep-db:5432/zep"
      ZEP_AUTH_REQUIRED: "false"
    depends_on:
      - zep-db
    networks:
      - indicagent
```

Also add `zep_postgres_data:` to the `volumes:` section at the bottom of the file.

**Important:** Zep exposes port 8000. Check if that port conflicts with another service in docker-compose.yml. If so, use `8010:8000` instead.

```bash
grep "8000" production/docker-compose.yml
```

If port 8000 is taken, use `8010:8000` and update the `ZEP_BASE_URL` in `.env` / Settings accordingly.

- [ ] **Step 3: Start Zep**

```bash
cd production && docker compose up -d zep-db zep
sleep 8 && docker compose ps zep
```

Expected: `zep` shows as running.

- [ ] **Step 4: Verify Zep API responds**

```bash
curl -s http://localhost:8000/healthz | head -5
```

Expected: HTTP 200 with `{"status":"ok"}` or similar.

- [ ] **Step 5: Commit**

```bash
cd /home/bg/dev/indicagent
git add production/docker-compose.yml
git commit -m "infra: add self-hosted Zep + zep-db to docker-compose for episodic memory"
```

---

## Task 2: Install zep-python and add Settings fields

**Files:**
- Modify: `requirements.txt`
- Modify: `src/config/settings.py`

- [ ] **Step 1: Add zep-python to requirements.txt**

```bash
echo "zep-python>=2.0" >> requirements.txt
```

Then install:

```bash
uv pip install zep-python
```

Verify:

```bash
.venv/bin/python -c "import zep_python; print(zep_python.__version__)"
```

- [ ] **Step 2: Read current Settings fields**

```bash
grep -n "ollama\|openrouter\|class Settings" src/config/settings.py | head -20
```

- [ ] **Step 3: Add Zep settings to Settings class**

Find the Settings class and add:

```python
zep_base_url: str = "http://localhost:8000"
zep_enabled: bool = True
```

These can be overridden in `.env` as `ZEP_BASE_URL` and `ZEP_ENABLED`.

- [ ] **Step 4: Commit**

```bash
git add requirements.txt src/config/settings.py
git commit -m "deps: add zep-python; add zep_base_url and zep_enabled to Settings"
```

---

## Task 3: Write failing tests for EpisodicMemoryStore

**Files:**
- Create: `tests/unit/ai_agent_tests/test_memory.py`

- [ ] **Step 1: Create the test file**

```python
"""Tests for EpisodicMemoryStore — Zep-backed episodic trading memory."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.ai.memory import EpisodicMemoryStore, NullMemoryStore


# ── NullMemoryStore ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_null_store_recall_returns_empty_string():
    store = NullMemoryStore()
    ctx = MagicMock()
    result = await store.recall(ctx)
    assert result == ""


@pytest.mark.asyncio
async def test_null_store_record_is_noop():
    store = NullMemoryStore()
    ctx = MagicMock()
    # Should not raise
    await store.record(ctx, signal_id="abc", outcome="profitable", pnl_r=1.5)


# ── EpisodicMemoryStore.recall ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_recall_returns_empty_string_when_no_results():
    with patch("src.core.ai.memory.AsyncZep") as mock_zep_cls:
        mock_client = AsyncMock()
        mock_zep_cls.return_value = mock_client
        mock_client.memory.search_sessions.return_value = []

        store = EpisodicMemoryStore(base_url="http://localhost:8000")
        ctx = MagicMock()
        ctx.symbol = "ES"
        ctx.timeframe = "5m"

        result = await store.recall(ctx)

        assert result == ""


@pytest.mark.asyncio
async def test_recall_formats_episodes_as_string():
    with patch("src.core.ai.memory.AsyncZep") as mock_zep_cls:
        mock_client = AsyncMock()
        mock_zep_cls.return_value = mock_client

        mock_session = MagicMock()
        mock_session.metadata = {
            "outcome": "profitable",
            "pnl_r": 1.8,
            "regime": "trending",
            "setup_type": "breakout",
        }
        mock_client.memory.search_sessions.return_value = [mock_session]

        store = EpisodicMemoryStore(base_url="http://localhost:8000")
        ctx = MagicMock()
        ctx.symbol = "ES"
        ctx.timeframe = "5m"

        result = await store.recall(ctx)

        assert "profitable" in result
        assert "1.8" in result or "1.80" in result


@pytest.mark.asyncio
async def test_recall_returns_empty_string_on_zep_error():
    with patch("src.core.ai.memory.AsyncZep") as mock_zep_cls:
        mock_client = AsyncMock()
        mock_zep_cls.return_value = mock_client
        mock_client.memory.search_sessions.side_effect = Exception("connection refused")

        store = EpisodicMemoryStore(base_url="http://localhost:8000")
        ctx = MagicMock()
        ctx.symbol = "ES"
        ctx.timeframe = "5m"

        # Should not raise — returns empty string on error
        result = await store.recall(ctx)
        assert result == ""


# ── EpisodicMemoryStore.record ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_record_adds_memory_to_zep_session():
    with patch("src.core.ai.memory.AsyncZep") as mock_zep_cls:
        mock_client = AsyncMock()
        mock_zep_cls.return_value = mock_client
        mock_client.memory.add = AsyncMock()
        mock_client.user.add = AsyncMock()
        mock_client.memory.add_session = AsyncMock()

        store = EpisodicMemoryStore(base_url="http://localhost:8000")
        ctx = MagicMock()
        ctx.symbol = "ES"
        ctx.timeframe = "5m"

        await store.record(ctx, signal_id="sig-123", outcome="profitable", pnl_r=2.1)

        # record() must call memory.add at least once
        assert mock_client.memory.add.called


@pytest.mark.asyncio
async def test_record_is_noop_on_zep_error():
    with patch("src.core.ai.memory.AsyncZep") as mock_zep_cls:
        mock_client = AsyncMock()
        mock_zep_cls.return_value = mock_client
        mock_client.memory.add.side_effect = Exception("zep unavailable")
        mock_client.user.add = AsyncMock()
        mock_client.memory.add_session = AsyncMock()

        store = EpisodicMemoryStore(base_url="http://localhost:8000")
        ctx = MagicMock()
        ctx.symbol = "ES"
        ctx.timeframe = "5m"

        # Should not raise
        await store.record(ctx, signal_id="sig-123", outcome="loss", pnl_r=-0.5)
```

- [ ] **Step 2: Run to confirm failure**

```bash
.venv/bin/pytest tests/unit/ai_agent_tests/test_memory.py -v 2>&1 | head -15
```

Expected: `ModuleNotFoundError: No module named 'src.core.ai.memory'`

---

## Task 4: Implement EpisodicMemoryStore

**Files:**
- Create: `src/core/ai/memory.py`

- [ ] **Step 1: Check the zep-python AsyncZep import**

```bash
.venv/bin/python -c "from zep_python import AsyncZep; print('ok')"
```

Note the exact import path — zep-python v2+ uses `from zep_python import AsyncZep`.

- [ ] **Step 2: Create `src/core/ai/memory.py`**

```python
"""EpisodicMemoryStore — Zep-backed episodic trading memory.

recall(context) → str injected as an additional system prompt by the
@pydantic_agent.system_prompt hook in each agent factory.

record(context, signal_id, outcome, pnl_r) → writes outcome back to Zep
when a signal closes. Called by llm_writer_service.

NullMemoryStore is used when zep_enabled=False or Zep is unreachable.
Both implement the same async interface so callers need no conditional logic.
"""
from __future__ import annotations

import structlog

logger = structlog.get_logger(__name__)

# Lazy import — Zep only needed when EpisodicMemoryStore is instantiated.
try:
    from zep_python import AsyncZep
    from zep_python.memory import Message, Memory
    from zep_python.user import CreateUserRequest
    _ZEP_AVAILABLE = True
except ImportError:
    _ZEP_AVAILABLE = False


class NullMemoryStore:
    """No-op memory store used when Zep is disabled or unavailable."""

    async def recall(self, context: object, k: int = 5) -> str:
        return ""

    async def record(
        self,
        context: object,
        signal_id: str,
        outcome: str,
        pnl_r: float | None,
    ) -> None:
        return


class EpisodicMemoryStore:
    """Zep-backed episodic memory for trading setups.

    Session ID = signal_id (one Zep session per signal).
    User ID = symbol (groups sessions by instrument).

    recall() fetches the k most relevant past sessions and formats them
    as a short string for injection into agent system prompts.

    record() writes the signal outcome back to Zep memory so future
    recall() calls reflect what happened.
    """

    def __init__(self, base_url: str = "http://localhost:8000") -> None:
        if not _ZEP_AVAILABLE:
            raise RuntimeError(
                "zep-python not installed. Run: uv pip install zep-python"
            )
        self._client = AsyncZep(base_url=base_url)

    async def recall(self, context: object, k: int = 5) -> str:
        """Return formatted past episodes for injection into system prompt.

        Returns empty string on error or when no relevant history exists.
        """
        symbol = getattr(context, "symbol", "UNKNOWN")
        timeframe = getattr(context, "timeframe", "")

        try:
            results = await self._client.memory.search_sessions(
                text=f"{symbol} {timeframe} trading setup",
                user_id=symbol,
                limit=k,
            )
            if not results:
                return ""

            lines = [f"Past {len(results)} similar setup(s) for {symbol}:"]
            for session in results:
                meta = session.metadata or {}
                outcome = meta.get("outcome", "unknown")
                pnl = meta.get("pnl_r")
                regime = meta.get("regime", "")
                setup_type = meta.get("setup_type", "")
                pnl_str = f"PnL={pnl:.2f}R" if pnl is not None else "PnL=?"
                lines.append(f"- {regime} {setup_type}: {outcome} ({pnl_str})")

            return "\n".join(lines)

        except Exception as exc:
            logger.debug(
                "memory.recall_failed",
                symbol=symbol,
                error=str(exc)[:100],
            )
            return ""

    async def record(
        self,
        context: object,
        signal_id: str,
        outcome: str,
        pnl_r: float | None,
    ) -> None:
        """Write signal outcome to Zep for future recall.

        Called by llm_writer_service when a signal closes.
        Errors are logged and swallowed — memory is best-effort.
        """
        symbol = getattr(context, "symbol", "UNKNOWN")
        timeframe = getattr(context, "timeframe", "")
        regime = getattr(context, "regime", "")
        setup_type = getattr(context, "setup_type", "")

        try:
            # Ensure user exists
            try:
                await self._client.user.add(
                    CreateUserRequest(user_id=symbol)
                )
            except Exception:
                pass  # user already exists

            # Create or update session with outcome metadata
            session_id = f"{symbol}_{signal_id}"
            try:
                await self._client.memory.add_session(
                    session_id=session_id,
                    user_id=symbol,
                    metadata={
                        "symbol": symbol,
                        "timeframe": timeframe,
                        "regime": regime,
                        "setup_type": setup_type,
                        "outcome": outcome,
                        "pnl_r": pnl_r,
                        "signal_id": signal_id,
                    },
                )
            except Exception:
                pass  # session may already exist

            await self._client.memory.add(
                session_id=session_id,
                memory=Memory(
                    messages=[
                        Message(
                            role="system",
                            role_type="system",
                            content=(
                                f"Signal {signal_id} for {symbol} {timeframe}: "
                                f"outcome={outcome}, pnl_r={pnl_r}, "
                                f"regime={regime}, setup_type={setup_type}"
                            ),
                        )
                    ]
                ),
            )

        except Exception as exc:
            logger.debug(
                "memory.record_failed",
                symbol=symbol,
                signal_id=signal_id,
                error=str(exc)[:100],
            )


def build_memory_store(settings: object) -> EpisodicMemoryStore | NullMemoryStore:
    """Build the appropriate memory store from settings.

    Returns NullMemoryStore when zep_enabled=False or zep-python not installed.
    """
    enabled = getattr(settings, "zep_enabled", True)
    if not enabled or not _ZEP_AVAILABLE:
        logger.info("memory.using_null_store", zep_enabled=enabled)
        return NullMemoryStore()

    base_url = getattr(settings, "zep_base_url", "http://localhost:8000")
    logger.info("memory.using_zep_store", base_url=base_url)
    return EpisodicMemoryStore(base_url=base_url)
```

- [ ] **Step 3: Run tests**

```bash
.venv/bin/pytest tests/unit/ai_agent_tests/test_memory.py -v
```

Expected: all tests pass.

- [ ] **Step 4: Commit**

```bash
git add src/core/ai/memory.py tests/unit/ai_agent_tests/test_memory.py
git commit -m "feat(ai): add EpisodicMemoryStore — Zep-backed episodic trading memory with NullMemoryStore fallback"
```

---

## Task 5: Add `memory` to AgentDeps and wire system_prompt hooks

**Files:**
- Modify: `src/core/ai/pydantic_agent.py`
- Modify: `src/core/ai/agent_registry.py`
- Modify: `src/intelligence/ai/alpha/pydantic_agents.py`

- [ ] **Step 1: Read current AgentDeps definition**

```bash
grep -n "class AgentDeps\|context:\|settings:" src/core/ai/pydantic_agent.py
```

- [ ] **Step 2: Update AgentDeps in pydantic_agent.py**

Find the `AgentDeps` dataclass and add the `memory` field:

```python
@dataclass
class AgentDeps:
    context: AIContext
    settings: Any
    memory: Any = None  # EpisodicMemoryStore | NullMemoryStore — None = no memory
```

- [ ] **Step 3: Update `_build_generic_agent` in agent_registry.py to accept and pass memory**

In `src/core/ai/agent_registry.py`, find `_build_generic_agent(spec, model, settings)` and update its signature and body:

```python
def _build_generic_agent(
    spec: AgentSpec,
    model: Any,
    settings: Any,
    memory_store: Any = None,
) -> PydanticAIAgent:
    ...
    # After constructing pydantic_agent, add memory hook if memory_store provided:
    if memory_store is not None:
        @pydantic_agent.system_prompt
        async def _memory_hook(ctx: RunContext[AgentDeps]) -> str:
            if ctx.deps.memory is None:
                return ""
            return await ctx.deps.memory.recall(ctx.deps.context)

    ...
    # In the returned PydanticAIAgent, the compute() call must pass memory to AgentDeps:
```

Also update `_build_one` to pass `memory_store` down:

```python
def _build_one(self, spec: AgentSpec, model: Any, settings: Any, memory_store: Any = None) -> PydanticAIAgent:
    if spec.agent_id in _BUILTIN_FACTORIES:
        return _build_builtin_agent(spec, model, settings)
    ...
    return _build_generic_agent(spec, model, settings, memory_store=memory_store)
```

And `build_agents`:

```python
def build_agents(self, model: Any, settings: Any, memory_store: Any = None) -> list[PydanticAIAgent]:
    specs = load_specs_from_dir(self._agents_dir)
    ...
    for spec in specs:
        agent = self._build_one(spec, model, settings, memory_store=memory_store)
```

- [ ] **Step 4: Update `PydanticAIAgent.compute()` to pass memory to AgentDeps**

In `src/core/ai/pydantic_agent.py`, find the `compute()` method. The `AgentDeps` construction:

```python
deps = AgentDeps(context=context, settings=self._settings)
```

Update to:

```python
deps = AgentDeps(context=context, settings=self._settings, memory=self._memory_store)
```

This requires adding `_memory_store` to `PydanticAIAgent.__init__`:

```python
def __init__(
    self,
    ...
    settings: Any,
    memory_store: Any = None,  # add this
) -> None:
    ...
    self._memory_store = memory_store
```

- [ ] **Step 5: Add `@agent.system_prompt` memory hook to all 4 factory functions in pydantic_agents.py**

For each of the 4 factory functions (`make_skeptic_agent`, `make_correlation_agent`, `make_counterfactual_agent`, `make_regime_coherence_agent`), update their signature to accept `memory_store=None` and add the hook:

```python
def make_skeptic_agent(model: Any, settings: Any, memory_store: Any = None) -> PydanticAIAgent:
    pydantic_agent: Agent[AgentDeps, SkepticResult] = Agent(
        model=model,
        result_type=SkepticResult,
        system_prompt=_SKEPTIC_SYSTEM,
        deps_type=AgentDeps,
    )

    if memory_store is not None:
        from pydantic_ai import RunContext

        @pydantic_agent.system_prompt
        async def _memory_enrich(ctx: RunContext[AgentDeps]) -> str:
            if ctx.deps.memory is None:
                return ""
            return await ctx.deps.memory.recall(ctx.deps.context)

    ...
    return PydanticAIAgent(
        ...
        memory_store=memory_store,
    )
```

Apply the same pattern to the other 3 factory functions.

Also update `_build_builtin_agent` in `agent_registry.py` to pass `memory_store`:

```python
def _build_builtin_agent(spec: AgentSpec, model: Any, settings: Any, memory_store: Any = None) -> PydanticAIAgent:
    from src.intelligence.ai.alpha import pydantic_agents as factories
    factory_name = _BUILTIN_FACTORIES[spec.agent_id]
    factory_fn = getattr(factories, factory_name)
    return factory_fn(model, settings, memory_store=memory_store)
```

- [ ] **Step 6: Update AlphaSwarmComputeAgent._setup() to build and pass memory_store**

In `services/alpha_swarm_agent.py`, import and wire:

```python
from src.core.ai.memory import build_memory_store

# In _setup():
_model = build_pydantic_model(self.settings)
_memory = build_memory_store(self.settings)
registry = AgentRegistry()
self._agents = registry.build_agents(_model, self.settings, memory_store=_memory)
```

Store `self._memory_store = _memory` so llm_writer_service can be wired separately (see Task 6).

- [ ] **Step 7: Run unit tests**

```bash
.venv/bin/pytest tests/unit/ -q --tb=short 2>&1 | tail -15
```

Expected: no regressions.

- [ ] **Step 8: Commit**

```bash
git add src/core/ai/pydantic_agent.py src/core/ai/agent_registry.py \
        src/intelligence/ai/alpha/pydantic_agents.py services/alpha_swarm_agent.py
git commit -m "feat(ai): wire Zep memory into AgentDeps and system_prompt hooks — recall enriches agent prompts"
```

---

## Task 6: Wire `record()` into llm_writer_service

**Files:**
- Modify: `services/llm_writer_service.py`

When a signal outcome arrives on `{env}.llm.outcomes`, after updating `llm_calls`, write the outcome to Zep.

- [ ] **Step 1: Read the outcome handler in llm_writer_service**

```bash
grep -n "_handle_outcome\|topic_llm_outcomes\|parsed\[.signal_id\|pnl_r" services/llm_writer_service.py | head -20
```

Find the method that processes outcome payloads (it reads `signal_id`, `outcome`, `pnl_r`).

- [ ] **Step 2: Add memory store initialization to llm_writer_service**

Find the `__init__` or `_setup` method of the writer service class. Add:

```python
from src.core.ai.memory import build_memory_store

# In __init__ or _setup():
self._memory_store = build_memory_store(self.settings)
```

- [ ] **Step 3: Add `record()` call after outcome DB update**

In the method that writes the outcome to `llm_calls`, after the successful DB UPDATE, add:

```python
# After successful DB update:
if parsed.get("outcome") and parsed.get("signal_id"):
    # Best-effort — errors logged inside record(), never raise
    import asyncio
    ctx = _MinimalContext(
        symbol=parsed.get("symbol", ""),
        timeframe=parsed.get("timeframe", ""),
        regime=parsed.get("regime", ""),
        setup_type=parsed.get("setup_type", ""),
    )
    asyncio.create_task(
        self._memory_store.record(
            ctx,
            signal_id=str(parsed["signal_id"]),
            outcome=parsed["outcome"],
            pnl_r=parsed.get("pnl_r"),
        )
    )
```

Add the `_MinimalContext` dataclass near the top of the file (not inside a class):

```python
from dataclasses import dataclass

@dataclass
class _MinimalContext:
    symbol: str
    timeframe: str
    regime: str = ""
    setup_type: str = ""
```

**Note:** The llm.outcomes payload may not include `symbol`, `timeframe`, `regime` — check what fields are available:

```bash
grep -n '"symbol"\|"timeframe"\|"regime"\|"setup_type"' services/llm_writer_service.py | head -10
```

If those fields are not in the outcome payload, fetch them from the DB row that was just updated. The `llm_calls` table has `symbol`, `timeframe`, `regime`, `setup_type`.

- [ ] **Step 4: Run unit tests**

```bash
.venv/bin/pytest tests/unit/ -q --tb=short 2>&1 | tail -10
```

- [ ] **Step 5: Commit**

```bash
git add services/llm_writer_service.py
git commit -m "feat(llm_writer): call memory_store.record() on signal outcome — closes Zep feedback loop"
```

---

## Task 7: Smoke test

- [ ] **Step 1: Verify Zep is running**

```bash
curl -s http://localhost:8000/healthz
```

- [ ] **Step 2: Test recall and record manually**

```bash
.venv/bin/python - <<'EOF'
import asyncio
from unittest.mock import MagicMock
from src.core.ai.memory import EpisodicMemoryStore

store = EpisodicMemoryStore(base_url="http://localhost:8000")

ctx = MagicMock()
ctx.symbol = "ES"
ctx.timeframe = "5m"
ctx.regime = "trending"
ctx.setup_type = "breakout"

async def run():
    # Record a test outcome
    await store.record(ctx, signal_id="smoke-test-001", outcome="profitable", pnl_r=1.5)
    print("record: ok")

    # Recall
    result = await store.recall(ctx)
    print(f"recall result: '{result[:100]}'")

asyncio.run(run())
EOF
```

Expected: `record: ok`, recall returns a string (may be empty if Zep hasn't indexed yet).

- [ ] **Step 3: Restart alpha swarm and check for errors**

```bash
sudo systemctl restart indicagent-alpha-swarm
sleep 6 && tail -20 logs/alpha_swarm_compute_agent.log | grep -iE "error|memory|zep"
```

Expected: no errors, may see `memory.using_zep_store` log line.

- [ ] **Step 4: Push**

```bash
git push origin main
```

---

## Verification

Phase 5 is complete when:

- [ ] `EpisodicMemoryStore` and `NullMemoryStore` exist at `src/core/ai/memory.py`
- [ ] `build_memory_store(settings)` returns `NullMemoryStore` when `zep_enabled=False`
- [ ] `AgentDeps` has `memory: Any = None`
- [ ] `@agent.system_prompt` hooks wired in all 4 factory functions and `_build_generic_agent`
- [ ] `AlphaSwarmComputeAgent._setup()` calls `build_memory_store` and passes it to registry
- [ ] `llm_writer_service` calls `memory_store.record()` on signal outcome
- [ ] All unit tests pass
- [ ] Zep container is running in docker-compose
- [ ] Smoke test: `record()` and `recall()` work against live Zep

---

## Next: Phase 6 — DSPy Optimizer

When ready, ask for:
> "Write the implementation plan for Phase 6 — DSPy offline prompt optimization."
