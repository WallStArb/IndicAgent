-- Migration 372: fixed-income nodes and exposure tags for the 2026-09-26 ETF expansion
--
-- config/universe/expansion_etfs_2026_09_26.csv adds mortgage-backed (MBB), leveraged-loan
-- (BKLN) and non-US developed bond (BNDX, BWX) funds. The indicagent_v1 tree (migration 365)
-- had no node for any of the three, and tag_vocabulary no exposure tag for MBS or non-US
-- bonds. Additive only: no existing node, tag or assignment changes.
--
-- classification_node's insert trigger requires valid_from = classification_write_date()
-- (today, UTC), so this migration must run in one transaction that starts and ends on the same
-- UTC day. The ON CONFLICT clauses make a re-run a no-op.

BEGIN;

INSERT INTO classification_node (scheme, code, parent_code, level, name, path, valid_from)
SELECT 'indicagent_v1', n.code, n.parent_code, p.level + 1, n.name,
       p.path || n.code, classification_write_date()
FROM (VALUES
    ('FI.SECURITIZED', 'FI', 'Securitized (mortgage- and asset-backed)'),
    ('FI.INTL', 'FI', 'Non-US developed-market bonds'),
    ('FI.CREDIT.LOANS', 'FI.CREDIT', 'Leveraged loans')
) AS n(code, parent_code, name)
JOIN classification_node p ON p.scheme = 'indicagent_v1' AND p.code = n.parent_code
ON CONFLICT (scheme, code) DO NOTHING;

INSERT INTO tag_vocabulary (tag, category, description, measurement_type)
VALUES
    ('fi_mbs', 'exposure', 'Agency mortgage-backed securities', 'definitional'),
    ('fi_intl', 'exposure', 'Non-US developed-market bonds', 'definitional')
ON CONFLICT (tag) DO NOTHING;

COMMIT;
