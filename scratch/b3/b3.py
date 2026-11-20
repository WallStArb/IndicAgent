import psycopg, sys, time
conn=psycopg.connect("postgresql://postgres:postgres@localhost/indicagent", autocommit=True)
x=conn.execute
x("set statement_timeout='900s'")
for tag,d in (("08","2008-06-30"),("12","2012-06-29"),("16","2016-09-30")):
    x(f"""create temp table snap{tag} as
select distinct on (e->>'ticker') e->>'ticker' ticker, e->>'type' ty, (e->>'active')::bool active, e->>'composite_figi' figi, e->>'cik' cik, e->>'name' nm, e->>'delisted_utc' delisted
from reference_raw_current r, jsonb_array_elements(case when jsonb_typeof(r.body->'results')='array' then r.body->'results' else '[]'::jsonb end) e
where r.endpoint='pit_snapshots' and r.as_of='{d}' and r.http_status=200
order by e->>'ticker', (r.request_key like '%@active') desc""")
    x(f"""create temp table cand{tag} as
with r as (select symbol, (timestamp at time zone 'UTC')::date as day, close, volume from market_data_ohlcv_tradeable where timeframe='1d' and timestamp >= '{d}'::date-130 and timestamp < '{d}'::date+1),
r2 as (select *, row_number() over (partition by symbol order by day desc) rn from r),
l as (select symbol, count(*) n, percentile_disc(0.5) within group (order by close*volume) med, max(day) lastday, max(close) filter (where rn=1) lastclose from r2 where rn<=60 group by 1)
select * from l where lastday='{d}'::date and med>=1000000""")
    x(f"""create temp table nm{tag} as
select c.*, p.ticker, s.ty, s.active, s.figi, s.cik, s.nm, s.delisted,
 case when p.ticker is null then 'placement' when s.ticker is null then 'type_missing_not_in_list' when s.ty is null then 'type_missing'
      when s.ty not in ('CS','ADRC','ETF') then 'type_ineligible' when c.n<60 then 'history' when c.lastclose<1 then 'price' else 'other' end reason
from cand{tag} c
left join (select distinct on (te.symbol) te.symbol, te.ticker from ticker_event te where te.vendor='massive' and te.retired_at is null and te.valid_from<='{d}'::date and (te.valid_to is null or '{d}'::date<te.valid_to) order by te.symbol, te.ticker) p using(symbol)
left join snap{tag} s on s.ticker=p.ticker
where c.symbol not in (select symbol from universe_membership where as_of='{d}'::date)""")
    print(tag, x(f"select count(*) from nm{tag}").fetchone())
x("create temp table want as select ticker from nm08 where reason='type_missing' union select ticker from nm12 where reason='type_missing'")
t=time.time()
x("""create temp table allsnap as
select r.as_of, e->>'ticker' ticker, e->>'type' ty, e->>'composite_figi' figi, e->>'cik' cik, e->>'name' nm
from reference_raw_current r, jsonb_array_elements(case when jsonb_typeof(r.body->'results')='array' then r.body->'results' else '[]'::jsonb end) e
where r.endpoint='pit_snapshots' and r.http_status=200 and (e->>'ticker') in (select ticker from want)""")
print("allsnap", x("select count(*), count(ty) from allsnap").fetchone(), round(time.time()-t))
x("create temp table wfig as select distinct figi from allsnap where figi is not null")
t=time.time()
x("""create temp table figsnap as
select r.as_of, e->>'ticker' ticker, e->>'type' ty, e->>'composite_figi' figi
from reference_raw_current r, jsonb_array_elements(case when jsonb_typeof(r.body->'results')='array' then r.body->'results' else '[]'::jsonb end) e
where r.endpoint='pit_snapshots' and r.http_status=200 and (e->>'composite_figi') in (select figi from wfig) and e->>'type' is not null""")
print("figsnap", x("select count(*) from figsnap").fetchone(), round(time.time()-t))

# ---- full scans, one session ----
t=time.time()
x("""create temp table allsnap_full as
select r.as_of, e->>'ticker' ticker, e->>'type' ty, e->>'composite_figi' figi, e->>'cik' cik, e->>'name' nm, (e->>'active')::bool act
from reference_raw_current r, jsonb_array_elements(case when jsonb_typeof(r.body->'results')='array' then r.body->'results' else '[]'::jsonb end) e
where r.endpoint='pit_snapshots' and r.http_status=200""")
x("create index on allsnap_full(ticker)"); x("create index on allsnap_full(figi)")
print("allsnap_full", x("select count(*), count(ty), count(figi) from allsnap_full").fetchone(), round(time.time()-t))
x("""create temp table ov as select body->'results'->>'ticker' ticker, body->'results'->>'type' ty, body->'results'->>'composite_figi' figi,
 body->'results'->>'cik' cik, body->'results'->>'name' nm, (body->'results'->>'active')::bool act, body->'results'->>'delisted_utc' delisted
 from reference_raw_current where endpoint='overview' and http_status=200""")
x("create index on ov(ticker)"); x("create index on ov(figi)")
x("create temp table tev as select symbol, ticker, valid_from, valid_to from ticker_event where vendor='massive' and retired_at is null")
x("create index on tev(ticker)")
x("create temp table symfigi as select distinct symbol, value figi from security_identifier where scheme='composite_figi' and retired_at is null")
x("create index on symfigi(figi)")
x("create index on symfigi(symbol)")
# conflicts: one FIGI, more than one type across snapshots (and overview)
print("figi with >1 snapshot type:", x("select count(*) from (select figi from allsnap_full where figi is not null and ty is not null group by 1 having count(distinct ty)>1) q").fetchone(),
      "of", x("select count(distinct figi) from allsnap_full where figi is not null and ty is not null").fetchone())
print("conflict examples:", x("select figi, array_agg(distinct ty) from allsnap_full where figi is not null and ty is not null group by 1 having count(distinct ty)>1 limit 8").fetchall())
print("ticker with >1 snapshot type:", x("select count(*) from (select ticker from allsnap_full where ty is not null group by 1 having count(distinct ty)>1) q").fetchone())
# per-security (symbol) type by source
x("""create temp table s1 as   -- own snapshot rows: the ticker the symbol held on that date
select t.symbol, mode() within group (order by a.ty) ty, count(distinct a.ty) nty, count(*) n
from allsnap_full a join tev t on t.ticker=a.ticker and t.valid_from<=a.as_of and (t.valid_to is null or a.as_of<t.valid_to)
where a.ty is not null group by 1""")
x("""create temp table s1f as   -- FIGI carry: any snapshot row (any ticker) with the symbol's composite figi
select f.symbol, mode() within group (order by a.ty) ty, count(distinct a.ty) nty
from symfigi f join allsnap_full a on a.figi=f.figi where a.ty is not null group by 1""")
x("""create temp table s2 as   -- overview strong: the overview record's composite figi equals the symbol's
select f.symbol, o.ty from symfigi f join ov o on o.figi=f.figi where o.ty is not null""")
x("""create temp table s2w as  -- overview weak: ticker only, the symbol held that ticker at some time
select distinct t.symbol, o.ty, o.figi ofigi, o.cik ocik from tev t join ov o on o.ticker=t.ticker where o.ty is not null""")
x("create temp table secs as select distinct symbol from tev")
print("securities (placed symbols):", x("select count(*) from secs").fetchone())
for name,q in [("typed by own snapshot rows (s1)","select count(*) from secs join s1 using(symbol)"),
  ("... plus FIGI carry (s1f, not in s1)","select count(*) from secs join s1f using(symbol) where symbol not in (select symbol from s1)"),
  ("... plus overview strong (s2, in neither)","select count(distinct symbol) from s2 where symbol not in (select symbol from s1) and symbol not in (select symbol from s1f)"),
  ("... plus overview ticker-only (in none of the above)","select count(distinct symbol) from s2w where symbol not in (select symbol from s1) and symbol not in (select symbol from s1f) and symbol not in (select symbol from s2)"),
  ("securities with a type conflict inside s1 (>1 type over own rows)","select count(*) from s1 where nty>1"),
  ("securities with s1 type != overview strong type","select count(*) from s1 join s2 using(symbol) where s1.ty<>s2.ty")]:
    print(name, x(q).fetchone())
x("""create temp table rsec as select s.symbol,
  coalesce(s1.ty, s1f.ty, s2.ty) strong_ty, case when s1.ty is not null then 's1' when s1f.ty is not null then 's1f' when s2.ty is not null then 's2' end src
 from secs s left join s1 using(symbol) left join s1f using(symbol) left join (select distinct on (symbol) symbol, ty from s2 order by symbol, ty) s2 using(symbol)""")
print("strong type distribution:", x("select strong_ty, count(*) from rsec group by 1 order by 2 desc").fetchall())
# ---- the over-floor non-members ----
for tag,d in (("08","2008-06-30"),("12","2012-06-29"),("16","2016-09-30")):
    print("=====", d)
    print("reasons", x(f"select reason, count(*) from nm{tag} group by 1 order by 2 desc").fetchall())
    x(f"""create temp table tm{tag} as select n.symbol, n.ticker, n.cik scik, n.nm, n.n, n.lastclose, n.med, i.is_active cur_active, r.strong_ty, r.src,
      (select o.ty from s2w o where o.symbol=n.symbol and o.ty is not null order by o.ty limit 1) weak_ty,
      (select string_agg(distinct o.ty, ',') from s2w o where o.symbol=n.symbol) weak_tys
     from nm{tag} n left join instruments i on i.symbol=n.symbol left join rsec r on r.symbol=n.symbol where n.reason='type_missing'""")
    print("type_missing names:", x(f"select count(*) from tm{tag}").fetchone())
    print("recovered by source:", x(f"select coalesce(src,'none'), count(*) from tm{tag} group by 1 order by 2 desc").fetchall())
    print("strong types:", x(f"select strong_ty, count(*) from tm{tag} where strong_ty is not null group by 1 order by 2 desc").fetchall())
    print("no strong, weak (ticker-only overview) types:", x(f"select coalesce(weak_tys,'none'), count(*) from tm{tag} where strong_ty is null group by 1 order by 2 desc limit 12").fetchall())
    # eligible recovered and passing history/price
    print("strong eligible & n>=60 & close>=1:", x(f"select count(*) from tm{tag} where strong_ty in ('CS','ADRC','ETF') and n>=60 and lastclose>=1").fetchone())
    print("weak-only eligible & n>=60 & close>=1:", x(f"select count(*) from tm{tag} where strong_ty is null and weak_tys is not null and weak_ty in ('CS','ADRC','ETF') and weak_tys not like '%,%' and n>=60 and lastclose>=1").fetchone())
    # survivorship: current active share
    print("current is_active: type_missing", x(f"select count(*) filter (where cur_active), count(*) filter (where not cur_active), count(*) from tm{tag}").fetchone(),
          "members", x(f"select count(*) filter (where i.is_active), count(*) filter (where not i.is_active), count(*) from universe_membership m join instruments i using(symbol) where m.as_of='{d}'").fetchone())
    print("untyped remainder name classes:", x(f"""select case when upper(nm) ~ '(\\mWT\\M|\\mWTS\\M|WARRANT)' then 'warrant' when upper(nm) ~ '(\\mUNIT\\M|\\mUNITS\\M)' then 'unit' when upper(nm) ~ '(\\mRIGHT|\\mRTS\\M)' then 'right' when upper(nm) ~ '(\\mPFD\\M|PREFERRED|\\mPRF\\M|\\mPF\\M)' then 'preferred' else 'other' end cls, count(*)
       from tm{tag} where strong_ty is null group by 1 order by 2 desc""").fetchall())

print("######## pass 2")
elig="('CS','ADRC','ETF')"
for tag,d in (("08","2008-06-30"),("12","2012-06-29"),("16","2016-09-30")):
    print("=====", d)
    # recovered by s1 with conflict
    print("s1-recovered with >1 own type:", x(f"select count(*) from tm{tag} t join s1 using(symbol) where t.src='s1' and s1.nty>1").fetchone())
    # nearest-in-time typed snapshot of the same security
    x(f"""create temp table near{tag} as
     select distinct on (t.symbol) t.symbol, a.ty near_ty, abs(a.as_of - '{d}'::date) gap
     from tm{tag} t join tev e on e.symbol=t.symbol join allsnap_full a on a.ticker=e.ticker and e.valid_from<=a.as_of and (e.valid_to is null or a.as_of<e.valid_to)
     where a.ty is not null order by t.symbol, abs(a.as_of - '{d}'::date), a.ty""")
    print("nearest-typed-snapshot type vs mode: agree/disagree/eligibility-disagree:", x(f"""select count(*) filter (where near_ty=strong_ty), count(*) filter (where near_ty<>strong_ty),
        count(*) filter (where (near_ty in {elig}) <> (strong_ty in {elig})) from tm{tag} t join near{tag} n using(symbol) where t.src='s1'""").fetchone())
    print("gap days to nearest typed snapshot (p50, p90, max):", x(f"select percentile_disc(0.5) within group (order by gap), percentile_disc(0.9) within group (order by gap), max(gap) from near{tag}").fetchone())
    print("members of 2008 recovered under nearest rule, eligible & n>=60 & close>=1:", x(f"select count(*) from tm{tag} t join near{tag} n using(symbol) where n.near_ty in {elig} and t.n>=60 and t.lastclose>=1").fetchone())
    print("strong-mode eligible & ok:", x(f"select count(*) from tm{tag} where strong_ty in {elig} and n>=60 and lastclose>=1").fetchone(),
          " both rules eligible & ok:", x(f"select count(*) from tm{tag} t join near{tag} n using(symbol) where n.near_ty in {elig} and t.strong_ty in {elig} and t.n>=60 and t.lastclose>=1").fetchone())
    # ticker-only weak: reuse check = overview figi exists and differs from the symbol's own figi, or cik differs
    print("weak candidates with overview cik == snapshot cik:", x(f"select count(distinct t.symbol) from tm{tag} t join s2w w using(symbol) where t.strong_ty is null and t.scik is not null and t.scik=w.ocik").fetchone(),
          " with snapshot cik null:", x(f"select count(distinct t.symbol) from tm{tag} t join s2w w using(symbol) where t.strong_ty is null and t.scik is null").fetchone())
    # raw Massive over floor vs canonical
x("""create temp table rawc as
select r.symbol, count(*) n, percentile_disc(0.5) within group (order by r.close*r.volume) med from
 (select symbol, close, volume, row_number() over (partition by symbol order by timestamp desc) rn from ohlcv_raw where timeframe='1d' and vendor='massive' and timestamp>='2008-02-01' and timestamp<'2008-07-01') r
where rn<=60 group by 1""")
print("raw massive 1d over floor (n>=60) at 2008-06-30:", x("select count(*) from rawc where med>=1000000 and n>=60").fetchone(),
      " of which in canonical cand08:", x("select count(*) from rawc where med>=1000000 and n>=60 and symbol in (select symbol from cand08)").fetchone(),
      " in placed (tev at D) :", x("select count(*) from rawc where med>=1000000 and n>=60 and symbol in (select symbol from tev where valid_from<='2008-06-30' and (valid_to is null or '2008-06-30'<valid_to))").fetchone())

print("######## pass 3")
print("securities whose own types straddle eligible/ineligible:", x("""select count(*) from (select e.symbol from allsnap_full a join tev e on e.ticker=a.ticker and e.valid_from<=a.as_of and (e.valid_to is null or a.as_of<e.valid_to)
  where a.ty is not null group by 1 having bool_or(a.ty in ('CS','ADRC','ETF')) and bool_or(a.ty not in ('CS','ADRC','ETF'))) q""").fetchone())
x("""create temp table nmx as select s.symbol, (select a.nm from allsnap_full a join tev e on e.ticker=a.ticker and e.symbol=s.symbol and e.valid_from<=a.as_of and (e.valid_to is null or a.as_of<e.valid_to) order by a.as_of desc limit 1) nm
 from secs s where s.symbol not in (select symbol from s1) and s.symbol not in (select symbol from s1f)""")
rx="""case when upper(nm) ~ '(\\mWT\\M|\\mWTS\\M|WARRANT)' then 'warrant' when upper(nm) ~ '(\\mUNIT\\M|\\mUNITS\\M)' then 'unit' when upper(nm) ~ '(\\mRIGHTS?\\M|\\mRTS\\M)' then 'right' when upper(nm) ~ '(\\mPFD\\M|PREFERRED|\\mPRF\\M)' then 'preferred' else 'other' end"""
print("all-years untyped remainder (no s1, no s1f) classes:", x(f"select {rx} c, count(*) from nmx group by 1 order by 2 desc").fetchall())
print("... of which have an overview type (ticker-only):", x("select coalesce(count(distinct symbol),0) from s2w where symbol in (select symbol from nmx)").fetchone())
print("name-pattern precision on typed snapshot rows 2008-06-30 (class -> eligible share):", x(f"""select c, count(*), round(avg((ty in ('CS','ADRC','ETF'))::int)::numeric,3) from (select ty, {rx} c from (select ty, nm from snap08 where ty is not null) q(ty,nm)) z group by 1 order by 2 desc""").fetchall())
print("untyped 2008 snapshot rows are active=", x("select act, count(*) from allsnap_full where as_of='2008-06-30' and ty is null group by 1").fetchall(), " typed:", x("select act, count(*) from allsnap_full where as_of='2008-06-30' and ty is not null group by 1").fetchall())
print("untyped share by year (typed / all rows) at June snapshots:", x("select extract(year from as_of)::int y, count(ty), count(*) from allsnap_full where extract(month from as_of)=6 group by 1 order by 1").fetchall())

print("######## pass 4 INDEX")
for tag,d in (("08","2008-06-30"),("12","2012-06-29"),("16","2016-09-30")):
    x(f"""create temp table ix{tag} as select n.symbol, n.ticker, n.nm, n.med, n.ty,
      (select mode() within group (order by a.ty) from allsnap_full a join tev e on e.ticker=a.ticker and e.symbol=n.symbol and e.valid_from<=a.as_of and (e.valid_to is null or a.as_of<e.valid_to) where a.ty is not null and a.ty<>'INDEX') other_ty,
      (select count(*) from allsnap_full a join tev e on e.ticker=a.ticker and e.symbol=n.symbol and e.valid_from<=a.as_of and (e.valid_to is null or a.as_of<e.valid_to) where a.ty='INDEX') n_index_rows,
      (select count(*) from allsnap_full a join tev e on e.ticker=a.ticker and e.symbol=n.symbol and e.valid_from<=a.as_of and (e.valid_to is null or a.as_of<e.valid_to) where a.ty is not null and a.ty<>'INDEX') n_other_rows,
      (select o.ty from ov o join tev e on e.ticker=o.ticker and e.symbol=n.symbol where o.ty is not null limit 1) ov_ty
      from nm{tag} n where n.ty='INDEX' and n.reason='type_ineligible'""")
    print("=====", d, "INDEX-labelled over-floor non-members:", x(f"select count(*) from ix{tag}").fetchone())
    print(" same security other typed rows (mode):", x(f"select coalesce(other_ty,'none'), count(*) from ix{tag} group by 1 order by 2 desc").fetchall())
    print(" overview type:", x(f"select coalesce(ov_ty,'none'), count(*) from ix{tag} group by 1 order by 2 desc").fetchall())
    print(" always INDEX (no other typed rows, overview not eligible):", x(f"select count(*) from ix{tag} where other_ty is null and coalesce(ov_ty,'INDEX') not in ('CS','ADRC','ETF')").fetchone(),
          " other_ty or overview eligible:", x(f"select count(*) from ix{tag} where other_ty in ('CS','ADRC','ETF') or ov_ty in ('CS','ADRC','ETF')").fetchone())
    print(" sample names:", x(f"select ticker, left(nm,32), other_ty, ov_ty from ix{tag} order by med desc limit 6").fetchall())
print("INDEX rows by snapshot year-end (INDEX rows / typed rows):", x("select extract(year from as_of)::int y, count(*) filter (where ty='INDEX'), count(ty) from allsnap_full where extract(month from as_of)=12 group by 1 order by 1").fetchall())
# third date counts
print("16 pass-3 summary:", x("select reason, count(*) from nm16 group by 1 order by 2 desc").fetchall(), x("select count(*) from universe_membership where as_of='2016-09-30'").fetchone(), x("select count(*) from cand16").fetchone())

print("######## pass 5 straddle pairs")
print(x("""select (array_agg(distinct ty order by ty))::text types, count(*) from (
   select e.symbol, a.ty from allsnap_full a join tev e on e.ticker=a.ticker and e.valid_from<=a.as_of and (e.valid_to is null or a.as_of<e.valid_to) where a.ty is not null) q
  group by symbol having bool_or(ty in ('CS','ADRC','ETF')) and bool_or(ty not in ('CS','ADRC','ETF')) order by 2 desc limit 0""").fetchall())
rows=x("""with t as (select e.symbol, array_agg(distinct a.ty order by a.ty) tys from allsnap_full a join tev e on e.ticker=a.ticker and e.valid_from<=a.as_of and (e.valid_to is null or a.as_of<e.valid_to) where a.ty is not null group by 1)
 select tys::text, count(*) from t where cardinality(tys)>1 and (tys && array['CS','ADRC','ETF']) and (exists (select 1 from unnest(tys) u where u not in ('CS','ADRC','ETF'))) group by 1 order by 2 desc limit 14""").fetchall()
for r in rows: print(r)

print("######## pass 6 INDEX resolution")
for tag,d in (("08","2008-06-30"),("12","2012-06-29"),("16","2016-09-30")):
    print("=====", d, x(f"select count(*) from ix{tag}").fetchone())
    print(" resolved by other own typed rows (mode, non-INDEX):", x(f"select other_ty, count(*) from ix{tag} where other_ty is not null group by 1 order by 2 desc").fetchall())
    print(" no own other row, overview type:", x(f"select coalesce(ov_ty,'none'), count(*) from ix{tag} where other_ty is null group by 1 order by 2 desc").fetchall())
    print(" own other row and overview disagree:", x(f"select count(*) from ix{tag} where other_ty is not null and ov_ty is not null and other_ty<>ov_ty").fetchone(),
          x(f"select other_ty, ov_ty, count(*) from ix{tag} where other_ty is not null and ov_ty is not null and other_ty<>ov_ty group by 1,2 order by 3 desc limit 5").fetchall())
    print(" unresolved (no other row, no non-INDEX overview) names:", x(f"select ticker, left(nm,40) from ix{tag} where other_ty is null and coalesce(ov_ty,'INDEX')='INDEX' limit 12").fetchall())
print("INDEX labels at 2016-09-30 snapshot:", x("select count(*) from allsnap_full where as_of='2016-09-30' and ty='INDEX'").fetchone())

print("######## pass 7 remainder reach")
x("create temp table rem as select symbol from secs where symbol not in (select symbol from s1)")
print("remainder (no own typed snapshot row):", x("select count(*) from rem").fetchone())
print(" with a composite_figi identifier:", x("select count(distinct symbol) from symfigi where symbol in (select symbol from rem)").fetchone())
print(" with a figi seen in any snapshot row:", x("select count(distinct f.symbol) from symfigi f join allsnap_full a on a.figi=f.figi where f.symbol in (select symbol from rem)").fetchone())
print(" with an ISIN identifier:", x("select count(distinct symbol) from security_identifier where scheme='isin' and symbol in (select symbol from rem)").fetchone())
print(" with a cik (any snapshot row via ticker span):", x("select count(distinct e.symbol) from allsnap_full a join tev e on e.ticker=a.ticker and e.valid_from<=a.as_of and (e.valid_to is null or a.as_of<e.valid_to) where a.cik is not null and e.symbol in (select symbol from rem)").fetchone())
print(" overview record exists (ticker held at any time), typed / untyped:", x("select count(distinct t.symbol) filter (where o.ty is not null), count(distinct t.symbol) filter (where o.ty is null) from tev t join ov o on o.ticker=t.ticker where t.symbol in (select symbol from rem)").fetchone())
print(" no overview record at all:", x("select count(*) from rem where symbol not in (select t.symbol from tev t join ov o on o.ticker=t.ticker)").fetchone())
