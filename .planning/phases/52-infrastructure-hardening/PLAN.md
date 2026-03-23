# Phase 52: Infrastructure Hardening

**Status:** 📋 Planned

**Milestone:** v2.1 Data Foundation & Signal Confidence

**Dependencies:** Phase 51 (validation framework in place)

---

## Goals

1. **Docker Restart Policies** — Add `restart: unless-stopped` to timescaledb and redpanda
2. **Automated Gap-Fill** — On service restart, automatically fill missing bars
3. **Log Rotation** — Prevent unbounded log file growth
4. **Deploy Scripts** — deploy_dashboard.sh for production builds
5. **Health Check Endpoints** — /health endpoints for all services
6. **No Manual Steps** — Entire pipeline runs without manual intervention

---

## Success Criteria

1. timescaledb and redpanda survive server reboot
2. Gap-fill service detects and fills missing bars automatically on restart
3. Log files rotate (max size, retention policy)
4. Dashboard deployable with single `./deploy_dashboard.sh` command
5. All services respond to GET /health with status
6. Full pipeline recovery from cold start requires zero manual steps

---

## Plans

(TBD — Planning will occur when Phase 51 is complete)
