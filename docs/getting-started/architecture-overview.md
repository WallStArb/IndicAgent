# Architecture Overview

10,000-foot view of IndicAgent.

---

## System Architecture

[TODO: High-level diagram and explanation]

### Intelligence Pipeline

```
IBKR TWS → I1 Indicators → I3 Structure → I4 Context →
I5 Patterns → I6 Smart Money → I7 Trading → Redis → Dashboard
```

### Data Flow

**Hot Tier:** DragonflyDB (sub-ms)
**Warm Tier:** Redis Streams (real-time)
**Cold Tier:** TimescaleDB (historical)

---

## Core Concepts

[TODO: Brief intro to intelligence tiers, plugins, services]

---

**Deep Dive:** [Concepts](../concepts/) for detailed architecture
