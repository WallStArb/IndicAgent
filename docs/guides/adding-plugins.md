# Adding Plugins

Step-by-step guide to creating new plugins.

---

## Plugin Types

- **I1: Indicators** — Technical indicators (SMA, RSI, etc.)
- **I3: Structure** — Market structure (swings, S/R, trends)
- **I4: Context** — Regime classification (volatility, trend)
- **I5: Patterns** — Pattern detection (divergence, confluence)
- **I6: Smart Money** — SMC concepts (FVG, order blocks, BOS)
- **I7: Trading** — Setup plugins (signals)

---

## Process

[TODO: Detailed step-by-step for each plugin type]

1. Design plugin (input/output schema)
2. Write tests (TDD)
3. Implement plugin
4. Register in register_plugins.py
5. Add to reference docs
6. Update STATUS.md plugin count

---

**Reference:** [Plugin Architecture](../concepts/plugin-architecture.md)
**Example:** [First Plugin Tutorial](../getting-started/first-plugin.md)
