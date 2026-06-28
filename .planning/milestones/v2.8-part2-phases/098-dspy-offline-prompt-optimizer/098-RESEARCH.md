# Phase 098: DSPy Offline Prompt Optimizer - Research

**Researched:** 2026-06-02
**Domain:** DSPy BootstrapFewShot, batch job patterns, prompt versioning, A/B routing
**Confidence:** HIGH (core patterns from codebase + official DSPy docs; some DSPy API details MEDIUM from web verification)

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

- **D-01**: Use `dspy.BootstrapFewShot` only. No MIPROv2, no COPRO.
- **D-02**: Optimize against `parse_success` (boolean column in `llm_calls`). Not `pnl_r`, not win rate.
- **D-03**: Per-agent independent runs. One ineligible agent never blocks another.
- **D-04**: Import each agent's `PROMPT_REGISTRY` and use `ACTIVE_VERSION` template as the DSPy Signature base. DB is only output — no Python prompt files modified.
- **D-05**: `prompt_versions` table: `version_id UUID PK`, `agent_id TEXT`, `version_tag TEXT UNIQUE`, `compiled_prompt JSONB`, `status TEXT CHECK ('candidate','active','retired')`, `created_at TIMESTAMPTZ DEFAULT NOW()`, `promoted_at TIMESTAMPTZ`.
- **D-06**: Prompt version loaded at `BaseGroupCoordinator` startup only. No DB read in live inference path. Takes effect on next systemd restart.
- **D-07**: Data gate `COUNT(*) >= 500` per agent in `llm_calls WHERE outcome IS NOT NULL`. Emit `job_completed_total{status="skipped_data_gate"}` when zero agents eligible.
- **D-08**: Weekly cadence, Monday 02:00 ET.
- **D-09**: Auto-promote after 7 days when: parse_success_candidate > baseline + 0.02, n >= 100 A/B calls, regime balance >= 20 examples each of regime 0/1/2. Extend 7 more days if regime balance unmet.
- **D-10**: Write `logs/dspy_optimizer_report_{date}.json`. No new DB table.
- **D-11**: Emit `job_completed_total{job="dspy-optimizer", status}` at exit. Status values: `success`, `failure`, `skipped_data_gate`.
- **Phase boundary**: `services/dspy_optimizer.py` (entrypoint) + `src/intelligence/optimization/dspy_optimizer.py` (core class) + migration `prompt_versions` table + `indicagent-dspy-optimizer.service` + `.timer`.
- **Depends on Phase 096**: `AgentRegistry`, `AgentDependencies`, `BaseGroupCoordinator._setup()` prompt injection.

### Claude's Discretion

- DSPy Signature field naming conventions for this domain.
- Internal retry/timeout handling if Ollama is unavailable during optimization.
- Exact JSONB structure of `compiled_prompt` field (DSPy's native serialization format).
- Whether to run compilation with the same Ollama model used in production or a dedicated optimization model.

### Deferred Ideas (OUT OF SCOPE)

- Cross-agent joint prompt optimization (COPRO).
- Hot-swap prompts without service restart.
- Prompt optimization for I1-I6 (non-LLM) plugins.
</user_constraints>

---

## Summary

Phase 098 builds an offline, timer-triggered DSPy optimizer that reads labeled `(prompt, input, parse_success)` tuples from `llm_calls`, compiles per-agent few-shot variants using `dspy.BootstrapFewShot`, stores them in a new `prompt_versions` table as JSONB, and auto-promotes after a 7-day A/B window with regime-balance guard.

The implementation mirrors the `ml_training_agent.py` / `MLTrainer` batch job pattern exactly: a thin `services/dspy_optimizer.py` entrypoint wraps a `DSPyOptimizer` class in `src/intelligence/optimization/`. DSPy 3.2.1 (current: `pip install dspy`) is the correct package name — `dspy-ai` is the old name. The compiled program state is a JSON file that DSPy's `program.save()` / `program.load()` round-trips cleanly; the planner should store this JSON string in the `compiled_prompt` JSONB column.

The critical design constraint (DAG Invariant 3) means prompt version is injected at service startup via `AgentDependencies` (Phase 096 deliverable — not yet built). Phase 098 depends on Phase 096 being complete. The data gate at >= 500 labeled rows per agent will likely not be met on first run; the optimizer must exit cleanly with `status="skipped_data_gate"`.

**Primary recommendation:** Follow `ml_training_agent.py` + `MLTrainer` as the canonical pattern. Use DSPy 3.2.1, `dspy.BootstrapFewShot`, JSON state saving (not whole-program pickle). One Signature per agent type, wrapping the existing `PROMPT_REGISTRY[ACTIVE_VERSION]` docstring.

---

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `dspy` | 3.2.1 (latest) | BootstrapFewShot compilation, Signature, Predict, save/load | Official Stanford NLP DSPy package (not `dspy-ai`, which is old name) |
| `asyncpg` | existing | Read `llm_calls`, write `prompt_versions` | Project-standard asyncpg; already in requirements |
| `structlog` | existing | Per-agent gate check, compilation duration, promotion results | Project-standard logging |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `litellm` (via DSPy's `dspy.LM`) | bundled in dspy | DSPy LM adapter talking to Ollama | Required for DSPy to call the LLM during bootstrap compilation |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `BootstrapFewShot` | `MIPROv2` | MIPROv2 requires meta-LLM calls during optimization — circular cost on local Ollama. Locked to BootstrapFewShot per D-01. |
| JSON state save | Whole-program cloudpickle save | Pickle is opaque, not queryable, version-sensitive. JSON is readable, storable in JSONB, forward-compatible. |

**Installation:**
```bash
uv pip install dspy
# Add to requirements.txt: dspy>=3.2.1
```

---

## Architecture Patterns

### Recommended Project Structure
```
services/
└── dspy_optimizer.py            # Oneshot entrypoint (mirrors ml_training_agent.py)

src/intelligence/optimization/
├── __init__.py
└── dspy_optimizer.py            # DSPyOptimizer class (mirrors ml_trainer.py)

production/migrations/
└── 115_prompt_versions.sql      # prompt_versions table + CHECK constraint

production/systemd/
├── indicagent-dspy-optimizer.service
└── indicagent-dspy-optimizer.timer
```

### Pattern 1: Oneshot Entrypoint (CANONICAL — copy ml_training_agent.py exactly)
**What:** Thin `main()` that instantiates the optimizer class, calls `asyncio.run(agent.start())`, emits `JOB_COMPLETED_TOTAL`, and calls `flush_and_shutdown_metrics()`.
**When to use:** All timer-triggered batch jobs in this codebase. Type=oneshot in systemd.

```python
# Source: services/ml_training_agent.py (canonical)
from src.observability.metrics import JOB_COMPLETED_TOTAL, flush_and_shutdown_metrics

def main() -> None:
    try:
        settings = Settings()
        agent = DSPyOptimizer(settings)
        asyncio.run(agent.start())
        JOB_COMPLETED_TOTAL.add(1, {"job": "dspy-optimizer", "status": "success"})
    except Exception as exc:
        JOB_COMPLETED_TOTAL.add(1, {"job": "dspy-optimizer", "status": "failure"})
        raise exc
    finally:
        flush_and_shutdown_metrics()
```

The `status="skipped_data_gate"` case is emitted from INSIDE `DSPyOptimizer._run()` before the early return — not from `main()`. The outer `main()` still emits `"success"` (clean exit is success; gate skip is not a failure).

### Pattern 2: DSPy Signature Wrapping Existing Prompts
**What:** A DSPy `Signature` class wraps the existing `PROMPT_REGISTRY[ACTIVE_VERSION]` template as its `instructions` docstring. DSPy uses the docstring as the instruction prefix in the compiled prompt.
**When to use:** For every agent being optimized. One Signature class per agent module.

```python
# Source: DSPy official docs (dspy.ai/learn/programming/signatures)
import dspy
from src.intelligence.ai.alpha.correlation_prompts import PROMPT_REGISTRY, ACTIVE_VERSION

class CorrelationSignature(dspy.Signature):
    # Docstring becomes the instruction block; use the existing prompt template stripped of format vars
    """You are a cross-asset coherence analyst evaluating whether intermarket behavior supports or contradicts a trading signal."""
    prompt_context: str = dspy.InputField(desc="Full signal context with intermarket data")
    coherence_score: float = dspy.OutputField(desc="Float 0.0-1.0: degree of cross-asset support")
    confidence: float = dspy.OutputField(desc="Float 0.0-1.0: confidence in assessment")
    reasoning: str = dspy.OutputField(desc="One sentence explaining the intermarket stance")
```

**Important:** The PROMPT_REGISTRY template uses Python `{format}` placeholders for runtime context injection. DSPy Signatures do not use format strings — they define typed fields. The optimizer builds a `Predict(CorrelationSignature)` module, not a raw string formatter. The planner must decide the field decomposition per agent type.

### Pattern 3: BootstrapFewShot Compilation Loop
**What:** Per agent, query labeled rows, build `dspy.Example` trainset, compile, serialize to JSON, write to `prompt_versions`.

```python
# Source: DSPy API docs (dspy.ai/api/optimizers/BootstrapFewShot/)
import dspy
from dspy.teleprompt import BootstrapFewShot

# 1. Configure DSPy LM (same Ollama model as production)
lm = dspy.LM(
    f"ollama_chat/{settings.ollama_model}",
    api_base="http://localhost:11434",
    api_key=""
)
dspy.configure(lm=lm)

# 2. Build student program
student = dspy.Predict(CorrelationSignature)

# 3. Build trainset from llm_calls rows
trainset = [
    dspy.Example(
        prompt_context=row["prompt"],
        # ground truth for metric evaluation
        parse_success=row["parse_success"],
    ).with_inputs("prompt_context")
    for row in labeled_rows
]

# 4. Define metric — parse_success is the signal
def parse_success_metric(example, pred, trace=None) -> bool:
    # During bootstrap, metric evaluates PREDICTED output against expected
    # For parse_success: did the model produce parseable JSON?
    # Implementation: try parsing pred output as JSON, return bool
    return _try_parse_json(pred)  # True if parseable

# 5. Compile
optimizer = BootstrapFewShot(
    metric=parse_success_metric,
    max_bootstrapped_demos=4,
    max_labeled_demos=16,
    max_rounds=1,
)
compiled = optimizer.compile(student, trainset=trainset)

# 6. Save to JSON string for JSONB storage
import tempfile, json, pathlib
with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
    tmp_path = f.name
compiled.save(tmp_path)
compiled_json = json.loads(pathlib.Path(tmp_path).read_text())
# compiled_json is a dict with "predict" key containing demos list
```

### Pattern 4: Metric Function — Parse Success Gate
**What:** The BootstrapFewShot metric function must work for BOOTSTRAPPING (predicting from context, then evaluating), not just labeled evaluation. For parse_success optimization, the metric evaluates whether the model's output is parseable JSON.

```python
def parse_success_metric(example: dspy.Example, pred: dspy.Prediction, trace=None) -> bool:
    """Return True if the predicted output fields produce valid JSON.
    
    During bootstrap, DSPy runs the student program on each training example
    and passes the PREDICTED output to this metric. We want demos where the
    model produced structurally valid output — those become the few-shot examples.
    """
    try:
        import json
        # pred has attributes matching OutputField names
        # Verify all required fields are present and numeric fields are floats
        score = float(pred.coherence_score)
        conf = float(pred.confidence)
        return 0.0 <= score <= 1.0 and 0.0 <= conf <= 1.0
    except (AttributeError, ValueError, TypeError):
        return False
```

**Key insight:** The metric is called during compilation with the PREDICTED values (not the labeled ground truth from `llm_calls.parse_success`). The labeled `parse_success` column is used to BUILD the trainset — only rows with `parse_success=TRUE` and `outcome IS NOT NULL` become training examples for bootstrapping. Rows with `parse_success=FALSE` can be used as negative examples to make the trainset more diverse, but the core gate uses `outcome IS NOT NULL` as the labeled signal gate.

### Pattern 5: DSPy LM Configuration for Ollama
```python
# Source: DSPy docs + verified via web search
import dspy

lm = dspy.LM(
    model=f"ollama_chat/{settings.ollama_model}",  # e.g. "ollama_chat/nemotron-3-nano:4b"
    api_base="http://localhost:11434",
    api_key="",
    timeout=120,  # Ollama local inference can be slow
    max_retries=2,
)
dspy.configure(lm=lm)
```

**Discretion recommendation:** Use the same `OLLAMA_MODEL` from `.env` (via `settings.ollama_model`) as production inference. This ensures the few-shot examples are calibrated to the same model being optimized. No dedicated optimization model needed.

### Pattern 6: Save/Load Round-Trip for JSONB Storage

DSPy `program.save(path)` writes a JSON file. The JSON structure contains:
- `"predict"` key with `"demos"` list (each demo is input/output fields)
- `"lm"` configuration
- Signature metadata

```python
# SAVE (at compile time — in dspy_optimizer.py)
import json, pathlib, tempfile

with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as f:
    tmp_path = pathlib.Path(f.name)
compiled.save(str(tmp_path))
compiled_dict = json.loads(tmp_path.read_text())
tmp_path.unlink()  # cleanup
# Store compiled_dict in prompt_versions.compiled_prompt (JSONB)

# LOAD (at startup — in BaseGroupCoordinator._setup() via AgentDependencies)
import json, pathlib, tempfile

compiled_dict = row["compiled_prompt"]  # asyncpg returns dict from JSONB
student = dspy.Predict(CorrelationSignature)
with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as f:
    json.dump(compiled_dict, f)
    tmp_path = pathlib.Path(f.name)
student.load(str(tmp_path))
tmp_path.unlink()
# Now student has demos injected; wrap in agent for inference
```

**Simpler alternative (planner's discretion):** Store `compiled_dict["predict"]["demos"]` only (the demos list) as the JSONB content, and reconstruct the `Predict` module at startup by directly setting `student.demos = loaded_demos`. This avoids the temp file round-trip and is more transparent. The planner should evaluate both approaches — the demos-only approach is simpler and more auditable.

### Pattern 7: Migration — `prompt_versions` Table

```sql
-- Source: migration pattern from production/migrations/084_ai_enrichment_tables.sql
-- and 099_dlq_quarantine.sql (CHECK constraint pattern)

CREATE TABLE IF NOT EXISTS prompt_versions (
    version_id      UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_id        TEXT        NOT NULL,
    version_tag     TEXT        UNIQUE NOT NULL,  -- e.g. "correlation_v1_dspy_20260602"
    compiled_prompt JSONB       NOT NULL,
    status          TEXT        NOT NULL DEFAULT 'candidate'
                                CHECK (status IN ('candidate', 'active', 'retired')),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    promoted_at     TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_prompt_versions_agent_status
    ON prompt_versions (agent_id, status);
```

Migration number: use `115_prompt_versions.sql` (next after `114_calibration_curves_add_timeframe.sql`).

### Pattern 8: systemd Timer Unit (Monday 02:00 ET)

```ini
# indicagent-dspy-optimizer.service
[Unit]
Description=IndicAgent DSPy Offline Prompt Optimizer -- weekly BootstrapFewShot compilation
After=network.target indicagent-infrastructure.target
Requires=indicagent-infrastructure.target

[Service]
Type=oneshot
User=bg
WorkingDirectory=/home/bg/dev/indicagent
Environment=PYTHONPATH=/home/bg/dev/indicagent
Environment=PYTHONUNBUFFERED=1
ExecStart=/home/bg/dev/indicagent/.venv/bin/python services/dspy_optimizer.py
TimeoutStartSec=7200

[Install]
WantedBy=multi-user.target
```

```ini
# indicagent-dspy-optimizer.timer
[Unit]
Description=DSPy Optimizer Timer -- weekly Monday 07:00 UTC (02:00 ET)

[Timer]
OnCalendar=Mon *-*-* 07:00:00 UTC
Persistent=true
Unit=indicagent-dspy-optimizer.service

[Install]
WantedBy=timers.target
```

**Note:** Monday 02:00 ET = 07:00 UTC (ET is UTC-5 in winter, UTC-4 in summer). Use 07:00 UTC as the conservative anchor; close enough to 02:00 ET year-round for a weekly batch job.

### Anti-Patterns to Avoid

- **Calling Ollama during live inference for DSPy**: DSPy compilation must happen ONLY in the batch job. Do not import dspy or call `dspy.configure()` in any daemon service.
- **Saving whole-program with cloudpickle** (`save_program=True`): Cloudpickle is version-sensitive and opaque. JSON state-only save is the right choice for JSONB storage and auditability.
- **Blocking on DSPy compile in `_run()`**: BootstrapFewShot is CPU/LLM-bound. The entire compilation is synchronous. Use `asyncio.get_event_loop().run_in_executor(None, compile_fn)` if needed, but given this is a Type=oneshot (no event loop concurrency required), synchronous compile is acceptable.
- **Reading `prompt_versions` during inference**: Violates DAG Invariant 3. Load at startup in `BaseGroupCoordinator._setup()` only.
- **Emitting `skipped_data_gate` from `main()`**: The data gate skip exits cleanly (exit code 0). The inner `DSPyOptimizer._run()` emits the `skipped_data_gate` counter and returns cleanly; `main()` then emits `success`. This matches the ml_trainer pattern where inner exceptions are swallowed and logged.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Few-shot example selection | Custom demo picker | `dspy.BootstrapFewShot` | Handles bootstrap traces, metric filtering, demo slot allocation |
| JSON serialization of demos | Custom dict builder | `program.save(path)` + `json.loads()` | DSPy handles field names, metadata, signature version |
| LLM provider routing during compilation | Custom Ollama caller | `dspy.LM("ollama_chat/...")` | DSPy wraps LiteLLM; retry, timeout, provider config handled |

**Key insight:** DSPy's value is that it handles the mechanics of few-shot trace collection and filtering. The project's value is the training data in `llm_calls` and the per-agent `PROMPT_REGISTRY` structure. Don't replicate DSPy internals.

---

## Common Pitfalls

### Pitfall 1: `dspy` vs `dspy-ai` Package Name
**What goes wrong:** `pip install dspy-ai` installs the old package (last version 2.6.0, Jan 2025). The current package is `pip install dspy` (3.2.1 as of Jun 2026).
**Why it happens:** The package was renamed from `dspy-ai` to `dspy` at version 2.6.
**How to avoid:** Add `dspy>=3.2.1` to `requirements.txt`. Run `pip install dspy`, not `dspy-ai`.
**Warning signs:** `import dspy; dspy.__version__` returns "2.x.x" or AttributeError.

### Pitfall 2: Metric Function Confusion — Labeled vs Bootstrap Metric
**What goes wrong:** Implementing the metric to check `example.parse_success == True` (comparing against the labeled value). This works for evaluation but not for bootstrapping, where `example.parse_success` is the ground truth label and `pred` is the model's PREDICTED output.
**Why it happens:** The metric function is called in two contexts: (1) during bootstrap to evaluate whether a traced example is worth keeping as a demo, (2) during evaluation to measure program quality. In context (1), `pred` is a `dspy.Prediction` object with output fields, not a parse_success boolean.
**How to avoid:** The metric function must evaluate `pred`'s output fields directly (can it be parsed as valid JSON with correct field types?), not compare against `example.parse_success`.
**Warning signs:** All bootstrap demos are accepted or all rejected; `max_bootstrapped_demos=0` in compiled output.

### Pitfall 3: Regime Values Are Numeric (0/1/2), Not Strings
**What goes wrong:** Querying `WHERE regime IN ('bullish','bearish','ranging')` returns zero rows.
**Why it happens:** The CONTEXT.md D-09 uses string labels for readability, but `llm_calls.regime` stores HMM numeric values: `0=ranging, 1=trending_up, 2=trending_down` (per `ml_trainer.py` comment).
**How to avoid:** Use `WHERE regime IN ('0','1','2')` or `WHERE regime::int IN (0,1,2)` in the regime-balance guard query. Map numeric to labels only in the report output.
**Warning signs:** Regime-balance guard always fails; A/B window keeps extending.

### Pitfall 4: Phase 096 Dependency — AgentDependencies Does Not Exist Yet
**What goes wrong:** Writing Phase 098 code that imports `AgentDependencies` or `AgentRegistry` from Phase 096 deliverables that haven't been built.
**Why it happens:** Phase 096 is planned but not executed as of 2026-06-02.
**How to avoid:** Phase 098 must either (a) be executed after Phase 096, or (b) define the `compiled_prompt` injection point as a stub that Phase 096 wires in. The CONTEXT.md says the injection point is `BaseGroupCoordinator._setup()` via `AgentDependencies`. The planner should ensure Phase 096 is complete before Phase 098 can be fully integrated, OR scope the Phase 098 plans so that the compile/store path ships first and the startup-injection path ships after Phase 096.
**Warning signs:** Import errors at service startup; `AgentDependencies` not found.

### Pitfall 5: DSPy Ollama Connection During Compilation
**What goes wrong:** DSPy compilation fails silently if Ollama is unavailable (e.g., model swap in progress, Docker restart).
**Why it happens:** BootstrapFewShot calls the LLM for each training example; an Ollama timeout causes the entire compilation to fail.
**How to avoid:** (Planner's discretion area) Pre-check Ollama availability before starting compilation. Implement a retry/timeout wrapper around the `optimizer.compile()` call. Set `TimeoutStartSec=7200` in the systemd unit (matches ml-training pattern). Log Ollama unavailability and emit `status="failure"`.
**Warning signs:** `compile()` hangs for > 30 minutes; systemd reports timeout.

### Pitfall 6: `_path_bootstrap` Import Must Be First
**What goes wrong:** `from src.config.settings import Settings` fails with ModuleNotFoundError in the oneshot entrypoint.
**Why it happens:** `services/` scripts run with CWD as project root but `src` is not on `sys.path` unless `_path_bootstrap` is imported first.
**How to avoid:** Copy exactly from `ml_training_agent.py`:
```python
import _path_bootstrap  # noqa: F401 — project root on sys.path
```
This must appear before any `from src.*` imports.

### Pitfall 7: `version_tag` Uniqueness Across Runs
**What goes wrong:** Running the optimizer twice on the same day produces a duplicate `version_tag` and hits the UNIQUE constraint.
**Why it happens:** `version_tag = f"{agent_id}_dspy_{YYYYMMDD}"` — same tag on re-run same day.
**How to avoid:** Add a short hash or hour suffix: `f"{agent_id}_dspy_{YYYYMMDD}_{run_hour:02d}"`. Or use `INSERT ... ON CONFLICT (version_tag) DO NOTHING` and log that this run was already compiled today.

---

## Code Examples

Verified patterns from codebase and official sources:

### llm_calls Query — Labeled Trainset with Regime
```sql
-- Source: production schema (PGPASSWORD=postgres psql verified)
SELECT
    call_id,
    agent_id,
    prompt,
    response,
    parse_success,
    outcome,
    regime,
    called_at
FROM llm_calls
WHERE agent_id = $1
  AND outcome IS NOT NULL
  AND called_at >= NOW() - INTERVAL '90 days'
ORDER BY called_at DESC
LIMIT 2000
```

### prompt_versions Query — Load Active at Startup
```sql
SELECT compiled_prompt, version_tag
FROM prompt_versions
WHERE agent_id = $1 AND status = 'active'
ORDER BY promoted_at DESC
LIMIT 1
```

### A/B Comparison Query — Promotion Check
```sql
SELECT
    prompt_version,
    COUNT(*) AS n_calls,
    AVG(parse_success::int) AS parse_success_rate,
    AVG(CASE WHEN win IS NOT NULL THEN win::int END) AS win_rate,
    COUNT(DISTINCT regime) AS regime_count,
    COUNT(*) FILTER (WHERE regime = '0') AS n_ranging,
    COUNT(*) FILTER (WHERE regime = '1') AS n_trending_up,
    COUNT(*) FILTER (WHERE regime = '2') AS n_trending_down
FROM llm_calls
WHERE agent_id = $1
  AND called_at >= $2  -- A/B window start (candidate created_at)
  AND prompt_version IN ($3, $4)  -- baseline version_tag, candidate version_tag
GROUP BY prompt_version
```

### OTel `job_completed_total` Pattern
```python
# Source: services/ml_training_agent.py (canonical)
from src.observability.metrics import JOB_COMPLETED_TOTAL, flush_and_shutdown_metrics

# In main() try block:
JOB_COMPLETED_TOTAL.add(1, {"job": "dspy-optimizer", "status": "success"})
# In except block:
JOB_COMPLETED_TOTAL.add(1, {"job": "dspy-optimizer", "status": "failure"})
# For data gate skip (inside DSPyOptimizer._run(), before early return):
JOB_COMPLETED_TOTAL.add(1, {"job": "dspy-optimizer", "status": "skipped_data_gate"})
```

**Critical:** `job` label value must match the systemd unit `%n` suffix exactly: `indicagent-dspy-optimizer` → suffix is `dspy-optimizer`.

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `dspy-ai` package | `dspy` package | v2.6 (Jan 2025) | Must update `requirements.txt` to use `dspy` not `dspy-ai` |
| `dspy.OllamaLocal` | `dspy.LM("ollama_chat/...")` | v2.5+ | `OllamaLocal` removed; use `LM` with LiteLLM prefix |
| `dspy.Module` base class | `dspy.Module` still valid | - | No change needed |
| Whole-program cloudpickle save | JSON state save (recommended) | v2.6+ | JSON preferred for JSONB storage; cloudpickle version-sensitive |

**Deprecated/outdated:**
- `dspy-ai` (PyPI): old package name; last version 2.6.0; do not use.
- `dspy.OllamaLocal`: removed in recent versions; use `dspy.LM("ollama_chat/model")`.
- `dspy.Program`: alias removed in 3.0; not relevant here (not used in BootstrapFewShot workflow).

---

## Open Questions

1. **Exact DSPy Signature field decomposition per agent**
   - What we know: Each agent's `PROMPT_REGISTRY` template is a long string with `{symbol}`, `{timeframe}`, `{full_context_block}` etc. format vars. DSPy Signatures define typed fields, not format strings.
   - What's unclear: Whether to flatten all context into one `prompt_context: str` InputField (simple, loses type information) vs decomposing into `symbol: str`, `timeframe: str`, `context: str` fields (more structured, potentially better few-shot matching).
   - Recommendation: Use a single `prompt_context: str` InputField per agent for simplicity. The optimizer is selecting among examples, not generating structure — rich field decomposition provides minimal benefit for BootstrapFewShot.

2. **Demos-only vs full JSON save in JSONB**
   - What we know: DSPy `program.save()` produces a JSON dict with demos nested under `"predict"` key. The demos themselves are `dspy.Example` objects serialized to dicts.
   - What's unclear: Whether to store the full DSPy JSON (includes LM config, signature metadata) or just the demos list in `compiled_prompt` JSONB.
   - Recommendation: Store the full DSPy JSON dict. The LM config section is ignored at load time (we reconfigure LM at startup), but having it provides audit information. The JSONB column supports `jsonb_array_length(compiled_prompt->'predict'->'demos')` for quick demo count queries.

3. **Startup injection for Phase 096 dependency**
   - What we know: `AgentDependencies` and `BaseGroupCoordinator._setup()` are Phase 096 deliverables not yet built (confirmed: no `AgentDependencies` class exists in codebase as of 2026-06-02).
   - What's unclear: Whether Phase 098 plans should scope the injection path as a separate plan gated on Phase 096, or assume Phase 096 is done first.
   - Recommendation: Split Phase 098 into two plan groups: (Group A) compile + store path (independent of Phase 096), and (Group B) startup injection into `AgentDependencies` (depends on Phase 096). Execute Group A first; Group B blocked until Phase 096 ships.

---

## Sources

### Primary (HIGH confidence)
- Codebase: `services/ml_training_agent.py` — oneshot entrypoint canonical pattern
- Codebase: `src/intelligence/services/ml_trainer.py` — training service class pattern
- Codebase: `services/llm_writer.py` — `llm_calls` INSERT SQL (exact column list)
- Codebase: `production/migrations/087_llm_calls_agent_attrs.sql` + live DB schema — confirmed columns: `agent_id`, `prompt_version`, `parse_success`, `outcome`, `regime`
- Codebase: `src/intelligence/ai/alpha/correlation_prompts.py` — `PROMPT_REGISTRY` / `ACTIVE_VERSION` pattern
- Codebase: `production/systemd/indicagent-ml-training.service` + `.timer` — systemd unit template
- Codebase: `src/observability/metrics.py:382` — `JOB_COMPLETED_TOTAL` already registered
- DB: `SELECT DISTINCT regime FROM llm_calls` — confirmed regime values are `'0','1','2'` (numeric strings), not text labels

### Secondary (MEDIUM confidence)
- [DSPy BootstrapFewShot API](https://dspy.ai/api/optimizers/BootstrapFewShot/) — constructor params, compile signature, metric interface
- [DSPy Saving/Loading tutorial](https://dspy.ai/tutorials/saving/) — `program.save()`, `program.load()`, JSON vs pickle
- [DSPy Bootstrap family](https://dspy.ai/diving-deeper/bootstrap-fewshot-family/) — step-by-step workflow, `dspy.Example` format, `metric(example, pred, trace)` signature
- [DSPy 3.2.0 release notes](https://github.com/stanfordnlp/dspy/releases/tag/3.2.0) — breaking changes (duplicate field names rejected; `prefix`/`format`/`parser` kwargs deprecated)
- [PyPI dspy](https://pypi.org/project/dspy/) — current version 3.2.1, `pip install dspy`
- [DSPy Ollama configuration](https://github.com/stanfordnlp/dspy/blob/main/docs/docs/learn/programming/language_models.md) — `dspy.LM("ollama_chat/model", api_base=...)` pattern

### Tertiary (LOW confidence)
- WebSearch results on metric function signature: `metric(example, pred, trace=None)` pattern — consistent across multiple sources, treating as MEDIUM
- DSPy 3.0 backward compatibility claim (breaking changes minimal for BootstrapFewShot) — single source, flag for validation

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — codebase + PyPI verified; dspy package name confirmed
- Architecture patterns: HIGH — ml_training_agent.py / ml_trainer.py are exact templates; DSPy API MEDIUM from official docs
- Pitfalls: HIGH for codebase pitfalls (regime values, _path_bootstrap); MEDIUM for DSPy-specific metric function pitfall
- Migration schema: HIGH — follows established patterns from 084/099 migrations
- Phase 096 dependency: HIGH — confirmed `AgentDependencies` does not yet exist in codebase

**Research date:** 2026-06-02
**Valid until:** 2026-07-02 (stable codebase patterns); DSPy API valid ~30 days (fast-moving library)
