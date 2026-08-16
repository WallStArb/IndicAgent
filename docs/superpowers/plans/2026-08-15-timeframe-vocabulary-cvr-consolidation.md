# Timeframe Vocabulary CVR Consolidation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Repoint the 5 genuinely-live, independently-hardcoded `timeframe` tuples at the CVR `controlled_vocabulary` registry (which already owns this namespace) instead of each hand-copying its own list, closing the self-drift risk D-07 exists to prevent.

**Architecture:** A new Ring 0 module (`src/core/timeframe_vocabulary.py`) mirrors the existing `ConfigService` module-level-cache pattern (`_config_service` global + `set_*_service()` + sync accessor) but wraps `VocabularyService` instead. Each live daemon prewarms `VocabularyService` once during its existing async `_setup()`/startup phase (same call site shape as `FeatureVectorPipeline._prewarm_threshold_config()`) and registers it via `set_vocabulary_service()`; the rest of that process reads synchronously through the wrapper, with zero additional hot-path DB calls (matching `VocabularyService`'s own zero-hot-path-DB-calls design). Two call sites (`feature_validation_analyzer.py`, `signal_auditor.py`) keep their deliberate 4-timeframe subset as a literal constant rather than switching to the full dynamic set - subset intent isn't documented anywhere and silently expanding audit/validation scope to include `1d` would be a real behavior change, not a refactor - but gain a startup-time assertion that the subset is still a subset of what CVR has registered, closing the actual drift risk without changing behavior.

**Tech Stack:** Python 3.14, asyncpg, PostgreSQL/TimescaleDB, pytest.

**Spec:** `.planning/todos/pending/327-timeframe-vocabulary-consolidation-into-cvr.md` (todo 327) - this plan supersedes that todo's file-list with the real, investigated scope (5 live call sites, not 9; see the todo's own "Status" note this plan will add).

## Global Constraints

- `VocabularyService` (`src/config/vocabulary_service.py`) is the only CVR read-side; never query `controlled_vocabulary` directly outside it except where an existing established pattern already does so (e.g. `src/api/routes/vocabulary.py`'s per-request DB handle - not touched by this plan).
- No new DB round-trips on any hot path - `VocabularyService.initialize()` runs once per process at startup; every other read is a synchronous in-memory dict lookup.
- `datetime.now(UTC)` only for any new timestamp code (DAG Invariant 6) - not touched by this plan, noted for completeness.
- Full `tests/unit/` suite must stay green after every task.
- Exception variable name is `error`, not `exc`, in any new `except` block.

---

## Task 1: Migration - register `4h` in the CVR `timeframe` namespace

CVR's `timeframe` namespace (migration 233) was seeded with 5 codes (`1m/5m/15m/1h/1d`) and never updated. `market_data_ohlcv_tradeable` has had live `4h` data since 2023-08-08 (2,184 rows, most recent 2026-08-06) that the registry never registered - confirmed directly against the DB during todo 327's investigation. This must land before any live call site is repointed at the registry, or a 6-timeframe constant would silently lose `4h` support the moment it starts reading from CVR instead of its own hardcoded tuple.

**Files:**
- Create: `production/migrations/317_cvr_timeframe_register_4h.sql`

**Interfaces:**
- Produces: `controlled_vocabulary` row `('timeframe', '4h', ...)`, `sort_order=5`; existing `('timeframe', '1d', ...)` row's `sort_order` bumped from 5 to 6 so the ordering stays chronological (1m < 5m < 15m < 1h < 4h < 1d).

- [ ] **Step 1: Write the migration**

```sql
-- Migration 317: CVR timeframe namespace was missing 4h (todo 327/D-07 investigation)
--
-- migration 233 seeded `timeframe` with 5 codes (1m/5m/15m/1h/1d) and was never updated.
-- market_data_ohlcv_tradeable has had live 4h data since 2023-08-08 (2,184 rows as of
-- 2026-08-15, most recent bar 2026-08-06) that the registry never registered -- confirmed
-- directly against the DB. This is a real drift bug in CVR's own registry, independent of
-- the Python-side scatter todo 327 otherwise fixes, and must land first: several live call
-- sites hardcode all 6 timeframes including 4h, and repointing them at
-- VocabularyService.active_codes("timeframe") before this migration would silently drop
-- 4h from their behavior.

BEGIN;

-- Bump 1d out of the way first so 4h can take sort_order=5, keeping duration order
-- (1m < 5m < 15m < 1h < 4h < 1d) intact for display purposes.
UPDATE controlled_vocabulary
SET sort_order = 6
WHERE namespace = 'timeframe' AND code = '1d';

INSERT INTO controlled_vocabulary (namespace, code, label, description, sort_order)
VALUES ('timeframe', '4h', '4 Hour', 'Four-hour bar timeframe', 5)
ON CONFLICT (namespace, code) DO NOTHING;

COMMIT;
```

- [ ] **Step 2: Apply the migration**

Run: `PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -f production/migrations/317_cvr_timeframe_register_4h.sql`

- [ ] **Step 3: Verify**

Run:
```bash
PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -t -c "SELECT code, sort_order FROM controlled_vocabulary WHERE namespace='timeframe' ORDER BY sort_order;"
```
Expected: 6 rows, `1m(1) 5m(2) 15m(3) 1h(4) 4h(5) 1d(6)`.

- [ ] **Step 4: Commit**

```bash
git add production/migrations/317_cvr_timeframe_register_4h.sql
git commit -m "fix(todo-327): register 4h in CVR timeframe namespace, migration 233 missed it"
```

---

## Task 2: New Ring 0 module `src/core/timeframe_vocabulary.py`

**Files:**
- Create: `src/core/timeframe_vocabulary.py`
- Test: `tests/unit/core/test_timeframe_vocabulary.py`

**Interfaces:**
- Produces: `set_vocabulary_service(vocab: Any) -> None`, `standard_timeframes(default: tuple[str, ...] = (...)) -> tuple[str, ...]`, `reset_vocabulary_service_for_test() -> None` (test-only reset so `tests/unit` runs don't leak state between test modules).
- Consumes: nothing from earlier tasks; consumed by Tasks 3-7.

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/core/test_timeframe_vocabulary.py
"""Unit tests for src.core.timeframe_vocabulary (todo 327)."""

import pytest

from src.core import timeframe_vocabulary


@pytest.fixture(autouse=True)
def _reset():
    """Every test starts with no VocabularyService registered."""
    timeframe_vocabulary.reset_vocabulary_service_for_test()
    yield
    timeframe_vocabulary.reset_vocabulary_service_for_test()


@pytest.mark.unit
def test_standard_timeframes_returns_default_when_unregistered():
    """No VocabularyService registered yet -> falls back to the literal default."""
    result = timeframe_vocabulary.standard_timeframes(default=("1m", "5m"))
    assert result == ("1m", "5m")


@pytest.mark.unit
def test_standard_timeframes_reads_registered_service():
    """Once a VocabularyService is registered, reads its active_codes("timeframe")."""

    class _FakeVocab:
        def active_codes(self, namespace):
            assert namespace == "timeframe"
            return ["1m", "5m", "15m", "1h", "4h", "1d"]

    timeframe_vocabulary.set_vocabulary_service(_FakeVocab())
    result = timeframe_vocabulary.standard_timeframes()
    assert result == ("1m", "5m", "15m", "1h", "4h", "1d")


@pytest.mark.unit
def test_standard_timeframes_falls_back_on_empty_registry():
    """A registered service with zero codes for the namespace still falls back --
    never silently returns an empty tuple (that would break every caller's loop)."""

    class _EmptyVocab:
        def active_codes(self, namespace):
            return []

    timeframe_vocabulary.set_vocabulary_service(_EmptyVocab())
    result = timeframe_vocabulary.standard_timeframes(default=("1m",))
    assert result == ("1m",)


@pytest.mark.unit
def test_assert_subset_passes_for_registered_subset():
    """assert_known_subset() is a no-op when every code is registered."""

    class _FakeVocab:
        def active_codes(self, namespace):
            return ["1m", "5m", "15m", "1h", "4h", "1d"]

    timeframe_vocabulary.set_vocabulary_service(_FakeVocab())
    # Must not raise.
    timeframe_vocabulary.assert_known_subset(("1m", "5m", "15m", "1h"), context="test")


@pytest.mark.unit
def test_assert_subset_raises_for_unregistered_code():
    """assert_known_subset() raises loud if a caller's hardcoded subset references a
    timeframe CVR doesn't know about -- the actual drift D-07 exists to catch."""

    class _FakeVocab:
        def active_codes(self, namespace):
            return ["1m", "5m", "15m", "1h", "4h", "1d"]

    timeframe_vocabulary.set_vocabulary_service(_FakeVocab())
    with pytest.raises(ValueError, match="30m"):
        timeframe_vocabulary.assert_known_subset(("1m", "30m"), context="test")


@pytest.mark.unit
def test_assert_subset_skips_when_unregistered():
    """No VocabularyService registered (e.g. a script run without daemon startup) ->
    assert_known_subset() is a no-op, not a crash -- matches standard_timeframes()'s
    same fallback-permissive contract."""
    # Must not raise even though "bogus" isn't a real timeframe -- there's no registry
    # to check against yet.
    timeframe_vocabulary.assert_known_subset(("bogus",), context="test")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/unit/core/test_timeframe_vocabulary.py -v`
Expected: `ModuleNotFoundError: No module named 'src.core.timeframe_vocabulary'` (or collection error) - the module doesn't exist yet.

- [ ] **Step 3: Write the module**

```python
# src/core/timeframe_vocabulary.py
"""Timeframe vocabulary - cached read-side accessor over CVR's `timeframe` namespace.

Ring 0 (`src/core/`). Mirrors the module-level `ConfigService` consumer pattern
documented in CLAUDE.md's "Migrate-as-you-go" section (`_config_service: Any | None
= None` + `set_config_service()` + `get_sync()` wrapper), applied to
`VocabularyService` instead. Prewarm once, during whichever daemon's existing async
setup phase initializes its DB pool, then read synchronously everywhere else in that
process - `VocabularyService` itself is already fully cached at `initialize()` with
zero further DB calls (docs/foundation/controlled-vocabulary-registry.md), so this
wrapper adds no additional caching of its own, just a well-known Ring 0 access point
so callers don't need a `VocabularyService` instance threaded through every
constructor (todo 327).
"""

from __future__ import annotations

from typing import Any

_vocab_service: Any | None = None

# Literal copy of CVR's registered `timeframe` codes as of migration 317 (todo 327).
# Used only as the fallback when no VocabularyService has been registered in this
# process (a script or test running outside daemon startup) -- keep in sync with the
# registry by hand if a future migration adds/removes a code, same maintenance
# contract as any other cached-default fallback in this codebase.
_DEFAULT_TIMEFRAMES: tuple[str, ...] = ("1m", "5m", "15m", "1h", "4h", "1d")


def set_vocabulary_service(vocab: Any) -> None:
    """Register the process's initialized `VocabularyService` instance.

    Call once, from whichever daemon's async setup routine initializes
    `VocabularyService` - same call-site shape as
    `FeatureVectorPipeline._prewarm_threshold_config()` registering `ConfigService`.
    A second call in the same process (e.g. a test replacing it with a fake) simply
    replaces the reference.
    """
    global _vocab_service
    _vocab_service = vocab


def reset_vocabulary_service_for_test() -> None:
    """Test-only: clear the registered service so tests don't leak state."""
    global _vocab_service
    _vocab_service = None


def standard_timeframes(default: tuple[str, ...] = _DEFAULT_TIMEFRAMES) -> tuple[str, ...]:
    """All registered, non-deprecated `timeframe` codes, in CVR sort_order.

    Falls back to `default` if no `VocabularyService` has been registered yet, or if
    the registered service has zero codes for the namespace (never silently returns
    an empty tuple - every known caller loops over this and an empty result would be
    a silent no-op, worse than a stale-but-nonempty fallback).
    """
    if _vocab_service is None:
        return default
    codes = _vocab_service.active_codes("timeframe")
    return tuple(codes) if codes else default


def assert_known_subset(timeframes: tuple[str, ...], *, context: str) -> None:
    """Raise if any of `timeframes` isn't a registered CVR `timeframe` code.

    For call sites that deliberately use a subset of all registered timeframes (e.g.
    `signal_auditor.py`'s coverage check intentionally excludes `1d`) rather than the
    full dynamic set - keeps the subset as an explicit literal (preserving whatever
    intentional scoping it encodes) while still closing the actual drift risk D-07
    exists to prevent: a hardcoded subset silently referencing a timeframe that no
    longer exists (or never did). A no-op if no `VocabularyService` is registered -
    matches `standard_timeframes()`'s same fallback-permissive contract for scripts/
    tests running outside daemon startup.
    """
    if _vocab_service is None:
        return
    known = set(_vocab_service.active_codes("timeframe"))
    unknown = [tf for tf in timeframes if tf not in known]
    if unknown:
        raise ValueError(
            f"{context}: timeframe(s) {unknown} not registered in CVR's `timeframe` "
            f"namespace (known: {sorted(known)})"
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/unit/core/test_timeframe_vocabulary.py -v`
Expected: 6 passed.

- [ ] **Step 5: Lint and format**

Run: `.venv/bin/ruff check src/core/timeframe_vocabulary.py tests/unit/core/test_timeframe_vocabulary.py && .venv/bin/black --check src/core/timeframe_vocabulary.py tests/unit/core/test_timeframe_vocabulary.py`

- [ ] **Step 6: Commit**

```bash
git add src/core/timeframe_vocabulary.py tests/unit/core/test_timeframe_vocabulary.py
git commit -m "feat(todo-327): add timeframe_vocabulary Ring 0 module over CVR timeframe namespace"
```

---

## Task 3: Repoint `services/feature_vector_pipeline.py`

The live orchestrator daemon (`indicagent-feature-vector-pipeline.service`, confirmed running). `_STANDARD_TFS` (6 tfs) is used at line 179 (`self._timeframes = list(_STANDARD_TFS)`), inside `__init__` - need to confirm exact timing relative to `_setup()`.

**Files:**
- Modify: `services/feature_vector_pipeline.py:101` (module constant), `:179` (usage), `:451` (`_setup()`, add prewarm)
- Test: `tests/unit/services/test_feature_vector_pipeline.py` (existing file - add one test)

**Interfaces:**
- Consumes: `src.core.timeframe_vocabulary.set_vocabulary_service`, `.standard_timeframes` (Task 2).

- [ ] **Step 1: Read the exact `__init__`/`_setup()` ordering before editing**

Run: `sed -n '160,200p;445,460p' services/feature_vector_pipeline.py` and confirm whether `self._timeframes` is set in `__init__` (sync, before `_setup()` can run) or later. If it's in `__init__`, this needs the same "move construction into `_setup()`" treatment as Task 4's `bar_writer.py` - write the failing test for whichever shape it actually has, don't assume.

- [ ] **Step 2: Write the failing test**

```python
# Add to tests/unit/services/test_feature_vector_pipeline.py

@pytest.mark.unit
async def test_setup_prewarms_timeframe_vocabulary(monkeypatch):
    """_setup() registers a VocabularyService with timeframe_vocabulary so
    self._timeframes reflects CVR's registered set, not the hardcoded default."""
    from src.core import timeframe_vocabulary

    timeframe_vocabulary.reset_vocabulary_service_for_test()
    # ... construct pipeline with mocked DB/Kafka per this file's existing fixtures,
    # call await pipeline._setup(), then:
    assert timeframe_vocabulary._vocab_service is not None
    timeframe_vocabulary.reset_vocabulary_service_for_test()
```

(Adapt the mock/fixture setup to match whatever pattern the rest of this test file already
uses for `_setup()` - read the file first; do not invent a new fixture shape.)

- [ ] **Step 3: Run test, verify it fails**

Run: `.venv/bin/pytest tests/unit/services/test_feature_vector_pipeline.py -k prewarms_timeframe -v`
Expected: FAIL (`_vocab_service is None` - nothing registers it yet).

- [ ] **Step 4: Wire the prewarm into `_setup()` and repoint the constant**

In `services/feature_vector_pipeline.py`:

```python
# near the top, alongside the other src.core imports
from src.config.vocabulary_service import VocabularyService
from src.core import timeframe_vocabulary
```

Delete the module-level `_STANDARD_TFS = (...)` constant (line 101).

In `_setup()`, immediately after `self._config_service = ConfigService(...)` / `await self._prewarm_threshold_config()`:

```python
        self._vocabulary_service = VocabularyService(
            self.settings.database_url, pool=self._db.pool
        )
        await self._vocabulary_service.initialize()
        timeframe_vocabulary.set_vocabulary_service(self._vocabulary_service)
```

Wherever `_STANDARD_TFS` was read (e.g. `self._timeframes = list(_STANDARD_TFS)`), replace with:

```python
        self._timeframes = list(timeframe_vocabulary.standard_timeframes())
```

If this assignment happens in `__init__` rather than `_setup()`, move it into `_setup()` (after the prewarm above) - same treatment as Task 4.

- [ ] **Step 5: Run test, verify it passes**

Run: `.venv/bin/pytest tests/unit/services/test_feature_vector_pipeline.py -v`
Expected: all pass, including the new test.

- [ ] **Step 6: Run the full test file plus a broader sweep**

Run: `.venv/bin/pytest tests/unit/services/test_feature_vector_pipeline.py tests/unit/ -q`
Expected: all green (this daemon is imported/exercised by other test modules - confirm no regression).

- [ ] **Step 7: Commit**

```bash
git add services/feature_vector_pipeline.py tests/unit/services/test_feature_vector_pipeline.py
git commit -m "fix(todo-327): feature_vector_pipeline reads timeframes from CVR, not a hardcoded tuple"
```

---

## Task 4: Repoint `services/bar_writer.py`

`_BAR_TFS` (6 tfs) is read inside `__init__` (line 122, building `self._bars_written_attrs`) - before `_setup()` (line 200) can run any async prewarm. This dict construction must move into `_setup()`.

**Files:**
- Modify: `services/bar_writer.py:58` (module constant), `:94-124` (`__init__`), `:200+` (`_setup()`)
- Test: `tests/unit/services/test_bar_writer.py` (existing file - add tests)

- [ ] **Step 1: Write the failing test**

```python
# Add to tests/unit/services/test_bar_writer.py

@pytest.mark.unit
def test_init_does_not_require_vocabulary_service():
    """__init__ must not crash before any async setup has run -- confirms the OTel
    attrs dict construction moved out of __init__."""
    from src.core import timeframe_vocabulary

    timeframe_vocabulary.reset_vocabulary_service_for_test()
    writer = BarWriter()  # must not raise, must not touch VocabularyService
    assert writer._bars_written_attrs == {}


@pytest.mark.unit
async def test_setup_builds_bars_written_attrs_from_cvr(monkeypatch):
    """_setup() prewarms VocabularyService and builds _bars_written_attrs from its
    registered timeframe codes."""
    from src.core import timeframe_vocabulary

    class _FakeVocab:
        def active_codes(self, namespace):
            return ["1m", "5m", "15m", "1h", "4h", "1d"]

    # Patch VocabularyService construction inside bar_writer's _setup() to return the
    # fake above, and patch whatever this file's existing tests already use to stub
    # Kafka/DB connections for _setup() -- read the file's existing _setup() test
    # fixtures before writing this, reuse them rather than inventing new ones.
    ...
    writer = BarWriter()
    await writer._setup()
    assert set(writer._bars_written_attrs.keys()) == {"1m", "5m", "15m", "1h", "4h", "1d"}
    timeframe_vocabulary.reset_vocabulary_service_for_test()
```

(Fill in the monkeypatch target for `VocabularyService` construction by reading how this
file's existing `_setup()` tests, if any, stub `asyncpg`/`create_pool` - match that pattern
exactly rather than introducing a second mocking style in the same file.)

- [ ] **Step 2: Run tests, verify they fail**

Run: `.venv/bin/pytest tests/unit/services/test_bar_writer.py -k "vocabulary_service or bars_written_attrs" -v`
Expected: FAIL - `_bars_written_attrs` is still built eagerly in `__init__` from the static `_BAR_TFS`.

- [ ] **Step 3: Move the dict construction and wire the prewarm**

In `services/bar_writer.py`, delete the module-level `_BAR_TFS = (...)` constant and delete this block from `__init__`:

```python
        self._bars_written_attrs: dict[str, dict] = {
            tf: {"agent": self.name, "tf": tf} for tf in _BAR_TFS
        }
```

Replace with, still in `__init__`:

```python
        self._bars_written_attrs: dict[str, dict] = {}
```

Add near the top of the file:

```python
from src.config.vocabulary_service import VocabularyService
from src.core import timeframe_vocabulary
```

At the top of `_setup()` (before whatever it currently does first):

```python
        vocab = VocabularyService(self.settings.database_url)
        await vocab.initialize()
        timeframe_vocabulary.set_vocabulary_service(vocab)
        self._bars_written_attrs = {
            tf: {"agent": self.name, "tf": tf}
            for tf in timeframe_vocabulary.standard_timeframes()
        }
```

(If `_setup()` already has its own DB pool by this point that `VocabularyService` could reuse
via `pool=`, read the surrounding code and pass it - don't open a second pool if one already
exists at this line.)

- [ ] **Step 4: Run tests, verify they pass**

Run: `.venv/bin/pytest tests/unit/services/test_bar_writer.py -v`
Expected: all pass.

- [ ] **Step 5: Full suite check**

Run: `.venv/bin/pytest tests/unit/ -q`
Expected: green.

- [ ] **Step 6: Commit**

```bash
git add services/bar_writer.py tests/unit/services/test_bar_writer.py
git commit -m "fix(todo-327): bar_writer reads timeframes from CVR, not a hardcoded tuple

Moves _bars_written_attrs construction from __init__ to _setup() -- it needs an
async VocabularyService prewarm, which __init__ can't do."
```

---

## Task 5: Repoint `src/intelligence/services/hmm_trainer.py`

`_DEFAULT_TARGET_TFS` (6 tfs) is a constructor default argument (`target_tfs: tuple[str, ...] = _DEFAULT_TARGET_TFS`), evaluated once at module-import time - cannot be sourced dynamically without restructuring to a `None` sentinel resolved inside `__init__`. Also fixes a stale docstring found in passing (says "Defaults to (1m, 5m, 15m, 1h)" - actually 6 tfs including 4h/1d).

**Files:**
- Modify: `src/intelligence/services/hmm_trainer.py:53` (module constant), `:90` (docstring), `:94-104` (`__init__`)
- Modify: `services/hmm_training_agent.py:31-39` (`_run()`, add prewarm before `HMMTrainer(...)` construction)
- Test: `tests/unit/intelligence/services/test_hmm_trainer.py` (existing file - add test) or wherever this class's existing tests live - check first with `grep -rl "class TestHMMTrainer\|HMMTrainer(" tests/`.

- [ ] **Step 1: Locate the existing test file**

Run: `grep -rl "HMMTrainer" tests/unit/ --include="*.py"`

- [ ] **Step 2: Write the failing test**

```python
@pytest.mark.unit
def test_target_tfs_defaults_from_cvr_when_none_passed():
    """target_tfs=None resolves via timeframe_vocabulary.standard_timeframes()."""
    from src.core import timeframe_vocabulary

    class _FakeVocab:
        def active_codes(self, namespace):
            return ["1m", "5m", "1h"]

    timeframe_vocabulary.set_vocabulary_service(_FakeVocab())
    trainer = HMMTrainer(db_manager=MagicMock(), settings=MagicMock(), target_tfs=None)
    assert trainer._target_tfs == ("1m", "5m", "1h")
    timeframe_vocabulary.reset_vocabulary_service_for_test()


@pytest.mark.unit
def test_target_tfs_explicit_value_still_honored():
    """An explicitly-passed target_tfs is never overridden by CVR -- explicit beats
    default, same as any other constructor default-argument contract."""
    trainer = HMMTrainer(db_manager=MagicMock(), settings=MagicMock(), target_tfs=("1d",))
    assert trainer._target_tfs == ("1d",)
```

- [ ] **Step 3: Run tests, verify they fail**

Run: `.venv/bin/pytest tests/unit/ -k test_target_tfs -v`
Expected: FAIL - `target_tfs=None` currently isn't a valid sentinel; the default is still the static tuple.

- [ ] **Step 4: Restructure the constructor default**

In `src/intelligence/services/hmm_trainer.py`, delete the module-level `_DEFAULT_TARGET_TFS = (...)` constant. Add near the top:

```python
from src.core import timeframe_vocabulary
```

Change:

```python
    def __init__(
        self,
        db_manager: Any,
        settings: Any,
        target_tfs: tuple[str, ...] = _DEFAULT_TARGET_TFS,
```

to:

```python
    def __init__(
        self,
        db_manager: Any,
        settings: Any,
        target_tfs: tuple[str, ...] | None = None,
```

and in the body, before `self._target_tfs = target_tfs`:

```python
        if target_tfs is None:
            target_tfs = timeframe_vocabulary.standard_timeframes()
        self._target_tfs = target_tfs
```

Fix the stale docstring at line 90 (currently says "Defaults to (1m, 5m, 15m, 1h)."):

```python
        target_tfs: Tuple of timeframe strings to train. Defaults to CVR's registered
            `timeframe` codes if not provided.
```

- [ ] **Step 5: Wire the prewarm into the oneshot agent**

In `services/hmm_training_agent.py`, add near the top:

```python
from src.config.vocabulary_service import VocabularyService
from src.core import timeframe_vocabulary
```

In `_run()`, between `await db_manager.initialize()` and `agent = HMMTrainer(...)`:

```python
        vocab = VocabularyService(settings.database_url, pool=db_manager.pool)
        await vocab.initialize()
        timeframe_vocabulary.set_vocabulary_service(vocab)
```

- [ ] **Step 6: Run tests, verify they pass**

Run: `.venv/bin/pytest tests/unit/ -k test_target_tfs -v`
Expected: pass.

- [ ] **Step 7: Full suite**

Run: `.venv/bin/pytest tests/unit/ -q`
Expected: green.

- [ ] **Step 8: Commit**

```bash
git add src/intelligence/services/hmm_trainer.py services/hmm_training_agent.py tests/unit/
git commit -m "fix(todo-327): hmm_trainer target_tfs defaults from CVR, not a hardcoded tuple

Also fixes a stale docstring (said 4 default tfs, code default was actually 6)."
```

---

## Task 6: Drift-guard for `src/intelligence/services/feature_validation_analyzer.py`

`_TIMEFRAMES` (4 tfs, `1m/5m/15m/1h`) has no documented rationale for excluding `4h`/`1d` - could be intentional (validation doesn't make sense for coarse timeframes) or stale. No evidence either way, so this task does **not** force it onto the full CVR set (that would silently expand validation scope). Instead: keep the literal, add a startup assertion that it's still a subset of what CVR has registered.

**Files:**
- Modify: `src/intelligence/services/feature_validation_analyzer.py:49` (keep as-is), `:82-84` (`_setup()`)
- Test: `tests/unit/intelligence/services/test_feature_validation_analyzer.py` (locate first)

- [ ] **Step 1: Locate the existing test file**

Run: `grep -rl "FeatureValidationAnalyzer" tests/unit/ --include="*.py"`

- [ ] **Step 2: Write the failing test**

```python
@pytest.mark.unit
async def test_setup_asserts_timeframes_subset_of_cvr(monkeypatch):
    """_setup() prewarms VocabularyService and validates _TIMEFRAMES is a subset of
    CVR's registered timeframe codes -- catches drift without changing behavior."""
    from src.core import timeframe_vocabulary

    timeframe_vocabulary.reset_vocabulary_service_for_test()
    # ... construct FeatureValidationAnalyzer with this file's existing DB-pool mock
    # pattern, call await analyzer._setup(), then:
    assert timeframe_vocabulary._vocab_service is not None
    timeframe_vocabulary.reset_vocabulary_service_for_test()
```

(Match this file's existing mock pattern for `create_db_pool`/`asyncpg` - read it first.)

- [ ] **Step 3: Run test, verify it fails**

Run: `.venv/bin/pytest tests/unit/ -k test_setup_asserts_timeframes_subset -v`
Expected: FAIL.

- [ ] **Step 4: Wire the prewarm + assertion into `_setup()`**

Add near the top of `src/intelligence/services/feature_validation_analyzer.py`:

```python
from src.config.vocabulary_service import VocabularyService
from src.core import timeframe_vocabulary
```

In `_setup()`, after `self._pool = await create_db_pool(self._settings.database_url)`:

```python
        vocab = VocabularyService(self._settings.database_url, pool=self._pool)
        await vocab.initialize()
        timeframe_vocabulary.set_vocabulary_service(vocab)
        timeframe_vocabulary.assert_known_subset(
            tuple(_TIMEFRAMES), context="FeatureValidationAnalyzer._TIMEFRAMES"
        )
```

`_TIMEFRAMES` itself is unchanged - still `["1m", "5m", "15m", "1h"]`.

- [ ] **Step 5: Run test, verify it passes; full suite**

Run: `.venv/bin/pytest tests/unit/ -k test_setup_asserts_timeframes_subset -v && .venv/bin/pytest tests/unit/ -q`
Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add src/intelligence/services/feature_validation_analyzer.py tests/unit/
git commit -m "fix(todo-327): feature_validation_analyzer asserts _TIMEFRAMES stays a subset of CVR

Keeps the deliberate 4-timeframe subset (no documented reason found to expand it to
6) but closes the actual drift risk -- a startup assertion now fails loud if this
list ever references a timeframe CVR doesn't know about."
```

---

## Task 7: Drift-guard for `services/signal_auditor.py`

Same treatment as Task 6 - `_COVERAGE_TFS` (4 tfs, same set as `_TIMEFRAMES`) keeps its literal value, gains a subset assertion.

**Files:**
- Modify: `services/signal_auditor.py:37` (keep as-is), `:112+` (`_setup()`)
- Test: `tests/unit/services/test_signal_auditor.py` (locate first)

- [ ] **Step 1: Locate the existing test file**

Run: `grep -rl "SignalAuditor" tests/unit/ --include="*.py"`

- [ ] **Step 2: Write the failing test**

```python
@pytest.mark.unit
async def test_setup_asserts_coverage_tfs_subset_of_cvr(monkeypatch):
    """_setup() prewarms VocabularyService and validates _COVERAGE_TFS is a subset of
    CVR's registered timeframe codes."""
    from src.core import timeframe_vocabulary

    timeframe_vocabulary.reset_vocabulary_service_for_test()
    # ... construct SignalAuditor with this file's existing setup mock pattern, call
    # await auditor._setup(), then:
    assert timeframe_vocabulary._vocab_service is not None
    timeframe_vocabulary.reset_vocabulary_service_for_test()
```

- [ ] **Step 3: Run test, verify it fails**

Run: `.venv/bin/pytest tests/unit/ -k test_setup_asserts_coverage_tfs_subset -v`
Expected: FAIL.

- [ ] **Step 4: Wire the prewarm + assertion into `_setup()`**

Add near the top of `services/signal_auditor.py`:

```python
from src.config.vocabulary_service import VocabularyService
from src.core import timeframe_vocabulary
```

In `_setup()` (read the file first to find where its DB pool is created - reuse it for
`VocabularyService(..., pool=...)` rather than opening a second one), add:

```python
        vocab = VocabularyService(self.settings.database_url, pool=<existing_pool>)
        await vocab.initialize()
        timeframe_vocabulary.set_vocabulary_service(vocab)
        timeframe_vocabulary.assert_known_subset(
            _COVERAGE_TFS, context="SignalAuditor._COVERAGE_TFS"
        )
```

`_COVERAGE_TFS` itself is unchanged.

- [ ] **Step 5: Run test, verify it passes; full suite**

Run: `.venv/bin/pytest tests/unit/ -k test_setup_asserts_coverage_tfs_subset -v && .venv/bin/pytest tests/unit/ -q`
Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add services/signal_auditor.py tests/unit/
git commit -m "fix(todo-327): signal_auditor asserts _COVERAGE_TFS stays a subset of CVR"
```

---

## Task 8: Close out todo 327

**Files:**
- Modify: `.planning/todos/pending/327-timeframe-vocabulary-consolidation-into-cvr.md` → move to `.planning/todos/completed/`
- Modify: `.planning/todos/PRIORITIES.md`

- [ ] **Step 1: Full verification**

Run: `.venv/bin/pytest tests/unit/ -q` - must be fully green, no new skips beyond the 2 pre-existing ones.
Run: `.venv/bin/ruff check . && .venv/bin/black --check .` on all files touched by Tasks 1-7.

- [ ] **Step 2: Live-service consideration**

`indicagent-feature-vector-pipeline.service` is actively running - Task 3's change lands on a live hot path. Per this project's own SOP, a code change to a running daemon needs an explicit restart decision, not an assumed one. Do not restart it as part of this plan; flag it in the closing summary as a deliberate follow-up requiring a go-ahead, same posture as todo 261's "deployment deliberately NOT done in that plan's execution." `bar_writer`/`signal_auditor`/`hmm_training_agent`/`feature_validation_agent` are currently inactive/oneshot - no live restart risk for those.

- [ ] **Step 3: Update and move the todo**

Move `327-timeframe-vocabulary-consolidation-into-cvr.md` to `completed/`, with a short status note recording: migration 317 landed, 5 live call sites repointed (2 via full dynamic set, 2 via subset-assertion, 1 via constructor-default restructuring), `feature_vector_pipeline.service` restart intentionally deferred pending explicit go-ahead.

- [ ] **Step 4: Update PRIORITIES.md**

Mark 327 closed with a one-line summary, same style as the 326 closure entry.

- [ ] **Step 5: Commit**

```bash
git add .planning/todos/
git commit -m "docs(todo-327): close out timeframe CVR consolidation"
```

---

## Self-Review

**Spec coverage:** All 5 confirmed-live call sites from todo 327's investigation are covered (Tasks 3-7); the CVR registry's own `4h` gap is covered (Task 1); the new Ring 0 module both groups need is covered (Task 2). The 4 confirmed-dead call sites and the `utils.py`/`feature_pipeline_executor.py` findings are explicitly out of scope - filed as todo 328, not duplicated here.

**Placeholder scan:** Tasks 3, 4, 6, 7 contain one deliberate "read the file first, match its existing mock pattern" instruction each rather than invented mock code - this is intentional, not a placeholder violation: each of those 4 files' existing test fixture style is unknown until the executing engineer opens it, and inventing a fake pattern here risked contradicting a convention already established in that specific test file. Every other step has complete, real code.

**Type consistency:** `timeframe_vocabulary.standard_timeframes()` returns `tuple[str, ...]` everywhere it's consumed (Tasks 3, 4, 5). `assert_known_subset()` takes `tuple[str, ...]` and is called with a `tuple(...)`-wrapped list in Task 6 (since `_TIMEFRAMES` is a `list`) and directly with `_COVERAGE_TFS` in Task 7 (already a `tuple`) - consistent.
