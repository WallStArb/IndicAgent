# Code Standards

Coding conventions for IndicAgent.

---

## Linting & Formatting

```bash
ruff check . --fix        # Linting
black .                   # Formatting
mypy src/ --ignore-missing-imports  # Type checking
```

**Target:** 0 ruff errors on new code

---

## Naming Conventions

### Files
`[domain]_[purpose]_[suffix].py`

Examples:
- `indicator_processor_service.py`
- `signal_aggregation_design.md`

### Redis Streams
`domain:SYMBOL:TIMEFRAME:type`

Examples:
- `market:ES:5m`
- `indicators:NQ:15m`

### Plugin Names
- I1 indicators: `ind_*` (e.g., `ind_sma`)
- I3 structure: `struct_*`
- I4 context: `ctx_*`
- I5 patterns: `patt_*`
- I6 smart money: `smc_*`
- I7 trading: `setup_*`

---

## Code Organization

[TODO: Expand with more conventions from CLAUDE.md]

---

**Reference:** [CLAUDE.md](../for-ai-assistants/CLAUDE.md)
