# High-Level Architecture Concepts

## Core Architectural Patterns

### **DAG Architecture**
- **Dependency-aware DAG orchestration** - Plugin dependencies declared, execution order derived automatically via topological sort
- **Circular dependency detection** - Prevents misconfigured plugins at startup
- **Parallel execution** - Where dependencies allow, plugins run in parallel
- **Plugin system** - 121 plugins across I1-I7 tiers, each with `compute_next()` for $O(1)$ incremental updates

### **Dynamic Clustering**
Currently uses systemd with manual scaling, but designed for future Kubernetes:
- **Horizontal Pod Autoscaler (HPA) ready** - Auto-scale based on Kafka consumer lag, persistence latency
- **Multi-node ready** - Geographic distribution support planned
- **Service discovery** - DNS-based service endpoints for dynamic pod scaling

### **Microservices Architecture**
- **Event-driven microservices** - No direct service calls, all communication via Redpanda streams
- **Separation of Concerns** - Each service owns exactly one responsibility:
  - Data collection, intelligence computation, signal generation, lifecycle tracking, persistence, AI narrative, API delivery
- **Zero coupling** - Services can be restarted/updated independently without affecting others

### **DAG Applied to Persistence**
- **Multi-tier persistence DAG**:
  - **Hot tier** (Redpanda) - Sub-millisecond stream processing
  - **Warm tier** (Processing services) - <10ms intelligence extraction
  - **Cold tier** (TimescaleDB) - Async batch writes for long-term storage
- **Stream-based persistence** - All data flows through topics before hitting database

### **Modularity**
- **Plugin-native shell** - Platform is an empty shell, intelligence composed entirely of plugins
- **Extensibility** - New capabilities added via single `@dataclass` without changing pipeline
- **Data contracts over APIs** - Typed `IntelligenceEvent` schema as the only contract
- **Opaque internal logic** - Service internals hidden, only schema matters

### **API First**
- **REST + SSE endpoints** - Full intelligence accessible via standard HTTP
- **Real-time push** - SSE streams for live intelligence delivery
- **Multi-consumer ready** - Any HTTP client can connect (trading bots, notebooks, downstream products)
- **Self-documenting** - Schema-first design with open endpoints

### **Data Hub - Hot/Warm/Cold Tiers**
```
Real-time Data Source → Hot (Redpanda streams) → Warm (Processing services) → Cold (TimescaleDB)
                          sub-ms writes             <10ms/bar             async batch writes
```
- **Hot tier** - Real-time stream processing, sub-millisecond ingestion
- **Warm tier** - Intelligence extraction across I1-I8 layers
- **Cold tier** - Feature store, signal ledger, ML training data

## Data Abstraction Layer

### **Provider-Neutral Architecture**
The platform abstracts data sources through a standardized interface:
- **Broker/Data Provider Abstraction** - Pluggable data sources with uniform stream format
- **Stream normalization** - All data sources emit standardized bar events to Redpanda
- **Multi-provider support** - Concurrent connections to multiple data sources
- **Automatic failover** - Seamless switching between providers based on health and quality

### **Data Provider Interface**
```python
class DataProvider(ABC):
    @abstractmethod
    async def connect(self) -> Stream[MarketBar]:
        pass

    @abstractmethod
    async def get_instruments(self) -> List[Instrument]:
        pass

    @abstractmethod
    async def validate_health(self) -> HealthStatus:
        pass
```

### **Multi-Provider Strategy**
- **Primary/Secondary providers** - Active monitoring with automatic failover
- **Quality-based routing** - Data weighted by provider reliability metrics
- **Reconciliation engine** - Detects and resolves discrepancies between providers
- **Market data consensus** - Uses multiple sources for validation before intelligence processing

## ML/AI Architecture

### **Intelligence Swarm System**
A collection of asynchronous agents that quantify market state friction and provide predictive alpha multipliers:

- **Agent Registry** - 9 specialized agents covering:
  - Regime & Entropy analysis (Regime Sentinel, Volatility Arbiter)
  - SMC & Structural Liquidity (Liquidity Decay Arbiter, SMC Validator)
  - Cross-Asset & Macro monitoring (Correlation Contagion, Macro Event Observer)
  - Model & System integrity checks (Execution Quality Observer, SkepticAgent)
- **Shadow-First Validation** - Agents run in shadow mode for 14+ days correlating predictions with outcomes before production promotion
- **Differentiable Intelligence** - Every agent outputs quantifiable vectors (multipliers, probabilities, friction scores)
- **Data Contract** - Standardized `AlphaMultiplier` JSON schema with agent contributions and final composite score

### **Multi-Agent Orchestrator Architecture**
A supervisor/lead orchestrator coordinates domain-specific agents using LangGraph:

```
┌─────────────────────────────────────────────────────────────────┐
│  ML Orchestrator (LangGraph Supervisor)                         │
│  "What needs to happen next given current system state?"       │
│                                                                 │
│  Reads: drift scores, model status, discovery schedule,         │
│         data quality signals, shadow mode results               │
│  Routes to: domain agents in sequence or parallel               │
│  Decides: retrain Y/N, promote Y/N, escalate to human Y/N      │
│  Logic: deterministic rules — NOT LLM-driven                    │
└─────────────────────────────────────────────────────────────────┘
         │           │           │           │           │
         ▼           ▼           ▼           ▼           ▼
  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌─────────┐ ┌──────────┐
  │  Data    │ │Discovery │ │Training  │ │Monitor  │ │Narrative │
  │ Quality  │ │  Agent   │ │  Agent   │ │  Agent  │ │  Agent   │
  │          │ │ (LLM)    │ │  (det.)  │ │  (det.) │ │  (LLM)   │
  └──────────┘ └──────────┘ └──────────┘ └─────────┘ └──────────┘
```

**Key principle:** Only Discovery and Narrative agents use LLMs. Orchestrator, Training, and Monitoring are deterministic.

### **Key Architectural Patterns**
- **Event-driven everything** - No shared state, all communication via streams
- **Hot path isolation** - Real-time pipeline never touches database directly
- **Incremental-first** - $O(1)$ per-bar updates for performance
- **Self-correcting pipeline** - Drift detection (KS/CUSUM) and auto-adjustment
- **Institutional rigor** - Multi-bucket CIS scoring requires cross-tier agreement
- **Dual-Path Integration** - Deterministic DAG (Path A) + LLM-Swarm (Path B) with shadow validation

The architecture is designed for institutional-grade reliability while remaining extensible and scalable - currently running on systemd but designed for future Kubernetes adoption when horizontal scaling becomes necessary.