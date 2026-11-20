import sys, re, collections, psycopg
sys.path.insert(0,"/tmp/claude-1000/-home-bg-dev-indicagent/124b6b57-0ca7-4853-a5b9-6c6096c5b23a/scratchpad/wtb3")
from src.intelligence.security_type import resolve_security_type
conn=psycopg.connect("postgresql://postgres:postgres@localhost/indicagent", autocommit=True); x=conn.execute
x("set statement_timeout='900s'")
x("""create temp table own as
select e.symbol, a.ty, count(*) n, max(a.as_of) last_as_of, (array_agg(a.nm order by a.as_of desc))[1] nm
from (select r.as_of, e->>'ticker' ticker, e->>'type' ty, e->>'name' nm from reference_raw_current r, jsonb_array_elements(case when jsonb_typeof(r.body->'results')='array' then r.body->'results' else '[]'::jsonb end) e where r.endpoint='pit_snapshots' and r.http_status=200) a
join ticker_event e on e.vendor='massive' and e.retired_at is null and e.ticker=a.ticker and e.valid_from<=a.as_of and (e.valid_to is null or a.as_of<e.valid_to)
group by 1,2""")
lab=collections.defaultdict(dict); names={}
for sym,ty,n,la,nm in x("select symbol, ty, n, last_as_of, nm from own").fetchall():
    if ty is not None: lab[sym][ty]=n
    names.setdefault(sym,[]).append((la,nm))
names={s:max(v)[1] for s,v in names.items()}
res={s:resolve_security_type(l) for s,l in lab.items()}
elig={"CS","ADRC","ETF"}
c=collections.Counter(t for t,_ in res.values()); print("resolved types:", c.most_common())
print("typed securities", len(res), " conflicts", sum(1 for _,k in res.values() if k), " eligible", sum(1 for t,_ in res.values() if t in elig))
# frozen fallback (declared before looking), bar precision >= 0.99
EXC=re.compile(r"\bWT\b|\bWTS\b|WARRANT|\bRTS?\b|RIGHTS?\b|\bUNITS?\b|\bPFD\b|PREFERRED|\bPRF\b|\bNOTES?\b|DEPOSITARY|\bETN\b|\bSR\b|DEBENTURE|\bPFD\b")
INC=re.compile(r"\bCOM\b|COMMON|\bORD\b|ORDINARY|\bSHS\b|\bADS\b|\bADR\b|\bETF\b")
for nm_,pred in (("A: not excluded",lambda n: not EXC.search(n)),("B: not excluded and common-stock word",lambda n: not EXC.search(n) and bool(INC.search(n)))):
    tp=fp=0
    for s,(t,_) in res.items():
        n=(names.get(s) or "").upper()
        if pred(n):
            if t in elig: tp+=1
            else: fp+=1
    tot_e=sum(1 for t,_ in res.values() if t in elig)
    print(nm_, "predicted eligible", tp+fp, "precision", round(tp/(tp+fp),4), "recall", round(tp/tot_e,4))
# residual by year and survivor status
x("create temp table res(symbol text, ty text)")
with conn.cursor() as cur:
    cur.executemany("insert into res values (%s,%s)",[(s,t) for s,(t,_) in res.items()])
print("year, placed-at-Dec-31 securities with a bar that year, untyped (survivor, dead):")
for y in (2004,2008,2012,2016,2020,2024):
    d=f"{y}-12-31"
    r=x(f"""with p as (select distinct e.symbol from ticker_event e where e.vendor='massive' and e.retired_at is null and e.valid_from<='{d}' and (e.valid_to is null or '{d}'<e.valid_to)),
      b as (select distinct symbol from market_data_ohlcv_tradeable where timeframe='1d' and timestamp>='{y}-10-01' and timestamp<'{y+1}-01-01')
      select count(*), count(*) filter (where res.ty is null and i.is_active), count(*) filter (where res.ty is null and not i.is_active),
             count(*) filter (where i.is_active), count(*) filter (where not i.is_active)
      from p join b using(symbol) join instruments i using(symbol) left join res using(symbol)""").fetchone()
    print(y, r)

print("######## fallback B robustness and reach")
act={r[0]:r[1] for r in x("select symbol, is_active from instruments").fetchall()}
lastyr={r[0]:r[1] for r in x("select symbol, max(last_as_of) from own group by 1").fetchall()}
def B(n): return not EXC.search(n) and bool(INC.search(n))
def slice_(name,f):
    tp=fp=0
    for s,(t,_) in res.items():
        if f(s) and B((names.get(s) or "").upper()):
            if t in elig: tp+=1
            else: fp+=1
    print(name, "n", tp+fp, "precision", round(tp/max(tp+fp,1),4))
slice_("dead (inactive) typed", lambda s: act.get(s) is False)
slice_("typed, last list before 2013", lambda s: lastyr[s].year<2013)
slice_("typed, dead and last list before 2013", lambda s: act.get(s) is False and lastyr[s].year<2013)
x("create temp table untyped as select symbol from instruments where symbol in (select distinct symbol from ticker_event where vendor='massive' and retired_at is null) and symbol not in (select symbol from res)")
nm_all={r[0]:r[1] for r in x("""select e.symbol, (array_agg(a.nm order by a.as_of desc))[1] from (select r.as_of, e->>'ticker' ticker, e->>'name' nm from reference_raw_current r, jsonb_array_elements(case when jsonb_typeof(r.body->'results')='array' then r.body->'results' else '[]'::jsonb end) e where r.endpoint='pit_snapshots' and r.http_status=200) a join ticker_event e on e.vendor='massive' and e.retired_at is null and e.ticker=a.ticker and e.valid_from<=a.as_of and (e.valid_to is null or a.as_of<e.valid_to) where e.symbol in (select symbol from untyped) group by 1""").fetchall()}
print("untyped securities:", len(nm_all), " fallback B would type eligible:", sum(1 for s,n in nm_all.items() if B((n or "").upper())))
