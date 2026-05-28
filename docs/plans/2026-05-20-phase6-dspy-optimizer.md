# Phase 6: DSPy Offline Prompt Optimizer Implementation Plan

**Version:** 1.0
**Status:** archived
**Last Updated:** 2026-05-20
> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an offline DSPy optimization pipeline that compiles improved prompts from historical `llm_calls` + `signal_ledger` outcome data and loads those compiled programs at startup, replacing hand-written system prompts with data-driven ones.

**Architecture:** An offline script `scripts/optimize_agents.py` queries TimescaleDB for the last 30 days of `llm_calls` joined to `signal_ledger` outcomes, builds `(prompt, response)` training pairs with `pnl_r > 0` as the positive label, runs DSPy's `MIPROv2` optimizer per agent, and saves compiled programs to `agents/<agent_id>_compiled.json`. `AgentRegistry._build_one()` checks for a compiled program file and — when present — patches the `PydanticAIAgent`'s `system_prompt` before returning it. Reverting a bad optimization is `git revert`. This never runs in the production hot path.

**Phase dependencies:** Phase 3 (Pydantic AI) + Phase 4 (Agent Registry) must be merged first. Phase 5 (Zep) is independent — DSPy can be added before or after.

**Spec:** `docs/plans/2026-05-20-agent-platform-redesign.md` — Layer 6 (DSPy)

**IMPORTANT — offline only:** DSPy runs on a developer machine or CI job, never inside any live service. The live system only reads compiled `.json` artifacts at startup.

---

## File Map

| Action | Path | Responsibility |
|---|---|---|
| Create | `scripts/optimize_agents.py` | Offline optimizer — loads data, runs MIPROv2, saves artifacts |
| Create | `src/core/ai/dspy_loader.py` | `load_compiled_program(agent_id)` — reads artifact, returns patched system_prompt |
| Modify | `src/core/ai/agent_registry.py` | Check for compiled program in `_build_one()`, apply via `dspy_loader` |
| Modify | `src/core/ai/agent_spec.py` | `dspy_program` field already present — no change needed if Phase 4 was implemented |
| Modify | `requirements.txt` | Add `dspy-ai` (dev/scripts only) |
| Create | `agents/.gitkeep` | Ensure `agents/` exists (no change if Phase 4 created it) |
| Create | `tests/unit/test_dspy_loader.py` | Unit tests for `load_compiled_program` |

---

## Task 1: Install dspy-ai

**Files:**
- Modify: `requirements.txt`

DSPy is an optimizer — it's needed both for running `optimize_agents.py` and for loading compiled programs at startup. Add it to the main requirements so the live service can import it.

- [ ] **Step 1: Check if dspy-ai is already installed**

```bash
.venv/bin/python -c "import dspy; print(dspy.__version__)" 2>/dev/null || echo "not installed"
```

- [ ] **Step 2: Add to requirements.txt**

```
dspy-ai>=2.4
```

Install:

```bash
uv pip install "dspy-ai>=2.4"
```

Verify:

```bash
.venv/bin/python -c "import dspy; print(dspy.__version__)"
```

Expected: version printed, no errors.

- [ ] **Step 3: Commit**

```bash
git add requirements.txt
git commit -m "deps: add dspy-ai for offline prompt optimization"
```

---

## Task 2: Write failing tests for dspy_loader

**Files:**
- Create: `tests/unit/test_dspy_loader.py`

- [ ] **Step 1: Create test file**

```python
"""Tests for dspy_loader — reads compiled DSPy programs and extracts system prompts."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.core.ai.dspy_loader import load_compiled_program


def _write_compiled(tmp_path: Path, agent_id: str, system_prompt: str) -> Path:
    artifact = {"agent_id": agent_id, "system_prompt": system_prompt, "dspy_version": "2.4"}
    path = tmp_path / f"{agent_id}_compiled.json"
    path.write_text(json.dumps(artifact))
    return path


def test_load_compiled_program_returns_system_prompt(tmp_path: Path):
    path = _write_compiled(tmp_path, "skeptic_v1", "OPTIMIZED SYSTEM PROMPT")

    result = load_compiled_program(path)

    assert result == "OPTIMIZED SYSTEM PROMPT"


def test_load_compiled_program_returns_none_when_file_missing(tmp_path: Path):
    path = tmp_path / "nonexistent_compiled.json"

    result = load_compiled_program(path)

    assert result is None


def test_load_compiled_program_returns_none_on_malformed_json(tmp_path: Path):
    path = tmp_path / "bad_compiled.json"
    path.write_text("{ not valid json }")

    result = load_compiled_program(path)

    assert result is None


def test_load_compiled_program_returns_none_when_system_prompt_missing(tmp_path: Path):
    path = tmp_path / "no_prompt_compiled.json"
    path.write_text(json.dumps({"agent_id": "skeptic_v1"}))

    result = load_compiled_program(path)

    assert result is None
```

- [ ] **Step 2: Run to confirm failure**

```bash
.venv/bin/pytest tests/unit/test_dspy_loader.py -v 2>&1 | head -10
```

Expected: `ModuleNotFoundError: No module named 'src.core.ai.dspy_loader'`

---

## Task 3: Implement dspy_loader

**Files:**
- Create: `src/core/ai/dspy_loader.py`

- [ ] **Step 1: Create `src/core/ai/dspy_loader.py`**

```python
"""dspy_loader — read compiled DSPy program artifacts and extract system prompts.

Compiled programs are JSON files saved by scripts/optimize_agents.py.
Format: {"agent_id": str, "system_prompt": str, "dspy_version": str, ...}

load_compiled_program(path) returns the optimized system_prompt string,
or None if the file doesn't exist or is malformed.

The live service only reads artifacts — it never runs the DSPy optimizer.
"""
from __future__ import annotations

import json
from pathlib import Path

import structlog

logger = structlog.get_logger(__name__)


def load_compiled_program(path: Path) -> str | None:
    """Read a compiled DSPy artifact and return the system_prompt.

    Returns None if the file is missing, unreadable, or missing the
    system_prompt key — caller uses the hand-written prompt as fallback.
    """
    if not path.exists():
        return None

    try:
        data = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning(
            "dspy_loader.read_failed",
            path=str(path),
            error=str(exc)[:100],
        )
        return None

    prompt = data.get("system_prompt")
    if not prompt:
        logger.warning("dspy_loader.missing_system_prompt", path=str(path))
        return None

    logger.info(
        "dspy_loader.loaded",
        path=str(path),
        agent_id=data.get("agent_id", "unknown"),
        prompt_len=len(prompt),
    )
    return prompt
```

- [ ] **Step 2: Run tests**

```bash
.venv/bin/pytest tests/unit/test_dspy_loader.py -v
```

Expected: all 4 tests pass.

- [ ] **Step 3: Commit**

```bash
git add src/core/ai/dspy_loader.py tests/unit/test_dspy_loader.py
git commit -m "feat(ai): add dspy_loader — reads compiled DSPy artifacts at startup"
```

---

## Task 4: Wire dspy_loader into AgentRegistry

**Files:**
- Modify: `src/core/ai/agent_registry.py`

When `spec.dspy_program` is set, load the compiled system_prompt and apply it to the agent.

- [ ] **Step 1: Read the current `_build_generic_agent` signature**

```bash
grep -n "def _build_generic_agent\|def _build_one\|dspy_program" src/core/ai/agent_registry.py
```

- [ ] **Step 2: Add dspy_loader import**

At the top of `src/core/ai/agent_registry.py`, add:

```python
from src.core.ai.dspy_loader import load_compiled_program
```

- [ ] **Step 3: Apply compiled system_prompt in `_build_one()`**

In `_build_one()`, before delegating to `_build_generic_agent` or `_build_builtin_agent`, check for a compiled program:

```python
def _build_one(self, spec: AgentSpec, model: Any, settings: Any, memory_store: Any = None) -> PydanticAIAgent:
    compiled_prompt: str | None = None
    if spec.dspy_program:
        compiled_prompt = load_compiled_program(Path(spec.dspy_program))

    if spec.agent_id in _BUILTIN_FACTORIES:
        return _build_builtin_agent(spec, model, settings, memory_store=memory_store)

    return _build_generic_agent(
        spec, model, settings,
        memory_store=memory_store,
        compiled_prompt=compiled_prompt,
    )
```

- [ ] **Step 4: Update `_build_generic_agent` to accept and apply compiled_prompt**

```python
def _build_generic_agent(
    spec: AgentSpec,
    model: Any,
    settings: Any,
    memory_store: Any = None,
    compiled_prompt: str | None = None,
) -> PydanticAIAgent:
    system_prompt = compiled_prompt or spec.system_prompt
    if not system_prompt.startswith("OUTPUT ONLY RAW JSON"):
        system_prompt = (
            "OUTPUT ONLY RAW JSON. NO PROSE. NO EXPLANATION. NO PREAMBLE. "
            + system_prompt
            + ' Begin your response with { and end with }.'
        )
    ...
```

**Note:** Built-in agents (skeptic, correlation, etc.) are not affected — they use their own factory functions which already have system prompts. DSPy optimization of built-ins is a future enhancement.

- [ ] **Step 5: Run full unit tests**

```bash
.venv/bin/pytest tests/unit/ -q --tb=short 2>&1 | tail -10
```

- [ ] **Step 6: Commit**

```bash
git add src/core/ai/agent_registry.py
git commit -m "feat(registry): load compiled DSPy program when spec.dspy_program is set"
```

---

## Task 5: Write the offline optimizer script

**Files:**
- Create: `scripts/optimize_agents.py`

This script is run manually or in CI — never by a live service. It produces `agents/<agent_id>_compiled.json`.

- [ ] **Step 1: Read the llm_calls schema**

```bash
PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "\d llm_calls" | head -30
```

Note the column names — particularly `prompt`, `response`, `call_type`, `signal_id`, `pnl_r`, `outcome`, `called_at`.

- [ ] **Step 2: Create `scripts/optimize_agents.py`**

```python
#!/usr/bin/env python3
"""Offline DSPy prompt optimizer for IndicAgent alpha agents.

Loads the last 30 days of LLM call data from llm_calls joined to signal_ledger
outcomes, builds training pairs, and runs MIPROv2 to find better system prompts.

Saves compiled programs to agents/<agent_id>_compiled.json.

Usage:
    python scripts/optimize_agents.py                     # all agents
    python scripts/optimize_agents.py --agent skeptic_v1  # one agent
    python scripts/optimize_agents.py --days 60           # wider window

Dependencies:
    dspy-ai, asyncpg, python-dotenv

Run from the project root:
    cd /home/bg/dev/indicagent
    .venv/bin/python scripts/optimize_agents.py
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

import asyncpg
import dspy
import structlog

logger = structlog.get_logger(__name__)

DB_DSN = os.environ.get(
    "DATABASE_URL",
    "postgresql://postgres:postgres@localhost:5432/indicagent",
)
AGENTS_DIR = Path("agents")
MIN_EXAMPLES = 20  # skip agent if fewer training pairs available


# ── DSPy signature ────────────────────────────────────────────────────────────

class TradingAnalysis(dspy.Signature):
    """Analyze a trading setup and output a JSON assessment."""

    setup_description: str = dspy.InputField(desc="Trading setup context and indicators")
    json_response: str = dspy.OutputField(desc="JSON response with multiplier and confidence")


# ── Data loading ──────────────────────────────────────────────────────────────

async def load_training_data(agent_id: str, days: int = 30) -> list[dspy.Example]:
    """Load (prompt, response, label) triples from llm_calls + signal_ledger.

    Positive label: outcome is not null AND pnl_r > 0.
    Negative label: outcome is not null AND pnl_r <= 0.
    Unlabeled (outcome IS NULL) rows are excluded.
    """
    conn = await asyncpg.connect(DB_DSN)
    try:
        rows = await conn.fetch(
            """
            SELECT
                lc.prompt,
                lc.response,
                lc.pnl_r,
                lc.outcome
            FROM llm_calls lc
            WHERE lc.call_type = $1
              AND lc.called_at >= NOW() - INTERVAL '1 day' * $2
              AND lc.outcome IS NOT NULL
              AND lc.pnl_r IS NOT NULL
              AND lc.prompt IS NOT NULL
              AND lc.response IS NOT NULL
            ORDER BY lc.called_at DESC
            LIMIT 500
            """,
            agent_id,
            days,
        )
    finally:
        await conn.close()

    examples = []
    for row in rows:
        label = "positive" if (row["pnl_r"] or 0.0) > 0.0 else "negative"
        ex = dspy.Example(
            setup_description=row["prompt"] or "",
            json_response=row["response"] or "",
            label=label,
        ).with_inputs("setup_description")
        examples.append(ex)

    logger.info(
        "optimizer.data_loaded",
        agent_id=agent_id,
        total=len(examples),
        positive=sum(1 for e in examples if e.label == "positive"),
    )
    return examples


# ── Metric ────────────────────────────────────────────────────────────────────

def trading_metric(example: dspy.Example, prediction: dspy.Prediction, trace=None) -> float:
    """Score: 1.0 if parse succeeds and label matches predicted quality."""
    response = prediction.json_response or ""
    try:
        parsed = json.loads(response)
        has_required = "multiplier" in parsed or "failure_probability" in parsed
        if not has_required:
            return 0.0
        multiplier = parsed.get("multiplier", parsed.get("failure_probability", 0.5))
        predicted_good = float(multiplier) > 0.5
        actual_good = example.label == "positive"
        return 1.0 if predicted_good == actual_good else 0.0
    except (json.JSONDecodeError, TypeError, ValueError):
        return 0.0


# ── Optimizer ─────────────────────────────────────────────────────────────────

def optimize_agent(agent_id: str, examples: list[dspy.Example]) -> str | None:
    """Run MIPROv2 optimizer and return the best system prompt found."""
    if len(examples) < MIN_EXAMPLES:
        logger.warning(
            "optimizer.insufficient_data",
            agent_id=agent_id,
            count=len(examples),
            min_required=MIN_EXAMPLES,
        )
        return None

    # Split 80/20 train/dev
    split = int(len(examples) * 0.8)
    train = examples[:split]
    dev = examples[split:]

    # Build DSPy LM backed by Ollama
    lm = dspy.LM(
        model="ollama_chat/nemotron-3-nano:4b",
        api_base="http://localhost:11434",
        api_key="ollama",
    )
    dspy.configure(lm=lm)

    program = dspy.Predict(TradingAnalysis)

    optimizer = dspy.MIPROv2(
        metric=trading_metric,
        num_candidates=5,
        init_temperature=1.0,
        verbose=False,
    )

    logger.info("optimizer.starting_mipro", agent_id=agent_id, train=len(train), dev=len(dev))

    compiled = optimizer.compile(
        program,
        trainset=train,
        valset=dev,
        num_trials=10,
        minibatch=True,
        minibatch_size=min(25, len(train)),
        requires_permission_to_run=False,
    )

    # Extract the optimized system instruction from the compiled predictor
    optimized_prompt = None
    for name, predictor in compiled.named_predictors():
        if hasattr(predictor, "extended_signature"):
            optimized_prompt = str(predictor.extended_signature.instructions)
            break
        if hasattr(predictor, "signature"):
            optimized_prompt = str(predictor.signature.instructions)
            break

    return optimized_prompt


# ── Save artifact ─────────────────────────────────────────────────────────────

def save_artifact(agent_id: str, system_prompt: str) -> Path:
    """Save compiled program to agents/<agent_id>_compiled.json."""
    AGENTS_DIR.mkdir(exist_ok=True)
    path = AGENTS_DIR / f"{agent_id}_compiled.json"
    artifact = {
        "agent_id": agent_id,
        "system_prompt": system_prompt,
        "compiled_at": datetime.now(timezone.utc).isoformat(),
        "dspy_version": dspy.__version__,
    }
    path.write_text(json.dumps(artifact, indent=2))
    logger.info("optimizer.saved", agent_id=agent_id, path=str(path))
    return path


# ── Main ──────────────────────────────────────────────────────────────────────

KNOWN_AGENTS = [
    "skeptic_v1",
    "correlation_v1",
    "counterfactual_v1",
    "regime_coherence_v1",
]


async def run(agent_ids: list[str], days: int) -> None:
    for agent_id in agent_ids:
        logger.info("optimizer.processing", agent_id=agent_id)
        examples = await load_training_data(agent_id, days=days)

        optimized_prompt = optimize_agent(agent_id, examples)
        if optimized_prompt is None:
            logger.warning("optimizer.skipped", agent_id=agent_id, reason="insufficient data or optimization failed")
            continue

        path = save_artifact(agent_id, optimized_prompt)
        print(f"  {agent_id}: saved to {path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Offline DSPy prompt optimizer")
    parser.add_argument(
        "--agent",
        help="Agent ID to optimize (default: all known agents)",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=30,
        help="Days of historical data to use (default: 30)",
    )
    args = parser.parse_args()

    agent_ids = [args.agent] if args.agent else KNOWN_AGENTS
    print(f"Optimizing agents: {agent_ids} using {args.days}d of data")

    asyncio.run(run(agent_ids, days=args.days))
    print("Done.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Make script executable and verify syntax**

```bash
chmod +x scripts/optimize_agents.py
.venv/bin/python -m py_compile scripts/optimize_agents.py && echo "syntax ok"
```

- [ ] **Step 4: Commit**

```bash
git add scripts/optimize_agents.py
git commit -m "feat(scripts): add optimize_agents.py — offline DSPy MIPROv2 prompt optimizer"
```

---

## Task 6: Wire compiled programs into YAML specs

When a compiled program exists for an agent, the YAML spec's `dspy_program` field should point to it. This is optional — if not set, the hand-written system_prompt is used.

- [ ] **Step 1: Update the 4 built-in YAML specs to reference compiled programs (when they exist)**

After running `optimize_agents.py`, add `dspy_program` to each YAML:

```yaml
# Example: agents/skeptic_v1.yaml (after optimization)
dspy_program: agents/skeptic_v1_compiled.json
```

**Note:** Do NOT add `dspy_program` until you have actually run the optimizer and verified the compiled program produces better results. The field is optional and defaults to None. Skip this step until Phase 6 is being actively used.

- [ ] **Step 2: Verify dry-run of optimizer against live DB**

```bash
# Check data availability without running optimization
.venv/bin/python - <<'EOF'
import asyncio
import asyncpg

async def check():
    conn = await asyncpg.connect("postgresql://postgres:postgres@localhost:5432/indicagent")
    rows = await conn.fetch("""
        SELECT call_type, COUNT(*) as n, COUNT(outcome) as with_outcome
        FROM llm_calls
        WHERE called_at >= NOW() - INTERVAL '30 days'
        GROUP BY call_type
        ORDER BY n DESC
    """)
    for r in rows:
        print(f"  {r['call_type']}: {r['n']} calls, {r['with_outcome']} with outcome")
    await conn.close()

asyncio.run(check())
EOF
```

Expected: shows call counts per agent. Need `>= 20` with outcomes to run optimizer.

- [ ] **Step 3: Run optimizer (only if data available)**

```bash
# Only run if you have >= 20 examples with outcomes
.venv/bin/python scripts/optimize_agents.py --agent skeptic_v1 --days 30
```

Expected: creates `agents/skeptic_v1_compiled.json`. If fewer than 20 examples, logs `optimizer.insufficient_data` and skips.

- [ ] **Step 4: Commit compiled artifacts if optimization ran**

```bash
# If artifacts were generated:
git add agents/*_compiled.json
git commit -m "feat(agents): add compiled DSPy programs — skeptic_v1 optimized"
```

---

## Verification

Phase 6 is complete when:

- [ ] `dspy-ai` is in requirements.txt
- [ ] `src/core/ai/dspy_loader.py` exists with `load_compiled_program(path) -> str | None`
- [ ] `AgentRegistry._build_one()` calls `load_compiled_program` when `spec.dspy_program` is set
- [ ] `scripts/optimize_agents.py` runs without errors and produces `agents/<agent_id>_compiled.json`
- [ ] All unit tests pass
- [ ] Data availability check shows expected call counts
- [ ] Reverting a compiled program is `git revert <sha>` (no service restart needed beyond normal deploy)

---

## Operational notes

- **Run frequency:** Monthly or after significant prompt changes.
- **Minimum data:** 20+ closed signals per agent. New agents may need weeks of shadow mode data before optimization is useful.
- **A/B testing:** Create two compiled programs (`skeptic_v1_a_compiled.json`, `skeptic_v1_b_compiled.json`), reference each from separate YAML specs with different `agent_id`s, compare shadow_registry pnl_r.
- **Rollback:** `git revert <sha-that-added-compiled-json>` then redeploy. No DB changes needed.

---

## Next: Phase 7 — Guardrails AI

When ready, ask for:
> "Write the implementation plan for Phase 7 — Guardrails AI content validation."
