-- Migration 370: indicagent_v1 level-4 nodes for the 2026-09-26 universe expansion
--
-- The Dow Utilities names, the S&P 500 constituents and the two down-cap draws (config/universe/r2k_draw_2026_09_26.csv
-- from IWM holdings, r3k_rank1001_draw_2026_09_26.csv from IWV ranks 1001+) include industries the Phase 182 build-date tree
-- (migration 365) had no instrument in, so it never minted those nodes. Each node below reuses
-- the public GICS industry name under its existing indicagent_v1 level-3 parent, as migration
-- 365 did. Additive only: no existing node or assignment changes.
--
-- classification_node's insert trigger requires valid_from = classification_write_date()
-- (today, UTC), so this migration must run in one transaction that starts and ends on the same
-- UTC day. The ON CONFLICT clause makes a re-run a no-op.

BEGIN;

INSERT INTO classification_node (scheme, code, parent_code, level, name, path, valid_from)
SELECT 'indicagent_v1', n.code, n.parent_code, 4, n.name,
       p.path || n.code, classification_write_date()
FROM (VALUES
    ('EQ.UTL.UTILITIES.GAS', 'EQ.UTL.UTILITIES', 'Gas Utilities'),
    ('EQ.RE.MGMT.MGMTDEV', 'EQ.RE.MGMT', 'Real Estate Management & Development'),
    ('EQ.RE.REITS.DIVERSIFIED', 'EQ.RE.REITS', 'Diversified REITs'),
    ('EQ.RE.REITS.HEALTHCARE', 'EQ.RE.REITS', 'Health Care REITs'),
    ('EQ.RE.REITS.HOTEL', 'EQ.RE.REITS', 'Hotel & Resort REITs'),
    ('EQ.RE.REITS.OFFICE', 'EQ.RE.REITS', 'Office REITs'),
    ('EQ.RE.REITS.RESIDENTIAL', 'EQ.RE.REITS', 'Residential REITs'),
    ('EQ.IT.HARDWARE.COMMEQUIP', 'EQ.IT.HARDWARE', 'Communications Equipment'),
    ('EQ.IT.HARDWARE.ELECEQUIP', 'EQ.IT.HARDWARE', 'Electronic Equipment, Instruments & Components'),
    ('EQ.IND.COMMSVC.COMMERCIAL', 'EQ.IND.COMMSVC', 'Commercial Services & Supplies'),
    ('EQ.IND.CAPGOODS.BUILDING', 'EQ.IND.CAPGOODS', 'Building Products'),
    ('EQ.IND.CAPGOODS.CONSTRUCTION', 'EQ.IND.CAPGOODS', 'Construction & Engineering'),
    ('EQ.MAT.MATERIALS.CONSTRUCTION', 'EQ.MAT.MATERIALS', 'Construction Materials'),
    ('EQ.MAT.MATERIALS.CONTAINERS', 'EQ.MAT.MATERIALS', 'Containers & Packaging'),
    ('EQ.CD.RETAIL.DISTRIBUTORS', 'EQ.CD.RETAIL', 'Distributors'),
    ('EQ.CS.HOUSEHOLD.PERSONAL', 'EQ.CS.HOUSEHOLD', 'Personal Care Products'),
    ('EQ.HC.PHARMA.LIFESCI', 'EQ.HC.PHARMA', 'Life Sciences Tools & Services'),
    ('EQ.CD.SERVICES.DIVERSIFIED', 'EQ.CD.SERVICES', 'Diversified Consumer Services')
) AS n(code, parent_code, name)
JOIN classification_node p ON p.scheme = 'indicagent_v1' AND p.code = n.parent_code
ON CONFLICT (scheme, code) DO NOTHING;

COMMIT;
