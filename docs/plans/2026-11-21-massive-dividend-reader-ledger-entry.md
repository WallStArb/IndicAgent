# Massive dividend reader: proposed ledger entry

Date: 2026-11-21. Status: proposed text for `docs/plans/methodology-change-ledger.md`
(append-only; the lead appends it after the load and fills the two measured numbers marked
TO MEASURE). Todo 651, phase B. Delete this file once the entry is in the ledger.

---

## 2026-11-21d: Massive as a dividend coverage source for total-return panels (lead ruling, owner veto reserved)

Recorded before any counted run on a total-return panel that reads Massive coverage.

What changes. A total-return panel prices a symbol on a session only where its dividends are
known. Until now only Yahoo's coverage decided that, and Yahoo covers the 1,529 names that were
live when it was asked, so every dead member of the stage 2 universe was NaN and a total-return
test ran on survivors. From this entry the research reader takes a session's dividend facts from
one source, first match wins: Yahoo where its span covers the session (the reconciled Yahoo and
IBKR facts, unchanged), else Massive where its claim (`massive-dividend-coverage-v1`, migration
608, `docs/plans/2026-11-21-massive-dividend-coverage-rule.md`) covers it and no gap of the claim
holds it. A Massive yield is the raw cash amount over the stored raw prior close; every Massive
event is unconfirmed (one source), so `suspect_yield` splits the name at one above it, as at any
one-source event; an event declared after its ex-date leaves its session unknown; a covered
session after a hole inside coverage starts a new segment, so no return window spans unknown
dividends.

The coverage claim. A Massive claim runs from a name's first stored ex-date to its last plus
0.75 payment intervals (capped at 400 days, the capture date 2026-11-10 and the end of the
name's last ticker span), minus cadence holes (gaps over 1.5 intervals), the days between ticker
spans and the ex-dates the writer could not store. Phase A measured it against Yahoo on live
names (0.099% silent misses, spin-offs the material class) and against the price drop on dead
names (no excess of unlisted dividend-sized drops); the dry run claimed 14,295 names and 52,296
member-years, 36,339 of them dead. Loaded counts: TO MEASURE (member-years gained on the real
first counted panel).

Disclosed residuals.
- Survivorship. A dead member Massive lists no dividend for gets no claim and drops out of a
  total-return panel: about 5,900 dead members by the Phase A recon (TO MEASURE on the loaded
  coverage). Dead non-payers are under-represented in total-return panels; a price-only panel
  of the same spec keeps them.
- Non-cash distributions. Massive carries cash only. A spin-off or return of capital in a
  Massive span stays in the prices as a loss. No price-based guard: on the Yahoo-covered names,
  98% of overnight drops above 10% (6,119 of 6,241 in 6,406,077 sessions) fall on no ex-date,
  so a guard would split dead names at their earnings and news gaps and remove their crash
  returns from the targets. The event-explained rate on live names, about 1.9 per 100,000
  sessions, is an upper estimate of the missed class.
- Look-ahead. Coverage never passes the capture date and no stored event lies after it; an
  event declared after its ex-date is not applied at that ex-date.

Unchanged. A name with only Yahoo coverage keeps its per-session dividend arrays bit for bit
(tested); the snapshot manifest now records the coverage sources and the Massive lineage, so
snapshot hashes move. `repro_frozen`: bit-identical at the landing commit. E17 battery code keys
unchanged: daily residual `3632233bc6102594ed8f275b091de107c240bf1d3dc19d1f50807e99a187b320`,
seasonality `ae9ff30d86e27d1b3c64e71a18e3c5258fd731dc4d0e1068e892254011f67d40` (the reader
modules are outside both import closures). The feature factory and the reconciliation audit read
only the Yahoo and IBKR sources, with output unchanged; a CI test refuses any new unfiltered
`dividend_events` read.

Pre-registered? Yes: the precedence, the yield, the unconfirmed rule, the declared_on rule, the
hole split and the no-guard decision are fixed in code and in the design note before any counted
run reads Massive coverage.
