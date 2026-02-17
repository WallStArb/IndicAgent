# Quick Start

Get IndicAgent running in 5 minutes.

---

## Prerequisites

- Python 3.11+
- Docker Desktop
- Git

---

## Steps

### 1. Clone Repository

```bash
git clone https://github.com/yourusername/indicagent.git
cd indicagent
```

### 2. Setup Environment

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 3. Start Infrastructure

```bash
docker-compose up -d
```

### 4. Start Services

```bash
python production/daemons/high_frequency_tws_daemon.py --client-id 35
python services/indicators_processor_service.py --config config/indicator_processor_service.json
```

### 5. Start Dashboard

```bash
cd dashboard
npm install
npm run dev
```

Open http://localhost:3000

---

## Next Steps

- **Full Installation:** [installation.md](installation.md) for detailed setup
- **First Plugin:** [first-plugin.md](first-plugin.md) to write your first plugin
- **Architecture:** [architecture-overview.md](architecture-overview.md) to understand the system

---

**Status:** See [STATUS.md](../STATUS.md) for current versions
