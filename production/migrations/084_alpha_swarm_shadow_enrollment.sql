-- Phase 78 D-23/D-26: Enroll skeptic_v1 (swarm_agent) in shadow_registry.
-- Idempotent: re-running this migration does not change rows.
-- Does NOT enroll correlation_v1 or volume_v1 (those agents are deleted in Plan 06).
-- shadow_registry uses component_name as PRIMARY KEY; ON CONFLICT targets it.
-- is_shadow=TRUE means shadow mode (not live); default gate params apply.

INSERT INTO shadow_registry (component_name, component_type, is_shadow)
VALUES ('skeptic_v1', 'swarm_agent', TRUE)
ON CONFLICT (component_name) DO NOTHING;
