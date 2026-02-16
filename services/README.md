# IndicAgent Service Management

Complete service orchestration system for the IndicAgent Trading Intelligence Platform.

## Overview

The IndicAgent platform uses a **master orchestrator** pattern with **systemd services** to manage all components as a cohesive system. This provides:

-  **Single command startup/shutdown**
-  **Automatic dependency management** 
-  **Health monitoring and restart**
-  **Resource cleanup and management**
-  **Production-ready service management**

## Quick Start

### 1. Install Services (One-time setup)

```bash
# Install all systemd services
./scripts/indicagent-control.sh install

# Reload systemd to recognize new services
systemctl --user daemon-reload
```

### 2. Start the System

```bash
# Start entire IndicAgent system
./scripts/indicagent-control.sh start
```

### 3. Check Status

```bash
# Check status of all services
./scripts/indicagent-control.sh status

# Check system health
./scripts/indicagent-control.sh health
```

### 4. View Logs

```bash
# View all service logs
./scripts/indicagent-control.sh logs

# View specific service logs
./scripts/indicagent-control.sh logs indicagent-hf-tws.service
```

### 5. Stop the System

```bash
# Stop entire IndicAgent system
./scripts/indicagent-control.sh stop
```

## Service Architecture

### Master Orchestrator

The **indicagent-master.service** coordinates all other services:

- Manages startup sequence based on dependencies
- Monitors health of all services  
- Handles coordinated shutdown
- Manages shared resources (Redis, PostgreSQL)
- Provides system-wide metrics

**Note:** The diagram below shows core data and API services. The platform also runs **intelligence-processor** (I3/I4/I5 plugins) and **coordination_parallel_service** (parallel stream coordination). See the root [README.md](../README.md) for the full service list.

### Service Dependencies

```
┌─────────────────────────────────────────────────────────┐
│                  Infrastructure                         │
│              Redis + PostgreSQL                         │
└────────────────────┬────────────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────────────┐
│               Data Collection                           │
│            indicagent-hf-tws.service                   │
│         (High-frequency tick data)                     │
└─────────────┬─────────────┬─────────────────────────────┘
              │             │
              ▼             ▼
┌─────────────────────┐   ┌─────────────────────────────────┐
│   Processing        │   │        Processing               │
│ indicator-processor │   │   timeframe-builder             │
│     .service        │   │      .service                   │
└─────────────┬───────┘   └─────────────┬───────────────────┘
              │                         │
              └─────────────┬───────────┘
                            │
                            ▼
              ┌─────────────────────────────────┐
              │           API Layer             │
              │    indicagent-backend-api       │
              │         .service                │
              └─────────────┬───────────────────┘
                            │
                            ▼
              ┌─────────────────────────────────┐
              │        WebSocket                │
              │    indicagent-websocket         │
              │         .service                │
              └─────────────────────────────────┘
```

## Service Details

### Core Services

| Service | Purpose | Port | Health Check | Metrics |
|---------|---------|------|--------------|---------|
| **indicagent-master** | Master orchestrator | 9100 | - | /metrics |
| **indicagent-hf-tws** | High-frequency data collection | 9108 | - | /metrics |
| **indicagent-indicator-processor** | Technical indicator calculation | 9109 | /health | /metrics |
| **indicagent-timeframe-builder** | Multi-timeframe aggregation | 9110 | /health | /metrics |
| **indicagent-backend-api** | FastAPI REST API | 8000 | /health | - |
| **indicagent-websocket** | Real-time WebSocket | 8001 | /health | - |

### Resource Requirements

**Minimum System Requirements:**
- **CPU:** 4 cores (8+ recommended)
- **Memory:** 8GB RAM (16GB+ recommended)
- **Storage:** 50GB SSD (100GB+ recommended)
- **Network:** Stable internet for IBKR connection

**Service Resource Limits:**
- HF TWS: 1GB RAM, 300% CPU
- Indicator Processor: 1GB RAM, 200% CPU  
- Timeframe Builder: 1GB RAM, 200% CPU
- Backend API: 512MB RAM, 200% CPU
- WebSocket: 512MB RAM, 200% CPU
- Master: 2GB RAM, 400% CPU

## Commands Reference

### Control Script Usage

```bash
./scripts/indicagent-control.sh [COMMAND] [OPTIONS]
```

**Commands:**
- `start` - Start the entire IndicAgent system
- `stop` - Stop the entire IndicAgent system  
- `restart` - Restart the entire IndicAgent system
- `status` - Show status of all services
- `logs [SERVICE]` - Show logs (optionally for specific service)
- `health` - Run comprehensive health check
- `install` - Install systemd services (one-time setup)
- `help` - Show help message

**Examples:**
```bash
# System management
./scripts/indicagent-control.sh start
./scripts/indicagent-control.sh restart
./scripts/indicagent-control.sh stop

# Monitoring
./scripts/indicagent-control.sh status
./scripts/indicagent-control.sh health
./scripts/indicagent-control.sh logs
./scripts/indicagent-control.sh logs indicagent-hf-tws.service

# Setup
./scripts/indicagent-control.sh install
```

### Manual Service Management

For troubleshooting, you can manage individual services:

```bash
# Check individual service status
systemctl --user status indicagent-master.service

# Start/stop individual services
systemctl --user start indicagent-hf-tws.service
systemctl --user stop indicagent-indicator-processor.service

# View individual service logs
journalctl --user -u indicagent-backend-api.service -f

# Restart individual service
systemctl --user restart indicagent-websocket.service
```

## Health Monitoring

### Automatic Health Checks

The master orchestrator continuously monitors:
- Service process status (via systemctl)
- Health endpoint responses (HTTP checks)
- Resource usage and limits
- Dependency availability

### Health Check URLs

Services expose health endpoints:
```bash
# Master orchestrator metrics
curl http://localhost:9100/metrics

# Service health endpoints  
curl http://localhost:8000/health   # Backend API
curl http://localhost:8001/health   # WebSocket
curl http://localhost:9109/health   # Indicator Processor
curl http://localhost:9110/health   # Timeframe Builder

# Service metrics endpoints (Prometheus format)
curl http://localhost:9108/metrics  # HF TWS metrics
curl http://localhost:9109/metrics  # Indicator Processor metrics
curl http://localhost:9110/metrics  # Timeframe Builder metrics
```

### Monitoring Dashboard

Access system metrics via Prometheus endpoint:
- **URL:** http://localhost:9100/metrics
- **Format:** Prometheus metrics format
- **Metrics:** Service health, performance, errors

## Troubleshooting

### Common Issues

**1. Services won't start**
```bash
# Check dependencies are running
systemctl --user status redis.service postgresql.service

# Check logs for errors
./scripts/indicagent-control.sh logs

# Run health check
./scripts/indicagent-control.sh health
```

**2. Services keep restarting**
```bash
# Check resource usage
./scripts/indicagent-control.sh status

# Check individual service logs
journalctl --user -u indicagent-hf-tws.service -n 50
```

**3. Performance issues**
```bash
# Check system resources
htop
free -h
df -h

# Check service metrics
curl http://localhost:9100/metrics | grep indicagent
```

### Log Locations

- **Service logs:** `journalctl --user -u SERVICE_NAME`
- **Application logs:** `/home/bg/projects/indicagent/logs/`
- **System logs:** `/var/log/syslog` or `journalctl --system`

### Manual Cleanup

If services are stuck or behaving oddly:

```bash
# Full system cleanup
./scripts/system-cleanup.sh full

# Clean and restart
./scripts/indicagent-control.sh stop
./scripts/system-cleanup.sh post-stop
./scripts/indicagent-control.sh start
```

## Development Mode

For development, you can run individual components manually:

```bash
# Activate virtual environment
source .venv/bin/activate

# Run individual services for development
python production/daemons/high_frequency_tws_daemon.py --client-id 35
python services/indicators_processor_service.py --config config/indicator_processor_service.json
python -m uvicorn src.api.main:app --reload
```

## Security

### Service Security Features

- **NoNewPrivileges=true** - Prevents privilege escalation
- **PrivateTmp=true** - Isolated temporary directories
- **ProtectSystem=strict** - Read-only system directories
- **Resource limits** - Memory and CPU constraints
- **User isolation** - Runs as non-root user

### Network Security

- Services bind to localhost only by default
- Health checks use HTTP (internal only)
- External access via configured reverse proxy (optional)

## Backup and Recovery

### Configuration Backup

Important files to backup:
- `services/*.service` - Service definitions
- `config/*.json` - Service configurations  
- `scripts/` - Control and cleanup scripts
- `logs/` - Application logs (optional)

### Recovery Procedure

1. **Stop all services:**
   ```bash
   ./scripts/indicagent-control.sh stop
   ```

2. **Restore configuration files**

3. **Reinstall services:**
   ```bash
   ./scripts/indicagent-control.sh install
   systemctl --user daemon-reload
   ```

4. **Start system:**
   ```bash
   ./scripts/indicagent-control.sh start
   ```

## Performance Tuning

### Resource Optimization

1. **Adjust service resource limits in .service files**
2. **Tune database connection pools**
3. **Configure Redis memory limits**
4. **Optimize log rotation**

### Monitoring Recommendations

- Monitor CPU/memory usage via `htop`
- Track service metrics via Prometheus
- Set up alerts for service failures
- Monitor disk space for logs

## Advanced Usage

### Custom Service Configuration

Modify service files in `services/` directory:
```bash
# Edit service configuration
vim services/indicagent-hf-tws.service

# Reload systemd
systemctl --user daemon-reload

# Restart service
systemctl --user restart indicagent-hf-tws.service
```

### Environment Variables

Set environment variables in service files:
```ini
[Service]
Environment=INDICAGENT_ENV=production
Environment=REDIS_URL=redis://localhost:6379/0
Environment=DEBUG=false
```

### Custom Health Checks

Add custom health checks to services:
```bash
ExecStartPost=/bin/bash -c 'custom-health-check.sh'
```