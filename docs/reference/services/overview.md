# Service Reference Overview

Production services architecture.

---

## Services

See [STATUS.md](../../STATUS.md) for current service status.

### Data Collection
- [HF TWS Daemon](hf-tws-daemon.md) — IBKR data collection

### Processing
- [Indicator Service](indicator-processor.md) — I1+I2 calculations
- [Market Analysis Service](intelligence-processor.md) — I3→I6 pipeline
- [Signal Generator Service](intelligence-processor.md) — I7 setups + aggregation
- [Signal Lifecycle Service](intelligence-processor.md) — Zone tracking, MAE/MFE, 8-class outcome
- [AI Narrative Service](intelligence-processor.md) — I8 LLM synthesis
- [Feature Writer Service](intelligence-processor.md) — Redpanda → TimescaleDB batch writer
- [LLM Writer Service](intelligence-processor.md) — LLM audit log + outcome back-fill

---

**Guide:** [Running Services](../../guides/running-services.md)
