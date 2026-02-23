# Quick Start

Get IndicAgent running in 5 minutes.

---

## Prerequisites

- Python 3.11+
- Docker Desktop
- Git

---

## Steps

### 1. Clone the Repository

```bash
git clone https://github.com/yourusername/indicagent.git
cd indicagent
```

### 2. Set Up the Python Environment

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 3. Start Infrastructure

```bash
docker compose -f production/docker-compose.yml up -d
```

Starts TimescaleDB (port 5432), DragonflyDB (port 6379), and Ollama (port 11434).

### 4. Apply Database Migrations

```bash
bash production/scripts/db_setup.sh
```

### 5. Start Services

```bash
python3 production/daemons/high_frequency_tws_daemon.py --client-id 35
python3 services/indicator_service.py --config config/indicator_service.json
python3 services/market_analysis_service.py --config config/market_analysis_service.json
python3 services/signal_generator_service.py --config config/signal_generator_service.json
```

### 6. Start Dashboard

```bash
cd dashboard
npm install
npm run dev
```

Open http://localhost:3000

---

## Next Steps

- **Full Installation:** [installation.md](installation.md) for infrastructure details and IBKR setup
- **First Plugin:** [first-plugin.md](first-plugin.md) to write your first intelligence plugin
- **Architecture:** [architecture-overview.md](architecture-overview.md) to understand the pipeline
