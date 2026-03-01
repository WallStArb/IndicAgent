# Ruff Zero & Stream Util Adoption Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Reach 0 ruff errors and wire all 5 remaining services to use the shared `ensure_consumer_group_with_reset` utility instead of their inline xgroup_create/xgroup_setid try/except blocks.

**Architecture:** Two independent passes. Pass 1 fixes cosmetic E501 line-length violations. Pass 2 adopts `src/core/stream_utils.ensure_consumer_group_with_reset` in 5 services — first extending it to return `bool` (freshly_created), then replacing 5 inline implementations.

**Tech Stack:** Python 3.13, redis.asyncio, pytest, ruff

---

## Context

`indicator_service` already uses `ensure_consumer_group_with_reset`. Five services still have inline implementations:
- `feature_writer_service` — bare `except Exception`
- `signal_tracker_service` — bare `except Exception`
- `market_analysis_service` — checks BUSYGROUP but only raises on unknown error
- `ai_narrative_service` — double-nested try/except (buggy: silently swallows xgroup_setid errors)
- `signal_generator_service` — needs `group_freshly_created` bool for warmup rewind logic

`ensure_consumer_group_with_reset` currently returns `None`. We need it to return `bool` so `signal_generator` can use it.

Run all tests with: `.venv/bin/pytest tests/unit/ -x -q`
Check ruff with: `.venv/bin/ruff check .`

---

## Pass 1: Fix E501 (3 lines)

### Task 1: Fix 3 line-too-long violations

**Files:**
- Modify: `production/scripts/historical_backfill.py:776`
- Modify: `tests/unit/intelligence/test_aggregator.py:237`
- Modify: `tests/unit/intelligence/test_cis_plugins.py:416`

**Step 1: Fix backfill.py print f-string (103 chars)**

Current (`production/scripts/historical_backfill.py:776`):
```python
                                f"  {instrument.symbol}/{tf} ({label}, {fetch_days}d): {n} bars stored"
```

Replace with:
```python
                                f"  {instrument.symbol}/{tf}"
                                f" ({label}, {fetch_days}d): {n} bars stored"
```

**Step 2: Fix test_aggregator.py docstring (102 chars)**

Current (`tests/unit/intelligence/test_aggregator.py:237`):
```python
        """AggregatedResult.cis_score, .bucket_scores, .weights_version populated when features given.
        """
```

Replace with:
```python
        """AggregatedResult.cis_score, .bucket_scores, .weights_version populated when
        features are given."""
```

**Step 3: Fix test_cis_plugins.py docstring (104 chars)**

Current (`tests/unit/intelligence/test_cis_plugins.py:416`):
```python
        """cp_probability>0.5, choch_detected, choch_direction=1, hmm toward trend_up → direction==1."""
```

Replace with:
```python
        """cp_probability>0.5, choch_detected, choch_direction=1, hmm toward trend_up
        → direction==1."""
```

**Step 4: Verify ruff is clean**

```bash
.venv/bin/ruff check .
```
Expected: `All checks passed!` (exit 0)

**Step 5: Run tests**

```bash
.venv/bin/pytest tests/unit/ -x -q
```
Expected: all pass

**Step 6: Commit**

```bash
git add production/scripts/historical_backfill.py \
        tests/unit/intelligence/test_aggregator.py \
        tests/unit/intelligence/test_cis_plugins.py
git commit -m "fix(lint): resolve final 3 E501 violations — ruff now clean"
```

---

## Pass 2: Wire services to `ensure_consumer_group_with_reset`

### Task 2: Update utility to return bool

**Files:**
- Modify: `src/core/stream_utils.py`

The utility needs to return `True` if the group was freshly created, `False` if it already existed. `signal_generator_service` uses this for warmup rewind logic.

**Step 1: Update the function signature and return value**

Current `src/core/stream_utils.py`:
```python
async def ensure_consumer_group_with_reset(
    redis_client: redis.Redis,
    stream_name: str,
    group_name: str,
    start_id: str = "$",
    mkstream: bool = True,
) -> None:
    ...
    try:
        await redis_client.xgroup_create(
            stream_name, group_name, start_id, mkstream=mkstream
        )
    except redis.ResponseError as e:
        if "BUSYGROUP" in str(e):
            await redis_client.xgroup_setid(stream_name, group_name, start_id)
        else:
            raise
```

Replace with:
```python
async def ensure_consumer_group_with_reset(
    redis_client: redis.Redis,
    stream_name: str,
    group_name: str,
    start_id: str = "$",
    mkstream: bool = True,
) -> bool:
    """Ensure a consumer group exists, resetting to current tail if it already exists.

    ...

    Returns:
        bool: True if group was freshly created, False if it already existed
    """
    try:
        await redis_client.xgroup_create(
            stream_name, group_name, start_id, mkstream=mkstream
        )
        return True
    except redis.ResponseError as e:
        if "BUSYGROUP" in str(e):
            await redis_client.xgroup_setid(stream_name, group_name, start_id)
            return False
        else:
            raise
```

**Step 2: Verify indicator_service still works (it discards the return value — that's fine)**

```bash
.venv/bin/pytest tests/unit/ -x -q -k "indicator"
```

**Step 3: Commit**

```bash
git add src/core/stream_utils.py
git commit -m "feat(streams): ensure_consumer_group_with_reset returns bool (freshly_created)"
```

---

### Task 3: Wire feature_writer_service

**Files:**
- Modify: `services/feature_writer_service.py`

**Step 1: Add import** (top of file, with other src.core imports around line 32):
```python
from src.core.stream_utils import ensure_consumer_group_with_reset
```

**Step 2: Replace `_setup_consumer_groups` body**

Current (around line 268):
```python
    async def _setup_consumer_groups(self) -> None:
        """Create consumer group for each intelligence:SYMBOL:TF stream."""
        for tf in self.config["service"]["timeframes"]:
            for sym in self.config["service"]["symbols"]:
                stream_name = sk_intelligence(self._env_prefix, sym, tf)
                try:
                    await self.redis_client.xgroup_create(
                        stream_name, CONSUMER_GROUP, "$", mkstream=True
                    )
                    self.logger.debug(
                        "Created consumer group",
                        group=CONSUMER_GROUP,
                        stream=stream_name,
                    )
                except Exception:
                    # Group already exists — reset position to skip stale backlog
                    await self.redis_client.xgroup_setid(
                        stream_name, CONSUMER_GROUP, "$"
                    )
                self._stream_map[stream_name] = (sym, tf)
```

Replace with:
```python
    async def _setup_consumer_groups(self) -> None:
        """Create consumer group for each intelligence:SYMBOL:TF stream."""
        for tf in self.config["service"]["timeframes"]:
            for sym in self.config["service"]["symbols"]:
                stream_name = sk_intelligence(self._env_prefix, sym, tf)
                await ensure_consumer_group_with_reset(
                    self.redis_client, stream_name, CONSUMER_GROUP
                )
                self._stream_map[stream_name] = (sym, tf)
```

**Step 3: Run tests**

```bash
.venv/bin/pytest tests/unit/ -x -q -k "feature_writer"
```

**Step 4: Commit**

```bash
git add services/feature_writer_service.py
git commit -m "refactor(feature-writer): use ensure_consumer_group_with_reset utility"
```

---

### Task 4: Wire signal_tracker_service

**Files:**
- Modify: `services/signal_tracker_service.py`

**Step 1: Add import** (with other src.core imports around line 31):
```python
from src.core.stream_utils import ensure_consumer_group_with_reset
```

**Step 2: Replace `_setup_consumer_groups` body** (around line 278):

Current:
```python
    async def _setup_consumer_groups(self) -> None:
        for symbol in self.config["service"]["symbols"]:
            stream_name = sk_market(self.env_prefix, symbol, "1m")
            try:
                await self.redis_client.xgroup_create(
                    stream_name, self.consumer_group, "$", mkstream=True
                )
            except Exception:
                # Group already exists — reset to current tail to avoid replaying history
                await self.redis_client.xgroup_setid(stream_name, self.consumer_group, "$")
            self._stream_map[stream_name] = (symbol, "1m")
```

Replace with:
```python
    async def _setup_consumer_groups(self) -> None:
        for symbol in self.config["service"]["symbols"]:
            stream_name = sk_market(self.env_prefix, symbol, "1m")
            await ensure_consumer_group_with_reset(
                self.redis_client, stream_name, self.consumer_group
            )
            self._stream_map[stream_name] = (symbol, "1m")
```

**Step 3: Run tests**

```bash
.venv/bin/pytest tests/unit/ -x -q -k "signal_tracker"
```

**Step 4: Commit**

```bash
git add services/signal_tracker_service.py
git commit -m "refactor(signal-tracker): use ensure_consumer_group_with_reset utility"
```

---

### Task 5: Wire market_analysis_service

**Files:**
- Modify: `services/market_analysis_service.py`

**Step 1: Add import** (with other src.core imports around line 38):
```python
from src.core.stream_utils import ensure_consumer_group_with_reset
```

**Step 2: Replace `_setup_consumer_groups` body** (around line 458):

Current:
```python
    async def _setup_consumer_groups(self) -> None:
        for timeframe in self.config["service"]["timeframes"]:
            for symbol in self.config["service"]["symbols"]:
                stream_name = sk_indicators(self.env_prefix, symbol, timeframe)
                self._stream_map[stream_name] = (symbol, timeframe)
                try:
                    await self.redis_client.xgroup_create(
                        stream_name, self.consumer_group, "$", mkstream=True
                    )
                except redis.ResponseError as e:
                    if "BUSYGROUP" in str(e):
                        await self.redis_client.xgroup_setid(stream_name, self.consumer_group, "$")
                    else:
                        raise
```

Replace with:
```python
    async def _setup_consumer_groups(self) -> None:
        for timeframe in self.config["service"]["timeframes"]:
            for symbol in self.config["service"]["symbols"]:
                stream_name = sk_indicators(self.env_prefix, symbol, timeframe)
                self._stream_map[stream_name] = (symbol, timeframe)
                await ensure_consumer_group_with_reset(
                    self.redis_client, stream_name, self.consumer_group
                )
```

**Step 3: Check if `redis` import is still needed elsewhere** — it will be, for type hints / other uses. Leave the import.

**Step 4: Run tests**

```bash
.venv/bin/pytest tests/unit/ -x -q -k "market_analysis"
```

**Step 5: Commit**

```bash
git add services/market_analysis_service.py
git commit -m "refactor(market-analysis): use ensure_consumer_group_with_reset utility"
```

---

### Task 6: Wire ai_narrative_service

**Files:**
- Modify: `services/ai_narrative_service.py`

Note: current implementation has a bug — the `xgroup_setid` call is wrapped in its own `try/except Exception: pass`, silently swallowing errors. The utility fixes this by only ignoring `BUSYGROUP` and re-raising unknown errors.

**Step 1: Add import** (with other src.core imports around line 36):
```python
from src.core.stream_utils import ensure_consumer_group_with_reset
```

**Step 2: Replace `_setup_consumer_groups` body** (around line 396):

Current:
```python
    async def _setup_consumer_groups(self) -> None:
        for tf in self.config["service"]["timeframes"]:
            for sym in self.config["service"]["symbols"]:
                stream_name = signals_aggregated(self.env_prefix, sym, tf)
                try:
                    await self.redis_client.xgroup_create(
                        stream_name, self.consumer_group, "$", mkstream=True
                    )
                except Exception:
                    # Group exists — force-reset to current tail to skip stale backlog
                    try:
                        await self.redis_client.xgroup_setid(
                            stream_name, self.consumer_group, "$"
                        )
                    except Exception:
                        pass
                self._stream_map[stream_name] = (sym, tf)
```

Replace with:
```python
    async def _setup_consumer_groups(self) -> None:
        for tf in self.config["service"]["timeframes"]:
            for sym in self.config["service"]["symbols"]:
                stream_name = signals_aggregated(self.env_prefix, sym, tf)
                await ensure_consumer_group_with_reset(
                    self.redis_client, stream_name, self.consumer_group
                )
                self._stream_map[stream_name] = (sym, tf)
```

**Step 3: Run tests**

```bash
.venv/bin/pytest tests/unit/ -x -q -k "ai_narrative"
```

**Step 4: Commit**

```bash
git add services/ai_narrative_service.py
git commit -m "refactor(ai-narrative): use ensure_consumer_group_with_reset, fix silent error swallow"
```

---

### Task 7: Wire signal_generator_service

**Files:**
- Modify: `services/signal_generator_service.py`

Note: `signal_generator` uses `group_freshly_created` to decide whether to rewind the stream before processing. The utility now returns `bool` for exactly this purpose.

**Step 1: Add import** (with other src.core imports around line 39):
```python
from src.core.stream_utils import ensure_consumer_group_with_reset
```

**Step 2: Replace the group creation try/except in `_setup_consumer_groups`** (around line 355):

Current block (inside the sym/tf loop):
```python
                group_freshly_created = False
                try:
                    # Create at $ (current end) for new groups only
                    await self.redis_client.xgroup_create(
                        stream_name, self.consumer_group, "$", mkstream=True
                    )
                    group_freshly_created = True
                except redis.ResponseError as e:
                    if "BUSYGROUP" not in str(e):
                        raise
                    # Group already exists - reset to current tail to skip stale backlog
                    await self.redis_client.xgroup_setid(stream_name, self.consumer_group, "$")
```

Replace with:
```python
                group_freshly_created = await ensure_consumer_group_with_reset(
                    self.redis_client, stream_name, self.consumer_group
                )
```

The warmup rewind block that follows uses `group_freshly_created` — leave it unchanged.

**Step 3: Run tests**

```bash
.venv/bin/pytest tests/unit/ -x -q -k "signal_generator"
```

**Step 4: Run full test suite**

```bash
.venv/bin/pytest tests/unit/ -x -q
```
Expected: all pass

**Step 5: Verify ruff still clean**

```bash
.venv/bin/ruff check .
```
Expected: `All checks passed!`

**Step 6: Commit**

```bash
git add services/signal_generator_service.py
git commit -m "refactor(signal-generator): use ensure_consumer_group_with_reset utility"
```

---

## Final Verification

```bash
.venv/bin/pytest tests/unit/ -q
.venv/bin/ruff check .
```

Expected:
- All tests pass
- `All checks passed!` (0 ruff errors)
