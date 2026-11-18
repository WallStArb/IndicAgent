#!/bin/bash
# Todo 609 membership build and the corpus rerun pin prerequisites, one named step at a time.
# Written 2026-11-15 from docs/plans/2026-11-15-post-d1-landing-runbook.md (steps 5a, 11, 12, 13 and section 5), the
# stage 2 preregistration (gates in the 2026-11-14 order), docs/plans/2026-11-15-stage2-5m-tier-and-intraday-universe.md,
# the universe wiring plan and the readiness README. NOT RUN: bash -n only. The lead launches each step.
#
#   bash run_609.sh list                    steps, markers and gaps
#   bash run_609.sh gaps                    the commands that do not exist yet or could not be confirmed
#   bash run_609.sh <step>                  dry or read-only form
#   RUN609_CONFIRM=<step> bash run_609.sh <step> --apply     a writing form (the confirm names the step)
# Heavy steps (s4, s5, s8) run for a long time: launch with  setsid nohup bash run_609.sh <step> > /dev/null 2>&1 &
# Every step runs after its predecessor's marker in run_609_status.txt, logs to run_609_<step>.log, and halts on nonzero.
#
# Order (preregistration amendment 2026-11-14: gate 4 and the map rebuild come before the all-ticker load):
#   s0 preflight   s1 migration 597   s2 pit-anchor identity map (scratch)   s3 pit install: dead-name instrument rows, identifiers, spans
#   s4 all-ticker 1d load   s4b unplaced share of liquid rows by year and type (owner-visible)   s5 membership (rehearsal, then apply)   s6 member and tier counts by year (owner, gate 5)
#   s7 5m tier cost estimate   s8 rerun pin prerequisites (plan-only; the writing steps are printed, never run)
set -u
cd /home/bg/dev/indicagent || exit 2
PY=.venv/bin/python
D=logs/massive_step7/post_step7_readiness_20261115
S=$D/run_609_status.txt
PSQL="env PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -At -F| -v ON_ERROR_STOP=1"
PSQLC="env PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent --csv -v ON_ERROR_STOP=1"
THROUGH=${RUN609_THROUGH:-2026-10-30}        # the last month-end to build: the writer builds every NYSE month-end up to it
STEP=${1:-list}
APPLY=0; [ "${2:-}" = --apply ] && APPLY=1

note(){ echo "$* $(date -u +%FT%TZ)" >> "$S"; }
die(){ echo "REFUSED: $*"; note "609_$STEP REFUSED: $*"; exit 2; }
done_(){ grep -q "^609_$1 DONE" "$S" 2>/dev/null; }
need(){ done_ "$1" || die "step $1 has not finished (no '609_$1 DONE' in $S)"; }
q(){ $PSQL -c "$1"; }
confirm(){ [ $APPLY -eq 1 ] || return 1; [ "${RUN609_CONFIRM:-}" = "$STEP" ] || die "--apply needs RUN609_CONFIRM=$STEP"; return 0; }
quiet_host(){
  [ "$(hostname)" = ubuntu1 ] || die "run on ubuntu1"
  pgrep -f '[o]ps_canonical_rebuild|[o]ps_massive_load|[b]ar_reconciliation_audit|[b]ar_derivation|[u]niverse_membership_writer|[c]orpus_rerun|[r]un_partf' > /dev/null && die "a heavy job is running (one at a time)"
}
# run NAME CMD...   logs, records, halts on nonzero
run(){ n=$1; shift; note "start 609_${STEP}_$n"; "$@" > "$D/run_609_${STEP}_$n.log" 2>&1; c=$?; note "end 609_${STEP}_$n exit=$c"
  [ $c -eq 0 ] || { note "609_$STEP STOPPED at $n"; echo "STOPPED at $n (log $D/run_609_${STEP}_$n.log)"; exit $c; }; }
gap(){ echo "GAP: $*"; note "609_$STEP BLOCKED: $*"; exit 3; }

case "$STEP" in
list)
  for s in s0 s1 s2 s3 s4 s4b s5 s6 s7 s8; do
    printf '%-4s %s\n' "$s" "$(grep -E "^609_$s (DONE|REHEARSAL DONE|APPLIED|BLOCKED)" "$S" 2>/dev/null | tail -1 | cut -c1-90)"; done
  echo "s0 preflight | s1 apply 597 | s2 pit-anchor identity map (scratch build) | s3 pit install: dead-name instruments, identifiers, spans (rehearsal, then apply) | s4 all-ticker 1d load | s4b unplaced share by year and type (owner) | s5 membership | s6 owner counts | s7 tier cost | s8 pin prerequisites"
  echo "(markers: '609_<s> DONE'; s3 and s5 also write REHEARSAL DONE; s5 writes APPLIED)" ;;

gaps)
cat <<'EOF'
Commands the docs name that do not exist yet, or whose flags could not be confirmed (2026-11-15, read-only check):
 G1 and G2 (the pit-anchor identity map and the stage 2 instrument rows): RESOLVED by the pit-anchor branch once it lands on main
    (services.ticker_entity_map_writer --pit-anchor builds the scratch map, --pit-install installs it; s2 and s3 run them). Until it
    lands s2 reports BLOCKED because --pit-anchor is not in the writer.
 G3 5m tier feature-compute time per name-year: no query or tool gives it; the pilot (corpus_rerun --step pilot) measures
    wall time and bytes per row on the run. s7 prints rows and bytes per name-year only and says so.
 G4 member and tier counts by year before apply: the rehearsal rolls back, so the table is empty. The 2026-11-15 design
    says the writer logs members and tier members by year; the exact log line is not confirmed here (s6 greps the rehearsal
    log for 'tier' and prints it; read it, do not trust the grep).
 G5 RESOLVED 2026-11-17: ops_massive_load exits 3 and stops after a year with unselected slots or basis-change flags
    (year_gate_failure). The compare half (0 real differences, canonical unchanged for names already in canonical) is still read
    from the printed report.
 G6 modules that exist only in the held L3 worktree today: services/universe_membership_writer.py, services/corpus_universe.py,
    src/intelligence/universe_membership.py, production/migrations/597_universe_membership.sql. s0 refuses until they are on
    main and in this checkout. check_ic_universe_aligned and UNIVERSE_SOURCE are not on main (I1 not built); s8 reports it.
 G7 the 5m tier amendment is a draft (adoption pending): s5 builds under RULE_ID stage2-2026-11-15 only if that is the rule
    on main at landing; s0 prints whether the amendment text is in the preregistration.
EOF
  ;;

s0)
  quiet_host
  need_marks=0
  grep -q '^PARTD4 DONE' logs/massive_step7/partd_status.txt 2>/dev/null || { echo "WARN: PARTD4 DONE not in partd_status.txt"; need_marks=1; }
  grep -q '^PARTD5 DONE' logs/massive_step7/partd_status.txt 2>/dev/null || { echo "WARN: PARTD5 DONE not in partd_status.txt"; need_marks=1; }
  git fetch -q
  [ "$(git rev-parse HEAD)" = "$(git rev-parse origin/main)" ] || die "this checkout is not at origin/main (fast-forward it first, with no live process importing the moved modules)"
  [ -z "$(git status --porcelain -- production services src)" ] || die "uncommitted changes under production, services or src"
  for f in production/migrations/597_universe_membership.sql services/universe_membership_writer.py services/corpus_universe.py src/intelligence/universe_membership.py; do
    [ -f "$f" ] || { echo "MISSING on main: $f (gap G6: L3 not landed)"; need_marks=2; }; done
  [ $need_marks -ne 2 ] || { note "609_s0 BLOCKED: L3 not landed"; exit 3; }
  echo "== pit snapshots in reference_raw (readiness: 6,132 rows)"
  q "select count(*), count(distinct as_of) from reference_raw_current where endpoint = 'pit_snapshots'" | tee "$D/run_609_s0_pit.txt"
  echo "== tier amendment text in the preregistration (adoption marker): $(grep -c 'Amendment 2026-11-15' docs/plans/2026-11-13-stage2-universe-preregistration.md)"
  echo "== instruments: active, inactive"
  q "select is_active, count(*) from instruments group by 1 order by 1"
  [ $need_marks -eq 0 ] || echo "(warnings above: Part D4 or D5 marker missing; s0 still records DONE, the lead decides)"
  note "609_s0 DONE" ;;

s1)
  need s0; quiet_host
  # apply 597 with its guards (landing runbook 5a): the file is on main, both tables absent, its contract test passes; then psql -f
  F=production/migrations/597_universe_membership.sql
  run guard_contract_test .venv/bin/pytest -n 0 -p no:cacheprovider tests/unit/test_universe_membership_migration_contract.py -q
  have=$(q "select coalesce(to_regclass('public.universe_membership')::text,'') || '/' || coalesce(to_regclass('public.universe_membership_build')::text,'')")
  echo "present before: $have (want '/' to apply, both names to skip)"
  if [ "$have" = "universe_membership/universe_membership_build" ]; then echo "already applied; checking emptiness only"
  elif [ "$have" = "/" ]; then
    confirm || { echo "DRY: would run psql -v ON_ERROR_STOP=1 -f $F (CREATE TABLE IF NOT EXISTS; transaction; no table is rewritten, so no VACUUM clause)"; exit 0; }
    note "start 609_s1_apply"
    env PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -v ON_ERROR_STOP=1 -f "$F" > "$D/run_609_s1_apply.log" 2>&1 || { note "609_s1 STOPPED at apply"; exit 4; }
    note "end 609_s1_apply exit=0"
  else die "only one of the two tables exists ($have); a half-applied 597 needs the lead"; fi
  n1=$(q "select count(*) from universe_membership"); n2=$(q "select count(*) from universe_membership_build")
  echo "rows: universe_membership=$n1 universe_membership_build=$n2 (want 0 and 0 before the first build)"
  [ "$have" = "/" ] && confirm && { [ "$n1" = 0 ] && [ "$n2" = 0 ] || { note "609_s1 STOPPED: not empty"; exit 4; }; note "609_s1 DONE"; }
  [ "$have" = "universe_membership/universe_membership_build" ] && note "609_s1 DONE" ;;

s2)
  need s1
  # gate 4's map half: the pit-anchor identity map, built as a NEW scratch map directory under $D (never data/ticker_entity_map, never the
  # installed map); reads only, no table is written. Needs the pit-anchor landing (services/ticker_entity_map_writer.py --pit-anchor).
  grep -q -- '--pit-anchor' services/ticker_entity_map_writer.py || gap "--pit-anchor is not in services/ticker_entity_map_writer.py (the pit-anchor landing is not on main)"
  quiet_host
  PINNED=${RUN609_PINNED_MAP:-$(ls -d data/ticker_entity_map/*/ | sort | tail -1)}; PINNED=${PINNED%/}
  DIGEST=${PINNED##*_}; VD=${RUN609_VERSION_DATE:-$(date -u +%Y%m%d)}
  [ "${PINNED##*/}" != "${VD}_$DIGEST" ] || die "version date $VD names the pinned map's own directory; set RUN609_VERSION_DATE"
  echo "pinned map: $PINNED (digest $DIGEST); version date $VD"
  OUT=$D/pit_map_scratch; [ ! -e "$OUT/${VD}_$DIGEST" ] || die "$OUT/${VD}_$DIGEST exists; move it aside (evidence is never overwritten)"
  # the pin of the live spans, computed the way the builder reads them (so a span moved since the plan refuses the build)
  PINSHA=$($PY - <<'PYEOF'
import asyncio, hashlib, asyncpg
from src.config.settings import Settings
import services.ticker_entity_map_writer as w
async def main():
    conn = await asyncpg.connect(Settings().database_url.replace("postgresql+asyncpg://", "postgresql://"))
    rows = await conn.fetch(w._PIT_LIVE_SPANS_SQL)
    await conn.close()
    print(hashlib.sha256(w.spans_csv(w.live_old_spans(rows))).hexdigest())
asyncio.run(main())
PYEOF
  ) || die "could not compute the live spans pin"
  echo "live spans sha256: $PINSHA"
  run pit_anchor $PY -m services.ticker_entity_map_writer --pit-anchor --map-dir "$PINNED" --pinned-map-digest "$DIGEST" \
      --pinned-spans-sha256 "$PINSHA" --out "$OUT" --version-date "$VD"
  # record the pins the install takes (the build prints one JSON document after its log lines)
  $PY - "$D/run_609_s2_pit_anchor.log" "$D/pit_map_pins.env" "$OUT" <<'PYEOF' || { note "609_s2 STOPPED: no pins in the build output"; exit 5; }
import json, re, sys
text = open(sys.argv[1]).read()
doc = json.loads(text[text.index('{\n'):]) if '{\n' in text else json.loads(text)
name = doc["out"].rstrip("/").rsplit("/", 1)[-1]
open(sys.argv[2], "w").write(f"PITMAP={doc['out']}\nPITDIGEST={name.split('_', 1)[1]}\nPITSPANS={doc['install_spans_sha256']}\n")
print("map", name, "install_spans_sha256", doc["install_spans_sha256"])
PYEOF
  echo "read the residual by year (unplaced share of month-end records) in $D/run_609_s2_pit_anchor.log: pit.by_year and pit.bridged_months, pit.cik_renames_split"
  note "609_s2 DONE" ;;

s3)
  need s2
  # gate 4: the stage 2 instrument rows, identifiers and spans in ONE transaction through the writer's --pit-install (the onboarding SOP
  # stage 2 exception; never hand-written rows). Rehearsal by default: it installs, proves its own rollback (live rows equal the pre-install
  # sha256, the same plan again, a reinstall) and rolls everything back. The ticker_event table is locked for the run (about 10 minutes,
  # about 2 with the identity-trigger index migration applied): run in a quiet window, detached.
  [ -f "$D/pit_map_pins.env" ] || die "no $D/pit_map_pins.env: run s2 first"
  . "$D/pit_map_pins.env"
  [ -d "$PITMAP" ] || die "the scratch map $PITMAP is gone"
  quiet_host
  if confirm; then
    grep -q '^609_s3 REHEARSAL DONE' "$S" || die "rehearse first: no '609_s3 REHEARSAL DONE'"
    run pit_install_apply $PY -m services.ticker_entity_map_writer --pit-install "$PITMAP" --install-digest "$PITDIGEST" --install-spans-sha256 "$PITSPANS" --apply
    note "609_s3 DONE"
  else
    run pit_install_rehearsal $PY -m services.ticker_entity_map_writer --pit-install "$PITMAP" --install-digest "$PITDIGEST" --install-spans-sha256 "$PITSPANS"
    echo "REHEARSAL (rolled back). Read $D/run_609_s3_pit_install_rehearsal.log: outcome rolled_back, written (instruments, identifiers, spans), rollback_proof"
    echo "(live_rows_equal_pre_install true, replan_files_identical true, identifiers_retired equals identifiers_inserted). Apply: RUN609_CONFIRM=s3 bash run_609.sh s3 --apply"
    note "609_s3 REHEARSAL DONE"
  fi ;;

s4)
  need s3; quiet_host
  # preregistration gate 3: all-ticker 1d load, newest year first, gated per year; --gap-list pinned (the default sorts by digest, not time)
  [ -n "${RUN609_NEWMAP:-}" ] && [ -f "$RUN609_NEWMAP/gap_list.csv" ] || die "set RUN609_NEWMAP to the map directory s2 produced (its gap_list.csv)"
  YEARS=$(seq "${RUN609_LAST_YEAR:-2026}" -1 2003 | tr '\n' ' ')
  if confirm; then
    run load_1d $PY -m scripts.ops.bars.ops_massive_load --timeframe 1d --years $YEARS --all-tickers --gap-list "$RUN609_NEWMAP/gap_list.csv" --out "$D/all_tickers_1d" --apply
    note "609_s4 DONE"
  else
    run load_1d_dry $PY -m scripts.ops.bars.ops_massive_load --timeframe 1d --years $YEARS --all-tickers --gap-list "$RUN609_NEWMAP/gap_list.csv" --out "$D/all_tickers_1d"
    echo "DRY RUN done: read each year's line in $D/run_609_s4_load_1d_dry.log: compare 0 real differences, canonical unchanged for names already in canonical (an unselected or basis-flagged year exits 3; the compare half is not in the exit code). Apply is the same command with --apply (resumable)."
    echo "expected: about 50M raw rows for the all-ticker 1d set (preregistration); a dead name with neither a span nor a gap row refuses the run"
  fi ;;

s4b)
  need s4
  # preregistration amendment 2026-11-13: the survivorship residual, the unplaced share of rows meeting the $1M rule by year and
  # type, is measured and recorded BEFORE membership is built. Read-only: day files, the pit snapshot capture and the live spans
  # (ticker_event_current); close level, volume and dates only, no return. The tool lands with the pit-anchor branch.
  [ -f scripts/ops/bars/ops_pit_unplaced_share.py ] || gap "scripts/ops/bars/ops_pit_unplaced_share.py is not on main (the pit-anchor landing carries it)"
  quiet_host
  OUT=$D/unplaced_share_by_year_type.csv
  [ ! -e "$OUT" ] || die "$OUT exists; move it aside (evidence is never overwritten)"
  run unplaced_share $PY -m scripts.ops.bars.ops_pit_unplaced_share --out "$OUT"
  echo "== unplaced share of rows at or above the floor, by year (all types), from $OUT"
  $PY - "$OUT" <<'PYEOF'
import csv, sys, collections
tot = collections.Counter(); unp = collections.Counter()
for r in csv.DictReader(open(sys.argv[1])):
    tot[r["year"]] += int(r["rows_meeting_floor"]); unp[r["year"]] += int(r["unplaced"])
for y in sorted(tot): print(f"{y} rows={tot[y]} unplaced={unp[y]} share={unp[y] / tot[y]:.4f}")
PYEOF
  echo "Show the owner this table (by year, and by type in $OUT) and record it in the preregistration before s5 builds membership."
  note "609_s4b DONE" ;;

s5)
  need s4b; quiet_host
  # 'PYTHONPATH=. ' is not needed for the module form; the writer's docstring uses python -m services.universe_membership_writer
  if confirm; then
    grep -q '^609_s5 REHEARSAL DONE' "$S" || die "rehearse first: no '609_s5 REHEARSAL DONE'"
    run apply $PY -m services.universe_membership_writer --through "$THROUGH" --apply
    note "609_s5 APPLIED"; note "609_s5 DONE"
  else
    run rehearse $PY -m services.universe_membership_writer --through "$THROUGH"
    echo "REHEARSAL (rolled back). Read: $D/run_609_s5_rehearse.log and data/universe_membership/$THROUGH/vanished_without_final_bar.csv"
    echo "expected failures, loud and writing nothing: an incomplete month-end snapshot capture; no inactive placed symbol (survivor-only build);"
    echo "canonical not current with the splits; an empty month after the first member. Type mix: count Massive types in the snapshots against ELIGIBLE_TYPES first (design note)."
    note "609_s5 REHEARSAL DONE"
  fi ;;

s6)
  grep -qE '^609_s5 (REHEARSAL DONE|APPLIED)' "$S" 2>/dev/null || die "run s5 first"
  # gate 5: member count by year shown to the owner before any compute. Expected: typical month-end about 4,150 members (2,950 to 6,040),
  # about 16,000 securities ever (preregistration); tier about 1,313 per month-end (571 to 2,539), 5,525 ever (tier amendment draft).
  if grep -q '^609_s5 APPLIED' "$S"; then
    $PSQLC -c "
      with m as (select as_of, count(*) n, count(*) filter (where tier_5m) t from universe_membership group by as_of)
      select extract(year from as_of)::int as year, count(*) as month_ends, min(n) as members_min,
             percentile_cont(0.5) within group (order by n)::int as members_median, max(n) as members_max,
             min(t) as tier_min, percentile_cont(0.5) within group (order by t)::int as tier_median, max(t) as tier_max
        from m group by 1 order by 1" > "$D/members_tier_by_year.csv" || { note "609_s6 STOPPED"; exit 5; }
    $PSQLC -c "
      select (select count(distinct symbol) from universe_membership) as securities_ever,
             (select count(distinct symbol) from universe_membership where tier_5m) as tier_securities_ever,
             (select count(distinct rule_id) from universe_membership_build) as rule_ids,
             (select min(rule_id) from universe_membership_build) as rule_id,
             (select count(*) from universe_membership_build) as ledger_months,
             (select count(*) from universe_membership_build where n_members = 0) as empty_months" > "$D/members_tier_totals.csv" || { note "609_s6 STOPPED"; exit 5; }
    cat "$D/members_tier_by_year.csv" "$D/members_tier_totals.csv"
  else
    echo "table is empty (rehearsal rolled back); the rehearsal's own by-year lines (gap G4, unconfirmed format):"
    grep -i "tier\|members\|year" "$D/run_609_s5_rehearse.log" | head -60
  fi
  echo "Show the owner this report before any compute. Files: $D/members_tier_by_year.csv, members_tier_totals.csv"
  note "609_s6 DONE" ;;

s7)
  need s0; quiet_host
  # 5m tier cost estimate, read-only. Rows per name-year are measured on a fixed hash sample of 60 active names with 5m
  # (md5 order, no return read); the tier projection needs universe_membership (s5 applied). Feature-compute time per name-year is
  # NOT estimated here (gap G3): the corpus_rerun pilot measures it.
  $PSQLC -c "
    with s as (select symbol from instruments where is_active
               and exists (select 1 from market_data_ohlcv_tradeable t where t.symbol = instruments.symbol and t.timeframe = '5m' limit 1)
               order by md5(symbol) limit 60),
    r as (select b.symbol, extract(year from b.\"timestamp\")::int as yr, count(*) as n
            from market_data_ohlcv_tradeable b join s using (symbol)
           where b.timeframe = '5m' and b.\"timestamp\" >= '2004-01-01' and b.\"timestamp\" < '2026-01-01' group by 1, 2)
    select count(*) as name_years, sum(n) as rows, round(avg(n)) as mean_rows, percentile_cont(0.5) within group (order by n)::int as median_rows,
           percentile_cont(0.9) within group (order by n)::int as p90_rows from r" > "$D/tier_cost_rows_per_name_year.csv" || { note "609_s7 STOPPED"; exit 5; }
  $PSQLC -c "select pg_size_pretty(hypertable_size('market_data_ohlcv'::regclass)) as canonical_size,
                    approximate_row_count('market_data_ohlcv'::regclass) as canonical_rows_all_timeframes" > "$D/tier_cost_storage.csv" || { note "609_s7 STOPPED"; exit 5; }
  cat "$D/tier_cost_rows_per_name_year.csv" "$D/tier_cost_storage.csv"
  if [ "$(q "select coalesce(to_regclass('public.universe_membership')::text,'')")" = universe_membership ] && [ "$(q "select count(*) from universe_membership")" -gt 0 ]; then
    $PSQLC -c "
      select count(*) filter (where tier_5m) / 12.0 as tier_member_name_years,
             (select count(distinct symbol) from universe_membership where tier_5m) as tier_securities_ever,
             (select count(*) from (select distinct symbol, extract(year from as_of) from universe_membership
                                     where symbol in (select symbol from universe_membership where tier_5m)) w) as tier_whole_history_name_years_lower_bound
        from universe_membership" > "$D/tier_cost_projection.csv" || { note "609_s7 STOPPED"; exit 5; }
    cat "$D/tier_cost_projection.csv"
    echo "Projected 5m rows = name-years x median rows per name-year; the tier amendment's planning figure is 46k whole-history name-years (0.6 to 0.9 billion rows). Record the estimate as the amendment's last step before the tier load."
  else echo "no membership rows yet: the tier projection is skipped (run after s5 --apply)."; fi
  note "609_s7 DONE" ;;

s8)
  need s5; quiet_host
  # pin prerequisites, read-only except plan-only (which the runbook says writes nothing). The writing steps are printed, never run.
  echo "== code is on main and in this checkout"; git fetch -q; [ "$(git rev-parse HEAD)" = "$(git rev-parse origin/main)" ] && echo "HEAD == origin/main" || die "checkout is not at origin/main"
  echo "== migrations applied (object checks; no version table)"
  echo "595 key infra.bar_replay.bars_per_sec rows: $(q "select count(*) from config_schema where config_key = 'infra.bar_replay.bars_per_sec'") (want 1)"
  echo "596 alpha.ic.active_scales% rows: $(q "select count(*) from config_schema where config_key like 'alpha.ic.active_scales%'") (want 0)"
  echo "597 tables: $(q "select coalesce(to_regclass('public.universe_membership')::text,'-')")"
  echo "== I1 (IC wiring) landed? UNIVERSE_SOURCE in readers (gap G6): $(grep -l 'UNIVERSE_SOURCE' services/ic_measure.py src/intelligence/research/snapshot.py 2>/dev/null | tr '\n' ' ')"
  grep -q 'UNIVERSE_SOURCE' services/ic_measure.py 2>/dev/null || echo "WARN: I1 not on main; check_ic_universe_aligned blocks the rerun until both readers declare corpus_universe"
  echo "== adoption markers: tier amendment text $(grep -c 'Amendment 2026-11-15' docs/plans/2026-11-13-stage2-universe-preregistration.md), E23 entry $(grep -c '^### E23' docs/plans/methodology-change-ledger.md) (the tier load needs the first; the first counted test needs E23)"
  echo "== corpus_run rows (readiness: 0): $(q "select count(*) from corpus_run")"
  echo "== 584 manifest: lines marked landed vs pending (the lead reads every row against git log; this count is not the check)"
  grep -ci "landed" .planning/todos/pending/584-corpus-rerun-fix-manifest.md; grep -ci "pending" .planning/todos/pending/584-corpus-rerun-fix-manifest.md
  HZ=""; [ -n "${RUN609_HORIZON:-}" ] && HZ="--horizon $RUN609_HORIZON"
  run plan_only $PY -m services.corpus_rerun --new-run --plan-only $HZ
  echo "plan-only done: read $D/run_609_s8_plan_only.log (span plan fits the limit; 1d and tier terms in the preview; the data gate verdict). It refuses when universe_membership is empty."
  cat <<'EOF'
Lead-only commands, from the main checkout at the pin commit (they write or stop timers; this script never runs them):
  .venv/bin/python -m services.corpus_rerun --quiesce
  .venv/bin/python -m services.corpus_rerun --new-run --commit <sha of main after the last code landing>     # record run id, commit, code key; edit nothing the rebuild imports after
  cd <worktree> && .venv/bin/python -m services.corpus_rerun --run-id <id> --step data_gate
  cd <worktree> && .venv/bin/python -m services.corpus_rerun --run-id <id> --step pilot                        # first corpus compute; measures wall time, bytes per row
  setsid nohup .venv/bin/python -m services.corpus_rerun --run-id <id> --through canary > /dev/null 2>&1 &
  .venv/bin/python -m services.corpus_rerun --release
Flags confirmed against --help on 2026-11-15: --new-run, --plan-only, --horizon, --commit, --run-id, --step, --through, --quiesce, --release.
EOF
  note "609_s8 DONE" ;;

*) echo "unknown step '$STEP'; try: list, gaps, s0 .. s4, s4b, s5 .. s8"; exit 2 ;;
esac
