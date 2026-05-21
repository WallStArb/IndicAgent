# Preserved Insights from Instructor Phase Planning

> **Context:** Phase 095 (Instructor) was deprioritized in favor of direct Pydantic AI adoption. This document captures patterns and decisions that remain relevant for Phase 095 (renamed from 095).

## Result Model Definitions (Preserved)

These Pydantic models are used directly by Pydantic AI's `NativeOutput(result_type)`. No changes needed — transport layer switches, data contracts stay the same.

### SkepticResult
```python
class SkepticResult(BaseModel):
    failure_probability: float = Field(ge=0.0, le=1.0)
    confidence: float = Field(ge=0.0, le=1.0)
    risk_factors: list[str] = Field(default_factory=list)
    reasoning: str = Field(default="", max_length=500)

    @field_validator("risk_factors", mode="before")
    @classmethod
    def coerce_to_list(cls, v: object) -> list[str]:
        if v is None:
            return []
        if not isinstance(v, list):
            return [str(v)]
        return [str(x) for x in v]
```

### CorrelationResult
```python
class CorrelationResult(BaseModel):
    coherence_score: float = Field(ge=0.0, le=1.0)
    confidence: float = Field(ge=0.0, le=1.0)
    contradicting_assets: list[str] = Field(default_factory=list)
    reasoning: str = Field(default="")

    @field_validator("contradicting_assets", mode="before")
    @classmethod
    def coerce_to_list(cls, v: object) -> list[str]:
        if v is None:
            return []
        if not isinstance(v, list):
            return [str(v)]
        return [str(x) for x in v]
```

### CounterfactualResult
```python
class CounterfactualResult(BaseModel):
    plausibility: float = Field(ge=0.0, le=1.0)
    confidence: float = Field(ge=0.0, le=1.0)
    validation_conditions: list[str] = Field(default_factory=list)
    invalidation_conditions: list[str] = Field(default_factory=list)
    alternative_scenario: str = Field(default="")

    @field_validator("validation_conditions", "invalidation_conditions", mode="before")
    @classmethod
    def coerce_to_list(cls, v: object) -> list[str]:
        if v is None:
            return []
        if not isinstance(v, list):
            return [str(v)]
        return [str(x) for x in v]
```

### RegimeCoherenceResult
```python
class RegimeCoherenceResult(BaseModel):
    regime_fit: float = Field(ge=0.0, le=1.0)
    confidence: float = Field(ge=0.0, le=1.0)
    supporting_factors: list[str] = Field(default_factory=list)
    warning_factors: list[str] = Field(default_factory=list)

    @field_validator("supporting_factors", "warning_factors", mode="before")
    @classmethod
    def coerce_to_list(cls, v: object) -> list[str]:
        if v is None:
            return []
        if not isinstance(v, list):
            return [str(v)]
        return [str(x) for x in v]
```

## Key Patterns

### coerce_to_list Validator Pattern
All list fields use the same `@field_validator(mode="before")` pattern:
- Handles `None` → empty list
- Handles single value → `[str(value)]`
- Handles list of values → `[str(x) for x in v]`

This pattern is critical because LLMs often return single strings instead of lists for one-item arrays.

### Field Constraints
- All `float` scores use `Field(ge=0.0, le=1.0)` for bounded 0-1 range
- `confidence` is always 0-1 bounded
- Multiplier calculations happen outside the model (in agent logic)

## Observability (STRUCT-OUT-03)

**Key finding:** `llm_calls.parse_success` column already exists in the database (per `\d llm_calls`). No schema migration needed.

**Metric approach:** OTel counter `LLM_PARSE_FAILURES` should drop to zero after Pydantic AI migration (structured output is enforced at generation time via llama.cpp grammar constraints). Query `llm_calls` before/after to validate delta.

## Retry Behavior (STRUCT-OUT-02)

**Requirement:** Parse failures trigger automatic retry with validation error injected back into prompt.

**Pydantic AI approach:** `OllamaModel` with `NativeOutput` enforces schema at generation time — no post-parse retry needed. Invalid responses are impossible by construction. The "retry" happens only on transport-level failures (LLM timeout, etc.), not parse failures.

## Boilerplate Elimination (STRUCT-OUT-04)

**Deleted after migration:**
- All `_validate_*_fields()` functions (replaced by Pydantic validators)
- `_parse_multiplier_response()` method (replaced by `NativeOutput`)
- `output_schema: ClassVar[dict]` declarations (replaced by `result_type`)

**Deleted from BaseMultiplierAgent:**
- `_parse_multiplier_response()` method
- Related `parse_llm_json()` helper if unused elsewhere

## RenTech Principle Applied

**No throwaway engineering:** Result models are data contracts. Transport is plumbing. Pydantic AI changes the plumbing without touching the contracts. Single migration, shipped once.
