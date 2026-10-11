# 532: session_coverage verdict anchors its denominator at first 1d bar, so early-history holes fail old names forever

Filed: 2026-10-10 late
Owner: pending
Priority: P1 if the 06:00 UTC verdict refresh leaves the cohort red; P2 otherwise
(discovered triaging the 186-26 d2_landed gate failure)

Evidence (indicagent-87, D7 sweep 2026-10-10 late): the 263-name session_coverage
failure set behind 186-26's d2_landed gate splits into near-boundary names missing
the paused 2026-10-09 session (self-heals: the deep 5m backfill's 1d lane resumed
pulls and refetches it) and genuinely holed names (AAOI 0.032, AGL 0.394, ACMR 0.613,
ADPT 0.684). The holed names are not young: session_coverage anchors its coverage
denominator at the name's FIRST 1d bar, so holes in early history (listing-venue
moves, vendor gaps pre-433) cap the ratio forever no matter how clean the rest of
the series is.

Design direction (87's proposal, matches todo 526's proven-span concept): anchor the
denominator at the PROVEN span (deepest stored series per provider floor, the
bar_source_policy/coverage-ledger notion of "what this name's tape actually is")
instead of first-bar-plus-holes, and make the hole policy explicit (which spans are
known-unfetchable vs unexplained) rather than a single coverage ratio failing quietly.

Process: this is a verdict-definition change feeding promotion gates, so it goes
through `docs/plans/methodology-change-ledger.md` (E-rule discipline), not an inline
edit. Triage first against the 06:00 UTC 2026-10-11 bar_reconciliation_audit: if the
holed cohort is still red on fresh verdicts, write the ledger entry and change the
verdict in the same session. Cross-links: todo 526 (per-TF provider floors),
todo 433 (listing-venue truncation), 186-26's d2_landed gate (the consumer).
