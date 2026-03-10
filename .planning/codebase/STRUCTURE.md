# Codebase Structure

## Directory Layout

```
indicagent/
├── src/                          # Core library code
│   ├── api/                      # FastAPI application
│   │   └── routes/               # API route handlers
│   ├── config/                   # Settings and configuration
│   ├── core/                     # Base classes, stream mixins, shared infra
│   │   └── streams_mixins/       # Reusable stream processing mixins
│   ├── indicators/               # Technical indicator calculations (I1)
│   │   └── calc_modules/         # Low-level math modules
│   ├── intelligence/             # Intelligence plugin system (I3–I8)
│   │   ├── composites/           # Multi-signal composite plugins
│   │   ├── confluence/           # Confluence detection plugins
│   │   ├── context/              # Market context plugins
│   │   ├── indicators/           # Indicator-based intelligence plugins
│   │   ├── patterns/             # Pattern recognition plugins
│   │   ├── smart_money/          # SMC / institutional plugins
│   │   ├── structure/            # Market structure plugins
│   │   ├── trading/              # Trade setup plugins
│   │   ├── dag.py                # Plugin dependency graph
│   │   ├── plugins.py            # Plugin base class / interface
│   │   ├── register_plugins.py   # Plugin registry (TIER_I7 etc.)
│   │   └── utils.py              # Shared intelligence utilities
│   ├── observability/            # Metrics, logging, tracing
│   └── providers/                # Data provider adapters
│
├── services/                     # Long-running pipeline services
│   ├── indicator_service.py      # I1: Redis → technical indicators
│   ├── market_analysis_service.py     # I3–I7: canonical pipeline service
│   ├── intelligence_processor_service.py  # (deprecated — use above)
│   ├── signal_generator_service.py    # Signal scoring and ledger writes
│   ├── signal_tracker_service.py      # Signal outcome tracking
│   ├── ai_narrative_service.py        # LLM narrative generation
│   ├── timeframes_builder_service.py  # Timeframe aggregation
│   └── signal_orchestrator_service.py # Orchestration (experimental)
│
├── production/                   # Production infrastructure
│   ├── daemons/
│   │   └── high_frequency_tws_daemon.py  # IBKR TWS market data ingest
│   ├── migrations/               # Numbered SQL migration files
│   ├── schemas/                  # DB schema definitions
│   ├── scripts/
│   │   └── historical_backfill.py  # 365-day IBKR → DB backfill
│   └── config/                   # Production config overrides
│
├── tests/
│   ├── unit/                     # Unit tests mirroring src/ layout
│   │   ├── api/
│   │   ├── config/
│   │   ├── core/
│   │   ├── daemons/
│   │   ├── indicators/
│   │   ├── intelligence/
│   │   ├── providers/
│   │   └── service_tests/
│   └── integration/              # Integration tests
│
├── dashboard/                    # Next.js frontend (TypeScript)
│   └── src/
│       ├── app/                  # Next.js App Router pages
│       ├── components/           # React components
│       ├── hooks/                # Custom React hooks
│       └── lib/                  # Utilities and API clients
│
├── docs/                         # Project documentation
│   ├── architecture/             # Architecture decision records
│   ├── concepts/                 # Domain concept explanations
│   ├── configuration/            # Config reference
│   ├── for-ai-assistants/        # AI-oriented context docs
│   ├── getting-started/          # Setup and quickstart guides
│   ├── guides/                   # How-to guides
│   ├── intelligence/             # Plugin system docs
│   ├── plans/                    # Design documents
│   ├── reference/                # API, plugin, schema references
│   └── roadmap/                  # Roadmap and status
│
├── config/                       # Shared config files
├── scripts/                      # Utility scripts
├── logs/                         # Log output directory
│
├── pyproject.toml                # Python project metadata + dependencies
├── requirements.txt              # Pinned requirements
├── pytest.ini                    # Test configuration
└── README.md                     # Project overview
```

## Key File Locations

| Purpose | Path |
|---------|------|
| Plugin registry | `src/intelligence/register_plugins.py` |
| Plugin base class | `src/intelligence/plugins.py` |
| Plugin DAG | `src/intelligence/dag.py` |
| Settings | `src/config/settings.py` |
| IBKR ingest daemon | `production/daemons/high_frequency_tws_daemon.py` |
| Canonical pipeline | `services/market_analysis_service.py` |
| Signal generation | `services/signal_generator_service.py` |
| Historical backfill | `production/scripts/historical_backfill.py` |
| DB migrations | `production/migrations/001_*.sql` → `008_*.sql` |
| FastAPI app | `src/api/` |

## Naming Conventions

- **Services**: `{noun}_service.py` — long-running async consumers
- **Daemons**: `{adjective}_{noun}_daemon.py` — data ingest processes
- **Plugins**: Grouped by intelligence tier subdirectory; class names are `PascalCase`
- **Tests**: Mirror source path — `tests/unit/intelligence/` mirrors `src/intelligence/`
- **Migrations**: Numbered `NNN_description.sql`, applied in order by `db_setup.sh`
- **Redis keys**: `intelligence:{symbol}:{timeframe}` stream, `plugin_state:{symbol}:{tf}:{name}` hash

## Intelligence Tier Directory Map

| Tier | Directory | Description |
|------|-----------|-------------|
| I1 | `src/indicators/` | Technical indicator calculation |
| I3 | `src/intelligence/indicators/` | Indicator-based intelligence |
| I4 | `src/intelligence/patterns/` | Pattern recognition |
| I5 | `src/intelligence/structure/` | Market structure analysis |
| I6/SMC | `src/intelligence/smart_money/` | Smart money concepts |
| I7 | `src/intelligence/context/`, `trading/`, `confluence/` | High-level context |
| I8 | `src/intelligence/composites/` | Multi-signal composites |

## Systemd Service Files

Located in `services/` with `.service` extension — deployed to `/etc/systemd/system/`:
- `indicagent-hf-tws.service` — IBKR daemon
- `indicagent-enhanced-indicator.service` — indicator service
- `indicagent-parallel.service` — parallel pipeline
- `indicagent-timeframe-builder.service` — timeframe builder

---
*Generated: 2026-02-22*
