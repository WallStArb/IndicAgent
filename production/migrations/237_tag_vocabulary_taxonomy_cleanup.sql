-- Migration 237: Tag vocabulary taxonomy cleanup (Phase 146 Wave 0)
--
-- Three data operations, no schema changes. Verified live against the indicagent DB
-- on 2026-07-17 before writing this migration -- see 146-CONTEXT.md D-03/D-07/D-09
-- and 146-RESEARCH.md for the full decision record.
--
-- (a) credit_cycle -> credit_risk merge (D-03): 8 credit_cycle holders (HYG, IWM,
--     LQD, PFF, XHB, XLF, XLY, XRT). Only HYG and LQD already carry a credit_risk
--     row, both at weight >= credit_cycle's weight (HYG 1.0>=0.9, LQD 0.8>=0.8) --
--     no bump needed for those two. The other 6 (IWM, PFF, XHB, XLF, XLY, XRT) have
--     no credit_risk row at all -- migrate their credit_cycle weight into a new
--     credit_risk row before the delete so the signal is not silently dropped.
-- (b) housing_cycle deletion (D-07): XHB is the sole holder and its own factor
--     series -- a self-regression tautology, not a low-population call. Delete
--     outright.
-- (c) spread_leg evidence backfill (D-09): 28 rows, 17 with NULL evidence.
--     4 rows mechanically recoverable from mirror mentions in other rows'
--     evidence text (LQD<-CWB, TLT<-EDV, SPY<-IPO/EZU, SCHD<-VYM); the 11
--     already-evidenced rows get a `pair` key added (they previously only carried
--     `reason` prose, no structured pair field); 3 reciprocal rows are inserted
--     (UUP, USMV, FXI) whose partners already referenced them in prose but had no
--     row of their own; the 13 remaining NULL-evidence rows are deleted
--     (unrecoverable -- no mirror mention exists anywhere in the table).
--
-- Nodes with more than one legitimate spread partner (SPY, FXY, FXE, VYM) carry
-- `pair` as a JSON array rather than a single string -- these are hub instruments
-- genuinely paired against multiple legs (derived from each partner's own
-- pre-existing `reason` text), not an arbitrary pick-one simplification that would
-- silently orphan a pre-existing relationship.
--
-- Auditable record of what changed:
--   BACKFILLED (pair key added to already-evidenced rows): CWB, EDV, EZU, FXA,
--     FXE, FXY, IPO, MCHI, SDOG, SPHB, VYM
--   BACKFILLED (NULL evidence -> full evidence, mechanically recoverable):
--     LQD, SCHD, SPY, TLT
--   INSERTED (missing reciprocal rows): UUP (<-FXE), USMV (<-SPHB), FXI (<-MCHI)
--   DELETED (unrecoverable NULL evidence, no mirror mention exists): AGG, EWY,
--     HYG, IEF, KRE, OIH, RSP, SLV, TIP, VNQ, VTV, VUG, XOP

BEGIN;

-- ── (a) credit_cycle -> credit_risk merge (D-03) ───────────────────────────────

-- Defensive migration: any credit_cycle holder lacking a credit_risk row gets one
-- inserted at the credit_cycle weight (there is no existing credit_risk weight to
-- take a max against for these six) before the delete, so the signal is preserved.
INSERT INTO instrument_tags (symbol, tag, weight, source)
SELECT ct.symbol, 'credit_risk', ct.weight, 'human'
FROM instrument_tags ct
WHERE ct.tag = 'credit_cycle'
  AND NOT EXISTS (
      SELECT 1 FROM instrument_tags cr
      WHERE cr.symbol = ct.symbol AND cr.tag = 'credit_risk'
  );

DELETE FROM instrument_tags WHERE tag = 'credit_cycle';
DELETE FROM tag_vocabulary WHERE tag = 'credit_cycle';

-- ── (b) housing_cycle deletion (D-07) ──────────────────────────────────────────
-- Self-regression tautology: housing_cycle's sole holder (XHB) IS its own factor
-- series. Delete outright -- not a low-population call, a broken-concept one.

DELETE FROM instrument_tags WHERE tag = 'housing_cycle';
DELETE FROM tag_vocabulary WHERE tag = 'housing_cycle';

-- ── (c) spread_leg evidence backfill (D-09) ────────────────────────────────────

-- Add a structured `pair` key to rows that already carry `reason` prose mentioning
-- their partner, but no `pair` field.
UPDATE instrument_tags SET evidence = evidence || '{"pair": "LQD"}'::jsonb
    WHERE symbol = 'CWB' AND tag = 'spread_leg';
UPDATE instrument_tags SET evidence = evidence || '{"pair": "TLT"}'::jsonb
    WHERE symbol = 'EDV' AND tag = 'spread_leg';
UPDATE instrument_tags SET evidence = evidence || '{"pair": "SPY"}'::jsonb
    WHERE symbol = 'EZU' AND tag = 'spread_leg';
UPDATE instrument_tags SET evidence = evidence || '{"pair": "FXY"}'::jsonb
    WHERE symbol = 'FXA' AND tag = 'spread_leg';
UPDATE instrument_tags SET evidence = evidence || '{"pair": ["FXY", "UUP"]}'::jsonb
    WHERE symbol = 'FXE' AND tag = 'spread_leg';
UPDATE instrument_tags SET evidence = evidence || '{"pair": ["FXA", "FXE"]}'::jsonb
    WHERE symbol = 'FXY' AND tag = 'spread_leg';
UPDATE instrument_tags SET evidence = evidence || '{"pair": "SPY"}'::jsonb
    WHERE symbol = 'IPO' AND tag = 'spread_leg';
UPDATE instrument_tags SET evidence = evidence || '{"pair": "FXI"}'::jsonb
    WHERE symbol = 'MCHI' AND tag = 'spread_leg';
UPDATE instrument_tags SET evidence = evidence || '{"pair": "VYM"}'::jsonb
    WHERE symbol = 'SDOG' AND tag = 'spread_leg';
UPDATE instrument_tags SET evidence = evidence || '{"pair": "USMV"}'::jsonb
    WHERE symbol = 'SPHB' AND tag = 'spread_leg';
UPDATE instrument_tags SET evidence = evidence || '{"pair": ["SDOG", "SCHD"]}'::jsonb
    WHERE symbol = 'VYM' AND tag = 'spread_leg';

-- Backfill the 4 mechanically-recoverable NULL-evidence rows.
UPDATE instrument_tags
    SET evidence = '{"pair": "CWB", "reason": "LQD/CWB convertible vs straight-credit spread (reciprocal of CWB''s evidence)"}'::jsonb
    WHERE symbol = 'LQD' AND tag = 'spread_leg';
UPDATE instrument_tags
    SET evidence = '{"pair": "VYM", "reason": "SCHD/VYM quality-dividend vs raw-yield spread (reciprocal of VYM''s evidence)"}'::jsonb
    WHERE symbol = 'SCHD' AND tag = 'spread_leg';
UPDATE instrument_tags
    SET evidence = '{"pair": ["IPO", "EZU"], "reason": "SPY is the broad-market spread leg for IPO (high-beta) and EZU (US vs Europe) pairs (reciprocal of IPO/EZU evidence)"}'::jsonb
    WHERE symbol = 'SPY' AND tag = 'spread_leg';
UPDATE instrument_tags
    SET evidence = '{"pair": "EDV", "reason": "TLT/EDV duration spread (reciprocal of EDV''s evidence)"}'::jsonb
    WHERE symbol = 'TLT' AND tag = 'spread_leg';

-- Insert the 3 missing reciprocal rows -- already named by their partner's
-- evidence, but had no spread_leg row of their own.
INSERT INTO instrument_tags (symbol, tag, weight, source, evidence) VALUES
('UUP',  'spread_leg', 1.0, 'human', '{"pair": "FXE", "reason": "UUP/FXE spread (reciprocal of FXE''s evidence)"}'::jsonb),
('USMV', 'spread_leg', 0.8, 'human', '{"pair": "SPHB", "reason": "SPHB/USMV high-beta vs low-vol factor spread (reciprocal of SPHB''s evidence)"}'::jsonb),
('FXI',  'spread_leg', 0.8, 'human', '{"pair": "MCHI", "reason": "FXI vs MCHI spread (H-share vs MSCI divergence) (reciprocal of MCHI''s evidence)"}'::jsonb);

-- Delete the 13 unrecoverable NULL-evidence rows -- no mirror mention exists
-- anywhere in the table; fabricating a pair would violate D-09's "unrecoverable
-- rows get deleted, not guessed".
DELETE FROM instrument_tags
    WHERE tag = 'spread_leg'
      AND symbol IN ('AGG', 'EWY', 'HYG', 'IEF', 'KRE', 'OIH', 'RSP', 'SLV', 'TIP', 'VNQ', 'VTV', 'VUG', 'XOP');

COMMIT;
