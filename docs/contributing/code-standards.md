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

### Plugin files

Each plugin lives in its tier directory under `src/intelligence/`:

```
src/intelligence/
├── indicators/     # I1 — ind_*
├── composites/     # I2
├── market_structure/ # I3 — struct_*
├── context/        # I4 — ctx_*
├── patterns/       # I5 — patt_*
├── smart_money/    # I6 SMC — smc_*
├── confluence/     # I6 cross-timeframe
└── setups/         # I7 — setup_*
```

### Service files

Services live in `services/` and follow the pattern `[name]_service.py`. They accept `--config <path>` and load JSON config from `config/`.

### Key principles

- **Incremental compute** — plugins implement `compute_next(bar)` for single-bar updates, not batch recompute
- **No global state** — plugins are stateful objects; each symbol+timeframe gets its own instance
- **Explicit warmup** — every plugin declares `warmup_period`; return `None` or `{}` until satisfied
- **Line length:** 100 characters (configured in `pyproject.toml`)

---

**Reference:** [CLAUDE.md](../for-ai-assistants/CLAUDE.md)
