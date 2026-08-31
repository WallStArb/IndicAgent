---
status: pending
priority: P2
filed: 2026-08-31
source: fixing todo 306's live-IBKR-ingestion gap live -- found the real root cause
  was a missing container package, fixed live but not durably
---

# `ib-gateway`'s missing `libgtk-3-0` fix was applied live, not baked into the image -- will silently regress on container recreation

## What

Live IBKR ingestion was down 16 days (2026-08-15 -> 2026-08-31), originally misdiagnosed as
a 2FA-approval-needed loop (see `project_ibkr_live_ingestion_stalled_2fa` memory for the full
corrected root-cause writeup). Actual cause: `ghcr.io/gnzsnz/ib-gateway:stable`'s Ubuntu 24.04
base image is missing `libgtk-3-0` entirely -- JavaFX's bundled `libglassgtk3.so` native
adapter has nothing to link against, so the gateway's UI thread fails during startup
(`UnsupportedOperationException: Unable to load glass GTK library`) and the process wedges
forever right after completing authentication, never opening its API port.

Fixed live 2026-08-31 via `docker exec -u root ib-gateway apt-get install -y libgtk-3-0`
against the already-running container, then a restart. This works and survives a plain
`docker restart` (same container, same writable layer) but will **NOT** survive:
- `docker compose up --force-recreate`
- removing and recreating the container
- an image re-pull (`:stable` is a rolling tag -- a future pull could reset this even
  without an explicit force-recreate, depending on how `docker compose up` is invoked)

If any of those happen, this exact 16-day-outage bug returns silently -- nothing currently
checks for or alerts on this specific failure mode.

## What to do

Add a small wrapper Dockerfile so the fix survives container recreation:

```dockerfile
FROM ghcr.io/gnzsnz/ib-gateway:stable
USER root
RUN apt-get update && apt-get install -y --no-install-recommends libgtk-3-0 \
    && rm -rf /var/lib/apt/lists/*
USER ibgateway
```

Reference it from `production/docker-compose.yml`'s `ib-gateway` service (`build:` instead
of the bare `image:` line, or keep `image:` pointing at a locally-built/tagged image), so
`docker compose up` (with or without `--force-recreate`) always produces a container with
the library present.

## References

- `project_ibkr_live_ingestion_stalled_2fa` memory -- full incident writeup, screenshots,
  verification steps
- `production/docker-compose.yml` line ~272, `ib-gateway` service
- todo 306 -- the live-ingestion-stalled todo this was found fixing
