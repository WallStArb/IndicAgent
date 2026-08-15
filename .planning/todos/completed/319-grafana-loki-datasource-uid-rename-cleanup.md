# 319: Rename Loki's Grafana datasource uid from auto-generated hex to "loki"

**Filed:** 2026-08-15
**Closed:** 2026-08-15
**Priority:** P3 (cosmetic/debt, not blocking)

## Resolution

Grafana's `PUT /api/datasources/uid/:uid` rejects an in-place uid change
(`500 Failed to update datasource`) -- uid is immutable via that endpoint, as
suspected. Went with `DELETE /api/datasources/uid/P8E80F9AEF21F6940` +
restart, letting file provisioning recreate the datasource fresh under
`uid: loki`. Grafana came back stable (25s+, no new errors) and both
correlation directions re-verified live against the new uid:
`Loki.jsonData.derivedFields[0].datasourceUid: tempo`,
`Tempo.jsonData.tracesToLogsV2.datasourceUid: loki`. Comment block and
literal removed from `datasources.yml`; the anchor (`&loki_uid` /
`*loki_uid`) now carries the readable string, matching
`uid: prometheus` / `uid: tempo`.

## Context

While wiring log<->trace correlation (Loki `derivedFields` -> Tempo,
Tempo `tracesToLogsV2` -> Loki) in
`production/grafana/provisioning/datasources/datasources.yml`, discovered
Loki's Grafana datasource has never had an explicit `uid` pinned in
provisioning -- it carries an auto-generated opaque value
(`P8E80F9AEF21F6940`) from whenever it was first created, unlike Prometheus
(`uid: prometheus`) and Tempo (`uid: tempo`), which were provisioned with
human-readable uids from day one.

Attempting to pin a fresh human-readable `uid: loki` in provisioning (instead
of the real existing value) crash-loops Grafana indefinitely on startup --
confirmed live 2026-08-15. Grafana's provisioning reconciler finds a
datasource already named "Loki" under the real auto-generated uid, can't
reconcile it against the different uid string in the file, and fails
deterministically (not a flake -- every restart hits the same conflict).

Current state uses the real value, aliased once via a YAML anchor
(`&loki_uid` / `*loki_uid`) so it's defined in exactly one place in
`datasources.yml`, with a comment marking why. Functionally correct and
stable, but the value itself is an opaque magic string that doesn't match
the `uid: prometheus` / `uid: tempo` convention.

## Fix

One-time operational step, not a code change:
1. Rename the Loki datasource's `uid` to `loki` via the Grafana API
   (`PUT /api/datasources/uid/P8E80F9AEF21F6940`) or the UI.
2. Update `datasources.yml`: replace `P8E80F9AEF21F6940` with `loki` at the
   anchor definition. The alias reference downstream doesn't need to change.
3. Restart Grafana, confirm both correlation directions still resolve
   (`curl -u admin:admin localhost:3001/api/datasources` should show
   `Loki` uid `loki`, and Tempo's `tracesToLogsV2.datasourceUid` should
   match).

## Why deferred

Purely cosmetic -- current wiring works and is stable. Not worth blocking
the correlation feature on. Low risk, cheap to do later; only gets more
annoying if more dashboards start referencing the opaque uid directly in
the meantime.
